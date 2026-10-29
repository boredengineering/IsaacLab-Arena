# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Memory-only operation grants, using static fake secrets and an injected clock."""

import json

import pytest

SECRET = "dummy-execution-secret-123456"
PROFILE = {
    "model": "test-model",
    "endpoint": "https://example.invalid",
    "principal": "test-user",
    "credential_generation": "gen-1",
}


def store(**kwargs):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

    return ExecutionGrants(clock=lambda: 100, **kwargs)


def issue(grants, **kwargs):
    args = dict(
        owner_id="owner",
        operation_id="operation",
        capability="model",
        profile=PROFILE,
        credentials={"api_key": SECRET, "options": {"values": [1]}},
        expires_at=200,
    )
    return grants.issue(**(args | kwargs))


@pytest.mark.parametrize(
    "owner, operation, capability",
    [
        ("foreign", "operation", "model"),
        ("owner", "foreign", "model"),
        ("owner", "operation", "retrieval_read"),
        ("owner", "operation", "unknown"),
    ],
)
def test_exact_binding_never_falls_back(owner, operation, capability):
    grants = store()
    public = issue(grants)
    with pytest.raises(ValueError, match="Execution grant unavailable"):
        grants.resolve(owner, public["grant_id"], operation, capability)
    with pytest.raises(ValueError, match="Execution grant unavailable"):
        grants.resolve("owner", "unknown", "operation", "model")


@pytest.mark.parametrize("capability", ["model", "retrieval_read", "publication_write", "reconciliation_read"])
def test_supported_capabilities(capability):
    grants = store()
    public = issue(grants, capability=capability)
    assert grants.resolve("owner", public["grant_id"], "operation", capability)


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": float("nan")},
        {"expires_at": float("inf")},
        {"expires_at": -float("inf")},
        {"expires_at": True},
        {"expires_at": 100},
        {"expires_at": 7301},
        {"capability": "unknown"},
        {"capability": []},
        {"owner_id": ""},
        {"operation_id": "x" * 257},
        {"profile": {"bad": object()}},
        {"profile": {1: "bad"}},
        {"credentials": {"key": float("nan")}},
        {"credentials": {"key": "x" * 65537}},
        {"profile": {"many": [0] * 4097}},
    ],
)
def test_reject_invalid_or_unbounded_input(changes):
    with pytest.raises(ValueError):
        issue(store(), **changes)


def test_capacity_is_finite_and_expired_entries_free_space():
    grants = store(capacity=1)
    public = issue(grants)
    with pytest.raises(ValueError, match="capacity"):
        issue(grants)
    assert grants.resolve("owner", public["grant_id"], "operation", "model")
    grants.clock = lambda: 200
    issue(grants, expires_at=201)
    for capacity in (0, -1, True, 1.5, 129):
        with pytest.raises(ValueError):
            store(capacity=capacity)


def test_json_depth_and_cycles_are_rejected():
    deep = {}
    for _ in range(18):
        deep = {"nested": deep}
    cycle = []
    cycle.append(cycle)
    for value in (deep, {"cyclic": cycle}):
        with pytest.raises(ValueError):
            issue(store(), credentials=value)


@pytest.mark.parametrize("value", [SECRET, {"nested": [{"prefix-" + SECRET: "ok"}]}, {"nested": ["prefix/" + SECRET]}])
def test_protect_public_scans_values_and_nested_keys(value):
    grants = store()
    issue(grants)
    with pytest.raises(ValueError) as error:
        grants.protect_public(value)
    assert SECRET not in str(error.value)
    assert grants.protect_public({"safe": ["public"]}) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"profile": {"nested": [{SECRET: "hidden"}]}},
        {"profile": {"model": SECRET}},
        {"profile": {"nested": {"api_key": "not-a-known-secret"}}},
        {"owner_id": SECRET},
        {"operation_id": SECRET},
    ],
)
def test_issue_rejects_secret_material_in_all_public_metadata(changes):
    with pytest.raises(ValueError) as error:
        issue(store(), **changes)
    assert SECRET not in str(error.value)


def test_nested_private_credentials_and_previous_grants_protect_public():
    grants = store()
    issue(grants, credentials={"auth": {"token": SECRET}, "model": "test-model"})
    with pytest.raises(ValueError):
        issue(grants, credentials={"api_key": "second-dummy-secret"}, profile={"principal": SECRET})
    with pytest.raises(ValueError):
        grants.protect_public({SECRET: "safe"})
    deep = {}
    for _ in range(18):
        deep = {"nested": deep}
    with pytest.raises(ValueError):
        grants.protect_public(deep)


def test_bad_clock_fails_closed_on_resolve():
    grants = store()
    public = issue(grants)
    grants.clock = lambda: float("nan")
    with pytest.raises(ValueError):
        grants.resolve("owner", public["grant_id"], "operation", "model")


