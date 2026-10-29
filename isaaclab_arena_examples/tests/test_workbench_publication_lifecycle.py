# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Publication grant lifecycle with real API sessions and no external calls."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from isaaclab_arena.agentic_environment_generation.workbench.research_registry import digest
from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app
from isaaclab_arena_examples.tests.test_workbench_editor import ORIGIN, login
from isaaclab_arena_examples.tests.test_workbench_publication_authorization import intent, setup


@pytest.mark.parametrize("change", ["session_expiry", "grant_expiry", "rotation"])
def test_idle_maintenance_purges_publication_grants(tmp_path, change):
    _, _, profiles, now = setup()
    app = create_app(
        tmp_path,
        start_paused=True,
        publication_profiles=profiles,
        clock=lambda: now[0],
        idle_seconds=60 if change == "session_expiry" else 1000,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        login(client)
        session, _ = app.state.sessions.create()
        auth = app.state.publication_authorization
        auth.issue(session, intent(auth), "request", "graph_read")
        if change == "rotation":
            app.state.publication_profiles["graph"]["connection"]["password"] = "rotated-private-marker-1234"
        else:
            now[0] += 60 if change == "session_expiry" else 180
        # Same synchronous tick used by maintain(), without any browser activity.
        app.state.model_settings.purge()
        assert auth._records == {}


@pytest.mark.parametrize("surface", ["request", "candidate", "get"])
def test_unused_publication_secret_guard_is_wired(tmp_path, surface):
    _, _, profiles, _ = setup()
    secret = profiles["graph"]["connection"]["password"]
    app = create_app(
        tmp_path, start_paused=True, publication_profiles=profiles, research_roots={secret: tmp_path / "absent"}
    )
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        assert app.state.publication_authorization._records == {}
        if surface == "request":
            response = client.post(
                "/api/editor/generate",
                headers=headers,
                json={"operation": "new", "prompt": secret, "idempotency_key": "bad"},
            )
        elif surface == "get":
            response = client.get("/api/research/stores")
        else:
            value = {"receipt": {"yaml_text": secret}}
            with pytest.raises(HTTPException) as caught:
                app.state.editor_execution.protect_workflow(value)
            assert caught.value.status_code == 422
            assert caught.value.detail == "Invalid request input"
            assert value == {"receipt": {"yaml_text": secret}}
            return
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}


def test_session_revokes_graph_grants_but_model_forget_does_not(tmp_path):
    profiles = {
        "primary": {
            "connection": {
                "uri": "bolt://127.0.0.1:7687",
                "user": "neo4j",
                "database": "neo4j",
                "password": "synthetic-graph-private-value",
            },
            "immutable_scope": True,
        }
    }
    app = create_app(tmp_path, publication_profiles=profiles)
    with TestClient(app, base_url="http://127.0.0.1:3000") as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": "http://127.0.0.1:3000"}).json()
        authority = app.state.publication_authorization
        payload = {"artifact": "projection.json"}
        intent = {
            "effect_id": "effect",
            "target_profile": authority.profile_metadata("primary"),
            "payload": payload,
            "payload_sha256": digest(payload),
        }
        metadata = authority.issue(session, intent, "request", "graph_write")
        authority.bind_attempt(metadata, "attempt", 1)
        binding = dict(
            capability="graph_write", effect_id="effect", request_id="request", attempt_id="attempt", generation=1
        )
        app.state.model_settings.forget(session["session_id"])
        assert authority.resolve(metadata, **binding)[1] == metadata
        response = client.delete(
            "/api/session", headers={"Origin": "http://127.0.0.1:3000", "X-CSRF-Token": session["csrf_token"]}
        )
        assert response.status_code == 200
        with pytest.raises(ValueError):
            authority.resolve(metadata, **binding)


