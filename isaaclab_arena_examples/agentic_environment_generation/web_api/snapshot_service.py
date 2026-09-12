# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Blocking, lazy Isaac snapshot adapter; HTTP callers must use a worker thread."""

from __future__ import annotations

import fcntl
import hashlib
import io
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
from contextlib import contextmanager
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.workbench.documents import canonical_digest
from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_process import SnapshotProcess

from .preview_diagnostics import clean_errors, clean_timings
from .preview_identity import digest as identity_digest
from .preview_identity import registry_asset_revision, renderer_revision
from .preview_options import normalized_options
from .preview_retention import cleanup as prune_previews
from .preview_retention import remove_output


class SnapshotError(RuntimeError):
    """An actionable snapshot failure, never a substitute image."""

    def __init__(self, message, *, errors=None, timings=None):
        super().__init__(message)
        self.errors = clean_errors(errors) or [
            {"id": "scene", "stage": "snapshot", "code": "snapshot_failed", "message": str(message)[:1000]}
        ]
        self.timings = clean_timings(timings)


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

    # Cold USD/material loading can exceed three minutes even with zero policy steps.
    timeout_s = 360.0

    def __init__(
        self,
        state_dir: Path,
        *,
        asset_revision=None,
        renderer_version=None,
        max_receipts=256,
        max_bytes=512 * 1024 * 1024,
        max_age_s=30 * 86400,
    ):
        assert 1 <= max_receipts <= 4096 and max_bytes > 0 and max_age_s > 0, "Invalid retention budget"
        self.max_receipts, self.max_bytes, self.max_age_s = max_receipts, max_bytes, max_age_s
        self.root = Path(state_dir).absolute() / "editor-artifacts"
        if self.root.resolve() != self.root:
            raise SnapshotError("Snapshot storage must not contain symlinks")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.asset_revision = asset_revision or registry_asset_revision
        self.renderer_version = renderer_version or renderer_revision()
        self._db_path = self.root / "index.sqlite3"
        if self._db_path.is_symlink():
            raise SnapshotError("Snapshot index must not be a symlink")
        with sqlite3.connect(self._db_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, digest TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS receipts (hash TEXT PRIMARY KEY, result TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS previews (cache_key TEXT PRIMARY KEY, canonical_hash TEXT NOT NULL, options"
                " TEXT NOT NULL, renderer TEXT NOT NULL, canonical TEXT NOT NULL, result TEXT NOT NULL, created REAL"
                " NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS preview_lookup ON previews(canonical_hash, options, renderer)")
        self._closed = False
        self._process = SnapshotProcess(self.root)
        self.cleanup()

    def render(self, yaml_text: str, job_id: str, emit: Callable[[str], None], options=None) -> dict:
        """Render a frozen spec, reusing only an exact canonical-spec receipt.

        Args:
            yaml_text: Resolved YAML; includes must be frozen by the document service.
            job_id: Journal correlation identifier; never used as a filesystem path.
            emit: Real stage notifications (no estimated percentages).

        Returns:
            Input hash, asset/scene artifact IDs and authenticated URLs, and warnings.
        """
        started = time.monotonic()
        deadline = started + self.timeout_s
        if not self._lock.acquire(timeout=self.timeout_s):
            raise SnapshotError("Snapshot queue deadline exceeded; retry when the current render finishes")
        output = None
        lease = self._write_lease(deadline)
        leased = False
        try:
            lease.__enter__()
            leased = True
            if self._closed:
                raise SnapshotError("Snapshot service is closed")
            validation_started = time.monotonic()
            measured = {"queue_s": validation_started - started}
            emit("validating_snapshot")
            spec = validated_spec(yaml_text)
            canonical = spec.to_dict()
            options = normalized_options(options, canonical)
            measured["validation_s"] = time.monotonic() - validation_started
            lookup_started = time.monotonic()
            digest = canonical_digest(canonical)
            revision = self.asset_revision(canonical)
            cache_key = identity_digest([digest, self.renderer_version, revision, options])
            cached = self.lookup(digest, options)
            measured["lookup_s"] = time.monotonic() - lookup_started
            if cached is not None:
                emit("cache_hit")
                return cached
            emit("waiting_for_renderer")
            output = self.root / "renders" / uuid.uuid4().hex
            rpc_started = time.monotonic()
            response = self._rpc(
                {
                    "yaml_text": yaml.safe_dump(canonical),
                    "output_dir": str(output),
                    "num_envs": 1,
                    "num_steps": 0,
                    "env_spacing": 3.0,
                    "options": options,
                    "renderer_version": self.renderer_version,
                    "asset_revision": revision,
                },
                deadline,
                emit,
            )
            measured["rpc_s"] = time.monotonic() - rpc_started
            if not response.get("ok"):
                raise SnapshotError(
                    f"Isaac Sim snapshot failed: {response.get('error', 'unknown renderer error')}",
                    errors=response.get("errors"),
                    timings={
                        **clean_timings(response.get("timings")),
                        **measured,
                        "total_s": time.monotonic() - started,
                    },
                )
            emit("publishing_artifacts")
            publishing = time.monotonic()
            assets = []
            warnings = []
            if not revision:
                warnings.append(
                    "Asset dependency revisions are unavailable; saved images are historical, not a verified fresh"
                    " cache."
                )
            errors = clean_errors(response.get("errors"))

            def publish(path, node_id):
                if not isinstance(path, str) or not path:
                    if not any(error["id"] == node_id for error in errors):
                        errors.append({
                            "id": node_id,
                            "stage": "render",
                            "code": "missing_artifact",
                            "message": "No PNG rendered for this preview.",
                        })
                    return None
                try:
                    return self._publish_variants(Path(path), output)
                except (OSError, ValueError, SnapshotError) as error:
                    errors.append(
                        {"id": node_id, "stage": "publish", "code": "invalid_artifact", "message": str(error)[:1000]}
                    )
                    return None

            paths = response.get("paths", {})
            for asset in [spec.embodiment, spec.background, *spec.objects, *(spec.object_references or [])]:
                artifact = publish(paths.get(asset.id), asset.id)
                if artifact is None:
                    warnings.append(f"No preview rendered for {asset.id}.")
                    continue
                entry = {"id": asset.id, **artifact}
                dims = response.get("aabb_dimensions_m", {}).get(asset.id)
                if (
                    isinstance(dims, (list, tuple))
                    and len(dims) == 3
                    and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in dims)
                ):
                    entry["dimensions_m"] = dims
                assets.append(entry)
            scene = publish(response.get("scene"), "scene")
            timings = clean_timings(response.get("timings"))
            timings.update(measured)
            timings.update(publish_s=time.monotonic() - publishing, total_s=time.monotonic() - started)
            if not assets and scene is None:
                raise SnapshotError(
                    "Isaac Sim returned no valid asset or scene PNG; inspect the renderer log and retry",
                    errors=errors,
                    timings=timings,
                )
            result = {
                "input_hash": digest,
                "assets": assets,
                "scene": scene,
                "warnings": warnings,
                "errors": errors,
                "partial": bool(errors),
                "timings": timings,
            }
            result.update(
                canonical_hash=digest,
                cache_key=cache_key,
                renderer_version=self.renderer_version,
                options=options,
                freshness="verified_assets" if revision else "unverified_assets",
            )
            with sqlite3.connect(self._db_path) as db:
                db.execute(
                    "INSERT OR REPLACE INTO previews VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        cache_key,
                        digest,
                        json.dumps(options, sort_keys=True),
                        self.renderer_version,
                        json.dumps(canonical),
                        json.dumps(result),
                        time.time(),
                    ),
                )
            self._cleanup(time.time())
            with sqlite3.connect(self._db_path) as db:
                if db.execute("SELECT 1 FROM previews WHERE cache_key=?", (cache_key,)).fetchone() is None:
                    raise SnapshotError("Preview exceeds the configured artifact storage budget")
            emit("snapshots_ready")
            return result
        finally:
            try:
                if leased:
                    try:
                        if output is not None:
                            remove_output(self.root, output)
                        self._cleanup(time.time())
                    finally:
                        lease.__exit__(None, None, None)
            finally:
                self._lock.release()

    @contextmanager
    def _write_lease(self, deadline):
        fd = os.open(self.root / "catalogue.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise SnapshotError("Catalogue lease is not an owned regular file")
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise SnapshotError("Snapshot catalogue queue deadline exceeded") from None
                    time.sleep(0.025)
            yield
        finally:
            os.close(fd)

    def _cleanup(self, now):
        prune_previews(
            self.root,
            self._db_path,
            max_receipts=self.max_receipts,
            max_bytes=self.max_bytes,
            max_age_s=self.max_age_s,
            now=now,
        )

    def cleanup(self, *, now=None):
        """Run bounded retention explicitly; catalogue GETs never call this method."""
        with self._lock, self._write_lease(time.monotonic() + self.timeout_s):
            self._cleanup(time.time() if now is None else now)

    def lookup(self, canonical_hash: str, options=None, *, allow_historical=False):
        """Read a verified receipt, optionally exposing unversioned historical pixels.

        Historical receipts are display-only; render cache lookup never opts in.
        """
        if not re.fullmatch(r"[a-f0-9]{64}", canonical_hash):
            raise ValueError("Canonical hash must be 64 lowercase hexadecimal characters")
        options = normalized_options(options)
        try:
            with sqlite3.connect(self._db_path.as_uri() + "?mode=ro", uri=True) as db:
                spec_row = db.execute(
                    "SELECT canonical FROM previews WHERE canonical_hash=? LIMIT 1", (canonical_hash,)
                ).fetchone()
                rows = db.execute(
                    "SELECT canonical, result FROM previews WHERE canonical_hash=? AND options=? AND renderer=? AND"
                    " created>=? ORDER BY created DESC LIMIT 1",
                    (
                        canonical_hash,
                        json.dumps(options, sort_keys=True),
                        self.renderer_version,
                        time.time() - self.max_age_s,
                    ),
                ).fetchall()
        except sqlite3.Error:
            return None
        if spec_row:
            try:
                known_canonical = json.loads(spec_row[0])
                if canonical_digest(known_canonical) != canonical_hash:
                    return None
            except (ValueError, TypeError):
                return None
            normalized_options(options, known_canonical)
        for canonical_json, result_json in rows:
            try:
                canonical = json.loads(canonical_json)
                normalized_options(options, canonical)
                revision = self.asset_revision(canonical)
                if not revision and not (allow_historical and revision is None):
                    return None
                result = json.loads(result_json)
                # The null-revision cache key proves this receipt was originally
                # rendered unversioned. Never downgrade an invalidated known key
                # to historical, nor search older rows after the newest misses.
                if canonical_digest(canonical) != canonical_hash or result["cache_key"] != identity_digest(
                    [canonical_hash, self.renderer_version, revision, options]
                ):
                    return None
                if (
                    result["canonical_hash"] != canonical_hash
                    or result["renderer_version"] != self.renderer_version
                    or result["options"] != options
                ):
                    return None
                for item in [*result["assets"], result["scene"]]:
                    if item is not None:
                        self.artifact_path(item["artifact_id"])
                        for variant in item.get("variants", {}).values():
                            self.artifact_path(variant["artifact_id"])
                return {**result, "freshness": "verified_assets" if revision else "unverified_assets"}
            except (KeyError, TypeError, ValueError, OSError):
                return None
        return None

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
        from PIL import Image

        try:
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                if image.format != "PNG" or image.size != (width, height) or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Unexpected image encoding")
        except (OSError, ValueError) as error:
            raise SnapshotError("Invalid PNG image data") from error
        artifact_id = uuid.uuid4().hex
        target = self.root / f"{artifact_id}.png"
        with target.open("xb") as stream:
            stream.write(data)
        with sqlite3.connect(self._db_path) as db:
            db.execute("INSERT INTO artifacts VALUES (?, ?)", (artifact_id, hashlib.sha256(data).hexdigest()))
        return {
            "artifact_id": artifact_id,
            "url": f"/api/editor/artifacts/{artifact_id}",
            "width": width,
            "height": height,
        }

    def _publish_variants(self, source: Path, output: Path):
        from PIL import Image

        full = self._publish(source, output)
        thumbnail = full
        if max(full["width"], full["height"]) > 256:
            with Image.open(self.artifact_path(full["artifact_id"])) as image:
                image.thumbnail((256, 256), Image.Resampling.LANCZOS)
                target = output / f"thumbnail-{uuid.uuid4().hex}.png"
                image.save(target, format="PNG")
            thumbnail = self._publish(target, output)
        return {**full, "variants": {"thumbnail": thumbnail, "full": full}}

    def artifact_path(self, artifact_id: str) -> Path:
        """Resolve only an indexed artifact ID, never a client-supplied path."""
        if not re.fullmatch(r"[a-f0-9]{32}", artifact_id):
            raise KeyError(artifact_id)
        try:
            with sqlite3.connect(self._db_path.as_uri() + "?mode=ro", uri=True) as db:
                row = db.execute("SELECT digest FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        except sqlite3.Error:
            raise KeyError(artifact_id) from None
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
