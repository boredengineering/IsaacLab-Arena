# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit renewal never rewrites a frozen generation request."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, generation, graph_access
from isaaclab_arena_examples.tests.test_workbench_editor import ORIGIN, login
from isaaclab_arena_examples.tests.test_workbench_workflow_authorization import BODY, GRAPH, MODEL


@pytest.fixture
def configs(monkeypatch):
    model, graph = dict(MODEL), dict(GRAPH)
    monkeypatch.setattr(generation, "configuration", lambda: dict(model) if model else None)
    monkeypatch.setattr(graph_access, "configuration", lambda: dict(graph) if graph else None)
    monkeypatch.setattr(generation, "generate", lambda *a, **k: pytest.fail("Provider call"))
    return model, graph


def block(app, job):
    journal = app.state.journal
    journal.resume_queue()
    attempt = journal.claim_attempt(job["id"])
    assert journal.block_attempt_authorization(job["id"], **attempt)
    return attempt


def test_explicit_renewal_freezes_inputs_and_replays_without_configuration(tmp_path, configs, monkeypatch):
    now = [1000.0]
    app = create_app(tmp_path, start_paused=True, clock=lambda: now[0])
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        old = block(app, job)
        now[0] += 181
        configs[0]["api_key"] = "renewed-private-key-marker"
        url = f'/api/editor/generations/{job["id"]}/reauthorize'
        body = {"idempotency_key": "renew-one"}
        response = client.post(url, headers=headers, json=body)
        assert response.status_code == 202, response.text
        renewed = response.json()
        assert renewed["status"] == "queued"
        assert renewed["inputs"] == job["inputs"]
        assert app.state.journal.get_job(job["id"])["inputs"] == job["inputs"]
        assert app.state.workflow_authorization.resolve(renewed)["config"] == configs[0]
        attempt = app.state.journal.claim_attempt(job["id"])
        assert attempt["generation"] == old["generation"] + 1
        # Current-policy scanning may observe absent server settings. Recovery
        # must not resolve the original configuration or issue renewed authority.
        monkeypatch.setattr(generation, "configuration", lambda: None)
        monkeypatch.setattr(graph_access, "configuration", lambda: None)
        policy_checks = []
        protect_public = app.state.model_settings.protect_public

        def current_policy(value):
            policy_checks.append(True)
            return protect_public(value)

        with monkeypatch.context() as replay_patch:
            replay_patch.setattr(
                app.state.model_settings, "resolve", lambda *a, **k: pytest.fail("Replay resolved credentials")
            )
            replay_patch.setattr(
                app.state.workflow_authorization, "resolve", lambda *a, **k: pytest.fail("Replay resolved workflow")
            )
            replay_patch.setattr(
                app.state.workflow_authorization, "capture_renewal", lambda *a, **k: pytest.fail("Replay captured grants")
            )
            replay_patch.setattr(
                app.state.workflow_authorization.grants, "issue", lambda *a, **k: pytest.fail("Replay issued grant")
            )
            replay_patch.setattr(
                app.state.workflow_authorization.grants, "resolve", lambda *a, **k: pytest.fail("Replay resolved grant")
            )
            replay_patch.setattr(app.state.supervisor.wake, "set", lambda: pytest.fail("Replay woke dispatch"))
            replay_patch.setattr(app.state.model_settings, "protect_public", current_policy)
            before_replay = list(app.state.journal.db.iterdump())
            replay = client.post(url, headers=headers, json=body)
            assert replay.status_code == 202, replay.text
            assert replay.json() == renewed
            assert policy_checks, "Accepted recovery must still apply current response policy"
            assert list(app.state.journal.db.iterdump()) == before_replay
            assert client.post(url, headers=headers, json={**body, "credential_ref": "a" * 64}).status_code == 409
            assert list(app.state.journal.db.iterdump()) == before_replay
    for path in tmp_path.rglob("*"):
        if path.is_file():
            for secret in (
                MODEL["api_key"],
                GRAPH["password"],
                "renewed-private-key-marker",
            ):
                assert secret.encode() not in path.read_bytes()


