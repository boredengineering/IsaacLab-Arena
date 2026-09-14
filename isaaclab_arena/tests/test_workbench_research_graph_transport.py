# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Fake physical-driver contract tests, not live Cypher validation."""

import importlib
import socket
from collections.abc import Callable
from copy import deepcopy

import pytest

from isaaclab_arena.tests import test_workbench_research_projection as projection_tests
from isaaclab_arena.tests.test_workbench_research_projection import project


@pytest.fixture
def spec(monkeypatch):
    return projection_tests.spec.__wrapped__(monkeypatch)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Transport contract tests must not open sockets")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def transport():
    return importlib.import_module("isaaclab_arena.agentic_environment_generation.workbench.research_graph_transport")


class Driver:
    def __init__(self):
        self.calls = []
        self.sessions = []
        self.constraints = []
        self.nodes = {}
        self.edges = []
        self.ack_loss = False
        self.read_failure = False
        self.close_failure = False
        self.commits = 0
        self.read_mutation: Callable | None = None

    def session(self, **kwargs):
        session = Session(self, kwargs)
        self.sessions.append(session)
        return session


class Session:
    def __init__(self, driver, options):
        self.driver, self.options = driver, options
        self.closed = False
        self.transactions = []

    def begin_transaction(self, **kwargs):
        tx = Transaction(self.driver, kwargs)
        self.transactions.append(tx)
        return tx

    def run(self, query, **params):
        if self.driver.read_failure:
            raise OSError("read lost")
        tx = Transaction(self.driver, {})
        if self.driver.read_mutation:
            self.driver.read_mutation(tx)
        return tx.run(str(query), **params)

    def close(self):
        self.closed = True
        if self.driver.close_failure:
            raise OSError("close lost")


class Transaction:
    def __init__(self, driver, options):
        self.driver, self.options = driver, options
        self.closed = False
        self.nodes = deepcopy(driver.nodes)
        self.edges = deepcopy(driver.edges)

    def run(self, query, **params):
        self.driver.calls.append((query, params))
        if query.startswith("SHOW CONSTRAINTS"):
            return self.driver.constraints
        if query.startswith("// root"):
            return [
                n
                for n in self.nodes.values()
                if n["labels"] == ["EnvironmentGraph"] and n["properties"]["name"] == params["name"]
            ]
        if query.startswith("// effect"):
            return [
                n
                for n in self.nodes.values()
                if "ArenaPublicationEffect" in n["labels"] and n["properties"]["id"] == params["effect_id"]
            ]
        if query.startswith("// node\n"):
            labels = query.split("MERGE (n:")[1].split(" {")[0].split(":")
            found = [
                n
                for n in self.nodes.values()
                if set(labels) <= set(n["labels"])
                and all(n["properties"].get(k) == v for k, v in params["key"].items())
            ]
            if found:
                return found
            eid = "node-" + str(len(self.nodes))
            node = dict(eid=eid, labels=labels, properties=deepcopy(params["properties"]))
            self.nodes[eid] = node
            return [node]
        if query.startswith("// edge\n"):
            kind = query.split("MERGE (a)-[r:")[1].split(" {")[0]
            found = [
                e
                for e in self.edges
                if e["type"] == kind
                and e["source"] == params["source"]
                and e["target"] == params["target"]
                and all(e["properties"].get(k) == v for k, v in params["key"].items())
            ]
            if found:
                return found
            edge = dict(
                type=kind, source=params["source"], target=params["target"], properties=deepcopy(params["properties"])
            )
            self.edges.append(edge)
            return [edge]
        if query.startswith("// nodes"):
            return [
                n
                for n in self.nodes.values()
                if n["properties"].get("scope_id") == params["scope_id"]
                or ("EnvironmentGraph" in n["labels"] and n["properties"].get("name") == params["name"])
            ]
        if query.startswith("// edges"):
            return [
                e
                for e in self.edges
                if e["properties"].get("scope_id") == params["scope_id"]
                or any(
                    self.nodes[e[k]]["properties"].get("scope_id") == params["scope_id"] for k in ("source", "target")
                )
            ]
        raise AssertionError(query)

    def commit(self):
        self.driver.nodes, self.driver.edges = deepcopy(self.nodes), deepcopy(self.edges)
        self.driver.commits += 1
        if self.driver.ack_loss:
            raise OSError("commit acknowledgement lost")

    def close(self):
        self.closed = True


