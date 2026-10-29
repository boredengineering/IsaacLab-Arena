# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded Neo4j transport; no credentials, grants, retries, or automatic DDL.

The caller must durably record and recheck a write release before publish_once,
using an authorized driver configured with max_transaction_retry_time=0. A read
release authorizes only verify_schema/reconcile_once, never publication. Unknown
outcomes do not grant permission to retry. Schema must remain stable during use.
Verification is conditional on a REQUIRED operator-attested deployment boundary:
only cooperative writers may own the canonical root fields, effect marker, revision
scope and incident relationships. They atomically create absent content and never
mutate/delete/repair existing owned content or add unexpected scoped records. The
operator must exclude outside writers for the lifetime of this publication. Outside
writers break the guarantee; neither bookmarks nor read-committed transactions give
snapshot isolation, and this module cannot verify the deployment's attestation.
Bind immutable_scope_attested in an immutable authorized target profile, never a
user-controlled request or a silent True default. No locks or admin writes are used.
Requires Neo4j >=5.7 relationship uniqueness support; schema syntax reference:
https://neo4j.com/docs/cypher-manual/5/constraints/create-constraints/
"""

from __future__ import annotations

import hashlib
import json

from neo4j import Query

from isaaclab_arena.agentic_environment_generation.graph_cleanup import GraphCleanupError, close_graph_resources

from .research_projection import (
    _bounded,
    bounded_neo4j_value,
    check_root_compatibility,
    compare_readback,
    validate_projection,
)

MAX_RECORDS = 4096
MAX_BYTES = 4 * 1024 * 1024
READ_TIMEOUT = 3.0
WRITE_TIMEOUT = 5.0
IMMUTABLE_SCOPE_DECLARATION = (
    "Deployment excludes outside writers from canonical owned root fields, effect markers, "
    "revision-scoped nodes and incident relationships for the publication lifetime; "
    "cooperative exclusive-scope writers only atomically create absent content and never "
    "mutate, delete, repair, or extend existing owned content. Schema remains stable."
)

# All interpolated identifiers originate exclusively in these internal tables.
NODE_KEYS = {
    ("EnvironmentGraph",): ("name",),
    ("WorkbenchRevision",): ("scope_id",),
    ("Embodiment",): ("id", "env_name", "scope_id"),
    ("Fixture", "Terrain"): ("id", "env_name", "scope_id"),
    ("RigidObject",): ("id", "env_name", "scope_id"),
    ("USDPrim",): ("id", "env_name", "scope_id"),
    ("SurfaceAnchor",): ("id", "env_name", "scope_id"),
    ("ReifiedRelation",): ("reifier_id", "env_name", "scope_id"),
    ("ArenaPublicationEffect",): ("id",),
}
EDGE_TYPES = (
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
SHOW_CONSTRAINTS = "SHOW CONSTRAINTS YIELD entityType, type, labelsOrTypes, properties RETURN * LIMIT 4097"


class SchemaIncompatible(RuntimeError):
    """Read-only preflight could not prove the required uniqueness capability."""


class OutcomeUnknown(RuntimeError):
    """Released invocation failed; no automatic or implicit write retry is safe."""


class PublicationCleanupError(GraphCleanupError, OutcomeUnknown):
    """Cleanup veto with the publication unknown-outcome/no-write-retry contract."""


def schema_requirements():
    """Return public constraint data and DDL for separate administrator approval."""
    result = []
    for labels, fields in NODE_KEYS.items():
        label = labels[0]
        columns = ", ".join(f"n.{field}" for field in fields)
        result.append(
            dict(
                entityType="NODE",
                type="UNIQUENESS",
                label=label,
                properties=list(fields),
                ddl=f"CREATE CONSTRAINT arena_p2_{label} IF NOT EXISTS FOR (n:{label}) REQUIRE ({columns}) IS UNIQUE",
            )
        )
    for kind in EDGE_TYPES:
        result.append(
            dict(
                entityType="RELATIONSHIP",
                type="RELATIONSHIP_UNIQUENESS",
                label=kind,
                properties=["scope_id", "ordinal"],
                ddl=(
                    f"CREATE CONSTRAINT arena_p2_{kind} IF NOT EXISTS FOR ()-[r:{kind}]-() REQUIRE (r.scope_id,"
                    " r.ordinal) IS UNIQUE"
                ),
            )
        )
    return result


def _rows(result):
    rows = []
    size = 0
    for row in result:
        if len(rows) >= MAX_RECORDS:
            raise ValueError("Readback record bound exceeded")
        record = dict(row)
        size += bounded_neo4j_value(record, max_bytes=MAX_BYTES - size)
        if size > MAX_BYTES:
            raise ValueError("Readback byte bound exceeded")
        rows.append(record)
    return rows


def _verify(tx):
    rows = _rows(tx.run(SHOW_CONSTRAINTS))
    for row in rows:
        for labels, fields in NODE_KEYS.items():
            if row["entityType"] == "NODE" and set(row["labelsOrTypes"]) & set(labels):
                # Keys also impose existence: only the exact owned key is proven safe.
                if row["type"] == "NODE_KEY" and set(row["properties"]) == set(fields):
                    continue
                if row["type"] != "UNIQUENESS":
                    raise SchemaIncompatible("Unproven overlapping node constraint")
                # DCRG reifier physical IDs already include the full authored scope.
                safe_reifier = labels == ("ReifiedRelation",) and "reifier_id" in row["properties"]
                if not set(fields) <= set(row["properties"]) and not safe_reifier:
                    raise SchemaIncompatible("Incompatible global node uniqueness constraint")
        if row["entityType"] == "RELATIONSHIP" and set(row["labelsOrTypes"]) & set(EDGE_TYPES):
            if row["type"] == "RELATIONSHIP_KEY" and set(row["properties"]) == {"scope_id", "ordinal"}:
                continue
            if row["type"] != "RELATIONSHIP_UNIQUENESS":
                raise SchemaIncompatible("Unproven overlapping relationship constraint")
            if not {"scope_id", "ordinal"} <= set(row["properties"]):
                raise SchemaIncompatible("Incompatible global relationship uniqueness constraint")
    # Existence/type/future kinds deliberately fail closed above, even with metadata.
    # Do not YIELD propertyType: that column is absent on older supported Neo4j 5.x.
    for requirement in schema_requirements():
        stronger = "NODE_KEY" if requirement["entityType"] == "NODE" else "RELATIONSHIP_KEY"
        if not any(
            row["entityType"] == requirement["entityType"]
            and row["type"] in (requirement["type"], stronger)
            and row["labelsOrTypes"] == [requirement["label"]]
            and set(row["properties"]) == set(requirement["properties"])
            for row in rows
        ):
            raise SchemaIncompatible(f"Missing uniqueness capability: {requirement['label']}")


def verify_schema(driver, database):
    """Read SHOW CONSTRAINTS in a bounded explicit read transaction; never install DDL."""
    session = tx = None
    try:
        session = driver.session(database=database, default_access_mode="READ", fetch_size=128)
        tx = session.begin_transaction(timeout=READ_TIMEOUT)
        _verify(tx)
        return True
    except Exception as error:
        raise SchemaIncompatible("Required schema/capability could not be verified") from error
    finally:
        _close(tx, session)


ROOT_QUERY = (
    "// root\nMATCH (n:EnvironmentGraph {name: $name}) RETURN elementId(n) AS eid, labels(n) AS labels, properties(n)"
    " AS properties LIMIT 2"
)
EFFECT_QUERY = (
    "// effect\nMATCH (n:ArenaPublicationEffect {id: $effect_id}) RETURN elementId(n) AS eid, labels(n) AS labels,"
    " properties(n) AS properties LIMIT 2"
)
NODES_QUERY = (
    "// nodes\nMATCH (n) WHERE n.scope_id = $scope_id OR (n:EnvironmentGraph AND n.name = $name) RETURN elementId(n) AS"
    " eid, labels(n) AS labels, properties(n) AS properties LIMIT 4097"
)
EDGES_QUERY = (
    "// edges\nMATCH (a)-[r]->(b) WHERE r.scope_id = $scope_id OR a.scope_id = $scope_id OR b.scope_id = $scope_id"
    " RETURN elementId(a) AS source, elementId(b) AS target, type(r) AS type, properties(r) AS properties LIMIT 4097"
)
NODE_QUERIES = {
    labels: (
        "// node\nMERGE (n:"
        + ":".join(labels)
        + " {"
        + ", ".join(f"{k}: $key.{k}" for k in fields)
        + "}) ON CREATE SET n = $properties RETURN elementId(n) AS eid, labels(n) AS labels, properties(n) AS"
        " properties LIMIT 2"
    )
    for labels, fields in NODE_KEYS.items()
}
EDGE_QUERIES = {
    kind: (
        "// edge\nMATCH (a), (b) WHERE elementId(a) = $source AND elementId(b) = $target MERGE (a)-[r:"
        + kind
        + " {scope_id: $key.scope_id, ordinal: $key.ordinal}]->(b) ON CREATE SET r = $properties "
        "RETURN elementId(a) AS source, elementId(b) AS target, type(r) AS type, properties(r) AS properties LIMIT 2"
    )
    for kind in EDGE_TYPES
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _seal(value):
    return {**value, "digest": _hash(value)}


def _node(row, projection):
    labels = tuple(sorted(row["labels"]))
    fields = NODE_KEYS[labels]
    properties = dict(row["properties"])
    if labels == ("EnvironmentGraph",):
        check_root_compatibility(projection, [properties])
        properties = {k: properties[k] for k in ("name", "version", "spec_sha256", "spec_json", "source_env_name")}
    _bounded(properties)
    key = {k: properties[k] for k in fields}
    return _seal(dict(id=_hash([list(labels), key]), labels=list(labels), key=key, properties=properties))


def _edge(row, identities):
    kind, properties = row["type"], dict(row["properties"])
    _bounded(properties)
    if kind not in EDGE_TYPES:
        raise ValueError("Unexpected relationship type")
    source, target = identities[row["source"]], identities[row["target"]]
    key = {k: properties[k] for k in ("scope_id", "ordinal")}
    return _seal(
        dict(
            id=_hash([source, target, kind, key]),
            source=source,
            target=target,
            type=kind,
            key=key,
            properties=properties,
        )
    )


def _binding(database, projection, effect_id):
    if not isinstance(database, str) or not database.strip() or len(database.encode()) > 1024:
        raise ValueError("Explicit bounded destination database required")
    if not isinstance(effect_id, str) or not effect_id.strip() or len(effect_id.encode()) > 1024:
        raise ValueError("Explicit bounded effect identity required")
    return dict(
        id=effect_id,
        digest=projection["digest"],
        scope_id=projection["scope_id"],
        database=database,
        canonical_name=projection["canonical_identity"]["name"],
        canonical_sha256=projection["canonical_identity"]["sha256"],
        source_sha256=projection["hashes"]["workbench"]["sha256"],
    )


def _exact_effect(rows, binding):
    if len(rows) != 1 or rows[0]["labels"] != ["ArenaPublicationEffect"] or rows[0]["properties"] != binding:
        raise ValueError("Immutable effect binding conflict or absent marker")


def _readback(run, projection, spec, binding):
    params = dict(scope_id=projection["scope_id"], name=projection["canonical_identity"]["name"])
    raw_nodes = _rows(run(NODES_QUERY, **params))
    raw_edges = _rows(run(EDGES_QUERY, **params))
    markers = [r for r in raw_nodes if "ArenaPublicationEffect" in r["labels"]]
    _exact_effect(markers, binding)
    raw_nodes = [r for r in raw_nodes if "ArenaPublicationEffect" not in r["labels"]]
    nodes = [_node(r, projection) for r in raw_nodes]
    identities = {r["eid"]: n["id"] for r, n in zip(raw_nodes, nodes)}
    edges = [_edge(r, identities) for r in raw_edges]
    compare_readback(projection, nodes, edges, spec=spec)


def _boundary(immutable_scope_attested):
    if immutable_scope_attested is not True:
        raise ValueError("Explicit operator attestation of immutable exclusive scope is required")
    return dict(
        method="operator_attested_immutable_scope_v1",
        operator_attested=immutable_scope_attested,
        declaration=IMMUTABLE_SCOPE_DECLARATION,
        database_snapshot=False,
    )


def _receipt(database, projection, effect_id, boundary):
    return dict(
        status="verified",
        database=database,
        effect_id=effect_id,
        scope_id=projection["scope_id"],
        projection_digest=projection["digest"],
        verification_boundary=dict(boundary),
        canonical_identity=dict(projection["canonical_identity"]),
    )


def _close(tx, session):
    close_graph_resources(tx, session)


def publish_once(driver, database, projection, *, spec, effect_id, immutable_scope_attested):
    """Publish once under an explicit operator-attested immutable-scope contract.

    immutable_scope_attested must be exactly True from the authorized target profile;
    omission/invalid attestation opens no session. This is an operator declaration,
    not a lock or database snapshot. After admission, failures are outcome-unknown.
    """
    boundary = _boundary(immutable_scope_attested)
    session = tx = None
    try:
        try:
            validate_projection(projection, spec=spec)
            if len(projection["nodes"]) + len(projection["edges"]) + 1 > MAX_RECORDS:
                raise ValueError("Projection total record bound exceeded (including effect marker)")
            binding = _binding(database, projection, effect_id)
            session = driver.session(database=database, default_access_mode="WRITE", fetch_size=128)
            tx = session.begin_transaction(timeout=WRITE_TIMEOUT)
            _verify(tx)
            roots = _rows(tx.run(ROOT_QUERY, name=projection["canonical_identity"]["name"]))
            check_root_compatibility(projection, [r["properties"] for r in roots])
            effects = _rows(tx.run(EFFECT_QUERY, effect_id=effect_id))
            if effects:
                _exact_effect(effects, binding)
            else:
                _exact_effect(
                    _rows(tx.run(NODE_QUERIES[("ArenaPublicationEffect",)], key={"id": effect_id}, properties=binding)),
                    binding,
                )
                identities = {}
                for node in projection["nodes"]:
                    rows = _rows(
                        tx.run(NODE_QUERIES[tuple(node["labels"])], key=node["key"], properties=node["properties"])
                    )
                    if len(rows) != 1 or _node(rows[0], projection) != node:
                        raise ValueError("Immutable node conflict")
                    identities[node["id"]] = rows[0]["eid"]
                reverse = {eid: nid for nid, eid in identities.items()}
                for edge in projection["edges"]:
                    rows = _rows(
                        tx.run(
                            EDGE_QUERIES[edge["type"]],
                            source=identities[edge["source"]],
                            target=identities[edge["target"]],
                            key=edge["key"],
                            properties=edge["properties"],
                        )
                    )
                    if len(rows) != 1 or _edge(rows[0], reverse) != edge:
                        raise ValueError("Immutable edge conflict")
            _readback(tx.run, projection, spec, binding)
            tx.commit()
            # The bookmark provides causal visibility of this commit, NOT a snapshot.
            # Separate reads are sound only under the operator's immutable boundary.
            # Auto-commit reads are never retried.
            _readback(lambda q, **p: session.run(Query(q, timeout=READ_TIMEOUT), **p), projection, spec, binding)
            return _receipt(database, projection, effect_id, boundary)
        finally:
            _close(tx, session)
    except GraphCleanupError:
        raise PublicationCleanupError(
            "Graph cleanup failed; publication outcome unknown, never implicitly retry"
        ) from None
    except Exception as error:
        raise OutcomeUnknown("Publication outcome unknown; reconcile read-only, never implicitly retry") from error


def reconcile_once(driver, database, projection, *, spec, effect_id, immutable_scope_attested):
    """Reconcile read-only under the same required operator attestation as publish_once.

    Read-committed statements do not prove a snapshot. No lock/dummy SET is used.
    Absent markers remain unknown, never permission to write or repair.
    """
    boundary = _boundary(immutable_scope_attested)
    session = tx = None
    try:
        try:
            validate_projection(projection, spec=spec)
            if len(projection["nodes"]) + len(projection["edges"]) + 1 > MAX_RECORDS:
                raise ValueError("Projection total record bound exceeded (including effect marker)")
            binding = _binding(database, projection, effect_id)
            session = driver.session(database=database, default_access_mode="READ", fetch_size=128)
            tx = session.begin_transaction(timeout=READ_TIMEOUT)
            _verify(tx)
            effects = _rows(tx.run(EFFECT_QUERY, effect_id=effect_id))
            if not effects:
                return dict(
                    status="unknown",
                    effect_id=effect_id,
                    database=database,
                    reason="Marker absent; absence does not authorize another write",
                    verification_boundary=dict(boundary),
                )
            _exact_effect(effects, binding)
            _readback(tx.run, projection, spec, binding)
            return _receipt(database, projection, effect_id, boundary)
        finally:
            _close(tx, session)
    except GraphCleanupError:
        raise PublicationCleanupError("Graph cleanup failed; reconciliation outcome unknown") from None
    except Exception as error:
        raise OutcomeUnknown("Read-only reconciliation could not verify the publication") from error
