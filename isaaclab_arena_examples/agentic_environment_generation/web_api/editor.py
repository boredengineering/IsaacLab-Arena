# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Authenticated prompt and YAML editor routes."""

import yaml

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import generation
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


class GenerateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
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


@router.get("", dependencies=[Depends(require_session)])
async def index(request: Request):
    documents = request.app.state.documents
    execution = request.app.state.editor_execution
    configured = generation.configuration() is not None
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
        return request.app.state.documents.load(document_id)
    except KeyError:
        raise HTTPException(404, "Document not found") from None
    except (ValueError, OSError):
        raise HTTPException(422, "Document source is unavailable or outside allowed roots") from None


@router.post("/validate", dependencies=[Depends(require_mutation)])
async def validate(request: Request, body: Draft):
    return request.app.state.documents.validate(body.yaml_text, body.document_id)


@router.post("/save", dependencies=[Depends(require_mutation)])
async def save(request: Request, body: SaveDraft):
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
    return Response(
        text,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="arena-{revision_id}-flattened.yaml"'},
    )


def frozen_draft(request, text, document_id):
    validation = request.app.state.documents.validate(text, document_id)
    if not validation["valid"]:
        raise HTTPException(422, {"message": "Invalid Arena environment specification", "errors": validation["errors"]})
    return yaml.safe_dump(validation["spec"], sort_keys=False), validation


def submit_editor(request, session, kind, key, inputs):
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
    if base is not None:
        base, validation = frozen_draft(request, base, document_id)
    if generation.configuration() is None:
        raise HTTPException(503, "Generation is not configured; set a supported server-side model API key")
    return submit_editor(
        request,
        session,
        "generate",
        body.idempotency_key,
        {
            "prompt": body.prompt,
            "base_yaml": base,
            "document_id": document_id,
            "input_hash": validation["source_hash"] if validation else None,
        },
    )


@router.post("/snapshots", status_code=202)
async def snapshots(request: Request, body: SnapshotDraft, session=Depends(require_mutation)):
    text, validation = frozen_draft(request, body.yaml_text, body.document_id)
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
