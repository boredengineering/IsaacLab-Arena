# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Managed research registry uses real isolated SQLite, never legacy output roots."""

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena.agentic_environment_generation.workbench.research_registry import (
    ResearchRegistry,
    canonical_json,
    digest,
)


def test_registry_requires_explicit_initialization_and_reuses_identity(tmp_path):
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        with pytest.raises(ValueError, match="not initialized"):
            ResearchRegistry(journal)
        registry = ResearchRegistry(journal, initialize=True)
        assert len(registry.registry_id) == 32
        assert ResearchRegistry(journal).registry_id == registry.registry_id
        registry.register_store("store-one")
        registry.register_store("store-one")
        assert registry.store_ids() == ["store-one"]


@pytest.mark.parametrize("store_id", ["../store", " store", "store/child", "", ".", "x" * 65, None, 12])
def test_store_identifiers_are_literal_bounded_identifiers(tmp_path, store_id):
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        registry = ResearchRegistry(journal, initialize=True)
        with pytest.raises(ValueError, match="identifier"):
            registry.register_store(store_id)
        assert registry.store_ids() == []


def test_store_registration_is_bounded_and_existing_store_remains_reopenable(tmp_path):
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        registry = ResearchRegistry(journal, initialize=True)
        for number in range(16):
            registry.register_store(f"store-{number}")
        registry.register_store("store-0")
        with pytest.raises(ValueError, match="capacity"):
            registry.register_store("extra-store")
        assert len(registry.store_ids()) == 16


def accepted_candidate(journal, key="candidate"):
    job = journal.submit(
        "synthetic-owner",
        "default",
        "generate",
        key,
        {"operation": "new", "prompt": "synthetic"},
    )
    attempt = journal.claim_attempt(job["id"])
    assert attempt is not None
    assert journal.release_attempt(job["id"], **attempt)
    receipt = {
        "yaml_text": "env_name: synthetic",
        "validation": {"valid": True},
        "publication": "not_published",
    }
    assert journal.commit_candidate(job["id"], **attempt, receipt=receipt)
    assert journal.complete_attempt(job["id"], **attempt, expected_state="candidate_committed")
    return job["id"], attempt


def test_reservation_binds_exact_candidate_and_retries_same_workflow(tmp_path):
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        journal.begin_run()
        registry = ResearchRegistry(journal, initialize=True)
        registry.register_store("store")
        job_id, attempt = accepted_candidate(journal)
        args = dict(
            job_id=job_id,
            **attempt,
            approval={"scope": "persist_candidate", "principal": "synthetic-owner"},
        )
        first = registry.reserve_candidate("store", "a2", "save-once", **args)
        assert first["version"] == 1
        assert first["source"]["attempt_id"] == attempt["attempt_id"]
        assert registry.reserve_candidate("store", "a2", "save-once", **args) == first
        assert registry.reserve_candidate("store", "a2", "save-again", **args)["version"] == 2
        with pytest.raises(ValueError, match="conflict"):
            registry.reserve_candidate("store", "other-family", "save-once", **args)


@pytest.mark.parametrize("same_workflow", [False, True])
def test_independent_connections_coordinate_reservations(tmp_path, same_workflow):
    path = tmp_path / "journal.sqlite3"
    with closing(Journal(path)) as journal:
        journal.begin_run()
        registry = ResearchRegistry(journal, initialize=True)
        registry.register_store("store")
        job_id, attempt = accepted_candidate(journal)

    def reserve(number):
        with closing(Journal(path)) as attached:
            # Attaching a persistence client must never begin/recover another API run.
            return ResearchRegistry(attached).reserve_candidate(
                "store",
                "a2",
                "same" if same_workflow else f"save-{number}",
                job_id=job_id,
                **attempt,
                approval={"scope": "persist_candidate", "principal": "synthetic-owner"},
            )

    with ThreadPoolExecutor(max_workers=6) as pool:
        reservations = list(pool.map(reserve, range(12)))
    if same_workflow:
        assert len({row["reservation_id"] for row in reservations}) == 1
        assert {row["version"] for row in reservations} == {1}
    else:
        assert sorted(row["version"] for row in reservations) == list(range(1, 13))


@pytest.fixture
def registry_candidate(tmp_path):
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        journal.begin_run()
        registry = ResearchRegistry(journal, initialize=True)
        registry.register_store("store")
        job_id, attempt = accepted_candidate(journal)
        args = dict(
            job_id=job_id,
            **attempt,
            approval={"scope": "persist_candidate", "principal": "owner"},
        )
        reservation = registry.reserve_candidate("store", "a2", "save", **args)
        yield registry, reservation, args


