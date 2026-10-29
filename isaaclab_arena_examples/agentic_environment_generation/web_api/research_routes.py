# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Authenticated adapters for explicitly configured managed research stores."""

import json
from contextlib import suppress
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from isaaclab_arena.agentic_environment_generation.workbench.editor_revision_storage import RevisionBusy, RevisionUncertain
from isaaclab_arena.agentic_environment_generation.workbench.research_registry import canonical_json, digest
from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore, SafeBusy

from .security import require_mutation, require_session

router = APIRouter(prefix="/api/research")


def protect_public(request, value):
    """Screen without changing canonical metadata or identity/digest inputs.

    The reject-only guard may purge/revoke expired authority as security maintenance;
    it must not issue/renew grants, dispatch workers, probe graphs or write schemas.
    Preserve secret-rejection HTTP errors; callback mutation is a static conflict.
    """
    try:
        before = canonical_json(value)
        request.app.state.model_settings.protect_public(value)
        if canonical_json(value) == before:
            return
    except (TypeError, ValueError, RecursionError):
        pass
    raise HTTPException(409, "Research public metadata changed")


@router.get("/publication-profiles")
async def publication_profiles(request: Request, session=Depends(require_session)):
    """List target metadata plus available=True; POST targets omit the availability field."""
    profiles = request.app.state.publication_profiles
    if type(profiles) is not dict or len(profiles) > 16:
        raise HTTPException(409, "Publication profiles unavailable")
    result = []
    for profile_id in sorted(profiles):
        with suppress(ValueError):
            metadata = request.app.state.publication_authorization.profile_metadata(profile_id)
            result.append({**metadata, "available": True})
    response = {"profiles": result}
    protect_public(request, response)
    return response


@router.get("/stores")
async def stores(request: Request, session=Depends(require_session)):
    """List configured research stores without creating or migrating a registry."""
    result = []
    for store_id, root in request.app.state.research_roots.items():
        available = False
        message = "Managed store unavailable"
        try:
            with suppress(ValueError, OSError):
                with ResearchStore.open(
                    request.app.state.journal,
                    root,
                    store_id,
                    protect_public=request.app.state.model_settings.protect_public,
                ):
                    available = True
                    message = "Managed store ready"
        except SafeBusy:
            message = "Managed store busy; retry later"

        result.append({
            "store_id": store_id,
            "available": available,
            "message": message,
        })
    response = {"stores": result}
    protect_public(request, response)
    return response


class PublicationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    profile_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    scope_ownership: Literal["cooperative_immutable"]


class PersistCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    family: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    source_job_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    source_attempt_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    source_generation: int = Field(ge=1)
    parent_revision_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    publication_target: PublicationTarget | None = None


class AcceptedCandidateSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["accepted_candidate"]
    job_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    attempt_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    generation: int = Field(ge=1)


class PersistTaggedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    family: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    source: AcceptedCandidateSource
    parent_revision_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    publication_target: PublicationTarget | None = None

    def legacy(self):
        return PersistCandidate(idempotency_key=self.idempotency_key, family=self.family,
            source_job_id=self.source.job_id, source_attempt_id=self.source.attempt_id,
            source_generation=self.source.generation, parent_revision_id=self.parent_revision_id,
            publication_target=self.publication_target)


class EditorRevisionSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["editor_revision"]
    editor_revision_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    canonical_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class PersistEditorRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    family: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    source: EditorRevisionSource
    parent_revision_id: str | None = Field(pattern=r"^[a-f0-9]{32}$")
    publication_target: PublicationTarget | None = None


def persist_manual(request, store, body):
    from isaaclab_arena.agentic_environment_generation.workbench.research_source import editor_revision_source
    from .editor import protect_revision_bundle

    approval = {"scope": "persist_editor_revision", "principal": "single_operator_workspace"}
    selected = body.source.model_dump()
    previous = store.registry.get_reservation_for_workflow(store.store_id, body.idempotency_key)
    loader = lambda revision_id: request.app.state.documents.load_revision_bundle(
        revision_id, protect_snapshot=lambda bundle: protect_revision_bundle(request, bundle))
    if previous is not None and store.registry.get_commit(previous["reservation_id"]) is not None:
        source = previous["source"]
        loader = None
    else:
        source = editor_revision_source(loader(body.source.editor_revision_id))
    if any(source.get(key) != value for key, value in selected.items()):
        raise ValueError("Research source conflict")
    return store.persist_editor_revision(
        body.family, body.idempotency_key, source=source, bundle_loader=loader,
        approval=approval, parent_revision_id=body.parent_revision_id)


def protected_version_source(request, store, reservation_id):
    """Verify copied source bytes and screen all retained content under current policy."""
    from isaaclab_arena.agentic_environment_generation.workbench.research_source import verify_source_artifacts, source_kind
    from .editor import protect_revision_bundle, protect_yaml

    reservation = store.get_reservation(reservation_id)
    files = store.read_version(reservation_id)
    source = verify_source_artifacts(reservation["source"], files,
        protect_snapshot=lambda bundle: protect_revision_bundle(request, bundle))
    if source_kind(reservation["source"]) == "accepted_candidate":
        protect_public(request, source)
        protect_yaml(request, source["yaml_text"])
    return source, files


