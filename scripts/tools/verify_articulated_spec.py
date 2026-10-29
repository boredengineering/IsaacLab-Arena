#!/usr/bin/env python3
"""Deterministic Deterministic Tooling Oracle for Articulated Environments.

Validates that an autonomously generated ArenaEnvGraphSpec YAML satisfies:
1. Schema & Graph Integrity (entity registrations, task composition).
2. USD Kinematics Ground-Truth across diverse articulated fixtures:
   - Revolute Doors: Microwave, refrigerator, cabinet doors, dishwasher, oven.
   - Prismatic Slides: Kitchen drawers, sliding cabinets, storage bins.
3. 3D Euclidean Swept Envelope Clearance (S_envelope ∩ Props == ∅).
   - Revolute: Circular wedge sector volume.
   - Prismatic: Linear pull corridor volume.
4. Sequential State Handoff Invariants (openness threshold, gripper release, standoff retract margin).
5. Task-Affordance Facing: the aperture of the articulated object faces the robot base (fixed-base arms).
6. Standoff & Elevation Alignment: Robot-to-fixture horizontal standoff (0.50m - 1.20m) and tabletop elevation alignment with robot stand base.

Outputs structured JSON diagnostic reports for consumption by the self-healing loop.
"""

import argparse
import datetime
import json
import math
import os
import sys
import yaml
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from isaaclab_arena.relations.motion_clearance_engine import (
    check_cavity_containment_and_headroom,
    check_dual_revolute_clearance,
    check_object_prismatic_clearance,
    check_pedestal_prismatic_clearance,
     check_revolute_manifold_clearance,
    compute_prismatic_stroke_corridor,
    compute_revolute_swept_manifold,
)


# ---------------------------------------------------------------------------
# Kinematic Asset Specifications Database
# (Revolute doors, prismatic drawers, sliding fixtures)
# ---------------------------------------------------------------------------
KNOWN_ASSET_FOOTPRINTS = {
    "microwave": (0.293, 0.260),
    "refrigerator": (0.400, 0.350),
    "fridge": (0.400, 0.350),
    "cabinet_door": (0.250, 0.200),
    "door": (0.250, 0.200),
    "drawer": (0.250, 0.200),
    "cabinet_drawer": (0.250, 0.200),
    "tomato_soup_can": (0.035, 0.035),
    "soup_can": (0.035, 0.035),
    "can": (0.035, 0.035),
    " cracker_box": (0.080, 0.035),
    "cracker_box": (0.080, 0.035),
    "sugar_box": (0.045, 0.025),
    "mustard_bottle": (0.045, 0.035),
    "saline_bottle": (0.036, 0.036),
    "screw_top_jar": (0.036, 0.036),
    "apple": (0.040, 0.040),
    "banana": (0.100, 0.040),
    "bowl": (0.090, 0.090),
    "tray": (0.150, 0.120),
    "bin": (0.150, 0.120),
    "bottle": (0.045, 0.045),
    "mug": (0.055, 0.055),
}

KNOWN_OBJECT_HEIGHTS = {
    "cracker_box": 0.160,
    "sugar_box": 0.175,
    "tomato_soup_can": 0.102,
    "mustard_bottle": 0.190,
    "saline_bottle": 0.097,
    "screw_top_jar": 0.097,
    "mug": 0.095,
}


def get_asset_footprint_half_extents(obj_dict: dict) -> tuple[float, float]:
    """Return local (half_width, half_depth) bounding footprint extents."""
    obj_id = str(obj_dict.get("id", "")).lower()
    reg_name = str(obj_dict.get("registry_name", "")).lower()
    for key, half_extents in KNOWN_ASSET_FOOTPRINTS.items():
        if key in obj_id or key in reg_name:
            return half_extents
    return (0.05, 0.05)


KINEMATIC_ASSET_SPECS = {
    "microwave": {
        "joint_type": "revolute",
        "joint_name": "microjoint",
        "axis": [0, 0, 1],
        "limits": (0.0, 1.5708),  # 0 to 90 degrees
        "envelope_radius_m": 0.35,
        "hinge_offset": (-0.10, -0.15),
        "swing_span": (0.0, 1.5708),
        # Measured from Microwave039.usd: the door mesh bounds are y in [-0.260, -0.187]
        # on a casing spanning y in [-0.215, 0.260], so the door faces local -Y.
        "canonical_aperture_normal": (0.0, -1.0, 0.0),
        "open_task": "OpenDoorTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "refrigerator": {
        "joint_type": "revolute",
        "joint_name": "door_joint",
        "axis": [0, 0, 1],
        "limits": (0.0, 1.9198),  # 0 to 110 degrees
        "envelope_radius_m": 0.60,
        "hinge_offset": (-0.15, -0.25),
        "swing_span": (0.0, 1.9198),
        "open_task": "OpenDoorTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "fridge": {
        "joint_type": "revolute",
        "joint_name": "door_joint",
        "axis": [0, 0, 1],
        "limits": (0.0, 1.9198),
        "envelope_radius_m": 0.60,
        "hinge_offset": (-0.15, -0.25),
        "swing_span": (0.0, 1.9198),
        "open_task": "OpenDoorTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "cabinet_door": {
        "joint_type": "revolute",
        "joint_name": "hinge_joint",
        "axis": [0, 0, 1],
        "limits": (0.0, 1.5708),
        "envelope_radius_m": 0.45,
        "hinge_offset": (-0.10, -0.20),
        "swing_span": (0.0, 1.5708),
        "open_task": "OpenDoorTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "door": {
        "joint_type": "revolute",
        "joint_name": "hinge_joint",
        "axis": [0, 0, 1],
        "limits": (0.0, 1.5708),
        "envelope_radius_m": 0.45,
        "hinge_offset": (-0.10, -0.20),
        "swing_span": (0.0, 1.5708),
        "open_task": "OpenDoorTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "drawer": {
        "joint_type": "prismatic",
        "joint_name": "drawer_slide",
        "axis": [1, 0, 0],  # Forward pull
        "limits": (0.0, 0.35),  # 0 to 35 cm stroke
        "stroke_length_m": 0.35,
        "corridor_width_m": 0.40,
        "drawer_depth_m": 0.35,
        "open_task": "OpenDrawerTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "cabinet_drawer": {
        "joint_type": "prismatic",
        "joint_name": "drawer_slide",
        "axis": [1, 0, 0],
        "limits": (0.0, 0.35),
        "stroke_length_m": 0.35,
        "corridor_width_m": 0.40,
        "drawer_depth_m": 0.35,
        "open_task": "OpenDrawerTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "top_drawer": {
        "articulation_category": "intrinsic_sub_prim",
        "joint_type": "prismatic",
        "joint_name": "drawer_1",
        "axis": [0, -1, 0],
        "limits": (0.0, 0.40),
        "stroke_length_m": 0.40,
        "corridor_width_m": 0.50,
        "drawer_depth_m": 0.311,
        "canonical_aperture_normal": (0.0, -1.0, 0.0),
        "open_task": "OpenDrawerTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "kitchen_base_cabinet": {
        "articulation_category": "intrinsic_sub_prim",
        "joint_type": "prismatic",
        "joint_name": "drawer_1",
        "axis": [0, -1, 0],
        "limits": (0.0, 0.40),
        "stroke_length_m": 0.40,
        "corridor_width_m": 0.50,
        "drawer_depth_m": 0.311,
        "canonical_aperture_normal": (0.0, -1.0, 0.0),
        "open_task": "OpenDrawerTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "storage_drawer": {
        "articulation_category": "intrinsic_sub_prim",
        "joint_type": "prismatic",
        "joint_name": "joint_shelf_02_joint_00",
        "axis": [1, 0, 0],
        "limits": (0.0, 0.45),
        "stroke_length_m": 0.45,
        "corridor_width_m": 0.55,
        "drawer_depth_m": 0.34,
        "cavity_dims_m": (0.40, 0.50, 0.18),
        "canonical_aperture_normal": (1.0, 0.0, 0.0),
        "open_task": "OpenDrawerTask",
        "cavity_task": "PickAndPlaceTask",
        "close_task": "CloseDrawerTask",
    },
    "fixture_counter_a01": {
        "articulation_category": "intrinsic_sub_prim",
        "joint_type": "prismatic",
        "joint_name": "joint_shelf_02_joint_00",
        "axis": [1, 0, 0],
        "limits": (0.0, 0.45),
        "stroke_length_m": 0.45,
        "corridor_width_m": 0.55,
        "drawer_depth_m": 0.34,
        "cavity_dims_m": (0.40, 0.50, 0.18),
        "canonical_aperture_normal": (1.0, 0.0, 0.0),
        "open_task": "OpenDrawerTask",
        "cavity_task": "PickAndPlaceTask",
        "close_task": "CloseDrawerTask",
    },
    "sm_fixture_counter_a01_01": {
        "articulation_category": "intrinsic_sub_prim",
        "joint_type": "prismatic",
        "joint_name": "joint_shelf_02_joint_00",
        "axis": [1, 0, 0],
        "limits": (0.0, 0.45),
        "stroke_length_m": 0.45,
        "corridor_width_m": 0.55,
        "drawer_depth_m": 0.34,
        "cavity_dims_m": (0.40, 0.50, 0.18),
        "canonical_aperture_normal": (1.0, 0.0, 0.0),
        "open_task": "OpenDrawerTask",
        "cavity_task": "PickAndPlaceTask",
        "close_task": "CloseDrawerTask",
    },
    "cart_medical_utility": {
        "articulation_category": "intrinsic_sub_prim",
        "joint_type": "dual_revolute",
        "joint_name": "joint_bigLid_01_joint_00",
        "secondary_joint_name": "joint_bigLid_02_joint_00",
        "axis": [0, 0, 1],
        "limits": (0.0, 1.5708),
        "envelope_radius_m": 0.14,
        "hinge_offset": (-0.35, -0.15),
        "right_hinge_offset": (-0.35, 0.15),
        "swing_span": (0.0, 1.5708),
        "vertical_headroom_m": 0.32,
        "required_headroom_m": 0.20,
        "canonical_aperture_normal": (-1.0, 0.0, 0.0),
        "open_task": "OpenDoorTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "sm_cart_medical_utility_a03_01": {
        "articulation_category": "intrinsic_sub_prim",
        "joint_type": "dual_revolute",
        "joint_name": "joint_bigLid_01_joint_00",
        "secondary_joint_name": "joint_bigLid_02_joint_00",
        "axis": [0, 0, 1],
        "limits": (0.0, 1.5708),
        "envelope_radius_m": 0.14,
        "hinge_offset": (-0.35, -0.15),
        "right_hinge_offset": (-0.35, 0.15),
        "swing_span": (0.0, 1.5708),
        "vertical_headroom_m": 0.32,
        "required_headroom_m": 0.20,
        "canonical_aperture_normal": (-1.0, 0.0, 0.0),
        "open_task": "OpenDoorTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "facilityEquipment_beverageFridge_display_a01": {
        "articulation_category": "intrinsic_sub_prim",
        "joint_type": "revolute",
        "joint_name": "joint_door_01_joint_00",
        "axis": [0, 0, 1],
        "limits": (0.0, 3.124),
        "envelope_radius_m": 0.48,
        "hinge_offset": (0.21, 0.23),
        "swing_span": (0.0, 1.5708),
        "vertical_headroom_m": 0.45,
        "required_headroom_m": 0.28,
        "canonical_aperture_normal": (1.0, 0.0, 0.0),
        "open_task": "OpenDoorTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "sm_facilityEquipment_beverageFridge_display_a01_01": {
        "articulation_category": "intrinsic_sub_prim",
        "joint_type": "revolute",
        "joint_name": "joint_door_01_joint_00",
        "axis": [0, 0, 1],
        "limits": (0.0, 3.124),
        "envelope_radius_m": 0.48,
        "hinge_offset": (0.21, 0.23),
        "swing_span": (0.0, 1.5708),
        "vertical_headroom_m": 0.45,
        "required_headroom_m": 0.28,
        "canonical_aperture_normal": (1.0, 0.0, 0.0),
        "open_task": "OpenDoorTask",
        "cavity_task": "PickAndPlaceTask",
    },
    "beverage_fridge": {
        "articulation_category": "intrinsic_sub_prim",
        "joint_type": "revolute",
        "joint_name": "joint_door_01_joint_00",
        "axis": [0, 0, 1],
        "limits": (0.0, 3.124),
        "envelope_radius_m": 0.48,
        "hinge_offset": (0.21, 0.23),
        "swing_span": (0.0, 1.5708),
        "vertical_headroom_m": 0.45,
        "required_headroom_m": 0.28,
        "canonical_aperture_normal": (1.0, 0.0, 0.0),
        "open_task": "OpenDoorTask",
        "cavity_task": "PickAndPlaceTask",
    },
}


