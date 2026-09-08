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
    """Indicator of whether the object is lifted above the minimal threshold."""
    object: RigidObject = env.scene[object_cfg.name]
    obj_z = wp.to_torch(object.data.root_pos_w)[:, 2:3]
    return (obj_z > minimal_height).float()


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

    lifting_object: RewardTermCfg = MISSING
    """Reward for lifting the object."""

    transporting_object: RewardTermCfg = MISSING
    """Reward for transporting the object to destination."""

    placed_bonus: RewardTermCfg = MISSING
    """Reward bonus for placing object on destination."""

    action_rate: RewardTermCfg = MISSING
    """Regularization penalty on action rate change."""

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
                "object_cfg": SceneEntityCfg(pick_up_object.name),
                "destination_cfg": SceneEntityCfg(destination_location.name),
            },
            weight=20.0,
        )
        self.action_rate = RewardTermCfg(
            func=pick_and_place_rewards.action_rate_l2,
            weight=-0.001,
        )


@configclass
class PickAndPlaceTerminationsCfg:
    """Termination terms for Pick and Place RL."""

    time_out: TerminationTermCfg = TerminationTermCfg(func=mdp_isaac_lab.time_out)
    """Timeout termination."""

    object_dropped: TerminationTermCfg = MISSING
    """Termination when object falls below floor/table threshold."""

    success: TerminationTermCfg | None = None
    """Optional success termination."""


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

    def make_rl_termination_cfg(self) -> PickAndPlaceTerminationsCfg:
        """Create termination terms tailored for RL training."""
        object_dropped = TerminationTermCfg(
            func=mdp_isaac_lab.root_height_below_minimum,
            params={
                "minimum_height": self.background_scene.object_min_z,
                "asset_cfg": SceneEntityCfg(self.pick_up_object.name),
            },
        )
        success = None if self.rl_training_mode else self.termination_cfg.success
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
