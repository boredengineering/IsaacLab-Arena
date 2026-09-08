# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Labeled Property Graph (LPG) synchronizer for IsaacLab-Arena environments using Neo4j and Cypher."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import neo4j

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec


def get_neo4j_driver(
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> neo4j.Driver:
    """Creates a Neo4j driver using environment variables or provided credentials.

    The default targets a Bolt endpoint on the local host. Set ``NEO4J_URI`` whenever the
    database is not there -- notably when it is published on a non-default port, or reached by
    its Docker bridge address. A bridge IP is assigned in start order and changes when
    containers are recreated, so it is never a safe default.

    Args:
        uri: Bolt URI; falls back to ``NEO4J_URI``, then to the local default.
        user: Username; falls back to ``NEO4J_USER``.
        password: Password; falls back to ``NEO4J_PASSWORD``.
    """
    # Imported here rather than at module scope so that every caller of this module stays
    # importable without the driver installed. Environments that only run simulation do not
    # ship it, and a hard top-level import made them fail at collection time.
    import neo4j

    uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7688")
    user = user or os.environ.get("NEO4J_USER", "neo4j")
    password = password or os.environ.get("NEO4J_PASSWORD", "isaaclab_arena_password")
    return neo4j.GraphDatabase.driver(uri, auth=(user, password))


def sync_spec_to_neo4j(
    spec: ArenaEnvGraphSpec,
    driver: neo4j.Driver | None = None,
    telemetry: Any | None = None,
    parent_env_name: str | None = None,
    derivation_feedback: str | None = None,
) -> dict[str, Any]:
    """Synchronizes an ArenaEnvGraphSpec into Neo4j as a Labeled Property Graph (LPG).

    Args:
        spec: The arena environment graph specification.
        driver: Optional active Neo4j driver.
        telemetry: Optional ActiveInferenceTelemetry metadata.
        parent_env_name: Optional name of the parent EnvironmentGraph this was derived from.
        derivation_feedback: User critique or feedback that guided the derivation.

    Returns:
        A dictionary containing summary counts of synced nodes and edges.
    """
    owns_driver = False
    if driver is None:
        driver = get_neo4j_driver()
        owns_driver = True

    try:
        with driver.session() as session:
            # 1. Merge Environment Graph Root Node
            llm_calls = getattr(telemetry, "total_llm_calls", 0) if telemetry else 0
            repair_iters = getattr(telemetry, "repair_iterations", 0) if telemetry else 0
            total_toks = getattr(telemetry, "total_tokens", 0) if telemetry else 0
            prompt_toks = getattr(telemetry, "prompt_tokens", 0) if telemetry else 0
            comp_toks = getattr(telemetry, "completion_tokens", 0) if telemetry else 0
            gen_time_s = getattr(telemetry, "duration_s", 0.0) if telemetry else 0.0
            model_name = getattr(telemetry, "model", "") if telemetry else ""
            is_converged = getattr(telemetry, "converged", True) if telemetry else True

            session.run(
                """
                MERGE (e:EnvironmentGraph {name: $name})
                SET e.task_composition = $task_comp,
                    e.task_description = $task_desc,
                    e.llm_call_count = $llm_calls,
                    e.repair_iterations = $repair_iters,
                    e.total_tokens = $total_toks,
                    e.prompt_tokens = $prompt_toks,
                    e.completion_tokens = $comp_toks,
                    e.generation_time_s = $gen_time_s,
                    e.model_used = $model_name,
                    e.converged = $is_converged,
                    e.updated_at = datetime()
                """,
                name=spec.env_name,
                task_comp=spec.task.composition if spec.task else "atomic",
                task_desc=spec.task.description if spec.task else "",
                llm_calls=llm_calls,
                repair_iters=repair_iters,
                total_toks=total_toks,
                prompt_toks=prompt_toks,
                comp_toks=comp_toks,
                gen_time_s=gen_time_s,
                model_name=model_name,
                is_converged=is_converged,
            )

            # Record derivation provenance if derived from a parent environment graph
            if parent_env_name and parent_env_name != spec.env_name:
                session.run(
                    """
                    MERGE (parent:EnvironmentGraph {name: $parent_name})
                    WITH parent
                    MATCH (child:EnvironmentGraph {name: $child_name})
                    MERGE (child)-[r:WAS_DERIVED_FROM]->(parent)
                    SET r.feedback = $feedback,
                        r.timestamp = datetime()
                    """,
                    parent_name=parent_env_name,
                    child_name=spec.env_name,
                    feedback=derivation_feedback or "",
                )

            # 2. Merge Embodiment Node
            if spec.embodiment:
                session.run(
                    """
                    MATCH (e:EnvironmentGraph {name: $env_name})
                    MERGE (emb:Embodiment {id: $id, env_name: $env_name})
                    SET emb.registry_name = $registry_name,
                        emb.params = $params
                    MERGE (e)-[:HAS_EMBODIMENT]->(emb)
                    """,
                    env_name=spec.env_name,
                    id=spec.embodiment.id,
                    registry_name=spec.embodiment.registry_name,
                    params=str(spec.embodiment.params),
                )

            # 3. Merge Background / Terrain Fixture
            if spec.background:
                session.run(
                    """
                    MATCH (e:EnvironmentGraph {name: $env_name})
                    MERGE (bg:Fixture:Terrain {id: $id, env_name: $env_name})
                    SET bg.registry_name = $registry_name,
                        bg.is_terrain = true,
                        bg.params = $params
                    MERGE (e)-[:HAS_TERRAIN]->(bg)
                    """,
                    env_name=spec.env_name,
                    id=spec.background.id,
                    registry_name=spec.background.registry_name,
                    params=str(spec.background.params),
                )

            # 4. Merge Objects & Furniture
            for obj in spec.objects:
                label = (
                    "Fixture:Furniture"
                    if "table" in obj.registry_name or "shelf" in obj.registry_name or "rack" in obj.registry_name
                    else ("RigidObject:Receptacle" if "bin" in obj.registry_name else "RigidObject")
                )
                session.run(
                    f"""
                    MATCH (e:EnvironmentGraph {{name: $env_name}})
                    MERGE (o:{label} {{id: $id, env_name: $env_name}})
                    SET o.registry_name = $registry_name,
                        o.params = $params
                    MERGE (e)-[:CONTAINS_OBJECT]->(o)
                    """,
                    env_name=spec.env_name,
                    id=obj.id,
                    registry_name=obj.registry_name,
                    params=str(obj.params),
                )

            # 4b. Merge Introspected USD Prims (Dollhouse Sub-Prims)
            if spec.object_references:
                for ref in spec.object_references:
                    session.run(
                        """
                        MATCH (e:EnvironmentGraph {name: $env_name})
                        MERGE (p:USDPrim {id: $id, env_name: $env_name})
                        SET p.prim_path = $prim_path,
                            p.object_type = $object_type,
                            p.parent_id = $parent_id
                        MERGE (e)-[:CONTAINS_PRIM]->(p)
                        """,
                        env_name=spec.env_name,
                        id=ref.id,
                        prim_path=ref.prim_path or "",
                        object_type=str(ref.object_type),
                        parent_id=ref.parent_id or "",
                    )

            # 5. Merge Relations with Rich Properties (LPG Edges)
            primary_furniture_id = None
            for rel in spec.relations:
                rel_kind = rel.kind.upper()
                if rel_kind == "ON":
                    rel_type = "PLACED_ON"
                elif rel_kind == "INSIDE":
                    rel_type = "PLACED_INSIDE"
                elif rel_kind == "NAV_CORRIDOR":
                    rel_type = "NAV_CORRIDOR_TO"
                elif rel_kind == "STANDS_NEAR":
                    rel_type = "STANDS_NEAR"
                else:
                    rel_type = rel_kind.replace(" ", "_")

                if rel.reference:
                    session.run(
                        f"""
                        MATCH (s {{id: $subject, env_name: $env_name}}),
                              (r {{id: $reference, env_name: $env_name}})
                        MERGE (s)-[rel:{rel_type}]->(r)
                        SET rel.surface_anchor = $surface_anchor,
                            rel.nominal_height = $nominal_height,
                            rel.bound_x = $bound_x,
                            rel.bound_y = $bound_y,
                            rel.clearance = $clearance,
                            rel.raw_params = $params
                        """,
                        env_name=spec.env_name,
                        subject=rel.subject,
                        reference=rel.reference,
                        surface_anchor=rel.params.get("surface_anchor", ""),
                        nominal_height=float(rel.params.get("nominal_height", 0.0)),
                        bound_x=rel.params.get("bound_x", []),
                        bound_y=rel.params.get("bound_y", []),
                        clearance=float(rel.params.get("clearance", 0.05)),
                        params=str(rel.params),
                    )

                    # If sub-surface tier anchor specified, materialize SurfaceAnchor node
                    if "surface_anchor" in rel.params:
                        anchor_name = str(rel.params["surface_anchor"])
                        session.run(
                            """
                            MATCH (r {id: $reference, env_name: $env_name}),
                                  (s {id: $subject, env_name: $env_name})
                            MERGE (sa:SurfaceAnchor {id: $anchor_id, env_name: $env_name})
                            SET sa.anchor_name = $anchor_name,
                                sa.nominal_height = $nominal_height
                            MERGE (r)-[:HAS_SUB_SURFACE]->(sa)
                            MERGE (s)-[:PLACED_ON_SUB_SURFACE]->(sa)
                            """,
                            env_name=spec.env_name,
                            reference=rel.reference,
                            subject=rel.subject,
                            anchor_id=f"{rel.reference}_{anchor_name}",
                            anchor_name=anchor_name,
                            nominal_height=float(rel.params.get("nominal_height", 0.0)),
                        )
                        primary_furniture_id = rel.reference

            # 5b. Merge RDF 1.2 Reified Relation Factor Nodes
            if spec.reified_relations:
                for reif in spec.reified_relations:
                    session.run(
                        """
                        MATCH (e:EnvironmentGraph {name: $env_name}),
                              (s {id: $source_id, env_name: $env_name}),
                              (t {id: $target_id, env_name: $env_name})
                        MERGE (rf:ReifiedRelation {reifier_id: $reifier_id, env_name: $env_name})
                        SET rf.relation_type = $relation_type,
                            rf.surface_anchor = $surface_anchor,
                            rf.contact_normal = $contact_normal,
                            rf.delta_x_min = $dx_min,
                            rf.delta_x_max = $dx_max,
                            rf.delta_y_min = $dy_min,
                            rf.delta_y_max = $dy_max,
                            rf.delta_z_nominal = $dz_nom,
                            rf.required_headroom = $headroom,
                            rf.required_friction = $friction,
                            rf.kinematic_manifold = $manifold,
                            rf.prior_entropy = $prior_e,
                            rf.posterior_entropy = $post_e,
                            rf.evidence_sources = $evidence
                        MERGE (e)-[:HAS_REIFIER]->(rf)
                        MERGE (rf)-[:REIFIES_SUBJECT]->(s)
                        MERGE (rf)-[:REIFIES_OBJECT]->(t)
                        """,
                        env_name=spec.env_name,
                        reifier_id=reif.reifier_id,
                        relation_type=reif.relation_type,
                        source_id=reif.source_id,
                        target_id=reif.target_id,
                        surface_anchor=reif.surface_anchor or "",
                        contact_normal=list(reif.contact_normal),
                        dx_min=float(reif.delta_x.min_val),
                        dx_max=float(reif.delta_x.max_val),
                        dy_min=float(reif.delta_y.min_val),
                        dy_max=float(reif.delta_y.max_val),
                        dz_nom=float(reif.delta_z.nominal),
                        headroom=float(reif.required_headroom),
                        friction=float(reif.required_friction),
                        manifold=reif.kinematic_manifold,
                        prior_e=float(reif.prior_entropy),
                        post_e=float(reif.posterior_entropy),
                        evidence=reif.evidence_sources,
                    )

            # 6. Merge Robot Affordance Standoff Link
            if spec.embodiment:
                target_fid = primary_furniture_id or (spec.objects[0].id if spec.objects else None)
                if target_fid:
                    session.run(
                        """
                        MATCH (emb:Embodiment {id: $emb_id, env_name: $env_name}),
                              (furn {id: $furn_id, env_name: $env_name})
                        MERGE (emb)-[a:STANDS_AT_AFFORDANCE]->(furn)
                        SET a.standoff_distance = 0.85,
                            a.relative_heading = 'front_facing'
                        """,
                        env_name=spec.env_name,
                        emb_id=spec.embodiment.id,
                        furn_id=target_fid,
                    )

            # 7. Merge Camera Viewport Grounding
            cam_target_id = spec.objects[0].id if spec.objects else (spec.background.id if spec.background else None)
            if cam_target_id:
                session.run(
                    """
                    MATCH (e:EnvironmentGraph {name: $env_name}),
                          (target {id: $target_id, env_name: $env_name})
                    MERGE (cam:Camera {id: $cam_id, env_name: $env_name})
                    SET cam.fov = 65.0,
                        cam.eye_offset = [-1.5, -1.5, 1.5]
                    MERGE (e)-[:HAS_CAMERA]->(cam)
                    MERGE (cam)-[:OBSERVES_INTERACTION_ZONE]->(target)
                    """,
                    env_name=spec.env_name,
                    cam_id=f"{spec.env_name}_viewer_cam",
                    target_id=cam_target_id,
                )

            # Summary verification
            result = session.run(
                """
                MATCH (e:EnvironmentGraph {name: $env_name})
                OPTIONAL MATCH (e)-[rel]->(n)
                OPTIONAL MATCH (n)-[r]->(m)
                RETURN count(DISTINCT n) AS node_count, count(DISTINCT r) AS rel_count
                """,
                env_name=spec.env_name,
            ).single()

            return {
                "env_name": spec.env_name,
                "node_count": result["node_count"] if result else 0,
                "rel_count": result["rel_count"] if result else 0,
            }
    finally:
        if owns_driver:
            driver.close()


def query_reified_relations(
    env_name: str,
    driver: neo4j.Driver | None = None,
) -> list[dict[str, Any]]:
    """Queries all active reified relation factor nodes for an environment in Neo4j."""
    owns_driver = False
    if driver is None:
        driver = get_neo4j_driver()
        owns_driver = True

    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (e:EnvironmentGraph {name: $env_name})-[:HAS_REIFIER]->(rf:ReifiedRelation)
                MATCH (rf)-[:REIFIES_SUBJECT]->(s), (rf)-[:REIFIES_OBJECT]->(t)
                RETURN rf.reifier_id AS reifier_id,
                       rf.relation_type AS relation_type,
                       s.id AS source_id,
                       t.id AS target_id,
                       rf.surface_anchor AS surface_anchor,
                       rf.required_headroom AS required_headroom,
                       rf.required_friction AS required_friction,
                       rf.kinematic_manifold AS kinematic_manifold,
                       rf.prior_entropy AS prior_entropy,
                       rf.posterior_entropy AS posterior_entropy
                """,
                env_name=env_name,
            )
            return [record.data() for record in result]
    finally:
        if owns_driver:
            driver.close()


def query_spatial_hierarchy(
    env_name: str,
    driver: neo4j.Driver | None = None,
) -> list[dict[str, Any]]:
    """Queries the hierarchical containment and placement chains in Neo4j."""
    owns_driver = False
    if driver is None:
        driver = get_neo4j_driver()
        owns_driver = True

    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (s)-[r]->(parent)
                WHERE s.env_name = $env_name AND parent.env_name = $env_name
                  AND type(r) IN ['PLACED_ON', 'PLACED_INSIDE', 'ATTACHED_TO_PRIM', 'HAS_SUB_SURFACE', 'PLACED_ON_SUB_SURFACE']
                RETURN s.id AS subject,
                       type(r) AS relation,
                       parent.id AS parent_id,
                       r.surface_anchor AS surface_anchor,
                       r.nominal_height AS nominal_height
                """,
                env_name=env_name,
            )
            return [record.data() for record in result]
    finally:
        if owns_driver:
            driver.close()


