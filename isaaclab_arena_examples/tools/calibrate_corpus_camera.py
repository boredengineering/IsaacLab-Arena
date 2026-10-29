# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Recover the head-camera mount pose a recording was captured with, by fitting it to the frames.

``rerender_demos.py`` establishes that state playback is exact while the rendered image still
disagrees with the recording, and that the disagreement has the near/far parallax signature of a
camera-mount difference rather than a scene-layout one. This tool measures that difference: it pins
the simulator to a recorded state and searches camera offsets for the one that reproduces the
recorded frame.

The camera pose is set at runtime, so the whole search runs in a single simulator session rather
than one boot per candidate.
"""

"""Launch Isaac Sim Simulator first."""

from isaaclab.app import AppLauncher

from isaaclab_arena.cli.isaaclab_arena_cli import get_isaaclab_arena_cli_parser
from isaaclab_arena_environments.cli import add_example_environments_cli_args, get_arena_builder_from_cli

parser = get_isaaclab_arena_cli_parser()
parser.add_argument("--dataset_file", type=str, required=True, help="HDF5 recording to fit the camera against.")
parser.add_argument("--episode", type=int, default=0, help="Episode index to fit against.")
parser.add_argument(
    "--fit_frames",
    type=int,
    nargs="+",
    default=[0, 40, 80],
    help="Frames the objective averages over. Several frames stop the fit latching onto one pose.",
)
parser.add_argument("--camera_name", type=str, default="robot_head_cam", help="Camera field name on the embodiment.")
parser.add_argument("--parent_body", type=str, default="head_link", help="Body the camera offset is relative to.")
parser.add_argument("--renders_per_frame", type=int, default=2, help="RTX render calls per candidate evaluation.")
parser.add_argument("--out_json", type=str, required=True, help="Where to write the fitted offset and search trace.")
parser.add_argument(
    "--refinement_passes",
    type=int,
    default=3,
    help="Coordinate-descent passes. Each pass halves the step sizes.",
)
parser.add_argument(
    "--position_step_m", type=float, default=0.06, help="Initial position step for the search, in metres."
)
parser.add_argument(
    "--rotation_step_deg", type=float, default=6.0, help="Initial rotation step for the search, in degrees."
)

# NOTE: added last so the environment subcommand's flags parse after the main-parser flags.
add_example_environments_cli_args(parser)

args_cli = parser.parse_args()
args_cli.headless = True
args_cli.enable_cameras = True

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

"""Rest everything follows."""

import gymnasium as gym
import h5py
import json
import math
import numpy as np
import torch

from isaaclab.utils.math import convert_camera_frame_orientation_convention, quat_apply, quat_mul

from isaaclab_arena.utils.demo_playback import frame_state_for_scene, read_recorded_states

# The camera offset is six numbers; the search walks them one at a time.
OFFSET_AXES = ("x", "y", "z", "roll", "pitch", "yaw")


def xyzw_to_wxyz(quat_xyzw: torch.Tensor) -> torch.Tensor:
    """Reorder a quaternion from ``(x, y, z, w)`` to Isaac Lab's ``(w, x, y, z)``."""
    return quat_xyzw[..., [3, 0, 1, 2]]


def wxyz_to_xyzw(quat_wxyz: torch.Tensor) -> torch.Tensor:
    """Reorder a quaternion from Isaac Lab's ``(w, x, y, z)`` to ``(x, y, z, w)``."""
    return quat_wxyz[..., [1, 2, 3, 0]]


def axis_quat_wxyz(axis: int, angle_rad: float, device: str) -> torch.Tensor:
    """Return the ``(w, x, y, z)`` quaternion for a rotation about one basis axis.

    Args:
        axis: 0 for x, 1 for y, 2 for z.
        angle_rad: Rotation angle in radians.
        device: Device to build the tensor on.

    Returns:
        The quaternion, shape ``(1, 4)``.
    """
    quat = torch.zeros(1, 4, device=device, dtype=torch.float32)
    quat[0, 0] = math.cos(angle_rad / 2.0)
    quat[0, 1 + axis] = math.sin(angle_rad / 2.0)
    return quat


