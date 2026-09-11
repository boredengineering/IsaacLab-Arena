# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Restricted, bounded Neo4j reads for the environment editor."""

import asyncio
import json
import re
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .graph_projection import GraphProjection
from .security import require_mutation, require_session

_FORBIDDEN = {
    "CALL",
    "LOAD",
    "CSV",
    "CREATE",
    "MERGE",
    "SET",
    "DELETE",
    "DETACH",
    "REMOVE",
    "FOREACH",
    "DROP",
    "ALTER",
    "GRANT",
    "DENY",
    "REVOKE",
    "SHOW",
    "START",
    "STOP",
    "TERMINATE",
    "USE",
    "EXPLAIN",
    "PROFILE",
    "INSERT",
    "FINISH",
}
_FUNCTIONS = {
    "COUNT",
    "COLLECT",
    "COALESCE",
    "LABELS",
    "TYPE",
    "PROPERTIES",
    "ELEMENTID",
    "ID",
    "SIZE",
    "TOSTRING",
    "TOINTEGER",
    "TOFLOAT",
    "TOBOOLEAN",
    "HEAD",
    "LAST",
    "KEYS",
    "NODES",
    "RELATIONSHIPS",
    "LENGTH",
    "EXISTS",
    "LOWER",
    "UPPER",
    "TOLOWER",
    "TOUPPER",
    "TRIM",
    "SPLIT",
    "REPLACE",
    "SUBSTRING",
    "ABS",
    "ROUND",
    "FLOOR",
    "CEIL",
    "MIN",
    "MAX",
    "AVG",
    "SUM",
    "DISTINCT",
    "DATETIME",
    "DATE",
    "TIME",
    "TIMESTAMP",
    "REVERSE",
    "RANGE",
    "SHORTESTPATH",
    "ALLSHORTESTPATHS",
    "ANY",
    "ALL",
    "NONE",
    "SINGLE",
    "REDUCE",
    "STARTNODE",
    "ENDNODE",
}
_GROUP_KEYWORDS = {"MATCH", "OPTIONAL", "WHERE", "WITH", "RETURN", "IN", "NOT", "AND", "OR", "XOR", "WHEN"}


def _code_only(query: str) -> str:
    """Blank literals and retain opaque backtick tokens for quoted identifiers."""
    result = []
    index = 0
    while index < len(query):
        character = query[index]
        if query[index : index + 2] in {"//", "/*"}:
            raise ValueError("Comments are not supported in the read-only query editor")
        if character in {"'", '"', "`"}:
            quote = character
            # Keep identifier boundaries visible without interpreting their contents.
            result.append("`" if quote == "`" else " ")
            index += 1
            while index < len(query):
                if query[index] == "\\":
                    index += 2
                elif query[index] == quote:
                    if index + 1 < len(query) and query[index + 1] == quote:
                        index += 2
                    else:
                        index += 1
                        break
                else:
                    index += 1
            else:
                raise ValueError("Unterminated quoted value")
        else:
            if ord(character) > 127:
                raise ValueError("Use backticks for non-ASCII identifiers")
            result.append(character)
            index += 1
    return "".join(result)


def validate_query(query: str) -> str:
    """Accept a single read-pattern query; reject procedures, updates and unknown functions."""
    if not isinstance(query, str) or not query.strip() or len(query.encode()) > 16000:
        raise ValueError("Enter a Cypher read query of at most 16000 bytes")
    query = query.strip()
    if query.endswith(";"):
        query = query[:-1].rstrip()
    code = _code_only(query)
    if ";" in code:
        raise ValueError("Only one Cypher statement is allowed")
    tokens = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", code.upper())
    if not tokens or tokens[0] not in {"MATCH", "OPTIONAL", "WITH", "UNWIND", "RETURN"}:
        raise ValueError("Use a MATCH, WITH, UNWIND or RETURN read query")
    if set(tokens) & _FORBIDDEN:
        raise ValueError("Only read queries are supported; updates, administration and CALL are disabled")
    if re.search(r"`\s*\(", code):
        raise ValueError("Quoted function calls are disabled; use an unquoted allowlisted function")
    if re.search(r"\.\s*[A-Za-z_]\w*\s*\(", code):
        raise ValueError("Procedure and namespaced function calls are disabled")
    for function in re.findall(r"\b([A-Za-z_]\w*)\s*\(", code):
        if function.upper() not in _FUNCTIONS | _GROUP_KEYWORDS:
            raise ValueError(f"Function '{function}' is not in the read-only allowlist")
    return query


