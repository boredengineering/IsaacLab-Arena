# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import yaml
import warnings
import importlib.util
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
    from g1_brainco_extension.embodiments.mdp.actions.wbc_action_cfg import G1BraincoWBCActionCfg


def is_running_in_container() -> bool:
    """Helper to detect if we are running inside the Docker container."""
    # Check standard container files/paths
    if os.path.exists("/.dockerenv"):
        return True
    if os.path.exists("/isaac-sim"):
        return True
    if os.path.exists("/workspaces/isaaclab_arena"):
        return True
    
    # Check cgroup for Docker/Containerd indicators
    try:
        if os.path.exists("/proc/self/cgroup"):
            with open("/proc/self/cgroup", "r") as f:
                content = f.read()
                if any(ind in content for ind in ["docker", "containerd", "kubepods", "lxc"]):
                    return True
    except Exception:
        pass
        
    return False


def find_policy_joints_yaml() -> str | None:
    """Resolves the path to the 43dof_joint_space.yaml file in a highly robust way."""
    # 1. Try resolving via package search spec
    try:
        spec = importlib.util.find_spec("isaaclab_arena_gr00t")
        if spec is not None and spec.submodule_search_locations:
            gr00t_dir = spec.submodule_search_locations[0]
            yaml_path = os.path.join(gr00t_dir, "embodiments/g1/43dof_joint_space.yaml")
            if os.path.exists(yaml_path):
                return yaml_path
    except Exception:
        pass

    # 2. Try traversing upwards from the current file's directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):  # Look up to 10 parent levels
        candidate = os.path.join(current_dir, "isaaclab_arena_gr00t/embodiments/g1/43dof_joint_space.yaml")
        if os.path.exists(candidate):
            return candidate
        parent_dir = os.path.dirname(current_dir)
        if parent_dir == current_dir:
            break
        current_dir = parent_dir

    # 3. Try standard absolute paths in container/workspace environments
    absolute_candidates = [
        "/workspaces/isaaclab_arena/isaaclab_arena_gr00t/embodiments/g1/43dof_joint_space.yaml",
        "/workspaces/IsaacLab-Arena/isaaclab_arena_gr00t/embodiments/g1/43dof_joint_space.yaml",
    ]
    for path in absolute_candidates:
        if os.path.exists(path):
            return path

    return None


