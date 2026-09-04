# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import torch

import warp as wp
from isaaclab.assets import RigidObject
from isaaclab.envs import ManagerBasedRLEnv
from isaaclab.managers import SceneEntityCfg
from isaaclab.sensors.contact_sensor.contact_sensor import ContactSensor

from isaaclab_arena.tasks.predicates.episode_state import get_episode_scoped_state
from isaaclab_arena.tasks.predicates.object_settling import get_object_initial_rest_state
from isaaclab_arena.tasks.predicates.predicate_utils import get_env, get_root_lin_vel_w, get_root_pos_w, select


def object_is_above_height(
    env: ManagerBasedRLEnv,
    object_name: str,
    surface_height: float | None = None,
    use_settled_state: bool = False,
    distance: float = 1e-2,
    env_id: int | None = None,
) -> torch.Tensor:
    """Checks if an object is above a certain height.

    The reference height is either a fixed ``surface_height`` or, when ``use_settled_state`` is set, the
    object's recorded resting height (see ``objects_settled``). For envs where no settled state
    has been recorded, the result is always False.

    Returns True when ``object_name`` is at least ``distance`` m above a height reference.
    """

    assert (
        surface_height is not None
    ) != use_settled_state, "object_is_above_height requires exactly one of surface_height or use_settled_state"

    object_z = get_root_pos_w(env, object_name)[:, 2]
    if use_settled_state:
        settled_pos, has_settled = get_object_initial_rest_state(env, object_name)
        result = has_settled & (object_z > (settled_pos[:, 2] + distance))
    else:
        result = object_z > (surface_height + distance)
    return select(result, env_id)


def object_lifted_above_resting_min(
    env: ManagerBasedRLEnv,
    object_name: str,
    distance: float = 5e-2,
    rest_speed_threshold: float = 5e-2,
    rest_steps_required: int = 3,
    min_airborne_steps: int = 1,
    env_id: int | None = None,
) -> torch.Tensor:
    """Checks if an object has been held ``distance`` m above its resting height, for a duration.

    Unlike ``object_is_above_height``, this needs neither a hardcoded surface height nor a recorded
    settled state: the reference is a per-env running minimum of the object's own height, which
    tracks the resting height once the object stops falling. That makes it usable from termination
    predicates, which run whether or not progress tracking is enabled.

    The result stays False until the object has been at rest for ``rest_steps_required``
    *consecutive* steps. Two distinct artefacts make that necessary, both observed:

    * A *bouncing* object otherwise satisfies the height test on its own rebound -- it spawns above
      the surface, falls, drives the running minimum down, and rises past ``distance`` with no robot
      involvement. That produced a false success in the v10 evaluation.
    * A single at-rest sample is not enough, because an object is placed with zero velocity and so
      reads as at rest for exactly the step before gravity acts on it. Requiring consecutive steps
      discards that instant while any genuine resting contact accumulates immediately.

    Resting first is therefore part of the definition of having been lifted, not an optimisation.

    ``min_airborne_steps`` additionally requires the object to *stay* above the threshold for that
    many **consecutive** steps. A pick is a sustained state, not an instant: an object clipped
    upward by a passing hand, or one crossing the threshold on a single-frame physics excursion,
    satisfies an instantaneous height test but was never carried. Requiring dwell is what separates
    "lifted and held" from "touched hard enough to move".

    Args:
        env: The environment.
        object_name: Scene name of the object.
        distance: Required height above the resting height, in metres.
        rest_speed_threshold: Speed below which the object counts as at rest, in m/s.
        rest_steps_required: Consecutive at-rest steps needed to establish the resting reference.
        min_airborne_steps: Consecutive steps the object must remain above ``distance``.
        env_id: Optional single env to select.

    Returns True once ``object_name`` has rested, then remained at least ``distance`` m above that
    resting height for ``min_airborne_steps`` consecutive steps.
    """

    state = get_episode_scoped_state(env)
    speed = torch.linalg.vector_norm(get_root_lin_vel_w(env, object_name), dim=-1)
    rest_run = state.run_length(f"rest_run::{object_name}", speed < rest_speed_threshold)
    has_rested = state.latch(f"has_rested::{object_name}", 1, 0, rest_run >= rest_steps_required)

    object_z = get_root_pos_w(env, object_name)[:, 2]
    # Only track the resting height once at rest, so a mid-fall low point cannot become the
    # reference the lift is measured against.
    reference_z = state.running_min(
        f"resting_min_z::{object_name}", torch.where(has_rested, object_z, torch.full_like(object_z, float("inf")))
    )
    above_threshold = has_rested & (object_z > (reference_z + distance))
    # Consecutive-step run, so a momentary excursion above the threshold does not count as a lift.
    airborne_run = state.run_length(f"airborne_run::{object_name}", above_threshold)
    return select(airborne_run >= min_airborne_steps, env_id)


def object_moving(
    env: ManagerBasedRLEnv,
    object_name: str,
    velocity_threshold: float = 1e-2,
    env_id: int | None = None,
) -> torch.Tensor:
    """Checks if an object is moving above a certain velocity threshold.

    Returns True when object_name's linear speed exceeds velocity_threshold (m/s).
    """

    speed = torch.linalg.vector_norm(get_root_lin_vel_w(env, object_name), dim=-1)
    result = speed > velocity_threshold
    return select(result, env_id)


