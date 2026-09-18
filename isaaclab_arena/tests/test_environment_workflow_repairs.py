# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure dict-shaped Arena repair tests; synthetic identities, no simulator."""
import copy
import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest


def scene():
    return {
        "env_name": "synthetic_banana",
        "embodiment": {"id": "robot", "registry_name": "synthetic_robot", "params": {}},
        "background": {"id": "table", "registry_name": "synthetic_table", "params": {}},
        "objects": [
            {"id": "banana", "registry_name": "synthetic_banana", "params": {}},
            {"id": "bowl", "registry_name": "synthetic_bowl", "params": {}},
        ],
        "relations": [
            {"kind": "is_anchor", "subject": "table", "params": {}},
            {"kind": "on", "subject": "banana", "reference": "table", "params": {"surface_anchor": "top"}},
            {"kind": "at_position", "subject": "banana", "params": {"x": 0.0, "y": 0.0}},
        ],
        "reified_relations": [],
        "task": {
            "composition": "atomic",
            "subtasks": [{
                "kind": "PickAndPlaceTask",
                "params": {"pick_up_object": "banana", "destination_location": "bowl", "background_scene": "table"},
            }],
        },
    }


def validate(original, candidate, **kwargs):
    from isaaclab_arena.agentic_environment_generation.workflow.repairs import validate_scene_repair

    return validate_scene_repair(original, candidate, target_id="banana", **kwargs)


def test_xy_receipt_is_immutable_and_not_runtime_evidence():
    original = scene()
    candidate = copy.deepcopy(original)
    candidate["relations"][2]["params"].update(x=0.03, y=0.04)
    before = copy.deepcopy((original, candidate))
    receipt = validate(original, candidate, max_xy_displacement_m=0.05)
    assert receipt.target_id == "banana"
    assert receipt.relation_index == 2
    assert receipt.original_xy == (0.0, 0.0)
    assert receipt.candidate_xy == (0.03, 0.04)
    assert receipt.displacement_m == pytest.approx(0.05)
    assert receipt.requires_fresh_runtime_evidence is True
    assert receipt.applies_changes is False
    assert (original, candidate) == before
    with pytest.raises((FrozenInstanceError, AttributeError)):
        receipt.target_id = "other"


@pytest.mark.parametrize(
    "path,value",
    [
        (("env_name",), "changed"),
        (("embodiment", "params"), {"initial_pose": {"position_xyz": [1, 2, 3]}}),
        (("background", "registry_name"), "changed"),
        (("objects", 0, "registry_name"), "changed"),
        (("objects", 0, "params"), {"initial_pose": {"position_xyz": [1, 2, 3]}}),
        (("objects", 1, "params"), {"mass": 3}),
        (("relations", 1, "reference"), "bowl"),
        (("relations", 2, "params", "z"), 1),
        (("relations", 2, "params", "relation_loss_weight"), 0),
        (("placement_validators",), {"enabled": []}),
        (("task", "subtasks", 0, "params", "destination_location"), "table"),
        (("reified_relations",), [{"source_id": "banana", "required_friction": 0}]),
    ],
)
def test_forbidden_edits(path, value):
    original = scene()
    candidate = copy.deepcopy(original)
    candidate["relations"][2]["params"]["x"] = 0.01
    node = candidate
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    before = copy.deepcopy((original, candidate))
    with pytest.raises(ValueError, match="^repair_forbidden_edit$"):
        validate(original, candidate, max_xy_displacement_m=0.1)
    assert (original, candidate) == before


