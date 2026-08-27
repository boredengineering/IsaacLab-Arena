#!/usr/bin/env bash
# ==============================================================================
# Physical AI & Robotics Agent Workspace Initializer
# Scaffolds the standard .agents/ topology, AGENTS.md, skills, memory, and docs.
# ==============================================================================

set -euo pipefail

TARGET_DIR="${1:-$PWD}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🤖 [Physical AI Agent Initializer] Initializing workspace topology at: ${TARGET_DIR}"

# 1. Ensure core directories
mkdir -p "${TARGET_DIR}/.agents/skills/isaac-automator/deploy-workstation"
mkdir -p "${TARGET_DIR}/.agents/skills/isaac-automator/connect-workstation"
mkdir -p "${TARGET_DIR}/.agents/skills/isaac-automator/manage-lifecycle"
mkdir -p "${TARGET_DIR}/.agents/skills/isaac-automator/run-demos"
mkdir -p "${TARGET_DIR}/.agents/skills/isaac-automator/transfer-data"
mkdir -p "${TARGET_DIR}/.agents/skills/isaac-automator/troubleshoot"
mkdir -p "${TARGET_DIR}/.agents/skills/isaac-automator/session-memory"
mkdir -p "${TARGET_DIR}/.agents/skills/isaac-installer/scripts"
mkdir -p "${TARGET_DIR}/.agents/skills/isaac-installer/references"
mkdir -p "${TARGET_DIR}/.agents/skills/isaac-installer/examples"
mkdir -p "${TARGET_DIR}/.agents/skills/install-nvidia-skills/scripts"
mkdir -p "${TARGET_DIR}/.agents/memory/sessions"
mkdir -p "${TARGET_DIR}/.agents/references/docs"
mkdir -p "${TARGET_DIR}/.agents/references/templates"

# 2. Master AGENTS.md
if [ ! -f "${TARGET_DIR}/AGENTS.md" ]; then
  cat <<'AGENTS_EOF' > "${TARGET_DIR}/AGENTS.md"
# Physical AI Agent Operating Instructions <!-- omit in toc -->

