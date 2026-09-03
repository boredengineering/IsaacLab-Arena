# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Forward-hook probes that read a GR00T policy's internals during inference.

Behavioural metrics say a rollout failed. They cannot say whether the policy looked at the scene
and planned the wrong trajectory, or never conditioned on the image at all -- and those two faults
have different fixes. These probes separate them by reading activations instead of outcomes.

Four measurements, cheapest first:

* ``vl_embedding_stats`` -- statistics of the backbone's image tokens, the representation the
  action head actually consumes. Compares against a corpus centroid when one is supplied.
* ``block_conditioning_deltas`` -- how much each action-head transformer block moves the hidden
  state, bucketed into image cross-attention, text cross-attention, and self-attention. An image
  bucket contributing far less than the self-attention bucket means the trajectory is being
  generated with little reference to what the camera sees.
* ``action_chunk_dynamics`` -- displacement across the predicted horizon. A near-zero chunk means
  the policy is not attempting a trajectory, which is a different fault from attempting a bad one.
* ``ablation_sensitivity`` -- re-runs inference with the image (or the instruction) replaced and
  measures how far the predicted chunk moves. This is the causal check: a null delta proves the
  input is not being used, where an attention map only suggests it.

GR00T runs attention through fused kernels that never materialise the attention matrix, so hooking
a block's output cannot recover per-patch attention weights. The block-delta metric is the
attention-free stand-in: it measures the magnitude of the update each conditioning source induces,
which is what the collapse diagnosis actually needs.

Ablation deltas are normalised by the policy's own sampling noise. The flow-matching head starts
from Gaussian noise, so two identical calls differ by construction; a delta is only meaningful
relative to that floor. Every comparison re-seeds the generator so the noise draw is held fixed.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from isaaclab_arena.agentic_environment_generation.policy_capability_graph import ProbeObservation

# Fraction of the self-attention bucket's contribution below which image cross-attention counts
# as collapsed. Well under parity, so ordinary imbalance between buckets is not flagged.
IMAGE_CONDITIONING_COLLAPSE_RATIO = 0.15

# Predicted horizon displacement, in action units, below which a chunk counts as static.
STATIC_CHUNK_DISPLACEMENT = 1e-2

# Ablation delta as a multiple of the sampling-noise floor. Below this, the ablated input is not
# influencing the prediction any more than resampling the initial noise would.
ABLATION_INSENSITIVE_RATIO = 0.5

# Cosine distance from the corpus image-token centroid beyond which the observation is treated as
# out of distribution in the representation the action head consumes.
VL_EMBEDDING_OOD_DISTANCE = 0.35


@dataclass
class BlockConditioningDelta:
    """Relative hidden-state update contributed by one action-head transformer block."""

    block_index: int
    role: str
    """``image_cross_attention``, ``text_cross_attention``, or ``self_attention``."""

    mean_relative_delta: float
    call_count: int


