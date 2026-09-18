# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Application admission boundary; acceptance never releases an execution attempt."""

import time
from dataclasses import dataclass

from .contracts import canonical_json, parse_contract
from .neo4j_store import StoreUnavailable, validate_operation_id
from .readiness import DependencyResult, ReadinessReport, required_dependencies


@dataclass(frozen=True)
class SubmissionResult:
    """Retained acceptance or a non-durable admission refusal."""

    disposition: str
    run: object | None
    readiness: ReadinessReport | None = None


class WorkflowService:
    """Compose scoped read authorization and exact replay before mutable checks.

    Store and authority are already bound to the same deployment/workspace by
    the trusted composition root. require_submit(principal, operation_id, contract)
    is a check-only admission port: never issue/renew/capture execution grants.
    Authority methods raise on denial; they never infer permissions from
    configured credentials or request effect flags. Exact replay requires only
    require_read(principal), independent of current execution authority.
    """

    def __init__(self, store, authority, gate, *, validate_support, max_pending=1):
        if type(max_pending) is not int or not 1 <= max_pending <= 1000:
            raise ValueError("Invalid pending workflow capacity")
        self._store = store
        self._authority = authority
        self._gate = gate
        self._validate_support = validate_support
        self._max_pending = max_pending

    @property
    def bound_store(self):
        """Expose exact store identity for trusted coordinator composition."""
        return self._store

    def adopt_generation(self, principal, fence, receipt, *, artifacts, protect):
        """Read-authorized exact released recovery; expired execution grants are irrelevant.

        The protection callback remains mandatory under current data policy. No
        authority renewal, provider call or current-configuration inference occurs.
        """
        checked = WorkflowService.prepare_generation_adoption(
            self, principal, fence, receipt, artifacts=artifacts, protect=protect
        )
        return self._store.commit_generation_receipt(fence, checked)

    def prepare_generation_adoption(self, principal, fence, receipt, *, artifacts, protect):
        """Verify retained authority/bindings and actual bytes before possible commit.

        This returns a receipt, not durable adoption. Trusted receivers may pin
        this exact verified value before calling the same store's commit boundary.
        Every adoption/repeat must perform this verification again.
        """
        from .artifacts import GenerationArtifacts
        from .contracts import contract_digest
        from .results import GenerationReceipt

        self._authority.require_read(principal)
        retained = self._store.get_attempt(fence)
        if principal != retained.authorization.principal:
            raise ValueError("receipt principal does not own retained attempt")
        if type(artifacts) is not GenerationArtifacts or type(receipt) is not GenerationReceipt:
            raise ValueError("concrete generation artifacts and typed receipt required")
        contract = parse_contract(retained.contract_json)
        if (
            not retained.released
            or retained.registration != receipt.registration
            or receipt.fence != fence
            or contract_digest(contract) != receipt.contract_digest
            or contract.execution.generation_model != receipt.generation_profile
        ):
            raise ValueError("receipt retained binding mismatch")
        checked = artifacts.verify(receipt, protect=protect)
        if checked != receipt:
            raise ValueError("verified artifact digests differ")
        return checked

    def submit(self, principal, operation_id: str, raw: str | bytes) -> SubmissionResult:
        """Admit or replay without releasing model, simulator or worker execution.

        Args:
            principal: Trusted authenticated identity, never credentials.
            operation_id: Scoped submission key; a changed request is a conflict.
            raw: Strict versioned workflow JSON.

        Returns:
            Retained acceptance, fresh pending admission, or local not-ready report.
        """
        self._authority.require_read(principal)
        validate_operation_id(operation_id)
        request = parse_contract(raw)
        normalized = canonical_json(request)
        try:
            retained = self._store.lookup_submission(operation_id, normalized)
        except StoreUnavailable:
            profile = request.execution.database
            report = ReadinessReport(
                (
                    DependencyResult(
                        "neo4j",
                        "unavailable",
                        profile.settings_sha256,
                        profile_id=profile.profile_id,
                        code="probe_failed",
                    ),
                ),
                time.monotonic(),
            )
            return SubmissionResult("dependencies_not_ready", None, report)
        if retained is not None:
            return SubmissionResult("retained", retained)
        if not request.effects.allow_operational_writes:
            raise ValueError("operational_writes_not_permitted")
        self._validate_support(request)
        self._authority.require_submit(principal, operation_id, request)
        report = self._gate.check(
            required_dependencies(request),
            timeout_s=min(120, request.budget.per_operation_timeout_seconds),
        )
        if not report.ready:
            return SubmissionResult("dependencies_not_ready", None, report)
        # Readiness consumes time. Recheck current authority before accepting;
        # every subsequent worker release still needs its own durable grant check.
        self._authority.require_submit(principal, operation_id, request)
        retained = self._store.admit(operation_id, normalized, normalized, self._max_pending)
        return SubmissionResult("accepted", retained, report)
