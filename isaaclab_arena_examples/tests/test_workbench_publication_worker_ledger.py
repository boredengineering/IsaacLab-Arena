# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Background ledger contracts, using temporary SQLite only."""

import sqlite3

import pytest

from isaaclab_arena_examples.tests.test_workbench_research_publication import api, compared
from isaaclab_arena_examples.tests.test_workbench_research_publication import env as publication_env
from isaaclab_arena_examples.tests.test_workbench_research_publication import grant, identity, receipt

env = publication_env


def worker_api(env):
    attempts = api(env, initialize=True, authorizer=lambda metadata, **scope: ({"secret": "PRIVATE"}, metadata))
    attempts.initialize_worker_support()
    return attempts


def accept(attempts, request="request", operation="write", previous=None, **changes):
    args = dict(
        owner_session="owner",
        principal="owner",
        store_id="store",
        operation=operation,
        request_digest="a" * 64,
        previous_request_id=previous,
    )
    args.update(changes)
    return attempts.accept_request(
        "effect", request, grant(request, "graph_read" if operation == "reconcile" else "graph_write"), **args
    )


def test_explicit_worker_schema_and_readiness(env):
    attempts = api(env, initialize=True)
    assert attempts.worker_support_ready() is False
    before = env[0].db.total_changes
    api(env).get_state("effect")
    assert env[0].db.total_changes == before
    attempts.initialize_worker_support()
    assert attempts.worker_support_ready() is True
    attempts.initialize_worker_support()
    env[0].db.execute("UPDATE publication_worker_meta SET schema_version=99")
    for call in (attempts.worker_support_ready, attempts.initialize_worker_support, lambda: api(env)):
        with pytest.raises(ValueError, match="schema"):
            call()


REQUIRED_TRIGGERS = {
    **{
        f"{table}_no_{action}": table
        for table in ("publication_requests", "publication_workers", "publication_bindings", "publication_receipts")
        for action in ("delete", "update", "replace")
    },
    "publication_workers_monotonic": "publication_workers",
}


@pytest.mark.parametrize("trigger", REQUIRED_TRIGGERS)
@pytest.mark.parametrize("damage", ["missing", "wrong_type", "wrong_table"])
def test_initialized_trigger_damage_refused_before_acceptance_or_release(env, trigger, damage):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    record(attempts, state)
    db = env[0].db
    actual = {
        row[0]: row[1]
        for row in db.execute(
            "SELECT name,tbl_name FROM sqlite_master WHERE type='trigger' AND name GLOB 'publication_*'"
        )
    }
    from isaaclab_arena.agentic_environment_generation.workbench.research_publication import (
        CORE_TRIGGERS,
        WORKER_TRIGGERS,
    )

    assert actual == REQUIRED_TRIGGERS == {**CORE_TRIGGERS, **WORKER_TRIGGERS}
    db.execute(f"DROP TRIGGER {trigger}")
    if damage == "wrong_type":
        db.execute(f"CREATE TABLE {trigger}(value)")
    elif damage == "wrong_table":
        db.execute(
            f"CREATE TRIGGER {trigger} BEFORE DELETE ON publication_states BEGIN SELECT RAISE(ABORT,'wrong'); END"
        )
    before = list(db.iterdump())
    prepared = []
    for call in (
        attempts.worker_support_ready,
        attempts.initialize_worker_support,
        lambda: api(env),
        lambda: api(env, initialize=True),
        lambda: accept(attempts, "next"),
        lambda: release(attempts, state, prepare_private=lambda c, i: prepared.append(c)),
        attempts.pending_workers,
        attempts.recover_worker_dispatch,
    ):
        with pytest.raises(ValueError, match="schema"):
            call()
        assert list(db.iterdump()) == before
    assert prepared == []


@pytest.mark.parametrize("orphan", ["publication_requests", "publication_workers", "publication_workers_monotonic"])
def test_orphan_worker_objects_fail_readiness_and_attachment(env, orphan):
    attempts = api(env, initialize=True)
    env[0].db.execute(f"CREATE TABLE {orphan}(value)")
    before = list(env[0].db.iterdump())
    for call in (attempts.worker_support_ready, attempts.initialize_worker_support, lambda: api(env)):
        with pytest.raises(ValueError, match="schema"):
            call()
        assert list(env[0].db.iterdump()) == before


