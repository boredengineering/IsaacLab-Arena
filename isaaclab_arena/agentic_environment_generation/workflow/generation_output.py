# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Existing generation-result contract, independent of jobs, GUI and process ownership."""

from ..prior_receipt import validate_prior_snapshot
from ..workbench.generation_diagnostics import GENERATION_STAGES


def validate_generation_output(inputs, result, *, validate_document):
    """Return a checked worker result with a fresh trusted document-validation result.

    Args:
        inputs: Frozen generation inputs, not a SQLite job or HTTP request.
        result: Decoded existing generation-worker result.
        validate_document: Trusted callable using the actual candidate schema.
    """
    fields = {
        "yaml_text",
        "validation",
        "traces",
        "publication",
        "warnings",
        "operation",
        "prior_snapshot",
        "catalogue_sha256",
    }
    if type(result) is not dict or set(result) != fields:
        raise ValueError("Invalid generation result fields")
    if result["operation"] != inputs["operation"] or result["publication"] != "not_published":
        raise ValueError("Invalid generation operation")
    if not isinstance(result["yaml_text"], str):
        raise ValueError("Invalid candidate text")
    validation = validate_document(result["yaml_text"])
    if not validation["valid"]:
        raise ValueError("Invalid candidate")
    if not isinstance(result["traces"], list) or any(stage not in GENERATION_STAGES for stage in result["traces"]):
        raise ValueError("Invalid generation traces")
    warnings = {
        "Not published to Neo4j. No simulation or policy evaluation was run.",
        "Agent did not converge on all physical/semantic checks; review the draft before use.",
    }
    if not isinstance(result["warnings"], list) or any(w not in warnings for w in result["warnings"]):
        raise ValueError("Invalid generation warnings")
    digest = result["catalogue_sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Invalid catalogue digest")
    expected = inputs.get("execution_catalogue_sha256")
    if type(expected) is not str or expected != digest:
        raise ValueError("Execution catalogue identity mismatch")
    snapshot = result["prior_snapshot"]
    if type(snapshot) is not dict:
        raise ValueError("Missing prior snapshot")
    status = snapshot.get("status")
    if result["operation"] == "new":
        if status == "not_requested":
            raise ValueError("New generation requires a retrieval outcome")
        if inputs.get("retrieval_policy") == "require_service" and status == "unavailable":
            raise ValueError("Required retrieval unavailable")
    elif status != "not_requested":
        raise ValueError("Refinement cannot claim retrieval")
    prompt = inputs.get("prompt", "") if result["operation"] == "new" else ""
    validate_prior_snapshot(snapshot, prompt=prompt)
    return {**result, "validation": validation}
