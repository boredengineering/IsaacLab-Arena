# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Fit the one global scalar that turns DA3's canonical depth into metres.

``DA3METRIC-LARGE`` emits canonical depth, and neither the raw output nor the model card's
``focal/300`` conversion is metres on this rig: the evidence appendix measured raw at 1.568x true on
the table region and the conversion at 2.566x. One fitted scalar reached 1.027x / 1.64 cm. This
script fits that scalar.

**It needs no ground-truth depth**, which matters because the only GT available comes from the
simulator render, and that render is frozen. Instead it anchors on scene geometry that is known
from the environment config:

- ``apple_01_objaverse_robolab`` has USD AABB ``min_z = -0.019``, ``max_z = 0.049``, so its
  **height is 0.068 m** and its radius 0.034 m.
- The shelf surface is planar, so a plane fit to it is a free measurement of whether the teacher's
  relative geometry is trustworthy at all before any scale is inferred.

**Two statistics, two anchors, and they differ by a factor of two.** The apple's *peak* relief above
the surface is its full height, 0.068 m. The *median* relief over its visible pixels is roughly its
radius, 0.034 m, because a camera looking down on a sphere sees a surface whose average height is
near the centre. §2.5 of the evidence appendix quotes "3.4 cm relief", which is the **median**
statistic. Both are reported, each against its own anchor, because picking one silently would put a
factor of two into every metre this pipeline ever reports.

A scale-free check runs first: relief divided by range is unaffected by the unknown scalar, so it
validates the relief measurement *before* the scalar is derived from it. If that ratio is wrong,
the fitted scalar would absorb the error and look fine.

**That check fails, and it changes the method.** Measured on frame 0, the apple's relief is 2.35% of
range where its 0.068 m height at ~0.40 m demands 17%. DA3 smooths the apple into the table: a
relief anchor asks the teacher for a *depth difference* of a few centimetres across ~95 pixels,
which is exactly the scale monocular depth blurs. So relief is reported as a diagnostic only.

The anchor used instead is the apple's **apparent size**, which is a *lateral* measurement. Under a
pinhole camera an object of known width ``W`` spanning ``p`` pixels sits at ``Z = focal * W / p``.
That needs no depth gradient at all -- only the pixel extent, which is sharp, and the depth *value*
at the object, which is what we are scaling. On frame 0 it gives ``s`` in the 0.72-0.89 range
against the evidence appendix's fitted 0.655, where the relief anchor gave 4.0-7.1.