def sync_eval_telemetry_to_neo4j(
    ttl_path: str,
    driver: neo4j.Driver | None = None,
) -> dict[str, Any]:
    """Ingests a W3C PROV-O eval_telemetry.ttl file into Neo4j."""
    import rdflib
    from rdflib import RDF, Namespace

    ARENA = Namespace("https://isaac-sim.github.io/arena/schema#")
    PROV = Namespace("http://www.w3.org/ns/prov#")

    g = rdflib.Graph()
    g.parse(ttl_path, format="turtle")

    eval_runs = list(g.subjects(RDF.type, ARENA.EvaluationRun))
    if not eval_runs:
        eval_runs = list(g.subjects(RDF.type, PROV.Entity))

    eval_id = str(eval_runs[0]).split("/")[-1] if eval_runs else "eval_run_unknown"
    env_target = list(g.objects(eval_runs[0], ARENA.evaluatedGraph)) if eval_runs else []
    env_name = str(env_target[0]).split("/")[-1] if env_target else ""

    success_rate_val = list(g.objects(eval_runs[0], ARENA.metric_success_rate)) if eval_runs else []
    success_rate = float(success_rate_val[0]) if success_rate_val else 0.0

    num_episodes_val = list(g.objects(eval_runs[0], ARENA.metric_num_episodes)) if eval_runs else []
    # via float() so an xsd:float literal ("20.0") parses; int() alone raises on it.
    num_episodes = int(float(num_episodes_val[0])) if num_episodes_val else 0

    payload_val = list(g.objects(eval_runs[0], ARENA.metricsPayload)) if eval_runs else []
    metrics_payload = str(payload_val[0]) if payload_val else "{}"

    all_complete_val = list(g.objects(eval_runs[0], ARENA.metric_all_complete_rate)) if eval_runs else []
    all_complete_rate = float(all_complete_val[0]) if all_complete_val else None

    progress_score_val = list(g.objects(eval_runs[0], ARENA.metric_mean_progress_score)) if eval_runs else []
    mean_progress_score = float(progress_score_val[0]) if progress_score_val else None

    integrity_val = list(g.objects(eval_runs[0], ARENA.semanticIntegrityVerified)) if eval_runs else []
    semantic_integrity_verified = bool(integrity_val[0]) if integrity_val else True

    violation_val = list(g.objects(eval_runs[0], ARENA.integrityViolation)) if eval_runs else []
    integrity_violation = str(violation_val[0]) if violation_val else None

    blocking_val = list(g.objects(eval_runs[0], ARENA.blockingPredicate)) if eval_runs else []
    blocking_predicate = str(blocking_val[0]) if blocking_val else None

    activities = list(g.subjects(RDF.type, PROV.Activity))
    ended_at = ""
    policies = []
    if activities:
        ended_val = list(g.objects(activities[0], PROV.endedAtTime))
        ended_at = str(ended_val[0]) if ended_val else ""
        used_entities = list(g.objects(activities[0], PROV.used))
        for u in used_entities:
            u_str = str(u).split("/")[-1]
            if "policy" in u_str.lower():
                policies.append(u_str.replace("policy_", ""))

    policy_name = policies[0] if policies else "unknown_policy"

    owns_driver = False
    if driver is None:
        driver = get_neo4j_driver()
        owns_driver = True

    try:
        with driver.session() as session:
            session.run(
                """
                MERGE (ev:EvaluationRun {id: $eval_id})
                SET ev.success_rate = $success_rate,
                    ev.num_episodes = $num_episodes,
                    ev.all_complete_rate = $all_complete_rate,
                    ev.mean_progress_score = $mean_progress_score,
                    ev.semantic_integrity_verified = $semantic_integrity_verified,
                    ev.integrity_violation = $integrity_violation,
                    ev.blocking_predicate = $blocking_predicate,
                    ev.metrics_payload = $metrics_payload,
                    ev.ended_at = $ended_at
                WITH ev
                OPTIONAL MATCH (e:EnvironmentGraph {name: $env_name})
                FOREACH (_ IN CASE WHEN e IS NOT NULL THEN [1] ELSE [] END |
                    MERGE (ev)-[:EVALUATED_GRAPH]->(e)
                )
                FOREACH (_ IN CASE WHEN $semantic_integrity_verified = false THEN [1] ELSE [] END |
                    FOREACH (rf IN [(e)<-[:REIFIED_IN]-(r:ReifiedRelation) | r] |
                        MERGE (ev)-[f:FEEDBACK_MUTATION]->(rf)
                        SET f.defect_mode = "ProxyMetricDiscrepancy",
                            f.root_cause = $integrity_violation,
                            f.remediation = "Ground RL rewards and termination criteria to match physical predicates",
                            f.timestamp = datetime()
                    )
                )
                MERGE (p:Policy {name: $policy_name})
                MERGE (ev)-[:USED_POLICY]->(p)
                """,
                eval_id=eval_id,
                success_rate=success_rate,
                num_episodes=num_episodes,
                all_complete_rate=all_complete_rate,
                mean_progress_score=mean_progress_score,
                semantic_integrity_verified=semantic_integrity_verified,
                integrity_violation=integrity_violation,
                blocking_predicate=blocking_predicate,
                metrics_payload=metrics_payload,
                ended_at=ended_at,
                env_name=env_name,
                policy_name=policy_name,
            )
            return {
                "eval_id": eval_id,
                "env_name": env_name,
                "policy_name": policy_name,
                "success_rate": success_rate,
                "all_complete_rate": all_complete_rate,
                "semantic_integrity_verified": semantic_integrity_verified,
            }
    finally:
        if owns_driver:
            driver.close()


