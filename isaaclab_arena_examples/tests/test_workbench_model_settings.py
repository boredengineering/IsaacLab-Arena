# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Temporary credentials: real HTTP boundaries, dummy secrets, no inference."""

import copy
import json

import pytest
from fastapi.testclient import TestClient

from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app, generation
from isaaclab_arena_examples.tests.test_workbench_editor import ORIGIN, login

KEY = "dummy-private-provider-marker-123456"
BODY = {"provider": "openai", "model": "explicit-test-model", "api_key": KEY}

PROFILE = {
    "provider": "openrouter", "model": "literal/provider/model:preview",
    "request_policy": {
        "api": "chat_completions", "temperature_mode": "omitted",
        "token_limit_parameter": "max_completion_tokens", "structured_output": "json_object",
        "multimodal_output": "omitted", "store": None,
    },
}


def test_create_profile_is_authenticated_immutable_persistent_and_not_activation(tmp_path):
    app = create_app(tmp_path, start_paused=True)
    route = "/api/model-settings/profiles/my-model"
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.put(route, json=PROFILE).status_code == 401
        headers = login(client)
        assert client.put(route, json=PROFILE).status_code == 403
        before = client.get("/api/model-settings").json()
        response = client.put(route, headers=headers, json=PROFILE)
        assert response.status_code == 200
        profile = response.json()
        assert profile == dict(PROFILE, id="my-model", revision=1, origin="user_defined",
                               support="unverified", verification="not_checked",
                               endpoint="https://openrouter.ai/api/v1", documentation_urls=[])
        assert client.put(route, headers=headers, json=PROFILE).json() == profile
        assert client.put(route, headers=headers, json=dict(PROFILE, model="different")).status_code == 409
        after = client.get("/api/model-settings").json()
        assert after["profile_creation"] == "create-only/v1"
        assert profile in after["profiles"]
        assert after["configured"] == before["configured"] is False
        assert app.state.model_settings._records == {}
        assert client.get("/api/jobs").json()["jobs"] == []
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        login(client)
        assert profile in client.get("/api/model-settings").json()["profiles"]


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import editor_execution, graph_access

    monkeypatch.setattr(generation, "configuration", lambda: None)
    monkeypatch.setattr(graph_access, "configuration", lambda: None)

    def unavailable(_state):
        raise RuntimeError("Metadata-only profile has no renderer")

    monkeypatch.setattr(editor_execution, "make_snapshot_service", unavailable)
    monkeypatch.setattr(generation, "generate", lambda *a, **k: pytest.fail("Unexpected provider invocation"))


