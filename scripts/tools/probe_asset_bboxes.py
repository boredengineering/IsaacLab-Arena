# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Print local-frame bounding boxes of the experiment 03 assets (R-1 diagnostic, read-only)."""

from isaaclab.app import AppLauncher

app = AppLauncher(headless=True).app

from pxr import Usd, UsdGeom

from isaaclab_arena.assets.registries import AssetRegistry


def bbox(path: str, scale=(1.0, 1.0, 1.0)):
    stage = Usd.Stage.Open(str(path))
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    r = cache.ComputeWorldBound(stage.GetDefaultPrim()).ComputeAlignedRange()
    lo, hi = r.GetMin(), r.GetMax()
    return [tuple(round(float(v) * s, 3) for v, s in zip(p, scale)) for p in (lo, hi)]


registry = AssetRegistry()
for name in ["microwave", "tomato_soup_can_ycb_robolab", "office_table_background"]:
    cls = registry.get_asset_by_name(name)
    scale = getattr(cls, "scale", (1.0, 1.0, 1.0))
    print(f"[BBOX] {name}: usd={cls.usd_path} scale={scale} min/max={bbox(cls.usd_path, scale)}", flush=True)
app.close()
