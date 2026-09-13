# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Memory-only provider credentials; public metadata never includes key material."""

import asyncio
import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import generation
from .provider_security import ENDPOINTS, PROVIDERS, checked_config, reject_secret
from .security import require_mutation, require_session

MAX_CREDENTIALS = 128
router = APIRouter(prefix="/api/model-settings")


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    provider: Literal["openai", "gemini", "openrouter", "nvidia"]
    model: str = Field(min_length=1, max_length=256)
    api_key: str = Field(min_length=16, max_length=4096, repr=False)
    ttl_minutes: int = Field(default=30, strict=True)

    @model_validator(mode="after")
    def safe_metadata(self):
        if self.ttl_minutes not in (15, 30, 60, 120):
            raise ValueError("Unsupported key expiration")
        checked_config({"api_key": self.api_key, "model": self.model, "base_url": ENDPOINTS[self.provider]})
        return self


class ModelSettings:
    """Keep one temporary credential per session, never serialize the private records."""

    def __init__(self, *, clock=time.time):
        self.clock = clock
        self._records = {}

    def forget(self, session_id):
        self._records.pop(session_id, None)

    def purge(self):
        for session_id, record in tuple(self._records.items()):
            if self.clock() >= record["expires_at"]:
                self.forget(session_id)

    async def maintain(self):
        while True:
            self.purge()
            await asyncio.sleep(30)

    def clear(self):
        self._records.clear()

    def save(self, session, body):
        self.purge()
        self.protect_public({"model": body.model, "provider": body.provider})
        if session["session_id"] not in self._records and len(self._records) >= MAX_CREDENTIALS:
            raise HTTPException(409, "Temporary credential capacity reached; try again after expiry")
        self._records[session["session_id"]] = {
            "api_key": body.api_key,
            "provider": body.provider,
            "model": body.model,
            "credential_ref": secrets.token_hex(32),
            "expires_at": min(self.clock() + body.ttl_minutes * 60, session["expires_at"]),
        }

    def protect_public(self, value):
        """Reject active credential material before public validation or durable submission."""
        try:
            for record in self._records.values():
                reject_secret(value, record["api_key"])
            reject_secret(value, (generation.configuration() or {}).get("api_key"))
        except ValueError:
            raise HTTPException(422, "Invalid request input") from None

    def status(self, session, allowed):
        self.purge()
        record = self._records.get(session["session_id"])
        server = generation.configuration() if record is None else None
        return {
            "providers": list(PROVIDERS),
            "configured": record is not None or server is not None,
            "source": "session" if record else "server" if server else "none",
            "provider": record["provider"] if record else (server or {}).get("provider"),
            "model": record["model"] if record else (server or {}).get("model"),
            "expires_at": record["expires_at"] if record else None,
            "credential_ref": record["credential_ref"] if record else None,
            "session_keys_allowed": allowed,
        }

    def resolve(self, session_id, credential_ref):
        """Resolve exactly this session's live reference, never a fallback or replacement."""
        self.purge()
        record = self._records.get(session_id)
        if record is None or not secrets.compare_digest(record["credential_ref"], credential_ref):
            raise ValueError("Temporary credential unavailable")
        return {key: record[key] for key in ("api_key", "provider", "model")} | {
            "base_url": ENDPOINTS[record["provider"]]
        }


@router.get("")
async def status(request: Request, session=Depends(require_session)):
    return request.app.state.model_settings.status(session, request.app.state.session_keys_allowed)


@router.put("")
async def save(request: Request, body: SettingsInput, session=Depends(require_mutation)):
    if not request.app.state.session_keys_allowed:
        raise HTTPException(403, "Temporary credentials require HTTPS or loopback HTTP")
    request.app.state.model_settings.save(session, body)
    return await status(request, session)


@router.delete("")
async def forget(request: Request, session=Depends(require_mutation)):
    request.app.state.model_settings.forget(session["session_id"])
    return await status(request, session)
