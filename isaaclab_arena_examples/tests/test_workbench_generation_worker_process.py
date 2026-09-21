# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Actual fixed-child process proofs, only in the exact F0 backend profile."""

import json
import os
import subprocess
from pathlib import Path

import pytest


def test_foreground_adapter_prepare_send_stop():
    import time

    import generation_worker_fixture as fixture

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence
    from isaaclab_arena.tests.test_environment_workflow_service import contract
    from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import ForegroundGenerationWorker

    worker = ForegroundGenerationWorker(spawn_spec=lambda: fixture.spawn_spec("production-result"))
    fence = AttemptFence(
        run_id="run", intent_id="intent", attempt_id="attempt", generation=1, owner_id="owner", owner_epoch=1
    )
    prepared = worker.prepare(fence, contract(), timeout_s=5)
    try:
        reg = prepared.registration
        assert reg.fence == fence and reg.pid == reg.pgid == reg.sid
        now = time.time()
        packet = {
            "inputs": {
                "operation": "new",
                "prompt": contract().source.prompt,
                "retrieval_policy": "allow_fallback",
                "execution_catalogue_sha256": "a" * 64,
            },
            "config": {},
            "graph_config": None,
            "workflow_execution": {
                "version": 1,
                "fence": fence.model_dump(mode="json"),
                "registration": reg.model_dump(mode="json"),
                "reservation": {
                    "model_calls": 2,
                    "model_tokens": 1000,
                    "cost_ceiling_usd": 0.0,
                    "runtime_allowance_seconds": 5.0,
                },
                "admitted_at": now,
                "released_at": now,
                "deadline": now + 5,
            },
        }
        worker.send(prepared, json.dumps(packet).encode() + b"\n", timeout_s=2)
        with pytest.raises(RuntimeError, match="already attempted"):
            worker.send(prepared, json.dumps(packet).encode() + b"\n", timeout_s=2)
        prepared.owned_handle.process.wait(timeout=5)
        assert json.loads(prepared.owned_handle.process.stdout.readline()) == {"result": {"fixture": "fixed-result"}}
    finally:
        evidence = worker.stop_owned(prepared, timeout_s=3)
    assert worker.cleanup_verified(reg, evidence)
    assert evidence.remote_effects == "unknown"


def test_foreground_scene_ports_actual_three_stage_trace(tmp_path):
    import importlib.util

    name = "isaaclab_arena_examples.agentic_environment_generation.foreground_scene_ports"
    assert importlib.util.find_spec(name) is not None, "owned ScenePorts composition missing"
    _scene_composition_trace(tmp_path)


def test_foreground_scene_role_expiry_is_unknown_without_resend(tmp_path):
    _scene_composition_trace(tmp_path, expiry=True)


def test_foreground_scene_required_dependency_blocks_before_all_children(tmp_path):
    _scene_composition_trace(tmp_path, dependency_blocked=True)


def test_foreground_scene_lease_rejects_database_only_settlement(tmp_path):
    from types import SimpleNamespace

    import generation_worker_fixture as fixture

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence
    from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence
    from isaaclab_arena.tests.test_environment_workflow_service import contract
    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
    from isaaclab_arena_examples.agentic_environment_generation.foreground_scene import ForegroundSceneWorker

    worker = ForegroundSceneWorker(spawn_spec=lambda: fixture.spawn_spec("scene-sdk"))
    private = tmp_path / "lease"
    private.mkdir(mode=0o700)
    lease = ForegroundOwnerLease(private, run_id="run", principal="creator", cleanup_verified=worker.cleanup_verified)
    fence = AttemptFence(
        run_id="run", intent_id="first", attempt_id="first", generation=1, owner_id=lease.owner_id, owner_epoch=1
    )
    lease.mark_prepared(fence)
    value = contract().model_dump(mode="json")
    value["budget"]["per_operation_timeout_seconds"] = 30.0
    prepared = worker.prepare(fence, type(contract()).model_validate(value), timeout_s=30)
    try:
        _wait_evidence(prepared, "sdk")
        registration = prepared.registration
        forged = CleanupEvidence(
            registration=registration,
            evidence_ref="forged",
            observation="owned_process_group_stopped",
            remote_effects="unknown",
        )
        retained = SimpleNamespace(
            status="produced", worker_fence=fence, worker_registration=registration, worker_cleanup=forged
        )
        store = SimpleNamespace(get_scene_intent=lambda *a: retained)
        with pytest.raises(ValueError, match="trusted cleanup"):
            lease.require_scene_settled(store, registration, forged)
        evidence = worker.stop_owned(prepared, timeout_s=3)
        retained.worker_cleanup = evidence
        retained.status = "released"
        with pytest.raises(ValueError, match="settled scene"):
            lease.require_scene_settled(store, registration, evidence)
        retained.status = "produced"
        # A reconstructed DB object is not the local supervisor's cleanup witness.
        with pytest.raises(ValueError, match="trusted cleanup"):
            lease.require_scene_settled(store, registration, evidence.model_copy())
        lease.require_scene_settled(store, registration, evidence)
        retained.worker_fence = fence.model_copy(update={"generation": True})
        with pytest.raises(ValueError, match="settled scene"):
            lease.require_scene_settled(store, registration, evidence)
        retained.worker_fence = fence
        with pytest.raises(ValueError, match="Cleanup proof"):
            lease.release_never_prepared()
        lease.require_held("run", "creator")
        lease.release_after_cleanup(registration, evidence)
    finally:
        worker.stop_owned(prepared, timeout_s=3)


def test_scene_worker_real_refine(tmp_path):
    import importlib.util

    name = "isaaclab_arena_examples.agentic_environment_generation.foreground_scene"
    assert importlib.util.find_spec(name) is not None, "scene WorkerPort is missing"
    _scene_roundtrip(tmp_path, "refine")


def test_scene_worker_real_assess(tmp_path):
    _scene_roundtrip(tmp_path, "assess")


def test_scene_worker_frozen_key_veto_before_persistence(tmp_path):
    _scene_roundtrip(tmp_path, "refine", secret=True)


@pytest.mark.parametrize("disposition", ["timeout", "cancel"])
def test_scene_worker_waiting_cleanup(tmp_path, disposition):

    import generation_worker_fixture as fixture

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence
    from isaaclab_arena.tests.test_environment_workflow_service import contract
    from isaaclab_arena_examples.agentic_environment_generation.foreground_scene import ForegroundSceneWorker

    value = contract().model_dump(mode="json")
    value["budget"]["per_operation_timeout_seconds"] = 30.0
    worker = ForegroundSceneWorker(spawn_spec=lambda: fixture.spawn_spec("scene-sdk"))
    fence = AttemptFence(
        run_id="waiting", intent_id="intent", attempt_id="attempt", generation=1, owner_id="owner", owner_epoch=1
    )
    prepared = worker.prepare(fence, type(contract()).model_validate(value), timeout_s=12)
    try:
        assert _wait_evidence(prepared, "sdk")["calls"] == 0
        if disposition == "timeout":
            prepared.owned_handle.process.wait(timeout=13)
        evidence = worker.stop_owned(prepared, timeout_s=3)
        assert worker.cleanup_verified(prepared.registration, evidence)
        assert _sdk_evidence(prepared)["calls"] == 0
    finally:
        worker.stop_owned(prepared, timeout_s=3)


