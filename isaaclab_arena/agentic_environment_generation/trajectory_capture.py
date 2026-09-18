# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded trajectory capture for an already constructed single-environment rollout."""

import re
from pathlib import Path


def capture_trajectory(env, policy, *, out_dir, num_steps, frame_interval, camera_names, save_frame):
    """Capture reset and sampled observations, excluding post-autoreset end-step observations.

    Args:
        env: Single Arena environment with batched termination/truncation flags exposing any().
        policy: Initialized policy exposing reset and get_action.
        out_dir: Owned directory for new frame files.
        num_steps: Maximum policy steps to execute.
        frame_interval: Capture frequency in policy steps.
        camera_names: Explicit camera keys, or None to capture available camera observations.
        save_frame: Callable taking one camera observation and a destination PNG path.

    Returns:
        Frame paths, actual executed steps, stop reason and terminal-image unavailability.
        On termination/truncation IsaacLab returns reset images; no terminal image is captured.
    """
    assert type(num_steps) is int and num_steps > 0, "num_steps must be positive"
    assert type(frame_interval) is int and frame_interval > 0, "frame_interval must be positive"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = {}
    obs, _ = env.reset()
    policy.reset()
    cameras = obs.get("camera_obs", {})
    selected = sorted(cameras) if camera_names is None else list(camera_names)
    assert len(selected) == len(set(selected)), "Camera names must be unique"
    assert all(
        isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", name) for name in selected
    ), "Invalid camera name"
    assert all(name in cameras for name in selected), "Requested camera is unavailable"
    assert (2 + (num_steps - 1) // frame_interval) * len(selected) <= 64, "Capture exceeds 64-image budget"

    def capture(observation, step):
        cameras = observation.get("camera_obs", {})
        for name in selected:
            assert name in cameras, "Camera disappeared during capture"
            label = f"step_{step:06d}_{name}"
            path = out_dir / f"{label}.png"
            assert not path.exists(), "Refusing to replace a captured frame"
            save_frame(cameras[name], path)
            frames[label] = path

    capture(obs, 0)
    stop_reason = "step_budget"
    for executed_steps in range(1, num_steps + 1):
        action = policy.get_action(env, obs)
        obs, _, terminated, truncated, _ = env.step(action)
        ended, limited = bool(terminated.any()), bool(truncated.any())
        if ended or limited:
            stop_reason = "terminated_and_truncated" if ended and limited else "terminated" if ended else "truncated"
            break
        if executed_steps % frame_interval == 0 or executed_steps == num_steps:
            capture(obs, executed_steps)
    return {
        "frames": frames,
        "executed_steps": executed_steps,
        "stop_reason": stop_reason,
        "terminal_image_unavailable": ended or limited,
    }
