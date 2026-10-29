# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Render recorded RGB beside its DA3 depth annotation as a side-by-side video.

A depth annotation is only as trustworthy as someone's having looked at it, and a colourised
depth map next to the frame it came from is the cheapest way to catch the failures that summary
statistics hide: a frozen render, an inverted depth sign, a teacher locked onto the gripper
instead of the scene.

The colour scale is fixed across the whole episode, from its own depth percentiles, so apparent
motion in the depth panel is real motion rather than per-frame renormalisation.
"""

from __future__ import annotations

import argparse
import json
import numpy as np
import subprocess
from pathlib import Path

import cv2


def load_rgb(video_path: Path, width: int, height: int) -> np.ndarray:
    """Return an episode's frames as an ``(N, H, W, 3)`` uint8 array in RGB order.

    Args:
        video_path: Path to the episode's mp4.
        width: Frame width in pixels.
        height: Frame height in pixels.

    Returns:
        Decoded frames.
    """
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video_path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        check=True,
    )
    frames = np.frombuffer(result.stdout, dtype=np.uint8)
    count = frames.size // (width * height * 3)
    return frames[: count * width * height * 3].reshape(count, height, width, 3)


def colourise(depth_metres: np.ndarray, low: float, high: float) -> np.ndarray:
    """Return depth as a turbo-coloured ``(N, H, W, 3)`` uint8 array, near = warm.

    Args:
        depth_metres: Depth in metres, shaped ``(N, H, W)``.
        low: Metres mapped to the near end of the scale.
        high: Metres mapped to the far end.

    Returns:
        Colourised depth in RGB order.
    """
    assert high > low, f"Degenerate depth range [{low}, {high}]."
    normalised = np.clip((depth_metres - low) / (high - low), 0.0, 1.0)
    # Inverted so nearer is warmer, which is the convention people read faster.
    scaled = ((1.0 - normalised) * 255).astype(np.uint8)
    return np.stack([cv2.cvtColor(cv2.applyColorMap(f, cv2.COLORMAP_TURBO), cv2.COLOR_BGR2RGB) for f in scaled])


def label(frame: np.ndarray, text: str) -> np.ndarray:
    """Return the frame with a caption burned into its top-left corner.

    Args:
        frame: An ``(H, W, 3)`` uint8 RGB frame.
        text: Caption to draw.

    Returns:
        The captioned frame.
    """
    # A real copy, not ``ascontiguousarray``: frames decoded via ``np.frombuffer`` are read-only
    # and already contiguous, so that call returns the same read-only array and cv2 refuses it.
    out = frame.copy()
    cv2.putText(out, text, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(out, text, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Return parsed command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dataset-path",
        type=Path,
        default=Path("/datasets/isaaclab_arena/static_apple_tutorial/lerobot"),
    )
    parser.add_argument(
        "--depth-dir",
        type=Path,
        default=Path("/datasets/isaaclab_arena/static_apple_tutorial/depth_da3"),
    )
    parser.add_argument("--episodes", type=int, nargs="+", default=[0])
    parser.add_argument("--video-key", default="observation.images.ego_view")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--percentiles",
        type=float,
        nargs=2,
        default=(2.0, 98.0),
        metavar=("LOW", "HIGH"),
        help="Depth percentiles mapped to the colour scale's ends, fixed per episode.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Render one side-by-side preview per requested episode."""
    args = parse_args(argv)

    with open(args.dataset_path / "meta" / "info.json") as handle:
        info = json.load(handle)
    shape = info["features"][args.video_key]["shape"]
    height, width = int(shape[0]), int(shape[1])
    fps = float(info["fps"])

    with open(args.depth_dir / "manifest.json") as handle:
        manifest = json.load(handle)
    scale = float(manifest["depth_scale_mm"])

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for episode in args.episodes:
        chunk = episode // int(info.get("chunks_size", 1000))
        video = args.dataset_path / "videos" / f"chunk-{chunk:03d}" / args.video_key / f"episode_{episode:06d}.mp4"
        annotation = args.depth_dir / f"episode_{episode:06d}.npz"
        assert video.is_file(), f"No recorded video at {video}."
        assert annotation.is_file(), f"No depth annotation at {annotation}."

        rgb = load_rgb(video, width, height)
        with np.load(annotation) as payload:
            depth = payload["metric_depth_mm"].astype(np.float32) / scale
        assert len(rgb) == len(depth), (
            f"Episode {episode}: {len(rgb)} recorded frames against {len(depth)} annotated ones."
            " The preview would pair a frame with another frame's depth."
        )

        low, high = np.percentile(depth, args.percentiles)
        panels = np.concatenate(
            [
                np.stack([label(f, "recorded RGB") for f in rgb]),
                np.stack([label(f, f"DA3 depth  {low:.2f}-{high:.2f} m") for f in colourise(depth, low, high)]),
            ],
            axis=2,
        )

        destination = args.output_dir / f"episode_{episode:06d}_rgb_depth.mp4"
        writer = subprocess.Popen(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                f"{panels.shape[2]}x{panels.shape[1]}",
                "-r",
                str(fps),
                "-i",
                "-",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(destination),
            ],
            stdin=subprocess.PIPE,
        )
        writer.communicate(panels.tobytes())
        assert writer.returncode == 0, f"ffmpeg failed writing {destination}."
        print(f"[preview] episode {episode}: {len(rgb)} frames, depth {low:.2f}-{high:.2f} m -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