def manifest_for(registry, reservation):
    source = reservation["source"]
    receipt = registry.journal.get_candidate_receipt(source["job_id"], source["attempt_id"], source["generation"])
    files = {
        "environment.yaml": receipt["yaml_text"].encode(),
        "candidate.json": canonical_json(receipt).encode(),
    }
    manifest = {
        "schema": 1,
        "store_id": reservation["store_id"],
        "registry_id": reservation["registry_id"],
        "reservation_id": reservation["reservation_id"],
        "binding": reservation,
        "files": {
            name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()
        },
    }
    return {**manifest, "digest": digest(manifest)}


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize(
    "approval",
    [None, {"scope": "publish", "principal": "owner"}, {"scope": "persist_candidate", "principal": "other"}],
)
def test_reservation_retry_requires_original_approval(registry_candidate, committed, approval):
    registry, reservation, args = registry_candidate
    resid = reservation["reservation_id"]
    if committed:
        registry.record_commit(resid, manifest_for(registry, reservation), "final/a2/v1")
    before = registry.journal.db.total_changes
    commit = registry.get_commit(resid)
    with pytest.raises(ValueError, match="approval"):
        registry.reserve_candidate("store", "a2", "save", **{**args, "approval": approval})
    assert registry.journal.db.total_changes == before
    assert registry.get_reservation(resid) == reservation
    assert registry.get_commit(resid) == commit
    assert registry.reserve_candidate("store", "a2", "save", **args) == reservation
    assert len(registry.list_versions("store", "a2")) == 1
    assert registry.reserve_candidate("store", "a2", "next", **args)["version"] == 2


def test_commit_round_trip_exact_shape_and_matching_retry(registry_candidate):
    registry, reservation, _ = registry_candidate
    resid = reservation["reservation_id"]
    manifest = manifest_for(registry, reservation)
    assert registry.get_reservation(resid) == reservation
    assert registry.get_commit(resid) is None
    commit = registry.record_commit(resid, manifest, "final/a2/v1")
    assert commit == {
        "reservation": reservation,
        "manifest": manifest,
        "relative_directory": "final/a2/v1",
        "publication_intent_id": None,
    }
    assert registry.get_commit(resid) == commit
    assert registry.record_commit(resid, manifest, "final/a2/v1") == commit
    events = registry.journal.db.execute(
        "SELECT body FROM events WHERE body LIKE '%research_version_committed%'"
    ).fetchall()
    assert len(events) == 1


@pytest.mark.parametrize(
    "profile",
    [
        "https://graph.invalid",
        "../graph",
        "",
        None,
        {},
        {"database": 1},
        {"password": "synthetic"},
        {str(i): "id" for i in range(17)},
    ],
)
def test_publication_target_is_explicit_bounded_nonsecret_ids(registry_candidate, profile):
    registry, _, args = registry_candidate
    with pytest.raises(ValueError):
        registry.reserve_candidate(
            "store",
            "a2",
            "bad-profile",
            **args,
            publication_request={"effect_id": "publish", "target_profile": profile},
        )
    assert len(registry.list_versions("store", "a2")) == 1


def test_revision_id_is_unique_and_indexed_for_lookup(registry_candidate):
    registry, reservation, _ = registry_candidate
    db = registry.journal.db
    row = db.execute(
        "SELECT body FROM research_reservations WHERE json_extract(body,'$.revision_id')=?",
        (reservation["revision_id"],),
    ).fetchone()
    assert row[0] == canonical_json(reservation)
    assert "research_revision_id" in str([
        tuple(row)
        for row in db.execute(
            "EXPLAIN QUERY PLAN SELECT body FROM research_reservations WHERE json_extract(body,'$.revision_id')=?",
            (reservation["revision_id"],),
        )
    ])
    changed = {**reservation, "reservation_id": "other", "workflow_id": "other", "version": 2}
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT OR REPLACE INTO research_reservations VALUES (?,?,?,?,?,?,?)",
            ("other", "store", "a2", 2, "other", changed["request_digest"], canonical_json(changed)),
        )
    assert registry.get_reservation(reservation["reservation_id"]) == reservation


