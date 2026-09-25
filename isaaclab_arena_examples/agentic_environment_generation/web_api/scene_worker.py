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
    if reference["family"] not in {"scene-model-input", "scene-model-output", "scene-model-phase"}:
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


def safe_failure(phase, error):
    """Describe a causal boundary without exception text, packets, locals or arbitrary class names."""
    phases = {
        "parent_authorization",
        "parent_prepare",
        "parent_execute",
        "parent_packet_validation",
        "parent_packet_write",
        "send_authorization",
        "parent_receive",
        "parent_validation",
        "parent_retention",
        "child_entry",
        "child_execute",
        "cleanup",
    }
    assert phase in phases, "Fixed failure phase required"
    kinds = {
        "PermissionError",
        "ValueError",
        "TypeError",
        "KeyError",
        "AttributeError",
        "AssertionError",
        "TimeoutError",
        "OSError",
        "RuntimeError",
        "ValidationError",
        "ConnectionError",
    }
    reported = getattr(error, "safe_causal_failure", None)
    if (
        type(reported) is dict
        and set(reported) == {"phase", "exception_type", "reason"}
        and all(type(value) is str for value in reported.values())
        and reported["phase"] in phases
        and reported["exception_type"] in kinds | {"Exception"}
        and reported["reason"] in {"operation_failed", "diagnostic_retention_failed"}
    ):
        return dict(reported, reason="diagnostic_retention_failed")
    kind = next((item.__name__ for item in type(error).__mro__ if item.__name__ in kinds), "Exception")
    return dict(
        phase=phase,
        exception_type=kind,
        reason=(
            "diagnostic_retention_failed"
            if getattr(error, "diagnostic_retention_failed", False) is True
            else "operation_failed"
        ),
    )


def retain_failure(
    area, *, run_id, intent_id, contract_sha256, fence, registration, phase, error, protect, cleanup=False
):
    """Keep the first causal error and first cleanup error in existing phase artifacts."""
    binding = dict(
        codec="scene-model-failure-v1",
        run_id=run_id,
        intent_id=intent_id,
        contract_digest=contract_sha256,
        fence=fence,
        category="cleanup" if cleanup else "causal",
    )
    version = hashlib.sha256(canonical(binding)).hexdigest()
    if area.has_final("scene-model-phase", version):
        manifest = area.read_final_manifest("scene-model-phase", version, binding=binding)
        reference = dict(
            family="scene-model-phase", version=version, manifest_digest=manifest["digest"], binding=binding
        )
        read_retained(area, reference, protect=protect)
        return reference
    value = dict(safe_failure(phase, error), binding=binding, registration=registration)
    return _retain(area, "scene-model-phase", binding, value, protect)


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


def retained_response_candidates(record, raw):
    """Read response content before trusting a fallible worker's text projection."""
    candidates = []
    http = record.get("http_response")
    if http is not None and 200 <= http["status_code"] < 300:
        with contextlib.suppress(ValueError):
            candidates.append(("http_response", json.loads(http["body_utf8"])))
    candidates.append(("sdk_response", record.get("response")))
    result = []
    for origin, response in candidates:
        if type(response) is dict:
            with contextlib.suppress(KeyError, IndexError, TypeError):
                result.append((origin, response["choices"][0]["message"]["content"]))
    return result + [("worker_projection", raw)]


