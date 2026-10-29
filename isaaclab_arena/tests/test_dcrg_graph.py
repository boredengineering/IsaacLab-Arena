# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Offline bridge contracts; synthetic fixtures are not rollout or database evidence."""

import hashlib
import importlib
import json
import re
from copy import deepcopy

import pytest

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environment_spec.arena_env_graph_types import AssetRegistry, TaskRegistry


@pytest.fixture
def spec(monkeypatch):
    monkeypatch.setattr(AssetRegistry, "is_registered", lambda *args: True)
    monkeypatch.setattr(TaskRegistry, "is_registered", lambda *args: True)
    return ArenaEnvGraphSpec.from_dict({
        "env_name": "synthetic_scene",
        "embodiment": {"id": "robot", "registry_name": "synthetic"},
        "background": {"id": "table", "registry_name": "synthetic"},
        "objects": [{"id": "apple", "registry_name": "synthetic", "params": {"x": 0.0}}],
        "task": {
            "composition": "atomic",
            "subtasks": [{
                "kind": "SyntheticTask",
                "params": {
                    "pick_up_object": "apple",
                    "background_scene": "table",
                },
            }],
        },
    })


def bridge():
    return importlib.import_module("isaaclab_arena.agentic_environment_generation.dcrg.graph")


def test_identity_is_canonical_full_hash_without_mutating_spec(spec):
    from isaaclab_arena.agentic_environment_generation.dcrg.loop import spec_digest

    original = spec.to_dict()
    canonical = json.dumps(original, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    identity = bridge().graph_identity(spec, target_object_id="apple")
    assert identity["version"] == spec_digest(spec)
    assert identity == {
        "env_name": f"synthetic_scene__{digest[:16]}",
        "version": digest,
        "reifier_id": "support_apple",
    }
    assert spec.to_dict() == original
    changed = spec.model_copy(deep=True)
    changed.objects[0].params["x"] = 0.01
    assert bridge().graph_identity(changed, target_object_id="apple") != identity


class Result(list):
    def consume(self):
        return None


class MemoryDriver:
    """Transactional property-store test double, not a Neo4j/Cypher emulator."""

    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self.constraints = {}
        self.queries = []
        self.transactions = 0
        self.corrupt_label = None

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute_write(self, callback):
        previous = deepcopy((self.nodes, self.edges))
        self.transactions += 1
        try:
            return callback(self)
        except Exception:
            self.nodes, self.edges = previous
            raise

    @staticmethod
    def key(label, key):
        return label, tuple(sorted(key.items()))

    def run(self, query, **params):
        self.queries.append((query, deepcopy(params)))
        if query.startswith("CREATE CONSTRAINT"):
            name, label, fields = re.search(r"CREATE CONSTRAINT (\w+).*\(n:(\w+)\).*REQUIRE \((.*?)\)", query).groups()
            self.constraints[name] = {
                "name": name,
                "type": "UNIQUENESS",
                "labelsOrTypes": [label],
                "properties": [field.strip()[2:] for field in fields.split(",")],
            }
            return Result()
        if query.startswith("SHOW CONSTRAINTS"):
            return Result(self.constraints.values())
        if "(n:" in query:
            label = re.search(r"\(n:(\w+)", query)[1]
            key = self.key(label, params["key"])
            if query.startswith("MERGE"):
                assert "ON CREATE SET n += $properties" in query
                self.nodes.setdefault(key, {**params["key"], **deepcopy(params["properties"])})
                return Result()
            record = deepcopy(self.nodes.get(key))
            if record is not None and label == self.corrupt_label:
                record["spec_json"] = "corrupted"
            return Result([{"properties": record}]) if record is not None else Result()
        source_label = re.search(r"\(s:(\w+)", query)[1]
        target_label = re.search(r"\(t:(\w+)", query)[1]
        relation = re.search(r"\[r:(\w+)", query)[1]
        source = self.key(source_label, params["source"])
        target = self.key(target_label, params["target"])
        key = (source, target, relation, tuple(sorted(params["key"].items())))
        if source not in self.nodes or target not in self.nodes:
            return Result()
        if "MERGE (s)" in query:
            assert "ON CREATE SET r += $properties" in query
            self.edges.setdefault(key, {**params["key"], **deepcopy(params["properties"])})
            return Result()
        return (
            Result([{
                "properties": deepcopy(self.edges[key]),
                "outgoing_count": sum(edge[0] == source and edge[2] == relation for edge in self.edges),
            }])
            if key in self.edges
            else Result()
        )


def register(spec, driver):
    return bridge().register_environment_version(spec, target_object_id="apple", driver=driver)


def test_registers_only_target_support_atomically_and_idempotently(spec):
    driver = MemoryDriver()
    identity = register(spec, driver)
    assert identity == bridge().graph_identity(spec, target_object_id="apple")
    root = driver.nodes[driver.key("EnvironmentGraph", {"name": identity["env_name"]})]
    assert root["version"] == root["spec_sha256"] == identity["version"]
    assert json.loads(root["spec_json"]) == spec.to_dict()
    assert "converged" not in root
    reifiers = [value for (label, _), value in driver.nodes.items() if label == "ReifiedRelation"]
    assert len(reifiers) == 1
    assert reifiers[0]["reifier_id"] == "support_apple"
    assert reifiers[0]["inferred_from_task"] is True
    assert reifiers[0]["evidence_sources"] == ["inferred_from_task"]
    assert "required_friction" not in reifiers[0]
    assert {edge[2] for edge in driver.edges} >= {
        "HAS_REIFIER",
        "REIFIES_SUBJECT",
        "REIFIES_OBJECT",
    }
    before = deepcopy((driver.nodes, driver.edges))
    assert register(spec, driver) == identity
    assert (driver.nodes, driver.edges) == before
    assert driver.transactions == 2
    assert any(record["labelsOrTypes"] == ["EnvironmentGraph"] for record in driver.constraints.values())


def test_conflicting_graph_payload_is_not_overwritten(spec):
    driver = MemoryDriver()
    identity = register(spec, driver)
    key = driver.key("EnvironmentGraph", {"name": identity["env_name"]})
    driver.nodes[key]["spec_json"] = "conflicting source"
    before = deepcopy((driver.nodes, driver.edges))
    with pytest.raises(ValueError, match="conflict"):
        register(spec, driver)
    assert (driver.nodes, driver.edges) == before


def test_failed_exact_readback_rolls_back_entire_registration(spec):
    driver = MemoryDriver()
    driver.corrupt_label = "ReifiedRelation"
    with pytest.raises(ValueError, match="conflict"):
        register(spec, driver)
    assert driver.nodes == driver.edges == {}


def test_explicit_target_reifier_wins_without_inventing_physical_evidence(spec):
    from isaaclab_arena.environment_spec.arena_env_graph_types import ReifiedRelationSpec

    explicit = ReifiedRelationSpec(
        reifier_id="explicit_apple",
        source_id="apple",
        target_id="table",
        relation_type="PLACED_ON",
        required_friction=0.7,
        evidence_sources=["authored"],
    )
    unrelated = explicit.model_copy(update={"reifier_id": "unrelated", "source_id": "robot"})
    spec.reified_relations = [unrelated, explicit]
    spec.task.subtasks[0].params.pop("background_scene")
    driver = MemoryDriver()
    identity = register(spec, driver)
    assert identity["reifier_id"] == "explicit_apple"
    reifiers = [value for (label, _), value in driver.nodes.items() if label == "ReifiedRelation"]
    assert len(reifiers) == 1
    assert reifiers[0]["required_friction"] == 0.7
    assert reifiers[0]["inferred_from_task"] is False
    assert reifiers[0]["evidence_sources"] == ["authored"]


@pytest.mark.parametrize(
    "change",
    ["missing_background", "wrong_target", "ambiguous_reifier", "unknown_endpoint"],
)
def test_rejects_unjustified_support_before_any_write(spec, change):
    from isaaclab_arena.environment_spec.arena_env_graph_types import ReifiedRelationSpec

    if change == "missing_background":
        spec.task.subtasks[0].params.pop("background_scene")
    elif change == "wrong_target":
        spec.task.subtasks[0].params["pick_up_object"] = "robot"
    else:
        explicit = ReifiedRelationSpec(
            reifier_id="support_apple",
            source_id="apple",
            target_id="table",
            relation_type="PLACED_ON",
        )
        spec.reified_relations = [explicit]
        if change == "ambiguous_reifier":
            spec.reified_relations.append(explicit.model_copy(update={"reifier_id": "other_support"}))
        else:
            explicit.target_id = "unknown"
    driver = MemoryDriver()
    with pytest.raises(ValueError):
        register(spec, driver)
    assert driver.queries == []


def evaluation(identity, driver, path, **changes):
    arguments = {
        "env_name": identity["env_name"],
        "version": identity["version"],
        "run_id": "eval-1",
        "policy_identity": "checkpoint:synthetic:sha256",
        "episode_results": [
            {
                "seed": 11,
                "env_id": 0,
                "episode_in_env": 0,
                "success": False,
                "lifted": True,
            },
            {
                "seed": 11,
                "env_id": 0,
                "episode_in_env": 1,
                "success": True,
                "lifted": True,
            },
        ],
        "artifact_paths": [path],
        "driver": driver,
    }
    arguments.update(changes)
    return bridge().register_evaluation_run(**arguments)


def test_evaluation_keeps_raw_honest_metrics_seed_and_hashed_artifacts(spec, tmp_path):
    driver = MemoryDriver()
    identity = register(spec, driver)
    artifact = tmp_path / "synthetic-results.jsonl"
    artifact.write_bytes(b"synthetic artifact for offline unit test\n")
    receipt = evaluation(identity, driver, artifact)
    props = driver.nodes[driver.key("EvaluationRun", {"id": "eval-1"})]
    assert props["num_episodes"] == 2
    assert props["num_successes"] == 1
    assert props["success_rate"] == 0.5
    assert props["seeds"] == [11]
    assert len(json.loads(props["episode_results_json"])) == 2
    assert props["artifact_paths"] == [str(artifact.resolve())]
    assert props["artifact_sha256"] == [hashlib.sha256(artifact.read_bytes()).hexdigest()]
    assert receipt["eval_id"] == "eval-1" and receipt["verified"] is True
    assert {edge[2] for edge in driver.edges} >= {"EVALUATED_GRAPH", "USED_POLICY"}
    before = deepcopy((driver.nodes, driver.edges))
    assert evaluation(identity, driver, artifact) == receipt
    assert (driver.nodes, driver.edges) == before
    with pytest.raises(ValueError, match="conflict"):
        evaluation(identity, driver, artifact, policy_identity="other-checkpoint")
    assert (driver.nodes, driver.edges) == before
    artifact.write_bytes(b"changed artifact")
    with pytest.raises(ValueError, match="conflict"):
        evaluation(identity, driver, artifact)
    assert (driver.nodes, driver.edges) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"episode_results": []},
        {"run_id": ""},
        {"policy_identity": " "},
        {"artifact_paths": []},
        {"version": "short"},
        {"version": "0" * 64},
        {"episode_results": [{"seed": 0, "env_id": 0, "episode_in_env": 0, "success": 1}]},
        {
            "episode_results": [{
                "seed": 0,
                "env_id": 0,
                "episode_in_env": 0,
                "success": False,
                "completed": False,
            }]
        },
        {"episode_results": [{"env_id": 0, "episode_in_env": 0, "success": False}]},
    ],
)
def test_evaluation_rejects_missing_identity_incomplete_evidence_and_wrong_graph(spec, tmp_path, changes):
    driver = MemoryDriver()
    identity = register(spec, driver)
    path = tmp_path / "evidence"
    path.write_text("synthetic unit fixture")
    before = deepcopy((driver.nodes, driver.edges))
    with pytest.raises(ValueError):
        evaluation(identity, driver, path, **changes)
    assert (driver.nodes, driver.edges) == before


