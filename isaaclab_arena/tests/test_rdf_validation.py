# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for RDF-star and SHACL validation in agentic environment generation."""

from __future__ import annotations

import rdflib
import pytest

from isaaclab_arena.agentic_environment_generation.rdf_validation import validate_rdf_environment_graph

VALID_SCENE_TTL = """
@prefix :      <https://isaac-sim.github.io/arena/instances/> .
@prefix arena: <https://isaac-sim.github.io/arena/schema#> .
@prefix prov:  <http://www.w3.org/ns/prov#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

:scene_001 a arena:EnvironmentGraph, prov:Entity ;
    arena:envName "valid_g1_box_pnp" ;
    arena:hasTerrain :ground_plane ;
    arena:hasEmbodiment :g1_robot ;
    arena:hasFixture :room ;
    arena:hasObject :box, :bin .

:ground_plane a arena:Terrain ;
    arena:registryName "default_ground_plane" .

:g1_robot a arena:Embodiment ;
    arena:registryName "g1_wbc_joint" ;
    arena:controllerBinding "g1_decoupled_wbc_pink_action" ;
    arena:numEnvs 1 .

:room a arena:Fixture ;
    arena:registryName "galileo_locomanip" .

:box a arena:RigidObject ;
    arena:registryName "brown_box" ;
    arena:placedOn :room .

:bin a arena:RigidObject ;
    arena:registryName "blue_sorting_bin" ;
    arena:placedOn :room .

:scene_001 arena:minClearanceRadius 0.75 .
"""

MISSING_TERRAIN_TTL = """
@prefix :      <https://isaac-sim.github.io/arena/instances/> .
@prefix arena: <https://isaac-sim.github.io/arena/schema#> .

:scene_002 a arena:EnvironmentGraph ;
    arena:envName "invalid_no_terrain" ;
    arena:hasEmbodiment :robot .

:robot a arena:Embodiment ;
    arena:registryName "unitree_g1" .
"""

PINK_WBC_MULTI_ENV_TTL = """
@prefix :      <https://isaac-sim.github.io/arena/instances/> .
@prefix arena: <https://isaac-sim.github.io/arena/schema#> .

:scene_003 a arena:EnvironmentGraph ;
    arena:envName "invalid_pink_multi_env" ;
    arena:hasTerrain :ground ;
    arena:hasEmbodiment :g1_robot .

:ground a arena:Terrain ;
    arena:registryName "default_ground_plane" .

:g1_robot a arena:Embodiment ;
    arena:registryName "g1_wbc_joint" ;
    arena:controllerBinding "g1_decoupled_wbc_pink_action" ;
    arena:numEnvs 4 .
"""

NARROW_CLEARANCE_TTL = """
@prefix :      <https://isaac-sim.github.io/arena/instances/> .
@prefix arena: <https://isaac-sim.github.io/arena/schema#> .

:scene_004 a arena:EnvironmentGraph ;
    arena:envName "invalid_narrow_corridor" ;
    arena:hasTerrain :ground ;
    arena:hasEmbodiment :robot ;
    arena:minClearanceRadius 0.35 .

:ground a arena:Terrain ;
    arena:registryName "default_ground_plane" .

:robot a arena:Embodiment ;
    arena:registryName "unitree_g1" .
"""


def test_valid_environment_graph_conforms():
    graph = rdflib.Graph()
    graph.parse(data=VALID_SCENE_TTL, format="turtle")
    conforms, report = validate_rdf_environment_graph(graph)
    assert conforms, f"Expected valid scene to conform, got report:\n{report}"


def test_missing_terrain_fails_shacl():
    graph = rdflib.Graph()
    graph.parse(data=MISSING_TERRAIN_TTL, format="turtle")
    conforms, report = validate_rdf_environment_graph(graph)
    assert not conforms
    assert "MandatoryTerrainShape" in report or "terrain" in report.lower()


def test_pink_wbc_multi_env_fails_shacl():
    graph = rdflib.Graph()
    graph.parse(data=PINK_WBC_MULTI_ENV_TTL, format="turtle")
    conforms, report = validate_rdf_environment_graph(graph)
    assert not conforms
    assert "Pink WBC" in report or "num_envs" in report.lower()


def test_narrow_corridor_clearance_fails_shacl():
    graph = rdflib.Graph()
    graph.parse(data=NARROW_CLEARANCE_TTL, format="turtle")
    conforms, report = validate_rdf_environment_graph(graph)
    assert not conforms
    assert "0.60" in report or "clearance" in report.lower()
