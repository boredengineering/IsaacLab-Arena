# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Actual ASGI + disposable Neo4j, never a mock API or worker cohort."""

import asyncio
import json
import os
import threading
import uuid
from pathlib import Path

import httpx
import pytest
from neo4j import GraphDatabase

from isaaclab_arena.agentic_environment_generation.workflow.api.application import (
    Composition,
    Settings,
    create_app,
)
from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
    Neo4jWorkflowStore,
)
from isaaclab_arena.agentic_environment_generation.workflow.profiles import (
    ProfileRegistration,
)
from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import (
    ScopeBinding,
)
from isaaclab_arena.agentic_environment_generation.workflow.service import (
    WorkflowProfileAdmin,
)

DOCUMENTS = Path(__file__).parent / "test_data/workflow_graphql"


def test_discover_writer_runs_events_and_exact_profile(prepared):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )

    settings, composition, store, driver, _ = prepared
    raw = canonical_json(retained_contract())
    expected = [
        store.admit("discover-a", raw, raw, 10),
        store.admit("discover-b", raw, raw, 10),
    ]

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                response = await client.post(
                    "/graphql",
                    json={
                        "query": (DOCUMENTS / "discovery.graphql").read_text(),
                        "variables": {"first": 1, "revision": str(2**63 - 1)},
                    },
                )
                body = response.json()
                assert "errors" not in body, "retained discovery queries unavailable"
                value = body["data"]
                assert value["workflowProfile"]["revision"] == str(2**63 - 1)
                page = value["workflows"]
                assert page["semantics"] == "live_keyset" and page["hasMore"] is True
                assert page["nodes"][0]["id"] == min(r.run_id for r in expected)
                assert page["nodes"][0]["version"] == "1"
                event_page = value["workflowEvents"]
                assert event_page["events"][0]["operationId"] == "discover-a"
                assert event_page["hasMore"] is True
                response = await client.post(
                    "/graphql",
                    json={
                        "query": (DOCUMENTS / "discovery.graphql").read_text(),
                        "variables": {
                            "first": 1,
                            "after": page["endCursor"],
                            "revision": str(2**63 - 1),
                        },
                    },
                )
                second = response.json()["data"]["workflows"]
                assert second["nodes"][0]["id"] == max(r.run_id for r in expected)
                assert second["hasMore"] is False

    asyncio.run(scenario())
    with driver.session(database=store.database) as session:
        actual = session.run(
            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) RETURN r.run_id AS"
            " id ORDER BY id",
            **store.scope,
        ).data()
    assert [row["id"] for row in actual] == sorted(r.run_id for r in expected)


def test_atomic_inspection_and_immutable_submission(prepared):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )

    settings, composition, store, driver, _ = prepared
    raw = canonical_json(retained_contract(existing=True))
    run = store.admit("inspect-source", raw, raw, 10)
    store.request_cancel(run.run_id, run.version)
    direct = store.get_run_inspection(run.run_id)

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                response = await client.post(
                    "/graphql",
                    json={
                        "query": (DOCUMENTS / "inspection.graphql").read_text(),
                        "variables": {"id": run.run_id, "operation": "inspect-source"},
                    },
                )
                body = response.json()
                assert "errors" not in body, "atomic inspection/submission query unavailable"
                result = body["data"]["workflow"]
                assert result["__typename"] == "Workflow"
                assert result["state"] == "cancelled" and result["version"] == str(direct.intent.run_version)
                assert result["retainedRevision"] == direct.retained_revision
                assert result["frozenIntent"]["source"] == {
                    "__typename": "ExistingSource",
                    "identity": "candidate-1",
                    "content": "opaque-yaml",
                }
                assert {k: result["budget"]["reserved"][k] for k in ("modelCalls", "costCeilingUsd")} == {
                    "modelCalls": "0",
                    "costCeilingUsd": "0",
                }
                assert {k: result["budget"]["remaining"][k] for k in ("modelCalls", "costCeilingUsd")} == {
                    "modelCalls": "8",
                    "costCeilingUsd": "1.0",
                }
                assert result["cleanup"]["currentScopeOwner"] is None and result["cleanup"]["intents"] == []
                assert result["scene"] is None and result["readiness"] == []
                assert result["policyOutcome"] == "not_requested" and result["publicationOutcome"] == "not_permitted"
                receipt = body["data"]["workflowSubmission"]
                assert receipt["disposition"] == "retained_admission" and receipt["runId"] == run.run_id
                assert receipt["receiptVersion"] is None and receipt["causeId"] is None

    asyncio.run(scenario())
    assert store.get_run_inspection(run.run_id).retained_revision == direct.retained_revision


def test_command_kinds_and_decision_coverage(prepared):
    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        LocalStopObservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )

    settings, composition, store, driver, _ = prepared
    raw = canonical_json(retained_contract())
    run = store.admit("same-key", raw, raw, 10)
    cancel = store.cancel_command(
        "same-key",
        run.run_id,
        LocalStopObservation(delivery="no_owner"),
        protect=lambda _: None,
    )
    resume = store.admit_resume(
        "same-key",
        {
            "runId": run.run_id,
            "expectedVersion": cancel.after_version,
            "renewAuthorization": False,
        },
        selection=None,
        eligibility=None,
        protect=lambda _: None,
    ).receipt

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            for legacy in (False, True):
                if legacy:
                    with driver.session(database=store.database) as session:
                        session.run(
                            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id,"
                            " run_id:$id}) REMOVE r.decision_coverage",
                            **store.scope,
                            id=run.run_id,
                        ).consume()
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://isolated",
                    trust_env=False,
                    headers=composition.authority.headers,
                ) as client:
                    response = await client.post(
                        "/graphql",
                        json={
                            "query": (DOCUMENTS / "receipts.graphql").read_text(),
                            "variables": {"id": run.run_id, "operation": "same-key"},
                        },
                    )
                    body = response.json()
                    assert "errors" not in body, "command/decision queries unavailable"
                    value = body["data"]
                    assert value["submit"]["disposition"] == "retained_admission"
                    assert value["cancel"]["receiptDigest"] == cancel.receipt_digest
                    assert value["resume"]["receiptDigest"] == resume.receipt_digest
                    assert value["resume"]["reason"] == "inactive_run"
                    decisions = value["workflow"]["decisions"]
                    if legacy:
                        assert (
                            decisions["__typename"] == "DecisionCoverageUnavailable"
                            and decisions["reason"] == "coverage_provenance_unavailable"
                        )
                    else:
                        assert decisions["__typename"] == "DecisionConnection" and decisions["nodes"] == []

    asyncio.run(scenario())
    with driver.session(database=store.database) as session:
        row = session.run(
            "MATCH (c:ArenaCancelReceipt {deployment_id:$deployment_id,"
            " workspace_id:$workspace_id})-[:CAUSED]->(e:ArenaWorkflowEvent) RETURN c.operation_id AS operation,"
            " e.run_id AS id, e.command_kind AS kind",
            **store.scope,
        ).single(strict=True)
        assert dict(row) == {
            "operation": "same-key",
            "id": run.run_id,
            "kind": "CANCEL",
        }


def test_unauthenticated_request_rejected_before_body_or_read(prepared):
    settings, composition, store, driver, screens = prepared

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            before = len(screens)
            reads = []
            messages = []

            async def receive():
                reads.append(True)
                return {
                    "type": "http.request",
                    "body": json.dumps({"query": (DOCUMENTS / "catalogue.graphql").read_text()}).encode(),
                    "more_body": False,
                }

            async def send(message):
                messages.append(message)

            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/graphql",
                "raw_path": b"/graphql",
                "query_string": b"",
                "headers": [(b"content-type", b"application/json")],
                "server": ("isolated", 80),
                "client": ("127.0.0.1", 1),
            }
            await app(scope, receive, send)
            assert messages[0]["status"] == 401, "unauthenticated request reached query endpoint"
            assert reads == [] and len(screens) == before

    asyncio.run(scenario())


def test_transport_prevalidation_bounds_without_partial_resolver_io(prepared, monkeypatch):
    settings, composition, store, driver, _ = prepared
    calls = []
    original = Neo4jWorkflowStore.list_profiles

    def observed(self):
        calls.append(True)
        return original(self)

    monkeypatch.setattr(Neo4jWorkflowStore, "list_profiles", observed)

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                cases = [
                    json.dumps({"query": "{ workflowProfiles { __typename } workflows(first:1001) { __typename } }"}),
                    '{"query":"{bad_SENTINEL}","query":"{workflowProfiles {__typename}}"}',
                    json.dumps(
                        {"query": "{ " + " ".join("a%d: workflowProfiles { __typename }" % i for i in range(17)) + " }"}
                    ),
                    json.dumps({
                        "query": "query One {workflowProfiles {__typename}} query Two {workflowProfiles {__typename}}",
                        "operationName": "One",
                    }),
                    json.dumps(
                        {"query": "{ workflowProfiles {...Cycle}} fragment Cycle on ProfileListResult {...Cycle}"}
                    ),
                    json.dumps({"query": "mutation { credential_SENTINEL }"}),
                    json.dumps({"query": "{__schema {queryType {name}}}"}),
                    json.dumps({"query": "{unknown_SENTINEL}"}),
                    '{"query": "{workflowProfiles{__typename}}", "variables": {"bad": NaN}}',
                    "[]",
                    "{",
                    " " * 65537,
                ]
                for body in cases:
                    response = await client.post(
                        "/graphql",
                        content=body,
                        headers={"Content-Type": "application/json"},
                    )
                    assert response.status_code == 400, "transport prevalidation not enforced"
                    assert "SENTINEL" not in response.text
                assert calls == [], "overbudget query performed a partial resolver read"

    asyncio.run(scenario())


def test_owned_offload_keeps_cancelled_capacity_and_drains(prepared, monkeypatch):
    settings, composition, store, driver, _ = prepared
    original = Neo4jWorkflowStore.list_profiles
    release = threading.Event()
    entered = []
    finished = []

    def blocked(self):
        import sys

        hook = sys.getprofile()
        assert hook is not None and hook.__self__.query_only
        assert hook.__self__.fixed_spec is None
        result = original(self)  # real Neo4j read before the controlled worker barrier
        entered.append(threading.get_ident())
        assert release.wait(5), "test barrier timed out"
        finished.append(threading.get_ident())
        return result

    monkeypatch.setattr(Neo4jWorkflowStore, "list_profiles", blocked)

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        tasks = []
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:

                async def query():
                    return await client.post(
                        "/graphql",
                        json={"query": "{workflowProfiles {__typename ... on QueryFailure {code}}}"},
                    )

                try:
                    tasks = [asyncio.create_task(query()) for _ in range(4)]
                    for _ in range(100):
                        if len(entered) == 2:
                            break
                        await asyncio.sleep(0.01)
                    assert len(entered) == 2, "whole service reads not offloaded"
                    tasks[0].cancel()
                    await asyncio.sleep(0.02)
                    fifth = asyncio.create_task(query())
                    tasks.append(fifth)
                    await asyncio.wait({fifth}, timeout=0.25)
                    assert fifth.done(), "cancelled awaiter released capacity or jobs were unbounded"
                    body = fifth.result().json()
                    assert body["data"]["workflowProfiles"] == {
                        "__typename": "QueryFailure",
                        "code": "OVERLOADED",
                    }
                    assert len(entered) == 2
                finally:
                    release.set()
                    await asyncio.gather(*tasks, return_exceptions=True)
        assert len(finished) == 4, "close did not drain cancelled worker ownership"

    asyncio.run(scenario())


