# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Spatial Geometric & Kinematic Oracle for Active Inference Verification & Factor Graph Relaxation."""

from __future__ import annotations

import math
import numpy as np
from collections.abc import Callable, Collection

from typing import Any

from isaaclab_arena.agentic_environment_generation.policy_capability_graph import frame_height
from isaaclab_arena.agentic_environment_generation.usd_stage_introspection import (
    resolve_fixture_support_patch,
)
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.relations.spatial_factor_graph import SpatialFactorGraph


class RelaxationResultList(list):
    """Backward-compatible list[str] of diagnostics carrying factor-graph relaxation metadata."""

    def __init__(
        self,
        items: list[str] | None = None,
        *,
        converged: bool = True,
        residual: float = 0.0,
        iterations: int = 0,
        unresolved_factors: list[str] | None = None,
    ) -> None:
        super().__init__(items or [])
        self.converged = converged
        self.residual = float(residual)
        self.iterations = int(iterations)
        self.unresolved_factors = list(unresolved_factors or [])

    def get(self, key: str, default: Any = None) -> Any:
        """Provide dict-style metadata access while remaining a list[str]."""
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        """Return structured metadata dictionary."""
        return {
            "converged": self.converged,
            "residual": self.residual,
            "iterations": self.iterations,
            "unresolved_factors": list(self.unresolved_factors),
            "diagnostics": list(self),
        }


KNOWN_FIXTURE_BOUNDS: dict[str, tuple[float, float, float, float, float]] = {
    # Note: maple_table / maple_table_robolab USD mesh is offset from its prim origin: X in [0.20, 0.90], Y in [-0.50, 0.50], Z_deck=0.0
    "maple_table_robolab": (0.20, 0.90, -0.50, 0.50, 0.0),
    "maple_table": (0.20, 0.90, -0.50, 0.50, 0.0),
    # Note: table_oak_robolab is 0.60x0.60m outer mesh with beveled edges; flat top-deck bounds are [-0.22, 0.22] x [-0.22, 0.22] at Z_deck=0.75
    "table_oak_robolab": (-0.22, 0.22, -0.22, 0.22, 0.75),
    "table": (-0.45, 0.45, -0.30, 0.30, 0.75),
    "office_table_background": (-0.45, 0.45, -0.30, 0.30, 0.75),
    "packing_table": (-0.50, 0.50, -0.35, 0.35, 0.75),
    "kitchen": (-0.40, 0.40, -0.30, 0.30, 0.75),
    "kitchen_background": (-0.40, 0.40, -0.30, 0.30, 0.75),
    "kitchen_with_open_drawer": (-0.40, 0.40, -0.30, 0.30, 0.75),
    "lightwheel_robocasa_kitchen": (-1.0, 1.0, -0.40, 0.40, 0.85),
    "galileo_locomanip": (0.45, 0.70, -0.15, 0.40, -0.03),
    "wireshelving_a01_vomp_robolab": (-0.45, 0.45, -0.25, 0.25, 0.76),
    "kitchen_base_cabinet": (-0.30, 0.30, -0.31, 0.29, 0.908),
    "fixture_counter_a01": (-0.25, 0.25, -1.35, 1.35, 0.9271),
    "cart_medical_utility": (-0.20, 0.20, -0.15, 0.15, 0.9109),
    "facilityEquipment_beverageFridge_display_a01": (-0.20, 0.20, -0.20, 0.20, 0.8652),
    "sm_facilityEquipment_beverageFridge_display_a01_01": (-0.20, 0.20, -0.20, 0.20, 0.8652),
    "beverage_fridge": (-0.20, 0.20, -0.20, 0.20, 0.8652),
    "galileo_room_background": (-2.0, 2.0, -2.0, 2.0, 0.0),
    "simple_room_background": (-2.0, 2.0, -2.0, 2.0, 0.0),
}

