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
    """Reward the agent for lifting the object above the minimal height from its resting position."""
    from isaaclab_arena.tasks.predicates.spatial import object_lifted_above_resting_min

    lifted = object_lifted_above_resting_min(env, object_cfg.name, distance=minimal_height)
    return lifted.float()


def object_destination_distance(
    env: ManagerBasedRLEnv,
    std: float,
    minimal_height: float,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
    destination_cfg: SceneEntityCfg = SceneEntityCfg("destination"),
) -> torch.Tensor:
    """Reward the agent for tracking the destination location while lifted."""
    from isaaclab_arena.tasks.predicates.spatial import object_lifted_above_resting_min

    object: RigidObject = env.scene[object_cfg.name]
    destination: RigidObject = env.scene[destination_cfg.name]
    obj_pos_w = wp.to_torch(object.data.root_pos_w)[:, :3]
    dest_pos_w = wp.to_torch(destination.data.root_pos_w)[:, :3]
    distance = torch.norm(dest_pos_w - obj_pos_w, dim=1)
    is_lifted = object_lifted_above_resting_min(env, object_cfg.name, distance=minimal_height).float()
    return is_lifted * (1.0 - torch.tanh(distance / std))


def object_placed_bonus(
    env: ManagerBasedRLEnv,
    minimal_height: float,
    max_xy_distance: float,
    velocity_threshold: float = 0.2,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
    destination_cfg: SceneEntityCfg = SceneEntityCfg("destination"),
) -> torch.Tensor:
    """Reward bonus when the object is lifted and placed within the destination radius at low speed."""
    from isaaclab_arena.tasks.predicates.spatial import object_lifted_above_resting_min

    object: RigidObject = env.scene[object_cfg.name]
    destination: RigidObject = env.scene[destination_cfg.name]
    obj_pos_w = wp.to_torch(object.data.root_pos_w)[:, :3]
    dest_pos_w = wp.to_torch(destination.data.root_pos_w)[:, :3]
    distance_xy = torch.norm(obj_pos_w[:, :2] - dest_pos_w[:, :2], dim=1)
    is_lifted = object_lifted_above_resting_min(env, object_cfg.name, distance=minimal_height)

    # Object velocity gate: must be settling or resting (< 0.2 m/s), not flying
    obj_vel = wp.to_torch(object.data.root_lin_vel_w)
    speed = torch.norm(obj_vel, dim=-1)
    is_settled = speed < velocity_threshold

    # Object vertical proximity: must be within 5cm of destination height
    dz = torch.abs(obj_pos_w[:, 2] - dest_pos_w[:, 2])
    is_near_deck = dz < 0.05

    is_placed = (distance_xy < max_xy_distance) & is_lifted & is_settled & is_near_deck
    return is_placed.float()


def object_excess_velocity_penalty(
    env: ManagerBasedRLEnv,
    max_allowed_speed: float = 1.0,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
) -> torch.Tensor:
    """Penalize excessive object linear speed to prevent batting or swatting."""
    object: RigidObject = env.scene[object_cfg.name]
    obj_vel = wp.to_torch(object.data.root_lin_vel_w)
    speed = torch.norm(obj_vel, dim=-1)
    return -torch.clamp(speed - max_allowed_speed, min=0.0)


def action_rate_l2(env: ManagerBasedRLEnv) -> torch.Tensor:
    """Penalize large changes in consecutive actions for policy smoothness."""
    return torch.sum(torch.square(env.action_manager.action - env.action_manager.prev_action), dim=1)


def arm_joint_vel_l2(
    env: ManagerBasedRLEnv,
    robot_cfg: SceneEntityCfg = SceneEntityCfg("robot"),
) -> torch.Tensor:
    """Penalize large arm joint velocities for smooth trajectory execution."""
    robot: Articulation = env.scene[robot_cfg.name]
    joint_vel = wp.to_torch(robot.data.joint_vel)
    arm_names = [name for name in robot.data.joint_names if any(k in name for k in ("shoulder", "elbow", "wrist"))]
    if arm_names:
        ids, _ = robot.find_joints(arm_names)
        return torch.sum(torch.square(joint_vel[:, ids]), dim=1)
    return torch.sum(torch.square(joint_vel), dim=1)


