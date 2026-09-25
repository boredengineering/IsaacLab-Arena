# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Owned model composition for ScenePorts; capture remains explicitly synthetic.

Composition order: screen the full fresh contract before persistence, bind_run,
bind_workflow_models, then adopt generation with receiver release_lease=True to
retire its owner BEFORE reserving scene work. Acquire and register a fresh held
scene owner BEFORE service.start_scene; construct these ports and run_scene next.
All subsequent scene stages retain the SAME physical flock. Call retire_terminal
only after terminal store readback. A reserved scene intent prevents bootstrap
owner retirement; do not reverse this order.
No callback replaces model engines, workflow routing or retained evidence checks.
"""

import json
import time
from contextlib import contextmanager
from threading import RLock

from isaaclab_arena.agentic_environment_generation.workflow.contracts import parse_contract
from isaaclab_arena.agentic_environment_generation.workflow.coordinator import PrepareFailed
from isaaclab_arena.agentic_environment_generation.workflow.evidence import CandidateBinding, EvidenceCohort
from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import _protected, canonical
from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import visual_request
from isaaclab_arena.agentic_environment_generation.workflow.scene_ports import ScenePorts

from .web_api.scene_worker import retain_request


class ForegroundScenePorts(ScenePorts):
    """Bind service hooks to exact registered children and private role authority.

    ready(contract) returns the store-compatible durable readiness receipt. The
    caller owns the same-store WorkflowService, explicit grants and owner startup.
    Capture is a trusted bounded synthetic context manager, not native permission.
    The authority must exclusively own its sources/grants through mutation_guard.
    """

    def __init__(
        self, *, store, authority, lease, worker, principal, run_id, catalogue_sha256, artifact_root, ready, **options
    ):
        self.store, self.authority, self.lease, self.worker = (store, authority, lease, worker)
        self.principal, self.run_id = principal, run_id
        self.catalogue_sha256, self.artifact_root = catalogue_sha256, artifact_root
        self._interlock = RLock()
        self._prepared_workers, self._cleanups, self._results = {}, {}, {}
        self._previous = None
        self._active = None
        self._stopped = False
        if authority.store is not store or not options["profile"].owned_worker:
            raise ValueError("Exact owned scene composition required")
        super().__init__(
            authorize=self._authorization,
            ready=ready,
            refine=self._refine_child,
            visual=self._visual_child,
            check_active=self._check_active,
            **options,
        )
        self.require_held_owner()

    @property
    def prepared_workers(self):
        """Exact local cleanup capabilities, including partially prepared handles."""
        return tuple(self._prepared_workers.values())

    def _check_active(self):
        if self._stopped:
            raise ValueError("Scene locally stopped")
        run = self.store.get_run(self.run_id)
        if run.state != "running":
            raise ValueError("Inactive scene run")
        self.require_held_owner()
        self.authority.require_scene_execute(self.principal, parse_contract(run.contract_json), run_id=self.run_id)

    def _authorization(self, principal, contract, action):
        if principal != self.principal or action not in ("observe", "repair"):
            raise ValueError("Exact scene principal and action required")
        return self.authority.require_scene_execute(principal, contract, run_id=self.run_id)

    def require_held_owner(self):
        """Return durable owner only after checking the actual local held lease."""
        self.lease.require_held(self.run_id, self.principal)
        owner = self.store.get_owner()
        if owner is None or not owner.dirty or owner.owner_id != self.lease.owner_id:
            raise ValueError("Exact active scene owner required")
        return owner

    def require_bounded_capability(self, principal, contract, reservation):
        super().require_bounded_capability(principal, contract, reservation)
        self.authority.require_scene_execute(self.principal, contract, run_id=self.run_id)
        bounds = self.authority.require_workflow_model_bounds(self.principal, contract)
        for role, bound in bounds.items():
            if canonical(self.model_ceilings[role].per_call_bound) != canonical(bound):
                raise ValueError("Frozen role accounting mismatch")
        return True

    def prepare_worker(self, intent, candidate, original, contract, **stage_args):
        """Latch exact claimed fence before spawn; never erase ambiguous preparation."""
        with self._interlock:
            if self._stopped:
                raise ValueError("Scene locally stopped")
            owner = self.require_held_owner()
            fence = intent.worker_fence
            retained = self.store.get_scene_intent(self.run_id, intent.intent_id)
            if (
                fence is None
                or fence.run_id != self.run_id
                or (fence.owner_id, fence.owner_epoch) != (owner.owner_id, owner.owner_epoch)
                or canonical(retained.model_dump(mode="json")) != canonical(intent.model_dump(mode="json"))
                or intent.status != "reserved"
                or intent.worker_registration is not None
                or intent.intent_id in self._prepared_workers
            ):
                raise ValueError("Exact fresh claimed scene fence required")
            if self._previous is None:
                self.lease.mark_prepared(fence)
            else:
                previous = self._prepared_workers[self._previous]
                self.lease.advance_scene(self.store, previous.registration, self._cleanups[self._previous], fence)
            try:
                prepared = self._prepare_child(intent, candidate, original, contract, **stage_args)
            except PrepareFailed as exc:
                self._prepared_workers[intent.intent_id] = exc.prepared
                raise
            self._prepared_workers[intent.intent_id] = prepared
            return prepared.registration

    def _prepare_child(self, intent, candidate, original, contract):
        return self.worker.prepare(
            intent.worker_fence,
            contract,
            timeout_s=min(intent.reservation.runtime_allowance_seconds, contract.budget.per_operation_timeout_seconds),
        )

    def execute(self, intent, candidate, original, contract, **stage_args):
        with self._interlock:
            prepared = self._prepared_workers.get(intent.intent_id)
            if (
                prepared is None
                or intent.worker_registration is None
                or canonical(prepared.registration.model_dump(mode="json"))
                != canonical(intent.worker_registration.model_dump(mode="json"))
            ):
                raise ValueError("Exact prepared scene registration required")
            self._active = (intent, candidate, original, contract)
        try:
            return super().execute(intent, candidate, original, contract, **stage_args)
        finally:
            self._active = None

    def _visual_child(self, *, request, frames, allowance):
        intent, candidate, original, contract = self._active
        criterion = next(c for c in contract.criteria if c.criterion_id == request["criterion_id"])
        binding = CandidateBinding.model_validate(request["candidate"])
        cohort = EvidenceCohort.model_validate(request["cohort"])
        if binding.candidate_digest != candidate.digest:
            raise ValueError("Visual candidate mismatch")
        receipt = self.artifacts.load_receipt(
            binding,
            cohort,
            kind="observation",
            manifest_digest=request["observation_manifest_digest"],
            protect=self.protect,
        )
        expected = visual_request(criterion, binding, cohort, self.artifacts, receipt, protect=self.protect)
        payload = self.artifacts.verified_payload(receipt, protect=self.protect)
        if canonical(request) != canonical(expected) or canonical(frames) != canonical(payload["frames"]):
            raise ValueError("Exact retained visual request required")
        result = self._call_child(
            "assess",
            dict(
                candidate=binding.model_dump(mode="json"),
                cohort=cohort.model_dump(mode="json"),
                criterion=criterion.model_dump(mode="json"),
                observation_manifest_digest=receipt.manifest_digest,
            ),
        )
        return result.output["raw_response"].encode("utf-8")

    def _refine_child(self, *, parent, original, feedback, contract, allowance):
        intent, candidate, baseline, active_contract = self._active
        if parent != candidate or original != baseline or contract != active_contract:
            raise ValueError("Exact refinement lineage required")
        # ScenePorts has re-evaluated retained feedback; recheck the durable parent
        # and decision rather than accepting arbitrary model-provided feedback.
        snapshot = self.store.scene_snapshot(self.run_id)
        if snapshot.candidate != parent or snapshot.original != original or snapshot.decision.action != "repair":
            raise ValueError("Retained repair decision required")
        if canonical(feedback["assessment"]) != canonical(snapshot.decision.assessment.model_dump(mode="json")):
            raise ValueError("Retained repair assessment changed")
        result = self._call_child("refine", dict(base_spec=json.loads(parent.scene_json), feedback=feedback))
        # The whole proposal (warnings/traces included) is screened BEFORE spec
        # projection and before any service/store candidate persistence.
        _protected(result.output, self.protect)
        return result.output["spec"]

    def _call_child(self, action, data):
        intent, candidate, original, contract = self._active
        prepared = self._prepared_workers[intent.intent_id]
        registration = prepared.registration
        payload = retain_request(
            self.artifacts.area,
            root=self.artifact_root,
            registration=registration,
            contract=contract,
            action=action,
            data=data,
            protect=self.protect,
        )
        role = "assessment" if action == "assess" else "generation"
        with self._interlock, self.authority.release_guard(self.principal, contract, run_id=self.run_id):
            if self._stopped:
                raise ValueError("Scene locally stopped")
            self.require_held_owner()
            auth = self.authority.require_scene_execute(self.principal, contract, run_id=self.run_id)
            retained = self.store.get_scene_intent(self.run_id, intent.intent_id)
            checked = self.store.check_scene_release(
                self.run_id,
                intent.intent_id,
                auth,
                readiness=self.ready(contract),
                fence=registration.fence,
                registration_id=registration.registration_id,
            )
            if any(
                canonical(item.model_dump(mode="json")) != canonical(intent.model_dump(mode="json"))
                for item in (retained, checked)
            ):
                raise ValueError("Exact committed scene release required")
            self.require_bounded_capability(self.principal, contract, intent.reservation)
            config = self.authority.private_model_config(self.principal, contract, run_id=self.run_id, role=role)
            bounds = self.authority.require_workflow_model_bounds(self.principal, contract)
            deadlines = [
                self.authority.private_model_deadline(self.principal, contract, run_id=self.run_id, role=r)
                for r in bounds
            ]
            admitted = self.store.get_generation_attempt(self.run_id).admitted_at
            ceiling = self.ceiling_for(intent.action)
            deadline = min(
                *deadlines,
                admitted + contract.budget.total_deadline_seconds,
                intent.released_at + intent.reservation.runtime_allowance_seconds,
                time.time() + ceiling.timeout_seconds,
            )
            if deadline <= max(time.time(), self.authority.clock()):
                raise ValueError("Scene role deadline expired")
            # Restrict child allowance to both the committed reservation and the
            # configured ceiling. Scene-only reservation counters stay in store.
            reservation = dict(
                model_calls=ceiling.max_calls,
                model_tokens=ceiling.max_tokens,
                cost_ceiling_usd=float(ceiling.max_cost_usd),
                runtime_allowance_seconds=intent.reservation.runtime_allowance_seconds,
            )
            packet = dict(
                inputs=dict(
                    operation="new",
                    prompt=contract.source.prompt,
                    retrieval_policy="allow_fallback",
                    execution_catalogue_sha256=self.catalogue_sha256,
                    scene_action=action,
                    scene_payload=payload,
                ),
                config=config,
                graph_config=None,
                workflow_execution=dict(
                    version=1,
                    fence=registration.fence.model_dump(mode="json"),
                    registration=registration.model_dump(mode="json"),
                    reservation=reservation,
                    admitted_at=admitted,
                    released_at=intent.released_at,
                    deadline=deadline,
                ),
            )
            encoded = json.dumps(packet, allow_nan=False, separators=(",", ":")).encode() + b"\n"
            self.lease.require_held(self.run_id, self.principal)
            # Match the transport's request-bounded protocol. Legacy/synthetic
            # packets have no SDK-send handshake; bounded packets must bind it.
            if "request_bounds" in config:
                self.worker.bind_model_send(
                    prepared, lambda frozen: self._model_send_guard(intent, contract, prepared, role, frozen)
                )
            self.worker.send(prepared, encoded, timeout_s=min(2.0, deadline - time.time()))
        result = self.worker.receive(prepared, protect=self.protect)
        self._results[intent.intent_id] = result
        _protected(result.output, self.protect)
        return result

    @contextmanager
    def _model_send_guard(self, intent, contract, prepared, role, config):
        """Revalidate the same reserved scene release just before each SDK transmission."""
        with self._interlock, self.authority.release_guard(self.principal, contract, run_id=self.run_id):
            self._check_active()
            registration = prepared.registration
            auth = self.authority.require_scene_execute(self.principal, contract, run_id=self.run_id)
            retained = self.store.check_scene_release(
                self.run_id,
                intent.intent_id,
                auth,
                readiness=self.ready(contract),
                fence=registration.fence,
                registration_id=registration.registration_id,
            )
            if (
                retained != intent
                or self.authority.private_model_config(self.principal, contract, run_id=self.run_id, role=role)
                != config
            ):
                raise ValueError("Scene send binding changed")
            self.require_bounded_capability(self.principal, contract, intent.reservation)
            yield

    def cleanup_worker(self, intent):
        """Stop without authority or DB access; retain physical witness for later advance."""
        prepared = self._prepared_workers.get(intent.intent_id)
        if prepared is None:
            raise ValueError("Uncertain preparation retains ownership")
        evidence = self.worker.stop_owned(prepared, timeout_s=3)
        if self.worker.cleanup_verified(prepared.registration, evidence) is not True:
            raise ValueError("Trusted scene cleanup required")
        self._cleanups[intent.intent_id] = evidence
        self._previous = intent.intent_id
        return evidence

    def stop_local(self):
        """Fence prepare/send and stop exact local children before any database IO."""
        with self._interlock:
            self._stopped = True
            result = []
            for intent_id, prepared in self._prepared_workers.items():
                evidence = self.worker.stop_owned(prepared, timeout_s=3)
                if self.worker.cleanup_verified(prepared.registration, evidence) is not True:
                    raise ValueError("Trusted scene cleanup required")
                self._cleanups[intent_id] = evidence
                self._previous = intent_id
                result.append((prepared.registration.fence, evidence))
            return tuple(result)

    def retire_cancelled(self):
        """Unlock only after exact local cleanup plus authoritative cancelled readback."""
        with self._interlock:
            if not self._stopped or self.store.get_run(self.run_id).state != "cancelled" or self._previous is None:
                raise ValueError("Settled cancelled scene required")
            for intent_id, prepared in self._prepared_workers.items():
                retained = self.store.get_scene_intent(self.run_id, intent_id)
                evidence = self._cleanups[intent_id]
                if (
                    retained.worker_registration != prepared.registration
                    or retained.worker_cleanup != evidence
                    or self.worker.cleanup_verified(prepared.registration, evidence) is not True
                ):
                    raise ValueError("Exact cancellation cleanup readback required")
            prepared = self._prepared_workers[self._previous]
            self.lease.retire_and_release(self.store, prepared.registration, self._cleanups[self._previous])

    def retire_terminal(self):
        """Retire only after exact produced+cleanup and terminal authoritative readback."""
        with self._interlock:
            snapshot = self.store.scene_snapshot(self.run_id)
            if snapshot.run.state not in ("accepted", "stopped") or self._previous is None:
                raise ValueError("Settled terminal scene required")
            prepared = self._prepared_workers[self._previous]
            evidence = self._cleanups[self._previous]
            self.lease.require_scene_settled(self.store, prepared.registration, evidence)
            self.lease.retire_and_release(self.store, prepared.registration, evidence)
