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
    # Note: maple_table / maple_table_robolab USD mesh is offset from its prim origin: X in [0.20, 0.90], Y in [-0.50, 0.50], Z_deck=0.0
    "maple_table_robolab": (0.20, 0.90, -0.50, 0.50, 0.0),
    "maple_table": (0.20, 0.90, -0.50, 0.50, 0.0),
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
    "maple_table": {
        "front_center": (0.25, 0.65, -0.20, 0.16, 0.0),
        "front_left": (0.35, 0.55, 0.08, 0.30, 0.0),
        "front_right": (0.35, 0.55, -0.30, -0.08, 0.0),
        "front_half": (0.25, 0.65, -0.48, 0.48, 0.0),
        "robot_front": (0.25, 0.65, -0.48, 0.48, 0.0),
        "rear_center": (0.55, 0.88, -0.15, 0.15, 0.0),
        "rear_left": (0.55, 0.88, 0.05, 0.48, 0.0),
        "rear_right": (0.55, 0.88, -0.48, -0.05, 0.0),
        "rear_storage": (0.55, 0.88, -0.48, 0.48, 0.0),
        "table_top": (0.25, 0.88, -0.48, 0.48, 0.0),
    },
    "maple_table_robolab": {
        "front_center": (0.25, 0.65, -0.20, 0.16, 0.0),
        "front_left": (0.35, 0.55, 0.08, 0.30, 0.0),
        "front_right": (0.35, 0.55, -0.30, -0.08, 0.0),
        "front_half": (0.25, 0.65, -0.48, 0.48, 0.0),
        "robot_front": (0.25, 0.65, -0.48, 0.48, 0.0),
        "rear_center": (0.55, 0.88, -0.15, 0.15, 0.0),
        "rear_left": (0.55, 0.88, 0.05, 0.48, 0.0),
        "rear_right": (0.55, 0.88, -0.48, -0.05, 0.0),
        "rear_storage": (0.55, 0.88, -0.48, 0.48, 0.0),
        "table_top": (0.25, 0.88, -0.48, 0.48, 0.0),
    },
    "table": {
        "front_center": (-0.25, -0.05, -0.08, 0.08, 0.75),
        "front_left": (-0.25, -0.05, 0.05, 0.24, 0.75),
        "front_right": (-0.25, -0.05, -0.24, -0.05, 0.75),
        "front_half": (-0.25, -0.05, -0.24, 0.24, 0.75),
        "robot_front": (-0.25, -0.05, -0.24, 0.24, 0.75),
        "rear_center": (0.05, 0.25, -0.08, 0.08, 0.75),
        "rear_left": (0.05, 0.25, 0.05, 0.24, 0.75),
        "rear_right": (0.05, 0.25, -0.24, -0.05, 0.75),
        "rear_storage": (0.05, 0.25, -0.24, 0.24, 0.75),
        "table_top": (-0.35, 0.35, -0.24, 0.24, 0.75),
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


# ---------------------------------------------------------------------------
# Depth Alignment: Pre-computed training dataset fingerprints
# ---------------------------------------------------------------------------
# Each entry captures the monocular depth statistics measured from the training
# demonstration video using Depth Anything V2.  The oracle compares a candidate
# scene's *predicted* image-plane object position (via pinhole projection) against
# these reference values to flag spatial misalignment before launching simulation.

DATASET_DEPTH_FINGERPRINTS: dict[str, dict[str, float]] = {
    "g1_static_pick_and_place": {
        # Measured from episode_000000.mp4 via Depth Anything V2 Small
        "apple_y_norm": 0.717,
        "apple_x_norm": 0.144,
        "apple_depth_norm": 0.777,
        "surface_slope": 0.0029,
        "camera_pitch_deg": -38.0,
        # Acceptable tolerance bands
        "y_norm_tol": 0.20,
        "x_norm_tol": 0.25,
        "depth_norm_tol": 0.25,
    },
}

# G1 head camera intrinsics (from g1.py PinholeCameraCfg)
_G1_HEAD_CAM = {
    "focal_length_mm": 15.0,
    "width": 640,
    "height": 480,
    "sensor_width_mm": 36.0,  # default horizontal aperture
    # Camera offset on head_link (position in head-link frame, ROS convention)
    "offset_xyz": (0.04485, 0.0, 0.35325),
    "offset_quat_xyzw": (-0.62721, 0.62721, -0.32651, 0.32651),
    # G1 head_link + camera offset sits at ~1.22m above ground (pelvis 0.72m + 0.15m + 0.353m)
    "head_link_height_above_base": 0.15,
}


def _quat_to_rotation_matrix(qx: float, qy: float, qz: float, qw: float) -> np.ndarray:
    """Convert quaternion (x, y, z, w) to 3x3 rotation matrix."""
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ])


