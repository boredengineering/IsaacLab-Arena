# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Deterministic synthetic scene traces; not native physics or SDK acceptance."""
import copy


def scene_contract():
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import WorkflowContract
    from isaaclab_arena.tests.test_environment_workflow_evidence import frozen_contract
    from isaaclab_arena.tests.test_environment_workflow_repairs import repair_contract

    raw = frozen_contract().model_dump(mode="python")
    raw["allowed_interventions"] = repair_contract().model_dump(mode="python")["allowed_interventions"]
    raw["budget"].update(
        max_candidates=3,
        max_revisions=2,
        max_realizations=4,
        max_observations=4,
        max_model_calls=10,
        max_model_tokens=10000,
        max_steps=100,
    )
    raw["effects"]["allow_operational_writes"] = True
    return WorkflowContract.model_validate(raw)


def observation(contract, candidate, tag, *, fail=False):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.evidence import CriterionEvidence, EvidenceCohort
    from isaaclab_arena.agentic_environment_generation.workflow.evidence_contracts import project_required_criteria
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import Observation, profile_digest

    cohort = EvidenceCohort(
        realization_id=tag,
        reset_id=tag,
        environment_id="env",
        window_id="0-10",
        frame_id="world",
        contract_digest=contract_digest(contract),
        profile_digest=profile_digest(contract),
    )
    records = tuple(
        CriterionEvidence(
            criterion_id=r.criterion_id,
            criterion_digest=r.criterion_digest,
            producer_id=r.producer_id,
            observed_coordinate_frames=r.coordinate_frames,
            observed_step_window=r.step_window,
            subject_ids=r.subject_ids,
            modality=r.modality,
            evaluator_version=r.evaluator_version,
            rubric_id=r.rubric_id,
            candidate_digest=candidate.digest,
            cohort=cohort,
            manifest_digest="d" * 64,
            verdict="violated" if fail and r.modality == "visual" else "established",
        )
        for r in project_required_criteria(contract)
    )
    return Observation(cohort=cohort, evidence=records, verified_manifest_digests=("d" * 64,))


def read_model_records() -> dict:
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.tests.test_environment_workflow_repairs import scene

    contract = scene_contract()
    candidate = scene_loop.candidate_record("run", scene(), source_id="generation")
    old = observation(contract, candidate, "old", fail=True)
    old = old.model_copy(
        update={"evidence": (old.evidence[0].model_copy(update={"verdict": "inconclusive"}), *old.evidence[1:])}
    )
    assert scene_loop.assess_and_route(contract, candidate, old).action == "observe"
    current = observation(contract, candidate, "current")
    current = current.model_copy(
        update={
            "evidence": tuple(e.model_copy(update={"manifest_digest": "e" * 64}) for e in current.evidence),
            "verified_manifest_digests": ("e" * 64,),
        }
    )
    decision = scene_loop.assess_and_route(contract, candidate, current)
    assert decision.action == "accept"
    run = SimpleNamespace(
        contract_json=canonical_json(contract),
        state="accepted",
        run_id="run",
        operation_id="operation",
        phase="scene",
        version=10,
        event_cursor=10,
    )
    records = dict(
        run=run,
        scene=SimpleNamespace(candidate=candidate, intent=None, decision=decision),
        owner=None,
        intents=[],
        admitted_at=100.0,
        selected_evidence_id="current-record",
        evidence=[
            dict(evidence_id=name, candidate_id=candidate.candidate_id, payload=value.model_dump_json())
            for name, value in (("current-record", current), ("old-record", old))
        ],
    )
    return records


def test_read_model_selects_current_decision_cohort_not_all_candidate_history():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.read_model import workflow_result

    records = read_model_records()
    result = workflow_result(SimpleNamespace(result_records=lambda _: records), "run", protect=lambda _: None)
    required = [c for c in result["criteria"] if c["requirement"] == "required"]
    assert all(c["verdict"] == "established" and c["manifests"] == ["e" * 64] for c in required)
    assert len(result["evidence"]) == 2  # Historical diagnostics are retained, not combined into current truth.


