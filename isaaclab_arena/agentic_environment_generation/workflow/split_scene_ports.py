# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""V2 retained producers; owner/service composition supplies all effect authority.

No native launcher or permission is inferred here. capture_stage is a required
trusted owned-worker port returning a SceneEvidenceReceipt, not an environment.
The service must stop the child and release its GPU slot before verifying the
pending result. Assessment consumes only its exact retained capture; it never
calls capture_stage. These producers alone are not executable service ports.
"""

import math
import time
from dataclasses import dataclass
from decimal import Decimal

from .contracts import contract_digest
from .evidence import CandidateBinding
from .inference_transport import checked_workflow_accounting
from .scene_evidence_artifacts import SceneEvidenceReceipt
from .scene_loop import CandidateRecord, Observation, identity, profile_digest
from .scene_observation import retain_visual_answer, visual_request
from .scene_ports import ScenePorts


@dataclass(frozen=True)
class PendingSceneEvidence:
    """Exact immutable receipt handles, not verified output or lifecycle authority."""

    candidate: CandidateRecord
    observation: SceneEvidenceReceipt
    answer: SceneEvidenceReceipt | None = None


class SplitScenePorts(ScenePorts):
    """Reuse ScenePorts evaluators with an absolute window and split model timing."""

    def __init__(self, *, capture_start_step, capture_stage, numeric_stage=None, native_producer=None, **options):
        if type(capture_start_step) is not int or capture_start_step < 0:
            raise ValueError("exact nonnegative absolute capture start required")
        if options["profile"].codec_version != 2 or not callable(capture_stage):
            raise ValueError("v2 trusted capture stage required")
        self.capture_start_step, self.capture_stage = capture_start_step, capture_stage
        self.numeric_stage = numeric_stage
        self.native_producer = native_producer
        super().__init__(capture=None, **options)

    def admit(self, contract):
        criteria = super().admit(contract)
        if self.profile.assurance == "native-unverified":
            from .native_capture import NativeCaptureProducer

            if not isinstance(self.native_producer, NativeCaptureProducer):
                raise ValueError("real frozen native producer required")
            if self.native_producer.admit(contract) != criteria:
                raise ValueError("native producer criteria binding mismatch")
            settings = self.native_producer.settings
            if (
                self.capture_window() != (settings.window.start_step, settings.window.end_step)
                or self.capture_timeout_seconds != settings.max_runtime_seconds
                or self.native_producer.artifacts is not self.artifacts
            ):
                raise ValueError("native window/runtime/artifact binding mismatch")
        return criteria

    def capture_window(self):
        """Charge settling before this exact inclusive absolute evidence window."""
        return self.capture_start_step, self.capture_start_step + self.capture_steps

    def ceiling_for(self, action):
        if action == "assess":
            action = "observe"
        return super().ceiling_for(action)

    def require_bounded_capability(self, principal, contract, reservation):
        criteria = self.admit(contract)
        self.check_active()
        if reservation not in (self.profile.capture, self.profile.assess, self.profile.repair):
            raise ValueError("unconfigured reservation")
        if reservation == self.profile.capture:
            runtime = self.capture_timeout_seconds
            if (
                self.capture_window()[1] > reservation.steps
                or reservation.realizations < 1
                or reservation.observations < 1
            ):
                raise ValueError("configured capture ceiling exceeds reservation")
        elif reservation == self.profile.assess and not any(c.kind == "visual" for c in criteria):
            # No allowance and no model construction for a numeric-only assessment.
            if reservation.model_calls or reservation.model_tokens or reservation.cost_ceiling_usd:
                raise ValueError("numeric-only assessment must reserve no model budget")
            runtime = reservation.runtime_allowance_seconds
        else:
            ceiling = self.ceiling_for("repair" if reservation == self.profile.repair else "assess")
            allowance = ceiling.allowance(now=time.monotonic())
            bound = checked_workflow_accounting(ceiling.per_call_bound)
            if (
                not allowance.token_cost_bounded
                or ceiling.max_calls > reservation.model_calls
                or ceiling.max_tokens > reservation.model_tokens
                or Decimal(ceiling.max_cost_usd) > Decimal(str(reservation.cost_ceiling_usd))
                or bound["max_tokens"] > ceiling.max_tokens
                or Decimal(bound["max_cost_usd"]) > Decimal(ceiling.max_cost_usd)
            ):
                raise ValueError("configured model ceiling exceeds reservation or attested allowance")
            runtime = ceiling.timeout_seconds
        if (
            not math.isfinite(runtime)
            or runtime <= 0
            or runtime > min(reservation.runtime_allowance_seconds, contract.budget.per_operation_timeout_seconds)
        ):
            raise ValueError("configured runtime ceiling exceeds reservation")
        return True

    def execute(self, intent, candidate, original, contract, *, retained_observation=None):
        if intent.action == "repair":
            return super().execute(intent, candidate, original, contract)
        criteria = self.admit(contract)
        if (
            intent.codec_version != 2
            or intent.action not in ("capture", "assess")
            or intent.status != "released"
            or intent.released_at is None
            or intent.candidate_id != candidate.candidate_id
            or intent.intent_id in self._executed
            or candidate.original_id != original.candidate_id
            or intent.reservation != getattr(self.profile, intent.action)
        ):
            raise ValueError("exact fresh released scene intent required")
        self.require_bounded_capability(None, contract, intent.reservation)
        if intent.action == "assess":
            receipt = self.load_retained_capture(intent, retained_observation, contract, candidate)
        elif retained_observation is not None:
            raise ValueError("unexpected retained capture")
        self._executed.add(intent.intent_id)
        self.check_active()
        if intent.action == "capture":
            receipt = self.capture_stage(intent, candidate, original, contract)
            if not isinstance(receipt, SceneEvidenceReceipt) or receipt.cohort.realization_id != identity(
                intent.intent_id, candidate.candidate_id
            ):
                raise ValueError("exact capture receipt required")
            return PendingSceneEvidence(candidate, receipt)
        visual = next((c for c in criteria if c.kind == "visual"), None)
        answer = None
        if visual is None and self.numeric_stage is not None:
            output = self.numeric_stage(
                intent, candidate, original, contract, retained_observation=retained_observation
            )
            self.check_active()
            if not isinstance(output, Observation) or output.cohort != retained_observation.cohort:
                raise ValueError("exact numeric assessment output required")
            return output
        if visual is not None:
            request = visual_request(
                visual, receipt.candidate, receipt.cohort, self.artifacts, receipt, protect=self.protect
            )
            payload = self.artifacts.verified_payload(receipt, protect=self.protect)
            raw = self._visual(
                request=request,
                frames=payload["frames"],
                allowance=self.ceiling_for("assess").allowance(now=time.monotonic()),
            )
            self.check_active()
            answer = retain_visual_answer(
                visual, receipt.candidate, receipt.cohort, self.artifacts, receipt, raw, protect=self.protect
            )
        self.check_active()
        return PendingSceneEvidence(candidate, receipt, answer)

    def load_retained_capture(self, intent, output, contract, candidate):
        """Reject mismatched durable metadata before any assessment worker effects."""
        if (
            not isinstance(output, Observation)
            or identity(output.model_dump(mode="json")) != intent.observation_digest
            or len(output.verified_manifest_digests) != 1
            or any(e.modality == "visual" for e in output.evidence)
        ):
            raise ValueError("exact retained capture required")
        checked = self.verify_observation(output, contract, candidate)
        return self._retained[checked.cohort.realization_id][1]

    def _reopen(self, candidate, contract, cohort, digests):
        if not 1 <= len(digests) <= 2 or len(set(digests)) != len(digests):
            raise ValueError("exact retained producer manifests required")
        binding = CandidateBinding(
            candidate_digest=candidate.digest,
            contract_digest=contract_digest(contract),
            profile_digest=profile_digest(contract),
        )
        receipts = [
            self.artifacts.load_receipt(binding, cohort, kind=kind, manifest_digest=digest, protect=self.protect)
            for kind, digest in zip(("observation", "visual-answer"), digests)
        ]
        self.admit(contract)
        if self.profile.assurance == "native-unverified":
            self.native_producer.replay(receipts[0], contract=contract, candidate=candidate)
        return receipts[0], receipts[1] if len(receipts) == 2 else None

    def _evaluate(self, tag, contract, candidate, *, include_visual=None):
        _, receipt, answer = self._retained[tag]
        output = super()._evaluate(
            tag, contract, candidate, include_visual=(answer is not None if include_visual is None else include_visual)
        )
        # Include exact raw-answer identity even when its evaluator rejects it.
        digests = (receipt.manifest_digest,) + (() if answer is None else (answer.manifest_digest,))
        return output.model_copy(update={"verified_manifest_digests": digests})

    def verify_observation(self, output, contract, candidate):
        self.check_active()
        if isinstance(output, PendingSceneEvidence):
            if output.candidate != candidate:
                raise ValueError("capture candidate mismatch")
            cohort = output.observation.cohort
            digests = (output.observation.manifest_digest,) + (
                () if output.answer is None else (output.answer.manifest_digest,)
            )
        elif isinstance(output, Observation):
            cohort, digests = output.cohort, output.verified_manifest_digests
        else:
            raise ValueError("exact retained evidence required")
        receipt, answer = self._reopen(candidate, contract, cohort, digests)
        tag = cohort.realization_id
        previous = self._retained.get(tag)
        self._retained[tag] = (candidate, receipt, answer)
        try:
            verified = self._evaluate(tag, contract, candidate)
            if isinstance(output, Observation) and output != verified:
                raise ValueError("observation differs from retained producer evaluation")
        except BaseException:
            if previous is None:
                self._retained.pop(tag, None)
            else:
                self._retained[tag] = previous
            raise
        self._latest[candidate.candidate_id] = verified
        return verified

    def restore_observations(self, records, contract):
        """Reopen selected immutable captures/answers in exact repair lineage order."""
        pending = [
            (CandidateRecord.model_validate_json(row["candidate"]), Observation.model_validate_json(row["payload"]))
            for row in self._selected_restore_rows(records)
        ]
        while pending:
            progress = False
            for candidate, observation in tuple(pending):
                if candidate.parent_id and candidate.parent_id not in self._latest:
                    continue
                self.verify_observation(observation, contract, candidate)
                pending.remove((candidate, observation))
                progress = True
            if not progress:
                raise ValueError("Missing retained parent observation")


class OwnedSceneStageAdapter:
    """Route exact owned children without holding the GPU during model assessment.

    All workers implement prepare/stop_owned/cleanup_verified. model_worker also
    implements the existing send/receive seam. native_worker.send_capture is a
    bounded one-shot dispatch; receive_capture returns the immutable receipt from
    NativeCaptureProducer in its isolated child (NativeCaptureResult.receipt).
    numeric_worker.send_evaluate/receive_evaluate perform numeric evaluation;
    it must be a real bounded evaluator, not a model process parked without work.
    No default native/numeric transport or permission is supplied. authorize_native
    is a trusted check-only capability scoped to the caller/run, rechecked before
    prepare and capture; contract flags and ForegroundAuthorization are insufficient.
    send_capture/send_evaluate receive deadline (absolute Unix seconds) and protect;
    send_evaluate additionally receives retained_observation. Each send must latch
    one release and enforce the minimum of this deadline and its prepare timeout.
    Native code converts the remaining wall-clock bound to a monotonic deadline
    without extending it. Receive runs outside the owner's dispatch interlock so
    local stop remains usable. prepare must leave the child inert until send.
    """

    def __init__(self, *, native_worker, model_worker, numeric_worker, gpu_lease, authorize_native):
        for worker, extra in (
            (native_worker, ("send_capture", "receive_capture")),
            (model_worker, ("send", "receive")),
            (numeric_worker, ("send_evaluate", "receive_evaluate")),
        ):
            if any(
                not callable(getattr(worker, name, None))
                for name in ("prepare", "stop_owned", "cleanup_verified", *extra)
            ):
                raise ValueError("explicit trusted owned stage worker required")
        if not callable(authorize_native):
            raise ValueError("explicit native authorization required")
        self.native_worker, self.model_worker, self.numeric_worker = (native_worker, model_worker, numeric_worker)
        self.gpu_lease, self.authorize_native = gpu_lease, authorize_native
        self._workers = {}

    def require_native_authorization(self, intent, contract):
        if self.authorize_native(intent, contract) is not True:
            raise ValueError("explicit native authorization required")

    def require_gpu_released(self):
        if self.gpu_lease.held:
            raise ValueError("capture GPU cleanup and release required before assessment")

    def prepare_stage(self, intent, contract, *, timeout_s):
        from .coordinator import PrepareFailed

        if any(p.registration.fence == intent.worker_fence for p, _, _ in self._workers.values()):
            raise ValueError("stage already prepared")
        if intent.action == "capture":
            self.require_native_authorization(intent, contract)
            self.gpu_lease.acquire(intent.worker_fence)
            worker = self.native_worker
        else:
            self.require_gpu_released()
            if intent.action not in ("assess", "repair"):
                raise ValueError("unsupported owned stage")
            worker = (
                self.model_worker
                if (intent.action == "repair" or any(c.kind == "visual" for c in contract.criteria))
                else self.numeric_worker
            )
        try:
            prepared = worker.prepare(intent.worker_fence, contract, timeout_s=timeout_s)
        except PrepareFailed as exc:
            self._remember(exc.prepared, worker, intent.action)
            raise
        # Other ambiguous failures deliberately retain the physical GPU lease.
        self._remember(prepared, worker, intent.action)
        return prepared

    def _remember(self, prepared, worker, action):
        key = prepared.registration.registration_id
        if key in self._workers:
            raise ValueError("duplicate owned registration")
        self._workers[key] = prepared, worker, action

    def _worker(self, prepared, *, role=None):
        retained, worker, action = self._workers[prepared.registration.registration_id]
        if retained is not prepared or (role is not None and worker is not role):
            raise ValueError("exact owned stage worker required, not a model fallback")
        return worker

    def send_capture(self, prepared, intent, candidate, original, contract, **options):
        worker = self._worker(prepared, role=self.native_worker)
        self.require_native_authorization(intent, contract)
        self.gpu_lease.require_held(prepared.registration.fence)
        return worker.send_capture(prepared, intent, candidate, original, contract, **options)

    def receive_capture(self, prepared, *, protect):
        return self._worker(prepared, role=self.native_worker).receive_capture(prepared, protect=protect)

    def send_evaluate(self, prepared, intent, candidate, original, contract, **options):
        worker = self._worker(prepared, role=self.numeric_worker)
        self.require_gpu_released()
        return worker.send_evaluate(prepared, intent, candidate, original, contract, **options)

    def receive_evaluate(self, prepared, *, protect):
        return self._worker(prepared, role=self.numeric_worker).receive_evaluate(prepared, protect=protect)

    def send(self, prepared, *args, **kwargs):
        self.require_gpu_released()
        return self._worker(prepared, role=self.model_worker).send(prepared, *args, **kwargs)

    def receive(self, prepared, *args, **kwargs):
        self.require_gpu_released()
        return self._worker(prepared, role=self.model_worker).receive(prepared, *args, **kwargs)

    def stop_owned(self, prepared, *, timeout_s):
        return self._worker(prepared).stop_owned(prepared, timeout_s=timeout_s)

    def cleanup_verified(self, registration, cleanup):
        prepared, worker, action = self._workers[registration.registration_id]
        if prepared.registration != registration:
            return False
        return worker.cleanup_verified(registration, cleanup)

    def release_native_resource(self, registration, cleanup):
        prepared, worker, action = self._workers[registration.registration_id]
        if prepared.registration != registration or worker is not self.native_worker or action != "capture":
            raise ValueError("exact native cleanup required")
        self.gpu_lease.release(registration, cleanup, verify_cleanup=self.cleanup_verified)
        return True
