# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Agent for parsing natural-language env-generation prompts into an ArenaEnvGraphSpec."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from isaaclab_arena.agentic_environment_generation.catalogues import (
    AssetCatalogue,
    RelationCatalogue,
    RelationCatalogueEntry,
    TaskCatalogue,
    TaskCatalogueEntry,
    agent_ready_task_names,
    build_asset_catalogue,
    build_relation_catalogue,
    build_task_catalogue,
)
from isaaclab_arena.agentic_environment_generation.graph_cleanup import GraphCleanupError
from isaaclab_arena.agentic_environment_generation.simready_asset_search import (
    SimReadySearchConfig,
    search_simready_objects,
)
from isaaclab_arena.agentic_environment_generation.spec_validation import required_task_init_param_names
from isaaclab_arena.agentic_environment_generation.telemetry import ActiveInferenceTelemetry
from isaaclab_arena.assets.simready_constants import SIMREADY_USD_OBJECT_REGISTRY_NAME
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

if TYPE_CHECKING:
    from isaaclab_arena.agentic_environment_generation.inference_backend import InferenceEndpoint

_logger = logging.getLogger(__name__)

__all__ = [
    "AssetCatalogue",
    "EnvironmentGenerationAgent",
    "RelationCatalogue",
    "RelationCatalogueEntry",
    "TaskCatalogue",
    "TaskCatalogueEntry",
    "agent_ready_task_names",
    "build_asset_catalogue",
    "build_relation_catalogue",
    "build_task_catalogue",
    "required_task_init_param_names",
]


# ---------------------------------------------------------------------------
# Environment generation agent
# ---------------------------------------------------------------------------


