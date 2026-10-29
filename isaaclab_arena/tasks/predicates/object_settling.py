# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Instantaneous rest checks and initial rest-pose recording."""

from __future__ import annotations

import torch
from typing import TYPE_CHECKING

from isaaclab_arena.tasks.predicates.predicate_utils import (
    get_env,
    get_root_ang_vel_w,
    get_root_lin_vel_w,
    get_root_pos_w,
    select,
)

if TYPE_CHECKING:
    from isaaclab.scene import InteractiveScene

    from isaaclab_arena.environments.arena_world import ArenaWorld
    from isaaclab_arena.environments.isaaclab_arena_manager_based_env import IsaacLabArenaManagerBasedRLEnv


DEFAULT_LINEAR_VELOCITY_THRESHOLD = 1e-2
DEFAULT_ANGULAR_VELOCITY_THRESHOLD = 5e-2


class ObjectInitialRestPoseRecorder:
    """Recorder object that works in conjunction with the ``objects_settled`` predicate to record the
    initial resting poses of scene objects and expose to downstream predicates.
    """

    def __init__(self, num_envs: int, device):
        self._num_envs = num_envs
        self._device = device
        self._entries: dict[str, dict[str, torch.Tensor]] = {}

    def _entry(self, name: str) -> dict[str, torch.Tensor]:
        """Get or create the ``{position, settled}`` record for one object."""

        entry = self._entries.get(name)
        if entry is None:
            entry = {
                "position": torch.full((self._num_envs, 3), float("nan"), device=self._device),
                "settled": torch.zeros(self._num_envs, dtype=torch.bool, device=self._device),
            }
            self._entries[name] = entry
        return entry

    def record(self, name: str, positions: torch.Tensor, settled: torch.Tensor) -> None:
        """Record object's world position for envs that just settled and weren't recorded yet."""

        entry = self._entry(name)
        new = settled & ~entry["settled"]
        if bool(new.any()):
            entry["position"] = torch.where(new.unsqueeze(-1), positions, entry["position"])
            entry["settled"] = entry["settled"] | new

    def get(self, name: str) -> tuple[torch.Tensor, torch.Tensor]:
        """Return ``(position, settled)`` for object's recorded initial rest pose."""

        entry = self._entry(name)
        return entry["position"], entry["settled"]

    def reset(self, env_ids=None) -> None:
        """Clear recorded rest poses for ``env_ids``."""

        if env_ids is None:
            ids = slice(None)
        elif isinstance(env_ids, slice):
            ids = env_ids
        else:
            ids = torch.as_tensor(env_ids, dtype=torch.long, device=self._device)
        for entry in self._entries.values():
            entry["settled"][ids] = False
            entry["position"][ids] = float("nan")


def get_rest_pose_recorder(env: IsaacLabArenaManagerBasedRLEnv) -> ObjectInitialRestPoseRecorder:
    """Return the ``ObjectInitialRestPoseRecorder`` owned by the Arena environment."""

    env = get_env(env)
    recorder = getattr(env, "object_initial_rest_pose_recorder", None)
    if recorder is None:
        recorder = ObjectInitialRestPoseRecorder(env.num_envs, env.device)
        env.object_initial_rest_pose_recorder = recorder
    return recorder


def reset_rest_pose_recorder(env: IsaacLabArenaManagerBasedRLEnv, env_ids=None) -> None:
    """Clear every recorded initial rest pose for ``env_ids``."""

    recorder = getattr(get_env(env), "object_initial_rest_pose_recorder", None)
    if recorder is not None:
        recorder.reset(env_ids)


