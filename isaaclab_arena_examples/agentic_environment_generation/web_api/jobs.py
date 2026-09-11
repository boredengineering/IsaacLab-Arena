# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Typed, bounded diagnostic commands and durable operator snapshots."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .security import require_mutation, require_session

router = APIRouter(prefix="/api")


class DiagnosticInputs(BaseModel):
    """The only executable Slice 0 input contract."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    steps: int = Field(ge=1, le=10)
    delay_seconds: float = Field(ge=0.1, le=5)


class Submission(BaseModel):
    """Immutable operator-scoped command; no commands, URLs, paths or secrets."""

    model_config = ConfigDict(extra="forbid", strict=True)
    workspace_id: Literal["default"]
    kind: Literal["diagnostic"]
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    inputs: DiagnosticInputs


def lookup(request, job_id):
    try:
        return request.app.state.journal.get_job(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found") from None


@router.get("/jobs", dependencies=[Depends(require_session)])
async def jobs(request: Request):
    return request.app.state.journal.snapshot()


@router.get("/workspaces/default", dependencies=[Depends(require_session)])
async def workspace(request: Request):
    return {"id": "default", "name": "Arena workspace", **request.app.state.journal.snapshot()}


@router.get("/jobs/{job_id}", dependencies=[Depends(require_session)])
async def job(request: Request, job_id: str):
    return lookup(request, job_id)


@router.post("/jobs", status_code=202)
async def submit(request: Request, body: Submission, session=Depends(require_mutation)):
    if not request.app.state.diagnostics:
        raise HTTPException(422, "Test-only diagnostic jobs are disabled")
    try:
        return request.app.state.journal.submit(
            session["session_id"],
            body.workspace_id,
            body.kind,
            body.idempotency_key,
            body.inputs.model_dump(),
            max_pending=request.app.state.max_pending,
        )
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@router.post("/jobs/resume-queue", dependencies=[Depends(require_mutation)])
async def resume_queue(request: Request):
    request.app.state.journal.resume_queue()
    request.app.state.supervisor.paused = False
    request.app.state.supervisor.wake.set()
    return {"resumed": True}


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_mutation)])
async def cancel(request: Request, job_id: str):
    current = lookup(request, job_id)
    if current["status"] == "queued":
        return request.app.state.journal.transition(job_id, "cancelled", "cancelled", "cancelled")
    if current["status"] == "running":
        return request.app.state.supervisor.request_cancel(job_id)
    return current
