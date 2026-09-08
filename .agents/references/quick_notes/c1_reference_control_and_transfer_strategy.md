# C1: reference controls before further environment search

**Status:** Evidence-led recommendation. The recorded DCRG pilot did not achieve C1 success. This note does not authorize a new rollout, policy change, or training run.

Current implementation documentation:
- [DCRG architecture](../../../docs/pages/concepts/dcrg.rst)
- [DCRG runbook and measured pilot](../../../docs/pages/example_workflows/agentic_env_gen/dcrg.rst)

## Main recommendation

Retain **v32 as a frozen comparison baseline**, not as a presumed solution. Do not simply rerun it expecting the new DCRG implementation to improve the robot. DCRG improves experiment control, evidence preservation, and acceptance/rejection; it does not add grasping capability to the frozen policy.

Before another placement search, separate three questions:
1. Is the checkpoint capable of the reference behavior?
2. Is the deployment/observation/action contract correct?
3. Does the policy transfer from the reference scene to C1?

## What our recorded evidence establishes

- The local `geometry_arms/baseline` checkpoint produced **0/4 placements and 0/4 sustained lifts** on the fresh v32 baseline, across simulation/placement seeds 42 and 7.
- The bounded XY candidate also produced **0/4 placements and 0/4 sustained lifts** and was rejected.
- In an older saved v32 run, the reported **7/20 lifts** counted peak excursions; completed sustained-lift events supported **5/20**. Do not mix these definitions.
- A named hand-link origin above the apple is not automatically a grasp-centre error. A finger-base link can legitimately be above the object during a grasp; calibrate against a successful reference using the same frame.
- These small screening trials do not establish that v32 can never work, but they do not justify a larger blind XY search either.

Version semantics matter: `latest` points to the most recently created numbered configuration, v35. The recorded DCRG experiment retained its v32-derived baseline after rejecting a candidate. Neither pointer proves a globally best or successful environment.

Recorded artifacts: `/eval/isaaclab_arena/dcrg_c1/20260907/`. These are workspace-local evaluation artifacts, not repository-shipped data. The initial closed-loop state predates Kit-argument contract hardening; preserve it as history rather than inventing missing provenance to resume it.

## What external evidence supports

### Establish a genuine positive control

NVIDIA documents the released `nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace` checkpoint on `galileo_g1_static_pick_and_place`, using the joint-control G1 embodiment. Its guidance explicitly requires the served model and client configuration to agree.[1]

Our tested server used a local checkpoint path. Verify its provenance and fingerprint rather than assuming it is equivalent to, or worse than, the released checkpoint.

### Preserve the training/serving interface

NVIDIA's G1 guidance emphasizes matching modality configuration and trained action horizon. It uses the PinkIK embodiment during recording and the joint-control twin for evaluation. The trained prediction horizon is not interchangeable with the number of predicted actions executed before replanning.[2]

Do not arbitrarily change action units or gripper ranges based on a forum example for another embodiment. Verify the actual checkpoint's action contract first.

### Treat scene transfer as an unproven capability

LIBERO-PRO reports substantial sensitivity to object/layout perturbations in the VLA models it evaluates.[6] Camera-conditioning research finds that ACT, Diffusion Policy, and SmolVLA can exploit background cues for camera pose and fail when those cues change.[8]

These studies identify plausible mechanisms worth testing. They do **not** establish the cause of this G1 failure, nor demonstrate a drop-in fix for C1.

### Establish the basic behavior before sophisticated chunking

In the GR00T real-time-chunking discussion, contributor `youliangtan` says the synchronous behavior-cloning policy should work first; asynchronous execution and RTC are subsequent rollout optimizations.[3]

This supports diagnosing the basic grasp before treating chunking changes as the primary remedy. The discussion concerns an earlier GR00T implementation; its configuration snippets should not be copied into the current runtime without compatibility checks.

## Recommended crossed comparison

Use compatible checkpoint-specific modality settings and consistent audited outcome definitions:

