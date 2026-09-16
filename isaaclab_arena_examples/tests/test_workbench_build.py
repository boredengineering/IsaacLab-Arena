# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Build API and simulated harness units; these tests do not run Isaac Sim."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, editor_execution

ORIGIN = "http://127.0.0.1:3000"
FIXTURE = Path(__file__).resolve().parents[2] / "isaaclab_arena/tests/test_data/minimal_maple_table_env_graph.yaml"
FIXED = {"headless": True, "num_envs": 1, "num_steps": 20, "policy": "zero_action"}


@pytest.fixture(autouse=True)
def no_renderer(monkeypatch):
    def unavailable(_state_dir):
        raise RuntimeError("Build unit profile has no renderer")

    monkeypatch.setattr(editor_execution, "make_snapshot_service", unavailable)


def login(client):
    session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
    return {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}


def test_build_freezes_validated_draft_and_replays_before_dead_view(tmp_path, monkeypatch):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        doc = client.get("/api/editor/documents/" + client.get("/api/editor").json()["default_document_id"]).json()
        body = {"yaml_text": doc["yaml_text"], "document_id": doc["document_id"], "idempotency_key": "build-first"}
        response = client.post("/api/editor/build", headers=headers, json=body)
        assert response.status_code == 202, response.text
        job = response.json()
        assert job["kind"] == "build" and job["status"] == "queued"
        assert {key: job["inputs"][key] for key in FIXED} == FIXED
        assert job["inputs"]["input_hash"] == doc["validation"]["source_hash"]
        assert job["inputs"]["canonical_hash"] == doc["validation"]["canonical_hash"]
        assert job["inputs"]["document_id"] == doc["document_id"]
        assert "external_yaml:" not in job["inputs"]["yaml_text"]
        monkeypatch.setattr(
            app.state.documents, "validate", lambda *args: (_ for _ in ()).throw(AssertionError("replay resolved view"))
        )
        assert client.post("/api/editor/build", headers=headers, json=body).json() == job
        assert (
            client.post("/api/editor/build", headers=headers, json={**body, "yaml_text": "changed"}).status_code == 409
        )
        assert client.get("/api/editor").json()["capabilities"]["build"] is True
        assert client.get("/api/health").json()["capabilities"]["build"] is True
        assert client.get("/api/jobs/" + job["id"]).json() == job
        cancelled = client.post("/api/jobs/" + job["id"] + "/cancel", headers=headers).json()
        assert cancelled["status"] == "cancelled"
        assert client.get("/api/jobs/" + job["id"]).json()["status"] == "cancelled"


