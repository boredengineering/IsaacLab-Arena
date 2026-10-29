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


def observation(contract, candidate, tag, *, fail=False, include_policy=False):
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
        for r in project_required_criteria(contract, **({"include_policy": True} if include_policy else {}))
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


def test_v1_scene_codecs_preserve_original_serialized_shape():
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop

    reservation = dict(
        model_calls=1,
        model_tokens=10,
        cost_ceiling_usd=0.0,
        runtime_allowance_seconds=1.0,
        candidates=0,
        revisions=0,
        realizations=0,
        steps=0,
        observations=0,
    )
    old_profile = dict(
        port_id="legacy",
        assurance="synthetic",
        owned_worker=False,
        producer_ids=[],
        observe=reservation,
        repair=reservation,
    )
    old_intent = dict(
        intent_id="a" * 64,
        candidate_id="b" * 64,
        action="observe",
        status="reserved",
        reservation=reservation,
        released_at=None,
        worker_fence=None,
        worker_registration=None,
        worker_cleanup=None,
    )
    old_result = dict(observation=None, candidate_json=None, failure="invalid_candidate")
    for cls, record in (
        (scene_loop.ScenePortProfile, old_profile),
        (scene_loop.SceneIntent, old_intent),
        (scene_loop.SceneResult, old_result),
    ):
        value = cls.model_validate(record)
        assert value.codec_version == 1
        assert value.model_dump(mode="json") == record


def test_split_unassessed_capture_is_not_promoted_by_legacy_read_model():
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.agentic_environment_generation.workflow.read_model import workflow_result
    from types import SimpleNamespace

    records = read_model_records()
    records["run"].state = "running"
    records["scene"].decision = scene_loop.SceneDecision(action="assess", reason="capture_verified")
    result = workflow_result(SimpleNamespace(result_records=lambda _: records), "run", protect=lambda _: None)
    assert all(c["verdict"] == "not_run" for c in result["criteria"])
    assert result["scene_acceptance"] == "not_established"


def test_split_capture_binding_and_static_failure_precede_assessment():
    import pytest

    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.tests.test_environment_workflow_repairs import scene

    contract = scene_contract()
    candidate = scene_loop.candidate_record("run", scene(), source_id="generation")
    value = observation(contract, candidate, "capture")
    value = value.model_copy(update={"evidence": tuple(e for e in value.evidence if e.modality != "visual")})
    assert scene_loop.route_capture(contract, candidate, value).action == "assess"
    failed = value.model_copy(update={"static_failure": "ineffective_edit"})
    decision = scene_loop.route_capture(contract, candidate, failed)
    assert decision.action == "stop" and decision.reason == "ineffective_edit" and decision.assessment is None
    changes = [
        {"cohort": value.cohort.model_copy(update={"contract_digest": "e" * 64})},
        {"cohort": value.cohort.model_copy(update={"profile_digest": "e" * 64})},
        {"evidence": (value.evidence[0].model_copy(update={"candidate_digest": "e" * 64}),)},
        {"verified_manifest_digests": ()},
        {"evidence": observation(contract, candidate, "capture").evidence},
    ]
    for change in changes:
        with pytest.raises(ValueError, match="capture binding"):
            scene_loop.route_capture(contract, candidate, value.model_copy(update=change))


def test_split_profile_separates_capture_and_assessment_budget_and_version():
    import pytest

    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop

    capture = dict(
        model_calls=0,
        model_tokens=0,
        cost_ceiling_usd=0.0,
        runtime_allowance_seconds=1.0,
        realizations=1,
        observations=1,
        steps=10,
    )
    assess = dict(model_calls=1, model_tokens=100, cost_ceiling_usd=0.1, runtime_allowance_seconds=2.0)
    raw = dict(
        codec_version=2,
        port_id="split",
        assurance="native-unverified",
        owned_worker=True,
        producer_ids=["capture"],
        capture=capture,
        assess=assess,
        repair=assess,
    )
    profile = scene_loop.ScenePortProfile.model_validate(raw)
    assert profile.codec_version == 2 and profile.model_dump()["codec_version"] == 2
    for field in ("model_calls", "model_tokens", "cost_ceiling_usd", "candidates", "revisions"):
        bad = copy.deepcopy(raw)
        bad["capture"][field] = 1
        with pytest.raises(ValueError, match="capture cannot reserve"):
            scene_loop.ScenePortProfile.model_validate(bad)
    for field in ("realizations", "steps", "observations", "candidates", "revisions"):
        bad = copy.deepcopy(raw)
        bad["assess"][field] = 1
        with pytest.raises(ValueError, match="assessment cannot reserve"):
            scene_loop.ScenePortProfile.model_validate(bad)
    for change in ({"codec_version": 1}, {"owned_worker": False}, {"observe": capture}, {"assess": None}):
        with pytest.raises(ValueError):
            scene_loop.ScenePortProfile.model_validate(dict(raw, **change))
    intent = dict(
        codec_version=2,
        intent_id="a" * 64,
        candidate_id="b" * 64,
        action="assess",
        status="reserved",
        reservation=assess,
        observation_id="c" * 64,
        observation_digest="d" * 64,
    )
    assert scene_loop.SceneIntent.model_validate(intent).codec_version == 2
    for change in ({"codec_version": 1}, {"observation_id": None}, {"observation_digest": None}, {"action": "capture"}):
        with pytest.raises(ValueError):
            scene_loop.SceneIntent.model_validate(dict(intent, **change))


