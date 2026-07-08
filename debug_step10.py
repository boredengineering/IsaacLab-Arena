import numpy as np
import glob
data = np.load(glob.glob('**/wbc_debug.npz', recursive=True)[0])
print("Step 10 wbc_action_q (first 10):", data['wbc_action_q'][10, 0, :10])
