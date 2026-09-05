# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Measure how well metric depth can be read out of a policy's visual embeddings.

This is the acceptance gate for geometry conditioning. The measured failure on
``g1_tabletop_apple_to_plate`` is accurate bearing with ~7 cm of vertical range error, which is what
a 2D-pretrained backbone whose embeddings do not encode range looks like. Conditioning is only
worth evaluating on the task if it changes that, so this probe asks the question directly: fit a
ridge regression from the backbone's image tokens to ground-truth depth, and compare a baseline
checkpoint against a conditioned one.

Two properties make the number trustworthy:

- The split is by **episode**, not by frame. Adjacent frames at 50 Hz are near-duplicates, so a
  frame-wise split leaks the answer and reports a probe that has memorised rather than generalised.
- A constant predictor is reported alongside. Depth in a fixed tabletop scene has limited variance,
  so an impressive-looking error means nothing until it is compared against predicting the mean.

Frames and depth both come from one ``rerender_demos.py`` output directory, so the depth corresponds
to the image the backbone is shown. Pairing recorded frames with re-rendered depth would not.
"""

import argparse
import json
import numpy as np
import subprocess
from pathlib import Path


def decode_video(video_path: Path, height: int, width: int) -> np.ndarray:
    """Decode an mp4 into a uint8 array of shape ``(T, H, W, 3)``."""
    command = [
        "ffmpeg", "-loglevel", "error", "-i", str(video_path),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]  # fmt: skip
    raw = subprocess.run(command, capture_output=True, check=True).stdout
    frame_bytes = height * width * 3
    assert len(raw) % frame_bytes == 0, f"{video_path} does not decode to whole {height}x{width} frames."
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, height, width, 3)


def pool_depth_to_grid(depth: np.ndarray, grid: tuple[int, int]) -> np.ndarray:
    """Average a depth map onto a ``(rows, columns)`` token grid, ignoring non-finite pixels.

    Each backbone image token covers a rectangular image patch, so the comparable depth target is
    that patch's mean rather than a point sample. The grid is not square: N1.7 preserves the
    camera's aspect ratio, so a 4:3 frame gives 8x11.

    Args:
        depth: Depth map as ``(H, W)``, possibly containing ``inf`` where nothing was hit.
        grid: Target grid as ``(rows, columns)``.

    Returns:
        Pooled depth as ``(rows * columns,)``, with ``nan`` where a cell had no finite pixel.
    """
    num_rows, num_columns = grid
    height, width = depth.shape
    rows = np.array_split(np.arange(height), num_rows)
    columns = np.array_split(np.arange(width), num_columns)
    pooled = np.full((num_rows, num_columns), np.nan, dtype=np.float64)
    for row_index, row_slice in enumerate(rows):
        for column_index, column_slice in enumerate(columns):
            cell = depth[np.ix_(row_slice, column_slice)]
            finite = cell[np.isfinite(cell)]
            if finite.size:
                pooled[row_index, column_index] = float(finite.mean())
    return pooled.reshape(-1)


def fit_ridge(features: np.ndarray, targets: np.ndarray, alpha: float) -> np.ndarray:
    """Return ridge-regression weights for a bias-augmented design matrix.

    Solved in closed form rather than via a dependency, so the probe runs anywhere the policy does.

    Args:
        features: Design matrix as ``(N, D)``.
        targets: Targets as ``(N,)``.
        alpha: Ridge penalty. The bias column is left unpenalised.

    Returns:
        Weights as ``(D + 1,)``, with the bias last.
    """
    design = np.concatenate([features, np.ones((features.shape[0], 1))], axis=1)
    gram = design.T @ design
    penalty = alpha * np.eye(gram.shape[0])
    penalty[-1, -1] = 0.0
    return np.linalg.solve(gram + penalty, design.T @ targets)


def apply_ridge(weights: np.ndarray, features: np.ndarray) -> np.ndarray:
    """Apply weights from :func:`fit_ridge` to a feature matrix."""
    return np.concatenate([features, np.ones((features.shape[0], 1))], axis=1) @ weights


def score(predictions: np.ndarray, targets: np.ndarray) -> dict[str, float]:
    """Return median absolute error, mean absolute error and R^2, in metres."""
    residual = predictions - targets
    total_variance = float(((targets - targets.mean()) ** 2).sum())
    return {
        "median_abs_error_m": float(np.median(np.abs(residual))),
        "mean_abs_error_m": float(np.abs(residual).mean()),
        "r2": float(1.0 - (residual**2).sum() / total_variance) if total_variance > 0 else float("nan"),
    }


def build_template_observation(policy, model_path: str, embodiment_tag, language: str, resolution) -> dict:
    """Build one well-formed observation from the checkpoint's own statistics.

    The policy validates the whole observation, including each state group's width, and those widths
    live in the checkpoint's ``statistics.json``. Reading them from there rather than from a dataset
    keeps the probe runnable wherever the checkpoint is, which matters because the corpus dataset is
    not mounted in the inference container. State groups are filled with their training means, so
    the observation is a plausible one rather than an artificial zero vector; state never reaches
    the backbone, so its value cannot affect the embeddings being probed either way.

    Args:
        policy: A loaded ``Gr00tPolicy``.
        model_path: Checkpoint directory, holding ``statistics.json``.
        embodiment_tag: Resolved embodiment tag.
        language: Task instruction to condition on.
        resolution: Frame ``(height, width)`` the video placeholder is built at.

    Returns:
        A nested observation dict accepted by ``Gr00tPolicy.get_action``.
    """
    modality_configs = policy.get_modality_config()
    statistics_path = Path(model_path) / "statistics.json"
    assert statistics_path.exists(), f"statistics.json not found beside the checkpoint: {statistics_path}"
    statistics = json.loads(statistics_path.read_text())

    tag = embodiment_tag.value
    assert tag in statistics, f"{tag!r} has no statistics in {statistics_path}. Present: {sorted(statistics)}"
    state_statistics = statistics[tag]["state"]

    height, width = resolution
    num_history = len(modality_configs["video"].delta_indices)
    observation: dict[str, dict] = {"video": {}, "state": {}, "language": {}}
    for video_key in modality_configs["video"].modality_keys:
        observation["video"][video_key] = np.zeros((1, num_history, height, width, 3), dtype=np.uint8)
    for state_key in modality_configs["state"].modality_keys:
        assert state_key in state_statistics, (
            f"state group {state_key!r} is in the modality config but not in statistics.json, so its"
            " width is unknown and the observation cannot be built."
        )
        mean = np.asarray(state_statistics[state_key]["mean"], dtype=np.float32)
        observation["state"][state_key] = np.tile(mean, (1, 1, 1))
    for language_key in modality_configs["language"].modality_keys:
        observation["language"][language_key] = [[language]]
    return observation


def collect_embeddings(policy, template: dict, frames: np.ndarray, depth: np.ndarray, sample_stride: int):
    """Run frames through the policy's backbone and pair the image tokens with pooled depth.

    Args:
        policy: A loaded ``Gr00tPolicy``.
        template: Well-formed observation whose video is replaced per frame.
        frames: Frames as ``(T, H, W, 3)`` uint8.
        depth: Depth maps as ``(T, Hd, Wd)``.
        sample_stride: Take every Nth frame, since neighbouring frames are near-duplicates.

    Returns:
        Tuple of features ``(N, D)`` and depth targets ``(N,)``, both already filtered to cells with
        finite depth.
    """
    import torch
    from copy import deepcopy

    from gr00t.model.modules.geometry_conditioning import token_grid_from_image_grid_thw

    captured: dict[str, torch.Tensor] = {}

    def hook(_module, inputs, output):
        captured["backbone_features"] = output["backbone_features"].detach()
        captured["image_mask"] = output["image_mask"].detach()
        # The token grid is only knowable from the processor's own image_grid_thw, which arrives on
        # the way in rather than on the way out.
        captured["image_grid_thw"] = inputs[0]["image_grid_thw"].detach()

    handle = policy.model.backbone.register_forward_hook(hook)

    modality_configs = policy.get_modality_config()
    video_key = modality_configs["video"].modality_keys[0]
    num_history = len(modality_configs["video"].delta_indices)
    template_video = template["video"][video_key]
    assert tuple(template_video.shape[-3:-1]) == tuple(frames.shape[1:3]), (
        f"The re-rendered frames are {frames.shape[1:3]} but the policy expects"
        f" {template_video.shape[-3:-1]}. Resampling here would change what is being probed."
    )

    feature_rows: list[np.ndarray] = []
    target_rows: list[np.ndarray] = []
    try:
        for frame_index in range(0, min(len(frames), len(depth)), sample_stride):
            # Repeat the current frame across the history slots. The probe asks what a single
            # observation's embedding encodes, so giving the history real motion would let temporal
            # context rather than the frame itself carry the depth signal.
            history = np.repeat(frames[frame_index][None], num_history, axis=0)
            observation = deepcopy(template)
            observation["video"][video_key] = history[None].astype(np.uint8)

            with torch.inference_mode():
                policy.get_action(observation)

            features = captured["backbone_features"][0]
            image_mask = captured["image_mask"][0]
            image_tokens = features[image_mask].to(torch.float32).cpu().numpy()
            merge_size = policy.model.backbone.model.config.vision_config.spatial_merge_size
            rows, columns = token_grid_from_image_grid_thw(captured["image_grid_thw"], merge_size)
            tokens_per_image = rows * columns
            assert int(image_mask.sum()) == tokens_per_image * num_history, (
                f"{int(image_mask.sum())} image tokens does not equal {num_history} images x"
                f" {rows}x{columns}; the grid and the token stream disagree."
            )

            # The last image is the current frame, which is the one the depth map belongs to.
            current = image_tokens[-tokens_per_image:]
            pooled = pool_depth_to_grid(np.asarray(depth[frame_index], dtype=np.float64), (rows, columns))

            usable = np.isfinite(pooled)
            feature_rows.append(current[usable])
            target_rows.append(pooled[usable])
    finally:
        handle.remove()

    return np.concatenate(feature_rows), np.concatenate(target_rows)


def main() -> None:
    """Fit a depth readout probe on one checkpoint and report its generalisation."""
    parser = argparse.ArgumentParser(description="Probe metric-depth readout from policy embeddings.")
    parser.add_argument("--model_path", type=str, required=True, help="Checkpoint to probe.")
    parser.add_argument(
        "--rerender_dir",
        type=Path,
        required=True,
        help="Output directory of rerender_demos.py, supplying paired frames and ground-truth depth.",
    )
    parser.add_argument("--episodes", type=int, nargs="+", default=[0], help="Episode indices to probe.")
    parser.add_argument("--modality_config_path", type=str, default=None, help="Modality config to register.")
    parser.add_argument("--embodiment_tag", type=str, default="new_embodiment", help="Embodiment tag.")
    parser.add_argument("--language", type=str, required=True, help="Task instruction to condition on.")
    parser.add_argument("--sample_stride", type=int, default=10, help="Take every Nth frame.")
    parser.add_argument("--ridge_alpha", type=float, default=100.0, help="Ridge penalty.")
    parser.add_argument("--out_json", type=Path, default=None, help="Where to write the report.")
    args = parser.parse_args()

    import sys
    import torch

    from gr00t.data.embodiment_tags import EmbodimentTag
    from gr00t.policy.gr00t_policy import Gr00tPolicy

    if args.modality_config_path:
        config_path = Path(args.modality_config_path).resolve()
        assert config_path.exists(), f"modality config not found: {config_path}"
        sys.path.insert(0, str(config_path.parent))
        __import__(config_path.stem)

    assert len(args.episodes) >= 2, (
        "At least two episodes are needed: the probe splits train from test by episode, because"
        " neighbouring frames at 50 Hz are near-duplicates and a frame-wise split leaks the answer."
    )

    embodiment_tag = EmbodimentTag.resolve(args.embodiment_tag)
    policy = Gr00tPolicy(
        embodiment_tag=embodiment_tag,
        model_path=args.model_path,
        device="cuda" if torch.cuda.is_available() else "cpu",
    )

    per_episode = {}
    template = None
    for episode in args.episodes:
        video_path = args.rerender_dir / "videos" / "observation.images.ego_view" / f"episode_{episode:06d}.mp4"
        depth_path = args.rerender_dir / "depth" / f"episode_{episode:06d}.npz"
        assert video_path.exists(), f"missing frames for episode {episode}: {video_path}"
        assert depth_path.exists(), f"missing depth for episode {episode}: {depth_path}"

        depth = np.load(depth_path)["depth"].astype(np.float64)
        frames = decode_video(video_path, depth.shape[1], depth.shape[2])
        if template is None:
            template = build_template_observation(
                policy, args.model_path, embodiment_tag, args.language, frames.shape[1:3]
            )
        features, targets = collect_embeddings(policy, template, frames, depth, args.sample_stride)
        per_episode[episode] = (features, targets)
        print(f"[Probe] episode {episode}: {features.shape[0]} token/depth pairs", flush=True)

    # Hold out the last episode; everything else trains the probe.
    test_episode = args.episodes[-1]
    train_episodes = args.episodes[:-1]
    train_features = np.concatenate([per_episode[e][0] for e in train_episodes])
    train_targets = np.concatenate([per_episode[e][1] for e in train_episodes])
    test_features, test_targets = per_episode[test_episode]

    weights = fit_ridge(train_features, train_targets, args.ridge_alpha)
    probe_scores = score(apply_ridge(weights, test_features), test_targets)
    constant_scores = score(np.full_like(test_targets, train_targets.mean()), test_targets)

    report = {
        "model_path": args.model_path,
        "rerender_dir": str(args.rerender_dir),
        "train_episodes": train_episodes,
        "test_episode": test_episode,
        "train_pairs": int(train_features.shape[0]),
        "test_pairs": int(test_features.shape[0]),
        "embedding_dim": int(train_features.shape[1]),
        "ridge_alpha": args.ridge_alpha,
        "probe": probe_scores,
        "constant_predictor": constant_scores,
        "depth_std_m": float(test_targets.std()),
    }
    improvement = constant_scores["median_abs_error_m"] - probe_scores["median_abs_error_m"]
    report["improvement_over_constant_m"] = float(improvement)
    report["verdict"] = (
        "READS DEPTH: the embedding predicts held-out depth better than the scene's mean."
        if improvement > 0.005
        else "NO READOUT: the embedding is no better than predicting the mean depth."
    )

    print(json.dumps(report, indent=2))
    print(f"\n[Probe] {report['verdict']}")
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(report, indent=2))
        print(f"[Probe] Wrote {args.out_json}")


if __name__ == "__main__":
    main()
