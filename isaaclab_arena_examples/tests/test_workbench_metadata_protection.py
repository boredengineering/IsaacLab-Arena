# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Public metadata boundaries: paused real HTTP, dummy credentials, no workloads."""

from copy import deepcopy

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import (
    create_app, editor_execution, generation, graph_access,
)
# Explicit unchanged lifecycle/recovery regressions run through this approved
# metadata suite; this is not an expansion to arbitrary pytest path selection.
from isaaclab_arena_examples.tests.test_workbench_model_settings import (
    test_selected_expiration_is_enforced_and_capped_by_session,
    test_no_key_timer_follows_session_activity_but_not_polling,
    test_credentials_expire_without_poll_extension_and_clear_on_revoke_shutdown_restart,
    test_invalid_expiration_does_not_replace_existing_key,
)
from isaaclab_arena_examples.tests.test_workbench_reauthorization import (
    configs,
    test_explicit_renewal_freezes_inputs_and_replays_without_configuration,
    test_session_key_renewal_uses_current_explicit_owner,
    test_renewal_rejects_changed_model_profile,
)

ORIGIN = "http://127.0.0.1:3000"
KEY = "DUMMY-incoming-private-key-123456"
OLD_KEY = "DUMMY-existing-private-key-123456"
BODY = {"provider": "openai", "model": "inert-model", "api_key": OLD_KEY}


def escaped(value):
    return ''.join(f"\\x{ord(char):02x}" for char in value)


