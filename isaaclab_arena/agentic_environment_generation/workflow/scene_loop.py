# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Scene-only rules and immutable records; lifecycle authority stays in Neo4j.

Observation verification and bounded effects are explicit trusted ports. Metadata
alone is not measurement proof; synthetic ports do not establish native validity.
"""
import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from .attempts import AttemptFence, GenerationReservation, WorkerRegistration
from .contracts import Count, FrozenModel, Hash, Identifier, contract_digest
from .evidence import (
    CandidateBinding,
    CriterionEvidence,
    EvidenceCohort,
    SceneEvidenceAssessment,
    assess_scene_evidence,
)
from .evidence_contracts import project_required_criteria
from .repairs import _scene_json, validate_permitted_scene_repair
from .results import CleanupEvidence


def identity(*values):
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def profile_digest(contract):
    return identity(contract.execution.model_dump(mode="json"))


class CandidateRecord(FrozenModel):
    candidate_id: Hash
    run_id: Identifier
    original_id: Hash
    parent_id: Hash | None
    source_id: Identifier
    digest: Hash
    scene_json: str


class Observation(FrozenModel):
    """Byte-verified port output; the service calls verify again before adoption."""

    cohort: EvidenceCohort
    evidence: tuple[CriterionEvidence, ...]
    verified_manifest_digests: tuple[Hash, ...]
    static_failure: Literal["ineffective_edit", "invalid_visual_answer"] | None = None


class SceneDecision(FrozenModel):
    action: Literal["accept", "repair", "observe", "stop"]
    reason: str
    assessment: SceneEvidenceAssessment | None = None


class SceneReservation(GenerationReservation):
    """Same conservative intent ledger; reservations are never usage/refund proof."""

    candidates: Count = 0
    revisions: Count = 0
    realizations: Count = 0
    steps: Count = 0
    observations: Count = 0


class ScenePortProfile(FrozenModel):
    """Only explicitly synthetic bounded ports admitted in this first tracer.

    Native/model adapters must add tested external enforcement before admission;
    a producer's self-reported token/cost usage cannot enable them.
    """

    port_id: Identifier
    assurance: Literal["synthetic"]
    owned_worker: bool = False
    """Trusted composition capability, not user authorization or physical proof."""
    producer_ids: tuple[Identifier, ...]
    observe: SceneReservation
    repair: SceneReservation


class SceneIntent(FrozenModel):
    intent_id: Hash
    candidate_id: Hash
    action: Literal["observe", "repair"]
    status: Literal["reserved", "released", "produced", "reconciliation_required"]
    reservation: SceneReservation
    released_at: float | None = None
    worker_fence: AttemptFence | None = None
    worker_registration: WorkerRegistration | None = None
    worker_cleanup: CleanupEvidence | None = None


class SceneResult(FrozenModel):
    observation: Observation | None = None
    candidate_json: str | None = None
    failure: Literal["repair_rejected", "invalid_candidate", "evidence_verification_failed"] | None = None


@dataclass(frozen=True)
class SceneSnapshot:
    run: object
    original: CandidateRecord
    candidate: CandidateRecord
    decision: SceneDecision
    intent: SceneIntent | None
    profile: ScenePortProfile


def candidate_record(run_id, scene, *, source_id, original_id=None, parent_id=None):
    raw = _scene_json(scene)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    candidate_id = identity(run_id, source_id, digest)
    return CandidateRecord(
        candidate_id=candidate_id,
        run_id=run_id,
        source_id=source_id,
        original_id=original_id or candidate_id,
        parent_id=parent_id,
        digest=digest,
        scene_json=raw,
    )


def repaired_candidate(contract, original, parent, scene, *, source_id):
    validate_permitted_scene_repair(contract, json.loads(original.scene_json), scene)
    if parent.original_id != original.candidate_id or parent.run_id != original.run_id:
        raise ValueError("repair lineage mismatch")
    if _scene_json(scene) == parent.scene_json:
        raise ValueError("repair_no_op")
    return candidate_record(
        parent.run_id, scene, source_id=source_id, original_id=original.candidate_id, parent_id=parent.candidate_id
    )


def assess_and_route(contract, candidate, observation):
    """Apply frozen scene rules, never model-suggested commands or generic routing."""
    try:
        required = project_required_criteria(contract)
    except ValueError:
        return SceneDecision(action="stop", reason="unsupported_criterion")
    assessment = assess_scene_evidence(
        required,
        CandidateBinding(
            candidate_digest=candidate.digest,
            contract_digest=contract_digest(contract),
            profile_digest=profile_digest(contract),
        ),
        observation.evidence,
        frozenset(observation.verified_manifest_digests),
        selected_cohort=observation.cohort,
    )
    if observation.static_failure:
        return SceneDecision(action="stop", reason=observation.static_failure, assessment=assessment)
    if assessment.status == "established":
        return SceneDecision(action="accept", reason="all_required_established", assessment=assessment)
    visual = {r.criterion_id for r in required if r.modality == "visual"}
    if "ambiguous_receipts" in assessment.limitations:
        return SceneDecision(action="observe", reason="evidence_not_established", assessment=assessment)
    if assessment.status == "not_established":
        if set(assessment.missing_ids) - visual:
            return SceneDecision(action="observe", reason="repair_preconditions_not_established", assessment=assessment)
        repair = (
            bool(assessment.failed_ids)
            and set(assessment.failed_ids) <= visual
            and bool(contract.allowed_interventions)
        )
        return SceneDecision(
            action="repair" if repair else "stop",
            reason="supported_visual_failure" if repair else "unsupported_correction",
            assessment=assessment,
        )
    return SceneDecision(action="observe", reason="evidence_not_established", assessment=assessment)
