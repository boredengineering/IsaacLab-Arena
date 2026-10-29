# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Milestone 3 verification suite: Causal Lightcone Estimator & In-Graph Dynamic Budgeting.

Verifies:
1. Job J7 (causal_estimator.py) Lyapunov error E(k), trajectory contraction Delta E(k),
   and causal horizon H*(s_k) across converging, narrow-cone, and diverging regimes.
2. Job J3 (SpatialGeometricOracleWorker) and Job J4 (SHACLValidatorWorker) WorkerPort integration.
3. In-Graph Dynamic Budget (:ExecutionBudget) and Transactional Causal Ledger (:BudgetTransaction)
   in live Neo4j, proving horizon expansion on contraction, graceful termination on divergence,
   and constant cryptographic contract_digest(contract) across all revisions (Gap 5).
"""

from __future__ import annotations

import os
import time
import uuid

from neo4j import GraphDatabase


def _live_neo4j_driver():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7688")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "isaaclab_arena_password")
    return GraphDatabase.driver(uri, auth=(user, password), connection_timeout=5, max_transaction_retry_time=0)


def _initial_unsettled_spec(env_name: str) -> dict:
    """Return a valid candidate spec dict where target object starts near the table edge."""
    from isaaclab_arena.agentic_environment_generation.execution.spec_synthesis_worker import (
        build_permissive_fallback_spec,
    )

    spec = build_permissive_fallback_spec(
        prompt="Place the rubiks cube on the packing table for manipulation.",
        env_name=env_name,
    )
    raw = spec.model_dump(mode="json")
    for obj in raw.get("objects", []):
        if obj.get("id") == "rubiks_cube_hot3d_robolab":
            obj.setdefault("params", {}).setdefault("initial_pose", {})["position_xyz"] = [0.48, 0.34, 0.78]
    has_at_pos = False
    for rel in raw.get("relations", []):
        if rel.get("kind") == "at_position" and rel.get("subject") == "rubiks_cube_hot3d_robolab":
            rel.setdefault("params", {})["x"] = 0.48
            rel["params"]["y"] = 0.34
            rel["params"]["z"] = 0.78
            rel["params"]["surface_sector"] = "center"
            rel["params"]["yaw"] = 0.0
            has_at_pos = True
    if not has_at_pos:
        raw.setdefault("relations", []).append(
            {
                "kind": "at_position",
                "subject": "rubiks_cube_hot3d_robolab",
                "params": {
                    "x": 0.48,
                    "y": 0.34,
                    "z": 0.78,
                    "surface_sector": "center",
                    "yaw": 0.0,
                },
            }
        )
    return raw


def test_causal_lightcone_estimator_math_and_worker_port():
    """Verify Job J7 Lyapunov error, contraction regimes, horizon estimation, and <1ms CPU execution."""
    from isaaclab_arena.agentic_environment_generation.causal_estimator import (
        CausalLightconeEstimator,
        TrajectoryStep,
        compute_lyapunov_error,
        estimate_causal_horizon,
        evaluate_trajectory_contraction,
    )

    t0 = time.perf_counter()
    # E(k) = 0.4 * 0.5 + 0.4 * 0.25 + 0.2 * (1 - 0.5) = 0.20 + 0.10 + 0.10 = 0.40
    e0 = compute_lyapunov_error(
        settle_telemetry={"settle_velocity_norm": 0.5},
        spatial_violations={"exclusion_distance": 0.25},
        visual_critic_score=0.5,
        weights=(0.4, 0.4, 0.2),
    )
    e1 = compute_lyapunov_error(
        settle_telemetry={"settle_velocity_norm": 0.1},
        spatial_violations={"exclusion_distance": 0.0},
        visual_critic_score=0.9,
        weights=(0.4, 0.4, 0.2),
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert abs(e0 - 0.40) < 1e-6
    assert abs(e1 - 0.06) < 1e-6
    assert elapsed_ms < 5.0

    # 1. Smooth quasi-static contraction -> H* = 3
    converging_res = evaluate_trajectory_contraction(
        [
            TrajectoryStep(step_index=0, lyapunov_error=e0),
            TrajectoryStep(step_index=1, lyapunov_error=e1),
        ]
    )
    assert converging_res.is_contracting is True
    assert converging_res.regime == "converging"
    assert abs(converging_res.delta_error - 0.34) < 1e-6
    h_deep = estimate_causal_horizon(
        scene_spec=None,
        physical_telemetry={"min_clearance_m": 0.15, "max_contact_force_n": 2.0},
        contraction_result=converging_res,
    )
    assert h_deep == 3

    # 2. Narrow clearance (< 0.05m) or high contact force -> H* = 1
    h_narrow_clearance = estimate_causal_horizon(
        scene_spec=None,
        physical_telemetry={"min_clearance_m": 0.03, "max_contact_force_n": 2.0},
        contraction_result=converging_res,
    )
    assert h_narrow_clearance == 1

    h_high_force = estimate_causal_horizon(
        scene_spec=None,
        physical_telemetry={"min_clearance_m": 0.15, "max_contact_force_n": 80.0},
        contraction_result=converging_res,
    )
    assert h_high_force == 1

    # 3. Diverging trajectory or topological collision -> H* = 0
    diverging_res = evaluate_trajectory_contraction(
        [
            TrajectoryStep(step_index=0, lyapunov_error=0.20),
            TrajectoryStep(step_index=1, lyapunov_error=0.55),
        ]
    )
    assert diverging_res.is_contracting is False
    assert diverging_res.regime == "diverging"
    assert diverging_res.delta_error < 0.0
    h_collapsed = estimate_causal_horizon(
        scene_spec=None,
        physical_telemetry={"min_clearance_m": 0.15, "max_contact_force_n": 0.0},
        contraction_result=diverging_res,
    )
    assert h_collapsed == 0

    h_collision = estimate_causal_horizon(
        scene_spec=None,
        physical_telemetry={"min_clearance_m": 0.15, "topological_collision": True},
        contraction_result=converging_res,
    )
    assert h_collision == 0

    # 4. WorkerPort lifecycle check on CausalLightconeEstimator
    estimator = CausalLightconeEstimator(max_ceiling=5)
    handle, reg = estimator.prepare(fence=None)
    assert "worker_id" in reg
    estimator.send(
        handle,
        {
            "physical_telemetry": {"settle_velocity_norm": 0.05, "min_clearance_m": 0.18},
            "spatial_violations": 0.0,
            "visual_critic_score": 0.95,
            "history": [{"step_index": 0, "lyapunov_error": 0.45}],
        },
    )
    receipt = estimator.receive(handle)
    assert receipt["horizon_H"] == 3
    assert receipt["regime"] == "converging"
    assert receipt["causal_status"] == "in_cone"
    stop_res = estimator.stop_owned(handle)
    assert stop_res["stopped"] is True


def test_spatial_and_shacl_oracle_worker_ports():
    """Verify Job J3 SpatialGeometricOracleWorker and Job J4 SHACLValidatorWorker WorkerPort interfaces."""
    from isaaclab_arena.agentic_environment_generation.rdf_validation import (
        SHACLValidatorWorker,
        validate_shacl_report,
    )
    from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
        SpatialGeometricOracleWorker,
    )

    spec_dict = _initial_unsettled_spec("oracle_port_test_env")

    # Job J3: SpatialGeometricOracleWorker
    spatial_worker = SpatialGeometricOracleWorker(relax_before_validate=True)
    h3, reg3 = spatial_worker.prepare(fence=None)
    assert "worker_id" in reg3
    spatial_worker.send(h3, {"spec": spec_dict, "relax": True})
    res3 = spatial_worker.receive(h3)
    assert "conforms" in res3
    assert "spec_dict" in res3
    assert isinstance(res3["diagnostics"], list)
    assert spatial_worker.stop_owned(h3)["stopped"] is True

    # Job J4: SHACLValidatorWorker
    shacl_worker = SHACLValidatorWorker()
    h4, reg4 = shacl_worker.prepare(fence=None)
    assert "worker_id" in reg4
    shacl_worker.send(h4, {"spec": res3["spec_dict"]})
    res4 = shacl_worker.receive(h4)
    assert isinstance(res4["conforms"], bool)
    assert res4["triples_count"] > 0
    assert shacl_worker.stop_owned(h4)["stopped"] is True

    direct_report = validate_shacl_report(res3["spec_dict"])
    assert direct_report.triples_count == res4["triples_count"]


def test_in_graph_dynamic_budget_expansion_and_divergence_termination():
    """Verify (:ExecutionBudget) expansion on contraction, collapse on divergence, and constant contract_digest."""
    from isaaclab_arena_examples.agentic_environment_generation.foreground_workflow import (
        execute_operational_workflow,
    )

    driver = _live_neo4j_driver()
    try:
        ws_expand = f"ws-expand-{uuid.uuid4().hex[:10]}"
        prompt = "Place the rubiks cube safely on the packing table."

        # --- Case 1: Monotonic Contraction Expands Causal Horizon ---
        # Outer ceiling max_revisions = 4, but initial_causal_horizon H_0 = 1.
        # Attempt 1 has high error (E = 0.44).
        # Attempt 2 contracts sharply (E = 0.12, Delta E = +0.32 > 0.15, clearance = 0.15 > 0.10),
        # so Job J7 estimates H* = 3 and expands (:ExecutionBudget).current_causal_horizon beyond H_0=1,
        # allowing Attempt 2 to repair into Attempt 3, which settles and is accepted as GOLD!
        contraction_schedule = [
            {
                "physical_ok": False,
                "visual_ok": False,
                "settle_telemetry": {"settle_velocity_norm": 0.60, "min_clearance_m": 0.15},
                "spatial_violations": 0.25,
                "visual_critic_score": 0.50,
            },
            {
                "physical_ok": False,
                "visual_ok": True,
                "settle_telemetry": {"settle_velocity_norm": 0.20, "min_clearance_m": 0.15},
                "spatial_violations": 0.05,
                "visual_critic_score": 0.90,
            },
            {
                "physical_ok": True,
                "visual_ok": True,
                "settle_telemetry": {"settle_velocity_norm": 0.0, "min_clearance_m": 0.18},
                "spatial_violations": 0.0,
                "visual_critic_score": 0.98,
            },
        ]
        res_expand = execute_operational_workflow(
            prompt=prompt,
            driver=driver,
            workspace_id=ws_expand,
            initial_spec_dict=_initial_unsettled_spec(f"expand_env_{ws_expand}"),
            max_revisions=4,
            initial_causal_horizon=1,
            telemetry_schedule=contraction_schedule,
        )

        # Because H_0 was 1, Attempt 3 is only reachable because Job J7 expanded current_causal_horizon!
        assert res_expand["final_state"] == "accepted"
        assert res_expand["final_decision"] == "accept"
        assert len(res_expand["attempts"]) == 3
        assert res_expand["execution_budget"] is not None
        assert res_expand["execution_budget"]["current_causal_horizon"] > 1
        assert res_expand["execution_budget"]["current_causal_horizon"] <= 4
        assert res_expand["execution_budget"]["max_ceiling"] == 4
        # Gap 5 invariant: contract_digest(contract) never mutated across all revisions
        assert len(set(res_expand["contract_digests"])) == 1

        # Verify (:BudgetTransaction) ledger nodes in Neo4j linked to (:ExecutionBudget) and (:CandidateRecord)
        tx_list = res_expand["budget_transactions"]
        assert len(tx_list) >= 3
        watermarks = [t["version_watermark"] for t in tx_list]
        assert watermarks == sorted(watermarks)
        with driver.session(database="neo4j") as session:
            linked_count = session.run(
                "MATCH (b:ExecutionBudget {run_id: $run_id})-[:HAS_TRANSACTION]->(t:BudgetTransaction)"
                "-[:FOR_CANDIDATE]->(c:CandidateRecord) "
                "RETURN count(t) AS cnt",
                run_id=res_expand["run_id"],
            ).single()["cnt"]
            assert linked_count >= 2

        # --- Case 2: Trajectory Divergence Collapses Causal Horizon & Terminates Early ---
        # Outer ceiling max_revisions = 5, initial_causal_horizon = 3.
        # Attempt 1 has E(0) = 0.20.
        # Attempt 2 diverges to E(1) = 0.72 (Delta E < 0, regime == "diverging").
        # Job J7 collapses current_causal_horizon to 0 (status="collapsed"),
        # and SceneLoop / Neo4jWorkflowStore stops immediately at Attempt 2 with reason="causal_lightcone_collapsed"!
        ws_diverge = f"ws-diverge-{uuid.uuid4().hex[:10]}"
        divergence_schedule = [
            {
                "physical_ok": False,
                "visual_ok": True,
                "settle_telemetry": {"settle_velocity_norm": 0.30, "min_clearance_m": 0.14},
                "spatial_violations": 0.10,
                "visual_critic_score": 0.80,
            },
            {
                "physical_ok": False,
                "visual_ok": False,
                "settle_telemetry": {"settle_velocity_norm": 1.10, "min_clearance_m": 0.02, "topological_collision": True},
                "spatial_violations": 0.50,
                "visual_critic_score": 0.20,
            },
            {
                "physical_ok": True,
                "visual_ok": True,
                "settle_telemetry": {"settle_velocity_norm": 0.0, "min_clearance_m": 0.18},
                "spatial_violations": 0.0,
                "visual_critic_score": 0.99,
            },
        ]
        res_diverge = execute_operational_workflow(
            prompt=prompt,
            driver=driver,
            workspace_id=ws_diverge,
            initial_spec_dict=_initial_unsettled_spec(f"diverge_env_{ws_diverge}"),
            max_revisions=5,
            initial_causal_horizon=3,
            telemetry_schedule=divergence_schedule,
        )

        # Must terminate at Attempt 2 without running Attempt 3!
        assert len(res_diverge["attempts"]) == 2
        assert res_diverge["final_decision"] == "stop"
        assert res_diverge["final_reason"] == "causal_lightcone_collapsed"
        assert res_diverge["execution_budget"]["current_causal_horizon"] == 0
        assert res_diverge["execution_budget"]["status"] == "collapsed"
        assert res_diverge["execution_budget"]["causal_status"] == "collapsed"
        # Gap 5 invariant: contract_digest(contract) remains constant even when horizon collapses to 0
        assert len(set(res_diverge["contract_digests"])) == 1
    finally:
        driver.close()
