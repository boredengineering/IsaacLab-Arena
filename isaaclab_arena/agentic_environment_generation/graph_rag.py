# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Graph-RAG experience memory retriever for IsaacLab-Arena environment generation."""

from __future__ import annotations

import json
from typing import Any, Optional
import neo4j

from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver


class GraphRAGRetriever:
    """Retrieves verified environment subgraphs from Neo4j LPG as few-shot generative priors."""

    def __init__(self, driver: Optional[neo4j.Driver] = None):
        self._driver = driver

    def get_driver(self) -> neo4j.Driver:
        if self._driver is None:
            self._driver = get_neo4j_driver()
        return self._driver

    def retrieve_prior_subgraphs(self, prompt: str, limit: int = 2) -> list[dict[str, Any]]:
        """Retrieve verified environment subgraphs matching keywords in the prompt."""
        p_lower = prompt.lower()
        emb_filter = "g1" if "g1" in p_lower else ("droid" if "droid" in p_lower else ("franka" if "franka" in p_lower else ""))
        fixture_filter = "wireshelving" if "shelv" in p_lower or "rack" in p_lower else ("kitchen" if "kitchen" in p_lower or "counter" in p_lower else ("table" if "table" in p_lower or "desk" in p_lower else ""))

        driver = self.get_driver()
        results: list[dict[str, Any]] = []

        try:
            with driver.session() as session:
                query = """
                MATCH (e:EnvironmentGraph)
                WHERE e.converged = true
                OPTIONAL MATCH (e)-[:HAS_EMBODIMENT]->(emb:Embodiment)
                OPTIONAL MATCH (e)-[:HAS_TERRAIN]->(bg:Fixture)
                OPTIONAL MATCH (e)-[:CONTAINS_OBJECT]->(obj)
                OPTIONAL MATCH (e)-[:HAS_RELATION]->(rel)
                WHERE ($emb_filter = "" OR emb.registry_name CONTAINS $emb_filter)
                  AND ($fixture_filter = "" OR bg.registry_name CONTAINS $fixture_filter)
                WITH e, emb, bg, collect(DISTINCT obj.registry_name) AS objects, collect(DISTINCT rel.kind) AS relations
                RETURN e.name AS name,
                       e.task_description AS task_description,
                       e.task_composition AS task_composition,
                       emb.registry_name AS embodiment,
                       bg.registry_name AS background,
                       objects,
                       relations
                LIMIT $limit
                """
                records = session.run(
                    query,
                    emb_filter=emb_filter,
                    fixture_filter=fixture_filter,
                    limit=limit,
                )
                for rec in records:
                    results.append({
                        "name": rec["name"],
                        "task_description": rec["task_description"],
                        "task_composition": rec["task_composition"],
                        "embodiment": rec["embodiment"],
                        "background": rec["background"],
                        "objects": rec["objects"],
                        "relations": rec["relations"],
                    })
        except Exception:
            # Graceful fallback if Neo4j is offline or empty
            return []

        return results

    def format_priors_as_context(self, priors: list[dict[str, Any]]) -> str:
        """Format retrieved subgraphs into a prompt context block."""
        if not priors:
            return ""

        lines = [
            "### Verified High-Performing Environment Subgraphs (Graph-RAG Priors from Neo4j):",
            "Use these verified structural patterns as guidance for valid entity grounding and spatial relations:",
            "",
        ]
        for idx, p in enumerate(priors, 1):
            lines.append(f"Example {idx} ({p.get('name', 'env')}):")
            lines.append(f"  • Task: {p.get('task_description')}")
            lines.append(f"  • Embodiment: {p.get('embodiment')}")
            lines.append(f"  • Background: {p.get('background')}")
            lines.append(f"  • Objects: {', '.join(p.get('objects', []))}")
            lines.append("")

        return "\n".join(lines)