def recover_assessment_output(area, payload, *, send_record, failure_kind, protect, diagnostic_retention_failed=False):
    """Recover stopped-owned-worker bytes before considering a counted retry."""
    from isaaclab_arena.agentic_environment_generation.workflow.inference_transport import retryable_http_failure

    def reference(family, binding):
        version = hashlib.sha256(canonical(binding)).hexdigest()
        if not area.has_final(family, version):
            return None
        manifest = area.read_final_manifest(family, version, binding=binding)
        return dict(family=family, version=version, binding=binding, manifest_digest=manifest["digest"])

    binding = dict(payload["request"]["binding"], request_manifest_digest=payload["request"]["manifest_digest"])
    result_binding = dict(binding, codec="scene-model-result-v1")
    completed = reference("scene-model-output", result_binding)
    if completed is not None:
        read_retained(area, completed, protect=protect)
        return completed
    phases, record = {}, None
    for phase in ("request", "response", "complete"):
        ref = reference("scene-model-phase", dict(binding, codec="scene-model-phase-v1", phase=phase))
        if ref is not None:
            phases[phase] = ref
            record = read_retained(area, ref, protect=protect)
    dispatched = send_record is not None
    if dispatched and (
        record is None
        or hashlib.sha256(record["serialized_request"].encode()).hexdigest() != send_record["request_sha256"]
    ):
        raise ValueError("Charged attempt has no matching retained request")
    raw = None
    if record is not None:
        record["dispatched"] = dispatched
        http = record.get("http_response")
        if http is not None and not dispatched:
            raise ValueError("Response without durable dispatch authority")
        if http is not None and "complete" not in phases:
            try:
                response = json.loads(http["body_utf8"])
            except ValueError:
                response = None
            if 200 <= http["status_code"] < 300:
                record["response"] = response
                record["usage"] = response.get("usage") if type(response) is dict else None
            else:
                error = response.get("error") if type(response) is dict else None
                code = error.get("code") if type(error) is dict else None
                record["transport_error"] = dict(
                    kind="retained_http_failure",
                    status=http["status_code"],
                    code=code,
                    retryable=retryable_http_failure(http["status_code"], code),
                    request_id=http["request_id"],
                )
        if dispatched and http is None and record["transport_error"] is None:
            record["transport_error"] = dict(
                kind="owned_transport_incomplete",
                observed_failure=failure_kind,
                status=None,
                code=None,
                retryable=not diagnostic_retention_failed,
                request_id=None,
            )
        raw = next((text for _, text in retained_response_candidates(record, None) if type(text) is str), None)
    output = dict(
        kind="raw_visual_response",
        raw_response=raw,
        publication="not_published",
        provider_records=[] if record is None else [record],
        phase_receipts=phases,
        local_error={"kind": failure_kind, "diagnostic_retention_failed": diagnostic_retention_failed},
        recovery="owned_stopped_retained_bytes_no_resend",
    )
    return _retain(
        area,
        "scene-model-output",
        result_binding,
        dict(
            binding=result_binding,
            output=output,
            attempted_calls=int(dispatched),
        ),
        protect,
    )


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
    if not (allowance.token_cost_bounded or allowance.accounting_only):
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

            retained = data.get("consumer_contract_digest") is not None
            expected_fields = {"criterion", "candidate", "cohort", "observation_manifest_digest"}
            if retained:
                expected_fields |= {"consumer_contract_digest", "producer_source"}
            if set(data) != expected_fields:
                raise ValueError("Invalid assessment request")
            candidate, cohort = CandidateBinding.model_validate(data["candidate"]), EvidenceCohort.model_validate(
                data["cohort"]
            )
            consumer_digest = data["consumer_contract_digest"] if retained else candidate.contract_digest
            if consumer_digest != payload["request"]["binding"]["contract_digest"]:
                raise ValueError("Candidate contract mismatch")
            if retained:
                from isaaclab_arena.agentic_environment_generation.workflow.contracts import RetainedEvidenceSource

                source = RetainedEvidenceSource.model_validate(data["producer_source"])
                if (
                    not allowance.accounting_only
                    or candidate.candidate_digest != source.candidate_digest
                    or candidate.contract_digest != source.contract_digest
                    or candidate.profile_digest != source.profile_digest
                    or data["observation_manifest_digest"] != source.observation_manifest_digest
                ):
                    raise ValueError("Retained producer/consumer link mismatch")
            artifacts = SceneEvidenceArtifacts(area)
            observation = artifacts.load_receipt(
                candidate,
                cohort,
                kind="observation",
                manifest_digest=data["observation_manifest_digest"],
                protect=protect,
            )
            raw, error = None, None
            phases = {}
            if retained:

                def retain_phase(phase, record):
                    binding = dict(
                        payload["request"]["binding"],
                        codec="scene-model-phase-v1",
                        request_manifest_digest=payload["request"]["manifest_digest"],
                        phase=phase,
                    )
                    phases[phase] = _retain(area, "scene-model-phase", binding, record, protect)

                allowance.retain_provider_phase = retain_phase
            try:
                raw = tools.assess(
                    criterion=Criterion.model_validate(data["criterion"]),
                    candidate=candidate,
                    cohort=cohort,
                    artifacts=artifacts,
                    observation=observation,
                    protect=protect,
                )
            except Exception as exc:
                if not retained:
                    raise
                error = safe_failure("child_execute", exc)
                error["kind"] = error["exception_type"]
                source = payload["request"]["binding"]
                try:
                    retain_failure(
                        area,
                        run_id=source["run_id"],
                        intent_id=source["fence"]["intent_id"],
                        contract_sha256=source["contract_digest"],
                        fence=source["fence"],
                        registration=source["registration"],
                        phase="child_execute",
                        error=exc,
                        protect=protect,
                    )
                except Exception:
                    setattr(exc, "diagnostic_retention_failed", True)
                    raise exc from None
            if not retained and (type(raw) is not str or not 1 <= len(raw.encode()) <= 65536):
                raise ValueError("Visual response bound")
            output = {"kind": "raw_visual_response", "raw_response": raw, "publication": "not_published"}
            if retained:
                output.update(provider_records=allowance.provider_records, local_error=error, phase_receipts=phases)
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
    packet = None
    phase = "child_entry"
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
            if "request_bounds" in packet["config"]
            else None
        )
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            phase = "child_execute"
            receipt = execute(packet, allowance, protect, send_guard=send_guard)
        message = {"result": receipt}
        _protected(message, protect)
        channel.write(json.dumps(message, allow_nan=False) + "\n")
        channel.flush()
        return 0
    except Exception as exc:
        # The parent can still report a failed diagnostic write and clean up.
        # Nothing from the private packet or exception message crosses this pipe.
        diagnostic_retention_failed = getattr(exc, "diagnostic_retention_failed", False) is True
        try:
            if packet is not None and packet["config"]["workflow_accounting"]["version"] == 2:
                payload = packet["inputs"]["scene_payload"]
                source = payload["request"]["binding"]
                with open_area(payload) as area:
                    retain_failure(
                        area,
                        run_id=source["run_id"],
                        intent_id=source["fence"]["intent_id"],
                        contract_sha256=source["contract_digest"],
                        fence=source["fence"],
                        registration=source["registration"],
                        phase=phase,
                        error=exc,
                        protect=protect,
                    )
        except Exception:
            diagnostic_retention_failed = True
        if diagnostic_retention_failed:
            channel.write(json.dumps({"diagnostic_retention_failed": safe_failure(phase, exc)}) + "\n")
            channel.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
