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
from pathlib import Path

from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdUtils

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.asset_usd import (
    AabbDimensionsM,
    absolute_prim_path,
    resolve_node_usd_paths,
)
from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.kit_viewport import (
    capture_viewport_png,
    frame_targets,
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

    Embodiments are their configured spawn USD in its authored joint pose, not a
    simulated initial joint configuration. World placement is intentionally absent.
    Raw reuse requires the complete local dependency closure; mutable remote assets
    are rendered again rather than treating their URL as a freshness guarantee.
    """
    import omni.usd

    from isaaclab_arena.assets.registries import AssetRegistry

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
