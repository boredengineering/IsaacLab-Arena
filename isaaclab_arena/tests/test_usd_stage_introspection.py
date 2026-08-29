# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :mod:`isaaclab_arena.agentic_environment_generation.usd_stage_introspection`."""

from __future__ import annotations

import numpy as np
import pytest
import shapely.geometry
from pxr import Gf, Usd, UsdGeom, Vt

from isaaclab_arena.agentic_environment_generation.usd_stage_introspection import (
    AffordancePatch,
    DollhouseSubPrim,
    extract_geometric_affordance_patches,
    format_dollhouse_catalog,
)


def test_affordance_patch_dataclass_instantiation():
    """Verify AffordancePatch dataclass attributes and defaults."""
    patch = AffordancePatch(
        patch_id="shelf_patch_1",
        parent_prim="/World/shelf",
        elevation_z=0.75,
        surface_area=0.36,
        headroom=0.45,
        approach_yaw_range=[-30.0, 30.0],
        usable_polygon_hull=[[0.0, 0.0], [0.6, 0.0], [0.6, 0.6], [0.0, 0.6]],
        anchor_centroid=[0.3, 0.3, 0.75],
        principal_orientation_deg=0.0,
        has_planar_contact_deck=True,
    )

    assert patch.patch_id == "shelf_patch_1"
    assert patch.elevation_z == 0.75
    assert patch.surface_area == 0.36
    assert patch.has_planar_contact_deck is True


def test_extract_geometric_affordance_patches_on_synthetic_mesh():
    """Test vectorized affordance patch extraction on an in-memory USD mesh."""
    stage = Usd.Stage.CreateInMemory()
    xform_prim = UsdGeom.Xform.Define(stage, "/World/Table")
    mesh_prim = UsdGeom.Mesh.Define(stage, "/World/Table/Mesh")

    points = [
        Gf.Vec3f(-0.5, -0.5, 0.8),
        Gf.Vec3f(0.5, -0.5, 0.8),
        Gf.Vec3f(0.5, 0.5, 0.8),
        Gf.Vec3f(-0.5, 0.5, 0.8),
    ]
    face_vertex_counts = [4]
    face_vertex_indices = [0, 1, 2, 3]

    mesh_prim.GetPointsAttr().Set(Vt.Vec3fArray(points))
    mesh_prim.GetFaceVertexCountsAttr().Set(Vt.IntArray(face_vertex_counts))
    mesh_prim.GetFaceVertexIndicesAttr().Set(Vt.IntArray(face_vertex_indices))

    patches = extract_geometric_affordance_patches(
        xform_prim.GetPrim(),
        stage,
        z_bin_size=0.05,
        min_area=0.1,
        safety_margin=0.04,
    )

    assert len(patches) == 1, f"Expected 1 affordance patch, got {len(patches)}"
    patch = patches[0]
    assert np.isclose(patch.elevation_z, 0.80, atol=0.05)
    assert patch.surface_area > 0.5
    assert patch.has_planar_contact_deck is True
    assert np.isclose(patch.anchor_centroid[0], 0.0, atol=0.05)
    assert np.isclose(patch.anchor_centroid[1], 0.0, atol=0.05)


def test_concave_l_shape_representative_point():
    """Verify that representative_point() places the anchor strictly inside a concave L-shape."""
    stage = Usd.Stage.CreateInMemory()
    xform_prim = UsdGeom.Xform.Define(stage, "/World/LDesk")
    mesh_prim = UsdGeom.Mesh.Define(stage, "/World/LDesk/Mesh")

    # Construct an L-shaped desk using 2 quads
    # Quad 1: [0,0] to [3,1] at z=0.75
    # Quad 2: [0,1] to [1,3] at z=0.75
    points = [
        Gf.Vec3f(0.0, 0.0, 0.75),  # 0
        Gf.Vec3f(3.0, 0.0, 0.75),  # 1
        Gf.Vec3f(3.0, 1.0, 0.75),  # 2
        Gf.Vec3f(0.0, 1.0, 0.75),  # 3
        Gf.Vec3f(1.0, 1.0, 0.75),  # 4
        Gf.Vec3f(1.0, 3.0, 0.75),  # 5
        Gf.Vec3f(0.0, 3.0, 0.75),  # 6
    ]
    face_vertex_counts = [4, 4]
    face_vertex_indices = [0, 1, 2, 3, 3, 4, 5, 6]

    mesh_prim.GetPointsAttr().Set(Vt.Vec3fArray(points))
    mesh_prim.GetFaceVertexCountsAttr().Set(Vt.IntArray(face_vertex_counts))
    mesh_prim.GetFaceVertexIndicesAttr().Set(Vt.IntArray(face_vertex_indices))

    patches = extract_geometric_affordance_patches(
        xform_prim.GetPrim(),
        stage,
        z_bin_size=0.05,
        min_area=0.1,
        safety_margin=0.02,
    )

    assert len(patches) == 1
    patch = patches[0]
    # Check that anchor_centroid is strictly inside the usable polygon hull
    poly = shapely.geometry.Polygon(patch.usable_polygon_hull)
    pt = shapely.geometry.Point(patch.anchor_centroid[0], patch.anchor_centroid[1])
    assert poly.contains(pt) or poly.touches(pt), "Anchor point must lie within L-shape boundary!"