@pytest.mark.parametrize(
    "case",
    [
        "raw_banana",
        "duplicate_relation",
        "missing_target",
        "duplicate_target",
        "identity_collision",
        "missing_x",
        "reorder",
        "object_reorder",
        "delete_z",
    ],
)
def test_unsupported_or_changed_structure(case):
    original = scene()
    if case == "raw_banana":
        original["relations"].pop()
    elif case == "duplicate_relation":
        original["relations"].append(copy.deepcopy(original["relations"][2]))
    elif case == "missing_target":
        original["objects"].pop(0)
    elif case == "duplicate_target":
        original["objects"].append(copy.deepcopy(original["objects"][0]))
    elif case == "identity_collision":
        original["embodiment"]["id"] = "banana"
    elif case == "missing_x":
        del original["relations"][2]["params"]["x"]
    elif case == "delete_z":
        original["relations"][2]["params"]["z"] = 0.8
    candidate = copy.deepcopy(original)
    if case == "raw_banana":
        candidate["relations"].append({"kind": "at_position", "subject": "banana", "params": {"x": 0.01, "y": 0}})
    else:
        candidate["relations"][2]["params"]["x"] = 0.01
    if case == "reorder":
        candidate["relations"].reverse()
    elif case == "object_reorder":
        candidate["objects"].reverse()
    elif case == "delete_z":
        del candidate["relations"][2]["params"]["z"]
    code = "repair_unsupported_no_at_position" if case == "raw_banana" else "repair_[a-z_]+"
    with pytest.raises(ValueError, match=f"^{code}$"):
        validate(original, candidate, max_xy_displacement_m=0.1)


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -float("inf"), "0", None])
@pytest.mark.parametrize("location", ["original", "candidate", "bound"])
def test_invalid_coordinates_or_bound(value, location):
    original = scene()
    candidate = copy.deepcopy(original)
    candidate["relations"][2]["params"]["x"] = 0.01
    bound = 0.1
    if location == "bound":
        bound = value
    else:
        (original if location == "original" else candidate)["relations"][2]["params"]["x"] = value
    with pytest.raises(ValueError, match="^repair_[a-z_]+$"):
        validate(original, candidate, max_xy_displacement_m=bound)


@pytest.mark.parametrize(
    "x,y,bound,code",
    [
        (0, 0, 1, "repair_no_op"),
        (0.04, 0.04, 0.05, "repair_displacement_exceeded"),
        (0.11, 0, 0.1, "repair_displacement_exceeded"),
        (0.01, 0, -1, "repair_invalid_bound"),
    ],
)
def test_original_baseline_euclidean_bound(x, y, bound, code):
    original = scene()
    candidate = copy.deepcopy(original)
    candidate["relations"][2]["params"].update(x=x, y=y)
    with pytest.raises(ValueError, match=f"^{code}$"):
        validate(original, candidate, max_xy_displacement_m=bound)


@pytest.mark.parametrize("case", ["cycle", "tuple", "key", "deep", "large", "nonfinite", "type_edit"])
def test_bounded_canonical_json(case):
    original = scene()
    if case == "cycle":
        original["extra"] = original
    elif case == "tuple":
        original["extra"] = (1, 2)
    elif case == "key":
        original[1] = "invalid"
    elif case == "deep":
        node = original
        for _ in range(100):
            node["extra"] = {}
            node = node["extra"]
    elif case == "large":
        original["extra"] = "x" * 1_048_577
    elif case == "nonfinite":
        original["extra"] = float("nan")
    else:
        original["extra"] = 1
    candidate = copy.deepcopy(original)
    candidate["relations"][2]["params"]["x"] = 0.01
    if case == "type_edit":
        candidate["extra"] = True
    with pytest.raises(ValueError, match="^repair_[a-z_]+$"):
        validate(original, candidate, max_xy_displacement_m=0.1)


@pytest.mark.parametrize(
    "case",
    [
        "anchor",
        "missing_on",
        "duplicate_on",
        "missing_reference",
        "unknown_reference",
        "ambiguous_reference",
        "self_reference",
    ],
)
def test_unsupported_target_profile_retained_in_both_scenes(case):
    original = scene()
    if case == "anchor":
        original["relations"].append({"kind": "is_anchor", "subject": "banana", "params": {}})
    elif case == "missing_on":
        original["relations"].pop(1)
    elif case == "duplicate_on":
        original["relations"].append(copy.deepcopy(original["relations"][1]))
    elif case == "missing_reference":
        del original["relations"][1]["reference"]
    elif case == "unknown_reference":
        original["relations"][1]["reference"] = "absent"
    elif case == "ambiguous_reference":
        original["objects"].append(copy.deepcopy(original["background"]))
    elif case == "self_reference":
        original["relations"][1]["reference"] = "banana"
    candidate = copy.deepcopy(original)
    next(r for r in candidate["relations"] if r["kind"] == "at_position")["params"]["x"] = 0.01
    before = copy.deepcopy((original, candidate))
    with pytest.raises(ValueError, match="^repair_unsupported_(anchor|on)$"):
        validate(original, candidate, max_xy_displacement_m=0.1)
    assert (original, candidate) == before


