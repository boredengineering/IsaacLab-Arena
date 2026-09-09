# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import pytest


def _test_g1_apple_to_plate_rl_environment_build(simulation_app):
    """Inner test function executed inside running SimulationApp."""
    from isaaclab_arena.assets.registries import EnvironmentRegistry, TaskRegistry
    from isaaclab_arena.tasks.pick_and_place_task_rl import PickAndPlaceTaskRL
    from isaaclab_arena_environments.g1_apple_to_plate_rl_environment import (
        G1AppleToPlateRLEnvironment,
        G1AppleToPlateRLEnvironmentCfg,
    )

    task_cls = TaskRegistry().get_component_by_name("PickAndPlaceTaskRL")
    assert task_cls is PickAndPlaceTaskRL, "PickAndPlaceTaskRL must be registered in TaskRegistry"

    env_cls = EnvironmentRegistry().get_component_by_name("g1_apple_to_plate_rl")
    assert env_cls is G1AppleToPlateRLEnvironment, "g1_apple_to_plate_rl must be in EnvironmentRegistry"

    factory = G1AppleToPlateRLEnvironment()
    cfg = G1AppleToPlateRLEnvironmentCfg()
    arena_env = factory.build(cfg)

    assert arena_env.name == "g1_apple_to_plate_rl"
    assert arena_env.embodiment.name == "g1_wbc_agile_diff_ik"
    assert isinstance(arena_env.task, PickAndPlaceTaskRL)
    assert arena_env.rl_framework_entry_point == "rsl_rl_cfg_entry_point"
    assert "RLPolicyCfg" in arena_env.rl_policy_cfg
    assert arena_env.embodiment.observation_config.policy.concatenate_terms is True
    assert arena_env.embodiment.observation_config.wbc is None

    # Check RL observation terms
    obs_cfg = arena_env.task.get_observation_cfg()
    assert hasattr(obs_cfg, "task_obs"), "Observation config must define task_obs group"
    assert hasattr(obs_cfg.task_obs, "object_position")
    assert hasattr(obs_cfg.task_obs, "destination_position")
    assert hasattr(obs_cfg.task_obs, "ee_position")
    assert hasattr(obs_cfg.task_obs, "ee_to_object")
    assert hasattr(obs_cfg.task_obs, "object_to_destination")
    assert hasattr(obs_cfg.task_obs, "is_lifted")

    # Check RL reward terms
    rew_cfg = arena_env.task.get_rewards_cfg()
    assert hasattr(rew_cfg, "reaching_object")
    assert hasattr(rew_cfg, "lifting_object")
    assert hasattr(rew_cfg, "transporting_object")
    assert hasattr(rew_cfg, "placed_bonus")
    assert hasattr(rew_cfg, "action_rate")
    assert hasattr(rew_cfg, "arm_joint_vel")
    assert hasattr(rew_cfg, "multi_keypoint_guidance")
    assert rew_cfg.reaching_object.weight == 2.0
    assert rew_cfg.lifting_object.weight == 10.0
    assert rew_cfg.transporting_object.weight == 15.0
    assert rew_cfg.placed_bonus.weight == 20.0
    assert rew_cfg.action_rate.weight == -0.005
    assert rew_cfg.arm_joint_vel.weight == -0.0005
    assert rew_cfg.multi_keypoint_guidance.weight == 3.0

    # Check RL termination terms
    term_cfg = arena_env.task.get_termination_cfg()
    assert hasattr(term_cfg, "time_out")
    assert hasattr(term_cfg, "object_dropped")
    assert term_cfg.success is not None, "RL termination must include dynamic success term for SuccessRecorder"

    # Check that in evaluation mode (default), reverse curriculum terms are inactive
    eval_events_cfg = arena_env.task.get_events_cfg()
    assert eval_events_cfg.reset_robot_curriculum is None
    assert eval_events_cfg.reset_object_curriculum is None

    # Check that in training mode, reverse curriculum terms are properly attached
    cfg_train = G1AppleToPlateRLEnvironmentCfg(rl_training_mode=True)
    arena_env_train = factory.build(cfg_train)
    train_events_cfg = arena_env_train.task.get_events_cfg()
    assert train_events_cfg.reset_robot_curriculum is not None
    assert train_events_cfg.reset_robot_curriculum.params["curriculum_ratio"] == 0.50
    assert train_events_cfg.reset_object_curriculum is None

    # Check explicit lift curriculum configuration
    cfg_lift = G1AppleToPlateRLEnvironmentCfg(rl_training_mode=True, lift_curriculum_ratio=0.15)
    train_lift_events = factory.build(cfg_lift).task.get_events_cfg()
    assert train_lift_events.reset_object_curriculum is not None
    assert train_lift_events.reset_object_curriculum.params["lift_curriculum_ratio"] == 0.15

    # Verify environment instantiation and 7-D Diff-IK action stepping with training curriculum active
    import torch

    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg

    builder = ArenaEnvBuilder(arena_env_train, ArenaEnvBuilderCfg(num_envs=4))
    env = builder.make_registered()
    obs, _ = env.reset()
    assert (
        env.unwrapped.action_manager.total_action_dim == 7
    ), f"Expected action dim 7 for Diff-IK, got {env.unwrapped.action_manager.total_action_dim}"

    action = torch.zeros((4, 7), device=env.unwrapped.device)
    obs, rew, term, trunc, info = env.step(action)
    assert obs["policy"].shape[0] == 4
    assert not torch.isnan(rew).any(), "Rewards contain NaNs"
    env.close()

    return True


def test_g1_apple_to_plate_rl_environment_build():
    """Verify G1 tabletop apple to plate RL environment structure inside simulation app."""
    pytest.importorskip("isaaclab.app")
    from isaaclab_arena.tests.utils.subprocess import run_simulation_app_function

    result = run_simulation_app_function(_test_g1_apple_to_plate_rl_environment_build)
    assert result