@pytest.mark.parametrize("operation", ["publish_once", "reconcile_once", "verify_schema"])
@pytest.mark.parametrize("failure", ["session", "transaction", "both"])
def test_cleanup_veto_retains_unknown_publication_contract(spec, monkeypatch, operation, failure):
    from isaaclab_arena.agentic_environment_generation.graph_cleanup import GraphCleanupError

    m, driver = transport(), ready_driver()
    projection = project(spec)
    if operation == "reconcile_once":
        receipt = m.publish_once(
            driver, "research", projection, spec=spec, effect_id="effect", immutable_scope_attested=True
        )
        assert receipt["status"] == "verified"
    if failure in {"session", "both"}:
        driver.close_failure = True
    if failure in {"transaction", "both"}:

        def close(tx):
            tx.closed = True
            raise OSError("private-transaction-secret")

        monkeypatch.setattr(Transaction, "close", close)
    with pytest.raises(GraphCleanupError, match="cleanup") as caught:
        if operation == "verify_schema":
            m.verify_schema(driver, "research")
        else:
            getattr(m, operation)(
                driver, "research", projection, spec=spec, effect_id="effect", immutable_scope_attested=True
            )
    assert isinstance(caught.value, m.OutcomeUnknown) == (operation != "verify_schema")
    assert all(s.closed and all(tx.closed for tx in s.transactions) for s in driver.sessions)
    assert "private-transaction-secret" not in str(caught.value)


def test_schema_is_public_data_and_verification_is_read_only():
    m = transport()
    requirements = m.schema_requirements()
    assert requirements and all(r["ddl"].startswith("CREATE CONSTRAINT") for r in requirements)
    driver = Driver()
    driver.constraints = [
        {"entityType": r["entityType"], "type": r["type"], "labelsOrTypes": [r["label"]], "properties": r["properties"]}
        for r in requirements
    ]
    assert m.verify_schema(driver, "research") is True
    assert all(q.startswith("SHOW CONSTRAINTS") for q, _ in driver.calls)
    assert driver.sessions[0].options["database"] == "research"
    assert driver.sessions[0].options["default_access_mode"] == "READ"
    assert driver.sessions[0].transactions[0].options["timeout"] == 3.0
    assert driver.sessions[0].closed and driver.sessions[0].transactions[0].closed
    assert any(r["label"] == "ArenaPublicationEffect" for r in requirements)
    assert any(r["entityType"] == "RELATIONSHIP" for r in requirements)


def ready_driver():
    # Independent SHOW fixture, intentionally not generated by schema_requirements.
    driver = Driver()
    node_fields = {
        "EnvironmentGraph": ["name"],
        "WorkbenchRevision": ["scope_id"],
        "Embodiment": ["id", "env_name", "scope_id"],
        "Fixture": ["id", "env_name", "scope_id"],
        "RigidObject": ["id", "env_name", "scope_id"],
        "USDPrim": ["id", "env_name", "scope_id"],
        "SurfaceAnchor": ["id", "env_name", "scope_id"],
        "ReifiedRelation": ["reifier_id", "env_name", "scope_id"],
        "ArenaPublicationEffect": ["id"],
    }
    driver.constraints = [
        dict(entityType="NODE", type="UNIQUENESS", labelsOrTypes=[label], properties=fields)
        for label, fields in node_fields.items()
    ] + [
        dict(
            entityType="RELATIONSHIP",
            type="RELATIONSHIP_UNIQUENESS",
            labelsOrTypes=[kind],
            properties=["scope_id", "ordinal"],
        )
        for kind in (
            "HAS_REVISION",
            "HAS_EMBODIMENT",
            "HAS_TERRAIN",
            "CONTAINS_OBJECT",
            "CONTAINS_PRIM",
            "AUTHORED_RELATION",
            "HAS_SUB_SURFACE",
            "AUTHORED_ANCHOR",
            "HAS_REIFIER",
            "REIFIES_SUBJECT",
            "REIFIES_OBJECT",
        )
    ]
    return driver


