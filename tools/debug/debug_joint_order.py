import numpy as np
import yaml
import sys
sys.path.append('/workspaces/IsaacLab-Arena')

# policy_joints_order (from 43dof_joint_space.yaml)
with open('/workspaces/IsaacLab-Arena/isaaclab_arena_gr00t/embodiments/g1/43dof_joint_space.yaml', 'r') as f:
    policy_joints = yaml.safe_load(f)['joints']

# wbc_joints_order (from loco_manip_g1_joints_order_43dof.yaml)
with open('/workspaces/IsaacLab-Arena/isaaclab_arena_g1/g1_env/config/loco_manip_g1_joints_order_43dof.yaml', 'r') as f:
    wbc_joints = yaml.safe_load(f)
    
print("--- JOINT MAPPING ANALYSIS ---")
print(f"Policy waist_yaw_joint idx: {policy_joints['waist_yaw_joint']}")
print(f"WBC waist_yaw_joint idx: {wbc_joints['waist_yaw_joint']}")
print(f"WBC upper_body indices:")

from isaaclab_arena_g1.g1_env.g1_supplemental_info import G1SupplementalInfo
info = G1SupplementalInfo()
upper_body = info.joint_groups["upper_body"]["joints"]
for j in upper_body:
    print(f"{j:30} Policy={policy_joints.get(j):2} WBC={wbc_joints.get(j):2}")
