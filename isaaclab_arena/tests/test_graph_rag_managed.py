# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Offline managed selection injection and legacy scope isolation."""

import hashlib
import json

import pytest

from isaaclab_arena.agentic_environment_generation import graph_rag
from isaaclab_arena.tests.test_graph_rag_snapshot import Driver, deny_transports, measured_row  # noqa: F401


@pytest.mark.parametrize("database", [None, "other"])
def test_combined_database_missing_or_mismatch_never_queries(database):
    driver = Driver([])
    calls = []

    def provider(*args, **kwargs):
        calls.append(kwargs)
        return []

    provider.database = "authorized"
    receipt = graph_rag.GraphRAGRetriever(driver).retrieve_prior_snapshot(
        "g1", database=database, managed_selection_provider=provider
    )
    assert receipt["warnings"] == ["invalid_request"]
    assert not driver.calls and not calls


def test_callback_without_explicit_database_never_queries():
    driver = Driver([], [])
    calls = []

    def provider(*args, **kwargs):
        calls.append(kwargs)
        return []

    receipt = graph_rag.GraphRAGRetriever(driver).retrieve_prior_snapshot(
        "g1", database="authorized", managed_selection_provider=provider
    )
    assert receipt["warnings"] == ["invalid_request"]
    assert not driver.calls and not calls


def test_combined_sessions_ignore_home_database():
    driver = Driver([], [])

    def provider(injected, **kwargs):
        assert injected is driver
        return []

    provider.database = "authorized"
    receipt = graph_rag.GraphRAGRetriever(driver).retrieve_prior_snapshot(
        "g1", database="authorized", managed_selection_provider=authorized(provider)
    )
    assert receipt["status"] == "empty"
    assert driver.session_options["database"] == "authorized"


def authorized(provider):
    provider.database = "authorized"
    return provider


def proof():
    payload = json.dumps({"env_name": "scene"}, sort_keys=True, separators=(",", ":"))
    return {"name": "scene", "sha256": hashlib.sha256(payload.encode()).hexdigest(), "spec_json": payload}


def test_managed_global_top_five_after_full_bounded_fetch():
    rows = [
        measured_row(name=name, evaluation_id=name, background="z" if name == "a" else "a")
        for name in ("g", "f", "e", "d", "c", "b", "a")
    ]
    calls = []

    def provider(*args, **kwargs):
        calls.append(kwargs)
        return rows

    receipt = graph_rag.GraphRAGRetriever(Driver([])).retrieve_prior_snapshot(
        "g1", limit=5, database="authorized", managed_selection_provider=authorized(provider)
    )
    assert receipt["status"] == "measured"
    assert calls[0]["limit"] == 32
    assert [p["name"] for p in receipt["priors"]] == ["a", "b", "c", "d", "e"]


def test_empty_provider_preserves_legacy_structural_recency():
    rows = [
        measured_row(name=name, best_success_rate=None, episodes=None, evaluation_id=None, policy_identity=None)
        for name in ("z-new", "a-old")
    ]
    receipt = graph_rag.GraphRAGRetriever(Driver([], rows)).retrieve_prior_snapshot(
        "g1", database="authorized", managed_selection_provider=authorized(lambda *a, **kw: [])
    )
    assert [p["name"] for p in receipt["priors"]] == ["z-new", "a-old"]


def test_proven_duplicates_do_not_consume_final_limit_or_pool_runs():
    canonical = proof()
    first = measured_row(_canonical_proof=canonical, graph_version=canonical["sha256"])
    second = measured_row(
        _canonical_proof=canonical,
        graph_version=canonical["sha256"],
        evaluation_id="other-run",
        best_success_rate=0.5,
        episodes=999,
    )
    third = measured_row(name="distinct", evaluation_id="distinct-run", best_success_rate=0.6)
    receipt = graph_rag.GraphRAGRetriever(Driver([first, second, third])).retrieve_prior_snapshot(
        "g1 table", database="authorized", managed_selection_provider=authorized(lambda *a, **kw: [first])
    )
    assert receipt["status"] == "measured"
    assert [(p["evaluation_id"], p["episodes"]) for p in receipt["priors"]] == [("run-four", 4), ("distinct-run", 4)]
    assert "_canonical_proof" not in receipt["priors"][0]


@pytest.mark.parametrize(
    "query",
    [
        graph_rag._EVALUATED_PRIORS_QUERY,
        graph_rag._STRUCTURAL_PRIORS_QUERY,
        graph_rag._SNAPSHOT_EVALUATED_QUERY,
        graph_rag._SNAPSHOT_STRUCTURAL_QUERY,
    ],
)
def test_unknown_managed_roots_excluded_before_membership(query):
    exclusion = "NOT EXISTS { MATCH (e)-[:HAS_REVISION]->(:WorkbenchRevision) }"
    assert exclusion in query
    assert query.index(exclusion) < query.index("OPTIONAL MATCH")


