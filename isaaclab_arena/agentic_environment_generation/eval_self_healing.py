# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Evaluation-to-Active-Inference self-healing flywheel and diagnostic oracle."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
import yaml

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import relax_spec_spatial_factor_graph


@dataclass
class FailureSignature:
    """Classified failure mode with root cause, evidence, and remediation parameters."""

    defect_type: Literal[
        "unconditioned_vla",
        "horizon_truncation",
        "reach_singularity",
        "grasp_instability",
        "camera_occlusion",
        "unknown",
    ]
    severity: float  # 0.0 to 1.0
    evidence: str
    recommended_policy_patches: dict[str, Any] = field(default_factory=dict)
    recommended_spatial_patches: dict[str, Any] = field(default_factory=dict)


class EvaluationDiagnosticOracle:
    """Diagnoses policy evaluation failures from simulation telemetry and logs."""

    def diagnose_eval_run(
        self,
        eval_dir: Path | str,
        spec: ArenaEnvGraphSpec,
        policy_config_path: Path | str | None = None,
        num_steps_executed: int = 500,
    ) -> list[FailureSignature]:
        """Analyze evaluation artifacts and isolate root-cause failure signatures."""
        eval_path = Path(eval_dir)
        signatures: list[FailureSignature] = []

        # 1. Load policy config if present
        policy_cfg_dict: dict[str, Any] = {}
        if policy_config_path and Path(policy_config_path).exists():
            try:
                policy_cfg_dict = yaml.safe_load(Path(policy_config_path).read_text(encoding="utf-8")) or {}
            except Exception:
                pass

        # 2. Ingest telemetry / metrics
        metrics: dict[str, Any] = {}
        ttl_file = next(eval_path.glob("**/eval_telemetry.ttl"), None)
        metrics_file = next(eval_path.glob("**/summary_metrics.json"), None)

        if metrics_file and metrics_file.exists():
            try:
                metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        elif ttl_file and ttl_file.exists():
            ttl_text = ttl_file.read_text(encoding="utf-8")
            if 'metric_success_rate "0.0"' in ttl_text or "metric_success_rate 0.0" in ttl_text:
                metrics["success_rate"] = 0.0
            if "metric_num_episodes 0" in ttl_text or 'metric_num_episodes "0"' in ttl_text:
                metrics["num_episodes"] = 0

        success_rate = float(metrics.get("success_rate", 0.0))
        object_moved_rate = float(metrics.get("object_moved_rate", 0.0))

        # Check Defect 1: VLA Training Distribution & Camera Perception Standoff (CRITICAL)
        # If object_moved_rate == 0.0 or success_rate == 0.0, check for tabletop near-field placement
        emb_p = (
            spec.embodiment.params.get("initial_pose", {}).get("position_xyz", [-0.55, 0.0, 0.0])
            if spec.embodiment and spec.embodiment.params
            else [-0.55, 0.0, 0.0]
        )

        # Identify manipuland vs container
        manipuland_id = None
        container_id = None
        for obj in spec.objects:
            is_recep = any(k in obj.id.lower() or k in obj.registry_name.lower() for k in ("bin", "basket", "box", "tray", "bowl", "plate"))
            if is_recep:
                container_id = obj.id
            else:
                manipuland_id = obj.id

        # Check if objects are explicitly constrained to near-field
        has_near_field_manipuland = False
        for rel in spec.relations:
            if rel.kind == "on" and rel.params:
                if rel.params.get("surface_sector") in ("front_center", "front_left", "front_right"):
                    if rel.subject == manipuland_id:
                        has_near_field_manipuland = True

        if object_moved_rate == 0.0 or not has_near_field_manipuland:
            signatures.append(
                FailureSignature(
                    defect_type="camera_occlusion",
                    severity=0.99,
                    evidence=(
                        f"Robot failed to contact or move target object (object_moved_rate={object_moved_rate:.2f}). "
                        f"For VLA policies (e.g. GR00T-DROID, OpenVLA), objects placed without strict near-field "
                        f"constraints (d in [0.25m, 0.45m], X in [-0.30m, -0.10m]) fall outside the downward camera crop "
                        f"and teleoperation training distribution. The table must be shifted closer to the robot base."
                    ),
                    recommended_spatial_patches={
                        "maple_table": {"position_xyz": [-0.15, 0.0, 0.0]},
                        manipuland_id or "pick_up_object": {"surface_sector": "front_center", "sector_bounds": [-0.30, -0.10, -0.15, 0.15]},
                        container_id or "destination_location": {"surface_sector": "front_left", "sector_bounds": [-0.30, -0.10, 0.15, 0.35]},
                    },
                )
            )

        # Check Defect 2: Unconditioned VLA Model
        lang_instr = policy_cfg_dict.get("language_instruction", "")
        if not lang_instr or str(lang_instr).strip() == "":
            task_desc = spec.task.description if spec.task else "Manipulate target object"
            signatures.append(
                FailureSignature(
                    defect_type="unconditioned_vla",
                    severity=0.95,
                    evidence="Policy config lacks 'language_instruction'; VLA multimodal backbone received empty text conditioning.",
                    recommended_policy_patches={"language_instruction": task_desc},
                )
            )

        # Check Defect 3: Horizon Truncation
        if success_rate < 0.5 and num_steps_executed <= 600:
            signatures.append(
                FailureSignature(
                    defect_type="horizon_truncation",
                    severity=0.80,
                    evidence=f"Rollout was limited to {num_steps_executed} steps ({num_steps_executed * 0.02:.1f}s), terminating before multi-stage pick-and-place completed.",
                    recommended_policy_patches={"num_steps": 2000},
                )
            )

        return signatures


