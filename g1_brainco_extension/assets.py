# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

import os
from isaaclab_arena.assets.register import register_asset
from isaaclab_arena.assets.object_library import LibraryObject

# Base path for local extension data
EXTENSION_DATA_PATH = os.path.join(os.path.dirname(__file__), "data")

@register_asset
class CokeCan(LibraryObject):
    """Custom Coke Can asset."""
    name = "coke_can"
    tags = ["object"]
    usd_path = os.path.join(EXTENSION_DATA_PATH, "coke_can.usd")

@register_asset
class RedSortingBin(LibraryObject):
    """Custom Red Sorting Bin asset."""
    name = "red_sorting_bin"
    tags = ["destination"]
    usd_path = os.path.join(EXTENSION_DATA_PATH, "red_sorting_bin.usd")
