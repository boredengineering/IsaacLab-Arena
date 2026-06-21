# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

"""
Table-based scene with PickAndPlaceTask, modeled after gr1_table_multi_object_no_collision_environment.
Reimplemented as a Pick and Place task using PickAndPlaceTask.
"""

from __future__ import annotations

import argparse
import os
import numpy as np
from typing import TYPE_CHECKING

from isaaclab_arena_environments.example_environment_base import ExampleEnvironmentBase

if TYPE_CHECKING:
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment

from isaaclab_arena.assets.background import Background
from isaaclab_arena.assets.register import register_asset
from isaaclab_arena.assets.object_library import LibraryObject
import isaaclab.sim as sim_utils


DEFAULT_TABLE_OBJECTS = [
    "beer_bottle",
    "beer_bottle",
    "beer_bottle",
    "beer_bottle",
    "beer_bottle",
    "beer_bottle",
]

@register_asset
class OficinaCBAGrande(Background):
    name = "oficina_cba_grande"
    def __init__(self, **kwargs):
        extension_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        path_variants = [
            os.path.join(extension_path, "assets", "Oficina_CBA_grande.usdz"),
            "g1_brainco_extension/assets/Oficina_CBA_grande.usdz",
            "/workspaces/IsaacLab-Arena/g1_brainco_extension/assets/Oficina_CBA_grande.usdz"
        ]
        usd_path = next((p for p in path_variants if os.path.exists(p)), path_variants[0])
        super().__init__(name=self.name, prim_path="{ENV_REGEX_NS}/Background", usd_path=usd_path, object_min_z=-0.2, **kwargs)

