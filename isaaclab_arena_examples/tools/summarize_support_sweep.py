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
            "manifold": self.manifold,
            "trustworthy": self.trustworthy,
            "notes": list(self.notes),
        }


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
            f"condition's numbers are not trustworthy"
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
        assert len(args.offsets) == len(condition_dirs), (
            f"{len(args.offsets)} offsets for {len(condition_dirs)} conditions "
            f"({[d.name for d in condition_dirs]})"
        )

    summaries = [
        summarize_condition(d.name, d, args.offsets[i] if args.offsets else None)
        for i, d in enumerate(condition_dirs)
    ]

    print("\n" + "=" * 96)
    print(" SUPPORT-RELATION SWEEP")
    print("=" * 96)
    header = f"{'condition':<26} {'offset':>8} {'N':>4} {'lift':>7} {'success':>8} {'conv':>7} {'false':>6}"
    print(header)
    print("-" * 96)
    for summary in summaries:
        offset = f"{summary.offset_m:+.3f}" if summary.offset_m is not None else "n/a"
        flag = "" if summary.trustworthy else "  <-- UNTRUSTWORTHY"
        print(
            f"{summary.label:<26} {offset:>8} {summary.episodes:>4} "
            f"{summary.lift_rate:>6.1%} {summary.success_rate:>7.1%} "
            f"{summary.conversion_rate:>6.1%} {summary.false_success:>6}{flag}"
        )
    print("-" * 96)
    for summary in summaries:
        for note in summary.notes:
            print(f"  {summary.label}: {note}")

    estimate = estimate_tolerance(summaries, args.corpus_offset)
    print("\nTolerance estimate:")
    for key, value in estimate.items():
        print(f"  {key}: {value}")
    print("=" * 96)

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps(
                {"conditions": [s.to_dict() for s in summaries], "tolerance_estimate": estimate},
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
