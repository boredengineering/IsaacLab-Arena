# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Isolated USD thumbnails; failures are scoped to individual graph nodes."""

from __future__ import annotations

import hashlib
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdUtils

from isaaclab_arena.assets.registries import AssetRegistry
from isaaclab_arena.environment_spec.arena_env_graph_conversion_utils import instantiate_assets_from_spec
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.asset_usd import (
    AabbDimensionsM,
    aabb_dimensions_from_asset,
    absolute_prim_path,
    object_reference_cache_key,
    resolve_aabb_dimensions_m,
    resolve_node_usd_paths,
    usd_cache_key,
)
from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.axis_overlay import (
    axis_length_from_extents,
    local_xyz_axis_segments,
    overlay_rgb_segments_on_png,
)
from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.kit_viewport import (
    PRE_CAPTURE_UPDATES,
    capture_viewport_png,
    frame_targets,
    pump_app,
    set_viewport_camera_eye_lookat,
    thumbnail_cache_dir,
    wait_for_stage_load,
)
from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.render_identity import (
    RENDERER_VERSION,
    normalize_options,
    prune_raw_cache,
    raw_cache_write_lease,
    thumbnail_identity,
)
from isaaclab_arena_examples.agentic_environment_generation.review_gui.spec_visualization.asset_cards import (
    object_set_member_key,
)

PANORAMA_CAMERA_PRIM_PATH = "/World/_ReviewPanoramaCamera"
PANORAMA_EYE_HEIGHT_M = 1.55
PANORAMA_ROTATION_XYZ_DEG = (90.0, 0.0, 0.0)
# Extra pump frames after restoring the pinhole camera so the RTX renderer drops the
# fisheyeSpherical projection before an object_reference is captured on the same stage.
PANORAMA_RESTORE_PUMP_UPDATES = PRE_CAPTURE_UPDATES + 5
_AXIS_LINE_WIDTH_PX = 4


@dataclass
class _UsdSnapshotJob:
    """Queued captures that share one opened parent USD stage."""

    usd_path: str
    viewer_cfg: object | None = None
    asset_captures: list[tuple[str, Path]] = field(default_factory=list)
    ref_captures: list[tuple[str, str, Path]] = field(default_factory=list)
    panorama_captures: list[tuple[str, Path]] = field(default_factory=list)


def _error(errors, node_id, stage, exc):
    errors.append({"id": node_id, "stage": stage, "code": type(exc).__name__, "message": str(exc)})
    print(f"[thumbnail_capture] {node_id} {stage}: {exc}", file=sys.stderr)


def _construct_asset(node, registry, *, embodiment=False, background=False):
    """Materialize one constructor without letting a broken peer erase its result."""
    from isaaclab_arena.environment_spec.arena_env_graph_conversion_utils import _parse_pose_data

    params = dict(node.params)
    pose = _parse_pose_data(params.pop("initial_pose", None))
    joints = params.pop("initial_joint_pos", None) if embodiment else None
    friction = params.pop("finger_contact_friction", None) if embodiment else None
    if not embodiment and not background:
        params.setdefault("instance_name", node.id)
    if pose is not None and (embodiment or background):
        params["initial_pose"] = pose
    asset = registry.get_asset_by_name(node.registry_name)(**params)
    if joints is not None:
        asset.set_joint_initial_pos(joints)
    if friction is not None:
        asset.set_finger_contact_friction(**friction)
    return asset


def _dependencies(usd_path):
    """Return a complete local USD/texture closure or an unverifiable sentinel."""
    if not Path(usd_path).is_file():
        return []
    layers, assets, unresolved = UsdUtils.ComputeAllDependencies(usd_path)
    # A warm Kit process retains Sdf layers. Reload their on-disk content before
    # trusting the dependency closure: a changed root can point at a new texture.
    for layer in layers:
        if layer.realPath and Path(layer.realPath).is_file():
            layer.Reload(force=True)
    layers, assets, unresolved = UsdUtils.ComputeAllDependencies(usd_path)
    if unresolved:
        return []
    return [*(layer.realPath for layer in layers), *assets]


