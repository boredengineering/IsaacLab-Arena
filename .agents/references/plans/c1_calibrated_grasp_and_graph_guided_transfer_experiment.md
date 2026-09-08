# C1 Calibrated Grasp and Graph-Guided Policy Transfer Experiment

Status: execution started and blocked at native replay fidelity (T01). The reference policy completed five episodes with two task-gate successes; the first native replay failed the predeclared state-error limits. Calibration and controller development have not started. No changes to task physics, success thresholds, model weights, or the right/left-arm contract are authorized. This is not successful C1 transfer.

## Original proposed plan

Establish that calibrated, coordinated assistance can produce a retained grasp, then separately test whether Graph-RAG helps select that assistance. A successful scripted controller alone would not establish Graph-RAG-driven policy transfer.

### 1. Freeze the experiment contract

Use `geometry_arms/align/checkpoint-5000`, without retraining, on the existing left-hand v32 baseline. Preserve the robot, camera, physics, joint-control/WBC backend and task gates. Initially use simulator object poses, explicitly labelled privileged-state assistance; perception-based pose estimation is a later stage.

Primary hypothesis: a calibrated object-relative grasp pose combined with coordinated arm/finger transitions improves retained grasp and placement compared with the frozen policy alone.

### 2. Establish a reference and calibrate the grasp

Run the checkpoint on `galileo_g1_static_pick_and_place` with its joint-control embodiment, not the environment's default PinkIK configuration. Identify verified successful reference demonstrations; use three successfully replayed demonstrations for calibration and two disjoint demonstrations for validation.

Measure a rigid palm/wrist frame, its pose relative to the apple at stable grasp, finger configuration, approach orientation, support clearance, and object motion relative to the hand. Produce an object-relative grasp pose and tolerances, not a guessed vertical offset. Preserve distinct grasp modes instead of averaging incompatible orientations.

Stop if reference behavior cannot be reproduced. Resolve checkpoint/replay/interface problems before claiming an unseen-environment transfer experiment.

### 3. Implement coordinated phases

`POLICY APPROACH -> ALIGN -> CLOSE -> VERIFY RETENTION -> HAND BACK`

- Approach: the model controls motion; the supervisor detects approach/grasp intent.
- Align: suspend normal action-chunk consumption, keep the hand open, and use bounded position/orientation control toward the calibrated grasp pose.
- Close: hold the grasp pose, close progressively, and require tracking and appropriate hand-object contact.
- Verify retention: perform a small bounded lift and check capture relative to the hand, not merely a bounce or roll.
- Hand back: discard the old chunk, request a fresh prediction from current observations and blend back to policy control for transport/placement.

A timeout records a phase failure; it must not automatically permit closure. Keep WBC active. Never attach the apple, teleport joints or bypass contact physics.

### 4. Component ablations

- A: frozen policy alone.
- B: calibrated spatial correction only, retaining policy finger timing.
- C: coordinated timing only, without spatial retargeting.
- D: calibrated spatial correction plus coordinated phases.

Initially run three episodes per condition. Freeze configurations before validation. The operational definition of timing-only needs refinement to avoid a deadlock/straw-man baseline.

### 5. Measurements

Preserve original task success and add separate diagnostics for retained grasp, transport and placement. Proposed retention measurement: stable capture over a 0.3-second hold, appropriate gripping-surface contacts, stable object-to-hand relation, and no continuing support contact. This hold duration is a design proposal, not a calibrated threshold.

Record pose/orientation error at closure; raw/executed/measured joints; phase transitions and reasons; contact pairs; intervention duration/magnitude; and retention after fresh-inference hand-back.

### 6. Validation and provisional budget

Compare the strongest assisted condition against unassisted policy on ten matched cases each, including original v32 and predeclared feasible apple-position perturbations. Each changed scene receives a new immutable version. Report familiar-pose repeatability separately from held-out layouts; new seeds alone do not establish layout generalization. Remote diffusion is currently unseeded.

