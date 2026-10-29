# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Measure how much of Spatial Forcing's alignment loss a constant predictor already wins.

``align_loss`` is ``1 - cos(student, teacher)``, and cosine only compares directions. If a
teacher's per-token features all point much the same way, then a projector that ignores its input
entirely and emits the teacher's *mean* direction already scores well -- so most of the loss's
dynamic range measures nothing about geometry.

That floor is what this measures. Reporting ``align_loss`` against zero, as "starts near 1.0 and
decreases", is satisfied by a model that learned only the mean; the informative quantity is how far
below the floor it gets.

Measured for ``DA3METRIC-LARGE`` layer 23 on this corpus: cos(token, mean) = 0.87 at the student's
8x11 grid, so the floor is **0.127**, and the features carry an effective rank of ~9 out of 1024.
At DA3's native 37x49 grid the floor is 0.145 and the rank ~11, so the resampling is a small
contributor and the low-rank structure is intrinsic to the teacher.
"""

from __future__ import annotations

import argparse
import json
import numpy as np
import subprocess
import sys
import torch
from pathlib import Path


def feature_statistics(features: np.ndarray) -> dict:
    """Return the constant-predictor floor and spectral summary of a feature set.

    Args:
        features: Features as ``(N, D)``.

    Returns:
        Mapping with the mean cosine to the global mean direction, the implied floor, the
        participation-ratio effective rank, and the dimension count for 90% of variance.
    """
    assert features.ndim == 2 and features.shape[0] > 1, f"Expected (N, D) with N > 1, got {features.shape}."
    unit = features / np.linalg.norm(features, axis=1, keepdims=True)
    mean = features.mean(axis=0)
    mean_direction = mean / np.linalg.norm(mean)
    cosine = float((unit @ mean_direction).mean())

    centred = features - features.mean(axis=0)
    eigenvalues = np.linalg.svd(centred, compute_uv=False) ** 2
    total = eigenvalues.sum()
    return {
        "tokens": int(features.shape[0]),
        "cosine_to_mean": cosine,
        "constant_predictor_align_loss": 1.0 - cosine,
        "effective_rank": float((total**2) / (eigenvalues**2).sum()),
        "dims_for_90pct_variance": int(np.searchsorted(np.cumsum(eigenvalues) / total, 0.90) + 1),
        "top_eigenvalue_share": float(eigenvalues[0] / total),
    }


def decode(video: Path, frames: int, height: int, width: int) -> torch.Tensor:
    """Return the first frames of a video as a ``(N, 3, H, W)`` uint8 tensor."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(video),
            "-frames:v",
            str(frames),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    stride = height * width * 3
    count = len(result.stdout) // stride
    array = np.frombuffer(result.stdout, dtype=np.uint8)[: count * stride]
    return torch.from_numpy(array.reshape(count, height, width, 3).copy()).permute(0, 3, 1, 2)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Return parsed command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--teacher", type=Path, default=Path("/models/isaaclab_arena/DA3METRIC-LARGE"))
    parser.add_argument(
        "--video",
        type=Path,
        default=Path(
            "/datasets/isaaclab_arena/static_apple_tutorial/lerobot/videos/chunk-000/"
            "observation.images.ego_view/episode_000000.mp4"
        ),
    )
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument(
        "--grids",
        type=int,
        nargs="+",
        default=(8, 11, 37, 49),
        help="Flat list of ROWS COLUMNS pairs to evaluate, e.g. 8 11 37 49.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Defaults to cpu so this can run alongside a training job without competing for VRAM.",
    )
    parser.add_argument("--gr00t-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Report the alignment floor at each requested token grid."""
    args = parse_args(argv)
    assert len(args.grids) % 2 == 0, "--grids takes ROWS COLUMNS pairs, so an even count."
    grids = list(zip(args.grids[::2], args.grids[1::2]))

    root = args.gr00t_root or (Path(__file__).resolve().parents[2] / "submodules" / "Isaac-GR00T")
    sys.path.insert(0, str(root))
    from gr00t.model.modules.geometry_conditioning import FrozenGeometryEncoder, GeometryConditioningConfig

    encoder = FrozenGeometryEncoder(
        GeometryConditioningConfig(
            mode="align",
            encoder_id=str(args.teacher),
            encoder_kind="da3",
            encoder_dtype="float32",
        )
    ).to(torch.device(args.device))

    images = decode(args.video, args.frames, 480, 640).to(args.device)
    results = []
    for grid in grids:
        with torch.no_grad():
            features = encoder(images, grid=grid)
        stats = feature_statistics(features.reshape(-1, features.shape[-1]).float().cpu().numpy())
        stats["grid"] = list(grid)
        results.append(stats)
        print(
            f"grid {grid[0]}x{grid[1]:<3d} tokens={stats['tokens']:5d}"
            f"  cos(token,mean)={stats['cosine_to_mean']:.4f}"
            f"  CONSTANT-PREDICTOR FLOOR={stats['constant_predictor_align_loss']:.4f}"
            f"  eff.rank={stats['effective_rank']:6.1f}"
            f"  dims@90%={stats['dims_for_90pct_variance']}"
        )

    print(
        "\nRead align_loss against the floor for the student's grid, not against zero:"
        " a run that only learned the teacher's mean direction lands there."
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as handle:
            json.dump({"teacher": str(args.teacher), "grids": results}, handle, indent=2)
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
