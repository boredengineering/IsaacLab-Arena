# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Milestone 5 verification: Job J11 Evaluation Flywheel, Franka Panda primacy, GR00T tiered policy rollout, and Neo4j experience memory read-after-write closure."""

from __future__ import annotations

import os
import uuid

import pytest
from neo4j import GraphDatabase

from isaaclab_arena.agentic_environment_generation.execution.policy_rollout_worker import (
    FRANKA_CAMERA_NAMES,
    FRANKA_EMBODIMENT_NAME,
    FRANKA_EMBODIMENT_TAG,
    FRANKA_GR00T_CONFIG_PATH,
    DEFAULT_VARIATION_SWEEP,
    PolicyRolloutWorker,
    probe_gr00t_server,
)
from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever
from isaaclab_arena_examples.agentic_environment_generation.foreground_workflow import execute_operational_workflow


def _base_franka_tabletop_scene() -> dict:
    """Return a valid Franka Panda tabletop ArenaEnvGraphSpec dictionary."""
    return {
        "env_name": f"flywheel_golden_franka_{uuid.uuid4().hex[:8]}",
        "embodiment": {
            "id": FRANKA_EMBODIMENT_NAME,
            "registry_name": FRANKA_EMBODIMENT_NAME,
            "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0], "orientation_xyzw": [0.0, 0.0, 0.0, 1.0]}},
        },
        "background": {"id": "maple_table_robolab", "registry_name": "maple_table_robolab", "params": {}},
        "objects": [
            {
                "id": "rubiks_cube_hot3d_robolab",
                "registry_name": "rubiks_cube_hot3d_robolab",
                "params": {
                    "initial_pose": {
                        "position_xyz": [0.50, 0.0, 0.05],
                        "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
                    }
                },
            },
            {
                "id": "bowl_ycb_robolab",
                "registry_name": "bowl_ycb_robolab",
                "params": {
                    "initial_pose": {
                        "position_xyz": [0.55, 0.22, 0.05],
                        "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
                    }
                },
            },
        ],
        "relations": [
            {"kind": "is_anchor", "subject": "maple_table_robolab", "params": {}},
            {
                "kind": "on",
                "subject": "rubiks_cube_hot3d_robolab",
                "reference": "maple_table_robolab",
                "params": {"surface_anchor": "table_top", "surface_sector": "center"},
            },
            {
                "kind": "at_position",
                "subject": "rubiks_cube_hot3d_robolab",
                "params": {"x": 0.50, "y": 0.0, "yaw": 0.0, "surface_sector": "center"},
            },
            {
                "kind": "on",
                "subject": "bowl_ycb_robolab",
                "reference": "maple_table_robolab",
                "params": {"surface_anchor": "table_top", "surface_sector": "front_left"},
            },
        ],
        "reified_relations": [],
        "task": {
            "composition": "atomic",
            "description": "Franka picks up a Rubik's cube from the maple table and places it into a bowl.",
            "subtasks": [
                {
                    "kind": "PickAndPlaceTask",
                    "params": {
                        "pick_up_object": "rubiks_cube_hot3d_robolab",
                        "destination_location": "bowl_ycb_robolab",
                        "background_scene": "maple_table_robolab",
                    },
                }
            ],
        },
    }


@pytest.fixture
def neo4j_driver():
    """Connect to the local Neo4j instance on bolt://localhost:7688."""
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7688")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD", "isaaclab_arena_password")
    driver = GraphDatabase.driver(uri, auth=(user, pwd), connection_timeout=5, max_transaction_retry_time=0)
    try:
        driver.verify_connectivity()
        yield driver
    finally:
        driver.close()


def test_policy_rollout_worker_tiered_fallback_hierarchy():
    """Verify PolicyRolloutWorker tiered policy resolution, Franka Panda primacy, and graceful fallback."""
    # Test probing unreachable server
    is_up = probe_gr00t_server("localhost", 59999, timeout_s=0.05)
    assert not is_up

    # Test automatic tier resolution (falls back to tier 2 or tier 3 when port 59999 is closed)
    worker = PolicyRolloutWorker(gr00t_port=59999)
    resolved_tier, resolved_policy_id = worker.resolve_policy_tier()
    assert resolved_tier in ("tier2_rsl_rl", "tier3_zero_action")
    if resolved_tier == "tier2_rsl_rl":
        assert resolved_policy_id == "rsl_rl_franka_lift"
    else:
        assert resolved_policy_id == "zero_action_equilibrium"

    # Test explicit tier overrides
    tier_gr00t, pol_gr00t = worker.resolve_policy_tier(tier_override="tier1_gr00t")
    assert tier_gr00t == "tier1_gr00t"
    assert pol_gr00t == "gr00t_franka_manipulation"

    tier_rsl, pol_rsl = worker.resolve_policy_tier(tier_override="tier2_rsl_rl")
    assert tier_rsl == "tier2_rsl_rl"
    assert pol_rsl == "rsl_rl_franka_lift"

    tier_zero, pol_zero = worker.resolve_policy_tier(tier_override="tier3_zero_action")
    assert tier_zero == "tier3_zero_action"
    assert pol_zero == "zero_action_equilibrium"

    # Verify Franka Primacy contract invariants
    assert FRANKA_EMBODIMENT_TAG == "OXE_DROID"
    assert FRANKA_EMBODIMENT_NAME == "franka_ik"
    assert "wrist_camera_rgb" in FRANKA_CAMERA_NAMES
    assert "external_camera_rgb" in FRANKA_CAMERA_NAMES
    assert os.path.exists(FRANKA_GR00T_CONFIG_PATH)