- [1. Decoupled Dual-Runtime Architecture Rule](#1-decoupled-dual-runtime-architecture-rule)
- [2. Port & IPC Safety Protocol](#2-port--ipc-safety-protocol)
- [3. Whole-Body Control (WBC) Concurrency Invariants](#3-whole-body-control-wbc-concurrency-invariants)
- [4. GPU Microarchitecture & Blackwell Execution](#4-gpu-microarchitecture--blackwell-execution)
- [5. Grounded Markdown Scene Specification Protocol](#5-grounded-markdown-scene-specification-protocol)
- [6. Session Memory Protocol](#6-session-memory-protocol)

---

### 1. Decoupled Dual-Runtime Architecture Rule
- **Simulation Engine**: Executes inside the Docker container (Python 3.12 / CUDA 12.8 / Omniverse Kit).
- **Foundation Policy Daemon**: Executes on the host in Python 3.10 via `uv` over ZeroMQ IPC.
- **NEVER** attempt to combine Isaac Sim and GR00T foundation training into a single monolithic Python environment.

### 2. Port & IPC Safety Protocol
- All GR00T ZeroMQ communication must strictly use port **`5556`** (preventing VS Code internal process collisions on port 5555).
- Always verify modality contracts: G1 humanoid models require `ego_view` and `NEW_EMBODIMENT`; DROID models require `OXE_DROID` and stereo camera views.

### 3. Whole-Body Control (WBC) Concurrency Invariants
- `g1_wbc_pink` uses a single-threaded CPU Pinocchio QP solver. **Strictly enforce `--num_envs 1`**.
- For parallel multi-environment rollouts ($N > 1$), strictly use `g1_wbc_joint`.

### 4. GPU Microarchitecture & Blackwell Execution
- Host Python 3.10 environments must pull PyTorch `cu128` wheels via `[tool.uv.index]` in `pyproject.toml` to ensure native `sm_120` execution on NVIDIA RTX PRO 6000 / RTX 50-series GPUs.

### 5. Grounded Markdown Scene Specification Protocol
- Never rely on raw zero-shot natural language prompts for metric scene composition.
- Always supply structured Markdown task specifications (`task_spec.md`) specifying `default_ground_plane`, metric heights ($z$), and kinematic reachability boundaries ($\mathcal{W}_{\text{reach}}$).

### 6. Session Memory Protocol
- Log all milestones, model iterations, and architectural discoveries in `.agents/memory/sessions/` using 25-character timestamped UUID files (`YYYYMMDD_HHMMSS_<short_uuid>.md`) and update `.agents/memory/INDEX.md`.
AGENTS_EOF
  echo "  ✓ Generated AGENTS.md"
fi

# 3. Session Memory Master Index
if [ ! -f "${TARGET_DIR}/.agents/memory/INDEX.md" ]; then
  cat <<'INDEX_EOF' > "${TARGET_DIR}/.agents/memory/INDEX.md"
# Architectural Session Memory Index

| Timestamp | Session ID | Topic / Milestone | Summary | Status |
| :--- | :--- | :--- | :--- | :--- |
| `2026-08-26` | `init_workspace` | Workspace Topology Scaffolding | Initialized standard Physical AI .agents hierarchy and devcontainer tooling. | Active |
INDEX_EOF
  touch "${TARGET_DIR}/.agents/memory/sessions/.gitkeep"
  echo "  ✓ Generated .agents/memory/INDEX.md"
fi

# 4. SKILL.md: isaac-automator / deploy-workstation
if [ ! -f "${TARGET_DIR}/.agents/skills/isaac-automator/deploy-workstation/SKILL.md" ]; then
  cat <<'EOF_SKILL' > "${TARGET_DIR}/.agents/skills/isaac-automator/deploy-workstation/SKILL.md"
---
name: deploy-workstation
description: Non-interactive multi-cloud GPU provisioning for NVIDIA Isaac Lab across AWS, GCP, Azure, and Alibaba Cloud.
---

# Deploy Workstation Skill

### Operational Invariants
1. Pass non-interactive flags: `--existing replace` or `--existing modify`. Never allow `ask` prompts in agent mode.
2. Ensure public IP lock: `--ingress-cidrs myip`.
3. Pre-baked images (`--from-image`) provision in 10–15m; bare-metal scripts (`--not-from-image`) take 45–60m.

```bash
# Example AWS deployment
./deploy --provider aws --deployment-name isaac-lab-gpu --gpu-type a10g --ingress-cidrs myip --from-image --existing replace
```
EOF_SKILL
  echo "  ✓ Generated skills/isaac-automator/deploy-workstation/SKILL.md"
fi

# 5. SKILL.md: isaac-automator / connect-workstation
if [ ! -f "${TARGET_DIR}/.agents/skills/isaac-automator/connect-workstation/SKILL.md" ]; then
  cat <<'EOF_SKILL' > "${TARGET_DIR}/.agents/skills/isaac-automator/connect-workstation/SKILL.md"
---
name: connect-workstation
description: Remote display streaming and headless shell connections (noVNC, NoMachine, NICE DCV, SSH).
---

# Connect Workstation Skill

### 3D Viewport Invariant
- **noVNC (`./novnc`)**: 2D web desktop only. Omniverse Kit renders to a Vulkan surface; blank viewports in noVNC are expected.
- **NoMachine / NICE DCV / Moonlight**: Dedicated hardware-accelerated 3D Vulkan streaming.
- **SSH (`./ssh`)**: Headless CLI control with GPU forwarding.

```bash
./connect --mode nomachine <deployment-name>
```
EOF_SKILL
  echo "  ✓ Generated skills/isaac-automator/connect-workstation/SKILL.md"
fi

# 6. SKILL.md: isaac-automator / manage-lifecycle
if [ ! -f "${TARGET_DIR}/.agents/skills/isaac-automator/manage-lifecycle/SKILL.md" ]; then
  cat <<'EOF_SKILL' > "${TARGET_DIR}/.agents/skills/isaac-automator/manage-lifecycle/SKILL.md"
---
name: manage-lifecycle
description: Cloud instance lifecycle and cost control (stop, start, destroy --yes, cycle-vm).
---

# Manage Lifecycle Skill

### Procedures
- `./stop <name>`: Pauses GPU compute charges, retains storage and static IP.
- `./start <name>`: Resumes instance with identical IP.
- `./destroy <name> --yes`: Complete teardown, stops 100% of billing.
- `./cycle-vm <name>`: Re-creates VM before GCP 7-day Flex-start expiry while preserving data.
EOF_SKILL
  echo "  ✓ Generated skills/isaac-automator/manage-lifecycle/SKILL.md"
fi

# 7. SKILL.md: isaac-automator / run-demos
if [ ! -f "${TARGET_DIR}/.agents/skills/isaac-automator/run-demos/SKILL.md" ]; then
  cat <<'EOF_SKILL' > "${TARGET_DIR}/.agents/skills/isaac-automator/run-demos/SKILL.md"
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
EOF_SKILL
  echo "  ✓ Generated skills/isaac-automator/run-demos/SKILL.md"
fi

# 8. SKILL.md: isaac-automator / transfer-data
if [ ! -f "${TARGET_DIR}/.agents/skills/isaac-automator/transfer-data/SKILL.md" ]; then
  cat <<'EOF_SKILL' > "${TARGET_DIR}/.agents/skills/isaac-automator/transfer-data/SKILL.md"
---
name: transfer-data
description: Bidirectional asset synchronization and automated boot execution (uploads/autorun.sh).
---

# Transfer Data Skill

```bash
./upload <name> ./assets/models/
./download <name> ~/results/ ./eval_results/
```
EOF_SKILL
  echo "  ✓ Generated skills/isaac-automator/transfer-data/SKILL.md"
fi

# 9. SKILL.md: isaac-automator / troubleshoot
if [ ! -f "${TARGET_DIR}/.agents/skills/isaac-automator/troubleshoot/SKILL.md" ]; then
  cat <<'EOF_SKILL' > "${TARGET_DIR}/.agents/skills/isaac-automator/troubleshoot/SKILL.md"
---
name: troubleshoot
description: Automated diagnostic engine for Vulkan display issues, driver mismatches, and CIDR drift.
---

# Troubleshoot Skill

1. **Security Group IP Drift**: Run `./repair-ip <name>` if local public IP changed.
2. **Vulkan ICD Diagnostics**: Verify `/usr/share/vulkan/icd.d/nvidia_icd.json` matches NVIDIA driver version.
EOF_SKILL
  echo "  ✓ Generated skills/isaac-automator/troubleshoot/SKILL.md"
fi

# 10. SKILL.md: isaac-automator / session-memory
if [ ! -f "${TARGET_DIR}/.agents/skills/isaac-automator/session-memory/SKILL.md" ]; then
  cat <<'EOF_SKILL' > "${TARGET_DIR}/.agents/skills/isaac-automator/session-memory/SKILL.md"
---
name: session-memory
description: Architectural checkpointing, 25-character UUID logging, and INDEX.md synchronization.
---

# Session Memory Skill

- Checkpoint format: `.agents/memory/sessions/YYYYMMDD_HHMMSS_<short_uuid>.md`
- Master table sync: append row to `.agents/memory/INDEX.md`
EOF_SKILL
  echo "  ✓ Generated skills/isaac-automator/session-memory/SKILL.md"
fi

# 11. isaac-installer suite
if [ ! -f "${TARGET_DIR}/.agents/skills/isaac-installer/SKILL.md" ]; then
  cat <<'EOF_SKILL' > "${TARGET_DIR}/.agents/skills/isaac-installer/SKILL.md"
---
name: isaac-installer
description: Bare-metal workstation provisioner, Blackwell sm_120 hardware auditor, and profile-based installer.
---

# Isaac Bare-Metal Installer Skill

Probes hardware compute capability, validates CUDA 12.8 / Driver 570+ compatibility, provisions Conda/uv environments, and tracks submodules with 0% Git dirt.
EOF_SKILL
  echo "  ✓ Generated skills/isaac-installer/SKILL.md"
fi

if [ ! -f "${TARGET_DIR}/.agents/skills/isaac-installer/scripts/check_hardware.py" ]; then
  cat <<'EOF_PY' > "${TARGET_DIR}/.agents/skills/isaac-installer/scripts/check_hardware.py"
#!/usr/bin/env python3
"""Hardware and GPU microarchitecture probe for Physical AI workloads."""
import json
import shutil
import subprocess
import sys

def probe():
    data = {"gpu_detected": False, "blackwell_sm120": False, "vulkan_ready": False}
    if shutil.which("nvidia-smi"):
        try:
            res = subprocess.check_output(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], text=True)
            data["gpu_detected"] = True
            data["gpu_info"] = [line.strip() for line in res.strip().split("\n") if line.strip()]
            if any("RTX 50" in g or "PRO 6000" in g or "B200" in g or "B100" in g for g in data["gpu_info"]):
                data["blackwell_sm120"] = True
        except Exception as e:
            data["error"] = str(e)
    if shutil.which("vulkaninfo"):
        data["vulkan_ready"] = True
    print(json.dumps(data, indent=2))

if __name__ == "__main__":
    probe()
EOF_PY
  chmod +x "${TARGET_DIR}/.agents/skills/isaac-installer/scripts/check_hardware.py"
  echo "  ✓ Generated skills/isaac-installer/scripts/check_hardware.py"
fi

# 12. install-nvidia-skills (On-demand official NVIDIA skills installer)
if [ ! -f "${TARGET_DIR}/.agents/skills/install-nvidia-skills/SKILL.md" ]; then
  cat <<'EOF_SKILL' > "${TARGET_DIR}/.agents/skills/install-nvidia-skills/SKILL.md"
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
EOF_SKILL
  echo "  ✓ Generated skills/install-nvidia-skills/SKILL.md"
fi

if [ ! -f "${TARGET_DIR}/.agents/skills/install-nvidia-skills/scripts/install_nvidia_skills.sh" ]; then
  cat <<'EOF_SH' > "${TARGET_DIR}/.agents/skills/install-nvidia-skills/scripts/install_nvidia_skills.sh"
#!/usr/bin/env bash
# ==============================================================================
# NVIDIA Agent Skills Installer (https://github.com/nvidia/skills)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Resolve the Git repository root (where .git and top-level .agents/ reside)
WORKSPACE_DIR="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${WORKSPACE_DIR}" ]; then
  curr="${SCRIPT_DIR}"
  while [ "${curr}" != "/" ]; do
    if [ -d "${curr}/.git" ] || [ -d "${curr}/.agents" ]; then
      WORKSPACE_DIR="${curr}"
      break
    fi
    curr="$(dirname "${curr}")"
  done
fi
WORKSPACE_DIR="${WORKSPACE_DIR:-${SCRIPT_DIR}/../../../..}"

show_help() {
  echo "NVIDIA Agent Skills Installer (https://github.com/nvidia/skills)"
  echo ""
  echo "Usage:"
  echo "  $0 --skill <name>   Install a specific NVIDIA skill (e.g. accelerated-computing-cudf)"
  echo "  $0 --all            Install the full NVIDIA skills catalog (340+ skills, ~1-2 min)"
  echo "  $0 --list           List all available skills from the upstream repository"
  echo "  $0 --help           Show this help message"
}

case "${1:-}" in
  --skill|-s)
    SKILL_NAME="${2:-}"
    if [ -z "$SKILL_NAME" ]; then
      echo "❌ Error: --skill requires a skill name."
      exit 1
    fi
    echo "📦 Installing NVIDIA skill '${SKILL_NAME}' into ${WORKSPACE_DIR}/.agents/skills/..."
    (cd "${WORKSPACE_DIR}" && npx -y skills add nvidia/skills --skill "${SKILL_NAME}" --copy -y)
    echo "✨ Skill '${SKILL_NAME}' installed successfully."
    ;;
  --all|-a)
    echo "📦 Installing full NVIDIA skills catalog (~340+ skills) into ${WORKSPACE_DIR}/.agents/skills/..."
    (cd "${WORKSPACE_DIR}" && npx -y skills add nvidia/skills --skill '*' --copy -y)
    echo "✨ All NVIDIA skills installed successfully."
    ;;
  --list|-l)
    echo "🔍 Fetching available skills from https://github.com/nvidia/skills..."
    npx -y skills add nvidia/skills --list
    ;;
  *)
    show_help
    ;;
