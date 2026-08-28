# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""CLI utility to inspect, query, and visualize Labeled Property Graphs (LPG) in Neo4j."""

import argparse
import json
import sys

from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver, query_spatial_hierarchy


def list_environment_graphs(driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (e:EnvironmentGraph)
            RETURN e.name AS name,
                   e.task_description AS task_description,
                   e.task_composition AS composition,
                   e.updated_at AS updated_at
            ORDER BY e.updated_at DESC
            """
        )
        return [record.data() for record in result]


def inspect_environment(driver, env_name: str) -> None:
    print(f"\n==================================================")
    print(f"  Neo4j LPG Inspection: '{env_name}'")
    print(f"==================================================")

    with driver.session() as session:
        # 1. Inspect Nodes
        nodes_result = session.run(
            """
            MATCH (e:EnvironmentGraph {name: $env_name})
            OPTIONAL MATCH (e)-[:HAS_EMBODIMENT]->(emb:Embodiment)
            OPTIONAL MATCH (e)-[:HAS_TERRAIN]->(bg:Fixture)
            OPTIONAL MATCH (e)-[:CONTAINS_OBJECT]->(obj)
            RETURN emb.id AS embodiment_id,
                   emb.registry_name AS embodiment_registry,
                   bg.id AS terrain_id,
                   bg.registry_name AS terrain_registry,
                   collect(DISTINCT {id: obj.id, registry: obj.registry_name, labels: labels(obj)}) AS objects
            LIMIT 1
            """,
            env_name=env_name,
        ).single()

        if not nodes_result:
            print(f"[Error] Environment '{env_name}' not found in Neo4j.")
            return

        print(f"\n[Entities]")
        print(f"  • Embodiment: {nodes_result['embodiment_id']} ({nodes_result['embodiment_registry']})")
        print(f"  • Terrain/Room: {nodes_result['terrain_id']} ({nodes_result['terrain_registry']})")
        print(f"  • Objects ({len(nodes_result['objects'])}):")
        for obj in nodes_result["objects"]:
            if obj.get("id"):
                print(f"    - {obj['id']} (registry: {obj['registry']}, labels: {obj['labels']})")

        # 2. Spatial Hierarchy & Edge Properties
        hierarchy = query_spatial_hierarchy(env_name, driver=driver)
        print(f"\n[Spatial Containment & Layout (LPG Edges)]")
        for rel in hierarchy:
            anchor_str = f" [anchor: {rel['surface_anchor']}]" if rel.get("surface_anchor") else ""
            height_str = f" [height: {rel['nominal_height']}m]" if rel.get("nominal_height") is not None else ""
            print(f"  • ({rel['subject']}) -[:{rel['relation']}{anchor_str}{height_str}]-> ({rel['parent_id']})")

        # 3. Cypher Traversal Chain
        chain_result = session.run(
            """
            MATCH path = (s:RigidObject {env_name: $env_name})-[:PLACED_ON*1..5]->(root:Fixture {env_name: $env_name})
            RETURN [n in nodes(path) | n.id] AS placement_chain
            """,
            env_name=env_name,
        )
        chains = [r["placement_chain"] for r in chain_result]
        if chains:
            print(f"\n[Containment Chains]")
            for chain in chains:
                print(f"  • {' -> '.join(chain)}")


def main():
    parser = argparse.ArgumentParser(description="Inspect Labeled Property Graphs in Neo4j.")
    parser.add_argument("--env_name", type=str, help="Specific environment graph name to inspect.")
    parser.add_argument("--list", action="store_true", help="List all environments stored in Neo4j.")
    parser.add_argument("--cypher", type=str, help="Run a custom ad-hoc Cypher query.")
    args = parser.parse_args()

    try:
        driver = get_neo4j_driver()
        driver.verify_connectivity()
    except Exception as exc:
        print(f"[Error] Failed to connect to Neo4j: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.cypher:
            print(f"\n[Executing Cypher]: {args.cypher}")
            with driver.session() as session:
                result = session.run(args.cypher)
                for record in result:
                    print(json.dumps(record.data(), indent=2, default=str))
            return

        if args.list or not args.env_name:
            envs = list_environment_graphs(driver)
            print(f"\n[Environments in Neo4j LPG ({len(envs)})]:")
            for env in envs:
                print(f"  • {env['name']}: {env['task_description']} ({env['composition']})")
            if not args.env_name:
                return

        if args.env_name:
            inspect_environment(driver, args.env_name)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
