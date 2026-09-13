# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Server-configured generation adapter; no credentials or raw model traces cross HTTP."""

import os
import yaml
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

from .provider_security import bounded_client, checked_config, reject_secret

GENERATION_TIMEOUT = 180
GENERATION_STAGES = frozenset({
    "agent_initializing",
    "catalogues_loading",
    "graph_priors_loading",
    "spec_inference",
    "prim_paths_resolving",
    "spatial_grounding",
    "validation_iteration_1",
    "validation_iteration_2",
    "generation_completed",
    "result_validating",
})


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


def generate(inputs, emit, *, agent_factory=None, config=None):
    """Run a fresh bounded agent and return only schema-validated output and allowlisted stages."""
    config = configuration() if config is None else config
    config = checked_config(config, trusted_server=isinstance(config, dict) and config.get("trusted_server") is True)
    if agent_factory is None:
        from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
            EnvironmentGenerationAgent,
        )

        with bounded_client(config):
            result = _generate(inputs, emit, agent_factory=EnvironmentGenerationAgent, config=config)
    else:
        result = _generate(inputs, emit, agent_factory=agent_factory, config=config)
    reject_secret(result, config["api_key"])
    return result


def _generate(inputs, emit, *, agent_factory, config):
    traces = []

    def progress(stage):
        if stage in GENERATION_STAGES:
            traces.append(stage)
            emit(stage)

    progress("agent_initializing")
    agent = agent_factory(**config, max_tokens=4096, max_retries=1, load_dotenv=False)
    # Transport budgets (including initialization) are installed before constructing the real agent.
    documents = Documents(Path("."))
    base = inputs.get("base_yaml")
    kwargs = {"publish_to_graph": False, "progress": progress}
    if base is not None:
        validation = documents.validate(base)
        if not validation["valid"]:
            raise ValueError("Invalid frozen generation base")
        spec, _ = agent.refine_spec(ArenaEnvGraphSpec.from_dict(validation["spec"]), inputs["prompt"], **kwargs)
    else:
        spec, _ = agent.generate_spec(inputs["prompt"], **kwargs)
    if spec is None:
        raise ValueError("Model did not produce a valid Arena environment specification")
    progress("result_validating")
    text = yaml.safe_dump(spec.to_dict(), sort_keys=False)
    validation = documents.validate(text)
    if not validation["valid"]:
        raise ValueError("Generated result failed Arena schema validation")
    warnings = ["Not published to Neo4j. No simulation or policy evaluation was run."]
    telemetry = agent.telemetry
    if telemetry is None or not telemetry.converged:
        warnings.append("Agent did not converge on all physical/semantic checks; review the draft before use.")
    return {
        "yaml_text": text,
        "validation": validation,
        "traces": traces,
        "publication": "not_published",
        "warnings": warnings,
    }
