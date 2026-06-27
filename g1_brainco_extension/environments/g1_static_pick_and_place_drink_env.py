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


# Per-asset uniform scale matching the tuned pick-up / destination pair.
_TUNED_SCALES: dict[str, tuple[float, float, float]] = {
    "apple_01_objaverse_robolab": (0.009, 0.009, 0.009),
    "clay_plates_hot3d_robolab": (0.5, 0.5, 0.5),
}


def _asset_scale(asset_name: str) -> tuple[float, float, float]:
    """Return the tuned uniform scale for asset_name, or 1.0 with a warning."""
    if asset_name in _TUNED_SCALES:
        return _TUNED_SCALES[asset_name]
    import warnings
    warnings.warn(
        "g1_static_pick_and_place_drink: no measured scale for "
        f"'{asset_name}'; spawning at scale=(1.0, 1.0, 1.0). Verify visually.",
        stacklevel=2,
    )
    return (1.0, 1.0, 1.0)


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
        from g1_brainco_extension.embodiments.mdp.robot_configs import ROBOT_INITIAL_POSE_XYZ

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
        
        # 1. Setup Embodiment Side Configuration
        # The solver can't place the embodiment, so compute the stance ourselves
        # from the table's world bounding box (mirrors NextTo's side semantics).
        _side_cfg = {  # (axis index, outward sign, yaw facing the table)
            Side.POSITIVE_X: (0, +1.0, np.pi),
            Side.NEGATIVE_X: (0, -1.0, 0.0),
            Side.POSITIVE_Y: (1, +1.0, -np.pi / 2.0),
            Side.NEGATIVE_Y: (1, -1.0,  np.pi / 2.0),
        }
        _robot_side = Side.POSITIVE_Y   # stand on -X, FACE +X toward the table
        _axis, _sign, _yaw = _side_cfg[_robot_side]
        _band = 1 - _axis
        
        # Determine the robot-side table edge along the active axis
        _u_edge = _lo[_axis] if _sign < 0 else _hi[_axis]
        
        # Determine object placement coordinates
        # Offset from table edge (within 10cm - 20cm range)
        _d_forward = 0.15
        _u_obj = _u_edge - _sign * _d_forward
        
        # Workspace center along the band/lateral axis (shifted to align with robot target area)
        _v_mid = _center[_band] - 0.10
        
        # Separation between source and destination (giving a 10cm gap)
        _separation = 0.30
        _v_src = _v_mid - _separation / 2.0
        _v_dst = _v_mid + _separation / 2.0
        
        # Assign coordinates to the bottles and destination centers
        drink_x_center = _u_obj if _axis == 0 else _v_src
        drink_y_center = _v_src if _axis == 0 else _u_obj
        
        dest_x_center = _u_obj if _axis == 0 else _v_dst
        dest_y_center = _v_dst if _axis == 0 else _u_obj
        
        # Bottles placement bounds
        drink_x_half = 0.05  # Ensures 10cm-20cm from border
        drink_y_half = 0.02  # Reduced area
        
        offsets = [(x * 0.08, y * 0.08) for x in [-1, 0, 1] for y in [-1, 0, 1]]
        for i, name in enumerate(object_names):
            obj = self.asset_registry.get_asset_by_name(name)(
                instance_name=f"{name}_{i}",
                scale=_asset_scale(name)
            )
            obj.add_relation(On(tabletop_reference))
            ox, oy = offsets[i % len(offsets)]
            obj.add_relation(AtPosition(x=drink_x_center + ox, y=drink_y_center + oy))
            obj.add_relation(RandomAroundSolution(x_half_m=drink_x_half, y_half_m=drink_y_half))
            if getattr(args_cli, "spawn_horizontal", False):
                obj.add_relation(RotateAroundSolution(roll_rad=np.pi/2))
            placeable_assets.append(obj)

        destination = self.asset_registry.get_asset_by_name(args_cli.destination)(
            scale=_asset_scale(args_cli.destination)
        )
        destination.add_relation(On(tabletop_reference))
        
        # Destination placement bounds
        dest_x_half = 0.02  # Reduced area
        dest_y_half = 0.02  # Reduced area
        
        destination.add_relation(AtPosition(x=dest_x_center, y=dest_y_center))
        destination.add_relation(RandomAroundSolution(x_half_m=dest_x_half, y_half_m=dest_y_half))

        # 2. Setup Embodiment
        embodiment = self.asset_registry.get_asset_by_name(args_cli.embodiment)(
            enable_cameras=args_cli.enable_cameras, 
            lock_waist=args_cli.lock_waist,
        )
        

        
        # Standoff Distance Solver: dynamically solve reach constraints
        _r_max = 0.65       # max reach of humanoid arms
        _d_min = 0.30       # minimum standoff distance to avoid table collisions
        
        # Solve for the maximum standoff distance to keep both target zones within reach
        import math
        _d_reach_max = math.sqrt(_r_max**2 - (_separation / 2.0)**2) - _d_forward
        
        # Validate that a valid placement is mathematically possible
        if _d_min > _d_reach_max:
            raise ValueError(
                f"Objects are placed too far apart ({_separation:.2f}m) or too deep ({_d_forward:.2f}m) "
                f"for the robot's maximum arm reach of {_r_max:.2f}m!"
            )
            
        # Select the optimal standoff distance (midpoint of valid range to maximize safety margin)
        _dist_from_edge_m = (_d_min + _d_reach_max) / 2.0
        
        # Compute final base coordinate position relative to the table edge
        _pos = [0.0, 0.0, ROBOT_INITIAL_POSE_XYZ[2]]
        _pos[_axis] = _u_edge + _sign * _dist_from_edge_m
        _pos[_band] = _v_mid
        
        embodiment.set_initial_pose(Pose(
            position_xyz=tuple(_pos),
            rotation_xyzw=(0.0, 0.0, np.sin(_yaw / 2.0), np.cos(_yaw / 2.0)),
        ))

        
        # Validate reachability for both targets
        _dist_to_drink = math.sqrt((drink_x_center - _pos[0])**2 + (drink_y_center - _pos[1])**2)
        _dist_to_dest = math.sqrt((dest_x_center - _pos[0])**2 + (dest_y_center - _pos[1])**2)
        assert _dist_to_drink <= _r_max, f"Bottles are out of reach! Distance is {_dist_to_drink:.2f}m (max allowed {_r_max:.2f}m)"
        assert _dist_to_dest <= _r_max, f"Destination is out of reach! Distance is {_dist_to_dest:.2f}m (max allowed {_r_max:.2f}m)"
        
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
                pick_up_object=placeable_assets[0], # pick_up_object=drink 
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
        parser.add_argument("--enable_cameras", action=argparse.BooleanOptionalAction, default=True)
        parser.add_argument("--teleop_device", type=str, default=None, help="Teleoperation device")
        parser.add_argument("--spawn_horizontal", action=argparse.BooleanOptionalAction, default=False, help="Spawn objects horizontally")
        parser.add_argument("--num_objects", type=int, default=4, help="Number of objects to spawn")
