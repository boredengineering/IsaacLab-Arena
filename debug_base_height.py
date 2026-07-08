import numpy as np
import glob
data = np.load(glob.glob('**/wbc_debug.npz', recursive=True)[0])
wbc_obs_q = data['wbc_obs_q']
# We didn't save floating_base_pose in wbc_debug.npz!
# wait, what did we save?
print(list(data.keys()))
