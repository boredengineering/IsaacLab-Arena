# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from isaaclab_arena.assets.register import register_environment
from isaaclab_arena.environments.arena_environment_factory import ArenaEnvironmentCfg, ArenaEnvironmentFactory

if TYPE_CHECKING:
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment


G1_PREGRASP_LEFT_ARM_JOINT_POS: dict[str, float] = {
    "left_shoulder_pitch_joint": -0.1038,
    "left_shoulder_roll_joint": -0.0865,
    "left_shoulder_yaw_joint": 0.2141,
    "left_elbow_joint": 0.4491,
    "left_wrist_roll_joint": 0.1850,
    "left_wrist_pitch_joint": -0.0044,
    "left_wrist_yaw_joint": 0.1924,
}


@dataclass
class G1AppleToPlateRLEnvironmentCfg(ArenaEnvironmentCfg):
    """Configure the G1 tabletop apple to plate RL training environment."""

    embodiment: str = "g1_wbc_agile_diff_ik"
    """The robot embodiment to use."""

    pick_up_object: str = "apple_01_objaverse_robolab"
    """Asset name of the object to pick up."""

    destination: str = "clay_plates_hot3d_robolab"
    """Asset name of the destination plate."""

    ee_link_name: str = "left_hand_middle_1_link"
    """Body link name used for reaching calculations."""

    minimum_height_to_lift: float = 0.03
    """Minimum height (m) to consider the object lifted."""

    episode_length_s: float = 6.0
    """Episode duration in seconds."""

    rl_training_mode: bool = False
    """Whether to run in RL training mode (no early success termination)."""

    curriculum_ratio: float = 0.35
    """Fraction of parallel training environments initialized in pre-grasp arm posture."""

    lift_curriculum_ratio: float = 0.15
    """Fraction of parallel training environments initialized with object elevated."""


@register_environment
class G1AppleToPlateRLEnvironment(ArenaEnvironmentFactory[G1AppleToPlateRLEnvironmentCfg]):
    """Registered provider for G1 tabletop apple to plate RL environment."""

    name: str = "g1_apple_to_plate_rl"
    _legacy_argparse_cfg_type = G1AppleToPlateRLEnvironmentCfg

    def build(self, cfg: G1AppleToPlateRLEnvironmentCfg) -> IsaacLabArenaEnvironment:
        """Build the environment from its typed configuration."""
        import isaaclab_arena_examples.policy.base_rsl_rl_policy as base_rsl_rl_policy
        from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
        from isaaclab_arena.scene.scene import Scene
        from isaaclab_arena.tasks.pick_and_place_task_rl import PickAndPlaceTaskRL
        from isaaclab_arena.utils.pose import Pose

        # Step 1: Retrieve assets
        background = self.asset_registry.get_asset_by_name("maple_table_robolab")()
        pick_up_object = self.asset_registry.get_asset_by_name(cfg.pick_up_object)(scale=(0.009, 0.009, 0.009))
        destination = self.asset_registry.get_asset_by_name(cfg.destination)(scale=(0.5, 0.5, 0.5))
        ground_plane = self.asset_registry.get_asset_by_name("ground_plane")()
        light = self.asset_registry.get_asset_by_name("light")()

        # Step 2: Configure embodiment with WBC and high friction fingers
        embodiment = self.asset_registry.get_asset_by_name(cfg.embodiment)(
            enable_cameras=cfg.enable_cameras,
        )
        embodiment.observation_config.policy.concatenate_terms = True
        # The 4x4 homogeneous matrix terms are for VLA/IL policies; set to None for 1D RL vector obs
        embodiment.observation_config.policy.right_wrist_pose_pelvis_frame = None
        embodiment.observation_config.policy.left_wrist_pose_pelvis_frame = None
        # Disable unused unconcatenated wbc group so all obs groups are pure 2D tensors for RSL-RL
        embodiment.observation_config.wbc = None
        embodiment.set_initial_pose(
            Pose(
                position_xyz=(-0.46, 0.0, 0.0007),
                rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
            )
        )
        embodiment.set_joint_initial_pos({
            "left_shoulder_roll_joint": 0.25,
            "right_shoulder_roll_joint": -0.25,
            "left_shoulder_yaw_joint": 0.5,
            "right_shoulder_yaw_joint": -0.5,
        })
        embodiment.set_finger_contact_friction(
            material_path="/World/Materials/g1_static_pick_place_high_friction_fingers",
            static_friction=6.0,
            dynamic_friction=5.0,
            prim_name_markers=["hand", "thumb", "index", "middle"],
        )

        # Step 3: Set scene object poses (matching C1 tabletop configuration)
        background.set_initial_pose(
            Pose(
                position_xyz=(-0.58, 0.0, 0.078),
                rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
            )
        )
        pick_up_object.set_initial_pose(
            Pose(
                position_xyz=(-0.1730, 0.1900, 0.0975),
                rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
            )
        )
        destination.set_initial_pose(
            Pose(
                position_xyz=(-0.1730, -0.0200, 0.0780),
                rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
            )
        )
        ground_plane.set_initial_pose(Pose(position_xyz=(0.0, 0.0, -1.05)))

        # Step 4: Compose scene and task
        scene = Scene(assets=[background, pick_up_object, destination, ground_plane, light])

        # Reverse curriculum: active during training mode, zeroed for evaluation from home position
        effective_curriculum_ratio = cfg.curriculum_ratio if cfg.rl_training_mode else 0.0
        effective_lift_curriculum_ratio = cfg.lift_curriculum_ratio if cfg.rl_training_mode else 0.0

        task = PickAndPlaceTaskRL(
            pick_up_object=pick_up_object,
            destination_location=destination,
            background_scene=background,
            embodiment=embodiment,
            ee_link_name=cfg.ee_link_name,
            minimum_height_to_lift=cfg.minimum_height_to_lift,
            episode_length_s=cfg.episode_length_s,
            rl_training_mode=cfg.rl_training_mode,
            curriculum_ratio=effective_curriculum_ratio,
            pregrasp_arm_joint_pos=G1_PREGRASP_LEFT_ARM_JOINT_POS,
            lift_curriculum_ratio=effective_lift_curriculum_ratio,
        )

        return IsaacLabArenaEnvironment(
            name=self.name,
            embodiment=embodiment,
            scene=scene,
            task=task,
            teleop_device=None,
            rl_framework_entry_point="rsl_rl_cfg_entry_point",
            rl_policy_cfg=f"{base_rsl_rl_policy.__name__}:RLPolicyCfg",
        )
