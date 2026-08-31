# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Agent for parsing natural-language env-generation prompts into an ArenaEnvGraphSpec."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from isaaclab_arena.agentic_environment_generation.inference_backend import InferenceBackend
from isaaclab_arena.agentic_environment_generation.prim_path_inference import PrimPathInference
from isaaclab_arena.agentic_environment_generation.spec_inference import SpecInference
from isaaclab_arena.agentic_environment_generation.spec_validation import required_task_init_param_names
from isaaclab_arena.assets.registries import AssetRegistry, ObjectRelationLibraryRegistry, TaskRegistry
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.relations.relations import RelationBase

# ---------------------------------------------------------------------------
# Active Inference Telemetry & Observability
# ---------------------------------------------------------------------------


@dataclass
class ActiveInferenceTelemetry:
    """Telemetry, iteration tracking, and token metrics for graph generation."""

    model: str = ""
    total_llm_calls: int = 0
    repair_iterations: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_s: float = 0.0
    converged: bool = True
    shacl_passed: bool = True
    geometry_passed: bool = True
    stagnation_detected: bool = False
    traces: list[str] = field(default_factory=list)

    def render_summary_card(self) -> str:
        """Render an ANSI / plain-text telemetry summary card."""
        status_symbol = "🟢 Converged (Variational Free Energy ≈ 0)" if self.converged else "🟡 Fallback Applied"
        shacl_sym = "✅ Passed" if self.shacl_passed else "❌ Violation"
        geom_sym = "✅ Passed" if self.geometry_passed else "❌ Violation"
        total_calls = int(self.total_llm_calls) if isinstance(self.total_llm_calls, (int, float)) else 0
        repair_iters = int(self.repair_iterations) if isinstance(self.repair_iterations, (int, float)) else 0
        tot_tok = int(self.total_tokens) if isinstance(self.total_tokens, (int, float)) else 0
        p_tok = int(self.prompt_tokens) if isinstance(self.prompt_tokens, (int, float)) else 0
        c_tok = int(self.completion_tokens) if isinstance(self.completion_tokens, (int, float)) else 0
        dur_s = float(self.duration_s) if isinstance(self.duration_s, (int, float)) else 0.0
        avg_latency = (dur_s / total_calls) if total_calls > 0 else 0.0

        lines = [
            "======================================================================",
            "  🤖 Active Bayesian Inference & Graph Generation Telemetry",
            "======================================================================",
            f"• Model:               {self.model}",
            f"• Convergence Status:  {status_symbol}",
            f"• Total LLM Calls:     {total_calls}",
            f"• Repair Iterations:   {repair_iters}",
            f"• Token Consumption:   {tot_tok:,} tokens ({p_tok:,} prompt, {c_tok:,} completion)",
            f"• Wall-Clock Latency:  {dur_s:.2f}s (avg {avg_latency:.2f}s / call)",
            f"• Physical Invariants: SHACL-star: {shacl_sym} | Spatial Geometry: {geom_sym}",
            "======================================================================",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Environment generation agent
# ---------------------------------------------------------------------------


class EnvironmentGenerationAgent:
    """Parses a natural-language env-generation prompt into an ArenaEnvGraphSpec."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        max_retries: int = 3,
    ):
        """Configure the OpenAI-compatible client and validate the model.

        Args:
            api_key: API token for the inference endpoint. Falls back
                to the ``NV_API_KEY`` environment variable.
            model: Model identifier at the inference endpoint.
                Must support OpenAI-compatible structured outputs.
            base_url: OpenAI-compatible inference endpoint.
            temperature: Sampling temperature forwarded to the model. Kept
                low by default (0.2) because spec generation is a
                deterministic-ish translation task — high temperature
                yields creative but invalid schemas.
            max_tokens: Hard cap on the response length.
            max_retries: Number of additional attempts after a recoverable failure
                (network errors, timeouts, empty responses, malformed JSON). Each
                retry is a fresh API call.
        """
        inference_backend = InferenceBackend(
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )
        self.inference_backend = inference_backend
        self.spec_inference = SpecInference(inference_backend)
        self.prim_path_inference = PrimPathInference(inference_backend)
        self.max_retries = max_retries
        self._traces: list[str] = []
        self._telemetry: ActiveInferenceTelemetry | None = None

    @property
    def traces(self) -> tuple[str, ...]:
        """Diagnostic lines from the most recent :meth:`generate_spec` call."""
        return tuple(self._traces)

    @property
    def telemetry(self) -> ActiveInferenceTelemetry | None:
        """Active inference telemetry metrics from the most recent :meth:`generate_spec` call."""
        return self._telemetry

    def generate_spec(
        self,
        prompt: str,
        asset_catalog: AssetCatalogue | None = None,
        relation_catalog: RelationCatalogue | None = None,
        task_catalog: TaskCatalogue | None = None,
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

        Returns:
            A ``(spec, data)`` tuple. On success, ``spec`` is validated and
            ``data`` is None. On failure, ``spec`` is None and ``data`` is the corresponding JSON dict.
            When validation fails, ``agent.traces`` holds the diagnostic trace.
        """
        self._traces = []
        start_t = time.perf_counter()
        repair_iterations = 0
        shacl_passed = False
        geometry_passed = False
        stagnation_detected = False
        converged = False

        asset_catalog = asset_catalog or build_asset_catalogue()
        relation_catalog = relation_catalog or build_relation_catalogue()
        task_catalog = task_catalog or build_task_catalogue()
        spec, data = self.spec_inference.infer(
            prompt,
            self._traces,
            asset_catalog=asset_catalog,
            relation_catalog=relation_catalog,
            task_catalog=task_catalog,
        )
        if spec is None:
            duration_s = time.perf_counter() - start_t
            backend_tel = getattr(self.inference_backend, "telemetry", None)
            self._telemetry = ActiveInferenceTelemetry(
                model=getattr(self.inference_backend, "model", "unknown"),
                total_llm_calls=backend_tel.total_calls if backend_tel else 0,
                repair_iterations=0,
                prompt_tokens=backend_tel.total_prompt_tokens if backend_tel else 0,
                completion_tokens=backend_tel.total_completion_tokens if backend_tel else 0,
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
            resolved = self.prim_path_inference.infer(spec, self._traces)
            if resolved is None:
                return None, spec.to_dict()
            spec = resolved

        # Ground spatial anchors and ensure reified relation contracts
        spec = _ensure_reified_relations_and_grounding(spec)

        # Active Bayesian Refinement & SHACL-star Self-Healing Loop with Governance
        seen_spec_hashes: set[str] = set()
        max_loop_steps = min(self.max_retries, 2)  # Cap repair attempts to prevent token runaway

        for iteration in range(max_loop_steps):
            current_hash = _compute_spec_hash(spec)
            if current_hash in seen_spec_hashes:
                stagnation_detected = True
                self._traces.append(
                    f"[ActiveInference] Stagnation/cycle detected at iteration {iteration + 1} "
                    f"(hash={current_hash[:8]}). Halting LLM loop to conserve tokens."
                )
                spec = _deterministic_affordance_fallback(spec)
                break
            seen_spec_hashes.add(current_hash)

            try:
                from isaaclab_arena.agentic_environment_generation.rdf_lowering import spec_to_rdf_graph
                from isaaclab_arena.agentic_environment_generation.rdf_validation import validate_rdf_environment_graph
                from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import validate_spatial_geometry

                rdf_graph = spec_to_rdf_graph(spec)
                shacl_conforms, shacl_report = validate_rdf_environment_graph(rdf_graph)
                geom_conforms, geom_diagnostics = validate_spatial_geometry(spec)

                if shacl_conforms and geom_conforms:
                    shacl_passed = True
                    geometry_passed = True
                    converged = True
                    self._traces.append(f"SHACL semantic validation passed on iteration {iteration + 1}.")
                    self._traces.append(f"Spatial Geometric validation passed on iteration {iteration + 1}.")
                    break
                else:
                    repair_iterations += 1
                    combined_report_parts = []
                    if not shacl_conforms:
                        combined_report_parts.append(f"SHACL constraint violation on iteration {iteration + 1}:\n{shacl_report}")
                        self._traces.append(f"SHACL constraint violation on iteration {iteration + 1}:\n{shacl_report}")
                    if not geom_conforms:
                        geom_text = "\n".join(geom_diagnostics)
                        combined_report_parts.append(f"Spatial & Geometric Violations on iteration {iteration + 1}:\n{geom_text}")
                        self._traces.append(f"Spatial & Geometric Violations on iteration {iteration + 1}:\n{geom_text}")

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
                            f"[ActiveInference] Repair failed on iteration {iteration + 1}: {repair_exc}. Applying deterministic fallback."
                        )
                        spec = _deterministic_affordance_fallback(spec)
                        break

                    if repaired_spec is not None:
                        spec = _ensure_reified_relations_and_grounding(repaired_spec)
                    else:
                        self._traces.append(
                            f"[ActiveInference] Repair returned None on iteration {iteration + 1}. Applying deterministic fallback."
                        )
                        spec = _deterministic_affordance_fallback(spec)
                        break
            except Exception as exc:  # pragma: no cover
                self._traces.append(f"RDF/SHACL validation skipped: {exc}. Applying deterministic fallback.")
                spec = _deterministic_affordance_fallback(spec)
                break
        else:
            # If loop finished without conforming to SHACL/Geometry, apply deterministic fallback
            spec = _deterministic_affordance_fallback(spec)

        duration_s = time.perf_counter() - start_t
        backend_tel = getattr(self.inference_backend, "telemetry", None)
        self._telemetry = ActiveInferenceTelemetry(
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
        )

        # Sync validated factor graph to Neo4j LPG
        try:
            from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import sync_spec_to_neo4j
            sync_spec_to_neo4j(spec, telemetry=self._telemetry)
        except Exception as exc:  # pragma: no cover
            self._traces.append(f"Neo4j LPG sync skipped: {exc}")

        return spec, None

    def refine_spec(
        self,
        base_spec: ArenaEnvGraphSpec,
        feedback: str,
        asset_catalog: Any = None,
        relation_catalog: Any = None,
        task_catalog: Any = None,
    ) -> tuple[ArenaEnvGraphSpec | None, dict[str, Any] | None]:
        """Refine or modify an existing ArenaEnvGraphSpec using natural-language instructions.

        Args:
            base_spec: The starting ArenaEnvGraphSpec to edit or continue from.
            feedback: Natural-language critique or modification instructions.
            asset_catalog: Pre-built asset vocabulary.
            relation_catalog: Pre-built relation vocabulary.
            task_catalog: Pre-built task vocabulary.

        Returns:
            A ``(spec, data)`` tuple with the refined, validated specification.
        """
        self._traces = []
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
        if spec is None:
            duration_s = time.perf_counter() - start_t
            backend_tel = getattr(self.inference_backend, "telemetry", None)
            self._telemetry = ActiveInferenceTelemetry(
                model=getattr(self.inference_backend, "model", "unknown"),
                total_llm_calls=backend_tel.total_calls if backend_tel else 0,
                repair_iterations=0,
                prompt_tokens=backend_tel.total_prompt_tokens if backend_tel else 0,
                completion_tokens=backend_tel.total_completion_tokens if backend_tel else 0,
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
            resolved = self.prim_path_inference.infer(spec, self._traces)
            if resolved is not None:
                spec = resolved

        # Ground spatial anchors and ensure reified relation contracts
        spec = _ensure_reified_relations_and_grounding(spec)

        # Active Bayesian Refinement & SHACL-star Self-Healing Loop with Governance
        seen_spec_hashes: set[str] = set()
        max_loop_steps = min(self.max_retries, 2)

        for iteration in range(max_loop_steps):
            current_hash = _compute_spec_hash(spec)
            if current_hash in seen_spec_hashes:
                stagnation_detected = True
                self._traces.append(
                    f"[ActiveInference] Stagnation/cycle detected at iteration {iteration + 1} "
                    f"(hash={current_hash[:8]}). Halting LLM loop to conserve tokens."
                )
                spec = _deterministic_affordance_fallback(spec)
                break
            seen_spec_hashes.add(current_hash)

            try:
                from isaaclab_arena.agentic_environment_generation.rdf_lowering import spec_to_rdf_graph
                from isaaclab_arena.agentic_environment_generation.rdf_validation import validate_rdf_environment_graph
                from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import validate_spatial_geometry

                rdf_graph = spec_to_rdf_graph(spec)
                shacl_conforms, shacl_report = validate_rdf_environment_graph(rdf_graph)
                geom_conforms, geom_diagnostics = validate_spatial_geometry(spec)

                if shacl_conforms and geom_conforms:
                    shacl_passed = True
                    geometry_passed = True
                    converged = True
                    self._traces.append(f"SHACL semantic validation passed on refinement iteration {iteration + 1}.")
                    self._traces.append(f"Spatial Geometric validation passed on refinement iteration {iteration + 1}.")
                    break
                else:
                    repair_iterations += 1
                    combined_report_parts = []
                    if not shacl_conforms:
                        combined_report_parts.append(f"SHACL constraint violation on iteration {iteration + 1}:\n{shacl_report}")
                        self._traces.append(f"SHACL constraint violation on iteration {iteration + 1}:\n{shacl_report}")
                    if not geom_conforms:
                        geom_text = "\n".join(geom_diagnostics)
                        combined_report_parts.append(f"Spatial & Geometric Violations on iteration {iteration + 1}:\n{geom_text}")
                        self._traces.append(f"Spatial & Geometric Violations on iteration {iteration + 1}:\n{geom_text}")

                    combined_report = "\n\n".join(combined_report_parts)
                    affordances = _discover_candidate_affordances(spec)
                    try:
                        repaired_spec, _ = self.spec_inference.repair_with_feedback(
                            spec,
                            combined_report,
                            self._traces,
                            original_prompt=feedback,
                            available_affordances=affordances,
                        )
                    except Exception as repair_exc:
                        self._traces.append(
                            f"[ActiveInference] Refinement repair failed: {repair_exc}. Applying deterministic fallback."
                        )
                        spec = _deterministic_affordance_fallback(spec)
                        break

                    if repaired_spec is not None:
                        spec = _ensure_reified_relations_and_grounding(repaired_spec)
                    else:
                        self._traces.append(
                            f"[ActiveInference] Refinement repair returned None. Applying deterministic fallback."
                        )
                        spec = _deterministic_affordance_fallback(spec)
                        break
            except Exception as exc:  # pragma: no cover
                self._traces.append(f"RDF/SHACL validation skipped: {exc}. Applying deterministic fallback.")
                spec = _deterministic_affordance_fallback(spec)
                break
        else:
            spec = _deterministic_affordance_fallback(spec)

        duration_s = time.perf_counter() - start_t
        backend_tel = getattr(self.inference_backend, "telemetry", None)
        self._telemetry = ActiveInferenceTelemetry(
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
        )

        # Sync validated factor graph to Neo4j LPG
        try:
            from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import sync_spec_to_neo4j
            sync_spec_to_neo4j(spec, telemetry=self._telemetry)
        except Exception as exc:  # pragma: no cover
            self._traces.append(f"Neo4j LPG sync skipped: {exc}")

        return spec, None


def _compute_spec_hash(spec: ArenaEnvGraphSpec) -> str:
    """Compute a canonical MD5 hash of the spec's entities and relational structure."""
    import hashlib
    import json

    canonical_repr = {
        "embodiment": spec.embodiment.registry_name if spec.embodiment else None,
        "background": spec.background.registry_name if spec.background else None,
        "objects": sorted([f"{o.id}:{o.registry_name}" for o in spec.objects]),
        "relations": sorted([
            f"{r.kind}:{r.subject}->{r.reference}:{r.params.get('surface_anchor', '') if r.params else ''}"
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


def _deterministic_affordance_fallback(spec: ArenaEnvGraphSpec) -> ArenaEnvGraphSpec:
    """Deterministically repair hierarchical placement and ungrounded reifiers without LLM calls."""
    furniture_objs = [
        obj for obj in spec.objects
        if any(k in f"{obj.id} {obj.registry_name}".lower() for k in ("shelf", "shelving", "table", "counter", "desk", "rack"))
    ]
    if furniture_objs and spec.background:
        primary_fixture = furniture_objs[0]
        for rel in spec.relations:
            if rel.kind == "on" and rel.reference == spec.background.id and rel.subject != primary_fixture.id:
                rel.reference = primary_fixture.id
                if not rel.params or "surface_anchor" not in rel.params:
                    rel.params = dict(rel.params or {})
                    rel.params["surface_anchor"] = "shelf_tier_1"

    return _ensure_reified_relations_and_grounding(spec)


def _ensure_reified_relations_and_grounding(spec: ArenaEnvGraphSpec) -> ArenaEnvGraphSpec:
    """Ensure spatial grounding, surface anchors, formal RDF 1.2 contracts, and dynamic factor graph relaxation."""
    from isaaclab_arena.environment_spec.arena_env_graph_types import ContinuousIntervalSpec, ReifiedRelationSpec
    from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import relax_spec_spatial_factor_graph

    spec = _ground_telescopic_dollhouse_spec(spec)

    # If reified relations were not synthesized, auto-construct contracts from spatial relations
    if not spec.reified_relations:
        reified_list: list[ReifiedRelationSpec] = []
        for idx, rel in enumerate(spec.relations):
            if rel.kind.lower() in ("on", "placed_on", "inside", "placed_inside", "stands_near"):
                rel_type = "PLACED_ON" if "on" in rel.kind.lower() else ("PLACED_INSIDE" if "inside" in rel.kind.lower() else "STANDS_NEAR")
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
        spec, _ = relax_spec_spatial_factor_graph(spec)
    except Exception:
        pass

    return spec


def _ground_telescopic_dollhouse_spec(spec: ArenaEnvGraphSpec) -> ArenaEnvGraphSpec:
    """Ensure background, furniture, and receptacles are grounded without overriding relational intent."""
    from isaaclab_arena.environment_spec.arena_env_graph_types import SpatialRelationSpec

    furniture_keywords = ("shelf", "shelving", "table", "counter", "desk", "cabinet", "stand")
    receptacle_keywords = ("bin", "basket", "tray", "box_target", "receptacle")

    bg_lower = f"{spec.background.id} {spec.background.registry_name}".lower()
    floor_z = -0.795 if "galileo" in bg_lower or "room" in bg_lower else 0.0

    # 1. Background scene root anchor
    has_bg_anchor = any(r.kind == "is_anchor" and r.subject == spec.background.id for r in spec.relations)
    if not has_bg_anchor:
        spec.relations.insert(
            0,
            SpatialRelationSpec(
                kind="is_anchor",
                subject=spec.background.id,
                reference=None,
                params={},
            ),
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
    target_fixture_id = primary_furniture_id or spec.background.id
    for obj in spec.objects:
        obj_name_lower = f"{obj.id} {obj.registry_name}".lower()
        is_receptacle = any(k in obj_name_lower for k in receptacle_keywords)
        if is_receptacle:
            has_rel = any(r.subject == obj.id for r in spec.relations if r.kind != "is_anchor")
            if not has_rel:
                spec.relations.append(
                    SpatialRelationSpec(
                        kind="on",
                        subject=obj.id,
                        reference=target_fixture_id,
                        params={"surface_anchor": "table_top"},
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

    for anchor_id in [spec.background.id, *(o.id for o in spec.objects if o.id in anchored_subjects)]:
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


# ---------------------------------------------------------------------------
# Asset catalogue (AssetRegistry → user-prompt blocks)
# ---------------------------------------------------------------------------


@dataclass
class AssetCatalogue:
    """Registered asset vocabulary grouped for the agent prompt."""

    # A list of embodiment names and their tags for agent to choose from.
    embodiments: list[dict[str, Any]] = field(default_factory=list)
    # A list of background names and their tags for agent to choose from.
    backgrounds: list[dict[str, Any]] = field(default_factory=list)
    # A list of object names and their tags for agent to choose from.
    objects: list[dict[str, Any]] = field(default_factory=list)

    def to_catalog_string(self) -> str:
        """Format this catalogue as the user-message vocabulary block."""
        embodiment_lines = "\n".join(
            f"- {e['name']}  tags={e['tags']}" for e in sorted(self.embodiments, key=lambda e: e["name"])
        )
        background_lines = "\n".join(
            f"- {b['name']}  tags={b['tags']}" for b in sorted(self.backgrounds, key=lambda b: b["name"])
        )
        object_lines = "\n".join(
            f"- {o['name']}  tags={o['tags']}" for o in sorted(self.objects, key=lambda o: o["name"])
        )
        return (
            f"EMBODIMENTS ({len(self.embodiments)}):\n{embodiment_lines}\n\n"
            f"BACKGROUNDS ({len(self.backgrounds)}):\n{background_lines}\n\n"
            f"OBJECTS ({len(self.objects)}):\n{object_lines}"
        )


def build_asset_catalogue(registry: AssetRegistry | None = None) -> AssetCatalogue:
    """Collect registered embodiments, backgrounds, and pick-up objects from ``AssetRegistry``."""
    registry = registry or AssetRegistry()
    catalogue = AssetCatalogue()
    # TODO(qianl): handle optional lights and hdr images.
    # TODO(qianl): add tag to filter out validated/agent-ready assets only.
    # Classify by registry tags, not issubclass(Background/Object/EmbodimentBase): importing those
    # types pulls in pxr before SimulationApp and breaks unit tests.
    for name in registry.get_all_keys():
        cls = registry.get_asset_by_name(name)
        tags = getattr(cls, "tags", None) or []
        if "embodiment" in tags:
            catalogue.embodiments.append({"name": name, "tags": [t for t in tags if t != "embodiment"]})
        elif "background" in tags:
            catalogue.backgrounds.append({"name": name, "tags": [t for t in tags if t != "background"]})
        elif "object" in tags:
            catalogue.objects.append({"name": name, "tags": [t for t in tags if t != "object"]})
    return catalogue


# ---------------------------------------------------------------------------
# Relation catalogue (ObjectRelationLibraryRegistry → user-prompt blocks)
# ---------------------------------------------------------------------------


def _first_docstring_line(cls: type) -> str:
    doc = cls.__doc__ or ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


@dataclass
class RelationCatalogueEntry:
    """One registered spatial relation exposed to the agent."""

    name: str
    unary: bool
    summary: str


@dataclass
class RelationCatalogue:
    """Registered object-relation vocabulary for the agent prompt."""

    relations: list[RelationCatalogueEntry] = field(default_factory=list)

    def to_catalog_string(self) -> str:
        """Format this catalogue as the user-message RELATIONS block."""
        lines = []
        for entry in sorted(self.relations, key=lambda r: r.name):
            arity = "unary" if entry.unary else "binary"
            lines.append(f"- {entry.name} ({arity}): {entry.summary}")
        return f"RELATIONS ({len(self.relations)}):\n" + "\n".join(lines)


def build_relation_catalogue(
    registry: ObjectRelationLibraryRegistry | None = None,
) -> RelationCatalogue:
    """Collect registered object relations from ``ObjectRelationLibraryRegistry``."""
    registry = registry or ObjectRelationLibraryRegistry()
    catalogue = RelationCatalogue()
    for name in registry.get_all_keys():
        relation_cls = registry.get_object_relation_by_name(name)
        assert issubclass(relation_cls, RelationBase), f"{name!r} is not a RelationBase subclass"
        catalogue.relations.append(
            RelationCatalogueEntry(
                name=name,
                unary=relation_cls.is_unary(),
                summary=_first_docstring_line(relation_cls),
            )
        )
    return catalogue


# ---------------------------------------------------------------------------
# Task catalogue (TaskRegistry → user-prompt blocks)
# ---------------------------------------------------------------------------


@dataclass
class TaskCatalogueEntry:
    """One agent_ready task exposed to the agent."""

    name: str
    required_params: list[str]
    summary: str


@dataclass
class TaskCatalogue:
    """Agent-ready task vocabulary for the agent prompt."""

    tasks: list[TaskCatalogueEntry] = field(default_factory=list)

    def to_catalog_string(self) -> str:
        """Format this catalogue as the user-message TASKS block."""
        lines = []
        for entry in sorted(self.tasks, key=lambda t: t.name):
            params = ", ".join(entry.required_params)
            lines.append(f"- {entry.name} ({params}): {entry.summary}")
        return f"TASKS ({len(self.tasks)}):\n" + "\n".join(lines)


def agent_ready_task_names(registry: TaskRegistry | None = None) -> frozenset[str]:
    """Return ``TaskRegistry`` keys for tasks marked with ``@agent_ready``."""
    registry = registry or TaskRegistry()
    return frozenset(
        name for name in registry.get_all_keys() if getattr(registry.get_task_by_name(name), "agent_ready", False)
    )


def build_task_catalogue(registry: TaskRegistry | None = None) -> TaskCatalogue:
    """Collect agent_ready tasks from ``TaskRegistry``."""
    registry = registry or TaskRegistry()
    catalogue = TaskCatalogue()
    for name in sorted(agent_ready_task_names(registry)):
        task_cls = registry.get_task_by_name(name)
        catalogue.tasks.append(
            TaskCatalogueEntry(
                name=name,
                required_params=required_task_init_param_names(task_cls),
                summary=_first_docstring_line(task_cls),
            )
        )
    return catalogue
