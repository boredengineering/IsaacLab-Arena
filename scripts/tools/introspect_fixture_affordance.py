#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""OpenUSD Fixture Affordance & Grounding Introspector for IsaacLab-Arena.

Introspects static scene fixtures (tables, workbenches, counters, cabinets) using
Pixar USD (pxr.Usd, UsdGeom.BBoxCache). Confirms physical ground contact (Z_min == 0.0m),
measures true physical deck height (Z_deck = Z_max) and surface bounding polygon,
and synchronizes (:Fixture)-[:HAS_SUB_SURFACE]->(:SurfaceAnchor) directly to Neo4j LPG.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Deferred imports for pxr to avoid Isaac Sim SimulationApp pre-initialization conflict


def resolve_fixture_usd(
    asset_identifier: str,
    scale_override: list[float] | None = None,
) -> tuple[str, list[float], str]:
    """Resolve a fixture identifier to a USD path, scale vector, and asset name.

    Args:
        asset_identifier: Filesystem path, Omniverse URL, or registered asset identifier.
        scale_override: Optional scale [sx, sy, sz] to override registry defaults.

    Returns:
        tuple[str, list[float], str]: (usd_path, scale, asset_name)
    """
    scale = scale_override or [1.0, 1.0, 1.0]
    derived_name = Path(asset_identifier).stem.lower()

    if os.path.exists(asset_identifier):
        return os.path.abspath(asset_identifier), scale, derived_name

    # Try resolving via IsaacLab-Arena AssetRegistry
    try:
        from isaaclab_arena.assets.registries import AssetRegistry, ensure_assets_registered
        ensure_assets_registered()
        reg = AssetRegistry()
        if reg.is_registered(asset_identifier):
            cls = reg.get_asset_by_name(asset_identifier)
            usd_path = (
                getattr(cls, "usd_path", None)
                or getattr(getattr(cls, "cfg", None), "usd_path", None)
                or getattr(getattr(getattr(cls, "scene_config", None), "spawn", None), "usd_path", None)
            )
            reg_scale = getattr(cls, "scale", None)
            if reg_scale and scale_override is None:
                scale = [float(s) for s in reg_scale]
            if usd_path:
                return str(usd_path), scale, asset_identifier
    except Exception as e:
        print(f"[Warning] AssetRegistry lookup for '{asset_identifier}' encountered: {e}", file=sys.stderr)

    return asset_identifier, scale, derived_name