class EnvironmentGenerationAgent:
    """Parses a natural-language env-generation prompt into an ArenaEnvGraphSpec."""

    enable_simready_search: bool = False
    simready_config: Any = None
    max_retries: int = 3
    strict_mode: bool = False
    _last_shacl_passed: bool = False
    _last_geometry_passed: bool = False
    _last_visual_tier: str = "tier_3_geometric_oracle"
    _last_visual_passed: bool = True
    _last_physics_passed: bool = True

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        endpoint: str | InferenceEndpoint | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        max_retries: int = 3,
        enable_simready_search: bool = False,
        simready_config: SimReadySearchConfig | None = None,
        load_dotenv: bool = True,
        inference_profile: dict | None = None,
        probe_connection: bool = True,
        strict_mode: bool = False,
    ):
        """Configure the OpenAI-compatible client and validate the model.

        Args:
            api_key: API token for the inference endpoint. Falls back to the
                selected endpoint's environment variable (``NVIDIA_API_KEY`` by default).
            model: Model identifier at the inference endpoint. Defaults to the
                selected endpoint's model and must support structured outputs.
            base_url: OpenAI-compatible inference endpoint override.
            endpoint: Named endpoint preset (``"public"``, ``"internal"``, or ``"openai"``).
                Falls back to ``ARENA_INFERENCE_ENDPOINT`` and then ``"public"``.
            temperature: Sampling temperature forwarded to the model. Kept
                low by default (0.2) because spec generation is a
                deterministic-ish translation task — high temperature
                yields creative but invalid schemas.
            max_tokens: Hard cap on the response length.
            max_retries: Number of additional attempts after a recoverable failure
                (network errors, timeouts, empty responses, malformed JSON). Each
                retry is a fresh API call.
            enable_simready_search: When True, search the SimReady database for objects the prompt
                names that are not in the asset catalogue, and add what it finds before inferring
                the spec.
            simready_config: Endpoints, database paths, and thresholds for that search.
            load_dotenv: Preserve CLI credential discovery; servers should pass False.
            inference_profile: Optional explicit inference profile dict.
            probe_connection: Perform a billable constructor probe; disable for single-request trials.
            strict_mode: When True, fail fast on critic or factor-graph errors instead of falling back.
        """
        from isaaclab_arena.agentic_environment_generation.inference_backend import InferenceBackend
        from isaaclab_arena.agentic_environment_generation.missing_object_inference import MissingObjectInference
        from isaaclab_arena.agentic_environment_generation.prim_path_inference import PrimPathInference
        from isaaclab_arena.agentic_environment_generation.spec_inference import SpecInference

        inference_backend = InferenceBackend(
            api_key=api_key,
            model=model,
            base_url=base_url,
            endpoint=endpoint,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            load_dotenv=load_dotenv,
            inference_profile=inference_profile,
            probe_connection=probe_connection,
        )
        self.inference_backend = inference_backend
        self.missing_object_inference = MissingObjectInference(inference_backend)
        self.spec_inference = SpecInference(inference_backend)
        self.prim_path_inference = PrimPathInference(inference_backend)
        self.enable_simready_search = enable_simready_search
        self.simready_config = simready_config or SimReadySearchConfig()
        self.max_retries = max_retries
        self.strict_mode = strict_mode
        self._traces: list[str] = []
        self._unavailable_objects: list[str] = []
        # Keyed by the asset name registered for the search hit; holds the usd_path it came from so
        # the spec can be rewritten onto the generic SimReady asset once inference finishes.
        self._simready_usd_paths: dict[str, str] = {}
        self._telemetry: ActiveInferenceTelemetry | None = None
        self._last_shacl_passed: bool = False
        self._last_geometry_passed: bool = False
        self._last_visual_tier: str = "tier_3_geometric_oracle"
        self._last_visual_passed: bool = True
        self._last_physics_passed: bool = True

    @property
    def traces(self) -> tuple[str, ...]:
        """Diagnostic lines from the most recent :meth:`generate_spec` call."""
        return tuple(self._traces)

    @property
    def unavailable_objects(self) -> tuple[str, ...]:
        """Objects the most recent ``generate_spec`` call needed but found no asset for.

        Only the SimReady search reports these. A catalog object always names a registry entry that
        exists, so it can be the wrong choice but never a missing one. The generated spec is still
        valid: these objects were never offered to spec inference, so it built the scene without
        them.
        """
        return tuple(self._unavailable_objects)

    @property
    def telemetry(self) -> ActiveInferenceTelemetry | None:
        """Active inference telemetry metrics from the most recent :meth:`generate_spec` call."""
        return self._telemetry

    def _build_telemetry(
        self,
        *,
        duration_s: float,
        repair_iterations: int,
        converged: bool,
        shacl_passed: bool,
        geometry_passed: bool,
        stagnation_detected: bool,
        rendered_images: dict[str, Any] | None = None,
    ) -> ActiveInferenceTelemetry:
        """Construct a transparent, tier-aware ActiveInferenceTelemetry record."""
        import re

        backend_tel = getattr(self.inference_backend, "telemetry", None)
        shacl_status = "Passed" if shacl_passed else "Violations Detected"
        spatial_status = "Passed" if geometry_passed else "Violations Detected"

        vis_tier = self._last_visual_tier or "tier_3_geometric_oracle"
        has_frames = bool(rendered_images)
        if not self._last_visual_passed:
            vis_status = "Failed"
        elif has_frames:
            if vis_tier == "tier_1_cloud_vlm":
                vis_status = "Passed (Tier 1 Cloud)"
            elif vis_tier == "tier_2_local_vlm":
                vis_status = "Passed (Tier 2 Local VLM)"
            else:
                vis_status = "Passed (Tier 3 Geometric)"
        else:
            vis_status = "Bypassed (No Frames - Tier 3 Fallback)"

        if not self._last_physics_passed:
            phys_status = "Failed (Drop Detected)"
        elif has_frames:
            phys_status = "Passed (30-step PhysX)"
        else:
            phys_status = "Heuristic Only (Pure Python)"

        fg_status = "Skipped"
        fg_residual = 0.0
        for line in reversed(self._traces):
            if "[ERROR][FactorGraph]" in line:
                fg_status = "Error Swallowed"
                break
            if "[FactorGraph] Relaxation completed:" in line:
                m_res = re.search(r"residual=([0-9.]+)", line)
                if m_res:
                    fg_residual = float(m_res.group(1))
                fg_status = "Converged" if "converged=True" in line else "Unconverged Warning"
                break

        if (
            has_frames
            and shacl_passed
            and geometry_passed
            and self._last_visual_passed
            and self._last_physics_passed
            and vis_tier in ("tier_1_cloud_vlm", "tier_2_local_vlm")
        ):
            grade = "GOLD: Grounded & Visually Verified"
        elif shacl_passed and geometry_passed and self._last_visual_passed and self._last_physics_passed:
            grade = "SILVER: Geometric & Semantic Only"
        else:
            grade = "PROVISIONAL: Unverified Settle"

        return ActiveInferenceTelemetry(
            model=getattr(self.inference_backend, "model", "unknown"),
            total_llm_calls=backend_tel.total_calls if backend_tel else 0,
            repair_iterations=repair_iterations,
            prompt_tokens=backend_tel.total_prompt_tokens if backend_tel else 0,
            completion_tokens=backend_tel.total_completion_tokens if backend_tel else 0,
            total_tokens=backend_tel.total_tokens if backend_tel else 0,
            duration_s=duration_s,
            converged=converged,
            shacl_passed=shacl_passed,
            geometry_passed=geometry_passed,
            stagnation_detected=stagnation_detected,
            traces=list(self._traces),
            shacl_status=shacl_status,
            spatial_geometry_status=spatial_status,
            visual_critic_tier=vis_tier,
            visual_critic_status=vis_status,
            physics_preflight_status=phys_status,
            factor_relaxation_status=fg_status,
            factor_relaxation_residual=fg_residual,
            verification_grade=grade,
        )

    def _evaluate_spec_comprehensive(
        self,
        spec: ArenaEnvGraphSpec,
        rendered_images: dict[str, Any] | None = None,
        iteration: int = 1,
    ) -> tuple[bool, list[str]]:
        """Run the full 4-critic validation battery (SHACL, Spatial Geometry, Visual, PhysX).

        Args:
            spec: Candidate environment graph specification.
            rendered_images: Optional dictionary of rendered camera views for visual critic.
            iteration: 1-based validation iteration index.

        Returns:
            Tuple of ``(conforms, violation_reports)``.
        """
        from isaaclab_arena.agentic_environment_generation.rdf_lowering import spec_to_rdf_graph
        from isaaclab_arena.agentic_environment_generation.rdf_validation import validate_rdf_environment_graph
        from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
            validate_spatial_geometry,
        )
        from isaaclab_arena.agentic_environment_generation.visual_critic import (
            PhysXPreflightCritic,
            VisualSceneCritic,
        )

        rdf_graph = spec_to_rdf_graph(spec)
        shacl_conforms, shacl_report = validate_rdf_environment_graph(rdf_graph)
        geom_conforms, geom_diagnostics = validate_spatial_geometry(spec)

        visual_critic = VisualSceneCritic(backend=self.inference_backend, strict_mode=self.strict_mode)
        visual_result = visual_critic.evaluate_scene_spec(spec, rendered_images=rendered_images)
        phys_critic = PhysXPreflightCritic()
        phys_issues = phys_critic.evaluate_physical_stability(spec)

        self._last_shacl_passed = bool(shacl_conforms)
        self._last_geometry_passed = bool(geom_conforms)
        self._last_visual_tier = str(visual_result.tier_used)
        self._last_visual_passed = bool(visual_result.conforms)
        self._last_physics_passed = not bool(phys_issues)

        if shacl_conforms and geom_conforms and visual_result.conforms and not phys_issues:
            self._traces.append(f"SHACL semantic validation passed on iteration {iteration}.")
            self._traces.append(f"Spatial Geometric validation passed on iteration {iteration}.")
            self._traces.append(
                f"Visual line-of-sight and dynamic physics validation passed on iteration {iteration}."
            )
            return True, []

        combined_report_parts: list[str] = []
        if not shacl_conforms:
            msg = f"SHACL constraint violation on iteration {iteration}:\n{shacl_report}"
            combined_report_parts.append(msg)
            self._traces.append(msg)
        if not geom_conforms:
            geom_text = "\n".join(geom_diagnostics)
            msg = f"Spatial & Geometric Violations on iteration {iteration}:\n{geom_text}"
            combined_report_parts.append(msg)
            self._traces.append(msg)
        if not visual_result.conforms:
            msg = f"Visual Scene Occlusion on iteration {iteration}:\n{visual_result.actionable_feedback}"
            combined_report_parts.append(msg)
            self._traces.append(msg)
        if phys_issues:
            phys_text = "\n".join(phys_issues)
            msg = f"PhysX Dynamic Stability Issues on iteration {iteration}:\n{phys_text}"
            combined_report_parts.append(msg)
            self._traces.append(msg)

        return False, combined_report_parts

    def generate_spec(
        self,
        prompt: str,
        asset_catalog: AssetCatalogue | None = None,
        relation_catalog: RelationCatalogue | None = None,
        task_catalog: TaskCatalogue | None = None,
        *,
        publish_to_graph: bool = True,
        proposal_only: bool = False,
        progress: Callable[[str], None] | None = None,
        prior_context: str | None = None,
        rendered_images: dict[str, Any] | None = None,
    ) -> tuple[ArenaEnvGraphSpec | None, dict[str, Any] | None]:
        """Call the model with user prompt and return the parsed ArenaEnvGraphSpec.

        Executes an Active Bayesian Reification loop:
        1. Synthesizes initial semantic prior spec with reified relations.
        2. Resolves USD sub-prims and grounds physical anchors.
        3. Validates against W3C SHACL-star constraints.
        4. When invariants fail, iteratively repairs candidate contracts via active LLM feedback.
        5. Syncs validated factor graph to Neo4j LPG.

        Args:
            prompt: Natural-language env description from the end user.
            asset_catalog: Pre-built asset vocabulary. When ``None``, built
                from the live ``AssetRegistry``.
            relation_catalog: Pre-built relation vocabulary. When ``None``, built
                from the live ``ObjectRelationLibraryRegistry``.
            task_catalog: Pre-built task vocabulary. When ``None``, built from
                ``TaskRegistry`` tasks marked ``@agent_ready``.
            publish_to_graph: Publish the completed spec to Neo4j; False returns an unpublished draft.
            proposal_only: Return the schema-checked model proposal without native grounding,
                autonomous repair or fallback; requires publication disabled.
            progress: Observer of real execution stages, without estimated percentages.
            prior_context: Exact prior context to consume without retrieval, including an empty
                string. None preserves legacy CLI Graph-RAG retrieval.
            rendered_images: Optional rendered camera views forwarded to VisualSceneCritic.

        Returns:
            A ``(spec, data)`` tuple. On success, ``spec`` is validated and
            ``data`` is None. On failure, ``spec`` is None and ``data`` is the corresponding JSON dict.
            When validation fails, ``agent.traces`` holds the diagnostic trace. ``agent.unavailable_objects``
            names any object the search found nothing for; the spec is built without it.
        """
        if proposal_only and publish_to_graph:
            raise ValueError("Proposal-only inference cannot publish")
        self._telemetry = None
        self._traces = []
        self._unavailable_objects = []
        self._simready_usd_paths = {}
        emit = progress or (lambda stage: None)
        emit("catalogues_loading")
        start_t = time.perf_counter()
        repair_iterations = 0
        shacl_passed = False
        geometry_passed = False
        stagnation_detected = False
        converged = False

        asset_catalog = asset_catalog or build_asset_catalogue()
        relation_catalog = relation_catalog or build_relation_catalogue()
        task_catalog = task_catalog or build_task_catalogue()
        if self.enable_simready_search:
            asset_catalog = self._extend_catalogue_with_simready(prompt, asset_catalog)
        else:
            emit("graph_priors_loading")
            if prior_context is not None:
                if prior_context:
                    prompt = f"{prompt}\n\n{prior_context}"
            else:
                # Retrieve Graph-RAG priors from Neo4j LPG memory for legacy CLI callers.
                try:
                    from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever

                    retriever = GraphRAGRetriever()
                    priors = retriever.retrieve_prior_subgraphs(prompt, limit=2)
                    rag_context = retriever.format_priors_as_context(priors)
                    if rag_context:
                        prompt = f"{prompt}\n\n{rag_context}"
                        self._traces.append(
                            f"[GraphRAG] Injected {len(priors)} verified environment priors from Neo4j."
                        )
                except GraphCleanupError:
                    raise
                except Exception:
                    self._traces.append("[GraphRAG] Prior retrieval unavailable; continuing without priors.")

        emit("spec_inference")
        spec, data = self.spec_inference.infer(
            prompt,
            self._traces,
            asset_catalog=asset_catalog,
            relation_catalog=relation_catalog,
            task_catalog=task_catalog,
        )
        if proposal_only:
            # The application owns grounding, validation, repair admission and routing.
            emit("proposal_completed")
            return spec, data
        if spec is None:
            duration_s = time.perf_counter() - start_t
            backend_tel = getattr(self.inference_backend, "telemetry", None)
            self._telemetry = ActiveInferenceTelemetry(
                model=getattr(self.inference_backend, "model", "unknown"),
                total_llm_calls=backend_tel.total_calls if backend_tel else 0,
                repair_iterations=0,
                prompt_tokens=backend_tel.total_prompt_tokens if backend_tel else 0,
                completion_tokens=(backend_tel.total_completion_tokens if backend_tel else 0),
                total_tokens=backend_tel.total_tokens if backend_tel else 0,
                duration_s=duration_s,
                converged=False,
                shacl_passed=False,
                geometry_passed=False,
                stagnation_detected=False,
                traces=list(self._traces),
            )
            return None, data
        if spec.object_references:
            emit("prim_paths_resolving")
            resolved = self.prim_path_inference.infer(spec, self._traces)
            if resolved is None:
                return None, spec.to_dict()
            spec = resolved

        if self.enable_simready_search:
            unusable = self._add_simready_usd_path_to_searched_objects(spec)
            if unusable is not None:
                self._traces.append(unusable)
                return None, spec.to_dict()
            return spec, None

        emit("spatial_grounding")
        # Ground spatial anchors and ensure reified relation contracts
        spec = _ensure_reified_relations_and_grounding(
            spec,
            strict_mode=self.strict_mode,
            traces_out=self._traces,
        )

        # Active Bayesian Refinement & SHACL-star Self-Healing Loop with Governance
        seen_spec_hashes: set[str] = set()
        max_loop_steps = min(self.max_retries, 2)  # Cap repair attempts to prevent token runaway

        for iteration in range(max_loop_steps):
            emit(f"validation_iteration_{iteration + 1}")
            current_hash = _compute_spec_hash(spec)
            if current_hash in seen_spec_hashes:
                stagnation_detected = True
                self._traces.append(
                    f"[ActiveInference] Stagnation/cycle detected at iteration {iteration + 1} "
                    f"(hash={current_hash[:8]}). Halting LLM loop to conserve tokens."
                )
                spec = _deterministic_affordance_fallback(
                    spec,
                    strict_mode=self.strict_mode,
                    traces_out=self._traces,
                )
                break
            seen_spec_hashes.add(current_hash)

            try:
                all_conforms, combined_report_parts = self._evaluate_spec_comprehensive(
                    spec,
                    rendered_images=rendered_images,
                    iteration=iteration + 1,
                )
                shacl_passed = self._last_shacl_passed
                geometry_passed = self._last_geometry_passed

                if all_conforms:
                    converged = True
                    break
                else:
                    repair_iterations += 1
                    combined_report = "\n\n".join(combined_report_parts)
                    affordances = _discover_candidate_affordances(spec)
                    try:
                        repaired_spec, _ = self.spec_inference.repair_with_feedback(
                            spec,
                            combined_report,
                            self._traces,
                            original_prompt=prompt,
                            available_affordances=affordances,
                        )
                    except Exception as repair_exc:
                        self._traces.append(
                            f"[ActiveInference] Repair failed on iteration {iteration + 1}: {repair_exc}. Applying"
                            " deterministic fallback."
                        )
                        spec = _deterministic_affordance_fallback(
                            spec,
                            strict_mode=self.strict_mode,
                            traces_out=self._traces,
                        )
                        break

                    if repaired_spec is not None:
                        spec = _ensure_reified_relations_and_grounding(
                            repaired_spec,
                            strict_mode=self.strict_mode,
                            traces_out=self._traces,
                        )
                    else:
                        self._traces.append(
                            f"[ActiveInference] Repair returned None on iteration {iteration + 1}. Applying"
                            " deterministic fallback."
                        )
                        spec = _deterministic_affordance_fallback(
                            spec,
                            strict_mode=self.strict_mode,
                            traces_out=self._traces,
                        )
                        break
            except Exception as exc:  # pragma: no cover
                if self.strict_mode:
                    raise
                self._traces.append(f"RDF/SHACL validation skipped: {exc}. Applying deterministic fallback.")
                spec = _deterministic_affordance_fallback(
                    spec,
                    strict_mode=self.strict_mode,
                    traces_out=self._traces,
                )
                break
        else:
            # If loop finished without conforming to SHACL/Geometry, apply deterministic fallback
            spec = _deterministic_affordance_fallback(
                spec,
                strict_mode=self.strict_mode,
                traces_out=self._traces,
            )

        duration_s = time.perf_counter() - start_t
        self._telemetry = self._build_telemetry(
            duration_s=duration_s,
            repair_iterations=repair_iterations,
            converged=converged,
            shacl_passed=shacl_passed,
            geometry_passed=geometry_passed,
            stagnation_detected=stagnation_detected,
            rendered_images=rendered_images,
        )

        if publish_to_graph:
            emit("graph_publishing")
            try:
                from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import sync_spec_to_neo4j

                sync_spec_to_neo4j(spec, telemetry=self._telemetry)
            except Exception as exc:  # pragma: no cover
                self._traces.append(f"Neo4j LPG sync skipped: {exc}")
        emit("generation_completed")
        return spec, None

    def refine_spec(
        self,
        base_spec: ArenaEnvGraphSpec,
        feedback: str,
        asset_catalog: Any = None,
        relation_catalog: Any = None,
        task_catalog: Any = None,
        *,
        publish_to_graph: bool = True,
        proposal_only: bool = False,
        progress: Callable[[str], None] | None = None,
        rendered_images: dict[str, Any] | None = None,
    ) -> tuple[ArenaEnvGraphSpec | None, dict[str, Any] | None]:
        """Refine or modify an existing ArenaEnvGraphSpec using natural-language instructions.

        Args:
            base_spec: The starting ArenaEnvGraphSpec to edit or continue from.
            feedback: Natural-language critique or modification instructions.
            asset_catalog: Pre-built asset vocabulary.
            relation_catalog: Pre-built relation vocabulary.
            task_catalog: Pre-built task vocabulary.
            publish_to_graph: Publish the completed spec to Neo4j; False returns an unpublished draft.
            proposal_only: Return the schema-checked model proposal without native grounding,
                autonomous repair or fallback; requires publication disabled.
            progress: Observer of real execution stages, without estimated percentages.
            rendered_images: Optional rendered camera views forwarded to VisualSceneCritic.

        Returns:
            A ``(spec, data)`` tuple with the refined, validated specification.
        """
        if proposal_only and publish_to_graph:
            raise ValueError("Proposal-only inference cannot publish")
        self._telemetry = None
        self._traces = []
        emit = progress or (lambda stage: None)
        emit("catalogues_loading")
        start_t = time.perf_counter()
        repair_iterations = 0
        shacl_passed = False
        geometry_passed = False
        stagnation_detected = False
        converged = False

        asset_catalog = asset_catalog or build_asset_catalogue()
        relation_catalog = relation_catalog or build_relation_catalogue()
        task_catalog = task_catalog or build_task_catalogue()
        affordances = _discover_candidate_affordances(base_spec)

        emit("spec_inference")
        spec, data = self.spec_inference.repair_with_feedback(
            base_spec,
            feedback_report=f"USER REFINEMENT INSTRUCTIONS:\n{feedback}",
            traces=self._traces,
            asset_catalog=asset_catalog,
            relation_catalog=relation_catalog,
            task_catalog=task_catalog,
            original_prompt=feedback,
            available_affordances=affordances,
        )
        if proposal_only:
            # The application owns grounding, validation, repair admission and routing.
            emit("proposal_completed")
            return spec, data
        if spec is None:
            duration_s = time.perf_counter() - start_t
            backend_tel = getattr(self.inference_backend, "telemetry", None)
            self._telemetry = ActiveInferenceTelemetry(
                model=getattr(self.inference_backend, "model", "unknown"),
                total_llm_calls=backend_tel.total_calls if backend_tel else 0,
                repair_iterations=0,
                prompt_tokens=backend_tel.total_prompt_tokens if backend_tel else 0,
                completion_tokens=(backend_tel.total_completion_tokens if backend_tel else 0),
                total_tokens=backend_tel.total_tokens if backend_tel else 0,
                duration_s=duration_s,
                converged=False,
                shacl_passed=False,
                geometry_passed=False,
                stagnation_detected=False,
                traces=list(self._traces),
            )
            return None, data

        if spec.object_references:
            emit("prim_paths_resolving")
            resolved = self.prim_path_inference.infer(spec, self._traces)
            if resolved is not None:
                spec = resolved

        emit("spatial_grounding")
        # Ground spatial anchors and ensure reified relation contracts
        spec = _ensure_reified_relations_and_grounding(
            spec,
            strict_mode=self.strict_mode,
            traces_out=self._traces,
        )

        # Active Bayesian Refinement & SHACL-star Self-Healing Loop with Governance
        seen_spec_hashes: set[str] = set()
        max_loop_steps = min(self.max_retries, 2)

        for iteration in range(max_loop_steps):
            emit(f"validation_iteration_{iteration + 1}")
            current_hash = _compute_spec_hash(spec)
            if current_hash in seen_spec_hashes:
                stagnation_detected = True
                self._traces.append(
                    f"[ActiveInference] Stagnation/cycle detected at iteration {iteration + 1} "
                    f"(hash={current_hash[:8]}). Halting LLM loop to conserve tokens."
                )
                spec = _deterministic_affordance_fallback(
                    spec,
                    strict_mode=self.strict_mode,
                    traces_out=self._traces,
                )
                break
            seen_spec_hashes.add(current_hash)

            try:
                all_conforms, combined_report_parts = self._evaluate_spec_comprehensive(
                    spec,
                    rendered_images=rendered_images,
                    iteration=iteration + 1,
                )
                shacl_passed = self._last_shacl_passed
                geometry_passed = self._last_geometry_passed

                if all_conforms:
                    converged = True
                    break
                else:
                    repair_iterations += 1
                    combined_report = "\n\n".join(combined_report_parts)
                    affordances = _discover_candidate_affordances(spec)
                    try:
                        repaired_spec, _ = self.spec_inference.repair_with_feedback(
                            spec,
                            combined_report,
                            self._traces,
                            asset_catalog=asset_catalog,
                            relation_catalog=relation_catalog,
                            task_catalog=task_catalog,
                            original_prompt=feedback,
                            available_affordances=affordances,
                        )
                    except Exception as repair_exc:
                        self._traces.append(
                            f"[ActiveInference] Refinement repair failed: {repair_exc}. Applying deterministic"
                            " fallback."
                        )
                        spec = _deterministic_affordance_fallback(
                            spec,
                            strict_mode=self.strict_mode,
                            traces_out=self._traces,
                        )
                        break

                    if repaired_spec is not None:
                        spec = _ensure_reified_relations_and_grounding(
                            repaired_spec,
                            strict_mode=self.strict_mode,
                            traces_out=self._traces,
                        )
                    else:
                        self._traces.append(
                            "[ActiveInference] Refinement repair returned None. Applying deterministic fallback."
                        )
                        spec = _deterministic_affordance_fallback(
                            spec,
                            strict_mode=self.strict_mode,
                            traces_out=self._traces,
                        )
                        break
            except Exception as exc:  # pragma: no cover
                if self.strict_mode:
                    raise
                self._traces.append(f"RDF/SHACL validation skipped: {exc}. Applying deterministic fallback.")
                spec = _deterministic_affordance_fallback(
                    spec,
                    strict_mode=self.strict_mode,
                    traces_out=self._traces,
                )
                break
        else:
            spec = _deterministic_affordance_fallback(
                spec,
                strict_mode=self.strict_mode,
                traces_out=self._traces,
            )

        duration_s = time.perf_counter() - start_t
        self._telemetry = self._build_telemetry(
            duration_s=duration_s,
            repair_iterations=repair_iterations,
            converged=converged,
            shacl_passed=shacl_passed,
            geometry_passed=geometry_passed,
            stagnation_detected=stagnation_detected,
            rendered_images=rendered_images,
        )

        if publish_to_graph:
            emit("graph_publishing")
            try:
                from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import sync_spec_to_neo4j

                sync_spec_to_neo4j(spec, telemetry=self._telemetry)
            except Exception as exc:  # pragma: no cover
                self._traces.append(f"Neo4j LPG sync skipped: {exc}")
        emit("generation_completed")
        return spec, None

    def _add_simready_usd_path_to_searched_objects(self, spec: ArenaEnvGraphSpec) -> str | None:
        """Point the spec's searched objects at the generic SimReady asset, USD path in params.

        A search name only exists in the process that searched, so a spec keeping it loads nowhere else.

        Args:
            spec: Generated spec, rewritten in place.

        Returns:
            An error message, or None when every searched object was rewritten.
        """
        # TODO(xinjieyao, 2026-08-03): Lift this once ObjectSetSpec.members can carry a usd_path.
        for object_set in spec.object_sets or []:
            searched_members = [name for name in object_set.members if name in self._simready_usd_paths]
            if searched_members:
                return (
                    f"Object set '{object_set.id}' has searched SimReady members {searched_members}."
                    " Members have nowhere to carry a usd_path; use them as objects instead."
                )
        for obj in spec.objects:
            usd_path = self._simready_usd_paths.get(obj.registry_name)
            if usd_path is not None:
                obj.registry_name = SIMREADY_USD_OBJECT_REGISTRY_NAME
                obj.params = {**obj.params, "usd_path": usd_path}
        return None

    def _extend_catalogue_with_simready(self, prompt: str, asset_catalog: AssetCatalogue) -> AssetCatalogue:
        """Search SimReady for the objects the catalog misses, and add what it finds to the catalog.

        Args:
            prompt: Natural-language env description, used to work out what the catalog misses.
            asset_catalog: Registered asset vocabulary to extend.

        Returns:
            A copy of the catalog with one added entry per asset found, or the argument itself
            when nothing was searched for or nothing was found.
        """
        # Imported here rather than at module scope: it pulls in the asset base classes, which
        # import pxr, and a pxr import before SimulationApp starts breaks the unit tests.
        from isaaclab_arena.assets.simready_object_library import register_searched_simready_object

        phrases = self.missing_object_inference.infer(prompt, asset_catalog)
        if not phrases:
            return asset_catalog
        search_result = search_simready_objects(phrases, self.simready_config)
        self._unavailable_objects = list(search_result.unmatched_phrases)
        if not search_result.candidates:
            return asset_catalog
        extended = replace(asset_catalog, objects=list(asset_catalog.objects))
        for candidate in search_result.candidates:
            asset_cls = register_searched_simready_object(candidate.search_phrase, candidate.usd_path, candidate.tags)
            tags = [tag for tag in asset_cls.tags if tag != "object"]
            extended.objects.append({
                "name": asset_cls.name,
                "tags": tags,
                "object_type": asset_cls.object_type.value,
            })
            self._simready_usd_paths[asset_cls.name] = candidate.usd_path
            _logger.info("catalogued %r for %r: %s", asset_cls.name, candidate.search_phrase, candidate.usd_path)
        return extended


