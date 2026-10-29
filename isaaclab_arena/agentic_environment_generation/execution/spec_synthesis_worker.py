# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Job J2: Spec synthesis & exemplar retrieval worker.

Must never import control-plane workflow modules, Omniverse Kit, or PyTorch.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .preflight_oracle import check_preflight_service_triad, verify_service_endpoint

if TYPE_CHECKING:
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

DEFAULT_PROMPT = "Franka picks up a cube from the maple table and places it into a bowl on the table."


@dataclass(frozen=True)
class SpecSynthesisResult:
    """Structured result returned by SpecSynthesisWorker (Job J2)."""

    spec: Any
    spec_dict: dict[str, Any]
    spec_path: Path | None
    version: int
    exemplars_used: list[dict[str, Any]]
    traces: tuple[str, ...]


def build_permissive_fallback_spec(
    *,
    prompt: str | None = None,
    env_name: str | None = None,
    base_spec_path: Path | str | None = None,
) -> ArenaEnvGraphSpec:
    """Build a grounded deterministic fallback spec when an endpoint is unreachable in permissive mode."""
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        _ensure_reified_relations_and_grounding,
    )
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    if base_spec_path and Path(base_spec_path).exists():
        spec = ArenaEnvGraphSpec.from_yaml(Path(base_spec_path))
        return _ensure_reified_relations_and_grounding(spec)

    fallback_dict = {
        "env_name": env_name or "llm_gen_maple_table_robolab_PickAndPlaceTask",
        "embodiment": {"id": "franka_ik", "registry_name": "franka_ik"},
        "background": {"id": "maple_table_robolab", "registry_name": "maple_table_robolab"},
        "objects": [
            {"id": "rubiks_cube_hot3d_robolab", "registry_name": "rubiks_cube_hot3d_robolab"},
            {"id": "bowl_ycb_robolab", "registry_name": "bowl_ycb_robolab"},
        ],
        "relations": [
            {"kind": "is_anchor", "subject": "maple_table_robolab"},
            {
                "kind": "on",
                "subject": "rubiks_cube_hot3d_robolab",
                "reference": "maple_table_robolab",
                "params": {"surface_anchor": "table_top", "surface_sector": "front_center"},
            },
            {
                "kind": "on",
                "subject": "bowl_ycb_robolab",
                "reference": "maple_table_robolab",
                "params": {"surface_anchor": "table_top", "surface_sector": "front_left"},
            },
        ],
        "task": {
            "composition": "atomic",
            "description": prompt or DEFAULT_PROMPT,
            "subtasks": [
                {
                    "kind": "PickAndPlaceTask",
                    "params": {
                        "pick_up_object": "rubiks_cube_hot3d_robolab",
                        "destination_location": "bowl_ycb_robolab",
                        "background_scene": "maple_table_robolab",
                    },
                }
            ],
        },
    }
    spec = ArenaEnvGraphSpec.from_dict(fallback_dict)
    return _ensure_reified_relations_and_grounding(spec)


def retrieve_graph_exemplars(
    prompt: str,
    *,
    task_kind: str = "PickAndPlaceTask",
    limit: int = 3,
    driver: Any | None = None,
    database: str | None = None,
    include_failures: bool = True,
) -> list[dict[str, Any]]:
    """Query Neo4j for evaluated and projected GOLD (:EnvironmentGraph) exemplars plus negative (:FailureSignature) priors."""
    try:
        from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever

        retriever = GraphRAGRetriever(driver=driver)
        exemplars: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for gold_ex in retriever.retrieve_projected_gold_exemplars(prompt, limit=limit, database=database):
            item = dict(gold_ex)
            item.setdefault("prior_kind", "positive_exemplar")
            exemplars.append(item)
            if item.get("name"):
                seen_names.add(str(item["name"]))
        subgraphs = retriever.retrieve_prior_subgraphs(prompt, limit=limit)
        for ex in subgraphs:
            item = dict(ex) if isinstance(ex, dict) else {"summary": str(ex)}
            item.setdefault("prior_kind", "positive_exemplar")
            if item.get("name") and str(item["name"]) in seen_names:
                continue
            exemplars.append(item)
        if include_failures:
            failures = retriever.retrieve_failure_signatures(prompt, limit=limit, database=database)
            for fail in failures:
                fitem = dict(fail)
                fitem["prior_kind"] = "negative_failure_signature"
                exemplars.append(fitem)
        return exemplars
    except Exception:
        return []



