# Debug Record: Why the G1 Grasps Air on `g1_tabletop_apple_to_plate`

> [!IMPORTANT]
> **Status**: ACTIVE, 2026-09-05. Detail companion to the canonical tracker
> [`g1_pick_success_phases.md`](g1_pick_success_phases.md). This file records the *diagnosis and the
> method that produced it*, because three separate sessions re-derived the same facts from scratch
> and two of them drew wrong conclusions from correct data.

**Symptom**: the robot approaches the apple, closes its hand, and comes up empty; occasionally it
strikes the apple and knocks it across the table. Under honest scoring, success is 0/10.

---

## 1. The diagnosis

> [!NOTE]
> **Read §4.5 first for the confirmed mechanism.** §1.1 (no depth input) and §1.5 (execution horizon)
> are both confirmed by measurement. §1.2–1.3 — camera pitch as *the* cause — was the working
> hypothesis and is only **partly** borne out: the pitch mismatch is real and measured, but both
> attempts to correct it failed structurally (§4.2, §4.3), and the direct measurement (§4.5) locates
> the failure as a **vertical range error with accurate bearing**, of which ~7 cm survives after all
> staleness is removed (§4.7). Do not re-litigate camera pitch expecting it to be the whole story.

### 1.1 The policy has no depth input — confirmed at two levels

| Level | Evidence |
| :--- | :--- |
| Modality config | `g1_sim_wbc_data_gr00t_n_1_7_config.py:15` — `video: ModalityConfig(modality_keys=["ego_view"])`. One RGB stream. |
| Sensor | `isaaclab_arena/embodiments/g1/g1.py:497` — `data_types=["rgb"]`. Depth is not even rendered. |

So distance to the apple is not measured; it is **inferred monocularly** from apparent size,
position in frame, and surface perspective. That inference is only valid if the camera views the
scene the way it did during training.

### 1.2 The camera does not view the scene the way it did during training

The scene spec overrides the robot's starting posture. The corpus environment does **not**:

| Joint | `v25` spec | Corpus (`g1.py:260-266` defaults) |
| :--- | ---: | ---: |
| `left_shoulder_roll_joint` | 0.25 | 0.0 |
| `right_shoulder_roll_joint` | −0.25 | 0.0 |
| `left_shoulder_yaw_joint` | 0.5 | 0.0 |
| `right_shoulder_yaw_joint` | −0.5 | 0.0 |
| **`waist_pitch_joint`** | **0.2** | **0.0** |

`waist_pitch_joint` tilts the torso, and the head camera rides on `head_link` above it, so ~0.2 rad
of waist pitch rotates the camera by roughly 11°. Both scenes share the same camera *offset*
(`_DEFAULT_G1_CAMERA_OFFSET`, `g1.py:105`), so nothing in the camera config reveals this — the
divergence is entirely in the robot's pose.

This is what the depth audit measured back on 2026-09-02 and nobody acted on
(`eval_output/g1_tabletop_apple_to_plate/depth_audit_v7_c1.json`):

```
object_vertical_pixel_delta   : -0.2687   (apple 27% of frame height HIGHER in sim)
object_horizontal_pixel_delta : +0.4422   (apple 44% of frame width further RIGHT in sim)
surface_slope_sign_flip       : true
diagnostics: "CRITICAL: Camera pitch slope sign is inverted! Simulation camera is looking
              level/upward across table, whereas demonstration was looking steeply down
              onto support surface."
```

### 1.3 Why this specifically causes grasping air

The metric layout is *already* close to the corpus:

| | corpus | target (`v25`, seed 1) |
| :--- | ---: | ---: |
| base → apple, horizontal | 0.3795 m | 0.3640 m |
| base → plate, horizontal | 0.3291 m | 0.3029 m |
| apple, relative to base | (+0.3285, +0.19) | (+0.3268, +0.1603) |

So the object is in the right *place*; the camera is at the wrong *angle*. For a policy with no
depth channel, **image position is the depth estimate**. Tilt the camera and the same physical
apple projects to a different pixel, so the policy reaches to where a corpus apple at that
apparent position would have been — short of, or above, the real one. It then closes on air.

This is a **geometric** distribution violation, not a photometric one. It is a fourth violation
alongside the three `P1` catalogued (mirror, chunk length, prompt), and it is the only one that
moves the camera.

