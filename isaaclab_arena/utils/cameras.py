# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import inspect
import numpy as np
from contextlib import suppress
from dataclasses import fields, is_dataclass
from typing import Any, ClassVar

from isaaclab.envs import mdp
from isaaclab.envs.common import ViewerCfg
from isaaclab.managers import ObservationGroupCfg as ObsGroup
from isaaclab.managers import ObservationTermCfg as ObsTerm
from isaaclab.managers import SceneEntityCfg
from isaaclab.sensors import CameraCfg, TiledCameraCfg  # noqa: F401

from isaaclab_arena.assets.asset import Asset
from isaaclab_arena.utils.configclass import make_configclass
from isaaclab_arena.utils.pose import Pose, PosePerEnv, PoseRange


class ArenaCameraCfg:
    """Parent class for camera configs in Arena.

    CameraCfg configclasses subclass this and declare camera fields (as per usual). The get_cfg
    then returns the rig un-tiled, or a tiled copy dependent on the value of ``use_tiled_camera``.
    """

    # Backing flag; tiled by default. Kept as a ClassVar so it is not treated as a camera field; instances shadow it.
    _use_tiled_camera: ClassVar[bool] = True

    @property
    def use_tiled_camera(self) -> bool:
        """Whether :meth:`get_cfg` returns tiled cameras."""
        return self._use_tiled_camera

    @use_tiled_camera.setter
    def use_tiled_camera(self, use_tiled_camera: bool) -> None:
        self._use_tiled_camera = use_tiled_camera

    def set_use_tiled_camera(self, use_tiled_camera: bool) -> None:
        """Select whether get_cfg returns tiled cameras."""
        self._use_tiled_camera = use_tiled_camera

    def camera_names(self) -> list[str]:
        """Return the field name of every camera in this rig."""
        return [f.name for f in fields(self) if isinstance(getattr(self, f.name), CameraCfg)]

    def get_cfg(self) -> Any:
        """Return a copy of this rig, tiled or untiled depending on use_tiled_camera.

        A copy is returned so callers may freely combine or mutate it without affecting this instance.
        """
        if self._use_tiled_camera:
            return self._tiled_rig()
        return self.copy()

    def _tiled_rig(self) -> Any:
        """Return a copy of this rig with every untiled CameraCfg field converted to tiled."""
        tiled = self.copy()
        for f in fields(tiled):
            value = getattr(tiled, f.name)
            if isinstance(value, CameraCfg) and not isinstance(value, TiledCameraCfg):
                setattr(tiled, f.name, self._as_tiled_camera_cfg(value))
        return tiled

    def _as_tiled_camera_cfg(self, camera_cfg: CameraCfg) -> TiledCameraCfg:
        """Return a TiledCameraCfg mirroring the settings of an untiled CameraCfg."""
        init_fields = {
            f.name: getattr(camera_cfg, f.name) for f in fields(camera_cfg) if f.init and f.name != "class_type"
        }
        return TiledCameraCfg(**init_fields)


def make_camera_observation_cfg(
    camera_cfg: Any,
    normalize: bool = False,
):
    """
    Build a configclass instance that adds one ObsTerm per selected camera.
    The SceneEntity name equals the camera field name plus the data type used in the Scene.
    For example, if the camera field name is "robot_pov_cam" and the data type is "rgb", the SceneEntity name will be "robot_pov_cam_rgb".
    We create a class which has a member pointing to another class which is based on the ObsGroup class.
    """

    # If they passed the class, instantiate it so we can read values
    if inspect.isclass(camera_cfg):
        camera_cfg = camera_cfg()

    if not is_dataclass(camera_cfg):
        raise TypeError("camera_cfg must be a dataclass/configclass class or instance")

    obs_fields = []
    for f in fields(camera_cfg):
        name = f.name
        cam = getattr(camera_cfg, name)
        # Skip non-camera fields
        if not isinstance(cam, CameraCfg):
            continue

        # Get modalities from the camera cfg (fallback to rgb)
        dtypes = getattr(cam, "data_types", None) or ["rgb"]
        # one ObsTerm per modality
        for dt in dtypes:
            field_name = f"{name}_{dt}"
            term = ObsTerm(
                func=mdp.image,
                params={"sensor_cfg": SceneEntityCfg(name), "data_type": dt, "normalize": normalize},
            )
            # Field name on ObservationsCfg: use the camera name (or add suffix if you like)
            obs_fields.append((field_name, ObsTerm, term))

    if not obs_fields:
        EmptyCameraObsCfg = make_configclass("EmptyCameraObsCfg", [], bases=(ObsGroup,))
        WrappedEmpty = make_configclass(
            "WrappedCameraObsCfg",
            [("camera_obs", EmptyCameraObsCfg, EmptyCameraObsCfg())],
            namespace={"EmptyCameraObsCfg": EmptyCameraObsCfg},
        )
        return WrappedEmpty()

    # Create the post init to be used in the observation class
    def post_init(self):
        self.enable_corruption = False
        self.concatenate_terms = False

    # Has to inherit from ObsGroup
    AutoCameraObsCfg = make_configclass(
        "AutoCameraObsCfg", obs_fields, bases=(ObsGroup,), namespace={"__post_init__": post_init}
    )

    # Now wrap the observation group in an observation class
    WrappedCameraObsCfg = make_configclass(
        "WrappedCameraObsCfg",
        [("camera_obs", AutoCameraObsCfg, AutoCameraObsCfg())],
        namespace={"AutoCameraObsCfg": AutoCameraObsCfg},
    )

    with suppress(Exception):
        AutoCameraObsCfg.__qualname__ = f"{WrappedCameraObsCfg.__name__}.AutoCameraObsCfg"

    return WrappedCameraObsCfg()


