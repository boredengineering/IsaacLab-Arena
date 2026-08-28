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
    semantic_tag: str | None = None
    sub_surfaces: list[str] = field(default_factory=list)


def introspect_usd_stage(usd_path: str) -> list[DollhouseSubPrim]:
    """Introspect a USD stage to extract its internal dollhouse hierarchy.

    Args:
        usd_path: Path to the USD file.

    Returns:
        List of DollhouseSubPrim objects representing rooms, fixtures, surfaces, and zones.
    """
    from isaaclab_arena.utils.usd_helpers import (
        has_physics_or_collision,
        object_type_for_prim,
        open_stage,
        relative_path_from_default_prim,
    )

    sub_prims: list[DollhouseSubPrim] = []

    try:
        with open_stage(usd_path) as stage:
            for prim in stage.Traverse():
                if prim.IsPseudoRoot():
                    continue
                if not (has_physics_or_collision(prim) or prim.GetTypeName() in ("Xform", "Scope", "Mesh")):
                    continue

                rel_path = relative_path_from_default_prim(stage, str(prim.GetPath()))
                if not rel_path:
                    continue

                obj_type = object_type_for_prim(prim).value if hasattr(object_type_for_prim(prim), "value") else "rigid"
                name_lower = prim.GetName().lower()

                # Detect surface or interaction affordance
                is_surface = any(kw in name_lower for kw in ("shelf", "tier", "table", "counter", "desk", "surface", "tray", "top"))
                semantic_tag = "surface" if is_surface else ("zone" if "bay" in name_lower or "room" in name_lower or "floor" in name_lower else None)

                # Sub-surfaces / tiers if composite
                sub_surfaces = []
                if "shelf" in name_lower or "rack" in name_lower:
                    sub_surfaces = ["shelf_tier_1", "shelf_tier_2", "shelf_tier_3"]

                sub_prims.append(
                    DollhouseSubPrim(
                        prim_path=rel_path,
                        prim_name=prim.GetName(),
                        object_type=obj_type,
                        is_surface=is_surface,
                        semantic_tag=semantic_tag,
                        sub_surfaces=sub_surfaces,
                    )
                )
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