def proposal(parent, child, driver, **changes):
    arguments = {
        "proposal_id": "proposal-1",
        "parent_env_name": parent["env_name"],
        "parent_version": parent["version"],
        "parent_reifier_id": parent["reifier_id"],
        "child_env_name": child["env_name"],
        "child_version": child["version"],
        "parent_eval_id": "eval-1",
        "delta_xy": [0.01, -0.02],
        "driver": driver,
    }
    arguments.update(changes)
    return bridge().register_proposal(**arguments)


@pytest.fixture
def lineage(spec, tmp_path):
    driver = MemoryDriver()
    parent = register(spec, driver)
    child_spec = spec.model_copy(deep=True)
    child_spec.objects[0].params["x"] = 0.01
    child = register(child_spec, driver)
    path = tmp_path / "synthetic-evidence"
    path.write_text("offline synthetic evidence")
    evaluation(parent, driver, path)
    return driver, parent, child, path


def test_proposal_records_immutable_provenance_not_success(lineage):
    driver, parent, child, _ = lineage
    receipt = proposal(parent, child, driver)
    props = driver.nodes[driver.key("DCRGProposal", {"id": "proposal-1"})]
    assert props["status"] == "proposed" and "success" not in props
    assert props["parent_eval_id"] == "eval-1"
    assert props["delta_xy"] == [0.01, -0.02]
    assert props["parent_reifier_id"] == parent["reifier_id"]
    direct_edges = [edge for edge in driver.edges if edge[2] in ("EVOLVES_TO", "PROPOSES_RELAXATION")]
    assert len(direct_edges) == 2
    for edge in direct_edges:
        assert driver.edges[edge]["proposal_id"] == "proposal-1"
        assert driver.edges[edge]["status"] == "proposed"
        assert driver.edges[edge]["parent_eval_id"] == "eval-1"
    before = deepcopy((driver.nodes, driver.edges))
    assert proposal(parent, child, driver) == receipt
    with pytest.raises(ValueError, match="conflict"):
        proposal(parent, child, driver, delta_xy=[0.02, 0.0])
    assert (driver.nodes, driver.edges) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"parent_eval_id": "missing"},
        {"parent_version": "0" * 64},
        {"parent_reifier_id": "other"},
        {"delta_xy": [float("nan"), 0]},
        {"delta_xy": [0, 0, 0]},
        {"delta_xy": [True, 0]},
    ],
)
def test_proposal_rejects_unbound_or_nonfinite_provenance(lineage, changes):
    driver, parent, child, _ = lineage
    before = deepcopy((driver.nodes, driver.edges))
    with pytest.raises(ValueError):
        proposal(parent, child, driver, **changes)
    assert (driver.nodes, driver.edges) == before


