# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Authenticated prompt and YAML editor routes."""

import asyncio
import hashlib
import json
import re
import yaml
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from isaaclab_arena.agentic_environment_generation.workbench.editor_revision_storage import RevisionBusy, RevisionError, RevisionUncertain

from . import catalogues, generation
from .preview_options import RenderOptions, normalized_options
from .public_records import protect_public_record as protect_editor_job, protect_yaml
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
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class SnapshotDraft(Draft):
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    options: RenderOptions = Field(default_factory=RenderOptions)


class BuildDraft(Draft):
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")


class GenerateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["new", "refine"] | None = None
    retrieval_policy: Literal["allow_fallback", "require_service"] = "allow_fallback"
    credential_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    prompt: str = Field(min_length=1, max_length=16000)
    document_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    base_yaml: str | None = Field(default=None, max_length=256 * 1024)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")

    @model_validator(mode="after")
    def explicit_operation(self):
        """Keep new generation distinct from frozen-base refinement and legacy requests."""
        if self.operation == "new" and self.model_fields_set & {"base_yaml", "document_id"}:
            raise ValueError("New generation cannot include a base document")
        if self.operation == "refine" and not self.base_yaml:
            raise ValueError("Refinement requires explicit base YAML")
        if self.operation != "new" and self.retrieval_policy == "require_service":
            raise ValueError("Required retrieval is only supported for new generation")
        if self.base_yaml is not None and len(self.base_yaml.encode("utf-8")) > 256 * 1024:
            raise ValueError("YAML exceeds 256 KiB")
        return self

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
    try:
        rows = documents.index(protect_snapshot=lambda bundle: protect_revision_bundle(request, bundle))
    except RevisionError:
        raise HTTPException(422, "Invalid editor revision bundle") from None
    except RevisionBusy:
        raise HTTPException(503, "Revision storage is busy; retry the exact request", headers={"Retry-After": "1"}) from None
    except (RevisionUncertain, OSError):
        raise HTTPException(503, "Revision data unavailable; retain the exact request") from None
    return {
        "default_document_id": documents.default_document_id,
        "documents": rows,
        "capabilities": {
            "generation": configured,
            "generation_modes": True,
            "durable_editor_save": True,
            "research_versions": bool(request.app.state.research_roots),
            "manual_research_save": bool(request.app.state.research_roots),
            "research_version_open": bool(request.app.state.research_roots),
            "publication_execution": getattr(request.app.state, "publication_admitting", False) is True,
            "snapshots": execution.snapshots is not None,
            "build": execution.build_available,
            "policy_evaluation": execution.evaluation_available,
            "neo4j": getattr(request.app.state, "neo4j_available", False),
        },
        "limitations": limitations,
    }


@router.get("/documents/{document_id}", dependencies=[Depends(require_session)])
async def document(request: Request, document_id: str):
    try:
        if document_id.startswith("research-version:"):
            from .research_routes import open_research_version
            result = open_research_version(request, document_id)
        else:
            result = request.app.state.documents.load(document_id, protect_snapshot=lambda bundle: protect_revision_bundle(request, bundle))
    except RevisionError:
        raise HTTPException(422, "Invalid editor revision bundle") from None
    except RevisionBusy:
        raise HTTPException(503, "Revision storage is busy; retry the exact request", headers={"Retry-After": "1"}) from None
    except RevisionUncertain:
        raise HTTPException(503, "Revision data unavailable; retain the exact request") from None
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
    if body.idempotency_key is not None:
        protect_yaml(request, body.yaml_text)
        try:
            # Exact committed replay must precede resolution of an expired view.
            return request.app.state.documents.save(
                body.yaml_text, body.document_id, body.expected_source_hash,
                idempotency_key=body.idempotency_key,
                protect_snapshot=lambda bundle: protect_revision_bundle(request, bundle),
            )
        except RevisionBusy:
            raise HTTPException(503, "Revision storage is busy; retry the exact request", headers={"Retry-After": "1"}) from None
        except KeyError:
            raise HTTPException(404, "Document not found") from None
        except RevisionError as error:
            if str(error) == "Invalid environment specification":
                raise HTTPException(422, "Invalid environment specification") from None
            raise HTTPException(409, "Revision request conflicts with stored data or source") from None
        except (RevisionUncertain, OSError):
            raise HTTPException(503, "Revision save outcome is uncertain; check the exact saved request before retrying") from None
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


