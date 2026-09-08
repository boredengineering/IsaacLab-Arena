# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Immutable DCRG registration; caller supplies the driver and actual evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def graph_identity(spec: ArenaEnvGraphSpec, *, target_object_id: str) -> dict[str, str]:
    """Return source-preserving canonical spec identity and the target support reifier."""
    support = _support(spec, target_object_id)
    digest = hashlib.sha256(_json(spec.to_dict()).encode()).hexdigest()
    return {
        "env_name": f"{spec.env_name}__{digest[:16]}",
        "version": digest,
        "reifier_id": support["reifier_id"],
    }


def _support(spec, target_object_id):
    tasks = [task for task in spec.task.subtasks if task.params.get("pick_up_object") == target_object_id]
    if not tasks:
        raise ValueError("Target must be an explicit task pick_up_object")
    assets = {
        asset.id
        for asset in [
            spec.embodiment,
            spec.background,
            *spec.objects,
            *(spec.object_references or []),
        ]
    }
    explicit = [
        relation
        for relation in spec.reified_relations or []
        if (relation.source_id == target_object_id and relation.relation_type in ("PLACED_ON", "ON", "on"))
        or relation.reifier_id == f"support_{target_object_id}"
    ]
    if len(explicit) > 1:
        raise ValueError("Ambiguous target support reifier")
    if explicit:
        relation = explicit[0]
        if relation.source_id != target_object_id or relation.relation_type not in (
            "PLACED_ON",
            "ON",
            "on",
        ):
            raise ValueError("Explicit target support reifier has conflicting semantics")
        payload = relation.model_dump(mode="json", exclude_none=True)
        properties = {key: value for key, value in payload.items() if not isinstance(value, dict)}
        for axis in ("x", "y", "z"):
            interval = payload[f"delta_{axis}"]
            for key, suffix in (
                ("min_val", "min"),
                ("max_val", "max"),
                ("nominal", "nominal"),
            ):
                properties[f"delta_{axis}_{suffix}"] = interval[key]
        properties["inferred_from_task"] = False
    else:
        if any(task.params.get("background_scene") != spec.background.id for task in tasks):
            raise ValueError("Support inference requires explicit task background_scene")
        properties = {
            "reifier_id": f"support_{target_object_id}",
            "relation_type": "PLACED_ON",
            "source_id": target_object_id,
            "target_id": spec.background.id,
            "inferred_from_task": True,
            "evidence_sources": ["inferred_from_task"],
        }
        payload = dict(properties)
    if properties["source_id"] not in assets or properties["target_id"] not in assets:
        raise ValueError("Unknown support endpoint")
    if properties["source_id"] == properties["target_id"]:
        raise ValueError("Support endpoints must be distinct")
    return {**properties, "spec_json": _json(payload)}


_KEYS = {
    "EnvironmentGraph": ("name",),
    "DCRGAsset": ("id", "env_name"),
    "ReifiedRelation": ("reifier_id", "env_name"),
    "EvaluationRun": ("id",),
    "Policy": ("name",),
    "DCRGProposal": ("id",),
    "DCRGProposalDecision": ("id",),
    "DCRGControllerVariant": ("id",),
    "DCRGControllerTrial": ("id",),
    "DCRGControllerExperiment": ("id",),
}


def _ensure_schema(driver):
    # Schema DDL cannot share a Neo4j data transaction. Uniqueness must exist before
    # MERGE: otherwise concurrent registrations can silently create duplicate identities.
    with driver.session() as session:
        for label, fields in _KEYS.items():
            columns = ", ".join(f"n.{field}" for field in fields)
            session.run(
                f"CREATE CONSTRAINT dcrg_{label}_identity IF NOT EXISTS FOR (n:{label}) REQUIRE ({columns}) IS UNIQUE"
            ).consume()
        constraints = list(session.run("SHOW CONSTRAINTS YIELD type, labelsOrTypes, properties RETURN *"))
        for label, fields in _KEYS.items():
            if not any(
                row["type"] == "UNIQUENESS" and row["labelsOrTypes"] == [label] and row["properties"] == list(fields)
                for row in constraints
            ):
                raise RuntimeError(f"Missing verified uniqueness constraint for {label}")


