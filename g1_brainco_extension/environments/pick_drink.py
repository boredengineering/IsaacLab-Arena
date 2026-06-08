# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations
import argparse
from typing import TYPE_CHECKING
from isaaclab_arena_environments.example_environment_base import ExampleEnvironmentBase

if TYPE_CHECKING:
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment

class G1BraincoPickDrinkEnvironment(ExampleEnvironmentBase):
    """G1 with Brainco hands PickDrink environment extension."""

    name: str = "g1_brainco_pick_drink"

    def get_env(self, args_cli: argparse.Namespace) -> IsaacLabArenaEnvironment:
        # INTERNAL IMPORTS to prevent startup crashes in the main CLI
        from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
        from isaaclab_arena.scene.scene import Scene
        from isaaclab_arena.tasks.pick_and_place_task import PickAndPlaceTask
        from isaaclab_arena.utils.pose import Pose
        
        # Import the custom embodiment to ensure it is registered via @register_asset
        import g1_brainco_extension.embodiments.g1_brainco  # noqa: F401
        
        # Import custom configs
        from g1_brainco_extension.mdp.robot_configs import (
            G1_BRAINCO_FINGER_DYNAMIC_FRICTION,
            G1_BRAINCO_FINGER_FRICTION_MATERIAL_PATH,
            G1_BRAINCO_FINGER_PRIM_NAME_MARKERS,
            G1_BRAINCO_FINGER_STATIC_FRICTION,
        )

        # 1. Setup Background and Table
        # Note: Ensure these assets are available in your registry
        background = self.asset_registry.get_asset_by_name("oficina_cba_grande")()
        table = self.asset_registry.get_asset_by_name("office_table")()
        table.set_initial_pose(Pose(position_xyz=(0.55, 0.0, 0.0)))

        # 2. Setup Pick-up Object and Destination
        drink = self.asset_registry.get_asset_by_name(args_cli.object)()
        drink.set_initial_pose(Pose(position_xyz=(0.5, 0.0, 0.75)))

        destination = self.asset_registry.get_asset_by_name(args_cli.destination)()
        destination.set_initial_pose(Pose(position_xyz=(0.5, 0.3, 0.75)))

        # 3. Setup Embodiment
        # This will fetch the G1BraincoCustomEmbodiment registered in step 2
        embodiment = self.asset_registry.get_asset_by_name(args_cli.embodiment)(
            enable_cameras=args_cli.enable_cameras,
            lock_waist=args_cli.lock_waist,
        )
        
        # Apply high friction to fingers
        embodiment.set_finger_contact_friction(
            material_path=G1_BRAINCO_FINGER_FRICTION_MATERIAL_PATH,
            static_friction=G1_BRAINCO_FINGER_STATIC_FRICTION,
            dynamic_friction=G1_BRAINCO_FINGER_DYNAMIC_FRICTION,
            prim_name_markers=G1_BRAINCO_FINGER_PRIM_NAME_MARKERS,
        )
        
        # Start in front of table
        embodiment.set_initial_pose(Pose(position_xyz=(0.1, 0.05, 0.0)))

        scene = Scene(assets=[background, table, drink, destination])
        
        return IsaacLabArenaEnvironment(
            name=self.name,
            embodiment=embodiment,
            scene=scene,
            task=PickAndPlaceTask(
                pick_up_object=drink,
                destination_location=destination,
                background_scene=background,
                episode_length_s=8.0,
                task_description=f"Pick up the {args_cli.object.replace('_', ' ')}.",
            ),
            env_cfg_callback=lambda cfg: (setattr(cfg, 'num_rerenders_on_reset', 1), cfg)[1],
        )

    @staticmethod
    def add_cli_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--object", type=str, default="beer_bottle")
        parser.add_argument("--destination", type=str, default="blue_sorting_bin")
        parser.add_argument("--embodiment", type=str, default="g1_brainco_custom")
        parser.add_argument(
            "--lock_waist",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Lock the waist joints for a stable static task.",
        )