def ee_approach_vector_alignment(
    env: ManagerBasedRLEnv,
    ee_link_name: str,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
    robot_cfg: SceneEntityCfg = SceneEntityCfg("robot"),
) -> torch.Tensor:
    """Reward alignment between the end-effector approach axis and the vector toward the target object.

    Args:
        env: The RL environment instance.
        ee_link_name: Name of the end-effector body link.
        object_cfg: Scene entity configuration for the target object.
        robot_cfg: Scene entity configuration for the robot.

    Returns:
        Cosine alignment score clamped to [0, 1].
    """
    from isaaclab.utils.math import quat_apply

    robot: Articulation = env.scene[robot_cfg.name]
    object: RigidObject = env.scene[object_cfg.name]
    assert ee_link_name in robot.data.body_names, f"Link {ee_link_name} not found in robot {robot_cfg.name}"
    link_idx = robot.data.body_names.index(ee_link_name)
    ee_pos_w = wp.to_torch(robot.data.body_pos_w)[:, link_idx, :]
    ee_quat_w = wp.to_torch(robot.data.body_quat_w)[:, link_idx, :]
    obj_pos_w = wp.to_torch(object.data.root_pos_w)[:, :3]

    to_obj = obj_pos_w - ee_pos_w
    dist = torch.norm(to_obj, dim=-1, keepdim=True).clamp(min=1e-6)
    target_dir = to_obj / dist

    local_axis = torch.tensor([0.0, 0.0, 1.0], device=ee_pos_w.device).repeat(ee_pos_w.shape[0], 1)
    hand_dir = quat_apply(ee_quat_w, local_axis)

    cos_sim = torch.sum(hand_dir * target_dir, dim=-1)
    return torch.clamp(cos_sim, min=0.0)


def finger_grasp_enclosure(
    env: ManagerBasedRLEnv,
    ee_link_name: str,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
    robot_cfg: SceneEntityCfg = SceneEntityCfg("robot"),
) -> torch.Tensor:
    """Reward finger enclosure when near the object and open aperture when approaching.

    Args:
        env: The RL environment instance.
        ee_link_name: Name of the end-effector link for proximity testing.
        object_cfg: Scene entity configuration for the target object.
        robot_cfg: SceneEntityCfg for the robot.

    Returns:
        Continuous grasp conditioning reward in [0, 1].
    """
    robot: Articulation = env.scene[robot_cfg.name]
    object: RigidObject = env.scene[object_cfg.name]
    assert ee_link_name in robot.data.body_names, f"Link {ee_link_name} not found in robot {robot_cfg.name}"
    link_idx = robot.data.body_names.index(ee_link_name)
    ee_pos_w = wp.to_torch(robot.data.body_pos_w)[:, link_idx, :]
    obj_pos_w = wp.to_torch(object.data.root_pos_w)[:, :3]
    distance = torch.norm(obj_pos_w - ee_pos_w, dim=-1)

    joint_pos_all = wp.to_torch(robot.data.joint_pos)
    flexions = []
    for i, name in enumerate(robot.data.joint_names):
        if "left_hand" in name:
            pos = joint_pos_all[:, i]
            if "index" in name or "middle" in name:
                # Closed curl is negative (down to -1.2 rad), open is 0.0
                flexions.append(torch.clamp(-pos / 1.0, 0.0, 1.0))
            elif "thumb_1" in name or "thumb_2" in name:
                # Closed curl is positive (up to +0.7 rad), open is 0.0
                flexions.append(torch.clamp(pos / 0.7, 0.0, 1.0))

    if flexions:
        mean_flexion = torch.mean(torch.stack(flexions, dim=-1), dim=-1)
    else:
        mean_flexion = torch.zeros_like(distance)

    near_mask = distance < 0.08
    close_reward = (1.0 - torch.tanh(distance / 0.08)) * torch.clamp(mean_flexion, 0.0, 1.0)
    open_reward = torch.tanh(distance / 0.15) * torch.clamp(1.0 - mean_flexion, 0.0, 1.0)
    return torch.where(near_mask, close_reward, open_reward)


def multi_keypoint_grasp_guidance(
    env: ManagerBasedRLEnv,
    object_cfg: SceneEntityCfg = SceneEntityCfg("object"),
    robot_cfg: SceneEntityCfg = SceneEntityCfg("robot"),
    std: float = 0.08,
) -> torch.Tensor:
    """Reward multi-keypoint enclosure of the object by hand links.

    Args:
        env: The RL environment instance.
        object_cfg: Scene entity configuration for the target object.
        robot_cfg: Scene entity configuration for the robot.
        std: Gaussian kernel bandwidth (standard deviation in meters).

    Returns:
        Mean exponential keypoint proximity score in [0, 1].
    """
    robot: Articulation = env.scene[robot_cfg.name]
    object: RigidObject = env.scene[object_cfg.name]
    obj_pos_w = wp.to_torch(object.data.root_pos_w)[:, :3]

    keypoint_links = [
        "left_wrist_yaw_link",
        "left_hand_thumb_2_link",
        "left_hand_index_1_link",
        "left_hand_middle_1_link",
    ]
    avail_indices = [robot.data.body_names.index(name) for name in keypoint_links if name in robot.data.body_names]
    if not avail_indices:
        return torch.zeros(env.num_envs, device=obj_pos_w.device)

    body_pos = wp.to_torch(robot.data.body_pos_w)[:, avail_indices, :]
    dists = torch.norm(body_pos - obj_pos_w.unsqueeze(1), dim=-1)
    keypoint_scores = torch.exp(-torch.square(dists) / (2.0 * std * std))
    return torch.mean(keypoint_scores, dim=-1)
