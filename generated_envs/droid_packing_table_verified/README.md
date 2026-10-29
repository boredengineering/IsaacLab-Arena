# Environment: `droid_packing_table_verified` (Latest: `v40`)

> **Prompt / Task Description**:
> "STEP-0 VLM VISUAL CRITIC (tier_2_local_vlm):
robot arm partially occludes the view of the banana
The robot arm is partially obscuring the view of the banana, making it difficult to grasp."

---

## 1. Quick Info & Artifact Paths
- **Canonical Environment Name**: `droid_packing_table_verified`
- **Active Version Directory**: `generated_envs/droid_packing_table_verified/latest/` (symlinked to `v40`)
- **Environment Graph Spec**: `/workspaces/isaaclab_arena/generated_envs/droid_packing_table_verified/latest/droid_packing_table_verified.yaml`
- **Policy Configuration**: `/workspaces/isaaclab_arena/generated_envs/droid_packing_table_verified/latest/policy_config.yaml`
- **Evaluation Output Directory**: `/workspaces/isaaclab_arena/eval_output/droid_packing_table_verified`
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
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_packing_table_verified/latest/droid_packing_table_verified.yaml \
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
  --policy_config_yaml_path /workspaces/isaaclab_arena/generated_envs/droid_packing_table_verified/latest/policy_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5557 \
  --num_steps 2000 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_packing_table_verified/latest/droid_packing_table_verified.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_packing_table_verified
```

### C. Scaled Headless Benchmark (High-Throughput Parallel Flywheel)
Run tensorized parallel environments headlessly to measure empirical success and lift rates:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
  --policy_config_yaml_path /workspaces/isaaclab_arena/generated_envs/droid_packing_table_verified/latest/policy_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5557 \
  --num_envs 32 \
  --num_episodes 32 \
  --num_steps 2000 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_packing_table_verified/latest/droid_packing_table_verified.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_packing_table_verified
```

### D. Active Inference Auto-Healing
Automatically analyze failure telemetry from evaluation runs and synthesize the next remediated version `v(N+1)`:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode auto_heal \
  --env_name droid_packing_table_verified
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
  --base_spec /workspaces/isaaclab_arena/generated_envs/droid_packing_table_verified/latest/droid_packing_table_verified.yaml \
  --feedback "Move the destination receptacle 5cm to the left and change the table surface material."

# Re-generate from initial prompt:
docker exec -it \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --prompt "STEP-0 VLM VISUAL CRITIC (tier_2_local_vlm):
robot arm partially occludes the view of the banana
The robot arm is partially obscuring the view of the banana, making it difficult to grasp." \
  --env_name droid_packing_table_verified
```

---

## 4. Version History & Remediation Lineage
| Version | Created Date | Trigger | Remediation / Patch Notes | Benchmark Outcome |
| :--- | :--- | :--- | :--- | :--- |
| `v1` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v2` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v3` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v4` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v5` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v6` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v7` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v8` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v9` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v10` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v11` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v12` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v13` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v14` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v15` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v16` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v17` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v18` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v19` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v20` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v21` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v22` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v23` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v24` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v25` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v26` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v27` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v28` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v29` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v30` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v31` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v32` | 2026-10-18 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v33` | 2026-10-18 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v34` | 2026-10-18 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v35` | 2026-10-18 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v36` | 2026-10-18 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v37` | 2026-10-18 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v38` | 2026-10-18 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v39` | 2026-10-18 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v40` | 2026-10-18 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
