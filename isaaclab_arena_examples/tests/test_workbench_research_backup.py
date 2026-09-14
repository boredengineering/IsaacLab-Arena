# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Private checkpoint contracts using temporary real WAL journals only."""

import hashlib
import importlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing

import pytest

from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena_examples.tests.test_workbench_research_store import candidate


@pytest.fixture
def ready(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore

    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        journal.begin_run()
        args, _ = candidate(journal)
        with ResearchStore.create(journal, tmp_path / "source", "store", protect_public=lambda value: None) as store:
            commit = store.persist_candidate("family", "save", **args)
            yield journal, store, commit


def api():
    name = "isaaclab_arena.agentic_environment_generation.workbench.research_backup"
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        pytest.fail("research_backup API is not implemented")


def test_process_death_during_seal_write_leaves_no_partial_final(ready, tmp_path):
    journal, store, _ = ready
    module = api()
    destination = tmp_path / "crashed"
    source = tmp_path / "backup"
    module.backup(journal, {"store": store}, source)
    code = """
import os, sys
from isaaclab_arena.agentic_environment_generation.workbench import research_backup as module
original = os.write
def interrupted(fd, data):
    if "checkpoint" in os.path.basename(os.readlink(f"/proc/self/fd/{fd}")):
        original(fd, data[:7])
        os._exit(77)
    return original(fd, data)
module.os.write = interrupted
module.prepare_restore(sys.argv[1], sys.argv[2])
"""
    result = subprocess.run([sys.executable, "-c", code, str(source), str(destination)], timeout=20)
    assert result.returncode == 77
    assert not (destination / module.MANIFEST_NAME).exists()
    assert store.read_version(store.list_versions("family")[0]["reservation"]["reservation_id"])


def test_backup_copies_wal_checkpoint_and_exact_bound_artifacts(ready, tmp_path):
    journal, store, commit = ready
    module = api()
    assert journal.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    journal.submit("owner", "default", "generate", "before", {"operation": "new"})
    destination = tmp_path / "backup"
    result = module.backup(journal, {"store": store}, destination)
    journal.submit("owner", "default", "generate", "after", {"operation": "new"})
    checkpoint = destination / module.DATABASE_NAME
    with closing(sqlite3.connect(f"{checkpoint.as_uri()}?mode=ro&immutable=1", uri=True)) as db:
        keys = {row[0] for row in db.execute("SELECT idempotency_key FROM jobs")}
        assert "before" in keys and "after" not in keys
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert result["database"]["sha256"] == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    assert result["store_ids"] == ["store"]
    assert result["references"][0]["reservation_id"] == commit["reservation"]["reservation_id"]
    assert json.loads((destination / module.MANIFEST_NAME).read_bytes()) == result
    for path in (tmp_path / "source" / commit["relative_directory"]).iterdir():
        assert (
            destination / "stores/store" / commit["relative_directory"] / path.name
        ).read_bytes() == path.read_bytes()
    assert all(path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600) for path in destination.rglob("*"))
    assert destination.stat().st_mode & 0o777 == 0o700


def test_offline_restore_verifies_exact_checkpoint_without_journal_lifecycle(ready, tmp_path, monkeypatch):
    journal, store, _ = ready
    module = api()
    source = tmp_path / "backup"
    manifest = module.backup(journal, {"store": store}, source)

    def forbidden(*args, **kwargs):
        pytest.fail("Checkpoint must not own or recover Journal")

    for name in ("__init__", "begin_run", "close", "submit"):
        monkeypatch.setattr(Journal, name, forbidden)
    assert module.verify_backup(source) == manifest
    restored = tmp_path / "restored"
    result = module.prepare_restore(source, restored)
    assert result["activation_required"] is True
    assert "OFFLINE" in result["warning"]
    assert module.verify_backup(restored) == manifest
    for path in source.rglob("*"):
        if path.is_file():
            assert (restored / path.relative_to(source)).read_bytes() == path.read_bytes()


