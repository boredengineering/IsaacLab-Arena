# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the affordance-facing check (Pass 5) of the articulated-spec oracle."""

import math
import pathlib
import sys

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import verify_articulated_spec as oracle  # noqa: E402

MICROWAVE_NORMAL = [0.0, -1.0, 0.0]  # measured from Microwave039.usd
ROBOT = [-0.65, 0.0, 0.75]
MICROWAVE = [0.0, -0.05, 0.75]


def _yaw_quat(deg: float) -> list[float]:
    half = math.radians(deg) / 2.0
    return [0.0, 0.0, math.sin(half), math.cos(half)]


def test_quat_rotate_yaw():
    out = oracle.quat_rotate(_yaw_quat(90.0), [1.0, 0.0, 0.0])
    assert out == pytest.approx([0.0, 1.0, 0.0], abs=1e-6)


@pytest.mark.parametrize("yaw_deg, expected_ok", [(-90.0, True), (0.0, False), (90.0, False), (180.0, False)])
def test_microwave_facing_for_robot_on_minus_x(yaw_deg, expected_ok):
    ok, alignment, _, _, _ = oracle.check_affordance_facing(ROBOT, MICROWAVE, _yaw_quat(yaw_deg), MICROWAVE_NORMAL)
    assert ok == expected_ok, f"yaw={yaw_deg} alignment={alignment:.2f}"


def test_recommended_quat_fixes_defect():
    ok, _, _, _, rec = oracle.check_affordance_facing(ROBOT, MICROWAVE, _yaw_quat(0.0), MICROWAVE_NORMAL)
    assert not ok
    fixed_ok, alignment, _, _, _ = oracle.check_affordance_facing(ROBOT, MICROWAVE, rec, MICROWAVE_NORMAL)
    assert fixed_ok and alignment <= -0.70


def _spec(tmp_path, yaw_deg: float, use_relation: bool = False) -> str:
    """Build a spec; with use_relation the yaw is a rotate_around_solution relation on a placed object."""
    relations = []
    if use_relation:
        relations = [
            {"kind": "on", "subject": "microwave", "reference": "office_table", "params": {}},
            {
                "kind": "rotate_around_solution",
                "subject": "microwave",
                "params": {"yaw_rad": math.radians(yaw_deg)},
            },
        ]
    spec = {
        "embodiment": {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": ROBOT}}},
        "objects": [
            {
                "id": "microwave",
                "registry_name": "microwave",
                "params": {"initial_pose": {"position_xyz": MICROWAVE, "rotation_xyzw": _yaw_quat(yaw_deg)}},
            }
        ],
        "relations": relations,
        "task": {"composition": "sequential", "subtasks": []},
    }
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec))
    return str(path)


def test_oracle_flags_sideways_microwave(tmp_path):
    report = oracle.verify_spec(_spec(tmp_path, 0.0))
    assert report["passes"]["pass5_facing"] is False
    assert any(d["code"] == "TASK_AFFORDANCE_FACING_DEFECT" for d in report["defects"])


def test_oracle_accepts_facing_microwave(tmp_path):
    report = oracle.verify_spec(_spec(tmp_path, -90.0))
    assert report["passes"]["pass5_facing"] is True


def test_initial_pose_rotation_is_ignored_for_placed_objects(tmp_path):
    """A facing yaw in initial_pose does not count when the object is placed by an 'on' relation."""
    path = _spec(tmp_path, -90.0)
    data = yaml.safe_load(open(path))
    data["relations"] = [{"kind": "on", "subject": "microwave", "reference": "office_table", "params": {}}]
    with open(path, "w") as f:
        yaml.safe_dump(data, f)
    report = oracle.verify_spec(path)
    assert report["passes"]["pass5_facing"] is False


def test_rotate_around_solution_relation_makes_microwave_face_robot(tmp_path):
    report = oracle.verify_spec(_spec(tmp_path, -90.0, use_relation=True))
    assert report["passes"]["pass5_facing"] is True


def test_check_2d_footprint_overlap_separated():
    ok, clearance, _ = oracle.check_2d_footprint_overlap(
        pos_a=(0.0, 0.0),
        yaw_a=0.0,
        half_extents_a=(0.2, 0.2),
        pos_b=(1.0, 0.0),
        yaw_b=0.0,
        half_extents_b=(0.2, 0.2),
        margin=0.05,
    )
    assert ok is True
    assert clearance == pytest.approx(0.55, abs=1e-4)


