# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Native mechanics for a released owned worker; importing does not initialize Kit.

These adapters do not grant execution authority or establish calibrated provenance.
The worker owns Kit startup, resource leases, immutable retention and cleanup.
"""

import math
from dataclasses import dataclass
from typing import Any

from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg

LINEAR_SPEED_LIMIT = 1e-3


@dataclass(frozen=True)
class NativeSettleSettings:
    """Frozen reset-relative settle allocation, never a calibrated support claim."""

    settle_steps: int
    subjects: tuple[str, ...]
    angular_velocity_limit: float
    consecutive_steps: int = 1
    camera_names: tuple[str, ...] = ()

    def __post_init__(self):
        assert type(self.settle_steps) is int and 0 < self.settle_steps <= 10000, "Invalid settle allocation"
        assert type(self.consecutive_steps) is int and 0 < self.consecutive_steps <= self.settle_steps
        assert isinstance(self.angular_velocity_limit, (int, float)) and not isinstance(
            self.angular_velocity_limit, bool
        )
        assert math.isfinite(self.angular_velocity_limit) and self.angular_velocity_limit > 0
        for values in (self.subjects, self.camera_names):
            assert type(values) is tuple and len(values) <= 64 and len(set(values)) == len(values)
            assert all(type(value) is str and 0 < len(value) <= 100 for value in values)
        assert self.subjects, "An explicit nonempty velocity subject set is required"


@dataclass(frozen=True)
class InitializedScene:
    """In-process nonterminal cohort; not a durable receipt or execution permission."""

    observation: Any
    hold_action: Any
    step_offset: int
    report: dict


class SceneSettleRejected(RuntimeError):
    """Blocking rejection with bounded diagnostic measurements for worker retention."""

    def __init__(self, report):
        super().__init__("Native settling rejected: " + report["reason"])
        self.report = report


def build_native_environment(
    spec,
    *,
    builder_cfg: ArenaEnvBuilderCfg,
    enable_cameras: bool,
    kit_cameras_enabled: bool,
):
    """Convert a validated graph using Arena's existing builder, returning its wrapper.

    Call only inside an authorized worker after Kit initialization. Camera startup
    is attested by that worker, not inferred from rendering mode or graph settings.
    """
    assert isinstance(builder_cfg, ArenaEnvBuilderCfg), "Typed builder configuration required"
    assert builder_cfg.num_envs == 1, "Native capture requires one environment"
    assert type(enable_cameras) is bool and type(kit_cameras_enabled) is bool, "Boolean camera settings required"
    graph_cameras = spec.embodiment.params.get("enable_cameras", enable_cameras)
    assert type(graph_cameras) is bool, "Boolean graph camera setting required"
    if enable_cameras or graph_cameras:
        assert kit_cameras_enabled, "Kit cameras must be enabled before construction"
    if enable_cameras:
        assert graph_cameras, "Explicit graph camera conflict"
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder

    arena_env = spec.to_arena_env(enable_cameras=enable_cameras)
    return ArenaEnvBuilder(arena_env, cfg=builder_cfg).make_registered()


def build_droid_posture_hold(env):
    """Freeze measured DROID absolute arm targets and the nearest binary gripper state.

    Resolve selected joint indices and term order from the live action manager, not
    articulation order or action width. Unsupported/clipped terms fail closed. A
    binary gripper cannot hold an intermediate angle; its nearest configured open
    or closed endpoint is selected (an equidistant state is ambiguous and rejected).
    """
    import torch

    from isaaclab.envs.mdp.actions.joint_actions import JointPositionAction

    from isaaclab_arena.embodiments.droid.actions import BinaryJointPositionZeroToOneAction

    base = env.unwrapped
    manager = base.action_manager
    assert base.num_envs == 1, "DROID hold requires one environment"
    assert set(manager.active_terms) == {
        "arm_action",
        "gripper_action",
    }, "Unsupported DROID action terms"
    arm, gripper = manager.get_term("arm_action"), manager.get_term("gripper_action")
    assert type(arm) is JointPositionAction, "DROID hold requires absolute joint position action"
    assert type(gripper) is BinaryJointPositionZeroToOneAction, "Unsupported DROID gripper semantics"
    assert arm.action_dim == 7 and gripper.action_dim == 1, "Unsupported DROID action dimensions"
    assert arm._asset is gripper._asset, "DROID action terms must target the same articulation"
    assert not arm.cfg.use_default_offset, "Expected DROID absolute action without default offset"
    assert arm.cfg.clip is None and gripper.cfg.clip is None, "Clipped DROID actions are unsupported"

    def tensor(value):
        if isinstance(value, torch.Tensor):
            return value
        import warp as wp

        return wp.to_torch(value)

    posture = tensor(arm._asset.data.joint_pos).detach().clone()
    assert bool(torch.isfinite(posture).all()), "Nonfinite DROID posture"
    scale = torch.as_tensor(arm._scale, device=posture.device)
    offset = torch.as_tensor(arm._offset, device=posture.device)
    assert bool(torch.isfinite(scale).all() and (scale != 0).all()), "Invalid arm scale"
    assert bool(torch.isfinite(offset).all()), "Nonfinite arm offset"
    arm_action = (posture[:, arm._joint_ids] - offset) / scale
    finger = posture[:, gripper._joint_ids]
    open_target, close_target = gripper._open_command, gripper._close_command
    assert bool(torch.isfinite(open_target).all() and torch.isfinite(close_target).all()), "Invalid gripper targets"
    open_distance = torch.linalg.vector_norm(finger - open_target, dim=-1, keepdim=True)
    close_distance = torch.linalg.vector_norm(finger - close_target, dim=-1, keepdim=True)
    assert bool((open_distance != close_distance).all()), "Ambiguous binary gripper posture"
    gripper_action = (close_distance < open_distance).to(dtype=posture.dtype)
    pieces = {"arm_action": arm_action, "gripper_action": gripper_action}
    action = torch.cat([pieces[name] for name in manager.active_terms], dim=-1).to(base.device)
    assert action.shape == (1, manager.total_action_dim) and bool(torch.isfinite(action).all()), "Invalid hold action"
    return action


def sample_native_velocities(env, subjects):
    """Read singleton raw world velocity vectors through Arena's existing getters."""
    from isaaclab_arena.tasks.predicates.predicate_utils import get_root_ang_vel_w, get_root_lin_vel_w

    result = {}
    for name in subjects:
        values = {}
        for key, getter in (
            ("linear_velocity_w", get_root_lin_vel_w),
            ("angular_velocity_w", get_root_ang_vel_w),
        ):
            value = getter(env.unwrapped, name)
            if tuple(value.shape) != (1, 3):
                raise ValueError("Expected singleton world velocity vector")
            values[key] = value[0].detach().cpu().tolist()
        result[name] = values
    return result