def _feedback_index(value: Any, field: str) -> int:
    """Validate an explicit nonnegative environment or episode index."""
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _feedback_number(value: Any) -> float | None:
    """Keep missing or nonfinite measurements unknown rather than imputing zero."""
    import math

    if type(value) not in (int, float):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except OverflowError:
        return None


def _feedback_samples(rows: list[dict[str, Any]], hand_body_name: str):
    """Yield validated environment/episode keys and numeric samples from fixed-body traces."""
    fields = ("hand_dist_to_obj", "hand_x_minus_obj", "hand_y_minus_obj", "hand_z_minus_obj", "lift", "contact_force")
    batch_width = None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Trace rows must be objects")
        if row.get("hand_body") != hand_body_name or row.get("hand_frame_mode") != "pinned":
            raise ValueError("Every trace row must name the same pinned hand body")
        batch = isinstance(row.get("episode"), list)
        indices = row["episode"] if batch else [row.get("episode")]
        if not indices:
            raise ValueError("Empty episode batch")
        if batch and "env_id" not in row:
            if batch_width is not None and batch_width != len(indices):
                raise ValueError("Implicit environment batch width changed")
            batch_width = len(indices)
        values = {}
        for field in ("env_id", *fields):
            value = row.get(field)
            if field == "env_id" and batch and field not in row:
                value = list(range(len(indices)))
            if batch:
                if value is None and field != "env_id":
                    value = [None] * len(indices)
                if not isinstance(value, list) or len(value) != len(indices):
                    raise ValueError(f"Invalid batch shape for {field}")
            else:
                if isinstance(value, list):
                    raise ValueError(f"Expected scalar {field}")
                value = [value]
            values[field] = value
        env_ids = [_feedback_index(v, "env_id") for v in values["env_id"]]
        if len(set(env_ids)) != len(env_ids):
            raise ValueError("Duplicate environment IDs in a batch")
        for index, episode in enumerate(indices):
            key = (env_ids[index], _feedback_index(episode, "episode"))
            yield key, {field: _feedback_number(values[field][index]) for field in fields}


