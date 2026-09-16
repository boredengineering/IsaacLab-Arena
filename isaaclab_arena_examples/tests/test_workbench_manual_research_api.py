# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""X05 isolated HTTP/core contracts; no workers, graph or renderer execution."""
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
from isaaclab_arena.agentic_environment_generation.workbench.research_source import editor_revision_source
from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, editor_execution

ORIGIN = "http://127.0.0.1:3000"
FIXTURE = Path(__file__).resolve().parents[2] / "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"
URL = "/api/research/stores/primary/versions"


@pytest.fixture
def api(tmp_path, monkeypatch):
    def unavailable(_):
        raise RuntimeError("No snapshot runtime in isolated X05 checks")
    monkeypatch.setattr(editor_execution, "make_snapshot_service", unavailable)
    app = create_app(tmp_path / "state", start_paused=True, research_roots={"primary": tmp_path / "managed"})
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        with ResearchStore.create(app.state.journal, tmp_path / "managed", "primary", protect_public=app.state.model_settings.protect_public):
            pass
        yield app, client, headers
        jobs = client.get("/api/jobs")
        expected = getattr(app.state, "x05_fixture_jobs", [])
        if getattr(app.state, "x05_jobs_denied", False):
            assert jobs.status_code == 422
            assert jobs.json() == {"detail": "Invalid request input"}
            assert app.state.journal.snapshot()["jobs"] == expected
        else:
            assert jobs.status_code == 200
            assert jobs.json()["jobs"] == expected
        assert not app.state.publication_authorization._records


def manual_payload(client, headers, text=None):
    saved = client.post("/api/editor/save", headers=headers, json={
        "yaml_text": text or FIXTURE.read_text(), "idempotency_key": "editor:x05"})
    assert saved.status_code == 200, saved.text
    revision = saved.json()["revision"]
    return {"idempotency_key": "manual-x05", "family": "family", "parent_revision_id": None,
            "source": {"kind": "editor_revision", "editor_revision_id": revision["revision_id"],
                       "source_hash": revision["source_hash"], "canonical_hash": revision["canonical_hash"]}}


