# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Resolve instantiated graph assets to USD paths and local AABB dimensions (no Kit viewport)."""

from __future__ import annotations

import hashlib
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isaaclab_arena.assets.object_base import ObjectBase

AabbDimensionsM = tuple[float, float, float]


def aabb_dimensions_from_asset(asset: ObjectBase) -> AabbDimensionsM | None:
    """Return local axis-aligned bounding box size (x, y, z) in meters for one live asset."""
    try:
        bbox = asset.get_bounding_box()
        size = bbox.size[0]
        return (float(size[0]), float(size[1]), float(size[2]))
    except Exception as exc:
        name = getattr(asset, "name", "?")
        print(f"[asset_usd]   {name}: bbox failed: {exc}", file=sys.stderr)
        return None


def resolve_aabb_dimensions_m(assets_by_node_id: dict[str, Any]) -> dict[str, AabbDimensionsM]:
    """Return axis-aligned bounding box sizes in meters for each snapshot asset (objects and references)."""
    dimensions: dict[str, AabbDimensionsM] = {}
    for node_id, asset in assets_by_node_id.items():
        if not callable(getattr(asset, "get_bounding_box", None)):
            continue
        dims = aabb_dimensions_from_asset(asset)
        if dims is not None:
            dimensions[node_id] = dims
    return dimensions


def resolve_node_usd_paths(assets_by_node_id: dict[str, object], node_ids: list[str]) -> dict[str, str]:
    """Map each requested ``node_id`` to its ``usd_path``, skipping assets without one."""
    paths: dict[str, str] = {}
    for node_id in node_ids:
        asset = assets_by_node_id.get(node_id)
        if asset is None:
            print(f"[asset_usd]   {node_id}: not found in instantiated assets, skipping.", file=sys.stderr)
            continue
        usd_path = getattr(asset, "usd_path", None)
        if not usd_path:
            # EmbodimentBase.get_bounding_box uses this same articulation spawn.
            robot = getattr(getattr(asset, "scene_config", None), "robot", None)
            usd_path = getattr(getattr(robot, "spawn", None), "usd_path", None)
        if usd_path:
            paths[node_id] = usd_path
    return paths


def usd_cache_key(usd_path: str) -> str:
    """Return a stable short hash for caching thumbnails keyed by USD path."""
    return hashlib.sha1(usd_path.encode("utf-8")).hexdigest()[:16]


def object_reference_cache_key(usd_path: str, relative_prim_path: str) -> str:
    """Return a stable cache key for an object_reference subtree snapshot."""
    return hashlib.sha1(f"{usd_path}::{relative_prim_path}".encode()).hexdigest()[:16]


def absolute_prim_path(stage, relative_suffix: str, *, parent_name: str | None = None) -> str:
    """Resolve a USD-relative or runtime-namespaced reference, rejecting missing prims."""
    default_prim = stage.GetDefaultPrim()
    if not default_prim or not default_prim.IsValid():
        raise RuntimeError("USD stage has no default prim")
    base = str(default_prim.GetPath())
    suffix = relative_suffix
    if suffix.startswith("{ENV_REGEX_NS}/"):
        # Match ObjectReference.isaaclab_prim_path_to_original_prim_path, with a
        # component boundary ("kitchen2" must not match parent "kitchen").
        prefix = f"{{ENV_REGEX_NS}}/{parent_name}"
        if parent_name is None or not (suffix == prefix or suffix.startswith(prefix + "/")):
            raise ValueError("Reference namespace does not match its parent asset")
        suffix = suffix[len(prefix) :]
    elif suffix == base or suffix.startswith(base + "/"):
        suffix = suffix[len(base) :]
    path = base + ("/" + suffix.lstrip("/") if suffix else "")
    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        raise ValueError(f"Reference prim does not exist: {path}")
    return path
