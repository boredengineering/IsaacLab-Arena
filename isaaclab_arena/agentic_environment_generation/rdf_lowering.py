# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Lowering compiler and bidirectional lifting between RDF-star knowledge graphs and ArenaEnvGraphSpec."""

from __future__ import annotations

from typing import Any
import rdflib
from rdflib import Literal, Namespace, RDF, XSD

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environment_spec.arena_env_graph_types import (
    AssetSpec,
    CompositeTaskSpec,
    SpatialRelationSpec,
    TaskCompositionType,
    TaskSpec,
)

ARENA = Namespace("https://isaac-sim.github.io/arena/schema#")
PROV = Namespace("http://www.w3.org/ns/prov#")
INSTANCES = Namespace("https://isaac-sim.github.io/arena/instances/")

SPARQL_SCENE_METADATA = """
PREFIX arena: <https://isaac-sim.github.io/arena/schema#>
SELECT ?scene ?env_name ?terrain ?terrain_reg ?robot ?robot_reg ?bg ?bg_reg ?clearance
WHERE {
    ?scene a arena:EnvironmentGraph .
    OPTIONAL { ?scene arena:envName ?env_name . }
    OPTIONAL { ?scene arena:minClearanceRadius ?clearance . }
    OPTIONAL {
        ?scene arena:hasTerrain ?terrain .
        ?terrain arena:registryName ?terrain_reg .
    }
    OPTIONAL {
        ?scene arena:hasEmbodiment ?robot .
        ?robot arena:registryName ?robot_reg .
    }
    OPTIONAL {
        ?scene arena:hasFixture ?bg .
        ?bg arena:registryName ?bg_reg .
    }
}
"""

SPARQL_OBJECTS = """
PREFIX arena: <https://isaac-sim.github.io/arena/schema#>
SELECT ?obj ?obj_reg
WHERE {
    ?scene a arena:EnvironmentGraph ;
           arena:hasObject ?obj .
    ?obj arena:registryName ?obj_reg .
}
"""

SPARQL_RELATIONS = """
PREFIX arena: <https://isaac-sim.github.io/arena/schema#>
SELECT ?subj ?pred ?ref ?anchor ?nominal_z ?bound_x_min ?bound_x_max ?bound_y_min ?bound_y_max
WHERE {
    {
        ?subj arena:placedOn ?ref .
        BIND("on" AS ?pred)
        OPTIONAL { ?subj arena:surfaceAnchor ?anchor . }
        OPTIONAL { ?subj arena:nominalHeight ?nominal_z . }
        OPTIONAL { ?subj arena:boundXMin ?bound_x_min . }
        OPTIONAL { ?subj arena:boundXMax ?bound_x_max . }
        OPTIONAL { ?subj arena:boundYMin ?bound_y_min . }
        OPTIONAL { ?subj arena:boundYMax ?bound_y_max . }
    }
    UNION
    {
        ?subj arena:placedInside ?ref .
        BIND("inside" AS ?pred)
    }
    UNION
    {
        ?subj arena:navCorridorTo ?ref .
        BIND("nav_corridor" AS ?pred)
    }
}
"""


def _extract_id_from_uri(uri: Any, fallback: str = "") -> str:
    """Extract human-readable resource ID from URI, handling both '#' and '/' delimiters."""
    if uri is None:
        return fallback
    s = str(uri)
    if "#" in s:
        extracted = s.rsplit("#", 1)[-1].strip()
        return extracted if extracted else fallback
    if "/" in s:
        extracted = s.rsplit("/", 1)[-1].strip()
        return extracted if extracted else fallback
    return s if s else fallback


def lower_rdf_graph_to_spec(graph: rdflib.Graph) -> ArenaEnvGraphSpec:
    """Lower an RDF-star graph into a validated Pydantic ArenaEnvGraphSpec.

    Args:
        graph: Parsed RDF graph containing scene nodes and entities.

    Returns:
        A validated ArenaEnvGraphSpec ready for simulation compilation.
    """
    meta_rows = list(graph.query(SPARQL_SCENE_METADATA))
    assert meta_rows, "Graph does not contain a valid arena:EnvironmentGraph instance."
    first = meta_rows[0]

    env_name = str(first.env_name) if first.env_name else "agentic_rdf_env"
    robot_id = _extract_id_from_uri(first.robot, "robot")
    robot_reg = str(first.robot_reg) if first.robot_reg else "unitree_g1"
    bg_id = _extract_id_from_uri(first.bg, "background")
    bg_reg = str(first.bg_reg) if first.bg_reg else "default_ground_plane"

    objects: list[AssetSpec] = []
    for row in graph.query(SPARQL_OBJECTS):
        obj_id = _extract_id_from_uri(row.obj, "obj")
        obj_reg = str(row.obj_reg)
        objects.append(AssetSpec(id=obj_id, registry_name=obj_reg))

    relations: list[SpatialRelationSpec] = []
    for row in graph.query(SPARQL_RELATIONS):
        subj_id = _extract_id_from_uri(row.subj)
        ref_id = _extract_id_from_uri(row.ref)
        pred = str(row.pred) if row.pred else "on"
        rel_params: dict[str, Any] = {}
        if row.nominal_z is not None:
            rel_params["nominal_height"] = float(row.nominal_z)
        if row.anchor is not None:
            rel_params["surface_anchor"] = str(row.anchor)
        if row.bound_x_min is not None and row.bound_x_max is not None:
            rel_params["bound_x"] = [float(row.bound_x_min), float(row.bound_x_max)]
        if row.bound_y_min is not None and row.bound_y_max is not None:
            rel_params["bound_y"] = [float(row.bound_y_min), float(row.bound_y_max)]

        relations.append(
            SpatialRelationSpec(
                kind=pred,
                subject=subj_id,
                reference=ref_id if ref_id else None,
                params=rel_params,
            )
        )

    # Construct default root task for objects if present
    subtasks = []
    if objects:
        subtasks.append(
            TaskSpec(
                kind="PickAndPlaceTask",
                params={
                    "pick_up_object": objects[0].id,
                    "destination_location": objects[1].id if len(objects) > 1 else bg_id,
                },
            )
        )
    else:
        subtasks.append(TaskSpec(kind="NoTask", params={}))

    spec_dict: dict[str, Any] = {
        "env_name": env_name,
        "embodiment": AssetSpec(id=robot_id, registry_name=robot_reg),
        "background": AssetSpec(id=bg_id, registry_name=bg_reg),
        "objects": objects,
        "relations": relations,
        "task": CompositeTaskSpec(
            composition=TaskCompositionType.ATOMIC,
            description="Agentic task lowered from RDF-star",
            subtasks=subtasks,
        ),
    }
    return ArenaEnvGraphSpec(**spec_dict)


