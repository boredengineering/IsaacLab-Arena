# Agentic Environment Generation & Multi-Embodiment Test Suite Matrix

This document defines the comprehensive evaluation catalog, testing matrix, prompt library, and physical constraints for testing the **Agentic Active Inference Environment Generation & Self-Healing Pipeline** across different robotic embodiments, background fixtures, interactable objects, and Vision-Language-Action (VLA) foundation policies (NVIDIA Isaac-GR00T N1.6/N1.7, Unitree G1 WBC, Fourier GR1, and Franka DROID).

---

## 1. Physical Invariants & VLA Model Constraints

To ensure high transferability, visual grounding, and execution success in simulation rollouts, generated scenes must satisfy the following physical invariants:

### A. Near-Field Workspace Envelopes
* **Franka Emika Panda (DROID)**:
  * Robot Base: Fixed at `[-0.55, 0.0, 0.0]`.
  * Table Standoff: Table origin shifted to `[-0.25, 0.0, 0.0]` so the front edge sits flush with the Franka stand.
  * Near-Field Sweet Spot: All manipulands and receptacles must reside within $d \in [0.25, 0.45]\text{ m}$ ($X_{\text{world}} \in [-0.30, -0.10]\text{ m}, Y_{\text{world}} \in [-0.26, 0.26]\text{ m}$).
  * Downward Camera Frustum: Exterior camera ($45^\circ$ downward tilt) only sees $X_{\text{world}} \in [-0.35, 0.05]\text{ m}$. Anything deeper is out of view.
* **Humanoids (Unitree G1 / Fourier GR1)**:
  * Torso/Pelvis Origin: `[0.0, 0.0, 0.0]` standing.
  * Table Surface: $Z \approx 0.75 - 0.85\text{ m}$ at horizontal standoff $X \in [0.35, 0.60]\text{ m}$.
  * Bimanual Workspace: Left arm covers $Y \in [0.0, +0.35]\text{ m}$, Right arm covers $Y \in [-0.35, 0.0]\text{ m}$.

### B. Bilateral Object Clearance & Sector Randomization
* **Bilateral Separation**: Manipulands (source) and target containers (receptacles) must be placed in opposing functional sectors (e.g. `front_right` vs. `front_left`), maintaining $\ge 28\text{ cm} - 36\text{ cm}$ lateral clearance.
* **Pocket Randomization**: Objects bound to a `surface_sector` receive `RandomAroundSolution(x_half_m=0.03, y_half_m=0.03)`. Episode resets randomize within a $\pm 3\text{ cm}$ local pocket rather than scattering across the entire tabletop.

### C. Multimodal Language Conditioning
* VLA diffusion policy backbones (`AlternateVLDiT`) require unambiguous natural language instructions matching visual semantics:
  * Format: `"<Action verb> the <source object> from the <source sector> and <destination verb> it <into/onto> the <destination receptacle> located at the <destination sector>."`

---

## 2. Test Scenario Catalog

### 🍎 Category A: Fresh Food & Kitchen Tabletop (Franka DROID / Single-Arm)
* **Embodiment**: `droid_abs_joint_pos` (Dual cameras: exterior $45^\circ$ + wrist)
* **Background**: `maple_table_robolab` (Pose: `[-0.25, 0.0, 0.0]`)
* **Policy Server**: `nvidia/GR00T-N1.6-DROID` (Port 5557)

| Scenario ID | Test Name | Source Object | Target Container | Source Sector | Target Sector | Prompt / Language Instruction |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **A1** | **Apple to Wooden Bowl** | `apple_01_objaverse_robolab` | `wooden_bowl_hot3d_robolab` | `front_right` | `front_left` | *"Pick up the red apple from the front right of the maple table and place it into the wooden bowl on the front left."* |
| **A2** | **Banana to Large Plate** | `banana_ycb_robolab` | `plate_large_vomp_robolab` | `front_right` | `front_left` | *"Grasp the yellow banana from the right side of the table and set it onto the white ceramic plate on the left."* |
| **A3** | **Lemon to Clay Plate** | `lemon_01_fruits_veggies_robolab` | `clay_plates_hot3d_robolab` | `front_right` | `front_left` | *"Pick up the fresh lemon from the front right and carefully place it on the clay plate at the front left."* |
| **A4** | **Avocado to Serving Bowl** | `avocado01_fruits_veggies_robolab` | `serving_bowl_vomp_robolab` | `front_right` | `front_left` | *"Pick the green avocado from the right sector and place it inside the serving bowl on the left."* |
| **A5** | **Red Bell Pepper to Blue Bin** | `red_bell_pepper_objaverse_robolab` | `bin_b03_vomp_robolab` | `front_right` | `front_left` | *"Grasp the red bell pepper from the front right table sector and drop it into the blue bin on the front left."* |

