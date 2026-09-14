# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Offline research administration; never a scheduler, session or inference owner.

Run with ``python -m isaaclab_arena_examples.agentic_environment_generation.research_admin``.
Only trusted-owner Linux-local storage is supported. The operator must attest the
filesystem; this is not distributed-storage detection or a same-UID boundary.
init-store, init-publication-ledger and backup require --attest-quiescent: close all journal
connections and keep the API/workers offline for the whole command. This tool
never stops services. A conflicting SQLite lock returns busy immediately.
Preflight copies main+WAL under Linux OFD locks compatible with SQLite's default
unix POSIX VFS; custom/no-lock VFSes and network filesystems are unsupported.
Rejected preflight preserves directory inventory, bytes and modes (not access
timestamps). Backup uses only the private snapshot, never a source SQLite attach.
After accepted preflight, initialization commands attach writable: SQLite may rebuild
SHM, recover/checkpoint WAL and delete sidecars, in addition to explicit local writes.
The offline attestation covers the lock-to-writable-attach handoff; it is not an
online administration guarantee. Copy is capped at 256 MiB and a 5-second checked
deadline; local filesystem syscall latency itself is not interruptibly bounded.
"""

import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import threading
import time
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.workbench import research_backup
from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import SafeBusy, _root
from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
from isaaclab_arena.agentic_environment_generation.workbench.research_registry import (
    ResearchRegistry,
    bounded_json,
    checked_identifier,
)
from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
from isaaclab_arena_examples.agentic_environment_generation.web_api.research_profiles import parse_research_roots

# SHA-256 of whitespace-stripped sqlite_master.sql from a fresh current P1 Journal.
# Fail closed on P1 schema changes: update only after reviewing the authoritative
# journal.py schema. No constructor, schema extraction/evaluation or migration at runtime.
_P1_SCHEMA = {
    "attempts": "cf7474522a6a1e7c1c7535ecffcba55a9911bfe6fbbca4e9282f1ce848495265",
    "authorization_no_delete": "9c0268c147427ac6ec872c47c8981e4bb9ea08884404b96e8778b5f7c5dd15dd",
    "authorization_no_update": "b5e8555dab7b331630a0c689bd06bc9401d58d43c48af2b1e03c0875aadc0880",
    "candidate_receipts": "3b9ce27f3794dc3e19fc03a14f8d8304e26a35ba961c411dc4a650636a830e9a",
    "events": "66fcae2b06da4216b4c63922ed55a628bdd88c7aa76b64a5076d8a4d88bd1649",
    "jobs": "04115b49a4e890521efeeb4facf8554a27b61ef91e30fdb52d01f97c641e6581",
    "metadata": "846533027b0258f412f370644da049ed04ca3c1e9f2bfc24d8c7ce82b628613e",
    "modern_candidate_receipts": "66a6bc4fba47cadda668a14d928e03733928e5e91039ce16ee06cd7ef913e0bb",
    "modern_receipt_no_delete": "f65442c222563a9d2f4876db1914a7c87b9b6701db1e34ed275be51853231ae8",
    "modern_receipt_no_update": "a3e05570880827b8ef2b7e9fb92743b9d2af5e5c819cbfaf36278ca1f030b3c2",
    "receipt_no_delete": "0ac89ebae82090b9ced0b85125cf59c369c4aaeb84b4acc01dfa0698a9c66c50",
    "receipt_no_update": "9ecb523315fdac5eac9530aaf63c479e12e51ce9699768ffe03577de3819424a",
    "rejection_no_delete": "dbbf36454648d1b39fc4ae96d708e9c5417ab56fb95ea5dd32553d665b7a80d1",
    "rejection_no_update": "2345bbeaa4e5872f3310b25352ce451c6562947fb2b11335947ae4d9b72fd9b3",
    "workers": "c56567bfe60d00faa6c74bd3612fbacbe2596b0e08896032db332d70e8d019e4",
    "workflow_authorizations": "40caa9c0d6decdba466bb297545696c68e82cd60f440f91b1bf0fc5872108b39",
    "workflow_renewal_rejections": "e1ce2c5d721d8dce346c5f009797e05da723fa9a27aa809986f06ee7ef05a1e0",
}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("Invalid arguments")


def _path(raw):
    if (
        not raw.startswith("/")
        or len(raw.encode()) > 4096
        or any(ord(c) < 32 for c in raw)
        or any(p in {".", ".."} for p in raw.split("/"))
    ):
        raise ValueError("Invalid path")
    return Path(raw)


def _schema(db):
    if db.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("Incompatible journal")
    for name, expected in _P1_SCHEMA.items():
        row = db.execute("SELECT sql FROM sqlite_master WHERE name=? AND length(sql)<=16384", (name,)).fetchone()
        if row is None or hashlib.sha256(re.sub(r"\s+", "", row[0]).encode()).hexdigest() != expected:
            raise ValueError("Incompatible journal")
    metadata = dict(
        db.execute(
            "SELECT key,value FROM metadata WHERE key IN "
            "('attempt_schema_version','clean_shutdown','queue_paused','pruned_through')"
        )
    )
    if metadata.get("attempt_schema_version") != 1 or len(metadata) != 4:
        raise ValueError("Incompatible journal")


MAX_PREFLIGHT_BYTES = 256 * 1024 * 1024
PREFLIGHT_SECONDS = 5.0


class _Flock(ctypes.Structure):
    # Linux LP64 struct flock; unsupported ABIs fail closed below.
    _fields_ = [
        ("type", ctypes.c_short),
        ("whence", ctypes.c_short),
        ("start", ctypes.c_long),
        ("length", ctypes.c_long),
        ("pid", ctypes.c_int),
    ]


class _AdminJournal:
    """Synchronous registry/backup adapter, deliberately without lifecycle methods."""

    _transaction = Journal._transaction

    def __init__(self, db):
        self.db, self._lock = db, threading.RLock()

    def _check_schema(self):
        _schema(self.db)


def _private(info):
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or info.st_mode & 0o777 != 0o600
    ):
        raise ValueError("Private journal required")


@contextmanager
def _snapshot(parent, name):
    """Copy a quiescent SQLite database without opening the source with SQLite."""
    if not hasattr(fcntl, "F_OFD_SETLK") or ctypes.sizeof(ctypes.c_long) != 8:
        raise ValueError("Linux LP64 OFD locks required")
    identity = os.stat(name, dir_fd=parent, follow_symlinks=False)
    _private(identity)
    # Closing ANY descriptor for an inode drops this process's POSIX SQLite locks.
    # Reject embedded use with existing source handles before opening another fd.
    for entry in os.listdir("/proc/self/fd"):
        try:
            info = os.stat("/proc/self/fd/" + entry)
        except FileNotFoundError:
            continue
        if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
            raise SafeBusy("Close local journal connections")
    with tempfile.TemporaryDirectory(prefix="arena-admin-") as temporary:
        target = Path(temporary) / name
        with ExitStack() as stack:
            fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            _private(info)
            if (info.st_dev, info.st_ino) != (identity.st_dev, identity.st_ino):
                raise ValueError("Journal path changed")
            # SQLite src/os.h: PENDING_BYTE=0x40000000, RESERVED=+1,
            # SHARED_FIRST=+2, SHARED_SIZE=510. walformat.html section 2.3:
            # every WAL connection holds a main-file SHARED lock until close;
            # last-close checkpoint/deletion holds EXCLUSIVE. An atomic exclusive
            # lock over this entire range excludes both and blocks new readers.
            # https://www.sqlite.org/src/raw/src/os.h?ci=trunk
            # https://www.sqlite.org/walformat.html#locking_matrix
            # OFD locks conflict with POSIX locks, including this process's locks:
            # https://man7.org/linux/man-pages/man2/F_GETLK.2const.html
            lock = _Flock(fcntl.F_WRLCK, os.SEEK_SET, 0x40000000, 512, 0)
            try:
                fcntl.fcntl(fd, fcntl.F_OFD_SETLK, bytes(lock))
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    raise SafeBusy("Journal is active") from None
                raise
            deadline, total = time.monotonic() + PREFLIGHT_SECONDS, 0
            for suffix in ("", "-wal", "-shm", "-journal"):
                source = fd
                if suffix:
                    try:
                        source = os.open(name + suffix, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    except FileNotFoundError:
                        continue
                    stack.callback(os.close, source)
                info = os.fstat(source)
                _private(info)
                total += info.st_size
                if total > MAX_PREFLIGHT_BYTES:
                    raise ValueError("Journal copy limit exceeded")
                # Do not recover rollback journals that may refer to external
                # super-journals. WAL is authoritative; SHM is only a cache.
                if suffix == "-journal" and info.st_size:
                    raise ValueError("Rollback journal requires separate recovery")
                if suffix in ("-shm", "-journal"):
                    continue
                out = os.open(str(target) + suffix, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(out, "wb") as output:
                    remaining = info.st_size
                    while remaining:
                        if time.monotonic() >= deadline:
                            raise SafeBusy("Journal copy deadline exceeded")
                        data = os.read(source, min(1024 * 1024, remaining))
                        if not data:
                            raise ValueError("Journal changed")
                        output.write(data)
                        remaining -= len(data)
                if time.monotonic() >= deadline:
                    raise SafeBusy("Journal copy deadline exceeded")
        # Source locks/fds are now closed. Only this private copy is recovered.
        yield target, (identity.st_dev, identity.st_ino)


@contextmanager
def _journal(raw, *, writable=False, preflight=None):
    """Validate a coherent private snapshot before any writable source attach."""
    path = _path(raw)
    parent = _root(str(path.parent), False)
    try:
        info = os.fstat(parent)
        if info.st_uid != os.geteuid() or info.st_mode & 0o777 != 0o700:
            raise ValueError("Private journal directory required")
        with _snapshot(parent, path.name) as (snapshot, identity):
            with closing(sqlite3.connect(snapshot, isolation_level=None, timeout=0)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only=ON")
                _schema(db)
                if preflight is not None:
                    preflight(_AdminJournal(db))
                if not writable:
                    yield _AdminJournal(db)
                    return
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if identity != (info.st_dev, info.st_ino):
                raise ValueError("Journal path changed")
            uri = Path(f"/proc/self/fd/{parent}/{path.name}").as_uri()
            with closing(sqlite3.connect(uri + "?mode=rw", uri=True, isolation_level=None, timeout=1)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA synchronous=FULL")
                yield _AdminJournal(db)
    finally:
        os.close(parent)


def protect_public(value):
    """Reject known explicit private markers; not a general-purpose secret detector."""
    checked = bounded_json(value, public=True)
    encoded = json.dumps(checked)
    if re.search(
        r"(?i)(bearer\s+|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
        r"(?:api[_-]?key|password|secret|token)\s*[=:]|[a-z][a-z0-9+.-]*://[^/\s]+:[^/\s]+@)",
        encoded,
    ):
        raise ValueError("Private marker rejected")
    return checked


def _summary(manifest):
    return {
        "ok": True,
        "registry_id": manifest["registry_id"],
        "store_ids": manifest["store_ids"],
        "database_sha256": manifest["database"]["sha256"],
        "reference_count": len(manifest["references"]),
        "effect_count": len(manifest["effect_ids"]),
        "file_count": len(manifest["files"]) + 1,
        "activation_required": True,
        "warnings": [research_backup.WARNING],
    }


def _publication_preflight(journal):
    """Validate registry and rehearse additive initialization on a private database."""
    registry = ResearchRegistry(journal)
    checked_identifier(registry.registry_id)
    stores = registry.store_ids()
    if not stores or len(stores) > 16:
        raise ValueError("Registered research stores required")
    for store_id in stores:
        checked_identifier(store_id)
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as db:
        journal.db.backup(db)
        db.row_factory = sqlite3.Row
        private = _AdminJournal(db)
        registry = ResearchRegistry(private)
        before = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE name GLOB 'publication_*'")}
        attempts = PublicationAttempts(private, registry, initialize=True, protect_public=protect_public)
        # Shared core validation rejects damaged initialized worker triggers before
        # additive initialization, and before any writable source attachment.
        attempts.worker_support_ready()
        core = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE name GLOB 'publication_*'")}
        attempts.initialize_worker_support()
        # Existing core objects must be complete, never silently repaired.
        if ("publication_meta" in before and core != before) or ("publication_meta" not in before and before):
            raise ValueError("Incomplete publication schema")


def _execute(args):
    if args.command == "init-publication-ledger":
        with _journal(args.journal, writable=True, preflight=_publication_preflight) as journal:
            registry = ResearchRegistry(journal)
            attempts = PublicationAttempts(journal, registry, initialize=True, protect_public=protect_public)
            attempts.initialize_worker_support()
            return {
                "ok": True,
                "registry_id": registry.registry_id,
                "worker_support_ready": attempts.worker_support_ready(),
                "no_graph_changes": True,
            }
    if args.command == "init-store":
        root = parse_research_roots([f"{args.store_id}={args.root}"])[args.store_id]
        parent = _root(str(root.parent), False)
        os.close(parent)
        if root.is_symlink():
            raise ValueError("Invalid root")
        with _journal(args.journal, writable=True) as journal:
            loader = ResearchStore.open if root.exists() else ResearchStore.create
            with loader(journal, root, args.store_id, protect_public=protect_public) as store:
                result = {"ok": True, "store_id": store.store_id, "registry_id": store.registry.registry_id}
            # Read back exact binding after explicit initialization.
            with ResearchStore.open(journal, root, args.store_id, protect_public=protect_public):
                return result
    if args.command == "backup":
        roots = parse_research_roots(args.store)
        destination = _path(args.destination)
        with _journal(args.journal) as journal, ExitStack() as stack:
            stores = {
                key: stack.enter_context(ResearchStore.open(journal, root, key, protect_public=protect_public))
                for key, root in roots.items()
            }
            research_backup.backup(journal, stores, destination)
        return _summary(research_backup.verify_backup(destination))
    source = _path(args.source)
    if args.command == "estimate-checkpoint":
        return {"ok": True, **research_backup.estimate_backup(source), "warnings": [research_backup.WARNING]}
    if args.command == "verify-checkpoint":
        return _summary(research_backup.verify_backup(source))
    destination = _path(args.destination)
    research_backup.prepare_restore(source, destination)
    result = _summary(research_backup.verify_backup(destination))
    result["inactive_database"] = str(destination / research_backup.DATABASE_NAME)
    return result


def main(argv=None):
    """Execute an explicit offline command, returning a process exit status."""
    parser = _Parser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-store", allow_abbrev=False)
    init.add_argument("--journal", required=True)
    init.add_argument("--store-id", required=True)
    init.add_argument("--root", required=True)
    init.add_argument("--attest-local-filesystem", action="store_true", required=True)
    backup = commands.add_parser("backup", allow_abbrev=False)
    backup.add_argument("--journal", required=True)
    backup.add_argument(
        "--store", action="append", required=True, help="Repeat for ALL registered ID=absolute-path profiles"
    )
    backup.add_argument("--destination", required=True)
    ledger = commands.add_parser("init-publication-ledger", allow_abbrev=False)
    ledger.add_argument("--journal", required=True)
    for command in (init, backup, ledger):
        command.add_argument(
            "--attest-quiescent",
            action="store_true",
            required=True,
            help="All journal connections closed; keep API/workers offline for entire command",
        )
    for name in ("verify-checkpoint", "estimate-checkpoint", "prepare-restore"):
        command = commands.add_parser(name, allow_abbrev=False)
        command.add_argument("--source", required=True, help="Existing sealed checkpoint, not a live journal")
        if name == "prepare-restore":
            command.add_argument("--destination", required=True)
    try:
        result = _execute(parser.parse_args(argv))
        print(json.dumps(protect_public(result), sort_keys=True))
        return 0
    except research_backup.BackupDurabilityUncertain:
        error, status = "durability_uncertain", 4
    except SafeBusy:
        error, status = "busy", 3
    except sqlite3.OperationalError as exc:
        busy = getattr(exc, "sqlite_errorcode", 0) & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
        error, status = ("busy", 3) if busy else ("invalid_request", 2)
    except Exception:
        error, status = "invalid_request", 2
    print(json.dumps({"ok": False, "error": error}, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
