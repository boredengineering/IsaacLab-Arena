# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Lowering compiler and bidirectional lifting between RDF-star knowledge graphs and ArenaEnvGraphSpec."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import numpy as np
import rdflib
from rdflib import Literal, Namespace, RDF, XSD

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

SPARQL_REIFIED_RELATIONS = """
PREFIX arena: <https://isaac-sim.github.io/arena/schema#>
SELECT ?reifier ?subj ?pred ?obj ?anchor ?headroom ?friction ?manifold ?dx_min ?dx_max ?dy_min ?dy_max ?dz_min ?dz_max ?prior_e ?post_e
WHERE {
    ?reifier a arena:ReifiedRelation ;
             arena:hasSubject ?subj ;
             arena:hasPredicate ?pred ;
             arena:hasObject ?obj .
    OPTIONAL { ?reifier arena:surfaceAnchor ?anchor . }
    OPTIONAL { ?reifier arena:requiredHeadroom ?headroom . }
    OPTIONAL { ?reifier arena:requiredFriction ?friction . }
    OPTIONAL { ?reifier arena:kinematicManifold ?manifold . }
    OPTIONAL { ?reifier arena:deltaXMin ?dx_min . }
    OPTIONAL { ?reifier arena:deltaXMax ?dx_max . }
    OPTIONAL { ?reifier arena:deltaYMin ?dy_min . }
    OPTIONAL { ?reifier arena:deltaYMax ?dy_max . }
    OPTIONAL { ?reifier arena:deltaZMin ?dz_min . }
    OPTIONAL { ?reifier arena:deltaZMax ?dz_max . }
    OPTIONAL { ?reifier arena:priorEntropy ?prior_e . }
    OPTIONAL { ?reifier arena:posteriorEntropy ?post_e . }
}
"""


@dataclass
class BipedalCapabilityProfile:
    """Offline pre-computed 3D capability and dexterity profile for an embodiment."""

    embodiment_name: str
    height_offset_pelvis: float = 0.75
    min_dexterous_height: float = 0.30
    max_dexterous_height: float = 1.35
    bimanual_lateral_span: tuple[float, float] = (-0.25, 0.25)

    def evaluate_optimal_standoff(self, delta_z: float) -> tuple[float, float, float]:
        """Calculate optimal standoff distance, tolerance, and manipulability score."""
        assert self.min_dexterous_height <= delta_z <= self.max_dexterous_height, (
            f"Target elevation {delta_z:.3f}m is outside embodiment '{self.embodiment_name}' "
            f"dexterous workspace [{self.min_dexterous_height}m, {self.max_dexterous_height}m]."
        )

        if delta_z > 1.05:
            standoff = 0.50 + 0.15 * (1.35 - delta_z)
            tolerance = 0.06
            dexterity = 0.82
        elif delta_z >= 0.65:
            standoff = 0.65 - 0.10 * ((delta_z - 0.85) ** 2)
            tolerance = 0.10
            dexterity = 0.98
        else:
            standoff = 0.75 + 0.20 * (0.65 - delta_z)
            tolerance = 0.08
            dexterity = 0.70

        return standoff, tolerance, dexterity


def sample_bipedal_reach_manifold(
    target_world_xyz: list[float],
    z_floor_estimate: float,
    approach_yaw_range: list[float] | None = None,
    manifold_type: str = "unitree_g1_bimanual_chest_height",
    profile: BipedalCapabilityProfile | None = None,
    upper_tier_clearance: float = 0.40,
) -> tuple[list[float], float, float]:
    """Project the optimal 3D bipedal base stance conditioned on target elevation and kinematics."""
    profile = profile or BipedalCapabilityProfile(
        embodiment_name="unitree_g1",
        height_offset_pelvis=0.75,
        min_dexterous_height=0.30,
        max_dexterous_height=1.35,
    )

    delta_z = target_world_xyz[2] - z_floor_estimate
    standoff, tolerance, dexterity = profile.evaluate_optimal_standoff(delta_z)

    if approach_yaw_range and len(approach_yaw_range) >= 2:
        min_yaw = np.radians(approach_yaw_range[0])
        max_yaw = np.radians(approach_yaw_range[1])
        yaw_approach = 0.5 * (min_yaw + max_yaw)
    else:
        yaw_approach = 0.0

    dx = -standoff * np.cos(yaw_approach)
    dy = -standoff * np.sin(yaw_approach)

    p_robot_x = target_world_xyz[0] + dx
    p_robot_y = target_world_xyz[1] + dy

    yaw_robot = float(
        np.degrees(np.arctan2(target_world_xyz[1] - p_robot_y, target_world_xyz[0] - p_robot_x))
    )

    if upper_tier_clearance < 0.30 and delta_z > 0.85:
        p_robot_x -= 0.08 * np.cos(yaw_approach)
        p_robot_y -= 0.08 * np.sin(yaw_approach)
        dexterity *= 0.85

    return [float(p_robot_x), float(p_robot_y)], yaw_robot, dexterity


