# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Stateless spatial predicates and geometric checks."""

from __future__ import annotations

import math
import torch
from typing import TYPE_CHECKING

import warp as wp
from isaaclab.assets import RigidObject
from isaaclab.envs import ManagerBasedRLEnv
from isaaclab.managers import SceneEntityCfg
from isaaclab.sensors.contact_sensor.contact_sensor import ContactSensor
from isaaclab.utils.math import quat_apply, quat_apply_inverse

from isaaclab_arena.tasks.predicates.episode_state import get_episode_scoped_state
from isaaclab_arena.tasks.predicates.object_settling import get_object_initial_rest_state
from isaaclab_arena.tasks.predicates.predicate_utils import get_env, get_root_lin_vel_w, get_root_pos_w, select
from isaaclab_arena.utils.bounding_box import AxisAlignedBoundingBox

if TYPE_CHECKING:
    from isaaclab_arena.embodiments.gripper import Gripper
    from isaaclab_arena.environments.isaaclab_arena_manager_based_env import IsaacLabArenaManagerBasedRLEnv


def gripper_distance_from_object_exceeds_threshold(
    env: IsaacLabArenaManagerBasedRLEnv,
    subject_name: str,
    gripper: Gripper,
    distance_threshold_m: float,
) -> torch.Tensor:
    """Check that a gripper is farther than a threshold from an object.

    Args:
        env: Environment supplying object and frame positions through ArenaWorld.
        subject_name: Object asset whose origin defines the distance.
        gripper: Embodiment-owned gripper implementation.
        distance_threshold_m: Strict minimum distance, in meters.

    Returns:
        Boolean tensor with one result per environment.
    """
    assert (
        math.isfinite(distance_threshold_m) and distance_threshold_m >= 0.0
    ), "Distance threshold must be non-negative and finite."
    gripper_position_W = gripper.get_position_w(env.arena_world)
    subject_position_W = env.arena_world.get_pose_w(subject_name)[:, :3]
    return torch.linalg.vector_norm(subject_position_W - gripper_position_W, dim=-1) > distance_threshold_m


def object_bounds_center_over_destination(
    object_centroid_W: torch.Tensor,
    T_W_D: torch.Tensor,
    destination_bounds_D: AxisAlignedBoundingBox,
) -> torch.Tensor:
    """Check whether an object's bounds center is over a destination.

    The check requires the object's bounds center to be inside the destination's
    X/Y footprint and above its lower Z bound. The upper Z bound is intentionally
    ignored so the same check works for open containers and supporting surfaces.
    This is a center-point test, not full-object containment.

    Args:
        object_centroid_W: Object geometry centroid expressed in world frame
            ``W``. Shape is ``(num_envs, 3)``.
        T_W_D: Destination poses mapping points from destination frame ``D``
            into world frame ``W``. Shape is ``(num_envs, 7)`` with quaternion
            order ``(x, y, z, w)``.
        destination_bounds_D: Destination bounds aligned with frame ``D`` and
            measured from its origin.

    Returns:
        One Boolean result per environment.
    """
    t_W_D, q_W_D = T_W_D[:, :3], T_W_D[:, 3:]

    object_centroid_D = quat_apply_inverse(
        q_W_D,
        object_centroid_W - t_W_D,
    )
    center_inside_horizontal_bounds = (
        (object_centroid_D[:, :2] >= destination_bounds_D.min_point[:, :2])
        & (object_centroid_D[:, :2] <= destination_bounds_D.max_point[:, :2])
    ).all(dim=-1)
    center_above_destination_bottom = object_centroid_D[:, 2] >= destination_bounds_D.min_point[:, 2]
    return center_inside_horizontal_bounds & center_above_destination_bottom


