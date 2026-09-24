# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Fixed scene MODEL TOOL child, not a workflow runner or acceptance authority.

Wire v1 retains the four generation envelope keys. inputs.operation='new' means
original workflow, NOT scene action. The extra scene_action is generate/refine/
assess; scene_payload identifies an immutable request in an existing ArtifactArea.
No module/callback names are accepted. The parent must register, commit release,
resolve authority and send once. Receipts prove retained bytes, not authorization.
"""

import argparse
import contextlib
import ctypes
import hashlib
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import _protected, canonical

from .generation_worker import workflow_allowance
from .provider_security import reject_secret

LEGACY_INPUTS = {"operation", "prompt", "retrieval_policy", "execution_catalogue_sha256"}
ACTIONS = {"generate", "refine", "assess"}


class ModelSendAuthorization:
    """Recheck through the owned pipe at the SDK boundary; no DB login reaches the child.

    Replies release one physical send under the existing precharged reservation.
    An absent, late or ambiguous acknowledgement is never retried. Process alarms
    and parent-death ownership bound the pipe wait, not a background broker.
    """

    def __init__(self, channel, source, allowance):
        self.channel, self.source, self.allowance = channel, source, allowance
        self.approved_calls = 0
        self._requested = 0

    def __call__(self, request):
        if self._requested != self.approved_calls or self._requested >= self.allowance.max_calls:
            raise ValueError("Model send authorization already consumed or uncertain")
        if time.monotonic() >= self.allowance.deadline:
            raise ValueError("Model send authorization expired")
        self._requested += 1
        message = dict(version=1, ordinal=self._requested, request_sha256=hashlib.sha256(request.content).hexdigest())
        self.channel.write(json.dumps({"model_send": message}, separators=(",", ":")) + "\n")
        self.channel.flush()
        expected = (json.dumps({"model_send_ack": message}, separators=(",", ":")) + "\n").encode()
        reply = self.source.readline(1025)
        if reply != expected or time.monotonic() >= self.allowance.deadline:
            raise ValueError("Exact current model send authorization required")
        self.approved_calls += 1


def _retain(area, family, binding, value, protect):
    raw = _protected(value, protect)
    version = hashlib.sha256(canonical(binding)).hexdigest()
    files = {"value.json": raw}
    manifest = area.expected_manifest(version, files, binding)
    _protected(manifest, protect)
    with area.writer_lock():
        if not area.has_final(family, version):
            area.stage(version, files, binding)
        area.promote(version, family, version, manifest)
    return {"family": family, "version": version, "manifest_digest": manifest["digest"], "binding": binding}


def read_retained(area, reference, *, protect):
    if type(reference) is not dict or set(reference) != {"family", "version", "manifest_digest", "binding"}:
        raise ValueError("Exact scene artifact reference required")
    if reference["family"] not in {"scene-model-input", "scene-model-output"}:
        raise ValueError("Scene artifact family required")
    if reference["version"] != hashlib.sha256(canonical(reference["binding"])).hexdigest():
        raise ValueError("Scene artifact identity mismatch")
    manifest = area.read_final_manifest(reference["family"], reference["version"], binding=reference["binding"])
    if manifest["digest"] != reference["manifest_digest"]:
        raise ValueError("Scene manifest mismatch")
    with area.writer_lock():
        files = area.verify(f"final/{reference['family']}/{reference['version']}", manifest)
        if set(files) != {"value.json"}:
            raise ValueError("Scene artifact files mismatch")
        value = json.loads(files["value.json"])
        if _protected(value, protect) != files["value.json"]:
            raise ValueError("Noncanonical scene artifact")
        area.promote(reference["version"], reference["family"], reference["version"], manifest)
    return value


def retain_request(area, *, root, registration, contract, action, data, protect):
    """Retain public inputs after prepare; no model construction or private key write.

    refine: base_spec, feedback. generate: prior receipt (relative_directory,
    manifest_json), require_prior. assess: candidate, cohort, criterion,
    observation_manifest_digest. All are frozen by the request manifest digest.
    The composition must source feedback/candidate from authoritative readback.
    """
    if action not in ACTIONS:
        raise ValueError("Unsupported scene action")
    binding = {
        "codec": "scene-model-request-v1",
        "registration": registration.model_dump(mode="json"),
        "fence": registration.fence.model_dump(mode="json"),
        "run_id": registration.fence.run_id,
        "contract_digest": contract_digest(contract),
        "scene_action": action,
    }
    ref = _retain(area, "scene-model-input", binding, data, protect)
    result = {
        "root": str(Path(root).absolute()),
        "store_id": area.store_id,
        "registry_id": area.registry_id,
        "request": ref,
    }
    _protected(result, protect)
    return result


def scene_allowance(packet, *, contract=None):
    inputs = packet["inputs"]
    if set(packet) != {"inputs", "config", "graph_config", "workflow_execution"} or set(inputs) != LEGACY_INPUTS | {
        "scene_action",
        "scene_payload",
    }:
        raise ValueError("Invalid scene envelope")
    if inputs["scene_action"] not in ACTIONS:
        raise ValueError("Unsupported scene action")
    payload = inputs["scene_payload"]
    if type(payload) is not dict or set(payload) != {"root", "store_id", "registry_id", "request"}:
        raise ValueError("Invalid scene payload")
    binding = payload["request"]["binding"]
    execution = packet["workflow_execution"]
    expected = {
        "codec": "scene-model-request-v1",
        "registration": execution["registration"],
        "fence": execution["fence"],
        "run_id": execution["fence"]["run_id"],
        "contract_digest": contract_digest(contract) if contract is not None else binding["contract_digest"],
        "scene_action": inputs["scene_action"],
    }
    if canonical(binding) != canonical(expected):
        raise ValueError("Scene request binding mismatch")
    projected = dict(packet, inputs={k: inputs[k] for k in LEGACY_INPUTS})
    allowance = workflow_allowance(projected)
    if not allowance.token_cost_bounded:
        raise ValueError("Attested scene allowance required")
    return allowance


def open_area(payload):
    return ArtifactArea.open(Path(payload["root"]), store_id=payload["store_id"], registry_id=payload["registry_id"])


def prepare_catalogues(expected_sha256):
    """Prepare the real execution catalogues and reject disagreement before model work."""
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        build_asset_catalogue,
        build_relation_catalogue,
        build_task_catalogue,
    )

    from .catalogues import execution_catalogue_sha256

    assets, relations, tasks = build_asset_catalogue(), build_relation_catalogue(), build_task_catalogue()
    if execution_catalogue_sha256(assets=assets, relations=relations, tasks=tasks) != expected_sha256:
        raise ValueError("Catalogue mismatch")
    return assets, relations, tasks


def execute(packet, allowance, protect, *, send_guard=None):
    from isaaclab_arena.agentic_environment_generation.workflow.scene_engines import BoundedSceneModels

    inputs, config = packet["inputs"], packet["config"]
    action, payload = inputs["scene_action"], inputs["scene_payload"]
    role = "assessment" if action == "assess" else "generation"
    with open_area(payload) as area:
        data = read_retained(area, payload["request"], protect=protect)
        tools = BoundedSceneModels(
            config=config,
            approved_roles={role: {"model": config["model"], "endpoint": config["base_url"]}},
            allowance=allowance,
            send_guard=send_guard,
        )
        if action == "assess":
            from isaaclab_arena.agentic_environment_generation.workflow.contracts import Criterion
            from isaaclab_arena.agentic_environment_generation.workflow.evidence import CandidateBinding, EvidenceCohort
            from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import (
                SceneEvidenceArtifacts,
            )

            if set(data) != {"criterion", "candidate", "cohort", "observation_manifest_digest"}:
                raise ValueError("Invalid assessment request")
            candidate, cohort = CandidateBinding.model_validate(data["candidate"]), EvidenceCohort.model_validate(
                data["cohort"]
            )
            if candidate.contract_digest != payload["request"]["binding"]["contract_digest"]:
                raise ValueError("Candidate contract mismatch")
            artifacts = SceneEvidenceArtifacts(area)
            observation = artifacts.load_receipt(
                candidate,
                cohort,
                kind="observation",
                manifest_digest=data["observation_manifest_digest"],
                protect=protect,
            )
            raw = tools.assess(
                criterion=Criterion.model_validate(data["criterion"]),
                candidate=candidate,
                cohort=cohort,
                artifacts=artifacts,
                observation=observation,
                protect=protect,
            )
            if type(raw) is not str or not 1 <= len(raw.encode()) <= 65536:
                raise ValueError("Visual response bound")
            output = {"kind": "raw_visual_response", "raw_response": raw, "publication": "not_published"}
        else:
            assets, relations, tasks = prepare_catalogues(inputs["execution_catalogue_sha256"])
            kwargs = dict(asset_catalog=assets, relation_catalog=relations, task_catalog=tasks, protect=protect)
            if action == "refine":
                from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

                if set(data) != {"base_spec", "feedback"}:
                    raise ValueError("Invalid refinement request")
                proposal = tools.refine(
                    base_spec=ArenaEnvGraphSpec.model_validate(data["base_spec"]), feedback=data["feedback"], **kwargs
                )
            else:
                from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import (
                    RetainedPriorArtifacts,
                    RetainedPriorReceipt,
                )

                if set(data) != {"prior", "require_prior"}:
                    raise ValueError("Invalid generation request")
                binding = payload["request"]["binding"]
                proposal = tools.generate(
                    prompt=inputs["prompt"],
                    contract_digest=binding["contract_digest"],
                    run_id=binding["run_id"],
                    priors=RetainedPriorArtifacts(area),
                    prior=RetainedPriorReceipt(**data["prior"]),
                    require_prior=data["require_prior"],
                    **kwargs,
                )
            output = {
                "kind": "proposal",
                "spec": proposal.spec.model_dump(mode="json"),
                "warnings": list(proposal.warnings),
                "traces": list(proposal.traces),
                "publication": proposal.publication,
            }
        binding = dict(
            payload["request"]["binding"],
            codec="scene-model-result-v1",
            request_manifest_digest=payload["request"]["manifest_digest"],
        )
        value = {"binding": binding, "output": output, "attempted_calls": allowance.attempted_calls}
        return _retain(area, "scene-model-output", binding, value, protect)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != args.parent_pid:
        return 1
    line = sys.stdin.buffer.readline(512 * 1024 + 1)
    if len(line) > 512 * 1024 or not line.endswith(b"\n"):
        return 1
    channel = sys.stdout
    logging.disable(sys.maxsize)
    try:
        packet = json.loads(line)
        key = packet["config"]["api_key"]

        def protect(value):
            reject_secret(value, key)

        allowance = scene_allowance(packet)
        from .process_identity import process_identity

        identity = process_identity(os.getpid())
        registration = packet["workflow_execution"]["registration"]
        if identity is None or any(
            registration[k] != v
            for k, v in {
                "pid": os.getpid(),
                "pgid": identity["pgid"],
                "sid": identity["sid"],
                "boot": identity["boot_id"],
                "start_ticks": int(identity["start_ticks"]),
            }.items()
        ):
            raise ValueError("Scene child registration mismatch")
        remaining = allowance.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Expired scene release")
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.setitimer(signal.ITIMER_REAL, remaining)
        send_guard = (
            ModelSendAuthorization(channel, sys.stdin.buffer, allowance)
            if "request_bounds" in packet["config"] else None
        )
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            receipt = execute(packet, allowance, protect, send_guard=send_guard)
        message = {"result": receipt}
        _protected(message, protect)
        channel.write(json.dumps(message, allow_nan=False) + "\n")
        channel.flush()
        return 0
    except Exception:
        # No exception text or unscreened diagnostic crosses the private output.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