### 1.4 Corroboration from outside this repo

- [Isaac-GR00T #210](https://github.com/NVIDIA/Isaac-GR00T/issues/210) — the identical symptom:
  the arm "moving to a position above the target object and stopping without completing the pick".
- [Modality-Augmented Fine-Tuning, 2025](https://arxiv.org/html/2512.01358v1) — the GR1 corpus has
  RGB + proprioception but no depth or contact, so the policy must infer contact boundaries "purely
  from color imagery — an ill-posed problem"; their remedy is synthesising metric depth (ZoeDepth)
  to give RGB-D.
- [StereoPolicy](https://arxiv.org/pdf/2605.09989) — RGB-only policies "approach the target but
  fail to insert the gripper accurately"; stereo fixes gripper-to-target alignment.
- [Isaac-GR00T #652](https://github.com/NVIDIA/Isaac-GR00T/issues/652) — whether N1.5/1.6/1.7 can
  take depth at all is an open question upstream. NVIDIA's *GR00T-Dexterity* stack does use depth.

### 1.5 The execution horizon is about twice what it should be

N1.7 renamed `--action-horizon` to `--execution-horizon` to separate two things the config conflates:

| Knob | Meaning | Ours | Should be |
| :--- | :--- | ---: | ---: |
| `action_horizon` | steps the model *predicts* | 40 | **40** — trained value and N1.7's `max_action_horizon` |
| `action_chunk_length` | steps *executed* before replanning | 16 | **8**, then sweep 4–16 |

NVIDIA's own examples, including `gr00t/eval/open_loop_eval.py`, use `--execution-horizon 8`. An
ablation on the same flow-matching DiT family (LIBERO-10) peaks at **n_act = 5 (93%)** and collapses
to 77% at n_act = 1 from replanning noise, so the optimum is short but not minimal.
[Issue #272](https://github.com/NVIDIA/Isaac-GR00T/issues/272) reports the too-long failure mode:
"the manipulator returning a few steps back every time I receive the new action horizon". At 50 Hz,
16 steps is **320 ms of blind motion** — ample for a 34 mm-radius apple to be missed.

---

## 2. How to debug this class of problem (the part worth remembering)

Three sessions re-derived these facts. What actually worked, and what misled:

### 2.1 Methods that found real things

1. **Read the config against the corpus, field by field.** Every violation found so far — mirror,
   chunk length, prompt, and now posture — was visible by diffing the scene/policy config against
   what the reference environment does. No simulation required.
2. **Render the observation the policy actually receives, and look at it.** The head-cam render
   beside a corpus dataset frame shows the framing mismatch in seconds. `render_env_camera.py`
   plus `dataset_ep0_frame_*.png`.
3. **Ablate inputs against the policy's own sampling-noise floor.** A delta is meaningless in
   absolute terms; as a multiple of the noise from re-drawing the flow-matching seed it is
   interpretable. `probe_policy_modality.py`.
4. **Dose-response beats a single contrast.** Move one thing across several values and measure the
   slope. Two points gave a misleading "12% tracking"; a sweep gives a number worth quoting.
5. **Measure thresholds from the geometry, never assert them.** `min_lift_height` was 0.05 m
   against a peak-ever lift of 0.0195 m — mathematically unreachable. `max_destination_xy_separation`
   was 0.10 m against a measured plate radius of 0.0755 m — larger than the plate.

### 2.2 Mistakes that cost time, and their antidotes

| Mistake | Antidote |
| :--- | :--- |
| Reading **pooled** peaks across all episodes as typical behaviour. "Peak lift 0.0278 m" was the best moment of the best episode; 6 of 9 episodes barely touched the apple. | Always tabulate **per episode** before claiming a behaviour. |
| Trusting a **stale artefact**. A `v8` head-cam render suggested "robot too far"; the metric distances disproved it. | Re-render at the version under test. Date-check every artefact. |
| Believing a **headline metric** whose threshold was never checked. `object_moved_rate` uses 0.5 m/s and read 0.0 through an entire campaign of real progress. | Verify a metric fires on the behaviour it claims to score. |
| Trusting `overall_score`. The progress funnel scored a *weaker* condition than the success gate, so it reported 1.000 alongside `success=False`. | Build progress objectives and the termination gate from the **same** predicates. |
| Comparing runs with **unseeded object placement**. `placement_seed` defaults to None, which makes the RNG generator None, which falls through to the unseeded global RNG. | Pass `--placement_seed` on every evaluation. An unseeded eval is not a measurement. |
| Believing a **plan document** over the code. The tracker asserted P2(a) complete when only its preconditions had been checked. | Re-verify claimed-done work before building on it. |
| Promoting a **diagnostic proxy** to a result. The hand-to-apple vertical distance improved 38% while lifts and successes stayed at zero — the proxy is not the task. | State the task-level endpoint alongside any proxy, and refuse to call a proxy change an improvement. |
| Comparing arms at **n = 6** against a 1-in-10 base rate, where P(zero events) ≈ 0.53. | Power the comparison before running it: n ≥ 30 per arm for a ~10% endpoint. |

### 2.3 Instrumentation gaps still open

- **The reach tracer logs only the manipuland.** Hand/wrist position is not recorded, so
  "reached the wrong place" cannot be decomposed into horizontal versus vertical error. **If XY
  converges but Z does not, that is depth, definitively.** This is the single most valuable missing
  measurement.
- **No region-wise visual ablation.** Whole-image scrambling shows the policy uses vision; it does
  not show that it *localises the apple*. Occluding the apple's bounding box versus an equal-area
  control patch elsewhere would, with a paired test over frames.

---

## 3. Fix sequence

Each step changes one thing, because two of the confounds above came from bundling.

| # | Change | Rationale | Status |
| :-- | :--- | :--- | :--- |
| F1 | Remove the `initial_joint_pos` override so posture (and therefore camera pitch) matches the corpus | §1.2 — the only violation that moves the camera | see run log |
| F2 | Validate F1 *before* evaluating: render the head cam and re-run the depth auditor against a corpus frame; require `surface_slope_sign_flip: false` | Cheap, and it fails fast if the pitch did not actually change | see run log |
| F3 | `action_chunk_length: 16 → 8` | §1.5 — separate run, not bundled with F1 | ⚠️ **applied to `v25` but UNVALIDATED**: proxy −38%, task unchanged at 0 lifts / 0 successes (§4.6) |
| F4 | Log wrist/hand position in `ReachTracer`; decompose hand→apple error into XY and Z | §2.3 — turns "grasps air" into a measurement | ✅ **done — diagnostic** (§4.5) |
| F5 | Region-occlusion ablation with a control patch | §2.3 — only if F1–F4 do not settle it | ❌ **unnecessary**: F4's 1.7 cm horizontal accuracy already proves the apple is localised |
| F6 | Derive fixture `Z_deck` from the fixture bounding box instead of the `FIXTURE_SECTOR_BOUNDS` constant | §4.3 — blocks any fixture-height change, and fails destructively | **open, recommended** |
| F7 | RGB-D: synthesise metric depth for the corpus and re-finetune with a depth channel | §1.4, §4.5 — the only intervention that addresses a 13 cm range error | **open, the real fix** |

**That is what happened.** F1 and F2 both failed structurally (§4.2, §4.3) and F4 then measured the
mechanism directly (§4.5): bearing is right, range is wrong by 13 cm. Monocular RGB cannot resolve
the grasp height in this scene, so the honest options are synthesised depth (RGB-D finetune, §1.4)
or new demonstrations — **not** photometric alignment, and not further spec tuning.

---

## 3b. Run index — output directory is NOT the spec version

> [!CAUTION]
> **Output directories were named after the experiment, not the spec.** `v24_pinnedlayout` and
> `v28_handtrace` have **no matching spec directory**; pointing `--env_graph_spec_yaml` at
> `generated_envs/.../v24/` fails with "Env graph spec YAML not found". Use this table.

| output dir | spec + policy_config | `--placement_seed` | episodes | code state |
| :--- | :--- | ---: | ---: | :--- |
| `v24_pinnedlayout` | **`v23`** | 42 | 10 | before funnel alignment — its 1.000 is a false positive |
| `v25_honest_baseline` | `v25` (chunk 16) | 1 | 10 | before funnel alignment |
| `v27_raised_table` | `v27` (table +0.101 m) | 1 | 10 req / 20 recorded | after alignment; objects ejected (§4.3) |
| `v28_handtrace` | **`v25`** (chunk 16) | 1 | 6 | after alignment + hand tracing |
| `v29_chunk8` | `v29` (chunk 8) | 1 | 6 | after alignment + hand tracing |
| `v30_chunk4` | `v30` (chunk 4) | 1 | 6 | after alignment + hand tracing |

**Numbers from runs marked "before funnel alignment" will not reproduce**, because the progress
objectives now use the same predicates as the termination gate. The *behaviour* reproduces; the
score is stricter. `v24`'s `overall_score: 1.000` specifically cannot recur — it was the
contact-only place stage firing, which the alignment removed.

Spec versions that exist: `v1`–`v10`, `v12`, `v15`–`v17`, `v19`, `v20`, `v22`, `v23`, `v25`–`v27`,
`v29`, `v30`. There is no `v11`, `v13`, `v14`, `v18`, `v21`, `v24` or `v28`.

**Lesson**: name the output directory after the spec version it runs, or record the mapping at the
time. A run whose inputs cannot be identified is not evidence.

### 3b.1 Two invocation traps that waste a full run

**Registered environments use a subcommand, and argument order matters.** The environment name is a
subparser (`dest="example_environment"`, `isaaclab_arena_environments/cli.py:168`), so **every
main-parser argument must come before it**; only the environment's own flags (`--embodiment`, and
anything generated from its cfg dataclass) may follow. Putting `--output_base_dir` after the
subcommand exits with a bare `SystemExit: 2` whose argparse message is swallowed by the Kit
launcher, so the log shows a traceback with no cause.

```bash
# WRONG -- --output_base_dir after the subcommand -> SystemExit: 2, no message
... --remote_port 5557 galileo_g1_static_pick_and_place --embodiment g1_wbc_agile_joint \
    --output_base_dir eval_output/x

# RIGHT -- everything main-parser first, subcommand and its own flags last
... --remote_port 5557 --output_base_dir eval_output/x \
    galileo_g1_static_pick_and_place --embodiment g1_wbc_agile_joint
```

**`--remote_host` / `--remote_port` are not optional in practice.** Omitting them silently defaults
to `localhost:5555` and fails with `ConnectionError: Cannot reach GR00T policy server` — the server
in this setup is on **5557**.

When a run dies early, `grep -vE "^2026|OmniHub|omni\.|carb\.|rtx"` on the log strips the Kit
warning flood and leaves the actual error. Without that filter the cause is invisible.

### 3b.2 The corpus and target scenes are scored by different gates

`galileo_g1_static_pick_and_place` sets **none** of the success-gate parameters, so it inherits
`PickAndPlaceTask` defaults; the target scene overrides them. Any corpus-versus-target comparison
must account for this:

| Parameter | corpus (`galileo`, defaults) | target (`v25`) |
| :--- | ---: | ---: |
| `min_lift_height` | **0.05 m** (stricter) | 0.015 m |
| `min_airborne_steps` | 1 | 5 |
| `max_destination_xy_separation` | **None -> contact-only** (looser) | 0.075 m |

So the corpus scene faces a harder lift gate and an easier place gate, and a success reported
there can still be a spurious contact — the exact false positive removed from the target scene.
**Compare the hand-to-apple vertical error instead**: it is gate-independent.

---

## 4. Run log

### 4.1 Current measured geometry (2026-09-05, all re-measured, not inherited)

| scene | apple z rel pelvis | base→apple horiz | torso lean (imu−torso Δx) |
| :--- | ---: | ---: | ---: |
| **corpus `galileo`** | **+0.0399** | **0.3692** | **−0.0464** |
| `v25` (`waist_pitch: 0.2`) | −0.0610 | 0.3640 | −0.0193 |
| `v26` (posture override removed) | −0.0610 | 0.4326 | −0.0440 |
| `v27` (table raised 0.101 m) | +0.0660 | 0.3692 | — |

Head-camera renders, apple's normalised position in frame:

| scene | apple in frame | hands visible? | view |
| :--- | :--- | :--- | :--- |
| corpus | (0.14, **0.67**) lower-left | **both, at frame edges** | steeply down onto surface |
| `v25` | (0.54, 0.60) centre | both | shallow; table far edge + sky |
| `v26` | apple **not in frame** | both | shallower still |
| `v27` | (0.20, **0.28**) upper-left | **neither** | very steep, surface fills frame |

### 4.2 F1 — removing the posture override: FAILED, and the sign was the opposite of assumed

Removing `initial_joint_pos` brought torso lean *toward* the corpus (−0.0440 vs corpus −0.0464,
against `v25`'s −0.0193) but pushed the robot **6.9 cm further from the apple** (0.4326 vs corpus
0.3692) and moved the apple out of camera view entirely.

**Cause**: the whole-body controller couples posture, pelvis height and stance. `waist_pitch_joint:
0.2` was leaning the torso forward, which both pitched the camera down *and* brought the robot
closer. There is no way to change one without the other through the spec.

### 4.3 F2/v27 — raising the table: FAILED on a hard coupling defect

Raising `background.initial_pose.z` by 0.101 m matched the corpus horizontal distance **exactly**
(0.3692, zero residual) and removed **74%** of the height error (residual +0.0261 m). The
measurement tool confirmed the objects settled at the raised height.

The evaluation then scored **0.000 on all 20 episodes**, with episode lengths of 10–21 steps and
twice as many episodes as requested — the `P0` phantom-episode signature. The reach trace shows why:

```
step  0  apple z=+0.6138  speed= 1.33 m/s     <- spawns in mid-air, already moving
step 11  apple z=+0.3297  speed=17.63 m/s
peak     apple z=+5.4451  speed=29.45 m/s     <- launched
```

**Cause — a real defect in the generation stack.** `FIXTURE_SECTOR_BOUNDS`
(`spatial_geometric_oracle.py:20`) hardcodes the maple table's deck height as the 5th tuple
element, `Z_deck = 0.0`, and **it does not follow the fixture's `initial_pose`**. Raising the table
therefore left the placer targeting z ≈ 0.0, which is now 10.1 cm *inside* the tabletop; PhysX
ejects the intersecting objects at 29 m/s.

Note the inconsistency: `object_placer._sample_on_surface` derives `surface_z` from the parent
bounding box (`parent_bbox.max_point[0, 2]`) on the non-sector path, but the **sector** path takes
the hardcoded oracle value. So a fixture's deck height is authoritative in one path and hardcoded in
the other.

> [!CAUTION]
> **Do not raise or lower a fixture through the spec until `Z_deck` is derived from the fixture's
> actual bounding box.** It silently spawns objects inside the fixture. The symptom is
> immediate-termination episodes with absurd manipuland speeds, which reads as a policy or physics
> problem rather than a placement one.

### 4.4 The structural conclusion

Two independent attempts to match the corpus observation geometry failed for *structural* reasons,
not tuning reasons:

- Robot posture, pelvis height, stance distance and camera pitch are **coupled through the WBC**.
- Fixture height and object placement are **coupled through a hardcoded deck constant**.

**So the corpus observation geometry cannot be reproduced by adjusting individual spec parameters.**
Matching it requires either pinning everything explicitly (object poses, robot posture, camera
pose — removing the solver and the WBC from the loop), or accepting the observation gap and closing
it on the policy side (RGB-D finetune per §1.4, or new demonstrations).

Also worth recording: `--placement_seed` reproduces a layout only for a **fixed** spec. Changing the
table height re-rolled the layout at the same seed, because the feasible region the solver samples
changes with the geometry.

### 4.5 F4 — hand-to-apple decomposition

`ReachTracer` now records the nearest end-effector body each step and logs `hand_xy_to_obj`,
`hand_z_minus_obj` and `hand_dist_to_obj`. The nearest hand is chosen per step rather than fixed,
because a fixed choice reports the idle arm whenever the other arm is working.

This is the measurement that settles §1: **if horizontal error converges while vertical error does
not, the failure is depth.**

**Result (v25 config, seed 1, 5 episodes with hand tracing).** At each episode's moment of closest
horizontal approach:

| ep | closest 3-D | closest horizontal | vertical error there | min \|vertical\| in episode |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 0.0968 | 0.0168 | +0.1493 | 0.0433 |
| 1 | 0.0696 | **0.0072** | +0.0692 | 0.0448 |
| 2 | 0.0944 | 0.0237 | +0.1589 | 0.0448 |
| 3 | 0.0729 | 0.0282 | +0.0959 | 0.0448 |
| 4 | 0.0562 | 0.0131 | +0.1286 | 0.0448 |

| Quantity | Median |
| :--- | ---: |
| **Horizontal error** | **0.0168 m** — *inside* the apple's 0.0340 m radius |
| **Vertical error** | **+0.1286 m** — hand 12.9 cm *above* the apple |
| Ratio | **7.7×** |

> [!IMPORTANT]
> **Verdict: the policy locates the apple and fails on depth.** Horizontal targeting lands within
> 1.7 cm — better than the apple's own radius, in 5 of 5 episodes, against a 20 × 22 cm placement
> sector where chance would give ~10 cm. That accuracy is not obtainable without visually
> localising the apple, so **"does the model detect the apple" is answered yes, without needing the
> region-occlusion ablation (F5)**.
>
> Vertical targeting is wrong by 12.9 cm, and the hand never descends within 4.3 cm of the apple in
> *any* episode — always above its 3.4 cm radius. The hand arrives over the apple and closes on air.
> This is precisely the symptom in [Isaac-GR00T #210](https://github.com/NVIDIA/Isaac-GR00T/issues/210)
> ("moving to a position above the target object and stopping") and the predicted consequence of
> §1.1: with no depth channel, bearing is recoverable from the image and range is not.
>
> **F5 is therefore unnecessary, and P3/P4 are dead ends** — no photometric alignment corrects a
> 13 cm range error. The live options are: supply depth (RGB-D finetune, §1.4), or reproduce the
> corpus observation geometry exactly, which §4.4 shows the current stack cannot do parameter by
> parameter.

The reaching hand is `left_hand_thumb_2_link` — the **left** hand, matching the corpus and
independently confirming the `v15` `bilateral_mirror: false` correction.

### 4.6 F3 — execution horizon: moved a *proxy*, did not move the task

> [!CAUTION]
> **This section originally claimed the horizon change was "the one intervention that actually moved
> the number". That was an overreach and is retracted.** What moved is a diagnostic proxy — the
> hand-to-apple vertical distance at closest horizontal approach. **Task outcome did not move: zero
> successes and zero lifts at every horizon setting.**
>
> | setting | n | lifts | successes |
> | :--- | ---: | ---: | ---: |
> | chunk 16 (`v25`) | 10 | 1 | 0 |
> | chunk 8 (`v29`) | 6 | **0** | 0 |
> | chunk 4 (`v30`) | 6 | **0** | 0, plus 2 episodes that never settled |
>
> The sweep is **underpowered to detect a change in lift rate**: against `v25`'s 1-in-10 baseline,
> six episodes expect 0.6 lifts, and P(0 lifts) = 0.9⁶ ≈ 0.53. Seeing zero is therefore consistent
> with an unchanged rate and cannot be read either way. Any horizon comparison intended to inform a
> decision needs a task-level endpoint at n ≥ 30 per arm, not a proxy at n = 6.
>
> This is the same failure mode §2.2 warns about — trusting a metric that was never checked against
> the behaviour it claims to score — committed while writing the warning. Added to §2.2.

Same scene and seed, only `action_chunk_length` changed, 6 episodes each, measured at closest
horizontal approach:

Same scene and seed, only `action_chunk_length` changed, 6 episodes each, measured at closest
horizontal approach:

| `action_chunk_length` | horizontal | **vertical** | median peak speed | peak lift |
| ---: | ---: | ---: | ---: | ---: |
| 16 (`v28`) | 0.0168 m | **+0.1286 m** | 0.265 m/s | 0.0141 m |
| **8 (`v29`)** | **0.0163 m** | **+0.0795 m (−38%)** | 0.270 m/s | 0.0077 m |
| 4 (`v30`) | 0.0294 m ✗ | +0.0721 m (−44%) | **0.101 m/s** | **0.0170 m** |

**Choose 8.** It captures 38 of the 44 percentage points available, keeps the best horizontal
accuracy, and matches both NVIDIA's own examples and the literature's n_act ≈ 5 optimum (§1.5).
At 4 the horizontal error nearly doubles (0.016 → 0.029 m) — the replanning-noise regime, exactly
as predicted for very short chunks. Peak speed falling 2.6× at chunk 4 also confirms the violent
knocks (up to 1.6 m/s elsewhere) were blind open-loop motion.

### 4.6b The positive control, re-run properly — TWO stacked deficits

The control the whole diagnosis rested on was run 2026-09-04 02:25, **before** the funnel alignment,
and its "4/4 lifts" were the weak `object_is_above_height` predicate. It also had **0 successes** —
in the policy's own training scene. Re-run under the aligned funnel with hand tracing:

| | horizontal | vert at closest | **min vert gap in episode** | peak lift | successes |
| :--- | ---: | ---: | ---: | ---: | ---: |
| **corpus `galileo`** | 0.0379 m | **+0.0495 m** | **0.0051 m** | **0.0296 m** | **0/6** |
| target `v25` | 0.0168 m | +0.1286 m | 0.0448 m | 0.0141 m | 0/10 |

Under a common lift gate (the target's 0.015 m), the corpus scene **would** register a lift (0.0296)
and the target scene **would not** (0.0141). So galileo's reported "0 lifts" is largely a gate
artefact — it is scored at its own 0.05 m default, which its 3.0 cm lift does not clear.

**Two independent deficits, and both must be stated:**

1. **Transfer degrades range 2.6×.** Vertical error at closest approach goes 4.95 cm → 12.86 cm, and
   the minimum vertical gap goes 0.51 cm → 4.48 cm. In the corpus scene the hand *reaches* the apple
   (5 mm); in the target it never comes within 4.5 cm. **This confirms the §1/§4.5 diagnosis** and
   resolves the worry that the checkpoint might be non-functional: it is not. Bearing and range both
   work at home; range specifically breaks on transfer, exactly as a depth-free policy would.
2. **But there is no success even at home.** Peak lift 3.0 cm, no placement, 0/6. The documented
   `success_rate: 1.0` for `galileo_g1_static_pick_and_place` **does not reproduce** under honest
   scoring. Either it was measured with the contact-only place gate (the false-positive class
   removed in `6433fc6a1`), or Arena's re-creation of the corpus scene differs from the scene the
   dataset was recorded in.

> [!IMPORTANT]
> **Deficit 2 is the more important open question and was never on the plan.** Chasing target-scene
> transfer while the policy does not complete the task in its own training scene puts the
> optimisation target in the wrong place. **Establish a genuine corpus-scene baseline first** — if
> the policy cannot place at home, no amount of target-scene work can produce a placement, and the
> `1.0` figure that motivated the whole campaign is unverified.
>
> The `min_lift_height` inconsistency also has to go: 0.05 m in the corpus environment against
> 0.015 m in the target makes every cross-scene comparison unreadable. Pick one, measured from the
> observed lift distribution in both.

### 4.7 The vertical error decomposes into two parts

The vertical error **plateaus near 7 cm**: 16 → 8 buys 4.9 cm, 8 → 4 buys only 0.7 cm more. So of
the 12.9 cm error at the shipped configuration:

| Component | Magnitude | Cause | Remedy |
| :--- | ---: | :--- | :--- |
| **Staleness** | **~5 cm** | 320 ms of blind motion between observation and action | shorten the executed chunk — free, done |
| **Range bias** | **~7 cm** | monocular RGB cannot recover metric range (§1.1) | supply depth (F7) — the only thing that touches this |

7 cm is still ~2× the apple's 3.4 cm radius, so **no execution-horizon setting alone will produce a
grasp.** This is the quantitative statement of the diagnosis: the reachable improvement from
replanning is real but bounded, and the residual is irreducible without a depth channel.

> [!IMPORTANT]
> **What is established.** Bearing is accurate (1.6 cm); vertical range error is 12.9 cm at chunk 16
> and ~7 cm at the shortest horizon tested. **No configuration produced a grasp: 0 successes and
> 0-1 lifts in 58 episodes across every run.** The horizon change is justified by the proxy and by
> NVIDIA's own default, not by any demonstrated task gain, and should be labelled as such until a
> powered comparison exists. What is ruled out is photometric alignment — it cannot address a range
> error of this size.
