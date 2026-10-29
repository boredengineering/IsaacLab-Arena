# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Local schema evidence only; no realization, geometry or task acceptance."""

from typing import Literal

from .artifacts import GenerationArtifacts, digest, encoded
from .attempts import AttemptFence
from .contracts import FrozenModel, Hash


class SchemaValidationReceipt(FrozenModel):
    """Immutable source-byte bindings and schema-only findings."""

    schema_version: Literal["1"] = "1"
    kind: Literal["schema_only"] = "schema_only"
    disposition: Literal["schema_validated", "static_failure"]
    failure_code: Literal["invalid_schema", "yaml_json_mismatch", "external_yaml_refused"] | None = None
    fence: AttemptFence
    contract_digest: Hash
    candidate_yaml_sha256: Hash
    candidate_json_sha256: Hash
    provenance_sha256: Hash
    manifest_sha256: Hash
    normalized_spec_sha256: Hash | None = None
    raw_yaml_digest_algorithm: Literal["sha256:raw-bytes:v1"] = "sha256:raw-bytes:v1"
    canonical_json_digest_algorithm: Literal["sha256:workflow-encoded-json:v1"] = "sha256:workflow-encoded-json:v1"
    normalized_spec_digest_algorithm: Literal["sha256:arena-model-json:workflow-encoded:v1"] = (
        "sha256:arena-model-json:workflow-encoded:v1"
    )
    validator_identity: str
    physical_validity: Literal["not_established"] = "not_established"
    task_validity: Literal["not_established"] = "not_established"


def validate_generation_candidate(artifacts, generation_receipt, *, protect):
    """Verify retained bytes and validate both representations without runtime execution."""
    if type(artifacts) is not GenerationArtifacts:
        raise ValueError("concrete generation artifacts required")
    files = artifacts.verified_bytes(generation_receipt, protect=protect)

    import yaml

    from isaaclab_arena.agentic_environment_generation.spec_wire_adapter import SpecWireAdapter
    from isaaclab_arena.agentic_environment_generation.workbench.document_yaml import parse_yaml, reject_unknown_fields
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    validator = ArenaEnvGraphSpec.from_dict
    failure = None
    normalized_digest = None
    try:
        documents = [
            parse_yaml(files["candidate.yaml"].decode("utf-8")),
            SpecWireAdapter.parse_json(files["candidate.json"].decode("utf-8")),
        ]
        pending = list(documents)
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if "external_yaml" in value:
                    failure = "external_yaml_refused"
                    break
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        if failure is None:
            # Compare Arena's canonical semantics, not source-byte identity (e.g. absent
            # and empty object_references both mean none). Retain both source digests.
            normalized = []
            for document in documents:
                reject_unknown_fields(document)
                normalized.append(encoded(validator(document).model_dump(mode="json")))
            if normalized[0] != normalized[1]:
                failure = "yaml_json_mismatch"
            else:
                normalized_digest = digest(normalized[0])
    except (ValueError, AssertionError, TypeError, RecursionError, yaml.YAMLError):
        failure = "invalid_schema"
    receipt = SchemaValidationReceipt(
        disposition="static_failure" if failure else "schema_validated",
        failure_code=failure,
        fence=generation_receipt.fence,
        contract_digest=generation_receipt.contract_digest,
        candidate_yaml_sha256=generation_receipt.candidate_yaml_sha256,
        candidate_json_sha256=generation_receipt.candidate_json_sha256,
        provenance_sha256=generation_receipt.provenance_sha256,
        manifest_sha256=generation_receipt.manifest_sha256,
        normalized_spec_sha256=normalized_digest,
        validator_identity=f"{validator.__module__}.{validator.__qualname__}",
    )
    value = receipt.model_dump(mode="json")
    before = encoded(value)
    protect(value)
    if encoded(value) != before:
        raise ValueError("validation protection must not mutate data")
    return receipt
