# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the deterministic Motion Clearance Engine (Pass 3c)."""

from __future__ import annotations

import math

import pytest

from isaaclab_arena.relations.motion_clearance_engine import (
    check_2d_obb_clearance,
    check_cavity_containment_and_headroom,
    check_dual_revolute_clearance,
    check_object_prismatic_clearance,
    check_pedestal_prismatic_clearance,
    check_revolute_manifold_clearance,
    compute_prismatic_stroke_corridor,
    compute_revolute_swept_manifold,
    evaluate_sector_admissibility,
    partition_fixture_surface_sectors,
    point_to_revolute_manifold_distance,
)


def test_revolute_manifold_clearance_d1c_microwave():
    """Verify microwave in front_right / back_right leaves front_left soup can clear (>= 0.15m)."""
    manifold = compute_revolute_swept_manifold(
        base_pos=(0.25, -0.35),
        base_yaw_rad=-math.pi / 2.0,
        hinge_offset_local=(-0.10, -0.15),
        door_radius_m=0.35,
        swing_span_rad=(0.0, math.pi / 2.0),
    )

    # Soup can in front_left sector at (0.25, +0.25) -> well outside swept arc
    ok_clear, clearance, _ = check_revolute_manifold_clearance(
        manifold, prop_xy=(0.25, 0.25), prop_radius_m=0.035, margin_m=0.15
    )
    assert ok_clear is True
    assert clearance >= 0.15

    # Soup can placed directly in front of microwave door at (0.15, -0.25) -> collides
    ok_collide, bad_clearance, msg = check_revolute_manifold_clearance(
        manifold, prop_xy=(0.15, -0.25), prop_radius_m=0.035, margin_m=0.15
    )
    assert ok_collide is False
    assert bad_clearance < 0.15
    assert "collides" in msg


def test_point_to_revolute_manifold_distance():
    """Verify analytical distance to an annular wedge inside and outside the sweep."""
    manifold = compute_revolute_swept_manifold(
        base_pos=(0.0, 0.0),
        base_yaw_rad=0.0,
        hinge_offset_local=(0.0, 0.0),
        door_radius_m=0.40,
        swing_span_rad=(0.0, math.pi / 2.0),
    )
    # Point inside wedge at (0.2, 0.2) -> distance 0.0
    assert point_to_revolute_manifold_distance((0.2, 0.2), manifold) == pytest.approx(0.0, abs=1e-6)
    # Point radially beyond wedge at (0.5, 0.0) -> distance 0.10
    assert point_to_revolute_manifold_distance((0.5, 0.0), manifold) == pytest.approx(0.10, abs=1e-5)


def test_prismatic_stroke_corridor_and_pedestal_clearance_d2a():
    """Verify prismatic drawer corridor V_prismatic and pedestal SAT clearance (D2-A / D2-B)."""
    corridor = compute_prismatic_stroke_corridor(
        fixture_pos=(0.10, 0.0, 0.0),
        fixture_yaw_rad=math.pi,  # Facing -X toward robot at (-0.85, 0.0)
        slide_axis_local=(1.0, 0.0),  # Local +X maps to world -X
        stroke_length_m=0.473,
        drawer_width_m=0.50,
        drawer_depth_m=0.35,
    )

    # Robot pedestal at (-0.85, 0.0) with 0.40x0.40m footprint clears corridor
    ok_ped, cl_ped, _ = check_pedestal_prismatic_clearance(
        robot_pos_xy=(-0.85, 0.0),
        robot_yaw_rad=0.0,
        corridor=corridor,
        pedestal_half_extents=(0.20, 0.20),
        margin_m=0.05,
    )
    assert ok_ped is True
    assert cl_ped >= 0.05

    # Robot pedestal too close at (-0.45, 0.0) intersects the extended drawer stroke
    ok_bad, cl_bad, _ = check_pedestal_prismatic_clearance(
        robot_pos_xy=(-0.45, 0.0),
        robot_yaw_rad=0.0,
        corridor=corridor,
        pedestal_half_extents=(0.20, 0.20),
        margin_m=0.05,
    )
    assert ok_bad is False
    assert cl_bad < 0.0


