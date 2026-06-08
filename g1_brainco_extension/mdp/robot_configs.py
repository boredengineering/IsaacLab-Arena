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
)
