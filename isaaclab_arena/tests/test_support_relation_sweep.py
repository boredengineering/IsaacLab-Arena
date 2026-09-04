# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the support-relation sweep generator.

The generator operates on plain spec dicts, so these run without Isaac Sim.
"""

from __future__ import annotations

from typing import Any

import pytest

from isaaclab_arena.agentic_environment_generation.support_relation_sweep import (
    ANCHOR_MATCH_TOLERANCE_M,
    generate_support_height_sweep_dicts,
)

# galileo_locomanip declares decks at -0.03, +0.50, +0.90 in FIXTURE_SECTOR_BOUNDS. The G1's
# articulation root IS its pelvis (measured 2026-09-03), so with the stub embodiment's root at
# z=0.0 the pelvis-relative offsets are the deck heights themselves.
#
# Note tier_2 and tier_3 sit 0.50 m and 0.90 m *above* the pelvis, i.e. above the shoulder
# (+0.292); they are overhead reaches, not tabletop ones. They remain valid as height-sensitivity
# probes but are not a gentle sweep -- see the implementation plan.
TIER_1_OFFSET = -0.03
TIER_2_OFFSET = 0.50
TIER_3_OFFSET = 0.90


def _spec_dict(fixture_registry: str = "galileo_locomanip", sector: str = "shelf_tier_1") -> dict[str, Any]:
    return {
        "env_name": "sweep_base",
        "embodiment": {
            "id": "g1",
            "registry_name": "g1_wbc_agile_joint",
            "params": {"initial_pose": {"position_xyz": [-0.46, 0.0, 0.0], "rotation_xyzw": [0, 0, 0, 1]}},
        },
        "background": {
            "id": "support",
            "registry_name": fixture_registry,
            "params": {"initial_pose": {"position_xyz": [-0.58, 0.0, 0.0], "rotation_xyzw": [0, 0, 0, 1]}},
        },
        "objects": [
            {"id": "red_apple", "registry_name": "apple_01_objaverse_robolab"},
            {"id": "clay_plate", "registry_name": "clay_plates_hot3d_robolab"},
        ],
        "relations": [
            {"kind": "on", "subject": "red_apple", "reference": "support", "params": {"surface_sector": sector}},
        ],
        "reified_relations": [{
            "reifier_id": "reifier_apple_support",
            "source_id": "red_apple",
            "relation_type": "PLACED_ON",
            "target_id": "support",
            "kinematic_manifold": "low_shelf_reach_down",
            "evidence_sources": ["tabletop_spatial_planner"],
        }],
        "task": {"composition": "atomic", "description": "move the apple to the plate", "subtasks": []},
    }


def _offset_of(variant) -> float:
    return variant.achieved_offset_m


def test_anchor_realization_selects_declared_decks():
    """Each requested offset should land on the shelf tier that actually exists there."""
    variants = generate_support_height_sweep_dicts(
        _spec_dict(), [TIER_1_OFFSET, TIER_2_OFFSET, TIER_3_OFFSET], realization="anchor"
    )
    assert all(v.emitted for v in variants), [v.to_dict() for v in variants]
    assert [v.anchor_name for v in variants] == ["shelf_tier_1", "shelf_tier_2", "shelf_tier_3"]

    for variant, expected in zip(variants, [TIER_1_OFFSET, TIER_2_OFFSET, TIER_3_OFFSET]):
        assert _offset_of(variant) == pytest.approx(expected, abs=0.02)
        relation = next(r for r in variant.spec_dict["relations"] if r["subject"] == "red_apple")
        assert relation["params"]["surface_sector"] == variant.anchor_name


def test_variants_differ_only_in_the_support_relation():
    """The whole point of the sweep: one edit, everything else byte-identical."""
    base = _spec_dict()
    variants = generate_support_height_sweep_dicts(base, [TIER_1_OFFSET, TIER_3_OFFSET], realization="anchor")
    first, second = (v.spec_dict for v in variants)

    assert first["embodiment"] == second["embodiment"]
    assert first["background"] == second["background"]
    assert first["objects"] == second["objects"]
    assert first["task"] == second["task"]

    rel_a = next(r for r in first["relations"] if r["subject"] == "red_apple")
    rel_b = next(r for r in second["relations"] if r["subject"] == "red_apple")
    keys = set(rel_a["params"]) | set(rel_b["params"])
    differing = {k for k in keys if rel_a["params"].get(k) != rel_b["params"].get(k)}
    assert differing == {"surface_sector"}, f"expected only surface_sector to differ, got {differing}"


def test_base_spec_is_never_mutated():
    """A generator that edits its input corrupts every subsequent variant."""
    base = _spec_dict()
    snapshot = str(base)
    generate_support_height_sweep_dicts(base, [TIER_3_OFFSET], realization="fixture")
    generate_support_height_sweep_dicts(base, [TIER_3_OFFSET], realization="anchor")
    assert str(base) == snapshot


def test_anchor_realization_refuses_offsets_with_no_declared_deck():
    """Refusing beats emitting a scene where the object would spawn in mid-air."""
    unsupported = TIER_1_OFFSET + 0.25  # between tier 1 and tier 2, no deck there
    variants = generate_support_height_sweep_dicts(_spec_dict(), [unsupported], realization="anchor")

    assert len(variants) == 1
    assert not variants[0].emitted
    assert variants[0].spec_dict is None
    assert any("refusing to emit" in note for note in variants[0].notes)


def test_auto_falls_back_to_fixture_translation():
    """``auto`` uses an anchor where one fits and translates the fixture where none does."""
    unsupported = TIER_1_OFFSET + 0.25
    variants = generate_support_height_sweep_dicts(_spec_dict(), [TIER_3_OFFSET, unsupported], realization="auto")

    assert variants[0].realization == "anchor"
    assert variants[0].anchor_name == "shelf_tier_3"
    assert variants[1].realization == "fixture"
    assert variants[1].emitted
    assert _offset_of(variants[1]) == pytest.approx(unsupported)


def test_fixture_translation_moves_the_fixture_by_the_right_delta():
    base = _spec_dict(sector="shelf_tier_1")
    target = TIER_3_OFFSET
    variant = generate_support_height_sweep_dicts(base, [target], realization="fixture")[0]

    assert variant.emitted
    original_z = base["background"]["params"]["initial_pose"]["position_xyz"][2]
    new_z = variant.spec_dict["background"]["params"]["initial_pose"]["position_xyz"][2]
    # tier_1 deck is at -0.03; reaching a +0.90 pelvis-relative offset needs +0.93 of lift.
    assert new_z - original_z == pytest.approx(0.93, abs=0.02)


def test_platform_realization_moves_the_embodiment_the_other_way():
    """Lowering the robot raises the support relative to it, so the sign must invert."""
    base = _spec_dict(sector="shelf_tier_1")
    variant = generate_support_height_sweep_dicts(base, [TIER_3_OFFSET], realization="platform")[0]

    assert variant.emitted
    original_z = base["embodiment"]["params"]["initial_pose"]["position_xyz"][2]
    new_z = variant.spec_dict["embodiment"]["params"]["initial_pose"]["position_xyz"][2]
    assert new_z < original_z, "raising the support offset means lowering the robot"
    assert any("platform must be added" in note for note in variant.notes)


def test_undetermined_base_height_is_refused_for_translation():
    """Without a resolvable base support height, a delta cannot be computed without guessing."""
    base = _spec_dict(fixture_registry="unknown_fixture_xyz", sector="mystery_deck")
    variants = generate_support_height_sweep_dicts(base, [TIER_3_OFFSET], realization="fixture")
    assert not variants[0].emitted
    assert any("undetermined" in note for note in variants[0].notes)


def test_variant_records_realization_and_manifold_for_reconstruction():
    variants = generate_support_height_sweep_dicts(_spec_dict(), [TIER_1_OFFSET], realization="anchor")
    variant = variants[0]

    # tier_1 sits ~at pelvis height, which is the tabletop envelope.
    assert variant.manifold == "tabletop_stationary_reach"
    reified = variant.spec_dict["reified_relations"][0]
    assert reified["kinematic_manifold"] == "tabletop_stationary_reach"
    assert any("support_relation_sweep:anchor" in source for source in reified["evidence_sources"])
    # The original provenance entry must survive alongside the new one.
    assert "tabletop_spatial_planner" in reified["evidence_sources"]


def test_offsets_outside_every_envelope_are_left_unclassified():
    """tier_3 sits 0.90 m above the pelvis - 0.6 m above the shoulder, beyond the arm.

    ``resolve_manifold_for_offset`` returning None is the honest answer, and it flags that this
    tier is not a usable sweep condition: a failure there would confound "the policy cannot" with
    "the robot cannot reach".
    """
    variant = generate_support_height_sweep_dicts(_spec_dict(), [TIER_3_OFFSET], realization="anchor")[0]
    assert variant.emitted
    assert variant.manifold is None


def test_tied_deck_heights_keep_the_base_sector_family():
    """galileo declares front_center/front_left/front_right/shelf_tier_1 all at the same z.

    Those sectors have different *lateral* bounds, so picking arbitrarily among them would change
    laterality as a side effect of a height sweep -- confounding the contrast being measured.
    """
    variants = generate_support_height_sweep_dicts(
        _spec_dict(sector="shelf_tier_1"), [TIER_1_OFFSET], realization="anchor"
    )
    assert variants[0].anchor_name == "shelf_tier_1"

    # Starting from a front_* sector, the same offset should stay in that family.
    variants = generate_support_height_sweep_dicts(
        _spec_dict(sector="front_left"), [TIER_1_OFFSET], realization="anchor"
    )
    assert variants[0].anchor_name.startswith("front_")


def test_env_name_is_suffixed_so_variants_do_not_collide():
    variants = generate_support_height_sweep_dicts(_spec_dict(), [TIER_1_OFFSET], realization="anchor")
    assert variants[0].spec_dict["env_name"] == "sweep_base_support_sweep"


def test_missing_manipuland_reports_rather_than_crashes():
    base = _spec_dict()
    base["objects"] = [{"id": "clay_plate", "registry_name": "clay_plates_hot3d_robolab"}]
    variants = generate_support_height_sweep_dicts(base, [TIER_1_OFFSET])
    assert not variants[0].emitted
    assert "no manipuland" in variants[0].notes[0]


def test_anchor_tolerance_is_respected_at_the_boundary():
    """An offset just inside the tolerance is accepted; just outside is refused."""
    inside = TIER_3_OFFSET + ANCHOR_MATCH_TOLERANCE_M * 0.5
    outside = TIER_3_OFFSET + ANCHOR_MATCH_TOLERANCE_M * 2.0
    accepted = generate_support_height_sweep_dicts(_spec_dict(), [inside], realization="anchor")[0]
    refused = generate_support_height_sweep_dicts(_spec_dict(), [outside], realization="anchor")[0]
    assert accepted.emitted and accepted.anchor_name == "shelf_tier_3"
    assert not refused.emitted


def test_unknown_realization_is_rejected():
    with pytest.raises(AssertionError, match="unknown realization"):
        generate_support_height_sweep_dicts(_spec_dict(), [0.0], realization="teleport")