def test_versions_are_sorted_bounded_and_latest_ignores_reservations(registry_candidate):
    registry, first, args = registry_candidate
    second = registry.reserve_candidate("store", "a2", "second", **args)
    assert registry.latest_version("store", "a2") is None
    commit2 = registry.record_commit(second["reservation_id"], manifest_for(registry, second), "final/a2/v2")
    assert registry.latest_version("store", "a2") == 2
    commit1 = registry.record_commit(first["reservation_id"], manifest_for(registry, first), "final/a2/v1")
    third = registry.reserve_candidate("store", "a2", "third", **args)
    assert third["version"] == 3
    assert registry.latest_version("store", "a2") == 2
    expected = [
        {"reservation": first, "state": "committed", "commit": commit1},
        {"reservation": second, "state": "committed", "commit": commit2},
        {"reservation": third, "state": "reserved", "commit": None},
    ]
    assert registry.list_versions("store", "a2") == expected
    assert registry.list_versions("store", "a2", limit=1, after_version=1) == expected[1:2]
    assert registry.list_versions("store", "absent") == []
    for options in (
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"after_version": -1},
        {"after_version": True},
        {"after_version": 2**63},
    ):
        with pytest.raises(ValueError):
            registry.list_versions("store", "a2", **options)


def test_parent_is_explicit_committed_same_store_family_and_branches(
    registry_candidate,
):
    registry, first, args = registry_candidate
    with pytest.raises(ValueError, match="Parent"):
        registry.reserve_candidate(
            "store",
            "a2",
            "uncommitted-parent",
            **args,
            parent_revision_id=first["revision_id"],
        )
    registry.record_commit(first["reservation_id"], manifest_for(registry, first), "final/a2/v1")
    branch1 = registry.reserve_candidate("store", "a2", "branch1", **args, parent_revision_id=first["revision_id"])
    branch2 = registry.reserve_candidate("store", "a2", "branch2", **args, parent_revision_id=first["revision_id"])
    assert branch1["parent_revision_id"] == branch2["parent_revision_id"] == first["revision_id"]
    registry.register_store("other")
    for store, family, parent in [
        ("other", "a2", first["revision_id"]),
        ("store", "different", first["revision_id"]),
        ("store", "a2", "unknown"),
        ("store", "a2", "../bad"),
    ]:
        with pytest.raises(ValueError):
            registry.reserve_candidate(store, family, "bad-parent", **args, parent_revision_id=parent)
    assert registry.reserve_candidate("store", "a2", "no-parent", **args)["parent_revision_id"] is None


@pytest.mark.parametrize("change", ["future", "identity", "journal-future"])
def test_existing_instance_refuses_changed_schema_or_registry(registry_candidate, change):
    registry, reservation, args = registry_candidate
    if change == "future":
        registry.journal.db.execute("UPDATE research_registry_meta SET schema_version=999")
    elif change == "identity":
        registry.journal.db.execute("UPDATE research_registry_meta SET registry_id='different'")
    else:
        registry.journal.db.execute("PRAGMA user_version=999")
    for call in [
        lambda: registry.store_ids(),
        lambda: registry.get_reservation(reservation["reservation_id"]),
        lambda: registry.get_commit(reservation["reservation_id"]),
        lambda: registry.get_publication_intent("unknown"),
        lambda: registry.list_versions("store", "a2"),
        lambda: registry.latest_version("store", "a2"),
        lambda: registry.register_store("new"),
        lambda: registry.reserve_candidate("store", "a2", "new", **args),
        lambda: registry.record_commit(
            reservation["reservation_id"],
            manifest_for(registry, reservation),
            "final/a2/v1",
        ),
    ]:
        with pytest.raises((ValueError, RuntimeError)):
            call()


def test_commit_rejects_reservation_from_rebound_registry(registry_candidate):
    registry, reservation, _ = registry_candidate
    manifest = manifest_for(registry, reservation)
    registry.journal.db.execute("UPDATE research_registry_meta SET registry_id='different'")
    rebound = ResearchRegistry(registry.journal)
    with pytest.raises(ValueError, match="registry"):
        rebound.record_commit(reservation["reservation_id"], manifest, "final/a2/v1")
    assert registry.journal.db.execute("SELECT COUNT(*) FROM research_commits").fetchone()[0] == 0


