# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Offline actual-schema and synthetic-completion tests; no provider execution."""

from __future__ import annotations

import copy
import json
from unittest.mock import MagicMock

import pytest

from isaaclab_arena.agentic_environment_generation.inference_backend import InferenceBackend, InferenceTelemetryTracker
from isaaclab_arena.agentic_environment_generation.spec_inference import SpecInference
from isaaclab_arena.agentic_environment_generation.spec_wire_adapter import SpecWireAdapter
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.tests.utils.agentic_environment_generation import chat_response, minimal_spec_dict


def rich_domain_data():
    data = minimal_spec_dict()
    nested = {"params": {"x": [None, True, False, 1, 1.5, "", "雪", {"key": "value_json"}]}, "empty": {}}
    data["embodiment"]["params"] = {"initial_pose": {"position_xyz": [-0.55, 0.0, 0.0], "rotation_xyzw": [0, 0, 0, 1]}}
    data["background"]["params"] = copy.deepcopy(nested)
    data["objects"][0]["params"] = copy.deepcopy(nested)
    data["object_references"] = [{
        "id": "table_surface",
        "parent_id": data["background"]["id"],
        "object_type": "base",
        "prim_path": None,
        "params": copy.deepcopy(nested),
    }]
    data["relations"][1]["params"] = {"surface_anchor": "table_top", "surface_sector": "front_right", **nested}
    data["task"]["subtasks"][0]["params"]["options"] = copy.deepcopy(nested)
    data["reified_relations"] = [{
        "reifier_id": "placement",
        "source_id": data["objects"][0]["id"],
        "target_id": data["background"]["id"],
        "relation_type": "PLACED_ON",
    }]
    return ArenaEnvGraphSpec.model_validate(data).model_dump(mode="json")


def test_nested_maps_round_trip_without_mutation_or_scene_blob():
    adapter = SpecWireAdapter()
    data = rich_domain_data()
    before = copy.deepcopy(data)
    wire = adapter.encode(data)
    assert data == before
    assert isinstance(wire["embodiment"], dict)
    assert isinstance(wire["task"], dict)
    assert wire["embodiment"]["params"] == [{
        "key": "initial_pose",
        "value_json": json.dumps(
            data["embodiment"]["params"]["initial_pose"], ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ),
    }]
    assert wire["objects"][1]["params"] == []
    restored = adapter.decode(wire)
    assert restored == data
    assert ArenaEnvGraphSpec.model_validate(restored).model_dump(mode="json") == data
    assert wire["background"]["params"][0]["key"] == "params"


