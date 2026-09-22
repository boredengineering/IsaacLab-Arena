# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit submit-only schema; raw contract codec preserves the domain bounds."""

from typing import NewType

import strawberry
from strawberry.types import Info

from ..contracts import canonical_json, parse_contract
from .schema import Capabilities, Query, SafeSchema, SubmissionResult, safe_resolver, submission_view


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
                "cancel",
                "resume",
                "native",
                "policy",
                "publication",
                "other_history",
                "scene_detail",
                "generation_detail",
                "artifact_bytes",
            ],
        )


@strawberry.type
class Mutation:
    @strawberry.mutation
    @safe_resolver
    async def submit_workflow(
        self, info: Info, operation_id: strawberry.ID, contract: WorkflowContractJSON
    ) -> SubmissionResult:
        return submission_view(await info.context.submit(str(operation_id), str(contract)))


schema = SafeSchema(query=ExecutionQuery, mutation=Mutation)
