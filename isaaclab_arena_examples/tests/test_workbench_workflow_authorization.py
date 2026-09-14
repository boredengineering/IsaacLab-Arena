# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Workflow acceptance and private authorization, without provider traffic."""

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, generation, graph_access
from isaaclab_arena_examples.tests.test_workbench_editor import ORIGIN, login

MODEL = {
    "api_key": "private-model-key-marker-12345",
    "model": "test-model",
    "provider": "openai",
    "base_url": "https://api.openai.com/v1",
    "trusted_server": True,
}
GRAPH = {
    "uri": "bolt://graph.invalid:7687",
    "user": "neo4j",
    "password": "private-graph-password-marker-12345",
    "database": "neo4j",
}
BODY = {"operation": "new", "prompt": "Move cube", "idempotency_key": "workflow-one"}


@pytest.fixture
def configs(monkeypatch):
    model, graph = dict(MODEL), dict(GRAPH)
    monkeypatch.setattr(generation, "configuration", lambda: dict(model) if model else None)
    monkeypatch.setattr(graph_access, "configuration", lambda: dict(graph) if graph else None)
    monkeypatch.setattr(generation, "generate", lambda *a, **k: pytest.fail("Provider call"))
    return model, graph


@pytest.mark.parametrize("change", ["replace", "forget", "purge"])
def test_temporary_origin_invalidates_pending_grants_and_replay_never_reissues(tmp_path, configs, monkeypatch, change):
    now = [1000.0]
    app = create_app(tmp_path, start_paused=True, clock=lambda: now[0])
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        settings = {
            "provider": "openai",
            "model": "temp-model",
            "api_key": "temporary-private-model-marker",
            "ttl_minutes": 15,
        }
        ref = client.put("/api/model-settings", headers=headers, json=settings).json()["credential_ref"]
        body = {**BODY, "credential_ref": ref}
        response = client.post("/api/editor/generate", headers=headers, json=body)
        assert response.status_code == 202, response.text
        job = response.json()
        assert app.state.workflow_authorization.resolve(job)["config"]["api_key"] == settings["api_key"]
        if change == "replace":
            client.put(
                "/api/model-settings", headers=headers, json={**settings, "api_key": settings["api_key"] + "-new"}
            )
        elif change == "forget":
            client.delete("/api/model-settings", headers=headers)
        else:
            now[0] += 900
            app.state.model_settings.purge()
        assert not app.state.workflow_authorization.grants._records
        with pytest.raises(ValueError):
            app.state.workflow_authorization.resolve(job)
        monkeypatch.setattr(
            app.state.workflow_authorization, "capture", lambda *a, **k: pytest.fail("Replay issued grants")
        )
        assert client.post("/api/editor/generate", headers=headers, json=body).json() == job
        assert (
            client.post("/api/editor/generate", headers=headers, json={**body, "prompt": "changed"}).status_code == 409
        )


def test_global_secret_guard_covers_rotations_nested_keys_and_large_public_data(tmp_path, configs):
    from fastapi import HTTPException

    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        assert client.post("/api/editor/generate", headers=headers, json=BODY).status_code == 202
        configs[0]["api_key"] = "rotated-model-key-marker"
        configs[1]["password"] = "rotated-graph-password-marker"
        for secret in (MODEL["api_key"], GRAPH["password"], configs[0]["api_key"], configs[1]["password"]):
            response = client.post(
                "/api/editor/generate",
                headers=headers,
                json={**BODY, "prompt": secret, "idempotency_key": "bad-secret"},
            )
            assert response.status_code == 422
            assert secret not in response.text
            with pytest.raises(HTTPException):
                app.state.model_settings.protect_public({"receipt": [{secret: "nested"}]})
        app.state.model_settings.protect_public({"catalogue": "x" * 100000})
        app.state.editor_execution.protect_workflow({"catalogue": "x" * 100000})


