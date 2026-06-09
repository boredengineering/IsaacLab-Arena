# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations
import argparse
import os
import numpy as np
from typing import TYPE_CHECKING
from isaaclab_arena_environments.example_environment_base import ExampleEnvironmentBase

# ---------------------------------------------------------------------------
# CONFIGURATION CONSTANTS
# ---------------------------------------------------------------------------
G1_BRAINCO_FINGER_FRICTION_MATERIAL_PATH = "/World/Materials/g1_brainco_high_friction_fingers"
G1_BRAINCO_FINGER_STATIC_FRICTION = 6.0
G1_BRAINCO_FINGER_DYNAMIC_FRICTION = 5.0
G1_BRAINCO_FINGER_PRIM_NAME_MARKERS: tuple[str, ...] = ("hand", "thumb", "index", "middle")
G1_BRAINCO_OPEN_ARM_JOINT_POS: dict[str, float] = {
    "left_shoulder_roll_joint": 0.25, "right_shoulder_roll_joint": -0.25,
    "left_shoulder_yaw_joint": 0.5, "right_shoulder_yaw_joint": -0.5,
}

# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment

from isaaclab_arena.assets.background import Background
from isaaclab_arena.assets.register import register_asset

@register_asset
class OficinaCBAGrande(Background):
    name = "oficina_cba_grande"
    def __init__(self):
        path_variants = [
            "data/Oficina_CBA_grande.usdz",
            "/workspaces/IsaacLab-Arena/data/Oficina_CBA_grande.usdz",
            "/workspaces/isaaclab_arena/data/Oficina_CBA_grande.usdz"
        ]
        usd_path = next((p for p in path_variants if os.path.exists(p)), path_variants[0])
        super().__init__(name=self.name, prim_path="{ENV_REGEX_NS}/Background", usd_path=usd_path, object_min_z=-0.2)

class G1BraincoPickDrinkEnvironment(ExampleEnvironmentBase):
    name: str = "g1_brainco_pick_drink"

    def get_env(self, args_cli: argparse.Namespace) -> IsaacLabArenaEnvironment:
        from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
        from isaaclab_arena.scene.scene import Scene
        from isaaclab_arena.tasks.pick_and_place_task import PickAndPlaceTask
        from isaaclab_arena.utils.pose import Pose
        import g1_brainco_extension.embodiments.g1_brainco  # noqa: F401
        
        # 1. Setup Assets
        background = self.asset_registry.get_asset_by_name("oficina_cba_grande")()
        table = self.asset_registry.get_asset_by_name("office_table")()
        table.set_initial_pose(Pose(position_xyz=(0.55, 0.0, 0.0)))
        drink = self.asset_registry.get_asset_by_name(args_cli.object)()
        drink.set_initial_pose(Pose(position_xyz=(0.5, 0.0, 0.75)))
        destination = self.asset_registry.get_asset_by_name(args_cli.destination)()
        destination.set_initial_pose(Pose(position_xyz=(0.5, 0.3, 0.75)))

        # 2. Setup Embodiment
        embodiment = self.asset_registry.get_asset_by_name(args_cli.embodiment)(
            enable_cameras=args_cli.enable_cameras, lock_waist=args_cli.lock_waist,
        )
        
        # Apply physics and posture settings (using local constants)
        embodiment.set_finger_contact_friction(
            material_path=G1_BRAINCO_FINGER_FRICTION_MATERIAL_PATH,
            static_friction=G1_BRAINCO_FINGER_STATIC_FRICTION,
            dynamic_friction=G1_BRAINCO_FINGER_DYNAMIC_FRICTION,
            prim_name_markers=G1_BRAINCO_FINGER_PRIM_NAME_MARKERS,
        )
        
        embodiment.set_initial_pose(Pose(position_xyz=(0.1, 0.05, 0.0)))
        embodiment.set_joint_initial_pos(G1_BRAINCO_OPEN_ARM_JOINT_POS)

        scene = Scene(assets=[background, table, drink, destination])
        
        return IsaacLabArenaEnvironment(
            name=self.name, embodiment=embodiment, scene=scene,
            task=PickAndPlaceTask(
                pick_up_object=drink, destination_location=destination, background_scene=background,
                episode_length_s=8.0, task_description=f"Pick up the {args_cli.object.replace('_', ' ')}.",
            ),
            env_cfg_callback=lambda cfg: (setattr(cfg, 'num_rerenders_on_reset', 1), cfg)[1],
        )

    @staticmethod
    def add_cli_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--object", type=str, default="beer_bottle")
        parser.add_argument("--destination", type=str, default="blue_sorting_bin")
        parser.add_argument("--embodiment", type=str, default="g1_brainco_custom")
        parser.add_argument("--lock_waist", action=argparse.BooleanOptionalAction, default=True)
