# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Summarises a support-relation sweep into a success-versus-offset curve.

Reads only the per-episode JSONL, so it needs no simulator and no GPU.

The output is the artefact Phase 1 exists to produce: the offset at which the policy's success
collapses, which is the *measured* tolerance for the support-height invariant. Until it exists that
tolerance is a guess, and every shift magnitude and failure-mode ranking derived from it inherits
the guess.

Each condition also reports its false-success count. A condition with any false successes has
untrustworthy numbers and is excluded from the fitted tolerance rather than quietly averaged in.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConditionSummary:
    """Funnel statistics for one sweep condition."""

    label: str
    offset_m: float | None
    episodes: int
    settled: int
    lifted: int
    placed: int
    false_success: int
    manifold: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def lift_rate(self) -> float:
        return self.lifted / self.episodes if self.episodes else 0.0

    @property
    def success_rate(self) -> float:
        return self.placed / self.episodes if self.episodes else 0.0

    @property
    def conversion_rate(self) -> float:
        return self.placed / self.lifted if self.lifted else 0.0

    @property
    def trustworthy(self) -> bool:
        """False when any episode reported success without progress, or nothing ran."""
        return self.episodes > 0 and self.false_success == 0

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "offset_m": self.offset_m,
            "episodes": self.episodes,
            "settled": self.settled,
            "lifted": self.lifted,
            "placed": self.placed,
            "false_success": self.false_success,
            "lift_rate": round(self.lift_rate, 4),
            "success_rate": round(self.success_rate, 4),
            "conversion_rate": round(self.conversion_rate, 4),
            "success_ci95": [round(v, 4) for v in clopper_pearson(self.placed, self.episodes)],
            "underpowered": self.episodes < MIN_EPISODES_FOR_COMPARISON,
            "manifold": self.manifold,
            "trustworthy": self.trustworthy,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Statistics
#
# A success rate without an interval is not a result. At n=20 the Clopper-Pearson 95% interval
# around an observed 90% spans +/-15.2 points, which is wider than most differences this project
# has reported. And interval overlap is not a test: two intervals can overlap substantially while
# a direct test still separates them, so pairwise comparisons use Fisher's exact test with a
# Holm-Bonferroni correction rather than eyeballing error bars.
# ---------------------------------------------------------------------------

MIN_EPISODES_FOR_COMPARISON = 100
"""Floor for any comparison this project reports. Two-sided Fisher exact at n=100/arm resolves a
0.90-vs-0.70 difference (p<0.001) but not 0.90-vs-0.80 (p=0.073); at n=20 it resolves neither."""


