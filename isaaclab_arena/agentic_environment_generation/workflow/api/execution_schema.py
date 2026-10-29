# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit installed controls; domain codecs and handlers retain their bounds."""

from typing import Annotated, NewType

import strawberry
from strawberry.types import Info

from ..contracts import canonical_json, parse_contract
from .schema import (
    CancellationReceipt,
    Capabilities,
    CommandResult,
    Counter,
    Digest,
    FrozenIntent,
    LocalStop,
    PredicateParameters,
    Query,
    QueryFailure,
    Revision,
    RunCleanup,
    SafeSchema,
    SubmissionResult,
    cleanup_view,
    command_view,
    criterion_parameters,
    fields,
    frozen_intent,
    safe_resolver,
    submission_view,
)


def contract_value(value):
    if type(value) is not str:
        raise ValueError("Contract text required")
    return canonical_json(parse_contract(value))


WorkflowContractJSON = strawberry.scalar(
    NewType("WorkflowContractJSON", str),
    serialize=str,
    parse_value=contract_value,
    description="Bounded strict workflow contract JSON text, not arbitrary JSON.",
)


@strawberry.type
class WorkflowInspection:
    operation_id: strawberry.ID
    mode: str
    contract_digest: Digest
    selection_digest: Digest
    settings_digest: Digest
    catalogue_digest: Digest
    source_kind: str
    source_bytes_sha256: Digest | None
    canonical_candidate_sha256: Digest | None
    validated_semantic_sha256: Digest | None
    initial_generation_required: bool
    prior_status: str
    frozen: FrozenIntent
    admitted: bool
    provider_sends: Counter
    native_releases: Counter
    live_admission_or_child_execution_proven: bool


InspectionResult = Annotated[WorkflowInspection | QueryFailure, strawberry.union("InspectionResult")]


def numeric_selection_value(value):
    from ..derived_assessment import NumericReassessmentSelection
    from ..scene_evidence_artifacts import canonical

    if type(value) is not str or len(value.encode("utf-8")) > 65536:
        raise ValueError("Bounded retained numeric selection required")
    selected = NumericReassessmentSelection.model_validate_json(value)
    return canonical(selected.model_dump(mode="json")).decode("utf-8")


NumericSelectionJSON = strawberry.scalar(
    NewType("NumericSelectionJSON", str), serialize=str, parse_value=numeric_selection_value
)


@strawberry.type
class NumericDerivedResult:
    operation_id: strawberry.ID
    selection_digest: Digest
    run_id: strawberry.ID
    evidence_id: Digest
    candidate_id: Digest
    source_manifest_digest: Digest
    purpose: str
    validation_contract_digest: Digest | None
    disposition: str
    reason: str | None
    assessment_id: Digest | None
    manifest_digest: Digest | None
    criterion_id: str
    evaluator_version: str
    parameters: PredicateParameters | None
    threshold_operator: str
    threshold_value: str
    threshold_unit: str
    verdict: str | None
    conflict: bool | None
    limitations: list[str]
    original_run_version: Revision
    provider_sends: Counter
    native_releases: Counter
    original_run_amended: bool


NumericDerivedOutcome = Annotated[NumericDerivedResult | QueryFailure, strawberry.union("NumericDerivedOutcome")]


def numeric_derived_view(value):
    if value is None:
        return None
    evidence = value.evidence
    return NumericDerivedResult(
        **fields(
            value,
            "operation_id selection_digest run_id evidence_id candidate_id source_manifest_digest purpose "
            "validation_contract_digest disposition reason assessment_id manifest_digest original_run_amended",
        ),
        criterion_id=value.criterion.criterion_id,
        evaluator_version=value.criterion.evaluator_version,
        parameters=criterion_parameters(value.criterion.parameters),
        threshold_operator=value.criterion.limit.operator,
        threshold_value=str(value.criterion.limit.value),
        threshold_unit=value.criterion.limit.unit,
        verdict=None if evidence is None else evidence.verdict,
        conflict=None if evidence is None else evidence.conflict,
        limitations=[] if evidence is None else list(evidence.limitations),
        original_run_version=Revision(str(value.original_run_version)),
        provider_sends=Counter(str(value.provider_sends)),
        native_releases=Counter(str(value.native_releases)),
    )


@strawberry.type
class NativeSupervisionProgress:
    run_id: strawberry.ID
    intent_id: strawberry.ID
    lease_generation: Counter
    credential_generation: Counter
    expires_at: str
    credential_expires_at: str
    allocation_digest: Digest
    acknowledged_lease_digest: Digest
    expired: bool
    cleanup_verified: bool = False
    current_workload_authority_proven: bool = False


SupervisionOutcome = Annotated[NativeSupervisionProgress | QueryFailure, strawberry.union("SupervisionOutcome")]


