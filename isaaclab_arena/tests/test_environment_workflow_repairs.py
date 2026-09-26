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


def test_resolved_selection_pins_original_scalar_paths():
    from isaaclab_arena.agentic_environment_generation.workflow import repairs
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import candidate_record

    contract = repair_contract(("x", "y"), bound=0.1)
    original = candidate_record("run", scene(), source_id="raw")
    selection = repairs.resolve_repair_selection(contract, original)
    assert selection.codec == "scalar-xy-selection-v1"
    assert selection.original_candidate_id == original.candidate_id
    assert selection.schema_paths == ("/relations/2/params/x", "/relations/2/params/y")
    assert selection.original_xy_m == (0.0, 0.0) and selection.max_displacement_m == 0.1
    assert selection.placement_semantics == "weighted-at-position-root-xy-v1"
    assert selection.applies_changes is False and selection.establishes_physical_effect is False
    proposed = scene()
    proposed["relations"][2]["params"]["x"] = 0.05
    assert repairs.validate_selected_scene_repair(contract, selection, original, proposed).delta.displacement_m == 0.05
    current = candidate_record(
        "run", proposed, source_id="revision", original_id=original.original_id, parent_id=original.candidate_id
    )
    with pytest.raises(ValueError, match="original"):
        repairs.resolve_repair_selection(contract, current)
    proposed["relations"][2]["params"]["x"] = 0.11
    with pytest.raises(ValueError, match="displacement"):
        repairs.validate_selected_scene_repair(contract, selection, original, proposed)
    proposed["relations"][2]["params"]["x"] = 0.05
    proposed["objects"][1]["params"]["mass"] = 1.0
    with pytest.raises(ValueError, match="forbidden"):
        repairs.validate_selected_scene_repair(contract, selection, original, proposed)
    duplicate = scene()
    duplicate["relations"].append(copy.deepcopy(duplicate["relations"][2]))
    with pytest.raises(ValueError, match="unique"):
        repairs.resolve_repair_selection(contract, candidate_record("run", duplicate, source_id="raw"))
    reordered = scene()
    reordered["relations"] = list(reversed(reordered["relations"]))
    with pytest.raises(ValueError, match="path"):
        repairs.resolve_repair_selection(contract, candidate_record("run", reordered, source_id="raw"))
    disabled = scene()
    disabled["relations"][2]["params"]["relation_loss_weight"] = 0
    with pytest.raises(ValueError, match="weight"):
        repairs.resolve_repair_selection(contract, candidate_record("run", disabled, source_id="raw"))