@pytest.mark.parametrize("kind", ["NODE_KEY", "RELATIONSHIP_KEY"])
def test_exact_stronger_keys_satisfy_uniqueness(kind):
    m, driver = transport(), ready_driver()
    entity = "NODE" if kind == "NODE_KEY" else "RELATIONSHIP"
    for row in driver.constraints:
        if row["entityType"] == entity:
            row["type"] = kind
    assert m.verify_schema(driver, "research")


@pytest.mark.parametrize(
    "entity,label,kind,fields",
    [
        ("NODE", "RigidObject", "NODE_PROPERTY_EXISTENCE", ["required_external"]),
        ("NODE", "Terrain", "NODE_PROPERTY_EXISTENCE", ["id"]),
        ("NODE", "EnvironmentGraph", "NODE_PROPERTY_TYPE", ["version"]),
        ("RELATIONSHIP", "HAS_REVISION", "RELATIONSHIP_PROPERTY_EXISTENCE", ["extra"]),
        ("RELATIONSHIP", "HAS_REVISION", "RELATIONSHIP_PROPERTY_TYPE", ["ordinal"]),
        ("NODE", "Fixture", "FUTURE_CONSTRAINT", ["id"]),
        ("NODE", "RigidObject", "NODE_KEY", ["id", "env_name", "scope_id", "extra"]),
        ("RELATIONSHIP", "HAS_REVISION", "RELATIONSHIP_KEY", ["scope_id", "ordinal", "extra"]),
    ],
)
@pytest.mark.parametrize("metadata", [{}, {"propertyType": "STRING"}])
def test_unproven_overlapping_constraints_rejected(entity, label, kind, fields, metadata):
    m, driver = transport(), ready_driver()
    driver.constraints.append(dict(entityType=entity, type=kind, labelsOrTypes=[label], properties=fields, **metadata))
    with pytest.raises(m.SchemaIncompatible):
        m.verify_schema(driver, "research")
    assert all(q.startswith("SHOW CONSTRAINTS") and "propertyType" not in q for q, _ in driver.calls)


def test_unrelated_constraints_do_not_block_and_legacy_reifier_is_safe():
    m, driver = transport(), ready_driver()
    driver.constraints.extend([
        dict(entityType="NODE", type="NODE_PROPERTY_EXISTENCE", labelsOrTypes=["Unrelated"], properties=["extra"]),
        dict(
            entityType="NODE",
            type="UNIQUENESS",
            labelsOrTypes=["ReifiedRelation"],
            properties=["reifier_id", "env_name"],
        ),
    ])
    assert m.verify_schema(driver, "research")


@pytest.mark.parametrize("operation", ["publish_once", "reconcile_once"])
def test_missing_boundary_attestation_opens_no_session(spec, operation):
    m, driver = transport(), ready_driver()
    with pytest.raises(TypeError, match="immutable_scope_attested"):
        getattr(m, operation)(driver, "research", project(spec), spec=spec, effect_id="effect-1")
    assert not driver.sessions and not driver.calls


@pytest.mark.parametrize("operation", ["publish_once", "reconcile_once"])
@pytest.mark.parametrize("attestation", [None, False, 1, "true", {}])
def test_invalid_boundary_attestation_opens_no_session(spec, operation, attestation):
    m, driver = transport(), ready_driver()
    with pytest.raises(ValueError, match="operator attestation"):
        getattr(m, operation)(
            driver, "research", project(spec), spec=spec, effect_id="effect-1", immutable_scope_attested=attestation
        )
    assert not driver.sessions and not driver.calls


