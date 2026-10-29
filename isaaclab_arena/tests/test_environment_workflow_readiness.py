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


def public_selection(outcome="scene-only"):
    from isaaclab_arena.agentic_environment_generation.inference_profiles import (
        frozen_builtin_profile,
        inference_profile_catalogue,
    )

    return {
        "schema_version": 1,
        "outcome": outcome,
        "roles": {
            role: {
                "provider": "openai",
                "model": "gpt-4.1",
                "endpoint": "https://api.openai.com/v1",
                "inference_profile": frozen_builtin_profile(inference_profile_catalogue()[0]),
                "credential": {
                    "alias": "shared-cloud",
                    "source": "private_file",
                    "source_role": "models." + role,
                    "public_id": "project-public-1",
                },
            }
            for role in ("generation", "assessment", "repair")
        },
    }


def offline_report(value):
    import json

    from isaaclab_arena.agentic_environment_generation.workflow.setup_readiness import setup_readiness

    return setup_readiness(json.dumps(value).encode())


def test_public_selection_preserves_literals_and_shared_alias_without_readiness():
    import copy
    import hashlib
    import json

    value = public_selection()
    before = copy.deepcopy(value)
    report = offline_report(value)
    assert value == before
    for role in ("generation", "assessment", "repair"):
        row = report["roles"][role]
        assert row["selection"] == value["roles"][role]
        assert row["public_selection"] == "configured"
        assert row["shared_alias_with"] == sorted({"generation", "assessment", "repair"} - {role})
        assert row["access"] == row["capability"] == "not_checked"
        assert row["execution"] == "not_authorized" and row["checked_at"] is None
    canonical = json.dumps(report["selection"], sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert report["selection_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert (
        offline_report(json.loads(json.dumps(value, sort_keys=True)))["selection_sha256"] == report["selection_sha256"]
    )
    for field, changed in (("model", "literal-other"), ("endpoint", "https://example.invalid/v1/")):
        altered = copy.deepcopy(value)
        altered["roles"]["generation"]["inference_profile"] = None
        altered["roles"]["generation"][field] = changed
        different = offline_report(altered)
        assert different["selection_sha256"] != report["selection_sha256"]
        assert different["roles"]["generation"]["selection"][field] == changed
        assert different["roles"]["generation"]["capability"] == "not_checked"
    altered = copy.deepcopy(value)
    altered["roles"]["generation"]["credential"]["alias"] = "rotated-public-alias"
    assert offline_report(altered)["selection_sha256"] != report["selection_sha256"]


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "outcome",
        "role",
        "secret",
        "grant",
        "checked",
        "credential_value",
        "credential_path",
        "source_role",
        "shared_source",
        "provider",
        "profile_model",
        "profile_verified",
        "model_whitespace",
        "endpoint_userinfo",
        "endpoint_query",
        "endpoint_fragment",
        "endpoint_port",
        "endpoint_whitespace",
        "profile_unknown",
        "oversized_model",
        "unicode_control",
    ],
)
def test_public_selection_rejects_malformed_or_asserted_authority(change):
    value = public_selection()
    generation = value["roles"]["generation"]
    if change == "version":
        value["schema_version"] = True
    elif change == "outcome":
        value["outcome"] = "live-ready"
    elif change == "role":
        value["roles"]["admin"] = None
    elif change in {"secret", "grant", "checked"}:
        value[{"secret": "api_key", "grant": "execution_authorized", "checked": "checked_at"}[change]] = "SENTINEL"
    elif change == "credential_value":
        generation["credential"]["value"] = "SENTINEL"
    elif change == "credential_path":
        generation["credential"]["path"] = "/private/SENTINEL"
    elif change == "source_role":
        generation["credential"]["source_role"] = "databases.operational"
    elif change == "shared_source":
        generation["credential"]["source"] = "named_environment"
    elif change == "provider":
        generation["provider"] = "ambient"
    elif change == "profile_model":
        generation["model"] = "other-model"
    elif change == "profile_verified":
        generation["inference_profile"]["verification"] = "passed"
    elif change == "profile_unknown":
        generation["inference_profile"]["key"] = "SENTINEL"
    elif change == "oversized_model":
        generation["model"] = "m" * 257
    elif change == "unicode_control":
        generation["credential"]["alias"] = "bad\u202ename"
    elif change == "model_whitespace":
        generation["model"] = " gpt-4.1"
    else:
        generation["inference_profile"] = None
        generation["endpoint"] = {
            "endpoint_userinfo": "https://user:SENTINEL@example.invalid/v1",
            "endpoint_query": "https://example.invalid/v1?key=SENTINEL",
            "endpoint_fragment": "https://example.invalid/v1#SENTINEL",
            "endpoint_port": "https://example.invalid:bad/v1",
            "endpoint_whitespace": " https://example.invalid/v1",
        }[change]
    with pytest.raises(ValueError, match="^Invalid public selection$"):
        offline_report(value)


