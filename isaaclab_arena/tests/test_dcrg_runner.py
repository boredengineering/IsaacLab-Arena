# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec


def test_runner_support_bounds_accept_saved_c1_and_reject_rotated_table():
    from isaaclab_arena_examples.agentic_environment_generation.dcrg_runner import support_bounds

    root = Path(__file__).resolve().parents[2]
    spec = ArenaEnvGraphSpec.from_yaml(
        root / "generated_envs/g1_tabletop_apple_to_plate/v32/g1_tabletop_apple_to_plate.yaml"
    )
    xmin, xmax, ymin, ymax = support_bounds(spec)
    x, y, _ = spec.objects[0].params["initial_pose"]["position_xyz"]
    assert xmin < x < xmax and ymin < y < ymax
    spec.background.params["initial_pose"]["rotation_xyzw"] = [0, 0, 0.707, 0.707]
    with pytest.raises(AssertionError, match="rotated"):
        support_bounds(spec)


def test_cli_exposes_frozen_contract_and_budgets(capsys):
    from isaaclab_arena_examples.agentic_environment_generation.dcrg_runner import main

    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    text = capsys.readouterr().out
    assert "--policy_identity" in text
    assert "--hand_body" in text
    assert "--max_candidates" in text
    assert "--reuse_baseline" in text


def test_changed_kit_args_cannot_resume_cached_evidence(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from isaaclab_arena_examples.agentic_environment_generation import dcrg_runner as runner

    root = Path(__file__).resolve().parents[2]
    source = root / "generated_envs/g1_tabletop_apple_to_plate/v32"
    calls = []
    monkeypatch.setattr(
        runner,
        "get_neo4j_driver",
        lambda **kwargs: SimpleNamespace(verify_connectivity=lambda: None, close=lambda: None),
    )
    real_loop = runner.run_dcrg

    def loop(*args, **kwargs):
        kwargs["sync_event"] = lambda event: None
        return real_loop(*args, **kwargs)

    def rollout(*args, **kwargs):
        calls.append(kwargs["kit_args"])
        return [{"seed": args[3], "env_id": 0, "episode_in_env": 0, "success": False, "lifted": False}]

    monkeypatch.setattr(runner, "run_dcrg", loop)
    monkeypatch.setattr(runner, "run_rollout", rollout)
    argv = [
        "--base_spec",
        str(source / "g1_tabletop_apple_to_plate.yaml"),
        "--policy_config",
        str(source / "policy_config.yaml"),
        "--policy_identity",
        "test-policy",
        "--scenario_contract",
        "test-contract",
        "--run_dir",
        str(tmp_path / "run"),
        "--hand_body",
        "left_hand_middle_1_link",
        "--seeds",
        "42",
        "--episodes_per_seed",
        "1",
        "--max_candidates",
        "0",
    ]
    runner.main([*argv, "--kit_args=--portable"])
    runner.main([*argv, "--kit_args=--portable"])
    assert calls == ["--portable"]
    with pytest.raises(AssertionError, match="contract"):
        runner.main([*argv, "--kit_args=--portable --/physics/cudaDevice=1"])
    assert calls == ["--portable"]


def test_graph_rag_history_is_policy_scoped_and_keeps_counts():
    from contextlib import nullcontext
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever

    calls = []
    row = {"versions": ["v1", "v2"], "success_rate": 0.0, "num_episodes": 4, "decision": "rejected"}
    session = SimpleNamespace(run=lambda query, **params: calls.append((query, params)) or [row])
    retriever = GraphRAGRetriever(SimpleNamespace(session=lambda: nullcontext(session)))
    assert retriever.retrieve_refinement_history("scene", "policy", accepted_only=False) == [row]
    assert calls[0][1]["policy_identity"] == "policy"
    assert calls[0][1]["source_env_name"] == "scene"
    assert calls[0][1]["accepted_only"] is False
    assert "EVOLVES_TO" in calls[0][0]
