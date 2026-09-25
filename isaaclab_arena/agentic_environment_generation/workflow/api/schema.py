# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Explicit query transport types; no domain model auto-exposure."""

from functools import wraps
from typing import Annotated, NewType

import strawberry
from strawberry.types import Info


def revision_value(value):
    if (
        type(value) is not str
        or not value.isascii()
        or not value.isdecimal()
        or str(int(value)) != value
        or not 0 <= int(value) <= 2**63 - 1
    ):
        raise ValueError("Invalid revision")
    return value


Revision = strawberry.scalar(NewType("Revision", str), serialize=revision_value, parse_value=revision_value)
Digest = strawberry.scalar(NewType("Digest", str), serialize=str, parse_value=str)


from enum import Enum


@strawberry.enum
class QueryFailureCode(Enum):
    NOT_FOUND = "not_found"
    OVERLOADED = "overloaded"
    INVALID_CURSOR = "invalid_cursor"
    CURSOR_SCOPE_MISMATCH = "cursor_scope_mismatch"
    CURSOR_QUERY_MISMATCH = "cursor_query_mismatch"
    REPLAY_GAP = "replay_gap"
    FUTURE_CURSOR = "future_cursor"
    UNSUPPORTED_CODEC = "unsupported_codec"
    CORRUPT = "corrupt"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    FORBIDDEN = "forbidden"


@strawberry.type
class QueryFailure:
    code: QueryFailureCode


def safe_resolver(function):
    @wraps(function)
    async def resolve(*args, **kwargs):
        from ..commands import CorruptCancelReceipt, CorruptResumeReceipt, CorruptResumeSelection
        from ..neo4j_store import ReplayGap, StoreUnavailable
        from ..paging import (
            CorruptPage,
            CursorBindingMismatch,
            CursorQueryMismatch,
            CursorVersionMismatch,
            FutureCursor,
            MalformedCursor,
            UnsupportedDecisionCoverage,
        )
        from ..profiles import CorruptProfileRecord
        from ..queries import CorruptCleanupRecord, CorruptRunInspection, CorruptRunRecord, CorruptSceneRecord
        from .resolvers import Overloaded

        try:
            return await function(*args, **kwargs)
        except Exception as error:
            classes = (
                (Overloaded, QueryFailureCode.OVERLOADED),
                (PermissionError, QueryFailureCode.FORBIDDEN),
                (MalformedCursor, QueryFailureCode.INVALID_CURSOR),
                (CursorBindingMismatch, QueryFailureCode.CURSOR_SCOPE_MISMATCH),
                (CursorQueryMismatch, QueryFailureCode.CURSOR_QUERY_MISMATCH),
                (ReplayGap, QueryFailureCode.REPLAY_GAP),
                (FutureCursor, QueryFailureCode.FUTURE_CURSOR),
                (
                    (CursorVersionMismatch, UnsupportedDecisionCoverage),
                    QueryFailureCode.UNSUPPORTED_CODEC,
                ),
                (
                    (
                        CorruptPage,
                        CorruptProfileRecord,
                        CorruptRunRecord,
                        CorruptRunInspection,
                        CorruptSceneRecord,
                        CorruptCleanupRecord,
                        CorruptCancelReceipt,
                        CorruptResumeReceipt,
                        CorruptResumeSelection,
                    ),
                    QueryFailureCode.CORRUPT,
                ),
                (StoreUnavailable, QueryFailureCode.UNAVAILABLE),
            )
            code = next(
                (code for cls, code in classes if isinstance(error, cls)),
                QueryFailureCode.UNKNOWN,
            )
            return QueryFailure(code=code)

    return resolve


@strawberry.type
class WorkflowProfile:
    id: strawberry.ID
    revision: Revision
    kind: str
    roles: list[str]
    settings_digest: Digest
    body_digest: Digest
    model: str
    endpoint: str
    billing: str
    settings: "PublicModelSettings"


@strawberry.type
class WorkflowProfileList:
    profiles: list[WorkflowProfile]


ProfileListResult = Annotated[WorkflowProfileList | QueryFailure, strawberry.union("ProfileListResult")]


def profile_view(value):
    r = value.registration
    return WorkflowProfile(
        id=strawberry.ID(r.profile_id),
        revision=str(r.revision),
        kind=r.kind,
        roles=list(r.roles),
        settings_digest=value.settings_sha256,
        body_digest=value.body_sha256,
        model=r.settings.model,
        endpoint=r.settings.endpoint,
        billing=r.settings.billing,
        settings=model_settings_view(r.settings),
    )


@strawberry.type
class NotFound:
    code: QueryFailureCode = QueryFailureCode.NOT_FOUND


Counter = strawberry.scalar(NewType("Counter", str), serialize=revision_value, parse_value=revision_value)
ProfileResult = Annotated[WorkflowProfile | NotFound | QueryFailure, strawberry.union("ProfileResult")]


@strawberry.type
class WorkflowSummary:
    id: strawberry.ID
    operation_id: strawberry.ID
    state: str
    phase: str
    version: Revision
    event_counter: Counter


@strawberry.type
class WorkflowConnection:
    semantics: str
    floor: Counter
    ceiling: Counter
    has_more: bool
    end_cursor: str | None
    event_watermark: str
    nodes: list[WorkflowSummary]


@strawberry.type
class WorkflowEvent:
    schema_version: int
    sequence: Counter
    run_id: strawberry.ID
    operation_id: strawberry.ID
    kind: str
    source_id: strawberry.ID | None
    command_kind: str | None
    command_operation_id: strawberry.ID | None


@strawberry.type
class WorkflowEventPage:
    floor: Counter
    ceiling: Counter
    has_more: bool
    resume_cursor: str
    events: list[WorkflowEvent]


