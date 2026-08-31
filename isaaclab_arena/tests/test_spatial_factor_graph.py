# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import math
import pytest
import torch

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
    relax_spec_spatial_factor_graph,
    validate_kinematic_reachability,
    validate_spatial_geometry,
    validate_support_containment,
)
from isaaclab_arena.relations.spatial_factor_graph import SpatialFactorGraph


class TestSpatialFactorGraph:
    def test_spatial_factor_graph_relaxes_tabletop_scene(self):
        """Test continuous LBP relaxation places mustard and bin on table within reach of robot."""
        fg = SpatialFactorGraph()
        # Fixed table anchor at origin
        fg.add_variable("maple_table", [0.0, 0.0, 0.0, 0.0], is_fixed=True)
        # Robot initially far away
        fg.add_variable("droid", [-1.2, 0.0, 0.0, 0.0], is_fixed=False)
        # Mustard initially overlapping with bin
        fg.add_variable("mustard_bottle", [0.0, 0.0, 0.75, 0.0], is_fixed=False)
        fg.add_variable("grey_bin", [0.05, 0.0, 0.75, 0.0], is_fixed=False)

        # Constraints
        # Table surface: [-0.45, 0.45, -0.30, 0.30, 0.75]
        fg.add_support_factor("mustard_bottle", "maple_table", [-0.45, 0.45, -0.30, 0.30, 0.75])
        fg.add_support_factor("grey_bin", "maple_table", [-0.45, 0.45, -0.30, 0.30, 0.75])
        fg.add_clearance_factor("mustard_bottle", "grey_bin", min_distance=0.25)
        fg.add_reachability_factor("droid", "mustard_bottle", target_distance=0.60, tolerance=0.15)
        fg.add_reachability_factor("droid", "grey_bin", target_distance=0.60, tolerance=0.15)
        fg.add_clearance_factor("droid", "maple_table", min_distance=0.45)
        fg.add_ground_factor("droid", floor_z=0.0)

        result = fg.relax(max_iters=150)

        assert result.converged
        assert result.total_energy < 0.1
        poses = result.poses

        # Verify robot moved within reach
        d_mustard = math.hypot(poses["droid"][0] - poses["mustard_bottle"][0], poses["droid"][1] - poses["mustard_bottle"][1])
        d_bin = math.hypot(poses["droid"][0] - poses["grey_bin"][0], poses["droid"][1] - poses["grey_bin"][1])
        assert 0.40 <= d_mustard <= 0.80
        assert 0.40 <= d_bin <= 0.80

        # Verify separation between mustard and bin
        d_sep = math.hypot(poses["mustard_bottle"][0] - poses["grey_bin"][0], poses["mustard_bottle"][1] - poses["grey_bin"][1])
        assert d_sep >= 0.20

        # Verify both are on table surface (X in [-0.40, 0.40], Y in [-0.25, 0.25])
        assert -0.42 <= poses["mustard_bottle"][0] <= 0.42
        assert -0.27 <= poses["mustard_bottle"][1] <= 0.27
        assert -0.42 <= poses["grey_bin"][0] <= 0.42
        assert -0.27 <= poses["grey_bin"][1] <= 0.27

    def test_relax_spec_places_objects_in_front_sectors(self):
        """Test spec relaxation with semantic sectors places objects in the front working sector near the robot."""
        spec_dict = {
            "env_name": "test_sectors",
            "embodiment": {
                "id": "droid",
                "registry_name": "droid_abs_joint_pos",
                "params": {"initial_pose": {"position_xyz": [-0.55, 0.0, 0.0]}},
            },
            "background": {
                "id": "maple_table",
                "registry_name": "maple_table_robolab",
                "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0]}},
            },
            "objects": [
                {
                    "id": "rubiks_cube",
                    "registry_name": "rubiks_cube_hot3d_robolab",
                    "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.75]}},
                },
                {
                    "id": "bin_b04",
                    "registry_name": "bin_b04_vomp_robolab",
                    "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.75]}},
                },
            ],
            "relations": [
                {"kind": "is_anchor", "subject": "maple_table", "params": {}},
                {
                    "kind": "on",
                    "subject": "rubiks_cube",
                    "reference": "maple_table",
                    "params": {"surface_anchor": "table_top", "surface_sector": "front_center"},
                },
                {
                    "kind": "on",
                    "subject": "bin_b04",
                    "reference": "maple_table",
                    "params": {"surface_anchor": "table_top", "surface_sector": "front_left"},
                },
            ],
            "task": {
                "composition": "atomic",
                "description": "Place rubiks cube into bin",
                "subtasks": [
                    {
                        "kind": "PickAndPlaceTask",
                        "params": {
                            "pick_up_object": "rubiks_cube",
                            "destination_location": "bin_b04",
                            "background_scene": "maple_table",
                        },
                    }
                ],
            },
        }

        spec = ArenaEnvGraphSpec.from_dict(spec_dict)
        relaxed_spec, diags = relax_spec_spatial_factor_graph(spec)

        cube_pos = relaxed_spec.objects[0].params["initial_pose"]["position_xyz"]
        bin_pos = relaxed_spec.objects[1].params["initial_pose"]["position_xyz"]

        # Assert both objects are relaxed into the robot-facing front half of the table (X in [-0.35, -0.05])
        assert -0.35 <= cube_pos[0] <= -0.05
        assert -0.35 <= bin_pos[0] <= -0.05

        # Assert bin is to the left (Y > 0.05) and cube is centered (Y around 0.0)
        assert bin_pos[1] > 0.05
        assert abs(cube_pos[1]) < 0.20


