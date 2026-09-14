# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Research facade contracts against isolated SQLite and actual filesystem bytes."""

import hashlib
import json
import sys
from contextlib import closing
from pathlib import Path

import pytest

from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena.agentic_environment_generation.workbench.research_registry import canonical_json


def candidate(journal, *, key="candidate", receipt_change=None):
    job = journal.submit("owner", "default", "generate", key, {"operation": "new", "prompt": "synthetic"})
    attempt = journal.claim_attempt(job["id"])
    assert journal.release_attempt(job["id"], **attempt)
    text = (
        Path(__file__).parents[2] / "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"
    ).read_text()
    receipt = {
        "yaml_text": text,
        "validation": {
            "valid": True,
            "source_hash": hashlib.sha256(text.encode()).hexdigest(),
        },
        "publication": "not_published",
    }
    if receipt_change:
        receipt_change(receipt)
    assert journal.commit_candidate(job["id"], **attempt, receipt=receipt)
    assert journal.complete_attempt(job["id"], **attempt, expected_state="candidate_committed")
    return (
        dict(
            job_id=job["id"],
            **attempt,
            approval={"scope": "persist_candidate", "principal": "owner"},
        ),
        receipt,
    )


@pytest.fixture
def ready(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore

    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        journal.begin_run()
        args, receipt = candidate(journal)
        with ResearchStore.create(journal, tmp_path / "managed", "store", protect_public=lambda value: None) as store:
            yield store, args, receipt


def mutate_public_metadata(value, mode):
    """Inject callback-only corruption, never malformed HTTP request JSON."""
    if mode == "object":
        value["private-callback-marker"] = object()
    elif mode == "deep":
        nested = "private-callback-marker"
        for _ in range(max(10000, sys.getrecursionlimit() + 10)):
            nested = [nested]
        value["private-callback-marker"] = nested
    elif mode == "cycle":
        value["private-callback-marker"] = value
    elif mode == "idempotent":
        value["generation"] = 999
    else:
        assert mode == "json"
        value.setdefault("private-callback-marker", []).append("changed")


def public_callback_target(value, boundary, seen):
    """Select a real store callback boundary, including retained earlier values."""
    if not isinstance(value, dict):
        return None
    targets = {}
    if "operation" in value:
        targets["request"] = value
    elif "yaml_text" in value:
        targets["receipt"] = value
    elif "approval" in value and "workflow_id" in value:
        targets["approval"] = value["approval"]
        targets["publication-request"] = value["publication_request"]
    elif "nodes" in value:
        targets["projection"] = value
    elif "payload" in value and "effect_id" in value:
        targets["intent"] = value
    seen.update(targets)
    if boundary.startswith("late-"):
        return seen[boundary.removeprefix("late-")] if "intent" in targets else None
    if boundary.startswith("projection-"):
        return seen[boundary.removeprefix("projection-")] if "projection" in targets else None
    return targets.get(boundary)


@pytest.mark.parametrize("mode", ["object", "deep", "cycle", "idempotent", "json"])
@pytest.mark.parametrize(
    "boundary",
    [
        "request",
        "receipt",
        "approval",
        "publication-request",
        "projection",
        "intent",
        "late-request",
        "late-receipt",
        "late-approval",
        "late-publication-request",
        "late-projection",
        "projection-request",
        "projection-receipt",
        "projection-approval",
        "projection-publication-request",
    ],
)
@pytest.mark.parametrize("replay", [False, True])
def test_persistence_callback_corruption_preserves_durable_data(ready, tmp_path, monkeypatch, mode, boundary, replay):
    store, args, receipt = ready
    request = {"effect_id": "effect", "target_profile": "graph"}
    original = store.persist_candidate("family", "save", **args, publication_request=request)
    resid = original["reservation"]["reservation_id"]
    files = store.read_version(resid)
    intent = store.registry.get_publication_intent("effect")
    reference = store.candidate_reference(args["job_id"])
    journal = store.registry.journal
    job = journal.get_job(args["job_id"])
    durable = list(journal.db.iterdump())
    schema = journal.db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    workflow = "save" if replay else "blocked"
    if not replay:
        request["effect_id"] = "blocked-effect"
    seen, changed = {}, []

    def mutate(value):
        target = public_callback_target(value, boundary, seen)
        if target is not None:
            mutate_public_metadata(target, mode)
            changed.append(True)

    with monkeypatch.context() as patch:
        patch.setattr(store, "protect_public", mutate)
        patch.setattr(store.area, "stage", lambda *a, **k: pytest.fail("Corrupt artifact staged"))
        patch.setattr(store.registry, "record_commit", lambda *a, **k: pytest.fail("Corrupt commit written"))
        with pytest.raises(ValueError) as error:
            store.persist_candidate("family", workflow, **args, publication_request=request)
        assert str(error.value) == "Public protection must not mutate immutable research data"
    assert changed == [True]
    assert store.read_version(resid) == files
    assert store.registry.get_commit(resid) == original
    assert store.registry.get_publication_intent("effect") == intent
    assert store.registry.get_publication_intent("blocked-effect") is None
    assert store.candidate_reference(args["job_id"]) == reference
    assert journal.get_job(args["job_id"]) == job
    assert journal.get_candidate_receipt(args["job_id"], args["attempt_id"], args["generation"]) == receipt
    assert journal.db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == schema
    assert list((tmp_path / "managed/staging").iterdir()) == []
    assert [path.name for path in (tmp_path / "managed/final/family").iterdir()] == ["v1"]
    if replay or boundary in {"request", "receipt", "approval", "publication-request"}:
        assert list(journal.db.iterdump()) == durable
    else:
        reservation = store.registry.get_reservation_for_workflow("store", workflow)
        assert reservation is not None
        assert store.registry.get_commit(reservation["reservation_id"]) is None


@pytest.mark.parametrize("mode", ["object", "deep", "cycle", "idempotent", "json"])
def test_candidate_reference_rejects_callback_mutation(ready, monkeypatch, mode):
    store, args, _ = ready
    original = store.candidate_reference(args["job_id"])
    journal = store.registry.journal
    before = journal.db.total_changes
    durable = list(journal.db.iterdump())

    with monkeypatch.context() as patch:
        patch.setattr(store, "protect_public", lambda value: mutate_public_metadata(value, mode))
        for _ in range(2):
            with pytest.raises(ValueError) as error:
                store.candidate_reference(args["job_id"])
            assert str(error.value) == "Public protection must not mutate immutable research data"
    assert store.candidate_reference(args["job_id"]) == original
    assert journal.db.total_changes == before
    assert list(journal.db.iterdump()) == durable


@pytest.mark.parametrize(
    "boundary", ["candidate", "request", "receipt", "approval", "publication-request", "projection", "intent"]
)
def test_store_preserves_callback_http_exception(ready, monkeypatch, boundary):
    from fastapi import HTTPException

    store, args, _ = ready
    request = {"effect_id": "effect", "target_profile": "graph"}
    original = store.persist_candidate("family", "save", **args, publication_request=request)
    reference = store.candidate_reference(args["job_id"])
    durable = list(store.registry.journal.db.iterdump())
    rejected = HTTPException(422, "Invalid request input", headers={"X-Test-Rejection": "preserved"})
    seen = {}

    def reject(value):
        target = value if boundary == "candidate" else public_callback_target(value, boundary, seen)
        if target is not None:
            mutate_public_metadata(target, "object")
            raise rejected

    with monkeypatch.context() as patch:
        patch.setattr(store, "protect_public", reject)
        with pytest.raises(HTTPException) as error:
            if boundary == "candidate":
                store.candidate_reference(args["job_id"])
            else:
                store.persist_candidate("family", "save", **args, publication_request=request)
    assert error.value is rejected
    assert store.candidate_reference(args["job_id"]) == reference
    assert store.registry.get_commit(original["reservation"]["reservation_id"]) == original
    assert list(store.registry.journal.db.iterdump()) == durable


@pytest.mark.parametrize("mode", ["noop", "reorder"])
def test_store_allows_canonically_unchanged_callback(ready, monkeypatch, mode):
    store, args, _ = ready
    request = {"effect_id": "effect", "target_profile": "graph"}
    original = store.persist_candidate("family", "save", **args, publication_request=request)
    reference = store.candidate_reference(args["job_id"])
    durable = list(store.registry.journal.db.iterdump())

    def unchanged(value):
        if mode == "reorder":
            items = list(value.items())
            value.clear()
            value.update(reversed(items))

    monkeypatch.setattr(store, "protect_public", unchanged)
    assert store.candidate_reference(args["job_id"]) == reference
    assert store.persist_candidate("family", "save", **args, publication_request=request) == original
    assert list(store.registry.journal.db.iterdump()) == durable


def test_publication_request_freezes_projection_and_pending_intent_without_writing_graph(ready, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench import research_graph_transport

    store, args, _ = ready
    monkeypatch.setattr(research_graph_transport, "publish_once", lambda *a, **k: pytest.fail("Graph write"))
    request = {"effect_id": "effect-one", "target_profile": "approved-graph"}
    commit = store.persist_candidate("family", "save-and-request", **args, publication_request=request)
    assert commit["publication_intent_id"] == "effect-one"
    files = store.read_version(commit["reservation"]["reservation_id"])
    projection = json.loads(files["projection.json"])
    intent = store.registry.get_publication_intent("effect-one")
    assert intent["state"] == "pending"
    assert intent["payload"]["artifact_sha256"] == hashlib.sha256(files["projection.json"]).hexdigest()
    assert intent["payload"]["projection_digest"] == projection["digest"]
    assert store.persist_candidate("family", "save-and-request", **args, publication_request=request) == commit
    with pytest.raises(ValueError, match="conflict"):
        store.persist_candidate("family", "save-and-request", **args, publication_request=None)


@pytest.mark.parametrize(
    "attack", ["projection", "projection-resealed", "payload", "options", "target", "publication-request"]
)
def test_publication_protection_mutation_never_stages(ready, tmp_path, monkeypatch, attack):
    from isaaclab_arena.agentic_environment_generation.workbench import research_graph_transport
    from isaaclab_arena.agentic_environment_generation.workbench.research_projection import project_scene
    from isaaclab_arena.agentic_environment_generation.workbench.research_registry import digest
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    store, args, _ = ready
    request = {"effect_id": "effect", "target_profile": "graph", "options": {"mode": "create"}}

    def mutate(value):
        if "nodes" in value and attack.startswith("projection"):
            if attack == "projection-resealed":
                root = next(node for node in value["nodes"] if node["labels"] == ["EnvironmentGraph"])
                source = json.loads(root["properties"]["spec_json"])
                source["env_name"] = "different-source"
                scope = {key: value["scope"][key] for key in ("revision_id", "store_id", "family", "version")}
                value.update(project_scene(ArenaEnvGraphSpec.from_dict(source), **scope))
            else:
                value["nodes"][0]["properties"]["changed"] = True
        elif "payload" in value:
            if attack == "payload":
                value["payload"]["artifact_sha256"] = "0" * 64
                value["payload_sha256"] = digest(value["payload"])
            elif attack == "options":
                value["options"]["mode"] = "replace"
            elif attack == "target":
                value["target_profile"] = "other"
            elif attack == "publication-request":
                request["effect_id"] = "different"

    store.protect_public = mutate
    monkeypatch.setattr(research_graph_transport, "publish_once", lambda *a, **k: pytest.fail("Graph write"))
    monkeypatch.setattr(store.area, "stage", lambda *a, **k: pytest.fail("Artifact write before rejection"))
    monkeypatch.setattr(store.registry, "record_commit", lambda *a, **k: pytest.fail("Commit before rejection"))
    with pytest.raises(ValueError, match="mutate"):
        store.persist_candidate("family", "save", **args, publication_request=request)
    rows = store.list_versions("family")
    assert len(rows) == 1
    assert rows[0]["state"] == "reserved"
    assert store.registry.get_publication_intent("effect") is None
    assert list((tmp_path / "managed/staging").iterdir()) == []
    assert list((tmp_path / "managed/final").iterdir()) == []
    assert store.registry.reserve_candidate("store", "family", "next", **args)["version"] == 2


@pytest.mark.parametrize(
    "approval",
    [None, {"scope": "publish", "principal": "owner"}, {"scope": "persist_candidate", "principal": "other"}],
)
def test_reserved_retry_invalid_approval_never_stages(ready, monkeypatch, tmp_path, approval):
    store, args, _ = ready
    reservation = store.registry.reserve_candidate("store", "family", "save", **args)
    with monkeypatch.context() as guard:
        guard.setattr(store.area, "stage", lambda *a, **k: pytest.fail("Unauthorized stage"))
        guard.setattr(store.registry, "record_commit", lambda *a, **k: pytest.fail("Unauthorized commit"))
        with pytest.raises(ValueError, match="approval"):
            store.persist_candidate("family", "save", **{**args, "approval": approval})
    assert store.registry.get_reservation(reservation["reservation_id"]) == reservation
    assert store.registry.get_commit(reservation["reservation_id"]) is None
    assert list((tmp_path / "managed/staging").iterdir()) == []
    assert list((tmp_path / "managed/final").iterdir()) == []
    commit = store.persist_candidate("family", "save", **args)
    assert commit["reservation"] == reservation
    assert store.persist_candidate("family", "save", **args) == commit
    assert len(store.list_versions("family")) == 1


@pytest.mark.parametrize("attack", ["wrong-source", "wrong-scope", "descriptor-digest"])
def test_publication_preflight_checks_authoritative_source_and_descriptor(ready, monkeypatch, tmp_path, attack):
    from isaaclab_arena.agentic_environment_generation.workbench import research_graph_transport, research_store

    store, args, _ = ready
    original = research_store.project_scene

    def wrong_projection(spec, **scope):
        if attack == "wrong-source":
            spec = spec.model_copy(deep=True)
            spec.env_name = "different-source"
        else:
            scope["revision_id"] = "different-revision"
        return original(spec, **scope)

    if attack == "descriptor-digest":
        monkeypatch.setattr(research_store, "digest", lambda value: "0" * 64)
    else:
        monkeypatch.setattr(research_store, "project_scene", wrong_projection)
    monkeypatch.setattr(research_graph_transport, "publish_once", lambda *a, **k: pytest.fail("Graph write"))
    monkeypatch.setattr(store.area, "stage", lambda *a, **k: pytest.fail("Unvalidated artifact write"))
    with pytest.raises(ValueError):
        store.persist_candidate(
            "family", "save", **args, publication_request={"effect_id": "effect", "target_profile": "graph"}
        )
    assert store.list_versions("family")[0]["state"] == "reserved"
    assert list((tmp_path / "managed/staging").iterdir()) == []
    assert list((tmp_path / "managed/final").iterdir()) == []


@pytest.mark.parametrize("crash", [False, True])
def test_retry_adopts_final_without_second_stage(ready, monkeypatch, crash):
    store, args, receipt = ready
    original = store.registry.record_commit
    if crash:

        def fail(*args, **kwargs):
            raise RuntimeError("injected commit failure")

        monkeypatch.setattr(store.registry, "record_commit", fail)
        with pytest.raises(RuntimeError, match="injected"):
            store.persist_candidate("family", "save", **args)
        monkeypatch.setattr(store.registry, "record_commit", original)
    else:
        store.persist_candidate("family", "save", **args)

    def no_stage(*args, **kwargs):
        pytest.fail("Retry must not require a second artifact copy")

    monkeypatch.setattr(store.area, "stage", no_stage)
    commit = store.persist_candidate("family", "save", **args)
    assert (
        store.read_version(commit["reservation"]["reservation_id"])["candidate.json"]
        == canonical_json(receipt).encode()
    )
    assert store.persist_candidate("family", "save", **args) == commit
    assert store.registry.journal.db.execute("SELECT COUNT(*) FROM research_commits").fetchone()[0] == 1


@pytest.mark.parametrize("entry", ["generated_envs", "eval_output"])
def test_reject_legacy_roots_before_any_creation(tmp_path, entry):
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore

    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        legacy = tmp_path / entry
        legacy.mkdir()
        with pytest.raises(ValueError, match="legacy"):
            ResearchStore.create(journal, legacy / "managed", "store", protect_public=lambda value: None)
        assert list(legacy.iterdir()) == []


def test_open_creates_nothing_and_does_not_own_journal(tmp_path, ready):
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore

    store, args, _ = ready
    journal = store.registry.journal
    changes = journal.db.total_changes
    with pytest.raises(ValueError):
        ResearchStore.open(journal, tmp_path / "absent", "store", protect_public=lambda value: None)
    assert not (tmp_path / "absent").exists()
    with ResearchStore.open(journal, tmp_path / "managed", "store", protect_public=lambda value: None) as opened:
        assert opened.registry.registry_id == store.registry.registry_id
    assert journal.db.total_changes == changes
    assert journal.get_job(args["job_id"])


def test_writer_lock_is_nonblocking_across_independent_connections(tmp_path, ready):
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore, SafeBusy

    store, args, _ = ready
    with closing(Journal(tmp_path / "journal.sqlite3")) as other_journal:
        with ResearchStore.open(
            other_journal,
            tmp_path / "managed",
            "store",
            protect_public=lambda value: None,
        ) as other:
            with store.area.writer_lock():
                with pytest.raises(SafeBusy):
                    other.persist_candidate("family", "save", **args)
            first = store.persist_candidate("family", "save", **args)
            assert other.persist_candidate("family", "save", **args) == first
            assert other_journal.db.execute("SELECT COUNT(*) FROM research_commits").fetchone()[0] == 1


@pytest.mark.parametrize("hash_value", [None, "0" * 64])
def test_candidate_requires_hash_bound_receipt_before_reservation(tmp_path, hash_value):
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore

    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        journal.begin_run()
        args, _ = candidate(
            journal,
            receipt_change=lambda receipt: receipt["validation"].update(source_hash=hash_value),
        )
        with ResearchStore.create(journal, tmp_path / "managed", "store", protect_public=lambda value: None) as store:
            with pytest.raises(ValueError, match="hash"):
                store.persist_candidate("family", "save", **args)
            assert journal.db.execute("SELECT COUNT(*) FROM research_reservations").fetchone()[0] == 0
            assert list((tmp_path / "managed/staging").iterdir()) == []


def test_registry_queries_and_explicit_committed_parent(ready):
    store, args, _ = ready
    assert store.latest_version("family") is None
    first = store.persist_candidate("family", "save", **args)
    parent = first["reservation"]["revision_id"]
    second = store.persist_candidate("family", "child", **args, parent_revision_id=parent)
    assert store.latest_version("family") == 2
    rows = store.list_versions("family", limit=1, after_version=1)
    assert [row["reservation"] for row in rows] == [second["reservation"]]
    assert store.get_reservation(second["reservation"]["reservation_id"]) == second["reservation"]
    assert store.lineage("family", limit=1, after_version=1) == [{
        "revision_id": second["reservation"]["revision_id"],
        "parent_revision_id": parent,
        "reservation_id": second["reservation"]["reservation_id"],
        "version": 2,
    }]
    with pytest.raises(ValueError):
        store.list_versions("family", limit=101)
    with pytest.raises(ValueError):
        store.persist_candidate("family", "bad-parent", **args, parent_revision_id="not-committed")


@pytest.mark.parametrize("attack", ["tamper", "missing", "symlink"])
@pytest.mark.parametrize("committed", [False, True])
def test_corrupt_final_fails_closed_without_staging(ready, tmp_path, monkeypatch, attack, committed):
    store, args, _ = ready
    original = store.registry.record_commit
    if not committed:
        monkeypatch.setattr(
            store.registry,
            "record_commit",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("crash")),
        )
        with pytest.raises(RuntimeError):
            store.persist_candidate("family", "save", **args)
        monkeypatch.setattr(store.registry, "record_commit", original)
    else:
        store.persist_candidate("family", "save", **args)
    target = tmp_path / "managed/final/family/v1/candidate.json"
    if attack == "tamper":
        target.write_bytes(b"{}")
    else:
        target.unlink()
        if attack == "symlink":
            outside = tmp_path / "outside.json"
            outside.write_bytes(b"{}")
            target.symlink_to(outside)
    monkeypatch.setattr(store.area, "stage", lambda *a: pytest.fail("Corruption is not absence"))
    with pytest.raises(ValueError):
        store.persist_candidate("family", "save", **args)
    assert store.registry.journal.db.execute("SELECT COUNT(*) FROM research_commits").fetchone()[0] == int(committed)


@pytest.mark.parametrize("blocked", ["request", "receipt", "approval"])
def test_protect_guard_rejects_before_reservation_or_payload_bytes(ready, tmp_path, blocked):
    store, args, receipt = ready
    request = store.registry.journal.get_job(args["job_id"])["inputs"]

    def protect(value):
        if (
            (blocked == "request" and value == request)
            or (blocked == "receipt" and value == receipt)
            or (blocked == "approval" and isinstance(value, dict) and "approval" in value)
        ):
            raise ValueError("Public content rejected")

    store.protect_public = protect
    with pytest.raises(ValueError, match="Public content rejected"):
        store.persist_candidate("family", "save", **args)
    assert store.registry.journal.db.execute("SELECT COUNT(*) FROM research_reservations").fetchone()[0] == 0
    assert list((tmp_path / "managed/staging").iterdir()) == []
    assert list((tmp_path / "managed/final").iterdir()) == []


def test_pending_worker_cleanup_blocks_persistence(ready):
    store, args, _ = ready
    journal = store.registry.journal
    journal.record_worker(args["job_id"], 12345, {"pid": 12345, "start_time": "isolated-test"})
    with pytest.raises(ValueError):
        store.persist_candidate("family", "save", **args)
    assert journal.db.execute("SELECT COUNT(*) FROM research_reservations").fetchone()[0] == 0
    journal.worker_cleaned(args["job_id"])
    assert store.persist_candidate("family", "save", **args)


def test_cancelled_accepted_candidate_can_be_persisted(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore

    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        journal.begin_run()
        job = journal.submit("owner", "default", "generate", "cancel", {"operation": "new"})
        attempt = journal.claim_attempt(job["id"])
        assert journal.release_attempt(job["id"], **attempt)
        text = "env_name: accepted\n"
        receipt = {
            "yaml_text": text,
            "validation": {
                "valid": True,
                "source_hash": hashlib.sha256(text.encode()).hexdigest(),
            },
            "publication": "not_published",
        }
        assert journal.commit_candidate(job["id"], **attempt, receipt=receipt)
        assert journal.request_cancel_attempt(job["id"], **attempt, expected_state="candidate_committed")
        assert journal.cancel_attempt(job["id"], **attempt, expected_state="cancel_requested")
        with ResearchStore.create(journal, tmp_path / "managed", "store", protect_public=lambda value: None) as store:
            commit = store.persist_candidate(
                "family",
                "save",
                job["id"],
                **attempt,
                approval={"scope": "persist_candidate", "principal": "owner"},
            )
            assert (
                store.read_version(commit["reservation"]["reservation_id"])["candidate.json"]
                == canonical_json(receipt).encode()
            )
            assert journal.get_job(job["id"])["status"] == "cancelled"


def test_filesystem_io_occurs_outside_journal_transaction(ready, monkeypatch):
    store, args, _ = ready
    for method in ("stage", "promote", "verify"):
        original = getattr(store.area, method)

        def checked(*args, _original=original, **kwargs):
            assert not store.registry.journal.db.in_transaction
            return _original(*args, **kwargs)

        monkeypatch.setattr(store.area, method, checked)
    store.persist_candidate("family", "save", **args)


def test_symlink_root_rejected_without_outside_writes(tmp_path, ready):
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore

    store, _, _ = ready
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        ResearchStore.create(
            store.registry.journal,
            link / "managed",
            "other",
            protect_public=lambda value: None,
        )
    assert list(outside.iterdir()) == []


def test_simultaneous_independent_clients_have_one_commit_or_safe_busy(tmp_path, ready):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import ExitStack
    from threading import Barrier

    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore, SafeBusy

    store, args, _ = ready
    barrier = Barrier(2)

    def persist(client):
        barrier.wait(timeout=5)
        try:
            return client.persist_candidate("family", "save", **args)
        except SafeBusy:
            return None

    with ExitStack() as stack:
        journals = [stack.enter_context(closing(Journal(tmp_path / "journal.sqlite3"))) for _ in range(2)]
        clients = [
            stack.enter_context(
                ResearchStore.open(
                    journal,
                    tmp_path / "managed",
                    "store",
                    protect_public=lambda value: None,
                )
            )
            for journal in journals
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(persist, clients))
    commits = [result for result in results if result is not None]
    assert commits
    final = store.persist_candidate("family", "save", **args)
    assert all(commit == final for commit in commits)
    assert store.registry.journal.db.execute("SELECT COUNT(*) FROM research_commits").fetchone()[0] == 1
    assert list((tmp_path / "managed/staging").iterdir()) == []


def test_secret_in_exact_receipt_is_guarded_before_writes(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore

    secret = "isolated-test-secret-not-a-real-credential"

    def protect(value):
        if secret in json.dumps(value):
            raise ValueError("Public content rejected")

    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        journal.begin_run()
        args, _ = candidate(journal, receipt_change=lambda receipt: receipt.update(warnings=[secret]))
        with ResearchStore.create(journal, tmp_path / "managed", "store", protect_public=protect) as store:
            with pytest.raises(ValueError, match="Public content rejected"):
                store.persist_candidate("family", "save", **args)
            assert journal.db.execute("SELECT COUNT(*) FROM research_reservations").fetchone()[0] == 0
            assert list((tmp_path / "managed/staging").iterdir()) == []
            assert list((tmp_path / "managed/final").iterdir()) == []


def test_protection_cannot_mutate_the_accepted_receipt(ready, tmp_path):
    store, args, _ = ready

    def mutate(value):
        if isinstance(value, dict) and "yaml_text" in value:
            value["warnings"] = ["changed"]

    store.protect_public = mutate
    with pytest.raises(ValueError):
        store.persist_candidate("family", "save", **args)
    assert store.registry.journal.db.execute("SELECT COUNT(*) FROM research_reservations").fetchone()[0] == 0
    assert list((tmp_path / "managed/staging").iterdir()) == []
    assert list((tmp_path / "managed/final").iterdir()) == []


def test_persist_real_candidate_exact_bytes_and_receipt_unchanged(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore

    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        journal.begin_run()
        args, receipt = candidate(journal)
        protected = []
        store = ResearchStore.create(journal, tmp_path / "managed", "store", protect_public=protected.append)
        commit = store.persist_candidate("family", "save", **args)
        assert commit["publication_intent_id"] is None
        resid = commit["reservation"]["reservation_id"]
        files = store.read_version(resid)
        assert files == {
            "environment.yaml": receipt["yaml_text"].encode(),
            "candidate.json": canonical_json(receipt).encode(),
            "source.json": canonical_json(commit["reservation"]).encode(),
        }
        assert receipt in protected
        assert journal.get_job(args["job_id"])["inputs"] in protected
        assert journal.get_candidate_receipt(args["job_id"], args["attempt_id"], args["generation"]) == receipt
        store.close()
        store.close()
        assert journal.get_job(args["job_id"])["status"] == "succeeded"
