import yaml
import sys
sys.path.append('/workspaces/IsaacLab-Arena')

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

print(f"Total upper body joints: {len(upper_body)}")

indices_and_names = []
for j in upper_body:
    if j in wbc_joints:
        indices_and_names.append((wbc_joints[j], j))

# Sort by index
indices_and_names.sort()

print("Sorted upper body joints (this is the order in WBC Target Upper Body):")
for i, (idx, name) in enumerate(indices_and_names):
    print(f"Index {i}: {name} (wbc_idx={idx})")