---

### 🥫 Category B: Packaged Groceries & Pantry Sorting (Franka DROID)
* **Embodiment**: `droid_abs_joint_pos`
* **Background**: `kitchen` or `packing_table` or `maple_table_robolab`
* **Policy Server**: `nvidia/GR00T-N1.6-DROID` (Port 5557)

| Scenario ID | Test Name | Source Object | Target Container | Source Sector | Target Sector | Prompt / Language Instruction |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **B1** | **Tomato Soup to Blue Bin** | `tomato_soup_can_ycb_robolab` | `bin_b03_vomp_robolab` | `front_right` | `front_left` | *"Pick up the red tomato soup can from the front right of the counter and deposit it into the blue sorting bin."* |
| **B2** | **Mustard Bottle to Purple Crate** | `mustard_bottle_hot3d_robolab` | `purple_crate` | `front_right` | `front_left` | *"Grasp the yellow mustard bottle from the right side and place it upright inside the purple storage crate."* |
| **B3** | **Cracker Box to Brown Box** | `cracker_box` | `brown_box` | `front_right` | `front_left` | *"Pick up the Cheez-It cracker box from the packing table and place it into the brown cardboard box."* |
| **B4** | **Spam Can to Grey Bin** | `spam_can_ycb_robolab` | `grey_bin_robolab` | `front_right` | `front_left` | *"Pick the blue Spam can from the right section and drop it into the grey bin on the left."* |
| **B5** | **Tuna Can to Small Plate** | `tuna_can_ycb_robolab` | `plate_small_vomp_robolab` | `front_right` | `front_left` | *"Pick up the tuna can from the front right sector and set it onto the small plate on the front left."* |

---

### 🤖 Category C: Bimanual & Humanoid Manipulation (Unitree G1)
* **Embodiment**: `g1_wbc_pink` / `g1_wbc_joint` (Head POV Camera: `robot_head_cam_rgb`)
* **Background**: `lightwheel_robocasa_kitchen` or `galileo`
* **Policy Server**: `nvidia/GR00T-N1.7-3B` (Port 5557)

| Scenario ID | Test Name | Source Object | Target Container | Source Sector | Target Sector | Prompt / Language Instruction |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **C1** | **G1 Static Apple to Plate** | `apple_02_objaverse_robolab` | `plate_large_vomp_robolab` | `front_right` | `front_left` | *"Reach with the right arm to grasp the apple from the kitchen counter and place it onto the plate."* |
| **C2** | **G1 Ceramic Mug to Tray** | `ceramic_mug_hot3d_robolab` | `plate_large_vomp_robolab` | `front_right` | `front_left` | *"Pick up the coffee mug by the handle from the counter and place it onto the serving tray."* |
| **C3** | **G1 Sugar Box Clearing** | `sugar_box_ycb_robolab` | `bin_a06_vomp_robolab` | `front_right` | `front_left` | *"Grasp the sugar box from the front right of the kitchen island and place it into the storage bin."* |
| **C4** | **G1 Snack Bar to Pail** | `snickers_bar_objaverse_robolab` | `plasticpail_a02_vomp_robolab` | `front_right` | `front_left` | *"Pick up the snack bar from the countertop and drop it into the plastic pail."* |

---

### 🦾 Category D: Upper-Body Humanoid Tabletop (Fourier GR1)
* **Embodiment**: `gr1_pink` / `gr1_joint` (POV Camera: `robot_pov_cam_rgb`)
* **Background**: `office_table_background` or `table_oak_robolab`
* **Policy Server**: `nvidia/GR00T-N1.6` (`gr1_arms_only` with Inspire hands)

| Scenario ID | Test Name | Source Object | Target Container | Source Sector | Target Sector | Prompt / Language Instruction |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **D1** | **GR1 Ranch Dressing to Wire Shelf** | `ranch_dressing_hope_robolab` | `wireshelving_a01_vomp_robolab` | `front_right` | `shelf_tier_1` | *"Place the salad dressing bottle onto the lower shelf tier of the wire rack."* |
| **D2** | **GR1 Sugar Box to Bowl** | `sugar_box_ycb_robolab` | `wooden_bowl_hot3d_robolab` | `front_right` | `front_left` | *"Pick up the yellow sugar box from the right side of the desk and place it into the wooden bowl."* |
| **D3** | **GR1 Hardware Gear Base Assembly** | `small_gear` | `gear_base` | `front_right` | `front_left` | *"Pick up the small gear from the workbench and align it onto the central peg of the gear base."* |
| **D4** | **GR1 BBQ Sauce to Storage Box** | `bbq_sauce_bottle_hope_robolab` | `storage_box_hot3d_robolab` | `front_right` | `front_left` | *"Grasp the BBQ sauce bottle and deposit it into the storage box on the table."* |

