# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for environment graph spec inference."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from isaaclab_arena.agentic_environment_generation.inference_backend import InferenceBackend, InferenceTelemetryTracker
from isaaclab_arena.agentic_environment_generation.spec_inference import SpecInference
from isaaclab_arena.assets.simready_constants import SIMREADY_USD_OBJECT_REGISTRY_NAME
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.tests.utils.agentic_environment_generation import catalog as make_catalog
from isaaclab_arena.tests.utils.agentic_environment_generation import chat_response, minimal_spec_dict
from isaaclab_arena.tests.utils.agentic_environment_generation import relation_catalog as make_relation_catalog
from isaaclab_arena.tests.utils.agentic_environment_generation import task_catalog as make_task_catalog


@pytest.fixture
def spec_inference():
    """Use real run_json with a synthetic client, no SDK constructor/ping/probe."""
    backend = InferenceBackend.__new__(InferenceBackend)
    backend._client = MagicMock()
    backend._client.base_url = "https://legacy.invalid/v1"
    backend._configured_base_url = "https://legacy.invalid/v1"
    backend._model = "test-model"
    backend._temperature = 0.2
    backend._max_tokens = 4096
    backend._max_retries = 3
    backend._telemetry = InferenceTelemetryTracker()
    return SpecInference(backend), backend.client


def _infer(
    inference: SpecInference,
    client: MagicMock,
    prompt: str = "p",
    *,
    asset_catalog=None,
    relation_catalog=None,
    task_catalog=None,
    traces: list[str] | None = None,
):
    traces = traces if traces is not None else []
    return inference.infer(
        prompt,
        traces,
        asset_catalog=asset_catalog or make_catalog("catalog"),
        relation_catalog=relation_catalog or make_relation_catalog("RELATIONS"),
        task_catalog=task_catalog or make_task_catalog("TASKS"),
    )


def test_infer_sets_response_format_to_json_schema(spec_inference):
    inference, client = spec_inference
    client.chat.completions.create.return_value = chat_response(content=json.dumps(minimal_spec_dict()))
    _infer(inference, client)
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["response_format"]["json_schema"]["name"] == "ArenaEnvGraphSpec"
    assert kwargs["response_format"]["json_schema"]["schema"] is inference._schema


@pytest.mark.parametrize("mode", ["json_schema", "json_object", "omitted"])
def test_user_profile_uses_explicit_format_and_strict_raw_validation(spec_inference, mode):
    from isaaclab_arena.agentic_environment_generation.spec_wire_adapter import SpecWireAdapter
    legacy, client = spec_inference
    backend = legacy._inference_backend
    backend._model = "literal-model"
    backend._client.base_url = backend._configured_base_url = "https://openrouter.ai/api/v1"
    backend._max_retries = 0
    backend._explicit_profile = {
        "id": "manual", "revision": 1, "provider": "openrouter", "model": backend._model,
        "endpoint": backend._configured_base_url, "origin": "user_defined", "support": "unverified",
        "verification": "not_checked", "documentation_urls": [],
        "request_policy": {"api": "chat_completions", "temperature_mode": "omitted",
            "token_limit_parameter": "max_tokens", "store": None, "structured_output": mode,
            "multimodal_output": "omitted"},
    }
    inference = SpecInference(backend)
    assert (inference._wire_adapter is not None) == (mode == "json_schema")
    domain = ArenaEnvGraphSpec.model_validate(minimal_spec_dict()).model_dump(mode="json")
    data = SpecWireAdapter().encode(domain) if mode == "json_schema" else domain
    client.chat.completions.create.return_value = chat_response(content=json.dumps(data))
    spec, parsed = _infer(inference, client)
    assert isinstance(spec, ArenaEnvGraphSpec)
    assert parsed == domain
    first = next(iter(data))
    raw = '{' + json.dumps(first) + ':' + json.dumps(data[first]) + ',' + json.dumps(data)[1:]
    client.chat.completions.create.return_value = chat_response(content=raw)
    with pytest.raises(RuntimeError):
        _infer(inference, client)
    client.chat.completions.create.return_value = chat_response(content='```json\n' + json.dumps(data) + '\n```')
    with pytest.raises(RuntimeError):
        _infer(inference, client)
    incomplete = dict(data)
    incomplete.pop(first)
    client.chat.completions.create.return_value = chat_response(content=json.dumps(incomplete))
    with pytest.raises((RuntimeError, ValueError)):
        _infer(inference, client)


