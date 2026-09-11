# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Read-only workbench graph query contracts; no credentials or live database required."""

from unittest.mock import MagicMock, patch

import pytest


def test_graph_driver_accepts_bounded_connection_options():
    from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver

    with patch("neo4j.GraphDatabase.driver") as factory:
        driver = get_neo4j_driver(connection_timeout=3, connection_acquisition_timeout=4, max_connection_pool_size=2)
    assert driver is factory.return_value
    assert factory.call_args.kwargs["connection_timeout"] == 3
    assert factory.call_args.kwargs["connection_acquisition_timeout"] == 4
    assert factory.call_args.kwargs["max_connection_pool_size"] == 2


def test_query_validation_accepts_read_patterns_and_rejects_side_effects():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_queries import validate_query

    assert validate_query("MATCH (n) RETURN n LIMIT 20;") == "MATCH (n) RETURN n LIMIT 20"
    assert validate_query("MATCH(n) WHERE n.name = 'CREATE;CALL' RETURN n")
    assert validate_query("MATCH(n:`Odd label`) RETURN properties(n)")
    for query in (
        "CREATE(n)",
        "MATCH(n) SET n.x=1 RETURN n",
        "MATCH(n) DETACH DELETE n",
        "CALL db.labels()",
        "CALL {MATCH(n) RETURN n} RETURN n",
        "LOAD CSV FROM 'http://example.com' AS x RETURN x",
        "RETURN apoc.load.json('http://example.com')",
        "MATCH(n) RETURN n; MATCH(m) RETURN m",
        "/* hidden */ CREATE(n)",
        "EXPLAIN CREATE(n)",
        "SHOW USERS",
        "RETURN untrustedFunction()",
        "MATCH(n) RETURN 'unterminated",
        "MATCH(n) /* unterminated",
        "MATCH(n) RETURN n LIMIT 1 // comment",
    ):
        with pytest.raises(ValueError):
            validate_query(query)


@pytest.mark.parametrize(
    "query",
    [
        "RETURN `untrustedFunction`()",
        "RETURN `apoc`.`version`()",
        "RETURN apoc.`version`()",
        "RETURN `apoc`.version()",
        "RETURN `apoc`.count()",
        "RETURN apoc.`version` ()",
        "RETURN `apoc` . `version` ()",
        "RETURN apoc.text.`join`([])",
        "RETURN `count`(*)",
        "RETURN `untrusted``Function`()",
    ],
)
def test_quoted_function_calls_are_rejected_before_database_access(query):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_queries import GraphQueryService

    driver, transaction = _driver_fixture(query_type="r")
    factory = MagicMock(return_value=driver)
    with pytest.raises(ValueError):
        GraphQueryService(driver_factory=factory).query(query, {})
    factory.assert_not_called()
    transaction.run.assert_not_called()


@pytest.mark.parametrize(
    "query",
    [
        "MATCH(n:`Odd label`) RETURN n.`name`",
        "MATCH(n:`CREATE`) RETURN n.`CALL`",
        "MATCH(n:`Odd``label`) RETURN n.`na``me`",
        "RETURN '`untrustedFunction`()' AS text",
        'RETURN "`apoc`.`version`()" AS text',
        "RETURN '`apoc`' + '.version()' AS text",
    ],
)
def test_quoted_identifiers_and_literal_function_text_are_preserved(query):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_queries import validate_query

    assert validate_query(query) == query


def _driver_fixture(query_type="r", records=None):
    driver = MagicMock()
    session = driver.__enter__.return_value.session.return_value.__enter__.return_value
    transaction = session.begin_transaction.return_value.__enter__.return_value
    explained = MagicMock()
    explained.consume.return_value.query_type = query_type
    result = MagicMock()
    result.keys.return_value = ["name"]
    result.fetch.return_value = records or [{"name": "existing-scene"}]
    transaction.run.side_effect = [explained, result]
    return driver, transaction


