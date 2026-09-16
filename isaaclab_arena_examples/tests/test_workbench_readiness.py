# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Readiness is explicit configuration evidence, never a generated or simulated result."""

import socket

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import (
    create_app,
    editor_execution,
    generation,
    graph_access,
)

ORIGIN = "http://127.0.0.1:3000"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(editor_execution, "make_snapshot_service", lambda _root: None)
    monkeypatch.setattr(generation, "configuration", lambda: None)
    monkeypatch.setattr(graph_access, "configuration", lambda: None)
    monkeypatch.setattr(socket.socket, "connect", lambda *args: pytest.fail("Unexpected network probe"))
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        yield client


def login(client):
    session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
    return {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}


def test_readiness_reports_missing_configuration_without_network_or_jobs(client):
    headers = login(client)
    before = client.get("/api/workspaces/default").json()
    response = client.get("/api/editor/readiness")
    assert response.status_code == 200
    result = response.json()
    assert result["schema_version"] == 1
    assert result["provider"] == {"configured": False, "source": "none", "verification": "not_checked"}
    assert result["graph"] == {"configured": False, "status": "not_configured"}
    assert result["runtime"]["simulation"] == "not_checked"
    assert result["workflow"]["scenario_harness"] == "cli_only"
    assert result["workflow"]["evaluation_scope"] == "droid_fixed_profiles"
    assert result["workflow"]["research_versions"] is False
    assert all(row["status"] == "not_checked" for row in result["policy_servers"])
    assert client.get("/api/workspaces/default").json() == before
    assert client.post("/api/editor/readiness/check", json={}).status_code == 403
    assert (
        client.post("/api/editor/readiness/check", headers=headers, json={"uri": "http://untrusted"}).status_code == 422
    )


def test_explicit_checks_use_server_targets_without_provider_calls_or_job_writes(client, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    secret = "synthetic-provider-secret"
    saved = client.put(
        "/api/model-settings", headers=headers, json={"provider": "openai", "model": "test-model", "api_key": secret}
    )
    assert saved.status_code == 200
    config = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "operator",
        "password": "synthetic-graph-secret",
        "database": "research",
    }
    monkeypatch.setattr(graph_access, "configuration", lambda: config)
    calls = []
    monkeypatch.setattr(readiness, "probe_graph", lambda actual: calls.append(actual) or "available")
    monkeypatch.setattr(readiness, "probe_policy", lambda row: "unreachable")
    before = client.get("/api/workspaces/default").json()
    result = client.post("/api/editor/readiness/check", headers=headers, json={})
    assert result.status_code == 200
    assert calls == [config]
    assert result.json()["provider"] == {"configured": True, "source": "session", "verification": "not_checked"}
    assert result.json()["graph"] == {"configured": True, "status": "available"}
    assert result.json()["checked_at"] is not None
    assert all(row["status"] == "unreachable" for row in result.json()["policy_servers"])
    assert secret not in result.text and config["password"] not in result.text
    assert client.get("/api/workspaces/default").json() == before
    assert client.get("/api/editor/readiness").json()["graph"]["status"] == "not_checked"
    assert calls == [config]


def test_readiness_does_not_relabel_old_graph_probe_after_configuration_change(client, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    config = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "operator",
        "password": "synthetic-graph-secret",
        "database": "research",
    }
    monkeypatch.setattr(graph_access, "configuration", lambda: config)

    def change(_config):
        monkeypatch.setattr(graph_access, "configuration", lambda: None)
        return "available"

    monkeypatch.setattr(readiness, "probe_graph", change)
    monkeypatch.setattr(readiness, "probe_policy", lambda row: "unreachable")
    result = client.post("/api/editor/readiness/check", headers=headers, json={}).json()
    assert result["graph"] == {"configured": False, "status": "configuration_changed"}


def test_revoked_session_cannot_receive_completed_check(client, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    token = client.cookies.get(client.app.state.cookie_name)

    def revoke(_config):
        client.app.state.sessions.revoke(token)
        return "available"

    monkeypatch.setattr(readiness, "probe_graph", revoke)
    monkeypatch.setattr(readiness, "probe_policy", lambda row: "unreachable")
    assert client.post("/api/editor/readiness/check", headers=headers, json={}).status_code == 401


def test_graph_probe_uses_explicit_database_read_and_rolls_back(monkeypatch):
    from unittest.mock import MagicMock

    from isaaclab_arena.agentic_environment_generation import lpg_neo4j_sync
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    driver = MagicMock()
    factory = MagicMock(return_value=driver)
    monkeypatch.setattr(lpg_neo4j_sync, "get_neo4j_driver", factory)
    transaction = (
        driver.session.return_value.__enter__.return_value.begin_transaction.return_value.__enter__.return_value
    )
    transaction.run.return_value.single.return_value = {"ready": 1}
    config = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "operator",
        "password": "synthetic-secret",
        "database": "research",
    }
    assert readiness.probe_graph(config) == "available"
    driver.session.assert_called_once_with(database="research", default_access_mode="READ")
    transaction.run.assert_called_once_with("RETURN 1 AS ready")
    transaction.rollback.assert_called_once()
    driver.close.assert_called_once()
    assert factory.call_args.kwargs["uri"] == config["uri"]
    assert factory.call_args.kwargs["max_transaction_retry_time"] == 0
    factory.reset_mock()
    assert readiness.probe_graph(None) == "not_configured"
    factory.assert_not_called()


