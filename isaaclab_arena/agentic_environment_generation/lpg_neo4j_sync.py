# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Labeled Property Graph (LPG) synchronizer for IsaacLab-Arena environments using Neo4j and Cypher."""

import os
from typing import Any, Dict, List, Optional
import neo4j

from isaaclab_arena.environment_spec.arena_env_graph_spec import (
    ArenaEnvGraphSpec,
    AssetSpec,
    SpatialRelationSpec,
    TaskSpec,
)


def get_neo4j_driver(
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> neo4j.Driver:
    """Creates a Neo4j driver using environment variables or provided credentials."""
    uri = uri or os.environ.get("NEO4J_URI", "bolt://172.17.0.2:7687")
    user = user or os.environ.get("NEO4J_USER", "neo4j")
    password = password or os.environ.get("NEO4J_PASSWORD", "isaaclab_arena_password")
    return neo4j.GraphDatabase.driver(uri, auth=(user, password))


def sync_spec_to_neo4j(
    spec: ArenaEnvGraphSpec,
    driver: Optional[neo4j.Driver] = None,
    telemetry: Optional[Any] = None,
    parent_env_name: Optional[str] = None,
    derivation_feedback: Optional[str] = None,
) -> Dict[str, Any]:
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
                label = "Fixture:Furniture" if "table" in obj.registry_name or "shelf" in obj.registry_name or "rack" in obj.registry_name else ("RigidObject:Receptacle" if "bin" in obj.registry_name else "RigidObject")
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
    driver: Optional[neo4j.Driver] = None,
) -> List[Dict[str, Any]]:
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
    driver: Optional[neo4j.Driver] = None,
) -> List[Dict[str, Any]]:
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
    driver: Optional[neo4j.Driver] = None,
) -> Dict[str, Any]:
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
    num_episodes = int(num_episodes_val[0]) if num_episodes_val else 0

    payload_val = list(g.objects(eval_runs[0], ARENA.metricsPayload)) if eval_runs else []
    metrics_payload = str(payload_val[0]) if payload_val else "{}"

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
                    ev.metrics_payload = $metrics_payload,
                    ev.ended_at = $ended_at
                WITH ev
                OPTIONAL MATCH (e:EnvironmentGraph {name: $env_name})
                FOREACH (_ IN CASE WHEN e IS NOT NULL THEN [1] ELSE [] END |
                    MERGE (ev)-[:EVALUATED_GRAPH]->(e)
                )
                MERGE (p:Policy {name: $policy_name})
                MERGE (ev)-[:USED_POLICY]->(p)
                """,
                eval_id=eval_id,
                success_rate=success_rate,
                num_episodes=num_episodes,
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
            }
    finally:
        if owns_driver:
            driver.close()
