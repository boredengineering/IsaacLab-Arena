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

from isaaclab_arena_g1.g1_env.g1_supplemental_info import G1SupplementalInfo
info = G1SupplementalInfo()
upper_body = []
for group_name in info.joint_groups["upper_body"]["groups"]:
    if "joints" in info.joint_groups[group_name]:
        upper_body.extend(info.joint_groups[group_name]["joints"])
    if "groups" in info.joint_groups[group_name]:
        for sub_group in info.joint_groups[group_name]["groups"]:
             upper_body.extend(info.joint_groups[sub_group]["joints"])

print(f"Upper body indices length: {len(upper_body)}")
for i, name in enumerate(upper_body):
    pol_idx = policy_joints.get(name, -1)
    print(f"WBC upper body index {i} is {name} (policy_idx={pol_idx})")

