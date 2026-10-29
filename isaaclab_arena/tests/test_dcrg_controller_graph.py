# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Controller graph contracts; synthetic fixtures are not rollout evidence."""

import hashlib
import importlib
import json
from copy import deepcopy

import pytest

from isaaclab_arena.tests import test_dcrg_graph as graph_fixtures
from isaaclab_arena.tests.test_dcrg_graph import MemoryDriver, evaluation, register

spec = graph_fixtures.spec


def controller_graph():
    return importlib.import_module("isaaclab_arena.agentic_environment_generation.dcrg.controller_graph")


@pytest.fixture
def contract():
    return {
        "checkpoint_identity": "/models/synthetic/checkpoint-5000",
        "checkpoint_weights_sha256": {"model.safetensors": "a" * 64},
        "controller_config": {"mode": "align", "gain": 0.2},
        "source_sha256": {"controller.py": "b" * 64, "base_policy.py": "c" * 64},
        "policy_config_sha256": "d" * 64,
        "hand_body": "left_hand_middle_1_link",
        "frame": "robot_root",
        "privilege_mode": "privileged_state_diagnostic",
        "scenario_contract": "c1_existing_left_hand_baseline",
    }


def test_registration_is_canonical_create_only_and_not_a_success(contract):
    driver = MemoryDriver()
    original = deepcopy(contract)
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    identity = controller_graph().register_controller_variant(contract, driver)
    assert identity == {
        "variant_id": digest,
        "policy_identity": contract["checkpoint_identity"] + "#controller:" + digest,
        "checkpoint_identity": contract["checkpoint_identity"],
        "verified": True,
    }
    props = driver.nodes[driver.key("DCRGControllerVariant", {"id": digest})]
    assert props["spec_json"] == canonical
    assert props["privileged_state"] is True
    assert "success" not in props and "success_rate" not in props
    assert not any(key[0] == "EvaluationRun" for key in driver.nodes)
    assert not any(key[2] in ("EVOLVES_TO", "PROPOSES_RELAXATION") for key in driver.edges)
    before = deepcopy((driver.nodes, driver.edges))
    assert controller_graph().register_controller_variant(dict(reversed(list(contract.items()))), driver) == identity
    assert (driver.nodes, driver.edges) == before
    assert contract == original
    altered = deepcopy(contract)
    altered["controller_config"]["gain"] = 0.3
    assert controller_graph().register_controller_variant(altered, driver)["variant_id"] != digest
    driver.nodes[driver.key("DCRGControllerVariant", {"id": digest})]["spec_json"] = "tampered"
    before = deepcopy((driver.nodes, driver.edges))
    with pytest.raises(ValueError, match="conflict"):
        controller_graph().register_controller_variant(contract, driver)
    assert (driver.nodes, driver.edges) == before


@pytest.mark.parametrize(
    "field",
    [
        "checkpoint_identity",
        "checkpoint_weights_sha256",
        "controller_config",
        "source_sha256",
        "policy_config_sha256",
        "hand_body",
        "frame",
        "privilege_mode",
        "scenario_contract",
    ],
)
def test_contract_requires_provenance_before_writing(contract, field):
    driver = MemoryDriver()
    del contract[field]
    with pytest.raises(ValueError, match=field):
        controller_graph().register_controller_variant(contract, driver)
    assert driver.queries == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("checkpoint_identity", " "),
        ("checkpoint_weights_sha256", {}),
        ("checkpoint_weights_sha256", {"model": "a" * 63}),
        ("source_sha256", {"controller.py": "A" * 64}),
        ("source_sha256", {}),
        ("policy_config_sha256", "bad"),
        ("controller_config", []),
        ("controller_config", {"gain": float("nan")}),
        ("hand_body", ""),
        ("frame", None),
        ("privilege_mode", "unprivileged"),
        ("scenario_contract", "right_hand_c1"),
    ],
)
def test_contract_rejects_invalid_provenance_before_writing(contract, field, value):
    driver = MemoryDriver()
    contract[field] = value
    with pytest.raises(ValueError):
        controller_graph().register_controller_variant(contract, driver)
    assert driver.queries == []


