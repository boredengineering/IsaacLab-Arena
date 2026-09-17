# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""SDK-free documented request policies, not live or complete scene readiness.

Documentation backs only these exact model/endpoint pairs. Unknown combinations
remain unverified; this catalogue does not migrate settings or probe providers.
``store=False`` controls completion storage, not all provider retention.
"""

import copy
import re

PROFILE_CATALOGUE_VERSION = "harness-model-profiles/v1"
FIXED_ENDPOINTS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
}


def checked_request_policy(value):
    """Validate the complete enumerated policy without coercion or defaulting."""
    choices = {
        "api": ("chat_completions",),
        "temperature_mode": ("configured", "omitted"),
        "token_limit_parameter": ("max_tokens", "max_completion_tokens"),
        "structured_output": ("json_schema", "json_object", "omitted"),
        "multimodal_output": ("json_object", "omitted"),
    }
    if type(value) is not dict or set(value) != set(choices) | {"store"}:
        raise ValueError("Invalid request policy")
    if any(type(value[k]) is not str or value[k] not in options for k, options in choices.items()):
        raise ValueError("Invalid request policy")
    if value["store"] is not None and value["store"] is not False:
        raise ValueError("Invalid request policy")
    return copy.deepcopy(value)


def frozen_builtin_profile(profile):
    """Expand legacy documented metadata into a complete frozen request policy."""
    result = copy.deepcopy(profile)
    result.update(origin="builtin", verification="not_checked")
    result["request_policy"]["multimodal_output"] = "json_object"
    return result


def checked_inference_profile(value, *, model=None, base_url=None):
    """Validate a detached explicit profile, including literal model/endpoint binding."""
    fields = {"id", "revision", "provider", "model", "endpoint", "origin", "support",
              "verification", "documentation_urls", "request_policy"}
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid inference profile")
    if type(value["id"]) is not str or value["id"] == "custom" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value["id"]):
        raise ValueError("Invalid inference profile")
    if (type(value["revision"]) is not int or value["revision"] != 1
            or type(value["model"]) is not str or not re.fullmatch(r"[!-~]{1,256}", value["model"])
            or type(value["provider"]) is not str or value["provider"] not in FIXED_ENDPOINTS
            or value["endpoint"] != FIXED_ENDPOINTS[value["provider"]]
            or value["verification"] != "not_checked"):
        raise ValueError("Invalid inference profile")
    checked_request_policy(value["request_policy"])
    builtins = {p["id"]: frozen_builtin_profile(p) for p in inference_profile_catalogue()}
    if value["id"] in builtins:
        if value != builtins[value["id"]]:
            raise ValueError("Invalid builtin inference profile")
    elif (value["origin"] != "user_defined" or value["support"] != "unverified"
          or value["documentation_urls"] != []):
        raise ValueError("Invalid inference profile")
    if model is not None and model != value["model"]:
        raise ValueError("Inference profile model mismatch")
    if base_url is not None and base_url not in (value["endpoint"], value["endpoint"].rstrip("/") + "/"):
        raise ValueError("Inference profile endpoint mismatch")
    return copy.deepcopy(value)


def resolve_inference_profile(model, base_url, *, actual_base_url=None):
    """Return a detached documented pair, or None without guessing compatibility.

    Args:
        model: Exact configured model literal; aliases are not inferred.
        base_url: Configured literal; only one optional trailing slash is accepted.
        actual_base_url: SDK endpoint; cannot upgrade an unverified configured literal.

    Returns:
        Public request-policy record, or None for an unverified pair.
    """
    if base_url not in ("https://api.openai.com/v1", "https://api.openai.com/v1/"):
        return None
    if actual_base_url is not None and actual_base_url not in (
        "https://api.openai.com/v1",
        "https://api.openai.com/v1/",
    ):
        return None
    return next((profile for profile in inference_profile_catalogue() if profile["model"] == model), None)


def inference_profile_catalogue():
    """Return detached public request-policy records for the documented pairs."""
    return [
        {
            "id": "openai-" + model,
            "revision": 1,
            "provider": "openai",
            "model": model,
            "endpoint": "https://api.openai.com/v1",
            "support": "documented",
            "documentation_urls": urls,
            "request_policy": {
                "api": "chat_completions",
                "structured_output": "json_schema",
                "temperature_mode": temperature,
                "token_limit_parameter": tokens,
                "store": store,
            },
        }
        for model, urls, temperature, tokens, store in [
            (
                "gpt-4.1",
                ["https://developers.openai.com/api/docs/models/gpt-4.1"],
                "configured",
                "max_tokens",
                None,
            ),
            (
                "gpt-6-astra",
                [
                    "https://developers.openai.com/api/docs/models/gpt-6-astra",
                    "https://developers.openai.com/api/docs/guides/latest-model",
                ],
                "omitted",
                "max_completion_tokens",
                False,
            ),
        ]
    ]