@pytest.mark.parametrize(
    "attack",
    [
        "bytes",
        "missing",
        "extra",
        "symlink",
        "marker",
        "database",
        "version",
        "registry",
        "traversal",
        "extra-directory",
    ],
)
def test_verification_rejects_tampered_checkpoint(ready, tmp_path, attack):
    journal, store, _ = ready
    module = api()
    root = tmp_path / "backup"
    module.backup(journal, {"store": store}, root)
    target = root / "stores/store/final/family/v1/environment.yaml"
    if attack == "bytes":
        target.write_bytes(b"tampered")
    elif attack == "missing":
        target.unlink()
    elif attack == "extra":
        target.with_name("extra.json").write_bytes(b"{}")
    elif attack == "symlink":
        target.unlink()
        target.symlink_to(tmp_path / "source/final/family/v1/environment.yaml")
    elif attack == "marker":
        (root / "stores/store/.artifact-area.json").write_text("{}")
    elif attack == "database":
        (root / module.DATABASE_NAME).write_bytes(b"invalid sqlite")
    elif attack == "extra-directory":
        (root / "stores/store/staging/extra").mkdir(mode=0o700)
    else:
        path = root / module.MANIFEST_NAME
        manifest = json.loads(path.read_bytes())
        if attack == "version":
            manifest["schema_version"] = 2
        elif attack == "registry":
            manifest["registry_id"] = "other"
        else:
            manifest["files"]["../outside"] = manifest["database"]
        path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, OSError, sqlite3.Error)):
        module.verify_backup(root)
    with pytest.raises((ValueError, OSError, sqlite3.Error)):
        module.prepare_restore(root, tmp_path / "restore")
    assert not (tmp_path / "restore" / module.MANIFEST_NAME).exists()


@pytest.mark.parametrize(
    "bound", ["MAX_TOTAL_BYTES", "MAX_FILES", "MAX_DATABASE_BYTES", "MAX_REFERENCES", "MAX_MANIFEST_BYTES"]
)
def test_bounds_fail_without_success_seal(ready, tmp_path, monkeypatch, bound):
    journal, store, _ = ready
    module = api()
    monkeypatch.setattr(module, bound, 0)
    with pytest.raises(ValueError):
        module.backup(journal, {"store": store}, tmp_path / "bounded")
    assert not (tmp_path / "bounded" / module.MANIFEST_NAME).exists()


def test_dry_estimate_is_snapshot_derived_and_side_effect_free(ready, tmp_path):
    journal, store, _ = ready
    module = api()
    root = tmp_path / "backup"
    manifest = module.backup(journal, {"store": store}, root)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    estimate = module.estimate_backup(root)
    assert estimate["files"] == len(manifest["files"]) + 1
    assert estimate["total_bytes"] == sum(len(data) for data in before.values())
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("fault", ["write", "fsync", "seal-write", "seal-fsync"])
def test_io_fault_never_leaves_success_seal(ready, tmp_path, monkeypatch, fault):
    journal, store, _ = ready
    module = api()
    original_write, original_fsync = module._write, module.os.fsync
    seal_started = False

    def write(fd, name, data):
        nonlocal seal_started
        seal_started = name == module.TEMP_MANIFEST_NAME
        if fault == "write" or fault == "seal-write" and seal_started:
            raise OSError("synthetic disk full")
        return original_write(fd, name, data)

    def fsync(fd):
        if fault == "fsync" or fault == "seal-fsync" and seal_started:
            raise OSError("synthetic fsync fault")
        return original_fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(module, "_write", write)
        patch.setattr(module.os, "fsync", fsync)
        with pytest.raises((OSError, ValueError)):
            module.backup(journal, {"store": store}, tmp_path / "fault")
    assert not (tmp_path / "fault" / module.MANIFEST_NAME).exists()
    assert store.read_version(store.list_versions("family")[0]["reservation"]["reservation_id"])


@pytest.mark.parametrize("attack", ["coverage", "registry", "overwrite", "symlink", "ancestor-symlink"])
def test_backup_refuses_unsafe_scope_without_overwrite(ready, tmp_path, attack):
    journal, store, _ = ready
    module = api()
    destination = tmp_path / "backup"
    stores = {"store": store}
    if attack == "coverage":
        store.registry.register_store("missing")
    elif attack == "registry":
        store.registry.registry_id = "other"
    elif attack == "overwrite":
        destination.mkdir()
        (destination / "keep").write_bytes(b"original")
    elif attack == "symlink":
        destination.symlink_to(tmp_path / "source", target_is_directory=True)
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        destination = alias / "backup"
    with pytest.raises((ValueError, OSError)):
        module.backup(journal, stores, destination)
    assert not (destination / module.MANIFEST_NAME).exists()
    if attack == "overwrite":
        assert (destination / "keep").read_bytes() == b"original"


