# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for ``ReachTracer``'s per-episode bookkeeping.

No simulator is needed: the episode boundary and resting-reference logic is tensor manipulation,
and a stub environment is enough to reach it. Importing the module still requires ``warp``, so
these run wherever the Arena package imports.
"""

import json
import torch

import pytest

from isaaclab_arena.evaluation.policy_runner import ReachTracer


class _StubEnv:
    """An environment whose scene lookups fail, so no hand bodies are resolved."""

    @property
    def scene(self):
        raise KeyError("stub environment exposes no scene")


def _tracer(tmp_path, envs: int) -> ReachTracer:
    """Return a tracer with its per-episode state seeded as if ``envs`` rows had been recorded."""
    tracer = ReachTracer(
        str(tmp_path / "trace.jsonl"),
        _StubEnv(),
        object_name="apple",
        destination_name=None,
    )
    tracer._rest_z = torch.zeros(envs)
    tracer._episode_index = torch.zeros(envs, dtype=torch.long)
    tracer._step_in_episode = 7
    return tracer


def test_begin_episode_advances_the_index_and_clears_the_reference(tmp_path):
    """A reset must start a new episode and drop the old resting height.

    Carrying the previous episode's resting height forward reports every later episode's lift
    against the wrong datum, which is why the evidence appendix's per-episode tables could not be
    re-derived from an earlier trace.
    """
    tracer = _tracer(tmp_path, envs=1)

    tracer.begin_episode(torch.tensor([0]))

    assert tracer._episode_index.tolist() == [1]
    assert torch.isnan(tracer._rest_z).all()
    assert tracer._step_in_episode == 0


def test_begin_episode_only_touches_the_environments_that_reset(tmp_path):
    """A partial reset must leave the still-running environments' episodes and references intact."""
    tracer = _tracer(tmp_path, envs=3)
    tracer._rest_z = torch.tensor([0.10, 0.20, 0.30])

    tracer.begin_episode(torch.tensor([1]))

    assert tracer._episode_index.tolist() == [0, 1, 0]
    assert tracer._rest_z[0].item() == pytest.approx(0.10)
    assert torch.isnan(tracer._rest_z[1])
    assert tracer._rest_z[2].item() == pytest.approx(0.30)


def test_begin_episode_with_no_ids_resets_every_environment(tmp_path):
    """Omitting the ids means a whole-scene reset."""
    tracer = _tracer(tmp_path, envs=2)

    tracer.begin_episode()

    assert tracer._episode_index.tolist() == [1, 1]
    assert torch.isnan(tracer._rest_z).all()


def test_begin_episode_before_any_record_is_a_no_op(tmp_path):
    """Nothing has been recorded, so there is no episode to close and nothing to reset."""
    tracer = ReachTracer(str(tmp_path / "trace.jsonl"), _StubEnv(), object_name="apple", destination_name=None)

    tracer.begin_episode(torch.tensor([0]))

    assert tracer._rest_z is None
    assert tracer._episode_index is None


def test_close_writes_rows_carrying_the_episode_index(tmp_path):
    """Each written row must name its episode, so a trace can be split per episode."""
    path = tmp_path / "trace.jsonl"
    tracer = _tracer(tmp_path, envs=1)
    tracer._rows = [
        json.dumps({"step": 0, "episode": [0]}),
        json.dumps({"step": 1, "episode": [1]}),
    ]

    tracer.close()

    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert [row["episode"] for row in rows] == [[0], [1]]
