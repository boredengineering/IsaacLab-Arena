# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Application composition contracts; every external port is synthetic here."""

import json

import pytest

from isaaclab_arena.agentic_environment_generation.workflow.contracts import parse_contract
from isaaclab_arena.agentic_environment_generation.workflow.readiness import DependencyGate, DependencyResult


@pytest.mark.parametrize(
    "case", ["valid", "denied", "missing_attempt", "foreign_run", "foreign_principal", "changed_contract"]
)
def test_recovery_read_is_authenticated_and_never_resolves_execution(case):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []
    run = SimpleNamespace(run_id="run", contract_json="retained frozen contract")
    attempt = SimpleNamespace(
        fence=SimpleNamespace(run_id="other" if case == "foreign_run" else "run"),
        authorization=SimpleNamespace(principal="other" if case == "foreign_principal" else "creator"),
        contract_json="different" if case == "changed_contract" else run.contract_json,
    )
    owner = SimpleNamespace(owner_id="original", owner_epoch=1, dirty=True)

    def require_read(principal):
        calls.append("read_authority")
        assert principal == "creator"
        if case == "denied":
            raise PermissionError("read denied")

    def forbidden(*args, **kwargs):
        pytest.fail("recovery read must not probe, resolve grants, or execute")

    store = SimpleNamespace(
        get_run=lambda run_id: calls.append("run") or run,
        get_generation_attempt=lambda run_id: calls.append("attempt")
        or (None if case == "missing_attempt" else attempt),
        get_owner=lambda: calls.append("owner") or owner,
    )
    authority = SimpleNamespace(
        require_read=require_read, require_submit=forbidden, require_execute=forbidden, private_envelope=forbidden
    )
    service = WorkflowService(store, authority, SimpleNamespace(check=forbidden), validate_support=forbidden)
    if case == "valid":
        assert service.read_generation_recovery("creator", "run") == (run, attempt, owner)
        assert calls == ["read_authority", "run", "attempt", "owner"]
    else:
        with pytest.raises(PermissionError if case == "denied" else ValueError):
            service.read_generation_recovery("creator", "run")
        assert calls == (["read_authority"] if case == "denied" else ["read_authority", "run", "attempt"])


def contract(*, policy=False, existing=False):
    profile = {"profile_id": "synthetic", "settings_sha256": "a" * 64}
    criterion = {
        "criterion_id": "visible",
        "kind": "visual",
        "evidence_producer": "visual-v1",
        "requirement": "required",
        "evaluator_version": "1",
        "required_modalities": ["rgb"],
        "coordinate_frames": ["external_camera"],
        "observation_window": {"start_step": 0, "end_step": 1},
        "rubric": "Target is visible",
        "subjects": ["banana"],
        "limit": {"operator": "eq", "value": 1.0, "unit": "boolean"},
    }
    criteria = [criterion]
    if policy:
        criteria.append({
            **criterion,
            "criterion_id": "policy",
            "kind": "policy",
            "required_modalities": ["policy_rollout"],
            "evidence_producer": "policy-v1",
        })
    return parse_contract(
        json.dumps({
            "schema_version": "1",
            "source": (
                {"kind": "existing", "identity": "candidate-1", "content": "opaque-yaml"}
                if existing
                else {"kind": "new", "prompt": "Banana on maple table"}
            ),
            "criteria": criteria,
            "preserved": [],
            "allowed_interventions": [],
            "execution": {
                "generation_model": {**profile, "billing": "free"},
                "assessment_model": {**profile, "billing": "free"},
                "runtime": profile,
                "database": profile,
                "policy": profile if policy else None,
                "capture": profile,
                "seed": 1,
                "timestep_seconds": 0.01,
                "decimation": 1,
                "dcrg": None,
            },
            "budget": {
                "max_candidates": 2,
                "max_revisions": 1,
                "max_runtime_seconds": 60.0,
                "max_model_calls": 8,
                "max_model_tokens": 10000,
                "max_cost_usd": 1.0,
                "max_realizations": 2,
                "max_steps": 100,
                "max_observations": 2,
                "max_policy_episodes": 2 if policy else 0,
                "max_policy_steps": 100 if policy else 0,
                "per_operation_timeout_seconds": 10.0,
                "total_deadline_seconds": 60.0,
            },
            "effects": {
                "allow_paid_models": False,
                "allow_runtime": True,
                "allow_database_reads": False,
                "allow_operational_writes": True,
                "allow_publication": False,
            },
        })
    )


