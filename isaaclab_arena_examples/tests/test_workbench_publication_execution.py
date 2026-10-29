# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Real local publication components with explicitly fake graph IO; no live graph."""

import copy
import hashlib
import json
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from isaaclab_arena.agentic_environment_generation.workbench import research_graph_transport as transport
from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore
from isaaclab_arena.agentic_environment_generation.workbench.sessions import Sessions
from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_authorization import (
    PublicationAuthorization,
)


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.mutate = lambda value: None

    def _call(
        self,
        mode,
        driver,
        database,
        projection,
        *,
        spec,
        effect_id,
        immutable_scope_attested,
    ):
        assert immutable_scope_attested is True
        self.calls.append((mode, database, copy.deepcopy(projection), spec.model_dump(mode="json")))
        if self.failure:
            raise self.failure
        receipt = dict(
            status="verified",
            effect_id=effect_id,
            database=database,
            scope_id=projection["scope_id"],
            projection_digest=projection["digest"],
            canonical_identity=copy.deepcopy(projection["canonical_identity"]),
            verification_boundary=dict(
                method="operator_attested_immutable_scope_v1",
                operator_attested=True,
                declaration=transport.IMMUTABLE_SCOPE_DECLARATION,
                database_snapshot=False,
            ),
        )
        self.mutate(receipt)
        return receipt

    def publish_once(self, *args, **kwargs):
        return self._call("write", *args, **kwargs)

    def reconcile_once(self, *args, **kwargs):
        return self._call("read", *args, **kwargs)


