# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations
from isaaclab_arena.assets.register import register_asset
from isaaclab_arena.embodiments.g1.g1 import G1EmbodimentBase

@register_asset
class G1BraincoCustomEmbodiment(G1EmbodimentBase):
    """Custom G1 embodiment for Brainco tasks."""
    
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
            concatenate_observation_terms=concatenate_observation_terms,
            arm_mode=arm_mode,
        )
        # Here you could override the USD path if needed:
        # self.scene_config.robot.prim_path = "path/to/your/custom_g1.usd"
        
        # Ensure the waist is locked if requested
        if lock_waist:
            # You can customize the joint locking here if the base class 
            # doesn't handle it exactly as you want.
            pass
