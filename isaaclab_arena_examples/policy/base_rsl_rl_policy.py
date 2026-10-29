# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import field

from isaaclab.utils.configclass import configclass
from isaaclab_rl.rsl_rl import (
    RslRlDistillationAlgorithmCfg,
    RslRlDistillationRunnerCfg,
    RslRlMLPModelCfg,
    RslRlOnPolicyRunnerCfg,
    RslRlPpoActorCriticCfg,
    RslRlPpoAlgorithmCfg,
    RslRlRNNModelCfg,
)


@configclass
class RLPolicyCfg(RslRlOnPolicyRunnerCfg):
    """Default RSL-RL runner configuration for Arena environments.

    Used as the ``rsl_rl_cfg_entry_point`` when registering environments with gym,
    allowing IsaacLab's ``train.py`` to load it via ``@hydra_task_config``.
    """

    num_steps_per_env: int = 24
    max_iterations: int = 4000
    save_interval: int = 50
    experiment_name: str = "g1_apple_to_plate_rl"
    obs_groups = field(
        default_factory=lambda: {
            "actor": ["policy", "task_obs"],
            "critic": ["policy", "task_obs"],
        }
    )
    policy: RslRlPpoActorCriticCfg = RslRlPpoActorCriticCfg(
        init_noise_std=1.0,
        actor_obs_normalization=False,
        critic_obs_normalization=False,
        actor_hidden_dims=[256, 128, 64],
        critic_hidden_dims=[256, 128, 64],
        activation="elu",
    )
    algorithm: RslRlPpoAlgorithmCfg = RslRlPpoAlgorithmCfg(
        value_loss_coef=1.0,
        use_clipped_value_loss=True,
        clip_param=0.2,
        entropy_coef=0.006,
        num_learning_epochs=5,
        num_mini_batches=4,
        learning_rate=0.0001,
        schedule="adaptive",
        gamma=0.98,
        lam=0.95,
        desired_kl=0.01,
        max_grad_norm=1.0,
    )


@configclass
class RaptorRecurrentPolicyCfg(RslRlOnPolicyRunnerCfg):
    """Recurrent policy configuration inspired by RAPTOR meta-learning.

    Equips the actor and critic with GRU recurrence to perform in-context system identification
    and adaptation over physical parameter variations (contact friction, mass, perturbation).
    """

    num_steps_per_env: int = 48
    max_iterations: int = 1500
    save_interval: int = 50
    experiment_name: str = "g1_raptor_recurrent_rl"
    obs_groups = field(
        default_factory=lambda: {
            "actor": ["policy", "task_obs"],
            "critic": ["policy", "task_obs"],
        }
    )
    actor: RslRlRNNModelCfg = RslRlRNNModelCfg(
        hidden_dims=[256, 128],
        activation="elu",
        obs_normalization=False,
        distribution_cfg=RslRlMLPModelCfg.GaussianDistributionCfg(init_std=1.0),
        rnn_type="gru",
        rnn_hidden_dim=128,
        rnn_num_layers=1,
    )
    critic: RslRlRNNModelCfg = RslRlRNNModelCfg(
        hidden_dims=[256, 128],
        activation="elu",
        obs_normalization=False,
        rnn_type="gru",
        rnn_hidden_dim=128,
        rnn_num_layers=1,
    )
    algorithm: RslRlPpoAlgorithmCfg = RslRlPpoAlgorithmCfg(
        value_loss_coef=1.0,
        use_clipped_value_loss=True,
        clip_param=0.2,
        entropy_coef=0.006,
        num_learning_epochs=5,
        num_mini_batches=4,
        learning_rate=0.0001,
        schedule="adaptive",
        gamma=0.98,
        lam=0.95,
        desired_kl=0.01,
        max_grad_norm=1.0,
    )


@configclass
class RaptorDistillationRunnerCfg(RslRlDistillationRunnerCfg):
    """RAPTOR-style Teacher-Student Meta-Learning distillation runner configuration.

    Distills a privileged MLP/RNN teacher trained on ground-truth physical parameters
    into an adaptive GRU student policy operating on observable trajectory histories.
    """

    num_steps_per_env: int = 48
    max_iterations: int = 500
    save_interval: int = 50
    experiment_name: str = "g1_raptor_distillation"
    obs_groups = field(
        default_factory=lambda: {
            "student": ["policy", "task_obs"],
            "teacher": ["policy", "task_obs"],
        }
    )
    student: RslRlRNNModelCfg = RslRlRNNModelCfg(
        hidden_dims=[256, 128],
        activation="elu",
        obs_normalization=False,
        distribution_cfg=RslRlMLPModelCfg.GaussianDistributionCfg(init_std=0.1),
        rnn_type="gru",
        rnn_hidden_dim=128,
        rnn_num_layers=1,
    )
    teacher: RslRlMLPModelCfg = RslRlMLPModelCfg(
        hidden_dims=[256, 128, 64],
        activation="elu",
        obs_normalization=False,
        distribution_cfg=RslRlMLPModelCfg.GaussianDistributionCfg(init_std=0.0),
    )
    algorithm: RslRlDistillationAlgorithmCfg = RslRlDistillationAlgorithmCfg(
        num_learning_epochs=4,
        learning_rate=1.0e-3,
        gradient_length=20,
    )