@pytest.mark.parametrize(
    "endpoint,authentication,tls,transport,auth",
    [
        ("bolt://127.0.0.1:7687", "basic", "none", "compatible", "compatible"),
        ("bolt://db.example:7687", "basic", "none", "incompatible", "compatible"),
        ("neo4j+s://db.example:7687", "bearer", "system_ca", "incompatible", "incompatible"),
        ("bolt+s://127.0.0.1:7687", "kerberos", "custom_ca", "incompatible", "incompatible"),
        ("bolt://127.0.0.1:7687", "basic", "system_ca", "incompatible", "compatible"),
        ("bolt://127.0.0.1:07687", "basic", "none", "incompatible", "compatible"),
        (None, None, None, "unresolved", "unresolved"),
    ],
)
def test_offline_database_compatibility_is_literal_and_declares_separate_prior_slot(
    endpoint, authentication, tls, transport, auth
):
    value = public_selection()
    for role, slot in (("operational_db", "operational"), ("prior_read", "prior_read")):
        value["roles"][role] = {
            "provider": "neo4j",
            "database": "pilot",
            "endpoint": endpoint,
            "authentication": authentication,
            "tls": tls,
            "credential": {"alias": "db-" + slot, "source": "private_file", "source_role": "databases." + slot},
        }
    report = offline_report(value)
    assert "database_compatibility" in report, "missing truthful installed DB compatibility row"
    for role in ("operational_db", "prior_read"):
        row = report["database_compatibility"][role]
        assert row["endpoint"] == endpoint and row["authentication"] == authentication and row["tls"] == tls
        assert row["transport"] == transport and row["auth"] == auth
    assert report["database_compatibility"]["operational_db"]["installed_credential_slot"] == "databases.operational"
    assert report["database_compatibility"]["prior_read"]["installed_credential_slot"] == "databases.prior_read"
    assert report["installed_boundary"]["admin_credential_slot"] == "databases.operational"
    assert report["installed_boundary"]["distinct_principals_select_distinct_db_logins"] is False
    assert report["installed_boundary"]["provider_bootstrap"] == "private_roles_v2"
    assert report["installed_boundary"]["mode"] == "query-only"
    if "incompatible" in (transport, auth):
        assert any(
            b["code"] == "database_adapter" and b["owner"] == "implementation_missing" for b in report["blockers"]
        )