def contact_force_is_upward_support(
    contact_force_w: torch.Tensor,
    force_threshold: float,
    support_cone_half_angle_rad: float,
) -> torch.Tensor:
    """Check whether contact forces point upward strongly enough.

    Args:
        contact_force_w: World-frame force vectors with shape
            ``(num_envs, 3)`` in newtons.
        force_threshold: Minimum force magnitude in newtons.
        support_cone_half_angle_rad: Maximum angle in radians between the force
            vector and world ``+Z``. Zero accepts only a straight-up force.

    Returns:
        One Boolean result per environment.
    """
    assert (
        contact_force_w.ndim == 2 and contact_force_w.shape[1] == 3
    ), f"contact_force_w must have shape (num_envs, 3), got {tuple(contact_force_w.shape)}."
    assert force_threshold >= 0.0, f"force_threshold must be non-negative, got {force_threshold}."
    assert (
        0.0 <= support_cone_half_angle_rad < math.pi / 2
    ), f"support_cone_half_angle_rad must be in [0, pi / 2), got {support_cone_half_angle_rad}."

    force_magnitude = torch.linalg.vector_norm(contact_force_w, dim=-1)
    upward_force = contact_force_w[:, 2]
    minimum_upward_fraction = math.cos(support_cone_half_angle_rad)
    return (
        (force_magnitude >= force_threshold)
        & (upward_force > 0.0)
        & (upward_force >= force_magnitude * minimum_upward_fraction)
    )


def object_is_moving_slowly(
    object_linear_velocity_w: torch.Tensor,
    velocity_threshold: float,
) -> torch.Tensor:
    """Check whether object linear speed is below the threshold."""
    return torch.linalg.vector_norm(object_linear_velocity_w, dim=-1) < velocity_threshold


