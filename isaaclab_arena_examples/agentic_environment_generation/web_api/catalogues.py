# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Authenticated schema and registered agent vocabulary, without agent construction."""

import asyncio
import hashlib
import json
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

from .security import require_session

router = APIRouter(prefix="/api/editor", dependencies=[Depends(require_session)])


def _digest(value):
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(text.encode()) > 2 * 1024 * 1024:
        raise ValueError("Metadata exceeds response budget")
    return hashlib.sha256(text.encode()).hexdigest()


@router.get("/schema")
async def schema(request: Request):
    value = ArenaEnvGraphSpec.model_json_schema()
    request.app.state.model_settings.protect_public(value)
    return {"schema_version": 1, "read_only": True, "schema": value, "schema_sha256": _digest(value)}


def execution_catalogue_sha256(*, assets=None, relations=None, tasks=None):
    """Hash the canonical execution vocabulary; omitted catalogues use current registries."""
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        build_asset_catalogue,
        build_relation_catalogue,
        build_task_catalogue,
    )

    return _digest({
        "assets": asdict(build_asset_catalogue() if assets is None else assets),
        "relations": asdict(build_relation_catalogue() if relations is None else relations),
        "tasks": asdict(build_task_catalogue() if tasks is None else tasks),
    })


def catalogue_snapshot():
    """Build the same registered vocabulary used by generation without creating an agent."""
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        build_asset_catalogue,
        build_relation_catalogue,
        build_task_catalogue,
    )

    catalogues = {
        "assets": asdict(build_asset_catalogue()),
        "relations": asdict(build_relation_catalogue()),
        "tasks": asdict(build_task_catalogue()),
    }
    return {"schema_version": 1, "read_only": True, "catalogues": catalogues, "catalogue_sha256": _digest(catalogues)}


@router.get("/catalogues")
async def catalogues(request: Request):
    try:
        result = await asyncio.to_thread(catalogue_snapshot)
    except (ImportError, ValueError, RuntimeError):
        raise HTTPException(503, "Registered catalogue unavailable") from None
    request.app.state.model_settings.protect_public(result)
    return result