@pytest.fixture
def ready(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Network prohibited"))
    now = [1000.0]
    with closing(Journal(tmp_path / "journal.sqlite3")) as journal:
        journal.begin_run()
        sessions = Sessions(journal, clock=lambda: now[0], idle_seconds=300, absolute_seconds=600)
        session, cookie = sessions.create()
        profiles = {
            "graph": {
                "connection": dict(
                    uri="bolt://example.invalid:7687",
                    user="operator",
                    password="fake-private-publication-password",
                    database="research",
                ),
                "immutable_scope": True,
            }
        }
        auth = PublicationAuthorization(sessions, lambda: profiles, clock=lambda: now[0])
        with ResearchStore.create(journal, tmp_path / "managed", "store", protect_public=auth.protect_public) as store:
            job = journal.submit(
                "owner",
                "default",
                "generate",
                "candidate",
                {"operation": "new", "prompt": "synthetic"},
            )
            attempt = journal.claim_attempt(job["id"])
            assert journal.release_attempt(job["id"], **attempt)
            text = (
                Path(__file__).parents[2] / "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"
            ).read_text()
            receipt = dict(
                yaml_text=text,
                validation=dict(valid=True, source_hash=hashlib.sha256(text.encode()).hexdigest()),
                publication="not_published",
            )
            assert journal.commit_candidate(job["id"], **attempt, receipt=receipt)
            assert journal.complete_attempt(job["id"], **attempt, expected_state="candidate_committed")
            commit = store.persist_candidate(
                "family",
                "save",
                job_id=job["id"],
                **attempt,
                approval=dict(scope="persist_candidate", principal="owner"),
                publication_request=dict(effect_id="effect", target_profile=auth.profile_metadata("graph")),
            )
            attempts = PublicationAttempts(
                journal,
                store.registry,
                initialize=True,
                clock=lambda: now[0],
                protect_public=auth.protect_public,
                authorizer=auth,
            )
            fake = FakeTransport()
            drivers = []
            configs = []

            def factory(**kwargs):
                configs.append(kwargs)
                driver = SimpleNamespace(closed=False)

                def close():
                    driver.closed = True

                driver.close = close
                drivers.append(driver)
                return driver

            yield SimpleNamespace(
                store=store,
                attempts=attempts,
                auth=auth,
                session=session,
                sessions=sessions,
                cookie=cookie,
                profiles=profiles,
                now=now,
                fake=fake,
                drivers=drivers,
                configs=configs,
                factory=factory,
                commit=commit,
                journal=journal,
            )


def executor(ready):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_execution import PublicationExecutor

    return PublicationExecutor(
        ready.store,
        ready.attempts,
        ready.auth,
        driver_factory=ready.factory,
        transport=ready.fake,
    )


def test_constructor_rejects_cloned_registry_connection_before_authority(ready, tmp_path, monkeypatch):
    from isaaclab_arena.agentic_environment_generation.workbench.research_registry import ResearchRegistry

    def forbidden(*args, **kwargs):
        pytest.fail("Authority or driver must not be consulted")

    with closing(Journal(tmp_path / "clone.sqlite3")) as clone:
        ready.journal.db.backup(clone.db)
        registry = ResearchRegistry(clone)
        assert registry.registry_id == ready.store.registry.registry_id
        assert registry.journal.db is not ready.journal.db
        ready.attempts.registry = registry
        monkeypatch.setattr(ready.auth, "profile_metadata", forbidden)
        monkeypatch.setattr(ready.auth, "issue", forbidden)
        ready.factory = forbidden
        with pytest.raises(ValueError, match="component binding conflict"):
            executor(ready)
    assert not ready.drivers
    assert not ready.fake.calls


@pytest.mark.parametrize("foreign_store", [False, True])
def test_accepted_replay_checks_store_without_current_authority(ready, tmp_path, monkeypatch, foreign_store):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_execution import PublicationExecutor

    run = executor(ready)
    accepted = run.publish(ready.session, "effect", "request")
    ready.profiles.clear()
    ready.sessions.revoke(ready.cookie)
    assert ready.sessions.get(ready.cookie) is None
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        pytest.fail("Accepted replay must not consult authority or graph")

    monkeypatch.setattr(ready.auth, "profile_metadata", forbidden)
    monkeypatch.setattr(ready.auth, "issue", forbidden)
    monkeypatch.setattr(PublicationAuthorization, "__call__", forbidden)
    monkeypatch.setattr(ready.fake, "publish_once", forbidden)
    with ResearchStore.create(
        ready.journal, tmp_path / "other-managed", "other-store", protect_public=ready.auth.protect_public
    ) as other:
        store = other if foreign_store else ready.store
        replay = PublicationExecutor(store, ready.attempts, ready.auth, driver_factory=forbidden, transport=ready.fake)
        if foreign_store:
            with pytest.raises(ValueError, match="Unknown research reservation"):
                replay.publish(ready.session, "effect", "request")
        else:
            assert replay.publish(ready.session, "effect", "request") == accepted
        assert run.publish(ready.session, "effect", "request") == accepted
    assert calls == []
    assert len(ready.drivers) == 1
    assert len(ready.fake.calls) == 1
    assert ready.attempts.get_state("effect")["write_claim_count"] == 1


def test_publish_verified_frozen_artifacts_and_accepted_replay(ready):
    run = executor(ready)
    result = run.publish(ready.session, "effect", "request")
    assert result["accepted"]["state"] == "claimed"
    assert result["state"]["state"] == "verified"
    assert result["state"]["receipt"]["transport"]["verification_boundary"]["database_snapshot"] is False
    assert ready.fake.calls[0][0:2] == ("write", "research")
    assert ready.drivers[0].closed
    assert ready.configs[0]["max_transaction_retry_time"] == 0
    assert ready.configs[0]["uri"] == ready.profiles["graph"]["connection"]["uri"]
    assert run.publish(ready.session, "effect", "request") == result
    assert len(ready.drivers) == 1
    assert len(ready.fake.calls) == 1


@pytest.mark.parametrize(
    "attack",
    [
        "artifact-sha",
        "artifact-name",
        "descriptor-scope",
        "descriptor-projection",
        "descriptor-extra",
        "reservation",
        "effect",
        "target",
        "options",
        "source",
        "candidate",
        "projection-scope",
    ],
)
def test_preparation_rejects_swapped_frozen_bindings_without_driver(ready, monkeypatch, attack):
    from isaaclab_arena.agentic_environment_generation.workbench.research_projection import project_scene
    from isaaclab_arena.agentic_environment_generation.workbench.research_registry import canonical_json, digest
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    registry = ready.store.registry
    intent = registry.get_publication_intent("effect")
    files = ready.store.read_version(intent["reservation_id"])
    if attack.startswith("artifact") or attack.startswith("descriptor"):
        key, value = {
            "artifact-sha": ("artifact_sha256", "0" * 64),
            "artifact-name": ("artifact", "candidate.json"),
            "descriptor-scope": ("scope_id", "wrong"),
            "descriptor-projection": ("projection_digest", "0" * 64),
            "descriptor-extra": ("extra", "unapproved"),
        }[attack]
        intent["payload"][key] = value
        intent["payload_sha256"] = digest(intent["payload"])
    elif attack in ("effect", "target", "options"):
        key, value = {
            "effect": ("effect_id", "swapped"),
            "target": ("target_profile", "graph"),
            "options": ("options", {"replace": True}),
        }[attack]
        intent[key] = value
    elif attack == "reservation":
        source = json.loads(files["source.json"])
        source["family"] = "swapped"
        files["source.json"] = canonical_json(source).encode()
    elif attack == "source":
        files["environment.yaml"] = files["environment.yaml"].replace(b"maple", b"different")
    elif attack == "candidate":
        candidate = json.loads(files["candidate.json"])
        candidate["publication"] = "swapped"
        files["candidate.json"] = canonical_json(candidate).encode()
    else:
        projection = json.loads(files["projection.json"])
        root = next(node for node in projection["nodes"] if node["labels"] == ["EnvironmentGraph"])
        spec = ArenaEnvGraphSpec.from_dict(json.loads(root["properties"]["spec_json"]))
        scope = {key: projection["scope"][key] for key in ("revision_id", "store_id", "family", "version")}
        scope["family"] = "swapped"
        projection = project_scene(spec, **scope)
        files["projection.json"] = canonical_json(projection).encode()
        intent["payload"].update(
            artifact_sha256=hashlib.sha256(files["projection.json"]).hexdigest(),
            scope_id=projection["scope_id"],
            projection_digest=projection["digest"],
        )
        intent["payload_sha256"] = digest(intent["payload"])
    monkeypatch.setattr(registry, "get_publication_intent", lambda effect_id: copy.deepcopy(intent))
    monkeypatch.setattr(ready.store, "read_version", lambda reservation_id: copy.deepcopy(files))
    with pytest.raises(ValueError):
        executor(ready).publish(ready.session, "effect", "request")
    assert not ready.drivers


def test_real_artifact_tampering_rejected_before_driver(ready):
    # Obtain the actual area location from the fixture's SQLite sibling, not an unverified path in an intent.
    root = Path(ready.journal.db.execute("PRAGMA database_list").fetchone()[2]).parent / "managed"
    artifact = root / ready.commit["relative_directory"] / "projection.json"
    artifact.write_bytes(b"{}")
    with pytest.raises(ValueError):
        executor(ready).publish(ready.session, "effect", "request")
    assert not ready.drivers


@pytest.mark.parametrize("field", ["database", "uri", "user"])
def test_authorized_connection_must_match_frozen_profile(ready, monkeypatch, field):
    original = PublicationAuthorization.__call__

    def swap(self, *args, **kwargs):
        connection, approved = original(self, *args, **kwargs)
        connection[field] = {
            "database": "other",
            "uri": "bolt://other.invalid:7687",
            "user": "other",
        }[field]
        return connection, approved

    monkeypatch.setattr(PublicationAuthorization, "__call__", swap)
    with pytest.raises(ValueError):
        executor(ready).publish(ready.session, "effect", "request")
    assert not ready.drivers


@pytest.mark.parametrize("negative_read", [False, True])
def test_lost_ack_requires_explicit_read_never_rewrites_or_regenerates(ready, monkeypatch, negative_read):
    run = executor(ready)
    frozen = ready.store.read_version(ready.commit["reservation"]["reservation_id"])
    ready.fake.failure = transport.OutcomeUnknown("fake lost acknowledgement")
    with pytest.raises(transport.OutcomeUnknown):
        run.publish(ready.session, "effect", "write-request")
    assert ready.attempts.get_state("effect")["state"] == "unknown"
    assert run.publish(ready.session, "effect", "write-request")["state"]["state"] == "unknown"
    with pytest.raises(ValueError):
        run.publish(ready.session, "effect", "another-write")
    assert len(ready.drivers) == 1
    monkeypatch.setattr(
        ready.store,
        "persist_candidate",
        lambda *a, **k: pytest.fail("Regeneration/persistence forbidden"),
    )
    ready.fake.failure = None
    if negative_read:
        ready.fake.mutate = lambda receipt: receipt.update(status="unknown")
    result = run.reconcile(ready.session, "effect", "read-request")
    assert result["state"]["state"] == ("unknown" if negative_read else "verified")
    assert result["state"]["write_claim_count"] == 1
    assert result["state"]["reconciliation"]["state"] == ("unknown" if negative_read else "verified")
    assert [call[0] for call in ready.fake.calls] == ["write", "read"]
    assert ready.fake.calls[0][2:] == ready.fake.calls[1][2:]
    assert run.reconcile(ready.session, "effect", "read-request") == result
    assert len(ready.drivers) == 2
    assert ready.store.read_version(ready.commit["reservation"]["reservation_id"]) == frozen


@pytest.mark.parametrize("failure", ["expired", "revoked", "rotated", "ownership", "endpoint"])
def test_session_and_profile_authority_rechecked_after_claim(ready, monkeypatch, failure):
    original = ready.auth.bind_attempt

    def bind(metadata, attempt_id, generation):
        original(metadata, attempt_id, generation)
        if failure == "expired":
            ready.now[0] += 301
        elif failure == "revoked":
            ready.auth.revoke(metadata["grant_id"])
        elif failure == "rotated":
            ready.profiles["graph"]["connection"]["password"] = "rotated-private-publication-password"
        elif failure == "ownership":
            ready.profiles["graph"]["immutable_scope"] = False
        else:
            ready.profiles["graph"]["connection"]["database"] = "swapped"

    monkeypatch.setattr(ready.auth, "bind_attempt", bind)
    with pytest.raises(ValueError):
        executor(ready).publish(ready.session, "effect", "request")
    state = ready.attempts.get_state("effect")
    assert state["state"] == "blocked_authorization"
    assert state["write_claim_count"] == 1
    assert not ready.drivers
    assert not ready.fake.calls


@pytest.mark.parametrize("when", ["before", "claimed", "released"])
def test_cancellation_respects_core_write_fence(ready, monkeypatch, when):
    if when == "before":
        ready.attempts.cancel("effect")
    elif when == "claimed":
        original = ready.auth.bind_attempt

        def bind(*args):
            original(*args)
            ready.attempts.cancel("effect")

        monkeypatch.setattr(ready.auth, "bind_attempt", bind)
    else:
        ready.fake.mutate = lambda receipt: ready.attempts.cancel("effect")
    if when == "before":
        with pytest.raises(ValueError):
            executor(ready).publish(ready.session, "effect", "request")
    else:
        executor(ready).publish(ready.session, "effect", "request")
    state = ready.attempts.get_state("effect")
    assert state["cancelled"] is True
    assert state["state"] == ("verified" if when == "released" else "cancelled_no_send")
    assert len(ready.drivers) == (1 if when == "released" else 0)


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "effect_id",
        "database",
        "scope_id",
        "projection_digest",
        "canonical_identity",
        "missing-boundary",
        "method",
        "operator_attested",
        "declaration",
        "database_snapshot",
    ],
)
def test_transport_receipt_comparator_rejects_every_changed_binding(ready, field):
    def mutate(receipt):
        if field == "missing-boundary":
            receipt.pop("verification_boundary")
        elif field in receipt["verification_boundary"]:
            receipt["verification_boundary"][field] = {
                "operator_attested": False,
                "database_snapshot": True,
            }.get(field, "wrong")
        else:
            receipt[field] = {
                "canonical_identity": {"name": "other", "sha256": "0" * 64},
                "projection_digest": "0" * 64,
            }.get(field, "wrong")

    ready.fake.mutate = mutate
    with pytest.raises(ValueError):
        executor(ready).publish(ready.session, "effect", "request")
    assert ready.attempts.get_state("effect")["state"] == "unknown"
    assert ready.drivers[0].closed