def _cache_read(path, metadata_path, resolution):
    """Reject symlinks, partial PNGs, or bytes that differ from the capture receipt."""
    try:
        if path.is_symlink() or metadata_path.is_symlink():
            return None
        metadata = json.loads(metadata_path.read_text())
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != metadata["sha256"]:
            return None
        from PIL import Image

        with Image.open(path) as image:
            if image.format != "PNG" or image.size != (resolution, resolution):
                return None
            image.verify()
        return data, metadata["capture"]
    except (OSError, ValueError, KeyError):
        return None


def _isolate_subtree(stage, target_path):
    """Hide siblings along the target's ancestry, retaining its transforms and lighting."""
    target = Sdf.Path(target_path)
    for prim in stage.Traverse():
        path = prim.GetPath()
        if path.HasPrefix(target) or target.HasPrefix(path):
            continue
        if prim.HasAPI(UsdLux.LightAPI):
            continue
        imageable = UsdGeom.Imageable(prim)
        if imageable:
            imageable.MakeInvisible()


def render_thumbnails_with_app(
    app,
    spec: ArenaEnvGraphSpec,
    *,
    background_panorama: bool | None = None,
    options=None,
    output_dir: Path | None = None,
    cache_dir: Path | None = None,
    renderer_version=RENDERER_VERSION,
    asset_revision=None,
    errors: list | None = None,
    timings: dict | None = None,
    manifest: dict | None = None,
) -> tuple[dict[str, Path], dict[str, AabbDimensionsM]]:
    """Capture isolated assets with optional web diagnostics; retain the Streamlit tuple API.

    When ``background_panorama`` is explicitly passed (Streamlit review GUI server), runs
    the batch snapshot/panorama/axis-overlay pipeline. Otherwise runs the dependency-verified
    isolated asset capture pipeline.
    """
    if background_panorama is not None:
        return _render_review_gui_thumbnails_with_app(
            app,
            spec,
            background_panorama=background_panorama,
        )

    import omni.usd

    errors = errors if errors is not None else []
    timings = timings if timings is not None else {}
    manifest = manifest if manifest is not None else {}
    nodes = [spec.background, spec.embodiment, *spec.objects]
    refs = list(spec.object_references or [])
    options = normalize_options(options, {n.id for n in [*nodes, *refs]})
    cache_dir = Path(cache_dir) if cache_dir is not None else thumbnail_cache_dir()
    output_dir = Path(output_dir) if output_dir is not None else cache_dir / ("capture-" + uuid.uuid4().hex)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    registry, assets, paths, dimensions = AssetRegistry(), {}, {}, {}
    node_by_id = {node.id: node for node in nodes}
    for node in nodes:
        started = time.monotonic()
        try:
            assets[node.id] = _construct_asset(
                node, registry, embodiment=node.id == spec.embodiment.id, background=node.id == spec.background.id
            )
        except Exception as exc:
            _error(errors, node.id, "constructor", exc)
        timings[f"constructor:{node.id}_s"] = time.monotonic() - started
    usd_paths = resolve_node_usd_paths(assets, list(assets))
    dependencies = {}
    for node in [*nodes, *refs]:
        started = time.monotonic()
        try:
            parent_id = node.parent_id if node in refs else node.id
            asset = assets.get(parent_id)
            usd_path = usd_paths.get(parent_id)
            if not usd_path:
                raise ValueError("Asset has no supported USD spawn (or its constructor failed)")
            parent_node = node_by_id[parent_id]
            view = options["asset_views"].get(node.id, options["view"])
            # Freeze resolved constructor defaults before lookup, then render exactly
            # those values. Authored params alone omit registry/spawn default scale.
            scale = getattr(asset, "scale", None)
            if scale is None:
                robot = getattr(getattr(asset, "scene_config", None), "robot", None)
                scale = getattr(getattr(robot, "spawn", None), "scale", None)
            scale = tuple(float(value) for value in scale) if scale is not None else (1.0, 1.0, 1.0)
            parent_name = asset.name if node in refs else None
            if usd_path not in dependencies:
                try:
                    dependencies[usd_path] = _dependencies(usd_path)
                except Exception as exc:
                    # Cache discovery is not a prerequisite for a fresh render.
                    print(f"[thumbnail_capture] dependency fingerprint unavailable: {exc}", file=sys.stderr)
                    dependencies[usd_path] = []
            identity = thumbnail_identity(
                registry_name=parent_node.registry_name,
                params={"parent": parent_node.params, "reference": node.params if node in refs else None},
                resolved_render={"scale": scale, "parent_name": parent_name},
                dependencies=dependencies[usd_path],
                view=view,
                resolution=options["resolution"],
                renderer_version=renderer_version,
                target=node.prim_path if node in refs else "",
                # The RPC revision describes the entire scene bundle. Raw reuse is
                # instead anchored to this asset's complete local dependency bytes.
                asset_revision=None,
            )
            # Never form paths from node IDs: Streamlit callers need not have web ID validation.
            filename = hashlib.sha256(node.id.encode()).hexdigest() + ".png"
            destination = output_dir / filename
            cached = cache_dir / f"{identity}.png" if identity else None
            metadata_path = cache_dir / f"{identity}.json" if identity else None
            hit = _cache_read(cached, metadata_path, options["resolution"]) if cached else None
            if hit:
                data, capture = hit
                destination.write_bytes(data)  # An owned regular file, never a cache symlink.
            else:
                ctx = omni.usd.get_context()
                if not ctx.open_stage(usd_path):
                    raise RuntimeError(f"Could not open asset USD: {usd_path}")
                wait_for_stage_load(app, ctx)
                stage = ctx.get_stage()
                # Camera, visibility, and scale changes must never mutate source USD files.
                stage.SetEditTarget(stage.GetSessionLayer())
                root = absolute_prim_path(stage, "")
                if scale != (1, 1, 1):
                    UsdGeom.Xformable(stage.GetPrimAtPath(root)).AddScaleOp(opSuffix="preview").Set(Gf.Vec3d(*scale))
                target = absolute_prim_path(stage, node.prim_path, parent_name=parent_name) if node in refs else root
                if node in refs:
                    _isolate_subtree(stage, target)
                _ensure_default_lighting(stage)
                ctx.get_selection().clear_selected_prim_paths()
                capture = frame_targets(app, stage, [target], view=view, resolution=options["resolution"])
                capture.update({
                    "usd_path": usd_path,
                    "target": target,
                    "pose": "authored_usd",
                    "isolated": node in refs or node.id != spec.background.id,
                })
                data = capture_viewport_png(app, destination, resolution=options["resolution"])
                if not data:
                    raise RuntimeError("Viewport capture did not produce a PNG")
                if cached:
                    token = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
                    temporary = cache_dir / (token + ".tmp.png")
                    metadata_temp = cache_dir / (token + ".tmp.json")
                    try:
                        with raw_cache_write_lease(cache_dir):
                            try:
                                temporary.write_bytes(data)
                                temporary.replace(cached)
                                metadata_temp.write_text(
                                    json.dumps({"sha256": hashlib.sha256(data).hexdigest(), "capture": capture})
                                )
                                metadata_temp.replace(metadata_path)
                            finally:
                                temporary.unlink(missing_ok=True)
                                metadata_temp.unlink(missing_ok=True)
                    except OSError as exc:
                        _error(errors, node.id, "cache", exc)
            paths[node.id] = destination
            dimensions[node.id] = tuple(capture["dimensions_m"])
            manifest[node.id] = {
                **capture,
                "cache_hit": bool(hit),
                "cache_key": identity,
                "cache_policy": "local_dependency_bytes" if identity else "unverifiable_dependencies_no_reuse",
            }
        except Exception as exc:
            _error(errors, node.id, "thumbnail", exc)
        finally:
            timings[f"asset:{node.id}_s"] = time.monotonic() - started
    try:
        prune_raw_cache(cache_dir)
    except OSError as exc:
        _error(errors, "assets", "cache_retention", exc)
    return paths, dimensions


