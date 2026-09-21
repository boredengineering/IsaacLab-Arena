# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded JSON evidence on the existing immutable ArtifactArea, not authorization.

Images use explicit base64 JSON, within the existing 2 MiB file ceiling. Protection
is mandatory and reject-only. The trusted caller owns capture/source authenticity.
"""

import hashlib
import json
from dataclasses import dataclass

from .evidence import CandidateBinding, EvidenceCohort


def canonical(value, *, max_bytes=2 * 1024 * 1024):
    """Encode a finite JSON tree; query callers may supply their serialization bound.

    Artifact callers retain the unchanged 2 MiB default and structural guards.
    """

    def check(node, depth=0):
        if depth > 24:
            raise ValueError("evidence nesting bound")
        if type(node) is dict:
            if len(node) > 4096 or any(type(k) is not str for k in node):
                raise ValueError("evidence mapping bound")
            for child in node.values():
                check(child, depth + 1)
        elif type(node) is list:
            if len(node) > 4096:
                raise ValueError("evidence sequence bound")
            for child in node:
                check(child, depth + 1)
        elif node is not None and type(node) not in (str, int, float, bool):
            raise ValueError("evidence JSON types required")

    check(value)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    if len(raw) > max_bytes:
        raise ValueError("evidence byte bound")
    return raw


def _protected(value, protect, *, max_bytes=2 * 1024 * 1024):
    before = canonical(value, max_bytes=max_bytes)
    returned = protect(value)
    try:
        after = canonical(value, max_bytes=max_bytes)
        if returned is not None and canonical(returned, max_bytes=max_bytes) != before:
            raise ValueError("reject-only protection required")
    except (ValueError, TypeError, RecursionError):
        raise ValueError("reject-only protection required") from None
    if before != after:
        raise ValueError("reject-only protection required")
    return before


@dataclass(frozen=True)
class SceneEvidenceReceipt:
    candidate: CandidateBinding
    cohort: EvidenceCohort
    relative_directory: str
    manifest_json: str

    @property
    def manifest_digest(self):
        """Identity only; use verified_payload before treating it as verified."""
        return json.loads(self.manifest_json)["digest"]


class SceneEvidenceArtifacts:
    """Retain exact cohort payloads; never overwrite or silently repair retries."""

    def __init__(self, area):
        self.area = area

    @staticmethod
    def _binding(candidate, cohort):
        candidate = CandidateBinding.model_validate(candidate)
        cohort = EvidenceCohort.model_validate(cohort)
        if (candidate.contract_digest, candidate.profile_digest) != (cohort.contract_digest, cohort.profile_digest):
            raise ValueError("candidate/cohort mismatch")
        return {
            "codec": "scene-evidence-v1",
            "candidate": candidate.model_dump(mode="json"),
            "cohort": cohort.model_dump(mode="json"),
        }

    def write(self, candidate, cohort, payload, *, protect):
        """Write observation or visual-answer data and verify actual retained bytes."""
        binding = self._binding(candidate, cohort)
        if type(payload) is not dict or payload.get("kind") not in ("observation", "visual-answer"):
            raise ValueError("unsupported evidence kind")
        envelope = dict(binding, payload=payload)
        raw = _protected(envelope, protect)
        # Cohort identity excludes candidate so changed candidates cannot reuse it.
        version = hashlib.sha256(canonical(binding["cohort"])).hexdigest()
        family = "scene-" + payload["kind"]
        files = {"evidence.json": raw}
        manifest = self.area.expected_manifest(version, files, binding)
        with self.area.writer_lock():
            if not self.area.has_final(family, version):
                self.area.stage(version, files, binding)
            relative = self.area.promote(version, family, version, manifest)
        receipt = SceneEvidenceReceipt(candidate, cohort, relative, json.dumps(manifest, sort_keys=True))
        self.verified_payload(receipt, protect=protect)
        return receipt

    def load_receipt(self, candidate, cohort, *, kind, manifest_digest, protect):
        """Reopen one exact final receipt, without scans or caller verification flags."""
        if kind not in ("observation", "visual-answer"):
            raise ValueError("unsupported evidence kind")
        if (
            type(manifest_digest) is not str
            or len(manifest_digest) != 64
            or any(c not in "0123456789abcdef" for c in manifest_digest)
        ):
            raise ValueError("exact evidence manifest digest required")
        binding = self._binding(candidate, cohort)
        version = hashlib.sha256(canonical(binding["cohort"])).hexdigest()
        family = "scene-" + kind
        manifest = self.area.read_final_manifest(family, version, binding=binding)
        if manifest["digest"] != manifest_digest:
            raise ValueError("evidence manifest digest mismatch")
        receipt = SceneEvidenceReceipt(
            CandidateBinding.model_validate(binding["candidate"]),
            EvidenceCohort.model_validate(binding["cohort"]),
            f"final/{family}/{version}",
            json.dumps(manifest, sort_keys=True),
        )
        payload = self.verified_payload(receipt, protect=protect)
        if payload.get("kind") != kind:
            raise ValueError("evidence kind mismatch")
        return receipt

    def verified_payload(self, receipt, *, protect):
        """Re-read exact manifest and bytes, screen current policy, and re-sync."""
        binding = self._binding(receipt.candidate, receipt.cohort)
        manifest = json.loads(receipt.manifest_json)
        if canonical(manifest["binding"]) != canonical(binding):
            raise ValueError("receipt binding mismatch")
        with self.area.writer_lock():
            files = self.area.verify(receipt.relative_directory, manifest)
            if set(files) != {"evidence.json"}:
                raise ValueError("unexpected evidence files")
            envelope = json.loads(files["evidence.json"])
            if canonical({k: v for k, v in envelope.items() if k != "payload"}) != canonical(binding):
                raise ValueError("payload binding mismatch")
            if _protected(envelope, protect) != files["evidence.json"]:
                raise ValueError("noncanonical evidence bytes")
            _, family, version = receipt.relative_directory.split("/")
            self.area.promote(version, family, version, manifest)
        return envelope["payload"]
