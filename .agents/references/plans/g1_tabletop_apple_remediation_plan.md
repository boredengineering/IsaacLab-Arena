# Remediation Plan & Architectural Resolution: G1 Tabletop Pick-and-Place (`Scenario C1`)

> [!IMPORTANT]
> **Status**: ACTIVE ARCHITECTURAL RESOLUTION (Post-`v9` Autopsy).
> While `v8` successfully resolved the physical hand collision and Phase 1 object settling invariants ($< 0.07\text{ mm}$ drift), the subsequent rollout in `v9` uncovered a **false-positive premature termination trap** and a **fundamental domain mismatch** between the pre-trained imitation checkpoint (`nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace`) and the synthetic tabletop environment (`maple_table_robolab`).

---

## 1. Executive Summary & Problem Evolution

Scenario C1 evaluates whether the agentic environment generation pipeline can autonomously synthesize, ground, settle, and evaluate a closed-loop tabletop pick-and-place task on a bipedal humanoid embodiment.

Across iterations `v6` through `v9`, four distinct failure modes and architectural blockers were diagnosed:

```mermaid
flowchart TD
    subgraph V6 ["Iteration v6: Overextended Reach & Visual Divergence"]
        F1["Robot: X = -0.42m | Table: X = 0.0m"] -->|Table too far: ΔX = 31.5cm| E1["Arm stalls; reaches into empty air"]
    end

    subgraph V7 ["Iteration v7: Hand Collision & PhysX Explosive Impulse"]
        F2["Table moved close: X = -0.08m"] -->|Plate placed at X = -0.18m| E2["Hand link overlaps 30cm plate at t=0;<br/>PhysX de-penetration catapults plate across table (1.21 m/s)"]
    end

    subgraph V8 ["Iteration v8: Clearance Resolution & Settling Verification"]
        F3["Grounded Table: X = -0.58m | Robot: X = -0.46m<br/>Clearance Sector: X_table in [0.48, 0.88]<br/>Hold-Action Settle Warmup (12 steps)"] --> E3["Settled drift <= 0.07mm, vel = 0.001 m/s;<br/>Phase 1 gate verified, but policy stood still"]
    end

    subgraph V9 ["Iteration v9: The False-Positive Trap & Core Blockers"]
        F4["Spawn apple/plate near training poses<br/>Prompt: 'move the apple to the plate'"] --> E4["Contact sensor fires at step 14 (0.28s) -> Fake 100% success;<br/>Scale 0.5x causes PhysX bounce on maple deck;<br/>Fundamental: Checkpoint overfitted to galileo_locomanip shelf, not maple table!"]
    end

    V6 -->|Ground Table Anchor| V7
    V7 -->|Clearance Sector + Posture Settle| V8
    V8 -->|Sector Re-alignment & Prompt Matching| V9
```

---

## 2. Root Cause Analysis (RCA)

### RCA 1: Fixed Camera Pitch Invariant
* **Initial Assumption**: `v7` proposed tilting the head camera downward by $15^\circ - 20^\circ$ to center the apple in the frame.
* **Physical Reality**: In physical humanoid hardware (and specifically the Unitree G1), head-mounted cameras have a **rigidly fixed pitch angle** ($35^\circ$ downward). Simulation environments cannot change the camera pitch, as doing so introduces a severe simulation-to-reality (Sim2Real) domain break.
* **Resolution**: Lock camera pitch to the hardware specification. Spatial layouts must be derived by intersecting the fixed downward Field of View (FOV) cone ($X_{\text{world}} \in [0.0, 0.25]\text{ m}$) with the arm reach envelope.

### RCA 2: Initial Bounding Box Interpenetration ($t = 0$ Hand Collisions)
* **Observed Symptom**: In `v7`, when the simulation spawned, the clay plate immediately slid across the table at high speed, failing the Phase 1 requirement that spawned objects must sit completely still.
* **Kinematic Footprint Audit**:
  * G1 base stands at $X_{\text{world}} = -0.46\text{ m}$.
  * G1 left palm rests at $X_{\text{world}} \in [-0.22, -0.13]\text{ m}, Y_{\text{world}} \in [+0.13, +0.17]\text{ m}$.
  * G1 left fingers extend forward to $X_{\text{world}} = -0.043\text{ m}$.
  * The `clay_plate` is $30\text{ cm}$ in diameter (radius $15\text{ cm}$). When placed at $X_{\text{world}} \approx -0.18\text{ m}$, its rear rim reached back to $X_{\text{world}} = -0.33\text{ m}$, heavily intersecting the robot's palm and fingers.
