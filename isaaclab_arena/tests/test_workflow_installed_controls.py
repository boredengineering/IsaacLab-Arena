# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Focused installed-owner boundaries; physical workers are verified separately."""

import asyncio
import threading
import unittest
from types import SimpleNamespace

from isaaclab_arena.agentic_environment_generation.workflow.api.execution_owner import ExecutionOwner
from isaaclab_arena.agentic_environment_generation.workflow.api.security import TokenRegistry
from isaaclab_arena.agentic_environment_generation.workflow.commands import (
    CancelResult,
    LocalStopObservation,
    command_digest,
    command_json,
    make_cancel_receipt,
)
from isaaclab_arena.agentic_environment_generation.workflow.scope_binding import ScopeBinding


class InstalledControls(unittest.TestCase):
    def test_scene_failure_dispatch_retains_first_cause_and_separate_cleanup(self):
        import json
        import tempfile
        from pathlib import Path

        from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import ArtifactArea
        from isaaclab_arena.agentic_environment_generation.workflow.read_model import scene_failure_references
        from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService
        from isaaclab_arena.tests.test_environment_workflow_service import contract
        from isaaclab_arena_examples.agentic_environment_generation.foreground_scene_ports import ForegroundScenePorts
        from isaaclab_arena_examples.agentic_environment_generation.web_api.scene_worker import read_retained

        # Exercise diagnostic dispatch only: no admission, registration, grant or database.
        for version in ("4", "5"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary:
                with ArtifactArea.create(Path(temporary) / "area", store_id="test", registry_id="scope") as area:
                    links = []
                    ports = ForegroundScenePorts.__new__(ForegroundScenePorts)
                    ports.run_id = "diagnostic-unit"
                    ports.artifacts = SimpleNamespace(area=area)
                    ports.protect = lambda value: None
                    ports._failure_contracts, ports._prepared_workers = {}, {}
                    ports.store = SimpleNamespace(record_scene_failure=lambda *a, **kw: links.append((a, kw)))
                    intent = SimpleNamespace(intent_id="intent", worker_fence=None, worker_registration=None)
                    selected = contract().model_copy(update={"schema_version": version})
                    error = PermissionError("private exception text must not be retained")
                    WorkflowService._record_scene_failure(ports, intent, selected, "parent_authorization", error)
                    self.assertEqual(len(links), 1)
                    first = links[0][0][2]
                    original = read_retained(area, first, protect=ports.protect)
                    self.assertEqual(original["phase"], "parent_authorization")
                    self.assertEqual(original["exception_type"], "PermissionError")
                    self.assertNotIn(str(error), str(original))
                    WorkflowService._record_scene_failure(ports, intent, selected, "parent_execute", RuntimeError())
                    ports.record_failure(intent, "cleanup", TimeoutError(), cleanup=True)
                    self.assertEqual(links[1][0][2], first)
                    self.assertNotEqual(links[2][0][2], first)
                    self.assertEqual(read_retained(area, first, protect=ports.protect), original)
                    self.assertEqual(links[2][0][2]["binding"]["category"], "cleanup")
                    rows = [
                        dict(
                            intent_id=intent.intent_id,
                            fence=None,
                            causal_failure=json.dumps(first, sort_keys=True, separators=(",", ":")),
                            cleanup_failure=json.dumps(links[2][0][2], sort_keys=True, separators=(",", ":")),
                        )
                    ]
                    projected = scene_failure_references(ports.run_id, selected, rows)
                    self.assertEqual(projected["failures"][0]["causal"], first)
                    self.assertEqual(projected["failures"][0]["cleanup"], links[2][0][2])
                    self.assertEqual(projected["fresh_artifact_verification"], "not_performed")
                    with self.assertRaises(ValueError):
                        scene_failure_references("foreign-run", selected, rows)
                    with self.assertRaises(ValueError):
                        scene_failure_references(
                            ports.run_id, selected, [dict(rows[0], cleanup_failure=rows[0]["causal_failure"])]
                        )
                    self.assertIsNone(scene_failure_references(ports.run_id, selected, []))
        calls = []
        ports = SimpleNamespace(record_failure=lambda *a, **kw: calls.append(a))
        for version in ("1", "2", "3"):
            WorkflowService._record_scene_failure(
                ports, object(), SimpleNamespace(schema_version=version), "parent_execute", RuntimeError()
            )
        self.assertEqual(calls, [])

    def test_scene_failure_links_use_existing_public_result_type_and_query(self):
        import strawberry
        from graphql import parse, validate

        from isaaclab_arena.agentic_environment_generation.workflow.api.client import DOCUMENTS
        from isaaclab_arena.agentic_environment_generation.workflow.api.schema import Workflow, schema
        from isaaclab_arena.agentic_environment_generation.workflow.queries import RunInspection

        # Serialize only reference metadata: no service, retained run or grant.
        payload = '{"fresh_artifact_verification":"not_performed","failures":[]}'
        result = strawberry.Schema(query=Workflow).execute_sync(
            "{sceneFailuresJson}", root_value=SimpleNamespace(scene_failures_json=payload)
        )
        self.assertIsNone(result.errors)
        self.assertEqual(result.data, {"sceneFailuresJson": payload})
        self.assertIn("sceneFailuresJson", DOCUMENTS["result"])
        self.assertEqual(validate(schema._schema, parse(DOCUMENTS["result"])), [])
        self.assertNotIn("scene_failures_json", RunInspection.model_construct().model_dump())
        self.assertEqual(
            RunInspection.model_construct(scene_failures_json=payload).model_dump()["scene_failures_json"], payload
        )

    def test_split_adapter_binds_failure_sink_only_to_exact_prepared_worker(self):
        from isaaclab_arena.agentic_environment_generation.workflow.coordinator import PreparedWorker
        from isaaclab_arena.agentic_environment_generation.workflow.split_scene_ports import OwnedSceneStageAdapter

        calls = []
        registration = SimpleNamespace(registration_id="diagnostic-unit")
        prepared = PreparedWorker(registration, object())
        worker = SimpleNamespace(bind_failure_retention=lambda *args: calls.append(args))
        adapter = OwnedSceneStageAdapter.__new__(OwnedSceneStageAdapter)
        adapter._workers = {registration.registration_id: (prepared, worker, "capture")}

        def retain(phase, error):
            return None

        adapter.bind_failure_retention(prepared, retain)
        self.assertEqual(calls, [(prepared, retain)])
        with self.assertRaises(ValueError):
            adapter.bind_failure_retention(PreparedWorker(registration, object()), retain)
        self.assertEqual(len(calls), 1)

    def test_native_supervision_uses_real_authority_guard_and_refuses_stale_owner(self):
        from isaaclab_arena.agentic_environment_generation.workflow.api.installed_full_scene import (
            native_supervision_context,
        )
        from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import Neo4jWorkflowStore
        from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import ForegroundAuthority

        authority = ForegroundAuthority.__new__(ForegroundAuthority)
        authority._lock = threading.RLock()
        calls = []

        def guarded(value):
            self.assertTrue(authority._lock._is_owned())
            calls.append(value)
            return value

        current_api = SimpleNamespace(principal="operator", instance="instance", generation=2, expires_at=300.0)
        fence = SimpleNamespace(run_id="run")
        intent = SimpleNamespace(intent_id="intent", worker_fence=fence, worker_registration=object())
        current_intent = SimpleNamespace(**vars(intent), status="released", worker_cleanup=None)
        run = SimpleNamespace(state="running", operation_id="operation")
        authority.require_scene_execute = lambda *a, **kw: guarded("grant")
        self.assertTrue(callable(Neo4jWorkflowStore.get_admitted_at))
        arguments = dict(
            config=SimpleNamespace(binding="scope"),
            tokens=SimpleNamespace(current=lambda auth: guarded(current_api)),
            auth=object(),
            store=SimpleNamespace(
                get_scene_intent=lambda *a: guarded(current_intent),
                get_run=lambda *a: guarded(run),
                get_admitted_at=lambda run_id: guarded(100.0),
            ),
            authority=authority,
            admission=lambda *a: guarded("admission"),
            intent=intent,
            contract=object(),
        )
        result = native_supervision_context(**arguments)
        self.assertEqual(result["credential_generation"], 2)
        self.assertEqual(result["authority"], "grant")
        self.assertEqual(result["admitted_at"], 100.0)
        self.assertFalse(authority._lock._is_owned())
        calls.clear()
        current_intent.worker_registration = object()
        with self.assertRaises(PermissionError):
            native_supervision_context(**arguments)
        self.assertNotIn("admission", calls)
        self.assertNotIn("grant", calls)

    def test_result_polling_keeps_minimum_interval_with_variable_call_overhead(self):
        from unittest.mock import patch

        from isaaclab_arena.agentic_environment_generation.workflow.api import client

        now, calls = [0.0], []

        def sleep(seconds):
            now[0] += seconds

        def query(*args, **kwargs):
            now[0] += 0.00002 if not calls else 0.00001
            calls.append(now[0])
            return {
                "data": {
                    "workflow": {
                        "__typename": "Workflow",
                        "id": "run",
                        "operationId": "submit",
                        "state": "running",
                    }
                }
            }

        clock = SimpleNamespace(monotonic=lambda: now[0], sleep=sleep)
        with patch.object(client, "query", query), patch.object(client, "time", clock):
            with self.assertRaises(TimeoutError):
                client.result("unused", "run", operation_id="submit", wait_terminal_seconds=3)
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(all(after - before >= 1.0 for before, after in zip(calls, calls[1:])))

    def test_installed_resume_owns_drive_and_replays_while_it_is_active(self):
        from isaaclab_arena.agentic_environment_generation.workflow.commands import CommandConflict
        from isaaclab_arena.tests.test_environment_workflow_import_boundaries import keyed_resume_fixture

        async def exercise():
            fixture = keyed_resume_fixture()
            binding = ScopeBinding(
                database="neo4j",
                deployment_id="dep",
                workspace_id="ws",
                schema_version=1,
                authority_id="authority",
                operational_schema_version=1,
                artifact_marker_schema=1,
                store_id="store",
                registry_id="registry",
            )
            tokens = TokenRegistry(binding=binding, instance="instance", generation=1, clock=lambda: 100.0)
            auth = tokens.authenticate(("Bearer " + tokens.issue(principal="creator", lifetime=100)).encode())
            active, release = threading.Event(), threading.Event()

            def receive(*a, **kw):
                active.set()
                assert release.wait(5)
                return SimpleNamespace(disposition="reconciliation_required")

            fixture.app._initial_receiver_factory = lambda *a, **kw: SimpleNamespace(receive=receive)
            owner = ExecutionOwner(
                fixture.app,
                None,
                tokens,
                lambda v: None,
                authorize_control=lambda kind, principal, run_id: self.assertEqual(
                    (kind, principal, run_id), ("resume", "creator", "run")
                ),
            )
            try:
                receipt = await asyncio.wait_for(owner.resume(auth, "resume-key", fixture.payload), 1)
                for _ in range(1000):
                    if active.is_set():
                        break
                    await asyncio.sleep(0.001)
                self.assertTrue(active.is_set())
                self.assertFalse(owner._drive.done())
                fixture.app._preflight = lambda *a: self.fail("Replay resolved execution configuration")
                replay = await owner.resume(auth, "resume-key", fixture.payload)
                self.assertEqual(receipt, replay)
                with self.assertRaises(CommandConflict):
                    await owner.resume(auth, "resume-key", {**fixture.payload, "expectedVersion": 2})
                tokens.revoke(auth)
                with self.assertRaises(PermissionError):
                    await owner.resume(auth, "resume-key", fixture.payload)
                self.assertEqual(fixture.f.calls.count("prepare"), 1)
                self.assertEqual(fixture.f.calls.count("send"), 1)
            finally:
                release.set()
                # Fixture worker/lease ports are inert; close actual owned threads.
                owner._driver.shutdown(wait=True)
                await owner.admissions.close(None)
                await owner.controls.close(None)
                owner._stopper.shutdown(wait=True)

        asyncio.run(exercise())

    def test_resume_drive_rejects_guarded_reentry_without_consuming_delivery(self):
        from isaaclab_arena.agentic_environment_generation.workflow.application import _resume_authority_context
        from isaaclab_arena.tests.test_environment_workflow_import_boundaries import keyed_resume_fixture

        fixture = keyed_resume_fixture()
        _, drive = fixture.app.admit_resume_keyed(
            "creator", "resume-key", fixture.payload, check_resume=lambda *a: None
        )
        _resume_authority_context.active = True
        try:
            with self.assertRaises(RuntimeError):
                drive()
        finally:
            _resume_authority_context.active = False
        self.assertEqual(drive().execution, "returned")
        self.assertEqual(fixture.f.calls.count("send"), 1)

    def test_resume_document_is_typed_and_query_only_refuses_it(self):
        from isaaclab_arena.agentic_environment_generation.workflow.api.client import DOCUMENTS
        from isaaclab_arena.agentic_environment_generation.workflow.api.execution_schema import schema
        from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema as read_schema
        from isaaclab_arena.agentic_environment_generation.workflow.api.security import validate_document

        body = {
            "query": DOCUMENTS["resume"],
            "variables": {"id": "run", "operation": "resume-1", "version": "2", "renew": True},
        }
        self.assertEqual(validate_document(body, schema, execution=True), body)
        with self.assertRaises(ValueError):
            validate_document(body, read_schema)
        with self.assertRaises(ValueError):
            validate_document({**body, "variables": {**body["variables"], "renew": "yes"}}, schema, execution=True)

    def test_resume_admission_returns_one_shot_drive_and_replay_never_delivers(self):
        from isaaclab_arena.tests.test_environment_workflow_import_boundaries import keyed_resume_fixture

        fixture = keyed_resume_fixture()
        result, drive = fixture.app.admit_resume_keyed(
            "creator", "resume-key", fixture.payload, check_resume=lambda *a: None
        )
        self.assertEqual(result.execution, "not_requested")
        self.assertNotIn("apply", fixture.f.calls)
        self.assertNotIn("prepare", fixture.f.calls)
        replay, duplicate = fixture.app.admit_resume_keyed("creator", "resume-key", fixture.payload, check_resume=None)
        self.assertEqual(replay.receipt, result.receipt)
        self.assertIsNone(duplicate)
        self.assertEqual(drive().execution, "returned")
        self.assertEqual(drive().execution, "blocked")
        self.assertEqual(fixture.f.calls.count("prepare"), 1)
        self.assertEqual(fixture.f.calls.count("send"), 1)
        self.assertNotIn("reserve", fixture.f.calls)

    def test_cancel_document_is_installed_but_query_only_stays_read_only(self):
        from isaaclab_arena.agentic_environment_generation.workflow.api.client import DOCUMENTS
        from isaaclab_arena.agentic_environment_generation.workflow.api.execution_schema import schema
        from isaaclab_arena.agentic_environment_generation.workflow.api.schema import schema as read_schema
        from isaaclab_arena.agentic_environment_generation.workflow.api.security import validate_document

        body = {"query": DOCUMENTS["cancel"], "variables": {"id": "run", "operation": "cancel-1"}}
        self.assertEqual(validate_document(body, schema, execution=True), body)
        with self.assertRaises(ValueError):
            validate_document(body, read_schema)

    def test_cancel_reaches_handler_while_owned_drive_is_active(self):
        async def exercise(delivery):
            from isaaclab_arena.agentic_environment_generation.workflow.contracts import ControlPolicy

            binding = ScopeBinding(
                database="db",
                deployment_id="deployment",
                workspace_id="workspace",
                schema_version=1,
                authority_id="authority",
                operational_schema_version=1,
                artifact_marker_schema=1,
                store_id="store",
                registry_id="registry",
            )
            now = [100.0]
            tokens = TokenRegistry(binding=binding, instance="b" * 32, generation=1, clock=lambda: now[0])
            bearer = tokens.issue(principal="operator", lifetime=100)
            auth = tokens.authenticate(("Bearer " + bearer).encode())
            tokens.bind_current(
                auth,
                ControlPolicy(
                    codec="renewable-control-v1",
                    max_supervision_lease_seconds=60.0,
                    heartbeat_seconds=20.0,
                    max_credential_lifetime_seconds=300.0,
                    client_descriptor_schema="2",
                ),
            )
            active, stop = threading.Event(), threading.Event()
            calls = []
            observation = LocalStopObservation(delivery=delivery)
            payload = command_json({"runId": "run"})
            receipt = make_cancel_receipt(
                scope=dict(database="db", deployment_id="deployment", workspace_id="workspace"),
                operation_id="cancel-1",
                run_id="run",
                payload_json=payload,
                payload_digest=command_digest(payload),
                before_version=1,
                after_version=2,
                disposition="cancellation_requested",
                reason=None,
                first_local_stop=observation.model_dump(mode="json"),
                events=[dict(sequence=1, kind="CancellationRequested", source_id="run")],
            )

            def authorize(kind, principal, run_id):
                self.assertEqual(tokens.current(auth).principal, principal)
                self.assertEqual((kind, principal, run_id), ("cancel", "operator", "run"))
                calls.append("permission")

            def cancel(principal, operation_id, run_id, *, authorize_cancel):
                self.assertTrue(active.is_set())
                authorize_cancel(principal, run_id)
                self.assertEqual((operation_id, run_id), ("cancel-1", "run"))
                calls.append("handler")
                stop.set()
                return CancelResult(
                    local_stop=observation,
                    durable="recorded",
                    receipt=receipt,
                    cleanup_status="not_requested",
                    cleanup=None,
                )

            def drive():
                active.set()
                assert stop.wait(5), "Cancellation waited behind the owned drive"

            root = SimpleNamespace(
                _lock=threading.RLock(),
                _cancel_controls={},
                _recoveries={},
                _local={},
                authority=SimpleNamespace(require_read=lambda p: self.assertEqual(p, "operator"), close=lambda: None),
                _cancellation=SimpleNamespace(stop_local=lambda *a: None),
                store=SimpleNamespace(
                    get_owner=lambda: None,
                    get_run_cleanup=lambda run: SimpleNamespace(current_scope_owner=None, intents=()),
                ),
                cancel_keyed=cancel,
                close=lambda: None,
            )
            owner = ExecutionOwner(
                root,
                SimpleNamespace(close=lambda: calls.append("closed")),
                tokens,
                lambda v: None,
                authorize_control=authorize,
            )
            try:
                owner._drive = owner._driver.submit(drive)
                while not active.is_set():
                    await asyncio.sleep(0.001)
                now[0] = 201.0
                with self.assertRaises(PermissionError):
                    tokens.authenticate(("Bearer " + bearer).encode())
                with self.assertRaises(PermissionError):
                    await owner.cancel(auth, "cancel-1", "run")
                delivered = []
                metadata = tokens.refresh_current(auth, deliver=delivered.append)
                self.assertNotIn("bearer", metadata)
                import tempfile
                from unittest.mock import patch

                from isaaclab_arena.agentic_environment_generation.workflow.api.client import descriptor
                from isaaclab_arena.agentic_environment_generation.workflow.api.private_files import Directory, encode

                with tempfile.TemporaryDirectory() as temporary:
                    with Directory(temporary + "/" + auth.instance, create=True) as directory:
                        private = dict(delivered[0], endpoint="http://127.0.0.1:36315/graphql")
                        directory.write("client.json", encode(private))
                        with patch("time.time", return_value=now[0]):
                            reloaded = descriptor(directory.path + "/client.json")
                            self.assertEqual(reloaded["credential_revision"], 2)
                            self.assertEqual(reloaded["binding"], binding.model_dump(mode="json"))
                refreshed = tokens.authenticate(("Bearer " + delivered[0]["bearer"]).encode())
                self.assertIs(tokens.current(auth), refreshed)
                self.assertEqual(
                    (refreshed.principal, refreshed.instance, refreshed.binding),
                    (auth.principal, auth.instance, auth.binding),
                )
                self.assertEqual(metadata["credential_revision"], 2)
                self.assertEqual(metadata["expires_at"], 501.0)
                with self.assertRaises(PermissionError):
                    tokens.recheck(auth)
                result = await asyncio.wait_for(owner.cancel(refreshed, "cancel-1", "run"), 1)
                self.assertEqual(result.receipt, receipt)
                self.assertEqual(owner._run_ids, {"run"} if delivery == "delivered" else set())
                self.assertEqual(calls, ["permission", "handler"])
                tokens.revoke(refreshed)
                with self.assertRaises(PermissionError):
                    await owner.cancel(refreshed, "cancel-2", "run")
                with self.assertRaises(PermissionError):
                    tokens.current(auth)
                with self.assertRaises(PermissionError):
                    tokens.refresh_current(auth, deliver=delivered.append)
                self.assertEqual(len(delivered), 1)
            finally:
                stop.set()
                await owner.close()
            self.assertEqual(calls, ["permission", "handler", "closed"])

        asyncio.run(exercise("delivered"))
        asyncio.run(exercise("no_owner"))


if __name__ == "__main__":
    unittest.main()