@pytest.mark.parametrize(
    "shutdown",
    ["return", "exit_zero", "exit_nonzero", "preflight_error", "enter_error", "rollout_error", "shutdown_error"],
)
def test_worker_receipts_after_rollout_before_simulated_shutdown(tmp_path, monkeypatch, capsys, shutdown):
    """Real runner build branch with a simulated rollout/context; no Isaac Sim execution."""
    import contextlib
    import io
    import json
    import sys
    from types import SimpleNamespace

    import yaml

    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    from isaaclab_arena_examples.agentic_environment_generation import environment_generation_runner as runner
    from isaaclab_arena_examples.agentic_environment_generation.web_api import build_worker, snapshot_process

    events = []
    channel = io.StringIO()

    def fail():
        raise RuntimeError("private simulated lifecycle failure")

    @contextlib.contextmanager
    def private_channel():
        yield channel

    class SimulatedContext:
        def __init__(self, args):
            assert args.mode == "build" and args.headless is True
            assert args.num_envs == 1 and args.num_steps == 20
            assert args.policy_config is None and args.policy_ref is None
            assert not args.record_camera_video and not args.record_viewport_video

        def __enter__(self):
            if shutdown == "enter_error":
                fail()
            events.append("context_entered")

        def __exit__(self, *args):
            frames = [json.loads(line) for line in channel.getvalue().splitlines()]
            events.append(("receipts_before_shutdown", sum("result" in frame for frame in frames)))
            events.append("context_exited")
            if shutdown == "exit_zero":
                raise SystemExit(0)
            if shutdown == "exit_nonzero":
                raise SystemExit(1)
            if shutdown == "shutdown_error":
                fail()

    text = FIXTURE.read_text()
    validation = Documents(tmp_path).validate(text)
    inputs = {
        **FIXED,
        "yaml_text": yaml.safe_dump(validation["spec"], sort_keys=False),
        "input_hash": validation["source_hash"],
        "canonical_hash": validation["canonical_hash"],
        "document_id": None,
        "request_sha256": "e" * 64,
    }

    def simulated_build(path, args):
        assert path.read_text() == inputs["yaml_text"]
        assert events == ["context_entered"]
        assert channel.getvalue() == json.dumps({"stage": "building_environment"}) + "\n"
        if shutdown == "rollout_error":
            fail()
        events.append("harness_returned")

    monkeypatch.setattr(runner, "SimulationAppContext", SimulatedContext)
    monkeypatch.setattr(runner, "build_env_and_run_policy", simulated_build)
    monkeypatch.setattr(runner, "resolve_env_spec", lambda *args: pytest.fail("generation invoked"))
    if shutdown == "preflight_error":
        monkeypatch.setattr(runner, "check_transfer_readiness", lambda *args: fail())
    monkeypatch.setattr(build_worker, "private_channel", private_channel)
    monkeypatch.setattr(snapshot_process, "watch_parent", lambda fd: None)
    argv = ["build_worker", "--owner-fd", "123"]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(
        sys, "stdin", SimpleNamespace(buffer=io.BytesIO((json.dumps({"inputs": inputs}) + "\n").encode()))
    )
    if shutdown in {"exit_zero", "exit_nonzero"}:
        with pytest.raises(SystemExit) as exited:
            build_worker.main()
        assert exited.value.code == (0 if shutdown == "exit_zero" else 1)
    else:
        assert build_worker.main() == (1 if shutdown.endswith("error") else 0)
    assert sys.argv is argv
    frames = [json.loads(line) for line in channel.getvalue().splitlines()]
    receipt = {
        "schema_version": 1,
        "input_hash": inputs["input_hash"],
        "canonical_hash": inputs["canonical_hash"],
        **FIXED,
        "completed": True,
    }
    completed = shutdown not in {"preflight_error", "enter_error", "rollout_error"}
    expected: list[dict] = [{"stage": "building_environment"}]
    if completed:
        expected.append({"result": receipt})
    if shutdown.endswith("error"):
        expected.append({"error": "Build failed; check private runtime logs"})
        logs = capsys.readouterr().err
        assert "Traceback (most recent call last)" in logs
        assert "private simulated lifecycle failure" in logs
        assert "private simulated lifecycle failure" not in channel.getvalue()
    assert frames == expected
    if shutdown in {"preflight_error", "enter_error"}:
        assert events == []
    else:
        assert events == [
            "context_entered",
            *(["harness_returned"] if completed else []),
            ("receipts_before_shutdown", int(completed)),
            "context_exited",
        ]


def test_runner_build_without_hook_keeps_cli_lifecycle(tmp_path, monkeypatch):
    """Run the ordinary CLI entry through simulated context and rollout seams."""
    import sys

    from isaaclab_arena_examples.agentic_environment_generation import environment_generation_runner as runner

    events = []
    path = tmp_path / "environment.yaml"
    path.write_text(FIXTURE.read_text())

    class SimulatedContext:
        def __init__(self, args):
            assert args.mode == "build"

        def __enter__(self):
            events.append("entered")

        def __exit__(self, *args):
            events.append("exited")

    monkeypatch.setattr(sys, "argv", ["runner", "--mode", "build", "--env_graph_spec_yaml", str(path)])
    monkeypatch.setattr(runner, "SimulationAppContext", SimulatedContext)
    monkeypatch.setattr(runner, "build_env_and_run_policy", lambda *args: events.append("rollout_returned"))
    assert runner.main() == 0
    assert events == ["entered", "rollout_returned", "exited"]


def wait_job(client, job_id, statuses):
    import time

    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        current = client.get("/api/jobs/" + job_id).json()
        if current["status"] in statuses:
            return current
        time.sleep(0.01)
    return pytest.fail(f"Build did not reach {statuses}: {current}")