@dataclass
class ProbeReport:
    """Everything the probes measured during one or more inference calls."""

    block_conditioning_deltas: list[BlockConditioningDelta] = field(default_factory=list)
    vl_embedding_stats: dict[str, float] = field(default_factory=dict)
    action_chunk_dynamics: dict[str, float] = field(default_factory=dict)
    ablation_sensitivity: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def contribution_by_role(self) -> dict[str, float]:
        """Mean relative hidden-state update per conditioning role."""
        totals: dict[str, list[float]] = {}
        for delta in self.block_conditioning_deltas:
            totals.setdefault(delta.role, []).append(delta.mean_relative_delta)
        return {role: sum(values) / len(values) for role, values in totals.items() if values}

    def image_conditioning_ratio(self) -> float | None:
        """Image cross-attention contribution as a fraction of the self-attention contribution.

        Returns None when the model did not expose both roles, e.g. a plain DiT action head with no
        image/text block split.
        """
        by_role = self.contribution_by_role()
        image = by_role.get("image_cross_attention")
        self_attn = by_role.get("self_attention")
        if image is None or not self_attn:
            return None
        return image / self_attn

    def to_observations(self) -> list[ProbeObservation]:
        """Convert the measurements into belief-updating evidence.

        Each observation names the failure modes it raises or lowers, so the result can be handed
        straight to ``PolicyDiagnosticState.apply_observations``.
        """
        observations: list[ProbeObservation] = []

        ratio = self.image_conditioning_ratio()
        if ratio is not None:
            collapsed = ratio < IMAGE_CONDITIONING_COLLAPSE_RATIO
            observations.append(
                ProbeObservation(
                    metric="image_cross_attention_contribution",
                    value=round(ratio, 5),
                    reference=IMAGE_CONDITIONING_COLLAPSE_RATIO,
                    technique_id="vl_conditioning_delta_probe",
                    supports=("vision_domain_ood", "policy_output_collapse") if collapsed else (),
                    refutes=() if collapsed else ("policy_output_collapse",),
                    likelihood_ratio=4.0,
                    note=(
                        f"Image cross-attention blocks move the hidden state {ratio:.3f}x as much as "
                        f"self-attention blocks."
                    ),
                )
            )

        displacement = self.action_chunk_dynamics.get("chunk_displacement_l2")
        if displacement is not None:
            static = displacement < STATIC_CHUNK_DISPLACEMENT
            observations.append(
                ProbeObservation(
                    metric="chunk_displacement_l2",
                    value=round(displacement, 6),
                    reference=STATIC_CHUNK_DISPLACEMENT,
                    technique_id="action_chunk_dynamics_probe",
                    supports=("policy_output_collapse",) if static else (),
                    refutes=("policy_output_collapse",) if not static else (),
                    likelihood_ratio=6.0,
                    note=(
                        f"Predicted chunk spans {displacement:.5f} action units across the horizon; the "
                        f"policy {'is not attempting' if static else 'is attempting'} a trajectory."
                    ),
                )
            )

        vision_ratio = self.ablation_sensitivity.get("vision_ablation_ratio")
        if vision_ratio is not None:
            insensitive = vision_ratio < ABLATION_INSENSITIVE_RATIO
            observations.append(
                ProbeObservation(
                    metric="action_delta_under_image_ablation",
                    value=round(vision_ratio, 5),
                    reference=ABLATION_INSENSITIVE_RATIO,
                    technique_id="vision_ablation_sensitivity",
                    supports=("vision_domain_ood", "policy_output_collapse") if insensitive else (),
                    refutes=() if insensitive else ("vision_domain_ood", "policy_output_collapse"),
                    likelihood_ratio=8.0,
                    note=(
                        f"Blanking the camera image moves the predicted chunk {vision_ratio:.3f}x as much "
                        f"as resampling the initial noise. "
                        + (
                            "The policy is not conditioning on vision in this state."
                            if insensitive
                            else "The policy is conditioning on vision, so it sees the scene and still fails."
                        )
                    ),
                )
            )

        prompt_ratio = self.ablation_sensitivity.get("prompt_ablation_ratio")
        if prompt_ratio is not None:
            insensitive = prompt_ratio < ABLATION_INSENSITIVE_RATIO
            observations.append(
                ProbeObservation(
                    metric="action_delta_under_prompt_swap",
                    value=round(prompt_ratio, 5),
                    reference=ABLATION_INSENSITIVE_RATIO,
                    technique_id="prompt_token_ablation",
                    supports=("unconditioned_language",) if insensitive else ("prompt_token_ood",),
                    refutes=("prompt_token_ood",) if insensitive else ("unconditioned_language",),
                    likelihood_ratio=4.0,
                    note=(
                        f"Swapping in the corpus instruction moves the predicted chunk {prompt_ratio:.3f}x "
                        f"the noise floor."
                    ),
                )
            )

        distance = self.vl_embedding_stats.get("cosine_distance_to_corpus_centroid")
        if distance is not None:
            ood = distance > VL_EMBEDDING_OOD_DISTANCE
            observations.append(
                ProbeObservation(
                    metric="cosine_distance_to_corpus_centroid",
                    value=round(distance, 5),
                    reference=VL_EMBEDDING_OOD_DISTANCE,
                    technique_id="vl_embedding_ood_distance",
                    supports=("vision_domain_ood",) if ood else (),
                    refutes=("vision_domain_ood",) if not ood else (),
                    likelihood_ratio=5.0,
                    note=f"Image-token embeddings sit {distance:.3f} cosine from the corpus centroid.",
                )
            )

        return observations

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable view of the report."""
        return {
            "contribution_by_role": {role: round(value, 6) for role, value in self.contribution_by_role().items()},
            "image_conditioning_ratio": self.image_conditioning_ratio(),
            "block_conditioning_deltas": [
                {
                    "block_index": delta.block_index,
                    "role": delta.role,
                    "mean_relative_delta": round(delta.mean_relative_delta, 6),
                    "call_count": delta.call_count,
                }
                for delta in self.block_conditioning_deltas
            ],
            "vl_embedding_stats": {k: round(v, 6) for k, v in self.vl_embedding_stats.items()},
            "action_chunk_dynamics": {k: round(v, 6) for k, v in self.action_chunk_dynamics.items()},
            "ablation_sensitivity": {k: round(v, 6) for k, v in self.ablation_sensitivity.items()},
            "notes": list(self.notes),
        }


def _resolve_action_head(model: Any) -> Any:
    """Return the GR00T action head, unwrapping a policy wrapper if one is passed."""
    for attribute in ("action_head", "model.action_head", "policy.model.action_head"):
        current = model
        for part in attribute.split("."):
            current = getattr(current, part, None)
            if current is None:
                break
        if current is not None:
            return current
    raise AssertionError(
        "Could not locate an 'action_head' on the supplied model. Pass a Gr00tN1d7 module or a "
        "wrapper exposing '.model.action_head'."
    )


def _resolve_backbone(model: Any) -> Any | None:
    """Return the GR00T vision-language backbone if reachable, else None."""
    for attribute in ("backbone", "model.backbone", "policy.model.backbone"):
        current = model
        for part in attribute.split("."):
            current = getattr(current, part, None)
            if current is None:
                break
        if current is not None:
            return current
    return None


def _block_role(block_index: int, attend_text_every_n_blocks: int) -> str:
    """Classify an ``AlternateVLDiT`` block by the conditioning it attends to.

    Mirrors ``AlternateVLDiT.forward``: odd blocks self-attend, even blocks cross-attend, and every
    ``2 * attend_text_every_n_blocks``-th block cross-attends to text rather than image tokens.
    """
    if block_index % 2 == 1:
        return "self_attention"
    if block_index % max(2 * attend_text_every_n_blocks, 2) == 0:
        return "text_cross_attention"
    return "image_cross_attention"


class Gr00tActivationProbe:
    """Registers forward hooks over a GR00T action head and accumulates activation statistics.

    Use as a context manager so the hooks are always removed, including on error::

        with Gr00tActivationProbe(model) as probe:
            model.get_action(observation)
        report = probe.report()

    Hooks fire once per transformer block per denoising step, so statistics are averaged over every
    call made inside the context.
    """

    def __init__(self, model: Any, corpus_image_centroid: Any | None = None):
        """
        Args:
            model: A ``Gr00tN1d7`` module, or a wrapper exposing ``.model.action_head``.
            corpus_image_centroid: Optional 1-D tensor of mean image-token embeddings measured over
                the training corpus. When supplied, the probe reports cosine distance to it.
        """
        self._model = model
        self._action_head = _resolve_action_head(model)
        self._backbone = _resolve_backbone(model)
        self._corpus_image_centroid = corpus_image_centroid
        self._handles: list[Any] = []
        self._block_sums: dict[int, float] = {}
        self._block_counts: dict[int, int] = {}
        self._vl_stats: dict[str, float] = {}
        self._notes: list[str] = []

        head_config = getattr(self._action_head, "config", None)
        self._attend_text_every_n_blocks = int(getattr(head_config, "attend_text_every_n_blocks", 2) or 2)
        self._uses_alternate_vl_dit = bool(getattr(head_config, "use_alternate_vl_dit", False))

    def __enter__(self) -> Gr00tActivationProbe:
        self.register()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.remove()

    def register(self) -> None:
        """Attach the hooks. Idempotent -- a second call is a no-op while hooks are live."""
        if self._handles:
            return

        blocks = getattr(getattr(self._action_head, "model", None), "transformer_blocks", None)
        if blocks is None:
            self._notes.append(
                "Action head exposes no 'model.transformer_blocks'; per-block conditioning deltas unavailable."
            )
        else:
            for index, block in enumerate(blocks):
                self._handles.append(block.register_forward_hook(self._make_block_hook(index)))
            if not self._uses_alternate_vl_dit:
                self._notes.append(
                    "Action head is not an AlternateVLDiT, so blocks are not split by conditioning "
                    "source; per-role attribution is not meaningful for this checkpoint."
                )

        if self._backbone is not None:
            self._handles.append(self._backbone.register_forward_hook(self._backbone_hook))
        else:
            self._notes.append("Backbone not reachable; vision-language embedding statistics unavailable.")

    def remove(self) -> None:
        """Detach every hook. Always call this, or the handles leak across rollouts."""
        for handle in self._handles:
            handle.remove()
        self._handles = []

    def _make_block_hook(self, block_index: int):
        """Build a forward hook that records block ``block_index``'s relative hidden-state update."""
        import torch

        def hook(_module, args, output) -> None:
            if not args:
                return
            hidden_in = args[0]
            hidden_out = output[0] if isinstance(output, tuple) else output
            if not torch.is_tensor(hidden_in) or not torch.is_tensor(hidden_out):
                return
            if hidden_in.shape != hidden_out.shape:
                return
            with torch.no_grad():
                input_norm = torch.linalg.vector_norm(hidden_in.float())
                if float(input_norm) <= 0.0:
                    return
                relative = float(torch.linalg.vector_norm((hidden_out - hidden_in).float()) / input_norm)
            self._block_sums[block_index] = self._block_sums.get(block_index, 0.0) + relative
            self._block_counts[block_index] = self._block_counts.get(block_index, 0) + 1

        return hook

    def _backbone_hook(self, _module, _args, output) -> None:
        """Record image-token embedding statistics from the backbone's output features."""
        import torch

        features = getattr(output, "backbone_features", None)
        if features is None and isinstance(output, dict):
            features = output.get("backbone_features")
        if features is None or not torch.is_tensor(features):
            return

        image_mask = getattr(output, "image_mask", None)
        if image_mask is None and isinstance(output, dict):
            image_mask = output.get("image_mask")

        with torch.no_grad():
            features = features.float()
            if torch.is_tensor(image_mask) and image_mask.shape[:2] == features.shape[:2]:
                selected = features[image_mask.bool()]
                self._vl_stats["image_token_count"] = float(selected.shape[0])
            else:
                selected = features.reshape(-1, features.shape[-1])
                self._notes.append("No usable image_mask on backbone output; pooling over all tokens.")
            if selected.numel() == 0:
                return

            self._vl_stats["image_token_mean_norm"] = float(torch.linalg.vector_norm(selected, dim=-1).mean())
            self._vl_stats["image_token_activation_std"] = float(selected.std())

            pooled = selected.mean(dim=0)
            if self._corpus_image_centroid is not None:
                centroid = self._corpus_image_centroid.to(device=pooled.device, dtype=pooled.dtype)
                if centroid.shape == pooled.shape:
                    similarity = float(
                        torch.nn.functional.cosine_similarity(pooled.unsqueeze(0), centroid.unsqueeze(0)).squeeze()
                    )
                    self._vl_stats["cosine_distance_to_corpus_centroid"] = 1.0 - similarity
                else:
                    self._notes.append(
                        f"Corpus centroid shape {tuple(centroid.shape)} does not match pooled embedding "
                        f"shape {tuple(pooled.shape)}; OOD distance skipped."
                    )

    def report(self) -> ProbeReport:
        """Return the statistics accumulated since ``register``."""
        deltas = [
            BlockConditioningDelta(
                block_index=index,
                role=_block_role(index, self._attend_text_every_n_blocks)
                if self._uses_alternate_vl_dit
                else "unclassified",
                mean_relative_delta=self._block_sums[index] / max(self._block_counts[index], 1),
                call_count=self._block_counts[index],
            )
            for index in sorted(self._block_sums)
        ]
        return ProbeReport(
            block_conditioning_deltas=deltas,
            vl_embedding_stats=dict(self._vl_stats),
            notes=list(self._notes),
        )