* **PhysX Impulse Explosion**: At $t = 0$, PhysX collision de-penetration injected a massive repulsive impulse ($1.21\text{ m/s}$), rocketing the plate across the table surface.

### RCA 3: Unpowered Joint Collapse During Raw Physics Stepping
* **Observed Symptom**: Calling `physics_settle.step_physics()` (which invokes `sim.step()` without stepping `action_manager`) resulted in plate velocities $> 0.70\text{ m/s}$ even when objects were placed far from the hands.
* **Mechanism**: G1 is an articulated humanoid with 29 active motor joints. Stepping `sim.step()` raw without Whole-Body Controller (WBC) PD target updates cuts motor torques. The robot's upper body and arms collapsed under gravity onto the table deck, crashing into the spawned objects.
* **Resolution**: Settling must be executed using environment steps with neutral posture-holding actions (`env.step(hold_action)`), maintaining standing posture while gravity and normal contact forces settle.

---

## 3. The Systematic Solution: `v8` Architecture

### A. Grounded Table & Clearance Sector Geometry
Table origin is anchored at $X_{\text{world}} = -0.58\text{ m}, Y = 0.0, Z = 0.0$.
* Table deck is at $Z_{\text{world}} = 0.003\text{ m}$.
* Table front edge nearest the robot is at $X_{\text{world}} = -0.38\text{ m}$ ($8\text{ cm}$ forward of G1 torso).
* Table local coordinate space: $X_{\text{world}} = X_{\text{table}} - 0.58\text{ m}$.

To guarantee zero bounding box collisions with G1 hands while staying inside the camera FOV:
```python
FIXTURE_SECTOR_BOUNDS = {
    "maple_table_robolab": {
        "front_left":   (0.48, 0.88,  0.05,  0.48, 0.0),  # Receptacle zone (clay plate)
        "front_right":  (0.48, 0.85, -0.45, -0.08, 0.0),  # Manipuland zone (red apple)
        "front_center": (0.45, 0.85, -0.15,  0.15, 0.0),
    }
}
```

```
                               Top-Down Geometry (World Frame)
                               
   Robot Base          Fingertips         Table Deck Front        Plate Center       Apple Center
  [ X = -0.46m ]     [ X = -0.04m ]        [ X = -0.38m ]        [ X = +0.11m ]     [ X = +0.08m ]
       |                  |                      |                      |                  |
       |<--- 42 cm ------>|                      |                      |                  |
       |                  |<------- 34 cm ------>|<------- 49 cm ------>|                  |
       |                  |  (Clearance Gap)     |  (Direct Camera FOV) |                  |
```

* **Plate Center**: $X_{\text{table}} \approx 0.69\text{ m} \implies X_{\text{world}} \approx +0.11\text{ m}, Y_{\text{world}} \approx +0.25\text{ m}$.
  * Rearmost rim of $30\text{ cm}$ plate: $X_{\text{world}} = 0.11 - 0.15 = \mathbf{-0.04\text{ m}}$.
  * Hand fingertips end at $X = -0.043\text{ m}$ only in the narrow strip $Y \in [0.035, 0.173]\text{ m}$.
  * **Result**: Complete geometric separation in 3D space ($X, Y, Z$)!

### B. In-Inference Settling Verification Pipeline

Integrated directly into `isaaclab_arena/evaluation/policy_runner.py` and `isaaclab_arena/tasks/pick_and_place_task.py`:

1. **`verify_and_settle_scene()`**:
   - On every episode reset, advances 12 warmup steps using zero/hold actions (`env.step(hold_action)`).
   - Reads rigid body root velocities for all movable scene assets.
   - Evaluates linear velocity ($v_{\text{lin}} \le 0.1\text{ m/s}$) and angular velocity ($\omega_{\text{ang}} \le 1.0\text{ rad/s}$).
   - Recomputes observation buffers post-settle so the policy perceives the stationary scene.
2. **CLI Flags in `policy_runner_cli.py`**:
   - `--check_settling`: Enables pre-inference settle verification (default: `True`).
   - `--settle_steps`: Warmup steps (default: `12`).
   - `--settle_lin_vel_thresh`: Linear threshold (default: `0.1` m/s).
   - `--settle_ang_vel_thresh`: Angular threshold (default: `1.0` rad/s).
3. **Dual-Object Task Predicate**:
   - `PickAndPlaceTask.get_progress_objectives()` now tracks both `self.pick_up_object` and `self.destination_object` in `objects_settled`.