def _position_relative_to_target(
    env: IsaacLabArenaManagerBasedRLEnv,
    subject_name: str,
    receiver_name: str,
    target_offset_xyz: tuple[float, float, float],
    subject_offset_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> torch.Tensor:
    """Return a subject-local point relative to a target, expressed in the receiver frame."""
    arena_world = env.arena_world
    T_W_S = arena_world.get_pose_w(subject_name)
    T_W_R = arena_world.get_pose_w(receiver_name)
    subject_offset_S = torch.as_tensor(subject_offset_xyz, dtype=T_W_S.dtype, device=T_W_S.device)
    subject_point_W = T_W_S[:, :3] + quat_apply(T_W_S[:, 3:], subject_offset_S.expand(env.num_envs, -1))
    position_R = quat_apply_inverse(T_W_R[:, 3:], subject_point_W - T_W_R[:, :3])
    target_position_R = torch.as_tensor(target_offset_xyz, dtype=position_R.dtype, device=position_R.device)
    return position_R - target_position_R


def _normalized_axis(axis: tuple[float, float, float], reference: torch.Tensor) -> torch.Tensor:
    """Return a unit axis matching the reference tensor's dtype and device."""
    vector = torch.as_tensor(axis, dtype=reference.dtype, device=reference.device)
    assert vector.shape == (3,) and torch.linalg.vector_norm(vector) > 0
    return vector / torch.linalg.vector_norm(vector)


def _relative_axial_distances(
    env: IsaacLabArenaManagerBasedRLEnv,
    subject_name: str,
    receiver_name: str,
    target_offset_xyz: tuple[float, float, float],
    subject_offset_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0),
    receiver_axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return signed axial depth and perpendicular distance from a receiver-local target."""
    position_R = _position_relative_to_target(env, subject_name, receiver_name, target_offset_xyz, subject_offset_xyz)
    axis_R = _normalized_axis(receiver_axis, position_R)
    depth = torch.sum(position_R * axis_R, dim=-1)
    lateral = torch.linalg.vector_norm(position_R - depth[:, None] * axis_R, dim=-1)
    return depth, lateral


def lateral_in_proximity(
    env: IsaacLabArenaManagerBasedRLEnv,
    subject_name: str,
    receiver_name: str,
    target_offset_xyz: tuple[float, float, float],
    tolerance_lateral: float,
    *,
    subject_offset_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0),
    receiver_axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> torch.Tensor:
    """Check point proximity perpendicular to a receiver-local axis."""
    _, lateral = _relative_axial_distances(
        env, subject_name, receiver_name, target_offset_xyz, subject_offset_xyz, receiver_axis
    )
    return lateral <= tolerance_lateral


def depth_in_range(
    env: IsaacLabArenaManagerBasedRLEnv,
    subject_name: str,
    receiver_name: str,
    target_offset_xyz: tuple[float, float, float],
    depth_min: float,
    depth_max: float | None,
    *,
    subject_offset_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0),
    receiver_axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> torch.Tensor:
    """Check point depth relative to a receiver-local target along its configured axis."""
    assert (
        depth_max is None or depth_min <= depth_max
    ), f"depth_min ({depth_min}) must not exceed depth_max ({depth_max})."
    depth, _ = _relative_axial_distances(
        env, subject_name, receiver_name, target_offset_xyz, subject_offset_xyz, receiver_axis
    )
    result = depth >= depth_min
    if depth_max is not None:
        result &= depth <= depth_max
    return result


def tilt_axis_aligned(
    env: IsaacLabArenaManagerBasedRLEnv,
    subject_name: str,
    receiver_name: str,
    max_tilt_rad: float,
    subject_axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
    receiver_axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
    *,
    allow_antiparallel: bool = False,
) -> torch.Tensor:
    """Check the angle between configured axes, optionally accepting opposite directions."""
    assert 0.0 <= max_tilt_rad <= math.pi, f"max_tilt_rad must be in [0, pi], got {max_tilt_rad}."
    arena_world = env.arena_world
    T_W_S = arena_world.get_pose_w(subject_name)
    T_W_R = arena_world.get_pose_w(receiver_name)
    subject_axis_F = _normalized_axis(subject_axis, T_W_S)
    receiver_axis_F = _normalized_axis(receiver_axis, T_W_R)
    subject_axis_w = quat_apply(T_W_S[:, 3:], subject_axis_F.expand(env.num_envs, -1))
    receiver_axis_w = quat_apply(T_W_R[:, 3:], receiver_axis_F.expand(env.num_envs, -1))
    axis_dot = torch.sum(subject_axis_w * receiver_axis_w, dim=-1)
    if allow_antiparallel:
        axis_dot = torch.abs(axis_dot)
    return axis_dot >= math.cos(max_tilt_rad)


def velocity_below_threshold(
    env: IsaacLabArenaManagerBasedRLEnv,
    subject_name: str,
    linear_velocity_threshold: float,
    angular_velocity_threshold: float | None = None,
) -> torch.Tensor:
    """Check subject root linear speed and, optionally, angular speed."""
    arena_world = env.arena_world
    linear_velocity_w = arena_world.get_root_linear_velocity_w(subject_name)
    result = torch.linalg.vector_norm(linear_velocity_w, dim=-1) <= linear_velocity_threshold
    if angular_velocity_threshold is not None:
        angular_velocity_w = arena_world.get_root_angular_velocity_w(subject_name)
        result &= torch.linalg.vector_norm(angular_velocity_w, dim=-1) <= angular_velocity_threshold
    return result


def object_is_above_height(
    env: IsaacLabArenaManagerBasedRLEnv,
    object_name: str,
    surface_height: float | None = None,
    use_settled_state: bool = False,
    distance: float = 1e-2,
    env_id: int | None = None,
) -> torch.Tensor:
    """Checks if an object is above a certain height."""
    assert (
        surface_height is not None
    ) != use_settled_state, "object_is_above_height requires exactly one of surface_height or use_settled_state"

    if hasattr(env, "arena_world"):
        object_z = env.arena_world.get_position_w(object_name)[:, 2]
    else:
        object_z = get_root_pos_w(env, object_name)[:, 2]
    if use_settled_state:
        settled_pos, has_settled = get_object_initial_rest_state(env, object_name)
        result = has_settled & (object_z > (settled_pos[:, 2] + distance))
    else:
        result = object_z > (surface_height + distance)
    return select(result, env_id) if env_id is not None else result


def object_lifted_above_resting_min(
    env: ManagerBasedRLEnv,
    object_name: str,
    distance: float = 5e-2,
    rest_speed_threshold: float = 5e-2,
    rest_steps_required: int = 3,
    min_airborne_steps: int = 1,
    env_id: int | None = None,
) -> torch.Tensor:
    """Checks if an object has been held ``distance`` m above its resting height, for a duration."""
    state = get_episode_scoped_state(env)
    speed = torch.linalg.vector_norm(get_root_lin_vel_w(env, object_name), dim=-1)
    rest_run = state.run_length(f"rest_run::{object_name}", speed < rest_speed_threshold)
    has_rested = state.latch(f"has_rested::{object_name}", 1, 0, rest_run >= rest_steps_required)

    object_z = get_root_pos_w(env, object_name)[:, 2]
    reference_z = state.running_min(
        f"resting_min_z::{object_name}", torch.where(has_rested, object_z, torch.full_like(object_z, float("inf")))
    )
    above_threshold = has_rested & (object_z > (reference_z + distance))
    airborne_run = state.run_length(f"airborne_run::{object_name}", above_threshold)
    return select(airborne_run >= min_airborne_steps, env_id)


def object_moving(
    env: IsaacLabArenaManagerBasedRLEnv,
    object_name: str,
    velocity_threshold: float = 1e-2,
) -> torch.Tensor:
    """Check whether an object is moving above a velocity threshold."""
    arena_world = env.arena_world
    object_mean_linear_velocity_w = arena_world.get_mean_linear_velocity_w(object_name)
    speed = torch.linalg.vector_norm(object_mean_linear_velocity_w, dim=-1)
    return speed > velocity_threshold


def objects_in_proximity(
    env: IsaacLabArenaManagerBasedRLEnv,
    object_cfg: SceneEntityCfg,
    target_object_cfg: SceneEntityCfg,
    max_y_separation: float,
    max_x_separation: float,
    max_z_separation: float,
) -> torch.Tensor:
    """Determine if two objects are within a certain proximity of each other."""
    if hasattr(env, "arena_world"):
        arena_world = env.arena_world
        object_position_w = arena_world.get_position_w(object_cfg.name)
        target_object_position_w = arena_world.get_position_w(target_object_cfg.name)
    else:
        object_position_w = get_root_pos_w(env, object_cfg.name)
        target_object_position_w = get_root_pos_w(env, target_object_cfg.name)

    x_separation = torch.abs(object_position_w[:, 0] - target_object_position_w[:, 0])
    y_separation = torch.abs(object_position_w[:, 1] - target_object_position_w[:, 1])
    z_separation = torch.abs(object_position_w[:, 2] - target_object_position_w[:, 2])

    done = x_separation < max_x_separation
    done = torch.logical_and(done, y_separation < max_y_separation)
    done = torch.logical_and(done, z_separation < max_z_separation)

    return done


def object_supported_by(
    object_vertices_pos_w: torch.Tensor,
    destination_bound: AxisAlignedBoundingBox,
    support_tolerance: float = 0.03,
    low_point_tolerance: float = 0.01,
    minimum_support_fraction: float = 0.5,
) -> torch.Tensor:
    """Check whether a large fraction of object's lowest vertices are close to the destination's top surface."""
    low_z = object_vertices_pos_w[..., 2].amin(dim=1, keepdim=True)
    low_mask = object_vertices_pos_w[..., 2] <= low_z + low_point_tolerance
    near_top = torch.abs(object_vertices_pos_w[..., 2] - destination_bound.top_surface_z[:, None]) <= support_tolerance
    inside_footprint = (
        (object_vertices_pos_w[..., :2] >= destination_bound.min_point[:, None, :2])
        & (object_vertices_pos_w[..., :2] <= destination_bound.max_point[:, None, :2])
    ).all(dim=-1)
    supported_points = low_mask & near_top & inside_footprint
    support_fraction = supported_points.sum(dim=1) / low_mask.sum(dim=1).clamp_min(1)
    return support_fraction >= minimum_support_fraction


def object_on_destination(
    env: IsaacLabArenaManagerBasedRLEnv,
    object_cfg: SceneEntityCfg = SceneEntityCfg("pick_up_object"),
    destination_cfg: SceneEntityCfg | None = None,
    contact_sensor_cfg: SceneEntityCfg | None = SceneEntityCfg("pick_up_object_contact_sensor"),
    force_threshold: float = 1.0,
    velocity_threshold: float = 0.5,
    support_cone_half_angle_rad: float = math.pi / 4,
    max_xy_separation: float | None = None,
) -> torch.Tensor:
    """Check whether an object is stably placed on its destination."""
    if not hasattr(env, "arena_world") or max_xy_separation is not None:
        unwrapped_env = get_env(env)
        object: RigidObject = unwrapped_env.scene[object_cfg.name]
        assert contact_sensor_cfg is not None
        sensor: ContactSensor = unwrapped_env.scene[contact_sensor_cfg.name]
        assert sensor.data.force_matrix_w.shape[1] == 1
        force_matrix_norm = torch.norm(wp.to_torch(sensor.data.force_matrix_w), dim=-1).max(dim=-1).values.reshape(-1)
        force_above_threshold = force_matrix_norm > force_threshold

        velocity_w = wp.to_torch(object.data.root_lin_vel_w)
        velocity_w_norm = torch.norm(velocity_w, dim=-1)
        vel_ok = velocity_w_norm < velocity_threshold

        condition_met = torch.logical_and(force_above_threshold, vel_ok)

        if max_xy_separation is not None:
            assert destination_cfg is not None, "max_xy_separation requires destination_cfg"
            destination: RigidObject = unwrapped_env.scene[destination_cfg.name]
            object_xy = wp.to_torch(object.data.root_pos_w)[:, :2]
            destination_xy = wp.to_torch(destination.data.root_pos_w)[:, :2]
            xy_separation = torch.linalg.vector_norm(object_xy - destination_xy, dim=-1)
            condition_met = torch.logical_and(condition_met, xy_separation < max_xy_separation)

        return condition_met

    assert destination_cfg is not None, "object_on_destination requires destination_cfg"
    arena_world = env.arena_world
    assert (
        destination_cfg.name not in env.scene.deformable_objects
    ), "object_on_destination does not support deformable destinations"

    object_center_over_destination = object_bounds_center_over_destination(
        object_centroid_W=arena_world.get_centroid_w(object_cfg.name),
        T_W_D=arena_world.get_pose_w(destination_cfg.name),
        destination_bounds_D=arena_world.get_aabb_in_local_frame(destination_cfg.name),
    )

    if object_cfg.name in env.scene.deformable_objects:
        object_vertices_w = arena_world.get_vertices_w(object_cfg.name)
        destination_vertices_w = arena_world.get_vertices_w(destination_cfg.name)
        destination_bound = AxisAlignedBoundingBox(
            min_point=destination_vertices_w.amin(dim=1),
            max_point=destination_vertices_w.amax(dim=1),
        )
        destination_provides_upward_support = object_supported_by(
            object_vertices_pos_w=object_vertices_w,
            destination_bound=destination_bound,
        )
    else:
        assert contact_sensor_cfg is not None, "object_on_destination requires a contact sensor for rigid objects"
        contact_sensor: ContactSensor = env.scene[contact_sensor_cfg.name]
        force_matrix_w = contact_sensor.data.force_matrix_w
        assert force_matrix_w is not None, f"Contact sensor '{contact_sensor_cfg.name}' has no filtered force matrix."
        force_matrix_w = force_matrix_w.torch if hasattr(force_matrix_w, "torch") else wp.to_torch(force_matrix_w)
        assert force_matrix_w.shape == (env.num_envs, 1, 1, 3), (
            f"Contact sensor '{contact_sensor_cfg.name}' must provide one sensed body and one filtered body; "
            f"got force shape {tuple(force_matrix_w.shape)}."
        )
        support_force_on_object_w = force_matrix_w[:, 0, 0, :]
        destination_provides_upward_support = contact_force_is_upward_support(
            contact_force_w=support_force_on_object_w,
            force_threshold=force_threshold,
            support_cone_half_angle_rad=support_cone_half_angle_rad,
        )

    object_mean_linear_velocity_w = arena_world.get_mean_linear_velocity_w(object_cfg.name)
    object_moves_slowly = object_is_moving_slowly(object_mean_linear_velocity_w, velocity_threshold)
    return object_center_over_destination & destination_provides_upward_support & object_moves_slowly


def objects_on_destinations(
    env: ManagerBasedRLEnv,
    object_cfg_list: list[SceneEntityCfg] = [SceneEntityCfg("pick_up_object")],
    contact_sensor_cfg_list: list[SceneEntityCfg] = [SceneEntityCfg("pick_up_object_contact_sensor")],
    force_threshold: float = 1.0,
    velocity_threshold: float = 0.5,
) -> torch.Tensor:
    """Multi-object version of `object_on_destination`."""
    assert len(object_cfg_list) == len(contact_sensor_cfg_list), (
        "object_cfg_list and contact_sensor_cfg_list must have equal length, got "
        f"{len(object_cfg_list)} objects and {len(contact_sensor_cfg_list)} sensors"
    )

    unwrapped_env = get_env(env)
    condition_met = torch.ones((unwrapped_env.num_envs), device=unwrapped_env.device, dtype=torch.bool)
    for object_cfg, contact_sensor_cfg in zip(object_cfg_list, contact_sensor_cfg_list):
        single_condition = object_on_destination(
            env=env,
            object_cfg=object_cfg,
            contact_sensor_cfg=contact_sensor_cfg,
            force_threshold=force_threshold,
            velocity_threshold=velocity_threshold,
        )
        condition_met = torch.logical_and(condition_met, single_condition)
    return condition_met


def object_in_target_aabb(
    env: IsaacLabArenaManagerBasedRLEnv,
    object_name: str,
    target_name: str,
    minimum_contained_fraction: float = 1.0,
) -> torch.Tensor:
    """Check the fraction of object AABB volume within the target world-frame AABB."""
    assert math.isfinite(minimum_contained_fraction) and 0 < minimum_contained_fraction <= 1
    object_aabb_W = env.arena_world.get_aabb_w(object_name)
    target_aabb_W = env.arena_world.get_aabb_w(target_name)
    return object_aabb_W.volume_fraction_within(target_aabb_W) >= minimum_contained_fraction


def object_in_contact_with_target(
    env: IsaacLabArenaManagerBasedRLEnv,
    contact_sensor_cfg: SceneEntityCfg,
    force_threshold: float,
) -> torch.Tensor:
    """Check contact with a destination using an object sensor filtered to that destination."""
    assert (
        math.isfinite(force_threshold) and force_threshold > 0
    ), "Contact force threshold must be positive and finite."
    force_matrix = env.scene[contact_sensor_cfg.name].data.force_matrix_w
    assert force_matrix is not None, "Destination contact requires a filtered contact sensor."
    forces_W = force_matrix.torch if hasattr(force_matrix, "torch") else wp.to_torch(force_matrix)
    return (torch.linalg.vector_norm(forces_W, dim=-1) >= force_threshold).flatten(start_dim=1).any(dim=-1)


def object_settled_in_target_aabb(
    env: IsaacLabArenaManagerBasedRLEnv,
    object_name: str,
    target_name: str,
    contact_sensor_cfg: SceneEntityCfg,
    minimum_contained_fraction: float,
    contact_force_threshold: float,
    linear_velocity_threshold: float,
    angular_velocity_threshold: float,
) -> torch.Tensor:
    """Check world-AABB volume containment, target contact, and low velocity for the current step."""
    contained = object_in_target_aabb(env, object_name, target_name, minimum_contained_fraction)
    touching = object_in_contact_with_target(env, contact_sensor_cfg, contact_force_threshold)
    settled = velocity_below_threshold(env, object_name, linear_velocity_threshold, angular_velocity_threshold)
    return contained & touching & settled
