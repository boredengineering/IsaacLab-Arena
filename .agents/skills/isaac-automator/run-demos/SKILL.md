---
name: run-demos
description: Pre-configured robotics simulation and RL policy demo runner (quadruped locomotion, humanoid manipulation).
---

# Run Demos Skill

### Headless & Display Execution
```bash
# Headless run with camera recording
python isaaclab/source/standalone/workflows/rsl_rl/play.py --task Isaac-Velocity-Rough-Anymal-D-v0 --headless --video --enable_cameras

# Desktop session run
DISPLAY=:0 ./demo.sh quadruped-locomotion
```
