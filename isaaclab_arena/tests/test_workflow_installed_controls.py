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
        async def exercise():
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
            tokens = TokenRegistry(binding=binding, instance="instance", generation=1, clock=lambda: 100.0)
            bearer = tokens.issue(principal="operator", lifetime=100)
            auth = tokens.authenticate(("Bearer " + bearer).encode())
            active, stop = threading.Event(), threading.Event()
            calls = []
            observation = LocalStopObservation(delivery="delivered")
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
                result = await asyncio.wait_for(owner.cancel(auth, "cancel-1", "run"), 1)
                self.assertEqual(result.receipt, receipt)
                self.assertEqual(calls, ["permission", "handler"])
                tokens.revoke(auth)
                with self.assertRaises(PermissionError):
                    await owner.cancel(auth, "cancel-2", "run")
            finally:
                stop.set()
                await owner.close()
            self.assertEqual(calls, ["permission", "handler", "closed"])

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
