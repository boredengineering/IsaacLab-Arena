# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Fixed typed HTTP queries from an explicit instance-bound private descriptor."""

import math
import re
import time
from contextlib import contextmanager, suppress
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
SUBMISSION_SELECTION = (
    "__typename ... on SubmissionReceipt { kind operationId runId requestDigest acceptedContractDigest digestCodec "
    "admittedAt disposition provenance receiptVersion causeId } ... on NotFound { code } ... on QueryFailure { code }"
)
DOCUMENTS["submit"] = (
    "mutation Submit($id: ID!, $contract: WorkflowContractJSON!) { submitWorkflow(operationId:$id,"
    " contract:$contract) { "
    + SUBMISSION_SELECTION
    + " } }"
)
DOCUMENTS["cancel"] = (
    "mutation Cancel($id: ID!, $operation: ID!) { cancelWorkflow(runId:$id, operationId:$operation) { "
    "__typename ... on CancellationResult { durable cleanupStatus remoteEffects "
    "localStop { delivery remoteEffects durableCancellation } "
    "receipt { kind operationId runId disposition reason receiptDigest payloadDigest beforeVersion afterVersion } "
    "cleanup { currentScopeOwner { id epoch dirty } intents { intentId registrationId releaseState cleanupState "
    "cleanupObservation retiredOwner { id epoch dirty } } } } ... on QueryFailure { code } } }"
)
DOCUMENTS["resume"] = (
    "mutation Resume($operation:ID!,$id:ID!,$version:Revision!,$renew:Boolean!){"
    "resumeWorkflow(operationId:$operation,runId:$id,expectedVersion:$version,renewAuthorization:$renew){"
    "__typename ... on ResumeReceipt{kind operationId runId payloadDigest receiptDigest beforeVersion afterVersion "
    "expectedVersion renewAuthorization contractDigest disposition reason authorizationAction "
    "selection{version branch intentId contractDigest} events{sequence kind sourceId}} ... on QueryFailure{code}}}"
)
DOCUMENTS["result-status"] = (
    "query TerminalStatus($id: ID!) { workflow(id:$id) { __typename ... on Workflow { id operationId state "
    "cleanup { currentScopeOwner { id epoch dirty } intents { registrationId cleanupState retiredOwner { dirty } } } "
    "} ... on NotFound { code } ... on QueryFailure { code } } }"
)
DOCUMENTS["prior"] = (
    "query Prior($id:ID!){workflowPrior(runId:$id){__typename ... on PriorDetail {runId contractDigest manifestDigest"
    " status contextSha256 priorCount warnings artifacts {runId kind referenceId name sha256 totalBytes}} ... on"
    " NotFound {code} ... on QueryFailure {code}}}"
)
DOCUMENTS["artifact"] = (
    "query"
    " Artifact($id:ID!,$kind:ArtifactKind!,$reference:ID!,$name:ArtifactName!,$sha:String!,$offset:Counter!,$limit:Int!){workflowArtifact(runId:$id,kind:$kind,referenceId:$reference,name:$name,expectedSha256:$sha,offset:$offset,limit:$limit){__typename"
    " ... on ArtifactChunk {runId kind referenceId name sha256 totalBytes offset length eof encoding data}... on"
    " NotFound {code} ... on QueryFailure {code}}}"
)
DOCUMENTS["candidate"] = (
    "query Candidate($id:ID!,$reference:ID!){workflowCandidate(runId:$id,candidateId:$reference){__typename "
    "... on CandidateDetail {runId candidateId originalId parentId sourceId digest contractDigest "
    "artifacts {runId kind referenceId name sha256 totalBytes}} ... on NotFound {code} ... on QueryFailure {code}}}"
)
DOCUMENTS["generation"] = (
    "query Generation($id:ID!,$reference:ID!){workflowGeneration(runId:$id,attemptId:$reference){__typename "
    "... on GenerationDetail {runId intentId attemptId generation ownerId ownerEpoch registrationId contractDigest "
    "manifestDigest disposition artifacts {runId kind referenceId name sha256 totalBytes}} "
    "... on NotFound {code} ... on QueryFailure {code}}}"
)
DOCUMENTS["evidence"] = (
    "query Evidence($id:ID!,$reference:ID!){workflowEvidence(runId:$id,evidenceId:$reference){__typename ... on"
    " EvidenceDetail {runId evidenceId candidateId staticFailure verifiedManifestDigests freshArtifactVerification"
    " cohort{realizationId resetId environmentId windowId frameId contractDigest profileDigest} entries{criterionId"
    " criterionDigest producerId observedCoordinateFrames observedStepWindow subjectIds modality evaluatorVersion"
    " rubricId candidateDigest manifestDigest verdict limitations cohort{realizationId resetId environmentId windowId"
    " frameId contractDigest profileDigest}} artifactSelectors{kind referenceId manifestDigest}} ... on NotFound {code}"
    " ... on QueryFailure {code}}}"
)
DOCUMENTS["artifact-inventory"] = (
    "query"
    " Artifacts($id:ID!,$kind:ArtifactKind!,$reference:ID!){workflowArtifacts(runId:$id,kind:$kind,referenceId:$reference){__typename"
    " ... on ArtifactInventory {runId kind referenceId manifestDigest freshArtifactVerification artifacts{runId kind"
    " referenceId name sha256 totalBytes}} ... on NotFound {code} ... on QueryFailure {code}}}"
)
DOCUMENTS["assessment"] = (
    "query Assessment($id:ID!,$reference:ID!){workflowAssessment(runId:$id,assessmentId:$reference){__typename ... on"
    " AssessmentDetail {runId assessmentId candidateId evidenceId status missingIds failedIds historicalConflictIds"
    " limitations} ... on NotFound {code} ... on QueryFailure {code}}}"
)
DOCUMENTS["result"] = (
    "query Result($id: ID!, $operation: ID!) { workflow(id:$id) { "
    + "__typename ... on Workflow {  id operationId state phase version retainedRevision retainedDependenciesRevision "
    " policyOutcome publicationOutcome experimentOutcome  cleanup { projectionRevision currentScopeOwner { id epoch"
    " dirty }   intents { intentId kind registrationId releaseState cleanupState cleanupEvidenceRef"
    " cleanupObservation remoteEffects retiredOwner { id epoch dirty } } }  scene { acceptance assessmentStatus"
    " selectedAssessed action reason evidenceId assessmentId decisionId   selectedCandidateReference { candidateId"
    " digest sourceId originalId parentId }   criteria { criterionId requirement verdict reportedVerdicts manifests }"
    " }  budget { reserved { modelCalls modelTokens costCeilingUsd runtimeAllowanceSeconds candidates revisions"
    " realizations steps observations policyEpisodes policySteps }   actualConsumption accounting runtimeAccounting"
    " admittedAt deadline perOperationCeilingSeconds }  generationOutputs { intentId attemptId registrationId"
    " contractDigest candidateYamlSha256 candidateJsonSha256 provenanceSha256 manifestSha256 disposition"
    " freshArtifactVerification } } ... on NotFound { code } ... on QueryFailure { code } "
    + " } workflowSubmission(operationId:$operation) { "
    + SUBMISSION_SELECTION
    + " } workflowCommand(kind:SUBMIT, operationId:$operation) { "
    + SUBMISSION_SELECTION
    + " } }"
)


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


