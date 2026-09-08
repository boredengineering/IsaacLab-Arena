# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import torch
from unittest.mock import MagicMock, patch

import warp as wp
from isaaclab.managers import SceneEntityCfg

from isaaclab_arena.tasks.rewards import pick_and_place_rewards

wp.init()


def test_action_rate_l2():
    """Verify action rate L2 regularization penalty calculation."""
    mock_env = MagicMock()
    mock_env.action_manager.action = torch.tensor([[1.0, 2.0], [0.5, 0.5]])
    mock_env.action_manager.prev_action = torch.tensor([[0.0, 2.0], [0.5, -0.5]])
    penalty = pick_and_place_rewards.action_rate_l2(mock_env)
    # Env 0: (1-0)^2 + (2-2)^2 = 1.0; Env 1: (0.5-0.5)^2 + (0.5 - (-0.5))^2 = 1.0
    expected = torch.tensor([1.0, 1.0])
    assert torch.allclose(penalty, expected), f"action_rate_l2 expected {expected}, got {penalty}"


def test_object_is_lifted():
    """Verify lifting indicator reward."""
    mock_env = MagicMock()
    with patch(
        "isaaclab_arena.tasks.predicates.spatial.object_lifted_above_resting_min",
        return_value=torch.tensor([True, False]),
    ):
        reward = pick_and_place_rewards.object_is_lifted(
            mock_env, minimal_height=0.03, object_cfg=SceneEntityCfg("object")
        )
        expected = torch.tensor([1.0, 0.0])
        assert torch.allclose(reward, expected), f"object_is_lifted expected {expected}, got {reward}"


def test_object_ee_distance():
    """Verify reaching reward using tanh kernel."""
    mock_env = MagicMock()
    mock_robot = MagicMock()
    mock_obj = MagicMock()

    mock_robot.data.body_names = ["link_0", "ee_link"]
    # 2 envs, link 1 (ee_link) at [0, 0, 0] for env 0, [0, 0, 0] for env 1
    ee_pos = torch.zeros(2, 2, 3)
    mock_robot.data.body_pos_w = wp.from_torch(ee_pos)

    # Object positions: env 0 at [0, 0, 0] (dist 0), env 1 at [0.1, 0, 0] (dist 0.1)
    obj_pos = torch.tensor([[0.0, 0.0, 0.0], [0.1, 0.0, 0.0]])
    mock_obj.data.root_pos_w = wp.from_torch(obj_pos)

    mock_env.scene = {"robot": mock_robot, "object": mock_obj}

    reward = pick_and_place_rewards.object_ee_distance(
        mock_env,
        std=0.1,
        ee_link_name="ee_link",
        object_cfg=SceneEntityCfg("object"),
        robot_cfg=SceneEntityCfg("robot"),
    )
    # Env 0: dist=0 -> 1 - tanh(0) = 1.0
    # Env 1: dist=0.1 -> 1 - tanh(1.0) ~ 0.2384
    expected_1 = 1.0 - torch.tanh(torch.tensor(1.0))
    assert torch.allclose(reward[0], torch.tensor(1.0), atol=1e-5), "Env 0 reaching reward should be 1.0"
    assert torch.allclose(
        reward[1], expected_1, atol=1e-5
    ), f"Env 1 reaching reward expected {expected_1}, got {reward[1]}"


def test_object_destination_distance():
    """Verify destination tracking reward gated on lifting."""
    mock_env = MagicMock()
    mock_obj = MagicMock()
    mock_dest = MagicMock()

    # Env 0: lifted (z=0.05 > 0.03), dist to dest = 0 -> reward = 1.0
    # Env 1: not lifted (z=0.01 <= 0.03), dist to dest = 0 -> reward = 0.0
    # Env 2: lifted (z=0.05 > 0.03), dist to dest = 0.25 -> reward = 1 - tanh(1.0)
    obj_pos = torch.tensor([
        [0.0, 0.0, 0.05],
        [0.0, 0.0, 0.01],
        [0.25, 0.0, 0.05],
    ])
    dest_pos = torch.tensor([
        [0.0, 0.0, 0.05],
        [0.0, 0.0, 0.05],
        [0.0, 0.0, 0.05],
    ])
    mock_obj.data.root_pos_w = wp.from_torch(obj_pos)
    mock_dest.data.root_pos_w = wp.from_torch(dest_pos)

    mock_env.scene = {"object": mock_obj, "destination": mock_dest}

    with patch(
        "isaaclab_arena.tasks.predicates.spatial.object_lifted_above_resting_min",
        return_value=torch.tensor([True, False, True]),
    ):
        reward = pick_and_place_rewards.object_destination_distance(
            mock_env,
            std=0.25,
            minimal_height=0.03,
            object_cfg=SceneEntityCfg("object"),
            destination_cfg=SceneEntityCfg("destination"),
        )
        expected = torch.tensor([1.0, 0.0, 1.0 - torch.tanh(torch.tensor(1.0))])
        assert torch.allclose(
            reward, expected, atol=1e-5
        ), f"destination tracking reward expected {expected}, got {reward}"


