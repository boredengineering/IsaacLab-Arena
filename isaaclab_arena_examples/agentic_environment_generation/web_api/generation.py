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
        ("OPENAI", "https://api.openai.com/v1", "gpt-6-astra"),
        ("GEMINI", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
        ("OPENROUTER", "https://openrouter.ai/api/v1", "anthropic/claude-sonnet-4.5"),
        ("NV", "https://inference-api.nvidia.com", "azure/anthropic/claude-opus-4-8"),
    )
    for prefix, endpoint, model in providers:
        key = os.environ.get(f"{prefix}_API_KEY", "").strip()
        if key:
            return {
                "api_key": key,
                "base_url": os.environ.get(f"{prefix}_BASE_URL") or os.environ.get("BASE_URL") or endpoint,
                "model": os.environ.get(f"{prefix}_MODEL") or model,
            }
    return None


def generate(inputs, emit, *, agent_factory=None, config=None):
    """Run a fresh bounded agent and return only schema-validated output and allowlisted stages."""
    config = configuration() if config is None else config
    if not config:
        raise ValueError("Generation is not configured; set a supported server-side model API key")
    if agent_factory is None:
        from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
            EnvironmentGenerationAgent,
        )

        agent_factory = EnvironmentGenerationAgent
    traces = []

    def progress(stage):
        if stage in GENERATION_STAGES:
            traces.append(stage)
            emit(stage)

    progress("agent_initializing")
    agent = agent_factory(**config, max_tokens=4096, max_retries=1, load_dotenv=False)
    # SDK retries are disabled; the agent owns one repair/retry and the worker has a hard wall-clock bound.
    if hasattr(agent, "inference_backend"):
        client = agent.inference_backend.client
        client.timeout = 45
        client.max_retries = 0
        completion = client.chat.completions.create
        calls = 0

        def bounded_completion(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls > 8:
                raise ValueError("Generation call budget exhausted")
            return completion(*args, **kwargs)

        client.chat.completions.create = bounded_completion
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