def initialize_and_settle(
    env,
    *,
    settings: NativeSettleSettings,
    charge_step,
    sample_velocities=sample_native_velocities,
    hold_action_factory=build_droid_posture_hold,
) -> InitializedScene:
    """Reset once and hold for the entire frozen allocation, then block unless settled.

    Args:
        env: Wrapped single environment, owned by the caller.
        settings: Frozen subjects, camera keys, duration and final consecutive window.
        charge_step: Trusted accounting/cancellation callback before each control step.
        sample_velocities: Trusted callback(env, subjects) returning exact subject maps
            with raw world linear_velocity_w and angular_velocity_w 3-vectors.
        hold_action_factory: Embodiment adapter called once after reset, before stepping.

    Returns:
        The final observation and absolute offset for initialized capture or rollout.
        Settling never ends early: the admitted post-settle window has a fixed start.
        No policy/model is constructed, no physics is changed and no environment is closed.
    """
    assert isinstance(settings, NativeSettleSettings), "Frozen settling settings required"
    assert env.unwrapped.num_envs == 1, "Native settling requires one environment"
    report = {
        "all_objects_settled": False,
        "reason": "unsettled",
        "executed_steps": 0,
        "linear_speed_limit": LINEAR_SPEED_LIMIT,
        "angular_speed_limit": settings.angular_velocity_limit,
        "comparison": "strict_less_than_raw_norm",
        "samples": [],
    }

    def reject(reason):
        report["reason"] = reason
        raise SceneSettleRejected(report)

    def cameras_available(obs):
        if not all(name in obs.get("camera_obs", {}) for name in settings.camera_names):
            reject("camera_unavailable")

    def norm(vector):
        if not isinstance(vector, (list, tuple)) or len(vector) != 3:
            raise ValueError("Invalid velocity vector")
        if not all(type(v) in (int, float) and math.isfinite(v) for v in vector):
            raise ValueError("Nonfinite or nonnumeric velocity")
        result = math.hypot(*vector)
        if not math.isfinite(result):
            raise ValueError("Nonfinite velocity norm")
        return result

    obs, _ = env.reset()
    cameras_available(obs)
    action = hold_action_factory(env)
    consecutive = 0
    for step in range(1, settings.settle_steps + 1):
        charge_step(step)
        report["executed_steps"] = step
        obs, _, terminated, truncated, _ = env.step(action)
        ended, limited = bool(terminated.any()), bool(truncated.any())
        if ended or limited:
            reject("terminated_and_truncated" if ended and limited else "terminated" if ended else "truncated")
        cameras_available(obs)
        try:
            measured = sample_velocities(env, settings.subjects)
            if set(measured) != set(settings.subjects):
                raise ValueError("Incomplete velocity subjects")
            subjects = {}
            for name in settings.subjects:
                linear = measured[name]["linear_velocity_w"]
                angular = measured[name]["angular_velocity_w"]
                speed, angular_speed = norm(linear), norm(angular)
                subjects[name] = {
                    "linear_velocity_w": list(linear),
                    "angular_velocity_w": list(angular),
                    "linear_speed": speed,
                    "angular_speed": angular_speed,
                    "settled": speed < LINEAR_SPEED_LIMIT and angular_speed < settings.angular_velocity_limit,
                }
        except (ValueError, TypeError, KeyError, OverflowError):
            reject("invalid_measurement")
        report["samples"].append({"step": step, "subjects": subjects})
        consecutive = consecutive + 1 if all(item["settled"] for item in subjects.values()) else 0
    if consecutive < settings.consecutive_steps:
        reject("unsettled")
    report.update(all_objects_settled=True, reason="settled")
    return InitializedScene(obs, action, settings.settle_steps, report)