---

## 4. Empirical Verification Evidence

### 1. Zero-Action Physics Settling Proof (30 Simulation Steps)
```text
--- RESET POSITIONS ---
Plate start: [0.1133, 0.2542, 0.0128]
Apple start: [0.0798, -0.3199, 0.0318]
Step 00: Plate pos=[0.1133, 0.2542, 0.0104], vel=0.1962 | Apple pos=[0.0798, -0.3199, 0.0294], vel=0.1962
Step 05: Plate pos=[0.1133, 0.2542, 0.0027], vel=0.0015 | Apple pos=[0.0801, -0.3206, 0.0196], vel=0.0344
Step 10: Plate pos=[0.1133, 0.2542, 0.0027], vel=0.0015 | Apple pos=[0.0801, -0.3207, 0.0195], vel=0.0012
Step 20: Plate pos=[0.1133, 0.2542, 0.0027], vel=0.0083 | Apple pos=[0.0801, -0.3206, 0.0195], vel=0.0117
Step 25: Plate pos=[0.1133, 0.2542, 0.0027], vel=0.0035 | Apple pos=[0.0801, -0.3206, 0.0195], vel=0.0061

Plate drift over 30 steps: 0.000070 m  (0.07 mm!)
Apple drift over 30 steps: 0.000748 m  (0.74 mm!)
```

### 2. Runtime Settle Verification Output During Inference
```text
[Rank 0/1] Simulation length: 100 steps
[Rank 0/1] Starting rollout (100 steps)
[policy_runner] 🔍 Phase 1 Settle Verification: Checking 2 scene objects for stationarity...
  - 'red_apple': lin_vel=0.0176 m/s, ang_vel=0.5759 rad/s -> ✅ SETTLED
  - 'clay_plate': lin_vel=0.0010 m/s, ang_vel=0.0238 rad/s -> ✅ SETTLED
[policy_runner] ✅ All scene objects are physically settled. Proceeding to policy inference.
Steps: 100%|██████████| 100/100 [00:06<00:00, 16.01step/s]
```

---

## 5. Iteration `v9` Autopsy: The Premature Termination Trap & Scale Instability

Iteration `v9` aligned the language prompt (`"move the apple to the plate"`) and mirrored the object layout to match the left-arm reaching trajectory of the training data. While initial rollout logs reported `success_rate: 1.0`, deep forensic analysis of the telemetry and video recordings revealed critical failure modes:

### A. The False-Positive Contact Termination Trap
* **Symptom**: `policy_runner` reported `success_rate: 1.0`, but the generated video (`robot-cam-env0-robot_head_cam_rgb-episode-0.mp4`) lasted only **0.28 seconds (14 frames)**.
* **Telemetry Evidence**: In `episode_results_rank0.jsonl`:
  ```json
  {
    "success": true,
    "episode_length": 15,
    "progress": {
      "overall_score": 0.0,
      "all_complete": false,
      "objectives": {
        "pick_and_place": {
          "score": 0.0,
          "is_complete": false,
          "completed_groups": 0,
          "active_predicates": {"default_group": "objects_settled"}
        }
      }
    }
  }
  ```
* **Root Mechanism**: In `PickAndPlaceTask`, `check_success` invokes `object_on_destination` (`force_threshold = 0.1 N`, `velocity_threshold = 0.1 m/s`). Because the unscaled clay plate (diameter 30 cm) spawned immediately adjacent to the apple on `maple_table`, the initial arm forward reach or slight table vibration caused the plate rim to touch the apple. The contact sensor registered normal force $> 0.1\text{ N}$ while the apple was at rest, immediately satisfying `object_on_destination` at step 14. The environment aborted before the robot ever grasped or lifted the object (`object_is_above_height` was never evaluated).

### B. Scaled Plate Mesh Instability on Maple Deck
* **Symptom**: When `scale: [0.5, 0.5, 0.5]` was injected into `clay_plate` to reduce footprint, PhysX dynamics broke during the Phase 1 settling gate:
  ```text
  - 'red_apple': lin_vel=0.7906 m/s, ang_vel=32.1118 rad/s -> ⚠️ UNSETTLED
  - 'clay_plate': lin_vel=0.1887 m/s, ang_vel=5.2592 rad/s -> ⚠️ UNSETTLED
  ```
