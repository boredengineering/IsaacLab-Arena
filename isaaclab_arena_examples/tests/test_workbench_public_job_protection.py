# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Current-policy public Journal boundaries; synthetic jobs only, no workers."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, editor_execution

ORIGIN = "http://127.0.0.1:3000"
MARKER = "dummy-public-job-marker-123456"


@pytest.fixture
def api(tmp_path, monkeypatch):
    def unavailable(_):
        raise RuntimeError("No snapshot runtime in isolated job checks")
    monkeypatch.setattr(editor_execution, "make_snapshot_service", unavailable)
    app = create_app(tmp_path / "state", start_paused=True, diagnostics=True)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
        yield app, client, headers
        assert app.state.supervisor.paused
        assert app.state.supervisor.process is None
        assert not app.state.workflow_authorization.grants._records
        assert not app.state.publication_authorization._records
        assert app.state.active_streams == 0


def activate(client, headers, marker=MARKER):
    response = client.put("/api/model-settings", headers=headers, json={
        "provider": "openai", "model": "inert", "api_key": marker})
    assert response.status_code == 200, response.text


def escaped(marker=MARKER):
    return '"' + ''.join(f"\\x{ord(char):02x}" for char in marker) + '"'


def stored(app, payload):
    journal = app.state.journal
    job = journal.submit("synthetic", "default", "generate", "stored", {"nested": payload})
    return journal.transition(job["id"], "succeeded", "completed", "succeeded", result={"nested": payload})


@pytest.mark.parametrize("route", ["/api/jobs", "/api/workspaces/default", "/api/jobs/{id}"])
@pytest.mark.parametrize("payload", [
    {"raw": MARKER}, {"yaml": "value: " + escaped()},
    {"nested": [{"value: " + escaped(): "safe"}]},
    {"yaml": 'value: "dummy-public-\\\n  job-marker-123456"'},
])
def test_reads_screen_complete_stored_records_under_new_policy(api, route, payload):
    app, client, headers = api
    job = stored(app, payload)
    path = route.format(id=job["id"])
    clean = client.get(path)
    assert clean.status_code == 200
    activate(client, headers)
    app.state.documents.views.clear()
    app.state.documents.frozen.clear()
    before = list(app.state.journal.db.iterdump())
    response = client.get(path)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request input"}
    assert MARKER not in response.text
    assert list(app.state.journal.db.iterdump()) == before
    assert app.state.journal.get_job(job["id"]) == job


def test_nested_yaml_string_decoding_is_not_just_one_parse(api):
    app, client, headers = api
    payload = {"outer": "wrapper: " + json.dumps("value: " + escaped())}
    job = stored(app, payload)
    activate(client, headers)
    before = list(app.state.journal.db.iterdump())
    response = client.get("/api/jobs/" + job["id"])
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request input"}
    assert list(app.state.journal.db.iterdump()) == before


@pytest.mark.parametrize("shape", ["string", "depth", "nodes"])
def test_unscreenable_records_fail_closed_without_a_partial_snapshot(api, shape):
    app, client, _ = api
    if shape == "string":
        payload = "a" * (256 * 1024 + 1)
    elif shape == "nodes":
        payload = [None] * 100_001
    else:
        payload = "safe"
        for _ in range(41):
            payload = [payload]
    stored(app, payload)
    before = list(app.state.journal.db.iterdump())
    response = client.get("/api/jobs")
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request input"}
    assert list(app.state.journal.db.iterdump()) == before


BODY = {"workspace_id": "default", "kind": "diagnostic", "idempotency_key": "diagnostic:one",
        "inputs": {"steps": 1, "delay_seconds": 0.1}}


