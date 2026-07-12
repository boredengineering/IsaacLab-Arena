import numpy as np
import sys
sys.path.append('/workspaces/IsaacLab-Arena')

from isaaclab_arena_g1.g1_whole_body_controller.wbc_policy.utils.g1 import instantiate_g1_robot_model
model = instantiate_g1_robot_model("lower_body")

print("Sim Joint Names (Isaac Lab order):")
# wait, model.joint_to_dof_index gives us the name -> sim_idx
sim_names = [""] * len(model.joint_to_dof_index)
for name, idx in model.joint_to_dof_index.items():
    sim_names[idx] = name

for i, name in enumerate(sim_names):
    print(f"Index {i:2}: {name}")
