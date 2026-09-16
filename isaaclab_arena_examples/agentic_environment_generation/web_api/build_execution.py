# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Fixed Build and Evaluate workers on the existing supervisor and shared GPU lease."""

import asyncio
import fcntl
import json
import os
import stat
import sys
import uuid

from . import snapshot_process
from .provider_security import worker_environment
from .public_records import screen_public_record

BUILD_TIMEOUT = 300
EVALUATION_TIMEOUT = 900
EVALUATION_ERROR = (
    "Evaluation failed or exceeded its 900-second budget; check the local policy server and private runtime logs"
)
BUILD_ERROR = "Build failed or exceeded its budget; check Isaac Sim assets, GPU availability and private runtime logs"


def build_environment():
    """Preserve simulator paths and GPU restrictions without inherited credentials."""
    environment = worker_environment(None)
    for name in ("EXP_PATH", "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES"):
        if name in os.environ:
            environment[name] = os.environ[name]
    environment["OMNICLIENT_HUB_MODE"] = "disabled"
    return environment


async def execute_build(execution, supervisor, job):
    """Publish completion only after the worker and its owned process group are reaped."""
    journal, job_id = supervisor.journal, job["id"]
    evaluation = job.get("kind", "build") == "evaluate"
    supervisor.job_id = job_id
    journal.transition(job_id, "running", "worker_starting", "started")
    result = None
    snapshots_cleaned = execution.snapshots is None
    try:
        async with asyncio.timeout(EVALUATION_TIMEOUT if evaluation else BUILD_TIMEOUT):
            # SnapshotService.close reaches SnapshotProcess.close -> identity-checked
            # group stop + wait. Never drop its object/lease on a failed close.
            if execution.snapshots is not None:
                await asyncio.to_thread(execution.snapshots.close)
                snapshots_cleaned = True
                execution.snapshots = None
            journal.transition(job_id, "running", "waiting_for_gpu_lease", "stage_changed")
            execution.build_lease_fd = os.open(
                snapshot_process.GPU_LEASE, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
            )
            info = os.fstat(execution.build_lease_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or os.getuid() == 0:
                raise ValueError("Invalid GPU lease")
            while True:
                cancelled(supervisor, job_id)
                try:
                    fcntl.flock(execution.build_lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.05)
            result = await run_worker(execution, supervisor, job)
    except Exception:
        # No simulator text, paths or exception messages enter the public journal.
        result = None
    finally:
        try:
            await supervisor.stop_process()
            if not snapshots_cleaned:
                raise RuntimeError("Snapshot cleanup remains unverified")
        except Exception:
            # Retain process, snapshot and descriptor ownership; dispatch no new GPU work.
            supervisor.paused = True
            current = journal.get_job(job_id)
            journal.transition(job_id, current["status"], "cleanup_pending", "stage_changed")
            return
        for name in ("build_owner_fd", "build_lease_fd"):
            descriptor = getattr(execution, name, None)
            if descriptor is not None:
                os.close(descriptor)
                setattr(execution, name, None)
        journal.worker_cleaned(job_id)
        if result is not None:
            try:
                if evaluation:
                    from .evaluation_artifacts import job_root, verify_result

                    verify_result(
                        job_root(execution.state_dir, job_id),
                        job["inputs"],
                        result,
                        execution.model_settings.protect_public,
                    )
                screen_public_record(result, execution.model_settings.protect_public)
            except Exception:
                result = None
        if journal.get_job(job_id)["status"] == "cancel_requested":
            journal.transition(job_id, "cancelled", "cancelled", "cancelled")
        elif result is not None:
            journal.transition(job_id, "succeeded", "completed", "succeeded", result=result)
        else:
            journal.transition(
                job_id, "failed", "failed", "failed", error=EVALUATION_ERROR if evaluation else BUILD_ERROR
            )
        supervisor.process = None
        supervisor.job_id = None
        if not supervisor.stopping:
            from .editor_execution import make_snapshot_service

            try:
                execution.snapshots = make_snapshot_service(execution.state_dir)
                execution.snapshot_error = None
            except (ImportError, OSError, RuntimeError):
                execution.snapshot_error = "Snapshot adapter unavailable in this runtime"


def cancelled(supervisor, job_id):
    if supervisor.stopping or supervisor.journal.get_job(job_id)["status"] == "cancel_requested":
        raise ValueError("Build cancelled")


async def run_worker(execution, supervisor, job):
    """Read one bounded fixed-worker receipt; native and Python simulator logs stay private."""
    from .editor_execution import process_identity

    inputs, job_id = job["inputs"], job["id"]
    evaluation = job.get("kind", "build") == "evaluate"
    receipt_limit = 256 * 1024 if evaluation else 4096
    module = "evaluation_worker" if evaluation else "build_worker"
    stage = "evaluating_policy" if evaluation else "building_environment"
    envelope_data = {"inputs": inputs}
    if evaluation:
        from .evaluation_artifacts import job_root

        output_root = job_root(execution.state_dir, job_id)
        output_root.parent.mkdir(mode=0o700, exist_ok=True)
        output_root.mkdir(mode=0o700)
        envelope_data["output_root"] = str(output_root)
    cancelled(supervisor, job_id)
    root = execution.state_dir / ("evaluation-logs" if evaluation else "build-logs")
    root.mkdir(mode=0o700, exist_ok=True)
    reader, execution.build_owner_fd = os.pipe()
    try:
        fd = os.open(root / f"{uuid.uuid4().hex}.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                "-m",
                f"isaaclab_arena_examples.agentic_environment_generation.web_api.{module}",
                "--owner-fd",
                str(reader),
                stdout=asyncio.subprocess.PIPE,
                stderr=log,
                stdin=asyncio.subprocess.PIPE,
                start_new_session=True,
                pass_fds=(reader, execution.build_lease_fd),
                env=build_environment(),
                limit=receipt_limit,
            )
            supervisor.process = process
    finally:
        os.close(reader)
    identity = process_identity(process.pid)
    if identity is None:
        raise ValueError("Build worker identity unavailable")
    supervisor.journal.record_worker(job_id, process.pid, identity)
    cancelled(supervisor, job_id)
    screen_public_record(inputs, execution.model_settings.protect_public)
    envelope = (json.dumps(envelope_data, ensure_ascii=False, allow_nan=False) + "\n").encode()
    if len(envelope) > 2 * 1024 * 1024:
        raise ValueError("Build envelope exceeds bounds")
    process.stdin.write(envelope)
    await process.stdin.drain()
    process.stdin.close()
    result = None
    for _ in range(4):
        line = await process.stdout.readline()
        if not line:
            break
        if len(line) > receipt_limit:
            raise ValueError("Worker receipt exceeds bounds")
        message = json.loads(line)
        if message == {"stage": stage} and result is None:
            cancelled(supervisor, job_id)
            supervisor.journal.transition(job_id, "running", stage, "stage_changed")
        elif type(message) is dict and set(message) == {"result"} and result is None:
            result = message["result"]
        else:
            raise ValueError("Invalid build receipt")
    else:
        raise ValueError("Too many build frames")
    if await process.wait() != 0 or result is None:
        raise ValueError("Build worker did not complete")
    if evaluation:
        from .evaluation_artifacts import validate_result

        validate_result(inputs, result)
        screen_public_record(result, execution.model_settings.protect_public)
        return result
    expected = {
        "schema_version": 1,
        "input_hash": inputs["input_hash"],
        "canonical_hash": inputs["canonical_hash"],
        "headless": True,
        "num_envs": 1,
        "num_steps": 20,
        "policy": "zero_action",
        "completed": True,
    }
    if (
        type(result) is not dict
        or set(result) != set(expected)
        or any(type(result[key]) is not type(value) or result[key] != value for key, value in expected.items())
    ):
        raise ValueError("Build receipt does not match frozen inputs")
    screen_public_record(result, execution.model_settings.protect_public)
    return result
