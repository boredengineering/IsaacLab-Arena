import numpy as np

data = np.load('.wbc_experiments/wbc_debug_04.npz')
actions = data['policy_raw_actions'][0, 0] # shape: (50, 43)

print("Policy first target frame (frame 0):")
print(actions[0])
print("\nPolicy tenth target frame (frame 10):")
print(actions[10])
