# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Workbench HTTP contract tests in the supported Arena runtime."""

from fastapi.testclient import TestClient

ORIGIN = "http://127.0.0.1:3000"


def test_localhost_session_matches_request_origin_without_weakening_boundary(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    local = "http://localhost:3000"
    with TestClient(create_app(tmp_path, origin=ORIGIN), base_url=local) as client:
        assert client.get("/api/health").status_code == 200
        assert client.post("/api/sessions", json={}).status_code == 403
        response = client.post("/api/sessions", json={}, headers={"Origin": local})
        assert response.status_code == 200
        assert "Domain=" not in response.headers["set-cookie"]
        session = response.json()
        assert client.get("/api/session").json() == session
        assert client.get("/api/workspaces/default").status_code == 200
        assert client.post("/api/session/activity", headers={"Origin": local}).status_code == 403
        headers = {"Origin": local, "X-CSRF-Token": session["csrf_token"]}
        assert client.post("/api/session/activity", json={}, headers=headers).status_code == 200
        for foreign in (ORIGIN, "http://localhost:3001", "https://localhost:3000", "http://evil.test", "null"):
            assert client.post("/api/sessions", json={}, headers={"Origin": foreign}).status_code == 403
        for host in ("evil.test:3000", "localhost.evil.test:3000", "127.0.0.2:3000", "localhost:3001"):
            assert client.get("/api/health", headers={"Host": host}).status_code == 403
        assert client.delete("/api/session", headers=headers).status_code == 200
        assert client.get("/api/session").status_code == 401


def test_numeric_loopback_alias_and_nonlocal_origin_isolation(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    with TestClient(create_app(tmp_path / "local", origin="http://localhost:3000"), base_url=ORIGIN) as client:
        assert client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).status_code == 200
    custom = "https://workbench.example:8443"
    with TestClient(create_app(tmp_path / "custom", origin=custom), base_url=custom) as client:
        assert client.post("/api/sessions", json={}, headers={"Origin": custom}).status_code == 200
        for host in ("localhost:8443", "127.0.0.1:8443", "workbench.example:3000"):
            assert client.get("/api/health", headers={"Host": host}).status_code == 403


def test_sessions_are_durable_origin_bound_revocable_and_expire(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    now = [1000.0]
    app = create_app(tmp_path, origin=ORIGIN, clock=lambda: now[0], idle_seconds=10, absolute_seconds=25)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/health").json() == {
            "status": "ok",
            "capabilities": {"diagnostic": False, "generation": False, "preview": False},
        }
        assert client.get("/api/session").status_code == 401
        assert client.post("/api/sessions", json={}).status_code == 403
        assert client.post("/api/sessions", json={}, headers={"Origin": "http://evil.test"}).status_code == 403
        response = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api" in cookie
        session = response.json()
        assert session["expires_at"] == 1010
        assert client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json() == session
        assert client.get("/api/session", headers={"Host": "evil.test"}).status_code == 403
        assert client.post("/api/session/activity", headers={"Origin": ORIGIN}).status_code == 403
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        cookies = client.cookies
    with TestClient(
        create_app(tmp_path, origin=ORIGIN, clock=lambda: now[0], idle_seconds=10, absolute_seconds=25), base_url=ORIGIN
    ) as client:
        client.cookies.update(cookies)
        now[0] = 1008
        assert client.get("/api/session").json() == session  # Polling is not activity.
        assert client.post("/api/session/activity", headers=headers).json()["expires_at"] == 1018
        now[0] = 1017
        assert client.post("/api/session/activity", headers=headers).json()["expires_at"] == 1025
        now[0] = 1025
        assert client.get("/api/session").status_code == 401
        replacement = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        assert replacement["session_id"] != session["session_id"]
        headers["X-CSRF-Token"] = replacement["csrf_token"]
        assert client.delete("/api/session", headers=headers).status_code == 200
        assert client.get("/api/session").status_code == 401


def test_job_submission_bounds_idempotency_and_queued_cancellation(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    body = {
        "workspace_id": "default",
        "kind": "diagnostic",
        "idempotency_key": "first",
        "inputs": {"steps": 2, "delay_seconds": 0.1},
    }
    with TestClient(create_app(tmp_path), base_url=ORIGIN) as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        assert client.post("/api/jobs", json=body, headers=headers).status_code == 422
    with TestClient(create_app(tmp_path, diagnostics=True, start_paused=True), base_url=ORIGIN) as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        assert client.post("/api/jobs", json=body).status_code == 403
        result = client.post("/api/jobs", json=body, headers=headers)
        assert result.status_code == 202
        job = result.json()
        assert job["inputs"] == body["inputs"] and job["status"] == "queued"
        assert client.post("/api/jobs", json=body, headers=headers).json() == job
        assert client.get("/api/workspaces/default").json() == {
            "id": "default",
            "name": "Arena workspace",
            "jobs": [job],
            "event_cursor": 1,
        }
        assert client.get("/api/jobs").json() == {"jobs": [job], "event_cursor": 1}
        assert client.get(f"/api/jobs/{job['id']}").json() == job
        assert client.get("/api/jobs/no-such-job").status_code == 404
        changed = {**body, "inputs": {"steps": 3, "delay_seconds": 0.1}}
        assert client.post("/api/jobs", json=changed, headers=headers).status_code == 409
        for invalid in [
            {**body, "kind": "generation"},
            {**body, "workspace_id": "../../etc"},
            {**body, "command": "ls"},
            {**body, "idempotency_key": ""},
            {**body, "idempotency_key": "x" * 129},
            *[
                {**body, "inputs": inputs}
                for inputs in (
                    {"steps": 0, "delay_seconds": 0.1},
                    {"steps": 11, "delay_seconds": 0.1},
                    {"steps": True, "delay_seconds": 0.1},
                    {"steps": "2", "delay_seconds": 0.1},
                    {"steps": 2, "delay_seconds": 0.01},
                    {"steps": 2, "delay_seconds": 5.1},
                    {"steps": 2, "delay_seconds": 0.1, "secret": "not-a-real-key"},
                )
            ],
        ]:
            response = client.post("/api/jobs", json=invalid, headers=headers)
            assert response.status_code == 422, response.text
            assert isinstance(response.json()["detail"], str)
            assert "not-a-real-key" not in response.text
        assert client.post("/api/jobs", content=b"x" * 20000, headers=headers).status_code == 413
        client.delete("/api/session", headers=headers)
        replacement = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        headers["X-CSRF-Token"] = replacement["csrf_token"]
        assert client.post("/api/jobs", json=body, headers=headers).json() == job
        cancelled = client.post(f"/api/jobs/{job['id']}/cancel", headers=headers).json()
        assert cancelled["status"] == "cancelled"
        assert client.post(f"/api/jobs/{job['id']}/cancel", headers=headers).json() == cancelled
        assert client.get("/api/jobs").json()["event_cursor"] == 2


def test_real_diagnostic_subprocess_progress_and_verified_receipt(tmp_path):
    import time

    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    app = create_app(tmp_path, diagnostics=True)
    with TestClient(app, base_url=ORIGIN) as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        result = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "workspace_id": "default",
                "kind": "diagnostic",
                "idempotency_key": "real-worker",
                "inputs": {"steps": 2, "delay_seconds": 0.2},
            },
        )
        job = result.json()
        observed = []
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            observed.append(current["status"])
            assert client.get("/api/health").status_code == 200
            if current["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.02)
        assert current["status"] == "succeeded", current
        assert "running" in observed
        assert current["result"] == {"diagnostic": True, "completed_steps": 2}
        events = app.state.journal.events_after(0)
        assert [event["kind"] for event in events] == [
            "queued",
            "started",
            "stage_changed",
            "stage_changed",
            "stage_changed",
            "stage_changed",
            "stage_changed",
            "succeeded",
        ]
        assert [event["job"]["stage"] for event in events] == [
            "queued",
            "worker_starting",
            "diagnostic_ready",
            "diagnostic_step_1_started",
            "diagnostic_step_1_completed",
            "diagnostic_step_2_started",
            "diagnostic_step_2_completed",
            "completed",
        ]
        assert events[-1]["job"] == current


def test_active_cancel_acknowledges_process_exit_before_terminal_state(tmp_path):
    import os
    import time

    import pytest

    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    app = create_app(tmp_path, diagnostics=True)
    with TestClient(app, base_url=ORIGIN) as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        job = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "workspace_id": "default",
                "kind": "diagnostic",
                "idempotency_key": "cancel-me",
                "inputs": {"steps": 10, "delay_seconds": 5},
            },
        ).json()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["stage"] == "diagnostic_step_1_started":
                break
            time.sleep(0.01)
        assert current["stage"] == "diagnostic_step_1_started"
        pid = app.state.supervisor.process.pid
        response = client.post(f"/api/jobs/{job['id']}/cancel", headers=headers)
        assert response.status_code == 200
        assert response.json()["status"] in {"cancel_requested", "cancelled"}
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["status"] == "cancelled":
                break
            time.sleep(0.01)
        assert current["status"] == "cancelled"
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        events = app.state.journal.events_after(0)
        assert [event["kind"] for event in events][-2:] == ["cancel_requested", "cancelled"]
        assert current["result"] is None


