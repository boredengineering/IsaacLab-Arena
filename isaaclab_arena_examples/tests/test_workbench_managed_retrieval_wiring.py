# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Managed generation wiring uses real local evidence and fake graph IO only."""

import importlib
import sqlite3

import pytest

from isaaclab_arena.tests.test_workbench_research_retrieval import TARGET
from isaaclab_arena.tests.test_workbench_research_retrieval import env as research_env


@pytest.fixture
def env(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import execution_catalogue_sha256

    execution_catalogue_sha256()  # Load real registries before the source fixture's permissive validation.
    yield from research_env.__wrapped__(tmp_path, monkeypatch)


def wiring():
    return importlib.import_module("isaaclab_arena_examples.agentic_environment_generation.web_api.managed_retrieval")


def context(tmp_path, store):
    return {
        "schema_version": 1,
        "journal_path": str(tmp_path / "journal.sqlite3"),
        "registry_id": store.registry.registry_id,
        "stores": [{"store_id": "store", "root": str(tmp_path / "store")}],
        "authorized_targets": {"graph": TARGET},
        "graph": {"uri": "bolt://graph.invalid:7687", "database": "research"},
    }


def test_read_attachment_uses_existing_evidence_without_journal_initialization(env, tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena.agentic_environment_generation.workbench.research_retrieval import ManagedSelectionProvider

    store, attempts, driver, add = env
    add()
    before = list(attempts.journal.db.iterdump())
    monkeypatch.setattr(Journal, "__init__", lambda *a, **kw: pytest.fail("Reader initialized Journal"))
    with wiring().open_managed_provider(context(tmp_path, store)) as provider:
        assert isinstance(provider, ManagedSelectionProvider)
        rows = provider(driver, min_success_rate=0, min_episodes=1)
        assert len(rows) == 1 and rows[0]["_canonical_proof"]
        reader = provider._stores[0][1].journal
        with pytest.raises(sqlite3.DatabaseError):
            reader.db.execute("DELETE FROM metadata")
        with pytest.raises(sqlite3.DatabaseError):
            reader.db.execute("CREATE TABLE unsafe(x)")
        for statement in (
            "ATTACH DATABASE ':memory:' AS unsafe",
            "PRAGMA writable_schema=ON",
            "PRAGMA wal_checkpoint(TRUNCATE)",
            "VACUUM",
            "BEGIN",
        ):
            with pytest.raises(sqlite3.DatabaseError):
                reader.db.execute(statement)
    with pytest.raises(sqlite3.ProgrammingError):
        reader.db.execute("SELECT 1")
    assert list(attempts.journal.db.iterdump()) == before


def combined_driver(driver):
    from isaaclab_arena.agentic_environment_generation import graph_rag

    original = driver.session

    def session(**kwargs):
        result = original(**kwargs)
        run = result.run

        def query(query, **params):
            if str(query) in (graph_rag._SNAPSHOT_EVALUATED_QUERY, graph_rag._SNAPSHOT_STRUCTURAL_QUERY):
                driver.calls.append((str(query), params))
                return []
            return run(query, **params)

        result.run = query

        class Session:
            def __getattr__(self, name):
                return getattr(result, name)

            def __enter__(self):
                return result

            def __exit__(self, *exc):
                result.close()

        return Session()

    driver.session = session
    driver.closed = False
    driver.close = lambda: setattr(driver, "closed", True)
    return driver


def test_generation_adapter_consumes_real_managed_provider_context_once(env, tmp_path, monkeypatch):
    import yaml
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation import lpg_neo4j_sync
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation
    from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import execution_catalogue_sha256
    from isaaclab_arena_examples.tests.test_workbench_generation_receipts import CONFIG, FIXTURE

    store, _, driver, add = env
    add()
    driver = combined_driver(driver)
    seen = []
    monkeypatch.setattr(lpg_neo4j_sync, "get_neo4j_driver", lambda **kw: driver)

    class Agent:
        telemetry = SimpleNamespace(converged=True)

        def __init__(self, **kwargs):
            pass

        def generate_spec(self, prompt, **kwargs):
            assert kwargs["publish_to_graph"] is False
            seen.append(kwargs["prior_context"])
            return ArenaEnvGraphSpec.from_dict(yaml.safe_load(FIXTURE.read_text())), None

    graph = {**context(tmp_path, store)["graph"], "user": "reader", "password": "synthetic-reader-secret"}
    result = generation.generate(
        {"operation": "new", "prompt": "Move object", "execution_catalogue_sha256": execution_catalogue_sha256()},
        lambda stage: None,
        config=CONFIG,
        graph_config=graph,
        managed_context=context(tmp_path, store),
        agent_factory=Agent,
    )
    assert result["prior_snapshot"]["status"] == "structural"
    assert seen == [result["prior_snapshot"]["exact_context"]]
    assert seen[0]
    assert sum(q.startswith("// managed evaluation") for q, _ in driver.calls) == 1
    assert all("CREATE" not in q and "MERGE" not in q for q, _ in driver.calls)
    assert all(s.options["database"] == "research" for s in driver.sessions)
    assert driver.closed


@pytest.mark.parametrize("failure", ["evaluation", "reconcile", "transaction", "rollback", "legacy"])
@pytest.mark.parametrize("policy", ["allow_fallback", "require_service"])
def test_inner_graph_cleanup_vetoes_generation(env, tmp_path, monkeypatch, failure, policy):
    from isaaclab_arena.agentic_environment_generation import lpg_neo4j_sync
    from isaaclab_arena.tests.test_workbench_research_graph_transport import Transaction
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation
    from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import execution_catalogue_sha256
    from isaaclab_arena_examples.tests.test_workbench_generation_receipts import CONFIG

    store, _, driver, add = env
    add()
    combined_driver(driver)
    original = driver.session
    cleaned = []

    def broken():
        cleaned.append(failure)
        raise OSError("private-cleanup-secret")

    def session(**options):
        result = original(**options)
        target = {"evaluation": 2, "reconcile": 128, "legacy": 6}.get(failure)
        if options["fetch_size"] == target:
            # The wrapper delegates __exit__ to the underlying session's close.
            underlying = result.__enter__()
            underlying.close = broken
        return result

    monkeypatch.setattr(driver, "session", session)
    if failure in {"transaction", "rollback"}:

        def close(tx):
            tx.closed = True
            if failure == "rollback":
                tx.rollback()
            else:
                broken()

        monkeypatch.setattr(Transaction, "close", close)
        monkeypatch.setattr(Transaction, "rollback", lambda tx: broken(), raising=False)
    monkeypatch.setattr(lpg_neo4j_sync, "get_neo4j_driver", lambda **kw: driver)
    stages = []
    with pytest.raises(ValueError, match="cleanup") as caught:
        generation.generate(
            {
                "operation": "new",
                "prompt": "Move object",
                "retrieval_policy": policy,
                "execution_catalogue_sha256": execution_catalogue_sha256(),
            },
            stages.append,
            config=CONFIG,
            graph_config={**context(tmp_path, store)["graph"], "user": "reader", "password": "reader-secret"},
            managed_context=context(tmp_path, store),
            agent_factory=lambda **kw: pytest.fail("Cleanup failure reached agent construction"),
        )
    from isaaclab_arena.agentic_environment_generation.graph_cleanup import GraphCleanupError
    from isaaclab_arena.agentic_environment_generation.workbench.research_graph_transport import OutcomeUnknown

    assert isinstance(caught.value, GraphCleanupError)
    assert isinstance(caught.value, OutcomeUnknown) == (failure in {"reconcile", "transaction", "rollback"})
    assert "private-cleanup-secret" not in str(caught.value)
    assert cleaned == [failure]
    assert driver.closed
    assert "agent_initializing" not in stages and "result_validating" not in stages


def test_api_opt_in_freezes_private_references_and_rechecks_profile(env, tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, generation, graph_access
    from isaaclab_arena_examples.tests.test_workbench_editor import ORIGIN, login
    from isaaclab_arena_examples.tests.test_workbench_workflow_authorization import BODY, MODEL

    store, _, driver, _ = env
    graph = {**context(tmp_path, store)["graph"], "user": "reader", "password": "synthetic-reader-secret"}
    profiles = {
        "graph": {
            "connection": {**graph, "user": "writer", "password": "synthetic-writer-secret"},
            "immutable_scope": True,
        }
    }
    monkeypatch.setattr(generation, "configuration", lambda: dict(MODEL))
    monkeypatch.setattr(graph_access, "configuration", lambda: dict(graph))
    app = create_app(
        tmp_path,
        start_paused=True,
        research_roots={"store": tmp_path / "store"},
        publication_profiles=profiles,
        managed_retrieval_enabled=True,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        response = client.post("/api/editor/generate", headers=headers, json=BODY)
        assert response.status_code == 202, response.text
        job = response.json()
        private = app.state.workflow_authorization.resolve(job)
        frozen = private["managed_context"]
        assert frozen["registry_id"] == store.registry.registry_id
        assert frozen["graph"] == {key: graph[key] for key in ("uri", "database")}
        assert frozen["authorized_targets"]["graph"] == app.state.publication_authorization.profile_metadata("graph")
        assert "synthetic-writer-secret" not in json.dumps(private)
        assert str(tmp_path) not in response.text
        assert not driver.calls
        assert (
            client.post("/api/editor/generate", headers=headers, json={**BODY, "managed_context": frozen}).status_code
            == 422
        )
        frozen["stores"].clear()
        assert app.state.workflow_authorization.resolve(job)["managed_context"]["stores"]
        app.state.publication_profiles["graph"]["connection"]["database"] = "foreign"
        with pytest.raises(ValueError):
            app.state.workflow_authorization.resolve(job)
        assert client.post("/api/editor/generate", headers=headers, json=BODY).json() == job


def generation_child(evidence_path, report_path):
    """Test-only bootstrap: real worker/provider with denied sockets and fake IO."""
    import json
    import socket
    import yaml
    from contextlib import nullcontext
    from pathlib import Path
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation import environment_generation_agent, lpg_neo4j_sync
    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.tests.test_workbench_research_graph_transport import Driver
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation, generation_worker

    evidence = json.loads(Path(evidence_path).read_text())
    driver = Driver()
    for field in ("nodes", "edges", "constraints"):
        setattr(driver, field, evidence[field])
    original = driver.session

    def session(**kwargs):
        result = original(**kwargs)
        run = result.run

        def query(query, **params):
            if str(query).startswith("// managed evaluation"):
                driver.calls.append((str(query), params))
                return []
            return run(query, **params)

        result.run = query
        return result

    driver.session = session
    combined_driver(driver)
    if evidence.get("cleanup_failure"):
        close = driver.close

        def broken_close():
            close()
            raise OSError("Synthetic graph cleanup failure")

        driver.close = broken_close
    seen = []

    def denied(*args, **kwargs):
        raise AssertionError("Live IO or Journal initialization forbidden")

    socket.socket.connect = denied
    socket.create_connection = denied
    Journal.__init__ = denied
    lpg_neo4j_sync.get_neo4j_driver = lambda **kwargs: driver

    class Agent:
        telemetry = SimpleNamespace(converged=True)

        def __init__(self, **kwargs):
            pass

        def generate_spec(self, prompt, **kwargs):
            assert kwargs["publish_to_graph"] is False
            seen.append(kwargs["prior_context"])
            return ArenaEnvGraphSpec.from_dict(yaml.safe_load(evidence["yaml_text"])), None

    environment_generation_agent.EnvironmentGenerationAgent = Agent
    generation.bounded_client = lambda config: nullcontext()  # No model transport in this fixture.
    result = generation_worker.main()
    Path(report_path).write_text(
        json.dumps({
            "code": result,
            "seen": seen,
            "queries": [q for q, _ in driver.calls],
            "databases": [s.options["database"] for s in driver.sessions],
            "closed": driver.closed,
            "commits": driver.commits,
        })
    )
    return result


@pytest.mark.parametrize(
    "case", ["success", "expired_after_spawn", "profile_removed_after_spawn", "missing_proof", "cleanup_failure"]
)
def test_real_api_to_owned_generation_child_consumes_exact_managed_context(env, tmp_path, monkeypatch, case):
    import asyncio
    import json

    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, generation, graph_access
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_authorization import (
        PublicationAuthorization,
    )
    from isaaclab_arena_examples.tests.test_workbench_editor import FIXTURE, ORIGIN, login
    from isaaclab_arena_examples.tests.test_workbench_workflow_authorization import BODY, MODEL

    store, _, driver, add = env
    graph = {**context(tmp_path, store)["graph"], "user": "reader", "password": "synthetic-reader-secret"}
    profiles = {
        "graph": {
            "connection": {**graph, "user": "writer", "password": "synthetic-writer-secret"},
            "immutable_scope": True,
        }
    }
    target = PublicationAuthorization(None, lambda: profiles).profile_metadata("graph")
    add(target=target)
    evidence = tmp_path / "fake-io.json"
    evidence.write_text(
        json.dumps({
            **{key: getattr(driver, key) for key in ("nodes", "edges", "constraints")},
            "yaml_text": FIXTURE.read_text(),
            "cleanup_failure": case == "cleanup_failure",
        })
    )
    report = tmp_path / "child-report.json"
    original_spawn = asyncio.create_subprocess_exec
    releases = []
    now = [1000.0]

    async def spawn(*args, **kwargs):
        assert "generation_worker" in args[3]
        releases.append(args)
        script = (
            "from isaaclab_arena_examples.tests.test_workbench_managed_retrieval_wiring "
            "import generation_child; raise SystemExit(generation_child("
            + repr(str(evidence))
            + ","
            + repr(str(report))
            + "))"
        )
        process = await original_spawn(args[0], "-u", "-c", script, *args[4:], **kwargs)
        if case == "expired_after_spawn":
            now[0] += 180
        elif case == "profile_removed_after_spawn":
            app.state.publication_profiles.clear()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(generation, "configuration", lambda: dict(MODEL))
    monkeypatch.setattr(graph_access, "configuration", lambda: dict(graph))
    app = create_app(
        tmp_path,
        start_paused=True,
        clock=lambda: now[0],
        research_roots={"store": tmp_path / "store"},
        publication_profiles=profiles,
        managed_retrieval_enabled=True,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        body = {**BODY, "retrieval_policy": "require_service"}
        response = client.post("/api/editor/generate", headers=headers, json=body)
        assert response.status_code == 202, response.text
        job = response.json()
        if case == "missing_proof":
            app.state.journal.db.execute("DROP TABLE publication_receipts")
        assert not driver.calls  # API acceptance did no graph work.
        app.state.journal.resume_queue()  # Only this isolated fixture's accepted generation is dispatched.
        client.portal.call(app.state.editor_execution.execute_managed, app.state.supervisor, job)
        actual = client.get("/api/jobs/" + job["id"]).json()
        if case in {"expired_after_spawn", "profile_removed_after_spawn"}:
            assert actual["status"] == "blocked_authorization"
            assert not report.exists()
            assert app.state.journal.pending_workers() == []
            assert len(releases) == 1
            return
        if case in {"missing_proof", "cleanup_failure"}:
            assert actual["status"] == "indeterminate"
            child = json.loads(report.read_text())
            assert child["seen"] == [] and child["closed"] and child["commits"] == 0
            assert app.state.journal.pending_workers() == []
            return
        assert actual["status"] == "succeeded", (actual, report.read_text() if report.exists() else "no child report")
        child = json.loads(report.read_text())
        assert child["code"] == 0 and child["closed"]
        assert child["seen"] == [actual["result"]["prior_snapshot"]["exact_context"]]
        assert actual["result"]["prior_snapshot"]["status"] == "structural"
        assert child["seen"][0]
        assert child["commits"] == 0
        assert all(db == "research" for db in child["databases"])
        assert sum(q.startswith("// managed evaluation") for q in child["queries"]) == 1
        assert all("MERGE" not in q and "CREATE" not in q for q in child["queries"])
        assert app.state.journal.pending_workers() == []
        assert len(releases) == 1
        replay = client.post("/api/editor/generate", headers=headers, json=body)
        assert replay.status_code == 202
        client.portal.call(app.state.editor_execution.execute_managed, app.state.supervisor, job)
        assert len(releases) == 1


@pytest.mark.parametrize(
    "bad",
    [
        "unsolicited",
        "missing",
        "digest",
        "database",
        "future",
        "extra",
        "root",
        "targets",
        "duplicate",
        "oversized",
        "refine",
    ],
)
def test_private_context_contract_rejects_before_attachment(env, tmp_path, bad):
    from copy import deepcopy

    module = wiring()
    managed = context(tmp_path, env[0])
    graph = {**managed["graph"], "user": "reader", "password": "synthetic-reader-secret"}
    inputs = {
        "operation": "new",
        "workflow_authorization": {
            "retrieval": {"profile": {"managed_context_sha256": module.context_digest(managed)}}
        },
    }
    private = {"graph_config": graph, "managed_context": deepcopy(managed)}
    if bad == "unsolicited":
        inputs.pop("workflow_authorization")
    elif bad == "missing":
        private.pop("managed_context")
    elif bad == "digest":
        private["managed_context"]["registry_id"] = "different"
    elif bad == "database":
        graph["database"] = "foreign"
    elif bad == "refine":
        inputs["operation"] = "refine"
    else:
        value = private["managed_context"]
        if bad == "future":
            value["schema_version"] = 2
        elif bad == "extra":
            value["password"] = "unsolicited-writer"
        elif bad == "root":
            value["stores"][0]["root"] = "relative/path"
        elif bad == "targets":
            value["authorized_targets"]["graph"]["scope_ownership"] = "unverified"
        elif bad == "duplicate":
            value["stores"] *= 2
        else:
            value["stores"][0]["root"] = "/" + "x" * 32768
        inputs["workflow_authorization"]["retrieval"]["profile"]["managed_context_sha256"] = module.context_digest(
            value
        )
    with pytest.raises(ValueError):
        module.private_context(inputs, private)


@pytest.mark.parametrize(
    "bad",
    [
        "journal_symlink",
        "journal_hardlink",
        "journal_future",
        "registry_future",
        "publication_future",
        "registry_mismatch",
        "missing_proof",
    ],
)
def test_existing_source_rejections_never_initialize_or_write(env, tmp_path, bad):
    import os

    store, attempts, _, add = env
    add()
    value = context(tmp_path, store)
    if bad == "journal_symlink":
        link = tmp_path / "alias.sqlite3"
        link.symlink_to(value["journal_path"])
        value["journal_path"] = str(link)
    elif bad == "journal_hardlink":
        os.link(value["journal_path"], tmp_path / "hardlink.sqlite3")
    elif bad == "journal_future":
        attempts.journal.db.execute("PRAGMA user_version=2")
    elif bad == "registry_future":
        attempts.journal.db.execute("UPDATE research_registry_meta SET schema_version=2")
    elif bad == "publication_future":
        attempts.journal.db.execute("UPDATE publication_meta SET schema_version=2")
    elif bad == "registry_mismatch":
        value["registry_id"] = "foreign"
    else:
        attempts.journal.db.execute("DROP TABLE publication_receipts")
    attempts.journal.db.commit()
    before = list(attempts.journal.db.iterdump())
    with pytest.raises((ValueError, RuntimeError, sqlite3.DatabaseError)):
        with wiring().open_managed_provider(value):
            pytest.fail("Invalid source accepted")
    assert list(attempts.journal.db.iterdump()) == before


def test_parent_rejects_oversized_envelope_before_release(tmp_path, monkeypatch):
    import asyncio

    from isaaclab_arena_examples.tests.test_workbench_managed_execution import harness

    journal, job, runner, supervisor, writes, _, _ = harness(tmp_path, monkeypatch, result=False)
    job["inputs"]["prompt"] = "x" * (512 * 1024)
    try:
        asyncio.run(runner.execute_managed(supervisor, job))
        assert not writes
        assert journal.get_attempt(job["id"])["state"] == "failed"
        assert journal.pending_workers() == []
    finally:
        journal.close()


def test_store_cleanup_failure_vetoes_retrieval_receipt(env, tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_access import retrieve_snapshot

    store, _, driver, add = env
    add()
    combined_driver(driver)
    close = ResearchStore.close

    def broken_close(instance):
        close(instance)
        raise OSError("synthetic cleanup failure")

    with monkeypatch.context() as patch:
        patch.setattr(ResearchStore, "close", broken_close)
        graph = {**context(tmp_path, store)["graph"], "user": "reader", "password": "synthetic-reader-secret"}
        with pytest.raises(ValueError, match="cleanup"):
            retrieve_snapshot(
                "Move object", graph, driver_factory=lambda **kw: driver, managed_context=context(tmp_path, store)
            )
    assert driver.closed


@pytest.mark.parametrize("bad", ["unsolicited", "missing", "malformed", "extra_envelope", "model_secret"])
def test_parent_and_worker_both_reject_invalid_context_before_generation(env, tmp_path, monkeypatch, capsys, bad):
    import asyncio
    import io
    import json
    import os
    import sys
    from copy import deepcopy
    from types import SimpleNamespace

    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation, generation_worker
    from isaaclab_arena_examples.tests.test_workbench_generation_receipts import CONFIG
    from isaaclab_arena_examples.tests.test_workbench_managed_execution import harness

    value = context(tmp_path, env[0])
    inputs = {
        "operation": "new",
        "execution_catalogue_sha256": "a" * 64,
        "workflow_authorization": {
            "retrieval": {"profile": {"managed_context_sha256": wiring().context_digest(value)}}
        },
    }
    private = {
        "config": CONFIG,
        "graph_config": {**value["graph"], "user": "reader", "password": "synthetic-read-secret"},
        "managed_context": value,
    }
    if bad == "unsolicited":
        inputs.pop("workflow_authorization")
    elif bad == "missing":
        private.pop("managed_context")
    elif bad == "extra_envelope":
        private["extra_context"] = "unapproved"
    elif bad == "model_secret":
        value["stores"][0]["root"] += "/" + CONFIG["api_key"]
        inputs["workflow_authorization"]["retrieval"]["profile"]["managed_context_sha256"] = wiring().context_digest(
            value
        )
    else:
        value["schema_version"] = 2
    dispatch = tmp_path / "dispatch"
    dispatch.mkdir()
    journal, job, runner, supervisor, writes, _, _ = harness(
        dispatch, monkeypatch, result=False, authorize=lambda *a, **kw: deepcopy(private)
    )
    job["inputs"] = inputs
    try:
        asyncio.run(runner.execute_managed(supervisor, job))
        assert not writes
        assert journal.get_job(job["id"])["status"] == "blocked_authorization"
    finally:
        journal.close()
    envelope = {"inputs": inputs, **private}
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO((json.dumps(envelope) + "\n").encode())))
    monkeypatch.setattr(sys, "argv", ["worker", "--parent-pid", str(os.getppid())])
    monkeypatch.setattr(generation_worker.ctypes, "CDLL", lambda *a, **kw: SimpleNamespace(prctl=lambda *a: 0))
    monkeypatch.setattr(generation, "generate", lambda *a, **kw: pytest.fail("Invalid context reached generation"))
    assert generation_worker.main() == 1
    assert CONFIG["api_key"] not in capsys.readouterr().out


@pytest.mark.parametrize("secret_source", ["writer", "reader"])
def test_operator_references_cannot_smuggle_credentials(env, tmp_path, secret_source):
    value = context(tmp_path, env[0])
    graph = {**value["graph"], "user": "reader", "password": "synthetic-reader-secret"}
    writer = {**graph, "password": "synthetic-writer-secret"}
    marker = writer["password"] if secret_source == "writer" else graph["password"]
    with pytest.raises(ValueError):
        wiring().configured_context(
            tmp_path / "journal.sqlite3",
            env[1].journal,
            {"store": tmp_path / marker},
            {"graph": {"connection": writer, "immutable_scope": True}},
            graph,
        )


@pytest.mark.parametrize("case", ["disabled", "refine", "unconfigured"])
def test_opt_in_does_not_change_refine_or_legacy_authorization(env, tmp_path, monkeypatch, case):
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, generation, graph_access
    from isaaclab_arena_examples.tests.test_workbench_editor import FIXTURE, ORIGIN, login
    from isaaclab_arena_examples.tests.test_workbench_workflow_authorization import BODY, MODEL

    graph = {**context(tmp_path, env[0])["graph"], "user": "reader", "password": "synthetic-reader-secret"}
    monkeypatch.setattr(generation, "configuration", lambda: dict(MODEL))
    monkeypatch.setattr(graph_access, "configuration", lambda: None if case == "unconfigured" else dict(graph))
    app = create_app(
        tmp_path,
        start_paused=True,
        managed_retrieval_enabled=case != "disabled",
        research_roots={"store": tmp_path / "store"},
        publication_profiles={"graph": {"connection": graph, "immutable_scope": True}},
    )
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        body = BODY if case != "refine" else {**BODY, "operation": "refine", "base_yaml": FIXTURE.read_text()}
        response = client.post("/api/editor/generate", headers=headers, json=body)
        assert response.status_code == 202, response.text
        private = app.state.workflow_authorization.resolve(response.json())
        assert set(private) == {"config", "graph_config"}
        assert private["graph_config"] == (graph if case == "disabled" else None)
        assert not env[2].calls


@pytest.mark.parametrize(
    "enabled,roots,profiles", [(1, {}, {}), (None, {}, {}), (True, {}, {}), (True, {"store": "/tmp/unused"}, {})]
)
def test_server_opt_in_is_explicit_and_requires_profiles(tmp_path, enabled, roots, profiles):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    with pytest.raises(ValueError, match="managed retrieval|Managed retrieval"):
        create_app(tmp_path, managed_retrieval_enabled=enabled, research_roots=roots, publication_profiles=profiles)
    assert not (tmp_path / "journal.sqlite3").exists()
