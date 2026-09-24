# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""One installed HTTP admission/owner/SDK/readback witness; never a fake owner."""

import json
import os
import time
from pathlib import Path


def _detachment_proof_negatives():
    """Pure checker regressions; no clocks, children, SDK or transport effects."""
    from copy import deepcopy

    from workflow_graphql_execution_join_fixture import check_detachment_proof

    identity = dict(pid=41, parent_pid=40, pgid=41, sid=41, boot="boot", pid_namespace="pid:[1]", start_ticks=7)
    server = dict(identity, pid=40, parent_pid=38, pgid=40, sid=40, start_ticks=6)
    detached = dict(
        submit_pid=39,
        server_identity=server,
        worker_identity=identity,
        server_live=dict(server, parent_pid=1, state="S"),
        worker_live=dict(identity, state="S"),
        submit_reaped_before_release=True,
        observed_at=12.0,
        release_requested_at=13.0,
    )
    release = dict(
        identity=identity, calls=2, phase="released", outcome="marker_removed",
        waiting_at=10.0, deadline=30.0, released_at=14.0,
        response_ready=True, response_returning=True,
    )
    check_detachment_proof(detached, release)
    mutations = (
        ("timeout_after_descheduling", "release", {"outcome": "timeout", "released_at": 31.0}, "explicit removal"),
        ("late_removal", "release", {"released_at": 31.0}, "release ordering"),
        ("missing_response", "release", {"response_returning": False}, "transport response"),
        ("submit_not_reaped", "detached", {"submit_reaped_before_release": False}, "submit reap"),
        ("zombie_worker", "worker_live", {"state": "Z"}, "live identity"),
        ("dead_server", "server_live", {"state": "X"}, "live identity"),
        ("reused_worker_pid", "worker_live", {"start_ticks": 8}, "live identity"),
        ("reused_server_pid", "server_live", {"start_ticks": 8}, "live identity"),
        ("foreign_namespace", "worker_live", {"pid_namespace": "pid:[2]"}, "live identity"),
        ("foreign_release", "release_identity", {"start_ticks": 8}, "release identity"),
    )
    checked = []
    for name, target, update, message in mutations:
        observed, returned = deepcopy(detached), deepcopy(release)
        destination = {
            "release": returned, "detached": observed,
            "worker_live": observed["worker_live"], "server_live": observed["server_live"],
            "release_identity": returned["identity"],
        }[target]
        destination.update(update)
        try:
            check_detachment_proof(observed, returned)
        except AssertionError as error:
            assert message in str(error), (name, str(error))
            checked.append(name)
        else:
            raise AssertionError(f"detachment checker accepted {name}")
    return checked


