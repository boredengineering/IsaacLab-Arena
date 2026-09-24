# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Shared foreground application, not a CLI, queue or second scene controller.

Factories are trusted composition, never request data. They construct transports
and retained prior inputs only; all next-step decisions belong to WorkflowService
and Neo4j. Capture remains explicitly synthetic; native execution is not admitted.
"""

import time
from threading import RLock
from threading import local as thread_local
from types import SimpleNamespace

from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, parse_contract
from isaaclab_arena.agentic_environment_generation.workflow.coordinator import GenerationCoordinator
from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import StoreUnavailable, validate_operation_id
from isaaclab_arena.agentic_environment_generation.workflow.readiness import (
    ReadinessClock,
    durable_readiness,
    required_dependencies,
)
from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import canonical
from isaaclab_arena.agentic_environment_generation.workflow.scene_ports import ScenePorts
from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
from isaaclab_arena.agentic_environment_generation.workflow.validation import validate_generation_candidate

_resume_authority_context = thread_local()


class ForegroundWorkflow:
    """Synchronous foreground run plus read/cancel/reconcile application boundary.

    initial_worker_factory(**kwargs) receives area, root, prior, protect and
    ownership_artifacts; scene_worker_factory(**kwargs) receives ownership_artifacts.
    prior_factory(principal=..., run_id=..., contract=...) returns a retained prior
    receipt. scene_options is the explicit ScenePorts configuration excluding its
    authority/ready/refine/visual/check_active/protect hooks. No decision callbacks.
    Caller owns the already-open store/driver and artifact area; close revokes this
    root's authority and stops its workers, but never closes shared storage or
    unlocks uncertain ownership.

    Runtime adapter factories and cancellation are required trusted composition,
    never request data or import paths. Only ownership_artifacts_factory(area) is
    called at construction; it must be inert. Execution adapters are constructed
    at their existing admission/recovery boundaries. cancellation supplies
    cancel_workflow, close_controls, finish_cancelled, start_owner_control,
    stop_local and stop_requested, each receiving this application first.
    """

    def __init__(
        self,
        *,
        store,
        authority,
        gate,
        private_parent,
        artifacts,
        artifact_root,
        catalogue_sha256,
        generation_reservation,
        prior_factory,
        initial_worker_factory,
        scene_worker_factory,
        validate_document,
        scene_options,
        owner_control=False,
        owner_lease_factory,
        initial_receiver_factory,
        scene_ports_factory,
        recovery_factory,
        ownership_artifacts_factory,
        cancellation,
    ):
        if authority.store is not store:
            raise ValueError("Exact same-store authority required")
        self.store, self.authority, self.gate = store, authority, gate
        self.private_parent, self.artifacts, self.artifact_root = (
            private_parent,
            artifacts,
            artifact_root,
        )
        self.catalogue_sha256 = catalogue_sha256
        self.generation_reservation = generation_reservation
        self.prior_factory, self.initial_worker_factory = (
            prior_factory,
            initial_worker_factory,
        )
        self.scene_worker_factory, self.validate_document = (
            scene_worker_factory,
            validate_document,
        )
        self.scene_options = dict(scene_options)
        if not self.scene_options["profile"].owned_worker or self.scene_options["profile"].assurance != "synthetic":
            raise ValueError("Only explicitly synthetic owned scene composition is supported")
        # Construct only pure admission ports: no worker, backend, SDK or ping.
        self._support = ScenePorts(
            **self.scene_options,
            protect=authority.protect_public,
            authorize=None,
            ready=None,
            refine=None,
            visual=None,
            check_active=lambda: None,
        )
        self.service = WorkflowService(store, authority, gate, validate_support=self._support.admit)
        self.ownership = ownership_artifacts_factory(artifacts.area)
        self._owner_lease_factory = owner_lease_factory
        self._initial_receiver_factory = initial_receiver_factory
        self._scene_ports_factory = scene_ports_factory
        self._recovery_factory = recovery_factory
        self._cancellation = cancellation
        self._local, self._recoveries = {}, {}
        self._owned_resources = ()
        self._lock, self._closed = RLock(), False
        self._admission_listener = None
        if type(owner_control) is not bool:
            raise TypeError("Trusted owner-control opt-in required")
        self._owner_control = owner_control
        self._cancel_controls = {}
        self._resume_deliveries, self._resume_busy = {}, set()

    def set_admission_listener(self, callback):
        """Install a trusted observer; failure leaves acceptance pending, never dispatches."""
        if callback is not None and not callable(callback):
            raise TypeError("Admission listener must be callable")
        self._admission_listener = callback

    def _check(self, principal):
        if self._closed:
            raise ValueError("Foreground workflow closed")
        self.authority.require_read(principal)

    def _preflight(self, principal, contract):
        self._support.admit(contract)
        self.authority.protect_workflow_contract(principal, contract)
        bounds = self.authority.require_workflow_model_bounds(principal, contract)
        for role, bound in bounds.items():
            if canonical(self._support.model_ceilings[role].per_call_bound) != canonical(bound):
                raise ValueError("Frozen role accounting mismatch")
        for reservation in (
            self._support.profile.observe,
            self._support.profile.repair,
        ):
            self._support.require_bounded_capability(principal, contract, reservation)
        generation = self._support.model_ceilings["generation"]
        reservation = self.generation_reservation
        if (
            generation.max_calls > reservation.model_calls
            or generation.max_tokens > reservation.model_tokens
            or generation.timeout_seconds > reservation.runtime_allowance_seconds
        ):
            raise ValueError("Initial generation reservation below configured bounds")

    def _ready(self, contract):
        mapping = ReadinessClock.capture()
        requirements = required_dependencies(contract, resolved_instances=self.store.dependency_instances)
        report = self.gate.check(
            requirements,
            timeout_s=min(120, contract.budget.per_operation_timeout_seconds),
        )
        return durable_readiness(contract, requirements, report, mapping=mapping)

    def run(self, principal, operation_id, raw_contract):
        """Preserve synchronous admission notification followed by fresh execution."""
        result, drive = self.admit(principal, operation_id, raw_contract)
        return result if drive is None else drive()

    def admit(self, principal, operation_id, raw_contract):
        """Return a public result and an owner-only, parameterless one-shot drive.

        Only acknowledged fresh admission returns a callable. Replay recovers the
        retained status with None, never another delivery. The callable captures
        this root, principal, immutable run/contract and already-issued bindings;
        it is not a serializable ticket or execution-by-run-id API. The trusted
        single in-process owner must retain it independently of client response
        delivery. Dropping it, losing submit ACK, callback failure or process loss
        requires explicit recovery, never submission replay to execute again.

        The owner must route submissions through this root/authority interlock;
        independent submitters or roots with independent authorities are not an
        exactly-once queue. Keep composition ports stable for the root lifetime.
        Call drive outside authority/application locks, on the owner's thread or
        offload, never inside an admission/authority callback. It consumes before
        checks/effects, including failures or stale/cancelled work, and expires
        with this root. Guarded reentry is refused without consumption. Neither
        drive nor replay renews grants or resets Neo4j's original admitted_at /
        total deadline; release retains the existing fenced authority checks.
        This seam provides no scheduler, restart recovery or API execution mode.

        Returns:
            (public_result, drive_or_none). Only public_result belongs on a wire.
        """
        if getattr(_resume_authority_context, "active", False):
            raise RuntimeError("Guarded admission reentry unavailable")
        _resume_authority_context.active = True
        try:
            return self._admit(principal, operation_id, raw_contract)
        finally:
            _resume_authority_context.active = False

    def _admit(self, principal, operation_id, raw_contract):
        self._check(principal)
        validate_operation_id(operation_id)
        contract = parse_contract(raw_contract)
        # Replay must precede current configuration, grants, readiness and factories.
        try:
            retained = self.store.lookup_submission(operation_id, canonical_json(contract))
        except StoreUnavailable:
            return self._unknown(None), None
        if retained is not None:
            return self.status(principal, retained.run_id), None
        with self.authority.mutation_guard():
            # A same-owner admission may have won while this call waited.
            try:
                retained = self.store.lookup_submission(operation_id, canonical_json(contract))
            except StoreUnavailable:
                return self._unknown(None), None
            if retained is not None:
                return self.status(principal, retained.run_id), None
            self.authority.protect_workflow_contract(principal, contract, operation_id=operation_id)
            self._preflight(principal, contract)
            submitted = self.service.submit(principal, operation_id, raw_contract)
            if submitted.disposition == "dependencies_not_ready":
                return (
                    self._public(
                        dict(
                            disposition="dependencies_not_ready",
                            run_id=None,
                            blockers=list(submitted.readiness.blockers),
                            available_actions=[],
                        )
                    ),
                    None,
                )
            if submitted.disposition == "retained":
                return self.status(principal, submitted.run.run_id), None
            run = submitted.run
            self._start_control(principal, run.run_id)
            handle = self._public(
                dict(
                    schema_version=1,
                    disposition="admitted",
                    run_id=run.run_id,
                    operation_id=run.operation_id,
                    state=run.state,
                    version=run.version,
                    event_cursor=run.event_cursor,
                )
            )
            if self._admission_listener is not None:
                self._admission_listener(dict(handle))
            if self._cancellation.stop_requested(self, run.run_id):
                return self.status(principal, run.run_id), None
            self.authority.bind_run(
                principal,
                operation_id,
                contract,
                run_id=run.run_id,
                catalogue_sha256=self.catalogue_sha256,
                retained_run=run,
            )
            self.authority.bind_workflow_models(principal, contract, run_id=run.run_id, retained_run=run)
        return handle, self._admitted_drive(principal, run, contract)

    def _admitted_drive(self, principal, run, contract):
        consumed = False

        def drive():
            nonlocal consumed
            if getattr(_resume_authority_context, "active", False):
                raise RuntimeError("Guarded admission drive unavailable")
            with self._lock:
                if consumed:
                    raise ValueError("Admission drive consumed")
                consumed = True
            self._check(principal)
            if self._cancellation.stop_requested(self, run.run_id):
                return self.status(principal, run.run_id)
            if self.store.get_run(run.run_id) != run:
                return self.status(principal, run.run_id)
            _resume_authority_context.active = True
            try:
                with self.authority.mutation_guard():
                    self.authority.require_scene_execute(principal, contract, run_id=run.run_id, retained_run=run)
            finally:
                _resume_authority_context.active = False
            if self.store.get_run(run.run_id) != run:
                return self.status(principal, run.run_id)
            return self._generate(principal, run, contract)

        return drive

    def _generate(self, principal, run, contract, *, pending=None, resume_receipt=None):
        if self._cancellation.stop_requested(self, run.run_id):
            return self.status(principal, run.run_id)
        prior = self.prior_factory(principal=principal, run_id=run.run_id, contract=contract)
        if contract.retrieval is not None:
            run = self.store.get_run(run.run_id)
        worker = self.initial_worker_factory(
            area=self.artifacts.area,
            root=self.artifact_root,
            prior=prior,
            protect=self.authority.protect_public,
            ownership_artifacts=self.ownership,
        )
        lease = self._owner_lease_factory(
            self.private_parent,
            run_id=run.run_id,
            principal=principal,
            cleanup_verified=worker.cleanup_verified,
        )
        coordinator = GenerationCoordinator(
            self.store,
            self.authority,
            self.gate,
            worker,
            run_id=run.run_id,
            principal=principal,
            lease=lease,
            readiness_clock=ReadinessClock.capture(),
            workflow_service=self.service,
        )
        receiver = self._initial_receiver_factory(
            worker,
            coordinator,
            lease,
            self.artifacts,
            validate_document=self.validate_document,
            protect=self.authority.protect_public,
        )
        local = SimpleNamespace(
            principal=principal,
            worker=worker,
            lease=lease,
            coordinator=coordinator,
            receiver=receiver,
            handle=None,
            ports=None,
            stopped=False,
            retired=False,
            busy=True,
        )
        with self._lock:
            local.stopped = self._cancellation.stop_requested(self, run.run_id)
            self._local[run.run_id] = local
        completed = None
        try:
            if local.stopped or self._cancellation.stop_requested(self, run.run_id):
                self._cancellation.stop_local(self, principal, run.run_id)
                lease.release_never_prepared()
                local.retired = True
                return self.status(principal, run.run_id)
            if pending is not None:
                owner = self.store.get_owner()
                if owner is not None and owner.dirty:
                    # The new exclusive lease must prove the complete durable
                    # obligation set unclaimed/settled before adopting identity.
                    # Claimed or uncertain preparation remains reconciliation.
                    lease.recover_unprepared_owner(self.store, self.ownership)
            local.handle = coordinator.dispatch(
                principal,
                expected_version=run.version if resume_receipt is None else resume_receipt.after_version,
                decision_id="foreground-initial-generation",
                reservation=(
                    pending["reservation"]
                    if pending and pending["reservation"] is not None
                    else self.generation_reservation
                ),
                pending_intent=pending["intent_id"] if pending else None,
                **({} if resume_receipt is None else dict(resume_operation_id=resume_receipt.operation_id)),
            )
            completed = receiver.receive(principal, local.handle.prepared, release_lease=True)
            local.retired = True
        except Exception as exc:
            # Receiver/coordinator retain exact cleanup and receipts. Never redispatch.
            if getattr(exc, "handle", None) is not None:
                local.handle = exc.handle
        finally:
            local.busy = False
            self._settle_cancel(principal, run.run_id, local)
        if (
            completed is not None
            and completed.disposition == "validation"
            and not self._cancellation.stop_requested(self, run.run_id)
        ):
            return self._scene(principal, run.run_id, contract)
        return self._blocked_status(principal, run.run_id)

    def _scene(self, principal, run_id, contract, *, continuation=False, resume_receipt=None):
        try:
            return self._scene_phase(
                principal,
                run_id,
                contract,
                continuation=continuation,
                **({} if resume_receipt is None else dict(resume_receipt=resume_receipt)),
            )
        except Exception:
            with self._lock:
                local = self._local.get(run_id)
            if local is not None:
                local.busy = False
                self._settle_cancel(principal, run_id, local)
            return self._blocked_status(principal, run_id)

    def _scene_phase(self, principal, run_id, contract, *, continuation=False, resume_receipt=None):
        if self._cancellation.stop_requested(self, run_id):
            return self.status(principal, run_id)
        self._preflight(principal, contract)
        self._ready(contract)
        worker = self.scene_worker_factory(ownership_artifacts=self.ownership)
        lease = self._owner_lease_factory(
            self.private_parent,
            run_id=run_id,
            principal=principal,
            cleanup_verified=worker.cleanup_verified,
        )
        local = SimpleNamespace(
            principal=principal,
            worker=worker,
            lease=lease,
            coordinator=None,
            receiver=None,
            handle=None,
            ports=None,
            stopped=False,
            retired=False,
            busy=True,
        )
        with self._lock:
            local.stopped = self._cancellation.stop_requested(self, run_id)
            self._local[run_id] = local
        if local.stopped:
            lease.release_never_prepared()
            local.retired = True
            return self.status(principal, run_id)
        # New physical owner is held before start_scene reserves its first intent.
        if continuation:
            lease.recover_unprepared_owner(self.store, self.ownership)
        else:
            self.store.begin_owner(lease.owner_id)
        if resume_receipt is None:
            self.service.start_scene(
                principal,
                run_id,
                artifacts=self.artifacts,
                protect=self.authority.protect_public,
                validate_generation_candidate=validate_generation_candidate,
                profile=self.scene_options["profile"],
            )
        ports = self._scene_ports_factory(
            store=self.store,
            authority=self.authority,
            lease=lease,
            worker=worker,
            principal=principal,
            run_id=run_id,
            catalogue_sha256=self.catalogue_sha256,
            artifact_root=self.artifact_root,
            ready=self._ready,
            protect=self.authority.protect_public,
            **self.scene_options,
        )
        with self._lock:
            local.ports = ports
            local.stopped = self._cancellation.stop_requested(self, run_id)
        if local.stopped:
            self._cancellation.stop_local(self, principal, run_id)
        elif continuation:
            local.ports.restore_observations(self.store.result_records(run_id), contract)
        return self._drive_scene(
            principal, run_id, local, **({} if resume_receipt is None else dict(resume_receipt=resume_receipt))
        )

    def _drive_scene(self, principal, run_id, local, *, resume_receipt=None):
        local.busy = True
        try:
            if self._cancellation.stop_requested(self, run_id):
                self._cancellation.stop_local(self, principal, run_id)
            else:
                result = self.service.run_scene(
                    principal,
                    run_id,
                    ports=local.ports,
                    **({} if resume_receipt is None else dict(resume_receipt=resume_receipt)),
                )
                if result.run.state in ("accepted", "stopped"):
                    local.ports.retire_terminal()
                    local.retired = True
        finally:
            local.busy = False
            self._settle_cancel(principal, run_id, local)
        return self.status(principal, run_id)

    def _public(self, value):
        self.authority.protect_public(value)
        return value

    def _unknown(self, run_id):
        return self._public(
            dict(
                disposition="unknown",
                run_id=run_id,
                state="unknown",
                reason="authoritative_store_unavailable",
                available_actions=[],
                ownership="retained_if_held",
            )
        )

    def status(self, principal, run_id):
        self._check(principal)
        validate_operation_id(run_id)
        from isaaclab_arena.agentic_environment_generation.workflow.read_model import workflow_result

        try:
            return workflow_result(self.store, run_id, protect=self.authority.protect_public)
        except StoreUnavailable:
            return self._unknown(run_id)

    def _blocked_status(self, principal, run_id):
        result = self.status(principal, run_id)
        if result["disposition"] != "unknown" and result["state"] not in (
            "accepted",
            "stopped",
            "cancelled",
        ):
            result.update(disposition="blocked", reason="reconciliation_required_no_redispatch")
        return self._public(result)

    def cancel_keyed(self, principal, operation_id, run_id, *, authorize_cancel):
        """Stop before store access; authorize_cancel is trusted check-only composition.

        The required callback checks current cancel permission without grants or
        database lookup. It is never supplied by a transport request. The injected
        stop_only adapter retains exact frozen-creator authentication independently.
        """
        from .commands import COMMAND_BYTES, CancelReceipt, CancelResult, CommandConflict, LocalStopObservation
        from .neo4j_store import OutcomeUnknown, _lookup_transport_errors
        from .scene_evidence_artifacts import _protected

        self._check(principal)
        validate_operation_id(operation_id)
        validate_operation_id(run_id)
        protect = self.authority.protect_public
        if not callable(authorize_cancel) or not callable(protect):
            raise ValueError("trusted cancel authority and public protection required")
        authorize_cancel(principal, run_id)
        _protected(dict(operation_id=operation_id, runId=run_id), protect, max_bytes=COMMAND_BYTES)
        local_stop = self._cancellation.stop_only(self, principal, run_id)
        local_stop = LocalStopObservation.model_validate_json(local_stop.model_dump_json())
        receipt, durable = None, "unknown"
        cleanup, cleanup_status = None, "not_requested"
        try:
            # Admission takes authority before the Neo4j control lock. Keep
            # that order here: cancel_command screens the exact receipt before
            # commit under that DB lock. Local stop above and physical cleanup
            # below must remain outside authority (they may wait on workers).
            with self.authority.mutation_guard():
                value = self.store.cancel_command(operation_id, run_id, local_stop, protect=protect)
            receipt = CancelReceipt.model_validate_json(value.model_dump_json())
            durable = "recorded"
        except CommandConflict:
            durable = "conflict"
        except (OutcomeUnknown, StoreUnavailable, *_lookup_transport_errors()):
            pass
        if receipt is not None:
            # Receipt-only denial is not a cleanup failure.
            _protected(receipt.model_dump(mode="json"), protect, max_bytes=COMMAND_BYTES)
            try:
                from .queries import RunCleanupView

                with self._lock:
                    local = self._local.get(run_id)
                if local is not None and receipt.disposition != "refused":
                    self._cancellation.finish_cancelled(self, principal, run_id, local)
                value = self.store.get_run_cleanup(run_id)
                if value is not None:
                    cleanup = RunCleanupView.model_validate_json(value.model_dump_json())
                    _protected(cleanup.model_dump(mode="json"), protect)
                result = CancelResult(
                    local_stop=local_stop,
                    durable=durable,
                    receipt=receipt,
                    cleanup_status="available",
                    cleanup=cleanup,
                )
                # Check the entire joined envelope too; cleanup may exceed its
                # budget or fail a contextual screen even when it fits alone.
                _protected(result.model_dump(mode="json"), protect)
                return result
            except Exception:
                # Durable fact is known; drop fallible cleanup, not the receipt.
                cleanup, cleanup_status = None, "unavailable"
        result = CancelResult(
            local_stop=local_stop, durable=durable, receipt=receipt, cleanup_status=cleanup_status, cleanup=cleanup
        )
        _protected(result.model_dump(mode="json"), protect)
        return result

    def cancel(self, principal, run_id):
        validate_operation_id(run_id)
        result = self._cancellation.cancel_workflow(self, principal, run_id)
        if not self._owner_control:
            # Preserve the existing in-process result contract outside IPC opt-in.
            result.pop("local_stop", None)
            result.pop("durable_cancellation", None)
        return result

    def _start_control(self, principal, run_id):
        if self._owner_control:
            return self._cancellation.start_owner_control(self, principal, run_id)
        # Ordinary injected compositions retain the same memory fence, no UDS.
        with self._lock:
            state = self._cancel_controls.get(run_id)
            if state is not None and state.principal != principal:
                raise PermissionError("Creator required")
            if state is None:
                self._cancel_controls[run_id] = SimpleNamespace(
                    principal=principal, stopped=False, server=SimpleNamespace(close=lambda: None)
                )
        return None

    def _settle_cancel(self, principal, run_id, local):
        if local.retired:
            return
        # ACK precedes the client's DB request. Retain the actual owner/cleanup
        # for bounded reconciliation, never redispatch or resend private bytes.
        latched = self._cancellation.stop_requested(self, run_id)
        try:
            cancelled = self.store.get_run(run_id).state in ("cancel_requested", "cancelled")
        except Exception:
            cancelled = False
        if not (latched or cancelled):
            return
        self._cancellation.stop_local(self, principal, run_id)
        if not hasattr(local, "cancel_wait_deadline"):
            local.cancel_wait_deadline = time.monotonic() + 20.0
        deadline = local.cancel_wait_deadline
        while True:
            if self._cancellation.finish_cancelled(self, principal, run_id, local):
                return
            if time.monotonic() >= deadline:
                return  # uncertain ownership remains held; no forced unlock
            time.sleep(0.05)

    def _resume_pin(self, receipt):
        """Read the exact acknowledged selection before private mutation; claim rechecks atomically."""
        from .contracts import contract_digest

        preview = self.store.preview_resume(receipt.run_id)
        expected = receipt.selection.model_copy(update={"version": receipt.after_version})
        if (
            preview.selection != expected
            or preview.run is None
            or preview.run.version != receipt.after_version
            or contract_digest(parse_contract(preview.run.contract_json)) != receipt.contract_digest
        ):
            raise ValueError("Resume selection changed")
        return preview.run

    def _resume_reconcile(self, principal, receipt, local):
        """Reconcile only the registered original fence; never advance into scene work."""
        from .contracts import contract_digest

        fence = receipt.selection.fence
        run, attempt, _ = self.service.read_generation_recovery(principal, receipt.run_id, expected_fence=fence)
        if (
            run.version != receipt.after_version
            or contract_digest(parse_contract(run.contract_json)) != receipt.contract_digest
        ):
            raise ValueError("Resume recovery selection changed")
        if local is not None and not local.retired:
            if (
                local.receiver is None
                or local.handle is None
                or local.handle.fence != fence
                or local.handle.prepared is None
                or local.handle.prepared.registration != attempt.registration
            ):
                raise ValueError("Exact local recovery registration required")
            local.busy = True
            try:
                result = local.receiver.receive(principal, local.handle.prepared, release_lease=True)
                local.retired = True
            finally:
                local.busy = False
                self._settle_cancel(principal, receipt.run_id, local)
        else:
            recovery = self._recoveries.get(receipt.run_id)
            newly_acquired = recovery is None
            if newly_acquired:
                recovery = self._recovery_factory(
                    self.private_parent,
                    run_id=receipt.run_id,
                    principal=principal,
                    service=self.service,
                    ownership_artifacts=self.ownership,
                    artifacts=self.artifacts,
                    protect=self.authority.protect_public,
                )
                self._recoveries[receipt.run_id] = recovery
            try:
                result = recovery.recover(release_lease=True, resume_receipt=receipt)
            except Exception:
                if newly_acquired:
                    try:
                        # The lease itself atomically refuses any preparation or
                        # recovery latch. No durable retirement/cleanup is implied.
                        recovery.lease.release_never_prepared()
                    except Exception:
                        pass  # Latched or uncertain release remains cached/owned.
                    else:
                        if self._recoveries.get(receipt.run_id) is recovery:
                            self._recoveries.pop(receipt.run_id)
                raise
            self._recoveries.pop(receipt.run_id, None)
        if result.attempt.fence != fence or result.attempt.registration != attempt.registration:
            raise ValueError("Exact recovery result required")

    def _resume_result(self, principal, receipt, execution, *, observe=False):
        """Keep known admission when an optional current-status read or screen fails."""
        from .commands import ResumeResult
        from .scene_evidence_artifacts import _protected

        protect = self.authority.protect_public
        _protected(receipt.model_dump(mode="json"), protect)
        status_status = "not_requested"
        if observe:
            try:
                result = ResumeResult(
                    receipt=receipt,
                    execution=execution,
                    status_status="available",
                    status=self.status(principal, receipt.run_id),
                )
                _protected(result.model_dump(mode="json"), protect)
                return result
            except Exception:
                status_status = "unavailable"
        result = ResumeResult(receipt=receipt, execution=execution, status_status=status_status)
        _protected(result.model_dump(mode="json"), protect)
        return result

    def resume_keyed(self, principal, operation_id, payload, *, check_resume):
        """Synchronously deliver only this call's acknowledged-fresh continuation."""
        result, drive = self.admit_resume_keyed(principal, operation_id, payload, check_resume=check_resume)
        return result if drive is None else drive()

    def admit_resume_keyed(self, principal, operation_id, payload, *, check_resume):
        """Return immutable admission and an owner-only one-shot continuation.

        check_resume is explicit trusted permission, not read permission or request
        data. Private eligibility is check-only; no callback is resolved before
        service replay. Interrupted deliveries require a new explicit command;
        replay never returns a drive or renews authorization.
        """
        # A synchronous trusted authority callback cannot reenter the service:
        # its receipt read could wait on a control lock whose holder needs the
        # authority guard. Other threads still perform ordinary authorized replay.
        if getattr(_resume_authority_context, "active", False):
            raise RuntimeError("Guarded resume reentry unavailable")
        from .scene_evidence_artifacts import _protected

        def eligibility(principal, contract, selection, *, renew_authorization):
            if self._closed:
                return "not_ready"
            run = self.store.get_run(selection.run_id)
            if run is None or run.version != selection.version or run.contract_json != canonical_json(contract):
                return "not_ready"
            try:
                self._preflight(principal, contract)
                action = self.authority.check_resume_eligibility(
                    principal, contract, run=run, renew_authorization=renew_authorization
                )
                if action != "not_ready":
                    self._ready(contract)
                return action
            except (ValueError, PermissionError):
                return "not_ready"

        admission = self.service.admit_resume(
            principal,
            operation_id,
            payload,
            check_resume=check_resume,
            check_eligibility=eligibility,
            protect=self.authority.protect_public,
        )
        receipt = admission.receipt
        _protected(receipt.model_dump(mode="json"), self.authority.protect_public)
        if admission.fresh is not True or receipt.disposition == "refused":
            return self._resume_result(principal, receipt, "not_requested"), None
        key = (
            receipt.scope.database,
            receipt.scope.deployment_id,
            receipt.scope.workspace_id,
            receipt.operation_id,
            receipt.receipt_digest,
        )
        with self._lock:
            local = self._local.get(receipt.run_id)
            busy = receipt.run_id in self._resume_busy or (local is not None and local.busy)
            if key in self._resume_deliveries or busy or self._closed:
                delivery = None
            else:
                delivery = [False]
                self._resume_deliveries[key] = delivery
                self._resume_busy.add(receipt.run_id)
        if delivery is None:
            return self._resume_result(principal, receipt, "blocked", observe=True), None
        started = [False]

        def drive():
            if getattr(_resume_authority_context, "active", False):
                raise RuntimeError("Resume authority re-entry unavailable")
            with self._lock:
                blocked = started[0] or self._closed
                started[0] = True
            if blocked:
                return self._resume_result(principal, receipt, "blocked")
            execution = "blocked"
            try:
                if self._cancellation.stop_requested(self, receipt.run_id):
                    raise ValueError("Resume locally stopped")
                run = self._resume_pin(receipt)
                self._start_control(principal, receipt.run_id)
                if self._cancellation.stop_requested(self, receipt.run_id):
                    raise ValueError("Resume locally stopped")
                contract = parse_contract(run.contract_json)
                if receipt.selection.branch == "reconciliation":
                    delivery[0] = True
                    self._resume_reconcile(principal, receipt, local)
                else:
                    if receipt.selection.branch not in {"generation", "scene"}:
                        raise ValueError("Resume handoff unavailable")
                    if receipt.selection.branch == "generation":
                        pending = self.store.pending_generation(run.run_id)
                        if (
                            pending is None
                            or pending["intent_id"] != receipt.selection.intent_id
                            or pending["reservation"] is None
                        ):
                            raise ValueError("Original unclaimed reservation required")
                        if local is not None and not local.retired:
                            if (
                                local.stopped
                                or local.ports is not None
                                or (
                                    local.handle is not None
                                    and (local.handle.fence is not None or local.handle.prepared is not None)
                                )
                            ):
                                raise ValueError("Resume local ownership unresolved")
                            local.coordinator.stop_local(principal)
                            local.lease.release_never_prepared()
                            local.retired = True
                    elif local is not None and (local.ports is None or local.retired or local.stopped):
                        raise ValueError("Resume scene ownership unresolved")
                    # Local retirement/pending reads can outlive the first check.
                    run = self._resume_pin(receipt)
                    # No DB, coordinator, lease or port calls under this authority guard.
                    _resume_authority_context.active = True
                    try:
                        with self.authority.mutation_guard():
                            if delivery[0] or self._cancellation.stop_requested(self, receipt.run_id):
                                raise ValueError("Resume delivery consumed or stopped")
                            delivery[0] = True
                            self.authority.apply_resume_authority(
                                principal,
                                contract,
                                run=run,
                                action=receipt.authorization_action,
                                catalogue_sha256=self.catalogue_sha256,
                            )
                    finally:
                        _resume_authority_context.active = False
                    if receipt.selection.branch == "generation":
                        self._generate(principal, run, contract, pending=pending, resume_receipt=receipt)
                    elif local is None:
                        self._scene(principal, run.run_id, contract, continuation=True, resume_receipt=receipt)
                    else:
                        local.ports.require_held_owner()
                        local.ports.restore_observations(self.store.result_records(run.run_id), contract)
                        self._drive_scene(principal, run.run_id, local, resume_receipt=receipt)
                execution = "returned"
            except Exception:
                # Admission is immutable; partial grants/claim/preparation are not rolled back.
                delivery[0] = True
            finally:
                with self._lock:
                    self._resume_busy.discard(receipt.run_id)
            return self._resume_result(principal, receipt, execution, observe=True)

        return self._resume_result(principal, receipt, "not_requested"), drive

    def _resume_authority(self, principal, run, contract, *, renew_authorization):
        """Capture absent local grants; only explicit renewal replaces old grants."""
        self._preflight(principal, contract)
        with self.authority.mutation_guard():
            try:
                self.authority.require_scene_execute(principal, contract, run_id=run.run_id)
            except ValueError as exc:
                if str(exc) == "Explicit execution binding required":
                    self.authority.bind_run(
                        principal,
                        run.operation_id,
                        contract,
                        run_id=run.run_id,
                        catalogue_sha256=self.catalogue_sha256,
                    )
                    self.authority.bind_workflow_models(principal, contract, run_id=run.run_id)
                elif renew_authorization:
                    self.authority.renew_run(principal, contract, run_id=run.run_id)
                else:
                    raise
            else:
                if renew_authorization:
                    self.authority.renew_run(principal, contract, run_id=run.run_id)

    def resume(self, principal, run_id, *, renew_authorization=False):
        if getattr(_resume_authority_context, "active", False):
            raise RuntimeError("Guarded resume reentry unavailable")
        if type(renew_authorization) is not bool:
            raise TypeError("Explicit boolean renewal required")
        current = self.status(principal, run_id)
        if current["disposition"] == "unknown" or current["state"] in (
            "accepted",
            "stopped",
            "cancelled",
        ):
            return current
        if "resume" not in current["available_actions"]:
            return self._blocked_status(principal, run_id)
        local = self._local.get(run_id)
        if local is not None and local.busy:
            return self._public(
                dict(
                    current,
                    disposition="blocked",
                    reason="foreground_operation_in_progress",
                )
            )
        try:
            self._start_control(principal, run_id)
            if self._cancellation.stop_requested(self, run_id):
                self._cancellation.stop_local(self, principal, run_id)
                if local is not None:
                    self._settle_cancel(principal, run_id, local)
                return self._blocked_status(principal, run_id)
            scene = self.store.scene_snapshot(run_id)
            if scene is not None:
                if scene.intent is not None and scene.intent.status == "reserved" and scene.intent.worker_fence is None:
                    contract = parse_contract(scene.run.contract_json)
                    self._resume_authority(principal, scene.run, contract, renew_authorization=renew_authorization)
                    if local is None:
                        return self._scene(principal, run_id, contract, continuation=True)
                    if local.ports is None or local.retired or local.stopped:
                        return self._blocked_status(principal, run_id)
                    local.ports.require_held_owner()
                    local.ports.restore_observations(
                        self.store.result_records(run_id),
                        parse_contract(scene.run.contract_json),
                    )
                    return self._drive_scene(principal, run_id, local)
                return self._blocked_status(principal, run_id)
            pending = self.store.pending_generation(run_id)
            if pending is not None:
                run = self.store.get_run(run_id)
                contract = parse_contract(run.contract_json)
                self._resume_authority(principal, run, contract, renew_authorization=renew_authorization)
                if local is not None and not local.retired:
                    # The authoritative pending read excludes a claim. Disarm the
                    # old coordinator, then release only its exact never-prepared
                    # capability; a preparation latch still vetoes this path.
                    if (
                        local.stopped
                        or local.ports is not None
                        or (
                            local.handle is not None
                            and (local.handle.fence is not None or local.handle.prepared is not None)
                        )
                    ):
                        return self._blocked_status(principal, run_id)
                    local.coordinator.stop_local(principal)
                    local.lease.release_never_prepared()
                    local.retired = True
                return self._generate(principal, run, contract, pending=pending)
            if local is not None and local.receiver is not None and local.handle is not None and not local.retired:
                result = local.receiver.receive(principal, local.handle.prepared, release_lease=True)
            else:
                recovery = self._recoveries.get(run_id)
                if recovery is None:
                    recovery = self._recovery_factory(
                        self.private_parent,
                        run_id=run_id,
                        principal=principal,
                        service=self.service,
                        ownership_artifacts=self.ownership,
                        artifacts=self.artifacts,
                        protect=self.authority.protect_public,
                    )
                    self._recoveries[run_id] = recovery
                result = recovery.recover(release_lease=True)
                # Successful recovery releases this physical lease. A later
                # preflight denial must not cache an unusable recovery handle.
                self._recoveries.pop(run_id, None)
            if result.disposition == "validation":
                contract = parse_contract(result.run.contract_json)
                self._resume_authority(principal, result.run, contract, renew_authorization=renew_authorization)
                return self._scene(principal, run_id, contract)
            return self.status(principal, run_id)
        except Exception:
            with self._lock:
                local = self._local.get(run_id)
            if local is not None:
                self._settle_cancel(principal, run_id, local)
            return self._blocked_status(principal, run_id)

    def close(self):
        if self._closed:
            return
        try:
            # Attempt every owner even if another owner's cleanup fails.
            with self._lock:
                owners = tuple(self._local.items())
            for run_id, local in owners:
                try:
                    self._cancellation.stop_local(self, local.principal, run_id)
                    if not local.retired:
                        self._cancellation.finish_cancelled(self, local.principal, run_id, local)
                except Exception:
                    pass  # never release uncertain physical ownership here
        finally:
            try:
                self._cancellation.close_controls(self)
            finally:
                self.authority.close()
                for resource in self._owned_resources:
                    resource.close()
                self._closed = True