def introspect_fixture_usd(
    usd_identifier: str,
    asset_name: str | None = None,
    scale_override: list[float] | None = None,
    tolerance_m: float = 0.005,
) -> dict:
    """Introspect an open USD stage to extract fixture grounding and deck surface affordances.

    Args:
        usd_identifier: Filesystem path or registered asset name.
        asset_name: Optional override for the fixture asset name.
        scale_override: Optional 3D scale vector [sx, sy, sz].
        tolerance_m: Ground contact tolerance in meters (default 0.005m).

    Returns:
        dict: Complete affordance card containing grounding status, deck height, and surface bounds.
    """
    resolved_path, scale, default_name = resolve_fixture_usd(usd_identifier, scale_override)
    derived_name = asset_name or default_name

    app = None
    if resolved_path.startswith(("http://", "https://", "omniverse://")):
        try:
            import omni.kit.app
            if omni.kit.app.get_app() is None:
                from isaaclab.app import AppLauncher
                app = AppLauncher(headless=True).app
        except Exception:
            try:
                from isaaclab.app import AppLauncher
                app = AppLauncher(headless=True).app
            except Exception as e:
                print(f"[Warning] Could not initialize AppLauncher for remote USD: {e}", file=sys.stderr)

    try:
        from pxr import Gf, Sdf, Usd, UsdGeom
    except ImportError as e:
        raise RuntimeError(
            "pxr.Usd is required. Run inside the Arena Docker container via: "
            "docker exec <container> /isaac-sim/python.sh <script>"
        ) from e

    stage = Usd.Stage.Open(resolved_path)
    assert stage, f"Could not open USD stage: {resolved_path}"

    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    root_prim = stage.GetDefaultPrim() or stage.GetPseudoRoot()
    raw_box = bbox_cache.ComputeWorldBound(root_prim).ComputeAlignedRange()

    raw_min = [float(x) for x in raw_box.GetMin()]
    raw_max = [float(x) for x in raw_box.GetMax()]

    # Apply scale
    scaled_min = [round(raw_min[i] * scale[i], 4) for i in range(3)]
    scaled_max = [round(raw_max[i] * scale[i], 4) for i in range(3)]

    dimensions_m = [round(scaled_max[i] - scaled_min[i], 4) for i in range(3)]
    centroid = [round((scaled_min[i] + scaled_max[i]) / 2.0, 4) for i in range(3)]

    z_min = scaled_min[2]
    z_deck = scaled_max[2]

    # Ground contact validation
    is_grounded = abs(z_min) <= tolerance_m
    if z_min > tolerance_m:
        ground_status = "FLOATING"
    elif z_min < -tolerance_m:
        ground_status = "PENETRATING"
    else:
        ground_status = "GROUNDED"

    bounds_x = [scaled_min[0], scaled_max[0]]
    bounds_y = [scaled_min[1], scaled_max[1]]
    usable_width = round(bounds_x[1] - bounds_x[0], 4)
    usable_depth = round(bounds_y[1] - bounds_y[0], 4)
    usable_area = round(usable_width * usable_depth, 4)

    # Surface bounding polygon (counter-clockwise quad)
    surface_polygon = [
        [bounds_x[0], bounds_y[0]],
        [bounds_x[1], bounds_y[0]],
        [bounds_x[1], bounds_y[1]],
        [bounds_x[0], bounds_y[1]],
    ]

    # Canonical surface sectors
    dx = (bounds_x[1] - bounds_x[0]) / 3.0
    dy = (bounds_y[1] - bounds_y[0]) / 3.0
    sectors = {
        "center": {
            "bounds_x": [round(bounds_x[0] + dx, 4), round(bounds_x[1] - dx, 4)],
            "bounds_y": [round(bounds_y[0] + dy, 4), round(bounds_y[1] - dy, 4)],
        },
        "front_center": {
            "bounds_x": [round(bounds_x[0] + dx, 4), round(bounds_x[1] - dx, 4)],
            "bounds_y": [round(bounds_y[0], 4), round(bounds_y[0] + dy, 4)],
        },
        "front_left": {
            "bounds_x": [round(bounds_x[0], 4), round(bounds_x[0] + dx, 4)],
            "bounds_y": [round(bounds_y[0], 4), round(bounds_y[0] + dy, 4)],
        },
        "front_right": {
            "bounds_x": [round(bounds_x[1] - dx, 4), round(bounds_x[1], 4)],
            "bounds_y": [round(bounds_y[0], 4), round(bounds_y[0] + dy, 4)],
        },
        "back_left": {
            "bounds_x": [round(bounds_x[0], 4), round(bounds_x[0] + dx, 4)],
            "bounds_y": [round(bounds_y[1] - dy, 4), round(bounds_y[1], 4)],
        },
        "back_right": {
            "bounds_x": [round(bounds_x[1] - dx, 4), round(bounds_x[1], 4)],
            "bounds_y": [round(bounds_y[1] - dy, 4), round(bounds_y[1], 4)],
        },
    }

    surface_anchor = {
        "id": f"{derived_name}_surface_top",
        "anchor_name": "table_top",
        "deck_height_m": z_deck,
        "bounds_x": bounds_x,
        "bounds_y": bounds_y,
        "usable_width_m": usable_width,
        "usable_depth_m": usable_depth,
        "usable_area_m2": usable_area,
        "surface_polygon": surface_polygon,
        "sectors": sectors,
    }

    card = {
        "fixture_name": derived_name,
        "usd_path": resolved_path,
        "scale": scale,
        "is_grounded": is_grounded,
        "ground_status": ground_status,
        "ground_contact_error_m": round(z_min, 4),
        "raw_bounds": [raw_min, raw_max],
        "scaled_bounds": [scaled_min, scaled_max],
        "dimensions_m": dimensions_m,
        "footprint_half_extents": [round(usable_width / 2.0, 4), round(usable_depth / 2.0, 4)],
        "canonical_approach_normal": [0.0, -1.0, 0.0],
        "centroid": centroid,
        "z_min_m": z_min,
        "z_deck_m": z_deck,
        "primary_surface_anchor": surface_anchor,
    }
    if app:
        try:
            app.close()
        except Exception:
            pass
    return card


