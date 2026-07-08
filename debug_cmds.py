import numpy as np
import glob
data = np.load(glob.glob('**/wbc_debug.npz', recursive=True)[0])
actions = data['policy_raw_actions']
print("Action shape:", actions.shape)
if actions.shape[-1] >= 52:
    print("Nav cmd:", actions[0, 0, 45:48])
    print("Base height cmd:", actions[0, 0, 48:49])
    print("Torso RPY cmd:", actions[0, 0, 49:52])
else:
    print("Action dimension is too small!")
