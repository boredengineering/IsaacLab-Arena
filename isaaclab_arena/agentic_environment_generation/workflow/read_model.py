# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Shared effect-free result projection; reservations never imply actual consumption."""

import json
from decimal import Decimal

from .contracts import contract_digest, parse_contract
from .evidence import CandidateBinding, assess_scene_evidence
from .evidence_contracts import project_required_criteria
from .scene_evidence_artifacts import _protected
from .scene_loop import Observation, profile_digest


def inspection_response_revision(value):
    """Hash the whole response separately from its atomic retained revision."""
    import hashlib

    from .queries import RUN_INSPECTION_BYTES
    from .scene_evidence_artifacts import canonical

    raw = canonical(value.model_dump(mode="json", exclude={"response_revision"}), max_bytes=RUN_INSPECTION_BYTES)
    result = value.model_copy(update={"response_revision": hashlib.sha256(raw).hexdigest()})
    canonical(result.model_dump(mode="json"), max_bytes=RUN_INSPECTION_BYTES)
    return result


def inspection_budget(intent, reservations):
    """Project exact cumulative allowances using the legacy ledger semantics."""
    from .queries import InspectionBudget, ReservationTotals

    b = intent.contract.budget
    limits = dict(
        model_calls=b.max_model_calls,
        model_tokens=b.max_model_tokens,
        cost_ceiling_usd=b.max_cost_usd,
        runtime_allowance_seconds=b.max_runtime_seconds,
        candidates=b.max_candidates,
        revisions=b.max_revisions,
        realizations=b.max_realizations,
        steps=b.max_steps,
        observations=b.max_observations,
        policy_episodes=b.max_policy_episodes,
        policy_steps=b.max_policy_steps,
    )
    # Inputs are the validated finite float Amount/Count ledger and budget,
    # not arbitrary Decimal coefficients. Include limits in the aligned width
    # so subtraction is exact too, plus row-count digits for addition carries.
    from decimal import Context, ROUND_HALF_EVEN, localcontext

    amounts = {key: [Decimal(str(row.get(key, 0))) for row in reservations] for key in limits}
    ceilings = {key: Decimal(str(value)) for key, value in limits.items()}
    operands = [Decimal(0), *ceilings.values(), *(value for values in amounts.values() for value in values)]
    least = min(int(value.as_tuple().exponent) for value in operands)
    most = max(value.adjusted() + 1 for value in operands)
    most += len(str(len(reservations) + 1))
    context = Context(
        prec=most - least,
        Emin=least,
        Emax=most,
        rounding=ROUND_HALF_EVEN,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[],
    )
    with localcontext(context):
        totals = {key: sum(values, Decimal(0)) for key, values in amounts.items()}
        remaining = {key: max(Decimal(0), limit - totals[key]) for key, limit in ceilings.items()}
    counts = set(limits) - {"cost_ceiling_usd", "runtime_allowance_seconds"}
    reserved = {key: int(value) if key in counts else value for key, value in totals.items()}
    remaining = {key: int(value) if key in counts else value for key, value in remaining.items()}
    return InspectionBudget(
        reserved=ReservationTotals(**reserved),
        remaining=ReservationTotals(**remaining),
        admitted_at=intent.submission.admitted_at,
        deadline=intent.submission.admitted_at + b.total_deadline_seconds,
        per_operation_ceiling_seconds=b.per_operation_timeout_seconds,
    )