def required_policy_contract():
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import WorkflowContract

    raw = scene_contract().model_dump(mode="python")
    criterion = dict(raw["criteria"][-1])
    criterion.update(
        criterion_id="task-success",
        kind="policy",
        required_modalities=("policy_rollout",),
        evidence_producer="task-evaluator",
        evaluator_version="v1",
        rubric="completed episode task success rate",
        coordinate_frames=("episode",),
        subjects=("task",),
        limit={"operator": "ge", "value": 1.0, "unit": "fraction"},
    )
    raw["criteria"] = (*raw["criteria"], criterion)
    raw["execution"]["policy"] = dict(raw["execution"]["runtime"])
    raw["budget"].update(max_policy_episodes=2, max_policy_steps=10)
    return WorkflowContract.model_validate(raw)


def test_policy_capability_requires_exact_supported_criterion_aggregation_mapping():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
    from isaaclab_arena.tests.test_environment_workflow_evidence import policy_binding

    contract = required_policy_contract()
    binding = policy_binding(contract_digest=contract_digest(contract), seed=contract.execution.seed)
    criteria = tuple(c for c in contract.criteria if c.kind == "policy")
    profile = SimpleNamespace(
        codec_version=2,
        policy_binding=binding,
        policy_criteria=tuple(scene_loop.identity(c.model_dump(mode="json")) for c in criteria),
    )
    assert scene_loop.policy_compatible(contract, profile)
    profile.policy_binding = binding.model_copy(update={"minimum_successes": 1})
    assert not scene_loop.policy_compatible(contract, profile), "one success cannot satisfy required rate 1.0 of two"
    changed = contract.model_copy(
        update={
            "criteria": (
                *contract.criteria[:-1],
                criteria[0].model_copy(update={"rubric": "unregistered task predicate"}),
            )
        }
    )
    profile.policy_binding = binding.model_copy(update={"contract_digest": contract_digest(changed)})
    profile.policy_criteria = (scene_loop.identity(changed.criteria[-1].model_dump(mode="json")),)
    assert not scene_loop.policy_compatible(changed, profile), "matching hashes do not validate semantics"


def required_policy_profile(profile, contract, candidate, *, task="a2"):
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
    from isaaclab_arena.tests.test_environment_workflow_evidence import policy_binding

    assert "policy" in scene_loop.ScenePortProfile.model_fields, "v2 required-policy capability missing"
    binding = policy_binding(
        candidate_digest=candidate.digest,
        contract_digest=contract_digest(contract),
        seed=contract.execution.seed,
        deadline_unix=150.0,
        max_prerequisite_steps=2,
        max_policy_steps=contract.budget.max_policy_steps,
        embodiment_id="droid_abs_joint_pos" if task == "a2" else "g1",
        task_id="pick-and-place" if task == "a2" else "navigation",
        evaluator_id="lift-before-place" if task == "a2" else "goal-arrival",
        task_definition_digest=(
            scene_loop.identity(
                "banana_ycb_robolab",
                "plate_large_vomp_robolab",
                "lift-before-place",
                "airborne-dwell",
                "destination-contact-velocity-proximity",
            )
            if task == "a2"
            else scene_loop.identity("navigation", "goal-region", "distance-threshold")
        ),
        instruction=(
            "Grasp the yellow banana from the right side of the table and set it onto the white ceramic plate on the"
            " left."
            if task == "a2"
            else "Walk to the marked goal region."
        ),
    )
    return scene_loop.ScenePortProfile.model_validate(
        dict(
            profile.model_dump(),
            policy=scene_loop.SceneReservation(
                model_calls=0,
                model_tokens=0,
                cost_ceiling_usd=0.0,
                runtime_allowance_seconds=1.0,
                realizations=1,
                steps=2,
                policy_steps=binding.max_policy_steps,
                policy_episodes=2,
            ),
            policy_binding=binding,
            policy_criteria=tuple(
                scene_loop.identity(c.model_dump(mode="json"))
                for c in contract.criteria
                if c.requirement == "required" and c.kind == "policy"
            ),
        )
    )
