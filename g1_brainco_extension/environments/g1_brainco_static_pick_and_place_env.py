# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0

"""Static-base G1 pick-and-place environment for Brainco tasks, using the locomanip warehouse shelf."""

from __future__ import annotations

import argparse
import numpy as np
from typing import TYPE_CHECKING

from isaaclab_arena_environments.example_environment_base import ExampleEnvironmentBase

if TYPE_CHECKING:
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment

# Constants matching original task geometry
SHELF_SURFACE_Z = -0.030
SHELF_SUPPORT_PATCH_SIZE = (0.8, 1.5, 0.04)
SHELF_SUPPORT_PATCH_CENTER = (0.62, 0.0, SHELF_SURFACE_Z - SHELF_SUPPORT_PATCH_SIZE[2] / 2.0)

_BACKGROUND_PRIMS_TO_DEACTIVATE: tuple[str, ...] = (
    "galileo_locomanip/BackgroundAssets/boxes/jetson_orin_06",
    "galileo_locomanip/BackgroundAssets/boxes/jetson_orin_03",
    "galileo_locomanip/BackgroundAssets/boxes/hesai_box_06",
)

def _deactivate_background_prims(env, env_ids, prim_relative_paths: tuple[str, ...]) -> None:
    """Deactivate selected referenced background prims before simulation starts."""
    del env_ids
    stage = env.sim.stage
    for env_prim_path in env.scene.env_prim_paths:
        for prim_relative_path in prim_relative_paths:
            prim_path = f"{env_prim_path}/{prim_relative_path}"
            prim = stage.GetPrimAtPath(prim_path)
            if prim.IsValid():
                stage.OverridePrim(prim_path).SetActive(False)


TUNED_PICK_UP_OBJECT_NAME = "apple_01_objaverse_robolab"
TUNED_DESTINATION_NAME = "clay_plates_hot3d_robolab"

# Per-asset uniform scale matching the tuned pick-up / destination pair.
_TUNED_SCALES: dict[str, tuple[float, float, float]] = {
    TUNED_PICK_UP_OBJECT_NAME: (0.009, 0.009, 0.009),
    TUNED_DESTINATION_NAME: (0.5, 0.5, 0.5),
}


def _asset_scale(asset_name: str) -> tuple[float, float, float]:
    """Return the tuned uniform scale for asset_name, or 1.0 with a warning."""
    if asset_name in _TUNED_SCALES:
        return _TUNED_SCALES[asset_name]
    import warnings
    warnings.warn(
        "g1_brainco_static_pick_and_place: no measured scale for "
        f"'{asset_name}'; spawning at scale=(1.0, 1.0, 1.0). Verify visually.",
        stacklevel=2,
    )
    return (1.0, 1.0, 1.0)