def test_acceptance_atomic_binding_replay_and_conflicts(env):
    attempts = worker_api(env)
    assert attempts.get_acceptance("request") is None
    result = accept(attempts)
    assert set(result) == {"accepted_new", "accepted", "state"}
    assert result["accepted_new"] is True
    assert result["accepted"]["owner_session"] == "owner"
    assert result["accepted"]["attempt_id"] == result["state"]["attempt_id"]
    attempts.clock = lambda: 300
    assert accept(attempts) == {**result, "accepted_new": False}
    for changes in (
        dict(owner_session="other"),
        dict(principal="other"),
        dict(store_id="other"),
        dict(request_digest="b" * 64),
    ):
        with pytest.raises(ValueError):
            accept(attempts, **changes)
    assert attempts.get_acceptance("request") == result["accepted"]
    for statement in (
        "UPDATE publication_requests SET body='{}'",
        "DELETE FROM publication_requests",
        "INSERT OR REPLACE INTO publication_requests SELECT * FROM publication_requests",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            env[0].db.execute(statement)


def test_acceptance_event_rollback(env):
    attempts = worker_api(env)
    env[0].db.execute(
        "CREATE TRIGGER reject_publication BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'event failed'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        accept(attempts)
    assert attempts.get_acceptance("request") is None
    assert attempts.get_state("effect")["state"] == "pending"
    assert env[0].db.execute("SELECT COUNT(*) FROM publication_bindings").fetchone()[0] == 0


WORKER = {"pid": 4321, "start_ticks": 100, "boot_id": "boot"}


def record(attempts, state, worker=WORKER, capability="graph_write"):
    return attempts.record_worker(
        "effect", **identity(state), capability=capability, pid=worker["pid"], identity=worker
    )


def release(attempts, state, request="request", capability="graph_write", **changes):
    args = dict(
        worker_identity=WORKER,
        grant_metadata=grant(request, capability),
        prepare_private=lambda config, intent: b"PRIVATE",
    )
    args.update(changes)
    return attempts.release_worker("effect", **identity(state), **args)


def test_worker_record_release_once_and_identity_fences(env):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    assert record(attempts, state) is True
    assert record(attempts, state) is False
    assert len(attempts.pending_workers()) == 1
    assert release(attempts, state, worker_identity={**WORKER, "start_ticks": 101}) is None
    assert release(attempts, state) == b"PRIVATE"
    assert release(attempts, state) is None
    assert attempts.get_state("effect")["state"] == "released"
    worker = attempts.pending_workers()[0]
    assert worker["released"] is True and worker["callback_open"] is True
    assert "PRIVATE" not in "\n".join(env[0].db.iterdump())
    assert not attempts.worker_cleaned("effect", **identity(state), worker_identity={**WORKER, "start_ticks": 101})
    assert attempts.worker_cleaned("effect", **identity(state), worker_identity=WORKER)
    assert attempts.pending_workers() == []
    assert not record(attempts, state)


@pytest.mark.parametrize("failure", ["prepare", "oversize", "event", "commit"])
def test_release_failure_returns_no_bytes_and_rolls_back(env, failure):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    record(attempts, state)
    if failure == "event":
        env[0].db.execute(
            "CREATE TRIGGER reject_release BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'event'); END"
        )
    if failure == "commit":
        env[0].db.execute("PRAGMA foreign_keys=ON")
        env[0].db.execute("CREATE TABLE deferred_worker (id INTEGER REFERENCES jobs(id) DEFERRABLE INITIALLY DEFERRED)")
        env[0].db.execute(
            "CREATE TRIGGER reject_commit AFTER UPDATE ON publication_workers BEGIN INSERT INTO deferred_worker VALUES"
            " (-1); END"
        )

    def prepare(config, intent):
        if failure == "prepare":
            raise ValueError("prepare failed")
        return b"x" * (2097153 if failure == "oversize" else 1)

    returned = []
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        returned.append(release(attempts, state, prepare_private=prepare))
    assert returned == []
    assert attempts.get_state("effect")["state"] == "claimed"
    assert attempts.pending_workers()[0]["released"] is False


def finish(attempts, state, **changes):
    args = dict(worker_identity=WORKER, receipt=receipt(), comparator=compared)
    args.update(changes)
    return attempts.complete_worker_verified("effect", **identity(state), **args)


@pytest.mark.parametrize("released", [False, True])
def test_cancel_before_or_after_worker_release(env, released):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    record(attempts, state)
    assert not finish(attempts, state)
    if released:
        release(attempts, state)
    attempts.cancel("effect")
    assert release(attempts, state) is None
    assert finish(attempts, state) is released
    assert attempts.get_state("effect")["state"] == ("verified" if released else "cancelled_no_send")


@pytest.mark.parametrize("released", [False, True])
def test_recovery_fences_before_cleanup_no_replay(env, released):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    record(attempts, state)
    if released:
        release(attempts, state)
    assert attempts.recover_worker_dispatch() == 1
    assert attempts.recover_worker_dispatch() == 0
    assert len(attempts.pending_workers()) == 1
    assert not attempts.pending_workers()[0]["callback_open"]
    assert not finish(attempts, state)
    assert release(attempts, state) is None
    operation = "reconcile" if released else "renew"
    with pytest.raises(ValueError, match="uncleaned"):
        accept(attempts, "next", operation, "request")
    attempts.worker_cleaned("effect", **identity(state), worker_identity=WORKER)
    next_state = accept(attempts, "next", operation, "request")["state"]
    assert not finish(attempts, state)
    assert next_state["generation"] == 2
    assert not record(attempts, state)


def test_read_worker_requires_actual_release_and_unknown_closes_callback(env):
    attempts = worker_api(env)
    write = accept(attempts)["state"]
    record(attempts, write)
    release(attempts, write)
    assert attempts.close_worker_unknown("effect", **identity(write), worker_identity=WORKER)
    assert not finish(attempts, write)
    with pytest.raises(ValueError):
        accept(attempts, "read", "reconcile", "request")
    attempts.worker_cleaned("effect", **identity(write), worker_identity=WORKER)
    read = accept(attempts, "read", "reconcile", "request")["state"]
    record(attempts, read, capability="graph_read")
    assert not finish(attempts, read)
    assert not attempts.close_worker_unknown("effect", **identity(read), worker_identity=WORKER)
    assert release(attempts, read, "read", "graph_read") == b"PRIVATE"
    assert attempts.get_state("effect")["reconciliation"] == {"state": "released"}
    assert finish(attempts, read)
    assert not attempts.close_worker_unknown("effect", **identity(read), worker_identity=WORKER)
    assert attempts.get_state("effect")["state"] == "verified"


def test_background_claim_cannot_use_unfenced_sync_release_or_completion(env):
    attempts = worker_api(env)
    write = accept(attempts)["state"]
    assert not attempts.release("effect", **identity(write), grant_metadata=grant())
    record(attempts, write)
    release(attempts, write)
    assert not attempts.complete_verified("effect", **identity(write), receipt=receipt(), comparator=compared)
    attempts.close_worker_unknown("effect", **identity(write), worker_identity=WORKER)
    with pytest.raises(ValueError, match="uncleaned"):
        attempts.claim_reconciliation("effect", "read", grant("read", "graph_read"))


@pytest.mark.parametrize("released", [False, True])
def test_cleanup_alone_pauses_and_closes_outcome(env, released):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    record(attempts, state)
    if released:
        release(attempts, state)
    attempts.worker_cleaned("effect", **identity(state), worker_identity=WORKER)
    assert attempts.get_state("effect")["state"] == ("unknown" if released else "blocked_authorization")
    assert not finish(attempts, state)
    assert not attempts.get_state("effect")["write_callback_open"]


def test_acceptance_requires_actual_store_and_same_journal(env):
    attempts = worker_api(env)
    env[1].get_reservation = lambda _: {"store_id": "store", "source": {"job_id": env[1].job["id"]}}
    with pytest.raises(ValueError, match="store"):
        accept(attempts, store_id="wrong")
    env[1].journal = object()
    with pytest.raises(ValueError, match="Journal"):
        accept(attempts)


@pytest.mark.parametrize("table", ["publication_requests", "publication_workers"])
@pytest.mark.parametrize("failure", ["insert", "commit"])
def test_request_and_worker_insert_failures_are_atomic(env, table, failure):
    attempts = worker_api(env)
    state = accept(attempts)["state"] if table == "publication_workers" else None
    if failure == "insert":
        env[0].db.execute(
            f"CREATE TRIGGER reject_insert BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'insert failed'); END"
        )
    else:
        env[0].db.execute("PRAGMA foreign_keys=ON")
        env[0].db.execute("CREATE TABLE deferred_atomic (id INTEGER REFERENCES jobs(id) DEFERRABLE INITIALLY DEFERRED)")
        env[0].db.execute(
            f"CREATE TRIGGER reject_commit AFTER INSERT ON {table} BEGIN INSERT INTO deferred_atomic VALUES (-1); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        record(attempts, state) if state else accept(attempts)
    assert attempts.pending_workers() == []
    if state is None:
        assert attempts.get_acceptance("request") is None
        assert attempts.get_state("effect")["state"] == "pending"
        assert env[0].db.execute("SELECT COUNT(*) FROM publication_bindings").fetchone()[0] == 0
    else:
        assert attempts.get_state("effect") == state


@pytest.mark.parametrize(
    "changes",
    [dict(effect_id="other"), dict(capability="graph_read"), dict(request_id="other"), dict(target_profile="other")],
)
def test_background_grant_scope_rejected_without_acceptance(env, changes):
    attempts = worker_api(env)
    with pytest.raises(ValueError):
        attempts.accept_request(
            "effect",
            "request",
            grant(**changes),
            owner_session="owner",
            principal="owner",
            store_id="store",
            operation="write",
            request_digest="a" * 64,
        )
    assert attempts.get_acceptance("request") is None


def test_worker_capability_and_immutable_identity(env):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    with pytest.raises(ValueError):
        record(attempts, state, capability="graph_read")
    record(attempts, state)
    for statement in (
        "UPDATE publication_workers SET body='{}'",
        "DELETE FROM publication_workers",
        "INSERT OR REPLACE INTO publication_workers SELECT * FROM publication_workers",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            env[0].db.execute(statement)
    assert not record(attempts, state, worker={**WORKER, "start_ticks": 101})


@pytest.mark.parametrize("bad_identity", [None, {}, {"pid": 4321}])
def test_missing_identity_cannot_release_clean_or_complete(env, bad_identity):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    record(attempts, state)
    assert release(attempts, state, worker_identity=bad_identity) is None
    assert not attempts.worker_cleaned("effect", **identity(state), worker_identity=bad_identity)
    release(attempts, state)
    assert not finish(attempts, state, worker_identity=bad_identity)
    assert not attempts.close_worker_unknown("effect", **identity(state), worker_identity=bad_identity)


def test_authorization_session_binding_rechecked_at_release(env):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    record(attempts, state)
    prepared = []

    def expired_session(metadata, **scope):
        raise ValueError("session binding expired")

    attempts.authorizer = expired_session
    with pytest.raises(ValueError, match="session"):
        release(attempts, state, prepare_private=lambda c, i: prepared.append(c))
    assert prepared == []
    assert not attempts.pending_workers()[0]["released"]


def test_worker_receipt_and_recovery_event_failures_rollback(env):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    record(attempts, state)
    release(attempts, state)
    env[0].db.execute("CREATE TRIGGER reject_outcome BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'event'); END")
    for action in (
        lambda: finish(attempts, state),
        attempts.recover_worker_dispatch,
        lambda: attempts.worker_cleaned("effect", **identity(state), worker_identity=WORKER),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            action()
        assert attempts.get_state("effect")["state"] == "released"
        assert attempts.get_state("effect")["receipt"] is None
        assert attempts.pending_workers()[0]["callback_open"]


def test_background_read_cannot_use_synchronous_execution(env):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    record(attempts, state)
    release(attempts, state)
    attempts.close_worker_unknown("effect", **identity(state), worker_identity=WORKER)
    attempts.worker_cleaned("effect", **identity(state), worker_identity=WORKER)
    read = accept(attempts, "read", "reconcile")["state"]
    calls = []
    assert not attempts.execute_reconciliation(
        "effect",
        **identity(read),
        grant_metadata=grant("read", "graph_read"),
        operation=lambda *a: calls.append(1),
        comparator=compared,
    )
    assert calls == []


def test_worker_lifecycle_sql_cannot_reopen_or_erase_release(env):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    record(attempts, state)
    release(attempts, state)
    attempts.close_worker_unknown("effect", **identity(state), worker_identity=WORKER)
    for statement in ("UPDATE publication_workers SET released=0", "UPDATE publication_workers SET callback_open=1"):
        with pytest.raises(sqlite3.IntegrityError):
            env[0].db.execute(statement)
    attempts.worker_cleaned("effect", **identity(state), worker_identity=WORKER)
    with pytest.raises(sqlite3.IntegrityError):
        env[0].db.execute("UPDATE publication_workers SET cleaned=0")


def test_registry_different_journal_refused_even_on_attach(env):
    api(env, initialize=True)
    env[1].journal = object()
    with pytest.raises(ValueError, match="Journal"):
        api(env)


def cancelled_write_cleaned(attempts):
    write = accept(attempts)["state"]
    assert record(attempts, write)
    assert release(attempts, write) == b"PRIVATE"
    assert attempts.cancel("effect")["cancelled"]
    assert attempts.close_worker_unknown("effect", **identity(write), worker_identity=WORKER)
    assert attempts.worker_cleaned("effect", **identity(write), worker_identity=WORKER)
    return write


def test_cancelled_write_allows_separately_authorized_read_lifecycle(env):
    attempts = worker_api(env)
    write = cancelled_write_cleaned(attempts)
    read = accept(attempts, "read", "reconcile", "request")["state"]
    assert read["cancelled"]
    assert record(attempts, read, capability="graph_read")
    assert not finish(attempts, read)
    assert release(attempts, read, "read", "graph_read") == b"PRIVATE"
    assert not finish(attempts, write)
    assert finish(attempts, read)
    assert attempts.worker_cleaned("effect", **identity(read), worker_identity=WORKER)
    final = attempts.get_state("effect")
    assert final["cancelled"] and final["state"] == "verified"
    assert final["receipt"] == receipt()
    assert attempts.pending_workers() == []


@pytest.mark.parametrize("phase", ["accepted", "recorded", "released"])
@pytest.mark.parametrize("historical_cancel", [False, True])
def test_cancel_current_read_fences_dispatch_and_callbacks(env, phase, historical_cancel):
    attempts = worker_api(env)
    write = accept(attempts)["state"]
    assert record(attempts, write)
    assert release(attempts, write) == b"PRIVATE"
    if historical_cancel:
        attempts.cancel("effect")
    assert attempts.close_worker_unknown("effect", **identity(write), worker_identity=WORKER)
    assert attempts.worker_cleaned("effect", **identity(write), worker_identity=WORKER)
    read = accept(attempts, "read", "reconcile")["state"]
    if phase != "accepted":
        assert record(attempts, read, capability="graph_read")
    if phase == "released":
        assert release(attempts, read, "read", "graph_read") == b"PRIVATE"
    cancelled = attempts.cancel("effect")
    assert cancelled["cancelled"]
    assert cancelled["reconciliation"] == {"state": "unknown"}
    assert attempts.cancel("effect") == cancelled
    assert not record(attempts, read, capability="graph_read")
    prepared = []
    assert release(attempts, read, "read", "graph_read", prepare_private=lambda *a: prepared.append(1)) is None
    assert prepared == []
    assert not finish(attempts, read)
    assert not attempts.close_worker_unknown("effect", **identity(read), worker_identity=WORKER)
    assert not attempts.complete_verified("effect", **identity(read), receipt=receipt(), comparator=compared)
    if phase != "accepted":
        assert not attempts.pending_workers()[0]["callback_open"]
        with pytest.raises(ValueError, match="uncleaned"):
            accept(attempts, "next", "reconcile", "read")
        assert attempts.worker_cleaned("effect", **identity(read), worker_identity=WORKER)
    fresh = accept(attempts, "next", "reconcile", "read")["state"]
    assert record(attempts, fresh, capability="graph_read")
    assert release(attempts, fresh, "next", "graph_read") == b"PRIVATE"
    assert not finish(attempts, read)
    assert finish(attempts, fresh)


@pytest.mark.parametrize("pause", ["recover", "block"])
def test_legacy_renew_cannot_drop_background_ownership(env, pause):
    attempts = worker_api(env)
    write = accept(attempts)["state"]
    assert record(attempts, write)
    if pause == "recover":
        assert attempts.recover_worker_dispatch() == 1
    else:
        assert attempts.block_authorization("effect", **identity(write))
    paused = attempts.get_state("effect")
    calls = []
    for cleaned in (False, True):
        error = "background" if cleaned else "uncleaned"
        for claim in (
            lambda: attempts.renew("effect", "next", grant("next"), previous_request_id="request"),
            lambda: attempts.claim("effect", "next", grant("next")),
        ):
            with pytest.raises(ValueError, match=error):
                claim()
            assert attempts.get_state("effect") == paused
            assert attempts.get_acceptance("next") is None
            assert env[0].db.execute("SELECT COUNT(*) FROM publication_bindings").fetchone()[0] == 1
        assert not attempts.execute_write(
            "effect",
            **identity(write),
            grant_metadata=grant(),
            operation=lambda *a: calls.append(1),
            comparator=compared,
        )
        if not cleaned:
            with pytest.raises(ValueError, match="uncleaned"):
                accept(attempts, "next", "renew", "request")
            assert attempts.worker_cleaned("effect", **identity(write), worker_identity=WORKER)
    assert calls == []
    fresh = accept(attempts, "next", "renew", "request")["state"]
    assert fresh["generation"] == write["generation"] + 1
    assert attempts.get_acceptance("next")["owner_session"] == "owner"
    assert not attempts.execute_write(
        "effect",
        **identity(fresh),
        grant_metadata=grant("next"),
        operation=lambda *a: calls.append(1),
        comparator=compared,
    )
    assert calls == []
    assert record(attempts, fresh)
    assert release(attempts, fresh, "next") == b"PRIVATE"
    assert finish(attempts, fresh)


@pytest.mark.parametrize("predecessor", ["write", "read"])
def test_direct_read_claim_cannot_drop_background_ownership(env, predecessor):
    attempts = worker_api(env)
    state = accept(attempts)["state"]
    assert record(attempts, state)
    assert release(attempts, state) == b"PRIVATE"
    assert attempts.close_worker_unknown("effect", **identity(state), worker_identity=WORKER)
    if predecessor == "read":
        assert attempts.worker_cleaned("effect", **identity(state), worker_identity=WORKER)
        state = accept(attempts, "read", "reconcile")["state"]
        assert record(attempts, state, capability="graph_read")
        assert release(attempts, state, "read", "graph_read") == b"PRIVATE"
        assert attempts.close_worker_unknown("effect", **identity(state), worker_identity=WORKER)
    before = attempts.get_state("effect")
    for cleaned in (False, True):
        with pytest.raises(ValueError, match="background" if cleaned else "uncleaned"):
            attempts.claim_reconciliation("effect", "next", grant("next", "graph_read"))
        assert attempts.get_state("effect") == before
        if not cleaned:
            assert attempts.worker_cleaned("effect", **identity(state), worker_identity=WORKER)
    fresh = accept(attempts, "next", "reconcile", state["request_id"])["state"]
    assert record(attempts, fresh, capability="graph_read")
    assert release(attempts, fresh, "next", "graph_read") == b"PRIVATE"
    assert finish(attempts, fresh)


@pytest.mark.parametrize("released", [False, True])
@pytest.mark.parametrize("historical_cancel", [False, True])
def test_sync_read_cancellation_closes_current_attempt_only(env, released, historical_cancel):
    attempts = api(env, initialize=True, authorizer=lambda metadata, **scope: ({}, metadata))
    write = attempts.claim("effect", "request", grant())
    assert attempts.release("effect", **identity(write), grant_metadata=grant())
    if historical_cancel:
        attempts.cancel("effect")
    assert attempts.mark_unknown("effect", **identity(write))
    read = attempts.claim_reconciliation("effect", "read", grant("read", "graph_read"))
    calls = []

    def operation(*args):
        calls.append(1)
        attempts.cancel("effect")
        return receipt()

    if not released:
        attempts.cancel("effect")
    assert not attempts.execute_reconciliation(
        "effect", **identity(read), grant_metadata=grant("read", "graph_read"), operation=operation, comparator=compared
    )
    assert calls == ([1] if released else [])
    assert not attempts.complete_verified("effect", **identity(read), receipt=receipt(), comparator=compared)
    fresh = attempts.claim_reconciliation("effect", "next", grant("next", "graph_read"))
    assert fresh["cancelled"]
    assert attempts.execute_reconciliation(
        "effect",
        **identity(fresh),
        grant_metadata=grant("next", "graph_read"),
        operation=lambda *a: receipt(),
        comparator=compared,
    )
    assert attempts.get_state("effect")["cancelled"]


def test_recovered_read_and_new_read_fence_old_worker(env):
    attempts = worker_api(env)
    write = accept(attempts)["state"]
    record(attempts, write)
    release(attempts, write)
    attempts.close_worker_unknown("effect", **identity(write), worker_identity=WORKER)
    attempts.worker_cleaned("effect", **identity(write), worker_identity=WORKER)
    read = accept(attempts, "read", "reconcile")["state"]
    record(attempts, read, capability="graph_read")
    release(attempts, read, "read", "graph_read")
    assert attempts.recover_worker_dispatch() == 1
    assert not finish(attempts, read)
    with pytest.raises(ValueError, match="uncleaned"):
        accept(attempts, "read-next", "reconcile", "read")
    attempts.worker_cleaned("effect", **identity(read), worker_identity=WORKER)
    next_read = accept(attempts, "read-next", "reconcile", "read")["state"]
    record(attempts, next_read, capability="graph_read")
    release(attempts, next_read, "read-next", "graph_read")
    assert not finish(attempts, read)
    assert finish(attempts, next_read)
