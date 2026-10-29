# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Milestone 2 verification: Closed-loop orchestration, physical+visual repair routing, and Neo4j dual-schema bridge."""

from __future__ import annotations

import copy
import os
import uuid

import pytest
from neo4j import GraphDatabase


def _base_tabletop_scene(cube_xyz: list[float] | None = None) -> dict:
    """Return a valid tabletop ArenaEnvGraphSpec dictionary."""
    pos = list(cube_xyz) if cube_xyz is not None else [0.50, 0.0, 0.05]
    return {
        "env_name": "operational_golden_tabletop",
        "embodiment": {
            "id": "franka_ik",
            "registry_name": "franka_ik",
            "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0], "orientation_xyzw": [0.0, 0.0, 0.0, 1.0]}},
        },
        "background": {"id": "maple_table_robolab", "registry_name": "maple_table_robolab", "params": {}},
        "objects": [
            {
                "id": "rubiks_cube_hot3d_robolab",
                "registry_name": "rubiks_cube_hot3d_robolab",
                "params": {
                    "initial_pose": {
                        "position_xyz": pos,
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
                "params": {"x": float(pos[0]), "y": float(pos[1]), "yaw": 0.0, "surface_sector": "center"},
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


def test_gap4_assess_and_route_routes_physical_and_visual_failures_to_repair():
    """Verify Gap 4: both physical ('measured') and visual ('visual') failures route to action='repair'."""
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.agentic_environment_generation.workflow.scene_eligibility import (
        is_repairable_physical_or_visual_failure,
    )
    from isaaclab_arena.tests.test_environment_workflow_repairs import scene
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import observation, scene_contract

    contract = scene_contract()
    candidate = scene_loop.candidate_record("run-gap4", scene(), source_id="generation")

    # 1. Visual failure -> action='repair', reason='supported_visual_failure'
    obs_vis_fail = observation(contract, candidate, "cohort-vis", fail=True)
    dec_vis = scene_loop.assess_and_route(contract, candidate, obs_vis_fail)
    assert dec_vis.action == "repair"
    assert dec_vis.reason == "supported_visual_failure"
    assert is_repairable_physical_or_visual_failure(contract, dec_vis.assessment) is True

    # 2. Physical failure (measured criterion violated) -> action='repair', reason='supported_physical_failure'
    obs_base = observation(contract, candidate, "cohort-phys", fail=False)
    phys_records = tuple(
        rec.model_copy(update={"verdict": "violated" if rec.modality == "measured" else "established"})
        for rec in obs_base.evidence
    )
    obs_phys_fail = obs_base.model_copy(update={"evidence": phys_records})
    dec_phys = scene_loop.assess_and_route(contract, candidate, obs_phys_fail)
    assert dec_phys.action == "repair"
    assert dec_phys.reason == "supported_physical_failure"
    assert is_repairable_physical_or_visual_failure(contract, dec_phys.assessment) is True


def test_operational_golden_run_repairs_physical_drop_and_projects_dual_schema(neo4j_driver, tmp_path):
    """Verify end-to-end closed-loop repair of a physical drop failure, dual-schema projection, and prior retrieval."""
    from isaaclab_arena.agentic_environment_generation.execution.simulation_worker import SimulationWorkerPort
    from isaaclab_arena_examples.agentic_environment_generation.foreground_workflow import (
        execute_operational_workflow,
    )

    workspace_id = f"golden-ws-{uuid.uuid4().hex[:10]}"
    deployment_id = "golden-deployment"
    prompt = "Franka picks up a Rubik's cube from the kitchen table and places it into a bowl."

    # Initial spec has Rubik's cube off-table at x=2.5m so Attempt 1 triggers a physical drop/settle failure
    flawed_initial_spec = _base_tabletop_scene(cube_xyz=[2.50, 0.0, 0.05])
    sim_port = SimulationWorkerPort()

    # Run 1: Should fail Attempt 1 (physical drop), repair via J8 RefinerWorker + polygon projection,
    # and accept on Attempt 2 in the SAME persistent SimulationWorkerSession (0 restarts).
    res1 = execute_operational_workflow(
        prompt=prompt,
        driver=neo4j_driver,
        database="neo4j",
        deployment_id=deployment_id,
        workspace_id=workspace_id,
        artifact_root=str(tmp_path / "artifacts_run1"),
        initial_spec_dict=flawed_initial_spec,
        target_subject="rubiks_cube_hot3d_robolab",
        sim_port=sim_port,
        run_rollout=True,
    )

    assert res1["final_state"] == "accepted"
    assert res1["final_decision"] == "accept"
    assert res1["stage_calls"] == ["observe", "repair", "observe"]
    assert len(res1["attempts"]) == 2
    assert res1["attempts"][0]["settled_ok"] is False
    assert res1["attempts"][0]["drop_detected"] is True
    assert res1["attempts"][1]["settled_ok"] is True
    assert res1["attempts"][1]["drop_detected"] is False
    assert res1["subprocess_restarts"] == 0
    assert res1["accepted_candidate_id"] != res1["original_candidate_id"]
    assert res1["rollout_result"] is not None
    assert res1["rollout_result"].completed_episodes >= 1

    # Verify repaired spec has cube projected onto safe tabletop coordinates
    accepted_cube = next(
        o for o in res1["accepted_spec_dict"]["objects"] if o["id"] == "rubiks_cube_hot3d_robolab"
    )
    accepted_xyz = accepted_cube["params"]["initial_pose"]["position_xyz"]
    assert 0.30 <= accepted_xyz[0] <= 0.75
    assert -0.40 <= accepted_xyz[1] <= 0.40

    # Verify Neo4j Dual-Schema Bridge:
    # 1. (:ArenaWorkflowRun) is in state 'accepted'
    # 2. Failed original candidate has [:HAS_FAILURE_SIGNATURE]->(:FailureSignature)
    # 3. Accepted child candidate has grade='GOLD' and [:EXEMPLAR_PROJECTION]->(:EnvironmentGraph {grade: 'GOLD'})
    with neo4j_driver.session(database="neo4j") as session:
        gold_row = session.run(
            """
            MATCH (r:ArenaWorkflowRun {deployment_id: $dep, workspace_id: $ws, run_id: $run_id})
            MATCH (c:ArenaCandidateRecord {deployment_id: $dep, workspace_id: $ws, record_id: $cand_id})
                  -[:EXEMPLAR_PROJECTION]->(e:EnvironmentGraph)
            RETURN r.state AS run_state, c.grade AS cand_grade, e.grade AS env_grade,
                   e.spec_json AS env_spec_json, e.candidate_id AS env_cand_id
            """,
            dep=deployment_id,
            ws=workspace_id,
            run_id=res1["run_id"],
            cand_id=res1["accepted_candidate_id"],
        ).single()
        assert gold_row is not None, "Expected (:ArenaCandidateRecord)-[:EXEMPLAR_PROJECTION]->(:EnvironmentGraph)"
        assert gold_row["run_state"] == "accepted"
        assert gold_row["cand_grade"] == "GOLD"
        assert gold_row["env_grade"] == "GOLD"
        assert gold_row["env_cand_id"] == res1["accepted_candidate_id"]
        assert "rubiks_cube_hot3d_robolab" in gold_row["env_spec_json"]

        fail_row = session.run(
            """
            MATCH (c:ArenaCandidateRecord {deployment_id: $dep, workspace_id: $ws, record_id: $orig_id})
                  -[:HAS_FAILURE_SIGNATURE]->(f:FailureSignature)
            RETURN f.reason AS reason, f.candidate_id AS cand_id
            """,
            dep=deployment_id,
            ws=workspace_id,
            orig_id=res1["original_candidate_id"],
        ).single()
        assert fail_row is not None, "Expected failed candidate to record (:FailureSignature)"
        assert fail_row["reason"] == "supported_physical_failure"
        assert fail_row["cand_id"] == res1["original_candidate_id"]

    # Run 2 (Read-After-Write Closure):
    # Verify that a subsequent workflow run retrieves both the GOLD (:EnvironmentGraph) exemplar
    # and the (:FailureSignature) negative prior from Run 1.
    valid_initial_spec = _base_tabletop_scene(cube_xyz=[0.50, 0.0, 0.05])
    res2 = execute_operational_workflow(
        prompt=prompt,
        driver=neo4j_driver,
        database="neo4j",
        deployment_id=deployment_id,
        workspace_id=workspace_id,
        artifact_root=str(tmp_path / "artifacts_run2"),
        initial_spec_dict=valid_initial_spec,
        target_subject="rubiks_cube_hot3d_robolab",
        sim_port=sim_port,
        run_rollout=False,
    )
    assert res2["final_state"] == "accepted"
    assert res2["stage_calls"] == ["observe"]
    assert res2["subprocess_restarts"] == 0
    assert len(res2["prior_exemplars"]) >= 1
    assert any(
        ex.get("name") == "operational_golden_tabletop" for ex in res2["prior_exemplars"]
    ), f"Expected projected GOLD EnvironmentGraph in prior_exemplars, got: {res2['prior_exemplars']}"
    assert len(res2["prior_failure_signatures"]) >= 1
    assert any(
        fs.get("reason") == "supported_physical_failure" for fs in res2["prior_failure_signatures"]
    ), f"Expected FailureSignature in prior_failure_signatures, got: {res2['prior_failure_signatures']}"


def test_operational_golden_run_repairs_visual_critic_failure(neo4j_driver, tmp_path):
    """Verify end-to-end closed-loop repair when VisualCriticWorker detects a visual anomaly on Attempt 1."""
    from isaaclab_arena.agentic_environment_generation.execution.visual_critic_worker import (
        VisualCriticResult,
        VisualCriticWorker,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_workflow import (
        execute_operational_workflow,
    )

    class OneShotVisualFailureCritic(VisualCriticWorker):
        def __init__(self):
            super().__init__(strict_mode=False)
            self.calls = 0

        def evaluate(self, spec_or_dict, *, rendered_images=None):
            self.calls += 1
            if self.calls == 1:
                return VisualCriticResult(
                    conforms=False,
                    visibility_score=3.0,
                    tier_used="vlm_step0",
                    occluded_objects=("rubiks_cube_hot3d_robolab",),
                    floating_objects=(),
                    anomalies=("rubiks_cube_hot3d_robolab occluded in wrist view",),
                    actionable_feedback="Move rubiks_cube_hot3d_robolab to front_right sector.",
                )
            return super().evaluate(spec_or_dict, rendered_images=rendered_images)

    workspace_id = f"golden-vis-{uuid.uuid4().hex[:10]}"
    visual_worker = OneShotVisualFailureCritic()
    initial_spec = copy.deepcopy(_base_tabletop_scene(cube_xyz=[0.50, 0.0, 0.05]))

    res = execute_operational_workflow(
        prompt="Franka picks up a Rubik's cube from the kitchen table.",
        driver=neo4j_driver,
        database="neo4j",
        deployment_id="golden-deployment",
        workspace_id=workspace_id,
        artifact_root=str(tmp_path / "artifacts_vis"),
        initial_spec_dict=initial_spec,
        target_subject="rubiks_cube_hot3d_robolab",
        visual_worker=visual_worker,
        run_rollout=False,
    )

    assert res["final_state"] == "accepted"
    assert res["stage_calls"] == ["observe", "repair", "observe"]
    assert len(res["attempts"]) == 2
    assert res["attempts"][0]["visual_conforms"] is False
    assert res["attempts"][1]["visual_conforms"] is True
    assert res["subprocess_restarts"] == 0