def test_full_policy_request_checks_policy_before_generation_factory():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

    calls = []

    def probe(required, timeout):
        calls.append(required.dependency_id)
        return DependencyResult(
            required.dependency_id,
            "unavailable" if required.dependency_id == "policy" else "passed",
            required.profile_sha256,
            profile_id=required.profile_id,
        )

    gate = DependencyGate(probe)
    report, _ = gate.execute(
        required_dependencies(contract(policy=True)), lambda: calls.append("initialization_ping"), timeout_s=5
    )
    assert report.blockers == ("policy",)
    assert "initialization_ping" not in calls
    assert {"runtime", "neo4j", "generation_model", "assessment_model", "capture", "gpu", "policy"} == set(calls)


def test_scene_only_positive_control_does_not_require_policy():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

    calls = []

    def probe(required, timeout):
        calls.append(required.dependency_id)
        return DependencyResult(
            required.dependency_id, "passed", required.profile_sha256, profile_id=required.profile_id
        )

    report, _ = DependencyGate(probe).execute(
        required_dependencies(contract()), lambda: calls.append("initialization_ping"), timeout_s=5
    )
    assert report.ready
    assert "policy" not in calls
    assert calls[-1] == "initialization_ping" and calls.count("initialization_ping") == 1


def test_existing_verification_without_repair_does_not_require_generation():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

    names = {item.dependency_id for item in required_dependencies(contract(existing=True))}
    assert "generation_model" not in names and "assessment_model" in names


@pytest.mark.parametrize("unavailable", ["runtime", "neo4j", "generation_model", "assessment_model", "capture", "gpu"])
def test_each_required_scene_dependency_blocks_all_model_construction(unavailable):
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

    calls = []

    def probe(required, timeout):
        return DependencyResult(
            required.dependency_id,
            "unavailable" if required.dependency_id == unavailable else "passed",
            required.profile_sha256,
            profile_id=required.profile_id,
        )

    report, _ = DependencyGate(probe).execute(
        required_dependencies(contract()), lambda: calls.append("initialization_ping"), timeout_s=5
    )
    assert report.blockers == (unavailable,) and calls == []


def test_probe_timeout_blocks_construction_without_exception_leakage():
    def probe(required, timeout):
        raise TimeoutError("synthetic-private-detail")

    from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

    calls = []
    report, _ = DependencyGate(probe).execute(
        required_dependencies(contract()), lambda: calls.append("initialization_ping"), timeout_s=5
    )
    assert not report.ready and calls == []
    assert all(item.code == "probe_timeout" for item in report.results)
    assert "synthetic-private-detail" not in repr(report)


@pytest.mark.parametrize("allow_writes", [False, True])
def test_exact_submission_replay_skips_resolution_probes_and_execution_authority(allow_writes):
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []
    retained = object()

    class Store:
        def lookup_submission(self, operation_id, request_json):
            calls.append("lookup")
            return retained

    class Authority:
        def require_read(self, principal):
            calls.append("read_authority")

        def require_submit(self, principal, operation_id, request):
            raise AssertionError("replay must not capture execution authority")

    def forbidden(*args):
        raise AssertionError("replay must not resolve profiles, probe or dispatch")

    service = WorkflowService(Store(), Authority(), DependencyGate(forbidden), validate_support=forbidden)
    raw = contract().model_dump(mode="json")
    raw["effects"]["allow_operational_writes"] = allow_writes
    result = service.submit("local-principal", "operation-1", json.dumps(raw))
    assert result.run is retained and result.disposition == "retained"
    assert calls == ["read_authority", "lookup"]


