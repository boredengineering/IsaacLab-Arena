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

from pydantic import model_serializer, model_validator

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
from .policy_contracts import PolicyTaskBinding, PolicyTrialReceipt
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
    action: Literal["accept", "repair", "observe", "capture", "assess", "policy", "stop"]
    reason: str
    assessment: SceneEvidenceAssessment | None = None
    policy_trial: PolicyTrialReceipt | None = None
    scene_disposition: Literal["accepted"] | None = None

    @model_serializer(mode="wrap")
    def retain_scene_shape(self, handler):
        value = handler(self)
        if self.policy_trial is None:
            value.pop("policy_trial", None)
        if self.scene_disposition is None:
            value.pop("scene_disposition", None)
        return value


class SceneReservation(GenerationReservation):
    """Same conservative intent ledger; reservations are never usage/refund proof."""

    candidates: Count = 0
    revisions: Count = 0
    realizations: Count = 0
    steps: Count = 0
    observations: Count = 0
    policy_episodes: Count = 0
    policy_steps: Count = 0

    @model_serializer(mode="wrap")
    def retain_zero_policy_shape(self, handler):
        value = handler(self)
        for key in ("policy_episodes", "policy_steps"):
            if not getattr(self, key):
                value.pop(key, None)
        return value


class _VersionedSceneModel(FrozenModel):
    codec_version: Literal[1, 2] = 1

    @model_serializer(mode="wrap")
    def retain_v1_shape(self, handler):
        value = handler(self)
        if self.codec_version == 1:
            for key in (
                "codec_version",
                "capture",
                "assess",
                "observation_id",
                "observation_digest",
                "policy",
                "policy_binding",
                "policy_criteria",
                "policy_trial",
            ):
                value.pop(key, None)
        return value


class ScenePortProfile(_VersionedSceneModel):
    """V1 synthetic loop or explicit V2 split; neither label proves native validity."""

    port_id: Identifier
    assurance: Literal["synthetic", "native-unverified"]
    owned_worker: bool = False
    """Trusted composition capability, not user authorization or physical proof."""
    producer_ids: tuple[Identifier, ...]
    observe: SceneReservation | None = None
    repair: SceneReservation
    capture: SceneReservation | None = None
    assess: SceneReservation | None = None
    policy: SceneReservation | None = None
    policy_binding: PolicyTaskBinding | None = None
    policy_criteria: tuple[Hash, ...] = ()

    @model_validator(mode="after")
    def versioned_stages(self):
        if self.codec_version == 1:
            if (
                self.assurance != "synthetic"
                or self.observe is None
                or self.capture is not None
                or self.assess is not None
                or self.policy is not None
                or self.policy_binding is not None
                or self.policy_criteria
            ):
                raise ValueError("v1 synthetic observe profile required")
        else:
            if not self.owned_worker or self.observe is not None or self.capture is None or self.assess is None:
                raise ValueError("v2 owned split capture/assess profile required")
            if any(
                getattr(self.capture, key)
                for key in ("model_calls", "model_tokens", "cost_ceiling_usd", "candidates", "revisions")
            ):
                raise ValueError("capture cannot reserve model or revision budget")
            if any(
                getattr(self.assess, key)
                for key in ("realizations", "observations", "steps", "candidates", "revisions")
            ):
                raise ValueError("assessment cannot reserve capture or revision budget")
        if (self.policy is not None) != (self.policy_binding is not None) or (self.policy is not None) != bool(
            self.policy_criteria
        ):
            raise ValueError("complete explicit policy capability required")
        for allocation in (self.observe, self.capture, self.assess, self.repair):
            if allocation is not None and (allocation.policy_episodes or allocation.policy_steps):
                raise ValueError("non-policy stage cannot reserve policy budget")
        return self


