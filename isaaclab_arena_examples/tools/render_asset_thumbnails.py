# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""High-fidelity asset preview renderer using IsaacLab-Arena environment pipeline."""

import argparse
from pathlib import Path
from PIL import Image

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="Render registered asset thumbnails to PNG.")
parser.add_argument(
    "--assets",
    nargs="+",
    default=[
        "bin_a06_vomp_robolab",
        "bin_b03_vomp_robolab",
        "bin_b04_vomp_robolab",
        "container_f24_vomp_robolab",
        "purple_crate",
        "grey_bin_robolab",
        "storage_box_hot3d_robolab",
        "green_container",
        "red_container",
        "wooden_bowl_hot3d_robolab",
        "bowl_ycb_robolab",
        "blue_sorting_bin",
    ],
    help="Asset registry names to render.",
)
parser.add_argument(
    "--out_dir",
    type=Path,
    default=Path("/workspaces/isaaclab_arena/eval_output/asset_thumbnails"),
    help="Output directory for thumbnail PNGs.",
)
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

args_cli.headless = True
args_cli.enable_cameras = True

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
from isaaclab_arena.environment_spec.arena_env_graph_spec import (
    ArenaEnvGraphSpec,
    AssetSpec,
    SpatialRelationSpec,
    CompositeTaskSpec,
    TaskSpec,
)
from isaaclab_arena.environment_spec.arena_env_graph_conversion_utils import build_arena_env_from_graph_spec
from isaaclab_arena.assets.registries import AssetRegistry, ensure_assets_registered


def render_single_asset(asset_name: str, out_dir: Path):
    ensure_assets_registered()
    asset_registry = AssetRegistry()
    if not asset_registry.is_registered(asset_name):
        print(f"[Warning] Asset {asset_name} is not registered in AssetRegistry. Skipping.")
        return

    print(f"[Rendering] Asset: {asset_name}")

    spec = ArenaEnvGraphSpec(
        env_name=f"render_{asset_name}",
        embodiment=AssetSpec(id="droid_robot", registry_name="droid_abs_joint_pos"),
        background=AssetSpec(id="maple_table", registry_name="maple_table_robolab"),
        objects=[AssetSpec(id="target_asset", registry_name=asset_name)],
        relations=[
            SpatialRelationSpec(kind="is_anchor", subject="maple_table"),
            SpatialRelationSpec(
                kind="on", subject="target_asset", reference="maple_table", params={"surface_anchor": "table_top"}
            ),
        ],
        task=CompositeTaskSpec(
            description=f"Inspect {asset_name}",
            subtasks=[
                TaskSpec(
                    kind="PickAndPlaceTask",
                    params={
                        "pick_up_object": "target_asset",
                        "destination_location": "target_asset",
                        "background_scene": "maple_table",
                    },
                )
            ],
        ),
    )

    arena_env = build_arena_env_from_graph_spec(spec, enable_cameras=True)
    builder = ArenaEnvBuilder(arena_env, cfg=ArenaEnvBuilderCfg(num_envs=1))
    env = builder.make_registered()
    obs, _ = env.reset()

    if "camera_obs" in obs:
        cam_tensor = obs["camera_obs"]["external_camera_rgb"]
        arr = cam_tensor[0].cpu().numpy()
        out_file = out_dir / f"{asset_name}.png"
        Image.fromarray(arr.astype("uint8")).save(out_file)
        print(f"  ✓ Saved thumbnail: {out_file.name}")

    env.close()


def main():
    args_cli.out_dir.mkdir(parents=True, exist_ok=True)
    for asset_name in args_cli.assets:
        try:
            render_single_asset(asset_name, args_cli.out_dir)
        except Exception as e:
            print(f"  ✗ Failed to render {asset_name}: {e}")

    print("\n[Done] All asset thumbnails rendered successfully.")
    simulation_app.close()


if __name__ == "__main__":
    main()