def simulated_worker(
    monkeypatch,
    app,
    tmp_path,
    *,
    receipt_change=None,
    cleanup_error=False,
    wait_for_signal=False,
    during_cleanup=None,
    receipt_count=1,
    exit_code=0,
):
    """A fake OS peer, not a simulator or process-cleanup proof."""
    import asyncio
    import fcntl
    import json
    from types import SimpleNamespace

    from isaaclab_arena_examples.agentic_environment_generation.web_api import snapshot_process, supervisor

    lease = tmp_path / "shared-gpu.lock"
    monkeypatch.setattr(snapshot_process, "GPU_LEASE", lease)
    events = []
    import threading

    signalled = threading.Event()

    class IdleSnapshots:
        def close(self):
            events.append("snapshot_reaped")

    app.state.editor_execution.snapshots = IdleSnapshots()

    class Group:
        cleaned = False

        def __init__(self, pid):
            assert pid == 987654

        def stop(self):
            events.append("group_cleanup")
            current = app.state.journal.get_job(app.state.supervisor.job_id)
            assert current["status"] in {"running", "cancel_requested"}
            with lease.open("rb") as other:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if cleanup_error:
                raise RuntimeError("private cleanup details")
            if during_cleanup:
                during_cleanup()
            self.cleaned = True

        def send_signal(self, sig):
            events.append("signal")
            signalled.set()

    monkeypatch.setattr(supervisor, "OwnedProcessGroup", Group)

    async def spawn(*argv, **kwargs):
        assert events == ["snapshot_reaped"]
        assert argv[1:4] == ("-u", "-m", "isaaclab_arena_examples.agentic_environment_generation.web_api.build_worker")
        assert kwargs["start_new_session"] is True
        assert "OPENAI_API_KEY" not in kwargs["env"] and "NEO4J_PASSWORD" not in kwargs["env"]
        assert kwargs["pass_fds"]
        events.append("spawn")
        pending = []

        class Input:
            def write(self, data):
                inputs = json.loads(data)["inputs"]
                result = {
                    "schema_version": 1,
                    **FIXED,
                    "completed": True,
                    "input_hash": inputs["input_hash"],
                    "canonical_hash": inputs["canonical_hash"],
                }
                if receipt_change:
                    result.update(receipt_change)
                pending.extend([(json.dumps({"result": result}) + "\n").encode()] * receipt_count + [b""])

            async def drain(self):
                pass

            def close(self):
                pass

        class Output:
            async def readline(self):
                while wait_for_signal and not signalled.is_set():
                    await asyncio.sleep(0.01)
                return pending.pop(0)

        async def wait():
            process.returncode = exit_code
            events.append("reaped")
            return exit_code

        process = SimpleNamespace(pid=987654, returncode=None, stdin=Input(), stdout=Output(), wait=wait)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return events, lease


