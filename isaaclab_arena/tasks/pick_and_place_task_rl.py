# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import torch
from dataclasses import MISSING

import isaaclab.envs.mdp as mdp_isaac_lab
import warp as wp
from isaaclab.assets import Articulation, RigidObject
from isaaclab.envs import ManagerBasedRLEnv
from isaaclab.managers import EventTermCfg
from isaaclab.managers import ObservationGroupCfg as ObsGroup
from isaaclab.managers import ObservationTermCfg as ObsTerm
from isaaclab.managers import RewardTermCfg, SceneEntityCfg, TerminationTermCfg
from isaaclab.utils.configclass import configclass
from isaaclab.utils.math import subtract_frame_transforms

from isaaclab_arena.assets.asset import Asset
from isaaclab_arena.assets.register import register_task
from isaaclab_arena.embodiments.embodiment_base import EmbodimentBase
from isaaclab_arena.tasks.observations import observations
from isaaclab_arena.tasks.pick_and_place_task import PickAndPlaceTask
from isaaclab_arena.tasks.rewards import pick_and_place_rewards


def ee_position_in_robot_root(
    env: ManagerBasedRLEnv,
    ee_link_name: str,
    robot_cfg: SceneEntityCfg = SceneEntityCfg("robot"),
) -> torch.Tensor:
    """Position of the robot end-effector in the robot's root frame."""
    robot: Articulation = env.scene[robot_cfg.name]
    assert ee_link_name in robot.data.body_names, f"Link {ee_link_name} not found in robot {robot_cfg.name}"
    link_idx = robot.data.body_names.index(ee_link_name)
    ee_pos_w = wp.to_torch(robot.data.body_pos_w)[:, link_idx, :]
    ee_pos_b, _ = subtract_frame_transforms(
        wp.to_torch(robot.data.root_pos_w), wp.to_torch(robot.data.root_quat_w), ee_pos_w
    )
    return ee_pos_b


def ee_orientation_in_robot_root(
    env: ManagerBasedRLEnv,
    ee_link_name: str,
    robot_cfg: SceneEntityCfg = SceneEntityCfg("robot"),
) -> torch.Tensor:
    """Quaternion orientation of the robot end-effector in the robot's root frame."""
    robot: Articulation = env.scene[robot_cfg.name]
    assert ee_link_name in robot.data.body_names, f"Link {ee_link_name} not found in robot {robot_cfg.name}"
    link_idx = robot.data.body_names.index(ee_link_name)
    ee_pos_w = wp.to_torch(robot.data.body_pos_w)[:, link_idx, :]
    ee_quat_w = wp.to_torch(robot.data.body_quat_w)[:, link_idx, :]
    _, ee_quat_b = subtract_frame_transforms(
        wp.to_torch(robot.data.root_pos_w), wp.to_torch(robot.data.root_quat_w), ee_pos_w, ee_quat_w
    )
    return ee_quat_b


def ee_to_object_vector(
    env: ManagerBasedRLEnv,
    ee_link_name: str,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
    robot_cfg: SceneEntityCfg = SceneEntityCfg("robot"),
) -> torch.Tensor:
    """Relative displacement vector from end-effector to the target object."""
    robot: Articulation = env.scene[robot_cfg.name]
    object: RigidObject = env.scene[object_cfg.name]
    assert ee_link_name in robot.data.body_names, f"Link {ee_link_name} not found in robot {robot_cfg.name}"
    link_idx = robot.data.body_names.index(ee_link_name)
    ee_pos_w = wp.to_torch(robot.data.body_pos_w)[:, link_idx, :]
    object_pos_w = wp.to_torch(object.data.root_pos_w)[:, :3]
    return object_pos_w - ee_pos_w


def object_to_destination_vector(
    env: ManagerBasedRLEnv,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
    destination_cfg: SceneEntityCfg = SceneEntityCfg("destination"),
) -> torch.Tensor:
    """Relative displacement vector from target object to destination."""
    object: RigidObject = env.scene[object_cfg.name]
    destination: RigidObject = env.scene[destination_cfg.name]
    object_pos_w = wp.to_torch(object.data.root_pos_w)[:, :3]
    dest_pos_w = wp.to_torch(destination.data.root_pos_w)[:, :3]
    return dest_pos_w - object_pos_w