RunPageResult = Annotated[WorkflowConnection | QueryFailure, strawberry.union("RunPageResult")]
EventPageResult = Annotated[WorkflowEventPage | QueryFailure, strawberry.union("EventPageResult")]


def exact_decimal(value):
    from decimal import Decimal

    if type(value) is not str or not Decimal(value).is_finite():
        raise ValueError("Invalid decimal")
    return value


DecimalString = strawberry.scalar(NewType("DecimalString", str), serialize=exact_decimal, parse_value=exact_decimal)


def positive_decimal_integer(value):
    """Validate canonical positive ASCII digits within the retained profile ceiling."""
    from ..profiles import MAX_PROFILE_BYTES

    if (
        type(value) is not str
        or not 0 < len(value) <= MAX_PROFILE_BYTES
        or not value.isascii()
        or not value.isdecimal()
        or value[0] == "0"
    ):
        raise ValueError("Invalid positive decimal integer")
    return value


PositiveDecimalInteger = strawberry.scalar(
    NewType("PositiveDecimalInteger", str),
    serialize=positive_decimal_integer,
    parse_value=positive_decimal_integer,
    description="Canonical positive ASCII decimal string, bounded by the retained profile's 16 KiB byte ceiling.",
)


@strawberry.type
class PublicRequestPolicy:
    api: str
    temperature_mode: str
    token_limit_parameter: str
    structured_output: str
    multimodal_output: str
    store: bool | None


@strawberry.type
class PublicInferencePolicy:
    id: strawberry.ID
    revision: Revision
    provider: str
    model: str
    endpoint: str
    origin: str
    support: str
    verification: str
    documentation_urls: list[str]
    request_policy: PublicRequestPolicy


@strawberry.type
class PublicWorkflowAccounting:
    version: Revision
    attested: bool
    model: str
    endpoint: str
    max_tokens: PositiveDecimalInteger | None
    max_cost_usd: DecimalString | None


@strawberry.type
class PublicModelSettings:
    model: str
    endpoint: str
    billing: str
    inference_policy: PublicInferencePolicy | None
    workflow_accounting: PublicWorkflowAccounting | None


def model_settings_view(value):
    policy = value.inference_policy
    accounting = value.workflow_accounting
    return PublicModelSettings(
        **fields(value, "model endpoint billing"),
        inference_policy=(
            None
            if policy is None
            else PublicInferencePolicy(
                **fields(policy, "id provider model endpoint origin support verification"),
                revision=str(policy.revision),
                documentation_urls=list(policy.documentation_urls),
                request_policy=PublicRequestPolicy(
                    **fields(
                        policy.request_policy,
                        "api temperature_mode token_limit_parameter structured_output multimodal_output store",
                    )
                ),
            )
        ),
        workflow_accounting=(
            None
            if accounting is None
            else PublicWorkflowAccounting(
                **fields(accounting, "attested model endpoint max_cost_usd"),
                version=str(accounting.version),
                max_tokens=None if accounting.max_tokens is None else str(accounting.max_tokens),
            )
        ),
    )


@strawberry.type
class NewSource:
    prompt: str


@strawberry.type
class ExistingSource:
    identity: strawberry.ID
    content: str


Source = Annotated[NewSource | ExistingSource, strawberry.union("Source")]


@strawberry.type
class ProfileReference:
    profile_id: strawberry.ID
    settings_digest: Digest
    billing: str | None


@strawberry.type
class ExecutionConfiguration:
    generation_model: ProfileReference | None
    assessment_model: ProfileReference | None
    runtime: ProfileReference
    database: ProfileReference
    policy: ProfileReference | None
    capture: ProfileReference | None
    seed: Counter
    timestep_seconds: DecimalString
    decimation: Counter
    dcrg: str | None


@strawberry.type
class CriterionLimit:
    operator: str
    value: DecimalString
    unit: str


@strawberry.type
class Criterion:
    id: strawberry.ID
    kind: str
    requirement: str
    producer: str
    evaluator_version: str
    modalities: list[str]
    frames: list[str]
    subjects: list[str]
    rubric: str
    start_step: Counter
    end_step: Counter
    limit: CriterionLimit


@strawberry.type
class Preservation:
    subject_id: strawberry.ID
    schema_path: str
    mode: str
    description: str | None


@strawberry.type
class Intervention:
    subject_id: strawberry.ID
    schema_path: str
    operation: str
    coordinate_frame: str
    units: str
    max_total_displacement_m: DecimalString
    description: str | None


@strawberry.type
class FrozenBudget:
    max_candidates: Counter
    max_revisions: Counter
    max_runtime_seconds: DecimalString
    max_model_calls: Counter
    max_model_tokens: Counter | None
    max_cost_usd: DecimalString | None
    max_realizations: Counter
    max_steps: Counter
    max_observations: Counter
    max_policy_episodes: Counter
    max_policy_steps: Counter
    per_operation_timeout_seconds: DecimalString
    total_deadline_seconds: DecimalString


@strawberry.type
class Effects:
    allow_paid_models: bool
    allow_runtime: bool
    allow_database_reads: bool
    allow_publication: bool
    allow_dcrg: bool
    allow_operational_writes: bool


@strawberry.type
class FrozenIntent:
    schema_version: str
    source: Source
    criteria: list[Criterion]
    preserved: list[Preservation]
    allowed_interventions: list[Intervention]
    execution: ExecutionConfiguration
    budget: FrozenBudget
    effects: Effects


@strawberry.type
class ReservationTotals:
    model_calls: Counter
    model_tokens: Counter | None
    cost_ceiling_usd: DecimalString | None
    runtime_allowance_seconds: DecimalString
    candidates: Counter
    revisions: Counter
    realizations: Counter
    steps: Counter
    observations: Counter
    policy_episodes: Counter
    policy_steps: Counter