def test_route_dispatches_build_and_commits_only_after_group_cleanup(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, lease = simulated_worker(monkeypatch, app, tmp_path)
        # Identity fixture only: no subprocess is started by this unit profile.
        monkeypatch.setattr(editor_execution, "process_identity", lambda pid: "123")
        headers = login(client)
        body = {"yaml_text": FIXTURE.read_text(), "idempotency_key": "execute-build"}
        response = client.post("/api/editor/build", json=body, headers=headers)
        assert response.status_code == 202, response.text
        job = response.json()
        current = wait_job(client, job["id"], {"succeeded", "failed"})
        assert current["status"] == "succeeded", current
        assert current["result"] == {
            "schema_version": 1,
            **FIXED,
            "completed": True,
            "input_hash": job["inputs"]["input_hash"],
            "canonical_hash": job["inputs"]["canonical_hash"],
        }
        assert events.index("snapshot_reaped") < events.index("spawn") < events.index("group_cleanup")
        import fcntl

        with lease.open("rb") as other:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert app.state.supervisor.process is None
        assert client.post("/api/editor/build", json=body, headers=headers).json()["id"] == job["id"]
        assert events.count("spawn") == 1


@pytest.mark.parametrize("receipt_count,exit_code", [(0, 0), (2, 0), (1, 1)])
def test_parent_rejects_missing_duplicate_or_nonzero_completion(tmp_path, monkeypatch, receipt_count, exit_code):
    """Synthetic OS peer checks parent admission, not physical simulator cleanup."""
    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_worker(monkeypatch, app, tmp_path, receipt_count=receipt_count, exit_code=exit_code)
        monkeypatch.setattr(editor_execution, "process_identity", lambda pid: "123")
        headers = login(client)
        job = client.post(
            "/api/editor/build",
            json={"yaml_text": FIXTURE.read_text(), "idempotency_key": "exit-and-receipt"},
            headers=headers,
        ).json()
        current = wait_job(client, job["id"], {"succeeded", "failed"})
        assert current["status"] == "failed" and current["result"] is None
        assert "group_cleanup" in events
        assert app.state.journal.pending_workers() == []


@pytest.mark.parametrize(
    "change",
    [
        {"canonical_hash": "0" * 64},
        {"input_hash": "invalid"},
        {"num_steps": 21},
        {"headless": 1},
        {"num_envs": True},
        {"policy": "remote"},
        {"shell": "not-allowed"},
    ],
)
def test_worker_rejects_corrupt_frozen_inputs_before_runner(tmp_path, monkeypatch, change):
    import yaml

    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    from isaaclab_arena_examples.agentic_environment_generation import environment_generation_runner as runner
    from isaaclab_arena_examples.agentic_environment_generation.web_api import build_worker

    validation = Documents(tmp_path).validate(FIXTURE.read_text())
    inputs = {
        **FIXED,
        "yaml_text": yaml.safe_dump(validation["spec"], sort_keys=False),
        "input_hash": validation["source_hash"],
        "canonical_hash": validation["canonical_hash"],
        "document_id": None,
        "request_sha256": "e" * 64,
        **change,
    }
    called = []
    monkeypatch.setattr(runner, "main", lambda: called.append(True) or 0)
    with pytest.raises(ValueError):
        build_worker.run_build(inputs, on_completed=lambda result: pytest.fail("invalid inputs completed"))
    assert called == []


@pytest.mark.parametrize("failure", [False, True])
def test_worker_main_frames_completion_or_static_failure(monkeypatch, failure):
    import contextlib
    import io
    import json
    import sys
    from types import SimpleNamespace

    from isaaclab_arena_examples.agentic_environment_generation.web_api import build_worker, snapshot_process

    assert hasattr(build_worker, "main"), "worker entry point is missing"
    channel = io.StringIO()

    @contextlib.contextmanager
    def private_channel():
        yield channel

    events = []
    monkeypatch.setattr(build_worker, "private_channel", private_channel)
    monkeypatch.setattr(snapshot_process, "watch_parent", lambda fd: events.append("owner_watch"))
    monkeypatch.setattr(sys, "argv", ["build_worker", "--owner-fd", "123"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b'{"inputs": {}}\n')))
    receipt = {"schema_version": 1, **FIXED, "completed": True, "input_hash": "a" * 64, "canonical_hash": "b" * 64}

    def simulated_build(inputs, *, on_completed):
        assert events == ["owner_watch"]
        if failure:
            raise RuntimeError("private simulator log and paths")
        events.append("harness_returned")
        on_completed(receipt)
        events.append("context_exited")

    monkeypatch.setattr(build_worker, "run_build", simulated_build)
    assert build_worker.main() == (1 if failure else 0)
    frames = [json.loads(line) for line in channel.getvalue().splitlines()]
    assert frames[0] == {"stage": "building_environment"}
    if failure:
        assert frames[1] == {"error": "Build failed; check private runtime logs"}
        assert "private simulator log and paths" not in channel.getvalue()
    else:
        assert frames[1] == {"result": receipt}
        assert events[-1] == "context_exited"


@pytest.mark.parametrize(
    "change",
    [
        {"canonical_hash": "f" * 64},
        {"input_hash": "f" * 64},
        {"num_steps": 19},
        {"completed": False},
        {"completed": 1},
        {"num_envs": True},
        {"extra": "private logs"},
    ],
)
def test_mismatched_worker_receipts_fail_with_static_error(tmp_path, monkeypatch, change):
    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_worker(monkeypatch, app, tmp_path, receipt_change=change)
        monkeypatch.setattr(editor_execution, "process_identity", lambda pid: "123")
        headers = login(client)
        job = client.post(
            "/api/editor/build",
            json={"yaml_text": FIXTURE.read_text(), "idempotency_key": "bad-receipt"},
            headers=headers,
        ).json()
        current = wait_job(client, job["id"], {"succeeded", "failed"})
        assert current["status"] == "failed" and current["result"] is None
        assert (
            current["error"]
            == "Build failed or exceeded its budget; check Isaac Sim assets, GPU availability and private runtime logs"
        )
        assert "group_cleanup" in events
        assert app.state.journal.pending_workers() == []


