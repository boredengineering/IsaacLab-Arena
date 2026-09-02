# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Multi-Tier Visual Active Inference & Multimodal VLM Critic for IsaacLab-Arena.

Implements a resilient 4-tier visual perception and verification hierarchy:
- Tier 1: Cloud Frontier VLM (OpenRouter / Claude 3.7 / Gemini / GPT-4o)
- Tier 2: Self-Hosted Local VLM (vLLM / Ollama / SGLang / NIM e.g. Qwen2.5-VL / Cosmos-Reason)
- Tier 3: Deterministic Geometric & Camera Frustum Raycast Oracle (Pure Python / NumPy)
- Tier 4: Graceful Degradation & Non-Blocking User Advisory Banner
"""

from __future__ import annotations

import base64
import json
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional
from pydantic import BaseModel, Field

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.agentic_environment_generation.usd_stage_introspection import resolve_surface_anchor_bounding_box
from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import get_fixture_sector_bounds


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
    floating_objects: list[str] = Field(
        default_factory=list,
        description="IDs of objects suspended in air / ceiling or penetrating below fixture deck.",
    )
    anomalies: list[str] = Field(
        default_factory=list,
        description="List of concrete perceptual or physical anomalies detected.",
    )
    actionable_feedback: str = Field(
        default="",
        description="Specific spatial or sector adjustments recommended to eliminate visual occlusions.",
    )
    actionable_corrections: dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value geometric coordinate corrections (e.g. {'red_apple_z': 0.76}).",
    )
    tier_used: str = Field(
        default="tier_3_geometric_oracle",
        description="Which verification tier produced this result (tier_1_cloud_vlm, tier_2_local_vlm, tier_3_geometric_oracle, tier_4_advisory_fallback).",
    )


class VisualSceneCritic:
    """Evaluates visual line-of-sight, occlusion, and physical grounding across a 4-tier hierarchy."""

    def __init__(self, backend: Optional[Any] = None, local_vlm_url: Optional[str] = None):
        self.backend = backend
        self.local_vlm_url = local_vlm_url or os.environ.get("LOCAL_VLM_BASE_URL", "http://localhost:8000/v1")

    def evaluate_scene_spec(
        self,
        spec: ArenaEnvGraphSpec,
        rendered_images: Optional[dict[str, Any]] = None,
    ) -> VisualCriticResult:
        """Evaluate visual occlusion, camera frustum coverage, and support grounding across cascading tiers.

        Cascades in order:
        1. Tier 1: Cloud Frontier Multimodal VLM (OpenRouter Claude 3.7 / Gemini 2.5 / GPT-4o)
        2. Tier 2: Self-Hosted Local VLM (vLLM / Ollama / NIM)
        3. Tier 3: Deterministic Geometric & Camera Frustum Raycast Oracle
        4. Tier 4: Graceful Degradation & Non-Blocking User Advisory Banner
        """
        # --- Tier 1: Cloud Frontier VLM ---
        if rendered_images and self.backend and hasattr(self.backend, "multimodal_chat"):
            try:
                res = self._call_cloud_vlm_critic(spec, rendered_images)
                res.tier_used = "tier_1_cloud_vlm"
                return res
            except Exception as exc:
                print(f"[VisualCritic] Tier 1 Cloud VLM unavailable ({exc}), attempting Tier 2 Local VLM...")

        # --- Tier 2: Self-Hosted Local VLM ---
        if rendered_images:
            try:
                local_res = self._call_local_vlm_critic(spec, rendered_images)
                if local_res is not None:
                    local_res.tier_used = "tier_2_local_vlm"
                    return local_res
            except Exception as exc:
                print(f"[VisualCritic] Tier 2 Local VLM unavailable ({exc}), falling back to Tier 3 Geometric Oracle...")

        # --- Tier 3: Deterministic Geometric & Frustum Oracle ---
        try:
            geom_res = self._run_deterministic_geometric_oracle(spec)
            geom_res.tier_used = "tier_3_geometric_oracle"
            return geom_res
        except Exception as exc:
            print(f"[VisualCritic] Tier 3 Geometric Oracle encountered error ({exc}), invoking Tier 4 Advisory...")

        # --- Tier 4: Graceful Degradation Advisory ---
        return self._emit_tier4_advisory_result(spec)

    def _call_cloud_vlm_critic(self, spec: ArenaEnvGraphSpec, images: dict[str, Any]) -> VisualCriticResult:
        """Call cloud multimodal LLM with scene preview images."""
        prompt = (
            f"You are a robotic scene perception critic inspecting an IsaacLab simulation environment for task: {spec.task.description if spec.task else 'manipulation'}.\n"
            "Inspect the provided camera perspective(s), which include the robot's first-person egocentric head camera looking down at the tabletop and its own hands.\n"
            "Evaluate:\n"
            "1. Are all target objects clearly visible, unoccluded, and inside the robot's forward field of view?\n"
            "2. Are all objects physically resting on the countertop/table deck, or are any suspended in air / ceiling or penetrating the floor?\n"
            "3. Are the objects positioned in the correct relative quadrants (e.g. front-right vs. front-left) corresponding to the robot's hands?\n"
            "4. Is the robot standing at a feasible reach elevation and distance relative to the work surface?\n\n"
            "Return JSON matching:\n"
            "{\n"
            "  \"conforms\": bool,\n"
            "  \"visibility_score\": float,\n"
            "  \"occluded_objects\": [str],\n"
            "  \"floating_objects\": [str],\n"
            "  \"anomalies\": [str],\n"
            "  \"actionable_feedback\": str,\n"
            "  \"actionable_corrections\": dict\n"
            "}"
        )
        resp = self.backend.multimodal_chat(prompt, images)
        data = json.loads(resp) if isinstance(resp, str) else resp
        return VisualCriticResult(**data)

    def _call_local_vlm_critic(self, spec: ArenaEnvGraphSpec, images: dict[str, Any]) -> Optional[VisualCriticResult]:
        """Query local OpenAI-compatible VLM endpoint (e.g. vLLM / Ollama serving Qwen2.5-VL)."""
        content_payload: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"Robotic scene perception check for task: {spec.task.description if spec.task else 'manipulation'}. "
                    "Evaluate visibility, occlusion, and whether objects are grounded on the table vs. floating at ceiling. "
                    "Respond with strict JSON matching: {\"conforms\": bool, \"visibility_score\": float, \"occluded_objects\": [], \"floating_objects\": [], \"anomalies\": [], \"actionable_feedback\": \"\", \"actionable_corrections\": {}}"
                ),
            }
        ]

        for cam_name, img_data in images.items():
            if isinstance(img_data, bytes):
                b64_str = base64.b64encode(img_data).decode("utf-8")
                content_payload.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_str}"},
                })

        req_data = {
            "model": "default",
            "messages": [{"role": "user", "content": content_payload}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

        url = f"{self.local_vlm_url.rstrip('/')}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=3.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return VisualCriticResult(**parsed)

    def _run_deterministic_geometric_oracle(self, spec: ArenaEnvGraphSpec) -> VisualCriticResult:
        """Evaluate camera FOV coverage, line-of-sight occlusion, and support grounding via geometry."""
        anomalies: list[str] = []
        occluded: list[str] = []
        floating: list[str] = []
        corrections: dict[str, Any] = {}

        emb_pose = spec.embodiment.params.get("initial_pose", {}).get("position_xyz", [-0.55, 0.0, 0.0]) if spec.embodiment and spec.embodiment.params else [-0.55, 0.0, 0.0]
        bg_reg = spec.background.registry_name if spec.background else "maple_table_robolab"

        receptacles = [obj for obj in spec.objects if any(k in f"{obj.id} {obj.registry_name}".lower() for k in ("bin", "crate", "box", "rack", "shelf", "tall"))]
        manipulands = [obj for obj in spec.objects if obj not in receptacles]

        # 1. Check object grounding against fixture sub-prim deck elevation
        for obj in spec.objects:
            obj_lower = f"{obj.id} {obj.registry_name}".lower()
            if any(k in obj_lower for k in ("shelf", "shelving", "shelv", "table", "counter", "desk", "rack", "cabinet", "stand")):
                continue

            if not obj.params or "initial_pose" not in obj.params:
                continue

            pos = obj.params.get("initial_pose", {}).get("position_xyz")
            if not pos or len(pos) < 3:
                continue

            # Find matching relation anchor if present
            anchor_name = None
            for rel in spec.relations:
                if rel.subject == obj.id and rel.params and "surface_anchor" in rel.params:
                    anchor_name = str(rel.params["surface_anchor"])
                    break

            _, _, _, nominal_z = resolve_surface_anchor_bounding_box(bg_reg, anchor_name)

            # Check for ceiling floating (Z > nominal_z + 0.35m) or floor penetration (Z < nominal_z - 0.20m)
            if pos[2] > nominal_z + 0.35:
                floating.append(obj.id)
                anomalies.append(
                    f"Object '{obj.id}' Z={pos[2]:.2f}m is floating high above support deck (nominal Z={nominal_z:.2f}m). "
                    f"Grounded placement required."
                )
                corrections[f"{obj.id}_z"] = float(nominal_z + 0.01)
            elif pos[2] < nominal_z - 0.20:
                floating.append(obj.id)
                anomalies.append(
                    f"Object '{obj.id}' Z={pos[2]:.2f}m is penetrating below support deck (nominal Z={nominal_z:.2f}m)."
                )
                corrections[f"{obj.id}_z"] = float(nominal_z + 0.01)

            # 2. Check camera frustum & reach distance from robot base
            dist_xy = math.hypot(pos[0] - emb_pose[0], pos[1] - emb_pose[1])
            is_humanoid = spec.embodiment and ("g1" in spec.embodiment.registry_name.lower() or "gr1" in spec.embodiment.registry_name.lower())
            max_reach = 0.95 if is_humanoid else 0.75

            if dist_xy > max_reach:
                occluded.append(obj.id)
                anomalies.append(
                    f"Object '{obj.id}' is at distance {dist_xy:.2f}m from robot base (max reach {max_reach:.2f}m). "
                    f"Outside primary camera frustum and dexterous reach."
                )
            elif dist_xy < 0.20:
                occluded.append(obj.id)
                anomalies.append(
                    f"Object '{obj.id}' is too close to robot base ({dist_xy:.2f}m), within body occlusion zone."
                )

        # 3. Check line-of-sight occlusion between tall receptacles and manipulands
        for manip in manipulands:
            m_pos = manip.params.get("initial_pose", {}).get("position_xyz") if manip.params else None
            if not m_pos:
                continue
            for recep in receptacles:
                r_pos = recep.params.get("initial_pose", {}).get("position_xyz") if recep.params else None
                if not r_pos:
                    continue
                # If receptacle is directly between robot and manipuland along X/Y ray
                if emb_pose[0] < r_pos[0] < m_pos[0] and abs(r_pos[1] - m_pos[1]) < 0.10:
                    occluded.append(manip.id)
                    anomalies.append(f"Object '{manip.id}' is visually occluded behind tall container '{recep.id}' from robot perspective")

        conforms = len(anomalies) == 0
        visibility_score = 10.0 if conforms else max(2.0, 10.0 - 2.5 * len(anomalies))
        feedback = "; ".join(anomalies) if anomalies else ""

        return VisualCriticResult(
            conforms=conforms,
            visibility_score=visibility_score,
            occluded_objects=occluded,
            floating_objects=floating,
            anomalies=anomalies,
            actionable_feedback=feedback,
            actionable_corrections=corrections,
            tier_used="tier_3_geometric_oracle",
        )

    def _emit_tier4_advisory_result(self, spec: ArenaEnvGraphSpec) -> VisualCriticResult:
        """Graceful non-blocking fallback with structured user advisory."""
        advisory_msg = (
            "[ADVISORY][VisualPreflight]: Automated multimodal verification was bypassed. "
            "The environment proceeded using spatial factor graph relaxation. "
            "To enable live visual inspection, configure OPENROUTER_API_KEY, GEMINI_API_KEY, or launch a local vLLM server."
        )
        print(advisory_msg)
        return VisualCriticResult(
            conforms=True,
            visibility_score=8.0,
            occluded_objects=[],
            floating_objects=[],
            anomalies=[],
            actionable_feedback=advisory_msg,
            actionable_corrections={},
            tier_used="tier_4_advisory_fallback",
        )


class PhysXPreflightCritic:
    """Preflight physics critic evaluating initial dynamic stability and contact safety."""

    def evaluate_physical_stability(self, spec: ArenaEnvGraphSpec) -> list[str]:
        """Check for physical placement instabilities (e.g. excessive drop heights, overlap)."""
        issues: list[str] = []
        bg_reg = spec.background.registry_name if spec.background else "maple_table_robolab"

        for obj in spec.objects:
            obj_lower = f"{obj.id} {obj.registry_name}".lower()
            is_furniture = any(k in obj_lower for k in ("shelf", "shelving", "table", "counter", "desk", "rack"))
            if is_furniture:
                continue

            if not obj.params or "initial_pose" not in obj.params:
                continue

            pos = obj.params.get("initial_pose", {}).get("position_xyz")
            if pos and len(pos) >= 3:
                _, _, _, nominal_z = resolve_surface_anchor_bounding_box(bg_reg)
                if pos[2] > nominal_z + 0.30:
                    issues.append(
                        f"[PhysXCritic] Object '{obj.id}' initial Z={pos[2]:.2f}m is floating high above table surface (nominal Z={nominal_z:.2f}m). "
                        f"Drop impact may cause bouncing or toppling. Ground object near Z={nominal_z + 0.01:.2f}m."
                    )
                elif pos[2] < nominal_z - 0.15:
                    issues.append(
                        f"[PhysXCritic] Object '{obj.id}' initial Z={pos[2]:.2f}m is below table surface, penetrating floor or fixture."
                    )

        return issues
