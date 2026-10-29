"""Independently recount Category A/B episode evidence and emit a compact run inventory."""

import csv
import hashlib
import json
import math
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".agents/references/presentations"


def median(values):
    return statistics.median(values) if values else None


def has_lift(record):
    return any(event.get("predicate_name", "").split("(")[0] in
               ("object_is_above_height", "object_lifted_above_resting_min")
               for event in record.get("progress", {}).get("events", []))


def first_event_steps(records, names):
    steps = []
    for record in records:
        matching = [event["step"] for event in record.get("progress", {}).get("events", [])
                    if event.get("predicate_name", "").split("(")[0] in names]
        if matching:
            steps.append(min(matching))
    return steps


def main():
    a = json.loads((ROOT / ".agents/scratch/category_ab_a_audit.json").read_text())
    b = json.loads((ROOT / ".agents/scratch/category_ab_b_audit.json").read_text())
    graph = json.loads((ROOT / ".agents/scratch/category_ab_graph_audit.json").read_text())
    graph_by_id = {r["id"]: r for r in graph["evaluations"] if r["id"]}
    entries = [("A", r) for r in a["runs"]] + [("B", r) for r in b["runs"]]
    output = []
    all_row_hashes = set()
    all_run_paths = set()
    for category, audited in entries:
        path = Path(audited.get("run_dir", audited.get("run_path", "")))
        assert path.is_dir() and path not in all_run_paths, path
        all_run_paths.add(path)
        records = []
        sources = []
        for source in sorted(path.glob("episode_results_rank*.jsonl")):
            raw = source.read_bytes()
            sources.append({"path": str(source.relative_to(ROOT)), "sha256": hashlib.sha256(raw).hexdigest()})
            keys = set()
            for line_number, line in enumerate(raw.decode().splitlines(), 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                assert isinstance(record["success"], bool), (source, line_number)
                key = (record.get("job_name"), record.get("seed"), record["env_id"], record["episode_in_env"])
                assert key not in keys, (source, key)
                keys.add(key)
                row_hash = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
                assert row_hash not in all_row_hashes, (source, line_number, "duplicate exact episode")
                all_row_hashes.add(row_hash)
                records.append(record)
        n = len(records)
        successes = sum(r["success"] for r in records)
        lifted = sum(has_lift(r) for r in records)
        complete = sum(r.get("progress", {}).get("all_complete", False) for r in records)
        intersection = sum(r["success"] and has_lift(r) for r in records)
        assert n == audited.get("episode_count", audited.get("episode_denominator")), path
        expected_success = audited.get("raw_success", audited.get("success"))
        assert successes == expected_success.get("numerator", expected_success.get("count")), path
        assert lifted == audited["lift_event"].get("numerator", audited["lift_event"].get("count")), path
        expected_complete = audited.get("progress_all_complete", audited.get("progress", {}).get("all_complete"))
        assert complete == expected_complete.get("numerator", expected_complete.get("count")), path
        expected_conversion = audited.get("raw_success_among_lifted", audited.get("conversion_success_given_lift"))
        assert intersection == expected_conversion.get("numerator", expected_conversion.get("count")), path
        ttl = path / "eval_telemetry.ttl"
        ttl_metrics = {}
        evaluation_id = None
        if ttl.exists():
            text = ttl.read_text()
            ids = re.findall(r":(eval_run_\d+)\s+a\s", text)
            assert len(ids) == 1, ttl
            evaluation_id = ids[0]
            for key in ("num_episodes", "success_rate", "object_moved_rate"):
                match = re.search(r"arena:metric_" + key + r'\s+(?:"([^"]+)"|([^\s;]+))', text)
                if match:
                    value = float(match.group(1) or match.group(2))
                    ttl_metrics[key] = value if math.isfinite(value) else None
            assert ttl_metrics["num_episodes"] == n, ttl
            if n:
                assert math.isclose(ttl_metrics["success_rate"], successes / n), ttl
            sources.append({"path": str(ttl.relative_to(ROOT)), "sha256": hashlib.sha256(ttl.read_bytes()).hexdigest()})
        graph_row = graph_by_id.get(evaluation_id)
        if graph_row:
            assert graph_row["num_episodes"] == n, evaluation_id
            if n:
                assert math.isclose(graph_row["success_rate"], successes / n), evaluation_id
        version = audited.get("version") if category == "A" else audited.get("version_assignment", {}).get("version")
        version_basis = audited.get("version_basis") if category == "A" else audited.get("version_assignment", {}).get("basis")
        candidate = audited.get("version_candidate")
        current = path.name == "2026-09-09_04-37-42"
        family = path.parent.name
        if category == "A":
            family = "droid_apple_to_wooden_bowl"
        moved_rate = ttl_metrics.get("object_moved_rate")
        lift_steps = first_event_steps(records, ("object_is_above_height", "object_lifted_above_resting_min"))
        contact_success_steps = first_event_steps([r for r in records if r["success"]], ("object_on_destination",))
        if category == "B" and n:
            metrics = audited["progress"]["event_metrics"]
            assert median(lift_steps) == metrics["object_is_above_height"]["first_completion_step"]["median"]
            if "object_on_destination" in metrics:
                assert median(contact_success_steps) == metrics["object_on_destination"]["first_completion_step_among_success"]["median"]
        row = {
            "category": category, "scenario_family": family, "run_path": str(path.relative_to(ROOT)),
            "evaluated_graph_recorded": audited.get("evaluated_graph", (audited.get("telemetry") or {}).get("evaluated_graph")),
            "run_timestamp": path.name, "evaluation_id": evaluation_id,
            "period": "current_verified_run" if current else ("current_empty_attempt" if category == "A" and path.name.startswith("2026-09-09") else "historical"),
            "version": version, "version_candidate": candidate, "version_basis": version_basis,
            "episodes": n, "success_flags": successes, "success_rate": successes / n if n else None,
            "lift_event_episodes": lifted, "progress_complete_episodes": complete,
            "success_and_lift": intersection, "success_given_lift": intersection / lifted if lifted else None,
            "success_without_lift": successes - intersection,
            "success_progress_incomplete": sum(r["success"] and not r.get("progress", {}).get("all_complete", False) for r in records),
            "failure_progress_complete": sum(not r["success"] and r.get("progress", {}).get("all_complete", False) for r in records),
            "reported_object_moved_rate": moved_rate,
            "moved_count_derived_from_aggregate": round(moved_rate * n) if n and moved_rate is not None else None,
            "median_episode_steps_all": median([r["episode_length"] for r in records]),
            "median_episode_steps_success_flags": median([r["episode_length"] for r in records if r["success"]]),
            "median_episode_steps_progress_complete": median([r["episode_length"] for r in records if r.get("progress", {}).get("all_complete")]),
            "median_first_lift_event_step": median(lift_steps),
            "median_first_destination_event_step_among_success_flags": median(contact_success_steps),
            "seeds": sorted({r.get("seed") for r in records}),
            "observed_env_ids": sorted({r["env_id"] for r in records}),
            "historical_checkpoint_pinned": False if not current else True,
            "checkpoint": "nvidia/GR00T-N1.6-DROID" if current else None,
            "actual_executed_chunk_verified": 16 if current else None,
            "current_config_or_context_chunk": audited.get("action_chunk_length", audited.get("configuration", {}).get("action_chunk_length_current_file")),
            "graph_node_found": graph_row is not None,
            "graph_environment_links": graph_row["environments"] if graph_row else None,
            "sources": sources,
        }
        output.append(row)
    output.sort(key=lambda r: (r["category"], r["scenario_family"], r["run_timestamp"]))
    counts = {"candidate_runs": len(output), "nonempty_runs": sum(r["episodes"] > 0 for r in output),
              "empty_runs": sum(r["episodes"] == 0 for r in output),
              "episode_records_audited_not_a_pooled_benchmark": sum(r["episodes"] for r in output)}
    assert counts == {"candidate_runs": 25, "nonempty_runs": 18, "empty_runs": 7,
                      "episode_records_audited_not_a_pooled_benchmark": 406}, counts
    artifact = {"audit_date": "2026-09-09", "counts": counts,
                "caveats": ["Raw success flags and progress completion are distinct archived labels, not physical certification.",
                            "No per-run historical checkpoint/source/chunk receipt was recovered.",
                            "All nonempty episode records have seed 42; do not treat environment IDs as independent seeds.",
                            "Moved counts are reconstructed from TTL velocity-metric aggregates, not remeasured.",
                            "Do not pool versions/pilots/current run or count duplicate JSONL/TTL/HTML/graph representations."],
                "runs": output}
    json_path = OUT / "category_a_b_run_inventory.json"
    json_path.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n")
    csv_path = OUT / "category_a_b_run_inventory.csv"
    fields = [k for k in output[0] if k != "sources"]
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in output:
            writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k,v in row.items() if k in fields})
    print(json.dumps(counts))
    for row in output:
        print(row["category"], row["run_path"], f'{row["success_flags"]}/{row["episodes"]}',
              "lift", row["lift_event_episodes"], "complete", row["progress_complete_episodes"],
              "intersection", row["success_and_lift"], "medians", row["median_episode_steps_all"], row["median_episode_steps_success_flags"])
    print("VERIFIED", json_path, csv_path)


if __name__ == "__main__":
    main()