def test_running_build_cancellation_uses_existing_job_and_group(tmp_path, monkeypatch):
    import time

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_worker(monkeypatch, app, tmp_path, wait_for_signal=True)
        monkeypatch.setattr(editor_execution, "process_identity", lambda pid: "123")
        headers = login(client)
        job = client.post(
            "/api/editor/build",
            json={"yaml_text": FIXTURE.read_text(), "idempotency_key": "cancel-running"},
            headers=headers,
        ).json()
        deadline = time.monotonic() + 4
        while "spawn" not in events and time.monotonic() < deadline:
            time.sleep(0.01)
        assert "spawn" in events
        response = client.post("/api/jobs/" + job["id"] + "/cancel", headers=headers)
        assert response.status_code == 200
        current = wait_job(client, job["id"], {"cancelled"})
        assert current["result"] is None and "signal" in events and "group_cleanup" in events
        assert app.state.journal.pending_workers() == []


def test_unknown_cleanup_retains_ownership_even_after_queue_resume(tmp_path, monkeypatch):
    import os
    import time

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_worker(monkeypatch, app, tmp_path, cleanup_error=True)
        monkeypatch.setattr(editor_execution, "process_identity", lambda pid: "123")
        headers = login(client)
        body = {"yaml_text": FIXTURE.read_text(), "idempotency_key": "unknown-cleanup"}
        job = client.post("/api/editor/build", json=body, headers=headers).json()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            current = client.get("/api/jobs/" + job["id"]).json()
            if current["stage"] == "cleanup_pending":
                break
            time.sleep(0.01)
        try:
            assert current["status"] == "running" and current["result"] is None
            assert current["stage"] == "cleanup_pending"
            assert app.state.journal.pending_workers()[0]["job_id"] == job["id"]
            process = app.state.supervisor.process
            assert process is not None and app.state.editor_execution.build_lease_fd is not None
            second = client.post(
                "/api/editor/build", json={**body, "idempotency_key": "later-build"}, headers=headers
            ).json()
            client.post("/api/jobs/resume-queue", headers=headers)
            time.sleep(0.3)
            assert client.get("/api/jobs/" + second["id"]).json()["status"] == "queued"
            assert app.state.supervisor.process is process
            assert events.count("spawn") == 1
        finally:
            # Dispose synthetic fixture identities only; this is not production recovery.
            app.state.supervisor.paused = True
            app.state.supervisor._process_group.cleaned = True
            app.state.supervisor.process.returncode = 0
            for name in ("build_owner_fd", "build_lease_fd"):
                fd = getattr(app.state.editor_execution, name, None)
                if fd is not None:
                    os.close(fd)
                    setattr(app.state.editor_execution, name, None)


def test_build_http_rejects_overrides_invalid_yaml_and_unprotected_requests(tmp_path):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        body = {"yaml_text": FIXTURE.read_text(), "idempotency_key": "strict-build"}
        assert client.post("/api/editor/build", json=body, headers={"Origin": ORIGIN}).status_code == 401
        headers = login(client)
        assert client.post("/api/editor/build", json=body, headers={"Origin": ORIGIN}).status_code == 403
        for change in (
            {"headless": False},
            {"num_envs": 2},
            {"num_steps": 2},
            {"policy": "remote"},
            {"command": "anything"},
            {"yaml_text": True},
            {"yaml_text": "x: invalid"},
            {"yaml_text": "#" + "é" * (128 * 1024)},
            {"document_id": "not-a-view"},
            {"idempotency_key": ""},
        ):
            assert client.post("/api/editor/build", json={**body, **change}, headers=headers).status_code == 422
        assert client.get("/api/jobs").json()["jobs"] == []
        accepted = client.post("/api/editor/build", json=body, headers=headers)
        assert accepted.status_code == 202 and accepted.json()["inputs"]["document_id"] is None


def test_private_worker_channel_separates_native_and_python_logs(capfd):
    import os

    from isaaclab_arena_examples.agentic_environment_generation.web_api import build_worker

    capfd.readouterr()
    with build_worker.private_channel() as channel:
        os.write(1, b"native-private-log\n")
        print("python-private-log", flush=True)
        channel.write("protocol-only\n")
        channel.flush()
    captured = capfd.readouterr()
    assert captured.out == "protocol-only\n"
    assert "native-private-log" in captured.err and "python-private-log" in captured.err


