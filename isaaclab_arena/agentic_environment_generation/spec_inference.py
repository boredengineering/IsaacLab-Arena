# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""LLM inference for environment graph specs."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from isaaclab_arena.agentic_environment_generation.inference_backend import (
    InferenceBackend,
    StructuredOutputRequest,
    build_strict_schema,
)
from isaaclab_arena.agentic_environment_generation.spec_validation import (
    collect_agent_ready_task_validation_traces,
    format_validation_error,
)
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec


class SpecInference:
    """Infers ArenaEnvGraphSpec from a natural-language prompt."""

    def __init__(self, inference_backend: InferenceBackend):
        self._inference_backend = inference_backend
        self._schema = build_strict_schema(ArenaEnvGraphSpec)

    def infer(
        self,
        prompt: str,
        traces: list[str],
        asset_catalog: Any,
        relation_catalog: Any,
        task_catalog: Any,
    ) -> tuple[ArenaEnvGraphSpec | None, dict[str, Any]]:
        """Generate an ArenaEnvGraphSpec from a natural-language prompt.

        Args:
            prompt: End-user environment description.
            traces: Accumulator for validation error lines, extended in place on failure.
            asset_catalog: Embodiment, background, and object vocabulary for the user message.
            relation_catalog: Relation vocabulary for the user message.
            task_catalog: Task vocabulary for the user message.

        Returns:
            A ``(spec, data)`` tuple. On success, ``spec`` is validated and ``data`` is the
            parsed model JSON. On failure, ``spec`` is ``None`` and ``data`` is the raw
            response object.
        """
        data = self._inference_backend.run_json(
            StructuredOutputRequest(
                schema_name="ArenaEnvGraphSpec",
                schema=self._schema,
                system=self._system_prompt(),
                user=self._user_message(
                    prompt,
                    asset_catalog,
                    relation_catalog,
                    task_catalog,
                ),
                retry_label="generate_spec",
            )
        )
        try:
            spec = ArenaEnvGraphSpec.model_validate(data)
        except ValidationError as exc:
            traces.extend(format_validation_error(exc))
            return None, data
        traces.extend(collect_agent_ready_task_validation_traces(spec))
        return spec, data

    def repair_with_feedback(
        self,
        previous_spec: ArenaEnvGraphSpec | dict[str, Any],
        feedback_report: str,
        traces: list[str],
        asset_catalog: Any = None,
        relation_catalog: Any = None,
        task_catalog: Any = None,
        original_prompt: str = "",
        available_affordances: list[str] | None = None,
    ) -> tuple[ArenaEnvGraphSpec | None, dict[str, Any]]:
        """Repair a failed ArenaEnvGraphSpec using structured diagnostic feedback.

        Uses a lightweight focused repair prompt to conserve token budget and prevent
        catalogue re-transmission bloat.

        Args:
            previous_spec: The failed spec or raw dict.
            feedback_report: Detailed SHACL or physical constraint violation diagnostics.
            traces: Diagnostic trace accumulator.
            asset_catalog: Optional asset catalogue (omitted by default in repair to save tokens).
            relation_catalog: Optional relation catalogue.
            task_catalog: Optional task catalogue.
            original_prompt: Original user goal description.
            available_affordances: List of valid introspected USD affordance patches.

        Returns:
            A ``(spec, data)`` tuple with the repaired spec or raw dict on failure.
        """
        prev_json = previous_spec.to_dict() if isinstance(previous_spec, ArenaEnvGraphSpec) else previous_spec
        repair_user_msg = self._repair_user_message(
            original_prompt=original_prompt,
            previous_spec=prev_json,
            feedback_report=feedback_report,
            available_affordances=available_affordances,
        )
        data = self._inference_backend.run_json(
            StructuredOutputRequest(
                schema_name="ArenaEnvGraphSpec",
                schema=self._schema,
                system=self._system_prompt(),
                user=repair_user_msg,
                retry_label="repair_spec",
            )
        )
        try:
            spec = ArenaEnvGraphSpec.model_validate(data)
        except ValidationError as exc:
            traces.extend(format_validation_error(exc))
            return None, data
        traces.extend(collect_agent_ready_task_validation_traces(spec))
        return spec, data

    @staticmethod
    def _repair_user_message(
        original_prompt: str,
        previous_spec: dict[str, Any],
        feedback_report: str,
        available_affordances: list[str] | None = None,
    ) -> str:
        affordance_sec = ""
        if available_affordances:
            affordance_sec = (
                f"\nAVAILABLE INTROSPECTED AFFORDANCE PATCHES (USD Ground Truth):\n"
                f"{json.dumps(available_affordances, indent=2)}\n"
            )
        prompt_sec = f"TARGET GOAL PROMPT:\n{original_prompt}\n\n" if original_prompt else ""
        return (
            f"{prompt_sec}"
            f"PREVIOUS CANDIDATE SPEC (WITH CONSTRAINT VIOLATIONS):\n"
            f"{json.dumps(previous_spec, indent=2)}\n\n"
            f"DIAGNOSTIC FEEDBACK & CONSTRAINT VIOLATIONS:\n"
            f"{feedback_report}\n"
            f"{affordance_sec}\n"
            f"INSTRUCTION:\n"
            f"Perform a targeted repair on the candidate spec to resolve every constraint violation above.\n"
            f"1. Update violating relations, surface anchors, or containment hierarchies so they conform.\n"
            f"2. Keep all valid objects, background, and embodiment configurations unchanged.\n"
            f"3. Emit the complete valid ArenaEnvGraphSpec JSON matching the schema."
        )

    @staticmethod
    def _user_message(
        prompt: str,
        asset_catalog: Any,
        relation_catalog: Any,
        task_catalog: Any,
    ) -> str:
        vocabulary = (
            f"{asset_catalog.to_catalog_string()}\n\n"
            f"{relation_catalog.to_catalog_string()}\n\n"
            f"{task_catalog.to_catalog_string()}"
        )
        if prompt:
            return f"{vocabulary}\n\nUSER PROMPT:\n{prompt}"
        return vocabulary

    @staticmethod
    def _system_prompt() -> str:
        return """\
You are an environment-generator for robot manipulation tasks.
Convert a natural-language prompt into an ArenaEnvGraphSpec with formal semantic reification.

OUTPUT SCHEMA STRUCTURE:
{
  "env_name": "short_descriptive_snake_case_name",
  "embodiment": {
    "id": "robot_id",
    "registry_name": "exact_embodiment_name_from_catalog",
    "params": {"initial_pose": {"position_xyz": [-0.55, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, 0.0, 1.0]}}
  },
  "background": {
    "id": "background_id",
    "registry_name": "exact_background_name_from_catalog",
    "params": {}
  },
  "objects": [
    {"id": "object_id", "registry_name": "exact_object_name_from_catalog", "params": {}}
  ],
  "relations": [
    {"kind": "is_anchor", "subject": "background_id", "params": {}},
    {"kind": "on", "subject": "object_id", "reference": "background_id", "params": {"surface_anchor": "table_top"}}
  ],
  "reified_relations": [
    {
      "reifier_id": "reifier_object_background",
      "source_id": "object_id",
      "relation_type": "PLACED_ON",
      "target_id": "background_id",
      "surface_anchor": "table_top",
      "required_headroom": 0.35,
      "required_friction": 0.60,
      "kinematic_manifold": "tabletop_stationary_reach",
      "prior_entropy": 2.5,
      "posterior_entropy": 0.05,
      "evidence_sources": ["tabletop_spatial_planner"]
    }
  ],
  "task": {
    "composition": "atomic",
    "description": "Natural language summary of the task.",
    "subtasks": [
      {
        "kind": "PickAndPlaceTask",
        "params": {
          "pick_up_object": "object_id",
          "destination_location": "destination_id",
          "background_scene": "background_id"
        }
      }
    ]
  }
}

GUIDANCE:
- Follow the per-field ``description`` strings in the schema.
- Use only exact names from the catalog for ``registry_name``:
  EMBODIMENTS for ``embodiment``, BACKGROUNDS for ``background``, and OBJECTS for ``objects``.
- Do NOT hallucinate asset names — every ``registry_name`` must appear verbatim in the catalog.
- For embodiment, if the prompt only mentions the robot family (droid/franka/g1) and there are multiple
  variations of that family in EMBODIMENTS, pick the one with the default tag.
- For multiple instances of the same registry asset, use semantic (left/right) or numerical (1/2/3) suffixes in ``id``.

TELESCOPIC DOLLHOUSE SPATIAL PLACEMENT:
- Robot Stance: Grounded in front of the table/workspace (e.g. [-0.55, 0.0, 0.0] facing +X, or [0.0, 0.35, floor_z] facing +Y), NOT inside the table volume.
- Multi-Object & Receptacle Support: For pick-and-place tasks with receptacles (e.g. bin, bowl, tray), BOTH the pickable object(s) AND the destination receptacle must have explicit 'on' relations to the support fixture (e.g. table_top or shelf_tier).
- Reachability Envelope: All task-relevant objects must be placed within reachable distance of the robot base (r in [0.30, 0.80]m for Franka/Droid, r in [0.45, 0.95]m for G1).
- Non-Overlap & Headroom: Maintain at least 0.20m separation between objects on the same support surface.
"""