@pytest.mark.parametrize(
    "field,value",
    [
        ("principal", "changed-principal"),
        ("base_url", "https://other.invalid/v1"),
        ("model", "other"),
        ("provider", "other"),
    ],
)
def test_renewal_rejects_changed_model_profile(tmp_path, configs, field, value):
    configs[0]["principal"] = "original-principal"
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        block(app, job)
        before = set(app.state.workflow_authorization.grants._records)
        configs[0][field] = value
        result = client.post(
            f'/api/editor/generations/{job["id"]}/reauthorize',
            headers=headers,
            json={"idempotency_key": "renew"},
        )
        assert result.status_code == 409
        assert set(app.state.workflow_authorization.grants._records) == before
        assert app.state.journal.latest_authorization(job["id"]) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://api.invalid/v1?api_key=hidden-marker",
        "https://user:password@api.invalid/v1",
        "https://api.invalid/v1#secret",
    ],
)
def test_capture_rejects_parameterized_metadata_url(tmp_path, configs, url):
    configs[0]["base_url"] = url
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        result = client.post("/api/editor/generate", headers=headers, json=BODY)
        assert result.status_code == 503
        assert not app.state.workflow_authorization.grants._records


@pytest.mark.parametrize("replace_session", [False, True])
def test_session_key_renewal_uses_current_explicit_owner(tmp_path, configs, replace_session):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        settings = {
            "provider": "openai",
            "model": "temp-model",
            "api_key": "old-temporary-marker",
            "ttl_minutes": 15,
        }
        ref = client.put("/api/model-settings", headers=headers, json=settings).json()["credential_ref"]
        job = client.post(
            "/api/editor/generate",
            headers=headers,
            json={**BODY, "credential_ref": ref},
        ).json()
        block(app, job)
        if replace_session:
            client.delete("/api/session", headers=headers)
            headers = login(client)
        settings["api_key"] = "replacement-temporary-marker"
        new_ref = client.put("/api/model-settings", headers=headers, json=settings).json()["credential_ref"]
        url = f'/api/editor/generations/{job["id"]}/reauthorize'
        assert client.post(url, headers=headers, json={"idempotency_key": "missing"}).status_code == 409
        assert (
            client.post(
                url,
                headers=headers,
                json={"idempotency_key": "old", "credential_ref": ref},
            ).status_code
            == 409
        )
        response = client.post(
            url,
            headers=headers,
            json={"idempotency_key": "new", "credential_ref": new_ref},
        )
        assert response.status_code == 202, response.text
        assert response.json()["inputs"] == job["inputs"]
        config = app.state.editor_execution.workflow_authorizer(response.json())["config"]
        assert config["api_key"] == settings["api_key"]
        owner = app.state.journal.latest_authorization(job["id"])["workflow_authorization"]["model"]["owner_id"]
        assert owner == client.get("/api/session").json()["session_id"]
        client.put(
            "/api/model-settings",
            headers=headers,
            json={**settings, "api_key": "rotated-again-marker"},
        )
        with pytest.raises(ValueError):
            app.state.editor_execution.workflow_authorizer(response.json())


@pytest.mark.parametrize("state", ["queued", "released", "indeterminate", "cancelled", "completed"])
def test_no_renewal_for_nonblocked_work(tmp_path, configs, state):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        j = app.state.journal
        if state != "queued":
            j.resume_queue()
            attempt = j.claim_attempt(job["id"])
            if state in ("released", "completed"):
                assert j.release_attempt(job["id"], **attempt)
            if state == "indeterminate":
                assert j.mark_attempt_indeterminate(job["id"], **attempt, expected_state="claimed")
            if state == "cancelled":
                assert j.cancel_attempt(job["id"], **attempt, expected_state="claimed")
            if state == "completed":
                assert j.commit_candidate(job["id"], **attempt, receipt={"safe": True})
                assert j.complete_attempt(job["id"], **attempt, expected_state="candidate_committed")
        before = set(app.state.workflow_authorization.grants._records)
        response = client.post(
            f'/api/editor/generations/{job["id"]}/reauthorize',
            headers=headers,
            json={"idempotency_key": "renew"},
        )
        assert response.status_code == 409
        assert set(app.state.workflow_authorization.grants._records) == before


