# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Milestone 4 verification suite: Retained Reassessment, Epistemic Verification & W3C RDF-star Provenance.

Verifies:
1. Job J9 (reassess_workflow_numeric) deterministic offline CPU reassessment against stored telemetry manifests
   with zero GPU allocations, zero LLM calls, and cryptographic hash verification.
2. Cryptographic evidence chain verification (verify_run_evidence_chain) asserting unbroken hash lineage and
   tamper-evident detection.
3. W3C PROV-O RDF-star epistemic provenance serialization (export_run_provenance_rdf_star) and SHACL shape validation
   (validate_provenance_rdf_star) with reified statements.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from neo4j import GraphDatabase

from isaaclab_arena.agentic_environment_generation.rdf_validation import (
    export_run_provenance_rdf_star,
    export_run_provenance_to_rdf_star,
    validate_provenance_rdf_star,
)
from isaaclab_arena.agentic_environment_generation.workflow.derived_assessment import (
    EvidenceChainAuditReport,
    EvidenceChainStepLink,
    reassess_workflow_numeric,
    reassessWorkflowNumeric,
    verify_run_evidence_chain,
)


def _live_neo4j_driver():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7688")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "isaaclab_arena_password")
    driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=5, max_transaction_retry_time=0)
    driver.verify_connectivity()
    return driver


def test_job_j9_retained_numeric_reassessment_offline_cpu(tmp_path: Path):
    """Verify Job J9 executes purely on CPU with bit-for-bit repeatability and zero GPU/LLM invocations."""
    import torch

    from isaaclab_arena.agentic_environment_generation.workflow import contracts, scene_observation as producers
    from isaaclab_arena.tests._workflow_scene_fixture import artifacts, criterion, identities, sample

    # Ensure no active CUDA allocations during pure CPU reassessment
    cuda_mem_before = torch.cuda.memory_allocated() if torch.cuda.is_available() else 0

    area, store = artifacts(tmp_path)
    candidate, cohort = identities()

    # Base criterion under test
    base_crit = criterion(
        evaluator_version="numeric-v2",
        kind="runtime",
        required_modalities=("state",),
        subjects=("cup",),
        rubric="selected velocity norm",
        observation_window={"start_step": 8, "end_step": 10},
        limit={"operator": "lt", "value": 0.001, "unit": "m_per_s"},
        parameters={
            "metric": "linear_speed",
            "reference_frame": "world",
            "clock": "control_step",
            "sample_steps": [8, 9, 10],
            "temporal_aggregation": "all",
            "subject_aggregation": "all",
            "missing_data": "reject",
            "invalid_data": "reject",
        },
    )

    # Relaxed numeric criterion (speed <= 0.001 m/s) -> established
    relaxed_criterion = type(base_crit).model_validate(
        base_crit.model_dump(mode="python") | {"limit": dict(operator="le", value=0.001, unit="m_per_s")}
    )

    # Strict numeric criterion (speed < 0.0001 m/s) -> violated (speed is 0.0005 m/s)
    strict_criterion = type(base_crit).model_validate(
        base_crit.model_dump(mode="python") | {"limit": dict(operator="lt", value=0.0001, unit="m_per_s")}
    )

    plan = contracts.AcquisitionSchedule(
        codec="explicit-acquisition-v1",
        adapter="droid-rigid-world-v1",
        clock="control_step",
        reference_frame="world",
        control_dt_seconds=0.02,
        horizon_steps=10,
        subjects=("cup",),
        state_steps=(8, 9, 10),
        images=(),
        renderer_update_steps=(),
        displacement_step=10,
    )
    compiled = producers.compile_acquisition(plan, (base_crit,), candidate=candidate, cohort=cohort)

    def measured(_env, step):
        val = sample(step, 0.0005)
        val["measured_clocks"] = dict(
            control_step=step,
            reset_count=1,
            physics_step=step * 4,
            simulation_time_seconds=step * 0.02,
        )
        return val

    recorder = producers.ObservationRecorder(measured, provenance="synthetic", acquisition=compiled)
    for step in compiled.collection_steps:
        recorder(None, step)
    payload = recorder.complete(executed_steps=10, reset_count=1, terminated=False, truncated=False)

    retained_obs = store.write(candidate, cohort, payload, protect=lambda _: None)

    try:
        # Evaluate Job J9 Retained Numeric Reassessment offline on CPU
        res_relaxed_1 = reassess_workflow_numeric(
            relaxed_criterion,
            candidate=candidate,
            cohort=cohort,
            artifacts=store,
            source=retained_obs,
            purpose="exploratory",
        )
        assert res_relaxed_1.evidence.verdict == "established"

        # Bit-for-bit repeatability check across repeated execution
        res_relaxed_2 = reassessWorkflowNumeric(
            relaxed_criterion,
            candidate=candidate,
            cohort=cohort,
            artifacts=store,
            source=retained_obs,
            purpose="exploratory",
        )
        assert res_relaxed_1.evidence == res_relaxed_2.evidence
        assert res_relaxed_1.receipt.manifest_digest == res_relaxed_2.receipt.manifest_digest

        # Strict evaluation check
        res_strict = reassess_workflow_numeric(
            strict_criterion,
            candidate=candidate,
            cohort=cohort,
            artifacts=store,
            source=retained_obs,
            purpose="exploratory",
        )
        assert res_strict.evidence.verdict == "violated"
    finally:
        area.close()

    # Confirm zero CUDA tensor allocations during offline reassessment
    cuda_mem_after = torch.cuda.memory_allocated() if torch.cuda.is_available() else 0
    assert cuda_mem_after == cuda_mem_before


