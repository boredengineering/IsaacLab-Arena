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
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import graph_access
from .evaluation_profiles import configured_profiles
from .policy_endpoint import configured_gr00t_port
from .provider_readiness import PROVIDER_CODES
from .public_records import protect_public_record
from .resource_readiness import RESOURCE_CODES
from .security import require_mutation, require_session

router = APIRouter(prefix="/api/editor/readiness")
_PROBE_SLOT = threading.BoundedSemaphore(1)


class CheckInput(BaseModel):
    """Only server-configured targets can be checked."""

    model_config = ConfigDict(extra="forbid", strict=True)


class CheckInputV2(BaseModel):
    """Authorize dependency reads, not inference, simulation or durable effects."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[2]
    workflow: Literal["agentic_generation", "a2_gr00t", "graph_generation", "build"]
    check_provider: bool = False
    prompt: str | None = Field(default=None, min_length=1, max_length=16000)
    yaml_text: str | None = Field(default=None, max_length=256 * 1024)
    document_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @model_validator(mode="before")
    @classmethod
    def literal_fields(cls, value):
        if type(value) is not dict or type(value.get("schema_version")) is not int:
            raise ValueError("Invalid readiness schema version")
        if any(
            key in value and type(value[key]) is not str
            for key in ("prompt", "yaml_text", "document_id")
        ):
            raise ValueError("Optional readiness fields must be strings when supplied")
        return value

    @field_validator("yaml_text")
    @classmethod
    def yaml_bound(cls, value):
        if value is not None and len(value.encode()) > 256 * 1024:
            raise ValueError("YAML exceeds bound")
        return value

    @model_validator(mode="after")
    def selection(self):
        if self.prompt is not None and not self.prompt.strip():
            raise ValueError("Prompt must not be blank")
        if self.document_id is not None and self.yaml_text is None:
            raise ValueError("Document requires a draft")
        return self


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
        "provider": {
            "configured": provider["configured"],
            "source": provider["source"],
            "verification": "not_checked",
        },
        "graph": {
            "configured": graph is not None,
            "status": graph_configuration_status(graph),
        },
        "dependencies": {
            name: importlib.util.find_spec(name) is not None
            for name in ("openai", "neo4j", "isaacsim")
        },
        "runtime": {
            "build_adapter": state.editor_execution.build_available,
            "evaluation_adapter": state.editor_execution.evaluation_available,
            "simulation": "not_checked",
        },
        "policy_servers": [
            {
                "profile": row["id"],
                "host": row["remote_host"],
                "port": row["remote_port"],
                "status": "not_checked",
            }
            for row in configured_profiles()
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

        from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import (
            get_neo4j_driver,
        )
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
        with driver.session(
            database=config["database"], default_access_mode="READ"
        ) as session:
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
        with socket.create_connection(
            (row["remote_host"], row["remote_port"]), timeout=1
        ):
            return "reachable"
    except OSError:
        return "unreachable"


def probe_dependencies(config, profiles):
    """Hold the slot until every synchronous probe has actually returned, even after HTTP timeout."""
    try:
        return probe_graph(config), [probe_policy(row) for row in profiles]
    finally:
        _PROBE_SLOT.release()


# Legacy identifiers remain explicit API contracts, not dashboard selections.
WORKFLOWS = ("agentic_generation", "a2_gr00t", "graph_generation", "build")
READINESS_CODES = (
    RESOURCE_CODES
    + PROVIDER_CODES
    + (
        "not_required",
        "not_checked",
        "api_contract_available",
        "api_contract_unavailable",
        "runtime_not_checked",
        "runtime_available",
        "runtime_unavailable",
        "generation_not_configured",
        "generation_configuration_only",
        "graph_not_configured",
        "graph_invalid_configuration",
        "graph_not_checked",
        "graph_retrieval_measured",
        "graph_retrieval_structural",
        "graph_retrieval_empty",
        "graph_retrieval_unavailable",
        "configuration_changed",
        "check_timeout",
        "policy_protocol_available",
        "policy_protocol_unavailable",
        "policy_modality_mismatch",
        "policy_expectation_missing",
        "policy_model_verified",
        "policy_model_mismatch",
        "policy_metadata_unavailable",
        "policy_transport_unverified",
        "policy_transport_verified",
        "policy_instance_mismatch",
        "openpi_verification_unsupported",
    )
)
READINESS_CHECKS = (
    "api_contract",
    "runtime",
    "generation_model",
    "graph",
    "policy_protocol",
    "policy_model",
    "policy_transport",
    "gpu",
)


# Versioned source contract matrix. These are inspected, never HTTP-dispatched.
COMMON_ROUTES = (
    ("GET", "/api/health"),
    ("GET", "/api/editor"),
    ("GET", "/api/editor/schema"),
    ("GET", "/api/editor/catalogues"),
    ("POST", "/api/sessions"),
    ("GET", "/api/session"),
    ("POST", "/api/session/activity"),
    ("POST", "/api/editor/validate"),
    ("GET", "/api/jobs/{job_id}"),
    ("GET", "/api/jobs"),
    ("GET", "/api/workspaces/default"),
)
WORKFLOW_ROUTES = {
    "agentic_generation": (
        ("GET", "/api/model-settings"),
        ("POST", "/api/editor/generate"),
        ("GET", "/api/editor/generate/operations/{idempotency_key}"),
        ("POST", "/api/editor/build"),
    ),
    "a2_gr00t": (
        ("GET", "/api/editor/evaluation-profiles"),
        ("POST", "/api/editor/evaluate"),
        ("GET", "/api/editor/evaluations/{job_id}/artifacts/{name}"),
    ),
    "build": (("POST", "/api/editor/build"),),
    "graph_generation": (
        ("GET", "/api/model-settings"),
        ("POST", "/api/editor/generate"),
        ("GET", "/api/editor/generate/operations/{idempotency_key}"),
    ),
}


def api_contract_available(request, workflow):
    """Require actual registered contracts and the same static execution capability flags."""
    from .editor import BuildDraft, Draft, GenerateDraft, SnapshotDraft
    from .evaluate import EvaluateDraft

    routes = {
        (method, route.path): route
        for route in request.app.routes
        for method in getattr(route, "methods", ())
    }
    execution = request.app.state.editor_execution
    required_routes = COMMON_ROUTES + WORKFLOW_ROUTES[workflow]
    # The editor advertises snapshots only while its adapter exists. Inspection
    # and Build remain useful without it; never contact or create the renderer.
    if workflow == "agentic_generation" and execution.snapshots is not None:
        required_routes += (
            ("POST", "/api/editor/snapshots"),
            ("GET", "/api/editor/previews/{canonical_hash}"),
            ("GET", "/api/editor/artifacts/{artifact_id}"),
        )
    if not all(key in routes for key in required_routes):
        return False
    for path, model in (
        ("/api/editor/validate", Draft),
        ("/api/editor/build", BuildDraft),
        ("/api/editor/evaluate", EvaluateDraft),
        ("/api/editor/generate", GenerateDraft),
        ("/api/editor/snapshots", SnapshotDraft),
    ):
        if ("POST", path) not in required_routes:
            continue
        params = getattr(routes[("POST", path)], "dependant", None)
        if params is None or not any(
            field.type_ is model for field in params.body_params
        ):
            return False
    return {
        "agentic_generation": execution.build_available is True,
        "a2_gr00t": execution.evaluation_available is True,
        "build": execution.build_available is True,
        "graph_generation": True,
    }[workflow]


def metadata_v2(request, session, workflow, *, check_provider=False):
    """Report contract/configuration observations without creating runtime evidence."""
    required = {"api_contract", "runtime"}
    if workflow in ("agentic_generation", "graph_generation"):
        required.update(("generation_model", "graph"))
    if workflow != "graph_generation":
        required.add("gpu")
    if workflow == "a2_gr00t":
        required.update(
            ("graph", "policy_protocol", "policy_model", "policy_transport")
        )
    if check_provider:
        required.add("generation_model")
    rows = {
        key: {
            "id": key,
            "status": "not_checked" if key in required else "not_required",
            "code": "not_checked" if key in required else "not_required",
            "required": key in required,
        }
        for key in READINESS_CHECKS
    }
    contract = api_contract_available(request, workflow)
    rows["api_contract"].update(
        status="passed" if contract else "unavailable",
        code="api_contract_available" if contract else "api_contract_unavailable",
    )
    rows["runtime"]["code"] = "runtime_not_checked"
    if "gpu" in required:
        rows["gpu"]["code"] = "resource_unknown"
    if "generation_model" in required:
        provider = request.app.state.model_settings.status(
            session, request.app.state.session_keys_allowed
        )
        rows["generation_model"]["code"] = (
            "generation_configuration_only"
            if provider["configured"]
            else "generation_not_configured"
        )
    if "graph" in required:
        configured = graph_configuration_status(graph_access.configuration())
        rows["graph"]["code"] = {
            "not_configured": "graph_not_configured",
            "invalid_configuration": "graph_invalid_configuration",
            "not_checked": "graph_not_checked",
        }[configured]
    return {
        "schema_version": 2,
        "workflow": workflow,
        "checked_at": None,
        "checks": list(rows.values()),
        "policy": None,
        "ready": False,
    }


@router.get("")
async def readiness(request: Request, session=Depends(require_session)):
    if not request.query_params:
        result = metadata(request, session)
    else:
        if (
            set(request.query_params) != {"version", "workflow"}
            or len(request.query_params.multi_items()) != 2
            or request.query_params["version"] != "2"
            or request.query_params["workflow"] not in WORKFLOWS
        ):
            raise HTTPException(422, "Invalid readiness selection")
        result = metadata_v2(request, session, request.query_params["workflow"])
    return protect_public_record(request, result)


def run_readiness_worker(envelope):
    """Dispatch through a private bounded worker, never the API's graph environment."""
    from .readiness_process import run_worker

    return run_worker(envelope)