def objects_in_proximity(
    env: ManagerBasedRLEnv,
    object_cfg: SceneEntityCfg,
    target_object_cfg: SceneEntityCfg,
    max_y_separation: float,
    max_x_separation: float,
    max_z_separation: float,
) -> torch.Tensor:
    """Determine if two objects are within a certain proximity of each other.

    Returns True when the object is within a certain proximity of the target object.
    """

    # Get object entities from the scene
    object: RigidObject = env.scene[object_cfg.name]
    target_object: RigidObject = env.scene[target_object_cfg.name]

    # Get positions relative to environment origin
    object_pos = wp.to_torch(object.data.root_pos_w) - env.scene.env_origins
    target_object_pos = wp.to_torch(target_object.data.root_pos_w) - env.scene.env_origins

    # object to target object
    x_separation = torch.abs(object_pos[:, 0] - target_object_pos[:, 0])
    y_separation = torch.abs(object_pos[:, 1] - target_object_pos[:, 1])
    z_separation = torch.abs(object_pos[:, 2] - target_object_pos[:, 2])

    done = x_separation < max_x_separation
    done = torch.logical_and(done, y_separation < max_y_separation)
    done = torch.logical_and(done, z_separation < max_z_separation)

    return done


def object_on_destination(
    env: ManagerBasedRLEnv,
    object_cfg: SceneEntityCfg = SceneEntityCfg("pick_up_object"),
    contact_sensor_cfg: SceneEntityCfg = SceneEntityCfg("pick_up_object_contact_sensor"),
    force_threshold: float = 1.0,
    velocity_threshold: float = 0.5,
    destination_cfg: SceneEntityCfg | None = None,
    max_xy_separation: float | None = None,
) -> torch.Tensor:
    """Checks if an object is resting on its destination, via contact and optional proximity.

    Contact alone is not evidence of placement. On ``g1_tabletop_apple_to_plate`` this predicate
    fired while the manipuland sat on the *table* 0.214 m from the plate: the object had grazed the
    plate earlier in the episode, and the residual reading cleared the (0.1 N) force threshold once
    the object came to rest and satisfied the velocity gate. Passing ``destination_cfg`` and
    ``max_xy_separation`` adds a geometric conjunct evaluated at the *same step*, so a stale or
    noisy sensor reading can no longer stand in for a placement.

    Args:
        env: The environment.
        object_cfg: The object being placed.
        contact_sensor_cfg: Contact sensor on the object, filtered to the destination.
        force_threshold: Minimum contact force, in N.
        velocity_threshold: Maximum object speed, in m/s.
        destination_cfg: The destination object. Required to enable the proximity check.
        max_xy_separation: Maximum horizontal centre-to-centre distance, in m. Requires
            ``destination_cfg``; when either is None the proximity check is skipped and the
            predicate keeps its contact-only behaviour.

    Returns True when the object is in contact with its destination above ``force_threshold``,
    below ``velocity_threshold``, and (when configured) within ``max_xy_separation`` of it.
    """

    unwrapped_env = get_env(env)
    object: RigidObject = unwrapped_env.scene[object_cfg.name]
    sensor: ContactSensor = unwrapped_env.scene[contact_sensor_cfg.name]

    # force_matrix_w shape is (N, B, M, 3), where N is the number of sensors, B is number of bodies in each sensor
    # and ``M`` is the number of filtered bodies.
    # We assume B = 1 and M = 1
    assert sensor.data.force_matrix_w.shape[2] == 1
    assert sensor.data.force_matrix_w.shape[1] == 1
    # NOTE(alexmillane, 2025-08-04): We expect the binary flags to have shape (N, )
    # where N is the number of envs.
    force_matrix_norm = torch.norm(wp.to_torch(sensor.data.force_matrix_w), dim=-1).reshape(-1)
    force_above_threshold = force_matrix_norm > force_threshold

    velocity_w = wp.to_torch(object.data.root_lin_vel_w)
    velocity_w_norm = torch.norm(velocity_w, dim=-1)
    velocity_below_threshold = velocity_w_norm < velocity_threshold

    condition_met = torch.logical_and(force_above_threshold, velocity_below_threshold)

    if max_xy_separation is not None:
        assert destination_cfg is not None, "max_xy_separation requires destination_cfg"
        destination: RigidObject = unwrapped_env.scene[destination_cfg.name]
        object_xy = wp.to_torch(object.data.root_pos_w)[:, :2]
        destination_xy = wp.to_torch(destination.data.root_pos_w)[:, :2]
        xy_separation = torch.linalg.vector_norm(object_xy - destination_xy, dim=-1)
        condition_met = torch.logical_and(condition_met, xy_separation < max_xy_separation)

    return condition_met


def objects_on_destinations(
    env: ManagerBasedRLEnv,
    object_cfg_list: list[SceneEntityCfg] = [SceneEntityCfg("pick_up_object")],
    contact_sensor_cfg_list: list[SceneEntityCfg] = [SceneEntityCfg("pick_up_object_contact_sensor")],
    force_threshold: float = 1.0,
    velocity_threshold: float = 0.5,
) -> torch.Tensor:
    """Multi-object version of `object_on_destination`.

    Returns True only when ALL objects in the list satisfy the destination condition.
    See `object_on_destination` for details on the single-object logic.
    """

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