@pytest.mark.parametrize("status", ["accepted", "rejected"])
def test_decision_is_separate_immutable_record_not_proposal_success(lineage, status):
    driver, parent, child, path = lineage
    proposal(parent, child, driver)
    evaluation(child, driver, path, run_id="child-eval")
    arguments = {
        "proposal_id": "proposal-1",
        "status": status,
        "reason": "recorded trial comparison",
        "evaluation_run_id": "child-eval",
        "driver": driver,
    }
    receipt = bridge().record_proposal_decision(**arguments)
    assert receipt["status"] == status and receipt["verified"] is True
    original = driver.nodes[driver.key("DCRGProposal", {"id": "proposal-1"})]
    assert original["status"] == "proposed"
    decision = driver.nodes[driver.key("DCRGProposalDecision", {"id": "proposal-1"})]
    assert decision["evaluation_run_id"] == "child-eval"
    assert "success" not in decision
    before = deepcopy((driver.nodes, driver.edges))
    assert bridge().record_proposal_decision(**arguments) == receipt
    with pytest.raises(ValueError, match="conflict"):
        bridge().record_proposal_decision(**{
            **arguments,
            "status": "rejected" if status == "accepted" else "accepted",
        })
    assert (driver.nodes, driver.edges) == before


@pytest.mark.parametrize(
    "change",
    [
        {"status": "success"},
        {"status": "proposed"},
        {"evaluation_run_id": "eval-1"},
        {"evaluation_run_id": None},
        {"proposal_id": "missing"},
        {"reason": ""},
    ],
)
def test_decision_requires_exact_child_evaluation_and_explicit_outcome(lineage, change):
    driver, parent, child, path = lineage
    proposal(parent, child, driver)
    evaluation(child, driver, path, run_id="child-eval")
    before = deepcopy((driver.nodes, driver.edges))
    arguments = {
        "proposal_id": "proposal-1",
        "status": "accepted",
        "reason": "trial improvement",
        "evaluation_run_id": "child-eval",
        "driver": driver,
        **change,
    }
    with pytest.raises(ValueError):
        bridge().record_proposal_decision(**arguments)
    assert (driver.nodes, driver.edges) == before


