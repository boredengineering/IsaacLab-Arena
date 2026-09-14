# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Serialized API-loop admission and bounded, one-shot private subprocess dispatch.

Borrow configured ResearchStore handles and Journal for the ENTIRE scheduler lifetime.
Initialize PublicationAttempts worker support explicitly before construction; call
recover() explicitly at startup, before accepting requests. No routes or schema writes
are installed here. accept() is synchronous and enqueue(request_id) is an async
BackgroundTask hook. Accepted replay never creates authority or queues work.
worker_command is trusted deployment/test CODE, never an HTTP parameter.
"""

import asyncio
import os
import signal
import sys
import weakref
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
from isaaclab_arena.agentic_environment_generation.workbench.research_registry import (
    canonical_json,
    checked_identifier,
    digest,
)

from .owned_process_group import OwnedProcessGroup, boot_id, process_stat, same_identity
from .process_identity import process_identity
from .provider_security import worker_environment
from .publication_payload import build_private_envelope, parse_frame, prepare_publication, screen_worker_result
from .publication_worker import MAX_RESULT_BYTES, READY


@dataclass
class _Dispatch:
    attempts: object
    accepted: dict
    metadata: dict
    prepared: tuple
    task: object = None
    process: object = None
    anchor_fd: object = None
    group: object = None
    identity: object = None
    recorded: bool = False
    leased: bool = False
    passwords: set = field(default_factory=set)
    expected: dict = field(default_factory=dict)

    @property
    def fence(self):
        return {k: self.accepted[k] for k in ("effect_id", "attempt_id", "generation")}


async def _settle(task):
    """Do not abandon a spawn or cleanup operation when its caller is cancelled."""
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


class PublicationScheduler:
    """Own bounded dispatch slots, not credentials or request-scoped stores."""

    def __init__(
        self,
        *,
        journal,
        authorization,
        protect_public,
        configured_stores,
        queue_capacity=8,
        concurrency=1,
        worker_command=None,
        io_timeout=15,
    ):
        if type(queue_capacity) is not int or not 0 <= queue_capacity <= 128 or concurrency != 1:
            raise ValueError("Invalid publication scheduler capacity")
        if not callable(protect_public) or not 0 < io_timeout <= 120:
            raise ValueError("Invalid publication scheduler configuration")
        if authorization.sessions.journal is not journal or not configured_stores:
            raise ValueError("Publication component binding conflict")
        self.journal, self.authorization, self.protect_public = journal, authorization, protect_public
        self.stores = dict(configured_stores)
        self.attempts = {}
        for key, store in self.stores.items():
            checked_identifier(key)
            if store.store_id != key or store.registry.journal is not journal:
                raise ValueError("Publication component binding conflict")
            attempts = PublicationAttempts(
                journal,
                store.registry,
                authorizer=authorization,
                protect_public=protect_public,
                clock=authorization.clock,
            )
            if not attempts.worker_support_ready():
                raise ValueError("Publication worker schema not initialized")
            self.attempts[key] = attempts
        self.command = tuple(worker_command or (sys.executable, str(Path(__file__).with_name("publication_worker.py"))))
        self.capacity = queue_capacity + concurrency
        self.io_timeout = io_timeout
        self._slots = {}
        self._tasks = set()
        self._semaphore = asyncio.Semaphore(concurrency)
        self._loop = None
        self._stopping = False
        self._stop_task = None
        self.worker_count = 0

    def _serialized(self):
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if loop is not self._loop:
            raise RuntimeError("Publication scheduler requires its owning API loop")

    def accept(self, session, store_id, effect_id, request_id, *, operation="write", previous_request_id=None):
        """Authenticate, reserve capacity, prepare/issue/accept/bind without yielding.

        Returns {accepted_new, accepted, state}; post-accept bind failure returns the
        retained acceptance with paused state, never an ordinary untraceable error.
        Failed state observation returns state=None, disposition=
        "accepted_state_unavailable", and a static public error.
        Principal is the authenticated session ID, not caller-selected identity.
        """
        self._serialized()
        for value in (store_id, effect_id, request_id):
            checked_identifier(value)
        owner = checked_identifier(session["session_id"])
        current = self.authorization.sessions.get_by_id(owner)
        if current is None:
            raise ValueError("Publication session unavailable")
        if operation not in {"write", "renew", "reconcile"}:
            raise ValueError("Invalid publication operation")
        if previous_request_id is not None:
            checked_identifier(previous_request_id)
        store, attempts = self.stores[store_id], self.attempts[store_id]
        binding = dict(
            store_id=store_id,
            effect_id=effect_id,
            request_id=request_id,
            owner_session=owner,
            principal=owner,
            operation=operation,
            previous_request_id=previous_request_id,
        )
        request_digest = digest(binding)
        old = attempts.get_acceptance(request_id)
        if old is not None:
            if any(old[k] != v for k, v in binding.items()) or old["request_digest"] != request_digest:
                raise ValueError("Publication request scope conflict")
            intent = store.registry.get_publication_intent(effect_id)
            store.get_reservation(intent["reservation_id"])
            return dict(accepted_new=False, accepted=old, state=attempts.get_state(effect_id))
        if self._stopping or len(self._slots) >= self.capacity:
            raise ValueError("Publication scheduler unavailable")
        self._slots[request_id] = None  # Reservation precedes every durable admission.
        metadata = accepted = None
        try:
            prepared = prepare_publication(store, self.authorization, effect_id)
            capability = "graph_read" if operation == "reconcile" else "graph_write"
            metadata = self.authorization.issue(session, prepared[0], request_id, capability)
            result = attempts.accept_request(
                effect_id,
                request_id,
                metadata,
                owner_session=owner,
                principal=owner,
                store_id=store_id,
                operation=operation,
                request_digest=request_digest,
                previous_request_id=previous_request_id,
            )
            if not result["accepted_new"]:
                self.authorization.revoke(metadata["grant_id"])
                self._slots.pop(request_id, None)
                return result
            accepted = result["accepted"]
            dispatch = _Dispatch(attempts, accepted, metadata, prepared)
            self._slots[request_id] = dispatch
            self.authorization.bind_attempt(metadata, accepted["attempt_id"], accepted["generation"])
            return result
        except Exception:
            if metadata:
                with suppress(Exception):
                    self.authorization.revoke(metadata["grant_id"])
            self._slots.pop(request_id, None)
            if accepted is None:
                raise
            with suppress(Exception):
                self._pause(dispatch)
            try:
                state = attempts.get_state(effect_id)
            except Exception:
                return dict(
                    accepted_new=True,
                    accepted=accepted,
                    state=None,
                    disposition="accepted_state_unavailable",
                    error="Publication state unavailable",
                )
            return dict(accepted_new=True, accepted=accepted, state=state)

    async def enqueue(self, request_id):
        """Start only a newly admitted in-memory ticket; replay/restart never redispatch."""
        self._serialized()
        dispatch = self._slots.get(request_id)
        if self._stopping or dispatch is None or dispatch.task is not None:
            return False
        dispatch.task = asyncio.create_task(self._run(dispatch))
        self._tasks.add(dispatch.task)
        dispatch.task.add_done_callback(self._tasks.discard)
        return True

    def _pause(self, dispatch):
        if dispatch.accepted["capability"] == "graph_read":
            dispatch.attempts.finish_reconciliation_unknown(**dispatch.fence)
        else:
            dispatch.attempts.block_authorization(**dispatch.fence)

    async def _spawn(self, dispatch, env):
        process = await asyncio.create_subprocess_exec(
            *self.command,
            "--parent-pid",
            str(os.getpid()),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            start_new_session=True,
            limit=MAX_RESULT_BYTES,
        )
        # This continuation owns the child even if stop cancelled the awaiting runner.
        dispatch.process = process
        self.worker_count += 1
        dispatch.anchor_fd = os.pidfd_open(process.pid)
        weakref.finalize(dispatch, os.close, dispatch.anchor_fd)
        self._capture_worker(dispatch)
        return process

    def _capture_worker(self, dispatch):
        """Retry capture only while the retained pidfd proves the same live leader."""
        process = dispatch.process
        if dispatch.anchor_fd is None:
            raise ValueError("Publication worker ownership unavailable")
        signal.pidfd_send_signal(dispatch.anchor_fd, 0)
        stat = process_stat(process.pid)
        if stat is None or (stat["pgid"], stat["sid"]) != (process.pid, process.pid):
            raise ValueError("Publication worker identity unavailable")
        dispatch.identity = {"boot_id": boot_id(), **{k: stat[k] for k in ("start_ticks", "pgid", "sid")}}
        if not same_identity(process_stat(process.pid), stat):
            raise ValueError("Publication worker identity changed")
        signal.pidfd_send_signal(dispatch.anchor_fd, 0)
        # Retain the object BEFORE __init__: its pidfd must survive a failing
        # descendant scan. Minimal start identity is already anchored above.
        dispatch.group = OwnedProcessGroup.__new__(OwnedProcessGroup)
        try:
            dispatch.group.__init__(process.pid, dispatch.identity)
            identity = process_identity(process.pid)
            if identity is not None:
                if identity["boot_id"] != dispatch.identity["boot_id"] or not same_identity(
                    identity, dispatch.identity
                ):
                    raise ValueError("Publication worker identity changed")
                dispatch.identity = identity
        finally:
            dispatch.recorded = dispatch.attempts.record_worker(
                **dispatch.fence,
                capability=dispatch.accepted["capability"],
                pid=process.pid,
                identity=dispatch.identity,
            )
        if not dispatch.recorded:
            raise ValueError("Publication worker fenced")

    async def _run(self, dispatch):
        receipt = None
        try:
            await self._semaphore.acquire()
            dispatch.leased = True
            if self._stopping:
                return
            config, _ = self.authorization.resolve(
                dispatch.metadata,
                capability=dispatch.accepted["capability"],
                request_id=dispatch.accepted["request_id"],
                **dispatch.fence,
            )
            dispatch.passwords.add(config["password"])
            del config
            env = worker_environment(None)
            env = {k: v for k, v in env.items() if not any(p in k or p in v for p in dispatch.passwords)}
            spawn = asyncio.create_task(self._spawn(dispatch, env))
            try:
                process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                await _settle(spawn)
                raise
            async with asyncio.timeout(self.io_timeout):
                raw_ready = await process.stdout.readline()
                if canonical_json(parse_frame(raw_ready, 1024)) != canonical_json(READY) or self._stopping:
                    raise ValueError("Publication worker readiness unavailable")

                def prepare_private(config, intent):
                    if canonical_json(intent) != canonical_json(dispatch.prepared[0]):
                        raise ValueError("Publication intent changed")
                    dispatch.passwords.add(config["password"])
                    raw, expected = build_private_envelope(*dispatch.prepared, config, dispatch.accepted["capability"])
                    dispatch.expected = expected
                    return raw

                raw = dispatch.attempts.release_worker(
                    **dispatch.fence,
                    worker_identity=dispatch.identity,
                    grant_metadata=dispatch.metadata,
                    prepare_private=prepare_private,
                )
                if raw is None:
                    raise ValueError("Publication worker release denied")
                process.stdin.write(raw)  # Deliberately no await after committed release.
                del raw
                await process.stdin.drain()
                process.stdin.close()
                await process.stdin.wait_closed()
                raw_result = await process.stdout.readline()
                if len(raw_result) > MAX_RESULT_BYTES or await process.stdout.read(1):
                    raise ValueError("Publication result framing unavailable")
                exit_code = await process.wait()
                candidate = screen_worker_result(raw_result, dispatch.expected, dispatch.passwords)
                if exit_code == 0:
                    receipt = candidate
        except (Exception, asyncio.CancelledError):
            pass  # Never publish subprocess exceptions or raw output.
        finally:
            await _settle(asyncio.create_task(self._finish(dispatch, receipt)))

    async def _finish(self, dispatch, receipt=None):
        try:
            if dispatch.process is not None and dispatch.group is None:
                self._capture_worker(dispatch)
            if dispatch.group is not None:
                if not all(hasattr(dispatch.group, name) for name in ("boot", "start", "expected_group", "witnesses")):
                    dispatch.group.__init__(dispatch.process.pid, dispatch.identity)
                await asyncio.to_thread(dispatch.group.stop, term_timeout=0.1, kill_timeout=2)
            if dispatch.process is not None:
                if dispatch.process.stdin is not None:
                    dispatch.process.stdin.close()
                await asyncio.wait_for(dispatch.process.wait(), self.io_timeout)
            if dispatch.recorded:
                # Physical cleanup, THEN accept receipt, THEN close callback/ownership.
                if receipt is not None:
                    self.protect_public(receipt)
                    dispatch.attempts.complete_worker_verified(
                        **dispatch.fence,
                        worker_identity=dispatch.identity,
                        receipt=receipt,
                        comparator=lambda intent, value: canonical_json(intent) == canonical_json(dispatch.prepared[0])
                        and canonical_json(value) == canonical_json(dispatch.expected),
                    )
                else:
                    dispatch.attempts.close_worker_unknown(**dispatch.fence, worker_identity=dispatch.identity)
                dispatch.attempts.worker_cleaned(**dispatch.fence, worker_identity=dispatch.identity)
            else:
                self._pause(dispatch)
            if dispatch.leased:
                dispatch.leased = False
                self._semaphore.release()
            dispatch.passwords.clear()
            dispatch.expected.clear()
            self._slots.pop(dispatch.accepted["request_id"], None)
        except Exception:
            # Keep identity, captured passwords and capacity until explicit cleanup.
            with suppress(Exception):
                if dispatch.recorded:
                    dispatch.attempts.close_worker_unknown(**dispatch.fence, worker_identity=dispatch.identity)
                else:
                    self._pause(dispatch)
        finally:
            self.authorization.revoke(dispatch.metadata["grant_id"])

    async def wait_idle(self):
        """Wait for queued/running tasks; failed cleanup still occupies retained slots."""
        self._serialized()
        while self._tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(self._tasks)))

    async def cancel(self, store_id, effect_id, *, attempt_id, generation):
        """Trusted authenticated caller only; stale expected attempts cannot kill replacements."""
        self._serialized()
        attempts = self.attempts[store_id]
        state = attempts.get_state(effect_id)
        if (state["attempt_id"], state["generation"]) != (attempt_id, generation):
            return False
        attempts.cancel(effect_id)
        for dispatch in tuple(self._slots.values()):
            if dispatch and dispatch.fence == dict(effect_id=effect_id, attempt_id=attempt_id, generation=generation):
                if dispatch.task is not None and not dispatch.task.done():
                    dispatch.task.cancel()
                    try:
                        await _settle(dispatch.task)
                    except asyncio.CancelledError:
                        # A task cancelled before its first instruction has no finally.
                        await _settle(asyncio.create_task(self._finish(dispatch)))
                else:
                    await _settle(asyncio.create_task(self._finish(dispatch)))
        return True

    async def recover(self):
        """Explicit startup fencing followed by owned cleanup; never reconstruct authority."""
        self._serialized()
        if self._slots or self._tasks:
            raise ValueError("Publication recovery requires idle startup")
        count = 0
        seen = set()
        for attempts in self.attempts.values():
            if attempts.registry.registry_id in seen:
                continue
            seen.add(attempts.registry.registry_id)
            count += attempts.recover_worker_dispatch()  # Fence synchronously before first await.
        for attempts in self.attempts.values():
            for worker in attempts.pending_workers():
                group = OwnedProcessGroup(worker["pid"], worker["identity"])
                await _settle(asyncio.create_task(asyncio.to_thread(group.stop, term_timeout=0)))
                attempts.worker_cleaned(
                    **{k: worker[k] for k in ("effect_id", "attempt_id", "generation")},
                    worker_identity=worker["identity"],
                )
        return count

    async def stop(self):
        """Fence admission immediately and await late spawns plus all owned cleanup."""
        self._serialized()
        self._stopping = True
        if self._stop_task is None or (
            self._stop_task.done() and (self._stop_task.cancelled() or self._stop_task.exception() is not None)
        ):
            self._stop_task = asyncio.create_task(self._stop())
        await _settle(self._stop_task)

    async def _stop(self):
        fencing_failed = False
        for attempts in self.attempts.values():
            try:
                attempts.recover_worker_dispatch()
            except Exception:
                fencing_failed = True  # A broken ledger must not bypass physical cleanup.
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        for dispatch in tuple(self._slots.values()):
            if dispatch is not None:
                await self._finish(dispatch)
        if self._slots or fencing_failed:
            raise RuntimeError("Publication shutdown fencing or owned cleanup remains pending")
