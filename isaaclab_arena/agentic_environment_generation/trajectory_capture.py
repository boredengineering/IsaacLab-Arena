# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded trajectory capture for an already constructed single-environment rollout."""

import re
from pathlib import Path


def capture_trajectory(
    env,
    policy,
    *,
    out_dir,
    num_steps,
    frame_interval,
    camera_names,
    save_frame,
    sample_state=None,
    initial_observation=None,
    step_offset=0,
    reset_policy=True,
):
    """Capture reset and sampled observations, excluding post-autoreset end-step observations.

    Args:
        env: Single Arena environment with batched termination/truncation flags exposing any().
        policy: Initialized policy exposing reset and get_action.
        out_dir: Owned directory for new frame files.
        num_steps: Maximum policy steps to execute.
        frame_interval: Capture frequency in policy steps.
        camera_names: Explicit camera keys, or None to capture available camera observations.
        save_frame: Callable taking one camera observation and a destination PNG path.
        sample_state: Optional trusted callback(env, step), invoked at reset and every
            nonterminal post-step; owns bounded retention. Return value is ignored.
        initial_observation: Trusted observation from an already initialized, nonterminal
            cohort. If provided, do not reset the environment. None preserves legacy reset.
        step_offset: Reset-relative control step of initial_observation; all sample and
            frame labels use this absolute offset, while executed_steps counts new steps.
        reset_policy: Reset policy state at entry (legacy default); disable only for an
            already initialized policy in the same cohort.

    Returns:
        Frame paths, actual executed steps, stop reason and terminal-image unavailability.
        On termination/truncation IsaacLab returns reset images; no terminal image is captured.
    """
    assert type(num_steps) is int and (
        num_steps > 0 or (num_steps == 0 and initial_observation is not None and reset_policy is False)
    ), "Zero-step capture requires an already initialized, non-reset observation"
    assert type(frame_interval) is int and frame_interval > 0, "frame_interval must be positive"
    assert type(step_offset) is int and step_offset >= 0, "step_offset must be nonnegative"
    assert initial_observation is not None or step_offset == 0, "Offset requires initialized observation"
    assert type(reset_policy) is bool, "reset_policy must be boolean"
    assert reset_policy or initial_observation is not None, "Policy reuse requires initialized observation"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = {}
    obs = initial_observation
    if obs is None:
        obs, _ = env.reset()
    if reset_policy:
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

    capture(obs, step_offset)
    if sample_state is not None:
        sample_state(env, step_offset)
    stop_reason = "step_budget"
    executed_steps = 0
    ended = limited = False
    for executed_steps in range(1, num_steps + 1):
        action = policy.get_action(env, obs)
        obs, _, terminated, truncated, _ = env.step(action)
        ended, limited = bool(terminated.any()), bool(truncated.any())
        if ended or limited:
            stop_reason = "terminated_and_truncated" if ended and limited else "terminated" if ended else "truncated"
            break
        if sample_state is not None:
            sample_state(env, step_offset + executed_steps)
        if executed_steps % frame_interval == 0 or executed_steps == num_steps:
            capture(obs, step_offset + executed_steps)
    result = {
        "frames": frames,
        "executed_steps": executed_steps,
        "stop_reason": stop_reason,
        "terminal_image_unavailable": ended or limited,
    }
    if initial_observation is not None:
        result.update(step_offset=step_offset, end_step=step_offset + executed_steps)
    return result