def test_sse_replay_heartbeat_revocation_and_expiry(tmp_path):
    import asyncio

    import pytest

    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena.agentic_environment_generation.workbench.sessions import Sessions
    from isaaclab_arena_examples.agentic_environment_generation.web_api.events import event_stream

    journal = Journal(tmp_path / "events.sqlite3")
    now = [100.0]
    sessions = Sessions(journal, clock=lambda: now[0], idle_seconds=10)
    _, token = sessions.create()
    job = journal.submit("s", "default", "diagnostic", "one", {"steps": 1, "delay_seconds": 0.1})

    async def exercise():
        stream = event_stream(journal, sessions, token, 0, heartbeat=0.03, poll_interval=0.01)
        first = await anext(stream)
        assert first.startswith("id: 1\nevent: job\ndata: ")
        assert '"schema_version":1' in first
        assert await asyncio.wait_for(anext(stream), 1) == ": heartbeat\n\n"
        journal.transition(job["id"], "cancelled", "cancelled", "cancelled")
        assert (await anext(stream)).startswith("id: 2\nevent: job\n")
        sessions.revoke(token)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        _, replacement = sessions.create()
        replay = event_stream(journal, sessions, replacement, 1, poll_interval=0.01)
        assert (await anext(replay)).startswith("id: 2\n")
        now[0] = 110
        with pytest.raises(StopAsyncIteration):
            await anext(replay)

    asyncio.run(exercise())
    journal.close()