def test_variant_failed_readback_rolls_back(contract):
    driver = MemoryDriver()
    driver.corrupt_label = "DCRGControllerVariant"
    with pytest.raises(ValueError, match="conflict"):
        controller_graph().register_controller_variant(contract, driver)
    assert driver.nodes == driver.edges == {}


@pytest.fixture
def trial(contract, spec, tmp_path):
    driver = MemoryDriver()
    graph = register(spec, driver)
    variant = controller_graph().register_controller_variant(contract, driver)
    path = tmp_path / "synthetic-episodes.jsonl"
    rows = [
        {
            "seed": 11,
            "env_id": 0,
            "episode_in_env": 0,
            "success": False,
            "lifted": True,
            "progress": {"events": []},
        },
        {
            "seed": 11,
            "env_id": 0,
            "episode_in_env": 1,
            "success": False,
            "progress": {"events": [{"predicate_name": "object_lifted_above_resting_min(apple)"}]},
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows))
    evaluation(graph, driver, path, policy_identity=variant["policy_identity"], episode_results=rows)
    return driver, graph, variant, path, rows


def test_attach_binds_verified_evaluation_without_mutating_old_evidence(trial):
    driver, graph, variant, _, _ = trial
    old_nodes = deepcopy(driver.nodes)
    receipt = controller_graph().attach_controller_evaluation("eval-1", variant["variant_id"], "experiment-1", driver)
    assert receipt == {
        "run_id": "eval-1",
        "variant_id": variant["variant_id"],
        "experiment_id": "experiment-1",
        "env_name": graph["env_name"],
        "version": graph["version"],
        "policy_identity": variant["policy_identity"],
        "verified": True,
    }
    assert all(driver.nodes[key] == value for key, value in old_nodes.items())
    assert {edge[2] for edge in driver.edges} >= {
        "TRIAL_CONTROLLER",
        "BASED_ON_EVALUATION",
        "IN_CONTROLLER_EXPERIMENT",
    }
    assert not any(key[2] in ("EVOLVES_TO", "PROPOSES_RELAXATION") for key in driver.edges)
    trial_node = driver.nodes[driver.key("DCRGControllerTrial", {"id": "eval-1"})]
    assert trial_node["variant_id"] == variant["variant_id"]
    before = deepcopy((driver.nodes, driver.edges))
    assert (
        controller_graph().attach_controller_evaluation("eval-1", variant["variant_id"], "experiment-1", driver)
        == receipt
    )
    assert (driver.nodes, driver.edges) == before
    with pytest.raises(ValueError, match="conflict"):
        controller_graph().attach_controller_evaluation("eval-1", variant["variant_id"], "other-experiment", driver)
    assert (driver.nodes, driver.edges) == before


@pytest.mark.parametrize("change", ["raw_checkpoint", "other_variant", "contract_tamper", "policy_tamper"])
def test_attach_rejects_unbound_or_corrupted_controller_identity(trial, contract, change):
    driver, graph, variant, path, rows = trial
    run_id = "eval-1"
    if change == "raw_checkpoint":
        run_id = "raw-checkpoint-run"
        evaluation(
            graph, driver, path, run_id=run_id, policy_identity=contract["checkpoint_identity"], episode_results=rows
        )
    elif change == "other_variant":
        contract["controller_config"]["gain"] = 0.7
        variant = controller_graph().register_controller_variant(contract, driver)
    else:
        props = driver.nodes[driver.key("DCRGControllerVariant", {"id": variant["variant_id"]})]
        if change == "contract_tamper":
            contract["controller_config"]["gain"] = 0.9
            props["spec_json"] = json.dumps(contract)
        else:
            props["policy_identity"] = "tampered"
    before = deepcopy((driver.nodes, driver.edges))
    with pytest.raises(ValueError, match="conflict"):
        controller_graph().attach_controller_evaluation(run_id, variant["variant_id"], "experiment-1", driver)
    assert (driver.nodes, driver.edges) == before


