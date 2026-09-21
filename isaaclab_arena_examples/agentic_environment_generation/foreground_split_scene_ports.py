# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Opt-in V2 foreground composition; no implicit native permission."""

import time

from isaaclab_arena.agentic_environment_generation.workflow.split_scene_ports import (
    OwnedSceneStageAdapter,
    SplitScenePorts,
)

from .foreground_scene_ports import ForegroundScenePorts


class ForegroundSplitScenePorts(ForegroundScenePorts, SplitScenePorts):
    """Explicit V2 composition over the existing owned model and scope-lease seams.

    Supply an OwnedSceneStageAdapter with real inert-until-release native/numeric
    worker transports and a separately scoped native authorization callback. This
    is not installed-profile admission or a calibrated native-support claim. The
    existing authority still owns model credentials and role-bound releases.
    """

    def __init__(self, *, worker, **options):
        if not isinstance(worker, OwnedSceneStageAdapter):
            raise ValueError("trusted split stage adapter required")
        self._output_intents = {}
        super().__init__(worker=worker, capture_stage=self._capture_child, numeric_stage=self._numeric_child, **options)

    def _authorization(self, principal, contract, action):
        if principal != self.principal or action not in ("capture", "assess", "repair"):
            raise ValueError("Exact scene principal and action required")
        if action == "capture":
            self.worker.require_native_authorization(self.store.scene_snapshot(self.run_id).intent, contract)
        return self.authority.require_scene_execute(principal, contract, run_id=self.run_id)

    def _prepare_child(self, intent, candidate, original, contract, *, retained_observation=None):
        self.admit(contract)
        if intent.action == "assess":
            self.worker.require_gpu_released()
            self.load_retained_capture(intent, retained_observation, contract, candidate)
        elif retained_observation is not None:
            raise ValueError("unexpected retained capture")
        return self.worker.prepare_stage(
            intent,
            contract,
            timeout_s=min(intent.reservation.runtime_allowance_seconds, contract.budget.per_operation_timeout_seconds),
        )

    def _checked_stage_release(self, intent, contract):
        self._check_active()
        prepared = self._prepared_workers[intent.intent_id]
        auth = self.authority.require_scene_execute(self.principal, contract, run_id=self.run_id)
        checked = self.store.check_scene_release(
            self.run_id,
            intent.intent_id,
            auth,
            readiness=self.ready(contract),
            fence=prepared.registration.fence,
            registration_id=prepared.registration.registration_id,
        )
        if checked != intent or self.store.get_scene_intent(self.run_id, intent.intent_id) != intent:
            raise ValueError("Exact committed scene release required")
        self.require_bounded_capability(self.principal, contract, intent.reservation)
        return prepared

    def _capture_child(self, intent, candidate, original, contract):
        with self._interlock, self.authority.release_guard(self.principal, contract, run_id=self.run_id):
            prepared = self._checked_stage_release(intent, contract)
            self.worker.send_capture(
                prepared,
                intent,
                candidate,
                original,
                contract,
                protect=self.protect,
                deadline=self._stage_deadline(intent, contract),
            )
        return self.worker.receive_capture(prepared, protect=self.protect)

    def _numeric_child(self, intent, candidate, original, contract, *, retained_observation):
        with self._interlock, self.authority.release_guard(self.principal, contract, run_id=self.run_id):
            prepared = self._checked_stage_release(intent, contract)
            self.worker.send_evaluate(
                prepared,
                intent,
                candidate,
                original,
                contract,
                retained_observation=retained_observation,
                protect=self.protect,
                deadline=self._stage_deadline(intent, contract),
            )
        return self.worker.receive_evaluate(prepared, protect=self.protect)

    def _stage_deadline(self, intent, contract):
        """Pass an absolute wall-clock deadline; the worker enforces it without renewal."""
        admitted = self.store.get_generation_attempt(self.run_id).admitted_at
        limit = (
            self.capture_timeout_seconds if intent.action == "capture" else intent.reservation.runtime_allowance_seconds
        )
        deadline = min(
            admitted + contract.budget.total_deadline_seconds,
            intent.released_at + intent.reservation.runtime_allowance_seconds,
            time.time() + limit,
        )
        if deadline <= time.time():
            raise ValueError("scene stage deadline expired")
        return deadline

    def execute(self, intent, candidate, original, contract, **stage_args):
        output = super().execute(intent, candidate, original, contract, **stage_args)
        if intent.action in ("capture", "assess"):
            self._output_intents[id(output)] = (output, intent)
        return output

    def verify_observation(self, output, contract, candidate):
        pending = self._output_intents.get(id(output))
        if pending is not None:
            _, intent = pending
            cleanup = self._cleanups.get(intent.intent_id)
            retained = self.store.get_scene_intent(self.run_id, intent.intent_id)
            if (
                cleanup is None
                or retained.worker_cleanup != cleanup
                or self.worker.cleanup_verified(intent.worker_registration, cleanup) is not True
            ):
                raise ValueError("exact acknowledged child cleanup required before evidence verification")
            self.worker.require_gpu_released()
        return super().verify_observation(output, contract, candidate)

    def release_native_resource(self, intent, cleanup):
        """Release only the GPU, after exact durable cleanup; keep scope ownership."""
        prepared = self._prepared_workers[intent.intent_id]
        retained = self.store.get_scene_intent(self.run_id, intent.intent_id)
        if (
            intent.action != "capture"
            or retained.worker_registration != prepared.registration
            or retained.worker_cleanup != cleanup
            or self._cleanups.get(intent.intent_id) != cleanup
        ):
            raise ValueError("exact acknowledged native cleanup required")
        return self.worker.release_native_resource(prepared.registration, cleanup)
