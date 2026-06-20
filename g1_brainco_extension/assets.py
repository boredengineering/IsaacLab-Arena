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
import isaaclab.sim as sim_utils
from isaaclab_arena.assets.register import register_asset
from isaaclab_arena.assets.object_library import LibraryObject
from isaaclab_arena.assets.object_set import RigidObjectSet
from isaaclab_arena.assets.object_utils import RIGID_BODY_PROPS_MEDIUM_PRECISION
from isaaclab.utils.assets import ISAAC_NUCLEUS_DIR, ISAACLAB_NUCLEUS_DIR

# Base path for local extension data
EXTENSION_DATA_PATH = os.path.join(os.path.dirname(__file__), "assets")

@register_asset
class TomatoSoupCan(LibraryObject):
    """Official YCB Tomato Soup Can with physics."""
    name = "tomato_soup_can_custom"
    tags = ["object", "drink"]
    usd_path = f"{ISAAC_NUCLEUS_DIR}/Props/YCB/Axis_Aligned_Physics/005_tomato_soup_can.usd"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.object_cfg.spawn.rigid_props = RIGID_BODY_PROPS_MEDIUM_PRECISION
        self.object_cfg.spawn.mass_props = sim_utils.MassPropertiesCfg(mass=0.35)

@register_asset
class MustardBottle(LibraryObject):
    """Official YCB Mustard Bottle with physics."""
    name = "mustard_bottle_custom"
    tags = ["object", "drink"]
    usd_path = f"{ISAAC_NUCLEUS_DIR}/Props/YCB/Axis_Aligned_Physics/006_mustard_bottle.usd"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.object_cfg.spawn.rigid_props = RIGID_BODY_PROPS_MEDIUM_PRECISION
        self.object_cfg.spawn.mass_props = sim_utils.MassPropertiesCfg(mass=0.4)

@register_asset
class MasterChefCan(LibraryObject):
    """Official YCB Master Chef Can with physics."""
    name = "master_chef_can_custom"
    tags = ["object", "drink"]
    usd_path = f"{ISAAC_NUCLEUS_DIR}/Props/YCB/Axis_Aligned_Physics/002_master_chef_can.usd"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.object_cfg.spawn.rigid_props = RIGID_BODY_PROPS_MEDIUM_PRECISION
        self.object_cfg.spawn.mass_props = sim_utils.MassPropertiesCfg(mass=0.5)

@register_asset
class DrinkObjectSet(RigidObjectSet):
    """A set of drink objects for randomization."""
    name = "drink_object_set"
    def __init__(self):
        assets = [
            TomatoSoupCan(),
            MustardBottle(),
            MasterChefCan(),
        ]
        super().__init__(name=self.name, objects=assets, random_choice=True)

@register_asset
class RedContainer(LibraryObject):
    """Official Isaac Sim Red Container with physics."""
    name = "red_container_custom"
    tags = ["destination"]
    usd_path = f"{ISAACLAB_NUCLEUS_DIR}/Arena/assets/object_library/isaac_container/container_h20_red.usd"
    scale = (0.5, 0.5, 0.5)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.object_cfg.spawn.rigid_props = RIGID_BODY_PROPS_MEDIUM_PRECISION
        self.object_cfg.spawn.mass_props = sim_utils.MassPropertiesCfg(mass=1.0)



# EXAMPLE: Adding an asset from the local 'data' folder
@register_asset
class RedBull(LibraryObject):
    """Red Bull can with physics."""
    name = "redbull"
    tags = ["object", "drink"]
    usd_path = os.path.join(EXTENSION_DATA_PATH, "redbull.usdz")
    scale = (1.0, 1.0, 1.0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.object_cfg.spawn.rigid_props = RIGID_BODY_PROPS_MEDIUM_PRECISION
        self.object_cfg.spawn.mass_props = sim_utils.MassPropertiesCfg(mass=0.3)

@register_asset
class IceBucketMetal(LibraryObject):
    """Metal ice bucket with physics."""
    name = "ice_bucket_metal"
    tags = ["object", "container"]
    usd_path = os.path.join(EXTENSION_DATA_PATH, "ice_bucket_metal.usdz")
    scale = (1.0, 1.0, 1.0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.object_cfg.spawn.rigid_props = RIGID_BODY_PROPS_MEDIUM_PRECISION
        self.object_cfg.spawn.mass_props = sim_utils.MassPropertiesCfg(mass=1.5)
