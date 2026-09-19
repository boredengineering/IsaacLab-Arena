# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Application helper units in the exact nonroot UDS sandbox; synthetic store."""
import importlib
from threading import RLock
from types import SimpleNamespace


def helper():
    return importlib.import_module("isaaclab_arena_examples.agentic_environment_generation.foreground_cancellation")


def application(root):
    root.mkdir(mode=0o700, exist_ok=True)
    calls = []

    def unavailable(*args, **kwargs):
        calls.append("db")
        raise ConnectionError("synthetic DB outage")

    app = SimpleNamespace(
        private_parent=root, _lock=RLock(), _local={}, _closed=False,
        authority=SimpleNamespace(scope=dict(database="neo4j", deployment_id="test", workspace_id="private")),
        store=SimpleNamespace(get_run=unavailable, request_cancel=unavailable),
        _check=lambda principal: None,
        status=unavailable,
        _unknown=lambda run_id: dict(disposition="unknown", run_id=run_id, state="unknown", available_actions=[]),
        _public=lambda result: result,
    )
    app.calls = calls
    return app


def test_non_ipc_composition_never_contacts_an_existing_owner(tmp_path):
    module = helper()
    owner = application(tmp_path / "private")
    client = application(owner.private_parent)
    client._owner_control = False
    module.start_owner_control(owner, "alice", "run-1")
    try:
        result = module.cancel_workflow(client, "alice", "run-1")
        assert result["local_stop"]["delivery"] == "no_owner"
        assert not module.stop_requested(owner, "run-1")
        assert not getattr(client, "_cancel_controls", {})
    finally:
        module.close_controls(owner)


def test_local_stop_precedes_first_db_read_and_latches_before_phase(tmp_path):
    module = helper()
    assert callable(getattr(module, "start_owner_control", None)), "Application cancellation helper missing"
    app = application(tmp_path / "private")
    module.start_owner_control(app, "alice", "run-1")
    try:
        result = module.cancel_workflow(app, "alice", "run-1")
        assert module.stop_requested(app, "run-1")
        assert result["local_stop"]["delivery"] == "delivered"
        assert result["durable_cancellation"] == "unconfirmed"
        assert app.calls == ["db"]
    finally:
        module.close_controls(app)
    assert module.stop_requested(app, "run-1"), "endpoint closure must not clear run stop"


def test_fresh_client_outage_stops_owned_coordinator_with_frozen_principal(tmp_path):
    module = helper()
    owner = application(tmp_path / "private")
    client = application(owner.private_parent)
    physical = []

    def stop(principal):
        assert principal == "alice"
        physical.append("stopped")
        return SimpleNamespace(cleanup_pending=False)

    owner._local["run-1"] = SimpleNamespace(
        principal="alice", coordinator=SimpleNamespace(stop_local=stop), ports=None,
        handle=None, retired=False, stopped=False,
    )
    owner._check = lambda p: (_ for _ in ()).throw(AssertionError("expired grant is not stop authority"))
    module.start_owner_control(owner, "alice", "run-1")
    try:
        def db(*args):
            assert physical == ["stopped"], "physical stop must precede ANY client DB read"
            raise ConnectionError("outage")
        client.status = db
        result = module.cancel_workflow(client, "alice", "run-1")
        assert result["local_stop"]["delivery"] == "delivered"
        assert physical == ["stopped"]
        assert owner._local["run-1"].stopped
        assert module.stop_requested(owner, "run-1")
    finally:
        module.close_controls(owner)


def test_cleanup_pending_never_acknowledges_and_retries_same_latch(tmp_path):
    module = helper()
    owner = application(tmp_path / "private")
    client = application(owner.private_parent)
    pending = [True]
    owner._local["run-1"] = SimpleNamespace(
        principal="alice",
        coordinator=SimpleNamespace(stop_local=lambda p: SimpleNamespace(cleanup_pending=pending[0])),
        ports=None, handle=None, retired=False, stopped=False,
    )
    module.start_owner_control(owner, "alice", "run-1")
    try:
        result = module.cancel_workflow(client, "alice", "run-1")
        assert result["local_stop"]["delivery"] == "unconfirmed"
        assert module.stop_requested(owner, "run-1")
        pending[0] = False
        assert module.cancel_workflow(client, "alice", "run-1")["local_stop"]["delivery"] == "delivered"
    finally:
        module.close_controls(owner)