class SpecSynthesisWorker:
    """Boundary worker for Job J2: LLM environment specification synthesis and exemplar retrieval."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.2,
        strict_mode: bool = True,
    ) -> None:
        self.base_url = base_url or os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
        self.model = model
        self.api_key = api_key or "local-vllm"
        self.temperature = temperature
        self.strict_mode = strict_mode

    def retrieve_graph_exemplars(
        self,
        prompt: str,
        *,
        driver: Any | None = None,
        database: str | None = None,
        deployment_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = 3,
    ) -> dict[str, list[dict[str, Any]]]:
        """Retrieve positive (:EnvironmentGraph) exemplars and negative (:FailureSignature) priors from Neo4j."""
        combined = retrieve_graph_exemplars(
            prompt,
            driver=driver,
            database=database,
            limit=limit,
            include_failures=True,
        )
        exemplars = [item for item in combined if item.get("prior_kind") == "positive_exemplar"]
        failures = [item for item in combined if item.get("prior_kind") == "negative_failure_signature"]
        return {
            "exemplars": exemplars,
            "failure_signatures": failures,
            "combined": combined,
        }

    def synthesize(
        self,
        prompt: str,
        *,
        env_name: str | None = None,
        base_spec_path: Path | str | None = None,
        feedback: str | None = None,
        persist_version: bool = True,
        sync_neo4j: bool = True,
    ) -> SpecSynthesisResult:
        """Synthesize or refine an ArenaEnvGraphSpec from a natural-language prompt."""
        from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
            EnvironmentGenerationAgent,
            build_asset_catalogue,
            build_relation_catalogue,
            build_task_catalogue,
        )
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        llm_ok, llm_info = verify_service_endpoint(self.base_url)
        asset_catalog = build_asset_catalogue()
        relation_catalog = build_relation_catalogue()
        task_catalog = build_task_catalogue()

        exemplars = retrieve_graph_exemplars(prompt)
        base_spec = ArenaEnvGraphSpec.from_yaml(Path(base_spec_path)) if base_spec_path else None
        agent = None

        if not llm_ok and not self.strict_mode:
            env_graph_spec = build_permissive_fallback_spec(
                prompt=prompt,
                env_name=env_name,
                base_spec_path=base_spec_path,
            )
            traces: tuple[str, ...] = ()
        else:
            resolved_model = self.model or (llm_info if llm_ok and llm_info != "ok" else None)
            agent_kwargs: dict[str, Any] = {
                "temperature": self.temperature,
                "strict_mode": self.strict_mode,
                "base_url": self.base_url,
                "api_key": self.api_key,
            }
            if resolved_model:
                agent_kwargs["model"] = resolved_model
            agent = EnvironmentGenerationAgent(**agent_kwargs)
            if base_spec is not None:
                env_graph_spec, _ = agent.refine_spec(
                    base_spec,
                    feedback=feedback or prompt,
                    asset_catalog=asset_catalog,
                    relation_catalog=relation_catalog,
                    task_catalog=task_catalog,
                )
            else:
                env_graph_spec, _ = agent.generate_spec(
                    prompt,
                    asset_catalog=asset_catalog,
                    relation_catalog=relation_catalog,
                    task_catalog=task_catalog,
                )
            traces = tuple(agent.traces) if agent else ()

        assert env_graph_spec is not None, f"SpecSynthesisWorker returned invalid spec. Traces: {traces}"

        spec_path: Path | None = None
        new_v = 1
        if persist_version:
            from isaaclab_arena.agentic_environment_generation.version_manager import EnvironmentVersionManager

            canonical_env_name = env_name or env_graph_spec.env_name
            mgr = EnvironmentVersionManager(canonical_env_name)
            new_v, _ = mgr.create_version(
                spec_source=env_graph_spec,
                trigger="active_inference_refinement" if base_spec is not None else "initial_generation",
                prompt=feedback or prompt,
            )
            spec_path = mgr.get_spec_yaml_path(new_v)

        if sync_neo4j:
            try:
                from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import sync_spec_to_neo4j

                sync_spec_to_neo4j(
                    env_graph_spec,
                    telemetry=getattr(agent, "telemetry", None),
                    parent_env_name=base_spec.env_name if base_spec is not None else None,
                    derivation_feedback=(feedback or prompt) if base_spec is not None else None,
                )
            except Exception:
                pass

        return SpecSynthesisResult(
            spec=env_graph_spec,
            spec_dict=env_graph_spec.model_dump(mode="json"),
            spec_path=spec_path,
            version=new_v,
            exemplars_used=exemplars,
            traces=traces,
        )


def resolve_env_spec(args_cli: argparse.Namespace) -> Path:
    """Resolve a prompt into an environment graph spec YAML using SpecSynthesisWorker."""
    check_preflight_service_triad(args_cli)
    strict_critics = bool(getattr(args_cli, "strict_critics", False)) or not bool(
        getattr(args_cli, "permissive", False)
    )
    worker = SpecSynthesisWorker(
        base_url=getattr(args_cli, "base_url", None),
        model=getattr(args_cli, "model", None),
        api_key=getattr(args_cli, "api_key", None),
        temperature=float(getattr(args_cli, "temperature", 0.2)),
        strict_mode=strict_critics,
    )
    result = worker.synthesize(
        getattr(args_cli, "prompt", None) or DEFAULT_PROMPT,
        env_name=getattr(args_cli, "env_name", None),
        base_spec_path=getattr(args_cli, "base_spec", None),
        feedback=getattr(args_cli, "feedback", None),
        persist_version=True,
        sync_neo4j=True,
    )
    assert result.spec_path is not None, "Expected persisted spec YAML path"
    return result.spec_path
