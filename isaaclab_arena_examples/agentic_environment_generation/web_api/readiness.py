# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Separate adapter/configuration metadata from explicitly requested dependency probes."""

import asyncio
import importlib.util
import socket
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from . import graph_access
from .evaluation_profiles import PROFILES
from .public_records import protect_public_record
from .security import require_mutation, require_session

router = APIRouter(prefix="/api/editor/readiness")
_PROBE_SLOT = threading.BoundedSemaphore(1)


class CheckInput(BaseModel):
    """Only server-configured targets can be checked."""

    model_config = ConfigDict(extra="forbid", strict=True)


def graph_configuration_status(config):
    """Preserve literal database identity while checking the retriever's accepted bounds."""
    if config is None:
        return "not_configured"
    database = config["database"]
    if not 0 < len(database) <= 128 or database.strip() != database:
        return "invalid_configuration"
    return "not_checked"


def metadata(request, session):
    """Project configuration without importing SDKs or contacting dependencies."""
    state = request.app.state
    provider = state.model_settings.status(session, state.session_keys_allowed)
    graph = graph_access.configuration()
    return {
        "schema_version": 1,
        "checked_at": None,
        "provider": {"configured": provider["configured"], "source": provider["source"], "verification": "not_checked"},
        "graph": {"configured": graph is not None, "status": graph_configuration_status(graph)},
        "dependencies": {name: importlib.util.find_spec(name) is not None for name in ("openai", "neo4j", "isaacsim")},
        "runtime": {
            "build_adapter": state.editor_execution.build_available,
            "evaluation_adapter": state.editor_execution.evaluation_available,
            "simulation": "not_checked",
        },
        "policy_servers": [
            {"profile": row["id"], "host": row["remote_host"], "port": row["remote_port"], "status": "not_checked"}
            for row in PROFILES
        ],
        "workflow": {
            "research_versions": bool(state.research_roots),
            "publication": state.publication_admitting is True,
            "managed_retrieval": state.managed_retrieval_enabled,
            "scenario_harness": "cli_only",
            "evaluation_scope": "droid_fixed_profiles",
        },
    }


def probe_graph(config):
    """Check one explicit database with a bounded, rolled-back read, never fallback defaults."""
    configured = graph_configuration_status(config)
    if configured != "not_checked":
        return configured
    try:
        from neo4j.exceptions import AuthError

        from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver
    except ImportError:
        return "dependency_unavailable"
    driver = None
    status = "unavailable"
    try:
        driver = get_neo4j_driver(
            uri=config["uri"],
            user=config["user"],
            password=config["password"],
            connection_timeout=3,
            connection_acquisition_timeout=3,
            max_connection_pool_size=1,
            max_transaction_retry_time=0,
        )
        with driver.session(database=config["database"], default_access_mode="READ") as session:
            with session.begin_transaction(timeout=3) as transaction:
                try:
                    record = transaction.run("RETURN 1 AS ready").single()
                    if record is not None and record["ready"] == 1:
                        status = "available"
                finally:
                    transaction.rollback()
    except AuthError:
        status = "authentication_failed"
    except Exception:
        status = "unavailable"
    finally:
        if driver is not None:
            try:
                driver.close()
            except Exception:
                status = "unavailable"
    return status


def probe_policy(row):
    """Report TCP reachability only, not protocol, checkpoint or policy compatibility."""
    try:
        with socket.create_connection((row["remote_host"], row["remote_port"]), timeout=1):
            return "reachable"
    except OSError:
        return "unreachable"


def probe_dependencies(config):
    """Hold the slot until every synchronous probe has actually returned, even after HTTP timeout."""
    try:
        return probe_graph(config), [probe_policy(row) for row in PROFILES]
    finally:
        _PROBE_SLOT.release()


@router.get("")
async def readiness(request: Request, session=Depends(require_session)):
    return protect_public_record(request, metadata(request, session))


@router.post("/check")
async def check(request: Request, body: CheckInput, session=Depends(require_mutation)):
    """Explicitly probe the authorized server graph target and fixed local policy TCP ports."""
    config = graph_access.configuration()
    if not _PROBE_SLOT.acquire(blocking=False):
        raise HTTPException(429, "A dependency check is still running; wait before checking again")
    # Cancellation must not release a still-running thread's slot or publish its late result.
    task = asyncio.create_task(asyncio.to_thread(probe_dependencies, config))
    try:
        graph_status, policy_statuses = await asyncio.wait_for(asyncio.shield(task), timeout=8)
    except TimeoutError:
        graph_status, policy_statuses = "timeout", ["not_checked"] * len(PROFILES)
    current = require_session(request)
    result = metadata(request, current)
    result["checked_at"] = time.time()
    result["graph"]["status"] = graph_status if config == graph_access.configuration() else "configuration_changed"
    for row, status in zip(result["policy_servers"], policy_statuses, strict=True):
        row["status"] = status
    return protect_public_record(request, result)
