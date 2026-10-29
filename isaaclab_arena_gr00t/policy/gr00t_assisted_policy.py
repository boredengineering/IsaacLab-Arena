# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit privileged-state experiment wrapping scheduled GR00T actions.

Class path: isaaclab_arena_gr00t.policy.gr00t_assisted_policy.Gr00tAssistedPolicy.
The first get_action MUST follow environment settling; reset never samples a
pre-settle pose. No physics, WBC, success criteria or remote chunks are modified.
"""

from __future__ import annotations

import hashlib
import json
import math
import torch
from dataclasses import asdict, dataclass
from pathlib import Path

from isaaclab_arena.assets.register import register_policy
from isaaclab_arena.policy.policy_base import PolicyBase
from isaaclab_arena_gr00t.policy.g1_hand_assistance import ARM_SLOTS, AssistanceCfg, HandAssistance
from isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy import (
    Gr00tRemoteClosedloopPolicy,
    Gr00tRemoteClosedloopPolicyCfg,
)

# Exact existing 43dof_joint_space.yaml action order; reject different embodiments.
G1_JOINT_NAMES = [
    "left_hip_pitch_joint",
    "right_hip_pitch_joint",
    "waist_yaw_joint",
    "left_hip_roll_joint",
    "right_hip_roll_joint",
    "waist_roll_joint",
    "left_hip_yaw_joint",
    "right_hip_yaw_joint",
    "waist_pitch_joint",
    "left_knee_joint",
    "right_knee_joint",
    "left_shoulder_pitch_joint",
    "right_shoulder_pitch_joint",
    "left_ankle_pitch_joint",
    "right_ankle_pitch_joint",
    "left_shoulder_roll_joint",
    "right_shoulder_roll_joint",
    "left_ankle_roll_joint",
    "right_ankle_roll_joint",
    "left_shoulder_yaw_joint",
    "right_shoulder_yaw_joint",
    "left_elbow_joint",
    "right_elbow_joint",
    "left_wrist_roll_joint",
    "right_wrist_roll_joint",
    "left_wrist_pitch_joint",
    "right_wrist_pitch_joint",
    "left_wrist_yaw_joint",
    "right_wrist_yaw_joint",
    "left_hand_index_0_joint",
    "left_hand_middle_0_joint",
    "left_hand_thumb_0_joint",
    "right_hand_index_0_joint",
    "right_hand_middle_0_joint",
    "right_hand_thumb_0_joint",
    "left_hand_index_1_joint",
    "left_hand_middle_1_joint",
    "left_hand_thumb_1_joint",
    "right_hand_index_1_joint",
    "right_hand_middle_1_joint",
    "right_hand_thumb_1_joint",
    "left_hand_thumb_2_joint",
    "right_hand_thumb_2_joint",
]


@dataclass(kw_only=True)
class Gr00tAssistedPolicyCfg(Gr00tRemoteClosedloopPolicyCfg):
    """Remote policy settings plus required, explicit assistance input/output paths."""

    assistance_config_path: str
    """Existing JSON file matching AssistanceCfg; privileged_state=true is mandatory."""

    assistance_trace_path: str
    """New JSONL file (create-only); existing files are never overwritten."""


def _torch(value) -> torch.Tensor:
    """Read a live ProxyArray, torch tensor or deferred Warp array without sim imports."""
    if isinstance(value, torch.Tensor):
        return value
    if hasattr(value, "torch"):
        return value.torch
    import warp as wp

    return wp.to_torch(value)


def _finite_json(value):
    """Represent unavailable/nonfinite diagnostics as JSON null, never fabricated zeros."""
    if isinstance(value, dict):
        return {key: _finite_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finite_json(item) for item in value]
    return None if isinstance(value, float) and not math.isfinite(value) else value


@register_policy
class Gr00tAssistedPolicy(PolicyBase[Gr00tAssistedPolicyCfg]):
    """Compose the remote chunk scheduler with a single-env, left-hand experiment."""

    name = "gr00t_assisted"

    def __init__(self, config: Gr00tAssistedPolicyCfg):
        super().__init__(config)
        assert config.num_envs == 1 and config.scheduler == "chunk"
        self.assistance = AssistanceCfg.from_json(config.assistance_config_path)
        assert config.assistance_trace_path, "assistance_trace_path is required"
        path = Path(config.assistance_trace_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._trace = path.open("x")
        self.core = HandAssistance(self.assistance)
        self._bound = False
        try:
            self.base = Gr00tRemoteClosedloopPolicy(config)
            assert self.base.action_dim == 50
            assert self.base.policy_config.task_mode_name == "g1_locomanipulation"
            assert not self.base.policy_config.bilateral_mirror, "Bilateral mirror must be false"
            assert self.base.robot_action_joints_config == dict(
                zip(G1_JOINT_NAMES, range(43))
            ), "Exact G1 mapping required"
            self._trace.write(json.dumps({"record": "config", "config": asdict(self.assistance)}) + "\n")
            self._trace.flush()
        except Exception:
            self._trace.close()
            if hasattr(self, "base"):
                self.base.close()
            raise

    def _bind(self, env):
        assert env.num_envs == 1
        robot = env.scene["robot"]
        assert list(robot.joint_names) == G1_JOINT_NAMES, "Robot order differs from G1 50D joint-control action"
        assert env.action_manager.active_terms == ["g1_action"], "Only G1 joint-control supported"
        term = env.action_manager.get_term("g1_action")
        assert type(term).__name__ == "G1DecoupledWBCJointAction", "Pink/IK control is unsupported"
        assert term.action_dim == 50 and term._asset is robot
        assert list(term._joint_names) == G1_JOINT_NAMES
        self._body_id = list(robot.body_names).index(self.assistance.hand_body)
        self._arm_ids = [robot.joint_names.index(G1_JOINT_NAMES[i]) for i in ARM_SLOTS]
        self._jacobian_row = self._body_id - 1 if robot.is_fixed_base else self._body_id
        assert self._jacobian_row >= 0
        self._jacobian_columns = [i + robot.num_base_dofs for i in self._arm_ids]
        self._bound = True

    def get_action(self, env, observation) -> torch.Tensor:
        assert not self._trace.closed, "Assisted policy has been closed"
        live = env.unwrapped
        if not self._bound:
            self._bind(live)
        raw = self.base.get_action(env, observation)
        data = live.scene["robot"].data

        # Read current state each call, not chunk-time snapshots; ProxyArray.torch
        # is the Isaac Lab 3 API and Jacobian columns include floating-base DoFs.
        def tensor(value):
            return _torch(value).to(device=raw.device, dtype=raw.dtype)

        executed, trace = self.core.apply(
            raw=raw,
            measured=tensor(data.joint_pos)[0],
            jacobian=tensor(data.body_link_jacobian_w)[0, self._jacobian_row][:, self._jacobian_columns],
            limits=tensor(data.soft_joint_pos_limits)[0, self._arm_ids],
            hand_pos=tensor(data.body_link_pos_w)[0, self._body_id],
            object_pos=tensor(live.scene[self.assistance.object_name].data.root_link_pos_w)[0],
            dt=float(live.step_dt),
        )
        trace["frame"] = int(live.common_step_counter)
        if self.assistance.rgb_checksum:
            trace["rgb_checksum"] = {
                key: hashlib.sha256(_torch(value).detach().cpu().contiguous().numpy().tobytes()).hexdigest()
                for key, value in observation.get("camera_obs", {}).items()
                if "rgb" in key
            }
        self._trace.write(json.dumps(_finite_json(trace), allow_nan=False) + "\n")
        self._trace.flush()
        return executed

    def reset(self, env_ids: torch.Tensor | None = None):
        if env_ids is not None:
            assert env_ids.numel() == 1 and int(env_ids.item()) == 0
        self.core.reset()
        self._bound = False
        self.base.reset(env_ids)

    def close(self):
        try:
            if not self._trace.closed:
                self.base.close()
        finally:
            self._trace.close()

    def set_task_description(self, task_description: str | None) -> str:
        return self.base.set_task_description(task_description)