def test_multipolygon_dumbbell_erosion():
    """Verify that a dumbbell shape with narrow neck splits into 2 distinct patches."""
    stage = Usd.Stage.CreateInMemory()
    xform_prim = UsdGeom.Xform.Define(stage, "/World/Dumbbell")
    mesh_prim = UsdGeom.Mesh.Define(stage, "/World/Dumbbell/Mesh")

    # Left pad: [-2, -0.5] to [-0.5, 0.5]
    # Right pad: [0.5, -0.5] to [2, 0.5]
    # Thin bridge: [-0.5, -0.01] to [0.5, 0.01] (width 0.02m < 0.08m safety margin)
    points = [
        Gf.Vec3f(-2.0, -0.5, 0.6), Gf.Vec3f(-0.5, -0.5, 0.6), Gf.Vec3f(-0.5, 0.5, 0.6), Gf.Vec3f(-2.0, 0.5, 0.6), # Left
        Gf.Vec3f(0.5, -0.5, 0.6), Gf.Vec3f(2.0, -0.5, 0.6), Gf.Vec3f(2.0, 0.5, 0.6), Gf.Vec3f(0.5, 0.5, 0.6),      # Right
        Gf.Vec3f(-0.5, -0.01, 0.6), Gf.Vec3f(0.5, -0.01, 0.6), Gf.Vec3f(0.5, 0.01, 0.6), Gf.Vec3f(-0.5, 0.01, 0.6), # Bridge
    ]
    face_vertex_counts = [4, 4, 4]
    face_vertex_indices = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

    mesh_prim.GetPointsAttr().Set(Vt.Vec3fArray(points))
    mesh_prim.GetFaceVertexCountsAttr().Set(Vt.IntArray(face_vertex_counts))
    mesh_prim.GetFaceVertexIndicesAttr().Set(Vt.IntArray(face_vertex_indices))

    patches = extract_geometric_affordance_patches(
        xform_prim.GetPrim(),
        stage,
        z_bin_size=0.05,
        min_area=0.1,
        safety_margin=0.04,
    )

    # The bridge must erode away, leaving 2 separate sub-patches
    assert len(patches) == 2, f"Expected 2 split affordance patches, got {len(patches)}"


def test_long_edge_principal_orientation():
    """Verify that principal_orientation_deg is consistently aligned with the longest major edge."""
    stage = Usd.Stage.CreateInMemory()
    xform_prim = UsdGeom.Xform.Define(stage, "/World/TiltedBench")
    mesh_prim = UsdGeom.Mesh.Define(stage, "/World/TiltedBench/Mesh")

    # 4m x 1m bench rotated by 30 degrees
    theta = np.radians(30.0)
    c, s = np.cos(theta), np.sin(theta)
    local_pts = [
        [-2.0, -0.5, 0.5],
        [2.0, -0.5, 0.5],
        [2.0, 0.5, 0.5],
        [-2.0, 0.5, 0.5],
    ]
    rot_pts = [
        Gf.Vec3f(float(p[0]*c - p[1]*s), float(p[0]*s + p[1]*c), p[2])
        for p in local_pts
    ]

    mesh_prim.GetPointsAttr().Set(Vt.Vec3fArray(rot_pts))
    mesh_prim.GetFaceVertexCountsAttr().Set(Vt.IntArray([4]))
    mesh_prim.GetFaceVertexIndicesAttr().Set(Vt.IntArray([0, 1, 2, 3]))

    patches = extract_geometric_affordance_patches(
        xform_prim.GetPrim(),
        stage,
        min_area=0.5,
        safety_margin=0.04,
    )

    assert len(patches) == 1
    patch = patches[0]
    assert np.isclose(patch.principal_orientation_deg, 30.0, atol=2.0) or np.isclose(patch.principal_orientation_deg, 210.0 % 180, atol=2.0)


def test_format_dollhouse_catalog():
    """Verify dollhouse catalog text formatting for LLM context prompts."""
    sub_prims = [
        DollhouseSubPrim(
            prim_path="/World/shelf",
            prim_name="shelf",
            object_type="fixture",
            center_xyz=[0.0, 0.0, 0.5],
            is_surface=True,
            semantic_tag="surface",
            sub_surfaces=["shelf_patch_1", "shelf_patch_2"],
        )
    ]

    formatted = format_dollhouse_catalog(sub_prims)
    assert "INTROSPECTED USD DOLLHOUSE PRIMS:" in formatted
    assert "/World/shelf" in formatted
    assert "shelf_patch_1" in formatted
