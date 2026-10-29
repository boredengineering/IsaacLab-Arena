# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Synthetic unit fixtures exercise orchestration, never simulation or database services."""

import json
import os
import stat
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from isaaclab_arena.agentic_environment_generation.dcrg import loop
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environment_spec.arena_env_graph_types import (
    AssetRegistry,
    ObjectRelationLibraryRegistry,
    TaskRegistry,
)


@pytest.fixture
def spec(monkeypatch):
    # Registry discovery is the only external schema boundary replaced by this fixture.
    monkeypatch.setattr(AssetRegistry, "is_registered", lambda *args: True)
    monkeypatch.setattr(TaskRegistry, "is_registered", lambda *args: True)
    monkeypatch.setattr(ObjectRelationLibraryRegistry, "is_registered", lambda *args: True)
    monkeypatch.setattr(
        ObjectRelationLibraryRegistry,
        "get_object_relation_by_name",
        lambda *args: SimpleNamespace(is_unary=lambda: False),
    )

    def asset(name, xyz):
        return {
            "id": name,
            "registry_name": "synthetic",
            "params": {"initial_pose": {"position_xyz": xyz, "rotation_xyzw": [0, 0, 0, 1]}, "friction": 0.5},
        }

    return ArenaEnvGraphSpec.from_dict({
        "env_name": "synthetic_unit_scene",
        "embodiment": asset("robot", [0, 0, 0]),
        "background": asset("table", [0, 0, 0]),
        "objects": [asset("apple", [0, 0, 0.1]), asset("plate", [0.2, 0, 0.1])],
        "relations": [{"kind": "on", "subject": "apple", "reference": "table"}],
        "task": {
            "composition": "atomic",
            "subtasks": [{
                "kind": "SyntheticTask",
                "params": {"pick_up_object": "apple", "destination_location": "plate", "min_lift_height": 0.02},
            }],
        },
    })


@pytest.fixture
def config():
    return loop.DCRGConfig(
        target_object_id="apple",
        policy_id="checkpoint:synthetic",
        seeds=(11, 22),
        max_xy_displacement=0.1,
        support_xy_bounds=(-0.3, 0.3, -0.3, 0.3),
        max_iterations=2,
        max_candidate_evaluations=2,
    )


def evidence(spec, seeds, successes=(0, 0), lifts=(0, 0), completed=(2, 2)):
    return loop.EvaluationEvidence(
        spec_hash=loop.spec_digest(spec),
        policy_id="checkpoint:synthetic",
        run_id=loop.spec_digest(spec),
        episodes=tuple(
            loop.EpisodeEvidence(seed, 0, episode, episode < success, episode < lift)
            for seed, count, success, lift in zip(seeds, completed, successes, lifts)
            for episode in range(count)
        ),
        artifacts=("synthetic://episode-trace",),
    )


def move(spec, x):
    spec.objects[0].params["initial_pose"]["position_xyz"][0] = x
    return spec


def test_no_proposal_persists_baseline_without_mutating_source(spec, config, tmp_path):
    before = spec.model_dump()
    calls = []

    def evaluate(candidate, output_dir, seeds):
        calls.append((loop.spec_digest(candidate), output_dir, seeds))
        return evidence(candidate, seeds)

    result = loop.run_dcrg(
        spec, tmp_path, config=config, evaluate=evaluate, propose=lambda current, observed, seed: None
    )
    assert result.status == "no_proposal"
    assert result.candidate_evaluations == 0
    assert len(calls) == 1
    assert spec.model_dump() == before
    state = json.loads(result.state_path.read_text())
    assert state["accepted_spec_hash"] == loop.spec_digest(spec)
    assert (tmp_path / "specs" / f"{loop.spec_digest(spec)}.yaml").is_file()
    assert len(state["evaluations"][loop.spec_digest(spec)]["episodes"]) == 4


@pytest.mark.parametrize("successes,expected", [((2, 0), "no_proposal"), ((1, 1), "success")])
def test_success_requires_completed_task_success_at_each_seed(spec, config, tmp_path, successes, expected):
    result = loop.run_dcrg(
        spec,
        tmp_path,
        config=config,
        evaluate=lambda s, out, seeds: evidence(s, seeds, successes=successes),
        propose=lambda *args: None,
    )
    assert result.status == expected