@pytest.mark.parametrize("operation", ["submit", "cancel"])
@pytest.mark.parametrize("failure_type", [RuntimeError, ValueError, TypeError])
def test_unexpected_screening_failure_after_effect_preserves_explicit_disposition(api, monkeypatch, operation, failure_type):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import jobs as routes

    app, client, headers = api
    job_id = None
    if operation == "cancel":
        accepted = client.post("/api/jobs", headers=headers, json=BODY)
        assert accepted.status_code == 202
        job_id = accepted.json()["id"]
    original_guard = routes.protect_public_record

    def fail_on_job(request, value):
        if isinstance(value, dict) and "id" in value and "status" in value:
            raise failure_type("private-screening-failure /private/path")
        return original_guard(request, value)

    with monkeypatch.context() as patcher:
        patcher.setattr(routes, "protect_public_record", fail_on_job)
        if operation == "submit":
            response = client.post("/api/jobs", headers=headers, json=BODY)
        else:
            response = client.post(f"/api/jobs/{job_id}/cancel", headers=headers)

    assert response.status_code == 503, response.text
    expected = (
        "Job accepted; public job record unavailable. Retain the exact submission for lookup"
        if operation == "submit" else
        "Cancellation handled; public job record unavailable. Cancellation may still be pending; read the job again for status"
    )
    assert response.json() == {"detail": expected}
    assert "private-screening-failure" not in response.text
    snapshot = app.state.journal.snapshot()
    assert len(snapshot["jobs"]) == 1
    observed = snapshot["jobs"][0]
    assert observed["status"] == ("queued" if operation == "submit" else "cancelled")
    assert job_id is None or observed["id"] == job_id
    assert client.get(f"/api/jobs/{observed['id']}").json() == observed


def test_direct_submission_rejects_current_key_before_persistence(api):
    app, client, headers = api
    activate(client, headers)
    before = list(app.state.journal.db.iterdump())
    response = client.post("/api/jobs", headers=headers, json={**BODY, "idempotency_key": MARKER})
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request input"}
    assert list(app.state.journal.db.iterdump()) == before


def test_direct_submission_replay_screens_stored_result_without_new_work(api):
    app, client, headers = api
    accepted = client.post("/api/jobs", headers=headers, json=BODY)
    assert accepted.status_code == 202
    job = accepted.json()
    assert client.post("/api/jobs", headers=headers, json=BODY).json() == job
    app.state.journal.transition(job["id"], "succeeded", "completed", "succeeded",
                                 result={"unused": [{"yaml": "value: " + escaped()}]})
    activate(client, headers)
    before = list(app.state.journal.db.iterdump())
    response = client.post("/api/jobs", headers=headers, json=BODY)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request input"}
    assert list(app.state.journal.db.iterdump()) == before


def test_submission_exception_text_is_not_public(api, monkeypatch):
    app, client, headers = api
    def conflict(*args, **kwargs):
        raise ValueError(MARKER)
    monkeypatch.setattr(app.state.journal, "submit", conflict)
    response = client.post("/api/jobs", headers=headers, json=BODY)
    assert response.status_code == 409
    assert response.json() == {"detail": "Job submission conflicts with stored inputs or queue capacity"}
    assert MARKER not in response.text