def _compute_spec_hash(spec: ArenaEnvGraphSpec) -> str:
    """Compute a canonical MD5 hash of the spec's entities, poses, and relational structure."""
    import hashlib
    import json

    canonical_repr = {
        "embodiment": spec.embodiment.registry_name if spec.embodiment else None,
        "background": spec.background.registry_name if spec.background else None,
        "objects": sorted([
            f"{o.id}:{o.registry_name}:"
            f"{[round(float(c), 3) for c in (o.params.get('initial_pose', {}).get('position_xyz', []) if o.params else [])]}"
            for o in spec.objects
        ]),
        "relations": sorted([
            f"{r.kind}:{r.subject}->{r.reference}:"
            f"{r.params.get('surface_anchor', '') if r.params else ''}:"
            f"{r.params.get('surface_sector', '') if r.params else ''}"
            for r in spec.relations
        ]),
    }
    return hashlib.md5(json.dumps(canonical_repr, sort_keys=True).encode("utf-8")).hexdigest()


def _discover_candidate_affordances(spec: ArenaEnvGraphSpec) -> list[str]:
    """Discover candidate surface anchors and support patches from scene entities."""
    affordances = []
    for obj in spec.objects:
        name_lower = f"{obj.id} {obj.registry_name}".lower()
        if "shelf" in name_lower or "rack" in name_lower or "shelv" in name_lower:
            affordances.extend([f"{obj.id}.shelf_tier_1", f"{obj.id}.shelf_tier_2", f"{obj.id}.shelf_tier_3"])
        elif "table" in name_lower or "desk" in name_lower or "counter" in name_lower:
            affordances.extend([f"{obj.id}.table_top", f"{obj.id}.center_workspace"])
        elif "bin" in name_lower or "box" in name_lower or "tray" in name_lower:
            affordances.append(f"{obj.id}.bin_bottom")
    return affordances


