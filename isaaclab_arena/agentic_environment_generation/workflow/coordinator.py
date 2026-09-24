# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Bounded generation dispatch and completion, never a scene execution loop.

Trusted composition supplies same-scope store/authority, authenticated creator,
process-unique owner ID and an actually held local lease. It must retain this one
coordinator per run for the lease lifetime. No adapter is supplied here. Worker
prepare waits only for bounded registration, never a result; it cannot execute
until send. The opaque owned handle must verify full registration when stopped.

Completion requires an explicitly configured concrete same-store WorkflowService
and actual generation artifacts. Receipt arrival triggers adoption, owned stop and
exact readback, not scene acceptance. No polling loop, process adapter, private
grant resolver or lease adapter is implemented. Cleanup evidence retained before
registration commits needs explicit reconciliation; this coordinator never
fabricates a durable registration to clear it.
"""

import json
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol

from .artifacts import GenerationArtifacts
from .attempts import AuthorizationSnapshot, GenerationReservation, WorkerRegistration
from .contracts import contract_digest, parse_contract
from .readiness import durable_readiness, required_dependencies
from .results import CleanupEvidence, GenerationReceipt, ReconciliationReason
from .service import WorkflowService


class PrepareFailed(RuntimeError):
    """Prepare created an owned worker; retain its exact handle even on failure.

    A plain prepare exception guarantees no worker was created. Adapters must
    raise this exception with the owned handle otherwise, including timeouts.
    """

    def __init__(self, prepared):
        super().__init__("worker preparation incomplete")
        self.prepared = prepared


class DispatchIncomplete(RuntimeError):
    """Sanitized safe failure; retained handle must be reconciled, never resent."""

    def __init__(self, handle):
        super().__init__("generation dispatch incomplete; inspect retained local handle")
        self.handle = handle


class CompletionIncomplete(RuntimeError):
    """Sanitized completion failure with exact retained reconciliation identity."""

    def __init__(self, handle):
        super().__init__("generation completion incomplete; reconcile retained local handle")
        self.handle = handle


@dataclass(frozen=True)
class CompletionResult:
    """Observed generation disposition, never scene acceptance."""

    disposition: str
    run: object
    attempt: object


@dataclass(frozen=True)
class StopResult:
    durable_cancellation_pending: bool
    cleanup_pending: bool


@dataclass(frozen=True)
class FailureResult:
    durable_reconciliation_pending: bool
    cleanup_pending: bool


class HeldOwnerLease(Protocol):
    owner_id: str

    def mark_prepared(self, fence) -> None:
        """Latch the exact claimed fence before prepare; retain until proven cleanup."""
        ...

    def require_held(self, run_id: str, principal: str) -> None:
        """Require this principal to hold the run lease."""
        ...


class GenerationAuthority(Protocol):
    def release_guard(self, principal, contract, fence, registration) -> AbstractContextManager:
        """Serialize final authorization and bounded send against all authority mutation.

        Acquire only beneath the coordinator interlock; callbacks must not enter
        the coordinator while holding this guard. No unguarded fallback exists.
        """
        ...

    def require_read(self, principal: str) -> None:
        """Authenticate scoped read access."""
        ...

    def require_execute(self, principal, contract, *, run_id, fence=None) -> AuthorizationSnapshot:
        """Check current run/attempt authority without issuing or renewing a grant."""
        ...

    def private_envelope(self, principal, contract, fence, registration) -> bytes:
        """Resolve the exact private execution envelope."""
        ...


@dataclass(frozen=True)
class PreparedWorker:
    registration: WorkerRegistration
    owned_handle: object = field(repr=False, compare=False)


class WorkerPort(Protocol):
    """Bounded owner-only transport; never submit to another workflow queue."""

    def prepare(self, fence, contract, *, timeout_s: float) -> PreparedWorker:
        """Prepare an owned waiting worker without execution."""
        ...

    def send(self, prepared: PreparedWorker, envelope: bytes, *, timeout_s: float) -> None:
        """Send once after fresh release authority."""
        ...

    def stop_owned(self, prepared: PreparedWorker, *, timeout_s: float):
        """Stop only the exactly registered owned worker."""
        ...


@dataclass
class LocalDispatch:
    """Local process handle, not a workflow state or permission to resume."""

    run_id: str | None = None
    expected_version: int | None = None
    decision_id: str | None = None
    reservation: GenerationReservation | None = None
    intent_id: str | None = None
    owner_id: str | None = None
    owner_epoch: int | None = None
    fence: object = None
    prepared: PreparedWorker | None = None
    cleanup: CleanupEvidence | None = None
    completion_receipt: GenerationReceipt | None = None
    incomplete: bool = False
    reconciliation_required: bool = False
    durable_reconciliation_pending: bool = False
    cleanup_pending: bool = False


class GenerationCoordinator:
    """One retained run interlock; no serial execution slot or child-result wait."""

    def __init__(
        self,
        store,
        authority: GenerationAuthority,
        gate,
        worker: WorkerPort,
        *,
        run_id,
        principal,
        lease: HeldOwnerLease,
        readiness_clock,
        workflow_service=None,
    ):
        if workflow_service is not None and (
            type(workflow_service) is not WorkflowService or workflow_service.bound_store is not store
        ):
            raise ValueError("concrete same-store workflow service required")
        self._service = workflow_service
        lease.require_held(run_id, principal)
        self._store, self._authority, self._gate, self._worker = (
            store,
            authority,
            gate,
            worker,
        )
        self._run_id, self._principal, self._lease = run_id, principal, lease
        self._clock = readiness_clock
        self._lock = RLock()
        self._handle = None
        self._key = None
        self._cancelled = False
        self._preparing = False
        self._completing = False
        self._timeout = 10.0

    def _authenticate(self, principal):
        self._authority.require_read(principal)
        if principal != self._principal:
            raise PermissionError("creator required")

    def _authorization(self, request, *, fence=None):
        auth = self._authority.require_execute(self._principal, request, run_id=self._run_id, fence=fence)
        if (
            type(auth) is not AuthorizationSnapshot
            or auth.principal != self._principal
            or auth.contract_digest != contract_digest(request)
        ):
            raise PermissionError("authorization binding mismatch")
        return auth

    def _readiness(self, request):
        requirements = required_dependencies(request, resolved_instances=self._store.dependency_instances)
        report = self._gate.check(
            requirements,
            timeout_s=min(120, request.budget.per_operation_timeout_seconds),
        )
        return durable_readiness(request, requirements, report, mapping=self._clock)

    def dispatch(
        self, principal, *, expected_version, decision_id, reservation, pending_intent=None, resume_operation_id=None
    ):
        """Release once and return locally; retries never construct another worker."""
        self._authenticate(principal)
        if resume_operation_id is not None and pending_intent is None:
            raise ValueError("Keyed dispatch requires an existing intent")
        key = (expected_version, decision_id, reservation, pending_intent, resume_operation_id)
        with self._lock:
            if self._handle is not None:
                if key != self._key:
                    raise ValueError("conflicting local dispatch")
                return self._handle
            if self._cancelled:
                raise ValueError("locally stopped")
            self._handle, self._key = (
                LocalDispatch(
                    run_id=self._run_id,
                    expected_version=expected_version,
                    decision_id=decision_id,
                    reservation=reservation,
                    owner_id=self._lease.owner_id,
                ),
                key,
            )
            try:
                self._lease.require_held(self._run_id, principal)
                run = self._store.get_run(self._run_id)
                if run.version != expected_version or (run.state != "pending" and pending_intent is None):
                    raise ValueError("dirty dispatch requires reconciliation")
                request = parse_contract(run.contract_json)
                self._timeout = min(120, request.budget.per_operation_timeout_seconds)
                auth = self._authorization(request)
                readiness = self._readiness(request)
                if pending_intent is None:
                    intent = self._store.reserve_generation(
                        self._run_id,
                        expected_version,
                        decision_id,
                        auth,
                        reservation,
                        readiness=readiness,
                    )
                else:
                    pending = self._store.pending_generation(self._run_id)
                    if pending != dict(intent_id=pending_intent, reservation=reservation):
                        raise ValueError("Original unclaimed reservation required")
                    intent = pending_intent
                # Retain acknowledged identities before another outcome can be unknown.
                self._handle.intent_id = intent
                epoch = self._store.begin_owner(self._handle.owner_id)
                self._handle.owner_epoch = epoch
                claim_args = {} if resume_operation_id is None else dict(resume_operation_id=resume_operation_id)
                fence = self._store.claim_intent(intent, self._handle.owner_id, epoch, **claim_args)
                self._handle.fence = fence
                self._lease.mark_prepared(fence)
                self._preparing = True
            except Exception:
                self._handle.incomplete = True
                raise DispatchIncomplete(self._handle) from None
        try:
            prepared = self._worker.prepare(fence, request, timeout_s=self._timeout)
            with self._lock:
                self._preparing = False
                self._handle.prepared = prepared
                self._handle.cleanup_pending = True
                if type(prepared) is not PreparedWorker or prepared.registration.fence != fence:
                    raise ValueError("prepared registration mismatch")
                if self._cancelled:
                    self._stop()
                    return self._handle
                self._store.register_worker(fence, prepared.registration)
                readiness = self._readiness(request)
                envelope = self._authority.private_envelope(principal, request, fence, prepared.registration)
                auth = self._authorization(request, fence=fence)
                self._lease.require_held(self._run_id, principal)
                # CAS acknowledgement can be lost. Never resend after this point.
                self._handle.reconciliation_required = True
                released = self._store.release_attempt(
                    fence,
                    prepared.registration.registration_id,
                    auth,
                    readiness=readiness,
                )
                if released is not True or self._cancelled:
                    raise ValueError("no fresh release authority")
                try:
                    # The database transaction may have outlived private authority.
                    # Resolve again, then bind its current snapshot to the exact
                    # release authorization (including expiry; checks never renew).
                    with self._authority.release_guard(principal, request, fence, prepared.registration):
                        envelope = self._authority.private_envelope(principal, request, fence, prepared.registration)
                        if self._authorization(request, fence=fence) != auth:
                            raise PermissionError("release authorization changed")
                        self._lease.require_held(self._run_id, principal)
                        if self._cancelled:
                            raise ValueError("locally stopped")
                        bind_send = getattr(self._worker, "bind_model_send", None)
                        if bind_send is not None:
                            bind_send(prepared, lambda config: self.model_send_guard(principal, prepared, config))
                        self._worker.send(prepared, envelope, timeout_s=self._timeout)
                finally:
                    del envelope
                self._handle.reconciliation_required = False
                return self._handle
        except Exception as exc:
            with self._lock:
                self._preparing = False
                if isinstance(exc, PrepareFailed):
                    self._handle.prepared = exc.prepared
                    self._handle.cleanup_pending = True
                self._handle.incomplete = True
                self._cancelled = True
                try:
                    self._stop()
                except Exception:
                    self._handle.cleanup_pending = True
                if self._handle.reconciliation_required:
                    self._handle.durable_reconciliation_pending = True
                    try:
                        reason = ReconciliationReason.OWNER_OUTCOME_UNCERTAIN
                        self._store.mark_reconciliation_required(fence, reason)
                        retained = self._store.get_attempt(fence)
                        self._handle.durable_reconciliation_pending = retained.reconciliation_reason != reason
                    except Exception:
                        # Exact local fence/registration remains the recovery obligation.
                        self._handle.durable_reconciliation_pending = True
                raise DispatchIncomplete(self._handle) from None

    @contextmanager
    def model_send_guard(self, principal, prepared, config):
        """Recheck an already released exact child at each SDK send, without redispatch."""
        with self._lock:
            handle = self._handle
            if self._cancelled or handle is None or handle.prepared is not prepared or handle.incomplete:
                raise ValueError("Inactive local generation send")
            run = self._store.get_run(self._run_id)
            request = parse_contract(run.contract_json)
            fence = prepared.registration.fence
            with self._authority.release_guard(principal, request, fence, prepared.registration):
                self._authenticate(principal)
                self._lease.require_held(self._run_id, principal)
                auth = self._authorization(request, fence=fence)
                attempt = self._store.get_attempt(fence)
                owner = self._store.get_owner()
                if (
                    run.state != "running" or run.phase != "generation"
                    or attempt.registration != prepared.registration or attempt.status != "released"
                    or not attempt.released or attempt.cleanup is not None or attempt.receipt is not None
                    or attempt.authorization != auth
                    or owner is None or not owner.dirty
                    or (owner.owner_id, owner.owner_epoch) != (fence.owner_id, fence.owner_epoch)
                ):
                    raise ValueError("Exact active generation reservation required")
                packet = json.loads(self._authority.private_envelope(principal, request, fence, prepared.registration))
                if packet["config"] != config:
                    raise ValueError("Generation send configuration changed")
                yield

    def complete(self, principal, receipt: GenerationReceipt, artifacts: GenerationArtifacts, *, protect):
        """Receive a bounded worker result and observe receipt plus owned cleanup."""
        self._authenticate(principal)
        with self._lock:
            handle = self._handle
            if self._service is None:
                raise ValueError("completion service not configured")
            if (
                type(receipt) is not GenerationReceipt
                or handle is None
                or handle.prepared is None
                or receipt.fence != handle.fence
                or receipt.registration != handle.prepared.registration
            ):
                raise ValueError("local completion binding mismatch")
            if handle.completion_receipt is not None and handle.completion_receipt != receipt:
                raise ValueError("conflicting local completion")
            if self._completing:
                raise ValueError("completion already in progress")
            self._completing = True
        failed = False
        # Artifact screening may call back or block on bounded I/O. Do not hold
        # the stop interlock: cancellation must remain independently deliverable.
        try:
            checked = WorkflowService.prepare_generation_adoption(
                self._service, principal, handle.fence, receipt, artifacts=artifacts, protect=protect
            )
            with self._lock:
                # Pin only verified bytes, but before a commit acknowledgement can
                # be lost. Rejected unverified messages cannot poison recovery.
                handle.completion_receipt = checked
            self._store.commit_generation_receipt(handle.fence, checked)
        except Exception:
            failed = True
        with self._lock:
            self._completing = False
            # Local stop does not depend on any database operation succeeding.
            try:
                self._stop()
            except Exception:
                failed = True
                handle.cleanup_pending = True
            try:
                if self._cancelled:
                    observed = self._store.get_run(self._run_id)
                    if observed.state not in ("cancel_requested", "cancelled"):
                        self._store.request_cancel(self._run_id, observed.version)
                if handle.cleanup is not None:
                    self._store.acknowledge_cleanup(handle.fence, handle.cleanup)
                if not failed:
                    attempt = self._store.get_attempt(handle.fence)
                    run = self._store.get_run(self._run_id)
                    if attempt.receipt != receipt or attempt.cleanup != handle.cleanup:
                        raise ValueError("completion readback mismatch")
                    if run.state == "cancelled" or (run.state == "running" and run.phase == "validation"):
                        handle.incomplete = handle.reconciliation_required = False
                        handle.durable_reconciliation_pending = False
                        disposition = "cancelled" if run.state == "cancelled" else "validation"
                        return CompletionResult(disposition, run, attempt)
            except Exception:
                pass
            handle.incomplete = handle.reconciliation_required = True
            handle.durable_reconciliation_pending = True
            try:
                reason = ReconciliationReason.OWNER_OUTCOME_UNCERTAIN
                self._store.mark_reconciliation_required(handle.fence, reason)
                retained = self._store.get_attempt(handle.fence)
                handle.durable_reconciliation_pending = retained.reconciliation_reason != reason
            except Exception:
                pass
            raise CompletionIncomplete(handle) from None

    def fail_owned(self, prepared):
        """Reconcile an owned receiver failure without requiring a current read grant.

        Exact retained object identity is the local stop capability. This endpoint
        returns no run/read data, never requests user cancellation, and never sends.
        Public cancel/complete remain authenticated. Physical stop precedes DB I/O.
        """
        with self._lock:
            handle = self._handle
            if handle is None or handle.prepared is not prepared:
                raise PermissionError("Exact retained owner capability required")
            handle.incomplete = handle.reconciliation_required = True
            handle.durable_reconciliation_pending = True
            try:
                self._stop()
            except Exception:
                handle.cleanup_pending = True
            try:
                reason = (
                    ReconciliationReason.RELEASED_WITHOUT_RECEIPT
                    if handle.completion_receipt is None
                    else ReconciliationReason.OWNER_OUTCOME_UNCERTAIN
                )
                self._store.mark_reconciliation_required(handle.fence, reason)
                if handle.cleanup is not None:
                    self._store.acknowledge_cleanup(handle.fence, handle.cleanup)
                retained = self._store.get_attempt(handle.fence)
                handle.durable_reconciliation_pending = retained.reconciliation_reason != reason
            except Exception:
                pass
            return FailureResult(handle.durable_reconciliation_pending, handle.cleanup_pending)

    def _stop(self):
        handle = self._handle
        if handle is not None and handle.prepared is not None and handle.cleanup is None:
            evidence = self._worker.stop_owned(handle.prepared, timeout_s=self._timeout)
            if type(evidence) is not CleanupEvidence or evidence.registration != handle.prepared.registration:
                raise ValueError("exact cleanup evidence required")
            handle.cleanup = evidence
            handle.cleanup_pending = False

    def stop_local(self, principal):
        """Fence and stop retained work without authority, model or database I/O.

        This owner-memory capability checks the frozen creator only and exposes no
        run data. The authenticated owner transport supplies that exact principal.
        A pending result is not physical cleanup proof; callers must not ACK it.
        """
        if type(principal) is not str or principal != self._principal:
            raise PermissionError("creator required")
        with self._lock:
            self._cancelled = True
            try:
                self._stop()
            except Exception:
                if self._handle is not None:
                    self._handle.cleanup_pending = True
                return StopResult(True, True)
            return StopResult(True, self._preparing)

    def cancel(self, principal):
        """Authenticate locally, fence send, stop owned work, then attempt persistence.

        Pending means delivery/cleanup/durable acknowledgement is incomplete; this
        method never asserts workflow cancellation or remote provider termination.
        """
        self._authenticate(principal)
        with self._lock:
            self._cancelled = True
            try:
                self._stop()
            except Exception:
                if self._handle is not None:
                    self._handle.cleanup_pending = True
                return StopResult(True, True)
            cleanup_pending = self._preparing
            try:
                run = self._store.get_run(self._run_id)
                if run.state not in ("cancel_requested", "cancelled"):
                    self._store.request_cancel(self._run_id, run.version)
                if self._handle is not None and self._handle.cleanup is not None:
                    self._store.acknowledge_cleanup(self._handle.fence, self._handle.cleanup)
                observed = self._store.get_run(self._run_id)
                return StopResult(observed.state != "cancelled", cleanup_pending)
            except Exception:
                return StopResult(True, cleanup_pending)