def test_object_placed_bonus():
    """Verify discrete placement bonus requires both lifting and destination proximity."""
    mock_env = MagicMock()
    mock_obj = MagicMock()
    mock_dest = MagicMock()

    # Env 0: lifted (z=0.05 > 0.03) and close (xy dist = 0.02 < 0.05) -> bonus 1.0
    # Env 1: not lifted (z=0.02 <= 0.03) and close (xy dist = 0.02) -> bonus 0.0
    # Env 2: lifted (z=0.05 > 0.03) but far (xy dist = 0.10 >= 0.05) -> bonus 0.0
    obj_pos = torch.tensor([
        [0.02, 0.0, 0.04],
        [0.02, 0.0, 0.02],
        [0.10, 0.0, 0.04],
    ])
    dest_pos = torch.zeros(3, 3)
    mock_obj.data.root_pos_w = wp.from_torch(obj_pos)
    mock_obj.data.root_lin_vel_w = wp.from_torch(torch.zeros(3, 3))
    mock_dest.data.root_pos_w = wp.from_torch(dest_pos)

    mock_env.scene = {"object": mock_obj, "destination": mock_dest}

    with patch(
        "isaaclab_arena.tasks.predicates.spatial.object_lifted_above_resting_min",
        return_value=torch.tensor([True, False, True]),
    ):
        bonus = pick_and_place_rewards.object_placed_bonus(
            mock_env,
            minimal_height=0.03,
            max_xy_distance=0.05,
            object_cfg=SceneEntityCfg("object"),
            destination_cfg=SceneEntityCfg("destination"),
        )
        expected = torch.tensor([1.0, 0.0, 0.0])
        assert torch.allclose(bonus, expected), f"object_placed_bonus expected {expected}, got {bonus}"


def test_multi_keypoint_grasp_guidance():
    """Verify multi-keypoint grasp guidance score."""
    mock_env = MagicMock()
    mock_env.num_envs = 2
    mock_robot = MagicMock()
    mock_obj = MagicMock()

    mock_robot.data.body_names = [
        "left_wrist_yaw_link",
        "left_hand_thumb_2_link",
        "left_hand_index_1_link",
        "left_hand_middle_1_link",
    ]
    # Env 0: all keypoints at object center -> score = 1.0
    # Env 1: keypoints far -> score near 0.0
    body_pos = torch.zeros(2, 4, 3)
    mock_robot.data.body_pos_w = wp.from_torch(body_pos)

    obj_pos = torch.tensor([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    mock_obj.data.root_pos_w = wp.from_torch(obj_pos)

    mock_env.scene = {"robot": mock_robot, "object": mock_obj}

    reward = pick_and_place_rewards.multi_keypoint_grasp_guidance(
        mock_env,
        std=0.08,
        object_cfg=SceneEntityCfg("object"),
        robot_cfg=SceneEntityCfg("robot"),
    )
    assert torch.allclose(reward[0], torch.tensor(1.0), atol=1e-4), f"Expected env 0 score 1.0, got {reward[0]}"
    assert reward[1] < 1e-4, f"Expected env 1 score near 0.0, got {reward[1]}"


def test_finger_grasp_enclosure():
    """Verify finger grasp enclosure score with curled fingers."""
    mock_env = MagicMock()
    mock_env.num_envs = 1
    mock_robot = MagicMock()
    mock_obj = MagicMock()

    mock_robot.data.body_names = ["ee_link"]
    mock_robot.data.body_pos_w = wp.from_torch(torch.zeros(1, 1, 3))
    mock_obj.data.root_pos_w = wp.from_torch(torch.zeros(1, 3))

    mock_robot.data.joint_names = [
        "left_hand_index_0_joint",
        "left_hand_index_1_joint",
        "left_hand_middle_0_joint",
        "left_hand_middle_1_joint",
        "left_hand_thumb_1_joint",
        "left_hand_thumb_2_joint",
    ]
    # Curled fingers: index/middle negative (-1.0), thumb positive (+0.7)
    curled_q = torch.tensor([[-1.0, -1.0, -1.0, -1.0, 0.7, 0.7]])
    mock_robot.data.joint_pos = wp.from_torch(curled_q)

    mock_env.scene = {"robot": mock_robot, "object": mock_obj}

    rew = pick_and_place_rewards.finger_grasp_enclosure(
        mock_env,
        ee_link_name="ee_link",
        object_cfg=SceneEntityCfg("object"),
        robot_cfg=SceneEntityCfg("robot"),
    )
    assert rew[0] > 0.9, f"Expected high grasp score for curled fingers, got {rew[0]}"
