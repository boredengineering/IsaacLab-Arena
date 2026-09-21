# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Fixed typed HTTP queries from an explicit instance-bound private descriptor."""

import math
import re
import time
from pathlib import Path

from .installed_config import endpoint, text
from .private_files import decode, fields, read_private

DOCUMENTS = {
    "profiles": (
        "query Profiles { workflowProfiles { __typename ... on WorkflowProfileList { profiles { id revision kind roles"
        " settingsDigest bodyDigest model endpoint billing } } ... on QueryFailure { code } } }"
    ),
    "profile": (
        "query Profile($id: ID!, $revision: Revision!) { workflowProfile(id:$id, revision:$revision) { __typename ..."
        " on WorkflowProfile { id revision kind roles settingsDigest bodyDigest model endpoint billing } ... on"
        " NotFound { code } ... on QueryFailure { code } } }"
    ),
    "status": (
        "query Status($id: ID!) { workflow(id:$id) { __typename ... on Workflow { id operationId state phase version"
        " eventCounter retainedRevision responseRevision availableActions policyOutcome publicationOutcome } ... on"
        " NotFound { code } ... on QueryFailure { code } } }"
    ),
    "submission": (
        "query Submission($id: ID!) { workflowSubmission(operationId:$id) { __typename ... on SubmissionReceipt { kind"
        " operationId runId requestDigest acceptedContractDigest digestCodec admittedAt disposition provenance"
        " receiptVersion causeId } ... on NotFound { code } ... on QueryFailure { code } } }"
    ),
    "receipt": (
        "query Receipt($id: ID!, $kind: WorkflowCommandKind!) { workflowCommand(kind:$kind, operationId:$id) {"
        " __typename ... on SubmissionReceipt { kind operationId runId requestDigest disposition } ... on"
        " CancellationReceipt { kind operationId runId disposition receiptDigest beforeVersion afterVersion } ... on"
        " ResumeReceipt { kind operationId runId disposition receiptDigest beforeVersion afterVersion } ... on NotFound"
        " { code } ... on QueryFailure { code } } }"
    ),
    "runs": (
        "query Runs($first: Int!, $after: String) { workflows(first:$first, after:$after) { __typename ... on"
        " WorkflowConnection { semantics floor ceiling hasMore endCursor eventWatermark nodes { id operationId state"
        " phase version eventCounter } } ... on QueryFailure { code } } }"
    ),
    "events": (
        "query Events($first: Int!, $after: String) { workflowEvents(first:$first, after:$after) { __typename ... on"
        " WorkflowEventPage { floor ceiling hasMore resumeCursor events { schemaVersion sequence runId operationId kind"
        " sourceId commandKind commandOperationId } } ... on QueryFailure { code } } }"
    ),
}
MAX_RESPONSE = 8 * 1024 * 1024


def descriptor(path):
    from ..scope_binding import ScopeBinding
    from .instance import instance_id
    from .private_files import encode

    value = fields(
        decode(read_private(path, 16384), 16384),
        "schema_version endpoint instance generation binding principal expires_at bearer",
    )
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or type(value["generation"]) is not int
        or value["generation"] != 1
    ):
        raise ValueError("Unsupported client descriptor")
    selected = instance_id(value["instance"])
    if Path(path).name != "client.json" or Path(path).parent.name != selected:
        raise ValueError("Client instance differs")
    endpoint(value["endpoint"])
    ScopeBinding.model_validate_json(encode(value["binding"]))
    text(value["principal"], 128)
    expires = value["expires_at"]
    if type(expires) not in (int, float) or not math.isfinite(expires) or time.time() >= expires:
        raise ValueError("Client descriptor expired")
    if type(value["bearer"]) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value["bearer"]):
        raise ValueError("Invalid client authentication")
    return value


def query(path, operation, *, identifier=None, revision=None, kind=None, first=None, after=None):
    import httpx

    if operation not in DOCUMENTS:
        raise ValueError("Unsupported query")
    variables = {}
    if operation in {"profile", "status", "submission", "receipt"}:
        if type(identifier) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", identifier) is None:
            raise ValueError("Invalid query identity")
        variables["id"] = identifier
    if operation == "profile":
        if (
            type(revision) is not str
            or re.fullmatch(r"[1-9][0-9]{0,18}", revision) is None
            or int(revision) > 2**63 - 1
        ):
            raise ValueError("Invalid exact revision")
        variables["revision"] = revision
    if operation == "receipt":
        if kind not in {"SUBMIT", "CANCEL", "RESUME"}:
            raise ValueError("Invalid command kind")
        variables["kind"] = kind
    if operation in {"runs", "events"}:
        if type(first) is not int or not 1 <= first <= 1000:
            raise ValueError("Invalid page size")
        variables.update(first=first, after=None if after is None else text(after, 4096))
    auth = descriptor(path)
    deadline = time.monotonic() + 10
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=5, cookies=None) as client:
        with client.stream(
            "POST",
            auth["endpoint"],
            headers={"Authorization": "Bearer " + auth["bearer"], "Accept-Encoding": "identity"},
            json={"query": DOCUMENTS[operation], "variables": variables},
        ) as response:
            if (
                response.status_code != 200
                or response.headers.get("content-encoding") not in (None, "identity")
                or "set-cookie" in response.headers
            ):
                raise ValueError("Query rejected")
            raw = bytearray()
            for part in response.iter_raw():
                if len(raw) + len(part) > MAX_RESPONSE or time.monotonic() >= deadline:
                    raise ValueError("Query response unavailable")
                raw.extend(part)
    result = fields(decode(bytes(raw), MAX_RESPONSE), "data")
    if type(result["data"]) is not dict:
        raise ValueError("Query response unavailable")
    return result
