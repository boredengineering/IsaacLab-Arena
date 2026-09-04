# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the GR00T activation probes.

Loading a real 3B checkpoint is not viable in a unit test, so these build a stand-in with the same
module topology the probes navigate: a ``backbone`` returning image-masked features, and an
``action_head`` whose ``model.transformer_blocks`` alternate self- and cross-attention exactly as
``AlternateVLDiT.forward`` does. The probes only ever touch that surface, so a topology match is
the property under test.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from isaaclab_arena.agentic_environment_generation.policy_activation_probe import (  # noqa: E402
    Gr00tActivationProbe,
    _block_role,
    measure_ablation_sensitivity,
    measure_action_chunk_dynamics,
    probe_policy_inference,
)

HIDDEN = 8
SEQ = 4
HORIZON = 6
ACTION_DIM = 3
NUM_BLOCKS = 8


class _BackboneOutput(dict):
    """Stands in for the ``BatchFeature`` the real backbone returns."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class _Backbone(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.project = torch.nn.Linear(HIDDEN, HIDDEN)

    def forward(self, inputs):
        features = self.project(inputs["features"])
        image_mask = torch.zeros(features.shape[:2], dtype=torch.bool)
        image_mask[:, : SEQ // 2] = True
        return _BackboneOutput(backbone_features=features, image_mask=image_mask)


class _Block(torch.nn.Module):
    """A residual block whose update magnitude is controllable, mirroring a DiT block's signature."""

    def __init__(self, gain: float):
        super().__init__()
        self.gain = gain
        self.linear = torch.nn.Linear(HIDDEN, HIDDEN)

    def forward(
        self,
        hidden_states,
        attention_mask=None,
        encoder_hidden_states=None,
        encoder_attention_mask=None,
        temb=None,
    ):
        return hidden_states + self.gain * torch.tanh(self.linear(hidden_states))


class _Dit(torch.nn.Module):
    def __init__(self, image_gain: float):
        super().__init__()
        # Match AlternateVLDiT parity: odd blocks self-attend, even blocks cross-attend, and every
        # 4th block (2 * attend_text_every_n_blocks) attends to text rather than image tokens.
        gains = []
        for index in range(NUM_BLOCKS):
            if index % 2 == 1:
                gains.append(0.5)
            elif index % 4 == 0:
                gains.append(0.4)
            else:
                gains.append(image_gain)
        self.transformer_blocks = torch.nn.ModuleList(_Block(gain) for gain in gains)


class _HeadConfig:
    use_alternate_vl_dit = True
    attend_text_every_n_blocks = 2


class _ActionHead(torch.nn.Module):
    def __init__(self, image_gain: float):
        super().__init__()
        self.config = _HeadConfig()
        self.model = _Dit(image_gain)
        self.vlln = torch.nn.LayerNorm(HIDDEN)
        self.action_decoder = torch.nn.Linear(HIDDEN, ACTION_DIM)


class _FakeGr00t(torch.nn.Module):
    """Minimal model exposing the surface the probes require.

    Args:
        image_gain: Contribution of the image cross-attention blocks. Low values emulate collapsed
            visual conditioning.
        vision_weight: How strongly the predicted chunk depends on the image input. Zero emulates a
            policy that ignores vision entirely.
        chunk_scale: Overall magnitude of the predicted trajectory. Zero emulates output collapse.
    """

    def __init__(self, image_gain: float = 0.5, vision_weight: float = 1.0, chunk_scale: float = 1.0):
        super().__init__()
        self.backbone = _Backbone()
        self.action_head = _ActionHead(image_gain)
        self.vision_weight = vision_weight
        self.chunk_scale = chunk_scale

    def get_action(self, inputs, options=None):
        backbone_out = self.backbone(inputs)
        hidden = self.action_head.vlln(backbone_out.backbone_features)
        for block in self.action_head.model.transformer_blocks:
            hidden = block(hidden, encoder_hidden_states=backbone_out.backbone_features)

        # A seeded noise draw, so repeated calls differ exactly as the flow-matching head's do.
        noise = torch.randn(1, HORIZON, ACTION_DIM)
        # Read a spatially weighted statistic, not the plain mean: a real vision-conditioned policy
        # depends on where things are, which is exactly what the scramble ablation removes.
        image = inputs["video.ego_view"].float().reshape(-1)
        weights = torch.linspace(0.0, 1.0, image.numel())
        image_term = self.vision_weight * float((image * weights).mean())
        ramp = torch.linspace(0.0, 1.0, HORIZON).view(1, HORIZON, 1)
        trajectory = self.chunk_scale * ramp * (1.0 + image_term)
        prompt_term = 0.0
        if isinstance(inputs.get("annotation.human.task_description"), str):
            prompt_term = 0.5 * len(inputs["annotation.human.task_description"]) / 50.0
        return _BackboneOutput(action_pred=trajectory + 0.05 * noise + prompt_term)