def test_absent_graph_stays_absent_and_required_rejects_without_issue(tmp_path, configs):
    configs[1].clear()
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        response = client.post(
            "/api/editor/generate", headers=headers, json={**BODY, "retrieval_policy": "require_service"}
        )
        assert response.status_code == 503
        assert not app.state.workflow_authorization.grants._records
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        assert job["inputs"]["workflow_authorization"]["retrieval"] is None
        configs[1].update(GRAPH)
        assert app.state.workflow_authorization.resolve(job)["graph_config"] is None
        assert client.post("/api/editor/generate", headers=headers, json=BODY).json() == job
        owner = job["created_by_session_id"]
        assert set(app.state.sessions.get_by_id(owner)) == {"session_id", "expires_at"}
        client.cookies.clear()
        login(client)
        other = client.get("/api/session").json()["session_id"]
        with pytest.raises(ValueError):
            app.state.workflow_authorization.resolve({**job, "created_by_session_id": other})


def test_maintenance_purges_server_grants_at_session_deadline(tmp_path, configs):
    now = [1000.0]
    app = create_app(tmp_path, start_paused=True, clock=lambda: now[0], idle_seconds=30)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        assert job["inputs"]["workflow_authorization"]["model"]["expires_at"] == 1030
        now[0] = 1030
        app.state.model_settings.purge()
        assert not app.state.workflow_authorization.grants._records
        assert app.state.sessions.get_by_id(job["created_by_session_id"]) is None


def test_explicit_replay_does_not_read_current_configuration(tmp_path, configs, monkeypatch):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        monkeypatch.setattr(
            generation, "configuration", lambda: (_ for _ in ()).throw(ValueError("Replay read config"))
        )
        monkeypatch.setattr(
            graph_access, "configuration", lambda: (_ for _ in ()).throw(ValueError("Replay read config"))
        )
        assert client.post("/api/editor/generate", headers=headers, json=BODY).json() == job
        assert (
            client.post("/api/editor/generate", headers=headers, json={**BODY, "prompt": "changed"}).status_code == 409
        )


def test_failed_submission_rolls_back_grants(tmp_path, configs):
    app = create_app(tmp_path, start_paused=True, max_pending=0)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        assert client.post("/api/editor/generate", headers=headers, json=BODY).status_code == 409
        assert not app.state.workflow_authorization.grants._records


def test_acceptance_freezes_two_private_grants_and_resolves_exact_shape(tmp_path, configs):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        response = client.post("/api/editor/generate", headers=headers, json=BODY)
        assert response.status_code == 202, response.text
        job = response.json()
        assert "workflow_authorization" in job["inputs"]
        auth = job["inputs"]["workflow_authorization"]
        assert auth["model"]["capability"] == "model"
        assert auth["retrieval"]["capability"] == "retrieval_read"
        assert app.state.editor_execution.workflow_authorizer(job) == {"config": MODEL, "graph_config": GRAPH}
        assert app.state.editor_execution.workflow_authorizer(job) == {"config": MODEL, "graph_config": GRAPH}
        assert MODEL["api_key"] not in response.text
        assert GRAPH["password"] not in response.text
    assert not app.state.workflow_authorization.grants._records
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert MODEL["api_key"].encode() not in path.read_bytes()
            assert GRAPH["password"].encode() not in path.read_bytes()


@pytest.mark.parametrize(
    "change",
    ["model_key", "model_profile", "model_missing", "graph_key", "graph_profile", "graph_missing", "expiry", "revoke"],
)
def test_dispatch_blocks_changed_origin_or_owner(tmp_path, configs, change):
    now = [1000.0]
    app = create_app(tmp_path, start_paused=True, clock=lambda: now[0])
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        assert app.state.workflow_authorization.resolve(job)["config"] == MODEL
        model, graph = configs
        if change == "model_key":
            model["api_key"] += "-rotated"
        elif change == "model_profile":
            model["model"] = "replacement-model"
        elif change == "model_missing":
            model.clear()
        elif change == "graph_key":
            graph["password"] += "-rotated"
        elif change == "graph_profile":
            graph["database"] = "replacement-db"
        elif change == "graph_missing":
            graph.clear()
        elif change == "expiry":
            now[0] += 180
        else:
            client.delete("/api/session", headers=headers)
            assert not app.state.workflow_authorization.grants._records
        with pytest.raises(ValueError, match="unavailable"):
            app.state.editor_execution.workflow_authorizer(job)
