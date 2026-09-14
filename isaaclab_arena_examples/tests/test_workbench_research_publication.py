# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Publication fencing with real temporary SQLite and detached registry contract."""

import copy
import importlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena.agentic_environment_generation.workbench.research_registry import digest

MODULE = "isaaclab_arena.agentic_environment_generation.workbench.research_publication"


class Registry:
    registry_id = "registry"

    def __init__(self, job):
        self.job = job
        self.intent = dict(
            schema_version=1,
            registry_id=self.registry_id,
            reservation_id="reservation",
            effect_id="effect",
            target_profile="graph",
            payload={"nodes": []},
            payload_sha256=digest({"nodes": []}),
            state="pending",
        )

    def get_publication_intent(self, effect_id):
        assert effect_id == "effect"
        return copy.deepcopy(self.intent)

    def get_reservation(self, reservation_id):
        assert reservation_id == "reservation"
        return {"source": {"job_id": self.job["id"]}}

    def get_commit(self, reservation_id):
        assert reservation_id == "reservation"
        return {"publication_intent_id": "effect"}


def grant(request="request", capability="graph_write", **changes):
    result = dict(
        grant_id="grant-" + request,
        request_id=request,
        effect_id="effect",
        target_profile="graph",
        payload_sha256=digest({"nodes": []}),
        capability=capability,
        expires_at=200.0,
    )
    result.update(changes)
    return result


def protect(value):
    return copy.deepcopy(value)


@pytest.fixture
def env(tmp_path):
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        job = journal.submit("owner", "default", "generate", "source", {"prompt": "public"})
        registry = Registry(job)
        yield journal, registry


def api(env, **kwargs):
    module = importlib.import_module(MODULE)
    return module.PublicationAttempts(*env, clock=lambda: 100.0, protect_public=protect, **kwargs)


def test_explicit_init_readonly_borrowed_journal_and_claim_replay(env):
    assert importlib.util.find_spec(MODULE) is not None, "publication state machine missing"
    with pytest.raises(ValueError, match="not initialized"):
        api(env)
    attempts = api(env, initialize=True)
    before = env[0].db.total_changes
    api(env)
    assert env[0].db.total_changes == before
    first = attempts.claim("effect", "request", grant())
    assert first["state"] == "claimed" and first["generation"] == 1
    assert attempts.claim("effect", "request", grant()) == first
    with pytest.raises(ValueError, match="conflict"):
        attempts.claim("effect", "request", grant(grant_id="changed"))
    with pytest.raises(ValueError, match="exclusive"):
        attempts.claim("effect", "second", grant("second"))
    assert attempts.get_state("effect") == first
    assert env[1].intent["state"] == "pending"


def identity(state):
    return {key: state[key] for key in ("attempt_id", "generation")}


@pytest.mark.parametrize(
    "changes",
    [
        dict(target_profile="other"),
        dict(effect_id="other"),
        dict(payload_sha256="0" * 64),
        dict(request_id="other"),
        dict(capability="graph_read"),
        dict(expires_at=100),
        dict(expires_at=float("nan")),
        dict(password="private"),
    ],
)
def test_grant_scope_checked_before_claim(env, changes):
    attempts = api(env, initialize=True)
    with pytest.raises(ValueError):
        attempts.claim("effect", "request", grant(**changes))
    assert attempts.get_state("effect")["write_claim_count"] == 0


def test_release_exact_cas_and_expiry_no_silent_renewal(env):
    attempts = api(env, initialize=True)
    claimed = attempts.claim("effect", "request", grant())
    with pytest.raises(ValueError):
        attempts.release("effect", **identity(claimed), grant_metadata=grant(expires_at=300))
    assert not attempts.release("effect", attempt_id="stale", generation=1, grant_metadata=grant())
    attempts.clock = lambda: 200
    with pytest.raises(ValueError):
        attempts.release("effect", **identity(claimed), grant_metadata=grant())
    attempts.clock = lambda: 100
    assert attempts.release("effect", **identity(claimed), grant_metadata=grant())
    assert not attempts.release("effect", **identity(claimed), grant_metadata=grant())
    with pytest.raises(ValueError, match="exclusive"):
        attempts.claim("effect", "new", grant("new"))
    assert attempts.mark_unknown("effect", **identity(claimed))
    assert attempts.get_state("effect")["state"] == "unknown"