class G1StaticPickAndPlaceDrinkEnvironment(ExampleEnvironmentBase):
    """
    Pick and Place environment with G1 Brainco, an office table background, 
    and task-specific assets.
    """

    name: str = "g1_static_pick_and_place_drink"

    def get_env(self, args_cli: argparse.Namespace) -> IsaacLabArenaEnvironment:
        from isaaclab_arena.assets.object_reference import ObjectReference
        from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
        from isaaclab_arena.relations.relations import IsAnchor, On, AtPosition, NextTo, Side, RandomAroundSolution, RotateAroundSolution
        from isaaclab_arena.scene.scene import Scene
        from isaaclab_arena.tasks.pick_and_place_task import PickAndPlaceTask
        from isaaclab_arena.utils.pose import Pose, PoseRange

        import g1_brainco_extension.embodiments.g1_brainco  # noqa: F401
        import g1_brainco_extension.assets  # noqa: F401
        from g1_brainco_extension.embodiments.mdp.robot_configs import (
            G1_BRAINCO_FINGER_FRICTION_MATERIAL_PATH,
            G1_BRAINCO_FINGER_STATIC_FRICTION,
            G1_BRAINCO_FINGER_DYNAMIC_FRICTION,
            G1_BRAINCO_FINGER_PRIM_NAME_MARKERS,
            G1_BRAINCO_OPEN_ARM_JOINT_POS,
            TABLE_SURFACE_Z,
            TABLE_COLLISION_Z_OFFSET,
            ROBOT_INITIAL_POSE_XYZ,
            DRINK_SPAWN_X_RANGE,
            DRINK_SPAWN_Y_RANGE,
            DEST_SPAWN_X_RANGE,
            DEST_SPAWN_Y_RANGE,
        )

        enable_cameras = getattr(args_cli, "enable_cameras", False)
        
        # 1. Setup Assets
        background = self.asset_registry.get_asset_by_name("oficina_cba_grande")()
        background.set_initial_pose(Pose(position_xyz=(0.0, 0.0, 1.0)))

        ground_plane = self.asset_registry.get_asset_by_name("ground_plane")()
        ground_plane.set_initial_pose(Pose(position_xyz=(0.0, 0.0, 0.0)))
        
        light = self.asset_registry.get_asset_by_name("light")()
        
        table_background = self.asset_registry.get_asset_by_name("office_table")()
        table_background.set_initial_pose(Pose(position_xyz=(0.55, 0.0, 0.0)))
        # Table surface as anchor for On relations
        tabletop_reference = ObjectReference(
            name="table",
            prim_path="{ENV_REGEX_NS}/office_table/Geometry/sm_tabletop_a01_01/sm_tabletop_a01_top_01",
            parent_asset=table_background,
        )
        tabletop_reference.add_relation(IsAnchor())

        object_names = [args_cli.object] * getattr(args_cli, "num_objects", 6)
        placeable_assets = []
        
        # Calculate table bounds
        _bbox = tabletop_reference.get_world_bounding_box()
        _lo, _hi = _bbox.min_point, _bbox.max_point
        _center = [(_lo[i] + _hi[i]) / 2.0 for i in range(3)]
        
        min_x = _lo[0]
        
        # Bottles placement
        drink_x_center = min_x + 0.15
        drink_y_center = -0.20
        drink_x_half = 0.05  # Ensures 10cm-20cm from border
        drink_y_half = 0.02  # Reduced area
        
        offsets = [(x * 0.08, y * 0.08) for x in [-1, 0, 1] for y in [-1, 0, 1]]
        for i, name in enumerate(object_names):
            obj = self.asset_registry.get_asset_by_name(name)(instance_name=f"{name}_{i}")
            obj.add_relation(On(tabletop_reference))
            ox, oy = offsets[i % len(offsets)]
            obj.add_relation(AtPosition(x=drink_x_center + ox, y=drink_y_center + oy))
            obj.add_relation(RandomAroundSolution(x_half_m=drink_x_half, y_half_m=drink_y_half))
            if getattr(args_cli, "spawn_horizontal", False):
                obj.add_relation(RotateAroundSolution(roll_rad=np.pi/2))
            placeable_assets.append(obj)

        destination = self.asset_registry.get_asset_by_name(args_cli.destination)()
        destination.add_relation(On(tabletop_reference))
        
        # Destination placement (25 cm center-to-center gives ~10 cm physical gap)
        dest_x_center = drink_x_center
        dest_y_center = drink_y_center + 0.25
        dest_x_half = 0.02  # Reduced area
        dest_y_half = 0.02  # Reduced area
        
        destination.add_relation(AtPosition(x=dest_x_center, y=dest_y_center))
        destination.add_relation(RandomAroundSolution(x_half_m=dest_x_half, y_half_m=dest_y_half))

        # 2. Setup Embodiment
        embodiment = self.asset_registry.get_asset_by_name(args_cli.embodiment)(
            enable_cameras=args_cli.enable_cameras, 
            lock_waist=args_cli.lock_waist,
        )
        
        embodiment.set_finger_contact_friction(
            material_path=G1_BRAINCO_FINGER_FRICTION_MATERIAL_PATH,
            static_friction=G1_BRAINCO_FINGER_STATIC_FRICTION,
            dynamic_friction=G1_BRAINCO_FINGER_DYNAMIC_FRICTION,
            prim_name_markers=G1_BRAINCO_FINGER_PRIM_NAME_MARKERS,
        )
        
        # The solver can't place the embodiment, so compute the stance ourselves
        # from the table's world bounding box (mirrors NextTo's side semantics).
        _side_cfg = {  # (axis index, outward sign, yaw facing the table)
            Side.POSITIVE_X: (0, +1.0, np.pi),
            Side.NEGATIVE_X: (0, -1.0, 0.0),
            Side.POSITIVE_Y: (1, +1.0, -np.pi / 2.0),
            Side.NEGATIVE_Y: (1, -1.0,  np.pi / 2.0),
        }
        _robot_side = Side.NEGATIVE_X   # stand on -X, FACE +X toward the table
        _dist_from_edge_m = 0.40      # base-to-table-edge distance
        _axis, _sign, _yaw = _side_cfg[_robot_side]
        _band = 1 - _axis
        _pos = [0.0, 0.0, ROBOT_INITIAL_POSE_XYZ[2]]
        
        # Position relative to the bounding box edges to prevent spawning inside table
        if _sign < 0:
            _pos[_axis] = _lo[_axis] - _dist_from_edge_m
        else:
            _pos[_axis] = _hi[_axis] + _dist_from_edge_m
            
        _pos[_band] = _center[_band]
        embodiment.set_initial_pose(Pose(
            position_xyz=tuple(_pos),
            rotation_xyzw=(0.0, 0.0, np.sin(_yaw / 2.0), np.cos(_yaw / 2.0)),
        ))
        embodiment.set_joint_initial_pos(G1_BRAINCO_OPEN_ARM_JOINT_POS)
        
        # Validate robot reach
        import math
        robot_x, robot_y = _pos[0], _pos[1]
        dist_to_cluster = math.sqrt((drink_x_center - robot_x)**2 + (drink_y_center - robot_y)**2)
        assert dist_to_cluster <= 0.65, f"Bottles are out of reach! Distance is {dist_to_cluster:.2f}m (max allowed 0.65m)"
        
        if args_cli.teleop_device is not None:
            teleop_device = self.device_registry.get_device_by_name(args_cli.teleop_device)()
        else:
            teleop_device = None

        scene = Scene(
            assets=[
                background,
                ground_plane,
                table_background,
                tabletop_reference,
                *placeable_assets,
                destination,
                light,
            ]
        )
        
        isaaclab_arena_environment = IsaacLabArenaEnvironment(
            name=self.name, 
            embodiment=embodiment, 
            scene=scene,
            task=PickAndPlaceTask(
                pick_up_object=placeable_assets[1], # pick_up_object=drink 
                destination_location=destination, 
                background_scene=background,
                episode_length_s=8.0, 
                task_description=f"Approach the table and pick up the {args_cli.object.replace('_', ' ')}.",
            ),
            teleop_device=teleop_device,
            env_cfg_callback=lambda cfg: (setattr(cfg, 'num_rerenders_on_reset', 1), cfg)[1],
        )

        return isaaclab_arena_environment

    @staticmethod
    def add_cli_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--object", type=str, default="beer_bottle")
        parser.add_argument("--destination", type=str, default="red_container_custom")
        parser.add_argument("--embodiment", type=str, default="g1_brainco_custom")
        parser.add_argument("--lock_waist", action=argparse.BooleanOptionalAction, default=True)
        parser.add_argument("--enable_cameras", action=argparse.BooleanOptionalAction, default=False)
        parser.add_argument("--teleop_device", type=str, default=None, help="Teleoperation device")
        parser.add_argument("--spawn_horizontal", action=argparse.BooleanOptionalAction, default=False, help="Spawn objects horizontally")
        parser.add_argument("--num_objects", type=int, default=6, help="Number of objects to spawn")
