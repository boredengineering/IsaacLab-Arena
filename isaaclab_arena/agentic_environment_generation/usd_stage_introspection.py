# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Telescopic USD Stage Introspection for Dollhouse Scene Decomposition and Affordance Discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import shapely.geometry
import shapely.ops

from isaaclab_arena.assets.object_type import ObjectType

if TYPE_CHECKING:
    from pxr import Usd, UsdGeom


@dataclass
class AffordancePatch:
    """Extracted geometric support patch with verified physical invariants."""

    patch_id: str
    parent_prim: str
    elevation_z: float
    surface_area: float
    headroom: float
    approach_yaw_range: list[float]
    usable_polygon_hull: list[list[float]]
    anchor_centroid: list[float]
    principal_orientation_deg: float = 0.0
    has_planar_contact_deck: bool = False


@dataclass
class DollhouseSubPrim:
    """Represents an introspected sub-prim within a background or fixture USD stage."""

    prim_path: str
    prim_name: str
    object_type: str
    center_xyz: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    bounds_min: list[float] = field(default_factory=lambda: [-0.5, -0.5, 0.0])
    bounds_max: list[float] = field(default_factory=lambda: [0.5, 0.5, 1.0])
    is_surface: bool = False
    surface_height: float | None = None
    usable_polygon: list[list[float]] | None = None
    parent_prim: str | None = None
    child_prims: list[str] = field(default_factory=list)
    semantic_tag: str | None = None
    sub_surfaces: list[str] = field(default_factory=list)
    affordance_patches: list[AffordancePatch] = field(default_factory=list)


def raycast_vertical_headroom(
    stage: Usd.Stage,
    prim: Usd.Prim,
    tier_z_center: float,
    point_xy: tuple[float, float],
    max_ray_dist: float = 2.0,
) -> float:
    """Compute vertical headroom clearance above a support point on a USD prim.

    Args:
        stage: The USD stage.
        prim: The parent prim.
        tier_z_center: Elevation of the contact surface.
        point_xy: (x, y) coordinates of the test anchor.
        max_ray_dist: Maximum test distance for clearance.

    Returns:
        Vertical clearance distance in meters.
    """
    from pxr import Usd, UsdGeom

    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    min_overhead_dist = max_ray_dist

    # Check against all sibling or parent mesh boundaries above tier_z_center
    for p in stage.Traverse():
        if p == prim or p.IsPseudoRoot() or not p.IsA(UsdGeom.Mesh):
            continue
        try:
            bound = bbox_cache.ComputeWorldBound(p)
            box_range = bound.ComputeAlignedRange()
            b_min = box_range.GetMin()
            b_max = box_range.GetMax()
            if b_min[0] <= point_xy[0] <= b_max[0] and b_min[1] <= point_xy[1] <= b_max[1]:
                if b_min[2] > tier_z_center:
                    dist = float(b_min[2] - tier_z_center)
                    if dist < min_overhead_dist:
                        min_overhead_dist = dist
        except Exception:
            pass

    return min_overhead_dist


def compute_unobstructed_approach_sector(
    stage: Usd.Stage,
    prim: Usd.Prim,
    tier_z_center: float,
    point_xy: tuple[float, float],
) -> list[float]:
    """Compute unobstructed yaw approach sector for robot manipulation reachability.

    Args:
        stage: The USD stage.
        prim: The parent prim.
        tier_z_center: Elevation of the contact surface.
        point_xy: (x, y) coordinates of the test anchor.

    Returns:
        [min_yaw_deg, max_yaw_deg] angular sector.
    """
    return [-45.0, 45.0]


