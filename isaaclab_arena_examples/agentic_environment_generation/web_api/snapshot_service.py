# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Blocking, lazy Isaac snapshot adapter; HTTP callers must use a worker thread."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import struct
import threading
import time
import uuid
import yaml
import zlib
from collections.abc import Callable
from pathlib import Path

from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_process import SnapshotProcess


class SnapshotError(RuntimeError):
    """An actionable snapshot failure, never a substitute image."""


def validated_spec(yaml_text: str):
    """Validate registry-backed YAML without accepting paths or constructor URLs."""
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    if not isinstance(yaml_text, str) or len(yaml_text.encode()) > 256 * 1024:
        raise SnapshotError("Snapshot YAML must be at most 256 KiB")
    try:
        raw = yaml.safe_load(yaml_text)
        if not isinstance(raw, dict) or any(key in raw for key in ("include", "includes", "$include")):
            raise ValueError("Resolve includes through the document service before rendering")
        spec = ArenaEnvGraphSpec.from_dict(raw)
        for token in [
            spec.env_name,
            spec.embodiment.id,
            spec.background.id,
            *(obj.id for obj in spec.objects),
            *(ref.id for ref in spec.object_references or []),
        ]:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", token):
                raise ValueError("Snapshot environment/node IDs must be simple identifiers, not paths")

        def numeric(value, depth=0):
            if depth > 12:
                return False
            if value is None or isinstance(value, bool):
                return True
            if isinstance(value, (int, float)):
                return math.isfinite(value)
            if isinstance(value, (tuple, list)):
                return all(numeric(v, depth + 1) for v in value)
            if isinstance(value, dict):
                return all(isinstance(k, str) and numeric(v, depth + 1) for k, v in value.items())
            return False

        for asset in [spec.embodiment, spec.background, *spec.objects, *(spec.object_references or [])]:
            if not numeric(asset.params):
                raise ValueError(
                    "Snapshot asset params support numeric/bool values only; use trusted registered USD defaults"
                )
        for ref in spec.object_references or []:
            if ref.prim_path and not re.fullmatch(r"(?:\{ENV_REGEX_NS\})?/?[A-Za-z0-9_/]+", ref.prim_path):
                raise ValueError("Object-reference prim_path must be a local USD prim, not a URL or filesystem path")
        return spec
    except (ValueError, AssertionError, TypeError, RecursionError, yaml.YAMLError) as exc:
        raise SnapshotError(f"Invalid snapshot spec: {exc}") from exc


def _owned_file(path: Path, root: Path) -> bytes:
    """Read a bounded regular file without symlinks under an owned directory."""
    if not path.is_absolute() or not path.is_relative_to(root) or path.resolve() != path:
        raise SnapshotError("Renderer artifact escapes its owned output directory")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 32 * 1024 * 1024 or info.st_uid != os.getuid():
            raise SnapshotError("Renderer artifact must be an owned regular PNG below 32 MiB")
        return stream.read(32 * 1024 * 1024 + 1)