def test_receipts_explicitly_declare_operator_boundary_not_snapshot(spec):
    m, driver, projection = transport(), ready_driver(), project(spec)
    for operation in (m.publish_once, m.reconcile_once):
        receipt = operation(
            driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True
        )
        assert receipt["verification_boundary"] == {
            "method": "operator_attested_immutable_scope_v1",
            "operator_attested": True,
            "declaration": m.IMMUTABLE_SCOPE_DECLARATION,
            "database_snapshot": False,
        }
    assert "outside writers" in m.IMMUTABLE_SCOPE_DECLARATION
    assert all("SET" not in q or "ON CREATE SET" in q for q, _ in driver.calls)


def test_external_mutable_observations_are_not_snapshot_safety(spec):
    # Deliberately VIOLATE the operator declaration: each statement sees a different
    # invalid graph, while their combined rows happen to match. The receipt is only
    # conditional on operator-attested exclusion, never database snapshot evidence.
    m, driver, projection = transport(), ready_driver(), project(spec)
    observed = []

    def external_writer(tx):
        if not observed:
            tx.edges[0]["properties"]["extra"] = "external-corruption"
        else:
            next(n for n in tx.nodes.values() if n["labels"] == ["RigidObject"])["properties"]["extra"] = True
        driver.nodes, driver.edges = deepcopy(tx.nodes), deepcopy(tx.edges)
        observed.append(deepcopy((tx.nodes, tx.edges)))
        if len(observed) == 1:
            # External writer changes the graph between the nodes and edges reads.
            driver.edges[0]["properties"].pop("extra")
            next(n for n in driver.nodes.values() if n["labels"] == ["RigidObject"])["properties"]["extra"] = True

    driver.read_mutation = external_writer
    receipt = m.publish_once(
        driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True
    )
    assert len(observed) == 2
    assert observed[0][1][0]["properties"]["extra"] == "external-corruption"
    assert any(n["properties"].get("extra") is True for n in observed[1][0].values())
    assert receipt["verification_boundary"]["database_snapshot"] is False
    assert receipt["verification_boundary"]["method"] == "operator_attested_immutable_scope_v1"


def test_publish_roundtrip_uses_one_explicit_transaction_and_actual_rows(spec):
    m, driver, projection = transport(), ready_driver(), project(spec)
    receipt = m.publish_once(
        driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True
    )
    assert receipt["status"] == "verified"
    assert receipt["effect_id"] == "effect-1"
    assert receipt["projection_digest"] == projection["digest"]
    assert driver.commits == 1
    assert len(driver.sessions) == 1
    assert len(driver.sessions[0].transactions) == 1
    assert driver.sessions[0].transactions[0].options["timeout"] == 5.0
    assert driver.sessions[0].closed and driver.sessions[0].transactions[0].closed
    assert not any(q.startswith("CREATE CONSTRAINT") or "ON MATCH" in q for q, _ in driver.calls)
    assert any(q.startswith("// nodes") for q, _ in driver.calls)
    assert all(
        "digest" not in n["properties"] for n in driver.nodes.values() if "ArenaPublicationEffect" not in n["labels"]
    )


def test_commit_ack_loss_then_absent_and_later_readonly_reconciliation(spec):
    m, driver, projection = transport(), ready_driver(), project(spec)
    driver.ack_loss = True
    with pytest.raises(m.OutcomeUnknown):
        m.publish_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)
    assert driver.commits == 1 and len(driver.sessions[0].transactions) == 1
    absent = ready_driver()
    assert (
        m.reconcile_once(
            absent, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True
        )["status"]
        == "unknown"
    )
    start = len(driver.calls)
    assert (
        m.reconcile_once(
            driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True
        )["status"]
        == "verified"
    )
    assert driver.commits == 1
    assert all("MERGE" not in q and "SET" not in q for q, _ in driver.calls[start:])
    assert driver.sessions[-1].options["default_access_mode"] == "READ"


