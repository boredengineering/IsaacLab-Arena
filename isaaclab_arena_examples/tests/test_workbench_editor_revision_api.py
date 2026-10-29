# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

"""Editor revision request contracts; run only in the isolated API test sandbox."""

import os
import time

import pytest
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.workbench import editor_revision_storage as storage
from fastapi.testclient import TestClient
from pydantic import ValidationError

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app
from isaaclab_arena_examples.agentic_environment_generation.web_api import editor_execution
from isaaclab_arena_examples.agentic_environment_generation.web_api.editor import SaveDraft
from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents

ORIGIN = "http://127.0.0.1:3000"
FIXTURE = Path(__file__).resolve().parents[2] / "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"


@pytest.fixture(autouse=True)
def revision_only_runtime(monkeypatch):
    """Exercise real revision HTTP/storage paths with the optional renderer unavailable."""
    def unavailable(_state_dir):
        raise RuntimeError("Revision-only test profile has no snapshot service")
    monkeypatch.setattr(editor_execution, "make_snapshot_service", unavailable)


def login(client):
    session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
    return {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}


def test_health_advertises_durable_save_without_granting_workload_admission(tmp_path):
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        capabilities = response.json()["capabilities"]
        assert capabilities.get("durable_editor_save") is True
        assert capabilities["generation"] is False
        assert capabilities["preview"] is False
        assert client.get("/api/editor").status_code == 401
        login(client)
        assert client.get("/api/editor").json()["capabilities"]["durable_editor_save"] is True
        assert client.get("/api/jobs").json()["jobs"] == []


def test_keyed_revision_replay_and_immutable_open_survive_api_restart(tmp_path):
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        headers = login(client)
        catalogue = client.get("/api/editor").json()
        document = client.get("/api/editor/documents/" + catalogue["default_document_id"]).json()
        payload = {"yaml_text": document["yaml_text"], "document_id": document["document_id"],
                   "expected_source_hash": document["source_hash"], "idempotency_key": "save:api-restart"}
        response = client.post("/api/editor/save", json=payload, headers=headers)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["state"] == "committed"
        assert receipt["idempotency_key"] == payload["idempotency_key"]
        assert client.post("/api/editor/save", json=payload, headers=headers).json() == receipt
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        assert client.get("/api/editor/save-requests/save:api-restart").status_code == 401
        headers = login(client)
        assert client.get("/api/editor/save-requests/save:api-restart").json() == receipt
        replay = client.post("/api/editor/save", json=payload, headers=headers)
        assert replay.status_code == 200, replay.text
        assert replay.json() == receipt
        assert client.post("/api/editor/save", json={**payload, "yaml_text": payload["yaml_text"] + "\n"}, headers=headers).status_code == 409
        source_id = receipt["revision"]["open_source"]["id"]
        opened = client.get("/api/editor/documents/" + source_id)
        assert opened.status_code == 200, opened.text
        opened = opened.json()
        assert opened["yaml_text"] == payload["yaml_text"]
        assert opened["validation"]["valid"]
        assert opened["document_id"] != document["document_id"]
        implicit = client.post("/api/editor/generate", headers=headers, json={
            "prompt": "Do not execute; use the issued immutable view as the implicit base",
            "document_id": opened["document_id"], "idempotency_key": "implicit:immutable-view",
        })
        assert implicit.status_code == 503, implicit.text
        assert implicit.json() == {"detail": "Generation is not configured; set a supported server-side model API key"}
        assert client.get("/api/editor/documents/" + source_id).json()["document_id"] != opened["document_id"]
        assert client.post("/api/editor/validate", json={"document_id": opened["document_id"], "yaml_text": opened["yaml_text"]}, headers=headers).json()["valid"]
        refinement = client.post("/api/editor/generate", headers=headers, json={
            "operation": "refine", "prompt": "Do not execute; verify the immutable view boundary",
            "base_yaml": opened["yaml_text"], "document_id": opened["document_id"],
            "idempotency_key": "refine:unconfigured-immutable-view",
        })
        assert refinement.status_code == 503, refinement.text
        assert refinement.json()["detail"] == "Workflow configuration unavailable"
        assert any(row["id"] == source_id and row["kind"] == "editor_revision" for row in client.get("/api/editor").json()["documents"])
        assert client.get("/api/jobs").json()["jobs"] == []