@pytest.mark.parametrize("constructor_failure", [False, True])
def test_default_factory_forwards_explicit_config_after_release(ready, monkeypatch, constructor_failure):
    import sys

    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_execution import PublicationExecutor

    calls = []
    connection = copy.deepcopy(ready.profiles["graph"]["connection"])
    for name in ("URI", "USER", "PASSWORD"):
        monkeypatch.setenv(f"NEO4J_{name}", "ambient-must-not-be-used")

    def driver(uri, *, auth, **options):
        state = ready.attempts.get_state("effect")
        assert state["state"] == "released"
        assert state["write_callback_open"] is True
        calls.append(dict(uri=uri, auth=auth, **options))
        if constructor_failure:
            raise RuntimeError("fake SDK constructor failure")
        return ready.factory(uri=uri, auth=auth, **options)

    monkeypatch.setitem(sys.modules, "neo4j", SimpleNamespace(GraphDatabase=SimpleNamespace(driver=driver)))
    run = PublicationExecutor(ready.store, ready.attempts, ready.auth, transport=ready.fake)
    if constructor_failure:
        with pytest.raises(RuntimeError, match="SDK constructor failure"):
            run.publish(ready.session, "effect", "request")
    else:
        assert run.publish(ready.session, "effect", "request")["state"]["state"] == "verified"
        assert ready.drivers[0].closed
    assert calls == [
        dict(
            uri=connection["uri"],
            auth=(connection["user"], connection["password"]),
            connection_timeout=3,
            connection_acquisition_timeout=5,
            max_connection_pool_size=1,
            max_transaction_retry_time=0,
        )
    ]
    state = ready.attempts.get_state("effect")
    assert state["state"] == ("unknown" if constructor_failure else "verified")
    assert state["write_callback_open"] is False
    assert state["write_claim_count"] == 1
    if constructor_failure:
        assert state["receipt"] is None
        assert not ready.drivers
        assert not ready.fake.calls
        with pytest.raises(ValueError):
            run.publish(ready.session, "effect", "second-write")
    assert run.publish(ready.session, "effect", "request")["state"] == state
    assert len(calls) == 1
    assert ready.auth._records == {}