def euler_to_quat_wxyz(roll: float, pitch: float, yaw: float, device: str) -> torch.Tensor:
    """Return the ``(w, x, y, z)`` quaternion for successive x, then y, then z rotations.

    Composed from explicit single-axis quaternions rather than an expanded closed form, because a
    sign slip in a hand-derived Euler formula is invisible until the fit quietly converges somewhere
    wrong.

    Args:
        roll: Rotation about x, in radians.
        pitch: Rotation about y, in radians.
        yaw: Rotation about z, in radians.
        device: Device to build the tensor on.

    Returns:
        The composed quaternion, shape ``(1, 4)``.
    """
    quat = axis_quat_wxyz(0, roll, device)
    quat = quat_mul(quat, axis_quat_wxyz(1, pitch, device))
    return quat_mul(quat, axis_quat_wxyz(2, yaw, device))


def compose_camera_world_pose(
    parent_pos_w: torch.Tensor,
    parent_quat_w_wxyz: torch.Tensor,
    offset_pos: torch.Tensor,
    offset_quat_ros_wxyz: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Place a ROS-convention camera offset, expressed in a parent body's frame, into the world.

    Mirrors what Isaac Lab's camera does with ``OffsetCfg``: the offset rotation is converted from
    its declared convention to OpenGL and applied as the camera prim's local orientation
    (``camera.py:151-155``), so the composition has to happen in OpenGL rather than in ROS. Getting
    this wrong composes a world-frame rotation with a ROS-camera rotation and silently mislocates
    the camera; the returned orientation is therefore in the OpenGL convention, and the caller must
    hand it to ``set_world_poses`` as such.

    Args:
        parent_pos_w: Parent body position in world, shape ``(N, 3)``.
        parent_quat_w_wxyz: Parent body orientation in world as ``(w, x, y, z)``, shape ``(N, 4)``.
        offset_pos: Offset translation in the parent frame, shape ``(3,)`` or ``(N, 3)``.
        offset_quat_ros_wxyz: Offset rotation in the ROS convention as ``(w, x, y, z)``, shape ``(1, 4)``.

    Returns:
        Camera world position ``(N, 3)`` and OpenGL-convention orientation ``(N, 4)`` as ``(w, x, y, z)``.
    """
    offset_quat_opengl_xyzw = convert_camera_frame_orientation_convention(
        wxyz_to_xyzw(offset_quat_ros_wxyz), origin="ros", target="opengl"
    )
    offset_quat_opengl_wxyz = xyzw_to_wxyz(offset_quat_opengl_xyzw).expand(parent_quat_w_wxyz.shape[0], 4)
    position = parent_pos_w + quat_apply(parent_quat_w_wxyz, offset_pos.expand(parent_pos_w.shape[0], 3))
    orientation = quat_mul(parent_quat_w_wxyz, offset_quat_opengl_wxyz)
    return position, orientation


class CameraFitter:
    """Renders a pinned recorded state under candidate camera offsets and scores them.

    Args:
        env: The unwrapped environment, already reset.
        camera_name: Scene key of the camera sensor to move.
        parent_body: Body whose frame the offset is expressed in.
        recorded_states: Per-frame recorded state arrays for the episode.
        recorded_rgb: Recorded frames to fit against, shape ``(T, H, W, 3)``.
        fit_frames: Frame indices the objective averages over.
        renders_per_frame: RTX render calls per evaluation.
    """

    def __init__(self, env, camera_name, parent_body, recorded_states, recorded_rgb, fit_frames, renders_per_frame):
        self._env = env
        self._camera = env.scene[camera_name]
        self._rgb_key = f"{camera_name}_rgb"
        self._recorded_states = recorded_states
        self._recorded_rgb = recorded_rgb
        self._fit_frames = fit_frames
        self._renders_per_frame = renders_per_frame
        self._env_ids = torch.tensor([0], device=env.device)
        self._evaluations = 0

        body_names = list(env.scene["robot"].body_names)
        assert parent_body in body_names, f"Body {parent_body!r} not on the robot. Available: {body_names}"
        self._parent_index = body_names.index(parent_body)

    @property
    def evaluations(self) -> int:
        """Number of candidate offsets rendered so far."""
        return self._evaluations

    def _write_frame_state(self, frame_index: int) -> None:
        """Pin the scene to a recorded frame."""
        state = frame_state_for_scene(
            self._env.scene.get_state(is_relative=True), self._recorded_states, frame_index, str(self._env.device)
        )
        self._env.scene.reset_to(state, self._env_ids, is_relative=True)
        self._env.sim.forward()

    def _place_camera(self, offset_pos: torch.Tensor, offset_quat_wxyz: torch.Tensor) -> None:
        """Move the camera to an offset expressed in the parent body's frame."""
        robot = self._env.scene["robot"]
        parent_pos = robot.data.body_pos_w[:, self._parent_index, :]
        parent_quat = robot.data.body_quat_w[:, self._parent_index, :]
        position, orientation = compose_camera_world_pose(parent_pos, parent_quat, offset_pos, offset_quat_wxyz)
        # compose_camera_world_pose returns an OpenGL-convention orientation, matching how the
        # camera prim itself is oriented.
        self._camera.set_world_poses(position, wxyz_to_xyzw(orientation), convention="opengl")

    def _render_rgb(self) -> np.ndarray:
        """Render and return the current camera RGB frame as ``(H, W, 3)`` uint8."""
        self._env.scene.update(dt=self._env.physics_dt)
        for _ in range(self._renders_per_frame):
            self._env.sim.render()
        frame = self._env.observation_manager.compute()["camera_obs"][self._rgb_key][0]
        frame = frame.detach().to("cpu")
        if frame.dtype != torch.uint8:
            frame = frame.clamp(0, 255).to(torch.uint8)
        return np.ascontiguousarray(frame.numpy()[..., :3])

    def composition_residual(self, offset_pos: torch.Tensor, offset_quat_wxyz: torch.Tensor, frame_index: int) -> float:
        """Return the difference between the config-driven view and the same offset set at runtime.

        The search only means anything if placing the shipped offset by hand reproduces the shipped
        view. A large residual here indicates a convention or composition error in this tool, and
        would otherwise surface as a fit that converges confidently on the wrong pose.

        Args:
            offset_pos: The shipped offset translation, shape ``(3,)``.
            offset_quat_wxyz: The shipped offset rotation as ``(w, x, y, z)``, shape ``(1, 4)``.
            frame_index: Frame to compare on.

        Returns:
            Mean absolute difference between the two renders, in 0-255 units.
        """
        self._write_frame_state(frame_index)
        config_driven = self._render_rgb().astype(np.float64)

        # Compare the poses numerically as well as the pixels: an image residual says the two views
        # differ, while the pose delta says by how much and in which component, which is what
        # actually localises a convention or parent-frame mistake.
        config_pos = self._camera.data.pos_w[0].detach().cpu().numpy().copy()
        config_quat = self._camera.data.quat_w_opengl[0].detach().cpu().numpy().copy()

        robot = self._env.scene["robot"]
        composed_pos, composed_quat = compose_camera_world_pose(
            robot.data.body_pos_w[:, self._parent_index, :],
            robot.data.body_quat_w[:, self._parent_index, :],
            offset_pos,
            offset_quat_wxyz,
        )
        composed_pos = composed_pos[0].detach().cpu().numpy()
        composed_quat = composed_quat[0].detach().cpu().numpy()
        print(f"[Calibrate]   camera pos_w  from cfg={config_pos.round(5)} composed={composed_pos.round(5)}")
        print(f"[Calibrate]   camera quat   from cfg={config_quat.round(5)} composed={composed_quat.round(5)}")
        print(f"[Calibrate]   |pos delta| = {float(np.abs(config_pos - composed_pos).max()):.6f}")

        self._place_camera(offset_pos, offset_quat_wxyz)
        placed_pos = self._camera.data.pos_w[0].detach().cpu().numpy().copy()
        print(f"[Calibrate]   camera pos_w after set_world_poses={placed_pos.round(5)}")
        hand_placed = self._render_rgb().astype(np.float64)
        print(f"[Calibrate]   camera pos_w after render={self._camera.data.pos_w[0].detach().cpu().numpy().round(5)}")
        return float(np.abs(config_driven - hand_placed).mean())

    def score(self, offset_pos: torch.Tensor, offset_quat_wxyz: torch.Tensor) -> float:
        """Return the mean absolute difference against the recording, averaged over the fit frames.

        Args:
            offset_pos: Candidate offset translation in the parent frame, shape ``(3,)``.
            offset_quat_wxyz: Candidate offset rotation as ``(w, x, y, z)``, shape ``(1, 4)``.

        Returns:
            Mean absolute difference in 0-255 units. Lower is better.
        """
        errors = []
        for frame_index in self._fit_frames:
            self._write_frame_state(frame_index)
            # The camera prim rides the parent body, so it has to be re-placed after every state write.
            self._place_camera(offset_pos, offset_quat_wxyz)
            rendered = self._render_rgb().astype(np.float64)
            reference = self._recorded_rgb[frame_index].astype(np.float64)
            errors.append(float(np.abs(rendered - reference).mean()))
        self._evaluations += 1
        return float(np.mean(errors))


def coordinate_descent(fitter: CameraFitter, base_pos, base_quat_wxyz, args, device: str) -> dict:
    """Search the six offset degrees of freedom one at a time, halving the step each pass.

    A pattern search rather than a gradient method: each evaluation costs a render, the objective is
    non-differentiable through the renderer, and six dimensions is small enough to walk directly.

    Args:
        fitter: Configured :class:`CameraFitter`.
        base_pos: Starting offset translation, shape ``(3,)``.
        base_quat_wxyz: Starting offset rotation as ``(w, x, y, z)``, shape ``(1, 4)``.
        args: Parsed CLI arguments supplying step sizes and pass count.
        device: Device to build tensors on.

    Returns:
        Mapping with the fitted offset, its score, the starting score, and the search trace.
    """
    best_pos = base_pos.clone()
    best_delta_rpy = [0.0, 0.0, 0.0]

    def quat_for(delta_rpy) -> torch.Tensor:
        return quat_mul(base_quat_wxyz, euler_to_quat_wxyz(*delta_rpy, device=device))

    best_score = fitter.score(best_pos, quat_for(best_delta_rpy))
    initial_score = best_score
    trace = [{"pass": 0, "axis": "start", "score": round(best_score, 4)}]
    print(f"[Calibrate] start score {best_score:.4f}")

    position_step = args.position_step_m
    rotation_step = math.radians(args.rotation_step_deg)

    for pass_index in range(1, args.refinement_passes + 1):
        improved_this_pass = False
        for axis_index, axis_name in enumerate(OFFSET_AXES):
            is_rotation = axis_index >= 3
            step = rotation_step if is_rotation else position_step
            for direction in (+1.0, -1.0):
                candidate_pos = best_pos.clone()
                candidate_rpy = list(best_delta_rpy)
                if is_rotation:
                    candidate_rpy[axis_index - 3] += direction * step
                else:
                    candidate_pos[axis_index] += direction * step
                score = fitter.score(candidate_pos, quat_for(candidate_rpy))
                if score < best_score - 1e-6:
                    best_score, best_pos, best_delta_rpy = score, candidate_pos, candidate_rpy
                    improved_this_pass = True
                    trace.append({
                        "pass": pass_index,
                        "axis": axis_name,
                        "direction": direction,
                        "step": round(step, 5),
                        "score": round(score, 4),
                    })
                    print(f"[Calibrate] pass {pass_index} {axis_name} {direction:+.0f} -> {score:.4f}")
                    break
        position_step /= 2.0
        rotation_step /= 2.0
        if not improved_this_pass:
            print(f"[Calibrate] pass {pass_index}: no axis improved; stopping early")
            break

    fitted_quat = quat_for(best_delta_rpy)
    return {
        "initial_score_mean_abs_diff": round(initial_score, 4),
        "fitted_score_mean_abs_diff": round(best_score, 4),
        "improvement_fraction": round((initial_score - best_score) / initial_score, 4) if initial_score else 0.0,
        "fitted_offset_pos": [round(v, 5) for v in best_pos.tolist()],
        "fitted_offset_rot_xyzw": [round(v, 6) for v in wxyz_to_xyzw(fitted_quat)[0].tolist()],
        "fitted_delta_rpy_deg": [round(math.degrees(v), 3) for v in best_delta_rpy],
        "evaluations": fitter.evaluations,
        "trace": trace,
    }


COMPOSITION_RESIDUAL_TOLERANCE = 1.5
"""Largest mean-absolute-difference accepted between the config-driven and hand-placed views.

Above codec-free render noise but far below the ~52 unit discrepancy under investigation, so it
catches a convention error without tripping on nondeterministic shading.
"""


def main() -> None:
    """Fit the head-camera offset to a recording and write the result."""
    import os

    arena_builder = get_arena_builder_from_cli(args_cli)
    camera_rig = arena_builder.arena_env.embodiment.camera_config
    shipped_camera = getattr(camera_rig, args_cli.camera_name)
    shipped_offset_pos = [float(v) for v in shipped_camera.offset.pos]
    shipped_offset_rot_xyzw = [float(v) for v in shipped_camera.offset.rot]
    print(f"[Calibrate] shipped offset pos={shipped_offset_pos} rot_xyzw={shipped_offset_rot_xyzw}")

    env_name, env_cfg, env_kwargs = arena_builder.build_registered()
    env_cfg.recorders = {}
    env_cfg.terminations = {}
    env = gym.make(env_name, cfg=env_cfg, **env_kwargs)
    from isaaclab_arena.utils.isaaclab_utils.simulation_app import reapply_viewer_cfg

    reapply_viewer_cfg(env)
    env = env.unwrapped
    env.reset()

    with h5py.File(args_cli.dataset_file, "r") as dataset:
        demo_names = sorted(dataset["data"].keys(), key=lambda name: int(name.split("_")[-1]))
        demo = dataset["data"][demo_names[args_cli.episode]]
        recorded_states = read_recorded_states(demo)
        recorded_rgb = np.asarray(demo["camera_obs"]["robot_head_cam_rgb"])
        num_frames = int(demo.attrs["num_samples"])

    fit_frames = [f for f in args_cli.fit_frames if f < num_frames]
    assert fit_frames, f"None of {args_cli.fit_frames} is within this episode's {num_frames} frames."
    print(f"[Calibrate] fitting against frames {fit_frames} of {num_frames}")

    device = str(env.device)
    base_pos = torch.tensor(shipped_offset_pos, device=device, dtype=torch.float32)
    base_quat_wxyz = xyzw_to_wxyz(torch.tensor([shipped_offset_rot_xyzw], device=device, dtype=torch.float32))

    fitter = CameraFitter(
        env,
        args_cli.camera_name,
        args_cli.parent_body,
        recorded_states,
        recorded_rgb,
        fit_frames,
        args_cli.renders_per_frame,
    )

    residual = fitter.composition_residual(base_pos, base_quat_wxyz, fit_frames[0])
    print(f"[Calibrate] pose-composition self-check residual: {residual:.4f}")
    assert residual <= COMPOSITION_RESIDUAL_TOLERANCE, (
        "Placing the shipped offset by hand does not reproduce the shipped view (residual"
        f" {residual:.3f} > {COMPOSITION_RESIDUAL_TOLERANCE}). The offset composition or quaternion"
        " convention in this tool is wrong, so any fit it produces would be meaningless."
    )

    result = coordinate_descent(fitter, base_pos, base_quat_wxyz, args_cli, device)
    result["shipped_offset_pos"] = shipped_offset_pos
    result["shipped_offset_rot_xyzw"] = shipped_offset_rot_xyzw
    result["composition_residual"] = round(residual, 4)
    result["episode"] = args_cli.episode
    result["fit_frames"] = fit_frames
    result["environment"] = env_name

    os.makedirs(os.path.dirname(args_cli.out_json) or ".", exist_ok=True)
    with open(args_cli.out_json, "w") as handle:
        json.dump(result, handle, indent=2)

    print("\n[Calibrate] ==== fitted head-camera offset ====")
    print(f"  position_xyz  = {tuple(result['fitted_offset_pos'])}")
    print(f"  rotation_xyzw = {tuple(result['fitted_offset_rot_xyzw'])}")
    print(f"  delta rpy deg = {result['fitted_delta_rpy_deg']}")
    print(
        f"  score {result['initial_score_mean_abs_diff']} -> {result['fitted_score_mean_abs_diff']}"
        f" ({result['improvement_fraction']:.1%} of the error removed, {result['evaluations']} renders)"
    )
    print(f"[Calibrate] Wrote {args_cli.out_json}")
    env.close()


if __name__ == "__main__":
    main()
    simulation_app.close()
