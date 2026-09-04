# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Measures where an embodiment's frames and a scene's support surface actually sit.

Every quantitative claim about the manipulation-height axis rests on two numbers nobody measured:
the standing pelvis height above the base frame, and the support height the training corpus fixed.
Both are currently hardcoded -- ``policy_capability_graph.FRAME_HEIGHT_ABOVE_BASE_M`` and
``spatial_geometric_oracle`` each carry an independent ``0.75`` -- and they are contradicted by the
reference environment's own constants. Taken at face value, the corpus scene would require the
robot to reach roughly 1.1 m from its shoulder against a stated 0.65 m limit, yet that environment
is documented at 100% success. So at least one of the pelvis height, the shoulder height, the reach
limit, or the frame convention is wrong.

This tool replaces those assumptions with measurements. It settles the robot into its standing
pose, then reports the world and env-local positions of every pelvis / shoulder / wrist / torso
body, the manipuland, and the offsets between them.

Run against the corpus scene and the scene under test so both are measured in one convention::

    python isaaclab_arena_examples/tools/measure_embodiment_frames.py --headless \\
        --example_environment galileo_g1_static_pick_and_place --embodiment g1_wbc_agile_joint

    python isaaclab_arena_examples/tools/measure_embodiment_frames.py --headless \\
        --env_graph_spec_yaml generated_envs/<env>/v9/<env>.yaml
