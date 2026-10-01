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
from isaaclab_arena.agentic_environment_generation.spec_wire_adapter import SpecWireAdapter
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec


def _sanitize_spec_candidate(data: dict[str, Any]) -> dict[str, Any]:
    """Sanitize LLM-generated spec dict before Pydantic domain validation."""
    if not isinstance(data, dict):
        return data

    if "cli_override_specs" in data and isinstance(data["cli_override_specs"], list):
        swappable_ids: set[str] = set()
        emb = data.get("embodiment")
        if isinstance(emb, dict) and isinstance(emb.get("id"), str):
            swappable_ids.add(emb["id"])
        bg = data.get("background")
        if isinstance(bg, dict) and isinstance(bg.get("id"), str):
            swappable_ids.add(bg["id"])
        objs = data.get("objects")
        if isinstance(objs, list):
            for obj in objs:
                if isinstance(obj, dict) and isinstance(obj.get("id"), str):
                    swappable_ids.add(obj["id"])

        valid_overrides = []
        seen_args: set[str] = set()
        for item in data["cli_override_specs"]:
            if isinstance(item, dict):
                arg = str(item.get("arg", "")).lstrip("-")
                target = item.get("target_node_id")
                if target in swappable_ids and arg and arg not in seen_args:
                    seen_args.add(arg)
                    valid_overrides.append({"arg": arg, "target_node_id": target})
        data["cli_override_specs"] = valid_overrides

    if "object_references" in data and isinstance(data["object_references"], list):
        obj_ids = {obj.get("id") for obj in data.get("objects", []) if isinstance(obj, dict)}
        bg_id = data.get("background", {}).get("id") if isinstance(data.get("background"), dict) else None
        valid_refs = []
        for ref in data["object_references"]:
            if isinstance(ref, dict):
                parent_id = ref.get("parent_id")
                if parent_id in obj_ids:
                    ref_id = ref.get("id")
                    tasks = data.get("task", {}).get("subtasks", [])
                    if isinstance(tasks, list):
                        for subtask in tasks:
                            if isinstance(subtask, dict) and isinstance(subtask.get("params"), dict):
                                if subtask["params"].get("destination_location") == ref_id:
                                    subtask["params"]["destination_location"] = parent_id
                    continue
                if parent_id == bg_id:
                    valid_refs.append(ref)
        data["object_references"] = valid_refs

    if "placement_validators" in data and isinstance(data["placement_validators"], dict):
        pv = data["placement_validators"]
        req = pv.get("required_checks")
        enb = pv.get("enabled_checks")
        if isinstance(req, list) and isinstance(enb, list):
            pv["enabled_checks"] = list(dict.fromkeys(enb + req))

    return data


class SpecInference:
    """Infers ArenaEnvGraphSpec from a natural-language prompt."""

    def __init__(self, inference_backend: InferenceBackend):
        self._inference_backend = inference_backend
        profile = inference_backend.inference_profile
        user_defined = profile is not None and profile.get("origin") == "user_defined"
        wire = profile is not None and (profile["request_policy"]["structured_output"] == "json_schema")
        self._wire_adapter = SpecWireAdapter() if wire else None
        self._strict_domain_adapter = SpecWireAdapter() if user_defined and not wire else None
        self._schema = self._wire_adapter.schema if self._wire_adapter else build_strict_schema(ArenaEnvGraphSpec)

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
            A ``(spec, data)`` tuple. ``data`` is parsed domain JSON, with wire maps
            decoded for documented OpenAI profiles. On domain-validation failure,
            ``spec`` is ``None`` and ``data`` retains that candidate's evidence.
            Malformed wire data fails before domain validation, without coercion.
        """
        data = self._inference_backend.run_json(
            StructuredOutputRequest(
                schema_name="ArenaEnvGraphSpec",
                schema=self._schema,
                system=self._request_system_prompt(),
                user=self._user_message(
                    prompt,
                    asset_catalog,
                    relation_catalog,
                    task_catalog,
                ),
                retry_label="generate_spec",
                parse_json=SpecWireAdapter.parse_json if self._wire_adapter or self._strict_domain_adapter else None,
            )
        )
        if self._wire_adapter:
            data = self._wire_adapter.decode(data)
        elif self._strict_domain_adapter:
            data = self._strict_domain_adapter.decode(self._strict_domain_adapter.encode(data))
        data = _sanitize_spec_candidate(data)
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
        if isinstance(previous_spec, ArenaEnvGraphSpec):
            prev_json = previous_spec.model_dump(mode="json") if self._wire_adapter else previous_spec.to_dict()
        else:
            prev_json = previous_spec
        if self._wire_adapter:
            prev_json = self._wire_adapter.encode(prev_json)
        repair_user_msg = self._repair_user_message(
            original_prompt=original_prompt,
            previous_spec=prev_json,
            feedback_report=feedback_report,
            available_affordances=available_affordances,
            asset_catalog=asset_catalog,
        )
        data = self._inference_backend.run_json(
            StructuredOutputRequest(
                schema_name="ArenaEnvGraphSpec",
                schema=self._schema,
                system=self._request_system_prompt(),
                user=repair_user_msg,
                retry_label="repair_spec",
                parse_json=SpecWireAdapter.parse_json if self._wire_adapter or self._strict_domain_adapter else None,
            )
        )
        if self._wire_adapter:
            data = self._wire_adapter.decode(data)
        elif self._strict_domain_adapter:
            data = self._strict_domain_adapter.decode(self._strict_domain_adapter.encode(data))
        data = _sanitize_spec_candidate(data)
        try:
            spec = ArenaEnvGraphSpec.model_validate(data)
        except ValidationError as exc:
            traces.extend(format_validation_error(exc))
            return None, data
        traces.extend(collect_agent_ready_task_validation_traces(spec))
        return spec, data

    def _request_system_prompt(self) -> str:
        prompt = self._system_prompt()
        if not self._wire_adapter:
            return prompt
        return prompt.replace("OUTPUT SCHEMA STRUCTURE:", "DOMAIN EXAMPLE (not the wire output format):") + r"""
