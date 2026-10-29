# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Cancellation preserves accepted evidence and unknown execution outcomes."""

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app
from isaaclab_arena_examples.tests.test_workbench_editor import ORIGIN, login
from isaaclab_arena_examples.tests.test_workbench_reauthorization import block
from isaaclab_arena_examples.tests.test_workbench_workflow_authorization import BODY
from isaaclab_arena_examples.tests.test_workbench_workflow_authorization import configs as workflow_configs

configs = workflow_configs


@pytest.mark.parametrize("state", ["claimed", "released", "candidate_committed"])
@pytest.mark.parametrize("restart", ["none", "during_cleanup", "after_cleanup"])
def test_cancellation_preserves_execution_evidence_until_and_after_cleanup(tmp_path, state, restart):
    path = tmp_path / "journal.sqlite3"
    journal = Journal(path)
    journal.begin_run()
    job = journal.submit("owner", "default", "generate", "one", {})
    attempt = journal.claim_attempt(job["id"])
    receipt = {"candidate": "accepted"}
    if state != "claimed":
        assert journal.release_attempt(job["id"], **attempt)
    if state == "candidate_committed":
        assert journal.commit_candidate(job["id"], **attempt, receipt=receipt)
    journal.record_worker(job["id"], 123, {"safe": "identity"})
    assert journal.request_cancel_attempt(job["id"], **attempt, expected_state=state)
    assert not journal.cancel_attempt(job["id"], **attempt, expected_state="cancel_requested")
    assert journal.get_job(job["id"])["status"] == "cancel_requested"
    if restart == "during_cleanup":
        journal.close()
        journal = Journal(path)
        journal.begin_run()
        assert journal.get_job(job["id"])["status"] == "cancel_requested"
    journal.worker_cleaned(job["id"])
    if restart == "after_cleanup":
        journal.close()
        journal = Journal(path)
        journal.begin_run()
    if journal.get_job(job["id"])["status"] != "cancelled":
        assert journal.cancel_attempt(job["id"], **attempt, expected_state="cancel_requested")
    result = journal.get_job(job["id"])
    assert result["status"] == "cancelled"
    assert result["result"] == (receipt if state == "candidate_committed" else None)
    assert result["execution"] == {
        "released": state != "claimed",
        "candidate_accepted": state == "candidate_committed",
        "outcome": {"claimed": "not_released", "released": "unknown", "candidate_committed": "candidate_accepted"}[
            state
        ],
    }
    assert not journal.complete_attempt(job["id"], **attempt, expected_state="candidate_committed")
    journal.close()


def test_blocked_cancel_endpoint_frees_quota_without_dispatch(tmp_path, configs):
    app = create_app(tmp_path, start_paused=True, max_pending=1)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        old = block(app, job)
        response = client.post(f'/api/jobs/{job["id"]}/cancel', headers=headers)
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert app.state.journal.get_job(job["id"])["status"] == "cancelled"
        assert not app.state.journal.release_attempt(job["id"], **old)
        assert (
            client.post("/api/editor/generate", headers=headers, json={**BODY, "idempotency_key": "next"}).status_code
            == 202
        )


def test_renewed_queued_cancel_endpoint_is_fenced(tmp_path, configs):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        old = block(app, job)
        assert (
            client.post(
                f'/api/editor/generations/{job["id"]}/reauthorize', headers=headers, json={"idempotency_key": "renew"}
            ).status_code
            == 202
        )
        response = client.post(f'/api/jobs/{job["id"]}/cancel', headers=headers)
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert app.state.journal.claim_attempt(job["id"]) is None
        assert not app.state.journal.release_attempt(job["id"], **old)