def reduce_recurrent_feedback(
    rows: list[dict[str, Any]],
    episode_results: list[dict[str, Any]] | None = None,
    *,
    hand_body_name: str,
    lift_objective: str = "lift",
) -> dict[str, Any]:
    """Reduce fixed-body reach samples by environment and episode, without I/O.

    Args:
        rows: ReachTracer rows; batch positions are environment IDs unless env_id is supplied.
            Scalar rows must supply env_id. Arrays must have the same shape as episode.
        episode_results: Finished-episode recorder rows keyed by env_id and episode_in_env.
            When supplied, only those episodes contribute; otherwise canonical scores are unknown.
        hand_body_name: Required pinned link; residual components are in world coordinates.
        lift_objective: Objective whose recorded is_complete represents the sustained-lift gate.
            Caller must pin this to the task contract; neither height nor force defines completion.

    Returns:
        Episode-balanced residual means, counts and missingness, never zero-imputed evidence.
    """
    if not isinstance(hand_body_name, str) or not hand_body_name.strip():
        raise ValueError("A pinned hand_body_name is required")
    import statistics

    episodes: dict[tuple[int, int], dict[str, Any]] = {}
    fields = ("hand_dist_to_obj", "hand_x_minus_obj", "hand_y_minus_obj", "hand_z_minus_obj", "lift", "contact_force")
    for key, numbers in _feedback_samples(rows, hand_body_name):
        summary = episodes.setdefault(
            key,
            {
                "env_id": key[0],
                "episode": key[1],
                "distance": None,
                "dx": None,
                "dy": None,
                "dz": None,
                "sample_count": 0,
                "invalid_residual_samples": 0,
                "peak_excursion": None,
                "force_max": None,
                "missing_lift_samples": 0,
                "missing_force_samples": 0,
            },
        )
        summary["sample_count"] += 1
        distance = numbers["hand_dist_to_obj"]
        if distance is not None and distance >= 0 and all(numbers[field] is not None for field in fields[1:4]):
            if summary["distance"] is None or distance < summary["distance"]:
                summary["distance"] = distance
                for axis, field in zip(("dx", "dy", "dz"), fields[1:4]):
                    summary[axis] = numbers[field]
        else:
            summary["invalid_residual_samples"] += 1
        for field, output, missing in (
            ("lift", "peak_excursion", "missing_lift_samples"),
            ("contact_force", "force_max", "missing_force_samples"),
        ):
            number = numbers[field]
            if number is None or (field == "contact_force" and number < 0):
                summary[missing] += 1
            elif summary[output] is None or number > summary[output]:
                summary[output] = number
    completed = {}
    for record in episode_results or []:
        if not isinstance(record, dict):
            raise ValueError("Episode result rows must be objects")
        key = (
            _feedback_index(record.get("env_id"), "env_id"),
            _feedback_index(record.get("episode_in_env"), "episode_in_env"),
        )
        if key in completed or record.get("completed", True) is not True:
            raise ValueError("Duplicate or unfinished episode result")
        success = record.get("success")
        lift = record
        for field in ("progress", "objectives", lift_objective, "is_complete"):
            lift = lift.get(field) if isinstance(lift, dict) else None
        # Sequential pick-and-place records the sustained lift as a completed event,
        # not a standalone objective; whole-task completion is a different predicate.
        if lift is None:
            progress = record.get("progress")
            events = progress.get("events") if isinstance(progress, dict) else None
            if isinstance(events, list):
                lift = any(
                    isinstance(event, dict)
                    and isinstance(event.get("predicate_name"), str)
                    and event["predicate_name"].startswith("object_lifted_above_resting_min(")
                    for event in events
                )
        if any(value is not None and type(value) is not bool for value in (success, lift)):
            raise ValueError("Episode success and lift completion must be boolean or missing")
        completed[key] = {"success": success, "sustained_lift": lift, "seed": record.get("seed")}
    keys = sorted(completed if episode_results is not None else episodes)
    summaries = []
    for key in keys:
        summary = dict(
            episodes.get(
                key,
                {
                    "env_id": key[0],
                    "episode": key[1],
                    "distance": None,
                    "dx": None,
                    "dy": None,
                    "dz": None,
                    "sample_count": 0,
                    "invalid_residual_samples": 0,
                    "peak_excursion": None,
                    "force_max": None,
                    "missing_lift_samples": 0,
                    "missing_force_samples": 0,
                },
            )
        )
        summary.update(completed.get(key, {"success": None, "sustained_lift": None, "seed": None}))
        summary["completed"] = key in completed
        summaries.append(summary)
    valid = [r for r in summaries if r["distance"] is not None]
    forces = [r["force_max"] for r in summaries if r["force_max"] is not None]
    peaks = [r["peak_excursion"] for r in summaries if r["peak_excursion"] is not None]
    successes = [r["success"] for r in summaries if r["success"] is not None]
    lifts = [r["sustained_lift"] for r in summaries if r["sustained_lift"] is not None]
    count = len(completed)
    dispersion = {}
    for axis in ("dx", "dy", "dz"):
        try:
            dispersion[f"{axis}_std"] = (
                _feedback_number(statistics.stdev(r[axis] for r in valid)) if len(valid) > 1 else None
            )
        except OverflowError:
            dispersion[f"{axis}_std"] = None
    return {
        **dispersion,
        "episodes": summaries,
        "hand_body": hand_body_name,
        "coordinate_frame": "world",
        "contact_channel": "unspecified_sensor_force",
        "trace_episode_count": len(episodes),
        "completed_episode_count": count,
        "uncompleted_trace_episode_count": len(episodes.keys() - completed.keys()),
        "missing_trace_episode_count": len(completed.keys() - episodes.keys()),
        "residual_episode_count": len(valid),
        "success_observed_count": len(successes),
        "lift_observed_count": len(lifts),
        "success_rate": sum(successes) / count if count and len(successes) == count else None,
        "lift_rate": sum(lifts) / count if count and len(lifts) == count else None,
        "peak_excursion": max(peaks) if peaks else None,
        "force_max": max(forces) if forces else None,
        **{f"{axis}_mean": sum(r[axis] / len(valid) for r in valid) if valid else None for axis in ("dx", "dy", "dz")},
    }


