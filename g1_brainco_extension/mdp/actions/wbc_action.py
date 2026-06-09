# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import numpy as np
import torch
import warp as wp
from typing import TYPE_CHECKING

from isaaclab.managers.action_manager import ActionTerm
from isaaclab_arena_g1.g1_env.mdp.actions.g1_decoupled_wbc_joint_action import G1DecoupledWBCJointAction
from isaaclab_arena_g1.g1_whole_body_controller.wbc_policy.run_policy import (
    convert_sim_joint_to_wbc_joint,
    postprocess_actions,
)

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedEnv
    from isaaclab_arena_g1.g1_env.mdp.actions.g1_decoupled_wbc_joint_action_cfg import G1DecoupledWBCJointActionCfg

class G1BraincoWBCAction(G1DecoupledWBCJointAction):
    """Custom action term for G1 with Brainco hands.
    
    This term overrides observation preparation to safely handle robots with 
    more than 43 degrees of freedom.
    """

    def process_actions(self, actions: torch.Tensor):
        # 1. Prepare actions (same as base)
        self._raw_actions[:] = actions
        
        # Use torch actions for command extraction to satisfy base class expectations
        navigate_cmd = self.get_navigation_cmd_from_actions(actions)
        base_height_cmd = self.get_base_height_cmd_from_actions(actions)
        torso_orientation_rpy_cmd = self.get_torso_orientation_rpy_cmd_from_actions(actions)

        # 2. Update WBC goal
        self.set_wbc_goal(navigate_cmd, base_height_cmd, torso_orientation_rpy_cmd)
        self.wbc_policy.set_goal(self._wbc_goal)

        # 3. PREPARE OBSERVATIONS (Custom implementation to avoid shape mismatch)
        wbc_obs = self._prepare_brainco_observations()
        
        # 4. Map target joints (use numpy for mapping logic)
        actions_np = actions.clone().cpu().numpy()
        sim_target_full_body_joints = actions_np[:, : self.num_joints]
        
        wbc_target_full_body_joints = self._brainco_convert_sim_to_wbc(
            sim_target_full_body_joints, self._asset.data.joint_names
        )
        
        wbc_target_upper_body_joints = wbc_target_full_body_joints[
            :, self.robot_model.get_joint_group_indices("upper_body")
        ]

        # 5. Execute WBC
        self.wbc_policy.set_observation(wbc_obs)
        wbc_action = self.wbc_policy.get_action(wbc_target_upper_body_joints)
        
        # 6. Post-process (maps back to sim joints)
        self._processed_actions = postprocess_actions(
            wbc_action, self._asset.data, self.wbc_g1_joints_order, self.device
        )

    def _brainco_convert_sim_to_wbc(self, sim_data, sim_names):
        """Maps sim joints to WBC joints, ignoring extra Brainco joints."""
        num_wbc_joints = len(self.wbc_g1_joints_order)
        wbc_data = np.zeros((self.num_envs, num_wbc_joints))
        
        for name in sim_names:
            if name in self.wbc_g1_joints_order:
                sim_idx = sim_names.index(name)
                wbc_idx = self.wbc_g1_joints_order[name]
                wbc_data[:, wbc_idx] = sim_data[:, sim_idx]
        return wbc_data

    def _prepare_brainco_observations(self):
        """Prepares a dictionary of observations specifically sized for the WBC (43 DOF)."""
        import isaaclab.utils.math as math_utils
        data = self._asset.data
        
        # Get raw data
        sim_joint_pos = wp.to_torch(data.joint_pos).cpu().numpy()
        sim_joint_vel = wp.to_torch(data.joint_vel).cpu().numpy()
        sim_default_pos = wp.to_torch(data.default_joint_pos).cpu().numpy()
        
        # Map to 43-DOF space
        q = self._brainco_convert_sim_to_wbc(sim_joint_pos, data.joint_names)
        dq = self._brainco_convert_sim_to_wbc(sim_joint_vel, data.joint_names)
        q_default = self._brainco_convert_sim_to_wbc(sim_default_pos, data.joint_names)
        ddq = np.zeros_like(q) # Dummy accelerations

        # Base Pose (same as original)
        root_pos_w = wp.to_torch(data.root_link_pos_w).cpu().numpy()
        root_quat_w_xyzw = wp.to_torch(data.root_link_quat_w).cpu().numpy()
        root_quat_w_wxyz = np.concatenate((root_quat_w_xyzw[:, 3:4], root_quat_w_xyzw[:, :3]), axis=1)
        base_pose_w = np.concatenate((root_pos_w, root_quat_w_wxyz), axis=1)
        
        base_lin_vel_b = wp.to_torch(data.root_link_lin_vel_b).cpu().numpy()
        base_ang_vel_b = wp.to_torch(data.root_link_ang_vel_b).cpu().numpy()
        base_vel_b = np.concatenate((base_lin_vel_b, base_ang_vel_b), axis=1)

        # Torso Data
        torso_state = wp.to_torch(data.body_link_state_w)[:, data.body_names.index("torso_link"), :]
        torso_quat_xyzw = torso_state[:, 3:7]
        torso_quat_wxyz = np.concatenate((torso_quat_xyzw[:, 3:4].cpu().numpy(), torso_quat_xyzw[:, :3].cpu().numpy()), axis=1)
        torso_ang_vel_w = torso_state[:, -3:]
        torso_ang_vel_b = math_utils.quat_apply_inverse(torso_quat_xyzw, torso_ang_vel_w).cpu().numpy()

        return {
            "q": q, "dq": dq, "ddq": ddq, "q_default": q_default,
            "floating_base_pose": base_pose_w, "floating_base_vel": base_vel_b,
            "torso_quat": torso_quat_wxyz, "torso_ang_vel": torso_ang_vel_b,
            "projected_gravity": wp.to_torch(data.projected_gravity_b).cpu().numpy(),
        }