esac
EOF_SH
  chmod +x "${TARGET_DIR}/.agents/skills/install-nvidia-skills/scripts/install_nvidia_skills.sh"
  echo "  ✓ Generated skills/install-nvidia-skills/scripts/install_nvidia_skills.sh"
fi

# 13. Reference Templates
if [ ! -f "${TARGET_DIR}/.agents/references/templates/task_spec.md" ]; then
  cat <<'EOF_SPEC' > "${TARGET_DIR}/.agents/references/templates/task_spec.md"
# Grounded Task Specification: Task Name

## 1. Scene Geometry & Metric Ground Planes
- **Ground Plane**: `default_ground_plane` ($z = 0.0\text{ m}$)
- **Workspace Bounds**: $x \in [-1.0, 1.0]$, $y \in [-1.0, 1.0]$, $z \in [0.0, 2.0]$
- **Table / Surface Height**: $z_{\text{table}} = 0.75\text{ m}$

## 2. Embodiment & Kinematic Reachability
- **Embodiment**: Unitree G1 / DROID Franka
- **Control Interface**: WBC Pink (`--num_envs 1`) / Joint WBC
- **Reachability Envelope ($\mathcal{W}_{\text{reach}}$)**: Max reach $0.65\text{ m}$ from base origin.

## 3. Sensor Modalities & Port Mapping
- **Camera Extrinsics**: `ego_view` RGB-D (1280x720, 30fps)
- **Policy Server Port**: ZeroMQ `tcp://127.0.0.1:5556`
EOF_SPEC
  echo "  ✓ Generated .agents/references/templates/task_spec.md"