@pytest.mark.parametrize(
    "label,fields", [("RigidObject", ["id"]), ("Fixture", ["id", "env_name"]), ("Terrain", ["id"])]
)
def test_incompatible_legacy_global_asset_constraints_fail_closed(label, fields):
    m, driver = transport(), ready_driver()
    driver.constraints.append(dict(entityType="NODE", type="UNIQUENESS", labelsOrTypes=[label], properties=fields))
    with pytest.raises(m.SchemaIncompatible):
        m.verify_schema(driver, "research")


@pytest.mark.parametrize("extra", projection_tests.hydrated_extras())
def test_hydrated_root_metadata_survives_publish_and_reconcile(spec, extra):
    m, driver, projection = transport(), ready_driver(), project(spec)
    root = next(n["properties"] for n in projection["nodes"] if n["labels"] == ["EnvironmentGraph"])
    driver.nodes["legacy-root"] = dict(
        eid="legacy-root", labels=["EnvironmentGraph"], properties={**root, "created_at": extra}
    )
    assert (
        m.publish_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)[
            "status"
        ]
        == "verified"
    )
    assert driver.nodes["legacy-root"]["properties"] == {**root, "created_at": extra}
    assert (
        m.reconcile_once(
            driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True
        )["status"]
        == "verified"
    )


@pytest.mark.parametrize("target", ["node", "edge", "marker"])
@pytest.mark.parametrize("extra", projection_tests.hydrated_extras() + [object()])
def test_nonroot_hydrated_or_unknown_extras_rejected_without_repair(spec, target, extra):
    m, driver, projection = transport(), ready_driver(), project(spec)
    m.publish_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)
    if target == "edge":
        record = driver.edges[0]
    else:
        label = "RigidObject" if target == "node" else "ArenaPublicationEffect"
        record = next(n for n in driver.nodes.values() if n["labels"] == [label])
    record["properties"]["extra"] = extra
    with pytest.raises(m.OutcomeUnknown):
        m.reconcile_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)
    assert record["properties"]["extra"] is extra
    assert driver.commits == 1


def test_raw_rows_unknown_objects_fail_without_calling_serializer():
    class Hostile:
        def __str__(self):
            raise AssertionError("must not stringify unknown values")

    with pytest.raises(ValueError, match="Unsupported"):
        transport()._rows([{"properties": {"extra": Hostile()}}])


def test_actual_record_byte_bound_stops_consumption():
    m = transport()
    with pytest.raises(ValueError, match="byte bound"):
        m._rows(iter([{"properties": {"blob": "x" * (m.MAX_BYTES + 1)}}]))


@pytest.mark.parametrize("change", ["property", "extra_node", "extra_edge", "endpoint", "root", "effect", "labels"])
def test_existing_corruption_blocks_without_repair(spec, change):
    m, driver, projection = transport(), ready_driver(), project(spec)
    m.publish_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)
    owned = next(n for n in driver.nodes.values() if n["labels"] == ["RigidObject"])
    if change == "property":
        owned["properties"]["unexpected"] = True
    elif change == "extra_node":
        driver.nodes["extra"] = dict(eid="extra", labels=["Intruder"], properties={"scope_id": projection["scope_id"]})
    elif change == "extra_edge":
        driver.edges.append(deepcopy(driver.edges[0]))
    elif change == "endpoint":
        driver.edges[0]["target"] = driver.edges[0]["source"]
    elif change == "root":
        next(n for n in driver.nodes.values() if n["labels"] == ["EnvironmentGraph"])["properties"]["spec_json"] = "{}"
    elif change == "effect":
        next(n for n in driver.nodes.values() if n["labels"] == ["ArenaPublicationEffect"])["properties"][
            "digest"
        ] = "different"
    else:
        owned["labels"].append("Intruder")
    before = deepcopy((driver.nodes, driver.edges))
    with pytest.raises(m.OutcomeUnknown):
        m.publish_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)
    assert driver.commits == 1
    assert (driver.nodes, driver.edges) == before
    with pytest.raises(m.OutcomeUnknown):
        m.reconcile_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)