@pytest.mark.parametrize("location", ["root", "unused_include"])
@pytest.mark.parametrize("encoding", ["hex", "folded"])
def test_committed_revision_rechecks_current_secret_policy_without_changing_artifacts(tmp_path, location, encoding):
    marker = "dummy-revision-boundary-marker-123456"
    escaped = ('"' + ''.join(f"\\x{ord(char):02x}" for char in marker) + '"') if encoding == "hex" else ('"dummy-revision-' + chr(92) + '\n  boundary-marker-123456"')
    sensitive = FIXTURE.read_text().replace("pick_and_place_maple_table_default", escaped)
    source = tmp_path / "repo/generated_envs/scene.yaml"
    source.parent.mkdir(parents=True)
    if location == "unused_include":
        (source.parent / "included.yaml").write_text(sensitive)
        source.write_text("external_yaml: included.yaml\n")
    else:
        source.write_text(sensitive)
    state = tmp_path / "state"
    app = create_app(state, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        app.state.documents = Documents(state, root=tmp_path / "repo")
        source_id = next(row["id"] for row in app.state.documents.index() if row["name"] == "scene")
        document = app.state.documents.load(source_id)
        headers = login(client)
        payload = {"yaml_text": FIXTURE.read_text() if location == "unused_include" else document["yaml_text"],
                   "document_id": document["document_id"], "expected_source_hash": document["source_hash"],
                   "idempotency_key": "save:policy"}
        saved = client.post("/api/editor/save", headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        revision = saved.json()["revision"]
        issued = client.get("/api/editor/documents/" + revision["open_source"]["id"])
        assert issued.status_code == 200, issued.text
        issued_id = issued.json()["document_id"]
        bundle_root = state / "editor-revision-bundles"
        before = {path.relative_to(bundle_root): path.read_bytes() for path in bundle_root.rglob("*") if path.is_file()}
        settings = client.put("/api/model-settings", headers=headers, json={"provider": "openai", "model": "test-model", "api_key": marker})
        assert settings.status_code == 200
        responses = [client.post("/api/editor/save", headers=headers, json=payload),
                     client.get("/api/editor/save-requests/save:policy"),
                     client.get(revision["download_url"]),
                     client.get("/api/editor/documents/" + revision["open_source"]["id"]),
                     client.get("/api/editor/documents/" + issued_id),
                     client.post("/api/editor/generate", headers=headers, json={
                         "document_id": issued_id, "prompt": "Do not execute; reject the retained secret",
                         "idempotency_key": "implicit:secret-view",
                     }),
                     client.get("/api/editor")]
        for response in responses:
            assert response.status_code == 422
            assert response.json() == {"detail": "Invalid request input"}
        assert {path.relative_to(bundle_root): path.read_bytes() for path in bundle_root.rglob("*") if path.is_file()} == before
        assert client.get("/api/jobs").json()["jobs"] == []


@pytest.mark.parametrize("location", ["base_yaml", "nested_yaml", "nested_metadata"])
@pytest.mark.parametrize("endpoint", ["replay", "operation"])
@pytest.mark.parametrize("encoding", ["hex", "folded"])
def test_generation_recovery_checks_complete_current_record_without_resolving_view(tmp_path, monkeypatch, location, endpoint, encoding):
    import hashlib
    import json
    from isaaclab_arena_examples.agentic_environment_generation.web_api.editor import GenerateDraft

    marker = "dummy-generation-recovery-marker-123456"
    encoded = '"' + ''.join(f"\\x{ord(char):02x}" for char in marker) + '"'
    if encoding == "folded":
        encoded = '"dummy-generation-' + chr(92) + '\n  recovery-marker-123456"'
    sensitive = FIXTURE.read_text().replace("pick_and_place_maple_table_default", encoded)
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        headers = login(client)
        payload = {"operation": "refine", "prompt": "Synthetic storage fixture; no model generation",
                   "base_yaml": sensitive if location == "base_yaml" else FIXTURE.read_text(),
                   "document_id": "e" * 32, "idempotency_key": "recover:current-policy"}
        request_hash = hashlib.sha256(json.dumps(GenerateDraft(**payload).model_dump(),
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        # An accepted Journal storage fixture, NOT model/worker execution evidence.
        journal = app.state.journal
        job = journal.submit("fixture", "default", "generate", payload["idempotency_key"], {
            "operation": "refine", "request_sha256": request_hash, "base_yaml": payload["base_yaml"],
            "document_id": payload["document_id"]})
        attempt = journal.claim_attempt(job["id"])
        assert journal.release_attempt(job["id"], **attempt)
        receipt = {"yaml_text": sensitive if location == "nested_yaml" else FIXTURE.read_text(),
                   "validation": {"valid": True}, "publication": "not_published",
                   "metadata": {"nested": [marker if location == "nested_metadata" else "inert"]}}
        assert journal.commit_candidate(job["id"], **attempt, receipt=receipt)
        assert journal.complete_attempt(job["id"], **attempt, expected_state="candidate_committed")
        prior = journal.get_submission("default", payload["idempotency_key"])
        path = "/api/editor/generate/operations/" + payload["idempotency_key"] + "?request_sha256=" + request_hash

        def forbidden(*args, **kwargs):
            pytest.fail("Recovery must not resolve views, submit, wake or capture grants")
        monkeypatch.setattr(app.state.documents, "resolve_view", forbidden)
        monkeypatch.setattr(app.state.documents, "load", forbidden)
        monkeypatch.setattr(journal, "submit", forbidden)
        monkeypatch.setattr(app.state.workflow_authorization, "capture", forbidden)
        with monkeypatch.context() as patcher:
            patcher.setattr(app.state.supervisor.wake, "set", forbidden)
            assert client.post("/api/editor/generate", headers=headers, json=payload).json() == prior
            assert client.get(path).json() == {"job": prior}
        assert client.put("/api/model-settings", headers=headers, json={
            "provider": "openai", "model": "inert", "api_key": marker}).status_code == 200
        before = list(journal.db.iterdump())
        grants = dict(app.state.workflow_authorization.grants._records)
        with monkeypatch.context() as patcher:
            patcher.setattr(app.state.supervisor.wake, "set", forbidden)
            response = (client.get(path) if endpoint == "operation" else
                        client.post("/api/editor/generate", headers=headers, json=payload))
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert client.get(path.replace(request_hash, "0" * 64)).status_code == 409
        assert client.post("/api/editor/generate", headers=headers, json={**payload, "prompt": "different"}).status_code == 409
        assert client.get(path + "&request_sha256=" + request_hash).status_code == 422
        assert client.get(path.replace(payload["idempotency_key"], "unknown:operation")).json() == {"job": None}
        assert list(journal.db.iterdump()) == before
        assert journal.get_submission("default", payload["idempotency_key"]) == prior
        assert app.state.workflow_authorization.grants._records == grants
        assert not app.state.publication_authorization._records


def test_fresh_generation_screening_precedes_grants_and_durable_submission(tmp_path, monkeypatch):
    marker = "dummy-fresh-generation-marker-123456"
    escaped = ''.join(f"\\x{ord(char):02x}" for char in marker)
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        headers = login(client)
        settings = client.put("/api/model-settings", headers=headers, json={
            "provider": "openai", "model": "inert", "api_key": marker})
        assert settings.status_code == 200
        reference = settings.json()["credential_ref"]
        before = list(app.state.journal.db.iterdump())
        captures = []
        original = app.state.workflow_authorization.capture
        def capture(*args, **kwargs):
            captures.append("capture")
            return original(*args, **kwargs)
        monkeypatch.setattr(app.state.workflow_authorization, "capture", capture)
        response = client.post("/api/editor/generate", headers=headers, json={
            "operation": "new", "prompt": escaped, "credential_ref": reference, "idempotency_key": "fresh:encoded-prompt"})
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert list(app.state.journal.db.iterdump()) == before
        assert captures == []
        assert not app.state.workflow_authorization.grants._records


@pytest.mark.parametrize("explicit,server", [(True, False), (False, False), (True, True)],
                         ids=["explicit-session", "legacy-session", "explicit-server"])
@pytest.mark.parametrize("sensitive", ["hex", "nested-key", None], ids=["escaped-model", "nested-key", "clean-control"])
def test_resolved_generation_model_is_screened_before_grant_or_journal(tmp_path, monkeypatch, explicit, server, sensitive):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation

    marker = "DUMMY-resolved-model-key-123456"
    escaped = ''.join(f"\\x{ord(char):02x}" for char in marker)
    model = escaped if sensitive == "hex" else ('{"' + escaped + '":0}' if sensitive else "inert-model")
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        headers = login(client)
        payload = {"prompt": "Admission only; no worker or provider", "idempotency_key": "resolved:model-admission"}
        if server:
            monkeypatch.setattr(generation, "configuration", lambda: {
                "provider": "openai", "model": model, "api_key": marker, "base_url": "https://synthetic.invalid/v1"})
        else:
            settings = client.put("/api/model-settings", headers=headers, json={
                "provider": "openai", "model": "inert-model", "api_key": marker})
            assert settings.status_code == 200
            assert settings.json()["model"] == "inert-model"
            payload["credential_ref"] = settings.json()["credential_ref"]
            if sensitive:
                # Explicit legacy in-memory fixture: current Settings PUT rejects
                # unsafe metadata. Preserve generation's independent guard test.
                owner = client.get("/api/session").json()["session_id"]
                app.state.model_settings._records[owner]["model"] = model
        if explicit:
            payload["operation"] = "new"
        journal = app.state.journal
        before = list(journal.db.iterdump())
        calls = []
        original_issue = app.state.workflow_authorization.grants.issue
        original_submit = journal.submit
        def issue(*args, **kwargs):
            calls.append("issue:" + args[2])
            return original_issue(*args, **kwargs)
        def submit(*args, **kwargs):
            calls.append("submit")
            return original_submit(*args, **kwargs)
        with monkeypatch.context() as patcher:
            patcher.setattr(app.state.workflow_authorization.grants, "issue", issue)
            patcher.setattr(journal, "submit", submit)
            patcher.setattr(app.state.supervisor.wake, "set", lambda: calls.append("wake"))
            response = client.post("/api/editor/generate", headers=headers, json=payload)
        if sensitive:
            assert response.status_code == 422
            assert response.json() == {"detail": "Invalid request input"}
            assert calls == [], "Rejected resolved metadata must precede every grant, submit and wake"
            assert list(journal.db.iterdump()) == before
            assert journal.get_submission("default", payload["idempotency_key"]) is None
            assert not app.state.workflow_authorization.grants._records
        else:
            assert response.status_code == 202, response.text
            assert calls == (["issue:model"] if explicit else []) + ["submit", "wake"]
            job = response.json()
            assert journal.get_submission("default", payload["idempotency_key"]) == job
            frozen = job["inputs"]["workflow_authorization"]["model"]["profile"] if explicit else job["inputs"]
            assert frozen["model"] == model
            assert marker not in response.text
            calls.clear()
            with monkeypatch.context() as patcher:
                patcher.setattr(app.state.workflow_authorization.grants, "issue", issue)
                patcher.setattr(app.state.supervisor.wake, "set", lambda: calls.append("wake"))
                replay = client.post("/api/editor/generate", headers=headers, json=payload)
            assert replay.status_code == 202
            assert replay.json() == job
            assert calls == []


@pytest.mark.parametrize("sensitive", [True, False], ids=["escaped-retrieval", "clean-control"])
def test_all_resolved_workflow_profiles_are_screened_before_first_grant(tmp_path, monkeypatch, sensitive):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import graph_access

    marker = "DUMMY-retrieval-profile-key-123456"
    escaped = ''.join(f"\\x{ord(char):02x}" for char in marker)
    graph = {"uri": "bolt://synthetic.invalid:7687", "user": escaped if sensitive else "reader",
             "database": "synthetic", "password": marker}
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        headers = login(client)
        settings = client.put("/api/model-settings", headers=headers, json={
            "provider": "openai", "model": "inert-model", "api_key": "DUMMY-distinct-model-key-123456"})
        assert settings.status_code == 200
        monkeypatch.setattr(graph_access, "configuration", lambda: dict(graph))
        journal = app.state.journal
        before = list(journal.db.iterdump())
        calls = []
        original_issue = app.state.workflow_authorization.grants.issue
        original_submit = journal.submit
        def issue(*args, **kwargs):
            calls.append("issue:" + args[2])
            return original_issue(*args, **kwargs)
        def submit(*args, **kwargs):
            calls.append("submit")
            return original_submit(*args, **kwargs)
        with monkeypatch.context() as patcher:
            patcher.setattr(app.state.workflow_authorization.grants, "issue", issue)
            patcher.setattr(journal, "submit", submit)
            patcher.setattr(app.state.supervisor.wake, "set", lambda: calls.append("wake"))
            response = client.post("/api/editor/generate", headers=headers, json={
                "operation": "new", "retrieval_policy": "require_service", "prompt": "Admission only",
                "credential_ref": settings.json()["credential_ref"], "idempotency_key": "resolved:all-profiles"})
        if sensitive:
            assert response.status_code == 422
            assert response.json() == {"detail": "Invalid request input"}
            assert calls == [], "Retrieval screening must precede even the model grant"
            assert list(journal.db.iterdump()) == before
            assert not app.state.workflow_authorization.grants._records
        else:
            assert response.status_code == 202, response.text
            assert calls == ["issue:model", "issue:retrieval_read", "submit", "wake"]
            job = response.json()
            assert journal.get_submission("default", "resolved:all-profiles") == job
            assert job["inputs"]["workflow_authorization"]["retrieval"]["profile"]["user"] == "reader"
            assert marker not in response.text


@pytest.mark.parametrize("kind", ["generate", "snapshots"])
def test_legacy_editor_replay_protects_nested_yaml_before_submission_or_wake(tmp_path, monkeypatch, kind):
    import yaml
    from isaaclab_arena_examples.agentic_environment_generation.web_api.preview_options import normalized_options

    marker = "dummy-legacy-recovery-marker-123456"
    encoded = '"' + ''.join(f"\\x{ord(char):02x}" for char in marker) + '"'
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        headers = login(client)
        text = FIXTURE.read_text()
        validation = app.state.documents.validate(text)
        frozen = yaml.safe_dump(validation["spec"], sort_keys=False)
        payload = {"idempotency_key": "legacy:current-policy"}
        if kind == "generate":
            payload.update(prompt="Synthetic legacy storage fixture", base_yaml=text)
            inputs = {"prompt": payload["prompt"], "base_yaml": frozen, "document_id": None, "input_hash": validation["source_hash"]}
        else:
            payload["yaml_text"] = text
            inputs = {"yaml_text": frozen, "document_id": None, "input_hash": validation["source_hash"],
                      "canonical_hash": validation["canonical_hash"], "options": normalized_options({}, validation["spec"])}
            # Admission sentinel only; no snapshot method or renderer may run.
            class AdmissionOnly:
                def close(self):
                    pass
            app.state.editor_execution.snapshots = AdmissionOnly()
        journal = app.state.journal
        job = journal.submit("fixture", "default", kind, payload["idempotency_key"], inputs)
        journal.transition(job["id"], "succeeded", "completed", "synthetic_fixture", result={
            "nested": [{"yaml_text": text.replace("pick_and_place_maple_table_default", encoded)}]})
        prior = journal.get_submission("default", payload["idempotency_key"])
        path = "/api/editor/" + ("generate" if kind == "generate" else "snapshots")
        wakes = []
        with monkeypatch.context() as patcher:
            patcher.setattr(app.state.supervisor.wake, "set", lambda: wakes.append("wake"))
            assert client.post(path, headers=headers, json=payload).json() == prior
        assert wakes == []
        assert client.put("/api/model-settings", headers=headers, json={
            "provider": "openai", "model": "inert", "api_key": marker}).status_code == 200
        before = list(journal.db.iterdump())
        calls = []
        original_submit = journal.submit
        def tracked_submit(*args, **kwargs):
            calls.append("submit")
            return original_submit(*args, **kwargs)
        with monkeypatch.context() as patcher:
            patcher.setattr(journal, "submit", tracked_submit)
            patcher.setattr(app.state.supervisor.wake, "set", lambda: calls.append("wake"))
            response = client.post(path, headers=headers, json=payload)
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert calls == []
        assert list(journal.db.iterdump()) == before
        assert journal.get_submission("default", payload["idempotency_key"]) == prior
        assert not app.state.workflow_authorization.grants._records


def saved_revision(client, headers):
    payload = {"yaml_text": FIXTURE.read_text(), "idempotency_key": "save:http-fault"}
    saved = client.post("/api/editor/save", headers=headers, json=payload)
    assert saved.status_code == 200, saved.text
    return payload, saved.json()


def revision_response(client, headers, payload, receipt, endpoint):
    revision = receipt["revision"]
    if endpoint == "save":
        return client.post("/api/editor/save", headers=headers, json=payload)
    paths = {"lookup": "/api/editor/save-requests/" + payload["idempotency_key"],
             "index": "/api/editor", "open": "/api/editor/documents/" + revision["open_source"]["id"],
             "download": revision["download_url"]}
    return client.get(paths[endpoint])


@pytest.mark.parametrize("endpoint", ["save", "lookup", "index", "open", "download"])
def test_busy_revision_http_is_bounded_static_retryable_and_preserves_receipt(tmp_path, monkeypatch, endpoint):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        headers = login(client)
        payload, receipt = saved_revision(client, headers)
        root = tmp_path / "editor-revision-bundles"
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        monkeypatch.setattr(storage, "LOCK_SECONDS", 0.02)
        with app.state.documents.revisions.area(lock=True):
            started = time.monotonic()
            response = revision_response(client, headers, payload, receipt, endpoint)
            elapsed = time.monotonic() - started
        assert response.status_code == 503, response.text
        assert response.json() == {"detail": "Revision storage is busy; retry the exact request"}
        assert response.headers["Retry-After"] == "1"
        assert elapsed < 1, elapsed
        assert client.get("/api/editor/save-requests/" + payload["idempotency_key"]).json() == receipt
        assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
        assert client.get("/api/jobs").json()["jobs"] == []


@pytest.mark.parametrize("endpoint", ["save", "lookup", "index", "open", "download"])
def test_revision_http_fsync_uncertain_is_static_503_not_corrupt_or_missing(tmp_path, monkeypatch, endpoint):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        headers = login(client)
        payload, receipt = saved_revision(client, headers)
        root = tmp_path / "editor-revision-bundles"
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        real_sync = os.fsync
        attempted = []

        def fail_sync(fd):
            name = os.readlink(f"/proc/self/fd/{fd}")
            if name.endswith("/manifest.json"):
                attempted.append(name)
                raise OSError("private-fsync-exception-marker /private/secret-path")
            return real_sync(fd)

        with monkeypatch.context() as patcher:
            patcher.setattr(os, "fsync", fail_sync)
            response = revision_response(client, headers, payload, receipt, endpoint)
        assert attempted, "The real revision read must attempt durability reconciliation"
        assert response.status_code == 503, response.text
        message = {"save": "Revision save outcome is uncertain; check the exact saved request before retrying",
                   "lookup": "Revision disposition unavailable; retain the exact request"}.get(
                       endpoint, "Revision data unavailable; retain the exact request")
        assert response.json() == {"detail": message}
        assert "private-fsync-exception-marker" not in response.text
        assert client.get("/api/editor/save-requests/" + payload["idempotency_key"]).json() == receipt
        assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
        assert client.get("/api/jobs").json()["jobs"] == []


@pytest.mark.parametrize("endpoint", ["save", "lookup", "index", "open", "download"])
def test_corrupt_manifest_http_is_explicit_static_and_never_repaired(tmp_path, endpoint):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        headers = login(client)
        payload, receipt = saved_revision(client, headers)
        root = tmp_path / "editor-revision-bundles"
        manifest = root / receipt["revision"]["revision_id"] / "manifest.json"
        manifest.write_bytes(b'{"private-corrupt-manifest-marker":')
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        response = revision_response(client, headers, payload, receipt, endpoint)
        disposition = endpoint in {"save", "lookup"}
        assert response.status_code == (409 if disposition else 422), response.text
        assert response.json() == {"detail": "Revision request conflicts with stored data or source" if disposition
                                   else "Invalid editor revision bundle"}
        assert "private-corrupt-manifest-marker" not in response.text
        assert "Retry-After" not in response.headers
        assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
        assert client.get("/api/jobs").json()["jobs"] == []


@pytest.mark.parametrize("fault", ["busy", "uncertain", "corrupt"])
def test_implicit_generation_preserves_issued_revision_failure_disposition(tmp_path, monkeypatch, fault):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        headers = login(client)
        _, receipt = saved_revision(client, headers)
        opened = client.get("/api/editor/documents/" + receipt["revision"]["open_source"]["id"])
        assert opened.status_code == 200
        issued_id = opened.json()["document_id"]
        root = tmp_path / "editor-revision-bundles"
        manifest = root / receipt["revision"]["revision_id"] / "manifest.json"
        if fault == "corrupt":
            manifest.write_bytes(b'{"private-generation-corruption":')
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

        def generate():
            return client.post("/api/editor/generate", headers=headers, json={
                "document_id": issued_id, "prompt": "Check storage disposition without generation",
                "idempotency_key": "implicit:storage-fault",
            })

        if fault == "busy":
            monkeypatch.setattr(storage, "LOCK_SECONDS", 0.02)
            with app.state.documents.revisions.area(lock=True):
                response = generate()
        elif fault == "uncertain":
            real_sync = os.fsync
            attempted = []

            def fail_sync(fd):
                if os.readlink(f"/proc/self/fd/{fd}").endswith("/manifest.json"):
                    attempted.append(fd)
                    raise OSError("private-generation-fsync /private/path")
                return real_sync(fd)

            with monkeypatch.context() as patcher:
                patcher.setattr(os, "fsync", fail_sync)
                response = generate()
            assert attempted, "Implicit generation must reconcile its actual retained revision"
        else:
            response = generate()

        expected = {
            "busy": (503, "Revision storage is busy; retry the exact request"),
            "uncertain": (503, "Revision data unavailable; retain the exact request"),
            "corrupt": (422, "Invalid editor revision bundle"),
        }[fault]
        assert response.status_code == expected[0], response.text
        assert response.json() == {"detail": expected[1]}
        assert response.headers.get("Retry-After") == ("1" if fault == "busy" else None)
        assert "private-generation" not in response.text
        assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
        assert client.get("/api/jobs").json()["jobs"] == []


def test_revision_routes_require_csrf_and_reject_expired_session_without_writes(tmp_path, monkeypatch):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        payload = {"yaml_text": FIXTURE.read_text(), "idempotency_key": "save:http-fault"}
        denied = client.post("/api/editor/save", headers={"Origin": ORIGIN}, json=payload)
        assert denied.status_code == 403
        assert denied.json() == {"detail": "CSRF token required"}
        assert not (tmp_path / "editor-revision-bundles").exists()
        payload, receipt = saved_revision(client, headers)
        root = tmp_path / "editor-revision-bundles"
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        expires_at = client.get("/api/session").json()["expires_at"]
        with monkeypatch.context() as patcher:
            patcher.setattr(app.state.sessions, "clock", lambda: expires_at)
            for endpoint in ("save", "lookup", "index", "open", "download"):
                response = revision_response(client, headers, payload, receipt, endpoint)
                assert response.status_code == 401
                assert response.json() == {"detail": "Session expired or revoked"}
        assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
        assert client.get("/api/editor/save-requests/" + payload["idempotency_key"]).json() == receipt
        assert client.get("/api/jobs").json()["jobs"] == []


def test_legacy_file_implicit_generation_and_unkeyed_export_remain_usable_without_jobs(tmp_path):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        source_id = client.get("/api/editor").json()["default_document_id"]
        loaded = client.get("/api/editor/documents/" + source_id).json()
        for document_id in (source_id, loaded["document_id"]):
            response = client.post("/api/editor/generate", headers=headers, json={
                "document_id": document_id, "prompt": "Do not execute; verify legacy implicit base",
                "idempotency_key": "legacy:" + document_id,
            })
            assert response.status_code == 503, response.text
            assert response.json() == {"detail": "Generation is not configured; set a supported server-side model API key"}
        saved = client.post("/api/editor/save", headers=headers, json={
            "yaml_text": loaded["yaml_text"], "document_id": loaded["document_id"],
            "expected_source_hash": loaded["source_hash"],
        })
        assert saved.status_code == 200, saved.text
        revision = saved.json()
        assert set(revision) == {"revision_id", "yaml_text", "source_hash", "canonical_hash", "download_url"}
        download = client.get(revision["download_url"])
        assert download.status_code == 200
        assert download.text.startswith("# Flattened immutable Arena editor export (includes resolved).\n")
        assert client.post("/api/editor/validate", headers=headers, json={"yaml_text": download.text}).json()["canonical_hash"] == loaded["validation"]["canonical_hash"]
        assert client.get("/api/jobs").json()["jobs"] == []


@pytest.mark.parametrize("endpoint", ["save", "lookup", "index", "open", "download"])
@pytest.mark.parametrize("error_type", [storage.RevisionBusy, storage.RevisionUncertain, storage.RevisionError])
def test_revision_boundary_never_reflects_exception_text(tmp_path, monkeypatch, endpoint, error_type):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        headers = login(client)
        payload, receipt = saved_revision(client, headers)
        def fail(*args, **kwargs):
            raise error_type("private-exception-marker /private/path")
        # Fault only the bundle read, keeping HTTP authorization and conversion real.
        with monkeypatch.context() as patcher:
            patcher.setattr(app.state.documents, "_revision", fail)
            response = revision_response(client, headers, payload, receipt, endpoint)
        expected = (409 if endpoint in {"save", "lookup"} else 422) if error_type is storage.RevisionError else 503
        assert response.status_code == expected, response.text
        assert "private-exception-marker" not in response.text
        assert "/private/path" not in response.text
        assert client.get("/api/editor/save-requests/" + payload["idempotency_key"]).json() == receipt
        assert client.get("/api/jobs").json()["jobs"] == []


def test_revision_save_accepts_an_explicit_retry_key_without_changing_legacy_fields():
    body = SaveDraft.model_validate({"yaml_text": "env_name: draft\n", "idempotency_key": "save:test-1"})
    assert body.idempotency_key == "save:test-1"
    assert body.yaml_text == "env_name: draft\n"
    assert body.document_id is None
    assert body.expected_source_hash is None
    assert SaveDraft.model_validate({"yaml_text": "env_name: draft\n"}).idempotency_key is None


@pytest.mark.parametrize("key", ["", "../outside", "space key", "x" * 129, 1, True, ":bad", "_bad", ".bad", "-bad"])
def test_revision_save_rejects_invalid_retry_keys(key):
    with pytest.raises(ValidationError):
        SaveDraft.model_validate({"yaml_text": "env_name: draft\n", "idempotency_key": key})