@pytest.mark.parametrize("ready", [False, True])
def test_fresh_admission_checks_support_authority_and_whole_readiness_before_store(ready):
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []
    accepted = object()

    class Store:
        def lookup_submission(self, operation_id, request_json):
            calls.append("lookup")

        def admit(self, operation_id, request_json, contract_json, max_pending):
            calls.append("admit")
            assert operation_id == "operation-1" and request_json == contract_json and max_pending == 1
            return accepted

    class Authority:
        def require_read(self, principal):
            calls.append("read_authority")

        def require_submit(self, principal, operation_id, request):
            calls.append("submit_authority")

    def supported(request):
        calls.append("supported")

    def probe(required, timeout):
        calls.append("probe:" + required.dependency_id)
        return DependencyResult(
            required.dependency_id,
            "passed" if ready else "unavailable",
            required.profile_sha256,
            profile_id=required.profile_id,
        )

    service = WorkflowService(Store(), Authority(), DependencyGate(probe), validate_support=supported)
    result = service.submit("local-principal", "operation-1", json.dumps(contract().model_dump(mode="json")))
    assert calls[:4] == ["read_authority", "lookup", "supported", "submit_authority"]
    assert result.disposition == ("accepted" if ready else "dependencies_not_ready")
    assert result.run is (accepted if ready else None)
    assert result.readiness.ready is ready
    assert ("admit" in calls) is ready
    if ready:
        assert calls[-2:] == ["submit_authority", "admit"]


def test_fresh_submission_without_operational_write_permission_stops_before_probes():
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []

    class Store:
        def lookup_submission(self, *args):
            return None

        def admit(self, *args):
            calls.append("write")

    class Authority:
        def require_read(self, principal):
            pass

        def require_submit(self, principal, operation_id, request):
            calls.append("submit_authority")

    def probe(*args):
        calls.append("probe")

    raw = contract().model_dump(mode="json")
    raw["effects"]["allow_operational_writes"] = False
    service = WorkflowService(Store(), Authority(), DependencyGate(probe), validate_support=lambda request: None)
    with pytest.raises(ValueError, match="operational_writes_not_permitted"):
        service.submit("principal", "operation-1", json.dumps(raw))
    assert calls == []


@pytest.mark.parametrize("operation_id", [None, "", True, [], "a" * 129, "a/b", " a", "a\n", "é", "-a"])
def test_invalid_operation_id_stops_after_read_auth_before_any_io(operation_id):
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []

    class Authority:
        def require_read(self, principal):
            calls.append("read")

    class Store:
        def lookup_submission(self, *args):
            calls.append("lookup")
            raise AssertionError("invalid operation must not reach store")

    service = WorkflowService(Store(), Authority(), None, validate_support=None)
    with pytest.raises(ValueError, match="operation"):
        service.submit("principal", operation_id, json.dumps(contract().model_dump(mode="json")))
    assert calls == ["read"]


def test_frozen_profile_ids_propagate_separately_from_instance_ids():
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import required_dependencies

    requests = required_dependencies(contract(policy=True))
    assert all(item.profile_id == "synthetic" and item.instance_id is None for item in requests)


def test_revoke_during_probe_blocks_admission():
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    revoked = []

    class Authority:
        def require_read(self, principal):
            pass

        def require_submit(self, principal, operation_id, request):
            if revoked:
                raise PermissionError("revoked")

    class Store:
        def lookup_submission(self, *args):
            return None

        def admit(self, *args):
            pytest.fail("revoked request admitted")

    def probe(required, timeout):
        revoked.append(True)
        return DependencyResult(
            required.dependency_id, "passed", required.profile_sha256, profile_id=required.profile_id
        )

    service = WorkflowService(Store(), Authority(), DependencyGate(probe), validate_support=lambda _: None)
    with pytest.raises(PermissionError, match="revoked"):
        service.submit("principal", "op", json.dumps(contract().model_dump(mode="json")))


