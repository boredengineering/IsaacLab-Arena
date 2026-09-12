# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Kit app pump and viewport PNG capture helpers (SimApp subprocess only)."""

from __future__ import annotations

from pathlib import Path

from isaaclab_arena.assets.asset_cache import get_arena_asset_cache_dir

PRE_CAPTURE_UPDATES = 5
CAPTURE_DONE_TAIL_UPDATES = 3
CAPTURE_WAIT_MAX_UPDATES = 10
THUMBNAIL_CACHE_SUBDIR = "agentic_env_gen_thumbnails"
SIM_PREVIEW_CACHE_SUBDIR = "agentic_env_gen_sim_preview"


def review_gui_cache_dir(subdir: str) -> Path:
    """Return a mkdir'd cache directory for review GUI SimApp viewport PNGs."""
    cache_dir = get_arena_asset_cache_dir().parent / subdir
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def thumbnail_cache_dir() -> Path:
    """Cache directory for per-node USD thumbnail PNGs."""
    return review_gui_cache_dir(THUMBNAIL_CACHE_SUBDIR)


def sim_preview_cache_dir() -> Path:
    """Cache directory for sim-preview rollout viewport frames."""
    return review_gui_cache_dir(SIM_PREVIEW_CACHE_SUBDIR)


def pump_app(app, *, count: int = 1) -> None:
    """Pump Kit render/UI updates without advancing physics simulation."""
    import carb.settings

    settings = carb.settings.get_settings()
    prev_play = settings.get("/app/player/playSimulations")
    settings.set_bool("/app/player/playSimulations", False)
    try:
        for _ in range(count):
            app.update()
    finally:
        settings.set_bool("/app/player/playSimulations", bool(prev_play) if prev_play is not None else True)


def wait_for_stage_load(app, usd_context, max_updates: int = 600) -> None:
    """Pump frames until stage loading settles (plus a short post-settle tail)."""
    settled = 0
    for _ in range(max_updates):
        pump_app(app)
        # omni.usd's installed _usd.pyi specifies (message, loaded files, total files).
        _msg, loaded_count, total_count = usd_context.get_stage_loading_status()
        if loaded_count >= total_count:
            settled += 1
            if settled >= CAPTURE_DONE_TAIL_UPDATES:
                return
        else:
            settled = 0
    raise TimeoutError("USD stage loading did not settle within the update budget")


def wait_for_capture(app, capture_obj, cache_path: Path, max_updates: int = CAPTURE_WAIT_MAX_UPDATES) -> None:
    """Pump render updates until the capture PNG exists or the budget expires."""
    if capture_obj is None:
        for _ in range(max_updates):
            pump_app(app)
            if cache_path.exists() and cache_path.stat().st_size > 0:
                return
        return

    # File existence is the reliable capture-completion signal.
    future = getattr(capture_obj, "future", None)

    for _ in range(max_updates):
        pump_app(app)
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return
        if future is not None and future.done():
            for _ in range(CAPTURE_DONE_TAIL_UPDATES):
                pump_app(app)
                if cache_path.exists() and cache_path.stat().st_size > 0:
                    return
            return


def capture_viewport_png(
    app,
    cache_path: Path,
    *,
    max_updates: int = CAPTURE_WAIT_MAX_UPDATES,
    pre_capture_updates: int = PRE_CAPTURE_UPDATES,
    resolution: int | None = None,
) -> bytes | None:
    """Capture the active Kit viewport to ``cache_path`` and return PNG bytes."""
    from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport

    viewport = get_active_viewport()
    if viewport is None:
        raise RuntimeError("No active Kit viewport")
    if resolution is not None:
        if type(resolution) is not int or resolution not in (512, 1024):
            raise ValueError("Resolution must be 512 or 1024")
        viewport.resolution = (resolution, resolution)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.unlink(missing_ok=True)
    pump_app(app, count=pre_capture_updates)
    capture_obj = capture_viewport_to_file(viewport, str(cache_path))
    wait_for_capture(app, capture_obj, cache_path, max_updates=max_updates)
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path.read_bytes()
    return None


def frame_targets(app, stage, prim_paths, *, view="isometric", resolution=1024) -> dict:
    """Fit visible target bounds and return auditable camera/target metadata."""
    from omni.kit.viewport.utility import get_active_viewport
    from pxr import Gf, Usd, UsdGeom

    from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.render_identity import camera_pose

    bbox = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render], useExtentsHint=True
    )
    bounds = Gf.Range3d()
    targets = []
    for path in prim_paths:
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.IsValid():
            raise ValueError(f"Camera target does not exist: {path}")
        box = bbox.ComputeWorldBound(prim).ComputeAlignedRange()
        if not box.IsEmpty():
            bounds.UnionWith(box)
            targets.append(str(path))
    if bounds.IsEmpty():
        raise ValueError("Camera targets have no visible geometry")
    lower, upper = tuple(bounds.GetMin()), tuple(bounds.GetMax())
    up_axis = str(UsdGeom.GetStageUpAxis(stage))
    eye, target = camera_pose(lower, upper, view, up_axis)
    camera = UsdGeom.Camera.Define(stage, "/_ReviewCamera")
    camera.CreateFocalLengthAttr(35.0)
    camera.CreateHorizontalApertureAttr(36.0)
    camera.CreateVerticalApertureAttr(36.0)
    distance = (Gf.Vec3d(*eye) - Gf.Vec3d(*target)).GetLength()
    camera.CreateClippingRangeAttr(Gf.Vec2f(max(distance / 10000, 0.0001), max(distance * 10, 100)))
    up = Gf.Vec3d(0, 1, 0) if up_axis.upper() == "Y" else Gf.Vec3d(0, 0, 1)
    transform = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), up).GetInverse()
    xform = UsdGeom.Xformable(camera.GetPrim())
    xform.ClearXformOpOrder()
    xform.MakeMatrixXform().Set(transform)
    viewport = get_active_viewport()
    if viewport is None:
        raise RuntimeError("No active Kit viewport")
    viewport.camera_path = str(camera.GetPath())
    viewport.resolution = (resolution, resolution)
    pump_app(app, count=PRE_CAPTURE_UPDATES)
    units = UsdGeom.GetStageMetersPerUnit(stage)
    return {
        "view": view,
        "resolution": resolution,
        "targets": targets,
        "eye": list(eye),
        "lookat": list(target),
        "bounds": [list(lower), list(upper)],
        "dimensions_m": [(b - a) * units for a, b in zip(lower, upper)],
    }