def test_typed_cursor_corruption_and_outage_outcomes(prepared, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
        StoreUnavailable,
    )

    settings, composition, store, driver, _ = prepared

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                response = await client.post(
                    "/graphql",
                    json={"query": '{workflows(first:1,after:"malformed") {__typename ... on QueryFailure {code}}}'},
                )
                body = response.json()
                assert body.get("data", {}).get("workflows") == {
                    "__typename": "QueryFailure",
                    "code": "INVALID_CURSOR",
                }, "typed cursor failure missing"
                response = await client.post(
                    "/graphql",
                    json={"query": '{workflow(id:"missing") {__typename ... on NotFound {code}}}'},
                )
                assert response.json()["data"]["workflow"]["__typename"] == "NotFound"
                with driver.session(database=store.database) as session:
                    session.run(
                        "MATCH (p:ArenaWorkflowProfileRevision {deployment_id:$deployment_id,"
                        " workspace_id:$workspace_id}) SET p.body_json=$bad",
                        **store.scope,
                        bad="PRIVATE_SENTINEL",
                    ).consume()
                response = await client.post(
                    "/graphql",
                    json={"query": "{workflowProfiles {__typename ... on QueryFailure {code}}}"},
                )
                assert response.json()["data"]["workflowProfiles"]["code"] == "CORRUPT"
                assert "PRIVATE_SENTINEL" not in response.text
                for error, expected in [
                    (StoreUnavailable("PRIVATE_SENTINEL"), "UNAVAILABLE"),
                    (RuntimeError("PRIVATE_SENTINEL"), "UNKNOWN"),
                ]:

                    def fail(self):
                        raise error

                    monkeypatch.setattr(Neo4jWorkflowStore, "list_profiles", fail)
                    response = await client.post(
                        "/graphql",
                        json={"query": "{workflowProfiles {__typename ... on QueryFailure {code}}}"},
                    )
                    assert response.json()["data"]["workflowProfiles"]["code"] == expected
                    assert "PRIVATE_SENTINEL" not in response.text

    asyncio.run(scenario())


def test_failed_boot_is_sanitized_and_closes_only_owned_driver(prepared):
    from dataclasses import replace

    settings, composition, store, driver, _ = prepared
    closed = []

    class OwnedDriver:
        def __init__(self):
            self.real = driver_factory()

        def close(self):
            self.real.close()
            closed.append(threading.get_ident())

    def broken_factory(owned):
        raise ValueError("PRIVATE_BOOT_SENTINEL")

    failing = replace(composition, create_driver=OwnedDriver, create_store=broken_factory)

    async def scenario():
        app = create_app(settings=settings, composition=failing)
        try:
            async with app.router.lifespan_context(app):
                pytest.fail("failed verification became ready")
        except ValueError as error:
            assert str(error) == "Workflow API not ready", "startup failure leaked raw diagnostics"

    asyncio.run(scenario())
    assert len(closed) == 1 and closed[0] != threading.get_ident()
    with driver.session(database=store.database) as session:
        assert session.run("RETURN 1 AS n").single()["n"] == 1


def test_query_only_capability_and_action_permission(prepared):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )

    settings, composition, store, driver, _ = prepared
    raw = canonical_json(retained_contract())
    run = store.admit("actions", raw, raw, 10)
    direct = store.get_run_inspection(run.run_id)

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                query = (DOCUMENTS / "capabilities.graphql").read_text()
                response = await client.post("/graphql", json={"query": query, "variables": {"id": run.run_id}})
                body = response.json()
                assert "errors" not in body, "query-only capability metadata missing"
                capabilities = body["data"]["capabilities"]
                assert capabilities["queryOnly"] and capabilities["configuredReadStore"]
                assert capabilities["observedExecutionReadiness"] == "not_checked"
                assert "execution" in capabilities["unsupported"] and "scene_detail" in capabilities["unsupported"]
                view = body["data"]["workflow"]
                assert view["availableActions"] == []
                assert view["actions"]["cancelApplicable"] is True
                assert view["actions"]["permission"]["cancel"] == view["actions"]["permission"]["resume"] == "denied"
                assert view["retainedRevision"] == direct.retained_revision
                assert view["responseRevision"] != view["retainedRevision"]

    asyncio.run(scenario())


def test_finite_auth_headers_generation_and_worker_recheck(prepared, monkeypatch):
    settings, composition, store, driver, screens = prepared
    registry = composition.tokens
    now = [100.0]
    registry.clock = lambda: now[0]
    good = registry.issue(principal="scoped-reader", lifetime=10.0)
    context = registry.authenticate(("Bearer " + good).encode())

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/graphql",
                "raw_path": b"/graphql",
                "query_string": b"",
                "server": ("isolated", 80),
                "client": ("127.0.0.1", 1),
            }
            auth = (b"authorization", ("Bearer " + good).encode())
            basic = [auth, (b"content-type", b"application/json")]
            cases = [
                [],
                [auth, auth],
                [(b"authorization", b"bearer invalid")],
                basic + [(b"cookie", b"ignored")],
                basic + [(b"origin", b"http://isolated")],
                basic + [(b"forwarded", b"for=local")],
                basic + [(b"x-forwarded-user", b"operator")],
                basic + [(b"content-type", b"application/json")],
            ]

            async def denied(headers, method="POST"):
                bodies, output = [], []
                before = len(screens)

                async def receive():
                    bodies.append(True)
                    return {"type": "http.request", "body": b"{}", "more_body": False}

                async def send(message):
                    output.append(message)

                await app(dict(scope, headers=headers, method=method), receive, send)
                assert output[0]["status"] in (400, 401)
                assert bodies == [] and len(screens) == before

            for headers in cases:
                await denied(headers)
            await denied(basic, "GET")
            now[0] = 110.0
            await denied(basic)
            now[0] = 100.0
            registry.revoke(context)
            await denied(basic)
            renewed = registry.issue(principal="scoped-reader", lifetime=10.0)
            registry.rotate()
            await denied([(b"authorization", ("Bearer " + renewed).encode()), basic[1]])
            # Valid at transport entry, revoked after queue admission, before worker IO.
            token = registry.issue(principal="scoped-reader", lifetime=10.0)
            auth_context = registry.authenticate(("Bearer " + token).encode())
            release = threading.Event()
            started = []
            pool = app.state.query_context.executor

            def barrier():
                started.append(True)
                assert release.wait(5)

            tasks = [asyncio.create_task(pool.run(barrier)) for _ in range(2)]
            try:
                for _ in range(100):
                    if len(started) == 2:
                        break
                    await asyncio.sleep(0.01)
                assert len(started) == 2
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://isolated",
                    trust_env=False,
                    headers={"Authorization": "Bearer " + token},
                ) as client:
                    pending = asyncio.create_task(
                        client.post(
                            "/graphql",
                            json={"query": "{workflowProfiles {__typename ... on QueryFailure {code}}}"},
                        )
                    )
                    await asyncio.sleep(0.03)
                    registry.revoke(auth_context)
                    before = len(screens)
                    release.set()
                    response = await pending
                    assert response.json()["data"]["workflowProfiles"]["code"] == "FORBIDDEN"
                    assert len(screens) == before + 1  # whole response only, no service protection/read
            finally:
                release.set()
                await asyncio.gather(*tasks)

    asyncio.run(scenario())


def test_open_verification_uses_only_match_show_and_never_repairs(prepared):
    from dataclasses import replace

    settings, composition, store, driver, screens = prepared
    queries, closes = [], []

    class Tx:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

        def run(self, query, *args, **kwargs):
            queries.append(query)
            assert query.startswith(("MATCH ", "SHOW "))
            assert not any(word in query for word in ("SET ", "CREATE ", "MERGE ", "DELETE ", "CALL "))
            return self.real.run(query, *args, **kwargs)

    class Session:
        def __init__(self, real):
            self.real = real

        def begin_transaction(self, **kwargs):
            return Tx(self.real.begin_transaction(**kwargs))

        def close(self):
            self.real.close()

    class OwnedDriver:
        def __init__(self):
            self.real = driver_factory()

        def session(self, **kwargs):
            return Session(self.real.session(**kwargs))

        def close(self):
            self.real.close()
            closes.append(threading.get_ident())

    original_bytes = {
        str(p.relative_to(settings.artifact_root)): p.read_bytes()
        for p in settings.artifact_root.rglob("*")
        if p.is_file()
    }

    async def boot(selected, fail):
        app = create_app(
            settings=selected,
            composition=replace(composition, create_driver=OwnedDriver),
        )
        if fail:
            with pytest.raises(ValueError, match="^Workflow API not ready$"):
                async with app.router.lifespan_context(app):
                    pytest.fail("missing resources were initialized")
        else:
            async with app.router.lifespan_context(app):
                assert app.state.resources.binding == settings.binding

    asyncio.run(boot(settings, False))
    assert queries and len(closes) == 1
    assert all(t != threading.get_ident() for t in closes)
    missing = replace(settings, artifact_root=settings.artifact_root.parent / "missing")
    asyncio.run(boot(missing, True))
    assert not missing.artifact_root.exists()
    with driver.session(database=store.database) as session:
        session.run(
            "MATCH (p:ArenaWorkflowProfileRevision {deployment_id:$deployment_id, workspace_id:$workspace_id}) DETACH"
            " DELETE p",
            **store.scope,
        ).consume()
    asyncio.run(boot(settings, True))
    assert len(closes) == 3
    assert original_bytes == {
        str(p.relative_to(settings.artifact_root)): p.read_bytes()
        for p in settings.artifact_root.rglob("*")
        if p.is_file()
    }


def test_read_protection_veto_includes_aliases_and_errors(prepared):
    from dataclasses import replace

    settings, composition, store, driver, screens = prepared
    rejected = []

    def protect(value):
        if isinstance(value, dict) and ("errors" in value or "ALIAS_SENTINEL" in json.dumps(value)):
            rejected.append(True)
            raise ValueError("PRIVATE_PROTECTION_SENTINEL")
        composition.protect(value)

    async def scenario():
        app = create_app(settings=settings, composition=replace(composition, protect=protect))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                for query in (
                    "{ALIAS_SENTINEL:workflowProfiles {__typename}}",
                    "{MISSING_SENTINEL}",
                ):
                    response = await client.post("/graphql", json={"query": query})
                    assert response.status_code == 403 and response.content == b""

    asyncio.run(scenario())
    assert len(rejected) == 2


def test_reserved_generation_reference_readiness_and_full_width(prepared):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        AuthorizationSnapshot,
        GenerationReservation,
        ReadinessReceipt,
        ReadyProfile,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
        contract_digest,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import (
        required_dependencies,
    )

    settings, composition, store, driver, _ = prepared
    store.clock = lambda: 100.0
    contract = retained_contract()
    raw = canonical_json(contract)
    run = store.admit("reserved-reference", raw, raw, 10)
    auth = AuthorizationSnapshot(
        database=store.database,
        **store.scope,
        principal="synthetic-writer",
        grant_ref="synthetic-never-released",
        contract_digest=contract_digest(contract),
        expires_at=200.0,
        capabilities=("generation_model", "operational_writes"),
    )
    ready = ReadinessReceipt(
        contract_digest=contract_digest(contract),
        checked_at=100.0,
        profiles=tuple(
            ReadyProfile(
                role=r.dependency_id,
                profile_id=r.profile_id,
                settings_sha256=r.profile_sha256,
                expected_instance_id=r.instance_id,
                observed_instance_id=r.instance_id,
            )
            for r in required_dependencies(contract)
        ),
    )
    intent = store.reserve_generation(
        run.run_id,
        1,
        "reference-decision",
        auth,
        GenerationReservation(
            model_calls=1,
            model_tokens=100,
            cost_ceiling_usd=0.1,
            runtime_allowance_seconds=5.0,
        ),
        readiness=ready,
    )
    with driver.session(database=store.database) as session:
        row = session.run(
            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id,"
            " run_id:$id})-[:HAS_DECISION]->(d:ArenaWorkflowDecision) RETURN d.decision_id AS id, d.record_kind AS"
            " kind",
            **store.scope,
            id=run.run_id,
        ).single(strict=True)
        assert dict(row) == {
            "id": "reference-decision",
            "kind": "generation_reservation",
        }
        session.run(
            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id, run_id:$id}) SET"
            " r.version=$high",
            **store.scope,
            id=run.run_id,
            high=2**63 - 1,
        ).consume()

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                response = await client.post(
                    "/graphql",
                    json={
                        "query": (DOCUMENTS / "inspection.graphql").read_text(),
                        "variables": {
                            "id": run.run_id,
                            "operation": "reserved-reference",
                        },
                    },
                )
                view = response.json()["data"]["workflow"]
                assert view["version"] == str(2**63 - 1)
                assert {k: view["budget"]["reserved"][k] for k in ("modelCalls", "costCeilingUsd")} == {
                    "modelCalls": "1",
                    "costCeilingUsd": "0.1",
                }
                assert {k: view["budget"]["remaining"][k] for k in ("modelCalls", "costCeilingUsd")} == {
                    "modelCalls": "7",
                    "costCeilingUsd": "0.9",
                }
                assert [{k: r[k] for k in ("intentId", "currentReadiness")} for r in view["readiness"]] == [
                    {"intentId": intent, "currentReadiness": "unknown"}
                ]
                assert [
                    {k: i[k] for k in ("intentId", "cleanupState", "releaseState")} for i in view["cleanup"]["intents"]
                ] == [{
                    "intentId": intent,
                    "cleanupState": "not_started",
                    "releaseState": "known_unreleased",
                }]
                response = await client.post(
                    "/graphql",
                    json={
                        "query": (DOCUMENTS / "receipts.graphql").read_text(),
                        "variables": {
                            "id": run.run_id,
                            "operation": "reserved-reference",
                        },
                    },
                )
                assert response.json()["data"]["workflow"]["decisions"]["nodes"] == [{
                    "runId": run.run_id,
                    "decisionId": "reference-decision",
                    "recordKind": "generation_reservation",
                    "detailSupported": False,
                }]

    asyncio.run(scenario())


