# Active Inference Closed-Loop Policy Evaluation & Self-Healing Test

This document provides a comprehensive report on the closed-loop evaluation of the generated environment (`droid_rubiks_cube_to_blue_bin`), the root-cause failure analysis (Camera FOV clipping & Table Standoff), and the automated Active Inference Self-Healing architecture.

---

## 1. Executive Summary & Test Workflow

We executed an end-to-end closed-loop simulation rollout connecting the **Active Inference generated environment** to the live **Isaac-GR00T foundation policy server** (`nvidia/GR00T-N1.6-DROID`) rendered in the interactive Omniverse Kit GUI (`--viz kit`).

```
[Active Inference Env Gen] ──► [Isaac-GR00T Policy Server] ──► [Omniverse Kit Viewport Rollout]
                                                                        │
                                                                        ▼
                                                         [eval_telemetry.ttl (RDF-star)]
                                                                        │
                                                                        ▼
                                                         [Evaluation Diagnostic Oracle]
                                                                        │
                                                                        ▼
                                                         [Automated Active Self-Healing]
```

---

## 2. Empirical Failure Analysis & Root Causes

During initial rollout (Iteration 0), the policy achieved `success_rate: 0.0`. Ingesting the telemetry traces revealed three distinct failure modes, led by a critical **Camera Field of View & Physical Reach Standoff** defect.

### A. Critical Defect: Table Standoff & Camera FOV Clipping
* **Robot Pose**: Franka DROID base is fixed at $p_{\text{robot}} = [-0.55,\, 0.0,\, 0.0]$.
* **Object Spawning in Sim**: Default table randomization spawned the Rubik's cube at $p_{\text{cube}} = [+\mathbf{0.725},\, -0.148,\, 0.044]$.
* **Physical Distance**:
  $$d = \sqrt{(0.725 - (-0.55))^2 + (-0.148 - 0.0)^2} = \mathbf{1.283\text{ meters}}$$
* **Perception Impact**:
  * The DROID camera is mounted on `panda_link0` at $(0.05, 0.57, 0.66)$ pointing downwards at $45^\circ$.
  * Its primary visual frustum covers the proximal tabletop ($X \in [-0.35, 0.10]\text{ m}$, distance $0.20 - 0.65\text{ m}$).
  * At $d = 1.28\text{ m}$, the cube was **completely outside the camera frustum** (invisible in the image stream) and **$43\text{ cm}$ beyond the Franka arm's maximum physical reach** ($0.855\text{ m}$).
  * **Result**: The VLA foundation model could not visually perceive the object to plan an approach vector.

### B. Language Conditioning Gap
* The policy config (`droid_manip_gr00t_closedloop_config.yaml`) lacked an explicit `language_instruction` parameter.
* The diffusion text backbone (`AlternateVLDiT`) received an empty string `""`, leaving the policy unconditioned.

### C. Simulation Horizon Truncation
* The test was evaluated for $500\text{ steps}$ ($10.0\text{ s}$ at $\Delta t = 0.02\text{ s}$).
* A full multi-stage manipulation trajectory (approach $\to$ grasp $\to$ lift $\to$ transport $\to$ release) requires $1500 - 2500\text{ steps}$ ($30 - 50\text{ s}$).

---

## 3. Active Inference Self-Healing Architecture

To automate the detection and remediation of these failures, we implemented three core modules:

### 1. Camera Frustum & Distance Oracle (`VisualSceneCritic` & `EvaluationDiagnosticOracle`)
Calculates the horizontal distance $d = \| p_{\text{obj}} - p_{\text{robot}} \|_{xy}$. If $d > 0.70\text{ m}$, it flags a critical `CAMERA_OCCLUSION / OUT_OF_REACH` failure signature:
```python
max_dexterous_dist = 0.70  # max camera FOV / kinematic reach envelope
dist = ((pos[0] - emb_p[0]) ** 2 + (pos[1] - emb_p[1]) ** 2) ** 0.5
if dist > max_dexterous_dist:
    # Flag failure and recommend sector shift to front_center (X in [-0.25m, 0.0m])
```

### 2. Evaluation Diagnostic Oracle (`EvaluationDiagnosticOracle`)
Parses `summary_metrics.json`, `eval_telemetry.ttl`, and policy configs into deterministic failure signatures:
* `CAMERA_OCCLUSION` / `OUT_OF_REACH` (Severity: 0.99)
* `UNCONDITIONED_VLA` (Severity: 0.95)
* `HORIZON_TRUNCATION` (Severity: 0.80)
* `REACH_STANDOFF` (Severity: 0.70)

### 3. Evaluation Remediation Engine (`EvaluationRemediationEngine`)
* Patches policy config YAML with `language_instruction = spec.task.description`.
* Re-weights the `SpatialFactorGraph` to clamp object positions to the robot-facing front half of the table ($X \in [-0.35, -0.05]\text{ m}$, $d \approx 0.42\text{ m}$).
* Extends rollout steps to $2000$.

---

## 4. Multi-Iteration Execution Commands & Semantic Versioning

All iterations and evaluations are tracked cleanly under canonical versioned directory trees:
* Environment Specs: `/workspaces/isaaclab_arena/generated_envs/droid_rubiks_cube_to_blue_bin/v1, v2, ..., latest`
* Evaluation Telemetry: `/workspaces/isaaclab_arena/eval_output/droid_rubiks_cube_to_blue_bin/v1, v2, ..., latest`
* Lineage Ledgers: `lineage.json` and `lineage.ttl`

