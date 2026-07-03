import json
import numpy as np

with open('/workspaces/IsaacLab-Arena/models/isaaclab_arena/GR00T-N1.6-G1-PnPAppleToPlate/checkpoint-20000/processor_config.json', 'r') as f:
    config = json.load(f)

modality = config['processor_kwargs']['modality_configs']['new_embodiment']
action_config = modality['action']
left_arm_config = action_config['left_arm']
print("left_arm keys:", left_arm_config.keys())
print("left_arm norm_params keys:", left_arm_config['norm_params'].keys())
print("left_arm norm_params min shape:", np.array(left_arm_config['norm_params']['min']).shape)
