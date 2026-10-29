"""Check B1/B4 presentation queries and diagram edges against real Neo4j results."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / ".agents/references/presentations"


def normalized(query):
    return re.sub(r"\s+", " ", query).strip().rstrip(";")


def main():
    text = (BASE / "category_a_b_manipulation_experiments.md").read_text()
    results = json.loads((BASE / "category_a_b_graph_queries.verified.json").read_text())["queries"]
    by_name = {q["name"]: q for q in results}
    known = {normalized(q["query"]) for q in results}
    assert len(results) == 17 and all(q["rows"] > 0 and not q["notifications"] for q in results)
    scenarios = [
        ("B1", "B2", "10_b1_can_statement_closeup", 3,
         {"G": "franka_droid_tomato_soup_to_bin", "R": "reifier_tomato_soup_can_maple_table", "C": "tomato_soup_can", "T": "maple_table"}),
        ("B4", "B5", "14_b4_support_statements_closeup", 4,
         {"G": "franka_droid_spam_can_to_grey_bin", "C": "spam_can", "B": "grey_bin", "T": "maple_table"}),
    ]
    checks = []
    for scenario, next_scenario, query_name, count, names in scenarios:
        section = text.split("### Scenario " + scenario + ":", 1)[1].split("### Scenario " + next_scenario + ":", 1)[0]
        queries = re.findall(r"```cypher\n(.*?)```", section, re.S)
        assert len(queries) == count and all(normalized(q) in known for q in queries), scenario
        diagrams = re.findall(r"```mermaid\n(.*?)```", section, re.S)
        assert len(diagrams) == 1
        diagram_edges = re.findall(r'\b([A-Z])(?:\["[^\n]*?"\])?\s+-->\|([^|]+)\|\s*([A-Z])', diagrams[0])
        projected = {(names[s], rel, names[t]) for s, rel, t in diagram_edges}
        result = by_name[query_name]
        ids = {n["element_id"]: n["properties"].get("reifier_id", n["properties"].get("id", n["properties"].get("name"))) for n in result["nodes"]}
        actual = {(ids[r["source"]], r["type"], ids[r["target"]]) for r in result["relationships"]}
        assert projected == actual and len(projected) == 4, (scenario, projected, actual)
        checks.append({"scenario": scenario, "tested_query_blocks": count, "diagram_edges_match_database": 4})
    assert by_name["15_b4_reification_gap"]["table_rows"][0]["reifier_count"] == 0
    print(json.dumps({"queries_passed": len(results), "presentation_checks": checks, "b4_reifiers": 0}, indent=2))


if __name__ == "__main__":
    main()
