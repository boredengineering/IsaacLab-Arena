# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Identifier-only publication HTTP adapters; session IDs are not multiuser identity."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from isaaclab_arena.agentic_environment_generation.workbench.research_registry import checked_identifier

from .security import require_mutation, require_session

router = APIRouter(prefix="/api/research/stores/{store_id}/publications")
IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"


class WriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(pattern=IDENTIFIER)


class FollowupRequest(WriteRequest):
    previous_request_id: str = Field(pattern=IDENTIFIER)


class CancelRequest(WriteRequest):
    attempt_id: str = Field(pattern=IDENTIFIER)
    generation: int = Field(ge=1)


def enabled(request: Request):
    if not request.app.state.publication_admitting:
        raise HTTPException(503, "Publication unavailable")
    return request.app.state.publication_scheduler


def scope(run, session, store_id, effect_id, request_id, *, required=False):
    for value in (store_id, effect_id, request_id):
        checked_identifier(value)
    store = run.stores[store_id]
    intent = store.registry.get_publication_intent(effect_id)
    store.get_reservation(intent["reservation_id"])
    accepted = run.attempts[store_id].get_acceptance(request_id)
    if accepted is None:
        if required:
            raise ValueError("Missing acceptance")
        return None
    expected = dict(
        store_id=store_id,
        effect_id=effect_id,
        request_id=request_id,
        owner_session=session["session_id"],
        principal=session["session_id"],
        registry_id=store.registry.registry_id,
    )
    if any(accepted[k] != value for k, value in expected.items()):
        raise ValueError("Publication scope conflict")
    return accepted


@router.get("/{effect_id}")
@router.get("/{effect_id}/requests/{request_id}")
async def disposition(
    request: Request,
    store_id: str,
    effect_id: str,
    request_id: str,
    run=Depends(enabled),
    session=Depends(require_session),
):
    try:
        accepted = scope(run, session, store_id, effect_id, request_id, required=True)
        state = run.attempts[store_id].get_state(effect_id)
        result = dict(accepted=accepted, state=state)
        request.app.state.model_settings.protect_public(result)
        return result
    except (KeyError, ValueError, OSError):
        raise HTTPException(409, "Publication state unavailable") from None


@router.post("/{effect_id}/write", status_code=202)
async def write(
    request: Request,
    store_id: str,
    effect_id: str,
    body: WriteRequest,
    background: BackgroundTasks,
    run=Depends(enabled),
    session=Depends(require_mutation),
):
    return admit(request, store_id, effect_id, body, background, run, session, "write")


def admit(request, store_id, effect_id, body, background, run, session, operation):
    try:
        request.app.state.model_settings.protect_public(body.model_dump())
        scope(run, session, store_id, effect_id, body.request_id)
        current = run.attempts[store_id].get_state(effect_id)
        if current["request_id"] is not None:
            scope(run, session, store_id, effect_id, current["request_id"], required=True)
        previous = getattr(body, "previous_request_id", None)
        if previous is not None:
            scope(run, session, store_id, effect_id, previous, required=True)
        result = run.accept(
            session, store_id, effect_id, body.request_id, operation=operation, previous_request_id=previous
        )
    except (KeyError, ValueError, OSError):
        raise HTTPException(409, "Publication admission unavailable or conflicting") from None
    if result["accepted_new"]:
        background.add_task(run.enqueue, body.request_id)
    return JSONResponse(
        result,
        status_code=202,
        headers={"Location": f"/api/research/stores/{store_id}/publications/{effect_id}/requests/{body.request_id}"},
    )


@router.post("/{effect_id}/reconcile", status_code=202)
async def reconcile(
    request: Request,
    store_id: str,
    effect_id: str,
    body: FollowupRequest,
    background: BackgroundTasks,
    run=Depends(enabled),
    session=Depends(require_mutation),
):
    return admit(request, store_id, effect_id, body, background, run, session, "reconcile")


@router.post("/{effect_id}/renew", status_code=202)
async def renew(
    request: Request,
    store_id: str,
    effect_id: str,
    body: FollowupRequest,
    background: BackgroundTasks,
    run=Depends(enabled),
    session=Depends(require_mutation),
):
    return admit(request, store_id, effect_id, body, background, run, session, "renew")


@router.post("/{effect_id}/cancel")
async def cancel(
    request: Request,
    store_id: str,
    effect_id: str,
    body: CancelRequest,
    run=Depends(enabled),
    session=Depends(require_mutation),
):
    try:
        accepted = scope(run, session, store_id, effect_id, body.request_id, required=True)
        state = run.attempts[store_id].get_state(effect_id)
        if any(
            accepted[k] != getattr(body, k) or state[k] != getattr(body, k)
            for k in ("request_id", "attempt_id", "generation")
        ):
            raise ValueError("Stale cancellation")
        cancelled = await run.cancel(store_id, effect_id, attempt_id=body.attempt_id, generation=body.generation)
        return {"cancelled": cancelled}
    except (KeyError, ValueError, OSError):
        raise HTTPException(409, "Publication cancellation unavailable or conflicting") from None