def _driver():
    from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver

    return get_neo4j_driver(
        connection_timeout=3,
        connection_acquisition_timeout=4,
        max_transaction_retry_time=0,
        max_connection_pool_size=2,
    )


class GraphQueryService:
    """Compile read queries first, then execute with a timeout and rollback-only transactions."""

    def __init__(self, driver_factory=None):
        self.driver_factory = driver_factory or _driver

    def query(self, query, params):
        query = validate_query(query)
        if not isinstance(params, dict) or len(json.dumps(params, allow_nan=False).encode()) > 16000:
            raise ValueError("Parameters must be a JSON object of at most 16000 bytes")
        started = time.monotonic()
        projection = GraphProjection()
        with self.driver_factory() as driver:
            with driver.session(default_access_mode="READ", fetch_size=200) as session:
                with session.begin_transaction(timeout=5) as transaction:
                    try:
                        summary = transaction.run("EXPLAIN " + query, params).consume()
                        if summary.query_type != "r":
                            raise ValueError("Neo4j did not classify this query as read-only")
                        records = transaction.run(query, params)
                        columns = list(records.keys())
                        fetched = records.fetch(201)
                        rows = [
                            [projection.cell(column, record[column]) for column in columns] for record in fetched[:200]
                        ]
                    finally:
                        transaction.rollback()
        return {
            "columns": columns,
            "rows": rows,
            "graph": projection.graph(),
            "truncated": len(fetched) > 200 or projection.truncated,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "read_only": True,
        }


EXAMPLES = [
    {
        "id": "environments",
        "name": "Environment graphs",
        "query": "MATCH (e:EnvironmentGraph) RETURN e LIMIT 50",
        "params": {},
    },
    {
        "id": "neighborhood",
        "name": "Environment neighborhood",
        "query": "MATCH (e:EnvironmentGraph {name: $name}) OPTIONAL MATCH (e)-[r]-(n) RETURN e, r, n LIMIT 100",
        "params": {"name": ""},
    },
    {
        "id": "statements",
        "name": "Reified statements",
        "query": (
            "MATCH (e:EnvironmentGraph)-[r:HAS_REIFIER]->(s) OPTIONAL MATCH (s)-[a]-(n) RETURN e,r,s,a,n LIMIT 100"
        ),
        "params": {},
    },
    {
        "id": "evaluations",
        "name": "Evaluation evidence",
        "query": "MATCH (ev:EvaluationRun)-[r:EVALUATED_GRAPH]->(e) RETURN ev,r,e LIMIT 100",
        "params": {},
    },
]
router = APIRouter(prefix="/api/graph")
_SLOTS = threading.BoundedSemaphore(2)


class GraphQueryInput(BaseModel):
    """One read query and JSON parameters; credentials remain server-side."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    query: str = Field(min_length=1, max_length=16000)
    params: dict = Field(default_factory=dict)


def _execute_bounded(query, params):
    if not _SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Neo4j query slots are busy; retry after the current query completes")
    try:
        return GraphQueryService().query(query, params)
    finally:
        _SLOTS.release()


@router.get("/examples", dependencies=[Depends(require_session)])
async def examples():
    return {"queries": EXAMPLES}


@router.get("/status", dependencies=[Depends(require_session)])
async def status():
    try:
        await asyncio.to_thread(_execute_bounded, "RETURN 1 AS ready", {})
    except Exception:
        return {
            "available": False,
            "message": "Neo4j is unavailable or busy. Check the Arena database service and server-side configuration.",
        }
    return {"available": True, "message": "Connected to the configured Arena database; read-only queries enabled."}


@router.post("/query", dependencies=[Depends(require_mutation)])
async def run_query(body: GraphQueryInput):
    try:
        return await asyncio.to_thread(_execute_bounded, body.query, body.params)
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except Exception as error:
        code = getattr(error, "code", "")
        if code.startswith("Neo.ClientError.Statement."):
            category = code.rsplit(".", 1)[-1]
            raise HTTPException(
                422, f"Neo4j rejected the query ({category}). Check Cypher syntax and parameter names."
            ) from None
        raise HTTPException(
            503, "Neo4j query unavailable or timed out. Check the Arena database service and narrow the query."
        ) from None