STRICT WIRE FORMAT — arena-spec-params-entries/v1:
The domain example and catalog describe semantics, not the response encoding.
Keep the complete scene structure as JSON objects/arrays matching the response schema.
ONLY each schema-declared freeform params map (assets, object references, tasks,
spatial relations) is an array of unique {"key": string, "value_json": string} entries.
Each value_json is valid JSON text for exactly ONE original parameter value,
including nested objects, arrays, strings, numbers, booleans and null. Preserve
nested keys and values; do not recursively convert dictionaries inside value_json.
Example domain params {"surface_anchor":"table_top","initial_pose":{"position_xyz":[0,0,1]}}
becomes params [{"key":"surface_anchor","value_json":"\"table_top\""},
{"key":"initial_pose","value_json":"{\"position_xyz\":[0,0,1]}"}].
An empty params map is []. Never encode the entire scene as a JSON string.
Emit every schema property (use null only where the schema allows it), with no
extra properties, duplicate keys, nonfinite numbers, markdown fences or comments.
The previous repair candidate, when present, uses this same map encoding but may
be incomplete or domain-invalid; preserve its valid data and fix the feedback.
"""

    @staticmethod
    def _repair_user_message(
        original_prompt: str,
        previous_spec: dict[str, Any],
        feedback_report: str,
        available_affordances: list[str] | None = None,
        asset_catalog: Any = None,
    ) -> str:
        affordance_sec = ""
        if available_affordances:
            affordance_sec = (
                "\nAVAILABLE INTROSPECTED AFFORDANCE PATCHES (USD Ground Truth):\n"
                f"{json.dumps(available_affordances, indent=2)}\n"
            )
        catalog_sec = ""
        if asset_catalog is not None:
            cat_str = (
                asset_catalog.to_catalog_string() if hasattr(asset_catalog, "to_catalog_string") else str(asset_catalog)
            )
            catalog_sec = f"\nREGISTERED ASSET VOCABULARY:\n{cat_str}\n\n"
        prompt_sec = f"TARGET GOAL / REFINEMENT REQUEST:\n{original_prompt}\n\n" if original_prompt else ""
        return (
            f"{catalog_sec}{prompt_sec}PREVIOUS CANDIDATE SPEC:\n{json.dumps(previous_spec, indent=2)}\n\nDIAGNOSTIC"
            f" FEEDBACK & INSTRUCTIONS:\n{feedback_report}\n{affordance_sec}\nINSTRUCTION:\nPerform a targeted"
            " modification on the candidate spec to satisfy all instructions and constraint feedback above.\n1. Update"
            " objects, relations, surface anchors, or containment hierarchies so they conform to registered catalogue"
            " names.\n2. Keep all valid unchanged objects, background, and embodiment configurations.\n3. Emit the"
            " complete valid ArenaEnvGraphSpec JSON matching the schema."
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
    {"kind": "on", "subject": "object_id", "reference": "background_id", "params": {"surface_anchor": "table_top", "surface_sector": "front_center"}}
  ],
  "reified_relations": [
    {
      "reifier_id": "reifier_object_background",
      "source_id": "object_id",
      "relation_type": "PLACED_ON",
      "target_id": "background_id",
      "surface_anchor": "table_top",
      "surface_sector": "front_center",
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
          "destination_location": "destination_object_id",
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
- For pick-and-place into a receptacle object (e.g. bowl, bin, box, plate), ``destination_location`` is the ID of that object (e.g. 'red_bowl'). Keep ``object_references`` as an empty list [].
- Do NOT generate ``object_references`` unless interacting with an articulated fixture part (e.g. a specific drawer or door in a cabinet).
- Do NOT generate ``cli_override_specs``; keep it as an empty list [] or omit it.

TELESCOPIC DOLLHOUSE SPATIAL PLACEMENT:
- Robot Stance: Grounded in front of the table/workspace (e.g. [-0.55, 0.0, 0.0] facing +X, or [0.0, 0.35, floor_z] facing +Y), NOT inside the table volume.
- Multi-Object & Receptacle Support: For pick-and-place tasks with receptacles (e.g. bin, bowl, tray), BOTH the pickable object(s) AND the destination receptacle must have explicit 'on' relations to the support fixture (e.g. table_top or shelf_tier).
- Reachability Envelope: All task-relevant objects must be placed within reachable distance of the robot base (r in [0.30, 0.80]m for Franka/Droid, r in [0.45, 0.95]m for G1).
- Non-Overlap & Headroom: Maintain at least 0.20m separation between objects on the same support surface.
"""
