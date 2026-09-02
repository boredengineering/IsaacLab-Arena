# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Spatial Geometric & Kinematic Oracle for Active Inference Verification & Factor Graph Relaxation."""

from __future__ import annotations

import math
from typing import Any
import numpy as np

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.relations.spatial_factor_graph import SpatialFactorGraph


KNOWN_FIXTURE_BOUNDS: dict[str, tuple[float, float, float, float, float]] = {
    # [min_x, max_x, min_y, max_y, z_surface]
    "maple_table_robolab": (-0.45, 0.45, -0.30, 0.30, 0.75),
    "table_oak_robolab": (-0.45, 0.45, -0.30, 0.30, 0.75),
    "table": (-0.45, 0.45, -0.30, 0.30, 0.75),
    "office_table_background": (-0.45, 0.45, -0.30, 0.30, 0.75),
    "packing_table": (-0.45, 0.45, -0.30, 0.30, 0.75),
    "kitchen": (-0.40, 0.40, -0.30, 0.30, 0.75),
    "kitchen_background": (-0.40, 0.40, -0.30, 0.30, 0.75),
    "kitchen_with_open_drawer": (-0.40, 0.40, -0.30, 0.30, 0.75),
    "lightwheel_robocasa_kitchen": (-1.0, 1.0, -0.40, 0.40, 0.85),
    "galileo_locomanip": (0.45, 0.70, -0.15, 0.40, -0.03),
    "wireshelving_a01_vomp_robolab": (-0.45, 0.45, -0.25, 0.25, 0.76),
    "galileo_room_background": (-2.0, 2.0, -2.0, 2.0, 0.0),
    "simple_room_background": (-2.0, 2.0, -2.0, 2.0, 0.0),
}

FIXTURE_SECTOR_BOUNDS: dict[str, dict[str, tuple[float, float, float, float, float]]] = {
    "maple_table_robolab": {
        "front_center": (0.05, 0.25, -0.10, 0.10, 0.75),
        "front_left": (0.05, 0.25, -0.35, -0.10, 0.75),
        "front_right": (0.05, 0.25, 0.05, 0.25, 0.75),
        "front_half": (0.05, 0.25, -0.35, 0.35, 0.75),
        "robot_front": (0.05, 0.25, -0.35, 0.35, 0.75),
        "rear_center": (-0.25, -0.05, -0.10, 0.10, 0.75),
        "rear_left": (-0.25, -0.05, -0.35, -0.10, 0.75),
        "rear_right": (-0.25, -0.05, 0.05, 0.25, 0.75),
        "rear_storage": (-0.25, -0.05, -0.35, 0.35, 0.75),
        "table_top": (-0.35, 0.35, -0.25, 0.25, 0.75),
    },
    "table": {
        "front_center": (0.05, 0.25, -0.10, 0.10, 0.75),
        "front_left": (0.05, 0.25, -0.35, -0.10, 0.75),
        "front_right": (0.05, 0.25, 0.05, 0.25, 0.75),
        "front_half": (0.05, 0.25, -0.35, 0.35, 0.75),
        "robot_front": (0.05, 0.25, -0.35, 0.35, 0.75),
        "rear_center": (-0.25, -0.05, -0.10, 0.10, 0.75),
        "rear_left": (-0.25, -0.05, -0.35, -0.10, 0.75),
        "rear_right": (-0.25, -0.05, 0.05, 0.25, 0.75),
        "rear_storage": (-0.25, -0.05, -0.35, 0.35, 0.75),
        "table_top": (-0.35, 0.35, -0.25, 0.25, 0.75),
    },
    "kitchen": {
        "front_center": (-0.15, 0.05, -0.10, 0.10, 0.78),
        "front_left": (-0.15, 0.05, 0.10, 0.30, 0.78),
        "front_right": (-0.15, 0.05, -0.30, -0.10, 0.78),
        "center": (-0.15, 0.15, -0.15, 0.15, 0.78),
        "counter_top": (-0.35, 0.35, -0.35, 0.35, 0.78),
        "island": (-0.35, 0.35, -0.35, 0.35, 0.78),
    },
    "galileo_locomanip": {
        "front_center": (0.50, 0.65, 0.05, 0.25, -0.03),
        "front_left": (0.50, 0.65, -0.05, 0.12, -0.03),
        "front_right": (0.50, 0.65, 0.18, 0.35, -0.03),
        "shelf_tier_1": (0.45, 0.70, -0.15, 0.40, -0.03),
        "shelf_tier_2": (0.45, 0.70, -0.15, 0.40, 0.50),
        "shelf_tier_3": (0.45, 0.70, -0.15, 0.40, 0.90),
    },
    "wireshelving_a01_vomp_robolab": {
        "shelf_tier_1": (-0.40, 0.40, -0.20, 0.20, 0.76),
        "shelf_tier_2": (-0.40, 0.40, -0.20, 0.20, 1.15),
        "shelf_tier_3": (-0.40, 0.40, -0.20, 0.20, 1.55),
    },
}


