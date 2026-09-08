# G1 Humanoid Dexterous Manipulation Trajectory & Meta-Learning Plan

- **Author / Lead**: Antigravity Pair Programming
- **Created**: 2026-09-08
- **Status**: ACTIVE EXECUTION PLAN
- **Scope**: Resolving the trajectory generation, contact exploration, and action space dimensionality bottlenecks in G1 humanoid tabletop pick-and-place using Operational Space Control, Keypoint Guidance, Residual RL, and RAPTOR-inspired Meta-Learning Distillation.

---

## 1. Executive Summary & Root-Cause Analysis

Model-free Reinforcement Learning (PPO via RSL-RL) failed to discover a valid pick-and-place trajectory when trained directly on raw joint commands. The root cause is not RL itself, but a fundamental mismatch between the physical problem manifold and the parameterization of the action space.

```mermaid
graph TD
    subgraph Defect ["Flawed Formulation: Raw 50-D Joint Space"]
        J50["50-D Action Vector a_t in R^50<br/>(12 legs + 3 waist + 14 arms + 24 hand joints)"]
        EXP["Random Gaussian Exploration N(0, Sigma)<br/>Volume of sphere V_50(epsilon) -> 0"]
        SCALAR["Scalar Distance ||p_hand - p_apple||<br/>No orientation or approach vector constraint"]
        MONO["Monolithic Reward at t=0<br/>Reach + Lift + Transport competing concurrently"]
        J50 --> EXP
        SCALAR --> EXP
        MONO --> EXP
        EXP --> FAIL["Failure Mode: Spastic joint twitching,<br/>knuckle swatting, and zero grasp retention"]
    end

    subgraph Solution ["Architectural Remediation: 4-Tier Trajectory Pipeline"]
        P1["Tier 1: Operational Space Control (Diff-IK)<br/>Action in R^7 (Delta SE(3) + Grasp Synergy)"]
        P2["Tier 2: Multi-Keypoint Geometric Guidance<br/>5 Finger Keypoints to Object Anchors"]
        P3["Tier 3: Staged Reverse Curriculum<br/>Grasp & Lift -> Transport -> Full Reach"]
        P4["Tier 4: RAPTOR Meta-Learning Distillation<br/>Privileged Teacher -> Recurrent In-Context Student"]
    end

    FAIL -.-> Solution
```

### The Three Mathematical Trajectory Bottlenecks
1. **Curse of Dimensionality in Joint Space**: In an unconstrained $\mathbb{R}^{50}$ action space, the probability of 7 arm joints and 12 hand joints accidentally aligning into a synchronized Cartesian trajectory toward an apple is astronomically small ($O(\epsilon^{50})$).
2. **$SO(3)$ Orientation Blindness**: A scalar Euclidean reward $\|\mathbf{p}_{\text{hand}} - \mathbf{p}_{\text{apple}}\|$ possesses spherical symmetry; it rewards approaching the apple with the back of the knuckles or upside down. Stable grasping requires aligning the palm normal $\hat{\mathbf{n}}_{\text{palm}}$ with the target approach vector.
3. **Competing Gradient Interference**: When reaching, lifting, and placing rewards are active simultaneously without phase gating, the policy receives gradients to transport before contact has been verified, incentivizing ballistic swatting.

---

## 2. Core Manipulation Trajectory Paradigms

Based on analysis of SOTA Isaac Lab implementations (`pickplace_unitree_g1_inspire_hand_env_cfg.py`, `fixed_base_upper_body_ik_g1_env_cfg.py`, `franka_lift`), we synthesize four foundational paradigms:

### Paradigm 1: Operational Space Control (Task-Space Diff-IK)
* **Mathematical Formulation**:
  $$\mathbf{a}_t = \begin{bmatrix} \Delta \mathbf{p}_{\text{EEF}} \\ \Delta \mathbf{\phi}_{\text{EEF}} \\ g_{\text{finger}} \end{bmatrix} \in \mathbb{R}^7$$
  The policy predicts a 3D Cartesian position delta $\Delta \mathbf{p} \in \mathbb{R}^3$, a 3D Euler/axis-angle orientation delta $\Delta \mathbf{\phi} \in \mathbb{R}^3$, and a 1D continuous grasp synergy $g \in [-1, 1]$.
  An onboard Differential Inverse Kinematics (Diff-IK) or Quadratic Programming solver (Pink / Pinocchio) computes the required joint velocities:
  $$\dot{\mathbf{q}} = \mathbf{J}^\dagger (\mathbf{v}_{\text{des}}) + (\mathbf{I} - \mathbf{J}^\dagger \mathbf{J})\dot{\mathbf{q}}_{\text{null}}$$