def login(client):
    session = client.post("/api/sessions", json={}, headers={"Origin": ORIGIN}).json()
    return session, {"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(generation, "configuration", lambda: None)
    monkeypatch.setattr(graph_access, "configuration", lambda: None)
    monkeypatch.setattr(generation, "generate", lambda *a, **k: pytest.fail("Unexpected provider invocation"))
    def unavailable(_state):
        raise RuntimeError("Metadata-only profile has no renderer")
    monkeypatch.setattr(editor_execution, "make_snapshot_service", unavailable)


@pytest.mark.parametrize("marker", [KEY, OLD_KEY], ids=["incoming", "current"])
@pytest.mark.parametrize("ttl_minutes", [30, None])
def test_settings_rejects_escaped_metadata_before_replacing_live_authority(tmp_path, monkeypatch, marker, ttl_minutes):
    app = create_app(tmp_path, start_paused=True, clock=lambda: 1000.0)
    with TestClient(app, base_url=ORIGIN) as client:
        session, headers = login(client)
        saved = client.put("/api/model-settings", headers=headers, json={**BODY, "ttl_minutes": ttl_minutes})
        assert saved.status_code == 200, saved.text
        auth = app.state.workflow_authorization
        auth.capture(session, "existing-operation", credential_ref=saved.json()["credential_ref"], retrieval=False)
        records = deepcopy(app.state.model_settings._records)
        grants = deepcopy(auth.grants._records)
        journal = list(app.state.journal.db.iterdump())
        calls = []
        invalidate = app.state.model_settings.on_invalidate
        def tracked(owner):
            calls.append(owner)
            invalidate(owner)
        monkeypatch.setattr(app.state.model_settings, "on_invalidate", tracked)
        rejected = client.put("/api/model-settings", headers=headers, json={
            **BODY, "api_key": KEY, "model": escaped(marker), "ttl_minutes": ttl_minutes,
        })
        assert rejected.status_code == 422, rejected.text
        assert rejected.json() == {"detail": "Invalid request input"}
        assert calls == []
        assert app.state.model_settings._records == records
        assert auth.grants._records == grants
        assert list(app.state.journal.db.iterdump()) == journal
        assert client.get("/api/model-settings").json() == saved.json()


@pytest.mark.parametrize("source", ["legacy-session", "server"])
@pytest.mark.parametrize("encoding", ["literal", "hex", "folded", "nested-key"])
def test_settings_readback_rejects_unsafe_metadata_without_rewriting_or_retaining_keys(
    tmp_path, monkeypatch, source, encoding,
):
    model = {
        "literal": OLD_KEY,
        "hex": escaped(OLD_KEY),
        "folded": '"DUMMY-existing-' + chr(92) + '\n  private-key-123456"',
        "nested-key": '"' + escaped(OLD_KEY) + '": inert',
    }[encoding]
    app = create_app(tmp_path, start_paused=True, clock=lambda: 1000.0)
    with TestClient(app, base_url=ORIGIN) as client:
        session, headers = login(client)
        if source == "legacy-session":
            assert client.put("/api/model-settings", headers=headers, json=BODY).status_code == 200
            # Explicit legacy in-memory fixture, never an accepted unsafe Settings PUT.
            app.state.model_settings._records[session["session_id"]]["model"] = model
        else:
            monkeypatch.setattr(generation, "configuration", lambda: {
                **BODY, "model": model, "base_url": "https://api.openai.com/v1",
            })
        before = deepcopy(app.state.model_settings._records)
        journal = list(app.state.journal.db.iterdump())
        response = client.get("/api/model-settings")
        assert response.status_code == 422, response.text
        assert response.json() == {"detail": "Invalid request input"}
        assert app.state.model_settings._records == before
        assert list(app.state.journal.db.iterdump()) == journal
        monkeypatch.setattr(generation, "configuration", lambda: None)
        assert client.delete("/api/model-settings", headers=headers).status_code == 200
        assert client.get("/api/model-settings").json()["source"] == "none"
        # Removed keys are not a persistent denylist; clean replacement remains usable.
        replacement = client.put("/api/model-settings", headers=headers, json={
            **BODY, "api_key": KEY, "model": escaped(OLD_KEY),
        })
        assert replacement.status_code == 200, replacement.text


@pytest.mark.parametrize("entry", ["default-capture", "noop-hook-capture", "http-renewal"])
@pytest.mark.parametrize("target", ["session-model", "server-model", "server-principal", "retrieval-user"])
def test_every_capture_screens_all_public_profiles_before_first_grant(tmp_path, monkeypatch, entry, target):
    model = {**BODY, "base_url": "https://api.openai.com/v1", "principal": "inert-principal"}
    graph = {"uri": "bolt://synthetic.invalid:7687", "user": "reader", "database": "synthetic",
             "password": KEY}
    monkeypatch.setattr(generation, "configuration", lambda: dict(model))
    monkeypatch.setattr(graph_access, "configuration", lambda: dict(graph))
    app = create_app(tmp_path, start_paused=True, clock=lambda: 1000.0)
    with TestClient(app, base_url=ORIGIN) as client:
        session, headers = login(client)
        ref = None
        if target == "session-model":
            saved = client.put("/api/model-settings", headers=headers, json=BODY)
            assert saved.status_code == 200, saved.text
            ref = saved.json()["credential_ref"]
        auth = app.state.workflow_authorization
        journal = app.state.journal
        if entry == "http-renewal":
            payload = {"operation": "new", "retrieval_policy": "require_service", "prompt": "No execution",
                       "idempotency_key": "metadata:original", **({"credential_ref": ref} if ref else {})}
            accepted = client.post("/api/editor/generate", headers=headers, json=payload)
            assert accepted.status_code == 202, accepted.text
            job = accepted.json()
            journal.resume_queue()
            attempt = journal.claim_attempt(job["id"])
            assert journal.block_attempt_authorization(job["id"], **attempt)
        if target == "session-model":
            # Explicit legacy in-memory state; current HTTP admission rejects this.
            app.state.model_settings._records[session["session_id"]]["model"] = escaped(OLD_KEY)
        elif target.startswith("server-"):
            model[target.removeprefix("server-")] = escaped(OLD_KEY)
        else:
            graph["user"] = escaped(KEY)
        before = deepcopy(auth.grants._records)
        durable = list(journal.db.iterdump())
        calls = []
        original_issue = auth.grants.issue
        def issue(*args, **kwargs):
            calls.append("issue:" + args[2])
            return original_issue(*args, **kwargs)
        monkeypatch.setattr(auth.grants, "issue", issue)
        monkeypatch.setattr(app.state.supervisor.wake, "set", lambda: calls.append("wake"))
        if entry == "http-renewal":
            response = client.post(f'/api/editor/generations/{job["id"]}/reauthorize', headers=headers, json={
                "idempotency_key": "metadata:renewal", **({"credential_ref": ref} if ref else {}),
            })
            assert response.status_code == 422, response.text
            assert response.json() == {"detail": "Invalid request input"}
        else:
            kwargs = {"protect_public": lambda value: None} if entry == "noop-hook-capture" else {}
            with pytest.raises(HTTPException) as error:
                auth.capture(session, "direct-operation", credential_ref=ref, retrieval=True, **kwargs)
            assert error.value.status_code == 422
            assert error.value.detail == "Invalid request input"
        assert calls == []
        assert auth.grants._records == before
        assert list(journal.db.iterdump()) == durable


@pytest.mark.parametrize("hook", ["noop", "rewrite", "reject"])
def test_additional_capture_guard_cannot_rewrite_profile_or_inspect_private_config(tmp_path, monkeypatch, hook):
    model = {**BODY, "base_url": "https://api.openai.com/v1"}
    monkeypatch.setattr(generation, "configuration", lambda: dict(model))
    app = create_app(tmp_path, start_paused=True, clock=lambda: 1000.0)
    with TestClient(app, base_url=ORIGIN) as client:
        session, _ = login(client)
        auth = app.state.workflow_authorization
        seen = []
        def additional(public):
            seen.append(deepcopy(public))
            assert "api_key" not in public["model"]
            assert OLD_KEY not in str(public)
            if hook == "rewrite":
                public["model"]["model"] = escaped(OLD_KEY)
            elif hook == "reject":
                raise HTTPException(422, "Additional policy refused")
        if hook == "reject":
            with pytest.raises(HTTPException, match="Additional policy refused"):
                auth.capture(session, "callback-operation", retrieval=False, protect_public=additional)
            assert not auth.grants._records
        else:
            grants = auth.capture(session, "callback-operation", retrieval=False, protect_public=additional)
            assert grants["model"]["profile"]["model"] == BODY["model"]
            assert auth.grants.resolve(session["session_id"], grants["model"]["grant_id"],
                                       "callback-operation", "model") == model
        assert len(seen) == 1


def test_shared_request_wrappers_preserve_return_contracts(tmp_path):
    from fastapi import Request
    from isaaclab_arena_examples.agentic_environment_generation.web_api import editor, public_records

    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN):
        request = Request({"type": "http", "app": app})
        text = "metadata: inert\n"
        assert public_records.protect_yaml(request, text) is None
        assert editor.protect_yaml(request, text) is None
        record = {"nested": [text]}
        assert public_records.protect_public_record(request, record) is record
        assert public_records.screen_public_record(record, app.state.model_settings.protect_public) is record


def test_metadata_suite_selection_is_explicit_only_and_does_not_expand_defaults():
    from backend_checks import core_only, selection

    path = "isaaclab_arena_examples/tests/test_workbench_metadata_protection.py"
    assert selection([]) == [
        "isaaclab_arena/tests/test_workbench_editor_revisions.py",
        "isaaclab_arena_examples/tests/test_workbench_editor_revision_api.py",
    ]
    assert selection([path]) == [path]
    assert not core_only([path])
    for invalid in ([path, path], [path + "::test_example"], ["-k"], ["--collect-only"],
                    ["isaaclab_arena_examples/tests/test_workbench_unapproved_models.py"]):
        with pytest.raises(ValueError, match="Only unique approved"):
            selection(invalid)