def inspection_scene(contract, candidate, decision, evidence, assessment_id, decision_id, next_intent_id):
    """Assess only an explicitly retained selected assessment, never raw claimed passes."""
    from .queries import CandidateReference, CorruptRunInspection, CriterionInspection, SceneInspection

    observation = evidence.observation if evidence is not None else None
    selected = (
        decision.assessment is not None
        and assessment_id is not None
        and evidence is not None
        and evidence.candidate_id == candidate.candidate_id
    )
    limitations = ["retained_metadata_not_fresh_verification"]
    try:
        required = project_required_criteria(
            contract,
            include_policy=decision.scene_disposition == "accepted"
            or decision.action == "policy"
            or decision.policy_trial is not None,
        )
    except ValueError:
        required = ()
        limitations.append("unsupported_criterion_projector")
    binding = CandidateBinding(
        candidate_digest=candidate.digest,
        contract_digest=contract_digest(contract),
        profile_digest=profile_digest(contract),
    )
    if selected and required:
        aggregate = assess_scene_evidence(
            required,
            binding,
            observation.evidence,
            frozenset(observation.verified_manifest_digests),
            selected_cohort=observation.cohort,
        )
        if aggregate != decision.assessment:
            raise CorruptRunInspection()
    requirements = {r.criterion_id: r for r in required}
    criteria = []
    for criterion in contract.criteria:
        found = (
            tuple(e for e in observation.evidence if e.criterion_id == criterion.criterion_id) if observation else ()
        )
        verdict = "not_assessed"
        if criterion.requirement == "advisory":
            verdict = "reported_only" if found else "not_assessed"
        elif criterion.kind == "policy":
            verdict = (
                "not_assessed"
                if decision.policy_trial is None
                else {"passed": "established", "failed": "violated", "unknown": "inconclusive"}[
                    decision.policy_trial.aggregate().outcome
                ]
            )
        elif not required:
            verdict = "unsupported"
        elif selected:
            single = assess_scene_evidence(
                (requirements[criterion.criterion_id],),
                binding,
                observation.evidence,
                frozenset(observation.verified_manifest_digests),
                selected_cohort=observation.cohort,
            )
            verdict = {"established": "established", "not_established": "violated", "inconclusive": "inconclusive"}[
                single.status
            ]
        criteria.append(
            CriterionInspection(
                criterion_id=criterion.criterion_id,
                requirement=criterion.requirement,
                verdict=verdict,
                reported_verdicts=tuple(e.verdict for e in found),
                manifests=tuple(sorted({e.manifest_digest for e in found})),
            )
        )
    return SceneInspection(
        candidate=CandidateReference(**candidate.model_dump(exclude={"run_id", "scene_json"})),
        decision_id=decision_id,
        decision_identity_provenance="latest_scene_event" if decision_id else "unavailable_retained_causality",
        action=decision.action,
        reason=decision.reason,
        next_intent_id=next_intent_id,
        evidence_id=evidence.evidence_id if evidence else None,
        observation=observation,
        assessment_id=assessment_id,
        assessment=decision.assessment,
        selected_assessed=selected,
        policy_trial=decision.policy_trial,
        assessment_status=decision.assessment.status if decision.assessment else "not_assessed",
        acceptance=(
            "accepted" if decision.action == "accept" or decision.scene_disposition == "accepted" else "not_established"
        ),
        criteria=tuple(criteria),
        limitations=tuple(limitations),
    )