def test_driver_cleanup_failure_cannot_persist_verified_receipt(ready):
    factory = ready.factory

    def failing_factory(**kwargs):
        driver = factory(**kwargs)

        def close():
            raise RuntimeError("fake driver close failure")

        driver.close = close
        return driver

    ready.factory = failing_factory
    with pytest.raises(RuntimeError, match="close failure"):
        executor(ready).publish(ready.session, "effect", "request")
    state = ready.attempts.get_state("effect")
    assert state["state"] == "unknown"
    assert state["receipt"] is None
    executor(ready).publish(ready.session, "effect", "request")
    assert len(ready.drivers) == 1


@pytest.mark.parametrize("phase", ["claim", "bind", "execute"])
def test_failed_authority_releases_memory_and_closes_unsent_claim(ready, monkeypatch, phase):
    if phase == "claim":
        ready.attempts.cancel("effect")
    elif phase == "bind":
        monkeypatch.setattr(
            ready.auth,
            "bind_attempt",
            lambda *a: (_ for _ in ()).throw(ValueError("bind failed")),
        )
    else:
        ready.fake.failure = RuntimeError("transport failed")
    with pytest.raises((ValueError, RuntimeError)):
        executor(ready).publish(ready.session, "effect", "request")
    assert ready.auth._records == {}
    if phase == "bind":
        assert ready.attempts.get_state("effect")["state"] == "blocked_authorization"


