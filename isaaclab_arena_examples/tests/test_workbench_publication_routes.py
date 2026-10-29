# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""HTTP through real scheduler/protocol, with a network-denied fake graph SDK."""

import asyncio
import sys
import time

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app
from isaaclab_arena_examples.tests.test_workbench_publication_execution import ready as _ready
from isaaclab_arena_examples.tests.test_workbench_publication_worker import FAKE_CODE

ready = _ready
ORIGIN = "http://127.0.0.1:3000"
BASE = "/api/research/stores/store/publications/effect"


def app_for(ready, tmp_path, code=None, **kwargs):
    ready.attempts.initialize_worker_support()
    return create_app(
        tmp_path,
        start_paused=True,
        clock=lambda: ready.now[0],
        research_roots={"store": tmp_path / "managed"},
        publication_profiles=ready.profiles,
        publication_enabled=True,
        _publication_worker_command=(
            sys.executable,
            "-c",
            code or FAKE_CODE.replace("CLOSE_FAIL", "False").replace("EXPECT_COMMITS", "1"),
        ),
        **kwargs,
    )


def login(client):
    session = client.post("/api/sessions", headers={"Origin": ORIGIN}, json={}).json()
    return {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}


def wait_for(predicate):
    deadline = time.monotonic() + 10
    while not predicate():
        assert time.monotonic() < deadline, "publication timeout"
        time.sleep(0.005)


