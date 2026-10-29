# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Legacy retrieval cleanup vetoes, exercised without live transports."""

import pytest

from isaaclab_arena.agentic_environment_generation import graph_rag
from isaaclab_arena.agentic_environment_generation.graph_cleanup import GraphCleanupError
from isaaclab_arena.tests.test_graph_rag_snapshot import Driver, deny_transports, measured_row  # noqa: F401

HOSTILE = "bolt://user:private-password@private-host secret-query\nFORGED diagnostic"


class LegacyDriver(Driver):
    def __init__(self, *, query_fails=False, cleanup_fails=False):
        super().__init__(OSError(HOSTILE) if query_fails else [measured_row()])
        self.cleanup_fails = cleanup_fails
        self.exits = []

    def __exit__(self, *exc):
        self.exits.append(exc)
        if self.cleanup_fails:
            raise OSError(HOSTILE)


@pytest.mark.parametrize("query_fails", [False, True])
def test_legacy_cleanup_veto(query_fails, caplog):
    driver = LegacyDriver(query_fails=query_fails, cleanup_fails=True)
    with pytest.raises(GraphCleanupError, match="Graph retrieval cleanup failed") as caught:
        graph_rag.GraphRAGRetriever(driver).retrieve_prior_subgraphs("g1 table")
    assert len(driver.exits) == len(driver.calls) == 1
    assert HOSTILE not in str(caught.value)
    assert HOSTILE not in caplog.text


def controlled_agent(monkeypatch):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import EnvironmentGenerationAgent

    # Keep the actual generate_spec path; replace only model IO and supply catalogues.
    agent = EnvironmentGenerationAgent.__new__(EnvironmentGenerationAgent)
    calls = []

    def infer(prompt, traces, **kwargs):
        calls.append(prompt)
        return None, {"controlled": True}

    agent.spec_inference = SimpleNamespace(infer=infer)
    agent.inference_backend = SimpleNamespace(model="offline", telemetry=None)
    return agent, calls


def generate(agent, **kwargs):
    return agent.generate_spec(
        "g1 table",
        asset_catalog=object(),
        relation_catalog=object(),
        task_catalog=object(),
        publish_to_graph=False,
        **kwargs,
    )


@pytest.mark.parametrize("query_fails", [False, True])
def test_actual_agent_cleanup_veto_after_positive_control(monkeypatch, caplog, query_fails):
    agent, calls = controlled_agent(monkeypatch)
    driver = LegacyDriver()
    monkeypatch.setattr(graph_rag, "get_neo4j_driver", lambda: driver)
    assert generate(agent) == (None, {"controlled": True})
    assert len(calls) == 1 and "scene" in calls[0]
    assert len(driver.exits) == 1
    calls.clear()
    driver = LegacyDriver(query_fails=query_fails, cleanup_fails=True)
    stages = []
    with pytest.raises(GraphCleanupError, match="cleanup"):
        generate(agent, progress=stages.append)
    assert calls == []
    assert "spec_inference" not in stages
    assert len(driver.exits) == 1
    assert HOSTILE not in caplog.text + "\n".join(agent.traces)


def test_query_unavailable_falls_back_without_hostile_diagnostics(monkeypatch, caplog):
    agent, calls = controlled_agent(monkeypatch)
    driver = LegacyDriver(query_fails=True)
    monkeypatch.setattr(graph_rag, "get_neo4j_driver", lambda: driver)
    assert generate(agent) == (None, {"controlled": True})
    assert calls == ["g1 table"]
    assert len(driver.exits) == 1 and driver.exits[0][0] is OSError
    assert HOSTILE not in caplog.text + "\n".join(agent.traces)
    assert "Graph-RAG unavailable; continuing without priors." in caplog.text


def test_generic_agent_retrieval_fallback_sanitizes_trace(monkeypatch, caplog):
    agent, calls = controlled_agent(monkeypatch)

    def unavailable(*args, **kwargs):
        raise OSError(HOSTILE)

    monkeypatch.setattr(graph_rag.GraphRAGRetriever, "retrieve_prior_subgraphs", unavailable)
    assert generate(agent) == (None, {"controlled": True})
    assert calls == ["g1 table"]
    assert HOSTILE not in caplog.text + "\n".join(agent.traces)
    assert agent.traces == ("[GraphRAG] Prior retrieval unavailable; continuing without priors.",)


@pytest.mark.parametrize("prior_context", ["", "injected exact prior"])
def test_injected_prior_bypasses_legacy_retrieval(monkeypatch, prior_context):
    agent, calls = controlled_agent(monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("Injected prior must bypass legacy retrieval")

    monkeypatch.setattr(graph_rag, "GraphRAGRetriever", forbidden)
    assert generate(agent, prior_context=prior_context) == (None, {"controlled": True})
    assert calls == ["g1 table" + ("\n\n" + prior_context if prior_context else "")]