def test_check_2d_footprint_overlap_overlapping():
    ok, clearance, _ = oracle.check_2d_footprint_overlap(
        pos_a=(0.0, 0.0),
        yaw_a=0.0,
        half_extents_a=(0.2, 0.2),
        pos_b=(0.3, 0.0),
        yaw_b=0.0,
        half_extents_b=(0.2, 0.2),
        margin=0.05,
    )
    assert ok is False
    assert clearance < 0.0


def test_check_2d_footprint_overlap_rotated():
    # Box A is 0.6m wide (half_x=0.3) and 0.2m deep (half_y=0.1)
    # Box B is at x=0.22, y=0.0 with half-extents 0.05
    # When Box A is unrotated (yaw=0), its half-extent along X is 0.30, so with margin 0.05 it overlaps B.
    ok_unrotated, cl_unrot, _ = oracle.check_2d_footprint_overlap(
        pos_a=(0.0, 0.0),
        yaw_a=0.0,
        half_extents_a=(0.3, 0.1),
        pos_b=(0.22, 0.0),
        yaw_b=0.0,
        half_extents_b=(0.05, 0.05),
        margin=0.05,
    )
    assert ok_unrotated is False

    # When Box A is rotated 90 degrees (pi/2), its half-extent along X becomes 0.10, so it clears B (0.22 > 0.10 + 0.05 + 0.05 = 0.20)
    ok_rotated, cl_rot, _ = oracle.check_2d_footprint_overlap(
        pos_a=(0.0, 0.0),
        yaw_a=math.pi / 2.0,
        half_extents_a=(0.3, 0.1),
        pos_b=(0.22, 0.0),
        yaw_b=0.0,
        half_extents_b=(0.05, 0.05),
        margin=0.05,
    )
    assert ok_rotated is True
    assert cl_rot > 0.0