@strawberry.type
class InspectionBudget:
    reserved: ReservationTotals
    remaining: ReservationTotals
    actual_consumption: str
    accounting: str
    runtime_accounting: str
    admitted_at: DecimalString
    deadline: DecimalString
    per_operation_ceiling_seconds: DecimalString


@strawberry.type
class Owner:
    id: strawberry.ID
    epoch: Counter
    dirty: bool


@strawberry.type
class Fence:
    run_id: strawberry.ID
    intent_id: strawberry.ID
    attempt_id: strawberry.ID
    generation: Counter
    owner_id: strawberry.ID
    owner_epoch: Counter


@strawberry.type
class IntentCleanup:
    intent_id: strawberry.ID
    kind: str
    fence: Fence | None
    registration_id: strawberry.ID | None
    release_state: str
    cleanup_state: str
    cleanup_evidence_ref: strawberry.ID | None
    cleanup_observation: str | None
    remote_effects: str | None
    retired_owner: Owner | None


@strawberry.type
class RunCleanup:
    projection_revision: Digest
    current_scope_owner: Owner | None
    intents: list[IntentCleanup]


@strawberry.type
class PermissionObservation:
    cancel: str
    resume: str
    observed_at: DecimalString
    provenance: str


@strawberry.type
class Actions:
    cancel_applicable: bool
    resume_branch: str | None
    resume_intent_id: strawberry.ID | None
    command_requirements: list[str]
    permission: PermissionObservation | None


@strawberry.type
class ReadyProfile:
    role: str
    profile_id: strawberry.ID
    settings_digest: Digest
    expected_instance_id: strawberry.ID | None
    observed_instance_id: strawberry.ID | None


@strawberry.type
class RetainedReadiness:
    intent_id: strawberry.ID
    attempt_id: strawberry.ID | None
    source: str
    contract_digest: Digest
    checked_at: DecimalString
    profiles: list[ReadyProfile]
    current_readiness: str
    ttl_seconds: DecimalString | None


@strawberry.type
class CandidateReference:
    candidate_id: strawberry.ID
    digest: Digest
    source_id: strawberry.ID
    original_id: strawberry.ID
    parent_id: strawberry.ID | None


@strawberry.type
class CriterionInspection:
    criterion_id: strawberry.ID
    requirement: str
    verdict: str
    reported_verdicts: list[str]
    manifests: list[Digest]


@strawberry.type
class PolicyBinding:
    candidate_digest: Digest
    contract_digest: Digest
    policy_artifact_digest: Digest
    policy_config_digest: Digest
    observation_interface_digest: Digest
    action_interface_digest: Digest
    transport_digest: Digest
    task_definition_digest: Digest
    evaluator_digest: Digest
    runtime_digest: Digest
    embodiment_id: strawberry.ID
    policy_adapter_id: strawberry.ID
    task_id: strawberry.ID
    evaluator_id: strawberry.ID
    instruction: str
    environment_id: strawberry.ID
    realization_id: strawberry.ID
    reset_id: strawberry.ID
    seed: Counter
    max_policy_steps: Counter
    max_episodes: Counter
    deadline_unix: DecimalString
    minimum_successes: Counter
    max_prerequisite_steps: Counter


@strawberry.type
class PolicyEpisode:
    binding_digest: Digest
    episode_id: strawberry.ID
    reset_id: strawberry.ID
    seed: Counter
    success: bool | None


@strawberry.type
class PolicyTrial:
    intent_id: strawberry.ID
    episode_records_digest: Digest
    manifest_digest: Digest
    binding: PolicyBinding
    episodes: list[PolicyEpisode]
    policy_steps: Counter
    prerequisite_steps: Counter


@strawberry.type
class SceneSummary:
    selected_candidate_reference: CandidateReference
    criteria: list[CriterionInspection]
    limitations: list[str]
    acceptance: str
    assessment_status: str
    decision_id: strawberry.ID | None
    decision_identity_provenance: str
    action: str
    reason: str
    next_intent_id: strawberry.ID | None
    evidence_id: strawberry.ID | None
    assessment_id: strawberry.ID | None
    selected_assessed: bool
    policy_trial: PolicyTrial | None
    detail_coverage: str = "compact_summary_only"


@strawberry.type
class SubmissionReceipt:
    kind: str
    operation_id: strawberry.ID
    run_id: strawberry.ID
    request_digest: Digest
    accepted_contract_digest: Digest
    digest_codec: str
    admitted_at: DecimalString
    disposition: str
    provenance: str
    receipt_version: Revision | None
    cause_id: strawberry.ID | None


from enum import Enum


@strawberry.enum
class WorkflowCommandKind(Enum):
    SUBMIT = "SUBMIT"
    CANCEL = "CANCEL"
    RESUME = "RESUME"


@strawberry.type
class DecisionReference:
    run_id: strawberry.ID
    decision_id: strawberry.ID
    record_kind: str
    detail_supported: bool


@strawberry.type
class DecisionConnection:
    coverage: str
    semantics: str
    floor: Counter
    ceiling: Counter
    has_more: bool
    end_cursor: str | None
    nodes: list[DecisionReference]


@strawberry.type
class DecisionCoverageUnavailable:
    reason: str
    floor: Counter
    ceiling: Counter


DecisionResult = Annotated[
    DecisionConnection | DecisionCoverageUnavailable | NotFound | QueryFailure,
    strawberry.union("DecisionResult"),
]


@strawberry.type
class CommandEvent:
    sequence: Counter
    kind: str
    source_id: strawberry.ID


@strawberry.type
class LocalStop:
    delivery: str
    remote_effects: str
    durable_cancellation: str


