# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Milestone 1 hardening (HR-01, HR-02, HR-03, HR-04)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
    EnvironmentGenerationAgent,
    _compute_spec_hash,
    _ensure_reified_relations_and_grounding,
)
from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
    RelaxationResultList,
    get_fixture_sector_bounds,
    get_known_fixture_bounds,
    relax_spec_spatial_factor_graph,
    validate_spatial_geometry,
    validate_support_containment,
)
from isaaclab_arena.agentic_environment_generation.visual_critic import VisualCriticResult, VisualSceneCritic
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.tests.utils.agentic_environment_generation import (
    catalog,
    chat_response,
    minimal_spec_dict,
    relation_catalog,
)
from isaaclab_arena.tests.utils.agentic_environment_generation import task_catalog as make_task_catalog


@pytest.fixture
def agent(stub_openai):
    """Construct an EnvironmentGenerationAgent with a mocked OpenAI client."""
    _, client = stub_openai
    a = EnvironmentGenerationAgent(api_key="test-key")
    client.chat.completions.create.reset_mock()
    return a, client


class TestAgentValidationParityHR02:
    """Verify HR-02 pipeline parity between generate_spec and refine_spec."""

    def test_refine_spec_runs_all_four_critics_and_repairs_visual_violation(self, agent):
        """Ensure refine_spec runs VisualSceneCritic and PhysXPreflightCritic and triggers repair on violation."""
        agent_obj, client = agent
        base_spec = ArenaEnvGraphSpec.model_validate(minimal_spec_dict())

        first_refined = minimal_spec_dict()
        second_refined = minimal_spec_dict()
        second_refined["relations"] = [
            {"kind": "is_anchor", "subject": "maple_table_robolab", "params": {}},
            {
                "kind": "on",
                "subject": "rubiks_cube_hot3d_robolab",
                "reference": "maple_table_robolab",
                "params": {"surface_anchor": "table_top", "surface_sector": "front_right"},
            },
            {
                "kind": "on",
                "subject": "bowl_ycb_robolab",
                "reference": "maple_table_robolab",
                "params": {"surface_anchor": "table_top", "surface_sector": "front_left"},
            },
        ]

        client.chat.completions.create.side_effect = [
            chat_response(content=json.dumps(first_refined)),
            chat_response(content=json.dumps(second_refined)),
        ]

        failing_visual = VisualCriticResult(
            conforms=False,
            visibility_score=3.0,
            occluded_objects=["rubiks_cube_hot3d_robolab"],
            anomalies=["Cube occluded by bowl"],
            actionable_feedback="Move rubiks_cube_hot3d_robolab to front_right sector.",
        )
        passing_visual = VisualCriticResult(conforms=True, visibility_score=10.0)

        with patch.object(
            VisualSceneCritic,
            "evaluate_scene_spec",
            side_effect=[failing_visual, passing_visual],
        ) as mock_vis:
            spec, data = agent_obj.refine_spec(
                base_spec,
                "Adjust placement on table",
                asset_catalog=catalog("catalog"),
                relation_catalog=relation_catalog("RELATIONS"),
                task_catalog=make_task_catalog("TASKS"),
                publish_to_graph=False,
            )

        assert spec is not None
        assert data is None
        assert mock_vis.call_count == 2
        assert client.chat.completions.create.call_count == 2
        assert any("Visual Scene Occlusion on iteration 1" in t for t in agent_obj.traces)
        assert any(
            "Visual line-of-sight and dynamic physics validation passed on iteration 2." in t
            for t in agent_obj.traces
        )

    def test_compute_spec_hash_sensitive_to_pose_and_sector_changes(self):
        """Ensure _compute_spec_hash changes when position_xyz or surface_sector is updated."""
        d1 = minimal_spec_dict()
        d1["objects"][0]["params"] = {"initial_pose": {"position_xyz": [-0.09, -0.20, 0.75]}}
        d1["relations"][1]["params"] = {"surface_anchor": "table_top", "surface_sector": "right"}

        d2 = minimal_spec_dict()
        d2["objects"][0]["params"] = {"initial_pose": {"position_xyz": [-0.09, -0.14, 0.75]}}
        d2["relations"][1]["params"] = {"surface_anchor": "table_top", "surface_sector": "front_right"}

        spec1 = ArenaEnvGraphSpec.model_validate(d1)
        spec2 = ArenaEnvGraphSpec.model_validate(d2)
        assert _compute_spec_hash(spec1) != _compute_spec_hash(spec2)


