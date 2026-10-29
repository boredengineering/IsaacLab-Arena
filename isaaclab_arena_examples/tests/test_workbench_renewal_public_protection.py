# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Paused renewal HTTP boundaries with synthetic frozen jobs, never workers."""
import hashlib
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, editor_execution
from isaaclab_arena_examples.tests.test_workbench_metadata_protection import ORIGIN, escaped, login
from isaaclab_arena_examples.tests.test_workbench_reauthorization import block, configs

MARKER = "DUMMY-renewal-public-marker-123456"
BODY = {"idempotency_key": "renewal:one", "credential_ref": None}
FINGERPRINT = hashlib.sha256(json.dumps(BODY, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
INVALID = {"detail": "Invalid request input"}


@pytest.fixture
def api(tmp_path, monkeypatch, configs):
    def unavailable(_):
        raise RuntimeError("No renderer in renewal boundary tests")
    monkeypatch.setattr(editor_execution, "make_snapshot_service", unavailable)
    configs[1].clear()
    app = create_app(tmp_path / "state", start_paused=True, clock=lambda: 1000.0)
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        session, headers = login(client)
        yield app, client, session, headers, configs
        assert app.state.supervisor.paused
        assert app.state.supervisor.process is None
        assert app.state.active_streams == 0
    assert not app.state.workflow_authorization.grants._records
    assert not app.state.publication_authorization._records


def frozen_job(api, shape="clean"):
    app, _, session, _, configs = api
    if shape == "profile":
        configs[0]["model"] = escaped(MARKER)
    metadata = app.state.workflow_authorization.capture(session, "synthetic-original", retrieval=bool(configs[1]))
    inputs = {"operation": "new", "prompt": "Never execute", "workflow_authorization": metadata}
    if shape in ("base_yaml", "root_yaml"):
        inputs[shape] = 'value: "' + escaped(MARKER) + '"'
    elif shape == "nested":
        inputs["unused"] = [{"wrapper": "outer: " + json.dumps('value: "' + escaped(MARKER) + '"')}]
    job = app.state.journal.submit(session["session_id"], "default", "generate", "synthetic:one", inputs)
    block(app, job)
    return app.state.journal.get_job(job["id"])


def url(job):
    return f'/api/editor/generations/{job["id"]}/reauthorize'


def read_disposition(client, job, body=BODY, fingerprint=FINGERPRINT):
    return client.get(f'/api/editor/generations/{job["id"]}/reauthorization-disposition',
                      params={"idempotency_key": body["idempotency_key"], "fingerprint": fingerprint})


def activate(api):
    _, client, _, headers, _ = api
    response = client.put("/api/model-settings", headers=headers, json={
        "provider": "openai", "model": "inert", "api_key": MARKER})
    assert response.status_code == 200, response.text


def observe_effects(app, monkeypatch):
    calls = []
    for obj, name in ((app.state.workflow_authorization, "capture_renewal"),
                      (app.state.workflow_authorization.grants, "issue"),
                      (app.state.journal, "renew_authorization"),
                      (app.state.journal, "seal_authorization_rejection")):
        original = getattr(obj, name)
        def tracked(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(obj, name, tracked)
    monkeypatch.setattr(app.state.supervisor.wake, "set", lambda: calls.append("wake"))
    return calls


@pytest.mark.parametrize("state", ["unknown", "sealed"])
def test_negative_disposition_is_independent_of_protected_frozen_job(api, monkeypatch, state):
    app, client, _, headers, configs = api
    job = frozen_job(api, "nested")
    journal = app.state.journal
    expected = journal.authorization_disposition(job["id"], BODY["idempotency_key"], FINGERPRINT)
    if state == "sealed":
        expected = journal.seal_authorization_rejection(job["id"], BODY["idempotency_key"], FINGERPRINT)
    activate(api)
    configs[0].clear()
    app.state.documents.views.clear()
    app.state.documents.frozen.clear()
    before = list(journal.db.iterdump())
    calls = observe_effects(app, monkeypatch)
    response = read_disposition(client, job)
    assert response.status_code == 200 and response.json() == expected
    assert expected["code"] == ("renewal_unknown" if state == "unknown" else "renewal_rejected")
    assert calls == [] and list(journal.db.iterdump()) == before


def test_recovery_screens_immutable_accepted_snapshot_not_later_job_state(api, monkeypatch):
    app, client, _, headers, _ = api
    job = frozen_job(api)
    accepted = client.post(url(job), headers=headers, json=BODY)
    assert accepted.status_code == 202
    journal = app.state.journal
    attempt = journal.claim_attempt(job["id"])
    assert journal.release_attempt(job["id"], **attempt)
    assert journal.commit_candidate(job["id"], **attempt, receipt={"private_later": MARKER})
    assert journal.complete_attempt(job["id"], **attempt, expected_state="candidate_committed")
    activate(api)
    before = list(journal.db.iterdump())
    calls = observe_effects(app, monkeypatch)
    assert client.post(url(job), headers=headers, json=BODY).json() == accepted.json()
    assert read_disposition(client, job).json()["code"] == "renewal_accepted"
    assert calls == [] and list(journal.db.iterdump()) == before


def test_clean_replay_survives_configuration_and_view_expiry(api, monkeypatch):
    app, client, _, headers, configs = api
    job = frozen_job(api)
    accepted = client.post(url(job), headers=headers, json=BODY)
    assert accepted.status_code == 202, accepted.text
    configs[0].clear()
    configs[1].clear()
    app.state.workflow_authorization.clear()
    app.state.documents.views.clear()
    app.state.documents.frozen.clear()
    before = list(app.state.journal.db.iterdump())
    calls = observe_effects(app, monkeypatch)
    monkeypatch.setattr(app.state.model_settings, "resolve", lambda *a: pytest.fail("Recovery resolved original key"))
    monkeypatch.setattr(app.state.workflow_authorization, "resolve", lambda *a, **k: pytest.fail("Recovery resolved grants"))
    response = client.post(url(job), headers=headers, json=BODY)
    assert response.status_code == 202 and response.json() == accepted.json()
    assert read_disposition(client, job).json()["code"] == "renewal_accepted"
    assert calls == [] and not app.state.workflow_authorization.grants._records
    assert list(app.state.journal.db.iterdump()) == before


@pytest.mark.parametrize("target", ["model", "retrieval"])
def test_fresh_resolved_profiles_are_screened_before_first_grant(api, monkeypatch, target):
    app, client, _, headers, configs = api
    if target == "retrieval":
        configs[1].update({"uri": "bolt://synthetic.invalid:7687", "user": "reader", "database": "synthetic",
                           "password": "DUMMY-graph-password-123456"})
    job = frozen_job(api)
    # Capture a genuine retrieval-bearing frozen fixture when required.
    if target == "retrieval":
        original = app.state.journal.get_job(job["id"])
        assert original["inputs"]["workflow_authorization"]["retrieval"] is not None
    activate(api)
    if target == "model":
        configs[0]["model"] = escaped(MARKER)
    else:
        configs[1]["user"] = escaped(MARKER)
    before = list(app.state.journal.db.iterdump())
    grants = deepcopy(app.state.workflow_authorization.grants._records)
    calls = observe_effects(app, monkeypatch)
    response = client.post(url(job), headers=headers, json=BODY)
    assert response.status_code == 422, response.text
    assert response.json() == INVALID
    assert calls == ["capture_renewal"]
    assert app.state.workflow_authorization.grants._records == grants
    assert list(app.state.journal.db.iterdump()) == before


PROFILE_UNAVAILABLE = {"detail": "Workflow public profile screening unavailable"}


@pytest.mark.parametrize("target,failure", [
    (target, failure) for target in ("model", "retrieval") for failure in (ValueError, RuntimeError, TypeError)
] + [("model", UnicodeEncodeError)])
def test_resolved_profile_screening_fault_leaves_exact_renewal_retryable(api, monkeypatch, target, failure):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import workflow_authorization

    app, client, _, headers, configs = api
    if target == "retrieval":
        configs[1].update({"uri": "bolt://synthetic.invalid:7687", "user": "reader", "database": "synthetic",
                           "password": "DUMMY-graph-password-123456"})
    job = frozen_job(api)
    journal, auth = app.state.journal, app.state.workflow_authorization
    original_model = configs[0]["model"]
    if failure is UnicodeEncodeError:
        # Shape validation accepts it, but the real literal policy's bounded
        # copy rejects it before the recursive scanner reaches its UTF-8 bound.
        configs[0]["model"] = "inert-\ud800"
    before = list(journal.db.iterdump())
    grants = deepcopy(auth.grants._records)
    scanner = workflow_authorization.screen_public_record
    phases = []
    exception_chain = []

    def failing_scanner(value, protect_literal):
        assert set(value) == {"model", "retrieval"}
        assert "api_key" not in value["model"]
        assert value[target] is not None
        if target == "retrieval":
            assert "password" not in value[target]
        try:
            result = scanner(value, protect_literal)
            if failure is not UnicodeEncodeError:
                raise failure("DUMMY-private-profile-screening-failure")
            return result
        except Exception as error:
            phases.append(("resolved_public_profiles", type(error).__name__))
            if failure is UnicodeEncodeError:
                # Record the real policy chain without disabling protect_grants.
                current = error
                while current is not None:
                    traceback = current.__traceback__
                    while traceback.tb_next is not None:
                        traceback = traceback.tb_next
                    exception_chain.append((type(current).__name__, traceback.tb_frame.f_code.co_name,
                                            traceback.tb_frame.f_code.co_filename.rsplit("/", 1)[-1]))
                    current = current.__context__
            raise

    with monkeypatch.context() as patcher:
        calls = observe_effects(app, patcher)
        patcher.setattr(workflow_authorization, "screen_public_record", failing_scanner)
        response = client.post(url(job), headers=headers, json=BODY)
        disposition = read_disposition(client, job)
    policy_rejection = failure is UnicodeEncodeError
    assert phases == [("resolved_public_profiles", "HTTPException" if policy_rejection else failure.__name__)]
    if policy_rejection:
        assert exception_chain == [
            ("HTTPException", "protect_public", "model_settings.py"),
            ("ValueError", "protect_public", "publication_authorization.py"),
            ("ValueError", "_bounded_copy", "execution_grants.py"),
            ("UnicodeEncodeError", "visit", "execution_grants.py"),
        ]
    observed = {
        "status": response.status_code,
        "body": response.json() if response.headers.get("content-type") == "application/json" else response.text,
        "calls": calls,
        "journal_unchanged": list(journal.db.iterdump()) == before,
        "grants_unchanged": auth.grants._records == grants,
        "disposition_status": disposition.status_code,
        "disposition": disposition.json()["code"],
    }
    assert observed == {
        "status": 422 if policy_rejection else 503,
        "body": INVALID if policy_rejection else PROFILE_UNAVAILABLE, "calls": ["capture_renewal"],
        "journal_unchanged": True, "grants_unchanged": True,
        "disposition_status": 200, "disposition": "renewal_unknown",
    }
    # Removing only the fault must allow the identical key to accept, then replay.
    configs[0]["model"] = original_model
    with monkeypatch.context() as patcher:
        calls = observe_effects(app, patcher)
        accepted = client.post(url(job), headers=headers, json=BODY)
        assert accepted.status_code == 202, accepted.text
        assert accepted.json()["inputs"] == job["inputs"]
        assert calls == ["capture_renewal", "issue"] + (["issue"] if target == "retrieval" else []) + [
            "renew_authorization", "wake"]
    configs[0].clear()
    configs[1].clear()
    before = list(journal.db.iterdump())
    grants = deepcopy(auth.grants._records)
    with monkeypatch.context() as patcher:
        calls = observe_effects(app, patcher)
        replay = client.post(url(job), headers=headers, json=BODY)
        assert replay.status_code == 202 and replay.json() == accepted.json()
        assert read_disposition(client, job).json()["code"] == "renewal_accepted"
        assert calls == []
        assert list(journal.db.iterdump()) == before and auth.grants._records == grants


@pytest.mark.parametrize("fault", ["absent_config", "invalid_profile", "changed_profile"])
def test_profile_domain_rejection_still_seals_and_replays_after_configuration_repair(api, monkeypatch, fault):
    app, client, _, headers, configs = api
    job = frozen_job(api)
    journal, auth = app.state.journal, app.state.workflow_authorization
    config = dict(configs[0])
    if fault == "absent_config":
        configs[0].clear()
    else:
        configs[0]["model"] = "" if fault == "invalid_profile" else "different-valid-model"
    before = list(journal.db.iterdump())
    grants = deepcopy(auth.grants._records)
    with monkeypatch.context() as patcher:
        calls = observe_effects(app, patcher)
        response = client.post(url(job), headers=headers, json=BODY)
        assert response.status_code == 409, response.text
        sealed = response.json()["detail"]
        assert sealed == journal.authorization_disposition(job["id"], BODY["idempotency_key"], FINGERPRINT)
        assert sealed["code"] == "renewal_rejected"
        assert calls == ["capture_renewal"] + (["issue"] if fault == "changed_profile" else []) + [
            "seal_authorization_rejection"]
        assert journal.latest_authorization(job["id"]) is None
        assert journal.get_job(job["id"]) == job
        assert list(journal.db.iterdump()) != before
        assert auth.grants._records == grants
    configs[0].clear()
    configs[0].update(config)
    before = list(journal.db.iterdump())
    with monkeypatch.context() as patcher:
        calls = observe_effects(app, patcher)
        replay = client.post(url(job), headers=headers, json=BODY)
        assert replay.status_code == 409 and replay.json() == response.json()
        disposition = read_disposition(client, job)
        assert disposition.status_code == 200 and disposition.json() == sealed
        assert calls == [] and list(journal.db.iterdump()) == before
        assert auth.grants._records == grants
    corrected = client.post(url(job), headers=headers, json={**BODY, "idempotency_key": "renewal:corrected"})
    assert corrected.status_code == 202, corrected.text


def test_profile_scanner_policy_http_exception_is_preserved(api, monkeypatch):
    from fastapi import HTTPException
    from isaaclab_arena_examples.agentic_environment_generation.web_api import workflow_authorization

    app, client, _, headers, _ = api
    job = frozen_job(api)
    journal, auth = app.state.journal, app.state.workflow_authorization
    before = list(journal.db.iterdump())
    grants = deepcopy(auth.grants._records)
    def reject(value, protect_literal):
        assert set(value) == {"model", "retrieval"}
        raise HTTPException(422, "Invalid request input", headers={"X-Policy-Test": "preserved"})
    with monkeypatch.context() as patcher:
        calls = observe_effects(app, patcher)
        patcher.setattr(workflow_authorization, "screen_public_record", reject)
        response = client.post(url(job), headers=headers, json=BODY)
        assert response.status_code == 422 and response.json() == INVALID
        assert response.headers["X-Policy-Test"] == "preserved"
        assert read_disposition(client, job).json()["code"] == "renewal_unknown"
        assert calls == ["capture_renewal"]
        assert list(journal.db.iterdump()) == before and auth.grants._records == grants


def test_profile_scanner_base_exception_control_flow_is_not_normalized(api, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import workflow_authorization

    class StopScreening(BaseException):
        pass

    app, _, session, _, _ = api
    job = frozen_job(api)
    journal, auth = app.state.journal, app.state.workflow_authorization
    before = list(journal.db.iterdump())
    grants = deepcopy(auth.grants._records)
    sentinel = StopScreening("test-only control flow")
    def stop(value, protect_literal):
        raise sentinel
    with monkeypatch.context() as patcher:
        calls = observe_effects(app, patcher)
        patcher.setattr(workflow_authorization, "screen_public_record", stop)
        # Direct capture: ASGI middleware owns BaseException transport semantics.
        with pytest.raises(StopScreening) as caught:
            auth.capture_renewal(session, job)
        assert caught.value is sentinel
        assert calls == ["capture_renewal"]
        assert list(journal.db.iterdump()) == before and auth.grants._records == grants


@pytest.mark.parametrize("shape", ["base_yaml", "root_yaml", "nested", "profile"])
def test_accepted_post_replay_withholds_newly_protected_snapshot_without_effects(api, monkeypatch, shape):
    app, client, _, headers, _ = api
    job = frozen_job(api, shape)
    accepted = client.post(url(job), headers=headers, json=BODY)
    assert accepted.status_code == 202, accepted.text
    activate(api)
    app.state.documents.views.clear()
    app.state.documents.frozen.clear()
    before = list(app.state.journal.db.iterdump())
    grants = deepcopy(app.state.workflow_authorization.grants._records)
    calls = observe_effects(app, monkeypatch)
    response = client.post(url(job), headers=headers, json=BODY)
    assert response.status_code == 422, response.text
    assert response.json() == INVALID
    assert calls == []
    assert list(app.state.journal.db.iterdump()) == before
    assert app.state.workflow_authorization.grants._records == grants
    assert app.state.journal.get_authorization_replay(job["id"], BODY["idempotency_key"], FINGERPRINT) == accepted.json()


@pytest.mark.parametrize("protected", [False, True])
def test_concurrent_commit_winner_rolls_back_loser_without_extra_wake(api, monkeypatch, protected):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.model_settings import SettingsInput

    app, client, session, headers, _ = api
    job = frozen_job(api, "nested")
    journal = app.state.journal
    auth = app.state.workflow_authorization
    winner_metadata = auth.capture_renewal(session, job)
    renew = journal.renew_authorization
    winner = {}
    def race(job_id, key, fingerprint, attempt, record, **kwargs):
        winner_record = {**record, "workflow_authorization": winner_metadata}
        winner["accepted"], fresh = renew(job_id, key, fingerprint, attempt, winner_record, **kwargs)
        assert fresh
        if protected:
            app.state.model_settings.save(session, SettingsInput(provider="openai", model="inert", api_key=MARKER))
        winner["durable"] = list(journal.db.iterdump())
        winner["grants"] = {key: deepcopy(value) for key, value in auth.grants._records.items() if key in grants}
        return renew(job_id, key, fingerprint, attempt, record, **kwargs)
    grants = deepcopy(auth.grants._records)
    monkeypatch.setattr(journal, "renew_authorization", race)
    calls = observe_effects(app, monkeypatch)
    response = client.post(url(job), headers=headers, json=BODY)
    assert response.status_code == (422 if protected else 202), response.text
    assert response.json() == (INVALID if protected else winner["accepted"])
    assert calls == ["capture_renewal", "issue", "renew_authorization"]
    assert list(journal.db.iterdump()) == winner["durable"]
    assert auth.grants._records == winner["grants"]


@pytest.mark.parametrize("protected", [False, True])
def test_concurrent_seal_winner_is_screened_without_reissuing_or_waking(api, monkeypatch, protected):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.model_settings import SettingsInput

    app, client, session, headers, _ = api
    job = frozen_job(api, "nested")
    journal = app.state.journal
    auth = app.state.workflow_authorization
    attempt = journal.renewable_attempt(job["id"])
    metadata = auth.capture_renewal(session, job)
    record = {"schema_version": 1, "workflow_authorization": metadata,
              "approval": "single_operator_workspace", "blocked_attempt": attempt}
    renewable = journal.renewable_attempt
    winner = {}
    def race(job_id):
        monkeypatch.setattr(journal, "renewable_attempt", renewable)
        winner["accepted"], fresh = journal.renew_authorization(
            job_id, BODY["idempotency_key"], FINGERPRINT, attempt, record)
        assert fresh
        if protected:
            app.state.model_settings.save(session, SettingsInput(provider="openai", model="inert", api_key=MARKER))
        winner["durable"] = list(journal.db.iterdump())
        winner["grants"] = deepcopy(auth.grants._records)
        raise ValueError("Concurrent accepted winner")
    calls = observe_effects(app, monkeypatch)
    monkeypatch.setattr(journal, "renewable_attempt", race)
    response = client.post(url(job), headers=headers, json=BODY)
    assert response.status_code == (422 if protected else 202), response.text
    assert response.json() == (INVALID if protected else winner["accepted"])
    assert calls == ["renew_authorization", "seal_authorization_rejection"]
    assert list(journal.db.iterdump()) == winner["durable"]
    assert auth.grants._records == winner["grants"]
    assert journal.get_authorization_replay(job["id"], BODY["idempotency_key"], FINGERPRINT) == winner["accepted"]


UNAVAILABLE = {"detail": "Workflow renewal accepted; public job record unavailable. Retain the exact renewal request for disposition lookup"}


@pytest.mark.parametrize("failure", ["policy", "value", "runtime", "type"])
def test_postcommit_response_failure_preserves_acceptance_without_false_rejection(api, monkeypatch, failure):
    from fastapi import HTTPException
    from isaaclab_arena_examples.agentic_environment_generation.web_api import workflow_routes

    app, client, _, headers, _ = api
    job = frozen_job(api)
    guard = workflow_routes.protect_public_record
    def fail_response(request, value):
        if isinstance(value, dict) and value.get("id") == job["id"] and value.get("status") == "queued":
            if failure == "policy":
                raise HTTPException(422, "Invalid request input")
            raise {"value": ValueError, "runtime": RuntimeError, "type": TypeError}[failure]("private failure")
        return guard(request, value)
    calls = observe_effects(app, monkeypatch)
    with monkeypatch.context() as patcher:
        patcher.setattr(workflow_routes, "protect_public_record", fail_response)
        response = client.post(url(job), headers=headers, json=BODY)
    assert response.status_code == 503, response.text
    assert response.json() == UNAVAILABLE
    assert calls == ["capture_renewal", "issue", "renew_authorization", "wake"]
    journal = app.state.journal
    accepted = journal.get_authorization_replay(job["id"], BODY["idempotency_key"], FINGERPRINT)
    assert accepted["status"] == "queued" and accepted["inputs"] == job["inputs"]
    assert len(app.state.workflow_authorization.grants._records) == 2
    assert read_disposition(client, job).json()["code"] == "renewal_accepted"
    assert client.post(url(job), headers=headers, json=BODY).json() == accepted
    assert calls == ["capture_renewal", "issue", "renew_authorization", "wake"]


@pytest.mark.parametrize("route", ["post", "get"])
@pytest.mark.parametrize("failure_type", [ValueError, RuntimeError, TypeError])
def test_accepted_recovery_guard_failure_never_enters_rejection_sealing(api, monkeypatch, route, failure_type):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import workflow_routes

    app, client, _, headers, _ = api
    job = frozen_job(api)
    assert client.post(url(job), headers=headers, json=BODY).status_code == 202
    before = list(app.state.journal.db.iterdump())
    calls = observe_effects(app, monkeypatch)
    guard = workflow_routes.protect_public_record
    def fail_response(request, value):
        if isinstance(value, dict) and value.get("id") == job["id"]:
            raise failure_type("private failure")
        return guard(request, value)
    monkeypatch.setattr(workflow_routes, "protect_public_record", fail_response)
    response = client.post(url(job), headers=headers, json=BODY) if route == "post" else read_disposition(client, job)
    assert response.status_code == 503, response.text
    assert response.json() == UNAVAILABLE
    assert calls == []
    assert list(app.state.journal.db.iterdump()) == before


def test_disposition_checks_exact_fingerprint_before_current_policy(api, monkeypatch):
    app, client, _, headers, _ = api
    job = frozen_job(api)
    assert client.post(url(job), headers=headers, json=BODY).status_code == 202
    wrong = "f" * 64
    saved = client.put("/api/model-settings", headers=headers, json={
        "provider": "openai", "model": "inert", "api_key": wrong})
    assert saved.status_code == 200, saved.text
    before = list(app.state.journal.db.iterdump())
    calls = observe_effects(app, monkeypatch)
    response = read_disposition(client, job, fingerprint=wrong)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "Workflow renewal disposition unavailable or conflicting"}
    assert calls == []
    assert list(app.state.journal.db.iterdump()) == before


def test_sealed_post_recovery_never_rechecks_protected_job_or_configuration(api, monkeypatch):
    app, client, _, headers, configs = api
    job = frozen_job(api, "nested")
    configs[0].clear()
    response = client.post(url(job), headers=headers, json=BODY)
    assert response.status_code == 409, response.text
    sealed = response.json()
    assert sealed["detail"]["code"] == "renewal_rejected"
    activate(api)
    app.state.documents.views.clear()
    app.state.documents.frozen.clear()
    before = list(app.state.journal.db.iterdump())
    calls = observe_effects(app, monkeypatch)
    response = client.post(url(job), headers=headers, json=BODY)
    assert response.status_code == 409, response.text
    assert response.json() == sealed
    assert read_disposition(client, job).json() == sealed["detail"]
    assert calls == []
    assert list(app.state.journal.db.iterdump()) == before


@pytest.mark.parametrize("phase", ["job", "record"])
def test_admission_guard_value_error_cannot_seal_nonacceptance(api, monkeypatch, phase):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import workflow_routes

    app, client, _, headers, _ = api
    job = frozen_job(api)
    before = list(app.state.journal.db.iterdump())
    grants = deepcopy(app.state.workflow_authorization.grants._records)
    guard = workflow_routes.protect_public_record
    def fail_input(request, value):
        if isinstance(value, dict) and (value.get("id") == job["id"] if phase == "job" else "blocked_attempt" in value):
            raise ValueError("private screening failure")
        return guard(request, value)
    calls = observe_effects(app, monkeypatch)
    monkeypatch.setattr(workflow_routes, "protect_public_record", fail_input)
    response = client.post(url(job), headers=headers, json=BODY)
    assert response.status_code == 503, response.text
    assert response.json() == {"detail": "Workflow renewal public record unavailable; retain the exact request for disposition lookup"}
    assert calls == ([] if phase == "job" else ["capture_renewal", "issue"])
    assert list(app.state.journal.db.iterdump()) == before
    assert app.state.workflow_authorization.grants._records == grants


def test_renewal_record_screening_rejects_encoded_metadata_and_rolls_back_before_commit(api, monkeypatch):
    app, client, _, headers, _ = api
    job = frozen_job(api)
    activate(api)
    auth = app.state.workflow_authorization
    capture = auth.capture_renewal
    def legacy_metadata(*args, **kwargs):
        metadata = capture(*args, **kwargs)
        metadata["model"]["profile"]["unused"] = 'value: "' + escaped(MARKER) + '"'
        return metadata
    monkeypatch.setattr(auth, "capture_renewal", legacy_metadata)
    before = list(app.state.journal.db.iterdump())
    grants = deepcopy(auth.grants._records)
    calls = observe_effects(app, monkeypatch)
    response = client.post(url(job), headers=headers, json=BODY)
    assert response.status_code == 422, response.text
    assert response.json() == INVALID
    assert calls == ["capture_renewal", "issue"]
    assert list(app.state.journal.db.iterdump()) == before
    assert auth.grants._records == grants


@pytest.mark.parametrize("shape", ["base_yaml", "root_yaml", "nested", "profile"])
def test_fresh_renewal_screens_complete_job_before_capture_or_seal(api, monkeypatch, shape):
    app, client, _, headers, _ = api
    job = frozen_job(api, shape)
    activate(api)
    before = list(app.state.journal.db.iterdump())
    grants = deepcopy(app.state.workflow_authorization.grants._records)
    calls = observe_effects(app, monkeypatch)
    response = client.post(url(job), headers=headers, json=BODY)
    assert response.status_code == 422, response.text
    assert response.json() == INVALID
    assert calls == []
    assert list(app.state.journal.db.iterdump()) == before
    assert app.state.workflow_authorization.grants._records == grants
    assert read_disposition(client, job).json()["code"] == "renewal_unknown"


@pytest.mark.parametrize("shape", ["base_yaml", "root_yaml", "nested", "profile"])
def test_accepted_disposition_withholds_newly_protected_snapshot_without_effects(api, monkeypatch, shape):
    app, client, _, headers, _ = api
    job = frozen_job(api, shape)
    accepted = client.post(url(job), headers=headers, json=BODY)
    assert accepted.status_code == 202, accepted.text
    assert read_disposition(client, job).json()["code"] == "renewal_accepted"
    activate(api)
    app.state.documents.views.clear()
    app.state.documents.frozen.clear()
    before = list(app.state.journal.db.iterdump())
    grants = deepcopy(app.state.workflow_authorization.grants._records)
    calls = observe_effects(app, monkeypatch)
    response = read_disposition(client, job)
    assert response.status_code == 422, response.text
    assert response.json() == INVALID
    assert calls == []
    assert list(app.state.journal.db.iterdump()) == before
    assert app.state.workflow_authorization.grants._records == grants
    assert app.state.journal.get_authorization_replay(job["id"], BODY["idempotency_key"], FINGERPRINT) == accepted.json()