@pytest.mark.parametrize("action", ["cancel", "timeout"])
def test_busy_shared_gpu_lease_never_spawns_build(tmp_path, monkeypatch, action):
    import fcntl
    import time

    from isaaclab_arena_examples.agentic_environment_generation.web_api import build_execution

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, lease = simulated_worker(monkeypatch, app, tmp_path)
        monkeypatch.setattr(build_execution, "BUILD_TIMEOUT", 0.2 if action == "timeout" else 3)
        headers = login(client)
        with lease.open("wb") as other:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            job = client.post(
                "/api/editor/build",
                json={"yaml_text": FIXTURE.read_text(), "idempotency_key": "lease-busy"},
                headers=headers,
            ).json()
            if action == "cancel":
                deadline = time.monotonic() + 2
                while "snapshot_reaped" not in events and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert "snapshot_reaped" in events
                client.post("/api/jobs/" + job["id"] + "/cancel", headers=headers)
            current = wait_job(client, job["id"], {"failed", "cancelled"})
            assert current["status"] == ("failed" if action == "timeout" else "cancelled")
            assert current["result"] is None and "spawn" not in events
            assert app.state.editor_execution.build_lease_fd is None


def test_snapshot_cleanup_failure_never_launches_or_discards_owner(tmp_path, monkeypatch):
    import time

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_worker(monkeypatch, app, tmp_path)
        snapshot = app.state.editor_execution.snapshots

        def fail_close():
            raise RuntimeError("private snapshot cleanup details")

        monkeypatch.setattr(snapshot, "close", fail_close)
        headers = login(client)
        job = client.post(
            "/api/editor/build",
            json={"yaml_text": FIXTURE.read_text(), "idempotency_key": "snapshot-unreaped"},
            headers=headers,
        ).json()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = client.get("/api/jobs/" + job["id"]).json()
            if current["stage"] == "cleanup_pending":
                break
            time.sleep(0.01)
        try:
            assert current["status"] == "running" and current["stage"] == "cleanup_pending"
            assert current["result"] is None and current["error"] is None
            assert app.state.editor_execution.snapshots is snapshot
            assert "spawn" not in events
        finally:
            monkeypatch.setattr(snapshot, "close", lambda: None)


def test_completion_rechecks_public_guard_after_awaited_cleanup(tmp_path, monkeypatch):
    import time

    from fastapi import HTTPException

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:

        def new_policy():
            def protect(value):
                if type(value) is dict and value.get("completed") is True:
                    raise HTTPException(422, "Protected receipt")

            monkeypatch.setattr(app.state.model_settings, "protect_public", protect)

        simulated_worker(monkeypatch, app, tmp_path, during_cleanup=new_policy)
        monkeypatch.setattr(editor_execution, "process_identity", lambda pid: "123")
        headers = login(client)
        job = client.post(
            "/api/editor/build",
            json={"yaml_text": FIXTURE.read_text(), "idempotency_key": "guard-at-commit"},
            headers=headers,
        ).json()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = app.state.journal.get_job(job["id"])
            if current["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        assert current["status"] == "failed" and current["result"] is None
        assert app.state.journal.pending_workers() == []


def test_log_setup_failure_does_not_leak_owner_pipe(tmp_path, monkeypatch):
    import os
    from contextlib import suppress

    app = create_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        events, _ = simulated_worker(monkeypatch, app, tmp_path)
        (tmp_path / "build-logs").write_text("unavailable")
        descriptors = []
        real_pipe = os.pipe

        def capture_pipe():
            pair = real_pipe()
            descriptors.extend(pair)
            return pair

        monkeypatch.setattr(os, "pipe", capture_pipe)
        headers = login(client)
        job = client.post(
            "/api/editor/build",
            json={"yaml_text": FIXTURE.read_text(), "idempotency_key": "log-failure"},
            headers=headers,
        ).json()
        current = wait_job(client, job["id"], {"failed"})
        assert current["result"] is None and "spawn" not in events
        try:
            for descriptor in descriptors:
                with pytest.raises(OSError):
                    os.fstat(descriptor)
        finally:
            for descriptor in descriptors:
                with suppress(OSError):
                    os.close(descriptor)