* **Impact**: Reduces policy action space from 50 to 7 dimensions. Reaching toward the target becomes a trivial linear gradient in 3D Euclidean space.

### Paradigm 2: Multi-Keypoint Geometric Guidance
* **Mathematical Formulation**:
  Instead of a single center-of-mass point distance, attach $K=5$ canonical keypoints to the robot hand (thumb tip, index tip, middle tip, ring tip, palm center: $\mathbf{p}_k^{\text{hand}}$) and corresponding target anchor points on the object ($\mathbf{p}_k^{\text{target}}$):
  $$R_{\text{keypoint}} = \frac{1}{K} \sum_{k=1}^K \exp\left(-\frac{\|\mathbf{p}_k^{\text{hand}} - \mathbf{p}_k^{\text{target}}\|^2}{2\sigma^2}\right)$$
* **Impact**: Constrains 3D position, 3D approach orientation, and finger aperture simultaneously without discontinuous penalty spikes.

### Paradigm 3: Residual Reinforcement Learning (RRL)
* **Mathematical Formulation**:
  A deterministic minimum-jerk or cubic Hermite spline generator provides a nominal reference waypoint $\mathbf{x}_{\text{nom}}(t)$ traversing:
  $$\mathbf{x}_{\text{home}} \longrightarrow \mathbf{x}_{\text{pre\_grasp}} \longrightarrow \mathbf{x}_{\text{grasp}} \longrightarrow \mathbf{x}_{\text{lift}} \longrightarrow \mathbf{x}_{\text{place}}$$
  The policy only learns a bounded residual displacement:
  $$\mathbf{x}_{\text{cmd}}(t) = \mathbf{x}_{\text{nom}}(t) + \alpha \cdot \pi_\theta(s_t)$$
* **Impact**: Guarantees kinematically smooth free-space transport (100% reachability) while allowing RL to focus exclusively on contact compliance, tactile friction adaptation, and slip prevention.

### Paradigm 4: Staged Reverse Curriculum
* **Curriculum Phases**:
  1. **Phase A (Grasp & Lift)**: Reset state initializes hand at $\mathbf{p}_{\text{pre\_grasp}}$ ($2\text{ cm}$ above apple); policy learns finger closure and $+3\text{ cm}$ vertical lift.
  2. **Phase B (Transport & Place)**: Reset state initializes with apple captured in hand; policy learns smooth arc transport to plate and release.
  3. **Phase C (Full Sequence)**: Reset state initializes from home position; policy executes full end-to-end task.

---

## 3. Advanced Reference: The RAPTOR Meta-Learning Architecture