def test_injected_provider_global_measured_and_explicit_driver_only():
    calls = []
    row = measured_row()

    def provider(driver, **kwargs):
        calls.append((driver, kwargs))
        return [row]

    absent = graph_rag.GraphRAGRetriever().retrieve_prior_snapshot(
        "g1 table", database="authorized", managed_selection_provider=authorized(provider)
    )
    assert absent["warnings"] == ["unconfigured"]
    assert calls == []
    driver = Driver([])
    receipt = graph_rag.GraphRAGRetriever(driver).retrieve_prior_snapshot(
        "g1 table", database="authorized", managed_selection_provider=authorized(provider)
    )
    assert receipt["status"] == "measured"
    assert receipt["priors"][0]["evaluation_id"] == "run-four"
    assert len(driver.calls) == 1
    assert len(calls) == 1 and calls[0][0] is driver
    assert calls[0][1].pop("deadline_monotonic") > 0
    assert calls[0][1] == dict(min_success_rate=0.0, min_episodes=1, embodiment="g1", fixture="table", limit=32)


@pytest.mark.parametrize(
    "change",
    [
        {"episodes": True},
        {"episodes": 10**1000},
        {"best_success_rate": False},
        {"objects": ["cube"] * 33},
        {"embodiment": "franka"},
        {"_canonical_proof": {**proof(), "sha256": "a" * 64}},
    ],
)
def test_invalid_provider_evidence_is_unavailable(change):
    receipt = graph_rag.GraphRAGRetriever(Driver([])).retrieve_prior_snapshot(
        "g1 table",
        database="authorized",
        managed_selection_provider=authorized(lambda *a, **kw: [measured_row(**change)]),
    )
    assert receipt["status"] == "unavailable"
    assert receipt["warnings"]


def test_conflicting_canonical_payload_projection_is_quarantined():
    p = proof()
    rows = [
        measured_row(_canonical_proof=p, graph_version=p["sha256"]),
        measured_row(_canonical_proof=p, graph_version=p["sha256"], objects=["other"]),
    ]
    receipt = graph_rag.GraphRAGRetriever(Driver([])).retrieve_prior_snapshot(
        "g1 table", database="authorized", managed_selection_provider=authorized(lambda *a, **kw: rows)
    )
    assert receipt["status"] == "unavailable"
    assert receipt["warnings"] == ["invalid_record"]


def test_snapshot_queries_project_physical_identity():
    assert "elementId(e) AS _physical_root_id" in graph_rag._SNAPSHOT_EVALUATED_QUERY
    assert "elementId(best_ev) AS _physical_run_id" in graph_rag._SNAPSHOT_EVALUATED_QUERY
    assert "elementId(e) AS _physical_root_id" in graph_rag._SNAPSHOT_STRUCTURAL_QUERY


def test_legacy_canonical_proof_is_explicitly_projected():
    for query in (graph_rag._SNAPSHOT_EVALUATED_QUERY, graph_rag._SNAPSHOT_STRUCTURAL_QUERY):
        assert "AS _canonical_proof" in query
        assert "spec_json: e.spec_json" in query


def test_same_deciding_run_cannot_claim_conflicting_counts():
    p = proof()
    rows = [measured_row(_canonical_proof=p, graph_version=p["sha256"], episodes=n) for n in (4, 8)]
    receipt = graph_rag.GraphRAGRetriever(Driver([])).retrieve_prior_snapshot(
        "g1 table", database="authorized", managed_selection_provider=authorized(lambda *a, **kw: rows)
    )
    assert receipt["warnings"] == ["invalid_record"]


@pytest.mark.parametrize("kind", ["failure", "oversized", "false"])
def test_provider_failure_never_becomes_empty_success(kind):
    def provider(*args, **kwargs):
        if kind == "failure":
            raise RuntimeError("SECRET")
        return [measured_row()] * 33 if kind == "oversized" else False

    receipt = graph_rag.GraphRAGRetriever(Driver([], [])).retrieve_prior_snapshot(
        "g1 table", database="authorized", managed_selection_provider=authorized(provider)
    )
    assert receipt["status"] == "unavailable"
    assert receipt["warnings"]
    assert "SECRET" not in json.dumps(receipt)


def test_unproven_aliases_and_reused_evaluation_ids_remain_distinct():
    rows = [measured_row(name=name) for name in ("scene", "scene__" + "a" * 16)]
    receipt = graph_rag.GraphRAGRetriever(Driver(rows)).retrieve_prior_snapshot(
        "g1 table", database="authorized", managed_selection_provider=authorized(lambda *a, **kw: [])
    )
    assert len(receipt["priors"]) == 2


def test_legacy_measured_outranks_managed_structural():
    structural = measured_row(best_success_rate=None, episodes=None, evaluation_id=None, policy_identity=None)
    receipt = graph_rag.GraphRAGRetriever(Driver([measured_row()])).retrieve_prior_snapshot(
        "g1 table", database="authorized", managed_selection_provider=authorized(lambda *a, **kw: [structural])
    )
    assert receipt["status"] == "measured"
    assert len(receipt["priors"]) == 1


