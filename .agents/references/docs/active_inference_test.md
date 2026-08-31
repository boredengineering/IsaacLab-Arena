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

## 4. Multi-Iteration Execution Commands

### Step 1: Run Auto-Healing Pipeline
```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode auto_heal \
  --base_spec /workspaces/isaaclab_arena/generated_envs/droid_rubiks_sector_verified/droid_rubiks_cube_to_blue_bin.yaml \
  --policy_config isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml \
  --eval_dir /workspaces/isaaclab_arena/eval_output/droid_rubiks_closedloop_test/2026-08-31_20-30-26 \
  --out_dir /workspaces/isaaclab_arena/generated_envs/droid_rubiks_auto_healed
```

### Step 2: Run Remediated Evaluation in Omniverse Kit Viewport
```bash
xhost +local:root 2>/dev/null || xhost +local:docker 2>/dev/null

docker exec -it \
  -e DISPLAY="$DISPLAY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena/evaluation/policy_runner.py \
  --viz kit \
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
  --policy_config_yaml_path /workspaces/isaaclab_arena/generated_envs/droid_rubiks_auto_healed/droid_manip_gr00t_closedloop_config.yaml \
  --remote_host 127.0.0.1 \
  --remote_port 5557 \
  --num_steps 2000 \
  --enable_cameras \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_rubiks_auto_healed/droid_rubiks_cube_to_blue_bin.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_rubiks_healed_rollout
```