def _render_review_gui_thumbnails_with_app(
    app,
    spec: ArenaEnvGraphSpec,
    *,
    background_panorama: bool = False,
) -> tuple[dict[str, Path], dict[str, AabbDimensionsM]]:
    """Render cache-missed node thumbnails and return png paths plus AABB sizes in meters."""
    assets_by_node_id = instantiate_assets_from_spec(spec, AssetRegistry())
    # Exclude embodiment from thumbnail rendering.
    assets_by_node_id.pop(spec.embodiment.id)
    asset_node_ids = [spec.background.id, *(obj.id for obj in spec.objects)]
    asset_paths = resolve_node_usd_paths(assets_by_node_id, asset_node_ids)
    # Object sets hold one USD per member rather than a single usd_path, so resolve them separately
    # and snapshot every member.
    member_paths, member_dimensions = _resolve_object_set_members(spec, assets_by_node_id)
    asset_paths.update(member_paths)
    background_viewer_cfg = assets_by_node_id[spec.background.id].get_viewer_cfg()

    cache_dir = thumbnail_cache_dir()

    thumbnail_paths: dict[str, Path] = {}
    jobs_by_usd: dict[str, _UsdSnapshotJob] = {}
    asset_render_count = 0
    panorama_render_count = 0
    ref_render_count = 0
    for node_id, usd_path in asset_paths.items():
        use_panorama = background_panorama and node_id == spec.background.id
        if use_panorama:
            cache_path = cache_dir / f"{usd_cache_key(usd_path)}_panorama.png"
            if cache_path.exists() and cache_path.stat().st_size > 0:
                thumbnail_paths[node_id] = cache_path
            else:
                job = jobs_by_usd.setdefault(usd_path, _UsdSnapshotJob(usd_path=usd_path))
                job.panorama_captures.append((node_id, cache_path))
                panorama_render_count += 1
            continue

        cache_path = cache_dir / f"{usd_cache_key(usd_path)}.png"
        if cache_path.exists() and cache_path.stat().st_size > 0:
            thumbnail_paths[node_id] = cache_path
        else:
            job = jobs_by_usd.setdefault(usd_path, _UsdSnapshotJob(usd_path=usd_path))
            if node_id == spec.background.id:
                job.viewer_cfg = background_viewer_cfg
            job.asset_captures.append((node_id, cache_path))
            asset_render_count += 1

    for ref in spec.object_references or []:
        if ref.prim_path is None:
            continue
        usd_path = asset_paths.get(ref.parent_id)
        if not usd_path:
            continue
        relative_prim_path = ref.prim_path.lstrip("/")
        cache_path = cache_dir / f"{object_reference_cache_key(usd_path, relative_prim_path)}.png"
        if cache_path.exists() and cache_path.stat().st_size > 0:
            thumbnail_paths[ref.id] = cache_path
        else:
            job = jobs_by_usd.setdefault(usd_path, _UsdSnapshotJob(usd_path=usd_path))
            if ref.parent_id == spec.background.id:
                job.viewer_cfg = background_viewer_cfg
            job.ref_captures.append((ref.id, relative_prim_path, cache_path))
            ref_render_count += 1

    jobs = list(jobs_by_usd.values())
    if not asset_paths and not jobs and not thumbnail_paths:
        print("[thumbnail_capture] no asset USD paths resolved; skipping thumbnail rendering.", file=sys.stderr)
        return {}, {}

    if jobs:
        print(
            f"[thumbnail_capture] rendering {asset_render_count} asset, "
            f"{panorama_render_count} panorama, and "
            f"{ref_render_count} object_reference thumbnail(s) "
            f"(reusing {len(thumbnail_paths)} from cache)...",
            file=sys.stderr,
        )
        captured = _capture_usd_snapshot_jobs(app, jobs)
        for node_id, cache_path in [
            *((nid, cp) for job in jobs for nid, cp in job.asset_captures),
            *((nid, cp) for job in jobs for nid, cp in job.panorama_captures),
            *((nid, cp) for job in jobs for nid, _rel, cp in job.ref_captures),
        ]:
            if node_id in captured and cache_path.exists() and cache_path.stat().st_size > 0:
                thumbnail_paths[node_id] = cache_path
    else:
        print(f"[thumbnail_capture] all {len(thumbnail_paths)} thumbnail(s) served from cache.", file=sys.stderr)

    aabb_dimensions_m = resolve_aabb_dimensions_m(assets_by_node_id)
    aabb_dimensions_m.update(member_dimensions)
    return thumbnail_paths, aabb_dimensions_m


