# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Exact retained scene query values, not latest projections or execution authority.

Missing/out-of-scope and unsupported generation decisions return None. Missing
legacy causal links stay None; payload summaries are not assessment identities.
These views expose retained metadata, not fresh artifact-byte verification.
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from .policy_contracts import PolicyTrialReceipt
from .attempts import AttemptFence, ReadinessReceipt
from .contracts import FrozenModel, Hash, Identifier, WorkflowContract
from .evidence import SceneEvidenceAssessment
from .results import OwnerView
from .scene_loop import CandidateRecord, Observation, SceneDecision

# Query-only encoding allowances; writer and artifact limits are unchanged.
# _scene_json emits at most 1 MiB of valid UTF-8 JSON. Embedding that JSON
# string doubles each ASCII quote/backslash at worst (other UTF-8 is unchanged).
# CandidateRecord adds four 64-byte hashes, two <=128-byte ASCII identifiers,
# field names/null/punctuation: <4 KiB. Another 4 KiB is reserved for the
# public scope/run wrapper. Store scope strings have no writer length limit;
# a wrapper exceeding this finite query allowance is rejected, not truncated.
HISTORICAL_CANDIDATE_BYTES = 2 * 1024 * 1024 + 4096
HISTORICAL_CANDIDATE_VIEW_BYTES = HISTORICAL_CANDIDATE_BYTES + 4096
# Other retained shapes (observation, assessment, decision, intent, contract)
# do not embed scene_json and retain the existing 2 MiB query policy. In
# particular Observation's model does not bound tuple lengths on every writer
# branch: these allowances are NOT a promise to expose arbitrary writer output.


class SceneReadScope(FrozenModel):
    database: str
    deployment_id: str
    workspace_id: str


# Admission exposes only hashes and a compact scope wrapper. Intent embeds the
# contract as a JSON object (not double-escaped JSON text), plus this admission
# wrapper and lifecycle metadata. Scope strings have no legacy writer bound;
# these are finite read policies, not a claim that every legacy row fits.
SUBMISSION_INSPECTION_BYTES = 4096
RUN_INTENT_VIEW_BYTES = 2 * 1024 * 1024 + 8192


class CorruptRunRecord(ValueError):
    """Retained admission/intent cannot be decoded without repair or invention."""

    def __init__(self):
        super().__init__("Invalid retained run record")


class FrozenSubmissionInspection(FrozenModel):
    """Immutable legacy admission facts, never the current run disposition."""

    scope: SceneReadScope
    kind: Literal["SUBMIT"]
    operation_id: Identifier
    run_id: Hash
    request_digest: Hash
    accepted_contract_digest: Hash
    digest_codec: Literal["sha256-canonical-json-utf8-v1"]
    admitted_at: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    disposition: Literal["retained_admission"]
    provenance: Literal["legacy_run_record"]
    receipt_version: None
    cause_id: None


class SceneRecordView(FrozenModel):
    scope: SceneReadScope
    run_id: Identifier


class FrozenRunIntentView(SceneRecordView):
    """Frozen intent plus current lifecycle only, not an operational aggregate."""

    contract: WorkflowContract
    submission: FrozenSubmissionInspection
    state: Literal[
        "pending", "running", "cancel_requested", "cancelled", "reconciliation_required", "accepted", "stopped"
    ]
    phase: Literal["dependency_readiness", "generation", "validation", "scene"]
    run_version: Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]
    event_cursor: Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
    intent_projection_revision: Hash
    """Content hash of this intent/lifecycle view, not a complete run revision."""


class SceneCandidateView(SceneRecordView):
    candidate: CandidateRecord
    """source_id retains its original meaning; it is not always an attempt ID."""


class SceneDecisionView(SceneRecordView):
    decision_id: Identifier
    candidate_id: Hash
    decision: SceneDecision
    next_intent_id: Hash | None
    """Work reserved by this decision, never its producing attempt."""
    evidence_id: Hash | None
    selected_assessment_id: Hash | None


class SceneAssessmentView(SceneRecordView):
    assessment_id: Hash
    evidence_id: Hash
    candidate_id: Hash
    assessment: SceneEvidenceAssessment


class SceneEvidenceView(SceneRecordView):
    evidence_id: Hash
    candidate_id: Hash | None
    """Unavailable for retained observations without a FOR_CANDIDATE link."""
    observation: Observation


class CorruptSceneRecord(ValueError):
    """A retained identity or relationship is ambiguous, invalid or inconsistent."""


class CorruptCleanupRecord(ValueError):
    """A retained cleanup projection cannot be safely reconstructed."""

    def __init__(self):
        super().__init__("Invalid retained cleanup record")


class IntentCleanupView(FrozenModel):
    """Compact exact receipt references; recorded is an owner report, not an OS probe."""

    intent_id: Identifier
    kind: Literal["generation", "scene"]
    fence: AttemptFence | None
    registration_id: Identifier | None
    release_state: Literal["known_unreleased", "released"]
    cleanup_state: Literal["not_started", "unknown", "recorded", "not_applicable"]
    cleanup_evidence_ref: Identifier | None
    cleanup_observation: Literal["owned_process_group_stopped"] | None
    remote_effects: Literal["unknown"] | None
    retired_owner: OwnerView | None


class RunCleanupView(SceneRecordView):
    """Retained obligations, not OS absence, execution authority or overall cleanliness."""

    run_version: Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]
    current_scope_owner: OwnerView | None
    intents: Annotated[tuple[IntentCleanupView, ...], Field(max_length=1000)]
    projection_revision: Hash


