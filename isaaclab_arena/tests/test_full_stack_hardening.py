# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Full-stack hardening acceptance and regression test suite (HR-14 through HR-16)."""

from __future__ import annotations

import argparse
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
    FIXTURE_SECTOR_BOUNDS,
    FIXTURE_STRUCTURAL_EXCLUSIONS,
    project_coordinate_to_support_hull,
    validate_spatial_geometry,
    validate_support_containment,
)
from isaaclab_arena.agentic_environment_generation.visual_critic import (
    VisualCriticResult,
    VisualSceneCritic,
)
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environment_spec.arena_env_graph_types import (
    AssetSpec,
    ReifiedRelationSpec,
    TaskSpec,
)
from isaaclab_arena.orchestration.infra_manager import InfraManager
from isaaclab_arena_examples.agentic_environment_generation.environment_generation_runner import (
    check_preflight_service_triad,
)


def _make_packing_table_spec(banana_xyz: list[float], bowl_xyz: list[float]) -> ArenaEnvGraphSpec:
    """Helper to synthesize a test spec on packing_table."""
    spec = ArenaEnvGraphSpec.from_yaml("generated_envs/droid_banana_to_red_bowl/v5-1/droid_banana_to_red_bowl.yaml")
    for obj in spec.objects:
        if obj.id == "yellow_banana":
            if not obj.params:
                obj.params = {}
            if "initial_pose" not in obj.params:
                obj.params["initial_pose"] = {}
            obj.params["initial_pose"]["position_xyz"] = list(banana_xyz)
        elif obj.id == "red_bowl":
            if not obj.params:
                obj.params = {}
            if "initial_pose" not in obj.params:
                obj.params["initial_pose"] = {}
            obj.params["initial_pose"]["position_xyz"] = list(bowl_xyz)
    return spec


def test_preflight_triad_strict_mode():
    """In strict mode, unreachable services fail immediately with exit code 2."""
    args = argparse.Namespace(
        strict_critics=True,
        base_url="http://127.0.0.1:9999/v1",
        model=None,
    )
    with patch(
        "isaaclab_arena_examples.agentic_environment_generation.environment_generation_runner.verify_neo4j_endpoint",
        return_value=(False, "Connection refused"),
    ):
        with pytest.raises(SystemExit) as excinfo:
            check_preflight_service_triad(args)
        assert excinfo.value.code == 2


def test_preflight_triad_permissive_mode(capsys):
    """In permissive mode (strict_critics=False), failing services log warnings without aborting."""
    args = argparse.Namespace(
        strict_critics=False,
        base_url="http://127.0.0.1:9999/v1",
        model=None,
    )
    with patch(
        "isaaclab_arena_examples.agentic_environment_generation.environment_generation_runner.verify_neo4j_endpoint",
        return_value=(False, "Connection refused"),
    ), patch(
        "isaaclab_arena_examples.agentic_environment_generation.environment_generation_runner.verify_service_endpoint",
        return_value=(False, "Connection refused"),
    ):
        # Should not raise SystemExit
        check_preflight_service_triad(args)
        captured = capsys.readouterr()
        assert "[WARNING]" in captured.out or "[WARNING]" in captured.err


def test_visual_critic_vlm_code_fence_stripping():
    """Visual critic strips markdown code fences from LLM responses."""
    raw_fenced = "```json\n{\n  \"conforms\": true,\n  \"visibility_score\": 9.5,\n  \"occluded_objects\": [],\n  \"floating_objects\": [],\n  \"anomalies\": [],\n  \"actionable_feedback\": \"\"\n}\n```"
    mock_backend = MagicMock()
    mock_backend.multimodal_chat.return_value = raw_fenced

    spec = _make_packing_table_spec([-0.10, 0.0, 0.75], [0.10, 0.0, 0.75])
    critic = VisualSceneCritic(backend=mock_backend)
    res = critic._call_cloud_vlm_critic(spec, {"cam1": b"dummy"})

    assert isinstance(res, VisualCriticResult)
    assert res.conforms is True
    assert res.visibility_score == 9.5


def test_grey_bin_fixture_exclusion_definition():
    """Verify grey bin exclusion geometry is configured for packing_table."""
    assert "packing_table" in FIXTURE_STRUCTURAL_EXCLUSIONS
    exclusions = FIXTURE_STRUCTURAL_EXCLUSIONS["packing_table"]
    label, x_min, x_max, y_min, y_max = exclusions[0]
    assert label == "grey_bin_fixture"
    assert x_min == 0.15 and x_max == 0.45
    assert y_min == -0.35 and y_max == -0.10

    # Sector bounds for packing_table carve out the bin
    pt_sectors = FIXTURE_SECTOR_BOUNDS["packing_table"]
    assert pt_sectors["rear_right"][1] <= 0.15 or pt_sectors["rear_right"][3] <= -0.10
    assert "rear_bin_fixture" in pt_sectors


def test_grey_bin_collision_detection():
    """validate_support_containment flags objects placed inside the grey bin fixture."""
    # Place yellow_banana right inside the grey bin: x=0.25, y=-0.20, z=0.75
    colliding_spec = _make_packing_table_spec([0.25, -0.20, 0.75], [-0.10, 0.05, 0.75])
    errors = validate_support_containment(colliding_spec)
    assert any("collides with permanent workstation fixture 'grey_bin_fixture'" in e for e in errors)

    # Place yellow_banana on clear deck: x=-0.10, y=-0.05, z=0.75
    clear_spec = _make_packing_table_spec([-0.10, -0.05, 0.75], [0.05, 0.10, 0.75])
    clear_errors = validate_support_containment(clear_spec)
    assert not any("collides with permanent workstation fixture" in e for e in clear_errors)


def test_project_coordinate_avoids_grey_bin():
    """project_coordinate_to_support_hull shifts coordinates away from the grey bin."""
    spec = _make_packing_table_spec([0.25, -0.20, 0.75], [-0.10, 0.05, 0.75])
    safe_coord, _ = project_coordinate_to_support_hull(
        spec,
        object_id="yellow_banana",
    )
    # Must not be inside [0.15, 0.45] x [-0.35, -0.10]
    in_bin = (0.15 <= safe_coord[0] <= 0.45) and (-0.35 <= safe_coord[1] <= -0.10)
    assert not in_bin, f"Projected coordinate {safe_coord} still inside grey bin fixture!"


def test_infra_manager_probing():
    """InfraManager correctly probes endpoints."""
    mgr = InfraManager()
    with patch.object(mgr, "probe_http_endpoint", return_value=(True, "Qwen2.5-Coder", 0.05)), patch.object(
        mgr, "probe_neo4j", return_value=(True, "connected", 0.02)
    ):
        results = mgr.probe_all_endpoints(timeout=1.0)
        assert results["llm"]["ok"] is True
        assert results["vlm"]["ok"] is True
        assert results["neo4j"]["ok"] is True
