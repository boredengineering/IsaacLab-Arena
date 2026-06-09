# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations
import os
import numpy as np
from isaaclab_arena.assets.register import register_asset
from isaaclab_arena.embodiments.g1.g1 import G1WBCJointEmbodiment
from g1_brainco_extension.mdp.actions.wbc_action_cfg import G1BraincoWBCActionCfg

@register_asset
class G1BraincoCustomEmbodiment(G1WBCJointEmbodiment):
    """Custom G1 embodiment for Brainco tasks.
    
    This class handles the mapping between the standard G1 Whole Body Controller 
    and the dexterous Brainco hand model.
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
        
        # Robust USD Path resolution
        extension_path = os.path.dirname(os.path.dirname(__file__))
        path_variants = [
            os.path.join(extension_path, "data", "g1_with_brainco_hands.usd"),
            "g1_brainco_extension/data/g1_with_brainco_hands.usd",
            "/workspaces/IsaacLab-Arena/g1_brainco_extension/data/g1_with_brainco_hands.usd",
        ]
        usd_path = next((p for p in path_variants if os.path.exists(p)), path_variants[0])
        self.scene_config.robot.spawn.usd_path = usd_path

        # --- STRUCTURAL WBC FIX ---
        # Switch to the custom WBC action term that handles extra joints without crashing.
        # This replaces the need for global monkey-patching.
        self.action_config.g1_action = G1BraincoWBCActionCfg(
            asset_name="robot", 
            joint_names=[".*"]
        )

        # Override actuator joint expressions for Brainco naming convention
        brainco_regex = ".*(index|middle|pinky|ring|thumb).*"
        
        for name, actuator in self.scene_config.robot.actuators.items():
            if hasattr(actuator, "joint_names_expr"):
                actuator.joint_names_expr = [
                    brainco_regex if expr == ".*_hand_.*" else expr 
                    for expr in actuator.joint_names_expr
                ]

        # Explicitly ensure the "hands" group is covered
        if "hands" in self.scene_config.robot.actuators:
             self.scene_config.robot.actuators["hands"].joint_names_expr = [brainco_regex]