class G1BraincoStaticPickAndPlaceEnvironment(ExampleEnvironmentBase):
    """G1 Brainco Custom (WBC-balanced, no nav) pick-and-place on the locomanip warehouse shelf.

    Uses programmatic relation-based layout anchoring to prevent ground penetration
    and coordinate mismatch issues across different robot embodiments.
    """

    name: str = "g1_brainco_static_pick_and_place"

    def get_env(self, args_cli: argparse.Namespace) -> IsaacLabArenaEnvironment:
        from isaaclab import sim as sim_utils

        from isaaclab_arena.assets.object import Object
        from isaaclab_arena.assets.object_base import ObjectType
        from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
        from isaaclab_arena.relations.relations import IsAnchor, On, AtPosition, RandomAroundSolution, Side
        from isaaclab_arena.scene.scene import Scene
        from isaaclab_arena.tasks.pick_and_place_task import PickAndPlaceTask
        from isaaclab_arena.utils.pose import Pose
        from isaaclab_arena.utils.bounding_box import AxisAlignedBoundingBox
        
        import g1_brainco_extension.embodiments.g1_brainco  # noqa: F401
        import g1_brainco_extension.assets  # noqa: F401
        from g1_brainco_extension.embodiments.mdp.robot_configs import (
            G1_BRAINCO_FINGER_DYNAMIC_FRICTION,
            G1_BRAINCO_FINGER_FRICTION_MATERIAL_PATH,
            G1_BRAINCO_FINGER_PRIM_NAME_MARKERS,
            G1_BRAINCO_FINGER_STATIC_FRICTION,
            G1_BRAINCO_OPEN_ARM_JOINT_POS,
        )

        # 1. Setup Assets
        background = self.asset_registry.get_asset_by_name("galileo_locomanip")()
        
        # Shelf support: local collision patch for the shelf area
        shelf_support = Object(
            name="static_pick_place_shelf_support",
            prim_path="{ENV_REGEX_NS}/static_pick_place_shelf_support",
            object_type=ObjectType.SPAWNER,
            spawner_cfg=sim_utils.CuboidCfg(
                size=SHELF_SUPPORT_PATCH_SIZE,
                collision_props=sim_utils.CollisionPropertiesCfg(contact_offset=0.005),
                visible=False,
            ),
        )
        
        # Override get_bounding_box on the procedural object to bypass usd_path assert
        def custom_get_bounding_box():
            return AxisAlignedBoundingBox(
                min_point=(-SHELF_SUPPORT_PATCH_SIZE[0] / 2.0, -SHELF_SUPPORT_PATCH_SIZE[1] / 2.0, -SHELF_SUPPORT_PATCH_SIZE[2] / 2.0),
                max_point=(SHELF_SUPPORT_PATCH_SIZE[0] / 2.0, SHELF_SUPPORT_PATCH_SIZE[1] / 2.0, SHELF_SUPPORT_PATCH_SIZE[2] / 2.0),
            )
        shelf_support.get_bounding_box = custom_get_bounding_box

        shelf_support.set_initial_pose(
            Pose(position_xyz=SHELF_SUPPORT_PATCH_CENTER, rotation_xyzw=(0.0, 0.0, 0.0, 1.0))
        )
        
        # Mark the shelf support directly as an anchor relation parent
        shelf_support.add_relation(IsAnchor())

        # Determine Z floor level relative to shelf support to prevent ground penetration
        # Shelf support top is at Z = -0.030. The warehouse room floor is at Z = -0.795.
        # Height of shelf is 0.765m.
        floor_z = SHELF_SURFACE_Z - 0.765
        
        # Spawn ground plane flush with the actual visual warehouse floor
        ground_plane = self.asset_registry.get_asset_by_name("ground_plane")()
        ground_plane.set_initial_pose(Pose(position_xyz=(0.0, 0.0, floor_z)))
        
        light = self.asset_registry.get_asset_by_name("light")()

        # Load pick-up object and destination
        pick_up_object = self.asset_registry.get_asset_by_name(args_cli.object)(scale=_asset_scale(args_cli.object))
        destination = self.asset_registry.get_asset_by_name(args_cli.destination)(scale=_asset_scale(args_cli.destination))

        # Calculate bounding box of the shelf anchor
        _bbox = shelf_support.get_world_bounding_box()
        _lo, _hi = _bbox.min_point, _bbox.max_point

        # Position robot and objects relative to shelf support bounds
        # Robot stands on the negative X side of the shelf, facing positive X
        _robot_side = Side.NEGATIVE_X
        _axis, _sign, _yaw = (0, -1.0, 0.0)
        _band = 1
        _u_edge = _lo[_axis]  # 0.22

        # Spacing / layout variables:
        # Distance of objects from the shelf edge along active axis (X)
        # Original apple: X = 0.5785. Shelf edge: X = 0.22. Forward offset = 0.3585m.
        _d_forward = 0.3585
        _u_obj = _u_edge - _sign * _d_forward  # 0.5785

        # Workspace center along lateral/band axis (Y)
        # Original robot Y = 0.08, workspace center = 0.165 (midpoint of apple at 0.27 and plate at 0.06)
        _v_mid = 0.08
        _v_work = 0.165
        _separation = 0.21

        drink_x_center = _u_obj
        drink_y_center = _v_work + _separation / 2.0  # 0.27

        dest_x_center = _u_obj
        dest_y_center = _v_work - _separation / 2.0  # 0.06

        # 2. Place pick-up object and destination on the shelf top
        pick_up_object.add_relation(On(shelf_support))
        pick_up_object.add_relation(AtPosition(x=drink_x_center, y=drink_y_center))
        # Zero randomization for static apple task to match original task determinism
        pick_up_object.add_relation(RandomAroundSolution(x_half_m=0.0, y_half_m=0.0))

        destination.add_relation(On(shelf_support))
        destination.add_relation(AtPosition(x=dest_x_center, y=dest_y_center))
        destination.add_relation(RandomAroundSolution(x_half_m=0.0, y_half_m=0.0))

        # 3. Setup Embodiment
        enable_cameras = getattr(args_cli, "enable_cameras", True)
        embodiment = self.asset_registry.get_asset_by_name(args_cli.embodiment)(
            enable_cameras=enable_cameras,
            lock_waist=args_cli.lock_waist,
        )
        embodiment.set_finger_contact_friction(
            material_path=G1_BRAINCO_FINGER_FRICTION_MATERIAL_PATH,
            static_friction=G1_BRAINCO_FINGER_STATIC_FRICTION,
            dynamic_friction=G1_BRAINCO_FINGER_DYNAMIC_FRICTION,
            prim_name_markers=G1_BRAINCO_FINGER_PRIM_NAME_MARKERS,
        )

        # Compute final base coordinate position relative to the shelf edge
        # Standoff offset: robot stands slightly inside the shelf bounding box for optimal reach
        _dist_from_edge_m = -0.03
        _pos = [0.0, 0.0, floor_z + 0.75]  # Standing height pelvis Z = floor_z + 0.75
        _pos[_axis] = _u_edge + _sign * _dist_from_edge_m
        _pos[_band] = _v_mid

        embodiment.set_initial_pose(Pose(
            position_xyz=tuple(_pos),
            rotation_xyzw=(0.0, 0.0, np.sin(_yaw / 2.0), np.cos(_yaw / 2.0)),
        ))
        embodiment.set_joint_initial_pos(G1_BRAINCO_OPEN_ARM_JOINT_POS)

        if args_cli.teleop_device is not None:
            teleop_device = self.device_registry.get_device_by_name(args_cli.teleop_device)()
        else:
            teleop_device = None

        if args_cli.task_description is not None:
            task_description = args_cli.task_description
        else:
            object_label = args_cli.object.replace("_", " ")
            destination_label = args_cli.destination.replace("_", " ")
            task_description = (
                f"Pick up the {object_label} from the shelf and place it onto the "
                f"{destination_label} on the same shelf next to it."
            )

        def env_cfg_callback(env_cfg):
            from isaaclab.managers import EventTermCfg

            env_cfg.events.deactivate_static_pick_place_background_prims = EventTermCfg(
                func=_deactivate_background_prims,
                mode="prestartup",
                params={"prim_relative_paths": _BACKGROUND_PRIMS_TO_DEACTIVATE},
            )
            env_cfg.num_rerenders_on_reset = 1
            return env_cfg

        scene = Scene(
            assets=[
                background,
                ground_plane,
                light,
                shelf_support,
                pick_up_object,
                destination,
            ]
        )
        
        return IsaacLabArenaEnvironment(
            name=self.name,
            embodiment=embodiment,
            scene=scene,
            task=PickAndPlaceTask(
                pick_up_object=pick_up_object,
                destination_location=destination,
                background_scene=background,
                episode_length_s=6.0,
                task_description=task_description,
                force_threshold=0.5,
                velocity_threshold=0.1,
            ),
            teleop_device=teleop_device,
            env_cfg_callback=env_cfg_callback,
        )

    @staticmethod
    def add_cli_args(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--object", type=str, default="apple_01_objaverse_robolab")
        parser.add_argument("--destination", type=str, default="clay_plates_hot3d_robolab")
        parser.add_argument("--embodiment", type=str, default="g1_brainco_custom")
        parser.add_argument("--teleop_device", type=str, default=None)
        parser.add_argument(
            "--task_description",
            type=str,
            default=None,
            help="Override natural-language task description.",
        )
        parser.add_argument(
            "--lock_waist",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Lock waist joints.",
        )
        parser.add_argument(
            "--enable_cameras",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Enable onboard cameras.",
        )
