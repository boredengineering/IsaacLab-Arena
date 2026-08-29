# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""LLM inference for environment graph specs."""

from __future__ import annotations

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
        return f"{vocabulary}\n\nUSER PROMPT:\n{prompt}"

    @staticmethod
    def _system_prompt() -> str:
        return """\
You are an environment-generator for robot manipulation tasks.
Convert a natural-language prompt into an ArenaEnvGraphSpec.

GUIDANCE:
- Follow the per-field ``description`` strings in the schema.
- Use only exact names from the catalog for ``registry_name``:
  EMBODIMENTS for ``embodiment``, BACKGROUNDS for ``background``, and OBJECTS for ``objects``.
- Do NOT hallucinate asset names — every ``registry_name`` must appear verbatim in the catalog.
  If the prompt includes the exact registry name, use it.
  If no reasonable match can be found, return empty string.
  If multiple reasonable matches are found, return the closest match or the one with the most specific name.
- For embodiment, if the prompt only mention the robot family (driod/franka) and there are multiple
  variance of that family in EMBODIMENTS, pick the one with the default tag.
- For multiple instances of the same registry asset, use semantic (left/right) or numerical (1/2/3)
  suffixes in ``id``.
- Only populate ``object_references`` when the prompt explicitly mentions surfaces or appliances
  inside the background; otherwise leave it unset.
- TELESCOPIC DOLLHOUSE SPATIAL PLACEMENT:
  * Treat the scene like a dollhouse with structured multi-tier containment:
    1. Background Room (e.g. galileo): Static building structure (is_anchor: true). Note: Room floor level is z = -0.795m.
    2. Embodiment Base Stance: Grounded firmly on the room floor at z = -0.795m (e.g. pos: [0.0, 0.35, -0.795]), facing the shelving/workspace in the +Y direction.
    3. Furniture/Fixtures (e.g. wireshelving, table, counter): Placed on the floor inside the room in the front interaction zone (e.g. pos: [0.0, 1.1, -0.795]).
    4. Fixture Sub-Surfaces / Tiers: For shelving/counters, specify 'surface_anchor': 'shelf_tier_1' or 'shelf_tier_2' with nominal_height: 0.75.
    5. Manipulands (e.g. brown_box, mug, bottle): Small items MUST be placed on the furniture's sub-surface tier (subject: 'brown_box', reference: 'wireshelving', params: {'surface_anchor': 'shelf_tier_1'}), NEVER directly on the massive room envelope.
    6. Receptacles (e.g. blue_sorting_bin, floor zone): Placed adjacent on the floor in the workspace (e.g. pos: [0.6, 0.8, -0.795] or next_to: wireshelving).
  * Always ensure the primary interaction surface is anchored so the camera viewport directly frames the robot and workspace.
"""