def _resolve_object_set_members(
    spec: ArenaEnvGraphSpec, assets_by_node_id: dict[str, Any]
) -> tuple[dict[str, str], dict[str, AabbDimensionsM]]:
    """Return the USD path and AABB of every object-set member, keyed so each gets its own card."""
    usd_paths: dict[str, str] = {}
    dimensions: dict[str, AabbDimensionsM] = {}
    for object_set in spec.object_sets or []:
        live_object_set = assets_by_node_id[object_set.id]
        members = zip(object_set.members, live_object_set.member_usd_paths, live_object_set.objects)
        for registry_name, usd_path, member_asset in members:
            member_key = object_set_member_key(object_set.id, registry_name)
            usd_paths[member_key] = usd_path
            member_dimensions = aabb_dimensions_from_asset(member_asset)
            if member_dimensions is not None:
                dimensions[member_key] = member_dimensions
    return usd_paths, dimensions


def _capture_usd_snapshot_jobs(app, jobs: list[_UsdSnapshotJob]) -> dict[str, bytes]:
    """Open each parent USD once and capture queued asset plus object_reference snapshots."""
    out: dict[str, bytes] = {}
    for job in jobs:
        try:
            out.update(_capture_usd_snapshot_job(app, job))
        except Exception as exc:
            print(f"[thumbnail_capture]   render failed for {job.usd_path}: {exc}", file=sys.stderr)
    return out


