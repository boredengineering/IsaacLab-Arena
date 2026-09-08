# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import torch
from typing import TYPE_CHECKING

import warp as wp

if TYPE_CHECKING:
    from isaaclab.assets import Articulation, RigidObject
    from isaaclab.envs import ManagerBasedRLEnv

from isaaclab.managers import SceneEntityCfg


def object_ee_distance(
    env: ManagerBasedRLEnv,
    std: float,
    ee_link_name: str,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
    robot_cfg: SceneEntityCfg = SceneEntityCfg("robot"),
) -> torch.Tensor:
    """Reward the agent for reaching the end-effector toward the object using a tanh kernel."""
    robot: Articulation = env.scene[robot_cfg.name]
    object: RigidObject = env.scene[object_cfg.name]
    assert ee_link_name in robot.data.body_names, f"Link {ee_link_name} not found in robot {robot_cfg.name}"
    link_idx = robot.data.body_names.index(ee_link_name)
    ee_pos_w = wp.to_torch(robot.data.body_pos_w)[:, link_idx, :]
    object_pos_w = wp.to_torch(object.data.root_pos_w)[:, :3]
    distance = torch.norm(object_pos_w - ee_pos_w, dim=1)
    return 1.0 - torch.tanh(distance / std)


def object_is_lifted(
    env: ManagerBasedRLEnv,
    minimal_height: float,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
) -> torch.Tensor:
    """Reward the agent for lifting the object above the minimal height."""
    object: RigidObject = env.scene[object_cfg.name]
    obj_z = wp.to_torch(object.data.root_pos_w)[:, 2]
    return torch.where(obj_z > minimal_height, 1.0, 0.0)


def object_destination_distance(
    env: ManagerBasedRLEnv,
    std: float,
    minimal_height: float,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
    destination_cfg: SceneEntityCfg = SceneEntityCfg("destination"),
) -> torch.Tensor:
    """Reward the agent for tracking the destination location while lifted."""
    object: RigidObject = env.scene[object_cfg.name]
    destination: RigidObject = env.scene[destination_cfg.name]
    obj_pos_w = wp.to_torch(object.data.root_pos_w)[:, :3]
    dest_pos_w = wp.to_torch(destination.data.root_pos_w)[:, :3]
    distance = torch.norm(dest_pos_w - obj_pos_w, dim=1)
    is_lifted = (obj_pos_w[:, 2] > minimal_height).float()
    return is_lifted * (1.0 - torch.tanh(distance / std))


def object_placed_bonus(
    env: ManagerBasedRLEnv,
    minimal_height: float,
    max_xy_distance: float,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
    destination_cfg: SceneEntityCfg = SceneEntityCfg("destination"),
) -> torch.Tensor:
    """Reward bonus when the object is lifted and placed within the destination radius."""
    object: RigidObject = env.scene[object_cfg.name]
    destination: RigidObject = env.scene[destination_cfg.name]
    obj_pos_w = wp.to_torch(object.data.root_pos_w)[:, :3]
    dest_pos_w = wp.to_torch(destination.data.root_pos_w)[:, :3]
    distance_xy = torch.norm(obj_pos_w[:, :2] - dest_pos_w[:, :2], dim=1)
    is_lifted = obj_pos_w[:, 2] > minimal_height
    is_placed = (distance_xy < max_xy_distance) & is_lifted
    return is_placed.float()


def action_rate_l2(env: ManagerBasedRLEnv) -> torch.Tensor:
    """Penalize large changes in consecutive actions for policy smoothness."""
    return torch.sum(torch.square(env.action_manager.action - env.action_manager.prev_action), dim=1)