def test_later_readers_only_select_never_initialize_or_recover(registry_candidate):
    registry, reservation, _ = registry_candidate
    statements = []
    registry.journal.db.set_trace_callback(statements.append)
    reader = ResearchRegistry(registry.journal)
    assert reader.get_reservation(reservation["reservation_id"]) == reservation
    assert reader.get_commit(reservation["reservation_id"]) is None
    reader.list_versions("store", "a2")
    reader.latest_version("store", "a2")
    reader.get_publication_intent("absent")
    assert all(sql.lstrip().upper().startswith(("SELECT", "PRAGMA")) for sql in statements)


@pytest.mark.parametrize("change", ["result", "inputs"])
def test_commit_uses_original_receipt_not_mutable_job_result(registry_candidate, change):
    registry, reservation, _ = registry_candidate
    manifest = manifest_for(registry, reservation)
    job = registry.journal.get_job(reservation["source"]["job_id"])
    job[change] = {
        "yaml_text": "env_name: not-the-receipt",
        "validation": {"valid": True},
    }
    registry.journal.db.execute("UPDATE jobs SET body=? WHERE id=?", (canonical_json(job), job["id"]))
    if change == "inputs":
        with pytest.raises(ValueError, match="source"):
            registry.record_commit(reservation["reservation_id"], manifest, "final/a2/v1")
    else:
        assert registry.record_commit(reservation["reservation_id"], manifest, "final/a2/v1")["manifest"] == manifest


def test_outbox_helper_requires_existing_transaction_and_commit(registry_candidate):
    registry, _, args = registry_candidate
    request = {"effect_id": "publish", "target_profile": "graph"}
    reservation = registry.reserve_candidate("store", "a2", "publish", **args, publication_request=request)
    intent = {**request, "payload": {}, "payload_sha256": digest({})}
    with pytest.raises(ValueError, match="transaction"):
        registry._insert_publication_intent(registry.journal.db, reservation, intent)
    with registry.journal._transaction() as db:
        with pytest.raises(ValueError, match="commit"):
            registry._insert_publication_intent(db, reservation, intent)
    assert registry.get_publication_intent("publish") is None