def sync_recurrent_feedback_to_neo4j(
    eval_id: str,
    env_name: str,
    reach_traces_path: str,
    timestamp: str | None = None,
    driver: neo4j.Driver | None = None,
    *,
    env_version: str | None = None,
    reifier_id: str | None = None,
    hand_body_name: str | None = None,
    episode_results_path: str | None = None,
    lift_objective: str = "lift",
) -> dict[str, Any]:
    """Attach verified evidence to one existing run/version/reifier in one transaction.

    Args:
        eval_id: Existing, complete EvaluationRun.id; never creates a run.
        env_name: Exact EnvironmentGraph.name already linked by EVALUATED_GRAPH.
        reach_traces_path: JSONL from a single run and target object, bound by the caller.
        timestamp: Optional ISO timestamp for the feedback edge.
        driver: Optional driver; caller-owned drivers are not closed.
        env_version: Required exact EnvironmentGraph.version string. The legacy spec writer
            does not populate this property: verified version registration is a prerequisite,
            not a value this function guesses or backfills from a filename.
        reifier_id: Required ReifiedRelation.reifier_id under this graph; no broadcast.
        hand_body_name: Required pinned link used in every trace row.
        episode_results_path: Finished-episode JSONL required for provenance-bound writes.
            Trace-only analysis belongs to reduce_recurrent_feedback, not this writer.
        lift_objective: Recorded objective implementing the task's sustained-lift predicate.

    Returns:
        Reduced evidence and exact identity after transactional edge/property read-back.
        Residuals are observations in world axes, not validated displacement proposals.
    """
    import hashlib
    import json
    import math
    from pathlib import Path

    identity = {"eval_id": eval_id, "env_name": env_name, "env_version": env_version, "reifier_id": reifier_id}
    for field, value in {**identity, "hand_body_name": hand_body_name}.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Explicit {field} is required")
    traces = Path(reach_traces_path)
    trace_bytes = traces.read_bytes()
    rows = [json.loads(line) for line in trace_bytes.splitlines() if line.strip()]
    results_path = Path(episode_results_path) if episode_results_path is not None else None
    result_bytes = results_path.read_bytes() if results_path is not None else None
    results = (
        [json.loads(line) for line in result_bytes.splitlines() if line.strip()] if result_bytes is not None else None
    )
    for row in [*rows, *(results or [])]:
        if not isinstance(row, dict):
            raise ValueError("Evidence rows must be objects")
        if any(field in row and row[field] != value for field, value in identity.items()):
            raise ValueError("Artifact identity conflicts with requested feedback target")
    summary = reduce_recurrent_feedback(rows, results, hand_body_name=hand_body_name, lift_objective=lift_objective)
    if not summary["residual_episode_count"]:
        raise ValueError("No valid episode residuals for feedback")
    properties = {
        **identity,
        "cartesian_dx": summary["dx_mean"],
        "cartesian_dy": summary["dy_mean"],
        "cartesian_dz": summary["dz_mean"],
        "contact_force_max": summary["force_max"],
        "lift_rate": summary["lift_rate"],
        "success_rate": summary["success_rate"],
        "hand_body": hand_body_name,
        "coordinate_frame": "world",
        "contact_channel": summary["contact_channel"],
        "reach_traces_path": str(traces.resolve()),
        "reach_traces_sha256": hashlib.sha256(trace_bytes).hexdigest(),
        "episode_results_sha256": hashlib.sha256(result_bytes).hexdigest() if result_bytes is not None else None,
        "episode_results_path": str(results_path.resolve()) if results_path is not None else None,
        "lift_objective": lift_objective,
        "evidence_payload": json.dumps(summary, sort_keys=True, allow_nan=False),
    }
    # Match the actual writer's keys and relationships. Requiring a registered version
    # deliberately rejects legacy unversioned graphs, rather than inventing identity.
    target = """
        MATCH (ev:EvaluationRun {id: $eval_id})-[:EVALUATED_GRAPH]->
              (env:EnvironmentGraph {name: $env_name, version: $env_version})
        MATCH (env)-[:HAS_REIFIER]->
              (rf:ReifiedRelation {reifier_id: $reifier_id, env_name: $env_name})
        WHERE EXISTS { MATCH (ev)-[:USED_POLICY]->(:Policy) }
          AND EXISTS { MATCH (rf)-[:REIFIES_SUBJECT]->({env_name: $env_name}) }
          AND EXISTS { MATCH (rf)-[:REIFIES_OBJECT]->({env_name: $env_name}) }
    """

    def write_feedback(tx):
        targets = list(
            tx.run(
                target + """RETURN ev.num_episodes AS num_episodes, ev.success_rate AS success_rate,
                ev.artifact_paths AS artifact_paths, ev.artifact_sha256 AS artifact_sha256,
                ev.episode_results_json AS episode_results_json""",
                **identity,
            )
        )
        if len(targets) != 1:
            raise ValueError("Feedback target must be one existing evaluation/environment/version/reifier chain")
        count = targets[0]["num_episodes"]
        rate = _feedback_number(targets[0]["success_rate"])
        if type(count) is not int or count <= 0 or rate is None or not 0 <= rate <= 1:
            raise ValueError("Existing evaluation must have complete canonical episode metrics")
        if results is not None and (
            count != summary["completed_episode_count"]
            or (
                summary["success_rate"] is not None
                and not math.isclose(rate, summary["success_rate"], rel_tol=1e-6, abs_tol=1e-9)
            )
        ):
            raise ValueError("Evidence conflicts with existing evaluation metrics")
        paths = targets[0].get("artifact_paths")
        hashes = targets[0].get("artifact_sha256")
        payload = targets[0].get("episode_results_json")
        if (
            not isinstance(paths, list)
            or not paths
            or not all(isinstance(path, str) for path in paths)
            or len(set(paths)) != len(paths)
            or not isinstance(hashes, list)
            or len(paths) != len(hashes)
            or not isinstance(payload, str)
        ):
            raise ValueError("Existing evaluation lacks registered evidence provenance")
        registered = dict(zip(paths, hashes))
        for artifact in ("reach_traces", "episode_results"):
            if (
                registered.get(properties[f"{artifact}_path"]) != properties[f"{artifact}_sha256"]
                or properties[f"{artifact}_path"] is None
            ):
                raise ValueError("Feedback evidence conflicts with registered artifact provenance")
        try:
            registered_results = json.loads(payload)
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid registered episode evidence provenance") from exc
        if json.dumps(registered_results, sort_keys=True, allow_nan=False) != json.dumps(
            results, sort_keys=True, allow_nan=False
        ):
            raise ValueError("Feedback episode evidence conflicts with registered raw records")
        tx.run(
            target + """
            MERGE (ev)-[f:FEEDBACK_MUTATION]->(rf)
            ON CREATE SET f += $properties,
                f.timestamp = CASE WHEN $ts IS NULL THEN datetime() ELSE datetime($ts) END
            """,
            **identity,
            properties=properties,
            ts=timestamp,
        ).consume()
        verified = list(
            tx.run(
                target + """MATCH (ev)-[f:FEEDBACK_MUTATION]->(rf) RETURN properties(f) AS feedback,
                ($ts IS NULL OR f.timestamp = datetime($ts)) AS timestamp_matches""",
                **identity,
                ts=timestamp,
            )
        )
        if (
            len(verified) != 1
            or verified[0]["timestamp_matches"] is not True
            or any(verified[0]["feedback"].get(key) != value for key, value in properties.items())
        ):
            raise RuntimeError("Feedback read-back verification failed")
        return {**summary, **identity, "verified": True}

    owns_driver = driver is None
    if driver is None:
        driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            return session.execute_write(write_feedback)
    finally:
        if owns_driver:
            driver.close()