def test_surface_sector_partitioning_and_admissibility():
    """Verify table deck partitioning marks front_left admissible when microwave is in back_right."""
    sectors = partition_fixture_surface_sectors(
        fixture_pos_xy=(0.0, 0.0),
        fixture_yaw_rad=-math.pi / 2.0,
        footprint_half_extents=(0.901, 0.401),
        deck_z_m=0.531,
    )
    assert set(sectors.keys()) == {
        "front_left",
        "front_right",
        "back_left",
        "back_right",
        "front_center",
        "center",
    }

    manifold = compute_revolute_swept_manifold(
        base_pos=sectors["back_right"].center_xy,
        base_yaw_rad=-math.pi / 2.0,
        hinge_offset_local=(-0.10, -0.15),
        door_radius_m=0.35,
    )
    admissibility = evaluate_sector_admissibility(sectors, revolute_manifold=manifold, margin_m=0.10)
    assert admissibility["front_left"] is True
    assert admissibility["back_right"] is False


def test_cavity_containment_and_headroom_d2b():
    """Verify stowed soup can fits inside drawer cavity with >= 0.02m vertical headroom (D2-B)."""
    # Soup can: 0.07 x 0.07 x 0.10m; Drawer cavity: 0.35 x 0.28 x 0.14m
    ok, metrics, _ = check_cavity_containment_and_headroom(
        object_dims_xyz=(0.07, 0.07, 0.10),
        cavity_dims_xyz=(0.35, 0.28, 0.14),
        min_headroom_m=0.02,
        max_volume_ratio=0.40,
    )
    assert ok is True
    assert metrics["headroom_z_m"] == pytest.approx(0.04, abs=1e-4)
    assert metrics["volume_ratio"] <= 0.40

    # Tall bottle (h=0.135m) in shallow drawer (h=0.14m) fails headroom (< 0.02m)
    ok_tall, _, msg_tall = check_cavity_containment_and_headroom(
        object_dims_xyz=(0.07, 0.07, 0.135),
        cavity_dims_xyz=(0.35, 0.28, 0.14),
        min_headroom_m=0.02,
    )
    assert ok_tall is False
    assert "headroom" in msg_tall


def test_dual_revolute_clearance_d2c():
    """Verify dual counter-rotating medical cabinet doors (D2-C) clear each other and the robot."""
    left_door = compute_revolute_swept_manifold(
        base_pos=(0.0, 0.25),
        base_yaw_rad=math.pi,
        hinge_offset_local=(0.0, 0.0),
        door_radius_m=0.24,
        swing_span_rad=(0.0, math.pi / 2.0),
    )
    right_door = compute_revolute_swept_manifold(
        base_pos=(0.0, -0.25),
        base_yaw_rad=math.pi,
        hinge_offset_local=(0.0, 0.0),
        door_radius_m=0.24,
        swing_span_rad=(-math.pi / 2.0, 0.0),
    )
    ok, metrics, _ = check_dual_revolute_clearance(
        left_manifold=left_door,
        right_manifold=right_door,
        robot_pos_xy=(-0.80, 0.0),
        pedestal_radius_m=0.20,
        min_seam_clearance_m=0.05,
    )
    assert ok is True
    assert metrics["hinge_span_m"] == pytest.approx(0.50, abs=1e-4)
    assert metrics["min_pedestal_clearance_m"] >= 0.05


def test_check_2d_obb_clearance_edge_cases():
    """Verify 2D SAT OBB separation and overlap calculations."""
    ok, cl, _ = check_2d_obb_clearance((0.0, 0.0), 0.0, (0.2, 0.2), (0.6, 0.0), 0.0, (0.2, 0.2), margin=0.05)
    assert ok is True
    assert cl >= 0.05

    ok_ov, cl_ov, _ = check_2d_obb_clearance((0.0, 0.0), 0.0, (0.2, 0.2), (0.3, 0.0), 0.0, (0.2, 0.2), margin=0.05)
    assert ok_ov is False
    assert cl_ov < 0.0
