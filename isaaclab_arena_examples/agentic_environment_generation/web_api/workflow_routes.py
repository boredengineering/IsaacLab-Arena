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

from .security import require_mutation, require_session

router = APIRouter(prefix="/api/editor/generations")


class Reauthorize(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    credential_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


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
            return replay
        state.model_settings.protect_public(body.model_dump())
        screened = True
        attempt = state.journal.renewable_attempt(job_id)
        metadata = state.workflow_authorization.capture_renewal(session, job, credential_ref=body.credential_ref)
        record = {
            "schema_version": 1,
            "workflow_authorization": metadata,
            "approval": "single_operator_workspace",
            "blocked_attempt": attempt,
        }
        state.model_settings.protect_public(record)
        accepted, fresh = state.journal.renew_authorization(
            job_id,
            body.idempotency_key,
            fingerprint,
            attempt,
            record,
            max_pending=state.max_pending,
        )
        state.supervisor.wake.set()
        return accepted
    except KeyError:
        raise HTTPException(404, "Generation not found") from None
    except ValueError:
        # Never seal raw request bytes after any early failure.
        if not screened:
            state.model_settings.protect_public(body.model_dump())
        try:
            outcome = state.journal.seal_authorization_rejection(job_id, body.idempotency_key, fingerprint)
        except (ValueError, sqlite3.Error):
            raise HTTPException(409, "Workflow renewal disposition unavailable or conflicting") from None
        if outcome.get("code") == "renewal_rejected":
            raise HTTPException(409, outcome) from None
        return outcome
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
    request.app.state.model_settings.protect_public({
        "idempotency_key": idempotency_key,
        "fingerprint": fingerprint,
    })
    try:
        if request.app.state.journal.get_job(job_id)["workspace_id"] != "default":
            raise KeyError(job_id)
        return request.app.state.journal.authorization_disposition(job_id, idempotency_key, fingerprint)
    except KeyError:
        raise HTTPException(404, "Generation not found") from None
    except (ValueError, sqlite3.Error):
        raise HTTPException(409, "Workflow renewal disposition unavailable or conflicting") from None
