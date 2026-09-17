# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Opted-in provider metadata reads; never construct an agent or request inference."""

import json
import time

from isaaclab_arena.agentic_environment_generation.inference_profiles import resolve_inference_profile

from . import generation
from .provider_security import checked_config

PROVIDER_CODES = (
    "generation_model_readable",
    "generation_provider_unsupported",
    "generation_provider_unavailable",
    "generation_authentication_failed",
    "generation_permission_denied",
    "generation_model_missing",
    "generation_rate_limited",
    "generation_redirect_refused",
    "generation_model_mismatch",
    "generation_metadata_invalid",
    "generation_check_timeout",
)
MAX_METADATA_BYTES = 8192


def capture_provider(state, session):
    """Resolve the same exact ModelSettings/server boundary as workflow capture, without issuing grants."""
    settings = state.model_settings
    metadata = settings.status(session, state.session_keys_allowed)
    reference = metadata["credential_ref"]
    if reference is not None:
        if not state.session_keys_allowed:
            return None
        config = settings.resolve(session["session_id"], reference)
    else:
        config = generation.configuration()
    if config is None:
        return None
    # Retain the original private configuration and generation, not just the model
    # label; same-key replacement in ModelSettings changes credential_ref.
    return {"source": metadata["source"], "credential_ref": reference, "config": dict(config)}


def probe_provider(config):
    """GET documented official model metadata with bounded raw bytes, no proxies or redirects."""
    if config is None:
        return "generation_not_configured"
    try:
        safe = checked_config(config, trusted_server=True)
        if (
            config.get("provider", "openai") != "openai"
            or safe.get("inference_profile", {}).get("origin") == "user_defined"
            or resolve_inference_profile(safe["model"], safe["base_url"]) is None
        ):
            return "generation_provider_unsupported"
    except Exception:
        return "generation_provider_unsupported"
    try:
        import httpx
    except ImportError:
        return "generation_provider_unavailable"
    try:
        deadline = time.monotonic() + 4
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=2) as client:
            with client.stream(
                "GET",
                "https://api.openai.com/v1/models/" + safe["model"],
                headers={"Authorization": "Bearer " + safe["api_key"], "Accept-Encoding": "identity"},
            ) as response:
                status = response.status_code
                if 300 <= status < 400:
                    return "generation_redirect_refused"
                if status != 200:
                    return {
                        401: "generation_authentication_failed",
                        403: "generation_permission_denied",
                        404: "generation_model_missing",
                        429: "generation_rate_limited",
                    }.get(status, "generation_provider_unavailable")
                if response.headers.get("content-encoding", "identity") != "identity":
                    return "generation_metadata_invalid"
                data = bytearray()
                for chunk in response.iter_raw():
                    if time.monotonic() >= deadline:
                        return "generation_check_timeout"
                    if len(data) + len(chunk) > MAX_METADATA_BYTES:
                        return "generation_metadata_invalid"
                    data.extend(chunk)
                if time.monotonic() >= deadline:
                    return "generation_check_timeout"

                def unique_pairs(items):
                    result = {}
                    for key, item in items:
                        if key in result:
                            raise ValueError("Duplicate model metadata")
                        result[key] = item
                    return result

                try:
                    value = json.loads(data, object_pairs_hook=unique_pairs)
                except (ValueError, UnicodeError, RecursionError):
                    return "generation_metadata_invalid"
                if type(value) is not dict or value.get("object") != "model":
                    return "generation_metadata_invalid"
                if value.get("id") != safe["model"]:
                    return "generation_model_mismatch"
                return "generation_model_readable"
    except (TimeoutError, httpx.TimeoutException):
        return "generation_check_timeout"
    except Exception:
        return "generation_provider_unavailable"
