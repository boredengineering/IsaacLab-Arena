# End-to-End Environment Generation & Closed-Loop GR00T Policy Evaluation

This guide provides a comprehensive end-to-end workflow for:
1. **Generating Physical AI Simulation Environments** via Active Inference.
2. **Launching the NVIDIA Isaac-GR00T Policy Inference Server** (ZeroMQ RPC).
3. **Running Closed-Loop Policy Evaluation** in Isaac Sim across single and parallel GPU simulation instances.

---

## 🏗️ Architecture Overview

```mermaid
graph TD
    subgraph "Stage 1: Active Inference Generation"
        UserPrompt["User Prompt"] --> Agent["Active Inference Agent"]
        Agent --> SpecYAML["Generated Env Graph YAML<br/>(e.g., droid_rubiks_cube_to_blue_bin.yaml)"]
    end

    subgraph "Stage 2: Policy Server (GR00T)"
        HF["Hugging Face Checkpoint<br/>(nvidia/GR00T-N1.6-DROID or GN1x-G1)"] --> Server["Isaac-GR00T Policy Server<br/>(ZeroMQ RPC on port 5556)"]
    end

    subgraph "Stage 3: Closed-Loop Simulation Rollout"
        SpecYAML --> Runner["Policy Runner (Isaac Sim)"]
        Runner <-->|1. Stream RGB Cameras + Joint States| Server
        Server <-->|2. Return Action Chunks (32/50 steps)| Runner
        Runner --> PhysX["PhysX Dynamics Simulation"]
        PhysX --> Outputs["Eval Metrics + Videos (.mp4) + Trajectories"]
    end
```

---

## 📦 Prerequisites & Directory Structure

### 1. Host vs Container Directory Mapping

| Location | Path on Host | Path Inside Container |
| :--- | :--- | :--- |
| **Workspace Root** | `/workspaces/IsaacLab-Arena` | `/workspaces/isaaclab_arena` |
| **Datasets** | `$HOME/datasets/isaaclab_arena/` | `/datasets/isaaclab_arena/` |
| **Model Weights** | `$HOME/models/isaaclab_arena/` | `/models/isaaclab_arena/` |

### 2. Start the Isaac Lab Docker Container

```bash
# On the Host:
./docker/run_docker.sh
```

---

## 🚀 Step-by-Step Workflow

### Step 1: Generate & Validate Target Environment

Use the Active Inference agent to synthesize and ground your task scene:

```bash
docker exec -it \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --model "anthropic/claude-sonnet-4.5" \
  --prompt "Droid robot picking rubiks cube into blue vomp bin on maple table" \
  --out_dir /workspaces/isaaclab_arena/generated_envs/droid_rubiks_sector_verified
```

---

### Step 2: Download Pre-Trained Policy Weights

#### Option A: For DROID Tabletop Manipulation (Single Arm)
```bash
# On the Host:
export MODELS_DIR=$HOME/models/isaaclab_arena/droid_tutorial
mkdir -p "$MODELS_DIR"

hf download \
  nvidia/GR00T-N1.6-DROID \
  --local-dir "$MODELS_DIR/gr00t_droid"
```

#### Option B: For G1 Humanoid Locomanipulation (Whole-Body WBC)
```bash
# On the Host:
export MODELS_DIR=$HOME/models/isaaclab_arena/locomanipulation_tutorial
mkdir -p "$MODELS_DIR"

hf download \
  --revision gn1_6 \
  nvidia/GN1x-Tuned-Arena-G1-Loco-Manipulation \
  --local-dir "$MODELS_DIR/checkpoint-20000"
```

---

### Step 3: Launch the Isaac-GR00T Policy Inference Server

The policy server runs the diffusion/transformer action-chunking network and serves predictions over ZeroMQ (`tcp://127.0.0.1:5556`).

#### Option A: Using the Docker Helper Script (Recommended)
```bash
# On the Host:
./docker/run_gr00t_server.sh \
  -m "$MODELS_DIR/gr00t_droid" \
  -e OXE_DROID \
  -p 5556 \
  -d
```
*(Flags: `-d` runs detached in background, `-k` stops running server, `-r` forces image rebuild).*

#### Option B: Direct Python/UV Execution on Host
```bash
# On the Host:
cd submodules/Isaac-GR00T
uv run python gr00t/eval/run_gr00t_server.py \
  --modality-config-path ../../isaaclab_arena_gr00t/embodiments/g1/g1_sim_wbc_data_config.py \
  --model-path "$MODELS_DIR/checkpoint-20000" \
  --embodiment-tag NEW_EMBODIMENT \
  --device cuda --host 127.0.0.1 --port 5556
```

---

### Step 4: Run Closed-Loop Policy Evaluation

Run `policy_runner.py` inside the container to connect the Isaac Sim environment to the running GR00T server.

#### 1. Single Environment Evaluation (Interactive Kit 3D GUI)
```bash
# Allow Docker GUI display access on host:
xhost +local:root 2>/dev/null || xhost +local:docker 2>/dev/null

docker exec -it \
  -e DISPLAY="$DISPLAY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --viz kit \
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
  --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5556 \
  --num_steps 1500 \
  --num_envs 1 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_rubiks_sector_verified/droid_rubiks_cube_to_blue_bin.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_rubiks_gr00t_single
```

#### 2. Parallel Environments Evaluation (Batched Multi-Instance Rollout)
```bash
docker exec -it \
  -e DISPLAY="$DISPLAY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --viz kit \
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
  --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5556 \
  --num_steps 1200 \
  --num_envs 4 \
  --enable_cameras \
  --device cuda \
  --policy_device cuda \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_rubiks_sector_verified/droid_rubiks_cube_to_blue_bin.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_rubiks_gr00t_parallel
```

#### 3. Headless CI / Cluster Mode
```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --headless \
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
  --policy_config_yaml_path isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5556 \
  --num_steps 1200 \
  --num_envs 8 \
  --enable_cameras \
  --device cuda \
  --policy_device cuda \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_rubiks_sector_verified/droid_rubiks_cube_to_blue_bin.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_rubiks_gr00t_headless
```

---

## 📊 Evaluation Artifacts & Analysis

After evaluation finishes, the following artifacts are available under `--output_base_dir`:

1. **Multi-Camera Replay Videos (`videos/`)**:
   * Encoded `.mp4` recordings capturing wrist and overhead camera perspectives across all parallel envs.
2. **Evaluation Metrics (`summary_metrics.json`)**:
   * Success rate percentage ($0.0 - 1.0$), episode completion lengths, and grasp tracking data.
3. **Trajectory Datasets**:
   * Synchronized observations, joint states, actions, and contact events saved in LeRobot / HDF5 format.

---

## 🛠️ Common Gotchas & Troubleshooting

1. **ZeroMQ Connection Refused (`tcp://127.0.0.1:5556`)**:
   * Ensure the GR00T server has finished initializing and printed `[Server] Ready to accept requests on port 5556`.
   * Check container networking (`--network host` is used by `run_docker.sh`).
2. **Display / GUI Window Not Opening**:
   * Run `xhost +local:root` on the host before launching with `--viz kit`.
   * Ensure `-e DISPLAY="$DISPLAY"` is passed to `docker exec`.
3. **PyTorch SDPA FlashAttention Mismatch**:
   * If running on GPUs without native FlashAttention-2 support, pass `-s` (SDPA math fallback) to `run_gr00t_server.sh`.
