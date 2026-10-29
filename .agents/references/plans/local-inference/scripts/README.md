# Local Inference & Robotics Simulation Execution Scripts

This directory contains the operational execution, verification, introspection, and benchmarking scripts for autonomous environment generation experiments (Experiments 01 through 04) conducted on the local dual-Blackwell workstation (**GPU 0: RTX PRO 6000 96 GB** + **GPU 1: RTX 5090 32 GB**).

---

## 1. Quick Reference & Navigation Matrix

| Script | Runtime Execution | Target Device | Primary Role & Research Affordance |
| :--- | :--- | :--- | :--- |
| [`orchestrate_experiment.py`](#1-orchestrate_experimentpy) | Host / Python 3 | GPU 0 / Container | End-to-end experiment driver: preflight, spec generation, ternary gate check, RSI repair, zero-action settle. |
| [`verify_articulated_spec.py`](#2-verify_articulated_specpy) | Host / Python 3 | CPU / Offline | Deterministic physical AI oracle: Pass 1 Grounding, Pass 2 SHACL, Pass 3c Software Motion Clearance ($\mathcal{W}_{\text{revolute}}$, $\mathcal{V}_{\text{prismatic}}$). |
| [`introspect_fixture_affordance.py`](#3-introspect_fixture_affordancepy) | Container / Host | CPU / Pixar USD | OpenUSD BBoxCache introspector: validates $Z_{\text{base}} = 0.0\,\text{m}$, deck height $Z_{\text{deck}}$, and syncs surface anchors to Neo4j. |
| [`introspect_usd_affordance.py`](#4-introspect_usd_affordancepy) | Container / Host | CPU / Pixar USD | USD articulation and prim tree parser: extracts revolute/prismatic joints, limits, axes, and affordance semantics. |
| [`run_experiment_03_rollouts.py`](#5-run_experiment_03_rolloutspy) | Host / Container | GPU 1 (RTX 5090) | Unified tri-track rollout runner for GR00T (Port 5556), OpenPI (Port 8008), and oracle baseline at 50 Hz. |
| [`run_phase2_5_rollouts.py`](#6-run_phase2_5_rolloutspy) | Host / Container | GPU 1 (RTX 5090) | Triad comparative rollout runner across Arms A/B/C for Scenarios B1 and C1. |
| [`test_prompt_quality.py`](#7-test_prompt_qualitypy) | Host / Python 3 | CPU | Autonomous prompt-to-spec synthesis and clearance validation test against oracle invariants. |
| [`test_verify_articulated_spec.py`](#8-test_verify_articulated_specpy) | Host / Pytest | CPU | Pytest test suite for `verify_articulated_spec.py` (facing geometry, SAT bounding boxes, quaternion rotations). |
| [`probe_asset_bboxes.py`](#9-probe_asset_bboxespy) | Container / Isaac Sim | GPU / Headless | Computes aligned local and world bounding boxes for scene assets via `pxr.UsdGeom.BBoxCache`. |
| [`probe_world_poses.py`](#10-probe_world_posespy) | Container / Isaac Sim | GPU / Headless | Dumps exact 6-DoF world poses and orientations of all scene bodies at $t=0$ and after 60 physics steps. |
| [`download_and_verify.py`](#11-download_and_verifypy) | Host / Docker | GPU 0 (RTX PRO 6000) | Candidate model downloader and isolated vLLM container smoke tester with clean VRAM deallocation. |
| [`download_openpi_weights.py`](#12-download_openpi_weightspy) | Host / Python 3 | CPU / Network | Multi-threaded streaming downloader for `pi05_droid_jointpos` foundation policy weights (~11.6 GB) from GCS. |

---

## 2. Detailed Script Documentation

### 1. `orchestrate_experiment.py`

#### Purpose & Context
The central workflow coordinator for local robotics simulation experiments. It drives the experiment lifecycle through six formal phases:
1. **`preflight`**: Hardware sanity check, GPU memory audit, and Neo4j connectivity validation.
2. **`gate_check`**: Evaluates ternary proposition logic ($\text{True}, \text{False}, \text{Unknown}$) and the Semantic Fidelity Filter ($\tau = 0.70$) to prevent cross-domain asset hallucination (e.g. Scenario `D2-NEG`).
3. **`spec`**: Dispatches natural language prompts to the local cognitive Spec LLM on Port 8000 and outputs validated `ArenaEnvGraphSpec` YAMLs.
4. **`repair`**: Triggers recursive self-healing (RSI) using Physical AI Oracle diagnostic reports to correct placement and clearance defects.
5. **`zero_action`**: Executes 300 steps of gravity settling in Isaac Sim inside Docker, recording viewport/camera MP4s and extracting keyframe validation snapshots.
6. **`all`**: Runs the complete end-to-end pipeline sequentially.

#### Runtime & Requirements
- **Host Python 3** with `yaml`, `requests`, `docker`, and `nvidia-smi` available.
- Communicates with container `isaaclab_arena-latest-isaaclab-arena-private`.
- Logs structured events to `rsi_interaction_ledger.jsonl`.

#### CLI Syntax & Examples
```bash
# 1. Run Ternary Gating Check for Scenario D2-NEG (Traps ungrounded office desk):
python3 orchestrate_experiment.py --scenario D2-NEG --phase gate_check

# 2. Synthesize cognitive specification for Scenario D1-C:
python3 orchestrate_experiment.py --scenario D1-C --phase spec --model-name qwen-coder-32b

# 3. Execute 10-seed Step-0 PhysX zero-action settling:
python3 orchestrate_experiment.py --scenario D1-C --phase zero_action --num-seeds 10

# 4. Run full pipeline with live RSI ledger tracking:
python3 orchestrate_experiment.py --scenario D2-A --phase all --log-rsi-ledger
```

#### Key Arguments
- `--scenario`: Scenario ID (`D1-C`, `D2-A`, `D2-NEG`, `D2-B`, `D2-C`, `A1`, `A2`, `B1`, `B2`).
- `--phase`: Target phase (`preflight`, `gate_check`, `spec`, `repair`, `zero_action`, `all`).
- `--num-seeds`: Evaluation seed count (default: 10).
- `--budget-tokens`: Maximum token budget for active inference reflection (default: 24,000).
- `--log-rsi-ledger`: Appends telemetry and epistemic states to `rsi_interaction_ledger.jsonl`.
- `--viz`: Launches interactive Omniverse Kit GUI instead of headless execution.

---

### 2. `verify_articulated_spec.py`

#### Purpose & Context
A deterministic, mathematically grounded Physical AI Oracle that validates candidate environment specifications before expensive simulation steps are launched. It enforces five strict verification passes:
- **Pass 1 (Digital Twin Grounding & Pedestal SAT)**: Asserts that all floor fixtures have $Z_{\text{base}} = 0.0\,\text{m}$ ($|Z| \le 0.005\,\text{m}$) and that the robot pedestal maintains $\ge 0.05\,\text{m}$ 2D Separating Axis Theorem (SAT) clearance.
- **Pass 2 (SHACL Invariant Compliance)**: Ensures that intrinsic fixture kinematics (e.g. cabinet drawers) carry zero `placedOn` edges and are linked via `hasSubPrim`, while placed props (e.g. microwaves) are strictly supported.
- **Pass 3c (Software Motion Clearance)**: Computes 2D/3D swept annular arcs $\mathcal{W}_{\text{revolute}}$ for revolving doors (clearance $\ge 0.15\,\text{m}$) and 3D Oriented Bounding Box (OBB) linear stroke corridors $\mathcal{V}_{\text{prismatic}}$ for sliding drawers (clearance $\ge 0.10\,\text{m}$).
- **Pass 4 (PhysX Settling Limits)**: Checks that linear settling velocity satisfies $v \le 0.01\,\text{m/s}$ without mesh depenetration.
- **Pass 5 (Affordance Facing Angle)**: Asserts that the approach corridor of the articulated link faces the robot workspace ($\cos \theta \le -0.70$), providing exact quaternion correction recommendations when misaligned.

#### CLI Syntax & Examples
```bash
# Verify a candidate environment YAML specification:
python3 verify_articulated_spec.py --spec_yaml generated_envs/exp04_d1c_microwave/latest/exp04_d1c_microwave.yaml

# Run verification with an explicit USD asset stage inspection:
python3 verify_articulated_spec.py --spec_yaml spec.yaml --usd_path artifacts/assets/simready/kitchen_base_cabinet.usda
```

#### Outputs
Returns a structured JSON report containing:
- `conforms`: Boolean pass/fail flag.
- `defects`: List of detected defect codes (e.g. `DEFECT_REVOLUTE_SWEPT_COLLISION`, `DEFECT_PRISMATIC_CORRIDOR_OBSTRUCTED`, `DEFECT_UNGROUNDED_FIXTURE`).
- `metrics`: Exact numerical clearances, swept arc radii, and alignment angles.
- `recommended_patches`: Deterministic pose and coordinate adjustments to resolve defects.

---

### 3. `introspect_fixture_affordance.py`

#### Purpose & Context
Introspects static scene fixtures (tables, workbenches, counters, cabinets) using Pixar USD APIs (`pxr.Usd`, `UsdGeom.BBoxCache`). It confirms physical ground contact ($Z_{\min} = 0.0\,\text{m}$), measures the exact physical deck height ($Z_{\text{deck}} = Z_{\max}$) and usable planar surface polygon, and synchronizes the fixture affordance graph `(:Fixture)-[:HAS_SUB_SURFACE]->(:SurfaceAnchor)` into the Neo4j knowledge database.

#### Runtime & Requirements
- Runs either on the host with USD bindings or inside the Isaac Sim container.
- Connects to Neo4j on Port 7688 (Bolt) when graph synchronization is enabled.

#### CLI Syntax & Examples
```bash
# Introspect an in-tree asset by registered identifier:
python3 introspect_fixture_affordance.py --fixture office_table_background

# Introspect an ingested OpenUSD file and sync to Neo4j:
python3 introspect_fixture_affordance.py \
  --fixture artifacts/assets/simready/kitchen_base_cabinet.usda \
  --sync-neo4j
```

---

### 4. `introspect_usd_affordance.py`

#### Purpose & Context
An articulation and kinematic schema analyzer. It traverses the OpenUSD prim hierarchy of articulated props and fixtures, identifying:
- Physics schemas (`PhysicsRevoluteJoint`, `PhysicsPrismaticJoint`, `PhysicsDriveAPI`).
- Joint axis vectors ($\hat{\mathbf{x}}, \hat{\mathbf{y}}, \hat{\mathbf{z}}$), upper/lower kinematic limits, and drive stiffness/damping.
- Nested prim paths and coordinate transforms between parent carcass and moving links.

#### CLI Syntax & Examples
```bash
# Introspect the kinematics of an articulated microwave:
python3 introspect_usd_affordance.py --usd_path /workspaces/isaaclab_arena/data/assets/Microwave039.usd

# Introspect an ingested SimReady counter fixture:
python3 introspect_usd_affordance.py --usd_path artifacts/assets/simready/sm_fixture_counter_a01_01.usd
```

---

### 5. `run_experiment_03_rollouts.py`

#### Purpose & Context
The unified batch execution runner for closed-loop neural policy evaluations. It manages simulation lifecycles, policy server handshakes, multi-seed evaluation loops, and video telemetry capture across three primary research tracks:
- **Track 1**: Flow-Matched DROID (`nvidia/GR00T-N1.7-3B` & `OpenPI pi05`) on tabletop scenarios.
- **Track 2**: In-domain humanoid loco-manipulation (`nvidia/GN1x-Tuned-Arena-G1`).
- **Track 3**: Multi-stage articulated manipulation (microwave door opening, turntable stowage, full sequential chain).

#### CLI Syntax & Examples
```bash
# Execute Track 3C full sequential chained rollouts with GR00T:
python3 run_experiment_03_rollouts.py --track 3C --policy gr00t --num_seeds 10

# Execute Track 1 tabletop rollouts with OpenPI pi0.5:
python3 run_experiment_03_rollouts.py --track 1 --policy openpi --num_seeds 10
```

---

### 6. `run_phase2_5_rollouts.py`

#### Purpose & Context
A specialized comparative evaluation runner designed to benchmark policy resilience across the Experiment 02 triad:
- **Arm A (Baseline)**: Overhanging or perturbed placements with reach and tipping hazards.
- **Arm B (Active Inference)**: Grounded, clearance-certified environments.
- **Arm C (Ablation)**: Constrained industrial topologies with singularity risks.

#### CLI Syntax & Examples
```bash
# Run Arm-B evaluations across Scenarios B1 and C1:
python3 run_phase2_5_rollouts.py --arm B --num_seeds 10 --headless
```

---

### 7. `test_prompt_quality.py`

#### Purpose & Context
A standalone integration test verifying that an end-to-end natural language prompt (e.g. microwave open and stow) can be successfully lowered into an `ArenaEnvGraphSpec` YAML that satisfies all software clearance and grounding checks.

#### CLI Syntax & Examples
```bash
python3 test_prompt_quality.py
```

---

### 8. `test_verify_articulated_spec.py`

#### Purpose & Context
The official unit test suite for the Physical AI Oracle (`verify_articulated_spec.py`). Covers:
- Affordance facing cosine alignment calculations.
- Quaternion rotations and yaw angle extractions.
- 2D Separating Axis Theorem (SAT) polygon overlap detection.
- Mathematical correctness of recommended orientation correction quaternions.

#### CLI Syntax & Examples
```bash
pytest test_verify_articulated_spec.py -v
```

---

### 9. `probe_asset_bboxes.py`

#### Purpose & Context
A headless Isaac Sim diagnostic script that loads scene assets inside the active simulator stage and queries `pxr.UsdGeom.BBoxCache` to compute exact aligned minimum and maximum 3D coordinates. Used for calibrating table heights, prop extents, and origin offsets.

#### CLI Syntax & Examples
```bash
docker exec isaaclab_arena-latest-isaaclab-arena-private \
  /isaac-sim/python.sh .agents/references/plans/local-inference/scripts/probe_asset_bboxes.py
```

---

### 10. `probe_world_poses.py`

#### Purpose & Context
A simulation-level diagnostic utility that instantiates a full `ArenaEnvBuilder` environment graph, calls `env.reset()`, and prints the exact 6-DoF world position (`root_pos_w`) and orientation quaternion (`root_quat_w`) of every rigid body and articulation at $t=0$ and after 60 physics steps.

#### CLI Syntax & Examples
```bash
docker exec isaaclab_arena-latest-isaaclab-arena-private \
  /isaac-sim/python.sh .agents/references/plans/local-inference/scripts/probe_world_poses.py \
    --env_graph_spec_yaml generated_envs/exp04_d1c_microwave/latest/exp04_d1c_microwave.yaml \
    --headless --num_envs 1
```

---

### 11. `download_and_verify.py`

#### Purpose & Context
Pre-downloads candidate LLM and VLM weight checkpoints from Hugging Face into `~/.cache/huggingface/hub` and spins up an isolated, temporary vLLM container on GPU 0 to execute a prompt smoke test. It asserts clean process shutdown and 100% VRAM release before returning.

#### CLI Syntax & Examples
```bash
# Download and verify candidate models:
python3 download_and_verify.py --model Qwen/Qwen2.5-72B-Instruct-AWQ
```

---

### 12. `download_openpi_weights.py`

#### Purpose & Context
A multi-threaded streaming downloader that fetches the official `Physical Intelligence OpenPI` policy weights (`pi05_droid_jointpos`, ~11.58 GB across 26 objects) directly from Google Cloud Storage into the local cache (`/root/.cache/openpi/openpi-assets-simeval/`).

#### CLI Syntax & Examples
```bash
python3 download_openpi_weights.py
```

---

## 3. Standard Operating Workflows

### Workflow 1: Ternary Gate Check & Refusal Verification
```bash
# Evaluate an unsatisfiable request with missing assets (Scenario D2-NEG):
python3 orchestrate_experiment.py --scenario D2-NEG --phase gate_check
```
*Expected Result*: Traps the missing `office_desk`, rejects cross-domain `kitchen_counter` candidate with `DEFECT_SEMANTIC_DOMAIN_MISMATCH`, and transitions $\text{Unknown} \to \text{False}$.

### Workflow 2: Cognitive Spec Generation & Motion Clearance Pass
```bash
# Step 1: Synthesize environment spec via Spec LLM:
python3 orchestrate_experiment.py --scenario D1-C --phase spec

# Step 2: Validate against Software Motion Clearance Oracle:
python3 verify_articulated_spec.py \
  --spec_yaml generated_envs/exp04_d1c_microwave/latest/exp04_d1c_microwave.yaml
```

### Workflow 3: Step-0 PhysX Simulation Settle Gating
```bash
# Execute 300 PhysX settling steps inside Isaac Sim:
python3 orchestrate_experiment.py --scenario D1-C --phase zero_action --num-seeds 10
```
*Expected Result*: Linear velocity $v_{\text{lin}} \le 0.01\,\text{m/s}$, zero mesh penetration, and frame snapshots extracted to output directory.

---

## 4. Strict Invariants & Boundaries

1. **Zero `file:///` URIs**: All file links and image references in reports and artifacts must use repository-relative paths (`../...`).
2. **Digital Twin Grounding ($Z=0.0\,\text{m}$)**: Static floor fixtures must have base height $Z = 0.0\,\text{m}$. Never lift fixtures to avoid collisions.
3. **Pedestal SAT Clearance ($\ge 0.05\,\text{m}$)**: Franka pedestal must remain clear of all fixture footprints and prismatic stroke corridors.
4. **Dual-GPU Partitioning**: Spec models strictly on GPU 0; Isaac Sim and Policy rollouts strictly on GPU 1. Never collide backends on the same GPU.
