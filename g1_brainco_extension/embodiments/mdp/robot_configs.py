# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

"""Robot-specific configuration constants for the G1 Brainco task."""

from __future__ import annotations

# High friction material path and values for stable grasping
G1_BRAINCO_FINGER_FRICTION_MATERIAL_PATH = "/World/Materials/g1_brainco_high_friction_fingers"
G1_BRAINCO_FINGER_STATIC_FRICTION = 6.0
G1_BRAINCO_FINGER_DYNAMIC_FRICTION = 5.0
G1_BRAINCO_FINGER_PRIM_NAME_MARKERS: tuple[str, ...] = (
    "hand",
    "thumb",
    "index",
    "middle",
    "ring",
    "pinky",
)

# Mild open-arm posture using shoulder joints only.
G1_BRAINCO_OPEN_ARM_JOINT_POS: dict[str, float] = {
    "left_shoulder_roll_joint": 0.0,
    "right_shoulder_roll_joint": 0.0,
    "left_shoulder_yaw_joint": 0.0,
    "right_shoulder_yaw_joint": 0.0,
}

# Scene Layout Constants (Env-local frame)
TABLE_SURFACE_Z = 0.70  # Top of the office_table (based on 0.7 scale)
TABLE_COLLISION_Z_OFFSET = 0.005 # Small airgap for PhysX

# Robot Placement: 2 meters from the table
# The table is at X=0.55. To be 2 meters away from it, robot should be at X = -1.45
ROBOT_INITIAL_POSE_XYZ = (-1.45, 0.0, 0.75)

# Drink Randomization Range (on the table)
DRINK_SPAWN_X_RANGE = (0.5, 0.7)
DRINK_SPAWN_Y_RANGE = (-0.1, 0.1)

# Destination Randomization Range (on the table)
DEST_SPAWN_X_RANGE = (0.55, 0.65)
DEST_SPAWN_Y_RANGE = (0.2, 0.4)
