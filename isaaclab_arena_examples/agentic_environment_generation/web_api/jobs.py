# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Typed, bounded diagnostic commands and durable operator snapshots."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .public_records import protect_public_record
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
    return protect_public_record(request, request.app.state.journal.snapshot())


@router.get("/workspaces/default", dependencies=[Depends(require_session)])
async def workspace(request: Request):
    return protect_public_record(request, {"id": "default", "name": "Arena workspace", **request.app.state.journal.snapshot()})


@router.get("/jobs/{job_id}", dependencies=[Depends(require_session)])
async def job(request: Request, job_id: str):
    return protect_public_record(request, lookup(request, job_id))


@router.post("/jobs", status_code=202)
async def submit(request: Request, body: Submission, session=Depends(require_mutation)):
    if not request.app.state.diagnostics:
        raise HTTPException(422, "Test-only diagnostic jobs are disabled")
    protect_public_record(request, body.model_dump())
    prior = request.app.state.journal.get_submission(body.workspace_id, body.idempotency_key)
    if prior is not None:
        protect_public_record(request, prior)
    try:
        accepted = request.app.state.journal.submit(
            session["session_id"],
            body.workspace_id,
            body.kind,
            body.idempotency_key,
            body.inputs.model_dump(),
            max_pending=request.app.state.max_pending,
        )
    except ValueError:
        raise HTTPException(409, "Job submission conflicts with stored inputs or queue capacity") from None
    try:
        return protect_public_record(request, accepted)
    except Exception:
        # Acceptance is durable even if its public representation cannot be returned.
        raise HTTPException(503, "Job accepted; public job record unavailable. Retain the exact submission for lookup") from None


@router.post("/jobs/resume-queue", dependencies=[Depends(require_mutation)])
async def resume_queue(request: Request):
    request.app.state.journal.resume_queue()
    request.app.state.supervisor.paused = False
    request.app.state.supervisor.wake.set()
    return {"resumed": True}


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_mutation)])
async def cancel(request: Request, job_id: str):
    """Keep cancellation independent of record visibility; never claim cleanup from intent.

    Safe responses remain complete Jobs. If the resulting record is protected,
    the explicit 503 reports public-status unavailability *after* handling the
    cancellation, not rollback or terminal cancellation. Retrying is idempotent.
    """
    current = lookup(request, job_id)
    if current["status"] == "blocked_authorization":
        journal = request.app.state.journal
        attempt = journal.get_attempt(job_id)
        if attempt is not None:
            journal.cancel_attempt(
                job_id, attempt["attempt_id"], attempt["generation"], expected_state="blocked_authorization"
            )
        current = journal.get_job(job_id)
    if current["status"] == "queued":
        current = request.app.state.journal.cancel_queued(job_id)
    if current["status"] == "running":
        current = request.app.state.supervisor.request_cancel(job_id)
    try:
        return protect_public_record(request, current)
    except Exception:
        raise HTTPException(503, "Cancellation handled; public job record unavailable. Cancellation may still be pending; read the job again for status") from None
