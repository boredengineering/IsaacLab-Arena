#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
Dynamic OpenUSD Affordance Extractor for IsaacLab-Arena.
Introspects USD assets directly via Pixar USD (pxr.Usd, UsdGeom, UsdPhysics),
extracts articulation roots, kinematics, outward aperture normals, and swing geometry,
and synchronizes discovered affordance cards to Neo4j LPG.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics


def resolve_asset_usd(asset_identifier: str) -> str:
    """Resolve an asset identifier (filesystem path, URL, or registry name) to a USD path."""
    if os.path.exists(asset_identifier):
        return os.path.abspath(asset_identifier)
    
    # Try resolving via IsaacLab-Arena AssetRegistry
    try:
        from isaaclab_arena.assets.registries import AssetRegistry, ensure_assets_registered
        ensure_assets_registered()
        reg = AssetRegistry()
        if reg.is_registered(asset_identifier):
            obj = reg.get_asset_by_name(asset_identifier)()
            usd_path = (
                getattr(obj, "usd_path", None)
                or getattr(getattr(obj, "cfg", None), "usd_path", None)
                or getattr(getattr(getattr(obj, "scene_config", None), "spawn", None), "usd_path", None)
            )
            if usd_path:
                return str(usd_path)
    except Exception as e:
        print(f"[Warning] AssetRegistry lookup for '{asset_identifier}' encountered: {e}", file=sys.stderr)
        
    return asset_identifier


