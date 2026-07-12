import os
log_path = "/workspaces/IsaacLab-Arena/isaaclab_arena_wbc_debug_log.txt"
if os.path.exists(log_path):
    with open(log_path, 'r') as f:
        print(f.read()[:2000])