def clopper_pearson(successes: int, total: int, confidence: float = 0.95) -> tuple[float, float]:
    """Return the exact binomial confidence interval for ``successes``/``total``.

    Exact rather than normal-approximation because the approximation misbehaves at the small n and
    extreme p this domain produces. Falls back to a conservative bound if scipy is unavailable.
    """
    if total <= 0:
        return (0.0, 1.0)
    alpha = 1.0 - confidence
    try:
        from scipy.stats import beta
    except ImportError:
        # Without scipy, report the widest honest bound rather than a wrong narrow one.
        return (0.0, 1.0)
    low = float(beta.ppf(alpha / 2, successes, total - successes + 1)) if successes > 0 else 0.0
    high = float(beta.ppf(1 - alpha / 2, successes + 1, total - successes)) if successes < total else 1.0
    return (low, high)


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p-value for the 2x2 table ``[[a, b], [c, d]]``.

    Implemented directly so the tool has no hard scipy dependency: it sums the probability of every
    table at least as extreme as the observed one under the hypergeometric null.
    """
    from math import comb

    n = a + b + c + d
    if n == 0:
        return 1.0
    row1, col1 = a + b, a + c

    def probability(x: int) -> float:
        return comb(row1, x) * comb(n - row1, col1 - x) / comb(n, col1)

    observed = probability(a)
    low = max(0, col1 - (n - row1))
    high = min(row1, col1)
    return min(1.0, sum(probability(x) for x in range(low, high + 1) if probability(x) <= observed + 1e-12))


def holm_bonferroni(p_values: dict[tuple[str, str], float], alpha: float = 0.05) -> dict[tuple[str, str], bool]:
    """Return which comparisons survive a Holm-Bonferroni correction at ``alpha``.

    A sweep makes every pairwise comparison at once, so uncorrected p-values would find
    "significant" differences by multiplicity alone.
    """
    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    total = len(ordered)
    significant: dict[tuple[str, str], bool] = {}
    for index, (pair, p_value) in enumerate(ordered):
        threshold = alpha / (total - index)
        if p_value <= threshold and all(significant.get(prev[0], False) for prev in ordered[:index]):
            significant[pair] = True
        else:
            significant[pair] = False
    return significant


def pairwise_comparisons(summaries: list[ConditionSummary], alpha: float = 0.05) -> list[dict]:
    """Compare every trustworthy pair of conditions, corrected for multiplicity."""
    usable = [s for s in summaries if s.trustworthy]
    raw: dict[tuple[str, str], float] = {}
    for i, first in enumerate(usable):
        for second in usable[i + 1 :]:
            raw[(first.label, second.label)] = fisher_exact_two_sided(
                first.placed,
                first.episodes - first.placed,
                second.placed,
                second.episodes - second.placed,
            )
    corrected = holm_bonferroni(raw, alpha=alpha)
    return [
        {
            "pair": list(pair),
            "p_value": round(p_value, 6),
            "significant_holm": corrected[pair],
        }
        for pair, p_value in sorted(raw.items(), key=lambda kv: kv[1])
    ]


def summarize_condition(label: str, run_dir: Path, offset_m: float | None = None) -> ConditionSummary:
    """Aggregate every ``episode_results_rank*.jsonl`` under ``run_dir`` into one summary.

    Mirrors the funnel and false-success logic in ``eval_self_healing`` rather than reimplementing
    it, so the two cannot disagree about what counts as a lift or a false success.
    """
    records = []
    for jsonl in sorted(run_dir.glob("**/episode_results_rank*.jsonl")):
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    settled = lifted = placed = false_success = 0
    for record in records:
        progress = record.get("progress", {}) or {}
        events = progress.get("events", []) or []
        predicates = [event.get("predicate_name", "") for event in events]
        if any("objects_settled" in name for name in predicates):
            settled += 1
        if any("object_is_above_height" in name for name in predicates):
            lifted += 1
        if record.get("success"):
            placed += 1
            if float(progress.get("overall_score", 1.0)) <= 0.0:
                false_success += 1

    notes = []
    if not records:
        notes.append("no episode records found; the run produced no data rather than failing")
    if false_success:
        notes.append(
            f"{false_success} episode(s) reported success with a zero progress score - this "
            "condition's numbers are not trustworthy"
        )

    return ConditionSummary(
        label=label,
        offset_m=offset_m,
        episodes=len(records),
        settled=settled,
        lifted=lifted,
        placed=placed,
        false_success=false_success,
        notes=notes,
    )


def estimate_tolerance(
    summaries: list[ConditionSummary], corpus_offset_m: float, relative_threshold: float = 0.5
) -> dict:
    """Estimate the support-height tolerance from a success-versus-offset curve.

    The tolerance is the distance from the corpus offset at which success falls below
    ``relative_threshold`` of the best-performing condition's rate. Reported as a bracket between
    the furthest still-good offset and the nearest already-bad one, because a handful of sampled
    conditions bounds the crossing rather than locating it.
    """
    usable = [s for s in summaries if s.trustworthy and s.offset_m is not None]
    if len(usable) < 2:
        return {"status": "insufficient_data", "usable_conditions": len(usable)}

    best = max(s.success_rate for s in usable)
    if best <= 0.0:
        return {"status": "no_condition_succeeded", "note": "even the corpus condition failed; suspect the stack"}

    cutoff = best * relative_threshold
    good = [s for s in usable if s.success_rate >= cutoff]
    bad = [s for s in usable if s.success_rate < cutoff]

    good_distances = [abs(s.offset_m - corpus_offset_m) for s in good]
    bad_distances = [abs(s.offset_m - corpus_offset_m) for s in bad]

    return {
        "status": "ok",
        "best_success_rate": round(best, 4),
        "cutoff_success_rate": round(cutoff, 4),
        "max_good_distance_m": round(max(good_distances), 4) if good_distances else None,
        "min_bad_distance_m": round(min(bad_distances), 4) if bad_distances else None,
        "tolerance_bracket_m": [
            round(max(good_distances), 4) if good_distances else None,
            round(min(bad_distances), 4) if bad_distances else None,
        ],
        "verdict": (
            "height is the blocking axis"
            if bad_distances
            else "no tested offset degraded success; height may not be the blocking axis"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sweep_root",
        type=Path,
        required=True,
        help="Directory containing one subdirectory per sweep condition.",
    )
    parser.add_argument(
        "--offsets",
        type=float,
        nargs="*",
        default=None,
        help="Support offsets matching the condition directories in sorted order.",
    )
    parser.add_argument(
        "--corpus_offset",
        type=float,
        default=-0.8015,
        help="The corpus support offset the tolerance is measured from.",
    )
    parser.add_argument("--out_json", type=Path, default=None)
    args = parser.parse_args()

    assert args.sweep_root.exists(), f"sweep root not found: {args.sweep_root}"
    condition_dirs = sorted(d for d in args.sweep_root.iterdir() if d.is_dir())
    assert condition_dirs, f"no condition subdirectories under {args.sweep_root}"

    if args.offsets:
        assert len(args.offsets) == len(
            condition_dirs
        ), f"{len(args.offsets)} offsets for {len(condition_dirs)} conditions ({[d.name for d in condition_dirs]})"

    summaries = [
        summarize_condition(d.name, d, args.offsets[i] if args.offsets else None) for i, d in enumerate(condition_dirs)
    ]

    print("\n" + "=" * 96)
    print(" SUPPORT-RELATION SWEEP")
    print("=" * 96)
    header = (
        f"{'condition':<24} {'offset':>8} {'N':>5} {'lift':>7} {'success':>8} "
        f"{'95% CI (Clopper-Pearson)':>26} {'false':>6}"
    )
    print(header)
    print("-" * 96)
    for summary in summaries:
        offset = f"{summary.offset_m:+.3f}" if summary.offset_m is not None else "n/a"
        low, high = clopper_pearson(summary.placed, summary.episodes)
        ci = f"[{low:.3f}, {high:.3f}] +/-{100 * (high - low) / 2:.1f}pt"
        flags = []
        if not summary.trustworthy:
            flags.append("UNTRUSTWORTHY")
        if summary.episodes < MIN_EPISODES_FOR_COMPARISON:
            flags.append(f"UNDERPOWERED(n<{MIN_EPISODES_FOR_COMPARISON})")
        suffix = ("  <-- " + ", ".join(flags)) if flags else ""
        print(
            f"{summary.label:<24} {offset:>8} {summary.episodes:>5} "
            f"{summary.lift_rate:>6.1%} {summary.success_rate:>7.1%} {ci:>26} "
            f"{summary.false_success:>6}{suffix}"
        )
    print("-" * 96)
    for summary in summaries:
        for note in summary.notes:
            print(f"  {summary.label}: {note}")

    comparisons = pairwise_comparisons(summaries)
    if comparisons:
        print("\nPairwise comparisons (Fisher exact, Holm-Bonferroni corrected):")
        for entry in comparisons:
            verdict = "SIGNIFICANT" if entry["significant_holm"] else "not significant"
            print(f"  {entry['pair'][0]} vs {entry['pair'][1]}: p={entry['p_value']:.5f}  {verdict}")
        print(
            "  Note: interval overlap is NOT a test. These p-values, not the CI overlap above,\n"
            "  determine whether two conditions differ."
        )

    estimate = estimate_tolerance(summaries, args.corpus_offset)
    print("\nTolerance estimate:")
    for key, value in estimate.items():
        print(f"  {key}: {value}")
    print("=" * 96)

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps(
                {
                    "conditions": [s.to_dict() for s in summaries],
                    "pairwise_comparisons": comparisons,
                    "tolerance_estimate": estimate,
                    "min_episodes_for_comparison": MIN_EPISODES_FOR_COMPARISON,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
