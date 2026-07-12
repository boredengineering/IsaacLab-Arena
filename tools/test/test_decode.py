import json
import sys
import numpy as np
sys.path.append('/workspaces/IsaacLab-Arena/submodules/Isaac-GR00T')
from gr00t.model.gr00t_n1d6.processing_gr00t_n1d6 import Gr00tN1d6Processor
from gr00t.data.embodiment_tags import EmbodimentTag

config = json.load(open('/workspaces/IsaacLab-Arena/models/isaaclab_arena/GR00T-N1.6-G1-PnPAppleToPlate/checkpoint-20000/processor_config.json'))
statistics = json.load(open('/workspaces/IsaacLab-Arena/models/isaaclab_arena/GR00T-N1.6-G1-PnPAppleToPlate/checkpoint-20000/statistics.json'))

kwargs = config['processor_kwargs']
kwargs['statistics'] = statistics
processor = Gr00tN1d6Processor(**kwargs)

normalized_action = np.zeros((1, 50, 7))

try:
    processor.decode_action(normalized_action, embodiment_tag=EmbodimentTag.NEW_EMBODIMENT)
    print("NEW_EMBODIMENT decode SUCCESS")
except Exception as e:
    import traceback
    print("Crash with NEW_EMBODIMENT:")
    traceback.print_exc()
