# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Renewal through the real coordinator and pipe, with an explicitly synthetic worker."""

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
from isaaclab_arena_examples.tests.test_workbench_reauthorization import block


def test_expired_authorization_renews_exact_job_and_releases_replacement_to_real_pipe(tmp_path, monkeypatch):
    clock = [1000.0]
    config = {
        "provider": "openai",
        "model": "synthetic-renewal-only",
        "base_url": "http://127.0.0.1:1/v1",
        "api_key": "synthetic-original-renewal-marker",
        "trusted_server": True,
    }
    replacement = "synthetic-replacement-renewal-marker"
    monkeypatch.setattr(generation, "configuration", lambda: dict(config))
    monkeypatch.setattr(graph_access, "configuration", lambda: None)
    prompt = "Synthetic renewal transport only"
    receipt = {
        "yaml_text": FIXTURE.read_text(),
        "validation": {},
        "traces": [],
        "publication": "not_published",
        "warnings": [],
        "operation": "new",
        "prior_snapshot": empty_snapshot(prompt),
        "catalogue_sha256": execution_catalogue_sha256(),
    }
    script = tmp_path / "synthetic_renewal_worker.py"
    script.write_text(
        "import json,sys\n"
        "envelope=json.loads(sys.stdin.readline())\n"
        f"assert envelope['config']['api_key']=={replacement!r}\n"
        "assert envelope['graph_config'] is None\n"
        f"print({json.dumps({'result': receipt})!r},flush=True)\n"
    )
    original_spawn = execution.asyncio.create_subprocess_exec
    children, messages = [], []

    async def spawn(*args, **kwargs):
        assert args[1:4] == (
            "-u",
            "-m",
            "isaaclab_arena_examples.agentic_environment_generation.web_api.generation_worker",
        )
        child = await original_spawn(args[0], "-u", str(script), **kwargs)
        original_read = child.stdout.readline

        async def read():
            line = await original_read()
            if line:
                messages.append(json.loads(line))
            return line

        child.stdout.readline = read
        children.append(child)
        return child

    monkeypatch.setattr(execution.asyncio, "create_subprocess_exec", spawn)
    app = create_app(tmp_path / "state", start_paused=True, clock=lambda: clock[0])
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        accepted = client.post(
            "/api/editor/generate",
            headers=headers,
            json={"operation": "new", "prompt": prompt, "idempotency_key": "synthetic-renewal-process"},
        )
        assert accepted.status_code == 202, accepted.text
        original = accepted.json()
        old_attempt = block(app, original)
        clock[0] += 181
        config["api_key"] = replacement
        url = f"/api/editor/generations/{original['id']}/reauthorize"
        renewed = client.post(url, headers=headers, json={"idempotency_key": "explicit-new-authorization"})
        assert renewed.status_code == 202, renewed.text
        assert renewed.json()["inputs"] == original["inputs"]
        assert not children
        assert client.post("/api/jobs/resume-queue", headers=headers).status_code == 200
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{original['id']}").json()
            if job["status"] in {"succeeded", "failed", "indeterminate", "blocked_authorization"}:
                break
            time.sleep(0.02)
        assert job["status"] == "succeeded", job["status"]
        assert job["inputs"] == original["inputs"]
        assert app.state.journal.get_attempt(job["id"])["generation"] == old_attempt["generation"] + 1
        assert messages == [{"result": receipt}]
        assert job["result"]["validation"]["valid"]
        assert not app.state.journal.pending_workers()
        assert len(children) == 1 and children[0].returncode == 0
        with pytest.raises(ProcessLookupError):
            os.kill(children[0].pid, 0)
        assert replacement not in json.dumps(job)
