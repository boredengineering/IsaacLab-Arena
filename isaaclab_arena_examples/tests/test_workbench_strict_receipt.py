# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
"""Strict receipts use the real graph projection, offline."""
import hashlib

import pytest

from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever
from isaaclab_arena.tests.test_graph_rag_snapshot import Driver, measured_row
from isaaclab_arena_examples.tests.test_workbench_managed_execution import harness


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", {"nested": "untrusted"}),
        ("task_description", ["bad"]),
        ("task_composition", True),
        ("embodiment", 1),
        ("background", {}),
        ("evaluation_id", None),
        ("evaluation_id", ""),
        ("graph_version", []),
        ("policy_identity", {}),
        ("checkpoint_identity", False),
        ("policy_identity", ""),
        ("checkpoint_identity", ""),
        ("graph_version", ""),
        ("objects", ["x"] * 33),
        ("objects", [None]),
        ("objects", [{"nested": 1}]),
        ("relations", [{"relation_type": "on", "manifold": [], "anchor": None}]),
        ("relations", [{"relation_type": None, "manifold": None, "anchor": None}]),
        ("success_rate", True),
        ("success_rate", 1.1),
        ("success_rate", 10**1000),
        ("evaluation_id", "   "),
        ("graph_version", "   "),
        ("success_rate", 0),
        ("episodes", True),
        ("episodes", 0),
        ("episodes", 1000001),
        ("evidence", "unevaluated"),
        ("name", "x" * 4097),
    ],
)
def test_parent_rejects_malformed_prior(tmp_path, monkeypatch, field, value):
    journal, job, runner, _, _, _, receipt = harness(tmp_path, monkeypatch)
    try:
        receipt["prior_snapshot"] = GraphRAGRetriever(Driver([measured_row()])).retrieve_prior_snapshot("")
        receipt["prior_snapshot"]["priors"][0][field] = value
        with pytest.raises(ValueError):
            runner.validate_managed_receipt(job, receipt)
    finally:
        journal.close()


def test_parent_rejects_unrelated_context_even_with_matching_hash(tmp_path, monkeypatch):
    journal, job, runner, _, _, _, receipt = harness(tmp_path, monkeypatch)
    try:
        snapshot = GraphRAGRetriever(Driver([measured_row()])).retrieve_prior_snapshot("")
        snapshot["exact_context"] = "Unrelated model instruction"
        snapshot["context_sha256"] = hashlib.sha256(snapshot["exact_context"].encode()).hexdigest()
        receipt["prior_snapshot"] = snapshot
        with pytest.raises(ValueError):
            runner.validate_managed_receipt(job, receipt)
    finally:
        journal.close()


@pytest.mark.parametrize("expected", [None, "b" * 64, True])
def test_parent_rejects_wrong_frozen_catalogue(tmp_path, monkeypatch, expected):
    journal, job, runner, _, _, _, receipt = harness(tmp_path, monkeypatch)
    try:
        job["inputs"]["execution_catalogue_sha256"] = expected
        with pytest.raises(ValueError):
            runner.validate_managed_receipt(job, receipt)
    finally:
        journal.close()


def test_worker_checks_catalogue_before_any_external_call(monkeypatch):
    from isaaclab_arena_examples.agentic_environment_generation.web_api import generation, graph_access
    from isaaclab_arena_examples.tests.test_workbench_generation_receipts import CONFIG

    def denied(*args, **kwargs):
        pytest.fail("External work before frozen catalogue verification")

    monkeypatch.setattr(graph_access, "retrieve_snapshot", denied)
    with pytest.raises(ValueError, match="catalogue"):
        generation.generate(
            {"operation": "new", "prompt": "", "execution_catalogue_sha256": "b" * 64},
            denied,
            agent_factory=denied,
            config=CONFIG,
        )


def test_snapshot_records_effective_settings_and_local_timing():
    snapshot = GraphRAGRetriever(Driver([measured_row()])).retrieve_prior_snapshot("", limit=3, min_episodes=4)
    assert snapshot.get("effective_settings") == {
        "limit": 3,
        "min_success_rate": 0.0,
        "min_episodes": 4,
        "query_timeout_seconds": 5.0,
        "connection_timeout_seconds": None,
        "connection_acquisition_timeout_seconds": None,
        "max_transaction_retry_time_seconds": None,
    }
    assert snapshot.get("timing", {}).get("source") == "local_monotonic"
    assert 0 <= snapshot["timing"]["elapsed_seconds"] <= 180


