# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Depth-Anything Spatial Auditor for Teleoperation Datasets vs Simulation.

Uses Depth Anything V2 monocular depth estimation to audit 3D spatial alignment,
relative/metric object depth, and support surface orientation between teleoperation
demonstration datasets (LeRobot MP4s) and simulation camera views.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
import torch
from transformers import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class DepthSpatialAuditor:
    """Audits spatial alignment between dataset demonstration frames and simulation renders."""

    def __init__(
        self,
        model_name: str = "depth-anything/Depth-Anything-V2-Small-hf",
        device: str | None = None,
    ):
        """Initialize Depth-Anything pipeline.

        Args:
            model_name: HuggingFace model checkpoint.
            device: 'cuda' or 'cpu'. Defaults to CUDA if available.
        """
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        logging.info("Initializing Depth Anything model '%s' on %s...", model_name, device)
        self.pipe = pipeline(task="depth-estimation", model=model_name, device=device)
        logging.info("Depth Anything model loaded successfully.")

    def estimate_depth(self, image_input: str | Path | np.ndarray | Image.Image) -> np.ndarray:
        """Estimate normalized depth map (higher values = closer, or metric distance).

        Args:
            image_input: Image path, numpy RGB array, or PIL Image.

        Returns:
            2D numpy array of shape (H, W) with normalized depth in [0, 1].
        """
        if isinstance(image_input, (str, Path)):
            pil_img = Image.open(str(image_input)).convert("RGB")
        elif isinstance(image_input, np.ndarray):
            pil_img = Image.fromarray(image_input)
        else:
            pil_img = image_input

        result = self.pipe(pil_img)
        depth_pil = result["depth"]
        depth_np = np.array(depth_pil, dtype=np.float32)

        # Normalize to [0, 1] range (1.0 = closest, 0.0 = furthest)
        d_min, d_max = depth_np.min(), depth_np.max()
        if d_max > d_min:
            norm_depth = (depth_np - d_min) / (d_max - d_min)
        else:
            norm_depth = np.zeros_like(depth_np)

        return norm_depth

    @staticmethod
    def locate_target_object(
        rgb_img: np.ndarray,
        depth_map: np.ndarray,
        target_uv: tuple[float, float] | None = None,
        target_bbox: tuple[int, int, int, int] | None = None,
    ) -> dict[str, Any]:
        """Robust multi-modal object localization.

        Priority:
        1. Explicit target_bbox (if provided).
        2. Localized search around target_uv coordinates (from camera pinhole projection).
        3. Depth elevation saliency (foreground protrusions above support deck).
        4. HSV color / circular compactness fallback.
        """
        h, w = depth_map.shape

        # Case 1: Explicit bounding box
        if target_bbox is not None:
            bx, by, bw, bh = target_bbox
            cx, cy = bx + bw // 2, by + bh // 2
            obj_d = float(np.median(depth_map[max(0, cy - 4) : min(h, cy + 4), max(0, cx - 4) : min(w, cx + 4)]))
            return {
                "detected": True,
                "method": "explicit_bbox",
                "bbox": [int(bx), int(by), int(bw), int(bh)],
                "center": [int(cx), int(cy)],
                "relative_depth": round(obj_d, 4),
                "norm_center_y": round(cy / h, 4),
                "norm_center_x": round(cx / w, 4),
            }

        # Case 2: Target UV hint provided (e.g. from camera pinhole projection)
        if target_uv is not None:
            u_norm, v_norm = target_uv
            cx, cy = int(np.clip(u_norm * w, 10, w - 10)), int(np.clip(v_norm * h, 10, h - 10))
            half_box = 24
            bx = max(0, cx - half_box)
            by = max(0, cy - half_box)
            bw = min(w - bx, half_box * 2)
            bh = min(h - by, half_box * 2)
            obj_d = float(np.median(depth_map[max(0, cy - 5) : min(h, cy + 5), max(0, cx - 5) : min(w, cx + 5)]))
            return {
                "detected": True,
                "method": "target_uv_projection",
                "bbox": [int(bx), int(by), int(bw), int(bh)],
                "center": [int(cx), int(cy)],
                "relative_depth": round(obj_d, 4),
                "norm_center_y": round(cy / h, 4),
                "norm_center_x": round(cx / w, 4),
            }

        # Case 3: HSV color saliency (apple / manipuland hues)
        hsv = cv2.cvtColor(rgb_img, cv2.COLOR_RGB2HSV)
        mask1 = cv2.inRange(hsv, np.array([0, 70, 35]), np.array([28, 255, 255]))
        mask2 = cv2.inRange(hsv, np.array([160, 70, 35]), np.array([180, 255, 255]))
        mask = mask1 | mask2

        # Exclude bottom corners where robot hands usually reside
        mask[int(h * 0.70) :, : int(w * 0.25)] = 0
        mask[int(h * 0.70) :, int(w * 0.75) :] = 0

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid_contours = [c for c in contours if 120 < cv2.contourArea(c) < 18000]

        if valid_contours:
            # Pick contour with compactness closest to a circle
            def compactness(c):
                a = cv2.contourArea(c)
                p = cv2.arcLength(c, True)
                return abs((p * p) / (4 * np.pi * a) - 1.0) if a > 0 else 999.0

            best = min(valid_contours, key=compactness)
            bx, by, bw, bh = cv2.boundingRect(best)
            cx, cy = bx + bw // 2, by + bh // 2
            obj_d = float(np.median(depth_map[max(0, cy - 4) : min(h, cy + 4), max(0, cx - 4) : min(w, cx + 4)]))
            return {
                "detected": True,
                "method": "hsv_saliency",
                "bbox": [int(bx), int(by), int(bw), int(bh)],
                "center": [int(cx), int(cy)],
                "relative_depth": round(obj_d, 4),
                "norm_center_y": round(cy / h, 4),
                "norm_center_x": round(cx / w, 4),
            }

        # Case 4: Depth elevation saliency (object protruding from support deck in center workspace)
        center_region = depth_map[int(h * 0.25) : int(h * 0.70), int(w * 0.20) : int(w * 0.80)]
        if center_region.size > 0:
            median_bg = float(np.median(center_region))
            diff = center_region - median_bg
            # Salient object is closer than surrounding deck
            peak_y, peak_x = np.unravel_index(np.argmax(diff), center_region.shape)
            if diff[peak_y, peak_x] > 0.08:
                abs_x = int(w * 0.20) + peak_x
                abs_y = int(h * 0.25) + peak_y
                bx = max(0, abs_x - 20)
                by = max(0, abs_y - 20)
                bw = min(w - bx, 40)
                bh = min(h - by, 40)
                obj_d = float(np.median(depth_map[max(0, abs_y - 4) : min(h, abs_y + 4), max(0, abs_x - 4) : min(w, abs_x + 4)]))
                return {
                    "detected": True,
                    "method": "depth_elevation_saliency",
                    "bbox": [int(bx), int(by), int(bw), int(bh)],
                    "center": [int(abs_x), int(abs_y)],
                    "relative_depth": round(obj_d, 4),
                    "norm_center_y": round(abs_y / h, 4),
                    "norm_center_x": round(abs_x / w, 4),
                }

        return {
            "detected": False,
            "method": "none",
            "bbox": None,
            "center": None,
            "relative_depth": None,
            "norm_center_y": None,
            "norm_center_x": None,
        }

    @staticmethod
    def compute_surface_gradient(depth_map: np.ndarray) -> float:
        """Compute the vertical depth gradient across the hand-free central workspace column.

        Excludes left and right hand corridors to isolate the support deck surface slope.
        A positive slope indicates camera is pitched downward looking onto a surface.
        A negative or near-zero slope indicates near-horizontal or inverted table view.
        """
        h, w = depth_map.shape
        # Center column strip (w*0.30 to w*0.70) from 35% to 75% height
        y_start = int(h * 0.35)
        y_end = int(h * 0.75)
        x_start = int(w * 0.30)
        x_end = int(w * 0.70)

        center_strip = depth_map[y_start:y_end, x_start:x_end]
        row_means = np.mean(center_strip, axis=1)
        y_indices = np.arange(len(row_means))
        slope, _ = np.polyfit(y_indices, row_means, 1)
        return float(slope)

    def analyze_frame(
        self,
        rgb_img: np.ndarray,
        label: str = "frame",
        target_uv: tuple[float, float] | None = None,
        target_bbox: tuple[int, int, int, int] | None = None,
    ) -> dict[str, Any]:
        """Perform full depth and geometric analysis on an RGB image."""
        depth_map = self.estimate_depth(rgb_img)
        h, w = depth_map.shape

        # 1. Detect target object
        obj_info = self.locate_target_object(
            rgb_img=rgb_img,
            depth_map=depth_map,
            target_uv=target_uv,
            target_bbox=target_bbox,
        )

        # 2. Support surface analysis
        surface_gradient = self.compute_surface_gradient(depth_map)
        lower_deck_depth = float(np.median(depth_map[int(h * 0.7) :, int(w * 0.25) : int(w * 0.75)]))

        return {
            "label": label,
            "resolution": [w, h],
            "object": obj_info,
            "surface_gradient_slope": round(surface_gradient, 6),
            "lower_deck_median_depth": round(lower_deck_depth, 4),
            "depth_map": depth_map,
        }

    def compare(
        self,
        dataset_img: np.ndarray,
        sim_img: np.ndarray,
        output_viz_path: str | Path | None = None,
        dataset_target_uv: tuple[float, float] | None = None,
        sim_target_uv: tuple[float, float] | None = None,
    ) -> dict[str, Any]:
        """Compare spatial geometries between dataset frame and simulation frame."""
        res_dataset = self.analyze_frame(
            dataset_img, label="Dataset Demonstration", target_uv=dataset_target_uv
        )
        res_sim = self.analyze_frame(
            sim_img, label="Simulation View", target_uv=sim_target_uv
        )

        discrepancies: dict[str, Any] = {}
        if res_dataset["object"]["detected"] and res_sim["object"]["detected"]:
            d_depth = res_sim["object"]["relative_depth"] - res_dataset["object"]["relative_depth"]
            d_y = res_sim["object"]["norm_center_y"] - res_dataset["object"]["norm_center_y"]
            d_x = res_sim["object"]["norm_center_x"] - res_dataset["object"]["norm_center_x"]
            discrepancies["object_relative_depth_delta"] = round(d_depth, 4)
            discrepancies["object_vertical_pixel_delta"] = round(d_y, 4)
            discrepancies["object_horizontal_pixel_delta"] = round(d_x, 4)

        slope_dataset = res_dataset["surface_gradient_slope"]
        slope_sim = res_sim["surface_gradient_slope"]
        slope_ratio = round(slope_sim / (slope_dataset + 1e-8), 3) if abs(slope_dataset) > 1e-6 else 1.0
        discrepancies["surface_pitch_slope_ratio"] = slope_ratio
        discrepancies["surface_slope_sign_flip"] = bool(slope_dataset * slope_sim < 0)

        # Generate human-readable diagnostics
        diagnostics = []
        if "object_relative_depth_delta" in discrepancies:
            d_depth = discrepancies["object_relative_depth_delta"]
            if d_depth < -0.20:
                diagnostics.append(f"Target object is significantly FURTHER away in simulation (depth delta: {d_depth:+.3f}).")
            elif d_depth > 0.20:
                diagnostics.append(f"Target object is significantly CLOSER in simulation (depth delta: {d_depth:+.3f}).")
            else:
                diagnostics.append("Target object distance is within acceptable training distribution range.")

        if "object_vertical_pixel_delta" in discrepancies:
            d_y = discrepancies["object_vertical_pixel_delta"]
            if abs(d_y) > 0.20:
                direction = "higher in frame (above reach envelope)" if d_y < 0 else "lower in frame"
                diagnostics.append(f"Target object is {direction} in simulation (vertical delta: {d_y:+.3f}).")

        if discrepancies.get("surface_slope_sign_flip"):
            diagnostics.append(
                "CRITICAL: Camera pitch slope sign is inverted! Simulation camera is looking level/upward across table, "
                "whereas demonstration was looking steeply down onto support surface."
            )
        elif abs(slope_ratio) < 0.4:
            diagnostics.append(
                f"Camera pitch is substantially flatter in simulation than dataset (slope ratio: {slope_ratio:.3f})."
            )
        else:
            diagnostics.append("Support surface pitch is aligned with demonstration dataset.")

        report = {
            "dataset_analysis": {k: v for k, v in res_dataset.items() if k != "depth_map"},
            "simulation_analysis": {k: v for k, v in res_sim.items() if k != "depth_map"},
            "discrepancies": discrepancies,
            "diagnostics": diagnostics,
        }

        # Render 4-panel visual comparison if requested
        if output_viz_path:
            self._render_comparison_figure(
                dataset_img,
                res_dataset,
                sim_img,
                res_sim,
                report,
                output_viz_path,
            )

        return report

    def _render_comparison_figure(
        self,
        dataset_img: np.ndarray,
        res_dataset: dict[str, Any],
        sim_img: np.ndarray,
        res_sim: dict[str, Any],
        report: dict[str, Any],
        output_path: str | Path,
    ) -> None:
        """Render a high-resolution 4-panel side-by-side visualization."""
        target_size = (640, 480)
        d_rgb = cv2.resize(dataset_img, target_size)
        s_rgb = cv2.resize(sim_img, target_size)

        # Colorize depth maps with INFERNO colormap
        d_depth_color = cv2.applyColorMap(
            (res_dataset["depth_map"] * 255).astype(np.uint8), cv2.COLORMAP_INFERNO
        )
        d_depth_color = cv2.resize(d_depth_color, target_size)

        s_depth_color = cv2.applyColorMap(
            (res_sim["depth_map"] * 255).astype(np.uint8), cv2.COLORMAP_INFERNO
        )
        s_depth_color = cv2.resize(s_depth_color, target_size)

        # Draw overlays on Dataset RGB
        if res_dataset["object"]["detected"]:
            bx, by, bw, bh = res_dataset["object"]["bbox"]
            cv2.rectangle(d_rgb, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)
            cv2.putText(
                d_rgb,
                f"Depth: {res_dataset['object']['relative_depth']:.3f} ({res_dataset['object']['method']})",
                (bx, max(20, by - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                (0, 255, 0),
                2,
            )
            cx, cy = res_dataset["object"]["center"]
            cv2.circle(d_depth_color, (cx, cy), 6, (0, 255, 0), -1)

        # Draw overlays on Sim RGB
        if res_sim["object"]["detected"]:
            bx, by, bw, bh = res_sim["object"]["bbox"]
            cv2.rectangle(s_rgb, (bx, by), (bx + bw, by + bh), (0, 0, 255), 2)
            cv2.putText(
                s_rgb,
                f"Depth: {res_sim['object']['relative_depth']:.3f} ({res_sim['object']['method']})",
                (bx, max(20, by - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                (0, 0, 255),
                2,
            )
            cx, cy = res_sim["object"]["center"]
            cv2.circle(s_depth_color, (cx, cy), 6, (0, 0, 255), -1)

        # Annotate Titles
        d_slope = res_dataset["surface_gradient_slope"]
        s_slope = res_sim["surface_gradient_slope"]
        cv2.putText(d_rgb, "DATASET DEMO (RGB)", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(d_depth_color, f"DATASET DEPTH (Slope: {d_slope:+.4f})", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        cv2.putText(s_rgb, "SIMULATION SCENE (RGB)", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(s_depth_color, f"SIM DEPTH (Slope: {s_slope:+.4f})", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

        # Stitch 2x2 grid
        top_row = np.hstack([d_rgb, d_depth_color])
        bot_row = np.hstack([s_rgb, s_depth_color])
        grid = np.vstack([top_row, bot_row])

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
        logging.info("Saved depth spatial comparison visualization to: %s", out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Depth-Anything Spatial Auditor")
    parser.add_argument("--dataset-video", type=str, default=None, help="Path to episode MP4 video")
    parser.add_argument("--dataset-frame", type=str, default=None, help="Path to reference dataset frame image")
    parser.add_argument("--sim-frame", type=str, required=True, help="Path to simulation camera snapshot")
    parser.add_argument("--output-viz", type=str, default="depth_spatial_comparison.png", help="Path to output visualization")
    parser.add_argument("--output-json", type=str, default=None, help="Optional path to save JSON metrics report")
    parser.add_argument("--sim-target-uv", type=float, nargs=2, default=None, help="Optional (u_norm, v_norm) target hint for sim frame")
    parser.add_argument("--dataset-target-uv", type=float, nargs=2, default=None, help="Optional (u_norm, v_norm) target hint for dataset")
    args = parser.parse_args()

    # Resolve dataset image
    if args.dataset_frame:
        d_img = np.array(Image.open(args.dataset_frame).convert("RGB"))
    elif args.dataset_video:
        cap = cv2.VideoCapture(args.dataset_video)
        ret, frame_bgr = cap.read()
        cap.release()
        if not ret:
            raise RuntimeError(f"Failed to read frame from video {args.dataset_video}")
        d_img = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    else:
        # Default auto-discovery of static apple episode 0
        cand = Path("/datasets/isaaclab_arena/static_apple_tutorial/arena_g1_static_apple_dataset_recorded/lerobot/videos/chunk-000/observation.images.ego_view/episode_000000.mp4")
        if not cand.exists():
            cand = Path("/home/tarfy/datasets/isaaclab_arena/static_apple_tutorial/arena_g1_static_apple_dataset_recorded/lerobot/videos/chunk-000/observation.images.ego_view/episode_000000.mp4")
        if not cand.exists():
            raise FileNotFoundError("Please specify --dataset-video or --dataset-frame.")
        cap = cv2.VideoCapture(str(cand))
        ret, frame_bgr = cap.read()
        cap.release()
        d_img = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

    s_img = np.array(Image.open(args.sim_frame).convert("RGB"))

    sim_uv = tuple(args.sim_target_uv) if args.sim_target_uv else None
    d_uv = tuple(args.dataset_target_uv) if args.dataset_target_uv else None

    auditor = DepthSpatialAuditor()
    report = auditor.compare(
        d_img, s_img, output_viz_path=args.output_viz, sim_target_uv=sim_uv, dataset_target_uv=d_uv
    )

    print("\n" + "=" * 60)
    print(" DEPTH ANYTHING SPATIAL AUDIT REPORT")
    print("=" * 60)
    print(json.dumps(report, indent=2))
    print("=" * 60 + "\n")

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(report, f, indent=2)
        logging.info("Saved JSON report to: %s", args.output_json)


if __name__ == "__main__":
    main()