def test_read_model_does_not_promote_mismatched_producer_claims_to_passes():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.agentic_environment_generation.workflow.read_model import workflow_result

    records = read_model_records()
    selected = records["evidence"][0]
    current = scene_loop.Observation.model_validate_json(selected["payload"])
    incorrect = current.evidence[0].model_copy(update={"subject_ids": ("foreign",)})
    current = current.model_copy(update={"evidence": (incorrect, *current.evidence[1:])})
    selected["payload"] = current.model_dump_json()
    records["run"].state = "running"
    records["scene"].decision = scene_loop.assess_and_route(scene_contract(), records["scene"].candidate, current)
    assert incorrect.criterion_id in records["scene"].decision.assessment.missing_ids
    result = workflow_result(SimpleNamespace(result_records=lambda _: records), "run", protect=lambda _: None)
    projected = next(c for c in result["criteria"] if c["criterion_id"] == incorrect.criterion_id)
    assert projected["verdict"] == "inconclusive"


def test_deterministic_validation_visual_failure_xy_child_fresh_cohort_acceptance():
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.tests.test_environment_workflow_repairs import scene

    contract = scene_contract()
    original = scene_loop.candidate_record("run", scene(), source_id="generation")
    a = observation(contract, original, "cohort-A", fail=True)
    decision = scene_loop.assess_and_route(contract, original, a)
    assert decision.action == "repair" and decision.reason == "supported_visual_failure"
    proposed = copy.deepcopy(scene())
    proposed["relations"][2]["params"]["x"] = 0.03
    child = scene_loop.repaired_candidate(contract, original, original, proposed, source_id="decision-A")
    assert child.original_id == original.candidate_id and child.parent_id == original.candidate_id
    assert child.candidate_id != original.candidate_id
    b = observation(contract, child, "cohort-B")
    decision = scene_loop.assess_and_route(contract, child, b)
    assert decision.action == "accept" and decision.assessment.status == "established"
    assert original.scene_json != child.scene_json


def test_visual_defect_without_required_physical_preconditions_observes():
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.tests.test_environment_workflow_repairs import scene

    contract = scene_contract()
    candidate = scene_loop.candidate_record("run", scene(), source_id="generation")
    evidence = observation(contract, candidate, "A", fail=True)
    evidence = evidence.model_copy(update={"evidence": tuple(r for r in evidence.evidence if r.modality != "measured")})
    assert scene_loop.assess_and_route(contract, candidate, evidence).action == "observe"


def test_conflicting_visual_verdicts_observe_instead_of_repair():
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.tests.test_environment_workflow_repairs import scene

    contract = scene_contract()
    candidate = scene_loop.candidate_record("run", scene(), source_id="generation")
    sample = observation(contract, candidate, "A", fail=True)
    visual = next(r for r in sample.evidence if r.modality == "visual")
    sample = sample.model_copy(
        update={"evidence": sample.evidence + (visual.model_copy(update={"verdict": "established"}),)}
    )
    assert scene_loop.assess_and_route(contract, candidate, sample).action == "observe"


def test_child_cannot_use_parent_evidence_and_repairs_stay_original_bounded():
    import pytest

    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.tests.test_environment_workflow_repairs import scene

    contract = scene_contract()
    original = scene_loop.candidate_record("run", scene(), source_id="generation")
    value = scene()
    value["relations"][2]["params"]["x"] = 0.08
    child = scene_loop.repaired_candidate(contract, original, original, value, source_id="repair-1")
    stale = observation(contract, original, "A")
    assert scene_loop.assess_and_route(contract, child, stale).action == "observe"
    value["relations"][2]["params"]["x"] = 0.16
    with pytest.raises(ValueError, match="repair_displacement_exceeded"):
        scene_loop.repaired_candidate(contract, original, child, value, source_id="repair-2")


def test_unsupported_policy_window_and_unbounded_port_are_explicit():
    import pytest

    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.tests.test_environment_workflow_repairs import scene

    contract = scene_contract()
    candidate = scene_loop.candidate_record("run", scene(), source_id="generation")
    sample = observation(contract, candidate, "A")
    for case in ("policy", "window"):
        raw = contract.model_dump(mode="python")
        if case == "policy":
            raw["criteria"][0].update(kind="policy", required_modalities=("policy_rollout",))
            raw["execution"]["policy"] = raw["execution"]["runtime"]
            raw["budget"].update(max_policy_episodes=1, max_policy_steps=1)
        else:
            raw["criteria"][0]["observation_window"]["end_step"] = 9
        changed = type(contract).model_validate(raw)
        decision = scene_loop.assess_and_route(changed, candidate, sample)
        assert (decision.action, decision.reason) == ("stop", "unsupported_criterion")
    with pytest.raises(ValueError):
        scene_loop.ScenePortProfile(
            port_id="unbounded-provider", assurance="self_reported_usage", producer_ids=(), observe={}, repair={}
        )
