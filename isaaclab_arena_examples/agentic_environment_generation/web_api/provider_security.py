# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Small secret-boundary helpers shared by the API and its private worker."""

import os
from contextlib import contextmanager
from urllib.parse import urlsplit

PROVIDERS = (
    {"id": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1"},
    {"id": "gemini", "label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"},
    {"id": "openrouter", "label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1"},
    {"id": "nvidia", "label": "NVIDIA", "base_url": "https://integrate.api.nvidia.com/v1"},
)
ENDPOINTS = {provider["id"]: provider["base_url"] for provider in PROVIDERS}


def checked_config(config, *, trusted_server=False):
    """Validate private configuration; only trusted server settings may override endpoints."""
    if not isinstance(config, dict):
        raise ValueError("Invalid provider configuration")
    key, model, endpoint = (config.get(name) for name in ("api_key", "model", "base_url"))
    if (
        not isinstance(key, str)
        or not (1 if trusted_server else 16) <= len(key) <= 4096
        or not isinstance(model, str)
        or not 1 <= len(model) <= 256
        or any(ord(c) < 33 or ord(c) > 126 for c in key + model)
        or not isinstance(endpoint, str)
        or (not trusted_server and endpoint not in ENDPOINTS.values())
    ):
        raise ValueError("Invalid provider configuration")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or any(ord(c) <= 32 for c in endpoint):
        raise ValueError("Invalid provider configuration")
    reject_secret(endpoint, key)
    reject_secret(model, key)
    reject_secret(PROVIDERS, key)
    reject_secret(
        (
            "providers",
            "configured",
            "source",
            "provider",
            "model",
            "expires_at",
            "credential_ref",
            "session_keys_allowed",
        ),
        key,
    )
    return {"api_key": key, "model": model, "base_url": endpoint}


@contextmanager
def bounded_client(config):
    """Install transport before the legacy agent's initialization ping, in its isolated worker only."""
    from openai import DefaultHttpxClient, OpenAI

    from isaaclab_arena.agentic_environment_generation import inference_backend

    # Use the SDK's client class: some runtimes vendor HTTPX under a different module name.
    with DefaultHttpxClient(follow_redirects=False, trust_env=False, timeout=45) as transport:
        with OpenAI(
            api_key=config["api_key"], base_url=config["base_url"], http_client=transport, timeout=45, max_retries=0
        ) as client:
            completion = client.chat.completions.create
            calls = 0

            def complete(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls > 8:
                    raise ValueError("Generation call budget exhausted")
                kwargs["model"] = config["model"]
                return completion(*args, **kwargs)

            client.chat.completions.create = complete
            original = inference_backend.OpenAI
            inference_backend.OpenAI = lambda **kwargs: client
            try:
                yield client
            finally:
                inference_backend.OpenAI = original


def reject_secret(value, api_key):
    """Reject exact secret material recursively, including dictionary keys."""
    if not api_key:
        return
    if isinstance(value, str):
        if api_key in value:
            raise ValueError("Protected credential material in generation data")
    elif isinstance(value, dict):
        for key, item in value.items():
            reject_secret(key, api_key)
            reject_secret(item, api_key)
    elif isinstance(value, (list, tuple)):
        for item in value:
            reject_secret(item, api_key)


def worker_environment(api_key):
    """Pass runtime search paths, not inherited credentials or provider overrides."""
    allowed = {"PATH", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}
    return {key: value for key, value in os.environ.items() if key in allowed and (not api_key or api_key not in value)}