@pytest.mark.parametrize(
    "error_name",
    ["StoreUnavailable", "SubmissionConflict", "OutcomeUnknown", "SchemaMissing", "OSError", "TypeError", "ValueError"],
)
def test_lookup_catches_only_classified_store_unavailable(error_name):
    from isaaclab_arena.agentic_environment_generation.workflow import neo4j_store
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    errors = {"OSError": OSError, "TypeError": TypeError, "ValueError": ValueError}
    error_type = errors[error_name] if error_name in errors else getattr(neo4j_store, error_name)
    error = error_type("private detail")
    calls = []

    class Authority:
        def require_read(self, principal):
            calls.append("read")

    class Store:
        def lookup_submission(self, *args):
            calls.append("lookup")
            raise error

        def admit(self, *args):
            pytest.fail("outage must not admit")

    def forbidden(*args):
        pytest.fail("lookup failure must not resolve or probe")

    service = WorkflowService(Store(), Authority(), DependencyGate(forbidden), validate_support=forbidden)
    raw = json.dumps(contract().model_dump(mode="json"))
    if error_name == "StoreUnavailable":
        result = service.submit("principal", "op", raw)
        assert result.disposition == "dependencies_not_ready" and result.run is None
        assert result.readiness.blockers == ("neo4j",)
        observation = result.readiness.results[0]
        assert observation.profile_id == "synthetic" and observation.profile_sha256 == "a" * 64
        assert observation.status == "unavailable" and observation.code == "probe_failed"
        assert "private detail" not in repr(result)
    else:
        with pytest.raises(type(error)) as caught:
            service.submit("principal", "op", raw)
        assert caught.value is error
    assert calls == ["read", "lookup"]


def test_admit_outcome_unknown_is_not_relabelled_or_retried():
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import OutcomeUnknown
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    calls = []

    class Authority:
        def require_read(self, principal):
            pass

        def require_submit(self, principal, operation_id, request):
            pass

    class Store:
        def lookup_submission(self, *args):
            return None

        def admit(self, *args):
            calls.append("admit")
            raise OutcomeUnknown("unknown")

    def probe(required, timeout):
        return DependencyResult(
            required.dependency_id, "passed", required.profile_sha256, profile_id=required.profile_id
        )

    service = WorkflowService(Store(), Authority(), DependencyGate(probe), validate_support=lambda _: None)
    with pytest.raises(OutcomeUnknown):
        service.submit("principal", "op", json.dumps(contract().model_dump(mode="json")))
    assert calls == ["admit"]


@pytest.mark.parametrize("kind", ["other_store", "fake_service", "subclass"])
def test_completion_constructor_rejects_untrusted_or_cross_store_adopter(kind):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import GenerationCoordinator
    from isaaclab_arena.agentic_environment_generation.workflow.service import WorkflowService

    f = coordinator_fixture()
    coordinator = f.coordinator

    class FakeService:
        bound_store = coordinator._store

        def adopt_generation(self, *args, **kwargs):
            pytest.fail("untrusted adopter must never run")

    class Subclass(WorkflowService):
        pass

    service = FakeService()
    if kind != "fake_service":
        cls = Subclass if kind == "subclass" else WorkflowService
        service = cls(
            object() if kind == "other_store" else coordinator._store,
            coordinator._authority,
            None,
            validate_support=lambda _: None,
        )
    with pytest.raises(ValueError, match="same-store"):
        GenerationCoordinator(
            coordinator._store,
            coordinator._authority,
            coordinator._gate,
            coordinator._worker,
            run_id="run",
            principal="creator",
            lease=coordinator._lease,
            readiness_clock=coordinator._clock,
            workflow_service=service,
        )
    assert "prepare" not in f.calls and "send" not in f.calls and "stop" not in f.calls