"""

import argparse
import json
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="Measure embodiment frame heights and support offsets.")
parser.add_argument(
    "--env_graph_spec_yaml",
    type=Path,
    default=None,
    help="Graph spec YAML to measure. Mutually exclusive with --example_environment.",
)
parser.add_argument(
    "--example_environment",
    type=str,
    default=None,
    help="Registered environment name to measure, e.g. 'galileo_g1_static_pick_and_place'.",
)
parser.add_argument(
    "--embodiment",
    type=str,
    default="g1_wbc_agile_joint",
    help="Embodiment override for --example_environment. The 50-D joint backend by default.",
)
parser.add_argument(
    "--settle_steps",
    type=int,
    default=60,
    help="Standing-action steps before measuring, so the WBC has reached its steady pose.",
)
parser.add_argument(
    "--out_json",
    type=Path,
    default=None,
    help="Optional path to write the measurements to as JSON.",
)

AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import torch  # noqa: E402

import warp as wp  # noqa: E402

# Bodies whose positions define the frames that manipulation-height invariants are expressed in.
_FRAME_BODY_MARKERS = ("pelvis", "shoulder", "wrist", "torso", "waist", "elbow")


def _build_env():
    """Build either a graph-spec environment or a registered example environment."""
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg

    if args_cli.env_graph_spec_yaml is not None:
        from isaaclab_arena.environment_spec.arena_env_graph_conversion_utils import build_arena_env_from_graph_spec
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        spec_path = args_cli.env_graph_spec_yaml
        assert spec_path.exists(), f"spec not found: {spec_path}"
        print(f"[frames] loading graph spec: {spec_path}")
        arena_env = build_arena_env_from_graph_spec(ArenaEnvGraphSpec.from_yaml(str(spec_path)))
        label = str(spec_path)
    else:
        assert args_cli.example_environment, "provide --env_graph_spec_yaml or --example_environment"
        from isaaclab_arena.assets.registries import EnvironmentRegistry
        from isaaclab_arena_environments.cli import ensure_environments_registered

        ensure_environments_registered()
        factory_type = EnvironmentRegistry().get_component_by_name(args_cli.example_environment)
        factory = factory_type()
        cfg = factory_type._legacy_argparse_cfg_type()
        if hasattr(cfg, "embodiment") and args_cli.embodiment:
            cfg.embodiment = args_cli.embodiment
        print(f"[frames] building registered env '{args_cli.example_environment}' with embodiment '{cfg.embodiment}'")
        arena_env = factory.build(cfg)
        label = f"{args_cli.example_environment}[{args_cli.embodiment}]"

    builder = ArenaEnvBuilder(arena_env, cfg=ArenaEnvBuilderCfg(num_envs=1))
    return builder.make_registered(), label


def _standing_actions(env) -> torch.Tensor:
    """Zero actions with the hip-height channel set, so WBC holds a standing pose.

    Mirrors the locomanip and static G1 tests: a plain zero action is interpreted as "squat to the
    floor", which would put every measured frame at the wrong height.
    """
    actions = torch.zeros(
        (env.unwrapped.num_envs,) + env.unwrapped.single_action_space.shape,
        device=env.unwrapped.device,
    )
    if actions.shape[-1] >= 4:
        actions[:, -4] = 0.75
    return actions


def _world_extent(prim_path: str) -> list[float] | None:
    """Return the world-aligned bounding-box size of ``prim_path``, or None if unavailable."""
    try:
        import omni.usd
        from pxr import Usd, UsdGeom

        stage = omni.usd.get_context().get_stage()
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid():
            return None
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
        size = cache.ComputeWorldBound(prim).ComputeAlignedRange().GetSize()
        return [float(size[0]), float(size[1]), float(size[2])]
    except Exception as exc:  # noqa: BLE001 - geometry is a bonus; never fail the measurement for it
        print(f"[measure] could not compute extent for {prim_path}: {exc}")
        return None


def measure() -> dict:
    """Settle the scene, then report frame and support positions with derived offsets."""
    env, label = _build_env()
    env.reset()

    try:
        for _ in range(args_cli.settle_steps):
            with torch.inference_mode():
                env.step(_standing_actions(env))

        unwrapped = env.unwrapped
        origin = unwrapped.scene.env_origins[0]
        report: dict = {"scene": label, "settle_steps": args_cli.settle_steps, "bodies": {}, "objects": {}}

        robot = unwrapped.scene["robot"]
        body_names = list(robot.body_names)
        body_pos_w = wp.to_torch(robot.data.body_pos_w)[0].to(origin.device)
        report["all_body_names"] = body_names

        for index, name in enumerate(body_names):
            if not any(marker in name.lower() for marker in _FRAME_BODY_MARKERS):
                continue
            world = body_pos_w[index]
            report["bodies"][name] = {
                "world": [round(float(v), 5) for v in world.tolist()],
                "env_local": [round(float(v), 5) for v in (world - origin).tolist()],
            }

        root_pos_w = wp.to_torch(robot.data.root_pos_w)[0].to(origin.device)
        report["robot_root"] = {
            "world": [round(float(v), 5) for v in root_pos_w.tolist()],
            "env_local": [round(float(v), 5) for v in (root_pos_w - origin).tolist()],
        }

        # Every rigid object in the scene, so the support surface and manipuland are both captured.
        for name, obj in unwrapped.scene.rigid_objects.items():
            pos = wp.to_torch(obj.data.root_pos_w)[0].to(origin.device)
            entry = {
                "world": [round(float(v), 5) for v in pos.tolist()],
                "env_local": [round(float(v), 5) for v in (pos - origin).tolist()],
            }
            # Extents matter for success thresholds: "on the plate" is bounded by the plate's own
            # footprint, so that radius has to be measured rather than guessed.
            extent = _world_extent(f"/World/envs/env_0/{name}")
            if extent is not None:
                entry["extent_m"] = [round(v, 5) for v in extent]
                entry["footprint_radius_m"] = round(max(extent[0], extent[1]) / 2.0, 5)
            report["objects"][name] = entry

        # Derived offsets: the quantities the invariants are actually expressed in.
        def _first(marker: str) -> tuple[str, torch.Tensor] | None:
            for name, index in ((n, i) for i, n in enumerate(body_names)):
                if marker in name.lower():
                    return name, body_pos_w[index]
            return None

        pelvis = _first("pelvis")
        left_shoulder = next(
            ((n, body_pos_w[i]) for i, n in enumerate(body_names) if "shoulder" in n.lower() and "left" in n.lower()),
            None,
        )
        derived: dict = {}
        if pelvis is not None:
            derived["pelvis_height_above_root_m"] = round(float(pelvis[1][2] - root_pos_w[2]), 5)
        if left_shoulder is not None:
            derived["left_shoulder_height_above_root_m"] = round(float(left_shoulder[1][2] - root_pos_w[2]), 5)

        # Pick the lowest-Z small object as the likely manipuland; report all so it is checkable.
        for name, entry in report["objects"].items():
            obj_z = entry["world"][2]
            if pelvis is not None:
                derived[f"{name}_rel_pelvis_z_m"] = round(float(obj_z - float(pelvis[1][2])), 5)
            if left_shoulder is not None:
                shoulder_pos = left_shoulder[1]
                obj_world = torch.tensor(entry["world"], device=shoulder_pos.device)
                derived[f"{name}_shoulder_distance_m"] = round(
                    float(torch.linalg.vector_norm(obj_world - shoulder_pos)), 5
                )
        report["derived"] = derived
        return report
    finally:
        env.close()


def main() -> int:
    report = measure()

    print("\n" + "=" * 78)
    print(f" EMBODIMENT FRAME MEASUREMENT: {report['scene']}")
    print("=" * 78)
    print(f"robot root  world={report['robot_root']['world']}  env_local={report['robot_root']['env_local']}")
    for name, entry in sorted(report["bodies"].items()):
        print(f"  {name:34s} world={entry['world']}  env_local={entry['env_local']}")
    print("-" * 78)
    for name, entry in sorted(report["objects"].items()):
        print(f"  {name:34s} world={entry['world']}")
    print("-" * 78)
    for key, value in sorted(report["derived"].items()):
        print(f"  {key:44s} {value:+.5f}")
    print("=" * 78)
    print(
        "\nCompare 'pelvis_height_above_root_m' against FRAME_HEIGHT_ABOVE_BASE_M['pelvis'] (0.75)\n"
        "and '<manipuland>_rel_pelvis_z_m' against the corpus invariant (-0.8015). If the shoulder\n"
        "distance exceeds the arm's reach while the scene is known to succeed, the frame convention\n"
        "is wrong and the invariant needs re-parameterising, not just re-valuing."
    )

    if args_cli.out_json:
        args_cli.out_json.parent.mkdir(parents=True, exist_ok=True)
        args_cli.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n[frames] wrote {args_cli.out_json}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        simulation_app.close()
