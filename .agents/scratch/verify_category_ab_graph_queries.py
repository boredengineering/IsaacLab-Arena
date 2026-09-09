"""Execute each visual Cypher query read-only and save the actual returned graph/counts."""

import json
import re
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / ".agents/references/presentations/category_a_b_graph_queries.cypher"
    blocks = re.split(r"(?m)^// === ([a-z0-9_]+) ===\n", source.read_text())
    assert len(blocks) == 35, "Expected seventeen named queries"
    verification = {"source": str(source), "database_writes": False, "queries": []}
    driver = get_neo4j_driver(uri="bolt://localhost:7688")
    try:
        with driver.session(default_access_mode="READ") as session:
            for name, query in zip(blocks[1::2], blocks[2::2]):
                result = session.run(query.strip().rstrip(";"))
                graph = result.graph()
                rows = list(result)
                summary = result.consume()
                notifications = [str(item) for item in summary.gql_status_objects if item.is_notification]
                assert not summary.counters.contains_updates, name
                assert not notifications, (name, notifications)
                assert rows, (name, "No records returned")
                nodes = [{"element_id": n.element_id, "labels": sorted(n.labels), "properties": dict(n)} for n in graph.nodes]
                relationships = [{"element_id": r.element_id, "type": r.type,
                                  "source": r.start_node.element_id, "target": r.end_node.element_id,
                                  "properties": dict(r)} for r in graph.relationships]
                verification["queries"].append({"name": name, "query": query.strip(), "rows": len(rows),
                    "nodes": nodes, "relationships": relationships,
                    "node_count": len(nodes), "relationship_count": len(relationships),
                    "notifications": notifications,
                    "table_rows": [r.data() for r in rows] if not nodes else None})
        print(json.dumps(verification, indent=2, default=str))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
