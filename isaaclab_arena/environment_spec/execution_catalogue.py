# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit workflow vocabulary; no simulator discovery or implementation loading."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType

_ACTIVE: ContextVar[ExecutionCatalogue | None] = ContextVar("execution_catalogue", default=None)


def _entries(rows, fields):
    assert isinstance(rows, list), "Catalogue entries must be a list"
    entries = {}
    for row in rows:
        assert isinstance(row, dict) and set(row) == fields, "Invalid catalogue entry fields"
        name = row["name"]
        assert isinstance(name, str) and name and name not in entries, "Invalid or duplicate catalogue name"
        entries[name] = row
    return entries


@dataclass(frozen=True, init=False)
class ExecutionCatalogue:
    """Snapshot only the vocabulary supplied by an execution adapter, not the whole simulator."""

    _json: str
    asset_names: frozenset[str]
    relation_arities: Mapping[str, bool]
    task_parameters: Mapping[str, tuple[str, ...]]

    def __init__(self, payload: dict):
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        assert len(encoded.encode()) <= 2 * 1024 * 1024, "Execution catalogue is too large"
        value = json.loads(encoded)
        assert set(value) == {"assets", "relations", "tasks"}, "Complete explicit vocabulary required"
        assert set(value["assets"]) == {"embodiments", "backgrounds", "objects"}, "Invalid asset groups"
        assert set(value["relations"]) == {"relations"} and set(value["tasks"]) == {"tasks"}
        assets = set()
        for rows in value["assets"].values():
            entries = _entries(rows, {"name", "tags"})
            assert not assets.intersection(entries), "Duplicate asset across catalogue groups"
            for row in entries.values():
                assert isinstance(row["tags"], list) and all(isinstance(tag, str) for tag in row["tags"])
            assets.update(entries)
        relations = _entries(value["relations"]["relations"], {"name", "unary", "summary"})
        assert all(type(row["unary"]) is bool and isinstance(row["summary"], str) for row in relations.values())
        tasks = _entries(value["tasks"]["tasks"], {"name", "required_params", "summary"})
        for row in tasks.values():
            params = row["required_params"]
            assert isinstance(params, list) and all(isinstance(name, str) and name for name in params)
            assert len(set(params)) == len(params) and isinstance(row["summary"], str)
        object.__setattr__(self, "_json", encoded)
        object.__setattr__(self, "asset_names", frozenset(assets))
        object.__setattr__(
            self, "relation_arities", MappingProxyType({name: row["unary"] for name, row in relations.items()})
        )
        object.__setattr__(
            self,
            "task_parameters",
            MappingProxyType({name: tuple(row["required_params"]) for name, row in tasks.items()}),
        )

    @property
    def sha256(self) -> str:
        """Hash the actual supplied vocabulary using the existing catalogue codec."""
        return hashlib.sha256(self._json.encode()).hexdigest()

    def payload(self) -> dict:
        """Return a detached copy of the adapter's vocabulary."""
        return json.loads(self._json)

    @contextmanager
    def activate(self):
        """Use this vocabulary for nested schema calls in this execution context only."""
        token = _ACTIVE.set(self)
        try:
            yield self
        finally:
            _ACTIVE.reset(token)

    def catalogues(self):
        """Build the existing prompt formatters from the supplied entries, without registries."""
        from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
            AssetCatalogue,
            RelationCatalogue,
            RelationCatalogueEntry,
            TaskCatalogue,
            TaskCatalogueEntry,
        )

        value = self.payload()
        return (
            AssetCatalogue(**value["assets"]),
            RelationCatalogue([RelationCatalogueEntry(**row) for row in value["relations"]["relations"]]),
            TaskCatalogue([TaskCatalogueEntry(**row) for row in value["tasks"]["tasks"]]),
        )

    def validate_document(self, text):
        """Validate actual YAML/schema rules against this explicit adapter vocabulary."""
        from isaaclab_arena.agentic_environment_generation.workbench.document_yaml import (
            parse_yaml,
            reject_unknown_fields,
        )
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        with self.activate():
            value = parse_yaml(text)
            reject_unknown_fields(value)
            return dict(valid=True, spec=ArenaEnvGraphSpec.model_validate(value).model_dump(mode="json"))


def current_catalogue(info=None) -> ExecutionCatalogue | None:
    """Return explicit Pydantic context or the scoped adapter vocabulary; otherwise keep legacy lookup."""
    context = getattr(info, "context", None)
    if isinstance(context, dict) and "execution_catalogue" in context:
        value = context["execution_catalogue"]
        if isinstance(value, ExecutionCatalogue):
            return value
        if isinstance(value, dict):
            return ExecutionCatalogue(value)
        raise ValueError("Explicit execution catalogue is missing")
    return _ACTIVE.get()
