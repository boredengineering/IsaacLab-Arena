# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Serial editor execution using owned bounded workers, never HTTP-loop simulation."""

import asyncio
import contextlib
import inspect
import json
import os
import sys
import threading
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.workbench.generation_diagnostics import checked_diagnostic

from . import generation
from .generation import GENERATION_STAGES, GENERATION_TIMEOUT
from .preview_diagnostics import clean_errors, clean_timings
from .preview_options import normalized_options
from .process_identity import process_identity
from .provider_security import reject_secret, worker_environment


def make_snapshot_service(state_dir):
    from .snapshot_service import SnapshotService

    return SnapshotService(Path(state_dir))


class EditorExecution:
    """Share the durable job dispatcher without coupling diagnostics to model or GPU imports."""

    evaluation_available = True
    """Fixed evaluation adapter availability, not remote server or GPU readiness."""

    build_available = True
    """Fixed build protocol availability, not a GPU-readiness assertion."""

    def __init__(self, state_dir, documents):
        self.state_dir = Path(state_dir)
        self.documents = documents
        self.model_settings = None
        self.workflow_authorizer = None
        self.protect_workflow = None
        self.snapshots = None
        self.cancel_task = None
        self.snapshot_error = None
        self.loop_thread = threading.get_ident()
        try:
            self.snapshots = make_snapshot_service(state_dir)
        except (ImportError, OSError, RuntimeError):
            self.snapshot_error = "Snapshot adapter unavailable in this runtime"

    async def execute(self, supervisor, job):
        if job["kind"] in {"build", "evaluate"}:
            from .build_execution import execute_build

            return await execute_build(self, supervisor, job)
        journal = supervisor.journal
        job_id = job["id"]
        supervisor.job_id = job_id
        journal.transition(job_id, "running", "worker_starting", "started")
        loop = asyncio.get_running_loop()

        def stage_on_loop(stage):
            if journal.get_job(job_id)["status"] == "running":
                journal.transition(job_id, "running", stage, "stage_changed")

        def emit(stage):
            if isinstance(stage, str) and len(stage) <= 100:
                loop.call_soon_threadsafe(stage_on_loop, stage)

        try:
            if job["kind"] == "generate":
                result = await self.generate(supervisor, job, stage_on_loop)
            elif job["kind"] == "snapshots" and self.snapshots is not None:
                options = normalized_options(job["inputs"].get("options"))
                kwargs = {"options": options}
                if "options" not in inspect.signature(self.snapshots.render).parameters:
                    # Legacy transport adapters can only honor the original default camera.
                    if options != normalized_options():
                        raise ValueError("Snapshot adapter does not support camera options")
                    kwargs = {}
                result = await asyncio.to_thread(
                    self.snapshots.render,
                    job["inputs"]["yaml_text"],
                    job_id,
                    emit,
                    **kwargs,
                )
                result["input_hash"] = job["inputs"]["input_hash"]
                assert (
                    result.get("canonical_hash", job["inputs"]["canonical_hash"]) == job["inputs"]["canonical_hash"]
                ), "Renderer receipt does not match the validated scene"
                result["canonical_hash"] = job["inputs"]["canonical_hash"]
            else:
                raise ValueError("Editor adapter unavailable")
            if journal.get_job(job_id)["status"] != "cancel_requested":
                journal.transition(job_id, "succeeded", "completed", "succeeded", result=result)
        except Exception as exc:
            await supervisor.stop_process()
            if journal.get_job(job_id)["status"] != "cancel_requested":
                error = (
                    "Generation failed or exceeded its 180-second budget; check configured model/endpoint and draft"
                    if job["kind"] == "generate"
                    else "Snapshot rendering failed; check Isaac Sim assets, GPU availability and runtime logs"
                )
                diagnostics = None
                if job["kind"] == "snapshots":
                    diagnostics = {
                        "canonical_hash": job["inputs"].get("canonical_hash"),
                        "options": job["inputs"].get("options", normalized_options()),
                        "errors": clean_errors(getattr(exc, "errors", None)) or [{
                            "id": "scene",
                            "stage": "snapshot",
                            "code": "snapshot_failed",
                            "message": error,
                        }],
                        "timings": clean_timings(getattr(exc, "timings", None)),
                    }
                journal.transition(
                    job_id,
                    "failed",
                    "failed",
                    "failed",
                    error=error,
                    result=diagnostics,
                )
        finally:
            await supervisor.stop_process()
            if self.cancel_task is not None:
                await self.cancel_task
                self.cancel_task = None
                if not supervisor.stopping:
                    self.snapshots = make_snapshot_service(self.state_dir)
            journal.worker_cleaned(job_id)
            if journal.get_job(job_id)["status"] == "cancel_requested":
                journal.transition(job_id, "cancelled", "cancelled", "cancelled")
            supervisor.process = None
            supervisor.job_id = None

    async def execute_managed(self, supervisor, job):
        """Release one fenced attempt and durably accept its candidate before reaping."""
        journal, job_id = supervisor.journal, job["id"]
        attempt = journal.claim_attempt(job_id)
        if attempt is None:
            return
        supervisor.job_id = job_id
        secrets = []
        authorization_failed = False
        diagnostic = None
        last_stage = "worker_starting"
        failure_code = "internal_error"

        def authorize():
            nonlocal authorization_failed
            authorization_failed = True
            if self.workflow_authorizer is None or self.protect_workflow is None:
                raise ValueError("Workflow authorization unavailable")
            private = self.workflow_authorizer(job, attempt=attempt)
            if type(private) is not dict or set(private) - {"config", "graph_config", "managed_context"}:
                raise ValueError("Invalid private generation fields")
            from .managed_retrieval import private_context

            managed = private_context(job["inputs"], private)
            if managed is not None:
                private = {**private, "managed_context": managed}
            secrets.append(private["config"].get("api_key"))
            secrets.append((private.get("graph_config") or {}).get("password"))
            authorization_failed = False
            return private

        def protect(value):
            for secret in secrets:
                reject_secret(value, secret)
            self.protect_workflow(value)

        try:
            private = authorize()
            async with asyncio.timeout(GENERATION_TIMEOUT):
                failure_code = "worker_exited"
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-u",
                    "-m",
                    "isaaclab_arena_examples.agentic_environment_generation.web_api.generation_worker",
                    "--parent-pid",
                    str(os.getpid()),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    stdin=asyncio.subprocess.PIPE,
                    start_new_session=True,
                    env=worker_environment(private["config"].get("api_key")),
                    limit=2 * 1024 * 1024,
                )
                supervisor.process = process
                identity = process_identity(process.pid)
                if identity is None:
                    raise ValueError("Worker identity unavailable")
                journal.record_worker(job_id, process.pid, identity)
                private = authorize()
                envelope = (json.dumps({"inputs": job["inputs"], **private}, allow_nan=False) + "\n").encode()
                if len(envelope) > 512 * 1024:
                    raise ValueError("Private generation envelope exceeds bounds")
                if not journal.release_attempt(job_id, **attempt):
                    return
                process.stdin.write(envelope)
                await process.stdin.drain()
                process.stdin.close()
                accepted = False
                for _ in range(64):
                    failure_code = "worker_exited"
                    line = await process.stdout.readline()
                    if not line:
                        break
                    failure_code = "worker_protocol"
                    message = json.loads(line)
                    protect(message)
                    if type(message) is not dict:
                        raise ValueError("Invalid generation frame")
                    if set(message) == {"error"} and not accepted:
                        value = checked_diagnostic(message["error"])
                        if value["stage"] != last_stage:
                            raise ValueError("Invalid diagnostic stage")
                        diagnostic = value
                        break
                    if set(message) == {"stage"} and message["stage"] in GENERATION_STAGES and not accepted:
                        if journal.progress_attempt(
                            job_id,
                            **attempt,
                            expected_state="released",
                            stage=message["stage"],
                        ):
                            last_stage = message["stage"]
                    elif set(message) == {"result"} and not accepted:
                        receipt = self.validate_managed_receipt(job, message["result"])
                        protect(receipt)
                        accepted = journal.commit_candidate(job_id, **attempt, receipt=receipt)
                        if not accepted:
                            return

                    else:
                        raise ValueError("Invalid generation receipt")
                await process.wait()
                if not accepted and diagnostic is None:
                    diagnostic = checked_diagnostic({"schema_version": 1, "code": failure_code, "stage": last_stage})
        except Exception as exc:
            # No exception text crosses the durable/public boundary.
            if not authorization_failed and diagnostic is None:
                diagnostic = checked_diagnostic({
                    "schema_version": 1,
                    "code": "worker_timeout" if isinstance(exc, TimeoutError) else failure_code,
                    "stage": last_stage,
                })
        finally:
            # Diagnostic reads, guards, and writes are best effort, never cleanup gates.
            with contextlib.suppress(Exception):
                current = journal.get_attempt(job_id)
                if current and all(current[key] == value for key, value in attempt.items()):
                    state = current["state"]
                    if diagnostic is not None and state in {"claimed", "released"}:
                        journal.record_attempt_diagnostic(
                            job_id, **attempt, expected_state=state, diagnostic=diagnostic, protect_public=protect
                        )
            # Persist evidence before cleanup; failed cleanup retains running state and ownership.
            await supervisor.stop_process()
            journal.worker_cleaned(job_id)
            current = journal.get_attempt(job_id)
            if current and all(current[key] == value for key, value in attempt.items()):
                state = current["state"]
                if state == "candidate_committed":
                    journal.complete_attempt(job_id, **attempt, expected_state=state)
                elif state == "cancel_requested":
                    journal.cancel_attempt(job_id, **attempt, expected_state=state)
                elif state == "released":
                    journal.mark_attempt_indeterminate(job_id, **attempt, expected_state=state)
                elif state == "claimed":
                    if authorization_failed:
                        journal.block_attempt_authorization(job_id, **attempt)
                    else:
                        journal.fail_attempt(job_id, **attempt, expected_state=state)
            supervisor.process = None
            supervisor.job_id = None

    def validate_managed_receipt(self, job, result):
        """Revalidate the candidate and reject unrecognized public result fields."""
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
        if result["operation"] != job["inputs"]["operation"] or result["publication"] != "not_published":
            raise ValueError("Invalid generation operation")
        if not isinstance(result["yaml_text"], str):
            raise ValueError("Invalid candidate text")
        validation = self.documents.validate(result["yaml_text"])
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
        expected = job["inputs"].get("execution_catalogue_sha256")
        if type(expected) is not str or expected != digest:
            raise ValueError("Execution catalogue identity mismatch")
        snapshot = result["prior_snapshot"]
        if type(snapshot) is not dict:
            raise ValueError("Missing prior snapshot")
        status = snapshot.get("status")
        if result["operation"] == "new":
            if status == "not_requested":
                raise ValueError("New generation requires a retrieval outcome")
            if job["inputs"].get("retrieval_policy") == "require_service" and status == "unavailable":
                raise ValueError("Required retrieval unavailable")
        elif status != "not_requested":
            raise ValueError("Refinement cannot claim retrieval")
        from isaaclab_arena.agentic_environment_generation.prior_receipt import validate_prior_snapshot

        prompt = job["inputs"].get("prompt", "") if result["operation"] == "new" else ""
        validate_prior_snapshot(snapshot, prompt=prompt)
        return {**result, "validation": validation}

    def request_cancel(self):
        if self.snapshots is not None and self.cancel_task is None:
            self.cancel_task = asyncio.create_task(asyncio.to_thread(self.snapshots.close))

    async def generate(self, supervisor, job, emit):
        inputs = job["inputs"]
        if "credential_ref" in inputs:
            assert self.model_settings is not None, "Temporary credential store unavailable"
            owner, reference = job["created_by_session_id"], inputs["credential_ref"]
            metadata = {key: inputs[key] for key in ("provider", "model")}
            config = self.model_settings.resolve(owner, reference)
            if any(config[key] != inputs[key] for key in ("provider", "model")):
                raise ValueError("Temporary credential metadata mismatch")
        else:
            config = generation.configuration()
        api_key = (config or {}).get("api_key")
        async with asyncio.timeout(GENERATION_TIMEOUT):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                "-m",
                "isaaclab_arena_examples.agentic_environment_generation.web_api.generation_worker",
                "--parent-pid",
                str(os.getpid()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.PIPE,
                start_new_session=True,
                env=worker_environment(api_key),
                limit=2 * 1024 * 1024,
            )
            supervisor.process = process
            if supervisor.journal.get_job(job["id"])["status"] == "cancel_requested":
                raise ValueError("Generation cancelled before authorization")
            identity = process_identity(process.pid)
            if identity is None:
                raise ValueError("Generation worker did not start")
            supervisor.journal.record_worker(job["id"], process.pid, identity)
            if "credential_ref" in inputs:
                # Spawning yields to Forget, expiry and replacement. Authorize again with
                # the original owner/ref, with no await before releasing the private bytes.
                config = self.model_settings.resolve(owner, reference)
                if any(config[key] != value for key, value in metadata.items()):
                    raise ValueError("Temporary credential metadata mismatch")
                api_key = config["api_key"]
            process.stdin.write((json.dumps({"inputs": inputs, "config": config}) + "\n").encode())
            await process.stdin.drain()
            process.stdin.close()
            result = None
            for _ in range(64):
                line = await process.stdout.readline()
                if not line:
                    break
                message = json.loads(line)
                reject_secret(message, api_key)
                if set(message) == {"stage"} and message["stage"] in GENERATION_STAGES and result is None:
                    emit(message["stage"])
                elif set(message) == {"result"} and result is None:
                    result = message["result"]
                else:
                    raise ValueError("Invalid generation receipt")
            if await process.wait() != 0 or result is None:
                raise ValueError("Generation worker did not complete")
            if set(result) != {
                "yaml_text",
                "validation",
                "traces",
                "publication",
                "warnings",
            }:
                raise ValueError("Invalid generation result fields")
            validation = self.documents.validate(result["yaml_text"])
            if not validation["valid"] or result["publication"] != "not_published":
                raise ValueError("Generation result failed validation")
            if not isinstance(result["traces"], list) or any(s not in GENERATION_STAGES for s in result["traces"]):
                raise ValueError("Invalid generation trace")
            result["validation"] = validation
            reject_secret(result, api_key)
            return result

    async def close(self):
        if self.snapshots is not None:
            await asyncio.to_thread(self.snapshots.close)
