# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Synthetic transaction contracts, not real Neo4j concurrency proofs."""
from dataclasses import FrozenInstanceError

import pytest


def schema_rows():
    return [
        dict(entityType="NODE", type="UNIQUENESS", labelsOrTypes=[label], properties=fields)
        for label, fields in [
            ("ArenaWorkflowControl", ["deployment_id", "workspace_id"]),
            ("ArenaWorkflowRun", ["deployment_id", "workspace_id", "operation_id"]),
            ("ArenaWorkflowRun", ["deployment_id", "workspace_id", "run_id"]),
            ("ArenaWorkflowEvent", ["deployment_id", "workspace_id", "sequence"]),
        ]
    ]


def test_schema_verification_and_explicit_scope_initialization():
    d = Driver([schema_rows(), schema_rows(), [{"floor": 0, "ceiling": 0}]])
    s = store(d)
    assert s.verify_schema() is True
    s.initialize_scope()
    queries = [q for q, _ in d.calls]
    assert sum(q.startswith("SHOW CONSTRAINTS") for q in queries) == 2
    assert not any("CREATE CONSTRAINT" in q for q in queries)
    assert any("MERGE (c:ArenaWorkflowControl" in q for q in queries)
    assert all(p == {"database": "explicit-db"} for q, p in d.calls if q == "session")
    assert all(p == {"timeout": 5} for q, p in d.calls if q == "begin")


def test_missing_schema_cannot_initialize():
    d = Driver([[]])
    with pytest.raises(api().SchemaMissing):
        store(d).initialize_scope()
    assert not any("MERGE" in q for q, _ in d.calls)


@pytest.mark.parametrize("failure", ["commit", "tx.close", "session.close"])
def test_cleanup_or_unknown_commit_never_returns_success(failure):
    d = Driver([schema_rows()], fail=failure)
    with pytest.raises(api().OutcomeUnknown):
        store(d).verify_schema()
    assert d.calls[-1][0] == "session.close"
    assert sum(q == "begin" for q, _ in d.calls) == 1


def run_row(**changes):
    return dict(
        run_id="run",
        operation_id="op",
        request_json='{"a":1}',
        contract_json='{"accepted":1}',
        version=1,
        state="pending",
        phase="dependency_readiness",
        event_cursor=1,
        **changes,
    )


def test_admission_locks_before_replay_and_capacity_and_retains_contract():
    row = run_row()
    d = Driver([[{"floor": 0, "ceiling": 0}], [], [{"pending": 0}], [{"run": row}]])
    result = store(d).admit("op", row["request_json"], row["contract_json"], 1)
    assert result.operation_id == "op" and result.event_cursor == 1
    with pytest.raises(FrozenInstanceError):
        result.state = "running"
    queries = [(q, p) for q, p in d.calls if "MATCH" in q]
    assert "SET c.revision=c.revision+1" in queries[0][0]
    assert "operation_id" in queries[1][0]
    assert "count" in queries[2][0]
    assert all(p["deployment_id"] == "d" and p["workspace_id"] == "w" for _, p in queries)
    d = Driver([[{"floor": 0, "ceiling": 1}], [{"run": row}]])
    replay = store(d).admit("op", row["request_json"], '{"accepted":2}', 0)
    assert replay == result
    assert not any("count(" in q or "CREATE (r" in q for q, _ in d.calls)


def test_conflict_and_capacity_and_missing_scope():
    row = run_row()
    d = Driver([[{"floor": 0, "ceiling": 1}], [{"run": row}]])
    with pytest.raises(api().SubmissionConflict):
        store(d).admit("op", '{"a":2}', "{}", 1)
    d = Driver([[{"floor": 0, "ceiling": 1}], [], [{"pending": 1}]])
    with pytest.raises(api().CapacityExceeded):
        store(d).admit("other", "{}", "{}", 1)
    d = Driver([[]])
    with pytest.raises(api().ScopeMissing):
        store(d).admit("op", "{}", "{}", 1)
    assert not any("MERGE" in q for q, _ in d.calls)