def _pattern(alias, label, key, parameter):
    assert label in _KEYS, "Internal node label must be fixed"
    assert set(key) == set(_KEYS[label]), "Internal identity fields must be fixed"
    fields = ", ".join(f"{field}: ${parameter}.{field}" for field in key)
    return f"({alias}:{label} {{{fields}}})"


def _verified(rows, expected, description):
    if len(rows) != 1 or any(_json(rows[0]["properties"].get(key)) != _json(value) for key, value in expected.items()):
        raise ValueError(f"Immutable {description} conflict or missing exact read-back")
    return dict(rows[0]["properties"])


def _node(tx, label, key, properties=None):
    pattern = _pattern("n", label, key, "key")
    if properties is not None:
        tx.run(
            f"MERGE {pattern} ON CREATE SET n += $properties",
            key=key,
            properties=properties,
        ).consume()
    rows = list(tx.run(f"MATCH {pattern} RETURN properties(n) AS properties", key=key))
    return _verified(rows, {**key, **(properties or {})}, label)


def _edge(tx, source, target, relation, properties=None, *, key=None):
    assert relation in {
        "HAS_REIFIER",
        "REIFIES_SUBJECT",
        "REIFIES_OBJECT",
        "EVALUATED_GRAPH",
        "USED_POLICY",
        "EVOLVES_TO",
        "PROPOSES_RELAXATION",
        "PARENT_GRAPH",
        "CHILD_GRAPH",
        "PARENT_REIFIER",
        "GENERATED_PROPOSAL",
        "HAS_DECISION",
        "BASED_ON_EVALUATION",
        "TRIAL_CONTROLLER",
        "IN_CONTROLLER_EXPERIMENT",
    }, "Internal relationship must be fixed"
    key = key or {}
    assert not key or set(key) == {"proposal_id"}, "Unexpected relationship key"
    match = f"MATCH {_pattern('s', *source, 'source')}, {_pattern('t', *target, 'target')} "
    fields = " {proposal_id: $key.proposal_id}" if key else ""
    pattern = f"(s)-[r:{relation}{fields}]->(t)"
    params = {"source": source[1], "target": target[1], "key": key}
    if properties is not None:
        tx.run(
            match + f"MERGE {pattern} ON CREATE SET r += $properties",
            **params,
            properties=properties,
        ).consume()
    rows = list(
        tx.run(
            match
            + f"MATCH {pattern} RETURN properties(r) AS properties, "
            f"size([(s)-[:{relation}]->() | 1]) AS outgoing_count",
            **params,
        )
    )
    if relation in {
        "REIFIES_SUBJECT",
        "REIFIES_OBJECT",
        "EVALUATED_GRAPH",
        "USED_POLICY",
        "PARENT_GRAPH",
        "CHILD_GRAPH",
        "PARENT_REIFIER",
        "HAS_DECISION",
        "BASED_ON_EVALUATION",
        "TRIAL_CONTROLLER",
        "IN_CONTROLLER_EXPERIMENT",
    } and (len(rows) != 1 or rows[0]["outgoing_count"] != 1):
        raise ValueError(f"Immutable {relation} target cardinality conflict")
    return _verified(rows, {**key, **(properties or {})}, relation)