@pytest.mark.parametrize("failure", ["read_failure", "close_failure"])
def test_postcommit_failure_is_unknown_not_retryable(spec, failure):
    m, driver, projection = transport(), ready_driver(), project(spec)
    setattr(driver, failure, True)
    with pytest.raises(m.OutcomeUnknown):
        m.publish_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)
    assert driver.commits == 1
    assert len(driver.sessions[0].transactions) == 1
    assert driver.sessions[0].closed


def test_missing_schema_is_read_only_and_publish_fails_before_writes(spec):
    m, driver = transport(), Driver()
    with pytest.raises(m.SchemaIncompatible):
        m.verify_schema(driver, "research")
    with pytest.raises(m.OutcomeUnknown):
        m.publish_once(
            driver, "research", project(spec), spec=spec, effect_id="effect-1", immutable_scope_attested=True
        )
    assert not driver.nodes and driver.commits == 0
    assert all(q.startswith("SHOW CONSTRAINTS") for q, _ in driver.calls)


def test_duplicate_effect_requires_actual_readback_and_never_repairs(spec):
    m, driver, projection = transport(), ready_driver(), project(spec)
    m.publish_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)
    start = len(driver.calls)
    assert (
        m.publish_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)[
            "status"
        ]
        == "verified"
    )
    assert all("MERGE" not in q for q, _ in driver.calls[start:])
    other = project(spec, revision_id="revision-2")
    with pytest.raises(m.OutcomeUnknown):
        m.publish_once(driver, "research", other, spec=spec, effect_id="effect-1", immutable_scope_attested=True)
    assert driver.commits == 2


@pytest.mark.parametrize("kind", ["node", "edge", "canonical_root"])
def test_first_effect_never_repairs_preexisting_records(spec, kind):
    m, driver, projection = transport(), ready_driver(), project(spec)
    m.publish_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)
    marker = next(k for k, n in driver.nodes.items() if n["labels"] == ["ArenaPublicationEffect"])
    del driver.nodes[marker]
    if kind == "node":
        next(n for n in driver.nodes.values() if n["labels"] == ["RigidObject"])["properties"]["params_json"] = "bad"
    elif kind == "edge":
        driver.edges[0]["properties"]["unexpected"] = "bad"
    else:
        next(n for n in driver.nodes.values() if n["labels"] == ["EnvironmentGraph"])["properties"]["version"] = "bad"
    before = deepcopy((driver.nodes, driver.edges))
    with pytest.raises(m.OutcomeUnknown):
        m.publish_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)
    assert (driver.nodes, driver.edges) == before
    assert driver.commits == 1


def test_projection_total_record_bound_precedes_session(spec, monkeypatch):
    m, driver = transport(), ready_driver()
    monkeypatch.setattr(m, "MAX_RECORDS", 2)
    with pytest.raises(m.OutcomeUnknown):
        m.publish_once(
            driver, "research", project(spec), spec=spec, effect_id="effect-1", immutable_scope_attested=True
        )
    assert not driver.sessions


def test_postcommit_actual_properties_not_expected_copy(spec):
    m, driver, projection = transport(), ready_driver(), project(spec)

    def mutate(tx):
        next(n for n in tx.nodes.values() if n["labels"] == ["RigidObject"])["properties"]["params_json"] = "{}"

    driver.read_mutation = mutate
    with pytest.raises(m.OutcomeUnknown):
        m.publish_once(driver, "research", projection, spec=spec, effect_id="effect-1", immutable_scope_attested=True)
    assert driver.commits == 1