def test_selected_profile_freezes_policy_through_authorization_and_checked_config(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import checked_config
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        profile = client.put("/api/model-settings/profiles/my-model", headers=headers, json=PROFILE).json()
        saved = client.put("/api/model-settings", headers=headers,
                           json=dict(BODY, provider=PROFILE["provider"], model=PROFILE["model"], profile_id="my-model"))
        assert saved.status_code == 200
        metadata = saved.json()
        assert metadata["effective_profile"]["id"] == "my-model"
        assert metadata["effective_profile"]["support"] == "unverified"
        owner = next(iter(app.state.model_settings._records))
        session = app.state.sessions.get_by_id(owner)
        config = app.state.model_settings.resolve(owner, metadata["credential_ref"])
        assert config["inference_profile"] == profile
        auth = app.state.workflow_authorization
        grant = auth.capture(session, "synthetic-operation", credential_ref=metadata["credential_ref"], retrieval=False)
        assert grant["model"]["profile"]["inference_profile"] == profile
        private = auth.grants.resolve(owner, grant["model"]["grant_id"], "synthetic-operation", "model")
        assert checked_config(private)["inference_profile"] == profile
        config["inference_profile"]["request_policy"]["store"] = False
        assert auth.grants.resolve(owner, grant["model"]["grant_id"], "synthetic-operation", "model") == private
        auth.protect_public(profile)
        # Real secrets and policy-shaped dictionaries at other paths remain private.
        from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants
        grants = ExecutionGrants(clock=lambda: 100)
        with pytest.raises(ValueError):
            grants.issue("o", "j", "model", {"other": {"token_limit_parameter": "max_tokens"}}, {}, 200)
        with pytest.raises(ValueError):
            grants.issue("o", "j", "model", {"model": "hidden-marker"}, {"other": {"request_policy": "hidden-marker"}}, 200)


def test_builtin_server_policy_is_frozen_in_immutable_job(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.inference_profiles import frozen_builtin_profile, inference_profile_catalogue
    config = {"api_key": KEY, "provider": "openai", "model": "gpt-6-astra", "base_url": "https://api.openai.com/v1", "trusted_server": True}
    monkeypatch.setattr(generation, "configuration", lambda: copy.deepcopy(config))
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        body = {"operation": "new", "prompt": "Synthetic request, never dispatch", "idempotency_key": "freeze-builtin"}
        response = client.post("/api/editor/generate", headers=headers, json=body)
        assert response.status_code == 202
        job = response.json()
        expected = frozen_builtin_profile(inference_profile_catalogue()[1])
        assert job["inputs"]["workflow_authorization"]["model"]["profile"]["inference_profile"] == expected
        assert app.state.workflow_authorization.resolve(job)["config"]["inference_profile"] == expected
        assert client.get('/api/jobs/' + job['id']).json() == job


def test_worker_admits_frozen_policy_to_generation_boundary(monkeypatch):
    import io
    import sys
    from types import SimpleNamespace
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation_worker
    from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import checked_config
    profile = dict(PROFILE, id="manual", revision=1, origin="user_defined", support="unverified",
                   verification="not_checked", endpoint="https://openrouter.ai/api/v1", documentation_urls=[])
    config = {"api_key": KEY, "model": PROFILE["model"], "base_url": profile["endpoint"], "inference_profile": profile}
    envelope = {"inputs": {"operation": "refine", "execution_catalogue_sha256": "a" * 64}, "config": config, "graph_config": None}
    monkeypatch.setattr(sys, "argv", ["worker", "--parent-pid", "123"])
    monkeypatch.setattr(generation_worker.os, "getppid", lambda: 123)
    monkeypatch.setattr(generation_worker.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(prctl=lambda *a: 0))
    observed = []
    def synthetic_generate(inputs, emit, *, config, **kwargs):
        observed.append(checked_config(config))
        return {"synthetic_boundary": True}
    monkeypatch.setattr(generation, "generate", synthetic_generate)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(envelope).encode() + b"\n")))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    assert generation_worker.main() == 0
    assert observed[0]["inference_profile"] == profile
    assert json.loads(output.getvalue()) == {"result": {"synthetic_boundary": True}}


@pytest.mark.parametrize("identity,change", [
    ("a" * 65, {}), ("-bad", {}), ("openai-gpt-4.1", {}), ("custom", {}),
    ("manual", {"api_key": KEY}), ("manual", {"endpoint": "https://elsewhere.invalid"}),
    ("manual", {"model": "x" * 257}), ("manual", {"model": "literal\n"}),
    ("manual", {"provider": "unknown"}), ("manual", {"revision": 1}),
    ("manual", {"request_policy": dict(PROFILE["request_policy"], store=True)}),
    ("manual", {"request_policy": dict(PROFILE["request_policy"], store=0)}),
    ("manual", {"request_policy": dict(PROFILE["request_policy"], temperature=0.2)}),
])
def test_registration_rejects_invalid_exact_shape_before_persistence(tmp_path, identity, change):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        response = client.put('/api/model-settings/profiles/' + identity, headers=headers, json=dict(PROFILE, **change))
        assert response.status_code == 422
        assert app.state.model_settings.profiles.catalogue() == []


def test_registration_and_incoming_key_screen_whole_catalogue_before_writes(tmp_path):
    app = create_app(tmp_path, start_paused=True)
    marker = 'synthetic-persistent-model-marker'
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        assert client.put('/api/model-settings', headers=headers, json=BODY).status_code == 200
        before = copy.deepcopy(app.state.model_settings._records)
        for literal in (KEY, '"' + ''.join('\\x%02x' % ord(c) for c in KEY) + '"'):
            rejected = client.put('/api/model-settings/profiles/protected', headers=headers, json=dict(PROFILE, model=literal))
            assert rejected.status_code == 422
            assert app.state.model_settings.profiles.catalogue() == []
        assert client.put('/api/model-settings/profiles/public-marker', headers=headers, json=dict(PROFILE, model=marker)).status_code == 200
        assert client.put('/api/model-settings', headers=headers, json=dict(BODY, api_key=marker)).status_code == 422
        assert app.state.model_settings._records == before


