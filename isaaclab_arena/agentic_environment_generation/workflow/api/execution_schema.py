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
    LocalStop,
    Query,
    QueryFailure,
    Revision,
    RunCleanup,
    SafeSchema,
    SubmissionResult,
    cleanup_view,
    command_view,
    fields,
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
class ExecutionQuery(Query):
    @strawberry.field
    def capabilities(self) -> Capabilities:
        return Capabilities(
            query_only=False,
            configured_read_store=True,
            observed_execution_readiness="guarded_synthetic_only",
            supported_queries=[
                "workflowProfiles",
                "workflowProfile",
                "workflow",
                "workflows",
                "workflowEvents",
                "workflowSubmission",
                "workflowCommand",
                "Workflow.decisions",
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
