# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import math
import numpy as np
import pytest

from isaaclab_arena.relations.placement_asset import PlaceableAsset
from isaaclab_arena.utils.cameras import compute_robot_relative_viewer_cfg
from isaaclab_arena.utils.pose import Pose


class DummyAsset(PlaceableAsset):
    def __init__(self, name: str):
        super().__init__(name=name)

    def get_bounding_box(self):
        return None

    def get_collision_mesh(self):
        return None


def test_compute_robot_relative_viewer_cfg_facing_positive_x():
    robot = DummyAsset("robot")
    robot.set_initial_pose(Pose(position_xyz=(0.0, 0.0, 0.0), rotation_xyzw=(0.0, 0.0, 0.0, 1.0)))

    target = DummyAsset("target")
    target.set_initial_pose(Pose(position_xyz=(1.0, 0.0, 0.75), rotation_xyzw=(0.0, 0.0, 0.0, 1.0)))

    viewer_cfg = compute_robot_relative_viewer_cfg(
        embodiment=robot,
        lookat_target=target,
        standoff_back=1.10,
        standoff_side=0.65,
        elevation=0.85,
    )

    assert pytest.approx(viewer_cfg.eye[0], 0.01) == -1.10
    assert pytest.approx(viewer_cfg.eye[1], 0.01) == 0.65
    assert pytest.approx(viewer_cfg.eye[2], 0.01) == 1.60

    assert pytest.approx(viewer_cfg.lookat[0], 0.01) == 1.0
    assert pytest.approx(viewer_cfg.lookat[1], 0.01) == 0.0
    assert pytest.approx(viewer_cfg.lookat[2], 0.01) == 0.75


def test_compute_robot_relative_viewer_cfg_rotated_heading():
    robot = DummyAsset("robot")
    yaw = math.pi / 2.0
    robot.set_initial_pose(
        Pose(position_xyz=(0.0, 0.0, 0.0), rotation_xyzw=(0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)))
    )

    viewer_cfg = compute_robot_relative_viewer_cfg(
        embodiment=robot,
        lookat_target=None,
        standoff_back=1.0,
        standoff_side=0.5,
        elevation=0.8,
    )

    assert pytest.approx(viewer_cfg.eye[0], 0.01) == -0.5
    assert pytest.approx(viewer_cfg.eye[1], 0.01) == -1.0
    assert pytest.approx(viewer_cfg.eye[2], 0.01) == 1.55
