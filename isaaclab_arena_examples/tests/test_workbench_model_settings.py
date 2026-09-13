# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Temporary credentials: real HTTP boundaries, dummy secrets, no inference."""

import json

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, generation
from isaaclab_arena_examples.tests.test_workbench_editor import ORIGIN, login

KEY = "dummy-private-provider-marker-123456"
BODY = {"provider": "openai", "model": "explicit-test-model", "api_key": KEY}


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    monkeypatch.setattr(generation, "configuration", lambda: None)
    monkeypatch.setattr(generation, "generate", lambda *a, **k: pytest.fail("Unexpected provider invocation"))


def test_settings_authenticated_save_and_forget_never_persist_key(tmp_path):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/model-settings").status_code == 401
        headers = login(client)
        empty = client.get("/api/model-settings").json()
        assert empty["source"] == "none"
        assert empty["session_keys_allowed"] is True
        assert {p["id"] for p in empty["providers"]} == {"openai", "gemini", "openrouter", "nvidia"}
        assert client.put("/api/model-settings", json=BODY).status_code == 403
        saved = client.put("/api/model-settings", headers=headers, json=BODY)
        assert saved.status_code == 200, saved.text
        status = saved.json()
        assert status == {
            **empty,
            "source": "session",
            "configured": True,
            "provider": "openai",
            "model": BODY["model"],
            "expires_at": status["expires_at"],
            "credential_ref": status["credential_ref"],
        }
        assert status["credential_ref"]
        assert KEY not in saved.text
        assert client.get("/api/model-settings").json() == status
        assert client.delete("/api/model-settings", headers=headers).json() == empty
        assert client.get("/api/jobs").json()["jobs"] == []
    assert all(KEY.encode() not in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": KEY},
        {"model": KEY},
        {"model": "prefix/" + KEY},
        {"model": " "},
        {"model": "x" * 257},
        {"api_key": " "},
        {"api_key": "x\ny"},
        {"api_key": "x" * 4097},
        {"base_url": "https://attacker.invalid/"},
        {"api_key": 123},
        {"model": "x\n"},
        {"api_key": "https://api.openai.com/v1"},
        {"api_key": "credential_ref"},
        {"api_key": "session_keys_allowed"},
    ],
)
def test_settings_invalid_inputs_have_generic_errors(tmp_path, changes):
    with TestClient(create_app(tmp_path), base_url=ORIGIN) as client:
        headers = login(client)
        result = client.put("/api/model-settings", headers=headers, json={**BODY, **changes})
        assert result.status_code == 422
        assert result.json() == {"detail": "Invalid request input"}
        assert client.get("/api/model-settings").json()["configured"] is False


@pytest.mark.parametrize(
    "origin, allowed",
    [
        ("http://operator.example:3000", False),
        ("https://operator.example", True),
        ("http://localhost:3000", True),
        ("http://[::1]:3000", True),
    ],
)
def test_settings_transport_uses_configured_origin_not_forwarded_headers(tmp_path, origin, allowed):
    # This runtime's Starlette TestClient cannot parse an IPv6 authority.
    base_url = ORIGIN if "[::1]" in origin else origin
    from urllib.parse import urlsplit

    with TestClient(
        create_app(tmp_path, origin=origin), base_url=base_url, headers={"Host": urlsplit(origin).netloc}
    ) as client:
        session = client.post("/api/sessions", headers={"Origin": origin}, json={}).json()
        headers = {"Origin": origin, "X-CSRF-Token": session["csrf_token"], "X-Forwarded-Proto": "https"}
        assert client.get("/api/model-settings").json()["session_keys_allowed"] is allowed
        assert client.put("/api/model-settings", headers=headers, json=BODY).status_code == (200 if allowed else 403)
        assert (
            client.put("/api/model-settings", headers={**headers, "Host": "evil.invalid"}, json=BODY).status_code == 403
        )
        assert (
            client.put(
                "/api/model-settings", headers={**headers, "Origin": "https://evil.invalid"}, json=BODY
            ).status_code
            == 403
        )


@pytest.mark.parametrize("ttl_minutes", [0, -1, 10, 121, 1440, "30", 30.0, True, None])
def test_invalid_expiration_does_not_replace_existing_key(tmp_path, ttl_minutes):
    with TestClient(create_app(tmp_path), base_url=ORIGIN) as client:
        headers = login(client)
        saved = client.put("/api/model-settings", headers=headers, json=BODY).json()
        response = client.put("/api/model-settings", headers=headers, json={**BODY, "ttl_minutes": ttl_minutes})
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert client.get("/api/model-settings").json() == saved


