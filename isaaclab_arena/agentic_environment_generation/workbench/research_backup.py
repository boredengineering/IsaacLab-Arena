# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded private research checkpoints, never API activation or job recovery.

Only the caller-owned SQLite checkpoint and committed immutable research files are
copied. No preview cache, remote USD, models, datasets, or service deployment is
provided. The opaque database is PRIVATE, not a public dump: it may contain session
cookie digests, CSRF tokens and other authentication state. The manifest omits them.
Existing provider/simulator work is never replayed. A data copy cannot prove graph
outcomes after backup or undo graph effects. Activation/profile cutover and effect
reconciliation require separate authorization. Unknown outcomes remain unknown.
Linux-local trusted-owner filesystem assumptions match ArtifactArea (not an ACL
boundary against another process with the same UID). Failed destinations are left
in place for inspection; source files are never deleted. Interrupted seal writes
leave private temporary evidence, never a partial final seal. A promoted complete
seal with failed directory fsync raises BackupDurabilityUncertain and is retained;
read-only verification checks bytes, not proof of durability after that failure.

Deadlines are operation-wide and cooperative: timed journal lock acquisition,
SQLite VM progress interruption, and checks between bounded filesystem chunks and
artifact operations. A blocked OS read/write/fsync or SQLite I/O cannot be forcibly
interrupted here; this is not a hard real-time deadline or a power-loss simulation.
"""

import contextlib
import contextvars
import functools
import hashlib
import json
import os
import sqlite3
import stat
import time
from typing import TYPE_CHECKING

from . import research_artifacts as artifacts
from .research_artifacts import ArtifactArea, _canonical, _rename_noreplace
from .research_registry import bounded_json, checked_identifier, digest

if TYPE_CHECKING:
    from .research_store import ResearchStore

DATABASE_NAME = "journal.inactive.sqlite3"
MANIFEST_NAME = "checkpoint.json"
TEMP_MANIFEST_NAME = ".checkpoint.json.pending"
SCHEMA_VERSION = 1
MAX_DATABASE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_STORES = 16
MAX_REFERENCES = 10000
MAX_FILES = 20000
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_BACKUP_SECONDS = 30
_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar("research_backup_deadline", default=None)
WARNING = (
    "OFFLINE checkpoint: activation_required; separate authorized reconciliation of immutable effect IDs "
    "and research references required. Not a full API restore; graph effects are not undone and "
    "post-backup graph outcomes cannot be proven. Pending provider/simulator work must never be replayed."
)


class BackupError(ValueError):
    """Checkpoint rejected without disclosing paths or database contents."""


class BackupDurabilityUncertain(BackupError):
    """Complete seal was promoted but its directory durability is unconfirmed."""


def _remaining():
    deadline = _DEADLINE.get()
    remaining = MAX_BACKUP_SECONDS if deadline is None else deadline - time.monotonic()
    if remaining <= 0:
        raise BackupError("Checkpoint operation deadline exceeded")
    return remaining


def _operation(function):
    @functools.wraps(function)
    def run(*args, **kwargs):
        token = _DEADLINE.set(time.monotonic() + MAX_BACKUP_SECONDS)
        try:
            _remaining()
            result = function(*args, **kwargs)
            _remaining()
            return result
        finally:
            _DEADLINE.reset(token)

    return run


def _read(parent, name, limit, sync=False):
    _remaining()
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    try:
        _remaining()
        artifacts._check(fd)
        if os.fstat(fd).st_size > limit:
            raise BackupError("Checkpoint file exceeds bounds")
        chunks, remaining = [], limit + 1
        while remaining:
            _remaining()
            chunk = os.read(fd, min(remaining, 65536))
            _remaining()
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        artifacts._check(fd)
        if len(data) > limit:
            raise BackupError("Checkpoint file exceeds bounds")
        if sync:
            _remaining()
            os.fsync(fd)
        _remaining()
        return data
    finally:
        os.close(fd)


def _write(parent, name, data):
    _remaining()
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
    try:
        _remaining()
        artifacts._check(fd)
        view = memoryview(data)
        while view:
            _remaining()
            count = os.write(fd, view[:65536])
            _remaining()
            if count <= 0:
                raise BackupError("Checkpoint write failed")
            view = view[count:]
        _remaining()
        os.fsync(fd)
        _remaining()
    finally:
        os.close(fd)


def _root(*args):
    _remaining()
    fd = artifacts._root(*args)
    try:
        _remaining()
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextlib.contextmanager
def _directory(*args):
    _remaining()
    with artifacts._directory(*args) as fd:
        _remaining()
        yield fd
        _remaining()


@contextlib.contextmanager
def _new_root(destination):
    _remaining()
    raw = os.fspath(destination)
    if not isinstance(raw, str) or not raw or any(part in (".", "..") for part in raw.split("/")):
        raise BackupError("Invalid checkpoint destination")
    parent, name = os.path.split(raw)
    checked_identifier(name)
    parent = parent or os.getcwd()
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY) if parent == "/" else _root(parent, False)
    try:
        os.mkdir(name, 0o700, dir_fd=fd)
        _remaining()
        os.fsync(fd)
        with _directory(fd, name) as root:
            yield root
    finally:
        os.close(fd)


@contextlib.contextmanager
def _mkdir(parent, name):
    _remaining()
    os.mkdir(name, 0o700, dir_fd=parent)
    with _directory(parent, name) as fd:
        yield fd
        os.fsync(fd)
        _remaining()
    os.fsync(parent)
    _remaining()


def _snapshot(journal, root):
    _write(root, DATABASE_NAME, b"")

    def progress(status, remaining, total):
        _remaining()
        if total * page_size > MAX_DATABASE_BYTES:
            raise BackupError("SQLite checkpoint exceeds bounds")

    if not journal._lock.acquire(timeout=_remaining()):
        raise BackupError("Checkpoint journal lock deadline exceeded")
    try:
        _remaining()
        if journal.db.in_transaction:
            raise BackupError("Checkpoint requires no caller transaction")
        page_size = journal.db.execute("PRAGMA page_size").fetchone()[0]
        if journal.db.execute("PRAGMA page_count").fetchone()[0] * page_size > MAX_DATABASE_BYTES:
            raise BackupError("SQLite checkpoint exceeds bounds")
        with contextlib.closing(sqlite3.connect(f"/proc/self/fd/{root}/{DATABASE_NAME}")) as copy:
            journal.db.backup(copy, pages=128, progress=progress, sleep=0.01)
            copy.execute("PRAGMA journal_mode=DELETE")
    finally:
        journal._lock.release()
    _read(root, DATABASE_NAME, MAX_DATABASE_BYTES, sync=True)
    os.fsync(root)


def _index(root):
    """Read research authority only from the inert SQLite copy, never a Journal."""
    uri = f"file:/proc/self/fd/{root}/{DATABASE_NAME}?mode=ro&immutable=1"
    with _indexed_database(uri) as db:
        db.row_factory = sqlite3.Row
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("Invalid SQLite checkpoint")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise BackupError("Checkpoint foreign key relation mismatch")
        if (
            db.execute(
                "SELECT 1 FROM research_commits c LEFT JOIN research_reservations r USING(reservation_id) "
                "WHERE r.reservation_id IS NULL LIMIT 1"
            ).fetchone()
            is not None
        ):
            raise BackupError("Checkpoint orphan research commit")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        attempt = db.execute("SELECT value FROM metadata WHERE key='attempt_schema_version'").fetchone()
        meta = db.execute("SELECT schema_version,registry_id FROM research_registry_meta").fetchall()
        if version != 1 or attempt is None or attempt[0] != 1 or len(meta) != 1 or meta[0][0] != 1:
            raise BackupError("Checkpoint schema version mismatch")
        registry_id = checked_identifier(meta[0][1])
        store_ids = [
            checked_identifier(row[0]) for row in db.execute("SELECT store_id FROM research_stores ORDER BY store_id")
        ]
        if len(store_ids) > MAX_STORES:
            raise BackupError("Checkpoint store count exceeds bounds")
        references, commits = [], []
        commits_by_id = {}
        rows = db.execute(
            "SELECT r.*,c.body AS commit_body FROM research_reservations r "
            "LEFT JOIN research_commits c USING(reservation_id) ORDER BY r.store_id,r.family,r.version LIMIT ?",
            (MAX_REFERENCES + 1,),
        )
        for row in rows:
            _remaining()
            if len(references) >= MAX_REFERENCES:
                raise BackupError("Checkpoint reference count exceeds bounds")
            reservation = bounded_json(json.loads(row["body"]))
            for key in ("reservation_id", "store_id", "family", "revision_id"):
                checked_identifier(reservation[key])
            if (
                reservation["registry_id"] != registry_id
                or reservation["schema_version"] != 1
                or reservation["store_id"] not in store_ids
                or any(reservation[key] != row[key] for key in ("reservation_id", "store_id", "family", "version"))
                or type(reservation["version"]) is not int
                or reservation["version"] < 1
            ):
                raise BackupError("Research reservation binding mismatch")
            reference = {
                key: reservation[key] for key in ("reservation_id", "revision_id", "store_id", "family", "version")
            }
            reference["committed"] = row["commit_body"] is not None
            references.append(reference)
            if row["commit_body"] is not None:
                commit = bounded_json(json.loads(row["commit_body"]), max_bytes=98304, max_depth=18)
                manifest = commit["manifest"]
                expected = f"final/{reservation['family']}/v{reservation['version']}"
                if (
                    commit["reservation"] != reservation
                    or manifest["binding"] != reservation
                    or commit["relative_directory"] != expected
                ):
                    raise BackupError("Research commit binding mismatch")
                commits.append(commit)
                commits_by_id[reservation["reservation_id"]] = commit
        effects = []
        for row in db.execute(
            "SELECT effect_id,reservation_id,body FROM research_publication_intents ORDER BY effect_id LIMIT ?",
            (MAX_REFERENCES + 1,),
        ):
            _remaining()
            body = bounded_json(json.loads(row["body"]), max_bytes=65536)
            payload = body.get("payload")
            commit = commits_by_id.get(row["reservation_id"])
            supplied_request = {k: body[k] for k in ("effect_id", "target_profile", "options") if k in body}
            if (
                body["registry_id"] != registry_id
                or body["schema_version"] != 1
                or any(body[k] != row[k] for k in ("effect_id", "reservation_id"))
                or commit is None
                or commit["publication_intent_id"] != row["effect_id"]
                or commit["reservation"].get("publication_request") != supplied_request
                or body.get("state") != "pending"
                or type(payload) is not dict
                or payload.get("artifact") != "projection.json"
                or payload.get("artifact_sha256")
                != commit["manifest"]["files"].get("projection.json", {}).get("sha256")
                or digest(payload) != body.get("payload_sha256")
            ):
                raise BackupError("Research intent binding mismatch")
            effects.append({
                "effect_id": checked_identifier(row["effect_id"]),
                "reservation_id": checked_identifier(row["reservation_id"]),
            })
        if len(effects) > MAX_REFERENCES:
            raise BackupError("Checkpoint effect count exceeds bounds")
        actual_intents = {item["reservation_id"]: item["effect_id"] for item in effects}
        for reservation_id, commit in commits_by_id.items():
            _remaining()
            request = commit["reservation"].get("publication_request")
            expected = None if request is None else request["effect_id"]
            if commit["publication_intent_id"] != expected or actual_intents.get(reservation_id) != expected:
                raise BackupError("Checkpoint missing or mismatched publication intent")
    return {
        "registry_id": registry_id,
        "store_ids": store_ids,
        "references": references,
        "effect_ids": effects,
    }, commits


@contextlib.contextmanager
def _indexed_database(uri):
    _remaining()
    with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=_remaining())) as db:

        def expired():
            deadline = _DEADLINE.get()
            return deadline is not None and time.monotonic() >= deadline

        db.set_progress_handler(expired, 1000)
        try:
            yield db
            _remaining()
        except sqlite3.OperationalError:
            _remaining()
            raise
        finally:
            db.set_progress_handler(None, 0)


def _copy_artifacts(root, index, commits, areas):
    families = {}
    for commit in commits:
        _remaining()
        reservation = commit["reservation"]
        families.setdefault(reservation["store_id"], {}).setdefault(reservation["family"], []).append(commit)
    with _mkdir(root, "stores") as stores:
        for store_id in index["store_ids"]:
            source = areas[store_id]
            with _mkdir(stores, store_id) as area:
                marker = _canonical({"schema": 1, "store_id": store_id, "registry_id": index["registry_id"]})
                if _read(source._fd, ArtifactArea.MARKER, 4096) != marker:
                    raise BackupError("Source area registry mismatch")
                _write(area, ArtifactArea.MARKER, marker)
                with _mkdir(area, "staging"):
                    pass
                with _mkdir(area, "final") as final:
                    selected = families.get(store_id, {})
                    for family in sorted(selected):
                        with _mkdir(final, family) as family_fd:
                            for commit in selected[family]:
                                _remaining()
                                reservation = commit["reservation"]
                                files = source.verify(commit["relative_directory"], commit["manifest"])
                                _remaining()
                                with _mkdir(family_fd, f"v{reservation['version']}") as version:
                                    for name, data in files.items():
                                        _write(version, name, data)
                                    _write(version, "manifest.json", _canonical(commit["manifest"]))
                                    source._verify_fd(version, commit["manifest"])


def _inventory(root, prefix=""):
    _remaining()
    result = {}
    for name in sorted(os.listdir(root)):
        _remaining()
        if not prefix and name == MANIFEST_NAME:
            continue
        relative = f"{prefix}{name}"
        info = os.stat(name, dir_fd=root, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            with _directory(root, name) as child:
                result.update(_inventory(child, relative + "/"))
        else:
            data = _read(root, name, MAX_DATABASE_BYTES if relative == DATABASE_NAME else 2 * 1024 * 1024)
            result[relative] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return result


@_operation
def backup(journal, stores: dict[str, "ResearchStore"], destination) -> dict:
    """Seal a new private research checkpoint without owning or recovering Journal."""
    with _new_root(destination) as root:
        _snapshot(journal, root)
        index, commits = _index(root)
        if set(stores) != set(index["store_ids"]):
            raise BackupError("All snapshot registered stores must be covered exactly")
        for key, store in stores.items():
            if (
                store.store_id != key
                or store.registry.registry_id != index["registry_id"]
                or store.area.registry_id != index["registry_id"]
                or store.area.store_id != key
            ):
                raise BackupError("Supplied store registry identity mismatch")
        _preflight(index, commits, os.stat(DATABASE_NAME, dir_fd=root).st_size)
        _copy_artifacts(root, index, commits, {key: value.area for key, value in stores.items()})
        files = _inventory(root)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            **index,
            "database": files[DATABASE_NAME],
            "files": files,
            "activation_required": True,
            "warning": WARNING,
        }
        _seal(root, manifest)
        return manifest


def _layout(index, commits):
    files = {DATABASE_NAME}
    directories = {"", "stores"}
    for store_id in index["store_ids"]:
        base = f"stores/{store_id}"
        files.add(f"{base}/{ArtifactArea.MARKER}")
        directories.update({base, f"{base}/staging", f"{base}/final"})
    for commit in commits:
        base = f"stores/{commit['reservation']['store_id']}/{commit['relative_directory']}"
        directories.update({base, base.rsplit("/", 1)[0]})
        files.update(f"{base}/{name}" for name in commit["manifest"]["files"])
        files.add(f"{base}/manifest.json")
    return files, directories


def _check_layout(root, files, directories, prefix="", sealed=True, children=None):
    _remaining()
    if children is None:
        children = {}
        for path in files | directories:
            _remaining()
            if path:
                parent, name = os.path.split(path)
                children.setdefault(parent, set()).add(name)
    expected = set(children.get(prefix.rstrip("/"), ()))
    if not prefix and sealed:
        expected.add(MANIFEST_NAME)
    if set(os.listdir(root)) != expected:
        raise BackupError("Checkpoint missing or extra filesystem entries")
    info = os.fstat(root)
    if info.st_uid != os.geteuid() or info.st_mode & 0o777 != 0o700:
        raise BackupError("Checkpoint directory must be private")
    for name in expected:
        _remaining()
        info = os.stat(name, dir_fd=root, follow_symlinks=False)
        mode = 0o700 if stat.S_ISDIR(info.st_mode) else 0o600
        if info.st_uid != os.geteuid() or info.st_mode & 0o777 != mode:
            raise BackupError("Checkpoint entry must be private")
    for name in expected:
        directory = prefix + name
        if directory in directories:
            with _directory(root, name) as child:
                _check_layout(child, files, directories, directory + "/", sealed, children)


@contextlib.contextmanager
def _areas(root, index):
    with contextlib.ExitStack() as stack:
        stores = stack.enter_context(_directory(root, "stores"))
        result = {}
        for store_id in index["store_ids"]:
            fd = stack.enter_context(_directory(stores, store_id))
            area = object.__new__(ArtifactArea)
            area._fd, area.store_id, area.registry_id = fd, store_id, index["registry_id"]
            marker = _canonical({"schema": 1, "store_id": store_id, "registry_id": index["registry_id"]})
            if _read(fd, ArtifactArea.MARKER, 4096) != marker:
                raise BackupError("Checkpoint managed area marker mismatch")
            result[store_id] = area
        yield result


def _verify(root, manifest, *, sealed=True):
    _remaining()
    if (
        type(manifest) is not dict
        or set(manifest)
        != {
            "schema_version",
            "registry_id",
            "store_ids",
            "references",
            "effect_ids",
            "database",
            "files",
            "activation_required",
            "warning",
        }
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != SCHEMA_VERSION
    ):
        raise BackupError("Checkpoint manifest schema mismatch")
    database = _read(root, DATABASE_NAME, MAX_DATABASE_BYTES)
    if manifest["database"] != {"size": len(database), "sha256": hashlib.sha256(database).hexdigest()}:
        raise BackupError("Checkpoint SQLite digest mismatch")
    index, commits = _index(root)
    _preflight(index, commits, len(database))
    _bounds(manifest)
    if (
        any(manifest[key] != value for key, value in index.items())
        or manifest["activation_required"] is not True
        or manifest["warning"] != WARNING
    ):
        raise BackupError("Checkpoint snapshot metadata mismatch")
    with _areas(root, index) as areas:
        for commit in commits:
            _remaining()
            areas[commit["reservation"]["store_id"]].verify(commit["relative_directory"], commit["manifest"])
            _remaining()
    files, directories = _layout(index, commits)
    _check_layout(root, files, directories, sealed=sealed)
    if set(manifest["files"]) != files or _inventory(root) != manifest["files"]:
        raise BackupError("Checkpoint file inventory mismatch")
    return index, commits


@_operation
def verify_backup(backup_root) -> dict:
    """Verify snapshot digest, exact managed layout and every immutable file read-only."""
    root = _root(backup_root, False)
    try:
        manifest = json.loads(_read(root, MANIFEST_NAME, MAX_MANIFEST_BYTES))
        _verify(root, manifest)
        return manifest
    finally:
        os.close(root)


@_operation
def prepare_restore(backup_root, destination) -> dict:
    """Copy verified bytes to a new OFFLINE checkpoint; never activate or reconcile."""
    source = _root(backup_root, False)
    try:
        manifest = json.loads(_read(source, MANIFEST_NAME, MAX_MANIFEST_BYTES))
        index, commits = _verify(source, manifest)
        with _new_root(destination) as root:
            _write(root, DATABASE_NAME, _read(source, DATABASE_NAME, MAX_DATABASE_BYTES))
            with _areas(source, index) as areas:
                _copy_artifacts(root, index, commits, areas)
            _seal(root, manifest)
        return manifest
    finally:
        os.close(source)


def _preflight(index, commits, database_bytes):
    count, total = 2 + len(index["store_ids"]), database_bytes
    for store_id in index["store_ids"]:
        total += len(_canonical({"schema": 1, "store_id": store_id, "registry_id": index["registry_id"]}))
    for commit in commits:
        _remaining()
        manifest = commit["manifest"]
        area = object.__new__(ArtifactArea)
        area.store_id, area.registry_id = commit["reservation"]["store_id"], index["registry_id"]
        area._validate_manifest(manifest)
        count += 1 + len(manifest["files"])
        total += len(_canonical(manifest)) + sum(entry["size"] for entry in manifest["files"].values())
    # Reserve the entire bounded seal budget before any artifact writes.
    if count > MAX_FILES or total + MAX_MANIFEST_BYTES > MAX_TOTAL_BYTES:
        raise BackupError("Checkpoint file count or total bytes exceeds bounds")


def _bounds(manifest):
    encoded = _canonical(manifest)
    count = len(manifest["files"]) + 1
    total = sum(entry["size"] for entry in manifest["files"].values()) + len(encoded)
    if len(encoded) > MAX_MANIFEST_BYTES or count > MAX_FILES or total > MAX_TOTAL_BYTES:
        raise BackupError("Checkpoint manifest or total exceeds bounds")
    return {"files": count, "total_bytes": total, "database_bytes": manifest["database"]["size"]}


def _seal(root, manifest):
    _bounds(manifest)
    _verify(root, manifest, sealed=False)
    _write(root, TEMP_MANIFEST_NAME, _canonical(manifest))
    _remaining()
    _rename_noreplace(root, TEMP_MANIFEST_NAME, root, MANIFEST_NAME)
    try:
        os.fsync(root)
    except OSError as exc:
        raise BackupDurabilityUncertain("Checkpoint seal promoted; durability uncertain") from exc
    _verify(root, manifest)


def estimate_backup(backup_root) -> dict:
    """Return exact dry copy bytes/counts for a verified checkpoint, with no writes.

    This is not a live-index estimate: backup itself bounds the SQLite copy first,
    then preflights snapshot references plus the maximum seal budget before copying
    artifacts. Filesystem allocation overhead and free-space races are not predicted.
    """
    return _bounds(verify_backup(backup_root))
