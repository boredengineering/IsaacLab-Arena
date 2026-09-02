# Copyright (c) 2026, Isaac Lab Arena Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Visualize LeRobot episodes using Rerun desktop GUI or web viewer.

Supports both native desktop GUI app and browser streaming.
Compatible with LeRobot format v2.1 and v3.0 datasets.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import socket
import time

import cv2
import numpy as np
import pandas as pd
import rerun as rr

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def find_free_port(start: int = 9876) -> int:
    """Find the first available TCP port starting from `start`."""
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def visualize_episode(
    dataset_dir: str | Path | None = None,
    episode_index: int = 0,
    web: bool = False,
    web_port: int = 9090,
    grpc_port: int = 0,
    save_rrd: str | Path | None = None,
) -> Path | None:
    """Load a LeRobot episode and visualize telemetry and video streams via Rerun.

    Args:
        dataset_dir: Directory containing the LeRobot dataset.
        episode_index: Episode index to load (0-based).
        web: If True, serve via web browser rather than native desktop app.
        web_port: Port for the Rerun web viewer (when web=True).
        grpc_port: Internal gRPC streaming port for Rerun (0 = auto-find).
        save_rrd: Optional path to save an `.rrd` recording file.
    """
    # Auto-resolve dataset directory across host and container environments
    resolved_dir = None
    if dataset_dir:
        cand = Path(dataset_dir)
        if cand.exists():
            resolved_dir = cand

    if not resolved_dir:
        for candidate in [
            Path("/home/tarfy/datasets/isaaclab_arena/static_apple_tutorial/lerobot"),
            Path("/datasets/isaaclab_arena/static_apple_tutorial/lerobot"),
            Path("./lerobot"),
        ]:
            if candidate.exists():
                resolved_dir = candidate
                break

    if not resolved_dir or not resolved_dir.exists():
        raise FileNotFoundError(
            "Could not locate the LeRobot dataset directory. "
            "Please specify --dataset-dir <PATH>."
        )

    chunk_idx = episode_index // 1000
    parquet_path = resolved_dir / "data" / f"chunk-{chunk_idx:03d}" / f"episode_{episode_index:06d}.parquet"
    video_path = (
        resolved_dir
        / "videos"
        / f"chunk-{chunk_idx:03d}"
        / "observation.images.ego_view"
        / f"episode_{episode_index:06d}.mp4"
    )

    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet file not found: {parquet_path}")
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    logging.info("Loading episode %d from %s", episode_index, resolved_dir)
    df = pd.read_parquet(parquet_path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 50.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    logging.info(
        "Video metadata: %dx%d, %d frames @ %.1f FPS (parquet rows: %d)",
        width,
        height,
        total_frames,
        fps,
        len(df),
    )

    rec_id = f"lerobot_episode_{episode_index:06d}"
    spawn_native = not web and not save_rrd
    rr.init(rec_id, spawn=spawn_native)

    if web:
        g_port = grpc_port or find_free_port(9876)
        w_port = web_port or find_free_port(9090)
        server_uri = rr.serve_grpc(grpc_port=g_port)
        logging.info("Rerun gRPC server running at: %s", server_uri)
        rr.serve_web_viewer(open_browser=True, web_port=w_port, connect_to=server_uri)
        logging.info("=================================================================")
        logging.info(" LeRobot Web Visualizer ready!")
        logging.info(" Open in your browser: http://127.0.0.1:%d", w_port)
        logging.info("=================================================================")

    logging.info("Ingesting episode frames and telemetry into Rerun...")
    frame_idx = 0
    while True:
        ret, frame_bgr = cap.read()
        if not ret or frame_idx >= len(df):
            break

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        row = df.iloc[frame_idx]
        timestamp = float(row["timestamp"]) if "timestamp" in row else frame_idx / fps

        rr.set_time("frame_index", sequence=frame_idx)
        rr.set_time("timestamp", timestamp=timestamp)

        # 1. Camera RGB view
        rr.log("camera/ego_view", rr.Image(frame_rgb))

        # 2. End-effector cartesian poses (pelvis frame)
        if "observation.eef_pose" in row and isinstance(row["observation.eef_pose"], (list, np.ndarray)):
            eef = np.array(row["observation.eef_pose"], dtype=np.float32)
            if len(eef) >= 3:
                rr.log("eef/left_wrist/pos_x", rr.Scalars(float(eef[0])))
                rr.log("eef/left_wrist/pos_y", rr.Scalars(float(eef[1])))
                rr.log("eef/left_wrist/pos_z", rr.Scalars(float(eef[2])))
            if len(eef) >= 10:
                rr.log("eef/right_wrist/pos_x", rr.Scalars(float(eef[7])))
                rr.log("eef/right_wrist/pos_y", rr.Scalars(float(eef[8])))
                rr.log("eef/right_wrist/pos_z", rr.Scalars(float(eef[9])))

        # 3. Actions & Joint States
        if "action" in row and isinstance(row["action"], (list, np.ndarray)):
            for i, val in enumerate(row["action"][:14]):  # Arm joints
                rr.log(f"action/joint_{i:02d}", rr.Scalars(float(val)))

        if "observation.state" in row and isinstance(row["observation.state"], (list, np.ndarray)):
            for i, val in enumerate(row["observation.state"][:14]):
                rr.log(f"state/joint_{i:02d}", rr.Scalars(float(val)))

        frame_idx += 1

    cap.release()
    logging.info("Finished ingesting %d frames.", frame_idx)

    saved_path = None
    if save_rrd:
        save_path = Path(save_rrd)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        rr.save(str(save_path))
        logging.info("Saved Rerun recording to: %s", save_path)
        saved_path = save_path

    if web:
        logging.info("Web server listening on port %d. Press Ctrl+C to stop.", w_port)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Shutting down web visualizer.")
    elif spawn_native:
        logging.info("Native Rerun app launched! Use the viewer UI. Press Ctrl+C to exit script.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Exiting visualizer.")

    return saved_path


def main() -> None:
    parser = argparse.ArgumentParser(description="LeRobot Episode Visualizer (Native App or Web)")
    parser.add_argument(
        "--dataset-dir",
        type=str,
        default=None,
        help="Path to LeRobot dataset directory (auto-detected if omitted)",
    )
    parser.add_argument(
        "--episode-index",
        type=int,
        default=0,
        help="Episode index to visualize (default: 0)",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Serve via web browser instead of spawning native desktop window",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=0,
        help="Web viewer port (default: auto-find free port starting at 9090)",
    )
    parser.add_argument(
        "--save-rrd",
        type=str,
        default=None,
        help="Optional path to save .rrd recording file",
    )

    args = parser.parse_args()
    visualize_episode(
        dataset_dir=args.dataset_dir,
        episode_index=args.episode_index,
        web=args.web,
        web_port=args.web_port,
        save_rrd=args.save_rrd,
    )


if __name__ == "__main__":
    main()