def introspect_usd(usd_path: str, asset_name: str | None = None) -> dict:
    """Introspect an open USD stage to extract mechanical and physical affordances."""
    resolved_path = resolve_asset_usd(usd_path)
    stage = Usd.Stage.Open(resolved_path)
    if not stage:
        raise RuntimeError(f"Could not open USD stage: {resolved_path}")

    derived_name = asset_name or Path(resolved_path).stem.lower()
    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])

    # Check for articulation roots and joints
    has_articulation = False
    articulation_type = "rigid_body"
    joints_found = []
    moving_links = []
    static_casing = None
    revolute_joint_data = None

    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
            has_articulation = True

        if prim.IsA(UsdPhysics.RevoluteJoint):
            has_articulation = True
            joint = UsdPhysics.RevoluteJoint(prim)
            axis = joint.GetAxisAttr().Get()
            lower = joint.GetLowerLimitAttr().Get() or 0.0
            upper = joint.GetUpperLimitAttr().Get() or 90.0
            body0_targets = joint.GetBody0Rel().GetTargets()
            body1_targets = joint.GetBody1Rel().GetTargets()
            body0_path = body0_targets[0].pathString if body0_targets else None
            body1_path = body1_targets[0].pathString if body1_targets else None
            pos0 = joint.GetLocalPos0Attr().Get()
            rot0 = joint.GetLocalRot0Attr().Get()
            
            joint_info = {
                "prim_path": prim.GetPath().pathString,
                "axis": str(axis),
                "limits_deg": [float(lower), float(upper)],
                "limits_rad": [round(float(math.radians(lower)), 4), round(float(math.radians(upper)), 4)],
                "casing_path": body0_path,
                "door_path": body1_path,
                "hinge_local_pos": [round(float(x), 4) for x in pos0] if pos0 else [0.0, 0.0, 0.0],
            }
            joints_found.append(joint_info)
            
            # Prioritize door/lid over continuous platters or turntables
            path_str = prim.GetPath().pathString.lower()
            if "door" in path_str or "lid" in path_str or revolute_joint_data is None:
                revolute_joint_data = joint_info
                articulation_type = "revolute_door"

        elif prim.IsA(UsdPhysics.PrismaticJoint):
            has_articulation = True
            articulation_type = "prismatic_drawer"
            joint = UsdPhysics.PrismaticJoint(prim)
            axis = joint.GetAxisAttr().Get()
            lower = joint.GetLowerLimitAttr().Get() or 0.0
            upper = joint.GetUpperLimitAttr().Get() or 0.40
            body0_targets = joint.GetBody0Rel().GetTargets()
            body1_targets = joint.GetBody1Rel().GetTargets()
            joints_found.append({
                "prim_path": prim.GetPath().pathString,
                "axis": str(axis),
                "limits_m": [float(lower), float(upper)],
                "casing_path": body0_targets[0].pathString if body0_targets else None,
                "drawer_path": body1_targets[0].pathString if body1_targets else None,
            })

    # Compute bounding extents of entire asset
    root_prim = stage.GetDefaultPrim() or stage.GetPseudoRoot()
    overall_box = bbox_cache.ComputeWorldBound(root_prim).ComputeAlignedRange()
    min_pt = [round(float(x), 4) for x in overall_box.GetMin()]
    max_pt = [round(float(x), 4) for x in overall_box.GetMax()]
    dimensions_m = [round(max_pt[i] - min_pt[i], 4) for i in range(3)]
    overall_centroid = [round((min_pt[i] + max_pt[i]) / 2.0, 4) for i in range(3)]

    # If revolute joint exists, compute outward aperture normal and swing geometry
    canonical_aperture_normal = [0.0, 1.0, 0.0]
    active_facet = "+Y"
    swing_radius_m = round(max(dimensions_m[0], dimensions_m[1]) * 0.7, 3)
    casing_bounds = None
    door_bounds = None

    if revolute_joint_data and revolute_joint_data["casing_path"] and revolute_joint_data["door_path"]:
        casing_prim = stage.GetPrimAtPath(revolute_joint_data["casing_path"])
        door_prim = stage.GetPrimAtPath(revolute_joint_data["door_path"])
        
        if casing_prim.IsValid() and door_prim.IsValid():
            c_box = bbox_cache.ComputeWorldBound(casing_prim).ComputeAlignedRange()
            d_box = bbox_cache.ComputeWorldBound(door_prim).ComputeAlignedRange()
            
            c_min = [float(x) for x in c_box.GetMin()]
            c_max = [float(x) for x in c_box.GetMax()]
            d_min = [float(x) for x in d_box.GetMin()]
            d_max = [float(x) for x in d_box.GetMax()]
            
            casing_bounds = [[round(x, 4) for x in c_min], [round(x, 4) for x in c_max]]
            door_bounds = [[round(x, 4) for x in d_min], [round(x, 4) for x in d_max]]
            
            c_center = [(c_min[i] + c_max[i]) / 2.0 for i in range(3)]
            d_center = [(d_min[i] + d_max[i]) / 2.0 for i in range(3)]
            
            # Displacement vector from static casing center to door center (outward vector)
            disp = [d_center[i] - c_center[i] for i in range(3)]
            
            # Dominant horizontal axis (X or Y)
            abs_x = abs(disp[0])
            abs_y = abs(disp[1])
            if abs_y >= abs_x:
                sign = 1.0 if disp[1] > 0 else -1.0
                canonical_aperture_normal = [0.0, sign, 0.0]
                active_facet = "+Y" if sign > 0 else "-Y"
            else:
                sign = 1.0 if disp[0] > 0 else -1.0
                canonical_aperture_normal = [sign, 0.0, 0.0]
                active_facet = "+X" if sign > 0 else "-X"
                
            # Swing radius is the door link's extent along the swing plane
            d_size = [d_max[i] - d_min[i] for i in range(3)]
            swing_radius_m = round(max(d_size[0], d_size[1]), 3)

    card = {
        "asset_name": derived_name,
        "usd_path": resolved_path,
        "has_articulation": has_articulation,
        "articulation_type": articulation_type,
        "dimensions_m": dimensions_m,
        "overall_centroid": overall_centroid,
        "canonical_aperture_normal": canonical_aperture_normal,
        "active_facet": active_facet,
        "swing_radius_m": swing_radius_m,
        "revolute_joint": revolute_joint_data,
        "all_joints": joints_found,
        "casing_bounds": casing_bounds,
        "door_bounds": door_bounds,
    }
    return card


