# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""RAPTOR Meta-Learning & Privileged Teacher-Student Distillation Configurations.

Inspired by RAPTOR (Eschmann, Albani, Loianno, 2026; github.com/rl-tools/raptor),
this module specifies:
1. G1PrivilegedTeacherPolicyCfg: Privileged PPO training with ground-truth physical state
   (object velocities, contact normals, hand keypoint offsets).
2. G1RaptorRecurrentStudentCfg: Recurrent GRU policy that compresses interaction history
   to perform implicit in-context system identification and zero-shot physical adaptation.
3. G1RaptorDistillationRunnerCfg: Teacher-student meta-distillation runner transferring
   privileged skills into the recurrent student across physical parameter variations.
4. G1RaptorRecurrentPpoCfg: End-to-end recurrent PPO baseline runner.
"""

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
class G1PrivilegedTeacherPolicyCfg(RslRlOnPolicyRunnerCfg):
    """Privileged teacher PPO configuration for G1 tabletop manipulation.

    The teacher policy observes both proprioceptive/task state and privileged physics state
    (object velocities, contact normals, hand keypoint offsets) to discover robust
    manipulation trajectories under full observability.
    """

    num_steps_per_env: int = 24
    max_iterations: int = 1000
    save_interval: int = 50
    experiment_name: str = "g1_privileged_teacher"
    obs_groups = field(
        default_factory=lambda: {
            "actor": ["policy", "task_obs", "teacher_obs"],
            "critic": ["policy", "task_obs", "teacher_obs"],
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
class G1RaptorRecurrentPpoCfg(RslRlOnPolicyRunnerCfg):
    """Recurrent PPO baseline configuration with GRU memory.

    Equips both actor and critic with GRU recurrence over observable states
    (policy + task_obs) to adapt to contact events and payload mass online.
    """

    num_steps_per_env: int = 48
    max_iterations: int = 1500
    save_interval: int = 50
    experiment_name: str = "g1_raptor_recurrent_ppo"
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
class G1RaptorDistillationRunnerCfg(RslRlDistillationRunnerCfg):
    """RAPTOR-style Teacher-Student Meta-Learning distillation runner.

    Distills a privileged MLP teacher (trained with ground-truth state)
    into an adaptive GRU student policy operating strictly on observable histories.
    The student's recurrent hidden state performs online implicit system identification.
    """

    num_steps_per_env: int = 48
    max_iterations: int = 500
    save_interval: int = 50
    experiment_name: str = "g1_raptor_distillation"
    obs_groups = field(
        default_factory=lambda: {
            "student": ["policy", "task_obs"],
            "teacher": ["policy", "task_obs", "teacher_obs"],
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
