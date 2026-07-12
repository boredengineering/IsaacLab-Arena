import numpy as np
import glob
data = np.load(glob.glob('**/wbc_debug.npz', recursive=True)[0])
print("Max step:", data['sim_joint_pos'].shape[0])
print("\n--- STEP 0: WBC ACTION Q (first 15) ---")
print(data['wbc_action_q'][0, 0, :15])
print("\n--- STEP 10: SIM POS (first 15) ---")
print(data['sim_joint_pos'][10, 0, :15])
print("\n--- STEP 50: SIM POS (first 15) ---")
print(data['sim_joint_pos'][50, 0, :15])