def test_typed_policy_trial_projection_preserves_pins_and_episode_denominator():
    """Actual Strawberry serialization, synthetic supplied receipt; not native execution."""
    import strawberry

    from isaaclab_arena.agentic_environment_generation.workflow.api.schema import PolicyTrial, policy_trial_view
    from isaaclab_arena.agentic_environment_generation.workflow.policy_contracts import (
        PolicyEpisode,
        PolicyTrialReceipt,
    )
    from isaaclab_arena.tests.test_environment_workflow_evidence import policy_binding

    binding = policy_binding()
    receipt = PolicyTrialReceipt(
        intent_id="1" * 64,
        episode_records_digest="2" * 64,
        manifest_digest="3" * 64,
        binding=binding,
        policy_steps=10,
        prerequisite_steps=4,
        episodes=tuple(
            PolicyEpisode(
                binding_digest=binding.digest(),
                episode_id=f"e{i}",
                reset_id=f"reset-{i + 1}",
                seed=binding.seed,
                success=success,
            )
            for i, success in enumerate((True, False))
        ),
    )

    @strawberry.type
    class Projection:
        @strawberry.field
        def trial(self) -> PolicyTrial:
            value = policy_trial_view(receipt)
            assert value is not None
            return value

    result = strawberry.Schema(query=Projection).execute_sync("""{trial {
        intentId manifestDigest episodeRecordsDigest policySteps prerequisiteSteps
        binding {candidateDigest contractDigest policyArtifactDigest taskDefinitionDigest evaluatorDigest
                 embodimentId taskId instruction seed maxEpisodes deadlineUnix}
        episodes {episodeId resetId seed success bindingDigest}
    }}""")
    assert not result.errors
    actual = result.data["trial"]
    assert actual["intentId"] == receipt.intent_id and actual["manifestDigest"] == receipt.manifest_digest
    assert actual["episodeRecordsDigest"] == receipt.episode_records_digest
    assert actual["policySteps"] == "10" and actual["prerequisiteSteps"] == "4"
    assert actual["binding"]["candidateDigest"] == binding.candidate_digest
    assert actual["binding"]["policyArtifactDigest"] == binding.policy_artifact_digest
    assert actual["binding"]["instruction"] == binding.instruction
    assert actual["binding"]["maxEpisodes"] == "2"
    assert [row["success"] for row in actual["episodes"]] == [True, False]
    assert [row["resetId"] for row in actual["episodes"]] == ["reset-1", "reset-2"]


def test_export_selected_schema_and_operation_documents():
    import hashlib

    from graphql import parse, validate

    from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema

    assert schema._schema.mutation_type is None and schema._schema.subscription_type is None
    coverage = {}
    for path in sorted(DOCUMENTS.glob("*.graphql")):
        raw = path.read_bytes()
        assert not validate(schema._schema, parse(raw.decode()))
        coverage[path.name] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "validated": True,
        }
    Path("/evidence/schema.graphql").write_text(schema.as_str())
    Path("/evidence/operation-coverage.json").write_text(json.dumps(coverage, indent=2))


def test_scope_cursor_families_foreign_parent_future_and_gap(prepared):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.paging import (
        DecisionPosition,
        EventPosition,
        RunPosition,
        encode_cursor,
    )

    settings, composition, store, driver, _ = prepared
    raw = canonical_json(retained_contract())
    run = store.admit("cursor-run", raw, raw, 10)
    another = store.admit("cursor-other", raw, raw, 10)
    binding = settings.binding
    foreign = binding.model_copy(update={"workspace_id": "foreign"})
    cases = [
        (
            "workflows",
            encode_cursor(foreign, RunPosition(position=run.run_id)),
            "CURSOR_SCOPE_MISMATCH",
        ),
        (
            "workflows",
            encode_cursor(binding, EventPosition(position="0", floor="0", ceiling="2")),
            "CURSOR_QUERY_MISMATCH",
        ),
        (
            "workflowEvents",
            encode_cursor(binding, EventPosition(position="3", floor="0", ceiling="3")),
            "FUTURE_CURSOR",
        ),
    ]

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                for field, cursor, expected in cases:
                    response = await client.post(
                        "/graphql",
                        json={
                            "query": (
                                "query($after:String!){"
                                + field
                                + "(first:1,after:$after){__typename ... on QueryFailure {code}}}"
                            ),
                            "variables": {"after": cursor},
                        },
                    )
                    assert response.json()["data"][field]["code"] == expected
                cursor = encode_cursor(
                    binding,
                    DecisionPosition(run_id=another.run_id, position="decision"),
                )
                response = await client.post(
                    "/graphql",
                    json={
                        "query": (
                            "query($id:ID!,$after:String!){workflow(id:$id){... on Workflow"
                            " {decisions(first:1,after:$after){... on QueryFailure {code}}}}}"
                        ),
                        "variables": {"id": run.run_id, "after": cursor},
                    },
                )
                assert response.json()["data"]["workflow"]["decisions"]["code"] == "CURSOR_QUERY_MISMATCH"
                cursor = encode_cursor(binding, EventPosition(position="0", floor="0", ceiling="2"))
                # Explicit synthetic retention-floor mutation, not API pruning.
                with driver.session(database=store.database) as session:
                    session.run(
                        "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) SET"
                        " c.floor=1",
                        **store.scope,
                    ).consume()
                response = await client.post(
                    "/graphql",
                    json={
                        "query": (
                            "query($after:String!){workflowEvents(first:1,after:$after){... on QueryFailure {code}}}"
                        ),
                        "variables": {"after": cursor},
                    },
                )
                assert response.json()["data"]["workflowEvents"]["code"] == "REPLAY_GAP"

    asyncio.run(scenario())


def test_scope_schema_mismatch_boot_and_close_failure(prepared):
    from dataclasses import replace

    settings, composition, store, driver, _ = prepared

    async def denied(settings, composition):
        app = create_app(settings=settings, composition=composition)
        with pytest.raises(ValueError, match="^Workflow API not ready$"):
            async with app.router.lifespan_context(app):
                pytest.fail("mismatched boot became ready")
        assert app.state.ready is False

    foreign = replace(
        composition,
        create_store=lambda d: Neo4jWorkflowStore(
            d,
            database=store.database,
            deployment_id=store.scope["deployment_id"],
            workspace_id="missing-scope",
        ),
    )
    asyncio.run(denied(settings, foreign))
    # Remove one owned DB index administratively, then restore outside application.
    ddl = next(q for q in Neo4jWorkflowStore.schema_requirements() if q.startswith("CREATE INDEX"))
    name = ddl.split()[2]
    with driver.session(database=store.database) as session:
        session.run("DROP INDEX " + name).consume()
    try:
        asyncio.run(denied(settings, composition))
    finally:
        with driver.session(database=store.database) as session:
            session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(30)").consume()
    closed = []

    class CloseFailure:
        def __init__(self):
            self.real = driver_factory()

        def session(self, **kwargs):
            return self.real.session(**kwargs)

        def close(self):
            self.real.close()
            closed.append(True)
            raise RuntimeError("PRIVATE_CLOSE_SENTINEL")

    async def bad_close():
        app = create_app(
            settings=settings,
            composition=replace(composition, create_driver=CloseFailure),
        )
        with pytest.raises(ValueError, match="^Workflow API resource close failed$"):
            async with app.router.lifespan_context(app):
                assert app.state.ready
        assert not app.state.ready

    asyncio.run(bad_close())
    assert closed == [True]


def test_stream_json_depth_tokens_and_expansion_limits(prepared):
    settings, composition, store, driver, screens = prepared

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                cases = [
                    json.dumps({
                        "query": "{workflowProfiles{__typename}}",
                        "variables": {"n": 10**100},
                    }),
                    json.dumps(
                        {"query": "{" + "... on Query {" * 17 + "workflowProfiles {__typename}" + "}" * 17 + "}"}
                    ),
                    json.dumps({"query": "{" + "a:__typename " * 700 + "}"}),
                    json.dumps({
                        "query": (
                            '{workflow(id:"missing"){... on Workflow {'
                            + " ".join("a%d:state" % i for i in range(17))
                            + "}}}"
                        )
                    }),
                    '{"query":"{workflowProfiles{__typename}}","variables":{"n":1e999}}',
                    '{"query":"{workflowProfiles{__typename}}","variables":' + ("[" * 33) + "0" + ("]" * 33) + "}",
                    json.dumps({"query": "{workflowProfiles{__typename}}" + " #padding" * 2100}),
                    json.dumps({
                        "query": "query($n:Int!){workflows(first:$n){__typename}}",
                        "variables": {"n": True},
                    }),
                    json.dumps({"query": "{workflows(first:501){__typename} workflowEvents(first:500){__typename}}"}),
                ]
                # The first case is unused variable metadata, not an Int coercion error: bounded JSON accepts it.
                positive = await client.post(
                    "/graphql",
                    content=cases.pop(0),
                    headers={"Content-Type": "application/json"},
                )
                assert positive.status_code == 200
                for raw in cases:
                    response = await client.post(
                        "/graphql",
                        content=raw,
                        headers={"Content-Type": "application/json"},
                    )
                    assert response.status_code == 400

                async def stream():
                    for _ in range(9):
                        yield b" " * 8192

                response = await client.post(
                    "/graphql",
                    content=stream(),
                    headers={"Content-Type": "application/json"},
                )
                assert response.status_code == 400
                response = await client.post(
                    "/graphql",
                    content="{}",
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": "65537",
                    },
                )
                assert response.status_code == 400

    asyncio.run(scenario())


def test_complete_response_byte_bound(prepared):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        WorkflowContract,
        canonical_json,
    )

    settings, composition, store, driver, _ = prepared
    value = retained_contract(existing=True).model_dump(mode="json")
    value["source"]["content"] = '"' * (512 * 1024)
    raw = canonical_json(WorkflowContract.model_validate(value))
    run = store.admit("response-bound", raw, raw, 10)

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                query = (
                    "query($id:ID!){workflow(id:$id){... on Workflow {frozenIntent {source {... on ExistingSource {"
                    + " ".join("c%d:content" % i for i in range(16))
                    + "}}}}}}"
                )
                response = await client.post("/graphql", json={"query": query, "variables": {"id": run.run_id}})
                assert response.status_code == 503
                assert response.json() == {"errors": [{"message": "Response unavailable"}]}
                assert len(response.content) < 128

    asyncio.run(scenario())