def object_is_lifted_obs(
    env: ManagerBasedRLEnv,
    minimal_height: float,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
) -> torch.Tensor:
    """Indicator of whether the object is lifted above the minimal threshold from resting height."""
    from isaaclab_arena.tasks.predicates.spatial import object_lifted_above_resting_min

    lifted = object_lifted_above_resting_min(env, object_cfg.name, distance=minimal_height)
    return lifted.float().unsqueeze(-1)


def pick_and_place_rl_success(
    env: ManagerBasedRLEnv,
    minimal_height: float,
    max_xy_distance: float,
    velocity_threshold: float = 0.2,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
    destination_cfg: SceneEntityCfg = SceneEntityCfg("destination"),
    rl_training: bool = False,
) -> torch.Tensor:
    """Evaluate success termination for pick-and-place.

    During RL training mode, returns all False to prevent premature episode termination while
    maintaining an active 'success' term in the termination manager required by SuccessRecorder.
    During evaluation, checks placement on the destination within tolerance with low velocity.
    """
    if rl_training:
        return torch.zeros(env.num_envs, dtype=torch.bool, device=env.device)

    from isaaclab_arena.tasks.predicates.spatial import object_lifted_above_resting_min

    object_instance: RigidObject = env.scene[object_cfg.name]
    destination_instance: RigidObject = env.scene[destination_cfg.name]
    obj_pos_w = wp.to_torch(object_instance.data.root_pos_w)[:, :3]
    dest_pos_w = wp.to_torch(destination_instance.data.root_pos_w)[:, :3]
    distance_xy = torch.norm(obj_pos_w[:, :2] - dest_pos_w[:, :2], dim=1)

    # 1. Lift condition: must have been lifted above resting reference
    has_been_lifted = object_lifted_above_resting_min(env, object_cfg.name, distance=minimal_height)

    # 2. Velocity gate: must be at rest / low velocity (< 0.2 m/s), not flying
    obj_vel = wp.to_torch(object_instance.data.root_lin_vel_w)
    speed = torch.norm(obj_vel, dim=-1)
    is_settled = speed < velocity_threshold

    # 3. Vertical alignment with destination deck: within 5cm
    dz = torch.abs(obj_pos_w[:, 2] - dest_pos_w[:, 2])
    is_near_deck = dz < 0.05

    return (distance_xy < max_xy_distance) & has_been_lifted & is_settled & is_near_deck


@configclass
class PickAndPlaceObservationsCfg:
    """Observation specifications for Pick and Place RL."""

    task_obs: ObsGroup = MISSING
    """Task specific observation group."""

    def __init__(
        self,
        pick_up_object: Asset,
        destination_location: Asset,
        robot_name: str,
        ee_link_name: str,
        minimal_height: float,
    ):
        @configclass
        class TaskObsCfg(ObsGroup):
            object_position = ObsTerm(
                func=observations.object_position_in_frame,
                params={
                    "root_frame_cfg": SceneEntityCfg(robot_name),
                    "object_cfg": SceneEntityCfg(pick_up_object.name),
                },
            )
            destination_position = ObsTerm(
                func=observations.object_position_in_frame,
                params={
                    "root_frame_cfg": SceneEntityCfg(robot_name),
                    "object_cfg": SceneEntityCfg(destination_location.name),
                },
            )
            ee_position = ObsTerm(
                func=ee_position_in_robot_root,
                params={
                    "robot_cfg": SceneEntityCfg(robot_name),
                    "ee_link_name": ee_link_name,
                },
            )
            ee_orientation = ObsTerm(
                func=ee_orientation_in_robot_root,
                params={
                    "robot_cfg": SceneEntityCfg(robot_name),
                    "ee_link_name": ee_link_name,
                },
            )
            ee_to_object = ObsTerm(
                func=ee_to_object_vector,
                params={
                    "robot_cfg": SceneEntityCfg(robot_name),
                    "object_cfg": SceneEntityCfg(pick_up_object.name),
                    "ee_link_name": ee_link_name,
                },
            )
            object_to_destination = ObsTerm(
                func=object_to_destination_vector,
                params={
                    "object_cfg": SceneEntityCfg(pick_up_object.name),
                    "destination_cfg": SceneEntityCfg(destination_location.name),
                },
            )
            is_lifted = ObsTerm(
                func=object_is_lifted_obs,
                params={
                    "minimal_height": minimal_height,
                    "object_cfg": SceneEntityCfg(pick_up_object.name),
                },
            )

            def __post_init__(self):
                self.enable_corruption = False
                self.concatenate_terms = True

        self.task_obs = TaskObsCfg()