def find_articulated_spec(
    objects_list: list[dict],
    object_references: list[dict] | None = None,
    background: dict | None = None,
) -> tuple[dict | None, dict | None]:
    """Identify the articulated entity from objects, object_references, or background."""
    # First check explicit intrinsic sub-prims (object_references) paired with background
    if object_references:
        bg_reg = (background or {}).get("registry_name", "").lower()
        bg_id = (background or {}).get("id", "").lower()
        for key, spec in KINEMATIC_ASSET_SPECS.items():
            if spec.get("articulation_category") == "intrinsic_sub_prim" and (key in bg_reg or key in bg_id):
                # Find the primary openable reference (or first reference)
                primary_ref = next(
                    (
                        r
                        for r in object_references
                        if r.get("params", {}).get("openable_joint_name")
                        or r.get("object_type") == "articulation"
                    ),
                    object_references[0],
                )
                merged_ref = dict(primary_ref)
                if "params" not in merged_ref or "initial_pose" not in merged_ref.get("params", {}):
                    merged_params = dict(merged_ref.get("params", {}))
                    if background and "initial_pose" in background.get("params", {}):
                        merged_params["initial_pose"] = background["params"]["initial_pose"]
                    merged_ref["params"] = merged_params
                return merged_ref, spec

        for ref in object_references:
            ref_id = str(ref.get("id", "")).lower()
            joint_name = str(ref.get("params", {}).get("openable_joint_name", "")).lower()
            for key, spec in KINEMATIC_ASSET_SPECS.items():
                if key in ref_id or (joint_name and joint_name in str(spec.get("joint_name", "")).lower()):
                    merged_ref = dict(ref)
                    if "params" not in merged_ref or "initial_pose" not in merged_ref.get("params", {}):
                        merged_params = dict(merged_ref.get("params", {}))
                        if background and "initial_pose" in background.get("params", {}):
                            merged_params["initial_pose"] = background["params"]["initial_pose"]
                        merged_ref["params"] = merged_params
                    return merged_ref, spec

    # Next check placed objects (Type A)
    for obj in objects_list:
        obj_id = str(obj.get("id", "")).lower()
        reg_name = str(obj.get("registry_name", "")).lower()
        for key, spec in KINEMATIC_ASSET_SPECS.items():
            if key in obj_id or key in reg_name:
                return obj, spec

    # Finally check background fixture directly
    if background:
        bg_id = str(background.get("id", "")).lower()
        bg_reg = str(background.get("registry_name", "")).lower()
        for key, spec in KINEMATIC_ASSET_SPECS.items():
            if key in bg_id or key in bg_reg:
                return background, spec

    return None, None


def check_revolute_swept_clearance(
    base_x: float,
    base_y: float,
    prop_x: float,
    prop_y: float,
    spec: dict,
    prop_radius: float = 0.05,
    margin: float = 0.10,
) -> tuple[bool, float, str]:
    """Calculate Euclidean clearance between a revolute swing arc and a prop."""
    hinge_ox, hinge_oy = spec.get("hinge_offset", (-0.10, -0.15))
    door_radius = spec.get("envelope_radius_m", 0.35)

    hinge_x = base_x + hinge_ox
    hinge_y = base_y + hinge_oy

    dist_to_hinge = math.hypot(prop_x - hinge_x, prop_y - hinge_y)
    effective_swept_radius = door_radius + margin + prop_radius

    in_swing_band = (dist_to_hinge <= effective_swept_radius) and (prop_x > hinge_x - 0.05)
    clearance = dist_to_hinge - (door_radius + prop_radius)

    if in_swing_band and clearance < margin:
        return False, clearance, (
            f"Revolute door swing arc (R={door_radius:.2f}m) collides with object at ({prop_x:.2f}, {prop_y:.2f}). "
            f"Clearance {clearance:.3f}m < required {margin:.2f}m margin."
        )
    return True, max(clearance, margin), "Clearance verified."


def check_prismatic_corridor_clearance(
    base_x: float,
    base_y: float,
    prop_x: float,
    prop_y: float,
    spec: dict,
    prop_radius: float = 0.05,
    margin: float = 0.10,
) -> tuple[bool, float, str]:
    """Calculate Euclidean clearance between a prismatic drawer pull corridor and a prop."""
    stroke = spec.get("stroke_length_m", 0.35)
    half_width = (spec.get("corridor_width_m", 0.40) / 2.0) + margin + prop_radius

    # Forward pull along +X from base_x to base_x + stroke + margin
    x_in_corridor = (base_x <= prop_x <= base_x + stroke + margin + prop_radius)
    y_in_corridor = (abs(prop_y - base_y) <= half_width)

    if x_in_corridor and y_in_corridor:
        clearance_x = (base_x + stroke + margin + prop_radius) - prop_x
        clearance_y = half_width - abs(prop_y - base_y)
        min_penetration = min(clearance_x, clearance_y)
        return False, -min_penetration, (
            f"Prismatic drawer opening corridor (stroke={stroke:.2f}m, width={spec.get('corridor_width_m', 0.40):.2f}m) "
            f"is blocked by object at ({prop_x:.2f}, {prop_y:.2f}). Penetration: {min_penetration:.3f}m."
        )
    dist_outside = max(0.0, abs(prop_y - base_y) - half_width)
    return True, max(dist_outside, margin), "Clearance verified."


def yaw_from_quat(q: list[float]) -> float:
    """Extract yaw angle (rotation about Z in radians) from quaternion [x, y, z, w]."""
    qx, qy, qz, qw = q
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    return math.atan2(siny_cosp, cosy_cosp)