@strawberry.type
class CancellationReceipt:
    kind: str
    operation_id: strawberry.ID
    run_id: strawberry.ID
    codec_version: Revision
    receipt_version: Revision
    digest_codec: str
    payload_digest: Digest
    receipt_digest: Digest
    before_version: Revision | None
    after_version: Revision | None
    disposition: str
    reason: str | None
    first_local_stop: LocalStop
    events: list[CommandEvent]


@strawberry.type
class ResumeSelection:
    branch: str
    intent_id: strawberry.ID
    version: Revision
    contract_digest: Digest
    fence: Fence | None


@strawberry.type
class ResumeReceipt:
    kind: str
    operation_id: strawberry.ID
    run_id: strawberry.ID
    codec_version: Revision
    receipt_version: Revision
    digest_codec: str
    payload_digest: Digest
    receipt_digest: Digest
    before_version: Revision | None
    after_version: Revision | None
    disposition: str
    reason: str | None
    authorization_action: str | None
    expected_version: Revision
    renew_authorization: bool
    selection: ResumeSelection | None
    contract_digest: Digest | None
    events: list[CommandEvent]


CommandResult = Annotated[
    SubmissionReceipt | CancellationReceipt | ResumeReceipt | NotFound | QueryFailure,
    strawberry.union("CommandResult"),
]


def command_view(value):
    if value is None or value.kind == "SUBMIT":
        return submission_view(value)
    common = fields(
        value,
        "kind operation_id run_id digest_codec payload_digest receipt_digest disposition reason",
    )
    common.update(
        codec_version=str(value.codec_version),
        receipt_version=str(value.receipt_version),
        before_version=(None if value.before_version is None else str(value.before_version)),
        after_version=None if value.after_version is None else str(value.after_version),
        events=[CommandEvent(sequence=str(e.sequence), kind=e.kind, source_id=e.source_id) for e in value.events],
    )
    if value.kind == "CANCEL":
        return CancellationReceipt(
            **common,
            first_local_stop=LocalStop(
                **fields(
                    value.first_local_stop,
                    "delivery remote_effects durable_cancellation",
                )
            ),
        )
    from ..commands import ResumePayload

    payload = ResumePayload.model_validate_json(value.payload_json)
    s = value.selection
    return ResumeReceipt(
        **common,
        authorization_action=value.authorization_action,
        expected_version=str(payload.expectedVersion),
        renew_authorization=payload.renewAuthorization,
        contract_digest=value.contract_digest,
        selection=(
            None
            if s is None
            else ResumeSelection(
                branch=s.branch,
                intent_id=s.intent_id,
                version=str(s.version),
                contract_digest=s.contract_digest,
                fence=fence_view(s.fence),
            )
        ),
    )


@strawberry.enum
class WorkflowAction(Enum):
    CANCEL = "cancel"
    RESUME = "resume"


@strawberry.type
class GenerationOutputReference:
    intent_id: strawberry.ID
    attempt_id: strawberry.ID
    registration_id: strawberry.ID
    contract_digest: Digest
    candidate_yaml_sha256: Digest
    candidate_json_sha256: Digest
    provenance_sha256: Digest
    manifest_sha256: Digest
    disposition: str
    fresh_artifact_verification: str


@strawberry.type
class Workflow:
    id: strawberry.ID
    operation_id: strawberry.ID
    version: Revision
    event_counter: Counter
    state: str
    phase: str
    retained_revision: Digest
    response_revision: Digest
    retained_dependencies_revision: Digest
    policy_outcome: str
    publication_outcome: str
    experiment_outcome: str
    frozen_intent: FrozenIntent
    budget: InspectionBudget
    cleanup: RunCleanup
    actions: Actions
    available_actions: list[WorkflowAction]
    scene: SceneSummary | None
    generation_outputs: list[GenerationOutputReference]
    readiness: list[RetainedReadiness]
    retained_assessment_json: str | None

    @strawberry.field
    @safe_resolver
    async def decisions(self, info: Info, first: int, after: str | None = None) -> DecisionResult:
        from ..paging import DecisionCoverageUnavailable as Unavailable

        page = await info.context.call("list_decisions", str(self.id), first=first, after=after)
        if page is None:
            return NotFound()
        if isinstance(page, Unavailable):
            return DecisionCoverageUnavailable(reason=page.reason, floor=page.floor, ceiling=page.ceiling)
        return DecisionConnection(
            coverage=page.coverage,
            semantics=page.semantics,
            floor=page.floor,
            ceiling=page.ceiling,
            has_more=page.has_more,
            end_cursor=page.end_cursor,
            nodes=[
                DecisionReference(
                    run_id=d.run_id,
                    decision_id=d.decision_id,
                    record_kind=d.record_kind,
                    detail_supported=False,
                )
                for d in page.decisions
            ],
        )


WorkflowResult = Annotated[Workflow | NotFound | QueryFailure, strawberry.union("WorkflowResult")]
SubmissionResult = Annotated[SubmissionReceipt | NotFound | QueryFailure, strawberry.union("SubmissionResult")]


def fields(value, names, *, text=False):
    """Project only the literal reviewed field list supplied by the mapper."""
    return {
        name: str(getattr(value, name)) if text and getattr(value, name) is not None else getattr(value, name)
        for name in names.split()
    }


def profile_reference(value):
    if value is None:
        return None
    return ProfileReference(
        profile_id=value.profile_id,
        settings_digest=value.settings_sha256,
        billing=getattr(value, "billing", None),
    )