def _capture_usd_snapshot_job(app, job: _UsdSnapshotJob) -> dict[str, bytes]:
    """Capture all queued snapshots for one opened parent USD."""
    import omni.usd
    from omni.kit.viewport.utility import frame_viewport_prims, get_active_viewport

    out: dict[str, bytes] = {}
    ctx = omni.usd.get_context()
    if not ctx.open_stage(job.usd_path):
        print(f"[thumbnail_capture]   open_stage failed: {job.usd_path}", file=sys.stderr)
        return out
    stage = ctx.get_stage()
    wait_for_stage_load(app, ctx)
    _ensure_default_lighting(stage)

    if job.asset_captures:
        cache_path = job.asset_captures[0][1]
        png_bytes = _capture_stage_snapshot(
            app,
            cache_path,
            viewer_cfg=job.viewer_cfg,
            axis_prim=_root_prim(stage),
        )
        if png_bytes:
            for node_id, _cache_path in job.asset_captures:
                out[node_id] = png_bytes

    if job.panorama_captures:
        cache_path = job.panorama_captures[0][1]
        png_bytes = _capture_background_panorama(app, stage, cache_path)
        if png_bytes:
            for node_id, _cache_path in job.panorama_captures:
                out[node_id] = png_bytes

    if job.ref_captures:
        if job.viewer_cfg is not None:
            _apply_viewer_cfg(app, job.viewer_cfg)
        _set_collision_mesh_visualization(enabled=True)
        try:
            for node_id, relative_prim_path, cache_path in job.ref_captures:
                root_path = absolute_prim_path(stage, relative_prim_path)
                omni.usd.get_context().get_selection().set_selected_prim_paths([root_path], True)
                pump_app(app, count=PRE_CAPTURE_UPDATES)
                viewport = get_active_viewport()
                framed = frame_viewport_prims(viewport, prims=[root_path])
                if not framed:
                    print(
                        f"[thumbnail_capture]   warning: frame_viewport_prims failed for {root_path}",
                        file=sys.stderr,
                    )
                png_bytes = _capture_with_origin_axes(app, stage.GetPrimAtPath(root_path), cache_path)
                if png_bytes:
                    out[node_id] = png_bytes
                else:
                    print(
                        f"[thumbnail_capture]   capture produced no file for {relative_prim_path}: {cache_path}",
                        file=sys.stderr,
                    )
        finally:
            omni.usd.get_context().get_selection().clear_selected_prim_paths()
            _set_collision_mesh_visualization(enabled=False)

    return out


