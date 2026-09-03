# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Episode-scoped per-env scratch state for predicates that need memory across steps.

Predicates are pure functions of the current sim state, which makes them unable to express
"has this ever happened this episode?". ``EpisodeScopedState`` supplies that memory: named
per-env tensors that clear themselves the moment an env starts a new episode.

Staleness is detected from the env's own ``episode_length_buf`` rather than a reset event, so
the state stays correct whether or not progress tracking is wired up, and whether a predicate
is evaluated once or several times per step.
"""

from __future__ import annotations

import torch

from isaaclab_arena.tasks.predicates.predicate_utils import get_env

_STATE_ATTR = "_arena_episode_scoped_state"


class EpisodeScopedState:
    """Named per-env tensors that reset when an env's episode restarts.

    Each accessor takes a ``key`` naming the slot. Slots are created on first use and cleared
    per env whenever that env's episode step counter goes backwards.
    """

    def __init__(self, num_envs: int, device):
        self._num_envs = num_envs
        self._device = device
        self._latches: dict[str, torch.Tensor] = {}
        self._minima: dict[str, torch.Tensor] = {}
        self._last_step = torch.full((num_envs,), -1, dtype=torch.long, device=device)

    def sync_episode_boundary(self, episode_step: torch.Tensor | None) -> None:
        """Clear every slot for envs whose episode restarted since the last call.

        Args:
            episode_step: Per-env step counter (``episode_length_buf``), or None to skip the check.
        """
        if episode_step is None:
            return
        episode_step = episode_step.to(device=self._device, dtype=torch.long)
        # Strictly-less-than so repeated calls within one step are not mistaken for a reset.
        restarted = episode_step < self._last_step
        self._last_step = episode_step.clone()
        if not bool(restarted.any()):
            return
        for latch in self._latches.values():
            latch[:, restarted] = False
        for minimum in self._minima.values():
            minimum[restarted] = float("inf")

    def latch(self, key: str, num_stages: int, stage: int, satisfied: torch.Tensor) -> torch.Tensor:
        """Latch ``stage`` True where ``satisfied``, and return the latched mask for that stage.

        Once a stage latches for an env it stays latched until the episode restarts.
        """
        latched = self._latches.get(key)
        if latched is None or latched.shape[0] != num_stages:
            latched = torch.zeros((num_stages, self._num_envs), dtype=torch.bool, device=self._device)
            self._latches[key] = latched
        latched[stage] |= satisfied.to(device=self._device, dtype=torch.bool)
        return latched[stage]

    def running_min(self, key: str, values: torch.Tensor) -> torch.Tensor:
        """Fold ``values`` into a per-env running minimum and return it."""
        minimum = self._minima.get(key)
        if minimum is None:
            minimum = torch.full((self._num_envs,), float("inf"), device=self._device)
        minimum = torch.minimum(minimum, values.to(device=self._device, dtype=minimum.dtype))
        self._minima[key] = minimum
        return minimum


def get_episode_scoped_state(env) -> EpisodeScopedState:
    """Return the env's ``EpisodeScopedState``, creating and attaching it on first use.

    The returned state has already been advanced to the current episode boundary, so callers can
    read and write slots directly.
    """
    unwrapped = get_env(env)
    state = getattr(unwrapped, _STATE_ATTR, None)
    if state is None:
        state = EpisodeScopedState(num_envs=unwrapped.num_envs, device=unwrapped.device)
        setattr(unwrapped, _STATE_ATTR, state)
    state.sync_episode_boundary(getattr(unwrapped, "episode_length_buf", None))
    return state
