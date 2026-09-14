# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure authored-scene projection, not a writer, retrieval policy, or evidence claim."""

from __future__ import annotations

import hashlib
import json
import math

from pydantic import BaseModel

from isaaclab_arena.agentic_environment_generation.dcrg.graph import graph_identity
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

MAX_SOURCE_BYTES = 256 * 1024
MAX_PROJECTION_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 4096
MAX_DEPTH = 32


def _bounded(value, *, max_bytes=MAX_PROJECTION_BYTES):
    # Inspect pre-serialization values: Pydantic JSON mode can replace NaN with null.
    stack = [(value, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > MAX_DEPTH or count > 100000:
            raise ValueError("Projection depth/item bound exceeded")
        if isinstance(item, BaseModel):
            stack.extend((getattr(item, key), depth + 1) for key in type(item).model_fields)
        elif type(item) is dict:
            if len(item) > MAX_RECORDS:
                raise ValueError("Projection collection bound exceeded")
            if not all(type(key) is str for key in item):
                raise ValueError("JSON keys must be strings")
            stack.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif type(item) in (list, tuple):
            if len(item) > MAX_RECORDS:
                raise ValueError("Projection collection bound exceeded")
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            # Authored Pydantic specs include string enums; raw reads are stricter.
            if len(item.encode("utf-8")) > max_bytes:
                raise ValueError("Projection string bound exceeded")
        elif type(item) is bool or item is None:
            pass
        elif type(item) is int:
            if not -(2**63) <= item < 2**63:
                raise ValueError("Neo4j integer out of range")
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("Nonfinite authored number")
        else:
            raise ValueError("Unsupported JSON value")


def bounded_neo4j_value(value, *, max_bytes=MAX_PROJECTION_BYTES):
    """Inspect raw hydrated values without serializing or normalizing owned content.

    Return a conservative byte-budget charge, not a wire-size measurement. Containers
    have depth/item/width bounds; temporal scalars and spatial coordinates are inspected
    through the driver's concrete types only. Arbitrary objects/subclasses fail closed.
    This tolerance is for raw reads/root extras, never canonical owned JSON fields.
    """
    from neo4j.spatial import CartesianPoint, WGS84Point
    from neo4j.time import Date, DateTime, Duration, Time

    temporal_fields = {
        Date: ("year", "month", "day"),
        Time: ("hour", "minute", "second", "nanosecond"),
        DateTime: ("year", "month", "day", "hour", "minute", "second", "nanosecond"),
        Duration: ("months", "days", "seconds", "nanoseconds"),
    }
    stack = [(value, 0)]
    count = size = 0
    while stack:
        item, depth = stack.pop()
        kind = type(item)
        count += 1
        size += 16  # Container delimiters, scalar framing, and per-item overhead.
        if depth > MAX_DEPTH or count > 100000:
            raise ValueError("Readback depth/item bound exceeded")
        if kind is dict:
            if len(item) > MAX_RECORDS or any(type(k) is not str for k in item):
                raise ValueError("Readback collection/key bound exceeded")
            stack.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif kind in (list, tuple):
            if len(item) > MAX_RECORDS:
                raise ValueError("Readback collection bound exceeded")
            stack.extend((child, depth + 1) for child in item)
        elif kind is str:
            # At most six JSON escape bytes per UTF-8 byte, without encoding huge inputs.
            if len(item) > max_bytes:
                raise ValueError("Readback byte bound exceeded")
            size += 6 * len(item.encode("utf-8"))
        elif kind in (bytes, bytearray):
            size += len(item)
        elif kind is bool or item is None:
            pass
        elif kind is int:
            if not -(2**63) <= item < 2**63:
                raise ValueError("Neo4j integer out of range")
            size += 20
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError("Nonfinite readback number")
            size += 24
        elif kind in temporal_fields:
            # Do not call str(), iso_format(), or user-provided timezone methods.
            stack.extend((getattr(item, field), depth + 1) for field in temporal_fields[kind])
            if kind in (DateTime, Time) and item.tzinfo is not None:
                from datetime import timezone

                import pytz

                zone = item.tzinfo
                if type(zone) is timezone:
                    size += 128  # Offset is fixed; its optional name is bounded below.
                    stack.append((zone.tzname(None), depth + 1))
                elif type(zone) is type(pytz.FixedOffset(1)):
                    size += 128  # Driver-hydrated fixed numeric offset, no zone name.
                elif type(zone) is type(pytz.UTC) or (
                    isinstance(zone, (pytz.tzinfo.DstTzInfo, pytz.tzinfo.StaticTzInfo))
                    and type(zone).__module__.startswith("pytz.")
                ):
                    stack.append((zone.zone, depth + 1))
                else:
                    raise ValueError("Unsupported temporal timezone")
        elif kind in (CartesianPoint, WGS84Point):
            if len(item) not in (2, 3):
                raise ValueError("Unsupported spatial dimension")
            stack.extend((child, depth + 1) for child in (*item, item.srid))
        else:
            raise ValueError("Unsupported hydrated Neo4j value")
        if size > max_bytes:
            raise ValueError("Readback byte bound exceeded")
    return size


def _encoded_bound(value, limit):
    text = _json(value)
    if len(text.encode("utf-8")) > limit:
        raise ValueError("Projection encoded byte bound exceeded")
    return text


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _seal(record):
    return {**record, "digest": _sha(_json(record))}


def project_scene(spec: ArenaEnvGraphSpec, *, revision_id, store_id, family, version) -> dict:
    """Return detached JSON records with explicit canonical and revision identities.

    Args:
        spec: Authored schema instance, never renamed or mutated.
        revision_id: Immutable revision identifier in the caller's store.
        store_id: Explicit store namespace.
        family: External scenario family, distinct from the source environment name.
        version: External version label, not a canonical content hash.

    Returns:
        Identity mappings and complete owned node/edge records. Node keys are MERGE
        keys; properties include keys. Record digests are envelope checksums, not
        additional Neo4j properties. The canonical root payload must never be SET
        on match. Existing unrelated DCRG records are outside this owned readback.
    """
    if not isinstance(spec, ArenaEnvGraphSpec):
        raise ValueError("Expected ArenaEnvGraphSpec")
    for value in (revision_id, store_id, family, version):
        if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > 1024:
            raise ValueError("Explicit bounded text scope required")
    _bounded(spec, max_bytes=MAX_SOURCE_BYTES)
    try:
        spec.validate()
    except (AssertionError, KeyError, TypeError) as error:
        raise ValueError("Invalid authored references") from error
    data = spec.to_dict()
    payload = _encoded_bound(data, MAX_SOURCE_BYTES)
    compact_hash = _sha(payload)
    targets = []
    for target in sorted({
        task.params["pick_up_object"]
        for task in spec.task.subtasks
        if isinstance(task.params.get("pick_up_object"), str)
    }):
        try:
            identity = graph_identity(spec, target_object_id=target)
            targets.append({"target_object_id": target, "status": "supported", **identity})
        except ValueError as error:
            targets.append({"target_object_id": target, "status": "unsupported", "reason": str(error)})
    supported = [target for target in targets if target["status"] == "supported"]
    name = supported[0]["env_name"] if supported else f"workbench__{compact_hash}"
    scope = dict(
        store_id=store_id, revision_id=revision_id, family=family, version=version, internal_env_name=spec.env_name
    )
    scope_id = _sha(_json({**scope, "canonical_sha256": compact_hash}))
    nodes, edges = [], []

    def node(labels, key, properties):
        nid = _sha(_json([labels, key]))
        if any(n["id"] == nid for n in nodes):
            raise ValueError("Duplicate authored node identity")
        if len(nodes) >= MAX_RECORDS:
            raise ValueError("Projection node bound exceeded")
        nodes.append(_seal(dict(id=nid, labels=labels, key=key, properties={**key, **properties})))
        return nid

    def edge(source, target, kind, properties=None):
        if len(edges) >= MAX_RECORDS:
            raise ValueError("Projection edge bound exceeded")
        key = {"scope_id": scope_id, "ordinal": len(edges)}
        record = dict(source=source, target=target, type=kind, key=key, properties={**key, **(properties or {})})
        edges.append(_seal({"id": _sha(_json([source, target, kind, key])), **record}))

    root = node(
        ["EnvironmentGraph"],
        {"name": name},
        dict(version=compact_hash, spec_sha256=compact_hash, spec_json=payload, source_env_name=spec.env_name),
    )
    revision = node(["WorkbenchRevision"], {"scope_id": scope_id}, {**scope, "canonical_sha256": compact_hash})
    edge(root, revision, "HAS_REVISION")
    mapping = {}
    for role, labels, kind, entries in (
        ("embodiment", ["Embodiment"], "HAS_EMBODIMENT", [data["embodiment"]]),
        ("background", ["Fixture", "Terrain"], "HAS_TERRAIN", [data["background"]]),
        ("object", ["RigidObject"], "CONTAINS_OBJECT", data["objects"]),
        ("object_reference", ["USDPrim"], "CONTAINS_PRIM", data.get("object_references", [])),
    ):
        for entry in entries:
            nid = node(
                labels,
                {"id": entry["id"], "env_name": name, "scope_id": scope_id},
                {
                    "role": role,
                    **{k: entry[k] for k in ("registry_name", "prim_path", "object_type", "parent_id") if k in entry},
                    "spec_json": _json(entry),
                    "params_json": _json(entry.get("params", {})),
                },
            )
            mapping[entry["id"]] = nid
            edge(root, nid, kind)
    for entry in data.get("object_references", []):
        edge(mapping[entry["parent_id"]], mapping[entry["id"]], "CONTAINS_PRIM")
    for index, relation in enumerate(data["relations"]):
        subject = mapping[relation["subject"]]
        reference = mapping[relation["reference"]] if "reference" in relation else subject
        edge(
            subject,
            reference,
            "AUTHORED_RELATION",
            {
                "kind": relation["kind"],
                "arity": "binary" if "reference" in relation else "unary",
                "spec_json": _json(relation),
                "params_json": _json(relation.get("params", {})),
            },
        )
        if "surface_anchor" in relation.get("params", {}):
            anchor = node(
                ["SurfaceAnchor"],
                {"id": f"relation:{index}", "env_name": name, "scope_id": scope_id},
                {"anchor_json": _json(relation["params"]["surface_anchor"])},
            )
            edge(reference, anchor, "HAS_SUB_SURFACE")
            edge(subject, anchor, "AUTHORED_ANCHOR")
    reifier_mapping = {}
    for relation in data.get("reified_relations", []):
        if relation["source_id"] not in mapping or relation["target_id"] not in mapping:
            raise ValueError("Unknown authored reifier endpoint")
        reifier = node(
            ["ReifiedRelation"],
            {
                "reifier_id": "workbench__" + _sha(_json([scope_id, relation["reifier_id"]])),
                "env_name": name,
                "scope_id": scope_id,
            },
            {
                "authored_reifier_id": relation["reifier_id"],
                "relation_type": relation["relation_type"],
                "spec_json": _json(relation),
                "authored": True,
            },
        )
        reifier_mapping[relation["reifier_id"]] = reifier
        edge(root, reifier, "HAS_REIFIER")
        edge(reifier, mapping[relation["source_id"]], "REIFIES_SUBJECT")
        edge(reifier, mapping[relation["target_id"]], "REIFIES_OBJECT")
    result = dict(
        format="arena.workbench.scene-projection.v1",
        scope=scope,
        scope_id=scope_id,
        canonical_identity={"name": name, "sha256": compact_hash},
        hashes={
            "workbench": {
                "sha256": _sha(json.dumps(data, sort_keys=True, allow_nan=False)),
                "separators": [", ", ": "],
                "ensure_ascii": True,
                "algorithm": "sha256",
            },
            "dcrg": {"sha256": compact_hash, "separators": [",", ":"], "ensure_ascii": True, "algorithm": "sha256"},
        },
        dcrg_mapping={"status": "supported" if supported else "unsupported", "targets": targets},
        asset_mapping=mapping,
        reifier_mapping=reifier_mapping,
        retrieval_limitations=(
            "Generic retrieval is NOT deduplicated. Select one authorized store/revision membership "
            "per canonical full digest before joining assets; otherwise multiple revisions multiply rows. "
            "DCRG support reifiers/assets are separate from authored revision records. Existing DCRG "
            "ReifiedRelation uniqueness (reifier_id, env_name) is respected by scoped physical reifier IDs. "
            "Legacy aliases require verified source canonical JSON/full "
            "digest proof, never family/name similarity; keep unproven legacy roots distinct. Preserve "
            "evaluation run identity and require actual evidence gates; do not set converged. Camera "
            "configuration is retained as authored params_json: there is no typed camera schema."
        ),
        nodes=sorted(nodes, key=lambda n: n["id"]),
        edges=sorted(edges, key=lambda e: e["id"]),
    )
    result = _seal(result)
    _encoded_bound(result, MAX_PROJECTION_BYTES)
    return result


def validate_projection(projection: dict, *, spec: ArenaEnvGraphSpec) -> None:
    """Validate every record against the caller's authoritative immutable specification.

    The source spec is required deliberately: self-consistent copied/recomputed hashes
    cannot certify the intended scene. Scope authorization remains the caller's job.
    """
    try:
        _bounded(projection)
        _encoded_bound(projection, MAX_PROJECTION_BYTES)
        scope = projection["scope"]
        expected = project_scene(spec, **{key: scope[key] for key in ("revision_id", "store_id", "family", "version")})
        if _json(projection) != _json(expected):
            raise ValueError("Projection differs from authoritative scene/identity/records")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Malformed projection") from error


def compare_readback(projection: dict, nodes: list, edges: list, *, spec: ArenaEnvGraphSpec) -> None:
    """Compare exact owned readback records, not reported counts or copied digests.

    Args:
        projection: Expected immutable projection, verified against spec first.
        nodes: Actual node envelopes, with labels/keys/properties read from Neo4j.
        edges: Actual edge envelopes, with actual endpoint identities and properties.
        spec: Authoritative source; never reconstructed from untrusted readback.

    Read the canonical root plus all nodes/edges in scope, including unexpected
    records; fetching only expected IDs cannot detect extras. Do not replace actual
    properties/endpoints with expected values when adapting driver records. Envelope
    IDs/digests must be computed from those actual records. Unrelated pre-existing
    root metadata is checked separately by check_root_compatibility, then projected
    to the owned canonical fields; never discard extra revision-node properties.
    """
    validate_projection(projection, spec=spec)
    try:
        _bounded([nodes, edges])
        _encoded_bound([nodes, edges], MAX_PROJECTION_BYTES)
        for kind, records in (("nodes", nodes), ("edges", edges)):
            if not isinstance(records, list):
                raise ValueError("Readback must be bounded lists")
            ids = [record["id"] for record in records]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate readback identity")
            if _json(sorted(records, key=lambda r: r["id"])) != _json(projection[kind]):
                raise ValueError(f"Exact {kind} readback mismatch (identity/properties/digest/endpoints)")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Malformed readback") from error


def check_root_compatibility(projection: dict, rows: list[dict]) -> None:
    """Reject duplicate roots or canonical short-name/full-digest/payload conflicts.

    Empty rows permit creation. Matching existing roots may retain unrelated fields;
    this check never mutates their canonical payload or infers legacy equivalence.
    The writer must invoke this inside its explicit transaction, after validating
    the projection against the authoritative source.
    """
    bounded_neo4j_value(rows)
    if not isinstance(rows, list) or len(rows) > 1:
        raise ValueError("Duplicate canonical root")
    if not rows:
        return
    root = next(n["properties"] for n in projection["nodes"] if n["labels"] == ["EnvironmentGraph"])
    if not isinstance(rows[0], dict):
        raise ValueError("Malformed canonical root")
    _bounded({k: rows[0].get(k) for k in root})
    if any(_json(rows[0].get(k)) != _json(v) for k, v in root.items()):
        raise ValueError("Canonical root collision or payload conflict")
    if _sha(rows[0]["spec_json"]) != rows[0]["spec_sha256"]:
        raise ValueError("Canonical root payload digest conflict")