def test_reference_index_comes_from_copy_not_later_live_writes(ready, tmp_path, monkeypatch):
    journal, store, _ = ready
    module = api()
    snapshot = module._snapshot

    def copy_then_write(*args):
        snapshot(*args)
        store.registry.register_store("registered-after-copy")
        journal.submit("owner", "default", "generate", "after-copy", {"operation": "new"})

    monkeypatch.setattr(module, "_snapshot", copy_then_write)
    monkeypatch.setattr(store.registry, "store_ids", lambda: pytest.fail("live index queried"))
    result = module.backup(journal, {"store": store}, tmp_path / "frozen")
    assert result["store_ids"] == ["store"]
    assert module.verify_backup(tmp_path / "frozen") == result


@pytest.mark.parametrize("entry", ["", "stores", "stores/store/final/family/v1/environment.yaml", "checkpoint.json"])
def test_verification_requires_private_permissions(ready, tmp_path, entry):
    journal, store, _ = ready
    module = api()
    root = tmp_path / "backup"
    module.backup(journal, {"store": store}, root)
    (root / entry).chmod(0o755 if (root / entry).is_dir() else 0o644)
    with pytest.raises(ValueError):
        module.verify_backup(root)


def test_verifier_enforces_current_total_bound(ready, tmp_path, monkeypatch):
    journal, store, _ = ready
    module = api()
    root = tmp_path / "backup"
    module.backup(journal, {"store": store}, root)
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", 0)
    with pytest.raises(ValueError):
        module.verify_backup(root)


def test_unknown_publication_and_pending_jobs_retained_without_recovery(ready, tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts

    journal, store, _ = ready
    module = api()
    args, _ = candidate(journal, key="publish-source")
    commit = store.persist_candidate(
        "family", "publish", **args, publication_request={"effect_id": "effect", "target_profile": "graph"}
    )
    intent = store.registry.get_publication_intent("effect")
    attempts = PublicationAttempts(
        journal, store.registry, initialize=True, clock=lambda: 100, protect_public=lambda value: value
    )
    grant = {
        "effect_id": "effect",
        "target_profile": "graph",
        "payload_sha256": intent["payload_sha256"],
        "request_id": "request",
        "capability": "graph_write",
        "grant_id": "grant",
        "expires_at": 200,
    }
    state = attempts.claim("effect", "request", grant)
    identity = {key: state[key] for key in ("attempt_id", "generation")}
    assert attempts.release("effect", **identity, grant_metadata=grant)
    assert attempts.mark_unknown("effect", **identity)
    journal.submit("owner", "default", "generate", "still-pending", {"operation": "new"})
    tables = ("research_publication_intents", "publication_states", "jobs", "metadata", "publication_bindings")
    before = {table: [tuple(row) for row in journal.db.execute(f"SELECT * FROM {table}")] for table in tables}
    with monkeypatch.context() as guard:
        guard.setattr(PublicationAttempts, "recover", lambda *a: pytest.fail("No publication recovery"))
        guard.setattr(Journal, "begin_run", lambda *a: pytest.fail("No Journal activation"))
        result = module.backup(journal, {"store": store}, tmp_path / "backup")
        restored = module.prepare_restore(tmp_path / "backup", tmp_path / "restore")
    assert restored == result
    assert result["effect_ids"] == [{"effect_id": "effect", "reservation_id": commit["reservation"]["reservation_id"]}]
    with closing(
        sqlite3.connect(f"{(tmp_path / 'restore' / module.DATABASE_NAME).as_uri()}?mode=ro&immutable=1", uri=True)
    ) as db:
        assert {table: db.execute(f"SELECT * FROM {table}").fetchall() for table in tables} == before
    assert {table: [tuple(row) for row in journal.db.execute(f"SELECT * FROM {table}")] for table in tables} == before


def test_final_directory_fsync_failure_is_explicit_uncertainty(ready, tmp_path, monkeypatch):
    journal, store, _ = ready
    module = api()
    original = os.fsync

    def fail_after_promotion(fd):
        if os.path.isdir(f"/proc/self/fd/{fd}") and module.MANIFEST_NAME in os.listdir(fd):
            raise OSError("final directory fsync failed")
        return original(fd)

    monkeypatch.setattr(module.os, "fsync", fail_after_promotion)
    with pytest.raises(module.BackupError, match="durability uncertain"):
        module.backup(journal, {"store": store}, tmp_path / "uncertain")
    assert json.loads((tmp_path / "uncertain" / module.MANIFEST_NAME).read_bytes())["activation_required"]


@pytest.mark.parametrize("operation", ["backup", "verify_backup", "prepare_restore"])
def test_operation_deadline_covers_filesystem_work(ready, tmp_path, monkeypatch, operation):
    journal, store, _ = ready
    module = api()
    source = tmp_path / "backup"
    module.backup(journal, {"store": store}, source)
    original = module._inventory

    def slow(*args, **kwargs):
        time.sleep(0.04)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "MAX_BACKUP_SECONDS", 0.03)
    monkeypatch.setattr(module, "_inventory", slow)
    with pytest.raises(module.BackupError, match="deadline"):
        if operation == "backup":
            module.backup(journal, {"store": store}, tmp_path / "out")
        elif operation == "verify_backup":
            module.verify_backup(source)
        else:
            module.prepare_restore(source, tmp_path / "out")
    assert not (tmp_path / "out" / module.MANIFEST_NAME).exists()