def test_graph_none_freeze_and_request_security(tmp_path, configs):
    configs[1].clear()
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        block(app, job)
        configs[1].update(GRAPH)
        url = f'/api/editor/generations/{job["id"]}/reauthorize'
        body = {"idempotency_key": "renew"}
        assert client.post(url, json=body).status_code == 403
        assert client.post(url, headers=headers, json={**body, "api_key": "raw-secret"}).status_code == 422
        assert client.post(url, headers=headers, json={**body, "idempotency_key": "a" * 129}).status_code == 422
        response = client.post(url, headers=headers, json=body)
        assert response.status_code == 202
        assert app.state.workflow_authorization.resolve(response.json())["graph_config"] is None
        configs[0]["model"] = "changed-after-renewal"
        with pytest.raises(ValueError):
            app.state.workflow_authorization.resolve(response.json())


def test_renewal_cas_one_winner_and_immutable_record(tmp_path, configs):
    import sqlite3

    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        block(app, job)
        attempt = app.state.journal.get_attempt(job["id"])
        barrier = threading.Barrier(2)

        def renew(number):
            barrier.wait()
            try:
                return app.state.journal.renew_authorization(
                    job["id"],
                    str(number),
                    str(number) * 64,
                    attempt,
                    {"schema_version": 1},
                )[1]
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(renew, [1, 2])) == [False, True]
        with pytest.raises(sqlite3.IntegrityError):
            app.state.journal.db.execute("UPDATE workflow_authorizations SET body='{}'")
        assert app.state.journal.get_job(job["id"])["inputs"] == job["inputs"]


@pytest.mark.parametrize("failure", ["queue", "grant", "bounds"])
def test_failed_renewal_rolls_back_only_new_grants(tmp_path, configs, monkeypatch, failure):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        block(app, job)
        grants = app.state.workflow_authorization.grants
        before = set(grants._records)
        if failure == "queue":
            app.state.max_pending = 0
        elif failure == "grant":
            grants._capacity = len(before) + 1
        else:
            original = app.state.workflow_authorization.capture_renewal

            def oversized(*args, **kwargs):
                result = original(*args, **kwargs)
                result["model"]["profile"]["padding"] = "x" * 17000
                return result

            monkeypatch.setattr(app.state.workflow_authorization, "capture_renewal", oversized)
        response = client.post(
            f'/api/editor/generations/{job["id"]}/reauthorize',
            headers=headers,
            json={"idempotency_key": "renew"},
        )
        assert response.status_code == 409
        proof = response.json()["detail"]
        assert proof["code"] == "renewal_rejected"
        assert proof["job_id"] == job["id"]
        assert proof["idempotency_key"] == "renew"
        assert len(proof["fingerprint"]) == 64
        read_url = f'/api/editor/generations/{job["id"]}/reauthorization-disposition'
        assert (
            client.get(
                read_url,
                params={
                    "idempotency_key": "renew",
                    "fingerprint": proof["fingerprint"],
                },
            ).json()
            == proof
        )
        assert set(grants._records) == before
        assert app.state.journal.get_job(job["id"])["status"] == "blocked_authorization"
        assert app.state.journal.latest_authorization(job["id"]) is None


