# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded local restart reconciliation, never permission to release or resend.

The caller supplies the SAME scoped private parent and concrete artifact area.
A missing registration/witness, foreign locality, or unanchored live group keeps
ownership blocked. Files are evidence, not a second workflow authority. No
Python deadline here can preempt a hung kernel syscall.
"""

import json
import os
import secrets
import socket

from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea, ArtifactError
from isaaclab_arena.agentic_environment_generation.workflow.artifacts import digest, encoded
from isaaclab_arena.agentic_environment_generation.workflow.contracts import parse_contract
from isaaclab_arena.agentic_environment_generation.workflow.coordinator import CompletionResult
from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence, ReconciliationReason
from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

from .foreground_owner import ForegroundOwnerLease
from .web_api.owned_process_group import OwnedProcessGroup, boot_id


class OwnershipArtifacts:
    """Separate v1 local ownership witness; WorkerRegistration stays unchanged."""

    def __init__(self, area):
        if type(area) is not ArtifactArea:
            raise ValueError("Concrete ownership artifact area required")
        self.area = area

    @staticmethod
    def _binding(registration):
        return {"schema": 1, "kind": "foreground-ownership", "registration": registration.model_dump(mode="json")}

    def write(self, registration, group):
        group.members()
        if len(group.witnesses) > 256:
            raise ValueError("Ownership witness limit")
        binding = self._binding(registration)
        version = digest(encoded(binding))
        value = {
            "schema": 1,
            "registration": registration.model_dump(mode="json"),
            "pid_namespace": os.readlink("/proc/self/ns/pid"),
            "members": {str(pid): start for pid, start in group.witnesses.items()},
        }
        files = {"ownership.json": encoded(value)}
        with self.area.writer_lock():
            manifest = self.area.expected_manifest(version, files, binding)
            if not self.area.has_final("foreground-ownership", version):
                self.area.stage(version, files, binding)
            self.area.promote(version, "foreground-ownership", version, manifest)
        return version

    def load(self, registration, *, previous_identity=None):
        binding = self._binding(registration)
        version = digest(encoded(binding))
        manifest = self.area.read_final_manifest("foreground-ownership", version, binding=binding)
        files = self.area.verify(f"final/foreground-ownership/{version}", manifest)
        if set(files) != {"ownership.json"} or len(files["ownership.json"]) > 32768:
            raise ValueError("Invalid ownership witness")
        value = json.loads(files["ownership.json"])
        if (
            set(value) != {"schema", "registration", "pid_namespace", "members"}
            or type(value["schema"]) is not int
            or value["schema"] != 1
            or encoded(value["registration"]) != encoded(binding["registration"])
            or type(value["pid_namespace"]) is not str
            or type(value["members"]) is not dict
            or not 1 <= len(value["members"]) <= 256
            or any(
                not pid.isdecimal()
                or str(int(pid)) != pid
                or int(pid) <= 0
                or type(start) is not str
                or not start.isdecimal()
                for pid, start in value["members"].items()
            )
            or value["members"].get(str(registration.pid)) != str(registration.start_ticks)
        ):
            raise ValueError("Invalid ownership witness")
        # A reboot proves old-boot processes cannot execute, but only a checked
        # original instance may bind that proof to this local retained worker.
        previous_boot = False
        if previous_identity is not None:
            from isaaclab_arena.agentic_environment_generation.workflow.api.instance import same_process

            if (
                same_process(previous_identity)
                or previous_identity["boot"] != registration.boot
                or previous_identity["namespace"] != value["pid_namespace"]
                or previous_identity["pid"] != previous_identity["pgid"]
                or previous_identity["pid"] != previous_identity["sid"]
                or not registration.fence.owner_id.startswith(f"foreground-{previous_identity['pid']}-")
            ):
                raise ValueError("Original stopped instance ownership required")
            previous_boot = registration.boot != boot_id()
        # Mandatory BEFORE construction: OwnedProcessGroup itself scans /proc.
        if (
            registration.host != socket.gethostname()
            or (not previous_boot and registration.boot != boot_id())
            or (not previous_boot and value["pid_namespace"] != os.readlink("/proc/self/ns/pid"))
            or registration.pid != registration.pgid
            or registration.pid != registration.sid
        ):
            raise ValueError("Ownership locality mismatch")
        with self.area.writer_lock():
            if not self.area.has_final("foreground-ownership", version):
                raise ArtifactError("Final ownership recovery artifact required")
            self.area.promote(version, "foreground-ownership", version, manifest)
        return dict(
            boot_id=registration.boot,
            start_ticks=str(registration.start_ticks),
            pgid=registration.pgid,
            sid=registration.sid,
            members=value["members"],
        )


class ForegroundGenerationRecovery:
    """Acquire the scope flock before reading the original fence; never begin an owner.

    recover(release_lease=False) retains ownership for later workflow stages.
    No worker transport, execution grant resolver or release API is composed here.
    """

    def __init__(self, private_parent, *, run_id, principal, service, ownership_artifacts, artifacts, protect):
        if type(service) is not WorkflowService or type(ownership_artifacts) is not OwnershipArtifacts:
            raise ValueError("Trusted concrete recovery composition required")
        self._service, self._ownership, self._artifacts, self._protect = (
            service,
            ownership_artifacts,
            artifacts,
            protect,
        )
        self._principal, self._run_id = principal, run_id
        self._observed = None
        self.lease = ForegroundOwnerLease(
            private_parent, run_id=run_id, principal=principal, cleanup_verified=self.cleanup_verified
        )
        self._group = None

    def cleanup_verified(self, registration, evidence):
        return (
            self._observed is not None
            and self._observed[0] == registration
            and self._observed[1] is evidence
            and self._group is not None
            and self._group.cleaned
        )

    def _historical_replay(self, run, attempt, *, release_lease, expected_fence=None):
        """Observe a settled retired predecessor without touching replacement ownership."""
        fence = attempt.fence
        lookup = getattr(self._service.bound_store, "get_retired_owner", None)
        retired = lookup(fence.owner_id) if callable(lookup) else None
        if (
            retired is None
            or retired.dirty is not False
            or (retired.owner_id, retired.owner_epoch) != (fence.owner_id, fence.owner_epoch)
            or attempt.cleanup is None
            or attempt.cleanup.registration != attempt.registration
        ):
            raise ValueError("Original registered owner retirement required; reconciliation blocked")
        if attempt.receipt is not None:
            self._service.prepare_generation_adoption(
                self._principal, fence, attempt.receipt, artifacts=self._artifacts, protect=self._protect
            )
        # Current cancellation may have won while artifact protection was running.
        run, retained, _ = self._service.read_generation_recovery(
            self._principal,
            self._run_id,
            **({} if expected_fence is None else dict(expected_fence=expected_fence)),
        )
        if (
            retained.fence != fence
            or retained.registration != attempt.registration
            or retained.receipt != attempt.receipt
            or retained.cleanup != attempt.cleanup
        ):
            raise ValueError("Historical recovery readback mismatch")
        disposition = "cancelled" if run.state == "cancelled" else "validation"
        if disposition == "validation" and (
            retained.receipt is None or (run.state, run.phase) != ("running", "validation")
        ):
            raise ValueError("Historical generation outcome unresolved")
        if release_lease:
            self.lease.release_never_prepared()
        return CompletionResult(disposition, run, retained)

    def recover(self, *, release_lease=True, resume_receipt=None):
        self.lease.require_held(self._run_id, self._principal)
        read_args = {}
        if resume_receipt is not None:
            from isaaclab_arena.agentic_environment_generation.workflow.commands import ResumeReceipt

            resume_receipt = ResumeReceipt.model_validate_json(resume_receipt.model_dump_json())
            if resume_receipt.disposition != "reconciliation_admitted" or resume_receipt.run_id != self._run_id:
                raise ValueError("Resume recovery selection changed")
            read_args = dict(expected_fence=resume_receipt.selection.fence)
        run, attempt, owner = self._service.read_generation_recovery(self._principal, self._run_id, **read_args)
        if resume_receipt is not None:
            from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest

            if (
                run.version != resume_receipt.after_version
                or contract_digest(parse_contract(run.contract_json)) != resume_receipt.contract_digest
            ):
                raise ValueError("Resume recovery selection changed")
        fence, registration = attempt.fence, attempt.registration
        if registration is None or registration.fence != fence or owner is None:
            raise ValueError("Original registered owner required; reconciliation blocked")
        if resume_receipt is not None:
            binding = (fence, registration)
            if getattr(self, "_resume_binding", binding) != binding:
                raise ValueError("Resume recovery binding changed")
            if self._observed is not None and self._observed[0] != registration:
                raise ValueError("Resume recovery binding changed")
            self._resume_binding = binding
        if (owner.owner_id, owner.owner_epoch) != (fence.owner_id, fence.owner_epoch):
            return self._historical_replay(run, attempt, release_lease=release_lease, **read_args)
        self.lease.mark_recovery(fence)
        identity = self._ownership.load(registration)
        if self._group is None:
            self._group = OwnedProcessGroup(registration.pid, identity)
        self._group.stop(term_timeout=0.2, kill_timeout=2)
        evidence = attempt.cleanup or CleanupEvidence(
            registration=registration,
            evidence_ref="recovery-" + secrets.token_hex(16),
            observation="owned_process_group_stopped",
            remote_effects="unknown",
        )
        if evidence.registration != registration:
            raise ValueError("Cleanup registration mismatch")
        self._observed = (registration, evidence)
        store = self._service.bound_store
        settled = attempt.cleanup is not None and (
            run.state == "cancelled"
            or (attempt.receipt is not None and (run.state, run.phase) == ("running", "validation"))
        )
        if not owner.dirty or settled:
            # Exact settled replay does not rewrite receipt/cleanup under the
            # original fence. Replacement owners use the read-only branch above.
            if attempt.cleanup is None or attempt.cleanup != evidence:
                raise ValueError("Retired owner cleanup unresolved")
            if attempt.receipt is not None:
                self._service.prepare_generation_adoption(
                    self._principal, fence, attempt.receipt, artifacts=self._artifacts, protect=self._protect
                )
            run, current, observed_owner = self._service.read_generation_recovery(
                self._principal, self._run_id, **read_args
            )
            if (
                current.fence != fence
                or current.registration != registration
                or current.receipt != attempt.receipt
                or current.cleanup != evidence
                or observed_owner is None
                or (observed_owner.owner_id, observed_owner.owner_epoch) != (fence.owner_id, fence.owner_epoch)
            ):
                raise ValueError("Settled recovery readback mismatch")
            attempt, owner = current, observed_owner
            disposition = "cancelled" if run.state == "cancelled" else "validation"
            if disposition == "validation" and (
                attempt.receipt is None or (run.state, run.phase) != ("running", "validation")
            ):
                raise ValueError("Retired owner outcome unresolved")
            if release_lease:
                if owner.dirty:
                    self.lease.retire_and_release(store, registration, evidence)
                else:
                    self.lease.release_after_cleanup(registration, evidence)
            return CompletionResult(disposition, run, attempt)
        # Physical cleanup is independent of whether a result can be recovered.
        store.acknowledge_cleanup(fence, evidence)
        if store.get_attempt(fence).cleanup != evidence:
            raise ValueError("Recovery cleanup readback mismatch")
        if attempt.receipt is not None:
            self._service.prepare_generation_adoption(
                self._principal, fence, attempt.receipt, artifacts=self._artifacts, protect=self._protect
            )
        try:
            receipt = self._artifacts.load_receipt(
                fence, registration, parse_contract(attempt.contract_json), protect=self._protect
            )
        except ArtifactError:
            # Cancellation may settle after actual cleanup without a candidate.
            run, _, _ = self._service.read_generation_recovery(self._principal, self._run_id, **read_args)
            if run.state not in ("cancel_requested", "cancelled"):
                store.mark_reconciliation_required(fence, ReconciliationReason.RELEASED_WITHOUT_RECEIPT)
                raise RuntimeError("Generation artifact unresolved; reconciliation required") from None
            receipt = None
        if receipt is not None:
            self._service.adopt_generation(
                self._principal, fence, receipt, artifacts=self._artifacts, protect=self._protect
            )
        elif run.state not in ("cancel_requested", "cancelled"):
            store.mark_reconciliation_required(fence, ReconciliationReason.RELEASED_WITHOUT_RECEIPT)
            store.acknowledge_cleanup(fence, evidence)
            return CompletionResult("reconciliation_required", store.get_run(self._run_id), store.get_attempt(fence))
        store.acknowledge_cleanup(fence, evidence)
        run, attempt, owner = self._service.read_generation_recovery(self._principal, self._run_id, **read_args)
        if attempt.cleanup != evidence or (receipt is not None and attempt.receipt != receipt):
            raise ValueError("Recovery readback mismatch")
        disposition = "cancelled" if run.state == "cancelled" else "validation"
        if disposition == "validation" and (receipt is None or (run.state, run.phase) != ("running", "validation")):
            raise ValueError("Recovery outcome unresolved")
        if release_lease:
            self.lease.retire_and_release(store, registration, evidence)
        return CompletionResult(disposition, run, attempt)


class ForegroundAssessmentRecovery(ForegroundGenerationRecovery):
    """Reconcile recorded assessment cleanup under the original scope flock; never send."""

    def recover(self, *, previous_identity, release_lease=True, verify_only=False):
        from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import SceneIntent

        assert release_lease is True, "Assessment cancellation recovery must retire and release"
        self.lease.require_held(self._run_id, self._principal)
        self._service._authority.require_read(self._principal)
        store = self._service.bound_store
        records = store.result_records(self._run_id)
        run = records["run"]
        contract = parse_contract(run.contract_json)
        if (
            contract.schema_version != "4"
            or run.state not in ("cancel_requested", "cancelled")
            or not 1 <= len(records["intents"]) <= contract.budget.max_model_calls
            or any(row["scene"] is None for row in records["intents"])
        ):
            raise ValueError("Recorded retained-assessment cancellation required")
        intents = tuple(SceneIntent.model_validate_json(row["scene"]) for row in records["intents"])
        owner = store.get_owner()
        workers = []
        for intent in intents:
            registration, cleanup, fence = intent.worker_registration, intent.worker_cleanup, intent.worker_fence
            if (
                registration is None
                or cleanup is None
                or fence is None
                or registration.fence != fence
                or cleanup.registration != registration
                or fence.run_id != run.run_id
                or owner is None
                or (owner.owner_id, owner.owner_epoch) != (fence.owner_id, fence.owner_epoch)
            ):
                raise ValueError("Exact recorded assessment worker and owner required")
            identity = self._ownership.load(registration, previous_identity=previous_identity)
            group = OwnedProcessGroup(registration.pid, identity)
            if group.members():
                raise ValueError("Recorded cleanup has live physical obligations")
            # stop() rechecks liveness; with no members it sends no signal.
            group.stop(term_timeout=0, kill_timeout=0)
            workers.append(
                dict(registration=registration.model_dump(mode="json"), cleanup=cleanup.model_dump(mode="json"))
            )
            self._group, self._observed = group, (registration, cleanup)
        retired = store.get_retired_owner(owner.owner_id)
        if verify_only:
            if run.state != "cancelled" or owner.dirty or retired != owner:
                raise ValueError("Exact durable assessment retirement required")
            if release_lease:
                self.lease.release_never_prepared()
        else:
            self.lease.mark_recovery(intents[-1].worker_fence)
            if run.state == "cancel_requested":
                if not owner.dirty:
                    raise ValueError("Pending cancellation has no active original owner")
                for intent in intents:
                    store.acknowledge_scene_cleanup(intent.worker_fence, intent.worker_cleanup)
            if store.get_run(run.run_id).state != "cancelled":
                raise ValueError("Assessment cancellation remains unresolved")
            after = store.result_records(run.run_id)
            if after["intents"] != records["intents"] or after["admitted_at"] != records["admitted_at"]:
                raise ValueError("Recovery changed retained assessment attempts")
            if release_lease:
                self.lease.retire_and_release(store, intents[-1].worker_registration, intents[-1].worker_cleanup)
            retired = store.get_retired_owner(owner.owner_id)
            if retired is None or retired.dirty or store.get_owner() != retired:
                raise ValueError("Assessment retirement readback unresolved")
        result: dict = dict(
            run_id=run.run_id,
            operation_id=run.operation_id,
            state=store.get_run(run.run_id).state,
            owner=retired.model_dump(mode="json"),
            workers=workers,
            owner_retired=True,
            lease_released=self.lease._released,
        )
        self._protect(result)
        return result
