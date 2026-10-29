# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""CPU-only camera validation and conservative isolated-thumbnail identities."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import stat
import time
from contextlib import contextmanager
from pathlib import Path

VIEWS = frozenset({"isometric", "front", "side", "top"})
RENDERER_VERSION = "isolated-usd-v2"


def normalize_options(options: dict | None, node_ids: set[str]) -> dict:
    """Validate bounded camera options without changing the scene specification."""
    if options is None:
        options = {}
    if not isinstance(options, dict) or set(options) - {"view", "resolution", "asset_views"}:
        raise ValueError("Invalid render options")
    view = options.get("view", "isometric")
    resolution = options.get("resolution", 1024)
    asset_views = options.get("asset_views", {})
    if not isinstance(view, str) or view not in VIEWS:
        raise ValueError("Unsupported view")
    if type(resolution) is not int or resolution not in (512, 1024):
        raise ValueError("Resolution must be 512 or 1024")
    if not isinstance(asset_views, dict) or len(asset_views) > 256:
        raise ValueError("asset_views must be a bounded object")
    if any(k not in node_ids or not isinstance(v, str) or v not in VIEWS for k, v in asset_views.items()):
        raise ValueError("asset_views must refer to known nodes and supported views")
    return {"view": view, "resolution": resolution, "asset_views": dict(sorted(asset_views.items()))}


def thumbnail_identity(
    *,
    registry_name,
    params,
    dependencies,
    view,
    resolution,
    renderer_version,
    target="",
    asset_revision=None,
    resolved_render=None,
) -> str | None:
    """Hash constructor, camera and local dependency bytes; unverifiable dependencies miss.

    Remote URLs (including mutable Nucleus/S3 URLs) are not revisions. The caller
    must supply the complete USD dependency closure, including textures. Missing
    or unresolved dependencies deliberately disable raw image reuse.
    """
    fingerprints = []
    for dependency in dependencies:
        path = Path(dependency)
        if not path.is_absolute() or not path.is_file():
            return None
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        fingerprints.append((str(path), digest))
    if not fingerprints:
        return None
    payload = dict(
        registry_name=registry_name,
        params=params,
        resolved_render=resolved_render,
        dependencies=sorted(fingerprints),
        view=view,
        resolution=resolution,
        renderer_version=renderer_version,
        implementation=RENDERER_VERSION,
        target=target,
        asset_revision=asset_revision,
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _owned(path, kind):
    try:
        info = path.lstat()
        return info if info.st_uid == os.getuid() and kind(info.st_mode) else None
    except FileNotFoundError:
        return None


@contextmanager
def raw_cache_write_lease(cache_dir: Path, *, blocking=True):
    """Serialize raw receipt publication and pruning; process exit releases the lease."""
    cache_dir = cache_dir.absolute()
    if not _owned(cache_dir, stat.S_ISDIR) or cache_dir.resolve() != cache_dir:
        raise OSError("Raw cache is not a real owned directory")
    # Lock the cache directory inode itself: no per-entry lease files or stale
    # lock-file cleanup can split writer/pruner ownership after a crash.
    fd = os.open(cache_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or not stat.S_ISDIR(info.st_mode):
            raise OSError("Raw cache lease is not an owned directory")
        acquired = False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            acquired = True
        except BlockingIOError:
            if blocking:
                raise
        yield acquired
    finally:
        os.close(fd)


def prune_raw_cache(
    cache_dir: Path, *, max_entries=128, max_bytes=256 * 1024 * 1024, max_age_s=7 * 24 * 60 * 60, now=None
):
    """Bound owned receipt/temp groups, including legacy crash leftovers, without following links."""
    cache_dir = cache_dir.absolute()
    if not _owned(cache_dir, stat.S_ISDIR) or cache_dir.resolve() != cache_dir:
        return
    with raw_cache_write_lease(cache_dir, blocking=False) as acquired:
        if acquired:
            _prune_raw_cache(cache_dir, max_entries=max_entries, max_bytes=max_bytes, max_age_s=max_age_s, now=now)


def _prune_raw_cache(cache_dir, *, max_entries, max_bytes, max_age_s, now):
    now = time.time() if now is None else now
    groups = {}
    for path in cache_dir.iterdir():
        # Keep final receipts and in-flight pairs separate; orphan JSONs and old
        # UUID .tmp files must also consume the byte, count and age budgets.
        if not re.fullmatch(r"[a-f0-9]{64}(?:\.tmp)?\.(?:png|json)|[a-f0-9]{32}\.tmp", path.name):
            continue
        info = _owned(path, stat.S_ISREG)
        if info:
            groups.setdefault(path.stem, []).append((path, info))
    total = sum(info.st_size for group in groups.values() for _, info in group)
    count = len(groups)
    for group in sorted(groups.values(), key=lambda group: max(info.st_mtime_ns for _, info in group)):
        if max(info.st_mtime for _, info in group) < now - max_age_s or count > max_entries or total > max_bytes:
            for path, info in group:
                current = _owned(path, stat.S_ISREG)
                if current and (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino):
                    path.unlink(missing_ok=True)
                    total -= info.st_size
            count -= 1


def camera_pose(lower, upper, view="isometric", up_axis="Z"):
    """Fit finite bounds in a square 36mm-aperture, 35mm-focal-length camera."""
    if view not in VIEWS:
        raise ValueError("Unsupported view")
    if not all(math.isfinite(float(v)) for v in (*lower, *upper)) or any(a > b for a, b in zip(lower, upper)):
        raise ValueError("Invalid visual bounds")
    center = tuple((a + b) / 2 for a, b in zip(lower, upper))
    radius = math.sqrt(sum((b - a) ** 2 for a, b in zip(lower, upper))) / 2
    if radius <= 1e-8:
        raise ValueError("Target has no visible extent")
    directions = {"isometric": (1, -1, 0.8), "front": (0, -1, 0), "side": (1, 0, 0), "top": (0, -0.001, 1)}
    direction = directions[view]
    if str(up_axis).upper() == "Y":
        direction = (direction[0], direction[2], -direction[1])
    distance = radius / math.sin(math.atan(18 / 35)) * 1.15
    norm = math.sqrt(sum(v * v for v in direction))
    eye = tuple(c + v * distance / norm for c, v in zip(center, direction))
    return eye, center