def test_profile_registration_rejects_duplicate_json_keys_before_insertion(tmp_path):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client) | {"Content-Type": "application/json"}
        raw = '{"model":"discarded",' + json.dumps(PROFILE)[1:]
        response = client.put('/api/model-settings/profiles/duplicate', headers=headers, content=raw)
        assert response.status_code == 422
        assert app.state.model_settings.profiles.catalogue() == []


def test_profile_capacity_is_bounded_without_blocking_identical_replay(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.model_profile_store import ModelProfileConflict
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        first = client.put('/api/model-settings/profiles/first', headers=headers, json=PROFILE).json()
        store = app.state.model_settings.profiles
        for index in range(63):
            store.create(dict(first, id='profile-' + str(index)), app.state.model_settings.protect_public)
        assert len(store.catalogue()) == 64
        assert store.create(first, app.state.model_settings.protect_public) == first
        with pytest.raises(ModelProfileConflict):
            store.create(dict(first, id='overflow'), app.state.model_settings.protect_public)
        assert client.put('/api/model-settings/profiles/overflow', headers=headers, json=PROFILE).status_code == 409
        assert client.put('/api/model-settings/profiles/first', headers=headers, json=PROFILE).status_code == 200


def test_user_profile_does_not_inherit_documented_provider_readiness(monkeypatch):
    import httpx
    from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_readiness import probe_provider
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: pytest.fail("Unverified profile attempted metadata transport"))
    profile = dict(PROFILE, provider="openai", model="gpt-4.1", id="custom-openai", revision=1,
                   origin="user_defined", support="unverified", verification="not_checked",
                   endpoint="https://api.openai.com/v1", documentation_urls=[])
    config = {"api_key": KEY, "model": profile["model"], "base_url": profile["endpoint"],
              "provider": "openai", "inference_profile": profile}
    assert probe_provider(config) == "generation_provider_unsupported"


def test_user_policy_is_immutable_in_job_and_renewal_cannot_substitute_policy(tmp_path):
    from isaaclab_arena_examples.tests.test_workbench_reauthorization import block
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        original = client.put('/api/model-settings/profiles/original', headers=headers, json=PROFILE).json()
        changed = dict(PROFILE, request_policy=dict(PROFILE["request_policy"], temperature_mode="configured"))
        assert client.put('/api/model-settings/profiles/changed', headers=headers, json=changed).status_code == 200
        settings = dict(BODY, provider=PROFILE["provider"], model=PROFILE["model"], profile_id="original")
        saved = client.put('/api/model-settings', headers=headers, json=settings).json()
        body = {"operation": "new", "prompt": "Synthetic profile freeze", "idempotency_key": "frozen-user-policy", "credential_ref": saved["credential_ref"]}
        response = client.post('/api/editor/generate', headers=headers, json=body)
        assert response.status_code == 202
        job = response.json()
        assert job["inputs"]["workflow_authorization"]["model"]["profile"]["inference_profile"] == original
        assert app.state.workflow_authorization.resolve(job)["config"]["inference_profile"] == original
        assert client.get('/api/jobs/' + job['id']).json() == job
        block(app, job)
        replacement = client.put('/api/model-settings', headers=headers, json=dict(settings, profile_id="changed")).json()
        owner = job["created_by_session_id"]
        session = app.state.sessions.get_by_id(owner)
        with pytest.raises(ValueError, match="Renewal profile changed"):
            app.state.workflow_authorization.capture_renewal(session, app.state.journal.get_job(job["id"]), credential_ref=replacement["credential_ref"])
        assert app.state.journal.get_job(job["id"])["inputs"] == job["inputs"]


def test_profile_store_itself_rejects_secret_shaped_or_builtin_records(tmp_path):
    from isaaclab_arena.agentic_environment_generation.inference_profiles import frozen_builtin_profile, inference_profile_catalogue
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN):
        store = app.state.model_settings.profiles
        for record in ({"id": "bad", "api_key": KEY}, frozen_builtin_profile(inference_profile_catalogue()[0])):
            with pytest.raises(ValueError):
                store.create(record, lambda value: None)
        assert store.catalogue() == []


