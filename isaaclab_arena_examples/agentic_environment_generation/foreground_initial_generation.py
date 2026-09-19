# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Initial proposal composition on the existing generation lifecycle.

Pass InitialGenerationWorker to GenerationCoordinator, dispatch normally, then
use InitialGenerationReceiver.receive(principal, handle.prepared,
release_lease=False) to retain the owner for subsequent workflow stages. The
outer composition must bind all required roles and check full readiness first.
This module never retrieves, publishes, constructs Documents, or accepts a scene.
"""

import json
from dataclasses import asdict

from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import (
    RetainedPriorArtifacts,
    RetainedPriorReceipt,
)
from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import _protected

from .foreground_generation import ForegroundGenerationReceiver
from .foreground_scene import ForegroundSceneWorker
from .web_api.provider_security import reject_secret
from .web_api.scene_worker import LEGACY_INPUTS, open_area, read_retained, retain_request


class InitialGenerationWorker(ForegroundSceneWorker):
    """Enrich only the coordinator's final post-release send; retain its original budget."""

    def __init__(self, *, area, root, prior, protect, require_prior=True, **kwargs):
        if type(prior) is not RetainedPriorReceipt or type(require_prior) is not bool or not callable(protect):
            raise ValueError("Exact retained prior and protection required")
        super().__init__(**kwargs)
        self._initial_area, self._initial_root = area, root
        self._initial_prior, self._initial_protect = prior, protect
        self._require_prior = require_prior

    def send(self, prepared, envelope, *, timeout_s):
        owned = self._get(prepared)
        with owned.lock:
            if getattr(owned, "initial_send_attempted", False):
                raise RuntimeError("Private send already attempted")
            owned.initial_send_attempted = True
            if type(envelope) is not bytes or len(envelope) > 512 * 1024 or not envelope.endswith(b"\n"):
                raise ValueError("Invalid initial generation envelope")
            packet = json.loads(envelope)
            if (
                set(packet) != {"inputs", "config", "graph_config", "workflow_execution"}
                or set(packet["inputs"]) != LEGACY_INPUTS
                or packet["inputs"]["operation"] != "new"
            ):
                raise ValueError("Original generation envelope required")
            key = packet["config"]["api_key"]

            def protect(value):
                reject_secret(value, key)
                _protected(value, self._initial_protect)

            # No workflow_execution field changes: preserve fence, reservation,
            # admission/release timestamps and the original absolute deadline.
            packet["inputs"]["scene_action"] = "generate"
            packet["inputs"]["scene_payload"] = retain_request(
                self._initial_area,
                root=self._initial_root,
                registration=prepared.registration,
                contract=owned.contract,
                action="generate",
                data={
                    "prior": asdict(self._initial_prior),
                    "require_prior": self._require_prior or packet["inputs"]["retrieval_policy"] == "require_service",
                },
                protect=protect,
            )
            super().send(prepared, json.dumps(packet, allow_nan=False).encode() + b"\n", timeout_s=timeout_s)


class InitialGenerationReceiver(ForegroundGenerationReceiver):
    """Translate verified model bytes, then reuse generation writer/completion/cleanup.

    The scene model receipt is provenance only, never a GenerationReceipt. The
    inherited receiver retains the actual generation receipt across adoption
    failures; retries do not invoke this translation or the SDK again.
    """

    def _read(self, owned):
        import yaml

        from isaaclab_arena.agentic_environment_generation.workflow.coordinator import PreparedWorker

        prepared = PreparedWorker(owned.registration, owned)
        model = self._worker.receive(prepared, protect=self._protect)

        def protect(value):
            reject_secret(value, owned.scene_private_key)
            _protected(value, self._protect)

        payload = owned.inputs["scene_payload"]
        with open_area(payload) as area:
            request = read_retained(area, payload["request"], protect=protect)
            binding = payload["request"]["binding"]
            snapshot = RetainedPriorArtifacts(area).verified_snapshot(
                RetainedPriorReceipt(**request["prior"]),
                prompt=owned.inputs["prompt"],
                contract_digest=binding["contract_digest"],
                run_id=binding["run_id"],
                protect=protect,
            )
        output = model.output
        _protected(output, protect)
        raw = {
            "yaml_text": yaml.safe_dump(output["spec"], sort_keys=False),
            "validation": {
                "proposal_only": True,
                "model_warnings": output["warnings"],
                "model_traces": output["traces"],
                "model_receipt": model.receipt,
                "attempted_calls": model.attempted_calls,
            },
            # Agent diagnostic traces are retained verbatim above, not relabelled
            # as the closed generation stage vocabulary.
            "traces": [],
            "publication": "not_published",
            "warnings": [
                "Not published to Neo4j. No simulation or policy evaluation was run.",
                "Agent did not converge on all physical/semantic checks; review the draft before use.",
            ],
            "operation": "new",
            "prior_snapshot": snapshot,
            "catalogue_sha256": owned.inputs["execution_catalogue_sha256"],
        }
        _protected(raw, protect)
        return raw
