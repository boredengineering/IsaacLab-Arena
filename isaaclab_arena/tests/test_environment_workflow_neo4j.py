# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Real Cypher and bounded races against the separately owned disposable database.

Schema provisioning and initialize_scope are administrative, quiescent gates:
finish them before starting cooperative readers/writers. Concurrent initialization
is not an acceptance claim of this suite. No admission/unknown-outcome retries.
"""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from neo4j import GraphDatabase

from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
    CapacityExceeded,
    Neo4jWorkflowStore,
    ReplayGap,
    SubmissionConflict,
)


@pytest.fixture
def driver():
    with GraphDatabase.driver(
        os.environ["ARENA_WORKFLOW_NEO4J_URI"],
        auth=None,
        max_transaction_retry_time=0,
        connection_timeout=3,
        connection_acquisition_timeout=5,
    ) as d:
        with d.session(database=os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"]) as session:
            for ddl in Neo4jWorkflowStore.schema_requirements():
                with session.begin_transaction(timeout=5) as tx:
                    tx.run(ddl).consume()
                    tx.commit()
        yield d


def scoped(driver, workspace=None, deployment="disposable-tests"):
    s = Neo4jWorkflowStore(
        driver,
        database=os.environ["ARENA_WORKFLOW_NEO4J_DATABASE"],
        deployment_id=deployment,
        workspace_id=workspace or uuid.uuid4().hex,
    )
    assert s.verify_schema()
    s.initialize_scope()
    return s


def test_result_read_model_conservative_pending_budget(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.read_model import (
        workflow_result,
    )
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import scene_contract

    store = scoped(driver)
    contract = scene_contract()
    run = store.admit("read-model", canonical_json(contract), canonical_json(contract), 1)
    result = workflow_result(store, run.run_id, protect=lambda value: None)
    assert result["schema_version"] == 1
    assert result["budget"]["reserved"]["model_calls"] == 0
    assert result["budget"]["remaining"]["model_calls"] == contract.budget.max_model_calls
    assert result["budget"]["actual_consumption"] == "unknown"
    assert result["publication"] == "not_requested"
    assert result["experiment"] == "not_requested"
    assert [c["criterion_id"] for c in result["criteria"]] == [c.criterion_id for c in contract.criteria]
    assert all(c["verdict"] == "not_run" for c in result["criteria"])
    assert result["evidence"] == []
    assert result["recovery"] == "known_unreleased"
    assert result["available_actions"] == ["cancel", "resume"]
    assert store.get_run(run.run_id) == run


def test_admit_readback_replay_conflict_capacity_scope_events(driver):
    s = scoped(driver)
    assert s.lookup_submission("op", "{}") is None
    accepted = s.admit("op", "{}", '{"resolved":1}', 1)
    assert (
        accepted.version == 1
        and accepted.state == "pending"
        and accepted.phase == "dependency_readiness"
        and accepted.event_cursor == 1
    )
    assert s.get_run(accepted.run_id) == accepted
    assert s.lookup_submission("op", "{}") == accepted
    assert s.admit("op", "{}", '{"resolved":2}', 0) == accepted
    with pytest.raises(SubmissionConflict):
        s.admit("op", '{"different":true}', "{}", 1)
    with pytest.raises(CapacityExceeded):
        s.admit("other", "{}", "{}", 1)
    snapshot = s.snapshot()
    assert snapshot.runs == (accepted,) and snapshot.cursor == 1
    page = s.events_after(0, 1)
    assert page.cursor == page.ceiling == 1 and page.floor == 0
    assert len(page.events) == 1 and page.events[0].run_id == accepted.run_id
    assert s.events_after(1).events == ()
    with pytest.raises(ReplayGap):
        s.events_after(2)
    other = scoped(driver)
    assert other.get_run(accepted.run_id) is None
    assert other.admit("op", "{}", "{}", 1).run_id != accepted.run_id
    s.initialize_scope()
    assert s.snapshot() == snapshot


def race(s, operations, capacity):
    barrier = Barrier(len(operations))

    def submit(operation):
        barrier.wait(timeout=10)
        try:
            return s.admit(operation, "{}", "{}", capacity)
        except CapacityExceeded:
            return None

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return list(pool.map(submit, operations))


def test_control_only_race(driver):
    s = scoped(driver)
    barrier = Barrier(6)

    def read(_):
        barrier.wait(timeout=10)
        return s.snapshot()

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert len(list(pool.map(read, range(6)))) == 6


def prime_lock(s):
    assert s.snapshot().cursor == 0
    with s.driver.session(database=s.database) as session:
        row = session.run(
            "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "RETURN c.lock_anchor AS anchor, c.sequence AS sequence",
            **s.scope,
        ).single(strict=True)
        assert row["anchor"] is True and row["sequence"] == 0


def assert_readback(s, expected):
    snapshot = s.snapshot()
    assert snapshot.runs == tuple(sorted(expected, key=lambda run: run.run_id))
    assert snapshot.cursor == len(expected) and snapshot.floor == 0
    page = s.events_after(0)
    assert page.cursor == page.ceiling == len(expected) and page.floor == 0
    assert [event.sequence for event in page.events] == list(range(1, len(expected) + 1))
    assert {(event.run_id, event.operation_id) for event in page.events} == {
        (run.run_id, run.operation_id) for run in expected
    }
    for run in expected:
        assert s.get_run(run.run_id) == s.lookup_submission(run.operation_id, run.request_json) == run


@pytest.mark.parametrize("round_index", range(3))
def test_duplicate_key_race_is_one_acceptance_and_one_event(driver, round_index):
    s = scoped(driver)
    prime_lock(s)
    results = race(s, ["same"] * 6, 1)
    assert all(result == results[0] and result is not None for result in results)
    assert len(s.snapshot().runs) == 1
    assert s.snapshot().cursor == 1
    assert len(s.events_after(0).events) == 1
    assert results[0].request_json == results[0].contract_json == "{}"
    assert_readback(s, [results[0]])


@pytest.mark.parametrize("round_index", range(3))
def test_distinct_keys_race_cannot_exceed_scoped_capacity(driver, round_index):
    s = scoped(driver)
    prime_lock(s)
    results = race(s, [str(i) for i in range(6)], 2)
    assert sum(result is not None for result in results) == 2
    snapshot = s.snapshot()
    assert len(snapshot.runs) == snapshot.cursor == 2
    first = s.events_after(0, 1)
    second = s.events_after(first.cursor, 1)
    assert [first.events[0].sequence, second.events[0].sequence] == [1, 2]
    accepted = [result for result in results if result is not None]
    assert all(run.request_json == run.contract_json == "{}" for run in accepted)
    assert_readback(s, accepted)
    for operation, result in zip(map(str, range(6)), results):
        assert s.lookup_submission(operation, "{}") == result


@pytest.mark.parametrize("different_requests", [True, False])
def test_same_key_competing_requests_or_contracts(driver, different_requests):
    s = scoped(driver)
    prime_lock(s)
    barrier = Barrier(6)
    requests = ['{"request":%d}' % (i if different_requests else 0) for i in range(6)]
    contracts = ['{"contract":%d}' % i for i in range(6)]

    def submit(i):
        barrier.wait(timeout=10)
        try:
            return s.admit("same", requests[i], contracts[i], 1)
        except SubmissionConflict as exc:
            return exc

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(submit, range(6)))
    accepted = [result for result in results if not isinstance(result, SubmissionConflict)]
    winner = accepted[0]
    assert len(accepted) == (1 if different_requests else 6)
    assert all(result == winner for result in accepted)
    winner_index = contracts.index(winner.contract_json)
    assert winner.request_json == requests[winner_index]
    if different_requests:
        assert results[winner_index] == winner
        assert sum(isinstance(result, SubmissionConflict) for result in results) == 5
    assert_readback(s, [winner])


def test_mixed_snapshots_and_admissions_have_exact_scoped_prefix(driver):
    s = scoped(driver)
    foreign = scoped(driver)
    foreign_runs = [foreign.admit(str(i), "{}", "{}", 3) for i in range(3)]
    prime_lock(s)
    barrier = Barrier(6)

    def work(i):
        barrier.wait(timeout=10)
        if i < 3:
            return s.admit(str(i), '{"member":%d}' % i, "{}", 3), []
        return None, [s.snapshot() for _ in range(3)]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(work, range(6)))
    accepted = [run for run, _ in results if run is not None]
    assert len(accepted) == 3
    snapshots = [snapshot for _, batch in results for snapshot in batch]
    assert len(snapshots) == 9
    for snapshot in snapshots:
        assert len(snapshot.runs) == snapshot.cursor and snapshot.floor == 0
        assert snapshot.runs == tuple(
            sorted(
                (run for run in accepted if run.event_cursor <= snapshot.cursor),
                key=lambda run: run.run_id,
            )
        )
        assert not {run.run_id for run in snapshot.runs} & {run.run_id for run in foreign_runs}
    assert_readback(s, accepted)
    assert_readback(foreign, foreign_runs)


def test_post_create_result_failure_rolls_back_real_transaction(driver):
    s = scoped(driver)
    prime_lock(s)
    injected = []

    class ResultFailure(RuntimeError):
        pass

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Transaction(Proxy):
        def run(self, query, **parameters):
            result = self.real.run(query, **parameters)
            if "CREATE (e:ArenaWorkflowEvent" not in query:
                return result
            rows = list(result)
            assert result.consume().counters.nodes_created == 2
            assert len(rows) == 1 and rows[0]["run"]["event_cursor"] == 1
            evidence = self.real.run(
                "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "MATCH (r:ArenaWorkflowRun {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "MATCH (e:ArenaWorkflowEvent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "RETURN c.sequence AS cursor, r.run_id AS run, e.run_id AS event",
                **s.scope,
            ).single(strict=True)
            assert evidence["cursor"] == 1 and evidence["run"] == evidence["event"] == rows[0]["run"]["run_id"]

            def failing_result():
                injected.append(dict(evidence))
                raise ResultFailure("after real create result, before commit")
                yield  # Deliberately fail while the store consumes the query result.

            return failing_result()

        def commit(self):
            pytest.fail("injected result failure must never reach commit")

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            return Session(self.real.session(**kwargs))

    failing = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope)
    with pytest.raises(ResultFailure, match="after real create result"):
        failing.admit("rollback", "{}", '{"retained":true}', 1)
    assert len(injected) == 1
    with GraphDatabase.driver(
        os.environ["ARENA_WORKFLOW_NEO4J_URI"],
        auth=None,
        max_transaction_retry_time=0,
        connection_timeout=3,
        connection_acquisition_timeout=5,
    ) as independent_driver:
        independent = Neo4jWorkflowStore(independent_driver, database=s.database, **s.scope)
        assert_readback(independent, [])
        assert independent.get_run(injected[0]["run"]) is None
        assert independent.lookup_submission("rollback", "{}") is None
        accepted = independent.admit("rollback", "{}", '{"retained":true}', 1)
        assert accepted.event_cursor == 1
        assert_readback(independent, [accepted])


def test_owner_epoch_is_stable_and_dirty_owner_cannot_be_replaced(driver):
    s = scoped(driver)
    assert hasattr(s, "begin_owner"), "durable owner protocol missing"
    assert s.begin_owner("owner-a") == 1
    assert s.begin_owner("owner-a") == 1
    with pytest.raises(ValueError):
        s.begin_owner("owner-b")
    replacement = Neo4jWorkflowStore(driver, database=s.database, **s.scope)
    assert replacement.begin_owner("owner-a") == 1


def test_owner_handover_requires_retirement_record_not_only_clean_flag(driver):
    s = scoped(driver)
    assert s.begin_owner("owner-a") == 1
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (c:ArenaWorkflowControl {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "SET c.owner_dirty=false",
            **s.scope,
        ).consume()
    before = s.get_owner()
    with pytest.raises(ValueError, match="retirement"):
        s.begin_owner("owner-b")
    assert s.get_owner() == before


def reserved(s):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        GenerationReservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )
    from isaaclab_arena.tests.test_environment_workflow_decisions import (
        authority,
        generation_contract,
    )

    contract = generation_contract()
    auth = authority(s, contract)
    reservation = GenerationReservation(
        model_calls=1,
        model_tokens=100,
        cost_ceiling_usd=1.0,
        runtime_allowance_seconds=5.0,
    )
    run = s.admit("generate", "{}", canonical_json(contract), 1)
    intent = s.reserve_generation(
        run.run_id,
        1,
        "decision-1",
        auth,
        reservation,
        readiness=readiness(contract, auth),
    )
    return run, intent, auth, reservation, contract


def test_reserve_exact_replay_and_transition_guards(driver):
    s = scoped(driver)
    assert hasattr(s, "reserve_generation"), "reservation transaction missing"
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    s.clock = lambda: 300.0
    assert s.reserve_generation(run.run_id, 1, "decision-1", auth, reservation, readiness=None) == intent
    assert s.get_run(run.run_id).version == 2
    assert s.get_run(run.run_id).phase == "generation"
    assert [e.kind for e in s.events_after(0).events] == [
        "WorkflowRequested",
        "GenerationReserved",
    ]
    with pytest.raises(ValueError):
        s.reserve_generation(run.run_id, 1, "different", auth, reservation, readiness=None)
    with pytest.raises(ValueError):
        s.reserve_generation(run.run_id, 2, "second", auth, reservation, readiness=None)


def test_exact_generation_recovery_lookup_is_bounded_and_scoped(driver):
    s = scoped(driver)
    s.clock = lambda: 100.0
    assert s.get_generation_attempt("unknown") is None
    run, intent, _, _, _ = reserved(s)
    assert s.get_generation_attempt(run.run_id) is None
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    assert s.get_generation_attempt(run.run_id) == s.get_attempt(fence)
    assert scoped(driver).get_generation_attempt(run.run_id) is None
    with pytest.raises(ValueError):
        s.get_attempt(fence.model_copy(update={"owner_epoch": 2}))
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (i:ArenaExecutionIntent {intent_id:$id})-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
            "CREATE (i)-[:HAS_ATTEMPT]->(duplicate:ArenaExecutionAttempt) SET duplicate=properties(a)",
            id=intent,
        ).consume()
    with pytest.raises(ValueError, match="ambiguous"):
        s.get_generation_attempt(run.run_id)


@pytest.mark.parametrize("damage", ["missing_fence", "duplicate_intent", "foreign_attempt", "detached_run"])
def test_recovery_rejects_inexact_retained_paths(driver, damage):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, _, _, _ = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    suffix = {
        "missing_fence": "REMOVE a.fence_json",
        "duplicate_intent": (
            "CREATE (r)-[:HAS_INTENT]->(other:ArenaExecutionIntent) SET other=properties(i) "
            "CREATE (other)-[:HAS_ATTEMPT]->(a)"
        ),
        "foreign_attempt": "SET a.workspace_id='foreign'",
        "detached_run": "DELETE link",
    }[damage]
    with driver.session(database=s.database) as session:
        session.run(
            "MATCH (r:ArenaWorkflowRun)-[link:HAS_INTENT]->(i:ArenaExecutionIntent)"
            "-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) WHERE i.intent_id=$id " + suffix,
            id=intent,
        ).consume()
    if damage == "detached_run":
        assert s.get_generation_attempt(run.run_id) is None
    else:
        with pytest.raises(ValueError):
            s.get_generation_attempt(run.run_id)
    with pytest.raises(ValueError):
        s.get_attempt(fence)


def test_claim_is_stable_and_owner_fenced(driver):
    s = scoped(driver)
    assert hasattr(s, "claim_intent"), "claim missing"
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    epoch = s.begin_owner("owner")
    with pytest.raises(ValueError):
        s.claim_intent(intent, "other", epoch)
    with pytest.raises(ValueError):
        s.claim_intent(intent, "owner", epoch + 1)
    fence = s.claim_intent(intent, "owner", epoch)
    assert fence.run_id == run.run_id and fence.intent_id == intent and fence.generation == 1
    assert s.claim_intent(intent, "owner", epoch) == fence
    assert s.get_run(run.run_id).version == 3


def registration(fence):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        WorkerRegistration,
    )

    return WorkerRegistration(
        registration_id="reg-1",
        fence=fence,
        host="host",
        boot="boot",
        pid=100,
        pgid=100,
        sid=100,
        start_ticks=1000,
    )


def test_attempt_reads_committed_reservation_and_original_timing(driver):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    before = s.get_attempt(fence)
    assert before.reservation == reservation
    assert before.admitted_at == 100.0 and before.released_at is None
    reg = registration(fence)
    s.register_worker(fence, reg)
    s.clock = lambda: 101.0
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    released = s.get_attempt(fence)
    assert released.reservation == reservation and released.admitted_at == 100.0
    assert released.released_at == 101.0
    s.clock = lambda: 300.0
    assert not s.release_attempt(fence, reg.registration_id, auth, readiness=None)
    assert s.get_attempt(fence) == released


def test_registration_is_exact_and_fenced(driver):
    s = scoped(driver)
    assert hasattr(s, "register_worker"), "registration missing"
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = registration(fence)
    assert s.register_worker(fence, reg) == reg
    assert s.register_worker(fence, reg) == reg
    with pytest.raises(ValueError):
        s.register_worker(fence, reg.model_copy(update={"pid": 101}))
    with pytest.raises(ValueError):
        s.register_worker(fence.model_copy(update={"generation": 2}), reg)
    assert s.get_run(run.run_id).version == 4


def readiness(contract, auth):
    from isaaclab_arena.tests.test_environment_workflow_decisions import gate_readiness

    return gate_readiness(contract)


def test_release_once_requires_fresh_exact_readiness_and_authority(driver):
    s = scoped(driver)
    assert hasattr(s, "release_attempt"), "release missing"
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    ready = readiness(contract, auth)
    with pytest.raises(ValueError):
        s.release_attempt(fence, "reg-1", auth, readiness=ready)
    reg = s.register_worker(fence, registration(fence))
    with pytest.raises(TypeError):
        s.release_attempt(fence, reg.registration_id, auth)
    for bad in [
        auth.model_copy(update={"expires_at": 100.0}),
        auth.model_copy(update={"contract_digest": "b" * 64}),
        auth.model_copy(update={"capabilities": ("operational_writes",)}),
        auth.model_copy(update={"workspace_id": "foreign"}),
    ]:
        with pytest.raises(ValueError):
            s.release_attempt(fence, reg.registration_id, bad, readiness=ready)
    for bad in [
        ready.model_copy(update={"checked_at": 69.0}),
        ready.model_copy(update={"checked_at": 101.0}),
        ready.model_copy(update={"profiles": ready.profiles[:-1]}),
        ready.model_copy(update={"contract_digest": "b" * 64}),
    ]:
        with pytest.raises(ValueError):
            s.release_attempt(fence, reg.registration_id, auth, readiness=bad)
    barrier = Barrier(6)

    def release(_):
        barrier.wait(timeout=10)
        return s.release_attempt(fence, reg.registration_id, auth, readiness=ready)

    with ThreadPoolExecutor(max_workers=6) as pool:
        winners = list(pool.map(release, range(6)))
    assert winners.count(True) == 1 and winners.count(False) == 5
    assert not s.release_attempt(fence, reg.registration_id, auth, readiness=ready)
    with pytest.raises(ValueError):
        s.claim_intent(intent, "owner", fence.owner_epoch)
    assert s.get_run(run.run_id).version == 5
    assert [e.kind for e in s.events_after(0).events].count("AttemptReleased") == 1
    with driver.session(database=s.database) as session:
        rows = list(
            session.run(
                "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id})"
                "-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) WHERE i.intent_id=$id "
                "RETURN properties(i) AS intent, properties(a) AS attempt",
                **s.scope,
                id=intent,
            )
        )
    assert len(rows) == 1
    assert rows[0]["attempt"]["fence_json"] == fence.model_dump_json()
    assert rows[0]["attempt"]["registration_json"] == reg.model_dump_json()
    assert rows[0]["attempt"]["readiness_json"] == ready.model_dump_json()
    assert rows[0]["attempt"]["release_authorization_json"] == auth.model_dump_json()
    assert rows[0]["attempt"]["status"] == rows[0]["intent"]["status"] == "released"


def test_cancel_fences_release_without_cleanup_or_refund(driver):
    s = scoped(driver)
    assert hasattr(s, "request_cancel"), "cancellation missing"
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    with pytest.raises(ValueError):
        s.request_cancel(run.run_id, 1)
    cancelled = s.request_cancel(run.run_id, 4)
    assert cancelled.state == "cancel_requested" and cancelled.version == 5
    assert s.request_cancel(run.run_id, 4) == cancelled
    assert not s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    with pytest.raises(ValueError):
        s.claim_intent(intent, "owner", fence.owner_epoch)
    with pytest.raises(ValueError):
        s.begin_owner("replacement")
    assert s.get_run(run.run_id) == cancelled
    assert s.events_after(0).events[-1].kind == "CancellationRequested"


@pytest.mark.parametrize(
    "change",
    [
        "calls",
        "tokens",
        "cost",
        "runtime",
        "stale",
        "expired",
        "digest",
        "scope",
        "capability",
        "existing",
        "deadline",
    ],
)
def test_reservation_rejection_is_atomic(driver, change):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        GenerationReservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        ExistingSource,
        canonical_json,
    )
    from isaaclab_arena.tests.test_environment_workflow_decisions import (
        authority,
        generation_contract,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    contract = generation_contract()
    if change == "existing":
        contract = contract.model_copy(
            update={"source": ExistingSource(kind="existing", identity="candidate", content="spec")}
        )
    auth = authority(s, contract)
    fields = dict(
        model_calls=1,
        model_tokens=100,
        cost_ceiling_usd=1.0,
        runtime_allowance_seconds=5.0,
    )
    if change in ("calls", "tokens", "cost", "runtime"):
        key, value = {
            "calls": ("model_calls", 3),
            "tokens": ("model_tokens", 1001),
            "cost": ("cost_ceiling_usd", 3.0),
            "runtime": ("runtime_allowance_seconds", 11.0),
        }[change]
        fields[key] = value
    updates = {
        "expired": {"expires_at": 100.0},
        "digest": {"contract_digest": "b" * 64},
        "scope": {"database": "foreign"},
        "capability": {"capabilities": ("operational_writes",)},
    }
    auth = auth.model_copy(update=updates.get(change, {}))
    run = s.admit("negative", "{}", canonical_json(contract), 1)
    if change == "deadline":
        s.clock = lambda: 160.0
    with pytest.raises(ValueError):
        s.reserve_generation(
            run.run_id,
            2 if change == "stale" else 1,
            "decision",
            auth,
            GenerationReservation(**fields),
            readiness=readiness(contract, auth),
        )
    assert s.get_run(run.run_id) == run
    assert s.snapshot().cursor == 1
    with driver.session(database=s.database) as session:
        row = session.run(
            "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "RETURN count(i) AS n",
            **s.scope,
        ).single()
        assert row["n"] == 0


def test_concurrent_reservations_validate_readiness_before_one_transition(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        GenerationReservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )
    from isaaclab_arena.tests.test_environment_workflow_decisions import (
        authority,
        generation_contract,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    contract = generation_contract()
    auth = authority(s, contract)
    allowance = GenerationReservation(
        model_calls=1,
        model_tokens=100,
        cost_ceiling_usd=1.0,
        runtime_allowance_seconds=5.0,
    )
    run = s.admit("race", "{}", canonical_json(contract), 1)
    ready = readiness(contract, auth)
    with pytest.raises(TypeError):
        s.reserve_generation(run.run_id, 1, "decision", auth, allowance)
    for bad in (
        None,
        ready.model_copy(update={"checked_at": 69.0}),
        ready.model_copy(update={"profiles": ready.profiles[:-1]}),
    ):
        with pytest.raises(ValueError):
            s.reserve_generation(run.run_id, 1, "decision", auth, allowance, readiness=bad)
        assert s.get_run(run.run_id) == run and s.snapshot().cursor == 1
    barrier = Barrier(4)

    def reserve(_):
        barrier.wait(timeout=10)
        return s.reserve_generation(run.run_id, 1, "decision", auth, allowance, readiness=ready)

    with ThreadPoolExecutor(max_workers=4) as pool:
        identities = list(pool.map(reserve, range(4)))
    assert len(set(identities)) == 1
    assert s.snapshot().cursor == 2
    with driver.session(database=s.database) as session:
        rows = list(
            session.run(
                "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "RETURN i.readiness_json AS readiness",
                **s.scope,
            )
        )
    assert len(rows) == 1 and rows[0]["readiness"] == ready.model_dump_json()


def test_cancel_vs_release_has_one_ordered_effect_and_no_retry_authority(driver):
    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, _, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    barrier = Barrier(2)

    def work(cancel):
        barrier.wait(timeout=10)
        if not cancel:
            return s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
        try:
            return s.request_cancel(run.run_id, 4)
        except ValueError:
            return "stale-cancel"

    with ThreadPoolExecutor(max_workers=2) as pool:
        released, cancelled = list(pool.map(work, (False, True)))
    events = s.events_after(0).events
    assert len(events) == 5
    assert events[-1].kind == ("AttemptReleased" if released else "CancellationRequested")
    assert (cancelled == "stale-cancel") is released
    s.clock = lambda: 300.0
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=None) is False


def test_release_acknowledgement_loss_replay_returns_false(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
        OutcomeUnknown,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, _, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Transaction(Proxy):
        def commit(self):
            self.real.commit()
            raise OSError("lost acknowledgement after real release commit")

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            return Session(self.real.session(**kwargs))

    failing = Neo4jWorkflowStore(Driver(driver), database=s.database, **s.scope, clock=lambda: 100.0)
    with pytest.raises(OutcomeUnknown):
        failing.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    s.clock = lambda: 300.0
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=None) is False
    assert [e.kind for e in s.events_after(0).events].count("AttemptReleased") == 1
    assert s.get_run(run.run_id).version == 5


def test_generation_result_requires_exact_cleanup(driver, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow import (
        artifacts,
        results,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))

    class ReadAuthority:
        def require_read(self, principal):
            if principal != "local":
                raise ValueError("not authenticated")

    service = WorkflowService(s, ReadAuthority(), None, validate_support=lambda value: None)
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        adapter = artifacts.GenerationArtifacts(area)
        receipt = adapter.write(
            fence,
            reg,
            contract,
            b"scene: synthetic\n",
            {"scene": "synthetic"},
            protect=lambda value: None,
        )
        s.clock = lambda: 300.0  # expired execution grant must not erase released work
        assert service.adopt_generation("local", fence, receipt, artifacts=adapter, protect=lambda value: None)
        assert not service.adopt_generation("local", fence, receipt, artifacts=adapter, protect=lambda value: None)
        assert s.get_run(run.run_id).state == "running"
        view = s.get_attempt(fence)
        assert view.receipt == receipt and view.cleanup is None
        evidence = results.CleanupEvidence(
            registration=reg,
            evidence_ref="synthetic-stop-1",
            observation="owned_process_group_stopped",
            remote_effects="unknown",
        )
        assert s.acknowledge_cleanup(fence, evidence)
        assert s.get_run(run.run_id).state == "running"
        assert s.get_run(run.run_id).phase == "validation"
        assert s.get_attempt(fence).status == "produced"
        assert s.get_attempt(fence).usage_disposition == "fully_reserved_consumption_deferred"
        assert not s.acknowledge_cleanup(fence, evidence)
        with pytest.raises(ValueError):
            s.acknowledge_cleanup(
                fence,
                evidence.model_copy(update={"registration": reg.model_copy(update={"pid": 101})}),
            )
        with pytest.raises(ValueError):
            s.commit_generation_receipt(fence.model_copy(update={"generation": 2}), receipt)
        with pytest.raises(ValueError):
            s.commit_generation_receipt(fence, receipt.model_copy(update={"candidate_yaml_sha256": "b" * 64}))


@pytest.mark.parametrize("damage", ["bytes", "missing", "symlink", "manifest", "deny", "owner"])
def test_generation_adoption_rejects_artifact_damage_without_receipt(driver, tmp_path, damage):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))

    class ReadAuthority:
        def require_read(self, principal):
            pass  # synthetic authenticated principal; service must still owner-bind

    service = WorkflowService(s, ReadAuthority(), None, validate_support=lambda value: None)
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        adapter = GenerationArtifacts(area)
        receipt = adapter.write(
            fence,
            reg,
            contract,
            b"synthetic: true\n",
            {"synthetic": True},
            protect=lambda value: None,
        )
        path = tmp_path / "area" / receipt.artifact_directory / "candidate.yaml"
        if damage == "bytes":
            path.write_bytes(b"changed")
        elif damage == "missing":
            path.unlink()
        elif damage == "symlink":
            path.unlink()
            path.symlink_to(tmp_path / "outside")
        elif damage == "manifest":
            path.with_name("manifest.json").write_text("{}")

        def protect(value):
            if damage == "deny":
                raise ValueError("current policy rejects private data")

        before = s.get_run(run.run_id)
        with pytest.raises(ValueError):
            service.adopt_generation(
                "other" if damage == "owner" else "local",
                fence,
                receipt,
                artifacts=adapter,
                protect=protect,
            )
        assert s.get_attempt(fence).receipt is None
        assert s.get_run(run.run_id) == before


@pytest.mark.parametrize("cleanup_first", [False, True])
def test_cancelled_late_generation_is_diagnostic_only(driver, tmp_path, cleanup_first):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    evidence = CleanupEvidence(
        registration=reg,
        evidence_ref="synthetic-stop",
        observation="owned_process_group_stopped",
        remote_effects="unknown",
    )
    s.request_cancel(run.run_id, s.get_run(run.run_id).version)
    if cleanup_first:
        s.acknowledge_cleanup(fence, evidence)

    class ReadAuthority:
        def require_read(self, principal):
            assert principal == "local"

    service = WorkflowService(s, ReadAuthority(), None, validate_support=lambda value: None)
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        adapter = GenerationArtifacts(area)
        receipt = adapter.write(
            fence,
            reg,
            contract,
            b"synthetic: true\n",
            {"synthetic": True},
            protect=lambda value: None,
        )
        assert service.adopt_generation("local", fence, receipt, artifacts=adapter, protect=lambda value: None)
        assert s.get_run(run.run_id).state == ("cancelled" if cleanup_first else "cancel_requested")
        if not cleanup_first:
            s.acknowledge_cleanup(fence, evidence)
        assert s.get_run(run.run_id).state == "cancelled"
        assert s.get_attempt(fence).receipt == receipt
        with driver.session(database=s.database) as session:
            row = session.run(
                "MATCH (a:ArenaExecutionAttempt {attempt_id:$id}) RETURN a.receipt_disposition AS disposition",
                id=fence.attempt_id,
            ).single()
        assert row["disposition"] == "diagnostic"
        with pytest.raises(ValueError):
            s.begin_owner("replacement")


def test_cleanup_before_release_fences_future_execution(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    s.acknowledge_cleanup(
        fence,
        CleanupEvidence(
            registration=reg,
            evidence_ref="synthetic-stop",
            observation="owned_process_group_stopped",
            remote_effects="unknown",
        ),
    )
    assert not s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    cancelled = s.request_cancel(run.run_id, s.get_run(run.run_id).version)
    assert cancelled.state == "cancelled"


def test_receipt_retained_with_uncertain_cleanup_requires_reconciliation(driver, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
        ReconciliationReason,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    store = scoped(driver)
    store.clock = lambda: 100.0
    run, intent, auth, _, contract = reserved(store)
    fence = store.claim_intent(intent, "owner", store.begin_owner("owner"))
    reg = store.register_worker(fence, registration(fence))
    assert store.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))

    class Authority:
        def require_read(self, principal):
            assert principal == "local"

    service = WorkflowService(store, Authority(), None, validate_support=lambda value: None)
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        artifacts = GenerationArtifacts(area)
        receipt = artifacts.write(
            fence,
            reg,
            contract,
            b"synthetic: true\n",
            {"synthetic": True},
            protect=lambda value: None,
        )
        assert service.adopt_generation("local", fence, receipt, artifacts=artifacts, protect=lambda value: None)
        with pytest.raises(ValueError):
            store.mark_reconciliation_required(fence, ReconciliationReason.RELEASED_WITHOUT_RECEIPT)
        assert store.mark_reconciliation_required(fence, ReconciliationReason.OWNER_OUTCOME_UNCERTAIN)
        assert store.get_run(run.run_id).state == "reconciliation_required"
        assert store.get_attempt(fence).receipt == receipt
        assert not store.release_attempt(fence, reg.registration_id, auth, readiness=None)
        assert store.acknowledge_cleanup(
            fence,
            CleanupEvidence(
                registration=reg,
                evidence_ref="synthetic-stop",
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            ),
        )
        final = store.get_run(run.run_id)
        assert (final.state, final.phase) == ("running", "validation")


@pytest.mark.parametrize("cancel_order", [None, "before_receipt", "after_receipt", "after_cleanup"])
@pytest.mark.parametrize("cleanup_first", [False, True])
def test_lost_released_attempt_reconciles_only_exact_output(driver, tmp_path, cancel_order, cleanup_first):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow import results
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, reservation, contract = reserved(s)
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    assert hasattr(s, "mark_reconciliation_required"), "lost attempt disposition missing"
    reason = results.ReconciliationReason.RELEASED_WITHOUT_RECEIPT
    before = s.get_run(run.run_id)
    with pytest.raises(ValueError):
        s.mark_reconciliation_required(fence, reason)
    assert s.get_run(run.run_id) == before
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    assert s.mark_reconciliation_required(fence, reason)
    retained = s.get_run(run.run_id)
    assert (retained.state, retained.phase) == ("reconciliation_required", "generation")
    assert not s.mark_reconciliation_required(fence, reason)
    with pytest.raises(ValueError):
        s.mark_reconciliation_required(fence, results.ReconciliationReason.OWNER_OUTCOME_UNCERTAIN)
    with pytest.raises(ValueError):
        s.mark_reconciliation_required(fence, "not-an-enum")
    assert s.get_run(run.run_id) == retained
    assert s.get_attempt(fence).reconciliation_reason == reason
    assert s.get_attempt(fence).status == "reconciliation_required"
    assert s.get_attempt(fence).released
    assert s.get_attempt(fence).receipt is None
    assert not s.release_attempt(fence, reg.registration_id, auth, readiness=None)
    with pytest.raises(ValueError):
        s.claim_intent(intent, "owner", fence.owner_epoch)
    with pytest.raises(ValueError):
        s.reserve_generation(
            run.run_id,
            retained.version,
            "retry",
            auth,
            reservation,
            readiness=readiness(contract, auth),
        )
    with pytest.raises(ValueError):
        s.begin_owner("replacement")
    assert s.snapshot().runs == (retained,)
    assert s.events_after(0).events[-1].kind == "ReconciliationRequired"
    evidence = results.CleanupEvidence(
        registration=reg,
        evidence_ref="synthetic-stop",
        observation="owned_process_group_stopped",
        remote_effects="unknown",
    )

    def cancel():
        s.request_cancel(run.run_id, s.get_run(run.run_id).version)

    if cancel_order == "before_receipt":
        cancel()
        assert s.get_run(run.run_id).state == "cancel_requested"
    if cleanup_first:
        s.acknowledge_cleanup(fence, evidence)

    class ReadAuthority:
        def require_read(self, principal):
            assert principal == "local"

    service = WorkflowService(s, ReadAuthority(), None, validate_support=lambda value: None)
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        adapter = GenerationArtifacts(area)
        receipt = adapter.write(
            fence,
            reg,
            contract,
            b"synthetic: true\n",
            {"synthetic": True},
            protect=lambda value: None,
        )
        s.clock = lambda: 300.0
        assert service.adopt_generation("local", fence, receipt, artifacts=adapter, protect=lambda value: None)
        if cancel_order == "after_receipt":
            cancel()
        if not cleanup_first:
            s.acknowledge_cleanup(fence, evidence)
        if cancel_order == "after_cleanup":
            cancel()
        final = s.get_run(run.run_id)
        assert final.state == ("cancelled" if cancel_order else "running")
        if not cancel_order:
            assert final.phase == "validation"
        assert not service.adopt_generation("local", fence, receipt, artifacts=adapter, protect=lambda value: None)
        assert not s.mark_reconciliation_required(fence, reason)
        assert s.get_run(run.run_id) == final
        view = s.get_attempt(fence)
        assert view.status == ("cancelled" if cancel_order else "produced")
        assert view.receipt == receipt and view.cleanup == evidence
        assert_receipt_storage(s, receipt, "diagnostic" if cancel_order else "produced")
        assert view.reconciliation_reason == reason
        assert view.usage_disposition == "fully_reserved_consumption_deferred"
        assert not s.release_attempt(fence, reg.registration_id, auth, readiness=None)
        assert [e.kind for e in s.events_after(0).events].count("AttemptReleased") == 1
        assert [e.kind for e in s.events_after(0).events].count("ReconciliationRequired") == 1
        with pytest.raises(ValueError):
            s.begin_owner("replacement")


def test_deployment_isolation_with_same_workspace_and_keys(driver):
    workspace = uuid.uuid4().hex
    left = scoped(driver, workspace, "deployment-left")
    right = scoped(driver, workspace, "deployment-right")
    first = left.admit("same", '{"side":"left"}', "{}", 1)
    assert_readback(right, [])
    assert right.lookup_submission("same", '{"side":"right"}') is None
    second = right.admit("same", '{"side":"right"}', "{}", 1)
    assert first.run_id != second.run_id
    assert left.get_run(second.run_id) is right.get_run(first.run_id) is None
    assert_readback(left, [first])
    assert_readback(right, [second])


def apply_release_authority_fault(f, fault):
    """Mutate only private fake authority after the real release commits."""
    if fault == "release_expiry":
        f.now[0] = f.auth.expires_at + 1
    elif fault == "release_revocation":
        f.revoked = True
    elif fault == "release_rotation":
        f.rotated = True
    elif fault == "release_grant_change":
        f.auth = f.auth.model_copy(update={"grant_ref": "replacement"})


def live_coordinator(driver, *, fault=None, completion=False):
    """Real store/gate/bridge; synthetic trusted lease, authority and worker (no processes)."""
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        GenerationReservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        GenerationCoordinator,
        PreparedWorker,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.readiness import (
        DependencyGate,
        DependencyResult,
        ReadinessClock,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )
    from isaaclab_arena.tests.test_environment_workflow_decisions import (
        authority,
        generation_contract,
    )

    store = scoped(driver)

    now = [100.0]

    def clock():
        return now[0]

    store.clock = clock
    contract = generation_contract()
    auth = authority(store, contract)
    run = store.admit("coordinator", "{}", canonical_json(contract), 1)
    f = SimpleNamespace(
        store=store,
        run=run,
        calls=[],
        prepared=None,
        intent=None,
        claimed=None,
        held=True,
        now=now,
        revoked=False,
        auth=auth,
        rotated=False,
    )

    class StoreProxy:
        """Fault only the selected boundary; every successful operation uses real Cypher."""

        def __getattr__(self, name):
            value = getattr(store, name)
            if not callable(value):
                return value

            def call(*args, **kwargs):
                f.calls.append("db:" + name)
                if name in ("begin_owner", "claim_intent"):
                    handle = f.coordinator._handle
                    assert handle.intent_id == f.intent and handle.decision_id == "decision"
                    assert handle.run_id == run.run_id and handle.expected_version == 1
                    assert handle.owner_id == f.coordinator._lease.owner_id
                    if name == "claim_intent":
                        assert handle.owner_epoch == args[2]
                if (name, fault) in {
                    ("register_worker", "registration_before"),
                    ("begin_owner", "pre_claim"),
                }:
                    raise OSError("synthetic boundary failure before commit")
                result = value(*args, **kwargs)
                if name == "release_attempt" and result is True:
                    apply_release_authority_fault(f, fault)
                if name == "reserve_generation":
                    f.intent = result
                    if fault == "reserve_ack_unknown":
                        raise OSError("synthetic reservation acknowledgement loss")
                if name == "claim_intent":
                    f.claimed = result
                if (name, fault) in {
                    ("register_worker", "registration_after"),
                    ("claim_intent", "claim_ack_unknown"),
                }:
                    raise OSError("synthetic acknowledgement loss after commit")
                return result

            return call

    class Authority:
        def require_read(self, principal):
            f.calls.append("authenticate")
            if principal != "local":
                raise PermissionError("creator required")

        def require_execute(self, principal, request, *, run_id, fence=None):
            assert principal == "local" and request == contract
            assert run_id == run.run_id and fence == f.claimed
            f.calls.append("execute_auth")
            if f.revoked or now[0] >= f.auth.expires_at:
                raise PermissionError("execution authority expired or revoked")
            return f.auth

        def release_guard(self, principal, request, fence, registration):
            from contextlib import nullcontext

            return nullcontext()

        def private_envelope(self, principal, request, fence, reg):
            assert principal == "local" and request == contract and reg.fence == fence
            f.calls.append("envelope")
            if f.rotated:
                raise PermissionError("frozen configuration changed")
            return b"synthetic-no-provider-envelope"

    class Lease:
        owner_id = "synthetic-owner-" + uuid.uuid4().hex

        def mark_prepared(self, fence):
            assert fence.owner_id == self.owner_id

        def require_held(self, run_id, principal):
            assert (run_id, principal) == (run.run_id, "local")
            if not f.held:
                raise RuntimeError("synthetic lease lost")

    class Worker:
        def prepare(self, fence, request, *, timeout_s):
            assert request == contract and 0 < timeout_s <= 120
            f.calls.append("prepare")
            f.prepared = PreparedWorker(registration(fence), object())
            if fault == "lease_lost":
                f.held = False
            return f.prepared

        def send(self, prepared, envelope, *, timeout_s):
            assert prepared is f.prepared and envelope == b"synthetic-no-provider-envelope"
            assert store.get_attempt(prepared.registration.fence).released
            f.calls.append("send")
            if fault == "send_failure":
                raise OSError("synthetic send outcome unknown")

        def stop_owned(self, prepared, *, timeout_s):
            assert prepared is f.prepared
            f.calls.append("localstop")
            return CleanupEvidence(
                registration=prepared.registration,
                evidence_ref="synthetic-owned-stop",
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            )

    gate = DependencyGate(
        lambda req, timeout: DependencyResult(
            req.dependency_id,
            "passed",
            req.profile_sha256,
            profile_id=req.profile_id,
            instance_id=req.instance_id,
        ),
        clock=clock,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )

    proxy, authority_port = StoreProxy(), Authority()
    options = {}
    if completion:
        options["workflow_service"] = WorkflowService(proxy, authority_port, gate, validate_support=lambda _: None)
    f.coordinator = GenerationCoordinator(
        proxy,
        authority_port,
        gate,
        Worker(),
        run_id=run.run_id,
        principal="local",
        lease=Lease(),
        readiness_clock=ReadinessClock.capture(monotonic=clock, wall_clock=clock),
        **options,
    )
    f.reservation = GenerationReservation(
        model_calls=1,
        model_tokens=100,
        cost_ceiling_usd=1.0,
        runtime_allowance_seconds=5.0,
    )
    f.dispatch = lambda: f.coordinator.dispatch(
        "local",
        expected_version=1,
        decision_id="decision",
        reservation=f.reservation,
    )
    return f


@pytest.mark.parametrize(
    "fault",
    [
        "release_expiry",
        "release_revocation",
        "release_rotation",
        "release_grant_change",
    ],
)
def test_committed_release_rechecks_private_authority_before_send(driver, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        ReconciliationReason,
    )

    f = live_coordinator(driver, fault=fault)
    with pytest.raises(DispatchIncomplete) as caught:
        f.dispatch()
    handle = caught.value.handle
    retained = f.store.get_attempt(handle.fence)
    assert retained.released and retained.receipt is None
    assert retained.authorization.grant_ref != "replacement"
    assert retained.reconciliation_reason is ReconciliationReason.OWNER_OUTCOME_UNCERTAIN
    assert handle.cleanup.registration == f.prepared.registration
    assert not handle.cleanup_pending and not handle.durable_reconciliation_pending
    assert f.calls.count("send") == 0 and f.calls.count("localstop") == 1
    before = list(f.calls)
    assert f.dispatch() is handle
    assert f.calls == before + ["authenticate"]
    assert f.store.get_run(f.run.run_id).state == "reconciliation_required"


@pytest.fixture
def completion_input(driver, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        parse_contract,
    )

    f = live_coordinator(driver, completion=True)
    handle = f.dispatch()
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        artifacts = GenerationArtifacts(area)
        receipt = artifacts.write(
            handle.fence,
            handle.prepared.registration,
            parse_contract(f.run.contract_json),
            b"scene: synthetic\n",
            {"scene": "synthetic"},
            protect=lambda _: None,
        )
        yield f, handle, artifacts, receipt, tmp_path / "area"


def test_retired_owner_read_survives_replacement_without_changing_authority(
    completion_input,
):
    f, handle, artifacts, receipt, _ = completion_input
    store, fence = f.store, handle.fence
    lookup = getattr(store, "get_retired_owner", None)
    assert callable(lookup), "read-only retained retirement lookup is missing"
    assert lookup(fence.owner_id) is None
    f.coordinator.complete("local", receipt, artifacts, protect=lambda value: None)
    assert store.retire_owner(fence.owner_id, fence.owner_epoch)
    retired = lookup(fence.owner_id)
    assert retired.model_dump() == {
        "owner_id": fence.owner_id,
        "owner_epoch": fence.owner_epoch,
        "dirty": False,
    }
    store.begin_owner("replacement")
    owner, snapshot = store.get_owner(), store.snapshot()
    assert lookup(fence.owner_id) == retired
    assert lookup("replacement") is None
    assert lookup("unknown") is None
    assert store.get_owner() == owner and store.snapshot() == snapshot


def test_clean_owner_handover_preserves_historical_reads_and_fences_mutations(
    completion_input,
):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        parse_contract,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        ReconciliationReason,
    )

    f, handle, artifacts, receipt, _ = completion_input
    s, fence = f.store, handle.fence
    owner = s.get_owner()
    assert owner.model_dump() == {
        "owner_id": fence.owner_id,
        "owner_epoch": 1,
        "dirty": True,
    }
    with pytest.raises(ValueError, match="unresolved"):
        s.retire_owner(fence.owner_id, 1)
    assert s.get_owner() == owner
    assert s.commit_generation_receipt(fence, artifacts.verify(receipt, protect=lambda _: None))
    with pytest.raises(ValueError, match="unresolved"):
        s.retire_owner(fence.owner_id, 1)
    result = f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    before = s.snapshot()
    retained = s.get_attempt(fence)
    assert result.attempt == retained and retained.status == "produced"
    assert s.retire_owner(fence.owner_id, 1) is True
    assert s.get_owner().model_dump() == {
        "owner_id": fence.owner_id,
        "owner_epoch": 1,
        "dirty": False,
    }
    assert s.retire_owner(fence.owner_id, 1) is False
    assert s.get_attempt(fence) == retained
    with pytest.raises(ValueError, match="retired"):
        s.begin_owner(fence.owner_id)
    assert s.begin_owner("owner-b") == 2
    assert s.begin_owner("owner-b") == 2
    replacement = s.get_owner()
    assert replacement.owner_id == "owner-b" and replacement.owner_epoch == 2 and replacement.dirty
    assert s.get_attempt(fence) == s.get_generation_attempt(fence.run_id) == retained
    assert s.snapshot() == before
    next_run = s.admit("next-run", "{}", f.run.contract_json, 1)
    next_intent = s.reserve_generation(
        next_run.run_id,
        1,
        "next-decision",
        f.auth,
        f.reservation,
        readiness=readiness(parse_contract(f.run.contract_json), f.auth),
    )
    next_fence = s.claim_intent(next_intent, "owner-b", 2)
    s.register_worker(next_fence, registration(next_fence))
    next_view, next_run = s.get_attempt(next_fence), s.get_run(next_run.run_id)
    before = s.snapshot()
    for mutation in (
        lambda: s.claim_intent(fence.intent_id, fence.owner_id, 1),
        lambda: s.register_worker(fence, retained.registration),
        lambda: s.release_attempt(fence, retained.registration.registration_id, f.auth, readiness=None),
        lambda: s.commit_generation_receipt(fence, receipt),
        lambda: s.acknowledge_cleanup(fence, retained.cleanup),
        lambda: s.mark_reconciliation_required(fence, ReconciliationReason.OWNER_OUTCOME_UNCERTAIN),
    ):
        with pytest.raises(ValueError, match="owner"):
            mutation()
        assert s.get_owner() == replacement and s.snapshot() == before
    cancelled = s.request_cancel(fence.run_id, result.run.version)
    assert cancelled.state == "cancelled"
    historical = s.get_generation_attempt(fence.run_id)
    assert historical.status == "cancelled" and historical.receipt == receipt
    assert historical.cleanup == retained.cleanup and historical.reservation == retained.reservation
    assert s.request_cancel(fence.run_id, result.run.version) == cancelled
    assert s.get_owner() == replacement
    assert s.get_attempt(next_fence) == next_view and s.get_run(next_run.run_id) == next_run
    assert_receipt_storage(s, receipt, "diagnostic")


@pytest.mark.parametrize(
    "stage",
    [
        "reserved",
        "claimed",
        "prepared_unregistered",
        "registered",
        "released",
        "cleaned_no_outcome",
        "cancelled_no_cleanup",
    ],
)
def test_retirement_never_treats_unresolved_or_missing_registration_as_no_process(driver, stage):
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )

    s = scoped(driver)
    s.clock = lambda: 100.0
    run, intent, auth, _, contract = reserved(s)
    epoch = s.begin_owner("owner")
    if stage != "reserved":
        fence = s.claim_intent(intent, "owner", epoch)
        reg = registration(fence)  # Synthetic prepared process even if registration was not committed.
        if stage not in ("claimed", "prepared_unregistered"):
            s.register_worker(fence, reg)
            if stage in ("released", "cleaned_no_outcome"):
                s.release_attempt(
                    fence,
                    reg.registration_id,
                    auth,
                    readiness=readiness(contract, auth),
                )
            if stage == "cleaned_no_outcome":
                s.acknowledge_cleanup(
                    fence,
                    CleanupEvidence(
                        registration=reg,
                        evidence_ref="synthetic-stop",
                        observation="owned_process_group_stopped",
                        remote_effects="unknown",
                    ),
                )
        if stage == "cancelled_no_cleanup":
            assert s.request_cancel(run.run_id, s.get_run(run.run_id).version).state == "cancel_requested"
    before, owner = s.snapshot(), s.get_owner()
    with pytest.raises(ValueError, match="unresolved"):
        s.retire_owner("owner", epoch)
    with pytest.raises(ValueError, match="dirty"):
        s.begin_owner("replacement")
    assert s.snapshot() == before and s.get_owner() == owner


def test_cancelled_clean_registration_can_retire_without_refund(driver):
    f = live_coordinator(driver)
    handle = f.dispatch()
    f.coordinator.cancel("local")
    s, fence = f.store, handle.fence
    retained = s.get_attempt(fence)
    assert retained.status == "cancelled" and retained.receipt is None and retained.cleanup
    assert s.retire_owner(fence.owner_id, fence.owner_epoch)
    assert s.get_owner().dirty is False
    assert s.begin_owner("next") == 2
    assert s.get_generation_attempt(fence.run_id) == retained
    assert retained.reservation == f.reservation
    assert retained.usage_disposition == "fully_reserved_consumption_deferred"


def test_owner_absence_and_unavailable_readback_grant_no_retirement(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
        ScopeMissing,
    )

    s = scoped(driver)
    assert s.get_owner() is None
    with pytest.raises(ValueError, match="owner"):
        s.retire_owner("unknown", 1)
    assert s.get_owner() is None
    uninitialized = Neo4jWorkflowStore(driver, database=s.database, **{**s.scope, "workspace_id": "uninitialized"})
    with pytest.raises(ScopeMissing):
        uninitialized.get_owner()

    class Offline:
        def session(self, **kwargs):
            raise OSError("database unavailable")

    offline = Neo4jWorkflowStore(Offline(), database=s.database, **s.scope)
    with pytest.raises(OSError):
        offline.get_owner()
    assert s.begin_owner("empty-owner") == 1
    for wrong in (True, 0, -1, 2, "1"):
        with pytest.raises(ValueError):
            s.retire_owner("empty-owner", wrong)
    assert s.retire_owner("empty-owner", 1)
    assert s.get_owner().dirty is False


def test_retirement_commit_ack_loss_replays_exact_identity_even_after_later_epochs(
    completion_input,
):
    from isaaclab_arena.agentic_environment_generation.workflow.neo4j_store import (
        OutcomeUnknown,
    )

    f, handle, artifacts, receipt, _ = completion_input
    f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    s, fence = f.store, handle.fence

    class Proxy:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, name):
            return getattr(self.real, name)

    class Transaction(Proxy):
        def commit(self):
            self.real.commit()
            raise OSError("lost retirement acknowledgement after real commit")

    class Session(Proxy):
        def begin_transaction(self, **kwargs):
            return Transaction(self.real.begin_transaction(**kwargs))

    class Driver(Proxy):
        def session(self, **kwargs):
            return Session(self.real.session(**kwargs))

    failing = Neo4jWorkflowStore(Driver(s.driver), database=s.database, **s.scope)
    with pytest.raises(OutcomeUnknown):
        failing.retire_owner(fence.owner_id, 1)
    independent = Neo4jWorkflowStore(s.driver, database=s.database, **s.scope)
    retired = independent.get_owner()
    assert (retired.owner_id, retired.owner_epoch, retired.dirty) == (
        fence.owner_id,
        1,
        False,
    )
    assert independent.retire_owner(fence.owner_id, 1) is False
    for epoch, name in enumerate(("owner-b", "owner-c", "owner-d"), 2):
        assert independent.begin_owner(name) == epoch
        assert independent.begin_owner(name) == epoch
        active = independent.get_owner()
        assert independent.retire_owner(fence.owner_id, 1) is False
        assert independent.get_owner() == active
        with pytest.raises(ValueError):
            independent.retire_owner(fence.owner_id, epoch)
        with pytest.raises(ValueError, match="retired"):
            independent.begin_owner(fence.owner_id)
        assert independent.retire_owner(name, epoch)
        assert independent.get_owner().dirty is False
    assert independent.get_generation_attempt(fence.run_id).receipt == receipt


@pytest.mark.parametrize("round_index", range(3))
def test_retirement_races_have_one_commit_and_never_clear_replacement(driver, round_index):
    s = scoped(driver)
    assert s.begin_owner("owner-a") == 1
    barrier = Barrier(6)

    def retire(_):
        barrier.wait(timeout=10)
        return s.retire_owner("owner-a", 1)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(retire, range(6)))
    assert results.count(True) == 1 and results.count(False) == 5
    assert s.get_owner().dirty is False
    barrier = Barrier(6)

    def begin_or_replay(index):
        barrier.wait(timeout=10)
        if index < 3:
            return s.retire_owner("owner-a", 1)
        try:
            return s.begin_owner("owner-" + str(index))
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(begin_or_replay, range(6)))
    assert results[:3] == [False] * 3
    assert results[3:].count(2) == 1 and results[3:].count(None) == 2
    owner = s.get_owner()
    assert owner.dirty and owner.owner_epoch == 2
    assert s.retire_owner("owner-a", 1) is False
    assert s.get_owner() == owner


@pytest.mark.parametrize("failure", ["bytes", "database", "cleanup", "acknowledgement"])
def test_real_completion_failure_stops_locally_and_retains_obligations(completion_input, monkeypatch, failure):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        CompletionIncomplete,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        ReconciliationReason,
    )

    f, handle, artifacts, receipt, root = completion_input

    def unavailable(*args, **kwargs):
        raise OSError("private failure detail")

    if failure == "bytes":
        (root / receipt.artifact_directory / "candidate.yaml").write_bytes(b"corrupt")
    elif failure == "database":
        monkeypatch.setattr(f.store, "get_attempt", unavailable)
        monkeypatch.setattr(f.store, "acknowledge_cleanup", unavailable)
        monkeypatch.setattr(f.store, "mark_reconciliation_required", unavailable)
    elif failure == "cleanup":
        monkeypatch.setattr(f.coordinator._worker, "stop_owned", unavailable)
    else:
        monkeypatch.setattr(f.store, "acknowledge_cleanup", unavailable)
    with pytest.raises(CompletionIncomplete) as caught:
        f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert "private" not in str(caught.value)
    assert caught.value.handle is handle and f.coordinator._handle is handle
    assert handle.incomplete and handle.reconciliation_required
    assert handle.fence == receipt.fence and handle.prepared is f.prepared
    if failure != "cleanup":
        assert handle.cleanup is not None and f.calls.count("localstop") == 1
    else:
        assert handle.cleanup is None and handle.cleanup_pending
    if failure == "database":
        assert handle.durable_reconciliation_pending
    else:
        view = f.store.get_attempt(handle.fence)
        assert view.reconciliation_reason == ReconciliationReason.OWNER_OUTCOME_UNCERTAIN
        assert view.receipt == (None if failure == "bytes" else receipt)
        assert f.store.get_run(f.run.run_id).phase != "validation"
    assert f.dispatch() is handle
    assert f.calls.count("send") == f.calls.count("prepare") == 1


@pytest.mark.parametrize("when", ["before", "callback", "concurrent", "offline_before"])
def test_real_completion_cancellation_wins_and_late_receipt_is_diagnostic(completion_input, monkeypatch, when):
    from threading import Thread

    f, handle, artifacts, receipt, _ = completion_input
    threads = []
    if when == "before":
        f.coordinator.cancel("local")
    if when == "offline_before":
        original = f.store.get_run

        def unavailable(*args):
            raise OSError("private offline")

        monkeypatch.setattr(f.store, "get_run", unavailable)
        assert f.coordinator.cancel("local").durable_cancellation_pending
        monkeypatch.setattr(f.store, "get_run", original)

    def protect(_):
        if when == "callback":
            f.coordinator.cancel("local")
        if when == "concurrent":
            thread = Thread(target=lambda: f.coordinator.cancel("local"))
            threads.append(thread)
            thread.start()
            thread.join(2)
            assert not thread.is_alive(), "adoption must not block cancellation"

    try:
        result = f.coordinator.complete("local", receipt, artifacts, protect=protect)
    finally:
        for thread in threads:
            thread.join(5)
    assert result.disposition == "cancelled" and result.run.state == "cancelled"
    assert result.attempt.receipt == receipt and result.attempt.cleanup == handle.cleanup
    assert f.calls.count("localstop") == f.calls.count("send") == 1
    assert f.store.get_run(f.run.run_id).state == "cancelled"
    assert_receipt_storage(f.store, receipt, "diagnostic")


def assert_receipt_storage(store, receipt, disposition):
    with store.driver.session(database=store.database) as session:
        row = session.run(
            "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) WHERE a.attempt_id=$attempt "
            "RETURN a.receipt_json AS receipt, a.receipt_disposition AS disposition",
            **store.scope,
            attempt=receipt.fence.attempt_id,
        ).single(strict=True)
    assert row["receipt"] == receipt.model_dump_json()
    assert row["disposition"] == disposition


@pytest.mark.parametrize("change", ["principal", "fence", "registration"])
def test_real_completion_wrong_local_identity_has_zero_stops(completion_input, change):
    f, handle, artifacts, receipt, _ = completion_input
    principal = "stranger" if change == "principal" else "local"
    if change == "fence":
        receipt = receipt.model_copy(update={"fence": receipt.fence.model_copy(update={"generation": 2})})
    if change == "registration":
        receipt = receipt.model_copy(update={"registration": receipt.registration.model_copy(update={"pid": 101})})
    with pytest.raises((ValueError, PermissionError)):
        f.coordinator.complete(principal, receipt, artifacts, protect=lambda _: None)
    assert "localstop" not in f.calls and handle.cleanup is None
    assert f.store.get_attempt(handle.fence).receipt is None


def test_real_completion_invalid_first_receipt_recovers_original_attempt(
    completion_input,
):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        CompletionIncomplete,
    )

    f, handle, artifacts, receipt, _ = completion_input
    malformed = receipt.model_copy(update={"candidate_yaml_sha256": "b" * 64})
    with pytest.raises(CompletionIncomplete):
        f.coordinator.complete("local", malformed, artifacts, protect=lambda _: None)
    assert f.store.get_attempt(handle.fence).receipt is None
    assert f.store.get_run(f.run.run_id).state == "reconciliation_required"
    assert handle.cleanup is not None and handle.reconciliation_required
    result = f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert result.disposition == "validation" and result.attempt.receipt == receipt
    assert not handle.incomplete and not handle.reconciliation_required
    assert not handle.durable_reconciliation_pending and not handle.cleanup_pending
    assert f.dispatch() is handle
    assert f.calls.count("localstop") == f.calls.count("send") == f.calls.count("prepare") == 1
    assert_receipt_storage(f.store, receipt, "produced")


@pytest.mark.parametrize("committed", [False, True])
def test_real_completion_verified_pin_survives_unknown_commit(completion_input, monkeypatch, tmp_path, committed):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        parse_contract,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        CompletionIncomplete,
    )

    f, handle, artifacts, receipt, _ = completion_input
    original = f.store.commit_generation_receipt

    def unknown(*args):
        assert handle.completion_receipt == receipt, "verified receipt must pin before possible commit"
        if committed:
            original(*args)
        raise OSError("private commit acknowledgement lost")

    monkeypatch.setattr(f.store, "commit_generation_receipt", unknown)
    with pytest.raises(CompletionIncomplete) as caught:
        f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert "private" not in str(caught.value)
    assert f.store.get_attempt(handle.fence).receipt == (receipt if committed else None)
    monkeypatch.setattr(f.store, "commit_generation_receipt", original)
    with ArtifactArea.create(tmp_path / "conflict", store_id="test", registry_id="scope") as area:
        other_artifacts = GenerationArtifacts(area)
        other = other_artifacts.write(
            handle.fence,
            handle.prepared.registration,
            parse_contract(f.run.contract_json),
            b"scene: other\n",
            {"scene": "other"},
            protect=lambda _: None,
        )
        assert other_artifacts.verify(other, protect=lambda _: None) == other
        with pytest.raises(ValueError, match="conflicting"):
            f.coordinator.complete("local", other, other_artifacts, protect=lambda _: None)
    result = f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert result.disposition == "validation"
    assert not handle.incomplete and not handle.reconciliation_required
    assert not handle.durable_reconciliation_pending and not handle.cleanup_pending
    assert f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None) == result
    assert f.calls.count("localstop") == f.calls.count("send") == f.calls.count("prepare") == 1
    assert_receipt_storage(f.store, receipt, "produced")


def test_expired_execution_still_allows_authenticated_completion_and_exact_retry(
    completion_input,
):
    f, handle, artifacts, receipt, _ = completion_input
    f.now[0] = f.auth.expires_at + 1
    calls = f.calls.count("execute_auth")
    result = f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert result.disposition == "validation"
    assert f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None) == result
    assert f.dispatch() is handle
    assert f.calls.count("execute_auth") == calls
    assert f.calls.count("send") == f.calls.count("localstop") == 1


def test_real_completion_conflict_rejected_locally_and_duplicate_rechecks_bytes(
    completion_input,
):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        CompletionIncomplete,
    )

    f, handle, artifacts, receipt, root = completion_input
    f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    count = len(f.calls)
    changed = receipt.model_copy(update={"candidate_yaml_sha256": "b" * 64})
    with pytest.raises(ValueError, match="conflicting"):
        f.coordinator.complete("local", changed, artifacts, protect=lambda _: None)
    assert f.calls[count:] == ["authenticate"]
    (root / receipt.artifact_directory / "candidate.yaml").write_bytes(b"corrupt")
    with pytest.raises(CompletionIncomplete):
        f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert f.calls.count("localstop") == f.calls.count("send") == 1
    assert handle.incomplete


@pytest.mark.parametrize("bypass", ["fake_artifacts", "instance_adopter"])
def test_real_completion_cannot_bypass_concrete_artifact_verification(completion_input, monkeypatch, bypass):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        CompletionIncomplete,
    )

    f, handle, artifacts, receipt, root = completion_input

    class FakeArtifacts:
        def verify(self, value, **kwargs):
            return value

    if bypass == "fake_artifacts":
        artifacts = FakeArtifacts()
    else:
        monkeypatch.setattr(f.coordinator._service, "adopt_generation", lambda *args, **kwargs: True)
        (root / receipt.artifact_directory / "candidate.yaml").write_bytes(b"corrupt")
    with pytest.raises(CompletionIncomplete):
        f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert f.store.get_attempt(handle.fence).receipt is None
    assert handle.incomplete and f.calls.count("localstop") == 1
    with pytest.raises(ValueError):
        f.store.begin_owner("replacement-owner")
    assert f.store.get_attempt(handle.fence).usage_disposition == "fully_reserved_consumption_deferred"


def test_real_completion_retry_reconciles_ack_loss_without_stopping_twice(completion_input, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        CompletionIncomplete,
    )

    f, handle, artifacts, receipt, _ = completion_input
    original = f.store.acknowledge_cleanup

    def unavailable(*args):
        assert original(*args) is True
        raise OSError("private ack loss after actual cleanup commit")

    monkeypatch.setattr(f.store, "acknowledge_cleanup", unavailable)
    with pytest.raises(CompletionIncomplete):
        f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    retained = f.store.get_attempt(handle.fence)
    assert retained.cleanup == handle.cleanup and retained.receipt == receipt
    assert f.store.get_run(f.run.run_id).phase == "validation"
    assert handle.incomplete and handle.reconciliation_required and handle.durable_reconciliation_pending
    assert_receipt_storage(f.store, receipt, "produced")
    monkeypatch.setattr(f.store, "acknowledge_cleanup", original)
    result = f.coordinator.complete("local", receipt, artifacts, protect=lambda _: None)
    assert result.disposition == "validation"
    assert f.store.get_attempt(handle.fence) == result.attempt == retained
    assert f.store.get_run(f.run.run_id) == result.run
    assert not handle.cleanup_pending
    assert not handle.incomplete and not handle.reconciliation_required
    assert not handle.durable_reconciliation_pending
    assert f.calls.count("localstop") == f.calls.count("send") == f.calls.count("prepare") == 1


def test_real_coordinator_completion_observes_validation_and_exact_cleanup(driver, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        parse_contract,
    )

    f = live_coordinator(driver, completion=True)
    handle = f.dispatch()
    with ArtifactArea.create(tmp_path / "area", store_id="test", registry_id="scope") as area:
        artifacts = GenerationArtifacts(area)
        receipt = artifacts.write(
            handle.fence,
            handle.prepared.registration,
            parse_contract(f.run.contract_json),
            b"scene: synthetic\n",
            {"scene": "synthetic"},
            protect=lambda _: None,
        )
        checked = []
        result = f.coordinator.complete("local", receipt, artifacts, protect=checked.append)
        assert result.disposition == "validation"
        assert (result.run.state, result.run.phase) == ("running", "validation")
        assert result.attempt.receipt == receipt and result.attempt.cleanup == handle.cleanup
        assert f.store.get_attempt(handle.fence) == result.attempt
        assert f.calls.count("send") == f.calls.count("prepare") == f.calls.count("localstop") == 1
        assert f.calls.index("db:commit_generation_receipt") < f.calls.index("localstop")
        assert f.calls.index("localstop") < f.calls.index("db:acknowledge_cleanup")
        again = f.coordinator.complete("local", receipt, artifacts, protect=checked.append)
        assert again == result and len(checked) == 2
        assert f.calls.count("localstop") == f.calls.count("send") == f.calls.count("prepare") == 1


def test_real_coordinator_dispatch_retry_authenticated_cancel_exact_cleanup(driver):
    f = live_coordinator(driver)
    handle = f.dispatch()
    retained = f.store.get_attempt(handle.fence)
    assert retained.registration == handle.prepared.registration and retained.released
    before = f.store.snapshot()
    assert f.dispatch() is handle
    assert f.store.snapshot() == before
    for decision, allowance in [
        ("changed", f.reservation),
        ("decision", f.reservation.model_copy(update={"model_tokens": 101})),
    ]:
        with pytest.raises(ValueError, match="conflicting local dispatch"):
            f.coordinator.dispatch("local", expected_version=1, decision_id=decision, reservation=allowance)
    assert f.calls.count("prepare") == f.calls.count("send") == 1
    with pytest.raises(PermissionError):
        f.coordinator.cancel("stranger")
    assert "localstop" not in f.calls and f.store.snapshot() == before
    f.calls.clear()
    result = f.coordinator.cancel("local")
    assert f.calls[:3] == ["authenticate", "localstop", "db:get_run"]
    assert not result.durable_cancellation_pending and not result.cleanup_pending
    assert f.store.get_run(f.run.run_id).state == "cancelled"
    retained = f.store.get_attempt(handle.fence)
    assert retained.status == "cancelled" and retained.cleanup == handle.cleanup
    assert retained.cleanup.registration == retained.registration == handle.prepared.registration
    assert retained.released and retained.receipt is None
    assert retained.usage_disposition == "fully_reserved_consumption_deferred"
    snapshot = f.store.snapshot()
    assert not f.coordinator.cancel("local").durable_cancellation_pending
    assert f.store.snapshot() == snapshot and f.calls.count("localstop") == 1
    assert [e.kind for e in f.store.events_after(0).events].count("AttemptReleased") == 1


def test_real_coordinator_lease_lost_before_release_never_sends(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
    )

    f = live_coordinator(driver, fault="lease_lost")
    with pytest.raises(DispatchIncomplete) as failure:
        f.dispatch()
    handle = failure.value.handle
    retained = f.store.get_attempt(handle.fence)
    assert retained.registration == handle.prepared.registration and not retained.released
    assert "send" not in f.calls and "db:release_attempt" not in f.calls
    assert f.calls.count("localstop") == 1 and handle.cleanup is not None
    assert f.dispatch() is handle and f.calls.count("prepare") == 1
    assert not f.coordinator.cancel("local").durable_cancellation_pending
    assert f.store.get_run(f.run.run_id).state == "cancelled"


@pytest.mark.parametrize("committed", [False, True])
def test_real_coordinator_registration_unknown_preserves_exact_cleanup_obligation(driver, committed):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
    )

    f = live_coordinator(driver, fault="registration_after" if committed else "registration_before")
    with pytest.raises(DispatchIncomplete) as failure:
        f.dispatch()
    handle = failure.value.handle
    retained = f.store.get_attempt(handle.fence)
    assert retained.registration == (handle.prepared.registration if committed else None)
    assert not retained.released and retained.cleanup is None
    assert "send" not in f.calls and f.calls.count("localstop") == 1
    assert handle.cleanup.registration == handle.prepared.registration
    assert f.dispatch() is handle and f.calls.count("prepare") == 1
    for _ in range(2):
        result = f.coordinator.cancel("local")
        assert result.durable_cancellation_pending is not committed
        assert not result.cleanup_pending
        retained = f.store.get_attempt(handle.fence)
        assert retained.cleanup == (handle.cleanup if committed else None)
        assert retained.registration == (handle.prepared.registration if committed else None)
        assert f.store.get_run(f.run.run_id).state == ("cancelled" if committed else "cancel_requested")
    assert f.calls.count("db:register_worker") == 1, "must not launder absent registration during cancellation"
    assert f.calls.count("localstop") == 1 and "send" not in f.calls


def test_real_coordinator_send_failure_persists_reconciliation_and_never_resends(
    driver,
):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        ReconciliationReason,
    )

    f = live_coordinator(driver, fault="send_failure")
    with pytest.raises(DispatchIncomplete) as failure:
        f.dispatch()
    handle = failure.value.handle
    assert handle.incomplete and handle.reconciliation_required
    assert not handle.durable_reconciliation_pending
    assert handle.cleanup is not None and not handle.cleanup_pending
    retained = f.store.get_attempt(handle.fence)
    assert retained.released and retained.reconciliation_reason == ReconciliationReason.OWNER_OUTCOME_UNCERTAIN
    assert retained.registration == handle.prepared.registration and retained.receipt is None
    assert f.store.get_run(f.run.run_id).state == "reconciliation_required"
    snapshot = f.store.snapshot()
    assert f.dispatch() is handle and f.store.snapshot() == snapshot
    assert f.calls.count("send") == f.calls.count("prepare") == f.calls.count("localstop") == 1
    assert [e.kind for e in f.store.events_after(0).events].count("ReconciliationRequired") == 1


@pytest.mark.parametrize("fault", ["pre_claim", "claim_ack_unknown"])
def test_real_coordinator_early_failure_retains_recovery_identifiers(driver, fault):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
    )

    f = live_coordinator(driver, fault=fault)
    with pytest.raises(DispatchIncomplete) as failure:
        f.dispatch()
    handle = failure.value.handle
    assert handle.incomplete and handle.prepared is None
    assert handle.fence is None and handle.cleanup is None
    assert handle.owner_id == f.coordinator._lease.owner_id
    assert handle.owner_epoch == (f.claimed.owner_epoch if f.claimed else None)
    before = f.store.snapshot()
    calls = list(f.calls)
    assert f.dispatch() is handle
    assert f.calls == calls + ["authenticate"] and f.store.snapshot() == before
    assert "prepare" not in f.calls and "send" not in f.calls
    with driver.session(database=f.store.database) as session:
        rows = list(
            session.run(
                "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "OPTIONAL MATCH (i)-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                "RETURN i.intent_id AS intent, a.fence_json AS fence",
                **f.store.scope,
            )
        )
    assert len(rows) == 1 and rows[0]["intent"] == f.intent
    assert rows[0]["fence"] == (f.claimed.model_dump_json() if f.claimed else None)
    # A committed claim with lost ACK cannot provide an acknowledged fence, but
    # the known intent/run/owner recovery identifiers must survive the exception.
    retained_intent = handle.fence.intent_id if handle.fence else getattr(handle, "intent_id", None)
    assert retained_intent == f.intent, (
        f"PRODUCT GAP {fault}: durable intent {f.intent!r}, claimed={f.claimed!r}; "
        f"local diagnostic handle loses recovery identifiers: {handle!r}"
    )


def test_real_coordinator_cancel_before_dispatch_is_terminal_without_attempt(driver):
    f = live_coordinator(driver)
    first = f.coordinator.cancel("local")
    second = f.coordinator.cancel("local")
    with pytest.raises(ValueError, match="locally stopped"):
        f.dispatch()
    assert "prepare" not in f.calls and "send" not in f.calls
    with driver.session(database=f.store.database) as session:
        row = session.run(
            "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
            "RETURN count(i) AS n",
            **f.store.scope,
        ).single(strict=True)
    assert row["n"] == 0
    observed = f.store.get_run(f.run.run_id)
    assert (
        observed.state == "cancelled"
    ), f"PRODUCT GAP: no-attempt cancellation remains {observed.state!r}; first={first!r}, retry={second!r}"
    assert not first.durable_cancellation_pending and not first.cleanup_pending
    assert not second.durable_cancellation_pending and not second.cleanup_pending
    assert observed.phase == "dependency_readiness" and observed.version == 2
    assert f.store.request_cancel(f.run.run_id, 1) == observed
    assert [e.kind for e in f.store.events_after(0).events] == [
        "WorkflowRequested",
        "CancellationRequested",
    ]


def test_real_coordinator_reservation_ack_unknown_retains_command_identity(driver):
    from isaaclab_arena.agentic_environment_generation.workflow.coordinator import (
        DispatchIncomplete,
    )

    f = live_coordinator(driver, fault="reserve_ack_unknown")
    with pytest.raises(DispatchIncomplete) as failure:
        f.dispatch()
    handle = failure.value.handle
    assert handle.run_id == f.run.run_id and handle.decision_id == "decision"
    assert handle.expected_version == 1 and handle.reservation == f.reservation
    assert handle.intent_id is None and handle.fence is None and handle.prepared is None
    calls = list(f.calls)
    assert f.dispatch() is handle and f.calls == calls + ["authenticate"]
    assert f.intent and f.store.get_run(f.run.run_id).state == "running"
    assert "prepare" not in f.calls and "send" not in f.calls


@pytest.mark.parametrize("round_index", range(3))
def test_pending_cancel_vs_reserve_never_fabricates_cleanup(driver, round_index):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        parse_contract,
    )
    from isaaclab_arena.tests.test_environment_workflow_decisions import authority

    f = live_coordinator(driver)
    s = f.store
    contract = parse_contract(f.run.contract_json)
    auth = authority(s, contract)
    barrier = Barrier(2)

    def work(cancel):
        barrier.wait(timeout=10)
        try:
            if cancel:
                return s.request_cancel(f.run.run_id, 1)
            return s.reserve_generation(
                f.run.run_id,
                1,
                "decision",
                auth,
                f.reservation,
                readiness=readiness(contract, auth),
            )
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancelled, intent = list(pool.map(work, (True, False)))
    observed = s.get_run(f.run.run_id)
    if cancelled is not None:
        assert intent is None and observed.state == "cancelled" and observed.phase == "dependency_readiness"
        assert s.request_cancel(f.run.run_id, 1) == observed
    else:
        assert intent and observed.state == "running"
        observed = s.request_cancel(f.run.run_id, observed.version)
        assert observed.state == "cancel_requested"
        with pytest.raises(ValueError, match="not claimable"):
            s.claim_intent(intent, "owner", s.begin_owner("owner"))
    with driver.session(database=s.database) as session:
        rows = list(
            session.run(
                "MATCH (i:ArenaExecutionIntent {deployment_id:$deployment_id, workspace_id:$workspace_id}) "
                "OPTIONAL MATCH (i)-[:HAS_ATTEMPT]->(a:ArenaExecutionAttempt) "
                "RETURN i.intent_id AS intent, i.cleanup_json AS cleanup, a.attempt_id AS attempt",
                **s.scope,
            )
        )
    assert len(rows) == (0 if cancelled is not None else 1)
    assert all(r["cleanup"] is None and r["attempt"] is None for r in rows)
    kinds = [e.kind for e in s.events_after(0).events]
    assert kinds.count("CancellationRequested") == 1
    assert "AttemptCleanupAcknowledged" not in kinds


@pytest.mark.parametrize(
    "case",
    [
        "accept",
        "unknown",
        "cancel_before",
        "cancel_during",
        "budget",
        "forbidden",
        "stale",
        "unsupported",
        "readiness",
        "deadline",
        "retire",
        "released_replay",
        "finish_replay",
        "corrupt_original",
        "observe_budget",
        "unbounded",
        "missing_bound_capability",
        "bound_revoked",
        "managed_accept",
        "managed_cancel_prepare",
        "managed_cancel_execute",
        "managed_prepare_unknown",
        "managed_release_ack",
        "managed_timeout",
        "managed_cleanup_failure",
        "managed_missing_ports",
        "managed_binding_cas",
        "managed_readiness_revoked",
    ],
)
def test_scene_durable_trace_readback_replay(driver, tmp_path, case):
    """Real Neo4j; synthetic ports/schema receipt, never native acceptance."""
    from isaaclab_arena.agentic_environment_generation.workbench.research_artifacts import (
        ArtifactArea,
    )
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.agentic_environment_generation.workflow.artifacts import (
        GenerationArtifacts,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.attempts import (
        GenerationReservation,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import (
        canonical_json,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )
    from isaaclab_arena.agentic_environment_generation.workflow.service import (
        WorkflowService,
    )
    from isaaclab_arena.tests.test_environment_workflow_decisions import authority
    from isaaclab_arena.tests.test_environment_workflow_repairs import scene
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import scene_contract

    s = scoped(driver)
    s.clock = lambda: 100.0
    contract = scene_contract()
    auth = authority(s, contract)
    run = s.admit("scene-trace", "{}", canonical_json(contract), 1)
    intent = s.reserve_generation(
        run.run_id,
        1,
        "generation",
        auth,
        GenerationReservation(
            model_calls=1,
            model_tokens=100,
            cost_ceiling_usd=0.0,
            runtime_allowance_seconds=1.0,
        ),
        readiness=readiness(contract, auth),
    )
    fence = s.claim_intent(intent, "owner", s.begin_owner("owner"))
    reg = s.register_worker(fence, registration(fence))
    assert s.release_attempt(fence, reg.registration_id, auth, readiness=readiness(contract, auth))
    with ArtifactArea.create(tmp_path / "scene", store_id="scene", registry_id="scene") as area:
        artifacts = GenerationArtifacts(area)
        import json

        receipt = artifacts.write(
            fence,
            reg,
            contract,
            json.dumps(scene()).encode(),
            scene(),
            protect=lambda _: None,
        )
        s.commit_generation_receipt(fence, artifacts.verify(receipt, protect=lambda _: None))
        s.acknowledge_cleanup(
            fence,
            CleanupEvidence(
                registration=reg,
                evidence_ref="synthetic-stop",
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            ),
        )
        validation = dict(
            disposition="schema_validated",
            fence=fence.model_dump(mode="json"),
            contract_digest=receipt.contract_digest,
            candidate_yaml_sha256=receipt.candidate_yaml_sha256,
            candidate_json_sha256=receipt.candidate_json_sha256,
            provenance_sha256=receipt.provenance_sha256,
            manifest_sha256=receipt.manifest_sha256,
            normalized_spec_sha256="a" * 64,
            validator_identity="explicitly-synthetic-schema-port",
        )
        candidate = scene_loop.candidate_record(run.run_id, scene(), source_id=fence.attempt_id)
        profile = scene_loop.ScenePortProfile(
            port_id="synthetic-tracer",
            assurance="synthetic",
            producer_ids=tuple(c.evidence_producer for c in contract.criteria),
            observe=scene_loop.SceneReservation(
                model_calls=1,
                model_tokens=100,
                cost_ceiling_usd=0.0,
                runtime_allowance_seconds=1.0,
                realizations=1,
                observations=1,
                steps=10,
            ),
            repair=scene_loop.SceneReservation(
                model_calls=1,
                model_tokens=100,
                cost_ceiling_usd=0.0,
                runtime_allowance_seconds=1.0,
                candidates=1,
                revisions=1,
            ),
        )
        if case.startswith("managed_"):
            profile = scene_loop.ScenePortProfile.model_validate(dict(profile.model_dump(), owned_worker=True))
        if case == "budget":
            profile = profile.model_copy(
                update={"observe": profile.observe.model_copy(update={"model_tokens": 10001})}
            )
        if case == "unsupported":
            profile = profile.model_copy(update={"producer_ids": ()})

        class ReadAuthority:
            def require_read(self, principal):
                assert principal == "local"

        service = WorkflowService(s, ReadAuthority(), None, validate_support=lambda _: None)
        if case == "corrupt_original":
            (tmp_path / "scene" / receipt.artifact_directory / "candidate.json").write_bytes(b"corrupt")
            with pytest.raises(ValueError):
                service.start_scene(
                    "local",
                    run.run_id,
                    artifacts=artifacts,
                    protect=lambda _: None,
                    validate_generation_candidate=lambda *a, **kw: validation,
                    profile=profile,
                )
            assert s.scene_snapshot(run.run_id) is None
            return
        version = s.get_run(run.run_id).version
        first = service.start_scene(
            "local",
            run.run_id,
            artifacts=artifacts,
            protect=lambda _: None,
            validate_generation_candidate=lambda *a, **kw: validation,
            profile=profile,
        )
        assert s.begin_scene(run.run_id, version, candidate, validation, profile) == first
        assert s.scene_snapshot(run.run_id).candidate == candidate

        ports = synthetic_scene_ports(case, s, run, auth)
        ports.profile = profile
        service = WorkflowService(s, ReadAuthority(), None, validate_support=lambda _: None)
        if exercise_scene_worker_case(case, s, service, ports, run, fence, reg, auth, contract, receipt):
            return
        if case == "cancel_before":
            s.request_cancel(run.run_id, s.get_run(run.run_id).version)
        if case == "deadline":
            s.clock = lambda: 159.5
        if case == "missing_bound_capability":
            ports.require_bounded_capability = None
        if case in ("readiness", "deadline", "unbounded", "missing_bound_capability"):
            with pytest.raises(ValueError, match="readiness|deadline|bounded"):
                service.run_scene("local", run.run_id, ports=ports)
            assert ports.calls == []
            return
        if case == "released_replay":
            pending = s.scene_snapshot(run.run_id)
            assert s.release_scene(
                run.run_id,
                pending.intent.intent_id,
                auth,
                readiness=readiness(contract, auth),
            )
            assert not s.release_scene(
                run.run_id,
                pending.intent.intent_id,
                auth,
                readiness=readiness(contract, auth),
            )
            final = service.run_scene("local", run.run_id, ports=ports)
            assert final.run.state == "reconciliation_required" and ports.calls == []
            return
        final = service.run_scene("local", run.run_id, ports=ports)
        if case in (
            "managed_timeout",
            "managed_release_ack",
            "managed_cancel_execute",
            "managed_readiness_revoked",
        ):
            assert final == s.scene_snapshot(run.run_id)
            assert final.intent.worker_cleanup is not None
            assert len(ports.prepared) == len(ports.cleaned) == 1
            assert ports.calls == ([] if case in ("managed_release_ack", "managed_readiness_revoked") else ["observe"])
            assert service.run_scene("local", run.run_id, ports=ports) == final
            if case == "managed_cancel_execute":
                assert final.run.state == "cancelled"
                assert s.retire_owner("owner", fence.owner_epoch)
            else:
                assert final.run.state == "reconciliation_required"
                with pytest.raises(ValueError, match="unresolved"):
                    s.retire_owner("owner", fence.owner_epoch)
            return
        if case == "bound_revoked":
            assert final.run.state == "reconciliation_required"
            assert final.intent.status == "reconciliation_required" and ports.calls == []
            return
        if case == "observe_budget":
            assert final.run.state == "stopped" and final.decision.reason == "budget_exhausted"
            assert ports.calls == ["observe"] * 4
            return
        if case == "finish_replay":
            result = scene_loop.SceneResult(observation=ports.last_observation)
            assert not s.finish_scene(run.run_id, ports.last_intent.intent_id, 1, result)
            with pytest.raises(ValueError, match="conflicting"):
                s.finish_scene(
                    run.run_id,
                    ports.last_intent.intent_id,
                    1,
                    scene_loop.SceneResult(failure="invalid_candidate"),
                )
        if case in ("unknown", "cancel_during"):
            assert final.run.state == ("reconciliation_required" if case == "unknown" else "cancel_requested")
            assert final.intent.status == "reconciliation_required"
            assert ports.calls == ["observe"]
            assert service.run_scene("local", run.run_id, ports=ports) == final
            with pytest.raises(ValueError, match="unresolved"):
                s.retire_owner("owner", fence.owner_epoch)
            return
        if case == "cancel_before":
            assert final.run.state == "cancelled" and ports.calls == []
            return
        if case in ("budget", "forbidden", "stale", "unsupported"):
            assert final.run.state == "stopped"
            assert (
                final.decision.reason
                == {
                    "budget": "budget_exhausted",
                    "forbidden": "repair_rejected",
                    "stale": "stale_cohort",
                    "unsupported": "unsupported_criterion",
                }[case]
            )
            assert len(ports.calls) == {"budget": 0, "unsupported": 0, "forbidden": 2, "stale": 3}[case]
            return
        assert final.run.state == "accepted" and final.decision.action == "accept"
        if case == "managed_accept":
            assert len(ports.prepared) == len(ports.cleaned) == 3
            for scene_id in ports.prepared:
                retained_scene = s.get_scene_intent(run.run_id, scene_id)
                assert retained_scene.status == "produced"
                assert retained_scene.worker_cleanup.registration == retained_scene.worker_registration
            assert s.retire_owner("owner", fence.owner_epoch)
            s.begin_owner("replacement-scene-owner")
            assert s.get_scene_intent(run.run_id, ports.prepared[-1]) == retained_scene
            assert s.get_generation_attempt(run.run_id).receipt == receipt
        if case == "retire":
            assert s.retire_owner("owner", fence.owner_epoch)
            assert s.get_owner().dirty is False
        assert ports.calls == ["observe", "repair", "observe"]
        assert final.candidate.parent_id == candidate.candidate_id
        assert final.candidate.original_id == candidate.candidate_id
        assert scoped(driver, workspace=s.scope["workspace_id"]).scene_snapshot(run.run_id) == final
        assert service.run_scene("local", run.run_id, ports=ports) == final
        assert ports.calls == ["observe", "repair", "observe"]
        assert s.get_generation_attempt(run.run_id).receipt == receipt
        assert (
            service.start_scene(
                "local",
                run.run_id,
                artifacts=artifacts,
                protect=lambda _: None,
                validate_generation_candidate=lambda *a, **kw: validation,
                profile=profile,
            )
            == first
        )
        with driver.session(database=s.database) as session:
            row = session.run(
                "MATCH (child:ArenaWorkflowCandidate {record_id:$child})-[:DERIVED_FROM]->"
                "(original:ArenaWorkflowCandidate {record_id:$original}) "
                "MATCH (e:ArenaWorkflowEvidence)-[:FOR_CANDIDATE]->(child) "
                "MATCH (a:ArenaCriterionAssessment)-[:ASSESSES]->(e) RETURN count(a) AS n",
                child=final.candidate.candidate_id,
                original=candidate.candidate_id,
            ).single()
            assert row["n"] == 1


def synthetic_scene_ports(case, s, run, auth):
    """Build controlled physical-port callbacks; no OS or native evidence."""
    import json

    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )
    from isaaclab_arena.tests.test_environment_workflow_scene_loop import observation

    class SyntheticPorts:
        calls = []
        bound_checks = 0
        prepared = []
        cleaned = []

        def require_held_owner(self):
            # Synthetic physical port: binding/order proof only, NO OS proof.
            return s.get_owner()

        def prepare_worker(self, intent, candidate, original, contract):
            assert intent.worker_fence is not None and intent.released_at is None
            assert len(self.prepared) == len(self.cleaned)
            self.prepared.append(intent.intent_id)
            if case == "managed_cancel_prepare":
                cancelled = s.request_cancel(run.run_id, s.get_run(run.run_id).version)
                assert cancelled.state == "cancel_requested"
            if case == "managed_prepare_unknown":
                raise TimeoutError("synthetic ambiguous prepare")
            return registration(intent.worker_fence)

        def cleanup_worker(self, intent):
            if case == "managed_cleanup_failure":
                raise TimeoutError("synthetic cleanup pending")
            if intent.worker_registration is None:
                raise ValueError("unregistered synthetic prepare remains unresolved")
            assert intent.worker_registration.fence == intent.worker_fence
            self.cleaned.append(intent.intent_id)
            return CleanupEvidence(
                registration=intent.worker_registration,
                evidence_ref="synthetic-scene-stop",
                observation="owned_process_group_stopped",
                remote_effects="unknown",
            )

        def require_bounded_capability(self, principal, contract, reservation):
            # Synthetic port has no provider effects; never provider attestation.
            assert principal == "local"
            self.bound_checks += 1
            return case != "unbounded" and not (case == "bound_revoked" and self.bound_checks > 1)

        def authorize(self, principal, contract, action):
            assert principal == "local"
            return auth

        ready_checks = 0

        def ready(self, contract):
            self.ready_checks += 1
            ready = readiness(contract, auth)
            revoked = case == "managed_readiness_revoked" and self.ready_checks >= 3
            return (
                ready.model_copy(update={"profiles": ready.profiles[:-1]}) if case == "readiness" or revoked else ready
            )

        def execute(self, released, candidate, original, contract):
            self.calls.append(released.action)
            if case in ("unknown", "managed_timeout"):
                raise TimeoutError("synthetic lost acknowledgement")
            if case in ("cancel_during", "managed_cancel_execute"):
                cancelled = s.request_cancel(run.run_id, s.get_run(run.run_id).version)
                assert cancelled.state == "cancel_requested"
            if released.action == "observe":
                output = observation(
                    contract,
                    candidate,
                    "A" if candidate.parent_id is None or case == "stale" else "B",
                    fail=candidate.parent_id is None,
                )
                if case == "observe_budget":
                    output = output.model_copy(update={"evidence": ()})
                    output = output.model_copy(
                        update={"cohort": output.cohort.model_copy(update={"realization_id": str(len(self.calls))})}
                    )
                self.last_observation = output
                self.last_intent = released
                return output
            value = json.loads(candidate.scene_json)
            value["relations"][2]["params"]["x"] = 0.03
            if case == "forbidden":
                value["relations"][2]["params"]["z"] = 1.0
            return value

        def verify_observation(self, value, contract, candidate):
            return value  # Explicit synthetic evidence; production must read actual bytes.

        def validate_candidate(self, value):
            return None  # Explicit synthetic schema; native composition remains separate.

    return SyntheticPorts()


def exercise_scene_worker_case(case, s, service, ports, run, fence, reg, auth, contract, receipt):
    """Exercise synthetic physical-port failure/CAS cases, never OS cleanup proof."""
    from isaaclab_arena.agentic_environment_generation.workflow import scene_loop
    from isaaclab_arena.agentic_environment_generation.workflow.results import (
        CleanupEvidence,
    )

    if case == "managed_missing_ports":
        ports.prepare_worker = None
        with pytest.raises(ValueError, match="managed scene worker ports"):
            service.run_scene("local", run.run_id, ports=ports)
        assert ports.calls == ports.prepared == []
        return True
    if case == "managed_binding_cas":
        pending = s.scene_snapshot(run.run_id)
        scene_id = pending.intent.intent_id
        with pytest.raises(ValueError, match="registration"):
            s.release_scene(run.run_id, scene_id, auth, readiness=readiness(contract, auth))
        sf = s.claim_scene_worker(run.run_id, scene_id, "owner", fence.owner_epoch)
        sr = registration(sf)
        with pytest.raises(ValueError, match="fence"):
            s.register_scene_worker(sf, registration(fence))
        assert s.register_scene_worker(sf, sr)
        assert not s.register_scene_worker(sf, sr)
        with pytest.raises(ValueError, match="conflicting"):
            s.register_scene_worker(sf, sr.model_copy(update={"pid": 999}))
        with ThreadPoolExecutor(max_workers=4) as pool:
            winners = list(
                pool.map(
                    lambda _: s.release_scene(
                        run.run_id,
                        scene_id,
                        auth,
                        readiness=readiness(contract, auth),
                        fence=sf,
                        registration_id=sr.registration_id,
                    ),
                    range(4),
                )
            )
        assert winners.count(True) == 1
        with pytest.raises(ValueError, match="cleanup"):
            s.finish_scene(
                run.run_id,
                scene_id,
                s.get_run(run.run_id).version,
                scene_loop.SceneResult(failure="invalid_candidate"),
            )
        with pytest.raises(ValueError, match="registration"):
            s.acknowledge_scene_cleanup(
                sf,
                CleanupEvidence(
                    registration=reg,
                    evidence_ref="wrong-scene-stop",
                    observation="owned_process_group_stopped",
                    remote_effects="unknown",
                ),
            )
        assert s.get_generation_attempt(run.run_id).receipt == receipt
        return True
    if case == "managed_release_ack":
        release = s.release_scene

        def lost_ack(*args, **kwargs):
            assert release(*args, **kwargs)
            raise OSError("synthetic committed release acknowledgement lost")

        s.release_scene = lost_ack
    if case in (
        "managed_prepare_unknown",
        "managed_cleanup_failure",
        "managed_cancel_prepare",
    ):
        with pytest.raises((ValueError, TimeoutError)):
            service.run_scene("local", run.run_id, ports=ports)
        retained = s.scene_snapshot(run.run_id)
        assert retained.intent.worker_fence is not None and retained.intent.worker_cleanup is None
        if case == "managed_cancel_prepare":
            assert retained.run.state == "cancel_requested"
        with pytest.raises(ValueError, match="unresolved"):
            s.retire_owner("owner", fence.owner_epoch)
        count = len(ports.prepared)
        service.run_scene("local", run.run_id, ports=ports)
        assert len(ports.prepared) == count == 1
        return True
    return False