def test_successive_attempts_use_original_baseline():
    original = scene()
    first = copy.deepcopy(original)
    first["relations"][2]["params"]["x"] = 0.06
    assert validate(original, first, max_xy_displacement_m=0.1).original_xy == (0.0, 0.0)
    second = copy.deepcopy(first)
    second["relations"][2]["params"]["x"] = 0.12
    # The caller retains the original baseline; the validator does not authenticate it.
    with pytest.raises(ValueError, match="^repair_displacement_exceeded$"):
        validate(original, second, max_xy_displacement_m=0.1)
    second["relations"][2]["params"]["x"] = 0.09
    receipt = validate(original, second, max_xy_displacement_m=0.1)
    assert receipt.original_xy == (0.0, 0.0)
    assert receipt.displacement_m == pytest.approx(0.09)


def test_z_and_dictionary_key_order_preserved():
    original = scene()
    original["relations"][2]["params"]["z"] = 0.8
    candidate = dict(reversed(list(copy.deepcopy(original).items())))
    candidate["relations"][2]["params"]["y"] = 0.01
    assert validate(original, candidate, max_xy_displacement_m=0.1).candidate_xy == (0.0, 0.01)


def repair_contract(axes=("x",), bound=0.1):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import WorkflowContract
    from isaaclab_arena.tests.test_environment_workflow_contracts import request

    raw = request()
    raw["source"] = {"kind": "existing", "identity": "raw", "content": json.dumps(scene(), indent=2)}
    raw["preserved"] = [{"subject_id": "banana", "schema_path": "/objects/0", "mode": "frozen"}]
    raw["allowed_interventions"] = [
        {
            "subject_id": "banana",
            "schema_path": f"/relations/2/params/{axis}",
            "operation": "replace",
            "coordinate_frame": "env_local",
            "units": "m",
            "max_total_displacement_m": bound,
        }
        for axis in axes
    ]
    return WorkflowContract.model_validate(raw)


def permitted(contract, original, candidate, **kwargs):
    from isaaclab_arena.agentic_environment_generation.workflow import repairs

    assert hasattr(repairs, "validate_permitted_scene_repair"), "contract-bound adapter missing"
    return repairs.validate_permitted_scene_repair(contract, original, candidate, **kwargs)


@pytest.mark.parametrize("axes", [("x",), ("y",), ("x", "y")])
def test_permitted_receipt_binds_contract_and_canonical_scenes(axes):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import contract_digest

    contract = repair_contract(axes)
    original = scene()
    candidate = copy.deepcopy(original)
    for axis in axes:
        candidate["relations"][2]["params"][axis] = 0.03
    before = copy.deepcopy((original, candidate))
    raw = contract.source.content
    receipt = permitted(contract, original, candidate)

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    assert receipt.contract_digest == contract_digest(contract)
    assert receipt.original_scene_digest == hashlib.sha256(canonical(original)).hexdigest()
    assert receipt.candidate_scene_digest == hashlib.sha256(canonical(candidate)).hexdigest()
    assert receipt.original_scene_digest != receipt.candidate_scene_digest
    assert receipt.delta.target_id == "banana"
    assert receipt.delta.requires_fresh_runtime_evidence
    assert not receipt.delta.applies_changes
    assert (original, candidate) == before
    assert contract.source.content == raw
    with pytest.raises((FrozenInstanceError, AttributeError)):
        receipt.contract_digest = "changed"


