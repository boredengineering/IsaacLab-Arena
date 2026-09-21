# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Credential-free fixed native/numeric codecs; receipts never confer authority."""

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

from .contracts import WorkflowContract, contract_digest
from .native_capture import NativeCaptureProducer, NativeCaptureSettings
from .scene_evidence_artifacts import _protected, canonical
from .scene_loop import CandidateRecord, Observation, SceneIntent, identity

CODECS = {"capture": "native-scene", "assess": "numeric-scene"}


@dataclass(frozen=True)
class SceneWorkerRequest:
    action: str
    intent: SceneIntent
    candidate: CandidateRecord
    original: CandidateRecord
    contract: WorkflowContract
    settings: NativeCaptureSettings
    deadline: float
    retained_observation: Observation | None

    def binding(self):
        return dict(
            codec=CODECS[self.action] + "-request-v1",
            intent_digest=identity(self.intent.model_dump(mode="json")),
            candidate_digest=self.candidate.digest,
            candidate_id=self.candidate.candidate_id,
            original_digest=identity(self.original.model_dump(mode="json")),
            settings_sha256=self.settings.digest(),
            contract_digest=contract_digest(self.contract),
            registration=self.intent.worker_registration.model_dump(mode="json"),
            deadline=self.deadline,
            observation_digest=self.intent.observation_digest,
        )


def validate_request(data, *, now=None):
    """Revalidate released metadata and every frozen binding before native imports."""
    if (
        type(data) is not dict
        or set(data)
        != {"action", "intent", "candidate", "original", "contract", "settings", "deadline", "retained_observation"}
        or data["action"] not in CODECS
    ):
        raise ValueError("exact native/numeric request required")
    r = SceneWorkerRequest(
        data["action"],
        SceneIntent.model_validate_json(canonical(data["intent"])),
        CandidateRecord.model_validate_json(canonical(data["candidate"])),
        CandidateRecord.model_validate_json(canonical(data["original"])),
        WorkflowContract.model_validate_json(canonical(data["contract"])),
        NativeCaptureSettings.model_validate_json(canonical(data["settings"])),
        data["deadline"],
        (
            None
            if data["retained_observation"] is None
            else Observation.model_validate_json(canonical(data["retained_observation"]))
        ),
    )
    i, c, s = r.intent, r.candidate, r.settings
    now = time.time() if now is None else now
    if (
        i.codec_version != 2
        or i.action != r.action
        or i.status != "released"
        or i.released_at is None
        or not math.isfinite(i.released_at)
        or i.released_at > now
        or i.worker_registration is None
        or i.worker_fence is None
        or i.worker_cleanup is not None
        or i.worker_registration.fence != i.worker_fence
        or i.worker_fence.intent_id != i.intent_id
        or i.worker_fence.run_id != c.run_id
        or i.candidate_id != c.candidate_id
        or c.original_id != r.original.candidate_id
        or c.run_id != r.original.run_id
        or r.original.original_id != r.original.candidate_id
        or r.original.parent_id is not None
    ):
        raise ValueError("exact registered released stage required")
    for candidate in (c, r.original):
        if (
            hashlib.sha256(candidate.scene_json.encode()).hexdigest() != candidate.digest
            or identity(candidate.run_id, candidate.source_id, candidate.digest) != candidate.candidate_id
            or type(json.loads(candidate.scene_json)) is not dict
        ):
            raise ValueError("exact candidate bytes required")
    reservation = i.reservation
    if (
        type(r.deadline) not in (float, int)
        or not math.isfinite(r.deadline)
        or r.deadline <= now
        or r.deadline
        > i.released_at
        + min(
            reservation.runtime_allowance_seconds,
            r.contract.budget.per_operation_timeout_seconds,
            r.contract.budget.total_deadline_seconds,
        )
        or any((
            reservation.model_calls,
            reservation.model_tokens,
            reservation.cost_ceiling_usd,
            reservation.candidates,
            reservation.revisions,
            reservation.policy_episodes,
            reservation.policy_steps,
        ))
    ):
        raise ValueError("bounded credential-free stage release required")
    # admit() is pure; this object does not construct a simulator or model.
    NativeCaptureProducer(settings=s, artifacts=None, protect=lambda _: None, output_root=".").admit(r.contract)
    if r.action == "capture":
        if (
            r.retained_observation is not None
            or reservation.realizations != 1
            or reservation.observations != 1
            or reservation.steps < s.window.end_step
            or reservation.runtime_allowance_seconds < s.max_runtime_seconds
        ):
            raise ValueError("exact capture reservation required")
    elif (
        r.retained_observation is None
        or identity(r.retained_observation.model_dump(mode="json")) != i.observation_digest
        or len(r.retained_observation.verified_manifest_digests) != 1
        or any(c.kind == "visual" for c in s.criteria)
        or any((reservation.realizations, reservation.observations, reservation.steps))
    ):
        raise ValueError("exact numeric retained observation required")
    return r


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
    return dict(family=family, version=version, manifest_digest=manifest["digest"], binding=binding)