def test_accepted_submission_with_unavailable_response_is_explicit(api, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.model_settings import SettingsInput
    app, client, headers = api
    submit = app.state.journal.submit
    session = client.get("/api/session").json()
    def accept_then_protect_identity(*args, **kwargs):
        job = submit(*args, **kwargs)
        app.state.model_settings.save(session, SettingsInput(provider="openai", model="inert", api_key=job["id"]))
        return job
    monkeypatch.setattr(app.state.journal, "submit", accept_then_protect_identity)
    response = client.post("/api/jobs", headers=headers, json=BODY)
    assert response.status_code == 503
    assert response.json() == {"detail": "Job accepted; public job record unavailable. Retain the exact submission for lookup"}
    snapshot = app.state.journal.snapshot()
    assert len(snapshot["jobs"]) == 1 and snapshot["event_cursor"] == 1
    assert snapshot["jobs"][0]["id"] not in response.text


CANCEL_UNAVAILABLE = {"detail": "Cancellation handled; public job record unavailable. Cancellation may still be pending; read the job again for status"}


@pytest.mark.parametrize("status,expected", [
    ("queued", "cancelled"), ("blocked_authorization", "cancelled"),
    ("running", "cancel_requested"), ("cancel_requested", "cancel_requested"),
    ("succeeded", "succeeded"), ("failed", "failed"), ("cancelled", "cancelled"),
])
@pytest.mark.parametrize("protected", [False, True])
def test_cancellation_preserves_authorized_effect_but_never_fabricates_a_job(api, status, expected, protected):
    app, client, headers = api
    journal = app.state.journal
    job = journal.submit("synthetic", "default", "generate", "cancel", {"unused": "value: " + escaped()})
    if status == "blocked_authorization":
        attempt = journal.claim_attempt(job["id"])
        assert journal.block_attempt_authorization(job["id"], **attempt)
    elif status != "queued":
        journal.transition(job["id"], status, status, status)
    if protected:
        activate(client, headers)
    before = journal.snapshot()["event_cursor"]
    response = client.post("/api/jobs/" + job["id"] + "/cancel", headers=headers)
    durable = journal.get_job(job["id"])
    assert durable["status"] == expected
    assert durable["inputs"] == job["inputs"]
    if protected:
        assert response.status_code == 503
        assert response.json() == CANCEL_UNAVAILABLE
        assert MARKER not in response.text
    else:
        assert response.status_code == 200 and response.json() == durable
    after = journal.snapshot()["event_cursor"]
    assert after == before + (status != expected)
    if status == "blocked_authorization":
        assert journal.get_attempt(job["id"])["state"] == "cancelled"
    # Exact repeats preserve the actual disposition and append no fake events.
    repeated = client.post("/api/jobs/" + job["id"] + "/cancel", headers=headers)
    assert repeated.status_code == response.status_code
    assert repeated.json() == response.json()
    assert journal.snapshot()["event_cursor"] == after


def test_cancel_authentication_csrf_and_missing_id_are_unchanged(api):
    app, client, headers = api
    job = app.state.journal.submit("synthetic", "default", "generate", "cancel-auth", {})
    before = list(app.state.journal.db.iterdump())
    path = "/api/jobs/" + job["id"] + "/cancel"
    assert client.post(path).status_code == 403
    assert client.post(path, headers={"Origin": ORIGIN}).status_code == 403
    assert client.post("/api/jobs/missing/cancel", headers=headers).json() == {"detail": "Job not found"}
    assert list(app.state.journal.db.iterdump()) == before
    assert client.delete("/api/session", headers=headers).status_code == 200
    assert client.post(path, headers=headers).status_code == 401
    assert app.state.journal.get_job(job["id"])["status"] == "queued"


async def asgi_stream(app, client, *, query=b"after=0", extra_headers=(), on_chunk=None, max_chunks=2):
    """Bound the real authenticated ASGI stream, including its disconnect cleanup."""
    disconnect = asyncio.Event()
    messages = []
    chunks = []
    first_receive = True
    async def receive():
        nonlocal first_receive
        if first_receive:
            first_receive = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}
    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            chunks.append(message["body"])
            if on_chunk:
                on_chunk(len(chunks), message["body"], disconnect)
            if len(chunks) >= max_chunks:
                disconnect.set()
    headers = [(b"host", b"127.0.0.1:3000"),
               (b"cookie", (app.state.cookie_name + "=" + client.cookies.get(app.state.cookie_name)).encode()),
               *extra_headers]
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"},
             "http_version": "1.1", "method": "GET", "scheme": "http", "path": "/api/events",
             "raw_path": b"/api/events", "query_string": query, "root_path": "", "headers": headers,
             "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 3000)}
    await asyncio.wait_for(app(scope, receive, send), 3)
    assert app.state.active_streams == 0
    starts = [m for m in messages if m["type"] == "http.response.start"]
    assert len(starts) == 1
    return starts[0], b"".join(chunks)


PROTECTED_RESYNC = b'event: resync_required\ndata: {"detail":"Public event unavailable; fetch a fresh workspace snapshot"}\n\n'


@pytest.mark.parametrize("payload", [MARKER, "value: " + escaped(),
                                     'value: "dummy-public-\\\n  job-marker-123456"'])