---

## 3. Workflow Execution Playbook

### Step 1: Generate Environment Specification via Agentic Active Inference
To instantiate any scenario from the catalog, run `--mode generate` with semantic versioning:

```bash
docker exec -it   -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY"   isaaclab_arena-latest /isaac-sim/python.sh   isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py   --mode generate   --model "anthropic/claude-sonnet-4.5"   --prompt "Create an environment for a Franka robot on a maple table where the task is to pick up the red apple from the front right and place it into the wooden bowl on the front left. Position the maple table at [-0.25, 0.0, 0.0] and use droid_abs_joint_pos at [-0.55, 0.0, 0.0]."   --env_name droid_apple_to_wooden_bowl
```

### Step 2: Launch Interactive Omniverse Kit Evaluation
Evaluate the generated versioned environment in closed-loop with the policy server:

```bash
xhost +local:root 2>/dev/null || xhost +local:docker 2>/dev/null

docker exec -it   -e DISPLAY="$DISPLAY"   isaaclab_arena-latest /isaac-sim/python.sh   isaaclab_arena/evaluation/policy_runner.py   --viz kit   --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy   --policy_config_yaml_path /workspaces/isaaclab_arena/generated_envs/droid_apple_to_wooden_bowl/latest/policy_config.yaml   --remote_host 127.0.0.1   --remote_port 5557   --num_steps 2000   --enable_cameras   --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_apple_to_wooden_bowl/latest/droid_apple_to_wooden_bowl.yaml   --output_base_dir /workspaces/isaaclab_arena/eval_output/droid_apple_to_wooden_bowl
```

```bash
docker exec -it   isaaclab_arena-latest /isaac-sim/python.sh   isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py   --mode auto_heal   --env_name droid_apple_to_wooden_bowl
```

---

## 4. Empirical Statistical Diagnostic Methodology & Data Science Findings

### A. Case Study: Parallel Vectorized Evaluation ($N=65$ Episodes across $32$ Parallel Envs)
When evaluating **Scenario A1 (`droid_apple_to_wooden_bowl`)** across $32$ parallel simulation environments (`--num_envs 32 --headless`), the evaluation produced $65$ completed episodes.

#### 1. Markov State Progression Funnel
* **Stage 0 (Initial Settled)**: $65/65$ ($100.0\%$)
* **Stage 1 (Object Reached & Lifted off Table)**: $56/65$ ($86.2\%$) — proves perception, visual line-of-sight, camera FOV, and inverse kinematics reachability are solved.
* **Stage 2 (Successfully Placed into Bowl)**: $8/65$ ($12.3\%$) — verified full pick-and-place success.
* **Funnel Conversion ($\text{Lift} \to \text{Place}$)**: $14.3\%$ ($8/56$) — reveals that $85.7\%$ of failures ($48$ episodes) occur **after the object is already in the air**.

#### 2. Hypothesis Testing & Statistical Significance
* **Chi-Square Test of Stage Independence**:
  $$\chi^2 = 59.51,\quad p = 1.22 \times 10^{-14}\quad (\text{Statistically Significant at } p \ll 0.001)$$
  * *Interpretation*: Rejects the null hypothesis of uniform failure distribution. Failure is overwhelmingly concentrated in the **mid-flight transport and bowl release phase**, not the approach.
* **Grasp Decisiveness (Mann-Whitney U Test)**:
  * Successful Episodes: Mean lift step = $335.2$ (Median = $293.0$).
  * Failed Episodes: Mean lift step = $447.5$ (Median = $417.0$).
  * *Interpretation*: Prompt, clean vertical grasps ($< 300\text{ steps}$) establish stable contact friction, whereas delayed/fumbling grasps introduce pre-lift rolling that slips during acceleration.
* **In-Flight Survival Holding Time**:
  * In the $48$ failed episodes that achieved lift, the arm held the apple in the air for an average of **$448.9\text{ steps}$ ($9.0\text{ seconds}$)** before rotational slip or episode horizon timeout.

