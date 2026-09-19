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

    def read_generation_recovery(self, principal, run_id):
        """Authenticate the exact original attempt without issuing execution authority."""
        self._authority.require_read(principal)
        run = self._store.get_run(run_id)
        attempt = self._store.get_generation_attempt(run_id)
        if (
            attempt is None
            or attempt.fence.run_id != run_id
            or attempt.authorization.principal != principal
            or attempt.contract_json != run.contract_json
        ):
            raise ValueError("Original generation recovery binding required")
        return run, attempt, self._store.get_owner()

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

    def start_scene(self, principal, run_id, *, artifacts, protect, validate_generation_candidate, profile):
        """Reverify retained generation bytes and stage the original candidate.

        The trusted composition passes workflow.validation.validate_generation_candidate
        as the schema port. Keeping the callable explicit avoids importing native
        registries into this runtime-independent service. Synthetic test validators
        must stay labelled synthetic; they are not actual-schema acceptance.
        """
        import json

        from .artifacts import GenerationArtifacts
        from .scene_loop import candidate_record

        self._authority.require_read(principal)
        run, attempt, _ = self.read_generation_recovery(principal, run_id)
        if type(artifacts) is not GenerationArtifacts or attempt.receipt is None or attempt.cleanup is None:
            raise ValueError("retained generation bytes and cleanup required")
        files = artifacts.verified_bytes(attempt.receipt, protect=protect)
        validation = validate_generation_candidate(artifacts, attempt.receipt, protect=protect)
        if hasattr(validation, "model_dump"):
            validation = validation.model_dump(mode="json")
        candidate = candidate_record(run_id, json.loads(files["candidate.json"]), source_id=attempt.fence.attempt_id)
        return self._store.begin_scene(run_id, run.version, candidate, validation, profile)

    def run_scene(self, principal, run_id, *, ports):
        """Drive the retained scene loop through explicitly trusted bounded ports.

        Native adapters, physical owner-local stop and transport enforcement remain
        composition gates, not inferred from a profile label or successful callback.
        With profile.owned_worker=True the required trusted hooks are:
        require_held_owner() -> OwnerView (checks the actual held lease),
        prepare_worker(intent, candidate, original, contract) -> WorkerRegistration,
        cleanup_worker(intent) -> CleanupEvidence. Prepare receives worker_fence;
        execute receives its committed registration and release. Cleanup MUST retain
        its local witness and handle partial prepare even without a registration.
        execute must use authority.release_guard(..., run_id=...), recheck exact
        retained fence/registration and lease, then resolve private_model_config
        inside that guard before the one bounded send. Its deadline is the minimum
        private_model_deadline for every required role, original run deadline and
        stage runtime allowance; generation snapshot expiry is NOT assessment TTL.
        No private resolution or
        SDK/runtime operation belongs in a store transaction. Ports are application
        composition, never user-supplied callbacks or booleans.
        require_bounded_capability is a check-only trusted port returning literal
        True after validating current authority/configuration AND enforced call,
        token, cost, runtime and capture ceilings for this reservation. Missing or
        false capability blocks release. Native composition must bind the existing
        authority token/cost check and CallAllowance.token_cost_bounded, not copy
        reservation values or accept provider self-reported usage as proof.
        """
        from .repairs import _scene_json
        from .scene_loop import Observation, ScenePortProfile, SceneResult

        self._authority.require_read(principal)
        profile = ScenePortProfile.model_validate_json(ports.profile.model_dump_json())
        if profile.owned_worker and any(
            not callable(getattr(ports, name, None))
            for name in ("prepare_worker", "cleanup_worker", "require_held_owner")
        ):
            raise ValueError("managed scene worker ports required")
        while True:
            snapshot = self._store.scene_snapshot(run_id)
            if snapshot is None:
                raise ValueError("retained validated scene required")
            if snapshot.profile != profile:
                raise ValueError("scene port profile changed")
            if snapshot.run.state != "running" or snapshot.intent is None:
                return snapshot
            if snapshot.intent.status != "reserved":
                # Released effects are never attempted again, including fresh
                # interpreter recovery. The caller must reconcile exact output.
                if snapshot.intent.status == "released":
                    self._store.mark_scene_unknown(run_id, snapshot.intent.intent_id)
                    return self._store.scene_snapshot(run_id)
                return snapshot
            if snapshot.intent.worker_fence is not None:
                return snapshot  # Prepared/ambiguous ownership is never fresh work.
            contract = parse_contract(snapshot.run.contract_json)
            auth = ports.authorize(principal, contract, snapshot.intent.action)
            ready = ports.ready(contract)
            auth = ports.authorize(principal, contract, snapshot.intent.action)
            bounded = getattr(ports, "require_bounded_capability", None)
            if not callable(bounded) or bounded(principal, contract, snapshot.intent.reservation) is not True:
                raise ValueError("bounded scene port capability required")
            failed = False
            worker_intent = None
            release_args = {}
            try:
                if profile.owned_worker:
                    owner = ports.require_held_owner()
                    fence = self._store.claim_scene_worker(
                        run_id, snapshot.intent.intent_id, owner.owner_id, owner.owner_epoch
                    )
                    worker_intent = snapshot.intent.model_copy(update={"worker_fence": fence})
                    registration = ports.prepare_worker(worker_intent, snapshot.candidate, snapshot.original, contract)
                    worker_intent = worker_intent.model_copy(update={"worker_registration": registration})
                    self._store.register_scene_worker(fence, registration)
                    if ports.require_held_owner() != owner:
                        raise ValueError("scene owner changed")
                    auth = ports.authorize(principal, contract, snapshot.intent.action)
                    ready = ports.ready(contract)
                    if bounded(principal, contract, snapshot.intent.reservation) is not True:
                        raise ValueError("bounded scene port capability revoked")
                    release_args = dict(fence=fence, registration_id=registration.registration_id)
                if not self._store.release_scene(
                    run_id, snapshot.intent.intent_id, auth, readiness=ready, **release_args
                ):
                    return self._store.scene_snapshot(run_id)
                released = self._store.scene_snapshot(run_id)
                # Recheck after committed release; a denial is unresolved, not retry.
                auth = ports.authorize(principal, contract, released.intent.action)
                ready = ports.ready(contract)
                checked = self._store.check_scene_release(
                    run_id, released.intent.intent_id, auth, readiness=ready, **release_args
                )
                if checked != released.intent:
                    raise ValueError("committed scene release changed")
                if profile.owned_worker and ports.require_held_owner() != owner:
                    raise ValueError("scene owner changed")
                if bounded(principal, contract, released.intent.reservation) is not True:
                    raise ValueError("bounded scene port capability revoked")
                if released.run.state != "running":
                    raise ValueError("scene cancelled after release")
                output = ports.execute(released.intent, released.candidate, released.original, contract)
                if released.intent.action == "observe":
                    checked = ports.verify_observation(output, contract, released.candidate)
                    result = SceneResult(observation=Observation.model_validate(checked))
                else:
                    try:
                        ports.validate_candidate(output)
                        result = SceneResult(candidate_json=_scene_json(output))
                    except ValueError:
                        result = SceneResult(failure="invalid_candidate")
                if self._store.get_run(run_id).state != "running":
                    raise ValueError("scene cancelled during execution")
            except Exception:
                if not profile.owned_worker and self._store.scene_snapshot(run_id).intent.status == "reserved":
                    raise
                self._store.mark_scene_unknown(run_id, snapshot.intent.intent_id)
                failed = True
            finally:
                if worker_intent is not None:
                    # Stop remains executable without database access. The port
                    # retains its local witness if durable acknowledgement fails.
                    cleanup = ports.cleanup_worker(worker_intent)
                    self._store.acknowledge_scene_cleanup(worker_intent.worker_fence, cleanup)
            current = self._store.scene_snapshot(run_id)
            if failed or current.run.state != "running":
                return current
            self._store.finish_scene(run_id, released.intent.intent_id, current.run.version, result)

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