def test_sse_http_cursor_precedence_gap_and_slow_consumer(tmp_path):
    import asyncio

    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app
    from isaaclab_arena_examples.agentic_environment_generation.web_api.events import event_stream

    app = create_app(tmp_path, diagnostics=True, start_paused=True, idle_seconds=0.2)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/events").status_code == 401
        client.post("/api/sessions", json={}, headers={"Origin": ORIGIN})
        journal = app.state.journal
        job = journal.submit("s", "default", "diagnostic", "one", {"steps": 1, "delay_seconds": 0.1})
        response = client.get("/api/events?after=999", headers={"Last-Event-ID": "0"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["cache-control"] == "no-cache"
        assert response.text.startswith("id: 1\nevent: job\n")
        client.post("/api/sessions", json={}, headers={"Origin": ORIGIN})
        assert client.get("/api/events?after=0", headers={"Last-Event-ID": "1"}).text == ""
        client.post("/api/sessions", json={}, headers={"Origin": ORIGIN})
        for cursor in ("-1", "oops", "9" * 50):
            assert client.get(f"/api/events?after={cursor}").status_code == 422
        response = client.get("/api/events?after=999")
        assert "event: resync_required" in response.text
        token = client.cookies.get(app.state.cookie_name)

        async def slow_reader():
            stream = event_stream(journal, app.state.sessions, token, 0, max_lag=2, poll_interval=0.01)
            assert (await anext(stream)).startswith("id: 1\n")
            for step in range(3):
                journal.transition(job["id"], "running", f"step-{step}", "stage_changed")
            assert "event: resync_required" in await anext(stream)
            await stream.aclose()

        asyncio.run(slow_reader())


def test_restart_queue_requires_explicit_resume_and_has_bounded_capacity(tmp_path):
    import time

    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    journal = Journal(tmp_path / "journal.sqlite3")
    journal.begin_run()
    queued = journal.submit("s", "default", "diagnostic", "one", {"steps": 1, "delay_seconds": 0.1})
    journal.close()
    app = create_app(tmp_path, diagnostics=True, max_pending=1)
    with TestClient(app, base_url=ORIGIN) as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        time.sleep(0.35)
        assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "queued"
        body = {
            "workspace_id": "default",
            "kind": "diagnostic",
            "idempotency_key": "two",
            "inputs": {"steps": 1, "delay_seconds": 0.1},
        }
        assert client.post("/api/jobs", json=body, headers=headers).status_code == 409
        body["idempotency_key"] = "one"
        assert client.post("/api/jobs", json=body, headers=headers).json() == queued
        assert client.post("/api/jobs/resume-queue").status_code == 403
        assert client.post("/api/jobs/resume-queue", headers=headers).json() == {"resumed": True}
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{queued['id']}").json()
            if current["status"] == "succeeded":
                break
            time.sleep(0.02)
        assert current["status"] == "succeeded"


def test_launcher_locks_permissions_and_safe_stale_socket_replacement(tmp_path, monkeypatch):
    import os
    import socket
    import stat

    import pytest

    from isaaclab_arena_examples.agentic_environment_generation.web_api.runtime import StateLease, UnixListener

    state = tmp_path / "state"
    ipc = tmp_path / "ipc"
    path = ipc / "api.sock"
    with StateLease(state):
        assert stat.S_IMODE(state.stat().st_mode) == 0o700
        with pytest.raises(RuntimeError, match="already"):
            with StateLease(state):
                pass
        with UnixListener(path) as listener:
            assert listener.family == socket.AF_UNIX
            assert stat.S_IMODE(ipc.stat().st_mode) == 0o750
            assert stat.S_IMODE(path.stat().st_mode) == 0o660
            with pytest.raises(RuntimeError, match="already"):
                with UnixListener(path):
                    pass
        assert not path.exists()
        stale = socket.socket(socket.AF_UNIX)
        stale.bind(str(path))
        stale.close()
        with UnixListener(path):
            assert path.is_socket()
        external = socket.socket(socket.AF_UNIX)
        external.bind(str(path))
        external.listen(1)
        inode = path.stat().st_ino
        try:
            with pytest.raises(RuntimeError, match="live"):
                with UnixListener(path):
                    pass
            assert path.stat().st_ino == inode
        finally:
            external.close()
            path.unlink()
        sentinel = tmp_path / "sentinel"
        sentinel.write_text("do not touch")
        path.symlink_to(sentinel)
        with pytest.raises(RuntimeError, match="socket"):
            with UnixListener(path):
                pass
        assert sentinel.read_text() == "do not touch"
        path.unlink()
        path.write_text("not a socket")
        with pytest.raises(RuntimeError, match="socket"):
            with UnixListener(path):
                pass
        assert path.read_text() == "not a socket"
        with pytest.raises(ValueError, match="long"):
            with UnixListener(ipc / ("x" * 108)):
                pass
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with pytest.raises(RuntimeError, match="non-root"):
        with StateLease(state):
            pass


def test_worker_identity_is_durable_and_clean_shutdown_reaps_before_cancellation(tmp_path):
    import os
    import time

    import pytest

    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app
    from isaaclab_arena_examples.agentic_environment_generation.web_api.process_identity import process_identity

    app = create_app(tmp_path, diagnostics=True)
    with TestClient(app, base_url=ORIGIN) as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        job = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "workspace_id": "default",
                "kind": "diagnostic",
                "idempotency_key": "shutdown",
                "inputs": {"steps": 10, "delay_seconds": 5},
            },
        ).json()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if client.get(f"/api/jobs/{job['id']}").json()["stage"] == "diagnostic_step_1_started":
                break
            time.sleep(0.02)
        records = app.state.journal.pending_workers()
        assert len(records) == 1
        identity = records[0]
        assert identity["job_id"] == job["id"]
        pid = identity["pid"]
        assert identity["identity"] == process_identity(pid)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    journal = Journal(tmp_path / "journal.sqlite3")
    assert journal.get_job(job["id"])["status"] == "cancelled"
    assert journal.pending_workers() == []
    assert journal.begin_run() is False
    journal.finish_run()
    journal.close()