def test_two_iterations_accept_lift_then_reject_task_regression(spec, config, tmp_path):
    before = spec.model_dump()
    feedback = []

    def evaluate(s, out, seeds):
        x = s.objects[0].params["initial_pose"]["position_xyz"][0]
        return evidence(
            s,
            seeds,
            successes=(1, 0) if x < 0.02 else (0, 0),
            lifts=(1, 1) if x == 0.01 else (2, 2) if x == 0.02 else (0, 0),
        )

    def propose(s, observed, seed):
        feedback.append(observed)
        return move(s, 0.01 if len(feedback) == 1 else 0.02)

    result = loop.run_dcrg(spec, tmp_path, config=config, evaluate=evaluate, propose=propose)
    state = json.loads(result.state_path.read_text())
    assert result.status == "exhausted"
    assert result.candidate_evaluations == 2
    assert [p["decision"] for p in state["proposals"]] == ["accepted", "rejected"]
    assert result.accepted_spec_hash == loop.spec_digest(move(spec.model_copy(deep=True), 0.01))
    assert feedback[1].spec_hash == result.accepted_spec_hash
    assert spec.model_dump() == before


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: move(s, 0.101),
        lambda s: move(s, float("nan")),
        lambda s: s.objects[0].params["initial_pose"]["position_xyz"].__setitem__(2, 0.2),
        lambda s: s.objects[1].params["initial_pose"]["position_xyz"].__setitem__(0, 0.1),
        lambda s: s.embodiment.params.update(friction=0.1),
        lambda s: s.background.params["initial_pose"]["position_xyz"].__setitem__(2, 0.3),
        lambda s: s.objects[0].params.update(friction=0.1),
        lambda s: s.objects[0].params["initial_pose"]["rotation_xyzw"].__setitem__(0, 0.3),
        lambda s: s.task.subtasks[0].params.update(min_lift_height=0.001),
        lambda s: s.relations.clear(),
    ],
)
def test_allowlist_rejects_forbidden_changes_before_evaluation(spec, config, tmp_path, mutation):
    calls = []
    before = spec.model_dump()

    def propose(s, observed, seed):
        mutation(s)
        return s

    def evaluate(s, out, seeds):
        calls.append(s)
        return evidence(s, seeds)

    result = loop.run_dcrg(spec, tmp_path, config=config, evaluate=evaluate, propose=propose)
    state = json.loads(result.state_path.read_text())
    assert len(calls) == 1
    assert result.candidate_evaluations == 0
    assert result.status == "exhausted"
    assert all(p["decision"] == "invalid" for p in state["proposals"])
    assert spec.model_dump() == before


def test_bound_is_total_displacement_from_initial_not_each_step(spec, config, tmp_path):
    proposals = iter((0.06, 0.12))
    calls = []

    def evaluate(s, out, seeds):
        calls.append(s)
        return evidence(s, seeds, lifts=(1, 1) if len(calls) > 1 else (0, 0))

    result = loop.run_dcrg(
        spec, tmp_path, config=config, evaluate=evaluate, propose=lambda s, e, seed: move(s, next(proposals))
    )
    assert len(calls) == 2
    assert result.candidate_evaluations == 1


def test_support_rectangle_is_enforced_even_with_larger_trust_region(spec, config, tmp_path):
    config = replace(config, max_xy_displacement=1.0)
    result = loop.run_dcrg(
        spec,
        tmp_path,
        config=config,
        evaluate=lambda s, out, seeds: evidence(s, seeds),
        propose=lambda s, e, seed: move(s, 0.31),
    )
    assert result.candidate_evaluations == 0


def test_resume_terminal_run_never_repeats_evaluation_or_rewrites_spec(spec, config, tmp_path):
    def evaluate(s, out, seeds):
        return evidence(s, seeds)

    first = loop.run_dcrg(spec, tmp_path, config=config, evaluate=evaluate, propose=lambda *args: None)
    spec_path = tmp_path / "specs" / f"{first.accepted_spec_hash}.yaml"
    timestamp = spec_path.stat().st_mtime_ns

    def unexpected(*args):
        pytest.fail("Resume repeated completed work")

    resumed = loop.run_dcrg(spec, tmp_path, config=config, evaluate=unexpected, propose=unexpected)
    assert resumed == first
    assert spec_path.stat().st_mtime_ns == timestamp


