# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Regression coverage for independently bound workflow grants."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app
from isaaclab_arena_examples.tests.test_workbench_editor import ORIGIN, login
from isaaclab_arena_examples.tests.test_workbench_workflow_authorization import BODY
from isaaclab_arena_examples.tests.test_workbench_workflow_authorization import configs as workflow_configs

configs = workflow_configs


@pytest.mark.parametrize(
    "change",
    [
        "copied_job",
        "prompt",
        "base_yaml",
        "input_hash",
        "request_sha256",
        "execution_catalogue_sha256",
        "released",
        "missing_attempt",
    ],
)
def test_grants_reject_unbound_request_or_released_attempt(tmp_path, configs, change):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        forged = deepcopy(job)
        if change == "copied_job":
            forged = app.state.journal.submit(
                job["created_by_session_id"], "default", "generate", "copied", job["inputs"]
            )
        elif change in ("released", "missing_attempt"):
            app.state.journal.resume_queue()
            attempt = app.state.journal.claim_attempt(job["id"])
            if change == "released":
                assert app.state.journal.release_attempt(job["id"], **attempt)
        else:
            forged["inputs"][change] = "modified"
        with pytest.raises(ValueError, match="unavailable"):
            app.state.workflow_authorization.resolve(forged)


def test_server_catalogue_digest_frozen_through_replay_and_renewal(tmp_path, configs, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import catalogues
    from isaaclab_arena_examples.tests.test_workbench_reauthorization import block

    monkeypatch.setattr(catalogues, "execution_catalogue_sha256", lambda: "a" * 64, raising=False)
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        assert job["inputs"]["execution_catalogue_sha256"] == "a" * 64
        old = block(app, job)
        monkeypatch.setattr(catalogues, "execution_catalogue_sha256", lambda: "b" * 64)
        response = client.post(
            f'/api/editor/generations/{job["id"]}/reauthorize', headers=headers, json={"idempotency_key": "renew"}
        )
        assert response.status_code == 202
        assert response.json()["inputs"] == job["inputs"]
        current = app.state.journal.claim_attempt(job["id"])
        assert app.state.workflow_authorization.resolve(response.json(), attempt=current)
        with pytest.raises(ValueError):
            app.state.workflow_authorization.resolve(response.json(), attempt=old)
        override = client.post(
            "/api/editor/generate", headers=headers, json={**BODY, "execution_catalogue_sha256": "c" * 64}
        )
        assert override.status_code == 422
