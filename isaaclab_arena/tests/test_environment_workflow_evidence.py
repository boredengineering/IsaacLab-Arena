# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Pure metadata tests: synthetic digests are NOT physical evidence or byte verification."""

import pytest
from pydantic import ValidationError


def api():
    from isaaclab_arena.agentic_environment_generation.workflow import evidence

    return evidence


def binding(**updates):
    return api().CandidateBinding(
        **(
            dict(
                candidate_digest="a" * 64,
                contract_digest="b" * 64,
                profile_digest="c" * 64,
            )
            | updates
        )
    )


def cohort(**updates):
    return api().EvidenceCohort(**(
        dict(
            realization_id="realization",
            reset_id="reset-1",
            environment_id="env-0",
            window_id="steps-0-10",
            frame_id="world",
            contract_digest="b" * 64,
            profile_digest="c" * 64,
        )
        | updates
    ))


def requirement(criterion_id="support", **updates):
    return api().CriterionRequirement(**(
        dict(
            criterion_digest="f" * 64,
            producer_id="contact-producer",
            coordinate_frames=("world",),
            step_window=(0, 10),
            criterion_id=criterion_id,
            subject_ids=("cup", "table"),
            modality="measured",
            evaluator_version="contact-v1",
            rubric_id="support-v1",
        )
        | updates
    ))


def receipt(criterion_id="support", **updates):
    return api().CriterionEvidence(**(
        dict(
            criterion_digest="f" * 64,
            producer_id="contact-producer",
            observed_coordinate_frames=("world",),
            observed_step_window=(0, 10),
            criterion_id=criterion_id,
            subject_ids=("cup", "table"),
            modality="measured",
            evaluator_version="contact-v1",
            rubric_id="support-v1",
            candidate_digest="a" * 64,
            cohort=cohort(),
            manifest_digest="d" * 64,
            verdict="established",
            limitations=(),
        )
        | updates
    ))


def assess(required, evidence, **updates):
    return api().assess_scene_evidence(
        required,
        binding(),
        evidence,
        updates.get("verified_manifest_digests", frozenset({"d" * 64})),
        selected_cohort=updates.get("selected_cohort", cohort()),
    )


def projection_api():
    from isaaclab_arena.agentic_environment_generation.workflow import evidence_contracts

    return evidence_contracts


def frozen_contract():
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import WorkflowContract

    profile = dict(profile_id="offline", settings_sha256="a" * 64)
    criteria = [
        dict(
            criterion_id=kind,
            kind=kind,
            evidence_producer=f"{kind}-producer",
            requirement="required",
            evaluator_version="1",
            required_modalities=(modality,),
            coordinate_frames=frames,
            observation_window=dict(start_step=0, end_step=10),
            rubric="Producer must evaluate the explicit numeric limit.",
            subjects=("cup", "table"),
            limit=dict(operator="ge", value=1.0, unit="count"),
        )
        for kind, modality, frames in (
            ("structural", "scene_graph", ("world",)),
            ("geometry", "state", ("world", "table-local")),
            ("runtime", "state", ("world",)),
            ("visual", "rgb", ("camera-front", "camera-top")),
        )
    ]
    return WorkflowContract.model_validate(
        dict(
            schema_version="1",
            source=dict(kind="new", prompt="Tabletop"),
            criteria=criteria,
            preserved=(),
            allowed_interventions=(),
            execution=dict(
                generation_model=profile | dict(billing="free"),
                assessment_model=profile | dict(billing="free"),
                runtime=profile,
                database=profile,
                policy=None,
                capture=profile,
                seed=42,
                timestep_seconds=0.01,
                decimation=2,
                dcrg=None,
            ),
            budget=dict(
                max_candidates=1,
                max_revisions=0,
                max_runtime_seconds=60.0,
                max_model_calls=0,
                max_model_tokens=0,
                max_cost_usd=0.0,
                max_realizations=1,
                max_steps=10,
                max_observations=10,
                max_policy_episodes=0,
                max_policy_steps=0,
                per_operation_timeout_seconds=10.0,
                total_deadline_seconds=60.0,
            ),
            effects=dict(
                allow_paid_models=False, allow_runtime=True, allow_database_reads=False, allow_publication=False
            ),
        )
    )