def test_documented_profile_catalogue_is_available_without_configuration(tmp_path):
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        login(client)
        response = client.get("/api/model-settings")
        assert response.status_code == 200
        public = response.json()
        assert public["profile_catalogue_version"] == "harness-model-profiles/v2"
        assert public["effective_profile"] is None
        assert public["profiles"] == [
            {
                "id": "openai-" + model,
                "revision": 1,
                "provider": "openai",
                "model": model,
                "endpoint": "https://api.openai.com/v1",
                "support": "documented",
                "origin": "builtin",
                "verification": "not_checked",
                "documentation_urls": urls,
                "request_policy": {
                    "api": "chat_completions",
                    "structured_output": "json_schema",
                    "multimodal_output": "json_object",
                    "temperature_mode": temperature,
                    "token_limit_parameter": tokens,
                    "store": store,
                },
            }
            for model, urls, temperature, tokens, store in [
                (
                    "gpt-4.1",
                    ["https://developers.openai.com/api/docs/models/gpt-4.1"],
                    "configured",
                    "max_tokens",
                    None,
                ),
                (
                    "gpt-6-astra",
                    [
                        "https://developers.openai.com/api/docs/models/gpt-6-astra",
                        "https://developers.openai.com/api/docs/guides/latest-model",
                    ],
                    "omitted",
                    "max_completion_tokens",
                    False,
                ),
            ]
        ]
        assert client.get("/api/jobs").json()["jobs"] == []


@pytest.mark.parametrize(
    "provider, model, expected",
    [
        ("openai", "gpt-4.1", "openai-gpt-4.1"),
        ("openai", "gpt-6-astra", "openai-gpt-6-astra"),
        ("openai", "gpt-6-astra-latest", None),
        ("gemini", "gpt-6-astra", None),
        ("openrouter", "gpt-4.1", None),
        ("nvidia", "gpt-6-astra", None),
    ],
)
def test_effective_profile_preserves_actual_session_identity(tmp_path, provider, model, expected):
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        headers = login(client)
        response = client.put(
            "/api/model-settings", headers=headers, json={**BODY, "provider": provider, "model": model}
        )
        assert response.status_code == 200
        public = response.json()
        assert public["effective_profile"] == {
            "id": expected,
            "support": "documented" if expected else "unverified",
            "verification": "not_checked",
        }
        assert (public["provider"], public["model"]) == (provider, model)
        assert client.get("/api/model-settings").json() == public
        assert client.get("/api/jobs").json()["jobs"] == []


@pytest.mark.parametrize(
    "marker",
    [
        "profile_catalogue_version",
        "effective_profile",
        "documentation_urls",
        "token_limit_parameter",
        "temperature_mode",
        "max_completion_tokens",
        "harness-model-profiles/v2",
        "openai-gpt-6-astra",
        "https://developers.openai.com/api/docs/models/gpt-4.1",
    ],
)
def test_profile_secret_collision_rejected_before_replacement(tmp_path, marker):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        saved = client.put("/api/model-settings", headers=headers, json=BODY).json()
        before = copy.deepcopy(app.state.model_settings._records)
        response = client.put("/api/model-settings", headers=headers, json={**BODY, "api_key": marker})
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert app.state.model_settings._records == before
        assert client.get("/api/model-settings").json() == saved


@pytest.mark.parametrize("encoding", ["literal", "escaped"])
def test_new_profile_projection_screened_against_active_keys_before_replacement(tmp_path, monkeypatch, encoding):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import model_settings

    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        assert client.put("/api/model-settings", headers=headers, json=BODY).status_code == 200
        before = copy.deepcopy(app.state.model_settings._records)
        catalogue = model_settings.inference_profile_catalogue()
        marker = KEY if encoding == "literal" else '"' + "".join("\\x%02x" % ord(c) for c in KEY) + '"'
        catalogue[0]["documentation_urls"].append(marker)
        monkeypatch.setattr(model_settings, "inference_profile_catalogue", lambda: copy.deepcopy(catalogue))
        invalidated = []
        app.state.model_settings.on_invalidate = invalidated.append
        response = client.put("/api/model-settings", headers=headers, json={**BODY, "api_key": KEY + "-replacement"})
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert app.state.model_settings._records == before
        assert invalidated == []
        read = client.get("/api/model-settings")
        assert read.status_code == 422
        assert KEY not in read.text
        assert app.state.model_settings._records == before


def test_status_records_are_detached_and_reads_do_not_mutate_credentials():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.model_settings import (
        ModelSettings,
        SettingsInput,
    )

    settings = ModelSettings(clock=lambda: 1000.0)
    session = {"session_id": "synthetic-session", "expires_at": 10000.0}
    settings.save(session, SettingsInput(**BODY, ttl_minutes=None))
    before = copy.deepcopy(settings._records)
    original = copy.deepcopy(settings.status(session, True))
    changed = settings.status(session, True)
    changed["profiles"][0]["documentation_urls"].append("mutated")
    changed["profiles"][0]["request_policy"]["store"] = True
    changed["effective_profile"]["verification"] = "mutated"
    provider = changed["providers"][0]
    old_label = provider["label"]
    try:
        provider["label"] = "mutated"
        assert settings.status(session, True) == original
        assert settings._records == before
    finally:
        provider["label"] = old_label