# Whole-response query policy: one intent allowance, one cleanup allowance, and
# 8 KiB of compact projection metadata. Scene/ledger additions share this finite
# envelope; individually admissible legacy rows may exceed the combined policy
# and are rejected rather than truncated. Artifact/global canonical caps stay put.
RUN_INSPECTION_BYTES = RUN_INTENT_VIEW_BYTES + 2 * 1024 * 1024 + 8192


class ReservationTotals(FrozenModel):
    """Exact cumulative counters and decimal allowances, not actual usage."""

    model_calls: Annotated[int, Field(strict=True, ge=0)]
    model_tokens: Annotated[int, Field(strict=True, ge=0)]
    cost_ceiling_usd: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
    runtime_allowance_seconds: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
    candidates: Annotated[int, Field(strict=True, ge=0)]
    revisions: Annotated[int, Field(strict=True, ge=0)]
    realizations: Annotated[int, Field(strict=True, ge=0)]
    steps: Annotated[int, Field(strict=True, ge=0)]
    observations: Annotated[int, Field(strict=True, ge=0)]
    policy_episodes: Annotated[int, Field(strict=True, ge=0)] = 0
    policy_steps: Annotated[int, Field(strict=True, ge=0)] = 0


class InspectionBudget(FrozenModel):
    reserved: ReservationTotals
    remaining: ReservationTotals
    actual_consumption: Literal["unknown"] = "unknown"
    accounting: Literal["conservative_cumulative_reservations_no_refunds"] = (
        "conservative_cumulative_reservations_no_refunds"
    )
    runtime_accounting: Literal["cumulative_allowance_not_walltime"] = "cumulative_allowance_not_walltime"
    admitted_at: float
    deadline: float
    per_operation_ceiling_seconds: float


class RetainedReadiness(FrozenModel):
    intent_id: Identifier
    attempt_id: Identifier | None
    source: Literal["intent.readiness_json", "attempt.readiness_json"]
    receipt: ReadinessReceipt
    current_readiness: Literal["unknown"] = "unknown"
    ttl_seconds: None = None


class ActionPermissionObservation(FrozenModel):
    """Trusted check-only observation after commit, not a grant or readiness check."""

    cancel: Literal["allowed", "denied", "unknown"]
    resume: Literal["allowed", "denied", "unknown"]
    observed_at: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    provenance: Literal["trusted_check_after_retained_snapshot"] = "trusted_check_after_retained_snapshot"


class InspectionActions(FrozenModel):
    cancel_applicable: bool
    resume_branch: Literal["generation", "scene", "reconciliation"] | None
    resume_intent_id: Identifier | None
    permission_observation: ActionPermissionObservation | None = None
    command_requirements: tuple[
        Literal[
            "current_authorization", "current_readiness", "exact_local_stop", "execution_lease", "revalidate_selection"
        ],
        ...,
    ] = (
        "current_authorization",
        "current_readiness",
        "exact_local_stop",
        "execution_lease",
        "revalidate_selection",
    )


class CorruptRunInspection(ValueError):
    def __init__(self):
        super().__init__("Invalid retained run inspection")


class CandidateReference(FrozenModel):
    candidate_id: Hash
    digest: Hash
    source_id: Identifier
    original_id: Hash
    parent_id: Hash | None


class CriterionInspection(FrozenModel):
    criterion_id: Identifier
    requirement: Literal["required", "advisory"]
    verdict: Literal["established", "violated", "inconclusive", "not_assessed", "reported_only", "unsupported"]
    reported_verdicts: tuple[Literal["established", "violated", "inconclusive", "not_run"], ...]
    manifests: tuple[Hash, ...]


class SceneInspection(FrozenModel):
    candidate: CandidateReference
    decision_id: Identifier | None
    decision_identity_provenance: Literal["latest_scene_event", "unavailable_retained_causality"]
    action: Literal["accept", "observe", "repair", "capture", "assess", "policy", "stop"]
    reason: Identifier
    next_intent_id: Identifier | None
    evidence_id: Hash | None
    observation: Observation | None
    assessment_id: Hash | None
    assessment: SceneEvidenceAssessment | None
    policy_trial: PolicyTrialReceipt | None = None
    selected_assessed: bool
    assessment_status: Literal["established", "not_established", "inconclusive", "not_assessed"]
    acceptance: Literal["accepted", "not_established"]
    criteria: tuple[CriterionInspection, ...]
    limitations: tuple[Literal["unsupported_criterion_projector", "retained_metadata_not_fresh_verification"], ...]


class GenerationOutputReference(FrozenModel):
    intent_id: Identifier
    attempt_id: Identifier
    registration_id: Identifier
    contract_digest: Hash
    candidate_yaml_sha256: Hash
    candidate_json_sha256: Hash
    provenance_sha256: Hash
    manifest_sha256: Hash
    disposition: Literal["produced", "diagnostic"]
    fresh_artifact_verification: Literal["not_performed"] = "not_performed"


class RunInspection(FrozenModel):
    """One retained snapshot; no execution authority or fresh physical verification."""

    intent: FrozenRunIntentView
    cleanup: RunCleanupView
    budget: InspectionBudget
    scene: SceneInspection | None
    generation_outputs: Annotated[tuple[GenerationOutputReference, ...], Field(max_length=1000)]
    readiness: Annotated[tuple[RetainedReadiness, ...], Field(max_length=2000)]
    actions: InspectionActions
    policy_outcome: Literal[
        "not_requested", "unsupported_or_unretained", "ready_for_policy", "passed", "failed", "unknown"
    ]
    publication_outcome: Literal["not_permitted", "unknown"]
    experiment_outcome: Literal["unknown"] = "unknown"
    retained_dependencies_revision: Hash
    retained_revision: Hash
    response_revision: Hash
