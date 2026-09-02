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
from isaaclab_arena.agentic_environment_generation.inference_backend import InferenceBackend, StructuredOutputRequest


@dataclass
class FailureSignature:
    """Classified failure mode with root cause, evidence, and remediation parameters."""

    defect_type: str
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
        healing_mode: str = "hybrid",
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.2,
    ) -> list[FailureSignature]:
        """Analyze evaluation artifacts and isolate root-cause failure signatures.

        Args:
            eval_dir: Path to evaluation output directory containing results.
            spec: ArenaEnvGraphSpec for the evaluated environment.
            policy_config_path: Optional path to policy configuration YAML.
            num_steps_executed: Simulation step limit used during evaluation.
            healing_mode: 'deterministic' (Option A), 'llm' (Option B), or 'hybrid' (Option A + B fallback).
            api_key: Optional API key for LLM inference.
            model: Optional LLM model identifier.
            base_url: Optional base URL for LLM API.
            temperature: LLM sampling temperature.

        Returns:
            List of classified FailureSignature objects.
        """
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

        # Ingest granular episode results JSONL for statistical stage progression funnel
        jsonl_files = list(eval_path.glob("**/episode_results_rank*.jsonl"))
        lifted_count = 0
        total_episodes_counted = 0
        placed_count = 0
        if jsonl_files:
            for jf in jsonl_files:
                for line in jf.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        total_episodes_counted += 1
                        events = rec.get("progress", {}).get("events", [])
                        if any("object_is_above_height" in e.get("predicate_name", "") for e in events):
                            lifted_count += 1
                        if rec.get("success", False):
                            placed_count += 1
                    except Exception:
                        pass

        lift_rate = (lifted_count / total_episodes_counted) if total_episodes_counted > 0 else object_moved_rate
        conversion_rate = (placed_count / lifted_count) if lifted_count > 0 else 0.0

        # --- OPTION A: Deterministic Statistical & Spatial Oracle Rules ---
        if healing_mode in ("deterministic", "hybrid"):
            # Check Defect 1: VLA Training Distribution & Camera Perception Standoff (CRITICAL)
            manipuland_id = None
            container_id = None
            for obj in spec.objects:
                is_recep = any(k in obj.id.lower() or k in obj.registry_name.lower() for k in ("bin", "basket", "box", "tray", "bowl", "plate"))
                if is_recep:
                    container_id = obj.id
                else:
                    manipuland_id = obj.id

            has_near_field_manipuland = False
            for rel in spec.relations:
                if rel.kind == "on" and rel.params:
                    if rel.params.get("surface_sector") in ("front_center", "front_left", "front_right"):
                        if rel.subject == manipuland_id:
                            has_near_field_manipuland = True

            if (object_moved_rate == 0.0 and lift_rate == 0.0) or not has_near_field_manipuland:
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

            # Check Defect 2: In-Flight Slippage & Open-Loop Inertial Jerk (Statistical Funnel Bottleneck)
            # Threshold tuned to <= 0.75 conversion rate to catch in-flight drops
            if total_episodes_counted >= 2 and lift_rate >= 0.50 and conversion_rate < 0.75:
                curr_chunk = policy_cfg_dict.get("action_chunk_length", 32)
                target_chunk = 16 if curr_chunk > 16 else 8
                signatures.append(
                    FailureSignature(
                        defect_type="in_flight_slip_inertia",
                        severity=0.92,
                        evidence=(
                            f"Statistical Funnel Bottleneck (N={total_episodes_counted}): "
                            f"Robot achieved initial reach and lift in {lift_rate * 100:.1f}% of episodes, "
                            f"but conversion to successful placement was only {conversion_rate * 100:.1f}%. "
                            f"High-lift with incomplete placement indicates in-flight rotational slippage, open-loop drift, "
                            f"or acceleration jerk during transport. Compress execution chunk (from {curr_chunk} to {target_chunk}) "
                            f"to enable high-frequency receding horizon feedback."
                        ),
                        recommended_policy_patches={
                            "action_chunk_length": target_chunk,
                        },
                    )
                )

            # Check Defect 3: Unconditioned VLA Model
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

            # Check Defect 4: Horizon Truncation
            if success_rate < 0.5 and num_steps_executed <= 600:
                signatures.append(
                    FailureSignature(
                        defect_type="horizon_truncation",
                        severity=0.80,
                        evidence=f"Rollout was limited to {num_steps_executed} steps ({num_steps_executed * 0.02:.1f}s), terminating before multi-stage pick-and-place completed.",
                        recommended_policy_patches={"num_steps": 2000},
                    )
                )

        # --- OPTION B: Generative LLM Healing (When configured or when deterministic signatures don't trigger) ---
        if healing_mode == "llm" or (healing_mode == "hybrid" and len(signatures) == 0 and success_rate < 0.8):
            llm_sigs = self._diagnose_with_llm(
                spec=spec,
                policy_cfg_dict=policy_cfg_dict,
                metrics=metrics,
                lift_rate=lift_rate,
                conversion_rate=conversion_rate,
                total_episodes=total_episodes_counted,
                api_key=api_key,
                model=model,
                base_url=base_url,
                temperature=temperature,
            )
            signatures.extend(llm_sigs)

        return signatures

    def _diagnose_with_llm(
        self,
        spec: ArenaEnvGraphSpec,
        policy_cfg_dict: dict[str, Any],
        metrics: dict[str, Any],
        lift_rate: float,
        conversion_rate: float,
        total_episodes: int,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.2,
    ) -> list[FailureSignature]:
        """Diagnose evaluation telemetry using generative LLM reasoning (Option B)."""
        backend = InferenceBackend(
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
        )

        schema = {
            "type": "object",
            "properties": {
                "signatures": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "defect_type": {"type": "string"},
                            "severity": {"type": "number"},
                            "evidence": {"type": "string"},
                            "recommended_policy_patches": {"type": "object", "additionalProperties": True},
                            "recommended_spatial_patches": {"type": "object", "additionalProperties": True},
                        },
                        "required": ["defect_type", "severity", "evidence", "recommended_policy_patches", "recommended_spatial_patches"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["signatures"],
            "additionalProperties": False,
        }

        system_prompt = (
            "You are an expert robotics simulation diagnostic engineer specializing in Foundation VLA policies (GR00T, OpenVLA, DROID) "
            "and Isaac Sim physics. Analyze the evaluation failure telemetry and recommend precise, grounded policy/spatial patches."
        )

        user_prompt = f"""Environment: {spec.env_name}
Task: {spec.task.description if spec.task else 'N/A'}
Embodiment: {spec.embodiment.registry_name if spec.embodiment else 'droid'}
Objects: {[obj.id for obj in spec.objects]}
Policy Config: {json.dumps(policy_cfg_dict, indent=2)}

Evaluation Telemetry (N={total_episodes}):
- Overall Success Rate: {metrics.get('success_rate', 0.0) * 100:.1f}%
- Object Lift Rate (Stage 1): {lift_rate * 100:.1f}%
- Placement Conversion Rate (Stage 2): {conversion_rate * 100:.1f}%
- Object Moved Rate: {metrics.get('object_moved_rate', 0.0) * 100:.1f}%

Identify any physical, kinematic, perceptual, or controller defects and provide exact parameter patches."""

        req = StructuredOutputRequest(
            schema_name="diagnostic_signatures",
            schema=schema,
            system=system_prompt,
            user=user_prompt,
            retry_label="diagnostic_oracle_llm",
        )

        try:
            res = backend.run_json(req)
            raw_sigs = res.get("signatures", [])
            llm_signatures = []
            for s in raw_sigs:
                llm_signatures.append(
                    FailureSignature(
                        defect_type=s.get("defect_type", "llm_diagnosed_defect"),
                        severity=float(s.get("severity", 0.85)),
                        evidence=s.get("evidence", "Diagnosed by generative Active Inference LLM."),
                        recommended_policy_patches=s.get("recommended_policy_patches", {}),
                        recommended_spatial_patches=s.get("recommended_spatial_patches", {}),
                    )
                )
            return llm_signatures
        except Exception as exc:
            print(f"[EvaluationDiagnosticOracle] Note: LLM diagnostic skipped or unavailable: {exc}")
            return []



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
