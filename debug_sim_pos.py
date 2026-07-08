import numpy as np

npz = np.load('g1_brainco_extension/wbc_debug.npz')

policy_raw = npz['policy_raw_actions']
wbc_target = npz['wbc_target_upper_body_joints']
sim_pos = npz['sim_joint_pos']
wbc_obs = npz['wbc_obs_q']

step = 0
print(f"--- Policy Raw Output (Step {step}) ---")
for i, v in enumerate(policy_raw[step, 0]):
    if abs(v) > 1e-4:
        print(f"Index {i:2}: {v:.6f}")
        
print(f"\n--- WBC Target Upper Body (Step {step}) ---")
for i, v in enumerate(wbc_target[step, 0]):
    if abs(v) > 1e-4:
        print(f"Index {i:2}: {v:.6f}")

print(f"\n--- WBC Obs q (Step {step}) ---")
for i, v in enumerate(wbc_obs[step, 0]):
    if abs(v) > 1e-4:
        print(f"Index {i:2}: {v:.6f}")

print(f"\n--- Sim Joint Pos (Step {step}) ---")
for i, v in enumerate(sim_pos[step, 0]):
    if abs(v) > 1e-4:
        print(f"Index {i:2}: {v:.6f}")
