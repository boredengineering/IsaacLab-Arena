# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Bounded ownership of whole synchronous service calls, including cancelled awaits."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..service import WorkflowService
from .security import AuthContext

if TYPE_CHECKING:
    from .application import Composition


class Overloaded(RuntimeError):
    """The fixed owned work budget is full or draining."""


class OwnedOffload:
    """Two threads and four admitted futures; cancellation never frees a running slot."""

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="workflow-query")
        self._lock = threading.Lock()
        self._pending = set()
        self._accepting = True

    async def run(self, operation):
        with self._lock:
            if not self._accepting or len(self._pending) >= 4:
                raise Overloaded("Read capacity unavailable")
            future = self._executor.submit(operation)
            self._pending.add(future)

        def completed(done):
            with self._lock:
                self._pending.discard(done)

        future.add_done_callback(completed)
        # shield keeps queued work tracked too; no request owns the worker lifetime.
        waiter = asyncio.wrap_future(future)

        # A cancelled requester no longer retrieves this wrapper's exception.
        # Consume it without logging; active awaiters still receive the exception.
        def observed(done):
            if not done.cancelled():
                done.exception()

        waiter.add_done_callback(observed)
        return await asyncio.shield(waiter)

    async def drain(self):
        with self._lock:
            self._accepting = False
            pending = tuple(self._pending)
        if pending:
            await asyncio.gather(*(asyncio.wrap_future(f) for f in pending), return_exceptions=True)

    async def close(self, close_resource):
        await self.drain()
        try:
            if close_resource is not None:
                await asyncio.wrap_future(self._executor.submit(close_resource))
        finally:
            # All submitted work, including resource close, has settled.
            self._executor.shutdown(wait=True)


async def finish_cleanup(operation):
    """Complete owned draining even if the lifespan awaiter is cancelled again."""
    task = asyncio.create_task(operation)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError()


@dataclass
class QueryContext:
    service: WorkflowService
    composition: "Composition"
    executor: OwnedOffload
    auth: AuthContext | None = None
    artifact_root: object | None = None

    async def call(self, method, *args, **kwargs):
        def operation():
            self.composition.tokens.recheck(self.auth)
            if method in {"read_retained_bundle", "read_artifact_chunk"}:
                kwargs["artifact_root"] = self.artifact_root
                kwargs["artifact_binding"] = self.composition.tokens.binding
            if method == "read_run_inspection":
                from ..queries import ActionPermissionObservation

                def check_only(principal, retained):
                    return ActionPermissionObservation(
                        cancel="denied",
                        resume="denied",
                        observed_at=float(self.composition.tokens.clock()),
                    )

                kwargs["check_action_permission"] = check_only
            return getattr(self.service, method)(self.auth.principal, *args, protect=self.composition.protect, **kwargs)

        return await self.executor.run(operation)
