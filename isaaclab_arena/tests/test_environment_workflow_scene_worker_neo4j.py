# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Real scene child and committed Neo4j fences; synthetic initial scene/evidence/HTTP.

The fixed HTTP fixture proposes a schema-valid but unauthorized scene: the real
repair guard must reject it, not turn SDK success into acceptance. Native and research off.
"""

import json
import os
import time
import uuid
from pathlib import Path

import pytest
from neo4j import GraphDatabase

from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts
from isaaclab_arena.agentic_environment_generation.workflow.attempts import GenerationReservation, WorkerRegistration
from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore
from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence
from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import ScenePortProfile, SceneResult
from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
from isaaclab_arena.agentic_environment_generation.workflow.validation import validate_generation_candidate
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.tests.test_environment_workflow_decisions import authority, gate_readiness
from isaaclab_arena.tests.test_environment_workflow_scene_engines import configuration
from isaaclab_arena.tests.test_environment_workflow_scene_loop import observation, scene_contract
from isaaclab_arena.tests.utils.agentic_environment_generation import minimal_spec_dict
from isaaclab_arena_examples.agentic_environment_generation.foreground_scene import ForegroundSceneWorker
from isaaclab_arena_examples.agentic_environment_generation.web_api.scene_worker import retain_request


def _check_keyed_recovery_inert_ports(mode):
    """Actual recovery code, inert cleanup/artifact ports; no additional child."""
    import inspect
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.commands import (
        ResumeSelection,
        command_digest,
        command_json,
        make_resume_receipt,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
    from isaaclab_arena.tests.test_environment_workflow_service import contract, coordinator_fixture
    from isaaclab_arena_examples.agentic_environment_generation.foreground_recovery import ForegroundGenerationRecovery

    assert "resume_receipt" in inspect.signature(ForegroundGenerationRecovery.recover).parameters
    f = coordinator_fixture()
    fence, registration = f.prepared.registration.fence, f.prepared.registration
    run = f.store.get_run("run")
    run.version, run.state = (3 if mode == "stale" else 2), "running"
    run.phase = "validation" if mode in {"settled", "historical"} else "generation"
    cleanup = CleanupEvidence(
        registration=registration,
        evidence_ref="inert-cleanup",
        observation="owned_process_group_stopped",
        remote_effects="unknown",
    )
    output = object()
    attempt = SimpleNamespace(
        fence=fence,
        registration=registration,
        contract_json=run.contract_json,
        authorization=SimpleNamespace(principal="creator"),
        cleanup=cleanup if mode in {"settled", "historical"} else None,
        receipt=output if mode in {"settled", "historical"} else None,
    )
    owner = SimpleNamespace(
        owner_id="replacement" if mode == "historical" else fence.owner_id, owner_epoch=fence.owner_epoch, dirty=True
    )
    pins, effects = [], []

    def exact(expected):
        pins.append(expected)
        assert expected == fence
        return attempt

    def ack(expected, value):
        assert expected == fence and value.registration == registration
        effects.append("cleanup_ack")
        attempt.cleanup = value
        run.version += 1

    store = SimpleNamespace(
        get_run=lambda r: run,
        get_attempt=exact,
        get_owner=lambda: owner,
        get_generation_attempt=lambda r: pytest.fail("reselection forbidden"),
        get_retired_owner=lambda o: SimpleNamespace(
            owner_id=fence.owner_id, owner_epoch=fence.owner_epoch, dirty=False
        ),
        acknowledge_cleanup=ack,
    )
    service = WorkflowService(store, f.coordinator._authority, None, validate_support=None)
    service.prepare_generation_adoption = lambda *a, **kw: output

    def adopt(*args, **kw):
        attempt.receipt = output
        run.phase = "validation"
        run.version += 1
        effects.append("adopt")

    service.adopt_generation = adopt
    recovery = ForegroundGenerationRecovery.__new__(ForegroundGenerationRecovery)
    recovery._service, recovery._principal, recovery._run_id = service, "creator", "run"
    recovery._protect = lambda v: None
    recovery._ownership = SimpleNamespace(load=lambda r: effects.append("ownership"))
    recovery._group = SimpleNamespace(stop=lambda **kw: effects.append("stop"), cleaned=True)
    recovery._observed = None
    if mode == "cached_mismatch":
        recovery._resume_binding = (fence.model_copy(update={"owner_epoch": 2}), registration)
    recovery._artifacts = SimpleNamespace(load_receipt=lambda *a, **kw: output)
    recovery.lease = SimpleNamespace(
        require_held=lambda *a: None,
        mark_recovery=lambda f: effects.append("mark"),
        retire_and_release=lambda *a: effects.append("retire"),
        release_never_prepared=lambda: effects.append("historical_release"),
        release_after_cleanup=lambda *a: effects.append("release"),
    )
    selection = ResumeSelection(
        run_id="run",
        version=1,
        contract_digest=contract_digest(contract()),
        branch="reconciliation",
        intent_id=fence.intent_id,
        fence=fence,
    )
    text = command_json(dict(runId="run", expectedVersion=1, renewAuthorization=False))
    receipt = make_resume_receipt(
        scope=dict(database="neo4j", deployment_id="dep", workspace_id="ws"),
        operation_id="recover",
        run_id="run",
        payload_json=text,
        payload_digest=command_digest(text),
        before_version=1,
        after_version=2,
        selection=selection.model_dump(mode="json"),
        contract_digest=selection.contract_digest,
        disposition="reconciliation_admitted",
        reason=None,
        authorization_action=None,
        events=[dict(sequence=2, kind="ResumeAdmitted", source_id=fence.intent_id)],
    )
    if mode in {"stale", "cached_mismatch"}:
        with pytest.raises(ValueError, match="Resume recovery (selection|binding) changed"):
            recovery.recover(resume_receipt=receipt)
        assert effects == []
    else:
        result = recovery.recover(resume_receipt=receipt)
        assert result.disposition == "validation" and result.attempt.fence == fence
        assert len(pins) >= 2
    assert "execute_auth" not in f.calls
    return SimpleNamespace(service=service, run=run, receipt=receipt, fence=fence)


def _check_keyed_recovery_real_unlatched_lease(tmp_path, mode):
    """Real constructor/flock, inert retained store; no worker or owner retirement."""
    import fcntl

    from isaaclab_arena.agentic_environment_generation.workflow.application import ForegroundWorkflow
    from isaaclab_arena_examples.agentic_environment_generation.foreground_recovery import (
        ForegroundGenerationRecovery,
        OwnershipArtifacts,
    )

    t = _check_keyed_recovery_inert_ports("stale")
    t.run.version, t.run.state = 2, "running"
    app = ForegroundWorkflow.__new__(ForegroundWorkflow)
    app.service, app._recoveries = t.service, {}
    root = tmp_path / mode
    root.mkdir(mode=0o700)
    private = root / "owner"
    private.mkdir(mode=0o700)
    app.private_parent = private
    app.authority = t.service._authority
    app.authority.protect_public = lambda value: None
    created, release_attempts = [], []

    with ArtifactArea.create(root / "artifacts", store_id="recovery", registry_id="recovery") as area:
        app.ownership = OwnershipArtifacts(area)
        app.artifacts = GenerationArtifacts(area)

        def unavailable(*a, **kw):
            raise ValueError("inert ownership unavailable after latch")

        # An exact concrete object with an inert artifact read fails only AFTER
        # the real recovery latch. No process-group construction is reached.
        app.ownership.load = unavailable

        def construct(*args, **kwargs):
            recovery = ForegroundGenerationRecovery(*args, **kwargs)
            created.append(recovery)
            original_release = recovery.lease.release_never_prepared

            def release():
                release_attempts.append(mode)
                if mode == "release_fault":
                    raise OSError("inert unlock uncertainty")
                return original_release()

            recovery.lease.release_never_prepared = release
            if mode == "prepared":
                recovery.lease.mark_prepared(object())
            if mode != "latched":
                # Cancellation changes the pin AFTER the actual constructor
                # acquires flock and BEFORE recover's first retained read.
                t.run.version, t.run.state = 3, "cancelled"
            return recovery

        app._recovery_factory = construct
        if mode == "cached":
            recovery = construct(
                private,
                run_id="run",
                principal="creator",
                service=t.service,
                ownership_artifacts=app.ownership,
                artifacts=app.artifacts,
                protect=app.authority.protect_public,
            )
            app._recoveries["run"] = recovery
            t.run.version, t.run.state = 2, "running"
            original_recover = recovery.recover

            def stale_cached(**kwargs):
                t.run.version, t.run.state = 3, "cancelled"
                return original_recover(**kwargs)

            recovery.recover = stale_cached

        try:
            with pytest.raises(
                ValueError, match=("inert ownership" if mode == "latched" else "Resume recovery selection changed")
            ):
                app._resume_reconcile("creator", t.receipt, None)
            assert len(created) == 1
            recovery = created[0]
            assert recovery._observed is None and recovery._group is None
            # Independent descriptor, actual kernel flock; cache observations
            # alone cannot establish scope availability or retained ownership.
            with (private / "foreground.lock").open("r+b") as contender:
                try:
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    blocked = True
                else:
                    blocked = False
                    fcntl.flock(contender, fcntl.LOCK_UN)
            if mode == "fresh":
                assert not blocked, "new never-latched recovery leaked actual scope flock"
                assert "run" not in app._recoveries, "new never-latched recovery retained in cache"
                assert recovery.lease._released is True
                assert release_attempts == [mode]
            else:
                assert blocked, "uncertain/cached recovery lost actual scope flock"
                assert app._recoveries["run"] is recovery, "uncertain/cached recovery must remain retained"
                assert recovery.lease._released is False
                recovery.lease.require_held("run", "creator")
                if mode == "cached":
                    assert release_attempts == [], "cached lease is not newly acquired by this delivery"
            assert t.receipt.after_version == 2 and t.receipt.disposition == "reconciliation_admitted"
        finally:
            # Fixture disposal only: no worker was ever created. Do not forge
            # durable retirement or a cleanup receipt for deliberately latched tests.
            for recovery in created:
                if not recovery.lease._released:
                    recovery.lease._lease.__exit__(None, None, None)


def test_foreground_application_api_exists(tmp_path):
    import inspect

    for mode in ("adopt", "settled", "historical", "stale", "cached_mismatch"):
        _check_keyed_recovery_inert_ports(mode)
    for mode in ("cached", "latched", "prepared", "release_fault", "fresh"):
        _check_keyed_recovery_real_unlatched_lease(tmp_path, mode)

    from isaaclab_arena_examples.agentic_environment_generation.foreground_workflow import (
        ForegroundWorkflow,
        application_from_cli,
    )

    assert list(inspect.signature(application_from_cli).parameters) == [
        "config",
        "credentials",
        "allow_startup",
    ]

    for method, names in {
        "run": ["self", "principal", "operation_id", "raw_contract"],
        "status": ["self", "principal", "run_id"],
        "cancel": ["self", "principal", "run_id"],
        "resume": ["self", "principal", "run_id", "renew_authorization"],
        "close": ["self"],
    }.items():
        assert list(inspect.signature(getattr(ForegroundWorkflow, method)).parameters) == names


@pytest.mark.parametrize(
    "missing",
    [
        "runtime",
        "neo4j",
        "generation_model",
        "assessment_model",
        "capture",
        "gpu",
        None,
        "resume-preflight",
    ],
)
def test_foreground_application_full_outcome(tmp_path, missing):
    from dataclasses import replace

    import workflow_process_harness as harness

    from isaaclab_arena.agentic_environment_generation.prior_receipt import empty_snapshot
    from isaaclab_arena.agentic_environment_generation.workbench.document_yaml import parse_yaml, reject_unknown_fields
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.prior_artifacts import RetainedPriorArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate, DependencyResult
    from isaaclab_arena.tests.test_environment_workflow_scene_producers import composed_fixture
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import (
        ForegroundAuthority,
        model_settings_sha256,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_initial_generation import (
        InitialGenerationWorker,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_workflow import ForegroundWorkflow
    from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import execution_catalogue_sha256
    from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

    f = composed_fixture(tmp_path)
    config = configuration()
    profiles = {
        role: dict(
            profile_id=role,
            billing="free",
            settings_sha256=model_settings_sha256(config, billing="free"),
        )
        for role in ("generation", "assessment")
    }
    raw = f.contract.model_dump(mode="json")
    # The fixed synthetic HTTP server recognizes this prompt; generation itself,
    # its SDK constructor/ping, output validation and durable adoption remain real.
    raw["source"]["prompt"] = "Initial foreground workflow scene fixture"
    for role, profile in profiles.items():
        raw["execution"][role + "_model"] = profile
    raw["budget"].update(
        per_operation_timeout_seconds=30.0,
        total_deadline_seconds=180.0,
        max_model_calls=8,
        max_model_tokens=80000,
        max_runtime_seconds=120.0,
    )
    request = type(f.contract).model_validate(raw)
    common = dict(
        model_calls=2,
        model_tokens=20000,
        cost_ceiling_usd=0.0,
        runtime_allowance_seconds=30.0,
    )
    profile = f.profile.model_copy(
        update=dict(
            owned_worker=True,
            observe=type(f.profile.observe)(**common, observations=1, realizations=1, steps=2),
            repair=type(f.profile.repair)(**common, candidates=1, revisions=1),
        )
    )
    ceiling = replace(
        f.ceiling,
        max_calls=2,
        max_tokens=20000,
        timeout_seconds=25.0,
        per_call_bound=config["workflow_accounting"],
    )
    calls, workers = [], []

    def probe(requirement, timeout):
        return DependencyResult(
            requirement.dependency_id,
            "unavailable" if requirement.dependency_id == missing else "passed",
            requirement.profile_sha256,
            profile_id=requirement.profile_id,
        )

    def initial_factory(**kwargs):
        calls.append("initial_factory")
        worker = InitialGenerationWorker(**kwargs, require_prior=False, spawn_spec=harness.scene_spawn_spec)
        workers.append(worker)
        return worker

    def scene_factory(**kwargs):
        worker = ForegroundSceneWorker(**kwargs, spawn_spec=harness.scene_spawn_spec)
        workers.append(worker)
        return worker

    def validate_document(text):
        value = parse_yaml(text)
        reject_unknown_fields(value)
        return dict(valid=True, spec=ArenaEnvGraphSpec.from_dict(value).model_dump(mode="json"))

    database = os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"]
    with GraphDatabase.driver(
        os.environ["ARENA_WORKFLOW_NEO4J_URI"],
        auth=None,
        connection_timeout=2,
        connection_acquisition_timeout=3,
        max_transaction_retry_time=0,
    ) as driver:
        with driver.session(database=database) as session:
            for ddl in Neo4jWorkflowStore.schema_requirements():
                session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(10)").consume()
        store = Neo4jWorkflowStore(
            driver,
            database=database,
            deployment_id="foreground-root",
            workspace_id=uuid.uuid4().hex,
        )
        store.initialize_scope()
        scope = dict(database=database, **store.scope)
        principal = dict(principal="creator", **scope, expires_at=time.time() + 240, revoked=False)
        auth = ForegroundAuthority(
            **scope,
            store=store,
            grants=ExecutionGrants(clock=time.time),
            clock=time.time,
            principal_lookup=lambda p: principal if p == "creator" else None,
            profiles=profiles,
            current_config=lambda p: dict(config=config, expires_at=principal["expires_at"]),
        )

        def prior_factory(*, principal, run_id, contract):
            snapshot = empty_snapshot(contract.source.prompt, status="empty", warning=None)
            snapshot["timing"] = {"source": "local_monotonic", "elapsed_seconds": 0.0}
            return RetainedPriorArtifacts(f.area).write(
                contract.source.prompt,
                contract_digest(contract),
                run_id,
                snapshot,
                protect=auth.protect_public,
            )

        private = tmp_path / "owner"
        private.mkdir(mode=0o700)
        app = ForegroundWorkflow(
            store=store,
            authority=auth,
            gate=DependencyGate(probe),
            private_parent=private,
            artifacts=GenerationArtifacts(f.area),
            artifact_root=tmp_path / "artifacts",
            catalogue_sha256=execution_catalogue_sha256(),
            generation_reservation=GenerationReservation(**common),
            prior_factory=prior_factory,
            initial_worker_factory=initial_factory,
            scene_worker_factory=scene_factory,
            validate_document=validate_document,
            scene_options=dict(
                profile=profile,
                artifacts=f.evidence_store,
                capture=f.capture,
                model_ceilings={role: ceiling for role in profiles},
                capture_steps=2,
                capture_timeout_seconds=5.0,
                output_root=tmp_path / "capture-owned",
                direct_root_subjects=(f.subject,),
                displacement_tolerance_m=0.001,
            ),
        )
        before = set(Path("/evidence").glob("generation-child-*-sdk.json"))
        try:
            if missing == "resume-preflight":
                admissions = []

                def admitted(handle):
                    assert store.get_run(handle["run_id"]).state == "pending"
                    assert calls == [] and workers == []
                    admissions.append(handle)

                app.set_admission_listener(admitted)
                original_preflight = app._preflight
                checks = []

                def interrupted_preflight(*args):
                    checks.append(True)
                    if len(checks) == 2:
                        raise ValueError("controlled scene preflight interruption")
                    return original_preflight(*args)

                app._preflight = interrupted_preflight
                interrupted = app.run("creator", "resume-preflight", canonical_json(request))
                run_id = interrupted["run_id"]
                retained = store.get_generation_attempt(run_id)
                assert retained.receipt is not None and store.get_owner().dirty is False
                binding = auth.require_scene_execute("creator", request, run_id=run_id)
                original_clock = auth.clock
                auth.clock = lambda: binding.expires_at + 1
                denied = app.resume("creator", run_id)
                assert denied["disposition"] == "blocked" and len(workers) == 1
                auth.clock = original_clock
                auth.grants.revoke(binding.grant_ref)
                assert app.resume("creator", run_id)["disposition"] == "blocked"
                app._preflight = original_preflight
                original_scene = app.service.run_scene

                def pause_before_claim(*args, **kwargs):
                    raise ValueError("controlled pending scene interruption")

                app.service.run_scene = pause_before_claim
                paused = app.resume("creator", run_id, renew_authorization=True)
                renewed = auth.require_scene_execute("creator", request, run_id=run_id)
                assert renewed.grant_ref != binding.grant_ref
                binding = renewed
                pending = store.scene_snapshot(run_id)
                assert pending.intent.status == "reserved" and pending.intent.worker_fence is None
                assert paused["state"] == "running"
                app.service.run_scene = original_scene
                original_finish = store.finish_scene
                interrupted_finishes = []

                def pause_after_observation(*args, **kwargs):
                    completed = original_finish(*args, **kwargs)
                    if not interrupted_finishes:
                        interrupted_finishes.append(True)
                        raise ValueError("controlled post-commit interruption")
                    return completed

                store.finish_scene = pause_after_observation
                first_resume = app.resume("creator", run_id)
                assert store.scene_snapshot(run_id).intent.action == "repair"
                assert first_resume["state"] == "running"
                store.finish_scene = original_finish
                # Reconstruct feedback from durable identities and actual artifact
                # bytes, even when producer caches have been lost.
                app._local[run_id].ports._retained.clear()
                app._local[run_id].ports._latest.clear()
                resumed = app.resume("creator", run_id)
                assert resumed["state"] == "accepted", resumed
                assert auth.require_scene_execute("creator", request, run_id=run_id) == binding
                assert store.get_generation_attempt(run_id) == retained
                assert calls == ["initial_factory"] and len(workers) == 2
                assert store.get_owner().dirty is False
                assert app.resume("creator", run_id) == resumed
                records = store.result_records(run_id)
                registrations = [retained.registration.model_dump(mode="json")]
                registrations.extend(
                    json.loads(row["scene"])["worker_registration"]
                    for row in records["intents"]
                    if row["scene"] is not None
                )
                assert len(registrations) == 4
                Path("/evidence/workflow-resume.json").write_text(
                    json.dumps(
                        dict(
                            result=resumed,
                            registrations=registrations,
                            same_root=True,
                            interruptions=["scene_preflight", "scene_before_claim", "observation_committed"],
                            cache_reconstructed=True,
                            original_admitted_at=retained.admitted_at,
                        )
                    )
                )
                return
            if missing:
                result = app.run("creator", "full-outcome", canonical_json(request))
            else:
                import contextlib
                import io

                from isaaclab_arena_examples.agentic_environment_generation.foreground_workflow_cli import main

                config_path, request_path = (
                    tmp_path / "profile.json",
                    tmp_path / "contract.json",
                )
                config_path.write_text(
                    json.dumps(
                        dict(
                            schema_version=1,
                            composition="isolated-synthetic-v1",
                            database=dict(
                                uri=os.environ["ARENA_WORKFLOW_NEO4J_URI"],
                                database=database,
                                username="synthetic",
                            ),
                            deployment_id=store.scope["deployment_id"],
                            workspace_id=store.scope["workspace_id"],
                            artifact_root=str(tmp_path / "artifacts"),
                            lease_root=str(private),
                        )
                    )
                )
                config_path.chmod(0o600)
                request_path.write_text(canonical_json(request))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main([
                        "run",
                        "--config",
                        str(config_path),
                        "--principal",
                        "creator",
                        "--operation-id",
                        "full-outcome",
                        str(request_path),
                    ])
                assert code == 0, output.getvalue()
                result = json.loads(output.getvalue().splitlines()[-1])["result"]
            if missing:
                assert result["disposition"] == "dependencies_not_ready"
                assert missing in result["blockers"]
                assert calls == [] and workers == []
                assert set(Path("/evidence").glob("generation-child-*-sdk.json")) == before
                assert store.lookup_submission("full-outcome", canonical_json(request)) is None
                if missing == "runtime":
                    original_source = auth.current_config
                    for role in ("generation", "assessment"):
                        auth.current_config = lambda p, role=role: (None if p == role else original_source(p))
                        with pytest.raises(ValueError):
                            app.run("creator", "missing-" + role, canonical_json(request))
                        auth.current_config = original_source
                    invalid = request.model_dump(mode="json")
                    invalid["criteria"][1]["rubric"] = "unsupported paraphrase"
                    with pytest.raises(ValueError):
                        app.run("creator", "unsupported-rubric", json.dumps(invalid))
                    for role in ("generation", "assessment"):
                        unbounded = dict(config)
                        unbounded.pop("workflow_accounting")
                        auth.current_config = lambda p, role=role: (
                            dict(config=unbounded, expires_at=principal["expires_at"])
                            if p == role
                            else original_source(p)
                        )
                        with pytest.raises(ValueError):
                            app.run("creator", "unbounded-" + role, canonical_json(request))
                        auth.current_config = original_source
                    assert calls == [] and workers == []
                # Real authoritative pending cancellation and outage projection,
                # independent of worker construction or current execution grants.
                pending = store.admit(
                    "pending-cancel",
                    canonical_json(request),
                    canonical_json(request),
                    1,
                )
                assert app.status("creator", pending.run_id)["available_actions"] == [
                    "cancel",
                    "resume",
                ]
                cancelled = app.cancel("creator", pending.run_id)
                assert cancelled["state"] == "cancelled"
                assert app.resume("creator", pending.run_id) == cancelled
                if missing == "runtime":
                    from isaaclab_arena_examples.agentic_environment_generation import foreground_cancellation

                    assert hasattr(foreground_cancellation, "stop_only"), "trusted stop-only wrapper missing"
                    keyed = store.admit("keyed-pending", canonical_json(request), canonical_json(request), 1)
                    authority_calls = []
                    original_config = auth.current_config
                    auth.current_config = lambda p: (_ for _ in ()).throw(AssertionError("cancel resolved config"))
                    try:
                        response = app.cancel_keyed(
                            "creator",
                            "keyed-stop",
                            keyed.run_id,
                            authorize_cancel=lambda p, r: authority_calls.append((p, r)),
                        )
                        assert (
                            response.durable == "recorded" and response.receipt.disposition == "cancellation_requested"
                        )
                        assert response.local_stop.delivery == "no_owner"
                        assert response.cleanup.run_id == keyed.run_id
                        assert store.get_run(keyed.run_id).state == "cancelled"
                        assert (
                            app.cancel_keyed(
                                "creator", "keyed-stop", keyed.run_id, authorize_cancel=lambda p, r: None
                            ).receipt
                            == response.receipt
                        )
                        assert authority_calls == [("creator", keyed.run_id)]
                        Path("/evidence/keyed-pending-adapter.json").write_text(response.model_dump_json())
                    finally:
                        auth.current_config = original_config
                from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import StoreUnavailable

                original_read = store.result_records

                def unavailable(*args):
                    raise StoreUnavailable("synthetic outage")

                store.result_records = unavailable
                try:
                    assert app.status("creator", pending.run_id)["state"] == "unknown"
                    assert app.cancel("creator", pending.run_id)["state"] == "unknown"
                    assert app.resume("creator", pending.run_id)["state"] == "unknown"
                finally:
                    store.result_records = original_read
                assert calls == [] and workers == []
                return
            assert result["state"] == "accepted", result
            run_id = result["run_id"]
            for command in ("status", "cancel", "resume"):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main([
                        command,
                        "--config",
                        str(config_path),
                        "--principal",
                        "creator",
                        run_id,
                    ])
                assert code == 0, output.getvalue()
                assert json.loads(output.getvalue().splitlines()[-1])["result"] == result
            attempt = store.get_generation_attempt(run_id)
            assert attempt.registration.host != "synthetic-bootstrap"
            metadata = json.loads(
                app.artifacts.verified_bytes(attempt.receipt, protect=auth.protect_public)["provenance.json"]
            )["producer_metadata"]
            assert metadata["validation"]["attempted_calls"] == 2
            snapshot = store.scene_snapshot(run_id)
            assert snapshot.candidate.parent_id == snapshot.original.candidate_id
            assert store.get_owner().dirty is False
            sdk = set(Path("/evidence").glob("generation-child-*-sdk.json")) - before
            assert len(sdk) == 4 and all(json.loads(p.read_text())["calls"] == 2 for p in sdk)
            assert app.status("creator", run_id) == result
            assert app.run("creator", "full-outcome", canonical_json(request)) == result
            assert app.resume("creator", run_id) == result
            assert app.cancel("creator", run_id) == result
            assert calls == []  # Positive path used the real default CLI factory.
            # Source configuration and factories are no longer needed by replay.
            auth.current_config = lambda p: (_ for _ in ()).throw(AssertionError("replay resolved config"))
            assert app.run("creator", "full-outcome", canonical_json(request)) == result
            assert app.resume("creator", run_id) == result
            with driver.session(database=database) as session:
                rows = list(
                    session.run(
                        "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                        "WHERE i.run_id=$run_id AND i.kind='scene' RETURN i.scene_json AS scene",
                        **store.scope,
                        run_id=run_id,
                    )
                )
            scenes = [json.loads(row["scene"]) for row in rows]
            assert len(scenes) == 3 and all(s["status"] == "produced" and s["worker_cleanup"] for s in scenes)
            registrations = [
                attempt.registration.model_dump(mode="json"),
                *[s["worker_registration"] for s in scenes],
            ]
            assert len({r["pid"] for r in registrations}) == 4
            assert len({r["fence"]["owner_id"] for r in registrations}) == 2
            Path("/evidence/workflow-application.json").write_text(
                json.dumps(
                    dict(
                        result=result,
                        registrations=registrations,
                        default_cli_factory=True,
                        sdk_files=sorted(p.name for p in sdk),
                        initial_generation="actual generate/SDK/adoption; synthetic HTTP",
                        stages=["observe", "repair", "observe"],
                        synthetic_capture=True,
                    )
                )
            )
        finally:
            app.close()
            f.area.close()


def fixture_registration(fence):
    """Explicit metadata-only bootstrap, not proof that a worker was launched."""
    return WorkerRegistration(
        registration_id=uuid.uuid4().hex,
        fence=fence,
        host="synthetic-bootstrap",
        boot="synthetic-bootstrap",
        pid=1,
        pgid=1,
        sid=1,
        start_ticks=1,
    )


def fixture_cleanup(registration):
    return CleanupEvidence(
        registration=registration,
        evidence_ref="synthetic-bootstrap-only",
        observation="owned_process_group_stopped",
        remote_effects="unknown",
    )


def test_real_scene_refine_committed_fences_and_proposal_guard(tmp_path):
    import workflow_process_harness as harness

    from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import execution_catalogue_sha256

    catalogue = execution_catalogue_sha256()
    raw = scene_contract().model_dump(mode="json")
    raw["budget"].update(
        per_operation_timeout_seconds=30.0,
        total_deadline_seconds=120.0,
        max_model_tokens=80000,
        max_model_calls=8,
        max_runtime_seconds=120.0,
    )
    contract = type(scene_contract()).model_validate(raw)
    scene = ArenaEnvGraphSpec.model_validate(minimal_spec_dict()).model_dump(mode="json")
    with GraphDatabase.driver(
        os.environ["ARENA_WORKFLOW_NEO4J_URI"],
        auth=None,
        connection_timeout=2,
        connection_acquisition_timeout=3,
        max_transaction_retry_time=0,
    ) as driver:
        database = os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"]
        with driver.session(database=database) as session:
            for ddl in Neo4jWorkflowStore.schema_requirements():
                session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(10)").consume()
        store = Neo4jWorkflowStore(
            driver,
            database=database,
            deployment_id="scene-child",
            workspace_id=uuid.uuid4().hex,
        )
        assert store.verify_schema()
        store.initialize_scope()
        auth = authority(store, contract).model_copy(update={"expires_at": time.time() + 120})

        def ready():
            return gate_readiness(contract, mono=time.monotonic, wall=time.time)

        run = store.admit("scene-child", "{}", canonical_json(contract), 1)
        generation = store.reserve_generation(
            run.run_id,
            1,
            "bootstrap",
            auth,
            GenerationReservation(
                model_calls=1,
                model_tokens=1,
                cost_ceiling_usd=0.0,
                runtime_allowance_seconds=1.0,
            ),
            readiness=ready(),
        )
        epoch = store.begin_owner("scene-owner")
        gf = store.claim_intent(generation, "scene-owner", epoch)
        gr = store.register_worker(gf, fixture_registration(gf))
        store.release_attempt(gf, gr.registration_id, auth, readiness=ready())
        with ArtifactArea.create(tmp_path / "artifacts", store_id="scene", registry_id="scene") as area:
            artifacts = GenerationArtifacts(area)
            receipt = artifacts.write(
                gf,
                gr,
                contract,
                json.dumps(scene).encode(),
                scene,
                protect=lambda v: None,
            )
            store.commit_generation_receipt(gf, artifacts.verify(receipt, protect=lambda v: None))
            store.acknowledge_cleanup(gf, fixture_cleanup(gr))
            common = dict(
                model_calls=2,
                model_tokens=20000,
                cost_ceiling_usd=0.0,
                runtime_allowance_seconds=30.0,
            )
            profile = ScenePortProfile(
                port_id="scene-sdk-real-store",
                assurance="synthetic",
                owned_worker=True,
                producer_ids=tuple(c.evidence_producer for c in contract.criteria),
                observe=dict(common, observations=1, realizations=1, steps=10),
                repair=dict(common, candidates=1, revisions=1),
            )

            class ReadAuthority:
                def require_read(self, principal):
                    assert principal == "local"

            service = WorkflowService(store, ReadAuthority(), None, validate_support=lambda c: None)
            first = service.start_scene(
                "local",
                run.run_id,
                artifacts=artifacts,
                protect=lambda v: None,
                validate_generation_candidate=validate_generation_candidate,
                profile=profile,
            )
            first = store.scene_snapshot(run.run_id)
            assert first is not None
            # Bootstrap observation is visibly synthetic, never an SDK or native claim.
            of = store.claim_scene_worker(run.run_id, first.intent.intent_id, "scene-owner", epoch)
            bootstrap_registration = fixture_registration(of)
            store.register_scene_worker(of, bootstrap_registration)
            store.release_scene(
                run.run_id,
                first.intent.intent_id,
                auth,
                readiness=ready(),
                fence=of,
                registration_id=bootstrap_registration.registration_id,
            )
            store.acknowledge_scene_cleanup(of, fixture_cleanup(bootstrap_registration))
            store.finish_scene(
                run.run_id,
                first.intent.intent_id,
                store.get_run(run.run_id).version,
                SceneResult(observation=observation(contract, first.candidate, "bootstrap", fail=True)),
            )
            pending = store.scene_snapshot(run.run_id)
            assert pending.intent is not None, pending.decision
            assert pending.intent.action == "repair", pending.decision
            fence = store.claim_scene_worker(run.run_id, pending.intent.intent_id, "scene-owner", epoch)
            with pytest.raises(ValueError, match="already claimed"):
                store.claim_scene_worker(run.run_id, pending.intent.intent_id, "scene-owner", epoch)
            assert store.get_scene_intent(run.run_id, pending.intent.intent_id).worker_fence == fence
            worker = ForegroundSceneWorker(spawn_spec=harness.scene_spawn_spec)
            prepared = worker.prepare(fence, contract, timeout_s=30)
            try:
                sdk_path = Path(f"/evidence/generation-child-{prepared.registration.pid}-sdk.json")
                deadline = time.monotonic() + 20
                while not sdk_path.exists():
                    assert time.monotonic() < deadline, (
                        prepared.owned_handle.process.stderr.read()
                        if prepared.owned_handle.process.poll() is not None
                        else "SDK startup timeout"
                    )
                    time.sleep(0.02)
                assert json.loads(sdk_path.read_text())["calls"] == 0
                reg = prepared.registration
                assert store.register_scene_worker(fence, reg)
                assert not store.register_scene_worker(fence, reg)
                with pytest.raises(ValueError):
                    store.release_scene(
                        run.run_id,
                        pending.intent.intent_id,
                        auth,
                        readiness=ready(),
                        fence=fence,
                        registration_id="wrong",
                    )
                assert json.loads(sdk_path.read_text())["calls"] == 0
                store.release_scene(
                    run.run_id,
                    pending.intent.intent_id,
                    auth,
                    readiness=ready(),
                    fence=fence,
                    registration_id=reg.registration_id,
                )
                released = store.check_scene_release(
                    run.run_id,
                    pending.intent.intent_id,
                    auth,
                    readiness=ready(),
                    fence=fence,
                    registration_id=reg.registration_id,
                )
                payload = retain_request(
                    area,
                    root=tmp_path / "artifacts",
                    registration=reg,
                    contract=contract,
                    action="refine",
                    data=dict(
                        base_spec=scene,
                        feedback=pending.decision.model_dump(mode="json"),
                    ),
                    protect=lambda v: None,
                )
                reservation = GenerationReservation(**{k: getattr(released.reservation, k) for k in common})
                packet = dict(
                    inputs=dict(
                        operation="new",
                        prompt=contract.source.prompt,
                        retrieval_policy="allow_fallback",
                        execution_catalogue_sha256=catalogue,
                        scene_action="refine",
                        scene_payload=payload,
                    ),
                    config=configuration(),
                    graph_config=None,
                    workflow_execution=dict(
                        version=1,
                        fence=fence.model_dump(mode="json"),
                        registration=reg.model_dump(mode="json"),
                        reservation=reservation.model_dump(mode="json"),
                        admitted_at=store.get_generation_attempt(run.run_id).admitted_at,
                        released_at=released.released_at,
                        deadline=released.released_at + 30,
                    ),
                )
                envelope = json.dumps(packet).encode() + b"\n"
                from isaaclab_arena_examples.agentic_environment_generation.web_api.scene_worker import scene_allowance

                scene_allowance(packet, contract=contract)
                assert prepared.owned_handle.process.poll() is None
                assert time.monotonic() < prepared.owned_handle.deadline
                worker.send(prepared, envelope, timeout_s=2)
                with pytest.raises(RuntimeError, match="already attempted"):
                    worker.send(prepared, envelope, timeout_s=2)
                result = worker.receive(prepared, protect=lambda v: None)
                assert result.attempted_calls == json.loads(sdk_path.read_text())["calls"] == 2
                assert result.output["kind"] == "proposal" and result.output["publication"] == "not_published"
                proposed = ArenaEnvGraphSpec.model_validate(result.output["spec"]).model_dump(mode="json")
                assert proposed == result.output["spec"]
                # Real schema validity is not authority to change the original scene.
                assert proposed["embodiment"] != scene["embodiment"]
                assert worker.cleanup_verified(reg, result.cleanup)
                assert store.acknowledge_scene_cleanup(fence, result.cleanup)
                assert store.get_scene_intent(run.run_id, pending.intent.intent_id).worker_cleanup == result.cleanup
                version = store.get_run(run.run_id).version
                store.finish_scene(
                    run.run_id,
                    pending.intent.intent_id,
                    version,
                    SceneResult(candidate_json=json.dumps(result.output["spec"])),
                )
                assert store.scene_snapshot(run.run_id).decision.reason == "repair_rejected"
                final = store.scene_snapshot(run.run_id)
                assert final.run.state == "stopped" and final.candidate == first.candidate
                assert store.get_scene_intent(run.run_id, pending.intent.intent_id).status == "produced"
                store.retire_owner("scene-owner", epoch)
                assert store.get_owner().dirty is False
                Path("/evidence/workflow-scene.json").write_text(
                    json.dumps(
                        dict(
                            registration=reg.model_dump(mode="json"),
                            cleanup=result.cleanup.model_dump(mode="json"),
                            receipt=result.receipt,
                            proposal_guarded=True,
                            state=final.run.state,
                            initial_generation="synthetic metadata fixture, true schema validation",
                            initial_observation="synthetic metadata fixture",
                            sdk_calls=2,
                            owner_retired=True,
                        )
                    )
                )
            finally:
                worker.stop_owned(prepared, timeout_s=3)


def test_real_neo4j_foreground_scene_ports_three_stage_trace(tmp_path):
    from dataclasses import replace

    import workflow_process_harness as harness

    from isaaclab_arena.tests.test_environment_workflow_scene_producers import composed_fixture
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import (
        ForegroundAuthority,
        model_settings_sha256,
    )
    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
    from isaaclab_arena_examples.agentic_environment_generation.foreground_scene_ports import ForegroundScenePorts
    from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import execution_catalogue_sha256
    from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

    catalogue = execution_catalogue_sha256()
    f = composed_fixture(tmp_path)
    config = configuration()
    profiles = {
        role: dict(
            profile_id=role,
            billing="free",
            settings_sha256=model_settings_sha256(config, billing="free"),
        )
        for role in ("generation", "assessment")
    }
    raw = f.contract.model_dump(mode="json")
    for role, profile in profiles.items():
        raw["execution"][role + "_model"] = profile
    raw["budget"].update(
        per_operation_timeout_seconds=30.0,
        total_deadline_seconds=120.0,
        max_model_calls=8,
        max_model_tokens=80000,
        max_runtime_seconds=120.0,
    )
    request = type(f.contract).model_validate(raw)
    common = dict(
        model_calls=2,
        model_tokens=20000,
        cost_ceiling_usd=0.0,
        runtime_allowance_seconds=30.0,
    )
    profile = f.profile.model_copy(
        update=dict(
            owned_worker=True,
            observe=type(f.profile.observe)(**common, observations=1, realizations=1, steps=2),
            repair=type(f.profile.repair)(**common, candidates=1, revisions=1),
        )
    )
    scene = ArenaEnvGraphSpec.model_validate(f.scene).model_dump(mode="json")
    database = os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"]
    with GraphDatabase.driver(
        os.environ["ARENA_WORKFLOW_NEO4J_URI"],
        auth=None,
        connection_timeout=2,
        connection_acquisition_timeout=3,
        max_transaction_retry_time=0,
    ) as driver:
        store = Neo4jWorkflowStore(
            driver,
            database=database,
            deployment_id="scene-ports",
            workspace_id=uuid.uuid4().hex,
        )
        assert store.verify_schema()
        store.initialize_scope()
        run = store.admit("scene-ports", "{}", canonical_json(request), 1)
        scope = dict(database=database, **store.scope)
        principal = dict(principal="creator", **scope, expires_at=time.time() + 120, revoked=False)
        auth = ForegroundAuthority(
            **scope,
            store=store,
            grants=ExecutionGrants(clock=time.time),
            clock=time.time,
            principal_lookup=lambda p: principal if p == "creator" else None,
            profiles=profiles,
            current_config=lambda p: dict(config=config, expires_at=principal["expires_at"]),
        )
        auth.protect_workflow_contract("creator", request)
        auth.bind_run(
            "creator",
            run.operation_id,
            request,
            run_id=run.run_id,
            catalogue_sha256=catalogue,
        )
        auth.bind_workflow_models("creator", request, run_id=run.run_id)

        def ready(c):
            return gate_readiness(c, mono=time.monotonic, wall=time.time)

        bootstrap_auth = authority(store, request).model_copy(
            update=dict(principal="creator", expires_at=principal["expires_at"])
        )
        generation = store.reserve_generation(
            run.run_id,
            1,
            "bootstrap",
            bootstrap_auth,
            GenerationReservation(
                model_calls=1,
                model_tokens=1,
                cost_ceiling_usd=0.0,
                runtime_allowance_seconds=1.0,
            ),
            readiness=ready(request),
        )
        epoch = store.begin_owner("synthetic-generation-bootstrap")
        gf = store.claim_intent(generation, "synthetic-generation-bootstrap", epoch)
        gr = store.register_worker(gf, fixture_registration(gf))
        store.release_attempt(gf, gr.registration_id, bootstrap_auth, readiness=ready(request))
        artifacts = GenerationArtifacts(f.area)
        receipt = artifacts.write(
            gf,
            gr,
            request,
            json.dumps(scene).encode(),
            scene,
            protect=auth.protect_public,
        )
        store.commit_generation_receipt(gf, artifacts.verify(receipt, protect=auth.protect_public))
        store.acknowledge_cleanup(gf, fixture_cleanup(gr))
        store.retire_owner("synthetic-generation-bootstrap", epoch)
        service = WorkflowService(store, auth, None, validate_support=lambda c: None)
        worker = ForegroundSceneWorker(spawn_spec=harness.scene_spawn_spec)
        private = tmp_path / "owner"
        private.mkdir(mode=0o700)
        lease = ForegroundOwnerLease(
            private,
            run_id=run.run_id,
            principal="creator",
            cleanup_verified=worker.cleanup_verified,
        )
        store.begin_owner(lease.owner_id)
        service.start_scene(
            "creator",
            run.run_id,
            artifacts=artifacts,
            protect=auth.protect_public,
            validate_generation_candidate=validate_generation_candidate,
            profile=profile,
        )
        original = store.scene_snapshot(run.run_id).candidate
        ceiling = replace(
            f.ceiling,
            max_calls=2,
            max_tokens=20000,
            timeout_seconds=25.0,
            per_call_bound=config["workflow_accounting"],
        )
        ports = ForegroundScenePorts(
            store=store,
            authority=auth,
            lease=lease,
            worker=worker,
            principal="creator",
            run_id=run.run_id,
            catalogue_sha256=catalogue,
            artifact_root=tmp_path / "artifacts",
            ready=ready,
            profile=profile,
            artifacts=f.evidence_store,
            protect=auth.protect_public,
            capture=f.capture,
            model_ceilings={r: ceiling for r in profiles},
            capture_steps=2,
            capture_timeout_seconds=5.0,
            output_root=tmp_path / "capture-owned",
            direct_root_subjects=(f.subject,),
            displacement_tolerance_m=0.001,
        )
        try:
            final = service.run_scene("creator", run.run_id, ports=ports)
            assert final.run.state == "accepted", (
                final.decision,
                [(p.registration.pid, p.owned_handle.process.poll()) for p in ports.prepared_workers],
            )
            assert final.candidate.parent_id == original.candidate_id
            assert len(ports.prepared_workers) == 3
            assert service.run_scene("creator", run.run_id, ports=ports) == final
            registrations = []
            for prepared in ports.prepared_workers:
                reg = prepared.registration
                retained = store.get_scene_intent(run.run_id, reg.fence.intent_id)
                assert retained.status == "produced" and retained.worker_registration == reg
                physical = worker.stop_owned(prepared, timeout_s=3)
                assert retained.worker_cleanup == physical
                assert worker.cleanup_verified(reg, physical)
                assert json.loads(Path(f"/evidence/generation-child-{reg.pid}-sdk.json").read_text())["calls"] == 2
                registrations.append(reg.model_dump(mode="json"))
            assert len({r["pid"] for r in registrations}) == 3
            assert len({r["fence"]["owner_id"] for r in registrations}) == 1
            original_get_run = store.get_run

            def offline(*args):
                raise AssertionError("local stop must not read Neo4j")

            store.get_run = offline
            try:
                assert len(ports.stop_local()) == 3
                with pytest.raises(ValueError, match="locally stopped"):
                    ports.prepare_worker(None, None, None, request)
            finally:
                store.get_run = original_get_run
            lease.require_held(run.run_id, "creator")
            ports.retire_terminal()
            assert store.get_owner().dirty is False
            with pytest.raises(ValueError):
                lease.require_held(run.run_id, "creator")
            independent = Neo4jWorkflowStore(driver, database=database, **store.scope)
            assert independent.scene_snapshot(run.run_id) == final
            with driver.session(database=database) as session:
                rows = list(
                    session.run(
                        "MATCH (a:ArenaCriterionAssessment {deployment_id:$deployment_id,"
                        " workspace_id:$workspace_id})-[:ASSESSES]->(e:ArenaWorkflowEvidence)-[:FOR_CANDIDATE]->(c:ArenaWorkflowCandidate)"
                        " RETURN e.payload AS evidence, c.record_id AS candidate",
                        **store.scope,
                    )
                )
            assert len(rows) == 2
            cohorts = [json.loads(r["evidence"])["cohort"] for r in rows]
            assert cohorts[0] != cohorts[1]
            assert {r["candidate"] for r in rows} == {
                original.candidate_id,
                final.candidate.candidate_id,
            }
            Path("/evidence/workflow-scene-ports.json").write_text(
                json.dumps(
                    dict(
                        state=final.run.state,
                        registrations=registrations,
                        stages=["observe", "repair", "observe"],
                        candidate=final.candidate.model_dump(mode="json"),
                        cohorts=cohorts,
                        owner_retired=True,
                        synthetic_capture=True,
                        initial_generation="synthetic fixture; true schema validation",
                    )
                )
            )
        finally:
            for prepared in ports.prepared_workers:
                worker.stop_owned(prepared, timeout_s=3)
            f.area.close()