def spec_to_rdf_graph(spec: ArenaEnvGraphSpec) -> rdflib.Graph:
    """Lift an ArenaEnvGraphSpec into an RDF-star knowledge graph for SHACL validation.

    Args:
        spec: The input ArenaEnvGraphSpec.

    Returns:
        An rdflib.Graph populated with scene nodes, entities, and spatial relations.
    """
    g = rdflib.Graph()
    g.bind("arena", ARENA)
    g.bind("prov", PROV)
    g.bind("", INSTANCES)

    scene_uri = INSTANCES[spec.env_name or "scene_001"]
    g.add((scene_uri, RDF.type, ARENA.EnvironmentGraph))
    g.add((scene_uri, RDF.type, PROV.Entity))
    if spec.env_name:
        g.add((scene_uri, ARENA.envName, Literal(spec.env_name, datatype=XSD.string)))

    # Ground Plane / Terrain
    terrain_uri = INSTANCES["default_ground_plane"]
    g.add((terrain_uri, RDF.type, ARENA.Terrain))
    g.add((terrain_uri, ARENA.registryName, Literal("default_ground_plane", datatype=XSD.string)))
    g.add((scene_uri, ARENA.hasTerrain, terrain_uri))

    # Embodiment
    if spec.embodiment:
        robot_uri = INSTANCES[spec.embodiment.id or "robot"]
        g.add((robot_uri, RDF.type, ARENA.Embodiment))
        g.add((robot_uri, ARENA.registryName, Literal(spec.embodiment.registry_name, datatype=XSD.string)))
        # Map controller binding and numEnvs
        if "wbc" in spec.embodiment.registry_name.lower():
            g.add((robot_uri, ARENA.controllerBinding, Literal("g1_decoupled_wbc_pink_action", datatype=XSD.string)))
            g.add((robot_uri, ARENA.numEnvs, Literal(1, datatype=XSD.integer)))
        g.add((scene_uri, ARENA.hasEmbodiment, robot_uri))

    # Background / Fixture
    if spec.background:
        bg_uri = INSTANCES[spec.background.id or "background"]
        g.add((bg_uri, RDF.type, ARENA.Fixture))
        g.add((bg_uri, ARENA.registryName, Literal(spec.background.registry_name, datatype=XSD.string)))
        g.add((scene_uri, ARENA.hasFixture, bg_uri))

    # Objects
    for obj in spec.objects:
        obj_uri = INSTANCES[obj.id]
        name_lower = obj.registry_name.lower()
        if "shelf" in name_lower or "table" in name_lower or "counter" in name_lower:
            g.add((obj_uri, RDF.type, ARENA.Fixture))
            g.add((obj_uri, RDF.type, ARENA.Furniture))
        else:
            g.add((obj_uri, RDF.type, ARENA.RigidObject))
        g.add((obj_uri, ARENA.registryName, Literal(obj.registry_name, datatype=XSD.string)))
        g.add((scene_uri, ARENA.hasObject, obj_uri))

    # Relations
    for rel in spec.relations:
        subj_uri = INSTANCES[rel.subject]
        if rel.reference:
            ref_uri = INSTANCES[rel.reference]
            if rel.kind == "on":
                g.add((subj_uri, ARENA.placedOn, ref_uri))
            elif rel.kind == "inside":
                g.add((subj_uri, ARENA.placedInside, ref_uri))
            elif rel.kind == "nav_corridor":
                g.add((subj_uri, ARENA.navCorridorTo, ref_uri))

        if rel.params:
            if "surface_anchor" in rel.params:
                g.add((subj_uri, ARENA.surfaceAnchor, Literal(str(rel.params["surface_anchor"]), datatype=XSD.string)))
            if "nominal_height" in rel.params:
                g.add((subj_uri, ARENA.nominalHeight, Literal(float(rel.params["nominal_height"]), datatype=XSD.float)))

    # Cameras & Viewpoints
    viewer_uri = INSTANCES[f"{spec.env_name or 'scene'}_viewer_cam"]
    g.add((viewer_uri, RDF.type, ARENA.Camera))
    target_id = spec.objects[0].id if spec.objects else (spec.background.id if spec.background else "scene")
    g.add((viewer_uri, ARENA.observes, INSTANCES[target_id]))
    g.add((viewer_uri, ARENA.lookAtTarget, INSTANCES[target_id]))
    g.add((scene_uri, ARENA.hasCamera, viewer_uri))

    return g
