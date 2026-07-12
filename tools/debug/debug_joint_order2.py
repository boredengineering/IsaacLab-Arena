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

# we need get_joint_group_indices
from isaaclab_arena_g1.g1_whole_body_controller.wbc_policy.config.robot_model import RobotModel
from isaaclab_arena_g1.g1_whole_body_controller.wbc_policy.utils.g1 import instantiate_g1_robot_model

model = instantiate_g1_robot_model("lower_body")
upper_body_indices = model.get_joint_group_indices("upper_body")

print(f"Upper body indices length: {len(upper_body_indices)}")
# reverse wbc_joints
idx_to_name = {v: k for k, v in wbc_joints.items()}

for i, idx in enumerate(upper_body_indices):
    name = idx_to_name[idx]
    pol_idx = policy_joints.get(name, -1)
    print(f"WBC index {i} is {name} (wbc_idx={idx}, policy_idx={pol_idx})")
