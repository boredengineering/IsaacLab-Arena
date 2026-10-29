# Environment: `red_bowl_with_banana_on_maple_table` (Latest: `v6`)

> **Prompt / Task Description**:
> "PHYSX SETTLE FAILURES:
Object 'red_bowl' unstable during 30-step PhysX settle: displaced 0.010m from [0.461, -0.118, 0.04] to [0.461, -0.118, 0.03].
Object 'banana' unstable during 30-step PhysX settle: displaced 0.010m from [0.581, 0.156, 0.031] to [0.581, 0.156, 0.021].

STEP-0 VLM VISUAL CRITIC (tier_2_local_vlm):
robot arm obstructs view of banana
banana is not in the correct position to be picked up
The robot arm is obstructing the view of the banana, making it difficult to pick up."

---

## 1. Quick Info & Artifact Paths
- **Canonical Environment Name**: `red_bowl_with_banana_on_maple_table`
- **Active Version Directory**: `generated_envs/red_bowl_with_banana_on_maple_table/latest/` (symlinked to `v6`)
- **Environment Graph Spec**: `/workspaces/isaaclab_arena/generated_envs/red_bowl_with_banana_on_maple_table/latest/red_bowl_with_banana_on_maple_table.yaml`
- **Policy Configuration**: `/workspaces/isaaclab_arena/generated_envs/red_bowl_with_banana_on_maple_table/latest/policy_config.yaml`
- **Evaluation Output Directory**: `/workspaces/isaaclab_arena/eval_output/red_bowl_with_banana_on_maple_table`
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
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/red_bowl_with_banana_on_maple_table/latest/red_bowl_with_banana_on_maple_table.yaml \
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
  --policy_config_yaml_path /workspaces/isaaclab_arena/generated_envs/red_bowl_with_banana_on_maple_table/latest/policy_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5557 \
  --num_steps 2000 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/red_bowl_with_banana_on_maple_table/latest/red_bowl_with_banana_on_maple_table.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/red_bowl_with_banana_on_maple_table
```

### C. Scaled Headless Benchmark (High-Throughput Parallel Flywheel)
Run tensorized parallel environments headlessly to measure empirical success and lift rates:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
  --policy_config_yaml_path /workspaces/isaaclab_arena/generated_envs/red_bowl_with_banana_on_maple_table/latest/policy_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5557 \
  --num_envs 32 \
  --num_episodes 32 \
  --num_steps 2000 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/red_bowl_with_banana_on_maple_table/latest/red_bowl_with_banana_on_maple_table.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/red_bowl_with_banana_on_maple_table
```

### D. Active Inference Auto-Healing
Automatically analyze failure telemetry from evaluation runs and synthesize the next remediated version `v(N+1)`:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode auto_heal \
  --env_name red_bowl_with_banana_on_maple_table
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
  --base_spec /workspaces/isaaclab_arena/generated_envs/red_bowl_with_banana_on_maple_table/latest/red_bowl_with_banana_on_maple_table.yaml \
  --feedback "Move the destination receptacle 5cm to the left and change the table surface material."

# Re-generate from initial prompt:
docker exec -it \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --prompt "PHYSX SETTLE FAILURES:
Object 'red_bowl' unstable during 30-step PhysX settle: displaced 0.010m from [0.461, -0.118, 0.04] to [0.461, -0.118, 0.03].
Object 'banana' unstable during 30-step PhysX settle: displaced 0.010m from [0.581, 0.156, 0.031] to [0.581, 0.156, 0.021].

STEP-0 VLM VISUAL CRITIC (tier_2_local_vlm):
robot arm obstructs view of banana
banana is not in the correct position to be picked up
The robot arm is obstructing the view of the banana, making it difficult to pick up." \
  --env_name red_bowl_with_banana_on_maple_table
```

---

## 4. Version History & Remediation Lineage
| Version | Created Date | Trigger | Remediation / Patch Notes | Benchmark Outcome |
| :--- | :--- | :--- | :--- | :--- |
| `v1` | 2026-10-16 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v2` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v3` | 2026-10-17 | `initial_generation` | Initial synthesis | *Pending evaluation* |
| `v4` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v5` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
| `v6` | 2026-10-17 | `grounded_resolve` | Initial synthesis | *Pending evaluation* |
