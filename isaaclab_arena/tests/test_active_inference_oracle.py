# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Frame and bounded-proposal regressions, without a simulator or database connection."""

import yaml
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from isaaclab_arena.agentic_environment_generation import spatial_geometric_oracle as oracle
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environment_spec.arena_env_graph_types import (
    AssetSpec,
    CompositeTaskSpec,
    ReifiedRelationSpec,
    SpatialRelationSpec,
    TaskCompositionType,
    TaskSpec,
)


def _asset(name, registry, xyz):
    return AssetSpec.model_construct(
        id=name,
        registry_name=registry,
        params={"initial_pose": {"position_xyz": xyz, "rotation_xyzw": [0, 0, 0.6, 0.8]}},
    )


@pytest.fixture
def spec():
    # Same root/table/object coordinates as saved C1 v32; skip registry loading only.
    return ArenaEnvGraphSpec.model_construct(
        env_name="g1_tabletop_apple_to_plate",
        embodiment=_asset("g1_robot", "g1_wbc_agile_joint", [-0.46, 0.0, 0.0007]),
        background=_asset("maple_table", "maple_table_robolab", [-0.58, 0.0, 0.078]),
        objects=[
            _asset("red_apple", "apple_01_objaverse_robolab", [-0.173, 0.19, 0.0975]),
            _asset("clay_plate", "clay_plates_hot3d_robolab", [-0.173, -0.02, 0.078]),
        ],
        relations=[
            SpatialRelationSpec.model_construct(kind="is_anchor", subject=name)
            for name in ("maple_table", "red_apple", "clay_plate")
        ],
        task=CompositeTaskSpec.model_construct(
            composition=TaskCompositionType.ATOMIC,
            description="move the apple to the plate",
            subtasks=[
                TaskSpec.model_construct(
                    kind="PickAndPlaceTask",
                    params={
                        "pick_up_object": "red_apple",
                        "destination_location": "clay_plate",
                        "background_scene": "maple_table",
                        "min_lift_height": 0.015,
                        "require_lift_before_place": True,
                    },
                )
            ],
        ),
    )


@pytest.mark.parametrize("feedback", [None, {}])
def test_no_feedback_returns_unchanged_independent_copy(spec, feedback):
    before = deepcopy(spec.model_dump())
    proposal, diagnostics = oracle.relax_spec_active_inference(
        spec,
        temperature=0.0,
        feedback_fetcher=lambda **kwargs: feedback,
    )
    assert proposal.model_dump() == before
    assert spec.model_dump() == before
    assert proposal is not spec
    proposal.objects[0].params["initial_pose"]["position_xyz"][0] = 99
    assert spec.model_dump() == before
    assert any("feedback" in message.lower() for message in diagnostics)


@pytest.mark.parametrize("allowed", [(), ("red_apple",)])
def test_feedback_cannot_move_anchors_by_default(spec, allowed):
    before = deepcopy(spec.model_dump())
    proposal, diagnostics = oracle.relax_spec_active_inference(
        spec,
        temperature=0.0,
        feedback={"dx": 0.01, "dy": 0.01, "dz": 0.04},
        allowed_mutations=allowed,
    )
    assert proposal.model_dump() == before
    assert spec.model_dump() == before
    assert diagnostics


def _propose(spec, **kwargs):
    options: dict[str, Any] = dict(
        feedback={"dx": 0.08, "dy": 0.06, "dz": 0.04},
        allowed_mutations=("red_apple",),
        allow_anchor_motion=True,
        max_displacement_m=0.02,
        temperature=0.0,
        max_iters=500,
    )
    options.update(kwargs)
    return oracle.relax_spec_active_inference(spec, **options)


def test_explicit_target_proposal_is_bounded_xy_copy_only(spec):
    spec.background.params["initial_pose"]["rotation_xyzw"] = [0, 0, 0, 1]
    spec.embodiment.params["finger_contact_friction"] = {"static_friction": 6.0, "dynamic_friction": 5.0}
    before = deepcopy(spec.model_dump())
    proposal, diagnostics = _propose(spec)
    old_xyz = before["objects"][0]["params"]["initial_pose"]["position_xyz"]
    new_xyz = proposal.objects[0].params["initial_pose"]["position_xyz"]
    distance = sum((a - b) ** 2 for a, b in zip(old_xyz[:2], new_xyz[:2])) ** 0.5
    assert 0 < distance <= 0.02 + 1e-9
    assert new_xyz[2] == old_xyz[2]
    assert spec.model_dump() == before
    expected = deepcopy(before)
    expected["objects"][0]["params"]["initial_pose"]["position_xyz"] = new_xyz
    assert proposal.model_dump() == expected
    assert any("proposal" in message.lower() and "unverified" in message.lower() for message in diagnostics)