def _root_prim(stage):
    """Return the stage default prim, or the stage root when unset."""
    prim = stage.GetDefaultPrim()
    if prim and prim.IsValid():
        return prim
    return stage.GetPrimAtPath(Sdf.Path("/"))


def _capture_stage_snapshot(
    app,
    cache_path: Path,
    *,
    viewer_cfg,
    axis_prim,
) -> bytes | None:
    """Capture the active viewport for an already-open stage."""
    from omni.kit.viewport.utility import frame_viewport_prims, get_active_viewport

    if viewer_cfg is not None:
        _apply_viewer_cfg(app, viewer_cfg)
    else:
        viewport = get_active_viewport()
        framed = frame_viewport_prims(viewport, prims=[str(axis_prim.GetPath())])
        if not framed:
            print(
                f"[thumbnail_capture]   warning: frame_viewport_prims failed for {axis_prim.GetPath()}",
                file=sys.stderr,
            )

    return _capture_with_origin_axes(app, axis_prim, cache_path)


def _capture_with_origin_axes(app, prim, cache_path: Path) -> bytes | None:
    """Capture the viewport, then composite always-on-top XYZ axis lines onto the PNG."""
    from omni.kit.viewport.utility import get_active_viewport

    png_bytes = capture_viewport_png(app, cache_path)
    if png_bytes is None or prim is None or not prim.IsValid():
        return png_bytes

    viewport = get_active_viewport()
    image_size = tuple(int(v) for v in viewport.resolution)
    segments_px = _project_prim_xyz_axes_to_pixels(prim, image_size=image_size)
    if not segments_px:
        return png_bytes

    overlaid = overlay_rgb_segments_on_png(png_bytes, segments_px, width_px=_AXIS_LINE_WIDTH_PX)
    cache_path.write_bytes(overlaid)
    return overlaid


def _project_prim_xyz_axes_to_pixels(
    prim,
    *,
    image_size: tuple[int, int],
) -> list[tuple[tuple[int, int], tuple[int, int], tuple[int, int, int]]]:
    """Project local XYZ axis segments for ``prim`` into image-pixel line segments."""
    from omni.kit.viewport.utility import get_active_viewport

    origin, x_dir, y_dir, z_dir = _prim_local_axes_world(prim)
    length_m = axis_length_from_extents(_prim_world_aabb_extents(prim))
    world_segments = local_xyz_axis_segments(origin, x_dir=x_dir, y_dir=y_dir, z_dir=z_dir, length_m=length_m)
    viewport = get_active_viewport()
    viewport_size = tuple(int(v) for v in viewport.resolution)
    segments: list[tuple[tuple[int, int], tuple[int, int], tuple[int, int, int]]] = []
    for start, end, color in world_segments:
        start_px = _world_to_image_pixel(viewport, start, image_size=image_size, viewport_size=viewport_size)
        end_px = _world_to_image_pixel(viewport, end, image_size=image_size, viewport_size=viewport_size)
        if start_px is None or end_px is None:
            continue
        rgb = tuple(int(round(c * 255.0)) for c in color[:3])
        segments.append((start_px, end_px, rgb))
    return segments


