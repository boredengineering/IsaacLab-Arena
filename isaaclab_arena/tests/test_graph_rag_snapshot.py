# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Offline provenance receipts; no graph, model, or simulation transports."""

import hashlib
import json
import socket

import pytest

from isaaclab_arena.agentic_environment_generation import graph_rag


@pytest.fixture(autouse=True)
def deny_transports(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Unexpected transport or default driver discovery")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(graph_rag, "get_neo4j_driver", denied)


def test_snapshot_requires_constructor_injected_driver():
    retriever = graph_rag.GraphRAGRetriever()
    # Even a driver lazily discovered by legacy retrieval must not configure snapshots.
    retriever._driver = object()
    receipt = retriever.retrieve_prior_snapshot("g1 on table")
    from isaaclab_arena.agentic_environment_generation.prior_receipt import effective_settings

    assert receipt == {
        "effective_settings": effective_settings(),
        "timing": {"source": "not_started", "elapsed_seconds": None},
        "status": "unavailable",
        "derived_filters": {"emb_filter": "g1", "fixture_filter": "table"},
        "priors": [],
        "exact_context": "",
        "context_sha256": hashlib.sha256(b"").hexdigest(),
        "warnings": ["unconfigured"],
    }
    json.dumps(receipt, allow_nan=False)


class Driver:
    def __init__(self, *results):
        self.results = iter(results)
        self.calls = []

    def session(self, **kwargs):
        self.session_options = kwargs
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def run(self, query, **params):
        self.calls.append((query, params))
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return iter(result)


def measured_row(**changes):
    return {
        "name": "scene",
        "task_description": "Pick cube",
        "task_composition": "atomic",
        "embodiment": "g1",
        "background": "table",
        "objects": ["cube"],
        "relations": [],
        "best_success_rate": 0.75,
        "episodes": 4,
        "evaluation_id": "run-four",
        "graph_version": "a" * 64,
        "policy_identity": "policy-one",
        "checkpoint_identity": None,
        "_graph_links": 1,
        "_run_ids": 1,
        "_policies": (
            []
            if changes.get("policy_identity", "policy-one") is None
            else [{"valid_label": True, "identity": changes.get("policy_identity", "policy-one")}]
        ),
        "_controllers": [],
        **changes,
    }


@pytest.mark.parametrize("query_fails", [False, True])
def test_snapshot_session_exit_cleanup_never_returns_receipt(query_fails):
    from isaaclab_arena.agentic_environment_generation.graph_cleanup import GraphCleanupError

    class BrokenExit(Driver):
        def __exit__(self, *args):
            self.exited = True
            raise OSError("private-session-secret")

    driver = BrokenExit(OSError("query unavailable") if query_fails else [measured_row()])
    with pytest.raises(GraphCleanupError, match="cleanup") as caught:
        graph_rag.GraphRAGRetriever(driver).retrieve_prior_snapshot("g1 on table")
    assert driver.exited and len(driver.calls) == 1
    assert "private-session-secret" not in str(caught.value)


def test_snapshot_projects_controller_writer_facts():
    query = graph_rag._SNAPSHOT_EVALUATED_QUERY
    for fact in (
        "MATCH (trial)-[r:BASED_ON_EVALUATION]->(target)",
        "count(r) AS evaluation_links",
        "collect(labels(target)) AS evaluation_labels",
        "trial.id",
        "trial.run_id",
        "trial.env_name",
        "trial.version",
        "trial.variant_id",
        "trial.policy_identity",
        "variant.id",
        "variant.policy_identity",
        "best_ev.policy_identity AS _run_policy",
        "best_ev.env_name AS _run_env_name",
        "best_ev.env_version AS _run_env_version",
    ):
        assert fact in query


def test_present_null_policy_is_not_absence():
    row = measured_row(policy_identity=None, _policies=[{"valid_label": True, "identity": None}])
    assert snapshot_with_optional_provider(row, False)["warnings"] == ["invalid_record"]


def controller_row():
    row = measured_row(checkpoint_identity="checkpoint")
    row.update(_run_policy="policy-one", _run_env_name="scene", _run_env_version="a" * 64)
    row["_controllers"] = [{
        "valid_label": True,
        "trial_id": "run-four",
        "run_id": "run-four",
        "env_name": "scene",
        "env_version": "a" * 64,
        "variant_id": "variant",
        "policy_identity": "policy-one",
        "evaluation_links": 1,
        "evaluation_labels": [["EvaluationRun"]],
        "variants": [{"valid_label": True, "identity": "checkpoint", "id": "variant", "policy_identity": "policy-one"}],
    }]
    return row


@pytest.mark.parametrize("combined", [False, True])
@pytest.mark.parametrize(
    "change",
    [
        {"evaluation_links": 2, "evaluation_labels": [["EvaluationRun"], ["Other"]]},
        {"evaluation_links": 2, "evaluation_labels": [["EvaluationRun"], ["EvaluationRun"]]},
        {"trial_id": "other"},
        {"run_id": "other"},
        {"env_name": "other"},
        {"env_version": "b" * 64},
        {"variant_id": "other"},
        {"policy_identity": "other"},
    ],
)
def test_legacy_controller_metadata_rejected(change, combined):
    row = controller_row()
    row["_controllers"][0].update(change)
    assert snapshot_with_optional_provider(row, combined)["warnings"] == ["invalid_record"]


def snapshot_with_optional_provider(row, combined):
    def provider(*args, **kwargs):
        return []

    provider.database = "authorized"
    return graph_rag.GraphRAGRetriever(Driver([row])).retrieve_prior_snapshot(
        "g1",
        database="authorized" if combined else None,
        managed_selection_provider=provider if combined else None,
    )


@pytest.mark.parametrize("combined", [False, True])
@pytest.mark.parametrize("value", [None, "", " "])
@pytest.mark.parametrize("kind", ["policy", "checkpoint", "variant", "controller_policy"])
def test_present_provenance_requires_identity(combined, value, kind):
    row = controller_row()
    if kind == "policy":
        row["_policies"][0]["identity"] = value
        row["policy_identity"] = value
    else:
        variant = row["_controllers"][0]["variants"][0]
        field = {"checkpoint": "identity", "variant": "id", "controller_policy": "policy_identity"}[kind]
        variant[field] = value
        if kind == "checkpoint":
            row["checkpoint_identity"] = value
    assert snapshot_with_optional_provider(row, combined)["warnings"] == ["invalid_record"]


@pytest.mark.parametrize("combined", [False, True])
@pytest.mark.parametrize(
    "kind",
    [
        "trial",
        "variant",
        "wrong_trial",
        "wrong_variant",
        "missing_checkpoint",
        "missing_policy",
        "run_env",
        "run_version",
        "run_policy",
    ],
)
def test_extra_links_and_missing_or_mismatched_identities(combined, kind):
    row = controller_row()
    trial = row["_controllers"][0]
    if kind in ("trial", "wrong_trial"):
        row["_controllers"].append({**trial, "valid_label": kind == "trial"})
    elif kind in ("variant", "wrong_variant"):
        trial["variants"].append({**trial["variants"][0], "valid_label": kind == "variant"})
    elif kind == "missing_checkpoint":
        del trial["variants"][0]["identity"]
    elif kind == "missing_policy":
        del row["_policies"][0]["identity"]
    else:
        field = {"run_env": "_run_env_name", "run_version": "_run_env_version", "run_policy": "_run_policy"}[kind]
        row[field] = "other"
    assert snapshot_with_optional_provider(row, combined)["warnings"] == ["invalid_record"]


@pytest.mark.parametrize("combined", [False, True])
def test_valid_controller_and_absent_links(combined):
    assert snapshot_with_optional_provider(controller_row(), combined)["status"] == "measured"
    row = measured_row(policy_identity=None)
    assert snapshot_with_optional_provider(row, combined)["status"] == "measured"


def test_measured_snapshot_binds_rate_count_and_provenance_to_same_run():
    driver = Driver([measured_row()])
    receipt = graph_rag.GraphRAGRetriever(driver).retrieve_prior_snapshot("g1 table")
    assert receipt["status"] == "measured"
    prior = receipt["priors"][0]
    assert (prior["success_rate"], prior["episodes"], prior["evaluation_id"]) == (0.75, 4, "run-four")
    assert prior["graph_version"] == "a" * 64
    assert prior["policy_identity"] == "policy-one"
    assert prior["checkpoint_identity"] is None
    assert receipt["context_sha256"] == hashlib.sha256(receipt["exact_context"].encode()).hexdigest()
    query, params = driver.calls[0]
    assert query.timeout == 5.0
    assert params["limit"] == 2
    text = str(query)
    assert "head(collect(ev)) AS best_ev" in text
    for projection in ("best_ev.id AS evaluation_id", "best_ev.success_rate", "best_ev.num_episodes", "e.version"):
        assert projection in text
    assert "USED_POLICY" in text
    assert "LIMIT $limit" in text
    assert len(driver.calls) == 1
    assert driver.session_options == {"default_access_mode": "READ", "fetch_size": 6}


def test_snapshot_query_bounds_payload_and_preserves_unknown_provenance():
    driver = Driver([measured_row(graph_version=None, policy_identity=None)])
    receipt = graph_rag.GraphRAGRetriever(driver).retrieve_prior_snapshot("g1")
    assert receipt["priors"][0]["graph_version"] is None
    query = str(driver.calls[0][0])
    assert "objects[..33] AS objects" in query
    assert "relations[..33] AS relations" in query
    assert "left(e.task_description, 4097) AS task_description" in query


def test_agent_default_none_preserves_legacy_retrieval(monkeypatch):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import EnvironmentGenerationAgent

    driver = Driver([measured_row()])
    monkeypatch.setattr(graph_rag, "get_neo4j_driver", lambda: driver)
    consumed = []

    def infer(prompt, *args, **kwargs):
        consumed.append(prompt)
        return None, {}

    agent = EnvironmentGenerationAgent.__new__(EnvironmentGenerationAgent)
    agent.inference_backend = SimpleNamespace()
    agent.spec_inference = SimpleNamespace(infer=infer)
    agent.generate_spec("prompt", object(), object(), object(), publish_to_graph=False)
    assert len(driver.calls) == 1
    assert "success_rate=0.75 over 4 episode(s)" in consumed[0]


def test_legacy_retrieval_still_returns_legacy_shape():
    driver = Driver([measured_row()])
    priors = graph_rag.GraphRAGRetriever(driver).retrieve_prior_subgraphs("g1 table")
    assert priors[0]["success_rate"] == 0.75
    assert "evaluation_id" not in priors[0]
    assert type(driver.calls[0][0]) is str
    assert driver.calls[0][0] == graph_rag._EVALUATED_PRIORS_QUERY


@pytest.mark.parametrize(
    "results,status,warning",
    [
        (
            ([], [measured_row(best_success_rate=None, episodes=None, evaluation_id=None, policy_identity=None)]),
            "structural",
            None,
        ),
        (([], []), "empty", None),
        ((RuntimeError("neo4j://user:SECRET@host"),), "unavailable", "retrieval_failed"),
        (([measured_row(task_description="password=SECRET")],), "unavailable", "unsafe_record"),
        (([measured_row(task_description="x" * 4097)],), "unavailable", "bounds_exceeded"),
        (([measured_row(objects=["cube"] * 33)],), "unavailable", "bounds_exceeded"),
        (([measured_row(best_success_rate=float("nan"))],), "unavailable", "invalid_record"),
        (([measured_row(episodes=True)],), "unavailable", "invalid_record"),
        (([measured_row(relations=[object()])],), "unavailable", "invalid_record"),
        (([measured_row(task_description="\ud800")],), "unavailable", "unsafe_record"),
        (([measured_row()] * 3,), "unavailable", "bounds_exceeded"),
    ],
)
def test_snapshot_status_and_fail_closed_receipts(results, status, warning):
    receipt = graph_rag.GraphRAGRetriever(Driver(*results)).retrieve_prior_snapshot("g1 table")
    assert receipt["status"] == status
    assert receipt["warnings"] == ([] if warning is None else [warning])
    assert "SECRET" not in json.dumps(receipt, allow_nan=False)
    if status in ("empty", "unavailable"):
        assert receipt["priors"] == []
        assert receipt["exact_context"] == ""
    if status == "structural":
        assert receipt["priors"][0]["evaluation_id"] is None
        assert "never evaluated" not in receipt["exact_context"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 6},
        {"limit": True},
        {"min_success_rate": float("nan")},
        {"min_episodes": -1},
        {"prompt": "x" * 16385},
    ],
)
def test_snapshot_invalid_bounds_never_query(kwargs):
    driver = Driver()
    receipt = graph_rag.GraphRAGRetriever(driver).retrieve_prior_snapshot(**{"prompt": "g1", **kwargs})
    assert receipt["status"] == "unavailable"
    assert receipt["warnings"] == ["invalid_request"]
    assert driver.calls == []


@pytest.mark.parametrize("supplied", ["", "snapshot"])
def test_agent_consumes_exact_snapshot_without_second_query(monkeypatch, supplied):
    from types import SimpleNamespace

    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import EnvironmentGenerationAgent

    receipt = graph_rag.GraphRAGRetriever(Driver([measured_row()])).retrieve_prior_snapshot("g1")
    context = receipt["exact_context"] if supplied else ""
    consumed = []

    def infer(prompt, *args, **kwargs):
        consumed.append(prompt)
        return None, {}

    def denied(*args, **kwargs):
        pytest.fail("Supplied context must not construct a retriever")

    monkeypatch.setattr(graph_rag, "GraphRAGRetriever", denied)
    agent = EnvironmentGenerationAgent.__new__(EnvironmentGenerationAgent)
    agent.inference_backend = SimpleNamespace()
    agent.spec_inference = SimpleNamespace(infer=infer)
    assert agent.generate_spec(
        "prompt", object(), object(), object(), publish_to_graph=False, prior_context=context
    ) == (None, {})
    assert consumed == ["prompt" + ("\n\n" + context if context else "")]
    if supplied:
        assert hashlib.sha256(consumed[0][len("prompt\n\n") :].encode()).hexdigest() == receipt["context_sha256"]