def sync_to_neo4j(card: dict, neo4j_uri: str = "bolt://127.0.0.1:7688", user: str = "neo4j", pwd: str = "isaaclab_arena_password") -> bool:
    """Synchronize discovered affordance card to Neo4j Labeled Property Graph (LPG)."""
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(neo4j_uri, auth=(user, pwd), connection_timeout=5)
        with driver.session() as session:
            cypher = """
            MERGE (a:Asset {name: $asset_name})
            SET a.usd_path = $usd_path,
                a.dimensions_m = $dimensions_m,
                a.has_articulation = $has_articulation,
                a.articulation_type = $articulation_type,
                a.active_facet = $active_facet,
                a.last_introspected = datetime()
            WITH a
            MERGE (aff:Affordance {id: $asset_name + '_affordance'})
            SET aff.type = $articulation_type,
                aff.canonical_aperture_normal = $canonical_aperture_normal,
                aff.active_facet = $active_facet,
                aff.swing_radius_m = $swing_radius_m,
                aff.hinge_pos = $hinge_pos,
                aff.joint_limits_deg = $joint_limits_deg
            MERGE (a)-[:HAS_AFFORDANCE]->(aff)
            WITH a, aff
            FOREACH (_ IN CASE WHEN $has_articulation THEN [1] ELSE [] END |
                MERGE (f:Facet {id: $asset_name + '_facet_' + $active_facet})
                SET f.axis = $active_facet, f.description = 'Articulated Access Aperture'
                MERGE (a)-[:EXPOSES_CANONICAL_FACE {axis: $active_facet}]->(f)
                
                MERGE (app:ApproachVector {id: $asset_name + '_approach'})
                SET app.normal = $canonical_aperture_normal, app.tolerance_deg = 30.0
                MERGE (a)-[:REQUIRES_APPROACH_VECTOR]->(app)
                
                MERGE (st:StanceWaypoint {id: $asset_name + '_nav_stance'})
                SET st.standoff_distance_m = 0.85, st.corridor_width_m = 0.80
                MERGE (a)-[:HAS_NAV_WAYPOINT]->(st)
            )
            RETURN a.name AS name, aff.type AS aff_type
            """
            hinge_pos = card["revolute_joint"]["hinge_local_pos"] if card.get("revolute_joint") else None
            joint_limits_deg = card["revolute_joint"]["limits_deg"] if card.get("revolute_joint") else None
            
            result = session.run(
                cypher,
                asset_name=card["asset_name"],
                usd_path=card["usd_path"],
                dimensions_m=card["dimensions_m"],
                has_articulation=card["has_articulation"],
                articulation_type=card["articulation_type"],
                active_facet=card["active_facet"],
                canonical_aperture_normal=card["canonical_aperture_normal"],
                swing_radius_m=card["swing_radius_m"],
                hinge_pos=hinge_pos,
                joint_limits_deg=joint_limits_deg,
            )
            record = result.single()
            if record:
                print(f"✓ Synchronized affordance card for '{record['name']}' ({record['aff_type']}) to Neo4j LPG at {neo4j_uri}")
                return True
        driver.close()
    except Exception as e:
        print(f"✗ Failed to sync affordance card to Neo4j: {e}", file=sys.stderr)
        return False
    return False


def main():
    parser = argparse.ArgumentParser(description="Dynamic OpenUSD Affordance Extractor for IsaacLab-Arena.")
    parser.add_argument("--usd", required=True, help="USD file path or registered asset name")
    parser.add_argument("--name", default=None, help="Asset name override")
    parser.add_argument("--sync-neo4j", action="store_true", help="Sync discovered affordance to Neo4j LPG")
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7688"), help="Neo4j Bolt URI")
    parser.add_argument("--out-json", default=None, help="Optional output JSON path")
    args = parser.parse_args()

    card = introspect_usd(args.usd, args.name)
    json_str = json.dumps(card, indent=2)
    print(json_str)

    if args.out_json:
        out_p = Path(args.out_json)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json_str)
        print(f"Saved affordance card to {out_p}")

    if args.sync_neo4j:
        sync_to_neo4j(card, neo4j_uri=args.neo4j_uri)


if __name__ == "__main__":
    main()