@pytest.mark.parametrize(
    "converged,energy,pose",
    [
        (False, 100.0, [-0.16, 0.20, 0.0975, 0]),
        (True, float("nan"), [-0.16, 0.20, 0.0975, 0]),
        (True, 0.0, [float("nan"), 0.20, 0.0975, 0]),
    ],
)
def test_invalid_solver_result_never_applied(spec, monkeypatch, converged, energy, pose):
    from isaaclab_arena.relations.spatial_factor_graph import FactorGraphRelaxationResult

    spec.background.params["initial_pose"]["rotation_xyzw"] = [0, 0, 0, 1]
    before = deepcopy(spec.model_dump())
    monkeypatch.setattr(
        oracle.SpatialFactorGraph,
        "relax_stochastic",
        lambda *args, **kwargs: FactorGraphRelaxationResult(converged, 1, energy, {"red_apple": pose}, {}, []),
    )
    proposal, diagnostics = _propose(spec)
    assert proposal.model_dump() == before
    assert spec.model_dump() == before
    assert any("reject" in message.lower() for message in diagnostics)


@pytest.mark.parametrize("reified", [False, True])
def test_support_sector_limits_xy_proposal(spec, reified):
    spec.background.params["initial_pose"]["rotation_xyzw"] = [0, 0, 0, 1]
    spec.objects[0].params["initial_pose"]["position_xyz"][1] = 0.259
    if reified:
        spec.reified_relations = [
            ReifiedRelationSpec(
                reifier_id="apple_support",
                source_id="red_apple",
                target_id="maple_table",
                relation_type="PLACED_ON",
                surface_sector="front_left",
            )
        ]
    else:
        spec.relations.append(
            SpatialRelationSpec.model_construct(
                kind="on",
                subject="red_apple",
                reference="maple_table",
                params={"surface_sector": "front_left"},
            )
        )
    proposal, _ = _propose(spec)
    xyz = proposal.objects[0].params["initial_pose"]["position_xyz"]
    assert xyz[0] > -0.173
    assert xyz[1] <= 0.26 + 1e-9  # front_left edge minus 4 cm margin
    assert xyz[2] == 0.0975


def test_inconsistent_reified_support_is_rejected(spec):
    spec.background.params["initial_pose"]["rotation_xyzw"] = [0, 0, 0, 1]
    spec.reified_relations = [
        ReifiedRelationSpec(
            reifier_id="apple_support",
            source_id="red_apple",
            target_id="maple_table",
            relation_type="PLACED_ON",
            surface_sector="front_right",
        )
    ]
    before = deepcopy(spec.model_dump())
    proposal, diagnostics = _propose(spec)
    assert proposal.model_dump() == before
    assert any("support" in message.lower() and "reject" in message.lower() for message in diagnostics)


@pytest.mark.parametrize(
    "feedback",
    [
        {"dx": 0.01, "dy": 0.0},
        {"dx": float("nan"), "dy": 0.0, "dz": 0.0},
        {"dx": 0.01, "dy": 0.0, "dz": float("inf")},
        {"dx": "bad", "dy": 0.0, "dz": 0.0},
    ],
)
def test_incomplete_or_nonfinite_feedback_is_rejected(spec, feedback):
    spec.background.params["initial_pose"]["rotation_xyzw"] = [0, 0, 0, 1]
    before = deepcopy(spec.model_dump())
    proposal, diagnostics = _propose(spec, feedback=feedback)
    assert proposal.model_dump() == before
    assert any("feedback" in msg.lower() and "reject" in msg.lower() for msg in diagnostics)