def research_open_source(store_id, commit):
    return {"kind": "research_version", "id": "research-version:" + store_id + ":" +
            commit["reservation"]["reservation_id"] + ":" + commit["manifest"]["digest"]}


def open_research_version(request, descriptor):
    import re
    from isaaclab_arena.agentic_environment_generation.workbench.research_registry import checked_identifier
    from .editor import protect_revision_bundle

    parts = descriptor.split(":")
    if len(parts) != 4 or parts[0] != "research-version" or not re.fullmatch(r"[a-f0-9]{64}", parts[3]):
        raise HTTPException(422, "Invalid research version descriptor")
    _, store_id, reservation_id, manifest_digest = parts
    try:
        checked_identifier(store_id)
        checked_identifier(reservation_id)
    except ValueError:
        raise HTTPException(422, "Invalid research version descriptor") from None
    try:
        with selected_store(request, store_id) as store:
            reservation = store.get_reservation(reservation_id)
            commit = store.registry.get_commit(reservation_id)
            if commit is None:
                raise HTTPException(404, "Research version is not committed")
            if commit["manifest"]["digest"] != manifest_digest:
                raise ValueError("Research manifest conflict")
            bundle, _ = protected_version_source(request, store, reservation_id)
            identity = {key: reservation[key] for key in ("store_id", "reservation_id", "revision_id", "family", "version", "source")}
            identity["manifest_digest"] = manifest_digest
            protect_public(request, identity)
            return request.app.state.documents.issue_research_view(
                bundle, research_open_source(store_id, commit), identity,
                protect_snapshot=lambda bundle: protect_revision_bundle(request, bundle))
    except (KeyError, ValueError, OSError):
        raise HTTPException(409, "Research version unavailable") from None


def selected_store(request, store_id):
    root = request.app.state.research_roots.get(store_id)
    if root is None:
        raise HTTPException(404, "Research store not configured")
    return ResearchStore.open(
        request.app.state.journal,
        root,
        store_id,
        protect_public=request.app.state.model_settings.protect_public,
    )


@router.post("/stores/{store_id}/versions", status_code=201)
async def persist(
    request: Request,
    response: Response,
    store_id: str,
    body: PersistCandidate | PersistTaggedCandidate | PersistEditorRevision,
    session=Depends(require_mutation),
):
    """Persist an exact source; this does not authorize graph publication."""
    protect_public(request, body.model_dump())
    if isinstance(body, PersistTaggedCandidate):
        body = body.legacy()
    if isinstance(body, PersistEditorRevision) and body.publication_target is not None:
        raise HTTPException(422, "Editor revision publication is unsupported")
    try:
        with selected_store(request, store_id) as store:
            if isinstance(body, PersistEditorRevision):
                result = persist_manual(request, store, body)
                protect_public(request, result)
                return result
            publication_request = None
            if body.publication_target is not None:
                target = body.publication_target.model_dump()
                previous = store.registry.get_reservation_for_workflow(store.store_id, body.idempotency_key)
                if previous is None:
                    if target != request.app.state.publication_authorization.profile_metadata(target["profile_id"]):
                        raise ValueError("Publication target changed")
                identity = {
                    "registry_id": store.registry.registry_id,
                    "store_id": store.store_id,
                    "workflow_id": body.idempotency_key,
                    "purpose": "save_publication_intent",
                }
                protect_public(request, identity)
                publication_request = {
                    "effect_id": digest(identity),
                    "target_profile": target,
                }
            result = store.persist_candidate(
                body.family,
                body.idempotency_key,
                body.source_job_id,
                body.source_attempt_id,
                body.source_generation,
                # Sessions authenticate this declared single-operator scope, not separate users.
                {
                    "scope": "persist_candidate",
                    "principal": "single_operator_workspace",
                },
                parent_revision_id=body.parent_revision_id,
                publication_request=publication_request,
            )
        protect_public(request, result)
        if result["publication_intent_id"] is not None:
            response.headers["X-Publication-Preparation"] = "prepared-not-published"
        return result
    except RevisionBusy:
        raise HTTPException(503, "Revision storage is busy; retry the exact request", headers={"Retry-After": "1"}) from None
    except RevisionUncertain:
        raise HTTPException(503, "Revision data unavailable; retain the exact request") from None
    except (KeyError, ValueError, OSError):
        raise HTTPException(
            409,
            "Research persistence unavailable or conflicting; retain the request for recovery",
        ) from None


