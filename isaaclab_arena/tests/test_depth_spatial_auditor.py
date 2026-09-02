# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Depth-Anything Spatial Auditor and Oracle depth alignment verification."""

import numpy as np
import pytest

from isaaclab_arena.agentic_environment_generation.depth_spatial_auditor import DepthSpatialAuditor
from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
    DATASET_DEPTH_FINGERPRINTS,
    _G1_HEAD_CAM,
    _project_to_image_plane,
    _quat_to_rotation_matrix,
)


def test_quat_to_rotation_matrix_identity():
    """Identity quaternion produces identity matrix."""
    r_mat = _quat_to_rotation_matrix(0.0, 0.0, 0.0, 1.0)
    np.testing.assert_allclose(r_mat, np.eye(3), atol=1e-6)


def test_pinhole_projection_centered_point():
    """Point directly in front of camera projects to image center."""
    cam_world = (0.0, 0.0, 1.0)
    # Point 1 meter forward along camera Z
    # Using identity orientation
    proj = _project_to_image_plane(
        obj_world_xyz=(0.0, 0.0, 2.0),
        cam_world_xyz=cam_world,
        cam_quat_xyzw=(0.0, 0.0, 0.0, 1.0),
        focal_px=200.0,
        cx=320.0,
        cy=240.0,
    )
    assert proj is not None
    u_norm, v_norm, depth = proj
    assert abs(u_norm - 0.5) < 1e-4
    assert abs(v_norm - 0.5) < 1e-4
    assert abs(depth - 1.0) < 1e-4


def test_pinhole_projection_behind_camera():
    """Point behind camera returns None."""
    proj = _project_to_image_plane(
        obj_world_xyz=(0.0, 0.0, 0.0),
        cam_world_xyz=(0.0, 0.0, 1.0),
        cam_quat_xyzw=(0.0, 0.0, 0.0, 1.0),
        focal_px=200.0,
        cx=320.0,
        cy=240.0,
    )
    assert proj is None


def test_compute_surface_gradient_synthetic():
    """Synthetic downward slope produces positive gradient."""
    # 480 rows x 640 cols: linear slope increasing with row index
    depth_map = np.zeros((480, 640), dtype=np.float32)
    for r in range(480):
        depth_map[r, :] = r * 0.002

    slope = DepthSpatialAuditor.compute_surface_gradient(depth_map)
    assert slope > 0.0015
    assert slope < 0.0025


def test_locate_target_object_explicit_target_uv():
    """Locating object with target UV returns target_uv_projection method."""
    depth_map = np.ones((480, 640), dtype=np.float32) * 0.5
    dummy_rgb = np.zeros((480, 640, 3), dtype=np.uint8)

    info = DepthSpatialAuditor.locate_target_object(
        rgb_img=dummy_rgb,
        depth_map=depth_map,
        target_uv=(0.35, 0.70),
    )
    assert info["detected"] is True
    assert info["method"] == "target_uv_projection"
    assert abs(info["norm_center_x"] - 0.35) < 0.02
    assert abs(info["norm_center_y"] - 0.70) < 0.02
    assert abs(info["relative_depth"] - 0.5) < 1e-4


def test_dataset_depth_fingerprint_contains_canonical():
    """Dataset fingerprint registry contains static apple benchmark."""
    assert "g1_static_pick_and_place" in DATASET_DEPTH_FINGERPRINTS
    fp = DATASET_DEPTH_FINGERPRINTS["g1_static_pick_and_place"]
    assert "apple_y_norm" in fp
    assert "apple_depth_norm" in fp
    assert fp["apple_y_norm"] > 0.65  # Training demonstration has apple in lower third