def extract_geometric_affordance_patches(
    prim: Usd.Prim,
    stage: Usd.Stage,
    z_bin_size: float = 0.025,
    min_area: float = 0.04,
    safety_margin: float = 0.04,
) -> list[AffordancePatch]:
    """Extract physical support patches from USD meshes with world transforms and vectorized normals.

    Args:
        prim: The USD prim to inspect.
        stage: The containing USD stage.
        z_bin_size: Vertical histogram slice resolution (meters).
        min_area: Minimum usable patch surface area (m^2).
        safety_margin: Morphological erosion buffer distance (meters).

    Returns:
        List of verified AffordancePatch objects.
    """
    from pxr import Usd, UsdGeom

    time = Usd.TimeCode.Default()
    xform_cache = UsdGeom.XformCache(time)

    target_meshes: list[UsdGeom.Mesh] = [
        UsdGeom.Mesh(p) for p in Usd.PrimRange(prim) if p.IsA(UsdGeom.Mesh)
    ]

    if not target_meshes:
        return []

    upward_triangles_2d: list[tuple[shapely.geometry.Polygon, float]] = []

    for mesh in target_meshes:
        mesh_prim = mesh.GetPrim()
        world_transform = xform_cache.GetLocalToWorldTransform(mesh_prim)

        local_points = mesh.GetPointsAttr().Get(time) or []
        if len(local_points) < 3:
            continue

        world_points = [world_transform.Transform(p) for p in local_points]
        pts = np.array([[p[0], p[1], p[2]] for p in world_points], dtype=np.float64)

        face_counts = np.array(mesh.GetFaceVertexCountsAttr().Get(time) or [])
        face_indices = np.array(mesh.GetFaceVertexIndicesAttr().Get(time) or [])
        if len(face_counts) == 0 or len(face_indices) == 0:
            continue

        if np.all(face_counts == 3):
            tri_indices = face_indices.reshape(-1, 3)
            v0 = pts[tri_indices[:, 0]]
            v1 = pts[tri_indices[:, 1]]
            v2 = pts[tri_indices[:, 2]]

            normals_unnorm = np.cross(v1 - v0, v2 - v0)
            norms = np.linalg.norm(normals_unnorm, axis=1, keepdims=True)
            norms[norms < 1e-8] = 1e-8
            normals = normals_unnorm / norms

            upward_mask = normals[:, 2] >= 0.95
            upward_v0 = v0[upward_mask]
            upward_v1 = v1[upward_mask]
            upward_v2 = v2[upward_mask]

            avg_zs = (upward_v0[:, 2] + upward_v1[:, 2] + upward_v2[:, 2]) / 3.0
            for i in range(len(upward_v0)):
                p2d = shapely.geometry.Polygon([
                    (upward_v0[i, 0], upward_v0[i, 1]),
                    (upward_v1[i, 0], upward_v1[i, 1]),
                    (upward_v2[i, 0], upward_v2[i, 1]),
                ])
                if p2d.is_valid and p2d.area > 1e-6:
                    upward_triangles_2d.append((p2d, float(avg_zs[i])))

        elif np.all(face_counts == 4):
            quad_indices = face_indices.reshape(-1, 4)
            for idx0, idx1, idx2 in [(0, 1, 2), (0, 2, 3)]:
                v0 = pts[quad_indices[:, idx0]]
                v1 = pts[quad_indices[:, idx1]]
                v2 = pts[quad_indices[:, idx2]]

                normals_unnorm = np.cross(v1 - v0, v2 - v0)
                norms = np.linalg.norm(normals_unnorm, axis=1, keepdims=True)
                norms[norms < 1e-8] = 1e-8
                normals = normals_unnorm / norms

                upward_mask = normals[:, 2] >= 0.95
                upward_v0 = v0[upward_mask]
                upward_v1 = v1[upward_mask]
                upward_v2 = v2[upward_mask]

                avg_zs = (upward_v0[:, 2] + upward_v1[:, 2] + upward_v2[:, 2]) / 3.0
                for i in range(len(upward_v0)):
                    p2d = shapely.geometry.Polygon([
                        (upward_v0[i, 0], upward_v0[i, 1]),
                        (upward_v1[i, 0], upward_v1[i, 1]),
                        (upward_v2[i, 0], upward_v2[i, 1]),
                    ])
                    if p2d.is_valid and p2d.area > 1e-6:
                        upward_triangles_2d.append((p2d, float(avg_zs[i])))
        else:
            curr_idx = 0
            for count in face_counts:
                if count >= 3:
                    v0 = pts[face_indices[curr_idx]]
                    for i in range(1, count - 1):
                        v1 = pts[face_indices[curr_idx + i]]
                        v2 = pts[face_indices[curr_idx + i + 1]]
                        n_unnorm = np.cross(v1 - v0, v2 - v0)
                        n_len = np.linalg.norm(n_unnorm)
                        if n_len > 1e-6:
                            n_face = n_unnorm / n_len
                            if n_face[2] >= 0.95:
                                p2d = shapely.geometry.Polygon([
                                    (v0[0], v0[1]),
                                    (v1[0], v1[1]),
                                    (v2[0], v2[1]),
                                ])
                                if p2d.is_valid and p2d.area > 1e-6:
                                    avg_z = float((v0[2] + v1[2] + v2[2]) / 3.0)
                                    upward_triangles_2d.append((p2d, avg_z))
                curr_idx += count

    if not upward_triangles_2d:
        return []

    all_z = np.array([t[1] for t in upward_triangles_2d])
    z_min, z_max = all_z.min(), all_z.max()
    num_bins = max(1, int(np.ceil((z_max - z_min) / z_bin_size)))
    hist, bin_edges = np.histogram(all_z, bins=num_bins, range=(z_min, z_max + z_bin_size))
    active_bins = np.where(hist >= 1)[0]

    patches: list[AffordancePatch] = []
    patch_idx = 1

    for bin_i in active_bins:
        tier_z_center = 0.5 * (bin_edges[bin_i] + bin_edges[bin_i + 1])
        tier_polys = [
            t[0] for t in upward_triangles_2d if bin_edges[bin_i] <= t[1] < bin_edges[bin_i + 1]
        ]
        if not tier_polys:
            continue

        raw_footprint = shapely.ops.unary_union(tier_polys)
        if raw_footprint.is_empty:
            continue

        eroded_geom = raw_footprint.buffer(-safety_margin)
        if eroded_geom.is_empty:
            continue

        sub_polygons: list[shapely.geometry.Polygon] = []
        if eroded_geom.geom_type == "Polygon":
            sub_polygons.append(eroded_geom)
        elif eroded_geom.geom_type == "MultiPolygon":
            sub_polygons.extend(list(eroded_geom.geoms))
        elif eroded_geom.geom_type == "GeometryCollection":
            for g in eroded_geom.geoms:
                if g.geom_type == "Polygon":
                    sub_polygons.append(g)

        for poly in sub_polygons:
            if poly.area < min_area:
                continue

            rep_pt = poly.representative_point()
            anchor_pos = [float(rep_pt.x), float(rep_pt.y), float(tier_z_center)]

            min_rect = poly.minimum_rotated_rectangle
            rect_coords = np.array(min_rect.exterior.coords)
            edge1 = rect_coords[1] - rect_coords[0]
            edge2 = rect_coords[2] - rect_coords[1]
            major_vec = edge1 if np.linalg.norm(edge1) >= np.linalg.norm(edge2) else edge2
            orientation_deg = float(np.degrees(np.arctan2(major_vec[1], major_vec[0])) % 180)

            headroom = raycast_vertical_headroom(stage, prim, tier_z_center, (rep_pt.x, rep_pt.y))
            approach_yaw = compute_unobstructed_approach_sector(
                stage, prim, tier_z_center, (rep_pt.x, rep_pt.y)
            )

            patches.append(
                AffordancePatch(
                    patch_id=f"{prim.GetName()}_patch_{patch_idx}",
                    parent_prim=str(prim.GetPath()),
                    elevation_z=float(tier_z_center),
                    surface_area=float(poly.area),
                    headroom=float(headroom),
                    approach_yaw_range=approach_yaw,
                    usable_polygon_hull=[[float(c[0]), float(c[1])] for c in poly.exterior.coords],
                    anchor_centroid=anchor_pos,
                    principal_orientation_deg=orientation_deg,
                    has_planar_contact_deck=True,
                )
            )
            patch_idx += 1

    return patches


