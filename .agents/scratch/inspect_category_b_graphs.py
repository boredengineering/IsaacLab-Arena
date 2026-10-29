"""Read-only discovery of the actual B1/B4 scene statements and evaluation links."""

import json
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver


def main():
    root = Path(__file__).resolve().parents[2]
    inventory = json.loads((root / ".agents/references/presentations/category_a_b_run_inventory.json").read_text())
    identifiers = [r["evaluation_id"] for r in inventory["runs"]
                   if "tomato_soup" in r["scenario_family"] or "spam_can" in r["scenario_family"]]
    queries = {
        "members": """MATCH (g:EnvironmentGraph {name:$name})-[r]-(n)
RETURN type(r) AS relationship, labels(n) AS labels, properties(n) AS properties""",
        "statements": """MATCH (g:EnvironmentGraph {name:$name})-[:HAS_REIFIER]->(rf:ReifiedRelation)
MATCH (rf)-[:REIFIES_SUBJECT]->(s), (rf)-[:REIFIES_OBJECT]->(t)
RETURN properties(rf) AS annotations, s.id AS subject, t.id AS object ORDER BY annotations.reifier_id""",
        "direct_edges": """MATCH (s)-[r]->(t) WHERE s.env_name=$name AND t.env_name=$name
RETURN s.id AS subject, type(r) AS predicate, t.id AS object, properties(r) AS annotations""",
    }
    output = {"graphs": [], "evaluations": []}
    driver = get_neo4j_driver(uri="bolt://localhost:7688")
    try:
        with driver.session(default_access_mode="READ") as session:
            names = session.run("""MATCH (g:EnvironmentGraph)
WHERE g.name CONTAINS 'tomato_soup' OR g.name CONTAINS 'spam_can'
RETURN g.name AS name, properties(g) AS properties ORDER BY name""").data()
            for graph in names:
                for key, query in queries.items():
                    result = session.run(query, name=graph["name"])
                    graph[key] = result.data()
                    assert not result.consume().counters.contains_updates
                output["graphs"].append(graph)
            output["evaluations"] = session.run("""MATCH (ev:EvaluationRun) WHERE ev.id IN $ids
OPTIONAL MATCH (ev)-[r]-(n)
RETURN ev.id AS id, ev.num_episodes AS num_episodes, ev.success_rate AS success_rate,
       type(r) AS relationship, labels(n) AS neighbor_labels,
       coalesce(n.name,n.id) AS neighbor ORDER BY id""", ids=identifiers).data()
        print(json.dumps(output, indent=2, default=str))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
