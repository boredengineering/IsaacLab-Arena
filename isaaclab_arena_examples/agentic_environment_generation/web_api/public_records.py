# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Current-policy screening at public boundaries, never rewriting durable records."""
import re

import yaml
from fastapi import HTTPException

from isaaclab_arena.agentic_environment_generation.workbench.document_yaml import MAX_YAML_BYTES, parse_yaml


def protect_yaml(request, text):
    """Guard raw YAML and escape spellings before errors can quote source excerpts."""
    _protect_yaml(text, request.app.state.model_settings.protect_public)


def _protect_yaml(text, protect_literal):
    protect_literal(text)

    def decode(match):
        value = int(match.group()[2:], 16)
        return chr(value) if value <= 0x10FFFF else match.group()

    # This is a conservative secret check, not a parser: malformed YAML must still
    # receive the normal validation diagnostics when it contains no credential.
    unfolded = re.sub(r"\\(?:\r\n|[\r\n])[ \t]*", "", text)
    decoded = re.sub(r"\\(?:x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})", decode, unfolded)
    protect_literal(decoded)
    try:
        parsed = parse_yaml(text)
    except (ValueError, yaml.YAMLError, TypeError):
        return  # Documents.validate owns invalid-YAML diagnostics.
    protect_literal(parsed)
    return parsed


def protect_public_record(request, record):
    """Preserve the shared request wrapper for editor, jobs and events."""
    return screen_public_record(record, request.app.state.model_settings.protect_public)


def screen_public_record(record, protect_literal):
    """Screen complete records and nested YAML under current policy, without source reads.

    Retain the policy's whole-record bounds; additionally bound each YAML string
    to 256 KiB and decoding work to 40 levels, 131072 nodes and 8 MiB of text.
    Refuse an unscreenable record as a whole, never truncate or rewrite it.
    """
    protect_literal(record)
    nodes = 0
    text_bytes = 0

    def check(value, depth=0):
        nonlocal nodes, text_bytes
        nodes += 1
        if depth > 40 or nodes > 131072:
            raise HTTPException(422, "Invalid request input")
        if isinstance(value, str):
            size = len(value.encode("utf-8"))
            text_bytes += size
            if size > MAX_YAML_BYTES or text_bytes > 8 * 1024 * 1024:
                raise HTTPException(422, "Invalid request input")
            parsed = _protect_yaml(value, protect_literal)
            if parsed is not None:
                check(parsed, depth + 1)
        elif isinstance(value, dict):
            for key, child in value.items():
                check(key, depth + 1)
                check(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                check(child, depth + 1)

    check(record)
    return record
