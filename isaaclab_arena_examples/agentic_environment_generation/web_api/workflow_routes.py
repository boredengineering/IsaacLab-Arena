# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit single-operator workspace approval for blocked, unreleased work."""

import hashlib
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .public_records import protect_public_record
from .security import require_mutation, require_session

router = APIRouter(prefix="/api/editor/generations")


class Reauthorize(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    credential_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def screen_record(request, record):
    """Keep public-policy failures outside domain rejection sealing."""
    try:
        protect_public_record(request, record)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            503,
            "Workflow renewal public record unavailable; retain the exact request for disposition lookup",
        ) from None


def accepted_response(request, accepted, *, fresh=False):
    """Withhold unsafe snapshots without changing their durable acceptance."""
    try:
        protect_public_record(request, accepted)
    except HTTPException:
        if not fresh:
            raise
    except Exception:
        pass
    else:
        return accepted
    raise HTTPException(
        503,
        "Workflow renewal accepted; public job record unavailable. "
        "Retain the exact renewal request for disposition lookup",
    ) from None


@router.post("/{job_id}/reauthorize", status_code=202)
async def reauthorize(request: Request, job_id: str, body: Reauthorize, session=Depends(require_mutation)):
    """Approve the frozen workspace operation using this active browser session."""
    state = request.app.state
    fingerprint = hashlib.sha256(
        json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    metadata = None
    fresh = False
    screened = False
    try:
        job = state.journal.get_job(job_id)
        if job["workspace_id"] != "default":
            raise KeyError(job_id)
        try:
            replay = state.journal.get_authorization_replay(job_id, body.idempotency_key, fingerprint)
        except ValueError:
            # A conflict with accepted work is not rejection proof and needs no credentials.
            raise HTTPException(409, "Workflow renewal conflicts with an accepted request") from None
        if replay is not None:
            return accepted_response(request, replay)
        try:
            previous = state.journal.authorization_disposition(job_id, body.idempotency_key, fingerprint)
        except ValueError:
            raise HTTPException(409, "Workflow renewal disposition unavailable or conflicting") from None
        if previous["code"] == "renewal_rejected":
            screen_record(request, previous)
            raise HTTPException(409, previous)
        screen_record(request, body.model_dump())
        screened = True
        screen_record(request, job)
        attempt = state.journal.renewable_attempt(job_id)
        metadata = state.workflow_authorization.capture_renewal(session, job, credential_ref=body.credential_ref)
        record = {
            "schema_version": 1,
            "workflow_authorization": metadata,
            "approval": "single_operator_workspace",
            "blocked_attempt": attempt,
        }
        screen_record(request, record)
        accepted, fresh = state.journal.renew_authorization(
            job_id,
            body.idempotency_key,
            fingerprint,
            attempt,
            record,
            max_pending=state.max_pending,
        )
        if fresh:
            state.supervisor.wake.set()
        return accepted_response(request, accepted, fresh=fresh)
    except KeyError:
        raise HTTPException(404, "Generation not found") from None
    except ValueError:
        # Never seal raw request bytes after any early failure.
        if not screened:
            screen_record(request, body.model_dump())
        try:
            outcome = state.journal.seal_authorization_rejection(job_id, body.idempotency_key, fingerprint)
        except (ValueError, sqlite3.Error):
            raise HTTPException(409, "Workflow renewal disposition unavailable or conflicting") from None
        if outcome.get("code") == "renewal_rejected":
            screen_record(request, outcome)
            raise HTTPException(409, outcome) from None
        return accepted_response(request, outcome)
    except sqlite3.Error:
        raise HTTPException(
            409,
            "Workflow renewal unavailable or conflicting; profile changes require a new operation",
        ) from None
    finally:
        # Only a committed winner retains its new private grants.
        if metadata is not None and not fresh:
            state.workflow_authorization.rollback(metadata)


@router.get("/{job_id}/reauthorization-disposition")
async def disposition(
    request: Request,
    job_id: str,
    idempotency_key: str = Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    fingerprint: str = Query(pattern=r"^[a-f0-9]{64}$"),
    session=Depends(require_session),
):
    """Read bounded public disposition for one exact workspace binding."""
    try:
        if request.app.state.journal.get_job(job_id)["workspace_id"] != "default":
            raise KeyError(job_id)
        outcome = request.app.state.journal.authorization_disposition(job_id, idempotency_key, fingerprint)
        if outcome["code"] == "renewal_accepted":
            # Acceptance proof is withheld with its immutable snapshot, not
            # reinterpreted as nonacceptance under the current privacy policy.
            accepted = request.app.state.journal.get_authorization_replay(job_id, idempotency_key, fingerprint)
            accepted_response(request, accepted)
        screen_record(request, outcome)
        return outcome
    except KeyError:
        raise HTTPException(404, "Generation not found") from None
    except (ValueError, sqlite3.Error):
        raise HTTPException(409, "Workflow renewal disposition unavailable or conflicting") from None