def get_viewer_cfg_look_at_object(lookat_object: Asset, offset: np.ndarray) -> ViewerCfg:
    """Create a viewer configuration that looks at a specific object with an offset.

    This function positions the viewport camera at a location offset from an object's
    initial position, while keeping the camera focused on the object itself.
    Returns a default ViewerCfg with standard positioning if the object has no initial pose set.

    Args:
        lookat_object: The asset to look at. The camera will target this object's
            initial pose position.
        offset: 3D offset vector (x, y, z) in meters from the object's position
            to place the camera. For example, offset=[1.0, 1.0, 1.0] places the
            camera 1 meter away in each direction from the object.

    Returns:
        ViewerCfg configured with the camera position and target.
        Default ViewerCfg with standard positioning if the object has no initial pose set.
    """
    initial_pose = lookat_object.get_initial_pose()
    if initial_pose is None:
        print(f"{lookat_object.name} has no initial pose set. Using default ViewerCfg.")
        return ViewerCfg()

    if isinstance(initial_pose, PoseRange):
        initial_pose = initial_pose.get_midpoint()
    elif isinstance(initial_pose, PosePerEnv):
        initial_pose = initial_pose.poses[0] if initial_pose.poses else None
        if initial_pose is None:
            return ViewerCfg()

    # TODO(cvolk): Add float coercion to Pose.__post_init__ so this conversion is unnecessary.
    # Ensure we only pass primitive Python floats (not NumPy scalars) into ViewerCfg,
    # since downstream config systems like Hydra/OmegaConf don't support np.float64.
    lookat = tuple(float(x) for x in initial_pose.position_xyz)
    camera_vec = np.array(lookat, dtype=float) + np.array(offset, dtype=float)
    camera_position = tuple(float(x) for x in camera_vec.tolist())
    return ViewerCfg(eye=camera_position, lookat=lookat, origin_type="env")


def compute_robot_relative_viewer_cfg(
    embodiment: Asset | None,
    lookat_target: Asset | None = None,
    standoff_back: float = 1.10,
    standoff_side: float = 0.65,
    elevation: float = 0.85,
    fallback_offset: tuple[float, float, float] = (-1.5, -1.5, 1.5),
) -> ViewerCfg:
    """Compute an over-the-shoulder perspective ViewerCfg relative to the robot's base frame and gaze centroid.

    Positions the camera behind and to the side of the robot's shoulder, pointing directly
    at the active manipulation centroid or lookat target.

    Args:
        embodiment: The robot asset whose pose anchors the perspective camera.
        lookat_target: Optional target asset (e.g. manipuland or receptacle) to focus on.
        standoff_back: Distance in meters to place camera behind robot along heading.
        standoff_side: Distance in meters to place camera laterally (positive = right shoulder).
        elevation: Height in meters above robot standing height (z=0.75m).
        fallback_offset: Offset used if robot pose is not yet known.

    Returns:
        ViewerCfg configured with robot-relative eye and lookat coordinates.
    """
    import math

    if embodiment is not None:
        robot_pose = embodiment.get_initial_pose()
        if isinstance(robot_pose, PoseRange):
            robot_pose = robot_pose.get_midpoint()
        elif isinstance(robot_pose, PosePerEnv):
            robot_pose = robot_pose.poses[0] if robot_pose.poses else None

        if robot_pose is not None:
            r_pos = robot_pose.position_xyz
            r_rot = robot_pose.rotation_xyzw  # (x, y, z, w)

            # Compute yaw from quaternion (x, y, z, w)
            qx, qy, qz, qw = r_rot
            siny_cosp = 2.0 * (qw * qz + qx * qy)
            cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
            yaw = math.atan2(siny_cosp, cosy_cosp)

            u_fwd = np.array([math.cos(yaw), math.sin(yaw), 0.0])
            u_lat = np.array([-math.sin(yaw), math.cos(yaw), 0.0])

            # Standing pelvis level is ~0.75m above base
            r_center = np.array([r_pos[0], r_pos[1], r_pos[2] + 0.75])
            eye = r_center - standoff_back * u_fwd + standoff_side * u_lat + np.array([0.0, 0.0, elevation])

            if lookat_target is not None and lookat_target.get_initial_pose() is not None:
                t_pose = lookat_target.get_initial_pose()
                if isinstance(t_pose, PoseRange):
                    t_pose = t_pose.get_midpoint()
                elif isinstance(t_pose, PosePerEnv):
                    t_pose = t_pose.poses[0] if t_pose.poses else None

                if t_pose is not None:
                    lookat = np.array(t_pose.position_xyz)
                else:
                    lookat = r_center + 0.9 * u_fwd - np.array([0.0, 0.0, 0.1])
            else:
                # Default lookat: 0.9m in front of robot at table height
                lookat = r_center + 0.9 * u_fwd - np.array([0.0, 0.0, 0.1])

            return ViewerCfg(
                eye=tuple(float(x) for x in eye),
                lookat=tuple(float(x) for x in lookat),
                origin_type="env",
            )

    # Fallback to lookat target if embodiment pose not set
    if lookat_target is not None:
        return get_viewer_cfg_look_at_object(lookat_target, np.array(fallback_offset))

    return ViewerCfg()