def register_environment_version(spec: ArenaEnvGraphSpec, *, target_object_id: str, driver) -> dict[str, str]:
    """Register immutable source JSON and one inferred support relation, with exact read-back.

    Args:
        spec: Validated source spec; never renamed or mutated.
        target_object_id: The pick-up object whose support relation receives feedback.
        driver: Caller-owned Neo4j driver with schema privileges. Unique constraints are
            installed and verified separately before the single atomic data transaction.

    Returns:
        env_name, full SHA-256 version, and reifier_id for the recurrent feedback API.
    """
    identity = graph_identity(spec, target_object_id=target_object_id)
    payload = _json(spec.to_dict())
    support = _support(spec, target_object_id)
    assets = {
        asset.id: asset
        for asset in [
            spec.embodiment,
            spec.background,
            *spec.objects,
            *(spec.object_references or []),
        ]
    }
    name = identity["env_name"]
    root = ("EnvironmentGraph", {"name": name})
    reifier = (
        "ReifiedRelation",
        {"reifier_id": identity["reifier_id"], "env_name": name},
    )
    source = ("DCRGAsset", {"id": target_object_id, "env_name": name})
    target = ("DCRGAsset", {"id": support["target_id"], "env_name": name})

    def write(tx):
        _node(
            tx,
            *root,
            {
                "version": identity["version"],
                "spec_sha256": identity["version"],
                "spec_json": payload,
                "source_env_name": spec.env_name,
            },
        )
        for endpoint in (source, target):
            asset = assets[endpoint[1]["id"]]
            _node(
                tx,
                *endpoint,
                {"spec_json": _json(asset.model_dump(mode="json", exclude_none=True))},
            )
        _node(tx, *reifier, support)
        for left, right, relation in (
            (root, reifier, "HAS_REIFIER"),
            (reifier, source, "REIFIES_SUBJECT"),
            (reifier, target, "REIFIES_OBJECT"),
        ):
            _edge(tx, left, right, relation, {})
        return identity

    _ensure_schema(driver)
    with driver.session() as session:
        return session.execute_write(write)


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Explicit {field} is required")


def _graph_key(env_name, version):
    _text(env_name, "env_name")
    if not isinstance(version, str) or re.fullmatch(r"[0-9a-f]{64}", version) is None:
        raise ValueError("version must be a full lowercase SHA-256")
    return "EnvironmentGraph", {"name": env_name}


def _registered_graph(tx, env_name, version):
    target = _graph_key(env_name, version)
    props = _node(tx, *target)
    payload = props.get("spec_json")
    if (
        props.get("version") != version
        or props.get("spec_sha256") != version
        or not isinstance(payload, str)
        or hashlib.sha256(payload.encode()).hexdigest() != version
        or env_name != f"{props.get('source_env_name')}__{version[:16]}"
    ):
        raise ValueError("Immutable graph version/hash/payload conflict")
    return target


def _episode_metrics(episode_results):
    if not isinstance(episode_results, (list, tuple)) or not episode_results:
        raise ValueError("Nonempty completed episode_results are required")
    seen = set()
    for row in episode_results:
        if not isinstance(row, dict):
            raise ValueError("Episode evidence must contain raw record objects")
        key = tuple(row.get(field) for field in ("seed", "env_id", "episode_in_env"))
        if any(type(value) is not int or value < 0 for value in key):
            raise ValueError("Episode seed/environment/index must be explicit nonnegative integers")
        if key in seen or row.get("completed", True) is not True or type(row.get("success")) is not bool:
            raise ValueError("Duplicate, unfinished or unscored episode evidence")
        seen.add(key)
    count = len(episode_results)
    successes = sum(row["success"] for row in episode_results)
    return {
        "num_episodes": count,
        "num_successes": successes,
        "success_rate": successes / count,
        "seeds": sorted({key[0] for key in seen}),
        "episode_results_json": _json(episode_results),
    }


