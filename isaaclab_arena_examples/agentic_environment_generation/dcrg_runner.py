# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""CLI wiring for the bounded DCRG controller; shared algorithms live in the core package."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.dcrg import graph
from isaaclab_arena.agentic_environment_generation.dcrg.evaluation import read_episode_evidence, run_rollout
from isaaclab_arena.agentic_environment_generation.dcrg.loop import (
    DCRGConfig,
    EpisodeEvidence,
    EvaluationEvidence,
    run_dcrg,
    spec_digest,
)
from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import (
    fetch_recurrent_feedback_from_neo4j,
    get_neo4j_driver,
    sync_recurrent_feedback_to_neo4j,
)
from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
    KNOWN_FIXTURE_BOUNDS,
    get_fixture_sector_bounds,
    relax_spec_active_inference,
)
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec


def support_bounds(spec: ArenaEnvGraphSpec) -> tuple[float, float, float, float]:
    """Resolve a conservative world-XY rectangle for a known, unrotated support fixture.

    Args:
        spec: Scene with explicit background pose and known fixture geometry.

    Returns:
        Target-center bounds in metres, inset by a 4 cm edge margin.
    """
    pose = spec.background.params["initial_pose"]
    assert pose.get("rotation_xyzw", [0, 0, 0, 1]) == [0, 0, 0, 1], "rotated support requires measured bounds"
    assert spec.background.registry_name in KNOWN_FIXTURE_BOUNDS, "Unknown support requires measured bounds"
    x, y, _ = pose["position_xyz"]
    xmin, xmax, ymin, ymax, _ = get_fixture_sector_bounds(spec.background.registry_name, None)
    return x + xmin + 0.04, x + xmax - 0.04, y + ymin + 0.04, y + ymax - 0.04


