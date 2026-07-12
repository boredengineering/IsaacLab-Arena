import numpy as np
import glob
data = np.load(glob.glob('**/wbc_debug.npz', recursive=True)[0])
print("Left Arm from policy:", data['policy_raw_actions'][0, 0, [11, 15, 19, 21, 23, 25, 27]])
print("Left Arm from WBC Q (indices 15..22):", data['wbc_action_q'][0, 0, 15:22])