def frozen_intent(value):
    e = value.execution
    return FrozenIntent(
        schema_version=value.schema_version,
        source=(
            NewSource(prompt=value.source.prompt)
            if value.source.kind == "new"
            else ExistingSource(identity=value.source.identity, content=value.source.content)
        ),
        execution=ExecutionConfiguration(
            generation_model=profile_reference(e.generation_model),
            assessment_model=profile_reference(e.assessment_model),
            runtime=profile_reference(e.runtime),
            database=profile_reference(e.database),
            policy=profile_reference(e.policy),
            capture=profile_reference(e.capture),
            seed=str(e.seed),
            timestep_seconds=str(e.timestep_seconds),
            decimation=str(e.decimation),
            dcrg=None,
        ),
        criteria=[
            Criterion(
                id=c.criterion_id,
                kind=c.kind,
                requirement=c.requirement,
                producer=c.evidence_producer,
                evaluator_version=c.evaluator_version,
                modalities=list(c.required_modalities),
                frames=list(c.coordinate_frames),
                subjects=list(c.subjects),
                rubric=c.rubric,
                start_step=str(c.observation_window.start_step),
                end_step=str(c.observation_window.end_step),
                limit=CriterionLimit(
                    operator=c.limit.operator,
                    value=str(c.limit.value),
                    unit=c.limit.unit,
                ),
            )
            for c in value.criteria
        ],
        preserved=[Preservation(**fields(p, "subject_id schema_path mode description")) for p in value.preserved],
        allowed_interventions=[
            Intervention(
                **fields(
                    i,
                    "subject_id schema_path operation coordinate_frame units description",
                ),
                max_total_displacement_m=str(i.max_total_displacement_m),
            )
            for i in value.allowed_interventions
        ],
        budget=FrozenBudget(
            **fields(
                value.budget,
                "max_candidates max_revisions max_runtime_seconds max_model_calls max_model_tokens max_cost_usd"
                " max_realizations max_steps max_observations max_policy_episodes max_policy_steps"
                " per_operation_timeout_seconds total_deadline_seconds",
                text=True,
            )
        ),
        effects=Effects(
            **fields(
                value.effects,
                "allow_paid_models allow_runtime allow_database_reads allow_publication allow_dcrg"
                " allow_operational_writes",
            )
        ),
    )


def owner_view(value):
    return None if value is None else Owner(id=value.owner_id, epoch=str(value.owner_epoch), dirty=value.dirty)


def fence_view(value):
    return (
        None
        if value is None
        else Fence(
            **fields(value, "run_id intent_id attempt_id owner_id"),
            generation=str(value.generation),
            owner_epoch=str(value.owner_epoch),
        )
    )


def cleanup_view(value):
    return RunCleanup(
        projection_revision=value.projection_revision,
        current_scope_owner=owner_view(value.current_scope_owner),
        intents=[
            IntentCleanup(
                **fields(
                    i,
                    "intent_id kind registration_id release_state cleanup_state cleanup_evidence_ref"
                    " cleanup_observation remote_effects",
                ),
                fence=fence_view(i.fence),
                retired_owner=owner_view(i.retired_owner),
            )
            for i in value.intents
        ],
    )


def submission_view(value):
    return (
        NotFound()
        if value is None
        else SubmissionReceipt(
            **fields(
                value,
                "kind operation_id run_id request_digest accepted_contract_digest digest_codec disposition provenance"
                " receipt_version cause_id",
            ),
            admitted_at=str(value.admitted_at),
        )
    )


def policy_trial_view(value):
    """Project already validated retained trial facts without executing or deciding."""
    if value is None:
        return None
    return PolicyTrial(
        **fields(value, "intent_id episode_records_digest manifest_digest"),
        policy_steps=str(value.policy_steps),
        prerequisite_steps=str(value.prerequisite_steps),
        binding=PolicyBinding(
            **fields(
                value.binding,
                "candidate_digest contract_digest policy_artifact_digest policy_config_digest"
                " observation_interface_digest action_interface_digest transport_digest task_definition_digest"
                " evaluator_digest runtime_digest embodiment_id policy_adapter_id task_id evaluator_id instruction"
                " environment_id realization_id reset_id seed max_policy_steps max_episodes deadline_unix"
                " minimum_successes max_prerequisite_steps",
                text=True,
            )
        ),
        episodes=[
            PolicyEpisode(**fields(e, "binding_digest episode_id reset_id success"), seed=str(e.seed))
            for e in value.episodes
        ],
    )