fi

if [ ! -f "${TARGET_DIR}/.agents/references/templates/env_graph_spec.yaml" ]; then
  cat <<'EOF_YAML' > "${TARGET_DIR}/.agents/references/templates/env_graph_spec.yaml"
# Scene Graph Environmental Specification
scene:
  ground_plane:
    type: default_ground_plane
    z_height: 0.0
  tables:
    - name: worktable_01
      usd_path: "omniverse://isaac/Props/Tables/table_wood.usd"
      position: [0.5, 0.0, 0.0]
      orientation: [1.0, 0.0, 0.0, 0.0]

embodiment:
  robot_type: "unitree_g1"
  controller: "wbc_pink"
  num_envs: 1

inference:
  policy_daemon_url: "tcp://127.0.0.1:5556"
  camera_mode: "ego_view"
EOF_YAML
  echo "  ✓ Generated .agents/references/templates/env_graph_spec.yaml"
fi

# 14. Reference Docs
if [ -f "${SCRIPT_DIR}/../physical-ai_agents.md" ] && [ ! -f "${TARGET_DIR}/.agents/references/docs/physical-ai_agents.md" ]; then
  cp "${SCRIPT_DIR}/../physical-ai_agents.md" "${TARGET_DIR}/.agents/references/docs/physical-ai_agents.md"
  echo "  ✓ Copied physical-ai_agents.md to .agents/references/docs/"