def _scene_roundtrip(tmp_path, action, *, secret=False):
    import time

    import generation_worker_fixture as fixture

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.tests.test_environment_workflow_scene_engines import configuration
    from isaaclab_arena.tests.test_environment_workflow_service import contract
    from isaaclab_arena.tests.utils.agentic_environment_generation import minimal_spec_dict
    from isaaclab_arena_examples.agentic_environment_generation.foreground_scene import ForegroundSceneWorker
    from isaaclab_arena_examples.agentic_environment_generation.web_api.scene_worker import retain_request

    value = contract().model_dump(mode="json")
    value["budget"]["per_operation_timeout_seconds"] = 30.0
    request = type(contract()).model_validate(value)
    worker = ForegroundSceneWorker(spawn_spec=lambda: fixture.spawn_spec("scene-sdk"))
    fence = AttemptFence(
        run_id="scene-run",
        intent_id="scene-intent",
        attempt_id="scene-attempt",
        generation=1,
        owner_id="scene-owner",
        owner_epoch=1,
    )
    root = tmp_path / "scene"
    with ArtifactArea.create(root, store_id="store", registry_id="registry") as area:
        prepared = worker.prepare(fence, request, timeout_s=30)
        try:
            _wait_evidence(prepared, "sdk")
            assert _sdk_evidence(prepared)["calls"] == 0
            packet = fixture.production_packet(runtime_seconds=30)
            packet["config"] = configuration()
            if secret:
                packet["config"]["api_key"] = "not_published"
            packet["inputs"]["prompt"] = request.source.prompt
            packet["workflow_execution"]["fence"] = fence.model_dump(mode="json")
            packet["workflow_execution"]["registration"] = prepared.registration.model_dump(mode="json")
            packet["workflow_execution"]["reservation"]["model_tokens"] = 20000
            packet["inputs"]["scene_action"] = action
            data = {
                "base_spec": minimal_spec_dict(),
                "feedback": {"decision": "repair", "evidence_ref": "retained-test"},
            }
            if action == "assess":
                from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest
                from isaaclab_arena.agentic_environment_generation.workflow.scene_evidence_artifacts import \
                    SceneEvidenceArtifacts
                from isaaclab_arena.agentic_environment_generation.workflow.scene_observation import ObservationRecorder
                from isaaclab_arena.tests._workflow_scene_fixture import criterion, identities, sample

                candidate, cohort = identities()
                digest = contract_digest(request)
                candidate = candidate.model_copy(update={"contract_digest": digest})
                cohort = cohort.model_copy(update={"contract_digest": digest})
                visual = criterion(
                    "scene.visible",
                    kind="visual",
                    required_modalities=("rgb",),
                    coordinate_frames=("front",),
                    observation_window={"start_step": 0, "end_step": 0},
                    rubric="subject visible in every retained frame",
                    limit={"operator": "eq", "value": 1, "unit": "boolean"},
                )
                recorder = ObservationRecorder(lambda env, step: sample(step), provenance="synthetic")
                recorder(None, 0)
                recorder.add_frame(
                    camera="front", step=0, subject_ids=("cup",), image_bytes=b"synthetic-image-not-native"
                )
                observation = SceneEvidenceArtifacts(area).write(
                    candidate, cohort, recorder.payload(), protect=lambda v: None
                )
                data = dict(
                    candidate=candidate.model_dump(mode="json"),
                    cohort=cohort.model_dump(mode="json"),
                    criterion=visual.model_dump(mode="json"),
                    observation_manifest_digest=observation.manifest_digest,
                )
            packet["inputs"]["scene_payload"] = retain_request(
                area,
                root=root,
                registration=prepared.registration,
                contract=request,
                action=action,
                data=data,
                protect=lambda v: None,
            )
            envelope = json.dumps(packet).encode() + b"\n"
            worker.send(prepared, envelope, timeout_s=2)
            with pytest.raises(RuntimeError, match="already attempted"):
                worker.send(prepared, envelope, timeout_s=2)
            prepared.owned_handle.process.wait(timeout=25)
            retained = list((root / "final/scene-model-output").glob("*/value.json"))
            if secret:
                assert not retained
                assert _sdk_evidence(prepared)["calls"] == 2
                assert prepared.owned_handle.process.stdout.read() == b""
                return
            assert len(retained) == 1, "child retains output before parent receives"
            assert packet["config"]["api_key"] not in retained[0].read_text()
            result = worker.receive(prepared, protect=lambda v: None)
            if action == "refine":
                assert result.output["kind"] == "proposal"
                assert result.output["spec"] == ArenaEnvGraphSpec.model_validate(minimal_spec_dict()).model_dump(
                    mode="json"
                )
            else:
                assert result.output["kind"] == "raw_visual_response"
                assert result.output["raw_response"]
            assert result.output["publication"] == "not_published"
            assert result.receipt["manifest_digest"]
            assert result.cleanup.registration == prepared.registration
            assert _sdk_evidence(prepared)["calls"] == 2
            assert result.attempted_calls == 2
            from isaaclab_arena_examples.agentic_environment_generation.web_api.scene_worker import read_retained

            def mutation(value):
                value["injected"] = True

            with pytest.raises(ValueError, match="reject-only"):
                read_retained(area, result.receipt, protect=mutation)
            assert read_retained(area, result.receipt, protect=lambda v: None)["output"] == result.output
            assert time.monotonic() < prepared.owned_handle.deadline
        finally:
            worker.stop_owned(prepared, timeout_s=3)


