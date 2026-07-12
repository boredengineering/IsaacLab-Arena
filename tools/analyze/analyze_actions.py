import numpy as np

def analyze_actions(filepath):
    data = np.load(filepath)
    actions = data["policy_raw_actions"]
    
    # Calculate delta actions
    action_diff = np.diff(actions, axis=0)
    max_diff = np.max(np.abs(action_diff))
    
    # Calculate action magnitude
    max_action = np.max(np.abs(actions))
    
    print(f"Max action output: {max_action:.4f}")
    print(f"Max action step-to-step delta: {max_diff:.4f}")
    
analyze_actions(".wbc_experiments/wbc_debug_01.npz")
