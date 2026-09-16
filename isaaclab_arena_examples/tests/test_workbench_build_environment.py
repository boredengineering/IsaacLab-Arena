# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Build subprocess environment projection; no simulator or external calls."""

import pytest

from isaaclab_arena_examples.agentic_environment_generation.web_api import build_execution


@pytest.mark.parametrize("visibility", ["", "0", "2,4", "GPU-unit-fixture"])
def test_build_preserves_runtime_experience_and_gpu_restrictions(monkeypatch, visibility):
    monkeypatch.setenv("EXP_PATH", "/synthetic/isaac/apps")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", visibility)
    monkeypatch.setenv("NVIDIA_VISIBLE_DEVICES", "none")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-provider-marker")
    monkeypatch.setenv("NEO4J_PASSWORD", "synthetic-graph-marker")
    monkeypatch.setenv("LIVESTREAM", "2")
    monkeypatch.setenv("OMNICLIENT_HUB_MODE", "enabled")
    assert hasattr(build_execution, "build_environment"), "Build needs its simulator-specific environment projection"
    environment = build_execution.build_environment()
    assert environment["EXP_PATH"] == "/synthetic/isaac/apps"
    assert environment["CUDA_VISIBLE_DEVICES"] == visibility
    assert environment["NVIDIA_VISIBLE_DEVICES"] == "none"
    assert environment["OMNICLIENT_HUB_MODE"] == "disabled"
    assert not {"OPENAI_API_KEY", "NEO4J_PASSWORD", "LIVESTREAM"} & environment.keys()


def test_build_does_not_invent_runtime_paths_or_device_selection(monkeypatch):
    for name in ("EXP_PATH", "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES"):
        monkeypatch.delenv(name, raising=False)
    assert hasattr(build_execution, "build_environment"), "Build needs its simulator-specific environment projection"
    environment = build_execution.build_environment()
    assert not {"EXP_PATH", "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES"} & environment.keys()


def test_process_launch_uses_the_build_environment_projection(monkeypatch, tmp_path):
    import asyncio
    import os
    from types import SimpleNamespace

    expected = {"EXP_PATH": "/synthetic/isaac/apps", "CUDA_VISIBLE_DEVICES": ""}
    monkeypatch.setattr(build_execution, "build_environment", lambda: expected, raising=False)
    captured = []

    async def no_process(*args, **kwargs):
        captured.append(kwargs["env"])
        raise RuntimeError("simulated spawn stop")

    monkeypatch.setattr(build_execution.asyncio, "create_subprocess_exec", no_process)
    execution = SimpleNamespace(state_dir=tmp_path, build_lease_fd=123, build_owner_fd=None)
    supervisor = SimpleNamespace(stopping=False, journal=SimpleNamespace(get_job=lambda _id: {"status": "running"}))
    try:
        with pytest.raises(RuntimeError, match="simulated spawn stop"):
            asyncio.run(build_execution.run_worker(execution, supervisor, {"id": "build-unit", "inputs": {}}))
        assert captured == [expected]
    finally:
        if execution.build_owner_fd is not None:
            os.close(execution.build_owner_fd)