def get_known_fixture_bounds(name: str) -> tuple[float, float, float, float, float]:
    """Retrieve approximate support surface boundary [min_x, max_x, min_y, max_y, z_deck]."""
    name_lower = name.lower()
    for key, bounds in KNOWN_FIXTURE_BOUNDS.items():
        if key in name_lower:
            return bounds
    if "shelf" in name_lower or "rack" in name_lower:
        return (-0.45, 0.45, -0.25, 0.25, 0.75)
    if "table" in name_lower or "desk" in name_lower or "counter" in name_lower:
        return (-0.45, 0.45, -0.30, 0.30, 0.75)
    # Default generic workspace patch
    return (-0.50, 0.50, -0.35, 0.35, 0.75)


def get_fixture_sector_bounds(
    fixture_name: str,
    sector_name: str | None = None,
) -> tuple[float, float, float, float, float]:
    """Retrieve functional sector bounds [min_x, max_x, min_y, max_y, z_deck] on a fixture."""
    known = get_known_fixture_bounds(fixture_name)
    if not sector_name:
        return known

    fixture_lower = fixture_name.lower()
    sector_lower = sector_name.lower()

    for fix_key, sectors in FIXTURE_SECTOR_BOUNDS.items():
        if fix_key in fixture_lower:
            matched_bounds = None
            if sector_lower in sectors:
                matched_bounds = sectors[sector_lower]
            else:
                for sec_key, sec_bounds in sectors.items():
                    if sec_key in sector_lower or sector_lower in sec_key:
                        matched_bounds = sec_bounds
                        break
            if matched_bounds:
                if matched_bounds[4] == 0.0 and known[4] != 0.0:
                    return (matched_bounds[0], matched_bounds[1], matched_bounds[2], matched_bounds[3], known[4])
                return matched_bounds

    # Default fallback to overall fixture bounds
    return known


def validate_support_containment(spec: ArenaEnvGraphSpec) -> list[str]:
    """Check if objects placed on fixtures lie within the fixture surface perimeter."""
    errors: list[str] = []
    assets_by_id = {obj.id: obj for obj in spec.objects}
    if spec.background:
        assets_by_id[spec.background.id] = spec.background

    for rel in spec.relations:
        if rel.kind == "on" and rel.reference:
            child = assets_by_id.get(rel.subject)
            parent = assets_by_id.get(rel.reference)
            if not child or not parent:
                continue

            bounds = get_known_fixture_bounds(parent.registry_name)
            edge_margin = float(rel.params.get("edge_margin_m", 0.05)) if rel.params else 0.05

            child_pose = child.params.get("initial_pose", {}) if child.params else {}
            pos = child_pose.get("position_xyz")
            if pos is not None and len(pos) >= 3:
                parent_pose = parent.params.get("initial_pose", {}) if parent.params else {}
                p_pos = parent_pose.get("position_xyz", [0.0, 0.0, 0.0])

                rel_x = pos[0] - p_pos[0]
                rel_y = pos[1] - p_pos[1]

                min_x = bounds[0] + edge_margin
                max_x = bounds[1] - edge_margin
                min_y = bounds[2] + edge_margin
                max_y = bounds[3] - edge_margin

                if rel_x < min_x or rel_x > max_x or rel_y < min_y or rel_y > max_y:
                    errors.append(
                        f"[GeometricOracle] Object '{child.id}' relative position [{rel_x:.2f}, {rel_y:.2f}] "
                        f"overhangs support surface of '{parent.id}' (allowed X in [{min_x:.2f}..{max_x:.2f}], "
                        f"Y in [{min_y:.2f}..{max_y:.2f}]). Place '{child.id}' on '{parent.id}' within valid bounds."
                    )
    return errors


