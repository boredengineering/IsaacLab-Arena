# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

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

@register_asset
class OficinaCBAGrande(Background):
    name = "oficina_cba_grande"
    def __init__(self):
        extension_path = os.path.dirname(os.path.dirname(__file__))
        path_variants = [
            os.path.join(extension_path, "data", "Oficina_CBA_grande.usdz"),
            "g1_brainco_extension/data/Oficina_CBA_grande.usdz",
            "/workspaces/IsaacLab-Arena/g1_brainco_extension/data/Oficina_CBA_grande.usdz"
        ]
        usd_path = next((p for p in path_variants if os.path.exists(p)), path_variants[0])
        super().__init__(name=self.name, prim_path="{ENV_REGEX_NS}/Background", usd_path=usd_path, object_min_z=-0.2)

class G1BraincoPickDrinkEnvironment(ExampleEnvironmentBase):
    name: str = "g1_brainco_pick_drink"

    def get_env(self, args_cli: argparse.Namespace) -> IsaacLabArenaEnvironment:
        from isaaclab import sim as sim_utils
        from isaaclab_arena.assets.object import Object
        from isaaclab_arena.assets.object_base import ObjectType
        from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
        from isaaclab_arena.scene.scene import Scene
        from isaaclab_arena.tasks.pick_and_place_task import PickAndPlaceTask
        from isaaclab_arena.utils.pose import Pose, PoseRange
        
        import g1_brainco_extension.embodiments.g1_brainco  # noqa: F401
        import g1_brainco_extension.assets  # noqa: F401
        from g1_brainco_extension.mdp.robot_configs import (
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

        # 1. Setup Assets
        background = self.asset_registry.get_asset_by_name("oficina_cba_grande")()
        ground_plane = self.asset_registry.get_asset_by_name("ground_plane")()
        ground_plane.set_initial_pose(Pose(position_xyz=(0.0, 0.0, 0.0)))
        
        light = self.asset_registry.get_asset_by_name("light")()
        
        # Table and invisible collision patch
        # OfficeTable default scale is (1.0, 1.0, 0.7). Top surface is at ~0.70m
        table = self.asset_registry.get_asset_by_name("office_table")()
        table.set_initial_pose(Pose(position_xyz=(0.55, 0.0, 0.0)))
        
        table_patch = Object(
            name="table_collision_patch",
            prim_path="{ENV_REGEX_NS}/table_collision_patch",
            object_type=ObjectType.SPAWNER,
            spawner_cfg=sim_utils.CuboidCfg(
                size=(1.5, 1.5, 0.02),
                collision_props=sim_utils.CollisionPropertiesCfg(contact_offset=0.005),
                visible=False,
            ),
        )
        table_patch.set_initial_pose(Pose(position_xyz=(0.55, 0.0, TABLE_SURFACE_Z - 0.01)))

        # Dynamic Drink Sampling
        drink = self.asset_registry.get_asset_by_name(args_cli.object)()
        drink.set_initial_pose(
            PoseRange(
                position_xyz_min=(DRINK_SPAWN_X_RANGE[0], DRINK_SPAWN_Y_RANGE[0], TABLE_SURFACE_Z + TABLE_COLLISION_Z_OFFSET),
                position_xyz_max=(DRINK_SPAWN_X_RANGE[1], DRINK_SPAWN_Y_RANGE[1], TABLE_SURFACE_Z + TABLE_COLLISION_Z_OFFSET),
                rpy_min=(0.0, 0.0, 0.0),
                rpy_max=(0.0, 0.0, 2 * np.pi), # Random yaw
            )
        )
        
        destination = self.asset_registry.get_asset_by_name(args_cli.destination)()
        destination.set_initial_pose(
            PoseRange(
                position_xyz_min=(DEST_SPAWN_X_RANGE[0], DEST_SPAWN_Y_RANGE[0], TABLE_SURFACE_Z + TABLE_COLLISION_Z_OFFSET),
                position_xyz_max=(DEST_SPAWN_X_RANGE[1], DEST_SPAWN_Y_RANGE[1], TABLE_SURFACE_Z + TABLE_COLLISION_Z_OFFSET),
                rpy_min=(0.0, 0.0, 0.0),
                rpy_max=(0.0, 0.0, 0.0),
            )
        )

        # 2. Setup Embodiment
        embodiment = self.asset_registry.get_asset_by_name(args_cli.embodiment)(
            enable_cameras=args_cli.enable_cameras, lock_waist=args_cli.lock_waist,
        )
        
        embodiment.set_finger_contact_friction(
            material_path=G1_BRAINCO_FINGER_FRICTION_MATERIAL_PATH,
            static_friction=G1_BRAINCO_FINGER_STATIC_FRICTION,
            dynamic_friction=G1_BRAINCO_FINGER_DYNAMIC_FRICTION,
            prim_name_markers=G1_BRAINCO_FINGER_PRIM_NAME_MARKERS,
        )
        
        embodiment.set_initial_pose(Pose(position_xyz=ROBOT_INITIAL_POSE_XYZ))
        embodiment.set_joint_initial_pos(G1_BRAINCO_OPEN_ARM_JOINT_POS)

        scene = Scene(assets=[background, ground_plane, light, table, table_patch, drink, destination])
        
        return IsaacLabArenaEnvironment(
            name=self.name, embodiment=embodiment, scene=scene,
            task=PickAndPlaceTask(
                pick_up_object=drink, destination_location=destination, background_scene=background,
                episode_length_s=8.0, task_description=f"Approach the table and pick up the {args_cli.object.replace('_', ' ')}.",
            ),
            env_cfg_callback=lambda cfg: (setattr(cfg, 'num_rerenders_on_reset', 1), cfg)[1],
        )

    @staticmethod
    def add_cli_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--object", type=str, default="drink_object_set")
        parser.add_argument("--destination", type=str, default="red_container_custom")
        parser.add_argument("--embodiment", type=str, default="g1_brainco_custom")
        parser.add_argument("--lock_waist", action=argparse.BooleanOptionalAction, default=True)
        parser.add_argument("--enable_cameras", action=argparse.BooleanOptionalAction, default=False)
