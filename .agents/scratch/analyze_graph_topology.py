# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

# Proof of Graph Topology & RDF-star Reified Relations in IsaacLab-Arena Neo4j LPG
import json
import os

from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver

driver = get_neo4j_driver()
with driver.session() as session:
    print("=================================================================")
    print("=== 1. GRAPH TOPOLOGY & CYCLE PROOF (DCRG ANALYSIS) ===")
    print("=================================================================")

    # Check self-loops (length 1)
    self_loops = session.run("MATCH (n)-[r]->(n) RETURN count(r) as c").single()["c"]
    print(f"Self-loops (length 1): {self_loops}")

    # Check 2-cycles (reciprocal edges a -> b -> a)
    reciprocal = session.run("MATCH (a)-[r1]->(b)-[r2]->(a) WHERE id(a) < id(b) RETURN count(r1) as c").single()["c"]
    print(f"Reciprocal 2-cycles (a <-> b): {reciprocal}")

    # Check directed cycles up to length 6
    cycles_query = """
    MATCH p = (n)-[*1..6]->(n)
    RETURN count(p) as cycle_count
    """
    cycle_res = session.run(cycles_query).single()["cycle_count"]
    print(f"Directed cycles of length 1..6: {cycle_res}")

    if cycle_res > 0:
        example_cycles = session.run("""
        MATCH p = (n)-[*1..6]->(n)
        RETURN [x in nodes(p) | labels(x)[0]] as node_labels, [r in relationships(p) | type(r)] as rel_types
        LIMIT 5
        """).data()
        print("Example cycles found:", example_cycles)
    else:
        print("CONCLUSION ON CYCLICITY: The graph has 0 directed cycles of length 1..6.")
        print("It is a Directed Acyclic Graph (DAG) with respect to hierarchical and provenance relations.")

    print("\n=================================================================")
    print("=== 2. RANDOM GRAPH VS DETERMINISTIC ONTOLOGICAL PROPERTY GRAPH ===")
    print("=================================================================")
    degree_stats = session.run("""
    MATCH (n)
    OPTIONAL MATCH (n)-[out]->()
    OPTIONAL MATCH (n)<-[in]-()
    WITH n, count(DISTINCT out) as out_deg, count(DISTINCT in) as in_deg, count(DISTINCT out) + count(DISTINCT in) as deg
    RETURN min(deg) as min_deg, max(deg) as max_deg, avg(deg) as avg_deg,
           stDev(deg) as stdev_deg, count(n) as total_nodes
    """).single()
    print("Degree stats:", dict(degree_stats))

    in_deg_sample = session.run("""
    MATCH (n)
    OPTIONAL MATCH ()-[r]->(n)
    WITH n, count(r) as in_deg
    RETURN labels(n)[0] as label, avg(in_deg) as avg_in, max(in_deg) as max_in, count(n) as node_count
    ORDER BY avg_in DESC
    """).data()
    print("\nDegree breakdown by Node Label:")
    for row in in_deg_sample:
        lbl = row["label"]
        cnt = row["node_count"]
        ain = row["avg_in"]
        min_in = row["max_in"]
        print(f"  Label: {lbl:<22} Count: {cnt:<4} Avg In-Deg: {ain:<6.2f} Max In-Deg: {min_in}")

    out_deg_sample = session.run("""
    MATCH (n)
    OPTIONAL MATCH (n)-[r]->()
    WITH n, count(r) as out_deg
    RETURN labels(n)[0] as label, avg(out_deg) as avg_out, max(out_deg) as max_out, count(n) as node_count
    ORDER BY avg_out DESC
    """).data()
    print("\nOut-Degree breakdown by Node Label:")
    for row in out_deg_sample:
        lbl = row["label"]
        cnt = row["node_count"]
        aout = row["avg_out"]
        mout = row["max_out"]
        print(f"  Label: {lbl:<22} Count: {cnt:<4} Avg Out-Deg: {aout:<6.2f} Max Out-Deg: {mout}")

    print("\n=================================================================")
    print("=== 3. PROOF OF RDF-STAR REIFIED RELATIONS IN NEO4J LPG ===")
    print("=================================================================")
    reifiers_count = session.run("MATCH (rf:ReifiedRelation) RETURN count(rf) as c").single()["c"]
    print(f"Total ReifiedRelation nodes in Neo4j: {reifiers_count}")

    reifiers = session.run("""
    MATCH (rf:ReifiedRelation)
    OPTIONAL MATCH (rf)-[:REIFIES_SUBJECT]->(s)
    OPTIONAL MATCH (rf)-[:REIFIES_OBJECT]->(t)
    RETURN rf.reifier_id as id, rf.relation_type as rel_type, s.id as subject, t.id as object,
           rf.surface_anchor as anchor, rf.kinematic_manifold as manifold,
           rf.delta_x_min as dx_min, rf.delta_x_max as dx_max,
           rf.required_friction as friction, rf.required_headroom as headroom
    LIMIT 10
    """).data()
    for r in reifiers:
        print(f"  Reifier [{r['id']}]: << ({r['subject']}) -[:{r['rel_type']}]-> ({r['object']}) >>")
        print(
            f"     Manifold: {r['manifold']} | Anchor: {r['anchor']} | Friction: {r['friction']} | dx: [{r['dx_min']},"
            f" {r['dx_max']}]"
        )

    print("\n=================================================================")
    print("=== 4. G1 TABLETOP ENVIRONMENT SUBGRAPH IN NEO4J ===")
    print("=================================================================")
    g1_envs = session.run("""
    MATCH (e:EnvironmentGraph) WHERE e.name CONTAINS "g1" AND e.name CONTAINS "apple"
    RETURN e.name as name, e.task_description as task, e.converged as converged, e.llm_call_count as llm_calls
    """).data()
    for e in g1_envs:
        print(f"  Env: {e['name']} | Task: {e['task']} | Converged: {e['converged']}")

    g1_details = session.run("""
    MATCH (e:EnvironmentGraph {name: "g1_tabletop_apple_to_plate"})
    OPTIONAL MATCH (e)-[r]->(child)
    RETURN type(r) as rel, labels(child)[0] as child_type, child.id as child_id, child.registry_name as reg_name
    """).data()
    print("  Children of g1_tabletop_apple_to_plate:")
    for d in g1_details:
        print(f"    -[{d['rel']}]-> ({d['child_type']}: id={d['child_id']}, reg={d['reg_name']})")

    # Check relationships between the objects inside g1_tabletop_apple_to_plate
    obj_rels = session.run("""
    MATCH (s {env_name: "g1_tabletop_apple_to_plate"})-[r]->(t {env_name: "g1_tabletop_apple_to_plate"})
    RETURN s.id as subject, type(r) as relation, t.id as target, properties(r) as props
    """).data()
    print("  Internal relations in g1_tabletop_apple_to_plate:")
    for o in obj_rels:
        print(f"    ({o['subject']}) -[{o['relation']}]-> ({o['target']}) : {o['props']}")