@pytest.mark.parametrize("field,value", [("run_id", ""), ("variant_id", "short"), ("experiment_id", " ")])
def test_attach_validates_identifiers_before_io(trial, field, value):
    driver, _, variant, _, _ = trial
    arguments = {
        "run_id": "eval-1",
        "variant_id": variant["variant_id"],
        "experiment_id": "experiment-1",
        "driver": driver,
        field: value,
    }
    queries = deepcopy(driver.queries)
    with pytest.raises(ValueError, match=field):
        controller_graph().attach_controller_evaluation(**arguments)
    assert driver.queries == queries


@pytest.mark.parametrize("change", ["scene", "weights", "checkpoint", "frame", "policy_config"])
def test_comparison_group_pins_scene_checkpoint_and_base_contract(trial, contract, spec, change):
    driver, graph, variant, path, rows = trial
    controller_graph().attach_controller_evaluation("eval-1", variant["variant_id"], "experiment-1", driver)
    if change == "scene":
        spec.objects[0].params["x"] = 0.1
        graph = register(spec, driver)
    elif change == "weights":
        contract["checkpoint_weights_sha256"]["model.safetensors"] = "e" * 64
    elif change == "checkpoint":
        contract["checkpoint_identity"] = "/models/other-checkpoint"
    elif change == "frame":
        contract["frame"] = "world"
    else:
        contract["policy_config_sha256"] = "f" * 64
    variant = controller_graph().register_controller_variant(contract, driver)
    evaluation(graph, driver, path, run_id="eval-2", policy_identity=variant["policy_identity"], episode_results=rows)
    before = deepcopy((driver.nodes, driver.edges))
    with pytest.raises(ValueError, match="conflict"):
        controller_graph().attach_controller_evaluation("eval-2", variant["variant_id"], "experiment-1", driver)
    assert (driver.nodes, driver.edges) == before


@pytest.mark.parametrize("relation", ["TRIAL_CONTROLLER", "BASED_ON_EVALUATION", "IN_CONTROLLER_EXPERIMENT"])
def test_attach_rejects_additional_relationship_targets(trial, relation):
    driver, _, variant, _, _ = trial
    controller_graph().attach_controller_evaluation("eval-1", variant["variant_id"], "experiment-1", driver)
    trial_key = driver.key("DCRGControllerTrial", {"id": "eval-1"})
    edge = next(edge for edge in driver.edges if edge[0] == trial_key and edge[2] == relation)
    driver.edges[(edge[0], trial_key, relation, ())] = {}
    before = deepcopy((driver.nodes, driver.edges))
    with pytest.raises(ValueError, match="conflict"):
        controller_graph().attach_controller_evaluation("eval-1", variant["variant_id"], "experiment-1", driver)
    assert (driver.nodes, driver.edges) == before