def coordinator_fixture():
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        AttemptFence,
        AuthorizationSnapshot,
        GenerationReservation,
        ReadinessReceipt,
        WorkerRegistration,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import canonical_json, contract_digest
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import GenerationCoordinator, PreparedWorker
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import ReadinessClock
    from isaaclab_arena.agentic_environment_generation.workflow.results import CleanupEvidence

    calls = []
    request = contract()
    state = SimpleNamespace(revoked=False, absent=False, db_down=False, prepare_hook=None, send_error=False)
    fence = AttemptFence(
        run_id="run",
        intent_id="intent",
        attempt_id="attempt",
        generation=1,
        owner_id="owner",
        owner_epoch=1,
    )
    registration = WorkerRegistration(
        registration_id="worker",
        fence=fence,
        host="host",
        boot="boot",
        pid=10,
        pgid=10,
        sid=10,
        start_ticks=10,
    )
    prepared = PreparedWorker(registration, object())
    authorization = AuthorizationSnapshot(
        database="neo4j",
        deployment_id="dep",
        workspace_id="ws",
        principal="creator",
        grant_ref="grant",
        contract_digest=contract_digest(request),
        expires_at=1000.0,
        capabilities=("generation_model", "operational_writes"),
    )

    class Store:
        dependency_instances = {}

        def get_run(self, run_id):
            calls.append("get_run")
            if state.db_down:
                raise OSError("private outage")
            return SimpleNamespace(
                run_id=run_id,
                contract_json=canonical_json(request),
                version=1,
                state="pending",
                phase="generation",
            )

        def reserve_generation(self, run_id, version, decision, auth, reservation, *, readiness):
            assert type(readiness) is ReadinessReceipt
            assert readiness.contract_digest == contract_digest(request) and auth == authorization
            calls.append("reserve")
            return "intent"

        def begin_owner(self, owner_id):
            calls.append("owner")
            return 1

        def claim_intent(self, intent, owner_id, epoch):
            calls.append("claim")
            return fence

        def register_worker(self, actual_fence, actual_registration):
            assert actual_fence == fence and actual_registration == registration
            calls.append("register")
            return registration

        def release_attempt(self, actual_fence, registration_id, auth, *, readiness):
            assert actual_fence == fence and registration_id == registration.registration_id
            assert type(readiness) is ReadinessReceipt and auth == authorization
            calls.append("release")
            return True

        def request_cancel(self, run_id, version):
            calls.append("cancel_db")
            if state.db_down:
                raise OSError("private outage")
            return SimpleNamespace(state="cancel_requested")

        def acknowledge_cleanup(self, actual_fence, evidence):
            assert actual_fence == fence and evidence.registration == registration
            calls.append("ack")

    class Authority:
        def require_read(self, principal):
            assert principal == "creator"
            calls.append("read_auth")

        def require_execute(self, principal, request, *, run_id, fence=None):
            assert run_id == "run"
            assert fence == (None if "claim" not in calls else registration.fence)
            assert principal == "creator" and request == contract()
            calls.append("execute_auth")
            if state.revoked:
                raise PermissionError("private revoked")
            return authorization

        def release_guard(self, principal, request, fence, registration):
            from contextlib import nullcontext

            return nullcontext()

        def private_envelope(self, principal, request, actual_fence, actual_registration):
            assert actual_fence == fence and actual_registration == registration
            calls.append("envelope")
            return b"secret"

    class Lease:
        owner_id = "owner"

        def mark_prepared(self, fence):
            assert fence.owner_id == self.owner_id

        def require_held(self, run_id, principal):
            assert (run_id, principal) == ("run", "creator")
            calls.append("lease")

    class Worker:
        def prepare(self, actual_fence, request, *, timeout_s):
            calls.append("prepare")
            assert actual_fence == fence and 0 < timeout_s <= 10
            if state.prepare_hook:
                state.prepare_hook()
            return prepared

        def send(self, actual, envelope, *, timeout_s):
            assert actual is prepared and envelope == b"secret"
            assert calls[-4:] == ["release", "envelope", "execute_auth", "lease"]
            calls.append("send")
            if state.send_error:
                raise OSError("secret")

        def stop_owned(self, actual, *, timeout_s):
            assert actual is prepared
            calls.append("stop")
            return CleanupEvidence(
                registration=registration,
                evidence_ref="stopped",
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            )

    def probe(required, timeout):
        calls.append("probe:" + required.dependency_id)
        return DependencyResult(
            required.dependency_id,
            "unavailable" if state.absent else "passed",
            required.profile_sha256,
            profile_id=required.profile_id,
        )

    def clock():
        return 100.0

    store, worker = Store(), Worker()
    coordinator = GenerationCoordinator(
        store,
        Authority(),
        DependencyGate(probe, clock=clock),
        worker,
        run_id="run",
        principal="creator",
        lease=Lease(),
        readiness_clock=ReadinessClock.capture(monotonic=clock, wall_clock=clock),
    )
    reservation = GenerationReservation(
        model_calls=2,
        model_tokens=100,
        cost_ceiling_usd=0.0,
        runtime_allowance_seconds=5.0,
    )

    def dispatch():
        return coordinator.dispatch("creator", expected_version=1, decision_id="decision", reservation=reservation)

    return SimpleNamespace(
        coordinator=coordinator,
        dispatch=dispatch,
        calls=calls,
        state=state,
        prepared=prepared,
        store=store,
        worker=worker,
    )