@pytest.mark.parametrize("changed", ["spec", "seeds", "policy", "budget"])
def test_resume_refuses_changed_contract(spec, config, tmp_path, changed):
    loop.run_dcrg(
        spec, tmp_path, config=config, evaluate=lambda s, out, seeds: evidence(s, seeds), propose=lambda *args: None
    )
    if changed == "spec":
        spec = move(spec.model_copy(deep=True), 0.01)
    elif changed == "seeds":
        config = replace(config, seeds=(33, 44))
    elif changed == "policy":
        config = replace(config, policy_id="another-checkpoint")
    else:
        config = replace(config, max_iterations=3)
    with pytest.raises(AssertionError, match="contract"):
        loop.run_dcrg(
            spec, tmp_path, config=config, evaluate=lambda *args: pytest.fail("evaluated"), propose=lambda *args: None
        )


def test_sync_failure_is_durable_visible_and_resume_reuses_completed_candidate(spec, config, tmp_path):
    calls = []
    failed = []

    def evaluate(s, out, seeds):
        calls.append(loop.spec_digest(s))
        return evidence(s, seeds, lifts=(1, 1) if len(calls) > 1 else (0, 0))

    def sync(event):
        if event["kind"] == "evaluation_completed" and len(calls) == 2:
            failed.append(event["event_id"])
            raise ConnectionError("synthetic database outage")

    with pytest.raises(ConnectionError, match="database outage"):
        loop.run_dcrg(
            spec, tmp_path, config=config, evaluate=evaluate, propose=lambda s, e, seed: move(s, 0.01), sync_event=sync
        )
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["status"] == "failed"
    assert "database outage" in state["error"]
    assert state["events"][-1]["sync_status"] == "failed"
    synced = []
    result = loop.run_dcrg(
        spec,
        tmp_path,
        config=config,
        evaluate=evaluate,
        propose=lambda *args: None,
        sync_event=lambda e: synced.append(e["event_id"]),
    )
    assert len(calls) == 2
    assert failed[0] in synced
    assert result.accepted_spec_hash == calls[1]
    assert result.status == "no_proposal"


def test_interrupted_evaluation_is_not_blindly_repeated(spec, config, tmp_path):
    calls = []

    def evaluate(*args):
        calls.append(1)
        raise KeyboardInterrupt("synthetic process interruption")

    with pytest.raises(KeyboardInterrupt):
        loop.run_dcrg(spec, tmp_path, config=config, evaluate=evaluate, propose=lambda *args: None)
    with pytest.raises(RuntimeError, match="indeterminate"):
        loop.run_dcrg(spec, tmp_path, config=config, evaluate=evaluate, propose=lambda *args: None)
    assert len(calls) == 1


@pytest.mark.parametrize("iterations,candidates,expected", [(0, 2, 0), (2, 0, 0), (2, 1, 1), (1, 2, 1)])
def test_budgets_bound_candidate_rollouts(spec, config, tmp_path, iterations, candidates, expected):
    config = replace(config, max_iterations=iterations, max_candidate_evaluations=candidates)
    calls = []

    def evaluate(s, out, seeds):
        calls.append(1)
        return evidence(s, seeds)

    result = loop.run_dcrg(
        spec, tmp_path, config=config, evaluate=evaluate, propose=lambda s, e, seed: move(s, 0.01 * (seed + 1))
    )
    assert result.status == "exhausted"
    assert result.candidate_evaluations == expected
    assert len(calls) == expected + 1


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda e: replace(e, spec_hash="wrong"),
        lambda e: replace(e, policy_id="wrong"),
        lambda e: replace(e, run_id=""),
        lambda e: replace(e, artifacts=()),
        lambda e: replace(e, episodes=e.episodes[:2]),
        lambda e: replace(e, episodes=e.episodes + (e.episodes[0],)),
        lambda e: replace(e, episodes=tuple(replace(p, success=1) for p in e.episodes)),
        lambda e: replace(e, episodes=tuple(replace(p, env_id=-1) for p in e.episodes)),
        lambda e: replace(e, episodes=tuple(replace(p, completed=False) for p in e.episodes)),
    ],
)
def test_invalid_evidence_is_failed_not_scored(spec, config, tmp_path, corrupt):
    with pytest.raises(AssertionError):
        loop.run_dcrg(
            spec,
            tmp_path,
            config=config,
            evaluate=lambda s, out, seeds: corrupt(evidence(s, seeds)),
            propose=lambda *args: None,
        )
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["status"] == "failed"
    assert not state["evaluations"]