def test_independent_connections_only_one_write_claim(env, tmp_path):
    api(env, initialize=True)

    def claim_one(number):
        with closing(Journal(tmp_path / "journal.sqlite3")) as attached:
            attempts = api((attached, env[1]))
            try:
                return attempts.claim("effect", f"request-{number}", grant(f"request-{number}"))
            except ValueError:
                return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim_one, range(8)))
    assert sum(result is not None for result in results) == 1


def test_protection_required_and_claim_event_failure_rolls_back(env):
    cls = importlib.import_module(MODULE).PublicationAttempts
    attempts = cls(*env, initialize=True, clock=lambda: 100)
    with pytest.raises(ValueError, match="protect_public"):
        attempts.claim("effect", "request", grant())
    attempts.protect_public = protect
    env[0].db.execute(
        "CREATE TRIGGER reject_publication BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'event failed'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="event failed"):
        attempts.claim("effect", "request", grant())
    assert attempts.get_state("effect")["state"] == "pending"
    assert env[0].db.execute("SELECT COUNT(*) FROM publication_bindings").fetchone()[0] == 0


@pytest.mark.parametrize("released", [False, True])
def test_cancel_keeps_send_outcome_independent(env, released):
    attempts = api(env, initialize=True)
    claimed = attempts.claim("effect", "request", grant())
    if released:
        assert attempts.release("effect", **identity(claimed), grant_metadata=grant())
    state = attempts.cancel("effect")
    assert state["cancelled"] is True
    assert state["state"] == ("unknown" if released else "cancelled_no_send")
    assert not attempts.release("effect", **identity(claimed), grant_metadata=grant())
    with pytest.raises(ValueError):
        attempts.claim("effect", "other", grant("other"))


def test_blocked_claim_counts_quota_and_only_explicit_linked_renewal(env):
    attempts = api(env, initialize=True)
    claimed = attempts.claim("effect", "request", grant())
    assert attempts.block_authorization("effect", **identity(claimed))
    state = attempts.get_state("effect")
    assert state["state"] == "blocked_authorization" and state["write_claim_count"] == 1
    with pytest.raises(ValueError):
        attempts.claim("effect", "second", grant("second"))
    with pytest.raises(ValueError):
        attempts.renew("effect", "second", grant("second"), previous_request_id="wrong")
    with pytest.raises(ValueError):
        attempts.renew("effect", "second", grant("second", target_profile="other"), previous_request_id="request")
    renewed = attempts.renew("effect", "second", grant("second"), previous_request_id="request")
    assert renewed["state"] == "claimed" and renewed["generation"] == 2
    assert renewed["write_claim_count"] == 2
    assert renewed["attempt_id"] != claimed["attempt_id"]
    assert attempts.renew("effect", "second", grant("second"), previous_request_id="request") == renewed
    assert not attempts.release("effect", **identity(claimed), grant_metadata=grant())
    attempts.block_authorization("effect", **identity(renewed))
    attempts.max_attempts = 2
    with pytest.raises(ValueError, match="quota"):
        attempts.renew("effect", "third", grant("third"), previous_request_id="second")


@pytest.mark.parametrize("released", [False, True])
def test_explicit_recover_only_publication_no_journal_job_changes(env, released):
    attempts = api(env, initialize=True)
    claimed = attempts.claim("effect", "request", grant())
    if released:
        attempts.release("effect", **identity(claimed), grant_metadata=grant())
    job_before = env[0].get_job(env[1].job["id"])
    reader = api(env)
    assert reader.get_state("effect")["state"] == ("released" if released else "claimed")
    assert reader.recover() == 1
    assert reader.recover() == 0
    assert reader.get_state("effect")["state"] == ("unknown" if released else "blocked_authorization")
    assert env[0].get_job(env[1].job["id"]) == job_before


def test_verified_receipt_retains_the_transport_verification_boundary(env):
    attempts = api(env, initialize=True)
    claimed = attempts.claim("effect", "request", grant())
    assert attempts.release("effect", **identity(claimed), grant_metadata=grant())
    result = receipt()
    result["transport"]["verification_boundary"] = {
        "method": "operator_attested_immutable_scope_v1",
        "operator_attested": True,
        "declaration": "Synthetic immutable-scope declaration",
        "database_snapshot": False,
    }
    assert attempts.complete_verified("effect", **identity(claimed), receipt=result, comparator=lambda *a: True)
    assert attempts.get_state("effect")["receipt"]["transport"]["verification_boundary"]["database_snapshot"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"operator_attested": False},
        {"operator_attested": 1},
        {"database_snapshot": True},
        {"method": "snapshot"},
        {"declaration": ""},
    ],
)
def test_missing_or_false_boundary_cannot_be_accepted(env, change):
    attempts = api(env, initialize=True)
    claimed = attempts.claim("effect", "request", grant())
    assert attempts.release("effect", **identity(claimed), grant_metadata=grant())
    result = receipt()
    result["transport"]["verification_boundary"].update(change)
    with pytest.raises(ValueError, match="boundary"):
        attempts.complete_verified("effect", **identity(claimed), receipt=result, comparator=lambda *a: True)
    assert attempts.get_state("effect")["state"] == "released"