def test_real_artifact_area_commit_uses_original_bytes(registry_candidate, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea

    registry, reservation, _ = registry_candidate
    source = reservation["source"]
    receipt = registry.journal.get_candidate_receipt(source["job_id"], source["attempt_id"], source["generation"])
    files = {
        "environment.yaml": receipt["yaml_text"].encode(),
        "candidate.json": canonical_json(receipt).encode(),
    }
    with ArtifactArea.create(tmp_path / "artifacts", store_id="store", registry_id=registry.registry_id) as area:
        manifest = area.stage(reservation["reservation_id"], files, reservation)
        relative = area.promote(reservation["reservation_id"], "a2", "v1", manifest)
        assert area.verify(relative, manifest) == files
        assert registry.record_commit(reservation["reservation_id"], manifest, relative)["manifest"] == manifest


@pytest.mark.parametrize(
    "receipt",
    [
        None,
        {
            "yaml_text": "",
            "publication": "not_published",
            "validation": {"valid": True},
        },
        {
            "yaml_text": "env_name: changed",
            "publication": "not_published",
            "validation": {"valid": True},
        },
    ],
)
def test_missing_or_changed_journal_receipt_cannot_commit(registry_candidate, receipt):
    registry, reservation, _ = registry_candidate
    manifest = manifest_for(registry, reservation)
    db = registry.journal.db
    # Deliberate corruption only in this disposable journal exercises revalidation.
    db.execute("DROP TRIGGER modern_receipt_no_update")
    db.execute("DROP TRIGGER modern_receipt_no_delete")
    if receipt is None:
        db.execute("DELETE FROM modern_candidate_receipts")
    else:
        db.execute("UPDATE modern_candidate_receipts SET body=?", (canonical_json(receipt),))
    with pytest.raises(ValueError):
        registry.record_commit(reservation["reservation_id"], manifest, "final/a2/v1")
    assert registry.get_commit(reservation["reservation_id"]) is None


def test_reservation_rejects_binding_too_deep_for_artifacts(registry_candidate):
    registry, _, args = registry_candidate
    options = {}
    for _ in range(15):
        options = {"child": options}
    request = {"effect_id": "deep", "target_profile": "graph", "options": options}
    with pytest.raises(ValueError, match="bounds"):
        registry.reserve_candidate("store", "a2", "deep", **args, publication_request=request)
    assert registry.journal.db.execute("SELECT COUNT(*) FROM research_reservations").fetchone()[0] == 1


def test_deep_valid_reservation_binding_remains_artifact_compatible(registry_candidate, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea

    registry, _, args = registry_candidate
    options = {}
    for _ in range(14):
        options = {"child": options}
    request = {"effect_id": "deep", "target_profile": "graph", "options": options}
    reservation = registry.reserve_candidate("store", "a2", "deep", **args, publication_request=request)
    source = reservation["source"]
    receipt = registry.journal.get_candidate_receipt(source["job_id"], source["attempt_id"], source["generation"])
    files = {
        "environment.yaml": receipt["yaml_text"].encode(),
        "candidate.json": canonical_json(receipt).encode(),
    }
    with ArtifactArea.create(tmp_path / "deep-artifacts", store_id="store", registry_id=registry.registry_id) as area:
        manifest = area.stage(reservation["reservation_id"], files, reservation)
        relative = area.promote(reservation["reservation_id"], "a2", "v2", manifest)
        area.verify(relative, manifest)
        registry.record_commit(
            reservation["reservation_id"],
            manifest,
            relative,
            publication_intent={**request, "payload": {}, "payload_sha256": digest({})},
        )


def test_conflicting_valid_manifest_and_publication_payload_never_overwrite(
    registry_candidate,
):
    registry, first, args = registry_candidate
    manifest = manifest_for(registry, first)
    original = registry.record_commit(first["reservation_id"], manifest, "final/a2/v1")
    changed = {
        **manifest,
        "files": {**manifest["files"], "extra.json": {"size": 1, "sha256": "a" * 64}},
    }
    changed["digest"] = digest({k: v for k, v in changed.items() if k != "digest"})
    with pytest.raises(ValueError, match="conflict"):
        registry.record_commit(first["reservation_id"], changed, "final/a2/v1")
    assert registry.get_commit(first["reservation_id"]) == original
    request = {"effect_id": "effect", "target_profile": "graph"}
    second = registry.reserve_candidate("store", "a2", "second", **args, publication_request=request)
    intent = {**request, "payload": {}, "payload_sha256": digest({})}
    original = registry.record_commit(
        second["reservation_id"],
        manifest_for(registry, second),
        "final/a2/v2",
        publication_intent=intent,
    )
    with pytest.raises(ValueError, match="conflict"):
        registry.record_commit(
            second["reservation_id"],
            manifest_for(registry, second),
            "final/a2/v2",
            publication_intent={
                **intent,
                "payload": {"new": True},
                "payload_sha256": digest({"new": True}),
            },
        )
    assert registry.get_commit(second["reservation_id"]) == original
    third = registry.reserve_candidate("store", "a2", "third", **args, publication_request=request)
    with pytest.raises(ValueError, match="conflict"):
        registry.record_commit(
            third["reservation_id"],
            manifest_for(registry, third),
            "final/a2/v3",
            publication_intent=intent,
        )
    assert registry.get_commit(third["reservation_id"]) is None


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "apiKey",
        "private_key",
        "credential",
        "authorization",
        "access_key",
        "passphrase",
    ],
)
def test_publication_rejects_recursive_private_fields_before_write(registry_candidate, key):
    registry, _, args = registry_candidate
    request = {"effect_id": "publish", "target_profile": "graph"}
    before = registry.journal.db.execute("SELECT COUNT(*) FROM research_reservations").fetchone()[0]
    with pytest.raises(ValueError):
        registry.reserve_candidate(
            "store",
            "a2",
            "private-options",
            **args,
            publication_request={
                **request,
                "options": {"nested": [{key: "synthetic-private"}]},
            },
        )
    assert registry.journal.db.execute("SELECT COUNT(*) FROM research_reservations").fetchone()[0] == before
    reservation = registry.reserve_candidate("store", "a2", "publish", **args, publication_request=request)
    payload = {"nested": [{key: "synthetic-private"}]}
    with pytest.raises(ValueError):
        registry.record_commit(
            reservation["reservation_id"],
            manifest_for(registry, reservation),
            "final/a2/v2",
            publication_intent={
                **request,
                "payload": payload,
                "payload_sha256": digest(payload),
            },
        )
    assert registry.get_commit(reservation["reservation_id"]) is None


