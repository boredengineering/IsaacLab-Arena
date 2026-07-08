import numpy as np

def analyze_timing(filepath):
    data = np.load(filepath)
    actions = data["policy_raw_actions"]
    sim_pos = data["sim_joint_pos"]
    
    # Calculate step-to-step deltas
    action_diff = np.diff(actions, axis=0)
    
    # Find the maximum action delta per step
    max_diffs_per_step = np.max(np.abs(action_diff), axis=(1, 2))
    
    # Print the first 10 deltas to see if it's just an initial jump
    print("First 10 step deltas:")
    for i in range(10):
        if i < len(max_diffs_per_step):
            print(f"Step {i}: {max_diffs_per_step[i]:.4f}")
            
    # Print max deltas over the whole trajectory
    import matplotlib.pyplot as plt
    print(f"Max delta in whole trajectory: {np.max(max_diffs_per_step):.4f}")
    
    # Find steps where delta > 0.1 (excluding step 0)
    if len(max_diffs_per_step) > 1:
        high_delta_steps = np.where(max_diffs_per_step[1:] > 0.1)[0] + 1
        if len(high_delta_steps) > 0:
            print(f"First high-delta step (excluding step 0): {high_delta_steps[0]}")
        else:
            print("No high delta steps after step 0!")

analyze_timing(".wbc_experiments/wbc_debug_03.npz")
