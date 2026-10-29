# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Renderer leases must reside on shared storage, not private container /tmp."""

from pathlib import Path

import pytest


def test_default_snapshot_lease_uses_the_shared_eval_mount(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.snapshot_process import gpu_lease_path

    monkeypatch.delenv("ARENA_WORKBENCH_GPU_LEASE", raising=False)
    assert gpu_lease_path() == Path("/eval/.arena-workbench-gpu.lock")
    monkeypatch.setenv("ARENA_WORKBENCH_GPU_LEASE", "/shared/renderer/gpu.lock")
    assert gpu_lease_path() == Path("/shared/renderer/gpu.lock")
    monkeypatch.setenv("ARENA_WORKBENCH_GPU_LEASE", "relative.lock")
    with pytest.raises(ValueError, match="absolute"):
        gpu_lease_path()
