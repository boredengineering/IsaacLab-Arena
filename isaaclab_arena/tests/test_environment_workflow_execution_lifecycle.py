# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Explicit lifecycle cohort, source-only pending review: inert external ports.

These tests require an owner-inclusive staged closure, not execution effects. Do not add this file to
legacy backend/query roots or increase their ceilings to make collection pass.
They do not replace the required installed slow-body/physical-worker witness.
"""

import asyncio
from threading import Event, RLock
from types import SimpleNamespace

import pytest

from workflow_graphql_execution_lifecycle_harness import historical_owner, record_blocked_admission

from isaaclab_arena.agentic_environment_generation.workflow.api.execution_owner import CleanupUnknown, ExecutionOwner


def owner_fixture(owner_type=ExecutionOwner, *, tokens=None):
    calls = []
    root = SimpleNamespace(
        _lock=RLock(), _cancel_controls={"run": SimpleNamespace(principal="operator")},
        _recoveries={}, _local={},
        authority=SimpleNamespace(close=lambda: calls.append("revoke")),
        store=SimpleNamespace(get_owner=lambda: None,
                              get_run_cleanup=lambda run: SimpleNamespace(current_scope_owner=None, intents=())),
        close=lambda: calls.append("root_close"),
    )
    root._cancellation = SimpleNamespace(stop_local=lambda *args: calls.append("stop"))
    area = SimpleNamespace(close=lambda: calls.append("area_close"))
    # Owner.close/request_stop do not use bearer handles. The ASGI test below
    # binds its real registry; inert owner tests never submit or mint authority.
    return owner_type(root, area, tokens, lambda value: None), calls


async def wait_until(predicate, seconds=1):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), seconds)


@pytest.mark.parametrize("failure", ["timeout", "cleanup_error"])
def test_execution_server_observation_does_not_cancel_unresolved_cleanup(monkeypatch, failure):
    from isaaclab_arena.agentic_environment_generation.workflow.api import server

    async def exercise():
        release = asyncio.Event()
        task = asyncio.create_task(release.wait())
        app = SimpleNamespace(state=SimpleNamespace(cleanup_unknown=failure == "cleanup_error"))
        monkeypatch.setattr(server, "EXECUTION_SHUTDOWN_SECONDS", 0.02)
        try:
            assert not await server.observe_execution_shutdown(task, app)
            assert not task.done(), "observation cancelled the owned lifetime"
        finally:
            release.set()
            await task

    asyncio.run(exercise())


def blocked_admission_observation(owner_type):
    """Use identical barriers and the same production close call for both owners."""
    async def exercise():
        owner, calls = owner_fixture(owner_type)
        entered, release = Event(), Event()

        def blocked():
            entered.set()
            assert release.wait(3)

        pending = asyncio.create_task(owner.admissions.run(blocked))
        closing = None
        try:
            await wait_until(entered.is_set)
            closing = asyncio.create_task(owner.close())
            await wait_until(lambda: not owner._accepting)
            try:
                await wait_until(lambda: "stop" in calls)
            except TimeoutError:
                pass
            observation = dict(
                admission_entered=entered.is_set(), close_pending=not closing.done(),
                refused=not owner._accepting, area_retained="area_close" not in calls,
                stop_before_release="stop" in calls,
            )
        finally:
            release.set()
            try:
                await pending
            finally:
                if closing is None:
                    await owner.close()
                else:
                    await closing
        assert calls.index("stop") < calls.index("root_close") < calls.index("area_close")
        observation["closed_after_release"] = owner._closed
        return observation

    return asyncio.run(exercise())


def assert_stop_before_release(observation):
    assert all(value for name, value in observation.items() if name != "stop_before_release")
    assert observation["stop_before_release"], "physical stop waited for admission drain"


def test_execution_stop_precedes_blocked_admission_drain():
    observation = blocked_admission_observation(ExecutionOwner)
    record_blocked_admission("current", observation)
    assert_stop_before_release(observation)


def test_historical_owner_fails_stop_before_blocked_admission_drain():
    # Loading and complete cleanup are OUTSIDE the expected-failure boundary.
    # Only the exact shared behavioral assertion is allowed to be the RED.
    observation = blocked_admission_observation(historical_owner())
    record_blocked_admission("historical", observation)
    with pytest.raises(AssertionError, match="^physical stop waited for admission drain"):
        assert_stop_before_release(observation)


def test_execution_cleanup_timeout_is_sticky_and_retains_area(monkeypatch):
    async def exercise():
        owner, calls = owner_fixture()
        entered, release = Event(), Event()

        def blocked():
            entered.set()
            assert release.wait(3)

        monkeypatch.setattr(owner, "CLOSE_TIMEOUT", 0.02)
        pending = asyncio.create_task(owner.admissions.run(blocked))
        try:
            await wait_until(entered.is_set)
            with pytest.raises(CleanupUnknown):
                await owner.close()
            assert owner.cleanup_unknown and not owner._closed
            assert "area_close" not in calls
        finally:
            release.set()
            await pending
            await asyncio.shield(owner._closing)
        with pytest.raises(CleanupUnknown):
            await owner.close()
        assert "area_close" not in calls

    asyncio.run(exercise())


def test_execution_stop_while_authenticated_body_and_query_are_pending(monkeypatch, tmp_path):
    """Actual ASGI boundary/owner; external DB and physical stop ports are inert."""
    from isaaclab_arena.agentic_environment_generation.workflow.admin import WorkflowScopeAdmin
    from isaaclab_arena.agentic_environment_generation.workflow.api.application import Composition, Settings, create_app
    from isaaclab_arena.agentic_environment_generation.workflow.api.security import TokenRegistry
    from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding

    async def exercise():
        binding = ScopeBinding(
            database="db", deployment_id="deployment", workspace_id="workspace", schema_version=1,
            authority_id="authority", operational_schema_version=1, artifact_marker_schema=1,
            store_id="store", registry_id="registry",
        )
        tokens = TokenRegistry(binding=binding, instance="instance", generation=1, clock=lambda: 100.0)
        owner, calls = owner_fixture(tokens=tokens)
        bearer = tokens.issue(principal="operator", lifetime=100)
        auth = tokens.authenticate(("Bearer " + bearer).encode())
        monkeypatch.setattr(WorkflowScopeAdmin, "verify_current_resources", lambda *a, **kw: object())
        driver = SimpleNamespace(close=lambda: calls.append("driver_close"))
        composition = Composition(
            lambda: driver, lambda d: owner.root.store, owner.root.authority,
            "admin", "operator", lambda value: None, tokens, lambda *a: owner,
        )
        app = create_app(settings=Settings(binding, tmp_path, ()), composition=composition)
        body_entered, body_release = asyncio.Event(), asyncio.Event()
        query_entered, query_release = Event(), Event()
        responses = []

        async def receive():
            body_entered.set()
            await body_release.wait()
            return {"type": "http.request", "body": b"invalid", "more_body": False}

        async def send(message):
            responses.append(message)

        def query():
            query_entered.set()
            assert query_release.wait(3)

        scope = dict(
            type="http", asgi={"version": "3.0"}, http_version="1.1", method="POST", scheme="http",
            path="/graphql", raw_path=b"/graphql", query_string=b"", root_path="",
            headers=[(b"authorization", ("Bearer " + bearer).encode()), (b"content-type", b"application/json")],
            client=("127.0.0.1", 1), server=("127.0.0.1", 2),
        )
        async with app.router.lifespan_context(app):
            request = asyncio.create_task(app(scope, receive, send))
            pending_query = asyncio.create_task(app.state.query_context.executor.run(query))
            try:
                await asyncio.wait_for(body_entered.wait(), 1)
                await wait_until(query_entered.is_set)
                app.state.request_execution_stop()
                assert not app.state.ready
                with pytest.raises(PermissionError):
                    tokens.recheck(auth)
                await wait_until(lambda: "stop" in calls)
                assert "stop" in calls, "stop waited for HTTP/query drain"
                assert not request.done() and not pending_query.done()
                assert "area_close" not in calls and "driver_close" not in calls
            finally:
                body_release.set()
                query_release.set()
                await request
                await pending_query
        assert owner._closed and calls[-1] == "driver_close"
        assert responses[0]["type"] == "http.response.start" and responses[0]["status"] == 400

    asyncio.run(exercise())


def test_execution_cleanup_error_is_observable_and_never_releases_area():
    async def exercise():
        owner, calls = owner_fixture()
        owner.root._recoveries["run"] = object()
        with pytest.raises(CleanupUnknown):
            await owner.close()
        assert owner.cleanup_unknown and not owner._closed
        with pytest.raises(CleanupUnknown):
            await owner.close()
        assert calls.count("root_close") == 1 and "area_close" not in calls

    asyncio.run(exercise())
