# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Managed execution uses fake pipes, real SQLite, and no provider transport."""

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from isaaclab_arena.agentic_environment_generation.prior_receipt import effective_settings
from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena_examples.agentic_environment_generation.web_api import editor_execution as execution


def test_cancellation_intent_requires_cleanup_ack(tmp_path):
    journal = Journal(tmp_path / "journal.sqlite3")
    job = journal.submit("s", "w", "generate", "one", {"operation": "new"})
    identity = journal.claim_attempt(job["id"])
    journal.record_worker(job["id"], 123, {"start": 1})
    assert journal.request_cancel_attempt(job["id"], **identity, expected_state="claimed")
    assert journal.get_job(job["id"])["status"] == "cancel_requested"
    assert not journal.release_attempt(job["id"], **identity)
    assert not journal.cancel_attempt(job["id"], **identity, expected_state="cancel_requested")
    journal.worker_cleaned(job["id"])
    assert journal.cancel_attempt(job["id"], **identity, expected_state="cancel_requested")
    assert journal.get_job(job["id"])["status"] == "cancelled"
    journal.close()


def harness(
    tmp_path,
    monkeypatch,
    *,
    spawn_hook=None,
    read_hook=None,
    result=True,
    authorize=None,
):
    journal = Journal(tmp_path / "journal.sqlite3")
    job = journal.submit("s", "w", "generate", "one", {"operation": "new", "execution_catalogue_sha256": "a" * 64})
    receipt = {
        "yaml_text": "scene",
        "validation": {"valid": True},
        "traces": [],
        "publication": "not_published",
        "warnings": [],
        "operation": "new",
        "prior_snapshot": {
            "effective_settings": effective_settings(),
            "timing": {"source": "local_monotonic", "elapsed_seconds": 0.01},
            "status": "empty",
            "derived_filters": {"emb_filter": "", "fixture_filter": ""},
            "priors": [],
            "exact_context": "",
            "context_sha256": hashlib.sha256(b"").hexdigest(),
            "warnings": [],
        },
        "catalogue_sha256": "a" * 64,
    }
    writes, order = [], []

    class Pipe:
        def write(self, body):
            assert journal.get_attempt(job["id"])["state"] == "released"
            writes.append(json.loads(body))

        async def drain(self):
            pass

        def close(self):
            pass

    class Output:
        sent = False

        async def readline(self):
            if read_hook:
                read_hook(journal, job)
            if self.sent or not result:
                return b""
            self.sent = True
            return (json.dumps({"result": receipt}) + "\n").encode()

    async def wait():
        if result and journal.get_attempt(job["id"])["state"] != "cancel_requested":
            assert journal.get_candidate_receipt(job["id"], **identity()) == receipt
        order.append("wait")
        return 0

    process = SimpleNamespace(pid=123, stdin=Pipe(), stdout=Output(), wait=wait)

    def identity():
        return {k: v for k, v in journal.get_attempt(job["id"]).items() if k != "state"}

    async def spawn(*args, **kwargs):
        assert journal.get_attempt(job["id"])["state"] == "claimed"
        if spawn_hook:
            spawn_hook(journal, job)
        return process

    async def stop():
        order.append("reaped")

    monkeypatch.setattr(execution.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(execution, "process_identity", lambda pid: {"start": 1})
    monkeypatch.setattr(execution, "make_snapshot_service", lambda path: None)
    runner = execution.EditorExecution(tmp_path, SimpleNamespace(validate=lambda text: {"valid": True}))

    def authorize_bound(job, *, attempt):
        assert attempt == identity()
        assert journal.get_attempt(job["id"])["state"] == "claimed"
        if authorize is not None:
            return authorize(job, attempt=attempt)
        return {"config": {"api_key": "private-key"}, "graph_config": None}

    runner.workflow_authorizer = authorize_bound
    runner.protect_workflow = lambda value: None
    supervisor = SimpleNamespace(journal=journal, process=None, job_id=None, stop_process=stop)
    return journal, job, runner, supervisor, writes, order, receipt


def test_managed_happy_candidate_is_durable_before_exit(tmp_path, monkeypatch):
    journal, job, runner, supervisor, writes, order, receipt = harness(tmp_path, monkeypatch)
    asyncio.run(runner.execute_managed(supervisor, job))
    assert journal.get_job(job["id"])["status"] == "succeeded"
    assert journal.get_job(job["id"])["result"] == receipt
    assert set(writes[0]) == {"inputs", "config", "graph_config"}
    assert order == ["wait", "reaped"]
    assert journal.pending_workers() == []
    asyncio.run(runner.execute_managed(supervisor, job))
    assert len(writes) == 1
    journal.close()


@pytest.mark.parametrize(
    "case", ["missing", "wrong_operation", "required_unavailable", "measured_empty", "oversized", "wrong_filters"]
)
def test_managed_receipt_rejects_inconsistent_retrieval(tmp_path, monkeypatch, case):
    journal, job, runner, _, _, _, receipt = harness(tmp_path, monkeypatch)
    snapshot = receipt["prior_snapshot"]
    if case == "missing":
        receipt["prior_snapshot"] = None
    elif case == "wrong_operation":
        snapshot["status"] = "not_requested"
    elif case == "required_unavailable":
        snapshot.update(status="unavailable", warnings=["unconfigured"])
        job["inputs"]["retrieval_policy"] = "require_service"
    elif case == "measured_empty":
        snapshot["status"] = "measured"
    elif case == "oversized":
        snapshot["exact_context"] = "x" * 32769
        snapshot["context_sha256"] = hashlib.sha256(snapshot["exact_context"].encode()).hexdigest()
    else:
        snapshot["derived_filters"]["emb_filter"] = "g1"
    try:
        with pytest.raises(ValueError):
            runner.validate_managed_receipt(job, receipt)
    finally:
        journal.close()


@pytest.mark.parametrize("when", ["spawn", "released", "candidate"])
def test_cancel_races_fence_candidate_and_wait_for_reap(tmp_path, monkeypatch, when):
    def cancel(journal, job):
        attempt = journal.get_attempt(job["id"])
        state = attempt.pop("state")
        journal.request_cancel_attempt(job["id"], **attempt, expected_state=state)

    count = 0

    def read(journal, job):
        nonlocal count
        count += 1
        if when == "released" or (when == "candidate" and count == 2):
            cancel(journal, job)

    journal, job, runner, supervisor, writes, order, _ = harness(
        tmp_path,
        monkeypatch,
        spawn_hook=cancel if when == "spawn" else None,
        read_hook=read,
    )
    asyncio.run(runner.execute_managed(supervisor, job))
    assert journal.get_job(job["id"])["status"] == "cancelled"
    assert order[-1] == "reaped"
    assert bool(writes) == (when != "spawn")
    journal.close()


def test_unknown_released_work_is_indeterminate(tmp_path, monkeypatch):
    journal, job, runner, supervisor, _, _, _ = harness(tmp_path, monkeypatch, result=False)
    asyncio.run(runner.execute_managed(supervisor, job))
    assert journal.get_job(job["id"])["status"] == "indeterminate"
    assert journal.claim_attempt(job["id"]) is None
    journal.close()


@pytest.mark.parametrize("post_spawn", [False, True])
def test_missing_authorization_blocks_and_counts_quota(tmp_path, monkeypatch, post_spawn):
    calls = 0

    def authorize(job, *, attempt):
        nonlocal calls
        calls += 1
        if calls > int(post_spawn):
            raise ValueError("revoked private-key")
        return {"config": {"api_key": "private-key"}, "graph_config": None}

    journal, job, runner, supervisor, writes, _, _ = harness(tmp_path, monkeypatch, authorize=authorize)
    asyncio.run(runner.execute_managed(supervisor, job))
    assert journal.get_job(job["id"])["status"] == "blocked_authorization"
    assert not writes
    with pytest.raises(ValueError, match="capacity"):
        journal.submit("s", "w", "generate", "two", {}, max_pending=1)
    assert journal.claim_attempt(job["id"]) is None
    journal.close()


def test_stale_progress_is_fenced(tmp_path):
    journal = Journal(tmp_path / "journal.sqlite3")
    job = journal.submit("s", "w", "generate", "one", {})
    attempt = journal.claim_attempt(job["id"])
    assert journal.release_attempt(job["id"], **attempt)
    assert journal.progress_attempt(job["id"], **attempt, expected_state="released", stage="spec_inference")
    assert journal.request_cancel_attempt(job["id"], **attempt, expected_state="released")
    cursor = journal.snapshot()["event_cursor"]
    assert not journal.progress_attempt(job["id"], **attempt, expected_state="released", stage="generation_completed")
    assert journal.snapshot()["event_cursor"] == cursor
    journal.close()


def test_modern_large_receipt_additive_bound_and_restart(tmp_path, monkeypatch):
    journal, job, runner, supervisor, _, _, receipt = harness(tmp_path, monkeypatch)
    receipt["yaml_text"] = "scene" * 20000
    asyncio.run(runner.execute_managed(supervisor, job))
    assert journal.get_job(job["id"])["status"] == "succeeded"
    assert "65536" in journal.db.execute("SELECT sql FROM sqlite_master WHERE name='candidate_receipts'").fetchone()[0]
    journal.close()
    journal = Journal(tmp_path / "journal.sqlite3")
    attempt = journal.get_attempt(job["id"])
    attempt.pop("state")
    assert journal.get_candidate_receipt(job["id"], **attempt) == receipt
    journal.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("warnings", ["raw provider error"]),
        ("catalogue_sha256", "bad"),
        ("prior_snapshot", {"error": "raw provider error"}),
    ],
)
def test_modern_receipt_rejects_unallowlisted_data(tmp_path, monkeypatch, field, value):
    journal, job, runner, supervisor, _, _, receipt = harness(tmp_path, monkeypatch)
    receipt[field] = value
    asyncio.run(runner.execute_managed(supervisor, job))
    assert journal.get_job(job["id"])["status"] == "indeterminate"
    assert "raw provider error" not in json.dumps(journal.snapshot())
    journal.close()