def test_blockers_are_consolidated_owned_actionable_and_outcome_scoped():
    scene = offline_report(public_selection())
    policy = offline_report(public_selection("required-policy"))
    assert scene["selection_sha256"] != policy["selection_sha256"]
    for report in (scene, policy):
        blockers = report["blockers"]
        assert {b["owner"] for b in blockers} == {"operator_setup", "implementation_missing", "runtime_verification"}
        assert len({b["code"] for b in blockers}) == len(blockers)
        assert all(b["next_action"] and report["outcome"] in b["outcomes"] for b in blockers)
        codes = {b["code"] for b in blockers}
        assert {
            "installed_execution",
            "private_role_bootstrap",
            "model_access_budget",
            "runtime_identity_assets",
            "database_safety",
            "bounded_access_checks",
            "native_calibration",
            "execution_approval",
        } <= codes
        assert report["credential_generation"] == "not_observed"
        assert report["access_checked_at"] is None and report["capability_checked_at"] is None
    assert not any("local_policy" in b["roles"] for b in scene["blockers"])
    assert {"policy_composition", "policy_runtime_verification"} <= {b["code"] for b in policy["blockers"]}
    assert not {"policy_composition", "policy_runtime_verification"} & {b["code"] for b in scene["blockers"]}
    assert scene["roles"]["local_policy"]["required_for_outcome"] is False
    assert policy["roles"]["local_policy"]["required_for_outcome"] is True


def test_offline_report_has_no_file_environment_runtime_or_authority_dependencies(monkeypatch):
    import builtins
    import io
    import json
    import os

    from isaaclab_arena.agentic_environment_generation.workflow.setup_readiness import setup_readiness

    raw = json.dumps(public_selection()).encode()
    real_import = builtins.__import__
    forbidden = (
        "neo4j",
        "openai",
        "socket",
        "subprocess",
        "installed_config",
        "installed_composition",
        "execution_grants",
        "native",
        "inference_backend",
        "dotenv",
        "torch",
        "isaacsim",
    )

    def guarded_import(name, *args, **kwargs):
        assert not any(part in name for part in forbidden), name
        return real_import(name, *args, **kwargs)

    def denied(*args, **kwargs):
        raise AssertionError("offline report attempted ambient I/O")

    class NoEnvironment(dict):
        __getitem__ = get = __iter__ = denied

    with monkeypatch.context() as scoped:
        scoped.setattr(builtins, "__import__", guarded_import)
        scoped.setattr(builtins, "open", denied)
        scoped.setattr(io, "open", denied)
        scoped.setattr(os, "open", denied)
        scoped.setattr(os, "getenv", denied)
        scoped.setattr(os, "environ", NoEnvironment())
        reports = (setup_readiness(), setup_readiness(raw))
    assert all(not report["execution_authorized"] for report in reports)
    assert all("credential_generation" in report for report in reports)


def test_local_policy_tcp_selection_is_inventory_not_inference_readiness():
    value = public_selection("required-policy")
    value["roles"]["local_policy"] = {
        "provider": "gr00t",
        "model": "checkpoint-example",
        "endpoint": "tcp://127.0.0.1:5555",
        "credential": {"alias": "local-no-auth", "source": "none", "source_role": "policy.local"},
    }
    try:
        report = offline_report(value)
    except ValueError:
        pytest.fail("native GR00T TCP endpoint must be representable without importing its transport")
    row = report["roles"]["local_policy"]
    assert row["public_selection"] == "configured"
    assert row["selection"] == value["roles"]["local_policy"]
    assert row["capability"] == "not_checked" and row["execution"] == "not_authorized"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.invalid:",
        "https://../v1",
        "https://host!bad/v1",
        "https://example.invalid:443:",
        "http://999.999.999.999/v1",
    ],
)
def test_malformed_endpoint_not_merely_an_unsupported_selection(endpoint):
    value = public_selection()
    value["roles"]["generation"].update(endpoint=endpoint, inference_profile=None)
    with pytest.raises(ValueError, match="^Invalid public selection$"):
        offline_report(value)


def test_operational_private_pipe_selection_does_not_claim_installed_file_support():
    value = public_selection()
    value["roles"]["operational_db"] = {
        "provider": "neo4j",
        "database": "pilot",
        "endpoint": "bolt://127.0.0.1:7687",
        "authentication": "basic",
        "tls": "none",
        "credential": {"alias": "db-ops", "source": "private_pipe", "source_role": "databases.operational"},
    }
    report = offline_report(value)
    assert report["database_compatibility"]["operational_db"].get("credential_source") == "incompatible"
    assert any(b["code"] == "database_credential_source" for b in report["blockers"])