@pytest.mark.parametrize("bound", [0.0, -0.01, float("nan"), float("inf")])
def test_invalid_trust_bound_is_rejected(spec, bound):
    with pytest.raises(AssertionError, match="max_displacement_m"):
        _propose(spec, max_displacement_m=bound)


def test_seeded_proposals_repeat_without_global_rng_changes(spec):
    import torch

    spec.background.params["initial_pose"]["rotation_xyzw"] = [0, 0, 0, 1]
    state = torch.random.get_rng_state().clone()
    first, _ = _propose(spec, seed=17, temperature=0.08)
    second, _ = _propose(spec, seed=17, temperature=0.08)
    assert first.model_dump() == second.model_dump()
    assert first.objects[0].params != spec.objects[0].params
    assert torch.equal(state, torch.random.get_rng_state())


@pytest.mark.parametrize("asset_name", ["objects", "embodiment"])
def test_missing_pose_rejects_without_inventing_origin(spec, asset_name):
    spec.background.params["initial_pose"]["rotation_xyzw"] = [0, 0, 0, 1]
    asset = spec.objects[0] if asset_name == "objects" else spec.embodiment
    del asset.params["initial_pose"]
    before = deepcopy(spec.model_dump())
    proposal, diagnostics = _propose(spec)
    assert proposal.model_dump() == before
    assert any("reject" in msg.lower() for msg in diagnostics)


def test_feedback_for_other_target_is_rejected(spec):
    spec.background.params["initial_pose"]["rotation_xyzw"] = [0, 0, 0, 1]
    before = deepcopy(spec.model_dump())
    proposal, diagnostics = _propose(spec, feedback={"dx": 0.01, "dy": 0.01, "dz": 0, "reifier_id": "plate_support"})
    assert proposal.model_dump() == before
    assert any("feedback" in msg.lower() and "reject" in msg.lower() for msg in diagnostics)


def test_reified_vertical_contract_is_not_silently_ignored(spec):
    spec.background.params["initial_pose"]["rotation_xyzw"] = [0, 0, 0, 1]
    spec.reified_relations = [
        ReifiedRelationSpec(
            reifier_id="apple_support",
            source_id="red_apple",
            target_id="maple_table",
            relation_type="PLACED_ON",
            surface_sector="front_left",
            delta_z={"min_val": 0.0, "max_val": 0.001, "nominal": 0.0},
        )
    ]
    before = deepcopy(spec.model_dump())
    proposal, diagnostics = _propose(spec)
    assert proposal.model_dump() == before
    assert any("support" in msg.lower() and "reject" in msg.lower() for msg in diagnostics)


@pytest.mark.parametrize("sector,normal", [("unresolved_patch", (0, 0, 1)), ("front_left", (1, 0, 0))])
def test_unresolved_or_nonhorizontal_support_rejected(spec, sector, normal):
    spec.background.params["initial_pose"]["rotation_xyzw"] = [0, 0, 0, 1]
    spec.reified_relations = [
        ReifiedRelationSpec(
            reifier_id="apple_support",
            source_id="red_apple",
            target_id="maple_table",
            relation_type="PLACED_ON",
            surface_sector=sector,
            contact_normal=normal,
        )
    ]
    before = deepcopy(spec.model_dump())
    proposal, diagnostics = _propose(spec)
    assert proposal.model_dump() == before
    assert any("support" in msg.lower() and "reject" in msg.lower() for msg in diagnostics)


