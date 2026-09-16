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
