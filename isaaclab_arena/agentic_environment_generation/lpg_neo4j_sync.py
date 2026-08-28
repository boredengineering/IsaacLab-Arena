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
) -> Dict[str, Any]:
    """Synchronizes an ArenaEnvGraphSpec into Neo4j as a Labeled Property Graph (LPG).

    Args:
        spec: The arena environment graph specification.
        driver: Optional active Neo4j driver.

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
            session.run(
                """
                MERGE (e:EnvironmentGraph {name: $name})
                SET e.task_composition = $task_comp,
                    e.task_description = $task_desc,
                    e.updated_at = datetime()
                """,
                name=spec.env_name,
                task_comp=spec.task.composition if spec.task else "atomic",
                task_desc=spec.task.description if spec.task else "",
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

            # 4. Merge Objects
            for obj in spec.objects:
                label = "Fixture" if "table" in obj.registry_name or "shelf" in obj.registry_name or "room" in obj.registry_name else "RigidObject"
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

            # 5. Merge Relations with Rich Properties (LPG Edges)
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

            # Summary verification
            result = session.run(
                """
                MATCH (e:EnvironmentGraph {name: $env_name})
                OPTIONAL MATCH (e)-[:HAS_EMBODIMENT|HAS_TERRAIN|CONTAINS_OBJECT]->(n)
                OPTIONAL MATCH (n)-[r]->(m) WHERE r.env_name IS NULL
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
                MATCH (s)-[r:PLACED_ON|PLACED_INSIDE]->(parent)
                WHERE s.env_name = $env_name AND parent.env_name = $env_name
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
