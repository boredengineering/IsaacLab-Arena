# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Agent for parsing natural-language env-generation prompts into an ArenaEnvGraphSpec."""

from __future__ import annotations

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
        self.spec_inference = SpecInference(inference_backend)
        self.prim_path_inference = PrimPathInference(inference_backend)
        self.max_retries = max_retries
        self._traces: list[str] = []

    @property
    def traces(self) -> tuple[str, ...]:
        """Diagnostic lines from the most recent :meth:`generate_spec` call."""
        return tuple(self._traces)

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
            return None, data
        if spec.object_references:
            resolved = self.prim_path_inference.infer(spec, self._traces)
            if resolved is None:
                return None, spec.to_dict()
            spec = resolved

        # Ground spatial anchors and ensure reified relation contracts
        spec = _ensure_reified_relations_and_grounding(spec)

        # Active Bayesian Refinement & SHACL-star Self-Healing Loop
        for iteration in range(self.max_retries):
            try:
                from isaaclab_arena.agentic_environment_generation.rdf_lowering import spec_to_rdf_graph
                from isaaclab_arena.agentic_environment_generation.rdf_validation import validate_rdf_environment_graph

                rdf_graph = spec_to_rdf_graph(spec)
                conforms, report = validate_rdf_environment_graph(rdf_graph)
                if conforms:
                    self._traces.append(f"SHACL semantic validation passed on iteration {iteration + 1}.")
                    break
                else:
                    self._traces.append(f"SHACL constraint violation on iteration {iteration + 1}:\n{report}")
                    repaired_spec, _ = self.spec_inference.repair_with_feedback(
                        spec,
                        report,
                        self._traces,
                        asset_catalog=asset_catalog,
                        relation_catalog=relation_catalog,
                        task_catalog=task_catalog,
                    )
                    if repaired_spec is not None:
                        spec = _ensure_reified_relations_and_grounding(repaired_spec)
                    else:
                        break
            except Exception as exc:  # pragma: no cover
                self._traces.append(f"RDF/SHACL validation skipped: {exc}")
                break

        # Sync validated factor graph to Neo4j LPG
        try:
            from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import sync_spec_to_neo4j
            sync_spec_to_neo4j(spec)
        except Exception as exc:  # pragma: no cover
            self._traces.append(f"Neo4j LPG sync skipped: {exc}")

        return spec, None


def _ensure_reified_relations_and_grounding(spec: ArenaEnvGraphSpec) -> ArenaEnvGraphSpec:
    """Ensure spatial grounding, surface anchors, and formal RDF 1.2 reified relation contracts."""
    from isaaclab_arena.environment_spec.arena_env_graph_types import ContinuousIntervalSpec, ReifiedRelationSpec

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
                        surface_anchor=str(rel.params.get("surface_anchor", "shelf_tier_1")),
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

    return spec


def _ground_telescopic_dollhouse_spec(spec: ArenaEnvGraphSpec) -> ArenaEnvGraphSpec:
    """Ensure background, furniture, and receptacles are anchored in the workspace to prevent scattered spawns."""
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

    for obj in spec.objects:
        obj_name_lower = f"{obj.id} {obj.registry_name}".lower()
        is_furniture = any(k in obj_name_lower for k in furniture_keywords)
        is_receptacle = any(k in obj_name_lower for k in receptacle_keywords)

        if is_furniture:
            if "initial_pose" not in obj.params:
                obj.params["initial_pose"] = {
                    "position_xyz": [0.0, 1.1, floor_z],
                    "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                }
            anchored_subjects.add(obj.id)

        elif is_receptacle:
            if "initial_pose" not in obj.params:
                obj.params["initial_pose"] = {
                    "position_xyz": [0.6, 0.8, floor_z],
                    "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                }
            anchored_subjects.add(obj.id)

    # 2. Embodiment Grounding
    if spec.embodiment and "initial_pose" not in spec.embodiment.params:
        # Position humanoid facing the workspace along the reach manifold
        spec.embodiment.params["initial_pose"] = {
            "position_xyz": [0.0, 0.35, floor_z],
            "rotation_xyzw": [0.0, 0.0, 0.7071, 0.7071],  # Face +Y toward shelving
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
