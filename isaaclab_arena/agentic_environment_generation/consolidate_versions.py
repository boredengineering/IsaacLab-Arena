# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Consolidate scattered environment and evaluation runs into structured versioned trees."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from isaaclab_arena.agentic_environment_generation.version_manager import EnvironmentVersionManager


def consolidate_droid_rubiks():
    gen_root = Path("/workspaces/isaaclab_arena/generated_envs")
    eval_root = Path("/workspaces/isaaclab_arena/eval_output")

    canonical_env_name = "droid_rubiks_cube_to_blue_bin"
    mgr = EnvironmentVersionManager(
        canonical_env_name,
        generated_envs_root=gen_root,
        eval_output_root=eval_root,
    )

    # 1. Setup Version 1 (Initial Generation / Sector Verified)
    v1_source_spec = gen_root / "droid_rubiks_sector_verified" / "droid_rubiks_cube_to_blue_bin.yaml"
    if not v1_source_spec.exists():
        v1_source_spec = gen_root / "droid_rubiks_blue_bin" / "droid_pick_rubiks_cube_to_blue_bin.yaml"

    default_policy = Path("/workspaces/isaaclab_arena/isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml")

    v1, v1_dir = mgr.create_version(
        spec_source=v1_source_spec,
        policy_config_source=default_policy,
        trigger="initial_active_inference_generation",
        prompt="Droid stands in front of the table, picks up the Rubik's cube from the maple table and places it in the blue bin.",
        remediations=[],
        diagnostics=[],
    )

    # Associate Iteration 1 Evaluation if present
    eval_v1_source = eval_root / "droid_rubiks_closedloop_test" / "2026-08-31_20-30-26"
    eval_v1_target = eval_root / canonical_env_name / "v1"
    eval_v1_target.parent.mkdir(parents=True, exist_ok=True)
    if eval_v1_source.exists():
        if eval_v1_target.exists():
            shutil.rmtree(eval_v1_target)
        shutil.copytree(eval_v1_source, eval_v1_target)
        mgr.record_evaluation_metrics(
            version=1,
            metrics={"success_rate": 0.0, "object_moved_rate": 0.0, "num_episodes": 1},
            eval_output_dir=eval_v1_target,
        )

    # 2. Setup Version 2 (Auto-Healed VLA Proximity & Language Conditioning)
    v2_source_spec = gen_root / "droid_rubiks_auto_healed" / "droid_rubiks_cube_to_blue_bin.yaml"
    v2_source_policy = gen_root / "droid_rubiks_auto_healed" / "droid_manip_gr00t_closedloop_config.yaml"

    v2, v2_dir = mgr.create_version(
        spec_source=v2_source_spec,
        policy_config_source=v2_source_policy,
        trigger="active_inference_auto_heal",
        prompt="Pick up the Rubik's cube from the maple table and place it into the blue bin.",
        parent_version=1,
        remediations=[
            "Restricted tabletop placement to robot-facing front sector (X in [-0.30, -0.10]) within camera FOV",
            "Injected task description into policy YAML language_instruction parameter",
            "Extended evaluation horizon to 2000 steps (40 seconds)",
        ],
        diagnostics=[
            "camera_occlusion (standoff distance 1.28m exceeded camera FOV and reach limit)",
            "unconditioned_vla (missing language_instruction)",
            "horizon_truncation (step count 500 truncated before pick-and-place completed)",
        ],
    )

    # Associate Iteration 2 Evaluation if present
    eval_v2_source = eval_root / "droid_rubiks_healed_rollout" / "2026-08-31_21-11-33"
    eval_v2_target = eval_root / canonical_env_name / "v2"
    if eval_v2_source.exists():
        if eval_v2_target.exists():
            shutil.rmtree(eval_v2_target)
        shutil.copytree(eval_v2_source, eval_v2_target)
        mgr.record_evaluation_metrics(
            version=2,
            metrics={"success_rate": 0.0, "object_moved_rate": 0.0, "progress_score": 0.3333, "num_episodes": 2},
            eval_output_dir=eval_v2_target,
        )

    # 3. Clean up obsolete redundant directories
    redundant_gen_dirs = [
        gen_root / "droid_rubiks_auto_healed",
        gen_root / "droid_rubiks_sector_verified",
        gen_root / "droid_rubiks_blue_bin",
        gen_root / "droid_rubiks_b04_tabletop",
        gen_root / "droid_rubiks_small_blue_bin",
        gen_root / "droid_rubiks_vomp_b04",
    ]
    for r_dir in redundant_gen_dirs:
        if r_dir.exists() and r_dir != mgr.env_dir:
            shutil.rmtree(r_dir)

    redundant_eval_dirs = [
        eval_root / "droid_rubiks_closedloop_test",
        eval_root / "droid_rubiks_healed_rollout",
        eval_root / "droid_rubiks_cube_to_blue_bin_eval",
        eval_root / "droid_rubiks_vomp_b04_test",
    ]
    for r_dir in redundant_eval_dirs:
        if r_dir.exists() and r_dir != mgr.env_eval_dir:
            shutil.rmtree(r_dir)

    print(f"✅ Successfully consolidated {canonical_env_name} into structured version tree:")
    print(f"   Generated Environments: {mgr.env_dir}")
    print(f"   Evaluations:            {mgr.env_eval_dir}")
    print(f"   Current Version:        v{mgr.get_latest_version()}")


if __name__ == "__main__":
    consolidate_droid_rubiks()