def test_backup_lock_contention_obeys_deadline(ready, tmp_path, monkeypatch):
    journal, store, _ = ready
    module = api()
    held, release = threading.Event(), threading.Event()

    def hold():
        with journal._lock:
            held.set()
            release.wait(0.5)

    thread = threading.Thread(target=hold)
    thread.start()
    assert held.wait(1)
    monkeypatch.setattr(module, "MAX_BACKUP_SECONDS", 0.03)
    start = time.monotonic()
    try:
        with pytest.raises(module.BackupError, match="deadline"):
            module.backup(journal, {"store": store}, tmp_path / "busy")
        assert time.monotonic() - start < 0.3
    finally:
        release.set()
        thread.join(1)


def test_sqlite_reference_work_is_interrupted_by_progress_deadline(ready, tmp_path, monkeypatch):
    journal, store, _ = ready
    module = api()
    root = tmp_path / "backup"
    module.backup(journal, {"store": store}, root)
    original = sqlite3.connect
    interrupted = []

    class SlowIntegrity(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == "PRAGMA integrity_check":
                try:
                    super().execute(
                        "WITH RECURSIVE work(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM work WHERE n<1000000) "
                        "SELECT sum(n) FROM work"
                    ).fetchone()
                except sqlite3.OperationalError:
                    interrupted.append(True)
                    raise
            return super().execute(sql, *args)

    monkeypatch.setattr(module.sqlite3, "connect", lambda *a, **k: original(*a, **k, factory=SlowIntegrity))
    monkeypatch.setattr(module, "MAX_BACKUP_SECONDS", 0.02)
    with pytest.raises(module.BackupError, match="deadline"):
        module.verify_backup(root)
    assert interrupted == [True]


@pytest.mark.parametrize(
    "attack", ["orphan-commit", "missing-intent", "orphan-intent", "target", "payload", "artifact"]
)
def test_resealed_database_rejects_broken_research_relations(ready, tmp_path, attack):
    journal, store, _ = ready
    module = api()
    args, _ = candidate(journal, key="publication")
    published = store.persist_candidate(
        "family", "publication", **args, publication_request={"effect_id": "effect", "target_profile": "graph"}
    )
    root = tmp_path / "backup"
    manifest = module.backup(journal, {"store": store}, root)
    database = root / module.DATABASE_NAME
    with closing(sqlite3.connect(database)) as db:
        for (trigger,) in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
            db.execute(f'DROP TRIGGER "{trigger}"')
        if attack == "orphan-commit":
            db.execute(
                "DELETE FROM research_reservations WHERE reservation_id=?",
                (published["reservation"]["reservation_id"],),
            )
        elif attack == "missing-intent":
            db.execute("DELETE FROM research_publication_intents")
        elif attack == "orphan-intent":
            db.execute(
                "DELETE FROM research_commits WHERE reservation_id=?", (published["reservation"]["reservation_id"],)
            )
        else:
            body = json.loads(db.execute("SELECT body FROM research_publication_intents").fetchone()[0])
            if attack == "artifact":
                body["payload"]["artifact_sha256"] = "0" * 64
                body["payload_sha256"] = module.digest(body["payload"])
            else:
                body["target_profile" if attack == "target" else "payload_sha256"] = "other"
            db.execute("UPDATE research_publication_intents SET body=?", (json.dumps(body),))
        db.commit()
    manifest["database"] = {
        "size": database.stat().st_size,
        "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
    }
    manifest["files"][module.DATABASE_NAME] = manifest["database"]
    (root / module.MANIFEST_NAME).write_text(json.dumps(manifest))
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(module.BackupError):
            module._index(fd)
    finally:
        os.close(fd)
    with pytest.raises(module.BackupError):
        module.verify_backup(root)
    with pytest.raises(module.BackupError):
        module.prepare_restore(root, tmp_path / "restore")


def test_layout_validation_indexes_paths_once(tmp_path):
    module = api()
    visits = []

    class CountedPaths(set):
        def __iter__(self):
            for item in super().__iter__():
                visits.append(item)
                yield item

    directories = CountedPaths({""})
    for number in range(80):
        name = f"family{number}"
        (tmp_path / name).mkdir(mode=0o700)
        directories.add(name)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        module._check_layout(fd, set(), directories, sealed=False)
    finally:
        os.close(fd)
    assert len(visits) <= 4 * len(directories)


@pytest.mark.parametrize("phase", ["before", "after"])
def test_process_death_at_seal_promotion_has_only_complete_final(ready, tmp_path, phase):
    journal, store, _ = ready
    module = api()
    root = tmp_path / "crashed"
    source = tmp_path / "backup"
    module.backup(journal, {"store": store}, source)
    code = """
import os, sys
from isaaclab_arena.agentic_environment_generation.workbench import research_backup as module
original = module._rename_noreplace
def crash(*args):
    if sys.argv[3] == "after":
        original(*args)
    os._exit(77)
module._rename_noreplace = crash
module.prepare_restore(sys.argv[1], sys.argv[2])
"""
    result = subprocess.run([sys.executable, "-c", code, str(source), str(root), phase], timeout=20)
    assert result.returncode == 77
    if phase == "before":
        assert not (root / module.MANIFEST_NAME).exists()
    else:
        assert module.verify_backup(root)["activation_required"] is True


def test_seal_promotion_never_overwrites_competing_target(ready, tmp_path, monkeypatch):
    journal, store, _ = ready
    module = api()
    original = module._rename_noreplace

    def race(source_fd, source, target_fd, target):
        module._write(target_fd, target, b"competing-original")
        return original(source_fd, source, target_fd, target)

    monkeypatch.setattr(module, "_rename_noreplace", race)
    with pytest.raises(FileExistsError):
        module.backup(journal, {"store": store}, tmp_path / "race")
    assert (tmp_path / "race" / module.MANIFEST_NAME).read_bytes() == b"competing-original"


def test_sessions_auth_material_stays_private_and_readonly_calls_never_activate(ready, tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench.sessions import Sessions

    journal, store, _ = ready
    module = api()
    sessions = Sessions(journal)
    body, cookie = sessions.create()
    private_values = [cookie, sessions._digest(cookie), body["csrf_token"], body["session_id"]]
    root = tmp_path / "backup"
    result = module.backup(journal, {"store": store}, root)
    public = json.dumps(result)
    assert all(value not in public for value in private_values)
    with closing(sqlite3.connect(f"{(root / module.DATABASE_NAME).as_uri()}?mode=ro&immutable=1", uri=True)) as db:
        row = db.execute("SELECT digest,csrf_token,session_id FROM sessions").fetchone()
        assert row == (private_values[1], private_values[2], private_values[3])

    def forbidden(*args, **kwargs):
        pytest.fail("read-only checkpoint call activated authentication or journal")

    monkeypatch.setattr(Sessions, "__init__", forbidden)
    monkeypatch.setattr(Journal, "__init__", forbidden)
    monkeypatch.setattr(Journal, "begin_run", forbidden)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert module.verify_backup(root) == result
    assert module.estimate_backup(root)["database_bytes"] == result["database"]["size"]
    assert module.prepare_restore(root, tmp_path / "restore") == result
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    for directory in (root, tmp_path / "restore"):
        assert directory.stat().st_mode & 0o777 == 0o700
        assert all(p.stat().st_mode & 0o777 == (0o700 if p.is_dir() else 0o600) for p in directory.rglob("*"))


@pytest.mark.parametrize("operation", ["read", "write"])
def test_deadline_checked_between_file_chunks(tmp_path, monkeypatch, operation):
    module = api()
    clock, calls = [0], []
    (tmp_path / "input").write_bytes(b"x" * 200000)
    (tmp_path / "input").chmod(0o600)
    original = getattr(os, operation)

    def slow(fd, data):
        calls.append(True)
        clock[0] += 1
        return original(fd, data if operation == "read" else data[:7])

    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module, "MAX_BACKUP_SECONDS", 0.5)
    monkeypatch.setattr(module.os, operation, slow)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(module.BackupError, match="deadline"):
            if operation == "read":
                module._operation(lambda: module._read(fd, "input", 200000))()
            else:
                module._operation(lambda: module._write(fd, "output", b"x" * 100))()
    finally:
        os.close(fd)
    assert len(calls) == 1