def test_owned_receiver_failure_does_not_require_read_or_cancel_user():
    f = coordinator_fixture()
    handle = f.dispatch()
    f.state.db_down = True

    def expired(principal):
        raise PermissionError("expired")

    f.coordinator._authority.require_read = expired
    with pytest.raises(PermissionError):
        f.coordinator.fail_owned(object())
    outcome = f.coordinator.fail_owned(handle.prepared)
    assert outcome.durable_reconciliation_pending and not outcome.cleanup_pending
    assert handle.reconciliation_required and handle.cleanup is not None
    assert "cancel_db" not in f.calls and f.calls.count("stop") == 1
    with pytest.raises(PermissionError):
        f.coordinator.cancel("creator")


def test_coordinator_preparation_latch_and_release_guard_boundaries():
    from contextlib import contextmanager

    f = coordinator_fixture()
    active = []
    marked = []

    @contextmanager
    def guard(principal, request, fence, registration):
        assert "release" in f.calls
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    f.coordinator._authority.release_guard = guard
    f.coordinator._lease.mark_prepared = lambda fence: marked.append(fence)
    prepare = f.worker.prepare
    send = f.worker.send

    def checked_prepare(fence, request, **kwargs):
        assert marked == [fence]
        return prepare(fence, request, **kwargs)

    def checked_send(*args, **kwargs):
        assert active == [True]
        return send(*args, **kwargs)

    f.worker.prepare, f.worker.send = checked_prepare, checked_send
    f.dispatch()
    assert not active


@pytest.mark.parametrize("revoke_before_guard", [False, True])
def test_coordinator_threaded_guard_and_cancellation_lock_order(revoke_before_guard):
    from contextlib import contextmanager
    from threading import Event, RLock, Thread

    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete

    f = coordinator_fixture()
    authority_lock = RLock()
    entered, resume, cancelling, cancelled = Event(), Event(), Event(), Event()
    errors = []

    @contextmanager
    def guard(*args):
        with authority_lock:
            if revoke_before_guard:
                raise PermissionError("revoked before final guard")
            yield

    read = f.coordinator._authority.require_read

    def locked_read(principal):
        with authority_lock:
            read(principal)

    f.coordinator._authority.require_read = locked_read
    f.coordinator._authority.release_guard = guard
    send = f.worker.send

    def waiting_send(*args, **kwargs):
        entered.set()
        assert resume.wait(2)
        send(*args, **kwargs)

    f.worker.send = waiting_send

    def dispatch():
        try:
            f.dispatch()
        except DispatchIncomplete:
            errors.append("denied")

    def cancel():
        cancelling.set()
        f.coordinator.cancel("creator")
        cancelled.set()

    thread = Thread(target=dispatch)
    thread.start()
    if revoke_before_guard:
        thread.join(2)
        assert not thread.is_alive() and errors == ["denied"] and "send" not in f.calls
        return
    assert entered.wait(2)
    stopper = Thread(target=cancel)
    stopper.start()
    assert cancelling.wait(2) and not cancelled.wait(0.1)
    resume.set()
    thread.join(2)
    stopper.join(2)
    assert not thread.is_alive() and not stopper.is_alive() and not errors
    assert cancelled.is_set() and f.calls.index("send") < f.calls.index("stop")