def test_saved_c1_v32_proposal_preserves_contract():
    path = (
        Path(__file__).resolve().parents[2]
        / "generated_envs/g1_tabletop_apple_to_plate/v32/g1_tabletop_apple_to_plate.yaml"
    )
    if not path.is_file():
        pytest.skip("Local saved C1 v32 artifact is not part of a fresh clone")
    data = yaml.safe_load(path.read_text())
    # Keep the actual saved schema and values, without loading simulator asset registries.
    data["embodiment"] = AssetSpec.model_construct(**data["embodiment"])
    data["background"] = AssetSpec.model_construct(**data["background"])
    data["objects"] = [AssetSpec.model_construct(**obj) for obj in data["objects"]]
    data["relations"] = [SpatialRelationSpec.model_construct(**rel) for rel in data["relations"]]
    data["task"]["subtasks"] = [TaskSpec.model_construct(**task) for task in data["task"]["subtasks"]]
    data["task"]["composition"] = TaskCompositionType(data["task"]["composition"])
    data["task"] = CompositeTaskSpec.model_construct(**data["task"])
    saved = ArenaEnvGraphSpec.model_construct(**data)
    before = deepcopy(saved.model_dump())
    unchanged, _ = _propose(saved, feedback={})
    assert unchanged.model_dump() == before
    assert oracle.validate_kinematic_reachability(saved) == []
    proposal, diagnostics = _propose(saved, seed=23)
    xyz = proposal.objects[0].params["initial_pose"]["position_xyz"]
    assert xyz != before["objects"][0]["params"]["initial_pose"]["position_xyz"]
    assert xyz[2] == 0.0975
    assert saved.model_dump() == before
    expected = deepcopy(before)
    expected["objects"][0]["params"]["initial_pose"]["position_xyz"] = xyz
    assert proposal.model_dump() == expected
    assert any("unverified" in msg.lower() for msg in diagnostics)


def test_feedback_reader_failure_leaves_copy_unchanged(spec):
    calls = []

    def unavailable(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("offline")

    before = deepcopy(spec.model_dump())
    proposal, diagnostics = oracle.relax_spec_active_inference(
        spec,
        parent_env_name="exact_parent",
        eval_id="run_1",
        feedback_fetcher=unavailable,
    )
    assert calls == [{"env_name": "exact_parent", "eval_id": "run_1"}]
    assert proposal.model_dump() == before
    assert proposal is not spec
    assert any("offline" in msg for msg in diagnostics)


@pytest.mark.parametrize(
    "allowed", [("g1_robot",), ("maple_table",), ("clay_plate",), ("red_apple", "clay_plate"), ("camera",)]
)
def test_allowlist_never_authorizes_fixed_assets(spec, allowed):
    before = deepcopy(spec.model_dump())
    proposal, _ = _propose(spec, allowed_mutations=allowed)
    assert proposal.model_dump() == before


@pytest.mark.parametrize("root_z", [-0.0445, 0.0007, 0.09543, 0.72])
def test_g1_frame_is_translation_invariant(spec, root_z):
    offset = root_z - spec.embodiment.params["initial_pose"]["position_xyz"][2]
    for asset in [spec.embodiment, spec.background, *spec.objects]:
        asset.params["initial_pose"]["position_xyz"][2] += offset
    assert oracle.validate_kinematic_reachability(spec) == []


def test_g1_named_asset_does_not_change_other_robot_frame_contract(spec):
    spec.embodiment.registry_name = "franka"
    assert oracle.validate_kinematic_reachability(spec) == []


def test_g1_low_root_is_pelvis(spec):
    assert oracle.validate_kinematic_reachability(spec) == []


def test_depth_uses_declared_g1_pelvis_height(spec, monkeypatch):
    cameras = []
    monkeypatch.setattr(oracle, "_project_to_image_plane", lambda obj, cam, *args: cameras.append(cam))
    oracle.validate_depth_alignment(spec)
    assert cameras[0][2] == pytest.approx(0.0007 + 0.15 + 0.35325)


def test_depth_does_not_apply_g1_camera_to_other_robots(spec, monkeypatch):
    spec.embodiment.registry_name = "franka"

    def unexpected(*args):
        pytest.fail("G1 camera model applied to another embodiment")

    monkeypatch.setattr(oracle, "_project_to_image_plane", unexpected)
    assert oracle.validate_depth_alignment(spec) == []


def test_feedback_reader_receives_exact_version_and_relation():
    from pathlib import Path

    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    root = Path(__file__).resolve().parents[2]
    spec = ArenaEnvGraphSpec.from_yaml(
        root / "generated_envs/g1_tabletop_apple_to_plate/v32/g1_tabletop_apple_to_plate.yaml"
    )
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)

    oracle.relax_spec_active_inference(
        spec,
        parent_env_name="immutable_scene",
        eval_id="run42",
        env_version="sha256",
        reifier_id="support_red_apple",
        feedback_fetcher=fetch,
    )
    assert calls == [
        {"env_name": "immutable_scene", "eval_id": "run42", "env_version": "sha256", "reifier_id": "support_red_apple"}
    ]