def verify_query_only_boundaries(metadata):
    """Real scoped Neo4j and ASGI reads with no execution factory or model credentials."""
    import asyncio
    import base64
    import hashlib
    import httpx
    import workflow_graphql_execution_join_harness as h
    from isaaclab_arena.agentic_environment_generation.workflow.api.application import Composition, Settings, create_app
    from isaaclab_arena.agentic_environment_generation.workflow.api.client import DOCUMENTS
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_composition import Resources
    from isaaclab_arena.agentic_environment_generation.workflow.api.installed_config import load
    from isaaclab_arena.agentic_environment_generation.workflow.api.security import TokenRegistry
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import parse_contract, contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import canonical

    config = load(h.CONFIG)
    resources = Resources(config)
    with resources.driver() as driver:
        before = resources.store(driver).get_run(h.RUN_ID)
    request = parse_contract(before.contract_json)
    binding = RetainedPriorArtifacts._binding(request.source.prompt, contract_digest(request), h.RUN_ID)
    version = hashlib.sha256(canonical(binding)).hexdigest()
    prior_path = Path(config.value["artifact_root"]) / "final" / "scene-prior" / version / "prior.json"
    original = prior_path.read_bytes()
    assert hashlib.sha256(original).hexdigest() == metadata["prior"]["artifacts"][0]["sha256"]
    registry = TokenRegistry(binding=config.binding, instance="p1-read-only", generation=1, clock=time.monotonic)
    principal = resources.authority.reader
    good = registry.issue(principal=principal, lifetime=120)
    wrong = registry.issue(principal="p1-wrong-principal", lifetime=120)
    stale = registry.issue(principal=principal, lifetime=120)
    registry.revoke(registry.authenticate(("Bearer " + stale).encode()))
    foreign = TokenRegistry(
        binding=config.binding.model_copy(update={"workspace_id": "p1-other-workspace"}),
        instance="p1-other-scope",
        generation=1,
        clock=time.monotonic,
    )
    foreign_token = foreign.issue(principal=principal, lifetime=120)
    composition = Composition(
        resources.driver,
        resources.store,
        resources.authority,
        resources.authority.admin,
        principal,
        resources.protect,
        registry,
    )
    assert composition.execution_factory is None
    app = create_app(
        settings=Settings(config.binding, Path(config.value["artifact_root"]), config.profiles), composition=composition
    )
    reference = metadata["prior"]["artifacts"][0]
    artifact_variables = dict(
        id=h.RUN_ID,
        kind="PRIOR",
        reference=h.RUN_ID,
        name="PRIOR_JSON",
        sha=reference["sha256"],
        offset="0",
        limit=65536,
    )
    outcomes = {}

    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://isolated", trust_env=False
            ) as client:

                async def post(label, operation, variables, *, credential=good, status=200, field=None, typename=None):
                    response = await client.post(
                        "/graphql",
                        json={"query": DOCUMENTS[operation], "variables": variables},
                        headers={"Authorization": "Bearer " + credential},
                    )
                    assert response.status_code == status, "Unexpected bounded read response"
                    value = response.json()
                    selected = None if field is None else value["data"][field]
                    if typename is not None:
                        assert selected["__typename"] == typename, "Unexpected typed read outcome"
                    outcomes[label] = dict(
                        http_status=response.status_code,
                        typename=None if selected is None else selected.get("__typename"),
                        code=None if selected is None else selected.get("code"),
                    )
                    return selected

                prior = await post(
                    "read_only_prior", "prior", {"id": h.RUN_ID}, field="workflowPrior", typename="PriorDetail"
                )
                assert prior == metadata["prior"]
                for operation, field, reference_id, expected in (
                    ("candidate", "workflowCandidate", metadata["candidate"]["candidateId"], metadata["candidate"]),
                    ("generation", "workflowGeneration", metadata["generation"]["attemptId"], metadata["generation"]),
                    ("evidence", "workflowEvidence", metadata["evidence"]["evidenceId"], metadata["evidence"]),
                    (
                        "assessment",
                        "workflowAssessment",
                        metadata["assessment"]["assessmentId"],
                        metadata["assessment"],
                    ),
                ):
                    value = await post(
                        "read_only_" + operation,
                        operation,
                        {"id": h.RUN_ID, "reference": reference_id},
                        field=field,
                        typename=expected["__typename"],
                    )
                    assert value == expected
                chunk = await post(
                    "read_only_artifact",
                    "artifact",
                    artifact_variables,
                    field="workflowArtifact",
                    typename="ArtifactChunk",
                )
                assert base64.b64decode(chunk["data"], validate=True) == original
                await post(
                    "read_only_receipt",
                    "receipt",
                    {"kind": "SUBMIT", "id": h.OPERATION},
                    field="workflowCommand",
                    typename="SubmissionReceipt",
                )
                denied = await post(
                    "wrong_principal",
                    "prior",
                    {"id": h.RUN_ID},
                    credential=wrong,
                    field="workflowPrior",
                    typename="QueryFailure",
                )
                assert denied["code"] == "FORBIDDEN"
                await post("wrong_scope_token", "artifact", artifact_variables, credential=foreign_token, status=401)
                await post("stale_authority", "artifact", artifact_variables, credential=stale, status=401)
                await post(
                    "cross_run_candidate",
                    "candidate",
                    {"id": "p1-other-run", "reference": metadata["candidate"]["candidateId"]},
                    field="workflowCandidate",
                    typename="NotFound",
                )
                await post(
                    "cross_run_evidence",
                    "evidence",
                    {"id": "p1-other-run", "reference": metadata["evidence"]["evidenceId"]},
                    field="workflowEvidence",
                    typename="QueryFailure",
                )
                await post(
                    "oversized_chunk",
                    "artifact",
                    dict(artifact_variables, limit=65537),
                    field="workflowArtifact",
                    typename="QueryFailure",
                )
                await post("arbitrary_path", "artifact", dict(artifact_variables, name="../../private"), status=400)
                await post(
                    "read_only_mutation",
                    "resume",
                    {"id": h.RUN_ID, "operation": "p1-denied-mutation", "version": "1", "renew": True},
                    status=400,
                )
                try:
                    prior_path.write_bytes(original + b"\n")
                    await post(
                        "tampered_artifact",
                        "artifact",
                        artifact_variables,
                        field="workflowArtifact",
                        typename="QueryFailure",
                    )
                finally:
                    prior_path.write_bytes(original)
                restored = await post(
                    "restored_artifact",
                    "artifact",
                    artifact_variables,
                    field="workflowArtifact",
                    typename="ArtifactChunk",
                )
                assert base64.b64decode(restored["data"], validate=True) == original
                registry.rotate()
                await post("stale_generation", "prior", {"id": h.RUN_ID}, status=401)

    asyncio.run(scenario())
    assert hashlib.sha256(prior_path.read_bytes()).hexdigest() == reference["sha256"]
    with resources.driver() as driver:
        after = resources.store(driver).get_run(h.RUN_ID)
    assert after == before, "Read-only acceptance changed operational state or budgets"
    h.write_evidence(
        "join-api-negatives.json",
        {
            "composition": "query-only",
            "execution_factory": None,
            "outcomes": outcomes,
            "retained_run_unchanged": True,
            "artifact_restored": True,
        },
    )