| Stage | Maximum episodes/replays |
|---|---:|
| Reference-policy control | 5 |
| Calibration/validation replay | 5 |
| Four development conditions, three episodes each | 12 |
| Assisted/baseline validation, ten each | 20 |
| Initial-stage ceiling | 42 |

Stop early when prerequisites fail. This is a feasibility budget, not a statistical-power justification. Sensor-debugging runs and a later Graph-RAG attribution experiment require separate accounting.

### 7. Graph-RAG attribution

Store calibrated grasp relations, applicability constraints, controller contracts and phase-specific failures. Once control is useful, compare graph-informed selection with the same controller using no-history search. Match parameter bounds, observations and evaluation budgets; freeze starting knowledge and prevent validation leakage. Evaluate placement success per evaluation budget across held-out layouts.

## Research refinement

The original proposal above is retained for context. The refinements below and [the test protocol](c1_calibrated_grasp_test_protocol.json) govern execution.

### Research-supported likelihood assessment

There is no defensible numerical probability of success for this exact checkpoint, scene and controller combination. The first engineering milestone is plausible; complete policy transfer and a measurable Graph-RAG advantage remain high-uncertainty research.

- **Calibrated simulation grasp with simulator poses:** plausible, conditional on correct frame calibration, replay and contact verification. MimicGen supports object-relative reuse of demonstration trajectories, but generates success-filtered demonstrations for learning; it does not establish that a frozen externally corrected G1 policy will resume successfully.[1]
- **Handover to the frozen policy:** substantially more uncertain. Residual Reinforcement Learning optimizes the combined controller during learning; our hand-designed supervisor and frozen policy have not received that coordination training.[2]
- **Action-chunk continuity:** fresh observations are necessary but do not guarantee compatible continuation. Real-Time Chunking coordinates chunks through committed-prefix conditioning; simple flushing/blending is not RTC and does not inherit its empirical results.[3]
- **Graph-RAG benefit:** unproven. Successful controller execution or graph writes alone do not demonstrate improved adaptation efficiency.
- **Vision-estimated poses:** a separate later challenge. Privileged simulator-pose success must not be called vision-only transfer.

The decisive early question is whether the supervisor establishes a verified grasp and the frozen policy retains it after handover. If capture succeeds but resumption drops the object, classify a handover/adaptation failure; do not respond by blindly searching more grasp offsets. Prior fixed-offset/delay failures did not test this calibrated, coordinated mechanism.

### Assumptions and prerequisite checks

| Assumption | Current evidence | Required check / failure action |
|---|---|---|
| Reference demonstrations are suitable for calibration | LeRobot contains joint/EEF data but not object poses or a complete physical scene. Original HDF5 includes object/root trajectories. | Use original HDF5; verify provenance and actual replay, not terminal rewards. Missing historical scene provenance may be reconstructed and labelled as such, never claimed exact. |
| Action replay matches the deployment interface | Sampled HDF5 has 23D native actions and 43D processed targets; current joint/WBC deployment is 50D. | Keep native replay and translated joint replay separate. Validate order, units, tail and sample alignment; do not pad arbitrary zeros. |
| Recorded success labels are reliable | The LeRobot converter sets terminal reward/done unconditionally; HDF5 success is a historical label. | Independently inspect actual grasp/placement, active predicates and state errors. Replay completion is not success. |
| A rigid calibration frame exists and is exposed | The current assistance wrapper is restricted to an articulating finger link. A separate simulator USD supplies the robot. | Resolve the actual rigid wrist/palm frame; verify finger-motion invariance, quaternion order, FK/Jacobian and common-world-transform invariance. |
| Existing contact telemetry measures grip | The task's existing apple contact sensor is filtered against the plate. | Add separately validated hand/support diagnostics without changing plate scoring. Unknown channels cannot certify retention. |
| Policy chunks can be paused safely | The current scheduler consumes one action per call and ignores its hold argument. | Add/test explicit action ownership, local invalidation and fresh-observation resumption; preserve WBC/tail and episode clock. |
| The phase sequence fits the task horizon | Settling consumes the existing six-second episode clock. | Measure remaining simulation steps and phase costs. No clock reset or silent extension; report wall-clock inference latency separately. |
| Reference success transfers to C1 | Not established for this checkpoint in the calibrated protocol. | Run the bounded reference control before attributing C1 failure specifically to unseen-scene transfer. Zero successes in a small batch blocks progression but does not prove incapability. |