def workflow_result(store, run_id, *, protect):
    """Return screened durable identities, conservative budgets and recovery actions."""
    records = store.result_records(run_id)
    run, scene, owner = (records[k] for k in ("run", "scene", "owner"))
    contract = parse_contract(run.contract_json)
    budget = contract.budget
    limits = dict(
        model_calls=budget.max_model_calls,
        model_tokens=budget.max_model_tokens,
        cost_ceiling_usd=budget.max_cost_usd,
        runtime_allowance_seconds=budget.max_runtime_seconds,
        candidates=budget.max_candidates,
        revisions=budget.max_revisions,
        realizations=budget.max_realizations,
        steps=budget.max_steps,
        observations=budget.max_observations,
        policy_episodes=budget.max_policy_episodes,
        policy_steps=budget.max_policy_steps,
    )
    reservations = [json.loads(i["reservation"]) for i in records["intents"]]
    reserved = {key: float(sum(Decimal(str(r.get(key, 0))) for r in reservations)) for key in limits}
    # Initial candidate production is reserved by generation, whose older codec
    # does not contain the scene-only candidates counter.
    reserved["candidates"] += sum(1 for i in records["intents"] if i["scene"] is None)
    remaining = {key: max(0, float(Decimal(str(limit)) - Decimal(str(reserved[key])))) for key, limit in limits.items()}
    counts = {
        "model_calls",
        "model_tokens",
        "candidates",
        "revisions",
        "realizations",
        "steps",
        "observations",
        "policy_episodes",
        "policy_steps",
    }
    for key in counts:
        reserved[key], remaining[key] = int(reserved[key]), int(remaining[key])
    evidence, criteria = [], []
    selected = {}
    selected_observations = []
    selected_id = records.get("selected_evidence_id")
    # Older records can establish selection only when there is no ambiguity.
    # Opaque evidence IDs and candidate identity do not imply temporal ordering.
    if "selected_evidence_id" not in records and scene is not None:
        matching = [r for r in records["evidence"] if r["candidate_id"] == scene.candidate.candidate_id]
        if len(matching) == 1:
            selected_id = matching[0]["evidence_id"]
    for row in records["evidence"]:
        observation = json.loads(row["payload"])
        evidence.append(
            dict(
                evidence_id=row["evidence_id"],
                candidate_id=row["candidate_id"],
                cohort=observation["cohort"],
                manifests=observation["verified_manifest_digests"],
                criteria=observation["evidence"],
            )
        )
        if (
            scene is not None
            and row["candidate_id"] == scene.candidate.candidate_id
            and row["evidence_id"] == selected_id
            and scene.decision.action not in ("capture", "assess")
        ):
            selected_observations.append(Observation.model_validate_json(row["payload"]))
            for item in observation["evidence"]:
                selected.setdefault(item["criterion_id"], []).append(item)
    requirements = (
        {
            r.criterion_id: r
            for r in project_required_criteria(
                contract,
                include_policy=scene.decision.scene_disposition == "accepted"
                or scene.decision.action == "policy"
                or scene.decision.policy_trial is not None,
            )
        }
        if selected_observations
        else {}
    )
    for criterion in contract.criteria:
        found = selected.get(criterion.criterion_id, [])
        verdict = found[0]["verdict"] if len(found) == 1 else "inconclusive" if found else "not_run"
        if criterion.requirement == "required" and found:
            verdict = "inconclusive"
            requirement = requirements.get(criterion.criterion_id)
            if len(selected_observations) == 1 and requirement is not None:
                current = selected_observations[0]
                try:
                    assessment = assess_scene_evidence(
                        (requirement,),
                        CandidateBinding(
                            candidate_digest=scene.candidate.digest,
                            contract_digest=contract_digest(contract),
                            profile_digest=profile_digest(contract),
                        ),
                        current.evidence,
                        frozenset(current.verified_manifest_digests),
                        selected_cohort=current.cohort,
                    )
                except ValueError:
                    pass  # Retain rejected metadata diagnostically, never promote its claimed pass.
                else:
                    verdict = {
                        "established": "established",
                        "not_established": "violated",
                        "inconclusive": "inconclusive",
                    }[assessment.status]
        if criterion.kind == "policy" and criterion.requirement == "required" and scene and scene.decision.policy_trial:
            verdict = {"passed": "established", "failed": "violated", "unknown": "inconclusive"}[
                scene.decision.policy_trial.aggregate().outcome
            ]
        criteria.append(
            dict(
                criterion_id=criterion.criterion_id,
                requirement=criterion.requirement,
                verdict=verdict,
                manifests=sorted({e["manifest_digest"] for e in found}),
            )
        )
    settled = run.state in ("accepted", "stopped", "cancelled", "failed")
    pending_scene = (
        scene is not None
        and scene.intent is not None
        and scene.intent.status == "reserved"
        and scene.intent.worker_fence is None
    )
    known = run.state == "pending" or pending_scene
    recovery = "settled" if settled else "known_unreleased" if known else "exact_reconciliation_required"
    actions = [] if settled else ["cancel", "resume"]
    value = dict(
        schema_version=1,
        disposition="observed",
        run_id=run.run_id,
        operation_id=run.operation_id,
        state=run.state,
        phase=run.phase,
        version=run.version,
        event_cursor=run.event_cursor,
        reason=scene.decision.reason if scene else None,
        available_actions=actions,
        recovery=recovery,
        owner=owner.model_dump(mode="json") if owner else None,
        candidate=scene.candidate.model_dump(mode="json") if scene else None,
        scene_intent=(scene.intent.model_dump(mode="json") if scene and scene.intent else None),
        criteria=criteria,
        evidence=evidence,
        budget=dict(
            reserved=reserved,
            remaining=remaining,
            actual_consumption="unknown",
            accounting="conservative_cumulative_reservations_no_refunds",
            runtime_accounting="cumulative_unallocated_allowance_not_walltime",
            per_operation_ceiling_seconds=budget.per_operation_timeout_seconds,
            admitted_at=records["admitted_at"],
            deadline=records["admitted_at"] + budget.total_deadline_seconds,
        ),
        scene_acceptance=(
            "accepted"
            if run.state == "accepted" or (scene and scene.decision.scene_disposition == "accepted")
            else "not_established"
        ),
        workflow_outcome=run.state,
        policy_outcome=(
            scene.decision.policy_trial.aggregate().outcome
            if scene and scene.decision.policy_trial is not None
            else "ready_for_policy" if scene and scene.decision.action == "policy" else "not_run"
        ),
        policy_trial=(
            scene.decision.policy_trial.model_dump(mode="json") if scene and scene.decision.policy_trial else None
        ),
        publication=("not_published" if contract.effects.allow_publication else "not_requested"),
        experiment=("not_run" if contract.execution.policy or contract.effects.allow_dcrg else "not_requested"),
        cleanup=(
            "owner_retired"
            if owner is not None and not owner.dirty
            else "pending_or_unknown" if owner else "not_started"
        ),
        limitations=[
            "synthetic_capture_no_native_physical_acceptance",
            "remote_effects_unknown",
        ],
    )
    return json.loads(_protected(value, protect))