def main(argv: list[str] | None = None) -> None:
    """Run a bounded experiment; all simulator and graph writes use verified adapters."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_spec", type=Path, required=True)
    parser.add_argument("--policy_config", type=Path, required=True)
    parser.add_argument("--policy_identity", required=True, help="Actual running checkpoint identity, not a YAML label")
    parser.add_argument("--scenario_contract", required=True, help="Explicit task/arm contract for this experiment")
    parser.add_argument("--run_dir", type=Path, required=True)
    parser.add_argument("--hand_body", required=True)
    parser.add_argument("--remote_port", type=int, default=5561)
    parser.add_argument("--neo4j_uri", default=None)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 7])
    parser.add_argument("--episodes_per_seed", type=int, default=2)
    parser.add_argument("--max_candidates", type=int, default=1)
    parser.add_argument("--max_displacement_m", type=float, default=0.01)
    parser.add_argument("--proposal_seed", type=int, default=42)
    parser.add_argument("--timeout_s", type=float, default=900)
    parser.add_argument("--kit_args", default=None)
    parser.add_argument("--reuse_baseline", type=Path, nargs="*", default=[])
    args = parser.parse_args(argv)
    initial = ArenaEnvGraphSpec.from_yaml(args.base_spec)
    tasks = initial.task.subtasks
    assert len(tasks) == 1, "Runner currently supports one atomic pick-and-place task"
    target = tasks[0].params["pick_up_object"]
    destination = tasks[0].params["destination_location"]
    policy_hash = hashlib.sha256(args.policy_config.read_bytes()).hexdigest()
    base_file_hash = hashlib.sha256(args.base_spec.read_bytes()).hexdigest()
    initial_hash = spec_digest(initial)
    reused = {}
    for directory in args.reuse_baseline:
        manifest = json.loads((directory / "manifest.json").read_text())
        assert manifest["status"] == "completed", "Only completed baseline manifests may be reused"
        assert manifest["spec_sha256"] == base_file_hash, "Reused baseline spec mismatch"
        assert manifest["policy_config_sha256"] == policy_hash, "Reused baseline policy mismatch"
        assert manifest["hand_body"] == args.hand_body, "Reused hand frame mismatch"
        assert manifest["seed"] not in reused, "Duplicate reused seed"
        reused[manifest["seed"]] = directory.resolve()
    assert not reused or set(reused) == set(args.seeds), "Reuse must cover exactly the requested seeds"
    config = DCRGConfig(
        target_object_id=target,
        policy_id=args.policy_identity,
        seeds=tuple(args.seeds),
        max_xy_displacement=args.max_displacement_m,
        support_xy_bounds=support_bounds(initial),
        max_iterations=args.max_candidates,
        max_candidate_evaluations=args.max_candidates,
        proposal_seed=args.proposal_seed,
        expected_episodes_per_seed=args.episodes_per_seed,
        frozen_context={
            "policy_config_sha256": policy_hash,
            "hand_body": args.hand_body,
            "scenario_contract": args.scenario_contract,
            "remote_port": args.remote_port,
            "kit_args": args.kit_args,
            "remote_diffusion_seed": None,
        },
    )
    driver = get_neo4j_driver(uri=args.neo4j_uri)
    run_dir = args.run_dir.resolve()

    def read_records(directory):
        files = sorted(directory.rglob("episode_results_rank*.jsonl"))
        assert len(files) == 1, "One single-environment result file is required per seed"
        return files[0], [json.loads(line) for line in files[0].read_text().splitlines() if line.strip()]

    def seed_run_id(directory):
        return "dcrg_" + hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest()

    def evaluate(spec, output_dir, seeds):
        assert hashlib.sha256(args.policy_config.read_bytes()).hexdigest() == policy_hash, "Policy config changed"
        spec_path = output_dir / "spec.yaml"
        spec.write_yaml(spec_path)
        episodes, artifacts = [], []
        for seed in seeds:
            directory = reused[seed] if spec_digest(spec) == initial_hash and reused else output_dir / f"seed{seed}"
            if spec_digest(spec) == initial_hash and reused:
                records = read_episode_evidence(directory, seed, args.episodes_per_seed)
            else:
                print(f"[DCRG] Evaluating {spec_digest(spec)[:12]} seed={seed}", flush=True)
                records = run_rollout(
                    spec_path,
                    args.policy_config,
                    directory,
                    seed,
                    args.episodes_per_seed,
                    args.remote_port,
                    args.hand_body,
                    target,
                    destination,
                    timeout_s=args.timeout_s,
                    kit_args=args.kit_args,
                )
            episodes.extend(
                EpisodeEvidence(**{k: row[k] for k in ("seed", "env_id", "episode_in_env", "success", "lifted")})
                for row in records
            )
            artifacts.append(str(directory / "manifest.json"))
        identity = "dcrg_batch_" + hashlib.sha256(";".join(artifacts).encode()).hexdigest()
        return EvaluationEvidence(spec_digest(spec), args.policy_identity, identity, tuple(episodes), tuple(artifacts))

    def load_spec(digest):
        spec = ArenaEnvGraphSpec.from_yaml(run_dir / "specs" / f"{digest}.yaml")
        assert spec_digest(spec) == digest, "Immutable spec mismatch"
        return spec

    def sync_event(event):
        state = json.loads((run_dir / "state.json").read_text())
        if event["kind"] == "evaluation_completed":
            spec = load_spec(event["spec_hash"])
            identity = graph.register_environment_version(spec, target_object_id=target, driver=driver)
            all_records, all_paths = [], []
            for manifest_path in event["evidence"]["artifacts"]:
                directory = Path(manifest_path).parent
                result_path, records = read_records(directory)
                paths = [result_path, directory / "reach.jsonl", Path(manifest_path)]
                run_id = seed_run_id(directory)
                graph.register_evaluation_run(
                    env_name=identity["env_name"],
                    version=identity["version"],
                    run_id=run_id,
                    policy_identity=args.policy_identity,
                    episode_results=records,
                    artifact_paths=paths,
                    driver=driver,
                )
                sync_recurrent_feedback_to_neo4j(
                    run_id,
                    identity["env_name"],
                    str(directory / "reach.jsonl"),
                    driver=driver,
                    env_version=identity["version"],
                    reifier_id=identity["reifier_id"],
                    hand_body_name=args.hand_body,
                    episode_results_path=str(result_path),
                )
                all_records.extend(records)
                all_paths.extend(paths)
            graph.register_evaluation_run(
                env_name=identity["env_name"],
                version=identity["version"],
                run_id=event["evidence"]["run_id"],
                policy_identity=args.policy_identity,
                episode_results=all_records,
                artifact_paths=all_paths,
                driver=driver,
            )
        elif event["kind"] == "proposal_created":
            parent, child = load_spec(event["parent_spec_hash"]), load_spec(event["candidate_spec_hash"])
            parent_id = graph.graph_identity(parent, target_object_id=target)
            child_id = graph.register_environment_version(child, target_object_id=target, driver=driver)
            before = next(o for o in parent.objects if o.id == target).params["initial_pose"]["position_xyz"]
            after = next(o for o in child.objects if o.id == target).params["initial_pose"]["position_xyz"]
            graph.register_proposal(
                proposal_id=event["event_id"],
                parent_env_name=parent_id["env_name"],
                parent_version=parent_id["version"],
                parent_reifier_id=parent_id["reifier_id"],
                child_env_name=child_id["env_name"],
                child_version=child_id["version"],
                parent_eval_id=state["evaluations"][event["parent_spec_hash"]]["run_id"],
                delta_xy=[after[0] - before[0], after[1] - before[1]],
                driver=driver,
            )
        elif event["kind"] == "proposal_decided" and event["decision"] in ("accepted", "rejected"):
            created = next(
                e
                for e in reversed(state["events"])
                if e["kind"] == "proposal_created"
                and e["candidate_spec_hash"] == event["candidate_spec_hash"]
                and e["parent_spec_hash"] == event["parent_spec_hash"]
            )
            graph.record_proposal_decision(
                proposal_id=created["event_id"],
                status=event["decision"],
                reason=event["reason"],
                evaluation_run_id=state["evaluations"][event["candidate_spec_hash"]]["run_id"],
                driver=driver,
            )
        print(f"[DCRG] {event['kind']} recorded", flush=True)

    def propose(spec, evidence, seed):
        identity = graph.graph_identity(spec, target_object_id=target)
        observations = []
        for artifact in evidence.artifacts:
            feedback = fetch_recurrent_feedback_from_neo4j(
                identity["env_name"],
                eval_id=seed_run_id(Path(artifact).parent),
                driver=driver,
                env_version=identity["version"],
                reifier_id=identity["reifier_id"],
            )
            assert feedback is not None, "Expected recorded parent feedback"
            observations.append(feedback)
        # Equal episode budgets make this a matched-seed mean. The exact per-seed
        # graph records remain attached to the parent batch evaluation.
        measured = {axis: sum(o[axis] for o in observations) / len(observations) for axis in ("dx", "dy", "dz")}
        candidate, diagnostics = relax_spec_active_inference(
            spec,
            feedback=measured,
            allowed_mutations=[target],
            allow_anchor_motion=True,
            max_displacement_m=args.max_displacement_m,
            seed=seed,
            temperature=0.0,
        )
        print("[DCRG] " + " ".join(diagnostics), flush=True)
        return candidate if spec_digest(candidate) != spec_digest(spec) else None

    try:
        driver.verify_connectivity()
        result = run_dcrg(initial, run_dir, config=config, evaluate=evaluate, propose=propose, sync_event=sync_event)
        print(json.dumps(asdict(result), default=str, indent=2), flush=True)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