def test_oracle_flags_overlapping_footprint(tmp_path):
    spec = {
        "embodiment": {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": ROBOT}}},
        "objects": [
            {
                "id": "microwave",
                "registry_name": "microwave",
                "params": {"initial_pose": {"position_xyz": [0.0, -0.05, 0.75]}},
            },
            {
                "id": "tomato_soup_can",
                "registry_name": "tomato_soup_can_ycb_robolab",
                "params": {"initial_pose": {"position_xyz": [-0.15, 0.10, 0.75]}},
            },
        ],
        "relations": [
            {"kind": "on", "subject": "microwave", "reference": "office_table", "params": {}},
            {"kind": "on", "subject": "tomato_soup_can", "reference": "office_table", "params": {}},
            {"kind": "rotate_around_solution", "subject": "microwave", "params": {"yaw_rad": -1.5708}},
        ],
        "task": {
            "composition": "sequential",
            "subtasks": [
                {"kind": "OpenDoorTask", "params": {"openness_threshold": 0.8}},
                {"kind": "PickAndPlaceTask", "params": {}},
            ],
        },
    }
    path = tmp_path / "overlap_spec.yaml"
    path.write_text(yaml.safe_dump(spec))

    report = oracle.verify_spec(str(path))
    assert report["passes"]["pass3_footprint_clearance"] is False
    assert any(d["code"] == "FOOTPRINT_OVERLAP_COLLISION" for d in report["defects"])


def test_oracle_accepts_separated_footprints(tmp_path):
    spec = {
        "embodiment": {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": ROBOT}}},
        "objects": [
            {
                "id": "microwave",
                "registry_name": "microwave",
                "params": {"initial_pose": {"position_xyz": [0.25, -0.175, 0.75]}},
            },
            {
                "id": "tomato_soup_can",
                "registry_name": "tomato_soup_can_ycb_robolab",
                "params": {"initial_pose": {"position_xyz": [-0.45, 0.30, 0.75]}},
            },
        ],
        "relations": [
            {"kind": "on", "subject": "microwave", "reference": "office_table", "params": {}},
            {"kind": "on", "subject": "tomato_soup_can", "reference": "office_table", "params": {}},
            {"kind": "rotate_around_solution", "subject": "microwave", "params": {"yaw_rad": -1.5708}},
        ],
        "task": {
            "composition": "sequential",
            "subtasks": [
                {"kind": "OpenDoorTask", "params": {"openness_threshold": 0.8}},
                {"kind": "PickAndPlaceTask", "params": {}},
            ],
        },
    }
    path = tmp_path / "separated_spec.yaml"
    path.write_text(yaml.safe_dump(spec))

    report = oracle.verify_spec(str(path))
    assert report["passes"]["pass3_footprint_clearance"] is True


def test_oracle_flags_invalid_open_threshold_param(tmp_path):
    spec = {
        "embodiment": {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": ROBOT}}},
        "objects": [
            {
                "id": "microwave",
                "registry_name": "microwave",
                "params": {"initial_pose": {"position_xyz": [0.25, -0.175, 0.75]}},
            },
            {
                "id": "tomato_soup_can",
                "registry_name": "tomato_soup_can_ycb_robolab",
                "params": {"initial_pose": {"position_xyz": [-0.45, 0.30, 0.75]}},
            },
        ],
        "relations": [
            {"kind": "on", "subject": "microwave", "reference": "office_table", "params": {}},
            {"kind": "on", "subject": "tomato_soup_can", "reference": "office_table", "params": {}},
            {"kind": "rotate_around_solution", "subject": "microwave", "params": {"yaw_rad": -1.5708}},
        ],
        "task": {
            "composition": "sequential",
            "subtasks": [
                {"kind": "OpenDoorTask", "params": {"open_threshold": 0.8}},
                {"kind": "PickAndPlaceTask", "params": {}},
            ],
        },
    }
    path = tmp_path / "invalid_param_spec.yaml"
    path.write_text(yaml.safe_dump(spec))

    report = oracle.verify_spec(str(path))
    assert report["passes"]["pass4_handoff"] is False
    assert any(d["code"] == "TASK_PARAM_NAME_INVALID" for d in report["defects"])


def test_check_fixture_flags_pedestal_collision_and_orientation():
    emb = {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": [-0.65, 0.0, 0.75]}}}
    bg = {"id": "office_table", "registry_name": "office_table_background", "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, 0.0, 1.0]}}}
    rr = [{"source_id": "microwave", "delta_z": {"nominal": 0.531}}]
    ok, defects, diags = oracle.check_fixture_standoff_and_elevation(emb, bg, rr)
    assert ok is False
    codes = [d["code"] for d in defects]
    assert "DEFECT_ROBOT_FIXTURE_COLLISION" in codes
    assert "DEFECT_FIXTURE_ORIENTATION_MISALIGNED" in codes


def test_check_fixture_standoff_and_elevation_rotated_clean():
    emb = {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": [-0.80, 0.0, 0.75]}}}
    bg = {
        "id": "office_table",
        "registry_name": "office_table_background",
        "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, -0.7071068, 0.7071068]}},
    }
    rr = [{"source_id": "microwave", "delta_z": {"nominal": 0.531}}]
    ok, defects, diags = oracle.check_fixture_standoff_and_elevation(emb, bg, rr)
    assert ok is True
    assert len(defects) == 0


def test_check_fixture_flags_floating_table():
    emb = {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": [-0.80, 0.0, 0.75]}}}
    bg = {
        "id": "office_table",
        "registry_name": "office_table_background",
        "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.219], "rotation_xyzw": [0.0, 0.0, -0.7071068, 0.7071068]}},
    }
    rr = [{"source_id": "microwave", "delta_z": {"nominal": 0.75}}]
    ok, defects, diags = oracle.check_fixture_standoff_and_elevation(emb, bg, rr)
    assert ok is False
    codes = [d["code"] for d in defects]
    assert "DEFECT_FIXTURE_NOT_GROUNDED" in codes


def test_check_fixture_flags_manipuland_elevation_mismatch():
    emb = {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": [-0.80, 0.0, 0.75]}}}
    bg = {
        "id": "office_table",
        "registry_name": "office_table_background",
        "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, -0.7071068, 0.7071068]}},
    }
    rr = [{"source_id": "microwave", "delta_z": {"nominal": 0.75}}]
    ok, defects, diags = oracle.check_fixture_standoff_and_elevation(emb, bg, rr)
    assert ok is False
    codes = [d["code"] for d in defects]
    assert "DEFECT_MANIPULAND_ELEVATION_MISMATCH" in codes


def test_check_fixture_standoff_too_close():
    emb = {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": [-0.30, 0.0, 0.75]}}}
    bg = {
        "id": "office_table",
        "registry_name": "office_table_background",
        "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, -0.7071068, 0.7071068]}},
    }
    ok, defects, _ = oracle.check_fixture_standoff_and_elevation(emb, bg)
    assert ok is False
    codes = [d["code"] for d in defects]
    assert "DEFECT_STANDOFF_DISTANCE_TOO_CLOSE" in codes or "DEFECT_ROBOT_FIXTURE_COLLISION" in codes


def test_check_fixture_standoff_too_far():
    emb = {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": [-1.50, 0.0, 0.75]}}}
    bg = {
        "id": "office_table",
        "registry_name": "office_table_background",
        "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, -0.7071068, 0.7071068]}},
    }
    ok, defects, _ = oracle.check_fixture_standoff_and_elevation(emb, bg)
    assert ok is False
    assert any(d["code"] == "DEFECT_STANDOFF_DISTANCE_TOO_FAR" for d in defects)


def test_oracle_flags_unrotated_table_collision(tmp_path):
    spec = {
        "embodiment": {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": [-0.65, 0.0, 0.75]}}},
        "background": {
            "id": "office_table",
            "registry_name": "office_table_background",
            "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, 0.0, 1.0]}},
        },
        "objects": [
            {
                "id": "microwave",
                "registry_name": "microwave",
                "params": {"initial_pose": {"position_xyz": [0.25, -0.175, 0.531]}},
            },
            {
                "id": "tomato_soup_can",
                "registry_name": "tomato_soup_can_ycb_robolab",
                "params": {"initial_pose": {"position_xyz": [-0.45, 0.30, 0.531]}},
            },
        ],
        "relations": [
            {"kind": "on", "subject": "microwave", "reference": "office_table", "params": {}},
            {"kind": "on", "subject": "tomato_soup_can", "reference": "office_table", "params": {}},
            {"kind": "rotate_around_solution", "subject": "microwave", "params": {"yaw_rad": -1.5708}},
        ],
        "reified_relations": [
            {"source_id": "microwave", "delta_z": {"nominal": 0.531}},
            {"source_id": "tomato_soup_can", "delta_z": {"nominal": 0.531}},
        ],
        "task": {
            "composition": "sequential",
            "subtasks": [
                {"kind": "OpenDoorTask", "params": {"openness_threshold": 0.75, "openable_object": "microwave"}},
                {"kind": "PickAndPlaceTask", "params": {"pick_up_object": "tomato_soup_can", "destination_location": "microwave", "background_scene": "office_table"}},
            ],
        },
    }
    path = tmp_path / "unrotated_spec.yaml"
    path.write_text(yaml.safe_dump(spec))

    report = oracle.verify_spec(str(path))
    assert report["passes"]["pass6_standoff_elevation"] is False
    codes = [d["code"] for d in report["defects"]]
    assert "DEFECT_ROBOT_FIXTURE_COLLISION" in codes


def test_oracle_flags_floating_table(tmp_path):
    spec = {
        "embodiment": {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": [-0.80, 0.0, 0.75]}}},
        "background": {
            "id": "office_table",
            "registry_name": "office_table_background",
            "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.219], "rotation_xyzw": [0.0, 0.0, -0.7071068, 0.7071068]}},
        },
        "objects": [
            {
                "id": "microwave",
                "registry_name": "microwave",
                "params": {"initial_pose": {"position_xyz": [-0.20, -0.35, 0.75]}},
            },
            {
                "id": "tomato_soup_can",
                "registry_name": "tomato_soup_can_ycb_robolab",
                "params": {"initial_pose": {"position_xyz": [-0.20, 0.25, 0.75]}},
            },
        ],
        "relations": [
            {"kind": "on", "subject": "microwave", "reference": "office_table", "params": {}},
            {"kind": "on", "subject": "tomato_soup_can", "reference": "office_table", "params": {}},
            {"kind": "rotate_around_solution", "subject": "microwave", "params": {"yaw_rad": -1.5708}},
        ],
        "reified_relations": [
            {"source_id": "microwave", "delta_z": {"nominal": 0.75}},
            {"source_id": "tomato_soup_can", "delta_z": {"nominal": 0.75}},
        ],
        "task": {
            "composition": "sequential",
            "subtasks": [
                {"kind": "OpenDoorTask", "params": {"openness_threshold": 0.75, "openable_object": "microwave"}},
                {"kind": "PickAndPlaceTask", "params": {"pick_up_object": "tomato_soup_can", "destination_location": "microwave", "background_scene": "office_table"}},
            ],
        },
    }
    path = tmp_path / "floating_spec.yaml"
    path.write_text(yaml.safe_dump(spec))

    report = oracle.verify_spec(str(path))
    assert report["passes"]["pass6_standoff_elevation"] is False
    assert any(d["code"] == "DEFECT_FIXTURE_NOT_GROUNDED" for d in report["defects"])


def test_oracle_accepts_grounded_spec(tmp_path):
    spec = {
        "embodiment": {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": [-0.80, 0.0, 0.75]}}},
        "background": {
            "id": "office_table",
            "registry_name": "office_table_background",
            "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, -0.7071068, 0.7071068]}},
        },
        "objects": [
            {
                "id": "microwave",
                "registry_name": "microwave",
                "params": {"initial_pose": {"position_xyz": [-0.20, -0.35, 0.531]}},
            },
            {
                "id": "tomato_soup_can",
                "registry_name": "tomato_soup_can_ycb_robolab",
                "params": {"initial_pose": {"position_xyz": [-0.20, 0.25, 0.531]}},
            },
        ],
        "relations": [
            {"kind": "on", "subject": "microwave", "reference": "office_table", "params": {"surface_anchor": "table_top", "surface_sector": "front_right"}},
            {"kind": "on", "subject": "tomato_soup_can", "reference": "office_table", "params": {"surface_anchor": "table_top", "surface_sector": "front_left"}},
            {"kind": "rotate_around_solution", "subject": "microwave", "params": {"yaw_rad": -1.5708}},
        ],
        "reified_relations": [
            {"source_id": "microwave", "delta_z": {"nominal": 0.531}},
            {"source_id": "tomato_soup_can", "delta_z": {"nominal": 0.531}},
        ],
        "task": {
            "composition": "sequential",
            "subtasks": [
                {"kind": "OpenDoorTask", "params": {"openness_threshold": 0.75, "openable_object": "microwave"}},
                {"kind": "PickAndPlaceTask", "params": {"pick_up_object": "tomato_soup_can", "destination_location": "microwave", "background_scene": "office_table"}},
            ],
        },
    }
    path = tmp_path / "grounded_spec.yaml"
    path.write_text(yaml.safe_dump(spec))

    report = oracle.verify_spec(str(path))
    assert report["passes"]["pass6_standoff_elevation"] is True
    assert report["conforms"] is True


def test_oracle_accepts_type_b_intrinsic_prismatic_cabinet_d2a(tmp_path):
    """D2-A: Type B intrinsic prismatic drawer in kitchen_base_cabinet with object_references."""
    spec = {
        "embodiment": {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": [-0.95, 0.0, 0.75]}}},
        "background": {
            "id": "kitchen_base_cabinet",
            "registry_name": "kitchen_base_cabinet",
            "params": {"initial_pose": {"position_xyz": [0.10, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, -0.7071068, 0.7071068]}},
        },
        "objects": [
            {
                "id": "sugar_box",
                "registry_name": "sugar_box",
                "params": {"initial_pose": {"position_xyz": [0.10, -0.15, 0.65]}},
            }
        ],
        "object_references": [
            {
                "id": "top_drawer",
                "parent_id": "kitchen_base_cabinet",
                "prim_path": "/Geometry/Carcass/Drawer_1",
                "object_type": "articulation",
                "params": {"openable_joint_name": "drawer_1"},
            }
        ],
        "relations": [
            {"kind": "is_anchor", "subject": "top_drawer", "params": {}},
        ],
        "reified_relations": [
            {"source_id": "sugar_box", "target_id": "top_drawer", "delta_x": {"nominal": 0.10}, "delta_y": {"nominal": -0.15}, "delta_z": {"nominal": 0.65}},
        ],
        "task": {
            "composition": "sequential",
            "subtasks": [
                {"kind": "OpenDrawerTask", "params": {"openness_threshold": 0.80, "openable_object": "top_drawer"}},
                {"kind": "PickAndPlaceTask", "params": {"pick_up_object": "sugar_box", "destination_location": "kitchen_base_cabinet", "background_scene": "kitchen_base_cabinet"}},
            ],
        },
    }
    path = tmp_path / "d2a_spec.yaml"
    path.write_text(yaml.safe_dump(spec))

    report = oracle.verify_spec(str(path))
    assert report["passes"]["pass2_kinematics"] is True
    assert report["passes"]["pass3_swept_sector"] is True
    assert report["passes"]["pass4_handoff"] is True
    assert report["passes"]["pass6_standoff_elevation"] is True
    assert report["conforms"] is True


def test_oracle_flags_intrinsic_articulation_conflation(tmp_path):
    """D2-A / D2-B SHACL Rule 8: Intrinsic sub-prim must not have 'kind: on' relation."""
    spec = {
        "embodiment": {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": [-0.95, 0.0, 0.75]}}},
        "background": {
            "id": "kitchen_base_cabinet",
            "registry_name": "kitchen_base_cabinet",
            "params": {"initial_pose": {"position_xyz": [0.10, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, -0.7071068, 0.7071068]}},
        },
        "objects": [
            {"id": "sugar_box", "registry_name": "sugar_box", "params": {}},
        ],
        "object_references": [
            {
                "id": "top_drawer",
                "parent_id": "kitchen_base_cabinet",
                "prim_path": "/Geometry/Carcass/Drawer_1",
                "object_type": "articulation",
                "params": {"openable_joint_name": "drawer_1"},
            }
        ],
        "relations": [
            {"kind": "on", "subject": "top_drawer", "reference": "kitchen_base_cabinet", "params": {}},
        ],
        "task": {
            "composition": "sequential",
            "subtasks": [
                {"kind": "OpenDrawerTask", "params": {"openness_threshold": 0.80, "openable_object": "top_drawer"}},
                {"kind": "PickAndPlaceTask", "params": {}},
            ],
        },
    }
    path = tmp_path / "conflation_spec.yaml"
    path.write_text(yaml.safe_dump(spec))

    report = oracle.verify_spec(str(path))
    assert report["passes"]["pass2_kinematics"] is False
    assert any(d["code"] == "DEFECT_INTRINSIC_ARTICULATION_CONFLATION" for d in report["defects"])


def test_oracle_accepts_reversible_3_stage_counter_d2b(tmp_path):
    """D2-B: 3-stage reversible OpenDrawerTask -> PickAndPlaceTask -> CloseDrawerTask."""
    spec = {
        "embodiment": {"registry_name": "droid_abs_joint_pos", "params": {"initial_pose": {"position_xyz": [-0.95, 0.0, 0.75]}}},
        "background": {
            "id": "fixture_counter_a01",
            "registry_name": "fixture_counter_a01",
            "params": {"initial_pose": {"position_xyz": [0.10, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, 1.0, 0.0]}},
        },
        "objects": [
            {
                "id": "cracker_box",
                "registry_name": "cracker_box",
                "params": {"initial_pose": {"position_xyz": [0.10, -0.45, 0.90]}},
            }
        ],
        "object_references": [
            {
                "id": "storage_drawer",
                "parent_id": "fixture_counter_a01",
                "prim_path": "/Geometry/shelf_02_obj_00/shelf_02_mesh_00",
                "object_type": "articulation",
                "params": {"openable_joint_name": "joint_shelf_02_joint_00"},
            }
        ],
        "relations": [
            {"kind": "is_anchor", "subject": "storage_drawer", "params": {}},
            {"kind": "on", "subject": "cracker_box", "reference": "fixture_counter_a01", "params": {"surface_sector": "front_left"}},
        ],
        "reified_relations": [
            {"source_id": "cracker_box", "target_id": "fixture_counter_a01", "delta_x": {"nominal": 0.10}, "delta_y": {"nominal": -0.45}, "delta_z": {"nominal": 0.90}},
        ],
        "task": {
            "composition": "sequential",
            "subtasks": [
                {"kind": "OpenDrawerTask", "params": {"openness_threshold": 0.80, "openable_object": "storage_drawer"}},
                {"kind": "PickAndPlaceTask", "params": {"pick_up_object": "cracker_box", "destination_location": "storage_drawer", "background_scene": "fixture_counter_a01"}},
                {"kind": "CloseDrawerTask", "params": {"closedness_threshold": 0.10, "openable_object": "storage_drawer"}},
            ],
        },
    }
    path = tmp_path / "d2b_spec.yaml"
    path.write_text(yaml.safe_dump(spec))

    report = oracle.verify_spec(str(path))
    assert report["conforms"] is True, f"Defects: {report['defects']}"




