# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Validation helpers for agent-generated environment graph specs."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from pydantic import ValidationError

from isaaclab_arena.assets.registries import TaskRegistry
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environment_spec.execution_catalogue import current_catalogue

if TYPE_CHECKING:
    from isaaclab_arena.agentic_environment_generation.catalogues import (
        AssetCatalogue,
        RelationCatalogue,
        TaskCatalogue,
    )


_ASSERTION_FAILED_PREFIX = "Assertion failed, "
_TASK_CATALOGUE_EXCLUDED_PARAMS = frozenset({"task_description"})


def _clean_validation_msg(msg: str) -> str:
    """Strip pydantic's assertion wrapper from validator error text."""
    if msg.startswith(_ASSERTION_FAILED_PREFIX):
        return msg[len(_ASSERTION_FAILED_PREFIX) :]
    return msg


def format_validation_error(exc: ValidationError) -> list[str]:
    """Flatten a Pydantic ``ValidationError`` into human-readable trace lines."""
    lines: list[str] = []
    for err in exc.errors():
        msg = _clean_validation_msg(err["msg"])
        loc = ".".join(str(part) for part in err["loc"])
        lines.append(f"{loc}: {msg}" if loc else msg)
    return lines


def required_task_init_param_names(task_cls: type) -> list[str]:
    """Return required ``__init__`` parameter names for a task class."""
    signature = inspect.signature(task_cls.__init__)
    return [
        name
        for name, param in signature.parameters.items()
        if name != "self"
        and name not in _TASK_CATALOGUE_EXCLUDED_PARAMS
        and param.default is inspect.Parameter.empty
        and param.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]


def collect_agent_ready_task_validation_traces(spec: ArenaEnvGraphSpec) -> list[str]:
    """Return validation trace lines for subtasks against ``TaskRegistry`` or active execution catalogue."""
    traces: list[str] = []
    catalogue = current_catalogue()
    task_registry = TaskRegistry() if catalogue is None else None
    for task in spec.task.subtasks:
        if catalogue is None:
            assert task_registry is not None
            task_cls = task_registry.get_task_by_name(task.kind)
            if not getattr(task_cls, "agent_ready", False):
                traces.append(f"Task {task.kind!r} is not agent-ready")
            required = required_task_init_param_names(task_cls)
        else:
            if task.kind not in catalogue.task_parameters:
                traces.append(f"Task {task.kind!r} is not agent-ready")
                continue
            required = list(catalogue.task_parameters[task.kind])
        for required_param in required:
            if required_param not in task.params:
                traces.append(f"Task {task.kind!r} is missing required param {required_param!r}")
    return traces


def collect_agent_ready_validation_trace(
    spec: ArenaEnvGraphSpec,
    asset_catalog: AssetCatalogue | None = None,
    task_catalog: TaskCatalogue | None = None,
    relation_catalog: RelationCatalogue | None = None,
) -> list[str]:
    """Return spec violations against the exact catalogues exposed to the agent."""
    if asset_catalog is None and task_catalog is None and relation_catalog is None:
        return collect_agent_ready_task_validation_traces(spec)

    traces: list[str] = []
    catalogue = current_catalogue()

    if asset_catalog is not None:
        # Check every registry_name against the asset catalogue the agent was given.
        asset_names = {
            "EMBODIMENTS": {entry["name"] for entry in asset_catalog.embodiments},
            "BACKGROUNDS": {entry["name"] for entry in asset_catalog.backgrounds},
            "OBJECTS": {entry["name"] for entry in asset_catalog.objects},
        }
        # Embodiment and background are required singles; flag any name outside the catalogue.
        if spec.embodiment.registry_name not in asset_names["EMBODIMENTS"]:
            traces.append(
                f"Embodiment registry_name {spec.embodiment.registry_name!r} is not in the EMBODIMENTS catalog"
            )
        if spec.background.registry_name not in asset_names["BACKGROUNDS"]:
            traces.append(
                f"Background registry_name {spec.background.registry_name!r} is not in the BACKGROUNDS catalog"
            )
        # Each movable object must resolve to a known OBJECTS entry.
        for obj in spec.objects:
            if obj.registry_name not in asset_names["OBJECTS"]:
                traces.append(f"Object {obj.id!r} registry_name {obj.registry_name!r} is not in the OBJECTS catalog")
        # Object-set members are registry names too; validate each one the same way.
        for object_set in spec.object_sets or []:
            for member in object_set.members:
                if member not in asset_names["OBJECTS"]:
                    traces.append(
                        f"Object set {object_set.id!r} member registry_name {member!r} is not in the OBJECTS catalog"
                    )

    if task_catalog is not None:
        # Check each subtask kind and its params against the task catalogue.
        task_entries = {entry.name: entry for entry in task_catalog.tasks}
        for task in spec.task.subtasks:
            entry = task_entries.get(task.kind)
            # Unknown task kinds cannot be repaired via params; skip further checks.
            if entry is None:
                traces.append(f"Task {task.kind!r} is not in the TASKS catalog")
                continue
            # Required params must be present; anything outside required|optional is rejected.
            for required_param in entry.required_params:
                if required_param not in task.params:
                    traces.append(f"Task {task.kind!r} is missing required param {required_param!r}")
            if catalogue is None:
                supported_params = set(entry.required_params) | set(entry.optional_params)
                for unsupported_param in sorted(set(task.params) - supported_params):
                    traces.append(
                        f"Task {task.kind!r} has unsupported param {unsupported_param!r}; "
                        f"supported params are {sorted(supported_params)!r}"
                    )
    else:
        traces.extend(collect_agent_ready_task_validation_traces(spec))

    if relation_catalog is not None:
        # Check each relation kind and its params against the relation catalogue.
        relation_entries = {entry.name: entry for entry in relation_catalog.relations}
        for relation in spec.relations:
            entry = relation_entries.get(relation.kind)
            # Same pattern as tasks: unknown kinds first, then required/unsupported params.
            if entry is None:
                traces.append(f"Relation {relation.kind!r} is not in the RELATIONS catalog")
                continue
            for required_param in entry.required_params:
                if required_param not in relation.params:
                    traces.append(f"Relation {relation.kind!r} is missing required param {required_param!r}")
            if catalogue is None:
                supported_params = set(entry.required_params) | set(entry.optional_params)
                for unsupported_param in sorted(set(relation.params) - supported_params):
                    traces.append(
                        f"Relation {relation.kind!r} has unsupported param {unsupported_param!r}; "
                        f"supported params are {sorted(supported_params)!r}"
                    )
    return traces
