# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Offline administrator contracts exercised in isolated CLI subprocesses."""

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena_examples.tests.test_workbench_research_backup import ready as checkpoint_fixture

MODULE = "isaaclab_arena_examples.agentic_environment_generation.research_admin"


def inventory(root):
    # Never open/close source files in the process owning a SQLite connection:
    # POSIX close would drop its locks and invalidate an active-writer test.
    code = """
import json, os, stat, sys
from pathlib import Path
root = Path(sys.argv[1])
result = {}
for path in [root, *root.rglob("*")]:
    info = path.lstat()
    payload = None
    if stat.S_ISREG(info.st_mode):
        payload = path.read_bytes().hex()
    elif stat.S_ISLNK(info.st_mode):
        payload = os.readlink(path)
    result[str(path.relative_to(root))] = (info.st_mode, info.st_nlink, payload)
print(json.dumps(result))
"""
    return json.loads(subprocess.check_output([sys.executable, "-c", code, str(root)], timeout=10))


@pytest.fixture
def ready(tmp_path):
    yield from checkpoint_fixture.__wrapped__(tmp_path)


def cli(*args):
    if args and args[0] in ("init-store", "backup"):
        args = (*args, "--attest-quiescent")
    return subprocess.run([sys.executable, "-m", MODULE, *map(str, args)], capture_output=True, text=True, timeout=40)


def test_init_reopens_without_taking_scheduler_ownership(tmp_path):
    path, root = tmp_path / "journal.sqlite3", tmp_path / "store"
    with closing(Journal(path)) as journal:
        journal.db.execute("UPDATE metadata SET value=0 WHERE key='clean_shutdown'")
        before = [tuple(row) for row in journal.db.execute("SELECT * FROM metadata ORDER BY key")]
    first = None
    for _ in range(2):
        result = cli(
            "init-store", "--journal", path, "--store-id", "local", "--root", root, "--attest-local-filesystem"
        )
        assert result.returncode == 0, result.stdout + result.stderr
        current = json.loads(result.stdout)
        assert current["store_id"] == "local"
        if first is not None:
            assert current["registry_id"] == first["registry_id"]
        first = current
    with closing(sqlite3.connect(path)) as db:
        assert before == db.execute("SELECT * FROM metadata ORDER BY key").fetchall()
        assert not db.execute("SELECT * FROM jobs").fetchall()
    assert root.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize(
    "kind",
    [
        "absent",
        "wrong",
        "old",
        "missing_table",
        "missing_trigger",
        "forged_trigger",
        "wrong_column_type",
        "relative",
        "symlink",
        "ancestor_symlink",
        "hardlink",
        "fifo",
        "public",
    ],
)
def test_journal_preflight_does_not_migrate_or_disclose(tmp_path, kind):
    path = tmp_path / "journal.sqlite3"
    if kind == "wrong":
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE private_sentinel(secret TEXT)")
        path.chmod(0o600)
    elif kind not in {"absent", "fifo"}:
        with closing(Journal(path)) as journal:
            if kind == "old":
                journal.db.execute("PRAGMA user_version=0")
            if kind == "missing_table":
                journal.db.execute("DROP TABLE modern_candidate_receipts")
            if kind in {"missing_trigger", "forged_trigger"}:
                journal.db.execute("DROP TRIGGER modern_receipt_no_delete")
            if kind == "forged_trigger":
                journal.db.execute(
                    "CREATE TRIGGER modern_receipt_no_delete BEFORE DELETE ON modern_candidate_receipts BEGIN SELECT"
                    " 1; END"
                )
            if kind == "wrong_column_type":
                journal.db.execute("DROP TABLE workers")
                journal.db.execute(
                    "CREATE TABLE workers(job_id TEXT PRIMARY KEY,pid TEXT NOT NULL,identity TEXT NOT NULL,cleaned"
                    " INTEGER NOT NULL)"
                )
    argument = path
    if kind == "relative":
        argument = "relative-secret.sqlite3"
    elif kind == "symlink":
        argument = tmp_path / "link"
        argument.symlink_to(path)
    elif kind == "ancestor_symlink":
        link = tmp_path / "alias"
        link.symlink_to(tmp_path, target_is_directory=True)
        argument = link / path.name
    elif kind == "hardlink":
        os.link(path, tmp_path / "alias")
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "public":
        path.chmod(0o644)
    before_inventory = inventory(tmp_path)
    before = path.read_bytes() if path.is_file() else None
    result = cli(
        "init-store",
        "--journal",
        argument,
        "--store-id",
        "local",
        "--root",
        tmp_path / "store",
        "--attest-local-filesystem",
    )
    assert result.returncode != 0
    assert json.loads(result.stdout) == {"ok": False, "error": "invalid_request"}
    assert result.stderr == ""
    assert inventory(tmp_path) == before_inventory
    assert not (tmp_path / "store").exists()
    if before is not None:
        assert path.read_bytes() == before
    elif kind == "absent":
        assert not path.exists()