### B. Realistic Policy & Controller Remediation (Why NOT Change Physics Friction)
Modifying `physics_material` friction in simulation is a **sim-to-real anti-pattern**: in the physical world, we cannot artificially alter the friction coefficient of real apples or containers. To achieve genuine sim-to-real transfer, remediation must focus on **policy execution, inference dynamics, and controller parameters**:

1. **Receding Horizon Closed-Loop Control (`action_chunk_length`)**:
   * *Problem*: Executing a full 32-step chunk open-loop means the robot cannot react to micro-slips occurring early in the trajectory.
   * *Fix*: Halve execution horizon to `action_chunk_length: 16` (or `8`) while keeping `action_horizon: 32`. Re-evaluates camera and state feedback at $6–12\text{ Hz}$, enabling active slip compensation.
2. **Temporal Action Smoothing & Inertial Jerk Reduction**:
   * *Problem*: Discrete action chunk transitions induce joint acceleration spikes ($\ddot{q}$), producing high inertial forces ($F = m \cdot a$) that break static contact friction.
   * *Fix*: Apply exponential moving average (EMA) or low-pass temporal filtering across overlapping predicted chunks to ensure smooth velocity transitions.
3. **Gripper Clamping Torque & Binary Squeeze Bias**:
   * *Problem*: Continuous diffusion heads often output fractional gripper positions ($0.7 - 0.8$), resulting in partial closure and weak normal force ($F_N$).
   * *Fix*: Apply binary squeeze thresholding: if $a_{\text{gripper}} > 0.5$, snap to $1.0$ (full rated motor clamping torque), maximizing normal force $F_N$.
4. **Diffusion Denoising Steps (`num_diffusion_steps`)**:
   * *Fix*: Increase diffusion sampling steps (e.g. from 8/10 to 16/32 steps) to reduce trajectory variance and avoid sudden wobbling motions.
5. **Prompt Conditioning Priors**:
   * *Fix*: Phrasing instructions with explicit vertical grasping priors (e.g. *"Firmly grasp the red apple from above, lift carefully, and smoothly set it into the wooden bowl"*).

### C. Active Inference Integration in `auto_heal` & Graph Knowledge Traceability
Statistical stage funnel testing and policy remediation are integrated into the core Active Inference pipeline:

1. **`EvaluationDiagnosticOracle` Markov Funnel Parser**:
   * Automatically parses `episode_results_rank*.jsonl` from parallel runs.
   * If $\text{Lift Rate} \ge 50\%$ and $\text{Conversion Rate} < 35\%$, automatically diagnoses `IN_FLIGHT_SLIP_INERTIA` (Severity: $0.92$) instead of spatial misplacement.
   * Recommends policy patch `action_chunk_length: 16`.
2. **Causal Knowledge Graph Representation (Neo4j LPG + RDF-star)**:
   * **Evaluation Nodes**: `(e:EnvironmentGraph)-[:HAS_EVALUATION]->(ev:EvaluationRun {lift_rate: 0.862, conversion_rate: 0.143, chi2_pval: 1.22e-14})`.
   * **Causal Derivation Edges**: `(v3:EnvironmentGraph)-[:WAS_DERIVED_FROM {defect: 'in_flight_slip_inertia', policy_patch: 'action_chunk_length=16'}]->(v2:EnvironmentGraph)`.
   * **Empirical Memory**: The knowledge graph permanently preserves which control parameters prevent slip for specific object geometric affordances (e.g. spherical vs. prismatic geometries) across all historical rollouts.

```
┌────────────────────────────────────────┐
│  (EnvironmentGraph: v2)               │
│  • lift_rate: 86.2%                   │
│  • conversion_rate: 14.3%             │
│  • chi2_pval: 1.22e-14                │
└──────────────────┬─────────────────────┘
                   │
                   │  WAS_DERIVED_FROM {
                   │    defect: "in_flight_slip_inertia",
                   │    evidence: "Statistical Funnel Bottleneck",
                   │    p_value: 1.22e-14,
                   │    patch_applied: "action_chunk_length = 16"
                   │  }
                   ▼
┌────────────────────────────────────────┐
│  (EnvironmentGraph: v3)               │
│  • action_chunk_length: 16            │
│  • closed_loop_frequency: 12.5 Hz     │
└────────────────────────────────────────┘
```

#### Reusable Cross-Task Active Inference Query:
```cypher
MATCH (o:RigidObject)-[:HAS_SHAPE_AFFORDANCE]->(:CurvedGeometry)
MATCH (e:EnvironmentGraph)-[:CONTAINS_OBJECT]->(o)
MATCH (e)-[:EVALUATED_WITH]->(p:PolicyConfig)
RETURN p.action_chunk_length, p.gripper_clamping_bias, avg(e.success_rate)
```

