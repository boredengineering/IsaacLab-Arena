import json
import sys
import numpy as np
sys.path.append('/workspaces/IsaacLab-Arena/submodules/Isaac-GR00T')
from gr00t.data.state_action.state_action_processor import StateActionProcessor

config = json.load(open('/workspaces/IsaacLab-Arena/models/isaaclab_arena/GR00T-N1.6-G1-PnPAppleToPlate/checkpoint-20000/processor_config.json'))
kwargs = config['processor_kwargs']
import inspect
sig = inspect.signature(StateActionProcessor.__init__)
kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
statistics = json.load(open('/workspaces/IsaacLab-Arena/models/isaaclab_arena/GR00T-N1.6-G1-PnPAppleToPlate/checkpoint-20000/statistics.json'))
kwargs['statistics'] = statistics
processor = StateActionProcessor(**kwargs)
print('new_embodiment action left_arm min shape:', processor.norm_params['new_embodiment']['action']['left_arm']['min'].shape)
