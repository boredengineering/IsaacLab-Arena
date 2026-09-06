# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the reach-trace comparison, which decides whether an arm improved vertical reach.

Worth testing carefully because a plausible-looking wrong answer here is the failure that already
happened once: the historical reach tables were computed from traces with no episode boundaries and
quoted as per-episode figures.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "compare_reach_traces.py"
_spec = importlib.util.spec_from_file_location("compare_reach_traces", _MODULE_PATH)
compare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare)


def _write(tmp_path: Path, rows: list[dict], name: str = "trace.jsonl") -> Path:
    """Write rows as a JSONL trace and return its path."""
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def test_closest_approach_picks_the_minimum_horizontal_row():
    """The reported vertical error must come from the row of nearest horizontal approach.

    Not the minimum vertical error, and not the last row: a policy that misses high converges in XY
    while still above the object, and the vertical error *at that moment* is the quantity of
    interest.
    """
    rows = [
        {"step": 0, "hand_xy_to_obj": [0.20], "hand_z_minus_obj": [0.01]},
        {"step": 1, "hand_xy_to_obj": [0.01], "hand_z_minus_obj": [0.07]},
        {"step": 2, "hand_xy_to_obj": [0.15], "hand_z_minus_obj": [0.02]},
    ]

    best = compare.closest_approach(rows, env=0)

    assert best["step"] == 1
    assert best["hand_z_minus_obj"] == pytest.approx(0.07)


def test_closest_approach_is_none_without_hand_columns():
    """A trace predating hand tracing must yield nothing rather than a fabricated zero."""
    rows = [{"step": 0, "obj_z": [0.02], "speed": [0.0]}]

    assert compare.closest_approach(rows, env=0) is None


def test_group_by_episode_reports_when_there_is_no_index():
    """Without an episode index the whole trace is one group, and the caller must be told."""
    rows = [{"step": i, "hand_xy_to_obj": [0.1], "hand_z_minus_obj": [0.05]} for i in range(4)]

    groups, indexed = compare.group_by_episode(rows, env=0)

    assert indexed is False
    assert len(groups) == 1
    assert len(groups[0]) == 4


def test_group_by_episode_splits_on_the_index():
    """With an index, rows must be grouped per episode so each yields its own approach."""
    rows = [
        {"step": 0, "episode": [0]},
        {"step": 1, "episode": [0]},
        {"step": 2, "episode": [1]},
    ]

    groups, indexed = compare.group_by_episode(rows, env=0)

    assert indexed is True
    assert [len(g) for g in groups] == [2, 1]


def test_summarise_yields_one_sample_per_episode(tmp_path):
    """Each episode contributes exactly one closest-approach sample."""
    path = _write(
        tmp_path,
        [
            {"step": 0, "episode": [0], "hand_xy_to_obj": [0.02], "hand_z_minus_obj": [0.06]},
            {"step": 1, "episode": [0], "hand_xy_to_obj": [0.30], "hand_z_minus_obj": [0.01]},
            {"step": 2, "episode": [1], "hand_xy_to_obj": [0.01], "hand_z_minus_obj": [0.08]},
        ],
    )

    summary = compare.summarise(path, env=0)

    assert summary["episode_indexed"] is True
    assert summary["episodes"] == 2
    assert summary["samples"] == 2
    assert summary["hand_z_minus_obj"]["values"] == [0.06, 0.08]
    assert summary["hand_z_minus_obj"]["median"] == pytest.approx(0.07)


def test_summarise_marks_an_unindexed_trace_as_a_single_sample(tmp_path):
    """An unindexed trace must report one sample, never a mean over episodes it cannot separate."""
    path = _write(
        tmp_path,
        [
            {"step": 0, "hand_xy_to_obj": [0.02], "hand_z_minus_obj": [0.06]},
            {"step": 1, "hand_xy_to_obj": [0.01], "hand_z_minus_obj": [0.09]},
        ],
    )

    summary = compare.summarise(path, env=0)

    assert summary["episode_indexed"] is False
    assert summary["samples"] == 1
    assert summary["hand_z_minus_obj"]["values"] == [0.09]
    assert summary["hand_z_minus_obj"]["stdev"] is None


def test_summarise_flags_a_trace_with_no_hand_columns(tmp_path):
    """Ten of thirteen historical traces are this case, so it must be reported, not crashed on."""
    path = _write(tmp_path, [{"step": 0, "obj_z": [0.02], "speed": [0.0]}])

    summary = compare.summarise(path, env=0)

    assert summary["has_hand_columns"] is False
    assert "hand_z_minus_obj" not in summary


def test_scalar_tolerates_absent_and_null_entries():
    """``lift`` is null before the resting reference exists, and must not become 0.0."""
    assert compare.scalar(None, env=0) is None
    assert compare.scalar([None], env=0) is None
    assert compare.scalar([], env=0) is None
    assert compare.scalar([0.5], env=0) == pytest.approx(0.5)
    assert compare.scalar([0.1, 0.9], env=1) == pytest.approx(0.9)


def test_max_lift_ignores_nulls(tmp_path):
    """A null lift is "not yet known", so it must not be treated as a value."""
    path = _write(
        tmp_path,
        [
            {"step": 0, "lift": [None], "hand_xy_to_obj": [0.02], "hand_z_minus_obj": [0.06]},
            {"step": 1, "lift": [0.014], "hand_xy_to_obj": [0.03], "hand_z_minus_obj": [0.05]},
        ],
    )

    summary = compare.summarise(path, env=0)

    assert summary["max_lift_m"] == pytest.approx(0.014)