def test_single_scope_admin_boot_fresh_clients_join_retained_queries(prepared):
    import hashlib

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        AuthorizationSnapshot,
        GenerationReservation,
        ReadinessReceipt,
        ReadyProfile,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        LocalStopObservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
        contract_digest,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import (
        required_dependencies,
    )

    settings, composition, store, driver, _ = prepared

    async def fresh(app, document, variables=None):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://isolated",
            trust_env=False,
            headers=composition.authority.headers,
        ) as client:
            response = await client.post(
                "/graphql",
                json={
                    "query": (DOCUMENTS / document).read_text(),
                    "variables": variables or {},
                },
            )
            assert response.status_code == 200 and "errors" not in response.json()
            return response.json()["data"]

    def facts():
        with driver.session(database=store.database) as session:
            rows = session.run(
                "MATCH (n {deployment_id:$deployment_id, workspace_id:$workspace_id}) RETURN labels(n) AS labels,"
                " properties(n) AS value",
                **store.scope,
            ).data()
        for row in rows:
            if "ArenaWorkflowControl" in row["labels"]:
                row["value"].pop("revision", None)  # cooperative lock bookkeeping, not domain history
        return sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            catalogue = await fresh(app, "catalogue.graphql")
            assert catalogue["workflowProfiles"]["profiles"][0]["revision"] == str(2**63 - 1)
            empty = await fresh(app, "discovery.graphql", {"first": 1, "revision": str(2**63 - 1)})
            assert empty["workflows"]["nodes"] == [] and empty["workflowEvents"]["events"] == []
            watermark = empty["workflows"]["eventWatermark"]
            store.clock = lambda: 100.0
            contract = retained_contract()
            raw = canonical_json(contract)
            run = store.admit("joined-key", raw, raw, 10)
            auth = AuthorizationSnapshot(
                database=store.database,
                **store.scope,
                principal="synthetic-writer",
                grant_ref="never-released",
                contract_digest=contract_digest(contract),
                expires_at=200.0,
                capabilities=("generation_model", "operational_writes"),
            )
            ready = ReadinessReceipt(
                contract_digest=contract_digest(contract),
                checked_at=100.0,
                profiles=tuple(
                    ReadyProfile(
                        role=r.dependency_id,
                        profile_id=r.profile_id,
                        settings_sha256=r.profile_sha256,
                        expected_instance_id=r.instance_id,
                        observed_instance_id=r.instance_id,
                    )
                    for r in required_dependencies(contract)
                ),
            )
            intent = store.reserve_generation(
                run.run_id,
                1,
                "joined-decision",
                auth,
                GenerationReservation(
                    model_calls=1,
                    model_tokens=100,
                    cost_ceiling_usd=0.1,
                    runtime_allowance_seconds=5.0,
                ),
                readiness=ready,
            )
            cancel = store.cancel_command(
                "joined-key",
                run.run_id,
                LocalStopObservation(delivery="no_owner"),
                protect=lambda _: None,
            )
            resume = store.admit_resume(
                "joined-key",
                {
                    "runId": run.run_id,
                    "expectedVersion": cancel.after_version,
                    "renewAuthorization": False,
                },
                selection=None,
                eligibility=None,
                protect=lambda _: None,
            ).receipt
            before = facts()
            discovery = await fresh(app, "discovery.graphql", {"first": 1, "revision": str(2**63 - 1)})
            assert discovery["workflows"]["nodes"][0]["id"] == run.run_id
            view = await fresh(app, "inspection.graphql", {"id": run.run_id, "operation": "joined-key"})
            assert view["workflow"]["frozenIntent"]["source"]["prompt"] == "Banana on maple table"
            receipts = await fresh(app, "receipts.graphql", {"id": run.run_id, "operation": "joined-key"})
            assert receipts["cancel"]["receiptDigest"] == cancel.receipt_digest
            assert receipts["resume"]["receiptDigest"] == resume.receipt_digest
            assert receipts["workflow"]["decisions"]["nodes"][0]["decisionId"] == "joined-decision"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                response = await client.post(
                    "/graphql",
                    json={
                        "query": (
                            "query($after:String!){workflowEvents(first:100,after:$after){... on WorkflowEventPage"
                            " {events {schemaVersion sequence kind sourceId commandKind commandOperationId}}}}"
                        ),
                        "variables": {"after": watermark},
                    },
                )
                events = response.json()["data"]["workflowEvents"]["events"]
                assert all(e["schemaVersion"] == 1 for e in events)
                assert [e["kind"] for e in events] == [
                    "WorkflowRequested",
                    "GenerationReserved",
                    "CancellationRequested",
                ]
                assert events[1]["sourceId"] == "joined-decision" and events[2]["commandOperationId"] == "joined-key"
            after = facts()
            assert before == after, "query mutated retained domain facts"
            with driver.session(database=store.database) as session:
                linked = session.run(
                    "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id,"
                    " workspace_id:$workspace_id})-[:HAS_INTENT]->(i:ArenaExecutionIntent),"
                    " (r)-[:HAS_DECISION]->(d:ArenaWorkflowDecision) RETURN r.run_id AS run, i.intent_id AS intent,"
                    " d.decision_id AS decision",
                    **store.scope,
                ).data()
                command_edges = session.run(
                    "MATCH (c:ArenaCancelReceipt"
                    " {deployment_id:$deployment_id,workspace_id:$workspace_id})-[:CAUSED]->(e:ArenaWorkflowEvent)"
                    " RETURN c.operation_id AS operation,e.sequence AS sequence,e.source_id AS source",
                    **store.scope,
                ).data()
            assert linked == [{"run": run.run_id, "intent": intent, "decision": "joined-decision"}]
            assert command_edges == [{
                "operation": "joined-key",
                "sequence": cancel.events[0].sequence,
                "source": run.run_id,
            }]
            Path("/evidence/graphql-full-join.json").write_text(
                json.dumps(
                    {
                        "fresh_clients": 6,
                        "first_watermark": watermark,
                        "linked_readback": linked,
                        "command_edge_readback": command_edges,
                        "events": events,
                        "unchanged_domain_facts_sha256": hashlib.sha256(
                            json.dumps(after, sort_keys=True).encode()
                        ).hexdigest(),
                        "excluded_bookkeeping": "ArenaWorkflowControl.revision",
                        "no_worker_preparation": True,
                    },
                    indent=2,
                )
            )

    asyncio.run(scenario())


def test_cancelled_boot_drains_failure_without_asyncio_error_leak(prepared):
    import gc
    from dataclasses import replace

    settings, composition, store, driver, _ = prepared
    started, release = threading.Event(), threading.Event()
    closed = []

    class OwnedDriver:
        def __init__(self):
            self.real = driver_factory()

        def close(self):
            self.real.close()
            closed.append(True)

    def fail_after_barrier(owned):
        started.set()
        assert release.wait(5)
        raise ValueError("PRIVATE_CANCELLED_BOOT_SENTINEL")

    async def scenario():
        observed = []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda loop, context: observed.append(context))
        app = create_app(
            settings=settings,
            composition=replace(composition, create_driver=OwnedDriver, create_store=fail_after_barrier),
        )
        lifecycle = app.router.lifespan_context(app)
        entering = asyncio.create_task(lifecycle.__aenter__())
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert started.is_set()
            entering.cancel()
            await asyncio.sleep(0.02)
            assert not entering.done() and closed == []
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await entering
            gc.collect()
            await asyncio.sleep(0.02)
            assert observed == [], "cancelled startup exposed an unhandled worker exception"
            assert closed == [True] and not app.state.ready
        finally:
            release.set()
            if not entering.done():
                await asyncio.gather(entering, return_exceptions=True)
            loop.set_exception_handler(None)

    asyncio.run(scenario())


def test_whole_response_protection_is_reject_only(prepared):
    from dataclasses import replace

    settings, composition, store, driver, _ = prepared

    def mutating_screen(value):
        if isinstance(value, dict) and "data" in value:
            value.clear()

    async def scenario():
        app = create_app(settings=settings, composition=replace(composition, protect=mutating_screen))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                response = await client.post("/graphql", json={"query": "{workflowProfiles{__typename}}"})
                assert (
                    response.status_code == 403 and response.content == b""
                ), "mutating protection did not fail closed"

    asyncio.run(scenario())


def test_trusted_clock_is_not_called_under_registry_lock(prepared):
    settings, composition, store, driver, _ = prepared
    registry = composition.tokens
    original_clock = registry.clock
    observations = []

    def clock():
        observations.append(registry._lock.locked())
        return original_clock()

    registry.clock = clock

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                response = await client.post("/graphql", json={"query": "{workflowProfiles{__typename}}"})
                assert response.status_code == 200 and "errors" not in response.json()
        assert len(observations) >= 2 and not any(observations), "trusted clock callback ran under registry lock"

    asyncio.run(scenario())


def test_event_codec_version_retained_catchup(prepared):
    from graphql import parse, validate

    from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema
    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        LocalStopObservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )

    settings, composition, store, driver, _ = prepared
    store.read_scope = settings.binding
    raw = canonical_json(retained_contract())
    run = store.admit("codec-catchup", raw, raw, 10)
    receipt = store.cancel_command(
        "codec-cancel",
        run.run_id,
        LocalStopObservation(delivery="no_owner"),
        protect=lambda _: None,
    )
    query = (
        "{workflowEvents(first:100){... on WorkflowEventPage {events {schemaVersion sequence runId operationId kind"
        " sourceId commandKind commandOperationId}}}}"
    )

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            for _ in range(2):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://isolated",
                    trust_env=False,
                    headers=composition.authority.headers,
                ) as client:
                    response = await client.post("/graphql", json={"query": query})
                    assert response.status_code == 200 and "errors" not in response.json(), {
                        "http": response.json(),
                        "validation": [str(e) for e in validate(schema._schema, parse(query))],
                    }
                    record_transport(query, response)
                    events = response.json()["data"]["workflowEvents"]["events"]
                    with driver.session(database=store.database) as session:
                        retained = session.run(
                            "MATCH (e:ArenaWorkflowEvent {deployment_id:$deployment_id, workspace_id:$workspace_id})"
                            " RETURN e.schema_version AS schemaVersion, toString(e.sequence) AS sequence, e.run_id AS"
                            " runId, e.operation_id AS operationId, e.kind AS kind, e.source_id AS sourceId,"
                            " e.command_kind AS commandKind, e.command_operation_id AS commandOperationId ORDER BY"
                            " e.sequence",
                            **store.scope,
                        ).data()
                    assert events == retained
                    assert all(e["schemaVersion"] == 1 for e in events)
                    assert events[-1]["commandOperationId"] == receipt.operation_id

    asyncio.run(scenario())


def test_full_retained_profile_settings_list_and_exact(prepared, monkeypatch):
    import hashlib
    from graphql import parse, validate

    from isaaclab_arena.agentic_environment_generation import inference_profiles
    from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema

    settings, composition, store, driver, _ = prepared
    value = registration().model_dump(mode="json")
    value["profile_id"] = "accounted-model"
    value["settings"].update(model="gpt-6-astra", billing="paid")
    value["settings"]["inference_policy"] = inference_profiles.frozen_builtin_profile(
        next(p for p in inference_profiles.inference_profile_catalogue() if p["model"] == "gpt-6-astra")
    )
    value["settings"]["workflow_accounting"] = dict(
        version=1,
        attested=True,
        model="gpt-6-astra",
        endpoint=value["settings"]["endpoint"],
        max_tokens=2**63 - 1,
        max_cost_usd="123456789.000000001",
    )
    WorkflowProfileAdmin(store, composition.authority).register_profile(
        "bootstrap-operator",
        ProfileRegistration.model_validate(value),
        protect=lambda _: None,
    )
    selection = """id revision kind roles settingsDigest bodyDigest model endpoint billing
      settings { model endpoint billing inferencePolicy { id revision provider model endpoint origin support verification documentationUrls
        requestPolicy { api temperatureMode tokenLimitParameter structuredOutput multimodalOutput store } }
        workflowAccounting { version attested model endpoint maxTokens maxCostUsd } }"""
    query = (
        "query($id:ID!,$revision:Revision!){ workflowProfiles {... on WorkflowProfileList {profiles {"
        + selection
        + "}}} workflowProfile(id:$id,revision:$revision){... on WorkflowProfile {"
        + selection
        + "}}}"
    )

    def camel(value):
        if isinstance(value, dict):
            return {k.split("_")[0] + "".join(s.title() for s in k.split("_")[1:]): camel(v) for k, v in value.items()}
        if isinstance(value, list):
            return [camel(v) for v in value]
        return value

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            for changed in (False, True):
                if changed:
                    monkeypatch.setattr(inference_profiles, "inference_profile_catalogue", lambda: [])
                    monkeypatch.setattr(
                        inference_profiles,
                        "resolve_inference_profile",
                        lambda *a, **kw: pytest.fail("mutable default resolved by retained query"),
                    )
                for profile_id in ("public-model", "accounted-model"):
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app),
                        base_url="http://isolated",
                        trust_env=False,
                        headers=composition.authority.headers,
                    ) as client:
                        response = await client.post(
                            "/graphql",
                            json={
                                "query": query,
                                "variables": {
                                    "id": profile_id,
                                    "revision": str(2**63 - 1),
                                },
                            },
                        )
                        assert response.status_code == 200 and "errors" not in response.json(), {
                            "http": response.json(),
                            "validation": [str(e) for e in validate(schema._schema, parse(query))],
                        }
                        record_transport(query, response)
                        data = response.json()["data"]
                        listed = {p["id"]: p for p in data["workflowProfiles"]["profiles"]}
                        assert data["workflowProfile"] == listed[profile_id]
                        with driver.session(database=store.database) as session:
                            rows = session.run(
                                "MATCH (p:ArenaWorkflowProfileRevision"
                                " {deployment_id:$deployment_id,workspace_id:$workspace_id}) RETURN p.body_json AS"
                                " body, p.body_sha256 AS body_digest, p.settings_sha256 AS settings_digest",
                                **store.scope,
                            ).data()
                        assert len(rows) == 2
                        for row in rows:
                            retained = json.loads(row["body"])["registration"]
                            expected = camel(retained["settings"])
                            expected["inferencePolicy"]["revision"] = str(expected["inferencePolicy"]["revision"])
                            if expected["workflowAccounting"] is not None:
                                expected["workflowAccounting"]["version"] = str(
                                    expected["workflowAccounting"]["version"]
                                )
                                expected["workflowAccounting"]["maxTokens"] = str(
                                    expected["workflowAccounting"]["maxTokens"]
                                )
                            actual = listed[retained["profile_id"]]
                            assert actual["settings"] == expected
                            assert actual["revision"] == str(retained["revision"])
                            assert actual["roles"] == retained["roles"] and actual["kind"] == retained["kind"]
                            assert (
                                actual["bodyDigest"]
                                == row["body_digest"]
                                == hashlib.sha256(row["body"].encode()).hexdigest()
                            )
                            assert actual["settingsDigest"] == row["settings_digest"]
                            assert all(actual[k] == expected[k] for k in ("model", "endpoint", "billing"))
                        assert listed["public-model"]["settings"]["workflowAccounting"] is None
                        assert listed["public-model"]["settings"]["inferencePolicy"]["requestPolicy"]["store"] is None
                        assert (
                            listed["accounted-model"]["settings"]["inferencePolicy"]["requestPolicy"]["store"] is False
                        )

    asyncio.run(scenario())


