# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""GR00T remote closed-loop policy using GR00T's native PolicyClient.

This policy connects to a GR00T policy server (launched via
``gr00t/eval/run_gr00t_server.py``) and uses its own observation/action translation pipeline.
"""

from __future__ import annotations

import gymnasium as gym
import numpy as np
import torch
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal

from gr00t.policy.server_client import PolicyClient as Gr00tPolicyClient

from isaaclab_arena.assets.register import register_policy
from isaaclab_arena.policy.action_scheduling import ActionChunkScheduler, ActionScheduler, SyncedBatchActionScheduler
from isaaclab_arena.policy.policy_base import PolicyBase
from isaaclab_arena_gr00t.policy.config.gr00t_closedloop_policy_config import Gr00tClosedloopPolicyCfg, TaskMode
from isaaclab_arena_gr00t.policy.gr00t_core import (
    Gr00tBasePolicyCfg,
    build_gr00t_action_tensor,
    build_gr00t_policy_observations,
    compute_action_dim,
    compute_droid_eef_9d,
    extract_obs_numpy_from_torch,
    load_gr00t_joint_configs,
    resize_rgb_for_policy,
)
from isaaclab_arena_gr00t.utils.io_utils import create_config_from_yaml, load_gr00t_modality_config_from_file, to_numpy


# TODO(xinjieyao, 2026-04-27): Consider adding RemotePolicyCfg and deriving this config from it.
@dataclass
class Gr00tRemoteClosedloopPolicyCfg(Gr00tBasePolicyCfg):
    """Configuration for Gr00tRemoteClosedloopPolicy.

    Inherits policy_config_yaml_path and policy_device from Gr00tBasePolicyCfg,
    and adds remote server connection parameters and num_envs.
    """

    num_envs: int = 1
    """Number of parallel environments served by the policy."""

    remote_host: str = "localhost"
    """GR00T policy server hostname."""

    remote_port: int = 5555
    """GR00T policy server port."""

    remote_api_token: str | None = None
    """Optional policy-server API token."""

    scheduler: Literal["chunk", "synced_batch"] = "chunk"
    """Action scheduler used to consume inference chunks."""


@register_policy
class Gr00tRemoteClosedloopPolicy(PolicyBase[Gr00tRemoteClosedloopPolicyCfg]):
    """GR00T closed-loop policy that delegates inference to a remote GR00T server.

    Uses GR00T's native ``PolicyClient`` (from ``gr00t.policy.server_client``)
    to communicate with a GR00T policy server.
    """

    name = "gr00t_remote_closedloop"

    def __init__(self, config: Gr00tRemoteClosedloopPolicyCfg):
        super().__init__(config)

        action_scheduler_cls: type[ActionScheduler]
        if config.scheduler == "synced_batch":
            action_scheduler_cls = SyncedBatchActionScheduler
        else:
            assert config.scheduler == "chunk", f"Unknown action scheduler: {config.scheduler}"
            action_scheduler_cls = ActionChunkScheduler

        # Policy config (for obs/action translation — no model loading)
        # TODO(xinjieyao, 2026-04-27): to be refactored
        self.policy_config: Gr00tClosedloopPolicyCfg = create_config_from_yaml(
            config.policy_config_yaml_path, Gr00tClosedloopPolicyCfg
        )
        self.num_envs = config.num_envs
        self.device = config.policy_device
        self.task_mode = TaskMode(self.policy_config.task_mode_name)

        # Joint configs (for sim from/to policy joint space remapping)
        (
            self.policy_joints_config,
            self.robot_action_joints_config,
            self.robot_state_joints_config,
        ) = load_gr00t_joint_configs(self.policy_config)

        # Connect before choosing default modalities: the server may run a different GR00T version.
        client = Gr00tPolicyClient(
            host=config.remote_host,
            port=config.remote_port,
            api_token=config.remote_api_token,
            strict=False,
        )
        self._client: Gr00tPolicyClient | None = client
        if not client.ping():
            raise ConnectionError(f"Cannot reach GR00T policy server at {config.remote_host}:{config.remote_port}")

        if self.policy_config.modality_config_path:
            self.modality_configs = load_gr00t_modality_config_from_file(
                self.policy_config.modality_config_path,
                self.policy_config.embodiment_tag,
            )
        else:
            self.modality_configs = client.get_modality_config()

        # Action / chunk shapes
        self.action_dim = compute_action_dim(self.task_mode, self.robot_action_joints_config)
        action_delta = getattr(self.modality_configs.get("action"), "delta_indices", None)
        if action_delta is not None and hasattr(action_delta, "__len__"):
            self.action_horizon = len(action_delta)
        else:
            self.action_horizon = self.policy_config.action_horizon
        self.action_chunk_length = min(self.policy_config.action_chunk_length, self.action_horizon)

        self._chunking_state: ActionScheduler | None = action_scheduler_cls(
            num_envs=self.num_envs,
            action_chunk_length=self.action_chunk_length,
            action_horizon=self.action_horizon,
            action_dim=self.action_dim,
            device=self.device,
            dtype=torch.float,
        )

        # Temporal observation buffer for models requiring video horizon > 1 (e.g. GR00T-N1.7 delta_indices: [-15, 0])
        video_delta = getattr(self.modality_configs["video"], "delta_indices", [0])
        self._video_delta_indices: list[int] = list(video_delta) if hasattr(video_delta, "__len__") else [0]
        self._video_horizon: int = len(self._video_delta_indices)
        min_delta = min(self._video_delta_indices) if self._video_delta_indices else 0
        self._video_buffer_maxlen: int = abs(min_delta) + 1 if min_delta < 0 else 1
        self._video_history: list[deque[np.ndarray]] = []

        self.task_description: str | None = None

    # ---------------------- Policy interface -------------------

    def set_task_description(self, task_description: str | None) -> str:
        if task_description is None:
            task_description = self.policy_config.language_instruction
        if not task_description:
            raise ValueError(
                "No language instruction provided. Set 'language_instruction' in the job config, "
                "pass --language_instruction on the CLI, or define 'task_description' on the task class."
            )
        self.task_description = task_description
        return self.task_description

    def _update_video_history(self, observation: dict[str, Any]) -> None:
        """Update the temporal video observation buffer with the current frame."""
        camera_names = self.policy_config.pov_cam_name_sim
        if isinstance(camera_names, str):
            camera_names = [camera_names]
        rgb_list_np, _ = extract_obs_numpy_from_torch(nested_obs=observation, camera_names=camera_names)
        if getattr(self.policy_config, "bilateral_mirror", False):
            rgb_list_np = [np.ascontiguousarray(img[:, :, ::-1, :]) for img in rgb_list_np]
        target_image_size = getattr(self.policy_config, "target_image_size", None)
        if target_image_size is not None:
            rgb_list_np = resize_rgb_for_policy(rgb_list_np=rgb_list_np, target_image_size=target_image_size)

        if not self._video_history:
            self._video_history = [
                deque([cam_frames] * self._video_buffer_maxlen, maxlen=self._video_buffer_maxlen)
                for cam_frames in rgb_list_np
            ]
        else:
            for cam_idx, cam_frames in enumerate(rgb_list_np):
                self._video_history[cam_idx].append(cam_frames)

    def get_action(self, env: gym.Env, observation: dict[str, Any]) -> torch.Tensor:
        assert self._chunking_state is not None, "GR00T remote policy has been closed"

        if self._video_horizon > 1:
            self._update_video_history(observation)

        def fetch_chunk() -> torch.Tensor:
            return self._get_action_chunk(observation, self.policy_config.pov_cam_name_sim)

        return self._chunking_state.get_action(
            fetch_chunk,
            hold_action=self._extract_hold_action(observation),
        )

    def _extract_hold_action(self, observation: dict[str, Any]) -> torch.Tensor:
        """Build the action vector that waiting envs should hold: their current sim joint positions
        copied into the action slots that share a joint name with the state config."""
        joint_pos_sim = observation["policy"]["robot_joint_pos"].to(device=self.device, dtype=torch.float)
        hold_action = torch.zeros((self.num_envs, self.action_dim), dtype=torch.float, device=self.device)
        for joint_name, action_idx in self.robot_action_joints_config.items():
            state_idx = self.robot_state_joints_config.get(joint_name)
            if state_idx is not None:
                hold_action[:, action_idx] = joint_pos_sim[:, state_idx]
        return hold_action

    def _get_action_chunk(
        self, observation: dict[str, Any], camera_names: list[str] | str = "robot_head_cam_rgb"
    ) -> torch.Tensor:
        """Get an action chunk from the remote GR00T server.

        Calls GR00T's PolicyClient to get the action chunk.
        """
        if isinstance(camera_names, str):
            camera_names = [camera_names]

        # 1. Reuse the same obs translation as local policy
        assert self.task_description is not None, "Task description is not set"
        assert self._client is not None, "GR00T remote policy has been closed"
        rgb_list_np, joint_pos_sim_np = extract_obs_numpy_from_torch(nested_obs=observation, camera_names=camera_names)

        extra_state_np: dict[str, np.ndarray] = {}
        if "policy" in observation:
            policy_obs = observation["policy"]
            if "eef_9d" in policy_obs:
                extra_state_np["eef_9d"] = to_numpy(policy_obs["eef_9d"])
            elif "eef_pos" in policy_obs and "eef_quat" in policy_obs:
                pos = to_numpy(policy_obs["eef_pos"])
                quat = to_numpy(policy_obs["eef_quat"])
                extra_state_np["eef_9d"] = compute_droid_eef_9d(pos, quat)

        if getattr(self.policy_config, "bilateral_mirror", False):
            # Horizontally flip RGB observations: shape (N, H, W, C) -> width is axis 2
            rgb_list_np = [np.ascontiguousarray(img[:, :, ::-1, :]) for img in rgb_list_np]

        if self._video_horizon > 1:
            if not self._video_history:
                self._update_video_history(observation)
            temporal_rgb_list = []
            for cam_idx in range(len(rgb_list_np)):
                history_deque = self._video_history[cam_idx]
                sampled = [history_deque[d - 1] for d in self._video_delta_indices]
                temporal_rgb_list.append(np.stack(sampled, axis=1))
            rgb_list_np = temporal_rgb_list

        policy_observations = build_gr00t_policy_observations(
            rgb_list_np=rgb_list_np,
            joint_pos_sim_np=joint_pos_sim_np,
            task_description=self.task_description,
            policy_config=self.policy_config,
            robot_state_joints_config=self.robot_state_joints_config,
            policy_joints_config=self.policy_joints_config,
            modality_configs=self.modality_configs,
            extra_state_np=extra_state_np,
        )

        if getattr(self.policy_config, "bilateral_mirror", False):
            # Mirror input state: swap left and right arm/hand states presented to policy
            state_dict = policy_observations.get("state", {})
            arm_signs = np.array([1.0, -1.0, -1.0, 1.0, -1.0, 1.0, -1.0], dtype=np.float32)
            if "left_arm" in state_dict and "right_arm" in state_dict:
                l_arm = state_dict["left_arm"].copy()
                r_arm = state_dict["right_arm"].copy()
                state_dict["left_arm"] = r_arm * arm_signs
                state_dict["right_arm"] = l_arm * arm_signs
            if "left_hand" in state_dict and "right_hand" in state_dict:
                l_hand = state_dict["left_hand"].copy()
                r_hand = state_dict["right_hand"].copy()
                state_dict["left_hand"] = r_hand
                state_dict["right_hand"] = l_hand

        # 2. Call GR00T's own client
        robot_action_policy, _ = self._client.get_action(policy_observations)

        if getattr(self.policy_config, "bilateral_mirror", False):
            # Remap predicted left-arm action to physical right-arm action on the robot
            arm_signs = np.array([1.0, -1.0, -1.0, 1.0, -1.0, 1.0, -1.0], dtype=np.float32)
            if "left_arm" in robot_action_policy and "right_arm" in robot_action_policy:
                pred_l_arm = robot_action_policy["left_arm"].copy()
                pred_r_arm = robot_action_policy["right_arm"].copy()
                robot_action_policy["right_arm"] = pred_l_arm * arm_signs
                robot_action_policy["left_arm"] = pred_r_arm * arm_signs
            if "left_hand" in robot_action_policy and "right_hand" in robot_action_policy:
                pred_l_hand = robot_action_policy["left_hand"].copy()
                pred_r_hand = robot_action_policy["right_hand"].copy()
                robot_action_policy["right_hand"] = pred_l_hand
                robot_action_policy["left_hand"] = pred_r_hand

        # 3. Action translation from policy output to sim action tensor
        action_tensor = build_gr00t_action_tensor(
            robot_action_policy=robot_action_policy,
            task_mode=self.task_mode,
            policy_joints_config=self.policy_joints_config,
            robot_action_joints_config=self.robot_action_joints_config,
            device=self.device,
            embodiment_tag=self.policy_config.embodiment_tag,
        )

        assert action_tensor.shape[0] == self.num_envs and action_tensor.shape[1] >= self.action_chunk_length
        return action_tensor

    def reset(self, env_ids: torch.Tensor | None = None):
        if env_ids is None:
            env_ids = slice(None)
        assert self._client is not None, "GR00T remote policy has been closed"
        assert self._chunking_state is not None, "GR00T remote policy has been closed"
        self._client.reset()
        self._chunking_state.reset(env_ids)
        self._video_history = []

    def close(self) -> None:
        """Release Arena-side resources for the remote GR00T policy client."""
        client = self._client
        try:
            if client is not None:
                socket = getattr(client, "socket", None)
                context = getattr(client, "context", None)
                try:
                    if socket is not None:
                        socket.close(linger=0)
                finally:
                    if context is not None:
                        context.term()
        finally:
            self._client = None
            self._chunking_state = None
            self.modality_configs = None