def _deterministic_affordance_fallback(
    spec: ArenaEnvGraphSpec,
    *,
    strict_mode: bool = False,
    traces_out: list[str] | None = None,
) -> ArenaEnvGraphSpec:
    """Deterministically repair hierarchical placement and ungrounded reifiers without LLM calls."""
    furniture_objs = [
        obj
        for obj in spec.objects
        if any(
            k in f"{obj.id} {obj.registry_name}".lower()
            for k in ("shelf", "shelving", "table", "counter", "desk", "rack")
        )
    ]
    if furniture_objs and spec.background:
        primary_fixture = furniture_objs[0]
        for rel in spec.relations:
            if rel.kind == "on" and rel.reference == spec.background.id and rel.subject != primary_fixture.id:
                rel.reference = primary_fixture.id
                if not rel.params or "surface_anchor" not in rel.params:
                    rel.params = dict(rel.params or {})
                    rel.params["surface_anchor"] = "shelf_tier_1"

    return _ensure_reified_relations_and_grounding(
        spec,
        strict_mode=strict_mode,
        traces_out=traces_out,
    )


def _ensure_reified_relations_and_grounding(
    spec: ArenaEnvGraphSpec,
    *,
    strict_mode: bool = False,
    traces_out: list[str] | None = None,
) -> ArenaEnvGraphSpec:
    """Ensure spatial grounding, surface anchors, formal RDF 1.2 contracts, and dynamic factor graph relaxation."""
    from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import relax_spec_spatial_factor_graph
    from isaaclab_arena.environment_spec.arena_env_graph_types import ContinuousIntervalSpec, ReifiedRelationSpec

    spec = _ground_telescopic_dollhouse_spec(spec)

    # If reified relations were not synthesized, auto-construct contracts from spatial relations
    if not spec.reified_relations:
        reified_list: list[ReifiedRelationSpec] = []
        for idx, rel in enumerate(spec.relations):
            if rel.kind.lower() in ("on", "placed_on", "inside", "placed_inside", "stands_near"):
                rel_type = (
                    "PLACED_ON"
                    if "on" in rel.kind.lower()
                    else ("PLACED_INSIDE" if "inside" in rel.kind.lower() else "STANDS_NEAR")
                )
                target_id = rel.reference or spec.background.id
                reified_list.append(
                    ReifiedRelationSpec(
                        reifier_id=f"reifier_{rel.subject}_{target_id}_{idx+1}",
                        source_id=rel.subject,
                        relation_type=rel_type,
                        target_id=target_id,
                        surface_anchor=str(rel.params.get("surface_anchor", "table_top")),
                        contact_normal=(0.0, 0.0, 1.0),
                        delta_x=ContinuousIntervalSpec(min_val=-0.05, max_val=0.05, nominal=0.0),
                        delta_y=ContinuousIntervalSpec(min_val=-0.05, max_val=0.05, nominal=0.0),
                        delta_z=ContinuousIntervalSpec(min_val=0.0, max_val=0.03, nominal=0.01),
                        required_headroom=float(rel.params.get("headroom", 0.35)),
                        required_friction=float(rel.params.get("friction", 0.60)),
                        kinematic_manifold=(
                            "unitree_g1_bimanual_chest_height"
                            if spec.embodiment and "g1" in spec.embodiment.registry_name.lower()
                            else "tabletop_stationary_reach"
                        ),
                        prior_entropy=2.5,
                        posterior_entropy=0.05,
                        evidence_sources=["llm_active_inference", "usd_stage_introspection"],
                    )
                )
        if reified_list:
            spec.reified_relations = reified_list

    # Dynamically relax continuous spatial factor graph
    try:
        spec, relax_diags = relax_spec_spatial_factor_graph(spec)
        msg = (
            f"[FactorGraph] Relaxation completed: residual={relax_diags.residual:.4f}, "
            f"iterations={relax_diags.iterations}, converged={relax_diags.converged}"
        )
        if traces_out is not None:
            traces_out.append(msg)
            for diag in relax_diags:
                traces_out.append(diag)
        if not relax_diags.converged:
            warn_msg = (
                f"[WARNING][FactorGraph] LBP relaxation did not converge "
                f"(residual={relax_diags.residual:.4f} > threshold). "
                f"Unresolved factors: {relax_diags.unresolved_factors}"
            )
            if traces_out is not None:
                traces_out.append(warn_msg)
    except Exception as exc:
        err_msg = f"[ERROR][FactorGraph] Spatial factor graph relaxation failed: {exc}"
        if traces_out is not None:
            traces_out.append(err_msg)
        if strict_mode:
            raise RuntimeError(err_msg) from exc

    return spec