@configclass
class PickAndPlaceRewardCfg:
    """Reward terms for Pick and Place RL."""

    reaching_object: RewardTermCfg = MISSING
    """Reward for reaching the object."""

    approach_alignment: RewardTermCfg = MISSING
    """Reward for aligning end-effector approach axis toward object."""

    finger_grasp_enclosure: RewardTermCfg = MISSING
    """Reward for closing fingers near object and opening when far."""

    multi_keypoint_guidance: RewardTermCfg = MISSING
    """Reward for multi-keypoint enclosure of the object by hand links."""

    lifting_object: RewardTermCfg = MISSING
    """Reward for lifting the object."""

    transporting_object: RewardTermCfg = MISSING
    """Reward for transporting the object to destination."""

    placed_bonus: RewardTermCfg = MISSING
    """Reward bonus for placing object on destination."""

    excess_velocity: RewardTermCfg = MISSING
    """Penalize excessive object linear speed to prevent swatting."""

    action_rate: RewardTermCfg = MISSING
    """Regularization penalty on action rate change."""

    arm_joint_vel: RewardTermCfg = MISSING
    """Regularization penalty on arm joint velocities to suppress excessive speed."""

    def __init__(
        self,
        pick_up_object: Asset,
        destination_location: Asset,
        robot_name: str,
        ee_link_name: str,
        minimum_height_to_lift: float,
        max_destination_xy_distance: float,
    ):
        self.reaching_object = RewardTermCfg(
            func=pick_and_place_rewards.object_ee_distance,
            params={
                "std": 0.1,
                "ee_link_name": ee_link_name,
                "object_cfg": SceneEntityCfg(pick_up_object.name),
                "robot_cfg": SceneEntityCfg(robot_name),
            },
            weight=2.0,
        )
        self.approach_alignment = RewardTermCfg(
            func=pick_and_place_rewards.ee_approach_vector_alignment,
            params={
                "ee_link_name": ee_link_name,
                "object_cfg": SceneEntityCfg(pick_up_object.name),
                "robot_cfg": SceneEntityCfg(robot_name),
            },
            weight=1.5,
        )
        self.finger_grasp_enclosure = RewardTermCfg(
            func=pick_and_place_rewards.finger_grasp_enclosure,
            params={
                "ee_link_name": ee_link_name,
                "object_cfg": SceneEntityCfg(pick_up_object.name),
                "robot_cfg": SceneEntityCfg(robot_name),
            },
            weight=2.0,
        )
        self.multi_keypoint_guidance = RewardTermCfg(
            func=pick_and_place_rewards.multi_keypoint_grasp_guidance,
            params={
                "std": 0.08,
                "object_cfg": SceneEntityCfg(pick_up_object.name),
                "robot_cfg": SceneEntityCfg(robot_name),
            },
            weight=3.0,
        )
        self.lifting_object = RewardTermCfg(
            func=pick_and_place_rewards.object_is_lifted,
            params={
                "minimal_height": minimum_height_to_lift,
                "object_cfg": SceneEntityCfg(pick_up_object.name),
            },
            weight=10.0,
        )
        self.transporting_object = RewardTermCfg(
            func=pick_and_place_rewards.object_destination_distance,
            params={
                "std": 0.25,
                "minimal_height": minimum_height_to_lift,
                "object_cfg": SceneEntityCfg(pick_up_object.name),
                "destination_cfg": SceneEntityCfg(destination_location.name),
            },
            weight=15.0,
        )
        self.placed_bonus = RewardTermCfg(
            func=pick_and_place_rewards.object_placed_bonus,
            params={
                "minimal_height": minimum_height_to_lift,
                "max_xy_distance": max_destination_xy_distance,
                "velocity_threshold": 0.2,
                "object_cfg": SceneEntityCfg(pick_up_object.name),
                "destination_cfg": SceneEntityCfg(destination_location.name),
            },
            weight=20.0,
        )
        self.excess_velocity = RewardTermCfg(
            func=pick_and_place_rewards.object_excess_velocity_penalty,
            params={
                "max_allowed_speed": 1.0,
                "object_cfg": SceneEntityCfg(pick_up_object.name),
            },
            weight=0.5,
        )
        self.action_rate = RewardTermCfg(
            func=pick_and_place_rewards.action_rate_l2,
            weight=-0.005,
        )
        self.arm_joint_vel = RewardTermCfg(
            func=pick_and_place_rewards.arm_joint_vel_l2,
            params={"robot_cfg": SceneEntityCfg(robot_name)},
            weight=-0.0005,
        )