@pytest.mark.parametrize(
    "model, endpoint, expected",
    [
        ("gpt-6-astra", "https://api.openai.com/v1/", "openai-gpt-6-astra"),
        ("gpt-4.1", "https://api.openai.com/v1", "openai-gpt-4.1"),
        ("gpt-6-astra", "https://private-operator.invalid/secret-path", None),
        ("gpt-4.1", "https://api.openai.com/v1?private=operator", None),
        ("gpt-4.1-custom", "https://api.openai.com/v1", None),
    ],
)
def test_server_profile_uses_actual_endpoint_without_exposing_override(
    tmp_path, monkeypatch, model, endpoint, expected
):
    server = {**BODY, "model": model, "base_url": endpoint, "trusted_server": True}
    monkeypatch.setattr(generation, "configuration", lambda: server)
    before = copy.deepcopy(server)
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        response = client.get("/api/model-settings")
        public = response.json()
        assert public["source"] == "server"
        assert public["model"] == model
        assert public["provider"] == "openai"
        assert public["effective_profile"] == {
            "id": expected,
            "support": "documented" if expected else "unverified",
            "verification": "not_checked",
        }
        assert "base_url" not in public and "endpoint" not in public["effective_profile"]
        if "private" in endpoint:
            assert endpoint not in response.text
        assert KEY not in response.text
        assert server == before
        assert app.state.model_settings._records == {}
        saved = client.put("/api/model-settings", headers=headers, json={**BODY, "model": "gpt-4.1"})
        assert saved.json()["effective_profile"]["id"] == "openai-gpt-4.1"
        assert client.delete("/api/model-settings", headers=headers).json() == public
        assert client.get("/api/jobs").json()["jobs"] == []


@pytest.mark.parametrize("ttl_minutes", [30, None])
def test_settings_authenticated_save_and_forget_never_persist_key(tmp_path, ttl_minutes):
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/model-settings").status_code == 401
        headers = login(client)
        empty = client.get("/api/model-settings").json()
        assert empty["source"] == "none"
        assert empty["session_keys_allowed"] is True
        assert {p["id"] for p in empty["providers"]} == {"openai", "gemini", "openrouter", "nvidia"}
        assert client.put("/api/model-settings", json=BODY).status_code == 403
        saved = client.put("/api/model-settings", headers=headers, json={**BODY, "ttl_minutes": ttl_minutes})
        assert saved.status_code == 200, saved.text
        status = saved.json()
        assert status == {
            **empty,
            "source": "session",
            "configured": True,
            "effective_profile": {"id": None, "support": "unverified", "verification": "not_checked"},
            "provider": "openai",
            "model": BODY["model"],
            "expires_at": status["expires_at"],
            "credential_ref": status["credential_ref"],
            "key_timer_disabled": ttl_minutes is None,
        }
        assert status["credential_ref"]
        assert KEY not in saved.text
        assert client.get("/api/model-settings").json() == status
        assert client.delete("/api/model-settings", headers=headers).json() == empty
        assert client.get("/api/jobs").json()["jobs"] == []
    assert all(KEY.encode() not in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": KEY},
        {"model": KEY},
        {"model": "prefix/" + KEY},
        {"model": " "},
        {"model": "x" * 257},
        {"api_key": " "},
        {"api_key": "x\ny"},
        {"api_key": "x" * 4097},
        {"base_url": "https://attacker.invalid/"},
        {"api_key": 123},
        {"model": "x\n"},
        {"api_key": "https://api.openai.com/v1"},
        {"api_key": "credential_ref"},
        {"api_key": "session_keys_allowed"},
        {"api_key": "key_timer_disabled"},
    ],
)
def test_settings_invalid_inputs_have_generic_errors(tmp_path, changes):
    with TestClient(create_app(tmp_path), base_url=ORIGIN) as client:
        headers = login(client)
        result = client.put("/api/model-settings", headers=headers, json={**BODY, **changes})
        assert result.status_code == 422
        assert result.json() == {"detail": "Invalid request input"}
        assert client.get("/api/model-settings").json()["configured"] is False