def _observation() -> dict:
    # A spatially structured frame, so a permutation ablation actually removes information.
    frame = torch.linspace(0.0, 1.0, 4 * 4 * 3).reshape(1, 4, 4, 3)
    return {
        "features": torch.randn(1, SEQ, HIDDEN),
        "video.ego_view": frame,
        "annotation.human.task_description": "pick up the red apple and place it on the plate",
        "state": torch.zeros(1, 1, ACTION_DIM),
    }


def test_block_role_matches_alternate_vl_dit_parity():
    """Role classification must mirror the branch structure in AlternateVLDiT.forward."""
    roles = [_block_role(index, attend_text_every_n_blocks=2) for index in range(8)]
    assert roles == [
        "text_cross_attention",
        "self_attention",
        "image_cross_attention",
        "self_attention",
        "text_cross_attention",
        "self_attention",
        "image_cross_attention",
        "self_attention",
    ]


def test_probe_records_every_block_and_removes_its_hooks():
    model = _FakeGr00t()
    with Gr00tActivationProbe(model) as probe:
        model.get_action(_observation())
        report = probe.report()

    assert len(report.block_conditioning_deltas) == NUM_BLOCKS
    assert all(delta.call_count == 1 for delta in report.block_conditioning_deltas)
    assert not probe._handles, "hooks must be removed on context exit or they leak across rollouts"

    roles = report.contribution_by_role()
    assert set(roles) == {"self_attention", "image_cross_attention", "text_cross_attention"}


def test_probe_averages_over_repeated_denoising_calls():
    """Hooks fire once per block per denoising step; statistics must average, not accumulate."""
    model = _FakeGr00t()
    with Gr00tActivationProbe(model) as probe:
        for _ in range(3):
            model.get_action(_observation())
        report = probe.report()

    assert all(delta.call_count == 3 for delta in report.block_conditioning_deltas)
    assert all(0.0 < delta.mean_relative_delta < 2.0 for delta in report.block_conditioning_deltas)


def test_collapsed_image_conditioning_is_detected():
    healthy = _FakeGr00t(image_gain=0.6)
    collapsed = _FakeGr00t(image_gain=0.001)

    with Gr00tActivationProbe(healthy) as probe:
        healthy.get_action(_observation())
        healthy_ratio = probe.report().image_conditioning_ratio()
    with Gr00tActivationProbe(collapsed) as probe:
        collapsed.get_action(_observation())
        collapsed_report = probe.report()

    assert healthy_ratio is not None and healthy_ratio > 0.15
    assert collapsed_report.image_conditioning_ratio() < 0.15

    supported = {mode for obs in collapsed_report.to_observations() for mode in obs.supports}
    assert "policy_output_collapse" in supported
    assert "vision_domain_ood" in supported


