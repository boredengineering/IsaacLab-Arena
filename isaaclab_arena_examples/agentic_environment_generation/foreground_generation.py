# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Foreground owned generation transport; no queue and no automatic replay.

The spawn callback is trusted Python composition, never a wire field. Possession
of an exact PreparedWorker is a local cleanup capability, not public read access.
"""

import json
import os
import secrets
import selectors
import socket
import subprocess
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field

from isaaclab_arena.agentic_environment_generation.workbench.generation_diagnostics import GENERATION_STAGES
from isaaclab_arena.agentic_environment_generation.workflow.attempts import WorkerRegistration
from isaaclab_arena.agentic_environment_generation.workflow.coordinator import PreparedWorker, PrepareFailed
from isaaclab_arena.agentic_environment_generation.workflow.generation_output import validate_generation_output
from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence

from .web_api.generation_worker import workflow_allowance
from .web_api.owned_process_group import OwnedProcessGroup
from .web_api.process_identity import process_identity
from .web_api.provider_security import worker_environment


@dataclass(repr=False)
class _Owned:
    process: object
    contract: object
    group: object = None
    pidfd: int | None = None
    registration: object = None
    attempted: bool = False
    cleanup: object = None
    deadline: float = 0
    started: float = field(default_factory=time.monotonic)
    timer: object = None
    inputs: dict = field(default_factory=dict)
    lock: object = field(default_factory=threading.RLock)


class ForegroundGenerationReceiver:
    """Read outside coordinator locks, retain exact output before durable adoption.

    validate_document is an explicit trusted actual-schema callback; a fixture
    callback proves only composition. This object retains the receipt across DB
    outages. It does not discover crashed owners or authorize takeover/resend.
    """

    def __init__(self, worker, coordinator, lease, artifacts, *, validate_document, protect):
        if not callable(validate_document) or not callable(protect):
            raise ValueError("Trusted validation and protection required")
        self._worker, self._coordinator, self._lease = worker, coordinator, lease
        self._artifacts, self._validate, self._protect = artifacts, validate_document, protect
        self.receipt = None

    def _read(self, owned):
        fd = owned.process.stdout.fileno()
        os.set_blocking(fd, False)
        buffer, total, frames, result = b"", 0, 0, None
        with selectors.DefaultSelector() as selector:
            selector.register(fd, selectors.EVENT_READ)
            while True:
                remaining = owned.deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError("Generation result deadline")
                chunk = os.read(fd, 65536)
                if not chunk:
                    if buffer or result is None:
                        raise ValueError("Generation result missing")
                    return result
                total += len(chunk)
                if total > 2 * 1024 * 1024:
                    raise ValueError("Generation stream limit")
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    frame = json.loads(line)
                    frames += 1
                    if frames > 128 or type(frame) is not dict or len(frame) != 1 or result is not None:
                        raise ValueError("Invalid generation stream")
                    if set(frame) == {"stage"} and frame["stage"] in GENERATION_STAGES:
                        continue
                    if set(frame) == {"model_send"}:
                        handler = getattr(owned, "model_send_handler", None)
                        if not callable(handler):
                            raise ValueError("Unbound model send request")
                        handler(frame["model_send"])
                        continue
                    if set(frame) != {"result"}:
                        raise ValueError("Generation worker failed")
                    result = frame["result"]

    def receive(self, principal, prepared, *, release_lease=True):
        owned = self._worker._get(prepared)
        try:
            if self.receipt is None:
                raw = self._read(owned)
                checked = validate_generation_output(owned.inputs, raw, validate_document=self._validate)
                import yaml

                spec = yaml.safe_load(checked["yaml_text"])
                self.receipt = self._artifacts.write(
                    prepared.registration.fence,
                    prepared.registration,
                    owned.contract,
                    checked["yaml_text"].encode(),
                    spec,
                    protect=self._protect,
                    catalogue_ref=checked["catalogue_sha256"],
                    producer_metadata=raw,
                )
            result = self._coordinator.complete(principal, self.receipt, self._artifacts, protect=self._protect)
            evidence = self._worker.stop_owned(prepared, timeout_s=3)
            if release_lease:
                self._lease.retire_and_release(self._coordinator._service.bound_store, prepared.registration, evidence)
            return result
        except Exception:
            try:
                self._worker.stop_owned(prepared, timeout_s=3)
            finally:
                self._coordinator.fail_owned(prepared)
            raise RuntimeError("Foreground generation incomplete; retained ownership requires reconciliation") from None


class ForegroundGenerationWorker:
    """Retain kernel ownership before fallible identity capture; send at most once."""

    def __init__(self, *, spawn_spec=None, ownership_artifacts=None):
        self._ownership_artifacts = ownership_artifacts
        self._spawn_spec = spawn_spec or self._production_spawn
        self._owned = []

    @staticmethod
    def _production_spawn():
        return (
            [
                sys.executable,
                "-m",
                "isaaclab_arena_examples.agentic_environment_generation.web_api.generation_worker",
                "--parent-pid",
                str(os.getpid()),
            ],
            dict(
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
                env=worker_environment(None),
            ),
        )

    def _get(self, prepared):
        owned = prepared.owned_handle
        if not any(owned is item for item in self._owned) or prepared.registration != owned.registration:
            raise ValueError("Exact owned capability required")
        return owned

    def _arm(self, owned, deadline):
        owned.deadline = deadline
        if owned.timer is not None:
            owned.timer.cancel()

        def expire():
            # Retain the owned capability; uncertainty cannot release a lease.
            with suppress(Exception):
                self.stop_owned(PreparedWorker(owned.registration, owned), timeout_s=3)

        owned.timer = threading.Timer(max(0, deadline - time.monotonic()), expire)
        owned.timer.daemon = True
        owned.timer.start()

    def prepare(self, fence, contract, *, timeout_s):
        started = time.monotonic()
        deadline = started + min(timeout_s, contract.budget.per_operation_timeout_seconds)
        args, kwargs = self._spawn_spec()
        proc = subprocess.Popen(args, **kwargs)
        owned = _Owned(proc, contract, started=started)
        self._owned.append(owned)
        try:
            owned.pidfd = os.pidfd_open(proc.pid)
            # Retain __new__ before initialization: its pidfd may already exist
            # when descendant discovery fails.
            owned.group = OwnedProcessGroup.__new__(OwnedProcessGroup)
            OwnedProcessGroup.__init__(owned.group, proc.pid)
            identity = process_identity(proc.pid)
            if identity is None or identity["pgid"] != proc.pid or identity["sid"] != proc.pid:
                raise ValueError("Waiting worker identity unavailable")
            owned.registration = WorkerRegistration(
                registration_id="worker-" + secrets.token_hex(16),
                fence=fence,
                host=socket.gethostname(),
                boot=identity["boot_id"],
                pid=proc.pid,
                pgid=identity["pgid"],
                sid=identity["sid"],
                start_ticks=int(identity["start_ticks"]),
            )
            if self._ownership_artifacts is not None:
                self._ownership_artifacts.write(owned.registration, owned.group)
            if time.monotonic() >= deadline:
                raise TimeoutError
            self._arm(owned, deadline)
            return PreparedWorker(owned.registration, owned)
        except Exception:
            raise PrepareFailed(PreparedWorker(owned.registration, owned)) from None

    def _allowance(self, packet, owned):
        return workflow_allowance(packet)

    def send(self, prepared, envelope, *, timeout_s):
        owned = self._get(prepared)
        with owned.lock:
            if owned.attempted:
                raise RuntimeError("Private send already attempted")
            owned.attempted = True  # Even an ambiguous write is never retried.
            try:
                if type(envelope) is not bytes or len(envelope) > 512 * 1024 or not envelope.endswith(b"\n"):
                    raise ValueError
                packet = json.loads(envelope)
                allowance = self._allowance(packet, owned)
                execution = packet["workflow_execution"]
                if (
                    set(packet) != {"inputs", "config", "graph_config", "workflow_execution"}
                    or execution["registration"] != prepared.registration.model_dump(mode="json")
                    or execution["fence"] != prepared.registration.fence.model_dump(mode="json")
                    or packet["inputs"]["prompt"] != owned.contract.source.prompt
                    or execution["deadline"] > execution["admitted_at"] + owned.contract.budget.total_deadline_seconds
                    or time.monotonic() >= owned.deadline
                    or owned.cleanup is not None
                ):
                    raise ValueError
                owned.inputs = dict(packet["inputs"])
                self._arm(
                    owned,
                    min(
                        owned.deadline,
                        allowance.deadline,
                        owned.started + execution["reservation"]["runtime_allowance_seconds"],
                    ),
                )
                write_deadline = min(owned.deadline, time.monotonic() + timeout_s)
                fd = owned.process.stdin.fileno()
                os.set_blocking(fd, False)
                with selectors.DefaultSelector() as selector:
                    selector.register(fd, selectors.EVENT_WRITE)
                    offset = 0
                    while offset < len(envelope):
                        remaining = write_deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise TimeoutError
                        try:
                            offset += os.write(fd, envelope[offset:])
                        except BlockingIOError:
                            continue
                if not callable(getattr(owned, "model_send_handler", None)):
                    owned.process.stdin.close()
            except Exception:
                raise RuntimeError("Private generation send incomplete") from None

    def stop_owned(self, prepared, *, timeout_s):
        owned = self._get(prepared)
        with owned.lock:
            if owned.cleanup is not None:
                return owned.cleanup
            if owned.group is None:
                owned.group = OwnedProcessGroup.__new__(OwnedProcessGroup)
            if not hasattr(owned.group, "witnesses"):
                # Early initialization failed before the helper could acquire a
                # descriptor. Reuse the retained object; never replace a pinned group.
                OwnedProcessGroup.__init__(owned.group, owned.process.pid)
            owned.group.stop(term_timeout=min(0.2, timeout_s / 3), kill_timeout=max(0.01, timeout_s * 2 / 3))
            owned.process.wait(timeout=max(0.01, timeout_s / 3))
            if callable(getattr(owned, "model_send_handler", None)):
                owned.process.stdin.close()
            if owned.timer is not None:
                owned.timer.cancel()
            if owned.pidfd is not None:
                os.close(owned.pidfd)
                owned.pidfd = None
            if owned.registration is None:
                raise RuntimeError("Physical cleanup without registration; reconciliation required")
            owned.cleanup = CleanupEvidence(
                registration=owned.registration,
                evidence_ref="physical-" + secrets.token_hex(16),
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            )
            return owned.cleanup

    def cleanup_verified(self, registration, evidence):
        """Trusted FileLease callback; caller-supplied evidence alone proves nothing."""
        if type(registration) is not WorkerRegistration or type(evidence) is not CleanupEvidence:
            return False
        return any(
            owned.registration == registration and owned.cleanup is evidence and owned.group.cleaned
            for owned in self._owned
        )