# ---------------------------------------------------------------------------
# Chunk dynamics and ablation
# ---------------------------------------------------------------------------


def _predict_chunk(model: Any, observation: dict[str, Any], seed: int) -> Any:
    """Run one seeded inference call and return the predicted action chunk as a tensor.

    Seeding is what makes ablation comparisons valid: the flow-matching head starts from a Gaussian
    draw, so without a fixed seed the difference between two calls is dominated by sampling noise.
    """
    import torch

    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    with torch.no_grad():
        output = model.get_action(copy.deepcopy(observation))

    chunk = getattr(output, "action_pred", None)
    if chunk is None and isinstance(output, dict):
        chunk = output.get("action_pred") or output.get("action")
    assert chunk is not None, "Model output carries no 'action_pred'; cannot measure chunk dynamics."

    if not torch.is_tensor(chunk):
        # Gr00tPolicy.get_action returns un-transformed actions as numpy; the raw Gr00tN1d7 returns
        # a tensor. Probing at the Gr00tPolicy level is preferred, so accept both.
        import numpy as np

        chunk = torch.as_tensor(np.asarray(chunk))
    if chunk.ndim == 2:
        # A single un-batched (horizon, action_dim) chunk; add the batch axis the metrics expect.
        chunk = chunk.unsqueeze(0)
    return chunk.float()


