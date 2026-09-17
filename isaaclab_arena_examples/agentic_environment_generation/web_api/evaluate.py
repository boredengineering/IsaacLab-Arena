# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Authenticated fixed-profile evaluation admission and local evidence downloads."""

import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import field_validator

from .editor import BuildDraft, frozen_draft, protect_editor_job, submit_editor
from .evaluation_profiles import FIXED, POLICY_CONTRACTS, compatible_spec, configured_profiles
from .security import require_mutation, require_session

router = APIRouter(prefix="/api/editor")


class EvaluateDraft(BuildDraft):
    profile: Literal["gr00t-droid", "openpi-droid"]
    language_instruction: str | None = None

    @field_validator("language_instruction")
    @classmethod
    def instruction_limit(cls, value):
        if value is not None and (not value.strip() or len(value.encode("utf-8")) > 4000):
            raise ValueError("Instruction must be nonblank and at most 4000 UTF-8 bytes")
        return value


@router.get("/evaluation-profiles", dependencies=[Depends(require_session)])
async def profiles():
    return {
        "profiles": configured_profiles(),
        **FIXED,
        "publication": "not_requested",
        "policy_contracts": POLICY_CONTRACTS,
    }


@router.post("/evaluate", status_code=202)
async def evaluate(request: Request, body: EvaluateDraft, session=Depends(require_mutation)):
    protect_editor_job(request, body.model_dump())
    request_hash = hashlib.sha256(
        json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prior = request.app.state.journal.get_submission("default", body.idempotency_key)
    if prior is not None:
        if prior["kind"] != "evaluate" or prior["inputs"].get("request_sha256") != request_hash:
            raise HTTPException(409, "Idempotency key already bound to different inputs")
        return submit_editor(request, session, "evaluate", body.idempotency_key, prior["inputs"])
    if not request.app.state.editor_execution.evaluation_available:
        raise HTTPException(503, "Evaluation adapter unavailable in this runtime")
    text, validation = frozen_draft(request, body.yaml_text, body.document_id)
    try:
        compatible_spec(validation["spec"])
    except ValueError:
        raise HTTPException(
            422,
            "Evaluation requires droid_abs_joint_pos with DROID cameras and separate observations",
        ) from None
    from .policy_endpoint import configured_gr00t_port

    policy_inputs = {"remote_host": "127.0.0.1", "remote_port": 8000}
    if body.profile == "gr00t-droid":
        from .policy_readiness import expected_hashes
        from .readiness import checked_worker

        try:
            policy_inputs["remote_port"] = configured_gr00t_port()
        except ValueError:
            raise HTTPException(503, "configuration_changed") from None
        try:
            expectations = expected_hashes()
        except ValueError:
            raise HTTPException(503, "policy_expectation_missing") from None
        try:
            receipt = await checked_worker({
                "workflow": "a2_gr00t",
                "prompt": "evaluation admission",
                "graph_config": None,
                "expectations": expectations,
                "gr00t_port": policy_inputs["remote_port"],
            })
            if receipt["runtime"] != "runtime_available" or receipt["policy"] is None:
                raise HTTPException(503, "runtime_unavailable")
            proof = receipt["policy"]
            for key in ("policy_protocol", "policy_model", "policy_transport"):
                if proof[key]["status"] != "passed":
                    from .readiness import READINESS_CODES

                    code = proof[key]["code"]
                    raise HTTPException(
                        503,
                        (code if code in READINESS_CODES else "policy_metadata_unavailable"),
                    )
            from isaaclab_arena.agentic_environment_generation.policy_contract import validate_server_info

            info = validate_server_info(proof["server_info"], **expectations)
            try:
                current_port = configured_gr00t_port()
            except ValueError:
                raise HTTPException(503, "configuration_changed") from None
            if expectations != expected_hashes() or policy_inputs["remote_port"] != current_port:
                raise HTTPException(503, "configuration_changed")
            policy_inputs["expected_server_info"] = info
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "policy_metadata_unavailable") from None
        # Dependency reads confer no stale-session submission authority.
        session = require_mutation(request, require_session(request))
    return submit_editor(
        request,
        session,
        "evaluate",
        body.idempotency_key,
        {
            "yaml_text": text,
            "document_id": body.document_id,
            "input_hash": validation["source_hash"],
            "canonical_hash": validation["canonical_hash"],
            "request_sha256": request_hash,
            "profile": body.profile,
            "language_instruction": body.language_instruction,
            **policy_inputs,
            **FIXED,
        },
    )


@router.get("/evaluations/{job_id}/artifacts/{name}", dependencies=[Depends(require_session)])
async def artifact(request: Request, job_id: str, name: str):
    """Serve checked bytes as a sandboxed attachment, never active API-origin HTML."""
    from fastapi.responses import Response

    from .evaluation_artifacts import ARTIFACT_NAMES, job_root, verify_result

    if name not in ARTIFACT_NAMES or request.query_params:
        raise HTTPException(404, "Evaluation artifact not found")
    try:
        root = job_root(request.app.state.editor_execution.state_dir, job_id)
        job = request.app.state.journal.get_job(job_id)
        if job["kind"] != "evaluate" or job["status"] != "succeeded" or job["result"] is None:
            raise ValueError("Evaluation has no accepted evidence")
        protect_editor_job(request, job)
        files = verify_result(
            root,
            job["inputs"],
            job["result"],
            request.app.state.model_settings.protect_public,
        )
        data = files[name]
    except (KeyError, ValueError, OSError, TypeError):
        raise HTTPException(404, "Evaluation artifact not found") from None
    return Response(
        data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Content-Security-Policy": "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
