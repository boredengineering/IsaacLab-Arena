# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Job J8: Refiner worker with support-polygon pre-projection and dual-coordinate sync.

Projects candidate proposals onto safe support polygons outside structural and FK exclusion
zones via project_pose_to_safe_support_surface() before envelope validation (Watch-Out 2)
and synchronizes /relations/{index}/params with /objects/{i}/params/initial_pose (Gap 1).

Must never import control-plane workflow modules, Omniverse Kit, or PyTorch.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from typing import Any

from .preflight_oracle import verify_service_endpoint
from .simulation_worker import relower_relations_to_object_poses


@dataclass(frozen=True)
class RefinementResult:
    """Structured result returned by RefinerWorker (Job J8)."""

    refined_spec_dict: dict[str, Any]
    target_subject: str
    projected_xyz: tuple[float, float, float]
    surface_sector: str | None
    yaw_rad: float
    used_llm: bool


def preproject_repair_proposal(
    original_spec_dict: dict[str, Any],
    proposed_spec_dict: dict[str, Any],
    *,
    target_subject: str,
    preferred_sector: str | None = None,
    max_displacement_m: float | None = None,
    sync_object_initial_pose: bool = True,
) -> RefinementResult:
    """Project a repair proposal onto the safe support polygon and synchronize coordinates.

    Calls project_pose_to_safe_support_surface() from spatial_geometric_oracle.py so that
    candidate coordinates are guaranteed to lie inside valid tabletop boundaries before
    being checked against repair_permission_envelope().
    """
    from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
        project_pose_to_safe_support_surface,
    )
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    candidate = copy.deepcopy(proposed_spec_dict)
    spec_obj = ArenaEnvGraphSpec.from_dict(candidate)

    # Determine sector preference from the proposed relation if not explicitly supplied
    sector_pref = preferred_sector
    yaw_val = 0.0
    for rel in candidate.get("relations", []):
        if isinstance(rel, dict) and rel.get("subject") == target_subject:
            rparams = rel.get("params") or {}
            if sector_pref is None and isinstance(rparams.get("surface_sector"), str):
                sector_pref = rparams["surface_sector"]
            if isinstance(rparams.get("yaw"), (int, float)):
                yaw_val = float(rparams["yaw"])

    safe_xyz, resolved_sector = project_pose_to_safe_support_surface(
        spec_obj,
        target_subject,
        preferred_sector=sector_pref,
    )

    # Find original (x, y, z) to clamp within max_displacement_m if specified
    orig_x, orig_y, orig_z = 0.0, 0.0, safe_xyz[2]
    oparams: dict[str, Any] = {}
    for rel in original_spec_dict.get("relations", []):
        if isinstance(rel, dict) and rel.get("kind") == "at_position" and rel.get("subject") == target_subject:
            oparams = rel.get("params") or {}
            orig_x = float(oparams.get("x", 0.0))
            orig_y = float(oparams.get("y", 0.0))
            orig_z = float(oparams.get("z", safe_xyz[2]))
            break

    px, py, pz = float(safe_xyz[0]), float(safe_xyz[1]), float(orig_z if "z" in oparams else safe_xyz[2])
    dx = px - orig_x
    dy = py - orig_y
    dist = (dx * dx + dy * dy) ** 0.5
    if dist < 1e-6:
        # Ensure a non-zero valid displacement when repairing a colliding/unstable pose
        step = min(0.04, (max_displacement_m or 0.1) * 0.5)
        px = round(orig_x + step, 6)
        py = round(orig_y, 6)
    elif max_displacement_m is not None and dist > max_displacement_m:
        scale = (max_displacement_m * 0.95) / dist
        px = round(orig_x + dx * scale, 6)
        py = round(orig_y + dy * scale, 6)
    else:
        px = round(px, 6)
        py = round(py, 6)

    for rel in candidate.get("relations", []):
        if isinstance(rel, dict) and rel.get("subject") == target_subject:
            rparams = rel.setdefault("params", {})
            if rel.get("kind") == "at_position":
                rparams["x"] = px
                rparams["y"] = py
                if "surface_sector" in rparams and resolved_sector:
                    rparams["surface_sector"] = resolved_sector
            elif rel.get("kind") == "on" and "surface_sector" in rparams and resolved_sector:
                rparams["surface_sector"] = resolved_sector

    if sync_object_initial_pose:
        candidate = relower_relations_to_object_poses(candidate)

    return RefinementResult(
        refined_spec_dict=candidate,
        target_subject=target_subject,
        projected_xyz=(px, py, round(float(pz), 6)),
        surface_sector=resolved_sector,
        yaw_rad=yaw_val,
        used_llm=False,
    )


class RefinerWorker:
    """Boundary worker for Job J8: Spec refinement with polygon pre-projection."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.2,
        strict_mode: bool = False,
    ) -> None:
        self.base_url = base_url or os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
        self.model = model
        self.api_key = api_key or "local-vllm"
        self.temperature = temperature
        self.strict_mode = strict_mode

    def refine(
        self,
        original_spec_or_dict: Any,
        current_spec_or_dict: Any,
        *,
        target_subject: str,
        feedback: str,
        preferred_sector: str | None = None,
        max_displacement_m: float | None = None,
        rendered_images: dict[str, bytes] | None = None,
        sync_object_initial_pose: bool = True,
        use_llm_if_available: bool = False,
    ) -> RefinementResult:
        """Refine a candidate specification and pre-project onto safe support polygon."""
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        orig_dict = (
            copy.deepcopy(original_spec_or_dict)
            if isinstance(original_spec_or_dict, dict)
            else original_spec_or_dict.model_dump(mode="json")
        )
        curr_dict = (
            copy.deepcopy(current_spec_or_dict)
            if isinstance(current_spec_or_dict, dict)
            else current_spec_or_dict.model_dump(mode="json")
        )

        proposed_dict = copy.deepcopy(curr_dict)
        used_llm = False

        if use_llm_if_available:
            llm_ok, llm_info = verify_service_endpoint(self.base_url)
            if llm_ok:
                try:
                    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
                        EnvironmentGenerationAgent,
                    )

                    agent = EnvironmentGenerationAgent(
                        model=self.model or (llm_info if llm_info != "ok" else None),
                        base_url=self.base_url,
                        api_key=self.api_key,
                        temperature=self.temperature,
                        strict_mode=self.strict_mode,
                    )
                    curr_spec = ArenaEnvGraphSpec.from_dict(curr_dict)
                    refined_spec, _ = agent.refine_spec(
                        curr_spec,
                        feedback=feedback,
                        rendered_images=rendered_images,
                    )
                    if refined_spec is not None:
                        proposed_dict = refined_spec.model_dump(mode="json")
                        used_llm = True
                except Exception:
                    pass

        res = preproject_repair_proposal(
            orig_dict,
            proposed_dict,
            target_subject=target_subject,
            preferred_sector=preferred_sector,
            max_displacement_m=max_displacement_m,
            sync_object_initial_pose=sync_object_initial_pose,
        )
        return RefinementResult(
            refined_spec_dict=res.refined_spec_dict,
            target_subject=res.target_subject,
            projected_xyz=res.projected_xyz,
            surface_sector=res.surface_sector,
            yaw_rad=res.yaw_rad,
            used_llm=used_llm,
        )