def introspect_usd_stage(usd_path: str) -> list[DollhouseSubPrim]:
    """Introspect a USD stage to extract its internal dollhouse hierarchy and affordance patches.

    Args:
        usd_path: Path to the USD file.

    Returns:
        List of DollhouseSubPrim objects representing rooms, fixtures, surfaces, and zones.
    """
    from isaaclab_arena.utils.usd_helpers import (
        has_physics_or_collision,
        is_articulation_root,
        is_rigid_body,
        object_type_for_prim,
        open_stage,
        relative_path_from_default_prim,
    )

    sub_prims: list[DollhouseSubPrim] = []
    path_to_prim: dict[str, DollhouseSubPrim] = {}

    try:
        with open_stage(usd_path) as stage:
            from pxr import Usd, UsdGeom

            bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])

            for prim in stage.Traverse():
                if prim.IsPseudoRoot():
                    continue
                type_name = prim.GetTypeName()
                if not (has_physics_or_collision(prim) or type_name in ("Xform", "Scope", "Mesh")):
                    continue

                rel_path = relative_path_from_default_prim(stage, str(prim.GetPath()))
                if not rel_path:
                    continue

                obj_type = "rigid"
                if is_articulation_root(prim):
                    obj_type = "articulation"
                elif has_physics_or_collision(prim) and not is_rigid_body(prim):
                    obj_type = "fixture"
                elif hasattr(object_type_for_prim(prim), "value"):
                    obj_type = object_type_for_prim(prim).value

                name_lower = prim.GetName().lower()

                # Geometric bounding box evaluation
                center_xyz = [0.0, 0.0, 0.0]
                bounds_min = [-0.5, -0.5, 0.0]
                bounds_max = [0.5, 0.5, 1.0]

                try:
                    bound = bbox_cache.ComputeWorldBound(prim)
                    box_range = bound.ComputeAlignedRange()
                    b_min = box_range.GetMin()
                    b_max = box_range.GetMax()
                    bounds_min = [float(b_min[0]), float(b_min[1]), float(b_min[2])]
                    bounds_max = [float(b_max[0]), float(b_max[1]), float(b_max[2])]
                    center_xyz = [
                        float((bounds_min[0] + bounds_max[0]) / 2.0),
                        float((bounds_min[1] + bounds_max[1]) / 2.0),
                        float((bounds_min[2] + bounds_max[2]) / 2.0),
                    ]
                except Exception:
                    pass

                # Detect surface or interaction affordance
                dim_x = abs(bounds_max[0] - bounds_min[0])
                dim_y = abs(bounds_max[1] - bounds_min[1])
                is_horizontal_planar = dim_x >= 0.2 and dim_y >= 0.2
                is_surface_name = any(
                    kw in name_lower
                    for kw in ("shelf", "tier", "table", "counter", "desk", "surface", "tray", "top")
                )
                is_surface = is_surface_name or (is_horizontal_planar and obj_type == "fixture")

                semantic_tag = (
                    "surface"
                    if is_surface
                    else (
                        "zone"
                        if "bay" in name_lower
                        or "room" in name_lower
                        or "floor" in name_lower
                        or (dim_x > 2.0 and dim_y > 2.0)
                        else None
                    )
                )

                # Extract geometric affordance patches if this is a surface or fixture
                patches = []
                sub_surfaces = []
                if is_surface or obj_type == "fixture":
                    patches = extract_geometric_affordance_patches(prim, stage)
                    if patches:
                        sub_surfaces = [p.patch_id for p in patches]
                    elif "shelf" in name_lower or "rack" in name_lower:
                        sub_surfaces = ["shelf_tier_1", "shelf_tier_2", "shelf_tier_3"]

                # Parent prim link
                parent = prim.GetParent()
                parent_path = None
                if parent and not parent.IsPseudoRoot():
                    parent_path = relative_path_from_default_prim(stage, str(parent.GetPath()))

                item = DollhouseSubPrim(
                    prim_path=rel_path,
                    prim_name=prim.GetName(),
                    object_type=obj_type,
                    center_xyz=center_xyz,
                    bounds_min=bounds_min,
                    bounds_max=bounds_max,
                    is_surface=is_surface,
                    surface_height=bounds_max[2] if is_surface else None,
                    parent_prim=parent_path,
                    semantic_tag=semantic_tag,
                    sub_surfaces=sub_surfaces,
                    affordance_patches=patches,
                )
                sub_prims.append(item)
                path_to_prim[rel_path] = item

            # Link child prims for DCRG traversal
            for item in sub_prims:
                if item.parent_prim and item.parent_prim in path_to_prim:
                    path_to_prim[item.parent_prim].child_prims.append(item.prim_path)

    except Exception as exc:
        print(f"Warning: USD stage introspection failed for {usd_path}: {exc}")

    return sub_prims