Local evidence: `isaaclab_arena_gr00t/lerobot/convert_hdf5_to_lerobot.py:441-447`, `isaaclab_arena/tasks/pick_and_place_task.py:117-125`, `isaaclab_arena/policy/action_scheduling/action_chunk_scheduler.py:64-108`, and `isaaclab_arena/scripts/imitation_learning/replay_demos.py:134-136,215-228`. Historical results remain in [the assistance report](../quick_notes/c1_controller_assistance_results.md).

### Operational refinements

1. **Reference gate first.** Native demonstration replay validates the recording/interface; a separate frozen-policy reference run tests the checkpoint. Record state mismatches as failures even though the existing replay utility only prints them. The replay utility disables task terminations, so it cannot alone certify completion under the scored task contract.
2. **Retargeting and coordination are distinct factors.** In coordination-only condition C, wait for measured tracking of the policy-selected arm goal rather than requiring an unreachable calibrated target while refusing to retarget. Condition D uses the calibrated goal. Coordination includes scheduler ownership and phase transitions, not just a finger delay.
3. **Independent observer.** Preserve original task success and additionally report audited retained grasp, transport and release. Use partner-resolved contacts plus relative object/hand motion; retain negative controls for support, touch, tilt, bounce and release. Derive thresholds from calibration only.
4. **Explicit handover.** No pre-intervention cached action may execute after handover. Preserve the last valid WBC tail while the supervisor owns the arm/hand. Use synchronous inference initially, as in the baseline; do not quietly add asynchronous execution. A fresh prediction that opens/releases the apple is a measured handover failure, not a successful transfer.
5. **Budget and stopping.** Follow the protocol's 42 task/replay-attempt ceiling and separately capped commissioning probes. Failed/interrupted attempts consume budget. Missing calibration values block development. No repeated trials merely to obtain a desired result.
6. **Hold-out discipline.** Freeze controller settings and validation cases before development. Original-pose repeatability and held-out layouts are separate results. Tiny samples support feasibility decisions, not a calibrated probability or robust generalization claim.
7. **Graph attribution later.** Compare relational retrieval, flat retrieval containing the same facts, and no-history search with matched controller/proposer/bounds/budgets. Isolate memory updates between methods and keep test outcomes out of search memory. This study is outside the initial feasibility budget.

### Execution records

Run `20260908T030344Z`: five reference-policy episodes completed, with two reference task-gate successes. Video confirms retained transport in the first successful episode but not independent release. Native `demo_0` replay completed 155 steps and failed the fixed fidelity limits: robot position error 0.034342 m, apple position error 0.163568 m, apple orientation error 2.047655 rad, and joint error 0.334733 rad. The plate stayed within tolerance. Calibration and downstream controller tests are blocked; no limits were loosened and no further replay was launched.

See [the reference gate execution report](../quick_notes/c1_calibrated_grasp_reference_gate_results.md). Raw artifacts: `/eval/isaaclab_arena/c1_calibrated_grasp/20260908T030344Z/`. The test protocol contains the execution summary. Proposed tests are not considered passed because their specifications or unit-test scaffolds exist; 463 helper/regression tests passing does not override the real replay failure. Review-driven fixes for invalid complex inputs and quaternion underflow were followed by an offline recheck (`native_demo0/validation_recheck_v3.json`): all gate decisions remained unchanged and the original evidence was preserved.

The blocked prerequisite is also stored in Neo4j as `ReferenceValidationRun.id = c1_reference_validation:20260908T030344Z`, with exact read-back and idempotent retry verified. Retrieve this diagnostic separately; it is not an accepted `EVOLVES_TO` refinement or controller-trial success.

Sources:
[1] https://ar5iv.labs.arxiv.org/html/2310.17596
[2] https://ar5iv.labs.arxiv.org/html/1812.03201
[3] https://arxiv.org/html/2506.07339v1