def _ground_telescopic_dollhouse_spec(spec: ArenaEnvGraphSpec) -> ArenaEnvGraphSpec:
    """Ensure background, furniture, and receptacles are grounded without overriding relational intent."""
    from isaaclab_arena.environment_spec.arena_env_graph_types import SpatialRelationSpec

    furniture_keywords = ("shelf", "shelving", "table", "counter", "desk", "cabinet", "stand")
    receptacle_keywords = ("bin", "basket", "tray", "box_target", "receptacle")

    bg_lower = f"{spec.background.id} {spec.background.registry_name}".lower()
    floor_z = -0.795 if "galileo" in bg_lower or "room" in bg_lower else 0.0

    # 1. Scene anchor: keep existing object_reference anchors if present, otherwise anchor background
    has_any_anchor = any(r.kind == "is_anchor" for r in spec.relations)
    if not has_any_anchor:
        spec.relations.insert(
            0, SpatialRelationSpec(kind="is_anchor", subject=spec.background.id, reference=None, params={})
        )

    anchored_subjects = {r.subject for r in spec.relations if r.kind == "is_anchor"}

    primary_furniture_id: str | None = None
    for obj in spec.objects:
        obj_name_lower = f"{obj.id} {obj.registry_name}".lower()
        is_furniture = any(k in obj_name_lower for k in furniture_keywords)

        if is_furniture:
            if primary_furniture_id is None:
                primary_furniture_id = obj.id
            if "initial_pose" not in obj.params:
                obj.params["initial_pose"] = {
                    "position_xyz": [0.0, 1.1 if "galileo" in bg_lower else 0.6, floor_z],
                    "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                }
            anchored_subjects.add(obj.id)

    # 2. Receptacles: If ungrounded, connect to primary furniture or background table
    default_anchor = next((r.subject for r in spec.relations if r.kind == "is_anchor"), spec.background.id)
    target_fixture_id = primary_furniture_id or default_anchor
    for obj in spec.objects:
        obj_name_lower = f"{obj.id} {obj.registry_name}".lower()
        is_receptacle = any(k in obj_name_lower for k in receptacle_keywords)
        if is_receptacle:
            has_rel = any(r.subject == obj.id for r in spec.relations if r.kind != "is_anchor")
            if not has_rel:
                spec.relations.append(
                    SpatialRelationSpec(
                        kind="on", subject=obj.id, reference=target_fixture_id, params={"surface_anchor": "table_top"}
                    )
                )

    # 3. Embodiment Grounding
    if spec.embodiment and "initial_pose" not in spec.embodiment.params:
        if "galileo" in bg_lower:
            spec.embodiment.params["initial_pose"] = {
                "position_xyz": [0.0, 0.35, floor_z],
                "rotation_xyzw": [0.0, 0.0, 0.7071, 0.7071],  # Face +Y toward shelving
            }
        else:
            spec.embodiment.params["initial_pose"] = {
                "position_xyz": [-0.55, 0.0, floor_z],
                "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],  # Face +X toward tabletop
            }

    # Clean and rebuild relations list without duplicates or redundant placements
    cleaned_relations: list[SpatialRelationSpec] = []
    seen_rel_signatures: set[tuple[str, str, str | None]] = set()

    existing_anchors = [r.subject for r in spec.relations if r.kind == "is_anchor"]
    for anchor_id in [*existing_anchors, *(o.id for o in spec.objects if o.id in anchored_subjects)]:
        sig = ("is_anchor", anchor_id, None)
        if sig not in seen_rel_signatures:
            cleaned_relations.append(
                SpatialRelationSpec(kind="is_anchor", subject=anchor_id, reference=None, params={})
            )
            seen_rel_signatures.add(sig)

    for r in spec.relations:
        if r.kind == "is_anchor":
            continue
        # Skip redundant 'on' if the subject is already anchored with an explicit initial_pose
        if r.kind == "on" and r.subject in anchored_subjects and r.reference == spec.background.id:
            continue
        sig = (r.kind, r.subject, r.reference)
        if sig not in seen_rel_signatures:
            cleaned_relations.append(r)
            seen_rel_signatures.add(sig)

    spec.relations = cleaned_relations
    return spec
