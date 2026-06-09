# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations
from isaaclab_arena.assets.register import register_asset
from isaaclab_arena.embodiments.g1.g1 import G1WBCJointEmbodiment

import os

@register_asset
class G1BraincoCustomEmbodiment(G1WBCJointEmbodiment):
    """Custom G1 embodiment for Brainco tasks.
    
    Inherits from G1WBCJointEmbodiment to ensure action, observation, and 
    event configs are properly initialized for the G1 robot.
    """
    
    name = "g1_brainco_custom"

    def __init__(
        self,
        enable_cameras: bool = False,
        initial_pose = None,
        concatenate_observation_terms: bool = False,
        arm_mode = None,
        lock_waist: bool = True,
    ):
        super().__init__(
            enable_cameras=enable_cameras,
            initial_pose=initial_pose,
            lock_waist=lock_waist,
        )
        
        # Try both casing variations for the robot
        path_variants = [
            "data/g1_with_brainco_hands.usd",
            "/workspaces/IsaacLab-Arena/data/g1_with_brainco_hands.usd",
            "/workspaces/isaaclab_arena/data/g1_with_brainco_hands.usd"
        ]
        
        usd_path = None
        for p in path_variants:
            if os.path.exists(p):
                usd_path = p
                print(f"[G1 Brainco Extension] Found robot at: {p}")
                break
        
        if usd_path is None:
            print(f"[G1 Brainco Extension] ERROR: Could not find g1_with_brainco_hands.usd in any of: {path_variants}")
            usd_path = path_variants[0]

        # Point to the custom USD using the resolved path
        self.scene_config.robot.spawn.usd_path = usd_path

        # Override the hands actuator joint names to match Brainco convention
        # The base G1_CFG uses ".*_hand_.*" which doesn't exist in the Brainco model.
        self.scene_config.robot.actuators["hands"].joint_names_expr = [
            ".*_(index|middle|pinky|ring|thumb)_.*"
        ]