def workflow_view(value):
    if value is None:
        return NotFound()
    b = value.budget
    a = value.actions
    p = a.permission_observation
    totals = (
        "model_calls model_tokens cost_ceiling_usd runtime_allowance_seconds candidates revisions realizations steps"
        " observations policy_episodes policy_steps"
    )
    return Workflow(
        id=value.intent.run_id,
        operation_id=value.intent.submission.operation_id,
        version=str(value.intent.run_version),
        event_counter=str(value.intent.event_cursor),
        state=value.intent.state,
        phase=value.intent.phase,
        **fields(
            value,
            "retained_revision response_revision retained_dependencies_revision policy_outcome publication_outcome"
            " experiment_outcome",
        ),
        frozen_intent=frozen_intent(value.intent.contract),
        retained_assessment_json=value.retained_assessment_json,
        available_actions=[
            action
            for action, allowed in (
                (
                    WorkflowAction.CANCEL,
                    p is not None and p.cancel == "allowed" and a.cancel_applicable,
                ),
                (
                    WorkflowAction.RESUME,
                    p is not None and p.resume == "allowed" and a.resume_branch is not None,
                ),
            )
            if allowed
        ],
        cleanup=cleanup_view(value.cleanup),
        generation_outputs=[
            GenerationOutputReference(
                **fields(
                    output,
                    "intent_id attempt_id registration_id contract_digest candidate_yaml_sha256"
                    " candidate_json_sha256 provenance_sha256 manifest_sha256 disposition fresh_artifact_verification",
                )
            )
            for output in value.generation_outputs
        ],
        budget=InspectionBudget(
            reserved=ReservationTotals(**fields(b.reserved, totals, text=True)),
            remaining=ReservationTotals(**fields(b.remaining, totals, text=True)),
            **fields(b, "actual_consumption accounting runtime_accounting"),
            **fields(b, "admitted_at deadline per_operation_ceiling_seconds", text=True),
        ),
        actions=Actions(
            **fields(a, "cancel_applicable resume_branch resume_intent_id"),
            command_requirements=list(a.command_requirements),
            permission=(
                None
                if p is None
                else PermissionObservation(
                    **fields(p, "cancel resume provenance"),
                    observed_at=str(p.observed_at),
                )
            ),
        ),
        scene=(
            None
            if value.scene is None
            else SceneSummary(
                selected_candidate_reference=CandidateReference(
                    **fields(
                        value.scene.candidate,
                        "candidate_id digest source_id original_id parent_id",
                    )
                ),
                criteria=[
                    CriterionInspection(
                        **fields(c, "criterion_id requirement verdict"),
                        reported_verdicts=list(c.reported_verdicts),
                        manifests=list(c.manifests),
                    )
                    for c in value.scene.criteria
                ],
                limitations=list(value.scene.limitations),
                policy_trial=policy_trial_view(value.scene.policy_trial),
                **fields(
                    value.scene,
                    "acceptance assessment_status decision_id decision_identity_provenance action reason next_intent_id"
                    " evidence_id assessment_id selected_assessed",
                ),
            )
        ),
        readiness=[
            RetainedReadiness(
                **fields(r, "intent_id attempt_id source current_readiness"),
                contract_digest=r.receipt.contract_digest,
                checked_at=str(r.receipt.checked_at),
                ttl_seconds=None,
                profiles=[
                    ReadyProfile(
                        role=p.role,
                        profile_id=p.profile_id,
                        settings_digest=p.settings_sha256,
                        expected_instance_id=p.expected_instance_id,
                        observed_instance_id=p.observed_instance_id,
                    )
                    for p in r.receipt.profiles
                ],
            )
            for r in value.readiness
        ],
    )


@strawberry.type
class Capabilities:
    query_only: bool
    supported_queries: list[str]
    unsupported: list[str]
    configured_read_store: bool
    observed_execution_readiness: str


@strawberry.enum
class ArtifactKind(Enum):
    PRIOR = "prior"
    CANDIDATE = "candidate"
    GENERATION = "generation"
    EVIDENCE = "evidence"


@strawberry.enum
class ArtifactName(Enum):
    PRIOR_JSON = "prior.json"
    CANDIDATE_JSON = "candidate.json"
    CANDIDATE_YAML = "candidate.yaml"
    PROVENANCE_JSON = "provenance.json"
    EVIDENCE_JSON = "evidence.json"


@strawberry.type
class ArtifactReference:
    run_id: strawberry.ID
    kind: ArtifactKind
    reference_id: strawberry.ID
    name: ArtifactName
    sha256: str
    total_bytes: Counter


@strawberry.type
class ArtifactChunk(ArtifactReference):
    offset: Counter
    length: Counter
    eof: bool
    data: str
    encoding: str = "base64"


@strawberry.type
class PriorDetail:
    run_id: strawberry.ID
    contract_digest: str
    manifest_digest: str
    status: str
    context_sha256: str
    prior_count: int
    warnings: list[str]
    artifacts: list[ArtifactReference]


PriorResult = Annotated[PriorDetail | NotFound | QueryFailure, strawberry.union("PriorResult")]
ArtifactResult = Annotated[ArtifactChunk | NotFound | QueryFailure, strawberry.union("ArtifactResult")]


@strawberry.type
class CandidateDetail:
    run_id: strawberry.ID
    candidate_id: strawberry.ID
    original_id: strawberry.ID
    parent_id: strawberry.ID | None
    source_id: strawberry.ID
    digest: str
    contract_digest: str
    artifacts: list[ArtifactReference]


CandidateResult = Annotated[CandidateDetail | NotFound | QueryFailure, strawberry.union("CandidateResult")]


@strawberry.type
class GenerationDetail:
    run_id: strawberry.ID
    intent_id: strawberry.ID
    attempt_id: strawberry.ID
    generation: Counter
    owner_id: strawberry.ID
    owner_epoch: Counter
    registration_id: strawberry.ID
    contract_digest: str
    manifest_digest: str
    disposition: str
    artifacts: list[ArtifactReference]


GenerationResult = Annotated[GenerationDetail | NotFound | QueryFailure, strawberry.union("GenerationResult")]


@strawberry.type
class RetainedEvidenceCohort:
    realization_id: str
    reset_id: str
    environment_id: str
    window_id: str
    frame_id: str
    contract_digest: str
    profile_digest: str


@strawberry.type
class CriterionEvidenceDetail:
    criterion_id: str
    criterion_digest: str
    producer_id: str
    observed_coordinate_frames: list[str]
    observed_step_window: list[Counter]
    subject_ids: list[str]
    modality: str
    evaluator_version: str
    rubric_id: str
    candidate_digest: str
    cohort: RetainedEvidenceCohort
    manifest_digest: str
    verdict: str
    limitations: list[str]


@strawberry.type
class EvidenceArtifactSelector:
    kind: ArtifactKind
    reference_id: strawberry.ID
    manifest_digest: str


@strawberry.type
class EvidenceDetail:
    run_id: strawberry.ID
    evidence_id: strawberry.ID
    candidate_id: strawberry.ID | None
    cohort: RetainedEvidenceCohort
    entries: list[CriterionEvidenceDetail]
    verified_manifest_digests: list[str]
    static_failure: str | None
    artifact_selectors: list[EvidenceArtifactSelector]
    fresh_artifact_verification: str = "not_performed"