@router.get("/save-requests/{idempotency_key}", dependencies=[Depends(require_session)])
async def save_request(request: Request, idempotency_key: str):
    """Read a workspace-global save disposition without resolving its former source view."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", idempotency_key) or request.query_params:
        raise HTTPException(422, "Invalid save request lookup")
    try:
        return request.app.state.documents.save_request(
            idempotency_key, protect_snapshot=lambda bundle: protect_revision_bundle(request, bundle)
        )
    except RevisionBusy:
        raise HTTPException(503, "Revision storage is busy; retry the exact request", headers={"Retry-After": "1"}) from None
    except KeyError:
        raise HTTPException(404, "Save request not found") from None
    except RevisionError:
        raise HTTPException(409, "Revision request conflicts with stored data or source") from None
    except (RevisionUncertain, OSError):
        raise HTTPException(503, "Revision disposition unavailable; retain the exact request") from None


@router.get("/revisions/{revision_id}/download", dependencies=[Depends(require_session)])
async def download(request: Request, revision_id: str):
    try:
        text = request.app.state.documents.download(revision_id, protect_snapshot=lambda bundle: protect_revision_bundle(request, bundle))
    except RevisionError:
        raise HTTPException(422, "Invalid editor revision bundle") from None
    except RevisionBusy:
        raise HTTPException(503, "Revision storage is busy; retry the exact request", headers={"Retry-After": "1"}) from None
    except (RevisionUncertain, OSError):
        raise HTTPException(503, "Revision data unavailable; retain the exact request") from None
    except KeyError:
        raise HTTPException(404, "Revision not found") from None
    protect_yaml(request, text)
    return Response(
        text,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="arena-{revision_id}-flattened.yaml"'},
    )


def protect_revision_bundle(request, bundle):
    """Apply current secret protection to the complete retained bundle, including unused includes."""
    request.app.state.model_settings.protect_public(bundle)
    snapshot = bundle["snapshot"]
    protect_yaml(request, snapshot["yaml_text"])
    for text in snapshot["includes"].values():
        protect_yaml(request, text)
    protect_yaml(request, bundle["export_yaml"])


def checked_validation(request, text, document_id):
    documents = request.app.state.documents
    if document_id in documents.views:
        try:
            documents.load(document_id, protect_snapshot=lambda bundle: protect_revision_bundle(request, bundle))
        except RevisionError:
            raise HTTPException(422, "Invalid editor revision bundle") from None
        except RevisionBusy:
            raise HTTPException(503, "Revision storage is busy; retry the exact request", headers={"Retry-After": "1"}) from None
        except (RevisionUncertain, OSError):
            raise HTTPException(503, "Revision data unavailable; retain the exact request") from None
        except KeyError:
            raise HTTPException(404, "Document not found") from None
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
    protect_editor_job(request, {"kind": kind, "idempotency_key": key, "inputs": inputs})
    prior = request.app.state.journal.get_submission("default", key)
    if prior is not None:
        if prior["kind"] != kind or json.dumps(prior["inputs"], sort_keys=True) != json.dumps(inputs, sort_keys=True):
            raise HTTPException(409, "Idempotency key already bound to different inputs")
        protect_editor_job(request, prior)
    try:
        job = request.app.state.journal.submit(
            session["session_id"], "default", kind, key, inputs, max_pending=request.app.state.max_pending
        )
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    protect_editor_job(request, job)
    if prior is None:
        request.app.state.supervisor.wake.set()
    return job


@router.get("/generate/operations/{idempotency_key}", dependencies=[Depends(require_session)])
async def generation_operation(request: Request, idempotency_key: str, request_sha256: str):
    """Read an exact accepted request without consulting configuration or issuing grants."""
    query = request.query_params
    if (
        not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", idempotency_key)
        or not re.fullmatch(r"[a-f0-9]{64}", request_sha256)
        or set(query) != {"request_sha256"}
        or len(query.getlist("request_sha256")) != 1
    ):
        raise HTTPException(422, "Invalid operation lookup")
    prior = request.app.state.journal.get_submission("default", idempotency_key)
    if prior is not None and (prior["kind"] != "generate" or prior["inputs"].get("request_sha256") != request_sha256):
        raise HTTPException(409, "Idempotency key already bound to different inputs")
    protect_editor_job(request, prior)
    return {"job": prior}


@router.post("/generate", status_code=202)
async def generate(request: Request, body: GenerateDraft, session=Depends(require_mutation)):
    request_hash = hashlib.sha256(
        json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prior = request.app.state.journal.get_submission("default", body.idempotency_key)
    if body.operation is not None and prior is not None and "request_sha256" in prior["inputs"]:
        if prior["kind"] != "generate" or prior["inputs"]["request_sha256"] != request_hash:
            raise HTTPException(409, "Idempotency key already bound to different inputs")
        # Accepted bytes still require current policy; recovery never resolves a view or grants new work.
        protect_editor_job(request, prior)
        return prior
    protect_editor_job(request, body.model_dump())
    base = body.base_yaml
    document_id = body.document_id
    if body.document_id:
        try:
            request.app.state.documents.resolve_view(body.document_id)
            if base is None:
                document = request.app.state.documents.load(body.document_id, protect_snapshot=lambda bundle: protect_revision_bundle(request, bundle))
                base = document["yaml_text"]
                document_id = document["document_id"]
        except RevisionError:
            raise HTTPException(422, "Invalid editor revision bundle") from None
        except RevisionBusy:
            raise HTTPException(503, "Revision storage is busy; retry the exact request", headers={"Retry-After": "1"}) from None
        except RevisionUncertain:
            raise HTTPException(503, "Revision data unavailable; retain the exact request") from None
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
    if body.operation is not None:
        inputs.update(operation=body.operation, retrieval_policy=body.retrieval_policy, request_sha256=request_hash)
        inputs["execution_catalogue_sha256"] = catalogues.execution_catalogue_sha256()
    existing = request.app.state.journal.get_submission("default", body.idempotency_key)
    if existing is not None:
        # Recovery is workspace-wide, not a fresh grant to consume a credential.
        # Only use the original frozen metadata; Journal.submit compares the full
        # fingerprint (including kind and exact ref) and never queues a replay.
        if body.credential_ref is not None:
            inputs["credential_ref"] = body.credential_ref
            inputs.update({key: existing["inputs"][key] for key in ("provider", "model") if key in existing["inputs"]})
        if body.operation is not None and "workflow_authorization" in existing["inputs"]:
            inputs["workflow_authorization"] = existing["inputs"]["workflow_authorization"]
        return submit_editor(request, session, "generate", body.idempotency_key, inputs)
    if body.operation is not None:
        if body.credential_ref is not None:
            inputs["credential_ref"] = body.credential_ref
        try:
            metadata = request.app.state.workflow_authorization.capture(
                session,
                request.app.state.journal.workflow_operation_id("default", body.idempotency_key, inputs),
                credential_ref=body.credential_ref,
                retrieval=body.operation == "new",
                require_service=body.retrieval_policy == "require_service",
                protect_public=lambda value: protect_editor_job(request, value),
            )
        except ValueError:
            raise HTTPException(503, "Workflow configuration unavailable") from None
        if body.credential_ref is not None:
            inputs["credential_ref"] = body.credential_ref
        try:
            return submit_editor(
                request, session, "generate", body.idempotency_key, {**inputs, "workflow_authorization": metadata}
            )
        except Exception:
            request.app.state.workflow_authorization.rollback(metadata)
            raise
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


@router.post("/build", status_code=202)
async def build(request: Request, body: BuildDraft, session=Depends(require_mutation)):
    """Freeze a validated draft for the fixed CLI build adapter, never runtime overrides."""
    protect_editor_job(request, body.model_dump())
    request_hash = hashlib.sha256(
        json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prior = request.app.state.journal.get_submission("default", body.idempotency_key)
    if prior is not None:
        if prior["kind"] != "build" or prior["inputs"].get("request_sha256") != request_hash:
            raise HTTPException(409, "Idempotency key already bound to different inputs")
        return submit_editor(request, session, "build", body.idempotency_key, prior["inputs"])
    if not request.app.state.editor_execution.build_available:
        raise HTTPException(503, "Build adapter unavailable in this runtime")
    text, validation = frozen_draft(request, body.yaml_text, body.document_id)
    return submit_editor(
        request,
        session,
        "build",
        body.idempotency_key,
        {
            "yaml_text": text,
            "document_id": body.document_id,
            "input_hash": validation["source_hash"],
            "canonical_hash": validation["canonical_hash"],
            "request_sha256": request_hash,
            "headless": True,
            "num_envs": 1,
            "num_steps": 20,
            "policy": "zero_action",
        },
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
