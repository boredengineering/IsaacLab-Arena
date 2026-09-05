# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Measure which input modality a GR00T checkpoint conditions on, over corpus observations.

Answers the question a closed-loop success rate cannot: when a policy reaches but does not
complete a task in a new scene, is it looking at the scene at all? Each ablation delta is reported
as a multiple of the policy's own sampling-noise floor, so a ratio near 1.0 means the input made no
difference beyond resampling the flow-matching noise.

No simulator is required -- observations come from the demonstration corpus. The model is loaded
in-process rather than reached over ZeroMQ because the ablation needs the flow-matching noise draw
held fixed across the baseline and ablated calls, which a remote server does not expose.

Example:
    python probe_policy_modality.py \\
        --model-path /models/isaaclab_arena/static_apple_tutorial/gn1x_tuned_static_apple \\
        --dataset-path /datasets/isaaclab_arena/static_apple_tutorial/lerobot \\
        --modality-config-path isaaclab_arena_gr00t/embodiments/g1/g1_sim_wbc_data_gr00t_n_1_7_config.py \\
        --steps 0 60 120 --output eval_output/p2b_modality_ablation.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from isaaclab_arena.agentic_environment_generation.policy_activation_probe import (  # noqa: E402
    measure_ablation_sensitivity,
)


class _ChunkDictPolicy:
    """Adapts ``Gr00tPolicy.get_action`` to the flat chunk tensor the probe expects.

    ``Gr00tPolicy`` returns a ``(chunk_dict, metadata)`` tuple whose chunk is split across
    per-group ``action.<group>`` keys. The probe compares whole chunks by vector norm, so the
    groups are concatenated in a fixed key order to keep the comparison well defined.
    """

    def __init__(self, policy: Any, action_keys: list[str]):
        self._policy = policy
        self._action_keys = action_keys

    def get_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        import numpy as np

        from gr00t.eval.open_loop_eval import parse_action_gr00t

        raw = self._policy.get_action(observation)
        chunk = raw[0] if isinstance(raw, tuple) else raw
        parsed = parse_action_gr00t(chunk)
        columns = [np.atleast_2d(np.asarray(parsed[f"action.{key}"])) for key in self._action_keys]
        return {"action_pred": np.concatenate(columns, axis=-1)}


def _register_modality_config(path: Path) -> None:
    """Import a modality-config module so it registers itself against its embodiment tag."""
    assert path.exists(), f"modality config not found: {path}"
    sys.path.insert(0, str(path.parent))
    importlib.import_module(path.stem)


def _build_observation(traj: Any, step: int, modality_configs: Any, embodiment_tag: Any) -> dict[str, Any]:
    """Build one GR00T observation dict from a corpus trajectory at ``step``."""
    import numpy as np
    from copy import deepcopy

    from gr00t.data.dataset.sharded_single_step_dataset import extract_step_data
    from gr00t.data.utils import parse_observation_gr00t

    obs_configs = deepcopy(modality_configs)
    obs_configs.pop("action", None)
    data_point = extract_step_data(traj, step, obs_configs, embodiment_tag)

    obs: dict[str, Any] = {}
    for key, value in data_point.states.items():
        obs[f"state.{key}"] = value
    for key, value in data_point.images.items():
        obs[f"video.{key}"] = np.array(value)
    for language_key in modality_configs["language"].modality_keys:
        obs[language_key] = data_point.text
    return parse_observation_gr00t(obs, modality_configs)


_MODALITIES = ("vision", "state", "prompt")


def _aggregate_ratio(per_step: list[dict[str, Any]], prefix: str) -> dict[str, Any] | None:
    """Summarise one modality's ablation across steps, robustly.

    The per-step ratio divides by that step's sampling-noise floor, and that floor varies by an
    order of magnitude along a trajectory. Averaging the ratios therefore over-weights the steps
    where the denominator happened to be small. The pooled ratio -- total delta over total noise --
    and the median both avoid that, so all three are reported and disagreement between them is
    itself the signal that the mean is being driven by a few low-floor steps.

    Args:
        per_step: Per-observation ablation results.
        prefix: Result-key prefix, e.g. ``"vision_ablation"``.

    Returns:
        Median, pooled and mean ratios with the sample count, or None if the modality was absent.
    """
    ratios = [r[f"{prefix}_ratio"] for r in per_step if f"{prefix}_ratio" in r]
    if not ratios:
        return None
    deltas = [r[f"{prefix}_delta"] for r in per_step if f"{prefix}_delta" in r]
    floors = [r["sampling_noise_floor"] for r in per_step if f"{prefix}_delta" in r]
    total_floor = sum(floors)
    return {
        "median": statistics.median(ratios),
        "mean": statistics.fmean(ratios),
        "pooled": (sum(deltas) / total_floor) if total_floor > 0 else float("nan"),
        "n": len(ratios),
    }