The apple is found by colour rather than a fixed pixel window, because the head camera's pose
varies per episode: a window read off one frame finds zero apple pixels on the next.
"""

from __future__ import annotations

import argparse
import json
import numpy as np
from pathlib import Path

# From ``galileo_g1_static_pick_and_place_environment.py``: the apple's USD AABB spans
# min_z = -0.019 to max_z = 0.049.
APPLE_HEIGHT_M = 0.068
APPLE_RADIUS_M = 0.034


def load_frame_rgb(dataset_path: Path, episode: int, frame: int, height: int, width: int):
    """Return one recorded frame as an ``(H, W, 3)`` uint8 RGB array.

    Args:
        dataset_path: LeRobot dataset root.
        episode: Episode index.
        frame: Frame index within the episode.
        height: Frame height in pixels.
        width: Frame width in pixels.

    Returns:
        The decoded frame.
    """
    import subprocess

    video = dataset_path / "videos" / "chunk-000" / "observation.images.ego_view" / f"episode_{episode:06d}.mp4"
    assert video.is_file(), f"No recorded video at {video}."
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(video),
            "-frames:v",
            str(frame + 1),
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
    return np.frombuffer(result.stdout, dtype=np.uint8)[frame * stride : (frame + 1) * stride].reshape(height, width, 3)


def segment_apple(rgb: np.ndarray, min_pixels: int = 150) -> np.ndarray:
    """Return a boolean mask of the apple, found by colour rather than by a fixed window.

    The apple is the only strongly saturated warm object in the scene: the shelf surface is near
    black, and the destination plate -- much larger in pixels, and the thing a fixed central window
    actually measures -- is a desaturated beige. Selecting on saturation *and* hue separates them,
    and the largest surviving connected component is the apple.

    Args:
        rgb: Frame as ``(H, W, 3)`` uint8.
        min_pixels: Reject a component smaller than this as noise.

    Returns:
        Boolean mask of the apple's pixels, empty if none was found.
    """
    import cv2

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hue, saturation, value = hsv[..., 0].astype(np.int16), hsv[..., 1], hsv[..., 2]
    # OpenCV hue is 0-179; the apple's red-orange sits below 25 or wraps above 160.
    warm = (hue < 25) | (hue > 160)
    candidate = warm & (saturation > 90) & (value > 60)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(candidate.astype(np.uint8), connectivity=8)
    if count <= 1:
        return np.zeros(rgb.shape[:2], dtype=bool)
    areas = stats[1:, cv2.CC_STAT_AREA]
    best = int(np.argmax(areas)) + 1
    if areas[best - 1] < min_pixels:
        return np.zeros(rgb.shape[:2], dtype=bool)
    return labels == best


def back_project(depth: np.ndarray, fx: float, fy: float, cx: float, cy: float) -> np.ndarray:
    """Return depth as camera-frame points, one per pixel.

    Args:
        depth: Depth as ``(H, W)``, in whatever unit is to be scaled.
        fx: Focal length in pixels along x.
        fy: Focal length in pixels along y.
        cx: Principal point x, in pixels.
        cy: Principal point y, in pixels.

    Returns:
        Points as ``(H, W, 3)``; the third channel equals ``depth``, since DA3 emits z-depth
        along the optical axis rather than ray distance.
    """
    height, width = depth.shape
    us, vs = np.meshgrid(np.arange(width, dtype=np.float64), np.arange(height, dtype=np.float64))
    return np.stack([(us - cx) / fx * depth, (vs - cy) / fy * depth, depth], axis=-1)


def fit_plane_ransac(
    points: np.ndarray, iterations: int = 500, tolerance: float = 0.004, seed: int = 0
) -> tuple[np.ndarray, float, np.ndarray]:
    """Fit a plane to a point set by RANSAC and return it with its inlier residual.

    Args:
        points: Points as ``(N, 3)``.
        iterations: Number of random minimal samples to try.
        tolerance: Inlier threshold, in the points' own unit.
        seed: Seed for the sampler, so a reported fit is reproducible.

    Returns:
        Tuple of the plane as ``(a, b, c, d)`` with unit normal, the inlier RMS residual, and the
        boolean inlier mask.
    """
    assert len(points) >= 3, f"A plane needs at least 3 points, got {len(points)}."
    rng = np.random.default_rng(seed)
    best_mask, best_plane = None, None

    for _ in range(iterations):
        sample = points[rng.choice(len(points), size=3, replace=False)]
        normal = np.cross(sample[1] - sample[0], sample[2] - sample[0])
        norm = np.linalg.norm(normal)
        if norm < 1e-12:
            continue
        normal = normal / norm
        offset = -normal @ sample[0]
        distances = np.abs(points @ normal + offset)
        mask = distances < tolerance
        if best_mask is None or mask.sum() > best_mask.sum():
            best_mask, best_plane = mask, np.append(normal, offset)

    assert best_plane is not None, "RANSAC found no plane; the point set may be degenerate."

    # Refit on the inliers by total least squares, which is what makes the residual meaningful
    # rather than an artefact of whichever three points happened to be drawn.
    inliers = points[best_mask]
    centroid = inliers.mean(axis=0)
    _, _, vh = np.linalg.svd(inliers - centroid)
    normal = vh[-1]
    plane = np.append(normal, -normal @ centroid)
    residual = float(np.sqrt(np.mean((inliers @ normal + plane[3]) ** 2)))
    return plane, residual, best_mask


def signed_height_above(points: np.ndarray, plane: np.ndarray) -> np.ndarray:
    """Return each point's signed distance from a plane, positive towards the camera.

    Args:
        points: Points as ``(N, 3)``.
        plane: Plane as ``(a, b, c, d)`` with unit normal.

    Returns:
        Signed distances, oriented so that a point nearer the camera than the plane is positive.
    """
    distances = points @ plane[:3] + plane[3]
    # The plane's normal has an arbitrary sign. Orient it away from the camera, which sits at the
    # origin: with d < 0 the origin is on the negative side, so flip to make "towards camera"
    # positive.
    return -distances if plane[3] > 0 else distances


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Return parsed command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--depth-dir",
        type=Path,
        default=Path("/datasets/isaaclab_arena/static_apple_tutorial/depth_da3"),
    )
    parser.add_argument(
        "--episodes",
        type=int,
        nargs="+",
        default=[0, 1, 125],
        help="Episodes to fit independently. A pose-dependent result means one global scalar is the wrong model.",
    )
    parser.add_argument(
        "--frame",
        type=int,
        default=0,
        help=(
            "Frame index. Must be before the grasp: relief above the surface is only defined"
            " while the apple is resting on it."
        ),
    )
    parser.add_argument(
        "--table-roi",
        type=int,
        nargs=4,
        default=(260, 480, 120, 560),
        metavar=("TOP", "BOTTOM", "LEFT", "RIGHT"),
        help="Pixel window holding the shelf surface and the apple.",
    )
    parser.add_argument(
        "--object-roi",
        type=int,
        nargs=4,
        default=(295, 390, 50, 155),
        metavar=("TOP", "BOTTOM", "LEFT", "RIGHT"),
        help=(
            "Pixel window holding the apple alone, read off the frame. Separate from the plane"
            " window because the plate is far larger in pixels than the apple and sits in the middle"
            " of the table: a single window measures the plate's relief, not the apple's."
        ),
    )
    parser.add_argument("--plane-tolerance", type=float, default=0.004)
    parser.add_argument(
        "--min-relief",
        type=float,
        default=0.008,
        help="Above-plane height, in canonical units, above which a pixel counts as object.",
    )
    parser.add_argument(
        "--dataset-path",
        type=Path,
        default=Path("/datasets/isaaclab_arena/static_apple_tutorial/lerobot"),
        help="Needed for the RGB frame the apple is segmented from.",
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Fit the scale on each requested episode and report agreement across them."""
    args = parse_args(argv)

    with open(args.depth_dir / "manifest.json") as handle:
        manifest = json.load(handle)
    height, width = manifest["source_resolution_hw"]
    focal = float(manifest["focal_px_native"])
    cx, cy = width / 2.0, height / 2.0
    top, bottom, left, right = args.table_roi

    print(f"[fit] intrinsics fx=fy={focal:.2f}px  principal point=({cx:.1f}, {cy:.1f})")
    print(f"[fit] anchors: apple height {APPLE_HEIGHT_M} m, radius {APPLE_RADIUS_M} m")
    print(f"[fit] frame {args.frame}, plane ROI rows {top}:{bottom}, cols {left}:{right}")
    print(
        f"[fit] object ROI rows {args.object_roi[0]}:{args.object_roi[1]},"
        f" cols {args.object_roi[2]}:{args.object_roi[3]}\n"
    )

    results = []
    for episode in args.episodes:
        path = args.depth_dir / f"episode_{episode:06d}.npz"
        if not path.is_file():
            # The corpus's episode indices are sparse -- 208 episodes across the range 0..250 --
            # so a missing index is normal here, not a broken annotation.
            print(f"[fit] episode {episode}: no annotation (index not in this corpus); skipping")
            continue
        with np.load(path) as payload:
            canonical = payload["canonical_depth"][args.frame].astype(np.float64)

        all_points = back_project(canonical, focal, focal, cx, cy)
        # The plane comes from the wide window; RANSAC rejects the plate and apple as outliers,
        # since between them they are a small fraction of it.
        flat = all_points[top:bottom, left:right].reshape(-1, 3)
        plane, residual, inliers = fit_plane_ransac(flat, tolerance=args.plane_tolerance, seed=episode)
        surface_range = float(np.median(flat[inliers][:, 2]))

        # Relief is measured only inside the apple's own window.
        otop, obottom, oleft, oright = args.object_roi
        object_points = all_points[otop:obottom, oleft:oright].reshape(-1, 3)
        object_heights = signed_height_above(object_points, plane)
        object_mask = object_heights > args.min_relief
        heights = object_heights

        # Relief is a diagnostic, so its absence must not skip the episode: the apparent-size
        # anchor below is the one the fit actually rests on, and it does not use the object window.
        have_relief = object_mask.sum() >= 50
        if have_relief:
            peak = float(np.percentile(heights[object_mask], 99))
            median = float(np.median(heights[object_mask]))
        else:
            peak = median = float("nan")

        # Scale-free, so it validates the relief measurement before any scalar is derived from it.
        peak_fraction = peak / surface_range
        median_fraction = median / surface_range

        scale_from_peak = APPLE_HEIGHT_M / peak
        scale_from_median = APPLE_RADIUS_M / median

        # --- the anchor that works: apparent size, a lateral measurement ---
        rgb = load_frame_rgb(args.dataset_path, episode, args.frame, height, width)
        apple = segment_apple(rgb)
        apparent = None
        if apple.any():
            # Equivalent diameter from area, which is stabler than a bounding box against the
            # irregular silhouette of a real apple mesh and against a stray highlight.
            area_px = int(apple.sum())
            diameter_px = float(2.0 * np.sqrt(area_px / np.pi))
            ys, xs = np.nonzero(apple)
            bbox_px = float(max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1))
            true_range = focal * APPLE_HEIGHT_M / diameter_px
            measured = float(np.median(canonical[apple]))
            apparent = {
                "apple_pixels": area_px,
                "equivalent_diameter_px": diameter_px,
                "bbox_extent_px": bbox_px,
                "implied_true_range_m": true_range,
                "measured_canonical_at_apple": measured,
                "scale_from_apparent_size": true_range / measured,
            }
            print(
                f"        apple    {area_px} px, equiv diameter {diameter_px:.1f} px"
                f" (bbox {bbox_px:.0f}) -> true range {true_range:.4f} m"
            )
            print(f"        SCALE    s = {true_range / measured:.4f}  (canonical at apple {measured:.4f})")
        else:
            print("        apple    not found by colour; apparent-size anchor unavailable")

        results.append({
            "episode": episode,
            "apparent_size": apparent,
            "plane_rms_canonical": residual,
            "plane_inlier_fraction": float(inliers.mean()),
            "surface_range_canonical": surface_range,
            "object_pixels": int(object_mask.sum()),
            "peak_relief_canonical": peak,
            "median_relief_canonical": median,
            "peak_relief_fraction_of_range": peak_fraction,
            "median_relief_fraction_of_range": median_fraction,
            "scale_from_peak_vs_height": scale_from_peak,
            "scale_from_median_vs_radius": scale_from_median,
        })
        print(
            f"[fit] episode {episode}: plane RMS {residual:.5f} canonical"
            f" ({100 * inliers.mean():.0f}% inliers), surface at {surface_range:.4f}"
        )
        if have_relief:
            print(
                f"        relief  peak {peak:.5f} ({100 * peak_fraction:.2f}% of range)"
                f"   median {median:.5f} ({100 * median_fraction:.2f}%)  over"
                f" {int(object_mask.sum())} px"
            )
            print(
                f"        scale   from peak/height {scale_from_peak:.4f}"
                f"   from median/radius {scale_from_median:.4f}   [diagnostic]"
            )
        else:
            print(
                f"        relief  only {int(object_mask.sum())} above-plane px in the object"
                " window; the apple is elsewhere in this frame (head pose varies per episode)"
            )

    if not results:
        print("\n[fit] no episode yielded a fit.")
        return 1

    apparent_scales = np.array([r["apparent_size"]["scale_from_apparent_size"] for r in results if r["apparent_size"]])
    if apparent_scales.size:
        spread = (apparent_scales.max() - apparent_scales.min()) / apparent_scales.mean()
        print(
            f"\n[fit] APPARENT SIZE (the usable anchor): s = {apparent_scales.mean():.4f}"
            f" +/- {apparent_scales.std():.4f} (spread {100 * spread:.1f}% over"
            f" {apparent_scales.size} episodes)"
        )
        print("        evidence appendix section 2.5b fitted 0.655 for comparison")

    print("\n[fit] relief anchors below are DIAGNOSTIC ONLY -- DA3 smooths the apple's relief,")
    print("      so these are expected to disagree. See the module docstring.")
    for key, label in (
        ("scale_from_peak_vs_height", "peak vs height"),
        ("scale_from_median_vs_radius", "median vs radius"),
    ):
        values = np.array([r[key] for r in results], dtype=float)
        values = values[np.isfinite(values)]
        if not values.size:
            print(f"\n[fit] {label}: no episode yielded a relief measurement")
            continue
        spread = (values.max() - values.min()) / values.mean() if values.mean() else float("nan")
        print(
            f"\n[fit] {label}: s = {values.mean():.4f} +/- {values.std():.4f}"
            f" (spread {100 * spread:.1f}% across {len(values)} episodes)"
        )
        print(
            "        plane residual in metres at this scale:"
            f" {100 * values.mean() * np.mean([r['plane_rms_canonical'] for r in results]):.2f} cm"
        )

    summary = {
        "anchors": {"apple_height_m": APPLE_HEIGHT_M, "apple_radius_m": APPLE_RADIUS_M},
        "frame": args.frame,
        "plane_roi": list(args.table_roi),
        "object_roi": list(args.object_roi),
        "focal_px_native": focal,
        "per_episode": results,
        "notes": (
            "Anchored on known scene geometry, not on render-derived ground truth, because the"
            " simulator render is frozen. The two scales differ by construction: peak relief is the"
            " apple's full height, median relief is roughly its radius. Evidence appendix section"
            " 2.5b's fitted 0.655 is the comparison point."
        ),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as handle:
            json.dump(summary, handle, indent=2)
        print(f"\n[fit] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