async def checked_worker(envelope):
    """Retain the shared slot until worker completion or verified cleanup."""
    if not _PROBE_SLOT.acquire(blocking=False):
        raise HTTPException(
            429, "A dependency check is still running; wait before checking again"
        )

    def owned():
        try:
            return run_readiness_worker(envelope)
        finally:
            from .readiness_process import cleanup_pending

            if not cleanup_pending():
                _PROBE_SLOT.release()

    task = asyncio.create_task(asyncio.to_thread(owned))
    return await asyncio.wait_for(asyncio.shield(task), timeout=20)


async def check_v2(request, body, session):
    from .editor import frozen_draft
    from .policy_readiness import expected_hashes
    from .provider_readiness import capture_provider
    from .resource_readiness import configuration as resource_configuration

    protect_public_record(request, body.model_dump())
    if body.yaml_text is not None:
        frozen_draft(request, body.yaml_text, body.document_id)
    config = graph_access.configuration()
    if (
        body.workflow in ("agentic_generation", "graph_generation", "a2_gr00t")
        and graph_configuration_status(config) == "invalid_configuration"
    ):
        result = metadata_v2(
            request, session, body.workflow, check_provider=body.check_provider
        )
        next(row for row in result["checks"] if row["id"] == "graph")[
            "status"
        ] = "blocked"
        return protect_public_record(request, result)
    try:
        expectations = expected_hashes() if body.workflow == "a2_gr00t" else None
    except ValueError:
        expectations = None
    resources = (
        resource_configuration()
        if body.workflow in ("agentic_generation", "build", "a2_gr00t")
        else None
    )
    provider = (
        capture_provider(request.app.state, session) if body.check_provider else None
    )
    envelope = {
        "workflow": body.workflow,
        "prompt": body.prompt or "readiness dependency check",
        "graph_config": (
            config
            if body.workflow in ("agentic_generation", "graph_generation", "a2_gr00t")
            else None
        ),
        "expectations": expectations if body.workflow == "a2_gr00t" else None,
        "resource_config": resources,
        "check_provider": body.check_provider,
        "provider_config": provider["config"] if provider is not None else None,
    }
    if body.workflow == "a2_gr00t":
        try:
            envelope["gr00t_port"] = configured_gr00t_port()
        except ValueError:
            raise HTTPException(503, "configuration_changed") from None
    try:
        receipt = await checked_worker(envelope)
    except HTTPException:
        raise
    except Exception:
        receipt = {
            "runtime": "runtime_unavailable",
            "graph": "graph_retrieval_unavailable",
            "policy": None,
        }
    current = require_session(request)
    result = metadata_v2(
        request, current, body.workflow, check_provider=body.check_provider
    )
    result["checked_at"] = time.time()
    rows = {row["id"]: row for row in result["checks"]}
    if body.check_provider:
        code = receipt.get("provider", "generation_provider_unavailable")
        if provider != capture_provider(request.app.state, current):
            code = "configuration_changed"
        rows["generation_model"].update(
            required=True,
            code=code,
            status="passed" if code == "generation_model_readable" else "unavailable",
        )
    rows["runtime"].update(
        status="passed" if receipt["runtime"] == "runtime_available" else "unavailable",
        code=receipt["runtime"],
    )
    if resources is not None:
        code = receipt.get("gpu", "resource_unknown")
        if resources != resource_configuration():
            code = "configuration_changed"
        rows["gpu"].update(
            code=code,
            status="passed" if code == "resource_headroom_observed" else "blocked",
        )
    if body.workflow in ("agentic_generation", "graph_generation", "a2_gr00t"):
        code = (
            receipt["graph"]
            if config == graph_access.configuration()
            else "configuration_changed"
        )
        rows["graph"].update(
            code=code,
            status=(
                "passed"
                if code
                in (
                    "graph_retrieval_measured",
                    "graph_retrieval_structural",
                    "graph_retrieval_empty",
                )
                else "unavailable"
            ),
        )
    if body.workflow == "a2_gr00t" and receipt["policy"] is not None:
        observed = receipt["policy"]
        for key in ("policy_protocol", "policy_model", "policy_transport"):
            rows[key].update(observed[key])
        result["policy"] = observed["evidence"]
        try:
            current_expectations = expected_hashes()
        except ValueError:
            current_expectations = None
        try:
            current_port = configured_gr00t_port()
        except ValueError:
            current_port = None
        if expectations != current_expectations or envelope["gr00t_port"] != current_port:
            rows["policy_model"].update(status="mismatch", code="configuration_changed")
            rows["policy_transport"].update(
                status="not_checked", code="policy_transport_unverified"
            )
            result["policy"] = None
    result["ready"] = all(
        row["status"] == "passed" for row in rows.values() if row["required"]
    )
    return protect_public_record(request, result)


