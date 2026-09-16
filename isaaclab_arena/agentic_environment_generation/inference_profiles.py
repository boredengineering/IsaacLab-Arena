# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""SDK-free documented request policies, not live or complete scene readiness.

Documentation backs only these exact model/endpoint pairs. Unknown combinations
remain unverified; this catalogue does not migrate settings or probe providers.
``store=False`` controls completion storage, not all provider retention.
"""

PROFILE_CATALOGUE_VERSION = "harness-model-profiles/v1"


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
