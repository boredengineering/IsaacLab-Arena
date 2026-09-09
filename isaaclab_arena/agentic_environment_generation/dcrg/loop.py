# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded environment-only DCRG orchestration with injected rollout and proposal boundaries."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal
from collections.abc import Callable

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec


@dataclass(frozen=True)
class EpisodeEvidence:
    """One episode's actual task and sustained-lift predicates, not peak-height proxies."""

    seed: int
    env_id: int
    episode_in_env: int
    success: bool
    lifted: bool
    completed: bool = True


@dataclass(frozen=True)
class EvaluationEvidence:
    """Matched-seed evidence for one immutable spec and exact policy identity."""

    spec_hash: str
    policy_id: str
    run_id: str
    episodes: tuple[EpisodeEvidence, ...]
    artifacts: tuple[str, ...]


@dataclass(frozen=True)
class DCRGConfig:
    """Freeze identity, budgets and a caller-verified target-center support rectangle."""

    target_object_id: str
    policy_id: str
    seeds: tuple[int, ...]
    max_xy_displacement: float
    support_xy_bounds: tuple[float, float, float, float]
    max_iterations: int = 10
    max_candidate_evaluations: int = 10
    proposal_seed: int = 0
    expected_episodes_per_seed: int | None = None
    """When supplied, require this exact completed count at every evaluation seed."""
    frozen_context: dict = field(default_factory=dict)
    """JSON runtime contract absent from the spec: checkpoint digest, hand, physics, inference settings."""


Status = Literal["success", "no_proposal", "exhausted", "failed"]
Evaluate = Callable[[ArenaEnvGraphSpec, Path, tuple[int, ...]], EvaluationEvidence]
Propose = Callable[[ArenaEnvGraphSpec, EvaluationEvidence, int], ArenaEnvGraphSpec | None]
SyncEvent = Callable[[dict], None]


@dataclass(frozen=True)
class DCRGResult:
    """Local run outcome; trial acceptance is not a robustness claim."""

    status: Status
    accepted_spec_hash: str
    iterations: int
    candidate_evaluations: int
    state_path: Path