def _scene_composition_trace(tmp_path, *, expiry=False, dependency_blocked=False):
    """Synthetic store, real held lease/authority/service/producers/SDK child; not native."""
    import copy
    import time
    from dataclasses import replace
    from types import SimpleNamespace

    import generation_worker_fixture as fixture

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (SceneDecision, SceneIntent,
                                                                                   SceneSnapshot, assess_and_route,
                                                                                   candidate_record, identity,
                                                                                   repaired_candidate)
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.tests.test_environment_workflow_scene_engines import configuration
    from isaaclab_arena.tests._workflow_scene_fixture import composed_fixture
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import (ForegroundAuthority,
                                                                                                 model_settings_sha256)
    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
    from isaaclab_arena_examples.agentic_environment_generation.foreground_scene import ForegroundSceneWorker
    from isaaclab_arena_examples.agentic_environment_generation.foreground_scene_ports import ForegroundScenePorts
    from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

    f = composed_fixture(tmp_path)
    # A real tiny PNG travels through capture_trajectory, retained artifacts and
    # the installed SDK image serializer; the synthetic environment is explicit.
    import base64

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
    )
    import struct
    import zlib

    offset = 8
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    while offset < len(png):
        size = struct.unpack(">I", png[offset : offset + 4])[0]
        chunk = png[offset + 4 : offset + 8 + size]
        assert zlib.crc32(chunk) & 0xFFFFFFFF == struct.unpack(">I", png[offset + 8 + size : offset + 12 + size])[0]
        offset += size + 12
    f.Env.reset = lambda self: ({"camera_obs": {"wrist": png}}, {})
    config = configuration()
    profiles = {
        role: dict(profile_id=role, billing="free", settings_sha256=model_settings_sha256(config, billing="free"))
        for role in ("generation", "assessment")
    }
    value = f.contract.model_dump(mode="json")
    for role, profile in profiles.items():
        value["execution"][role + "_model"] = profile
    value["budget"].update(
        per_operation_timeout_seconds=30.0,
        total_deadline_seconds=120.0,
        max_runtime_seconds=120.0,
        max_model_calls=8,
        max_model_tokens=80000,
    )
    request = type(f.contract).model_validate(value)
    common = dict(model_calls=2, model_tokens=20000, cost_ceiling_usd=0.0, runtime_allowance_seconds=30.0)
    profile = f.profile.model_copy(
        update=dict(
            owned_worker=True,
            observe=type(f.profile.observe)(**common, observations=1, realizations=1, steps=2),
            repair=type(f.profile.repair)(**common, candidates=1, revisions=1),
        )
    )
    original = candidate_record(
        "run", ArenaEnvGraphSpec.model_validate(f.scene).model_dump(mode="json"), source_id="generation"
    )

    class ReadySceneWorker(ForegroundSceneWorker):
        def prepare(self, *args, **kwargs):
            prepared = super().prepare(*args, **kwargs)
            assert _wait_evidence(prepared, "sdk")["calls"] == 0
            return prepared

    worker = ReadySceneWorker(spawn_spec=lambda: fixture.spawn_spec("scene-sdk"))
    private = tmp_path / "owner"
    private.mkdir(mode=0o700)
    lease = ForegroundOwnerLease(private, run_id="run", principal="creator", cleanup_verified=worker.cleanup_verified)
    scope = dict(database="neo4j", deployment_id="dep", workspace_id="ws")
    now = time.time()
    principal = dict(principal="creator", **scope, expires_at=now + 120, revoked=False)
    clock = [now]
    sources = {role: dict(config=config, expires_at=now + (100 if role == "assessment" else 120)) for role in profiles}

    class Store:
        database = "neo4j"
        dependency_instances = {}

        def __init__(self):
            self.scope = {k: v for k, v in scope.items() if k != "database"}
            self.owner = SimpleNamespace(owner_id=lease.owner_id, owner_epoch=1, dirty=True)
            self.run = SimpleNamespace(
                run_id="run",
                operation_id="operation",
                state="running",
                phase="scene",
                version=1,
                contract_json=canonical_json(request),
            )
            self.candidate, self.decision = original, SceneDecision(action="observe", reason="initial")
            self.results, self.history, self.registrations, self.releases = [], {}, [], []
            self.failures = []
            self.intent = self.next_intent("observe")

        def next_intent(self, action):
            return SceneIntent(
                intent_id=identity(self.run.version),
                candidate_id=self.candidate.candidate_id,
                action=action,
                status="reserved",
                reservation=getattr(profile, action),
            )

        def get_run(self, run_id):
            assert run_id == "run"
            return copy.deepcopy(self.run)

        def get_generation_attempt(self, run_id):
            return SimpleNamespace(admitted_at=now)

        def get_owner(self):
            return copy.deepcopy(self.owner)

        def scene_snapshot(self, run_id):
            return SceneSnapshot(self.get_run(run_id), original, self.candidate, self.decision, self.intent, profile)

        def get_scene_intent(self, run_id, intent_id):
            return self.intent if self.intent and self.intent.intent_id == intent_id else self.history[intent_id]

        def claim_scene_worker(self, run_id, intent_id, owner_id, owner_epoch):
            assert self.intent.intent_id == intent_id and self.intent.worker_fence is None
            assert (owner_id, owner_epoch) == (lease.owner_id, 1)
            fence = AttemptFence(
                run_id=run_id,
                intent_id=intent_id,
                attempt_id=identity(intent_id, "worker"),
                generation=1,
                owner_id=owner_id,
                owner_epoch=owner_epoch,
            )
            self.intent = self.intent.model_copy(update={"worker_fence": fence})
            return fence

        def register_scene_worker(self, fence, registration):
            assert self.intent.worker_fence == fence == registration.fence
            self.registrations.append(registration)
            self.intent = self.intent.model_copy(update={"worker_registration": registration})

        def release_scene(self, run_id, intent_id, auth, *, readiness, fence, registration_id):
            assert (
                self.intent.worker_fence == fence and self.intent.worker_registration.registration_id == registration_id
            )
            self.auth = auth
            self.intent = self.intent.model_copy(update={"status": "released", "released_at": time.time()})
            self.releases.append(intent_id)
            if expiry:
                clock[0] = sources["assessment"]["expires_at"] + 1
            return True

        def check_scene_release(self, run_id, intent_id, auth, *, readiness, fence, registration_id):
            assert auth == self.auth and self.intent.intent_id == intent_id and self.intent.status == "released"
            assert (
                self.intent.worker_fence == fence and self.intent.worker_registration.registration_id == registration_id
            )
            assert self.intent.worker_cleanup is None
            return self.intent

        def acknowledge_scene_cleanup(self, fence, evidence):
            assert self.intent.worker_fence == fence and evidence.registration == self.intent.worker_registration
            assert worker.cleanup_verified(evidence.registration, evidence)
            self.intent = self.intent.model_copy(update={"worker_cleanup": evidence})

        def mark_scene_unknown(self, run_id, intent_id):
            import sys

            self.failures.append(repr(sys.exception()))
            self.run.state = "reconciliation_required"
            self.intent = self.intent.model_copy(update={"status": "reconciliation_required"})

        def finish_scene(self, run_id, intent_id, version, result):
            assert len(self.results) < 3 and self.intent.worker_cleanup is not None
            lease.require_held("run", "creator")
            self.history[intent_id] = self.intent.model_copy(update={"status": "produced"})
            self.results.append(result)
            self.run.version += 1
            if result.observation:
                self.decision = assess_and_route(request, self.candidate, result.observation)
            else:
                assert result.candidate_json is not None, result
                self.candidate = repaired_candidate(
                    request, original, self.candidate, json.loads(result.candidate_json), source_id=intent_id
                )
                self.decision = SceneDecision(action="observe", reason="fresh_child")
            if self.decision.action in ("accept", "stop"):
                self.run.state = "accepted" if self.decision.action == "accept" else "stopped"
                self.intent = None
            else:
                self.intent = self.next_intent(self.decision.action)

        def retire_owner(self, owner_id, epoch):
            assert self.run.state == "accepted" and len(self.history) == 3
            assert (owner_id, epoch) == (self.owner.owner_id, self.owner.owner_epoch)
            self.owner.dirty = False

    store = Store()
    authority = ForegroundAuthority(
        **scope,
        store=store,
        grants=ExecutionGrants(clock=lambda: clock[0]),
        clock=lambda: clock[0],
        principal_lookup=lambda p: principal,
        profiles=profiles,
        current_config=lambda p: sources[p],
    )
    # Fresh-contract screening before any binding or persistence belongs to the caller.
    authority.protect_workflow_contract("creator", request)
    authority.bind_run(
        "creator",
        "operation",
        request,
        run_id="run",
        catalogue_sha256=fixture.production_packet()["inputs"]["execution_catalogue_sha256"],
    )
    authority.bind_workflow_models("creator", request, run_id="run")
    ceiling = replace(
        f.ceiling, max_calls=2, max_tokens=20000, timeout_seconds=25.0, per_call_bound=config["workflow_accounting"]
    )
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import (DependencyGate, DependencyResult,
                                                                                  ReadinessClock, durable_readiness,
                                                                                  required_dependencies)

    probes = []

    def probe(requirement, timeout):
        probes.append(requirement.dependency_id)
        return DependencyResult(
            requirement.dependency_id,
            "unavailable" if dependency_blocked and requirement.dependency_id == "assessment_model" else "passed",
            requirement.profile_sha256,
            profile_id=requirement.profile_id,
        )

    gate = DependencyGate(probe)
    mapping = ReadinessClock.capture()

    def ready(contract):
        requirements = required_dependencies(contract)
        report = gate.check(requirements, timeout_s=30)
        if not report.ready:
            raise ValueError("required dependency unavailable")
        return durable_readiness(contract, requirements, report, mapping=mapping)

    ports = ForegroundScenePorts(
        store=store,
        authority=authority,
        lease=lease,
        worker=worker,
        principal="creator",
        run_id="run",
        catalogue_sha256=fixture.production_packet()["inputs"]["execution_catalogue_sha256"],
        artifact_root=tmp_path / "artifacts",
        ready=ready,
        profile=profile,
        artifacts=f.evidence_store,
        protect=authority.protect_public,
        capture=f.capture,
        model_ceilings={r: ceiling for r in profiles},
        capture_steps=2,
        capture_timeout_seconds=5.0,
        output_root=tmp_path / "capture-owned",
        direct_root_subjects=(f.subject,),
        displacement_tolerance_m=0.001,
    )
    service = WorkflowService(store, authority, None, validate_support=ports.admit)
    try:
        if dependency_blocked:
            with pytest.raises(ValueError, match="required dependency unavailable"):
                service.run_scene("creator", "run", ports=ports)
            assert set(probes) == {r.dependency_id for r in required_dependencies(request)}
            assert not worker._owned and not store.registrations and not store.releases
            lease.release_never_prepared()
            return
        final = service.run_scene("creator", "run", ports=ports)
        assert final.run.state == ("reconciliation_required" if expiry else "accepted"), (
            store.failures,
            final,
            store.results,
        )
        before = len(worker._owned)
        assert service.run_scene("creator", "run", ports=ports).run.state == final.run.state
        assert len(worker._owned) == before
        if expiry:
            assert not store.results and len(store.releases) == 1
            assert all(not o.attempted for o in worker._owned)
            lease.require_held("run", "creator")
            return
        assert [bool(r.observation) for r in store.results] == [True, False, True]
        assert final.candidate.parent_id == original.candidate_id
        assert len({r.pid for r in store.registrations}) == 3
        assert len({r.fence.owner_id for r in store.registrations}) == 1
        assert store.results[0].observation.cohort != store.results[2].observation.cohort
        for prepared in ports.prepared_workers:
            assert _sdk_evidence(prepared)["calls"] == 2
            assert worker.cleanup_verified(prepared.registration, worker.stop_owned(prepared, timeout_s=3))
        lease.require_held("run", "creator")
        ports.retire_terminal()
        assert not store.get_owner().dirty
        from api import write

        write(
            "foreground-scene-trace.json",
            dict(
                scope="synthetic store and capture; real held owner, service, SDK scene children; not native",
                state=final.run.state,
                parent_id=original.candidate_id,
                candidate_id=final.candidate.candidate_id,
                stages=[
                    dict(
                        action=i.action,
                        intent_id=i.intent_id,
                        registration=i.worker_registration.model_dump(mode="json"),
                        cleanup=i.worker_cleanup.model_dump(mode="json"),
                        receipt=ports._results[i.intent_id].receipt,
                        attempted_calls=ports._results[i.intent_id].attempted_calls,
                    )
                    for i in store.history.values()
                ],
                observations=[r.observation.model_dump(mode="json") for r in store.results if r.observation],
                owner_retired=True,
            ),
        )
        with pytest.raises(ValueError, match="unavailable"):
            lease.require_held("run", "creator")
    finally:
        for prepared in ports.prepared_workers:
            worker.stop_owned(prepared, timeout_s=3)
        f.area.close()


