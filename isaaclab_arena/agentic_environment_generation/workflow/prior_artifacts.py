# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Immutable prior receipts on ArtifactArea; no graph connection or authorization."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

from ..prior_receipt import validate_prior_snapshot
from .contracts import FrozenModel, Hash, Identifier, contract_digest
from .scene_evidence_artifacts import _protected, canonical

PRIOR_REFERENCE_BYTES = 262144


class FrozenPriorReference(FrozenModel):
    """Authoritative run linkage to one immutable selection and its exact prior bytes."""

    schema_version: Literal["1"]
    run_id: Identifier
    contract_digest: Hash
    selection_sha256: Hash
    disposition: Literal["measured", "structural", "empty", "unavailable"]
    context_sha256: Hash
    relative_directory: Annotated[str, Field(strict=True, min_length=1, max_length=128)]
    manifest_json: Annotated[str, Field(strict=True, min_length=2, max_length=PRIOR_REFERENCE_BYTES)]


def checked_prior_reference(raw, *, contract, run_id):
    """Validate the bounded linkage independently of filesystem access or credentials."""
    if type(raw) is not str or len(raw.encode()) > PRIOR_REFERENCE_BYTES or contract.retrieval is None:
        raise ValueError("Prior linkage unavailable")
    ref = FrozenPriorReference.model_validate_json(raw)
    if (
        ref.run_id != run_id
        or ref.contract_digest != contract_digest(contract)
        or ref.selection_sha256 != hashlib.sha256(canonical(contract.retrieval.model_dump(mode="json"))).hexdigest()
        or canonical(ref.model_dump(mode="json"), max_bytes=PRIOR_REFERENCE_BYTES).decode() != raw
    ):
        raise ValueError("Prior linkage differs")
    return ref


@dataclass(frozen=True)
class RetainedPriorReceipt:
    relative_directory: str
    manifest_json: str


class RetainedPriorArtifacts:
    """Retain one exact validated snapshot under the original prompt/contract/run."""

    def __init__(self, area):
        self.area = area

    @staticmethod
    def _binding(prompt, contract_digest, run_id):
        if (
            type(prompt) is not str
            or not prompt.strip()
            or len(prompt) > 32768
            or type(contract_digest) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", contract_digest)
            or type(run_id) is not str
            or not run_id.strip()
            or len(run_id) > 256
        ):
            raise ValueError("invalid prior binding")
        return dict(codec="retained-prior-v1", prompt=prompt, contract_digest=contract_digest, run_id=run_id)

    def capture(self, prompt, contract_digest, run_id, *, authorized_retriever, protect):
        """Call an explicitly read-authorized retriever once, then retain its exact snapshot.

        The trusted composition supplies authorization; this method neither creates
        grants nor connects to a graph. Exceptions propagate without fallback.
        Use write with empty_snapshot for unavailable/not_requested outcomes.
        """
        self._binding(prompt, contract_digest, run_id)
        if not callable(authorized_retriever):
            raise ValueError("authorized retriever callback required")
        snapshot = authorized_retriever(prompt)
        return self.write(prompt, contract_digest, run_id, snapshot, protect=protect)

    def write(self, prompt, contract_digest, run_id, snapshot, *, protect):
        binding = self._binding(prompt, contract_digest, run_id)
        validate_prior_snapshot(snapshot, prompt=prompt)
        raw = _protected(dict(binding, prior_snapshot=snapshot), protect)
        version = hashlib.sha256(canonical(binding)).hexdigest()
        files = {"prior.json": raw}
        manifest = self.area.expected_manifest(version, files, binding)
        with self.area.writer_lock():
            if not self.area.has_final("scene-prior", version):
                self.area.stage(version, files, binding)
            relative = self.area.promote(version, "scene-prior", version, manifest)
        receipt = RetainedPriorReceipt(relative, json.dumps(manifest, sort_keys=True))
        self.verified_snapshot(receipt, prompt=prompt, contract_digest=contract_digest, run_id=run_id, protect=protect)
        return receipt

    def verified_snapshot(self, receipt, *, prompt, contract_digest, run_id, protect):
        binding = self._binding(prompt, contract_digest, run_id)
        manifest = json.loads(receipt.manifest_json)
        version = hashlib.sha256(canonical(binding)).hexdigest()
        if (
            canonical(manifest["binding"]) != canonical(binding)
            or receipt.relative_directory != f"final/scene-prior/{version}"
        ):
            raise ValueError("prior binding mismatch")
        with self.area.writer_lock():
            files = self.area.verify(receipt.relative_directory, manifest)
            if set(files) != {"prior.json"}:
                raise ValueError("unexpected prior files")
            envelope = json.loads(files["prior.json"])
            if canonical({k: v for k, v in envelope.items() if k != "prior_snapshot"}) != canonical(binding):
                raise ValueError("prior payload binding mismatch")
            if _protected(envelope, protect) != files["prior.json"]:
                raise ValueError("noncanonical prior bytes")
            validate_prior_snapshot(envelope["prior_snapshot"], prompt=prompt)
            self.area.promote(version, "scene-prior", version, manifest)
        return envelope["prior_snapshot"]

    def reference(self, receipt, *, contract, run_id, protect):
        """Bind the validated retained disposition and context without granting execution."""
        snapshot = self.verified_snapshot(
            receipt,
            prompt=contract.source.prompt,
            contract_digest=contract_digest(contract),
            run_id=run_id,
            protect=protect,
        )
        if contract.retrieval is None:
            raise ValueError("Explicit prior selection required")
        ref = FrozenPriorReference(
            schema_version="1",
            run_id=run_id,
            contract_digest=contract_digest(contract),
            selection_sha256=hashlib.sha256(canonical(contract.retrieval.model_dump(mode="json"))).hexdigest(),
            disposition=snapshot["status"],
            context_sha256=snapshot["context_sha256"],
            relative_directory=receipt.relative_directory,
            manifest_json=receipt.manifest_json,
        )
        raw = canonical(ref.model_dump(mode="json"), max_bytes=PRIOR_REFERENCE_BYTES).decode()
        checked_prior_reference(raw, contract=contract, run_id=run_id)
        protect(raw)
        return raw

    def reopen(self, raw, *, contract, run_id, protect, enforce_policy=True):
        """Reopen only the authoritative bytes; never retrieve, reconstruct or substitute."""
        ref = checked_prior_reference(raw, contract=contract, run_id=run_id)
        receipt = RetainedPriorReceipt(ref.relative_directory, ref.manifest_json)
        snapshot = self.verified_snapshot(
            receipt,
            prompt=contract.source.prompt,
            contract_digest=contract_digest(contract),
            run_id=run_id,
            protect=protect,
        )
        if snapshot["status"] != ref.disposition or snapshot["context_sha256"] != ref.context_sha256:
            raise ValueError("Prior linkage content differs")
        selection = contract.retrieval
        for key, expected in selection.settings.model_dump(mode="json").items():
            observed = snapshot["effective_settings"][key]
            if observed != expected and not (ref.disposition == "unavailable" and observed is None):
                raise ValueError("Retained prior settings differ")
        if enforce_policy and (
            ref.disposition == "unavailable"
            and selection.required
            or ref.disposition == "empty"
            and not selection.allow_empty
        ):
            raise ValueError("Frozen prior requirement not satisfied")
        return receipt