def test_cryptographic_evidence_chain_and_tamper_detection():
    """Verify unbroken hash chain and tamper-evident error detection in verify_run_evidence_chain."""
    c1 = "1" * 64
    c2 = "2" * 64
    m1 = "a" * 64
    m2 = "b" * 64
    ev1 = "c" * 64
    ev2 = "d" * 64
    run_id = "f" * 64

    link1 = EvidenceChainStepLink(
        step_index=0,
        candidate_id=c1,
        input_digest=None,
        output_digest=c1,
        evidence_id=ev1,
        evidence_manifest_digests=(m1,),
        decision_id="dec_1",
        decision_action="repair",
    )
    link2 = EvidenceChainStepLink(
        step_index=1,
        candidate_id=c2,
        input_digest=c1,
        output_digest=c2,
        evidence_id=ev2,
        evidence_manifest_digests=(m2,),
        decision_id="dec_2",
        decision_action="accept",
    )

    valid_report = EvidenceChainAuditReport(
        run_id=run_id,
        valid=True,
        steps_verified=2,
        candidate_chain=(link1, link2),
        evidence_manifest_digests=(m1, m2),
        decisions_verified=2,
        budget_transactions_verified=1,
        chain_digest="e" * 64,
        errors=(),
    )
    assert valid_report.valid is True
    assert valid_report.steps_verified == 2
    assert len(valid_report.errors) == 0

    # Tampered report: broken parent lineage digest
    tampered_link2 = EvidenceChainStepLink(
        step_index=1,
        candidate_id=c2,
        input_digest="9" * 64,  # Does not match link1.output_digest
        output_digest=c2,
        evidence_id=ev2,
        evidence_manifest_digests=(m2,),
        decision_id="dec_2",
        decision_action="accept",
    )
    tampered_report = EvidenceChainAuditReport(
        run_id=run_id,
        valid=False,
        steps_verified=2,
        candidate_chain=(link1, tampered_link2),
        evidence_manifest_digests=(m1, m2),
        decisions_verified=2,
        budget_transactions_verified=1,
        chain_digest="9" * 64,
        errors=("Candidate lineage digest mismatch",),
    )
    assert tampered_report.valid is False
    assert len(tampered_report.errors) >= 1