def get_log_path() -> str:
    """Resolves a robust path for wbc_debug.log in the extension root."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    ext_root = current_dir
    for _ in range(10):
        if os.path.basename(ext_root) == "g1_brainco_extension":
            break
        parent = os.path.dirname(ext_root)
        if parent == ext_root:
            break
        ext_root = parent
    return os.path.join(ext_root, "wbc_debug.log")


class G1BraincoWBCAction(G1DecoupledWBCJointAction):
    """Custom action term for G1 with Brainco hands.
    
    This term overrides observation preparation to safely handle robots with 
    more than 43 degrees of freedom.
    """

    def __init__(self, cfg: G1BraincoWBCActionCfg, env: ManagerBasedEnv):
        super().__init__(cfg, env)
        
        # Filter wbc_g1_joints_order to only include joints that exist in the asset
        # to avoid warnings during postprocess_actions
        self.wbc_g1_joints_order_filtered = {
            name: idx for name, idx in self.wbc_g1_joints_order.items()
            if name in self._asset.data.joint_names
        }

        # Check and warn if we are not running inside the Docker container
        in_container = is_running_in_container()
        if not in_container:
            warnings.warn(
                "G1BraincoWBCAction: It appears that this script is not running inside the Docker container "
                "('isaaclab_arena-latest'). Running outside the container may result in path resolution "
                "issues or missing simulation dependencies. Please confirm your execution environment.",
                UserWarning
            )

        # Load 43dof policy action joint space config to map joint names to policy indices
        policy_joints_yaml = find_policy_joints_yaml()
        self.load_error = None
        self.policy_joints_order = {}

        if policy_joints_yaml is not None:
            try:
                with open(policy_joints_yaml, "r") as f:
                    yaml_data = yaml.safe_load(f)
                    self.policy_joints_order = yaml_data["joints"]
            except Exception as e:
                self.load_error = f"Exception occurred while loading path {policy_joints_yaml}: {e}"
        else:
            self.load_error = "Could not locate 43dof_joint_space.yaml config file in the environment."

        # Debug paths
        self.debug_paths = {
            "__file__": __file__,
            "abspath(__file__)": os.path.abspath(__file__),
            "policy_joints_yaml": policy_joints_yaml,
            "policy_joints_order_size": len(self.policy_joints_order),
            "load_error": self.load_error,
            "running_in_container": in_container,
        }

        if not cfg.lock_waist:
            from isaaclab_arena_g1.g1_whole_body_controller.wbc_policy.config.configs import AgileConfig, HomieV2Config
            from isaaclab_arena_g1.g1_whole_body_controller.wbc_policy.utils.g1 import instantiate_g1_robot_model
            from isaaclab_arena_g1.g1_whole_body_controller.wbc_policy.policy.wbc_policy_factory import get_wbc_policy

            if self._wbc_version == "homie_v2":
                wbc_config = HomieV2Config()
            elif self._wbc_version == "agile":
                wbc_config = AgileConfig()
            else:
                raise ValueError(f"Invalid WBC version: {self._wbc_version}")

            wbc_config.enable_waist = True
            waist_location = "lower_and_upper_body"
            self.robot_model = instantiate_g1_robot_model(waist_location=waist_location)
            self.wbc_policy = get_wbc_policy("g1", self.robot_model, wbc_config, self.num_envs)

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
        # Note: actions contains the policy's raw actions. The first 43 DOFs are in policy order (43dof_joint_space.yaml).
        actions_np = actions.clone().cpu().numpy()
        policy_joint_data = actions_np[:, : self.num_joints]
        
        # Remap from policy/sim order (43dof_joint_space.yaml) to WBC order (loco_manip_g1_joints_order_43dof.yaml)
        wbc_target_full_body_joints = np.zeros((self.num_envs, 43))
        for joint_name, wbc_idx in self.wbc_g1_joints_order.items():
            if joint_name in self.policy_joints_order:
                policy_idx = self.policy_joints_order[joint_name]
                wbc_target_full_body_joints[:, wbc_idx] = policy_joint_data[:, policy_idx]
            else:
                # Fallback to aliases
                from isaaclab_arena_gr00t.utils.joints_conversion import JOINT_ALIASES
                aliases = JOINT_ALIASES.get(joint_name, [])
                mapped = False
                for alias in aliases:
                    if alias in self.policy_joints_order:
                        policy_idx = self.policy_joints_order[alias]
                        wbc_target_full_body_joints[:, wbc_idx] = policy_joint_data[:, policy_idx]
                        mapped = True
                        break
                if not mapped:
                    wbc_target_full_body_joints[:, wbc_idx] = 0.0
        
        wbc_target_upper_body_joints = wbc_target_full_body_joints[
            :, self.robot_model.get_joint_group_indices("upper_body")
        ]

        # 5. Execute WBC
        self.wbc_policy.set_observation(wbc_obs)
        wbc_action = self.wbc_policy.get_action(wbc_target_upper_body_joints)
        
        # 6. Post-process (maps back to sim joints)
        self._processed_actions = postprocess_actions(
            wbc_action, self._asset.data, self.wbc_g1_joints_order_filtered, self.device
        )

        # 7. Map policy hand joints to simulation hand joints
        policy_to_sim_map = {
            # Left hand
            "left_hand_index_0_joint": "left_index_proximal_joint",
            "left_hand_index_1_joint": "left_index_distal_joint",
            "left_hand_middle_0_joint": "left_middle_proximal_joint",
            "left_hand_middle_1_joint": "left_middle_distal_joint",
            "left_hand_thumb_0_joint": "left_thumb_metacarpal_joint",
            "left_hand_thumb_1_joint": "left_thumb_proximal_joint",
            "left_hand_thumb_2_joint": "left_thumb_distal_joint",
            # Right hand
            "right_hand_index_0_joint": "right_index_proximal_joint",
            "right_hand_index_1_joint": "right_index_distal_joint",
            "right_hand_middle_0_joint": "right_middle_proximal_joint",
            "right_hand_middle_1_joint": "right_middle_distal_joint",
            "right_hand_thumb_0_joint": "right_thumb_metacarpal_joint",
            "right_hand_thumb_1_joint": "right_thumb_proximal_joint",
            "right_hand_thumb_2_joint": "right_thumb_distal_joint",
        }

        joint_names = self._asset.data.joint_names
        
        for policy_name, sim_name in policy_to_sim_map.items():
            if policy_name in self.policy_joints_order and sim_name in joint_names:
                policy_idx = self.policy_joints_order[policy_name]
                sim_idx = joint_names.index(sim_name)
                # Fix: map direct from the policy actions, since WBC doesn't track fingers
                self._processed_actions[:, sim_idx] = actions[:, policy_idx]

        # 8. Mimic coupling for extra dexterous joints (ring and pinky) and tips
        mimic_finger_map = {
            # Ring mimics middle
            "left_ring_proximal_joint": "left_middle_proximal_joint",
            "left_ring_distal_joint": "left_middle_distal_joint",
            "right_ring_proximal_joint": "right_middle_proximal_joint",
            "right_ring_distal_joint": "right_middle_distal_joint",
            # Pinky mimics middle
            "left_pinky_proximal_joint": "left_middle_proximal_joint",
            "left_pinky_distal_joint": "left_middle_distal_joint",
            "right_pinky_proximal_joint": "right_middle_proximal_joint",
            "right_pinky_distal_joint": "right_middle_distal_joint",
        }

        mimic_tip_map = {
            # Tips mimic distal joints
            "left_index_tip_joint": "left_index_distal_joint",
            "left_middle_tip_joint": "left_middle_distal_joint",
            "left_ring_tip_joint": "left_ring_distal_joint",
            "left_pinky_tip_joint": "left_pinky_distal_joint",
            "left_thumb_tip_joint": "left_thumb_distal_joint",
            "right_index_tip_joint": "right_index_distal_joint",
            "right_middle_tip_joint": "right_middle_distal_joint",
            "right_ring_tip_joint": "right_ring_distal_joint",
            "right_pinky_tip_joint": "right_pinky_distal_joint",
            "right_thumb_tip": "right_thumb_distal_joint",
        }

        # Apply mimic mappings
        for target_name, source_name in mimic_finger_map.items():
            if target_name in joint_names and source_name in joint_names:
                target_idx = joint_names.index(target_name)
                source_idx = joint_names.index(source_name)
                self._processed_actions[:, target_idx] = self._processed_actions[:, source_idx]

        for target_name, source_name in mimic_tip_map.items():
            if target_name in joint_names and source_name in joint_names:
                target_idx = joint_names.index(target_name)
                source_idx = joint_names.index(source_name)
                self._processed_actions[:, target_idx] = self._processed_actions[:, source_idx]

        # File-based logging for WBC_DEBUG
        if os.environ.get("WBC_DEBUG", "0") == "1":
            log_path = get_log_path()
            mode = "w" if not getattr(self, "_debug_file_initialized", False) else "a"
            try:
                if not getattr(self, "_debug_file_initialized", False):
                    with open(log_path, "w") as f:
                        f.write(f"Asset Joint Names: {self._asset.data.joint_names}\n\n")
                        f.write(f"WBC Joint Order: {list(self.wbc_g1_joints_order.keys())}\n\n")
                        f.write(f"Policy Joint Order: {list(self.policy_joints_order.keys())}\n\n")
                        if hasattr(self, "load_error") and self.load_error is not None:
                            f.write(f"LOAD ERROR: {self.load_error}\n\n")
                        if hasattr(self, "debug_paths"):
                            f.write(f"Debug Paths:\n")
                            for k, v in self.debug_paths.items():
                                f.write(f"  {k}: {v}\n")
                            f.write("\n")
                self._debug_file_initialized = True
                
                with open(log_path, "a") as f:
                    f.write(f"\n--- WBC DEBUG STEP ---\n")
                    f.write(f"num_envs: {self.num_envs}\n")
                    f.write(f"actions (first 10): {actions.cpu().numpy()[0, :10]}\n")
                    left_arm_indices = [self.policy_joints_order[name] for name in ["left_shoulder_pitch_joint", "left_shoulder_roll_joint", "left_shoulder_yaw_joint", "left_elbow_joint", "left_wrist_roll_joint", "left_wrist_pitch_joint", "left_wrist_yaw_joint"] if name in self.policy_joints_order]
                    right_arm_indices = [self.policy_joints_order[name] for name in ["right_shoulder_pitch_joint", "right_shoulder_roll_joint", "right_shoulder_yaw_joint", "right_elbow_joint", "right_wrist_roll_joint", "right_wrist_pitch_joint", "right_wrist_yaw_joint"] if name in self.policy_joints_order]
                    f.write(f"actions (arm joints left targets): {actions.cpu().numpy()[0, left_arm_indices]}\n")
                    f.write(f"actions (arm joints right targets): {actions.cpu().numpy()[0, right_arm_indices]}\n")
                    f.write(f"navigate_cmd (vel_x, vel_y, yaw): {navigate_cmd.cpu().numpy()[0]}\n")
                    f.write(f"base_height_cmd (height): {base_height_cmd.cpu().numpy()[0]}\n")
                    f.write(f"torso_orientation_rpy_cmd: {torso_orientation_rpy_cmd.cpu().numpy()[0]}\n")
                    f.write(f"wbc_obs q (first 5): {wbc_obs['q'][0, :5]}\n")
                    f.write(f"wbc_action q (first 5): {wbc_action['q'][0, :5]}\n")
                    arm_names_to_log = ["left_shoulder_pitch_joint", "left_shoulder_roll_joint", "left_shoulder_yaw_joint", "left_elbow_joint", "right_shoulder_pitch_joint", "right_shoulder_roll_joint", "right_shoulder_yaw_joint", "right_elbow_joint"]
                    arm_indices = {name: joint_names.index(name) for name in arm_names_to_log if name in joint_names}
                    arm_targets = {name: self._processed_actions[0, idx].item() for name, idx in arm_indices.items()}
                    f.write(f"arm joint targets: {arm_targets}\n")
            except Exception as e:
                print(f"[WBC DEBUG ERROR] Failed to write to {log_path}: {e}")


    def _brainco_convert_sim_to_wbc(self, sim_data, sim_names):
        """Maps sim joints to WBC joints, ignoring extra Brainco joints."""
        num_wbc_joints = len(self.wbc_g1_joints_order)
        wbc_data = np.zeros((self.num_envs, num_wbc_joints))
        
        sim_to_policy_map = {
            # Left hand
            "left_index_proximal_joint": "left_hand_index_0_joint",
            "left_index_distal_joint": "left_hand_index_1_joint",
            "left_middle_proximal_joint": "left_hand_middle_0_joint",
            "left_middle_distal_joint": "left_hand_middle_1_joint",
            "left_thumb_metacarpal_joint": "left_hand_thumb_0_joint",
            "left_thumb_proximal_joint": "left_hand_thumb_1_joint",
            "left_thumb_distal_joint": "left_hand_thumb_2_joint",
            # Right hand
            "right_index_proximal_joint": "right_hand_index_0_joint",
            "right_index_distal_joint": "right_hand_index_1_joint",
            "right_middle_proximal_joint": "right_hand_middle_0_joint",
            "right_middle_distal_joint": "right_hand_middle_1_joint",
            "right_thumb_metacarpal_joint": "right_hand_thumb_0_joint",
            "right_thumb_proximal_joint": "right_hand_thumb_1_joint",
            "right_thumb_distal_joint": "right_hand_thumb_2_joint",
        }

        for name in sim_names:
            policy_name = sim_to_policy_map.get(name, name)
            if policy_name in self.wbc_g1_joints_order:
                sim_idx = sim_names.index(name)
                if sim_idx < sim_data.shape[1]:
                    wbc_idx = self.wbc_g1_joints_order[policy_name]
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
