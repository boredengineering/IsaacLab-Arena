# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Exact, detached request-policy classification; no SDK or provider execution."""

import pytest

from isaaclab_arena.agentic_environment_generation import inference_profiles


def test_catalogue_and_resolution_are_deeply_detached():
    import copy

    before = inference_profiles.inference_profile_catalogue()
    changed = inference_profiles.inference_profile_catalogue()
    record = inference_profiles.resolve_inference_profile("gpt-6-astra", "https://api.openai.com/v1")
    expected = copy.deepcopy(record)
    changed[1]["request_policy"]["store"] = True
    changed[1]["documentation_urls"].clear()
    record["documentation_urls"].append("changed")
    record["request_policy"]["temperature_mode"] = "changed"
    assert inference_profiles.inference_profile_catalogue() == before
    assert inference_profiles.resolve_inference_profile("gpt-6-astra", "https://api.openai.com/v1") == expected


def test_profile_import_and_resolution_are_sdk_free(monkeypatch):
    import builtins
    import importlib

    original = builtins.__import__

    def safe_import(name, *args, **kwargs):
        assert not name.startswith(("openai", "httpx", "requests", "dotenv"))
        assert "inference_backend" not in name
        return original(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", safe_import)
        importlib.reload(inference_profiles)
        assert len(inference_profiles.inference_profile_catalogue()) == 2
        assert inference_profiles.resolve_inference_profile("gpt-4.1", "https://api.openai.com/v1") is not None


@pytest.mark.parametrize("model", ["gpt-4.1", "gpt-6-astra"])
@pytest.mark.parametrize("endpoint", ["https://api.openai.com/v1", "https://api.openai.com/v1/"])
def test_exact_documented_pairs(model, endpoint):
    assert hasattr(inference_profiles, "resolve_inference_profile")
    record = inference_profiles.resolve_inference_profile(model, endpoint)
    assert record == next(p for p in inference_profiles.inference_profile_catalogue() if p["model"] == model)


@pytest.mark.parametrize(
    "model, endpoint",
    [
        (model, "https://api.openai.com/v1")
        for model in ("gpt-6-astra-latest", "gpt-4.1-2025-04-14", "openai/gpt-6-astra", "GPT-6-ASTRA", "unknown", None)
    ]
    + [
        ("gpt-6-astra", endpoint)
        for endpoint in (
            "https://api.openai.com/v1//",
            "https://api.openai.com/v1?x=1",
            "https://api.openai.com/v1#fragment",
            "https://api.openai.com/v1/chat/completions",
            "https://api.openai.com.evil.invalid/v1",
            "http://api.openai.com/v1",
            "https://api.openai.com:443/v1",
            "https://API.OPENAI.COM/v1",
            "https://user@api.openai.com/v1",
            "https://openrouter.ai/api/v1",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            "https://integrate.api.nvidia.com/v1",
            "",
            None,
        )
    ],
)
def test_unknown_pairs_are_not_inferred(model, endpoint):
    assert hasattr(inference_profiles, "resolve_inference_profile")
    assert inference_profiles.resolve_inference_profile(model, endpoint) is None