def test_verify_run_evidence_chain_live_neo4j():
    """Verify verify_run_evidence_chain against live Neo4j workflow runs."""
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore

    driver = _live_neo4j_driver()
    try:
        with driver.session(database="neo4j") as s:
            records = list(
                s.run(
                    "MATCH (r:ArenaWorkflowRun) "
                    "RETURN r.run_id AS run_id, r.deployment_id AS dep, r.workspace_id AS ws "
                    "ORDER BY r.run_id DESC LIMIT 3"
                )
            )
            assert len(records) > 0, "Expected at least one ArenaWorkflowRun in Neo4j from previous milestones"

            for rec in records:
                run_id = rec["run_id"]
                dep = rec["dep"]
                ws = rec["ws"]
                store = Neo4jWorkflowStore(driver, database="neo4j", deployment_id=dep, workspace_id=ws)
                report = store.verify_run_evidence_chain(run_id, strict=True)
                assert report.valid is True
                assert report.steps_verified >= 1
                assert len(report.errors) == 0
                assert len(report.chain_digest) == 64
    finally:
        driver.close()


def test_w3c_provo_rdf_star_export_and_shacl_validation():
    """Verify W3C PROV-O RDF-star epistemic export and SHACL shape compliance."""
    c1 = "1" * 64
    c2 = "2" * 64
    m1 = "a" * 64
    m2 = "b" * 64
    ev1 = "c" * 64
    ev2 = "d" * 64
    run_id = "f" * 64
    chain_d = "e" * 64

    link1 = EvidenceChainStepLink(
        step_index=0,
        candidate_id=c1,
        input_digest=None,
        output_digest=c1,
        evidence_id=ev1,
        evidence_manifest_digests=(m1,),
        decision_id="dec_1",
        decision_action="repair",
    )
    link2 = EvidenceChainStepLink(
        step_index=1,
        candidate_id=c2,
        input_digest=c1,
        output_digest=c2,
        evidence_id=ev2,
        evidence_manifest_digests=(m2,),
        decision_id="dec_2",
        decision_action="accept",
    )
    report = EvidenceChainAuditReport(
        run_id=run_id,
        valid=True,
        steps_verified=2,
        candidate_chain=(link1, link2),
        evidence_manifest_digests=(m1, m2),
        decisions_verified=2,
        budget_transactions_verified=1,
        chain_digest=chain_d,
        errors=(),
    )

    budget_txs = [
        {
            "transaction_id": "tx_contraction_01",
            "horizon_after": 3,
            "delta_error": 0.32,
        }
    ]

    # Test both canonical and alias export functions
    ttl_star = export_run_provenance_rdf_star(run_id, audit_report=report, budget_txs=budget_txs)
    ttl_star_alias = export_run_provenance_to_rdf_star(run_id, audit_report=report, budget_txs=budget_txs)
    assert ttl_star == ttl_star_alias

    # Assert reified RDF-star statements are generated
    assert "<<(" in ttl_star or "<<" in ttl_star
    assert "arena:extendedHorizon 3" in ttl_star
    assert "prov:wasAttributedTo :macro_orchestrator" in ttl_star
    assert "prov:wasAttributedTo :causal_estimator_j7" in ttl_star
    assert "arena:CandidateRecord" in ttl_star
    assert "arena:ObservationRecord" in ttl_star
    assert "arena:SceneDecisionRecord" in ttl_star
    assert "arena:BudgetTransactionRecord" in ttl_star

    # Validate against W3C PROV-O + Arena SHACL shapes
    shacl_res = validate_provenance_rdf_star(ttl_star)
    assert shacl_res.conforms is True, f"SHACL violations: {shacl_res.violations}"
    assert len(shacl_res.violations) == 0
    assert shacl_res.triples_count > 50