def projected_receipt(req, **updates):
    return receipt(
        req.criterion_id,
        **(
            dict(
                subject_ids=req.subject_ids,
                modality=req.modality,
                evaluator_version=req.evaluator_version,
                rubric_id=req.rubric_id,
                criterion_digest=req.criterion_digest,
                producer_id=req.producer_id,
                observed_coordinate_frames=req.coordinate_frames,
                observed_step_window=req.step_window,
            )
            | updates
        ),
    )


def test_full_frozen_contract_projection_establishes_distinct_frames_in_one_scene():
    import hashlib
    import json

    contract = frozen_contract()
    required = projection_api().project_required_criteria(contract)
    assert len(required) == 4
    for criterion, req in zip(contract.criteria, required):
        expected = hashlib.sha256(
            json.dumps(
                criterion.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        assert req.criterion_digest == expected
        assert req.producer_id == criterion.evidence_producer
        assert req.coordinate_frames == criterion.coordinate_frames
        assert req.step_window == (0, 10)
        assert not req.state_independent
    assert assess(required, tuple(projected_receipt(req) for req in required)).status == "established"


@pytest.mark.parametrize(
    "updates",
    [
        {"criterion_digest": "e" * 64},
        {"producer_id": "wrong"},
        {"observed_coordinate_frames": ("camera-front",)},
        {"observed_coordinate_frames": ("camera-front", "camera-top", "extra")},
        {"observed_coordinate_frames": ("world",)},
        {"observed_step_window": (1, 10)},
        {"observed_step_window": (0, 9)},
        {"modality": "measured"},
    ],
)
def test_frozen_requirement_not_receipt_agreement_binds_observations(updates):
    required = projection_api().project_required_criteria(frozen_contract())[-1:]
    record = projected_receipt(required[0], **updates)
    assert assess(required, (record, record)).status == "inconclusive"


@pytest.mark.parametrize(
    "field,value",
    [
        ("limit", dict(operator="ge", value=2.0, unit="count")),
        ("limit", dict(operator="le", value=1.0, unit="count")),
        ("limit", dict(operator="ge", value=1.0, unit="m")),
        ("rubric", "A different interpretation of the same numeric limit."),
    ],
)
def test_changed_limit_or_rubric_cannot_reuse_old_digest(field, value):
    contract = frozen_contract()
    old = projection_api().project_required_criteria(contract)[0]
    raw = contract.model_dump(mode="python")
    raw["criteria"][0][field] = value
    changed = type(contract).model_validate(raw)
    new = projection_api().project_required_criteria(changed)[0]
    assert old.criterion_digest != new.criterion_digest
    # Isolate digest matching from the legacy rubric identity comparison.
    record = projected_receipt(new, criterion_digest=old.criterion_digest)
    assert assess((new,), (record,)).status == "inconclusive"


def test_observed_frames_are_exact_unordered_sets_and_not_cameras_in_cohort():
    req = projection_api().project_required_criteria(frozen_contract())[-1]
    record = projected_receipt(req, observed_coordinate_frames=tuple(reversed(req.coordinate_frames)))
    assert record.cohort.frame_id == "world"
    assert assess((req,), (record,)).status == "established"


@pytest.mark.parametrize(
    "kind,modalities",
    [
        ("structural", ("rgb",)),
        ("geometry", ("scene_graph",)),
        ("runtime", ("depth",)),
        ("visual", ("state",)),
        ("visual", ("rgb", "depth")),
        ("visual", ("rgb", "rgb")),
        ("policy", ("policy_rollout",)),
    ],
)
def test_unsupported_projection_fails_before_assessment(kind, modalities):
    contract = frozen_contract()
    raw = contract.model_dump(mode="python")
    raw["criteria"][0].update(kind=kind, required_modalities=modalities)
    if kind == "policy":
        raw["execution"]["policy"] = raw["execution"]["runtime"]
        raw["budget"].update(max_policy_episodes=1, max_policy_steps=1)
    valid_contract = type(contract).model_validate(raw)
    with pytest.raises(ValueError, match="unsupported"):
        projection_api().project_required_criteria(valid_contract)


def test_advisory_is_excluded_even_with_unsupported_modality_and_no_required_rejected():
    contract = frozen_contract()
    raw = contract.model_dump(mode="python")
    raw["criteria"][0].update(requirement="advisory", required_modalities=("depth",))
    required = projection_api().project_required_criteria(type(contract).model_validate(raw))
    assert tuple(r.criterion_id for r in required) == ("geometry", "runtime", "visual")
    for criterion in raw["criteria"]:
        criterion["requirement"] = "advisory"
    with pytest.raises(ValueError, match="required"):
        projection_api().project_required_criteria(type(contract).model_validate(raw))


def test_projection_rejects_different_windows_instead_of_hiding_them_in_window_id():
    contract = frozen_contract()
    raw = contract.model_dump(mode="python")
    raw["criteria"][0]["observation_window"]["end_step"] = 9
    with pytest.raises(ValueError, match="window"):
        projection_api().project_required_criteria(type(contract).model_validate(raw))


@pytest.mark.parametrize("count", [128, 129])
def test_projection_enforces_assessor_required_criterion_bound(count):
    contract = frozen_contract()
    raw = contract.model_dump(mode="python")
    template = raw["criteria"][0]
    raw["criteria"] = tuple({**template, "criterion_id": f"criterion-{index}"} for index in range(count))
    bounded_contract = type(contract).model_validate(raw)
    if count == 128:
        assert len(projection_api().project_required_criteria(bounded_contract)) == count
    else:
        with pytest.raises(ValueError, match="unsupported.*count"):
            projection_api().project_required_criteria(bounded_contract)


@pytest.mark.parametrize(
    "factory,field",
    [
        (requirement, "criterion_digest"),
        (requirement, "producer_id"),
        (requirement, "coordinate_frames"),
        (requirement, "step_window"),
        (receipt, "criterion_digest"),
        (receipt, "producer_id"),
        (receipt, "observed_coordinate_frames"),
        (receipt, "observed_step_window"),
    ],
)
def test_frozen_binding_fields_are_mandatory(factory, field):
    instance = factory()
    raw = instance.model_dump()
    del raw[field]
    with pytest.raises(ValidationError):
        type(instance).model_validate(raw)


@pytest.mark.parametrize("window", [(10, 0), (-1, 0), (False, 10), (0, 1.0), (0,), (0, 1, 2)])
def test_observation_windows_are_exact_ordered_strict_pairs(window):
    with pytest.raises(ValidationError):
        requirement(step_window=window)
    with pytest.raises(ValidationError):
        receipt(observed_step_window=window)


def test_complete_cohort_positive_is_immutable():
    result = assess((requirement(), requirement("clearance")), (receipt(), receipt("clearance")))
    assert result.status == "established"
    assert result.missing_ids == result.failed_ids == ()
    with pytest.raises(ValidationError):
        result.status = "inconclusive"


@pytest.mark.parametrize("field", ["realization_id", "reset_id", "environment_id", "window_id", "frame_id"])
def test_complementary_cohorts_never_stitch(field):
    result = assess(
        (requirement(), requirement("clearance")),
        (receipt(), receipt("clearance", cohort=cohort(**{field: "other"}))),
    )
    assert result.status == "inconclusive"
    assert result.missing_ids == ("clearance",)


@pytest.mark.parametrize(
    "updates",
    [
        {"candidate_digest": "e" * 64},
        {"cohort": {"profile_digest": "e" * 64}},
        {"cohort": {"contract_digest": "e" * 64}},
        {"subject_ids": ("other",)},
        {"evaluator_version": "other"},
        {"rubric_id": "other"},
        {"modality": "visual"},
        {"manifest_digest": "e" * 64},
        {"verdict": "inconclusive"},
        {"verdict": "not_run"},
    ],
)
def test_incompatible_or_unverified_receipt_cannot_establish(updates):
    if "cohort" in updates:
        updates = updates | {"cohort": cohort(**updates["cohort"])}
    result = assess((requirement(),), (receipt(**updates),))
    assert result.status == "inconclusive" and result.missing_ids == ("support",)


def test_verification_is_explicit_and_empty_evidence_is_not_success():
    assert assess((requirement(),), (receipt(),), verified_manifest_digests=frozenset()).status == "inconclusive"
    assert assess((requirement(),), ()).missing_ids == ("support",)


def test_failure_survives_other_cohort_pass_and_duplicate_conflict():
    failed = receipt(verdict="violated")
    other = receipt(cohort=cohort(reset_id="reset-2"))
    for receipts in (
        (failed,),
        (failed, other),
        (receipt(), failed),
        (failed, receipt()),
    ):
        result = assess((requirement(),), receipts)
        assert result.status == "not_established" and result.failed_ids == ("support",)
    assert "ambiguous_receipts" in assess((requirement(),), (receipt(), failed)).limitations


def test_historical_failure_does_not_veto_complete_current_scene():
    result = assess(
        (requirement(),),
        (receipt(cohort=cohort(reset_id="old"), verdict="violated"), receipt()),
    )
    assert result.status == "established"
    assert result.failed_ids == ("support",)
    assert "historical_failure" in result.limitations


def test_historical_conflict_is_diagnostic_not_a_veto():
    old = cohort(reset_id="old")
    result = assess(
        (requirement(),),
        (receipt(cohort=old), receipt(cohort=old, verdict="violated"), receipt()),
    )
    assert result.status == "established"
    assert result.failed_ids == ("support",)
    assert result.historical_conflict_ids == ("support",)
    assert "historical_conflict" in result.limitations


def test_explicit_selection_never_chooses_another_complete_cohort():
    result = assess(
        (requirement(), requirement("clearance")),
        (receipt(), receipt("clearance"), receipt(cohort=cohort(reset_id="partial"))),
        selected_cohort=cohort(reset_id="partial"),
    )
    assert result.status == "inconclusive"
    assert result.missing_ids == ("clearance",)


@pytest.mark.parametrize("field", ["contract_digest", "profile_digest"])
def test_selection_must_match_candidate_binding(field):
    with pytest.raises(ValueError, match="selected cohort"):
        assess((requirement(),), (receipt(),), selected_cohort=cohort(**{field: "e" * 64}))


def test_selection_is_mandatory():
    with pytest.raises(TypeError, match="selected_cohort"):
        api().assess_scene_evidence((requirement(),), binding(), (receipt(),), frozenset({"d" * 64}))


def test_selected_contradiction_blocks_despite_complete_other_cohort():
    result = assess(
        (requirement(),),
        (receipt(), receipt(verdict="violated"), receipt(cohort=cohort(reset_id="other"))),
    )
    assert result.status == "not_established"
    assert "ambiguous_receipts" in result.limitations


def test_identical_duplicate_is_idempotent_but_uncertain_duplicate_blocks():
    assert assess((requirement(),), (receipt(), receipt())).status == "established"
    assert assess((requirement(),), (receipt(), receipt(verdict="inconclusive"))).status == "inconclusive"


def test_explicit_structural_static_reuse_only():
    reqs = (
        requirement(),
        requirement("asset", modality="structural", state_independent=True),
    )
    records = (
        receipt(),
        receipt("asset", modality="structural", cohort=cohort(reset_id="old")),
    )
    assert assess(reqs, records).status == "established"
    assert assess((reqs[0], requirement("asset", modality="structural")), records).status == "inconclusive"
    for modality in ("measured", "visual"):
        with pytest.raises(ValidationError):
            requirement(modality=modality, state_independent=True)


def test_policy_requirement_is_explicitly_unsupported():
    result = assess((requirement(scope="policy"),), (receipt(),))
    assert result.status == "inconclusive"
    assert "unsupported_policy_requirement" in result.limitations


@pytest.mark.parametrize("value", ["", " ", 1, True, float("nan"), float("inf")])
def test_invalid_identity_and_digest_values(value):
    for factory, field in (
        (binding, "candidate_digest"),
        (cohort, "frame_id"),
        (requirement, "rubric_id"),
        (receipt, "evaluator_version"),
    ):
        with pytest.raises(ValidationError):
            factory(**{field: value})


@pytest.mark.parametrize(
    "field",
    ["subject_ids", "rubric_id", "evaluator_version", "cohort", "manifest_digest"],
)
def test_missing_receipt_identity_rejected(field):
    data = receipt().model_dump()
    del data[field]
    with pytest.raises(ValidationError):
        api().CriterionEvidence.model_validate(data)


def test_free_text_limitations_are_bounded_and_receipts_stay_frozen():
    record = receipt(limitations=("Only metadata was assessed; no physical assertion.",))
    assert record.limitations == ("Only metadata was assessed; no physical assertion.",)
    with pytest.raises(ValidationError):
        record.cohort.frame_id = "other"
    with pytest.raises(ValidationError):
        binding().profile_digest = "e" * 64
    for limitations in ((" ",), ("x" * 1025,), ("x",) * 129, ["mutable"]):
        with pytest.raises(ValidationError):
            receipt(limitations=limitations)


def test_bounded_strict_inputs_and_revalidation():
    for subjects in ((), ("cup", "cup"), ("x",) * 129, (True,)):
        with pytest.raises(ValidationError):
            receipt(subject_ids=subjects)
    with pytest.raises(ValidationError):
        requirement(state_independent=1)
    with pytest.raises(ValidationError):
        cohort(frame_id="x" * 257)
    with pytest.raises(ValueError):
        assess((), ())
    with pytest.raises(ValueError):
        assess((requirement(), requirement()), (receipt(),))
    with pytest.raises((ValueError, TypeError)):
        assess((requirement(),), (receipt(),), verified_manifest_digests={"d" * 64})
    with pytest.raises(ValidationError):
        assess((requirement(),), (receipt().model_copy(update={"candidate_digest": True}),))


def test_policy_contract_types_live_in_pure_module():
    from isaaclab_arena.agentic_environment_generation.workflow import policy_contracts as pe

    assert pe.PolicyTaskBinding.__module__.endswith(".policy_contracts")
    assert pe.PolicyEpisode.__module__.endswith(".policy_contracts")
    assert pe.PolicyCohortReadiness.__module__.endswith(".policy_contracts")


def policy_binding(**updates):
    from isaaclab_arena.agentic_environment_generation.workflow import policy_contracts as pe

    return pe.PolicyTaskBinding(**(
        dict(
            candidate_digest="a" * 64,
            contract_digest="b" * 64,
            policy_artifact_digest="c" * 64,
            policy_config_digest="d" * 64,
            observation_interface_digest="e" * 64,
            action_interface_digest="f" * 64,
            transport_digest="1" * 64,
            task_definition_digest="2" * 64,
            evaluator_digest="3" * 64,
            runtime_digest="4" * 64,
            embodiment_id="test-droid",
            policy_adapter_id="test-policy-v1",
            task_id="pick-place",
            evaluator_id="task-v1",
            instruction="Move the object",
            environment_id="env-0",
            realization_id="realization-1",
            reset_id="reset-1",
            seed=7,
            max_policy_steps=10,
            max_episodes=2,
            deadline_unix=1000.0,
            minimum_successes=2,
            max_prerequisite_steps=6,
        )
        | updates
    ))


def test_policy_aggregation_is_frozen_task_bound_and_empty_is_unknown():
    from isaaclab_arena.agentic_environment_generation.workflow import policy_contracts as pe

    frozen = policy_binding()
    with pytest.raises(ValidationError):
        frozen.task_id = "changed"
    empty = pe.aggregate_policy_episodes(frozen, ())
    assert (empty.completed, empty.successes, empty.success_rate, empty.outcome) == (0, 0, None, "unknown")
    records = tuple(
        pe.PolicyEpisode(
            binding_digest=frozen.digest(),
            episode_id=f"episode-{index}",
            reset_id=f"reset-{index}",
            seed=7,
            success=success,
        )
        for index, success in enumerate((True, False))
    )
    result = pe.aggregate_policy_episodes(frozen, records)
    assert (result.completed, result.successes, result.success_rate, result.outcome) == (2, 1, 0.5, "failed")


def test_policy_receipt_coverage_is_bounded_before_execution():
    from isaaclab_arena.agentic_environment_generation.workflow.policy_contracts import (
        PolicyEpisode,
        PolicyTrialReceipt,
    )

    with pytest.raises(ValueError):
        policy_binding(max_episodes=513)
    binding = policy_binding(max_episodes=512, max_policy_steps=512)
    receipt = PolicyTrialReceipt(
        intent_id="1" * 64,
        episode_records_digest="2" * 64,
        manifest_digest="3" * 64,
        binding=binding,
        policy_steps=512,
        prerequisite_steps=0,
        episodes=tuple(
            PolicyEpisode(
                binding_digest=binding.digest(),
                episode_id=f"{i:0128d}",
                reset_id=binding.reset_id if i == 0 else f"{i:0128d}",
                seed=binding.seed,
                success=True,
            )
            for i in range(512)
        ),
    )
    assert len(receipt.model_dump_json().encode()) < 512 * 1024


@pytest.mark.parametrize("corruption", ["binding", "seed", "duplicate", "reset", "overflow", "forged", "mutable"])
def test_policy_aggregation_rejects_mixed_or_unbounded_evidence(corruption):
    from isaaclab_arena.agentic_environment_generation.workflow import policy_contracts as pe

    frozen = policy_binding()
    record = pe.PolicyEpisode(binding_digest=frozen.digest(), episode_id="e1", reset_id="r1", seed=7, success=True)
    records = (record,)
    if corruption == "binding":
        records = (record.model_copy(update={"binding_digest": "f" * 64}),)
    elif corruption == "seed":
        records = (record.model_copy(update={"seed": 8}),)
    elif corruption == "duplicate":
        records = (record, record)
    elif corruption == "reset":
        records = (record, record.model_copy(update={"episode_id": "e2"}))
    elif corruption == "overflow":
        records = tuple(record.model_copy(update={"episode_id": f"e{i}", "reset_id": f"r{i}"}) for i in range(3))
    elif corruption == "forged":
        records = (record.model_copy(update={"success": 1}),)
    else:
        records = [record]
    with pytest.raises((ValueError, TypeError)):
        pe.aggregate_policy_episodes(frozen, records)


def test_policy_aggregation_unknowns_and_distinct_task_profiles():
    from isaaclab_arena.agentic_environment_generation.workflow import policy_contracts as pe

    for task, embodiment, evaluator in (("pick-place", "droid", "lift-place-v1"), ("navigate", "g1", "goal-v1")):
        frozen = policy_binding(task_id=task, embodiment_id=embodiment, evaluator_id=evaluator)
        records = tuple(
            pe.PolicyEpisode(binding_digest=frozen.digest(), episode_id=f"e{i}", reset_id=f"r{i}", seed=7, success=True)
            for i in range(2)
        )
        assert pe.aggregate_policy_episodes(frozen, records).outcome == "passed"
        partial = pe.aggregate_policy_episodes(frozen, records[:1])
        assert partial.outcome == "unknown" and partial.success_rate == 1.0
        unknown = records[1].model_copy(update={"success": None})
        result = pe.aggregate_policy_episodes(frozen, (records[0], unknown))
        assert result.outcome == "unknown" and result.success_rate is None
    with pytest.raises(ValidationError):
        policy_binding(minimum_successes=3)


@pytest.mark.parametrize(
    "required,established,status,terminal",
    [
        (True, True, "ready_for_policy", False),
        (False, True, "accepted", True),
        (True, False, "blocked", False),
        (False, False, "blocked", False),
    ],
)
def test_policy_prerequisite_readiness_is_nonterminal(required, established, status, terminal):
    from isaaclab_arena.agentic_environment_generation.workflow import policy_contracts as pe

    result = pe.policy_prerequisite_readiness(required_policy=required, prerequisites_established=established)
    assert result.status == status and result.terminal is terminal
    assert result.reserve_policy is (required and established)
    with pytest.raises((TypeError, ValueError)):
        pe.policy_prerequisite_readiness(required_policy=1, prerequisites_established=established)