def _verdict(vision: float | None, state: float | None) -> str:
    """Turn the two ratios into the phase decision the transfer plan branches on."""
    if vision is None:
        return "inconclusive: no image key found in the observation"
    if vision >= 2.0:
        return (
            "vision IS load-bearing. The fault is in what vision encodes for this scene, so "
            "photometric/appearance alignment is worth trying before a re-finetune."
        )
    # Below the bar, the state ratio only changes the wording, never the conclusion: photometric
    # alignment cannot help a policy whose actions the image barely moves, whether or not it is
    # leaning on proprioception instead.
    shortcut = (
        ""
        if state is None or state <= vision
        else f" State moves it {state / max(vision, 1e-9):.1f}x more, so it is riding proprioception."
    )
    return (
        "vision is NOT load-bearing (ratio < 2x sampling noise). Photometric alignment alone "
        f"cannot fix this; a visual re-finetune is required.{shortcut}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-path", required=True, help="Local checkpoint directory or HuggingFace model id.")
    parser.add_argument("--dataset-path", required=True, help="LeRobot corpus supplying the observations.")
    parser.add_argument("--modality-config-path", default=None, help="Modality config to import and register.")
    parser.add_argument("--embodiment-tag", default="new_embodiment")
    parser.add_argument("--traj-id", type=int, default=0)
    parser.add_argument("--steps", type=int, nargs="+", default=[0, 60, 120])
    parser.add_argument("--corpus-instruction", default=None, help="Instruction to swap in for the prompt ablation.")
    parser.add_argument("--output", default=None, help="Path to write the JSON report to.")
    args = parser.parse_args()

    import torch

    from gr00t.data.dataset.lerobot_episode_loader import LeRobotEpisodeLoader
    from gr00t.data.embodiment_tags import EmbodimentTag
    from gr00t.policy.gr00t_policy import Gr00tPolicy

    if args.modality_config_path:
        _register_modality_config(Path(args.modality_config_path).resolve())

    embodiment_tag = EmbodimentTag.resolve(args.embodiment_tag)
    policy = Gr00tPolicy(
        embodiment_tag=embodiment_tag,
        model_path=args.model_path,
        device="cuda" if torch.cuda.is_available() else "cpu",
    )
    modality_configs = policy.get_modality_config()
    loader = LeRobotEpisodeLoader(dataset_path=args.dataset_path, modality_configs=modality_configs)
    action_keys = list(modality_configs["action"].modality_keys)
    probe_model = _ChunkDictPolicy(policy, action_keys)

    traj = loader[args.traj_id]
    per_step: list[dict[str, Any]] = []
    for step in args.steps:
        if step >= len(traj):
            print(f"  step {step}: beyond trajectory length {len(traj)}, skipping", flush=True)
            continue
        observation = _build_observation(traj, step, modality_configs, embodiment_tag)
        result = measure_ablation_sensitivity(probe_model, observation, corpus_instruction=args.corpus_instruction)
        result["step"] = step
        per_step.append(result)
        print(
            f"  step {step:4d}: noise_floor={result['sampling_noise_floor']:.4f}"
            f"  vision={result.get('vision_ablation_ratio', float('nan')):.2f}x"
            f"  state={result.get('state_ablation_ratio', float('nan')):.2f}x"
            f"  prompt={result.get('prompt_ablation_ratio', float('nan')):.2f}x",
            flush=True,
        )

    assert per_step, "No observations were probed; check --traj-id and --steps."

    summary = {
        "model_path": args.model_path,
        "dataset_path": args.dataset_path,
        "traj_id": args.traj_id,
        "steps_probed": [r["step"] for r in per_step],
        "mean_sampling_noise_floor": statistics.fmean(r["sampling_noise_floor"] for r in per_step),
        "aggregates": {name: _aggregate_ratio(per_step, f"{name}_ablation") for name in _MODALITIES},
        "per_step": per_step,
    }
    pooled = {name: (summary["aggregates"][name] or {}).get("pooled") for name in _MODALITIES}
    summary["verdict"] = _verdict(pooled["vision"], pooled["state"])

    print("\n--- modality ablation (multiples of the policy's sampling-noise floor) ---")
    print(f"  {'modality':10s} {'median':>9s} {'pooled':>9s} {'mean':>9s}   n")
    for name in _MODALITIES:
        agg = summary["aggregates"][name]
        if agg is None:
            print(f"  {name:10s} {'n/a':>9s}")
            continue
        print(f"  {name:10s} {agg['median']:8.2f}x {agg['pooled']:8.2f}x {agg['mean']:8.2f}x  {agg['n']:3d}")
    print(
        "\n  'pooled' is sum(delta)/sum(noise_floor) and 'median' the per-step median; both resist the\n"
        "  low-noise-floor steps that inflate the mean. The verdict reads the pooled ratio."
    )
    print(f"\n  verdict: {summary['verdict']}")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2))
        print(f"\n  wrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