def fetch_recurrent_feedback_from_neo4j(
    env_name: str,
    eval_id: str | None = None,
    driver: neo4j.Driver | None = None,
    *,
    env_version: str | None = None,
    reifier_id: str | None = None,
) -> dict[str, Any] | None:
    """Read feedback only for an explicitly qualified graph version and relation.

    Args:
        env_name: Exact EnvironmentGraph.name.
        eval_id: Exact existing evaluation ID, or latest evaluation for this target.
        driver: Optional caller-owned driver.
        env_version: Required registered EnvironmentGraph.version.
        reifier_id: Required ReifiedRelation.reifier_id.

    Returns:
        One target's observations with frame and provenance, or None when absent.
    """
    for field, value in {"env_name": env_name, "env_version": env_version, "reifier_id": reifier_id}.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Explicit {field} is required")
    if eval_id is not None and (not isinstance(eval_id, str) or not eval_id.strip()):
        raise ValueError("eval_id must be nonempty when supplied")
    owns_driver = driver is None
    if driver is None:
        driver = get_neo4j_driver()
    try:
        with driver.session() as session:
            records = list(
                session.run(
                    """
                MATCH (e:EnvironmentGraph {name: $env_name, version: $env_version})
                      <-[:EVALUATED_GRAPH]-(ev:EvaluationRun)-[f:FEEDBACK_MUTATION]->
                      (rf:ReifiedRelation {reifier_id: $reifier_id, env_name: $env_name})
                MATCH (e)-[:HAS_REIFIER]->(rf)
                WHERE ($eval_id IS NULL OR ev.id = $eval_id)
                  AND f.env_version = $env_version AND f.reifier_id = $reifier_id
                  AND f.eval_id = ev.id AND f.env_name = $env_name
                RETURN f.cartesian_dx AS dx, f.cartesian_dy AS dy, f.cartesian_dz AS dz,
                       f.lift_rate AS lift_rate, f.success_rate AS success_rate,
                       f.contact_force_max AS force_max, f.hand_body AS hand_body,
                       f.coordinate_frame AS coordinate_frame, f.contact_channel AS contact_channel,
                       f.evidence_payload AS evidence_payload, ev.id AS eval_id,
                       rf.reifier_id AS reifier_id, e.version AS env_version
                ORDER BY f.timestamp DESC, ev.id DESC
                LIMIT 1
                """,
                    env_name=env_name,
                    eval_id=eval_id,
                    env_version=env_version,
                    reifier_id=reifier_id,
                )
            )
            return dict(records[0]) if records else None
    finally:
        if owns_driver:
            driver.close()


def sync_environment_evolution_to_neo4j(
    parent_env_name: str,
    child_env_name: str,
    delta_position_xyz: list[float] | None = None,
    delta_rotation_xyzw: list[float] | None = None,
    driver: neo4j.Driver | None = None,
) -> None:
    """Record an evolutionary step between two EnvironmentGraphs in the DCRG active inference loop."""
    owns_driver = False
    if driver is None:
        driver = get_neo4j_driver()
        owns_driver = True

    try:
        with driver.session() as session:
            session.run(
                """
                MATCH (parent:EnvironmentGraph {name: $parent_name})
                MATCH (child:EnvironmentGraph {name: $child_name})
                MERGE (parent)-[r:EVOLVES_TO]->(child)
                SET r.delta_position_xyz = $delta_pos,
                    r.delta_rotation_xyzw = $delta_rot,
                    r.timestamp = datetime()
                """,
                parent_name=parent_env_name,
                child_name=child_env_name,
                delta_pos=delta_position_xyz or [0.0, 0.0, 0.0],
                delta_rot=delta_rotation_xyzw or [0.0, 0.0, 0.0, 1.0],
            )
    finally:
        if owns_driver:
            driver.close()
