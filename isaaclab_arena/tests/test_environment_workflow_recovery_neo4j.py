# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Real Neo4j + owned stdlib fixture child + fresh recovery object.

Actual authority/lease/coordinator/receiver/schema/artifacts/retirement; fixture
readiness and registered vocabulary, no SDK, generation engine or scene proof.
Fresh object recovery is not crashed-owner/fresh-interpreter recovery.
"""
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from neo4j import GraphDatabase

from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
from isaaclab_arena.agentic_environment_generation.workflow.artifacts import GenerationArtifacts
from isaaclab_arena.agentic_environment_generation.workflow.attempts import GenerationReservation
from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
from isaaclab_arena.agentic_environment_generation.workflow.coordinator import GenerationCoordinator
from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore
from isaaclab_arena.agentic_environment_generation.workflow.readiness import (
    DependencyGate,
    DependencyResult,
    ReadinessClock,
)
from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
from isaaclab_arena.tests.test_environment_workflow_service import contract
from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import (
    ForegroundAuthority,
    model_settings_sha256,
)
from isaaclab_arena_examples.agentic_environment_generation.foreground_generation import (
    ForegroundGenerationReceiver,
    ForegroundGenerationWorker,
)
from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
from isaaclab_arena_examples.agentic_environment_generation.foreground_recovery import (
    ForegroundGenerationRecovery,
    OwnershipArtifacts,
)
from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants


def test_real_neo4j_owned_fixture_generation_and_fresh_object_recovery(tmp_path, monkeypatch):
    import yaml

    import workflow_process_harness as harness

    from isaaclab_arena.assets import registries
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    # Fixed registry fixture: actual schema checks remain intact; no simulator imports.
    document = yaml.safe_load(Path("/source/" + harness.FIXTURE).read_text())
    monkeypatch.setattr(registries, "_assets_registered", True)
    for registry, names in (
        (
            registries.AssetRegistry(),
            [a["registry_name"] for a in [document["embodiment"], document["background"], *document["objects"]]],
        ),
        (registries.TaskRegistry(), [t["kind"] for t in document["task"]["subtasks"]]),
        (registries.ObjectRelationLibraryRegistry(), [r["kind"] for r in document["relations"]]),
    ):
        monkeypatch.setattr(
            registry,
            "_components",
            {name: type("Fixture", (), {"is_unary": staticmethod(lambda n=name: n == "is_anchor")}) for name in names},
        )

    def validate(text):
        spec = ArenaEnvGraphSpec.from_dict(yaml.safe_load(text))
        return {"valid": True, "spec": spec.model_dump(mode="json")}

    validate(Path("/source/" + harness.FIXTURE).read_text())
    config = {"api_key": "synthetic-unit-key-only", "model": "fixture", "base_url": "https://api.openai.com/v1"}
    profile = dict(
        profile_id="synthetic", billing="free", settings_sha256=model_settings_sha256(config, billing="free")
    )
    value = contract().model_dump(mode="json")
    value["execution"]["generation_model"] = profile
    value["budget"]["per_operation_timeout_seconds"] = 30.0
    request = type(contract()).model_validate(value)
    catalogue = hashlib.sha256(Path("/source/" + harness.FIXTURE).read_bytes()).hexdigest()
    database = os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"]
    with GraphDatabase.driver(
        os.environ["ARENA_WORKFLOW_NEO4J_URI"],
        auth=None,
        max_transaction_retry_time=0,
        connection_timeout=2,
        connection_acquisition_timeout=3,
    ) as driver:
        with driver.session(database=database) as session:
            for ddl in Neo4jWorkflowStore.schema_requirements():
                session.run(ddl).consume()
            session.run("CALL db.awaitIndexes(10)").consume()
        store = Neo4jWorkflowStore(
            driver, database=database, deployment_id="process-fixture", workspace_id=uuid.uuid4().hex
        )
        assert store.verify_schema()
        store.initialize_scope()
        run = store.admit("fixture-operation", "{}", canonical_json(request), 1)
        private = tmp_path / "private"
        private.mkdir(mode=0o700)
        area = ArtifactArea.create(private / "artifacts", store_id="store", registry_id="registry")
        ownership = OwnershipArtifacts(area)
        worker = ForegroundGenerationWorker(spawn_spec=harness.spawn_spec, ownership_artifacts=ownership)
        lease = ForegroundOwnerLease(
            private, run_id=run.run_id, principal="creator", cleanup_verified=worker.cleanup_verified
        )
        scope = dict(database=database, **store.scope)
        principal = dict(principal="creator", **scope, expires_at=time.time() + 120, revoked=False)
        authority = ForegroundAuthority(
            **scope,
            store=store,
            grants=ExecutionGrants(clock=time.time),
            clock=time.time,
            principal_lookup=lambda p: principal if p == "creator" else None,
            profiles={"synthetic": profile},
            current_config=lambda p: dict(config=config, expires_at=principal["expires_at"]),
        )
        authority.bind_run("creator", run.operation_id, request, run_id=run.run_id, catalogue_sha256=catalogue)
        gate = DependencyGate(
            lambda r, t: DependencyResult(r.dependency_id, "passed", r.profile_sha256, profile_id=r.profile_id)
        )
        service = WorkflowService(store, authority, gate, validate_support=lambda r: None)
        coordinator = GenerationCoordinator(
            store,
            authority,
            gate,
            worker,
            run_id=run.run_id,
            principal="creator",
            lease=lease,
            readiness_clock=ReadinessClock.capture(),
            workflow_service=service,
        )
        artifacts = GenerationArtifacts(area)
        reservation = GenerationReservation(
            model_calls=2, model_tokens=1000, cost_ceiling_usd=0.0, runtime_allowance_seconds=30.0
        )
        handle = coordinator.dispatch(
            "creator", expected_version=1, decision_id="fixture-decision", reservation=reservation
        )
        prepared = handle.prepared
        try:
            released = store.get_attempt(handle.fence)
            assert released.released and released.registration == prepared.registration
            receiver = ForegroundGenerationReceiver(
                worker, coordinator, lease, artifacts, validate_document=validate, protect=lambda value: None
            )
            completed = receiver.receive("creator", prepared)
            assert completed.disposition == "validation"
            retained = store.get_attempt(handle.fence)
            assert retained.receipt is not None and retained.cleanup is not None
            assert retained.receipt == receiver.receipt
            assert store.get_owner().dirty is False
            assert store.get_retired_owner(handle.fence.owner_id).owner_epoch == handle.fence.owner_epoch
            launches = dict(harness.ACTIVE.allowed)
            events_before = store.snapshot().cursor
            # A fresh concrete recovery object and service have no worker/send port.
            recovered = ForegroundGenerationRecovery(
                private,
                run_id=run.run_id,
                principal="creator",
                service=WorkflowService(store, authority, gate, validate_support=lambda r: None),
                ownership_artifacts=OwnershipArtifacts(area),
                artifacts=GenerationArtifacts(area),
                protect=lambda value: None,
            )
            result = recovered.recover()
            assert result.disposition == "validation"
            assert result.attempt.receipt == retained.receipt and result.attempt.cleanup == retained.cleanup
            assert store.snapshot().cursor == events_before
            assert harness.ACTIVE.allowed["child_launch"] == launches["child_launch"] == 1
            assert worker._get(prepared).attempted is True
            Path("/evidence/workflow-recovery.json").write_text(
                json.dumps(
                    dict(
                        scope=(
                            "real Neo4j, fixed stdlib producer, fixture registry, fresh recovery object; no SDK/runtime"
                        ),
                        run_id=run.run_id,
                        fence=handle.fence.model_dump(mode="json"),
                        registration=prepared.registration.model_dump(mode="json"),
                        receipt=retained.receipt.model_dump(mode="json"),
                        cleanup=retained.cleanup.model_dump(mode="json"),
                        fresh_object=True,
                        resend_count=0,
                        owner_retired=True,
                    )
                )
            )
        finally:
            worker.stop_owned(prepared, timeout_s=3)