def test_target_goal_and_selected_unknown_policy_gate_actions(tmp_path):
    import base64
    import io

    from PIL import Image

    from isaaclab_arena.agentic_environment_generation.workflow import contracts, scene_eligibility, scene_observation
    from isaaclab_arena.agentic_environment_generation.workflow.evidence import CandidateBinding, EvidenceCohort
    from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import (
        Observation,
        candidate_record,
        profile_digest,
        repaired_candidate,
    )
    from isaaclab_arena.tests._workflow_scene_fixture import artifacts, composed_fixture, criterion

    area, store = artifacts(tmp_path)
    image = io.BytesIO()
    Image.new("RGB", (1, 1)).save(image, format="PNG")

    def selected_inputs(tag, measured_x, visual_truth, unknown_action="stop"):
        # Byte-backed pure inputs, not a worker/physics stand-in or live proof.
        raw = repair_contract(("x", "y"), bound=0.1).model_dump(mode="json")
        raw["schema_version"] = "5"
        raw["effects"]["allow_runtime"] = True
        raw["acquisition"] = dict(
            codec="explicit-acquisition-v1",
            adapter="droid-rigid-world-v1",
            clock="control_step",
            reference_frame="world",
            control_dt_seconds=0.02,
            horizon_steps=2,
            subjects=["banana", "bowl"],
            state_steps=[1, 2],
            images=[dict(camera="wrist_camera_rgb", step=1, modality="rgb")],
            renderer_update_steps=[1],
            displacement_step=1,
        )
        raw["criteria"] = [
            criterion(
                "scene.xy-target-error",
                criterion_id="goal",
                kind="geometry",
                evaluator_version="numeric-v2",
                subjects=("banana",),
                observation_window=dict(start_step=1, end_step=2),
                rubric="selected world XY target error",
                limit=dict(operator="lt", value=0.001, unit="m"),
                parameters=dict(
                    metric="xy_target_error",
                    reference_frame="world",
                    clock="control_step",
                    sample_steps=[1, 2],
                    temporal_aggregation="all",
                    subject_aggregation="all",
                    missing_data="reject",
                    invalid_data="reject",
                    target_xy_m=[0.05, 0.0],
                ),
            ).model_dump(mode="json"),
            criterion(
                "scene.visible",
                criterion_id="visible",
                kind="visual",
                evaluator_version="full-scene-ternary-v1",
                subjects=("bowl",),
                required_modalities=("rgb",),
                coordinate_frames=("wrist_camera_rgb",),
                observation_window=dict(start_step=1, end_step=1),
                rubric="selected per-frame visibility",
                limit=dict(operator="eq", value=1.0, unit="boolean"),
                parameters=dict(
                    metric="visibility",
                    reference_frame="camera",
                    clock="control_step",
                    images=raw["acquisition"]["images"],
                    temporal_aggregation="all",
                    camera_aggregation="all",
                    subject_aggregation="all",
                    missing_data="reject",
                    invalid_data="reject",
                ),
            ).model_dump(mode="json"),
        ]
        raw["action_policy"] = dict(
            codec="scene-action-policy-v1",
            on_false="corrective_repair",
            on_unknown=unknown_action,
            target_subject="banana",
            mechanism="direct-root-xy-goal-v1",
            goal_criterion_id="goal",
            prerequisite_criterion_ids=[],
            observation=raw["acquisition"] if unknown_action == "informative_observation" else None,
            diagnostic_delta_xy_m=[0.02, 0.0] if unknown_action == "diagnostic_intervention" else None,
            displacement_tolerance_m=0.001,
        )
        raw["budget"].update(
            max_runtime_seconds=None,
            total_deadline_seconds=None,
            max_model_tokens=None,
            max_cost_usd=None,
            max_realizations=3,
            max_steps=6,
            max_observations=3,
            max_model_calls=3,
            policy=dict(
                codec="experiment-policy-v1",
                runtime="accounting_only",
                deadline="accounting_only",
                model_tokens="accounting_only",
                cost="accounting_only",
            ),
            control=dict(
                codec="renewable-control-v1",
                max_supervision_lease_seconds=60.0,
                heartbeat_seconds=20.0,
                max_credential_lifetime_seconds=300.0,
                client_descriptor_schema="2",
            ),
        )
        contract = contracts.WorkflowContract.model_validate(raw)
        original = candidate_record("run", scene(), source_id="raw")
        candidate = CandidateBinding(
            candidate_digest=original.digest,
            contract_digest=contracts.contract_digest(contract),
            profile_digest=profile_digest(contract),
        )
        cohort = EvidenceCohort(
            environment_id="synthetic-env0",
            contract_digest=candidate.contract_digest,
            profile_digest=candidate.profile_digest,
            realization_id=tag,
            reset_id=tag,
            frame_id="world",
            window_id=tag,
        )
        sample = dict(
            step=1,
            frame="world",
            origin_w=[0.0, 0.0, 0.0],
            subjects={
                subject: dict(
                    position_w=[measured_x if subject == "banana" else 1.0, 0.0, 0.5],
                    linear_velocity_w=[0.0, 0.0, 0.0],
                    angular_velocity_w=[0.0, 0.0, 0.0],
                    scene_name=subject,
                    prim_path=f"/World/envs/env_0/{subject}",
                    root_kind="rigid_object",
                )
                for subject in ("banana", "bowl")
            },
        )
        compiled = scene_observation.compile_acquisition(
            contract.acquisition, contract.criteria, candidate=candidate, cohort=cohort
        )
        recorder = scene_observation.ObservationRecorder(
            lambda _env, step: sample | {"step": step}, provenance="synthetic", acquisition=compiled
        )
        recorder(None, 1)
        recorder.add_frame(
            camera="wrist_camera_rgb",
            step=1,
            subject_ids=contract.acquisition.subjects,
            image_bytes=image.getvalue(),
            sensor_update_step=1,
            sensor_sequence=1,
        )
        recorder(None, 2)
        payload = recorder.complete(executed_steps=2, reset_count=1, terminated=False, truncated=False)
        payload["diagnostics"] = dict(
            root_xy_mapping=dict(
                codec="root-xy-mapping-v1",
                subject="banana",
                scene_name="banana",
                prim_path="/World/envs/env_0/banana",
                root_kind="rigid_object",
                position_mapping="root-world-with-env-origin-v1",
                authored_coordinate_frame="env_local",
                placement_semantics="weighted-at-position-root-xy-v1",
                relation_index=2,
                relation_loss_weight=1.0,
                original_scene_digest=original.digest,
                candidate_scene_digest=original.digest,
            )
        )
        source = store.write(candidate, cohort, payload, protect=lambda _: None)
        request = scene_observation.visual_request(
            contract.criteria[1], candidate, cohort, store, source, protect=lambda _: None
        )
        frame = request["frames"][0]
        response = dict(
            codec="full-scene-ternary-v1",
            request_sha256=request["request_sha256"],
            answers=[
                {key: frame[key] for key in ("observation_id", "camera", "step", "clock", "time_seconds", "modality")}
                | dict(
                    frame_digest=frame["sha256"],
                    subjects=[
                        dict(
                            subject="bowl",
                            truth=visual_truth,
                            confidence=None,
                            conflict=False,
                            reason="pure codec input",
                        )
                    ],
                )
            ],
        )
        answer = scene_observation.retain_visual_answer(
            contract.criteria[1],
            candidate,
            cohort,
            store,
            source,
            json.dumps(response).encode(),
            protect=lambda _: None,
        )
        diagnostic = scene_eligibility.retain_root_xy_diagnostic(
            contract, original, original, store, source, protect=lambda _: None
        )
        decision = scene_eligibility.evaluate_action_eligibility(
            contract,
            original,
            original,
            store,
            source,
            visual_answer=answer,
            diagnostic=diagnostic,
            protect=lambda _: None,
        )
        from isaaclab_arena.agentic_environment_generation.workflow.scene_loop import assess_and_route

        routed_observation = Observation(
            codec="scene-observation-v2",
            cohort=cohort,
            source_manifest_digest=source.manifest_digest,
            answer_manifest_digest=answer.manifest_digest,
            answer_assessment_id=store.verified_payload(answer, protect=lambda _: None)["assessment_id"],
            evidence=decision.required_evidence,
            verified_manifest_digests=(source.manifest_digest, answer.manifest_digest),
            action_selection=decision.model_dump(mode="json"),
        )
        route = assess_and_route(contract, original, routed_observation)
        expected_action = {
            "corrective_repair": "repair",
            "diagnostic_intervention": "repair",
            "informative_observation": "capture",
            "stop": "stop",
        }[decision.action]
        if decision.reason == "all_required_true":
            expected_action = "accept"
        assert route.action == expected_action
        assert route.action_selection == decision.model_dump(mode="json")
        if route.action in ("repair", "capture"):
            assert (
                scene_eligibility.validate_selected_effect(contract, original, route.action, route.action_selection)
                == decision
            )
        else:
            for forbidden in ("repair", "capture"):
                with pytest.raises(ValueError, match="selection"):
                    scene_eligibility.validate_selected_effect(contract, original, forbidden, route.action_selection)
        stale = routed_observation.model_copy(
            update={
                "action_selection": decision.model_copy(update={"candidate_digest": "f" * 64}).model_dump(mode="json")
            }
        )
        with pytest.raises(ValueError, match="selection"):
            assess_and_route(contract, original, stale)
        if tag == "corrective":
            (tmp_path / "read-only").mkdir(mode=0o700)
            reader = composed_fixture(tmp_path / "read-only")
            try:
                reader.ports.artifacts = store
                observed = Observation(
                    codec="scene-observation-v2",
                    source_manifest_digest=source.manifest_digest,
                    answer_manifest_digest=answer.manifest_digest,
                    answer_assessment_id=store.verified_payload(answer, protect=lambda _: None)["assessment_id"],
                    cohort=cohort,
                    evidence=decision.required_evidence,
                    verified_manifest_digests=(source.manifest_digest, answer.manifest_digest),
                )
                reader.ports.restore_observations(
                    [
                        dict(
                            candidate_id=original.candidate_id,
                            candidate=original.model_dump_json(),
                            payload=observed.model_dump_json(),
                        )
                    ],
                    contract,
                )
                assert reader.ports.verify_observation(observed, contract, original) == observed
                assert reader.events == []
                malformed = scene_observation.retain_visual_answer(
                    contract.criteria[1], candidate, cohort, store, source, b"\xff", protect=lambda _: None
                )
                reader.ports._retained[cohort.realization_id] = (original, source, malformed)
                failed = reader.ports._evaluate(cohort.realization_id, contract, original)
                assert failed.static_failure == "invalid_visual_answer"
                assert malformed.manifest_digest in failed.verified_manifest_digests
                without_answer = failed.model_copy(
                    update={"answer_manifest_digest": None, "answer_assessment_id": None}
                )
                with pytest.raises(ValueError, match="ancestry"):
                    Observation.model_validate_json(without_answer.model_dump_json())
                legacy_observation = Observation(cohort=cohort, evidence=(), verified_manifest_digests=())
                assert set(legacy_observation.model_dump(mode="json")) == {
                    "cohort",
                    "evidence",
                    "verified_manifest_digests",
                    "static_failure",
                }
                with pytest.raises(ValueError, match="Legacy observations"):
                    Observation.model_validate(
                        legacy_observation.model_dump(mode="python") | {"source_manifest_digest": None}
                    )
                (tmp_path / "failed-readback").mkdir(mode=0o700)
                failed_reader = composed_fixture(tmp_path / "failed-readback")
                try:
                    failed_reader.ports.artifacts = store
                    failed_row = {
                        "candidate_id": original.candidate_id,
                        "candidate": original.model_dump_json(),
                        "payload": failed.model_dump_json(),
                    }
                    failed_reader.ports.restore_observations([failed_row], contract)
                    recovered_answer = failed_reader.ports._retained[cohort.realization_id][2]
                    assert recovered_answer == malformed  # Failure is not verification of absent answer=None.
                    raw_failed = store.verified_payload(recovered_answer, protect=lambda _: None)["raw_response"]
                    assert raw_failed["encoding"] == "base64"
                    assert base64.b64decode(raw_failed["bytes"], validate=True) == b"\xff"
                    assert failed_reader.ports.verify_observation(failed, contract, original) == failed
                    assert failed_reader.events == []
                finally:
                    failed_reader.area.close()
            finally:
                reader.area.close()
            proposed = scene()
            proposed["relations"][2]["params"]["x"] = decision.hypothesis.proposed_authored_xy_m[0]
            validated = scene_eligibility.validate_action_proposal(
                contract,
                original,
                original,
                store,
                source,
                decision,
                proposed,
                visual_answer=answer,
                diagnostic=diagnostic,
                protect=lambda _: None,
            )
            assert validated.candidate_scene_digest == decision.proposed_scene_digest
            other_proposal = copy.deepcopy(proposed)
            other_proposal["relations"][2]["params"]["x"] = 0.04
            with pytest.raises(ValueError, match="decision|hypothesis"):
                scene_eligibility.validate_action_proposal(
                    contract,
                    original,
                    original,
                    store,
                    source,
                    decision,
                    other_proposal,
                    visual_answer=answer,
                    diagnostic=diagnostic,
                    protect=lambda _: None,
                )
            after_candidate = repaired_candidate(contract, original, original, proposed, source_id="repair")
            after_binding = candidate.model_copy(update={"candidate_digest": after_candidate.digest})
            after_cohort = cohort.model_copy(update={"realization_id": "after", "reset_id": "after"})
            after_schedule = scene_observation.compile_acquisition(
                contract.acquisition, contract.criteria, candidate=after_binding, cohort=after_cohort
            )

            def after_sample(_env, step):
                measured = copy.deepcopy(sample)
                measured["step"] = step
                measured["subjects"]["banana"]["position_w"][0] = 0.05 if step == 1 else 0.08
                return measured

            after_recorder = scene_observation.ObservationRecorder(
                after_sample, provenance="synthetic", acquisition=after_schedule
            )
            after_recorder(None, 1)
            after_recorder.add_frame(
                camera="wrist_camera_rgb",
                step=1,
                subject_ids=contract.acquisition.subjects,
                image_bytes=image.getvalue(),
                sensor_update_step=1,
                sensor_sequence=1,
            )
            after_recorder(None, 2)
            after = store.write(
                after_binding,
                after_cohort,
                after_recorder.complete(executed_steps=2, reset_count=1, terminated=False, truncated=False),
                protect=lambda _: None,
            )
            displacement = scene_observation.effective_displacement(
                store,
                source,
                after,
                subject="banana",
                step=1,
                target_local=[0.05, 0.0, 0.5],
                mapping="direct-root-translation-v1",
                tolerance_m=0.001,
                protect=lambda _: None,
                hypothesis=decision.hypothesis,
            )
            assert displacement["codec"] == "measured-displacement-v2" and displacement["effective"]
            assert displacement["step"] == 1 and displacement["causal_status"] == "unproven"
            with pytest.raises(ValueError, match="selected|hypothesis"):
                scene_observation.effective_displacement(
                    store,
                    source,
                    after,
                    subject="banana",
                    step=2,
                    target_local=[0.05, 0.0, 0.5],
                    mapping="direct-root-translation-v1",
                    tolerance_m=0.001,
                    protect=lambda _: None,
                    hypothesis=decision.hypothesis,
                )
            after_request = scene_observation.visual_request(
                contract.criteria[1], after_binding, after_cohort, store, after, protect=lambda _: None
            )
            after_response = copy.deepcopy(response)
            after_response["request_sha256"] = after_request["request_sha256"]
            after_frame = after_request["frames"][0]
            after_response["answers"][0].update(
                {
                    key: after_frame[key]
                    for key in ("observation_id", "camera", "step", "clock", "time_seconds", "modality")
                }
                | {"frame_digest": after_frame["sha256"]}
            )
            after_answer = scene_observation.retain_visual_answer(
                contract.criteria[1],
                after_binding,
                after_cohort,
                store,
                after,
                json.dumps(after_response).encode(),
                protect=lambda _: None,
            )
            after_observed = Observation(
                codec="scene-observation-v2",
                source_manifest_digest=after.manifest_digest,
                answer_manifest_digest=after_answer.manifest_digest,
                answer_assessment_id=store.verified_payload(after_answer, protect=lambda _: None)["assessment_id"],
                cohort=after_cohort,
                evidence=(
                    scene_observation.evaluate_measurement(
                        contract.criteria[0], after_binding, after_cohort, store, after, protect=lambda _: None
                    ),
                    scene_observation.evaluate_visual_answer(
                        contract.criteria[1],
                        after_binding,
                        after_cohort,
                        store,
                        after,
                        after_answer,
                        protect=lambda _: None,
                    ),
                ),
                verified_manifest_digests=(after.manifest_digest, after_answer.manifest_digest),
            )
            assert (
                after_observed.evidence[0].verdict == "violated"
            )  # Movement at step 1 is not goal satisfaction over steps 1–2.
            (tmp_path / "ancestry").mkdir(mode=0o700)
            fresh = composed_fixture(tmp_path / "ancestry")
            try:
                fresh.ports.artifacts = store
                fresh.ports.restore_observations(
                    [
                        dict(
                            candidate_id=after_candidate.candidate_id,
                            candidate=after_candidate.model_dump_json(),
                            payload=after_observed.model_dump_json(),
                        ),
                        dict(
                            candidate_id=original.candidate_id,
                            candidate=original.model_dump_json(),
                            payload=observed.model_dump_json(),
                        ),
                    ],
                    contract,
                    decisions={after_candidate.candidate_id: decision},
                )
                assert fresh.ports.verify_observation(after_observed, contract, after_candidate) == after_observed
                assert fresh.events == []
            finally:
                fresh.area.close()
        return decision

    try:
        wrong_subject = selected_inputs("wrong-subject", 0.05, "false")
        assert wrong_subject.action == "stop" and wrong_subject.reason == "causal_link_not_supported"
        unknown = selected_inputs("unknown", 0.05, "unknown")
        assert unknown.action == "stop" and unknown.observation_selection is None
        observe = selected_inputs("observe", 0.05, "unknown", "informative_observation")
        assert observe.action == "informative_observation" and observe.observation_selection is not None
        corrective = selected_inputs("corrective", 0.0, "true")
        assert corrective.action == "corrective_repair" and corrective.hypothesis.target_subject == "banana"
        assert corrective.hypothesis.baseline_error_m == 0.05 and corrective.hypothesis.predicted_error_m == 0.0
        diagnostic = selected_inputs("diagnostic", 0.05, "unknown", "diagnostic_intervention")
        assert diagnostic.action == "diagnostic_intervention" and diagnostic.hypothesis.predicted_error_m > 0
        assert diagnostic.can_execute is False and corrective.can_execute is False
        assert corrective.policy_digest != observe.policy_digest
        assert corrective.diagnostic_manifest_digest and corrective.repair_selection_digest
    finally:
        area.close()


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