def test_image_token_statistics_use_the_image_mask():
    model = _FakeGr00t()
    with Gr00tActivationProbe(model) as probe:
        model.get_action(_observation())
        stats = probe.report().vl_embedding_stats

    assert stats["image_token_count"] == float(SEQ // 2)
    assert stats["image_token_mean_norm"] > 0.0


def test_corpus_centroid_yields_an_ood_distance():
    model = _FakeGr00t()
    centroid = torch.ones(HIDDEN)
    with Gr00tActivationProbe(model, corpus_image_centroid=centroid) as probe:
        model.get_action(_observation())
        stats = probe.report().vl_embedding_stats

    assert "cosine_distance_to_corpus_centroid" in stats
    assert 0.0 <= stats["cosine_distance_to_corpus_centroid"] <= 2.0


def test_mismatched_centroid_is_reported_not_silently_dropped():
    model = _FakeGr00t()
    with Gr00tActivationProbe(model, corpus_image_centroid=torch.ones(HIDDEN + 5)) as probe:
        model.get_action(_observation())
        report = probe.report()

    assert "cosine_distance_to_corpus_centroid" not in report.vl_embedding_stats
    assert any("does not match" in note for note in report.notes)


def test_chunk_dynamics_separate_a_static_chunk_from_a_moving_one():
    moving = measure_action_chunk_dynamics(_FakeGr00t(chunk_scale=1.0), _observation(), seed=0)
    static = measure_action_chunk_dynamics(_FakeGr00t(chunk_scale=0.0), _observation(), seed=0)

    assert moving["action_horizon"] == float(HORIZON)
    assert moving["chunk_displacement_l2"] > static["chunk_displacement_l2"]
    assert moving["mean_step_norm"] > 0.0


def test_seeding_makes_repeated_predictions_identical():
    """Ablation deltas are only meaningful if the noise draw is held fixed between calls."""
    model = _FakeGr00t()
    observation = _observation()
    first = measure_action_chunk_dynamics(model, observation, seed=7)
    second = measure_action_chunk_dynamics(model, observation, seed=7)
    assert first["chunk_displacement_l2"] == pytest.approx(second["chunk_displacement_l2"], abs=1e-9)

    different = measure_action_chunk_dynamics(model, observation, seed=8)
    assert different["chunk_displacement_l2"] != pytest.approx(first["chunk_displacement_l2"], abs=1e-9)


def test_vision_ablation_separates_a_seeing_policy_from_a_blind_one():
    """The causal check: blanking the image must move a vision-conditioned policy and not a blind one."""
    seeing = measure_ablation_sensitivity(_FakeGr00t(vision_weight=4.0), _observation(), seed=0)
    blind = measure_ablation_sensitivity(_FakeGr00t(vision_weight=0.0), _observation(), seed=0)

    assert seeing["sampling_noise_floor"] > 0.0, "noise floor must be non-zero or ratios are meaningless"
    assert seeing["vision_ablation_ratio"] > 0.5
    assert blind["vision_ablation_ratio"] < 0.5


def test_scramble_preserves_the_intensity_distribution():
    """The ablation must remove layout only; a brightness change would confound the delta."""
    from isaaclab_arena.agentic_environment_generation.policy_activation_probe import _scramble

    frame = torch.linspace(0.0, 1.0, 48).reshape(1, 4, 4, 3)
    scrambled = _scramble(frame, seed=0)

    assert scrambled.shape == frame.shape
    assert torch.equal(torch.sort(scrambled.reshape(-1)).values, torch.sort(frame.reshape(-1)).values)
    assert not torch.equal(scrambled, frame), "a permutation that changes nothing ablates nothing"
    assert torch.equal(_scramble(frame, seed=0), scrambled), "must be deterministic for a given seed"


def test_prompt_ablation_is_measured_when_a_corpus_instruction_is_supplied():
    result = measure_ablation_sensitivity(
        _FakeGr00t(),
        _observation(),
        corpus_instruction="move the apple to the plate",
        seed=0,
    )
    assert "prompt_ablation_ratio" in result
    assert result["prompt_ablation_delta"] >= 0.0


def test_full_battery_produces_belief_updating_observations():
    report = probe_policy_inference(
        _FakeGr00t(vision_weight=0.0, image_gain=0.001, chunk_scale=0.0),
        _observation(),
        corpus_instruction="move the apple to the plate",
    )
    observations = report.to_observations()
    metrics = {observation.metric for observation in observations}
    assert "image_cross_attention_contribution" in metrics
    assert "chunk_displacement_l2" in metrics
    assert "action_delta_under_image_ablation" in metrics

    # A blind, collapsed policy must produce evidence for collapse rather than against it.
    supported = {mode for observation in observations for mode in observation.supports}
    assert "policy_output_collapse" in supported
    assert report.to_dict()["image_conditioning_ratio"] is not None


def test_probe_reports_missing_topology_instead_of_failing():
    """A checkpoint without the expected submodules should degrade to notes, not raise."""

    class _Bare(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.action_head = torch.nn.Linear(2, 2)

    with Gr00tActivationProbe(_Bare()) as probe:
        report = probe.report()

    assert not report.block_conditioning_deltas
    assert report.image_conditioning_ratio() is None
    assert any("transformer_blocks" in note for note in report.notes)


def test_chunk_dynamics_accepts_a_numpy_action_output():
    """Gr00tPolicy returns un-transformed actions as numpy, and un-batched; both must work."""
    np = pytest.importorskip("numpy")

    class _NumpyPolicy(_FakeGr00t):
        def get_action(self, inputs, options=None):
            out = super().get_action(inputs, options)
            # Mimic Gr00tPolicy: numpy, and without the batch axis.
            return {"action": out["action_pred"].squeeze(0).cpu().numpy().astype(np.float32)}

    dynamics = measure_action_chunk_dynamics(_NumpyPolicy(chunk_scale=1.0), _observation(), seed=0)
    assert dynamics["action_horizon"] == float(HORIZON)
    assert dynamics["chunk_displacement_l2"] > 0.0

    ablation = measure_ablation_sensitivity(_NumpyPolicy(vision_weight=4.0), _observation(), seed=0)
    assert ablation["sampling_noise_floor"] > 0.0
    assert ablation["vision_ablation_ratio"] > 0.5


def test_probe_rejects_a_model_without_an_action_head():
    with pytest.raises(AssertionError, match="action_head"):
        Gr00tActivationProbe(torch.nn.Linear(2, 2))


def test_bank_verdict_supersedes_the_uncalibrated_cosine_distance():
    """With a calibrated bank the probe asserts; without one it explicitly asserts nothing."""
    from isaaclab_arena.agentic_environment_generation.corpus_embedding_bank import build_bank
    from isaaclab_arena.agentic_environment_generation.policy_activation_probe import VL_EMBEDDING_OOD_PERCENTILE

    model = _FakeGr00t()
    # The fake backbone emits HIDDEN-dim features; fit a bank on samples far from what it produces
    # so the observation reads as out of distribution.
    generator = torch.Generator().manual_seed(0)
    reference = torch.randn(120, HIDDEN, generator=generator) * 0.1 + 40.0
    bank = build_bank(reference, source="unit-test")

    with Gr00tActivationProbe(model, corpus_bank=bank) as probe:
        model.get_action(_observation())
        report = probe.report()

    assert "bank_is_ood" in report.vl_embedding_stats
    metrics = {observation.metric for observation in report.to_observations()}
    assert "corpus_embedding_ood_percentile" in metrics
    assert "cosine_distance_to_corpus_centroid" not in metrics, "bank verdict must supersede it"

    ood_observation = next(o for o in report.to_observations() if o.metric == "corpus_embedding_ood_percentile")
    assert ood_observation.reference == VL_EMBEDDING_OOD_PERCENTILE
    assert "vision_domain_ood" in ood_observation.supports


def test_without_a_bank_the_centroid_distance_supports_no_conclusion():
    """An uncalibrated distance must not move any belief."""
    model = _FakeGr00t()
    with Gr00tActivationProbe(model, corpus_image_centroid=torch.ones(HIDDEN)) as probe:
        model.get_action(_observation())
        report = probe.report()

    observation = next(o for o in report.to_observations() if o.metric == "cosine_distance_to_corpus_centroid")
    assert observation.supports == ()
    assert observation.refutes == ()
    assert observation.likelihood_ratio == 1.0, "a neutral ratio leaves the prior untouched"
    assert "supports no conclusion" in observation.note
