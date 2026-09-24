# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Lifespan-owned admission and single retained drive, never request-owned work."""

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, nullcontext, suppress

from ..contracts import canonical_json, parse_contract
from ..neo4j_store import validate_operation_id
from .resolvers import Overloaded, OwnedOffload


class CleanupUnknown(RuntimeError):
    """Keep resources and the instance lease: cleanup has not been established."""


class ExecutionOwner:
    CLOSE_TIMEOUT = 10.0

    def __init__(
        self, root, area, tokens, protect, *, execution_context: Callable[[], AbstractContextManager] = nullcontext
    ):
        self.root, self.area, self.tokens, self.protect = root, area, tokens, protect
        self._execution_context = execution_context
        self.admissions = OwnedOffload()
        self._driver = ThreadPoolExecutor(max_workers=1, thread_name_prefix="workflow-drive")
        self._admission_lock = threading.Lock()
        self._drive = None
        self._accepting = True
        self._run_ids = set()
        self._closed = False
        self._stop_lock = threading.Lock()
        self._stopper = ThreadPoolExecutor(max_workers=1, thread_name_prefix="workflow-stop")
        self._stop_future = None
        self._closing = None
        self.cleanup_unknown = False

    def _run(self, operation):
        """Bind the adapter context in the owned thread, independently of the HTTP request."""
        with self._execution_context():
            return operation()

    async def submit(self, auth, operation_id, raw_contract):
        """Shield admission together with retention; response loss never loses a drive."""

        def operation():
            self.tokens.recheck(auth)
            validate_operation_id(operation_id)
            contract = parse_contract(raw_contract)
            canonical = canonical_json(contract)
            with self._admission_lock:
                self.tokens.recheck(auth)
                self.root.authority.require_read(auth.principal)
                # Exact immutable replay precedes capacity, mutable model sources,
                # readiness, grants, and all worker factories.
                retained = self.root.store.lookup_submission(operation_id, canonical)
                if retained is None:
                    if not self._accepting or self._drive is not None and not self._drive.done():
                        raise Overloaded("Execution capacity unavailable")
                    if self._drive is not None:
                        # A returned callable is not cleanup proof. Uncertain
                        # prior ownership keeps this single slot unavailable.
                        self._verify_closed()
                    _, drive = self.root.admit(auth.principal, operation_id, canonical)
                    if drive is not None:
                        # Submit before receipt projection/HTTP response. This executor
                        # has exactly one reserved slot and no fresh-work queue.
                        with self._stop_lock:
                            if self._accepting:
                                self._drive = self._driver.submit(self._run, drive)
                receipt = self.root.service.read_submission(auth.principal, operation_id, protect=self.protect)
                if receipt is not None:
                    self._run_ids.add(receipt.run_id)
                return receipt

        return await self.admissions.run(lambda: self._run(operation))

    def request_stop(self):
        """Refuse immediately; stop on one owned lane independent of DB/HTTP drains."""
        with self._stop_lock:
            self._accepting = False
            if self._stop_future is None:
                self._stop_future = self._stopper.submit(self._stop)
        return self._stop_future

    def _stop(self):
        # No application/authority lock is held while stopping physical children.
        with self.root._lock:
            controls = tuple(self.root._cancel_controls.items())
            # Fence every already published run before attempting any slow stop.
            for _, state in controls:
                state.stopped = True
        error = None
        for run_id, state in controls:
            try:
                self.root._cancellation.stop_local(self.root, state.principal, run_id)
            except Exception as exc:
                error = exc
        try:
            self.root.authority.close()
        finally:
            # An in-flight admission may publish its control after our snapshot.
            # It cannot dispatch after request_stop; fence its late control too.
            with self.root._lock:
                for state in self.root._cancel_controls.values():
                    state.stopped = True
        if error is not None:
            raise CleanupUnknown("Local stop incomplete") from None

    def _verify_closed(self):
        """Check actual retained cleanup and physical local lease release after drain."""
        if self.root._recoveries:
            raise CleanupUnknown("Recovery ownership unresolved")
        for local in self.root._local.values():
            if local.busy or not local.retired or not local.lease._released:
                raise CleanupUnknown("Local ownership unresolved")
        scope_owner = self.root.store.get_owner()
        if scope_owner is not None and scope_owner.dirty:
            raise CleanupUnknown("Retained scope ownership unresolved")
        for run_id in self._run_ids | set(self.root._cancel_controls):
            cleanup = self.root.store.get_run_cleanup(run_id)
            if cleanup is None:
                raise CleanupUnknown("Retained cleanup unavailable")
            current = cleanup.current_scope_owner
            if current is not None and (
                current.dirty or self.root.store.get_retired_owner(current.owner_id) != current
            ):
                raise CleanupUnknown("Retained retirement unavailable")
            for intent in cleanup.intents:
                if intent.registration_id is not None and (
                    intent.cleanup_state != "recorded"
                    or intent.cleanup_observation != "owned_process_group_stopped"
                    or intent.retired_owner is None
                    or intent.retired_owner.dirty
                ):
                    raise CleanupUnknown("Worker cleanup unresolved")
                if intent.registration_id is not None:
                    if intent.kind == "generation":
                        registration = self.root.store.get_generation_attempt(run_id).registration
                    else:
                        registration = self.root.store.get_scene_intent(run_id, intent.intent_id).worker_registration
                    if registration is None or registration.registration_id != intent.registration_id:
                        raise CleanupUnknown("Exact cleanup registration unavailable")
                    from isaaclab_arena_examples.agentic_environment_generation.web_api.owned_process_group import (
                        OwnedProcessGroup,
                    )

                    identity = self.root.ownership.load(registration)
                    if OwnedProcessGroup(registration.pid, identity).members():
                        raise CleanupUnknown("Owned physical processes remain")

    async def close(self):
        """Bound observation, not worker lifetime; unknown retains the artifact area."""
        if self._closed:
            return
        if self.cleanup_unknown:
            raise CleanupUnknown("Execution cleanup unresolved")
        self.request_stop()
        if self._closing is None:
            self._closing = asyncio.create_task(self._drain())
            self._closing.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            await asyncio.wait_for(asyncio.shield(self._closing), timeout=self.CLOSE_TIMEOUT)
        except Exception:
            self.cleanup_unknown = True
            raise CleanupUnknown("Execution cleanup unresolved") from None
        # A prior observer's timeout is sticky even if the owned drain later ends.
        if self.cleanup_unknown:
            raise CleanupUnknown("Execution cleanup unresolved")
        if not self._closed:
            try:
                self.area.close()
            except Exception:
                self.cleanup_unknown = True
                raise CleanupUnknown("Artifact close unresolved") from None
            self._closed = True

    async def _drain(self):
        assert self._stop_future is not None
        await asyncio.shield(asyncio.wrap_future(self._stop_future))
        self._stopper.shutdown(wait=True)
        await self.admissions.drain()

        def finish():
            # Catch controls published by an admission already running at stop.
            self._stop()
            if self._drive is not None:
                # Failure is consumed, not treated as cleanup. Verification below
                # is mandatory even after an exceptional one-shot return.
                with suppress(Exception):
                    self._drive.result()
            self._driver.shutdown(wait=True)
            self.root.close()
            self._verify_closed()

        await self.admissions.close(finish)


class ExecutionContext:
    """Delegate unchanged retained queries; mutations use a separate owner budget."""

    def __init__(self, query, owner):
        self.query, self.owner = query, owner

    async def call(self, method, *args, **kwargs):
        # Cancel/resume are deliberately not public in this first submit-only
        # composition; the existing denied action projection remains truthful.
        return await self.query.call(method, *args, **kwargs)

    async def submit(self, operation_id, raw_contract):
        return await self.owner.submit(self.query.auth, operation_id, raw_contract)