@pytest.mark.parametrize("max_tokens", [2**63 - 1, 2**63, 10**99], ids=["signed64-max", "signed64-plus-one", "100-digits"])
def test_accounting_positive_integer_retained_http(prepared, monkeypatch, max_tokens):
    import hashlib

    from isaaclab_arena.agentic_environment_generation import inference_profiles
    from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import (
        MAX_PROFILE_BYTES,
        profile_body,
        public_model_settings_sha256,
    )

    settings, composition, store, driver, _ = prepared
    value = registration().model_dump(mode="json")
    value["profile_id"] = "accounting-width"
    value["settings"]["workflow_accounting"] = dict(
        version=1, attested=True, model=value["settings"]["model"],
        endpoint=value["settings"]["endpoint"], max_tokens=max_tokens,
        max_cost_usd="123456789.000000001",
    )
    registered = ProfileRegistration.model_validate(value)
    admitted = WorkflowProfileAdmin(store, composition.authority).register_profile(
        "bootstrap-operator", registered, protect=lambda _: None,
    )

    def retained_row():
        with driver.session(database=store.database) as session:
            return session.run(
                "MATCH (p:ArenaWorkflowProfileRevision {deployment_id:$deployment_id,"
                " workspace_id:$workspace_id, profile_id:$id}) RETURN p.body_json AS body,"
                " p.body_sha256 AS body_digest, p.settings_sha256 AS settings_digest",
                **store.scope, id=registered.profile_id,
            ).single(strict=True).data()

    before = retained_row()
    assert before["body"] == profile_body(registered)
    assert len(before["body"].encode()) <= MAX_PROFILE_BYTES
    assert json.loads(before["body"])["registration"] == value
    assert before["body_digest"] == admitted.body_sha256 == hashlib.sha256(before["body"].encode()).hexdigest()
    assert before["settings_digest"] == admitted.settings_sha256 == public_model_settings_sha256(registered.settings)
    monkeypatch.setattr(inference_profiles, "inference_profile_catalogue", lambda: [])
    monkeypatch.setattr(
        inference_profiles, "resolve_inference_profile",
        lambda *a, **kw: pytest.fail("mutable default resolved by retained query"),
    )
    selection = "id revision bodyDigest settingsDigest settings { inferencePolicy { revision } workflowAccounting { version maxTokens maxCostUsd } }"
    queries = {
        "list": "{workflowProfiles {... on WorkflowProfileList {profiles {" + selection + "}}}}",
        "exact": "query($id:ID!,$revision:Revision!){workflowProfile(id:$id,revision:$revision){... on WorkflowProfile {" + selection + "}}}",
    }
    responses = {}

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            for kind, query in queries.items():
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://isolated",
                    trust_env=False, headers=composition.authority.headers,
                ) as client:
                    response = await client.post("/graphql", json={
                        "query": query,
                        **({"variables": {"id": registered.profile_id, "revision": str(registered.revision)}} if kind == "exact" else {}),
                    })
                    record_transport(query, response)
                    responses[kind] = {"status": response.status_code, "body": response.json()}

    asyncio.run(scenario())
    after = retained_row()
    # Persist both real responses and writer/readback before the RED assertion.
    Path(f"/evidence/accounting-width-{max_tokens}.json").write_text(json.dumps({
        "max_tokens": str(max_tokens), "registration": value,
        "before": before, "after": after, "http": responses,
    }, indent=2))
    assert after == before, "query changed immutable profile body/digests"
    assert all(r["status"] == 200 and "errors" not in r["body"] for r in responses.values()), responses
    listed = responses["list"]["body"]["data"]["workflowProfiles"]["profiles"]
    exact = responses["exact"]["body"]["data"]["workflowProfile"]
    assert exact == next(p for p in listed if p["id"] == registered.profile_id)
    assert exact == {
        "id": registered.profile_id, "revision": str(registered.revision),
        "bodyDigest": before["body_digest"], "settingsDigest": before["settings_digest"],
        "settings": {"inferencePolicy": {"revision": "1"}, "workflowAccounting": {
            "version": "1", "maxTokens": str(max_tokens), "maxCostUsd": "123456789.000000001",
        }},
    }

    # Exercise the executable scalar codecs, independently of Python's int digit limit.
    scalar = schema._schema.get_type("PublicWorkflowAccounting").fields["maxTokens"].type.of_type
    assert scalar.name == "PositiveDecimalInteger"
    for codec in (scalar.serialize, scalar.parse_value):
        for valid in ("1", str(2**63 - 1), str(2**63), "9" * MAX_PROFILE_BYTES):
            assert codec(valid) == valid
        for invalid in (None, True, 1, 1.0, "", "0", "01", "+1", "-1", " 1", "1 ", "1.0", "1e2", "١", "１", "9" * (MAX_PROFILE_BYTES + 1)):
            with pytest.raises(ValueError, match="^Invalid positive decimal integer$"):
                codec(invalid)
    for name in ("Counter", "Revision"):
        counter = schema._schema.get_type(name)
        for codec in (counter.serialize, counter.parse_value):
            assert codec(str(2**63 - 1)) == str(2**63 - 1)
            with pytest.raises(ValueError, match="^Invalid revision$"):
                codec(str(2**63))


def metadata_reservation(store, contract, operation):
    """Real retained writer metadata; never a private grant or physical worker."""
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        AuthorizationSnapshot,
        GenerationReservation,
        ReadinessReceipt,
        ReadyProfile,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
        contract_digest,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import (
        required_dependencies,
    )

    store.clock = lambda: 100.0
    raw = canonical_json(contract)
    run = store.admit(operation, raw, raw, 10)
    auth = AuthorizationSnapshot(
        database=store.database,
        **store.scope,
        principal="scoped-reader",
        grant_ref="metadata-only-no-private-grant",
        contract_digest=contract_digest(contract),
        expires_at=200.0,
        capabilities=("generation_model", "operational_writes"),
    )
    store.dependency_instances = {
        (r.dependency_id, r.profile_id, r.profile_sha256): "metadata-instance-" + r.dependency_id
        for r in required_dependencies(contract)
    }
    ready = ReadinessReceipt(
        contract_digest=contract_digest(contract),
        checked_at=100.0,
        profiles=tuple(
            ReadyProfile(
                role=r.dependency_id,
                profile_id=r.profile_id,
                settings_sha256=r.profile_sha256,
                expected_instance_id=r.instance_id,
                observed_instance_id=r.instance_id,
            )
            for r in required_dependencies(contract, resolved_instances=store.dependency_instances)
        ),
    )
    intent = store.reserve_generation(
        run.run_id,
        1,
        operation + "-generation",
        auth,
        GenerationReservation(
            model_calls=1,
            model_tokens=100,
            cost_ceiling_usd=min(0.1, contract.budget.max_cost_usd),
            runtime_allowance_seconds=1.0,
        ),
        readiness=ready,
    )
    return run, intent, auth, ready


def metadata_registration(store, intent):
    """Synthetic process coordinates persisted by real registration writer, not OS proof."""
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        WorkerRegistration,
    )

    fence = store.claim_intent(intent, "metadata-owner-A", store.begin_owner("metadata-owner-A"))
    reg = store.register_worker(
        fence,
        WorkerRegistration(
            registration_id="metadata-registration",
            fence=fence,
            host="synthetic-host",
            boot="synthetic-boot",
            pid=100,
            pgid=100,
            sid=100,
            start_ticks=1000,
        ),
    )
    return fence, reg


def metadata_generation(prepared, contract, source):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )

    settings, composition, store, driver, _ = prepared
    run, intent, auth, ready = metadata_reservation(store, contract, "metadata-produced")
    fence, reg = metadata_registration(store, intent)
    assert store.release_attempt(fence, reg.registration_id, auth, readiness=ready)
    with ArtifactArea.open(
        settings.artifact_root,
        store_id=settings.binding.store_id,
        registry_id=settings.binding.registry_id,
    ) as area:
        artifacts = GenerationArtifacts(area)
        receipt = artifacts.write(
            fence,
            reg,
            contract,
            json.dumps(source).encode(),
            source,
            protect=lambda _: None,
        )
        store.commit_generation_receipt(fence, artifacts.verify(receipt, protect=lambda _: None))
    cleanup = CleanupEvidence(
        registration=reg,
        evidence_ref="metadata-cleanup",
        observation="owned_process_group_stopped",
        remote_effects="unknown",
    )
    store.acknowledge_cleanup(fence, cleanup)
    return run, auth, ready, fence, receipt


def retained_facts(store, driver):
    with driver.session(database=store.database) as session:
        rows = session.run(
            "MATCH (n {deployment_id:$deployment_id,workspace_id:$workspace_id}) RETURN labels(n) AS labels,"
            " properties(n) AS value",
            **store.scope,
        ).data()
        edges = session.run(
            "MATCH (n {deployment_id:$deployment_id,workspace_id:$workspace_id})-[r]->(m) RETURN elementId(n) AS"
            " source,type(r) AS kind,properties(r) AS value,elementId(m) AS target",
            **store.scope,
        ).data()
    for row in rows:
        if "ArenaWorkflowControl" in row["labels"]:
            row["value"].pop("revision", None)
    return [sorted(items, key=lambda r: json.dumps(r, sort_keys=True)) for items in (rows, edges)]


async def fresh_query(app, composition, query, variables=None):
    from graphql import parse, validate
    from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://isolated",
        trust_env=False,
        headers=composition.authority.headers,
    ) as client:
        response = await client.post("/graphql", json={"query": query, "variables": variables or {}})
        assert response.status_code == 200 and "errors" not in response.json(), {
            "http": response.json(),
            "validation": [str(e) for e in validate(schema._schema, parse(query))],
        }
        record_transport(query, response)
        return response.json()["data"]


def record_transport(query, response):
    """Persist actual safe response bytes, never bearer headers or private context."""
    with Path("/evidence/correction-http.jsonl").open("a") as output:
        output.write(
            json.dumps({
                "test": os.environ.get("PYTEST_CURRENT_TEST"),
                "query": query,
                "status": response.status_code,
                "response": response.text,
            })
            + "\n"
        )


