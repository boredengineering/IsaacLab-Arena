# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import field

from isaaclab.controllers import DifferentialIKControllerCfg
from isaaclab.managers.action_manager import ActionTerm
from isaaclab.utils.configclass import configclass

from isaaclab_arena_g1.g1_env.mdp.actions.g1_decoupled_wbc_diff_ik_action import G1DecoupledWBCDiffIKAction
from isaaclab_arena_g1.g1_env.mdp.actions.g1_decoupled_wbc_joint_action_cfg import G1DecoupledWBCJointActionCfg


@configclass
class G1DecoupledWBCDiffIKActionCfg(G1DecoupledWBCJointActionCfg):
    """Specifies the action term configuration for G1 WBC with upper body Differential IK controller."""

    class_type: type[ActionTerm] = G1DecoupledWBCDiffIKAction

    arm_joint_names: list[str] = field(
        default_factory=lambda: [
            "left_shoulder_pitch_joint",
            "left_shoulder_roll_joint",
            "left_shoulder_yaw_joint",
            "left_elbow_joint",
            "left_wrist_roll_joint",
            "left_wrist_pitch_joint",
            "left_wrist_yaw_joint",
        ]
    )
    ee_link_name: str = "left_wrist_yaw_link"

    scale_pos: float = 0.025
    scale_rot: float = 0.08
    ema_factor: float = 0.8

    controller: DifferentialIKControllerCfg = DifferentialIKControllerCfg(
        command_type="pose",
        use_relative_mode=True,
        ik_method="dls",
    )