def test_incomplete_success_does_not_count_as_task_completion(spec, config, tmp_path):
    def evaluate(s, out, seeds):
        observed = evidence(s, seeds)
        return replace(
            observed,
            episodes=observed.episodes
            + (
                loop.EpisodeEvidence(seeds[0], 1, 0, True, True, completed=False),
                loop.EpisodeEvidence(seeds[1], 1, 0, True, True, completed=False),
            ),
        )

    result = loop.run_dcrg(spec, tmp_path, config=config, evaluate=evaluate, propose=lambda *args: None)
    assert result.status == "no_proposal"


def test_candidate_must_match_completed_episode_counts_per_seed(spec, config, tmp_path):
    calls = []

    def evaluate(s, out, seeds):
        calls.append(1)
        return evidence(
            s, seeds, completed=(2, 2) if len(calls) == 1 else (1, 2), lifts=(0, 0) if len(calls) == 1 else (1, 2)
        )

    result = loop.run_dcrg(
        spec,
        tmp_path,
        config=replace(config, max_iterations=1),
        evaluate=evaluate,
        propose=lambda s, e, seed: move(s, 0.01),
    )
    assert result.accepted_spec_hash == loop.spec_digest(spec)
    state = json.loads(result.state_path.read_text())
    assert state["proposals"][0]["decision"] == "rejected"
    assert "count" in state["proposals"][0]["reason"]


@pytest.mark.parametrize(
    "change",
    [
        {"seeds": (11, 11)},
        {"seeds": ()},
        {"seeds": (True, 22)},
        {"max_iterations": -1},
        {"max_candidate_evaluations": -1},
        {"max_xy_displacement": float("nan")},
        {"max_xy_displacement": -0.1},
        {"support_xy_bounds": (1, -1, 0, 1)},
        {"policy_id": ""},
        {"target_object_id": "plate"},
    ],
)
def test_invalid_contract_is_rejected_before_rollout(spec, config, tmp_path, change):
    # The receptacle cannot become the target intervention object.
    with pytest.raises(AssertionError):
        loop.run_dcrg(
            spec,
            tmp_path,
            config=replace(config, **change),
            evaluate=lambda *args: pytest.fail("evaluated invalid contract"),
            propose=lambda *args: None,
        )


def test_single_seed_is_diagnostic_never_independent_seed_success(spec, config, tmp_path):
    result = loop.run_dcrg(
        spec,
        tmp_path,
        config=replace(config, seeds=(11,)),
        evaluate=lambda s, out, seeds: evidence(s, seeds, successes=(2,)),
        propose=lambda *args: None,
    )
    assert result.status == "no_proposal"


def test_run_directory_has_one_writer(spec, config, tmp_path):
    def evaluate(s, out, seeds):
        with pytest.raises(RuntimeError, match="locked"):
            loop.run_dcrg(
                spec,
                tmp_path,
                config=config,
                evaluate=lambda *args: pytest.fail("concurrent evaluation"),
                propose=lambda *args: None,
            )
        return evidence(s, seeds)

    loop.run_dcrg(spec, tmp_path, config=config, evaluate=evaluate, propose=lambda *args: None)


def test_evaluation_receipt_recovers_interrupted_return_without_duplicate(spec, config, tmp_path):
    calls = []

    def evaluate(s, out, seeds):
        calls.append(1)
        (out / "evidence.json").write_text(json.dumps(asdict(evidence(s, seeds))))
        raise KeyboardInterrupt("interrupted after durable receipt")

    with pytest.raises(KeyboardInterrupt):
        loop.run_dcrg(spec, tmp_path, config=config, evaluate=evaluate, propose=lambda *args: None)
    result = loop.run_dcrg(spec, tmp_path, config=config, evaluate=evaluate, propose=lambda *args: None)
    assert result.status == "no_proposal"
    assert len(calls) == 1