def reset_robot_arm_reverse_curriculum(
    env: ManagerBasedRLEnv,
    env_ids: torch.Tensor,
    curriculum_ratio: float,
    pregrasp_arm_joint_pos: dict[str, float],
    robot_cfg: SceneEntityCfg = SceneEntityCfg("robot"),
) -> None:
    """Initialize a fraction of resetting environments with the robot arm in pre-grasp posture.

    Args:
        env: The simulation environment.
        env_ids: Environment indices being reset.
        curriculum_ratio: Fraction of resetting environments to place in pre-grasp posture.
        pregrasp_arm_joint_pos: Dictionary mapping joint names to pre-grasp target angles.
        robot_cfg: Scene entity configuration for the robot articulation.
    """
    if env_ids is None or len(env_ids) == 0 or curriculum_ratio <= 0.0 or not pregrasp_arm_joint_pos:
        return

    rand_vals = torch.rand(len(env_ids), device=env.device)
    curr_mask = rand_vals < curriculum_ratio
    curr_env_ids = env_ids[curr_mask]
    if len(curr_env_ids) == 0:
        return

    robot: Articulation = env.scene[robot_cfg.name]
    joint_names = list(pregrasp_arm_joint_pos.keys())
    joint_ids, _ = robot.find_joints(joint_names, preserve_order=True)

    joint_pos = wp.to_torch(robot.data.joint_pos)[curr_env_ids].clone()
    joint_vel = wp.to_torch(robot.data.joint_vel)[curr_env_ids].clone()

    for i, name in enumerate(joint_names):
        joint_pos[:, joint_ids[i]] = pregrasp_arm_joint_pos[name]
    joint_vel[:, joint_ids] = 0.0

    robot.write_joint_state_to_sim(joint_pos, joint_vel, env_ids=curr_env_ids)


def reset_object_reverse_curriculum(
    env: ManagerBasedRLEnv,
    env_ids: torch.Tensor,
    lift_curriculum_ratio: float,
    lift_height_offset: float = 0.025,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
) -> None:
    """Initialize a fraction of resetting environments with the object slightly elevated.

    Args:
        env: The simulation environment.
        env_ids: Environment indices being reset.
        lift_curriculum_ratio: Fraction of environments to elevate.
        lift_height_offset: Vertical offset in meters to add to default root position.
        object_cfg: Scene entity configuration for the manipuland object.
    """
    if env_ids is None or len(env_ids) == 0 or lift_curriculum_ratio <= 0.0:
        return

    rand_vals = torch.rand(len(env_ids), device=env.device)
    curr_mask = rand_vals < lift_curriculum_ratio
    curr_env_ids = env_ids[curr_mask]
    if len(curr_env_ids) == 0:
        return

    obj: RigidObject = env.scene[object_cfg.name]
    root_pose = wp.to_torch(obj.data.default_root_state)[curr_env_ids, :7].clone()
    root_pose[:, :3] += env.scene.env_origins[curr_env_ids]
    root_pose[:, 2] += lift_height_offset
    root_vel = torch.zeros(len(curr_env_ids), 6, device=env.device)

    obj.write_root_pose_to_sim(root_pose, env_ids=curr_env_ids)
    obj.write_root_velocity_to_sim(root_vel, env_ids=curr_env_ids)


