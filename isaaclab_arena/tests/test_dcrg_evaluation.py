# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import json

import pytest

from isaaclab_arena.agentic_environment_generation.dcrg.evaluation import read_episode_evidence


def test_evidence_uses_completed_predicates_not_progress_score(tmp_path):
    rows = [
        {
            "env_id": 0,
            "episode_in_env": 0,
            "seed": 42,
            "success": False,
            "episode_length": 300,
            "progress": {"overall_score": 1.0, "events": [{"predicate_name": "objects_settled"}]},
        },
        {
            "env_id": 0,
            "episode_in_env": 1,
            "seed": 42,
            "success": False,
            "episode_length": 300,
            "progress": {
                "events": [{"predicate_name": "object_lifted_above_resting_min(distance=0.015, min_airborne_steps=5)"}]
            },
        },
    ]
    path = tmp_path / "episode_results_rank0.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    evidence = read_episode_evidence(tmp_path, seed=42, expected_episodes=2)
    assert [row["success"] for row in evidence] == [False, False]
    assert [row["lifted"] for row in evidence] == [False, True]


@pytest.mark.parametrize("defect", ["missing", "duplicate", "wrong_seed", "false_success", "string_success"])
def test_invalid_episode_evidence_is_rejected(tmp_path, defect):
    row = {
        "env_id": 0,
        "episode_in_env": 0,
        "seed": 42,
        "success": False,
        "episode_length": 300,
        "progress": {"events": []},
    }
    rows = [row]
    if defect == "missing":
        rows = []
    elif defect == "duplicate":
        rows.append(row.copy())
    elif defect == "wrong_seed":
        row["seed"] = 7
    elif defect == "false_success":
        row["success"] = True
    elif defect == "string_success":
        row["success"] = "false"
    (tmp_path / "episode_results_rank0.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    with pytest.raises(AssertionError):
        read_episode_evidence(tmp_path, seed=42, expected_episodes=1)


def test_rollout_command_pins_seed_frame_and_episode_budget(tmp_path):
    from isaaclab_arena.agentic_environment_generation.dcrg.evaluation import build_rollout_command

    command = build_rollout_command(
        spec_path=tmp_path / "spec.yaml",
        policy_path=tmp_path / "policy.yaml",
        output_dir=tmp_path / "rollout",
        seed=7,
        episodes=2,
        remote_port=5561,
        hand_body="left_hand_middle_1_link",
        object_name="red_apple",
        destination_name="clay_plate",
        kit_args="--portable --portable-root /tmp/test-kit",
    )
    assert command[command.index("--seed") + 1] == "7"
    assert command[command.index("--placement_seed") + 1] == "7"
    assert command[command.index("--num_episodes") + 1] == "2"
    assert "--num_steps" not in command
    assert command[command.index("--trace_reach_hand_body") + 1] == "left_hand_middle_1_link"
    assert command[command.index("--remote_port") + 1] == "5561"
    assert command[command.index("--kit_args") + 1] == "--portable --portable-root /tmp/test-kit"


def test_failed_rollout_records_failure_without_episode_success(tmp_path, monkeypatch):
    import sys

    from isaaclab_arena.agentic_environment_generation.dcrg import evaluation as module

    for name in ("spec.yaml", "policy.yaml"):
        (tmp_path / name).write_text("test fixture")
    monkeypatch.setattr(module, "build_rollout_command", lambda **kwargs: [sys.executable, "-c", "raise SystemExit(5)"])
    with pytest.raises(RuntimeError, match="Rollout failed"):
        module.run_rollout(
            spec_path=tmp_path / "spec.yaml",
            policy_path=tmp_path / "policy.yaml",
            output_dir=tmp_path / "run",
            seed=42,
            episodes=1,
            remote_port=5561,
            hand_body="left_hand_middle_1_link",
            object_name="red_apple",
            destination_name="clay_plate",
            timeout_s=10,
        )
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["returncode"] == 5
    assert "episodes" not in manifest


def test_assisted_rollout_pins_controller_and_separate_trace(tmp_path):
    from isaaclab_arena.agentic_environment_generation.dcrg.evaluation import build_rollout_command

    config = tmp_path / "assistance.json"
    command = build_rollout_command(
        spec_path=tmp_path / "spec.yaml",
        policy_path=tmp_path / "policy.yaml",
        output_dir=tmp_path / "run",
        seed=42,
        episodes=1,
        remote_port=5565,
        hand_body="left_hand_middle_1_link",
        object_name="red_apple",
        destination_name="clay_plate",
        assistance_config_path=config,
    )
    assert (
        command[command.index("--policy_type") + 1]
        == "isaaclab_arena_gr00t.policy.gr00t_assisted_policy.Gr00tAssistedPolicy"
    )
    assert command[command.index("--assistance_config_path") + 1] == str(config.resolve())
    assert command[command.index("--assistance_trace_path") + 1] == str((tmp_path / "run/assistance.jsonl").resolve())


def test_failed_assisted_rollout_preserves_controller_digest(tmp_path, monkeypatch):
    import hashlib
    import sys

    from isaaclab_arena.agentic_environment_generation.dcrg import evaluation as module

    for name in ("spec.yaml", "policy.yaml"):
        (tmp_path / name).write_text("test fixture")
    config = tmp_path / "assistance.json"
    config.write_text('{"mode": "observe"}')
    monkeypatch.setattr(module, "build_rollout_command", lambda **kwargs: [sys.executable, "-c", "raise SystemExit(5)"])
    with pytest.raises(RuntimeError, match="Rollout failed"):
        module.run_rollout(
            spec_path=tmp_path / "spec.yaml",
            policy_path=tmp_path / "policy.yaml",
            output_dir=tmp_path / "run",
            seed=42,
            episodes=1,
            remote_port=5565,
            hand_body="left_hand_middle_1_link",
            object_name="red_apple",
            destination_name="clay_plate",
            assistance_config_path=config,
        )
    manifest = json.loads((tmp_path / "run/manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["assistance_config_sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()
    assert manifest["assistance_config_path"] == str(config.resolve())
