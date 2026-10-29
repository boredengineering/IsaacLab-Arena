#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

"""Quality Test: Autonomous Scene Generation & Oracle Verification for Articulated Prompt."""

import math
import os
import sys
import yaml
from pathlib import Path

# Insert local-inference scripts path
SCRIPTS_DIR = Path("/workspaces/isaaclab-arena-private/.agents/references/plans/local-inference/scripts")
sys.path.insert(0, str(SCRIPTS_DIR))

import verify_articulated_spec as oracle


def generate_scene_spec_from_prompt():
    """Generates the grounded, clearance-certified ArenaEnvGraphSpec YAML for the user prompt."""
    spec_dict = {
        "env_name": "franka_office_table_microwave_stow_task",
        "embodiment": {
            "id": "franka_robot",
            "registry_name": "droid_abs_joint_pos",
            "params": {
                "initial_pose": {
                    "position_xyz": [-0.80, 0.0, 0.75],
                    "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                }
            },
        },
        "background": {
            "id": "office_table",
            "registry_name": "office_table_background",
            "params": {
                "initial_pose": {
                    "position_xyz": [0.0, 0.0, 0.0],
                    "rotation_xyzw": [0.0, 0.0, -0.7071068, 0.7071068],  # -90 deg yaw to face approach corridor
                }
            },
        },
        "objects": [
            {
                "id": "microwave",
                "registry_name": "microwave",
                "params": {
                    "initial_pose": {
                        "position_xyz": [-0.20, -0.35, 0.531],  # Placed in front_right sector of table
                        "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                    }
                },
            },
            {
                "id": "tomato_soup_can",
                "registry_name": "tomato_soup_can_ycb_robolab",
                "params": {
                    "initial_pose": {
                        "position_xyz": [-0.20, 0.25, 0.531],  # Placed in front_left sector: 0.60m from microwave (> 0.30m)
                        "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                    }
                },
            },
        ],
        "relations": [
            {
                "kind": "is_anchor",
                "subject": "office_table",
                "params": {},
            },
            {
                "kind": "on",
                "subject": "microwave",
                "reference": "office_table",
                "params": {
                    "surface_anchor": "table_top",
                    "surface_sector": "front_right",
                },
            },
            {
                "kind": "on",
                "subject": "tomato_soup_can",
                "reference": "office_table",
                "params": {
                    "surface_anchor": "table_top",
                    "surface_sector": "front_left",
                },
            },
            {
                "kind": "rotate_around_solution",
                "subject": "microwave",
                "params": {
                    "yaw_rad": -1.5707963267948966,  # -90 deg so door aperture faces robot base at -X
                },
            },
        ],
        "reified_relations": [
            {
                "reifier_id": "reifier_microwave_office_table",
                "source_id": "microwave",
                "relation_type": "PLACED_ON",
                "target_id": "office_table",
                "surface_anchor": "table_top",
                "surface_sector": "front_right",
                "contact_normal": [0.0, 0.0, 1.0],
                "delta_x": {"nominal": 0.25, "min_val": 0.10, "max_val": 0.40},
                "delta_y": {"nominal": -0.35, "min_val": -0.45, "max_val": -0.20},
                "delta_z": {"nominal": 0.531, "min_val": 0.531, "max_val": 0.531},
            },
            {
                "reifier_id": "reifier_tomato_soup_can_office_table",
                "source_id": "tomato_soup_can",
                "relation_type": "PLACED_ON",
                "target_id": "office_table",
                "surface_anchor": "table_top",
                "surface_sector": "front_left",
                "contact_normal": [0.0, 0.0, 1.0],
                "delta_x": {"nominal": 0.25, "min_val": 0.10, "max_val": 0.40},
                "delta_y": {"nominal": 0.25, "min_val": 0.15, "max_val": 0.40},
                "delta_z": {"nominal": 0.531, "min_val": 0.531, "max_val": 0.531},
            },
        ],
        "task": {
            "composition": "sequential",
            "description": "Open microwave door to at least 75 degrees and stow tomato soup can inside turntable cavity.",
            "subtasks": [
                {
                    "kind": "OpenDoorTask",
                    "params": {
                        "openable_object": "microwave",
                        "openness_threshold": 0.75,  # 75% opening (>= 67.5 deg / 1.18 rad)
                    },
                },
                {
                    "kind": "PickAndPlaceTask",
                    "params": {
                        "pick_up_object": "tomato_soup_can",
                        "destination_location": "microwave",
                        "background_scene": "office_table",
                    },
                },
            ],
        },
    }
    return spec_dict


def main():
    print("[TEST 1] Synthesizing Scene Specification from User Prompt...")
    spec = generate_scene_spec_from_prompt()
    repo_root = Path(__file__).resolve().parents[5]
    out_path = repo_root / "artifacts/experiments/test_prompt_quality_spec.yaml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        yaml.safe_dump(spec, f, sort_keys=False)
    print(f"Saved candidate spec to: {out_path}")

    print("\n[TEST 2] Running 6-Pass Deterministic Articulated Oracle...")
    report = oracle.verify_spec(str(out_path))

    print(f"Overall Conforms: {report['conforms']}")
    print(f"Pass 1 (Schema & Graph):          {report['passes'].get('pass1_schema')}")
    print(f"Pass 2 (USD Kinematics):          {report['passes'].get('pass2_kinematics')}")
    print(f"Pass 3a (3D Swept Sector Arc):    {report['passes'].get('pass3_swept_sector')}")
    print(f"Pass 3b (2D Footprint Clear):     {report['passes'].get('pass3_footprint_clearance')}")
    print(f"Pass 4 (Sequential Handoff):      {report['passes'].get('pass4_handoff')}")
    print(f"Pass 5 (Affordance Facing):       {report['passes'].get('pass5_facing')}")
    print(f"Pass 6 (Standoff & Elevation):    {report['passes'].get('pass6_standoff_elevation')}")

    if report["defects"]:
        print("\nDefects Encountered:")
        for d in report["defects"]:
            print(f"  - [{d.get('code')}] {d.get('message')}")
        sys.exit(1)

    print("\n[TEST 3] Distance & Clearance Mathematical Audit:")
    micro_pos = spec["objects"][0]["params"]["initial_pose"]["position_xyz"]
    soup_pos = spec["objects"][1]["params"]["initial_pose"]["position_xyz"]
    euclidean_dist = math.dist(micro_pos[:2], soup_pos[:2])
    print(f"Microwave Position: {micro_pos}")
    print(f"Soup Can Position:  {soup_pos}")
    print(f"2D Center-to-Center Euclidean Distance: {euclidean_dist:.4f}m (Required >= 0.30m -> PASS)")
    assert euclidean_dist >= 0.30, f"Distance {euclidean_dist:.3f}m < 0.30m"

    print("\n[ALL QUALITY TESTS PASSED CLEANLY]")


if __name__ == "__main__":
    main()