def test_frozen_runtime_contract_and_expected_counts(spec, config, tmp_path):
    config = replace(
        config, frozen_context={"permitted_hand": "right", "physics_dt": 0.01}, expected_episodes_per_seed=2
    )
    loop.run_dcrg(
        spec, tmp_path, config=config, evaluate=lambda s, out, seeds: evidence(s, seeds), propose=lambda *args: None
    )
    with pytest.raises(AssertionError, match="contract"):
        loop.run_dcrg(
            spec,
            tmp_path,
            config=replace(config, frozen_context={"permitted_hand": "left"}),
            evaluate=lambda *args: pytest.fail("changed runtime"),
            propose=lambda *args: None,
        )


def test_fewer_than_expected_completed_episodes_is_failed(spec, config, tmp_path):
    with pytest.raises(AssertionError, match="count"):
        loop.run_dcrg(
            spec,
            tmp_path,
            config=replace(config, expected_episodes_per_seed=3),
            evaluate=lambda s, out, seeds: evidence(s, seeds),
            propose=lambda *args: None,
        )


def test_evaluator_cannot_change_its_spec_copy_and_mislabel_evidence(spec, config, tmp_path):
    before = spec.model_dump()

    def evaluate(s, out, seeds):
        observed = evidence(s, seeds)
        move(s, 0.1)
        return observed

    with pytest.raises(AssertionError, match="mutated"):
        loop.run_dcrg(spec, tmp_path, config=config, evaluate=evaluate, propose=lambda *args: None)
    assert spec.model_dump() == before


def test_resume_checks_accepted_spec_content_and_saved_evidence(spec, config, tmp_path):
    def evaluate(s, out, seeds):
        return evidence(
            s, seeds, successes=(1, 1) if s.objects[0].params["initial_pose"]["position_xyz"][0] else (0, 0)
        )

    first = loop.run_dcrg(spec, tmp_path, config=config, evaluate=evaluate, propose=lambda s, e, seed: move(s, 0.01))
    assert first.status == "success"
    saved = tmp_path / "specs" / f"{first.accepted_spec_hash}.yaml"
    move(spec.model_copy(deep=True), 0.02).write_yaml(saved)
    with pytest.raises(AssertionError, match="hash"):
        loop.run_dcrg(spec, tmp_path, config=config, evaluate=evaluate, propose=lambda *args: None)


@pytest.mark.parametrize("expected", [0, -1, True, 1.5])
def test_expected_count_contract_is_positive_integer(spec, config, tmp_path, expected):
    with pytest.raises(AssertionError, match="count"):
        loop.run_dcrg(
            spec,
            tmp_path,
            config=replace(config, expected_episodes_per_seed=expected),
            evaluate=lambda *args: pytest.fail("invalid count evaluated"),
            propose=lambda *args: None,
        )


def test_atomic_state_and_spec_renames_are_directory_synced(spec, config, tmp_path, monkeypatch):
    real_fsync = os.fsync
    directories = []

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directories.append(os.readlink(f"/proc/self/fd/{fd}"))
        real_fsync(fd)

    monkeypatch.setattr(loop.os, "fsync", fsync)
    loop.run_dcrg(
        spec, tmp_path, config=config, evaluate=lambda s, out, seeds: evidence(s, seeds), propose=lambda *args: None
    )
    assert str(tmp_path) in directories
    assert str(tmp_path / "specs") in directories


def test_resume_revalidates_saved_episode_evidence(spec, config, tmp_path):
    result = loop.run_dcrg(
        spec, tmp_path, config=config, evaluate=lambda s, out, seeds: evidence(s, seeds), propose=lambda *args: None
    )
    state = json.loads(result.state_path.read_text())
    state["evaluations"][loop.spec_digest(spec)]["episodes"] = []
    result.state_path.write_text(json.dumps(state))
    with pytest.raises(AssertionError, match="seed"):
        loop.run_dcrg(
            spec, tmp_path, config=config, evaluate=lambda *args: pytest.fail("repeated"), propose=lambda *args: None
        )