def test_infer_user_message_contains_catalog_and_prompt(spec_inference):
    inference, client = spec_inference
    client.chat.completions.create.return_value = chat_response(content=json.dumps(minimal_spec_dict()))
    _infer(
        inference,
        client,
        "user wants avocado on kitchen",
        asset_catalog=make_catalog("<<CATALOG-MARKER>>"),
        relation_catalog=make_relation_catalog("<<RELATIONS-MARKER>>"),
        task_catalog=make_task_catalog("<<TASKS-MARKER>>"),
    )
    msgs = client.chat.completions.create.call_args.kwargs["messages"]
    assert [m["role"] for m in msgs] == ["system", "user"]
    user_msg = msgs[1]["content"]
    assert "<<CATALOG-MARKER>>" in user_msg
    assert "<<RELATIONS-MARKER>>" in user_msg
    assert "<<TASKS-MARKER>>" in user_msg
    assert "user wants avocado on kitchen" in user_msg


def test_system_prompt_requires_object_references_to_be_anchors():
    system_prompt = SpecInference._system_prompt()

    assert "every ``object_reference`` must have an ``is_anchor`` relation" in system_prompt


def test_system_prompt_requires_all_required_relation_params():
    system_prompt = SpecInference._system_prompt()

    assert "For every relation, include all parameters marked ``required`` in the RELATIONS catalog" in system_prompt


def test_infer_retries_after_api_error_then_succeeds(spec_inference):
    inference, client = spec_inference
    client.chat.completions.create.side_effect = [
        ConnectionError("timeout"),
        chat_response(content=json.dumps(minimal_spec_dict())),
    ]
    spec, _ = _infer(inference, client)
    assert isinstance(spec, ArenaEnvGraphSpec)
    assert spec.background.registry_name == "maple_table_robolab"
    assert client.chat.completions.create.call_count == 2


def test_infer_returns_none_with_validation_traces_on_invalid_spec(spec_inference):
    inference, client = spec_inference
    invalid = dict(minimal_spec_dict())
    invalid["embodiment"]["registry_name"] = "not_a_real_asset"
    client.chat.completions.create.return_value = chat_response(content=json.dumps(invalid))
    traces: list[str] = []
    spec, data = _infer(inference, client, traces=traces)
    assert spec is None
    assert data["embodiment"]["registry_name"] == "not_a_real_asset"
    assert traces
    assert any("registry_name" in line for line in traces)
    assert client.chat.completions.create.call_count == 3


def test_infer_feeds_validation_errors_back_and_recovers(spec_inference):
    inference, client = spec_inference
    invalid = dict(minimal_spec_dict())
    invalid["embodiment"]["registry_name"] = "not_a_real_asset"
    client.chat.completions.create.side_effect = [
        chat_response(content=json.dumps(invalid)),
        chat_response(content=json.dumps(minimal_spec_dict())),
    ]
    traces: list[str] = []
    spec, data = _infer(inference, client, traces=traces)
    assert isinstance(spec, ArenaEnvGraphSpec)
    assert data["embodiment"]["registry_name"] == "franka_ik"
    assert traces == []
    assert client.chat.completions.create.call_count == 2
    critic_message = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "CRITIC FEEDBACK" in critic_message
    assert "not_a_real_asset" in critic_message
    assert "registry_name" in critic_message


def test_infer_feeds_catalog_validation_errors_back_and_recovers(spec_inference):
    inference, client = spec_inference
    assets = make_catalog("ASSETS")
    assets.embodiments = [{"name": "droid_abs_joint_pos", "tags": []}]
    corrected = minimal_spec_dict()
    corrected["embodiment"]["registry_name"] = "droid_abs_joint_pos"
    client.chat.completions.create.side_effect = [
        chat_response(content=json.dumps(minimal_spec_dict())),
        chat_response(content=json.dumps(corrected)),
    ]

    spec, _ = _infer(inference, client, asset_catalog=assets)

    assert isinstance(spec, ArenaEnvGraphSpec)
    assert client.chat.completions.create.call_count == 2
    critic_message = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "Embodiment registry_name 'franka_ik' is not in the EMBODIMENTS catalog" in critic_message


def test_infer_retries_agent_ready_task_validation_errors(spec_inference):
    inference, client = spec_inference
    invalid = minimal_spec_dict()
    del invalid["task"]["subtasks"][0]["params"]["pick_up_object"]
    client.chat.completions.create.side_effect = [
        chat_response(content=json.dumps(invalid)),
        chat_response(content=json.dumps(minimal_spec_dict())),
    ]
    traces: list[str] = []
    spec, _ = _infer(inference, client, traces=traces)
    assert isinstance(spec, ArenaEnvGraphSpec)
    assert traces == []
    assert client.chat.completions.create.call_count == 2
    critic_message = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "missing required param 'pick_up_object'" in critic_message


def test_infer_never_mentions_the_asset_search(spec_inference):
    # Searching for assets is a separate pass that extends the catalog before this one runs, so
    # every object here is spawnable and spec inference has nothing to say about where it came from.
    inference, client = spec_inference
    client.chat.completions.create.return_value = chat_response(content=json.dumps(minimal_spec_dict()))
    _infer(inference, client)
    messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert SIMREADY_USD_OBJECT_REGISTRY_NAME not in messages[0]["content"]
    assert "simready" not in messages[0]["content"].lower()