class SceneIntent(_VersionedSceneModel):
    intent_id: Hash
    candidate_id: Hash
    action: Literal["observe", "repair", "capture", "assess", "policy"]
    status: Literal["reserved", "released", "produced", "reconciliation_required"]
    reservation: SceneReservation
    released_at: float | None = None
    worker_fence: AttemptFence | None = None
    worker_registration: WorkerRegistration | None = None
    worker_cleanup: CleanupEvidence | None = None
    observation_id: Hash | None = None
    observation_digest: Hash | None = None
    policy_binding: PolicyTaskBinding | None = None

    @model_validator(mode="after")
    def versioned_action(self):
        if self.codec_version == 1 and self.action not in ("observe", "repair"):
            raise ValueError("v1 scene action required")
        if self.codec_version == 2 and self.action == "observe":
            raise ValueError("v2 capture action required")
        if (self.action == "policy") != (self.policy_binding is not None):
            raise ValueError("exact frozen policy binding required")
        if self.action in ("assess", "policy"):
            if self.observation_id is None or self.observation_digest is None:
                raise ValueError("exact retained capture required")
        elif self.observation_id is not None or self.observation_digest is not None:
            raise ValueError("unexpected retained capture binding")
        return self


class SceneResult(_VersionedSceneModel):
    policy_trial: PolicyTrialReceipt | None = None
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


def policy_compatible(contract, profile):
    """Check whole-outcome support against exact trusted contract/task pins."""
    from decimal import Decimal, ROUND_CEILING

    criteria = tuple(c for c in contract.criteria if c.requirement == "required" and c.kind == "policy")
    if len(criteria) != 1:
        return False
    if profile is None or profile.codec_version != 2 or profile.policy_binding is None:
        return False
    binding = profile.policy_binding
    criterion = criteria[0]
    if (
        criterion.evidence_producer != "task-evaluator"
        or criterion.evaluator_version != "v1"
        or criterion.rubric != "completed episode task success rate"
        or criterion.coordinate_frames != ("episode",)
        or criterion.subjects != ("task",)
        or criterion.limit.operator != "ge"
        or criterion.limit.unit != "fraction"
        or not 0 < criterion.limit.value <= 1
        or (criterion.observation_window.start_step, criterion.observation_window.end_step)
        != (0, binding.max_policy_steps)
    ):
        return False
    minimum = int(
        (Decimal(str(criterion.limit.value)) * binding.max_episodes).to_integral_value(rounding=ROUND_CEILING)
    )
    return (
        binding.contract_digest == contract_digest(contract)
        and binding.seed == contract.execution.seed
        and contract.execution.policy is not None
        and binding.minimum_successes == minimum
        and profile.policy_criteria == tuple(identity(c.model_dump(mode="json")) for c in criteria)
        and all(c.required_modalities == ("policy_rollout",) for c in criteria)
    )


def route_capture(contract, candidate, observation):
    """Bind verified native capture metadata without evaluating model criteria."""
    if (
        observation.cohort.contract_digest != contract_digest(contract)
        or observation.cohort.profile_digest != profile_digest(contract)
        or not observation.verified_manifest_digests
        or any(
            e.candidate_digest != candidate.digest
            or e.cohort != observation.cohort
            or e.modality == "visual"
            or e.manifest_digest not in observation.verified_manifest_digests
            for e in observation.evidence
        )
    ):
        raise ValueError("capture binding mismatch")
    if observation.static_failure:
        return SceneDecision(action="stop", reason=observation.static_failure)
    return SceneDecision(action="assess", reason="capture_verified")


def assess_and_route(contract, candidate, observation, profile=None):
    """Apply frozen scene rules, never model-suggested commands or generic routing."""
    try:
        required = project_required_criteria(contract, include_policy=policy_compatible(contract, profile))
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
        required_policy = any(c.kind == "policy" and c.requirement == "required" for c in contract.criteria)
        return SceneDecision(
            action="policy" if required_policy else "accept",
            reason="ready_for_policy" if required_policy else "all_required_established",
            assessment=assessment,
            scene_disposition="accepted" if required_policy else None,
        )
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