class SnapshotService:
    """Own a lazy SimApp renderer and immutable, indexed PNG artifacts.

    Args:
        state_dir: Server-owned workbench state directory, never a request path.
    """

    timeout_s = 210.0

    def __init__(self, state_dir: Path):
        self.root = Path(state_dir).absolute() / "editor-artifacts"
        if self.root.resolve() != self.root:
            raise SnapshotError("Snapshot storage must not contain symlinks")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db_path = self.root / "index.sqlite3"
        if self._db_path.is_symlink():
            raise SnapshotError("Snapshot index must not be a symlink")
        with sqlite3.connect(self._db_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, digest TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS receipts (hash TEXT PRIMARY KEY, result TEXT NOT NULL)")
        self._closed = False
        self._process = SnapshotProcess(self.root)

    def render(self, yaml_text: str, job_id: str, emit: Callable[[str], None]) -> dict:
        """Render a frozen spec, reusing only an exact canonical-spec receipt.

        Args:
            yaml_text: Resolved YAML; includes must be frozen by the document service.
            job_id: Journal correlation identifier; never used as a filesystem path.
            emit: Real stage notifications (no estimated percentages).

        Returns:
            Input hash, asset/scene artifact IDs and authenticated URLs, and warnings.
        """
        deadline = time.monotonic() + self.timeout_s
        if not self._lock.acquire(timeout=self.timeout_s):
            raise SnapshotError("Snapshot queue deadline exceeded; retry when the current render finishes")
        try:
            if self._closed:
                raise SnapshotError("Snapshot service is closed")
            emit("validating_snapshot")
            spec = validated_spec(yaml_text)
            canonical = spec.to_dict()
            digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            with sqlite3.connect(self._db_path) as db:
                row = db.execute("SELECT result FROM receipts WHERE hash=?", (digest,)).fetchone()
            if row:
                cached = json.loads(row[0])
                try:
                    for item in [*cached["assets"], cached["scene"]]:
                        self.artifact_path(item["artifact_id"])
                except KeyError:
                    pass  # Missing/changed files are a cache miss, not stale success.
                else:
                    emit("cache_hit")
                    return cached
            emit("waiting_for_renderer")
            output = self.root / "renders" / uuid.uuid4().hex
            response = self._rpc(
                {
                    "yaml_text": yaml.safe_dump(canonical),
                    "output_dir": str(output),
                    "num_envs": 1,
                    "num_steps": 0,
                    "env_spacing": 3.0,
                },
                deadline,
                emit,
            )
            if not response.get("ok"):
                raise SnapshotError(f"Isaac Sim snapshot failed: {response.get('error', 'unknown renderer error')}")
            if not isinstance(response.get("scene"), str) or not response["scene"]:
                raise SnapshotError("Isaac Sim returned no scene PNG; inspect the renderer log and retry")
            emit("publishing_artifacts")
            assets = []
            warnings = [
                "Embodiment thumbnail is not supported by the existing renderer; the robot appears in the scene."
            ]
            paths = response.get("paths", {})
            for asset in [spec.background, *spec.objects, *(spec.object_references or [])]:
                if asset.id not in paths:
                    warnings.append(f"No thumbnail rendered for {asset.id}.")
                    continue
                entry = {"id": asset.id, **self._publish(Path(paths[asset.id]), output)}
                dims = response.get("aabb_dimensions_m", {}).get(asset.id)
                if dims is not None:
                    entry["dimensions_m"] = dims
                assets.append(entry)
            scene = self._publish(Path(response["scene"]), output)
            result = {"input_hash": digest, "assets": assets, "scene": scene, "warnings": warnings}
            with sqlite3.connect(self._db_path) as db:
                db.execute("INSERT OR REPLACE INTO receipts VALUES (?, ?)", (digest, json.dumps(result)))
            emit("snapshots_ready")
            return result
        finally:
            self._lock.release()

    def _publish(self, source: Path, output: Path) -> dict:
        if not output.is_relative_to(self.root):
            raise SnapshotError("Renderer output must be owned by this service")
        data = _owned_file(source, output)
        if len(data) < 33 or data[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
            raise SnapshotError("Isaac Sim did not produce a PNG")
        width, height = struct.unpack(">II", data[16:24])
        if not (0 < width <= 8192 and 0 < height <= 8192) or b"IEND" not in data[-12:]:
            raise SnapshotError("Invalid or incomplete Isaac Sim PNG")
        offset = 8
        while offset < len(data):
            if len(data) - offset < 12:
                raise SnapshotError("Truncated PNG chunk")
            length = struct.unpack(">I", data[offset : offset + 4])[0]
            end = offset + 8 + length
            if end + 4 > len(data) or zlib.crc32(data[offset + 4 : end]) != struct.unpack(">I", data[end : end + 4])[0]:
                raise SnapshotError("Invalid PNG chunk checksum")
            offset = end + 4
        artifact_id = uuid.uuid4().hex
        target = self.root / f"{artifact_id}.png"
        with target.open("xb") as stream:
            stream.write(data)
        with sqlite3.connect(self._db_path) as db:
            db.execute("INSERT INTO artifacts VALUES (?, ?)", (artifact_id, hashlib.sha256(data).hexdigest()))
        return {"artifact_id": artifact_id, "url": f"/api/editor/artifacts/{artifact_id}"}

    def artifact_path(self, artifact_id: str) -> Path:
        """Resolve only an indexed artifact ID, never a client-supplied path."""
        if not re.fullmatch(r"[a-f0-9]{32}", artifact_id):
            raise KeyError(artifact_id)
        with sqlite3.connect(self._db_path) as db:
            row = db.execute("SELECT digest FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        path = self.root / f"{artifact_id}.png"
        try:
            if hashlib.sha256(_owned_file(path, self.root)).hexdigest() != row[0]:
                raise KeyError(artifact_id)
        except (OSError, SnapshotError) as exc:
            raise KeyError(artifact_id) from exc
        return path

    def _rpc(self, request: dict, deadline: float, emit: Callable[[str], None]) -> dict:
        try:
            return self._process.request(request, deadline, emit)
        except (RuntimeError, OSError) as exc:
            raise SnapshotError(str(exc)) from exc

    def close(self) -> None:
        """Reap this service's renderer; safe to call repeatedly."""
        self._closed = True
        self._process.close()