elif [ -f "${TARGET_DIR}/useful_devcontainers/isaac-automator/physical-ai_agents.md" ] && [ ! -f "${TARGET_DIR}/.agents/references/docs/physical-ai_agents.md" ]; then
  cp "${TARGET_DIR}/useful_devcontainers/isaac-automator/physical-ai_agents.md" "${TARGET_DIR}/.agents/references/docs/physical-ai_agents.md"
  echo "  ✓ Copied physical-ai_agents.md to .agents/references/docs/"
fi

if [ ! -f "${TARGET_DIR}/.agents/references/docs/env_generation_notes.md" ]; then
  cat <<'EOF_DOC' > "${TARGET_DIR}/.agents/references/docs/env_generation_notes.md"
# Mathematical Scene Graphs & Grounded Markdown Generation

Describes the mathematical transformation pipeline from Natural Language $\to$ Grounded Markdown $\to$ Scene Knowledge Graph ($G = (V, E)$) $\to$ `ArenaEnvBuilder` PhysX scene.
EOF_DOC
  echo "  ✓ Generated .agents/references/docs/env_generation_notes.md"
fi

if [ ! -f "${TARGET_DIR}/.agents/references/docs/debugging_arena_gr00t.md" ]; then
  cat <<'EOF_DOC' > "${TARGET_DIR}/.agents/references/docs/debugging_arena_gr00t.md"