def test_committed_banana_on_plate_dictionaries_round_trip():
    """Real repository YAML, not an invented completion or a live A2 result."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "isaaclab_arena_environments/robolab/tasks/banana_on_plate.yaml"
    data = ArenaEnvGraphSpec.from_yaml(source).model_dump(mode="json")
    assert data["embodiment"]["params"] == {"stand_height_m": 1.35}
    assert data["task"]["subtasks"][0]["params"] == {
        "pick_up_object": "banana",
        "destination_location": "plate",
        "background_scene": "maple_table_robolab",
        "episode_length_s": 20.0,
    }
    adapter = SpecWireAdapter()
    assert adapter.decode(adapter.encode(data)) == data


def test_decoder_rejects_ambiguous_or_malformed_maps():
    adapter = SpecWireAdapter()
    valid = adapter.encode(rich_domain_data())
    invalid_maps = [
        {},
        None,
        "{}",
        ["entry"],
        [{"key": "a"}],
        [{"key": "a", "value_json": "0", "extra": None}],
        [{"key": 1, "value_json": "0"}],
        [{"key": "a", "value_json": 0}],
        [{"key": "a", "value_json": "0"}, {"key": "a", "value_json": "1"}],
        *[
            [{"key": "a", "value_json": raw}]
            for raw in (
                '{"x":1,"x":2}',
                '{"x":1,"\\u0078":2}',
                '{"nested":{"x":1,"x":2}}',
                "NaN",
                "Infinity",
                "-Infinity",
                "1e309",
                '{"x": [NaN]}',
                "",
                "{} trailing",
                "```json\n{}\n```",
                '"unescaped\tcontrol"',
            )
        ],
    ]
    for invalid in invalid_maps:
        wire = copy.deepcopy(valid)
        wire["embodiment"]["params"] = invalid
        with pytest.raises(ValueError):
            adapter.decode(wire)


@pytest.mark.parametrize(
    "raw",
    [
        '{"a":1,"a":2}',
        '{"a":{"x":1,"x":2}}',
        '{"a":NaN}',
        '{"a":1e309}',
        '{"a":"raw\tcontrol"}',
        "```json\n{}\n```",
        "{} trailing",
        "[]",
        "null",
    ],
)
def test_raw_parser_rejects_lossy_inputs(raw):
    with pytest.raises(ValueError):
        SpecWireAdapter.parse_json(raw)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), (1, 2), {1: "numeric key"}, {"set"}])
def test_encoder_rejects_non_json_values(value):
    data = rich_domain_data()
    data["embodiment"]["params"]["invalid"] = value
    with pytest.raises(ValueError):
        SpecWireAdapter().encode(data)


def test_decoder_rejects_structural_coercions_and_dropped_fields():
    adapter = SpecWireAdapter()
    valid = adapter.encode(rich_domain_data())
    invalid = []
    for key, value in [
        ("unknown", 1),
        ("env_name", ""),
        ("env_name", None),
        ("objects", {}),
        ("embodiment", "franka_ik"),
    ]:
        wire = copy.deepcopy(valid)
        wire[key] = value
        invalid.append(wire)
    wire = copy.deepcopy(valid)
    del wire["env_name"]
    invalid.append(wire)
    for normal in [[0, 1], [0, 0, True], [0, 0, "1"]]:
        wire = copy.deepcopy(valid)
        wire["reified_relations"][0]["contact_normal"] = normal
        invalid.append(wire)
    for wire in invalid:
        with pytest.raises(ValueError):
            adapter.decode(wire)


def test_json_resource_limits_fail_closed():
    from isaaclab_arena.agentic_environment_generation.spec_wire_adapter import (
        MAX_JSON_BYTES,
        MAX_JSON_DEPTH,
        MAX_JSON_NODES,
    )

    for value in ["x" * MAX_JSON_BYTES, [None] * MAX_JSON_NODES]:
        with pytest.raises(ValueError):
            SpecWireAdapter.parse_json(json.dumps({"a": value}))
    nested = 0
    for _ in range(MAX_JSON_DEPTH + 1):
        nested = [nested]
    with pytest.raises(ValueError):
        SpecWireAdapter.parse_json(json.dumps({"a": nested}))
    data = rich_domain_data()
    data["embodiment"]["params"]["too_deep"] = nested
    with pytest.raises(ValueError):
        SpecWireAdapter().encode(data)


def make_backend(model="gpt-4.1", base_url="https://api.openai.com/v1"):
    """Exercise real run_json without initializer ping, SDK or metadata subprocess."""
    backend = InferenceBackend.__new__(InferenceBackend)
    backend._client = MagicMock()
    backend._client.base_url = base_url
    backend._configured_base_url = base_url
    backend._model = model
    backend._temperature = 0.2
    backend._max_tokens = 4096
    backend._max_retries = 0
    backend._telemetry = InferenceTelemetryTracker()
    return backend


def infer(inference, traces):
    catalog = MagicMock()
    catalog.to_catalog_string.return_value = "catalog"
    return inference.infer("place object", traces, catalog, catalog, catalog)


@pytest.mark.parametrize("model", ["gpt-4.1", "gpt-6-astra"])
@pytest.mark.parametrize("base_url", ["https://api.openai.com/v1", "https://api.openai.com/v1/"])
@pytest.mark.parametrize("operation", ["infer", "repair_dict", "repair_spec"])
def test_actual_requests_decode_maps_and_repair_uses_same_wire(model, base_url, operation):
    backend = make_backend(model, base_url)
    inference = SpecInference(backend)
    data = rich_domain_data()
    wire = SpecWireAdapter().encode(data)
    backend.client.chat.completions.create.return_value = chat_response(content=json.dumps(wire))
    traces = []
    if operation == "infer":
        spec, returned = infer(inference, traces)
    else:
        previous = data if operation == "repair_dict" else ArenaEnvGraphSpec.model_validate(data)
        spec, returned = inference.repair_with_feedback(previous, "retain all nested parameters", traces)
    assert isinstance(spec, ArenaEnvGraphSpec)
    assert returned == data
    assert spec.model_dump(mode="json") == data
    assert traces == []
    request = backend.client.chat.completions.create.call_args.kwargs
    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "ArenaEnvGraphSpec", "strict": True, "schema": inference._schema},
    }
    assert "value_json" in request["messages"][0]["content"]
    assert "DOMAIN EXAMPLE" in request["messages"][0]["content"]
    if operation != "infer":
        previous_text = (
            request["messages"][1]["content"].split("PREVIOUS CANDIDATE SPEC:\n", 1)[1].split("\n\nDIAGNOSTIC", 1)[0]
        )
        encoded_prior = json.loads(previous_text)
        assert SpecWireAdapter().decode(encoded_prior) == data
        assert isinstance(encoded_prior["embodiment"]["params"], list)
        assert encoded_prior["embodiment"]["params"] == wire["embodiment"]["params"]
        assert encoded_prior["task"]["subtasks"][0]["params"] == wire["task"]["subtasks"][0]["params"]


@pytest.mark.parametrize("operation", ["infer", "repair"])
def test_domain_validation_and_failed_evidence_survive_decoding(operation):
    backend = make_backend()
    inference = SpecInference(backend)
    data = rich_domain_data()
    data["embodiment"]["registry_name"] = "not_registered"
    backend.client.chat.completions.create.return_value = chat_response(
        content=json.dumps(SpecWireAdapter().encode(data))
    )
    traces = []
    result = (
        infer(inference, traces) if operation == "infer" else inference.repair_with_feedback(data, "fix asset", traces)
    )
    assert result == (None, data)
    assert any("registry_name" in trace for trace in traces)


@pytest.mark.parametrize(
    "model,endpoint",
    [
        ("gpt-4.1", "https://api.openai.com/v1/proxy"),
        ("gpt-6-astra", "https://proxy.example/v1"),
        ("gpt-6-astra-preview", "https://api.openai.com/v1"),
        ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai"),
        ("anthropic/claude-sonnet-4.5", "https://openrouter.ai/api/v1"),
    ],
)
def test_legacy_pairs_keep_original_schema_and_domain_maps(model, endpoint):
    from isaaclab_arena.agentic_environment_generation.inference_backend import build_strict_schema

    backend = make_backend(model, endpoint)
    inference = SpecInference(backend)
    data = minimal_spec_dict()
    backend.client.chat.completions.create.return_value = chat_response(content=json.dumps(data))
    spec, returned = infer(inference, [])
    assert isinstance(spec, ArenaEnvGraphSpec)
    assert returned == data
    assert inference._schema == build_strict_schema(ArenaEnvGraphSpec)
    request = backend.client.chat.completions.create.call_args.kwargs
    assert request["messages"][0]["content"] == SpecInference._system_prompt()
    assert request["response_format"]["type"] == "json_schema"


@pytest.mark.parametrize("operation", ["infer", "repair"])
@pytest.mark.parametrize("corruption", ["duplicate_outer", "duplicate_entry", "fenced", "control_character"])
def test_actual_request_rejects_raw_text_before_tolerant_backend_parsing(operation, corruption):
    backend = make_backend()
    inference = SpecInference(backend)
    data = rich_domain_data()
    raw = json.dumps(SpecWireAdapter().encode(data))
    if corruption == "duplicate_outer":
        raw = raw[:-1] + ',"env_name":"overwritten"}'
    elif corruption == "duplicate_entry":
        raw = raw.replace('"key": "initial_pose"', '"key": "discarded", "key": "initial_pose"', 1)
    elif corruption == "fenced":
        raw = "```json\n" + raw + "\n```"
    else:
        raw = raw.replace(data["env_name"], "raw\tcontrol", 1)
    backend.client.chat.completions.create.return_value = chat_response(content=raw)
    with pytest.raises((ValueError, RuntimeError)):
        if operation == "infer":
            infer(inference, [])
        else:
            inference.repair_with_feedback(data, "feedback", [])
    assert backend.client.chat.completions.create.call_count == 1
    request = backend.client.chat.completions.create.call_args.kwargs
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True


def schema_nodes(node, path=()):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from schema_nodes(value, (*path, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from schema_nodes(value, (*path, index))


def test_actual_generated_schema_has_no_open_objects_or_tuple_keywords():
    raw = ArenaEnvGraphSpec.model_json_schema()
    maps = [path for path, node in schema_nodes(raw) if node.get("additionalProperties") is True]
    assert set(maps) == {
        ("$defs", name, "properties", "params")
        for name in ("AssetSpec", "ObjectReferenceSpec", "TaskSpec", "SpatialRelationSpec")
    }
    assert [path for path, node in schema_nodes(raw) if "prefixItems" in node] == [
        ("$defs", "ReifiedRelationSpec", "properties", "contact_normal")
    ]
    assert set(raw["$defs"]) == {
        "AssetSpec",
        "CliOverrideSpec",
        "CompositeTaskSpec",
        "ContinuousIntervalSpec",
        "ObjectReferenceSpec",
        "ObjectType",
        "PlacementValidatorSpec",
        "ReifiedRelationSpec",
        "SpatialRelationSpec",
        "TaskCompositionType",
        "TaskSpec",
    }
    wire = SpecInference(make_backend())._schema
    assert set(raw["$defs"]) == set(wire["$defs"])
    allowed_keywords = {
        "$defs",
        "$ref",
        "type",
        "title",
        "description",
        "properties",
        "required",
        "additionalProperties",
        "anyOf",
        "enum",
        "minLength",
        "items",
        "minItems",
        "maxItems",
    }
    pending = [wire]
    while pending:
        node = pending.pop()
        assert set(node) <= allowed_keywords
        if "$ref" in node:
            assert node["$ref"].startswith("#/$defs/")
            assert node["$ref"].removeprefix("#/$defs/") in wire["$defs"]
        elif "anyOf" in node:
            assert len(node["anyOf"]) == 2
            assert sum(branch.get("type") == "null" for branch in node["anyOf"]) == 1
            pending.extend(node["anyOf"])
        else:
            assert node["type"] in {"object", "array", "string", "number", "null"}
        pending.extend(node.get("$defs", {}).values())
        pending.extend(node.get("properties", {}).values())
        if "items" in node:
            pending.append(node["items"])
    normal = wire["$defs"]["ReifiedRelationSpec"]["properties"]["contact_normal"]
    assert normal["items"] == {"type": "number"}
    assert normal["minItems"] == normal["maxItems"] == 3
    for path, node in schema_nodes(wire):
        assert "default" not in node, path
        assert "prefixItems" not in node, path
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, path
            assert set(node["required"]) == set(node["properties"]), path
        if node.get("type") == "array":
            assert isinstance(node.get("items"), dict), path


def test_wire_schema_matches_installed_openai_reference_normalization():
    from openai.lib._pydantic import _ensure_strict_json_schema

    wire = SpecWireAdapter().schema
    expected = copy.deepcopy(wire)
    _ensure_strict_json_schema(expected, path=(), root=expected)
    assert wire == expected
    assert all(len(node) == 1 for _, node in schema_nodes(wire) if "$ref" in node)
