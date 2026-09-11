# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Session routes and reusable browser authorization dependencies."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api")


class EmptySessionInput(BaseModel):
    """Session establishment accepts only an empty JSON object."""

    model_config = ConfigDict(extra="forbid")


def cookie_token(request: Request):
    return request.cookies.get(request.app.state.cookie_name)


def require_origin(request: Request):
    expected = request.app.state.browser_origins.get(request.headers.get("host"))
    if expected is None or request.headers.get("origin") != expected:
        raise HTTPException(403, "Exact Origin required")


def require_session(request: Request):
    session = request.app.state.sessions.get(cookie_token(request))
    if session is None:
        raise HTTPException(401, "Session expired or revoked")
    return session


def require_mutation(request: Request, session=Depends(require_session)):
    require_origin(request)
    if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), session["csrf_token"]):
        raise HTTPException(403, "CSRF token required")
    return session


def set_cookie(request, response, token):
    response.set_cookie(
        request.app.state.cookie_name,
        token,
        httponly=True,
        samesite="strict",
        path="/api",
        secure=request.app.state.secure_cookie,
        max_age=int(request.app.state.absolute_seconds),
    )


@router.post("/sessions", dependencies=[Depends(require_origin)])
async def establish(request: Request, response: Response, body: EmptySessionInput):
    session = request.app.state.sessions.get(cookie_token(request))
    if session is None:
        session, token = request.app.state.sessions.create()
        set_cookie(request, response, token)
    return session


@router.get("/session")
async def inspect_session(session=Depends(require_session)):
    return session


@router.post("/session/activity", dependencies=[Depends(require_mutation)])
async def activity(request: Request):
    session = request.app.state.sessions.activity(cookie_token(request))
    if session is None:
        raise HTTPException(401, "Session expired or revoked")
    return session


@router.delete("/session", dependencies=[Depends(require_mutation)])
async def revoke(request: Request, response: Response):
    request.app.state.sessions.revoke(cookie_token(request))
    response.delete_cookie(
        request.app.state.cookie_name,
        path="/api",
        httponly=True,
        samesite="strict",
        secure=request.app.state.secure_cookie,
    )
    return {"revoked": True}