def receipt(**changes) -> dict:
    value = dict(
        schema_version=1,
        status="verified",
        effect_id="effect",
        target_profile="graph",
        payload_sha256=digest({"nodes": []}),
        transport=dict(
            status="verified",
            verification_boundary={
                "method": "operator_attested_immutable_scope_v1",
                "operator_attested": True,
                "declaration": "Synthetic immutable-scope declaration",
                "database_snapshot": False,
            },
            effect_id="effect",
            database="neo4j",
            scope_id="scope",
            projection_digest="a" * 64,
            canonical_identity={"name": "scene"},
        ),
    )
    value.update(changes)
    return value


def compared(intent, result):
    assert intent["effect_id"] == result["effect_id"]
    return True


def test_verified_requires_actual_comparator_and_immutable_receipt(env):
    attempts = api(env, initialize=True)
    claimed = attempts.claim("effect", "request", grant())
    assert not attempts.complete_verified("effect", **identity(claimed), receipt=receipt(), comparator=compared)
    attempts.release("effect", **identity(claimed), grant_metadata=grant())
    with pytest.raises(ValueError, match="comparator"):
        attempts.complete_verified("effect", **identity(claimed), receipt=receipt())
    with pytest.raises(ValueError, match="verification"):
        attempts.complete_verified("effect", **identity(claimed), receipt=receipt(), comparator=lambda i, r: False)
    assert not attempts.complete_verified(
        "effect", attempt_id="stale", generation=1, receipt=receipt(), comparator=compared
    )
    assert attempts.complete_verified("effect", **identity(claimed), receipt=receipt(), comparator=compared)
    assert attempts.complete_verified("effect", **identity(claimed), receipt=receipt(), comparator=compared)
    with pytest.raises(ValueError, match="conflict"):
        attempts.complete_verified(
            "effect",
            **identity(claimed),
            receipt=receipt(transport={**receipt()["transport"], "database": "changed"}),
            comparator=compared,
        )
    assert attempts.get_state("effect")["receipt"] == receipt()
    assert attempts.cancel("effect")["state"] == "verified"
    assert attempts.recover() == 0
    assert api(env).get_state("effect")["receipt"] == receipt()
    for statement in (
        "UPDATE publication_receipts SET body='{}'",
        "DELETE FROM publication_receipts",
        "INSERT OR REPLACE INTO publication_receipts SELECT * FROM publication_receipts",
        "UPDATE publication_bindings SET body='{}'",
        "DELETE FROM publication_bindings",
        "INSERT OR REPLACE INTO publication_bindings SELECT * FROM publication_bindings",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="Immutable"):
            env[0].db.execute(statement)


