# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Memory-only provider credentials; public metadata never includes key material."""

import asyncio
import json
from copy import deepcopy
import re
import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from isaaclab_arena.agentic_environment_generation.inference_profiles import (
    inference_profile_catalogue,
    resolve_inference_profile,
    frozen_builtin_profile,
    checked_inference_profile,
)

from . import generation, graph_access
from .provider_security import ENDPOINTS, PROVIDERS, checked_config, reject_secret
from .public_records import screen_public_record
from .security import require_mutation, require_session
from isaaclab_arena.agentic_environment_generation.workbench.model_profile_store import ModelProfileStore, ModelProfileConflict

MAX_CREDENTIALS = 128
router = APIRouter(prefix="/api/model-settings")


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    provider: Literal["openai", "gemini", "openrouter", "nvidia"]
    model: str = Field(min_length=1, max_length=256)
    api_key: str = Field(min_length=16, max_length=4096, repr=False)
    ttl_minutes: int | None = Field(default=30, strict=True)
    profile_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def safe_metadata(self):
        if self.ttl_minutes not in (None, 15, 30, 60, 120):
            raise ValueError("Unsupported key expiration")
        checked_config({"api_key": self.api_key, "model": self.model, "base_url": ENDPOINTS[self.provider]})
        return self


class RequestPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    api: Literal["chat_completions"]
    temperature_mode: Literal["configured", "omitted"]
    token_limit_parameter: Literal["max_tokens", "max_completion_tokens"]
    structured_output: Literal["json_schema", "json_object", "omitted"]
    multimodal_output: Literal["json_object", "omitted"]
    store: bool | None

    @model_validator(mode="after")
    def no_storage_opt_in(self):
        if self.store is not None and self.store is not False:
            raise ValueError("Invalid request policy")
        return self


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    provider: Literal["openai", "gemini", "openrouter", "nvidia"]
    model: str = Field(min_length=1, max_length=256, pattern=r"^[!-~]+$")
    request_policy: RequestPolicyInput