def measure_action_chunk_dynamics(model: Any, observation: dict[str, Any], seed: int = 0) -> dict[str, float]:
    """Measure how much of a trajectory the policy is actually proposing.

    Args:
        model: A GR00T model exposing ``get_action``.
        observation: One observation dict, as passed to ``get_action``.
        seed: Seed for the initial noise draw.

    Returns:
        Horizon displacement, mean per-step step size, and the largest single-step jump. A tiny
        displacement distinguishes "not attempting a trajectory" from "attempting a wrong one".
    """
    import torch

    chunk = _predict_chunk(model, observation, seed)
    with torch.no_grad():
        horizon = chunk.shape[1] if chunk.ndim >= 2 else 1
        displacement = float(torch.linalg.vector_norm(chunk[:, -1] - chunk[:, 0])) if horizon > 1 else 0.0
        steps = torch.diff(chunk, dim=1) if horizon > 1 else torch.zeros_like(chunk)
        step_norms = torch.linalg.vector_norm(steps, dim=-1)
        return {
            "action_horizon": float(horizon),
            "chunk_displacement_l2": displacement,
            "mean_step_norm": float(step_norms.mean()) if step_norms.numel() else 0.0,
            "max_step_norm": float(step_norms.max()) if step_norms.numel() else 0.0,
            "chunk_abs_mean": float(chunk.abs().mean()),
        }