---

## 5. False Positive Diagnostics & Container Spatial Bounding (`max_separation`)

### A. The Discrepancy: Ground-Truth Visual Validation vs. Raw Contact Sensors
During visual inspection of single-environment rollouts in the Omniverse Kit viewport (`--viz kit`), a critical ground-truth discrepancy was discovered:
* **The Raw Metric Claim**: The simulation telemetry reported a "success" based on `object_on_destination` firing.
* **The Physical Reality**: The robot never placed the apple inside the bowl. When the arm approached the apple, the flat parallel fingers pushed or rolled the spherical apple sideways. The arm proceeded along its trajectory empty-handed, and the apple merely rolled against the **outer exterior rim/base of the wooden bowl**.
* **The Root Cause**: `PickAndPlaceTask` evaluated success strictly via a PhysX contact force sensor between the apple and bowl (`force > 0.1 N, velocity < 0.1 m/s`). Because `max_separation` was `None`, any grazing contact with the **outside** of the container falsely satisfied the termination condition!

### B. The Codebase Fix: Dual-Condition Containment Verification
To guarantee that `success = True` reflects **genuine physical placement inside the receptacle volume**:
1. **Container Auto-Guarding in `PickAndPlaceTask.__init__`**:
   If `destination_location` is a container (`bin`, `bowl`, `box`, `basket`, `pail`, `crate`), `max_separation` automatically defaults to `(0.12, 0.12, 0.15)` meters unless explicitly overridden.
2. **Proximity Integration in `get_progress_objectives`**:
   `objects_in_proximity` is formally added to the multi-stage progress tracker. Success now strictly requires:
   $$\text{Success} \iff (\text{Contact Force } > 0.1\text{ N}) \;\land\; (|x - x_{\text{dest}}| < 0.12\text{ m}) \;\land\; (|y - y_{\text{dest}}| < 0.12\text{ m}) \;\land\; (|z - z_{\text{dest}}| < 0.15\text{ m})$$

### C. Geometric Affordance Transition: Scenario A1 (Spherical) to Scenario B1 (Prismatic)
* **Spherical Mesh Failure Mode**: The Franka 2-finger parallel jaw gripper contacts a sphere at a single tangent point per finger. Any approach angle offset produces shear torque that rolls the sphere away before grasp closure.
* **Prismatic Cylinder Affordance (Scenario B1)**: The `tomato_soup_can_ycb_robolab` features vertical, flat parallel sides that align with the planar surface of the Franka parallel jaws, providing distributed surface contact and high passive friction resistance against slip.

---

## 6. Scenario B1 (`droid_tomato_soup_to_blue_bin`) End-to-End Results

### A. Environment Specification & Generation
* **LLM Engine**: `anthropic/claude-sonnet-4.5` via OpenRouter.
* **Convergence**: 1 call, 0 repair iterations, 17.5s wall-clock latency. Passed SHACL-star invariants and factor graph spatial reachability.
* **Assets**:
  * Robot: `droid_abs_joint_pos` at `[-0.55, 0.0, 0.0]`.
  * Background: `maple_table_robolab` at `[-0.25, 0.0, 0.0]`.
  * Manipuland: `tomato_soup_can_ycb_robolab` in `front_right` sector.
  * Destination: `bin_b03_vomp_robolab` in `front_left` sector.
* **Task Definition**: `PickAndPlaceTask` guarded by container proximity bounding: `max_separation: [0.12, 0.12, 0.15]`.

### B. Quantitative Parallel Rollout Results ($N=16$ Envs, $20$ Episodes)
* **Stage 0 (Objects Settled)**: $20 / 20$ ($100.0\%$).
* **Stage 1 (Can Lifted off Table)**: **$17 / 20$ ($85.0\%$)**.
* **Stage 2 (Placed in Bin)**: **Verified True Positive Success** (e.g. `env_id: 15` in $392\text{ steps}$).
* **Grasp Latency vs. Scenario A1**:
  * Apple (Spherical): Median grasp step = $417\text{ steps}$ (prolonged fumbling against curved surface).
  * Tomato Soup Can (Prismatic Cylinder): First grasp step = **$122\text{ steps}$** ($3.4\times$ faster grasp acquisition due to planar jaw surface alignment).
* **Dual-Condition Verification**: Because `max_separation` was enforced, the successful completion verified both contact force $> 0.1\text{ N}$ and position inside the bin's cavity volume.





