# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path
from isaaclab_arena.agentic_environment_generation.version_manager import EnvironmentVersionManager


def test_version_manager_lifecycle(tmp_path):
    gen_root = tmp_path / "generated_envs"
    eval_root = tmp_path / "eval_output"

    mgr = EnvironmentVersionManager(
        env_name="test_pnp_robot",
        generated_envs_root=gen_root,
        eval_output_root=eval_root,
    )

    assert mgr.get_latest_version() == 0

    # Create v1
    dummy_spec = {"env_name": "test_pnp_robot", "objects": []}
    dummy_policy = {"language_instruction": "test instruction"}

    v1, v1_dir = mgr.create_version(
        spec_source=dummy_spec,
        policy_config_source=dummy_policy,
        trigger="initial_generation",
        prompt="Pick up the red cube",
    )

    assert v1 == 1
    assert v1_dir.exists()
    assert (v1_dir / "test_pnp_robot.yaml").exists()
    assert (v1_dir / "policy_config.yaml").exists()
    assert mgr.get_latest_version() == 1

    # Record eval metrics for v1
    mgr.record_evaluation_metrics(
        version=1,
        metrics={"success_rate": 0.0, "progress_score": 0.33, "num_episodes": 2},
    )

    with open(mgr.lineage_file, "r") as f:
        lineage = json.load(f)
        assert lineage["current_version"] == 1
        assert lineage["versions"][0]["evaluation"]["success_rate"] == 0.0

    # Create v2 via auto-heal
    v2, v2_dir = mgr.create_version(
        spec_source=dummy_spec,
        policy_config_source=dummy_policy,
        trigger="auto_heal",
        parent_version=1,
        remediations=["Shift table closer to Franka arm (X in [-0.30, -0.10])"],
        diagnostics=["camera_occlusion"],
    )

    assert v2 == 2
    assert mgr.get_latest_version() == 2
    # Verify README.md generation and contents
    readme_file = mgr.env_dir / "README.md"
    assert readme_file.exists(), "README.md should be automatically generated"
    readme_content = readme_file.read_text(encoding="utf-8")
    assert "test_pnp_robot" in readme_content
    assert "Pick up the red cube" in readme_content
    assert "--viz kit" in readme_content
    assert "GEMINI_API_KEY" in readme_content
    assert "OPENROUTER_API_KEY" in readme_content
    assert "5557" in readme_content
    assert "Shift table closer" in readme_content
    assert "| `v1` |" in readme_content
    assert "| `v2` |" in readme_content