def _project_to_image_plane(
    obj_world_xyz: tuple[float, float, float],
    cam_world_xyz: tuple[float, float, float],
    cam_quat_xyzw: tuple[float, float, float, float],
    focal_px: float,
    cx: float,
    cy: float,
) -> tuple[float, float, float] | None:
    """Project a 3D world point onto a camera's image plane.

    Returns:
        (u_norm, v_norm, depth) normalized image coordinates and depth, or None if behind camera.
    """
    r_mat = _quat_to_rotation_matrix(*cam_quat_xyzw)
    # World-to-camera transform: p_cam = R^T @ (p_world - t_cam)
    delta = np.array(obj_world_xyz) - np.array(cam_world_xyz)
    p_cam = r_mat.T @ delta

    # ROS convention: Z forward, X right, Y down
    if p_cam[2] <= 0.01:
        return None  # Behind camera

    u = focal_px * p_cam[0] / p_cam[2] + cx
    v = focal_px * p_cam[1] / p_cam[2] + cy
    depth = float(p_cam[2])

    u_norm = u / (2 * cx)  # normalize to [0, 1]
    v_norm = v / (2 * cy)
    return (float(u_norm), float(v_norm), depth)


def validate_depth_alignment(
    spec: ArenaEnvGraphSpec,
    dataset_key: str = "g1_static_pick_and_place",
) -> list[str]:
    """Predict object image-plane position from spec geometry and compare to dataset fingerprint.

    Uses pinhole camera projection from the robot's head-cam pose and the object's world
    position to estimate where the manipuland will appear in the frame. Compares against
    the precomputed training dataset fingerprint to flag spatial misalignment before
    running any simulation.  No GPU required.

    Args:
        spec: The environment graph specification.
        dataset_key: Key into DATASET_DEPTH_FINGERPRINTS for the reference training distribution.
    """
    errors: list[str] = []
    ref = DATASET_DEPTH_FINGERPRINTS.get(dataset_key)
    if not ref or not spec.embodiment:
        return errors

    # --- Resolve robot base position ---
    emb_pose = spec.embodiment.params.get("initial_pose", {}) if spec.embodiment.params else {}
    emb_pos = emb_pose.get("position_xyz")
    if not emb_pos or len(emb_pos) < 3:
        return errors

    # --- Estimate camera world position ---
    cam = _G1_HEAD_CAM
    # For humanoid embodiments with WBC, pelvis height at runtime stands at ~0.72m
    base_z = emb_pos[2] if emb_pos[2] > 0.2 else 0.72
    cam_world = (
        emb_pos[0] + cam["offset_xyz"][0],
        emb_pos[1] + cam["offset_xyz"][1],
        base_z + cam["head_link_height_above_base"] + cam["offset_xyz"][2],
    )

    # --- Compute focal length in pixels ---
    fx_px = cam["focal_length_mm"] * cam["width"] / cam["sensor_width_mm"]
    cx = cam["width"] / 2.0
    cy = cam["height"] / 2.0

    # --- Find manipuland object (first non-furniture, non-receptacle task object) ---
    manipuland = None
    for obj in spec.objects:
        obj_lower = f"{obj.id} {obj.registry_name}".lower()
        is_furniture = any(k in obj_lower for k in ("shelf", "shelving", "table", "counter", "desk", "rack"))
        is_receptacle = any(k in obj_lower for k in ("bin", "basket", "tray", "box", "bowl", "plate"))
        if not is_furniture and not is_receptacle:
            manipuland = obj
            break

    if not manipuland:
        return errors

    obj_pose = manipuland.params.get("initial_pose", {}) if manipuland.params else {}
    obj_pos = obj_pose.get("position_xyz")
    if not obj_pos or len(obj_pos) < 3:
        return errors

    # --- Project manipuland onto image plane ---
    proj = _project_to_image_plane(
        tuple(obj_pos),
        cam_world,
        cam["offset_quat_xyzw"],
        fx_px,
        cx,
        cy,
    )

    if proj is None:
        errors.append(
            f"[DepthAlignmentOracle] Manipuland '{manipuland.id}' projects behind the robot's head camera. "
            f"Object at {obj_pos} is not visible from camera at {cam_world}."
        )
        return errors

    pred_x_norm, pred_y_norm, pred_depth = proj

    # --- Compare against dataset fingerprint ---
    ref_y = ref["apple_y_norm"]
    ref_x = ref["apple_x_norm"]
    # If task or object sector targets the right arm / right side, mirror the reference X
    task_desc = spec.task.description.lower() if spec.task and spec.task.description else ""
    on_rel = next((r for r in spec.relations if r.subject == manipuland.id and r.kind == "on"), None)
    sector = on_rel.params.get("surface_sector", "") if on_rel and on_rel.params else ""
    if "right arm" in task_desc or "front_right" in sector or "right" in sector:
        ref_x = 1.0 - ref_x

    y_tol = ref.get("y_norm_tol", 0.20)
    x_tol = ref.get("x_norm_tol", 0.25)

    y_delta = pred_y_norm - ref_y
    x_delta = pred_x_norm - ref_x

    if abs(y_delta) > y_tol:
        direction = "higher in frame (object above training distribution)" if y_delta < 0 else "lower in frame"
        errors.append(
            f"[DepthAlignmentOracle] Manipuland '{manipuland.id}' projects to Y_norm={pred_y_norm:.3f} "
            f"but training dataset expects Y_norm={ref_y:.3f} (delta={y_delta:+.3f}, tol=±{y_tol:.2f}). "
            f"Object is {direction}. Adjust table height, camera pitch, or object forward distance."
        )

    if abs(x_delta) > x_tol:
        direction = "too far left" if x_delta < 0 else "too far right"
        errors.append(
            f"[DepthAlignmentOracle] Manipuland '{manipuland.id}' projects to X_norm={pred_x_norm:.3f} "
            f"but training dataset expects X_norm={ref_x:.3f} (delta={x_delta:+.3f}, tol=±{x_tol:.2f}). "
            f"Object is {direction} in frame. Adjust lateral placement."
        )

    # --- Check if object distance is plausible for reaching ---
    if pred_depth > 0.8:
        errors.append(
            f"[DepthAlignmentOracle] Manipuland '{manipuland.id}' is {pred_depth:.2f}m from head camera, "
            f"which is likely too far for the training distribution (typical range 0.3–0.6m). "
            f"Move object closer to robot or adjust robot base position."
        )

    return errors


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
                pelvis_z = emb_pos[2] + 0.75 if emb_pos[2] < 0.2 else emb_pos[2]
                rel_z = obj_pos[2] - pelvis_z
                if rel_z > 0.45 or rel_z < -0.35:
                    errors.append(
                        f"[KinematicOracle] Humanoid '{spec.embodiment.id}' pelvis height Z={pelvis_z:.2f}m is misaligned "
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
    """Run comprehensive spatial geometric, kinematic, depth alignment, and support containment checks."""
    diagnostics: list[str] = []
    diagnostics.extend(validate_relational_completeness(spec))
    diagnostics.extend(validate_support_containment(spec))
    diagnostics.extend(validate_kinematic_reachability(spec))
    diagnostics.extend(validate_depth_alignment(spec))
    return len(diagnostics) == 0, diagnostics