@pytest.mark.parametrize(
    "origin, allowed",
    [
        ("http://operator.example:3000", False),
        ("https://operator.example", True),
        ("http://localhost:3000", True),
        ("http://[::1]:3000", True),
    ],
)
def test_settings_transport_uses_configured_origin_not_forwarded_headers(tmp_path, origin, allowed):
    # This runtime's Starlette TestClient cannot parse an IPv6 authority.
    base_url = ORIGIN if "[::1]" in origin else origin
    from urllib.parse import urlsplit

    with TestClient(
        create_app(tmp_path, origin=origin), base_url=base_url, headers={"Host": urlsplit(origin).netloc}
    ) as client:
        session = client.post("/api/sessions", headers={"Origin": origin}, json={}).json()
        headers = {"Origin": origin, "X-CSRF-Token": session["csrf_token"], "X-Forwarded-Proto": "https"}
        assert client.get("/api/model-settings").json()["session_keys_allowed"] is allowed
        assert client.put("/api/model-settings", headers=headers, json=BODY).status_code == (200 if allowed else 403)
        assert (
            client.put("/api/model-settings", headers={**headers, "Host": "evil.invalid"}, json=BODY).status_code == 403
        )
        assert (
            client.put(
                "/api/model-settings", headers={**headers, "Origin": "https://evil.invalid"}, json=BODY
            ).status_code
            == 403
        )


@pytest.mark.parametrize("ttl_minutes", [0, -1, 10, 121, 1440, "30", "never", 30.0, True])
def test_invalid_expiration_does_not_replace_existing_key(tmp_path, ttl_minutes):
    with TestClient(create_app(tmp_path), base_url=ORIGIN) as client:
        headers = login(client)
        saved = client.put("/api/model-settings", headers=headers, json=BODY).json()
        response = client.put("/api/model-settings", headers=headers, json={**BODY, "ttl_minutes": ttl_minutes})
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request input"}
        assert client.get("/api/model-settings").json() == saved


@pytest.mark.parametrize("ttl_minutes", [15, 30, 60, 120])
@pytest.mark.parametrize("idle_seconds", [86400, 300])
def test_selected_expiration_is_enforced_and_capped_by_session(tmp_path, ttl_minutes, idle_seconds):
    now = [1000.0]
    app = create_app(tmp_path, clock=lambda: now[0], idle_seconds=idle_seconds)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        response = client.put("/api/model-settings", headers=headers, json={**BODY, "ttl_minutes": ttl_minutes})
        assert response.status_code == 200, response.text
        saved = response.json()
        session_id = client.get("/api/session").json()["session_id"]
        deadline = 1000 + min(ttl_minutes * 60, idle_seconds)
        assert saved["expires_at"] == deadline
        now[0] = deadline - 1
        assert client.get("/api/model-settings").json()["expires_at"] == deadline
        now[0] = deadline
        with pytest.raises(ValueError, match="unavailable"):
            app.state.model_settings.resolve(session_id, saved["credential_ref"])
        assert not app.state.model_settings._records


def test_no_key_timer_follows_session_activity_but_not_polling(tmp_path):
    now = [1000.0]
    app = create_app(tmp_path, clock=lambda: now[0], idle_seconds=10000, absolute_seconds=30000)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        response = client.put("/api/model-settings", headers=headers, json={**BODY, "ttl_minutes": None})
        assert response.status_code == 200, response.text
        saved = response.json()
        session_id = client.get("/api/session").json()["session_id"]
        assert saved["key_timer_disabled"] is True
        assert saved["expires_at"] == 11000
        now[0] = 10999
        assert client.get("/api/model-settings").json() == saved
        assert client.post("/api/session/activity", headers=headers).json()["expires_at"] == 20999
        now[0] = 11001
        assert app.state.model_settings.resolve(session_id, saved["credential_ref"])["api_key"] == KEY
        assert client.get("/api/model-settings").json()["expires_at"] == 20999
        now[0] = 20998
        assert client.post("/api/session/activity", headers=headers).json()["expires_at"] == 30998
        now[0] = 30997
        assert client.post("/api/session/activity", headers=headers).json()["expires_at"] == 31000
        now[0] = 31000
        app.state.model_settings.purge()
        assert not app.state.model_settings._records
        assert client.get("/api/model-settings").status_code == 401
        with pytest.raises(ValueError, match="unavailable"):
            app.state.model_settings.resolve(session_id, saved["credential_ref"])


