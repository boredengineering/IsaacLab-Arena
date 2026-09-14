# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded operator-only research profile configuration, never store initialization."""

from pathlib import Path

from isaaclab_arena.agentic_environment_generation.workbench.research_registry import MAX_STORES, checked_identifier

from .execution_grants import _bounded_copy
from .graph_access import checked_graph_config


def configured_publication_profiles(mapping):
    """Detach at most 16 explicit private profiles; never consult environment or IO."""
    if mapping is None:
        return {}
    try:
        if type(mapping) is not dict or len(mapping) > 16:
            raise ValueError
        result = {}
        for profile_id, profile in mapping.items():
            checked_identifier(profile_id)
            profile = _bounded_copy(profile)
            if type(profile) is not dict or set(profile) != {"connection", "immutable_scope"}:
                raise ValueError
            if profile["immutable_scope"] is not True:
                raise ValueError
            result[profile_id] = {"connection": checked_graph_config(profile["connection"]), "immutable_scope": True}
        return result
    except Exception:
        raise ValueError("Invalid publication profile configuration") from None


def configured_research_roots(mapping):
    """Validate explicit absolute managed paths without resolving or touching them."""
    if mapping is None:
        return {}
    if type(mapping) is not dict or len(mapping) > MAX_STORES:
        raise ValueError("Invalid managed store profile configuration")
    result = {}
    for store_id, root in mapping.items():
        checked_identifier(store_id)
        if not isinstance(root, (str, Path)):
            raise ValueError("Invalid managed store root")
        text = str(root)
        if (
            not text.startswith("/")
            or len(text.encode()) > 4096
            or any(ord(c) < 32 for c in text)
            or any(part in {".", "..", "generated_envs", "eval_output"} for part in text.split("/"))
        ):
            raise ValueError("Managed store root must be explicit and outside legacy outputs")
        result[store_id] = Path(text)
    return result


def parse_research_roots(entries):
    """Parse repeatable ID=absolute-path options without implicit overrides."""
    result = {}
    for entry in entries:
        if type(entry) is not str or "=" not in entry:
            raise ValueError("Expected managed store ID=absolute-path")
        store_id, root = entry.split("=", 1)
        if store_id in result:
            raise ValueError("Duplicate managed store profile")
        result[store_id] = root
    return configured_research_roots(result)