@configclass
class PickAndPlaceEventsCfg:
    """Event terms for Pick and Place RL to ensure object reset across episodes."""

    reset_object: EventTermCfg = MISSING
    """Reset the pick-up object to its default root state upon episode reset."""

    reset_destination: EventTermCfg = MISSING
    """Reset the destination object to its default root state upon episode reset."""

    reset_robot_curriculum: EventTermCfg | None = None
    """Optional reverse-curriculum reset term that initializes arm joints to pre-grasp posture."""

    reset_object_curriculum: EventTermCfg | None = None
    """Optional reverse-curriculum reset term that elevates object to pre-lifted state."""


@configclass
class PickAndPlaceTerminationsCfg:
    """Termination terms for Pick and Place RL."""

    time_out: TerminationTermCfg = TerminationTermCfg(func=mdp_isaac_lab.time_out)
    """Timeout termination."""

    object_dropped: TerminationTermCfg = MISSING
    """Termination when object falls below floor/table threshold."""

    success: TerminationTermCfg = MISSING
    """Success termination."""


@register_task
class PickAndPlaceTaskRL(PickAndPlaceTask):
    """Pick-and-place task configured for reinforcement learning with dense rewards and privileged state."""

    def __init__(
        self,
        pick_up_object: Asset,
        destination_location: Asset,
        background_scene: Asset,
        embodiment: EmbodimentBase,
        destination_object: Asset | None = None,
        episode_length_s: float | None = 6.0,
        task_description: str | None = None,
        force_threshold: float = 0.1,
        velocity_threshold: float = 0.1,
        max_separation: tuple[float, float, float] | None = None,
        require_lift_before_place: bool = True,
        min_lift_height: float = 0.03,
        min_airborne_steps: int = 1,
        max_destination_xy_separation: float | None = 0.075,
        ee_link_name: str = "left_hand_middle_1_link",
        rl_training_mode: bool = True,
        minimum_height_to_lift: float | None = None,
        curriculum_ratio: float = 0.0,
        pregrasp_arm_joint_pos: dict[str, float] | None = None,
        lift_curriculum_ratio: float = 0.0,
    ):
        """Initialize the Pick-and-Place RL task.

        Args:
            pick_up_object: The object to pick up.
            destination_location: The destination surface or container.
            background_scene: The background scene (table, etc.).
            embodiment: The robot embodiment.
            destination_object: Optional explicit destination object.
            episode_length_s: Episode length in seconds.
            task_description: Natural language task description.
            force_threshold: Contact force threshold for placement.
            velocity_threshold: Velocity threshold for placement.
            max_separation: Optional maximum xyz separation bounding box.
            require_lift_before_place: Whether lifting is prerequisite for placement.
            min_lift_height: Minimum lift height in meters.
            min_airborne_steps: Minimum consecutive airborne steps required.
            max_destination_xy_separation: Maximum horizontal distance to destination.
            ee_link_name: Body link name used for reaching calculations.
            rl_training_mode: Whether to run in RL training mode (no early success termination).
            minimum_height_to_lift: Optional alias for min_lift_height.
            curriculum_ratio: Fraction of environments reset in pre-grasp arm posture.
            pregrasp_arm_joint_pos: Dictionary mapping arm joint names to pre-grasp target angles.
            lift_curriculum_ratio: Fraction of environments reset with object elevated.
        """
        if minimum_height_to_lift is not None:
            min_lift_height = minimum_height_to_lift

        super().__init__(
            pick_up_object=pick_up_object,
            destination_location=destination_location,
            background_scene=background_scene,
            destination_object=destination_object,
            episode_length_s=episode_length_s,
            task_description=task_description,
            force_threshold=force_threshold,
            velocity_threshold=velocity_threshold,
            max_separation=max_separation,
            require_lift_before_place=require_lift_before_place,
            min_lift_height=min_lift_height,
            min_airborne_steps=min_airborne_steps,
            max_destination_xy_separation=max_destination_xy_separation,
        )
        self.embodiment = embodiment
        self.ee_link_name = ee_link_name
        self.rl_training_mode = rl_training_mode
        self.curriculum_ratio = curriculum_ratio
        self.pregrasp_arm_joint_pos = pregrasp_arm_joint_pos
        self.lift_curriculum_ratio = lift_curriculum_ratio

        self.observation_cfg = PickAndPlaceObservationsCfg(
            pick_up_object=self.pick_up_object,
            destination_location=self.destination_location,
            robot_name=self.embodiment.get_scene_key(),
            ee_link_name=self.ee_link_name,
            minimal_height=self.min_lift_height,
        )
        self.rewards_cfg = PickAndPlaceRewardCfg(
            pick_up_object=self.pick_up_object,
            destination_location=self.destination_location,
            robot_name=self.embodiment.get_scene_key(),
            ee_link_name=self.ee_link_name,
            minimum_height_to_lift=self.min_lift_height,
            max_destination_xy_distance=self.max_destination_xy_separation or 0.075,
        )
        self.termination_cfg = self.make_rl_termination_cfg()
        self.events_cfg = self.make_rl_events_cfg()

    def make_rl_events_cfg(self) -> PickAndPlaceEventsCfg:
        """Create event terms to guarantee object and destination reset across episodes."""
        reset_object = EventTermCfg(
            func=mdp_isaac_lab.reset_root_state_uniform,
            mode="reset",
            params={
                "pose_range": {},
                "velocity_range": {},
                "asset_cfg": SceneEntityCfg(self.pick_up_object.name),
            },
        )
        reset_destination = EventTermCfg(
            func=mdp_isaac_lab.reset_root_state_uniform,
            mode="reset",
            params={
                "pose_range": {},
                "velocity_range": {},
                "asset_cfg": SceneEntityCfg(self.destination_location.name),
            },
        )

        reset_robot_curriculum = None
        if self.curriculum_ratio > 0.0 and self.pregrasp_arm_joint_pos:
            reset_robot_curriculum = EventTermCfg(
                func=reset_robot_arm_reverse_curriculum,
                mode="reset",
                params={
                    "curriculum_ratio": self.curriculum_ratio,
                    "pregrasp_arm_joint_pos": self.pregrasp_arm_joint_pos,
                    "robot_cfg": SceneEntityCfg(self.embodiment.get_scene_key()),
                },
            )

        reset_object_curriculum = None
        if self.lift_curriculum_ratio > 0.0:
            reset_object_curriculum = EventTermCfg(
                func=reset_object_reverse_curriculum,
                mode="reset",
                params={
                    "lift_curriculum_ratio": self.lift_curriculum_ratio,
                    "lift_height_offset": 0.025,
                    "object_cfg": SceneEntityCfg(self.pick_up_object.name),
                },
            )

        return PickAndPlaceEventsCfg(
            reset_object=reset_object,
            reset_destination=reset_destination,
            reset_robot_curriculum=reset_robot_curriculum,
            reset_object_curriculum=reset_object_curriculum,
        )

    def make_rl_termination_cfg(self) -> PickAndPlaceTerminationsCfg:
        """Create termination terms tailored for RL training."""
        object_dropped = TerminationTermCfg(
            func=mdp_isaac_lab.root_height_below_minimum,
            params={
                "minimum_height": self.background_scene.object_min_z,
                "asset_cfg": SceneEntityCfg(self.pick_up_object.name),
            },
        )
        success = TerminationTermCfg(
            func=pick_and_place_rl_success,
            params={
                "minimal_height": self.min_lift_height,
                "max_xy_distance": self.max_destination_xy_separation or 0.075,
                "velocity_threshold": 0.2,
                "object_cfg": SceneEntityCfg(self.pick_up_object.name),
                "destination_cfg": SceneEntityCfg(self.destination_location.name),
                "rl_training": self.rl_training_mode,
            },
        )
        return PickAndPlaceTerminationsCfg(
            time_out=TerminationTermCfg(func=mdp_isaac_lab.time_out),
            object_dropped=object_dropped,
            success=success,
        )

    def get_observation_cfg(self) -> PickAndPlaceObservationsCfg:
        """Return observation configuration for RL."""
        return self.observation_cfg

    def get_rewards_cfg(self) -> PickAndPlaceRewardCfg:
        """Return dense reward terms for RL."""
        return self.rewards_cfg

    def get_termination_cfg(self) -> PickAndPlaceTerminationsCfg:
        """Return termination terms for RL."""
        return self.termination_cfg

    def get_events_cfg(self) -> PickAndPlaceEventsCfg:
        """Return event configuration for RL."""
        return self.events_cfg
