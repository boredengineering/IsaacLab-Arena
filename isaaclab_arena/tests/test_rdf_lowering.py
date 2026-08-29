# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for RDF-star lowering and 3D bipedal capability manifolds."""

from __future__ import annotations

import numpy as np
import pytest
import rdflib

from isaaclab_arena.agentic_environment_generation.rdf_lowering import (
    BipedalCapabilityProfile,
    compile_reified_scene_transforms,
    lower_rdf_graph_to_spec,
    sample_bipedal_reach_manifold,
    spec_to_rdf_graph,
)
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environment_spec.arena_env_graph_types import (
    AssetSpec,
    CompositeTaskSpec,
    ContinuousIntervalSpec,
    ReifiedRelationSpec,
    SpatialRelationSpec,
    TaskCompositionType,
    TaskSpec,
)

SCENE_WITH_OBJECTS_TTL = """
@prefix :      <https://isaac-sim.github.io/arena/instances/> .
@prefix arena: <https://isaac-sim.github.io/arena/schema#> .
@prefix prov:  <http://www.w3.org/ns/prov#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

:scene_g1 a arena:EnvironmentGraph, prov:Entity ;
    arena:envName "g1_box_sorting_demo" ;
    arena:hasTerrain :ground_plane ;
    arena:hasEmbodiment :g1_robot ;
    arena:hasFixture :galileo_room ;
    arena:hasObject :brown_box, :blue_bin .

:ground_plane a arena:Terrain ;
    arena:registryName "default_ground_plane" .

:g1_robot a arena:Embodiment ;
    arena:registryName "g1_wbc_joint" .

:galileo_room a arena:Fixture ;
    arena:registryName "galileo_locomanip" .

:brown_box a arena:RigidObject ;
    arena:registryName "brown_box" ;
    arena:placedOn :galileo_room ;
    arena:surfaceAnchor "shelf_tier_1" ;
    arena:nominalHeight 0.0707 .

:blue_bin a arena:RigidObject ;
    arena:registryName "blue_sorting_bin" ;
    arena:placedOn :galileo_room ;
    arena:surfaceAnchor "floor_zone" ;
    arena:nominalHeight -0.2641 .
"""


def test_lower_rdf_graph_to_spec():
    graph = rdflib.Graph()
    graph.parse(data=SCENE_WITH_OBJECTS_TTL, format="turtle")

    spec = lower_rdf_graph_to_spec(graph)
    assert isinstance(spec, ArenaEnvGraphSpec)
    assert spec.env_name == "g1_box_sorting_demo"
    assert spec.embodiment.registry_name == "g1_wbc_joint"
    assert spec.background.registry_name == "galileo_locomanip"
    assert len(spec.objects) == 2
    assert {obj.registry_name for obj in spec.objects} == {"brown_box", "blue_sorting_bin"}

    assert len(spec.relations) == 2
    box_rel = next(r for r in spec.relations if r.subject == "brown_box")
    assert box_rel.kind == "on"
    assert box_rel.reference == "galileo_room"
    assert box_rel.params.get("surface_anchor") == "shelf_tier_1"
    assert abs(box_rel.params.get("nominal_height", 0.0) - 0.0707) < 1e-4

    assert len(spec.task.subtasks) == 1
    assert spec.task.subtasks[0].kind == "PickAndPlaceTask"


def test_spec_to_rdf_graph_lifting_and_validation():
    from isaaclab_arena.agentic_environment_generation.rdf_validation import validate_rdf_environment_graph

    graph = rdflib.Graph()
    graph.parse(data=SCENE_WITH_OBJECTS_TTL, format="turtle")
    spec = lower_rdf_graph_to_spec(graph)

    lifted_graph = spec_to_rdf_graph(spec)
    conforms, report = validate_rdf_environment_graph(lifted_graph)
    assert conforms, f"Lifted graph failed SHACL validation:\n{report}"


def test_bipedal_capability_profile_standoff_elevation_mapping():
    """Verify that BipedalCapabilityProfile adjusts standoff distance across elevations."""
    profile = BipedalCapabilityProfile(
        embodiment_name="unitree_g1",
        min_dexterous_height=0.30,
        max_dexterous_height=1.35,
    )

    # 1. High Tier (1.20m) -> closer standoff (~0.52m)
    standoff_high, _, dex_high = profile.evaluate_optimal_standoff(1.20)
    assert 0.50 <= standoff_high <= 0.55
    assert dex_high > 0.80

    # 2. Chest Height (0.85m) -> optimal manipulability (~0.65m)
    standoff_mid, _, dex_mid = profile.evaluate_optimal_standoff(0.85)
    assert np.isclose(standoff_mid, 0.65, atol=0.02)
    assert dex_mid >= 0.95

    # 3. Crouch Low Tier (0.45m) -> wider standoff (~0.79m)
    standoff_low, _, dex_low = profile.evaluate_optimal_standoff(0.45)
    assert standoff_low > standoff_mid
    assert dex_low >= 0.65


def test_sample_bipedal_reach_manifold():
    """Verify that sample_bipedal_reach_manifold outputs valid robot base poses."""
    target_pos = [1.0, 0.0, 0.85]
    floor_z = 0.0
    approach_yaw = [-20.0, 20.0]

    robot_xy, robot_yaw, dexterity = sample_bipedal_reach_manifold(
        target_world_xyz=target_pos,
        z_floor_estimate=floor_z,
        approach_yaw_range=approach_yaw,
    )

    # Robot should stand in front of the target along X axis
    assert np.isclose(robot_xy[0], 0.35, atol=0.05)
    assert np.isclose(robot_xy[1], 0.0, atol=0.05)
    assert np.isclose(robot_yaw, 0.0, atol=2.0)
    assert dexterity > 0.90


def test_compile_reified_scene_transforms():
    """Verify that compile_reified_scene_transforms grounds all scene entities."""
    spec = ArenaEnvGraphSpec(
        env_name="test_compile_env",
        embodiment=AssetSpec(id="g1", registry_name="g1_wbc_joint"),
        background=AssetSpec(id="galileo", registry_name="galileo_locomanip"),
        objects=[
            AssetSpec(id="brown_box", registry_name="brown_box"),
        ],
        relations=[
            SpatialRelationSpec(kind="is_anchor", subject="galileo"),
            SpatialRelationSpec(kind="on", subject="brown_box", reference="galileo"),
        ],
        task=CompositeTaskSpec(
            composition=TaskCompositionType.ATOMIC,
            description="Pick brown box",
            subtasks=[TaskSpec(kind="PickAndPlaceTask", params={"pick_up_object": "brown_box", "destination_location": "galileo"})],
        ),
    )

    transforms = compile_reified_scene_transforms(spec, floor_z=-0.795)
    assert "brown_box" in transforms
    assert "g1" in transforms
    # Check that robot is grounded at floor_z
    robot_pose = transforms["g1"]
    assert np.isclose(robot_pose[2], -0.795, atol=1e-3)