@router.post("/check")
async def check(
    request: Request, body: CheckInputV2 | CheckInput, session=Depends(require_mutation)
):
    """Explicitly probe server-configured dependencies without submitting jobs."""
    if isinstance(body, CheckInputV2):
        return await check_v2(request, body, session)
    config = graph_access.configuration()
    profiles = configured_profiles()
    if not _PROBE_SLOT.acquire(blocking=False):
        raise HTTPException(
            429, "A dependency check is still running; wait before checking again"
        )
    # Cancellation must not release a still-running thread's slot or publish its late result.
    task = asyncio.create_task(asyncio.to_thread(probe_dependencies, config, profiles))
    try:
        graph_status, policy_statuses = await asyncio.wait_for(
            asyncio.shield(task), timeout=8
        )
    except TimeoutError:
        graph_status, policy_statuses = "timeout", ["not_checked"] * len(profiles)
    current = require_session(request)
    result = metadata(request, current)
    result["checked_at"] = time.time()
    result["graph"]["status"] = (
        graph_status
        if config == graph_access.configuration()
        else "configuration_changed"
    )
    for row, captured, status in zip(result["policy_servers"], profiles, policy_statuses, strict=True):
        row["status"] = (
            status if (row["host"], row["port"]) == (captured["remote_host"], captured["remote_port"])
            else "not_checked"
        )
    return protect_public_record(request, result)