def test_external_scene_cancel_acks_exact_local_cleanup_then_retires(tmp_path):
    module = helper()
    app = application(tmp_path / "private")
    events = []
    cleanup, fence = object(), object()
    run = SimpleNamespace(state="cancel_requested", version=3)

    def stopped():
        events.append("physical")
        return ((fence, cleanup),)

    def ack(actual_fence, actual_cleanup):
        assert actual_fence is fence and actual_cleanup is cleanup
        events.append("ack")
        run.state = "cancelled"

    def read(run_id):
        events.append("read")
        return run

    local = SimpleNamespace(
        principal="alice", retired=False, stopped=False, coordinator=None,
        ports=SimpleNamespace(stop_local=stopped, retire_cancelled=lambda: events.append("retire-readback-unlock")),
    )
    app._local["run-1"] = local
    app.store.get_run, app.store.acknowledge_scene_cleanup = read, ack
    module.start_owner_control(app, "alice", "run-1")
    try:
        assert callable(getattr(module, "finish_cancelled", None)), "Owner-side cancellation finalizer missing"
        assert module.finish_cancelled(app, "alice", "run-1", local)
        assert events == ["physical", "read", "ack", "read", "retire-readback-unlock"]
        assert local.retired and module.stop_requested(app, "run-1")
        assert module.finish_cancelled(app, "alice", "run-1", local)
        assert events.count("retire-readback-unlock") == 1
    finally:
        module.close_controls(app)


def test_generation_finish_verifies_local_capability_and_readback_before_unlock(tmp_path):
    module = helper()
    app = application(tmp_path / "private")
    actual = SimpleNamespace(registration="registration")
    deserialized = SimpleNamespace(registration="registration")
    assert deserialized == actual and deserialized is not actual
    run = SimpleNamespace(state="cancel_requested", version=4)
    events = []
    handle = SimpleNamespace(fence="fence", prepared=SimpleNamespace(registration="registration"), cleanup=actual)
    local = SimpleNamespace(principal="alice", retired=False, stopped=False, ports=None, handle=handle,
                            coordinator=SimpleNamespace(stop_local=lambda p: SimpleNamespace(cleanup_pending=False)),
                            worker=SimpleNamespace(cleanup_verified=lambda registration, evidence: evidence is actual))

    def ack(fence, cleanup):
        assert cleanup is actual
        events.append("ack")
        run.state = "cancelled"

    def retire(store, registration, cleanup):
        assert cleanup is actual and events == ["ack", "readback"]
        events.append("retire-readback-unlock")

    local.lease = SimpleNamespace(retire_and_release=retire)
    app._local["run-1"] = local
    app.store.get_run = lambda r: run
    app.store.acknowledge_cleanup = ack

    def attempt(fence):
        events.append("readback")
        return SimpleNamespace(cleanup=deserialized, registration="registration")

    app.store.get_attempt = attempt
    module.start_owner_control(app, "alice", "run-1")
    try:
        handle.cleanup = deserialized
        assert not module.finish_cancelled(app, "alice", "run-1", local)
        assert not events and not local.retired
        handle.cleanup = actual
        assert module.finish_cancelled(app, "alice", "run-1", local), "Generation cancellation must finish"
        assert events == ["ack", "readback", "retire-readback-unlock"]
        assert local.retired
    finally:
        module.close_controls(app)


def test_same_application_cancel_finishes_scene_without_a_second_driver(tmp_path):
    module = helper()
    app = application(tmp_path / "private")
    run = SimpleNamespace(state="running", version=4)
    events = []
    cleanup = object()

    def request(run_id, version):
        events.append("request")
        run.state = "cancel_requested"

    def ack(fence, evidence):
        assert evidence is cleanup
        events.append("ack")
        run.state = "cancelled"

    local = SimpleNamespace(
        principal="alice", retired=False, stopped=False, coordinator=None,
        ports=SimpleNamespace(stop_local=lambda: (("fence", cleanup),), retire_cancelled=lambda: events.append("retire")),
    )
    app._local["run-1"] = local
    app.store.get_run = lambda r: run
    app.store.request_cancel, app.store.acknowledge_scene_cleanup = request, ack
    app.status = lambda p, r: dict(
        state=run.state, version=run.version, disposition="retained", available_actions=["cancel"],
    )
    module.start_owner_control(app, "alice", "run-1")
    try:
        result = module.cancel_workflow(app, "alice", "run-1")
        assert result["durable_cancellation"] == "confirmed"
        assert events == ["request", "ack", "retire"] and local.retired
    finally:
        module.close_controls(app)