def test_sealed_expired_reference_allows_new_key_but_never_old_replay(tmp_path, configs):
    import hashlib
    import json
    import sqlite3

    now = [1000.0]
    app = create_app(tmp_path, start_paused=True, clock=lambda: now[0])
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        settings = {
            "provider": "openai",
            "model": "temp-model",
            "api_key": "private-A-marker",
            "ttl_minutes": 15,
        }
        ref = client.put("/api/model-settings", headers=headers, json=settings).json()["credential_ref"]
        job = client.post(
            "/api/editor/generate",
            headers=headers,
            json={**BODY, "credential_ref": ref},
        ).json()
        block(app, job)
        attempt = app.state.journal.get_attempt(job["id"])
        now[0] += 901
        headers = login(client)
        new_ref = client.put(
            "/api/model-settings",
            headers=headers,
            json={**settings, "api_key": "private-B-marker"},
        ).json()["credential_ref"]
        body = {"idempotency_key": "rejected-A", "credential_ref": ref}
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        url = f'/api/editor/generations/{job["id"]}/reauthorize'
        proof = client.post(url, headers=headers, json=body).json()["detail"]
        assert proof == {
            "schema_version": 1,
            "code": "renewal_rejected",
            "job_id": job["id"],
            "idempotency_key": "rejected-A",
            "fingerprint": fingerprint,
        }
        with pytest.raises(ValueError):
            app.state.journal.renew_authorization(job["id"], "rejected-A", fingerprint, attempt, {})
        assert client.post(url, headers=headers, json=body).json()["detail"] == proof
        corrected = client.post(
            url,
            headers=headers,
            json={"idempotency_key": "corrected-B", "credential_ref": new_ref},
        )
        assert corrected.status_code == 202
        assert corrected.json()["inputs"] == job["inputs"]
        read_url = f'/api/editor/generations/{job["id"]}/reauthorization-disposition'
        params = {"idempotency_key": "rejected-A", "fingerprint": fingerprint}
        assert client.get(read_url, params=params).json() == proof
        assert client.get(read_url, params={**params, "fingerprint": "f" * 64}).status_code == 409
        assert client.get(read_url, params={**params, "idempotency_key": "absent"}).json()["code"] == "renewal_unknown"
        with pytest.raises(sqlite3.IntegrityError):
            app.state.journal.db.execute("UPDATE workflow_renewal_rejections SET fingerprint='x'")
        client.delete("/api/session", headers=headers)
        assert client.get(read_url, params=params).status_code == 401
        login(client)
        assert client.get(read_url, params=params).json() == proof
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert b"private-A-marker" not in path.read_bytes()
            assert b"private-B-marker" not in path.read_bytes()


@pytest.mark.parametrize("winner", ["accepted", "sealed", "race"])
def test_acceptance_and_sealing_have_one_durable_outcome(tmp_path, configs, winner):
    from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal

    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        block(app, job)
        journal = app.state.journal
        attempt = journal.get_attempt(job["id"])
        peer = Journal(journal.db.execute("PRAGMA database_list").fetchone()[2])
        barrier = threading.Barrier(2)

        def accept():
            if winner == "race":
                barrier.wait()
            try:
                return journal.renew_authorization(job["id"], "key", "a" * 64, attempt, {})[0]
            except ValueError:
                return None

        def seal():
            if winner == "race":
                barrier.wait()
            return peer.seal_authorization_rejection(job["id"], "key", "a" * 64)

        try:
            if winner == "race":
                with ThreadPoolExecutor(max_workers=2) as pool:
                    a, s = pool.submit(accept), pool.submit(seal)
                    accepted, sealed = a.result(), s.result()
            elif winner == "accepted":
                accepted, sealed = accept(), seal()
            else:
                sealed, accepted = seal(), accept()
            if accepted is not None:
                assert sealed == accepted
                assert journal.get_authorization_replay(job["id"], "key", "a" * 64) == accepted
                assert journal.db.execute("SELECT COUNT(*) FROM workflow_renewal_rejections").fetchone()[0] == 0
            else:
                assert sealed["code"] == "renewal_rejected"
                assert journal.latest_authorization(job["id"]) is None
                assert journal.renew_authorization(job["id"], "new-key", "b" * 64, attempt, {})[1]
        finally:
            peer.db.close()


