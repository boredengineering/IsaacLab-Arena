import numpy as np
import glob
data = np.load(glob.glob('**/wbc_debug.npz', recursive=True)[0])
wbc_action_q = data['wbc_action_q']
sim_joint_pos = data['sim_joint_pos']
for step in [10, 50, 100, 160]:
    if step < wbc_action_q.shape[0]:
        print(f"Step {step} - Target Left Knee: {wbc_action_q[step, 0, 3]:.3f}, Target Right Knee: {wbc_action_q[step, 0, 9]:.3f}")
        # Find knee joints in sim_joint_pos
        # To do this correctly, we need the indices from joint_names, but let's just print wbc_action_q for now.
