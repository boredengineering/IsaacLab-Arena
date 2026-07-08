import numpy as np
import glob
data = np.load(glob.glob('**/wbc_debug.npz', recursive=True)[0])
actions = data['policy_raw_actions']
print("Action shape:", actions.shape)
print("Nav cmd:", actions[0, 0, -7:-4])
print("Base height cmd:", actions[0, 0, -4:-3])
print("Torso RPY cmd:", actions[0, 0, -3:])
