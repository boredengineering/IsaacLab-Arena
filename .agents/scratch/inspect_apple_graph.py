"""Inspect the live apple graph and reproduce presentation-query warnings without writes."""

import json

from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver

GRAPH_NAME = "franka_droid_apple_to_bowl_maple_table"
QUERIES = {
    "original_topology": """MATCH (g:EnvironmentGraph)
WHERE g.name CONTAINS 'apple_to_wooden_bowl'
OPTIONAL MATCH (g)-[r]-(n)
RETURN g, r, n""",
    "original_factors": """MATCH (g:EnvironmentGraph)-[:HAS_REIFIER]->(rf:ReifiedRelation)
WHERE g.name CONTAINS 'apple'
MATCH (rf)-[:REIFIES_SUBJECT]->(s), (rf)-[:REIFIES_OBJECT]->(t)
RETURN g.name, rf.relation_type, s.name, t.name, rf.clearance_radius, rf.nominal_height""",
    "apple_names": """MATCH (g:EnvironmentGraph) WHERE g.name CONTAINS 'apple'
RETURN g.name AS name, keys(g) AS property_keys ORDER BY name""",
    "root_properties": """MATCH (g:EnvironmentGraph {name:$name}) RETURN properties(g) AS properties""",
    "members": """MATCH (g:EnvironmentGraph {name:$name})-[r]-(n)
RETURN type(r) AS relationship, labels(n) AS labels, properties(n) AS properties ORDER BY relationship""",
    "reifiers": """MATCH (g:EnvironmentGraph {name:$name})-[:HAS_REIFIER]->(rf:ReifiedRelation)
OPTIONAL MATCH (rf)-[r]->(n)
RETURN properties(rf) AS reifier, collect({relationship:type(r), labels:labels(n), properties:properties(n)}) AS neighbors""",
    "local_edges": """MATCH (s)-[r]->(t) WHERE s.env_name=$name AND t.env_name=$name
RETURN s.id AS source_id, labels(s) AS source_labels, type(r) AS relationship,
       t.id AS target_id, labels(t) AS target_labels, properties(r) AS properties""",
    "current_run": """MATCH (ev:EvaluationRun {id:'eval_run_1788928970'})
OPTIONAL MATCH (ev)-[r]-(n)
RETURN properties(ev) AS evaluation, type(r) AS relationship, labels(n) AS labels, properties(n) AS neighbor""",
}


def main():
    driver = get_neo4j_driver(uri="bolt://localhost:7688")
    output = {}
    try:
        with driver.session(default_access_mode="READ") as session:
            for key, query in QUERIES.items():
                result = session.run(query, name=GRAPH_NAME)
                rows = [r.data() for r in result]
                summary = result.consume()
                assert not summary.counters.contains_updates
                output[key] = {"query":query, "rows":rows, "row_count":len(rows),
                               "notifications":summary.notifications or [], "contains_updates":False}
        print(json.dumps(output, indent=2, default=str))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
