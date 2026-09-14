# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Modern worker consumes exactly one captured prior context, without external work."""

import io
import json
import os
import sys
import yaml
from types import SimpleNamespace

import pytest

from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.tests.test_graph_rag_snapshot import Driver, measured_row
from isaaclab_arena_examples.agentic_environment_generation.web_api import generation, graph_access
from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import execution_catalogue_sha256
from isaaclab_arena_examples.tests.test_workbench_editor import FIXTURE

CONFIG = {"api_key": "synthetic-worker-model-secret", "model": "test-model", "base_url": "https://api.openai.com/v1"}


def test_new_consumes_exact_snapshot_and_catalogue_once(monkeypatch):
    seen = []
    snapshot = GraphRAGRetriever(Driver([measured_row()])).retrieve_prior_snapshot("Droid on table")
    context = snapshot["exact_context"]

    def retrieve(prompt, config):
        seen.append((prompt, config))
        return snapshot

    monkeypatch.setattr(graph_access, "retrieve_snapshot", retrieve)

    class Agent:
        telemetry = SimpleNamespace(converged=True)

        def __init__(self, **kwargs):
            pass

        def generate_spec(self, prompt, **kwargs):
            assert kwargs["prior_context"] == context
            assert kwargs["publish_to_graph"] is False
            assert kwargs["asset_catalog"].objects
            assert kwargs["task_catalog"].tasks
            return ArenaEnvGraphSpec.from_dict(yaml.safe_load(FIXTURE.read_text())), None

    result = generation.generate(
        {
            "operation": "new",
            "prompt": "Droid on table",
            "retrieval_policy": "allow_fallback",
            "execution_catalogue_sha256": execution_catalogue_sha256(),
        },
        lambda stage: None,
        agent_factory=Agent,
        config=CONFIG,
        graph_config=None,
    )
    assert seen == [("Droid on table", None)]
    assert result["operation"] == "new"
    assert result["prior_snapshot"] == snapshot
    assert len(result["catalogue_sha256"]) == 64
    assert result["validation"]["valid"] is True


@pytest.mark.parametrize("failure", ["query", "network", "cleanup"])
@pytest.mark.parametrize("policy", ["allow_fallback", "require_service"])
def test_real_retrieval_availability_policy_never_overrides_cleanup(monkeypatch, failure, policy):
    from isaaclab_arena.agentic_environment_generation import lpg_neo4j_sync
    from isaaclab_arena.agentic_environment_generation.graph_cleanup import GraphCleanupError

    driver = Driver(OSError("private-query-secret"))
    closed = []
    seen = []

    def close():
        closed.append(True)
        if failure == "cleanup":
            raise OSError("private-cleanup-secret")

    driver.close = close

    def factory(**kwargs):
        if failure == "network":
            raise OSError("private-network-secret")
        return driver

    monkeypatch.setattr(lpg_neo4j_sync, "get_neo4j_driver", factory)

    class Agent:
        telemetry = SimpleNamespace(converged=True)

        def __init__(self, **kwargs):
            seen.append("constructed")

        def generate_spec(self, prompt, **kwargs):
            seen.append(kwargs["prior_context"])
            assert kwargs["publish_to_graph"] is False
            return ArenaEnvGraphSpec.from_dict(yaml.safe_load(FIXTURE.read_text())), None

    def generate():
        return generation.generate(
            {
                "operation": "new",
                "prompt": "Droid",
                "retrieval_policy": policy,
                "execution_catalogue_sha256": execution_catalogue_sha256(),
            },
            lambda stage: None,
            config=CONFIG,
            graph_config={
                "uri": "bolt://graph.invalid",
                "user": "reader",
                "password": "reader-secret",
                "database": "research",
            },
            agent_factory=Agent,
        )

    if failure == "cleanup":
        with pytest.raises(GraphCleanupError, match="cleanup"):
            generate()
        assert not seen
    elif policy == "require_service":
        with pytest.raises(ValueError, match="Required graph retrieval unavailable"):
            generate()
        assert not seen
    else:
        result = generate()
        assert result["prior_snapshot"]["status"] == "unavailable"
        assert result["prior_snapshot"]["warnings"] == ["retrieval_failed"]
        assert seen == ["constructed", ""]
        assert "private-" not in str(result)
    assert closed == ([] if failure == "network" else [True])


def test_registry_change_after_capture_fails_before_graph_or_agent(monkeypatch):
    from dataclasses import replace

    from isaaclab_arena.agentic_environment_generation import environment_generation_agent as module
    from isaaclab_arena_examples.agentic_environment_generation.web_api.catalogues import catalogue_snapshot

    frozen = execution_catalogue_sha256()
    assert frozen == catalogue_snapshot()["catalogue_sha256"]
    tasks = module.build_task_catalogue()
    monkeypatch.setattr(module, "build_task_catalogue", lambda: replace(tasks, tasks=[]))

    def denied(*args, **kwargs):
        pytest.fail("Changed catalogue reached external work")

    monkeypatch.setattr(graph_access, "retrieve_snapshot", denied)
    with pytest.raises(ValueError, match="catalogue"):
        generation.generate(
            {"operation": "new", "prompt": "offline", "execution_catalogue_sha256": frozen},
            lambda s: None,
            agent_factory=denied,
            config=CONFIG,
        )