@pytest.mark.parametrize("cleanup_ttl", [30, None])
def test_credentials_expire_without_poll_extension_and_clear_on_revoke_shutdown_restart(tmp_path, cleanup_ttl):
    now = [1000.0]
    app = create_app(tmp_path, clock=lambda: now[0])
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        saved = client.put("/api/model-settings", headers=headers, json=BODY).json()
        assert saved["expires_at"] == 2800
        now[0] = 2799
        client.post("/api/session/activity", headers=headers)
        assert client.get("/api/model-settings").json() == saved
        now[0] = 2800
        assert client.get("/api/model-settings").json()["source"] == "none"
        assert not app.state.model_settings._records
        client.put("/api/model-settings", headers=headers, json={**BODY, "ttl_minutes": cleanup_ttl})
        client.delete("/api/session", headers=headers)
        assert not app.state.model_settings._records
        headers = login(client)
        client.put("/api/model-settings", headers=headers, json={**BODY, "ttl_minutes": cleanup_ttl})
        cookies = dict(client.cookies)
    assert not app.state.model_settings._records
    with TestClient(create_app(tmp_path, clock=lambda: now[0]), base_url=ORIGIN, cookies=cookies) as client:
        assert client.get("/api/model-settings").json()["source"] == "none"


@pytest.mark.parametrize("ttl_minutes", [30, None])
def test_capacity_and_session_deadline_bound_retention(tmp_path, monkeypatch, ttl_minutes):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import model_settings

    monkeypatch.setattr(model_settings, "MAX_CREDENTIALS", 1)
    now = [1000.0]
    app = create_app(tmp_path, clock=lambda: now[0], idle_seconds=60)
    with TestClient(app, base_url=ORIGIN) as client:
        first = login(client)
        saved = client.put("/api/model-settings", headers=first, json={**BODY, "ttl_minutes": ttl_minutes}).json()
        assert saved["expires_at"] == 1060
        client.cookies.clear()
        second = login(client)
        assert client.get("/api/model-settings").json()["source"] == "none"
        assert client.put("/api/model-settings", headers=second, json=BODY).status_code == 409
        now[0] = 1060
        app.state.model_settings.purge()
        assert not app.state.model_settings._records
        client.cookies.clear()
        third = login(client)
        assert client.put("/api/model-settings", headers=third, json=BODY).status_code == 200