def validate_kinematic_reachability(spec: ArenaEnvGraphSpec) -> list[str]:
    """Check if robot base pose can reach task-relevant pick objects and destinations."""
    errors: list[str] = []
    if not spec.embodiment:
        return errors

    emb_pose = spec.embodiment.params.get("initial_pose", {}) if spec.embodiment.params else {}
    emb_pos = emb_pose.get("position_xyz")
    if emb_pos is None or len(emb_pos) < 2:
        return errors

    emb_name_lower = f"{spec.embodiment.id} {spec.embodiment.registry_name}".lower()
    is_humanoid = "g1" in emb_name_lower or "gr1" in emb_name_lower
    max_reach = 0.95 if is_humanoid else 0.85
    min_reach = 0.25

    assets_by_id = {obj.id: obj for obj in spec.objects}

    # Collect objects involved in tasks
    task_object_ids: set[str] = set()
    for task in spec.task.subtasks:
        for p_val in task.params.values():
            if isinstance(p_val, str) and p_val in assets_by_id:
                task_object_ids.add(p_val)

    for obj_id in task_object_ids:
        obj = assets_by_id[obj_id]
        obj_pose = obj.params.get("initial_pose", {}) if obj.params else {}
        obj_pos = obj_pose.get("position_xyz")
        if obj_pos is not None and len(obj_pos) >= 2:
            dist = math.hypot(emb_pos[0] - obj_pos[0], emb_pos[1] - obj_pos[1])
            if dist > max_reach:
                errors.append(
                    f"[KinematicOracle] Task object '{obj.id}' is at distance {dist:.2f}m from robot base, "
                    f"exceeding max arm reach of {max_reach:.2f}m. Move '{obj.id}' closer to workspace center "
                    f"or adjust robot base position."
                )
            elif dist < min_reach:
                errors.append(
                    f"[KinematicOracle] Task object '{obj.id}' is at distance {dist:.2f}m (too close, within robot body collider). "
                    f"Maintain minimum distance of {min_reach:.2f}m."
                )
            if is_humanoid and len(emb_pos) >= 3 and len(obj_pos) >= 3:
                rel_z = obj_pos[2] - emb_pos[2]
                if rel_z > 0.45 or rel_z < -0.35:
                    errors.append(
                        f"[KinematicOracle] Humanoid '{spec.embodiment.id}' pelvis height Z={emb_pos[2]:.2f}m is misaligned "
                        f"with object '{obj.id}' at Z={obj_pos[2]:.2f}m (relative delta {rel_z:.2f}m outside reachable range [-0.35m, +0.45m]). "
                        f"Adjust robot standing elevation or workstation surface height."
                    )
    return errors


def validate_relational_completeness(spec: ArenaEnvGraphSpec) -> list[str]:
    """Ensure all manipulands and receptacles have explicit support/containment relations."""
    errors: list[str] = []
    referenced_subjects = {rel.subject for rel in spec.relations}

    for obj in spec.objects:
        obj_name_lower = f"{obj.id} {obj.registry_name}".lower()
        is_furniture = any(k in obj_name_lower for k in ("shelf", "shelving", "table", "counter", "desk", "rack"))
        if not is_furniture and obj.id not in referenced_subjects:
            errors.append(
                f"[RelationalOracle] Object '{obj.id}' has no support relation (e.g. 'on' or 'inside'). "
                f"It will spawn floating ungrounded. Add an explicit 'on' relation to the support fixture."
            )
    return errors