def check_2d_footprint_overlap(
    pos_a: list[float] | tuple[float, float],
    yaw_a: float,
    half_extents_a: tuple[float, float],
    pos_b: list[float] | tuple[float, float],
    yaw_b: float,
    half_extents_b: tuple[float, float],
    margin: float = 0.05,
) -> tuple[bool, float, str]:
    """Check 2D oriented bounding box (OBB) clearance using Separating Axis Theorem (SAT).

    Args:
        pos_a: (x, y) center of object A.
        yaw_a: Yaw rotation of object A in radians.
        half_extents_a: (half_width, half_depth) in object A local frame.
        pos_b: (x, y) center of object B.
        yaw_b: Yaw rotation of object B in radians.
        half_extents_b: (half_width, half_depth) in object B local frame.
        margin: Minimum clearance required between footprints in meters.

    Returns:
        (is_separated, clearance, message)
        is_separated: True if footprints are separated by at least margin.
        clearance: Max clearance across test axes (> 0 means separated, < 0 means penetration).
    """
    dx = pos_b[0] - pos_a[0]
    dy = pos_b[1] - pos_a[1]

    # Local unit axes for A
    cos_a, sin_a = math.cos(yaw_a), math.sin(yaw_a)
    ax1 = (cos_a, sin_a)
    ax2 = (-sin_a, cos_a)

    # Local unit axes for B
    cos_b, sin_b = math.cos(yaw_b), math.sin(yaw_b)
    bx1 = (cos_b, sin_b)
    bx2 = (-sin_b, cos_b)

    axes = [ax1, ax2, bx1, bx2]
    clearances = []

    for ux, uy in axes:
        dist = abs(dx * ux + dy * uy)
        ra = half_extents_a[0] * abs(ax1[0] * ux + ax1[1] * uy) + half_extents_a[1] * abs(ax2[0] * ux + ax2[1] * uy)
        rb = half_extents_b[0] * abs(bx1[0] * ux + bx1[1] * uy) + half_extents_b[1] * abs(bx2[0] * ux + bx2[1] * uy)
        c = dist - (ra + rb + margin)
        clearances.append(c)

    best_clearance = max(clearances)
    if best_clearance >= 0.0:
        return True, best_clearance, "Footprint clearance verified."

    penetration = -best_clearance
    return False, best_clearance, f"Bounding footprints overlap (penetration: {penetration:.3f}m, margin: {margin:.2f}m)."



def quat_rotate(q: list[float], v: list[float]) -> list[float]:
    """Rotate 3D vector v by the quaternion q = [x, y, z, w]."""
    qx, qy, qz, qw = q
    vx, vy, vz = v
    tx = 2.0 * (qy * vz - qz * vy)
    ty = 2.0 * (qz * vx - qx * vz)
    tz = 2.0 * (qx * vy - qy * vx)
    return [
        vx + qw * tx + (qy * tz - qz * ty),
        vy + qw * ty + (qz * tx - qx * tz),
        vz + qw * tz + (qx * ty - qy * tx),
    ]


def effective_orientation(obj: dict, relations: list[dict]) -> list[float]:
    """Return the quaternion [x, y, z, w] the simulator applies to an object.

    Objects with an 'on' relation are placed by the relation solver, which discards the spec's
    initial_pose rotation. Only a 'rotate_around_solution' relation (yaw_rad) rotates them.
    Objects without an 'on' relation keep their initial_pose rotation.
    """
    obj_id = obj.get("id")
    own = [r for r in relations if r.get("subject") == obj_id]
    if any(r.get("kind") == "on" for r in own):
        yaw = sum(
            float(r.get("params", {}).get("yaw_rad", 0.0)) for r in own if r.get("kind") == "rotate_around_solution"
        )
        return [0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)]
    return list(obj.get("params", {}).get("initial_pose", {}).get("rotation_xyzw", [0.0, 0.0, 0.0, 1.0]))


def check_affordance_facing(
    robot_pos: list[float],
    art_pos: list[float],
    art_quat: list[float],
    canonical_aperture_normal: list[float],
    min_alignment: float = -0.70,
) -> tuple[bool, float, list[float], str, list[float]]:
    """Check that the articulated object's aperture faces the robot base in the XY plane.

    The alignment is the dot product of the world aperture normal and the unit vector from
    the robot to the object, so -1.0 means the aperture points straight at the robot.

    Returns:
        (is_valid, alignment, world_aperture_normal, message, recommended_quat_xyzw)
    """
    dx, dy = art_pos[0] - robot_pos[0], art_pos[1] - robot_pos[1]
    dist = math.hypot(dx, dy)
    world_norm = quat_rotate(art_quat, list(canonical_aperture_normal))
    if dist < 1e-4:
        return True, -1.0, world_norm, "Robot and asset colocated.", list(art_quat)

    u_app = (dx / dist, dy / dist)
    alignment = world_norm[0] * u_app[0] + world_norm[1] * u_app[1]
    if alignment <= min_alignment:
        return True, alignment, world_norm, f"Aperture facing verified (alignment = {alignment:.2f}).", list(art_quat)

    # The aperture must point along -u_app; solve for the yaw that maps the canonical normal onto it.
    required_yaw = math.atan2(-u_app[1], -u_app[0]) - math.atan2(
        canonical_aperture_normal[1], canonical_aperture_normal[0]
    )
    rec_quat = [0.0, 0.0, round(math.sin(required_yaw / 2.0), 4), round(math.cos(required_yaw / 2.0), 4)]
    msg = (
        f"Aperture normal {[round(x, 2) for x in world_norm]} does not face the robot "
        f"(alignment = {alignment:.2f} > {min_alignment:.2f}); the object faces sideways or away."
    )
    return False, alignment, world_norm, msg, rec_quat


# ---------------------------------------------------------------------------
# Known Fixture Tabletop Specifications Database
# (raw unshifted tabletop height, nominal surface height, calibration offset)
# ---------------------------------------------------------------------------
KNOWN_FIXTURE_TABLETOP_HEIGHTS = {
    # office_table_background: table.usd scaled (1.0, 1.0, 0.7) has physical surface at Z=0.5306m when grounded at Z=0.
    "office_table_background": {
        "raw_tabletop_z": 0.5306,
        "ground_required": True,
        "footprint_half_extents": (0.901, 0.401),
        "canonical_approach_normal": [0.0, -1.0, 0.0],
    },
    "office_table": {
        "raw_tabletop_z": 0.5306,
        "ground_required": True,
        "footprint_half_extents": (0.901, 0.401),
        "canonical_approach_normal": [0.0, -1.0, 0.0],
    },
    "table_oak_robolab": {
        "raw_tabletop_z": 0.75,
        "ground_required": True,
        "footprint_half_extents": (0.60, 0.40),
        "canonical_approach_normal": [0.0, -1.0, 0.0],
    },
    "table": {
        "raw_tabletop_z": 0.75,
        "ground_required": True,
        "footprint_half_extents": (0.60, 0.40),
        "canonical_approach_normal": [0.0, -1.0, 0.0],
    },
    "packing_table": {
        "raw_tabletop_z": 0.75,
        "ground_required": True,
        "footprint_half_extents": (0.60, 0.40),
        "canonical_approach_normal": [0.0, -1.0, 0.0],
    },
    "kitchen": {
        "raw_tabletop_z": 0.75,
        "ground_required": True,
        "footprint_half_extents": (0.80, 0.40),
        "canonical_approach_normal": [0.0, -1.0, 0.0],
    },
    "kitchen_background": {
        "raw_tabletop_z": 0.75,
        "ground_required": True,
        "footprint_half_extents": (0.80, 0.40),
        "canonical_approach_normal": [0.0, -1.0, 0.0],
    },
    "kitchen_base_cabinet": {
        "raw_tabletop_z": 0.908,
        "ground_required": True,
        "footprint_half_extents": (0.30, 0.311),
        "canonical_approach_normal": [0.0, -1.0, 0.0],
        "sub_surface_heights": [0.65, 0.908],
    },
    "kitchen_base_cabinet.usda": {
        "raw_tabletop_z": 0.908,
        "ground_required": True,
        "footprint_half_extents": (0.30, 0.311),
        "canonical_approach_normal": [0.0, -1.0, 0.0],
        "sub_surface_heights": [0.65, 0.908],
    },
    "fixture_counter_a01": {
        "raw_tabletop_z": 0.9271,
        "ground_required": True,
        "footprint_half_extents": (0.34, 0.90),
        "canonical_approach_normal": [1.0, 0.0, 0.0],
        "sub_surface_heights": [0.65, 0.90, 0.9271],
    },
    "sm_fixture_counter_a01_01": {
        "raw_tabletop_z": 0.9271,
        "ground_required": True,
        "footprint_half_extents": (0.34, 0.90),
        "canonical_approach_normal": [1.0, 0.0, 0.0],
        "sub_surface_heights": [0.65, 0.90, 0.9271],
    },
    "sm_fixture_counter_a01_01.usd": {
        "raw_tabletop_z": 0.9271,
        "ground_required": True,
        "footprint_half_extents": (0.34, 0.90),
        "canonical_approach_normal": [1.0, 0.0, 0.0],
        "sub_surface_heights": [0.65, 0.90, 0.9271],
    },
    "cart_medical_utility": {
        "raw_tabletop_z": 0.9109,
        "ground_required": True,
        "footprint_half_extents": (0.37, 0.26),
        "canonical_approach_normal": [-1.0, 0.0, 0.0],
        "sub_surface_heights": [0.45, 0.85, 0.9109],
    },
    "sm_cart_medical_utility_a03_01": {
        "raw_tabletop_z": 0.9109,
        "ground_required": True,
        "footprint_half_extents": (0.37, 0.26),
        "canonical_approach_normal": [-1.0, 0.0, 0.0],
        "sub_surface_heights": [0.45, 0.85, 0.9109],
    },
    "sm_cart_medical_utility_a03_01.usd": {
        "raw_tabletop_z": 0.9109,
        "ground_required": True,
        "footprint_half_extents": (0.37, 0.26),
        "canonical_approach_normal": [-1.0, 0.0, 0.0],
        "sub_surface_heights": [0.45, 0.85, 0.9109],
    },
    "facilityEquipment_beverageFridge_display_a01": {
        "raw_tabletop_z": 0.8652,
        "ground_required": True,
        "footprint_half_extents": (0.23, 0.25),
        "canonical_approach_normal": [1.0, 0.0, 0.0],
        "sub_surface_heights": [0.25, 0.50, 0.70, 0.8652],
    },
    "sm_facilityEquipment_beverageFridge_display_a01_01": {
        "raw_tabletop_z": 0.8652,
        "ground_required": True,
        "footprint_half_extents": (0.23, 0.25),
        "canonical_approach_normal": [1.0, 0.0, 0.0],
        "sub_surface_heights": [0.25, 0.50, 0.70, 0.8652],
    },
    "sm_facilityEquipment_beverageFridge_display_a01_01.usd": {
        "raw_tabletop_z": 0.8652,
        "ground_required": True,
        "footprint_half_extents": (0.23, 0.25),
        "canonical_approach_normal": [1.0, 0.0, 0.0],
        "sub_surface_heights": [0.25, 0.50, 0.70, 0.8652],
    },
    "beverage_fridge": {
        "raw_tabletop_z": 0.8652,
        "ground_required": True,
        "footprint_half_extents": (0.23, 0.25),
        "canonical_approach_normal": [1.0, 0.0, 0.0],
        "sub_surface_heights": [0.25, 0.50, 0.70, 0.8652],
    },
}