@pytest.mark.parametrize(
    "case",
    [
        "empty",
        "wrong_subject",
        "wrong_index",
        "frame",
        "vector_path",
        "wildcard",
        "multiple_targets",
        "operation",
        "units",
        "bound",
        "forbidden_axis",
        "forbidden_axis_type",
        "preservation_conflict",
        "preservation_missing",
        "preservation_subject",
        "raw_banana",
        "vector_scene",
        "other_field",
    ],
)
def test_permitted_rejects_unlisted_or_unsupported_rules(case):
    from isaaclab_arena.agentic_environment_generation.workflow.contracts import PreservationRule

    contract = repair_contract()
    rule = contract.allowed_interventions[0]
    original = scene()
    candidate = copy.deepcopy(original)
    candidate["relations"][2]["params"]["x"] = 0.03
    updates = {
        "wrong_subject": {"subject_id": "bowl"},
        "wrong_index": {"schema_path": "/relations/1/params/x"},
        "frame": {"coordinate_frame": "world"},
        "vector_path": {"schema_path": "/relations/2/params/position"},
        "wildcard": {"schema_path": "/relations/*/params/x"},
        "operation": {"operation": "add"},
        "units": {"units": "cm"},
        "bound": {"max_total_displacement_m": True},
    }
    if case in updates:
        contract = contract.model_copy(update={"allowed_interventions": (rule.model_copy(update=updates[case]),)})
    elif case == "empty":
        contract = contract.model_copy(update={"allowed_interventions": ()})
    elif case == "multiple_targets":
        contract = contract.model_copy(
            update={"allowed_interventions": (rule, rule.model_copy(update={"subject_id": "bowl"}))}
        )
    elif case.startswith("preservation_"):
        path = {
            "preservation_conflict": "/relations/2",
            "preservation_missing": "/objects/9",
            "preservation_subject": "/objects/1",
        }[case]
        contract = contract.model_copy(
            update={"preserved": (PreservationRule(subject_id="banana", schema_path=path, mode="frozen"),)}
        )
    elif case == "forbidden_axis":
        candidate["relations"][2]["params"]["y"] = 0.01
    elif case == "forbidden_axis_type":
        candidate["relations"][2]["params"]["y"] = 0
    elif case == "raw_banana":
        original["relations"].pop()
    elif case == "vector_scene":
        for spec in (original, candidate):
            spec["relations"][2]["params"]["position"] = [0, 0, 0]
    elif case == "other_field":
        candidate["task"]["composition"] = "changed"
    with pytest.raises(ValueError):
        permitted(contract, original, candidate)


@pytest.mark.parametrize("override", [{"target_id": "bowl"}, {"max_xy_displacement_m": 100}])
def test_permitted_has_no_external_overrides(override):
    with pytest.raises(TypeError):
        permitted(repair_contract(), scene(), scene(), **override)


def test_permitted_cumulative_drift_and_conservative_rule_minimum():
    contract = repair_contract(("x", "y"), bound=0.1)
    rule_x, rule_y = contract.allowed_interventions
    contract = contract.model_copy(
        update={"allowed_interventions": (rule_x, rule_y.model_copy(update={"max_total_displacement_m": 0.05}))}
    )
    original = scene()
    first = copy.deepcopy(original)
    first["relations"][2]["params"]["x"] = 0.03
    first_receipt = permitted(contract, original, first)
    second = copy.deepcopy(first)
    second["relations"][2]["params"]["x"] = 0.06
    with pytest.raises(ValueError, match="repair_displacement_exceeded"):
        permitted(contract, original, second)
    second["relations"][2]["params"]["x"] = 0.04
    second_receipt = permitted(contract, original, second)
    assert second_receipt.delta.max_xy_displacement_m == 0.05
    assert first_receipt.contract_digest == second_receipt.contract_digest
    assert first_receipt.original_scene_digest == second_receipt.original_scene_digest
    assert first_receipt.candidate_scene_digest != second_receipt.candidate_scene_digest
    changed_contract_receipt = permitted(repair_contract(("x", "y")), original, second)
    assert changed_contract_receipt.contract_digest != second_receipt.contract_digest
    assert changed_contract_receipt.candidate_scene_digest == second_receipt.candidate_scene_digest