@pytest.mark.parametrize(
    "change",
    [
        dict(target_profile="wrong"),
        dict(payload_sha256="b" * 64),
        dict(effect_id="wrong"),
        dict(status="unknown"),
        dict(transport={}),
        dict(transport={**receipt()["transport"], "projection_digest": "bad"}),
        dict(transport={**receipt()["transport"], "status": "unknown"}),
    ],
)
def test_verified_receipt_scope_and_transport_fields(env, change):
    attempts = api(env, initialize=True)
    claimed = attempts.claim("effect", "request", grant())
    attempts.release("effect", **identity(claimed), grant_metadata=grant())
    with pytest.raises(ValueError):
        attempts.complete_verified("effect", **identity(claimed), receipt=receipt(**change), comparator=compared)
    assert attempts.get_state("effect")["receipt"] is None


def test_read_claim_negative_read_never_unlocks_write_and_fences_callbacks(env):
    attempts = api(env, initialize=True)
    write = attempts.claim("effect", "request", grant())
    attempts.release("effect", **identity(write), grant_metadata=grant())
    attempts.mark_unknown("effect", **identity(write))
    with pytest.raises(ValueError):
        attempts.claim_reconciliation("effect", "read", grant("read"))
    read = attempts.claim_reconciliation("effect", "read", grant("read", "graph_read"))
    assert read["state"] == "unknown" and read["reconciliation"]["state"] == "claimed"
    assert attempts.claim_reconciliation("effect", "read", grant("read", "graph_read")) == read
    assert not attempts.complete_verified("effect", **identity(write), receipt=receipt(), comparator=compared)
    assert attempts.finish_reconciliation_unknown("effect", **identity(read))
    assert not attempts.complete_verified("effect", **identity(read), receipt=receipt(), comparator=compared)
    with pytest.raises(ValueError):
        attempts.claim("effect", "write-again", grant("write-again"))
    assert attempts.get_state("effect")["write_claim_count"] == 1
    next_read = attempts.claim_reconciliation("effect", "read-next", grant("read-next", "graph_read"))
    assert attempts.complete_verified("effect", **identity(next_read), receipt=receipt(), comparator=compared)


def test_revoked_write_grant_independent_read_still_reconciles(env):
    calls = []
    revoked = set()

    def authorize(metadata, **scope):
        calls.append(scope["capability"])
        if metadata["grant_id"] in revoked:
            raise ValueError("revoked")
        return {"private_config": "never-persist"}, copy.deepcopy(metadata)

    attempts = api(env, initialize=True, authorizer=authorize)
    write = attempts.claim("effect", "request", grant())
    revoked.add("grant-request")
    with pytest.raises(ValueError, match="revoked"):
        attempts.release("effect", **identity(write), grant_metadata=grant())
    assert attempts.get_state("effect")["state"] == "claimed"
    revoked.clear()
    attempts.release("effect", **identity(write), grant_metadata=grant())
    attempts.mark_unknown("effect", **identity(write))
    revoked.add("grant-request")
    attempts.clock = lambda: 250
    read_grant = grant("read", "graph_read", expires_at=300)
    read = attempts.claim_reconciliation("effect", "read", read_grant)
    operations = []

    def operation(config, intent):
        assert config == {"private_config": "never-persist"}
        operations.append("read")
        return receipt()

    assert attempts.execute_reconciliation(
        "effect", **identity(read), grant_metadata=read_grant, operation=operation, comparator=compared
    )
    assert operations == ["read"] and calls[-1] == "graph_read"
    assert "never-persist" not in str(attempts.get_state("effect"))


def test_reconcile_recovery_fences_interrupted_read(env):
    attempts = api(env, initialize=True)
    write = attempts.claim("effect", "request", grant())
    attempts.release("effect", **identity(write), grant_metadata=grant())
    attempts.mark_unknown("effect", **identity(write))
    read = attempts.claim_reconciliation("effect", "read", grant("read", "graph_read"))
    assert attempts.recover() == 1
    assert not attempts.complete_verified("effect", **identity(read), receipt=receipt(), comparator=compared)
    assert attempts.get_state("effect")["state"] == "unknown"


def test_write_callback_failure_unknown_no_autoredispatch(env):
    attempts = api(env, initialize=True, authorizer=lambda metadata, **scope: ({}, metadata))
    write = attempts.claim("effect", "request", grant())
    calls = []

    def fail(config, intent):
        calls.append("write")
        raise RuntimeError("transport failed")

    with pytest.raises(RuntimeError, match="transport failed"):
        attempts.execute_write("effect", **identity(write), grant_metadata=grant(), operation=fail, comparator=compared)
    assert attempts.get_state("effect")["state"] == "unknown"
    assert not attempts.execute_write(
        "effect", **identity(write), grant_metadata=grant(), operation=fail, comparator=compared
    )
    assert calls == ["write"]