def check_fixture_standoff_and_elevation(
    emb_cfg: dict,
    bg_cfg: dict,
    reified_relations: list[dict] | None = None,
    objects_list: list[dict] | None = None,
    relations: list[dict] | None = None,
) -> tuple[bool, list[dict], list[str]]:
    """Validate horizontal standoff distance, orientation, and tabletop elevation alignment (Pass 6).

    Checks:
    1. Robot-fixture pedestal clearance: SAT 2D OBB clearance >= 0.05m to prevent pedestal embedding.
    2. Fixture approach orientation: Working edge normal faces robot approach vector (alignment >= 0.50).
    3. Horizontal standoff distance: sqrt(dx^2 + dy^2) in [0.50, 1.20]m (SHACL Rule 6).
    4. Physical ground contact: Floor-standing fixture base must rest at Z_base = 0.0m (tolerance 0.005m).
    5. Workspace kinematic reachability: Tabletop deck height falls within manipulator reachable vertical window.
    6. Manipuland support height consistency: reified delta_z.nominal matches effective tabletop surface (within 0.02m).

    Returns:
        tuple[bool, list[dict], list[str]]: (pass_ok, defects, diagnostics)
    """
    defects = []
    diagnostics = []
    pass_ok = True

    if not bg_cfg:
        diagnostics.append("Pass 6: No background fixture registered; standoff and elevation skipped.")
        return True, defects, diagnostics

    emb_reg = emb_cfg.get("registry_name", "").lower()
    is_mobile = any(m in emb_reg for m in ["g1", "humanoid", "fetch", "mobile", "gr1", "unitree"])
    if is_mobile:
        diagnostics.append(f"Pass 6: Mobile embodiment '{emb_reg}'; standoff and elevation unconstrained.")
        return True, defects, diagnostics

    # Extract robot pose
    emb_params = emb_cfg.get("params", {})
    robot_pose = emb_params.get("initial_pose", {})
    robot_pos = robot_pose.get("position_xyz", [-0.65, 0.0, 0.75])
    rx, ry = float(robot_pos[0]), float(robot_pos[1])
    rz = float(robot_pos[2]) if len(robot_pos) > 2 else 0.75
    robot_rot = robot_pose.get("rotation_xyzw", [0.0, 0.0, 0.0, 1.0])
    robot_yaw = yaw_from_quat(robot_rot)

    # Extract fixture pose & specs
    bg_id = bg_cfg.get("id", "background")
    bg_reg = bg_cfg.get("registry_name", "").lower()
    bg_params = bg_cfg.get("params", {})
    bg_pose = bg_params.get("initial_pose", {})
    bg_pos = bg_pose.get("position_xyz", [0.0, 0.0, 0.0])
    bx, by = float(bg_pos[0]), float(bg_pos[1])
    bz = float(bg_pos[2]) if len(bg_pos) > 2 else 0.0
    bg_rot = bg_pose.get("rotation_xyzw", [0.0, 0.0, 0.0, 1.0])
    bg_yaw = yaw_from_quat(bg_rot)

    # Determine fixture specifications
    fixture_info = KNOWN_FIXTURE_TABLETOP_HEIGHTS.get(bg_reg) or KNOWN_FIXTURE_TABLETOP_HEIGHTS.get(bg_id.lower())
    if not fixture_info:
        raw_tabletop_z = 0.75
        ground_required = True
        footprint_half_extents = (0.60, 0.40)
        app_normal = [0.0, -1.0, 0.0]
    else:
        raw_tabletop_z = fixture_info["raw_tabletop_z"]
        ground_required = fixture_info.get("ground_required", True)
        footprint_half_extents = fixture_info.get("footprint_half_extents", (0.901, 0.401))
        app_normal = fixture_info.get("canonical_approach_normal", [0.0, -1.0, 0.0])

    effective_tabletop_z = raw_tabletop_z + bz

    # Check 1: Robot-to-Fixture Pedestal Clearance (2D OBB SAT Collision)
    is_separated, clearance, _ = check_2d_footprint_overlap(
        pos_a=(rx, ry),
        yaw_a=robot_yaw,
        half_extents_a=(0.30, 0.30),
        pos_b=(bx, by),
        yaw_b=bg_yaw,
        half_extents_b=footprint_half_extents,
        margin=0.05,
    )
    if not is_separated:
        pass_ok = False
        defects.append({
            "code": "DEFECT_ROBOT_FIXTURE_COLLISION",
            "robot_pos_xy": [round(rx, 3), round(ry, 3)],
            "fixture_pos_xy": [round(bx, 3), round(by, 3)],
            "penetration_depth_m": round(-clearance, 3),
            "message": (
                f"Robot pedestal at ({rx:.2f}, {ry:.2f}) collides with fixture '{bg_id}' footprint "
                f"(penetration: {-clearance:.3f}m). Fixture extends "
                f"{footprint_half_extents[0]*2:.2f}m x {footprint_half_extents[1]*2:.2f}m."
            ),
            "remediation": (
                f"Rotate fixture '{bg_id}' by 90 deg (yaw = -1.5708) to align narrow depth along approach corridor, "
                f"or translate fixture to achieve >= 0.05m clearance."
            ),
        })
    else:
        diagnostics.append(f"Pass 6: Robot-to-fixture pedestal clearance verified (clearance = {clearance:.3f}m >= 0.05m).")

    # Check 2: Fixture Canonical Approach Orientation
    cos_by, sin_by = math.cos(bg_yaw), math.sin(bg_yaw)
    rot_nx = app_normal[0] * cos_by - app_normal[1] * sin_by
    rot_ny = app_normal[0] * sin_by + app_normal[1] * cos_by

    to_robot_x = rx - bx
    to_robot_y = ry - by
    to_robot_dist = math.sqrt(to_robot_x ** 2 + to_robot_y ** 2)
    if to_robot_dist > 1e-4:
        ux = to_robot_x / to_robot_dist
        uy = to_robot_y / to_robot_dist
        approach_alignment = rot_nx * ux + rot_ny * uy
        if approach_alignment < 0.50:
            pass_ok = False
            defects.append({
                "code": "DEFECT_FIXTURE_ORIENTATION_MISALIGNED",
                "fixture_id": bg_id,
                "fixture_yaw_rad": round(bg_yaw, 4),
                "approach_alignment": round(approach_alignment, 3),
                "message": (
                    f"Fixture '{bg_id}' working edge does not face the robot (alignment = {approach_alignment:.2f} < 0.50). "
                    f"Approach normal [{rot_nx:.2f}, {rot_ny:.2f}] is directed away from robot at ({rx:.2f}, {ry:.2f})."
                ),
                "remediation": (
                    f"Rotate fixture '{bg_id}' (e.g. yaw = -1.5708) so its canonical approach corridor faces the robot."
                ),
            })
        else:
            diagnostics.append(
                f"Pass 6: Fixture '{bg_id}' approach orientation verified (alignment = {approach_alignment:.2f} >= 0.50)."
            )

    # Check 3: Horizontal Standoff Distance (SHACL Rule 6: 0.50m - 1.20m)
    standoff_dist = math.sqrt((rx - bx) ** 2 + (ry - by) ** 2)
    MIN_STANDOFF = 0.50
    MAX_STANDOFF = 1.20

    if standoff_dist < MIN_STANDOFF:
        pass_ok = False
        defects.append({
            "code": "DEFECT_STANDOFF_DISTANCE_TOO_CLOSE",
            "standoff_distance_m": round(standoff_dist, 3),
            "min_standoff_m": MIN_STANDOFF,
            "message": f"Robot-to-fixture horizontal standoff distance {standoff_dist:.2f}m is too close (< min {MIN_STANDOFF:.2f}m). Robot base/pedestal collides with fixture frame.",
            "remediation": f"Increase horizontal standoff between embodiment and '{bg_id}' to >= {MIN_STANDOFF:.2f}m (target: 0.65m - 0.85m)."
        })
    elif standoff_dist > MAX_STANDOFF:
        pass_ok = False
        defects.append({
            "code": "DEFECT_STANDOFF_DISTANCE_TOO_FAR",
            "standoff_distance_m": round(standoff_dist, 3),
            "max_standoff_m": MAX_STANDOFF,
            "message": f"Robot-to-fixture horizontal standoff distance {standoff_dist:.2f}m exceeds kinematic reach envelope (> max {MAX_STANDOFF:.2f}m). Manipulator cannot reach workspace.",
            "remediation": f"Decrease horizontal standoff between embodiment and '{bg_id}' to <= {MAX_STANDOFF:.2f}m (target: 0.65m - 0.85m)."
        })
    else:
        diagnostics.append(f"Pass 6: Robot-to-fixture horizontal standoff verified ({standoff_dist:.2f}m in [{MIN_STANDOFF:.2f}, {MAX_STANDOFF:.2f}]m).")

    # Check 4: Physical Ground Contact (Digital Twin Grounding Rule: Z_base = 0.0m)
    GROUNDING_TOLERANCE = 0.005
    if ground_required and abs(bz) > GROUNDING_TOLERANCE:
        pass_ok = False
        defects.append({
            "code": "DEFECT_FIXTURE_NOT_GROUNDED",
            "fixture_id": bg_id,
            "fixture_z": round(bz, 4),
            "tolerance_m": GROUNDING_TOLERANCE,
            "message": (
                f"Floor fixture '{bg_id}' has non-zero Z coordinate (Z = {bz:.4f}m). "
                f"Digital Twin physical grounding invariant mandates Z_base = 0.0m."
            ),
            "remediation": f"Set background.params.initial_pose.position_xyz to [{bx:.1f}, {by:.1f}, 0.0]."
        })
    else:
        diagnostics.append(f"Pass 6: Fixture '{bg_id}' physical floor grounding verified (Z_base = {bz:.4f}m).")

    # Check 5: Workspace Kinematic Reachability Envelope
    MIN_REACH_Z = rz - 0.45
    MAX_REACH_Z = rz + 0.20
    if not (MIN_REACH_Z <= effective_tabletop_z <= MAX_REACH_Z):
        pass_ok = False
        defects.append({
            "code": "DEFECT_TABLETOP_KINEMATICALLY_UNREACHABLE",
            "effective_tabletop_z": round(effective_tabletop_z, 3),
            "robot_stand_z": round(rz, 3),
            "reachable_z_envelope": [round(MIN_REACH_Z, 3), round(MAX_REACH_Z, 3)],
            "message": (
                f"Tabletop surface height ({effective_tabletop_z:.3f}m) falls outside the robot workspace envelope "
                f"[{MIN_REACH_Z:.2f}m, {MAX_REACH_Z:.2f}m] for robot stand height {rz:.2f}m."
            ),
            "remediation": f"Select a fixture whose deck height is within [{MIN_REACH_Z:.2f}m, {MAX_REACH_Z:.2f}m] or adjust robot stand height."
        })
    else:
        diagnostics.append(
            f"Pass 6: Tabletop elevation kinematically reachable (effective surface = {effective_tabletop_z:.3f}m "
            f"in [{MIN_REACH_Z:.2f}m, {MAX_REACH_Z:.2f}m] for robot stand = {rz:.3f}m)."
        )

    # Check 6: Manipuland Support Height Consistency
    # Objects resting on a surface have their centroid at level_z + h/2 (e.g. 0.908m deck + 0.051m = 0.959m).
    # Allowed range covers surface level up to surface level + object half-extent (0.075m tolerance).
    MANIPULAND_TOLERANCE = 0.075
    allowed_z_levels = [effective_tabletop_z]
    if fixture_info and "sub_surface_heights" in fixture_info:
        allowed_z_levels.extend(h + bz for h in fixture_info["sub_surface_heights"])
    if reified_relations:
        for rr in reified_relations:
            src_id = rr.get("source_id", "object")
            delta_z_cfg = rr.get("delta_z", {})
            if isinstance(delta_z_cfg, dict) and "nominal" in delta_z_cfg:
                nominal_z = float(delta_z_cfg["nominal"])
                if not any(abs(level_z - nominal_z) <= MANIPULAND_TOLERANCE or (0.0 <= nominal_z - level_z <= MANIPULAND_TOLERANCE) for level_z in allowed_z_levels):
                    pass_ok = False
                    defects.append({
                        "code": "DEFECT_MANIPULAND_ELEVATION_MISMATCH",
                        "source_id": src_id,
                        "reified_nominal_z": round(nominal_z, 3),
                        "effective_tabletop_z": round(effective_tabletop_z, 3),
                        "message": (
                            f"Manipuland '{src_id}' reified delta_z ({nominal_z:.3f}m) mismatches supporting "
                            f"fixture surface deck height ({effective_tabletop_z:.3f}m)."
                        ),
                        "remediation": f"Set reified_relations delta_z for '{src_id}' to nominal = {effective_tabletop_z:.3f}m (surface) or {effective_tabletop_z + 0.051:.3f}m (seated centroid)."
                    })
    if objects_list and relations:
        bg_id = bg_cfg.get("id", "background")
        for rel in relations:
            if rel.get("kind") == "on" and rel.get("reference") == bg_id:
                subj = rel.get("subject")
                matched_obj = next((o for o in objects_list if o.get("id") == subj), None)
                if matched_obj:
                    pos = matched_obj.get("params", {}).get("initial_pose", {}).get("position_xyz")
                    if pos and len(pos) > 2:
                        nom_z = float(pos[2])
                        if not any(abs(level_z - nom_z) <= MANIPULAND_TOLERANCE or (0.0 <= nom_z - level_z <= MANIPULAND_TOLERANCE) for level_z in allowed_z_levels):
                            pass_ok = False
                            defects.append({
                                "code": "DEFECT_MANIPULAND_ELEVATION_MISMATCH",
                                "source_id": subj,
                                "reified_nominal_z": round(nom_z, 3),
                                "effective_tabletop_z": round(effective_tabletop_z, 3),
                                "message": (
                                    f"Manipuland '{subj}' initial_pose Z ({nom_z:.3f}m) mismatches supporting "
                                    f"fixture surface deck height ({effective_tabletop_z:.3f}m)."
                                ),
                                "remediation": f"Set initial_pose Z for '{subj}' to nominal = {effective_tabletop_z:.3f}m (surface) or {effective_tabletop_z + 0.051:.3f}m (seated centroid)."
                            })

    return pass_ok, defects, diagnostics