@router.get("/stores/{store_id}/versions")
async def versions(
    request: Request,
    store_id: str,
    family: str = Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"),
    after_version: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=50),
    session=Depends(require_session),
):
    """Read bounded metadata pages; only committed revisions contribute to latest."""
    try:
        with selected_store(request, store_id) as store:
            rows = store.list_versions(family, limit=limit + 1, after_version=after_version)
            page = rows[:limit]
            summaries = []
            for row in page:
                reservation, commit = row["reservation"], row["commit"]
                if commit is not None:
                    protected_version_source(request, store, reservation["reservation_id"])
                summaries.append({
                    **{
                        key: reservation[key]
                        for key in (
                            "reservation_id",
                            "revision_id",
                            "version",
                            "parent_revision_id",
                        )
                    },
                    "state": row["state"],
                    "source": reservation["source"],
                    **({"source_job_id": reservation["source"]["job_id"]} if "job_id" in reservation["source"] else {}),
                    "open_source": research_open_source(store_id, commit) if commit else None,
                    "manifest_digest": commit["manifest"]["digest"] if commit else None,
                    "publication_intent_id": commit["publication_intent_id"] if commit else None,
                })
            result = {
                "versions": summaries,
                "latest_version": store.latest_version(family),
                "next_after_version": page[-1]["reservation"]["version"] if len(rows) > limit else None,
            }
        protect_public(request, result)
        return result
    except (KeyError, ValueError, OSError):
        raise HTTPException(409, "Research metadata unavailable") from None


@router.get("/stores/{store_id}/versions/{reservation_id}")
async def version(
    request: Request,
    store_id: str,
    reservation_id: str,
    session=Depends(require_session),
):
    """Read a commit only after verifying its actual artifact bytes."""
    try:
        with selected_store(request, store_id) as store:
            store.get_reservation(reservation_id)
            commit = store.registry.get_commit(reservation_id)
            if commit is None:
                raise HTTPException(404, "Research version is not committed")
            protected_version_source(request, store, reservation_id)
        protect_public(request, commit)
        return commit
    except (KeyError, ValueError, OSError):
        raise HTTPException(409, "Research version unavailable") from None


@router.get("/stores/{store_id}/versions/{reservation_id}/publication-binding")
async def publication_binding(request: Request, store_id: str, reservation_id: str, session=Depends(require_session)):
    """Read verified frozen props, not publication status or execution authority."""
    from isaaclab_arena.agentic_environment_generation.workbench.research_registry import checked_identifier

    from .publication_payload import checked_frozen_config, prepare_publication

    try:
        checked_identifier(store_id)
        checked_identifier(reservation_id)
        with selected_store(request, store_id) as store:
            reservation = store.get_reservation(reservation_id)
            commit = store.registry.get_commit(reservation_id)
            if commit is None or commit["publication_intent_id"] is None:
                raise HTTPException(404, "Research publication binding is not prepared")
            intent, _, projection = prepare_publication(
                store, request.app.state.publication_authorization, commit["publication_intent_id"]
            )
            if intent["reservation_id"] != reservation_id or commit["reservation"] != reservation:
                raise ValueError("Publication reservation conflict")
            target = intent["target_profile"]
            config = checked_frozen_config(
                request.app.state.publication_profiles[target["profile_id"]]["connection"], target
            )
            result = {
                "storeId": store.store_id,
                "effectId": intent["effect_id"],
                "registryId": store.registry.registry_id,
                "target": target,
                "versionRef": {
                    "reservation_id": reservation_id,
                    "revision_id": reservation["revision_id"],
                    "version": reservation["version"],
                    "payload_sha256": intent["payload_sha256"],
                    "projection_digest": projection["digest"],
                    "scope_id": projection["scope_id"],
                    "database": config["database"],
                    "canonical_identity": projection["canonical_identity"],
                },
            }
        protect_public(request, result)
        return result
    except (KeyError, ValueError, TypeError, OSError):
        raise HTTPException(409, "Research publication binding unavailable") from None


@router.get("/stores/{store_id}/versions/{reservation_id}/artifacts/{name}")
async def artifact(
    request: Request,
    store_id: str,
    reservation_id: str,
    name: str,
    session=Depends(require_session),
):
    """Download verified YAML/JSON as an attachment, never same-origin executable content."""
    try:
        with selected_store(request, store_id) as store:
            _, files = protected_version_source(request, store, reservation_id)
        if name not in files:
            raise HTTPException(404, "Research artifact not found")
        text = files[name].decode("utf-8")
        protect_public(request, text)
        if name.endswith(".json"):
            protect_public(request, json.loads(text))
        else:
            protect_public(request, request.app.state.documents.validate(text))
        return Response(
            files[name],
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    except (KeyError, ValueError, OSError):
        raise HTTPException(409, "Research artifact unavailable") from None


@router.get("/stores/{store_id}/candidates/{job_id}")
async def candidate(request: Request, store_id: str, job_id: str, session=Depends(require_session)):
    """Read exact receipt/attempt identity rather than guessing from a job result."""
    try:
        with selected_store(request, store_id) as store:
            result = store.candidate_reference(job_id)
        protect_public(request, result)
        return result
    except (KeyError, ValueError, OSError):
        raise HTTPException(409, "Managed candidate unavailable") from None