@strawberry.type
class ArtifactInventory:
    run_id: strawberry.ID
    kind: ArtifactKind
    reference_id: strawberry.ID
    manifest_digest: str | None
    artifacts: list[ArtifactReference]
    fresh_artifact_verification: str = "verified_for_this_read"


EvidenceResult = Annotated[EvidenceDetail | NotFound | QueryFailure, strawberry.union("EvidenceResult")]
ArtifactInventoryResult = Annotated[
    ArtifactInventory | NotFound | QueryFailure, strawberry.union("ArtifactInventoryResult")
]


@strawberry.type
class AssessmentDetail:
    run_id: strawberry.ID
    assessment_id: strawberry.ID
    candidate_id: strawberry.ID | None
    evidence_id: strawberry.ID | None
    status: str
    missing_ids: list[str]
    failed_ids: list[str]
    historical_conflict_ids: list[str]
    limitations: list[str]


AssessmentResult = Annotated[AssessmentDetail | NotFound | QueryFailure, strawberry.union("AssessmentResult")]


def artifact_references(bundle):
    from ..artifacts import digest

    return [
        ArtifactReference(
            run_id=bundle.run_id,
            kind=ArtifactKind(bundle.kind),
            reference_id=bundle.reference_id,
            name=ArtifactName(name),
            sha256=digest(raw),
            total_bytes=str(len(raw)),
        )
        for name, raw in sorted(bundle.files.items())
    ]


