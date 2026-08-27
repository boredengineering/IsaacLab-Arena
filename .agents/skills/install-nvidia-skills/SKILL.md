---
name: install-nvidia-skills
description: Prompts the user and installs official NVIDIA agent skills on-demand from https://github.com/nvidia/skills (e.g., cuDF, CUDA, NeMo, cuOpt, Omniverse, DeepStream).
---

# NVIDIA Agent Skills Installer

The official NVIDIA Agent Skills repository (`https://github.com/nvidia/skills`) contains 340+ specialized agent skills (such as `accelerated-computing-cudf`, `cupynumeric-guide`, `cudaq-guide`, `cuopt-overview`, `nemo-curator`, etc.).

Because downloading and cloning the entire catalog takes noticeable network bandwidth and time (~1-2 minutes), **always prompt the user before installing** or install only the specific requested skill.

## Interaction Rule for the Agent

When the user asks for NVIDIA accelerated computing features, cuDF/GPU DataFrames, or official NVIDIA workflows:
1. Check if the required skill is already present in `.agents/skills/<skill-name>/`.
2. If not installed, ask the user if they would like to:
   - **Fast Install**: Install only the specific needed skill (e.g. `accelerated-computing-cudf`, takes ~5 seconds).
   - **Full Install**: Install the complete NVIDIA Skills catalog (340+ skills, takes ~1-2 minutes).
   - **Skip**: Continue without downloading external skills.
3. Execute the installer script based on the user's choice.

## Usage

Run the bundled installer script:

```bash
# Quick install for a specific skill (e.g. cuDF / GPU DataFrames)
bash .agents/skills/install-nvidia-skills/scripts/install_nvidia_skills.sh --skill accelerated-computing-cudf

# List available skills from the upstream catalog
bash .agents/skills/install-nvidia-skills/scripts/install_nvidia_skills.sh --list

# Install all skills from the catalog (takes ~1-2 mins)
bash .agents/skills/install-nvidia-skills/scripts/install_nvidia_skills.sh --all
```