class TestStrictCriticsAndFactorGraphHR01HR04:
    """Verify HR-01 strict critic probing and HR-04 fail-loud factor graph relaxation."""

    def test_visual_critic_strict_mode_raises_on_unreachable_local_vlm(self):
        """Ensure VisualSceneCritic(strict_mode=True) raises RuntimeError when local VLM fails."""
        spec = ArenaEnvGraphSpec.model_validate(minimal_spec_dict())
        critic = VisualSceneCritic(local_vlm_url="http://127.0.0.1:9999/v1", strict_mode=True)
        with pytest.raises(RuntimeError, match="Strict critics enabled: Tier 2 Local VLM"):
            critic.evaluate_scene_spec(spec, rendered_images={"front": b"fake_png"})

    def test_visual_critic_auto_discovers_vlm_model_id(self):
        """Ensure VisualSceneCritic queries GET /v1/models instead of hardcoding model='default'."""
        critic = VisualSceneCritic(local_vlm_url="http://127.0.0.1:8001/v1", strict_mode=True)
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value.read.return_value = json.dumps(
            {"data": [{"id": "Qwen/Qwen2.5-VL-7B-Instruct"}]}
        ).encode("utf-8")
        with patch("urllib.request.urlopen", return_value=mock_resp):
            model_id = critic._resolve_local_vlm_model()
        assert model_id == "Qwen/Qwen2.5-VL-7B-Instruct"

    def test_relaxation_result_list_backward_compatibility_and_metadata(self):
        """Ensure relax_spec_spatial_factor_graph returns a RelaxationResultList with metadata."""
        spec = ArenaEnvGraphSpec.model_validate(minimal_spec_dict())
        _, res = relax_spec_spatial_factor_graph(spec)
        assert isinstance(res, list)
        assert isinstance(res, RelaxationResultList)
        assert isinstance(res.converged, bool)
        assert isinstance(res.residual, float)
        assert res.iterations > 0
        assert res.get("converged") == res.converged
        assert "residual" in res.to_dict()

    def test_ensure_reified_relations_logs_traces_and_raises_in_strict_mode(self):
        """Ensure _ensure_reified_relations_and_grounding logs factor-graph metrics and raises on strict failure."""
        spec = ArenaEnvGraphSpec.model_validate(minimal_spec_dict())
        traces: list[str] = []
        _ensure_reified_relations_and_grounding(spec, strict_mode=False, traces_out=traces)
        assert any("[FactorGraph] Relaxation completed:" in t for t in traces)

        with patch(
            "isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle.relax_spec_spatial_factor_graph",
            side_effect=ValueError("singular factor matrix"),
        ):
            err_traces: list[str] = []
            with pytest.raises(RuntimeError, match="Spatial factor graph relaxation failed"):
                _ensure_reified_relations_and_grounding(spec, strict_mode=True, traces_out=err_traces)
            assert any("[ERROR][FactorGraph]" in t for t in err_traces)

    def test_runner_verify_service_endpoint_and_strict_exit_code_2(self):
        """Ensure runner verify_service_endpoint detects unreachable port and exits with code 2 under --strict-critics."""
        import argparse
        from isaaclab_arena_examples.agentic_environment_generation.environment_generation_runner import (
            resolve_env_spec,
            verify_service_endpoint,
        )

        ok, msg = verify_service_endpoint("http://127.0.0.1:9999/v1", timeout=0.5)
        assert not ok
        assert "127.0.0.1:9999" in msg

        args_strict = argparse.Namespace(
            spec_path=None,
            base_spec=None,
            prompt="A red bowl on a maple table",
            env_name="test_strict_fail_env",
            model="local-vllm",
            base_url="http://127.0.0.1:9999/v1",
            api_key=None,
            max_iterations=1,
            strict_critics=True,
            disable_graph_rag=True,
            neo4j_uri="bolt://localhost:7688",
            neo4j_user="neo4j",
            neo4j_password="password",
            feedback=None,
            version_tag=None,
        )
        with pytest.raises(SystemExit) as exc_info:
            resolve_env_spec(args_strict)
        assert exc_info.value.code == 2



