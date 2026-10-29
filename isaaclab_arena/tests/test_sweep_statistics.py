# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the sweep summariser's statistics.

These pin the numbers quoted in the implementation plan's power table, so a future change to the
statistics cannot silently move the threshold at which this project believes a difference is real.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("isaaclab_arena_examples/tools").resolve()))

from summarize_support_sweep import (  # noqa: E402
    MIN_EPISODES_FOR_COMPARISON,
    clopper_pearson,
    fisher_exact_two_sided,
    holm_bonferroni,
    pairwise_comparisons,
    summarize_condition,
)


def _write_jsonl(directory: Path, records: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "episode_results_rank0.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )


def _episode(success: bool, lifted: bool = True, score: float = 1.0) -> dict:
    events = [{"predicate_name": "objects_settled"}]
    if lifted:
        events.append({"predicate_name": "object_is_above_height"})
    return {"success": success, "episode_length": 300, "progress": {"overall_score": score, "events": events}}


# ---------------------------------------------------------------------------
# Interval estimation
# ---------------------------------------------------------------------------


def test_clopper_pearson_matches_the_planned_power_table():
    """The plan quotes these half-widths to justify n=100; they must not drift."""
    pytest.importorskip("scipy")
    expected_half_widths = {20: 15.2, 50: 9.2, 70: 7.7, 100: 6.4, 200: 4.4}
    for n, expected in expected_half_widths.items():
        low, high = clopper_pearson(round(0.9 * n), n)
        half_width = 100 * (high - low) / 2
        assert half_width == pytest.approx(expected, abs=0.15), f"n={n}: {half_width:.1f} != {expected}"


def test_clopper_pearson_handles_the_degenerate_ends():
    assert clopper_pearson(0, 10)[0] == 0.0
    assert clopper_pearson(10, 10)[1] == 1.0
    assert clopper_pearson(0, 0) == (0.0, 1.0), "no episodes must give no claim, not a point estimate"


# ---------------------------------------------------------------------------
# Hypothesis testing
# ---------------------------------------------------------------------------


def test_fisher_reproduces_the_planned_significance_boundary():
    """n=20 cannot resolve 0.90 vs 0.70; n=100 can. This is why the floor is 100."""
    assert fisher_exact_two_sided(18, 2, 14, 6) == pytest.approx(0.235, abs=0.01)
    assert fisher_exact_two_sided(90, 10, 70, 30) < 0.001
    # And the case n=100 still cannot resolve, quoted in the plan as a limit.
    assert fisher_exact_two_sided(90, 10, 80, 20) == pytest.approx(0.073, abs=0.01)


def test_fisher_is_symmetric_and_bounded():
    assert fisher_exact_two_sided(18, 2, 14, 6) == pytest.approx(fisher_exact_two_sided(14, 6, 18, 2))
    assert fisher_exact_two_sided(10, 10, 10, 10) == pytest.approx(1.0)
    for table in ((5, 5, 5, 5), (0, 20, 20, 0), (1, 19, 19, 1)):
        assert 0.0 <= fisher_exact_two_sided(*table) <= 1.0


def test_identical_conditions_are_never_significant():
    assert fisher_exact_two_sided(45, 5, 45, 5) > 0.05


# ---------------------------------------------------------------------------
# Multiplicity correction
# ---------------------------------------------------------------------------


def test_holm_bonferroni_is_stricter_than_uncorrected():
    """A p-value that clears 0.05 alone may not clear it among several comparisons."""
    p_values = {("a", "b"): 0.04, ("a", "c"): 0.20, ("b", "c"): 0.30}
    corrected = holm_bonferroni(p_values)
    # 0.04 must beat alpha/3 = 0.0167 to survive; it does not.
    assert corrected[("a", "b")] is False

    p_values = {("a", "b"): 0.001, ("a", "c"): 0.20, ("b", "c"): 0.30}
    corrected = holm_bonferroni(p_values)
    assert corrected[("a", "b")] is True
    assert corrected[("a", "c")] is False


def test_holm_stops_at_the_first_failure():
    """Holm is a step-down procedure: once one hypothesis fails, the rest cannot pass."""
    p_values = {("a", "b"): 0.20, ("a", "c"): 0.0001}
    corrected = holm_bonferroni(p_values)
    assert corrected[("a", "c")] is True
    assert corrected[("a", "b")] is False


# ---------------------------------------------------------------------------
# End-to-end over synthetic runs
# ---------------------------------------------------------------------------


def test_summarize_condition_computes_the_funnel(tmp_path):
    _write_jsonl(
        tmp_path / "cond_a",
        [_episode(True)] * 9 + [_episode(False)] * 1,
    )
    summary = summarize_condition("cond_a", tmp_path / "cond_a", offset_m=-0.03)

    assert summary.episodes == 10
    assert summary.placed == 9
    assert summary.lifted == 10
    assert summary.success_rate == pytest.approx(0.9)
    assert summary.conversion_rate == pytest.approx(0.9)
    assert summary.trustworthy
    assert summary.to_dict()["underpowered"] is True


def test_false_success_marks_a_condition_untrustworthy_and_excludes_it(tmp_path):
    """A condition with a zero-progress success must not contribute to a comparison."""
    _write_jsonl(tmp_path / "good", [_episode(True)] * 50 + [_episode(False)] * 50)
    _write_jsonl(
        tmp_path / "tainted",
        [_episode(True, score=0.0)] * 5 + [_episode(True)] * 45 + [_episode(False)] * 50,
    )
    good = summarize_condition("good", tmp_path / "good", 0.0)
    tainted = summarize_condition("tainted", tmp_path / "tainted", 0.5)

    assert good.trustworthy
    assert not tainted.trustworthy
    assert tainted.false_success == 5
    assert any("not trustworthy" in note for note in tainted.notes)

    comparisons = pairwise_comparisons([good, tainted])
    assert comparisons == [], "an untrustworthy condition must be excluded from comparisons"


def test_pairwise_comparison_flags_a_real_difference(tmp_path):
    _write_jsonl(tmp_path / "high", [_episode(True)] * 90 + [_episode(False)] * 10)
    _write_jsonl(tmp_path / "low", [_episode(True)] * 50 + [_episode(False)] * 50)
    summaries = [
        summarize_condition("high", tmp_path / "high", -0.03),
        summarize_condition("low", tmp_path / "low", 0.50),
    ]
    comparisons = pairwise_comparisons(summaries)

    assert len(comparisons) == 1
    assert comparisons[0]["p_value"] < 0.001
    assert comparisons[0]["significant_holm"] is True
    assert all(s.episodes >= MIN_EPISODES_FOR_COMPARISON for s in summaries)


def test_empty_run_reports_no_data_rather_than_zero_success(tmp_path):
    """A run that recorded nothing must be distinguishable from a run that failed everything."""
    (tmp_path / "empty").mkdir(parents=True)
    (tmp_path / "empty" / "episode_results_rank0.jsonl").write_text("", encoding="utf-8")
    summary = summarize_condition("empty", tmp_path / "empty", 0.0)

    assert summary.episodes == 0
    assert not summary.trustworthy
    assert any("no episode records" in note for note in summary.notes)