class ReadDriver:
    """Capture retrieval's Cypher contract; rows are synthetic query results."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, query, **params):
        self.queries.append((query, params))
        return self.rows


def retrieval_row(trial):
    driver, graph, variant, _, _ = trial
    return {
        "variant": deepcopy(driver.nodes[driver.key("DCRGControllerVariant", {"id": variant["variant_id"]})]),
        "evaluation": deepcopy(driver.nodes[driver.key("EvaluationRun", {"id": "eval-1"})]),
        "experiment_id": "experiment-1",
        "source_env_name": "synthetic_scene",
        "spec_json": driver.nodes[driver.key("EnvironmentGraph", {"name": graph["env_name"]})]["spec_json"],
    }


def test_retrieval_keeps_zero_success_trials_config_raw_lifts_and_artifacts(trial, contract):
    from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever

    driver = ReadDriver([retrieval_row(trial)])
    result = GraphRAGRetriever(driver).retrieve_controller_trials(
        "synthetic_scene",
        contract["checkpoint_identity"],
        experiment_id="experiment-1",
        limit=20,
    )
    assert len(result) == 1
    row = result[0]
    assert row["run_id"] == "eval-1"
    assert row["version"] == trial[1]["version"]
    assert row["experiment_id"] == "experiment-1"
    assert row["contract"] == contract
    assert row["controller_config"] == contract["controller_config"]
    assert row["privileged_state"] is True
    assert row["privilege_mode"] == "privileged_state_diagnostic"
    assert row["num_episodes"] == 2 and row["num_successes"] == 0 and row["success_rate"] == 0.0
    assert row["num_sustained_lifts"] == 1 and row["sustained_lift_rate"] == 0.5
    assert row["evidence"] == "measured_controller_trial"
    assert row["artifacts"] == [
        {"path": str(trial[3].resolve()), "sha256": hashlib.sha256(trial[3].read_bytes()).hexdigest()}
    ]
    query, params = driver.queries[0]
    assert params == {
        "source_env_name": "synthetic_scene",
        "checkpoint_identity": contract["checkpoint_identity"],
        "experiment_id": "experiment-1",
        "limit": 20,
    }
    assert "RETURN DISTINCT" in query and "LIMIT $limit" in query
    assert "e.source_env_name = $source_env_name" in query
    assert "v.checkpoint_identity = $checkpoint_identity" in query
    assert "$experiment_id IS NULL" in query
    assert "ev.policy_identity = v.policy_identity" in query
    assert "ev.num_episodes > 0" in query
    assert "OPTIONAL MATCH" not in query and "sum(" not in query.lower()
    assert "success_rate >" not in query and "EVOLVES_TO" not in query


def test_retrieval_missing_raw_events_are_unknown_not_claimed_lifts(trial, contract):
    from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever

    row = retrieval_row(trial)
    episodes = json.loads(row["evaluation"]["episode_results_json"])
    del episodes[0]["progress"]
    row["evaluation"]["episode_results_json"] = json.dumps(episodes, sort_keys=True, separators=(",", ":"))
    driver = ReadDriver([row])
    results = GraphRAGRetriever(driver).retrieve_controller_trials("synthetic_scene", contract["checkpoint_identity"])
    assert results[0]["num_sustained_lifts"] is None
    assert results[0]["sustained_lift_rate"] is None
    assert driver.queries[0][1]["experiment_id"] is None


def test_retrieval_does_not_fall_back_to_unevaluated_variants(contract):
    from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever

    driver = ReadDriver([])
    assert (
        GraphRAGRetriever(driver).retrieve_controller_trials("synthetic_scene", contract["checkpoint_identity"]) == []
    )
    assert len(driver.queries) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"source_env_name": " "},
        {"checkpoint_identity": ""},
        {"experiment_id": " "},
        {"limit": 0},
        {"limit": -1},
        {"limit": True},
        {"limit": 1.5},
    ],
)
def test_retrieval_rejects_invalid_bounds_and_identities_before_io(contract, changes):
    from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever

    driver = ReadDriver([])
    arguments = {
        "source_env_name": "synthetic_scene",
        "checkpoint_identity": contract["checkpoint_identity"],
        **changes,
    }
    with pytest.raises(ValueError):
        GraphRAGRetriever(driver).retrieve_controller_trials(**arguments)
    assert driver.queries == []


@pytest.mark.parametrize("change", ["count", "success_count", "variant_contract", "privilege", "policy", "unfinished"])
def test_retrieval_rejects_corrupted_stored_evidence(trial, contract, change):
    from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever

    row = retrieval_row(trial)
    if change == "count":
        row["evaluation"]["num_episodes"] = 5
    elif change == "success_count":
        row["evaluation"]["num_successes"] = 1
    elif change == "variant_contract":
        contract["controller_config"]["gain"] = 0.9
        row["variant"]["spec_json"] = json.dumps(contract)
    elif change == "privilege":
        row["variant"]["privileged_state"] = False
    elif change == "policy":
        row["evaluation"]["policy_identity"] = "raw-checkpoint"
    else:
        episodes = json.loads(row["evaluation"]["episode_results_json"])
        episodes[0]["completed"] = False
        row["evaluation"]["episode_results_json"] = json.dumps(episodes)
    with pytest.raises(ValueError):
        GraphRAGRetriever(ReadDriver([row])).retrieve_controller_trials(
            "synthetic_scene", contract["checkpoint_identity"]
        )


def test_retrieval_database_failure_propagates(contract):
    from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever

    class Unavailable(ReadDriver):
        def run(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="unavailable"):
        GraphRAGRetriever(Unavailable([])).retrieve_controller_trials(
            "synthetic_scene", contract["checkpoint_identity"]
        )
