# Session Memory: Active Inference & Robot Vision-Language-Action (VLA) Calibration

## 1. DROID / Franka Geometric & Visual Standoff Constants
* **Robot Base Origin**: `[-0.55, 0.0, 0.0]` (Franka mounted on DROID stand).
* **Table-to-Arm Proximity**:
  * In real DROID physical setups, the Franka base is mounted immediately adjacent to the table edge ($10\text{ cm} - 15\text{ cm}$ gap).
  * Table origin is shifted to `[-0.25, 0.0, 0.0]` so the tabletop front edge sits directly against the Franka stand and tabletop center is within $0.30\text{ m} - 0.40\text{ m}$ of the robot base.
* **VLA Fine-Tuning Distribution & Near-Field Inductive Bias**:
  * **VLA Training Distribution**: VLA models (`GR00T-N1.6-DROID`, OpenVLA, Octo, $\pi_0$) are trained exclusively on human teleoperated demonstrations where objects are located strictly in the **near-field manipulation zone** ($20\text{ cm} - 45\text{ cm}$ directly in front of the robot arm).
  * **Visual Perception Limit**: Franka's downward-angled camera ($45^\circ$) only captures $X_{\text{world}} \in [-0.35, 0.05]\text{ m}$ ($20\text{ cm} - 50\text{ cm}$ in front of base). Anything further is outside the camera FOV, and the VLA cannot pick what it cannot see.
  * **Spatial Constraint Invariant**: All manipulands, target receptacles, and interactive objects must be placed within $d \in [0.25, 0.45]\text{ m}$ ($X \in [-0.30, -0.10]\text{ m}, Y \in [-0.20, 0.20]\text{ m}$) relative to the robot base.

## 2. Spatial Placement & Sector-Confined Pocket Randomization
* **Sector-Bounded Initial Sampling**:
  * `On(parent, surface_sector='front_right')` and `On(parent, surface_sector='front_left')` constrain candidate sampling in `ObjectPlacer` strictly to the designated sector bounds (e.g. $Y \in [-0.26, -0.10]\text{ m}$ for `front_right`, $Y \in [0.10, 0.26]\text{ m}$ for `front_left`), accounting for parent fixture translation.
* **Pocket Randomization on Reset**:
  * Objects with `surface_sector` automatically receive `RandomAroundSolution(x_half_m=0.03, y_half_m=0.03)`. On every episode reset, objects randomize within a $\pm 3\text{ cm}$ local pocket inside their section, rather than jumping across the entire tabletop.
* **Bilateral Workspace Separation**:
  * Source manipulands and destination receptacles are placed in opposite sectors (`front_right` vs. `front_left`), maintaining $\ge 28\text{ cm} - 36\text{ cm}$ lateral clearance.
  * This avoids visual feature overlap in wrist/exterior cameras and eliminates gripper-receptacle collisions during pre-grasp.

## 3. Unified Environment & Evaluation Semantic Versioning
* **Canonical Directory Hierarchy**:
  * Graph specs: `/workspaces/isaaclab_arena/generated_envs/<env_name>/v1, v2, v3, ...` with `latest` symlink pointer.
  * Evaluation runs: `/workspaces/isaaclab_arena/eval_output/<env_name>/v1, v2, v3, ...` with `latest` symlink pointer.
* **Dual-Ledger Lineage Tracking**:
  * Human/Agent JSON: `lineage.json` with parent version pointers, refinement triggers, and success rates.
  * W3C PROV-O RDF-star: `lineage.ttl` tracking agent activities, derivations, and evaluations.
* **Automated Telemetry Sync**:
  * `policy_runner.py` automatically synchronizes evaluation metrics (`success_rate`, `object_moved_rate`, `episode_count`) into `lineage.json` and `lineage.ttl` upon rollout completion.

## 4. Foundation Policy Server (Isaac-GR00T)
* **Architecture**: `nvidia/GR00T-N1.6-DROID` with `AlternateVLDiT` diffusion action chunking.
* **Embodiment Specification**: Must use `droid_abs_joint_pos` with DROID camera and joint space.
* **Protocol**: ZeroMQ RPC on port `5557` (default port `5556` may be in use by other services).
* **Language Conditioning**: Policy config YAML **must** declare `language_instruction: "<task description>"`. Without this, the multimodal language backbone receives empty string and fails to ground objects.
* **Evaluation Horizon**: Use at least $\ge 1500 - 2000\text{ steps}$ ($30 - 40\text{ s}$) for complete pick-and-place trajectories.