class ModelSettings:
    """Keep one temporary credential per session, never serialize the private records."""

    def __init__(self, *, clock=time.time, journal=None):
        self.clock = clock
        self.profiles = ModelProfileStore(journal) if journal is not None else None
        self._records = {}
        self.on_invalidate = lambda owner: None
        self.protect_grants = lambda value: None
        self.purge_grants = lambda: None

    def forget(self, session_id):
        self._records.pop(session_id, None)
        self.on_invalidate(session_id)

    def purge(self):
        self.purge_grants()
        for session_id, record in tuple(self._records.items()):
            if self.clock() >= record["expires_at"]:
                self.forget(session_id)

    async def maintain(self):
        while True:
            self.purge()
            await asyncio.sleep(30)

    def clear(self):
        self._records.clear()

    def session_activity(self, session):
        """Follow explicit session activity only for credentials without a key timer."""
        self.purge()
        record = self._records.get(session["session_id"])
        if record is not None and record["key_timer_disabled"]:
            record["expires_at"] = session["expires_at"]

    def save(self, session, body):
        self.purge()

        # The candidate key is not active yet. Screen only its public projection
        # against both policies before replacement can invalidate existing grants.
        def protect_candidate(value):
            self.protect_public(value)
            try:
                reject_secret(value, body.api_key)
            except ValueError:
                raise HTTPException(422, "Invalid request input") from None

        selected = None
        if body.profile_id is not None:
            catalogue = inference_profile_catalogue() + (self.profiles.catalogue() if self.profiles else [])
            selected = next((p for p in catalogue if p["id"] == body.profile_id), None)
            if selected is None:
                raise HTTPException(422, "Unknown model profile")
            if "origin" not in selected:
                selected = frozen_builtin_profile(selected)
            try:
                selected = checked_inference_profile(selected, model=body.model, base_url=ENDPOINTS[body.provider])
                if selected["provider"] != body.provider:
                    raise ValueError("Profile provider mismatch")
            except ValueError:
                raise HTTPException(422, "Model profile does not match selection") from None
        else:
            builtin = resolve_inference_profile(body.model, ENDPOINTS[body.provider])
            selected = frozen_builtin_profile(builtin) if builtin else None
        candidate = {
            "api_key": body.api_key,
            "inference_profile": selected,
            "provider": body.provider,
            "model": body.model,
            "credential_ref": secrets.token_hex(32),
            "expires_at": (
                session["expires_at"]
                if body.ttl_minutes is None
                else min(self.clock() + body.ttl_minutes * 60, session["expires_at"])
            ),
            "key_timer_disabled": body.ttl_minutes is None,
        }
        screen_public_record(self._public_metadata(candidate, None, True), protect_candidate)
        if session["session_id"] not in self._records and len(self._records) >= MAX_CREDENTIALS:
            raise HTTPException(409, "Temporary credential capacity reached; try again after expiry")
        self.forget(session["session_id"])
        self._records[session["session_id"]] = candidate

    def protect_public(self, value):
        """Reject active credential material before public validation or durable submission."""
        try:
            self.protect_grants(value)
            reject_secret(value, (graph_access.configuration() or {}).get("password"))
            for record in self._records.values():
                reject_secret(value, record["api_key"])
            reject_secret(value, (generation.configuration() or {}).get("api_key"))
        except ValueError:
            raise HTTPException(422, "Invalid request input") from None

    def status(self, session, allowed):
        self.purge()
        record = self._records.get(session["session_id"])
        server = generation.configuration() if record is None else None
        # Unsafe legacy/operator metadata is withheld, not rewritten. Expiry and
        # Forget still remove authority normally; no historical key denylist.
        return screen_public_record(self._public_metadata(record, server, allowed), self.protect_public)

    def _public_metadata(self, record, server, allowed):
        """Build detached metadata without mutating credentials or exposing endpoints."""
        config = record if record is not None else server
        profile = resolve_inference_profile(
            (config or {}).get("model"),
            ENDPOINTS.get(record["provider"]) if record is not None else (server or {}).get("base_url"),
        )
        profile = (record or {}).get("inference_profile") or profile
        public = {
            "profile_catalogue_version": "harness-model-profiles/v2",
            "profiles": [frozen_builtin_profile(p) for p in inference_profile_catalogue()] + (self.profiles.catalogue() if self.profiles else []),
            "profile_creation": "create-only/v1" if self.profiles else None,
            "effective_profile": (
                {
                    "id": profile["id"] if profile else None,
                    "support": profile["support"] if profile else "unverified",
                    "verification": "not_checked",
                }
                if config is not None
                else None
            ),
            "providers": [dict(provider) for provider in PROVIDERS],
            "configured": record is not None or server is not None,
            "source": "session" if record else "server" if server else "none",
            "provider": record["provider"] if record else (server or {}).get("provider"),
            "model": record["model"] if record else (server or {}).get("model"),
            "expires_at": record["expires_at"] if record else None,
            "key_timer_disabled": record["key_timer_disabled"] if record else False,
            "credential_ref": record["credential_ref"] if record else None,
            "session_keys_allowed": allowed,
        }
        return public

    def credential_expiry(self, session_id, credential_ref):
        """Return the exact original reference deadline, never replacement metadata."""
        self.resolve(session_id, credential_ref)
        return self._records[session_id]["expires_at"]

    def resolve(self, session_id, credential_ref):
        """Resolve exactly this session's live reference, never a fallback or replacement."""
        self.purge()
        record = self._records.get(session_id)
        if record is None or not secrets.compare_digest(record["credential_ref"], credential_ref):
            raise ValueError("Temporary credential unavailable")
        return {key: record[key] for key in ("api_key", "provider", "model")} | {
            "base_url": ENDPOINTS[record["provider"]]
        } | ({"inference_profile": deepcopy(record["inference_profile"])} if record["inference_profile"] else {})


@router.get("")
async def status(request: Request, session=Depends(require_session)):
    return request.app.state.model_settings.status(session, request.app.state.session_keys_allowed)


@router.put("")
async def save(request: Request, body: SettingsInput, session=Depends(require_mutation)):
    if not request.app.state.session_keys_allowed:
        raise HTTPException(403, "Temporary credentials require HTTPS or loopback HTTP")
    request.app.state.model_settings.save(session, body)
    return await status(request, session)


@router.put("/profiles/{profile_id}")
async def create_profile(request: Request, profile_id: str, body: ProfileInput, session=Depends(require_mutation)):
    settings = request.app.state.model_settings
    def unique(pairs):
        value = {}
        for key, child in pairs:
            if key in value:
                raise ValueError("Duplicate profile field")
            value[key] = child
        return value
    try:
        json.loads(await request.body(), object_pairs_hook=unique)
    except (ValueError, RecursionError):
        raise HTTPException(422, "Invalid model profile JSON") from None
    if settings.profiles is None:
        raise HTTPException(503, "Model profile creation unavailable")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", profile_id)
            or profile_id == "custom" or profile_id in {p["id"] for p in inference_profile_catalogue()}):
        raise HTTPException(422, "Invalid model profile identity")
    profile = dict(body.model_dump(), id=profile_id, revision=1, origin="user_defined", support="unverified",
                   verification="not_checked", endpoint=ENDPOINTS[body.provider], documentation_urls=[])
    def protect(value):
        screen_public_record(value, settings.protect_public)
    try:
        return settings.profiles.create(profile, protect)
    except ModelProfileConflict:
        raise HTTPException(409, "Model profile conflict or capacity reached") from None


@router.delete("")
async def forget(request: Request, session=Depends(require_mutation)):
    request.app.state.model_settings.forget(session["session_id"])
    return await status(request, session)
