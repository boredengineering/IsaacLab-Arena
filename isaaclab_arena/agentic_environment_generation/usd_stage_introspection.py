# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Telescopic USD Stage Introspection for Dollhouse Scene Decomposition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from isaaclab_arena.assets.object_type import ObjectType

if TYPE_CHECKING:
    from pxr import Usd


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


def introspect_usd_stage(usd_path: str) -> list[DollhouseSubPrim]:
    """Introspect a USD stage to extract its internal dollhouse hierarchy and Directed Cyclic Random Graph.

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
            from pxr import UsdGeom, UsdTimeCode

            bbox_cache = UsdGeom.BBoxCache(UsdTimeCode.Default(), [UsdGeom.Tokens.default_])

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
                is_horizontal_planar = (dim_x >= 0.2 and dim_y >= 0.2)
                is_surface_name = any(kw in name_lower for kw in ("shelf", "tier", "table", "counter", "desk", "surface", "tray", "top"))
                is_surface = is_surface_name or (is_horizontal_planar and obj_type == "fixture")

                semantic_tag = "surface" if is_surface else ("zone" if "bay" in name_lower or "room" in name_lower or "floor" in name_lower or (dim_x > 2.0 and dim_y > 2.0) else None)

                # Sub-surfaces / tiers if composite
                sub_surfaces = []
                if "shelf" in name_lower or "rack" in name_lower:
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
    """Format introspected USD prims into a structured prompt section for the LLM."""
    if not sub_prims:
        return "No introspected sub-prims found."

    lines = ["INTROSPECTED USD DOLLHOUSE PRIMS:"]
    for p in sub_prims:
        tag_str = f" [tag: {p.semantic_tag}]" if p.semantic_tag else ""
        surface_str = f" (sub-surfaces: {', '.join(p.sub_surfaces)})" if p.sub_surfaces else ""
        lines.append(f"  • {p.prim_path} ({p.object_type}){tag_str}{surface_str}")
    return "\n".join(lines)
