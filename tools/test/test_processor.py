import sys
sys.path.append("/workspaces/IsaacLab-Arena/submodules/Isaac-GR00T")
from transformers import AutoProcessor
processor = AutoProcessor.from_pretrained("/workspaces/IsaacLab-Arena/models/isaaclab_arena/GR00T-N1.6-G1-PnPAppleToPlate/checkpoint-20000")
params = processor.state_action_processor.norm_params["new_embodiment"]["action"]["left_arm"]
print("min shape:", params["min"].shape)
