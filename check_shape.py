import json
import sys
import os
import numpy as np

sys.path.append('/workspaces/IsaacLab-Arena/submodules/Isaac-GR00T')
from gr00t.data.state_action.state_action_processor import StateActionProcessor

config = json.load(open('/workspaces/isaaclab_arena/models/isaaclab_arena/GR00T-N1.6-G1-PnPAppleToPlate/checkpoint-20000/processor_config.json'))
processor = StateActionProcessor(**config['processor_kwargs'])
print('new_embodiment action left_arm min shape:', processor.norm_params['new_embodiment']['action']['left_arm']['min'].shape)