def test_query_service_checks_explain_and_never_commits_or_exceeds_row_limit():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_queries import GraphQueryService

    driver, transaction = _driver_fixture(records=[{"name": str(i)} for i in range(201)])
    service = GraphQueryService(driver_factory=lambda: driver)
    result = service.query("MATCH(n) RETURN n.name AS name", {})
    assert result["columns"] == ["name"]
    assert len(result["rows"]) == 200
    assert result["truncated"] is True
    assert result["read_only"] is True
    assert transaction.run.call_args_list[0].args[0].startswith("EXPLAIN ")
    transaction.rollback.assert_called_once()
    transaction.commit.assert_not_called()


def test_query_service_refuses_non_read_compiler_classification_before_execution():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_queries import GraphQueryService

    driver, transaction = _driver_fixture(query_type="rw")
    with pytest.raises(ValueError, match="read-only"):
        GraphQueryService(driver_factory=lambda: driver).query("MATCH(n) RETURN n", {})
    assert transaction.run.call_count == 1
    transaction.rollback.assert_called_once()
    transaction.commit.assert_not_called()


def test_query_result_preserves_actual_graph_identity_and_redacts_sensitive_properties():
    import json

    from neo4j.graph import Graph, Node

    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_queries import GraphQueryService

    graph = Graph()
    first = Node(graph, "node-a", 1, ["EnvironmentGraph"], {"name": "scene-a", "api_key": "test-only"})
    second = Node(graph, "node-b", 2, ["Object"], {"name": "apple"})
    relation = graph.relationship_type("CONTAINS_OBJECT")(graph, "edge-a", 3, {"weight": 1})
    relation._start_node = first
    relation._end_node = second
    driver, transaction = _driver_fixture(records=[{"name": [first, relation, second, first]}])
    result = GraphQueryService(driver_factory=lambda: driver).query("MATCH(n) RETURN n AS name", {})
    nodes = {node["id"]: node for node in result["graph"]["nodes"]}
    assert set(nodes) == {"node-a", "node-b"}
    assert nodes["node-a"]["label"] == "scene-a"
    assert nodes["node-a"]["properties"]["api_key"] == "[redacted]"
    assert result["graph"]["edges"] == [{
        "id": "edge-a",
        "source": "node-a",
        "target": "node-b",
        "label": "CONTAINS_OBJECT",
        "properties": {"weight": 1},
    }]
    encoded = json.dumps(result, allow_nan=False)
    assert "test-only" not in encoded
    transaction.rollback.assert_called_once()


def test_large_nested_query_values_are_bounded_and_flagged():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_queries import GraphQueryService

    driver, _ = _driver_fixture(records=[{"name": list(range(1000))}])
    result = GraphQueryService(driver_factory=lambda: driver).query("RETURN range(0,999) AS name", {})
    assert len(result["rows"][0][0]) <= 257
    assert result["truncated"] is True


def test_projection_budget_exhaustion_is_a_truncated_result_not_a_server_error():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_queries import GraphQueryService

    driver, _ = _driver_fixture(records=[{"name": list(range(256))} for _ in range(100)])
    result = GraphQueryService(driver_factory=lambda: driver).query("RETURN 1 AS name", {})
    assert len(result["rows"]) == 100
    assert result["rows"][-1] == ["[truncated]"]
    assert result["truncated"] is True


@pytest.mark.parametrize("stage", ["explain_run", "explain_consume", "run", "fetch", "serialization"])
def test_query_service_rolls_back_on_errors(stage):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_queries import GraphQueryService

    class Unserializable:
        def __str__(self):
            raise RuntimeError("serialization failed")

    driver, transaction = _driver_fixture(records=[{"name": Unserializable()}])
    explained = MagicMock()
    explained.consume.return_value.query_type = "r"
    records = MagicMock()
    records.keys.return_value = ["name"]
    records.fetch.return_value = [{"name": Unserializable()}]
    error = RuntimeError(f"{stage} failed")
    if stage == "explain_run":
        transaction.run.side_effect = error
    else:
        transaction.run.side_effect = [explained, error if stage == "run" else records]
    if stage == "explain_consume":
        explained.consume.side_effect = error
    if stage == "fetch":
        records.fetch.side_effect = error

    with pytest.raises(RuntimeError, match=f"{stage} failed"):
        GraphQueryService(driver_factory=lambda: driver).query("RETURN 1 AS name", {})
    assert transaction.run.call_count == (1 if stage.startswith("explain") else 2)
    transaction.rollback.assert_called_once()
    transaction.commit.assert_not_called()