@pytest.mark.parametrize("diagnostic", [False, True])
def test_retained_generation_output_references_are_atomic_metadata(prepared, diagnostic):
    settings, composition, store, driver, _ = prepared
    run, auth, ready, fence, receipt = metadata_generation(prepared, retained_contract(), {"scene": "synthetic"})
    if diagnostic:
        store.request_cancel(run.run_id, store.get_run(run.run_id).version)
    direct = store.get_run_inspection(run.run_id)
    assert direct.scene is None and len(direct.generation_outputs) == 1
    before = retained_facts(store, driver)
    query = (
        "query($id:ID!){workflow(id:$id){... on Workflow {retainedRevision generationOutputs {intentId attemptId"
        " registrationId contractDigest candidateYamlSha256 candidateJsonSha256 provenanceSha256 manifestSha256"
        " disposition freshArtifactVerification}}}}"
    )

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            for _ in range(2):
                data = await fresh_query(app, composition, query, {"id": run.run_id})
                actual = data["workflow"]
                assert actual["retainedRevision"] == direct.retained_revision
                assert actual["generationOutputs"] == [{
                    "intentId": fence.intent_id,
                    "attemptId": fence.attempt_id,
                    "registrationId": receipt.registration.registration_id,
                    "contractDigest": receipt.contract_digest,
                    "candidateYamlSha256": receipt.candidate_yaml_sha256,
                    "candidateJsonSha256": receipt.candidate_json_sha256,
                    "provenanceSha256": receipt.provenance_sha256,
                    "manifestSha256": receipt.manifest_sha256,
                    "disposition": "diagnostic" if diagnostic else "produced",
                    "freshArtifactVerification": "not_performed",
                }]
                with driver.session(database=store.database) as session:
                    row = session.run(
                        "MATCH (a:ArenaExecutionAttempt"
                        " {deployment_id:$deployment_id,workspace_id:$workspace_id,attempt_id:$id}) RETURN"
                        " a.receipt_json AS receipt, a.receipt_disposition AS disposition",
                        **store.scope,
                        id=fence.attempt_id,
                    ).single(strict=True)
                assert json.loads(row["receipt"]) == receipt.model_dump(mode="json")
                assert row["disposition"] == ("diagnostic" if diagnostic else "produced")
                assert actual["generationOutputs"] == camel_fields(
                    [v.model_dump(mode="json") for v in direct.generation_outputs]
                )

    asyncio.run(scenario())
    assert retained_facts(store, driver) == before


def metadata_scene(prepared, *, owned_worker=False, rich=False):
    """Derive the ordinary metadata tracer; schema callback is explicitly synthetic."""
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        ScenePortProfile,
        SceneReservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )
    from isaaclab_arena.tests.test_environment_workflow_repairs import scene
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import scene_contract

    settings, composition, store, driver, _ = prepared
    contract = scene_contract()
    if rich:
        raw = contract.model_dump(mode="json")
        raw["preserved"] = [{
            "subject_id": "banana",
            "schema_path": "/objects/0",
            "mode": "frozen",
            "description": "Retain original object",
        }]
        raw["allowed_interventions"][0]["description"] = "Bounded effective XY only"
        raw["criteria"].append(
            dict(
                raw["criteria"][-1],
                criterion_id="advisory-visual",
                requirement="advisory",
            )
        )
        contract = type(contract).model_validate(raw)
    run, auth, ready, fence, receipt = metadata_generation(prepared, contract, scene())
    profile = ScenePortProfile(
        port_id="synthetic-metadata",
        assurance="synthetic",
        owned_worker=owned_worker,
        producer_ids=tuple(c.evidence_producer for c in contract.criteria),
        observe=SceneReservation(
            model_calls=1,
            model_tokens=100,
            cost_ceiling_usd=0.0,
            runtime_allowance_seconds=1.0,
            realizations=1,
            observations=1,
            steps=10,
        ),
        repair=SceneReservation(
            model_calls=1,
            model_tokens=100,
            cost_ceiling_usd=0.0,
            runtime_allowance_seconds=1.0,
            candidates=1,
            revisions=1,
        ),
    )
    validation = dict(
        disposition="schema_validated",
        fence=fence.model_dump(mode="json"),
        contract_digest=receipt.contract_digest,
        candidate_yaml_sha256=receipt.candidate_yaml_sha256,
        candidate_json_sha256=receipt.candidate_json_sha256,
        provenance_sha256=receipt.provenance_sha256,
        manifest_sha256=receipt.manifest_sha256,
        normalized_spec_sha256="a" * 64,
        validator_identity="explicitly-synthetic-schema-port",
    )
    service = WorkflowService(store, composition.authority, None, validate_support=None)
    with ArtifactArea.open(
        settings.artifact_root,
        store_id=settings.binding.store_id,
        registry_id=settings.binding.registry_id,
    ) as area:
        service.start_scene(
            "scoped-reader",
            run.run_id,
            artifacts=GenerationArtifacts(area),
            protect=lambda _: None,
            validate_generation_candidate=lambda *a, **kw: validation,
            profile=profile,
        )
    return run, contract, auth, ready, fence


def metadata_scene_result(store, run, auth, ready, result):
    selected = store.scene_snapshot(run.run_id)
    assert store.release_scene(run.run_id, selected.intent.intent_id, auth, readiness=ready)
    assert store.finish_scene(run.run_id, selected.intent.intent_id, store.get_run(run.run_id).version, result)
    return store.get_run_inspection(run.run_id)


