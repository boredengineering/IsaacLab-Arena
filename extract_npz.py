import numpy as np
import glob
import os

files = glob.glob('**/wbc_debug.npz', recursive=True)
if not files:
    print('No npz file found.')
else:
    data = np.load(files[0])
    
    print('--- STEP 0 ---')
    print('Current Sim Joint Pos (first 10):', data['sim_joint_pos'][0, 0, :10])
    print('Model Raw Absolute Output (first 10):', data['policy_raw_actions'][0, 0, :10])
    print('WBC Target Upper Body (first 10):', data['wbc_target_upper_body_joints'][0, 0, :10])
