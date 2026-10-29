# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Retention of server-owned previews; never traverse request paths or symlinks."""

import json
import os
import re
import shutil
import sqlite3
import stat

from isaaclab_arena_examples.agentic_environment_generation.review_gui.simapp.render_identity import prune_raw_cache


def artifact_ids(result):
    ids = set()
    for entry in [*result["assets"], result["scene"]]:
        if entry is not None:
            ids.add(entry["artifact_id"])
            ids.update(variant["artifact_id"] for variant in entry.get("variants", {}).values())
    if not all(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value) for value in ids):
        raise ValueError("Invalid artifact IDs")
    return ids


def owned(path, kind):
    try:
        info = path.lstat()
        return info if info.st_uid == os.getuid() and kind(info.st_mode) else None
    except FileNotFoundError:
        return None


def remove_output(root, output):
    """Delete only a UUID output directory below the real owned renders directory."""
    renders = root / "renders"
    if (
        output.parent != renders
        or not re.fullmatch(r"[a-f0-9]{32}", output.name)
        or not owned(renders, stat.S_ISDIR)
        or renders.resolve() != renders
        or not owned(output, stat.S_ISDIR)
        or output.resolve() != output
    ):
        return
    if shutil.rmtree.avoids_symlink_attacks:
        shutil.rmtree(output)


def cleanup(root, db_path, *, max_receipts, max_bytes, max_age_s, now):
    """Prune oldest receipts and their unshared files while holding the catalogue write lease."""
    files = {}
    for path in root.iterdir():
        if re.fullmatch(r"[a-f0-9]{32}\.png", path.name):
            info = owned(path, stat.S_ISREG)
            if info:
                files[path.stem] = (path, info)
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            "SELECT cache_key, result, created FROM previews ORDER BY created DESC, rowid DESC"
        ).fetchall()
        keep, referenced, evicted = [], set(), set()
        for key, text, created in rows:
            try:
                ids = artifact_ids(json.loads(text))
            except (ValueError, TypeError, KeyError):
                continue
            union = referenced | ids
            size = sum(files[value][1].st_size for value in union if value in files)
            if created >= now - max_age_s and len(keep) < max_receipts and ids <= files.keys() and size <= max_bytes:
                keep.append(key)
                referenced = union
            else:
                evicted.update(ids)
        if keep:
            db.execute(f"DELETE FROM previews WHERE cache_key NOT IN ({','.join('?' for _ in keep)})", keep)
        else:
            db.execute("DELETE FROM previews")
        total = sum(info.st_size for _, info in files.values())
        for value, (path, info) in sorted(files.items(), key=lambda item: item[1][1].st_mtime):
            if value not in referenced and (value in evicted or info.st_mtime < now - max_age_s or total > max_bytes):
                path.unlink(missing_ok=True)
                total -= info.st_size
                db.execute("DELETE FROM artifacts WHERE id=?", (value,))
        # Old pre-versioning receipts cannot be promoted to verified cache hits.
        db.execute("DELETE FROM receipts")
        for (value,) in db.execute("SELECT id FROM artifacts").fetchall():
            if value not in files:
                db.execute("DELETE FROM artifacts WHERE id=?", (value,))
    renders = root / "renders"
    if owned(renders, stat.S_ISDIR) and renders.resolve() == renders:
        for output in renders.iterdir():
            info = owned(output, stat.S_ISDIR)
            if info and info.st_mtime < now - max_age_s:
                remove_output(root, output)
    cache = root / "isolated-thumbnails"
    prune_raw_cache(cache, max_entries=max_receipts, max_bytes=max_bytes // 4, max_age_s=max_age_s, now=now)