def camel_fields(value):
    if isinstance(value, dict):
        return {
            k.split("_")[0] + "".join(s.title() for s in k.split("_")[1:]): camel_fields(v) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [camel_fields(v) for v in value]
    return value


@pytest.mark.parametrize("stale", [False, True])
def test_selected_scene_candidate_criteria_and_limitations(prepared, stale, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        SceneResult,
    )
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import observation

    settings, composition, store, driver, _ = prepared
    run, contract, auth, ready, fence = metadata_scene(prepared)
    parent = store.scene_snapshot(run.run_id).candidate
    first = metadata_scene_result(
        store,
        run,
        auth,
        ready,
        SceneResult(observation=observation(contract, parent, "A", fail=True)),
    )
    assert first.scene.action == "repair" and first.scene.selected_assessed
    query = """query($id:ID!){workflow(id:$id){... on Workflow {retainedRevision scene {
        selectedCandidateReference {candidateId digest sourceId originalId parentId}
        acceptance assessmentStatus decisionId decisionIdentityProvenance action reason nextIntentId evidenceId assessmentId selectedAssessed
        criteria {criterionId requirement verdict reportedVerdicts manifests} limitations
        policyTrial {intentId manifestDigest episodeRecordsDigest} }}}}"""

    async def inspect(app, expected):
        before = retained_facts(store, driver)
        calls = []
        original = Neo4jWorkflowStore.get_run_inspection

        def joined(self, *args, **kwargs):
            value = original(self, *args, **kwargs)
            calls.append(value)
            return value

        def separate(*args, **kwargs):
            pytest.fail("field mapping made an additional historical point-read")

        with monkeypatch.context() as m:
            m.setattr(Neo4jWorkflowStore, "get_run_inspection", joined)
            for name in (
                "get_scene_candidate",
                "get_scene_decision",
                "get_scene_assessment",
                "get_scene_evidence",
            ):
                m.setattr(Neo4jWorkflowStore, name, separate)
            actual = (await fresh_query(app, composition, query, {"id": run.run_id}))["workflow"]
        assert calls == [expected], "projection did not use one atomic RunInspection"
        assert actual["retainedRevision"] == expected.retained_revision
        scene = actual["scene"]
        assert scene.pop("selectedCandidateReference") == camel_fields(expected.scene.candidate.model_dump(mode="json"))
        wanted = expected.scene.model_dump(mode="json", exclude={"candidate", "observation", "assessment"})
        assert scene == camel_fields(wanted)
        with driver.session(database=store.database) as session:
            candidate = session.run(
                "MATCH (c:ArenaWorkflowCandidate"
                " {deployment_id:$deployment_id,workspace_id:$workspace_id,record_id:$id}) RETURN c.payload AS payload",
                **store.scope,
                id=expected.scene.candidate.candidate_id,
            ).single(strict=True)
            retained = json.loads(candidate["payload"])
            assert {
                k: retained[k] for k in type(expected.scene.candidate).model_fields
            } == expected.scene.candidate.model_dump(mode="json")
            if expected.scene.evidence_id is not None:
                edge = session.run(
                    "MATCH (e:ArenaWorkflowEvidence"
                    " {deployment_id:$deployment_id,workspace_id:$workspace_id,record_id:$id}) OPTIONAL MATCH"
                    " (a:ArenaCriterionAssessment)-[:ASSESSES]->(e) OPTIONAL MATCH (e)-[:FOR_CANDIDATE]->(c) RETURN"
                    " a.record_id AS assessment,c.record_id AS candidate,e.payload AS observation",
                    **store.scope,
                    id=expected.scene.evidence_id,
                ).single(strict=True)
                assert edge["assessment"] == expected.scene.assessment_id
                assert edge["candidate"] == (
                    expected.scene.candidate.candidate_id if expected.scene.selected_assessed else None
                )
                assert json.loads(edge["observation"]) == expected.scene.observation.model_dump(mode="json")
        assert retained_facts(store, driver) == before
        return actual

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            await inspect(app, first)
            proposed = json.loads(parent.scene_json)
            proposed["relations"][2]["params"]["x"] = 0.03
            child_view = metadata_scene_result(
                store,
                run,
                auth,
                ready,
                SceneResult(candidate_json=json.dumps(proposed)),
            )
            assert child_view.scene.candidate.parent_id == parent.candidate_id
            assert child_view.scene.evidence_id is None and not child_view.scene.selected_assessed
            await inspect(app, child_view)
            child = store.scene_snapshot(run.run_id).candidate
            final = metadata_scene_result(
                store,
                run,
                auth,
                ready,
                SceneResult(observation=observation(contract, child, "A" if stale else "B")),
            )
            if stale:
                assert final.scene.reason == "stale_cohort" and final.scene.assessment_id is None
                assert all(c.verdict == "not_assessed" for c in final.scene.criteria)
                assert all(c.reported_verdicts == ("established",) for c in final.scene.criteria)
            else:
                assert final.scene.acceptance == "accepted" and final.scene.selected_assessed
                assert all(c.verdict == "established" for c in final.scene.criteria)
            await inspect(app, final)
            await inspect(app, final)
            assert first.scene.decision_id != final.scene.decision_id
            assert first.scene.candidate.candidate_id != final.scene.candidate.candidate_id

    asyncio.run(scenario())


@pytest.mark.parametrize("branch", ["generation", "scene", "reconciliation"])
def test_populated_resume_receipt_selection_is_stable_read_only(prepared, branch):
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    settings, composition, store, driver, _ = prepared
    if branch == "scene":
        run, contract, auth, ready, _ = metadata_scene(prepared, owned_worker=True)
    else:
        run, intent, auth, ready = metadata_reservation(store, retained_contract(), "resume-positive")
        if branch == "reconciliation":
            metadata_registration(store, intent)
    service = WorkflowService(store, composition.authority, None, validate_support=None)
    version = store.get_run(run.run_id).version
    payload = dict(runId=run.run_id, expectedVersion=version, renewAuthorization=False)
    checks = []
    admission = service.admit_resume(
        "scoped-reader",
        "resume-positive",
        payload,
        check_resume=lambda *a: checks.append("permission"),
        check_eligibility=lambda *a, **kw: checks.append("eligibility") or "current",
        protect=lambda _: None,
    )
    receipt = admission.receipt
    assert admission.fresh and receipt.selection.branch == branch
    assert receipt.disposition == ("reconciliation_admitted" if branch == "reconciliation" else "continuation_admitted")
    assert checks == (["permission"] if branch == "reconciliation" else ["permission", "eligibility"])
    assert (receipt.selection.fence is not None) == (branch == "reconciliation")
    expected = receipt.model_dump(mode="json", exclude={"scope", "payload_json"})
    expected.update(expected_version=version, renew_authorization=False)
    assert expected["selection"].pop("run_id") == run.run_id  # receipt already exposes exact target
    expected = camel_fields(number_text(expected))
    expected["__typename"] = "ResumeReceipt"

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            for later in (False, True):
                if later:
                    store.request_cancel(run.run_id, store.get_run(run.run_id).version)
                    replay = service.admit_resume(
                        "scoped-reader",
                        "resume-positive",
                        payload,
                        check_resume=lambda *a: pytest.fail("replay checked execution permission"),
                        check_eligibility=lambda *a, **kw: pytest.fail("replay checked renewal"),
                        protect=lambda _: None,
                    )
                    assert not replay.fresh and replay.receipt == receipt
                before = retained_facts(store, driver)
                inspection = await fresh_query(
                    app,
                    composition,
                    (DOCUMENTS / "inspection.graphql").read_text(),
                    {"id": run.run_id, "operation": run.operation_id},
                )
                direct = store.get_run_inspection(run.run_id)
                assert_full_inspection(inspection["workflow"], direct)
                if not later:
                    assert inspection["workflow"]["actions"]["resumeBranch"] == branch
                assert all(
                    p["expectedInstanceId"] is not None and p["expectedInstanceId"] == p["observedInstanceId"]
                    for r in inspection["workflow"]["readiness"]
                    for p in r["profiles"]
                )
                actual = await fresh_query(
                    app,
                    composition,
                    (DOCUMENTS / "receipts.graphql").read_text(),
                    {"id": run.run_id, "operation": "resume-positive"},
                )
                assert actual["resume"] == expected
                assert retained_facts(store, driver) == before
                with driver.session(database=store.database) as session:
                    row = session.run(
                        "MATCH (r:ArenaResumeReceipt"
                        " {deployment_id:$deployment_id,workspace_id:$workspace_id,kind:'RESUME',operation_id:$key})"
                        " RETURN r.receipt_json AS receipt",
                        **store.scope,
                        key="resume-positive",
                    ).single(strict=True)
                    events = session.run(
                        "MATCH (r:ArenaResumeReceipt"
                        " {deployment_id:$deployment_id,workspace_id:$workspace_id,kind:'RESUME',operation_id:$key})-[:CAUSED]->(e:ArenaWorkflowEvent)"
                        " RETURN e.sequence AS sequence,e.kind AS kind,e.source_id AS source_id ORDER BY sequence",
                        **store.scope,
                        key="resume-positive",
                    ).data()
                assert json.loads(row["receipt"]) == receipt.model_dump(mode="json")
                assert events == [e.model_dump(mode="json") for e in receipt.events]

    asyncio.run(scenario())


def number_text(value):
    from decimal import Decimal

    if isinstance(value, dict):
        return {k: number_text(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [number_text(v) for v in value]
    return str(value) if type(value) in (int, float, Decimal) else value


def assert_full_inspection(view, direct):
    contract = direct.intent.contract
    assert view["__typename"] == "Workflow"
    assert view["id"] == direct.intent.run_id and view["operationId"] == direct.intent.submission.operation_id
    assert view["version"] == str(direct.intent.run_version) and view["eventCounter"] == str(direct.intent.event_cursor)
    assert view["state"] == direct.intent.state and view["phase"] == direct.intent.phase
    assert view["policyOutcome"] == direct.policy_outcome
    assert view["publicationOutcome"] == direct.publication_outcome
    assert view["experimentOutcome"] == direct.experiment_outcome
    assert len(view["responseRevision"]) == 64 and view["responseRevision"] != view["retainedRevision"]
    frozen = view["frozenIntent"]
    assert frozen["schemaVersion"] == contract.schema_version
    assert frozen["source"] == (
        {"__typename": "NewSource", "prompt": contract.source.prompt}
        if contract.source.kind == "new"
        else {
            "__typename": "ExistingSource",
            "identity": contract.source.identity,
            "content": contract.source.content,
        }
    )
    execution = camel_fields(number_text(contract.execution.model_dump(mode="python")))
    for key in (
        "generationModel",
        "assessmentModel",
        "runtime",
        "database",
        "policy",
        "capture",
    ):
        if execution[key] is not None:
            execution[key]["settingsDigest"] = execution[key].pop("settingsSha256")
            execution[key].setdefault("billing", None)
    assert frozen["execution"] == execution
    for key, attr in (
        ("preserved", "preserved"),
        ("allowedInterventions", "allowed_interventions"),
    ):
        assert frozen[key] == camel_fields(number_text([v.model_dump(mode="python") for v in getattr(contract, attr)]))
    assert frozen["budget"] == camel_fields(number_text(contract.budget.model_dump(mode="python")))
    assert frozen["effects"] == camel_fields(contract.effects.model_dump(mode="json"))
    assert frozen["criteria"] == [
        {
            "id": c.criterion_id,
            "kind": c.kind,
            "requirement": c.requirement,
            "producer": c.evidence_producer,
            "evaluatorVersion": c.evaluator_version,
            "modalities": list(c.required_modalities),
            "frames": list(c.coordinate_frames),
            "subjects": list(c.subjects),
            "rubric": c.rubric,
            "startStep": str(c.observation_window.start_step),
            "endStep": str(c.observation_window.end_step),
            "limit": camel_fields(number_text(c.limit.model_dump(mode="python"))),
        }
        for c in contract.criteria
    ]
    assert view["budget"] == camel_fields(number_text(direct.budget.model_dump(mode="python")))
    cleanup = camel_fields(
        number_text(direct.cleanup.model_dump(mode="python", exclude={"scope", "run_id", "run_version"}))
    )
    for owner in [cleanup["currentScopeOwner"]] + [i["retiredOwner"] for i in cleanup["intents"]]:
        if owner is not None:
            owner["id"] = owner.pop("ownerId")
            owner["epoch"] = owner.pop("ownerEpoch")
    assert view["cleanup"] == cleanup
    assert view["generationOutputs"] == camel_fields([v.model_dump(mode="json") for v in direct.generation_outputs])
    readiness = []
    for r in direct.readiness:
        value = dict(
            intent_id=r.intent_id,
            attempt_id=r.attempt_id,
            source=r.source,
            current_readiness=r.current_readiness,
            ttl_seconds=r.ttl_seconds,
            **r.receipt.model_dump(mode="python"),
        )
        for profile in value["profiles"]:
            profile["settings_digest"] = profile.pop("settings_sha256")
        readiness.append(camel_fields(number_text(value)))
    assert view["readiness"] == readiness
    assert view["retainedRevision"] == direct.retained_revision
    assert view["retainedDependenciesRevision"] == direct.retained_dependencies_revision
    assert view["availableActions"] == []
    assert view["actions"]["cancelApplicable"] == direct.actions.cancel_applicable
    assert view["actions"]["resumeBranch"] == direct.actions.resume_branch
    assert view["actions"]["resumeIntentId"] == direct.actions.resume_intent_id
    assert view["actions"]["commandRequirements"] == list(direct.actions.command_requirements)
    assert view["actions"]["permission"]["cancel"] == view["actions"]["permission"]["resume"] == "denied"
    assert view["actions"]["permission"]["provenance"] == "trusted_check_after_retained_snapshot"
    assert float(view["actions"]["permission"]["observedAt"]) > 0


def test_populated_frozen_intent_readiness_advisory_and_historical_cleanup(prepared):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        SceneResult,
    )
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import observation

    settings, composition, store, driver, _ = prepared
    run, contract, auth, ready, fence = metadata_scene(prepared, rich=True)
    candidate = store.scene_snapshot(run.run_id).candidate
    observed = observation(contract, candidate, "complete")
    advisory = observed.evidence[-1].model_copy(update={"criterion_id": "advisory-visual"})
    observed = observed.model_copy(update={"evidence": (*observed.evidence, advisory)})
    final = metadata_scene_result(store, run, auth, ready, SceneResult(observation=observed))
    assert final.scene.acceptance == "accepted"
    assert final.scene.criteria[-1].verdict == "reported_only"
    assert contract.preserved and contract.allowed_interventions
    # Metadata writer reports synthetic cleanup; this does not establish OS process absence.
    assert store.retire_owner(fence.owner_id, fence.owner_epoch)
    epoch = store.begin_owner("metadata-owner-B")
    store.clock = lambda: 10000.0  # read cannot refresh the original retained readiness.
    direct = store.get_run_inspection(run.run_id)
    before = retained_facts(store, driver)

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            for _ in range(2):
                data = await fresh_query(
                    app,
                    composition,
                    (DOCUMENTS / "inspection.graphql").read_text(),
                    {"id": run.run_id, "operation": run.operation_id},
                )
                view = data["workflow"]
                assert_full_inspection(view, direct)
                assert data["workflowSubmission"] == dict(
                    camel_fields(number_text(direct.intent.submission.model_dump(mode="python", exclude={"scope"}))),
                    __typename="SubmissionReceipt",
                )
                assert view["scene"]["criteria"] == camel_fields(
                    [v.model_dump(mode="json") for v in direct.scene.criteria]
                )
                assert view["scene"]["criteria"][-1]["verdict"] == "reported_only"
                assert view["cleanup"]["currentScopeOwner"] == {
                    "id": "metadata-owner-B",
                    "epoch": str(epoch),
                    "dirty": True,
                }
                historical = next(i for i in view["cleanup"]["intents"] if i["kind"] == "generation")
                assert (
                    historical["cleanupState"] == "recorded" and historical["cleanupEvidenceRef"] == "metadata-cleanup"
                )
                assert historical["retiredOwner"] == {
                    "id": fence.owner_id,
                    "epoch": str(fence.owner_epoch),
                    "dirty": False,
                }
                assert all(
                    r["checkedAt"] == "100.0" and r["currentReadiness"] == "unknown" and r["ttlSeconds"] is None
                    for r in view["readiness"]
                )

    asyncio.run(scenario())
    assert retained_facts(store, driver) == before
    with driver.session(database=store.database) as session:
        row = session.run(
            "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id,workspace_id:$workspace_id,run_id:$id}) RETURN"
            " r.contract_json AS contract",
            **store.scope,
            id=run.run_id,
        ).single(strict=True)
        assert json.loads(row["contract"]) == contract.model_dump(mode="json")
        rows = session.run(
            "MATCH (a:ArenaExecutionAttempt {deployment_id:$deployment_id,workspace_id:$workspace_id,attempt_id:$id})"
            " RETURN a.cleanup_json AS cleanup,a.readiness_json AS readiness",
            **store.scope,
            id=fence.attempt_id,
        ).single(strict=True)
        assert json.loads(rows["cleanup"])["evidence_ref"] == "metadata-cleanup"
        assert json.loads(rows["readiness"]) == ready.model_dump(mode="json")


def test_wrong_instance_bearer_replay_precedes_body_and_io(prepared):
    from dataclasses import replace
    from isaaclab_arena.agentic_environment_generation.workflow.api.security import (
        TokenRegistry,
    )

    settings, composition, store, driver, screens = prepared
    replacement = TokenRegistry(
        binding=settings.binding,
        instance="replacement-instance",
        generation=1,
        clock=composition.tokens.clock,
    )
    reads, output = [], []
    before = retained_facts(store, driver)

    async def scenario():
        app = create_app(settings=settings, composition=replace(composition, tokens=replacement))
        async with app.router.lifespan_context(app):
            screened = len(screens)

            async def receive():
                reads.append(True)
                return {"type": "http.request", "body": b"{}", "more_body": False}

            async def send(message):
                output.append(message)

            scope = dict(
                type="http",
                asgi={"version": "3.0"},
                http_version="1.1",
                method="POST",
                scheme="http",
                path="/graphql",
                raw_path=b"/graphql",
                query_string=b"",
                headers=[
                    (b"content-type", b"application/json"),
                    (
                        b"authorization",
                        composition.authority.headers["Authorization"].encode(),
                    ),
                ],
                server=("isolated", 80),
                client=("127.0.0.1", 1),
            )
            await app(scope, receive, send)
            assert output[0]["status"] == 401 and reads == [] and len(screens) == screened

    asyncio.run(scenario())
    assert retained_facts(store, driver) == before


@pytest.mark.parametrize("case", ["identity_mismatch", "busy_marker_flock"])
def test_artifact_boot_refusal_preserves_bytes_and_closes_driver(prepared, monkeypatch, case):
    from dataclasses import replace
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )

    settings, composition, store, driver, _ = prepared
    selected = settings
    if case == "identity_mismatch":
        root = settings.artifact_root.parent / "foreign-area"
        with ArtifactArea.create(root, store_id="foreign-store", registry_id="foreign-registry"):
            pass
        selected = replace(settings, artifact_root=root)
    before_bytes = {
        str(p.relative_to(selected.artifact_root)): p.read_bytes()
        for p in selected.artifact_root.rglob("*")
        if p.is_file()
    }
    before = retained_facts(store, driver)
    closes = []

    class OwnedDriver:
        def __init__(self):
            self.real = driver_factory()

        def session(self, **kwargs):
            return self.real.session(**kwargs)

        def close(self):
            self.real.close()
            closes.append(threading.get_ident())

    def forbidden(*args, **kwargs):
        pytest.fail("open-only boot attempted initialization or repair")

    monkeypatch.setattr(ArtifactArea, "create", forbidden)
    monkeypatch.setattr(Neo4jWorkflowStore, "initialize_bound_scope", forbidden)
    monkeypatch.setattr(Neo4jWorkflowStore, "initialize_scope", forbidden)

    async def scenario():
        app = create_app(
            settings=selected,
            composition=replace(composition, create_driver=OwnedDriver),
        )
        with pytest.raises(ValueError, match="^Workflow API not ready$"):
            async with app.router.lifespan_context(app):
                pytest.fail("invalid artifact area became ready")
        assert not app.state.ready

    if case == "busy_marker_flock":
        with ArtifactArea.open(
            settings.artifact_root,
            store_id=settings.binding.store_id,
            registry_id=settings.binding.registry_id,
        ) as area:
            with area.writer_lock():  # actual marker flock remains held throughout worker-thread open
                asyncio.run(scenario())
    else:
        asyncio.run(scenario())
    assert len(closes) == 1 and closes[0] != threading.get_ident()
    assert before_bytes == {
        str(p.relative_to(selected.artifact_root)): p.read_bytes()
        for p in selected.artifact_root.rglob("*")
        if p.is_file()
    }
    assert retained_facts(store, driver) == before


def test_expanded_projection_overbudget_documents_do_zero_resolver_io(prepared, monkeypatch):
    settings, composition, store, driver, _ = prepared
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        pytest.fail("overbudget projection reached store")

    monkeypatch.setattr(Neo4jWorkflowStore, "get_run_inspection", forbidden)
    monkeypatch.setattr(Neo4jWorkflowStore, "list_profiles", forbidden)
    generation = (
        "generationOutputs {intentId attemptId registrationId contractDigest candidateYamlSha256 candidateJsonSha256"
        " provenanceSha256 manifestSha256 disposition freshArtifactVerification}"
    )
    scene = (
        "scene { selectedCandidateReference { candidateId digest sourceId originalId parentId } criteria { criterionId"
        " requirement verdict reportedVerdicts manifests } limitations }"
    )
    queries = [
        "{"
        + " ".join('r%d:workflow(id:"absent"){... on Workflow {%s %s}}' % (i, generation, scene) for i in range(9))
        + "}",
        '{workflow(id:"absent"){... on Workflow {' + " ".join("a%d:%s" % (i, generation) for i in range(17)) + "}}}",
        '{workflow(id:"absent"){... on Workflow {' + " ".join([generation, scene] * 12) + "}}}",
        "{"
        + " ".join(
            "p%d:workflowProfiles {... on WorkflowProfileList {profiles {settings {inferencePolicy {id revision"
            " provider model endpoint origin support verification documentationUrls requestPolicy {api temperatureMode"
            " tokenLimitParameter structuredOutput multimodalOutput store}} workflowAccounting {version attested model"
            " endpoint maxTokens maxCostUsd}}}}}" % i
            for i in range(9)
        )
        + "}",
    ]

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://isolated",
                trust_env=False,
                headers=composition.authority.headers,
            ) as client:
                for query in queries:
                    response = await client.post("/graphql", json={"query": query})
                    assert response.status_code == 400
        assert calls == []

    asyncio.run(scenario())


