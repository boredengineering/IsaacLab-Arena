"""Read-only inventory of recorded Neo4j evaluation metadata for a historical audit."""

import json

from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver


def main():
    driver = get_neo4j_driver(uri="bolt://localhost:7688")
    try:
        with driver.session(default_access_mode="READ") as session:
            keys = [r.data() for r in session.run(
                "MATCH (ev:EvaluationRun) UNWIND keys(ev) AS key RETURN key, count(*) AS count ORDER BY key"
            )]
            runs = [r.data() for r in session.run(
                """
                MATCH (ev:EvaluationRun)
                OPTIONAL MATCH (ev)-[:EVALUATED_GRAPH]->(g:EnvironmentGraph)
                WITH ev, collect(DISTINCT g.name) AS environments
                OPTIONAL MATCH (ev)-[:USED_POLICY]->(p:Policy)
                RETURN ev.id AS id, ev.evaluation_id AS evaluation_id,
                       ev.num_episodes AS num_episodes, ev.success_rate AS success_rate,
                       ev.all_complete_rate AS all_complete_rate,
                       ev.mean_progress_score AS mean_progress_score,
                       ev.blocking_predicate AS blocking_predicate,
                       ev.metrics_payload AS metrics_payload, ev.ended_at AS ended_at,
                       ev.semantic_integrity_verified AS semantic_integrity_verified,
                       ev.integrity_violation AS integrity_violation,
                       environments, collect(DISTINCT p.name) AS policies
                ORDER BY ended_at, id
                """
            )]
            graphs = [r.data() for r in session.run(
                """
                MATCH (g:EnvironmentGraph)
                WHERE any(term IN $terms WHERE toLower(coalesce(g.name,'')) CONTAINS term)
                RETURN g.name AS name, g.id AS id, g.env_name AS env_name, keys(g) AS property_keys
                ORDER BY name
                """, terms=["droid", "apple", "banana", "avocado", "lemon", "pepper", "tomato", "spam", "mustard", "cracker", "tuna"]
            )]
        print(json.dumps({"evaluation_property_keys": keys, "evaluations": runs,
                          "candidate_environment_graphs": graphs}, indent=2, default=str))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