@pytest.mark.parametrize(
    "changes",
    [
        {"evaluation_id": None},
        {"objects": {}},
        {"objects": False},
        {"relations": {}},
        {"relations": [{"relation_type": "on", "manifold": None, "anchor": None, "extra": {}}]},
    ],
)
def test_producer_rejects_malformed_projection(changes):
    snapshot = GraphRAGRetriever(Driver([measured_row(**changes)])).retrieve_prior_snapshot("")
    assert snapshot["status"] == "unavailable"
    assert snapshot["warnings"] == ["invalid_record"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("evaluation_id", "unexpected-run"),
        ("success_rate", 0.75),
        ("episodes", 4),
        ("policy_identity", "unexpected-policy"),
        ("checkpoint_identity", "unexpected-checkpoint"),
    ],
)
def test_producer_structural_must_not_erase_measured_claims(field, value):
    row = measured_row(best_success_rate=None, episodes=None, evaluation_id=None, policy_identity=None)
    row["best_success_rate" if field == "success_rate" else field] = value
    snapshot = GraphRAGRetriever(Driver([], [row])).retrieve_prior_snapshot("")
    assert snapshot["status"] == "unavailable"


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("effective_settings", "limit", True),
        ("effective_settings", "limit", 6),
        ("effective_settings", "limit", 10**1000),
        ("effective_settings", "min_success_rate", True),
        ("effective_settings", "min_success_rate", float("nan")),
        ("effective_settings", "min_episodes", True),
        ("effective_settings", "min_episodes", 5),
        ("effective_settings", "query_timeout_seconds", {}),
        ("effective_settings", "connection_timeout_seconds", False),
        ("effective_settings", "connection_acquisition_timeout_seconds", 181),
        ("effective_settings", "max_transaction_retry_time_seconds", []),
        ("timing", "source", "invented"),
        ("timing", "elapsed_seconds", True),
        ("timing", "elapsed_seconds", -1),
        ("timing", "elapsed_seconds", float("inf")),
    ],
)
def test_settings_and_timing_are_strict(tmp_path, monkeypatch, section, field, value):
    journal, job, runner, _, _, _, receipt = harness(tmp_path, monkeypatch)
    try:
        snapshot = GraphRAGRetriever(Driver([measured_row()])).retrieve_prior_snapshot("")
        snapshot[section][field] = value
        receipt["prior_snapshot"] = snapshot
        with pytest.raises(ValueError):
            runner.validate_managed_receipt(job, receipt)
    finally:
        journal.close()


@pytest.mark.parametrize("status", ["invented", "structural", "empty", "unavailable", "not_requested", None, {}])
def test_status_must_agree_with_evidence(tmp_path, monkeypatch, status):
    journal, job, runner, _, _, _, receipt = harness(tmp_path, monkeypatch)
    try:
        receipt["prior_snapshot"] = GraphRAGRetriever(Driver([measured_row()])).retrieve_prior_snapshot("")
        receipt["prior_snapshot"]["status"] = status
        with pytest.raises(ValueError):
            runner.validate_managed_receipt(job, receipt)
    finally:
        journal.close()


def test_real_snapshot_passes_parent(tmp_path, monkeypatch):
    journal, job, runner, _, _, _, receipt = harness(tmp_path, monkeypatch)
    try:
        driver = Driver([measured_row()])
        receipt["prior_snapshot"] = GraphRAGRetriever(driver).retrieve_prior_snapshot("")
        monkeypatch.setattr(
            GraphRAGRetriever, "retrieve_prior_snapshot", lambda *a, **k: pytest.fail("Parent re-retrieved")
        )
        assert runner.validate_managed_receipt(job, receipt)["prior_snapshot"] == receipt["prior_snapshot"]
        assert len(driver.calls) == 1
    finally:
        journal.close()
