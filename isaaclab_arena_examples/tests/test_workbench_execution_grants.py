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


def foreground_fixture():
    from types import SimpleNamespace

    from isaaclab_arena.tests.test_environment_workflow_service import contract
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json
    from isaaclab_arena_examples.agentic_environment_generation.foreground_authorization import (
        ForegroundAuthority, model_settings_sha256,
    )
    from isaaclab_arena_examples.agentic_environment_generation.web_api.execution_grants import ExecutionGrants

    now = [100.0]
    config = {"api_key": SECRET, "model": "test-model", "base_url": "https://api.openai.com/v1"}
    profile = {"profile_id": "synthetic", "billing": "free",
               "settings_sha256": model_settings_sha256(config, billing="free")}
    value = contract().model_dump(mode="json")
    value["execution"]["generation_model"] = profile
    c = type(contract()).model_validate(value)
    scope = dict(database="arena", deployment_id="local", workspace_id="workspace")
    principal = dict(principal="operator", **scope, expires_at=1000.0, revoked=False)
    runs = {name: SimpleNamespace(run_id=name, operation_id="op-" + name, contract_json=canonical_json(c))
            for name in ("run-1", "run-2")}
    attempts = {}
    db = SimpleNamespace(database="arena", scope={k: v for k, v in scope.items() if k != "database"},
                         get_run=lambda r: runs.get(r), get_attempt=lambda f: attempts[f.attempt_id])
    grants = ExecutionGrants(clock=lambda: now[0])
    source = {"config": config, "expires_at": 900.0}
    authority = ForegroundAuthority(**scope, store=db, grants=grants, clock=lambda: now[0],
                                   principal_lookup=lambda p: principal if p == "operator" else None,
                                   profiles={"synthetic": profile}, current_config=lambda p: source)
    return SimpleNamespace(authority=authority, grants=grants, now=now, source=source, principal=principal,
                           contract=c, attempts=attempts, runs=runs, profile=profile)


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


def test_foreground_exact_fence_and_private_packet():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, WorkerRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json

    f = foreground_fixture()
    a, c = f.authority, f.contract
    snapshot = a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    fence = AttemptFence(run_id="run-1", intent_id="intent", attempt_id="attempt", generation=1,
                         owner_id="owner", owner_epoch=1)
    registration = WorkerRegistration(registration_id="registered", fence=fence, host="host", boot="boot",
                                      pid=10, pgid=10, sid=10, start_ticks=100)
    f.attempts["attempt"] = SimpleNamespace(fence=fence, registration=registration,
                                          authorization=snapshot, contract_json=canonical_json(c))
    packet = a.private_envelope("operator", c, fence, registration)
    assert packet.endswith(b"\n") and len(packet) <= 512 * 1024
    assert json.loads(packet) == {
        "inputs": {"operation": "new", "prompt": c.source.prompt, "retrieval_policy": "allow_fallback",
                   "execution_catalogue_sha256": "c" * 64},
        "config": f.source["config"], "graph_config": None,
    }
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
    fence = AttemptFence(run_id="run-1", intent_id="intent", attempt_id="attempt", generation=1,
                         owner_id="owner", owner_epoch=1)
    reg = WorkerRegistration(registration_id="registered", fence=fence, host="host", boot="boot",
                             pid=10, pgid=10, sid=10, start_ticks=100)
    f.attempts["attempt"] = SimpleNamespace(fence=fence, registration=reg, authorization=old,
                                          contract_json=canonical_json(c))
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
    fence = AttemptFence(run_id="run-1", intent_id="intent", attempt_id="attempt", generation=1,
                         owner_id="owner", owner_epoch=1)
    reg = WorkerRegistration(registration_id="registered", fence=fence, host="host", boot="boot",
                             pid=10, pgid=10, sid=10, start_ticks=100)
    f.attempts["attempt"] = SimpleNamespace(fence=fence, registration=reg,
        authorization=a.require_execute("operator", c, run_id="run-1"), contract_json=canonical_json(c))
    with a.release_guard("operator", c, fence, reg):
        thread = Thread(target=mutate)
        thread.start()
        assert started.wait(2)
        assert not finished.wait(.1), "mutation crossed the guarded send boundary"
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
    crossed = marked.wait(.1)
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
    lease = ForegroundOwnerLease(private, run_id="run", principal="operator",
        cleanup_verified=lambda r, e: verified.append((r, e)) is None and e == "clean")
    fence = AttemptFence(run_id="run", intent_id="intent", attempt_id="attempt", generation=1,
                         owner_id=lease.owner_id, owner_epoch=1)
    lease.mark_prepared(fence)
    with pytest.raises(ValueError):
        lease.release_never_prepared()
    reg = WorkerRegistration(registration_id="registered", fence=fence, host="host", boot="boot",
                             pid=10, pgid=10, sid=10, start_ticks=100)
    with pytest.raises(ValueError):
        lease.release_after_cleanup(reg, "unknown")
    lease.require_held("run", "operator")
    lease.release_after_cleanup(reg, "clean")
    assert verified == [(reg, "unknown"), (reg, "clean")]