| Checkpoint | Reference scene | C1 / v32 |
|---|---|---|
| Verified released checkpoint | Positive control | Transfer test |
| Current local checkpoint | Checkpoint control | Existing baseline |

Fingerprint the checkpoints first. If they are identical, eliminate that redundant comparison. Reuse existing results only when their contracts and provenance match.

### Decision rules

- **Released checkpoint fails on the reference scene:** Stop C1 search. Investigate runtime compatibility, observation preprocessing, action mapping, resets/settling, and scoring.
- **Released checkpoint works but the local checkpoint fails on the reference scene:** Investigate the local checkpoint or training configuration before moving the table or apple.
- **Both work on the reference scene but fail on v32:** Prioritize scene-transfer diagnosis: camera/posture, robot-relative layout, and grasp geometry.
- **Released checkpoint works on v32 but the local checkpoint does not:** Keep v32 and address checkpoint selection or adaptation.

The reference scene's reported success must be audited too. NVIDIA's example uses contact-based termination, so its illustrative success output is not directly comparable with our stricter lift-before-place and placement checks.[1]

## Measure the failure before choosing the intervention

Compare successful reference grasps with C1 using:
- The same explicitly named hand frame and a calibrated grasp reference.
- Commanded versus measured finger joints for the active hand.
- Finger closure timing relative to object contact.
- Fresh camera observations and measured camera/robot posture.
- Separate stages for grasp acquisition, sustained lift, transport, and placement.

Choose the remedy from those measurements:

1. **Proven calibration/mapping mismatch:** Correct that mismatch and run a controlled A/B.
2. **Proven timing problem:** Test execution timing without changing the trained action horizon.
3. **Genuine transfer limitation:** Consider target-scene demonstrations with meaningful layout/view variation and evaluate policy adaptation. NVIDIA provides the applicable G1 post-training workflow.[2]

The recommendation to favor a demonstrated adaptation path over additional graph machinery or an untested auxiliary loss is an engineering judgment, not a measured guarantee. A fixed number of demonstrations should not be promised sufficient; use a learning curve and held-out layouts.

DCRG should record the hypotheses, intervention contracts, observations, and rejected trials. It should not assume every failure is an object-placement error.

## Success expectations and evaluation discipline

There is no defensible probability of C1 success from the current evidence. Confidence in **v32 plus more blind XY search** is low. The crossed comparison is recommended because it distinguishes competing causes, not because success is guaranteed.

If the problem is genuine transfer, reliable C1 performance may require policy adaptation rather than environment-only changes. If policy adaptation is out of scope, acknowledge that limitation instead of changing physics or weakening success thresholds.

Four episodes are screening evidence, not a robustness result. A GR00T contributor reported high variance even with ten episodes; NVIDIA's G1 evaluation guide recommends larger complete-episode samples for estimating success rate.[9][1] Expand the evaluation budget after a repeatable grasp improvement appears, not before basic faults are localized.

The original C1 catalog explicitly requests the right arm. The recorded pilot is an existing **left-hand baseline**. Resolve the intended arm contract before claiming C1 completion; do not silently equate the two.

## Sources

Sources include official NVIDIA documentation, primary research, and attributable developer discussion. Developer comments provide diagnostic guidance, not proof that a fix will work on this checkpoint and scene.

[1] https://docs.nvidia.com/learning/physical-ai/gr00t-e2e-workflow/latest/simulation-workflow/sim-evaluation.html
[2] https://docs.nvidia.com/learning/physical-ai/gr00t-e2e-workflow/latest/simulation-workflow/groot-fine-tuning-sim.html
[3] https://github.com/NVIDIA/Isaac-GR00T/pull/320
[6] https://arxiv.org/html/2510.03827v2
[8] https://ripl.github.io/know_your_camera
[9] https://github.com/NVIDIA/Isaac-GR00T/issues/251

Specific developer comments consulted:
- Synchronous policy before RTC optimization: https://github.com/NVIDIA/Isaac-GR00T/pull/320#issuecomment-3264745479
- Evaluation variance with small episode counts: https://github.com/NVIDIA/Isaac-GR00T/issues/251#issuecomment-3063270522