class TestSpatialOracleRectificationHR03:
    """Verify HR-03 fixture substring specificity, oak table chamfer inset, and resting EE clearance."""

    def test_fixture_bounds_and_sector_substring_specificity(self):
        """Ensure table_oak_robolab and packing_table do not collide with generic 'table'."""
        oak_bounds = get_known_fixture_bounds("table_oak_robolab")
        assert oak_bounds == (-0.22, 0.22, -0.22, 0.22, 0.75)

        packing_bounds = get_known_fixture_bounds("packing_table")
        assert packing_bounds == (-0.50, 0.50, -0.35, 0.35, 0.75)

        oak_fr = get_fixture_sector_bounds("table_oak_robolab", "front_right")
        assert oak_fr[2] >= -0.22 and oak_fr[4] == 0.75

    def test_saved_v3_and_v3_1_fail_and_v5_1_passes(self):
        """Verify v3 fails containment, v3-1 fails resting EE clearance, and v5-1 passes."""
        spec_v3 = ArenaEnvGraphSpec.from_yaml(
            "isaaclab_arena/tests/fixtures/droid_banana_to_red_bowl/v3/droid_banana_to_red_bowl.yaml"
        )
        assert len(validate_support_containment(spec_v3)) > 0

        spec_v3_1 = ArenaEnvGraphSpec.from_yaml(
            "isaaclab_arena/tests/fixtures/droid_banana_to_red_bowl/v3-1/droid_banana_to_red_bowl.yaml"
        )
        ok_v3_1, errs_v3_1 = validate_spatial_geometry(spec_v3_1)
        assert not ok_v3_1
        assert any("resting end-effector exclusion zone" in e for e in errs_v3_1)

        spec_v5_1 = ArenaEnvGraphSpec.from_yaml(
            "isaaclab_arena/tests/fixtures/droid_banana_to_red_bowl/v5-1/droid_banana_to_red_bowl.yaml"
        )
        ok_v5_1, errs_v5_1 = validate_spatial_geometry(spec_v5_1)
        assert ok_v5_1, f"Expected v5-1 to pass spatial geometry, got: {errs_v5_1}"


class TestSelfHealingHR07:
    """Verify HR-07 failure manifest writing, premature drop detection, and remediation."""

    def test_write_failure_manifest(self, tmp_path):
        """Ensure write_failure_manifest writes structured JSON."""
        import json
        from pathlib import Path
        from isaaclab_arena.evaluation.policy_runner import write_failure_manifest

        payload = {
            "event": "object_dropped",
            "step": 15,
            "dropped_object_id": "yellow_banana",
            "drop_position": [-0.09, -0.1997, 0.7492],
            "support_fixture_id": "background_table",
            "failure_reason": "Premature episode termination (step 15 < 50) due to object drop / instability.",
        }
        out_p = write_failure_manifest(tmp_path, payload)
        assert Path(out_p).exists()
        loaded = json.loads(Path(out_p).read_text(encoding="utf-8"))
        assert loaded["event"] == "object_dropped"
        assert loaded["step"] == 15

    def test_evaluation_diagnostic_oracle_detects_drop_and_heals_v3(self, tmp_path):
        """Ensure oracle identifies premature drop from historical v3 eval dir and remediates spec."""
        from isaaclab_arena.agentic_environment_generation.eval_self_healing import (
            EvaluationDiagnosticOracle,
            EvaluationRemediationEngine,
        )

        eval_dir = Path("isaaclab_arena/tests/fixtures/eval_output/droid_banana_to_red_bowl/zero_action/2026-10-04_22-52-39")
        spec_v3 = ArenaEnvGraphSpec.from_yaml(
            "isaaclab_arena/tests/fixtures/droid_banana_to_red_bowl/v3/droid_banana_to_red_bowl.yaml"
        )
        policy_cfg = "isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml"

        oracle = EvaluationDiagnosticOracle()
        signatures = oracle.diagnose_eval_run(
            eval_dir=eval_dir,
            spec=spec_v3,
            policy_config_path=policy_cfg,
            num_steps_executed=500,
            healing_mode="deterministic",
        )

        drop_sigs = [s for s in signatures if s.defect_type == "object_dropped_premature_termination"]
        assert len(drop_sigs) == 1
        sig = drop_sigs[0]
        assert "yellow_banana" in sig.recommended_spatial_patches

        engine = EvaluationRemediationEngine()
        healed_spec, healed_policy, _ = engine.remediate_and_heal(
            spec=spec_v3,
            policy_config_path=policy_cfg,
            signatures=signatures,
            out_dir=tmp_path,
        )

        b_obj = next(o for o in healed_spec.objects if o.id == "yellow_banana")
        b_xyz = b_obj.params["initial_pose"]["position_xyz"]
        assert abs(b_xyz[1]) <= 0.15
        assert abs(b_xyz[2] - 0.75) < 0.05

        ok, errs = validate_spatial_geometry(healed_spec)
        assert ok, f"Expected healed spec to pass spatial geometry, got errors: {errs}"


