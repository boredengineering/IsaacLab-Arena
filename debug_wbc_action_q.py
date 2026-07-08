import numpy as np
import glob
data = np.load(glob.glob('**/wbc_debug.npz', recursive=True)[0])
wbc_action_q = data['wbc_action_q']
print("wbc_action_q shape:", wbc_action_q.shape)

# Let's see the hand joints in wbc_action_q
# Upper body joints are usually after the lower body joints
print("Some values from step 10:", wbc_action_q[10, 0, :])