def test_lookup_and_get_share_canonical_view_and_scope():
    row = run_row()
    d = Driver([[{"floor": 0, "ceiling": 1}], [{"run": row}], [{"floor": 0, "ceiling": 1}], [{"run": row}]])
    s = store(d, "other")
    assert s.lookup_submission("op", row["request_json"]) == s.get_run("run")
    assert all(p["workspace_id"] == "other" for q, p in d.calls if "MATCH" in q)


@pytest.mark.parametrize("raw", ['{ "a":1}', '{"a":NaN}', '{"a":1,"a":1}', "[]"])
def test_noncanonical_request_rejected_without_io(raw):
    d = Driver()
    with pytest.raises(ValueError):
        store(d).admit("op", raw, "{}", 1)
    assert not d.calls


def test_snapshot_and_event_page_hold_control_lock_and_bounds():
    row = run_row()
    event = dict(sequence=1, run_id="run", operation_id="op", kind="WorkflowRequested", schema_version=1)
    d = Driver([[{"floor": 0, "ceiling": 1}], [{"run": row}], [{"floor": 0, "ceiling": 1}], [{"event": event}]])
    s = store(d)
    snap = s.snapshot()
    assert snap.cursor == 1 and snap.floor == 0 and snap.runs[0].run_id == "run"
    page = s.events_after(0, limit=1)
    assert page.ceiling == 1 and page.cursor == 1 and page.events[0].sequence == 1
    queries = [(q, p) for q, p in d.calls if "MATCH" in q]
    assert "SET c.revision=c.revision+1" in queries[0][0]
    assert "SET c.revision=c.revision+1" in queries[2][0]
    assert "ORDER BY e.sequence" in queries[3][0] and "LIMIT $limit" in queries[3][0]
    assert queries[3][1]["ceiling"] == 1


@pytest.mark.parametrize("cursor", [-1, 1, 4])
def test_cursor_below_floor_or_above_ceiling_is_rejected(cursor):
    d = Driver([[{"floor": 2, "ceiling": 3}]])
    with pytest.raises(api().ReplayGap):
        store(d).events_after(cursor)
    assert not any("ArenaWorkflowEvent" in q for q, _ in d.calls)


@pytest.mark.parametrize("limit", [0, 1001, True])
def test_page_bound_is_enforced_before_io(limit):
    d = Driver()
    with pytest.raises(ValueError):
        store(d).events_after(0, limit)
    assert not d.calls


def test_lock_uses_constant_write_before_dependent_increment():
    d = Driver([[{"floor": 0, "ceiling": 0}], []])
    store(d).snapshot()
    query = next(q for q, _ in d.calls if "MATCH" in q)
    assert query.index("SET c.lock_anchor=true") < query.index("SET c.revision=c.revision+1")


@pytest.mark.parametrize("field", ["database", "deployment_id", "workspace_id"])
def test_empty_scope_identifiers_rejected_without_io(field):
    d = Driver()
    values = dict(database="db", deployment_id="d", workspace_id="w")
    values[field] = ""
    with pytest.raises(ValueError):
        api().Neo4jWorkflowStore(d, **values)
    assert not d.calls


@pytest.mark.parametrize("operation", ["", None, 1, True, [], "a" * 129, "a/b", " a", "a\n", "é", "-a"])
@pytest.mark.parametrize("method", ["lookup_submission", "admit"])
def test_invalid_operation_rejected_without_io(operation, method):
    d = Driver()
    with pytest.raises(ValueError):
        if method == "admit":
            store(d).admit(operation, "{}", "{}", 1)
        else:
            store(d).lookup_submission(operation, "{}")
    assert not d.calls


def api():
    try:
        from isaaclab_arena.agentic_environment_generation.workflow import neo4j_store

        return neo4j_store
    except ModuleNotFoundError:
        pytest.fail("Neo4j workflow store is not implemented")


class Driver:
    def __init__(self, replies=(), fail=None):
        self.replies = list(replies)
        self.calls = []
        self.fail = fail

    def session(self, **kwargs):
        self.calls.append(("session", kwargs))
        return Session(self)


class Session:
    def __init__(self, driver):
        self.d = driver

    def begin_transaction(self, **kwargs):
        self.d.calls.append(("begin", kwargs))
        return Transaction(self.d)

    def close(self):
        self.d.calls.append(("session.close", {}))
        if self.d.fail == "session.close":
            raise RuntimeError("session close failed")