def test_exact_research_open_retains_includes_and_issued_view_semantics(api, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    app, client, headers = api
    repo = tmp_path / "repo"
    folder = repo / "generated_envs"
    folder.mkdir(parents=True)
    (folder / "root.yaml").write_text("external_yaml: included.yaml\n")
    (folder / "included.yaml").write_text(FIXTURE.read_text())
    app.state.documents = Documents(tmp_path / "state", root=repo)
    source_id = next(row["id"] for row in app.state.documents.index() if row["name"] == "root")
    loaded = client.get("/api/editor/documents/" + source_id).json()
    saved = client.post("/api/editor/save", headers=headers, json={
        "yaml_text": loaded["yaml_text"], "document_id": loaded["document_id"],
        "expected_source_hash": loaded["source_hash"], "idempotency_key": "editor:included"}).json()["revision"]
    payload = {"family": "family", "idempotency_key": "included", "parent_revision_id": None,
               "source": {"kind": "editor_revision", **{key: saved[key] for key in ("source_hash", "canonical_hash")},
                          "editor_revision_id": saved["revision_id"]}}
    commit = client.post(URL, headers=headers, json=payload).json()
    descriptor = "research-version:primary:" + commit["reservation"]["reservation_id"] + ":" + commit["manifest"]["digest"]
    shutil.rmtree(repo)
    shutil.rmtree(tmp_path / "state/editor-revision-bundles")
    app.state.documents = Documents(tmp_path / "state", root=repo)
    opened = client.get("/api/editor/documents/" + descriptor)
    assert opened.status_code == 200, opened.text
    opened = opened.json()
    assert opened["source_origin"] == {"kind": "research_version", "id": descriptor}
    assert opened["research_identity"] == {"store_id": "primary", "reservation_id": commit["reservation"]["reservation_id"],
        "revision_id": commit["reservation"]["revision_id"], "family": "family", "version": 1,
        "manifest_digest": commit["manifest"]["digest"], "source": commit["reservation"]["source"]}
    assert opened["yaml_text"] == "external_yaml: included.yaml\n"
    assert opened["validation"]["canonical_hash"] == saved["canonical_hash"]
    assert opened["document_id"] not in app.state.documents.paths
    again = client.get("/api/editor/documents/" + descriptor).json()
    assert again["document_id"] != opened["document_id"]
    assert client.get("/api/editor/documents/" + opened["document_id"]).json() == opened
    draft = {"document_id": opened["document_id"], "yaml_text": opened["yaml_text"]}
    assert client.post("/api/editor/validate", headers=headers, json=draft).json()["valid"]
    assert client.post("/api/editor/snapshots", headers=headers, json={**draft, "idempotency_key": "snapshot:x05"}).status_code == 503
    for extra in ({}, {"operation": "refine", "base_yaml": opened["yaml_text"]}):
        response = client.post("/api/editor/generate", headers=headers, json={
            "document_id": opened["document_id"], "prompt": "No execution", "idempotency_key": "refine:x05", **extra})
        assert response.status_code == 503, response.text
    child = client.post("/api/editor/save", headers=headers, json={**draft, "expected_source_hash": opened["source_hash"],
        "idempotency_key": "editor:child"})
    assert child.status_code == 200, child.text
    assert app.state.documents.load_revision_bundle(child.json()["revision"]["revision_id"])["snapshot"]["includes"] == {"included.yaml": FIXTURE.read_text()}
    rows = client.get(URL + "?family=family")
    assert rows.status_code == 200, rows.text
    row = rows.json()["versions"][0]
    assert row["source"] == commit["reservation"]["source"]
    assert "source_job_id" not in row
    assert row["open_source"] == opened["source_origin"]


def test_manual_save_derives_full_proof_and_replays_without_original(api, tmp_path):
    app, client, headers = api
    payload = manual_payload(client, headers)
    bundle = app.state.documents.load_revision_bundle(payload["source"]["editor_revision_id"])
    result = client.post(URL, headers=headers, json=payload)
    assert result.status_code == 201, result.text
    commit = result.json()
    assert set(commit) == {"reservation", "manifest", "relative_directory", "publication_intent_id"}
    assert commit["reservation"]["source"] == editor_revision_source(bundle)
    assert commit["reservation"]["approval"] == {"scope": "persist_editor_revision", "principal": "single_operator_workspace"}
    assert commit["publication_intent_id"] is None
    shutil.rmtree(tmp_path / "state/editor-revision-bundles")
    replay = client.post(URL, headers=headers, json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json() == commit
    for field, value in (("family", "other"), ("parent_revision_id", "a" * 32)):
        assert client.post(URL, headers=headers, json={**payload, field: value}).status_code == 409
    for field in ("editor_revision_id", "source_hash", "canonical_hash"):
        changed = {**payload, "source": {**payload["source"], field: "0" * len(payload["source"][field])}}
        assert client.post(URL, headers=headers, json=changed).status_code == 409


@pytest.mark.parametrize("unavailable_include", [False, True])
def test_tagged_candidate_is_exact_legacy_adapter(api, unavailable_include):
    import hashlib
    app, client, headers = api
    journal = app.state.journal
    job = journal.submit("fixture", "default", "generate", "synthetic-candidate", {"prompt": "inert fixture"})
    attempt = journal.claim_attempt(job["id"])
    assert journal.release_attempt(job["id"], **attempt)
    text = "external_yaml: missing.yaml\n" if unavailable_include else FIXTURE.read_text()
    receipt = {"yaml_text": text, "validation": {"valid": True, "source_hash": hashlib.sha256(text.encode()).hexdigest()}, "publication": "not_published"}
    assert journal.commit_candidate(job["id"], **attempt, receipt=receipt)
    assert journal.complete_attempt(job["id"], **attempt, expected_state="candidate_committed")
    app.state.x05_fixture_jobs = client.get("/api/jobs").json()["jobs"]
    flat = {"idempotency_key": "legacy", "family": "family", "source_job_id": job["id"],
            "source_attempt_id": attempt["attempt_id"], "source_generation": attempt["generation"]}
    original = client.post(URL, headers=headers, json=flat)
    assert original.status_code == 201, original.text
    tagged = {"idempotency_key": "legacy", "family": "family", "source": {"kind": "accepted_candidate", "job_id": job["id"], **attempt}}
    replay = client.post(URL, headers=headers, json=tagged)
    assert replay.status_code == 201, replay.text
    assert replay.content == original.content
    assert "kind" not in replay.json()["reservation"]["source"]
    commit = replay.json()
    descriptor = "research-version:primary:" + commit["reservation"]["reservation_id"] + ":" + commit["manifest"]["digest"]
    opened = client.get("/api/editor/documents/" + descriptor)
    assert opened.status_code == (409 if unavailable_include else 200), opened.text
    if not unavailable_include:
        assert opened.json()["yaml_text"] == text
        assert opened.json()["validation"]["valid"]
        assert opened.json()["research_identity"]["source"] == commit["reservation"]["source"]
        assert opened.json()["document_id"] not in app.state.documents.paths
        assert client.get("/api/editor/documents/" + opened.json()["document_id"]).json() == opened.json()
    assert client.get("/api/jobs").json()["jobs"] == app.state.x05_fixture_jobs


@pytest.mark.parametrize("mutation", ["parent", "extra", "mixed", "source_extra", "boolean", "unknown", "hash", "family"])
def test_source_union_rejects_invalid_or_mixed_fields_before_writes(api, mutation):
    app, client, headers = api
    body = manual_payload(client, headers)
    if mutation == "parent":
        del body["parent_revision_id"]
    elif mutation == "extra":
        body["approval"] = {}
    elif mutation == "mixed":
        body["source_job_id"] = "a" * 32
    elif mutation == "source_extra":
        body["source"]["bundle_sha256"] = "a" * 64
    elif mutation == "boolean":
        body["source"] = {"kind": "accepted_candidate", "job_id": "a" * 32, "attempt_id": "a" * 32, "generation": True}
    elif mutation == "unknown":
        body["source"]["kind"] = "other"
    elif mutation == "hash":
        body["source"]["source_hash"] += "\n"
    else:
        body["family"] = "x" * 65
    before = list(app.state.journal.db.iterdump())
    assert client.post(URL, headers=headers, json=body).status_code == 422
    assert list(app.state.journal.db.iterdump()) == before


@pytest.mark.parametrize("endpoint", ["list", "detail", "artifact", "open", "issued", "validate", "snapshot", "refine", "child", "replay"])
def test_current_secret_policy_checks_unused_decoded_research_includes(api, tmp_path, endpoint):
    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    app, client, headers = api
    marker = "x05-unused-secret-marker-123456"
    folder = tmp_path / "repo/generated_envs"
    folder.mkdir(parents=True)
    (folder / "root.yaml").write_text("external_yaml: included.yaml\n")
    encoded = '"' + ''.join(f"\\x{ord(char):02x}" for char in marker) + '"'
    (folder / "included.yaml").write_text(FIXTURE.read_text().replace("pick_and_place_maple_table_default", encoded))
    app.state.documents = Documents(tmp_path / "state", root=tmp_path / "repo")
    source_id = next(row["id"] for row in app.state.documents.index() if row["name"] == "root")
    view = app.state.documents.load(source_id)
    receipt = app.state.documents.save(FIXTURE.read_text(), view["document_id"], view["source_hash"], idempotency_key="editor:unused")
    revision = receipt["revision"]
    payload = {"family": "family", "idempotency_key": "secret-save", "parent_revision_id": None,
        "source": {"kind": "editor_revision", "editor_revision_id": revision["revision_id"],
                   **{key: revision[key] for key in ("source_hash", "canonical_hash")}}}
    saved = client.post(URL, headers=headers, json=payload)
    assert saved.status_code == 201, saved.text
    commit = saved.json()
    detail = URL + "/" + commit["reservation"]["reservation_id"]
    descriptor = "research-version:primary:" + commit["reservation"]["reservation_id"] + ":" + commit["manifest"]["digest"]
    opened = client.get("/api/editor/documents/" + descriptor).json()
    assert client.put("/api/model-settings", headers=headers, json={"provider": "openai", "model": "inert", "api_key": marker}).status_code == 200
    before = {p.relative_to(tmp_path / "managed"): p.read_bytes() for p in (tmp_path / "managed").rglob("*") if p.is_file()}
    if endpoint in {"list", "detail", "artifact", "open", "issued"}:
        response = client.get({"list": URL + "?family=family", "detail": detail,
            "artifact": detail + "/artifacts/environment.yaml", "open": "/api/editor/documents/" + descriptor,
            "issued": "/api/editor/documents/" + opened["document_id"]}[endpoint])
    elif endpoint == "replay":
        response = client.post(URL, headers=headers, json=payload)
    else:
        draft = {"document_id": opened["document_id"], "yaml_text": opened["yaml_text"]}
        path = {"validate": "validate", "snapshot": "snapshots", "refine": "generate", "child": "save"}[endpoint]
        if endpoint == "refine":
            draft = {"document_id": opened["document_id"], "operation": "refine", "base_yaml": opened["yaml_text"], "prompt": "No execution"}
        if endpoint != "validate":
            draft["idempotency_key"] = "secret:child"
        response = client.post("/api/editor/" + path, headers=headers, json=draft)
    assert response.status_code == 422, response.text
    assert response.json() == {"detail": "Invalid request input"}
    assert {p.relative_to(tmp_path / "managed"): p.read_bytes() for p in (tmp_path / "managed").rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("origin", ["research_version", "editor_revision"])
@pytest.mark.parametrize("location", ["removed_root", "unused_include"])
@pytest.mark.parametrize("endpoint", ["keyed_child", "legacy_child", "validate", "refine", "snapshot"])
def test_fresh_immutable_draft_checks_complete_original_policy(api, tmp_path, origin, location, endpoint):
    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    app, client, headers = api
    marker = "dummy-immutable-origin-marker-123456"
    encoded = '"' + ''.join(f"\\x{ord(char):02x}" for char in marker) + '"'
    sensitive = FIXTURE.read_text().replace("pick_and_place_maple_table_default", encoded)
    folder = tmp_path / "repo/generated_envs"
    folder.mkdir(parents=True)
    (folder / "root.yaml").write_text(sensitive if location == "removed_root" else "external_yaml: included.yaml\n")
    if location == "unused_include":
        (folder / "included.yaml").write_text(sensitive)
    app.state.documents = Documents(tmp_path / "state", root=tmp_path / "repo")
    source_id = next(row["id"] for row in app.state.documents.index() if row["name"] == "root")
    view = client.get("/api/editor/documents/" + source_id).json()
    saved = client.post("/api/editor/save", headers=headers, json={
        "yaml_text": sensitive if location == "removed_root" else FIXTURE.read_text(),
        "document_id": view["document_id"], "expected_source_hash": view["source_hash"],
        "idempotency_key": "editor:original"})
    assert saved.status_code == 200, saved.text
    revision = saved.json()["revision"]
    descriptor = revision["open_source"]["id"]
    if origin == "research_version":
        result = client.post(URL, headers=headers, json={"family": "family", "idempotency_key": "origin",
            "parent_revision_id": None, "source": {"kind": "editor_revision", "editor_revision_id": revision["revision_id"],
                **{key: revision[key] for key in ("source_hash", "canonical_hash")}}})
        assert result.status_code == 201, result.text
        commit = result.json()
        descriptor = "research-version:primary:" + commit["reservation"]["reservation_id"] + ":" + commit["manifest"]["digest"]
    opened_response = client.get("/api/editor/documents/" + descriptor)
    assert opened_response.status_code == 200, opened_response.text
    opened = opened_response.json()
    assert client.put("/api/model-settings", headers=headers, json={
        "provider": "openai", "model": "inert", "api_key": marker}).status_code == 200

    def artifacts():
        roots = [tmp_path / "managed", tmp_path / "state/editor-revision-bundles", tmp_path / "state/editor-revisions"]
        return {p.relative_to(tmp_path): p.read_bytes() for root in roots for p in root.rglob("*") if p.is_file()}
    before, database = artifacts(), list(app.state.journal.db.iterdump())
    draft = {"yaml_text": FIXTURE.read_text(), "document_id": opened["document_id"]}
    path = {"keyed_child": "save", "legacy_child": "save", "validate": "validate", "refine": "generate", "snapshot": "snapshots"}[endpoint]
    if endpoint in {"keyed_child", "legacy_child"}:
        draft["expected_source_hash"] = opened["source_hash"]
    if endpoint == "refine":
        draft = {"operation": "refine", "prompt": "No model execution", "document_id": opened["document_id"], "base_yaml": FIXTURE.read_text()}
    if endpoint in {"keyed_child", "refine", "snapshot"}:
        draft["idempotency_key"] = "fresh:origin-policy"
    response = client.post("/api/editor/" + path, headers=headers, json=draft)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request input"}
    assert artifacts() == before
    assert list(app.state.journal.db.iterdump()) == database
    assert not app.state.workflow_authorization.grants._records


@pytest.mark.parametrize("fault", ["busy", "uncertain", "corrupt"])
def test_manual_source_storage_fault_has_static_non_success_before_reservation(api, tmp_path, monkeypatch, fault):
    import os
    from isaaclab_arena.agentic_environment_generation.workbench import editor_revision_storage as storage
    app, client, headers = api
    payload = manual_payload(client, headers)
    manifest = tmp_path / "state/editor-revision-bundles" / payload["source"]["editor_revision_id"] / "manifest.json"
    before = list(app.state.journal.db.iterdump())
    if fault == "busy":
        monkeypatch.setattr(storage, "LOCK_SECONDS", 0.02)
        with app.state.documents.revisions.area(lock=True):
            response = client.post(URL, headers=headers, json=payload)
    elif fault == "uncertain":
        sync = os.fsync
        def fail(fd):
            if os.readlink(f"/proc/self/fd/{fd}").endswith("/manifest.json"):
                raise OSError("private-x05-fsync-marker")
            return sync(fd)
        monkeypatch.setattr(os, "fsync", fail)
        response = client.post(URL, headers=headers, json=payload)
    else:
        manifest.write_bytes(b'{"private-corruption":')
        response = client.post(URL, headers=headers, json=payload)
    assert response.status_code == (409 if fault == "corrupt" else 503), response.text
    assert "private-" not in response.text
    assert response.headers.get("Retry-After") == ("1" if fault == "busy" else None)
    assert list(app.state.journal.db.iterdump()) == before


def test_authenticated_capabilities_are_configuration_not_publication_authority(api):
    app, client, headers = api
    caps = client.get("/api/editor").json()["capabilities"]
    assert caps.get("manual_research_save") is True
    assert caps.get("research_version_open") is True
    assert caps["publication_execution"] is False
    assert "manual_research_save" not in client.get("/api/health").json()["capabilities"]
    app.state.research_roots = {}
    caps = client.get("/api/editor").json()["capabilities"]
    assert caps["manual_research_save"] is False
    assert caps["research_version_open"] is False


@pytest.mark.parametrize("endpoint", ["list", "detail", "artifact", "open"])
def test_candidate_reads_protect_the_actual_root(api, endpoint):
    import hashlib
    app, client, headers = api
    marker = "candidate-current-secret-marker-123456"
    text = FIXTURE.read_text().replace("pick_and_place_maple_table_default", marker)
    journal = app.state.journal
    job = journal.submit("fixture", "default", "generate", "secret-candidate", {"prompt": "inert fixture"})
    attempt = journal.claim_attempt(job["id"])
    assert journal.release_attempt(job["id"], **attempt)
    receipt = {"yaml_text": text, "validation": {"valid": True, "source_hash": hashlib.sha256(text.encode()).hexdigest()}, "publication": "not_published"}
    assert journal.commit_candidate(job["id"], **attempt, receipt=receipt)
    assert journal.complete_attempt(job["id"], **attempt, expected_state="candidate_committed")
    app.state.x05_fixture_jobs = client.get("/api/jobs").json()["jobs"]
    payload = {"idempotency_key": "candidate-secret", "family": "family", "source": {"kind": "accepted_candidate", "job_id": job["id"], **attempt}}
    result = client.post(URL, headers=headers, json=payload)
    assert result.status_code == 201, result.text
    commit = result.json()
    detail = URL + "/" + commit["reservation"]["reservation_id"]
    descriptor = "research-version:primary:" + commit["reservation"]["reservation_id"] + ":" + commit["manifest"]["digest"]
    assert client.put("/api/model-settings", headers=headers, json={"provider": "openai", "model": "inert", "api_key": marker}).status_code == 200
    app.state.x05_jobs_denied = True
    response = client.get({"list": URL + "?family=family", "detail": detail, "artifact": detail + "/artifacts/source.json",
                           "open": "/api/editor/documents/" + descriptor}[endpoint])
    assert response.status_code == 422, response.text
    assert response.json() == {"detail": "Invalid request input"}


def test_core_research_factory_binds_every_source_proof_before_issuing_view(api):
    app, client, headers = api
    payload = manual_payload(client, headers)
    bundle = app.state.documents.load_revision_bundle(payload["source"]["editor_revision_id"])
    commit = client.post(URL, headers=headers, json=payload).json()
    identity = {key: commit["reservation"][key] for key in ("store_id", "reservation_id", "revision_id", "family", "version", "source")}
    identity["manifest_digest"] = commit["manifest"]["digest"]
    origin = {"kind": "research_version", "id": "research-version:primary:" + identity["reservation_id"] + ":" + identity["manifest_digest"]}
    identity["source"]["bundle_sha256"] = "0" * 64
    before = dict(app.state.documents.views)
    with pytest.raises(ValueError):
        app.state.documents.issue_research_view(bundle, origin, identity)
    assert app.state.documents.views == before


def test_research_reads_require_live_session_and_saves_require_csrf(api, monkeypatch):
    app, client, headers = api
    payload = manual_payload(client, headers)
    assert client.post(URL, headers={"Origin": ORIGIN}, json=payload).status_code == 403
    saved = client.post(URL, headers=headers, json=payload)
    assert saved.status_code == 201
    commit = saved.json()
    detail = URL + "/" + commit["reservation"]["reservation_id"]
    descriptor = "research-version:primary:" + commit["reservation"]["reservation_id"] + ":" + commit["manifest"]["digest"]
    expiry = client.get("/api/session").json()["expires_at"]
    with monkeypatch.context() as patcher:
        patcher.setattr(app.state.sessions, "clock", lambda: expiry)
        for path in (URL + "?family=family", detail, detail + "/artifacts/environment.yaml", "/api/editor/documents/" + descriptor, "/api/editor"):
            response = client.get(path)
            assert response.status_code == 401, response.text
        assert client.post(URL, headers=headers, json=payload).status_code == 401


@pytest.mark.parametrize("origin", ["research_version", "editor_revision"])
def test_clean_committed_child_replay_precedes_retired_original_and_source_cas(api, tmp_path, origin):
    app, client, headers = api
    marker = "dummy-retired-origin-marker-123456"
    encoded = '"' + ''.join(f"\\x{ord(char):02x}" for char in marker) + '"'
    payload = manual_payload(client, headers, FIXTURE.read_text().replace("pick_and_place_maple_table_default", encoded))
    descriptor = "editor-revision:" + payload["source"]["editor_revision_id"]
    if origin == "research_version":
        result = client.post(URL, headers=headers, json=payload)
        assert result.status_code == 201, result.text
        commit = result.json()
        descriptor = "research-version:primary:" + commit["reservation"]["reservation_id"] + ":" + commit["manifest"]["digest"]
    opened = client.get("/api/editor/documents/" + descriptor).json()
    child = {"yaml_text": FIXTURE.read_text(), "document_id": opened["document_id"],
             "expected_source_hash": opened["source_hash"], "idempotency_key": "child:clean-replay"}
    before = list(app.state.journal.db.iterdump())
    wrong = client.post("/api/editor/save", headers=headers, json={**child, "expected_source_hash": "0" * 64})
    assert wrong.status_code == 409, wrong.text
    assert list(app.state.journal.db.iterdump()) == before
    saved = client.post("/api/editor/save", headers=headers, json=child)
    assert saved.status_code == 200, saved.text
    assert client.put("/api/model-settings", headers=headers, json={
        "provider": "openai", "model": "inert", "api_key": marker}).status_code == 200
    # Even a still-issued now-sensitive origin must not be rechecked for committed replay.
    replay = client.post("/api/editor/save", headers=headers, json=child)
    assert replay.status_code == 200 and replay.content == saved.content
    fresh = {**child, "idempotency_key": "child:fresh"}
    assert client.post("/api/editor/save", headers=headers, json={**fresh, "expected_source_hash": "0" * 64}).status_code == 409
    denied = client.post("/api/editor/save", headers=headers, json=fresh)
    assert denied.status_code == 422 and denied.json() == {"detail": "Invalid request input"}
    app.state.documents.views.clear()
    app.state.documents.frozen.clear()
    shutil.rmtree(tmp_path / "state/editor-revision-bundles" / payload["source"]["editor_revision_id"])
    shutil.rmtree(tmp_path / "managed")
    root = tmp_path / "state/editor-revision-bundles"
    artifacts = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    before = list(app.state.journal.db.iterdump())
    replay = client.post("/api/editor/save", headers=headers, json=child)
    assert replay.status_code == 200 and replay.content == saved.content
    assert client.get("/api/editor/save-requests/" + child["idempotency_key"]).json() == saved.json()
    assert client.post("/api/editor/save", headers=headers, json=fresh).status_code == 409
    assert client.post("/api/editor/save", headers=headers, json={**child, "yaml_text": child["yaml_text"] + "\n"}).status_code == 409
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == artifacts
    assert list(app.state.journal.db.iterdump()) == before
    assert not app.state.workflow_authorization.grants._records


def test_research_descriptor_cannot_borrow_reservation_from_other_configured_store(api, tmp_path):
    app, client, headers = api
    payload = manual_payload(client, headers)
    commit = client.post(URL, headers=headers, json=payload).json()
    app.state.research_roots["secondary"] = tmp_path / "secondary"
    with ResearchStore.create(app.state.journal, tmp_path / "secondary", "secondary",
                             protect_public=app.state.model_settings.protect_public):
        pass
    before = list(app.state.journal.db.iterdump())
    views = dict(app.state.documents.views)
    descriptor = "research-version:secondary:" + commit["reservation"]["reservation_id"] + ":" + commit["manifest"]["digest"]
    response = client.get("/api/editor/documents/" + descriptor)
    assert response.status_code == 409, response.text
    assert app.state.documents.views == views
    assert list(app.state.journal.db.iterdump()) == before


@pytest.mark.parametrize("change", ["digest", "store", "reservation", "alias", "malformed", "identifier"])
def test_research_descriptor_never_resolves_latest_or_other_store(api, change):
    app, client, headers = api
    payload = manual_payload(client, headers)
    commit = client.post(URL, headers=headers, json=payload).json()
    parts = ["research-version", "primary", commit["reservation"]["reservation_id"], commit["manifest"]["digest"]]
    expected = 409
    if change == "digest":
        parts[3] = "0" * 64
    elif change == "store":
        parts[1] = "not-configured"
        expected = 404
    elif change == "reservation":
        parts[2] = "0" * 32
    elif change == "alias":
        parts[3] = "latest"
        expected = 422
    elif change == "malformed":
        parts.append("extra")
        expected = 422
    else:
        parts[1] = "_invalid"
        expected = 422
    before = dict(app.state.documents.views)
    response = client.get("/api/editor/documents/" + ":".join(parts))
    assert response.status_code == expected, response.text
    assert app.state.documents.views == before


@pytest.mark.parametrize("endpoint", ["list", "detail", "artifact", "open", "replay"])
def test_corrupt_copied_source_never_opens_or_repairs(api, tmp_path, endpoint):
    app, client, headers = api
    payload = manual_payload(client, headers)
    commit = client.post(URL, headers=headers, json=payload).json()
    directory = tmp_path / "managed" / commit["relative_directory"]
    (directory / "environment.yaml").write_bytes(b"private-corrupt-source")
    before = {p.relative_to(directory): p.read_bytes() for p in directory.iterdir() if p.is_file()}
    detail = URL + "/" + commit["reservation"]["reservation_id"]
    descriptor = "research-version:primary:" + commit["reservation"]["reservation_id"] + ":" + commit["manifest"]["digest"]
    if endpoint == "replay":
        response = client.post(URL, headers=headers, json=payload)
    else:
        response = client.get({"list": URL + "?family=family", "detail": detail, "artifact": detail + "/artifacts/source.json",
                               "open": "/api/editor/documents/" + descriptor}[endpoint])
    assert response.status_code == 409, response.text
    assert "private-corrupt" not in response.text
    assert {p.relative_to(directory): p.read_bytes() for p in directory.iterdir() if p.is_file()} == before


def test_manual_replay_and_exact_open_survive_full_api_restart(tmp_path, monkeypatch):
    def unavailable(_):
        raise RuntimeError("No renderer in X05 restart check")
    monkeypatch.setattr(editor_execution, "make_snapshot_service", unavailable)
    state, roots = tmp_path / "state", {"primary": tmp_path / "managed"}
    with TestClient(create_app(state, start_paused=True, research_roots=roots), base_url=ORIGIN) as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        with ResearchStore.create(client.app.state.journal, roots["primary"], "primary", protect_public=client.app.state.model_settings.protect_public):
            pass
        payload = manual_payload(client, headers)
        saved = client.post(URL, headers=headers, json=payload)
        assert saved.status_code == 201, saved.text
        commit = saved.json()
        descriptor = "research-version:primary:" + commit["reservation"]["reservation_id"] + ":" + commit["manifest"]["digest"]
        issued = client.get("/api/editor/documents/" + descriptor).json()
        shutil.rmtree(state / "editor-revision-bundles")
    with TestClient(create_app(state, start_paused=True, research_roots=roots), base_url=ORIGIN) as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        replay = client.post(URL, headers=headers, json=payload)
        assert replay.status_code == 201, replay.text
        assert replay.content == saved.content
        assert client.get("/api/editor/documents/" + issued["document_id"]).status_code == 404
        reopened = client.get("/api/editor/documents/" + descriptor)
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["document_id"] != issued["document_id"]
        assert reopened.json()["research_identity"] == issued["research_identity"]
        assert reopened.json()["yaml_text"] == issued["yaml_text"]
        assert client.get("/api/jobs").json()["jobs"] == []


def test_manual_parent_is_explicit_not_latest_and_callback_is_reject_only(api, monkeypatch):
    app, client, headers = api
    payload = manual_payload(client, headers)
    first = client.post(URL, headers=headers, json=payload).json()
    second = client.post(URL, headers=headers, json={**payload, "idempotency_key": "second-root"}).json()
    assert second["reservation"]["parent_revision_id"] is None
    third = client.post(URL, headers=headers, json={**payload, "idempotency_key": "explicit-child",
        "parent_revision_id": first["reservation"]["revision_id"]}).json()
    assert third["reservation"]["parent_revision_id"] == first["reservation"]["revision_id"]
    assert third["reservation"]["version"] == 3
    original = app.state.model_settings.protect_public
    def mutate_bundle(value):
        original(value)
        if isinstance(value, dict) and "snapshot" in value:
            value["snapshot"]["yaml_text"] += "\n"
    monkeypatch.setattr(app.state.model_settings, "protect_public", mutate_bundle)
    before = list(app.state.journal.db.iterdump())
    response = client.post(URL, headers=headers, json={**payload, "idempotency_key": "callback-mutation"})
    assert response.status_code == 409, response.text
    assert list(app.state.journal.db.iterdump()) == before


def test_manual_publication_rejected_before_source_read_and_reservation(api, monkeypatch):
    app, client, headers = api
    payload = manual_payload(client, headers)
    payload["publication_target"] = {"profile_id": "graph", "revision": "a" * 64, "scope_ownership": "cooperative_immutable"}
    def forbidden(*args, **kwargs):
        pytest.fail("Manual publication must reject before reading source")
    monkeypatch.setattr(app.state.documents, "load_revision_bundle", forbidden)
    before = list(app.state.journal.db.iterdump())
    response = client.post(URL, headers=headers, json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Editor revision publication is unsupported"}
    assert list(app.state.journal.db.iterdump()) == before