* **Root Mechanism**: Unlike the reference `galileo_locomanip` environment (which incorporates an invisible flat cuboid `StaticShelfSupport` and asset-specific `_USD_ORIGIN_ABOVE_BOTTOM_M` Z-offset compensations), `maple_table_robolab` lacks collision support geometry for small scaled meshes. At fractional scales, thin mesh boundaries experience contact jitter, tunneling, and elastic rebound off the procedural table deck.

---

## 6. The Core Architectural Blockers (Why Subsequent Attempts on this Setup Will Fail)

Iterating further within the `maple_table_robolab` + `nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace` configuration will continue to fail due to three immutable architectural constraints:

### 1. The Checkpoint is an Overfitted Imitation Policy, Not a Zero-Shot Generalist VLA
`nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace` is a task-specific checkpoint fine-tuned on 200 teleoperated demonstrations recorded strictly inside the reference environment `galileo_g1_static_pick_and_place`. It does not possess zero-shot cross-scene visual or physical generalization.

### 2. Massive Out-of-Distribution (OOD) Visual Domain Shift
| Reference Demonstrations (`galileo_locomanip`) | Synthetic Environment (`maple_table_robolab`) |
| :--- | :--- |
| Dark matte industrial shelf surface | High-contrast, bright yellow-brown wood grain |
| Dense background features (white/gray packing boxes, shelf struts) | Empty white void |
| Low-glare directional shadows | Flat default dome light |

Diffusion policy visual backbones (`AlternateVLDiT`) encode image patch tokens. When fed the wood-grain table texture, the cross-attention activations collapse or produce null action vectors, preventing the arms from initiating purposeful reaching.

### 3. Kinematic and Prompt Specification Contradiction
* **Scenario C1 Specification** (`env_gen_test.md`):
  *"Reach with the right arm to grasp the red apple from the front right of the maple table and place it onto the clay plate on the front left."*
* **Checkpoint Demonstrations**:
  * **Arm**: 100% Left arm. Zero right-arm grasp demonstrations exist in the checkpoint weights.
  * **Layout**: Apple on the left ($\Delta Y \approx +0.19\text{ m}$), plate in the center ($\Delta Y \approx -0.02\text{ m}$).
  * **Conditioning Prompt**: Strictly `"move the apple to the plate"`.
* **The Conflict**: Providing the C1 prompt causes prompt token OOD rejection. Providing the C1 right-arm layout commands the left arm into empty space on the left. Aligning to the left arm violates the benchmark specification while still failing due to the visual domain shift.

---

## 7. Resolution Pathways: Aligning the Evaluation Contract

To resolve Scenario C1 rigorously, one of the following architectural pathways must be adopted:

### Pathway A: Ground the Benchmark against the Checkpoint's True Reference Scene
If the goal is to evaluate the closed-loop foundation checkpoint `nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace`, update the environment generation target to synthesize a valid `galileo_locomanip` shelf scene:
1. Target background: `galileo_locomanip` with invisible `StaticShelfSupport`.
2. Object scales: Apple `(0.009, 0.009, 0.009)`, plate `(0.5, 0.5, 0.5)`.
3. Task prompt: `"move the apple to the plate"`.
4. Layout: Left-arm pickup corridor ($X \approx 0.33\text{ m}, Y \approx +0.19\text{ m}$) to center ($X \approx 0.33\text{ m}, Y \approx -0.02\text{ m}$).

### Pathway B: Follow the Full 4-Stage Workflow for Novel Tables (`maple_table`)
If the objective is truly an autonomous pick-and-place task on `maple_table_robolab` with the right arm:
$$\text{Stage 1: Generate Env} \longrightarrow \text{Stage 2: Teleop / Mimic Demos} \longrightarrow \text{Stage 3: Fine-Tune GR00T Policy} \longrightarrow \text{Stage 4: Closed-Loop Eval}$$
An imitation checkpoint cannot be evaluated on an environment it was never trained to operate within.

### Pathway C: Sequential Termination Guard in `PickAndPlaceTask` — **IMPLEMENTED (2026-09-03)**
To prevent the false-positive premature termination discovered in `v9`:
* `SuccessMode.SEQUENCE` added to `isaaclab_arena/tasks/terminations.py`. Predicates latch in listed order and a later stage cannot latch until every earlier one has, so `object_on_destination` cannot fire before a verified lift. Predicates that hold simultaneously latch within the same step, so concurrent stages still behave like `ALL`.
* `object_lifted_above_resting_min` (`predicates/spatial.py`) supplies the lift stage, referencing a per-env **running minimum of the object's own height** rather than a hardcoded surface height or the settled-state recorder. The recorder is reset only by the progress tracker, so depending on it inside the always-active termination path would have made success unreachable in runs without progress tracking.
* Episode-scoped latch and running-min state lives in `predicates/episode_state.py`, self-clearing when `episode_length_buf` rewinds — correct in every run mode, and idempotent under repeated evaluation within one step.
* `PickAndPlaceTask(require_lift_before_place=True, min_lift_height=0.05)`, both settable from a graph spec's `TaskSpec.params`.

