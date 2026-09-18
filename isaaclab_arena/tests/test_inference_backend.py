# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :mod:`isaaclab_arena.agentic_environment_generation.inference_backend`."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from isaaclab_arena.agentic_environment_generation.inference_backend import (
    DEFAULT_BASE_URL,
    InferenceBackend,
    StructuredOutputRequest,
)
from isaaclab_arena.tests.utils import agentic_environment_generation as generation_test_utils
from isaaclab_arena.tests.utils.agentic_environment_generation import chat_response, inference_backend

# Explicit fixture registration for isolated --noconftest runs.
stub_openai = generation_test_utils.stub_openai


@pytest.fixture(autouse=True)
def deny_network_and_ambient_configuration(monkeypatch):
    """Install denial before constructors; never load credential files in units."""
    import socket

    from isaaclab_arena.agentic_environment_generation import inference_backend as module

    def denied(*args, **kwargs):
        pytest.fail("Network access is forbidden in inference units")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(module, "_load_dotenv_if_present", lambda: None)
    for prefix in ("OPENAI", "GEMINI", "OPENROUTER", "NV"):
        for suffix in ("API_KEY", "MODEL", "BASE_URL"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    monkeypatch.delenv("BASE_URL", raising=False)


@pytest.fixture
def sdk_transport(monkeypatch):
    """Real installed SDK serialization; synthetic responses are unit evidence only."""
    import importlib

    import openai._base_client
    from openai import DefaultHttpxClient

    # SDK platform metadata may invoke distro's lsb_release subprocess. This
    # transport-only unit fixes that header, not SDK serialization or responses.
    monkeypatch.setattr(openai._base_client, "get_platform", lambda: "Linux")
    with DefaultHttpxClient(trust_env=False) as client:
        transport_type = type(client._transport)
    httpx = importlib.import_module(transport_type.__module__.split(".")[0])
    requests = []
    statuses = []

    def synthetic_response(transport, request):
        requests.append(request)
        status = statuses.pop(0) if statuses else 200
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "synthetic unit rejection"}}, request=request)
        return httpx.Response(
            200,
            json={
                "id": "synthetic-unit-only",
                "object": "chat.completion",
                "created": 0,
                "model": json.loads(request.content)["model"],
                "choices": [{
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": '{"unit_evidence": true}',
                    },
                }],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
            request=request,
        )

    monkeypatch.setattr(transport_type, "handle_request", synthetic_response)
    return requests, statuses


def _request() -> StructuredOutputRequest:
    return StructuredOutputRequest(
        schema_name="TestSchema",
        schema={"type": "object", "properties": {}},
        system="system",
        user="user",
        retry_label="test",
    )


@pytest.mark.parametrize("text", ['{"count":1,"count":2}', '```json\n{"count":1}\n```', '{"count":"1"}', '{"count":1,"extra":true}'])
def test_user_profile_run_json_preserves_raw_keys_and_validates_schema(stub_openai, text):
    profile = {"id": "strict-user", "revision": 1, "provider": "openrouter", "model": "literal",
        "endpoint": "https://openrouter.ai/api/v1", "origin": "user_defined", "support": "unverified",
        "verification": "not_checked", "documentation_urls": [], "request_policy": {
            "api": "chat_completions", "temperature_mode": "omitted", "token_limit_parameter": "max_tokens",
            "structured_output": "omitted", "multimodal_output": "omitted", "store": None}}
    stub_openai[1].base_url = profile["endpoint"]
    backend = InferenceBackend(api_key="dummy-explicit-key", model="literal", base_url=profile["endpoint"],
                               inference_profile=profile, max_retries=0, load_dotenv=False)
    backend.client.chat.completions.create.return_value = chat_response(content=text)
    request = StructuredOutputRequest(schema_name="Count", schema={"type": "object", "properties": {
        "count": {"type": "integer"}}, "required": ["count"], "additionalProperties": False},
        system="system", user="user", retry_label="strict")
    with pytest.raises(RuntimeError):
        backend.run_json(request)


