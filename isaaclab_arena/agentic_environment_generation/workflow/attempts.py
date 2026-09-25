# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Frozen metadata for the generation-only persistence boundary, never credentials."""
from typing import Annotated, Literal

from pydantic import Field, model_serializer, model_validator

from .contracts import Amount, Count, FrozenModel, Hash, Identifier


class AuthorizationSnapshot(FrozenModel):
    """Trusted composition's current scoped grant metadata, not proof or credentials.

    Private authentication, revocation checks and credential resolution stay outside
    this store. Renewal cannot expand the retained contract's effect ceilings.
    """

    database: Identifier
    deployment_id: Identifier
    workspace_id: Identifier
    principal: Identifier
    grant_ref: Identifier
    contract_digest: Hash
    expires_at: Amount
    capabilities: Annotated[
        tuple[
            Literal["generation_model", "assessment_model", "operational_writes", "paid_models", "native_validation"],
            ...,
        ],
        Field(min_length=1, max_length=3),
    ]


PositiveCount = Annotated[int, Field(strict=True, gt=0, le=9_223_372_036_854_775_807)]


class AttemptFence(FrozenModel):
    """Exact generation/owner fence; possession alone is not execution authority."""

    run_id: Identifier
    intent_id: Identifier
    attempt_id: Identifier
    generation: PositiveCount
    owner_id: Identifier
    owner_epoch: PositiveCount


class WorkerRegistration(FrozenModel):
    """Exact locally verified identity metadata; the database does not inspect OS state.

    Trusted process composition must verify host/boot/process group/start identity
    and retain local leases before submitting this record. No arbitrary PID stop
    capability or cleanup-complete assertion is conferred by registration.
    """

    registration_id: Identifier
    fence: AttemptFence
    host: Identifier
    boot: Identifier
    pid: PositiveCount
    pgid: PositiveCount
    sid: PositiveCount
    start_ticks: PositiveCount


class ReadyProfile(FrozenModel):
    """A trusted non-inference probe established this exact dependency profile."""

    role: Literal["generation_model", "assessment_model", "runtime", "neo4j", "capture", "gpu", "policy"]
    profile_id: Identifier
    settings_sha256: Hash
    expected_instance_id: Identifier | None = None
    observed_instance_id: Identifier | None = None


class ReadinessReceipt(FrozenModel):
    """Required full-outcome readiness; not a lease or a boolean bypass.

    Trusted application probes supply these successful bindings; unsupported,
    unavailable and unknown dependencies cannot produce this receipt. Freshness
    is checked against the store composition's bounded TTL and trusted clock.
    """

    contract_digest: Hash
    checked_at: Amount
    profiles: Annotated[tuple[ReadyProfile, ...], Field(min_length=1, max_length=7)]


class GenerationReservation(FrozenModel):
    """Full outer allowance; no refund or consumption reconciliation exists yet."""

    model_calls: Count
    model_tokens: Count | None
    cost_ceiling_usd: Amount | None
    runtime_allowance_seconds: Amount
    accounting_policy: Literal["bounded-v1", "accounting-only-v1"] = "bounded-v1"

    @model_validator(mode="after")
    def accounting(self):
        missing = self.model_tokens is None or self.cost_ceiling_usd is None
        if self.accounting_policy == "accounting-only-v1":
            if self.model_tokens is not None or self.cost_ceiling_usd is not None:
                raise ValueError("Accounting-only reservations cannot contain token/cost caps")
        elif missing:
            raise ValueError("Legacy reservations require token and cost bounds")
        return self

    @model_serializer(mode="wrap")
    def versioned_accounting(self, handler):
        value = handler(self)
        if self.accounting_policy == "bounded-v1":
            value.pop("accounting_policy", None)
        return value