def test_retained_required_policy_reference_is_not_execution(prepared):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )

    settings, composition, store, driver, _ = prepared
    contract = retained_contract(policy=True, existing=True)
    raw = canonical_json(contract)
    run = store.admit("unsupported-policy", raw, raw, 10)
    direct = store.get_run_inspection(run.run_id)
    before = retained_facts(store, driver)

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            data = await fresh_query(
                app,
                composition,
                (DOCUMENTS / "inspection.graphql").read_text(),
                {"id": run.run_id, "operation": run.operation_id},
            )
            view = data["workflow"]
            assert_full_inspection(view, direct)
            assert view["frozenIntent"]["execution"]["policy"] is not None
            assert view["policyOutcome"] == "unsupported_or_unretained" and view["scene"] is None

    asyncio.run(scenario())
    assert retained_facts(store, driver) == before


def test_nullable_legacy_settings_mapper_without_catalogue_invention():
    from isaaclab_arena.agentic_environment_generation.workflow.api.schema import (
        model_settings_view,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.profiles import (
        PublicModelSettings,
    )

    value = PublicModelSettings(
        model="legacy-model",
        endpoint="https://api.openai.com/v1",
        billing="free",
        inference_policy=None,
    )
    mapped = model_settings_view(value)
    assert mapped.inference_policy is None and mapped.workflow_accounting is None
    # Registration intentionally still requires explicit policy; no fake legacy DB row is created.
    assert (mapped.model, mapped.endpoint, mapped.billing) == (
        value.model,
        value.endpoint,
        value.billing,
    )


class Authority:
    def require_admin(self, principal):
        assert principal == "bootstrap-operator"

    def require_read(self, principal):
        assert principal == "scoped-reader"


def driver_factory():
    return GraphDatabase.driver(
        os.environ["ARENA_WORKFLOW_NEO4J_URI"],
        auth=None,
        connection_timeout=3,
        connection_acquisition_timeout=5,
        max_transaction_retry_time=0,
    )


def registration():
    return ProfileRegistration.model_validate({
        "profile_id": "public-model",
        "revision": 2**63 - 1,
        "kind": "model",
        "roles": ["generation_model", "assessment_model"],
        "settings": {
            "model": "gpt-4.1",
            "endpoint": "https://api.openai.com/v1/",
            "billing": "free",
            "inference_policy": {
                "id": "openai-gpt-4.1",
                "revision": 1,
                "provider": "openai",
                "model": "gpt-4.1",
                "endpoint": "https://api.openai.com/v1",
                "origin": "builtin",
                "support": "documented",
                "verification": "not_checked",
                "documentation_urls": ["https://developers.openai.com/api/docs/models/gpt-4.1"],
                "request_policy": {
                    "api": "chat_completions",
                    "temperature_mode": "configured",
                    "token_limit_parameter": "max_tokens",
                    "structured_output": "json_schema",
                    "multimodal_output": "json_object",
                    "store": None,
                },
            },
        },
    })


@pytest.fixture
def prepared(tmp_path):
    binding = ScopeBinding(
        authority_id="synthetic-authority",
        database=os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"],
        deployment_id="graphql-tests",
        workspace_id=uuid.uuid4().hex,
        schema_version=1,
        operational_schema_version=1,
        artifact_marker_schema=1,
        store_id="synthetic-store",
        registry_id="synthetic-registry",
    )

    def store_factory(driver):
        return Neo4jWorkflowStore(
            driver,
            database=binding.database,
            deployment_id=binding.deployment_id,
            workspace_id=binding.workspace_id,
        )

    driver = driver_factory()
    with driver.session(database=binding.database) as session:
        for ddl in Neo4jWorkflowStore.schema_requirements():
            session.run(ddl).consume()
        session.run("CALL db.awaitIndexes(30)").consume()
    store = store_factory(driver)
    authority = Authority()
    screens = []
    admin = WorkflowProfileAdmin(store, authority)
    admin.initialize_scope("bootstrap-operator", binding, protect=screens.append)
    root = tmp_path / "artifacts"
    admin.initialize_artifacts("bootstrap-operator", binding, root=root, create=True, protect=screens.append)
    profile = admin.register_profile("bootstrap-operator", registration(), protect=screens.append)
    settings = Settings(binding=binding, artifact_root=root, required_profiles=(profile,))
    import time

    from isaaclab_arena.agentic_environment_generation.workflow.api.security import (
        TokenRegistry,
    )

    tokens = TokenRegistry(binding=binding, instance=uuid.uuid4().hex, generation=1, clock=time.time)
    token = tokens.issue(principal="scoped-reader", lifetime=300.0)
    # Test-only token handoff; never retained in evidence.
    authority.headers = {"Authorization": "Bearer " + token}
    composition = Composition(
        create_driver=driver_factory,
        create_store=store_factory,
        authority=authority,
        bootstrap_principal="bootstrap-operator",
        read_principal="scoped-reader",
        protect=screens.append,
        tokens=tokens,
    )
    yield settings, composition, store, driver, screens
    driver.close()


def retained_contract(*, policy=False, existing=False):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        parse_contract,
    )

    profile = {"profile_id": "synthetic", "settings_sha256": "a" * 64}
    criterion = {
        "criterion_id": "visible",
        "kind": "visual",
        "evidence_producer": "visual-v1",
        "requirement": "required",
        "evaluator_version": "1",
        "required_modalities": ["rgb"],
        "coordinate_frames": ["external_camera"],
        "observation_window": {"start_step": 0, "end_step": 1},
        "rubric": "Target is visible",
        "subjects": ["banana"],
        "limit": {"operator": "eq", "value": 1.0, "unit": "boolean"},
    }
    criteria = [criterion]
    if policy:
        criteria.append({
            **criterion,
            "criterion_id": "policy",
            "kind": "policy",
            "required_modalities": ["policy_rollout"],
            "evidence_producer": "policy-v1",
        })
    return parse_contract(
        json.dumps({
            "schema_version": "1",
            "source": (
                {
                    "kind": "existing",
                    "identity": "candidate-1",
                    "content": "opaque-yaml",
                }
                if existing
                else {"kind": "new", "prompt": "Banana on maple table"}
            ),
            "criteria": criteria,
            "preserved": [],
            "allowed_interventions": [],
            "execution": {
                "generation_model": {**profile, "billing": "free"},
                "assessment_model": {**profile, "billing": "free"},
                "runtime": profile,
                "database": profile,
                "policy": profile if policy else None,
                "capture": profile,
                "seed": 1,
                "timestep_seconds": 0.01,
                "decimation": 1,
                "dcrg": None,
            },
            "budget": {
                "max_candidates": 2,
                "max_revisions": 1,
                "max_runtime_seconds": 60.0,
                "max_model_calls": 8,
                "max_model_tokens": 10000,
                "max_cost_usd": 1.0,
                "max_realizations": 2,
                "max_steps": 100,
                "max_observations": 2,
                "max_policy_episodes": 2 if policy else 0,
                "max_policy_steps": 100 if policy else 0,
                "per_operation_timeout_seconds": 10.0,
                "total_deadline_seconds": 60.0,
            },
            "effects": {
                "allow_paid_models": False,
                "allow_runtime": True,
                "allow_database_reads": False,
                "allow_operational_writes": True,
                "allow_publication": False,
            },
        })
    )


def test_open_only_catalogue_through_fresh_asgi_clients(prepared):
    settings, composition, store, driver, screens = prepared

    async def scenario():
        app = create_app(settings=settings, composition=composition)
        async with app.router.lifespan_context(app):
            for _ in range(2):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://isolated",
                    trust_env=False,
                    headers=composition.authority.headers,
                ) as client:
                    response = await client.post(
                        "/graphql",
                        json={"query": (DOCUMENTS / "catalogue.graphql").read_text()},
                    )
                    assert response.status_code == 200, "actual query catalogue endpoint unavailable"
                    body = response.json()
                    assert "errors" not in body, body
                    rows = body["data"]["workflowProfiles"]["profiles"]
                    assert [
                        {
                            k: row[k]
                            for k in (
                                "id",
                                "revision",
                                "kind",
                                "roles",
                                "settingsDigest",
                                "bodyDigest",
                                "model",
                                "endpoint",
                                "billing",
                            )
                        }
                        for row in rows
                    ] == [{
                        "id": "public-model",
                        "revision": str(2**63 - 1),
                        "kind": "model",
                        "roles": ["assessment_model", "generation_model"],
                        "settingsDigest": settings.required_profiles[0].settings_sha256,
                        "bodyDigest": settings.required_profiles[0].body_sha256,
                        "model": "gpt-4.1",
                        "endpoint": "https://api.openai.com/v1/",
                        "billing": "free",
                    }]

    asyncio.run(scenario())
    with driver.session(database=settings.binding.database) as session:
        rows = session.run(
            "MATCH (p:ArenaWorkflowProfileRevision {deployment_id:$d, workspace_id:$w}) RETURN p.profile_id AS id,"
            " p.revision AS revision",
            d=settings.binding.deployment_id,
            w=settings.binding.workspace_id,
        ).data()
        assert rows == [{"id": "public-model", "revision": 2**63 - 1}]
    Path("/evidence/graphql-joined.json").write_text(json.dumps({"fresh_clients": 2, "profile_readback": rows}))