def test_rejection_bounds_are_enforced_without_consuming_acceptance_slot(tmp_path, configs):
    import sqlite3

    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        block(app, job)
        journal = app.state.journal
        for key, fp in [
            ("x" * 129, "a" * 64),
            ("unicode-雪", "a" * 64),
            ("key", "z" * 64),
        ]:
            with pytest.raises(ValueError):
                journal.seal_authorization_rejection(job["id"], key, fp)
        for number in range(128):
            assert journal.seal_authorization_rejection(job["id"], str(number), "a" * 64)["code"] == "renewal_rejected"
        with pytest.raises(ValueError):
            journal.seal_authorization_rejection(job["id"], "over-cap", "a" * 64)
        assert journal.db.execute("SELECT COUNT(*) FROM workflow_renewal_rejections").fetchone()[0] == 128
        with pytest.raises(sqlite3.IntegrityError):
            journal.db.execute("DELETE FROM workflow_renewal_rejections")
        assert journal.renew_authorization(job["id"], "new", "b" * 64, journal.get_attempt(job["id"]), {})[1]


def test_sealing_storage_failure_is_ambiguous(tmp_path, configs, monkeypatch):
    import sqlite3

    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        block(app, job)
        configs[0].clear()

        def fail(*args):
            raise sqlite3.OperationalError("private-error-marker")

        monkeypatch.setattr(app.state.journal, "seal_authorization_rejection", fail)
        response = client.post(
            f'/api/editor/generations/{job["id"]}/reauthorize',
            headers=headers,
            json={"idempotency_key": "key"},
        )
        assert response.status_code == 409
        assert isinstance(response.json()["detail"], str)
        assert "private-error-marker" not in response.text


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("secret_source", ["model", "graph"])
def test_nonrenewable_request_never_seals_private_renewal_key(tmp_path, configs, cancelled, secret_source):
    secret = configs[0]["api_key"] if secret_source == "model" else configs[1]["password"]
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        if cancelled:
            assert client.post(f'/api/jobs/{job["id"]}/cancel', headers=headers).status_code == 200
        response = client.post(
            f'/api/editor/generations/{job["id"]}/reauthorize',
            headers=headers,
            json={"idempotency_key": secret},
        )
        assert secret not in response.text
        assert response.status_code == 422
        assert app.state.journal.db.execute("SELECT COUNT(*) FROM workflow_renewal_rejections").fetchone()[0] == 0
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()


@pytest.mark.parametrize("secret_source", ["model", "graph"])
def test_disposition_does_not_reflect_private_query_key(tmp_path, configs, secret_source):
    secret = configs[0]["api_key"] if secret_source == "model" else configs[1]["password"]
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        response = client.get(
            f'/api/editor/generations/{job["id"]}/reauthorization-disposition',
            params={"idempotency_key": secret, "fingerprint": "a" * 64},
        )
        assert secret not in response.text
        assert response.status_code == 422


def test_uncommitted_rejection_never_becomes_disposition_proof(tmp_path, configs):
    import hashlib
    import json
    import sqlite3

    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        job = client.post("/api/editor/generate", headers=headers, json=BODY).json()
        block(app, job)
        configs[0].clear()
        connection = app.state.journal.db

        class FailCommitOnce:
            failed = False
            seal_written = False

            def execute(self, sql, *args):
                if sql.startswith("INSERT INTO workflow_renewal_rejections"):
                    self.seal_written = True
                if sql == "COMMIT" and self.seal_written and not self.failed:
                    self.failed = True
                    raise sqlite3.OperationalError("synthetic-commit-failure")
                return connection.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(connection, name)

        app.state.journal.db = FailCommitOnce()
        payload = {"idempotency_key": "commit-fails", "credential_ref": None}
        url = f'/api/editor/generations/{job["id"]}'
        response = client.post(url + "/reauthorize", headers=headers, json=payload)
        assert response.status_code == 409 and isinstance(response.json()["detail"], str)
        assert not connection.in_transaction
        assert connection.execute("SELECT COUNT(*) FROM workflow_renewal_rejections").fetchone()[0] == 0
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        proof = client.get(
            url + "/reauthorization-disposition",
            params={
                "idempotency_key": payload["idempotency_key"],
                "fingerprint": fingerprint,
            },
        )
        assert proof.status_code == 200 and proof.json()["code"] == "renewal_unknown"


def test_renewal_body_has_small_transport_bound(tmp_path, configs):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        response = client.post(
            "/api/editor/generations/" + "a" * 32 + "/reauthorize",
            headers=headers,
            content=" " * 16385,
        )
        assert response.status_code == 413
