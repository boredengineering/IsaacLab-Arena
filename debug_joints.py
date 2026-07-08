import numpy as np
import glob
data = np.load(glob.glob('**/wbc_debug.npz', recursive=True)[0])
sim_joint_pos = data['sim_joint_pos']
print("sim_joint_pos shape:", sim_joint_pos.shape)