def query(
    path,
    operation,
    *,
    identifier=None,
    revision=None,
    kind=None,
    first=None,
    after=None,
    operation_id=None,
    raw_contract=None,
    expected_version=None,
    renew_authorization=None,
    reference_id=None,
    artifact_name=None,
    sha256=None,
    offset="0",
    limit=65536,
    deadline=None,
):
    import httpx

    if operation not in DOCUMENTS:
        raise ValueError("Unsupported query")
    variables = {}
    if operation in {
        "profile",
        "status",
        "submission",
        "receipt",
        "submit",
        "cancel",
        "resume",
        "result",
        "result-status",
        "prior",
        "artifact",
        "candidate",
        "generation",
        "evidence",
        "artifact-inventory",
        "assessment",
    }:
        if type(identifier) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", identifier) is None:
            raise ValueError("Invalid query identity")
        variables["id"] = identifier
    if operation in {"profile", "resume"}:
        revision = expected_version if operation == "resume" else revision
        if (
            type(revision) is not str
            or re.fullmatch(r"[1-9][0-9]{0,18}", revision) is None
            or int(revision) > 2**63 - 1
        ):
            raise ValueError("Invalid exact revision")
        variables["version" if operation == "resume" else "revision"] = revision
    if operation == "resume":
        if type(renew_authorization) is not bool:
            raise ValueError("Explicit renewal choice required")
        variables["renew"] = renew_authorization
    if operation == "receipt":
        if kind not in {"SUBMIT", "CANCEL", "RESUME"}:
            raise ValueError("Invalid command kind")
        variables["kind"] = kind
    if operation == "artifact":
        if (
            (kind, artifact_name)
            not in {
                ("PRIOR", "PRIOR_JSON"),
                ("CANDIDATE", "CANDIDATE_JSON"),
                ("GENERATION", "CANDIDATE_JSON"),
                ("GENERATION", "CANDIDATE_YAML"),
                ("GENERATION", "PROVENANCE_JSON"),
                ("EVIDENCE", "EVIDENCE_JSON"),
            }
            or type(reference_id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", reference_id) is None
            or type(sha256) is not str
            or re.fullmatch(r"[a-f0-9]{64}", sha256) is None
            or type(offset) is not str
            or re.fullmatch(r"0|[1-9][0-9]{0,18}", offset) is None
            or int(offset) > 2**63 - 1
            or type(limit) is not int
            or not 1 <= limit <= 65536
        ):
            raise ValueError("Invalid bounded artifact reference")
        variables.update(kind=kind, reference=reference_id, name=artifact_name, sha=sha256, offset=offset, limit=limit)
    if operation in {"candidate", "generation", "evidence", "artifact-inventory", "assessment"}:
        if type(reference_id) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", reference_id) is None:
            raise ValueError("Invalid retained reference")
        variables["reference"] = reference_id
    if operation == "artifact-inventory":
        if kind not in {"PRIOR", "CANDIDATE", "GENERATION", "EVIDENCE"}:
            raise ValueError("Invalid artifact kind")
        variables["kind"] = kind
    if operation in {"runs", "events"}:
        if type(first) is not int or not 1 <= first <= 1000:
            raise ValueError("Invalid page size")
        variables.update(first=first, after=None if after is None else text(after, 4096))
    if operation == "submit":
        from ..contracts import canonical_json, parse_contract

        variables["contract"] = canonical_json(parse_contract(raw_contract))
    if operation in {"cancel", "resume", "result"}:
        if type(operation_id) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", operation_id) is None:
            raise ValueError("Invalid operation identity")
        variables["operation"] = operation_id
    auth = descriptor(path)
    supplied_deadline = deadline is not None
    now = time.monotonic()
    if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
        raise ValueError("Invalid query deadline")
    deadline = now + 10 if deadline is None else min(deadline, now + 10)
    if deadline <= now:
        raise TimeoutError("Query deadline expired")
    bounded = operation in {"submit", "cancel", "resume", "result"} or supplied_deadline
    with _transport_deadline(deadline, enabled=bounded) as trace:
        with httpx.Client(
            trust_env=False, follow_redirects=False, timeout=min(5, deadline - now), cookies=None
        ) as client:
            with client.stream(
                "POST",
                auth["endpoint"],
                headers={"Authorization": "Bearer " + auth["bearer"], "Accept-Encoding": "identity"},
                json={"query": DOCUMENTS[operation], "variables": variables},
                **({"extensions": {"trace": trace}} if bounded else {}),
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
                if bounded and time.monotonic() >= deadline:
                    raise TimeoutError("Query deadline expired")
    result = fields(decode(bytes(raw), MAX_RESPONSE), "data")
    if type(result["data"]) is not dict:
        raise ValueError("Query response unavailable")
    return result


@contextmanager
def _transport_deadline(deadline, *, enabled):
    """Close only this call's socket at its overall deadline, including headers."""
    if not enabled:
        yield None
        return
    import socket
    import threading

    lock = threading.Lock()
    sockets = []
    expired = False

    def shutdown(sock):
        with suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)

    def expire():
        nonlocal expired
        with lock:
            expired = True
            for sock in sockets:
                shutdown(sock)

    def trace(name, info):
        if name == "connection.connect_tcp.complete":
            stream = info["return_value"]
            sock = stream.get_extra_info("socket")
            if sock is None:
                raise ValueError("Bounded HTTP stream unavailable")
            with lock:
                if expired or time.monotonic() >= deadline:
                    shutdown(sock)
                    raise TimeoutError("Query deadline expired")
                sockets.append(sock)

    timer = threading.Timer(max(0, deadline - time.monotonic()), expire)
    timer.start()
    try:
        yield trace
        if not sockets or time.monotonic() >= deadline:
            raise TimeoutError("Bounded HTTP response unavailable")
    finally:
        timer.cancel()
        timer.join()


def result(path, run_id, *, operation_id, wait_terminal_seconds):
    """Poll at most 120 times, then read one exact combined retained projection."""
    if type(wait_terminal_seconds) is not int or not 1 <= wait_terminal_seconds <= 120:
        raise ValueError("Bounded terminal wait required")
    deadline = time.monotonic() + wait_terminal_seconds
    for _ in range(120):
        observed = query(path, "result-status", identifier=run_id, deadline=deadline)
        row = observed["data"].get("workflow", {})
        if row.get("__typename") != "Workflow" or row.get("id") != run_id or row.get("operationId") != operation_id:
            raise ValueError("Exact workflow unavailable")
        cleanup = row.get("cleanup", {})
        current = cleanup.get("currentScopeOwner", {})
        clean = (current is None or current.get("dirty") is False) and all(
            intent.get("registrationId") is None
            or (
                intent.get("cleanupState") == "recorded"
                and intent.get("retiredOwner") is not None
                and intent["retiredOwner"].get("dirty") is False
            )
            for intent in cleanup.get("intents", [])
        )
        if row.get("state") in {"accepted", "stopped", "cancelled"} and clean:
            value = query(path, "result", identifier=run_id, operation_id=operation_id, deadline=deadline)
            data = value["data"]
            if set(data) != {"workflow", "workflowSubmission", "workflowCommand"}:
                raise ValueError("Exact result unavailable")
            for name in ("workflowSubmission", "workflowCommand"):
                receipt = data[name]
                if (
                    receipt.get("__typename") != "SubmissionReceipt"
                    or receipt.get("runId") != run_id
                    or receipt.get("operationId") != operation_id
                    or receipt.get("kind") != "SUBMIT"
                ):
                    raise ValueError("Exact submission unavailable")
            final = data["workflow"]
            if (
                final.get("__typename") != "Workflow"
                or final.get("id") != run_id
                or final.get("operationId") != operation_id
                or final.get("state") not in {"accepted", "stopped", "cancelled"}
            ):
                raise ValueError("Exact terminal result unavailable")
            if data["workflowSubmission"] != data["workflowCommand"]:
                raise ValueError("Submission projections differ")
            return value
        # Pace from completed observation, not a pre-call timestamp whose
        # variable entry overhead can put successive requests less than 1 s apart.
        if time.monotonic() + 1 >= deadline:
            break
        time.sleep(1.0)
    raise TimeoutError("Terminal result unavailable")