@pytest.mark.parametrize(
    "invalid",
    ["nan", "infinite", "depth", "nodes", "string", "key", "integer", "bytes", "size"],
)
def test_publication_payload_json_is_finite_bounded(registry_candidate, invalid):
    registry, _, args = registry_candidate
    request = {"effect_id": "publish", "target_profile": "graph"}
    reservation = registry.reserve_candidate("store", "a2", "publish", **args, publication_request=request)
    payload = {
        "data": {
            "nan": float("nan"),
            "infinite": float("inf"),
            "nodes": [None] * 4096,
            "string": "x" * 8193,
            "integer": 2**63,
            "bytes": b"bytes",
            "key": {"x" * 129: None},
            "size": ["x" * 8192] * 7,
        }.get(invalid)
    }
    if invalid == "depth":
        for _ in range(17):
            payload = {"nested": payload}
    payload_hash = "0" * 64 if invalid in {"nan", "infinite", "bytes"} else digest(payload)
    with pytest.raises(ValueError):
        registry.record_commit(
            reservation["reservation_id"],
            manifest_for(registry, reservation),
            "final/a2/v2",
            publication_intent={
                **request,
                "payload": payload,
                "payload_sha256": payload_hash,
            },
        )
    assert registry.get_publication_intent("publish") is None


@pytest.mark.parametrize(
    "table",
    ["research_commits", "research_publication_intents", "research_reservations"],
)
@pytest.mark.parametrize(
    "body",
    ["{}", "[]", "not-json", canonical_json({"large": "x" * 100000})],
    ids=["empty", "array", "invalid", "oversize"],
)
def test_sql_json_bounds_and_shapes_are_enforced(registry_candidate, table, body):
    registry, reservation, _ = registry_candidate
    with pytest.raises(sqlite3.IntegrityError):
        if table == "research_commits":
            registry.journal.db.execute(
                "INSERT INTO research_commits VALUES (?,?)",
                (reservation["reservation_id"], body),
            )
        elif table == "research_publication_intents":
            registry.journal.db.execute(
                "INSERT INTO research_publication_intents VALUES (?,?,?)",
                ("effect", reservation["reservation_id"], body),
            )
        else:
            registry.journal.db.execute(
                "INSERT INTO research_reservations VALUES (?,?,?,?,?,?,?)",
                ("new", "store", "a2", 2, "new", "0" * 64, body),
            )


@pytest.mark.parametrize(
    "corruption",
    [
        "digest",
        "binding",
        "registry",
        "store",
        "source",
        "yaml",
        "candidate",
        "missing",
        "path",
        "extra-field",
        "schema-bool",
        "size-bool",
        "negative-size",
        "large-file",
        "many-files",
        "total-bytes",
        "nested-name",
        "private-name",
        "nan",
        "deep",
        "long-string",
    ],
)
def test_commit_rejects_noncanonical_or_unbound_manifest(registry_candidate, corruption):
    registry, reservation, _ = registry_candidate
    manifest = manifest_for(registry, reservation)
    path = "final/a2/v1"
    if corruption == "digest":
        manifest["digest"] = "0" * 64
    elif corruption == "binding":
        manifest["binding"] = {**reservation, "workflow_id": "other"}
    elif corruption in {"registry", "store"}:
        manifest[f"{corruption}_id"] = "other"
    elif corruption == "source":
        manifest["binding"] = {
            **reservation,
            "source": {**reservation["source"], "receipt_sha256": "0" * 64},
        }
    elif corruption in {"yaml", "candidate"}:
        manifest["files"]["environment.yaml" if corruption == "yaml" else "candidate.json"]["sha256"] = "0" * 64
    elif corruption == "missing":
        del manifest["files"]["candidate.json"]
    elif corruption == "path":
        path = "final/a2/../a2/v1"
    elif corruption == "extra-field":
        manifest["extra"] = "ignored?"
    elif corruption == "schema-bool":
        manifest["schema"] = True
    elif corruption in {"size-bool", "negative-size", "large-file"}:
        manifest["files"]["extra.json"] = {
            "size": {"size-bool": True, "negative-size": -1, "large-file": 2097153}[corruption],
            "sha256": "a" * 64,
        }
    elif corruption in {"many-files", "total-bytes"}:
        for i in range(17 if corruption == "many-files" else 5):
            manifest["files"][f"extra{i}.json"] = {"size": 2097152, "sha256": "a" * 64}
    elif corruption in {"nested-name", "private-name"}:
        manifest["files"]["nested/file.json" if corruption == "nested-name" else "credentials.json"] = {
            "size": 1,
            "sha256": "a" * 64,
        }
    else:
        item = float("nan") if corruption == "nan" else "x" * 8193
        if corruption == "deep":
            item = {}
            for _ in range(20):
                item = {"child": item}
        manifest["binding"] = {**reservation, "extra": item}
    if corruption not in {"digest", "nan"}:
        manifest["digest"] = digest({k: v for k, v in manifest.items() if k != "digest"})
    with pytest.raises(ValueError):
        registry.record_commit(reservation["reservation_id"], manifest, path)
    assert registry.get_commit(reservation["reservation_id"]) is None


