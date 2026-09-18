# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Capture a supplied task's trajectory and retain an evidence-bound visual assessment."""

import argparse
import hashlib
import json
import traceback
import uuid
from pathlib import Path


def build_parser(app_launcher=None):
    """Return the CLI parser, optionally registering simulator options before required inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    if app_launcher is not None:
        # AppLauncher probes process argv while registering options. Required
        # trajectory inputs must not be present until that probe has finished.
        app_launcher.add_app_launcher_args(parser)
    parser.add_argument("--env_graph_spec_yaml", type=Path, required=True)
    parser.add_argument("--policy_config_yaml_path", type=Path, required=True)
    parser.add_argument(
        "--policy_type",
        default="isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy",
    )
    parser.add_argument("--remote_host", default="127.0.0.1")
    parser.add_argument("--remote_port", type=int, default=5557)
    parser.add_argument("--policy_device", help="Arena-side policy device; defaults to the simulator --device.")
    parser.add_argument(
        "--out_dir", type=Path, help="New run directory; defaults to a unique trajectory_assessments directory."
    )
    parser.add_argument("--num_steps", type=int, default=120)
    parser.add_argument("--frame_interval", type=int, default=30)
    parser.add_argument("--camera_names", nargs="+", help="Camera observation keys; defaults to all available cameras.")
    parser.add_argument("--model", help="Assessment model; otherwise use configured inference defaults.")
    parser.add_argument("--base_url", help="Assessment provider endpoint; otherwise use configured defaults.")
    return parser


def run(args):
    """Capture and assess after SimulationApp initialization; return the retained result."""
    import torch

    from PIL import Image

    from isaaclab_arena.agentic_environment_generation.inference_backend import InferenceBackend
    from isaaclab_arena.agentic_environment_generation.trajectory_assessment import assess_trajectory
    from isaaclab_arena.agentic_environment_generation.trajectory_capture import capture_trajectory
    from isaaclab_arena.environment_spec.arena_env_graph_conversion_utils import build_arena_env_from_graph_spec
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
    from isaaclab_arena.evaluation.policy_runner import get_policy_cls
    from isaaclab_arena.evaluation.policy_runner_cli import build_policy_from_cli

    out_dir = (args.out_dir or Path("eval_output/trajectory_assessments") / uuid.uuid4().hex).resolve()
    out_dir.mkdir(parents=True, exist_ok=False)
    spec = ArenaEnvGraphSpec.from_yaml(str(args.env_graph_spec_yaml))
    spec.write_yaml(out_dir / "spec.yaml")
    policy_hash = hashlib.sha256(args.policy_config_yaml_path.read_bytes()).hexdigest()
    if args.policy_device is None:
        args.policy_device = args.device
    arena_env = build_arena_env_from_graph_spec(spec, enable_cameras=True)
    env = ArenaEnvBuilder(arena_env, cfg=ArenaEnvBuilderCfg(num_envs=1, device=args.device)).make_registered(
        render_mode="rgb_array"
    )

    def save_frame(tensor, path):
        Image.fromarray(tensor[0].detach().cpu().numpy()).save(path)

    policy = None
    try:
        policy = build_policy_from_cli(get_policy_cls(args.policy_type), args)
        policy_instruction = policy.set_task_description(env.unwrapped.get_language_instruction())
        with torch.inference_mode():
            capture = capture_trajectory(
                env,
                policy,
                out_dir=out_dir,
                num_steps=args.num_steps,
                frame_interval=args.frame_interval,
                camera_names=args.camera_names,
                save_frame=save_frame,
            )
        manifest = {
            "schema_version": 1,
            "spec_path": str(out_dir / "spec.yaml"),
            "policy_config_sha256": policy_hash,
            "policy_type": args.policy_type,
            "policy_instruction": policy_instruction,
            "requested_steps": args.num_steps,
            "executed_steps": capture["executed_steps"],
            "stop_reason": capture["stop_reason"],
            "terminal_image_unavailable": capture["terminal_image_unavailable"],
            "frames": {label: str(path) for label, path in capture["frames"].items()},
            "task_success": None,
        }
        (out_dir / "capture.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    finally:
        try:
            if policy is not None:
                policy.close()
        finally:
            env.close()

    backend = InferenceBackend(model=args.model, base_url=args.base_url) if capture["frames"] else None
    try:
        result = assess_trajectory(
            spec.to_dict(),
            capture["frames"],
            backend=backend,
            model=backend.model if backend else None,
            executed_steps=capture["executed_steps"],
            policy_instruction=policy_instruction,
            stop_reason=capture["stop_reason"],
            terminal_image_unavailable=capture["terminal_image_unavailable"],
            output_path=out_dir / "assessment.json",
        )
    finally:
        if backend is not None:
            backend.client.close()
    print(json.dumps({"assessment_path": str(out_dir / "assessment.json"), "status": result["assessment"]["status"]}))
    return result


def main(argv=None):
    """Launch explicitly and release SimulationApp after the assessment is retained."""
    from isaaclab.app import AppLauncher

    parser = build_parser(AppLauncher)
    args = parser.parse_args(argv)
    if args.num_steps <= 0 or args.frame_interval <= 0:
        parser.error("num_steps and frame_interval must be positive")
    args.headless, args.enable_cameras = True, True
    app = AppLauncher(args).app
    exit_code = 1
    try:
        result = run(args)
        exit_code = 0
        return result
    except BaseException:
        # Kit fast shutdown may terminate before Python displays an exception.
        traceback.print_exc()
        raise
    finally:
        app.close(exit_code=exit_code)


if __name__ == "__main__":
    main()
