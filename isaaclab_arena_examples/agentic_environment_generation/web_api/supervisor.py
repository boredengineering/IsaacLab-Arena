# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""One asynchronous diagnostic subprocess at a time, with verified bounded receipts."""

import asyncio
import json
import os
import signal
import sys
from contextlib import suppress
from pathlib import Path

from .owned_process_group import OwnedProcessGroup
from .process_identity import process_identity


class Supervisor:
    """Dispatch only the fixed diagnostic adapter; HTTP never runs a blocking worker."""

    def __init__(self, journal, *, enabled=False, paused=False):
        self.journal = journal
        self.enabled = enabled
        self.paused = paused
        self.stopping = False
        self.process = None
        self.job_id = None
        self.wake = asyncio.Event()
        self.editor_execution = None

    @property
    def process(self):
        return self._process

    @process.setter
    def process(self, process):
        self._process = process
        self._process_group = None if process is None else OwnedProcessGroup(process.pid)

    async def run(self):
        while not self.stopping:
            self.wake.clear()
            queued = [job for job in self.journal.snapshot()["jobs"] if job["status"] == "queued"]
            executable = [
                job
                for job in queued
                if (job["kind"] == "diagnostic" and self.enabled)
                or (job["kind"] in {"generate", "snapshots"} and self.editor_execution is not None)
            ]
            if not self.paused and executable:
                job = executable[0]
                if job["kind"] == "diagnostic":
                    await self.execute(job)
                else:
                    await self.editor_execution.execute(self, job)
                continue
            with suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), timeout=0.2)

    async def execute(self, job):
        self.job_id = job["id"]
        self.journal.transition(self.job_id, "running", "worker_starting", "started")
        inputs = job["inputs"]
        try:
            self.process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-u",
                str(Path(__file__).with_name("diagnostic_worker.py")),
                "--steps",
                str(inputs["steps"]),
                "--delay",
                str(inputs["delay_seconds"]),
                "--parent-pid",
                str(os.getpid()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.PIPE,
                env={"PATH": os.defpath, "LANG": "C.UTF-8"},
                start_new_session=True,
                limit=4096,
            )
            if self.journal.get_job(self.job_id)["status"] == "cancel_requested":
                raise ValueError("Cancellation requested during process startup")
            identity = process_identity(self.process.pid)
            if identity is None:
                raise ValueError("Diagnostic worker exited during startup")
            self.journal.record_worker(self.job_id, self.process.pid, identity)
            self.process.stdin.write(b"go\n")
            await self.process.stdin.drain()
            self.process.stdin.close()
            async with asyncio.timeout(inputs["steps"] * inputs["delay_seconds"] + 10):
                stages = ["diagnostic_ready"]
                for step in range(1, inputs["steps"] + 1):
                    stages.extend([f"diagnostic_step_{step}_started", f"diagnostic_step_{step}_completed"])
                for stage in stages:
                    message = json.loads(await self.process.stdout.readline())
                    if self.journal.get_job(self.job_id)["status"] == "cancel_requested":
                        raise ValueError("Cancellation requested")
                    if message != {"stage": stage}:
                        raise ValueError("Invalid diagnostic stage receipt")
                    self.journal.transition(self.job_id, "running", stage, "stage_changed")
                receipt = json.loads(await self.process.stdout.readline())
                expected = {"diagnostic": True, "completed_steps": inputs["steps"]}
                if receipt != {"result": expected} or await self.process.stdout.read(4096):
                    raise ValueError("Invalid diagnostic completion receipt")
                if await self.process.wait() != 0:
                    raise ValueError("Diagnostic worker exited unsuccessfully")
                if self.journal.get_job(self.job_id)["status"] == "cancel_requested":
                    raise ValueError("Cancellation requested")
                self.journal.transition(self.job_id, "succeeded", "completed", "succeeded", result=expected)
        except (OSError, ValueError, TimeoutError):
            await self.stop_process()
            if self.journal.get_job(self.job_id)["status"] == "cancel_requested":
                self.journal.transition(self.job_id, "cancelled", "cancelled", "cancelled")
            else:
                self.journal.transition(
                    self.job_id,
                    "failed",
                    "failed",
                    "failed",
                    error="Diagnostic worker failed or returned no valid receipt",
                )
        finally:
            await self.stop_process()
            self.journal.worker_cleaned(self.job_id)
            self.process = None
            self.job_id = None

    def request_cancel(self, job_id):
        """Record intent before signaling; the reader commits cancellation only after reaping."""
        job = self.journal.transition(job_id, "cancel_requested", "cleanup_requested", "cancel_requested")
        if self.job_id == job_id and job["kind"] == "snapshots" and self.editor_execution is not None:
            self.editor_execution.request_cancel()
        if self.job_id == job_id and self._process_group is not None:
            self._process_group.send_signal(signal.SIGTERM)
        return job

    async def stop_process(self):
        """Reap the workbench-owned process group before releasing execution ownership."""
        process, group = self.process, self._process_group
        if process is None or (group.cleaned and process.returncode is not None):
            return
        await asyncio.to_thread(group.stop)
        await asyncio.wait_for(process.wait(), timeout=3)

    async def stop(self):
        self.stopping = True
        self.wake.set()
        if self.job_id and self.journal.get_job(self.job_id)["status"] == "running":
            self.request_cancel(self.job_id)
        await self.stop_process()
