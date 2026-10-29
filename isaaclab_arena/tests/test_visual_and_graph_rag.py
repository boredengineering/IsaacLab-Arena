# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0


from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever
from isaaclab_arena.agentic_environment_generation.visual_critic import PhysXPreflightCritic, VisualSceneCritic
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec


class TestVisualAndGraphRAG:
    def test_graph_rag_formats_measured_priors(self):
        retriever = GraphRAGRetriever()
        mock_priors = [{
            "name": "mock_env",
            "task_description": "Pick cube",
            "task_composition": "atomic",
            "embodiment": "droid_abs_joint_pos",
            "background": "maple_table_robolab",
            "objects": ["rubiks_cube", "bin_b04"],
            "relations": [
                {"relation_type": "PLACED_ON", "manifold": "tabletop_stationary_reach", "anchor": "table_top"}
            ],
            "success_rate": 0.6,
            "episodes": 20,
            "evidence": "measured",
        }]
        context = retriever.format_priors_as_context(mock_priors)
        assert "mock_env" in context
        assert "droid_abs_joint_pos" in context
        # The measured outcome must be stated, so the model can weigh the prior.
        assert "success_rate=0.6" in context
        assert "20 episode(s)" in context
        # Relations carry the invariant the policy actually depends on, so they must survive.
        assert "PLACED_ON" in context
        assert "tabletop_stationary_reach" in context
        assert "atomic" in context

    def test_graph_rag_does_not_claim_quality_for_unevaluated_priors(self):
        """An unevaluated prior is structural precedent only and must not be sold as verified."""
        retriever = GraphRAGRetriever()
        context = retriever.format_priors_as_context([{
            "name": "unevaluated_env",
            "task_description": "Pick cube",
            "embodiment": "droid_abs_joint_pos",
            "background": "maple_table_robolab",
            "objects": ["rubiks_cube"],
            "relations": [],
            "success_rate": None,
            "episodes": None,
            "evidence": "unevaluated",
        }])
        assert "unevaluated_env" in context
        assert "never evaluated" in context
        assert "High-Performing" not in context
        assert "Verified" not in context

    def test_graph_rag_formats_empty_priors_as_empty_string(self):
        assert GraphRAGRetriever().format_priors_as_context([]) == ""

    def test_visual_critic_detects_occlusion(self):
        spec_dict = {
            "env_name": "test_occlusion",
            "embodiment": {
                "id": "droid",
                "registry_name": "droid_abs_joint_pos",
                "params": {"initial_pose": {"position_xyz": [-0.55, 0.0, 0.0]}},
            },
            "background": {
                "id": "maple_table",
                "registry_name": "maple_table_robolab",
                "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0]}},
            },
            "objects": [
                {
                    "id": "tall_bin",
                    "registry_name": "bin_b04_vomp_robolab",
                    # Placed directly in front of robot
                    "params": {"initial_pose": {"position_xyz": [-0.20, 0.0, 0.75]}},
                },
                {
                    "id": "rubiks_cube",
                    "registry_name": "rubiks_cube_hot3d_robolab",
                    # Placed directly behind the tall bin along X axis
                    "params": {"initial_pose": {"position_xyz": [0.10, 0.0, 0.75]}},
                },
            ],
            "relations": [
                {"kind": "is_anchor", "subject": "maple_table", "params": {}},
                {"kind": "on", "subject": "tall_bin", "reference": "maple_table", "params": {}},
                {"kind": "on", "subject": "rubiks_cube", "reference": "maple_table", "params": {}},
            ],
            "task": {
                "composition": "atomic",
                "description": "Pick cube",
                "subtasks": [{
                    "kind": "PickAndPlaceTask",
                    "params": {
                        "pick_up_object": "rubiks_cube",
                        "destination_location": "tall_bin",
                        "background_scene": "maple_table",
                    },
                }],
            },
        }
        spec = ArenaEnvGraphSpec.from_dict(spec_dict)
        critic = VisualSceneCritic()
        res = critic.evaluate_scene_spec(spec)
        assert not res.conforms
        assert "visually occluded" in res.actionable_feedback

    def test_physx_preflight_critic_detects_floating_objects(self):
        spec_dict = {
            "env_name": "test_physx",
            "embodiment": {
                "id": "droid",
                "registry_name": "droid_abs_joint_pos",
                "params": {"initial_pose": {"position_xyz": [-0.55, 0.0, 0.0]}},
            },
            "background": {
                "id": "maple_table",
                "registry_name": "maple_table_robolab",
                "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 0.0]}},
            },
            "objects": [{
                "id": "rubiks_cube",
                "registry_name": "rubiks_cube_hot3d_robolab",
                # Floating 1.5m in the air
                "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 1.50]}},
            }],
            "relations": [],
            "task": {
                "composition": "atomic",
                "description": "Test",
                "subtasks": [{
                    "kind": "PickAndPlaceTask",
                    "params": {
                        "pick_up_object": "rubiks_cube",
                        "destination_location": "maple_table",
                        "background_scene": "maple_table",
                    },
                }],
            },
        }
        spec = ArenaEnvGraphSpec.from_dict(spec_dict)
        phys_critic = PhysXPreflightCritic()
        issues = phys_critic.evaluate_physical_stability(spec)
        assert len(issues) >= 1
        assert "floating high above table surface" in issues[0]

    def test_visual_critic_step0_preflight_prompt_and_tier2_vlm_call(self):
        """Ensure HR-05 Step-0 preflight prompt explicitly instructs VLM not to expect objects inside container at Step 0."""
        import json
        from unittest.mock import MagicMock, patch

        spec = ArenaEnvGraphSpec.from_yaml(
            "isaaclab_arena/tests/fixtures/droid_banana_to_red_bowl/v5-1/droid_banana_to_red_bowl.yaml"
        )
        critic = VisualSceneCritic(local_vlm_model="Qwen/Qwen2.5-VL-7B-Instruct", strict_mode=True)
        prompt = critic._build_step0_preflight_prompt(spec)
        assert "STEP-0 INITIAL SPAWN PREFLIGHT CHECK" in prompt
        assert "MUST NOT already be inside the destination container/bowl" in prompt
        assert "gripper fingers at Step 0" in prompt
        assert "beveled table edges/chamfers" in prompt

        mock_resp = MagicMock()
        mock_resp.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "conforms": True,
                        "visibility_score": 9.5,
                        "occluded_objects": [],
                        "floating_objects": [],
                        "anomalies": [],
                        "actionable_feedback": "",
                        "actionable_corrections": {},
                    })
                }
            }]
        }).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            res = critic.evaluate_scene_spec(spec, rendered_images={"table_cam": b"\x89PNG\r\n\x1a\n"})
            assert res.conforms
            assert res.tier_used == "tier_2_local_vlm"
            sent_req = mock_urlopen.call_args[0][0]
            sent_body = json.loads(sent_req.data.decode("utf-8"))
            assert sent_body["model"] == "Qwen/Qwen2.5-VL-7B-Instruct"
            assert "STEP-0 INITIAL SPAWN PREFLIGHT CHECK" in sent_body["messages"][0]["content"][0]["text"]

    def test_telemetry_card_tier_transparency_hr06(self):
        """Verify HR-06 ActiveInferenceTelemetry exports and renders transparent critic tier statuses."""
        from isaaclab_arena.agentic_environment_generation import ActiveInferenceTelemetry as ExportedTelemetry
        from isaaclab_arena.agentic_environment_generation.telemetry import ActiveInferenceTelemetry

        assert ExportedTelemetry is ActiveInferenceTelemetry
        t = ActiveInferenceTelemetry(repair_iterations=1)
        t.visual_critic_status = "Bypassed (No Frames)"
        t.physics_preflight_status = "Bypassed (Pure Python)"
        card = t.render_summary_card()
        assert "Active Bayesian Inference" in card
        assert "Repair Iterations:   1" in card
        assert "Bypassed (No Frames)" in card
        assert "Bypassed (Pure Python)" in card
        assert "Verification Grade:" in card

    def test_encode_rgb_and_grounded_resolve_cli_mode(self):
        """Verify HR-05 PNG encoding and grounded-resolve CLI mode registration."""
        import numpy as np
        from isaaclab_arena.cli.isaaclab_arena_cli import get_isaaclab_arena_cli_parser
        from isaaclab_arena_examples.agentic_environment_generation.environment_generation_runner import (
            _encode_rgb_array_to_png_bytes,
            add_agentic_env_gen_runner_cli_args,
        )

        rgb = np.zeros((16, 16, 3), dtype=np.uint8)
        png_bytes = _encode_rgb_array_to_png_bytes(rgb)
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

        parser = get_isaaclab_arena_cli_parser()
        add_agentic_env_gen_runner_cli_args(parser)
        args = parser.parse_args(["--mode", "grounded-resolve", "--prompt", "test prompt"])
        assert args.mode == "grounded-resolve"

    def test_run_grounded_resolve_repairs_and_verifies_loop(self, tmp_path):
        """Verify HR-05 run_grounded_resolve executes settle + VLM check and refines on failure."""
        import argparse
        from unittest.mock import patch
        from isaaclab_arena.agentic_environment_generation.visual_critic import VisualCriticResult
        from isaaclab_arena_examples.agentic_environment_generation.environment_generation_runner import (
            run_grounded_resolve,
        )

        v5_path = "isaaclab_arena/tests/fixtures/droid_banana_to_red_bowl/v5-1/droid_banana_to_red_bowl.yaml"
        spec_copy = tmp_path / "candidate_spec.yaml"
        spec_copy.write_text(open(v5_path, encoding="utf-8").read(), encoding="utf-8")

        args = argparse.Namespace(
            mode="grounded-resolve",
            prompt="Place banana in red bowl",
            env_name="test_grounded_resolve_env",
            base_spec=spec_copy,
            base_url="http://127.0.0.1:9999/v1",
            model=None,
            api_key=None,
            temperature=0.2,
            num_steps=30,
            strict_critics=False,
            out_dir=tmp_path,
            feedback=None,
        )

        settle_calls = [
            (False, ["Object 'yellow_banana' displaced 0.22m during 30-step PhysX settle."], {"cam": b"\x89PNG\r\n\x1a\n"}),
            (True, [], {"cam": b"\x89PNG\r\n\x1a\n"}),
        ]
        vlm_calls = [
            VisualCriticResult(
                conforms=False,
                visibility_score=5.0,
                anomalies=["Object near beveled edge"],
                actionable_feedback="Shift banana inward toward center",
                tier_used="tier_2_local_vlm",
            ),
            VisualCriticResult(
                conforms=True,
                visibility_score=9.8,
                anomalies=[],
                actionable_feedback="",
                tier_used="tier_2_local_vlm",
            ),
        ]

        with (
            patch(
                "isaaclab_arena_examples.agentic_environment_generation.environment_generation_runner.resolve_env_spec",
                return_value=spec_copy,
            ),
            patch(
                "isaaclab_arena_examples.agentic_environment_generation.environment_generation_runner._settle_and_capture_frames",
                side_effect=settle_calls,
            ) as mock_settle,
            patch(
                "isaaclab_arena.agentic_environment_generation.visual_critic.VisualSceneCritic.evaluate_scene_spec",
                side_effect=vlm_calls,
            ) as mock_vlm,
        ):
            out_path = run_grounded_resolve(args)
            assert out_path.exists()
            assert mock_settle.call_count == 2
            assert mock_vlm.call_count == 2


