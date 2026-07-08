import numpy as np
import glob
files = glob.glob('**/wbc_debug.npz', recursive=True)
data = np.load(files[0])
print("Shape of policy_raw_actions:", data['policy_raw_actions'].shape)
print("Shape of wbc_action_q:", data['wbc_action_q'].shape)
print("Shape of sim_joint_pos:", data['sim_joint_pos'].shape)

policy_actions = data['policy_raw_actions'][:, 0, :]
print("\n--- STEP 0: LEFT ARM TARGETS (Policy Indices: 11, 15, 19, 21, 23, 25, 27) ---")
print(policy_actions[0, [11, 15, 19, 21, 23, 25, 27]])
print("\n--- STEP 0: HAND TARGETS (Policy Indices 29-42) ---")
print(policy_actions[0, 29:43])

print("\n--- STEP 0: WBC TARGET UPPER BODY ---")
print(data['wbc_target_upper_body_joints'][0, 0, :])

sim_pos = data['sim_joint_pos'][:, 0, :]
print("\n--- STEP 0: SIM POS ---")
print("Total sim joints:", sim_pos.shape[1])