def relax_spec_spatial_factor_graph(spec: ArenaEnvGraphSpec) -> tuple[ArenaEnvGraphSpec, list[str]]:
    """Construct and relax a continuous SpatialFactorGraph over the spec's entities and relations."""
    diagnostics: list[str] = []
    if not spec.background:
        return spec, diagnostics

    bg_name = spec.background.id
    bg_lower = f"{bg_name} {spec.background.registry_name}".lower()
    floor_z = -0.795 if "galileo" in bg_lower or "room" in bg_lower else 0.0

    fg = SpatialFactorGraph()
    # 1. Ground scene background anchor at origin
    fg.add_variable(bg_name, [0.0, 0.0, floor_z, 0.0], is_fixed=True)

    # 2. Add Furniture Fixtures
    furniture_ids = set()
    receptacle_ids = set()
    for obj in spec.objects:
        obj_lower = f"{obj.id} {obj.registry_name}".lower()
        if any(k in obj_lower for k in ("shelf", "shelving", "table", "counter", "desk", "rack")):
            furniture_ids.add(obj.id)
            init_p = obj.params.get("initial_pose", {}).get("position_xyz", [0.0, 0.6, floor_z]) if obj.params else [0.0, 0.6, floor_z]
            fg.add_variable(obj.id, [init_p[0], init_p[1], init_p[2], 0.0], is_fixed=False)
            fg.add_ground_factor(obj.id, floor_z=floor_z)
        elif any(k in obj_lower for k in ("bin", "basket", "tray", "box")):
            receptacle_ids.add(obj.id)

    # 3. Add Robot Embodiment
    if spec.embodiment:
        emb_id = spec.embodiment.id
        init_emb = spec.embodiment.params.get("initial_pose", {}).get("position_xyz", [-0.55, 0.0, floor_z]) if spec.embodiment.params else [-0.55, 0.0, floor_z]
        fg.add_variable(emb_id, [init_emb[0], init_emb[1], init_emb[2], 0.0], is_fixed=False)
        fg.add_ground_factor(emb_id, floor_z=floor_z)

    # 4. Add Manipulands & Receptacles
    for obj in spec.objects:
        if obj.id in furniture_ids:
            continue
        init_p = obj.params.get("initial_pose", {}).get("position_xyz", [0.0, 0.0, floor_z + 0.75]) if obj.params else [0.0, 0.0, floor_z + 0.75]
        fg.add_variable(obj.id, [init_p[0], init_p[1], init_p[2], 0.0], is_fixed=False)

    # 5. Connect Factors from Relations
    for rel in spec.relations:
        if rel.kind == "on" and rel.reference:
            parent_reg = (
                spec.background.registry_name
                if rel.reference == bg_name
                else next((o.registry_name for o in spec.objects if o.id == rel.reference), "table")
            )
            sector = rel.params.get("surface_sector") if rel.params else None
            # On tabletop environments, default unassigned manipulands to front_center and receptacles to front_left
            if not sector and ("table" in parent_reg.lower() or "desk" in parent_reg.lower() or "counter" in parent_reg.lower()):
                sector = "front_left" if rel.subject in receptacle_ids else "front_center"
            bounds = get_fixture_sector_bounds(parent_reg, sector)
            fg.add_support_factor(rel.subject, rel.reference, bounds, edge_margin=0.04)

    # 6. Add Non-Overlap Clearance between all placed items
    placeable_objs = [o.id for o in spec.objects if o.id not in furniture_ids]
    for i in range(len(placeable_objs)):
        for j in range(i + 1, len(placeable_objs)):
            fg.add_clearance_factor(placeable_objs[i], placeable_objs[j], min_distance=0.22)

    # 7. Add Reachability Factors to Robot
    if spec.embodiment:
        for obj_id in placeable_objs:
            fg.add_reachability_factor(spec.embodiment.id, obj_id, target_distance=0.60, tolerance=0.20)
        # Prevent robot colliding with furniture
        for furn_id in furniture_ids:
            fg.add_clearance_factor(spec.embodiment.id, furn_id, min_distance=0.45)

    # 8. Perform LBP Relaxation
    result = fg.relax(max_iters=100)

    # 9. Apply Relaxed Poses back to Spec
    for obj in spec.objects:
        if obj.id in result.poses:
            p = result.poses[obj.id]
            if not obj.params:
                obj.params = {}
            obj.params["initial_pose"] = {
                "position_xyz": [p[0], p[1], p[2]],
                "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
            }

    if spec.embodiment and spec.embodiment.id in result.poses:
        ep = result.poses[spec.embodiment.id]
        if not spec.embodiment.params:
            spec.embodiment.params = {}
        spec.embodiment.params["initial_pose"] = {
            "position_xyz": [ep[0], ep[1], ep[2]],
            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
        }

    if not result.converged and result.conflicting_factors:
        diagnostics.append(
            f"[FactorGraphOracle] Dynamic LBP relaxation residual energy={result.total_energy:.3f}. "
            f"Conflicting factors: {', '.join(result.conflicting_factors)}"
        )

    return spec, diagnostics


def validate_spatial_geometry(spec: ArenaEnvGraphSpec) -> tuple[bool, list[str]]:
    """Run comprehensive spatial geometric, kinematic, and support containment checks."""
    diagnostics: list[str] = []
    diagnostics.extend(validate_relational_completeness(spec))
    diagnostics.extend(validate_support_containment(spec))
    diagnostics.extend(validate_kinematic_reachability(spec))
    return len(diagnostics) == 0, diagnostics