## 5. Active Inference Self-Healing Pipeline
* **Diagnostic Oracle**: `EvaluationDiagnosticOracle` ingests `eval_telemetry.ttl` and classifies defects (`camera_occlusion`, `unconditioned_vla`, `horizon_truncation`, `reach_singularity`).
* **Remediation Engine**: `EvaluationRemediationEngine` auto-patches policy YAML, pulls table/objects into the near-field VLA sweet spot ($X \in [-0.30, -0.10]\text{ m}$), assigns bilateral sectors, and re-relaxes the `SpatialFactorGraph`.
* **Single-Command Pipeline**:
  `python isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py --mode auto_heal --env_name <env_name>`

## 6. Grasp Affordance, Contact Dynamics & Parallel Data Science Flywheel
* **Beyond Spatial Placement**: In addition to spatial reach and camera line-of-sight, organic/spherical objects (e.g. `apple_01_objaverse_robolab`) require tactile contact compliance and friction (`physics_material: friction >= 0.8`). The 2-finger parallel Franka gripper experiences rotational slip against spherical curvatures if approached without top-down alignment.
* **Parallel Simulation Scalability (`--num_envs N`)**: GPU tensorized execution allows simulating $N = 4, 16, 32, 64$ parallel environments concurrently ($32\times$ data collection speedup).
* **Data Science Diagnostic Flywheel**: When local compute is constrained for full foundation model fine-tuning, parallel trajectory generation provides the rich dataset required for offline data science (trajectory clustering, contact affordance heatmaps, sub-goal failure mode classification).
## 7. Statistical Diagnostic Methodology (Empirical Case Study N=65)
* **Markov Progression Funnel**:
  * Stage 0 (Settled): $65/65$ ($100\%$).
  * Stage 1 (Lifted off Table): $56/65$ ($86.2\%$) — proves perception, visual line-of-sight, and reach are solved.
  * Stage 2 (Placed in Receptacle): $8/65$ ($12.3\%$) — conversion from Lift $\to$ Place is only $14.3\%$ ($8/56$).
* **Chi-Square Test of Stage Independence**: $\chi^2 = 59.51,\; p = 1.22 \times 10^{-14}$. Proves failure is overwhelmingly localized to the in-flight transport and release phase, not the approach.
* **Grasp Decisiveness (Mann-Whitney U Test)**: Clean, prompt grasps ($< 300\text{ steps}$, median $293$) correlate with higher success vs delayed fumbling grasps (median $417\text{ steps}$).
* **In-Flight Survival Holding Time**: Failed lifted episodes held the apple in the air for an average of $448.9\text{ steps}$ ($9.0\text{ s}$) before rotational slip or time-out.

## 8. Realistic Policy/Controller Remediation & Graph Causal Memory
* **Sim-to-Real Invariant**: Never artificially inflate USD `physics_material` friction to force simulation success. In physical reality, fruit friction cannot be altered. Remediation must fix the controller, policy execution, and inference dynamics.
* **Valid Remediation Knobs**:
  1. *Receding Horizon Control*: Halve `action_chunk_length` to $16$ (or $8$) to enable $6 - 12\text{ Hz}$ closed-loop replanning and active slip correction.
  2. *Temporal Smoothing (EMA)*: Eliminates joint acceleration jerks ($\ddot{q}$) at chunk boundaries, reducing inertial flinging forces ($F = m \cdot a$).
  3. *Binary Gripper Squeeze Bias*: Snap continuous gripper predictions $> 0.5$ to $1.0$ (full rated motor clamping torque), maximizing normal force $F_N$.
  4. *Diffusion Steps*: Increase denoising steps (16–32) for low-variance trajectory synthesis.
* **Active Inference Auto-Heal Integration**:
  * `EvaluationDiagnosticOracle` parses `episode_results_rank*.jsonl`.
  * If $\text{Lift Rate} \ge 50\%$ and $\text{Conversion Rate} < 35\%$, it classifies `in_flight_slip_inertia` (Severity: 0.92) and patches `action_chunk_length = 16`.
* **Causal Knowledge Graph (Neo4j LPG + RDF-star)**:
  * Records `EvaluationRun` metrics (`lift_rate`, `conversion_rate`, $\chi^2$ p-value) and links versions via `(v2)-[:REMEDIATED_FROM {defect: 'in_flight_slip_inertia', patch: 'action_chunk_length=16'}]->(v1)`.
  * Forms a persistent empirical memory of which control parameters stabilize grasps for given object geometries.