def spec_digest(spec: ArenaEnvGraphSpec) -> str:
    """Return the SHA-256 of canonical JSON for an environment spec."""
    return hashlib.sha256(_json(spec.to_dict()).encode()).hexdigest()


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(_json(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _sync_directory(path.parent)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def run_dcrg(
    initial_spec: ArenaEnvGraphSpec,
    run_dir: str | Path,
    *,
    config: DCRGConfig,
    evaluate: Evaluate,
    propose: Propose,
    sync_event: SyncEvent | None = None,
) -> DCRGResult:
    """Run or resume matched-seed evaluations without modifying the caller's spec.

    Budget counts exclude the baseline; repeated spec hashes reuse recorded evidence.
    Callback exceptions persist ``failed`` and propagate. An interrupted evaluation
    without an atomic ``evaluations/<hash>/evidence.json`` receipt is indeterminate,
    never automatically repeated. Sync callbacks must be idempotent by event_id and
    verify external writes before returning. Callbacks must enforce their own timeouts.
    Success on the required distinct seeds is a trial milestone, not robustness proof.

    Args:
        initial_spec: Frozen starting environment, not a version-manager latest pointer.
        run_dir: Dedicated durable run directory.
        config: Policy, seed, intervention and budget contract.
        evaluate: Evaluate a private spec copy into the supplied artifact directory.
        propose: Return a candidate private spec or None when no proposal is available.
        sync_event: Optional synchronous lineage writer; must verify its own external writes.

    Returns:
        Local terminal outcome and state location.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"DCRG run directory is locked: {run_dir}") from error
        return _run_locked(
            initial_spec, run_dir, config=config, evaluate=evaluate, propose=propose, sync_event=sync_event
        )


def _run_locked(initial_spec, run_dir, *, config, evaluate, propose, sync_event):
    _validate_config(initial_spec, config)
    config = deepcopy(config)
    initial_spec = initial_spec.model_copy(deep=True)
    run_dir = Path(run_dir)
    (run_dir / "specs").mkdir(parents=True, exist_ok=True)
    digest = spec_digest(initial_spec)
    state_path = run_dir / "state.json"
    contract = json.loads(_json({"initial_spec_hash": digest, "config": asdict(config)}))
    if state_path.exists():
        state = json.loads(state_path.read_text())
        assert state["contract"] == contract, "Resume contract mismatch"
    else:
        state = {
            "schema_version": 1,
            "run_id": uuid.uuid4().hex,
            "contract": contract,
            "status": "running",
            "accepted_spec_hash": digest,
            "iterations": 0,
            "candidate_evaluations": 0,
            "evaluations": {},
            "proposals": [],
            "events": [],
            "started_evaluations": [],
            "pending_candidate": None,
            "pending_proposal": False,
            "terminal_status": None,
            "error": None,
        }
        _atomic_json(state_path, state)

    def save():
        _atomic_json(state_path, state)

    def load_spec(key):
        loaded = ArenaEnvGraphSpec.from_yaml(run_dir / "specs" / f"{key}.yaml")
        assert spec_digest(loaded) == key, "Immutable spec content hash mismatch"
        return loaded

    def store_spec(spec):
        key = spec_digest(spec)
        path = run_dir / "specs" / f"{key}.yaml"
        if path.exists():
            load_spec(key)
        else:
            temporary = path.with_suffix(".tmp")
            spec.write_yaml(temporary)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            _sync_directory(path.parent)
        return key

    def flush_events():
        _flush_events(state, sync_event, save)

    def emit(kind, **payload):
        state["events"].append({
            "event_id": f"{state['run_id']}:{len(state['events'])}",
            "run_id": state["run_id"],
            "kind": kind,
            **payload,
            "sync_status": "pending" if sync_event else "not_requested",
        })
        save()
        flush_events()

    def evaluate_once(spec):
        key = store_spec(spec)
        if key in state["evaluations"]:
            return _evidence_from_dict(state["evaluations"][key])
        output_dir = run_dir / "evaluations" / key
        output_dir.mkdir(parents=True, exist_ok=True)
        receipt = output_dir / "evidence.json"
        if receipt.exists():
            observed = _evidence_from_dict(json.loads(receipt.read_text()))
        else:
            if key in state["started_evaluations"]:
                raise RuntimeError(f"Evaluation {key} is indeterminate; recover evidence.json before resuming")
            state["started_evaluations"].append(key)
            if key != digest:
                state["candidate_evaluations"] += 1
            save()
            private_spec = spec.model_copy(deep=True)
            observed = evaluate(private_spec, output_dir, config.seeds)
            assert spec_digest(private_spec) == key, "Evaluator mutated the frozen rollout spec"
            _validate_evidence(observed, key, config)
            _atomic_json(receipt, asdict(observed))
        _validate_evidence(observed, key, config)
        state["evaluations"][key] = asdict(observed)
        # Evidence and its outbox event share one atomic state write.
        emit("evaluation_completed", spec_hash=key, evidence=asdict(observed))
        return observed

    try:
        store_spec(initial_spec)
        for key, saved in state["evaluations"].items():
            validate_candidate(initial_spec, load_spec(key), config)
            _validate_evidence(_evidence_from_dict(saved), key, config)
        flush_events()
        state["error"] = None
        if state["terminal_status"] is None:
            state["status"] = "running"
            save()
            current = load_spec(state["accepted_spec_hash"])
            observed = evaluate_once(current)
            while True:
                if state["pending_candidate"] is not None:
                    candidate = load_spec(state["pending_candidate"])
                    candidate_evidence = evaluate_once(candidate)
                    matched = _counts(candidate_evidence) == _counts(observed)
                    accepted = matched and _score(candidate_evidence) > _score(observed)
                    decision = {
                        "parent_spec_hash": spec_digest(current),
                        "candidate_spec_hash": spec_digest(candidate),
                        "decision": "accepted" if accepted else "rejected",
                        "reason": "lexicographic task/lift rate" if matched else "completed episode count mismatch",
                    }
                    state["proposals"].append(decision)
                    if accepted:
                        current, observed = candidate, candidate_evidence
                        state["accepted_spec_hash"] = spec_digest(current)
                    state["pending_candidate"] = None
                    emit("proposal_decided", **decision)
                    continue
                if len(config.seeds) >= 2 and all(
                    any(e.seed == seed and e.completed and e.success for e in observed.episodes)
                    for seed in config.seeds
                ):
                    state["terminal_status"] = "success"
                    break
                if not state["pending_proposal"]:
                    if (
                        state["iterations"] >= config.max_iterations
                        or state["candidate_evaluations"] >= config.max_candidate_evaluations
                    ):
                        state["terminal_status"] = "exhausted"
                        break
                    state["iterations"] += 1
                    state["pending_proposal"] = True
                    save()
                candidate = propose(
                    current.model_copy(deep=True), deepcopy(observed), config.proposal_seed + state["iterations"] - 1
                )
                if candidate is None:
                    state["pending_proposal"] = False
                    state["terminal_status"] = "no_proposal"
                    break
                try:
                    validate_candidate(initial_spec, candidate, config)
                except (AssertionError, ValueError, TypeError, KeyError, IndexError, StopIteration) as error:
                    decision = {"parent_spec_hash": spec_digest(current), "decision": "invalid", "reason": str(error)}
                    state["proposals"].append(decision)
                    state["pending_proposal"] = False
                    emit("proposal_decided", **decision)
                    continue
                state["pending_candidate"] = store_spec(candidate)
                state["pending_proposal"] = False
                emit(
                    "proposal_created",
                    parent_spec_hash=spec_digest(current),
                    candidate_spec_hash=state["pending_candidate"],
                )
            state["status"] = state["terminal_status"]
            emit("run_completed", status=state["status"], accepted_spec_hash=state["accepted_spec_hash"])
        state["status"] = state["terminal_status"]
        save()
    except BaseException as error:
        state["status"] = "failed"
        state["error"] = f"{type(error).__name__}: {error}"
        save()
        raise
    return DCRGResult(
        state["status"], state["accepted_spec_hash"], state["iterations"], state["candidate_evaluations"], state_path
    )


def _flush_events(state: dict, sync_event: SyncEvent | None, save: Callable[[], None]) -> None:
    if sync_event is None:
        assert not any(
            e["sync_status"] in ("pending", "failed") for e in state["events"]
        ), "A sync callback is required to resume pending database writes"
        return
    for event in state["events"]:
        if event["sync_status"] == "synced":
            continue
        try:
            sync_event(deepcopy(event))
        except BaseException as error:
            event["sync_status"] = "failed"
            event["error"] = f"{type(error).__name__}: {error}"
            save()
            raise
        event["sync_status"] = "synced"
        event.pop("error", None)
        save()


def _validate_config(initial: ArenaEnvGraphSpec, config: DCRGConfig) -> None:
    assert config.seeds and all(type(seed) is int and seed >= 0 for seed in config.seeds), "Invalid seeds"
    assert len(set(config.seeds)) == len(config.seeds), "Independent seeds must be distinct"
    assert type(config.proposal_seed) is int and config.proposal_seed >= 0, "Invalid proposal seed"
    assert all(
        type(n) is int and n >= 0 for n in (config.max_iterations, config.max_candidate_evaluations)
    ), "Invalid budgets"
    if config.expected_episodes_per_seed is not None:
        assert (
            type(config.expected_episodes_per_seed) is int and config.expected_episodes_per_seed > 0
        ), "Invalid episode count"
    assert config.policy_id and isinstance(config.policy_id, str), "Missing exact policy identity"
    assert math.isfinite(config.max_xy_displacement) and config.max_xy_displacement >= 0, "Invalid displacement bound"
    assert len(config.support_xy_bounds) == 4 and all(
        math.isfinite(v) for v in config.support_xy_bounds
    ), "Invalid support bounds"
    xmin, xmax, ymin, ymax = config.support_xy_bounds
    assert xmin <= xmax and ymin <= ymax, "Invalid support rectangle"
    targets = {task.params.get("pick_up_object") for task in initial.task.subtasks}
    destinations = {task.params.get("destination_location") for task in initial.task.subtasks}
    assert (
        config.target_object_id in targets - destinations
    ), "Target must be the task pick-up object, never a receptacle"
    validate_candidate(initial, initial, config)


def _counts(evidence: EvaluationEvidence) -> dict[int, int]:
    return {
        seed: sum(e.seed == seed and e.completed for e in evidence.episodes)
        for seed in {e.seed for e in evidence.episodes}
    }


def _validate_evidence(evidence: EvaluationEvidence, key: str, config: DCRGConfig) -> None:
    assert isinstance(evidence, EvaluationEvidence), "Evaluator must return EvaluationEvidence"
    assert evidence.spec_hash == key, "Evidence spec hash mismatch"
    assert evidence.policy_id == config.policy_id, "Evidence policy mismatch"
    assert isinstance(evidence.run_id, str) and evidence.run_id, "Missing evaluation run identity"
    assert evidence.artifacts and all(isinstance(p, str) and p for p in evidence.artifacts), "Missing source artifacts"
    identities = set()
    for episode in evidence.episodes:
        assert isinstance(episode, EpisodeEvidence), "Invalid episode record"
        assert all(
            type(v) is int and v >= 0 for v in (episode.seed, episode.env_id, episode.episode_in_env)
        ), "Invalid episode identity"
        assert all(
            type(v) is bool for v in (episode.completed, episode.success, episode.lifted)
        ), "Predicates must be explicit booleans"
        identity = (episode.seed, episode.env_id, episode.episode_in_env)
        assert identity not in identities, "Duplicate episode identity"
        identities.add(identity)
    counts = _counts(evidence)
    assert set(counts) == set(config.seeds), "Evidence seed set mismatch"
    assert all(count > 0 for count in counts.values()), "Every seed requires completed episodes"
    if config.expected_episodes_per_seed is not None:
        assert all(
            count == config.expected_episodes_per_seed for count in counts.values()
        ), "Completed episode count mismatch"


def _evidence_from_dict(data: dict) -> EvaluationEvidence:
    return EvaluationEvidence(
        spec_hash=data["spec_hash"],
        policy_id=data["policy_id"],
        run_id=data["run_id"],
        episodes=tuple(EpisodeEvidence(**e) for e in data["episodes"]),
        artifacts=tuple(data["artifacts"]),
    )


def validate_candidate(initial: ArenaEnvGraphSpec, candidate: ArenaEnvGraphSpec, config: DCRGConfig) -> None:
    """Allow only target initial-pose XY inside the total trust region and support rectangle.

    Args:
        initial: Original environment, never the most recently accepted proposal.
        candidate: Candidate to check without mutation.
        config: Explicit intervention allowlist and caller-verified safe support bounds.
    """
    original = initial.model_dump()
    changed = candidate.model_dump()
    index = next(i for i, obj in enumerate(original["objects"]) if obj["id"] == config.target_object_id)
    xyz = original["objects"][index]["params"]["initial_pose"]["position_xyz"]
    proposed = changed["objects"][index]["params"]["initial_pose"]["position_xyz"]
    assert len(proposed) == 3 and all(math.isfinite(v) for v in proposed), "Nonfinite or malformed target pose"
    assert math.hypot(proposed[0] - xyz[0], proposed[1] - xyz[1]) <= config.max_xy_displacement, "XY trust region"
    xmin, xmax, ymin, ymax = config.support_xy_bounds
    assert xmin <= proposed[0] <= xmax and ymin <= proposed[1] <= ymax, "Target outside support rectangle"
    changed["objects"][index]["params"]["initial_pose"]["position_xyz"] = [xyz[0], xyz[1], proposed[2]]
    assert _json(changed) == _json(original), "Mutation outside target initial_pose.position_xyz XY allowlist"


def _score(evidence: EvaluationEvidence) -> tuple:
    completed = [e for e in evidence.episodes if e.completed]
    return (sum(e.success for e in completed) / len(completed), sum(e.lifted for e in completed) / len(completed))
