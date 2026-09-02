# Environment: `g1_tabletop_apple_to_plate` (Latest: `v4`)

> **Prompt / Task Description**:
> "Create an environment for a Unitree G1 humanoid robot on a maple table where the task is to reach with the right arm to grasp the red apple from the front right of the table and place it onto the clay plate on the front left. Position the maple table at [0.0, 0.0, 0.0] and use embodiment g1_wbc_agile_pink standing at [-0.45, 0.0, 0.0] facing the table, with head camera robot_head_cam_rgb."

---

## 1. Quick Info & Artifact Paths
- **Canonical Environment Name**: `g1_tabletop_apple_to_plate`
- **Active Version Directory**: `generated_envs/g1_tabletop_apple_to_plate/latest/` (symlinked to `v4`)
- **Environment Graph Spec**: `/workspaces/isaaclab_arena/generated_envs/g1_tabletop_apple_to_plate/latest/g1_tabletop_apple_to_plate.yaml`
- **Policy Configuration**: `/workspaces/isaaclab_arena/generated_envs/g1_tabletop_apple_to_plate/latest/policy_config.yaml`
- **Evaluation Output Directory**: `/workspaces/isaaclab_arena/eval_output/g1_tabletop_apple_to_plate`
- **Lineage Ledgers**: [`lineage.json`](./lineage.json) | [`lineage.ttl`](./lineage.ttl) (W3C PROV-O)

---

## 2. API Credentials Setup (LLM Generation & Refinement)
Before invoking the Active Bayesian environment generation agent or refinement tools, export the API key for your preferred LLM provider:

```bash
# Option A: Google Gemini
export GEMINI_API_KEY="your-gemini-api-key"

# Option B: OpenAI
export OPENAI_API_KEY="your-openai-api-key"

# Option C: NVIDIA NIM / NGC API
export NV_API_KEY="your-nv-api-key"

# Option D: OpenRouter (Claude Sonnet 4.5, Gemini 3.7, GPT-4o)
export OPENROUTER_API_KEY="your-openrouter-key"
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
```

---

## 3. Developer Quick-Run Commands

### A. Zero-Action Physics & Scene Verification
Verify object placement stability, kinematic reach, and contact settling in Omniverse Kit without running policy inference:

```bash
# Allow host X11 access (run once on host): xhost +local:docker
docker exec -it \
  -e DISPLAY="$DISPLAY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode build \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/g1_tabletop_apple_to_plate/latest/g1_tabletop_apple_to_plate.yaml \
  --num_steps 200 \
  --viz kit
```

### B. Interactive GR00T Policy Rollout (Live Viewport)
Watch the Franka Panda robot arm execute closed-loop pick-and-place trajectories in real time:

```bash
# Allow host X11 access (run once on host): xhost +local:docker
docker exec -it \
  -e DISPLAY="$DISPLAY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --viz kit \
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
  --policy_config_yaml_path /workspaces/isaaclab_arena/generated_envs/g1_tabletop_apple_to_plate/latest/policy_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5557 \
  --num_steps 2000 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/g1_tabletop_apple_to_plate/latest/g1_tabletop_apple_to_plate.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/g1_tabletop_apple_to_plate
```

### C. Scaled Headless Benchmark (High-Throughput Parallel Flywheel)
Run tensorized parallel environments headlessly to measure empirical success and lift rates:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
  --policy_config_yaml_path /workspaces/isaaclab_arena/generated_envs/g1_tabletop_apple_to_plate/latest/policy_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5557 \
  --num_envs 32 \
  --num_episodes 32 \
  --num_steps 2000 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/g1_tabletop_apple_to_plate/latest/g1_tabletop_apple_to_plate.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/g1_tabletop_apple_to_plate
```

### D. Active Inference Auto-Healing
Automatically analyze failure telemetry from evaluation runs and synthesize the next remediated version `v(N+1)`:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode auto_heal \
  --env_name g1_tabletop_apple_to_plate
```

### E. Conversational Refinement & Prompt Synthesis
Modify this environment with natural language feedback or generate a new sibling variant:

```bash
# Refine this environment based on feedback:
docker exec -it \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --base_spec /workspaces/isaaclab_arena/generated_envs/g1_tabletop_apple_to_plate/latest/g1_tabletop_apple_to_plate.yaml \
  --feedback "Move the destination receptacle 5cm to the left and change the table surface material."

# Re-generate from initial prompt:
docker exec -it \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --prompt "Create an environment for a Unitree G1 humanoid robot on a maple table where the task is to reach with the right arm to grasp the red apple from the front right of the table and place it onto the clay plate on the front left. Position the maple table at [0.0, 0.0, 0.0] and use embodiment g1_wbc_agile_pink standing at [-0.45, 0.0, 0.0] facing the table, with head camera robot_head_cam_rgb." \
  --env_name g1_tabletop_apple_to_plate
```

---

## 4. Version History & Remediation Lineage
| Version | Created Date | Trigger | Remediation / Patch Notes | Benchmark Outcome |
| :--- | :--- | :--- | :--- | :--- |
| `v1` | 2026-09-02 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v2` | 2026-09-02 | `embodiment_joint_space_alignment` | Embodiment: switch from g1_wbc_agile_pink (23-D PinkIK) to g1_wbc_agile_joint (50-D direct joint targets) for closed-loop GR00T foundation policy evaluation., Policy: action_chunk_length=16, action_horizon=32 | 0.0% (0 eps) |
| `v3` | 2026-09-02 | `vlm_critic_closed_loop_remediation` | Spatial: Rectified front_right and front_left table sector bounds to REP-103 robot coordinate frame (-Y right, +Y left) as diagnosed by VLM Critic., Embodiment: Maintained 50-D g1_wbc_agile_joint with action_horizon=40, action_chunk_length=20. | *Pending evaluation* |
| `v4` | 2026-09-02 | `vlm_critic_closed_loop_remediation` | Spatial: Rectified front_right and front_left table sector bounds to REP-103 robot coordinate frame (-Y right, +Y left) as diagnosed by VLM Critic., Embodiment: Maintained 50-D g1_wbc_agile_joint with action_horizon=40, action_chunk_length=20. | 0.0% (2 eps) |
