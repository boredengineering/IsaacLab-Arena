# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Read-only CLI contracts, exercised only in the offline backend sandbox."""

import copy
import hashlib
import json

import pytest


def request():
    profile = {"profile_id": "offline", "settings_sha256": "a" * 64}
    return {
        "schema_version": "1",
        "source": {"kind": "new", "prompt": "Create a tabletop scene"},
        "criteria": [{
            "criterion_id": "layout",
            "kind": "structural",
            "evidence_producer": "graph-check-v1",
            "requirement": "required",
            "evaluator_version": "1",
            "required_modalities": ["scene_graph"],
            "coordinate_frames": ["world"],
            "observation_window": {"start_step": 0, "end_step": 0},
            "rubric": "Objects must be present",
            "subjects": ["table"],
            "limit": {"operator": "ge", "value": 1.0, "unit": "count"},
        }],
        "preserved": [],
        "allowed_interventions": [],
        "execution": {
            "generation_model": {**profile, "billing": "free"},
            "assessment_model": {**profile, "billing": "free"},
            "runtime": profile,
            "database": profile,
            "policy": None,
            "capture": profile,
            "seed": 42,
            "timestep_seconds": 0.01,
            "decimation": 2,
            "dcrg": None,
        },
        "budget": {
            "max_candidates": 2,
            "max_revisions": 1,
            "max_runtime_seconds": 60.0,
            "max_model_calls": 0,
            "max_model_tokens": 0,
            "max_cost_usd": 0.0,
            "max_realizations": 0,
            "max_steps": 0,
            "max_observations": 0,
            "max_policy_episodes": 0,
            "max_policy_steps": 0,
            "per_operation_timeout_seconds": 10.0,
            "total_deadline_seconds": 60.0,
        },
        "effects": {
            "allow_paid_models": False,
            "allow_runtime": False,
            "allow_database_reads": False,
            "allow_publication": False,
        },
    }


PREFIX = "isaaclab_arena.agentic_environment_generation.workflow"
PRIVATE = "PRIVATE_DO_NOT_ECHO_82a72"


def cli():
    try:
        from isaaclab_arena.agentic_environment_generation.workflow import cli as entry

        return entry
    except ModuleNotFoundError:
        pytest.fail("read-only inspect-contract CLI is missing")


def test_module_entrypoint_inspects_file_without_releasing_execution(tmp_path, capsys, monkeypatch):
    import runpy
    import sys

    path = tmp_path / "request.json"
    path.write_text(json.dumps(request()))
    monkeypatch.delitem(sys.modules, PREFIX + ".cli", raising=False)
    monkeypatch.setattr(sys, "argv", [PREFIX + ".cli", "inspect-contract", str(path)])
    with pytest.raises(SystemExit) as exit_result:
        runpy.run_module(PREFIX + ".cli", run_name="__main__")
    assert exit_result.value.code == 0
    output, error = capsys.readouterr()
    assert error == ""
    result = json.loads(output)
    assert result["execution_released"] is False and result["readiness_checked"] is False
    assert result["required_criteria"] == {"count": 1, "ids": ["layout"]}