def verify_spec(spec_path: str, usd_path: str = None) -> dict:
    report = {
        "spec_path": spec_path,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "conforms": True,
        "passes": {},
        "defects": [],
        "diagnostics": []
    }

    if not os.path.exists(spec_path):
        report["conforms"] = False
        report["defects"].append({"code": "FILE_NOT_FOUND", "message": f"Spec file not found: {spec_path}"})
        return report

    with open(spec_path, "r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except Exception as e:
            report["conforms"] = False
            report["defects"].append({"code": "YAML_PARSE_ERROR", "message": str(e)})
            return report

    # -------------------------------------------------------------
    # Pass 1: Schema & Graph Integrity
    # -------------------------------------------------------------
    required_keys = ["embodiment", "background", "objects", "task"]
    missing_keys = [k for k in required_keys if k not in data]
    if missing_keys:
        report["passes"]["pass1_schema"] = False
        report["defects"].append({"code": "SCHEMA_KEY_MISSING", "message": f"Missing keys: {missing_keys}"})
    else:
        report["passes"]["pass1_schema"] = True
        report["diagnostics"].append(
            f"Pass 1: Schema integrity verified ({len(data.get('objects', []))} objects, "
            f"{len(data.get('object_references', []))} object_references registered)."
        )

    # -------------------------------------------------------------
    # Pass 2: USD Kinematic Ground-Truth & Dual-Ontology SHACL Checks
    # -------------------------------------------------------------
    objects_list = data.get("objects", [])
    object_references = data.get("object_references", [])
    bg_cfg = data.get("background", {})
    relations = data.get("relations", [])

    art_obj, art_spec = find_articulated_spec(
        objects_list=objects_list,
        object_references=object_references,
        background=bg_cfg,
    )
    pass2_ok = True
    if not art_obj or not art_spec:
        pass2_ok = False
        report["defects"].append({
            "code": "NO_ARTICULATED_OBJECT",
            "message": "No recognized articulated asset found in objects, object_references, or background."
        })
    else:
        joint_name = art_spec["joint_name"]
        joint_type = art_spec["joint_type"]
        limits = art_spec["limits"]
        axis = art_spec["axis"]
        report["diagnostics"].append(
            f"Pass 2: USD kinematics verified for '{art_obj.get('id')}' (type: {joint_type}, joint: '{joint_name}', limits: {limits}, axis: {axis})."
        )

        # Dual-Ontology SHACL check: Type B intrinsic sub-prims must not have 'on' placement relations
        ref_ids = {r.get("id") for r in object_references if r.get("id")}
        for obj in objects_list:
            oid = obj.get("id")
            if obj.get("is_intrinsic_component") or obj.get("parent_id"):
                ref_ids.add(oid)
        for rel in relations:
            if rel.get("kind") == "on" and rel.get("subject") in ref_ids:
                pass2_ok = False
                report["defects"].append({
                    "code": "DEFECT_INTRINSIC_ARTICULATION_CONFLATION",
                    "object": rel.get("subject"),
                    "message": (
                        f"Intrinsic articulated sub-prim '{rel.get('subject')}' is bound to its parent fixture "
                        f"via USD joint hierarchy and MUST NOT have a spatial 'on' placement relation."
                    ),
                    "remediation": f"Remove 'kind: on' relation for '{rel.get('subject')}' and declare it under 'object_references'."
                })

        # Dual-Ontology SHACL check: Type A placed articulated prop must have an 'on' relation when relations/background exist
        is_type_a_prop = any(o.get("id") == art_obj.get("id") for o in objects_list) and art_obj.get("id") not in ref_ids
        if is_type_a_prop and bg_cfg and relations:
            has_on_rel = any(r.get("kind") == "on" and r.get("subject") == art_obj.get("id") for r in relations)
            if not has_on_rel:
                pass2_ok = False
                report["defects"].append({
                    "code": "DEFECT_UNSUPPORTED_ARTICULATED_PROP",
                    "object": art_obj.get("id"),
                    "message": f"Placed articulated prop '{art_obj.get('id')}' lacks a supporting 'kind: on' relation on a fixture.",
                    "remediation": f"Add a 'kind: on' relation with subject '{art_obj.get('id')}' and reference '{bg_cfg.get('id', 'background')}'."
                })

    report["passes"]["pass2_kinematics"] = pass2_ok

    # -------------------------------------------------------------
    # Pass 3: 3D Euclidean Swept Envelope Collision & 2D Footprint Clearance
    # -------------------------------------------------------------
    base_x, base_y = 0.0, 0.0
    if bg_cfg and "initial_pose" in bg_cfg.get("params", {}):
        bg_pos_xyz = bg_cfg["params"]["initial_pose"].get("position_xyz", [0.0, 0.0, 0.0])
        base_x, base_y = float(bg_pos_xyz[0]), float(bg_pos_xyz[1])
    else:
        base_x, base_y = 0.15, 0.0  # Nominal tabletop center fallback

    art_id = art_obj.get("id", "microwave") if art_obj else "microwave"
    for rr in data.get("reified_relations", []):
        if rr.get("source_id") == art_id:
            base_x = rr.get("delta_x", {}).get("nominal", base_x)
            base_y = rr.get("delta_y", {}).get("nominal", base_y)

    pass3_ok = True
    if art_spec:
        # Collect targets that are *inside* the articulated cavity/shelf so they are not flagged as external obstacles
        internal_target_ids = {art_id}
        for ref in object_references:
            if ref.get("id"):
                internal_target_ids.add(ref.get("id"))
        if bg_cfg.get("id") and art_spec.get("articulation_category") == "intrinsic_sub_prim":
            # Only objects explicitly placed on the outer deck (or without target_id in internal_target_ids) are checked
            pass

        for rr in data.get("reified_relations", []):
            src = rr.get("source_id")
            tgt = rr.get("target_id")
            if src != art_id and "delta_x" in rr and "delta_y" in rr:
                # If the manipuland is stowed inside the drawer/cabinet cavity itself, skip external corridor collision
                if tgt in {r.get("id") for r in object_references if r.get("id")}:
                    report["diagnostics"].append(
                        f"Pass 3: '{src}' is stowed inside intrinsic sub-prim '{tgt}'; external swept collision skipped."
                    )
                    continue

                prop_x = float(rr["delta_x"].get("nominal", 0.0))
                prop_y = float(rr["delta_y"].get("nominal", 0.0))

                if art_spec["joint_type"] == "revolute":
                    ok, clearance, msg = check_revolute_swept_clearance(base_x, base_y, prop_x, prop_y, art_spec)
                    hinge_oy = art_spec.get("hinge_offset", (-0.10, -0.15))[1]
                    door_radius = art_spec.get("envelope_radius_m", 0.35)
                    margin = 0.10
                    hinge_y = base_y + hinge_oy
                    prop_radius = 0.05
                    min_pos_y = hinge_y + door_radius + margin + prop_radius
                    max_neg_y = hinge_y - door_radius - margin - prop_radius
                    remediation = (
                        f"Shift '{src}' Y-coordinate to >= {min_pos_y:.2f}m (e.g. {min_pos_y:.2f}m) "
                        f"or <= {max_neg_y:.2f}m to place safely outside door swing arc."
                    )
                elif art_spec["joint_type"] == "dual_revolute":
                    left_m = compute_revolute_swept_manifold(
                        base_pos=(base_x, base_y, 0.0),
                        base_yaw_rad=-math.pi / 2.0,
                        hinge_offset_local=art_spec.get("hinge_offset", (-0.10, -0.35)),
                        door_radius_m=art_spec.get("envelope_radius_m", 0.30),
                        swing_span_rad=art_spec.get("swing_span", (0.0, 1.5708)),
                    )
                    right_m = compute_revolute_swept_manifold(
                        base_pos=(base_x, base_y, 0.0),
                        base_yaw_rad=-math.pi / 2.0,
                        hinge_offset_local=art_spec.get("right_hinge_offset", (-0.10, 0.35)),
                        door_radius_m=art_spec.get("envelope_radius_m", 0.30),
                        swing_span_rad=(-1.5708, 0.0),
                    )
                    ok_l, cl_l, msg_l = check_revolute_manifold_clearance(left_m, (prop_x, prop_y), prop_radius_m=0.05, margin_m=0.10)
                    ok_r, cl_r, msg_r = check_revolute_manifold_clearance(right_m, (prop_x, prop_y), prop_radius_m=0.05, margin_m=0.10)
                    ok = ok_l and ok_r
                    clearance = min(cl_l, cl_r)
                    msg = msg_l if not ok_l else msg_r
                    remediation = f"Place '{src}' outside dual-door swept wedges (|Y| >= 0.85m or on top tray)."
                else:  # prismatic
                    ok, clearance, msg = check_prismatic_corridor_clearance(base_x, base_y, prop_x, prop_y, art_spec)
                    remediation = f"Shift '{src}' lateral position to outside drawer width (|Y - {base_y:.2f}| > {art_spec.get('corridor_width_m', 0.4)/2 + 0.1:.2f}m)."

                if not ok:
                    pass3_ok = False
                    report["defects"].append({
                        "code": "SWEPT_VOLUME_COLLISION",
                        "object": src,
                        "clearance_m": clearance,
                        "message": msg,
                        "remediation": remediation
                    })
                else:
                    report["diagnostics"].append(f"Pass 3: Envelope clearance for '{src}' verified ({clearance:.3f}m >= 0.10m).")

        # Pass 3c: Prismatic Pedestal Corridor, Cavity Headroom & Dual-Revolute Checks via motion_clearance_engine
        emb_cfg = data.get("embodiment", {})
        emb_reg = emb_cfg.get("registry_name", "").lower()
        is_mobile = any(m in emb_reg for m in ["g1", "humanoid", "fetch", "mobile", "gr1", "unitree"])
        if not is_mobile and bg_cfg and art_spec["joint_type"] == "prismatic":
            robot_pose = emb_cfg.get("params", {}).get("initial_pose", {})
            r_pos = robot_pose.get("position_xyz", [-0.80, 0.0, 0.75])
            r_rot = robot_pose.get("rotation_xyzw", [0.0, 0.0, 0.0, 1.0])
            r_yaw = yaw_from_quat(r_rot)
            bg_pose = bg_cfg.get("params", {}).get("initial_pose", {})
            b_pos = bg_pose.get("position_xyz", [0.0, 0.0, 0.0])
            b_rot = bg_pose.get("rotation_xyzw", [0.0, 0.0, 0.0, 1.0])
            b_yaw = yaw_from_quat(b_rot)

            corridor = compute_prismatic_stroke_corridor(
                fixture_pos=(float(b_pos[0]), float(b_pos[1]), float(b_pos[2]) if len(b_pos) > 2 else 0.0),
                fixture_yaw_rad=b_yaw,
                slide_axis_local=(0.0, -1.0),
                stroke_length_m=float(art_spec.get("stroke_length_m", 0.40)),
                drawer_width_m=float(art_spec.get("corridor_width_m", 0.50)),
                drawer_depth_m=float(art_spec.get("drawer_depth_m", 0.34)),
            )
            ped_ok, ped_clear, ped_msg = check_pedestal_prismatic_clearance(
                robot_pos_xy=(float(r_pos[0]), float(r_pos[1])),
                robot_yaw_rad=r_yaw,
                corridor=corridor,
                pedestal_half_extents=(0.20, 0.20),
                margin_m=0.05,
            )
            if not ped_ok:
                pass3_ok = False
                report["defects"].append({
                    "code": "DEFECT_PRISMATIC_PEDESTAL_COLLISION",
                    "clearance_m": round(ped_clear, 4),
                    "message": ped_msg,
                    "remediation": "Increase robot-to-fixture standoff (e.g. robot X <= -0.90m or fixture X >= 0.05m) so fully extended drawer clears the robot pedestal."
                })
            else:
                report["diagnostics"].append(
                    f"Pass 3c: Prismatic stroke corridor clears robot pedestal (clearance = {ped_clear:.3f}m >= 0.05m)."
                )

            # Check cavity headroom for reversible stowing (D2-B)
            if "cavity_dims_m" in art_spec:
                cav_dims = art_spec["cavity_dims_m"]
                for obj in objects_list:
                    oid = obj.get("id", "")
                    reg_n = obj.get("registry_name", "")
                    ext = get_asset_footprint_half_extents(obj)
                    obj_h = KNOWN_OBJECT_HEIGHTS.get(oid, KNOWN_OBJECT_HEIGHTS.get(reg_n, 0.16))
                    cav_ok, cav_metrics, cav_msg = check_cavity_containment_and_headroom(
                        object_dims_xyz=(ext[0] * 2.0, ext[1] * 2.0, obj_h),
                        cavity_dims_xyz=cav_dims,
                        min_headroom_m=0.02,
                    )
                    headroom = cav_metrics.get("headroom_z_m", 0.0)
                    if not cav_ok:
                        pass3_ok = False
                        report["defects"].append({
                            "code": "DEFECT_CAVITY_HEADROOM_COLLISION",
                            "object": oid,
                            "headroom_m": round(headroom, 4),
                            "message": cav_msg,
                            "remediation": "Ensure stowed manipuland height is at least 0.02m shorter than the drawer internal cavity height."
                        })
                    else:
                        report["diagnostics"].append(f"Pass 3c: Stowed '{oid}' cavity headroom verified ({headroom:.3f}m >= 0.02m).")
        elif not is_mobile and bg_cfg and art_spec["joint_type"] == "dual_revolute":
            robot_pose = emb_cfg.get("params", {}).get("initial_pose", {})
            r_pos = robot_pose.get("position_xyz", [-0.85, 0.0, 0.75])
            bg_pose = bg_cfg.get("params", {}).get("initial_pose", {})
            b_pos = bg_pose.get("position_xyz", [0.10, 0.0, 0.0])
            b_rot = bg_pose.get("rotation_xyzw", [0.0, 0.0, -0.7071068, 0.7071068])
            b_yaw = yaw_from_quat(b_rot)
            left_m = compute_revolute_swept_manifold(
                base_pos=(float(b_pos[0]), float(b_pos[1]), 0.0),
                base_yaw_rad=b_yaw,
                hinge_offset_local=art_spec.get("hinge_offset", (-0.35, -0.15)),
                door_radius_m=float(art_spec.get("envelope_radius_m", 0.14)),
                swing_span_rad=(0.0, 1.5708),
            )
            right_m = compute_revolute_swept_manifold(
                base_pos=(float(b_pos[0]), float(b_pos[1]), 0.0),
                base_yaw_rad=b_yaw,
                hinge_offset_local=art_spec.get("right_hinge_offset", (-0.35, 0.15)),
                door_radius_m=float(art_spec.get("envelope_radius_m", 0.14)),
                swing_span_rad=(-1.5708, 0.0),
            )
            dual_ok, dual_metrics, dual_msg = check_dual_revolute_clearance(
                left_manifold=left_m,
                right_manifold=right_m,
                robot_pos_xy=(float(r_pos[0]), float(r_pos[1])),
                pedestal_radius_m=0.20,
                min_seam_clearance_m=0.05,
            )
            if not dual_ok:
                pass3_ok = False
                report["defects"].append({
                    "code": "SWEPT_VOLUME_COLLISION",
                    "object": art_id,
                    "clearance_m": dual_metrics.get("min_pedestal_clearance_m", 0.0),
                    "message": dual_msg,
                    "remediation": "Increase robot-to-cart standoff or adjust dual-door hinge span."
                })
            else:
                report["diagnostics"].append(f"Pass 3c: {dual_msg}")
    else:
        pass3_ok = False

    report["passes"]["pass3_swept_sector"] = pass3_ok

    # --- Pass 3b: Tabletop 2D Bounding Footprint Overlap Check ---
    pass3b_ok = True
    objects_by_id = {obj.get("id"): obj for obj in objects_list if obj.get("id")}

    # Group objects by supporting fixture (On relation reference)
    surfaces: dict[str, list[dict]] = {}
    for r in relations:
        if r.get("kind") == "on":
            subj_id = r.get("subject")
            ref_id = r.get("reference")
            if subj_id in objects_by_id and ref_id:
                surfaces.setdefault(ref_id, []).append(objects_by_id[subj_id])

    # Build reified relation nominal coordinate map
    reified_map: dict[str, tuple[float, float]] = {}
    for rr in data.get("reified_relations", []):
        src = rr.get("source_id")
        if src and "delta_x" in rr and "delta_y" in rr:
            nom_x = rr["delta_x"].get("nominal")
            nom_y = rr["delta_y"].get("nominal")
            if nom_x is not None and nom_y is not None:
                reified_map[src] = (float(nom_x), float(nom_y))

    for surface_id, placed_objs in surfaces.items():
        for i in range(len(placed_objs)):
            for j in range(i + 1, len(placed_objs)):
                obj_a = placed_objs[i]
                obj_b = placed_objs[j]
                id_a = obj_a.get("id")
                id_b = obj_b.get("id")

                ext_a = get_asset_footprint_half_extents(obj_a)
                ext_b = get_asset_footprint_half_extents(obj_b)

                quat_a = effective_orientation(obj_a, relations)
                quat_b = effective_orientation(obj_b, relations)
                yaw_a = yaw_from_quat(quat_a)
                yaw_b = yaw_from_quat(quat_b)

                # Check 1: Initial pose coordinates
                pos_a = obj_a.get("params", {}).get("initial_pose", {}).get("position_xyz")
                pos_b = obj_b.get("params", {}).get("initial_pose", {}).get("position_xyz")

                if pos_a and pos_b:
                    ok_init, clearance_init, msg_init = check_2d_footprint_overlap(
                        (float(pos_a[0]), float(pos_a[1])),
                        yaw_a,
                        ext_a,
                        (float(pos_b[0]), float(pos_b[1])),
                        yaw_b,
                        ext_b,
                        margin=0.05,
                    )
                    if not ok_init:
                        pass3b_ok = False
                        report["defects"].append({
                            "code": "FOOTPRINT_OVERLAP_COLLISION",
                            "objects": [id_a, id_b],
                            "coordinate_source": "initial_pose",
                            "clearance_m": round(clearance_init, 4),
                            "message": f"Initial pose: {id_a} and {id_b} {msg_init} on surface '{surface_id}'.",
                            "remediation": f"Increase separation between '{id_a}' and '{id_b}' by >= {-clearance_init:.3f}m."
                        })

                # Check 2: Reified relations nominal coordinates
                if id_a in reified_map and id_b in reified_map:
                    nom_a = reified_map[id_a]
                    nom_b = reified_map[id_b]
                    ok_rr, clearance_rr, msg_rr = check_2d_footprint_overlap(
                        nom_a, yaw_a, ext_a, nom_b, yaw_b, ext_b, margin=0.05
                    )
                    if not ok_rr:
                        pass3b_ok = False
                        report["defects"].append({
                            "code": "FOOTPRINT_OVERLAP_COLLISION",
                            "objects": [id_a, id_b],
                            "coordinate_source": "reified_relations",
                            "clearance_m": round(clearance_rr, 4),
                            "message": f"Reified nominal: {id_a} and {id_b} {msg_rr} on surface '{surface_id}'.",
                            "remediation": f"Increase nominal delta separation between '{id_a}' and '{id_b}' by >= {-clearance_rr:.3f}m."
                        })

        # Check individual object surface and sector containment
        for obj in placed_objs:
            obj_id = obj.get("id")
            pos = obj.get("params", {}).get("initial_pose", {}).get("position_xyz")
            if pos and len(pos) >= 2 and bg_cfg:
                on_r = next((r for r in relations if r.get("kind") == "on" and r.get("subject") == obj_id), None)
                sec_name = on_r.get("params", {}).get("surface_sector") or on_r.get("params", {}).get("surface_anchor") if on_r else None
                from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
                    get_fixture_sector_bounds,
                    transform_sector_bounds_to_world,
                )
                bg_reg = bg_cfg.get("registry_name") or bg_cfg.get("id", "")
                sec_bounds = get_fixture_sector_bounds(bg_reg, sec_name)
                bg_pose = bg_cfg.get("params", {}).get("initial_pose", {})
                b_pos = bg_pose.get("position_xyz", [0.0, 0.0, 0.0])
                b_rot = bg_pose.get("rotation_xyzw", [0.0, 0.0, 0.0, 1.0])
                w_b = transform_sector_bounds_to_world(sec_bounds, b_pos, b_rot)
                ext = get_asset_footprint_half_extents(obj)
                obj_yaw = 0.0
                rot_r = next((r for r in relations if r.get("kind") == "rotate_around_solution" and r.get("subject") == obj_id), None)
                if rot_r:
                    obj_yaw = float(rot_r.get("params", {}).get("yaw_rad", 0.0))
                else:
                    obj_rot = obj.get("params", {}).get("initial_pose", {}).get("rotation_xyzw")
                    if obj_rot and len(obj_rot) == 4:
                        from isaaclab_arena.utils.yaw import yaw_from_quat_xyzw
                        obj_yaw = yaw_from_quat_xyzw(tuple(obj_rot))
                c_yaw, s_yaw = abs(math.cos(obj_yaw)), abs(math.sin(obj_yaw))
                ext_x = c_yaw * ext[0] + s_yaw * ext[1]
                ext_y = s_yaw * ext[0] + c_yaw * ext[1]
                tol = 0.05
                if (float(pos[0]) - ext_x < w_b[0] - tol or float(pos[0]) + ext_x > w_b[1] + tol or
                    float(pos[1]) - ext_y < w_b[2] - tol or float(pos[1]) + ext_y > w_b[3] + tol):
                    pass3b_ok = False
                    report["defects"].append({
                        "code": "DEFECT_SURFACE_BOUNDS_VIOLATION",
                        "object": obj_id,
                        "surface": surface_id,
                        "sector": sec_name,
                        "position_xy": [float(pos[0]), float(pos[1])],
                        "world_sector_bounds": [round(w_b[0], 3), round(w_b[1], 3), round(w_b[2], 3), round(w_b[3], 3)],
                        "message": f"Object '{obj_id}' at ({pos[0]:.2f}, {pos[1]:.2f}) lies outside surface sector bounds [{w_b[0]:.2f}, {w_b[1]:.2f}] x [{w_b[2]:.2f}, {w_b[3]:.2f}]."
                    })

    report["passes"]["pass3_footprint_clearance"] = pass3b_ok
    if pass3b_ok:
        report["diagnostics"].append("Pass 3b: Tabletop 2D bounding footprint clearances verified across all surface objects.")

    # -------------------------------------------------------------
    # Pass 4: Sequential State Handoff Invariant (2-stage & 3-stage)
    # -------------------------------------------------------------
    task_cfg = data.get("task", {})
    composition = task_cfg.get("composition", "atomic")
    subtasks = task_cfg.get("subtasks", [])

    pass4_ok = True
    if composition != "sequential":
        pass4_ok = False
        expected_open = art_spec.get("open_task", "OpenDoorTask") if art_spec else "OpenDoorTask"
        expected_stow = art_spec.get("cavity_task", "CavityStowTask") if art_spec else "CavityStowTask"
        report["defects"].append({
            "code": "TASK_DECOMPOSITION_MISSING",
            "message": f"Articulated task requiring access to '{art_id}' cavity must be decomposed into 'composition: sequential' with [{expected_open}, {expected_stow}], but got 'composition: {composition}' with atomic subtask."
        })
    elif len(subtasks) < 2:
        pass4_ok = False
        report["defects"].append({
            "code": "SEQUENTIAL_TASK_UNDERPOPULATED",
            "message": f"Sequential task requires >= 2 subtasks, found {len(subtasks)}."
        })
    else:
        # Check Subtask 1 opens the articulated fixture
        st1 = subtasks[0]
        expected_open_task = art_spec.get("open_task", "OpenDoorTask") if art_spec else "OpenDoorTask"
        if st1.get("kind") not in [expected_open_task, "OpenDoorTask", "OpenDrawerTask"]:
            pass4_ok = False
            report["defects"].append({
                "code": "HANDOFF_FIRST_SUBTASK_INVALID",
                "message": f"First subtask must be {expected_open_task}, got {st1.get('kind')}."
            })
        else:
            for idx, st in enumerate(subtasks):
                kind = st.get("kind", "")
                params = st.get("params", {})
                if kind in ("OpenDoorTask", "OpenDrawerTask"):
                    if "open_threshold" in params and "openness_threshold" not in params:
                        pass4_ok = False
                        report["defects"].append({
                            "code": "TASK_PARAM_NAME_INVALID",
                            "message": f"Subtask {idx+1} ({kind}) parameter must be named 'openness_threshold' (does not accept 'open_threshold').",
                            "remediation": f"Rename parameter 'open_threshold' to 'openness_threshold' in {kind}."
                        })
                    raw_threshold = params.get("openness_threshold", 0.0)
                    threshold = float(raw_threshold) if raw_threshold is not None else 0.0
                    if threshold < 0.75:
                        pass4_ok = False
                        report["defects"].append({
                            "code": "OPENNESS_THRESHOLD_LOW",
                            "threshold": threshold,
                            "message": f"Subtask {idx+1} ({kind}) openness_threshold {threshold:.2f} < required 0.75 for clearance."
                        })
                elif kind in ("CloseDoorTask", "CloseDrawerTask"):
                    raw_closed = params.get("closedness_threshold", 0.10)
                    closed_thresh = float(raw_closed) if raw_closed is not None else 0.10
                    if closed_thresh > 0.25:
                        pass4_ok = False
                        report["defects"].append({
                            "code": "CLOSEDNESS_THRESHOLD_HIGH",
                            "threshold": closed_thresh,
                            "message": f"Subtask {idx+1} ({kind}) closedness_threshold {closed_thresh:.2f} > max 0.25 for full closure."
                        })
            if pass4_ok:
                chain_str = " -> ".join(st.get("kind", "?") for st in subtasks)
                report["diagnostics"].append(
                    f"Pass 4: Sequential handoff invariant verified across {len(subtasks)} subtasks ({chain_str})."
                )
    report["passes"]["pass4_handoff"] = pass4_ok

    # -------------------------------------------------------------
    # Pass 5: Task-Affordance Facing (fixed-base manipulators)
    # -------------------------------------------------------------
    pass5_ok = True
    canon_normal = art_spec.get("canonical_aperture_normal") if art_spec else None
    emb_cfg = data.get("embodiment", {})
    emb_reg = emb_cfg.get("registry_name", "").lower()
    is_mobile = any(m in emb_reg for m in ["g1", "humanoid", "fetch", "mobile", "gr1", "unitree"])
    if not canon_normal:
        report["diagnostics"].append(f"Pass 5: No measured aperture normal for '{art_id}'; skipped.")
    elif is_mobile:
        report["diagnostics"].append(f"Pass 5: Mobile embodiment '{emb_reg}'; facing check skipped.")
    else:
        robot_pose = emb_cfg.get("params", {}).get("initial_pose", {})
        art_pose = art_obj.get("params", {}).get("initial_pose", {}) if art_obj else {}
        facing_ok, alignment, world_norm, msg, rec_quat = check_affordance_facing(
            robot_pos=robot_pose.get("position_xyz", [-0.55, 0.0, 0.0]),
            art_pos=art_pose.get("position_xyz", [base_x, base_y, 0.0]),
            art_quat=effective_orientation(art_obj, data.get("relations", [])),
            canonical_aperture_normal=list(canon_normal),
        )
        if facing_ok:
            report["diagnostics"].append(f"Pass 5: '{art_id}' {msg}")
        else:
            pass5_ok = False
            report["defects"].append({
                "code": "TASK_AFFORDANCE_FACING_DEFECT",
                "object": art_id,
                "alignment_dot": alignment,
                "world_aperture_normal": world_norm,
                "message": msg,
                "remediation": (
                    f"Add relation 'kind: rotate_around_solution, subject: {art_id}, params: {{yaw_rad: "
                    f"{math.atan2(math.sin(2.0 * math.atan2(rec_quat[2], rec_quat[3])), math.cos(2.0 * math.atan2(rec_quat[2], rec_quat[3]))):.4f}}}' so the door faces the robot base. "
                    "initial_pose rotation is ignored for objects placed by an 'on' relation."
                ),
            })
    report["passes"]["pass5_facing"] = pass5_ok

    # -------------------------------------------------------------
    # Pass 6: Standoff & Elevation Alignment Oracle
    # -------------------------------------------------------------
    reified_rels = data.get("reified_relations", [])
    pass6_ok, pass6_defects, pass6_diags = check_fixture_standoff_and_elevation(
        emb_cfg=emb_cfg,
        bg_cfg=bg_cfg,
        reified_relations=reified_rels,
        objects_list=objects_list,
        relations=relations,
    )
    report["passes"]["pass6_standoff_elevation"] = pass6_ok
    report["defects"].extend(pass6_defects)
    report["diagnostics"].extend(pass6_diags)

    # Overall conformance
    report["conforms"] = (
        report["passes"].get("pass1_schema", False) and
        report["passes"].get("pass2_kinematics", False) and
        report["passes"].get("pass3_swept_sector", False) and
        report["passes"].get("pass3_footprint_clearance", True) and
        report["passes"].get("pass4_handoff", True) and
        report["passes"].get("pass5_facing", True) and
        report["passes"].get("pass6_standoff_elevation", True)
    )
    return report


