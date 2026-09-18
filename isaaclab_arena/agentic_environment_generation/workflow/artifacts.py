# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Immutable generation files using the existing artifact area, never a queue."""
import hashlib
import json

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
    ):
        """Persist one exact candidate; unknown references are explicit, never inferred."""
        fence = AttemptFence.model_validate_json(fence.model_dump_json())
        registration = WorkerRegistration.model_validate_json(
            registration.model_dump_json()
        )
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
            "generation_profile": contract.execution.generation_model.model_dump(
                mode="json"
            ),
            "source": contract.source.model_dump(mode="json"),
            "catalogue_ref": (
                catalogue_ref if catalogue_ref is not None else {"status": "unknown"}
            ),
            "prior_ref": prior_ref if prior_ref is not None else {"status": "unknown"},
        }
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
            "generation_profile": contract.execution.generation_model.model_dump(
                mode="json"
            ),
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
        if (
            encoded(manifest).decode() != receipt.manifest_json
            or manifest["digest"] != receipt.manifest_sha256
        ):
            raise ArtifactError("receipt manifest mismatch")
        binding = {
            "fence": receipt.fence.model_dump(mode="json"),
            "registration": receipt.registration.model_dump(mode="json"),
            "contract_digest": receipt.contract_digest,
            "generation_profile": receipt.generation_profile.model_dump(mode="json"),
        }
        identity = digest(encoded(binding))
        if (
            manifest["binding"] != binding
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
        if set(files) != set(expected) or any(
            digest(files[name]) != sha for name, sha in expected.items()
        ):
            raise ArtifactError("receipt payload mismatch")
        provenance = json.loads(files["provenance.json"])
        contract = WorkflowContract.model_validate(provenance["contract"])
        if (
            any(provenance[key] != value for key, value in binding.items())
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
