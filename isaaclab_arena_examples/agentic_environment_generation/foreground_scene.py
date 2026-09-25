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

import json
import os
import re
import time
from dataclasses import dataclass

from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import _protected, canonical

from .foreground_generation import ForegroundGenerationReceiver, ForegroundGenerationWorker
from .web_api.provider_security import reject_secret
from .web_api.scene_worker import open_area, read_retained, recover_assessment_output, scene_allowance


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
        if "request_bounds" in packet["config"]:
            if not callable(getattr(owned, "model_send_guard", None)):
                raise ValueError("Owned model send authority required")
            owned.model_send_config = packet["config"]
            owned.model_send_allowance = allowance
            owned.model_send_handler = lambda message: self._answer_model_send(owned, message)
        return allowance

    def bind_model_send(self, prepared, guard, *, expected_request_sha256=None, record_send=None, lookup_send=None):
        """Bind only a trusted parent callback, never a private-packet callable selector."""
        owned = self._get(prepared)
        with owned.lock:
            if not callable(guard) or owned.attempted or hasattr(owned, "model_send_guard"):
                raise ValueError("Fresh owned model send binding required")
            owned.model_send_guard = guard
            owned.model_send_count = 0
            owned.expected_request_sha256 = expected_request_sha256
            owned.record_model_send = record_send
            owned.lookup_model_send = lookup_send

    def _answer_model_send(self, owned, message):
        """Consume one reserved send before rechecking authority and replying once."""
        with owned.lock:
            if (
                not any(owned is item for item in self._owned)
                or type(message) is not dict
                or set(message) != {"version", "ordinal", "request_sha256"}
                or type(message["version"]) is not int
                or message["version"] != 1
                or type(message["ordinal"]) is not int
                or message["ordinal"] != owned.model_send_count + 1
                or message["ordinal"] > owned.model_send_allowance.max_calls
                or type(message["request_sha256"]) is not str
                or re.fullmatch("[0-9a-f]{64}", message["request_sha256"]) is None
                or owned.cleanup is not None
                or time.monotonic() >= owned.deadline
            ):
                raise ValueError("Invalid or consumed owned send request")
            owned.model_send_count += 1
        # Preserve coordinator/authority -> owned-lock order. No lock spans HTTP.
        with owned.model_send_guard(owned.model_send_config), owned.lock:
            if owned.cleanup is not None or time.monotonic() >= owned.deadline:
                raise ValueError("Owned send authority expired")
            if owned.expected_request_sha256 is not None:
                if message["request_sha256"] != owned.expected_request_sha256 or not callable(owned.record_model_send):
                    raise ValueError("Frozen assessment request differs")
                owned.record_model_send(message)
            raw = (json.dumps({"model_send_ack": message}, separators=(",", ":")) + "\n").encode()
            if os.write(owned.process.stdin.fileno(), raw) != len(raw):
                raise ValueError("Owned send reply incomplete; never retry")
        return True

    def receive(self, prepared, *, protect):
        """Reverify immutable output under frozen-key AND reject-only current policy."""
        owned = self._get(prepared)

        def screen(value):
            reject_secret(value, owned.scene_private_key)
            _protected(value, protect)

        try:
            payload = owned.inputs["scene_payload"]
            try:
                receipt = ForegroundGenerationReceiver._read(self, owned)
            except Exception as exc:
                if owned.contract.schema_version != "4" or not callable(owned.lookup_model_send):
                    raise
                self.stop_owned(prepared, timeout_s=3)
                with open_area(payload) as area:
                    receipt = recover_assessment_output(
                        area,
                        payload,
                        send_record=owned.lookup_model_send(),
                        failure_kind=type(exc).__name__,
                        protect=screen,
                    )
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