> [!NOTE]
> **This is a correctness fix for all manipulation tasks, not a fix for C1.** It closes the measurement defect that made `v9`'s telemetry untrustworthy; it does not make the checkpoint capable of the task.
> Verified in `test_object_on_termination.py`: the same gravity drop that fires success with the gate off never fires it with the gate on.
> Six existing tests reach success by dropping an object with zero actions to exercise contact-sensor plumbing; they now pass `require_lift_before_place=False` explicitly.

---

## 7b. Decision Taken (2026-09-03): Adapt the Model, Not the Scene

Pathways A and B are **rejected**. The direction is to fine-tune on the galileo scene and transfer to `maple_table`, with the generation pipeline itself responsible for diagnosing and closing the transfer gap.

That required the graph to model the policy, which it previously did not. See session [`modelgraph`](../../memory/sessions/20260903_180000_modelgraph.md) for the implementation. In brief:

* `arena:violatesInvariant` joins an `EnvironmentGraph` to a `TrainingInvariant` established by the corpus a policy was trained on — the missing edge between the scene graph and the model graph.
* Three closed registries (`FailureMode`, `DiagnosticTechnique`, `RemediationTechnique`) with `arena:discriminates` and `arena:resolves`, so technique choice becomes information-gain-per-cost rather than running every check.
* `arena:invalidatedBy` keeps physically dishonest fixes representable and permanently disqualified.
* `RemediationTechnique.preserves_target_scene` encodes this very decision: fixes that work by rebuilding the scene as the corpus are excluded when the scene is what is being evaluated.

Running the C1 `v9` spec through it reproduces this document's autopsy with no rollout and no policy weights: `surface_height_rel_pelvis` off by 5.6x tolerance (dominant `vertical_reach_ood`), laterality/prompt/visual-domain violated, and `controller_binding` correctly reported as **in** tolerance.

**Next step for the transfer plan**: after fine-tuning, register a new `PolicyProfile` whose invariants reflect the widened training distribution. Transfer readiness against `maple_table` then becomes a re-measurement rather than a re-argument.

---

## 8. Generalized Workflow Blueprint for Future Humanoid Scenarios

To ensure any future humanoid scenario (e.g., dual-arm sorting, tool pickup) succeeds automatically without manual debugging iterations:

1. **Phase 1: Grounded Specification**:
   - Extract embodiment-specific hardware invariants (fixed camera pitch, resting arm footprint).
   - Anchor support fixtures to known metric origin frames.
2. **Phase 2: Clearance & FOV Bounding**:
   - Query `FIXTURE_SECTOR_BOUNDS`: Sectors must be offset by the robot's resting hand reach radius ($X_{\text{clearance}} \ge X_{\text{fingertip}} + R_{\text{object}}$).
   - Intersect sector bounds with the fixed camera downward frustum.
3. **Phase 3: Controller Pre-Conditioning**:
   - Match embodiment action dimensions (e.g. 50-D for G1 WBC joint vs. 23-D for Pink IK).
   - Configure diffusion action chunking ($40$ steps for G1) and initial open-arm stance.
4. **Phase 4: Hold-Action Settle Gate**:
   - Warm up with hold action for $10-12$ steps.
   - Guard inference entry with $v_{\text{lin}} \le 0.1\text{ m/s}, \omega_{\text{ang}} \le 1.0\text{ rad/s}$.
5. **Phase 5: Telemetry Attribution & Auto-Heal**:
   - Log `settle_report` and `object_drift` into W3C PROV-O (`eval_telemetry.ttl`).
   - If drift $> 0.05\text{ m}$, trigger sector clearance shift. If lift fails, check language prompt and standoff.

---

## 9. Visual Verification Command

To visually observe the settled spawn and closed-loop rollout in Omniverse Kit:

```bash
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
  --check_settling \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/g1_tabletop_apple_to_plate/latest/g1_tabletop_apple_to_plate.yaml \
  --output_base_dir /workspaces/isaaclab_arena/eval_output/g1_tabletop_apple_to_plate
```

