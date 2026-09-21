# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Managed policy runtime bridge; pure codecs are compatibility re-exports."""

import math
from typing import TYPE_CHECKING, Any, Callable

from .policy_contracts import (  # noqa: F401 - compatibility re-exports
    ManagedPolicyResult,
    PolicyAggregate,
    PolicyCohortReadiness,
    PolicyEpisode,
    PolicyPrerequisiteReadiness,
    PolicyTaskBinding,
    aggregate_policy_episodes,
    policy_prerequisite_readiness,
)

if TYPE_CHECKING:
    from isaaclab_arena.tasks.task_base import TaskBase


def run_managed_policy(
    binding: PolicyTaskBinding,
    *,
    env,
    policy,
    task: "TaskBase",
    initialized_observation: Any,
    verify_runtime: Callable,
    prepare_cohort: Callable,
    read_episodes: Callable,
    clock: Callable[[], float],
    rollout: Callable | None = None,
) -> ManagedPolicyResult:
    """Reuse Arena rollout with task-specific trusted verification/evaluator ports.

    The caller owns environment/policy creation, authorization, watchdog, cleanup
    and artifact retention. ``verify_runtime`` receives binding, env, policy,
    TaskBase, termination config and metrics; it must attest the observed binding
    or return None for unsupported pins. ``prepare_cohort`` receives the binding,
    env, observation, reset env IDs and remaining prerequisite-step allocation,
    returning (observation, PolicyCohortReadiness). It owns bounded hold/settle
    work and its step accounting. ``read_episodes(binding, env)`` reads completed
    records through the selected evaluator, not a generic manipulation predicate.

    This direct rollout path never invokes CLI telemetry, graph synchronization,
    report serving or legacy version-tree updates. No default native adapter is
    provided: generic pins alone cannot establish a supported runtime.
    """
    binding = PolicyTaskBinding.model_validate(binding.model_dump())
    terminations, task_metrics = task.get_termination_cfg(), task.get_metrics()
    prerequisite_steps = 0
    reset_ids = set()
    current_reset = None
    completed_resets = []

    def guard():
        now = clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now >= binding.deadline_unix:
            raise ValueError("policy deadline exceeded or unavailable")
        if type(env.unwrapped.num_envs) is not int or env.unwrapped.num_envs != 1:
            raise ValueError("managed policy requires one environment")
        if (
            task.get_task_description() != binding.instruction
            or env.unwrapped.get_language_instruction() != binding.instruction
        ):
            raise ValueError("policy task instruction mismatch")
        observed = verify_runtime(binding, env, policy, task, terminations, task_metrics)
        if not isinstance(observed, PolicyTaskBinding):
            raise ValueError("policy runtime pins unsupported or unverified")
        if PolicyTaskBinding.model_validate(observed.model_dump()) != binding:
            raise ValueError("policy runtime pin mismatch")
        now = clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now >= binding.deadline_unix:
            raise ValueError("policy deadline exceeded or unavailable")

    guard()

    def prepare(env_arg, observation, env_ids):
        nonlocal prerequisite_steps, current_reset
        guard()
        observation, readiness = prepare_cohort(
            binding, env_arg, observation, env_ids, binding.max_prerequisite_steps - prerequisite_steps
        )
        readiness = PolicyCohortReadiness.model_validate(readiness.model_dump())
        prerequisite_steps += readiness.steps
        if (
            readiness.binding_digest != binding.digest()
            or not readiness.established
            or readiness.terminated
            or readiness.truncated
        ):
            raise ValueError("policy prerequisites not established")
        if prerequisite_steps > binding.max_prerequisite_steps:
            raise ValueError("policy prerequisite step budget exceeded")
        if readiness.reset_id in reset_ids or (not reset_ids and readiness.reset_id != binding.reset_id):
            raise ValueError("policy prerequisite reset mismatch")
        reset_ids.add(readiness.reset_id)
        current_reset = readiness.reset_id
        guard()
        return observation

    def completed(env_ids):
        assert current_reset is not None and env_ids.tolist() == [0], "Invalid managed completed cohort"
        completed_resets.append(current_reset)

    if rollout is None:
        from isaaclab_arena.evaluation.policy_runner import rollout_policy

        rollout = rollout_policy
    metrics = rollout(
        env,
        policy,
        binding.max_policy_steps,
        None,
        check_settling=False,
        initialized_observation=initialized_observation,
        post_reset=prepare,
        episode_limit=binding.max_episodes,
        before_action=guard,
        before_step=guard,
        on_episode_completed=completed,
    )
    guard()
    episodes = read_episodes(binding, env)
    guard()
    aggregate = aggregate_policy_episodes(binding, episodes)
    if tuple(episode.reset_id for episode in episodes) != tuple(completed_resets):
        raise ValueError("policy episode completion/readback mismatch")
    return ManagedPolicyResult(metrics, episodes, aggregate, prerequisite_steps)