def get_object_initial_rest_state(
    env: IsaacLabArenaManagerBasedRLEnv,
    name: str,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return ``(position, settled)`` for an object's recorded initial rest pose.

    ``position`` (num_envs, 3) is meaningful only for envs whose ``settled`` mask (num_envs,) is True.
    """

    return get_rest_pose_recorder(env).get(name)


def compute_objects_settled_mask(
    arena_world: ArenaWorld,
    scene: InteractiveScene,
    object_names: list[str],
    lin_vel_threshold: float,
    ang_vel_threshold: float,
) -> torch.Tensor:
    """Return a per-env mask that is True when every named object is below velocity thresholds.

    Rigid objects use root linear and angular speed. Deformable objects use the 90th percentile of
    nodal linear speeds and have no angular-speed condition.

    Args:
        arena_world: Arena scene query facade.
        scene: Live scene (used to detect deformable objects).
        object_names: Object scene keys to check.
        lin_vel_threshold: Linear speed threshold in meters per second.
        ang_vel_threshold: Angular speed threshold in radians per second (rigid objects only).

    Returns:
        Boolean mask with shape ``(num_envs,)``.
    """
    if not object_names:
        return torch.ones(scene.num_envs, dtype=torch.bool, device=scene.device)

    per_object_settled = []
    for object_name in object_names:
        if object_name in scene.deformable_objects:
            nodal_velocity_w = arena_world.get_nodal_velocities_w(object_name)
            nodal_speed = torch.linalg.vector_norm(nodal_velocity_w, dim=-1)
            linear_speed = torch.quantile(nodal_speed, q=0.9, dim=1)
            per_object_settled.append(linear_speed < lin_vel_threshold)
            continue
        root_linear_velocity_w = arena_world.get_root_linear_velocity_w(object_name)
        linear_speed = torch.linalg.vector_norm(root_linear_velocity_w, dim=-1)
        root_angular_velocity_w = arena_world.get_root_angular_velocity_w(object_name)
        angular_speed = torch.linalg.vector_norm(root_angular_velocity_w, dim=-1)
        per_object_settled.append((linear_speed < lin_vel_threshold) & (angular_speed < ang_vel_threshold))
    return torch.stack(per_object_settled, dim=0).all(dim=0)


def objects_settled(
    env: IsaacLabArenaManagerBasedRLEnv,
    object_names: list[str],
    lin_vel_threshold: float = DEFAULT_LINEAR_VELOCITY_THRESHOLD,
    ang_vel_threshold: float = DEFAULT_ANGULAR_VELOCITY_THRESHOLD,
    env_id: int | None = None,
) -> torch.Tensor:
    """Check whether every named object is at rest and record its first resting position.

    Rigid objects use root linear and angular speed. Deformable objects use the 90th percentile of
    nodal linear speeds and have no angular-speed condition. Recorded rest poses are readable via
    ``get_object_initial_rest_state``.
    """

    settled = objects_below_velocity_thresholds(
        env,
        object_names=object_names,
        lin_vel_threshold=lin_vel_threshold,
        ang_vel_threshold=ang_vel_threshold,
    )

    unwrapped = get_env(env)
    has_arena_world = hasattr(unwrapped, "arena_world") and unwrapped.arena_world is not None
    recorder = get_rest_pose_recorder(unwrapped)
    for object_name in object_names:
        if has_arena_world:
            object_position_w = unwrapped.arena_world.get_position_w(object_name)
        else:
            object_position_w = get_root_pos_w(unwrapped, object_name)
        recorder.record(object_name, object_position_w, settled)

    return select(settled, env_id)


def objects_below_velocity_thresholds(
    env: IsaacLabArenaManagerBasedRLEnv,
    object_names: list[str],
    lin_vel_threshold: float = DEFAULT_LINEAR_VELOCITY_THRESHOLD,
    ang_vel_threshold: float = DEFAULT_ANGULAR_VELOCITY_THRESHOLD,
) -> torch.Tensor:
    """Return whether all named objects meet their speed limits in each environment.

    This check does not record resting positions or count consecutive steps.
    """

    unwrapped = get_env(env)
    if hasattr(unwrapped, "arena_world") and unwrapped.arena_world is not None:
        return compute_objects_settled_mask(
            unwrapped.arena_world,
            unwrapped.scene,
            object_names,
            lin_vel_threshold,
            ang_vel_threshold,
        )
    if not object_names:
        return torch.ones(unwrapped.num_envs, dtype=torch.bool, device=unwrapped.device)
    per_object_settled = []
    for object_name in object_names:
        linear_speed = torch.linalg.vector_norm(get_root_lin_vel_w(unwrapped, object_name), dim=-1)
        angular_speed = torch.linalg.vector_norm(get_root_ang_vel_w(unwrapped, object_name), dim=-1)
        per_object_settled.append((linear_speed < lin_vel_threshold) & (angular_speed < ang_vel_threshold))
    return torch.stack(per_object_settled, dim=0).all(dim=0)
