# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Real managed subprocess/pipe/cleanup with a synthetic worker, never a model or database."""

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app
from isaaclab_arena_examples.agentic_environment_generation.web_api import editor_execution as execution
from isaaclab_arena_examples.agentic_environment_generation.web_api import generation, graph_access
from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import execution_catalogue_sha256
from isaaclab_arena_examples.tests.test_workbench_editor import FIXTURE, ORIGIN, login


@pytest.mark.parametrize("leak_after_revoke", [False, True])
def test_real_managed_process_receipt_and_revoked_secret_guard(tmp_path, monkeypatch, leak_after_revoke):
    model_key = "synthetic-managed-process-model-secret"
    graph_key = "synthetic-managed-process-graph-secret"
    config = {
        "provider": "openai",
        "model": "synthetic-only",
        "base_url": "http://127.0.0.1:1/v1",
        "api_key": model_key,
        "trusted_server": True,
    }
    graph = {"uri": "bolt://127.0.0.1:1", "user": "fixture-user", "password": graph_key, "database": "fixture"}
    monkeypatch.setattr(generation, "configuration", lambda: dict(config))
    monkeypatch.setattr(graph_access, "configuration", lambda: dict(graph) if leak_after_revoke else None)
    receipt = {
        "yaml_text": FIXTURE.read_text() + ("\n# " + graph_key if leak_after_revoke else ""),
        "validation": {},
        "traces": [],
        "publication": "not_published",
        "warnings": [],
        "operation": "new",
        "prior_snapshot": empty_snapshot(""),
        "catalogue_sha256": execution_catalogue_sha256(),
    }
    ready, release = tmp_path / "worker-ready", tmp_path / "release-worker"
    script = tmp_path / "synthetic_worker.py"
    script.write_text(
        "import json,sys,time\nfrom pathlib import Path\n"
        "envelope=json.loads(sys.stdin.readline())\n"
        "assert set(envelope)=={'inputs','config','graph_config'}\n"
        f"Path({str(ready)!r}).touch()\n"
        "deadline=time.monotonic()+10\n"
        f"while not Path({str(release)!r}).exists():\n"
        " if time.monotonic()>deadline: raise SystemExit(2)\n time.sleep(.01)\n"
        f"print({json.dumps({'result': receipt})!r},flush=True)\n"
    )
    original_spawn = execution.asyncio.create_subprocess_exec
    children = []
    received = []
    diagnostics = []
    original_validate = execution.EditorExecution.validate_managed_receipt

    def observe_validation(self, job, result):
        try:
            value = original_validate(self, job, result)
            diagnostics.append("validated")
            return value
        except Exception as exc:
            diagnostics.append((type(exc).__name__, str(exc)))
            raise

    monkeypatch.setattr(execution.EditorExecution, "validate_managed_receipt", observe_validation)

    async def synthetic_spawn(*args, **kwargs):
        assert args[1:4] == (
            "-u",
            "-m",
            "isaaclab_arena_examples.agentic_environment_generation.web_api.generation_worker",
        )
        child = await original_spawn(args[0], "-u", str(script), **kwargs)
        original_read = child.stdout.readline

        async def observe_read():
            line = await original_read()
            if line:
                received.append(json.loads(line))
            return line

        child.stdout.readline = observe_read
        children.append(child)
        return child

    monkeypatch.setattr(execution.asyncio, "create_subprocess_exec", synthetic_spawn)
    state = tmp_path / "state"
    with TestClient(create_app(state), base_url=ORIGIN) as peer:
        headers = login(peer)
        response = peer.post(
            "/api/editor/generate",
            headers=headers,
            json={
                "operation": "new",
                "prompt": "Synthetic transport only",
                "idempotency_key": "real-process",
            },
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), peer.get(f"/api/jobs/{job_id}").text
        if leak_after_revoke:
            peer.app.state.workflow_authorization.clear()
        release.touch()
        expected = "indeterminate" if leak_after_revoke else "succeeded"
        while time.monotonic() < deadline:
            job = peer.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {expected, "failed", "indeterminate"} and not peer.app.state.journal.pending_workers():
                break
            time.sleep(0.02)
        assert job["status"] == expected, (job["status"], diagnostics, children[0].returncode)
        assert model_key not in json.dumps(job) and graph_key not in json.dumps(job)
        assert received == [{"result": receipt}]
        assert len(children) == 1 and children[0].returncode is not None
        with pytest.raises(ProcessLookupError):
            os.kill(children[0].pid, 0)
        attempt = peer.app.state.journal.get_attempt(job_id)
        candidate = peer.app.state.journal.get_candidate_receipt(job_id, attempt["attempt_id"], attempt["generation"])
        assert (candidate is None) == leak_after_revoke
        if candidate is not None:
            assert candidate["validation"]["valid"]
        assert peer.app.state.journal.pending_workers() == []
