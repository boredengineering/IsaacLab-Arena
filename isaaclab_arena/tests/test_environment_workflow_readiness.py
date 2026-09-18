# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Readiness admission with synthetic probes and model factories; never live dependencies."""

import pytest


def requirement(name="runtime", identity="runtime-1"):
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyRequirement

    return DependencyRequirement(name, "a" * 64, identity, profile_id="test-profile")


def result(name="runtime", status="passed", identity="runtime-1", digest="a" * 64):
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyResult

    return DependencyResult(name, status, digest, identity, profile_id="test-profile")


@pytest.mark.parametrize("status", ["unavailable", "mismatch", "not_checked"])
def test_required_dependency_failure_never_constructs_model(status):
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate

    effects = []
    gate = DependencyGate(lambda request, timeout: result(status=status), clock=lambda: 10.0)
    report, output = gate.execute((requirement(),), lambda: effects.append("initialization_ping"), timeout_s=5.0)
    assert not report.ready and report.blockers == ("runtime",)
    assert output is None and effects == []


def test_all_ready_positive_control_constructs_model_once_after_probes():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate

    effects = []

    def probe(request, timeout):
        effects.append(("probe", request.dependency_id))
        assert 0 < timeout <= 5
        return result(request.dependency_id, identity=request.instance_id)

    def model():
        effects.append("initialization_ping")
        return "synthetic-completion"

    gate = DependencyGate(probe, clock=lambda: 10.0)
    report, output = gate.execute((requirement(), requirement("neo4j", "graph-1")), model, timeout_s=5.0)
    assert report.ready and report.blockers == ()
    assert output == "synthetic-completion"
    assert effects == [("probe", "runtime"), ("probe", "neo4j"), "initialization_ping"]
    assert report.checked_at == 10.0


@pytest.mark.parametrize("changed", ["profile", "instance", "dependency", "receipt"])
def test_changed_identity_or_invalid_receipt_cannot_pass(changed):
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate

    observations = {
        "profile": result(digest="b" * 64),
        "instance": result(identity="replacement"),
        "dependency": result(name="different"),
        "receipt": {"status": "passed"},
    }
    calls = []
    gate = DependencyGate(lambda *_: observations[changed], clock=lambda: 10.0)
    report, _ = gate.execute((requirement(),), lambda: calls.append(True), timeout_s=5.0)
    assert not report.ready and calls == []
    assert report.results[0].status in ("mismatch", "unavailable")


def test_probe_failure_retains_only_static_diagnostic():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate

    def probe(*_):
        raise OSError("synthetic-protected-marker")

    report = DependencyGate(probe, clock=lambda: 10.0).check((requirement(),), timeout_s=5.0)
    assert not report.ready
    assert report.results[0].code == "probe_failed"
    assert "synthetic-protected-marker" not in repr(report)


def test_deadline_expired_during_probe_prevents_model_and_further_probes():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate

    now = [10.0]
    probes, models = [], []

    def probe(request, timeout):
        probes.append(request.dependency_id)
        now[0] += timeout
        return result(request.dependency_id, identity=request.instance_id)

    gate = DependencyGate(probe, clock=lambda: now[0])
    report, _ = gate.execute(
        (requirement(), requirement("neo4j", "graph-1")), lambda: models.append(True), timeout_s=5.0
    )
    assert not report.ready and models == [] and probes == ["runtime"]
    assert all(item.code == "probe_timeout" for item in report.results)


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), "5"])
def test_invalid_timeout_rejected_before_probes(timeout):
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate

    calls = []
    gate = DependencyGate(lambda *_: calls.append(True), clock=lambda: 10.0)
    with pytest.raises(ValueError):
        gate.check((requirement(),), timeout_s=timeout)
    assert calls == []


@pytest.mark.parametrize("requests", [(), ("unvalidated",)])
def test_invalid_request_set_rejected_before_probe(requests):
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate

    calls = []
    with pytest.raises(ValueError):
        DependencyGate(lambda *_: calls.append(True)).check(requests, timeout_s=1.0)
    assert calls == []


def test_duplicate_requests_rejected_before_probe():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate

    calls = []
    with pytest.raises(ValueError):
        DependencyGate(lambda *_: calls.append(True)).check((requirement(), requirement()), timeout_s=1.0)
    assert calls == []


def test_check_is_observation_only_and_next_execution_rechecks_dependencies():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate

    state = ["passed"]
    calls = []
    gate = DependencyGate(lambda request, timeout: result(status=state[0]), clock=lambda: 10.0)
    assert gate.check((requirement(),), timeout_s=5.0).ready
    state[0] = "unavailable"
    report, _ = gate.execute((requirement(),), lambda: calls.append("model"), timeout_s=5.0)
    assert not report.ready and calls == []


def test_model_errors_are_not_relabelled_dependency_failure_or_retried():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate

    calls = []

    def model():
        calls.append(True)
        raise RuntimeError("synthetic effect outcome unknown")

    gate = DependencyGate(lambda *_: result(), clock=lambda: 10.0)
    with pytest.raises(RuntimeError, match="outcome unknown"):
        gate.execute((requirement(),), model, timeout_s=5.0)
    assert calls == [True]


def test_equal_settings_different_profile_id_blocks_release():
    from dataclasses import replace

    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate

    observed = replace(result(), profile_id="different-profile")
    calls = []
    report, _ = DependencyGate(lambda *_: observed).execute((requirement(),), lambda: calls.append(True), timeout_s=5)
    assert report.results[0].status == "mismatch"
    assert report.results[0].code == "identity_mismatch"
    assert calls == []
