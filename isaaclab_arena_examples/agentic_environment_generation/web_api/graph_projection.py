# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded JSON projection of actual Neo4j result entities, not inferred graph links."""

import math
import re
from itertools import islice

_SENSITIVE = re.compile(r"(?:^|_)(?:password|secret|token|api_key|authorization)(?:$|_)", re.I)


class GraphProjection:
    """Collect graph identities while producing bounded, JSON-safe table values."""

    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self.truncated = False
        self.remaining = 10000

    def value(self, value, depth=0):
        from neo4j.graph import Node, Path, Relationship

        self.remaining -= 1
        if self.remaining < 0 or depth > 8:
            self.truncated = True
            return "[truncated]"
        if isinstance(value, Node):
            properties = self.value(dict(value), depth + 1)
            labels = sorted(value.labels)
            node = {
                "id": value.element_id,
                "label": str(value.get("name") or value.get("id") or value.get("registry_name") or value.element_id)[
                    :160
                ],
                "role": labels[0] if labels else "node",
                "labels": labels,
                "properties": properties,
            }
            if node["id"] in self.nodes or len(self.nodes) < 256:
                self.nodes[node["id"]] = node
            else:
                self.truncated = True
            return node
        if isinstance(value, Relationship):
            self.value(value.start_node, depth + 1)
            self.value(value.end_node, depth + 1)
            edge = {
                "id": value.element_id,
                "source": value.start_node.element_id,
                "target": value.end_node.element_id,
                "label": value.type,
                "properties": self.value(dict(value), depth + 1),
            }
            if (edge["id"] in self.edges or len(self.edges) < 512) and all(
                node_id in self.nodes for node_id in (edge["source"], edge["target"])
            ):
                self.edges[edge["id"]] = edge
            else:
                self.truncated = True
            return edge
        if isinstance(value, Path):
            return {
                "nodes": self.value(value.nodes, depth + 1),
                "edges": self.value(value.relationships, depth + 1),
            }
        if isinstance(value, dict):
            if len(value) > 256:
                self.truncated = True
            return {
                str(key): "[redacted]" if _SENSITIVE.search(str(key)) else self.value(item, depth + 1)
                for key, item in islice(value.items(), 256)
            }
        if isinstance(value, (list, tuple, set, frozenset)):
            if len(value) > 256:
                self.truncated = True
            return [self.value(item, depth + 1) for item in islice(value, 256)]
        if isinstance(value, str):
            if len(value) > 4096:
                self.truncated = True
                return value[:4096] + "[truncated]"
            return value
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if hasattr(value, "iso_format"):
            return value.iso_format()
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)[:4096]

    def graph(self):
        """Return only stored entities encountered in this query's returned values."""
        return {"nodes": list(self.nodes.values()), "edges": list(self.edges.values())}

    def cell(self, column, value):
        """Preserve redaction and projection limits for named result columns."""
        return "[redacted]" if _SENSITIVE.search(column) else self.value(value)
