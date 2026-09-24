# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Immutable generation files using the existing artifact area, never a queue."""
import base64
import hashlib
import json
import re
from dataclasses import dataclass

from ..workbench.research_artifacts import ArtifactArea, ArtifactError
from .attempts import AttemptFence, WorkerRegistration
from .contracts import WorkflowContract, canonical_json, contract_digest
from .results import GenerationReceipt


def encoded(value):
    """Canonical JSON bytes; no schema or physical validity assertion."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError, RecursionError):
        raise ArtifactError("Invalid generation JSON") from None


def digest(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class RetainedBundle:
    """Exact currently verified bytes; the reference never grants path authority."""

    run_id: str
    kind: str
    reference_id: str
    manifest_digest: str | None
    files: dict[str, bytes]
    record: object
    contract_digest: str | None = None


class RetainedArtifacts:
    """Resolve immutable bytes from scoped retained records, never caller paths."""

    def __init__(self, service, area, protect):
        assert type(area) is ArtifactArea and callable(protect), "Bound artifact area and public protection required"
        self.service, self.area, self.protect = service, area, protect

    def read(self, principal, run_id, kind, reference_id):
        if kind not in {"prior", "candidate", "generation", "evidence"} or kind == "prior" and reference_id != run_id:
            raise ValueError("Unsupported artifact reference")
        if kind == "evidence" and (
            type(reference_id) is not str or re.fullmatch(r"[0-9a-f]{128}", reference_id) is None
        ):
            raise ValueError("Exact evidence and manifest identities required")
        intent = self.service.read_run_intent(principal, run_id, protect=self.protect)
        if intent is None:
            return None
        if kind == "evidence":
            from .evidence import CandidateBinding
            from .scene_evidence_artifacts import SceneEvidenceArtifacts
            from .scene_loop import profile_digest

            evidence_id, manifest_digest = reference_id[:64], reference_id[64:]
            view = self.service.read_scene_evidence(principal, evidence_id, protect=self.protect)
            if view is None:
                return None
            if view.run_id != run_id or view.evidence_id != evidence_id:
                raise ValueError("Evidence does not belong to selected run")
            entries = [entry for entry in view.observation.evidence if entry.manifest_digest == manifest_digest]
            if not entries or manifest_digest not in view.observation.verified_manifest_digests:
                raise ValueError("Manifest is not a retained verified evidence reference")
            selected = entries[0]
            family = "visual-answer" if selected.modality == "visual" else "observation"
            if any(
                (entry.candidate_digest, entry.cohort, entry.modality == "visual")
                != (selected.candidate_digest, selected.cohort, selected.modality == "visual")
                for entry in entries
            ):
                raise ValueError("Ambiguous retained manifest binding")
            binding = CandidateBinding(
                candidate_digest=selected.candidate_digest,
                contract_digest=contract_digest(intent.contract),
                profile_digest=profile_digest(intent.contract),
            )
            receipt = SceneEvidenceArtifacts(self.area).load_receipt(
                binding,
                selected.cohort,
                kind=family,
                manifest_digest=manifest_digest,
                protect=self.protect,
            )
            files = self.area.verify(receipt.relative_directory, json.loads(receipt.manifest_json))
            return RetainedBundle(run_id, kind, reference_id, manifest_digest, files, receipt, binding.contract_digest)
        if kind == "generation":
            _, attempt, _ = self.service.read_generation_recovery(principal, run_id)
            if attempt.fence.run_id != run_id or attempt.fence.attempt_id != reference_id:
                raise ValueError("Generation does not belong to selected run/attempt")
            receipt = attempt.receipt
            if receipt is None:
                return None
            if (
                not attempt.released
                or receipt.fence != attempt.fence
                or receipt.registration != attempt.registration
                or receipt.contract_digest != contract_digest(intent.contract)
            ):
                raise ValueError("Retained generation receipt binding differs")
            files = GenerationArtifacts(self.area).verified_bytes(receipt, protect=self.protect)
            return RetainedBundle(
                run_id, kind, reference_id, receipt.manifest_sha256, files, receipt, receipt.contract_digest
            )
        if kind == "candidate":
            view = self.service.read_scene_candidate(principal, reference_id, protect=self.protect)
            if view is None:
                return None
            candidate = view.candidate
            if view.run_id != run_id or candidate.run_id != run_id or candidate.candidate_id != reference_id:
                raise ValueError("Candidate does not belong to selected run")
            raw = candidate.scene_json.encode()
            if len(raw) > 2 * 1024 * 1024 or digest(raw) != candidate.digest:
                raise ValueError("Retained candidate bytes changed")
            return RetainedBundle(
                run_id, kind, reference_id, None, {"candidate.json": raw}, candidate, contract_digest(intent.contract)
            )
        if intent.contract.source.kind != "new":
            return None
        from .prior_artifacts import RetainedPriorArtifacts, RetainedPriorReceipt
        from .scene_evidence_artifacts import canonical

        prompt = intent.contract.source.prompt
        sha = contract_digest(intent.contract)
        if intent.contract.retrieval is not None:
            reference = self.service.bound_store.get_prior_reference(run_id)
            if reference is None:
                raise ValueError("Authoritative prior linkage unavailable")
            receipt = RetainedPriorArtifacts(self.area).reopen(
                reference,
                contract=intent.contract,
                run_id=run_id,
                protect=self.protect,
                enforce_policy=False,
            )
            manifest = json.loads(receipt.manifest_json)
        else:
            binding = RetainedPriorArtifacts._binding(prompt, sha, run_id)
            version = digest(canonical(binding))
            if not self.area.has_final("scene-prior", version):
                return None
            manifest = self.area.read_final_manifest("scene-prior", version, binding=binding)
            receipt = RetainedPriorReceipt(f"final/scene-prior/{version}", json.dumps(manifest, sort_keys=True))
        snapshot = RetainedPriorArtifacts(self.area).verified_snapshot(
            receipt, prompt=prompt, contract_digest=sha, run_id=run_id, protect=self.protect
        )
        files = self.area.verify(receipt.relative_directory, manifest)
        return RetainedBundle(run_id, kind, reference_id, manifest["digest"], files, snapshot, sha)


def artifact_chunk(bundle, name, expected_sha256, offset, limit):
    """Return at most 64 KiB of an exact fully verified immutable file."""
    if (
        type(name) is not str
        or name not in bundle.files
        or type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 65536
        or type(expected_sha256) is not str
    ):
        raise ValueError("Invalid bounded artifact selection")
    raw = bundle.files[name]
    sha = digest(raw)
    if expected_sha256 != sha or offset > len(raw):
        raise ValueError("Artifact identity or range differs")
    selected = raw[offset : offset + limit]
    return dict(
        run_id=bundle.run_id,
        kind=bundle.kind,
        reference_id=bundle.reference_id,
        name=name,
        sha256=sha,
        total_bytes=len(raw),
        offset=offset,
        length=len(selected),
        eof=offset + len(selected) == len(raw),
        data=base64.b64encode(selected).decode("ascii"),
    )


class GenerationArtifacts:
    """Protect private values before writing and on every verified readback."""

    def __init__(self, area):
        if type(area) is not ArtifactArea:
            raise ValueError("concrete artifact area required")
        self.area = area

    @staticmethod
    def _screen(files, protect):
        if not callable(protect):
            raise ValueError("artifact protection callback required")
        value = {
            "raw_yaml": files["candidate.yaml"].decode("utf-8"),
            "spec": json.loads(files["candidate.json"]),
            "provenance": json.loads(files["provenance.json"]),
        }
        before = encoded(value)
        protect(value)
        if encoded(value) != before:
            raise ValueError("artifact protection must not mutate data")

    def write(
        self,
        fence,
        registration,
        contract,
        raw_yaml,
        spec,
        *,
        protect,
        catalogue_ref=None,
        prior_ref=None,
        producer_metadata=None,
    ):
        """Persist one exact candidate; unknown references are explicit, never inferred."""
        fence = AttemptFence.model_validate_json(fence.model_dump_json())
        registration = WorkerRegistration.model_validate_json(registration.model_dump_json())
        contract = WorkflowContract.model_validate_json(contract.model_dump_json())
        if (
            registration.fence != fence
            or contract.source.kind != "new"
            or type(raw_yaml) is not bytes
            or type(spec) is not dict
        ):
            raise ValueError("invalid generation artifact binding")
        for ref in (catalogue_ref, prior_ref):
            if ref is not None and (type(ref) is not str or not 1 <= len(ref) <= 1024):
                raise ValueError("invalid provenance reference")
        provenance = {
            "schema": 1,
            "fence": fence.model_dump(mode="json"),
            "registration": registration.model_dump(mode="json"),
            "contract": json.loads(canonical_json(contract)),
            "contract_digest": contract_digest(contract),
            "generation_profile": contract.execution.generation_model.model_dump(mode="json"),
            "source": contract.source.model_dump(mode="json"),
            "catalogue_ref": catalogue_ref if catalogue_ref is not None else {"status": "unknown"},
            "prior_ref": prior_ref if prior_ref is not None else {"status": "unknown"},
        }
        if producer_metadata is not None:
            if type(producer_metadata) is not dict:
                raise ValueError("producer metadata must be a JSON object")
            # Retain findings/context rather than only their reference. Shape and
            # meaning are validated by the generation adapter, not this byte store.
            # Existing artifact-area payload bounds and public screening still apply.
            provenance["producer_metadata"] = json.loads(encoded(producer_metadata))
        files = {
            "candidate.yaml": raw_yaml,
            "candidate.json": encoded(spec),
            "provenance.json": encoded(provenance),
        }
        self._screen(files, protect)
        binding = {
            "fence": fence.model_dump(mode="json"),
            "registration": registration.model_dump(mode="json"),
            "contract_digest": contract_digest(contract),
            "generation_profile": contract.execution.generation_model.model_dump(mode="json"),
        }
        identity = digest(encoded(binding))
        directory = f"final/generation/{identity}"
        with self.area.writer_lock():
            manifest = self.area.expected_manifest(identity, files, binding)
            if self.area.has_final("generation", identity):
                self.area.verify(directory, manifest)
            else:
                self.area.stage(identity, files, binding)
            self.area.promote(identity, "generation", identity, manifest)
            self.area.verify(directory, manifest)
        return GenerationReceipt(
            fence=fence,
            registration=registration,
            contract_digest=contract_digest(contract),
            generation_profile=contract.execution.generation_model,
            candidate_yaml_sha256=digest(files["candidate.yaml"]),
            candidate_json_sha256=digest(files["candidate.json"]),
            provenance_sha256=digest(files["provenance.json"]),
            manifest_sha256=manifest["digest"],
            manifest_json=encoded(manifest).decode(),
            artifact_directory=directory,
        )

    def load_receipt(self, fence, registration, contract, *, protect):
        """Reconstruct a verified receipt from exact retained bindings, not a directory scan.

        Args:
            fence: Original authoritative attempt fence.
            registration: Original retained worker registration.
            contract: Original frozen workflow contract.
            protect: Reject-only public-data protection callback.

        Returns:
            A byte-verified receipt; no execution, cleanup or acceptance authority.
        """
        fence = AttemptFence.model_validate_json(fence.model_dump_json())
        registration = WorkerRegistration.model_validate_json(registration.model_dump_json())
        contract = WorkflowContract.model_validate_json(contract.model_dump_json())
        if registration.fence != fence or contract.source.kind != "new":
            raise ValueError("Exact generation recovery binding required")
        binding = {
            "fence": fence.model_dump(mode="json"),
            "registration": registration.model_dump(mode="json"),
            "contract_digest": contract_digest(contract),
            "generation_profile": contract.execution.generation_model.model_dump(mode="json"),
        }
        identity = digest(encoded(binding))
        manifest = self.area.read_final_manifest("generation", identity, binding=binding)
        if set(manifest["files"]) != {"candidate.yaml", "candidate.json", "provenance.json"}:
            raise ArtifactError("Generation recovery file set mismatch")
        receipt = GenerationReceipt(
            fence=fence,
            registration=registration,
            contract_digest=contract_digest(contract),
            generation_profile=contract.execution.generation_model,
            candidate_yaml_sha256=manifest["files"]["candidate.yaml"]["sha256"],
            candidate_json_sha256=manifest["files"]["candidate.json"]["sha256"],
            provenance_sha256=manifest["files"]["provenance.json"]["sha256"],
            manifest_sha256=manifest["digest"],
            manifest_json=encoded(manifest).decode(),
            artifact_directory=f"final/generation/{identity}",
        )
        self.verify(receipt, protect=protect)
        # A crashed writer may have promoted bytes before confirming durability.
        # Reuse exact-final retry syncing; never promote a staging-only candidate.
        with self.area.writer_lock():
            if not self.area.has_final("generation", identity):
                raise ArtifactError("Final generation recovery artifact required")
            self.area.promote(identity, "generation", identity, manifest)
        return self.verify(receipt, protect=protect)

    def verify(self, receipt, *, protect):
        """Read all real bytes and compare every retained binding immediately before adoption."""
        self.verified_bytes(receipt, protect=protect)
        return receipt

    def verified_bytes(self, receipt, *, protect):
        """Return the exact protected bytes whose complete bindings were verified."""
        if type(receipt) is not GenerationReceipt:
            raise ValueError("typed generation receipt required")
        receipt = GenerationReceipt.model_validate_json(receipt.model_dump_json())
        manifest = json.loads(receipt.manifest_json)
        if encoded(manifest).decode() != receipt.manifest_json or manifest["digest"] != receipt.manifest_sha256:
            raise ArtifactError("receipt manifest mismatch")
        binding = {
            "fence": receipt.fence.model_dump(mode="json"),
            "registration": receipt.registration.model_dump(mode="json"),
            "contract_digest": receipt.contract_digest,
            "generation_profile": receipt.generation_profile.model_dump(mode="json"),
        }
        identity = digest(encoded(binding))
        if (
            encoded(manifest["binding"]) != encoded(binding)
            or manifest["reservation_id"] != identity
            or receipt.artifact_directory != f"final/generation/{identity}"
        ):
            raise ArtifactError("receipt artifact binding mismatch")
        with self.area.writer_lock():
            files = self.area.verify(receipt.artifact_directory, manifest)
        expected = {
            "candidate.yaml": receipt.candidate_yaml_sha256,
            "candidate.json": receipt.candidate_json_sha256,
            "provenance.json": receipt.provenance_sha256,
        }
        if set(files) != set(expected) or any(digest(files[name]) != sha for name, sha in expected.items()):
            raise ArtifactError("receipt payload mismatch")
        provenance = json.loads(files["provenance.json"])
        contract = WorkflowContract.model_validate(provenance["contract"])
        if (
            any(encoded(provenance[key]) != encoded(value) for key, value in binding.items())
            or contract_digest(contract) != receipt.contract_digest
            or contract.execution.generation_model != receipt.generation_profile
            or provenance["source"] != contract.source.model_dump(mode="json")
            or not {"catalogue_ref", "prior_ref"} <= provenance.keys()
            or encoded(json.loads(files["candidate.json"])) != files["candidate.json"]
            or encoded(provenance) != files["provenance.json"]
        ):
            raise ArtifactError("receipt provenance mismatch")
        self._screen(files, protect)
        return files