def test_real_transport_fake_physical_driver_lost_ack_readback(ready):
    from isaaclab_arena.tests.test_workbench_research_graph_transport import Driver
    from isaaclab_arena_examples.agentic_environment_generation.web_api.publication_execution import PublicationExecutor

    driver = Driver()
    driver.close = lambda: None
    driver.constraints = [
        {
            "entityType": row["entityType"],
            "type": row["type"],
            "labelsOrTypes": [row["label"]],
            "properties": row["properties"],
        }
        for row in transport.schema_requirements()
    ]
    driver.ack_loss = True
    run = PublicationExecutor(ready.store, ready.attempts, ready.auth, driver_factory=lambda **kwargs: driver)
    with pytest.raises(transport.OutcomeUnknown):
        run.publish(ready.session, "effect", "write")
    assert driver.commits == 1
    queries = len(driver.calls)
    driver.ack_loss = False
    result = run.reconcile(ready.session, "effect", "read")
    assert result["state"]["state"] == "verified"
    assert driver.commits == 1
    assert all(
        "MERGE" not in query and "CREATE" not in query and "SET" not in query for query, _ in driver.calls[queries:]
    )
    assert [session.options["default_access_mode"] for session in driver.sessions] == [
        "WRITE",
        "READ",
    ]


def test_failed_read_authority_closes_read_claim_without_reopening_write(ready, monkeypatch):
    run = executor(ready)
    ready.fake.failure = transport.OutcomeUnknown("lost ack")
    with pytest.raises(transport.OutcomeUnknown):
        run.publish(ready.session, "effect", "write")
    ready.fake.failure = None
    original = ready.auth.bind_attempt

    def bind(metadata, *args):
        original(metadata, *args)
        ready.auth.revoke(metadata["grant_id"])

    with monkeypatch.context() as context:
        context.setattr(ready.auth, "bind_attempt", bind)
        with pytest.raises(ValueError):
            run.reconcile(ready.session, "effect", "denied-read")
    assert ready.attempts.get_state("effect")["reconciliation"] == {"state": "unknown"}
    assert run.reconcile(ready.session, "effect", "explicit-read")["state"]["state"] == "verified"
    assert [call[0] for call in ready.fake.calls] == ["write", "read"]