def test_public_guard_supports_existing_void_callback_and_rejects_mutation(env):
    seen = []
    attempts = api(env, initialize=True)
    attempts.protect_public = lambda value: seen.append(copy.deepcopy(value))
    assert attempts.claim("effect", "request", grant())["state"] == "claimed"
    assert seen
    attempts.protect_public = lambda value: value.update(expires_at=999)
    with pytest.raises(ValueError):
        attempts.release("effect", **identity(attempts.get_state("effect")), grant_metadata=grant())


@pytest.mark.parametrize("table", ["publication_states", "publication_bindings", "publication_receipts"])
def test_all_tables_schema_checked_without_repair(env, table):
    attempts = api(env, initialize=True)
    env[0].db.execute(f"DROP TABLE {table}")
    before = env[0].db.total_changes
    with pytest.raises(ValueError, match="schema"):
        api(env)
    with pytest.raises(ValueError, match="schema"):
        attempts.claim("effect", "request", grant())
    assert env[0].db.total_changes == before


def test_incompatible_version_and_closed_borrowed_journal_untouched(env):
    api(env, initialize=True)
    env[0].db.execute("UPDATE publication_meta SET schema_version=99")
    before = env[0].db.total_changes
    for initialize in (False, True):
        with pytest.raises(ValueError, match="schema"):
            api(env, initialize=initialize)
    assert env[0].db.total_changes == before
    env[0].close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        api(env, initialize=True)