class TestGeneralizationMilestone4HR08HR10:
    """Verification suite for Milestone 4: HR-08, HR-09, and HR-10."""

    def test_hr08_usd_chamfer_normal_exclusion_and_patch_containment(self):
        """HR-08: Ensure beveled chamfers (n_z < 0.98) are excluded and patch polygons are enforced."""
        from pxr import Gf, Usd, UsdGeom, Vt
        from isaaclab_arena.agentic_environment_generation.usd_stage_introspection import (
            _FIXTURE_PATCH_CACHE,
            extract_geometric_affordance_patches,
            resolve_fixture_support_patch,
        )
        from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
            get_known_fixture_bounds,
            get_fixture_sector_bounds,
            validate_support_containment,
        )

        stage = Usd.Stage.CreateInMemory()
        xform = UsdGeom.Xform.Define(stage, "/World/CustomBevelTable")
        mesh = UsdGeom.Mesh.Define(stage, "/World/CustomBevelTable/Mesh")

        # Flat top quad: [-0.3, -0.3, 0.75] to [0.3, 0.3, 0.75]
        # Chamfer quad: [0.3, -0.3, 0.75] to [0.4, 0.3, 0.70] (sloped down, n_z ~ 0.89 < 0.98)
        pts = [
            Gf.Vec3f(-0.3, -0.3, 0.75),  # 0
            Gf.Vec3f(0.3, -0.3, 0.75),   # 1
            Gf.Vec3f(0.3, 0.3, 0.75),    # 2
            Gf.Vec3f(-0.3, 0.3, 0.75),   # 3
            Gf.Vec3f(0.4, -0.3, 0.70),   # 4 (sloped)
            Gf.Vec3f(0.4, 0.3, 0.70),    # 5 (sloped)
        ]
        face_vertex_counts = [4, 4]
        # Quad 0: 0, 1, 2, 3 (flat top)
        # Quad 1: 1, 4, 5, 2 (chamfer slope)
        face_vertex_indices = [0, 1, 2, 3, 1, 4, 5, 2]

        mesh.GetPointsAttr().Set(Vt.Vec3fArray(pts))
        mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray(face_vertex_counts))
        mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray(face_vertex_indices))

        patches = extract_geometric_affordance_patches(
            xform.GetPrim(),
            stage,
            min_normal_z=0.98,
            safety_margin=0.02,
        )

        assert len(patches) == 1, f"Expected 1 flat patch (chamfer excluded), got {len(patches)}"
        patch = patches[0]
        poly_pts = np.array(patch.usable_polygon_hull)
        # The flat deck was [-0.3, 0.3], eroded by 0.02 -> max X must be <= 0.285 (chamfer at X in [0.3, 0.4] rejected)
        assert poly_pts[:, 0].max() <= 0.285

        # Test cache injection and bounds derivation
        cache_key = ("custom_beveled_fixture", None)
        _FIXTURE_PATCH_CACHE[cache_key] = patch

        bounds = get_known_fixture_bounds("custom_beveled_fixture")
        assert bounds[0] < bounds[1]
        assert np.isclose(bounds[4], 0.75, atol=0.05)

        sec_bounds = get_fixture_sector_bounds("custom_beveled_fixture", "front_right")
        assert sec_bounds[0] < sec_bounds[1]

    def test_hr09_embodiment_fk_exclusion_transformation(self):
        """HR-09: Ensure 3D embodiment exclusion zones dynamically transform with robot base pose."""
        from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
            compute_world_embodiment_exclusion_zones,
            validate_kinematic_reachability,
        )
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        # Standard pose: robot at [-0.4367, 0.0, 0.0] facing +X
        spec = ArenaEnvGraphSpec.from_yaml(
            "isaaclab_arena/tests/fixtures/droid_banana_to_red_bowl/v5-1/droid_banana_to_red_bowl.yaml"
        )
        zones = compute_world_embodiment_exclusion_zones(spec)
        assert len(zones) >= 1
        _, wx, wy, wz, r = zones[0]
        assert np.isclose(wx, -0.09, atol=0.01)
        assert np.isclose(wy, -0.10, atol=0.01)
        assert np.isclose(wz, 0.75, atol=0.01)

        # Rotated robot: base at [0.0, -0.4367, 0.0] facing +Y (yaw = +90 deg, rotation_xyzw = [0, 0, 0.7071068, 0.7071068])
        spec.embodiment.params["initial_pose"] = {
            "position_xyz": [0.0, -0.4367, 0.0],
            "rotation_xyzw": [0.0, 0.0, 0.7071068, 0.7071068],
        }
        rot_zones = compute_world_embodiment_exclusion_zones(spec)
        assert len(rot_zones) >= 1
        _, r_wx, r_wy, r_wz, _ = rot_zones[0]
        # Rotated +90 deg maps (dx=+0.3467, dy=-0.10) to (+0.10, +0.3467), then plus base [0, -0.4367] -> [+0.10, -0.09, 0.75]
        assert np.isclose(r_wx, 0.10, atol=0.01), f"Expected r_wx ~ 0.10, got {r_wx}"
        assert np.isclose(r_wy, -0.09, atol=0.01), f"Expected r_wy ~ -0.09, got {r_wy}"
        assert np.isclose(r_wz, 0.75, atol=0.01)

        # Place object directly inside rotated exclusion zone and verify rejection
        target_obj = next(o for o in spec.objects if o.id == "yellow_banana")
        target_obj.params["initial_pose"]["position_xyz"] = [0.10, -0.09, 0.75]
        errs = validate_kinematic_reachability(spec)
        assert any("collides with resting end-effector exclusion zone" in e for e in errs)

    def test_hr10_project_pose_to_safe_support_surface_and_track2_unification(self):
        """HR-10: Test Shapely polygon projection auto-heal and Track 2 repairs unification."""
        from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
            project_pose_to_safe_support_surface,
            validate_spatial_geometry,
        )
        from isaaclab_arena.agentic_environment_generation.workflow.repairs import (
            project_scene_repair_candidate,
        )
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        spec_v3 = ArenaEnvGraphSpec.from_yaml(
            "isaaclab_arena/tests/fixtures/droid_banana_to_red_bowl/v3/droid_banana_to_red_bowl.yaml"
        )
        # In v3, yellow_banana was placed overhanging at [-0.09, -0.1997, 0.7492]
        safe_xyz, sector = project_pose_to_safe_support_surface(spec_v3, "yellow_banana", preferred_sector="front_right")

        assert abs(safe_xyz[1]) <= 0.15
        assert np.isclose(safe_xyz[2], 0.75, atol=0.05)
        # Verify distance from resting EE (-0.09, -0.10) is >= 0.06m
        dist_ee = math.hypot(safe_xyz[0] - (-0.09), safe_xyz[1] - (-0.10))
        assert dist_ee >= 0.06, f"Distance {dist_ee} too close to resting EE"

        # Test Track 2 workflow/repairs.py adapter
        orig_dict = spec_v3.to_dict()
        candidate = project_scene_repair_candidate(orig_dict, "yellow_banana", preferred_sector="front_right")
        candidate = project_scene_repair_candidate(candidate, "red_bowl", preferred_sector="front_left")
        cand_spec = ArenaEnvGraphSpec.from_dict(candidate)
        b_obj = next(o for o in cand_spec.objects if o.id == "yellow_banana")
        assert b_obj.params["initial_pose"]["position_xyz"] == safe_xyz

        conforms, diags = validate_spatial_geometry(cand_spec)
        assert conforms, f"Projected candidate should pass spatial geometry, got {diags}"