def _foreground_composition(tmp_path, mode="production-sdk", runtime=30, model_calls=2, dispatch=True):
    import time
    from types import SimpleNamespace

    import generation_worker_fixture as fixture

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, GenerationReservation
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import GenerationCoordinator
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import (DependencyGate, DependencyResult,
                                                                                  ReadinessClock)
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena.tests.test_environment_workflow_service import contract
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import (ForegroundAuthority,
                                                                                                 model_settings_sha256)
    from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import ForegroundGenerationWorker
    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
    from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

    fixture_packet = fixture.production_packet()
    config = fixture_packet["config"]
    profile = dict(
        profile_id="synthetic", billing="free", settings_sha256=model_settings_sha256(config, billing="free")
    )
    value = contract().model_dump(mode="json")
    value["execution"]["generation_model"] = profile
    value["budget"]["per_operation_timeout_seconds"] = 30.0
    request = type(contract()).model_validate(value)
    worker = ForegroundGenerationWorker(spawn_spec=lambda: fixture.spawn_spec(mode))
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    lease = ForegroundOwnerLease(private, run_id="run", principal="creator", cleanup_verified=worker.cleanup_verified)
    fence = AttemptFence(
        run_id="run", intent_id="intent", attempt_id="attempt", generation=1, owner_id=lease.owner_id, owner_epoch=1
    )
    reservation = GenerationReservation(
        model_calls=model_calls, model_tokens=1000, cost_ceiling_usd=0.0, runtime_allowance_seconds=float(runtime)
    )
    scope = dict(database="neo4j", deployment_id="dep", workspace_id="ws")
    principal = dict(principal="creator", **scope, expires_at=time.time() + 120, revoked=False)
    run = SimpleNamespace(
        run_id="run",
        operation_id="operation",
        contract_json=canonical_json(request),
        state="pending",
        phase="generation",
        version=1,
    )
    attempt = SimpleNamespace(
        fence=fence,
        registration=None,
        contract_json=run.contract_json,
        authorization=None,
        reservation=None,
        admitted_at=time.time(),
        released_at=None,
        released=False,
        receipt=None,
        cleanup=None,
        reconciliation_reason=None,
    )
    state = SimpleNamespace(db_down=False, read_expired=False)

    class Store:
        owner = SimpleNamespace(owner_id=fence.owner_id, owner_epoch=fence.owner_epoch, dirty=True)
        dependency_instances = {}
        database = scope["database"]

        def get_run(self, run_id):
            if state.db_down:
                raise OSError("private-db-detail")
            return run

        def reserve_generation(self, run_id, version, decision, auth, reserved, **kwargs):
            assert reserved.runtime_allowance_seconds <= request.budget.per_operation_timeout_seconds
            attempt.authorization = auth
            attempt.reservation = reserved
            return "intent"

        def get_owner(self):
            self.get_run("run")
            return self.owner

        def retire_owner(self, owner_id, epoch):
            self.get_run("run")
            assert (owner_id, epoch) == (fence.owner_id, fence.owner_epoch)
            assert attempt.receipt is not None and attempt.cleanup is not None
            self.owner.dirty = False
            return True

        def begin_owner(self, *args):
            return 1

        def claim_intent(self, *args):
            return fence

        def register_worker(self, fence, registration):
            attempt.registration = registration

        def release_attempt(self, *args, **kwargs):
            attempt.released = True
            attempt.released_at = time.time()
            return True

        def get_attempt(self, fence):
            self.get_run("run")
            return attempt

        def commit_generation_receipt(self, fence, receipt):
            self.get_run("run")
            attempt.receipt = receipt
            run.state, run.phase = "running", "validation"

        def acknowledge_cleanup(self, fence, evidence):
            self.get_run("run")
            attempt.cleanup = evidence
            if run.state == "cancel_requested":
                run.state = "cancelled"

        def mark_reconciliation_required(self, fence, reason):
            self.get_run("run")
            attempt.reconciliation_reason = reason

        def request_cancel(self, *args):
            self.get_run("run")
            run.state = "cancel_requested"

    gate = DependencyGate(
        lambda r, t: DependencyResult(r.dependency_id, "passed", r.profile_sha256, profile_id=r.profile_id)
    )
    store = Store()
    store.scope = {k: v for k, v in scope.items() if k != "database"}
    grants = ExecutionGrants(clock=time.time)
    authority = ForegroundAuthority(
        **scope,
        store=store,
        grants=grants,
        clock=time.time,
        principal_lookup=lambda p: principal if p == "creator" and not state.read_expired else None,
        profiles={profile["profile_id"]: profile},
        current_config=lambda p: dict(config=config, expires_at=principal["expires_at"]),
    )
    authority.bind_run(
        "creator",
        run.operation_id,
        request,
        run_id="run",
        catalogue_sha256=fixture_packet["inputs"]["execution_catalogue_sha256"],
    )
    service = WorkflowService(store, authority, gate, validate_support=lambda r: None)
    coordinator = GenerationCoordinator(
        store,
        authority,
        gate,
        worker,
        run_id="run",
        principal="creator",
        lease=lease,
        readiness_clock=ReadinessClock.capture(),
        workflow_service=service,
    )
    artifacts = GenerationArtifacts(
        ArtifactArea.create(private / "artifacts", store_id="store", registry_id="registry")
    )
    handle = (
        coordinator.dispatch("creator", expected_version=1, decision_id="decision", reservation=reservation)
        if dispatch
        else None
    )
    return SimpleNamespace(**locals())


def _validate_document(text):
    from isaaclab_arena.agentic_environment_generation.workbench.document_yaml import parse_yaml, reject_unknown_fields
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    document = parse_yaml(text)
    reject_unknown_fields(document)
    spec = ArenaEnvGraphSpec.from_dict(document)
    return {"valid": True, "spec": spec.model_dump(mode="json")}


def _sdk_evidence(prepared):
    return json.loads(Path(f"/evidence/generation-child-{prepared.owned_handle.process.pid}-sdk.json").read_text())