@pytest.mark.parametrize("ttl_minutes", [15, 30, 60, 120])
@pytest.mark.parametrize("idle_seconds", [86400, 300])
def test_selected_expiration_is_enforced_and_capped_by_session(tmp_path, ttl_minutes, idle_seconds):
    now = [1000.0]
    app = create_app(tmp_path, clock=lambda: now[0], idle_seconds=idle_seconds)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        response = client.put("/api/model-settings", headers=headers, json={**BODY, "ttl_minutes": ttl_minutes})
        assert response.status_code == 200, response.text
        saved = response.json()
        session_id = client.get("/api/session").json()["session_id"]
        deadline = 1000 + min(ttl_minutes * 60, idle_seconds)
        assert saved["expires_at"] == deadline
        now[0] = deadline - 1
        assert client.get("/api/model-settings").json()["expires_at"] == deadline
        now[0] = deadline
        with pytest.raises(ValueError, match="unavailable"):
            app.state.model_settings.resolve(session_id, saved["credential_ref"])
        assert not app.state.model_settings._records


def test_credentials_expire_without_poll_extension_and_clear_on_revoke_shutdown_restart(tmp_path):
    now = [1000.0]
    app = create_app(tmp_path, clock=lambda: now[0])
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        saved = client.put("/api/model-settings", headers=headers, json=BODY).json()
        assert saved["expires_at"] == 2800
        now[0] = 2799
        assert client.get("/api/model-settings").json() == saved
        now[0] = 2800
        assert client.get("/api/model-settings").json()["source"] == "none"
        assert not app.state.model_settings._records
        client.put("/api/model-settings", headers=headers, json=BODY)
        client.delete("/api/session", headers=headers)
        assert not app.state.model_settings._records
        headers = login(client)
        client.put("/api/model-settings", headers=headers, json=BODY)
        cookies = dict(client.cookies)
    assert not app.state.model_settings._records
    with TestClient(create_app(tmp_path, clock=lambda: now[0]), base_url=ORIGIN, cookies=cookies) as client:
        assert client.get("/api/model-settings").json()["source"] == "none"