def test_reference_collision_fails_without_replacing_existing_grant(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import execution_grants

    grants = store()
    monkeypatch.setattr(execution_grants.secrets, "token_hex", lambda size: "a" * 64)
    public = issue(grants)
    with pytest.raises(ValueError):
        issue(grants, credentials={"api_key": "replacement-secret"})
    assert grants.resolve("owner", public["grant_id"], "operation", "model")["api_key"] == SECRET


@pytest.mark.parametrize("reference", [None, [], {}, 123])
def test_malformed_reference_fails_closed(reference):
    with pytest.raises(ValueError):
        store().resolve("owner", reference, "operation", "model")


def test_lifecycle_replacement_revocation_owner_cleanup_and_exact_expiry():
    grants = store()
    first = issue(grants)
    second = issue(grants)
    assert first["grant_id"] != second["grant_id"]
    grants.revoke(first["grant_id"])
    grants.revoke(first["grant_id"])
    with pytest.raises(ValueError):
        grants.resolve("owner", first["grant_id"], "operation", "model")
    assert grants.resolve("owner", second["grant_id"], "operation", "model")["api_key"] == SECRET
    other = issue(grants, owner_id="other")
    grants.forget_owner("owner")
    with pytest.raises(ValueError):
        grants.resolve("owner", second["grant_id"], "operation", "model")
    grants.clock = lambda: 199.999
    assert grants.resolve("other", other["grant_id"], "operation", "model")
    grants.clock = lambda: 200
    with pytest.raises(ValueError):
        grants.resolve("other", other["grant_id"], "operation", "model")
    grants.purge()
    fresh = issue(grants, expires_at=201)
    grants.clear()
    with pytest.raises(ValueError):
        grants.resolve("owner", fresh["grant_id"], "operation", "model")


def test_issue_resolve_detaches_private_config_and_public_profile():
    grants = store()
    profile = {**PROFILE, "metadata": {"labels": ["original"]}}
    credentials = {"api_key": SECRET, "options": {"values": [1]}}
    public = issue(grants, profile=profile, credentials=credentials)
    assert set(public) == {"grant_id", "owner_id", "operation_id", "capability", "profile", "expires_at"}
    assert SECRET not in json.dumps(public)
    profile["metadata"]["labels"].append("changed")
    credentials["options"]["values"].append(2)
    assert public["profile"]["metadata"]["labels"] == ["original"]
    public["profile"]["model"] = "changed"
    resolved = grants.resolve("owner", public["grant_id"], "operation", "model")
    assert resolved == {"api_key": SECRET, "options": {"values": [1]}}
    resolved["options"]["values"].append(3)
    assert grants.resolve("owner", public["grant_id"], "operation", "model")["options"]["values"] == [1]


def _workflow_packet_fixture():
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration

    fence = AttemptFence(
        run_id="run", intent_id="intent", attempt_id="attempt", generation=1, owner_id="owner", owner_epoch=1
    )
    reg = WorkerRegistration(
        registration_id="registered", fence=fence, host="host", boot="boot", pid=10, pgid=10, sid=10, start_ticks=100
    )
    return {
        "inputs": {
            "operation": "new",
            "prompt": "synthetic",
            "retrieval_policy": "allow_fallback",
            "execution_catalogue_sha256": "c" * 64,
        },
        "config": {"api_key": SECRET, "model": "gpt-6-astra", "base_url": "https://api.openai.com/v1"},
        "graph_config": None,
        "workflow_execution": {
            "version": 1,
            "fence": fence.model_dump(mode="json"),
            "registration": reg.model_dump(mode="json"),
            "reservation": _attempt_budget_fixture()["reservation"].model_dump(mode="json"),
            "admitted_at": 90.0,
            "released_at": 100.0,
            "deadline": 110.0,
        },
    }


def _accounting_fixture(model="gpt-6-astra"):
    return dict(
        version=1, attested=True, model=model, endpoint="https://api.openai.com/v1", max_tokens=100, max_cost_usd="0.10"
    )


@pytest.mark.parametrize("nested_registration", [False, True])
def test_scene_allowance_rejects_boolean_fence_binding(monkeypatch, nested_registration):
    import copy
    import hashlib

    from isaaclab_arena_examples.agentic_environment_generation.web_api import scene_worker as worker

    packet = _workflow_packet_fixture()
    monkeypatch.setattr(worker.time, "time", lambda: 103.0)
    packet["config"]["workflow_accounting"] = _accounting_fixture()
    packet["workflow_execution"]["reservation"].update(model_calls=10, model_tokens=100, cost_ceiling_usd=0.1)
    execution = packet["workflow_execution"]
    binding: dict = dict(
        codec="scene-model-request-v1",
        registration=copy.deepcopy(execution["registration"]),
        fence=copy.deepcopy(execution["fence"]),
        run_id="run",
        contract_digest="d" * 64,
        scene_action="refine",
    )
    reference = dict(
        family="scene-model-input",
        version=hashlib.sha256(worker.canonical(binding)).hexdigest(),
        manifest_digest="a" * 64,
        binding=binding,
    )
    packet["inputs"].update(
        scene_action="refine",
        scene_payload=dict(root="/private/scene", store_id="store", registry_id="registry", request=reference),
    )
    assert worker.scene_allowance(packet).attempted_calls == 0
    target = binding["registration"]["fence"] if nested_registration else binding["fence"]
    target["owner_epoch"] = True
    reference["version"] = hashlib.sha256(worker.canonical(binding)).hexdigest()
    with pytest.raises(ValueError, match="binding mismatch"):
        worker.scene_allowance(packet)


@pytest.mark.parametrize("price", ["0", "0.10"])
def test_validated_accounting_is_metadata_not_secret_material(price):
    grants = store()
    accounting = _accounting_fixture("test-model") | {"max_cost_usd": price}
    credentials = {
        "api_key": SECRET,
        "model": "test-model",
        "base_url": accounting["endpoint"],
        "workflow_accounting": accounting,
    }
    public = issue(grants, credentials=credentials)
    resolved = grants.resolve("owner", public["grant_id"], "operation", "model")
    assert resolved["workflow_accounting"]["max_cost_usd"] == price
    grants.protect_public({"model": "test-model", "price": price, "counter": 0})
    with pytest.raises(ValueError):
        grants.protect_public({"leak": SECRET})


@pytest.mark.parametrize("damage", ["extra", "model", "endpoint", "unattested", "missing_origin"])
def test_accounting_metadata_exemption_requires_exact_valid_binding(damage):
    accounting = _accounting_fixture("test-model")
    credentials = {
        "api_key": SECRET,
        "model": "test-model",
        "base_url": accounting["endpoint"],
        "workflow_accounting": accounting,
    }
    if damage == "extra":
        accounting["extra"] = SECRET
    elif damage in {"model", "endpoint"}:
        accounting[damage] = "foreign"
    elif damage == "unattested":
        accounting["attested"] = False
    else:
        credentials.pop("base_url")
    grants = store()
    with pytest.raises(ValueError, match="accounting"):
        issue(grants, credentials=credentials)
    assert not grants._records


def test_workflow_accounting_uses_private_bound_and_retained_reservation(monkeypatch):
    from decimal import Decimal

    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation_worker as worker

    packet = _workflow_packet_fixture()
    monkeypatch.setattr(worker.time, "time", lambda: 103.0)
    monkeypatch.setattr(worker.time, "monotonic", lambda: 20.0)
    packet["config"]["workflow_accounting"] = _accounting_fixture()
    packet["workflow_execution"]["reservation"].update(model_calls=10, model_tokens=100, cost_ceiling_usd=0.1)
    allowance = worker.workflow_allowance(packet)
    assert allowance.token_cost_bounded
    allowance.charge()
    with pytest.raises(ValueError, match="budget exhausted"):
        allowance.charge()
    assert allowance.attempted_calls == 1 and allowance.charged_tokens == 100
    assert allowance.charged_cost_usd == Decimal("0.1")


def test_workflow_clock_sampling_does_not_extend_deadline(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation_worker as worker

    monotonic = [20.0]

    def wall():
        monotonic[0] = 22.0
        return 103.0

    monkeypatch.setattr(worker.time, "time", wall)
    monkeypatch.setattr(worker.time, "monotonic", lambda: monotonic[0])
    assert worker.workflow_allowance(_workflow_packet_fixture()).deadline == 27.0


def test_workflow_worker_packet_elapsed_budget_and_pre_release(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation_worker as worker

    packet = _workflow_packet_fixture()
    monkeypatch.setattr(worker.time, "time", lambda: 103.0)
    monkeypatch.setattr(worker.time, "monotonic", lambda: 20.0)
    allowance = worker.workflow_allowance(packet)
    assert allowance.max_calls == 1 and allowance.deadline == 27.0
    packet["workflow_execution"]["released_at"] = None
    with pytest.raises(ValueError, match="^Invalid workflow execution packet$"):
        worker.workflow_allowance(packet)


@pytest.mark.parametrize(
    "damage",
    [
        "version",
        "extra",
        "fence",
        "expired",
        "future",
        "unbounded",
        "graph",
        "managed",
        "refine",
        "base",
        "boolean",
        "nan",
    ],
)
def test_workflow_packet_rejects_wrong_scope_and_timing(monkeypatch, damage):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation_worker as worker

    envelope = _workflow_packet_fixture()
    packet = envelope["workflow_execution"]
    monkeypatch.setattr(worker.time, "time", lambda: 103.0)
    if damage == "version":
        packet["version"] = True
    if damage == "extra":
        packet["secret_extra"] = SECRET
    if damage == "fence":
        packet["registration"]["fence"]["owner_epoch"] = 2
    if damage == "expired":
        packet["deadline"] = 103.0
    if damage == "future":
        packet["released_at"] = 104.0
    if damage == "unbounded":
        packet["deadline"] = 111.0
    if damage == "graph":
        envelope["graph_config"] = {"password": SECRET}
    if damage == "managed":
        envelope["managed_context"] = {}
    if damage == "refine":
        envelope["inputs"]["operation"] = "refine"
    if damage == "base":
        envelope["inputs"]["base_yaml"] = "injected"
    if damage == "boolean":
        packet["admitted_at"] = True
    if damage == "nan":
        packet["deadline"] = float("nan")
    with pytest.raises(ValueError, match="^Invalid workflow execution packet$") as error:
        worker.workflow_allowance(envelope)
    assert SECRET not in str(error.value)


@pytest.mark.parametrize("mode", ["workflow", "workflow_bounded", "pre_release", "stale", "legacy"])
def test_existing_worker_passes_allowance_and_arms_remaining_watchdog(monkeypatch, mode):
    import io
    from types import SimpleNamespace

    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation_worker as worker

    envelope = _workflow_packet_fixture()
    if mode == "pre_release":
        envelope["workflow_execution"]["released_at"] = None
    if mode == "workflow_bounded":
        envelope["config"]["workflow_accounting"] = _accounting_fixture()
    if mode == "stale":
        envelope["workflow_execution"]["deadline"] = 103.0
    if mode == "legacy":
        del envelope["workflow_execution"]
    timers, calls = [], []
    monkeypatch.setattr(worker.sys, "argv", ["worker", "--parent-pid", "12"])
    monkeypatch.setattr(worker.os, "getppid", lambda: 12)
    monkeypatch.setattr(worker.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(prctl=lambda *a: 0))
    monkeypatch.setattr(worker.sys, "stdin", SimpleNamespace(buffer=io.BytesIO((json.dumps(envelope) + "\n").encode())))
    channel = io.StringIO()
    monkeypatch.setattr(worker.sys, "stdout", channel)
    monkeypatch.setattr(worker.time, "time", lambda: 103.0)
    monkeypatch.setattr(worker.time, "monotonic", lambda: 20.0)
    monkeypatch.setattr(worker.signal, "signal", lambda *a: worker.signal.SIG_DFL)
    monkeypatch.setattr(worker.signal, "setitimer", lambda *a: timers.append(a))

    def generate(inputs, progress, **kwargs):
        calls.append(kwargs)
        return {"synthetic": True}

    monkeypatch.setattr(generation, "generate", generate)
    if mode in {"pre_release", "stale"}:
        assert worker.main() == 1
        assert calls == timers == []
        assert SECRET not in channel.getvalue()
        return
    assert worker.main() == 0
    if mode == "legacy":
        assert len(calls) == 1 and "allowance" not in calls[0] and timers == []
        return
    assert len(calls) == 1 and calls[0]["allowance"].max_calls == 1
    assert calls[0]["allowance"].token_cost_bounded == (mode == "workflow_bounded")
    assert calls[0]["allowance"].deadline == 27.0
    assert timers == [(worker.signal.ITIMER_REAL, 7.0), (worker.signal.ITIMER_REAL, 0)]
    assert json.loads(channel.getvalue()) == {"result": {"synthetic": True}}


def _attempt_budget_fixture():
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import GenerationReservation

    return dict(
        reservation=GenerationReservation(
            model_calls=1, model_tokens=1, cost_ceiling_usd=0, runtime_allowance_seconds=10
        ),
        admitted_at=90.0,
        released_at=None,
        released=False,
    )


def foreground_fixture(*, accounting=False):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena.tests.test_environment_workflow_service import contract
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import (
        ForegroundAuthority,
        model_settings_sha256,
    )
    from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

    now = [100.0]
    config = {"api_key": SECRET, "model": "test-model", "base_url": "https://api.openai.com/v1"}
    if accounting:
        config["workflow_accounting"] = _accounting_fixture("test-model")
    profile = {
        "profile_id": "synthetic",
        "billing": "free",
        "settings_sha256": model_settings_sha256(config, billing="free"),
    }
    value = contract().model_dump(mode="json")
    value["execution"]["generation_model"] = profile
    c = type(contract()).model_validate(value)
    scope = dict(database="arena", deployment_id="local", workspace_id="workspace")
    principal = dict(principal="operator", **scope, expires_at=1000.0, revoked=False)
    runs = {
        name: SimpleNamespace(run_id=name, operation_id="op-" + name, contract_json=canonical_json(c))
        for name in ("run-1", "run-2")
    }
    attempts = {}
    db = SimpleNamespace(
        database="arena",
        scope={k: v for k, v in scope.items() if k != "database"},
        get_run=lambda r: runs.get(r),
        get_attempt=lambda f: attempts[f.attempt_id],
    )
    grants = ExecutionGrants(clock=lambda: now[0])
    source = {"config": config, "expires_at": 900.0}
    authority = ForegroundAuthority(
        **scope,
        store=db,
        grants=grants,
        clock=lambda: now[0],
        principal_lookup=lambda p: principal if p == "operator" else None,
        profiles={"synthetic": profile},
        current_config=lambda p: source,
    )
    return SimpleNamespace(
        authority=authority,
        grants=grants,
        now=now,
        source=source,
        principal=principal,
        contract=c,
        attempts=attempts,
        runs=runs,
        profile=profile,
    )


def test_accounting_hash_is_additive_and_rotation_invalidates_grant():
    import hashlib

    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import model_settings_sha256

    f = foreground_fixture()
    config = f.source["config"]
    old_payload = dict(
        version=1, model=config["model"], endpoint=config["base_url"], billing="free", inference_policy=None
    )
    expected = hashlib.sha256(
        json.dumps(old_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    assert model_settings_sha256(config, billing="free") == expected
    f.authority.bind_run("operator", "op-run-1", f.contract, run_id="run-1", catalogue_sha256="c" * 64)
    config["workflow_accounting"] = _accounting_fixture("test-model")
    changed = model_settings_sha256(config, billing="free")
    assert changed != expected
    with pytest.raises(ValueError, match="settings changed"):
        f.authority.require_execute("operator", f.contract, run_id="run-1")
    with pytest.raises(ValueError):
        f.authority.renew_run("operator", f.contract, run_id="run-1")
    f.authority.revoke_run("run-1")
    profile = {**f.profile, "settings_sha256": changed}
    contract = f.contract.model_dump(mode="json")
    contract["execution"]["generation_model"] = profile
    contract = type(f.contract).model_validate(contract)
    f.authority.profiles["synthetic"] = profile
    f.runs["run-1"].contract_json = canonical_json(contract)
    grant = f.authority.bind_run("operator", "op-run-1", contract, run_id="run-1", catalogue_sha256="c" * 64)
    assert f.authority.require_execute("operator", contract, run_id="run-1") == grant
    config["workflow_accounting"]["max_tokens"] += 1
    assert model_settings_sha256(config, billing="free") != changed
    with pytest.raises(ValueError):
        f.authority.require_execute("operator", contract, run_id="run-1")


def test_accounting_admission_binds_each_required_model_role_without_grants():
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import model_settings_sha256

    f = foreground_fixture(accounting=True)
    config = {
        **f.source["config"],
        "model": "assessment-model",
        "workflow_accounting": {**_accounting_fixture("assessment-model"), "max_tokens": 300},
    }
    profile = {
        "profile_id": "assessment",
        "billing": "free",
        "settings_sha256": model_settings_sha256(config, billing="free"),
    }
    value = f.contract.model_dump(mode="json")
    value["execution"]["assessment_model"] = profile
    contract = type(f.contract).model_validate(value)
    f.authority.profiles["assessment"] = profile
    sources = {"synthetic": f.source, "assessment": {"config": config, "expires_at": 900.0}}
    f.authority.current_config = sources.__getitem__
    assert f.authority.require_token_cost_bound("operator", contract, role="assessment")["max_tokens"] == 300
    bounds = f.authority.require_workflow_model_bounds("operator", contract)
    assert bounds["generation"] == _accounting_fixture("test-model")
    assert bounds["assessment"] == config["workflow_accounting"]
    assert not f.grants._records
    with f.authority.mutation_guard():
        config["workflow_accounting"]["max_tokens"] += 1
    with pytest.raises(ValueError, match="settings changed"):
        f.authority.require_workflow_model_bounds("operator", contract)
    assert f.authority.require_token_cost_bound("operator", contract) == bounds["generation"]
    with pytest.raises(ValueError, match="role"):
        f.authority.require_token_cost_bound("operator", contract, role="arbitrary")


def test_accounting_admission_does_not_resolve_unused_assessment_role():
    f = foreground_fixture(accounting=True)
    value = f.contract.model_dump(mode="json")
    value["criteria"][0].update(kind="structural", required_modalities=["scene_graph"])
    contract = type(f.contract).model_validate(value)
    # The fixture's assessment settings are deliberately not an approved profile.
    assert f.authority.require_workflow_model_bounds("operator", contract) == {
        "generation": _accounting_fixture("test-model"),
    }
    assert not f.grants._records


def test_accounting_attestation_does_not_authorize_paid_model_effects():
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import model_settings_sha256

    f = foreground_fixture(accounting=True)
    profile = {
        **f.profile,
        "billing": "paid",
        "settings_sha256": model_settings_sha256(f.source["config"], billing="paid"),
    }
    value = f.contract.model_dump(mode="json")
    value["execution"]["assessment_model"] = profile
    f.authority.profiles[profile["profile_id"]] = profile
    with pytest.raises(ValueError, match="paid model requires"):
        type(f.contract).model_validate(value)
    # Internal unchecked copies must not turn a price assertion into permission either.
    contract = f.contract.model_copy(
        update={
            "execution": f.contract.execution.model_copy(
                update={
                    "assessment_model": type(f.contract.execution.assessment_model).model_validate(profile),
                }
            )
        }
    )
    with pytest.raises(ValueError, match="Paid model permission"):
        f.authority.require_token_cost_bound("operator", contract, role="assessment")
    value["effects"]["allow_paid_models"] = True
    contract = type(f.contract).model_validate(value)
    assert f.authority.require_token_cost_bound("operator", contract, role="assessment") == _accounting_fixture(
        "test-model"
    )
    assert not f.grants._records


@pytest.mark.parametrize("change", ["approval", "settings"])
def test_model_profile_mismatch_has_typed_not_ready_outcome(change):
    f = foreground_fixture()
    if change == "approval":
        f.authority.profiles.clear()
    else:
        f.source["config"]["model"] = "another-model"
    with pytest.raises(ValueError) as error:
        f.authority.require_token_cost_bound("operator", f.contract)
    assert type(error.value).__name__ == "ModelProfileUnavailable"
    assert not f.grants._records


def test_explicit_token_cost_capability_requires_current_approved_attestation():
    f = foreground_fixture()
    with pytest.raises(ValueError, match="attested"):
        f.authority.require_token_cost_bound("operator", f.contract)
    assert not f.grants._records
    f = foreground_fixture(accounting=True)
    assert f.authority.require_token_cost_bound("operator", f.contract) == _accounting_fixture("test-model")
    assert not f.grants._records
    f.source["config"]["workflow_accounting"]["max_tokens"] += 1
    with pytest.raises(ValueError):
        f.authority.require_token_cost_bound("operator", f.contract)


@pytest.mark.parametrize(
    "bound",
    [None, {}, {"version": 1}, _accounting_fixture() | {"extra": SECRET}, _accounting_fixture() | {"model": "foreign"}],
)
def test_private_accounting_shape_rejected_by_hash_and_worker(monkeypatch, bound):
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import model_settings_sha256
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation_worker as worker

    packet = _workflow_packet_fixture()
    packet["config"]["workflow_accounting"] = bound
    monkeypatch.setattr(worker.time, "time", lambda: 103.0)
    for call in (
        lambda: model_settings_sha256(packet["config"], billing="free"),
        lambda: worker.workflow_allowance(packet),
    ):
        with pytest.raises(ValueError) as error:
            call()
        assert SECRET not in str(error.value)


def scene_authority_fixture():
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import model_settings_sha256

    f = foreground_fixture(accounting=True)
    f.assessment = {
        "config": {
            "api_key": "dummy-assessment-secret-987654",
            "model": "assessment-model",
            "base_url": "https://api.openai.com/v1",
            "workflow_accounting": _accounting_fixture("assessment-model"),
        },
        "expires_at": 850.0,
    }
    profile = dict(
        profile_id="assessment",
        billing="free",
        settings_sha256=model_settings_sha256(f.assessment["config"], billing="free"),
    )
    value = f.contract.model_dump(mode="json")
    value["execution"]["assessment_model"] = profile
    f.contract = type(f.contract).model_validate(value)
    f.runs["run-1"].contract_json = canonical_json(f.contract)
    f.authority.profiles["assessment"] = profile
    sources = {"synthetic": f.source, "assessment": f.assessment}
    f.authority.current_config = sources.__getitem__
    return f


@pytest.mark.parametrize("role", ["generation", "assessment"])
def test_fresh_operation_identity_screened_before_any_role_grant(role):
    f = scene_authority_fixture()
    source = f.source if role == "generation" else f.assessment
    with pytest.raises(ValueError, match="Protected credential"):
        f.authority.protect_workflow_contract("operator", f.contract, operation_id=source["config"]["api_key"])
    assert not f.grants._records
    f.authority.protect_workflow_contract("operator", f.contract, operation_id="safe-operation")
    assert not f.grants._records


def test_scene_private_deadline_preserves_shorter_role_lifetime():
    f = scene_authority_fixture()
    a, c = f.authority, f.contract
    f.assessment["expires_at"] = f.now[0] + 10
    snapshot = a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    a.bind_workflow_models("operator", c, run_id="run-1")
    assert hasattr(a, "private_model_deadline"), "private role deadline missing"
    with pytest.raises(ValueError, match="release guard"):
        a.private_model_deadline("operator", c, run_id="run-1", role="assessment")
    with a.release_guard("operator", c, run_id="run-1"):
        deadline = a.private_model_deadline("operator", c, run_id="run-1", role="assessment")
        assert deadline == f.now[0] + 10 < snapshot.expires_at
        f.assessment["expires_at"] = f.now[0] + 5
        assert a.private_model_deadline("operator", c, run_id="run-1", role="assessment") == f.now[0] + 5
        f.assessment["expires_at"] = f.now[0] + 100
        assert a.private_model_deadline("operator", c, run_id="run-1", role="assessment") == deadline


def test_scene_roles_explicit_capture_and_guarded_detached_private_configs():
    f = scene_authority_fixture()
    a, c = f.authority, f.contract
    a.protect_workflow_contract("operator", c)
    assert not f.grants._records
    generation = a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    with pytest.raises(ValueError):
        a.require_scene_execute("operator", c, run_id="run-1")
    assert a.bind_workflow_models("operator", c, run_id="run-1") == generation
    assert a.require_scene_execute("operator", c, run_id="run-1") == generation
    assert len(f.grants._records) == 2
    with pytest.raises(ValueError, match="release guard"):
        a.private_model_config("operator", c, run_id="run-1", role="assessment")
    with a.release_guard("operator", c, run_id="run-1"):
        for role, source in (("generation", f.source), ("assessment", f.assessment)):
            private = a.private_model_config("operator", c, run_id="run-1", role=role)
            assert private == source["config"]
            private["api_key"] = "changed-detached-copy"
            assert a.private_model_config("operator", c, run_id="run-1", role=role) == source["config"]
    assert SECRET not in generation.model_dump_json()
    with pytest.raises(ValueError):
        a.bind_workflow_models("operator", c, run_id="run-1")


@pytest.mark.parametrize("mutation", ["revoke", "close", "renew", "expiry", "principal", "settings"])
def test_scene_role_lifecycle_preserves_scope_and_revokes_all(mutation):
    f = scene_authority_fixture()
    a, c = f.authority, f.contract
    original = a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    a.bind_workflow_models("operator", c, run_id="run-1")
    old_refs = set(f.grants._records)
    if mutation == "renew":
        with a.mutation_guard():
            f.assessment["config"]["api_key"] = "replacement-assessment-secret-456"
            f.source["config"]["api_key"] = "replacement-generation-secret-456"
        renewed = a.renew_run("operator", c, run_id="run-1")
        assert renewed.model_dump(exclude={"grant_ref", "expires_at"}) == original.model_dump(
            exclude={"grant_ref", "expires_at"}
        )
        assert a.require_scene_execute("operator", c, run_id="run-1") == renewed
        assert not old_refs.intersection(f.grants._records)
        assert len(f.grants._records) == 2
        with a.release_guard("operator", c, run_id="run-1"):
            assert a.private_model_config("operator", c, run_id="run-1", role="assessment") == f.assessment["config"]
        return
    if mutation == "revoke":
        a.revoke_run("run-1")
    elif mutation == "close":
        a.close()
    elif mutation == "expiry":
        f.now[0] = original.expires_at
    elif mutation == "principal":
        f.principal["revoked"] = True
    else:
        f.assessment["config"]["model"] = "unapproved-model"
    with pytest.raises(ValueError):
        a.require_scene_execute("operator", c, run_id="run-1")
    if mutation in {"revoke", "close"}:
        assert not f.grants._records


@pytest.mark.parametrize("role", ["generation", "assessment"])
def test_scene_rotation_after_guard_entry_invalidates_private_release(role):
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import model_settings_sha256

    f = scene_authority_fixture()
    a, c = f.authority, f.contract
    a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    a.bind_workflow_models("operator", c, run_id="run-1")
    source = f.source if role == "generation" else f.assessment
    before = model_settings_sha256(source["config"], billing="free")
    with a.release_guard("operator", c, run_id="run-1"):
        with a.mutation_guard():
            source["config"]["api_key"] = "new-dummy-rotated-key-123456"
        assert model_settings_sha256(source["config"], billing="free") == before
        with pytest.raises(ValueError):
            a.private_model_config("operator", c, run_id="run-1", role=role)
    refs = set(f.grants._records)
    a.require_read("operator")
    a.require_submit("operator", "op-run-1", c)
    a.require_workflow_model_bounds("operator", c)
    with pytest.raises(ValueError):
        a.require_scene_execute("operator", c, run_id="run-1")
    assert set(f.grants._records) == refs


@pytest.mark.parametrize("role", ["generation", "assessment"])
def test_fresh_workflow_screening_checks_all_keys_before_issue(monkeypatch, role):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json

    f = scene_authority_fixture()
    a = f.authority
    source = f.source if role == "generation" else f.assessment
    value = f.contract.model_dump(mode="json")
    value["source"]["prompt"] = "prefix/" + source["config"]["api_key"]
    c = type(f.contract).model_validate(value)
    f.runs["run-1"].contract_json = canonical_json(c)
    calls = []
    issue = f.grants.issue

    def traced(*args, **kwargs):
        calls.append(True)
        return issue(*args, **kwargs)

    monkeypatch.setattr(f.grants, "issue", traced)
    with pytest.raises(ValueError) as error:
        a.protect_workflow_contract("operator", c)
    assert source["config"]["api_key"] not in str(error.value)
    assert not calls and not f.grants._records
    if role == "generation":
        with pytest.raises(ValueError):
            a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
        assert not calls and not f.grants._records


@pytest.mark.parametrize("mutation", ["revoke", "close", "renew", "source"])
def test_scene_guard_serializes_all_role_mutations(mutation):
    from threading import Event, Thread

    f = scene_authority_fixture()
    a, c = f.authority, f.contract
    a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    a.bind_workflow_models("operator", c, run_id="run-1")
    started, done = Event(), Event()
    errors = []

    def mutate():
        started.set()
        try:
            if mutation == "revoke":
                a.revoke_run("run-1")
            elif mutation == "close":
                a.close()
            elif mutation == "renew":
                a.renew_run("operator", c, run_id="run-1")
            else:
                with a.mutation_guard():
                    f.assessment["config"]["api_key"] = "rotated-assessment-key-123456"
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    with a.release_guard("operator", c, run_id="run-1"):
        thread = Thread(target=mutate)
        thread.start()
        assert started.wait(2) and not done.wait(0.1)
        assert a.private_model_config("operator", c, run_id="run-1", role="assessment")
    thread.join(2)
    assert done.is_set() and not errors
    with pytest.raises(ValueError, match="release guard"):
        a.private_model_config("operator", c, run_id="run-1", role="generation")


def test_scene_unused_assessment_is_never_resolved():
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json

    f = foreground_fixture()
    value = f.contract.model_dump(mode="json")
    value["criteria"][0].update(kind="structural", required_modalities=["scene_graph"])
    c = type(f.contract).model_validate(value)
    f.runs["run-1"].contract_json = canonical_json(c)
    f.authority.current_config = lambda profile: f.source if profile == "synthetic" else pytest.fail("unused role")
    a = f.authority
    a.protect_workflow_contract("operator", c)
    a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    a.bind_workflow_models("operator", c, run_id="run-1")
    assert len(f.grants._records) == 1
    with a.release_guard("operator", c, run_id="run-1"):
        assert a.private_model_config("operator", c, run_id="run-1", role="generation")
        with pytest.raises(ValueError, match="role"):
            a.private_model_config("operator", c, run_id="run-1", role="assessment")


def test_scene_renewal_cannot_expand_effects_or_partially_replace_grants(monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json

    f = scene_authority_fixture()
    a, c = f.authority, f.contract
    a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    a.bind_workflow_models("operator", c, run_id="run-1")
    refs = set(f.grants._records)
    value = c.model_dump(mode="json")
    value["effects"]["allow_paid_models"] = True
    expanded = type(c).model_validate(value)
    f.runs["run-1"].contract_json = canonical_json(expanded)
    with pytest.raises(ValueError, match="original binding"):
        a.renew_run("operator", expanded, run_id="run-1")
    f.runs["run-1"].contract_json = canonical_json(c)
    issue = f.grants.issue

    def fail_assessment(*args, **kwargs):
        if args[3]["profile_id"] == "assessment":
            raise ValueError("synthetic capacity failure")
        return issue(*args, **kwargs)

    monkeypatch.setattr(f.grants, "issue", fail_assessment)
    with pytest.raises(ValueError, match="capacity"):
        a.renew_run("operator", c, run_id="run-1")
    assert set(f.grants._records) == refs
    assert a.require_scene_execute("operator", c, run_id="run-1")
    for secret in (SECRET, f.assessment["config"]["api_key"]):
        with pytest.raises(ValueError):
            a.protect_public({"proposal": {"evidence": secret}})


@pytest.mark.parametrize("damage", ["assessment_expiry", "foreign_principal", "foreign_run", "foreign_contract"])
def test_scene_private_release_rechecks_exact_current_scope(damage):
    f = scene_authority_fixture()
    a, c = f.authority, f.contract
    a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    a.bind_workflow_models("operator", c, run_id="run-1")
    with a.release_guard("operator", c, run_id="run-1"):
        principal, run_id, contract = "operator", "run-1", c
        if damage == "assessment_expiry":
            f.assessment["expires_at"] = f.now[0]
        elif damage == "foreign_principal":
            principal = "foreign"
        elif damage == "foreign_run":
            run_id = "run-2"
        else:
            contract = c.model_copy(update={"source": c.source.model_copy(update={"prompt": "changed"})})
        with pytest.raises(ValueError):
            a.private_model_config(principal, contract, run_id=run_id, role="assessment")


def test_foreground_explicit_binding_expiry_and_rotation(monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AuthorizationSnapshot
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation

    monkeypatch.setattr(generation, "configuration", lambda: pytest.fail("ambient config lookup"))
    f = foreground_fixture()
    a, c = f.authority, f.contract
    a.require_read("operator")
    a.require_submit("operator", "op-run-1", c)
    assert not f.grants._records
    with pytest.raises(ValueError):
        a.require_execute("operator", c, run_id="run-1")
    first = a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    second = a.bind_run("operator", "op-run-2", c, run_id="run-2", catalogue_sha256="c" * 64)
    assert isinstance(first, AuthorizationSnapshot)
    assert first.grant_ref != second.grant_ref
    assert first.expires_at == 280.0
    assert a.require_execute("operator", c, run_id="run-1") == first
    f.source["config"] = {**f.source["config"], "api_key": "rotated-dummy-secret-123"}
    with pytest.raises(ValueError):
        a.require_execute("operator", c, run_id="run-1")
    renewed = a.renew_run("operator", c, run_id="run-1")
    assert renewed.grant_ref != first.grant_ref
    f.grants.revoke(renewed.grant_ref)
    with pytest.raises(ValueError):
        a.require_execute("operator", c, run_id="run-1")
    f.now[0] = 280.0
    before = set(f.grants._records)
    a.require_read("operator")
    a.require_submit("operator", "op-run-1", c)
    assert set(f.grants._records) == before
    with pytest.raises(ValueError):
        a.require_execute("operator", c, run_id="run-2")
    f.principal["revoked"] = True
    with pytest.raises(ValueError):
        a.require_read("operator")


@pytest.mark.parametrize("accounting", [False, True])
def test_foreground_exact_fence_and_private_packet(accounting):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json

    f = foreground_fixture(accounting=accounting)
    a, c = f.authority, f.contract
    snapshot = a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    fence = AttemptFence(
        run_id="run-1", intent_id="intent", attempt_id="attempt", generation=1, owner_id="owner", owner_epoch=1
    )
    registration = WorkerRegistration(
        registration_id="registered", fence=fence, host="host", boot="boot", pid=10, pgid=10, sid=10, start_ticks=100
    )
    f.attempts["attempt"] = SimpleNamespace(
        fence=fence, registration=registration, authorization=snapshot, contract_json=canonical_json(c)
    )
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import GenerationReservation

    attempt = f.attempts["attempt"]
    attempt.reservation = GenerationReservation(
        model_calls=1, model_tokens=1, cost_ceiling_usd=0, runtime_allowance_seconds=10
    )
    attempt.admitted_at = 90.0
    attempt.released_at = None
    attempt.released = False
    assert c.budget.max_model_calls > attempt.reservation.model_calls
    packet = a.private_envelope("operator", c, fence, registration)
    assert packet.endswith(b"\n") and len(packet) <= 512 * 1024
    assert json.loads(packet) == {
        "inputs": {
            "operation": "new",
            "prompt": c.source.prompt,
            "retrieval_policy": "allow_fallback",
            "execution_catalogue_sha256": "c" * 64,
        },
        "config": f.source["config"],
        "graph_config": None,
        "workflow_execution": {
            "version": 1,
            "fence": fence.model_dump(mode="json"),
            "registration": registration.model_dump(mode="json"),
            "reservation": attempt.reservation.model_dump(mode="json"),
            "admitted_at": 90.0,
            "released_at": None,
            "deadline": min(90 + c.budget.total_deadline_seconds, snapshot.expires_at),
        },
    }
    attempt.released_at = 100.0
    attempt.released = True
    released = json.loads(a.private_envelope("operator", c, fence, registration))["workflow_execution"]
    assert released["reservation"]["model_calls"] == 1
    assert released["released_at"] == 100.0 and released["deadline"] == 110.0
    for field, value in (("run_id", "run-2"), ("owner_epoch", 2), ("generation", 2)):
        foreign = fence.model_copy(update={field: value})
        with pytest.raises(ValueError):
            a.require_execute("operator", c, run_id="run-1", fence=foreign)
    with pytest.raises(ValueError):
        a.private_envelope("operator", c, fence, registration.model_copy(update={"pid": 11}))
    with pytest.raises(ValueError):
        a.protect_public({"value": SECRET})
    f.source["expires_at"] = 100.0
    with pytest.raises(ValueError):
        a.private_envelope("operator", c, fence, registration)


def test_foreground_renewed_registered_fence_uses_current_grant():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json

    f = foreground_fixture()
    a, c = f.authority, f.contract
    old = a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    fence = AttemptFence(
        run_id="run-1", intent_id="intent", attempt_id="attempt", generation=1, owner_id="owner", owner_epoch=1
    )
    reg = WorkerRegistration(
        registration_id="registered", fence=fence, host="host", boot="boot", pid=10, pgid=10, sid=10, start_ticks=100
    )
    f.attempts["attempt"] = SimpleNamespace(
        fence=fence, registration=reg, authorization=old, contract_json=canonical_json(c), **_attempt_budget_fixture()
    )
    f.source["config"] = {**f.source["config"], "api_key": "rotated-dummy-secret-123"}
    renewed = a.renew_run("operator", c, run_id="run-1")
    assert renewed.grant_ref != old.grant_ref
    assert old.grant_ref not in f.grants._records
    assert json.loads(a.private_envelope("operator", c, fence, reg))["config"] == f.source["config"]
    assert a.require_execute("operator", c, run_id="run-1", fence=fence) == renewed
    f.source["config"]["model"] = "changed-model"
    with pytest.raises(ValueError):
        a.renew_run("operator", c, run_id="run-1")


@pytest.mark.parametrize("mutation", ["revoke", "renew", "source", "close"])
def test_foreground_release_guard_serializes_mutation(mutation):
    from threading import Event, Thread

    f = foreground_fixture()
    a, c = f.authority, f.contract
    a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    started, finished = Event(), Event()
    errors = []

    def mutate():
        started.set()
        try:
            if mutation == "revoke":
                a.revoke_run("run-1")
            elif mutation == "renew":
                a.renew_run("operator", c, run_id="run-1")
            elif mutation == "close":
                a.close()
            else:
                with a.mutation_guard():
                    f.principal["revoked"] = True
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    # Guard validates registration; reuse the exact registered fixture shape.
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json

    fence = AttemptFence(
        run_id="run-1", intent_id="intent", attempt_id="attempt", generation=1, owner_id="owner", owner_epoch=1
    )
    reg = WorkerRegistration(
        registration_id="registered", fence=fence, host="host", boot="boot", pid=10, pgid=10, sid=10, start_ticks=100
    )
    f.attempts["attempt"] = SimpleNamespace(
        fence=fence,
        registration=reg,
        authorization=a.require_execute("operator", c, run_id="run-1"),
        contract_json=canonical_json(c),
        **_attempt_budget_fixture(),
    )
    with a.release_guard("operator", c, fence, reg):
        thread = Thread(target=mutate)
        thread.start()
        assert started.wait(2)
        assert not finished.wait(0.1), "mutation crossed the guarded send boundary"
        assert a.private_envelope("operator", c, fence, reg)
    thread.join(2)
    assert finished.is_set() and not errors
    if mutation != "renew":
        sent = []
        with pytest.raises(ValueError):
            with a.release_guard("operator", c, fence, reg):
                sent.append(True)
        assert sent == []


def test_foreground_owner_mark_cannot_succeed_after_concurrent_unlock(tmp_path, monkeypatch):
    from threading import Event, Thread

    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease

    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    lease = ForegroundOwnerLease(private, run_id="run", principal="operator", cleanup_verified=lambda r, e: True)
    entered, continue_release, marked = Event(), Event(), Event()
    original = lease._lease.__class__.__exit__
    errors = []

    def paused_exit(self, *args):
        entered.set()
        assert continue_release.wait(2)
        return original(self, *args)

    monkeypatch.setattr(lease._lease.__class__, "__exit__", paused_exit)
    release = Thread(target=lease.release_never_prepared)
    release.start()
    assert entered.wait(2)

    def mark():
        try:
            lease.mark_prepared("registration")
            marked.set()
        except ValueError:
            errors.append("released")

    marker = Thread(target=mark)
    marker.start()
    crossed = marked.wait(0.1)
    continue_release.set()
    release.join(2)
    marker.join(2)
    assert not crossed and not marked.is_set() and errors == ["released"]


def test_foreground_owner_accepts_fence_before_registration(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration
    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease

    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    verified = []
    lease = ForegroundOwnerLease(
        private,
        run_id="run",
        principal="operator",
        cleanup_verified=lambda r, e: verified.append((r, e)) is None and e == "clean",
    )
    fence = AttemptFence(
        run_id="run", intent_id="intent", attempt_id="attempt", generation=1, owner_id=lease.owner_id, owner_epoch=1
    )
    lease.mark_prepared(fence)
    with pytest.raises(ValueError):
        lease.release_never_prepared()
    reg = WorkerRegistration(
        registration_id="registered", fence=fence, host="host", boot="boot", pid=10, pgid=10, sid=10, start_ticks=100
    )
    with pytest.raises(ValueError):
        lease.release_after_cleanup(reg, "unknown")
    lease.require_held("run", "operator")
    lease.release_after_cleanup(reg, "clean")
    assert verified == [(reg, "unknown"), (reg, "clean")]


@pytest.mark.parametrize("prepare_fails", [False, True])
def test_foreground_coordinator_real_adapters_keep_lease_until_proof(tmp_path, prepare_fails):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        AttemptFence,
        GenerationReservation,
        WorkerRegistration,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
        GenerationCoordinator,
        PreparedWorker,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import (
        DependencyGate,
        DependencyResult,
        ReadinessClock,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence
    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
    from isaaclab_arena_examples.agentic_environment_generation.web_api.runtime import FileLease

    f = foreground_fixture()
    a, c = f.authority, f.contract
    old = a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    evidence = []
    lease = ForegroundOwnerLease(
        private,
        run_id="run-1",
        principal="operator",
        cleanup_verified=lambda r, e: bool(evidence) and e == evidence[0] and e.registration == r,
    )
    fence = AttemptFence(
        run_id="run-1", intent_id="intent", attempt_id="attempt", generation=1, owner_id=lease.owner_id, owner_epoch=1
    )
    run = f.runs["run-1"]
    run.state, run.version = "pending", 1
    store = a.store
    store.dependency_instances = {}
    store.reserve_generation = lambda *args, **kwargs: "intent"
    store.begin_owner = lambda owner: 1
    store.claim_intent = lambda *args: fence
    calls = []

    def register(actual, registration):
        assert actual == fence
        f.attempts["attempt"] = SimpleNamespace(
            fence=fence,
            registration=registration,
            authorization=old,
            contract_json=run.contract_json,
            **_attempt_budget_fixture(),
        )
        with a.mutation_guard():
            f.source["config"] = {**f.source["config"], "api_key": "rotated-dummy-secret-123"}
        a.renew_run("operator", c, run_id="run-1")

    def release(actual, registration_id, auth, **kwargs):
        assert actual == fence and auth.grant_ref != old.grant_ref
        calls.append("release")
        return True

    store.register_worker, store.release_attempt = register, release

    class Worker:
        def prepare(self, actual, request, **kwargs):
            assert actual == fence and lease._prepared == fence
            with pytest.raises(ValueError):
                lease.release_never_prepared()
            if prepare_fails:
                raise OSError("preparation uncertain")
            reg = WorkerRegistration(
                registration_id="registered",
                fence=fence,
                host="host",
                boot="boot",
                pid=10,
                pgid=10,
                sid=10,
                start_ticks=100,
            )
            return PreparedWorker(reg, object())

        def send(self, prepared, packet, **kwargs):
            assert json.loads(packet)["config"] == f.source["config"]
            calls.append("send")

        def stop_owned(self, prepared, **kwargs):
            result = CleanupEvidence(
                registration=prepared.registration,
                evidence_ref="cleanup",
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            )
            evidence.append(result)
            return result

    def clock():
        return f.now[0]

    gate = DependencyGate(
        lambda req, timeout: DependencyResult(
            req.dependency_id, "passed", req.profile_sha256, profile_id=req.profile_id, instance_id=req.instance_id
        ),
        clock=clock,
    )
    coordinator = GenerationCoordinator(
        store,
        a,
        gate,
        Worker(),
        run_id="run-1",
        principal="operator",
        lease=lease,
        readiness_clock=ReadinessClock.capture(monotonic=clock, wall_clock=clock),
    )
    reservation = GenerationReservation(
        model_calls=1, model_tokens=100, cost_ceiling_usd=0.0, runtime_allowance_seconds=5.0
    )

    def dispatch():
        return coordinator.dispatch("operator", expected_version=1, decision_id="decision", reservation=reservation)

    if prepare_fails:
        with pytest.raises(DispatchIncomplete):
            dispatch()
        assert calls == [] and not evidence
    else:
        handle = dispatch()
        assert dispatch() is handle and calls == ["release", "send"]
    lease.require_held("run-1", "operator")
    with pytest.raises(ValueError):
        lease.release_never_prepared()
    with pytest.raises(RuntimeError):
        with FileLease(private / "foreground.lock"):
            pass
    if not prepare_fails:
        coordinator._stop()
        lease.release_after_cleanup(handle.prepared.registration, evidence[0])
        with FileLease(private / "foreground.lock"):
            pass
    # A failed preparation deliberately retains the lease: no invented cleanup.


def test_foreground_owner_real_lock_lifetime_and_symlink(tmp_path):
    import os

    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
    from isaaclab_arena_examples.agentic_environment_generation.web_api.runtime import FileLease

    assert os.geteuid() != 0, "isolated backend must run non-root"
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    lease = ForegroundOwnerLease(
        private, run_id="run", principal="operator", cleanup_verified=lambda r, e: e == "clean"
    )
    lease.require_held("run", "operator")
    with pytest.raises(RuntimeError):
        with FileLease(private / "foreground.lock"):
            pass
    with pytest.raises(ValueError):
        lease.require_held("foreign", "operator")
    lease.mark_prepared("registration")
    with pytest.raises(ValueError):
        lease.release_never_prepared()
    with pytest.raises(ValueError):
        lease.release_after_cleanup("foreign", "clean")
    with pytest.raises(ValueError):
        lease.release_after_cleanup("registration", "unknown")
    with pytest.raises(RuntimeError):
        with FileLease(private / "foreground.lock"):
            pass
    lease.release_after_cleanup("registration", "clean")
    with FileLease(private / "foreground.lock"):
        pass
    link = tmp_path / "link"
    link.symlink_to(private, target_is_directory=True)
    with pytest.raises((ValueError, RuntimeError)):
        ForegroundOwnerLease(link, run_id="run", principal="operator", cleanup_verified=lambda r, e: True)
    private.chmod(0o755)
    with pytest.raises((ValueError, RuntimeError)):
        ForegroundOwnerLease(private, run_id="run", principal="operator", cleanup_verified=lambda r, e: True)
    assert private.stat().st_mode & 0o777 == 0o755


def test_foreground_foreign_run_fence_never_reads_foreign_attempt():
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence

    f = foreground_fixture()
    f.authority.bind_run("operator", "op-run-1", f.contract, run_id="run-1", catalogue_sha256="c" * 64)
    f.authority.store.get_attempt = lambda fence: pytest.fail("foreign attempt lookup")
    foreign = AttemptFence(
        run_id="run-2", intent_id="intent", attempt_id="attempt", generation=1, owner_id="owner", owner_epoch=1
    )
    with pytest.raises(ValueError):
        f.authority.require_execute("operator", f.contract, run_id="run-1", fence=foreign)


@pytest.mark.parametrize("change", [{"revoked": True}, {"expires_at": 100.0}, {"workspace_id": "foreign"}])
def test_foreground_principal_lifecycle_checks(change):
    f = foreground_fixture()
    f.principal.update(change)
    with pytest.raises(ValueError):
        f.authority.require_read("operator")
    assert not f.grants._records


def test_foreground_checks_do_not_consult_private_source_and_frozen_profile_cannot_change():
    f = foreground_fixture()
    f.authority.current_config = lambda profile: pytest.fail("private source lookup during read/replay")
    f.authority.require_read("operator")
    f.authority.require_submit("operator", "op-run-1", f.contract)
    assert not f.grants._records
    f = foreground_fixture()
    f.authority.bind_run("operator", "op-run-1", f.contract, run_id="run-1", catalogue_sha256="c" * 64)
    f.source["config"]["model"] = "changed-model"
    with pytest.raises(ValueError):
        f.authority.renew_run("operator", f.contract, run_id="run-1")