def _world_to_image_pixel(
    viewport,
    world_xyz: tuple[float, float, float],
    *,
    image_size: tuple[int, int],
    viewport_size: tuple[int, int],
) -> tuple[int, int] | None:
    """Project a world point to PNG pixel coordinates, or None if not projectable."""
    clip = Gf.Vec4d(float(world_xyz[0]), float(world_xyz[1]), float(world_xyz[2]), 1.0) * viewport.world_to_ndc
    if abs(clip[3]) < 1e-9:
        return None
    ndc_x = clip[0] / clip[3]
    ndc_y = clip[1] / clip[3]
    ndc_z = clip[2] / clip[3]
    if not (-1.5 <= ndc_x <= 1.5 and -1.5 <= ndc_y <= 1.5 and -0.1 <= ndc_z <= 1.1):
        return None

    pixel = viewport.map_ndc_to_texture_pixel(Gf.Vec2d(ndc_x, ndc_y))[0]
    vw, vh = viewport_size
    iw, ih = image_size
    if vw <= 0 or vh <= 0:
        return None
    return (int(round(float(pixel[0]) * iw / vw)), int(round(float(pixel[1]) * ih / vh)))


def _prim_local_axes_world(prim) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    """Return world-space origin and local +X/+Y/+Z basis rows for a prim."""
    world_tf = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(0)
    origin = world_tf.ExtractTranslation()
    return (
        (float(origin[0]), float(origin[1]), float(origin[2])),
        (float(world_tf[0][0]), float(world_tf[0][1]), float(world_tf[0][2])),
        (float(world_tf[1][0]), float(world_tf[1][1]), float(world_tf[1][2])),
        (float(world_tf[2][0]), float(world_tf[2][1]), float(world_tf[2][2])),
    )


def _world_aligned_box(prim):
    """Return the world-space aligned AABB for ``prim``, or None when UsdGeom fails."""
    cache = UsdGeom.BBoxCache(0, [UsdGeom.Tokens.default_])
    try:
        return cache.ComputeWorldBound(prim).ComputeAlignedBox()
    except Exception as exc:
        print(f"[thumbnail_capture]   warning: AABB failed for {prim.GetPath()}: {exc}", file=sys.stderr)
        return None


def _prim_world_aabb_extents(prim) -> tuple[float, float, float]:
    """Return world-space AABB extents ``(x, y, z)`` for ``prim``, or a unit cube fallback."""
    bbox = _world_aligned_box(prim)
    if bbox is None:
        return (1.0, 1.0, 1.0)
    min_pt, max_pt = bbox.GetMin(), bbox.GetMax()
    extents = (
        float(max_pt[0] - min_pt[0]),
        float(max_pt[1] - min_pt[1]),
        float(max_pt[2] - min_pt[2]),
    )
    if max(extents) <= 0.0:
        return (1.0, 1.0, 1.0)
    return extents


