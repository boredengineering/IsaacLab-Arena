# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for RDF-star lowering into ArenaEnvGraphSpec."""

from __future__ import annotations

import rdflib
import pytest

from isaaclab_arena.agentic_environment_generation.rdf_lowering import lower_rdf_graph_to_spec
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

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
    from isaaclab_arena.agentic_environment_generation.rdf_lowering import spec_to_rdf_graph
    from isaaclab_arena.agentic_environment_generation.rdf_validation import validate_rdf_environment_graph

    graph = rdflib.Graph()
    graph.parse(data=SCENE_WITH_OBJECTS_TTL, format="turtle")
    spec = lower_rdf_graph_to_spec(graph)

    lifted_graph = spec_to_rdf_graph(spec)
    conforms, report = validate_rdf_environment_graph(lifted_graph)
    assert conforms, f"Lifted graph failed SHACL validation:\n{report}"
