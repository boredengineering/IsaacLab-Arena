# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Lossless strict-output wire schema; the Arena domain schema is unchanged.

Only freeform dictionaries become arrays of closed ``{key, value_json}`` entries.
The JSON string holds one parameter value, never an entire scene. Homogeneous
fixed tuples use ``items`` with their original length bounds instead of
``prefixItems``. Unknown schema shapes fail closed rather than erasing fields.
"""

from __future__ import annotations

import copy
import json
import math
from typing import Any

from isaaclab_arena.agentic_environment_generation.inference_backend import build_strict_schema
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

MAX_JSON_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 100000


def _check_json(value: Any) -> None:
    """Reject non-JSON Python values, nonfinite numbers and unbounded trees."""
    remaining = MAX_JSON_NODES

    def visit(item: Any, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if depth > MAX_JSON_DEPTH or remaining < 0:
            raise ValueError("Spec wire JSON exceeds tree limits")
        kind = type(item)
        if kind is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("Spec wire JSON requires string keys")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif kind is list:
            for child in item:
                visit(child, depth + 1)
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError("Spec wire JSON requires finite numbers")
        elif kind not in (str, int, bool, type(None)):
            raise ValueError("Spec wire accepts only JSON value types")

    visit(value, 0)
    if (
        len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))
        > MAX_JSON_BYTES
    ):
        raise ValueError("Spec wire JSON exceeds byte limit")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Spec wire JSON contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Spec wire JSON requires finite numbers")


def _parse_value(text: str) -> Any:
    if type(text) is not str or len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("Spec wire JSON requires bounded text")
    try:
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Malformed spec wire JSON") from exc
    _check_json(value)
    return value


class SpecWireAdapter:
    """Adapt freeform maps at schema-declared positions, not arbitrary 'params' keys."""

    def __init__(self):
        self._domain_schema = build_strict_schema(ArenaEnvGraphSpec)
        self.schema = copy.deepcopy(self._domain_schema)
        self._adapt_schema(self.schema)
        self._inline_reference_siblings(self.schema, copy.deepcopy(self.schema))

    @classmethod
    def _inline_reference_siblings(cls, node, root, active=()):
        """Match OpenAI's strict-schema reference expansion without changing values."""
        if isinstance(node, list):
            for child in node:
                cls._inline_reference_siblings(child, root, active)
        elif isinstance(node, dict):
            if "$ref" in node and len(node) > 1:
                ref = node["$ref"]
                if (
                    not isinstance(ref, str)
                    or not ref.startswith("#/$defs/")
                    or ref in active
                    or len(active) >= MAX_JSON_DEPTH
                ):
                    raise ValueError("Unsupported spec wire reference expansion")
                name = ref.removeprefix("#/$defs/")
                target = root.get("$defs", {}).get(name)
                if not isinstance(target, dict):
                    raise ValueError("Unknown spec wire schema reference")
                expanded = {**copy.deepcopy(target), **node}
                expanded.pop("$ref")
                node.clear()
                node.update(expanded)
                cls._inline_reference_siblings(node, root, (*active, ref))
            else:
                for child in node.values():
                    cls._inline_reference_siblings(child, root, active)

    @staticmethod
    def parse_json(text: str) -> dict[str, Any]:
        """Parse raw completion text without duplicate-key loss or tolerant repair."""
        value = _parse_value(text)
        if type(value) is not dict:
            raise ValueError("Spec wire response must be an object")
        return value

    def encode(self, data: dict[str, Any]) -> dict[str, Any]:
        """Encode JSON domain data, retaining incomplete prior repair candidates."""
        _check_json(data)
        wire = self._walk(data, self._domain_schema, encode=True)
        _check_json(wire)
        return wire

    def decode(self, data: dict[str, Any]) -> dict[str, Any]:
        """Decode the wire object before ordinary Arena domain validation."""
        _check_json(data)
        domain = self._walk(data, self._domain_schema, encode=False)
        _check_json(domain)
        return domain

    def _walk(self, value: Any, node: dict[str, Any], *, encode: bool) -> Any:
        if "$ref" in node:
            return self._walk(value, self._domain_schema["$defs"][node["$ref"].removeprefix("#/$defs/")], encode=encode)
        if "anyOf" in node:
            branches = [branch for branch in node["anyOf"] if (branch.get("type") == "null") == (value is None)]
            if len(branches) != 1:
                raise ValueError("Unsupported spec wire union")
            return self._walk(value, branches[0], encode=encode)
        if node.get("additionalProperties") is True:
            if encode:
                if type(value) is not dict:
                    raise ValueError("Spec domain params must be a map")
                return [
                    {
                        "key": key,
                        "value_json": json.dumps(item, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
                    }
                    for key, item in value.items()
                ]
            if type(value) is not list:
                raise ValueError("Spec wire params must be an entry array")
            result = {}
            for entry in value:
                if (
                    type(entry) is not dict
                    or set(entry) != {"key", "value_json"}
                    or type(entry["key"]) is not str
                    or type(entry["value_json"]) is not str
                ):
                    raise ValueError("Malformed spec wire parameter entry")
                if entry["key"] in result:
                    raise ValueError("Duplicate spec wire parameter key")
                result[entry["key"]] = _parse_value(entry["value_json"])
            return result
        kind = node.get("type")
        expected = {
            "object": (dict,),
            "array": (list,),
            "string": (str,),
            "number": (int, float),
            "integer": (int,),
            "boolean": (bool,),
            "null": (type(None),),
        }
        if kind not in expected or type(value) not in expected[kind]:
            raise ValueError("Spec wire value does not match schema type")
        if kind == "object":
            properties = node["properties"]
            if set(value) - set(properties) or (not encode and set(value) != set(properties)):
                raise ValueError("Spec wire object has missing or unexpected fields")
            return {key: self._walk(item, properties[key], encode=encode) for key, item in value.items()}
        if kind == "array":
            if len(value) < node.get("minItems", 0) or len(value) > node.get("maxItems", MAX_JSON_NODES):
                raise ValueError("Spec wire array length does not match schema")
            item_schema = node.get("items", node.get("prefixItems", [{}])[0])
            return [self._walk(item, item_schema, encode=encode) for item in value]
        if kind == "string" and len(value) < node.get("minLength", 0):
            raise ValueError("Spec wire string is too short")
        if "enum" in node and value not in node["enum"]:
            raise ValueError("Spec wire value does not match enum")
        return value

    @classmethod
    def _adapt_schema(cls, node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                cls._adapt_schema(item)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" and node.get("additionalProperties") is not False:
            if node.get("properties") or node.get("additionalProperties") is not True:
                raise ValueError("Unsupported freeform map schema")
            description = node.get("description", "Freeform parameters.")
            node.clear()
            node.update(
                type="array",
                description=description + " Wire format: unique key/value_json entries; [] is an empty map.",
                items={
                    "type": "object",
                    "properties": {"key": {"type": "string"}, "value_json": {"type": "string"}},
                    "required": ["key", "value_json"],
                    "additionalProperties": False,
                },
            )
        if "prefixItems" in node:
            items = node.pop("prefixItems")
            if not items or any(item != items[0] for item in items) or "items" in node:
                raise ValueError("Unsupported heterogeneous tuple schema")
            node["items"] = copy.deepcopy(items[0])
        for value in node.values():
            cls._adapt_schema(value)