# Blackwell sm_120, PyTorch cu128, and ZeroMQ Contracts Runbook

Troubleshooting guide for CUTLASS CuTe DSL, SDPA fallback modes (`GR00T_DIT_SDPA_MODE=math`), and ZeroMQ port 5556 policy daemon rollouts.
EOF_DOC
  echo "  ✓ Generated .agents/references/docs/debugging_arena_gr00t.md"
fi

# 15. Agent MCP Servers Configuration (Antigravity, VS Code, Cursor, Claude Code)
mkdir -p /root/.gemini/config "${TARGET_DIR}/.vscode" "${TARGET_DIR}/.cursor"

# Master MCP configuration (ansible, gcp-cloud, playwright, terraform, filesystem)
cat <<'EOF_MCP' > /root/.gemini/config/mcp_config.json
{
  "mcpServers": {
    "ansible": {
      "command": "ansible-mcp-server",
      "args": []
    },
    "gcp-cloud": {
      "command": "gcloud-mcp",
      "args": []
    },
    "playwright": {
      "command": "playwright-mcp-server",
      "args": []
    },
    "terraform": {
      "command": "/usr/local/bin/terraform-mcp-server",
      "args": []
    },
    "filesystem": {
      "command": "mcp-server-filesystem",
      "args": [
        "/workspaces"
      ]
    }
  }
}
EOF_MCP
chmod 644 /root/.gemini/config/mcp_config.json

# VS Code & Cursor workspace MCP configuration
cp /root/.gemini/config/mcp_config.json "${TARGET_DIR}/.vscode/mcp.json"
cp /root/.gemini/config/mcp_config.json "${TARGET_DIR}/.cursor/mcp.json"

# Claude Code global MCP configuration
cp /root/.gemini/config/mcp_config.json /root/.claude.json
chmod 644 /root/.claude.json

echo "  ✓ Configured MCP servers for Antigravity, VS Code, Cursor, and Claude Code"

# 16. Verify Persistent Mounts & Dataset/Model Directories
echo "🔍 Verifying mounted storage volumes..."
for mnt in "/datasets" "/models" "/eval" "/root/.cache/huggingface"; do
  if [ -d "${mnt}" ]; then
    echo "  ✓ Mounted: ${mnt} ($(df -h "${mnt}" 2>/dev/null | awk 'NR==2 {print $4}') available)"
  else
    mkdir -p "${mnt}"
    echo "  ⚠️ Created fallback container directory: ${mnt}"
  fi
done

echo "✨ [Physical AI Agent Initializer] Workspace initialization complete!"


