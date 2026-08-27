# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Lowering compiler from RDF-star knowledge graphs to ArenaEnvGraphSpec."""

from __future__ import annotations

from typing import Any
import rdflib

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environment_spec.arena_env_graph_types import (
    AssetSpec,
    CompositeTaskSpec,
    SpatialRelationSpec,
    TaskCompositionType,
    TaskSpec,
)

SPARQL_SCENE_METADATA = """
PREFIX arena: <https://isaac-sim.github.io/arena/schema#>
SELECT ?scene ?env_name ?terrain_reg ?robot_id ?robot_reg ?bg_id ?bg_reg
WHERE {
    ?scene a arena:EnvironmentGraph .
    OPTIONAL { ?scene arena:envName ?env_name . }
    OPTIONAL {
        ?scene arena:hasTerrain ?terrain .
        ?terrain arena:registryName ?terrain_reg .
    }
    OPTIONAL {
        ?scene arena:hasEmbodiment ?robot .
        BIND(STRAFTER(STR(?robot), "#") AS ?robot_id_frag)
        BIND(COALESCE(?robot_id_frag, "robot") AS ?robot_id)
        ?robot arena:registryName ?robot_reg .
    }
    OPTIONAL {
        ?scene arena:hasFixture ?bg .
        BIND(STRAFTER(STR(?bg), "#") AS ?bg_id_frag)
        BIND(COALESCE(?bg_id_frag, "background") AS ?bg_id)
        ?bg arena:registryName ?bg_reg .
    }
}
"""

SPARQL_OBJECTS = """
PREFIX arena: <https://isaac-sim.github.io/arena/schema#>
SELECT ?obj ?obj_id ?obj_reg
WHERE {
    ?scene a arena:EnvironmentGraph ;
           arena:hasObject ?obj .
    BIND(STRAFTER(STR(?obj), "#") AS ?obj_id_frag)
    BIND(COALESCE(?obj_id_frag, "object") AS ?obj_id)
    ?obj arena:registryName ?obj_reg .
}
"""

SPARQL_RELATIONS = """
PREFIX arena: <https://isaac-sim.github.io/arena/schema#>
SELECT ?subj_id ?pred ?ref_id ?anchor ?nominal_z
WHERE {
    ?subj arena:placedOn ?ref .
    BIND(STRAFTER(STR(?subj), "#") AS ?subj_id)
    BIND(STRAFTER(STR(?ref), "#") AS ?ref_id)
    BIND("on" AS ?pred)
    OPTIONAL { ?subj arena:surfaceAnchor ?anchor . }
    OPTIONAL { ?subj arena:nominalHeight ?nominal_z . }
}
"""


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
    robot_id = str(first.robot_id) if first.robot_id else "robot"
    robot_reg = str(first.robot_reg) if first.robot_reg else "unitree_g1"
    bg_id = str(first.bg_id) if first.bg_id else "background"
    bg_reg = str(first.bg_reg) if first.bg_reg else "default_ground_plane"

    objects: list[AssetSpec] = []
    for row in graph.query(SPARQL_OBJECTS):
        obj_id = str(row.obj_id) if row.obj_id else "obj"
        obj_reg = str(row.obj_reg)
        objects.append(AssetSpec(id=obj_id, registry_name=obj_reg))

    relations: list[SpatialRelationSpec] = []
    for row in graph.query(SPARQL_RELATIONS):
        subj_id = str(row.subj_id)
        ref_id = str(row.ref_id)
        rel_params: dict[str, Any] = {}
        if row.nominal_z is not None:
            rel_params["nominal_height"] = float(row.nominal_z)
        if row.anchor is not None:
            rel_params["surface_anchor"] = str(row.anchor)
        relations.append(
            SpatialRelationSpec(
                kind="on",
                subject=subj_id,
                reference=ref_id,
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