def _find_image_keys(observation: dict[str, Any]) -> list[str]:
    """Return the observation keys that carry camera frames."""
    return [
        key
        for key in observation
        if key.startswith("video.") or "image" in key.lower() or "cam" in key.lower() or key == "vlm_content"
    ]


def _scramble(value: Any, seed: int) -> Any:
    """Return ``value`` with its elements randomly permuted, or None if it is not an array.

    Permuting rather than blanking is what makes the ablation interpretable. A constant fill
    changes the image's brightness as well as its structure, so a resulting action delta cannot be
    attributed to either; worse, filling with the image's own mean leaves every global statistic
    intact and is invisible to a policy that reads them. A permutation holds the intensity
    distribution exactly fixed and removes only spatial layout, so the delta measures dependence on
    spatial content specifically. Layout-agnostic: it does not need to know NCHW from NHWC.
    """
    import torch

    if torch.is_tensor(value):
        generator = torch.Generator(device="cpu").manual_seed(seed)
        flat = value.reshape(-1)
        permutation = torch.randperm(flat.numel(), generator=generator).to(flat.device)
        return flat[permutation].reshape(value.shape)

    if hasattr(value, "shape") and hasattr(value, "reshape") and hasattr(value, "dtype"):
        try:
            import numpy as np

            rng = np.random.default_rng(seed)
            flat = np.asarray(value).reshape(-1).copy()
            rng.shuffle(flat)
            return flat.reshape(value.shape)
        except ImportError:
            return None

    return None