def test_sse_rechecks_current_policy_after_stream_start_without_advancing_protected_cursor(api, payload):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.model_settings import SettingsInput
    app, client, _ = api
    journal = app.state.journal
    first = journal.submit("synthetic", "default", "generate", "first", {"safe": True})
    session = client.get("/api/session").json()
    before = []
    def activate_and_append(count, chunk, disconnect):
        if count == 1:
            assert chunk.startswith(b"id: 1\nevent: job\n")
            app.state.model_settings.save(session, SettingsInput(provider="openai", model="inert", api_key=MARKER))
            journal.submit("synthetic", "default", "generate", "second", {"nested": [{"yaml": payload}]})
            before.extend(journal.db.iterdump())
    start, body = asyncio.run(asgi_stream(app, client, on_chunk=activate_and_append))
    assert start["status"] == 200
    assert dict(start["headers"])[b"content-type"].startswith(b"text/event-stream")
    assert body.endswith(PROTECTED_RESYNC)
    assert MARKER.encode() not in body and b"id: 2\n" not in body
    first_frame = body.split(b"\n\n", 1)[0].split(b"data: ", 1)[1]
    assert json.loads(first_frame)["job"] == first
    assert list(journal.db.iterdump()) == before
    # The blocked durable event is not skipped or replaced with a synthetic ID.
    start, replay = asyncio.run(asgi_stream(app, client, query=b"after=1", max_chunks=1))
    assert start["status"] == 200 and replay == PROTECTED_RESYNC
    assert list(journal.db.iterdump()) == before
    assert client.get("/api/workspaces/default").status_code == 422


@pytest.mark.parametrize("retire", ["expiry", "revoke"])
def test_no_heartbeat_after_session_retirement_between_yields(api, monkeypatch, retire):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.events import event_stream
    app, client, _ = api
    journal, sessions = app.state.journal, app.state.sessions
    token = client.cookies.get(app.state.cookie_name)
    session = sessions.get(token)
    journal.submit("synthetic", "default", "generate", "heartbeat", {})
    async def exercise():
        stream = event_stream(journal, sessions, token, 0, heartbeat=0, poll_interval=0)
        assert (await anext(stream)).startswith("id: 1\n")
        if retire == "expiry":
            monkeypatch.setattr(sessions, "clock", lambda: session["expires_at"])
        else:
            sessions.revoke(token)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        await stream.aclose()
    asyncio.run(exercise())


