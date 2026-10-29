# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Print world poses of every scene asset at reset and after zero-action steps (R-1/R-2 diagnostic, read-only).

Usage (inside the container): python probe_world_poses.py --env_graph_spec_yaml <spec.yaml> --headless --num_envs 1
"""

import torch

from isaaclab_arena.cli.isaaclab_arena_cli import get_isaaclab_arena_cli_parser
from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext

args_parser = get_isaaclab_arena_cli_parser()
args_cli, _ = args_parser.parse_known_args()

with SimulationAppContext(args_cli):
    import warp as wp

    from isaaclab_arena_environments.cli import get_arena_builder_from_cli, get_isaaclab_arena_environments_cli_parser

    args_parser = get_isaaclab_arena_environments_cli_parser(args_parser)
    args_cli, hydra_overrides = args_parser.parse_known_args()
    builder = get_arena_builder_from_cli(args_cli, hydra_overrides=hydra_overrides)
    env = builder.make_registered()
    env.reset()
    scene = env.unwrapped.scene

    def dump(tag):
        for name in list(scene.rigid_objects.keys()) + list(scene.articulations.keys()):
            data = scene[name].data
            pos = wp.to_torch(data.root_pos_w)[0, :3].tolist()
            quat = wp.to_torch(data.root_quat_w)[0].tolist()
            print(f"[POSE] {tag} {name}: pos={[round(v, 3) for v in pos]} quat_wxyz={[round(v, 3) for v in quat]}", flush=True)

    dump("t0")
    action = torch.zeros(env.action_space.shape, device=env.unwrapped.device)
    for _ in range(60):
        env.step(action)
    dump("t60")
    env.close()
