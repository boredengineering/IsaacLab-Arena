# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Authenticated prompt and YAML editor routes."""

import asyncio
import json
import re
import yaml

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from isaaclab_arena.agentic_environment_generation.workbench.document_yaml import parse_yaml

from . import generation
from .preview_options import RenderOptions, normalized_options
from .security import require_mutation, require_session

router = APIRouter(prefix="/api/editor")


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    yaml_text: str = Field(max_length=256 * 1024)
    document_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @field_validator("yaml_text")
    @classmethod
    def byte_limit(cls, value):
        if len(value.encode("utf-8")) > 256 * 1024:
            raise ValueError("YAML exceeds 256 KiB")
        return value


class SaveDraft(Draft):
    expected_source_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class SnapshotDraft(Draft):
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    options: RenderOptions = Field(default_factory=RenderOptions)


class GenerateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    credential_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    prompt: str = Field(min_length=1, max_length=16000)
    document_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    base_yaml: str | None = Field(default=None, max_length=256 * 1024)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")

    @field_validator("prompt")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Prompt must not be blank")
        return value


@router.get("")
async def index(request: Request, session=Depends(require_session)):
    documents = request.app.state.documents
    execution = request.app.state.editor_execution
    configured = request.app.state.model_settings.status(session, request.app.state.session_keys_allowed)["configured"]
    limitations = [
        "Schema validation is not a simulation or policy evaluation.",
        "Save creates an immutable revision; downloads are explicitly flattened YAML exports.",
    ]
    if not configured:
        limitations.append("Generation is not configured; set a supported API key in the server environment.")
    if execution.snapshot_error:
        limitations.append(execution.snapshot_error)
    return {
        "default_document_id": documents.default_document_id,
        "documents": documents.index(),
        "capabilities": {
            "generation": configured,
            "snapshots": execution.snapshots is not None,
            "neo4j": getattr(request.app.state, "neo4j_available", False),
        },
        "limitations": limitations,
    }


@router.get("/documents/{document_id}", dependencies=[Depends(require_session)])
async def document(request: Request, document_id: str):
    try:
        result = request.app.state.documents.load(document_id)
    except KeyError:
        raise HTTPException(404, "Document not found") from None
    except (ValueError, OSError):
        raise HTTPException(422, "Document source is unavailable or outside allowed roots") from None
    protect_yaml(request, result["yaml_text"])
    request.app.state.model_settings.protect_public(result)
    return result


@router.post("/validate", dependencies=[Depends(require_mutation)])
async def validate(request: Request, body: Draft):
    return checked_validation(request, body.yaml_text, body.document_id)


@router.post("/save", dependencies=[Depends(require_mutation)])
async def save(request: Request, body: SaveDraft):
    request.app.state.model_settings.protect_public(body.model_dump())
    checked_validation(request, body.yaml_text, body.document_id)
    # Revisions retain the complete frozen source set, even if this draft drops its include.
    includes = request.app.state.documents.frozen.get(body.document_id, {})
    request.app.state.model_settings.protect_public(includes)
    for text in includes.values():
        protect_yaml(request, text)
    try:
        return request.app.state.documents.save(body.yaml_text, body.document_id, body.expected_source_hash)
    except KeyError:
        raise HTTPException(404, "Document not found") from None
    except ValueError as error:
        raise HTTPException(409 if "changed" in str(error) else 422, str(error)) from None


@router.get("/revisions/{revision_id}/download", dependencies=[Depends(require_session)])
async def download(request: Request, revision_id: str):
    try:
        text = request.app.state.documents.download(revision_id)
    except KeyError:
        raise HTTPException(404, "Revision not found") from None
    protect_yaml(request, text)
    return Response(
        text,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="arena-{revision_id}-flattened.yaml"'},
    )


def protect_yaml(request, text):
    """Guard raw YAML and escape spellings before errors can quote source excerpts."""
    request.app.state.model_settings.protect_public(text)

    def decode(match):
        value = int(match.group()[2:], 16)
        return chr(value) if value <= 0x10FFFF else match.group()

    # This is a conservative secret check, not a parser: malformed YAML must still
    # receive the normal validation diagnostics when it contains no credential.
    unfolded = re.sub(r"\\(?:\r\n|[\r\n])[ \t]*", "", text)
    decoded = re.sub(r"\\(?:x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})", decode, unfolded)
    request.app.state.model_settings.protect_public(decoded)
    try:
        parsed = parse_yaml(text)
    except (ValueError, yaml.YAMLError, TypeError):
        return  # Documents.validate owns invalid-YAML diagnostics.
    request.app.state.model_settings.protect_public(parsed)


def checked_validation(request, text, document_id):
    protect_yaml(request, text)
    validation = request.app.state.documents.validate(text, document_id)
    request.app.state.model_settings.protect_public(validation)
    return validation


def frozen_draft(request, text, document_id):
    validation = checked_validation(request, text, document_id)
    if not validation["valid"]:
        raise HTTPException(422, {"message": "Invalid Arena environment specification", "errors": validation["errors"]})
    return yaml.safe_dump(validation["spec"], sort_keys=False), validation