def test_installed_execution_survives_submit_exit():
    """Reach production composition first, then require the whole retained join."""
    import workflow_graphql_execution_join_harness as h
    from workflow_graphql_execution_join_fixture import (
        IDENTITY_FIELDS,
        PAUSE,
        PAUSE_BYTES,
        configuration,
        contract,
        registrations,
    )

    records = []
    proof_negative_checks = []
    launched = False
    pause = PAUSE

    def invoke(arguments, *, private_fd=None):
        result = h.fresh(arguments, private_fd=private_fd)
        h.screen(result.stdout + result.stderr)
        records.append({
            "argv": arguments,
            "pid": result.pid,
            "returncode": result.returncode,
            "stdout": result.stdout.decode(),
            "stderr": result.stderr.decode(),
        })
        return result

    try:
        proof_negative_checks = _detachment_proof_negatives()
        profiles = registrations()
        for kind, config_path in zip(("query", "execution"), h.CONFIGS, strict=True):
            configuration(kind, profiles if kind == "execution" else ())
            raw = json.dumps({
                "schema_version": 1,
                "databases": {
                    "operational": {
                        "scheme": "basic",
                        "username": "synthetic-user",
                        "password": "synthetic-only-secret",
                    }
                },
            }).encode()
            read_fd, write_fd = os.pipe()
            try:
                os.fchmod(read_fd, 0o600)
                assert os.write(write_fd, raw) == len(raw)
            finally:
                os.close(write_fd)
            try:
                result = invoke(
                    ["setup", "--config", config_path, "--create", "--credentials-fd", str(read_fd)],
                    private_fd=read_fd,
                )
            finally:
                os.close(read_fd)
            assert result.returncode == 0, "E1 prerequisite setup failed; not joined application RED"
            assert json.loads(result.stdout)["code"] == "setup_complete"
        raw_contract = contract(profiles)
        path = Path(h.CONTRACT)
        path.write_text(raw_contract)
        path.chmod(0o600)
        for arguments in h.ADMIN:
            result = invoke(arguments)
            assert result.returncode == 0, "E1 explicit administration failed; not joined application RED"
            assert json.loads(result.stdout)["code"] == "admin_complete"

        result = invoke(h.LAUNCH)
        # First application acceptance assertion. This is an actual installed
        # api-launch -> api-serve attempt, not a source-inspection placeholder.
        assert result.returncode == 0, "Production installed synthetic owner composition is missing or refused"
        launched = True
        ready = json.loads(result.stdout)
        assert ready["state"] == "ready"
        # Proposed execution capability projection. Query-only readiness is not
        # accepted as an execution witness, even if a descriptor exists.
        capabilities = ready.get("capabilities", {})
        assert (
            capabilities.get("mode") == "isolated-synthetic-execution-v1"
        ), "Production installed execution composition/capabilities are absent; query readiness is not execution"
        assert capabilities.get("submit") is True
        assert capabilities.get("required_policy") is False
        server_pid = h.server_pid()
        pause.parent.mkdir(mode=0o700)
        pause.write_bytes(PAUSE_BYTES)
        pause.chmod(0o600)
        result = invoke(h.SUBMIT)
        assert result.returncode == 0, "Production installed submit command/transport is missing or refused"
        admitted = json.loads(result.stdout)
        assert admitted["data"]["submitWorkflow"]["runId"] == h.RUN_ID
        assert admitted["data"]["submitWorkflow"]["operationId"] == h.OPERATION
        assert not Path(f"/proc/{result.pid}").exists(), "submit was not reaped"
        if h.JOIN_CASE == "resume":
            h.interrupt_unreleased_server(server_pid)
            launched = False
            result = invoke(h.RECONCILE)
            assert result.returncode == 3 and json.loads(result.stdout)["state"] == "exited_unclean"
            result = invoke(h.RELAUNCH)
            assert result.returncode == 0 and json.loads(result.stdout)["state"] == "ready"
            launched = True
            server_pid = h.server_pid()
            lost = invoke(h.LOST_RESPONSE)
            assert lost.returncode == 2, "Lost response body was not exercised"
            original_resume = h.snapshot_resume_receipt()
            result = invoke(h.resume_arguments())
            assert result.returncode == 0, "Installed reauthorized resume unavailable"
            assert (
                json.loads(result.stdout)["data"]["resumeWorkflow"]["receiptDigest"] == original_resume.receipt_digest
            )
            h.verify_resume_admission(json.loads(result.stdout))
        deadline = min(h.ACTIVE.deadline, time.monotonic() + 15)
        while not list(Path("/evidence").glob("generation-child-*-active.json")):
            assert time.monotonic() < deadline, "actual generation SDK barrier not reached"
            time.sleep(0.02)
        active_paths = list(Path("/evidence").glob("generation-child-*-active.json"))
        assert len(active_paths) == 1
        active = h.read_json(active_paths[0])
        worker_pid = active["identity"]["pid"]
        assert active["calls"] == 2 and active["phase"] == "waiting" and active["outcome"] is None
        assert active["response_ready"] is True and active["response_returning"] is False
        witness = h.read_json(Path(f"/evidence/join-process-{worker_pid}-started.json"))
        assert witness["parent_pid"] == server_pid and witness["role"] == "model"
        assert witness["preimport"]["before_package_imports"] is True
        worker_identity = {key: witness[key] for key in IDENTITY_FIELDS}
        assert active["identity"] == worker_identity
        server = h.read_json(Path(f"/evidence/join-process-{server_pid}-started.json"))
        assert server["role"] == "server"
        server_identity = {key: server[key] for key in IDENTITY_FIELDS}
        worker_live = h.live_identity(worker_identity)
        server_live = h.live_identity(server_identity)
        if h.JOIN_CASE == "resume":
            controls = invoke(h.CONTROL_CHECK)
            assert controls.returncode == 0, "Installed resume replay/control negatives failed"
            h.verify_control_results(json.loads(controls.stdout))
        observed_at = time.monotonic()
        assert pause.read_bytes() == PAUSE_BYTES
        h.write_evidence(
            "join-detached.json",
            {
                "submit_pid": result.pid,
                "server_identity": server_identity,
                "worker_identity": worker_identity,
                "worker_live": worker_live,
                "server_live": server_live,
                "submit_reaped_before_release": True,
                "observed_at": observed_at,
                "release_requested_at": time.monotonic(),
            },
        )
        if h.JOIN_CASE == "cancel":
            result = invoke(h.CANCEL)
            assert result.returncode == 0, "Installed keyed cancellation unavailable"
            cancellation = json.loads(result.stdout)
            assert (
                pause.read_bytes() == PAUSE_BYTES
            ), "Cancellation must stop the active worker, not release the barrier"
            result = invoke(h.RESULT)
            assert result.returncode == 0, "Cancelled result/cleanup unavailable through HTTP"
            h.verify_cancel_result(json.loads(result.stdout), cancellation, worker_identity)
            controls = invoke(h.CONTROL_CHECK)
            assert controls.returncode == 0, "Installed terminal cancellation/replay controls failed"
            h.verify_control_results(json.loads(controls.stdout))
        else:
            pause.unlink()
            result = invoke(h.RESULT)
            assert result.returncode == 0, "Production exact-result HTTP reader missing or incomplete"
            h.verify_result(json.loads(result.stdout), raw_contract)
            if h.JOIN_CASE in {"evidence", "resume"}:
                result = invoke(h.READBACK)
                assert result.returncode == 0, "Authenticated retained bytes unavailable to a fresh HTTP client"
                readback_value = json.loads(result.stdout)
                h.verify_api_readback(readback_value)
                if h.JOIN_CASE == "evidence":
                    verify_query_only_boundaries(readback_value)
        result = invoke(h.STOP)
        assert result.returncode == 0 and json.loads(result.stdout)["state"] == "stopped"
        launched = False
        result = invoke(h.STATUS)
        assert result.returncode == 0 and json.loads(result.stdout)["state"] == "stopped"
        h.verify_positive()
    finally:
        if pause.exists():
            pause.unlink()
        # Only the fixed stop/status roles; never restart, retry submit or create
        # authority from a receipt. Cleanup failure must remain visible.
        if launched:
            for arguments in (h.STOP, h.STATUS):
                if h.unused(arguments):
                    invoke(arguments)
        h.write_evidence("join-case.json", {
            "processes": records,
            "positive_complete": h.ACTIVE.positive_complete,
            "proof_negative_checks": proof_negative_checks,
        })