class Transaction:
    def __init__(self, driver):
        self.d = driver

    def run(self, query, **params):
        self.d.calls.append((query, params))
        assert self.d.replies, query
        return self.d.replies.pop(0)

    def commit(self):
        self.d.calls.append(("commit", {}))
        if self.d.fail == "commit":
            raise RuntimeError("commit unknown")

    def close(self):
        self.d.calls.append(("tx.close", {}))
        if self.d.fail == "tx.close":
            raise RuntimeError("transaction close failed")


def store(driver, workspace="w"):
    return api().Neo4jWorkflowStore(driver, database="explicit-db", deployment_id="d", workspace_id=workspace)


def test_constructor_is_driver_free_and_schema_is_explicit():
    d = Driver()
    s = store(d)
    assert not d.calls
    ddl = s.schema_requirements()
    assert len(ddl) == 4
    assert all("CREATE CONSTRAINT" in item for item in ddl)
    assert not d.calls


@pytest.mark.parametrize("failure", [OSError, TimeoutError])
@pytest.mark.parametrize("phase", ["session", "begin_transaction", "run"])
def test_initial_lookup_transport_failure_is_store_unavailable(monkeypatch, failure, phase):
    target = {"session": Driver, "begin_transaction": Session, "run": Transaction}[phase]

    def fail(*args, **kwargs):
        raise failure("private transport detail")

    monkeypatch.setattr(target, phase, fail)
    with pytest.raises(api().StoreUnavailable, match="^workflow store unavailable$"):
        store(Driver()).lookup_submission("op", "{}")


@pytest.mark.parametrize("failure", ["commit", "tx.close", "session.close"])
def test_lookup_unknown_outcomes_are_not_outages(failure):
    d = Driver([[{"floor": 0, "ceiling": 0}], []], fail=failure)
    with pytest.raises(api().OutcomeUnknown):
        store(d).lookup_submission("op", "{}")


@pytest.mark.parametrize("failure", [ValueError, TypeError, RuntimeError])
def test_lookup_programming_errors_propagate(monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure("programming error")

    monkeypatch.setattr(Transaction, "run", fail)
    with pytest.raises(failure, match="programming error"):
        store(Driver()).lookup_submission("op", "{}")


def test_conflict_read_is_not_an_outage():
    d = Driver([[{"floor": 0, "ceiling": 1}], [{"run": run_row()}]])
    with pytest.raises(api().SubmissionConflict):
        store(d).lookup_submission("op", '{"a":2}')


@pytest.mark.parametrize("name", ["ServiceUnavailable", "SessionExpired"])
def test_real_optional_driver_transport_errors_are_classified(monkeypatch, name):
    import importlib

    try:
        exceptions = importlib.import_module("neo4j.exceptions")
    except ModuleNotFoundError as exc:
        assert exc.name == "neo4j"
        assert api()._lookup_transport_errors() == (OSError,)
        return

    def fail(*args, **kwargs):
        raise getattr(exceptions, name)("private detail")

    monkeypatch.setattr(Driver, "session", fail)
    with pytest.raises(api().StoreUnavailable):
        store(Driver()).lookup_submission("op", "{}")


@pytest.mark.parametrize("phase", ["commit", "transaction_close", "session_close"])
def test_lookup_transport_errors_during_commit_or_cleanup_remain_unknown(monkeypatch, phase):
    target, method = {
        "commit": (Transaction, "commit"),
        "transaction_close": (Transaction, "close"),
        "session_close": (Session, "close"),
    }[phase]

    def fail(*args, **kwargs):
        raise OSError("private transport detail")

    monkeypatch.setattr(target, method, fail)
    d = Driver([[{"floor": 0, "ceiling": 0}], []])
    with pytest.raises(api().OutcomeUnknown):
        store(d).lookup_submission("op", "{}")


@pytest.mark.parametrize("operation", ["a", "A0_.:-z", "A" * 128])
def test_valid_operation_ids_reach_lookup_unchanged(operation):
    d = Driver([[{"floor": 0, "ceiling": 0}], []])
    assert store(d).lookup_submission(operation, "{}") is None
    assert [p["identity"] for _, p in d.calls if "identity" in p] == [operation]
