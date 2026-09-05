# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Compare re-rendered demonstration frames against the frames in the original recording.

This is the acceptance check for ``rerender_demos.py``: state playback only yields usable
ground-truth depth if the scene the current build renders is the scene the dataset was recorded in.
A large discrepancy is a finding about the environment, not about this tool, so the report separates
the candidate causes -- channel order, render latency, orientation, and per-channel appearance --
rather than collapsing them into one number.

Requires no simulator, so it runs on the recording and the re-render output alone.
"""

import argparse
import h5py
import json
import math
import numpy as np
import subprocess
from pathlib import Path

CHANNEL_PERMUTATIONS = {
    "RGB": (0, 1, 2),
    "BGR": (2, 1, 0),
    "GRB": (1, 0, 2),
    "RBG": (0, 2, 1),
    "GBR": (1, 2, 0),
    "BRG": (2, 0, 1),
}


def decode_video(video_path: Path, height: int, width: int) -> np.ndarray:
    """Decode an mp4 to a uint8 array of shape ``(T, H, W, 3)``.

    Uses ffmpeg over a raw pipe rather than a Python video backend, so the result does not depend on
    which decoder happens to be installed.

    Args:
        video_path: Video to decode.
        height: Expected frame height.
        width: Expected frame width.

    Returns:
        Decoded frames as ``(T, H, W, 3)`` uint8.
    """
    command = [
        "ffmpeg", "-loglevel", "error", "-i", str(video_path),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]  # fmt: skip
    raw = subprocess.run(command, capture_output=True, check=True).stdout
    frame_bytes = height * width * 3
    assert len(raw) % frame_bytes == 0, (
        f"Decoded {len(raw)} bytes, which is not a whole number of {height}x{width} RGB frames."
        " The resolution passed here disagrees with the video."
    )
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, height, width, 3)


def mean_abs_diff(lhs: np.ndarray, rhs: np.ndarray) -> float:
    """Return the mean absolute difference between two uint8 image arrays, in 0-255 units."""
    return float(np.abs(lhs.astype(np.float64) - rhs.astype(np.float64)).mean())


def psnr_db(lhs: np.ndarray, rhs: np.ndarray) -> float:
    """Return peak signal-to-noise ratio in dB, or ``inf`` for an exact match."""
    mse = float(np.mean((lhs.astype(np.float64) - rhs.astype(np.float64)) ** 2))
    return float("inf") if mse == 0.0 else 10.0 * math.log10(255.0**2 / mse)


def diagnose(rendered: np.ndarray, recorded: np.ndarray) -> dict:
    """Attribute a rendered-vs-recorded discrepancy across its candidate causes.

    Args:
        rendered: Re-rendered frames, ``(T, H, W, 3)`` uint8.
        recorded: Recorded frames, ``(T, H, W, 3)`` uint8.

    Returns:
        Report mapping with aligned-frame error, per-channel means, and the channel-permutation,
        render-latency and orientation checks.
    """
    frames = min(len(rendered), len(recorded))
    rendered, recorded = rendered[:frames], recorded[:frames]

    per_frame = [mean_abs_diff(rendered[i], recorded[i]) for i in range(frames)]

    # Channel order: a swap shows up as a permutation beating the identity.
    permutations = {
        name: round(mean_abs_diff(rendered[0][..., perm], recorded[0]), 3)
        for name, perm in CHANNEL_PERMUTATIONS.items()
    }
    # Render latency: a stale RTX buffer shows up as a later recorded frame matching better.
    latency = {
        f"rendered[0]_vs_recorded[{j}]": round(mean_abs_diff(rendered[0], recorded[j]), 3)
        for j in range(min(frames, 8))
    }
    # Orientation: a convention flip shows up as a flip beating the unflipped comparison.
    orientation = {
        "unflipped": round(mean_abs_diff(rendered[0], recorded[0]), 3),
        "vertical_flip": round(mean_abs_diff(rendered[0][::-1], recorded[0]), 3),
        "horizontal_flip": round(mean_abs_diff(rendered[0][:, ::-1], recorded[0]), 3),
    }

    return {
        "frames_compared": frames,
        "mean_abs_diff": float(np.mean(per_frame)),
        "psnr_db": float(np.mean([psnr_db(rendered[i], recorded[i]) for i in range(frames)])),
        "channel_mean_rendered": [round(v, 2) for v in rendered.reshape(-1, 3).mean(0).tolist()],
        "channel_mean_recorded": [round(v, 2) for v in recorded.reshape(-1, 3).mean(0).tolist()],
        "channel_permutation_mean_abs_diff": permutations,
        "latency_scan_mean_abs_diff": latency,
        "orientation_mean_abs_diff": orientation,
    }


MATERIAL_IMPROVEMENT = 0.20
"""Relative error reduction a candidate cause must deliver before it is named.

