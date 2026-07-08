import numpy as np
import glob
data = np.load(glob.glob('**/wbc_debug.npz', recursive=True)[0])
policy_raw_actions = data['policy_raw_actions']
print("policy_raw_actions shape:", policy_raw_actions.shape)
print("Step 10 actions last 7 elements:", policy_raw_actions[10, 0, -7:])
