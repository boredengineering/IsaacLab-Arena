# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Neo4j Labeled Property Graph (LPG) synchronization and spatial queries."""

import pytest
from isaaclab_arena.environment_spec.arena_env_graph_spec import (
    ArenaEnvGraphSpec,
    AssetSpec,
    CompositeTaskSpec,
    SpatialRelationSpec,
    TaskSpec,
)
from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import (
    get_neo4j_driver,
    query_spatial_hierarchy,
    sync_spec_to_neo4j,
)


def _is_neo4j_reachable() -> bool:
    try:
        driver = get_neo4j_driver()
        driver.verify_connectivity()
        driver.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _is_neo4j_reachable(), reason="Neo4j instance not reachable at bolt://172.17.0.2:7687")
def test_sync_spec_to_neo4j_and_query():
    spec = ArenaEnvGraphSpec(
        env_name="test_g1_shelf_pnp_lpg",
        embodiment=AssetSpec(id="g1_robot", registry_name="g1_wbc_pink"),
        background=AssetSpec(id="galileo_room", registry_name="galileo"),
        objects=[
            AssetSpec(id="wireshelving", registry_name="wireshelving_a01_vomp_robolab"),
            AssetSpec(id="brown_box", registry_name="brown_box"),
            AssetSpec(id="blue_sorting_bin", registry_name="blue_sorting_bin"),
        ],
        relations=[
            SpatialRelationSpec(
                kind="on",
                subject="wireshelving",
                reference="galileo_room",
                params={"surface_anchor": "room_storage_bay", "nominal_height": 0.0},
            ),
            SpatialRelationSpec(
                kind="on",
                subject="brown_box",
                reference="wireshelving",
                params={"surface_anchor": "shelf_tier_1", "nominal_height": 0.75, "clearance": 0.08},
            ),
            SpatialRelationSpec(
                kind="on",
                subject="blue_sorting_bin",
                reference="galileo_room",
                params={"surface_anchor": "floor_deposit_zone", "nominal_height": 0.0},
            ),
        ],
        task=CompositeTaskSpec(
            composition="atomic",
            description="Pick up the brown box from the wireshelving and place it in the blue sorting bin.",
            subtasks=[
                TaskSpec(
                    kind="PickAndPlaceTask",
                    params={
                        "pick_up_object": "brown_box",
                        "destination_location": "blue_sorting_bin",
                        "background_scene": "galileo_room",
                    },
                )
            ],
        ),
    )

    summary = sync_spec_to_neo4j(spec)
    assert summary["env_name"] == "test_g1_shelf_pnp_lpg"
    assert summary["node_count"] >= 4

    hierarchy = query_spatial_hierarchy("test_g1_shelf_pnp_lpg")
    assert len(hierarchy) >= 3

    # Verify that brown_box is child of wireshelving with surface_anchor
    box_rel = next((h for h in hierarchy if h["subject"] == "brown_box"), None)
    assert box_rel is not None
    assert box_rel["parent_id"] == "wireshelving"
    assert box_rel["surface_anchor"] == "shelf_tier_1"
    assert box_rel["nominal_height"] == 0.75