def submit_editor(request, session, kind, key, inputs):
    # Both fresh submissions and safe prior replays cross this durable/public boundary.
    request.app.state.model_settings.protect_public({"idempotency_key": key, "inputs": inputs})
    try:
        job = request.app.state.journal.submit(
            session["session_id"], "default", kind, key, inputs, max_pending=request.app.state.max_pending
        )
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    request.app.state.supervisor.wake.set()
    return job


@router.post("/generate", status_code=202)
async def generate(request: Request, body: GenerateDraft, session=Depends(require_mutation)):
    request.app.state.model_settings.protect_public(body.model_dump())
    base = body.base_yaml
    document_id = body.document_id
    if body.document_id:
        try:
            request.app.state.documents.path(body.document_id)
            if base is None:
                document = request.app.state.documents.load(body.document_id)
                base = document["yaml_text"]
                document_id = document["document_id"]
        except (KeyError, OSError, ValueError):
            raise HTTPException(404, "Document not found") from None
    validation = None
    request.app.state.model_settings.protect_public(base)
    if base is not None:
        base, validation = frozen_draft(request, base, document_id)
    inputs = {
        "prompt": body.prompt,
        "base_yaml": base,
        "document_id": document_id,
        "input_hash": validation["source_hash"] if validation else None,
    }
    existing = request.app.state.journal.get_submission("default", body.idempotency_key)
    if existing is not None:
        # Recovery is workspace-wide, not a fresh grant to consume a credential.
        # Only use the original frozen metadata; Journal.submit compares the full
        # fingerprint (including kind and exact ref) and never queues a replay.
        if body.credential_ref is not None:
            inputs["credential_ref"] = body.credential_ref
            inputs.update({key: existing["inputs"][key] for key in ("provider", "model") if key in existing["inputs"]})
        return submit_editor(request, session, "generate", body.idempotency_key, inputs)
    credential = {}
    if body.credential_ref is not None:
        try:
            config = request.app.state.model_settings.resolve(session["session_id"], body.credential_ref)
        except ValueError:
            raise HTTPException(409, "Temporary credential unavailable; save settings and submit again") from None
        credential = {"credential_ref": body.credential_ref, "provider": config["provider"], "model": config["model"]}
    elif generation.configuration() is None:
        raise HTTPException(503, "Generation is not configured; set a supported server-side model API key")
    return submit_editor(
        request,
        session,
        "generate",
        body.idempotency_key,
        {**inputs, **credential},
    )


@router.post("/snapshots", status_code=202)
async def snapshots(request: Request, body: SnapshotDraft, session=Depends(require_mutation)):
    text, validation = frozen_draft(request, body.yaml_text, body.document_id)
    try:
        options = normalized_options(body.options.model_dump(), validation["spec"])
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    if request.app.state.editor_execution.snapshots is None:
        raise HTTPException(503, "Snapshot adapter unavailable in this runtime")
    return submit_editor(
        request,
        session,
        "snapshots",
        body.idempotency_key,
        {
            "yaml_text": text,
            "document_id": body.document_id,
            "input_hash": validation["source_hash"],
            "canonical_hash": validation["canonical_hash"],
            "options": options,
        },
    )


@router.get("/artifacts/{artifact_id}", dependencies=[Depends(require_session)])
async def artifact(request: Request, artifact_id: str):
    service = request.app.state.editor_execution.snapshots
    if service is None:
        raise HTTPException(503, "Snapshot adapter unavailable in this runtime")
    try:
        path = service.artifact_path(artifact_id)
    except (KeyError, ValueError, OSError):
        raise HTTPException(404, "Artifact not found") from None
    return FileResponse(path, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})


@router.get("/previews/{canonical_hash}", dependencies=[Depends(require_session)])
async def preview(request: Request, canonical_hash: str):
    """Recover verified or explicitly historical pixels without submitting work."""
    import re

    if not re.fullmatch(r"[a-f0-9]{64}", canonical_hash):
        raise HTTPException(422, "Invalid canonical hash")
    query = request.query_params
    if set(query) - {"view", "resolution", "asset_views"} or any(len(query.getlist(key)) != 1 for key in query):
        raise HTTPException(422, "Invalid preview query fields")
    try:
        if query.get("resolution", "1024") not in {"512", "1024"}:
            raise ValueError("Invalid resolution")
        raw_views = query.get("asset_views", "{}")
        if len(raw_views) > 40000:
            raise ValueError("Too many camera overrides")

        def unique_pairs(pairs):
            if len(dict(pairs)) != len(pairs):
                raise ValueError("Duplicate camera override")
            return dict(pairs)

        asset_views = json.loads(raw_views, object_pairs_hook=unique_pairs)
        if not isinstance(asset_views, dict):
            raise ValueError("Camera overrides must be an object")
        options = normalized_options({
            "view": query.get("view", "isometric"),
            "resolution": int(query.get("resolution", "1024")),
            "asset_views": asset_views,
        })
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid preview options") from None
    service = request.app.state.editor_execution.snapshots
    try:
        receipt = (
            await asyncio.to_thread(service.lookup, canonical_hash, options, allow_historical=True)
            if service is not None
            else None
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    status = "miss"
    if receipt is not None:
        status = "historical" if receipt["freshness"] == "unverified_assets" else "hit"
    return {"status": status, "canonical_hash": canonical_hash, "receipt": receipt}
