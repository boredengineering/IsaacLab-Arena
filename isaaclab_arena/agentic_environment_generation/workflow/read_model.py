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
        ):
            selected_observations.append(Observation.model_validate_json(row["payload"]))
            for item in observation["evidence"]:
                selected.setdefault(item["criterion_id"], []).append(item)
    requirements = {r.criterion_id: r for r in project_required_criteria(contract)} if selected_observations else {}
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
        scene_acceptance="accepted" if run.state == "accepted" else "not_established",
        workflow_outcome=run.state,
        policy_outcome="not_run",
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