def test_coordinator_missing_guard_never_sends():
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete

    f = coordinator_fixture()
    f.coordinator._authority.release_guard = None
    with pytest.raises(DispatchIncomplete):
        f.dispatch()
    assert "release" in f.calls and "send" not in f.calls and "stop" in f.calls


def test_generation_coordinator_releases_then_sends_once_and_retains_exact_retry():
    f = coordinator_fixture()
    handle = f.dispatch()
    assert handle.prepared is f.prepared
    before = list(f.calls)
    f.state.revoked = True
    assert f.dispatch() is handle
    assert f.calls == before + ["read_auth"]
    assert f.calls.count("execute_auth") == 3
    assert f.calls.count("envelope") == 2
    lifecycle = [c for c in f.calls if c in {"reserve", "owner", "claim", "prepare", "register", "release", "send"}]
    assert lifecycle == [
        "reserve",
        "owner",
        "claim",
        "prepare",
        "register",
        "release",
        "send",
    ]
    assert f.calls.count("probe:gpu") == 2
    assert b"secret" not in repr(handle).encode()


@pytest.mark.parametrize("context", ["run", "fence"])
def test_execution_authority_rejects_wrong_run_or_attempt_context(context):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete

    f = coordinator_fixture()
    original = f.coordinator._authority.require_execute

    def bound_elsewhere(principal, request, *, run_id, fence=None):
        auth = original(principal, request, run_id=run_id, fence=fence)
        if context == "run":
            assert run_id == "run"
            raise PermissionError("grant belongs to another run")
        if fence is not None:
            assert fence == f.prepared.registration.fence
            raise PermissionError("grant belongs to another attempt")
        return auth

    f.coordinator._authority.require_execute = bound_elsewhere
    with pytest.raises(DispatchIncomplete):
        f.dispatch()
    assert "send" not in f.calls and "release" not in f.calls
    assert ("reserve" in f.calls) is (context == "fence")
    assert ("stop" in f.calls) is (context == "fence")


@pytest.mark.parametrize(
    "field,value",
    [
        ("grant_ref", "other"),
        ("principal", "other"),
        ("database", "other"),
        ("workspace_id", "other"),
        ("deployment_id", "other"),
        ("contract_digest", "f" * 64),
        ("capabilities", ("generation_model",)),
        ("expires_at", 2000.0),
    ],
)
def test_final_authorization_must_equal_durable_release_snapshot(field, value):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete

    f = coordinator_fixture()
    original = f.coordinator._authority.require_execute

    def changed(principal, request, *, run_id, fence=None):
        auth = original(principal, request, run_id=run_id, fence=fence)
        return auth.model_copy(update={field: value}) if "release" in f.calls else auth

    f.coordinator._authority.require_execute = changed
    with pytest.raises(DispatchIncomplete) as caught:
        f.dispatch()
    assert "release" in f.calls and "send" not in f.calls
    assert f.calls.count("stop") == 1 and caught.value.handle.reconciliation_required
    assert f.dispatch() is caught.value.handle


@pytest.mark.parametrize("failure", ["dependency", "revoked", "send", "prepare"])
def test_generation_coordinator_failure_fences_retry_and_stops_exact_worker(failure):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete, PrepareFailed

    f = coordinator_fixture()
    if failure == "dependency":
        f.state.absent = True
    elif failure == "revoked":
        f.state.prepare_hook = lambda: setattr(f.state, "revoked", True)
    elif failure == "send":
        f.state.send_error = True
    else:

        def fail():
            raise PrepareFailed(f.prepared)

        f.state.prepare_hook = fail
    with pytest.raises(DispatchIncomplete) as caught:
        f.dispatch()
    retained = caught.value.handle
    assert f.dispatch() is retained
    assert f.calls.count("send") == (1 if failure == "send" else 0)
    assert f.calls.count("prepare") == (0 if failure == "dependency" else 1)
    assert f.calls.count("stop") == (0 if failure == "dependency" else 1)
    assert retained.incomplete
    if failure == "send":
        assert retained.reconciliation_required and retained.prepared is f.prepared
    assert "secret" not in str(caught.value)