def test_restart_cleans_exact_worker_identity_without_signalling_reused_pid(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, diagnostic_worker
    from isaaclab_arena_examples.agentic_environment_generation.web_api.process_identity import process_identity

    worker = subprocess.Popen(
        [
            sys.executable,
            "-I",
            str(Path(diagnostic_worker.__file__)),
            "--steps",
            "1",
            "--delay",
            "5",
            "--parent-pid",
            str(os.getpid()),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        journal = Journal(tmp_path / "journal.sqlite3")
        journal.begin_run()
        active = journal.submit("s", "default", "diagnostic", "active", {"steps": 1, "delay_seconds": 5})
        journal.transition(active["id"], "running", "worker_starting", "started")
        journal.record_worker(active["id"], worker.pid, process_identity(worker.pid))
        reused = journal.submit("s", "default", "diagnostic", "reused", {"steps": 1, "delay_seconds": 5})
        journal.transition(reused["id"], "running", "worker_starting", "started")
        identity = {**process_identity(os.getpid()), "start_ticks": "different-start"}
        journal.record_worker(reused["id"], os.getpid(), identity)
        journal.close()
        app = create_app(tmp_path, diagnostics=True)
        with TestClient(app, base_url=ORIGIN):
            assert app.state.journal.pending_workers() == []
            assert worker.poll() is not None
            assert app.state.journal.get_job(active["id"])["status"] == "indeterminate"
            assert app.state.journal.get_job(reused["id"])["status"] == "indeterminate"
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.communicate(timeout=3)


def test_session_input_is_empty_and_clone_origin_cookies_are_distinct(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    app = create_app(tmp_path / "one")
    other_clone = create_app(tmp_path / "two")
    other_origin = create_app(tmp_path / "one", origin="https://127.0.0.1:3001")
    assert len({app.state.cookie_name, other_clone.state.cookie_name, other_origin.state.cookie_name}) == 3
    with TestClient(app, base_url=ORIGIN) as client:
        assert (
            client.post("/api/sessions", json={"secret": "do-not-echo"}, headers={"Origin": ORIGIN}).status_code == 422
        )
        assert client.post("/api/sessions", content="malformed", headers={"Origin": ORIGIN}).status_code == 422
        assert client.get("/api/artifacts/%2e%2e%2fetc%2fpasswd").status_code == 404
    with TestClient(other_origin, base_url="https://127.0.0.1:3001") as client:
        response = client.post("/api/sessions", json={}, headers={"Origin": "https://127.0.0.1:3001"})
        assert "Secure" in response.headers["set-cookie"]


def test_ipc_and_private_state_cannot_overlap(tmp_path):
    import pytest

    from isaaclab_arena_examples.agentic_environment_generation.web_api.runtime import validate_layout

    validate_layout(tmp_path / "state", tmp_path / "ipc" / "api.sock")
    for state, socket in (
        (tmp_path / "state", tmp_path / "state" / "api.sock"),
        (tmp_path / "ipc" / "state", tmp_path / "ipc" / "api.sock"),
        (tmp_path / "state", tmp_path / "state" / "nested" / "api.sock"),
    ):
        with pytest.raises(ValueError, match="separate"):
            validate_layout(state, socket)


def test_api_storage_fault_is_atomic_and_returns_sanitized_json(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    app = create_app(tmp_path, diagnostics=True, start_paused=True)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        app.state.journal.db.execute(
            "CREATE TRIGGER reject_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'private-diagnostic'); END"
        )
        response = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "workspace_id": "default",
                "kind": "diagnostic",
                "idempotency_key": "fault",
                "inputs": {"steps": 1, "delay_seconds": 0.1},
            },
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal workbench error"}
        assert client.get("/api/jobs").json() == {"jobs": [], "event_cursor": 0}


def _launch_api(tmp_path, *, diagnostics=True):
    import subprocess
    import sys
    import time
    from contextlib import suppress

    import httpx

    socket_path = tmp_path / "ipc" / "api.sock"
    command = [
        sys.executable,
        "-m",
        "isaaclab_arena_examples.agentic_environment_generation.web_api",
        "--state-dir",
        str(tmp_path / "state"),
        "--socket",
        str(socket_path),
        "--origin",
        ORIGIN,
    ]
    if diagnostics:
        command.append("--diagnostics")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    client = httpx.Client(transport=httpx.HTTPTransport(uds=str(socket_path)), base_url=ORIGIN, timeout=5)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(process.communicate()[0].decode())
        with suppress(httpx.TransportError):
            if client.get("/api/health").status_code == 200:
                return process, client, command
        time.sleep(0.03)
    process.terminate()
    process.wait(timeout=5)
    client.close()
    raise AssertionError("API never became ready")


def _stop_api(process, client):
    import subprocess

    client.close()
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    process.communicate(timeout=1)


def test_real_uds_stream_admission_is_bounded_and_disconnect_releases_capacity(tmp_path):
    import time

    process, client, _ = _launch_api(tmp_path)
    responses = []
    try:
        client.post("/api/sessions", json={}, headers={"Origin": ORIGIN})
        for _ in range(8):
            response = client.send(client.build_request("GET", "/api/events"), stream=True)
            responses.append(response)
            assert response.status_code == 200
        rejected = client.send(client.build_request("GET", "/api/events"), stream=True)
        responses.append(rejected)
        assert rejected.status_code == 429
        assert client.get("/api/health").status_code == 200
        for response in responses:
            response.close()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            retry = client.send(client.build_request("GET", "/api/events"), stream=True)
            retry.close()
            if retry.status_code == 200:
                break
            time.sleep(0.03)
        assert retry.status_code == 200
    finally:
        for response in responses:
            response.close()
        _stop_api(process, client)


def test_real_cli_uds_sse_and_durable_restart(tmp_path):
    import json
    import subprocess

    process, client, command = _launch_api(tmp_path)
    try:
        assert client.get("/api/health").json()["capabilities"]["diagnostic"] is True
        duplicate = subprocess.run(command, capture_output=True, timeout=10)
        assert duplicate.returncode != 0 and b"already" in duplicate.stderr
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        cookies = client.cookies
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        job = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "workspace_id": "default",
                "kind": "diagnostic",
                "idempotency_key": "uds",
                "inputs": {"steps": 1, "delay_seconds": 0.1},
            },
        ).json()
        observed = []
        with client.stream("GET", "/api/events?after=0") as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    observed.append(event)
                    if event["job"]["status"] == "succeeded":
                        break
        assert [event["id"] for event in observed] == list(range(1, 7))
        assert observed[-1]["job"]["id"] == job["id"]
        assert client.get("/api/jobs").json()["event_cursor"] == 6
    finally:
        _stop_api(process, client)
    assert not (tmp_path / "ipc" / "api.sock").exists()
    process, client, _ = _launch_api(tmp_path)
    try:
        client.cookies.update(cookies)
        assert client.get("/api/session").json() == session
        assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded"
        assert "resync_required" in client.get("/api/events?after=999").text
    finally:
        _stop_api(process, client)


def test_real_worker_survives_heartbeat_but_not_api_crash_and_is_never_replayed(tmp_path):
    import json
    import os
    import signal
    import time
    from pathlib import Path

    process, client, _ = _launch_api(tmp_path)
    child = None
    try:
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        cookies = client.cookies
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        body = {
            "workspace_id": "default",
            "kind": "diagnostic",
            "idempotency_key": "crash",
            "inputs": {"steps": 10, "delay_seconds": 5},
        }
        active = client.post("/api/jobs", json=body, headers=headers).json()
        queued = client.post(
            "/api/jobs",
            json={**body, "idempotency_key": "waiting", "inputs": {"steps": 1, "delay_seconds": 0.1}},
            headers=headers,
        ).json()
        saw_running = False
        saw_heartbeat = False
        started = time.monotonic()
        with client.stream("GET", "/api/events?after=0", timeout=20) as response:
            for line in response.iter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    saw_running |= event["job"]["status"] == "running"
                    if saw_heartbeat and event["job"]["stage"].endswith("_started"):
                        break
                if line == ": heartbeat":
                    saw_heartbeat = True
        assert saw_running and saw_heartbeat and time.monotonic() - started >= 14
        assert client.get(f"/api/jobs/{active['id']}").json()["status"] == "running"
        children = Path(f"/proc/{process.pid}/task/{process.pid}/children").read_text().split()
        assert len(children) == 1
        child = int(children[0])
        process.kill()
        process.wait(timeout=3)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            info = Path(f"/proc/{child}/stat")
            if not info.exists() or info.read_text().rsplit(")", 1)[1].split()[0] == "Z":
                child = None
                break
            time.sleep(0.02)
        assert child is None, "Diagnostic child continued executing after API death"
    finally:
        if child is not None:
            os.killpg(child, signal.SIGKILL)
        _stop_api(process, client)
    process, client, _ = _launch_api(tmp_path)
    try:
        client.cookies.update(cookies)
        assert client.get(f"/api/jobs/{active['id']}").json()["status"] == "indeterminate"
        time.sleep(0.35)
        assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "queued"
        assert client.post("/api/jobs", json=body, headers=headers).json()["id"] == active["id"]
        assert client.post("/api/jobs/resume-queue", headers=headers).json() == {"resumed": True}
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{queued['id']}").json()
            if current["status"] == "succeeded":
                break
            time.sleep(0.02)
        assert current["status"] == "succeeded"
        assert client.get(f"/api/jobs/{active['id']}").json()["status"] == "indeterminate"
    finally:
        _stop_api(process, client)