@strawberry.type
class ExecutionQuery(Query):
    @strawberry.field
    @safe_resolver
    async def workflow_supervision(
        self, info: Info, run_id: strawberry.ID, intent_id: strawberry.ID
    ) -> SupervisionOutcome | None:
        import time

        value = await info.context.supervision(str(run_id), str(intent_id))
        if value is None:
            return None
        lease, ack = value["lease"], value["last_acknowledgement"]
        return NativeSupervisionProgress(
            run_id=run_id,
            intent_id=intent_id,
            lease_generation=Counter(str(lease["generation"])),
            credential_generation=Counter(str(lease["credential_generation"])),
            expires_at=str(lease["expires_at"]),
            credential_expires_at=str(lease["credential_expires_at"]),
            allocation_digest=Digest(lease["allocation_digest"]),
            acknowledged_lease_digest=Digest(ack["lease_sha256"]),
            expired=time.time() >= lease["expires_at"],
        )

    @strawberry.field
    @safe_resolver
    async def workflow_numeric_assessment(
        self, info: Info, operation_id: strawberry.ID
    ) -> NumericDerivedOutcome | None:
        return numeric_derived_view(await info.context.reassess_numeric(str(operation_id)))

    @strawberry.field
    @safe_resolver
    async def workflow_inspection(self, info: Info, contract: WorkflowContractJSON) -> InspectionResult:
        value = await info.context.inspect(str(contract))
        source = value["source"]
        return WorkflowInspection(
            **{
                key: value[key]
                for key in (
                    "operation_id",
                    "mode",
                    "contract_digest",
                    "selection_digest",
                    "settings_digest",
                    "catalogue_digest",
                    "prior_status",
                    "admitted",
                    "live_admission_or_child_execution_proven",
                )
            },
            source_kind=source["kind"],
            initial_generation_required=source["initial_generation_required"],
            source_bytes_sha256=source.get("source_bytes_sha256"),
            canonical_candidate_sha256=source.get("canonical_candidate_sha256"),
            validated_semantic_sha256=source.get("validated_semantic_sha256"),
            provider_sends=str(value["provider_sends"]),
            native_releases=str(value["native_releases"]),
            frozen=frozen_intent(parse_contract(str(contract))),
        )

    @strawberry.field
    def capabilities(self, info: Info) -> Capabilities:
        full_scene = getattr(info.context.owner, "installed_mode", None) == "full-scene-workflow-v1"
        return Capabilities(
            query_only=False,
            configured_read_store=True,
            observed_execution_readiness="installed_non_sending_only" if full_scene else "guarded_synthetic_only",
            supported_queries=[
                "workflowProfiles",
                "workflowProfile",
                "workflow",
                "workflows",
                "workflowEvents",
                "workflowSubmission",
                "workflowCommand",
                "Workflow.decisions",
                *(["workflowInspection"] if full_scene else []),
                *(["workflowNumericAssessment", "reassessWorkflowNumeric"] if full_scene else []),
                *(["workflowSupervision"] if full_scene else []),
            ],
            unsupported=[
                "native",
                "policy",
                "publication",
                "other_history",
            ],
        )


@strawberry.type
class CancellationResult:
    local_stop: LocalStop
    durable: str
    receipt: CancellationReceipt | None
    cleanup_status: str
    cleanup: RunCleanup | None
    remote_effects: str


CancellationOutcome = Annotated[CancellationResult | QueryFailure, strawberry.union("CancellationOutcome")]


@strawberry.type
class Mutation:
    @strawberry.mutation
    @safe_resolver
    async def reassess_workflow_numeric(
        self, info: Info, operation_id: strawberry.ID, selection: NumericSelectionJSON
    ) -> NumericDerivedOutcome:
        import json

        return numeric_derived_view(await info.context.reassess_numeric(str(operation_id), json.loads(str(selection))))

    @strawberry.mutation
    @safe_resolver
    async def resume_workflow(
        self,
        info: Info,
        operation_id: strawberry.ID,
        run_id: strawberry.ID,
        expected_version: Revision,
        renew_authorization: bool,
    ) -> CommandResult:
        return command_view(
            await info.context.resume(
                str(operation_id),
                {
                    "runId": str(run_id),
                    "expectedVersion": int(expected_version),
                    "renewAuthorization": renew_authorization,
                },
            )
        )

    @strawberry.mutation
    @safe_resolver
    async def submit_workflow(
        self, info: Info, operation_id: strawberry.ID, contract: WorkflowContractJSON
    ) -> SubmissionResult:
        return submission_view(await info.context.submit(str(operation_id), str(contract)))

    @strawberry.mutation
    @safe_resolver
    async def cancel_workflow(
        self, info: Info, operation_id: strawberry.ID, run_id: strawberry.ID
    ) -> CancellationOutcome:
        result = await info.context.cancel(str(operation_id), str(run_id))
        return CancellationResult(
            local_stop=LocalStop(**fields(result.local_stop, "delivery remote_effects durable_cancellation")),
            durable=result.durable,
            receipt=None if result.receipt is None else command_view(result.receipt),
            cleanup_status=result.cleanup_status,
            cleanup=None if result.cleanup is None else cleanup_view(result.cleanup),
            remote_effects=result.remote_effects,
        )


schema = SafeSchema(query=ExecutionQuery, mutation=Mutation)