def measure_ablation_sensitivity(
    model: Any,
    observation: dict[str, Any],
    corpus_instruction: str | None = None,
    seed: int = 0,
    alternate_seed: int = 1,
) -> dict[str, float]:
    """Measure how much the predicted chunk depends on the image, and on the instruction.

    Runs the same observation under a fixed noise draw against a spatially scrambled copy, and
    reports the resulting action delta relative to the policy's own sampling-noise floor. A ratio
    near zero is causal evidence the input is not being used -- the cleanest way to tell "the policy
    cannot see the scene" apart from "the policy sees it and still fails".

    Args:
        model: A GR00T model exposing ``get_action``.
        observation: One observation dict, as passed to ``get_action``.
        corpus_instruction: When given, additionally re-runs with this instruction substituted to
            test whether the wording is load-bearing.
        seed: Seed held fixed across the baseline and ablated calls.
        alternate_seed: Second seed used to establish the sampling-noise floor.

    Returns:
        Raw deltas, the noise floor, and each delta as a multiple of that floor. Ratios are absent
        when the corresponding input could not be located in the observation.
    """
    import torch

    baseline = _predict_chunk(model, observation, seed)
    resampled = _predict_chunk(model, observation, alternate_seed)

    with torch.no_grad():
        noise_floor = float(torch.linalg.vector_norm(baseline - resampled))
    results: dict[str, float] = {"sampling_noise_floor": noise_floor}
    denominator = max(noise_floor, 1e-6)

    image_keys = _find_image_keys(observation)
    if image_keys:
        ablated = copy.deepcopy(observation)
        ablated_any = False
        for key in image_keys:
            scrambled = _scramble(ablated[key], seed)
            if scrambled is not None:
                ablated[key] = scrambled
                ablated_any = True
        if ablated_any:
            ablated_chunk = _predict_chunk(model, ablated, seed)
            with torch.no_grad():
                delta = float(torch.linalg.vector_norm(baseline - ablated_chunk))
            results["vision_ablation_delta"] = delta
            results["vision_ablation_ratio"] = delta / denominator

    if corpus_instruction is not None:
        swapped = copy.deepcopy(observation)
        instruction_keys = [
            key for key in swapped if "instruction" in key.lower() or "annotation" in key.lower() or key == "language"
        ]
        for key in instruction_keys:
            current = swapped[key]
            swapped[key] = [corpus_instruction] * len(current) if isinstance(current, list) else corpus_instruction
        if instruction_keys:
            swapped_chunk = _predict_chunk(model, swapped, seed)
            with torch.no_grad():
                delta = float(torch.linalg.vector_norm(baseline - swapped_chunk))
            results["prompt_ablation_delta"] = delta
            results["prompt_ablation_ratio"] = delta / denominator

    return results


def probe_policy_inference(
    model: Any,
    observation: dict[str, Any],
    corpus_instruction: str | None = None,
    corpus_image_centroid: Any | None = None,
    seed: int = 0,
) -> ProbeReport:
    """Run the full probe battery over a single observation and return one report.

    Args:
        model: A GR00T model exposing ``get_action``.
        observation: One observation dict, as passed to ``get_action``.
        corpus_instruction: Corpus instruction to test the prompt ablation against, if available.
        corpus_image_centroid: Mean corpus image-token embedding, if available.
        seed: Seed for the initial noise draw.

    Returns:
        A report whose ``to_observations()`` feeds straight into the belief state.
    """
    with Gr00tActivationProbe(model, corpus_image_centroid=corpus_image_centroid) as probe:
        dynamics = measure_action_chunk_dynamics(model, observation, seed=seed)
        report = probe.report()

    # Ablation runs outside the hook context: it makes several inference calls, and mixing them into
    # the per-block averages would blur the baseline the deltas are measured against.
    ablation = measure_ablation_sensitivity(
        model,
        observation,
        corpus_instruction=corpus_instruction,
        seed=seed,
    )

    report.action_chunk_dynamics = dynamics
    report.ablation_sensitivity = ablation
    return report