def test_generation_coordinator_local_cancel_stops_before_database_outage():
    f = coordinator_fixture()
    handle = f.dispatch()
    f.state.db_down = True
    result = f.coordinator.cancel("creator")
    assert result.durable_cancellation_pending and not result.cleanup_pending
    assert handle.cleanup.registration == f.prepared.registration
    assert f.calls.index("stop") < f.calls.index("get_run", f.calls.index("send"))
    assert f.dispatch() is handle and f.calls.count("send") == 1


def test_generation_coordinator_cancel_during_prepare_never_sends():
    f = coordinator_fixture()
    f.state.prepare_hook = lambda: f.coordinator.cancel("creator")
    handle = f.dispatch()
    assert handle.cleanup.registration == f.prepared.registration
    assert "send" not in f.calls and "release" not in f.calls
    assert f.calls.count("stop") == 1


@pytest.mark.parametrize("release", [False, "unknown", "send_error"])
def test_generation_release_ambiguity_never_resends_and_records_reconciliation(release):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import DispatchIncomplete
    from isaaclab_arena.agentic_environment_generation.workflow.results import ReconciliationReason

    f = coordinator_fixture()

    def release_attempt(*args, **kwargs):
        f.calls.append("release")
        if release == "unknown":
            raise OSError("unknown private commit")
        return release == "send_error"

    def reconcile(fence, reason):
        assert fence == f.prepared.registration.fence
        assert reason is ReconciliationReason.OWNER_OUTCOME_UNCERTAIN
        f.calls.append("reconcile")
        raise OSError("database offline")

    f.store.release_attempt = release_attempt
    f.store.mark_reconciliation_required = reconcile
    f.state.send_error = True
    with pytest.raises(DispatchIncomplete) as caught:
        f.dispatch()
    assert f.dispatch() is caught.value.handle
    assert f.calls.count("send") == (1 if release == "send_error" else 0)
    assert f.calls.index("stop") < f.calls.index("reconcile")
    assert caught.value.handle.durable_reconciliation_pending


def test_generation_cancel_serializes_with_release_send_and_is_creator_only():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    f = coordinator_fixture()
    entered, proceed, cancelling = Event(), Event(), Event()
    original = f.store.release_attempt

    def release(*args, **kwargs):
        entered.set()
        assert proceed.wait(2)
        return original(*args, **kwargs)

    f.store.release_attempt = release

    def cancel():
        cancelling.set()
        return f.coordinator.cancel("creator")

    with ThreadPoolExecutor(max_workers=2) as pool:
        dispatched = pool.submit(f.dispatch)
        assert entered.wait(2)
        cancelled = pool.submit(cancel)
        assert cancelling.wait(2)
        assert "stop" not in f.calls
        proceed.set()
        dispatched.result(3)
        cancelled.result(3)
    assert f.calls.index("release") < f.calls.index("send") < f.calls.index("stop")
    before = list(f.calls)
    with pytest.raises((PermissionError, AssertionError)):
        f.coordinator.cancel("other")
    assert f.calls == before


def test_generation_cancel_retries_cleanup_ack_without_reissuing_versioned_cancel():
    from types import SimpleNamespace

    f = coordinator_fixture()
    f.dispatch()
    f.store.get_run = lambda _: SimpleNamespace(version=8, state="cancel_requested")

    def forbidden(*args):
        pytest.fail("cancel_requested must not be issued with a new version")

    f.store.request_cancel = forbidden
    result = f.coordinator.cancel("creator")
    assert result.durable_cancellation_pending
    assert "ack" in f.calls


def test_generation_stop_failure_retains_exact_cleanup_obligation():
    f = coordinator_fixture()
    handle = f.dispatch()

    def failed_stop(prepared, *, timeout_s):
        assert prepared is f.prepared
        raise OSError("private stop error")

    f.worker.stop_owned = failed_stop
    result = f.coordinator.cancel("creator")
    assert result.cleanup_pending and result.durable_cancellation_pending
    assert handle.cleanup_pending and handle.prepared is f.prepared
    assert "cancel_db" not in f.calls
    assert f.dispatch() is handle and f.calls.count("send") == 1
