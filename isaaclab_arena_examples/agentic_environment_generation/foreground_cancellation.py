# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Application cancellation composition; no database/model constructors or lifecycle.

Frozen API (all functions receive the existing ForegroundWorkflow application):
    start_owner_control(app, principal, run_id) -> OwnerStopServer
    stop_requested(app, run_id) -> bool
    stop_local(app, principal, run_id) -> owner-delivery receipt
    cancel_workflow(app, principal, run_id) -> public workflow result + local_stop
    finish_cancelled(app, principal, run_id, local) -> bool (retired)
    close_controls(app) -> None

Integration hooks for ForegroundWorkflow (not optional):
* After a fresh service.submit, start_owner_control BEFORE the admission listener,
  bind_run, prior/worker factories or any prepare. Resume starts it before work too.
* Keep app._lock an RLock and app._local the existing phase-owner table. Never
  hold app._lock across DB/authority IO or dispatch/receive. Under that lock check
  stop_requested before publishing each generation/scene local; inherit a latched
  stop instead of replacing it with local.stopped=False. Before dispatch or scene
  drive call stop_local again if latched, then return without dispatch. A published
  coordinator/ports must be stopped even when local.handle has not returned yet.
* Scene ports must be installed under the same short lock and stopped before any
  prepare if the latch won during construction. Generation -> scene and resume
  must check the RUN latch, including when the preceding owner is retired.
* Replace cancel with cancel_workflow; do not status/get_run first. The local
  server callback uses the frozen principal, NOT _check/current grant expiry.
* After receive/drive, including exception/finally paths, if latched OR durable
  run state is cancel_requested/cancelled, invoke finish_cancelled with the exact
  current local. It stops first, ACKs only supervisor-owned cleanup, and delegates
  exact retirement/readback/unlock to existing ports/lease. Retain local.handle
  from dispatch/CompletionIncomplete before this call; absent handle while busy
  is unresolved, never permission to unlock. Retry after DB recovery, no resend.
  If only local delivery succeeded during a DB outage, retry cancel_workflow to
  persist the request; finish_cancelled never invents durable cancellation.
  A never-prepared/registration-uncertain lease remains held unless the existing
  owning adapter supplies its verified retirement path; no DB-derived capability.
* close_controls belongs in close's finally after local stop attempts. It only
  closes endpoints; it never unlocks leases or clears the sticky run latch.

Results keep local_stop.delivery separate from durable_cancellation. A delivery
receipt is never physical CleanupEvidence. The helper's run latch is memory-only
send fencing, NOT another authoritative workflow state machine. Root integration
and a fresh active CLI/Neo4j proof remain required to close CANCEL-01.
"""

import hashlib
import json
from types import SimpleNamespace

from .foreground_control import OwnerStopServer, request_owner_stop


def _scope(app):
    return hashlib.sha256(
        json.dumps(app.authority.scope, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _receipt(delivery):
    return dict(delivery=delivery, remote_effects="unknown", durable_cancellation="unconfirmed")


def start_owner_control(app, principal, run_id):
    """Start before publishing admission; preserve a run's original frozen binding."""
    with app._lock:
        if app._closed:
            raise ValueError("Foreground workflow closed")
        if not hasattr(app, "_cancel_controls"):
            app._cancel_controls = {}
        previous = app._cancel_controls.get(run_id)
        if previous is not None:
            if previous.principal != principal:
                raise PermissionError("Creator required")
            return previous.server
        state = SimpleNamespace(principal=principal, stopped=False, server=None)

        def stop():
            if stop_local(app, principal, run_id)["delivery"] != "delivered":
                raise RuntimeError("Owned cleanup pending")

        server = OwnerStopServer(app.private_parent, run_id=run_id, principal=principal, scope=_scope(app), stop=stop)
        app._cancel_controls[run_id] = state
        try:
            state.server = server.start()
        except BaseException:
            del app._cancel_controls[run_id]
            raise
        return server


def stop_requested(app, run_id):
    """Read the sticky run-level send fence, never a phase-local replacement."""
    with app._lock:
        state = getattr(app, "_cancel_controls", {}).get(run_id)
        return state is not None and state.stopped


def stop_local(app, principal, run_id):
    """Latch a frozen creator's local stop without database or authority calls."""
    with app._lock:
        state = getattr(app, "_cancel_controls", {}).get(run_id)
        if state is None:
            return _receipt("no_owner")
        if type(principal) is not str or principal != state.principal:
            raise PermissionError("Creator required")
        local = app._local.get(run_id)
        if local is not None and local.principal != principal:
            raise PermissionError("Creator required")
        state.stopped = True
        if local is not None:
            local.stopped = True
    # Do not hold the application publication lock across lower-level interlocks.
    # The root must recheck the run latch before publishing/dispatching a phase.
    if local is not None and not local.retired:
        try:
            if local.coordinator is not None:
                if local.coordinator.stop_local(principal).cleanup_pending:
                    return _receipt("unconfirmed")
            elif local.ports is not None:
                local.cancel_cleanups = local.ports.stop_local()
        except Exception:
            return _receipt("unconfirmed")
    return _receipt("delivered")


