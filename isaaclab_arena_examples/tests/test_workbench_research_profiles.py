# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Operator store-profile parsing never creates or normalizes research locations."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from isaaclab_arena_examples.agentic_environment_generation.web_api.research_profiles import parse_research_roots


def test_explicit_profile_paths_are_not_created(tmp_path):
    root = tmp_path / "managed"
    assert parse_research_roots([f"primary={root}"]) == {"primary": root}
    assert not root.exists()
    assert parse_research_roots([]) == {}


@pytest.mark.parametrize(
    "entries",
    [
        ["bad"],
        ["../store=/tmp/managed"],
        ["store=relative"],
        ["store=/tmp/../managed"],
        ["store=/tmp/generated_envs/managed"],
        ["store=/tmp/one", "store=/tmp/two"],
    ],
)
def test_invalid_or_ambiguous_profile_is_rejected(entries):
    with pytest.raises(ValueError):
        parse_research_roots(entries)


def test_application_rejects_invalid_profiles_before_starting(tmp_path):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import create_app

    with pytest.raises(ValueError):
        create_app(tmp_path / "state", research_roots={"../bad": tmp_path / "root"})
    assert not (tmp_path / "state").exists()


def test_launcher_passes_only_explicit_profiles_without_initializing_them(tmp_path, monkeypatch):
    import sys

    from isaaclab_arena_examples.agentic_environment_generation.web_api import __main__ as launcher

    captured = {}
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "workbench",
            "--state-dir",
            str(tmp_path / "state"),
            "--socket",
            str(tmp_path / "api.sock"),
            "--research-store",
            f"primary={tmp_path / 'managed'}",
        ],
    )
    monkeypatch.setattr(launcher, "validate_layout", lambda *args: None)
    monkeypatch.setattr(launcher, "StateLease", lambda *args: nullcontext(object()))
    monkeypatch.setattr(launcher, "UnixListener", lambda *args: nullcontext(object()))
    monkeypatch.setattr(launcher, "create_app", lambda *args, **kwargs: captured.update(kwargs))
    monkeypatch.setattr(launcher.uvicorn, "Config", lambda *args, **kwargs: None)
    monkeypatch.setattr(launcher, "OwnedServer", lambda *args: SimpleNamespace(started=True, run=lambda **kwargs: None))
    launcher.main()
    assert captured["research_roots"] == {"primary": tmp_path / "managed"}
    assert not (tmp_path / "managed").exists()