def test_graph_probe_never_returns_raw_driver_errors(monkeypatch):
    from unittest.mock import MagicMock

    from neo4j.exceptions import AuthError

    from isaaclab_arena.agentic_environment_generation import lpg_neo4j_sync
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    config = {
        "uri": "bolt://127.0.0.1:7688",
        "user": "operator",
        "password": "synthetic-secret",
        "database": "research",
    }
    monkeypatch.setattr(lpg_neo4j_sync, "get_neo4j_driver", MagicMock(side_effect=AuthError(config["password"])))
    assert readiness.probe_graph(config) == "authentication_failed"
    monkeypatch.setattr(lpg_neo4j_sync, "get_neo4j_driver", MagicMock(side_effect=RuntimeError(config["password"])))
    assert readiness.probe_graph(config) == "unavailable"


@pytest.mark.parametrize("database", [" research ", "a" * 129])
def test_graph_readiness_rejects_retriever_incompatible_database_before_probe(client, monkeypatch, database):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    login(client)
    config = {"uri": "bolt://127.0.0.1:7688", "user": "operator", "password": "synthetic-secret", "database": database}
    monkeypatch.setattr(graph_access, "configuration", lambda: config)
    assert client.get("/api/editor/readiness").json()["graph"] == {
        "configured": True,
        "status": "invalid_configuration",
    }
    assert readiness.probe_graph(config) == "invalid_configuration"


@pytest.mark.parametrize("wait_for_http_timeout", [False, True])
def test_busy_probe_retains_slot_until_thread_finishes(client, monkeypatch, wait_for_http_timeout):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    headers = login(client)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(readiness, "_PROBE_SLOT", threading.BoundedSemaphore(1))

    def blocked(_config):
        entered.set()
        assert release.wait(15), "Probe fixture was not released"
        return "not_configured"

    original = readiness.probe_dependencies

    def tracked(config):
        try:
            return original(config)
        finally:
            finished.set()

    monkeypatch.setattr(readiness, "probe_graph", blocked)
    monkeypatch.setattr(readiness, "probe_policy", lambda row: "unreachable")
    monkeypatch.setattr(readiness, "probe_dependencies", tracked)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(client.post, "/api/editor/readiness/check", headers=headers, json={})
        try:
            assert entered.wait(3)
            assert client.post("/api/editor/readiness/check", headers=headers, json={}).status_code == 429
            if wait_for_http_timeout:
                timed_out = pending.result(timeout=12)
                assert timed_out.status_code == 200
                assert timed_out.json()["graph"]["status"] == "timeout"
                assert not finished.is_set()
                assert client.post("/api/editor/readiness/check", headers=headers, json={}).status_code == 429
        finally:
            release.set()
        assert finished.wait(3)
        assert pending.result(timeout=3).status_code == 200
    assert client.post("/api/editor/readiness/check", headers=headers, json={}).status_code == 200


def test_cancelled_request_does_not_release_running_probe_slot(monkeypatch):
    """Exercise actual coroutine cancellation with a blocked, mocked dependency thread."""
    import asyncio
    import threading

    from fastapi import HTTPException

    from isaaclab_arena_examples.agentic_environment_generation.web_api import readiness

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(readiness, "_PROBE_SLOT", threading.BoundedSemaphore(1))
    monkeypatch.setattr(graph_access, "configuration", lambda: None)
    monkeypatch.setattr(readiness, "require_session", lambda request: {})
    monkeypatch.setattr(readiness, "metadata", lambda *args: {"graph": {}, "policy_servers": [{}, {}]})
    monkeypatch.setattr(readiness, "protect_public_record", lambda request, value: value)

    def blocked(_config):
        entered.set()
        assert release.wait(5)
        return "not_configured"

    original = readiness.probe_dependencies

    def tracked(config):
        try:
            return original(config)
        finally:
            finished.set()

    monkeypatch.setattr(readiness, "probe_graph", blocked)
    monkeypatch.setattr(readiness, "probe_policy", lambda row: "unreachable")
    monkeypatch.setattr(readiness, "probe_dependencies", tracked)

    async def run():
        task = asyncio.create_task(readiness.check(None, readiness.CheckInput(), session={}))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(HTTPException) as busy:
                await readiness.check(None, readiness.CheckInput(), session={})
            assert busy.value.status_code == 429
            assert not finished.is_set()
        finally:
            release.set()
        assert await asyncio.to_thread(finished.wait, 2)
        result = await readiness.check(None, readiness.CheckInput(), session={})
        assert result["graph"]["status"] == "not_configured"

    asyncio.run(run())
