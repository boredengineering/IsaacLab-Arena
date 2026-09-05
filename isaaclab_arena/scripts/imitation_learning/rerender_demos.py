# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Re-render recorded demonstrations by state playback, capturing RGB and ground-truth depth.

Unlike ``replay_demos.py``, which replays *actions* from an initial state and therefore diverges
from the recording, this script *writes* the recorded simulator state for every frame before
rendering. The rendered frame is consequently pixel-aligned with the recorded one, which is what
makes the ground-truth depth usable as supervision for the frames the policy was trained on.

The camera offset may be perturbed while the recorded actions are left untouched, producing extra
(observation, action) pairs that teach invariance to camera pose.
"""

"""Launch Isaac Sim Simulator first."""

from isaaclab.app import AppLauncher

from isaaclab_arena.cli.isaaclab_arena_cli import get_isaaclab_arena_cli_parser
from isaaclab_arena_environments.cli import add_example_environments_cli_args, get_arena_builder_from_cli

parser = get_isaaclab_arena_cli_parser()
parser.add_argument("--dataset_file", type=str, required=True, help="HDF5 recording to re-render.")
parser.add_argument(
    "--select_episodes",
    type=int,
    nargs="+",
    default=[],
    help="Episode indices to re-render. Empty re-renders every episode in the file.",
)
parser.add_argument("--out_dir", type=str, required=True, help="Directory to write frames and metadata into.")
parser.add_argument(
    "--camera_pitch_deg",
    type=float,
    default=0.0,
    help="Pitch applied to the camera offset, in degrees. Positive pitches the camera down.",
)
parser.add_argument(
    "--camera_height_offset_m",
    type=float,
    default=0.0,
    help="Vertical offset applied to the camera position, in metres.",
)
parser.add_argument(
    "--renders_per_frame",
    type=int,
    default=2,
    help=(
        "RTX render calls issued after writing each state. The RTX sensor pipeline lags the write, so"
        " too few renders yields the previous frame; the RGB fidelity report is what validates this."
    ),
)
parser.add_argument(
    "--camera_far_clip_m",
    type=float,
    default=20.0,
    help=(
        "Far clipping plane. The shipped G1 camera clips at 5 m, beyond which depth reads as inf;"
        " widening it keeps the background finite."
    ),
)
parser.add_argument("--camera_name", type=str, default="robot_head_cam", help="Camera field name on the embodiment.")
parser.add_argument("--no_depth", action="store_true", help="Render RGB only, skipping the depth annotator.")
parser.add_argument(
    "--depth_downsample",
    type=int,
    default=1,
    help="Store depth at 1/N resolution. Depth is only needed at patch-grid resolution downstream.",
)
parser.add_argument(
    "--max_frames_per_episode",
    type=int,
    default=0,
    help="Truncate each episode to this many frames. 0 re-renders every frame. Intended for smoke tests.",
)
parser.add_argument(
    "--fps", type=int, default=50, help="Frame rate written into the RGB videos. Must match the recording."
)
parser.add_argument(
    "--validate_states",
    action="store_true",
    help=(
        "After writing each state, read it back and report the discrepancy. Separates 'the recording"
        " did not apply' from 'the scene renders the recorded state differently'."
    ),
)

# NOTE: This has to be added last, because the example-environment subparser flags are parsed after
# the main-parser flags. Every main-parser argument must precede the environment subcommand.
add_example_environments_cli_args(parser)

args_cli = parser.parse_args()
args_cli.headless = True
args_cli.enable_cameras = True

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

"""Rest everything follows."""

import contextlib
import gymnasium as gym
import h5py
import json
import math
import numpy as np
import os
import torch
import torchvision

from isaaclab.sensors import CameraCfg

DEPTH_DATA_TYPE = "distance_to_image_plane"


def quat_mul_xyzw(q_a: tuple[float, ...], q_b: tuple[float, ...]) -> tuple[float, float, float, float]:
    """Return the Hamilton product ``q_a * q_b`` for quaternions in ``(x, y, z, w)`` order.

    Args:
        q_a: Left quaternion as ``(x, y, z, w)``.
        q_b: Right quaternion as ``(x, y, z, w)``.

    Returns:
        The product quaternion as ``(x, y, z, w)``.
    """
    x_a, y_a, z_a, w_a = q_a
    x_b, y_b, z_b, w_b = q_b
    return (
        w_a * x_b + x_a * w_b + y_a * z_b - z_a * y_b,
        w_a * y_b - x_a * z_b + y_a * w_b + z_a * x_b,
        w_a * z_b + x_a * y_b - y_a * x_b + z_a * w_b,
        w_a * w_b - x_a * x_b - y_a * y_b - z_a * z_b,
    )


def pitched_camera_offset(offset: CameraCfg.OffsetCfg, pitch_deg: float, height_offset_m: float):
    """Return a copy of ``offset`` pitched about the camera's own right axis and raised.

    The offset uses the ROS optical convention (x right, y down, z forward), so a rotation about the
    local x axis is what tilts the view up or down. Positive ``pitch_deg`` pitches the camera down.

    Args:
        offset: The camera offset to perturb.
        pitch_deg: Pitch to apply, in degrees.
        height_offset_m: Vertical translation to add to the offset position, in metres.

    Returns:
        A new ``CameraCfg.OffsetCfg`` carrying the perturbed pose and the original convention.
    """
    half_angle = math.radians(pitch_deg) / 2.0
    pitch_quat = (math.sin(half_angle), 0.0, 0.0, math.cos(half_angle))
    rotated = quat_mul_xyzw(tuple(float(v) for v in offset.rot), pitch_quat)
    position = (float(offset.pos[0]), float(offset.pos[1]), float(offset.pos[2]) + height_offset_m)
    return CameraCfg.OffsetCfg(pos=position, rot=rotated, convention=offset.convention)


def read_recorded_states(demo_group: h5py.Group) -> dict[str, dict[str, dict[str, np.ndarray]]]:
    """Return the per-frame recorded state arrays for one demo, keyed by asset type and name.

    Args:
        demo_group: The ``data/demo_N`` group of a recording.

    Returns:
        Nested mapping ``{asset_type: {asset_name: {state_name: array of shape (T, D)}}}``.
    """
    states: dict[str, dict[str, dict[str, np.ndarray]]] = {}
    for asset_type in ("articulation", "rigid_object"):
        if asset_type not in demo_group["states"]:
            continue
        states[asset_type] = {}
        for asset_name, asset_group in demo_group["states"][asset_type].items():
            states[asset_type][asset_name] = {name: np.asarray(arr) for name, arr in asset_group.items()}
    return states


def frame_state_for_scene(
    scene_state: dict[str, dict[str, dict[str, torch.Tensor]]],
    recorded: dict[str, dict[str, dict[str, np.ndarray]]],
    frame_index: int,
    device: str,
) -> dict[str, dict[str, dict[str, torch.Tensor]]]:
    """Overlay one recorded frame onto the scene's current state, leaving unrecorded assets alone.

    Starting from the live scene state rather than building a fresh dict means an asset the scene
    has but the recording does not (an invisible support surface, say) keeps its own pose instead of
    raising.

    Args:
        scene_state: Current scene state, as returned by ``InteractiveScene.get_state``.
        recorded: Per-frame recorded arrays from :func:`read_recorded_states`.
        frame_index: Frame to overlay.
        device: Device to place the overlaid tensors on.

    Returns:
        A state dict in the format ``InteractiveScene.reset_to`` expects.
    """
    overlaid = {
        asset_type: {asset_name: dict(entries) for asset_name, entries in assets.items()}
        for asset_type, assets in scene_state.items()
    }
    for asset_type, assets in recorded.items():
        for asset_name, entries in assets.items():
            if asset_type not in overlaid or asset_name not in overlaid[asset_type]:
                continue
            for state_name, array in entries.items():
                if state_name not in overlaid[asset_type][asset_name]:
                    continue
                value = torch.as_tensor(array[frame_index], dtype=torch.float32, device=device)
                overlaid[asset_type][asset_name][state_name] = value.unsqueeze(0)
    return overlaid


def assert_recording_covers_scene(
    scene_state: dict[str, dict[str, dict[str, torch.Tensor]]],
    recorded: dict[str, dict[str, dict[str, np.ndarray]]],
) -> list[str]:
    """Assert the recording drives the robot, and report scene assets it does not drive.

    Args:
        scene_state: Current scene state.
        recorded: Per-frame recorded arrays.

    Returns:
        Names of scene assets left at their live pose because the recording does not contain them.
    """
    recorded_articulations = set(recorded.get("articulation", {}))
    scene_articulations = set(scene_state.get("articulation", {}))
    assert scene_articulations & recorded_articulations, (
        "The recording drives none of the scene's articulations, so playback would render a scene the"
        f" recording never describes. Scene has {sorted(scene_articulations)}, recording has"
        f" {sorted(recorded_articulations)}."
    )
    undriven = []
    for asset_type, assets in scene_state.items():
        for asset_name in assets:
            if asset_name not in recorded.get(asset_type, {}):
                undriven.append(f"{asset_type}/{asset_name}")
    return sorted(undriven)


def rgb_fidelity(rendered: np.ndarray, recorded: np.ndarray) -> dict[str, float]:
    """Compare a rendered frame against the recorded one.

    Args:
        rendered: Rendered frame, ``(H, W, 3)`` uint8.
        recorded: Recorded frame, ``(H, W, 3)`` uint8.

    Returns:
        Mapping with ``mean_abs_diff`` in 0-255 units and ``psnr_db`` (``inf`` for an exact match).
    """
    lhs = rendered.astype(np.float64)
    rhs = recorded.astype(np.float64)
    mean_squared_error = float(np.mean((lhs - rhs) ** 2))
    psnr = float("inf") if mean_squared_error == 0.0 else 10.0 * math.log10(255.0**2 / mean_squared_error)
    return {"mean_abs_diff": float(np.mean(np.abs(lhs - rhs))), "psnr_db": psnr}


def state_playback_error(env, written: dict) -> dict[str, float]:
    """Read the scene state back after a write and return the worst discrepancy per asset.

    A silent mismatch here is the difference between "the recording did not apply" and "the scene
    renders the recorded state differently", which are diagnosed in completely different places.

    Args:
        env: The unwrapped environment, already advanced with ``sim.forward()``.
        written: The state dict that was handed to ``InteractiveScene.reset_to``.

    Returns:
        Mapping from ``"<asset_type>/<asset>/<state>"`` to the maximum absolute difference.
    """
    realised = env.scene.get_state(is_relative=True)
    errors = {}
    for asset_type, assets in written.items():
        for asset_name, entries in assets.items():
            for state_name, value in entries.items():
                other = realised.get(asset_type, {}).get(asset_name, {}).get(state_name)
                if other is None:
                    continue
                diff = (value.to(other.device).float() - other.float()).abs().max()
                errors[f"{asset_type}/{asset_name}/{state_name}"] = float(diff)
    return errors


def configure_camera(
    embodiment, camera_name: str, want_depth: bool, far_clip_m: float, pitch_deg: float, height_m: float
):
    """Mutate the embodiment's camera in place, before the env cfg is built from it.

    The data types drive both the scene sensor and the generated observation terms, so this has to
    happen before ``build_registered``. It is deliberately applied to the builder's own embodiment
    instance rather than the shared ``G1CameraCfg`` default, so no other caller pays for the second
    annotator.

    Args:
        embodiment: Embodiment whose ``camera_config`` is perturbed.
        camera_name: Camera field name on the camera rig.
        want_depth: Whether to add the depth annotator.
        far_clip_m: Far clipping plane, in metres.
        pitch_deg: Camera pitch, in degrees. Positive pitches down.
        height_m: Vertical camera offset, in metres.

    Returns:
        Mapping describing the applied camera configuration, for the run metadata.
    """
    camera_rig = embodiment.camera_config
    assert camera_rig is not None, "The chosen embodiment declares no camera rig, so there is nothing to render."
    assert hasattr(
        camera_rig, camera_name
    ), f"Camera {camera_name!r} is not on this embodiment's rig. Available: {camera_rig.camera_names()}."
    camera_cfg = getattr(camera_rig, camera_name)

    data_types = ["rgb"] + ([DEPTH_DATA_TYPE] if want_depth else [])
    camera_cfg.data_types = data_types

    near_clip = float(camera_cfg.spawn.clipping_range[0])
    camera_cfg.spawn.clipping_range = (near_clip, far_clip_m)

    if pitch_deg != 0.0 or height_m != 0.0:
        camera_cfg.offset = pitched_camera_offset(camera_cfg.offset, pitch_deg, height_m)

    return {
        "camera_name": camera_name,
        "data_types": data_types,
        "clipping_range": [near_clip, far_clip_m],
        "offset_pos": [float(v) for v in camera_cfg.offset.pos],
        "offset_rot_xyzw": [float(v) for v in camera_cfg.offset.rot],
        "offset_convention": camera_cfg.offset.convention,
        "camera_pitch_deg": pitch_deg,
        "camera_height_offset_m": height_m,
        "resolution_hw": [int(camera_cfg.height), int(camera_cfg.width)],
    }


def render_frame(env, renders_per_frame: int, rgb_key: str, depth_key: str | None):
    """Render the current simulator state and return the camera observation the policy would see.

    Mirrors the refresh protocol ``ManagerBasedEnv.reset_to`` uses after writing state: sync
    kinematics, issue RTX renders, then recompute observations.

    Args:
        env: The unwrapped environment.
        renders_per_frame: Number of RTX render calls to issue.
        rgb_key: Observation key for the RGB image.
        depth_key: Observation key for depth, or None when depth is not rendered.

    Returns:
        Tuple of the RGB frame ``(H, W, 3)`` uint8 and the depth frame ``(H, W)`` float32 or None.
    """
    env.sim.forward()
    # InteractiveScene.update is what pushes the written transforms into the render context and
    # marks the sensors outdated. Without it the buffers hold the new state while the renderer
    # still draws the previous one, which validates as correct and renders as wrong.
    env.scene.update(dt=env.physics_dt)
    for _ in range(renders_per_frame):
        env.sim.render()
    camera_obs = env.observation_manager.compute()["camera_obs"]

    assert rgb_key in camera_obs, f"Camera observation {rgb_key!r} missing. Available: {sorted(camera_obs)}."
    rgb = camera_obs[rgb_key][0].detach().to("cpu")
    if rgb.dtype != torch.uint8:
        rgb = rgb.clamp(0, 255).to(torch.uint8)
    rgb_np = rgb.numpy()
    if rgb_np.shape[0] in (1, 3, 4) and rgb_np.shape[0] < rgb_np.shape[-1]:
        rgb_np = np.transpose(rgb_np, (1, 2, 0))
    rgb_np = np.ascontiguousarray(rgb_np[..., :3])

    depth_np = None
    if depth_key is not None:
        assert depth_key in camera_obs, f"Depth observation {depth_key!r} missing. Available: {sorted(camera_obs)}."
        depth = camera_obs[depth_key][0].detach().to("cpu").to(torch.float32).numpy()
        depth_np = np.ascontiguousarray(np.squeeze(depth))

    return rgb_np, depth_np


def main():
    """Re-render the selected episodes at the requested camera pose."""
    assert os.path.exists(args_cli.dataset_file), f"The dataset file {args_cli.dataset_file} does not exist."

    out_dir = args_cli.out_dir
    video_dir = os.path.join(out_dir, "videos", "observation.images.ego_view")
    depth_dir = os.path.join(out_dir, "depth")
    os.makedirs(video_dir, exist_ok=True)
    if not args_cli.no_depth:
        os.makedirs(depth_dir, exist_ok=True)

    arena_builder = get_arena_builder_from_cli(args_cli)
    camera_metadata = configure_camera(
        arena_builder.arena_env.embodiment,
        args_cli.camera_name,
        want_depth=not args_cli.no_depth,
        far_clip_m=args_cli.camera_far_clip_m,
        pitch_deg=args_cli.camera_pitch_deg,
        height_m=args_cli.camera_height_offset_m,
    )
    print(f"[Rerender] Camera configuration: {json.dumps(camera_metadata)}")

    env_name, env_cfg, env_kwargs = arena_builder.build_registered()
    # Playback drives the state directly, so recorders and terminations have nothing to contribute.
    env_cfg.recorders = {}
    env_cfg.terminations = {}

    env = gym.make(env_name, cfg=env_cfg, **env_kwargs)
    from isaaclab_arena.utils.isaaclab_utils.simulation_app import reapply_viewer_cfg

    reapply_viewer_cfg(env)
    env = env.unwrapped
    env.reset()

    rgb_key = f"{args_cli.camera_name}_rgb"
    depth_key = None if args_cli.no_depth else f"{args_cli.camera_name}_{DEPTH_DATA_TYPE}"
    env_ids = torch.tensor([0], device=env.device)
    pose_is_unperturbed = args_cli.camera_pitch_deg == 0.0 and args_cli.camera_height_offset_m == 0.0

    episode_reports = []
    with h5py.File(args_cli.dataset_file, "r") as dataset:
        demo_names = sorted(dataset["data"].keys(), key=lambda name: int(name.split("_")[-1]))
        selected = args_cli.select_episodes or list(range(len(demo_names)))

        with contextlib.suppress(KeyboardInterrupt), torch.inference_mode():
            for episode_index in selected:
                if episode_index >= len(demo_names):
                    print(f"[Rerender] Skipping episode {episode_index}: only {len(demo_names)} in the file.")
                    continue
                demo_name = demo_names[episode_index]
                demo_group = dataset["data"][demo_name]

                recorded_states = read_recorded_states(demo_group)
                undriven = assert_recording_covers_scene(env.scene.get_state(is_relative=True), recorded_states)
                if undriven and episode_index == selected[0]:
                    print(f"[Rerender] Scene assets not driven by the recording, left at their live pose: {undriven}")

                recorded_rgb = demo_group["camera_obs"].get("robot_head_cam_rgb")
                num_frames = int(demo_group.attrs["num_samples"])
                if args_cli.max_frames_per_episode:
                    num_frames = min(num_frames, args_cli.max_frames_per_episode)

                rgb_frames = []
                depth_frames = []
                fidelity_per_frame = []
                playback_errors = []
                for frame_index in range(num_frames):
                    frame_state = frame_state_for_scene(
                        env.scene.get_state(is_relative=True), recorded_states, frame_index, str(env.device)
                    )
                    env.scene.reset_to(frame_state, env_ids, is_relative=True)
                    rgb_np, depth_np = render_frame(env, args_cli.renders_per_frame, rgb_key, depth_key)
                    if args_cli.validate_states:
                        playback_errors.append(state_playback_error(env, frame_state))

                    rgb_frames.append(rgb_np)
                    if depth_np is not None:
                        stride = max(1, args_cli.depth_downsample)
                        depth_frames.append(depth_np[::stride, ::stride].astype(np.float16))
                    if recorded_rgb is not None and pose_is_unperturbed:
                        fidelity_per_frame.append(rgb_fidelity(rgb_np, np.asarray(recorded_rgb[frame_index])))

                video_path = os.path.join(video_dir, f"episode_{episode_index:06d}.mp4")
                torchvision.io.write_video(
                    video_path, torch.from_numpy(np.stack(rgb_frames)), args_cli.fps, video_codec="h264"
                )

                report = {"episode_index": episode_index, "demo": demo_name, "num_frames": num_frames}
                if depth_frames:
                    depth_stack = np.stack(depth_frames)
                    depth_path = os.path.join(depth_dir, f"episode_{episode_index:06d}.npz")
                    np.savez_compressed(depth_path, depth=depth_stack)
                    finite = np.isfinite(depth_stack)
                    report["depth_shape"] = list(depth_stack.shape)
                    report["depth_inf_fraction"] = float(1.0 - finite.mean())
                    report["depth_min_m"] = float(depth_stack[finite].min()) if finite.any() else None
                    report["depth_max_m"] = float(depth_stack[finite].max()) if finite.any() else None
                if playback_errors:
                    report["state_playback_max_abs_error"] = {
                        key: max(frame[key] for frame in playback_errors) for key in playback_errors[0]
                    }
                if fidelity_per_frame:
                    report["rgb_mean_abs_diff"] = float(np.mean([f["mean_abs_diff"] for f in fidelity_per_frame]))
                    finite_psnr = [f["psnr_db"] for f in fidelity_per_frame if math.isfinite(f["psnr_db"])]
                    report["rgb_psnr_db"] = float(np.mean(finite_psnr)) if finite_psnr else float("inf")
                episode_reports.append(report)
                print(f"[Rerender] {demo_name}: {json.dumps(report)}")

    summary = {
        "dataset_file": args_cli.dataset_file,
        "environment": env_name,
        "renders_per_frame": args_cli.renders_per_frame,
        "fps": args_cli.fps,
        "depth_downsample": args_cli.depth_downsample,
        "camera": camera_metadata,
        "episodes": episode_reports,
    }
    diffs = [r["rgb_mean_abs_diff"] for r in episode_reports if "rgb_mean_abs_diff" in r]
    if diffs:
        summary["rgb_fidelity"] = {
            "episodes_compared": len(diffs),
            "mean_abs_diff": float(np.mean(diffs)),
            "worst_episode_mean_abs_diff": float(np.max(diffs)),
        }
        print(f"[Rerender] RGB fidelity vs recording: {json.dumps(summary['rgb_fidelity'])}")
    else:
        summary["rgb_fidelity"] = None
        print("[Rerender] RGB fidelity not computed: camera pose is perturbed or the recording has no RGB.")

    with open(os.path.join(out_dir, "rerender_summary.json"), "w") as handle:
        json.dump(summary, handle, indent=2)
    print(f"[Rerender] Wrote {len(episode_reports)} episodes to {out_dir}")
    env.close()


if __name__ == "__main__":
    main()
    simulation_app.close()