@pytest.mark.parametrize("prepare_fails", [False, True])
def test_foreground_coordinator_real_adapters_keep_lease_until_proof(tmp_path, prepare_fails):
    from types import SimpleNamespace
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import AttemptFence, GenerationReservation, WorkerRegistration
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import GenerationCoordinator, PreparedWorker, DispatchIncomplete
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate, DependencyResult, ReadinessClock
    from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence
    from isaaclab_arena_examples.agentic_environment_generation.foreground_owner import ForegroundOwnerLease
    from isaaclab_arena_examples.agentic_environment_generation.web_api.runtime import FileLease

    f = foreground_fixture()
    a, c = f.authority, f.contract
    old = a.bind_run("operator", "op-run-1", c, run_id="run-1", catalogue_sha256="c" * 64)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    evidence = []
    lease = ForegroundOwnerLease(private, run_id="run-1", principal="operator",
        cleanup_verified=lambda r, e: bool(evidence) and e == evidence[0] and e.registration == r)
    fence = AttemptFence(run_id="run-1", intent_id="intent", attempt_id="attempt", generation=1,
                         owner_id=lease.owner_id, owner_epoch=1)
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
        f.attempts["attempt"] = SimpleNamespace(fence=fence, registration=registration,
            authorization=old, contract_json=run.contract_json)
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
            reg = WorkerRegistration(registration_id="registered", fence=fence, host="host", boot="boot",
                                     pid=10, pgid=10, sid=10, start_ticks=100)
            return PreparedWorker(reg, object())

        def send(self, prepared, packet, **kwargs):
            assert json.loads(packet)["config"] == f.source["config"]
            calls.append("send")

        def stop_owned(self, prepared, **kwargs):
            result = CleanupEvidence(registration=prepared.registration, evidence_ref="cleanup",
                observation="owned_process_group_stopped", remote_effects="unknown")
            evidence.append(result)
            return result

    clock = lambda: f.now[0]
    gate = DependencyGate(lambda req, timeout: DependencyResult(req.dependency_id, "passed",
        req.profile_sha256, profile_id=req.profile_id, instance_id=req.instance_id), clock=clock)
    coordinator = GenerationCoordinator(store, a, gate, Worker(), run_id="run-1", principal="operator",
        lease=lease, readiness_clock=ReadinessClock.capture(monotonic=clock, wall_clock=clock))
    reservation = GenerationReservation(model_calls=1, model_tokens=100, cost_ceiling_usd=0.0,
                                        runtime_allowance_seconds=5.0)
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
    lease = ForegroundOwnerLease(private, run_id="run", principal="operator", cleanup_verified=lambda r, e: e == "clean")
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
    foreign = AttemptFence(run_id="run-2", intent_id="intent", attempt_id="attempt", generation=1,
                           owner_id="owner", owner_epoch=1)
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