def _artifact_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def register_evaluation_run(
    *,
    env_name: str,
    version: str,
    run_id: str,
    policy_identity: str,
    episode_results: list[dict],
    artifact_paths: list[str | Path],
    driver,
) -> dict:
    """Register actual completed episode records, deriving counts without success proxies.

    Args:
        env_name: Exact registered graph name.
        version: Exact full canonical spec SHA-256.
        run_id: Explicit stable evaluation identity (EvaluationRun.id).
        policy_identity: Exact frozen policy/checkpoint identity (Policy.name).
        episode_results: Finished-recorder rows with seed, env_id, episode_in_env and
            boolean success. An explicit completed=False is rejected. Raw JSON is retained;
            the caller must bind these records and artifacts to the actual run, not synthesize them.
        artifact_paths: Existing source evidence files; absolute paths and byte hashes are retained.
        driver: Caller-owned Neo4j driver; never creates a connection or reads credentials.

    Returns:
        Verified evaluation identity and honest canonical counts.
    """
    _graph_key(env_name, version)
    _text(run_id, "run_id")
    _text(policy_identity, "policy_identity")
    metrics = _episode_metrics(episode_results)
    identity = {
        "run_id": run_id,
        "eval_id": run_id,
        "env_name": env_name,
        "env_version": version,
        "policy_identity": policy_identity,
    }
    if any(field in row and row[field] != value for row in episode_results for field, value in identity.items()):
        raise ValueError("Episode record identity conflicts with evaluation registration")
    if not artifact_paths:
        raise ValueError("Source artifact paths are required")
    paths = sorted({str(Path(path).resolve()) for path in artifact_paths})
    hashes = [_artifact_digest(path) for path in paths]
    properties = {
        "env_name": env_name,
        "env_version": version,
        "policy_identity": policy_identity,
        **metrics,
        "artifact_paths": paths,
        "artifact_sha256": hashes,
    }
    evaluation = ("EvaluationRun", {"id": run_id})
    policy = ("Policy", {"name": policy_identity})

    def write(tx):
        graph = _registered_graph(tx, env_name, version)
        _node(tx, *evaluation, properties)
        _node(tx, *policy, {"identity": policy_identity})
        _edge(tx, evaluation, graph, "EVALUATED_GRAPH", {})
        _edge(tx, evaluation, policy, "USED_POLICY", {})
        return {"eval_id": run_id, **properties, "verified": True}

    _ensure_schema(driver)
    with driver.session() as session:
        return session.execute_write(write)


def _registered_evaluation(tx, run_id, graph, version):
    evaluation = ("EvaluationRun", {"id": run_id})
    props = _node(tx, *evaluation)
    if props.get("env_name") != graph[1]["name"] or props.get("env_version") != version:
        raise ValueError("Evaluation graph/version conflict")
    metrics = _episode_metrics(json.loads(props.get("episode_results_json", "null")))
    _verified([{"properties": props}], metrics, "evaluation metrics")
    policy_identity = props.get("policy_identity")
    _text(policy_identity, "stored policy_identity")
    policy = ("Policy", {"name": policy_identity})
    _node(tx, *policy)
    _edge(tx, evaluation, graph, "EVALUATED_GRAPH")
    _edge(tx, evaluation, policy, "USED_POLICY")
    return evaluation, props


def register_proposal(
    *,
    proposal_id: str,
    parent_env_name: str,
    parent_version: str,
    parent_reifier_id: str,
    child_env_name: str,
    child_version: str,
    parent_eval_id: str,
    delta_xy: list[float],
    driver,
) -> dict:
    """Record a proposed world-XY relaxation without asserting feasibility or success.

    Args:
        proposal_id: Stable immutable proposal identity; retries cannot change its payload.
        parent_env_name: Exact registered parent graph.
        parent_version: Parent canonical SHA-256.
        parent_reifier_id: Exact parent support factor that motivated the proposal.
        child_env_name: Exact separately registered candidate graph.
        child_version: Candidate canonical SHA-256.
        parent_eval_id: Existing completed evaluation of the parent graph.
        delta_xy: Explicit finite world-frame displacement; validation/bounds belong to the loop.
        driver: Caller-owned driver; one data transaction after verified schema setup.

    Returns:
        Verified immutable proposal provenance, still with status proposed.
    """
    _graph_key(parent_env_name, parent_version)
    _graph_key(child_env_name, child_version)
    for field, value in {
        "proposal_id": proposal_id,
        "parent_reifier_id": parent_reifier_id,
        "parent_eval_id": parent_eval_id,
    }.items():
        _text(value, field)
    if parent_env_name == child_env_name or parent_version == child_version:
        raise ValueError("Proposal must identify a distinct child graph")
    if (
        not isinstance(delta_xy, (list, tuple))
        or len(delta_xy) != 2
        or any(type(value) not in (int, float) or not math.isfinite(value) for value in delta_xy)
    ):
        raise ValueError("delta_xy must contain exactly two finite numbers")
    properties = {
        "proposal_id": proposal_id,
        "parent_env_name": parent_env_name,
        "parent_version": parent_version,
        "parent_reifier_id": parent_reifier_id,
        "child_env_name": child_env_name,
        "child_version": child_version,
        "parent_eval_id": parent_eval_id,
        "delta_xy": list(delta_xy),
        "coordinate_frame": "world",
        "status": "proposed",
    }
    proposed = ("DCRGProposal", {"id": proposal_id})
    reifier = (
        "ReifiedRelation",
        {"env_name": parent_env_name, "reifier_id": parent_reifier_id},
    )

    def write(tx):
        parent = _registered_graph(tx, parent_env_name, parent_version)
        child = _registered_graph(tx, child_env_name, child_version)
        evaluation, _ = _registered_evaluation(tx, parent_eval_id, parent, parent_version)
        factor = _node(tx, *reifier)
        _edge(tx, parent, reifier, "HAS_REIFIER")
        for field, relation in (
            ("source_id", "REIFIES_SUBJECT"),
            ("target_id", "REIFIES_OBJECT"),
        ):
            endpoint = (
                "DCRGAsset",
                {"id": factor.get(field), "env_name": parent_env_name},
            )
            _node(tx, *endpoint)
            _edge(tx, reifier, endpoint, relation)
        _node(tx, *proposed, properties)
        for source, target, relation in (
            (proposed, parent, "PARENT_GRAPH"),
            (proposed, child, "CHILD_GRAPH"),
            (proposed, reifier, "PARENT_REIFIER"),
            (evaluation, proposed, "GENERATED_PROPOSAL"),
        ):
            _edge(tx, source, target, relation, {})
        _edge(
            tx,
            parent,
            child,
            "EVOLVES_TO",
            properties,
            key={"proposal_id": proposal_id},
        )
        _edge(
            tx,
            reifier,
            child,
            "PROPOSES_RELAXATION",
            properties,
            key={"proposal_id": proposal_id},
        )
        return {**properties, "verified": True}

    _ensure_schema(driver)
    with driver.session() as session:
        return session.execute_write(write)