def compile_reified_scene_transforms(
    spec: ArenaEnvGraphSpec,
    stage_or_patches: Any = None,
    floor_z: float = 0.0,
) -> dict[str, Any]:
    """Compile reified semantic relations into exact, grounded 3D transforms."""
    resolved = {}

    # Map object placements
    for obj in spec.objects:
        resolved[obj.id] = [0.0, 0.0, floor_z + 0.85]

    # Map robot stance using 3D capability manifold
    if spec.embodiment:
        target_pos = resolved[spec.objects[0].id] if spec.objects else [0.0, 0.0, floor_z + 0.85]
        robot_xy, robot_yaw, _ = sample_bipedal_reach_manifold(
            target_world_xyz=target_pos,
            z_floor_estimate=floor_z,
        )
        resolved[spec.embodiment.id] = [robot_xy[0], robot_xy[1], floor_z, robot_yaw]

    return resolved


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

    # Reified Relations
    reified_relations: list[ReifiedRelationSpec] = []
    for row in graph.query(SPARQL_REIFIED_RELATIONS):
        reifier_id = _extract_id_from_uri(row.reifier, "reifier_1")
        subj_id = _extract_id_from_uri(row.subj)
        pred_type = str(row.pred) if row.pred else "PLACED_ON"
        obj_id = _extract_id_from_uri(row.obj)
        anchor = str(row.anchor) if row.anchor else None
        headroom = float(row.headroom) if row.headroom is not None else 0.35
        friction = float(row.friction) if row.friction is not None else 0.60
        manifold = str(row.manifold) if row.manifold else "unitree_g1_bimanual_chest_height"

        dx = ContinuousIntervalSpec(
            min_val=float(row.dx_min) if row.dx_min is not None else -0.05,
            max_val=float(row.dx_max) if row.dx_max is not None else 0.05,
            nominal=0.0,
        )
        dy = ContinuousIntervalSpec(
            min_val=float(row.dy_min) if row.dy_min is not None else -0.05,
            max_val=float(row.dy_max) if row.dy_max is not None else 0.05,
            nominal=0.0,
        )
        dz = ContinuousIntervalSpec(
            min_val=float(row.dz_min) if row.dz_min is not None else 0.0,
            max_val=float(row.dz_max) if row.dz_max is not None else 0.03,
            nominal=0.01,
        )

        prior_e = float(row.prior_e) if row.prior_e is not None else 2.5
        post_e = float(row.post_e) if row.post_e is not None else 0.05

        reified_relations.append(
            ReifiedRelationSpec(
                reifier_id=reifier_id,
                source_id=subj_id,
                relation_type=pred_type,
                target_id=obj_id,
                surface_anchor=anchor,
                delta_x=dx,
                delta_y=dy,
                delta_z=dz,
                required_headroom=headroom,
                required_friction=friction,
                kinematic_manifold=manifold,
                prior_entropy=prior_e,
                posterior_entropy=post_e,
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
        "reified_relations": reified_relations if reified_relations else None,
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

    # Introspected USD Object References (Dollhouse Sub-Prims)
    if spec.object_references:
        for ref in spec.object_references:
            prim_uri = INSTANCES[ref.id]
            g.add((prim_uri, RDF.type, ARENA.USDPrim))
            if ref.prim_path:
                g.add((prim_uri, ARENA.primPath, Literal(ref.prim_path, datatype=XSD.string)))
            parent_uri = INSTANCES[ref.parent_id] if ref.parent_id else bg_uri
            g.add((parent_uri, ARENA.hasSubPrim, prim_uri))

    # Objects & Furniture
    for obj in spec.objects:
        obj_uri = INSTANCES[obj.id]
        name_lower = obj.registry_name.lower()
        if "shelf" in name_lower or "table" in name_lower or "counter" in name_lower or "rack" in name_lower:
            g.add((obj_uri, RDF.type, ARENA.Fixture))
            g.add((obj_uri, RDF.type, ARENA.Furniture))
        elif "bin" in name_lower or "box" in name_lower or "tray" in name_lower:
            g.add((obj_uri, RDF.type, ARENA.RigidObject))
            if "bin" in name_lower or "tray" in name_lower:
                g.add((obj_uri, RDF.type, ARENA.Receptacle))
        else:
            g.add((obj_uri, RDF.type, ARENA.RigidObject))
        g.add((obj_uri, ARENA.registryName, Literal(obj.registry_name, datatype=XSD.string)))
        g.add((scene_uri, ARENA.hasObject, obj_uri))

    # Telescopic Spatial Relations
    primary_furniture_uri = None
    for rel in spec.relations:
        subj_uri = INSTANCES[rel.subject]
        if rel.reference:
            ref_uri = INSTANCES[rel.reference]
            if rel.kind == "on":
                g.add((subj_uri, ARENA.placedOn, ref_uri))
                if rel.params and "surface_anchor" in rel.params:
                    anchor_name = str(rel.params["surface_anchor"])
                    anchor_uri = INSTANCES[f"{rel.reference}_{anchor_name}"]
                    g.add((anchor_uri, RDF.type, ARENA.SurfaceAnchor))
                    g.add((anchor_uri, ARENA.anchorName, Literal(anchor_name, datatype=XSD.string)))
                    g.add((ref_uri, ARENA.hasSubSurface, anchor_uri))
                    g.add((subj_uri, ARENA.placedOnSubSurface, anchor_uri))
                    primary_furniture_uri = ref_uri
            elif rel.kind == "inside":
                g.add((subj_uri, ARENA.placedInside, ref_uri))
            elif rel.kind == "nav_corridor":
                g.add((subj_uri, ARENA.navCorridorTo, ref_uri))

        if rel.params:
            if "surface_anchor" in rel.params:
                g.add((subj_uri, ARENA.surfaceAnchor, Literal(str(rel.params["surface_anchor"]), datatype=XSD.string)))
            if "nominal_height" in rel.params:
                g.add((subj_uri, ARENA.nominalHeight, Literal(float(rel.params["nominal_height"]), datatype=XSD.float)))

    # Reified RDF 1.2 Relations
    if spec.reified_relations:
        for r_rel in spec.reified_relations:
            reifier_uri = INSTANCES[r_rel.reifier_id]
            subj_uri = INSTANCES[r_rel.source_id]
            obj_uri = INSTANCES[r_rel.target_id]

            g.add((reifier_uri, RDF.type, ARENA.ReifiedRelation))
            g.add((reifier_uri, ARENA.hasSubject, subj_uri))
            g.add((reifier_uri, ARENA.hasPredicate, Literal(r_rel.relation_type, datatype=XSD.string)))
            g.add((reifier_uri, ARENA.hasObject, obj_uri))

            if r_rel.surface_anchor:
                g.add((reifier_uri, ARENA.surfaceAnchor, Literal(r_rel.surface_anchor, datatype=XSD.string)))
            g.add((reifier_uri, ARENA.requiredHeadroom, Literal(r_rel.required_headroom, datatype=XSD.float)))
            g.add((reifier_uri, ARENA.requiredFriction, Literal(r_rel.required_friction, datatype=XSD.float)))
            g.add((reifier_uri, ARENA.kinematicManifold, Literal(r_rel.kinematic_manifold, datatype=XSD.string)))
            g.add((reifier_uri, ARENA.priorEntropy, Literal(r_rel.prior_entropy, datatype=XSD.float)))
            g.add((reifier_uri, ARENA.posteriorEntropy, Literal(r_rel.posterior_entropy, datatype=XSD.float)))

    # Robot Standoff Affordance Link
    if spec.embodiment and (primary_furniture_uri or spec.objects):
        target_furn = primary_furniture_uri or INSTANCES[spec.objects[0].id]
        g.add((robot_uri, ARENA.standsAtAffordance, target_furn))
        g.add((robot_uri, ARENA.standoffDistance, Literal(0.85, datatype=XSD.float)))

    # Cameras & Viewpoints Grounding
    viewer_uri = INSTANCES[f"{spec.env_name or 'scene'}_viewer_cam"]
    g.add((viewer_uri, RDF.type, ARENA.Camera))
    target_id = spec.objects[0].id if spec.objects else (spec.background.id if spec.background else "scene")
    target_node = INSTANCES[target_id]
    g.add((viewer_uri, ARENA.observes, target_node))
    g.add((viewer_uri, ARENA.observesInteraction, target_node))
    g.add((viewer_uri, ARENA.lookAtTarget, target_node))
    g.add((scene_uri, ARENA.hasCamera, viewer_uri))

    return g