def test_inspect_real_file_has_canonical_digest_and_only_public_plan(tmp_path, capsys):
    from isaaclab_arena.agentic_environment_generation.workflow import canonical_json, parse_contract

    raw = request()
    raw["source"]["prompt"] = PRIVATE
    raw["criteria"][0]["rubric"] = PRIVATE
    advisory = copy.deepcopy(raw["criteria"][0])
    advisory.update(criterion_id="advisory", requirement="advisory")
    raw["criteria"].append(advisory)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(raw))
    assert cli().main(["inspect-contract", str(path)]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert PRIVATE not in out
    expected_digest = hashlib.sha256(canonical_json(parse_contract(path.read_bytes())).encode()).hexdigest()
    assert json.loads(out) == {
        "schema_version": "1",
        "contract_digest": expected_digest,
        "required_criteria": {"ids": ["layout"], "count": 1},
        "advisory_criteria": {"ids": ["advisory"], "count": 1},
        "planned_dependencies": [
            {"category": "generation_model", "profile_id": "offline"},
            {"category": "neo4j", "profile_id": "offline"},
            {"category": "runtime", "profile_id": "offline"},
        ],
        "scene_assessment": {"compatible": True, "code": "supported_projection"},
        "execution_released": False,
        "readiness_checked": False,
    }
    assert cli().main(["inspect-contract", str(path)]) == 0
    assert capsys.readouterr().out == out


@pytest.mark.parametrize(
    "case", ["missing", "invalid", "validation", "oversize", "directory", "symlink", "fifo", "utf8", "duplicate"]
)
def test_bad_file_has_static_diagnostic_without_private_input(case, tmp_path, capsys):
    import os

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import MAX_CONTRACT_BYTES

    path = tmp_path / PRIVATE
    if case == "directory":
        path.mkdir()
    elif case == "symlink":
        target = tmp_path / "real.json"
        target.write_text(json.dumps(request()))
        path.symlink_to(target)
    elif case == "fifo":
        os.mkfifo(path)
    elif case != "missing":
        data = {
            "invalid": PRIVATE.encode(),
            "validation": json.dumps({"schema_version": PRIVATE}).encode(),
            "oversize": b" " * (MAX_CONTRACT_BYTES + 1),
            "utf8": b"\xff" + PRIVATE.encode(),
            "duplicate": ('{"' + PRIVATE + '":1,"' + PRIVATE + '":2}').encode(),
        }[case]
        path.write_bytes(data)
    if case == "fifo":
        import signal

        def timeout(*_):
            # Must escape the CLI's OSError handler; otherwise a blocking open
            # would look like the expected static rejection after the alarm.
            raise AssertionError("nonregular input must not block")

        previous = signal.signal(signal.SIGALRM, timeout)
        signal.alarm(1)
        try:
            result = cli().main(["inspect-contract", str(path)])
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
    else:
        result = cli().main(["inspect-contract", str(path)])
    assert result == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err == "inspect-contract: invalid request file\n"
    assert PRIVATE not in err


@pytest.mark.parametrize(
    "args", [[], ["inspect-contract"], ["run", PRIVATE], ["status"], ["inspect-contract", PRIVATE, "--" + PRIVATE]]
)
def test_bad_arguments_are_static_and_no_placeholder_commands(args, capsys):
    assert cli().main(args) == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert err == "inspect-contract: invalid arguments\n"


def test_unsupported_policy_is_inspected_not_admitted(tmp_path, capsys):
    raw = request()
    raw["criteria"][0].update(kind="policy", required_modalities=["policy_rollout"])
    raw["execution"]["policy"] = raw["execution"]["runtime"]
    raw["effects"]["allow_runtime"] = True
    raw["budget"].update(max_realizations=1, max_steps=1, max_observations=1, max_policy_episodes=1, max_policy_steps=1)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw))
    assert cli().main(["inspect-contract", str(path)]) == 0
    out, err = capsys.readouterr()
    summary = json.loads(out)
    assert err == ""
    assert summary["scene_assessment"] == {"compatible": False, "code": "unsupported_scene_assessment"}
    assert summary["execution_released"] is False
    assert summary["readiness_checked"] is False
    assert {item["category"] for item in summary["planned_dependencies"]} == {
        "runtime",
        "neo4j",
        "generation_model",
        "capture",
        "gpu",
        "policy",
    }


def test_domain_construction_and_cli_do_not_import_or_construct_effects(tmp_path, capsys, monkeypatch):
    import builtins
    import importlib.abc
    import importlib.util
    import sys

    forbidden = (
        "argparse",
        "torch",
        "isaacsim",
        "isaaclab",
        "omni",
        "pxr",
        "neo4j",
        "openai",
        "anthropic",
        "requests",
        "httpx",
        "isaaclab_arena_examples",
        "isaaclab_arena.agentic_environment_generation.environment_generation_agent",
        "isaaclab_arena.agentic_environment_generation.inference",
        PREFIX + ".service",
        PREFIX + ".coordinator",
        PREFIX + ".neo4j_store",
    )
    attempts = []
    original_import = builtins.__import__

    def check(name):
        if any(name == item or name.startswith(item + ".") for item in forbidden):
            attempts.append(name)
            raise AssertionError("forbidden import attempted")

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        resolved = importlib.util.resolve_name("." * level + name, globals["__package__"]) if level else name
        check(resolved)
        return original_import(name, globals, locals, fromlist, level)

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            check(fullname)

    for name in tuple(sys.modules):
        if name == PREFIX or name.startswith(PREFIX + "."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(sys, "meta_path", [Guard(), *sys.meta_path])
    domain = importlib.import_module(PREFIX)
    contract = domain.WorkflowContract.model_validate(request())
    assert domain.parse_contract(domain.canonical_json(contract)) == contract
    readiness = importlib.import_module(PREFIX + ".readiness")
    projection = importlib.import_module(PREFIX + ".evidence_contracts")
    assert readiness.required_dependencies(contract)
    assert projection.project_required_criteria(contract)
    assert PREFIX + ".cli" not in sys.modules
    assert attempts == []

    # argparse is allowed only after entering the CLI module, never in the domain.
    forbidden = tuple(name for name in forbidden if name != "argparse")

    def no_effects(*args, **kwargs):
        raise AssertionError("readiness probe or effect construction attempted")

    monkeypatch.setattr(readiness.DependencyGate, "__init__", no_effects)
    monkeypatch.setattr(readiness, "durable_readiness", no_effects)
    entry = importlib.import_module(PREFIX + ".cli")
    raw = request()
    raw["source"] = {"kind": "existing", "identity": "scene", "content": PRIVATE}
    path = tmp_path / "existing.json"
    path.write_text(json.dumps(raw))
    assert entry.main(["inspect-contract", str(path)]) == 0
    out, err = capsys.readouterr()
    assert err == "" and PRIVATE not in out
    assert json.loads(out)["planned_dependencies"] == [
        {"category": "neo4j", "profile_id": "offline"},
        {"category": "runtime", "profile_id": "offline"},
    ]
    assert attempts == []
