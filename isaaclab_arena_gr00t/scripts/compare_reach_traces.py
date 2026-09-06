# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Compare arms on vertical reach error, read from ``ReachTracer`` traces.

The quantity of interest is ``hand_z_minus_obj`` **at closest horizontal approach**: a policy with
accurate bearing and poor range converges in XY off a correct heading while missing in Z, which
presents as closing the hand on air. Success rate alone hides that entirely -- two arms can both
fail every episode with vertical errors differing by centimetres.

**Per-episode statistics require an episode index, and older traces have none.** Every trace
written before ``ReachTracer.begin_episode`` existed is one undifferentiated stream, so "closest
horizontal approach" over such a file yields a single global minimum rather than a distribution
over episodes. This script reports that case as one sample and says so, rather than presenting a
mean over episodes it cannot separate -- which is exactly how a reach table becomes
irreproducible.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    """Return a trace's rows, skipping blank lines.

    Args:
        path: Path to a ``ReachTracer`` JSONL trace.

    Returns:
        The parsed rows.
    """
    with open(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def scalar(value, env: int) -> float | None:
    """Return one environment's entry from a trace field, which is a per-environment list.

    Args:
        value: The field, normally a list with one entry per environment.
        env: Environment index.

    Returns:
        The value as a float, or None when it is absent or null.
    """
    if value is None:
        return None
    if isinstance(value, list):
        if env >= len(value) or value[env] is None:
            return None
        return float(value[env])
    return float(value)


def closest_approach(rows: list[dict], env: int) -> dict | None:
    """Return the row at minimum horizontal hand-to-object distance, with its vertical error.

    Args:
        rows: Rows belonging to one episode, or a whole stream when no episode index exists.
        env: Environment index.

    Returns:
        Mapping with the horizontal distance, the signed vertical error and the step, or None when
        the rows carry no hand columns.
    """
    best = None
    for row in rows:
        xy = scalar(row.get("hand_xy_to_obj"), env)
        z = scalar(row.get("hand_z_minus_obj"), env)
        if xy is None or z is None:
            continue
        if best is None or xy < best["hand_xy_to_obj"]:
            best = {
                "hand_xy_to_obj": xy,
                "hand_z_minus_obj": z,
                "step": row.get("step"),
                "hand_body": row.get("hand_body"),
            }
    return best


def group_by_episode(rows: list[dict], env: int) -> tuple[list[list[dict]], bool]:
    """Split rows into episodes, reporting whether the trace actually carries an index.

    Args:
        rows: All rows of a trace.
        env: Environment index.

    Returns:
        Tuple of the episode groups and whether an episode index was present. Without one the
        whole trace is returned as a single group.
    """
    if not rows or "episode" not in rows[0]:
        return [rows], False
    groups: dict[int, list[dict]] = {}
    for row in rows:
        index = scalar(row.get("episode"), env)
        groups.setdefault(int(index) if index is not None else -1, []).append(row)
    return [groups[key] for key in sorted(groups)], True


def summarise(path: Path, env: int) -> dict:
    """Return one trace's reach summary.

    Args:
        path: Path to the trace.
        env: Environment index.

    Returns:
        Mapping describing the trace and its vertical-error statistics.
    """
    rows = load_rows(path)
    groups, indexed = group_by_episode(rows, env)
    approaches = [a for a in (closest_approach(group, env) for group in groups) if a]

    lifts = [v for v in (scalar(row.get("lift"), env) for row in rows) if v is not None]
    summary = {
        "trace": str(path),
        "rows": len(rows),
        "episode_indexed": indexed,
        "episodes": len(groups) if indexed else None,
        "samples": len(approaches),
        "max_lift_m": max(lifts) if lifts else None,
        "has_hand_columns": bool(approaches),
    }
    if approaches:
        zs = [a["hand_z_minus_obj"] for a in approaches]
        xys = [a["hand_xy_to_obj"] for a in approaches]
        summary["hand_z_minus_obj"] = {
            "median": statistics.median(zs),
            "mean": statistics.fmean(zs),
            "stdev": statistics.stdev(zs) if len(zs) > 1 else None,
            "min": min(zs),
            "max": max(zs),
            "values": [round(v, 5) for v in zs],
        }
        summary["hand_xy_to_obj_at_closest"] = {
            "median": statistics.median(xys),
            "mean": statistics.fmean(xys),
        }
    return summary


def report(summary: dict) -> None:
    """Print one trace's summary, naming what the numbers can and cannot support."""
    name = Path(summary["trace"]).name
    print(f"\n{name}")
    print(f"  rows {summary['rows']}", end="")
    if summary["episode_indexed"]:
        print(f", {summary['episodes']} episodes")
    else:
        print(", NO episode index")
    if not summary["has_hand_columns"]:
        print("  no hand columns: this trace predates hand tracing and says nothing about reach")
        return
    stats = summary["hand_z_minus_obj"]
    if summary["episode_indexed"]:
        spread = "" if stats["stdev"] is None else f"  sd {stats['stdev']:.4f}"
        print(
            f"  hand_z_minus_obj at closest approach: median {stats['median']:+.4f} m"
            f"  mean {stats['mean']:+.4f}{spread}  over {summary['samples']} episodes"
        )
        print(f"  range {stats['min']:+.4f} to {stats['max']:+.4f} m")
    else:
        print(
            f"  hand_z_minus_obj at closest approach: {stats['median']:+.4f} m"
            "  -- ONE global sample, not a distribution"
        )
        print("  the trace has no episode boundaries, so a per-episode mean cannot be computed from it")
    print(f"  horizontal distance there: {summary['hand_xy_to_obj_at_closest']['median']:.4f} m")
    if summary["max_lift_m"] is not None:
        print(f"  max lift observed: {summary['max_lift_m']:+.4f} m")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Return parsed command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("traces", type=Path, nargs="+", help="ReachTracer JSONL traces to compare.")
    parser.add_argument("--env", type=int, default=0, help="Environment index within each row.")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Summarise each trace and, when two or more carry reach data, print their difference."""
    args = parse_args(argv)

    summaries = []
    for path in args.traces:
        if not path.is_file():
            print(f"[compare] no trace at {path}; skipping")
            continue
        summary = summarise(path, args.env)
        summaries.append(summary)
        report(summary)

    usable = [s for s in summaries if s["has_hand_columns"]]
    if len(usable) >= 2:
        print("\n--- vertical error at closest approach ---")
        for summary in usable:
            stats = summary["hand_z_minus_obj"]
            label = "median" if summary["episode_indexed"] else "single"
            print(f"  {Path(summary['trace']).name:42s} {stats['median']:+.4f} m  ({label}, n={summary['samples']})")
        first, last = usable[0], usable[-1]
        delta = last["hand_z_minus_obj"]["median"] - first["hand_z_minus_obj"]["median"]
        print(f"\n  difference (last - first): {delta:+.4f} m  ({100 * delta:+.2f} cm)")
        if not all(s["episode_indexed"] for s in usable):
            print(
                "  WARNING: at least one trace has no episode index, so this difference compares"
                " single samples and carries no spread. Re-run those arms with the repaired"
                " tracer before reporting it."
            )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as handle:
            json.dump(summaries, handle, indent=2)
        print(f"\n[compare] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