def test_publication_intent_is_frozen_pending_atomic_and_retryable(registry_candidate):
    registry, _, args = registry_candidate
    payload = {"revision": "public-revision", "options": {"mode": "create"}}
    request = {
        "effect_id": "publish-once",
        "target_profile": {"profile_id": "graph", "database": "research"},
        "options": {"mode": "create"},
    }
    reservation = registry.reserve_candidate("store", "a2", "publish-save", **args, publication_request=request)
    assert reservation["publication_request"] == request
    intent = {**request, "payload": payload, "payload_sha256": digest(payload)}
    assert registry.get_publication_intent("publish-once") is None
    manifest = manifest_for(registry, reservation)
    commit = registry.record_commit(
        reservation["reservation_id"],
        manifest,
        "final/a2/v2",
        publication_intent=intent,
    )
    assert commit["publication_intent_id"] == "publish-once"
    assert registry.get_publication_intent("publish-once") == {
        **intent,
        "schema_version": 1,
        "registry_id": registry.registry_id,
        "reservation_id": reservation["reservation_id"],
        "state": "pending",
    }
    assert (
        registry.record_commit(
            reservation["reservation_id"],
            manifest,
            "final/a2/v2",
            publication_intent=intent,
        )
        == commit
    )
    with pytest.raises(ValueError, match="conflict"):
        registry.reserve_candidate(
            "store",
            "a2",
            "publish-save",
            **args,
            publication_request={**request, "target_profile": "other"},
        )
    with pytest.raises(ValueError, match="conflict"):
        registry.record_commit(
            reservation["reservation_id"],
            manifest,
            "final/a2/v2",
            publication_intent={**intent, "options": {"mode": "replace"}},
        )


@pytest.mark.parametrize(
    "table",
    [
        "research_commits",
        "research_publication_intents",
        "research_reservations",
        "research_stores",
    ],
)
@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "REPLACE"])
def test_sql_research_records_are_immutable(registry_candidate, table, action):
    registry, _, args = registry_candidate
    request = {"effect_id": "publish", "target_profile": "graph"}
    reservation = registry.reserve_candidate("store", "a2", "publish", **args, publication_request=request)
    intent = {**request, "payload": {}, "payload_sha256": digest({})}
    registry.record_commit(
        reservation["reservation_id"],
        manifest_for(registry, reservation),
        "final/a2/v2",
        publication_intent=intent,
    )
    column = "store_id" if table == "research_stores" else "body"
    sql = f"UPDATE {table} SET {column}={column}" if action == "UPDATE" else f"DELETE FROM {table}"
    if action == "REPLACE":
        sql = f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}"
    with pytest.raises(sqlite3.IntegrityError, match="Immutable"):
        registry.journal.db.execute(sql)


@pytest.mark.parametrize("table", ["research_commits", "events", "research_publication_intents"])
def test_failed_insert_rolls_back_commit_and_outbox(registry_candidate, table):
    registry, _, args = registry_candidate
    request = {"effect_id": "publish", "target_profile": "graph"}
    reservation = registry.reserve_candidate("store", "a2", "publish", **args, publication_request=request)
    intent = {**request, "payload": {}, "payload_sha256": digest({})}
    before = registry.journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    registry.journal.db.execute(
        f"CREATE TRIGGER fail_insert BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'forced'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="forced"):
        registry.record_commit(
            reservation["reservation_id"],
            manifest_for(registry, reservation),
            "final/a2/v2",
            publication_intent=intent,
        )
    assert registry.get_commit(reservation["reservation_id"]) is None
    assert registry.get_publication_intent("publish") is None
    assert registry.journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before
    registry.journal.db.execute("DROP TRIGGER fail_insert")
    assert (
        registry.record_commit(
            reservation["reservation_id"],
            manifest_for(registry, reservation),
            "final/a2/v2",
            publication_intent=intent,
        )["publication_intent_id"]
        == "publish"
    )
