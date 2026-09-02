# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tool to render camera viewpoints from any IsaacLab-Arena environment specification."""

import argparse
from pathlib import Path
from PIL import Image
import torch

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="Render camera viewpoints from an environment spec YAML.")
parser.add_argument(
    "--env_graph_spec_yaml",
    type=Path,
    required=True,
    help="Path to the environment graph specification YAML file.",
)
parser.add_argument(
    "--camera_name",
    type=str,
    default="robot_head_cam_rgb",
    help="Name of the camera to render (e.g. 'robot_head_cam_rgb', 'all').",
)
parser.add_argument(
    "--out_path",
    type=Path,
    default=Path("eval_output/camera_renders/robot_view.png"),
    help="Output file path or directory for rendered PNG image(s).",
)
parser.add_argument(
    "--settle_steps",
    type=int,
    default=10,
    help="Number of physics simulation steps to allow objects to settle before capture.",
)

AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

args_cli.headless = True
args_cli.enable_cameras = True

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environment_spec.arena_env_graph_conversion_utils import build_arena_env_from_graph_spec


def render_environment_cameras(
    spec_yaml_path: Path,
    camera_name: str,
    out_path: Path,
    settle_steps: int = 10,
) -> list[Path]:
    """Render camera views from a generated environment specification.

    Args:
        spec_yaml_path: Path to the environment spec YAML.
        camera_name: Name of the camera observation or 'all' to render all cameras.
        out_path: Output path or directory for saved images.
        settle_steps: Number of simulation steps to run before capturing frames.

    Returns:
        List of paths to generated image files.
    """
    assert spec_yaml_path.exists(), f"Environment spec not found: {spec_yaml_path}"

    print(f"[RenderEnvCamera] Loading spec from: {spec_yaml_path}")
    spec = ArenaEnvGraphSpec.from_yaml(str(spec_yaml_path))

    arena_env = build_arena_env_from_graph_spec(spec, enable_cameras=True)
    builder = ArenaEnvBuilder(arena_env, cfg=ArenaEnvBuilderCfg(num_envs=1))
    env = builder.make_registered(render_mode="rgb_array")

    obs, _ = env.reset()

    # Step simulation to let physics and manipulands settle
    try:
        zero_action = torch.zeros(env.action_space.shape, device=env.unwrapped.device)
    except Exception:
        zero_action = torch.zeros((1, *env.action_space.shape), device=env.unwrapped.device)

    # For G1 WBC embodiments, channel -4 commands standing height (0.75m pelvis)
    # rather than interpreting 0.0 as squat-to-floor.
    if zero_action.shape[-1] in (23, 50):
        zero_action[..., -4] = 0.75

    for step_idx in range(settle_steps):
        try:
            obs, _, _, _, _ = env.step(zero_action)
        except Exception:
            # If 1D/2D mismatch, try alternate shape
            zero_action = zero_action.unsqueeze(0) if zero_action.ndim == 1 else zero_action.squeeze(0)
            obs, _, _, _, _ = env.step(zero_action)

    camera_obs = obs.get("camera_obs", {})
    if not camera_obs and hasattr(env.unwrapped, "observation_manager"):
        obs_dict = env.unwrapped.observation_manager.compute()
        camera_obs = obs_dict.get("camera_obs", {})

    if not camera_obs:
        print("[RenderEnvCamera] Warning: No 'camera_obs' group found in environment observations.")
        print(f"[RenderEnvCamera] Top-level observation keys: {list(obs.keys())}")
        env.close()
        return []

    available_cameras = list(camera_obs.keys())
    print(f"[RenderEnvCamera] Available cameras in observation: {available_cameras}")

    target_cameras = available_cameras if camera_name == "all" else [camera_name]

    saved_files = []
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for cam in target_cameras:
        if cam not in camera_obs:
            print(f"[RenderEnvCamera] Warning: Camera '{cam}' not found in observations. Skipping.")
            continue

        cam_tensor = camera_obs[cam]
        if hasattr(cam_tensor, "detach"):
            img_tensor = cam_tensor.detach().cpu()
        else:
            img_tensor = torch.as_tensor(cam_tensor)

        if img_tensor.ndim == 4:
            img_np = img_tensor[0].numpy()
        elif img_tensor.ndim == 3:
            img_np = img_tensor.numpy()
        else:
            img_np = img_tensor.squeeze().numpy()

        if img_np.ndim == 3 and img_np.shape[0] in (1, 3, 4) and img_np.shape[2] not in (1, 3, 4):
            img_np = img_np.transpose(1, 2, 0)

        if out_path.suffix.lower() == ".png" and len(target_cameras) == 1:
            save_file = out_path
        else:
            out_dir = out_path if out_path.is_dir() or not out_path.suffix else out_path.parent
            out_dir.mkdir(parents=True, exist_ok=True)
            save_file = out_dir / f"{cam}.png"

        img = Image.fromarray(img_np.astype("uint8"))
        img.save(save_file)
        print(f"[RenderEnvCamera] ✓ Saved camera view to: {save_file}")
        saved_files.append(save_file)

    env.close()
    return saved_files


def main():
    try:
        render_environment_cameras(
            spec_yaml_path=args_cli.env_graph_spec_yaml,
            camera_name=args_cli.camera_name,
            out_path=args_cli.out_path,
            settle_steps=args_cli.settle_steps,
        )
    except Exception as e:
        import traceback
        print(f"[RenderEnvCamera] Error during rendering: {e}")
        traceback.print_exc()
    finally:
        simulation_app.close()


if __name__ == "__main__":
    main()
