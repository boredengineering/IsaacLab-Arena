# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for RAPTOR meta-learning teacher-student distillation configurations."""

from isaaclab_rl.rsl_rl import (
    RslRlDistillationAlgorithmCfg,
    RslRlDistillationRunnerCfg,
    RslRlMLPModelCfg,
    RslRlOnPolicyRunnerCfg,
    RslRlRNNModelCfg,
)

from isaaclab_arena_examples.policy.raptor_distillation_cfg import (
    G1PrivilegedTeacherPolicyCfg,
    G1RaptorDistillationRunnerCfg,
    G1RaptorRecurrentPpoCfg,
)


def test_privileged_teacher_policy_cfg():
    """Verify privileged teacher PPO configuration and observation mappings."""
    cfg = G1PrivilegedTeacherPolicyCfg()
    assert isinstance(cfg, RslRlOnPolicyRunnerCfg)
    assert cfg.experiment_name == "g1_privileged_teacher"

    # Privileged observations must include teacher_obs for both actor and critic
    assert "teacher_obs" in cfg.obs_groups["actor"]
    assert "teacher_obs" in cfg.obs_groups["critic"]
    assert "policy" in cfg.obs_groups["actor"]
    assert "task_obs" in cfg.obs_groups["actor"]

    # MLP architecture specifications
    assert cfg.policy.actor_hidden_dims == [256, 128, 64]
    assert cfg.policy.critic_hidden_dims == [256, 128, 64]
    assert cfg.policy.activation == "elu"
    assert cfg.algorithm.learning_rate == 0.0001
    assert cfg.algorithm.schedule == "adaptive"


def test_raptor_recurrent_ppo_cfg():
    """Verify recurrent GRU PPO configuration for in-context contact adaptation."""
    cfg = G1RaptorRecurrentPpoCfg()
    assert isinstance(cfg, RslRlOnPolicyRunnerCfg)
    assert cfg.experiment_name == "g1_raptor_recurrent_ppo"

    # Recurrent policy operates strictly on observable history
    assert cfg.obs_groups["actor"] == ["policy", "task_obs"]
    assert cfg.obs_groups["critic"] == ["policy", "task_obs"]

    # GRU RNN model specifications
    assert isinstance(cfg.actor, RslRlRNNModelCfg)
    assert cfg.actor.rnn_type == "gru"
    assert cfg.actor.rnn_hidden_dim == 128
    assert cfg.actor.rnn_num_layers == 1
    assert cfg.actor.hidden_dims == [256, 128]

    assert isinstance(cfg.critic, RslRlRNNModelCfg)
    assert cfg.critic.rnn_type == "gru"
    assert cfg.critic.rnn_hidden_dim == 128


def test_raptor_distillation_runner_cfg():
    """Verify RAPTOR teacher-student distillation runner configuration."""
    cfg = G1RaptorDistillationRunnerCfg()
    assert isinstance(cfg, RslRlDistillationRunnerCfg)
    assert cfg.experiment_name == "g1_raptor_distillation"

    # Observation group routing: Student (observable) vs Teacher (privileged)
    assert cfg.obs_groups["student"] == ["policy", "task_obs"]
    assert "teacher_obs" in cfg.obs_groups["teacher"]
    assert "task_obs" in cfg.obs_groups["teacher"]
    assert "policy" in cfg.obs_groups["teacher"]

    # Student model: Recurrent GRU
    assert isinstance(cfg.student, RslRlRNNModelCfg)
    assert cfg.student.rnn_type == "gru"
    assert cfg.student.rnn_hidden_dim == 128
    assert cfg.student.rnn_num_layers == 1

    # Teacher model: Privileged MLP
    assert isinstance(cfg.teacher, RslRlMLPModelCfg)
    assert cfg.teacher.hidden_dims == [256, 128, 64]

    # Distillation algorithm
    assert isinstance(cfg.algorithm, RslRlDistillationAlgorithmCfg)
    assert cfg.algorithm.num_learning_epochs == 4
    assert cfg.algorithm.learning_rate == 1.0e-3
    assert cfg.algorithm.gradient_length == 20
