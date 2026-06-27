#!/usr/bin/env python3
import os
import sys
import argparse

# Start AppLauncher first to initialize Omniverse/Isaac Sim
from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="Inspect robot link positions in simulation.")
AppLauncher.add_cli_args(parser)
args_cli = parser.parse_args()
args_cli.headless = True

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

# Deferred imports after AppLauncher is initialized
import torch
import numpy as np
import isaaclab.sim as sim_utils
from isaaclab.scene import InteractiveSceneCfg, InteractiveScene
from isaaclab_arena.assets.asset_registry import AssetRegistry
import g1_brainco_extension.embodiments.g1_brainco

def main():
    registry = AssetRegistry()
    embodiment_cls = registry.get_asset_by_name("g1_brainco_custom")
    
    # Setup simple interactive scene
    scene_cfg = InteractiveSceneCfg(num_envs=1, env_spacing=5.0)
    
    # Load custom G1 Brainco config
    embodiment = embodiment_cls()
    robot_cfg = embodiment.get_scene_cfg().robot
    robot_cfg.prim_path = "/World/Robot"
    
    # Spawn ground plane
    gp_cfg = sim_utils.GroundPlaneCfg()
    gp_cfg.func(prim_path="/World/defaultGroundPlane", cfg=gp_cfg)
    
    # Add robot to scene
    scene_cfg.robot = robot_cfg
    scene = InteractiveScene(scene_cfg)
    
    # Initialize and play simulation
    sim_utils.play()
    
    # Step simulation to settle articulation
    for _ in range(10):
        scene.write_data_to_sim()
        sim_utils.step()
        scene.update(dt=0.01)
    
    # Get robot data
    robot = scene["robot"]
    
    print("\n==================================================")
    print("Link Positions in Simulation:")
    print("==================================================")
    for i, name in enumerate(robot.data.body_names):
        pos = robot.data.body_pos_w[0, i].cpu().numpy()
        print(f"Link {i:02d} '{name}': pos = {pos}")
        
    try:
        torso_idx = robot.data.body_names.index("torso_link")
        head_idx = robot.data.body_names.index("head_link")
        
        torso_pos = robot.data.body_pos_w[0, torso_idx].cpu().numpy()
        head_pos = robot.data.body_pos_w[0, head_idx].cpu().numpy()
        
        diff = head_pos - torso_pos
        dist = np.linalg.norm(diff)
        print(f"\n==================================================")
        print(f"Head relative to Torso analysis:")
        print(f"==================================================")
        print(f"Torso position: {torso_pos}")
        print(f"Head position: {head_pos}")
        print(f"Translation diff (Head - Torso): {diff}")
        print(f"Distance: {dist:.4f} meters")
        
        # A standard G1 head should be positioned around ~0.35m higher than the torso
        if diff[2] < 0.1:
            print("\nWARNING: Head link height is very low relative to the torso!")
            print("The head might have collapsed, or head_fixed_joint is positioned incorrectly.")
        else:
            print("\nSUCCESS: Head link height looks reasonable (neck is upright).")
    except ValueError as e:
        print(f"Error finding torso_link or head_link in body names: {e}")
        
    simulation_app.close()

if __name__ == "__main__":
    main()
