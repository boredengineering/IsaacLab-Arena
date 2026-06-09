# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

"""
Custom Asset Registration for G1 Brainco Extension.

This module handles the registration of custom objects into the Arena's AssetRegistry.
Assets defined here can be utilized in environments via CLI arguments (e.g., --object coke_can).

HOW TO BROWSE & ADD SIM-READY ASSETS:
1. Open NVIDIA Isaac Sim / USD Composer.
2. Navigate to 'Window' -> 'Browsers' -> 'SimReady Explorer'.
3. Find an asset and copy its Nucleus path (Right-click -> Copy Path).
4. Create a new class below inheriting from 'LibraryObject'.
5. Use the '@register_asset' decorator.
6. Ensure the USD path uses the correct Nucleus environment variables 
   (e.g., ISAAC_NUCLEUS_DIR or ISAACLAB_NUCLEUS_DIR).
"""

import os
from isaaclab_arena.assets.register import register_asset
from isaaclab_arena.assets.object_library import LibraryObject
from isaaclab.utils.assets import ISAAC_NUCLEUS_DIR, ISAACLAB_NUCLEUS_DIR

# Base path for local extension data (for assets stored within this folder)
EXTENSION_DATA_PATH = os.path.join(os.path.dirname(__file__), "data")

@register_asset
class TomatoSoupCan(LibraryObject):
    """
    Official YCB Tomato Soup Can.
    Replaces 'coke_can' as a physically validated beverage-sized container.
    """
    name = "tomato_soup_can_custom"
    tags = ["object"]
    usd_path = f"{ISAAC_NUCLEUS_DIR}/Props/YCB/Axis_Aligned_Physics/005_tomato_soup_can.usd"

@register_asset
class RedContainer(LibraryObject):
    """
    Official Isaac Sim Red Container.
    Validated storage/destination asset.
    """
    name = "red_container_custom"
    tags = ["destination"]
    usd_path = f"{ISAACLAB_NUCLEUS_DIR}/Arena/assets/object_library/isaac_container/container_h20_red.usd"

# EXAMPLE: Adding an asset from the local 'data' folder
# @register_asset
# class MyCustomObject(LibraryObject):
#     name = "my_object"
#     tags = ["object"]
#     usd_path = os.path.join(EXTENSION_DATA_PATH, "my_model.usd")
