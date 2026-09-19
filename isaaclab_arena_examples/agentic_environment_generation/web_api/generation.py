# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Server-configured generation adapter; no credentials or raw model traces cross HTTP."""

import os
import yaml
from pathlib import Path

from isaaclab_arena.agentic_environment_generation import inference_profiles as _inference_profiles
from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
from isaaclab_arena.agentic_environment_generation.workbench.generation_diagnostics import GENERATION_STAGES
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

from . import graph_access
from .catalogues import execution_catalogue_sha256
from .generation_diagnostics import SafeGenerationFailure
from .provider_security import bounded_client, checked_config, reject_secret

GENERATION_TIMEOUT = 180
freeze_configuration = _inference_profiles.freeze_configuration


def configuration():
    """Resolve only process-environment configuration, without reading credential files or probing endpoints."""
    providers = (
        ("OPENAI", "openai", "https://api.openai.com/v1", "gpt-6-astra"),
        ("GEMINI", "gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
        ("OPENROUTER", "openrouter", "https://openrouter.ai/api/v1", "anthropic/claude-sonnet-4.5"),
        ("NV", "nvidia", "https://inference-api.nvidia.com", "azure/anthropic/claude-opus-4-8"),
    )
    for prefix, provider, endpoint, model in providers:
        key = os.environ.get(f"{prefix}_API_KEY", "").strip()
        if not key:
            continue
        try:
            config = checked_config(
                {
                    "api_key": key,
                    "model": os.environ.get(f"{prefix}_MODEL") or model,
                    "base_url": os.environ.get(f"{prefix}_BASE_URL") or os.environ.get("BASE_URL") or endpoint,
                },
                trusted_server=True,
            )
        except ValueError:
            return None
        # Private pipe provenance, never accepted by the settings HTTP schema or
        # passed to the legacy agent. Session credentials retain fixed endpoints.
        return {**config, "provider": provider, "trusted_server": True}
    return None


def generate(inputs, emit, *, agent_factory=None, config=None, graph_config=None, managed_context=None, allowance=None):
    """Run a fresh bounded agent and return only schema-validated output and allowlisted stages."""
    if allowance is not None and config is None:
        raise ValueError("Explicit workflow provider configuration required")
    config = configuration() if config is None else config
    config = checked_config(config, trusted_server=isinstance(config, dict) and config.get("trusted_server") is True)
    if agent_factory is None:
        from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
            EnvironmentGenerationAgent,
        )

        with bounded_client(config, allowance=allowance):
            result = _generate(
                inputs,
                emit,
                agent_factory=EnvironmentGenerationAgent,
                config=config,
                graph_config=graph_config,
                managed_context=managed_context,
            )
    elif allowance is not None:
        with bounded_client(config, allowance=allowance):
            result = _generate(
                inputs,
                emit,
                agent_factory=agent_factory,
                config=config,
                graph_config=graph_config,
                managed_context=managed_context,
            )
    else:
        result = _generate(
            inputs,
            emit,
            agent_factory=agent_factory,
            config=config,
            graph_config=graph_config,
            managed_context=managed_context,
        )
    reject_secret(result, config["api_key"])
    reject_secret(result, (graph_config or {}).get("password"))
    return result


def _generate(inputs, emit, *, agent_factory, config, graph_config=None, managed_context=None):
    if managed_context is not None:
        from .managed_retrieval import checked_context

        if inputs.get("operation") != "new" or graph_config is None:
            raise ValueError("Managed retrieval requires authorized New generation")
        managed_context = checked_context(managed_context, graph_config)
    traces = []

    def progress(stage):
        if stage in GENERATION_STAGES:
            traces.append(stage)
            emit(stage)

    documents = Documents(Path("."))
    base = inputs.get("base_yaml")
    kwargs = {"publish_to_graph": False, "progress": progress}
    operation = inputs.get("operation")
    metadata = {}
    if operation is not None:
        if operation not in {"new", "refine"}:
            raise ValueError("Unsupported generation operation")
        if operation == "new" and (base is not None or inputs.get("document_id") is not None):
            raise ValueError("New generation cannot include a base document")
        if operation == "refine" and not base:
            raise ValueError("Refinement requires an explicit base")
        policy = inputs.get("retrieval_policy", "allow_fallback")
        if policy not in {"allow_fallback", "require_service"} or (
            operation == "refine" and policy != "allow_fallback"
        ):
            raise ValueError("Unsupported retrieval policy")
        from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
            build_asset_catalogue,
            build_relation_catalogue,
            build_task_catalogue,
        )

        assets, relations, tasks = build_asset_catalogue(), build_relation_catalogue(), build_task_catalogue()
        digest = execution_catalogue_sha256(assets=assets, relations=relations, tasks=tasks)
        expected = inputs.get("execution_catalogue_sha256")
        if type(expected) is not str or digest != expected:
            raise ValueError("Execution catalogue identity mismatch")
        progress("catalogues_loading")
        kwargs.update(asset_catalog=assets, relation_catalog=relations, task_catalog=tasks)
        metadata = {"operation": operation, "catalogue_sha256": digest}
        if operation == "new":
            progress("graph_priors_loading")
            options = {} if managed_context is None else {"managed_context": managed_context}
            snapshot = graph_access.retrieve_snapshot(inputs["prompt"], graph_config, **options)
            reject_secret(snapshot, config["api_key"])
            reject_secret(snapshot, (graph_config or {}).get("password"))
            if policy == "require_service" and snapshot["status"] == "unavailable":
                raise SafeGenerationFailure("required_retrieval_unavailable")
            kwargs["prior_context"] = snapshot["exact_context"]
        else:
            from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot

            snapshot = empty_snapshot("", status="not_requested", warning=None)
        from isaaclab_arena.agentic_environment_generation.prior_receipt import validate_prior_snapshot

        validate_prior_snapshot(snapshot, prompt=inputs["prompt"] if operation == "new" else "")
        metadata["prior_snapshot"] = snapshot
    progress("agent_initializing")
    agent = agent_factory(**config, max_tokens=4096, max_retries=1, load_dotenv=False)
    # Transport budgets (including initialization) precede real agent construction.
    if base is not None:
        validation = documents.validate(base)
        if not validation["valid"]:
            raise SafeGenerationFailure("invalid_specification")
        spec, _ = agent.refine_spec(ArenaEnvGraphSpec.from_dict(validation["spec"]), inputs["prompt"], **kwargs)
    else:
        spec, _ = agent.generate_spec(inputs["prompt"], **kwargs)
    if spec is None:
        raise SafeGenerationFailure("invalid_specification")
    progress("result_validating")
    text = yaml.safe_dump(spec.to_dict(), sort_keys=False)
    validation = documents.validate(text)
    if not validation["valid"]:
        raise SafeGenerationFailure("invalid_specification")
    warnings = ["Not published to Neo4j. No simulation or policy evaluation was run."]
    telemetry = agent.telemetry
    if telemetry is None or not telemetry.converged:
        warnings.append("Agent did not converge on all physical/semantic checks; review the draft before use.")
    return {
        **metadata,
        "yaml_text": text,
        "validation": validation,
        "traces": traces,
        "publication": "not_published",
        "warnings": warnings,
    }
