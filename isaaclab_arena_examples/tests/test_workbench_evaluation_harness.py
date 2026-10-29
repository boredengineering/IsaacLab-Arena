# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Production harness with synthetic simulator/serialization seams, never GPU or graph execution."""

import builtins
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from isaaclab_arena.evaluation import policy_runner, telemetry_to_prov  # noqa: F401


def load_source(name) -> Any:
    """Execute the complete production module in an isolated test namespace."""
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "synthetic_harness_" + name, root / "isaaclab_arena/evaluation" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def telemetry(monkeypatch):
    # This approved immutable image has no rdflib. Mock only serialization;
    # do not manufacture a TTL artifact or claim real RDF serialization evidence.
    rdf = ModuleType("rdflib")
    for name in ("RDF", "XSD", "Literal", "Namespace", "Graph"):
        setattr(rdf, name, MagicMock(name=name))
    monkeypatch.setitem(sys.modules, "rdflib", rdf)
    return load_source("telemetry_to_prov")


def test_local_telemetry_serializes_without_importing_graph_sync(tmp_path, monkeypatch, telemetry):
    original_import = builtins.__import__
    forbidden_imports = []

    def guarded_import(name, *args, **kwargs):
        if name.endswith("lpg_neo4j_sync"):
            forbidden_imports.append(name)
            raise AssertionError("Graph sync must not be imported for local telemetry")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    output = telemetry.record_eval_telemetry_to_prov(
        tmp_path, "frozen_environment", {"num_episodes": 1}, "synthetic_policy", publish_to_graph=False
    )
    assert forbidden_imports == []
    assert output == tmp_path / "eval_telemetry.ttl"
    telemetry.rdflib.Graph.return_value.serialize.assert_called_once_with(destination=str(output), format="turtle")


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Load the complete real runner with explicit synthetic simulator boundaries."""
    import numpy as np

    dependencies = {
        "warp": (),
        "isaaclab_arena.assets.registries": ("PolicyRegistry",),
        "isaaclab_arena.cli.isaaclab_arena_cli": ("get_isaaclab_arena_cli_parser",),
        "isaaclab_arena.evaluation.policy_runner_cli": (
            "add_policy_cli_args",
            "add_policy_runner_arguments",
            "build_policy_from_cli",
        ),
        "isaaclab_arena.utils.isaaclab_utils.simulation_app": ("SimulationAppContext",),
        "isaaclab_arena.video.video_recording": ("VideoRecordingCfg", "timestamped_run_dir", "wrap_env_for_video"),
        "isaaclab_arena.visualization.report": ("build_report", "serve_until_ctrl_c"),
        "isaaclab_arena_environments.cli": ("get_arena_builder_from_cli", "get_isaaclab_arena_environments_cli_parser"),
    }
    for name, attributes in dependencies.items():
        module = ModuleType(name)
        for attribute in attributes:
            setattr(module, attribute, MagicMock(name=attribute))
        monkeypatch.setitem(sys.modules, name, module)
    runner = load_source("policy_runner")
    events = []
    results = []
    args = SimpleNamespace(
        device="cpu",
        list_variations=False,
        policy_type="synthetic_policy",
        record_camera_video=False,
        record_viewport_video=False,
        output_base_dir=str(tmp_path),
        num_steps=20,
        num_episodes=None,
        remote_kill_on_exit=False,
        serve_evaluation_report=False,
        evaluation_report_port=8000,
        example_environment="legacy_environment",
        env_graph_spec_yaml="generated_envs/example/v2/env_graph.yaml",
    )
    state = SimpleNamespace(
        runner=runner,
        args=args,
        events=events,
        results=results,
        output=tmp_path,
        policy_length=7,
        shutdown=None,
        fail_at=None,
        rank=0,
        missing_report=False,
        metrics=SimpleNamespace(
            num_episodes=2,
            metric_data_entries={
                "success_rate": SimpleNamespace(metric_value=np.float32(0.5)),
                "episode_lengths": SimpleNamespace(metric_value=np.array([3, 4])),
            },
        ),
    )

    def event(name):
        events.append(name)
        if state.fail_at == name:
            raise RuntimeError("private synthetic failure")

    class SyntheticContext:
        def __init__(self, parsed):
            assert parsed is args

        def __enter__(self):
            event("enter")

        def __exit__(self, *exc):
            event("shutdown")
            if state.shutdown is not None:
                raise SystemExit(state.shutdown)

    parser = SimpleNamespace(parse_known_args=lambda: (args, []))
    runner.get_isaaclab_arena_cli_parser = lambda: parser
    runner.get_isaaclab_arena_environments_cli_parser = lambda parser: parser
    runner.add_policy_cli_args = lambda parser, cls: parser
    runner.get_local_rank = lambda: state.rank
    runner.get_world_size = lambda: 1
    runner.SimulationAppContext = SyntheticContext
    runner.get_policy_cls = lambda name: object
    runner.timestamped_run_dir = lambda base: str(tmp_path)
    runner.VideoRecordingCfg = lambda **kwargs: SimpleNamespace(render_mode=None)
    env = MagicMock(name="synthetic_environment")
    env.close.side_effect = lambda: event("env_close")
    runner.make_recorded_environment = lambda *args: env
    runner.wrap_env_for_video = lambda env, *args: env
    policy = SimpleNamespace(
        has_length=lambda: state.policy_length is not None,
        length=lambda: state.policy_length,
        is_remote=True,
        shutdown_remote=lambda **kw: events.append(("remote_shutdown", kw)),
    )
    runner.build_policy_from_cli = lambda cls, args: policy

    def rollout(env_arg, policy_arg, steps, episodes, **kwargs):
        assert env_arg is env and policy_arg is policy
        state.effective_budget = (steps, episodes)
        state.rollout_options = kwargs
        event("rollout")
        return state.metrics

    def report(output):
        assert output == str(tmp_path)
        event("report")
        path = tmp_path / "index.html"
        if not state.missing_report:
            path.write_text("<html>Synthetic report fixture, not simulator evidence</html>")
        return path

    def record(**kwargs):
        state.telemetry_args = kwargs
        event("telemetry")

    module = ModuleType("isaaclab_arena.evaluation.telemetry_to_prov")
    setattr(module, "record_eval_telemetry_to_prov", record)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    runner.rollout_policy = rollout
    runner.build_report = report
    runner.serve_until_ctrl_c = lambda *args: event("serve")

    def completed(result):
        event("completed")
        results.append(result)

    state.completed = completed
    state.env = env
    original_import = builtins.__import__
    state.lineage_imports = []
    state.lineage = None

    def guarded_import(name, *args, **kwargs):
        if name.endswith("version_manager"):
            state.lineage_imports.append(name)
            if state.lineage is not None:
                return state.lineage
            raise AssertionError("private synthetic lineage import denied")
        if name.endswith("lpg_neo4j_sync"):
            pytest.fail("Graph writer must never be reached by harness tests")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    return state


def test_completion_precedes_terminating_shutdown_with_effective_budget(harness):
    h = harness
    h.shutdown = 0
    with pytest.raises(SystemExit) as exited:
        h.runner.main(
            on_evaluation_completed=h.completed,
            publish_to_graph=False,
            telemetry_env_name="frozen_environment",
            update_lineage=False,
        )
    assert exited.value.code == 0
    assert h.events == [
        "enter",
        "rollout",
        ("remote_shutdown", {"kill_server": False}),
        "env_close",
        "telemetry",
        "report",
        "completed",
        "shutdown",
    ]
    assert h.lineage_imports == []
    assert h.results == [{
        "output_dir": str(h.output),
        "report_path": str(h.output / "index.html"),
        "metrics": {"num_episodes": 2, "success_rate": 0.5, "episode_lengths": [3, 4]},
        "num_steps": 7,
        "num_episodes": None,
        "warnings": [],
    }]
    assert h.effective_budget == (7, None)
    assert h.telemetry_args == {
        "output_dir": str(h.output),
        "env_name": "frozen_environment",
        "metrics": h.results[0]["metrics"],
        "policy_name": "synthetic_policy",
        "publish_to_graph": False,
    }


def test_missing_report_cannot_emit_completion(harness):
    harness.missing_report = True
    with pytest.raises(AssertionError, match="report"):
        harness.runner.main(on_evaluation_completed=harness.completed, publish_to_graph=False, update_lineage=False)
    assert harness.results == []


@pytest.mark.parametrize("failure", ["enter", "rollout", "env_close", "report"])
def test_failure_before_report_cannot_emit_completion(harness, failure):
    harness.fail_at = failure
    with pytest.raises(RuntimeError, match="private synthetic failure"):
        harness.runner.main(on_evaluation_completed=harness.completed, publish_to_graph=False, update_lineage=False)
    assert harness.results == []
    assert "completed" not in harness.events


@pytest.mark.parametrize("shutdown", [None, 0, 1, "error"])
def test_completion_is_not_a_shutdown_success_claim(harness, shutdown):
    h = harness
    if shutdown == "error":
        h.fail_at = "shutdown"
    else:
        h.shutdown = shutdown

    def run():
        return h.runner.main(on_evaluation_completed=h.completed, publish_to_graph=False, update_lineage=False)

    if shutdown == "error":
        with pytest.raises(RuntimeError, match="private synthetic failure"):
            run()
    elif shutdown is not None:
        with pytest.raises(SystemExit) as exited:
            run()
        assert exited.value.code == shutdown
    else:
        assert run() is None
    assert len(h.results) == 1
    assert h.events[-2:] == ["completed", "shutdown"]


@pytest.mark.parametrize("steps,episodes", [(13, None), (None, 3)])
def test_effective_cli_budget_and_absent_metrics_are_not_fabricated(harness, steps, episodes):
    h = harness
    h.policy_length = None
    h.args.num_steps = steps
    h.args.num_episodes = episodes
    h.metrics = None
    h.runner.main(on_evaluation_completed=h.completed, publish_to_graph=False, update_lineage=False)
    assert h.effective_budget == (steps, episodes)
    assert (h.results[0]["num_steps"], h.results[0]["num_episodes"]) == (steps, episodes)
    assert h.results[0]["metrics"] is None
    assert h.results[0]["warnings"] == []
    assert "telemetry" not in h.events
    assert h.lineage_imports == []
    assert h.rollout_options == {
        "check_settling": True,
        "settle_steps": 12,
        "lin_vel_thresh": 0.1,
        "ang_vel_thresh": 1.0,
        "trace_reach": None,
        "trace_reach_object": None,
        "trace_reach_destination": None,
        "trace_reach_hand_body": None,
    }


@pytest.mark.parametrize(
    "failure,warning", [("telemetry", "telemetry_recording_failed"), ("lineage", "lineage_update_failed")]
)
def test_caught_optional_failures_only_expose_static_warning_codes(harness, failure, warning):
    h = harness
    if failure == "telemetry":
        h.fail_at = "telemetry"
    h.runner.main(on_evaluation_completed=h.completed, publish_to_graph=False)
    assert h.results[0]["warnings"] == [warning]
    assert "private synthetic" not in json.dumps(h.results)
    assert h.telemetry_args["env_name"] == "legacy_environment"
    assert bool(h.lineage_imports) == (failure == "lineage")


def test_legacy_no_argument_entry_keeps_publication_lineage_and_serving(harness):
    h = harness
    h.args.serve_evaluation_report = True
    h.lineage = ModuleType("synthetic_version_manager")
    manager = MagicMock(name="synthetic_version_manager")
    setattr(h.lineage, "EnvironmentVersionManager", manager)
    assert h.runner.main() is None
    assert h.telemetry_args["publish_to_graph"] is True
    assert h.telemetry_args["env_name"] == "legacy_environment"
    assert len(h.lineage_imports) == 1
    manager.assert_called_once_with("example")
    manager.return_value.record_evaluation_metrics.assert_called_once_with(
        version=2, metrics=h.telemetry_args["metrics"], eval_output_dir=str(h.output)
    )
    assert h.results == []
    assert h.events[-3:] == ["report", "serve", "shutdown"]


@pytest.mark.parametrize("explicit", [None, "frozen_identity", ""])
def test_telemetry_identity_uses_fallback_only_when_not_provided(harness, explicit):
    h = harness
    h.runner.main(publish_to_graph=False, telemetry_env_name=explicit, update_lineage=False)
    assert h.telemetry_args["env_name"] == ("legacy_environment" if explicit is None else explicit)


def test_nonzero_rank_does_not_report_or_complete(harness):
    harness.rank = 1
    harness.runner.main(on_evaluation_completed=harness.completed, publish_to_graph=False, update_lineage=False)
    assert harness.results == []
    assert "report" not in harness.events
    assert "telemetry" not in harness.events
    assert harness.lineage_imports == []


def test_callback_failure_propagates_and_does_not_serve(harness):
    harness.fail_at = "completed"
    harness.args.serve_evaluation_report = True
    with pytest.raises(RuntimeError, match="private synthetic failure"):
        harness.runner.main(on_evaluation_completed=harness.completed, publish_to_graph=False, update_lineage=False)
    assert harness.results == []
    assert "serve" not in harness.events
    assert harness.events[-1] == "shutdown"


def test_telemetry_default_publication_reaches_only_a_fail_spy(tmp_path, monkeypatch, telemetry, caplog):
    original_import = builtins.__import__
    imports = []
    fake_sync = ModuleType("synthetic_graph_sync")
    writer = MagicMock(side_effect=RuntimeError("synthetic graph writer denied"))
    setattr(fake_sync, "sync_eval_telemetry_to_neo4j", writer)

    def guarded_import(name, *args, **kwargs):
        if name.endswith("lpg_neo4j_sync"):
            imports.append(name)
            return fake_sync
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    output = telemetry.record_eval_telemetry_to_prov(tmp_path, "synthetic_environment", {})
    assert len(imports) == 1
    writer.assert_called_once_with(str(output))
    assert "graph was not updated" in caplog.text
    telemetry.rdflib.Graph.return_value.serialize.assert_called_once_with(destination=str(output), format="turtle")


def rollout_fixture():
    import torch

    events = []
    base = SimpleNamespace(cfg=SimpleNamespace(metrics=None), get_language_instruction=lambda: "frozen task")
    env = SimpleNamespace(unwrapped=base)
    env.reset = lambda: (events.append("reset") or "reset-observation", {})
    env.step = lambda action: (
        events.append("step") or "autoreset-observation",
        None,
        torch.tensor([True]),
        torch.tensor([False]),
        {},
    )
    policy = SimpleNamespace(
        reset=lambda **kwargs: events.append(("policy-reset", kwargs)),
        set_task_description=lambda text: events.append(("instruction", text)),
        get_action=lambda env, obs: events.append(("action", obs)),
    )
    return env, policy, events


@pytest.mark.parametrize("truncated", [False, True])
def test_initialized_policy_cohort_skips_hidden_reset_and_rechecks_autoreset(harness, truncated):
    runner = load_source("policy_runner")
    env, policy, events = rollout_fixture()
    if truncated:
        original_step = env.step

        def step(action):
            obs, reward, terminated, timeout, info = original_step(action)
            return obs, reward, timeout, terminated, info

        env.step = step

    def prerequisite(env_arg, obs, env_ids):
        assert env_arg is env
        events.append(("prerequisite", obs, None if env_ids is None else env_ids.tolist()))
        return "checked-" + obs

    runner.rollout_policy(
        env,
        policy,
        2,
        None,
        check_settling=False,
        initialized_observation="captured-observation",
        post_reset=prerequisite,
    )
    assert "reset" not in events
    assert [(e[0], e[1]) for e in events if isinstance(e, tuple) and e[0] == "action"] == [
        ("action", "checked-captured-observation"),
        ("action", "checked-autoreset-observation"),
    ]
    assert [e for e in events if isinstance(e, tuple) and e[0] == "prerequisite"] == [
        ("prerequisite", "captured-observation", None),
        ("prerequisite", "autoreset-observation", [0]),
    ]


@pytest.mark.parametrize("initialized", [False, True])
def test_policy_prerequisite_failure_blocks_actions_and_preserves_legacy_reset(harness, initialized):
    runner = load_source("policy_runner")
    env, policy, events = rollout_fixture()

    def prerequisite(*args):
        raise ValueError("unsettled cohort")

    kwargs = {"initialized_observation": "captured"} if initialized else {}
    with pytest.raises(RuntimeError, match="unsettled cohort"):
        runner.rollout_policy(env, policy, 2, None, check_settling=False, post_reset=prerequisite, **kwargs)
    assert ("reset" in events) is not initialized
    assert not any(isinstance(e, tuple) and e[0] == "action" for e in events)


def test_legacy_rollout_still_resets_without_managed_hooks(harness):
    runner = load_source("policy_runner")
    env, policy, events = rollout_fixture()
    runner.rollout_policy(env, policy, 1, None, check_settling=False)
    assert events[0] == "reset"
    assert ("action", "reset-observation") in events


def test_managed_runner_step_and_episode_ceilings_and_effect_guard(harness):
    runner = load_source("policy_runner")
    env, policy, events = rollout_fixture()
    runner.rollout_policy(
        env, policy, 10, None, check_settling=False, episode_limit=2, before_action=lambda: events.append("guard")
    )
    assert events.count("step") == 2 and events.count("guard") == 2
    env, policy, events = rollout_fixture()

    def expired():
        raise ValueError("policy deadline exceeded")

    with pytest.raises(RuntimeError, match="deadline"):
        runner.rollout_policy(env, policy, 2, None, check_settling=False, before_action=expired)
    assert "step" not in events


@pytest.mark.parametrize("budget", [0, -1, True])
def test_managed_runner_rejects_invalid_episode_ceiling_before_reset(harness, budget):
    runner = load_source("policy_runner")
    env, policy, events = rollout_fixture()
    with pytest.raises((ValueError, AssertionError)):
        runner.rollout_policy(env, policy, 2, None, check_settling=False, episode_limit=budget)
    assert events == []


def managed_fixture(harness):
    from isaaclab_arena.agentic_environment_generation.workflow import policy_evaluation as pe
    from isaaclab_arena.tests.test_environment_workflow_evidence import policy_binding

    runner = load_source("policy_runner")
    env, policy, events = rollout_fixture()
    env.unwrapped.num_envs = 1
    frozen = policy_binding(instruction="frozen task")
    task = SimpleNamespace(
        get_task_description=lambda: "frozen task",
        get_termination_cfg=lambda: events.append("task-terminations") or "terminations",
        get_metrics=lambda: events.append("task-metrics") or ["task-success"],
    )
    prepared = []

    def verify(binding, env_arg, policy_arg, task_arg, terminations, metrics):
        assert env_arg is env and policy_arg is policy and task_arg is task
        assert terminations == "terminations" and metrics == ["task-success"]
        events.append("verify-runtime")
        return binding

    def prepare(binding, env_arg, observation, env_ids, remaining_steps):
        reset_id = f"reset-{len(prepared) + 1}"
        prepared.append(reset_id)
        events.append("prepare-cohort")
        assert remaining_steps >= 2
        return observation, pe.PolicyCohortReadiness(
            binding_digest=binding.digest(),
            reset_id=reset_id,
            established=True,
            terminated=False,
            truncated=False,
            steps=2,
        )

    def episodes(binding, env_arg):
        return tuple(
            pe.PolicyEpisode(
                binding_digest=binding.digest(),
                episode_id=f"episode-{i}",
                reset_id=reset,
                seed=binding.seed,
                success=True,
            )
            for i, reset in enumerate(prepared)
        )

    return (
        pe,
        frozen,
        dict(
            env=env,
            policy=policy,
            task=task,
            verify_runtime=verify,
            prepare_cohort=prepare,
            read_episodes=episodes,
            clock=lambda: 100.0,
            rollout=runner.rollout_policy,
            initialized_observation="captured",
        ),
        events,
    )


def test_managed_bridge_reuses_runner_and_task_contract_without_hidden_reset(harness):
    pe, frozen, options, events = managed_fixture(harness)
    result = pe.run_managed_policy(frozen, **options)
    assert result.aggregate.outcome == "passed"
    assert result.aggregate.completed == 2 and result.prerequisite_steps == 4
    assert "reset" not in events and events.count("step") == 2
    assert events.count("prepare-cohort") == 2
    assert "task-terminations" in events and "task-metrics" in events
    assert len(result.episodes) == 2


def test_arena_episode_jsonl_reader_preserves_real_denominator_and_a2_identity(harness):
    import hashlib

    from isaaclab_arena.agentic_environment_generation.workflow.policy_episode_records import decode_episode_records

    pe, frozen, _, _ = managed_fixture(harness)
    frozen = frozen.model_copy(
        update={
            "instruction": (
                "Grasp the yellow banana from the right side of the table and set it onto the white ceramic plate on"
                " the left."
            ),
            "embodiment_id": "droid_abs_joint_pos",
        }
    )
    rows = [
        dict(
            job_name="trial-a2",
            env_id=0,
            episode_in_env=i,
            seed=frozen.seed,
            success=success,
            episode_length=4,
            language_instruction=frozen.instruction,
            timestamp="synthetic-timestamp",
        )
        for i, success in enumerate((True, False), start=3)
    ]
    raw = ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
    checked = decode_episode_records(
        frozen, raw, job_name="trial-a2", first_episode_index=3, reset_ids=("reset-1", "reset-2")
    )
    assert checked.raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert checked.byte_count == len(raw)
    assert [e.success for e in checked.episodes] == [True, False]
    aggregate = pe.aggregate_policy_episodes(frozen, checked.episodes)
    assert (aggregate.completed, aggregate.successes, aggregate.outcome) == (2, 1, "failed")
    empty = decode_episode_records(frozen, b"", job_name="trial-a2", first_episode_index=3, reset_ids=("reset-1",))
    assert pe.aggregate_policy_episodes(frozen, empty.episodes).success_rate is None


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate-field",
        "nonfinite",
        "initial-reset",
        "repeated-reset",
        "seed",
        "index",
        "job",
        "success",
        "empty-line",
    ],
)
def test_arena_episode_jsonl_rejects_ambiguous_or_foreign_records(harness, defect):
    from isaaclab_arena.agentic_environment_generation.workflow.policy_episode_records import decode_episode_records

    _, frozen, _, _ = managed_fixture(harness)
    row = dict(
        job_name="trial",
        env_id=0,
        episode_in_env=0,
        seed=frozen.seed,
        success=True,
        episode_length=4,
        language_instruction=frozen.instruction,
    )
    resets = ("reset-1",)
    if defect in ("seed", "index", "job", "success"):
        key, value = {
            "seed": ("seed", 8),
            "index": ("episode_in_env", 1),
            "job": ("job_name", "other"),
            "success": ("success", 1),
        }[defect]
        row[key] = value
    raw = json.dumps(row).encode() + b"\n"
    if defect == "duplicate-field":
        raw = raw.replace(b'"success": true', b'"success": false, "success": true')
    elif defect == "nonfinite":
        raw = raw.replace(b'"episode_length": 4', b'"episode_length": 4, "diagnostic": NaN')
    elif defect == "initial-reset":
        resets = ("foreign-reset",)
    elif defect == "repeated-reset":
        resets = ("reset-1", "reset-1")
    elif defect == "empty-line":
        raw += b"\n"
    with pytest.raises(ValueError):
        decode_episode_records(frozen, raw, job_name="trial", first_episode_index=0, reset_ids=resets)


@pytest.mark.parametrize("slow_boundary", ["inference", "runtime-verification"])
def test_managed_deadline_is_rechecked_after_blocking_calls_before_next_effect(harness, slow_boundary):
    pe, frozen, options, events = managed_fixture(harness)
    now = [100.0]
    options["clock"] = lambda: now[0]
    if slow_boundary == "inference":
        action = options["policy"].get_action

        def slow_action(*args):
            value = action(*args)
            now[0] = frozen.deadline_unix
            return value

        options["policy"].get_action = slow_action
    else:
        verify = options["verify_runtime"]
        calls = []

        def slow_verification(*args):
            value = verify(*args)
            calls.append(True)
            if len(calls) == 4:  # The final guard immediately before inference.
                now[0] = frozen.deadline_unix
            return value

        options["verify_runtime"] = slow_verification
    with pytest.raises((ValueError, RuntimeError), match="deadline"):
        pe.run_managed_policy(frozen, **options)
    assert "step" not in events
    if slow_boundary == "runtime-verification":
        assert not any(isinstance(event, tuple) and event[0] == "action" for event in events)


@pytest.mark.parametrize(
    "defect", ["unsupported", "pin-drift", "expired", "nan-clock", "task", "instruction", "vector"]
)
def test_managed_bridge_rejects_unverified_runtime_before_effects(harness, defect):
    pe, frozen, options, events = managed_fixture(harness)
    if defect == "unsupported":
        options["verify_runtime"] = lambda *args: None
    elif defect == "pin-drift":
        options["verify_runtime"] = lambda *args: frozen.model_copy(update={"transport_digest": "9" * 64})
    elif defect in ("expired", "nan-clock"):
        options["clock"] = lambda: 1001.0 if defect == "expired" else float("nan")
    elif defect == "task":
        options["task"].get_task_description = lambda: "wrong task"
    elif defect == "instruction":
        options["env"].unwrapped.get_language_instruction = lambda: "wrong task"
    else:
        options["env"].unwrapped.num_envs = 2
    with pytest.raises((ValueError, RuntimeError)):
        pe.run_managed_policy(frozen, **options)
    assert "step" not in events and "prepare-cohort" not in events


@pytest.mark.parametrize(
    "defect", ["unsettled", "terminated", "truncated", "over-budget", "binding", "reset", "forged"]
)
def test_managed_bridge_requires_current_bounded_prerequisites(harness, defect):
    pe, frozen, options, events = managed_fixture(harness)
    original = options["prepare_cohort"]

    def prepare(*args):
        observation, readiness = original(*args)
        update = {
            "unsettled": {"established": False},
            "terminated": {"terminated": True},
            "truncated": {"truncated": True},
            "over-budget": {"steps": 7},
            "binding": {"binding_digest": "f" * 64},
            "reset": {"reset_id": "stale"},
            "forged": {"established": 1},
        }[defect]
        return observation, readiness.model_copy(update=update)

    options["prepare_cohort"] = prepare
    with pytest.raises((ValueError, RuntimeError)):
        pe.run_managed_policy(frozen, **options)
    assert "step" not in events


@pytest.mark.parametrize("defect", ["repeated-reset", "second-unsettled", "deadline-after-settle", "runtime-drift"])
def test_managed_bridge_rechecks_every_new_cohort_and_action(harness, defect):
    pe, frozen, options, events = managed_fixture(harness)
    original = options["prepare_cohort"]

    def prepare(*args):
        observation, readiness = original(*args)
        if events.count("prepare-cohort") == 2:
            if defect == "repeated-reset":
                readiness = readiness.model_copy(update={"reset_id": "reset-1"})
            elif defect == "second-unsettled":
                readiness = readiness.model_copy(update={"established": False})
        return observation, readiness

    options["prepare_cohort"] = prepare
    if defect == "deadline-after-settle":
        options["clock"] = lambda: 1001.0 if "prepare-cohort" in events else 100.0
    if defect == "runtime-drift":
        options["verify_runtime"] = lambda *args: None if "step" in events else frozen
    with pytest.raises((ValueError, RuntimeError)):
        pe.run_managed_policy(frozen, **options)
    assert events.count("step") <= 1


def test_managed_bridge_does_not_import_legacy_publication_or_lineage(harness, monkeypatch):
    pe, frozen, options, events = managed_fixture(harness)
    original = builtins.__import__

    def deny(name, *args, **kwargs):
        assert not any(part in name for part in ("telemetry_to_prov", "lpg_neo4j_sync", "version_manager"))
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny)
    assert pe.run_managed_policy(frozen, **options).aggregate.outcome == "passed"


@pytest.mark.parametrize("defect", ["missing", "foreign-reset", "duplicate-reset", "phantom"])
def test_managed_bridge_joins_actual_completion_count_to_evaluator_records(harness, defect):
    pe, frozen, options, events = managed_fixture(harness)
    original = options["read_episodes"]

    def records(*args):
        result = original(*args)
        if defect == "missing":
            return ()
        if defect == "foreign-reset":
            return (result[0], result[1].model_copy(update={"reset_id": "foreign"}))
        if defect == "duplicate-reset":
            return (result[0], result[1].model_copy(update={"reset_id": result[0].reset_id}))
        return result

    if defect == "phantom":
        import torch

        options["env"].step = lambda action: ("ongoing", None, torch.tensor([False]), torch.tensor([False]), {})
    options["read_episodes"] = records
    with pytest.raises(ValueError, match="episode"):
        pe.run_managed_policy(frozen, **options)


def test_managed_bridge_zero_completed_episodes_remains_unknown(harness):
    import torch

    pe, frozen, options, events = managed_fixture(harness)
    options["env"].step = lambda action: ("ongoing", None, torch.tensor([False]), torch.tensor([False]), {})
    options["read_episodes"] = lambda *args: ()
    result = pe.run_managed_policy(frozen, **options)
    assert result.aggregate.completed == 0 and result.aggregate.success_rate is None
    assert result.aggregate.outcome == "unknown"


def test_managed_bridge_deadline_after_final_step_cannot_be_accepted(harness):
    pe, frozen, options, events = managed_fixture(harness)
    options["clock"] = lambda: 1001.0 if events.count("step") == 2 else 100.0
    with pytest.raises(ValueError, match="deadline"):
        pe.run_managed_policy(frozen, **options)


@pytest.mark.parametrize(
    "task_id,embodiment,evaluator,success",
    [
        ("A2.pick-and-place", "droid_abs_joint_pos", "pick-place-v1", True),
        ("navigation", "g1", "goal-region-v1", False),
    ],
)
def test_managed_task_profiles_use_same_bridge_and_selected_evaluator(
    harness, monkeypatch, task_id, embodiment, evaluator, success
):
    pe, frozen, options, events = managed_fixture(harness)
    frozen = frozen.model_copy(update={"task_id": task_id, "embodiment_id": embodiment, "evaluator_id": evaluator})
    original = options["read_episodes"]
    options["read_episodes"] = lambda *args: tuple(
        record.model_copy(update={"success": success}) for record in original(*args)
    )
    # Exercise the lazy production import, not a second rollout implementation.
    runner = load_source("policy_runner")
    monkeypatch.setitem(sys.modules, "isaaclab_arena.evaluation.policy_runner", runner)
    options.pop("rollout")
    result = pe.run_managed_policy(frozen, **options)
    assert result.aggregate.outcome == ("passed" if success else "failed")
    assert result.aggregate.completed == 2
