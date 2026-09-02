# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tool to step a closed-loop policy, capture trajectory frames, and invoke VLM failure autopsy."""

import argparse
import json
import os
from pathlib import Path
from PIL import Image
import torch

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="Render policy trajectory and run VLM failure diagnostic.")
parser.add_argument(
    "--env_graph_spec_yaml",
    type=Path,
    required=True,
    help="Path to environment graph spec YAML.",
)
parser.add_argument(
    "--policy_config_yaml_path",
    type=Path,
    required=True,
    help="Path to policy config YAML.",
)
parser.add_argument(
    "--policy_type",
    type=str,
    default="isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy",
    help="Policy class import string.",
)
parser.add_argument(
    "--remote_host",
    type=str,
    default="127.0.0.1",
    help="Policy server host.",
)
parser.add_argument(
    "--remote_port",
    type=int,
    default=5557,
    help="Policy server port.",
)
parser.add_argument(
    "--out_dir",
    type=Path,
    default=Path("eval_output/g1_tabletop_apple_to_plate/trajectory_frames"),
    help="Output directory for frames.",
)
parser.add_argument(
    "--num_steps",
    type=int,
    default=120,
    help="Number of policy steps.",
)
parser.add_argument(
    "--frame_interval",
    type=int,
    default=30,
    help="Interval of steps between saved frames.",
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
from isaaclab_arena.evaluation.policy_runner import get_policy_cls
from isaaclab_arena.evaluation.policy_runner_cli import build_policy_from_cli
from isaaclab_arena.agentic_environment_generation.inference_backend import InferenceBackend
from isaaclab_arena.agentic_environment_generation.visual_critic import VisualSceneCritic


def main():
    out_dir = Path(args_cli.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    spec = ArenaEnvGraphSpec.from_yaml(str(args_cli.env_graph_spec_yaml))
    arena_env = build_arena_env_from_graph_spec(spec, enable_cameras=True)
    builder = ArenaEnvBuilder(arena_env, cfg=ArenaEnvBuilderCfg(num_envs=1))
    env = builder.make_registered(render_mode="rgb_array")

    policy_cls = get_policy_cls(args_cli.policy_type)
    policy = build_policy_from_cli(policy_cls, args_cli)

    obs, _ = env.reset()
    policy.reset()
    policy.set_task_description(env.unwrapped.get_language_instruction())

    captured_frames: dict[str, str] = {}

    print(f"[Trajectory] Starting rollout for {args_cli.num_steps} steps...")
    with torch.inference_mode():
        for step in range(args_cli.num_steps):
            # Capture frame
            if step % args_cli.frame_interval == 0 or step == args_cli.num_steps - 1:
                camera_obs = obs.get("camera_obs", {})
                if "robot_head_cam_rgb" in camera_obs:
                    cam_tensor = camera_obs["robot_head_cam_rgb"]
                    img_np = cam_tensor[0].detach().cpu().numpy()
                    frame_path = out_dir / f"step_{step:03d}.png"
                    Image.fromarray(img_np).save(frame_path)
                    captured_frames[f"step_{step:03d}"] = str(frame_path)
                    print(f"[Trajectory] Saved frame at step {step}: {frame_path}")

            actions = policy.get_action(env, obs)
            obs, _, terminated, truncated, _ = env.step(actions)
            if terminated.any() or truncated.any():
                print(f"[Trajectory] Terminated/truncated at step {step}")
                break

    env.close()

    # Run VLM Critic on captured trajectory
    print("\n--- Running VLM Failure Autopsy ---")
    backend = InferenceBackend(model="anthropic/claude-sonnet-4.5")
    critic = VisualSceneCritic(backend=backend)

    autopsy_prompt = (
        f"You are a robotic failure autopsy expert inspecting an IsaacLab rollout for task: '{spec.task.description}'.\n"
        f"The robot failed to pick and place the red apple onto the plate.\n"
        f"Review the sequential egocentric frames from the robot's head camera showing the progression from step 0 to step {args_cli.num_steps - 1}.\n"
        f"Notice the robot's hands entering from the bottom facing the table.\n"
        f"Evaluate:\n"
        f"1. Did the robot's arm reach toward the apple, or did it move elsewhere/freeze?\n"
        f"2. Did the hand reach the apple's location, or was the apple placed too far / out of reach?\n"
        f"3. Did the fingers contact or grasp the apple, or did slip / collision occur?\n"
        f"4. What exact physical or spatial correction is required to succeed?\n\n"
        f"Respond in strict JSON matching:\n"
        f"{{\n"
        f'  "conforms": false,\n'
        f'  "visibility_score": float,\n'
        f'  "occluded_objects": [str],\n'
        f'  "floating_objects": [str],\n'
        f'  "anomalies": [str],\n'
        f'  "actionable_feedback": str,\n'
        f'  "actionable_corrections": dict\n'
        f"}}"
    )

    resp_str = backend.multimodal_chat(autopsy_prompt, captured_frames)
    print("\n--- VLM Autopsy Output ---")
    print(resp_str)


if __name__ == "__main__":
    main()