@pytest.mark.parametrize("relation", ["EVALUATED_GRAPH", "USED_POLICY", "REIFIES_SUBJECT", "REIFIES_OBJECT"])
def test_registration_rejects_additional_conflicting_targets(lineage, relation):
    driver, parent, child, path = lineage
    edge = next(edge for edge in driver.edges if edge[2] == relation)
    alien = driver.key("EnvironmentGraph", {"name": child["env_name"]})
    driver.edges[(edge[0], alien, relation, ())] = {}
    before = deepcopy((driver.nodes, driver.edges))
    with pytest.raises(ValueError, match="conflict"):
        if relation in ("EVALUATED_GRAPH", "USED_POLICY"):
            evaluation(parent, driver, path)
        else:
            proposal(parent, child, driver)
    assert (driver.nodes, driver.edges) == before


def test_registration_rejects_boolean_corruption_of_episode_count(lineage):
    driver, parent, _, path = lineage
    single = [{"seed": 11, "env_id": 0, "episode_in_env": 0, "success": False}]
    evaluation(parent, driver, path, run_id="single", episode_results=single)
    driver.nodes[driver.key("EvaluationRun", {"id": "single"})]["num_episodes"] = True
    with pytest.raises(ValueError, match="conflict"):
        evaluation(parent, driver, path, run_id="single", episode_results=single)


@pytest.mark.parametrize(
    "identity",
    [
        {"run_id": "another-run"},
        {"eval_id": "another-run"},
        {"env_name": "another-scene"},
        {"env_version": "0" * 64},
        {"policy_identity": "another-policy"},
    ],
)
def test_evaluation_rejects_explicit_conflicting_record_identity(lineage, identity):
    driver, parent, _, path = lineage
    records = [{"seed": 11, "env_id": 0, "episode_in_env": 0, "success": False, **identity}]
    before = deepcopy((driver.nodes, driver.edges))
    with pytest.raises(ValueError, match="identity"):
        evaluation(parent, driver, path, episode_results=records, run_id="new-eval")
    assert (driver.nodes, driver.edges) == before


def test_missing_schema_readback_blocks_data_writes(spec):
    class MissingSchema(MemoryDriver):
        def run(self, query, **params):
            result = super().run(query, **params)
            return Result() if query.startswith("SHOW CONSTRAINTS") else result

    driver = MissingSchema()
    with pytest.raises(RuntimeError, match="constraint"):
        register(spec, driver)
    assert driver.nodes == driver.edges == {}
    assert driver.transactions == 0