def record_proposal_decision(
    *,
    proposal_id: str,
    status: str,
    reason: str,
    evaluation_run_id: str,
    driver,
) -> dict:
    """Append one immutable trial decision, leaving the original proposal untouched.

    Args:
        proposal_id: Exact previously registered proposal.
        status: accepted or rejected, never success; the caller owns the comparison rule.
        reason: Explicit explanation of the trial comparison.
        evaluation_run_id: Completed evaluation of the candidate with the same policy as its parent.
        driver: Caller-owned Neo4j driver.

    Returns:
        Verified separate decision record; acceptance is not a robustness claim.
    """
    for field, value in {
        "proposal_id": proposal_id,
        "reason": reason,
        "evaluation_run_id": evaluation_run_id,
    }.items():
        _text(value, field)
    if status not in ("accepted", "rejected"):
        raise ValueError("Decision status must be accepted or rejected")
    properties = {
        "proposal_id": proposal_id,
        "status": status,
        "reason": reason,
        "evaluation_run_id": evaluation_run_id,
    }
    proposed = ("DCRGProposal", {"id": proposal_id})
    decision = ("DCRGProposalDecision", {"id": proposal_id})

    def write(tx):
        provenance = _node(tx, *proposed)
        parent = _registered_graph(tx, provenance["parent_env_name"], provenance["parent_version"])
        child = _registered_graph(tx, provenance["child_env_name"], provenance["child_version"])
        parent_eval, parent_props = _registered_evaluation(
            tx, provenance["parent_eval_id"], parent, provenance["parent_version"]
        )
        child_eval, child_props = _registered_evaluation(tx, evaluation_run_id, child, provenance["child_version"])
        if parent_props["policy_identity"] != child_props["policy_identity"]:
            raise ValueError("Decision child/parent policy identity conflict")
        _edge(tx, proposed, parent, "PARENT_GRAPH")
        _edge(tx, proposed, child, "CHILD_GRAPH")
        _edge(tx, parent_eval, proposed, "GENERATED_PROPOSAL")
        _node(tx, *decision, properties)
        _edge(tx, proposed, decision, "HAS_DECISION", {})
        _edge(tx, decision, child_eval, "BASED_ON_EVALUATION", {})
        return {**properties, "verified": True}

    _ensure_schema(driver)
    with driver.session() as session:
        return session.execute_write(write)