@pytest.mark.parametrize("container_type", [list, tuple, set, frozenset])
def test_projection_only_iterates_the_retained_collection_prefix(container_type):
    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_projection import GraphProjection

    class LimitedIteration(container_type):
        def __iter__(self):
            for index, item in enumerate(super().__iter__()):
                assert index < 256, "projection consumed discarded collection entries"
                yield item

    projection = GraphProjection()
    result = projection.value(LimitedIteration(range(1000)))
    assert len(result) == 256
    assert all(isinstance(item, int) for item in result)
    assert projection.truncated is True


def test_projection_only_iterates_the_retained_mapping_prefix():
    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_projection import GraphProjection

    class LimitedItems(dict):
        def items(self):
            for index, entry in enumerate(super().items()):
                assert index < 256, "projection consumed discarded mapping entries"
                yield entry

    projection = GraphProjection()
    result = projection.value(LimitedItems((str(i), i) for i in range(1000)))
    assert result == {str(i): i for i in range(256)}
    assert projection.truncated is True


def test_projection_does_not_copy_whole_path_sequences():
    from neo4j.graph import Graph, Node, Path

    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_projection import GraphProjection

    class LimitedTuple(tuple):
        def __iter__(self):
            for index, item in enumerate(super().__iter__()):
                assert index < 256, "projection consumed discarded path entries"
                yield item

    class CheckedPath(Path):
        @property
        def nodes(self):
            return LimitedTuple(super().nodes)

        @property
        def relationships(self):
            return LimitedTuple(super().relationships)

    graph = Graph()
    node = Node(graph, "node-a", 1, ["Object"], {})
    edge = graph.relationship_type("LINK")(graph, "edge-a", 2, {})
    edge._start_node = node
    edge._end_node = node
    projection = GraphProjection()
    result = projection.value(CheckedPath(node, *([edge] * 300)))
    assert len(result["nodes"]) == 256
    assert len(result["edges"]) == 256
    assert {item["id"] for item in result["nodes"]} == {"node-a"}
    assert {item["id"] for item in result["edges"]} == {"edge-a"}
    assert projection.truncated is True


def test_graph_routes_require_session_and_csrf_and_return_live_service_results():
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_queries import GraphQueryService, router

    app = FastAPI()
    app.state.origin = "http://testserver"
    app.state.browser_origins = {"testserver": "http://testserver"}
    app.state.cookie_name = "test-session"
    app.state.sessions = SimpleNamespace(
        get=lambda token: {"csrf_token": "test-csrf"} if token == "test-session" else None
    )
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/api/graph/examples").status_code == 401
        client.cookies.set("test-session", "test-session")
        assert client.get("/api/graph/examples").status_code == 200
        assert client.post("/api/graph/query", json={"query": "RETURN 1", "params": {}}).status_code == 403
        headers = {"Origin": "http://testserver", "X-CSRF-Token": "test-csrf"}
        with patch.object(GraphQueryService, "query", return_value={"columns": ["n"], "rows": [[1]]}):
            assert client.get("/api/graph/status").json()["available"] is True
            response = client.post("/api/graph/query", headers=headers, json={"query": "RETURN 1 AS n", "params": {}})
            assert response.status_code == 200
            assert response.json()["rows"] == [[1]]
        with patch.object(GraphQueryService, "query", side_effect=RuntimeError("private connection detail")):
            response = client.get("/api/graph/status")
            assert response.json()["available"] is False
            assert "private connection detail" not in response.text