@strawberry.type
class Query:
    @strawberry.field
    @safe_resolver
    async def workflow_assessment(
        self,
        info: Info,
        run_id: strawberry.ID,
        assessment_id: strawberry.ID,
    ) -> AssessmentResult:
        view = await info.context.call("read_scene_assessment", str(assessment_id))
        if view is None:
            return NotFound()
        if view.run_id != str(run_id) or view.assessment_id != str(assessment_id):
            raise PermissionError("Scoped assessment identity required")
        assessment = view.assessment
        return AssessmentDetail(
            **fields(view, "run_id assessment_id candidate_id evidence_id"),
            status=assessment.status,
            missing_ids=list(assessment.missing_ids),
            failed_ids=list(assessment.failed_ids),
            historical_conflict_ids=list(assessment.historical_conflict_ids),
            limitations=list(assessment.limitations),
        )

    @strawberry.field
    @safe_resolver
    async def workflow_evidence(
        self,
        info: Info,
        run_id: strawberry.ID,
        evidence_id: strawberry.ID,
    ) -> EvidenceResult:
        view = await info.context.call("read_scene_evidence", str(evidence_id))
        if view is None:
            return NotFound()
        if view.run_id != str(run_id) or view.evidence_id != str(evidence_id):
            raise PermissionError("Scoped evidence identity required")
        observation = view.observation
        manifests = sorted(
            {entry.manifest_digest for entry in observation.evidence} & set(observation.verified_manifest_digests)
        )
        if len(manifests) > 16:
            raise ValueError("Retained artifact selection bound exceeded")
        return EvidenceDetail(
            run_id=view.run_id,
            evidence_id=view.evidence_id,
            candidate_id=view.candidate_id,
            cohort=RetainedEvidenceCohort(**observation.cohort.model_dump()),
            entries=[
                CriterionEvidenceDetail(
                    **fields(
                        entry,
                        "criterion_id criterion_digest producer_id modality evaluator_version rubric_id"
                        " candidate_digest manifest_digest verdict",
                    ),
                    observed_coordinate_frames=list(entry.observed_coordinate_frames),
                    observed_step_window=[str(step) for step in entry.observed_step_window],
                    subject_ids=list(entry.subject_ids),
                    cohort=RetainedEvidenceCohort(**entry.cohort.model_dump()),
                    limitations=list(entry.limitations),
                )
                for entry in observation.evidence
            ],
            verified_manifest_digests=list(observation.verified_manifest_digests),
            static_failure=observation.static_failure,
            artifact_selectors=[
                EvidenceArtifactSelector(
                    kind=ArtifactKind.EVIDENCE, reference_id=view.evidence_id + manifest, manifest_digest=manifest
                )
                for manifest in manifests
            ],
        )

    @strawberry.field
    @safe_resolver
    async def workflow_artifacts(
        self,
        info: Info,
        run_id: strawberry.ID,
        kind: ArtifactKind,
        reference_id: strawberry.ID,
    ) -> ArtifactInventoryResult:
        bundle = await info.context.call("read_retained_bundle", str(run_id), kind.value, str(reference_id))
        if bundle is None:
            return NotFound()
        return ArtifactInventory(
            run_id=bundle.run_id,
            kind=ArtifactKind(bundle.kind),
            reference_id=bundle.reference_id,
            manifest_digest=bundle.manifest_digest,
            artifacts=artifact_references(bundle),
        )

    @strawberry.field
    @safe_resolver
    async def workflow_generation(
        self,
        info: Info,
        run_id: strawberry.ID,
        attempt_id: strawberry.ID,
    ) -> GenerationResult:
        bundle = await info.context.call("read_retained_bundle", str(run_id), "generation", str(attempt_id))
        if bundle is None:
            return NotFound()
        receipt = bundle.record
        return GenerationDetail(
            **fields(receipt.fence, "run_id intent_id attempt_id owner_id"),
            generation=str(receipt.fence.generation),
            owner_epoch=str(receipt.fence.owner_epoch),
            registration_id=receipt.registration.registration_id,
            contract_digest=receipt.contract_digest,
            manifest_digest=receipt.manifest_sha256,
            disposition=receipt.disposition,
            artifacts=artifact_references(bundle),
        )

    @strawberry.field
    @safe_resolver
    async def workflow_candidate(
        self,
        info: Info,
        run_id: strawberry.ID,
        candidate_id: strawberry.ID,
    ) -> CandidateResult:
        bundle = await info.context.call("read_retained_bundle", str(run_id), "candidate", str(candidate_id))
        if bundle is None:
            return NotFound()
        return CandidateDetail(
            **fields(bundle.record, "run_id candidate_id original_id parent_id source_id digest"),
            contract_digest=bundle.contract_digest,
            artifacts=artifact_references(bundle),
        )

    @strawberry.field
    @safe_resolver
    async def workflow_prior(self, info: Info, run_id: strawberry.ID) -> PriorResult:
        bundle = await info.context.call("read_retained_bundle", str(run_id), "prior", str(run_id))
        if bundle is None:
            return NotFound()
        return PriorDetail(
            run_id=bundle.run_id,
            contract_digest=bundle.contract_digest,
            manifest_digest=bundle.manifest_digest,
            status=bundle.record["status"],
            context_sha256=bundle.record["context_sha256"],
            prior_count=len(bundle.record["priors"]),
            warnings=bundle.record["warnings"],
            artifacts=artifact_references(bundle),
        )

    @strawberry.field
    @safe_resolver
    async def workflow_artifact(
        self,
        info: Info,
        run_id: strawberry.ID,
        kind: ArtifactKind,
        reference_id: strawberry.ID,
        name: ArtifactName,
        expected_sha256: str,
        offset: Counter,
        limit: int,
    ) -> ArtifactResult:
        value = await info.context.call(
            "read_artifact_chunk",
            str(run_id),
            kind.value,
            str(reference_id),
            name.value,
            expected_sha256,
            int(offset),
            limit,
        )
        if value is None:
            return NotFound()
        return ArtifactChunk(
            **dict(
                value,
                kind=ArtifactKind(value["kind"]),
                name=ArtifactName(value["name"]),
                total_bytes=str(value["total_bytes"]),
                offset=str(value["offset"]),
                length=str(value["length"]),
            )
        )

    @strawberry.field
    def capabilities(self) -> Capabilities:
        return Capabilities(
            query_only=True,
            configured_read_store=True,
            observed_execution_readiness="not_checked",
            supported_queries=[
                "workflowProfiles",
                "workflowProfile",
                "workflow",
                "workflows",
                "workflowEvents",
                "workflowSubmission",
                "workflowCommand",
                "workflowPrior",
                "workflowArtifact",
                "workflowCandidate",
                "workflowGeneration",
                "workflowEvidence",
                "workflowArtifacts",
                "workflowAssessment",
                "Workflow.decisions",
            ],
            unsupported=[
                "execution",
                "native",
                "policy",
                "publication",
                "other_history",
            ],
        )

    @strawberry.field
    @safe_resolver
    async def workflow_command(
        self, info: Info, kind: WorkflowCommandKind, operation_id: strawberry.ID
    ) -> CommandResult:
        return command_view(await info.context.call("read_command", kind.value, str(operation_id)))

    @strawberry.field
    @safe_resolver
    async def workflow(self, info: Info, id: strawberry.ID) -> WorkflowResult:
        return workflow_view(await info.context.call("read_run_inspection", str(id)))

    @strawberry.field
    @safe_resolver
    async def workflow_submission(self, info: Info, operation_id: strawberry.ID) -> SubmissionResult:
        return submission_view(await info.context.call("read_submission", str(operation_id)))

    @strawberry.field
    @safe_resolver
    async def workflow_profile(self, info: Info, id: strawberry.ID, revision: Revision) -> ProfileResult:
        row = await info.context.call("read_profile", str(id), int(revision))
        return NotFound() if row is None else profile_view(row)

    @strawberry.field
    @safe_resolver
    async def workflows(self, info: Info, first: int, after: str | None = None) -> RunPageResult:
        page = await info.context.call("list_runs", first=first, after=after)
        return WorkflowConnection(
            semantics=page.semantics,
            floor=page.floor,
            ceiling=page.ceiling,
            has_more=page.has_more,
            end_cursor=page.end_cursor,
            event_watermark=page.event_watermark,
            nodes=[
                WorkflowSummary(
                    id=row.run_id,
                    operation_id=row.operation_id,
                    state=row.state,
                    phase=row.phase,
                    version=row.run_version,
                    event_counter=row.event_cursor,
                )
                for row in page.runs
            ],
        )

    @strawberry.field
    @safe_resolver
    async def workflow_events(self, info: Info, first: int, after: str | None = None) -> EventPageResult:
        page = await info.context.call("read_scope_events", first=first, after=after)
        return WorkflowEventPage(
            floor=page.floor,
            ceiling=page.ceiling,
            has_more=page.has_more,
            resume_cursor=page.resume_cursor,
            events=[
                WorkflowEvent(
                    schema_version=row.schema_version,
                    sequence=row.sequence,
                    run_id=row.run_id,
                    operation_id=row.operation_id,
                    kind=row.kind,
                    source_id=row.source_id,
                    command_kind=row.command_kind,
                    command_operation_id=row.command_operation_id,
                )
                for row in page.events
            ],
        )

    @strawberry.field
    @safe_resolver
    async def workflow_profiles(self, info: Info) -> ProfileListResult:
        rows = await info.context.call("list_profiles")
        return WorkflowProfileList(profiles=[profile_view(row) for row in rows])


class SafeSchema(strawberry.Schema):
    def process_errors(self, errors, execution_context=None):
        """Transport returns fixed diagnostics; never log GraphQL input or traces."""


schema = SafeSchema(query=Query)