def _capture_background_panorama(app, stage, cache_path: Path) -> bytes | None:
    """Capture a raw fisheyeSpherical 360 panorama from the stage centroid."""
    from omni.kit.viewport.utility import get_active_viewport

    if stage.GetPrimAtPath(PANORAMA_CAMERA_PRIM_PATH):
        stage.RemovePrim(Sdf.Path(PANORAMA_CAMERA_PRIM_PATH))

    root = stage.GetDefaultPrim() or stage.GetPseudoRoot()
    bbox = _world_aligned_box(root)
    if bbox is None:
        print(f"[thumbnail_capture]   panorama AABB failed for {root.GetPath()}", file=sys.stderr)
        return None
    min_pt, max_pt = bbox.GetMin(), bbox.GetMax()
    centroid = Gf.Vec3d(
        (min_pt[0] + max_pt[0]) * 0.5,
        (min_pt[1] + max_pt[1]) * 0.5,
        PANORAMA_EYE_HEIGHT_M,
    )

    camera = UsdGeom.Camera.Define(stage, Sdf.Path(PANORAMA_CAMERA_PRIM_PATH))
    xform = UsdGeom.Xformable(camera.GetPrim())
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(centroid)
    xform.AddRotateXYZOp().Set(Gf.Vec3f(*PANORAMA_ROTATION_XYZ_DEG))

    cam_prim = camera.GetPrim()
    cam_prim.CreateAttribute("cameraProjectionType", Sdf.ValueTypeNames.Token).Set("fisheyeSpherical")
    for attr_name, value in (
        ("fthetaWidth", 1024.0),
        ("fthetaHeight", 1024.0),
        ("fthetaMaxFov", 360.0),
    ):
        cam_prim.CreateAttribute(attr_name, Sdf.ValueTypeNames.Float).Set(value)

    viewport = get_active_viewport()
    prior_camera_path = str(viewport.camera_path)
    viewport.camera_path = PANORAMA_CAMERA_PRIM_PATH
    pump_app(app, count=PRE_CAPTURE_UPDATES)

    try:
        png_bytes = capture_viewport_png(app, cache_path, pre_capture_updates=PRE_CAPTURE_UPDATES)
        if png_bytes is None:
            print(f"[thumbnail_capture]   panorama capture produced no file: {cache_path}", file=sys.stderr)
        return png_bytes
    finally:
        if prior_camera_path and prior_camera_path != PANORAMA_CAMERA_PRIM_PATH:
            viewport.camera_path = prior_camera_path
        if stage.GetPrimAtPath(PANORAMA_CAMERA_PRIM_PATH):
            stage.RemovePrim(Sdf.Path(PANORAMA_CAMERA_PRIM_PATH))
        pump_app(app, count=PANORAMA_RESTORE_PUMP_UPDATES)


def _apply_viewer_cfg(app, viewer_cfg) -> None:
    """Point the active viewport camera at ``viewer_cfg`` eye/lookat (world frame)."""
    from omni.kit.viewport.utility import get_active_viewport

    viewport = get_active_viewport()
    set_viewport_camera_eye_lookat(viewport, viewer_cfg.eye, viewer_cfg.lookat)
    pump_app(app, count=PRE_CAPTURE_UPDATES)


def _ensure_default_lighting(stage) -> None:
    """Add neutral dome and key lights to standalone assets."""
    for prim in stage.Traverse():
        if prim.HasAPI(UsdLux.LightAPI):
            return
    dome = UsdLux.DomeLight.Define(stage, Sdf.Path("/_ReviewDomeLight"))
    dome.CreateIntensityAttr(800.0)
    dome.CreateColorAttr(Gf.Vec3f(1.0, 1.0, 1.0))
    key = UsdLux.DistantLight.Define(stage, Sdf.Path("/_ReviewKeyLight"))
    key.CreateIntensityAttr(2500.0)
    key.CreateAngleAttr(2.0)
    UsdGeom.Xformable(key.GetPrim()).AddRotateXYZOp().Set(Gf.Vec3f(-45.0, 30.0, 0.0))


def _set_collision_mesh_visualization(*, enabled: bool) -> None:
    """Toggle viewport Show By Type → Physics → Colliders → Selected."""
    import carb.settings

    settings = carb.settings.get_settings()
    settings.set_bool("/persistent/physics/visualizationCollisionMesh", enabled)
    settings.set_int("/persistent/physics/visualizationDisplayColliders", 1 if enabled else 0)