def test_refine_never_retrieves_and_passes_parent(monkeypatch, tmp_path):
    from isaaclab_arena.agentic_environment_generation.workbench.documents import Documents
    from isaaclab_arena_examples.agentic_environment_generation.web_api.editor_execution import EditorExecution

    monkeypatch.setattr(graph_access, "retrieve_snapshot", lambda *a: pytest.fail("Refinement requested retrieval"))

    class Agent:
        telemetry = SimpleNamespace(converged=True)

        def __init__(self, **kwargs):
            assert set(kwargs) == {"api_key", "model", "base_url", "max_tokens", "max_retries", "load_dotenv"}

        def refine_spec(self, spec, prompt, **kwargs):
            return spec, None

    inputs = {
        "operation": "refine",
        "prompt": "Keep objects",
        "base_yaml": FIXTURE.read_text(),
        "execution_catalogue_sha256": execution_catalogue_sha256(),
    }
    result = generation.generate(inputs, lambda s: None, agent_factory=Agent, config=CONFIG)
    assert result["prior_snapshot"]["status"] == "not_requested"
    runner = EditorExecution.__new__(EditorExecution)
    runner.documents = Documents(tmp_path)
    assert runner.validate_managed_receipt({"inputs": inputs}, result)["prior_snapshot"] == result["prior_snapshot"]


def test_required_service_stops_before_model_initialization(monkeypatch):
    def forbidden(**kwargs):
        pytest.fail("Unavailable required retrieval still initialized a model")

    with pytest.raises(ValueError, match="Required graph retrieval unavailable"):
        generation.generate(
            {
                "operation": "new",
                "prompt": "A2",
                "retrieval_policy": "require_service",
                "execution_catalogue_sha256": execution_catalogue_sha256(),
            },
            lambda stage: None,
            agent_factory=forbidden,
            config=CONFIG,
            graph_config=None,
        )


@pytest.mark.parametrize("invalid", ["missing_digest", "bad_digest", "extra_config"])
def test_modern_worker_rejects_invalid_private_contract(monkeypatch, capsys, invalid):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation_worker

    inputs = {"operation": "new", "prompt": "offline", "execution_catalogue_sha256": execution_catalogue_sha256()}
    config = dict(CONFIG)
    if invalid == "missing_digest":
        inputs.pop("execution_catalogue_sha256")
    elif invalid == "bad_digest":
        inputs["execution_catalogue_sha256"] = True
    else:
        config["arbitrary_nested"] = {"unapproved": "value"}
    envelope = {"inputs": inputs, "config": config, "graph_config": None}
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO((json.dumps(envelope) + "\n").encode())))
    monkeypatch.setattr(sys, "argv", ["worker", "--parent-pid", str(os.getppid())])
    monkeypatch.setattr(generation_worker.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(prctl=lambda *a: 0))
    monkeypatch.setattr(generation, "generate", lambda *a, **k: pytest.fail("Invalid contract reached generation"))
    assert generation_worker.main() == 1
    assert CONFIG["api_key"] not in capsys.readouterr().out


@pytest.mark.parametrize("leak", [None, "model", "graph"])
def test_modern_worker_envelope_protects_both_credentials(monkeypatch, capsys, leak):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation_worker

    graph = {
        "uri": "bolt://localhost:7688",
        "user": "u",
        "password": "synthetic-private-graph-password",
        "database": "research",
    }
    envelope = {
        "inputs": {
            "operation": "new",
            "prompt": "No real inference",
            "execution_catalogue_sha256": execution_catalogue_sha256(),
        },
        "config": CONFIG,
        "graph_config": graph,
    }
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO((json.dumps(envelope) + "\n").encode())))
    monkeypatch.setattr(sys, "argv", ["worker", "--parent-pid", str(os.getppid())])
    monkeypatch.setattr(generation_worker.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(prctl=lambda *a: 0))
    seen = []

    def fake_generate(inputs, emit, *, config, graph_config):
        seen.append(graph_config)
        return {"value": CONFIG["api_key"] if leak == "model" else graph["password"] if leak == "graph" else "safe"}

    monkeypatch.setattr(generation, "generate", fake_generate)
    code = generation_worker.main()
    captured = capsys.readouterr()
    assert seen == [graph]
    assert CONFIG["api_key"] not in captured.out + captured.err
    assert graph["password"] not in captured.out + captured.err
    assert code == (0 if leak is None else 1)
