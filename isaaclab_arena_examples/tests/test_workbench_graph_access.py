# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Graph profile configuration never reads credential files or probes the network."""

import pytest

from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_access import (
    checked_graph_config,
    configuration,
    retrieve_snapshot,
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for key in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE"):
        monkeypatch.delenv(key, raising=False)


def test_no_default_database_or_credential_fallback(monkeypatch):
    assert configuration() is None
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7688")
    monkeypatch.setenv("NEO4J_USER", "test-user")
    assert configuration() is None
    monkeypatch.setenv("NEO4J_PASSWORD", "synthetic-graph-secret")
    assert configuration() == {
        "uri": "bolt://localhost:7688",
        "user": "test-user",
        "password": "synthetic-graph-secret",
        "database": "neo4j",
    }


@pytest.mark.parametrize(
    "uri",
    [
        "file:///tmp/x",
        "https://localhost",
        "bolt://name:secret@localhost",
        "bolt://localhost?x=1",
        "bolt://localhost/#fragment",
    ],
)
def test_rejects_unsafe_graph_configuration(uri):
    with pytest.raises(ValueError, match="Invalid graph configuration"):
        checked_graph_config({"uri": uri, "user": "u", "password": "synthetic-graph-secret", "database": "neo4j"})


def test_returns_detached_only_explicit_configuration():
    value = {
        "uri": "neo4j+s://example.invalid",
        "user": "u",
        "password": "synthetic-graph-secret",
        "database": "research",
    }
    checked = checked_graph_config(value)
    assert checked == value and checked is not value
    with pytest.raises(ValueError):
        checked_graph_config({**value, "raw_driver_args": {}})
    with pytest.raises(ValueError):
        checked_graph_config({**value, "database": value["password"]})


@pytest.mark.parametrize("database", ["   ", "\u00a0\u2003", "\u0085"])
def test_blank_database_cannot_authorize_transport_invalid_destination(database):
    config = {"uri": "bolt://localhost:7688", "user": "u", "password": "synthetic-graph-secret", "database": database}
    with pytest.raises(ValueError, match="Invalid graph configuration"):
        checked_graph_config(config)


@pytest.mark.parametrize("database", [" research.db ", "研究.db"])
def test_database_identity_is_not_trimmed(database):
    config = {"uri": "bolt://localhost:7688", "user": "u", "password": "synthetic-graph-secret", "database": database}
    assert checked_graph_config(config)["database"] == database


def test_retrieval_owns_driver_and_never_uses_default_database():
    calls = []

    class Driver:
        def session(self, **kwargs):
            calls.append(kwargs)
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def run(self, *args, **kwargs):
            return []

        def close(self):
            calls.append("closed")

    config = {"uri": "bolt://localhost:7688", "user": "u", "password": "synthetic-graph-secret", "database": "research"}
    result = retrieve_snapshot("Droid on a table", config, driver_factory=lambda **kwargs: Driver())
    assert result["status"] == "empty"
    assert calls[0]["database"] == "research"
    assert calls[-1] == "closed"


def test_unconfigured_or_failed_retrieval_does_not_disclose_credentials():
    def failed(**kwargs):
        raise RuntimeError("synthetic-graph-secret")

    result = retrieve_snapshot("Droid", None, driver_factory=failed)
    assert result["warnings"] == ["unconfigured"]
    result = retrieve_snapshot(
        "Droid",
        {
            "uri": "bolt://localhost:7688",
            "user": "u",
            "password": "synthetic-graph-secret",
            "database": "research",
        },
        driver_factory=failed,
    )
    assert result["status"] == "unavailable"
    assert result["timing"]["source"] == "local_monotonic"
    assert result["timing"]["elapsed_seconds"] >= 0
    assert result["effective_settings"]["connection_timeout_seconds"] == 3
    assert result["effective_settings"]["connection_acquisition_timeout_seconds"] == 5
    assert result["effective_settings"]["max_transaction_retry_time_seconds"] == 0
    assert "synthetic-graph-secret" not in str(result)