def read_retained(area, reference, *, family, binding, protect):
    """Reopen protected canonical bytes, never accept a caller verification flag."""
    if (
        type(reference) is not dict
        or set(reference) != {"family", "version", "manifest_digest", "binding"}
        or reference["family"] != family
        or canonical(reference["binding"]) != canonical(binding)
        or reference["version"] != hashlib.sha256(canonical(binding)).hexdigest()
    ):
        raise ValueError("stage artifact binding mismatch")
    manifest = area.read_final_manifest(family, reference["version"], binding=binding)
    if manifest["digest"] != reference["manifest_digest"]:
        raise ValueError("stage manifest mismatch")
    with area.writer_lock():
        files = area.verify(f"final/{family}/{reference['version']}", manifest)
        if set(files) != {"value.json"}:
            raise ValueError("stage files mismatch")
        value = json.loads(files["value.json"])
        if _protected(value, protect) != files["value.json"]:
            raise ValueError("noncanonical stage value")
        area.promote(reference["version"], family, reference["version"], manifest)
    return value


def retain_request(
    area, *, root, action, intent, candidate, original, contract, settings, deadline, protect, retained_observation=None
):
    """Retain one release; no authority, callback names or credentials on the wire."""
    data = dict(action=action, deadline=deadline)
    for key, value in dict(
        intent=intent,
        candidate=candidate,
        original=original,
        contract=contract,
        settings=settings,
        retained_observation=retained_observation,
    ).items():
        data[key] = None if value is None else value.model_dump(mode="json")
    request = validate_request(data)
    prefix = CODECS[action]
    ref = _retain(area, prefix + "-input", request.binding(), data, protect)
    packet = dict(
        codec=prefix + "-packet-v1",
        payload=dict(
            root=str(Path(root).absolute()), store_id=area.store_id, registry_id=area.registry_id, request=ref
        ),
    )
    _protected(packet, protect)
    return packet


def decode_packet(raw):
    """Decode one bounded unambiguous finite JSON release frame."""
    if type(raw) is not bytes or len(raw) > 512 * 1024 or not raw.endswith(b"\n"):
        raise ValueError("bounded stage frame required")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate stage field")
            value[key] = item
        return value

    def invalid_constant(value):
        raise ValueError("finite stage values required")

    packet = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    canonical(packet, max_bytes=512 * 1024)
    packet_action(packet)
    return packet


def packet_action(packet):
    if type(packet) is not dict or set(packet) != {"codec", "payload"}:
        raise ValueError("exact credential-free packet required")
    actions = [action for action, prefix in CODECS.items() if packet["codec"] == prefix + "-packet-v1"]
    p = packet["payload"]
    if len(actions) != 1 or type(p) is not dict or set(p) != {"root", "store_id", "registry_id", "request"}:
        raise ValueError("versioned stage packet required")
    if type(p["root"]) is not str or not Path(p["root"]).is_absolute():
        raise ValueError("absolute artifact root required")
    return actions[0]


def read_request(area, packet, *, protect):
    action = packet_action(packet)
    p = packet["payload"]
    if (p["store_id"], p["registry_id"]) != (area.store_id, area.registry_id):
        raise ValueError("exact artifact area required")
    ref = p["request"]
    data = read_retained(area, ref, family=CODECS[action] + "-input", binding=ref["binding"], protect=protect)
    request = validate_request(data)
    if action != request.action or canonical(request.binding()) != canonical(ref["binding"]):
        raise ValueError("released request binding mismatch")
    return request


