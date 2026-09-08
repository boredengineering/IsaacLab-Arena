# C1 controller-assistance experiment

## Research question

Can bounded runtime assistance transfer the frozen Spatial-Forcing G1 policy to the unseen C1/v32 scene? Test a downward arm residual, delayed finger commands, and their combination without changing the scene, physics, or success gates.

## Verified setup

- Scene: the existing **left-hand v32 baseline**, canonical hash `3442a766d74fdfe1f721d3a934ba93f289763f1e8329abd73b250e669d79ac3a`. This is not completion of the original catalog's right-arm C1 requirement.
- Checkpoint: `/models/isaaclab_arena/static_apple_tutorial/geometry_arms/align/checkpoint-5000`. Weight shards and model/processor configuration files were fingerprinted. The prior DCRG pilot served `geometry_arms/baseline`, not this align checkpoint.
- `geometry_mode=align` is training-time auxiliary RGB-feature alignment against DA3 features. Inference still uses RGB, joint state and language; it does not consume an online depth image.
- Prediction horizon 40, executed chunk 32; single environment and existing G1 joint-control/WBC backend. No mirror, retraining, physics change, scene movement, threshold relaxation or version promotion.
- Explicit `privileged_state_diagnostic`: assistance reads simulator object position and robot kinematics. This is not vision-only transfer.
- Pin `left_hand_middle_1_link`, explicitly a finger origin rather than a calibrated grasp centre.

## Completed results

Each row is one independent two-episode trial. Seeds control simulation/placement, **not** the remote diffusion process.

| Controller | Seed | Episodes | Height-dwell events | Placements |
|---|---:|---:|---:|---:|
| Observe-only / unassisted | 42 | 2 | 0 | 0 |
| Downward residual, 0.01 m | 42 | 2 | 0 | 0 |
| Finger gate, 0.4 s maximum | 42 | 2 | 1 | 0 |
| Residual + gate | 42 | 2 | 0 | 0 |
| Observe-only / unassisted | 7 | 2 | 0 | 0 |
| Finger gate, 0.4 s maximum | 7 | 2 | 0 | 0 |

**Total: 12 completed episodes; no placements.** One earlier interrupted smoke produced zero episodes and remains a failed artifact, excluded from scoring. A shell launch with an empty container variable never launched the simulator.

The height event preserves the original predicate: more than 0.015 m above the running resting reference for five consecutive steps. It is not contact-based proof of a retained grasp. In the gate/seed-42 episode, video shows the apple slipping/rolling away while the empty hand continues toward the plate. Do not promote that event as successful grasp transfer. The event did not recur on seed 7.

## What was learned

1. Active-hand commands really do change toward closure while the pinned link remains above the apple; measured fingers follow afterwards. The legacy bilateral mean-absolute joint metric was insufficient to establish this.
2. The bounded residual actually executed, rather than silently being disabled. The gate also changed executed commands while preserving the underlying scheduled arm motion.
3. All tested gate episodes released through the timeout, not geometric readiness. These runs therefore test bounded delay, not a validated geometry-aware release condition.
4. Fresh RGB checksums changed at every adjacent recorded policy step. This rules out wholly identical consecutive frames in these traces, not every possible observation-latency problem.
5. A 1 cm downward residual plus a short finger delay did not establish a retained grasp or placement. Small samples and uncontrolled diffusion prohibit a strong causal ranking of these settings.

A plausible next research design is calibrated grasp-frame control with coordinated arm/hand phase transitions, rather than another arbitrary offset: determine an actual grasp region, reach it, permit closure, verify retention, then hand transport back to the policy. This is a **proposal**, not implemented or proven by this batch. Compare graph-informed selection against a no-history baseline before attributing any future improvement to Graph-RAG itself.

## Graph and implementation

- Wrapper: `isaaclab_arena_gr00t/policy/gr00t_assisted_policy.py`; pure controller core: `g1_hand_assistance.py`.
- The wrapper clones scheduled actions. It changes only the selected arm/fingers, not cached chunks, inactive joints or WBC command tail.
- Residual: world-frame damped least squares, applied to the policy's absolute arm targets (not accumulated), with joint/soft-limit/slew checks, bounded approach window and one-second active interval. Rejections/timeouts restore the base command and report discontinuities; bounds are not collision guarantees.
- Gate: initial **post-settle measured** finger reference; first command-deviation trigger; at most 0.4 s including a 0.1 s authority-restoration ramp. Readiness latches; it does not repeatedly reopen a grasp.
- Keep the base GR00T lifecycle flag: `is_remote=True` selects the runner's managed-server shutdown API, which this independently served client does not implement. A regression test guards the corrected behavior.
- `dcrg/controller_graph.py` stores immutable controller contracts and same-scene trials. Do not encode these as apple-XY `EVOLVES_TO` proposals.
- Retrieve with `GraphRAGRetriever.retrieve_controller_trials('g1_tabletop_apple_to_plate', checkpoint_identity, experiment_id='c1_align_assistance_20260908')`.
- Live Neo4j read-back verified six trials, four controller variants, twelve episodes, every registered artifact/source hash, an unchanged identical retry, and rejection of conflicting controller attribution.
- Trials were selected by the agent and read back through Graph-RAG. There is no new autonomous controller-parameter optimizer or automatic LLM routing.

## Verification and artifacts

191 focused regression tests passed in the non-root simulator container. Black, isort/flake8 checks and documentation verification accompany the changes; the full three-phase simulation suite was not run. An independent review supported rollout readiness but missed the lifecycle issue subsequently caught and regression-tested by the parent.

Artifacts: `/eval/isaaclab_arena/dcrg_c1_assistance/20260908/`

- `summary.json`: completed/failed trial summaries and episode diagnostics.
- `graph_verification.json`: exact graph identities/counts and immutability checks.
- `checkpoint_fingerprint.json`: actual checked checkpoint files and digests.
- `controller_comparison.png`: first-episode command/measurement/geometry curves.
- `gate_lift_contact_sheet.png`, `gate_visual_review.json`: qualitative audit of the height event.
- `trials/<name>/`: immutable controller config/contract, rollout manifest/log, raw episode JSON, active-hand trace, reach trace and per-episode camera videos.
- `run_trial.py`, `summarize.py`: execution and aggregation harnesses; the run harness requires the verified align server on port 5565. Use a new trial name; never overwrite an old trial.

No commits or pushes were made. No unsuccessful controller was promoted.