def compute_transformed_surface_sectors(
    card: dict,
    fixture_pos: list[float] | tuple[float, float, float] = (0.0, 0.0, 0.0),
    fixture_yaw_rad: float = 0.0,
) -> dict[str, dict]:
    """Transform local surface sectors into world coordinates given fixture pose.

    When a fixture is rotated (e.g. yaw = -1.5708 to align with robot approach),
    all supporting surface sectors (front_left, front_right, etc.) rotate and translate accordingly.
    This provides the exact world-frame coordinates and bounding boxes needed for placing objects.
    """
    import math

    sa = card.get("primary_surface_anchor", {})
    sectors = sa.get("sectors", {})
    deck_z = float(fixture_pos[2]) + float(card.get("z_deck_m", 0.75))

    cos_yaw = math.cos(fixture_yaw_rad)
    sin_yaw = math.sin(fixture_yaw_rad)

    transformed = {}
    for name, s in sectors.items():
        bx = s["bounds_x"]
        by = s["bounds_y"]
        corners_local = [
            (bx[0], by[0]),
            (bx[1], by[0]),
            (bx[1], by[1]),
            (bx[0], by[1]),
        ]
        corners_world = [
            (
                fixture_pos[0] + cx * cos_yaw - cy * sin_yaw,
                fixture_pos[1] + cx * sin_yaw + cy * cos_yaw,
            )
            for cx, cy in corners_local
        ]
        world_min_x = min(c[0] for c in corners_world)
        world_max_x = max(c[0] for c in corners_world)
        world_min_y = min(c[1] for c in corners_world)
        world_max_y = max(c[1] for c in corners_world)

        center_local_x = (bx[0] + bx[1]) / 2.0
        center_local_y = (by[0] + by[1]) / 2.0
        center_world_x = fixture_pos[0] + center_local_x * cos_yaw - center_local_y * sin_yaw
        center_world_y = fixture_pos[1] + center_local_x * sin_yaw + center_local_y * cos_yaw

        transformed[name] = {
            "center_xyz": [round(center_world_x, 4), round(center_world_y, 4), round(deck_z, 4)],
            "world_bounds_x": [round(world_min_x, 4), round(world_max_x, 4)],
            "world_bounds_y": [round(world_min_y, 4), round(world_max_y, 4)],
            "surface_polygon_world": [
                [round(c[0], 4), round(c[1], 4)] for c in corners_world
            ],
        }

    return transformed


