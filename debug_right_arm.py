import numpy as np
import glob
data = np.load(glob.glob('**/wbc_debug.npz', recursive=True)[0])
print("Right Arm from policy:", data['policy_raw_actions'][0, 0, [12, 16, 20, 22, 24, 26, 28]])
print("Right Arm from WBC Q (indices 29..35):", data['wbc_action_q'][0, 0, 29:36])