def test_capacity_and_session_deadline_bound_retention(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import model_settings

    monkeypatch.setattr(model_settings, "MAX_CREDENTIALS", 1)
    now = [1000.0]
    app = create_app(tmp_path, clock=lambda: now[0], idle_seconds=60)
    with TestClient(app, base_url=ORIGIN) as client:
        first = login(client)
        saved = client.put("/api/model-settings", headers=first, json=BODY).json()
        assert saved["expires_at"] == 1060
        client.cookies.clear()
        second = login(client)
        assert client.get("/api/model-settings").json()["source"] == "none"
        assert client.put("/api/model-settings", headers=second, json=BODY).status_code == 409
        now[0] = 1060
        app.state.model_settings.purge()
        assert not app.state.model_settings._records
        client.cookies.clear()
        third = login(client)
        assert client.put("/api/model-settings", headers=third, json=BODY).status_code == 200


@pytest.mark.parametrize("invalidate", ["replace", "forget", "expire", "revoke"])
def test_session_generation_binds_reference_and_invalidated_queue_cannot_fallback(tmp_path, monkeypatch, invalidate):
    import asyncio
    import time

    now = [1000.0]
    app = create_app(tmp_path, clock=lambda: now[0], start_paused=True)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *a, **k: pytest.fail("Invalid ref spawned a worker"))
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        saved = client.put("/api/model-settings", headers=headers, json=BODY).json()
        assert client.get("/api/editor").json()["capabilities"]["generation"] is True
        body = {"prompt": "Move cube", "idempotency_key": "scoped-job", "credential_ref": saved["credential_ref"]}
        response = client.post("/api/editor/generate", headers=headers, json=body)
        assert response.status_code == 202, response.text
        job = response.json()
        assert job["inputs"]["credential_ref"] == saved["credential_ref"]
        assert job["inputs"]["provider"] == "openai"
        assert job["inputs"]["model"] == BODY["model"]
        assert KEY not in response.text
        assert client.post("/api/editor/generate", headers=headers, json=body).json()["id"] == job["id"]
        cookies = dict(client.cookies)
        client.cookies.clear()
        other_headers = login(client)
        assert client.get("/api/editor").json()["capabilities"]["generation"] is False
        assert (
            client.post(
                "/api/editor/generate", headers=other_headers, json={**body, "idempotency_key": "other"}
            ).status_code
            == 409
        )
        client.cookies.clear()
        client.cookies.update(cookies)
        if invalidate == "replace":
            replacement = client.put(
                "/api/model-settings", headers=headers, json={**BODY, "api_key": KEY + "-new"}
            ).json()
            assert replacement["credential_ref"] != saved["credential_ref"]
        elif invalidate == "forget":
            client.delete("/api/model-settings", headers=headers)
        elif invalidate == "expire":
            now[0] = 2800
        else:
            client.delete("/api/session", headers=headers)
            client.cookies.clear()
            headers = login(client)
        monkeypatch.setattr(generation, "configuration", lambda: {"api_key": "dummy-server-key", "model": "server"})
        replay = client.post("/api/editor/generate", headers=headers, json=body)
        assert replay.status_code == 202, replay.text
        assert replay.json() == job
        conflict = client.post("/api/editor/generate", headers=headers, json={**body, "prompt": "Changed"})
        assert conflict.status_code == 409
        assert conflict.json() == {"detail": "Idempotency key already bound to different inputs"}
        assert (
            client.post(
                "/api/editor/generate", headers=headers, json={**body, "idempotency_key": "new-submission"}
            ).status_code
            == 409
        )
        assert len(client.get("/api/jobs").json()["jobs"]) == 1
        assert client.post("/api/jobs/resume-queue", headers=headers).status_code == 200
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["status"] == "failed":
                break
            time.sleep(0.02)
        assert current["status"] == "failed"
        assert KEY not in json.dumps(current)
    assert all(KEY.encode() not in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


@pytest.mark.parametrize("status", ["queued", "succeeded", "failed", "cancelled", "indeterminate"])
def test_generation_replay_after_restart_is_workspace_wide_and_never_reauthorized(tmp_path, monkeypatch, status):
    import asyncio

    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *a, **k: pytest.fail("Replay spawned a worker"))
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        saved = client.put("/api/model-settings", headers=headers, json=BODY).json()
        body = {"prompt": "Original", "idempotency_key": "durable-replay", "credential_ref": saved["credential_ref"]}
        job = client.post("/api/editor/generate", headers=headers, json=body).json()
        if status != "queued":
            app.state.journal.transition(job["id"], status, status, status)
        original = app.state.journal.get_job(job["id"])
    app = create_app(tmp_path, start_paused=True, max_pending=0)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        assert not app.state.model_settings._records
        event_count = app.state.journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        monkeypatch.setattr(app.state.model_settings, "resolve", lambda *a: pytest.fail("Replay authorized a key"))
        replay = client.post("/api/editor/generate", headers=headers, json=body)
        assert replay.status_code == 202, replay.text
        assert replay.json() == original
        for changes in ({"credential_ref": "0" * 64}, {"credential_ref": None}, {"prompt": "Changed"}):
            conflict = client.post("/api/editor/generate", headers=headers, json={**body, **changes})
            assert conflict.status_code == 409
            assert conflict.json() == {"detail": "Idempotency key already bound to different inputs"}
        assert app.state.journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == event_count
        assert len(client.get("/api/jobs").json()["jobs"]) == 1


def test_server_generation_replay_recovers_even_when_server_key_removed(tmp_path, monkeypatch):
    app = create_app(tmp_path, start_paused=True)
    monkeypatch.setattr(generation, "configuration", lambda: {"model": "server"})
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        body = {"prompt": "Original", "idempotency_key": "server-replay"}
        job = client.post("/api/editor/generate", headers=headers, json=body).json()
        monkeypatch.setattr(generation, "configuration", lambda: None)
        assert client.post("/api/editor/generate", headers=headers, json=body).json() == job
        assert (
            client.post(
                "/api/editor/generate", headers=headers, json={**body, "idempotency_key": "new-server-job"}
            ).status_code
            == 503
        )


def test_generation_rejects_credentials_in_prompt_or_metadata_before_journaling(tmp_path):
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        headers = login(client)
        status = client.put("/api/model-settings", headers=headers, json=BODY).json()
        body = {"prompt": KEY, "idempotency_key": "no-key-in-prompt", "credential_ref": status["credential_ref"]}
        response = client.post("/api/editor/generate", headers=headers, json=body)
        assert response.status_code == 422
        assert KEY not in response.text
        assert client.get("/api/jobs").json()["jobs"] == []
        response = client.put(
            "/api/model-settings", headers=headers, json={**BODY, "api_key": KEY + "-new", "model": KEY}
        )
        assert response.status_code == 422
        assert KEY not in response.text
    assert all(KEY.encode() not in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