def sync_fixture_to_neo4j(
    card: dict,
    neo4j_uri: str = "bolt://127.0.0.1:7688",
    user: str = "neo4j",
    pwd: str = "isaaclab_arena_password",
) -> bool:
    """Synchronize discovered fixture affordance card to Neo4j LPG.

    Args:
        card: Affordance card produced by introspect_fixture_usd.
        neo4j_uri: Bolt URI for Neo4j.
        user: Username.
        pwd: Password.

    Returns:
        bool: True if synchronization succeeded, False otherwise.
    """
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(neo4j_uri, auth=(user, pwd), connection_timeout=5)
        with driver.session() as session:
            cypher = """
            MERGE (f:Fixture {name: $fixture_name})
            SET f.usd_path = $usd_path,
                f.scale = $scale,
                f.dimensions_m = $dimensions_m,
                f.z_min = $z_min,
                f.z_deck = $z_deck,
                f.is_grounded = $is_grounded,
                f.ground_status = $ground_status,
                f.ground_contact_error_m = $ground_contact_error_m,
                f.last_introspected = datetime()
            WITH f
            MERGE (s:SurfaceAnchor {id: $anchor_id})
            SET s.anchor_name = $anchor_name,
                s.deck_height_m = $deck_height_m,
                s.bounds_x = $bounds_x,
                s.bounds_y = $bounds_y,
                s.usable_width_m = $usable_width,
                s.usable_depth_m = $usable_depth,
                s.usable_area_m2 = $usable_area,
                s.surface_polygon = $surface_polygon
            MERGE (f)-[:HAS_SUB_SURFACE {is_primary: true}]->(s)
            RETURN f.name AS name, s.id AS anchor, s.deck_height_m AS deck_height
            """
            sa = card["primary_surface_anchor"]
            result = session.run(
                cypher,
                fixture_name=card["fixture_name"],
                usd_path=card["usd_path"],
                scale=card["scale"],
                dimensions_m=card["dimensions_m"],
                z_min=card["z_min_m"],
                z_deck=card["z_deck_m"],
                is_grounded=card["is_grounded"],
                ground_status=card["ground_status"],
                ground_contact_error_m=card["ground_contact_error_m"],
                anchor_id=sa["id"],
                anchor_name=sa["anchor_name"],
                deck_height_m=sa["deck_height_m"],
                bounds_x=sa["bounds_x"],
                bounds_y=sa["bounds_y"],
                usable_width=sa["usable_width_m"],
                usable_depth=sa["usable_depth_m"],
                usable_area=sa["usable_area_m2"],
                surface_polygon=str(sa["surface_polygon"]),
            )
            record = result.single()
            if record:
                print(
                    f"✓ Synchronized fixture '{record['name']}' -> SurfaceAnchor '{record['anchor']}' "
                    f"(deck_height={record['deck_height']:.3f}m) to Neo4j at {neo4j_uri}"
                )
                return True
        driver.close()
    except Exception as e:
        print(f"✗ Failed to sync fixture affordance card to Neo4j: {e}", file=sys.stderr)
        return False
    return False


def main():
    parser = argparse.ArgumentParser(
        description="OpenUSD Fixture Affordance & Grounding Introspector for IsaacLab-Arena."
    )
    parser.add_argument("--usd", required=True, help="USD file path or registered asset name")
    parser.add_argument("--name", default=None, help="Asset name override")
    parser.add_argument(
        "--scale",
        nargs=3,
        type=float,
        default=None,
        metavar=("SX", "SY", "SZ"),
        help="Optional 3D scale vector override [sx, sy, sz]",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.005,
        help="Ground contact tolerance in meters (default: 0.005)",
    )
    parser.add_argument(
        "--sync-neo4j",
        action="store_true",
        help="Sync discovered fixture and SurfaceAnchor nodes to Neo4j LPG",
    )
    parser.add_argument(
        "--neo4j-uri",
        default=os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7688"),
        help="Neo4j Bolt URI",
    )
    parser.add_argument("--out-json", default=None, help="Optional output JSON path")
    parser.add_argument(
        "--check-grounding",
        action="store_true",
        help="Assert ground contact and exit with code 1 if fixture is floating or penetrating",
    )
    parser.add_argument(
        "--pose",
        nargs=4,
        type=float,
        default=None,
        metavar=("X", "Y", "Z", "YAW"),
        help="Optional world pose [x, y, z, yaw_rad] to compute transformed surface sectors",
    )
    args = parser.parse_args()

    app = None
    try:
        from isaaclab.app import AppLauncher
        app = AppLauncher(headless=True).app
    except Exception:
        pass

    try:
        card = introspect_fixture_usd(
            args.usd,
            asset_name=args.name,
            scale_override=args.scale,
            tolerance_m=args.tolerance,
        )
        if args.pose:
            card["transformed_sectors"] = compute_transformed_surface_sectors(
                card, fixture_pos=args.pose[:3], fixture_yaw_rad=args.pose[3]
            )
        json_str = json.dumps(card, indent=2)
        print(json_str)

        if args.out_json:
            out_p = Path(args.out_json)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(json_str)
            print(f"Saved fixture affordance card to {out_p}")

        if args.sync_neo4j:
            sync_fixture_to_neo4j(card, neo4j_uri=args.neo4j_uri)

        if args.check_grounding and not card["is_grounded"]:
            print(
                f"\n[GROUNDING INVARIANT DEFECT]: Fixture '{card['fixture_name']}' is {card['ground_status']}! "
                f"Z_min = {card['z_min_m']:.4f}m exceeds tolerance ({args.tolerance}m).",
                file=sys.stderr,
            )
            sys.exit(1)
    finally:
        if app is not None:
            try:
                app.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
