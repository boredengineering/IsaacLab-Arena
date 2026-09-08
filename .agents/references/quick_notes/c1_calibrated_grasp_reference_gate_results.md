# C1 calibrated grasp — reference gate execution

Run: `20260908T030344Z`

## Outcome: blocked at native replay fidelity

The frozen align policy demonstrated useful reference-scene behavior, but the first historical native-action replay failed the predeclared fidelity limits. Calibration and controller development did not start. No failed gate was bypassed and no tolerance, physics setting, task threshold or model weight was changed.

## Frozen-policy reference control

- Checkpoint: `/models/isaaclab_arena/static_apple_tutorial/geometry_arms/align/checkpoint-5000`; recorded weight/configuration hashes rechecked successfully.
- Current reference factory: `galileo_g1_static_pick_and_place` with `g1_wbc_agile_joint`.
- Five completed episodes, simulator/placement seed 42; remote diffusion seed uncontrolled.
- **Two of five episodes passed the reference task gate.** This is a small-sample observation, not a calibrated success probability.
- The first successful episode visibly captured and transported the apple to the plate. Finger release was not visible before termination, so independent release certification remains false.
- Reference thresholds are those of the current reference factory: 0.05 m lift with one above-threshold step, followed by destination contact/velocity checks. These are not the C1/v32 0.015 m/five-step criteria; do not combine the two rates as one metric.
- The reference scene is reconstructed from the current factory. Exact historical recording-scene identity is not established by the HDF5 metadata.

## Native replay prerequisite

Selected calibration demonstrations: `demo_0`, `demo_1`, `demo_2`. Selected validation demonstrations: `demo_3`, `demo_4`. Only `demo_0` was replayed before the stop gate fired.

- Source: `/datasets/isaaclab_arena/static_apple_tutorial/arena_g1_static_apple_dataset_recorded.hdf5`.
- Native actions: 23D, replayed with `g1_wbc_agile_pink`; no fabricated 23-to-50D conversion.
- Collected all 155 steps with camera video, actual/reference state arrays and all runtime body-link poses.
- Terminations were disabled solely for full recorded-trajectory comparison, as documented before the run. Replay completion does not certify task success.
- Reference arrays were checked element-for-element against the original HDF5 numerical arrays after explicit selection of the singleton environment axis added by `EpisodeData.get_state`. No samples were discarded, shifted, resampled or truncated.
- Timestamps used by the comparator are derived from the recorded fixed timestep and post-step index, not invented observed wall-clock timestamps. Runtime XYZW convention was checked in the installed PhysX data source.

| Quantity | Maximum observed error | Predeclared limit | Result |
|---|---:|---:|---|
| Robot root position | 0.034342 m | 0.01 m | Fail |
| Robot root orientation | 0.033605 rad | 0.1 rad | Pass |
| Apple position | 0.163568 m | 0.01 m | Fail |
| Apple orientation | 2.047655 rad | 0.1 rad | Fail |
| Plate position | 0.000346 m | 0.01 m | Pass |
| Plate orientation | 0.020683 rad | 0.1 rad | Pass |
| Joint position | 0.334733 rad | 0.05 rad | Fail |

Robot position first exceeded its limit at zero-based step 9; apple position first exceeded its limit at step 51. The largest joint discrepancy was `left_hand_thumb_1_joint`; an early discrepancy also occurred at `left_knee_joint`. Video shows the apple slipping and remaining away from the plate, unlike the recorded final trajectory.

These observations motivate investigation of initial controller history, reset semantics, backend/version/gains and contact dynamics. They do **not** prove which factor caused the divergence. A stable plate does not establish equality of every relevant physical setting.

## Budget and gates

- Reference-policy attempts used: 5 of 5.
- Native replay attempts used: 1 of 5.
- Remaining selected replays: not run after the failure.
- Calibrated-controller development/validation episodes used: 0.
- Commissioning contact/frame probes used: 0 of the separately reserved probe budget.
- Grasp-frame parameters and contact/retention thresholds remain uncalibrated.
- Graph-attribution experiments: not started.

Proceed only after fixing reference validity, or explicitly revising the plan to obtain new provenance-complete reference trajectories under the current joint-control runtime. Do not quietly reinterpret a divergent replay as an exact historical reproduction.

## Artifacts and implementation

Artifact root: `/eval/isaaclab_arena/c1_calibrated_grasp/20260908T030344Z/`

- `reference_policy/manifest.json`, raw episode JSON and videos.
- `reference_video_audit.json`, `reference_success_candidate.png`.
- `replay_preregistration.json`, `reference_metadata.json`.
- `native_demo0/state_comparison.npz`, `native_replay.mp4`, `contact_sheet.png`.
- `native_demo0/validation.json`, `divergence_diagnostics.json`, `metadata_inspection.json`.
- `run_reference_policy.py`, `run_native_replay.py`, `validate_native_replay.py`: preserved execution/analysis harnesses.

New reusable numerical/metadata checks: `isaaclab_arena/agentic_environment_generation/dcrg/reference_validation.py`, with `isaaclab_arena/tests/test_dcrg_reference_validation.py`. Independent review found complex-input coercion and quaternion-underflow false-pass cases; regressions were added and both classes corrected, including boxed complex values and minimum-subnormal perturbations. The final focused regression run passed **463 tests**. These tests verify the helpers; the real replay remained a failure.

The corrected validator rechecked the saved float32 replay offline, writing `native_demo0/validation_recheck_v3.json` separately. All gate decisions and reported maximum errors remained unchanged. The original `validation.json` hash stayed `92f3461792a6e8cca991fe77046f4c49c2f2098356e6ae03f7381a8ac1d93a83`; no original evidence or simulation was rewritten/rerun for the correction.

Neo4j read-back and an identical retry verified `ReferenceValidationRun.id = c1_reference_validation:20260908T030344Z`, status `blocked_replay_fidelity`, linked by `REFERENCE_DIAGNOSTIC_FOR` to the exact v32 graph. Seventeen raw evidence artifacts are hash-bound in the record. This is prerequisite evidence, not an accepted controller trial or successful environment prior; the existing controller/XY retrieval methods do not automatically include this separate diagnostic label. See `graph_receipt.json` and the preserved `record_reference_evidence.py` harness.

The isolated align server was stopped after the gate failure. No simulator rollout remains active, and the original baseline server's health check passed.

Final independent verification found no remaining concrete validator blockers. It exercised complex/object rejection, subnormal quaternion differences and normal-angle cases with warnings treated as errors. This closes the software review; it does not change the failed T01 replay gate.

No commits or pushes were made. No calibration or successful C1 transfer is claimed.
