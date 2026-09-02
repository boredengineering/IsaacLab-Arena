# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tool to render 3D perspective and side-profile views of a scene graph specification for workflow verification."""

import argparse
from pathlib import Path
from PIL import Image
import torch
import numpy as np

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="Render external 3D perspective & side views of environment.")
parser.add_argument(
    "--env_graph_spec_yaml",
    type=Path,
    required=True,
    help="Path to environment graph spec YAML.",
)
parser.add_argument(
    "--out_dir",
    type=Path,
    default=Path("/workspaces/isaaclab_arena/eval_output/g1_tabletop_apple_to_plate"),
    help="Output directory for perspective renders.",
)

AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

args_cli.headless = True
args_cli.enable_cameras = True

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

from isaaclab.sensors.camera.camera_cfg import CameraCfg
from isaaclab.utils import configclass
import isaaclab.sim as sim_utils
from isaaclab_arena.embodiments.g1.g1 import G1CameraCfg
from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environment_spec.arena_env_graph_conversion_utils import build_arena_env_from_graph_spec


@configclass
class PerspectiveG1CameraCfg(G1CameraCfg):
    """Rig adding an external 3/4 perspective camera and a side-profile camera."""

    perspective_cam: CameraCfg = CameraCfg(
        prim_path="{ENV_REGEX_NS}/Robot/pelvis/PerspectiveCam",
        update_period=0.0,
        height=720,
        width=960,
        data_types=["rgb"],
        spawn=sim_utils.PinholeCameraCfg(
            focal_length=15.0,
            horizontal_aperture=20.955,
            clipping_range=(0.1, 20.0),
        ),
        offset=CameraCfg.OffsetCfg(
            pos=(-0.75, -0.85, 0.65),
            rot=[0.7751169, -0.3210639, 0.2082415, -0.5027396],
            convention="ros",
        ),
    )

    side_cam: CameraCfg = CameraCfg(
        prim_path="{ENV_REGEX_NS}/Robot/pelvis/SideCam",
        update_period=0.0,
        height=720,
        width=960,
        data_types=["rgb"],
        spawn=sim_utils.PinholeCameraCfg(
            focal_length=15.0,
            horizontal_aperture=20.955,
            clipping_range=(0.1, 20.0),
        ),
        offset=CameraCfg.OffsetCfg(
            pos=(0.25, -1.35, 0.45),
            rot=[0.7733421, 0.0, 0.0, -0.6339889],
            convention="ros",
        ),
    )


def main():
    spec = ArenaEnvGraphSpec.from_yaml(str(args_cli.env_graph_spec_yaml))
    arena_env = build_arena_env_from_graph_spec(spec, enable_cameras=True)

    # Attach perspective camera rig to embodiment
    arena_env.embodiment.camera_config = PerspectiveG1CameraCfg()

    builder = ArenaEnvBuilder(arena_env, cfg=ArenaEnvBuilderCfg(num_envs=1))
    env = builder.make_registered()
    obs, _ = env.reset()

    # Step to settle
    zero_action = torch.zeros(1, 50, device=env.unwrapped.device)
    for _ in range(5):
        obs, _, _, _, _ = env.step(zero_action)

    out_dir = Path(args_cli.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for cam_key in ["perspective_cam_rgb", "side_cam_rgb", "robot_head_cam_rgb"]:
        if cam_key in obs["camera_obs"]:
            raw_img = obs["camera_obs"][cam_key][0].detach().cpu().numpy()
            if raw_img.ndim == 3 and raw_img.shape[2] == 4:
                raw_img = raw_img[:, :, :3]
            img_uint8 = raw_img.astype(np.uint8)
            filename = f"v6_{cam_key.replace('_rgb', '')}_view.png"
            out_file = out_dir / filename
            Image.fromarray(img_uint8).save(str(out_file))
            print(f"[PerspectiveView] ✓ Successfully written: {out_file}")

    # Kinematic reach calculation
    robot_pos = env.unwrapped.scene["robot"].data.root_pos_w[0].cpu().numpy()
    apple_pos = env.unwrapped.scene["red_apple"].data.root_pos_w[0].cpu().numpy()
    plate_pos = env.unwrapped.scene["clay_plate"].data.root_pos_w[0].cpu().numpy()

    # Left shoulder estimate (~0.18 Y, ~1.05 Z from base)
    left_shoulder = robot_pos.copy()
    left_shoulder[1] += 0.18
    left_shoulder[2] += 1.05

    d_apple = float(torch.linalg.norm(torch.tensor(apple_pos - left_shoulder)))
    d_plate = float(torch.linalg.norm(torch.tensor(plate_pos - left_shoulder)))

    print("\n--- Kinematic Reach Analysis ---")
    print(f"Robot base pose:       X={robot_pos[0]:.3f}, Y={robot_pos[1]:.3f}, Z={robot_pos[2]:.3f}")
    print(f"Left shoulder pose:   X={left_shoulder[0]:.3f}, Y={left_shoulder[1]:.3f}, Z={left_shoulder[2]:.3f}")
    print(f"Red apple center:     X={apple_pos[0]:.3f}, Y={apple_pos[1]:.3f}, Z={apple_pos[2]:.3f}")
    print(f"Clay plate center:    X={plate_pos[0]:.3f}, Y={plate_pos[1]:.3f}, Z={plate_pos[2]:.3f}")
    print(f"Distance (Shoulder -> Apple): {d_apple:.3f} m (Max reach: 0.65m)")
    print(f"Distance (Shoulder -> Plate): {d_plate:.3f} m (Max reach: 0.65m)")
    reachable = d_apple < 0.55 and d_plate < 0.60
    print(f"Within comfortable reach:     {reachable}")

    env.close()
    simulation_app.close()


if __name__ == "__main__":
    main()