def stop_only(app, principal, run_id):
    """Deliver the existing exact-target stop without any durable cancellation.

    Current API/cancel authority is the caller's prerequisite. Frozen creator and
    scope authentication, sticky fencing and exact owned cleanup stay unchanged.
    """
    from isaaclab_arena.agentic_environment_generation.workflow.commands import LocalStopObservation

    delivery = stop_local(app, principal, run_id)
    if delivery["delivery"] == "no_owner" and getattr(app, "_owner_control", True):
        delivery = request_owner_stop(app.private_parent, run_id=run_id, principal=principal, scope=_scope(app))
    return LocalStopObservation.model_validate(delivery)


def cancel_workflow(app, principal, run_id):
    """Deliver local stop first; report authoritative cancellation independently."""
    delivery = stop_local(app, principal, run_id)
    if delivery["delivery"] == "no_owner" and getattr(app, "_owner_control", True):
        delivery = request_owner_stop(app.private_parent, run_id=run_id, principal=principal, scope=_scope(app))
    app._check(principal)
    try:
        # Physical stop can let the owner record cleanup/reconciliation between
        # our read and CAS. Re-read only this rejected cancellation transaction;
        # never retry worker release, cleanup authority or an unavailable store.
        for attempt in range(3):
            current = app.status(principal, run_id)
            if current["disposition"] == "unknown" or "cancel" not in current["available_actions"]:
                break
            try:
                app.store.request_cancel(run_id, current["version"])
            except ValueError as exc:
                if str(exc) != "stale cancellation version or inactive run" or attempt == 2:
                    raise
                continue
            current = app.status(principal, run_id)
            break
        with app._lock:
            local = app._local.get(run_id)
        if local is not None and current["state"] in ("cancel_requested", "cancelled"):
            finish_cancelled(app, principal, run_id, local)
            current = app.status(principal, run_id)
    except Exception:
        current = app._unknown(run_id)
    return app._public(
        dict(
            current,
            local_stop=delivery,
            durable_cancellation="confirmed" if current["state"] == "cancelled" else "unconfirmed",
        )
    )


def finish_cancelled(app, principal, run_id, local):
    """Finish only exact local cleanup through existing durable retirement methods."""
    with app._lock:
        if app._local.get(run_id) is not local or local.principal != principal:
            raise PermissionError("Exact current owner required")
        if local.retired:
            return True
        if getattr(local, "cancel_finishing", False):
            return False
        local.cancel_finishing = True
    try:
        if stop_local(app, principal, run_id)["delivery"] != "delivered":
            return False
        run = app.store.get_run(run_id)
        if run.state not in ("cancel_requested", "cancelled"):
            return False
        if local.ports is not None:
            for fence, cleanup in local.cancel_cleanups:
                app.store.acknowledge_scene_cleanup(fence, cleanup)
        else:
            handle = local.handle
            if (
                run.state == "cancelled" and not getattr(local, "busy", True)
                and (handle is None or (handle.prepared is None and handle.fence is None and handle.owner_epoch is None))
            ):
                # A rejected reservation may leave an actual flock but no owned
                # worker. The stopped coordinator and the lease's preparation
                # latch—not absence of a DB row alone—make this release safe.
                if app.store.get_generation_attempt(run_id) is not None:
                    return False
                owner = app.store.get_owner()
                if owner is not None and owner.dirty:
                    return False
                local.lease.release_never_prepared()
                local.retired = True
                return True
            if handle is None or handle.prepared is None or handle.cleanup is None:
                return False
            registration, cleanup = handle.prepared.registration, handle.cleanup
            if local.worker.cleanup_verified(registration, cleanup) is not True:
                return False
            app.store.acknowledge_cleanup(handle.fence, cleanup)
            retained = app.store.get_attempt(handle.fence)
            if retained.registration != registration or retained.cleanup != cleanup:
                return False
        if app.store.get_run(run_id).state != "cancelled":
            return False
        if local.ports is not None:
            local.ports.retire_cancelled()
        else:
            local.lease.retire_and_release(app.store, registration, cleanup)
        local.retired = True
        return True
    except Exception:
        # Exact capabilities and held ownership remain available for explicit retry.
        return False
    finally:
        with app._lock:
            local.cancel_finishing = False


def close_controls(app):
    """Close endpoints without erasing sticky stops or implying lease release."""
    with app._lock:
        controls = tuple(getattr(app, "_cancel_controls", {}).values())
    for state in controls:
        state.server.close()
