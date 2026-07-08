import numpy as np
import glob
data = np.load(glob.glob('**/wbc_debug.npz', recursive=True)[0])
print("Step 10 wbc_obs_q (first 15):", data['wbc_obs_q'][10, 0, :15])
print("Step 10 sim_joint_pos (first 15):", data['sim_joint_pos'][10, 0, :15])