def test_supervisor_routes_modern_only(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.supervisor import Supervisor

    journal = Journal(tmp_path / "journal.sqlite3")
    journal.submit("s", "w", "generate", "one", {"operation": "new"})
    supervisor = Supervisor(journal)
    called = []

    async def modern(owner, job):
        called.append("modern")
        owner.stopping = True

    async def legacy(owner, job):
        called.append("legacy")
        owner.stopping = True

    supervisor.editor_execution = SimpleNamespace(execute_managed=modern, execute=legacy)
    asyncio.run(supervisor.run())
    assert called == ["modern"]
    journal.close()


def test_restart_adoption_waits_for_worker_cleanup(tmp_path):
    journal = Journal(tmp_path / "journal.sqlite3")
    job = journal.submit("s", "w", "generate", "one", {"operation": "new"})
    attempt = journal.claim_attempt(job["id"])
    journal.record_worker(job["id"], 123, {"start": 1})
    journal.release_attempt(job["id"], **attempt)
    journal.commit_candidate(job["id"], **attempt, receipt={"candidate": "safe"})
    journal.begin_run()
    assert journal.get_job(job["id"])["status"] == "running"
    journal.worker_cleaned(job["id"])
    assert journal.get_job(job["id"])["status"] == "succeeded"
    journal.close()


def test_post_spawn_rotation_and_locally_retained_secret_guard(tmp_path, monkeypatch):
    calls = 0

    def authorize(job, *, attempt):
        nonlocal calls
        calls += 1
        return {
            "config": {"api_key": "old-key" if calls == 1 else "new-key"},
            "graph_config": {"password": "graph-secret"},
        }

    journal, job, runner, supervisor, writes, _, receipt = harness(tmp_path, monkeypatch, authorize=authorize)
    receipt["yaml_text"] = "old-key"
    asyncio.run(runner.execute_managed(supervisor, job))
    assert calls == 2
    assert writes[0]["config"]["api_key"] == "new-key"
    assert journal.get_job(job["id"])["status"] == "indeterminate"
    journal.close()


def test_nested_prior_fields_are_allowlisted(tmp_path, monkeypatch):
    import hashlib

    journal, job, runner, supervisor, _, _, receipt = harness(tmp_path, monkeypatch)
    receipt["prior_snapshot"] = {
        "status": "empty",
        "derived_filters": {"error": "raw error"},
        "priors": [],
        "exact_context": "",
        "warnings": [],
        "context_sha256": hashlib.sha256(b"").hexdigest(),
    }
    asyncio.run(runner.execute_managed(supervisor, job))
    assert journal.get_job(job["id"])["status"] == "indeterminate"
    journal.close()
