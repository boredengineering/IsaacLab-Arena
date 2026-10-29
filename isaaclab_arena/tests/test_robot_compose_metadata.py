# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""CPU regression for the coordinate system of composed robot USDs."""


def test_composed_robot_declares_z_up_and_meters(tmp_path, monkeypatch):
    from pxr import Usd, UsdGeom

    from isaaclab_arena.embodiments import robot_on_stand_utils as compose

    robot_path = tmp_path / "robot.usda"
    source = Usd.Stage.CreateNew(str(robot_path))
    root = UsdGeom.Xform.Define(source, "/Robot").GetPrim()
    source.SetDefaultPrim(root)
    source.GetRootLayer().Save()
    monkeypatch.setattr(compose, "retrieve_file_path", lambda path: path)
    monkeypatch.setattr(compose, "get_arena_asset_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(compose, "_mount_stand_normalized", lambda *args: None)
    robot = compose.RobotPrimSpec(str(robot_path), "/Robot", "base", "stand")
    stand = compose.StandPrimSpec(str(robot_path), "/Robot", "payload", (0, 0, 0), (1, 1), 1)
    path = compose.compose_on_stand_usd(robot, stand, stand_height_m=1, output_basename="metadata-test")
    result = Usd.Stage.Open(path)
    assert result.HasAuthoredMetadata("upAxis")
    assert UsdGeom.GetStageUpAxis(result) == UsdGeom.Tokens.z
    assert result.HasAuthoredMetadata("metersPerUnit")
    assert UsdGeom.GetStageMetersPerUnit(result) == 1.0
