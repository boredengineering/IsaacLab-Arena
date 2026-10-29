# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure frozen policy identities, readiness and episode aggregation codecs."""

import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from .contracts import Count, Duration, FrozenModel, Hash, Identifier, Text


@dataclass(frozen=True)
class PolicyPrerequisiteReadiness:
    """Pure disposition; the owner must persist it and reserve policy atomically."""

    status: Literal["ready_for_policy", "accepted", "blocked"]
    terminal: bool
    reserve_policy: bool


def policy_prerequisite_readiness(*, required_policy: bool, prerequisites_established: bool):
    """Keep required policy work nonterminal; this function releases no effects."""
    if type(required_policy) is not bool or type(prerequisites_established) is not bool:
        raise TypeError("policy readiness requires explicit booleans")
    if not prerequisites_established:
        return PolicyPrerequisiteReadiness("blocked", False, False)
    if required_policy:
        return PolicyPrerequisiteReadiness("ready_for_policy", False, True)
    return PolicyPrerequisiteReadiness("accepted", True, False)


class PolicyTaskBinding(FrozenModel):
    """Freeze execution identity; these pins are requirements, not runtime attestation."""

    candidate_digest: Hash
    contract_digest: Hash
    policy_artifact_digest: Hash
    policy_config_digest: Hash
    observation_interface_digest: Hash
    action_interface_digest: Hash
    transport_digest: Hash
    task_definition_digest: Hash
    evaluator_digest: Hash
    runtime_digest: Hash
    embodiment_id: Identifier
    policy_adapter_id: Identifier
    task_id: Identifier
    evaluator_id: Identifier
    instruction: Text
    environment_id: Identifier
    realization_id: Identifier
    reset_id: Identifier
    seed: Count
    max_policy_steps: Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
    max_episodes: Annotated[int, Field(strict=True, ge=1, le=512)]
    """One bounded retained trial; larger campaigns require separately admitted trials."""
    deadline_unix: Duration
    minimum_successes: Annotated[int, Field(strict=True, ge=1, le=512)]
    max_prerequisite_steps: Count

    @model_validator(mode="after")
    def bounded_aggregation(self):
        if self.minimum_successes > self.max_episodes:
            raise ValueError("policy aggregation exceeds episode budget")
        return self

    def digest(self) -> str:
        """Return the v1 canonical binding digest, separate from artifact byte hashes."""
        data = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode()).hexdigest()


class PolicyEpisode(FrozenModel):
    """One completed episode, supplied by the selected task evaluator."""

    binding_digest: Hash
    episode_id: Identifier
    reset_id: Identifier
    seed: Count
    success: Annotated[bool, Field(strict=True)] | None


class PolicyAggregate(FrozenModel):
    binding_digest: Hash
    completed: Count
    successes: Count
    success_rate: float | None
    outcome: Literal["passed", "failed", "unknown"]


def aggregate_policy_episodes(binding: PolicyTaskBinding, episodes: tuple[PolicyEpisode, ...]) -> PolicyAggregate:
    """Aggregate completed task outcomes without inventing an empty denominator."""
    binding = PolicyTaskBinding.model_validate(binding.model_dump())
    if not isinstance(episodes, tuple) or len(episodes) > binding.max_episodes:
        raise ValueError("invalid policy episode collection")
    episodes = tuple(PolicyEpisode.model_validate(episode.model_dump()) for episode in episodes)
    identities = {(episode.episode_id, episode.reset_id) for episode in episodes}
    if (
        len(identities) != len(episodes)
        or len({episode.episode_id for episode in episodes}) != len(episodes)
        or len({episode.reset_id for episode in episodes}) != len(episodes)
    ):
        raise ValueError("duplicate policy episode")
    if any(episode.binding_digest != binding.digest() or episode.seed != binding.seed for episode in episodes):
        raise ValueError("policy episode binding mismatch")
    completed = len(episodes)
    successes = sum(episode.success is True for episode in episodes)
    rate_unknown = not completed or any(episode.success is None for episode in episodes)
    unknown = completed < binding.max_episodes or rate_unknown
    return PolicyAggregate(
        binding_digest=binding.digest(),
        completed=completed,
        successes=successes,
        success_rate=None if rate_unknown else successes / completed,
        outcome="unknown" if unknown else "passed" if successes >= binding.minimum_successes else "failed",
    )


class PolicyTrialReceipt(FrozenModel):
    """Verified immutable trial metadata; byte verification is a trusted port duty."""

    codec_version: Literal[1] = 1
    intent_id: Hash
    episode_records_digest: Hash
    binding: PolicyTaskBinding
    episodes: Annotated[tuple[PolicyEpisode, ...], Field(max_length=512)]
    manifest_digest: Hash
    policy_steps: Count
    prerequisite_steps: Count

    @model_validator(mode="after")
    def bounded_trial(self):
        aggregate_policy_episodes(self.binding, self.episodes)
        if self.episodes and self.episodes[0].reset_id != self.binding.reset_id:
            raise ValueError("policy initial reset mismatch")
        if (
            len(self.episodes) > self.policy_steps
            or self.policy_steps > self.binding.max_policy_steps
            or self.prerequisite_steps > self.binding.max_prerequisite_steps
        ):
            raise ValueError("policy trial step budget exceeded")
        return self

    def aggregate(self) -> PolicyAggregate:
        return aggregate_policy_episodes(self.binding, self.episodes)


class PolicyCohortReadiness(FrozenModel):
    """Trusted producer result for one initialized or newly autoreset cohort."""

    binding_digest: Hash
    reset_id: Identifier
    established: Annotated[bool, Field(strict=True)]
    terminated: Annotated[bool, Field(strict=True)]
    truncated: Annotated[bool, Field(strict=True)]
    steps: Count


@dataclass(frozen=True)
class ManagedPolicyResult:
    """Local results only; the owner retains artifacts and decides adoption."""

    metrics: Any
    episodes: tuple[PolicyEpisode, ...]
    aggregate: PolicyAggregate
    prerequisite_steps: int