def test_distinct_application_cancel_reaps_owned_child_before_faulting_database(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    fixture = "/source/isaaclab_arena_examples/tests/foreground_control_fixture.py"
    owner = subprocess.Popen(
        [sys.executable, "-I", "-S", "-B", fixture, "--owner"],
        cwd="/source", env={"PATH": "/usr/bin:/bin"}, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    try:
        info = json.loads(owner.stdout.readline())
        assert info["owner_pid"] == owner.pid != os.getpid()
        child = Path(f'/proc/{info["child_pid"]}')
        assert child.exists()
        client = application(Path(info["root"]))
        db_reads = []

        def db(*args):
            db_reads.append(not child.exists())
            raise ConnectionError("synthetic outage AFTER physical cleanup")

        client.status = db
        result = helper().cancel_workflow(client, "alice", "run-application")
        assert result["local_stop"]["delivery"] == "delivered"
        assert result["durable_cancellation"] == "unconfirmed"
        assert db_reads == [True] and not child.exists()
        owner.stdin.write(b"finish\n")
        owner.stdin.flush()
        out, err = owner.communicate(timeout=5)
        assert owner.returncode == 0, err.decode()
        final = json.loads(out)
        assert final["application_sticky_stop"] and final["child_reaped"]
        assert final["forbidden"] == []
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)


def test_completion_race_does_not_retire_or_unlock_twice(tmp_path):
    from threading import Event, Thread

    module = helper()
    app = application(tmp_path / "private")
    entered, release = Event(), Event()
    retired, results = [], []
    cleanup = object()

    def retire():
        retired.append(1)
        if len(retired) == 1:
            entered.set()
            assert release.wait(3)

    local = SimpleNamespace(principal="alice", retired=False, stopped=False, coordinator=None,
        ports=SimpleNamespace(stop_local=lambda: (("fence", cleanup),), retire_cancelled=retire))
    app._local["run-1"] = local
    app.store.get_run = lambda r: SimpleNamespace(state="cancelled")
    app.store.acknowledge_scene_cleanup = lambda *args: None
    module.start_owner_control(app, "alice", "run-1")
    thread = Thread(target=lambda: results.append(module.finish_cancelled(app, "alice", "run-1", local)))
    try:
        thread.start()
        assert entered.wait(2)
        assert module.finish_cancelled(app, "alice", "run-1", local) is False
        assert retired == [1]
    finally:
        release.set()
        thread.join(3)
        module.close_controls(app)
    assert not thread.is_alive() and results == [True]
    assert local.retired


def test_latch_survives_retired_generation_and_blocks_phase_handoff(tmp_path):
    from threading import Event, Thread

    module = helper()
    app = application(tmp_path / "private")
    phase_ready, stopped = Event(), Event()
    started = []
    app._local["run-1"] = SimpleNamespace(principal="alice", retired=True, stopped=False)
    module.start_owner_control(app, "alice", "run-1")

    def handoff():
        phase_ready.set()
        assert stopped.wait(2)
        with app._lock:
            if not module.stop_requested(app, "run-1"):
                started.append("scene-factory")

    thread = Thread(target=handoff)
    try:
        thread.start()
        assert phase_ready.wait(2)
        assert module.stop_local(app, "alice", "run-1")["delivery"] == "delivered"
        # A newly allocated phase flag is not the run-level authority.
        app._local["run-1"] = SimpleNamespace(principal="alice", retired=False, stopped=False,
            coordinator=None, ports=SimpleNamespace(stop_local=lambda: ()))
        stopped.set()
        thread.join(3)
        assert not started and module.stop_requested(app, "run-1")
        assert module.stop_local(app, "alice", "run-1")["delivery"] == "delivered"
        assert app._local["run-1"].stopped
    finally:
        stopped.set()
        thread.join(3)
        module.close_controls(app)


def test_unreachable_owner_is_not_cleanup_or_durable_ack(tmp_path):
    app = application(tmp_path / "private")
    app.status = lambda *args: dict(state="cancel_requested", disposition="retained", available_actions=[])
    result = helper().cancel_workflow(app, "alice", "run-1")
    assert result["local_stop"]["delivery"] == "no_owner"
    assert result["durable_cancellation"] == "unconfirmed"
    assert not helper().stop_requested(app, "run-1")


def test_retirement_fault_keeps_local_capability_for_retry(tmp_path):
    module = helper()
    app = application(tmp_path / "private")
    capability = object()
    attempts = []

    def retire():
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("lost DB retirement ACK")

    local = SimpleNamespace(principal="alice", retired=False, stopped=False, coordinator=None,
        ports=SimpleNamespace(stop_local=lambda: (("fence", capability),), retire_cancelled=retire))
    app._local["run-1"] = local
    app.store.get_run = lambda r: SimpleNamespace(state="cancelled")
    seen = []
    app.store.acknowledge_scene_cleanup = lambda f, c: seen.append(c)
    module.start_owner_control(app, "alice", "run-1")
    try:
        assert not module.finish_cancelled(app, "alice", "run-1", local)
        assert not local.retired and local.cancel_cleanups[0][1] is capability
        assert module.finish_cancelled(app, "alice", "run-1", local)
        assert local.retired and seen == [capability, capability]
    finally:
        module.close_controls(app)