def test_combinatorial_variation_sweeps():
    """Verify that PolicyRolloutWorker executes systematic parameter variation sweeps."""
    worker = PolicyRolloutWorker(policy_tier_override="tier1_gr00t")
    spec = _base_franka_tabletop_scene()

    sweep_res = worker.execute_evaluation_sweep(
        spec,
        variations=DEFAULT_VARIATION_SWEEP,
        steps_per_episode=20,
    )

    assert sweep_res.env_name == spec["env_name"]
    assert sweep_res.policy_id == "gr00t_franka_manipulation"
    assert sweep_res.policy_tier == "tier1_gr00t"
    assert sweep_res.total_episodes == len(DEFAULT_VARIATION_SWEEP)
    assert sweep_res.variations_evaluated == len(DEFAULT_VARIATION_SWEEP)
    assert sweep_res.success_rate >= 0.8  # Nominal + high friction + lighting passes
    assert sweep_res.executed_steps == len(DEFAULT_VARIATION_SWEEP) * 20

    # Verify variation matrix detail
    frictions = {v["friction"] for v in sweep_res.variation_matrix}
    assert 0.4 in frictions
    assert 0.8 in frictions
    assert 1.2 in frictions

    masses = {v["mass_multiplier"] for v in sweep_res.variation_matrix}
    assert 0.8 in masses
    assert 1.0 in masses
    assert 1.2 in masses

    # Verify metrics payload
    assert sweep_res.metrics_payload["embodiment"] == FRANKA_EMBODIMENT_NAME
    assert sweep_res.metrics_payload["embodiment_tag"] == FRANKA_EMBODIMENT_TAG
    assert "wrist_camera_rgb" in sweep_res.metrics_payload["cameras"]


def test_neo4j_evaluation_run_ingestion_and_graph_rag_read_closure(neo4j_driver, tmp_path):
    """Verify complete closed-loop: synthesis -> repair -> GOLD acceptance -> GR00T Franka sweep -> Neo4j ingestion -> Graph-RAG measured prior retrieval."""
    workspace_id = f"flywheel-{uuid.uuid4().hex[:10]}"
    deployment_id = "flywheel-deployment"
    initial_spec = _base_franka_tabletop_scene()
    env_name = initial_spec["env_name"]

    prompt = "Franka picks up a Rubik's cube from the maple table."
    rollout_worker = PolicyRolloutWorker(policy_tier_override="tier1_gr00t")

    # Step 1: Execute operational workflow with automated evaluation sweep enabled
    res = execute_operational_workflow(
        prompt=prompt,
        driver=neo4j_driver,
        database="neo4j",
        deployment_id=deployment_id,
        workspace_id=workspace_id,
        artifact_root=str(tmp_path / "artifacts_flywheel"),
        initial_spec_dict=initial_spec,
        target_subject="rubiks_cube_hot3d_robolab",
        rollout_worker=rollout_worker,
        run_evaluation_sweep=True,
    )

    assert res["final_state"] == "accepted"
    assert res["final_decision"] == "accept"
    assert res["evaluation_sweep"] is not None
    sweep = res["evaluation_sweep"]
    assert sweep["success_rate"] > 0.0
    assert sweep["total_episodes"] >= 1
    assert sweep["policy_id"] == "gr00t_franka_manipulation"

    # Step 2: Verify Neo4j graph nodes and edges
    with neo4j_driver.session(database="neo4j") as session:
        # Check GOLD EnvironmentGraph exists
        env_row = session.run(
            """
            MATCH (e:EnvironmentGraph {name: $env_name})
            RETURN e.name AS name, e.grade AS grade
            """,
            env_name=env_name,
        ).single()
        assert env_row is not None
        assert env_row["grade"] == "GOLD"

        # Check EvaluationRun is committed and linked to EnvironmentGraph and Policy
        eval_row = session.run(
            """
            MATCH (ev:EvaluationRun {id: $eval_id})-[:EVALUATED_GRAPH]->(e:EnvironmentGraph {name: $env_name})
            MATCH (ev)-[:USED_POLICY]->(p:Policy)
            RETURN ev.id AS eval_id, ev.success_rate AS success_rate, ev.num_episodes AS num_episodes,
                   p.policy_id AS policy_id, e.name AS env_name
            """,
            eval_id=sweep["eval_id"],
            env_name=env_name,
        ).single()
        assert eval_row is not None, "Expected (:EvaluationRun)-[:EVALUATED_GRAPH]->(:EnvironmentGraph)"
        assert eval_row["success_rate"] == sweep["success_rate"]
        assert eval_row["num_episodes"] == sweep["total_episodes"]
        assert eval_row["policy_id"] == "gr00t_franka_manipulation"

    # Step 3: Verify Read-After-Write Closure via GraphRAGRetriever
    retriever = GraphRAGRetriever(neo4j_driver)
    priors = retriever.retrieve_prior_subgraphs(
        prompt,
        limit=5,
        min_success_rate=0.0,
        min_episodes=1,
    )

    assert len(priors) >= 1, "GraphRAGRetriever must retrieve the evaluated prior"
    matched_prior = next((p for p in priors if p["name"] == env_name), None)
    assert matched_prior is not None, f"Environment {env_name} must be in retrieved priors: {priors}"
    assert matched_prior["evidence"] == "measured", f"Prior must carry 'measured' evidence, got: {matched_prior['evidence']}"
    assert matched_prior["success_rate"] > 0.0
    assert matched_prior["episodes"] >= 1
    assert matched_prior["embodiment"] == FRANKA_EMBODIMENT_NAME