def test_rejected_structural_proof_cannot_hide_behind_measured_branch():
    structural = measured_row(
        best_success_rate=None, episodes=None, evaluation_id=None, policy_identity=None, _canonical_proof={}
    )
    receipt = graph_rag.GraphRAGRetriever(Driver([measured_row()])).retrieve_prior_snapshot(
        "g1 table", database="authorized", managed_selection_provider=authorized(lambda *a, **kw: [structural])
    )
    assert receipt["warnings"] == ["invalid_record"]


def test_physical_root_run_duplicates_do_not_inflate():
    row = measured_row(_physical_root_id="root-id", _physical_run_id="run-id")
    receipt = graph_rag.GraphRAGRetriever(Driver([row, row])).retrieve_prior_snapshot(
        "g1 table", database="authorized", managed_selection_provider=authorized(lambda *a, **kw: [])
    )
    assert len(receipt["priors"]) == 1


def test_context_and_canonical_receipt_fields_unchanged():
    old = graph_rag.GraphRAGRetriever(Driver([measured_row()])).retrieve_prior_snapshot("g1 table")
    new = graph_rag.GraphRAGRetriever(Driver([])).retrieve_prior_snapshot(
        "g1 table", database="authorized", managed_selection_provider=authorized(lambda *a, **kw: [measured_row()])
    )
    assert set(old) == set(new)
    for key in set(old) - {"timing"}:
        assert old[key] == new[key]


@pytest.mark.parametrize(
    "change",
    [
        {"_policies": [{"valid_label": True, "identity": "policy-one"}] * 2},
        {"_policies": [{"valid_label": False, "identity": "policy-one"}]},
        {"_policies": [{"valid_label": True, "identity": "other"}]},
        {"_controllers": [{"valid_label": False, "variants": []}]},
        {"_controllers": [{"valid_label": True, "variants": []}] * 2},
        {"_graph_links": 2},
        {"_run_ids": 2},
    ],
)
def test_provider_absent_rejects_ambiguous_legacy_provenance(change):
    receipt = graph_rag.GraphRAGRetriever(Driver([measured_row(**change)])).retrieve_prior_snapshot("g1")
    assert receipt["warnings"] == ["invalid_record"]


def test_provider_absent_one_physical_run_occupies_one_slot():
    row = measured_row(_physical_root_id="root", _physical_run_id="run")
    receipt = graph_rag.GraphRAGRetriever(Driver([row, row])).retrieve_prior_snapshot("g1")
    assert len(receipt["priors"]) == 1


def test_same_physical_run_cannot_escape_dedup_through_canonical_proof():
    p = proof()
    row = measured_row(_physical_root_id="root", _physical_run_id="run", graph_version=p["sha256"])
    receipt = graph_rag.GraphRAGRetriever(Driver([row, {**row, "_canonical_proof": p}])).retrieve_prior_snapshot("g1")
    assert len(receipt["priors"]) == 1


def test_same_physical_run_cannot_claim_different_roots():
    rows = [measured_row(_physical_root_id=root, _physical_run_id="run") for root in ("a", "b")]
    receipt = graph_rag.GraphRAGRetriever(Driver(rows)).retrieve_prior_snapshot("g1")
    assert receipt["warnings"] == ["invalid_record"]


def test_legacy_provenance_queries_count_wrong_labels_without_row_products():
    query = graph_rag._SNAPSHOT_EVALUATED_QUERY
    assert "MATCH (best_ev)-[r:USED_POLICY]->(policy)" in query
    assert "MATCH (trial)-[r:BASED_ON_EVALUATION]->(best_ev)" in query
    assert "MATCH (trial)-[r:TRIAL_CONTROLLER]->(variant)" in query
    assert "AS _graph_links" in query and "AS _run_ids" in query
    assert "AS _policies" in query and "AS _controllers" in query


@pytest.mark.parametrize("elapsed", [180.1, 1000.0])
def test_deadline_overflow_returns_unavailable_without_fabricated_elapsed(monkeypatch, elapsed):
    clock = [10.0]
    monkeypatch.setattr(graph_rag.time, "monotonic", lambda: clock[0])
    driver = Driver([measured_row()])

    def provider(*args, **kwargs):
        clock[0] += elapsed
        return [measured_row()]

    receipt = graph_rag.GraphRAGRetriever(driver).retrieve_prior_snapshot(
        "g1", database="authorized", managed_selection_provider=authorized(provider)
    )
    assert receipt["status"] == "unavailable"
    assert receipt["warnings"] == ["retrieval_failed"]
    assert receipt["timing"]["elapsed_seconds"] is None
    assert receipt["timing"]["source"] == "unavailable"
    assert not driver.calls


def test_cooperative_deadline_is_forwarded_and_bounds_later_queries(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(graph_rag.time, "monotonic", lambda: clock[0])
    driver = Driver([measured_row()])

    def provider(*args, **kwargs):
        assert kwargs["deadline_monotonic"] == 190.0
        clock[0] = 188.0
        return []

    receipt = graph_rag.GraphRAGRetriever(driver).retrieve_prior_snapshot(
        "g1", database="authorized", managed_selection_provider=authorized(provider)
    )
    assert receipt["status"] == "measured"
    assert driver.calls[0][0].timeout == 2.0