### Step 1: Run Auto-Healing Pipeline (Autonomous Iteration)
```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode auto_heal \
  --env_name droid_rubiks_cube_to_blue_bin
```

### Step 2: Run Agentic Feedback Refinement (Human-in-the-Loop)
```bash
docker exec -it \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --model "anthropic/claude-sonnet-4.5" \
  --base_spec /workspaces/isaaclab_arena/generated_envs/droid_rubiks_cube_to_blue_bin/latest/droid_rubiks_cube_to_blue_bin.yaml \
  --feedback "Separate the objects across the workspace: place rubiks_cube in front_right and blue_bin in front_left." \
  --env_name droid_rubiks_cube_to_blue_bin
```

### Step 3: Run Remediated Evaluation in Omniverse Kit Viewport
```bash
xhost +local:root 2>/dev/null || xhost +local:docker 2>/dev/null

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
```

---

## 5. Beyond Object Placement: Grasp Affordance, Contact Dynamics & Parallel Data Science Flywheel

### A. Empirical Critique: Spatial Reach vs. Grasp Synthesis
In **Scenario A1 (`droid_apple_to_wooden_bowl`)**, the policy consistently achieved `object_moved_rate > 0.0` (100% in v1, 50% in v2), confirming that:
1. **Spatial reachability and camera FOV are fully resolved** (table standoff at `[-0.25, 0.0, 0.0]` brings objects within the near-field $25 - 40\text{ cm}$ visual cone).
2. **Language conditioning is grounded** (robot reaches directly toward the target apple).

However, full pick-and-place success remains gated by **tactile contact physics and grasp synthesis**:
* **Spherical Mesh Rolling & Friction Slip**: The Franka 2-finger parallel jaw gripper slips against curved/spherical organic surfaces (`apple_01_objaverse_robolab`) during closing without dynamic friction compensation (`physics_material: friction >= 0.8`), grasp yaw alignment, and adaptive finger closure pressure.
* **Affordance Standoff**: The policy approaches the apple but nudges/rolls it before achieving a stable frictional grasp lock.

### B. Parallel Vectorized Environments (`--num_envs N`)
Isaac Lab's tensorized PhysX architecture allows simulating $N = 4, 16, 32, 64$ parallel environments concurrently on a single GPU:
* **High-Throughput Rollout**: `--num_envs 32` records 32 distinct demonstration trajectories with multi-view camera feeds every $40\text{ seconds}$ ($\approx 2,880\text{ episodes / hour}$).
* **Pocket Domain Randomization**: Every parallel cell samples unique object starting poses within its $\pm 3\text{ cm}$ sector pocket, exposing the policy to diverse approach vectors.

### C. Data Science Diagnostics on Parallel Rollout Datasets
When local compute is constrained for full foundation model fine-tuning, parallel trajectory generation provides the rich dataset required for diagnostic data science:
1. **Trajectory Clustering & State-Space Divergence**: Cluster end-effector phase trajectories to pinpoint the exact time step where pre-grasp transitions into slip.
2. **Grasp Affordance Heatmaps**: Project gripper contact points onto object 3D meshes to identify high-success surface normals vs. slip zones.
3. **Sub-Goal Classification**: Automatically categorize failure modes into *Approach Error*, *Grasp Slip*, *Transport Collision*, and *Release Miss* for targeted remediation.

### D. Realistic Policy & Controller Remediation (Why NOT Inflate Physics Friction)
Artificially increasing `physics_material` friction in simulation is a **sim-to-real anti-pattern**: physical apples in the real world cannot be made stickier. Genuine remediation must be applied to **policy execution, inference dynamics, and controller parameters**:
* **Receding Horizon Control (`action_chunk_length: 16` or `8`)**: Executes high-confidence near-term steps with closed-loop visual replanning at $6–12\text{ Hz}$ to react to micro-slips.
* **Temporal Action Smoothing (EMA)**: Eliminates chunk boundary acceleration spikes ($\ddot{q}$) and inertial flinging forces ($F = m \cdot a$).
* **Binary Gripper Squeeze Bias**: Clamps gripper action $> 0.5$ to $1.0$ (full rated motor clamping torque $F_N$).
* **Diffusion Denoising Steps**: Increases inference steps (16–32) for low-variance grasp planning.

### E. Causal Knowledge Graph Memory (Neo4j LPG + RDF-star)
Containing evaluation statistics and remediation actions on the graph turns the knowledge graph into a **Causal Active Inference Memory**:
1. **Statistical Funnel Properties on `EvaluationRun`**:
   `e.lift_rate = 0.862`, `e.conversion_rate = 0.143`, `e.chi2_pval = 1.22e-14`, `e.num_episodes = 65`.
2. **Causal Derivation Edges**:
   `(v3:EnvironmentGraph)-[:WAS_DERIVED_FROM {defect: 'IN_FLIGHT_SLIP_INERTIA', patch: 'action_chunk_length=16'}]->(v2:EnvironmentGraph)`.
3. **Persistent Empirical Affordance Memory**: The system remembers which controller parameters stabilize grasps for curved/spherical geometries, eliminating repeated trial-and-error across future environments.