@pytest.mark.parametrize("kind", ["relative", "legacy", "symlink", "attestation", "abbreviated_attestation"])
def test_root_rejection_is_explicit_and_nonmutating(tmp_path, kind):
    path = tmp_path / "journal.sqlite3"
    with closing(Journal(path)):
        pass
    root = tmp_path / "store"
    if kind == "relative":
        root = "relative-store"
    elif kind == "legacy":
        root = tmp_path / "generated_envs" / "store"
    elif kind == "symlink":
        root.symlink_to(tmp_path)
    args = ["init-store", "--journal", path, "--store-id", "local", "--root", root]
    if kind != "attestation":
        args.append("--attest-local" if kind == "abbreviated_attestation" else "--attest-local-filesystem")
    before = path.read_bytes()
    result = cli(*args)
    assert result.returncode != 0
    assert json.loads(result.stdout)["error"] == "invalid_request"
    assert path.read_bytes() == before


def test_backup_verify_estimate_restore_exact_bytes(ready, tmp_path):
    journal, store, commit = ready
    source, destination = tmp_path / "checkpoint", tmp_path / "restored"
    journal.db.execute("CREATE TABLE opaque_private (value TEXT)")
    journal.db.execute("INSERT INTO opaque_private VALUES ('DO_NOT_PRINT_COOKIE_OR_CSRF')")
    journal.close()
    result = cli(
        "backup",
        "--journal",
        tmp_path / "journal.sqlite3",
        "--store",
        f"store={tmp_path / 'source'}",
        "--destination",
        source,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary["reference_count"] == 1
    assert summary["store_ids"] == ["store"]
    assert "DO_NOT_PRINT" not in result.stdout
    assert "references" not in summary and "files" not in summary
    for command in ("verify-checkpoint", "estimate-checkpoint"):
        result = cli(command, "--source", source)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["ok"] is True
    result = cli("prepare-restore", "--source", source, "--destination", destination)
    assert result.returncode == 0, result.stdout + result.stderr
    restored = json.loads(result.stdout)
    assert restored["activation_required"] is True
    assert restored["inactive_database"] == str(destination / "journal.inactive.sqlite3")
    for path in source.rglob("*"):
        if path.is_file():
            assert (destination / path.relative_to(source)).read_bytes() == path.read_bytes()
    assert (tmp_path / "source" / commit["relative_directory"]).is_dir()
    result = cli("prepare-restore", "--source", source, "--destination", destination)
    assert result.returncode != 0


def test_partial_profiles_preserve_failed_destination(ready, tmp_path):
    journal, _, _ = ready
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore

    with ResearchStore.create(journal, tmp_path / "second", "second", protect_public=lambda value: None):
        pass
    target = tmp_path / "incomplete"
    journal.close()
    result = cli(
        "backup",
        "--journal",
        tmp_path / "journal.sqlite3",
        "--store",
        f"store={tmp_path / 'source'}",
        "--destination",
        target,
    )
    assert result.returncode != 0
    assert target.is_dir()
    assert not (target / "checkpoint.json").exists()
    assert (target / "journal.inactive.sqlite3").exists()


def test_existing_destination_never_clobbered(ready, tmp_path):
    journal, _, _ = ready
    target = tmp_path / "existing"
    target.mkdir(mode=0o700)
    sentinel = target / "sentinel"
    sentinel.write_bytes(b"keep")
    journal.close()
    result = cli(
        "backup",
        "--journal",
        tmp_path / "journal.sqlite3",
        "--store",
        f"store={tmp_path / 'source'}",
        "--destination",
        target,
    )
    assert result.returncode != 0
    assert sentinel.read_bytes() == b"keep"
    assert list(target.iterdir()) == [sentinel]


def test_locked_journal_returns_static_busy(tmp_path):
    path = tmp_path / "journal.sqlite3"
    with closing(Journal(path)) as journal:
        journal.db.execute("BEGIN IMMEDIATE")
        try:
            result = cli(
                "init-store",
                "--journal",
                path,
                "--store-id",
                "local",
                "--root",
                tmp_path / "store",
                "--attest-local-filesystem",
            )
            assert result.returncode == 3
            assert json.loads(result.stdout) == {"ok": False, "error": "busy"}
        finally:
            journal.db.execute("ROLLBACK")
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize(
    "value",
    [
        {"password": "x"},
        {"note": "Bearer private-marker"},
        {"note": "-----BEGIN " + "PRIVATE KEY-----"},
        {"note": "api_key=private-marker"},
    ],
)
def test_static_public_guard_rejects_private_markers(value):
    import importlib

    admin = importlib.import_module(MODULE)
    with pytest.raises(ValueError):
        admin.protect_public(value)


def test_durability_uncertain_is_distinct_and_does_not_delete(ready, tmp_path, monkeypatch, capsys):
    import importlib

    admin = importlib.import_module(MODULE)
    original = admin.research_backup.backup
    target = tmp_path / "uncertain"

    def uncertain(*args):
        original(*args)
        raise admin.research_backup.BackupDurabilityUncertain("NEVER DISCLOSE THIS")

    journal, _, _ = ready
    journal.close()
    monkeypatch.setattr(admin.research_backup, "backup", uncertain)
    assert (
        admin.main([
            "backup",
            "--attest-quiescent",
            "--journal",
            str(tmp_path / "journal.sqlite3"),
            "--store",
            f"store={tmp_path / 'source'}",
            "--destination",
            str(target),
        ])
        == 4
    )
    assert json.loads(capsys.readouterr().out) == {"ok": False, "error": "durability_uncertain"}
    assert admin.research_backup.verify_backup(target)["activation_required"]


def test_no_lifecycle_network_inference_or_credential_reads(tmp_path):
    live = tmp_path / "live"
    live.mkdir(mode=0o700)
    path = live / "journal.sqlite3"
    with closing(Journal(path)):
        pass
    code = """
import os, runpy, sys
from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
def forbidden(*args, **kwargs):
    raise AssertionError("Forbidden lifecycle operation")
for name in ("__init__", "begin_run", "recover", "finish_run", "submit"):
    setattr(Journal, name, forbidden)
from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
for name in ("claim", "accept_request", "release", "recover", "recover_worker_dispatch", "record_worker"):
    setattr(PublicationAttempts, name, forbidden)
def audit(event, args):
    if event in ("socket.connect", "subprocess.Popen", "os.system"):
        forbidden()
    if event == "open" and isinstance(args[0], str):
        name = os.path.basename(args[0]).lower()
        if name == ".env" or name.startswith(".env.") or name in ("credentials", "credentials.json"):
            forbidden()
sys.addaudithook(audit)
def profile(frame, event, arg):
    if event == "call" and (
        frame.f_code.co_name == "create_app"
        or (frame.f_code.co_name == "main" and frame.f_code.co_filename.endswith("publication_worker.py"))
    ):
        forbidden()
sys.setprofile(profile)
sys.argv = [sys.argv[1], *sys.argv[2:]]
runpy.run_module(sys.argv[0], run_name="__main__")
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            MODULE,
            "init-store",
            "--attest-quiescent",
            "--journal",
            str(path),
            "--store-id",
            "local",
            "--root",
            str(live / "store"),
            "--attest-local-filesystem",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["ok"]
    ledger = subprocess.run(
        [sys.executable, "-c", code, MODULE, "init-publication-ledger", "--journal", str(path), "--attest-quiescent"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert ledger.returncode == 0, ledger.stdout + ledger.stderr
    assert json.loads(ledger.stdout)["worker_support_ready"]
    source, restored = tmp_path / "checkpoint", tmp_path / "restored"
    before = inventory(live)
    for args in (
        [
            "backup",
            "--journal",
            str(path),
            "--store",
            f"local={live / 'store'}",
            "--destination",
            str(source),
            "--attest-quiescent",
        ],
        ["verify-checkpoint", "--source", str(source)],
        ["estimate-checkpoint", "--source", str(source)],
        ["prepare-restore", "--source", str(source), "--destination", str(restored)],
    ):
        result = subprocess.run([sys.executable, "-c", code, MODULE, *args], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["ok"]
    assert inventory(live) == before
    assert inventory(source) == inventory(restored)


@pytest.mark.parametrize("invalid", [False, True])
def test_committed_wal_is_authoritative_and_source_untouched(tmp_path, invalid):
    import importlib

    path = tmp_path / "journal.sqlite3"
    with closing(Journal(path)):
        pass
    main_before = path.read_bytes()
    sql = (
        "UPDATE metadata SET value=9 WHERE key='attempt_schema_version'" if invalid else "CREATE TABLE wal_only(value)"
    )
    code = (
        "import os,sqlite3,sys; d=sqlite3.connect(sys.argv[1],isolation_level=None); d.execute(sys.argv[2]);"
        " os._exit(0)"
    )
    subprocess.run([sys.executable, "-c", code, str(path), sql], check=True, timeout=10)
    assert path.read_bytes() == main_before
    assert (tmp_path / "journal.sqlite3-wal").stat().st_size > 32
    before = inventory(tmp_path)
    admin = importlib.import_module(MODULE)
    if invalid:
        with pytest.raises(ValueError):
            with admin._journal(str(path)):
                pytest.fail("stale main database accepted")
    else:
        with admin._journal(str(path)) as journal:
            assert journal.db.execute("SELECT * FROM wal_only").fetchall() == []
            assert not hasattr(journal, "submit")
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("kind", ["idle", "writer", "same_process"])
def test_active_wal_busy_preserves_inventory(tmp_path, kind):
    import importlib
    import time

    path = tmp_path / "journal.sqlite3"
    with closing(Journal(path)) as journal:
        if kind == "writer":
            journal.db.execute("BEGIN IMMEDIATE")
        before = inventory(tmp_path)
        started = time.monotonic()
        if kind == "same_process":
            admin = importlib.import_module(MODULE)
            with pytest.raises(admin.SafeBusy):
                with admin._journal(str(path)):
                    pytest.fail("active connection accepted")
        else:
            result = cli(
                "init-store",
                "--journal",
                path,
                "--store-id",
                "local",
                "--root",
                tmp_path / "store",
                "--attest-local-filesystem",
            )
            assert result.returncode == 3
        assert time.monotonic() - started < 3
        assert inventory(tmp_path) == before
        if kind == "writer":
            journal.db.execute("ROLLBACK")


@pytest.mark.parametrize("limit", ["MAX_PREFLIGHT_BYTES", "PREFLIGHT_SECONDS"])
def test_preflight_bounds_preserve_source(tmp_path, monkeypatch, limit):
    import importlib

    path = tmp_path / "journal.sqlite3"
    with closing(Journal(path)):
        pass
    admin = importlib.import_module(MODULE)
    before = inventory(tmp_path)
    monkeypatch.setattr(admin, limit, 0)
    with pytest.raises((ValueError, admin.SafeBusy)):
        with admin._journal(str(path)):
            pytest.fail("copy bound ignored")
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode", "contents"])
def test_sidecar_rejection_preserves_full_inventory(tmp_path, suffix, kind):
    path = tmp_path / "journal.sqlite3"
    with closing(Journal(path)) as journal:
        journal.db.execute("UPDATE metadata SET value=9 WHERE key='attempt_schema_version'")
    sidecar = tmp_path / (path.name + suffix)
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"opaque private bytes")
    sentinel.chmod(0o600)
    if kind == "symlink":
        sidecar.symlink_to(sentinel)
    elif kind == "hardlink":
        os.link(sentinel, sidecar)
    else:
        sidecar.write_bytes(b"opaque sidecar data")
        sidecar.chmod(0o644 if kind == "mode" else 0o600)
    before = inventory(tmp_path)
    result = cli(
        "init-store",
        "--journal",
        path,
        "--store-id",
        "local",
        "--root",
        tmp_path / "store",
        "--attest-local-filesystem",
    )
    assert result.returncode == 2
    assert inventory(tmp_path) == before


def test_explicit_offline_gate_required(tmp_path):
    path = tmp_path / "journal.sqlite3"
    with closing(Journal(path)):
        pass
    before = inventory(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            MODULE,
            "init-store",
            "--journal",
            str(path),
            "--store-id",
            "local",
            "--root",
            str(tmp_path / "store"),
            "--attest-local-filesystem",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert inventory(tmp_path) == before


def test_publication_ledger_initializes_only_local_tables(ready, tmp_path):
    from isaaclab_arena_examples.tests.test_workbench_research_store import candidate

    journal, store, _ = ready
    args, _ = candidate(journal, key="publication")
    store.persist_candidate(
        "family", "publication", **args, publication_request={"effect_id": "effect", "target_profile": "graph"}
    )
    registry_id = store.registry.registry_id
    before = {
        row[0]: [tuple(item) for item in journal.db.execute(f'SELECT * FROM "{row[0]}"')]
        for row in journal.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    journal.close()
    result = cli("init-publication-ledger", "--journal", tmp_path / "journal.sqlite3", "--attest-quiescent")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "ok": True,
        "registry_id": registry_id,
        "worker_support_ready": True,
        "no_graph_changes": True,
    }
    assert result.stderr == ""
    with closing(sqlite3.connect(tmp_path / "journal.sqlite3")) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables - before.keys() == {
            "publication_meta",
            "publication_states",
            "publication_bindings",
            "publication_receipts",
            "publication_worker_meta",
            "publication_requests",
            "publication_workers",
        }
        for table, rows in before.items():
            assert db.execute(f'SELECT * FROM "{table}"').fetchall() == rows
        for table in tables - before.keys() - {"publication_meta", "publication_worker_meta"}:
            assert db.execute(f'SELECT * FROM "{table}"').fetchall() == []
    from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
    from isaaclab_arena.agentic_environment_generation.workbench.research_registry import ResearchRegistry
    from isaaclab_arena_examples.tests.test_workbench_research_publication import grant, identity, receipt

    # Populate real acceptance and worker lifecycle records using local-only
    # synthetic evidence. The comparator here does not assert graph verification.
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        registry = ResearchRegistry(journal)
        attempts = PublicationAttempts(
            journal,
            registry,
            clock=lambda: 100,
            protect_public=lambda value: value,
            authorizer=lambda metadata, **scope: ({}, metadata),
        )
        intent = registry.get_publication_intent("effect")
        metadata = grant(payload_sha256=intent["payload_sha256"])
        state = attempts.accept_request(
            "effect",
            "request",
            metadata,
            owner_session="owner",
            principal="owner",
            store_id=registry.store_ids()[0],
            operation="write",
            request_digest="a" * 64,
        )["state"]
        worker = {"pid": 4321, "start_ticks": 100, "boot_id": "fixture"}
        assert attempts.record_worker(
            "effect",
            **identity(state),
            capability="graph_write",
            pid=4321,
            identity=worker,
        )
        assert (
            attempts.release_worker(
                "effect",
                **identity(state),
                worker_identity=worker,
                grant_metadata=metadata,
                prepare_private=lambda config, intent: b"fixture",
            )
            == b"fixture"
        )
        evidence = receipt(payload_sha256=intent["payload_sha256"])
        for key in ("scope_id", "projection_digest"):
            if key in intent["payload"]:
                evidence["transport"][key] = intent["payload"][key]
        assert attempts.complete_worker_verified(
            "effect",
            **identity(state),
            worker_identity=worker,
            receipt=evidence,
            comparator=lambda *args: True,
        )
        assert attempts.worker_cleaned("effect", **identity(state), worker_identity=worker)
        assert journal.db.execute("SELECT COUNT(*) FROM publication_requests").fetchone()[0] == 1
        assert tuple(
            journal.db.execute("SELECT released,callback_open,cleaned FROM publication_workers").fetchone()
        ) == (1, 0, 1)
        assert journal.db.execute("SELECT COUNT(*) FROM publication_receipts").fetchone()[0] == 1
    with closing(sqlite3.connect(tmp_path / "journal.sqlite3")) as db:
        snapshot = list(db.iterdump())
    for _ in range(2):
        replay = cli("init-publication-ledger", "--journal", tmp_path / "journal.sqlite3", "--attest-quiescent")
        assert replay.returncode == 0, replay.stdout + replay.stderr
        assert json.loads(replay.stdout) == json.loads(result.stdout)
        with closing(sqlite3.connect(tmp_path / "journal.sqlite3")) as db:
            assert list(db.iterdump()) == snapshot
            for table in ("research_publication_intents", "publication_receipts"):
                with pytest.raises(sqlite3.IntegrityError):
                    db.execute(f"DELETE FROM {table}")


@pytest.mark.parametrize(
    "kind",
    [
        "missing_registry",
        "no_stores",
        "attestation",
        "active",
        "relative",
        "future_registry",
        "future_core",
        "wrong_registry",
        "future_worker",
        "wrong_worker_registry",
        "orphan_worker",
        "missing_core_table",
        "missing_trigger",
    ],
)
def test_publication_ledger_rejection_preserves_inventory(tmp_path, kind):
    from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
    from isaaclab_arena.agentic_environment_generation.workbench.research_registry import ResearchRegistry

    path = tmp_path / "journal.sqlite3"
    journal = Journal(path)
    try:
        if kind != "missing_registry":
            registry = ResearchRegistry(journal, initialize=True)
            if kind != "no_stores":
                registry.register_store("store")
            if kind in {
                "future_core",
                "wrong_registry",
                "future_worker",
                "wrong_worker_registry",
                "missing_core_table",
                "missing_trigger",
            }:
                attempts = PublicationAttempts(journal, registry, initialize=True, protect_public=lambda value: value)
                attempts.initialize_worker_support()
            statements = {
                "future_registry": "UPDATE research_registry_meta SET schema_version=99",
                "future_core": "UPDATE publication_meta SET schema_version=99",
                "wrong_registry": "UPDATE publication_meta SET registry_id='other'",
                "future_worker": "UPDATE publication_worker_meta SET schema_version=99",
                "wrong_worker_registry": "UPDATE publication_worker_meta SET registry_id='other'",
                "orphan_worker": "CREATE TABLE publication_workers (private_sentinel TEXT)",
                "missing_core_table": "DROP TABLE publication_states",
                "missing_trigger": "DROP TRIGGER publication_receipts_no_update",
            }
            if kind in statements:
                journal.db.execute(statements[kind])
        if kind != "active":
            journal.close()
            # Leave authoritative committed WAL behind, so even a failed writable
            # attach would visibly recover/checkpoint source sidecars.
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os,sqlite3,sys; d=sqlite3.connect(sys.argv[1]); d.execute('CREATE TABLE"
                        " wal_sentinel(value)'); d.commit(); os._exit(0)"
                    ),
                    str(path),
                ],
                check=True,
            )
        before = inventory(tmp_path)
        args = ["init-publication-ledger", "--journal", "relative.sqlite3" if kind == "relative" else path]
        if kind != "attestation":
            args.append("--attest-quiescent")
        result = cli(*args)
        assert result.returncode == (3 if kind == "active" else 2), result.stdout + result.stderr
        assert json.loads(result.stdout) == {"ok": False, "error": "busy" if kind == "active" else "invalid_request"}
        assert result.stderr == ""
        assert inventory(tmp_path) == before
    finally:
        journal.close()


@pytest.mark.parametrize(
    "sql",
    [
        *[
            f"DROP TRIGGER {table}_no_{action}"
            for table in ("publication_requests", "publication_workers", "publication_bindings", "publication_receipts")
            for action in ("delete", "update", "replace")
        ],
        "DROP TRIGGER publication_workers_monotonic",
        "UPDATE publication_worker_meta SET schema_version=99",
        "UPDATE publication_meta SET schema_version=99",
        "DROP TABLE publication_worker_meta",
        "DROP TABLE publication_requests",
    ],
)
def test_publication_wal_schema_damage_preserves_full_source(tmp_path, sql):
    from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
    from isaaclab_arena.agentic_environment_generation.workbench.research_registry import ResearchRegistry

    path = tmp_path / "journal.sqlite3"
    with closing(Journal(path)) as journal:
        registry = ResearchRegistry(journal, initialize=True)
        registry.register_store("store")
        attempts = PublicationAttempts(journal, registry, initialize=True, protect_public=lambda value: value)
        attempts.initialize_worker_support()
    main_before = path.read_bytes()
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os,sqlite3,sys; d=sqlite3.connect(sys.argv[1],isolation_level=None); d.execute(sys.argv[2]);"
                " os._exit(0)"
            ),
            str(path),
            sql,
        ],
        check=True,
        timeout=10,
    )
    assert path.read_bytes() == main_before
    assert (tmp_path / "journal.sqlite3-wal").stat().st_size > 32
    before = inventory(tmp_path)
    result = cli("init-publication-ledger", "--journal", path, "--attest-quiescent")
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"ok": False, "error": "invalid_request"}
    assert result.stderr == ""
    assert inventory(tmp_path) == before


def test_help_and_unknown_secret_flags_are_safe():
    result = cli("--help")
    assert result.returncode == 0
    for name in (
        "init-store",
        "init-publication-ledger",
        "backup",
        "verify-checkpoint",
        "estimate-checkpoint",
        "prepare-restore",
    ):
        assert name in result.stdout
        assert cli(name, "--help").returncode == 0
    result = cli("init-store", "--api-key", "DO_NOT_ECHO")
    assert result.returncode != 0
    assert "DO_NOT_ECHO" not in result.stdout + result.stderr