Without a margin, any candidate that happens to be a hair better than the aligned comparison gets
blamed for an error it explains almost none of -- which reads as a confident diagnosis of the wrong
thing.
"""


def _best_candidate(candidates: dict[str, float], baseline_key: str) -> tuple[str, float]:
    """Return the best-fitting candidate and its relative improvement over the baseline.

    Args:
        candidates: Mapping from candidate name to its mean absolute difference.
        baseline_key: The candidate representing "no cause", against which improvement is measured.

    Returns:
        Tuple of the best candidate's name and its fractional improvement over the baseline.
    """
    best_key = min(candidates, key=candidates.get)
    baseline = candidates[baseline_key]
    improvement = 0.0 if baseline == 0.0 else (baseline - candidates[best_key]) / baseline
    return best_key, improvement


def verdict(report: dict) -> str:
    """Summarise which cause, if any, the numbers point at.

    A candidate is only named if it removes at least ``MATERIAL_IMPROVEMENT`` of the error; otherwise
    the discrepancy is reported as unexplained by the mechanical causes, which is the honest answer.

    Args:
        report: Report from :func:`diagnose`.

    Returns:
        A one-line human-readable verdict.
    """
    if report["psnr_db"] > 30.0:
        return "MATCH: the re-render reproduces the recording; codec noise only."

    best_permutation, permutation_gain = _best_candidate(report["channel_permutation_mean_abs_diff"], "RGB")
    best_orientation, orientation_gain = _best_candidate(report["orientation_mean_abs_diff"], "unflipped")
    latency = report["latency_scan_mean_abs_diff"]
    best_latency, latency_gain = _best_candidate(latency, next(iter(latency)))

    if best_permutation != "RGB" and permutation_gain >= MATERIAL_IMPROVEMENT:
        return f"CHANNEL ORDER: permutation {best_permutation} cuts the error by {permutation_gain:.0%}."
    if best_orientation != "unflipped" and orientation_gain >= MATERIAL_IMPROVEMENT:
        return f"ORIENTATION: {best_orientation} cuts the error by {orientation_gain:.0%}."
    if not best_latency.endswith("[0]") and latency_gain >= MATERIAL_IMPROVEMENT:
        return f"RENDER LATENCY: {best_latency} cuts the error by {latency_gain:.0%}."
    rendered_mean = np.array(report["channel_mean_rendered"])
    recorded_mean = np.array(report["channel_mean_recorded"])
    channel_gap = (rendered_mean - recorded_mean).round(1).tolist()
    return (
        "SCENE MISMATCH: channel order, orientation and render latency are all ruled out, so the"
        f" current build renders a different scene. Per-channel mean gap (R,G,B) = {channel_gap}."
    )


def main() -> None:
    """Compare one re-rendered episode against its recording and write a report plus a contact sheet."""
    parser = argparse.ArgumentParser(description="Compare re-rendered frames against the original recording.")
    parser.add_argument("--dataset_file", type=Path, required=True, help="HDF5 recording that was re-rendered.")
    parser.add_argument("--rerender_dir", type=Path, required=True, help="Output directory of rerender_demos.py.")
    parser.add_argument("--episode", type=int, default=0, help="Episode index to compare.")
    parser.add_argument(
        "--recorded_camera_key", type=str, default="robot_head_cam_rgb", help="Camera key inside the recording."
    )
    parser.add_argument("--out_dir", type=Path, default=None, help="Where to write the report. Defaults in-place.")
    args = parser.parse_args()

    out_dir = args.out_dir or args.rerender_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    with h5py.File(args.dataset_file, "r") as dataset:
        demo_names = sorted(dataset["data"].keys(), key=lambda name: int(name.split("_")[-1]))
        demo = dataset["data"][demo_names[args.episode]]
        recorded = np.asarray(demo["camera_obs"][args.recorded_camera_key])

    video_path = args.rerender_dir / "videos" / "observation.images.ego_view" / f"episode_{args.episode:06d}.mp4"
    assert video_path.exists(), f"Re-rendered video not found: {video_path}"
    rendered = decode_video(video_path, recorded.shape[1], recorded.shape[2])

    report = diagnose(rendered, recorded)
    report["verdict"] = verdict(report)
    report["episode"] = args.episode

    contact_sheet = out_dir / f"fidelity_episode_{args.episode:06d}.png"
    _write_contact_sheet(rendered, recorded, contact_sheet)
    report["contact_sheet"] = str(contact_sheet)

    report_path = out_dir / f"fidelity_report_episode_{args.episode:06d}.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"\n[Fidelity] {report['verdict']}")
    print(f"[Fidelity] Wrote {report_path} and {contact_sheet}")


def _write_contact_sheet(rendered: np.ndarray, recorded: np.ndarray, path: Path) -> None:
    """Write a recorded-above-rendered contact sheet for a few evenly spaced frames."""
    from PIL import Image

    frames = min(len(rendered), len(recorded))
    picks = np.linspace(0, frames - 1, num=min(4, frames), dtype=int)
    rows = [
        np.concatenate([recorded[i] for i in picks], axis=1),
        np.concatenate([rendered[i] for i in picks], axis=1),
    ]
    Image.fromarray(np.concatenate(rows, axis=0)).save(path)


if __name__ == "__main__":
    main()
