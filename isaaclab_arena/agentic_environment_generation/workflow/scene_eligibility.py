# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Evidence-bound scientific eligibility, never authority, release, or physical proof.

G2 must supply measured root-mapping premises in the acquisition, retain decisions
and consume their exact identities at reservation/release/recovery/refiner boundaries.
No mapping, contact, occlusion, calibration or IK fact is inferred from visibility.
"""

import hashlib
import json
from math import hypot
from typing import Annotated, Any, Literal

from pydantic import Field

from .contracts import (
    AcquisitionSchedule,
    Amount,
    Count,
    FrozenModel,
    Hash,
    Identifier,
    PoseErrorParameters,
    Text,
    contract_digest,
    parse_contract,
)
from .evidence import CandidateBinding, CriterionEvidence, EvidenceCohort, assess_scene_evidence
from .evidence_contracts import project_required_criteria
from .repairs import (
    _scene_json,
    resolve_repair_selection,
    validate_permitted_scene_repair,
    validate_selected_scene_repair,
)
from .scene_evidence_artifacts import assessment_identity, canonical
from .scene_loop import CandidateRecord, profile_digest
from .scene_observation import _bound_payload, _compare_limit, evaluate_measurement, evaluate_visual_answer

Coordinate = Annotated[float, Field(strict=True, allow_inf_nan=False)]


def _digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class RootXYMappingPremise(FrozenModel):
    """Measured adapter premise required from G2, not a caller verification flag."""

    codec: Literal["root-xy-mapping-v1"]
    subject: Identifier
    scene_name: Identifier
    prim_path: Annotated[str, Field(strict=True, min_length=1, max_length=512, pattern=r"^/")]
    root_kind: Literal["rigid_object"]
    position_mapping: Literal["root-world-with-env-origin-v1"]
    authored_coordinate_frame: Literal["env_local"]
    placement_semantics: Literal["weighted-at-position-root-xy-v1"]
    relation_index: Count
    relation_loss_weight: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
    original_scene_digest: Hash
    candidate_scene_digest: Hash


class RootXYHypothesis(FrozenModel):
    codec: Literal["root-xy-hypothesis-v1"]
    mechanism: Literal["direct-root-xy-goal-v1"]
    purpose: Literal["corrective_repair", "diagnostic_intervention"]
    target_subject: Identifier
    goal_criterion_digest: Hash
    diagnostic_manifest_digest: Hash
    diagnostic_assessment_id: Hash
    repair_selection_digest: Hash
    source_acquisition_id: Hash
    step: Count
    clock: Literal["control_step"]
    before_world_xy_m: tuple[Coordinate, Coordinate]
    goal_world_xy_m: tuple[Coordinate, Coordinate]
    authored_before_xy_m: tuple[Coordinate, Coordinate]
    proposed_authored_xy_m: tuple[Coordinate, Coordinate]
    predicted_delta_world_xy_m: tuple[Coordinate, Coordinate]
    baseline_error_m: Amount
    predicted_error_m: Amount
    displacement_tolerance_m: Annotated[float, Field(strict=True, gt=0, le=1e12, allow_inf_nan=False)]
    limitations: tuple[Text, ...]

    def digest(self):
        return _digest(self.model_dump(mode="json"))


class ResolvedObservationSelection(FrozenModel):
    codec: Literal["informative-acquisition-selection-v1"]
    contract_digest: Hash
    policy_digest: Hash
    source_acquisition_id: Hash
    acquisition: AcquisitionSchedule
    requires_new_realization_and_reset: Literal[True] = True
    establishes_original_proposition: Literal[False] = False

    def digest(self):
        return _digest(self.model_dump(mode="json"))


class SceneActionDecision(FrozenModel):
    codec: Literal["scene-eligibility-v1"]
    run_id: Identifier
    contract_digest: Hash
    policy_digest: Hash
    original_candidate_id: Hash
    candidate_id: Hash
    candidate_digest: Hash
    source_manifest_digest: Hash
    source_acquisition_id: Hash
    cohort: EvidenceCohort
    required_evidence: Annotated[tuple[CriterionEvidence, ...], Field(min_length=1, max_length=32)]
    action: Literal["stop", "informative_observation", "diagnostic_intervention", "corrective_repair"]
    reason: Identifier
    can_execute: Literal[False] = False
    diagnostic_manifest_digest: Hash | None = None
    repair_selection_digest: Hash | None = None
    observation_selection: ResolvedObservationSelection | None = None
    hypothesis: RootXYHypothesis | None = None
    proposed_scene_digest: Hash | None = None
    required_effects: tuple[Identifier, ...] = ()
    limitations: tuple[Text, ...]

    def digest(self):
        return _digest(self.model_dump(mode="json"))


def bound_action_selection(contract, candidate, observation):
    """Check retained scientific identities before routing or reserving effects."""
    from .observation_schedule import compile_acquisition

    if contract.schema_version != "5" or observation.action_selection is None:
        raise ValueError("Exact scientific selection required")
    selected = SceneActionDecision.model_validate_json(canonical(observation.action_selection))
    binding = CandidateBinding(
        candidate_digest=candidate.digest,
        contract_digest=contract_digest(contract),
        profile_digest=profile_digest(contract),
    )
    acquisition = compile_acquisition(
        contract.acquisition, contract.criteria, candidate=binding, cohort=observation.cohort
    ).metadata()["acquisition_id"]
    required_ids = {c.criterion_id for c in contract.criteria if c.requirement == "required"}
    measured = tuple(e for e in observation.evidence if e.criterion_id in required_ids)
    if (
        selected.run_id != candidate.run_id
        or selected.candidate_id != candidate.candidate_id
        or selected.original_candidate_id != candidate.original_id
        or selected.candidate_digest != candidate.digest
        or selected.contract_digest != binding.contract_digest
        or selected.policy_digest != _digest(contract.action_policy.model_dump(mode="json"))
        or selected.source_manifest_digest != observation.source_manifest_digest
        or selected.source_acquisition_id != acquisition
        or selected.cohort != observation.cohort
        or canonical([e.model_dump(mode="json") for e in selected.required_evidence])
        != canonical([e.model_dump(mode="json") for e in measured])
    ):
        raise ValueError("Scientific selection binding mismatch")
    return selected


def validate_selected_effect(contract, candidate, action, selection, *, initial_capture=False):
    """Refuse unsupported/stale scientific actions before reservation and release."""
    if contract.schema_version != "5":
        if selection is not None:
            raise ValueError("Unexpected scientific selection")
        return None
    if selection is None:
        if action == "capture" and initial_capture and candidate.parent_id is None:
            return None
        if action == "assess":
            return None
        raise ValueError("Scientific selection required before effect")
    selected = SceneActionDecision.model_validate_json(canonical(selection))
    if (
        selected.contract_digest != contract_digest(contract)
        or selected.policy_digest != _digest(contract.action_policy.model_dump(mode="json"))
        or selected.run_id != candidate.run_id
        or selected.original_candidate_id != candidate.original_id
    ):
        raise ValueError("Scientific selection identity mismatch")
    parent = selected.candidate_id == candidate.candidate_id and selected.candidate_digest == candidate.digest
    repaired = candidate.parent_id == selected.candidate_id and candidate.digest == selected.proposed_scene_digest
    repair = selected.action in ("corrective_repair", "diagnostic_intervention")
    if action == "repair" and parent and repair and selected.hypothesis is not None:
        return selected
    if action == "capture" and repaired and repair and selected.hypothesis is not None:
        return selected
    if action == "capture" and parent and selected.action == "informative_observation":
        if (
            selected.observation_selection is None
            or contract.action_policy.observation is None
            or selected.observation_selection.acquisition != contract.action_policy.observation
        ):
            raise ValueError("Unpermitted observation selection")
        return selected
    raise ValueError("Scientific selection cannot release this effect")


def _context(contract, original, current, artifacts, source, protect):
    contract = parse_contract(contract.model_dump_json())
    original = CandidateRecord.model_validate_json(original.model_dump_json())
    current = CandidateRecord.model_validate_json(current.model_dump_json())
    if (
        contract.schema_version != "5"
        or current.run_id != original.run_id
        or current.original_id != original.candidate_id
    ):
        raise ValueError("configurable current/original lineage required")
    if original.parent_id is not None or original.original_id != original.candidate_id:
        raise ValueError("retained original candidate required")
    for candidate in (original, current):
        raw = _scene_json(json.loads(candidate.scene_json))
        if raw != candidate.scene_json or hashlib.sha256(raw.encode()).hexdigest() != candidate.digest:
            raise ValueError("candidate bytes do not match lineage")
    if current.digest != original.digest:
        validate_permitted_scene_repair(contract, json.loads(original.scene_json), json.loads(current.scene_json))
    binding = CandidateBinding(
        candidate_digest=current.digest,
        contract_digest=contract_digest(contract),
        profile_digest=profile_digest(contract),
    )
    payload = _bound_payload(binding, source.cohort, artifacts, source, protect)
    if payload.get("codec") != "observation-v2" or payload["acquisition"]["plan"] != contract.acquisition.model_dump(
        mode="json"
    ):
        raise ValueError("exact admitted acquisition selection required")
    return contract, original, current, payload


def _diagnostic_payload(contract, original, current, artifacts, source, protect):
    contract, original, current, payload = _context(contract, original, current, artifacts, source, protect)
    selection = resolve_repair_selection(contract, original)
    mapping = RootXYMappingPremise.model_validate(payload.get("diagnostics", {}).get("root_xy_mapping", {}))
    step = contract.acquisition.displacement_step
    samples = [s for s in payload["samples"] if s["step"] == step]
    if len(samples) != 1:
        raise ValueError("diagnostic displacement coverage missing")
    sample = samples[0]
    measured = sample["subjects"][selection.target_subject]
    if (
        mapping.subject != selection.target_subject
        or mapping.original_scene_digest != original.digest
        or mapping.candidate_scene_digest != current.digest
        or mapping.relation_index != selection.relation_index
        or mapping.relation_loss_weight != selection.relation_loss_weight
        or mapping.scene_name != measured.get("scene_name")
        or mapping.prim_path != measured.get("prim_path")
        or mapping.root_kind != measured.get("root_kind")
        or sum(v.get("prim_path") == mapping.prim_path for v in sample["subjects"].values()) != 1
    ):
        raise ValueError("unsupported or inconsistent measured root mapping")
    facts = dict(
        mapping=mapping.model_dump(mode="json"),
        repair_selection_digest=selection.digest(),
        source_acquisition_id=payload["acquisition"]["acquisition_id"],
        observation_id=sample["observation_id"],
        clock=sample["clock"],
        step=step,
        time_seconds=sample["time_seconds"],
        position_world_m=measured["position_w"],
        origin_world_m=sample["origin_w"],
        provenance=payload["provenance"],
    )
    return dict(
        kind="diagnostic",
        codec="root-xy-diagnostic-v1",
        source_manifest_digest=source.manifest_digest,
        assessment_id=assessment_identity("root-xy-diagnostic", source.manifest_digest, facts),
        facts=facts,
    )


def retain_root_xy_diagnostic(contract, original, current, artifacts, source, *, protect):
    """Retain checked source premises and pose/origin; missing mapping is never invented."""
    payload = _diagnostic_payload(contract, original, current, artifacts, source, protect)
    return artifacts.write(source.candidate, source.cohort, payload, protect=protect)


def evaluate_action_eligibility(
    contract, original, current, artifacts, source, *, visual_answer=None, diagnostic=None, protect
):
    """Recompute required predicates and consume verified premises under the frozen policy.

    Returns:
        A bound scientific decision. Actual counts, current authority, ownership,
        release, realized displacement and causal validation remain separate gates.
    """
    contract, original, current, payload = _context(contract, original, current, artifacts, source, protect)
    policy = contract.action_policy
    assert policy is not None
    evidence = []
    for criterion in contract.criteria:
        if criterion.requirement != "required":
            continue
        if criterion.kind == "visual":
            if visual_answer is None:
                raise ValueError("missing visual execution result is not UNKNOWN")
            value = evaluate_visual_answer(
                criterion, source.candidate, source.cohort, artifacts, source, visual_answer, protect=protect
            )
        else:
            value = evaluate_measurement(criterion, source.candidate, source.cohort, artifacts, source, protect=protect)
        evidence.append(value)
    aggregate = assess_scene_evidence(
        required=project_required_criteria(contract),
        candidate=source.candidate,
        evidence=tuple(evidence),
        selected_cohort=source.cohort,
        verified_manifest_digests=frozenset(value.manifest_digest for value in evidence),
    )
    if aggregate.collection_status != "complete":
        raise ValueError("incomplete required collection is not UNKNOWN")
    base: dict[str, Any] = dict(
        codec="scene-eligibility-v1",
        run_id=current.run_id,
        contract_digest=contract_digest(contract),
        policy_digest=_digest(policy.model_dump(mode="json")),
        original_candidate_id=original.candidate_id,
        candidate_id=current.candidate_id,
        candidate_digest=current.digest,
        source_manifest_digest=source.manifest_digest,
        source_acquisition_id=payload["acquisition"]["acquisition_id"],
        cohort=source.cohort,
        required_evidence=tuple(evidence),
        limitations=(
            "eligibility_is_not_release_authority",
            "not_calibration_or_causal_proof",
            f"{payload['provenance']}_source",
        ),
    )

    def stop(reason):
        return SceneActionDecision(**base, action="stop", reason=reason)

    if aggregate.truth == "true" and not aggregate.conflict:
        return stop("all_required_true")
    action = policy.on_false if aggregate.truth == "false" and not aggregate.conflict else policy.on_unknown
    if action == "stop":
        return stop("selected_stopping_policy")
    if action == "informative_observation":
        assert policy.observation is not None
        selection = ResolvedObservationSelection(
            codec="informative-acquisition-selection-v1",
            contract_digest=base["contract_digest"],
            policy_digest=base["policy_digest"],
            source_acquisition_id=base["source_acquisition_id"],
            acquisition=policy.observation,
        )
        return SceneActionDecision(
            **base,
            action=action,
            reason="selected_informative_observation",
            observation_selection=selection,
            required_effects=("fresh_native_acquisition",),
        )
    by_id = {value.criterion_id: value for value in evidence}
    if any(by_id[key].verdict != "established" or by_id[key].conflict for key in policy.prerequisite_criterion_ids):
        return stop("required_prerequisite_not_established")
    goal = next(c for c in contract.criteria if c.criterion_id == policy.goal_criterion_id)
    parameters = goal.parameters
    assert isinstance(parameters, PoseErrorParameters)
    if action == "corrective_repair" and (
        by_id[goal.criterion_id].verdict != "violated" or by_id[goal.criterion_id].conflict
    ):
        return stop("causal_link_not_supported")
    if diagnostic is None:
        return stop("diagnostic_evidence_required")
    checked = artifacts.verified_payload(diagnostic, protect=protect)
    expected = _diagnostic_payload(contract, original, current, artifacts, source, protect)
    if (
        diagnostic.candidate != source.candidate
        or diagnostic.cohort != source.cohort
        or canonical(checked) != canonical(expected)
    ):
        raise ValueError("diagnostic bytes or ancestry mismatch")
    selection = resolve_repair_selection(contract, original)
    facts = checked["facts"]
    before = (facts["position_world_m"][0], facts["position_world_m"][1])
    desired = parameters.target_xy_m
    baseline_error = hypot(before[0] - desired[0], before[1] - desired[1])
    if action == "corrective_repair" and _compare_limit(baseline_error, goal.limit):
        return stop("causal_link_not_supported")  # A historical/other-subject failure is not a current target defect.
    delta = (
        (desired[0] - before[0], desired[1] - before[1])
        if action == "corrective_repair"
        else policy.diagnostic_delta_xy_m
    )
    assert delta is not None
    candidate = json.loads(current.scene_json)
    params = candidate["relations"][selection.relation_index]["params"]
    authored = (float(params["x"]), float(params["y"]))
    for axis, value in zip(("x", "y"), delta):
        if value:
            params[axis] = params[axis] + value
    try:
        validate_selected_scene_repair(contract, selection, original, candidate)
    except ValueError:
        return stop("proposal_outside_original_permissions")
    predicted_error = hypot(before[0] + delta[0] - desired[0], before[1] + delta[1] - desired[1])
    if action == "corrective_repair" and (
        predicted_error >= baseline_error or not _compare_limit(predicted_error, goal.limit)
    ):
        return stop("causal_link_not_supported")
    assert policy.displacement_tolerance_m is not None
    hypothesis = RootXYHypothesis(
        codec="root-xy-hypothesis-v1",
        mechanism="direct-root-xy-goal-v1",
        purpose=action,
        target_subject=selection.target_subject,
        goal_criterion_digest=by_id[goal.criterion_id].criterion_digest,
        diagnostic_manifest_digest=diagnostic.manifest_digest,
        diagnostic_assessment_id=checked["assessment_id"],
        repair_selection_digest=selection.digest(),
        source_acquisition_id=base["source_acquisition_id"],
        step=facts["step"],
        clock="control_step",
        before_world_xy_m=before,
        goal_world_xy_m=desired,
        authored_before_xy_m=authored,
        proposed_authored_xy_m=(params["x"], params["y"]),
        predicted_delta_world_xy_m=delta,
        baseline_error_m=baseline_error,
        predicted_error_m=predicted_error,
        displacement_tolerance_m=policy.displacement_tolerance_m,
        limitations=(
            "weighted_constraint_not_guaranteed_pose_assignment",
            "fresh_matched_displacement_and_goal_assessment_required",
            "preserve_prerequisites_and_report_uncontrolled_factors",
        ),
    )
    return SceneActionDecision(
        **base,
        action=action,
        reason="supported_mechanism_selected",
        diagnostic_manifest_digest=diagnostic.manifest_digest,
        repair_selection_digest=selection.digest(),
        hypothesis=hypothesis,
        proposed_scene_digest=hashlib.sha256(_scene_json(candidate).encode()).hexdigest(),
        required_effects=("authorized_refinement", "fresh_native_acquisition"),
    )


def validate_action_proposal(
    contract, original, current, artifacts, source, decision, proposal, *, visual_answer=None, diagnostic=None, protect
):
    """Recompute eligibility and bind a proposal; this does not release any effect."""
    supplied = SceneActionDecision.model_validate_json(canonical(decision.model_dump(mode="json")))
    checked = evaluate_action_eligibility(
        contract,
        original,
        current,
        artifacts,
        source,
        visual_answer=visual_answer,
        diagnostic=diagnostic,
        protect=protect,
    )
    if (
        supplied != checked
        or checked.action not in ("corrective_repair", "diagnostic_intervention")
        or hashlib.sha256(_scene_json(proposal).encode()).hexdigest() != checked.proposed_scene_digest
    ):
        raise ValueError("proposal does not match the verified decision/hypothesis")
    selection = resolve_repair_selection(contract, original)
    if selection.digest() != checked.repair_selection_digest:
        raise ValueError("decision repair selection changed")
    return validate_selected_scene_repair(contract, selection, original, proposal)
