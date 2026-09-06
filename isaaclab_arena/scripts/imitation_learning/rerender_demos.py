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
    "--guard_channel",
    type=str,
    default="auto",
    choices=["auto", "rgb", "depth"],
    help=(
        "Which channel the frozen-render guard watches. 'auto' uses depth and disables the guard"
        " when depth is off, because RGB is not deterministic on this renderer (measured: 42/255"
        " max|diff| between two renders of one state) and would pass on noise. 'rgb' is a"
        " diagnostic only -- it cannot establish that the scene changed."
    ),
)
parser.add_argument(
    "--determinism_probe",
    action="store_true",
    help="Render the same state twice and report per-channel differences, then exit. Diagnostic only.",
)
parser.add_argument(
    "--playback_step",
    action="store_true",
    help=(
        "Advance physics one dt after writing each state, instead of only refreshing kinematics."
        " PhysX synchronizes state to USD while stepping, and the RTX renderer reads USD, so"
        " without a step the written state never reaches the renderer. Use with --no_fabric."
    ),
)
parser.add_argument(
    "--no_fabric",
    action="store_true",
    help=(
        "Disable Fabric so physics state stays synchronized to USD. Required for faithful playback:"
        " the RTX renderer reads the USD scene directly, while Fabric (on by default) bypasses USD,"
        " so written states reach physics but never reach the renderer."
    ),
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

from isaaclab_arena.utils.demo_playback import (
    assert_recording_covers_scene,
    frame_state_for_scene,
    read_recorded_states,
    state_playback_error,
)

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


def state_max_abs_delta(state_a, state_b) -> float:
    """Return the largest absolute difference between two nested scene-state dicts.

    Args:
        state_a: Scene state, as returned by ``InteractiveScene.get_state``.
        state_b: Scene state to compare against, with the same structure.

    Returns:
        The maximum absolute elementwise difference over every shared leaf tensor.
    """
    if isinstance(state_a, dict):
        shared = set(state_a) & set(state_b)
        return max((state_max_abs_delta(state_a[k], state_b[k]) for k in shared), default=0.0)
    return float(torch.as_tensor(state_a - state_b).abs().max().item())


def assert_render_not_frozen(prev_frame, frame, state_delta: float, frame_index: int) -> None:
    """Fail when the renderer emits a bit-identical frame for a state that actually moved.

    This is the guard for the failure mode where the written state round-trips through physics
    correctly -- so ``--validate_states`` reports zero error -- while RTX keeps drawing the
    transforms of the last real physics step. Validating physics cannot detect it; only comparing
    consecutive *rendered* frames against the state delta can.

    Bit-identity is a sufficient test only for a **deterministic** channel such as
    ``distance_to_image_plane``. RTX colour carries sampling noise, so consecutive RGB frames differ
    even when the scene is completely frozen -- measured at 0.42 grey levels per frame against a
    recording that moves 2.72. Pair this with :func:`assert_render_tracks_recording` whenever RGB is
    the witness, or a frozen render passes.

    Args:
        prev_frame: The previously rendered frame, or None on the first frame of an episode.
        frame: The frame just rendered.
        state_delta: Largest absolute change in the recorded state since the previous frame.
        frame_index: Index of the current frame, for the failure message.
    """
    if prev_frame is None or frame is None or state_delta <= 0.0:
        return
    assert not np.array_equal(prev_frame, frame), (
        f"Frame {frame_index} is bit-identical to frame {frame_index - 1} while the recorded state"
        f" moved by {state_delta:.6g}. The renderer is frozen: the state reaches physics but not"
        " RTX, so every frame draws the last real physics step. Do not trust this run's images or"
        " depth -- see the transform-push guards in render_frame."
    )


def measure_rgb_noise_floor(env, renders_per_frame: int, rgb_key: str, playback_step: bool) -> float:
    """Return the mean absolute RGB difference between two renders of one unchanged state.

    RTX colour is nondeterministic -- denoiser and accumulation make the same scene render
    differently -- so any freeze test on RGB has to clear this floor to mean anything. Measured at
    0.877 grey levels on this scene, which is above a naive 20%-of-recorded-motion threshold, so
    without it a completely frozen render passes.

    Args:
        env: The unwrapped environment.
        renders_per_frame: Number of RTX render calls per frame.
        rgb_key: Observation key for the RGB image.
        playback_step: Whether to step physics as part of the refresh.

    Returns:
        Mean absolute difference between two same-state renders, in grey levels.
    """
    first, _ = render_frame(env, renders_per_frame, rgb_key, None, playback_step)
    second, _ = render_frame(env, renders_per_frame, rgb_key, None, playback_step)
    return float(np.abs(first.astype(np.float64) - second.astype(np.float64)).mean())


def assert_render_tracks_recording(
    prev_rendered,
    rendered,
    prev_recorded,
    recorded,
    frame_index: int,
    min_motion_ratio: float = 0.0,
    noise_floor: float | None = None,
    noise_margin: float = 2.0,
) -> None:
    """Fail when the render barely moves between frames that the recording shows moving.

    The magnitude test that bit-identity cannot do. A frozen RTX colour buffer still yields
    non-identical frames, so the only way to catch a frozen render on the RGB witness is to compare
    how much it moved against how much the recording moved over the same frame pair.

    Args:
        prev_rendered: Previously rendered RGB frame, or None on an episode's first frame.
        rendered: RGB frame just rendered.
        prev_recorded: Recorded RGB frame for the previous index, or None when unavailable.
        recorded: Recorded RGB frame for this index, or None when unavailable.
        frame_index: Index of the current frame, for the failure message.
        min_motion_ratio: Optional extra floor as a share of the recording's motion. Defaults to
            0, since differing materials make magnitude matching unreliable; ``noise_floor`` is the
            real test.
        noise_floor: Same-state RGB noise from ``measure_rgb_noise_floor``, or None to skip the
            noise term -- which leaves the test unsound on a stochastic channel.
        noise_margin: Multiple of ``noise_floor`` the render's motion must also clear.
    """
    if any(x is None for x in (prev_rendered, rendered, prev_recorded, recorded)):
        return
    recorded_motion = float(np.abs(np.asarray(recorded, np.float32) - np.asarray(prev_recorded, np.float32)).mean())
    if recorded_motion <= 0.0:
        return
    rendered_motion = float(np.abs(np.asarray(rendered, np.float32) - np.asarray(prev_rendered, np.float32)).mean())
    # The sound invariant is "the render moves more than its own noise", not "the render moves as
    # much as the recording": fallback materials legitimately reduce apparent motion, so matching
    # the recording's magnitude is not required. When the recording itself moves no more than the
    # noise, the frame pair cannot discriminate and is skipped rather than failed.
    threshold = min_motion_ratio * recorded_motion
    if noise_floor is not None:
        if recorded_motion <= noise_margin * noise_floor:
            return
        threshold = max(threshold, noise_margin * noise_floor)
    assert rendered_motion >= threshold, (
        f"Frame {frame_index} moved {rendered_motion:.4g} against the recording's"
        f" {recorded_motion:.4g} ({rendered_motion / recorded_motion:.1%} of it), below the"
        f" required {threshold:.4g}"
        + (
            f" (max of {min_motion_ratio:.0%} of recorded motion and {noise_margin:g}x the measured"
            f" {noise_floor:.4g} same-state noise)"
            if noise_floor is not None
            else ""
        )
        + ". The render is not tracking the recorded state. Bit-identity does not catch this on RGB"
        " because RTX sampling noise keeps consecutive frames distinct."
    )


def render_frame(env, renders_per_frame: int, rgb_key: str, depth_key: str | None, playback_step: bool = False):
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
    # Getting the written state in front of the renderer is the whole difficulty here. Three layers
    # were ruled out by source audit and by measurement, in this order:
    #
    # 1. `render_context.update_transforms` cannot help: `IsaacRtxRenderer.update_transforms` is
    #    `pass` -- "No-op for Isaac RTX - uses USD scene directly" -- so every route into it is dead
    #    at the leaf, whatever the `lazy_sensor_update` gate or the step-count dedupe do.
    # 2. RTX reads the **USD** scene. `PhysXManager._load_fabric` sets `/physics/updateToUsd` to
    #    `not use_fabric`, so `--no_fabric` does re-enable physics-to-USD synchronization.
    # 3. But that synchronization is performed by PhysX *while stepping*. `sim.forward()` refreshes
    #    kinematics without stepping, so nothing is ever written to USD and the renderer keeps
    #    drawing the last stepped state -- which is why `--no_fabric` alone still renders frozen.
    #
    # Hence `--playback_step`: advance physics by a single `dt` after writing the state, so the
    # physics-to-USD sync actually runs. The cost is that the rendered pose is the written state
    # advanced by one `dt` rather than the written state exactly; `--validate_states` measures that
    # drift, and it must be reported rather than assumed negligible.
    if playback_step:
        env.sim.step(render=False)
    else:
        env.sim.forward()
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
    if args_cli.no_fabric:
        # Fabric reads physics buffers directly and skips USD synchronization; the RTX renderer
        # reads USD. With Fabric on, `reset_to` therefore updates physics and leaves the rendered
        # image on the last state USD actually saw. Playback cares about fidelity, not throughput.
        env_cfg.sim.use_fabric = False
        print("[Rerender] Fabric disabled: physics state will stay synchronized to USD for rendering.")

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
                if args_cli.determinism_probe:
                    # Render the SAME state twice with no state write in between. Any difference is
                    # renderer nondeterminism (denoiser/TAA/progressive accumulation), which would
                    # make that channel useless as a "did the scene change?" witness.
                    a_rgb, a_depth = render_frame(
                        env, args_cli.renders_per_frame, rgb_key, depth_key, args_cli.playback_step
                    )
                    b_rgb, b_depth = render_frame(
                        env, args_cli.renders_per_frame, rgb_key, depth_key, args_cli.playback_step
                    )
                    rgb_d = float(np.abs(a_rgb.astype(np.int32) - b_rgb.astype(np.int32)).max())
                    rgb_mean = float(np.abs(a_rgb.astype(np.float64) - b_rgb.astype(np.float64)).mean())
                    print(f"[Probe] same-state RGB max|diff| = {rgb_d}  (0 => deterministic)")
                    print(f"[Probe] same-state RGB MEAN|diff| = {rgb_mean:.4f}  <-- noise floor of rgb_fidelity")
                    print(f"[Probe] same-state RGB identical  = {np.array_equal(a_rgb, b_rgb)}")
                    if a_depth is not None:
                        dep_d = float(np.abs(a_depth - b_depth).max())
                        print(f"[Probe] same-state depth max|diff| = {dep_d}")
                        print(f"[Probe] same-state depth identical = {np.array_equal(a_depth, b_depth)}")
                    raise SystemExit(0)

                if args_cli.guard_channel == "auto" and depth_key is None:
                    print(
                        "[Rerender] NOTE: the bit-identity guard is off because depth is off; RGB"
                        " cannot substitute for it, since this renderer is nondeterministic in RGB"
                        " (measured same-state mean |diff| 0.877) and bit-identity would never fire."
                        " The motion guard still applies, so the run is not unverified -- provided"
                        " the camera pose is unperturbed and the recording has RGB to compare to."
                    )
                # Two extra renders per episode, so the RGB motion test has a floor to clear:
                # a fraction of the recording's motion is not enough on its own when same-state
                # noise can exceed it.
                rgb_noise_floor = measure_rgb_noise_floor(
                    env, args_cli.renders_per_frame, rgb_key, args_cli.playback_step
                )
                prev_state = None
                prev_guard_frame = None
                prev_rgb = None
                prev_recorded = None
                for frame_index in range(num_frames):
                    frame_state = frame_state_for_scene(
                        env.scene.get_state(is_relative=True), recorded_states, frame_index, str(env.device)
                    )
                    env.scene.reset_to(frame_state, env_ids, is_relative=True)
                    rgb_np, depth_np = render_frame(
                        env, args_cli.renders_per_frame, rgb_key, depth_key, args_cli.playback_step
                    )
                    if args_cli.validate_states:
                        playback_errors.append(state_playback_error(env.scene, frame_state))

                    # Bit-identity is only a valid freeze test on a *deterministic* channel.
                    # Measured here with `--determinism_probe`, rendering one state twice: depth is
                    # bit-exact (max |diff| 0.0) while RGB differs by up to 42-60/255, mean 0.877 --
                    # the RTX denoiser/TAA path is nondeterministic. Note that same-state RGB noise
                    # (0.877) is *larger* than the consecutive-frame RGB difference measured on the
                    # frozen run (0.4238), so RGB bit-identity can never fire and RGB "motion" at
                    # that scale is indistinguishable from noise. Hence: depth for bit-identity,
                    # and `assert_render_tracks_recording` below for the magnitude test that covers
                    # RGB.
                    if args_cli.guard_channel == "rgb":
                        guard_frame = rgb_np
                    elif args_cli.guard_channel == "depth":
                        assert depth_np is not None, "--guard_channel depth requires depth rendering."
                        guard_frame = depth_np
                    else:
                        guard_frame = depth_np
                    state_delta = 0.0 if prev_state is None else state_max_abs_delta(frame_state, prev_state)
                    assert_render_not_frozen(prev_guard_frame, guard_frame, state_delta, frame_index)
                    # Bit-identity alone passes a frozen RGB buffer, so also require the render to
                    # reproduce a share of the recording's own frame-to-frame motion.
                    this_recorded = np.asarray(recorded_rgb[frame_index]) if recorded_rgb is not None else None
                    if pose_is_unperturbed:
                        assert_render_tracks_recording(
                            prev_rgb,
                            rgb_np,
                            prev_recorded,
                            this_recorded,
                            frame_index,
                            noise_floor=rgb_noise_floor,
                        )
                    prev_state, prev_guard_frame = frame_state, guard_frame
                    prev_rgb, prev_recorded = rgb_np, this_recorded

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
