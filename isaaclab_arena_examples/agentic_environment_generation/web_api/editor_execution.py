# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Serial editor execution using owned bounded workers, never HTTP-loop simulation."""

import asyncio
import inspect
import json
import os
import sys
import threading
from pathlib import Path

from .generation import GENERATION_STAGES, GENERATION_TIMEOUT
from .preview_diagnostics import clean_errors, clean_timings
from .preview_options import normalized_options
from .process_identity import process_identity


def make_snapshot_service(state_dir):
    from .snapshot_service import SnapshotService

    return SnapshotService(Path(state_dir))


class EditorExecution:
    """Share the durable job dispatcher without coupling diagnostics to model or GPU imports."""

    def __init__(self, state_dir, documents):
        self.state_dir = Path(state_dir)
        self.documents = documents
        self.snapshots = None
        self.cancel_task = None
        self.snapshot_error = None
        self.loop_thread = threading.get_ident()
        try:
            self.snapshots = make_snapshot_service(state_dir)
        except (ImportError, OSError, RuntimeError):
            self.snapshot_error = "Snapshot adapter unavailable in this runtime"

    async def execute(self, supervisor, job):
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
                    self.snapshots.render, job["inputs"]["yaml_text"], job_id, emit, **kwargs
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
                        "errors": clean_errors(getattr(exc, "errors", None)) or [
                            {"id": "scene", "stage": "snapshot", "code": "snapshot_failed", "message": error}
                        ],
                        "timings": clean_timings(getattr(exc, "timings", None)),
                    }
                journal.transition(job_id, "failed", "failed", "failed", error=error, result=diagnostics)
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

    def request_cancel(self):
        if self.snapshots is not None and self.cancel_task is None:
            self.cancel_task = asyncio.create_task(asyncio.to_thread(self.snapshots.close))

    async def generate(self, supervisor, job, emit):
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
                limit=2 * 1024 * 1024,
            )
            supervisor.process = process
            if supervisor.journal.get_job(job["id"])["status"] == "cancel_requested":
                raise ValueError("Generation cancelled before authorization")
            identity = process_identity(process.pid)
            if identity is None:
                raise ValueError("Generation worker did not start")
            supervisor.journal.record_worker(job["id"], process.pid, identity)
            process.stdin.write((json.dumps(job["inputs"]) + "\n").encode())
            await process.stdin.drain()
            process.stdin.close()
            result = None
            for _ in range(64):
                line = await process.stdout.readline()
                if not line:
                    break
                message = json.loads(line)
                if set(message) == {"stage"} and message["stage"] in GENERATION_STAGES and result is None:
                    emit(message["stage"])
                elif set(message) == {"result"} and result is None:
                    result = message["result"]
                else:
                    raise ValueError("Invalid generation receipt")
            if await process.wait() != 0 or result is None:
                raise ValueError("Generation worker did not complete")
            if set(result) != {"yaml_text", "validation", "traces", "publication", "warnings"}:
                raise ValueError("Invalid generation result fields")
            validation = self.documents.validate(result["yaml_text"])
            if not validation["valid"] or result["publication"] != "not_published":
                raise ValueError("Generation result failed validation")
            if not isinstance(result["traces"], list) or any(s not in GENERATION_STAGES for s in result["traces"]):
                raise ValueError("Invalid generation trace")
            result["validation"] = validation
            return result

    async def close(self):
        if self.snapshots is not None:
            await asyncio.to_thread(self.snapshots.close)
