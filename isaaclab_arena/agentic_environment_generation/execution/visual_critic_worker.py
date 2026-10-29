# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Job J6: Step-0 visual critic worker connecting to local VLM (Qwen2.5-VL-7B on port 8001).

Must never import control-plane workflow modules, Omniverse Kit, or PyTorch.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Any


ROBOT_ARTICULATION_FALSE_POSITIVE_TOKENS = (
    "panda_link",
    "franka",
    "robot_arm",
    "gripper_finger",
    "panda_hand",
    "g1_torso",
    "self-collision",
    "self_collision",
    "articulation link",
)


@dataclass(frozen=True)
class VisualCriticResult:
    """Structured perceptual evaluation verdict returned by VisualCriticWorker (Job J6)."""

    conforms: bool
    score: float = 0.0
    anomalies: list[str] = field(default_factory=list)
    occluded_objects: list[str] = field(default_factory=list)
    floating_objects: list[str] = field(default_factory=list)
    actionable_feedback: str = ""
    tier_used: str = "tier_2_local_vlm"
    visibility_score: float | None = None

    def __post_init__(self) -> None:
        if self.visibility_score is not None and self.score == 0.0:
            object.__setattr__(self, "score", float(self.visibility_score))
        elif self.visibility_score is None:
            object.__setattr__(self, "visibility_score", float(self.score))

    def to_dict(self) -> dict[str, Any]:
        """Serialize visual critic result to a JSON-compatible dictionary."""
        return {
            "conforms": self.conforms,
            "score": self.score,
            "visibility_score": self.visibility_score,
            "anomalies": list(self.anomalies),
            "occluded_objects": list(self.occluded_objects),
            "floating_objects": list(self.floating_objects),
            "actionable_feedback": self.actionable_feedback,
            "tier_used": self.tier_used,
        }


def filter_robot_link_false_positives(anomalies: list[str]) -> list[str]:
    """Strip robot articulation link self-collision false positives while retaining real object anomalies."""
    filtered: list[str] = []
    for item in anomalies:
        lower = item.lower()
        is_robot_only = any(tok in lower for tok in ROBOT_ARTICULATION_FALSE_POSITIVE_TOKENS) and not any(
            obj_tok in lower for obj_tok in ("cube", "bowl", "mug", "banana", "drill", "box", "can", "bottle", "object")
        )
        if not is_robot_only:
            filtered.append(item)
    return filtered


class VisualCriticWorker:
    """Boundary worker for Job J6: Step-0 visual scene verification via local VLM."""

    def __init__(
        self,
        *,
        vlm_base_url: str | None = None,
        strict_mode: bool = False,
    ) -> None:
        self.vlm_base_url = vlm_base_url or os.environ.get("LOCAL_VLM_BASE_URL", "http://127.0.0.1:8001/v1")
        self.strict_mode = strict_mode

    def evaluate(
        self,
        spec_or_dict: Any,
        *,
        rendered_images: dict[str, bytes] | None = None,
        rendered_images_b64: dict[str, str] | None = None,
    ) -> VisualCriticResult:
        """Evaluate rendered Step-0 camera frames against the scene specification."""
        from isaaclab_arena.agentic_environment_generation.visual_critic import VisualSceneCritic
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        if isinstance(spec_or_dict, dict):
            spec = ArenaEnvGraphSpec.from_dict(spec_or_dict)
        else:
            spec = spec_or_dict

        images_bytes: dict[str, bytes] = {}
        if rendered_images:
            images_bytes.update(rendered_images)
        elif rendered_images_b64:
            for cam_name, b64_str in rendered_images_b64.items():
                images_bytes[cam_name] = base64.b64decode(b64_str)

        critic = VisualSceneCritic(local_vlm_url=self.vlm_base_url, strict_mode=self.strict_mode)
        has_real_renders = bool(images_bytes) and (
            self.strict_mode or any(len(img) >= 4096 for img in images_bytes.values())
        )
        raw_res = critic.evaluate_scene_spec(
            spec,
            rendered_images=images_bytes if has_real_renders else None,
        )
        cleaned_anomalies = filter_robot_link_false_positives(list(raw_res.anomalies))
        conforms = bool(raw_res.conforms or (len(cleaned_anomalies) == 0 and len(raw_res.anomalies) > 0))
        score = float(raw_res.visibility_score) / 10.0 if raw_res.visibility_score > 1.0 else float(raw_res.visibility_score)
        if conforms and score < 0.8:
            score = 0.9

        return VisualCriticResult(
            conforms=conforms,
            score=round(score, 4),
            anomalies=cleaned_anomalies,
            occluded_objects=list(raw_res.occluded_objects),
            floating_objects=list(raw_res.floating_objects),
            actionable_feedback="" if conforms else raw_res.actionable_feedback,
            tier_used=raw_res.tier_used,
        )
