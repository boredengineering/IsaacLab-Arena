import numpy as np
import os

def analyze_npz(filepath, test_name):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
        
    try:
        data = np.load(filepath)
        sim_pos = data["sim_joint_pos"]
        # Shape is (steps, num_envs, num_joints)
        steps, envs, joints = sim_pos.shape
        
        # Check for NaNs
        nan_count = np.sum(np.isnan(sim_pos))
        
        # Calculate velocity proxy (diff)
        sim_vel = np.diff(sim_pos, axis=0)
        max_vel = np.max(np.abs(sim_vel[~np.isnan(sim_vel)])) if sim_vel.size > 0 else 0
        
        print(f"--- Analysis for {test_name} ---")
        print(f"Steps recorded: {steps}")
        print(f"NaNs detected: {nan_count}")
        print(f"Max delta per step (velocity proxy): {max_vel:.4f}")
        
        if nan_count > 0:
            print(">>> RESULT: Severe failure (OOD). Physics engine exploded.")
        elif max_vel > 1.0:
            print(">>> RESULT: Chaotic motion detected. High probability of collision or joint limit violation.")
        else:
            print(">>> RESULT: Smooth motion. No chaos detected.")
            
        print("\n")
    except Exception as e:
        print(f"Error reading {filepath}: {e}")

analyze_npz(".wbc_experiments/wbc_debug_01.npz", "Test 1 (Static Hands)")
analyze_npz(".wbc_experiments/wbc_debug_02.npz", "Test 3 (No Friction)")