def test_real_registry_descriptor_and_void_public_guard(tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.research_registry import ResearchRegistry
    from isaaclab_arena_examples.tests.test_workbench_research_registry import accepted_candidate, manifest_for

    with closing(Journal(tmp_path / "real.sqlite3")) as journal:
        journal.begin_run()
        registry = ResearchRegistry(journal, initialize=True)
        registry.register_store("store")
        job_id, attempt = accepted_candidate(journal)
        request = {"effect_id": "effect", "target_profile": "graph"}
        reservation = registry.reserve_candidate(
            "store",
            "scene",
            "persist",
            job_id=job_id,
            **attempt,
            approval={"scope": "persist_candidate", "principal": "owner"},
            publication_request=request,
        )
        payload = dict(
            artifact="projection.json", artifact_sha256="b" * 64, projection_digest="a" * 64, scope_id="scope"
        )
        registry.record_commit(
            reservation["reservation_id"],
            manifest_for(registry, reservation),
            "final/scene/v1",
            publication_intent={**request, "payload": payload, "payload_sha256": digest(payload)},
        )
        attempts = api((journal, registry), initialize=True)
        approved = grant(payload_sha256=digest(payload))
        claimed = attempts.claim("effect", "request", approved)
        attempts.release("effect", **identity(claimed), grant_metadata=approved)
        assert attempts.complete_verified(
            "effect", **identity(claimed), receipt=receipt(payload_sha256=digest(payload)), comparator=compared
        )
        assert registry.get_publication_intent("effect")["state"] == "pending"


def test_failed_or_recovered_write_callback_requires_read_reconciliation(env):
    attempts = api(env, initialize=True)
    state = attempts.claim("effect", "request", grant())
    attempts.release("effect", **identity(state), grant_metadata=grant())
    attempts.mark_unknown("effect", **identity(state))
    assert not attempts.complete_verified("effect", **identity(state), receipt=receipt(), comparator=compared)


def test_cancel_after_release_still_accepts_actual_inflight_receipt(env):
    attempts = api(env, initialize=True)
    state = attempts.claim("effect", "request", grant())
    attempts.release("effect", **identity(state), grant_metadata=grant())
    attempts.cancel("effect")
    assert attempts.complete_verified("effect", **identity(state), receipt=receipt(), comparator=compared)
    assert attempts.get_state("effect")["cancelled"]


def test_mutating_authorizer_cannot_silently_renew_and_helper_blocks(env):
    def renew(metadata, **scope):
        metadata["expires_at"] = 500
        return {}, metadata

    attempts = api(env, initialize=True, authorizer=renew)
    state = attempts.claim("effect", "request", grant())
    calls = []
    with pytest.raises(ValueError, match="grant conflict"):
        attempts.execute_write(
            "effect",
            **identity(state),
            grant_metadata=grant(),
            operation=lambda c, i: calls.append(1),
            comparator=compared,
        )
    assert calls == []
    assert attempts.get_state("effect")["state"] == "blocked_authorization"


def test_http_idempotency_replays_acceptance_after_release_and_expiry(env):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    attempts = api(env, initialize=True)
    application = FastAPI()

    @application.post("/publication")
    def submit(body: dict):
        try:
            return attempts.claim(body["effect_id"], body["request_id"], body["grant"])
        except ValueError:
            raise HTTPException(409, "conflict") from None

    with TestClient(application) as client:
        body = dict(effect_id="effect", request_id="request", grant=grant())
        first = client.post("/publication", json=body)
        assert first.status_code == 200
        attempts.release("effect", **identity(first.json()), grant_metadata=grant())
        attempts.clock = lambda: 250
        assert client.post("/publication", json=body).json() == first.json()
        body["grant"]["expires_at"] = 500
        assert client.post("/publication", json=body).status_code == 409


@pytest.mark.parametrize("failure", [False, True])
def test_cancelled_failure_closes_callback_and_read_recovery_is_once(env, failure):
    attempts = api(env, initialize=True)
    state = attempts.claim("effect", "request", grant())
    attempts.release("effect", **identity(state), grant_metadata=grant())
    attempts.cancel("effect")
    if failure:
        assert attempts.mark_unknown("effect", **identity(state))
        assert not attempts.complete_verified("effect", **identity(state), receipt=receipt(), comparator=compared)
    attempts.claim_reconciliation("effect", "read", grant("read", "graph_read"))
    assert attempts.recover() == 1
    assert attempts.recover() == 0


def test_read_grant_expired_before_operation_does_not_call(env):
    attempts = api(env, initialize=True, authorizer=lambda m, **s: ({}, m))
    state = attempts.claim("effect", "request", grant())
    attempts.release("effect", **identity(state), grant_metadata=grant())
    attempts.mark_unknown("effect", **identity(state))
    read = attempts.claim_reconciliation("effect", "read", grant("read", "graph_read"))
    attempts.clock = lambda: 200
    calls = []
    with pytest.raises(ValueError, match="expired"):
        attempts.execute_reconciliation(
            "effect",
            **identity(read),
            grant_metadata=grant("read", "graph_read"),
            operation=lambda c, i: calls.append(1),
            comparator=compared,
        )
    assert calls == []
    assert attempts.get_state("effect")["state"] == "unknown"


def test_receipt_event_and_commit_failures_roll_back(env):
    attempts = api(env, initialize=True)
    claimed = attempts.claim("effect", "request", grant())
    attempts.release("effect", **identity(claimed), grant_metadata=grant())
    env[0].db.execute(
        "CREATE TRIGGER reject_receipt_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'event failed'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        attempts.complete_verified("effect", **identity(claimed), receipt=receipt(), comparator=compared)
    assert attempts.get_state("effect")["state"] == "released"
    assert env[0].db.execute("SELECT COUNT(*) FROM publication_receipts").fetchone()[0] == 0
    env[0].db.execute("DROP TRIGGER reject_receipt_event")
    env[0].db.execute("PRAGMA foreign_keys=ON")
    env[0].db.execute("CREATE TABLE deferred_child (id INTEGER REFERENCES jobs(id) DEFERRABLE INITIALLY DEFERRED)")
    env[0].db.execute(
        "CREATE TRIGGER reject_commit AFTER INSERT ON publication_receipts BEGIN INSERT INTO deferred_child VALUES"
        " (-1); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        attempts.complete_verified("effect", **identity(claimed), receipt=receipt(), comparator=compared)
    assert attempts.get_state("effect")["state"] == "released"
    assert env[0].db.execute("SELECT COUNT(*) FROM publication_receipts").fetchone()[0] == 0
