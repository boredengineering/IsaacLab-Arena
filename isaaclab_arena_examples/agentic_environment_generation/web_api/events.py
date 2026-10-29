# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Cursor-based event observation; disconnecting never changes job execution."""

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from isaaclab_arena.agentic_environment_generation.workbench.journal import ReplayGap

from .public_records import protect_public_record
from .security import cookie_token, require_session

router = APIRouter(prefix="/api")


class LeasedEventResponse(StreamingResponse):
    """Release stream admission even when the ASGI client disconnects or is cancelled."""

    def __init__(self, state, *args, **kwargs):
        self.state = state
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.state.active_streams -= 1


async def event_stream(journal, sessions, token, cursor, *, heartbeat=15, poll_interval=0.25, max_lag=256, protect=None):
    """Replay pages; HTTP callers supply current-policy screening for every emission.

    A protected/unscreenable event terminates with the existing resync signal,
    without an ID or cursor advance. Headers are already sent: this is not an
    HTTP error or a replacement durable event. A fresh snapshot may itself be
    unavailable under current policy; clients must not infer missing progress.
    """
    last_heartbeat = time.monotonic()
    while sessions.get(token) is not None:
        try:
            events = journal.events_after(cursor, max_lag=max_lag)
        except ReplayGap:
            if sessions.get(token) is None:
                return
            yield 'event: resync_required\ndata: {"detail":"Fetch a fresh workspace snapshot"}\n\n'
            return
        for event in events:
            if sessions.get(token) is None:
                return
            try:
                if protect is not None:
                    protect(event)
            except Exception:
                if sessions.get(token) is None:
                    return
                # Never serialize exception text, redact durable bytes, or skip an ID.
                yield 'event: resync_required\ndata: {"detail":"Public event unavailable; fetch a fresh workspace snapshot"}\n\n'
                return
            if sessions.get(token) is None:
                return
            cursor = event["id"]
            yield f"id: {cursor}\nevent: job\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
        if time.monotonic() - last_heartbeat >= heartbeat:
            if sessions.get(token) is None:
                return
            yield ": heartbeat\n\n"
            last_heartbeat = time.monotonic()
        await asyncio.sleep(poll_interval)


@router.get("/events", dependencies=[Depends(require_session)])
async def events(request: Request):
    raw = request.headers.get("last-event-id", request.query_params.get("after", "0"))
    if len(raw) > 19 or not raw.isascii() or not raw.isdecimal() or int(raw) > 2**63 - 1:
        raise HTTPException(422, "Invalid event cursor")
    state = request.app.state
    if state.active_streams >= 8:
        raise HTTPException(429, "Event stream capacity reached; use bounded polling")
    state.active_streams += 1
    return LeasedEventResponse(
        state,
        event_stream(
            state.journal, state.sessions, cookie_token(request), int(raw),
            protect=lambda event: protect_public_record(request, event),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