def test_http_real_child_write_readback_cleanup_and_exact_replay(ready, tmp_path):
    app = app_for(ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        response = client.post(BASE + "/write", headers=headers, json={"request_id": "request"})
        assert response.status_code == 202, response.text
        assert response.json()["accepted_new"]
        location = response.headers["location"]
        assert location == BASE + "/requests/request"
        for _ in range(10):
            assert client.get("/api/health").status_code == 200
        wait_for(lambda: client.get(location).json()["state"]["state"] == "verified")
        run = app.state.publication_scheduler
        assert run.worker_count == 1
        assert not run.attempts["store"].pending_workers()
        app.state.publication_authorization.clear()
        replay = client.post(BASE + "/write", headers=headers, json={"request_id": "request"})
        assert replay.status_code == 202
        assert replay.json()["accepted"] == response.json()["accepted"]
        assert replay.json()["accepted_new"] is False
        assert run.worker_count == 1
        assert not app.state.publication_authorization._records
        assert "fake-private-publication-password" not in str(client.get(location).json())


def test_cancelled_write_then_explicit_reconcile_without_second_write(ready, tmp_path):
    saved = tmp_path / "graph.json"
    code = FAKE_CODE.replace("CLOSE_FAIL", "False").replace("EXPECT_COMMITS", "1")
    code = code.replace(
        "    def close():",
        f"    def close():\n        open({str(saved)!r}, 'w').write(json.dumps([driver.nodes, driver.edges]))\n       "
        " import time\n        time.sleep(60)",
    )
    app = app_for(ready, tmp_path, code)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        accepted = client.post(BASE + "/write", headers=headers, json={"request_id": "request"}).json()["accepted"]
        wait_for(saved.exists)
        body = {k: accepted[k] for k in ("request_id", "attempt_id", "generation")}
        stale = client.post(BASE + "/cancel", headers=headers, json=dict(body, generation=99))
        assert stale.status_code == 409
        assert client.post(BASE + "/cancel", headers=headers, json=body).json()["cancelled"] is True
        assert client.get(BASE, params={"request_id": "request"}).json()["state"]["state"] == "unknown"
        run = app.state.publication_scheduler
        read = FAKE_CODE.replace("CLOSE_FAIL", "False").replace("EXPECT_COMMITS", "0")
        read = read.replace(
            "    def close():", f"    driver.nodes, driver.edges = json.load(open({str(saved)!r}))\n    def close():"
        )
        run.command = (sys.executable, "-c", read)
        response = client.post(
            BASE + "/reconcile", headers=headers, json={"request_id": "read", "previous_request_id": "request"}
        )
        assert response.status_code == 202, response.text
        wait_for(lambda: client.get(response.headers["location"]).json()["state"]["state"] == "verified")
        assert run.worker_count == 2
        assert not run.attempts["store"].pending_workers()


def test_wrong_owner_new_request_never_issues_grant(ready, tmp_path, monkeypatch):
    app = app_for(ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        first = client.post(BASE + "/write", headers=headers, json={"request_id": "request"})
        client.cookies.clear()
        other = login(client)
        calls = []
        original = app.state.publication_authorization.issue

        def issue(*a, **kw):
            calls.append(1)
            return original(*a, **kw)

        monkeypatch.setattr(app.state.publication_authorization, "issue", issue)
        assert client.get(first.headers["location"]).status_code == 409
        assert client.post(BASE + "/write", headers=other, json={"request_id": "other"}).status_code == 409
        assert not calls


def test_renew_retained_acceptance_after_bind_failure(ready, tmp_path, monkeypatch):
    app = app_for(ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        auth = app.state.publication_authorization
        original = auth.bind_attempt
        monkeypatch.setattr(auth, "bind_attempt", lambda *a: (_ for _ in ()).throw(ValueError("private")))
        response = client.post(BASE + "/write", headers=headers, json={"request_id": "request"})
        assert response.status_code == 202
        assert response.json()["state"]["state"] == "blocked_authorization"
        monkeypatch.setattr(auth, "bind_attempt", original)
        renewed = client.post(
            BASE + "/renew", headers=headers, json={"request_id": "renew", "previous_request_id": "request"}
        )
        assert renewed.status_code == 202, renewed.text
        wait_for(lambda: client.get(renewed.headers["location"]).json()["state"]["state"] == "verified")


@pytest.mark.parametrize(
    "case", ["csrf", "origin", "missing_origin", "store", "payload", "command", "credentials", "driver", "identifier"]
)
def test_http_boundaries_before_admission(ready, tmp_path, case):
    app = app_for(ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        body, url = {"request_id": "request"}, BASE + "/write"
        expected = 422
        if case == "csrf":
            headers["X-CSRF-Token"] = "wrong"
            expected = 403
        elif case == "origin":
            headers["Origin"] = "https://evil.invalid"
            expected = 403
        elif case == "missing_origin":
            headers.pop("Origin")
            expected = 403
        elif case == "store":
            url = url.replace("/store/", "/wrong/")
            expected = 409
        elif case == "identifier":
            body["request_id"] = "../request"
        else:
            body[case] = "private"
        response = client.post(url, headers=headers, json=body)
        assert response.status_code == expected
        assert app.state.publication_scheduler.worker_count == 0
        assert not app.state.publication_authorization._records
        assert ready.attempts.get_acceptance("request") is None


def test_disabled_routes_never_open_store_or_worker_schema(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore

    def denied(*a, **kw):
        pytest.fail("disabled publication touched managed storage")

    monkeypatch.setattr(ResearchStore, "open", denied)
    monkeypatch.setattr(PublicationAttempts, "worker_support_ready", denied)
    app = create_app(tmp_path, research_roots={"store": tmp_path / "absent"})
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        assert client.get(BASE + "/requests/request").status_code == 503
        for operation in ("write", "renew", "reconcile", "cancel"):
            assert (
                client.post(BASE + "/" + operation, headers=headers, json={"request_id": "request"}).status_code == 503
            )
    assert not (tmp_path / "absent").exists()


def test_enabled_missing_worker_schema_never_initializes(ready, tmp_path):
    before = list(ready.journal.db.execute("SELECT name, sql FROM sqlite_master WHERE name LIKE 'publication_%'"))
    app = create_app(
        tmp_path,
        publication_enabled=True,
        publication_profiles=ready.profiles,
        research_roots={"store": tmp_path / "managed"},
    )

    async def scenario():
        before_tasks = asyncio.all_tasks()
        with pytest.raises(ValueError, match="worker schema not initialized"):
            async with app.router.lifespan_context(app):
                pytest.fail("missing schema admitted startup")
        assert not app.state.publication_profiles
        assert not app.state.publication_authorization._records
        assert not app.state.workflow_authorization.grants._records
        assert not app.state.model_settings._records
        assert app.state._cleanup.closed
        assert not app.state._cleanup.stores
        assert not (asyncio.all_tasks() - before_tasks)

    asyncio.run(scenario())
    assert (
        list(ready.journal.db.execute("SELECT name, sql FROM sqlite_master WHERE name LIKE 'publication_%'")) == before
    )


def test_shutdown_inflight_cleans_before_profiles_and_journal(ready, tmp_path, monkeypatch):
    entered = tmp_path / "entered"
    code = FAKE_CODE.replace(
        "raise SystemExit(main(driver_factory=factory))",
        f"import time\nopen({str(entered)!r}, 'w').close()\ntime.sleep(60)",
    )
    app = app_for(ready, tmp_path, code)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        assert client.post(BASE + "/write", headers=headers, json={"request_id": "request"}).status_code == 202
        wait_for(entered.exists)
        run = app.state.publication_scheduler
        dispatch = run._slots["request"]
        original = run.recover

        async def recover():
            assert app.state.publication_profiles, "recovery must precede clearing profiles"
            assert not app.state.publication_admitting
            return await original()

        monkeypatch.setattr(run, "recover", recover)
    assert dispatch.process.returncode is not None
    assert not run._slots
    assert not ready.attempts.pending_workers()
    assert not app.state.publication_profiles


def test_post_accept_state_unavailable_retains_location(ready, tmp_path, monkeypatch):
    app = app_for(ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        run = app.state.publication_scheduler

        def fail(*a, **kw):
            raise ValueError("private observation failure")

        original = run.attempts["store"].get_state

        def bind(*a):
            monkeypatch.setattr(run.attempts["store"], "get_state", fail)
            monkeypatch.setattr(run, "_pause", fail)
            fail()

        monkeypatch.setattr(app.state.publication_authorization, "bind_attempt", bind)
        response = client.post(BASE + "/write", headers=headers, json={"request_id": "request"})
        assert response.status_code == 202
        assert response.headers["location"] == BASE + "/requests/request"
        assert response.json()["disposition"] == "accepted_state_unavailable"
        assert response.json()["state"] is None
        assert response.json()["accepted"] == ready.attempts.get_acceptance("request")
        monkeypatch.setattr(run.attempts["store"], "get_state", original)


@pytest.mark.parametrize("missing", ["roots", "profiles"])
def test_enabled_requires_explicit_configuration(tmp_path, missing):
    kwargs = {"publication_enabled": True}
    if missing == "profiles":
        kwargs["research_roots"] = {"store": tmp_path / "absent"}
    with pytest.raises(ValueError, match="requires configured stores and profiles"):
        create_app(tmp_path, **kwargs)
    assert not (tmp_path / "journal.sqlite3").exists()


def test_shutdown_failure_retains_resources_and_unclean_marker(ready, tmp_path, monkeypatch):
    app = app_for(ready, tmp_path)

    async def scenario():
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        scheduler = app.state.publication_scheduler
        original = scheduler.stop

        async def fail():
            raise RuntimeError("cleanup pending")

        monkeypatch.setattr(scheduler, "stop", fail)
        try:
            with pytest.raises(RuntimeError, match="cleanup pending"):
                await context.__aexit__(None, None, None)
            assert not app.state.publication_admitting
            assert app.state.publication_profiles
            assert (
                app.state.journal.db.execute("SELECT value FROM metadata WHERE key='clean_shutdown'").fetchone()[0] == 0
            )
            assert scheduler.stores["store"].get_reservation(ready.commit["reservation"]["reservation_id"])
        finally:
            monkeypatch.setattr(scheduler, "stop", original)
            await app.state._cleanup.retry()

    asyncio.run(scenario())


def test_capacity_error_static_and_replay_no_enqueue(ready, tmp_path, monkeypatch):
    app = app_for(ready, tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        run = app.state.publication_scheduler
        calls = []

        async def queued(request_id):
            calls.append(request_id)

        monkeypatch.setattr(run, "enqueue", queued)
        run.capacity = 1
        assert client.post(BASE + "/write", headers=headers, json={"request_id": "request"}).status_code == 202
        replay = client.post(BASE + "/write", headers=headers, json={"request_id": "request"})
        assert replay.status_code == 202
        assert not replay.json()["accepted_new"]
        response = client.post(BASE + "/write", headers=headers, json={"request_id": "other"})
        assert response.status_code == 409
        assert response.json() == {"detail": "Publication admission unavailable or conflicting"}
        assert calls == ["request"]
        client.cookies.clear()
        other = login(client)
        assert client.post(BASE + "/write", headers=other, json={"request_id": "request"}).status_code == 409
        body = {k: replay.json()["accepted"][k] for k in ("request_id", "attempt_id", "generation")}
        assert client.post(BASE + "/cancel", headers=other, json=body).status_code == 409
        assert run._slots["request"] is not None
