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


class _BodyEnv:
    """An environment exposing named robot bodies, so hand resolution can be exercised."""

    def __init__(self, names):
        self._names = names

    @property
    def scene(self):
        outer = self

        class _Scene:
            def __getitem__(self, key):
                assert key == "robot", f"only the robot is stubbed, got {key!r}"

                class _Robot:
                    body_names = outer._names

                return _Robot()

        return _Scene()


_BODIES = [
    "left_wrist_yaw_link",
    "left_hand_palm_link",
    "left_hand_middle_1_link",
    "left_hand_thumb_2_link",
    "torso_link",
]


def test_pinning_restricts_tracking_to_one_body(tmp_path):
    """Pinning must leave exactly one tracked body, so the metric cannot change frame per step.

    Minimising over several links is a selection bias rather than a measurement: the minimum over
    six links is smaller than any single link's distance, and the frame silently changes between
    steps. On this repo's own traces that understated lateral error by 3.2-5.2 cm.
    """
    tracer = ReachTracer(
        str(tmp_path / "t.jsonl"),
        _BodyEnv(_BODIES),
        object_name="apple",
        destination_name=None,
        hand_body_name="left_hand_middle_1_link",
    )

    assert list(tracer._hand_indices) == ["left_hand_middle_1_link"]


def test_unpinned_tracks_every_matching_body(tmp_path):
    """The default keeps the old behaviour, so existing callers are unchanged."""
    tracer = ReachTracer(str(tmp_path / "t.jsonl"), _BodyEnv(_BODIES), object_name="apple", destination_name=None)

    assert set(tracer._hand_indices) == {
        "left_wrist_yaw_link",
        "left_hand_palm_link",
        "left_hand_middle_1_link",
        "left_hand_thumb_2_link",
    }


def test_pinning_an_unknown_body_fails_loudly(tmp_path):
    """A typo must not silently fall back to tracking everything."""
    with pytest.raises(AssertionError, match="is not a tracked body"):
        ReachTracer(
            str(tmp_path / "t.jsonl"),
            _BodyEnv(_BODIES),
            object_name="apple",
            destination_name=None,
            hand_body_name="left_hand_middle_9_link",
        )