def result_binding(packet):
    action = packet_action(packet)
    reference = packet["payload"]["request"]
    return dict(
        reference["binding"], codec=CODECS[action] + "-result-v1", request_manifest_digest=reference["manifest_digest"]
    )


def result_version(packet):
    return hashlib.sha256(canonical(result_binding(packet))).hexdigest()


def retain_result(area, packet, output, *, protect):
    """Retain the final receipt reference before native Kit teardown."""
    binding = result_binding(packet)
    return _retain(
        area, CODECS[packet_action(packet)] + "-output", binding, dict(binding=binding, output=output), protect
    )


def capture_reference(receipt):
    return dict(
        candidate=receipt.candidate.model_dump(mode="json"),
        cohort=receipt.cohort.model_dump(mode="json"),
        manifest_digest=receipt.manifest_digest,
    )


def reopen_capture(area, request, reference, *, protect):
    """Reopen exact capture bytes and recompute numeric evidence without Kit/model."""
    from .evidence import CandidateBinding, EvidenceCohort
    from .scene_evidence_artifacts import SceneEvidenceArtifacts
    from .scene_loop import profile_digest

    if type(reference) is not dict or set(reference) != {"candidate", "cohort", "manifest_digest"}:
        raise ValueError("exact capture reference required")
    binding = CandidateBinding(
        candidate_digest=request.candidate.digest,
        contract_digest=contract_digest(request.contract),
        profile_digest=profile_digest(request.contract),
    )
    if canonical(binding.model_dump(mode="json")) != canonical(reference["candidate"]):
        raise ValueError("capture candidate mismatch")
    cohort = EvidenceCohort.model_validate_json(canonical(reference["cohort"]))
    if request.action == "capture":
        tag = identity(request.intent.intent_id, request.candidate.candidate_id)
        s = request.settings
        expected = EvidenceCohort(
            realization_id=tag,
            reset_id=identity(tag, "reset"),
            environment_id="native-env0",
            window_id=identity(tag, "window", s.window.model_dump(), s.digest()),
            frame_id="world",
            contract_digest=binding.contract_digest,
            profile_digest=binding.profile_digest,
        )
        if cohort != expected:
            raise ValueError("capture cohort mismatch")
    elif (
        cohort != request.retained_observation.cohort
        or reference["manifest_digest"] != request.retained_observation.verified_manifest_digests[0]
    ):
        raise ValueError("numeric capture binding mismatch")
    artifacts = SceneEvidenceArtifacts(area)
    receipt = artifacts.load_receipt(
        binding, cohort, kind="observation", manifest_digest=reference["manifest_digest"], protect=protect
    )
    producer = NativeCaptureProducer(settings=request.settings, artifacts=artifacts, protect=protect, output_root=".")
    observation = producer.replay(receipt, contract=request.contract, candidate=request.candidate)
    if request.action == "assess" and observation != request.retained_observation:
        raise ValueError("retained numeric assessment differs from replay")
    return receipt, observation


def numeric_evaluate(area, request, *, protect):
    from .contracts import contract_digest
    from .scene_loop import profile_digest

    output = request.retained_observation
    reference = dict(
        candidate=dict(
            candidate_digest=request.candidate.digest,
            contract_digest=contract_digest(request.contract),
            profile_digest=profile_digest(request.contract),
        ),
        cohort=output.cohort.model_dump(mode="json"),
        manifest_digest=output.verified_manifest_digests[0],
    )
    return reopen_capture(area, request, reference, protect=protect)[1]


def read_result(area, packet, request, reference, *, protect):
    """Verify immutable final result AND its evidence; caller must verify child exit."""
    binding = result_binding(packet)
    value = read_retained(area, reference, family=CODECS[request.action] + "-output", binding=binding, protect=protect)
    if (
        type(value) is not dict
        or set(value) != {"binding", "output"}
        or canonical(value["binding"]) != canonical(binding)
    ):
        raise ValueError("stage result shape mismatch")
    if request.action == "capture":
        return reopen_capture(area, request, value["output"], protect=protect)[0]
    checked = numeric_evaluate(area, request, protect=protect)
    if canonical(value["output"]) != canonical(checked.model_dump(mode="json")):
        raise ValueError("numeric output differs from retained evidence")
    return checked