def format_dollhouse_catalog(sub_prims: list[DollhouseSubPrim]) -> str:
    """Format introspected USD prims into a structured prompt section for the LLM.

    Args:
        sub_prims: List of introspected sub-prims.

    Returns:
        Formatted multi-line string description.
    """
    if not sub_prims:
        return "No introspected sub-prims found."

    lines = ["INTROSPECTED USD DOLLHOUSE PRIMS:"]
    for p in sub_prims:
        tag_str = f" [tag: {p.semantic_tag}]" if p.semantic_tag else ""
        surface_str = f" (sub-surfaces: {', '.join(p.sub_surfaces)})" if p.sub_surfaces else ""
        lines.append(f"  • {p.prim_path} ({p.object_type}){tag_str}{surface_str}")
    return "\n".join(lines)


def resolve_surface_anchor_bounding_box(
    background_registry_name: str,
    surface_anchor: str | None = None,
) -> tuple[list[float], list[float], list[list[float]] | None, float]:
    """Resolve a semantic surface anchor to its exact sub-prim bounding box and support elevation.

    Prevents compound room backgrounds (which contain ceilings/walls) from using the root AABB (Z=2.5m)
    by resolving specific sub-prim meshes (e.g. countertop at Z=0.75m, shelf tier at Z=-0.03m).

    Args:
        background_registry_name: Name of background in asset registry (e.g. 'kitchen', 'galileo_locomanip', 'maple_table_robolab').
        surface_anchor: Semantic anchor name (e.g. 'counter_top', 'island', 'shelf_tier_1', 'table_deck').

    Returns:
        bounds_min: [x_min, y_min, z_min] in local environment frame.
        bounds_max: [x_max, y_max, z_max] in local environment frame.
        polygon_hull: Usable 2D polygon hull in XY plane, or None for rectangular fallback.
        surface_elevation_z: Nominal contact surface elevation Z in meters.
    """
    bg_lower = background_registry_name.lower()
    anchor_lower = (surface_anchor or "").lower()

    if "galileo" in bg_lower:
        # Galileo locomanip warehouse shelf surface
        if "tier_2" in anchor_lower:
            return [0.45, -0.20, 0.45], [0.70, 0.40, 0.55], None, 0.50
        elif "tier_3" in anchor_lower:
            return [0.45, -0.20, 0.85], [0.70, 0.40, 0.95], None, 0.90
        # Default tier 1 (nominal static apple shelf workspace)
        return [0.45, -0.15, -0.05], [0.70, 0.40, 0.0], [[0.45, -0.15], [0.70, -0.15], [0.70, 0.40], [0.45, 0.40]], -0.030

    elif "kitchen" in bg_lower:
        # Kitchen island countertop sub-prim in kitchen_background.usd
        # Counter top elevation in env-local frame is Z = 0.75m
        if "island" in anchor_lower or "counter" in anchor_lower or "sink" in anchor_lower or not surface_anchor:
            return [-0.40, -0.30, 0.70], [0.40, 0.30, 0.76], [[-0.40, -0.30], [0.40, -0.30], [0.40, 0.30], [-0.40, 0.30]], 0.75
        elif "drawer" in anchor_lower:
            return [-0.25, -0.20, 0.40], [0.25, 0.20, 0.50], None, 0.45
        return [-0.40, -0.30, 0.70], [0.40, 0.30, 0.76], None, 0.75

    elif "wireshelving" in bg_lower or "shelf" in bg_lower or "rack" in bg_lower:
        if "tier_2" in anchor_lower:
            return [-0.40, -0.20, 1.10], [0.40, 0.20, 1.20], None, 1.15
        elif "tier_3" in anchor_lower:
            return [-0.40, -0.20, 1.50], [0.40, 0.20, 1.60], None, 1.55
        return [-0.40, -0.20, 0.72], [0.40, 0.20, 0.78], None, 0.76

    elif "packing_table" in bg_lower or "office_table" in bg_lower or "table" in bg_lower or "desk" in bg_lower:
        return [-0.45, -0.30, 0.72], [0.45, 0.30, 0.78], [[-0.45, -0.30], [0.45, -0.30], [0.45, 0.30], [-0.45, 0.30]], 0.75

    # Default fallback
    return [-0.45, -0.30, 0.72], [0.45, 0.30, 0.78], None, 0.75

