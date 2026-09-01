# Environment: `droid_rubiks_cube_to_blue_bin` (Latest: `v9`)

> **Prompt / Task Description**:
> "Separate the objects across the workspace to avoid visual occlusion and collision during grasp: place the rubiks_cube in front_right (surface_sector: front_right) and keep the blue_bin in front_left (surface_sector: front_left). Keep maple_table at [-0.25, 0.0, 0.0] and droid_abs_joint_pos at [-0.55, 0.0, 0.0]."

---

## 1. Quick Info & Artifact Paths
- **Canonical Environment Name**: `droid_rubiks_cube_to_blue_bin`
- **Active Version Directory**: `generated_envs/droid_rubiks_cube_to_blue_bin/latest/` (symlinked to `v9`)
- **Environment Graph Spec**: `/workspaces/isaaclab_arena/generated_envs/droid_rubiks_cube_to_blue_bin/latest/droid_rubiks_cube_to_blue_bin.yaml`
- **Policy Configuration**: `/workspaces/isaaclab_arena/generated_envs/droid_rubiks_cube_to_blue_bin/latest/policy_config.yaml`
- **Evaluation Output Directory**: `/workspaces/isaaclab_arena/eval_output/droid_rubiks_cube_to_blue_bin`
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
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_rubiks_cube_to_blue_bin/latest/droid_rubiks_cube_to_blue_bin.yaml \
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
  --policy_config_yaml_path /workspaces/isaaclab_arena/generated_envs/droid_rubiks_cube_to_blue_bin/latest/policy_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5557 \
  --num_steps 2000 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_rubiks_cube_to_blue_bin/latest/droid_rubiks_cube_to_blue_bin.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_rubiks_cube_to_blue_bin
```

### C. Scaled Headless Benchmark (High-Throughput Parallel Flywheel)
Run tensorized parallel environments headlessly to measure empirical success and lift rates:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
  --policy_config_yaml_path /workspaces/isaaclab_arena/generated_envs/droid_rubiks_cube_to_blue_bin/latest/policy_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5557 \
  --num_envs 32 \
  --num_episodes 32 \
  --num_steps 2000 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_rubiks_cube_to_blue_bin/latest/droid_rubiks_cube_to_blue_bin.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_rubiks_cube_to_blue_bin
```

### D. Active Inference Auto-Healing
Automatically analyze failure telemetry from evaluation runs and synthesize the next remediated version `v(N+1)`:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode auto_heal \
  --env_name droid_rubiks_cube_to_blue_bin
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
  --base_spec /workspaces/isaaclab_arena/generated_envs/droid_rubiks_cube_to_blue_bin/latest/droid_rubiks_cube_to_blue_bin.yaml \
  --feedback "Move the destination receptacle 5cm to the left and change the table surface material."

# Re-generate from initial prompt:
docker exec -it \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --prompt "Separate the objects across the workspace to avoid visual occlusion and collision during grasp: place the rubiks_cube in front_right (surface_sector: front_right) and keep the blue_bin in front_left (surface_sector: front_left). Keep maple_table at [-0.25, 0.0, 0.0] and droid_abs_joint_pos at [-0.55, 0.0, 0.0]." \
  --env_name droid_rubiks_cube_to_blue_bin
```

---

## 4. Version History & Remediation Lineage
| Version | Created Date | Trigger | Remediation / Patch Notes | Benchmark Outcome |
| :--- | :--- | :--- | :--- | :--- |
| `v1` | 2026-08-31 | `initial_active_inference_generation` | Initial synthesis | 0.0% (1 eps) |
| `v2` | 2026-08-31 | `active_inference_auto_heal` | Restricted tabletop placement to robot-facing front sector (X in [-0.30, -0.10]) within camera FOV, Injected task description into policy YAML language_instruction parameter, Extended evaluation horizon to 2000 steps (40 seconds) | 0.0% (2 eps) |
| `v3` | 2026-08-31 | `active_inference_auto_heal` | Policy: {'num_steps': 2000} | *Pending evaluation* |
| `v4` | 2026-08-31 | `active_inference_auto_heal` | Policy: {'num_steps': 2000} | *Pending evaluation* |
| `v5` | 2026-08-31 | `active_inference_auto_heal` | Spatial: {'rubiks_cube': {'surface_sector': 'front_center', 'sector_bounds': [-0.3, -0.1, -0.15, 0.15]}, 'blue_bin': {'surface_sector': 'front_left', 'sector_bounds': [-0.3, -0.1, 0.15, 0.35]}}, Policy: {'num_steps': 2000} | 0.0% (2 eps) |
| `v6` | 2026-08-31 | `active_inference_auto_heal` | Spatial: {'maple_table': {'position_xyz': [-0.15, 0.0, 0.0]}, 'rubiks_cube': {'surface_sector': 'front_center', 'sector_bounds': [-0.3, -0.1, -0.15, 0.15]}, 'blue_bin': {'surface_sector': 'front_left', 'sector_bounds': [-0.3, -0.1, 0.15, 0.35]}}, Policy: {'num_steps': 2000} | *Pending evaluation* |
| `v7` | 2026-08-31 | `active_inference_refinement` | Initial synthesis | 0.0% (2 eps) |
| `v8` | 2026-08-31 | `active_inference_refinement` | Initial synthesis | 0.0% (2 eps) |
| `v9` | 2026-08-31 | `active_inference_refinement` | Initial synthesis | 66.7% (3 eps) |
