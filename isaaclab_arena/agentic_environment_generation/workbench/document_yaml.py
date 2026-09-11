# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded YAML parsing and strict field checks at the untrusted editor boundary."""

import yaml

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

MAX_YAML_BYTES = 256 * 1024


class EditorLoader(yaml.SafeLoader):
    """Reject aliases, excessive nesting and duplicate mapping keys before construction."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("YAML aliases are not supported in editor documents")
        depth = getattr(self, "editor_depth", 0)
        if depth >= 40:
            raise ValueError("YAML nesting exceeds 40 levels")
        self.editor_depth = depth + 1
        try:
            return super().compose_node(parent, index)
        finally:
            self.editor_depth = depth

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError("YAML mapping keys must be strings")
            if key in result:
                raise ValueError(f"Duplicate YAML key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def parse_yaml(text):
    if len(text.encode("utf-8")) > MAX_YAML_BYTES:
        raise ValueError("YAML exceeds 256 KiB")
    data = yaml.load(text, Loader=EditorLoader)
    if not isinstance(data, dict):
        raise ValueError("Environment YAML must be a mapping")
    return data


def reject_unknown_fields(data):
    """Reject ignored model fields while keeping open-ended params dictionaries."""
    schema = ArenaEnvGraphSpec.model_json_schema()

    def visit(value, node, path):
        if "$ref" in node:
            node = schema["$defs"][node["$ref"].rsplit("/", 1)[1]]
        if "anyOf" in node:
            for variant in node["anyOf"]:
                visit(value, variant, path)
        if isinstance(value, dict) and "properties" in node:
            unknown = value.keys() - node["properties"].keys()
            if unknown:
                raise ValueError(f"Unknown fields at {path}: {', '.join(sorted(unknown))}")
            for key, child in value.items():
                visit(child, node["properties"][key], f"{path}.{key}")
        if isinstance(value, list) and "items" in node:
            for child in value:
                visit(child, node["items"], path + "[]")

    visit(data, schema, "spec")
