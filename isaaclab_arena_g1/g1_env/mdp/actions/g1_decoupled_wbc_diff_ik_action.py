# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import torch
from collections.abc import Sequence
from typing import TYPE_CHECKING

import isaaclab.utils.math as math_utils
from isaaclab.controllers import DifferentialIKController

from isaaclab_arena_g1.g1_env.mdp.actions.g1_decoupled_wbc_joint_action import G1DecoupledWBCJointAction
from isaaclab_arena_g1.g1_whole_body_controller.wbc_policy.run_policy import (
    convert_sim_joint_to_wbc_joint,
    postprocess_actions,
    prepare_observations,
)

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedEnv

    from isaaclab_arena_g1.g1_env.mdp.actions.g1_decoupled_wbc_diff_ik_action_cfg import G1DecoupledWBCDiffIKActionCfg


def _to_torch(value) -> torch.Tensor:
    """Read a live ProxyArray, torch tensor or Warp array."""
    if isinstance(value, torch.Tensor):
        return value
    if hasattr(value, "torch"):
        return value.torch
    import warp as wp

    return wp.to_torch(value)


class G1DecoupledWBCDiffIKAction(G1DecoupledWBCJointAction):
    """Action term for G1 humanoid combining GPU Differential IK for the upper body with AGILE WBC balancing.

    Action dimension is 7:
        - [0:3]: End-effector Cartesian translation delta [dx, dy, dz] in base frame.
        - [3:6]: End-effector Cartesian rotation delta [droll, dpitch, dyaw] in base frame.
        - [6]: Finger grasp synergy g in [-1, 1] (-1 for fully open, +1 for closed grasp).
    """

    cfg: G1DecoupledWBCDiffIKActionCfg

    def __init__(self, cfg: G1DecoupledWBCDiffIKActionCfg, env: ManagerBasedEnv):
        super().__init__(cfg, env)

        # Resolve arm joint IDs for Differential IK
        self._arm_joint_ids, self._arm_joint_names = self._asset.find_joints(self.cfg.arm_joint_names)
        assert len(self._arm_joint_ids) == len(
            self.cfg.arm_joint_names
        ), f"Not all arm joints found: expected {self.cfg.arm_joint_names}, got {self._arm_joint_names}"

        # Resolve end-effector body index
        body_indices, _ = self._asset.find_bodies(self.cfg.ee_link_name)
        assert len(body_indices) > 0, f"End-effector link {self.cfg.ee_link_name} not found in robot bodies"
        self._ee_body_idx = body_indices[0]

        # Calculate Jacobian row and column indices (accounting for fixed/floating base DoFs)
        self._jacobian_row = self._ee_body_idx - 1 if self._asset.is_fixed_base else self._ee_body_idx
        self._jacobian_cols = [idx + self._asset.num_base_dofs for idx in self._arm_joint_ids]

        # Initialize GPU Differential IK controller
        self._ik_controller = DifferentialIKController(
            cfg=self.cfg.controller,
            num_envs=self.num_envs,
            device=self.device,
        )

        # Resolve left hand joint IDs for synergy mapping
        self._hand_joint_map = {}
        for name in [
            "left_hand_index_0_joint",
            "left_hand_index_1_joint",
            "left_hand_middle_0_joint",
            "left_hand_middle_1_joint",
            "left_hand_thumb_0_joint",
            "left_hand_thumb_1_joint",
            "left_hand_thumb_2_joint",
        ]:
            ids, _ = self._asset.find_joints([name])
            if ids:
                self._hand_joint_map[name] = ids[0]

        # Overwrite raw actions tensor with 7-D shape
        self._raw_actions = torch.zeros(self.num_envs, self.action_dim, device=self.device)
        self._prev_delta_pose = torch.zeros(self.num_envs, 6, device=self.device)

        # Pre-allocate scale tensor
        self._scale_tensor = torch.tensor(
            [self.cfg.scale_pos] * 3 + [self.cfg.scale_rot] * 3,
            device=self.device,
        ).repeat(self.num_envs, 1)

    @property
    def action_dim(self) -> int:
        """7-D: 6-D delta Cartesian pose + 1-D finger grasp synergy."""
        return 7

    def process_actions(self, actions: torch.Tensor):
        """Process 7-D task-space action commands and execute Differential IK + AGILE WBC."""
        self._raw_actions[:] = actions[:, : self.action_dim]

        # Extract delta pose and finger grasp synergy
        delta_pose = self._raw_actions[:, :6] * self._scale_tensor
        finger_cmd = self._raw_actions[:, 6:7]

        # Apply EMA smoothing on Cartesian delta pose to prevent sudden jerks
        if hasattr(self.cfg, "ema_factor") and self.cfg.ema_factor < 1.0:
            delta_pose = self.cfg.ema_factor * delta_pose + (1.0 - self.cfg.ema_factor) * self._prev_delta_pose
            self._prev_delta_pose.copy_(delta_pose)

        # 1. Compute current EE pose in robot root (pelvis) frame
        root_pos_w = _to_torch(self._asset.data.root_pos_w)
        root_quat_w = _to_torch(self._asset.data.root_quat_w)
        ee_pos_w = _to_torch(self._asset.data.body_pos_w)[:, self._ee_body_idx]
        ee_quat_w = _to_torch(self._asset.data.body_quat_w)[:, self._ee_body_idx]

        ee_pos_b, ee_quat_b = math_utils.subtract_frame_transforms(root_pos_w, root_quat_w, ee_pos_w, ee_quat_w)

        # 2. Feed Cartesian delta into Differential IK controller
        self._ik_controller.set_command(delta_pose, ee_pos_b, ee_quat_b)

        # 3. Transform PhysX Jacobian from world frame to base frame
        jacobian_all = _to_torch(self._asset.data.body_link_jacobian_w)
        jacobian_w = jacobian_all[:, self._jacobian_row, :, :][:, :, self._jacobian_cols]
        base_rot_matrix = math_utils.matrix_from_quat(math_utils.quat_inv(root_quat_w))
        jacobian_b = jacobian_w.clone()
        jacobian_b[:, :3, :] = torch.bmm(base_rot_matrix, jacobian_w[:, :3, :])
        jacobian_b[:, 3:, :] = torch.bmm(base_rot_matrix, jacobian_w[:, 3:, :])

        # 4. Compute target arm joint angles via Differential IK
        current_arm_q = _to_torch(self._asset.data.joint_pos)[:, self._arm_joint_ids]
        arm_joint_pos_des = self._ik_controller.compute(ee_pos_b, ee_quat_b, jacobian_b, current_arm_q)

        # 5. Map continuous grasp synergy g in [-1, 1] to finger joints
        curl = torch.clamp(0.5 * (finger_cmd + 1.0), 0.0, 1.0)

        # 6. Assemble full joint target vector
        full_body_des = _to_torch(self._asset.data.default_joint_pos).clone()
        full_body_des[:, self._arm_joint_ids] = arm_joint_pos_des
        for name, joint_id in self._hand_joint_map.items():
            if "index_0" in name or "middle_0" in name:
                full_body_des[:, joint_id] = -0.6 * curl.squeeze(-1)
            elif "index_1" in name or "middle_1" in name:
                full_body_des[:, joint_id] = -1.2 * curl.squeeze(-1)
            elif "thumb_1" in name or "thumb_2" in name:
                full_body_des[:, joint_id] = 0.7 * curl.squeeze(-1)

        # 7. Convert to WBC order and extract upper body targets
        wbc_target_full_body = convert_sim_joint_to_wbc_joint(
            full_body_des, self._asset.data.joint_names, self.wbc_g1_joints_order
        )
        wbc_target_upper = wbc_target_full_body[:, self.robot_model.get_joint_group_indices("upper_body")]

        # 8. Set WBC standing balance goal (pelvis height 0.75m, neutral orientation)
        self.wbc_policy.set_goal(self._wbc_goal)

        # 9. Execute AGILE WBC closed-loop balance policy
        wbc_obs = prepare_observations(self.num_envs, self._asset.data, self.wbc_g1_joints_order)
        self.wbc_policy.set_observation(wbc_obs)
        wbc_action = self.wbc_policy.get_action(wbc_target_upper)

        # 10. Post-process WBC actions back to PhysX joint order
        self._processed_actions = postprocess_actions(
            wbc_action, self._asset.data, self.wbc_g1_joints_order, self.device
        )

    def reset(self, env_ids: Sequence[int] | None = None) -> None:
        """Reset action history."""
        if env_ids is None:
            self._raw_actions.zero_()
            self._prev_delta_pose.zero_()
            self._ik_controller.reset()
        else:
            self._raw_actions[env_ids] = 0.0
            self._prev_delta_pose[env_ids] = 0.0
            env_ids_tensor = torch.as_tensor(env_ids, dtype=torch.long, device=self.device)
            self._ik_controller.reset(env_ids_tensor)