def test_resync_revalidates_session_after_replay_read(api, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench.journal import ReplayGap
    from isaaclab_arena_examples.agentic_environment_generation.web_api.events import event_stream
    app, client, _ = api
    journal, sessions = app.state.journal, app.state.sessions
    token = client.cookies.get(app.state.cookie_name)
    def retire_during_read(*args, **kwargs):
        sessions.revoke(token)
        raise ReplayGap("private " + MARKER)
    monkeypatch.setattr(journal, "events_after", retire_during_read)
    async def exercise():
        stream = event_stream(journal, sessions, token, 0)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        await stream.aclose()
    asyncio.run(exercise())


def test_sse_screens_current_policy_on_each_event_in_an_already_fetched_page(api):
    from types import SimpleNamespace
    from isaaclab_arena_examples.agentic_environment_generation.web_api.events import event_stream
    from isaaclab_arena_examples.agentic_environment_generation.web_api.public_records import protect_public_record
    app, client, headers = api
    journal, sessions = app.state.journal, app.state.sessions
    token = client.cookies.get(app.state.cookie_name)
    journal.submit("synthetic", "default", "generate", "page-first", {})
    journal.submit("synthetic", "default", "generate", "page-second", {"nested": "value: " + escaped()})
    before = list(journal.db.iterdump())
    async def exercise():
        stream = event_stream(journal, sessions, token, 0,
                              protect=lambda event: protect_public_record(SimpleNamespace(app=app), event))
        assert (await anext(stream)).startswith("id: 1\n")
        activate(client, headers)
        assert (await anext(stream)).encode() == PROTECTED_RESYNC
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        await stream.aclose()
    asyncio.run(exercise())
    assert list(journal.db.iterdump()) == before


@pytest.mark.parametrize("location", ["event_kind", "error", "stage", "yaml_key", "nested_yaml"])
def test_sse_screens_whole_envelope_and_all_job_fields(api, location):
    app, client, headers = api
    journal = app.state.journal
    job = journal.submit("synthetic", "default", "generate", "envelope", {})
    result = None
    if location == "yaml_key":
        result = {"value: " + escaped(): "safe"}
    if location == "nested_yaml":
        result = {"outer": "wrapper: " + json.dumps("value: " + escaped())}
    journal.transition(job["id"], "failed", MARKER if location == "stage" else "failed",
                       MARKER if location == "event_kind" else "failed", result=result,
                       error="value: " + escaped() if location == "error" else None)
    activate(client, headers)
    before = list(journal.db.iterdump())
    start, body = asyncio.run(asgi_stream(app, client, query=b"after=1", max_chunks=1))
    assert start["status"] == 200 and body == PROTECTED_RESYNC
    assert list(journal.db.iterdump()) == before


def test_sse_protection_exception_is_static_and_releases_admission(api, monkeypatch):
    app, client, _ = api
    app.state.journal.submit("synthetic", "default", "generate", "failure", {})
    def broken(value):
        raise RuntimeError(MARKER)
    monkeypatch.setattr(app.state.model_settings, "protect_public", broken)
    start, body = asyncio.run(asgi_stream(app, client, max_chunks=1))
    assert start["status"] == 200 and body == PROTECTED_RESYNC


def test_sse_cursor_precedence_disconnect_gap_and_unchanged_jobs(api):
    app, client, _ = api
    journal = app.state.journal
    job = journal.submit("synthetic", "default", "generate", "cursor", {})
    journal.transition(job["id"], "running", "synthetic", "started")
    before = list(journal.db.iterdump())
    start, body = asyncio.run(asgi_stream(app, client, query=b"after=999",
                                        extra_headers=[(b"last-event-id", b"1")], max_chunks=1))
    assert start["status"] == 200 and body.startswith(b"id: 2\nevent: job\n")
    assert dict(start["headers"])[b"cache-control"] == b"no-cache"
    assert dict(start["headers"])[b"x-accel-buffering"] == b"no"
    start, body = asyncio.run(asgi_stream(app, client, query=b"after=999", max_chunks=1))
    assert start["status"] == 200
    assert body == b'event: resync_required\ndata: {"detail":"Fetch a fresh workspace snapshot"}\n\n'
    for cursor in ("-1", "invalid", "9223372036854775808", "9" * 50, "%D9%A1"):
        response = client.get("/api/events?after=" + cursor)
        assert response.status_code == 422 and response.json() == {"detail": "Invalid event cursor"}
    assert list(journal.db.iterdump()) == before


def test_sse_capacity_and_task_cancellation_release_all_leases(api):
    app, client, _ = api
    before = list(app.state.journal.db.iterdump())
    async def exercise():
        tasks = [asyncio.create_task(asgi_stream(app, client)) for _ in range(8)]
        try:
            for _ in range(200):
                if app.state.active_streams == 8:
                    break
                await asyncio.sleep(0.005)
            assert app.state.active_streams == 8
            response = client.get("/api/events")
            assert response.status_code == 429
            assert response.json() == {"detail": "Event stream capacity reached; use bounded polling"}
            assert app.state.active_streams == 8
        finally:
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        assert app.state.active_streams == 0
    asyncio.run(exercise())
    assert list(app.state.journal.db.iterdump()) == before


@pytest.mark.parametrize("retire", ["expiry", "revoke"])
def test_authenticated_asgi_stream_retirement_closes_without_mutating_jobs(api, monkeypatch, retire):
    app, client, _ = api
    journal, sessions = app.state.journal, app.state.sessions
    token = client.cookies.get(app.state.cookie_name)
    session = sessions.get(token)
    job = journal.submit("synthetic", "default", "generate", "retire", {})
    snapshot = journal.snapshot()
    def retire_session(count, chunk, disconnect):
        if retire == "expiry":
            monkeypatch.setattr(sessions, "clock", lambda: session["expires_at"])
        else:
            sessions.revoke(token)
    start, body = asyncio.run(asgi_stream(app, client, on_chunk=retire_session, max_chunks=20))
    assert start["status"] == 200 and body.count(b"event: job\n") == 1
    assert b"heartbeat" not in body
    assert journal.snapshot() == snapshot
    assert journal.get_job(job["id"])["status"] == "queued"
    assert client.get("/api/events").status_code == 401


@pytest.mark.parametrize("reject", [False, True])
def test_sse_rechecks_session_after_bounded_protection_before_any_frame(api, reject):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.events import event_stream
    app, client, _ = api
    journal, sessions = app.state.journal, app.state.sessions
    token = client.cookies.get(app.state.cookie_name)
    journal.submit("synthetic", "default", "generate", "retired-during-screen", {})
    def screen(event):
        sessions.revoke(token)
        if reject:
            raise ValueError(MARKER)
    async def exercise():
        stream = event_stream(journal, sessions, token, 0, protect=screen)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        await stream.aclose()
    asyncio.run(exercise())


@pytest.mark.parametrize("payload", ["a" * (256 * 1024 + 1), [None] * 131_073], ids=["oversized-string", "node-budget"])
def test_sse_unscreenable_records_terminate_without_partial_or_skipped_events(api, payload):
    app, client, _ = api
    journal = app.state.journal
    journal.submit("synthetic", "default", "generate", "unscreenable", {"unused": payload})
    before = list(journal.db.iterdump())
    start, body = asyncio.run(asgi_stream(app, client, max_chunks=1))
    assert start["status"] == 200 and body == PROTECTED_RESYNC
    assert list(journal.db.iterdump()) == before


def test_sse_heartbeat_and_slow_consumer_do_not_renew_session_or_skip_cursor(api):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.events import event_stream
    app, client, _ = api
    journal, sessions = app.state.journal, app.state.sessions
    token = client.cookies.get(app.state.cookie_name)
    session = sessions.get(token)
    job = journal.submit("synthetic", "default", "generate", "slow", {})
    async def exercise():
        stream = event_stream(journal, sessions, token, 0, heartbeat=0, poll_interval=0, max_lag=2)
        assert (await anext(stream)).startswith("id: 1\n")
        assert await anext(stream) == ": heartbeat\n\n"
        assert sessions.get(token) == session
        for step in range(3):
            journal.transition(job["id"], "running", "stage-" + str(step), "stage_changed")
        frame = await anext(stream)
        assert frame == 'event: resync_required\ndata: {"detail":"Fetch a fresh workspace snapshot"}\n\n'
        assert "id:" not in frame
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        await stream.aclose()
        assert sessions.get(token) == session
    asyncio.run(exercise())


def test_protected_replay_can_later_return_exact_durable_event_under_changed_policy(api):
    app, client, headers = api
    journal = app.state.journal
    journal.submit("synthetic", "default", "generate", "policy-replay", {"value": MARKER})
    original = journal.events_after(0)[0]
    activate(client, headers)
    start, body = asyncio.run(asgi_stream(app, client, max_chunks=1))
    assert start["status"] == 200 and body == PROTECTED_RESYNC
    assert client.delete("/api/model-settings", headers=headers).status_code == 200
    before = list(journal.db.iterdump())
    start, body = asyncio.run(asgi_stream(app, client, max_chunks=1))
    assert start["status"] == 200 and body.startswith(b"id: 1\nevent: job\n")
    assert json.loads(body.split(b"data: ", 1)[1]) == original
    assert list(journal.db.iterdump()) == before


@pytest.mark.parametrize("yaml_text", [
    "value: >-\n  dummy-folded\n  password-marker-123456\n",
    "? >-\n  dummy-folded\n  password-marker-123456\n: safe\n",
], ids=["scalar", "key"])
def test_folded_yaml_scalars_and_keys_use_current_password_policy(api, monkeypatch, yaml_text):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import graph_access
    app, client, _ = api
    # Password policy permits spaces; no credential environment or transport is used.
    marker = "dummy-folded password-marker-123456"
    job = stored(app, {"nested": [yaml_text]})
    assert client.get("/api/jobs/" + job["id"]).status_code == 200
    monkeypatch.setattr(graph_access, "configuration", lambda: {
        "uri": "bolt://unused.invalid:7687", "user": "fixture", "password": marker, "database": "neo4j"})
    before = list(app.state.journal.db.iterdump())
    for path in ("/api/jobs", "/api/workspaces/default", "/api/jobs/" + job["id"]):
        response = client.get(path)
        assert response.status_code == 422 and response.json() == {"detail": "Invalid request input"}
        assert marker not in response.text
    start, body = asyncio.run(asgi_stream(app, client, max_chunks=1))
    assert start["status"] == 200 and body == PROTECTED_RESYNC
    assert list(app.state.journal.db.iterdump()) == before