The user identified **RAPTOR** ([github.com/rl-tools/raptor](https://github.com/rl-tools/raptor), *Eschmann, Albani, Loianno, 2026*) as an exemplary meta-learning framework. While developed for agile quadrotor control, its architectural principles directly solve the core bottlenecks of robotic manipulation.

```mermaid
flowchart TD
    subgraph Teacher ["Phase 1: Privileged Teacher Ensemble (RL)"]
        SIM_VARS["Simulated Variations:<br/>Object mass m in [0.05, 0.35] kg<br/>Friction mu in [0.2, 1.2]<br/>Compliance k_table in [1e3, 1e5]<br/>External perturb F_dist"]
        TEACHER_OBS["Privileged Observations s_t^priv:<br/>(Proprioception + True Object CoM +<br/>Friction Tensor + Contact Normal Forces)"]
        TEACHER_POL["Privileged MLP Teacher Policy<br/>pi_teacher(a | s_t^priv)"]
        SIM_VARS --> TEACHER_OBS --> TEACHER_POL
    end

    subgraph Distillation ["Phase 2: Recurrent Meta-Imitation Distillation"]
        STUDENT_OBS["Non-Privileged Observable History o_t:<br/>(Joint pos/vel + EE pose + Target spec + Prev Action)"]
        GRU["Gated Recurrent Unit (GRU) Hidden State h_t<br/>h_t = GRU(h_{t-1}, [o_t, a_{t-1}])<br/>(Implicit In-Context System Identification)"]
        STUDENT_POL["Adaptive Student Policy<br/>pi_student(a | h_t)"]
        LOSS["Meta-Distillation Loss:<br/>L_distill = ||pi_student(o_t, h_{t-1}) - pi_teacher(s_t^priv)||^2"]
        STUDENT_OBS --> GRU --> STUDENT_POL
        TEACHER_POL --> LOSS
        STUDENT_POL --> LOSS
    end

    subgraph Deployment ["Phase 3: Real-Time In-Context Adaptation"]
        TOUCH["Hand makes physical contact with apple"] --> SHOCK["Instant change in joint effort / velocity"]
        SHOCK --> ADAPT["GRU hidden state h_t adapts in 2-3 simulation steps"]
        ADAPT --> STABLE["Grasp pressure & lift force dynamically adjusted"]
    end
```

### Why RAPTOR's Meta-Learning Solves Manipulation
1. **In-Context System Identification**: Physical manipulation is rife with unobservable parameters: the exact friction coefficient $\mu$, object mass $m$, and contact normal $\hat{\mathbf{n}}$ cannot be measured directly by standard sensors. In RAPTOR, the recurrent hidden state ($h_t$) acts as an online system identifier, adapting the control strategy within milliseconds based on interaction history.
2. **Separation of Concerns**: Training a monolithic student policy to explore both physical variation and trajectory planning simultaneously leads to policy collapse. Training a privileged teacher first guarantees that optimal manipulation strategies are discovered under ground-truth conditions, which are then compressed into the adaptive student.
3. **Zero-Shot Sim-to-Real Robustness**: Because the recurrent student learned to infer dynamic properties from sensor trajectories, it handles real-world physical discrepancies (weight differences, surface dampening) zero-shot without retraining.

---

## 4. Concrete Implementation Architecture in IsaacLab-Arena

### Phase 1: Operational Space Control ($\mathbb{R}^7$) & Keypoint Guidance (Immediate Implementation)
1. **Embodiment Action Controller**:
   - Provide a task-space action binding: `DifferentialInverseKinematicsActionCfg` or operational Pink IK for the Unitree G1 upper body.
   - Action dimensions:
     - $[0:3]$: Cartesian target delta $[\Delta x, \Delta y, \Delta z]$ for left hand wrist.
     - $[3:6]$: Cartesian orientation delta $[\Delta \text{roll}, \Delta \text{pitch}, \Delta \text{yaw}]$.
     - $[6]$: Grasp scalar command $g \in [-1, 1]$ mapped to finger flexion joints.
2. **Reward & Term Reshaping**:
   - Add `palm_object_approach_alignment`: Cosine similarity between palm downward normal and vector to apple:
     $$R_{\text{approach}} = \max(0, \hat{\mathbf{n}}_{\text{palm}} \cdot \hat{\mathbf{v}}_{\text{target}})$$
   - Add `finger_aperture_shaping`: Pre-grasp open aperture when distance $> 0.05\text{ m}$; closure reward when distance $< 0.03\text{ m}$.
   - Retain our verified grounded relative lift `object_lifted_above_resting_min` and low-velocity placed bonus.
3. **Parallel Exploration Scale**:
   - Increase training environment count from `num_envs = 64` to `num_envs = 256` or `512`.

### Phase 2: RAPTOR Teacher-Student Distillation Integration
1. **Privileged Observation Group (`teacher`)**:
   - Includes object linear/angular velocities, contact forces from table and hand, exact friction coefficient, and object mass.
2. **Student Observation Group (`student`)**:
   - Includes joint positions, joint velocities, end-effector pose, target plate pose, and previous action.
3. **RSL-RL Distillation Config**:
   - Leverage `RslRlDistillationRunnerCfg` with `rnn_type="gru"`, `rnn_hidden_dim=128`.
   - Train privileged teacher with PPO for 1,000 iterations.
   - Distill into GRU student policy across randomized physical parameter sweeps.

---

## 5. Implementation Roadmap & Verification Milestones

| Milestone | Deliverable | Validation Metric | Target File(s) |
| :--- | :--- | :--- | :--- |
| **M1: Task-Space Action Setup** | 7-D Diff-IK / Pink IK action adapter for G1 tabletop task | Action dimension verified at 7; IK convergence $< 2\text{ ms}$ | `isaaclab_arena/tasks/pick_and_place_task_rl.py`, `g1_apple_to_plate_rl_environment.py` |
| **M2: Keypoint & Approach Reward** | Palm orientation alignment + fingertip-to-apple guidance terms | Hand approaches vertically with fingers open; 0 knuckle collisions | `isaaclab_arena/tasks/rewards/pick_and_place_rewards.py` |
| **M3: Staged Validation Training** | Train RSL-RL for 300 iterations with 256 envs | Lift rate $> 40\%$, object moved rate $> 80\%$ | `logs/rsl_rl/` |
| **M4: RAPTOR Meta-Learning Config** | Teacher-student distillation spec with GRU hidden state | Loss convergence in distillation; in-context mass adaptation | `isaaclab_arena_examples/policy/raptor_distillation_cfg.py` |
| **M5: DCRG Knowledge Graph Sync** | Evaluation telemetry ingested into Neo4j with updated predicates | `semantic_integrity_verified: true`, `all_complete_rate > 0` | `lpg_neo4j_sync.py`, `eval_telemetry.ttl` |
