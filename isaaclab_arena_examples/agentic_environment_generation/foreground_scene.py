# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Scene WorkerPort: prepare -> durable register/release -> send -> receive.

No store or lease retirement is performed here. receive returns retained output,
its exact immutable receipt and verified physical cleanup for later adoption.
Cancellation calls inherited stop_owned; remote effects remain unknown. A lost
pipe can be reconciled by reading the deterministic output artifact, never resend.
"""

from dataclasses import dataclass

from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import _protected, canonical

from .foreground_generation import ForegroundGenerationReceiver, ForegroundGenerationWorker
from .web_api.provider_security import reject_secret
from .web_api.scene_worker import open_area, read_retained, scene_allowance


@dataclass(frozen=True)
class SceneModelResult:
    output: dict
    receipt: dict
    cleanup: object
    attempted_calls: int


class ForegroundSceneWorker(ForegroundGenerationWorker):
    """Fixed scene child, same exact-registration and one-shot transport ownership."""

    @staticmethod
    def _production_spawn():
        args, kwargs = ForegroundGenerationWorker._production_spawn()
        args[2] = "isaaclab_arena_examples.agentic_environment_generation.web_api.scene_worker"
        return args, kwargs

    def _allowance(self, packet, owned):
        allowance = scene_allowance(packet, contract=owned.contract)
        # Memory only, frozen at release; never part of registration/artifact/proof.
        owned.scene_private_key = packet["config"]["api_key"]
        return allowance

    def receive(self, prepared, *, protect):
        """Reverify immutable output under frozen-key AND reject-only current policy."""
        owned = self._get(prepared)

        def screen(value):
            reject_secret(value, owned.scene_private_key)
            _protected(value, protect)

        try:
            receipt = ForegroundGenerationReceiver._read(self, owned)
            payload = owned.inputs["scene_payload"]
            expected = dict(
                payload["request"]["binding"],
                codec="scene-model-result-v1",
                request_manifest_digest=payload["request"]["manifest_digest"],
            )
            if receipt["family"] != "scene-model-output" or canonical(receipt["binding"]) != canonical(expected):
                raise ValueError("Scene output binding mismatch")
            _protected(receipt, screen)
            with open_area(payload) as area:
                value = read_retained(area, receipt, protect=screen)
            if set(value) != {"binding", "output", "attempted_calls"} or canonical(value["binding"]) != canonical(
                expected
            ):
                raise ValueError("Scene result shape mismatch")
            output = value["output"]
            expected_kind = "raw_visual_response" if owned.inputs["scene_action"] == "assess" else "proposal"
            if output.get("kind") != expected_kind or output.get("publication") != "not_published":
                raise ValueError("Scene result kind mismatch")
            cleanup = self.stop_owned(prepared, timeout_s=3)
            return SceneModelResult(output, receipt, cleanup, value["attempted_calls"])
        finally:
            self.stop_owned(prepared, timeout_s=3)