def test_foreground_committed_cap_one_stops_after_ping(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import \
        ForegroundGenerationReceiver

    c = _foreground_composition(tmp_path, model_calls=1)
    receiver = ForegroundGenerationReceiver(
        c.worker,
        c.coordinator,
        c.lease,
        c.artifacts,
        validate_document=_validate_document,
        protect=c.authority.protect_public,
    )
    try:
        with pytest.raises(RuntimeError, match="reconciliation"):
            receiver.receive("creator", c.handle.prepared)
        assert c.attempt.reservation.model_calls == 1
        assert c.attempt.admitted_at <= c.attempt.released_at
        assert c.request.budget.max_model_calls > c.attempt.reservation.model_calls
        sdk = _sdk_evidence(c.handle.prepared)
        assert sdk["calls"] == 1 and sdk["responses"] == [{"ordinal": 1, "kind": "ping"}]
        assert receiver.receipt is None and c.attempt.receipt is None
        assert c.worker.cleanup_verified(c.handle.prepared.registration, c.handle.cleanup)
        assert c.handle.reconciliation_required
        replay = c.coordinator.dispatch(
            "creator", expected_version=1, decision_id="decision", reservation=c.reservation
        )
        assert replay is c.handle and _sdk_evidence(c.handle.prepared) == sdk
        c.lease.require_held("run", "creator")
    finally:
        c.worker.stop_owned(c.handle.prepared, timeout_s=3)


def test_foreground_receiver_retains_then_completes_and_releases(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import \
        ForegroundGenerationReceiver

    c = _foreground_composition(tmp_path)
    validated = []

    def validate(text):
        validated.append(text)
        return _validate_document(text)

    receiver = ForegroundGenerationReceiver(
        c.worker, c.coordinator, c.lease, c.artifacts, validate_document=validate, protect=c.authority.protect_public
    )
    try:
        result = receiver.receive("creator", c.handle.prepared)
        assert result.disposition == "validation" and c.run.state != "accepted"
        assert c.store.get_owner().dirty is False, "retire durable owner before flock release"
        files = c.artifacts.verified_bytes(receiver.receipt, protect=lambda value: None)
        metadata = json.loads(files["provenance.json"])["producer_metadata"]
        assert metadata["prior_snapshot"] and metadata["warnings"]
        assert validated and c.worker.cleanup_verified(c.handle.prepared.registration, c.handle.cleanup)
        assert c.attempt.reservation.model_calls == 2
        assert c.attempt.admitted_at <= c.attempt.released_at
        sdk = _sdk_evidence(c.handle.prepared)
        assert sdk["calls"] == 2 and [r["kind"] for r in sdk["responses"]] == ["ping", "completion"]
        from isaaclab_arena.agentic_environment_generation.workflow.validation import validate_generation_candidate

        schema = validate_generation_candidate(c.artifacts, receiver.receipt, protect=c.authority.protect_public)
        assert schema.disposition == "schema_validated"
        assert schema.physical_validity == schema.task_validity == "not_established"
        with pytest.raises(ValueError, match="unavailable"):
            c.lease.require_held("run", "creator")
    finally:
        c.worker.stop_owned(c.handle.prepared, timeout_s=3)


def test_foreground_receiver_can_retain_lease_for_later_stages(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import \
        ForegroundGenerationReceiver

    c = _foreground_composition(tmp_path)
    receiver = ForegroundGenerationReceiver(
        c.worker,
        c.coordinator,
        c.lease,
        c.artifacts,
        validate_document=_validate_document,
        protect=c.authority.protect_public,
    )
    try:
        result = receiver.receive("creator", c.handle.prepared, release_lease=False)
        assert result.disposition == "validation" and c.store.get_owner().dirty
        c.lease.require_held("run", "creator")
        c.lease.retire_and_release(c.store, c.handle.prepared.registration, c.handle.cleanup)
    finally:
        c.worker.stop_owned(c.handle.prepared, timeout_s=3)


def test_foreground_retirement_uncertainty_retains_flock(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import \
        ForegroundGenerationReceiver

    c = _foreground_composition(tmp_path)
    receiver = ForegroundGenerationReceiver(
        c.worker,
        c.coordinator,
        c.lease,
        c.artifacts,
        validate_document=_validate_document,
        protect=c.authority.protect_public,
    )

    def unavailable():
        raise OSError("synthetic retirement readback unavailable")

    monkeypatch.setattr(c.store, "get_owner", unavailable)
    with pytest.raises(RuntimeError, match="reconciliation"):
        receiver.receive("creator", c.handle.prepared)
    c.lease.require_held("run", "creator")
    assert c.attempt.receipt is not None and c.handle.cleanup is not None
    assert _sdk_evidence(c.handle.prepared)["calls"] == 2


def test_foreground_retained_result_same_owner_database_recovery(tmp_path, monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import \
        ForegroundGenerationReceiver

    c = _foreground_composition(tmp_path)
    receiver = ForegroundGenerationReceiver(
        c.worker,
        c.coordinator,
        c.lease,
        c.artifacts,
        validate_document=_validate_document,
        protect=c.authority.protect_public,
    )
    try:
        c.state.db_down = True
        with pytest.raises(RuntimeError, match="reconciliation"):
            receiver.receive("creator", c.handle.prepared)
        retained = receiver.receipt
        assert retained is not None and c.attempt.receipt is None
        assert c.handle.durable_reconciliation_pending
        assert c.worker.cleanup_verified(c.handle.prepared.registration, c.handle.cleanup)
        files = c.artifacts.verified_bytes(retained, protect=c.authority.protect_public)
        sdk = _sdk_evidence(c.handle.prepared)
        assert sdk["calls"] == 2
        c.lease.require_held("run", "creator")
        c.state.db_down = False
        monkeypatch.setattr(receiver, "_read", lambda owned: pytest.fail("retained result must not be reread"))
        monkeypatch.setattr(c.worker, "send", lambda *a, **k: pytest.fail("recovery must not send"))
        result = receiver.receive("creator", c.handle.prepared)
        assert result.disposition == "validation" and c.attempt.receipt == retained
        assert receiver.receipt is retained
        assert c.artifacts.verified_bytes(retained, protect=c.authority.protect_public) == files
        assert not c.handle.reconciliation_required and not c.handle.durable_reconciliation_pending
        assert _sdk_evidence(c.handle.prepared) == sdk and len(c.worker._owned) == 1
        with pytest.raises(ValueError, match="unavailable"):
            c.lease.require_held("run", "creator")
    finally:
        c.worker.stop_owned(c.handle.prepared, timeout_s=3)


@pytest.mark.parametrize("mode", ["production-wait", "production-resistant", "production-result"])
def test_foreground_failure_stops_without_read_grant_or_database(tmp_path, mode):
    from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import \
        ForegroundGenerationReceiver

    c = _foreground_composition(tmp_path, mode, runtime=4)
    c.state.db_down = c.state.read_expired = True
    receiver = ForegroundGenerationReceiver(
        c.worker,
        c.coordinator,
        c.lease,
        c.artifacts,
        validate_document=lambda text: {"valid": True},
        protect=lambda value: None,
    )
    with pytest.raises(RuntimeError, match="reconciliation"):
        receiver.receive("creator", c.handle.prepared)
    assert c.handle.cleanup is not None
    assert c.handle.reconciliation_required and c.handle.durable_reconciliation_pending
    assert c.worker.cleanup_verified(c.handle.prepared.registration, c.handle.cleanup)
    assert receiver.receipt is None and c.run.state != "cancelled"
    c.lease.require_held("run", "creator")
    with pytest.raises(ValueError, match="authority unavailable"):
        c.coordinator.cancel("creator")


def _wait_evidence(prepared, suffix, timeout=10):
    import time

    path = Path(f"/evidence/generation-child-{prepared.owned_handle.process.pid}-{suffix}.json")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text())
        time.sleep(0.02)
    raise TimeoutError("Fixed child startup witness missing")


def test_foreground_cancel_waiting_before_release_has_zero_sdk_calls(tmp_path, monkeypatch):
    c = _foreground_composition(tmp_path, dispatch=False)
    prepare = c.worker.prepare
    waiting = []

    def cancel_waiting(*args, **kwargs):
        prepared = prepare(*args, **kwargs)
        waiting.append(prepared)
        assert _wait_evidence(prepared, "sdk")["calls"] == 0
        stopped = c.coordinator.cancel("creator")
        assert stopped.cleanup_pending
        return prepared

    monkeypatch.setattr(c.worker, "prepare", cancel_waiting)
    try:
        handle = c.coordinator.dispatch(
            "creator", expected_version=1, decision_id="decision", reservation=c.reservation
        )
        assert handle.prepared is waiting[0]
        assert not c.attempt.released and c.attempt.released_at is None
        assert not handle.prepared.owned_handle.attempted
        assert _sdk_evidence(handle.prepared)["calls"] == 0
        assert c.worker.cleanup_verified(handle.prepared.registration, handle.cleanup)
        stopped = c.coordinator.cancel("creator")
        assert not stopped.cleanup_pending and not stopped.durable_cancellation_pending
        assert c.run.state == "cancelled"
        c.lease.release_after_cleanup(handle.prepared.registration, handle.cleanup)
    finally:
        for prepared in waiting:
            c.worker.stop_owned(prepared, timeout_s=3)


def test_foreground_ambiguous_write_never_retries(tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete

    c = _foreground_composition(tmp_path, dispatch=False)
    send = c.worker.send
    writes = []
    packet = []

    def ambiguous_send(prepared, envelope, **kwargs):
        packet.append(envelope)
        native_write = os.write
        fd = prepared.owned_handle.process.stdin.fileno()

        def lost_ack(target, data):
            count = native_write(target, data)
            if target == fd:
                writes.append(count)
                assert count == len(envelope)
                _wait_evidence(prepared, "final", timeout=20)
                raise OSError("synthetic lost write acknowledgement")
            return count

        with monkeypatch.context() as patch:
            patch.setattr(os, "write", lost_ack)
            send(prepared, envelope, **kwargs)

    monkeypatch.setattr(c.worker, "send", ambiguous_send)
    with pytest.raises(DispatchIncomplete) as failed:
        c.coordinator.dispatch("creator", expected_version=1, decision_id="decision", reservation=c.reservation)
    handle = failed.value.handle
    try:
        assert len(writes) == 1 and c.attempt.released
        assert handle.reconciliation_required and handle.incomplete
        assert c.worker.cleanup_verified(handle.prepared.registration, handle.cleanup)
        sdk = _sdk_evidence(handle.prepared)
        assert sdk["calls"] == 2
        replay = c.coordinator.dispatch(
            "creator", expected_version=1, decision_id="decision", reservation=c.reservation
        )
        assert replay is handle and len(c.worker._owned) == len(writes) == 1
        with pytest.raises(RuntimeError, match="already attempted"):
            send(handle.prepared, packet[0], timeout_s=1)
        assert _sdk_evidence(handle.prepared) == sdk
        c.lease.require_held("run", "creator")
    finally:
        c.worker.stop_owned(handle.prepared, timeout_s=3)


@pytest.mark.parametrize("fault", ["before_identity", "after_identity"])
def test_foreground_postspawn_group_init_failure_retains_exact_handle(tmp_path, monkeypatch, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete, PreparedWorker
    from isaaclab_arena_examples.agentic_environment_generation import foreground_generation as adapter

    c = _foreground_composition(tmp_path, "production-wait", dispatch=False)
    initialize = adapter.OwnedProcessGroup.__init__
    captured = []

    def fail_after_init(group, pid):
        if captured:
            return initialize(group, pid)
        owned = c.worker._owned[-1]
        captured.append((owned, group))
        _wait_evidence(PreparedWorker(None, owned), "preimport")
        if fault == "after_identity":
            initialize(group, pid)
        raise OSError("synthetic postspawn group initialization failure")

    monkeypatch.setattr(adapter.OwnedProcessGroup, "__init__", fail_after_init)
    with pytest.raises(DispatchIncomplete) as failed:
        c.coordinator.dispatch("creator", expected_version=1, decision_id="decision", reservation=c.reservation)
    handle = failed.value.handle
    owned, group = captured[0]
    assert handle.prepared.owned_handle is owned and owned.group is group
    # Retry exact local cleanup too; never fabricate a missing registration.
    try:
        with pytest.raises(RuntimeError, match="without registration"):
            c.worker.stop_owned(handle.prepared, timeout_s=3)
        assert owned.process.poll() is not None and group.cleaned and not group.members()
        assert owned.pidfd is None, "physically stopped unregistered worker must close its retained pidfd"
        assert not c.worker.cleanup_verified(None, None), "missing registration/evidence cannot prove cleanup"
    finally:
        if not hasattr(group, "witnesses"):
            initialize(group, owned.process.pid)
        group.stop(term_timeout=0.1, kill_timeout=2)
        owned.process.wait(timeout=3)

    assert handle.cleanup_pending and handle.cleanup is None and not c.attempt.released
    c.lease.require_held("run", "creator")


@pytest.mark.parametrize("fault", ["pidfd", "identity", "timer"])
def test_foreground_postspawn_other_initialization_failures(tmp_path, monkeypatch, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete, PreparedWorker
    from isaaclab_arena_examples.agentic_environment_generation import foreground_generation as adapter

    c = _foreground_composition(tmp_path, "production-wait", dispatch=False)
    captured = []
    target, attribute = {
        "pidfd": (adapter.os, "pidfd_open"),
        "identity": (adapter, "process_identity"),
        "timer": (c.worker, "_arm"),
    }[fault]
    original = getattr(target, attribute)

    def fail_once(*args, **kwargs):
        if captured:
            return original(*args, **kwargs)
        owned = c.worker._owned[-1]
        captured.append(owned)
        _wait_evidence(PreparedWorker(owned.registration, owned), "preimport")
        raise OSError("synthetic postspawn initialization failure")

    monkeypatch.setattr(target, attribute, fail_once)
    with pytest.raises(DispatchIncomplete) as failed:
        c.coordinator.dispatch("creator", expected_version=1, decision_id="decision", reservation=c.reservation)
    handle = failed.value.handle
    assert handle.prepared.owned_handle is captured[0]
    owned = captured[0]
    assert owned.group.cleaned and not owned.group.members() and owned.process.poll() is not None
    assert owned.pidfd is None and not owned.attempted and not c.attempt.released
    if fault == "timer":
        assert c.worker.cleanup_verified(handle.prepared.registration, handle.cleanup)
        c.lease.release_after_cleanup(handle.prepared.registration, handle.cleanup)
    else:
        assert handle.prepared.registration is None and handle.cleanup is None and handle.cleanup_pending
        c.lease.require_held("run", "creator")


def test_foreground_prepare_based_deadline_stops_without_receiver_or_database(tmp_path, monkeypatch):
    import time

    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import PreparedWorker

    c = _foreground_composition(tmp_path, "production-resistant", runtime=4, dispatch=False)
    release = c.store.release_attempt

    def delayed_release(*args, **kwargs):
        owned = c.worker._owned[-1]
        _wait_evidence(PreparedWorker(owned.registration, owned), "preimport")
        time.sleep(0.4)
        return release(*args, **kwargs)

    monkeypatch.setattr(c.store, "release_attempt", delayed_release)
    handle = c.coordinator.dispatch("creator", expected_version=1, decision_id="decision", reservation=c.reservation)
    owned = handle.prepared.owned_handle
    try:
        assert owned.deadline <= owned.started + c.attempt.reservation.runtime_allowance_seconds
        c.state.db_down = c.state.read_expired = True
        _wait_evidence(handle.prepared, "descendant", timeout=4)
        owned.process.wait(timeout=6)
        owned.timer.join(timeout=3)
        assert not owned.timer.is_alive()
        assert owned.cleanup is not None and c.worker.cleanup_verified(handle.prepared.registration, owned.cleanup)
        assert owned.group.cleaned and not owned.group.members()
        assert time.monotonic() - owned.started < 8
        result = c.coordinator.fail_owned(handle.prepared)
        assert result.durable_reconciliation_pending and not result.cleanup_pending
        assert c.run.state != "cancelled"
        c.lease.require_held("run", "creator")
    finally:
        c.worker.stop_owned(handle.prepared, timeout_s=3)


@pytest.mark.parametrize("phase", ["late_identity", "waiting_for_release"])
def test_foreground_bounded_startup_before_send(tmp_path, monkeypatch, phase):
    import time

    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import PreparedWorker, PrepareFailed
    from isaaclab_arena_examples.agentic_environment_generation import foreground_generation as adapter

    c = _foreground_composition(tmp_path, "production-wait", dispatch=False)
    identity = adapter.process_identity
    c.lease.mark_prepared(c.fence)

    def delayed_identity(pid):
        _wait_evidence(PreparedWorker(None, c.worker._owned[-1]), "preimport")
        time.sleep(0.1)
        return identity(pid)

    started = time.monotonic()
    if phase == "late_identity":
        monkeypatch.setattr(adapter, "process_identity", delayed_identity)
        with pytest.raises(PrepareFailed) as failed:
            c.worker.prepare(c.fence, c.request, timeout_s=0.05)
        prepared = failed.value.prepared
    else:
        prepared = c.worker.prepare(c.fence, c.request, timeout_s=0.5)
        _wait_evidence(prepared, "preimport")
    try:
        owned = prepared.owned_handle
        assert prepared.registration.fence == c.fence and owned is c.worker._owned[0]
        if phase == "waiting_for_release":
            c.state.db_down = c.state.read_expired = True
            owned.process.wait(timeout=3)
            owned.timer.join(timeout=3)
            assert owned.cleanup is not None and not owned.timer.is_alive()
        evidence = c.worker.stop_owned(prepared, timeout_s=3)
        assert c.worker.cleanup_verified(prepared.registration, evidence)
        assert not owned.attempted and not c.attempt.released
        assert time.monotonic() - started < 4
        c.lease.release_after_cleanup(prepared.registration, evidence)
    finally:
        c.worker.stop_owned(prepared, timeout_s=3)


def test_foreground_cancel_after_release_keeps_cancel_distinct(tmp_path):
    import time

    c = _foreground_composition(tmp_path, "production-wait")
    witness = Path(f"/evidence/generation-child-{c.handle.prepared.registration.pid}-preimport.json")
    deadline = time.monotonic() + 5
    while not witness.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert witness.exists()
    result = c.coordinator.cancel("creator")
    assert not result.cleanup_pending and not result.durable_cancellation_pending
    assert c.run.state == "cancelled" and c.handle.completion_receipt is None
    c.lease.release_after_cleanup(c.handle.prepared.registration, c.handle.cleanup)


def test_fixed_child_preimport_and_result():
    import generation_worker_fixture as fixture

    args, kwargs = fixture.spawn_spec("result")
    proc = subprocess.Popen(args, **kwargs)
    stdout, stderr = proc.communicate(b"release\n", timeout=15)
    assert proc.returncode == 0, stderr
    assert json.loads(stdout) == {"result": {"fixture": "fixed-result"}}
    proof = json.loads(Path(f"/evidence/generation-child-{proc.pid}-preimport.json").read_text())
    assert proof["identity"]["pid"] == proc.pid
    assert proof["pgid"] == proof["sid"] == proc.pid
    assert proof["preimport"]["before_repository_imports"] is True
    assert proof["source_sha256"][fixture.WORKER]
    assert proof["parent_pid"] == os.getpid()
    assert proof["identity"]["pid_namespace"] == os.readlink("/proc/self/ns/pid")
    assert proof["forbidden"] == dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), 0)


def test_alternate_launch_inputs_rejected_without_spawn():
    import generation_worker_fixture as fixture

    args, kwargs = fixture.spawn_spec("result")
    for changed_args, changed_kwargs in (
        ([args[0], "-c", "pass"], kwargs),
        ([args[0], "/private/worker.py", "result"], kwargs),
        (args, {**kwargs, "env": {**kwargs["env"], "INJECT": "1"}}),
        (args, {**kwargs, "cwd": "/private"}),
        (args, {**kwargs, "start_new_session": False}),
        (args, {**kwargs, "pass_fds": (1,)}),
        (args, {**kwargs, "preexec_fn": lambda: None}),
        (args, {**kwargs, "close_fds": 1}),
        (args, {**kwargs, "start_new_session": 1}),
        (args, {**kwargs, "stdin": True}),
    ):
        with pytest.raises(ValueError, match="fixed generation"):
            subprocess.Popen(changed_args, **changed_kwargs)
    with pytest.raises(ValueError):
        fixture.spawn_spec("arbitrary.module")


def test_unbound_source_manifest_rejected():
    import generation_worker_fixture as fixture

    with pytest.raises(AssertionError, match="source manifest"):
        fixture.verify_sources({})
    manifest = fixture.verify_sources()
    manifest[fixture.WORKER] = "0" * 64
    with pytest.raises(AssertionError, match="source manifest"):
        fixture.verify_sources(manifest)


@pytest.mark.parametrize("mode", ["wait", "resistant"])
def test_owned_group_timeout_and_resistant_descendant(mode):
    import generation_worker_fixture as fixture

    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import OwnedProcessGroup

    args, kwargs = fixture.spawn_spec(mode)
    proc = subprocess.Popen(args, **kwargs)
    owner = OwnedProcessGroup(proc.pid)
    try:
        ready = json.loads(proc.stdout.readline())
        assert ready["ready"] == proc.pid
        if mode == "resistant":
            assert ready["descendant"] in owner.members()
        with pytest.raises(subprocess.TimeoutExpired):
            proc.wait(timeout=0.05)
        owner.stop(term_timeout=0.1, kill_timeout=2)
        assert owner.cleaned and not owner.members()
        proc.wait(timeout=3)
        Path(f"/evidence/generation-cleanup-{proc.pid}.json").write_text(
            json.dumps(
                {
                    "pid": proc.pid,
                    "mode": mode,
                    "cleaned": owner.cleaned,
                    "members": owner.witnesses,
                    "returncode": proc.returncode,
                }
            )
        )
    finally:
        owner.stop(term_timeout=0.1, kill_timeout=2)
        proc.communicate(timeout=3)


@pytest.mark.parametrize(
    "mode, packet, expected_exit",
    [
        ("production", {}, 1),
        ("production-result", {"inputs": {}, "config": {}}, 0),
    ],
)
def test_actual_generation_worker_entry(mode, packet, expected_exit):
    import generation_worker_fixture as fixture

    args, kwargs = fixture.spawn_spec(mode)
    proc = subprocess.Popen(args, **kwargs)
    stdout, stderr = proc.communicate(json.dumps(packet).encode() + b"\n", timeout=20)
    assert proc.returncode == expected_exit, stderr
    messages = [json.loads(line) for line in stdout.splitlines()]
    assert messages
    if expected_exit == 0:
        assert messages[-1] == {"result": {"fixture": "fixed-result"}}
    else:
        assert "error" in messages[-1]


def test_spawn_count_bound_and_unarmed_audit():
    from types import SimpleNamespace

    import generation_worker_fixture as fixture
    from api import make_profile

    counts = dict.fromkeys(("network", "provider", "graph", "render", "workload", "subprocess"), 0)
    gate = fixture.SpawnGate(counts)
    args, kwargs = fixture.spawn_spec("result")
    with pytest.raises(RuntimeError, match="subprocess"):
        gate.audit("subprocess.Popen", (args[0], args, "/source", kwargs["env"]))
    assert counts["subprocess"] == 1
    gate.launches.extend({} for _ in range(fixture.MAX_LAUNCHES))
    with pytest.raises(ValueError, match="bounded fixed generation"):
        gate.popen(args, **kwargs)
    profile = make_profile(counts)
    frame = SimpleNamespace(
        f_globals={"__name__": "synthetic"},
        f_code=SimpleNamespace(co_name="__init__"),
        f_locals={"self": type("InferenceBackend", (), {})()},
    )
    with pytest.raises(RuntimeError, match="provider"):
        profile(frame, "call", None)
    assert counts["provider"] == 1


def _restart_owner(mode):
    """Fixed entry; test-owned persisted synthetic store, not Neo4j."""
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (AttemptFence, AuthorizationSnapshot,
                                                                                 WorkerRegistration)
    from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence, OwnerView
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
    from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import \
        ForegroundGenerationReceiver
    from isaaclab_arena_examples.agentic_environment_generation.foreground_recovery import (
        ForegroundGenerationRecovery, OwnershipArtifacts)

    live = mode in {"restart-old-live", "restart-live-missing", "restart-live-cancel"}
    root = Path("/private/restart-live" if live else "/private/restart")
    snapshot = root / "synthetic-store.json"
    if mode in {"restart-old", "restart-old-live"}:
        root.mkdir(mode=0o700)
        c = _foreground_composition(root, "production-orphan" if live else "production-sdk", dispatch=False)
        c.worker._ownership_artifacts = OwnershipArtifacts(c.artifacts.area)
        c.handle = c.coordinator.dispatch(
            "creator", expected_version=1, decision_id="decision", reservation=c.reservation
        )
        receiver = ForegroundGenerationReceiver(
            c.worker,
            c.coordinator,
            c.lease,
            c.artifacts,
            validate_document=_validate_document,
            protect=c.authority.protect_public,
        )
        if live:
            branch = _wait_evidence(c.handle.prepared, "descendant")
            assert branch["descendant"] in c.handle.prepared.owned_handle.group.members()
            assert c.handle.prepared.owned_handle.process.poll() is None
            # Deliberately exit without stop or durable cleanup. The leader is
            # still the recovery anchor; this is NOT member-only recovery.
            sdk = {"calls": 0}
        else:
            c.state.db_down = True
            with pytest.raises(RuntimeError, match="reconciliation"):
                receiver.receive("creator", c.handle.prepared)
            assert receiver.receipt is not None and c.attempt.receipt is None
            assert c.worker.cleanup_verified(c.handle.prepared.registration, c.handle.cleanup)
            sdk = _sdk_evidence(c.handle.prepared)
        data = dict(
            scope="synthetic store snapshot only",
            old_pid=os.getpid(),
            run=vars(c.run),
            fence=c.fence.model_dump(mode="json"),
            registration=c.attempt.registration.model_dump(mode="json"),
            authorization=c.attempt.authorization.model_dump(mode="json"),
            sdk=sdk,
        )
        with snapshot.open("x") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        return {"old_pid": os.getpid(), "sdk_calls": data["sdk"]["calls"]}
    data = json.loads(snapshot.read_text())
    assert data["old_pid"] != os.getpid()
    fence = AttemptFence.model_validate(data["fence"])
    run = SimpleNamespace(**data["run"])
    if mode in {"restart-cancel", "restart-live-cancel"}:
        run.state = "cancel_requested"
    attempt = SimpleNamespace(
        fence=fence,
        registration=WorkerRegistration.model_validate(data["registration"]),
        authorization=AuthorizationSnapshot.model_validate(data["authorization"]),
        contract_json=run.contract_json,
        receipt=None,
        cleanup=CleanupEvidence.model_validate(data["cleanup"]) if data.get("cleanup") else None,
        released=True,
    )

    class Store:
        owner = OwnerView(owner_id=fence.owner_id, owner_epoch=fence.owner_epoch, dirty=True)

        def get_run(self, run_id):
            assert run_id == fence.run_id
            return run

        def mark_reconciliation_required(self, expected, reason):
            assert expected == fence and self.owner.dirty
            attempt.reconciliation_reason = reason

        def get_generation_attempt(self, run_id):
            self.get_run(run_id)
            return attempt

        def get_attempt(self, expected):
            assert expected == fence
            return attempt

        def get_owner(self):
            return self.owner

        def commit_generation_receipt(self, expected, receipt):
            assert expected == fence and self.owner.dirty
            attempt.receipt = receipt
            run.state, run.phase = "running", "validation"

        def acknowledge_cleanup(self, expected, evidence):
            assert expected == fence and self.owner.dirty
            attempt.cleanup = evidence
            if run.state == "cancel_requested":
                run.state = "cancelled"

        def retire_owner(self, owner, epoch):
            assert (owner, epoch) == (fence.owner_id, fence.owner_epoch)
            assert (attempt.receipt is not None or run.state == "cancelled") and attempt.cleanup is not None
            self.owner = self.owner.model_copy(update={"dirty": False})
            return True

    class ReadAuthority:
        def require_read(self, principal):
            assert principal == "creator"

    store = Store()
    service = WorkflowService(store, ReadAuthority(), None, validate_support=lambda c: None)
    area = ArtifactArea.open(root / "private/artifacts", store_id="store", registry_id="registry")
    recovery = ForegroundGenerationRecovery(
        root / "private",
        run_id="run",
        principal="creator",
        service=service,
        ownership_artifacts=OwnershipArtifacts(area),
        artifacts=GenerationArtifacts(area),
        protect=lambda value: None,
    )
    if mode == "restart-locality":
        from unittest.mock import patch

        from isaaclab_arena_examples.agentic_environment_generation import foreground_recovery as module

        with (
            patch.object(module, "boot_id", return_value="foreign-boot"),
            patch.object(module, "OwnedProcessGroup") as group,
        ):
            with pytest.raises(ValueError, match="locality"):
                recovery.recover()
            group.assert_not_called()
        readlink = module.os.readlink
        with (
            patch.object(
                module.os,
                "readlink",
                side_effect=lambda path: "pid:[foreign]" if str(path) == "/proc/self/ns/pid" else readlink(path),
            ),
            patch.object(module, "OwnedProcessGroup") as group,
        ):
            with pytest.raises(ValueError, match="locality"):
                recovery.recover()
            group.assert_not_called()
        from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactError

        witness = next((root / "private/artifacts/final/foreground-ownership").glob("*/ownership.json"))
        original = witness.read_bytes()
        try:
            witness.write_bytes(original + b" ")
            with patch.object(module, "OwnedProcessGroup") as group:
                with pytest.raises(ArtifactError):
                    recovery.recover()
                group.assert_not_called()
        finally:
            witness.write_bytes(original)
        recovery.lease.require_held("run", "creator")
        return {"blocked": True, "sdk_calls": 0}
    if mode in {"restart-missing", "restart-live-missing"}:
        from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactError

        live_before = None
        if live:
            from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import group_members

            members = group_members(attempt.registration.pid)
            live_before = {pid: member for pid, member in members.items() if member["state"] not in {"Z", "X"}}
            branch = json.loads(
                Path(f"/evidence/generation-child-{attempt.registration.pid}-descendant.json").read_text()
            )
            assert attempt.registration.pid in live_before and branch["descendant"] in live_before
            assert live_before[attempt.registration.pid]["start_ticks"] == str(attempt.registration.start_ticks)
        with pytest.raises((ArtifactError, RuntimeError)):
            recovery.recover()
        assert attempt.receipt is None and store.owner.dirty
        assert attempt.reconciliation_reason == "released_without_receipt"
        assert attempt.cleanup is not None, "trusted physical cleanup must survive missing result"
        assert attempt.cleanup.registration == attempt.registration
        if live:
            snapshot_data = dict(data, cleanup=attempt.cleanup.model_dump(mode="json"))
            with snapshot.open("w") as stream:
                json.dump(snapshot_data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            assert json.loads(snapshot.read_text())["cleanup"] == snapshot_data["cleanup"]
            assert recovery._group.cleaned and not recovery._group.members()
            return {
                "blocked": True,
                "sdk_calls": 0,
                "cleanup": snapshot_data["cleanup"],
                "new_pid": os.getpid(),
                "old_pid": data["old_pid"],
                "leader_anchor": True,
                "live_before": live_before,
                "live_after": [],
            }
        recovery.lease.require_held("run", "creator")
        return {"blocked": True, "sdk_calls": 0}
    result = recovery.recover()
    assert (
        result.disposition == ("cancelled" if mode in {"restart-cancel", "restart-live-cancel"} else "validation")
        and not store.owner.dirty
    )
    with pytest.raises(ValueError, match="unavailable"):
        recovery.lease.require_held("run", "creator")
    if mode == "restart-new":
        from unittest.mock import patch

        from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import SafeBusy

        promote = area.promote

        def require_locked_promotion(*args, **kwargs):
            with pytest.raises(SafeBusy, match="writer busy"), area.writer_lock():
                pass
            return promote(*args, **kwargs)

        with patch.object(area, "promote", require_locked_promotion):
            OwnershipArtifacts(area).load(attempt.registration)
        retained_receipt, retained_cleanup = attempt.receipt, attempt.cleanup
        for dirty in (True, False, False):
            store.owner = store.owner.model_copy(update={"dirty": dirty})
            replay = ForegroundGenerationRecovery(
                root / "private",
                run_id="run",
                principal="creator",
                service=service,
                ownership_artifacts=OwnershipArtifacts(area),
                artifacts=GenerationArtifacts(area),
                protect=lambda value: None,
            )
            with (
                patch.object(
                    store, "commit_generation_receipt", side_effect=AssertionError("settled receipt mutation")
                ),
                patch.object(store, "acknowledge_cleanup", side_effect=AssertionError("settled cleanup mutation")),
                patch.object(
                    store, "mark_reconciliation_required", side_effect=AssertionError("settled reconciliation mutation")
                ),
            ):
                repeated = replay.recover()
            assert repeated.disposition == "validation"
            assert attempt.receipt == retained_receipt and attempt.cleanup == retained_cleanup
            assert not store.owner.dirty

        def reopen():
            return ForegroundGenerationRecovery(
                root / "private",
                run_id="run",
                principal="creator",
                service=service,
                ownership_artifacts=OwnershipArtifacts(area),
                artifacts=GenerationArtifacts(area),
                protect=lambda value: None,
            )

        from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactError
        from isaaclab_arena_examples.agentic_environment_generation import foreground_recovery as module

        retired = store.owner
        replacement = retired.model_copy(
            update={"owner_id": "owner-B", "owner_epoch": retired.owner_epoch + 1, "dirty": True}
        )
        store.owner = replacement
        blocked = reopen()
        with patch.object(module, "OwnedProcessGroup") as group:
            with pytest.raises(ValueError, match="Original registered owner"):
                blocked.recover()
            group.assert_not_called()
        assert store.owner == replacement and store.owner.dirty
        blocked.lease.release_never_prepared()
        historical = reopen()
        with (
            patch.object(store, "get_retired_owner", create=True, return_value=retired) as retirement,
            patch.object(store, "commit_generation_receipt", side_effect=AssertionError("historical receipt mutation")),
            patch.object(store, "acknowledge_cleanup", side_effect=AssertionError("historical cleanup mutation")),
            patch.object(store, "retire_owner", side_effect=AssertionError("replacement retirement")),
            patch.object(module, "OwnedProcessGroup") as group,
        ):
            historical_result = historical.recover()
            retirement.assert_called_once_with(fence.owner_id)
            group.assert_not_called()
        assert historical_result.disposition == "validation"
        assert historical_result.attempt.receipt == retained_receipt
        assert historical_result.attempt.cleanup == retained_cleanup
        assert store.owner == replacement and store.owner.dirty
        with pytest.raises(ValueError, match="unavailable"):
            historical.lease.require_held("run", "creator")
        store.owner = retired

        cancelled_replay = reopen()

        def cancel_during_protection(value):
            run.state = "cancelled"

        cancelled_replay._protect = cancel_during_protection
        # Real store reads return detached snapshots, unlike this fixture's mutable run.
        with patch.object(store, "get_run", side_effect=lambda run_id: SimpleNamespace(**vars(run))):
            assert cancelled_replay.recover().disposition == "cancelled"
        run.state = "running"

        blocked = reopen()
        attempt.cleanup = None
        with pytest.raises(ValueError, match="cleanup unresolved"):
            blocked.recover()
        attempt.cleanup = retained_cleanup
        blocked.recover()

        # Known damaged receipts remain invalid even when cancellation is final.
        for dirty in (False, True):
            store.owner = retired.model_copy(update={"dirty": dirty})
            run.state = "cancelled"
            candidate = root / "private/artifacts" / retained_receipt.artifact_directory / "candidate.yaml"
            original = candidate.read_bytes()
            blocked = reopen()
            try:
                candidate.write_bytes(original + b" ")
                with pytest.raises(ArtifactError):
                    blocked.recover()
                blocked.lease.require_held("run", "creator")
                assert attempt.receipt == retained_receipt and attempt.cleanup == retained_cleanup
            finally:
                candidate.write_bytes(original)
            assert blocked.recover().disposition == "cancelled"
    return {
        "new_pid": os.getpid(),
        "old_pid": data["old_pid"],
        "sdk_calls": 0,
        "receipt": attempt.receipt.model_dump(mode="json") if attempt.receipt else None,
        "cleaned": attempt.cleanup is not None,
        "retired": not store.owner.dirty,
        "scope": data["scope"],
    }


def test_fresh_process_retained_generation_recovery():
    import generation_worker_fixture as fixture

    outputs = []
    for mode in ("restart-old", "restart-locality", "restart-missing", "restart-cancel", "restart-new"):
        args, kwargs = fixture.spawn_spec(mode)
        generation = Path("/private/restart/private/artifacts/final/generation")
        held = Path("/private/restart/held-generation")
        if mode in {"restart-missing", "restart-cancel"}:
            generation.rename(held)
        process = subprocess.Popen(args, **kwargs)
        stdout, stderr = process.communicate(timeout=28)
        if mode in {"restart-missing", "restart-cancel"}:
            held.rename(generation)
        assert process.returncode == 0, stderr.decode(errors="replace")
        outputs.append(json.loads(stdout))
    old, locality, missing, cancelled, new = outputs
    assert cancelled["retired"] and cancelled["cleaned"] and cancelled["receipt"] is None
    assert locality == missing == {"blocked": True, "sdk_calls": 0}
    assert old["old_pid"] == new["old_pid"] != new["new_pid"]
    assert old["sdk_calls"] == 2 and new["sdk_calls"] == 0
    assert new["retired"] and new["cleaned"]


def test_fresh_process_kills_live_leader_and_resistant_descendant():
    import generation_worker_fixture as fixture

    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import group_members

    assert "restart-old-live" in fixture.MODES, "fixed live-group restart mode required"
    outputs = []
    for mode in ("restart-old-live", "restart-live-missing", "restart-live-cancel"):
        args, kwargs = fixture.spawn_spec(mode)
        process = subprocess.Popen(args, **kwargs)
        stdout, stderr = process.communicate(timeout=28)
        assert process.returncode == 0, stderr.decode(errors="replace")
        outputs.append(json.loads(stdout))
        snapshot = json.loads(Path("/private/restart-live/synthetic-store.json").read_text())
        pid = snapshot["registration"]["pid"]
        members = group_members(pid)
        alive = {member for member, state in members.items() if state["state"] not in {"Z", "X"}}
        branch = json.loads(Path(f"/evidence/generation-child-{pid}-descendant.json").read_text())
        if mode == "restart-old-live":
            assert pid in alive and branch["descendant"] in alive
            assert snapshot.get("cleanup") is None
        else:
            assert not alive
            assert snapshot["cleanup"]["registration"] == snapshot["registration"]
        assert not Path(f"/evidence/generation-child-{pid}-sdk.json").exists()
    assert outputs[0]["sdk_calls"] == 0
    assert outputs[1]["blocked"] and outputs[1]["sdk_calls"] == 0
    assert outputs[1]["leader_anchor"] and not outputs[1]["live_after"]
    assert outputs[1]["new_pid"] != outputs[1]["old_pid"]
    assert outputs[1]["cleanup"]["registration"] == snapshot["registration"]
    assert outputs[2]["cleaned"] and outputs[2]["retired"] and outputs[2]["receipt"] is None