@pytest.mark.parametrize("invalidate", ["replace", "forget", "expire", "revoke"])
@pytest.mark.parametrize("ttl_minutes", [30, None])
def test_session_generation_binds_reference_and_invalidated_queue_cannot_fallback(
    tmp_path, monkeypatch, invalidate, ttl_minutes
):
    import asyncio
    import time

    now = [1000.0]
    app = create_app(tmp_path, clock=lambda: now[0], start_paused=True)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *a, **k: pytest.fail("Invalid ref spawned a worker"))
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        saved = client.put("/api/model-settings", headers=headers, json={**BODY, "ttl_minutes": ttl_minutes}).json()
        assert client.get("/api/editor").json()["capabilities"]["generation"] is True
        body = {"prompt": "Move cube", "idempotency_key": "scoped-job", "credential_ref": saved["credential_ref"]}
        response = client.post("/api/editor/generate", headers=headers, json=body)
        assert response.status_code == 202, response.text
        job = response.json()
        assert job["inputs"]["credential_ref"] == saved["credential_ref"]
        assert job["inputs"]["provider"] == "openai"
        assert job["inputs"]["model"] == BODY["model"]
        assert KEY not in response.text
        assert client.post("/api/editor/generate", headers=headers, json=body).json()["id"] == job["id"]
        cookies = dict(client.cookies)
        client.cookies.clear()
        other_headers = login(client)
        assert client.get("/api/editor").json()["capabilities"]["generation"] is False
        assert (
            client.post(
                "/api/editor/generate", headers=other_headers, json={**body, "idempotency_key": "other"}
            ).status_code
            == 409
        )
        client.cookies.clear()
        client.cookies.update(cookies)
        if invalidate == "replace":
            replacement = client.put(
                "/api/model-settings", headers=headers, json={**BODY, "api_key": KEY + "-new"}
            ).json()
            assert replacement["credential_ref"] != saved["credential_ref"]
        elif invalidate == "forget":
            client.delete("/api/model-settings", headers=headers)
        elif invalidate == "expire":
            now[0] = saved["expires_at"]
            if ttl_minutes is None:
                client.cookies.clear()
                headers = login(client)
        else:
            client.delete("/api/session", headers=headers)
            client.cookies.clear()
            headers = login(client)
        monkeypatch.setattr(generation, "configuration", lambda: {"api_key": "dummy-server-key", "model": "server"})
        replay = client.post("/api/editor/generate", headers=headers, json=body)
        assert replay.status_code == 202, replay.text
        assert replay.json() == job
        conflict = client.post("/api/editor/generate", headers=headers, json={**body, "prompt": "Changed"})
        assert conflict.status_code == 409
        assert conflict.json() == {"detail": "Idempotency key already bound to different inputs"}
        assert (
            client.post(
                "/api/editor/generate", headers=headers, json={**body, "idempotency_key": "new-submission"}
            ).status_code
            == 409
        )
        assert len(client.get("/api/jobs").json()["jobs"]) == 1
        assert client.post("/api/jobs/resume-queue", headers=headers).status_code == 200
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = client.get(f"/api/jobs/{job['id']}").json()
            if current["status"] == "failed":
                break
            time.sleep(0.02)
        assert current["status"] == "failed"
        assert KEY not in json.dumps(current)
    assert all(KEY.encode() not in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


@pytest.mark.parametrize("status", ["queued", "succeeded", "failed", "cancelled", "indeterminate"])
def test_generation_replay_after_restart_is_workspace_wide_and_never_reauthorized(tmp_path, monkeypatch, status):
    import asyncio

    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *a, **k: pytest.fail("Replay spawned a worker"))
    app = create_app(tmp_path, start_paused=True)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        saved = client.put("/api/model-settings", headers=headers, json=BODY).json()
        body = {"prompt": "Original", "idempotency_key": "durable-replay", "credential_ref": saved["credential_ref"]}
        job = client.post("/api/editor/generate", headers=headers, json=body).json()
        if status != "queued":
            app.state.journal.transition(job["id"], status, status, status)
        original = app.state.journal.get_job(job["id"])
    app = create_app(tmp_path, start_paused=True, max_pending=0)
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        assert not app.state.model_settings._records
        event_count = app.state.journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        monkeypatch.setattr(app.state.model_settings, "resolve", lambda *a: pytest.fail("Replay authorized a key"))
        replay = client.post("/api/editor/generate", headers=headers, json=body)
        assert replay.status_code == 202, replay.text
        assert replay.json() == original
        for changes in ({"credential_ref": "0" * 64}, {"credential_ref": None}, {"prompt": "Changed"}):
            conflict = client.post("/api/editor/generate", headers=headers, json={**body, **changes})
            assert conflict.status_code == 409
            assert conflict.json() == {"detail": "Idempotency key already bound to different inputs"}
        assert app.state.journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == event_count
        assert len(client.get("/api/jobs").json()["jobs"]) == 1


def test_server_generation_replay_recovers_even_when_server_key_removed(tmp_path, monkeypatch):
    app = create_app(tmp_path, start_paused=True)
    monkeypatch.setattr(generation, "configuration", lambda: {"model": "server"})
    with TestClient(app, base_url=ORIGIN) as client:
        headers = login(client)
        body = {"prompt": "Original", "idempotency_key": "server-replay"}
        job = client.post("/api/editor/generate", headers=headers, json=body).json()
        monkeypatch.setattr(generation, "configuration", lambda: None)
        assert client.post("/api/editor/generate", headers=headers, json=body).json() == job
        assert (
            client.post(
                "/api/editor/generate", headers=headers, json={**body, "idempotency_key": "new-server-job"}
            ).status_code
            == 503
        )


def test_generation_rejects_credentials_in_prompt_or_metadata_before_journaling(tmp_path):
    with TestClient(create_app(tmp_path, start_paused=True), base_url=ORIGIN) as client:
        headers = login(client)
        status = client.put("/api/model-settings", headers=headers, json=BODY).json()
        body = {"prompt": KEY, "idempotency_key": "no-key-in-prompt", "credential_ref": status["credential_ref"]}
        response = client.post("/api/editor/generate", headers=headers, json=body)
        assert response.status_code == 422
        assert KEY not in response.text
        assert client.get("/api/jobs").json()["jobs"] == []
        response = client.put(
            "/api/model-settings", headers=headers, json={**BODY, "api_key": KEY + "-new", "model": KEY}
        )
        assert response.status_code == 422
        assert KEY not in response.text
    assert all(KEY.encode() not in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
