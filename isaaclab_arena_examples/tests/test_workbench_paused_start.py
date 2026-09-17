# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Exercise CLI paused startup through the real app, journal and dispatch loop."""

import asyncio
import os
import sys
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena_examples.agentic_environment_generation.web_api import __main__ as entry
from isaaclab_arena_examples.agentic_environment_generation.web_api import editor_execution, generation
from isaaclab_arena_examples.agentic_environment_generation.web_api.supervisor import Supervisor


@pytest.mark.parametrize("paused", [True, False])
@pytest.mark.parametrize("kind", ["diagnostic", "generate", "snapshots", "build", "evaluate"])
def test_cli_paused_start_preserves_queued_work_and_unpaused_control_dispatches(tmp_path, monkeypatch, paused, kind):
    """Mock only socket serving and the worker effect, not startup or queue decisions."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    ipc = tmp_path / "ipc"
    ipc.mkdir()
    os.chmod(ipc, 0o750)
    journal = Journal(state / "journal.sqlite3")
    inputs = {"steps": 1, "delay_seconds": 0.0} if kind == "diagnostic" else {"operation": "new"}
    job = journal.submit("synthetic-owner", "default", kind, "queued-before-start", inputs)
    initial = journal.snapshot()
    assert journal.db.execute("SELECT value FROM metadata WHERE key='clean_shutdown'").fetchone()[0] == 1
    assert journal.db.execute("SELECT value FROM metadata WHERE key='queue_paused'").fetchone()[0] == 0
    journal.close()
    dispatched = []
    observed = []
    monkeypatch.setattr(editor_execution, "make_snapshot_service", lambda _: None)
    monkeypatch.setattr(generation, "configuration", lambda: None)

    def complete(journal, selected):
        dispatched.append(selected["id"])
        journal.transition(selected["id"], "running", "started", "started")
        journal.transition(selected["id"], "succeeded", "completed", "succeeded", result={"synthetic": True})

    async def synthetic_worker(self, selected):
        complete(self.journal, selected)

    async def synthetic_editor_worker(self, supervisor, selected):
        complete(supervisor.journal, selected)

    monkeypatch.setattr(Supervisor, "execute", synthetic_worker)
    monkeypatch.setattr(editor_execution.EditorExecution, "execute", synthetic_editor_worker)
    monkeypatch.setattr(editor_execution.EditorExecution, "execute_managed", synthetic_editor_worker)

    @contextmanager
    def no_socket(_path):
        yield None

    monkeypatch.setattr(entry, "UnixListener", no_socket)

    class InProcessServer:
        def __init__(self, config):
            self.config = config
            self.started = False

        def run(self, sockets):
            assert sockets == [None]
            app = self.config.app
            with TestClient(app, base_url="http://127.0.0.1:3010") as client:
                assert app.state.start_paused is paused
                assert app.state.supervisor.paused is paused

                async def dispatch_turns():
                    for _ in range(4):
                        app.state.supervisor.wake.set()
                        await asyncio.sleep(0)

                client.portal.call(dispatch_turns)
                observed.append(app.state.journal.snapshot())
                assert client.get("/api/health").status_code == 200
            self.started = True

    monkeypatch.setattr(entry, "OwnedServer", InProcessServer)
    argv = [
        "arena-api",
        "--state-dir",
        str(state),
        "--socket",
        str(ipc / "api.sock"),
        "--origin",
        "http://127.0.0.1:3010",
    ]
    if kind == "diagnostic":
        argv.append("--diagnostics")
    if paused:
        argv.append("--start-paused")
    monkeypatch.setattr(sys, "argv", argv)
    entry.main()
    assert len(observed) == 1
    if paused:
        assert dispatched == []
        assert observed[0] == initial
    else:
        assert dispatched == [job["id"]]
        assert observed[0]["jobs"][0]["status"] == "succeeded"
    reopened = Journal(state / "journal.sqlite3")
    try:
        assert reopened.get_job(job["id"])["status"] == ("queued" if paused else "succeeded")
    finally:
        reopened.close()