class TestSpatialGeometricOracle:
    def test_geometric_oracle_catches_overhang_and_unreachable_objects(self):
        """Test oracle flags overhang and unreachable distance violations."""
        spec_dict = {
            "env_name": "test_overhang",
            "embodiment": {
                "id": "droid",
                "registry_name": "droid_abs_joint_pos",
                "params": {"initial_pose": {"position_xyz": [-0.55, 0.0, 0.0]}},
            },
            "background": {
                "id": "maple_table",
                "registry_name": "maple_table_robolab",
                "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0]}},
            },
            "objects": [
                {
                    "id": "mustard_bottle",
                    "registry_name": "mustard_bottle_hot3d_robolab",
                    "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.75]}},
                },
                {
                    "id": "grey_bin",
                    "registry_name": "grey_bin_robolab",
                    # Overhang position (0.75 is outside table max_x=0.45)
                    "params": {"initial_pose": {"position_xyz": [0.75, 0.0, 0.75]}},
                },
            ],
            "relations": [
                {"kind": "is_anchor", "subject": "maple_table", "params": {}},
                {"kind": "on", "subject": "mustard_bottle", "reference": "maple_table", "params": {}},
                {"kind": "on", "subject": "grey_bin", "reference": "maple_table", "params": {}},
            ],
            "task": {
                "composition": "atomic",
                "description": "Place mustard into bin",
                "subtasks": [
                    {
                        "kind": "PickAndPlaceTask",
                        "params": {
                            "pick_up_object": "mustard_bottle",
                            "destination_location": "grey_bin",
                            "background_scene": "maple_table",
                        },
                    }
                ],
            },
        }

        spec = ArenaEnvGraphSpec.from_dict(spec_dict)
        containment_errs = validate_support_containment(spec)
        assert len(containment_errs) >= 1
        assert any("overhangs support surface" in e for e in containment_errs)

        reach_errs = validate_kinematic_reachability(spec)
        assert len(reach_errs) >= 1
        assert any("exceeding max arm reach" in e for e in reach_errs)

        is_valid, all_diags = validate_spatial_geometry(spec)
        assert not is_valid
        assert len(all_diags) >= 2
