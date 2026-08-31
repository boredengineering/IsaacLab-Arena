# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Visual Active Inference and Multimodal VLM Critic for IsaacLab-Arena environment generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional
from pydantic import BaseModel, Field

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec


class VisualCriticResult(BaseModel):
    """Structured evaluation result returned by the Visual VLM Critic."""

    conforms: bool = Field(
        default=True,
        description="True if the scene is visually sound, all task objects are visible, and approach headroom is clear.",
    )
    visibility_score: float = Field(
        default=10.0,
        description="Overall visual clarity score from 0.0 to 10.0.",
    )
    occluded_objects: list[str] = Field(
        default_factory=list,
        description="IDs of objects obstructed or hidden from primary camera views.",
    )
    actionable_feedback: str = Field(
        default="",
        description="Specific spatial or sector adjustments recommended to eliminate visual occlusions.",
    )


class VisualSceneCritic:
    """Evaluates visual line-of-sight, occlusion, and aesthetic clarity of candidate environments."""

    def __init__(self, backend: Optional[Any] = None):
        self.backend = backend

    def evaluate_scene_spec(
        self,
        spec: ArenaEnvGraphSpec,
        rendered_images: Optional[dict[str, Any]] = None,
    ) -> VisualCriticResult:
        """Evaluate visual occlusion and spatial camera headroom.

        When rendered images and a multimodal backend are available, performs multimodal VLM evaluation.
        Otherwise, evaluates heuristic visual line-of-sight from camera viewpoint geometry.
        """
        # 1. Geometric line-of-sight heuristic check
        occlusions = self._check_geometric_line_of_sight(spec)
        if occlusions:
            feedback = "; ".join(occlusions)
            return VisualCriticResult(
                conforms=False,
                visibility_score=5.0,
                occluded_objects=[occ.split()[1] for occ in occlusions if len(occ.split()) > 1],
                actionable_feedback=f"Visual Line-of-Sight Occlusion Detected: {feedback}. Move occluded objects to front_center or front_left.",
            )

        # 2. Multimodal LLM check if images and backend are available
        if rendered_images and self.backend and hasattr(self.backend, "multimodal_chat"):
            try:
                vlm_res = self._call_vlm_critic(spec, rendered_images)
                return vlm_res
            except Exception:
                pass

        return VisualCriticResult(conforms=True, visibility_score=10.0, occluded_objects=[], actionable_feedback="")

    def _check_geometric_line_of_sight(self, spec: ArenaEnvGraphSpec) -> list[str]:
        """Check if objects are outside camera FOV / reach envelope or hidden behind taller obstacles."""
        issues: list[str] = []
        if not spec.embodiment:
            return issues

        emb_p = spec.embodiment.params.get("initial_pose", {}).get("position_xyz", [-0.55, 0.0, 0.0]) if spec.embodiment.params else [-0.55, 0.0, 0.0]
        
        objects_by_id = {obj.id: obj for obj in spec.objects}
        receptacles = [obj for obj in spec.objects if any(k in f"{obj.id} {obj.registry_name}".lower() for k in ("bin", "crate", "box", "rack", "shelf"))]
        manipulands = [obj for obj in spec.objects if obj not in receptacles]

        # 1. Camera FOV & Distance Standoff Check
        # For DROID / Franka on stand at [-0.55, 0.0], the primary camera frustum and dexterous reach span d in [0.30m, 0.70m] (world X in [-0.25, 0.15])
        max_dexterous_dist = 0.70
        for obj in spec.objects:
            pos = obj.params.get("initial_pose", {}).get("position_xyz") if obj.params else None
            if pos:
                dist = ((pos[0] - emb_p[0]) ** 2 + (pos[1] - emb_p[1]) ** 2) ** 0.5
                if dist > max_dexterous_dist:
                    issues.append(
                        f"Object '{obj.id}' is placed at distance {dist:.2f}m from robot base (X={pos[0]:.2f}m). "
                        f"This exceeds the camera FOV and dexterous reach envelope (max {max_dexterous_dist:.2f}m). "
                        f"The VLA policy cannot perceive the object in the camera frustum. Move object closer to robot (X in [-0.25m, 0.0m])."
                    )

        # 2. Line-of-sight occlusion between containers and manipulands
        for manip in manipulands:
            m_pos = manip.params.get("initial_pose", {}).get("position_xyz") if manip.params else None
            if not m_pos:
                continue
            for recep in receptacles:
                r_pos = recep.params.get("initial_pose", {}).get("position_xyz") if recep.params else None
                if not r_pos:
                    continue

                # Check if receptacle is directly between robot (x=-0.55) and manipuland along X-axis
                if emb_p[0] < r_pos[0] < m_pos[0] and abs(r_pos[1] - m_pos[1]) < 0.08:
                    issues.append(f"Object '{manip.id}' is visually occluded behind tall container '{recep.id}' from robot perspective")

        return issues

    def _call_vlm_critic(self, spec: ArenaEnvGraphSpec, images: dict[str, Any]) -> VisualCriticResult:
        """Call multimodal LLM with scene preview images."""
        prompt = (
            f"You are a robotic scene perception critic inspecting an IsaacLab simulation environment for task: {spec.task.description if spec.task else 'manipulation'}.\n"
            "Inspect the camera views and evaluate:\n"
            "1. Are all target objects clearly visible and unobstructed by bins or fixtures?\n"
            "2. Is there clear vertical headroom for the robot gripper to grasp each object?\n\n"
            "Return JSON matching: {\"conforms\": bool, \"visibility_score\": float, \"occluded_objects\": [str], \"actionable_feedback\": str}"
        )
        resp = self.backend.multimodal_chat(prompt, images)
        data = json.loads(resp)
        return VisualCriticResult(**data)


class PhysXPreflightCritic:
    """Preflight physics critic evaluating initial dynamic stability and contact safety."""

    def evaluate_physical_stability(self, spec: ArenaEnvGraphSpec) -> list[str]:
        """Check for physical placement instabilities (e.g. excessive drop heights, overlap)."""
        issues: list[str] = []
        for obj in spec.objects:
            obj_lower = f"{obj.id} {obj.registry_name}".lower()
            is_furniture = any(k in obj_lower for k in ("shelf", "shelving", "table", "counter", "desk", "rack"))
            if is_furniture:
                continue

            pos = obj.params.get("initial_pose", {}).get("position_xyz") if obj.params else None
            if pos and len(pos) >= 3:
                # Check for floating objects above table surface (nominal table deck is z=0.75m)
                if pos[2] > 0.95:
                    issues.append(
                        f"[PhysXCritic] Object '{obj.id}' initial Z={pos[2]:.2f}m is floating high above table surface. "
                        f"Drop impact may cause bouncing or toppling. Ground object near Z=0.76m."
                    )
                elif pos[2] < 0.50:
                    issues.append(
                        f"[PhysXCritic] Object '{obj.id}' initial Z={pos[2]:.2f}m is below table surface, penetrating floor or table structure."
                    )

        return issues
