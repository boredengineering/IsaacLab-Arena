import numpy as np
import yaml
import sys
sys.path.append('/workspaces/IsaacLab-Arena')

from isaaclab_arena_g1.g1_whole_body_controller.wbc_policy.utils.g1 import instantiate_g1_robot_model

model = instantiate_g1_robot_model("lower_body")
upper_body_indices = model.get_joint_group_indices("upper_body")

print("upper_body_indices:", upper_body_indices)

# mapping from wbc order to name
with open('/workspaces/IsaacLab-Arena/isaaclab_arena_g1/g1_env/config/loco_manip_g1_joints_order_43dof.yaml', 'r') as f:
    wbc_joints = yaml.safe_load(f)
idx_to_name = {v: k for k, v in wbc_joints.items()}

for i, idx in enumerate(upper_body_indices):
    print(f"Index {i} -> wbc idx {idx} -> {idx_to_name[idx]}")

