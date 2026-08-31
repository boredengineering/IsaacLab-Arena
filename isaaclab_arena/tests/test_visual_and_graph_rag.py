# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import pytest
from unittest.mock import MagicMock

from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever
from isaaclab_arena.agentic_environment_generation.visual_critic import (
    PhysXPreflightCritic,
    VisualSceneCritic,
)
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec


class TestVisualAndGraphRAG:
    def test_graph_rag_formats_priors(self):
        retriever = GraphRAGRetriever()
        mock_priors = [
            {
                "name": "mock_env",
                "task_description": "Pick cube",
                "embodiment": "droid_abs_joint_pos",
                "background": "maple_table_robolab",
                "objects": ["rubiks_cube", "bin_b04"],
            }
        ]
        context = retriever.format_priors_as_context(mock_priors)
        assert "Verified High-Performing Environment Subgraphs" in context
        assert "mock_env" in context
        assert "droid_abs_joint_pos" in context

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
                "subtasks": [
                    {
                        "kind": "PickAndPlaceTask",
                        "params": {
                            "pick_up_object": "rubiks_cube",
                            "destination_location": "tall_bin",
                            "background_scene": "maple_table",
                        },
                    }
                ],
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
            "objects": [
                {
                    "id": "rubiks_cube",
                    "registry_name": "rubiks_cube_hot3d_robolab",
                    # Floating 1.5m in the air
                    "params": {"initial_pose": {"position_xyz": [0.0, 0.0, 1.50]}},
                }
            ],
            "relations": [],
            "task": {
                "composition": "atomic",
                "description": "Test",
                "subtasks": [
                    {
                        "kind": "PickAndPlaceTask",
                        "params": {
                            "pick_up_object": "rubiks_cube",
                            "destination_location": "maple_table",
                            "background_scene": "maple_table",
                        },
                    }
                ],
            },
        }
        spec = ArenaEnvGraphSpec.from_dict(spec_dict)
        phys_critic = PhysXPreflightCritic()
        issues = phys_critic.evaluate_physical_stability(spec)
        assert len(issues) >= 1
        assert "floating high above table surface" in issues[0]