class EvaluationRemediationEngine:
    """Applies automated policy config patches and spatial spec refinements based on diagnostic signatures."""

    def remediate_and_heal(
        self,
        spec: ArenaEnvGraphSpec,
        policy_config_path: Path | str,
        signatures: list[FailureSignature],
        out_dir: Path | str,
    ) -> tuple[ArenaEnvGraphSpec, Path, dict[str, Any]]:
        """Apply fixes to policy config and environment spec, relaxing the factor graph."""
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        policy_path = Path(policy_config_path)
        policy_dict: dict[str, Any] = {}
        if policy_path.exists():
            policy_dict = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}

        remediation_meta: dict[str, Any] = {
            "applied_fixes": [],
            "recommended_steps": 2000,
        }

        # 1. Apply Policy Config Patches
        for sig in signatures:
            if sig.recommended_policy_patches:
                for k, v in sig.recommended_policy_patches.items():
                    if k == "num_steps":
                        remediation_meta["recommended_steps"] = int(v)
                    else:
                        policy_dict[k] = v
                        remediation_meta["applied_fixes"].append(f"Patched policy config '{k}' = '{v}'")

        # Save patched policy config in out_dir
        healed_policy_path = out_path / policy_path.name
        healed_policy_path.write_text(yaml.safe_dump(policy_dict, sort_keys=False), encoding="utf-8")

        # 2. Apply Spatial Spec Refinements
        spec_dict = spec.to_dict()
        modified_spatial = False

        for sig in signatures:
            if sig.recommended_spatial_patches:
                for obj_id, patch in sig.recommended_spatial_patches.items():
                    # Handle background table repositioning
                    if obj_id in ("background", "maple_table", "table", spec_dict.get("background", {}).get("id")):
                        if "position_xyz" in patch:
                            if "params" not in spec_dict["background"]:
                                spec_dict["background"]["params"] = {}
                            if "initial_pose" not in spec_dict["background"]["params"]:
                                spec_dict["background"]["params"]["initial_pose"] = {}
                            spec_dict["background"]["params"]["initial_pose"]["position_xyz"] = patch["position_xyz"]
                            modified_spatial = True
                            remediation_meta["applied_fixes"].append(
                                f"Shifted background table origin closer to robot: {patch['position_xyz']}"
                            )

                    # Handle embodiment robot repositioning
                    elif obj_id in ("embodiment", "droid_robot", "robot", spec_dict.get("embodiment", {}).get("id")):
                        if "position_xyz" in patch:
                            if "params" not in spec_dict["embodiment"]:
                                spec_dict["embodiment"]["params"] = {}
                            if "initial_pose" not in spec_dict["embodiment"]["params"]:
                                spec_dict["embodiment"]["params"]["initial_pose"] = {}
                            spec_dict["embodiment"]["params"]["initial_pose"]["position_xyz"] = patch["position_xyz"]
                            modified_spatial = True
                            remediation_meta["applied_fixes"].append(
                                f"Shifted robot base origin: {patch['position_xyz']}"
                            )

                    # Update object on-table relations
                    for rel in spec_dict.get("relations", []):
                        if rel.get("subject") == obj_id and rel.get("kind") == "on":
                            if "params" not in rel:
                                rel["params"] = {}
                            if "surface_sector" in patch:
                                rel["params"]["surface_sector"] = patch["surface_sector"]
                                modified_spatial = True
                                remediation_meta["applied_fixes"].append(
                                    f"Shifted '{obj_id}' surface_sector to '{patch['surface_sector']}'"
                                )

        healed_spec = ArenaEnvGraphSpec.from_dict(spec_dict)
        if modified_spatial:
            # Re-relax spatial factor graph with updated sector constraints
            healed_spec, _ = relax_spec_spatial_factor_graph(healed_spec)

        # Save healed spec
        yaml_out = out_path / f"{healed_spec.env_name}.yaml"
        healed_spec.write_yaml(yaml_out)

        return healed_spec, healed_policy_path, remediation_meta