class TestAstraWireCompatibility:
    @pytest.mark.parametrize("max_tokens", [4, 123])
    @pytest.mark.parametrize("mode", ["json_schema", "json_object", "omitted"])
    @pytest.mark.parametrize("temperature_mode,tokens,store,multimodal", [
        ("omitted", "max_completion_tokens", None, "omitted"),
        ("configured", "max_tokens", False, "json_object"),
    ])
    def test_explicit_profile_policy_reaches_all_sdk_calls_without_model_rewrite(
        self, sdk_transport, mode, temperature_mode, tokens, store, multimodal, max_tokens
    ):
        from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import bounded_client
        profile = {
            "id": "literal-claude", "revision": 1, "provider": "openrouter", "model": "claude-sonnet-latest",
            "endpoint": "https://openrouter.ai/api/v1", "origin": "user_defined", "support": "unverified",
            "verification": "not_checked", "documentation_urls": [],
            "request_policy": {"api": "chat_completions", "temperature_mode": temperature_mode,
                "token_limit_parameter": tokens, "store": store, "structured_output": mode,
                "multimodal_output": multimodal},
        }
        config = {"api_key": "synthetic-unit-key-only", "base_url": profile["endpoint"],
                  "model": profile["model"], "inference_profile": profile}
        requests, _ = sdk_transport
        with bounded_client(config):
            backend = InferenceBackend(**config, temperature=0.7, max_tokens=max_tokens, max_retries=0, load_dotenv=False)
            assert backend.model == config["model"]
            backend.run_json(_request())
            backend.multimodal_chat("unit JSON", {})
        bodies = [json.loads(r.content) for r in requests]
        assert len(bodies) == 3
        for i, body in enumerate(bodies):
            assert body["model"] == config["model"]
            assert body[tokens] == (min(8, max_tokens) if i == 0 else max_tokens)
            assert ("temperature" in body) == (temperature_mode == "configured")
            if temperature_mode == "configured":
                assert body["temperature"] == 0.7
            assert ("store" in body) == (store is False)
        assert ("response_format" in bodies[1]) == (mode != "omitted")
        if mode != "omitted":
            assert bodies[1]["response_format"]["type"] == mode
        if mode != "json_schema":
            assert json.dumps(_request().schema, sort_keys=True) in bodies[1]["messages"][0]["content"]
        assert ("response_format" in bodies[2]) == (multimodal != "omitted")

    def test_request_policy_uses_shared_profile_authority(self, monkeypatch, sdk_transport):
        from isaaclab_arena.agentic_environment_generation import inference_profiles
        from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import bounded_client

        requests, _ = sdk_transport
        resolved = []

        def unverified(model, base_url, *, actual_base_url=None):
            resolved.append((model, base_url, actual_base_url))

        monkeypatch.setattr(inference_profiles, "resolve_inference_profile", unverified)
        config = {"api_key": "synthetic-unit-key-only", "base_url": "https://api.openai.com/v1", "model": "gpt-6-astra"}
        with bounded_client(config):
            backend = InferenceBackend(**config, temperature=0.3, max_tokens=123, max_retries=0, load_dotenv=False)
            backend.run_json(_request())
        assert resolved == [("gpt-6-astra", "https://api.openai.com/v1", "https://api.openai.com/v1/")] * 2
        body = json.loads(requests[1].content)
        assert body["temperature"] == 0.3 and body["max_tokens"] == 123
        assert "max_completion_tokens" not in body

    @pytest.mark.parametrize("endpoint", ["https://api.openai.com/v1", "https://api.openai.com/v1/"])
    @pytest.mark.parametrize("max_tokens", [4, 4096])
    def test_all_paths_use_bounded_completion_tokens_without_sampling_or_storage(
        self, sdk_transport, endpoint, max_tokens
    ):
        from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import bounded_client

        requests, _ = sdk_transport
        config = {"api_key": "synthetic-unit-key-only", "base_url": endpoint, "model": "gpt-6-astra"}
        with bounded_client(config) as client:
            backend = InferenceBackend(
                **config, temperature=0.3, max_tokens=max_tokens, max_retries=0, load_dotenv=False
            )
            assert backend.run_json(_request()) == {"unit_evidence": True}
            assert backend.multimodal_chat("unit JSON", {"camera": b"unit-image"}) == '{"unit_evidence": true}'
            assert backend.inference_profile["model"] == config["model"]
            assert client.max_retries == 0
            assert client.timeout == 45
            assert client._client.follow_redirects is False
            assert client._client._trust_env is False
        assert len(requests) == 3
        bodies = [json.loads(request.content) for request in requests]
        for index, (request, body) in enumerate(zip(requests, bodies)):
            assert str(request.url) == "https://api.openai.com/v1/chat/completions"
            assert request.method == "POST"
            assert body["model"] == "gpt-6-astra" == backend.model
            assert "temperature" not in body
            assert "max_tokens" not in body
            assert "top_p" not in body and "logprobs" not in body
            assert body["max_completion_tokens"] == (min(8, max_tokens) if index == 0 else max_tokens)
            assert body["store"] is False
            assert set(body) == {"model", "messages", "max_completion_tokens", "store"} | (
                {"response_format"} if index else set()
            )
        assert bodies[0]["messages"] == [{"role": "user", "content": "Respond with exactly: OK"}]
        assert bodies[1]["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "TestSchema", "strict": True, "schema": _request().schema},
        }
        assert bodies[2]["response_format"] == {"type": "json_object"}
        assert bodies[2]["messages"][0]["content"] == [
            {"type": "text", "text": "unit JSON"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,dW5pdC1pbWFnZQ=="}},
        ]

    @pytest.mark.parametrize(
        "endpoint,model",
        [
            ("https://api.openai.com/v1", "gpt-4.1"),
            ("https://api.openai.com/v1", "gpt-4o"),
            ("https://api.openai.com/v1", "gpt-6-astra-preview"),
            ("https://api.openai.com/v1", "openai/gpt-6-astra"),
            ("https://api.openai.com/v1", "GPT-6-Astra"),
            ("https://openrouter.ai/api/v1", "openai/gpt-6-astra"),
            ("https://openrouter.ai/api/v1", "gpt-6-astra"),
            ("https://openrouter.ai/api/v1", "anthropic/claude-sonnet-4.5"),
            ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
            ("https://integrate.api.nvidia.com/v1", "nvidia/llama-3.1-nemotron-70b-instruct"),
            (DEFAULT_BASE_URL, "azure/anthropic/claude-opus-4-8"),
            ("https://api.openai.com.attacker.invalid/v1", "gpt-6-astra"),
            ("https://api.openai.com@attacker.invalid/v1", "gpt-6-astra"),
            ("https://trusted.invalid/api.openai.com/v1", "gpt-6-astra"),
            ("http://api.openai.com/v1", "gpt-6-astra"),
            ("https://api.openai.com:443/v1", "gpt-6-astra"),
            ("https://API.OPENAI.COM/v1", "gpt-6-astra"),
            ("https://api.openai.com:444/v1", "gpt-6-astra"),
            ("https://api.openai.com/other/v1", "gpt-6-astra"),
            ("https://api.openai.com/v1?proxy=1", "gpt-6-astra"),
            ("https://api.openai.com/v1#proxy", "gpt-6-astra"),
        ],
    )
    def test_legacy_wire_parameters_and_literal_models_are_unchanged(self, sdk_transport, endpoint, model):
        from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import bounded_client

        requests, _ = sdk_transport
        config = {"api_key": "synthetic-unit-key-only", "base_url": endpoint, "model": model}
        with bounded_client(config):
            backend = InferenceBackend(**config, temperature=0.7, max_tokens=123, max_retries=0, load_dotenv=False)
            assert backend.run_json(_request()) == {"unit_evidence": True}
            backend.multimodal_chat("unit JSON", {})
        assert len(requests) == 3
        for index, request in enumerate(requests):
            body = json.loads(request.content)
            assert body["model"] == model == backend.model
            assert body["temperature"] == (0 if index == 0 else 0.7)
            assert body["max_tokens"] == (8 if index == 0 else 123)
            assert "max_completion_tokens" not in body and "store" not in body
            assert set(body) == {"model", "messages", "temperature", "max_tokens"} | (
                {"response_format"} if index else set()
            )

    def test_profile_uses_actual_client_endpoint_not_constructor_provider_hint(self, sdk_transport):
        from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import bounded_client

        requests, _ = sdk_transport
        config = {
            "api_key": "synthetic-unit-key-only",
            "base_url": "https://trusted.invalid/v1",
            "model": "gpt-6-astra",
        }
        with bounded_client(config):
            backend = InferenceBackend(**{**config, "base_url": "https://api.openai.com/v1"}, load_dotenv=False)
            backend.run_json(_request())
            assert backend.inference_profile is None
        assert all(str(request.url) == "https://trusted.invalid/v1/chat/completions" for request in requests)
        assert all("temperature" in json.loads(request.content) for request in requests)

    @pytest.mark.parametrize("stage", ["ping", "structured", "multimodal"])
    def test_rejection_never_adds_a_compatibility_retry_or_switches_models(self, sdk_transport, stage):
        from openai import BadRequestError

        from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import bounded_client

        requests, statuses = sdk_transport
        config = {"api_key": "synthetic-unit-key-only", "base_url": "https://api.openai.com/v1", "model": "gpt-6-astra"}
        statuses.extend([400] if stage == "ping" else [200, 400])
        with bounded_client(config):
            if stage == "ping":
                with pytest.raises(BadRequestError, match="synthetic unit rejection"):
                    InferenceBackend(**config, max_retries=0, load_dotenv=False)
            else:
                backend = InferenceBackend(**config, max_retries=0, load_dotenv=False)
                with pytest.raises(RuntimeError if stage == "structured" else BadRequestError):
                    if stage == "structured":
                        backend.run_json(_request())
                    else:
                        backend.multimodal_chat("unit JSON", {})
        assert len(requests) == (1 if stage == "ping" else 2)
        assert all(json.loads(request.content)["model"] == config["model"] for request in requests)

    def test_initializer_consumes_the_existing_eight_call_budget(self, sdk_transport):
        from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import bounded_client

        requests, _ = sdk_transport
        config = {"api_key": "synthetic-unit-key-only", "base_url": "https://api.openai.com/v1", "model": "gpt-6-astra"}
        with bounded_client(config):
            backend = InferenceBackend(**config, max_retries=0, load_dotenv=False)
            for _ in range(7):
                backend.run_json(_request())
            with pytest.raises(RuntimeError, match="Generation call budget exhausted"):
                backend.run_json(_request())
        assert len(requests) == 8

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_deterministic_rejection_does_not_consume_application_retries(self, sdk_transport, status):
        from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import bounded_client

        requests, statuses = sdk_transport
        config = {"api_key": "synthetic-unit-key-only", "base_url": "https://api.openai.com/v1", "model": "gpt-6-astra"}
        statuses.extend([200, status, status, status, status])
        with bounded_client(config):
            backend = InferenceBackend(**config, max_retries=3, load_dotenv=False)
            with pytest.raises(RuntimeError):
                backend.run_json(_request())
        assert len(requests) == 2  # One initialization plus one rejected structured request.
        assert len(backend.telemetry.calls) == 1


class TestInit:
    def test_explicit_api_key_overrides_env(self, monkeypatch, stub_openai):
        mock_cls, _ = stub_openai
        monkeypatch.setenv("NV_API_KEY", "env-key")
        InferenceBackend(api_key="explicit-key")
        mock_cls.assert_called_once_with(api_key="explicit-key", base_url=DEFAULT_BASE_URL)

    def test_falls_back_to_env_var(self, monkeypatch, stub_openai):
        mock_cls, _ = stub_openai
        monkeypatch.setenv("NV_API_KEY", "env-key")
        InferenceBackend()
        mock_cls.assert_called_once_with(api_key="env-key", base_url=DEFAULT_BASE_URL)

    def test_raises_when_no_key_anywhere(self, monkeypatch, stub_openai):
        monkeypatch.delenv("NV_API_KEY", raising=False)
        with pytest.raises(AssertionError, match="API key required"):
            InferenceBackend()

    def test_custom_model_and_base_url(self, stub_openai):
        mock_cls, _ = stub_openai
        backend = InferenceBackend(api_key="k", model="custom-model", base_url="http://localhost:8000")
        assert backend.model == "custom-model"
        mock_cls.assert_called_once_with(api_key="k", base_url="http://localhost:8000")


class TestRunJson:
    def test_tolerates_unescaped_control_chars(self, stub_openai):
        _, client = stub_openai
        backend = inference_backend(stub_openai)
        payload = {"env_name": "pick\tup"}
        raw = json.dumps(payload).replace("\\t", "\t")
        assert "\t" in raw
        client.chat.completions.create.return_value = chat_response(content=raw)
        result = backend.run_json(_request())
        assert "\t" in result["env_name"]

    def test_raises_when_response_has_no_choices(self, stub_openai):
        _, client = stub_openai
        backend = inference_backend(stub_openai)
        resp = MagicMock()
        resp.choices = []
        client.chat.completions.create.return_value = resp
        with pytest.raises(RuntimeError, match="failed test after 4 attempts"):
            backend.run_json(_request())
        assert client.chat.completions.create.call_count == 4

    def test_retries_after_api_error_then_succeeds(self, stub_openai):
        _, client = stub_openai
        backend = inference_backend(stub_openai)
        client.chat.completions.create.side_effect = [
            ConnectionError("timeout"),
            chat_response(content='{"ok": true}'),
        ]
        result = backend.run_json(_request())
        assert result == {"ok": True}
        assert client.chat.completions.create.call_count == 2

    def test_raises_after_api_errors_exhaust_retries(self, stub_openai):
        _, client = stub_openai
        backend = inference_backend(stub_openai, max_retries=1)
        client.chat.completions.create.side_effect = ConnectionError("timeout")
        with pytest.raises(RuntimeError, match="failed test after 2 attempts"):
            backend.run_json(_request())
        assert client.chat.completions.create.call_count == 2


def test_shared_call_allowance_counts_before_sdk_across_contexts(sdk_transport, monkeypatch):
    import time

    from isaaclab_arena.agentic_environment_generation import inference_backend as module
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance, bounded_client

    requests, statuses = sdk_transport
    config = {"api_key": "synthetic-unit-key-only", "base_url": "https://api.openai.com/v1", "model": "gpt-6-astra"}
    allowance = CallAllowance(max_calls=5, deadline=time.monotonic() + 60)
    original = module.OpenAI
    with bounded_client(config, allowance=allowance) as client:
        completion = client.chat.completions.create

        def observed(*args, **kwargs):
            result = completion(*args, **kwargs)
            assert allowance.attempted_calls == len(requests)
            return result

        monkeypatch.setattr(client.chat.completions, "create", observed)
        backend = InferenceBackend(**config, max_retries=0, load_dotenv=False)
        assert allowance.attempted_calls == 1
        assert backend.run_json(_request()) == {"unit_evidence": True}
        assert backend.multimodal_chat("unit JSON", {"camera": b"unit-image"}) == '{"unit_evidence": true}'
        statuses.append(500)
        with pytest.raises(RuntimeError, match="synthetic unit rejection"):
            backend.run_json(_request())
        assert allowance.attempted_calls == len(requests) == 4
        assert client.max_retries == 0
    assert module.OpenAI is original
    assert allowance.attempted_calls == 4
    with bounded_client(config, allowance=allowance):
        backend = InferenceBackend(**config, max_retries=0, load_dotenv=False)
        assert allowance.attempted_calls == 5
        with pytest.raises(RuntimeError, match="Generation call budget exhausted"):
            backend.run_json(_request())
    assert allowance.attempted_calls == len(requests) == 5
    assert module.OpenAI is original


@pytest.mark.parametrize("max_calls", [0, -1, True, 1.5, "2"])
def test_call_allowance_requires_positive_integer(max_calls):
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance

    with pytest.raises(ValueError, match="positive integer"):
        CallAllowance(max_calls=max_calls, deadline=100)


@pytest.mark.parametrize("deadline", [True, None, "100", float("nan")])
def test_call_allowance_requires_absolute_numeric_deadline(deadline):
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance

    with pytest.raises(ValueError, match="monotonic"):
        CallAllowance(max_calls=1, deadline=deadline)


def test_shared_allowance_deadline_denies_ping_and_later_calls(sdk_transport, monkeypatch):
    from isaaclab_arena.agentic_environment_generation import inference_backend as backend_module
    from isaaclab_arena.agentic_environment_generation.workflow import inference_transport as module

    requests, _ = sdk_transport
    config = {"api_key": "synthetic-unit-key-only", "base_url": "https://api.openai.com/v1", "model": "gpt-6-astra"}
    clock = [10]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    allowance = module.CallAllowance(max_calls=4, deadline=11)
    original = backend_module.OpenAI
    with module.bounded_client(config, allowance=allowance) as client:
        backend = InferenceBackend(**config, max_retries=0, load_dotenv=False)
        clock[0] = 11
        with pytest.raises(RuntimeError, match="deadline exhausted"):
            backend.run_json(_request())
        with pytest.raises(ValueError, match="deadline exhausted"):
            backend.multimodal_chat("unit JSON", {})
    assert client.is_closed()
    assert allowance.attempted_calls == len(requests) == 1
    with pytest.raises(ValueError, match="deadline exhausted"):
        with module.bounded_client(config, allowance=allowance):
            InferenceBackend(**config, max_retries=0, load_dotenv=False)
    assert backend_module.OpenAI is original
    assert allowance.attempted_calls == len(requests) == 1


def test_allowance_charged_before_sdk_validation_failure(sdk_transport, monkeypatch):
    import time

    from openai.resources.chat.completions import Completions
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance, bounded_client

    requests, _ = sdk_transport
    allowance = CallAllowance(max_calls=1, deadline=time.monotonic() + 60)
    entered = []

    def fail_before_http(self, *args, **kwargs):
        entered.append(allowance.attempted_calls)
        raise TypeError("synthetic SDK validation failure")

    monkeypatch.setattr(Completions, "create", fail_before_http)
    config = {"api_key": "synthetic-unit-key-only", "base_url": "https://api.openai.com/v1", "model": "gpt-6-astra"}
    with pytest.raises(TypeError, match="SDK validation"):
        with bounded_client(config, allowance=allowance):
            InferenceBackend(**config, max_retries=0, load_dotenv=False)
    with bounded_client(config, allowance=allowance):
        with pytest.raises(ValueError, match="budget exhausted"):
            InferenceBackend(**config, max_retries=0, load_dotenv=False)
    assert entered == [1]
    assert allowance.attempted_calls == 1 and requests == []


def test_shared_transport_restores_after_overlap_body_and_close_failure(sdk_transport, monkeypatch):
    import time

    from isaaclab_arena.agentic_environment_generation import inference_backend as module
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance, bounded_client

    requests, _ = sdk_transport
    config = {"api_key": "synthetic-unit-key-only", "base_url": "https://api.openai.com/v1", "model": "gpt-6-astra"}
    allowance = CallAllowance(max_calls=4, deadline=time.monotonic() + 60)
    original = module.OpenAI
    with pytest.raises(RuntimeError, match="body failure"):
        with bounded_client(config, allowance=allowance) as first:
            patched = module.OpenAI
            with pytest.raises(RuntimeError, match="Overlapping"):
                with bounded_client(config, allowance=allowance):
                    pytest.fail("overlap admitted")
            assert module.OpenAI is patched
            InferenceBackend(**config, max_retries=0, load_dotenv=False)
            raise RuntimeError("body failure")
    assert module.OpenAI is original and first.is_closed()
    with pytest.raises(RuntimeError, match="close failure"):
        with bounded_client(config, allowance=allowance) as second:
            InferenceBackend(**config, max_retries=0, load_dotenv=False)
            close = second.close

            def failing_close():
                close()
                raise RuntimeError("close failure")

            monkeypatch.setattr(second, "close", failing_close)
    assert module.OpenAI is original and second.is_closed()
    with bounded_client(config, allowance=allowance):
        backend = InferenceBackend(**config, max_retries=2, load_dotenv=False)
        assert backend._max_retries == 2
        assert backend.run_json(_request()) == {"unit_evidence": True}
    assert module.OpenAI is original
    assert allowance.attempted_calls == len(requests) == 4


def test_transport_factory_failure_releases_patch_lock(sdk_transport, monkeypatch):
    import time
    import openai

    from isaaclab_arena.agentic_environment_generation import inference_backend as module
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance, bounded_client

    original = module.OpenAI
    sdk_factory = openai.OpenAI
    config = {"api_key": "synthetic-unit-key-only", "base_url": "https://api.openai.com/v1", "model": "gpt-6-astra"}
    allowance = CallAllowance(max_calls=1, deadline=time.monotonic() + 60)

    def fail_factory(**kwargs):
        raise RuntimeError("synthetic factory failure")

    monkeypatch.setattr(openai, "OpenAI", fail_factory)
    with pytest.raises(RuntimeError, match="factory failure"):
        with bounded_client(config, allowance=allowance):
            pytest.fail("factory failure ignored")
    assert module.OpenAI is original and allowance.attempted_calls == 0
    monkeypatch.setattr(openai, "OpenAI", sdk_factory)
    with bounded_client(config, allowance=allowance):
        InferenceBackend(**config, max_retries=0, load_dotenv=False)
    assert allowance.attempted_calls == len(sdk_transport[0]) == 1


def test_transport_freezes_config_and_rejects_wrong_model_policy(sdk_transport, monkeypatch):
    import time

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance, bounded_client

    requests, _ = sdk_transport
    config = {"api_key": "synthetic-unit-key-only", "base_url": "https://api.openai.com/v1", "model": "gpt-6-astra"}
    original_config = dict(config)
    allowance = CallAllowance(max_calls=2, deadline=time.monotonic() + 60)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ambient.invalid/v1")
    monkeypatch.setenv("HTTPS_PROXY", "https://ambient.invalid")
    with bounded_client(config, allowance=allowance) as client:
        config.update(model="gpt-4o", base_url="https://mutated.invalid/v1", api_key="changed-unit-key")
        with pytest.raises(ValueError, match="model binding mismatch"):
            InferenceBackend(**config, max_retries=0, load_dotenv=False)
        assert allowance.attempted_calls == 0 and requests == []
        backend = InferenceBackend(**original_config, max_retries=0, load_dotenv=False)
        assert backend.run_json(_request()) == {"unit_evidence": True}
        assert client.timeout == 45 and client.max_retries == 0
        assert client._client.follow_redirects is False and client._client._trust_env is False
    assert len(requests) == allowance.attempted_calls == 2
    for request in requests:
        assert str(request.url) == "https://api.openai.com/v1/chat/completions"
        assert json.loads(request.content)["model"] == "gpt-6-astra"


def test_legacy_contexts_get_fresh_eight_calls_without_deadline(sdk_transport, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow import inference_transport as module
    from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import bounded_client

    monkeypatch.setattr(module.time, "monotonic", lambda: 10**20)
    config = {"api_key": "synthetic-unit-key-only", "base_url": "https://api.openai.com/v1", "model": "gpt-6-astra"}
    for _ in range(2):
        with bounded_client(config) as client:
            backend = InferenceBackend(**config, max_retries=0, load_dotenv=False)
            for _ in range(7):
                assert backend.run_json(_request()) == {"unit_evidence": True}
            with pytest.raises(RuntimeError, match="budget exhausted"):
                backend.run_json(_request())
        assert client.is_closed()
    assert len(sdk_transport[0]) == 16


def test_legacy_openrouter_alias_preserves_literal_and_eight_attempt_cap(sdk_transport):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.provider_security import (
        bounded_client,
        checked_config,
    )

    requests, _ = sdk_transport
    config = checked_config({
        "api_key": "synthetic-unit-key-only",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "claude-sonnet-4.5",
    })
    assert "inference_profile" not in config
    with bounded_client(config) as client:
        backend = InferenceBackend(**config, max_retries=0, load_dotenv=False)
        assert backend.model == "anthropic/claude-sonnet-4.5"
        assert backend.run_json(_request()) == {"unit_evidence": True}
        assert backend.multimodal_chat("unit JSON", {"camera": b"unit-image"}) == '{"unit_evidence": true}'
        for _ in range(5):
            backend.run_json(_request())
        assert len(requests) == 8
        with pytest.raises(RuntimeError, match="budget exhausted"):
            backend.run_json(_request())
        assert len(requests) == 8
    assert client.is_closed()
    bodies = [json.loads(request.content) for request in requests]
    assert all(body["model"] == "claude-sonnet-4.5" for body in bodies)
    assert bodies[0]["messages"] == [{"role": "user", "content": "Respond with exactly: OK"}]
    assert bodies[1]["response_format"]["type"] == "json_schema"
    assert bodies[2]["messages"][0]["content"][1]["type"] == "image_url"


def test_allowance_charge_is_atomic_across_actual_threads():
    import threading

    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import CallAllowance

    allowance = CallAllowance(max_calls=3, deadline=float("inf"))
    start = threading.Barrier(12)
    outcomes: list[str | None] = [None] * 12

    def charge(index):
        start.wait(timeout=10)
        try:
            allowance.charge()
        except ValueError as exc:
            outcomes[index] = str(exc)
        else:
            outcomes[index] = "charged"

    threads = [threading.Thread(target=charge, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads)
    assert outcomes.count("charged") == allowance.attempted_calls == 3
    assert outcomes.count("Generation call budget exhausted") == 9


def test_transport_module_import_defers_sdk_and_backend(monkeypatch):
    import builtins
    import importlib.util

    from isaaclab_arena.agentic_environment_generation.workflow import inference_transport

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert not name.startswith(("openai", "httpx"))
        assert "inference_backend" not in name
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    spec = importlib.util.spec_from_file_location("transport_import_unit", inference_transport.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.CallAllowance(max_calls=1, deadline=0).attempted_calls == 0