def test_comparator_independently_rejects_all_envelope_bindings(ready, monkeypatch):
    original = ready.attempts.complete_verified

    def complete(*args, receipt, comparator):
        intent = ready.store.registry.get_publication_intent("effect")
        assert comparator(intent, receipt) is True
        for key in (
            "schema_version",
            "status",
            "effect_id",
            "target_profile",
            "payload_sha256",
        ):
            changed = copy.deepcopy(receipt)
            changed[key] = "swapped"
            assert comparator(intent, changed) is False
        for key in receipt["transport"]:
            changed = copy.deepcopy(receipt)
            changed["transport"][key] = "swapped"
            assert comparator(intent, changed) is False
        changed = copy.deepcopy(intent)
        changed["reservation_id"] = "swapped"
        assert comparator(changed, receipt) is False
        return original(*args, receipt=receipt, comparator=comparator)

    monkeypatch.setattr(ready.attempts, "complete_verified", complete)
    assert executor(ready).publish(ready.session, "effect", "request")["state"]["state"] == "verified"


def test_revoked_real_session_cannot_issue_or_create_driver(ready):
    ready.sessions.revoke(ready.cookie)
    with pytest.raises(ValueError):
        executor(ready).publish(ready.session, "effect", "request")
    assert not ready.drivers