def main():
    parser = argparse.ArgumentParser(description="Deterministic Deterministic Tooling Oracle for Articulated Specs")
    parser.add_argument("--spec", "--spec_yaml", dest="spec", type=str, required=True, help="Path to ArenaEnvGraphSpec YAML")
    parser.add_argument("--usd", "--usd_path", dest="usd", type=str, default=None, help="Path to articulated USD asset")
    parser.add_argument("--json", action="store_true", help="Output raw JSON report")
    args = parser.parse_args()

    result = verify_spec(args.spec, args.usd)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "PASSED" if result["conforms"] else "FAILED"
        print(f"\n=======================================================")
        print(f"[ORACLE REPORT] Specification Validation: {status}")
        print(f"Spec: {args.spec}")
        print("=======================================================")
        print(f"Pass 1 (Schema & Graph):          {'PASS' if result['passes'].get('pass1_schema') else 'FAIL'}")
        print(f"Pass 2 (USD Kinematics):          {'PASS' if result['passes'].get('pass2_kinematics') else 'FAIL'}")
        print(f"Pass 3a (3D Swept Sector Arc):    {'PASS' if result['passes'].get('pass3_swept_sector') else 'FAIL'}")
        print(f"Pass 3b (2D Footprint Clear):     {'PASS' if result['passes'].get('pass3_footprint_clearance') else 'FAIL'}")
        print(f"Pass 4 (Sequential Handoff):      {'PASS' if result['passes'].get('pass4_handoff') else 'FAIL'}")
        print(f"Pass 5 (Affordance Facing):       {'PASS' if result['passes'].get('pass5_facing') else 'FAIL'}")
        print(f"Pass 6 (Standoff & Elevation):    {'PASS' if result['passes'].get('pass6_standoff_elevation') else 'FAIL'}")

        if result["defects"]:
            print("\n[DETECTED DEFECTS FOR SELF-HEALING LOOP]:")
            for d in result["defects"]:
                print(f"  * [{d['code']}] {d['message']}")
                if "remediation" in d:
                    print(f"    -> Remediation Hint: {d['remediation']}")

        if result["diagnostics"]:
            print("\n[VERIFIED DIAGNOSTIC EVIDENCE]:")
            for diag in result["diagnostics"]:
                print(f"  + {diag}")
        print("=======================================================\n")

    sys.exit(0 if result["conforms"] else 1)


if __name__ == "__main__":
    main()
