# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for EvaluationDiagnosticOracle and EvaluationRemediationEngine."""

from pathlib import Path
import tempfile
import yaml
import pytest

from isaaclab_arena.agentic_environment_generation.eval_self_healing import (
    EvaluationDiagnosticOracle,
    EvaluationRemediationEngine,
)
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec


def _sample_spec() -> ArenaEnvGraphSpec:
    return ArenaEnvGraphSpec.from_dict({
        "env_name": "test_droid_env",
        "embodiment": {
            "id": "droid",
            "registry_name": "droid_abs_joint_pos",
            "params": {"initial_pose": {"position_xyz": [-0.55, 0.0, 0.0], "rotation_xyzw": [0, 0, 0, 1]}},
        },
        "background": {"id": "table", "registry_name": "maple_table_robolab"},
        "objects": [
            {
                "id": "cube",
                "registry_name": "rubiks_cube_hot3d_robolab",
                "params": {"initial_pose": {"position_xyz": [-0.12, 0.14, 0.75], "rotation_xyzw": [0, 0, 0, 1]}},
            },
            {
                "id": "bin",
                "registry_name": "bin_b03_vomp_robolab",
                "params": {"initial_pose": {"position_xyz": [-0.12, -0.14, 0.75], "rotation_xyzw": [0, 0, 0, 1]}},
            },
        ],
        "relations": [
            {"kind": "is_anchor", "subject": "table"},
            {"kind": "on", "subject": "cube", "reference": "table", "params": {"surface_anchor": "table_top", "surface_sector": "front_left"}},
            {"kind": "on", "subject": "bin", "reference": "table", "params": {"surface_anchor": "table_top", "surface_sector": "front_right"}},
        ],
        "task": {
            "composition": "atomic",
            "description": "Pick up the Rubik's cube and place it into the bin.",
            "subtasks": [
                {
                    "kind": "PickAndPlaceTask",
                    "params": {
                        "pick_up_object": "cube",
                        "destination_location": "bin",
                        "background_scene": "table",
                    },
                }
            ],
        },
    })


def test_eval_diagnostic_oracle_detects_unconditioned_vla_and_horizon():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        eval_dir = tmp_path / "eval_run"
        eval_dir.mkdir()

        # Write dummy TTL
        ttl_content = """
        @prefix arena: <https://isaac-sim.github.io/arena/schema#> .
        :run arena:metric_success_rate "0.0"^^xsd:float ;
             arena:metric_num_episodes 0 .
        """
        (eval_dir / "eval_telemetry.ttl").write_text(ttl_content, encoding="utf-8")

        # Write policy config lacking language_instruction
        policy_cfg = tmp_path / "policy_config.yaml"
        policy_cfg.write_text(yaml.safe_dump({"action_horizon": 32, "embodiment_tag": "OXE_DROID"}), encoding="utf-8")

        spec = _sample_spec()
        oracle = EvaluationDiagnosticOracle()
        signatures = oracle.diagnose_eval_run(
            eval_dir=eval_dir,
            spec=spec,
            policy_config_path=policy_cfg,
            num_steps_executed=500,
        )

        defect_types = [s.defect_type for s in signatures]
        assert "unconditioned_vla" in defect_types
        assert "horizon_truncation" in defect_types


def test_eval_remediation_engine_applies_patches_and_relaxes_graph():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        policy_cfg = tmp_path / "policy_config.yaml"
        policy_cfg.write_text(yaml.safe_dump({"action_horizon": 32, "embodiment_tag": "OXE_DROID"}), encoding="utf-8")

        spec = _sample_spec()
        oracle = EvaluationDiagnosticOracle()
        eval_dir = tmp_path / "eval_dir"
        eval_dir.mkdir()
        (eval_dir / "summary_metrics.json").write_text('{"success_rate": 0.0, "num_episodes": 0}', encoding="utf-8")

        signatures = oracle.diagnose_eval_run(
            eval_dir=eval_dir,
            spec=spec,
            policy_config_path=policy_cfg,
            num_steps_executed=500,
        )

        engine = EvaluationRemediationEngine()
        out_dir = tmp_path / "healed_out"
        healed_spec, healed_policy_path, meta = engine.remediate_and_heal(
            spec=spec,
            policy_config_path=policy_cfg,
            signatures=signatures,
            out_dir=out_dir,
        )

        # Verify policy config was patched
        healed_policy_data = yaml.safe_load(healed_policy_path.read_text(encoding="utf-8"))
        assert "language_instruction" in healed_policy_data
        assert "Pick up the Rubik's cube" in healed_policy_data["language_instruction"]

        # Verify spec was written
        assert (out_dir / f"{healed_spec.env_name}.yaml").exists()
        assert meta["recommended_steps"] == 2000
