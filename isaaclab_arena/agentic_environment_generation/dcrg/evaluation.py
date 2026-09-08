# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Run isolated policy evaluations and extract honest episode evidence for DCRG."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def build_rollout_command(
    spec_path: Path,
    policy_path: Path,
    output_dir: Path,
    seed: int,
    episodes: int,
    remote_port: int,
    hand_body: str,
    object_name: str,
    destination_name: str,
    kit_args: str | None = None,
    assistance_config_path: Path | None = None,
) -> list[str]:
    """Build an isolated, camera-recorded policy-runner invocation.

    Args:
        spec_path: Immutable candidate specification.
        policy_path: Frozen policy configuration.
        output_dir: Fresh output directory for this seed.
        seed: Simulation and placement seed (not a remote diffusion seed).
        episodes: Number of completed episodes to request.
        remote_port: GR00T server port on localhost.
        hand_body: Explicit diagnostic hand frame.
        object_name: Manipuland scene name.
        destination_name: Destination scene name.
        kit_args: Optional Kit arguments, e.g. a writable portable cache root.
        assistance_config_path: Explicit controller intervention; omitted for the original policy.

    Returns:
        Argument vector for the current Isaac Sim Python interpreter.
    """
    assert episodes > 0, "episodes must be positive"
    assert hand_body, "A pinned hand frame is required"
    runner = Path(__file__).resolve().parents[2] / "evaluation" / "policy_runner.py"
    command = [
        sys.executable,
        str(runner),
        "--headless",
        "--enable_cameras",
        "--policy_type",
        "isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy",
        "--policy_config_yaml_path",
        str(policy_path.resolve()),
        "--remote_host",
        "127.0.0.1",
        "--remote_port",
        str(remote_port),
        "--num_envs",
        "1",
        "--num_episodes",
        str(episodes),
        "--seed",
        str(seed),
        "--placement_seed",
        str(seed),
        "--env_graph_spec_yaml",
        str(spec_path.resolve()),
        "--trace_reach",
        str(output_dir.resolve() / "reach.jsonl"),
        "--trace_reach_object",
        object_name,
        "--trace_reach_destination",
        destination_name,
        "--trace_reach_hand_body",
        hand_body,
        "--record_camera_video",
        "--output_base_dir",
        str(output_dir.resolve()),
    ]
    if kit_args:
        command.extend(["--kit_args", kit_args])
    if assistance_config_path is not None:
        command[command.index("--policy_type") + 1] = (
            "isaaclab_arena_gr00t.policy.gr00t_assisted_policy.Gr00tAssistedPolicy"
        )
        command.extend([
            "--assistance_config_path",
            str(assistance_config_path.resolve()),
            "--assistance_trace_path",
            str(output_dir.resolve() / "assistance.jsonl"),
        ])
    return command


def read_episode_evidence(output_dir: Path, seed: int, expected_episodes: int) -> list[dict[str, Any]]:
    """Read completed episodes without interpreting surrogate progress scores as success.

    Args:
        output_dir: Directory containing this evaluation's episode result files.
        seed: Required simulation seed.
        expected_episodes: Exact number of completed episodes required.

    Returns:
        Episode records with explicit task-success and sustained-lift booleans.
    """
    assert expected_episodes > 0, "expected_episodes must be positive"
    evidence = []
    seen = set()
    for path in sorted(output_dir.rglob("episode_results_rank*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            assert row["seed"] == seed, f"Unexpected seed in {path}"
            assert type(row["success"]) is bool, f"Non-boolean success in {path}"
            assert row["episode_length"] > 0, f"Empty episode in {path}"
            key = (row["seed"], row["env_id"], row["episode_in_env"])
            assert key not in seen, f"Duplicate episode {key}"
            seen.add(key)
            events = row.get("progress", {}).get("events", [])
            lifted = any(
                event.get("predicate_name", "").startswith("object_lifted_above_resting_min(") for event in events
            )
            placed = any(event.get("predicate_name", "").startswith("object_on_destination(") for event in events)
            assert not row["success"] or (lifted and placed), "Success lacks sustained lift and placement evidence"
            evidence.append({
                "seed": row["seed"],
                "env_id": row["env_id"],
                "episode_in_env": row["episode_in_env"],
                "success": row["success"],
                "lifted": lifted,
                "source_path": str(path.resolve()),
            })
    assert len(evidence) == expected_episodes, f"Expected {expected_episodes} episodes, found {len(evidence)}"
    return evidence


def run_rollout(
    spec_path: Path,
    policy_path: Path,
    output_dir: Path,
    seed: int,
    episodes: int,
    remote_port: int,
    hand_body: str,
    object_name: str,
    destination_name: str,
    timeout_s: float = 900.0,
    kit_args: str | None = None,
    assistance_config_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Execute one bounded rollout, recording failures rather than treating them as episodes.

    Args:
        spec_path: Immutable candidate specification.
        policy_path: Frozen policy configuration.
        output_dir: Fresh artifact directory; existing directories are rejected.
        seed: Simulation and placement seed.
        episodes: Exact completed-episode budget.
        remote_port: Local policy server port.
        hand_body: Pinned diagnostic body.
        object_name: Manipuland name.
        destination_name: Destination name.
        timeout_s: Maximum wall-clock duration, including simulator startup.
        kit_args: Optional Kit settings forwarded unchanged.
        assistance_config_path: Optional immutable controller configuration for assisted trials.

    Returns:
        Validated completed-episode evidence.
    """
    assert timeout_s > 0, "timeout_s must be positive"
    command = build_rollout_command(
        spec_path=spec_path,
        policy_path=policy_path,
        output_dir=output_dir,
        seed=seed,
        episodes=episodes,
        remote_port=remote_port,
        hand_body=hand_body,
        object_name=object_name,
        destination_name=destination_name,
        kit_args=kit_args,
        assistance_config_path=assistance_config_path,
    )
    manifest = {
        "status": "running",
        "command": command,
        "spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "policy_config_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "seed": seed,
        "remote_diffusion_seed": None,
        "expected_episodes": episodes,
        "hand_body": hand_body,
    }
    if assistance_config_path is not None:
        manifest.update(
            assistance_config_path=str(assistance_config_path.resolve()),
            assistance_config_sha256=hashlib.sha256(assistance_config_path.read_bytes()).hexdigest(),
        )
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    try:
        with (output_dir / "process.log").open("w") as log:
            result = subprocess.run(
                command,
                cwd=Path(__file__).resolve().parents[3],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout_s,
                check=False,
            )
        manifest["returncode"] = result.returncode
        assert result.returncode == 0, f"Process exited {result.returncode}"
        evidence = read_episode_evidence(output_dir, seed=seed, expected_episodes=episodes)
    except Exception as exc:
        manifest.update(status="failed", error=str(exc))
        manifest_path.write_text(json.dumps(manifest, indent=2))
        raise RuntimeError(f"Rollout failed; inspect {output_dir / 'process.log'}: {exc}") from exc
    manifest.update(status="completed", episodes=evidence)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return evidence