FIXTURE_SECTOR_BOUNDS: dict[str, dict[str, tuple[float, float, float, float, float]]] = {
    "kitchen_base_cabinet": {
        "front_left": (-0.25, 0.05, -0.25, 0.15, 0.908),
        "front_right": (-0.05, 0.25, -0.25, 0.15, 0.908),
        "front_center": (-0.15, 0.15, -0.25, 0.15, 0.908),
        "counter_top": (-0.25, 0.25, -0.25, 0.25, 0.908),
        "cabinet_deck": (-0.25, 0.25, -0.25, 0.25, 0.908),
        "top": (-0.25, 0.25, -0.25, 0.25, 0.908),
    },
    "fixture_counter_a01": {
        "front_left": (-0.20, 0.20, -1.20, 1.20, 0.9271),
        "front_right": (-0.20, 0.20, -1.20, -0.25, 0.9271),
        "front_center": (-0.20, 0.20, -1.20, 1.20, 0.9271),
        "counter_deck": (-0.20, 0.20, -1.20, 1.20, 0.9271),
    },
    "cart_medical_utility": {
        "front_left": (-0.15, 0.20, -0.12, 0.15, 0.9109),
        "front_right": (-0.15, 0.20, -0.15, 0.12, 0.9109),
        "front_center": (-0.15, 0.20, -0.12, 0.12, 0.9109),
        "preparation_tray": (-0.15, 0.20, -0.15, 0.15, 0.9109),
    },
    "facilityEquipment_beverageFridge_display_a01": {
        "top": (-0.18, 0.18, -0.18, 0.18, 0.8652),
        "front_left": (-0.18, 0.18, 0.05, 0.18, 0.8652),
        "front_right": (-0.18, 0.18, -0.18, -0.05, 0.8652),
        "front_center": (-0.18, 0.18, -0.10, 0.10, 0.8652),
        "fridge_top": (-0.18, 0.18, -0.18, 0.18, 0.8652),
    },
    "sm_facilityEquipment_beverageFridge_display_a01_01": {
        "top": (-0.18, 0.18, -0.18, 0.18, 0.8652),
        "front_left": (-0.18, 0.18, 0.05, 0.18, 0.8652),
        "front_right": (-0.18, 0.18, -0.18, -0.05, 0.8652),
        "front_center": (-0.18, 0.18, -0.10, 0.10, 0.8652),
        "fridge_top": (-0.18, 0.18, -0.18, 0.18, 0.8652),
    },
    "beverage_fridge": {
        "top": (-0.18, 0.18, -0.18, 0.18, 0.8652),
        "front_left": (-0.18, 0.18, 0.05, 0.18, 0.8652),
        "front_right": (-0.18, 0.18, -0.18, -0.05, 0.8652),
        "front_center": (-0.18, 0.18, -0.10, 0.10, 0.8652),
        "fridge_top": (-0.18, 0.18, -0.18, 0.18, 0.8652),
    },
    "maple_table": {
        "front_center": (0.25, 0.65, -0.20, 0.16, 0.0),
        "front_left": (0.35, 0.55, 0.08, 0.30, 0.0),
        "front_right": (0.35, 0.55, -0.30, -0.08, 0.0),
        "left": (0.35, 0.55, 0.08, 0.30, 0.0),
        "right": (0.35, 0.55, -0.30, -0.08, 0.0),
        "front_half": (0.25, 0.65, -0.48, 0.48, 0.0),
        "robot_front": (0.25, 0.65, -0.48, 0.48, 0.0),
        "rear_center": (0.55, 0.88, -0.15, 0.15, 0.0),
        "rear_left": (0.55, 0.88, 0.05, 0.48, 0.0),
        "rear_right": (0.55, 0.88, -0.48, -0.05, 0.0),
        "rear_storage": (0.55, 0.88, -0.48, 0.48, 0.0),
        "table_top": (0.25, 0.88, -0.48, 0.48, 0.0),
    },
    "maple_table_robolab": {
        "front_center": (0.25, 0.65, -0.20, 0.20, 0.0),
        "front_left": (0.25, 0.65, 0.05, 0.45, 0.0),
        "front_right": (0.25, 0.65, -0.45, -0.05, 0.0),
        "left": (0.25, 0.65, 0.05, 0.45, 0.0),
        "right": (0.25, 0.65, -0.45, -0.05, 0.0),
        "front_half": (0.25, 0.65, -0.48, 0.48, 0.0),
        "robot_front": (0.25, 0.65, -0.48, 0.48, 0.0),
        "rear_center": (0.55, 0.88, -0.15, 0.15, 0.0),
        "rear_left": (0.55, 0.88, 0.05, 0.48, 0.0),
        "rear_right": (0.55, 0.88, -0.48, -0.05, 0.0),
        "rear_storage": (0.55, 0.88, -0.48, 0.48, 0.0),
        "table_top": (0.25, 0.88, -0.48, 0.48, 0.0),
    },
    "table_oak_robolab": {
        "front_center": (-0.21, -0.11, -0.05, 0.05, 0.75),
        "front_left": (-0.21, -0.11, 0.10, 0.185, 0.75),
        "front_right": (-0.21, -0.11, -0.185, -0.10, 0.75),
        "left": (-0.21, 0.21, 0.10, 0.185, 0.75),
        "right": (-0.21, 0.21, -0.185, -0.10, 0.75),
        "front_half": (-0.21, -0.11, -0.185, 0.185, 0.75),
        "robot_front": (-0.21, -0.11, -0.185, 0.185, 0.75),
        "rear_center": (0.01, 0.17, -0.05, 0.05, 0.75),
        "rear_left": (0.01, 0.17, 0.10, 0.185, 0.75),
        "rear_right": (0.01, 0.17, -0.185, -0.10, 0.75),
        "rear_storage": (0.01, 0.17, -0.185, 0.185, 0.75),
        "table_top": (-0.21, 0.17, -0.185, 0.185, 0.75),
    },
    "packing_table": {
        "front_center": (-0.35, 0.15, -0.12, 0.12, 0.75),
        "front_left": (-0.35, 0.15, 0.05, 0.30, 0.75),
        "front_right": (-0.35, 0.15, -0.30, -0.05, 0.75),
        "left": (-0.45, 0.45, 0.05, 0.30, 0.75),
        "right": (-0.45, 0.15, -0.30, -0.10, 0.75),
        "front_half": (-0.35, 0.15, -0.30, 0.30, 0.75),
        "robot_front": (-0.35, 0.15, -0.30, 0.30, 0.75),
        "rear_center": (0.05, 0.45, -0.12, 0.12, 0.75),
        "rear_left": (0.05, 0.45, 0.05, 0.30, 0.75),
        "rear_right": (0.05, 0.15, -0.30, -0.10, 0.75),
        "rear_storage": (0.05, 0.45, -0.12, 0.30, 0.75),
        "rear_bin_fixture": (0.15, 0.45, -0.35, -0.10, 0.75),
        "table_top": (-0.45, 0.45, -0.30, 0.30, 0.75),
    },
    "office_table_background": {
        "front_center": (-0.25, -0.05, -0.08, 0.08, 0.75),
        "front_left": (-0.25, -0.05, 0.05, 0.24, 0.75),
        "front_right": (-0.25, -0.05, -0.24, -0.05, 0.75),
        "left": (-0.35, 0.35, 0.05, 0.24, 0.75),
        "right": (-0.35, 0.35, -0.24, -0.05, 0.75),
        "front_half": (-0.25, -0.05, -0.24, 0.24, 0.75),
        "robot_front": (-0.25, -0.05, -0.24, 0.24, 0.75),
        "rear_center": (0.05, 0.25, -0.08, 0.08, 0.75),
        "rear_left": (0.05, 0.25, 0.05, 0.24, 0.75),
        "rear_right": (0.05, 0.25, -0.24, -0.05, 0.75),
        "rear_storage": (0.05, 0.25, -0.24, 0.24, 0.75),
        "table_top": (-0.35, 0.35, -0.24, 0.24, 0.75),
    },
    "table": {
        "front_center": (-0.25, -0.05, -0.08, 0.08, 0.75),
        "front_left": (-0.25, -0.05, 0.05, 0.24, 0.75),
        "front_right": (-0.25, -0.05, -0.24, -0.05, 0.75),
        "left": (-0.35, 0.35, 0.05, 0.24, 0.75),
        "right": (-0.35, 0.35, -0.24, -0.05, 0.75),
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

# Alias for backward compatibility with callers referencing FIXTURE_SECTOR_MAP
FIXTURE_SECTOR_MAP = FIXTURE_SECTOR_BOUNDS

# Permanent structural workstation fixtures embedded in background meshes (not spawned as separate objects)
# Map: background_registry_name -> list of (fixture_label, min_x, max_x, min_y, max_y)
FIXTURE_STRUCTURAL_EXCLUSIONS: dict[str, list[tuple[str, float, float, float, float]]] = {
    # packing_table.usd features a permanent grey storage bin with a distinctive grid pattern on its rear-right side
    "packing_table": [("grey_bin_fixture", 0.15, 0.45, -0.35, -0.10)],
}

# Resting end-effector clearance zones (world X, world Y, world Z, clearance_radius_m)
# Applies when robot base X is in [-0.50, -0.35] and tabletop Z is near 0.75m
RESTING_EE_EXCLUSION_ZONES: dict[str, tuple[float, float, float, float]] = {
    "droid": (-0.09, -0.10, 0.75, 0.06),
    "franka": (-0.09, -0.10, 0.75, 0.06),
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
    if not ref or not spec.embodiment or "g1" not in spec.embodiment.registry_name.lower().split("_"):
        return errors

    # --- Resolve robot base position ---
    emb_pose = spec.embodiment.params.get("initial_pose", {}) if spec.embodiment.params else {}
    emb_pos = emb_pose.get("position_xyz")
    if not emb_pos or len(emb_pos) < 3:
        return errors

    # --- Estimate camera world position ---
    cam = _G1_HEAD_CAM
    # G1's articulation root is the pelvis, even when its world Z is near zero.
    base_z = frame_height(emb_pos, "pelvis")
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
            "which is likely too far for the training distribution (typical range 0.3–0.6m). "
            "Move object closer to robot or adjust robot base position."
        )

    return errors


def get_known_fixture_bounds(
    name: str,
    usd_path: str | None = None,
) -> tuple[float, float, float, float, float]:
    """Retrieve approximate support surface boundary [min_x, max_x, min_y, max_y, z_deck]."""
    name_lower = name.lower()

    if usd_path:
        try:
            patch = resolve_fixture_support_patch(name, usd_path=usd_path)
            if patch and patch.usable_polygon_hull:
                pts = np.array(patch.usable_polygon_hull)
                min_x, max_x = float(pts[:, 0].min()), float(pts[:, 0].max())
                min_y, max_y = float(pts[:, 1].min()), float(pts[:, 1].max())
                return (min_x, max_x, min_y, max_y, patch.elevation_z)
        except Exception:
            pass

    for key, bounds in sorted(KNOWN_FIXTURE_BOUNDS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if key in name_lower:
            return bounds

    try:
        patch = resolve_fixture_support_patch(name, usd_path=usd_path)
        if patch and patch.usable_polygon_hull:
            pts = np.array(patch.usable_polygon_hull)
            min_x, max_x = float(pts[:, 0].min()), float(pts[:, 0].max())
            min_y, max_y = float(pts[:, 1].min()), float(pts[:, 1].max())
            return (min_x, max_x, min_y, max_y, patch.elevation_z)
    except Exception:
        pass

    if "shelf" in name_lower or "rack" in name_lower:
        return (-0.45, 0.45, -0.25, 0.25, 0.75)
    if "table" in name_lower or "desk" in name_lower or "counter" in name_lower:
        return (-0.45, 0.45, -0.30, 0.30, 0.75)
    # Default generic workspace patch
    return (-0.50, 0.50, -0.35, 0.35, 0.75)


def get_fixture_sector_bounds(
    fixture_name: str,
    sector_name: str | None = None,
    usd_path: str | None = None,
) -> tuple[float, float, float, float, float]:
    """Retrieve functional sector bounds [min_x, max_x, min_y, max_y, z_deck] on a fixture."""
    known = get_known_fixture_bounds(fixture_name, usd_path=usd_path)
    if not sector_name:
        return known

    fixture_lower = fixture_name.lower()
    sector_lower = sector_name.lower()

    for fix_key, sectors in sorted(FIXTURE_SECTOR_BOUNDS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if fix_key in fixture_lower:
            matched_bounds = None
            if sector_lower in sectors:
                matched_bounds = sectors[sector_lower]
            else:
                for sec_key, sec_bounds in sorted(sectors.items(), key=lambda kv: len(kv[0]), reverse=True):
                    if sec_key in sector_lower or sector_lower in sec_key:
                        matched_bounds = sec_bounds
                        break
            if matched_bounds:
                if matched_bounds[4] == 0.0 and known[4] != 0.0:
                    return (matched_bounds[0], matched_bounds[1], matched_bounds[2], matched_bounds[3], known[4])
                return matched_bounds

    # Derive sectors dynamically from known / patch bounds
    min_x, max_x, min_y, max_y, z_deck = known
    mid_x = (min_x + max_x) / 2.0
    mid_y = (min_y + max_y) / 2.0
    y_span = max_y - min_y
    y_center_half = 0.2 * y_span

    derived_sectors: dict[str, tuple[float, float, float, float, float]] = {
        "front_left": (min_x, mid_x, mid_y, max_y, z_deck),
        "front_right": (min_x, mid_x, min_y, mid_y, z_deck),
        "front_center": (min_x, mid_x, mid_y - y_center_half, mid_y + y_center_half, z_deck),
        "rear_left": (mid_x, max_x, mid_y, max_y, z_deck),
        "rear_right": (mid_x, max_x, min_y, mid_y, z_deck),
        "center": (min_x + 0.25 * (max_x - min_x), max_x - 0.25 * (max_x - min_x), mid_y - y_center_half, mid_y + y_center_half, z_deck),
        "table_top": (min_x, max_x, min_y, max_y, z_deck),
    }

    if sector_lower in derived_sectors:
        return derived_sectors[sector_lower]
    for sec_key, sec_bounds in derived_sectors.items():
        if sec_key in sector_lower or sector_lower in sec_key:
            return sec_bounds

    # Default fallback to overall fixture bounds
    return known


def transform_sector_bounds_to_world(
    sec_bounds: tuple[float, float, float, float, float],
    parent_pos: tuple[float, float, float] | list[float],
    parent_rot_xyzw: tuple[float, float, float, float] | list[float] | None = None,
) -> tuple[float, float, float, float, float]:
    """Transform local sector bounds [min_x, max_x, min_y, max_y, z_deck] to world coordinate AABB bounds.

    Transforms the 4 2D corner vertices of the local XY sector box by the parent yaw rotation
    and translates by parent position.
    """
    p_x = float(parent_pos[0]) if len(parent_pos) > 0 else 0.0
    p_y = float(parent_pos[1]) if len(parent_pos) > 1 else 0.0
    p_z = float(parent_pos[2]) if len(parent_pos) > 2 else 0.0

    yaw = 0.0
    if parent_rot_xyzw is not None and len(parent_rot_xyzw) == 4:
        from isaaclab_arena.utils.yaw import yaw_from_quat_xyzw
        yaw = yaw_from_quat_xyzw(tuple(parent_rot_xyzw))

    lx_min, lx_max, ly_min, ly_max, lz = sec_bounds
    if abs(yaw) > 1e-4:
        c, s = math.cos(yaw), math.sin(yaw)
        corners = [
            (lx_min, ly_min),
            (lx_min, ly_max),
            (lx_max, ly_min),
            (lx_max, ly_max),
        ]
        world_corners_x = [c * x - s * y + p_x for x, y in corners]
        world_corners_y = [s * x + c * y + p_y for x, y in corners]
        w_min_x = min(world_corners_x)
        w_max_x = max(world_corners_x)
        w_min_y = min(world_corners_y)
        w_max_y = max(world_corners_y)
    else:
        w_min_x = lx_min + p_x
        w_max_x = lx_max + p_x
        w_min_y = ly_min + p_y
        w_max_y = ly_max + p_y

    w_z = lz + p_z if lz != 0.0 else 0.0
    return (w_min_x, w_max_x, w_min_y, w_max_y, w_z)


def validate_support_containment(spec: ArenaEnvGraphSpec) -> list[str]:
    """Check if objects placed on fixtures lie within the fixture surface perimeter and assigned sector."""
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

                # If patch with polygon hull is available, check 2D containment
                try:
                    patch = resolve_fixture_support_patch(parent.registry_name)
                    if patch and patch.usable_polygon_hull:
                        import shapely.geometry
                        poly = shapely.geometry.Polygon(patch.usable_polygon_hull)
                        pt = shapely.geometry.Point(rel_x, rel_y)
                        if not poly.contains(pt) and not poly.touches(pt):
                            errors.append(
                                f"[GeometricOracle] Object '{child.id}' relative position [{rel_x:.2f}, {rel_y:.2f}] "
                                f"lies outside introspected support polygon of '{parent.id}'. "
                                f"Place '{child.id}' on '{parent.id}' within valid bounds."
                            )
                            continue
                except Exception:
                    pass

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
                    continue

                # Check for collision with permanent structural workstation fixtures (e.g. grey bin on packing table)
                collides_fixture = False
                for excl_name, em_x, eM_x, em_y, eM_y in FIXTURE_STRUCTURAL_EXCLUSIONS.get(parent.registry_name, []):
                    if em_x <= rel_x <= eM_x and em_y <= rel_y <= eM_y:
                        errors.append(
                            f"[GeometricOracle] Object '{child.id}' relative position [{rel_x:.2f}, {rel_y:.2f}] "
                            f"collides with permanent workstation fixture '{excl_name}' on '{parent.id}' "
                            f"(fixture occupies X in [{em_x:.2f}..{eM_x:.2f}], Y in [{em_y:.2f}..{eM_y:.2f}]). "
                            f"Reposition '{child.id}' to clear table surface."
                        )
                        collides_fixture = True
                        break
                if collides_fixture:
                    continue

                surface_sector = (
                    (rel.params.get("surface_sector") or rel.params.get("surface_anchor")) if rel.params else None
                )
                if surface_sector:
                    sec_bounds = get_fixture_sector_bounds(parent.registry_name, str(surface_sector))
                    if (
                        rel_x < sec_bounds[0] - 1e-4
                        or rel_x > sec_bounds[1] + 1e-4
                        or rel_y < sec_bounds[2] - 1e-4
                        or rel_y > sec_bounds[3] + 1e-4
                    ):
                        errors.append(
                            f"[GeometricOracle] Object '{child.id}' relative position [{rel_x:.2f}, {rel_y:.2f}] "
                            f"lies outside assigned sector '{surface_sector}' on '{parent.id}' "
                            f"(allowed X in [{sec_bounds[0]:.2f}..{sec_bounds[1]:.2f}], "
                            f"Y in [{sec_bounds[2]:.2f}..{sec_bounds[3]:.2f}])."
                        )
    return errors


def compute_world_embodiment_exclusion_zones(
    spec: ArenaEnvGraphSpec,
) -> list[tuple[str, float, float, float, float]]:
    """Compute world-frame 3D exclusion zones from embodiment initial pose and kinematic profile.

    Returns:
        List of (zone_label, world_x, world_y, world_z, radius_m).
    """
    if not spec.embodiment:
        return []

    emb_pose = spec.embodiment.params.get("initial_pose", {}) if spec.embodiment.params else {}
    base_pos = emb_pose.get("position_xyz", [0.0, 0.0, 0.0])
    if len(base_pos) < 3:
        base_pos = [base_pos[0], base_pos[1], 0.0] if len(base_pos) == 2 else [0.0, 0.0, 0.0]

    # Parse quaternion: support rotation_xyzw, orientation_xyzw, orientation_wxyz, rotation_wxyz
    quat_xyzw = (0.0, 0.0, 0.0, 1.0)
    for q_key in ("rotation_xyzw", "orientation_xyzw", "quat_xyzw"):
        if q_key in emb_pose and len(emb_pose[q_key]) == 4:
            q = emb_pose[q_key]
            quat_xyzw = (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
            break
    else:
        for q_key in ("orientation_wxyz", "rotation_wxyz", "quat_wxyz"):
            if q_key in emb_pose and len(emb_pose[q_key]) == 4:
                q = emb_pose[q_key]
                quat_xyzw = (float(q[1]), float(q[2]), float(q[3]), float(q[0]))
                break

    R = _quat_to_rotation_matrix(quat_xyzw[0], quat_xyzw[1], quat_xyzw[2], quat_xyzw[3])

    from isaaclab_arena.agentic_environment_generation.policy_capability_graph import (
        get_embodiment_capability_profile,
    )

    profile = get_embodiment_capability_profile(spec.embodiment.registry_name)
    local_spheres = profile.resting_local_exclusion_spheres if profile else []

    # If no profile found, fall back to default for droid/franka
    if not local_spheres:
        emb_lower = spec.embodiment.registry_name.lower()
        if "droid" in emb_lower or "franka" in emb_lower:
            local_spheres = [(0.3467, -0.10, 0.75, 0.06)]

    world_zones: list[tuple[str, float, float, float, float]] = []
    for idx, (dx, dy, dz, radius) in enumerate(local_spheres):
        local_vec = np.array([dx, dy, dz], dtype=np.float64)
        rot_vec = R @ local_vec
        wx = float(base_pos[0] + rot_vec[0])
        wy = float(base_pos[1] + rot_vec[1])
        wz = float(base_pos[2] + rot_vec[2])
        label = f"{spec.embodiment.registry_name}_ee_{idx}"
        world_zones.append((label, wx, wy, wz, radius))

    return world_zones


def validate_kinematic_reachability(spec: ArenaEnvGraphSpec) -> list[str]:
    """Check if robot base pose can reach task-relevant pick objects and destinations."""
    errors: list[str] = []
    if not spec.embodiment:
        return errors

    emb_pose = spec.embodiment.params.get("initial_pose", {}) if spec.embodiment.params else {}
    emb_pos = emb_pose.get("position_xyz")
    if emb_pos is None or len(emb_pos) < 2:
        return errors

    embodiment_tokens = spec.embodiment.registry_name.lower().split("_")
    is_humanoid = "g1" in embodiment_tokens or "gr1" in embodiment_tokens
    max_reach = 0.95 if is_humanoid else 0.85
    min_reach = 0.25

    world_exclusion_zones = compute_world_embodiment_exclusion_zones(spec)

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
                    "or adjust robot base position."
                )
            elif dist < min_reach:
                errors.append(
                    f"[KinematicOracle] Task object '{obj.id}' is at distance {dist:.2f}m (too close, within robot body"
                    f" collider). Maintain minimum distance of {min_reach:.2f}m."
                )
            for _label, ee_x, ee_y, ee_z, ee_radius in world_exclusion_zones:
                if len(obj_pos) >= 3 and abs(obj_pos[2] - ee_z) <= 0.20:
                    ee_dist = math.hypot(obj_pos[0] - ee_x, obj_pos[1] - ee_y)
                    if ee_dist < ee_radius:
                        errors.append(
                            f"[KinematicOracle] Task object '{obj.id}' at [{obj_pos[0]:.2f}, {obj_pos[1]:.2f}] "
                            f"collides with resting end-effector exclusion zone [{ee_x:.2f}, {ee_y:.2f}] "
                            f"(distance {ee_dist:.3f}m < {ee_radius:.2f}m clearance). "
                            f"Move '{obj.id}' away from resting gripper initialization zone."
                        )
            if is_humanoid and len(emb_pos) >= 3 and len(obj_pos) >= 3:
                if "g1" in spec.embodiment.registry_name.lower().split("_"):
                    pelvis_z = frame_height(emb_pos, "pelvis")
                else:
                    # Preserve the legacy GR1 assumption; G1 metadata is not a GR1 contract.
                    pelvis_z = emb_pos[2] + 0.75 if emb_pos[2] < 0.2 else emb_pos[2]
                rel_z = obj_pos[2] - pelvis_z
                if rel_z > 0.45 or rel_z < -0.35:
                    errors.append(
                        f"[KinematicOracle] Humanoid '{spec.embodiment.id}' pelvis height Z={pelvis_z:.2f}m is"
                        f" misaligned with object '{obj.id}' at Z={obj_pos[2]:.2f}m (relative delta {rel_z:.2f}m"
                        " outside reachable range [-0.35m, +0.45m]). Adjust robot standing elevation or workstation"
                        " surface height."
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
                "It will spawn floating ungrounded. Add an explicit 'on' relation to the support fixture."
            )
    return errors


def relax_spec_spatial_factor_graph(
    spec: ArenaEnvGraphSpec,
) -> tuple[ArenaEnvGraphSpec, RelaxationResultList]:
    """Construct and relax a continuous SpatialFactorGraph over the spec's entities and relations."""
    diagnostics: list[str] = []
    if not spec.background:
        return spec, RelaxationResultList(diagnostics, converged=True, residual=0.0, iterations=0)

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
            init_p = (
                obj.params.get("initial_pose", {}).get("position_xyz", [0.0, 0.6, floor_z])
                if obj.params
                else [0.0, 0.6, floor_z]
            )
            fg.add_variable(obj.id, [init_p[0], init_p[1], init_p[2], 0.0], is_fixed=False)
            fg.add_ground_factor(obj.id, floor_z=floor_z)
        elif any(k in obj_lower for k in ("bin", "basket", "tray", "box")):
            receptacle_ids.add(obj.id)

    # 3. Add Robot Embodiment
    if spec.embodiment:
        emb_id = spec.embodiment.id
        default_emb_x = -0.15 if "maple_table" in bg_lower else -0.55
        init_emb = (
            spec.embodiment.params.get("initial_pose", {}).get("position_xyz", [default_emb_x, 0.0, floor_z])
            if spec.embodiment.params
            else [default_emb_x, 0.0, floor_z]
        )
        fg.add_variable(emb_id, [init_emb[0], init_emb[1], init_emb[2], 0.0], is_fixed=False)
        fg.add_ground_factor(emb_id, floor_z=floor_z)

    # 4. Add Manipulands & Receptacles
    default_obj_z = floor_z + (0.0 if "maple_table" in bg_lower else 0.75)
    for obj in spec.objects:
        if obj.id in furniture_ids:
            continue
        obj_z = default_obj_z
        for rel in spec.relations:
            if rel.kind == "on" and rel.subject == obj.id and rel.reference:
                p_reg = (
                    spec.background.registry_name
                    if rel.reference == bg_name
                    else next((o.registry_name for o in spec.objects if o.id == rel.reference), "table")
                )
                sec = (rel.params.get("surface_sector") or rel.params.get("surface_anchor")) if rel.params else None
                bnds = get_fixture_sector_bounds(p_reg, sec)
                p_z = 0.0
                if rel.reference in furniture_ids:
                    p_obj = next((o for o in spec.objects if o.id == rel.reference), None)
                    if p_obj and p_obj.params and "initial_pose" in p_obj.params:
                        p_z = p_obj.params["initial_pose"]["position_xyz"][2]
                obj_z = p_z + bnds[4]
                break

        init_p = (
            obj.params.get("initial_pose", {}).get("position_xyz", [0.0, 0.0, obj_z])
            if obj.params
            else [0.0, 0.0, obj_z]
        )
        fg.add_variable(obj.id, [init_p[0], init_p[1], init_p[2], 0.0], is_fixed=False)

    # 5. Connect Factors from Relations
    for rel in spec.relations:
        if rel.kind == "on" and rel.reference:
            parent_reg = (
                spec.background.registry_name
                if rel.reference == bg_name
                else next((o.registry_name for o in spec.objects if o.id == rel.reference), "table")
            )
            sector = (rel.params.get("surface_sector") or rel.params.get("surface_anchor")) if rel.params else None
            # On tabletop environments, default unassigned manipulands to front_center and receptacles to front_left
            if not sector and (
                "table" in parent_reg.lower() or "desk" in parent_reg.lower() or "counter" in parent_reg.lower()
            ):
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
            fg.add_reachability_factor(spec.embodiment.id, obj_id, target_distance=0.55, tolerance=0.15)
        # Prevent robot colliding with furniture
        for furn_id in furniture_ids:
            fg.add_clearance_factor(spec.embodiment.id, furn_id, min_distance=0.45)
        # Prevent items colliding with resting end-effector exclusion zones
        exclusion_zones = compute_world_embodiment_exclusion_zones(spec)
        for z_label, z_x, z_y, z_z, z_radius in exclusion_zones:
            fg.add_variable(z_label, [z_x, z_y, z_z, 0.0], is_fixed=True)
            for obj_id in placeable_objs:
                fg.add_clearance_factor(obj_id, z_label, min_distance=z_radius + 0.04)

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

    return spec, RelaxationResultList(
        diagnostics,
        converged=result.converged,
        residual=result.total_energy,
        iterations=result.iterations,
        unresolved_factors=result.conflicting_factors,
    )


def _proposal_supports(spec: ArenaEnvGraphSpec, target_id: str) -> list[tuple[str, dict]]:
    """Resolve explicit support contracts, falling back only to the task's named background."""
    supports = [
        (rel.reference, rel.params)
        for rel in spec.relations
        if rel.kind == "on" and rel.subject == target_id and rel.reference
    ]
    supports.extend(
        (
            rel.target_id,
            {
                "surface_sector": rel.surface_sector,
                "surface_anchor": rel.surface_anchor,
                "contact_normal": rel.contact_normal,
                "delta_z": (rel.delta_z.min_val, rel.delta_z.max_val),
            },
        )
        for rel in spec.reified_relations or []
        if rel.relation_type == "PLACED_ON" and rel.source_id == target_id
    )
    if not supports:
        # Saved C1 v32 declares anchored poses, not an `on` relation. Its task names the table.
        backgrounds = {
            task.params.get("background_scene")
            for task in spec.task.subtasks
            if task.params.get("pick_up_object") == target_id
        }
        if backgrounds == {spec.background.id}:
            supports.append((spec.background.id, {}))
    return supports


def relax_spec_active_inference(
    spec: ArenaEnvGraphSpec,
    parent_env_name: str | None = None,
    eval_id: str | None = None,
    temperature: float = 0.08,
    cooling_rate: float = 0.98,
    max_iters: int = 150,
    *,
    feedback: dict | None = None,
    allowed_mutations: Collection[str] = (),
    allow_anchor_motion: bool = False,
    max_displacement_m: float = 0.02,
    seed: int | None = None,
    feedback_fetcher: Callable[..., dict | None] | None = None,
    env_version: str | None = None,
    reifier_id: str | None = None,
) -> tuple[ArenaEnvGraphSpec, list[str]]:
    """Return an unverified, copy-on-write XY proposal, not a causal correction or accepted scene.

    Args:
        spec: Immutable source scene; only a deep copy can be changed.
        parent_env_name: Exact environment name used by the legacy feedback reader.
        eval_id: Optional evaluation identity passed to the feedback reader.
        temperature: Gradient-noise scale (not a calibrated posterior temperature).
        cooling_rate: Per-step noise decay.
        max_iters: Numerical proposal iteration budget.
        feedback: Injected dx/dy/dz mapping; an empty mapping means no feedback.
        allowed_mutations: Must explicitly name only the unique task pick target.
        allow_anchor_motion: Explicitly permit that target's anchored pose to change.
        max_displacement_m: Positive XY Euclidean trust radius in metres.
        seed: Local solver seed; does not modify the global random state.
        feedback_fetcher: Optional read-only feedback provider; None uses the Neo4j reader.
        env_version: Immutable graph version required by the Neo4j reader.
        reifier_id: Exact target support relation required by the Neo4j reader.

    Returns:
        Independent spec copy and diagnostics. Rejected proposals leave the copy unchanged.
        All proposals require simulator validation; task, physics, Z and rotations are preserved.
    """
    assert (
        math.isfinite(max_displacement_m) and max_displacement_m > 0
    ), "max_displacement_m must be finite and positive"
    diagnostics: list[str] = []
    spec = spec.model_copy(deep=True)
    if not spec.background:
        return spec, diagnostics

    # Query empirical feedback mutation from Neo4j
    query_env = parent_env_name or spec.env_name
    try:
        if feedback is None:
            if feedback_fetcher is None:
                from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import (
                    fetch_recurrent_feedback_from_neo4j,
                )

                feedback_fetcher = fetch_recurrent_feedback_from_neo4j
            qualifiers = {}
            if env_version is not None:
                qualifiers["env_version"] = env_version
            if reifier_id is not None:
                qualifiers["reifier_id"] = reifier_id
            feedback = feedback_fetcher(env_name=query_env, eval_id=eval_id, **qualifiers)
    except Exception as exc:
        diagnostics.append(f"[ActiveInferenceOracle] Neo4j feedback query failed: {exc}")

    if not feedback:
        diagnostics.append("[ActiveInferenceOracle] No feedback; unchanged proposal.")
        return spec, diagnostics

    try:
        measured = np.asarray([feedback[key] for key in ("dx", "dy", "dz")], dtype=float)
        assert measured.shape == (3,) and np.isfinite(measured).all(), "expected finite dx/dy/dz"
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        diagnostics.append(f"[ActiveInferenceOracle] Rejected feedback: {exc}.")
        return spec, diagnostics

    anchors = {rel.subject for rel in spec.relations if rel.kind == "is_anchor"}
    if not allowed_mutations or (not allow_anchor_motion and anchors.intersection(allowed_mutations)):
        diagnostics.append("[ActiveInferenceOracle] No permitted motion; anchors remain fixed by default.")
        return spec, diagnostics

    task_targets = {task.params.get("pick_up_object") for task in spec.task.subtasks}
    task_targets.discard(None)
    if len(task_targets) != 1 or set(allowed_mutations) != task_targets:
        diagnostics.append("[ActiveInferenceOracle] Rejected: only the unique task pick target may move.")
        return spec, diagnostics
    target_id = next(iter(task_targets))
    assert isinstance(target_id, str), "pick target must be an object id"
    target = next((obj for obj in spec.objects if obj.id == target_id), None)
    if target is None:
        diagnostics.append("[ActiveInferenceOracle] Rejected: pick target is not an object.")
        return spec, diagnostics

    reifier_ids = {rel.reifier_id for rel in spec.reified_relations or [] if rel.source_id == target_id}
    if feedback.get("reifier_id") is not None and feedback["reifier_id"] not in reifier_ids:
        diagnostics.append("[ActiveInferenceOracle] Rejected feedback for an unknown or different target relation.")
        return spec, diagnostics

    assets = {asset.id: asset for asset in [spec.background, spec.embodiment, *spec.objects]}
    positions = {}
    try:
        for asset in assets.values():
            position = np.asarray(asset.params["initial_pose"]["position_xyz"], dtype=float)
            assert position.shape == (3,) and np.isfinite(position).all(), f"invalid pose for '{asset.id}'"
            positions[asset.id] = position
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        diagnostics.append(f"[ActiveInferenceOracle] Rejected missing or invalid scene pose: {exc}.")
        return spec, diagnostics
    initial = positions[target_id]
    xy_min = initial[:2] - max_displacement_m
    xy_max = initial[:2] + max_displacement_m
    support_factors = []
    supports = _proposal_supports(spec, target_id)
    try:
        assert supports, "support is unresolved"
        for parent_id, params in supports:
            parent = assets[parent_id]
            parent_pose = parent.params["initial_pose"]
            parent_xyz = np.asarray(parent_pose["position_xyz"], dtype=float)
            quat = np.asarray(parent_pose.get("rotation_xyzw", [0, 0, 0, 1]), dtype=float)
            assert np.isfinite(parent_xyz).all(), "non-finite support pose"
            assert (
                quat.shape == (4,) and np.allclose(quat[:3], 0) and np.isclose(abs(quat[3]), 1)
            ), "rotated support requires measured geometry"
            assert any(key in parent.registry_name.lower() for key in KNOWN_FIXTURE_BOUNDS), "unknown support geometry"
            assert np.allclose(
                params.get("contact_normal", (0, 0, 1)), (0, 0, 1)
            ), "only horizontal support is implemented"
            sector = params.get("surface_sector") or params.get("surface_anchor")
            if sector:
                assert any(
                    sector in sectors
                    for name, sectors in FIXTURE_SECTOR_BOUNDS.items()
                    if name in parent.registry_name.lower()
                ), "unresolved support sector or anchor"
            bounds = get_fixture_sector_bounds(parent.registry_name, sector)
            margin = max(0.04, float(params.get("edge_margin_m", 0.04)))
            xy_min = np.maximum(xy_min, parent_xyz[:2] + [bounds[0] + margin, bounds[2] + margin])
            xy_max = np.minimum(xy_max, parent_xyz[:2] + [bounds[1] - margin, bounds[3] - margin])
            deck_z = float(params.get("nominal_height", parent_xyz[2] + bounds[4]))
            z_min, z_max = params.get("delta_z", (0.0, 0.10))
            assert z_min - 1e-6 <= initial[2] - deck_z <= z_max + 1e-6, "support height conflicts with fixed object Z"
            assert np.all(initial[:2] >= xy_min) and np.all(
                initial[:2] <= xy_max
            ), "initial target lies outside support bounds"
            # Preserve the existing object-origin/contact offset rather than snapping its center to the deck.
            support_factors.append((parent_id, (*bounds[:4], initial[2] - parent_xyz[2]), margin))
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        diagnostics.append(f"[ActiveInferenceOracle] Rejected support contract: {exc}.")
        return spec, diagnostics

    delta = measured.copy()
    delta[2] = 0.0
    length = math.hypot(*delta[:2])
    if length > max_displacement_m:
        delta *= max_displacement_m / length
    delta[:2] = np.clip(initial[:2] + delta[:2], xy_min, xy_max) - initial[:2]
    if not np.any(delta):
        diagnostics.append("[ActiveInferenceOracle] No XY feedback; unchanged proposal (Z is fixed).")
        return spec, diagnostics

    fg = SpatialFactorGraph()
    for asset_id, position in positions.items():
        bounds = (xy_min[0], xy_max[0], xy_min[1], xy_max[1]) if asset_id == target_id else None
        fg.add_variable(asset_id, position.tolist(), is_fixed=asset_id != target_id, bounds=bounds)
    for parent_id, bounds, margin in support_factors:
        fg.add_support_factor(target_id, parent_id, bounds, edge_margin=margin)
    fg.add_empirical_reach_likelihood_factor(
        spec.embodiment.id,
        target_id,
        tuple(delta),
        sigma=(0.05, 0.05, 0.05),
        weight=1.0,
    )
    result = fg.relax_stochastic(
        max_iters=max_iters,
        lr=0.0003,
        temperature=temperature,
        cooling_rate=cooling_rate,
        seed=seed,
    )
    candidate = np.asarray(result.poses.get(target_id, []), dtype=float)
    if (
        not result.converged
        or not math.isfinite(result.total_energy)
        or candidate.size < 3
        or not np.isfinite(candidate).all()
    ):
        diagnostics.append("[ActiveInferenceOracle] Rejected unconverged or non-finite solver proposal.")
        return spec, diagnostics

    shift = np.clip(candidate[:2], xy_min, xy_max) - initial[:2]
    length = float(np.linalg.norm(shift))
    if length > max_displacement_m:
        shift *= max_displacement_m / length
    # The solver supplies an XY proposal, never a change to the support height or orientation.
    target.params["initial_pose"]["position_xyz"] = [
        float(initial[0] + shift[0]),
        float(initial[1] + shift[1]),
        float(initial[2]),
    ]
    diagnostics.append(
        f"[ActiveInferenceOracle] Unverified bounded XY proposal for '{target_id}'; "
        "hand residual is not a causal object displacement. Requires simulator re-evaluation; "
        "robot, fixtures, camera, receptacles, Z, rotations, task and physics are unchanged."
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


def project_pose_to_safe_support_surface(
    spec: ArenaEnvGraphSpec,
    object_id: str,
    preferred_sector: str | None = None,
) -> tuple[list[float], str]:
    """Project an object's position onto the nearest collision-free interior point of its support surface.

    Args:
        spec: Environment graph specification.
        object_id: Identifier of the target object to place or repair.
        preferred_sector: Optional sector preference (e.g. 'front_right', 'front_left').

    Returns:
        (safe_position_xyz, resolved_sector) tuple.
    """
    import shapely.geometry
    import shapely.ops

    # 1. Locate target object and its current position
    obj = next((o for o in spec.objects if o.id == object_id), None)
    curr_pos = [0.0, 0.0, 0.75]
    if obj and obj.params and "initial_pose" in obj.params:
        p = obj.params["initial_pose"].get("position_xyz")
        if p and len(p) >= 2:
            curr_pos = [float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.75]

    # 2. Determine support fixture and sector
    support_id = spec.background.id if spec.background else "table"
    support_reg = spec.background.registry_name if spec.background else "table"
    assigned_sector = preferred_sector

    for rel in spec.relations:
        if rel.subject == object_id and rel.kind == "on" and rel.reference:
            support_id = rel.reference
            if spec.background and rel.reference == spec.background.id:
                support_reg = spec.background.registry_name
            else:
                ref_obj = next((o for o in spec.objects if o.id == rel.reference), None)
                if ref_obj:
                    support_reg = ref_obj.registry_name
            if not assigned_sector and rel.params:
                assigned_sector = rel.params.get("surface_sector") or rel.params.get("surface_anchor")
            break

    if not assigned_sector:
        assigned_sector = "front_right" if curr_pos[1] < 0 else "front_left"

    # 3. Derive 2D support deck polygon and elevation
    patch = None
    try:
        patch = resolve_fixture_support_patch(support_reg)
    except Exception:
        pass

    deck_z = 0.75
    support_poly = None

    if patch and patch.usable_polygon_hull:
        deck_z = float(patch.elevation_z)
        raw_poly = shapely.geometry.Polygon(patch.usable_polygon_hull)
        if raw_poly.is_valid and not raw_poly.is_empty:
            support_poly = raw_poly.buffer(-0.02)

    if support_poly is None or support_poly.is_empty:
        sec_bounds = get_fixture_sector_bounds(support_reg, assigned_sector)
        min_x, max_x, min_y, max_y, deck_z = sec_bounds
        support_poly = shapely.geometry.box(min_x + 0.03, min_y + 0.03, max_x - 0.03, max_y - 0.03)

    # 4. Subtract exclusion zones (embodiment resting EE and links, and workstation fixtures)
    feasible_region = support_poly
    ee_zones = compute_world_embodiment_exclusion_zones(spec)
    for _label, ex, ey, ez, er in ee_zones:
        if abs(deck_z - ez) <= 0.20:
            exclusion_disc = shapely.geometry.Point(ex, ey).buffer(er + 0.03)
            feasible_region = feasible_region.difference(exclusion_disc)

    for _excl_name, em_x, eM_x, em_y, eM_y in FIXTURE_STRUCTURAL_EXCLUSIONS.get(support_reg, []):
        fixture_box = shapely.geometry.box(em_x - 0.02, em_y - 0.02, eM_x + 0.02, eM_y + 0.02)
        feasible_region = feasible_region.difference(fixture_box)

    # 5. Subtract sibling objects on the same support surface
    for other in spec.objects:
        if other.id != object_id:
            o_pos = other.params.get("initial_pose", {}).get("position_xyz") if other.params else None
            if o_pos and len(o_pos) >= 2:
                sibling_disc = shapely.geometry.Point(o_pos[0], o_pos[1]).buffer(0.08)
                feasible_region = feasible_region.difference(sibling_disc)

    # 6. Project current (x, y) to nearest point in feasible_region
    target_pt = shapely.geometry.Point(curr_pos[0], curr_pos[1])

    if feasible_region.is_empty or feasible_region.area < 1e-4:
        rep = support_poly.representative_point()
        safe_x, safe_y = float(rep.x), float(rep.y)
    elif feasible_region.contains(target_pt):
        safe_x, safe_y = curr_pos[0], curr_pos[1]
    else:
        interior_region = feasible_region.buffer(-0.01)
        region_to_query = interior_region if (interior_region.is_valid and not interior_region.is_empty) else feasible_region
        _, nearest = shapely.ops.nearest_points(target_pt, region_to_query)
        safe_x, safe_y = float(nearest.x), float(nearest.y)

    # 7. Check if safe coordinate passes spatial geometry bounds
    bounds = get_known_fixture_bounds(support_reg)
    edge_inset = 0.06
    min_x = bounds[0] + edge_inset
    max_x = bounds[1] - edge_inset
    min_y = bounds[2] + edge_inset
    max_y = bounds[3] - edge_inset

    # For tabletop fixtures, enforce safe near-field deck envelope (|Y| <= 0.15m)
    if "table" in support_reg.lower() or "desk" in support_reg.lower():
        min_y = max(min_y, -0.15)
        max_y = min(max_y, 0.15)

    safe_x = max(min_x, min(max_x, safe_x))
    safe_y = max(min_y, min(max_y, safe_y))

    # Ensure outside resting EE
    for _label, ex, ey, ez, er in ee_zones:
        if abs(deck_z - ez) <= 0.20:
            d = math.hypot(safe_x - ex, safe_y - ey)
            if d < er + 0.02:
                shift_dir = np.array([safe_x - ex, safe_y - ey])
                dist = float(np.linalg.norm(shift_dir))
                if dist > 1e-4:
                    shift_dir = shift_dir / dist
                else:
                    shift_dir = np.array([-1.0, -1.0]) / math.sqrt(2)
                target_dist = er + 0.025
                safe_x = ex + shift_dir[0] * target_dist
                safe_y = ey + shift_dir[1] * target_dist
                safe_x = max(min_x, min(max_x, safe_x))
                safe_y = max(min_y, min(max_y, safe_y))

    # Ensure outside workstation structural fixtures (e.g. grey bin on packing table)
    for _excl_name, em_x, eM_x, em_y, eM_y in FIXTURE_STRUCTURAL_EXCLUSIONS.get(support_reg, []):
        if em_x <= safe_x <= eM_x and em_y <= safe_y <= eM_y:
            if abs(safe_x - em_x) < abs(safe_x - eM_x):
                safe_x = max(min_x, em_x - 0.05)
            else:
                safe_x = min(max_x, eM_x + 0.05)

    return ([round(safe_x, 4), round(safe_y, 4), round(deck_z, 4)], str(assigned_sector))


# Alias for backward compatibility and test ergonomics
project_coordinate_to_support_hull = project_pose_to_safe_support_surface


class SpatialOracleReceipt:
    """Structured receipt from Job J3 (Spatial Geometric & Factor Graph Oracle)."""

    def __init__(
        self,
        *,
        conforms: bool,
        diagnostics: list[str],
        converged: bool = True,
        residual: float = 0.0,
        iterations: int = 0,
        unresolved_factors: list[str] | None = None,
        spec_dict: dict[str, Any] | None = None,
    ) -> None:
        self.conforms = bool(conforms)
        self.diagnostics = list(diagnostics)
        self.converged = bool(converged)
        self.residual = float(residual)
        self.iterations = int(iterations)
        self.unresolved_factors = list(unresolved_factors or [])
        self.spec_dict = spec_dict or {}

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        """Return JSON-serializable receipt payload."""
        return {
            "conforms": self.conforms,
            "diagnostics": self.diagnostics,
            "converged": self.converged,
            "residual": self.residual,
            "iterations": self.iterations,
            "unresolved_factors": self.unresolved_factors,
            "spec_dict": self.spec_dict,
        }


class SpatialGeometricOracleWorker:
    """Job J3 WorkerPort-compatible Spatial Geometric & Factor Graph Oracle."""

    def __init__(self, *, relax_before_validate: bool = True) -> None:
        self.relax_before_validate = relax_before_validate

    def run_oracle(
        self,
        spec: ArenaEnvGraphSpec | dict[str, Any],
        *,
        relax: bool | None = None,
    ) -> tuple[ArenaEnvGraphSpec, SpatialOracleReceipt]:
        """Run factor-graph relaxation and spatial geometric validation on a candidate spec."""
        if isinstance(spec, dict):
            parsed = ArenaEnvGraphSpec.from_dict(spec)
        else:
            parsed = spec.model_copy(deep=True)

        do_relax = self.relax_before_validate if relax is None else bool(relax)
        converged = True
        residual = 0.0
        iterations = 0
        unresolved: list[str] = []
        diagnostics: list[str] = []

        if do_relax:
            parsed, relax_diag = relax_spec_spatial_factor_graph(parsed)
            diagnostics.extend(relax_diag)
            converged = bool(getattr(relax_diag, "converged", True))
            residual = float(getattr(relax_diag, "residual", 0.0))
            iterations = int(getattr(relax_diag, "iterations", 0))
            unresolved = list(getattr(relax_diag, "unresolved_factors", []))

        conforms, val_diag = validate_spatial_geometry(parsed)
        diagnostics.extend(val_diag)
        receipt = SpatialOracleReceipt(
            conforms=conforms and converged,
            diagnostics=diagnostics,
            converged=converged,
            residual=residual,
            iterations=iterations,
            unresolved_factors=unresolved,
            spec_dict=parsed.model_dump(mode="json"),
        )
        return parsed, receipt

    def prepare(self, fence: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        """Prepare WorkerPort handle for Job J3."""
        import uuid

        wid = f"spatial-oracle-{uuid.uuid4().hex[:8]}"
        handle: dict[str, Any] = {"worker_id": wid, "fence": fence, "request": None}
        return handle, {"worker_id": wid}

    def send(self, handle: dict[str, Any], request: dict[str, Any]) -> None:
        """Accept candidate spec request for factor-graph relaxation and validation."""
        handle["request"] = dict(request)

    def receive(self, handle: dict[str, Any], deadline: float | None = None) -> dict[str, Any]:
        """Execute factor-graph relaxation and spatial validation, returning receipt dict."""
        req = handle.get("request") or {}
        raw_spec = req.get("spec") or req.get("scene") or req
        relax = req.get("relax", self.relax_before_validate)
        _, receipt = self.run_oracle(raw_spec, relax=relax)
        return receipt.model_dump(mode="json")

    def stop_owned(self, handle: dict[str, Any]) -> dict[str, Any]:
        """Release WorkerPort handle cleanly."""
        handle["request"] = None
        return {"worker_id": handle.get("worker_id", "spatial-oracle"), "stopped": True}

