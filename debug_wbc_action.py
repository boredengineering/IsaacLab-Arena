import numpy as np

npz = np.load('g1_brainco_extension/wbc_debug.npz')

wbc_action_q = npz['wbc_action_q']
sim_pos = npz['sim_joint_pos']

step = 0
print(f"wbc_action_q shape: {wbc_action_q.shape}")
print(f"sim_pos shape: {sim_pos.shape}")

print(f"\n--- WBC Action q (Step {step}) ---")
for i, v in enumerate(wbc_action_q[step, 0]):
    if abs(v) > 1e-4:
        print(f"Index {i:2}: {v:.6f}")