@pytest.mark.parametrize(
    "profiles",
    [
        [],
        False,
        {"bad/id": {}},
        {"p": {"connection": {}, "immutable_scope": True}},
        {"p": {"connection": {}, "immutable_scope": 1}},
        {str(i): {} for i in range(17)},
    ],
)
def test_invalid_profiles_fail_before_lifecycle(tmp_path, profiles):
    state = tmp_path / "not-created"
    with pytest.raises(ValueError):
        create_app(state, publication_profiles=profiles)
    assert not state.exists()


def test_profiles_are_detached_bounded_and_never_lookup_environment(tmp_path, monkeypatch):
    import socket

    from isaaclab_arena_examples.agentic_environment_generation.web_api import graph_access
    from isaaclab_arena_examples.agentic_environment_generation.web_api.research_profiles import (
        configured_publication_profiles,
    )

    _, _, profiles, _ = setup()
    monkeypatch.setattr(graph_access, "configuration", lambda: pytest.fail("Implicit environment lookup"))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("Network lookup"))
    app = create_app(tmp_path, publication_profiles=profiles)
    profiles["graph"]["connection"]["password"] = "operator-replacement-private-value"
    assert app.state.publication_profiles != profiles
    assert len(configured_publication_profiles({str(i): profiles["graph"] for i in range(16)})) == 16
    assert create_app(tmp_path / "default").state.publication_profiles == {}
    assert not tmp_path.joinpath("journal.sqlite3").exists()
    for change in (
        {"immutable_scope": 1},
        {"immutable_scope": False},
        {"extra": "private"},
        {"connection": {**profiles["graph"]["connection"], "uri": "https://invalid.example"}},
        {"connection": {**profiles["graph"]["connection"], "password": "x" * 4097}},
        {"connection": {**profiles["graph"]["connection"], "user": "bad\nuser"}},
    ):
        with pytest.raises(ValueError, match="^Invalid publication profile configuration$"):
            configured_publication_profiles({"graph": {**profiles["graph"], **change}})


def test_unused_secret_in_durable_candidate_cannot_be_saved(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
    from isaaclab_arena_examples.tests.test_workbench_research_store import candidate

    _, _, profiles, _ = setup()
    secret = profiles["graph"]["connection"]["password"]
    app = create_app(
        tmp_path / "state",
        start_paused=True,
        publication_profiles=profiles,
        research_roots={"primary": tmp_path / "managed"},
    )
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        source, _ = candidate(app.state.journal, receipt_change=lambda receipt: receipt.update(marker=secret))
        with ResearchStore.create(
            app.state.journal, tmp_path / "managed", "primary", protect_public=app.state.model_settings.protect_public
        ):
            pass
        response = client.post(
            "/api/research/stores/primary/versions",
            headers=headers,
            json={
                "idempotency_key": "save",
                "family": "a2",
                "source_job_id": source["job_id"],
                "source_attempt_id": source["attempt_id"],
                "source_generation": source["generation"],
            },
        )
        assert response.status_code == 422, response.text
        assert secret not in response.text
        assert client.get("/api/research/stores/primary/versions?family=a2").json()["versions"] == []


def test_shutdown_clears_owned_publication_secrets(tmp_path):
    profiles = {
        "primary": {
            "connection": {
                "uri": "bolt://127.0.0.1:7687",
                "user": "neo4j",
                "database": "neo4j",
                "password": "synthetic-graph-private-value",
            },
            "immutable_scope": True,
        }
    }
    app = create_app(tmp_path, publication_profiles=profiles)
    with TestClient(app, base_url="http://127.0.0.1:3000") as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": "http://127.0.0.1:3000"}).json()
        authority = app.state.publication_authorization
        payload = {"artifact": "projection.json"}
        intent = {
            "effect_id": "effect",
            "target_profile": authority.profile_metadata("primary"),
            "payload": payload,
            "payload_sha256": digest(payload),
        }
        authority.issue(session, intent, "request", "graph_read")
        owned_records = authority._records
        owned_profiles = app.state.publication_profiles
        assert len(owned_records) == 1
    assert owned_records == {}
    assert owned_profiles == {}
    assert "primary" in profiles  # Caller-owned configuration is not mutated.
