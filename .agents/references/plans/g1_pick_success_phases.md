# Canonical Phase Tracker: Make the GN1x Policy Pick the Apple on the Maple Table

> [!IMPORTANT]
> **This file is the single source of truth for phase numbering and status.**
> The three transfer plans accumulated overlapping schemes (`Phase 0`, `0.5`, `1`–`4`, then
> `5b`–`5f` as sessions appended). Those sections remain valid as *detail*; their numbering does
> not. Cite phases as `P0`–`P6` from this table.

**Goal**: a closed-loop run in which the G1 lifts the apple off the maple table and places it on
the clay plate, scored by the honest harness (`SuccessMode.SEQUENCE`, lift-before-place gated).

**Definition of done**: `success_rate > 0` with `object_moved_rate > 0` on
`g1_tabletop_apple_to_plate`, reproducible across at least 2 seeds, with no false-success mode
identified in the artefacts.

---

## Status board

| Phase | Name | Status | Gates | Detail |
| :--- | :--- | :--- | :--- | :--- |
| **P0** | Harness integrity | ✅ **DONE** 2026-09-04 | everything | impl §12.1 |
| **P1** | Distribution-violation corrections (config) | ✅ **DONE** 2026-09-04 — but see §P1 retraction | — | impl §12.2 |
| **P2a** | Ground truth: open-loop fidelity | ✅ **DONE** 2026-09-04 (measured, not inferred) | P3–P6 | impl §13 |
| **P2b** | Fix `object_on_destination` false positive | ✅ **DONE** 2026-09-04 — commit `6433fc6a1` | every rate | run log |
| **P2c** | Ground truth: modality ablation | ✅ **DONE** 2026-09-04 | **P4 vs P5** | run log |
| **P3** | Observation-framing metrology | ⏳ **NEXT — gates P4** | P4 | impl §14 |
| **P4** | Photometric alignment (nuisance parameters) | ⏸ pending P3 — **indicated by P2c** | — | impl §16, strategic §5b.I1 |
| **P5** | Augmented re-finetune on existing corpus | ⏸ **deprioritised by P2c** | — | impl §17, strategic §5b.I2 |
| **P6** | Few-shot on target demos — **last resort** | ⏸ | — | strategic §5b.I3 |
| **PX** | Height sweep — **demoted, off critical path** | ⏸ optional | nothing | strategic §3 |
| **F1-F5** | **Monocular-depth / camera-pitch fixes** | ⏳ **NEXT — supersedes P3/P4** | the grasp itself | [depth debug record](g1_monocular_depth_and_camera_pitch_debug.md) |

Legend: ✅ done · ⏳ in progress / next · ⏸ blocked or not started

> [!IMPORTANT]
> **2026-09-05: the failure is the grasp, not the place.** Per-episode (not pooled) inspection shows
> 6 of 9 episodes barely touch the apple and one *launches* it at 1.6 m/s. The policy has no depth
> input (`video: ["ego_view"]`, camera `data_types=["rgb"]`) and the scene tilts its camera via a
> `waist_pitch_joint: 0.2` posture override the corpus never had, so its monocular depth cue is
> wrong and it closes on air. Full diagnosis, method, and fix sequence:
> [`g1_monocular_depth_and_camera_pitch_debug.md`](g1_monocular_depth_and_camera_pitch_debug.md).
> This supersedes P3/P4 on the critical path — photometric alignment cannot fix a camera-pose error.

> [!IMPORTANT]
> **The old `P2` split into `P2a`/`P2b`/`P2c`.** The tracker previously marked `P2` as "complete for
> (a) and superseded for (b)". Both halves of that were wrong: (a) had never actually been run --
> only its *preconditions* (normalisation stats, modality-group counts) had been checked -- and (b)
> was not superseded, because the positive control localises the fault to the scene but cannot say
> which modality the policy reads. Both are now measured. See the 2026-09-04 third-session log.

---

## P0 — Harness integrity ✅

The settle loop's `torch.zeros()` hold action commanded a floor squat on the G1 WBC, collapsing the
robot and launching the apple before inference. Median episode length 7 → **1000 steps**,
terminations and false successes → **0**. Commit `83dc00658`.

**Exit criteria (met)**: full-horizon episodes, zero terminations, stable progress score.

## P1 — Distribution-violation corrections ✅ (partly retracted)

> [!CAUTION]
> **The `v17` prompt attribution is retracted (2026-09-04, third session).** The modality ablation
> measures the instruction at **0.75–0.95× the sampling-noise floor** — swapping it changes the
> action chunk less than resampling noise does. Independently, object placement turned out to be
> unseeded, so each rung of the ladder below ran on a different scene layout. The `v15` and `v16`
> changes remain correct on their own merits (the mirror was genuinely double-applying; chunk 40
> was genuinely 1.3 s of blind open-loop motion), but the *evidence* offered for all three rungs
> does not support the attribution. A fourth violation — unseeded layout against a corpus with zero
> spatial variation — was missed entirely. See the third-session run log.

Three real violations corrected; none sufficient alone (`object_moved_rate` stayed 0.0):

| | Change | Kept |
| :--- | :--- | :--- |
| `v15` | `bilateral_mirror: false` — layout was already mirrored in the scene | yes |
| `v16` | `action_chunk_length: 40 → 16` (canonical) | yes |
| `v17` | exact corpus prompt from `meta/tasks.jsonl` | yes |

**Exit criteria (met)**: the config axis is eliminated as a *sufficient* explanation, which is what
authorises P5's cost.

## P2 — Ground truth ⏳ **NEXT**

Two tests, run together. Neither is optional and the second is the discriminating one.

**(a) Open-loop fidelity** — replay corpus trajectories, per-dimension MSE, and diff the
checkpoint's `experiment_cfg/metadata.json` normalisation stats against `meta/stats.json`.

**(b) Modality ablation** — for a fixed observation, compare action chunks under
`baseline / vision_scrambled / vision_blank / vision_crossscene / state_perturbed / state_zeroed`.

**Exit criteria**: a signed statement of which modality the policy conditions on, with numbers.

**Decision rule**:

| P2 outcome | Next phase |
| :--- | :--- |
| open-loop MSE high | fix normalisation/modality wiring; **do not** start P3–P6 |
| vision ablation barely moves the chunk | **P5 is mandatory**; P4 alone cannot work |
| vision ablation moves the chunk substantially | **P4 first**; the fault is what vision encodes here |

> [!CAUTION]
> A good open-loop plot does **not** clear the checkpoint. Causally confused policies have low
> open-loop loss by construction. (a) without (b) repeats this project's own history.

## P3 — Observation-framing metrology ⏸

Formalise the 2.04× brightness / 71× red-dominant-pixel measurement over ≥100 corpus and ≥100
target frames, reporting distributions rather than the current single frame pair.

**Exit criteria**: a reproducible separability metric, validated by confirming the corpus blob
tracks the apple through the grasp. If it does not, the metric measures background and P4 loses its
target function.

## P4 — Photometric alignment ⏸

Add an `appearance` block to the graph spec (dome light, material albedo/roughness) and drive the
target scene's statistics toward the corpus's. Requires the `preserves_target_scene` split into
scene-semantics vs nuisance-rendering predicates.

**Exit criteria**: target statistics within tolerance of corpus, **and** a closed-loop run
reported for both aligned and unaligned scenes.

## P5 — Augmented re-finetune ⏸

Four arms on the existing 251-episode corpus. **No new demonstrations, target scene untouched.**

| Arm | `--tune-visual` | State dropout | Photometric jitter |
| :--- | :--- | :--- | :--- |
| A control | off | off | off |
| B | off | on | off |
| C recommended | on | on | on |
| D vision-only floor | on | inputs removed | on |

**Exit criteria**: arm C beats arm A on the target scene without regressing on the corpus scene.
Arm D beating A confirms the proprioceptive shortcut.

## P6 — Few-shot on target demos ⏸ last resort

10–20 `maple_table` demos with LoRA / object-centric adaptation. Requires new demonstrations, which
is precisely what Pathway B was rejected for. If this phase is reached, record plainly that the
zero-new-demo transfer premise failed.

---

## Run log and current status (2026-09-04, second session)

### The metric that hid ten iterations of progress

`object_moved_rate` uses `object_velocity_threshold = 0.5` m/s
(`isaaclab_arena/metrics/object_moved.py:75`). A careful pick-and-place never reaches 0.5 m/s, so
the metric only fires when the object is **violently displaced**. It was the headline signal for
`v13`-`v19` and it reported `0.0` while the policy was steadily improving.

Re-scored by progress predicates, the "four negative experiments" were cumulative **wins**:

| Run | Change | Lifts | Placed | Progress |
| :--- | :--- | :--- | :--- | :--- |
| `v14` | baseline (mirror on, chunk 40, wrong prompt) | 0 | 0 | 0.0 / 0.333 |
| `v15` | `bilateral_mirror: false` | 0 | 0 | 0.333 / 0.333 |
| `v16` | + `action_chunk_length: 16` | **1** | 0 | **0.667** |
| `v17` | + exact corpus prompt | **1** | **1** | **1.000** |

`v17` ep1 was **verified on video**: the hand closes on the apple, the apple leaves its start
position, and the hand delivers it to the plate. That is one genuine task completion.

> [!IMPORTANT]
> **Lesson for the benchmark, not just this task**: a headline metric whose threshold was never
> checked against the behaviour it scores can invert the sign of an entire experimental campaign.
> `object_moved_rate` should either be renamed (`object_disturbed_rate`) or take its threshold from
> the manipuland's own dynamics. Progress-predicate scoring is the trustworthy signal and should
> lead the reports.

### The positive control that localised the fault

Running the same policy on its **corpus scene** (`galileo_g1_static_pick_and_place`, with
`--embodiment g1_wbc_agile_joint` for the 50-D action space):

| Scene | Lift | Progress |
| :--- | :--- | :--- |
| galileo (corpus) | **4/4 episodes** | 0.667 each — lifts at step ~20, never places |
| maple (target) | 1/24 episodes | 0.333 typical |

The checkpoint reaches and lifts reliably on the scene it was trained on and rarely on the target.
Combined with the clean P2(a) preconditions below, this puts the fault in **scene-side grounding**,
not in the checkpoint or the plumbing.

### P2(a) preconditions: all clean, no replay needed

| Check | Result |
| :--- | :--- |
| `new_embodiment` key in `experiment_cfg/dataset_statistics.json` | present (`embodiment_id` = 10) |
| Normalisation stats vs `meta/stats.json` | **identical**, max abs diff `0.0` |
| Inference modality config vs checkpoint groups | **match**: state 5 groups / action 7 groups |
| Action representation | `ABSOLUTE` on all groups, matching the 43-DoF joint space |
| Backbone availability | `Cosmos-Reason2-2B` cached, 8.4 GB |

So the `#408`/`#213` metadata failure class and the absolute-vs-relative convention risk are both
**ruled out**.

### Success definition, corrected

The operative definition is: **the apple must be lifted, must stay airborne for a sustained
period, and must be placed on the plate.** Implemented as an ordered `SuccessMode.SEQUENCE`:

1. `object_lifted_above_resting_min(distance, min_airborne_steps)` — now requires the lift to hold
   for N **consecutive** steps. Added 2026-09-04; a single-step excursion is not a carry.
2. `object_on_destination(force_threshold, velocity_threshold)` — contact with the plate at rest.

Thresholds must come from the measured distribution, not assertion:

| Parameter | Old | Measured basis | New |
| :--- | :--- | :--- | :--- |
| `min_lift_height` | 0.05 (asserted) | peak lift ever observed = **0.0195 m** | 0.015 |
| `min_airborne_steps` | n/a | — | 5 |

The old 5 cm gate was **mathematically unreachable** on this scene, so every genuine completion was
scored a failure.

### Open defect: `object_on_destination` false positive — **BLOCKS honest scoring**

`v20` produced `success_rate: 0.1`, and the trace shows it is **not genuine**:

| Step | Event | Apple state |
| :--- | :--- | :--- |
| 66-72 | apple struck, briefly airborne | lift → 0.0275 m, speed 0.43 m/s, dist 0.143 m |
| 78 | landed back at start | lift 0.0008 m, dist 0.214 m |
| 87 | lift stage latches | (legitimate — the knock *was* a sustained excursion) |
| **95** | **`object_on_destination` fires ⇒ success** | **z = 0.0195 m (resting), 0.214 m from the plate** |

The apple was on the **table**, a fifth of a metre from the plate, when "placed on destination"
fired. The contact sensor is filtered to the plate's prim
(`object_base.py:196`), so the reading is spurious — the leading hypothesis is a **stale
`force_matrix_w`** from the graze at step ~72 that passes the `velocity < 0.1` gate once the apple
settles. `force_threshold` also defaults to **0.1 N**, low enough for noise to clear it.

**Required fix before any success rate is quotable**: add a geometric conjunct to the destination
stage — the apple must be within the plate's radius in XY and supported at plate height — so that
"placed on the plate" cannot be satisfied by a sensor artefact. Contact alone is not evidence of
placement. Instrumentation for `contact_force` and `xy_to_dest` is in the reach tracer as of this
session.

### Honest status

| Quantity | Value |
| :--- | :--- |
| Gate-reported success rate | **0.1** (`v20`, 1/10) — **rejected as a false positive** |
| Video-verified genuine completions | **1** (`v17` ep1) |
| Trustworthy success rate | **not yet measurable** — pending the destination fix |

**P2 is complete for (a) and superseded for (b)**: the positive control answered the localisation
question that the modality ablation was meant to answer, so the ablation is now a *confirmation*
step rather than a gate. **The critical path is the `object_on_destination` fix, then a re-measured
rate, then P4.**

---

## Run log (2026-09-04, third session)

### The finding that invalidates the campaign's A/B comparisons

**Object placement is not seeded, so every run got a different scene layout.**

`ObjectPlacerParams.placement_seed` defaults to `None`
(`isaaclab_arena/relations/object_placer_params.py:58`). At
`isaaclab_arena/relations/object_placer.py:196-199` a `None` seed means the RNG *generator itself*
is `None`, and `_sample_axis_position` (`:607`) then calls `torch.rand(1, generator=None)` — the
unseeded global RNG. Neither `policy_runner` nor `measure_embodiment_frames` passes
`--placement_seed`, so no evaluation in the `v9`–`v23` campaign controlled object placement.

Measured, from three identical invocations of the **same** `v23` spec:

| Run | apple XY | plate XY | apple→plate |
| :--- | :--- | :--- | ---: |
| A | (−0.124, +0.160) | (−0.154, −0.027) | 0.189 m |
| B | (−0.115, +0.162) | (−0.150, −0.053) | 0.217 m |
| C | (+0.042, −0.242) | (−0.154, −0.049) | 0.275 m |

The sectors the `v23` spec places into are large and overlapping —
`front_left` (apple) is 20×22 cm, `front_center` (plate) is 40×36 cm
(`spatial_geometric_oracle.py:49-51`) — so the achievable separation spans roughly 0 to 0.58 m.

**The corpus has no such variation at all.** `APPLE_SPAWN_XY_RANGE_M = 0.0`
(`galileo_g1_static_pick_and_place_environment.py:67`), with apple at `(0.5785, 0.27)` and plate at
`(0.5785, 0.06)` — a **fixed 0.21 m** lateral offset in all 251 episodes.

Three consequences:

1. **The `v14`→`v15`→`v16`→`v17` ladder is uncontrolled.** Each rung was a separate run and
   therefore a separate layout. The gains attributed to `bilateral_mirror`,
   `action_chunk_length` and the corpus prompt are confounded with layout luck.
2. **`v17`'s single completion is most simply explained as a favourable layout**, which is
   consistent with `v23` (byte-identical policy config) scoring 0/10.
3. **The policy is being asked to generalise over a spatial axis it has exactly zero training
   variation in.** This is a distribution violation of the same class as `P1`'s three, and it was
   never on the list.

**Fix**: pass `--placement_seed` on every evaluation. The flag already exists and documents itself
as "objects are placed at the same positions across runs"; it was simply never used. An unseeded
evaluation is not a measurement, so this should arguably be seeded by default rather than opt-in.

### P2a — open-loop fidelity: clean

Run against the live server with `gr00t.eval.open_loop_eval`, 5 trajectories, execution horizon 16:

| Metric | Value |
| :--- | ---: |
| Mean action MSE | **0.0141** |
| Mean action MAE | **0.0266** |

The checkpoint reproduces corpus actions when fed corpus observations, so normalisation, modality
wiring and the checkpoint↔server path are ruled out **by measurement** rather than by inspecting
metadata. Note the tracker's own caution still applies: low open-loop loss is what a causally
confused policy produces too, so this clears the wiring, not the policy.

### P2c — modality ablation: vision is load-bearing, the prompt is not

`isaaclab_arena_examples/tools/probe_policy_modality.py` (new), 24 observations across 3
trajectories. Each delta is expressed as a multiple of the policy's own sampling-noise floor:

| Modality | median | pooled | mean |
| :--- | ---: | ---: | ---: |
| Vision (scrambled) | 2.73× | **2.90×** | 6.34× |
| State (zeroed) | 2.32× | **2.28×** | 4.23× |
| Prompt (swapped) | 0.95× | **0.75×** | 1.15× |

Per-step ratios anti-correlate with the noise floor (corr **−0.50**), so the mean is inflated by a
few low-denominator steps; median and pooled agree and are the ones to quote.

- **Vision is load-bearing (~2.9×)** → by this tracker's own decision rule, **P4 before P5**.
- **State is ~2.3×, below vision** → the proprioceptive-shortcut hypothesis is **not** supported,
  so **P5 arm D's premise falls away**.
- **The prompt is at or below the noise floor (~0.8×)** → swapping the instruction changes the
  action chunk *less* than resampling noise. **This retracts P1's `v17` attribution.** Combined
  with the unseeded-layout finding above, the `v17` result has two independent explanations that
  do not involve the prompt.

> [!WARNING]
> The ablation ran on **corpus** observations. "Vision is load-bearing" is established for the
> training distribution; the target-scene equivalent needs target observations, which is exactly
> what **P3** is for. P4 without P3 has no target function to align toward.

### Success-gate thresholds, now measured rather than asserted

`measure_embodiment_frames` reports object extents, so the provisional gate can be replaced:

| Object | extent (m) | footprint radius |
| :--- | :--- | ---: |
| `clay_plate` | 0.150 × 0.151 × 0.024 | **0.0755** |
| `red_apple` | 0.068 × 0.066 × 0.068 | **0.0340** |

`max_destination_xy_separation` is currently **0.10 m**, which *exceeds the plate's own radius*: an
apple 0.09 m from the plate centre is 1.5 cm beyond the rim and not on the plate, yet passes. The
defensible value is the plate footprint radius, **0.075 m** (apple centre over the plate, combined
with the existing contact and at-rest conditions). Stricter still, 0.0415 m puts the apple fully
inside the rim. This is a false-positive fix, not a route to a success.

### Probe defects found by first use

`policy_activation_probe.py` had **no production callers** — written for this phase and never run.
Wiring it up surfaced three real bugs, all now fixed and covered by regression tests:

1. `output.get("action_pred") or output.get("action")` — `or` on an array raises `ValueError`.
2. Key detection assumed the **flat** `video.x` observation form, but `Gr00tPolicy` requires the
   **nested** `{"video": {...}}` form. The vision *and* state ablations therefore located nothing
   and silently reported no ratios — a failed measurement that looked like a clean run.
3. The prompt ablation overwrote the `language` container with a bare string, which
   `Gr00tPolicy.check_observation` rejects.

A state ablation did not exist at all and was added; P5 arm D depends on it.

### Graph plumbing (experience memory now actually closes the loop)

- Evaluation telemetry never reached Neo4j from the evaluation image: the `neo4j` driver was not
  installed there and `telemetry_to_prov.py` swallowed the failure with a bare `except: pass`. The
  graph's newest evaluation was **2026-09-02T23:14** — the entire 09-04 campaign was missing.
  Driver declared in `pyproject.toml`, failure now logged, 09-04 runs backfilled.
- `graph_rag` retrieval never read a single evaluation outcome, matched a relationship type
  (`HAS_RELATION`) and property (`rel.kind`) that the writer does not emit, and filtered on
  `converged` — a *generator* health flag — while labelling the result "Verified High-Performing".
  Retrieval now ranks by measured success rate behind an episode floor, renders relations with
  their `kinematic_manifold`/`surface_anchor`, and labels unevaluated priors honestly.
- Registered environments were orphaning their telemetry: the subparser destination is
  `example_environment`, but the code read `environment_name`, so every one fell through to the
  generic `arena_env` (43 of 78 runs unlinked).

### The progress funnel was scoring a weaker condition than the success gate

Found by code review of the P2b fix and then confirmed in live `v24` data. `PickAndPlaceTask` built
its termination gate and its progress objectives from **different** predicates:

| Stage | Termination gate | Progress objective (before fix) |
| :--- | :--- | :--- |
| Lift | `object_lifted_above_resting_min(distance=min_lift_height, min_airborne_steps=5)` | `object_is_above_height(use_settled_state=True)` — no height, no airborne hold |
| Place | `object_on_destination(..., destination_cfg, max_xy_separation)` | `object_on_destination(...)` — **contact only** |

So the `6433fc6a1` "contact alone is not a placement" fix reached the gate and not the funnel. `v24`
episode 1 is the proof: `overall_score = 1.000` with `success = False`, its events naming the
progress-side predicates.

Three consequences:

1. **`overall_score` was never the trustworthy signal** the second-session log promoted it to. It
   overstates both the lift and the place stage.
2. **`v17`'s "progress 1.000" carries the same signature as `v24`'s false positive.** The reported
   completion rests on the funnel's contact-only place stage, not on the gate.
3. The `success and overall_score <= 0` false-success detector (`eval_self_healing.py:118`) became
   unreachable, because the funnel now latches wherever the gate does and further.

Fixed by building both from the same predicates and parameters. That required first making
`EpisodeScopedState.run_length` count **steps rather than calls** — it is now evaluated from two
places per step, and a call-counting run length would have silently halved `min_airborne_steps`.

### Baseline at a pinned, corpus-matched layout

Placement seeds sweep the layout, so a seed can be chosen to match the corpus geometry:

| seed | apple→plate | vs corpus (0.210 m) |
| ---: | ---: | ---: |
| 1 | **0.2036 m** | **0.97×** |
| 7 | 0.1928 m | 0.92× |
| 42 | 0.2337 m | 1.11× |
| 123 | 0.1960 m | 0.93× |

`v24` (seed 42, i.e. a layout 11–25% longer than anything in training, old funnel, gate 0.10 m):

| Quantity | Value |
| :--- | ---: |
| Success | **0/10** |
| Progress | 1×1.000 (false positive), 1×0.667, 7×0.333, 1×0.0 |
| Peak lift above rest | **0.028 m** (clears the 0.015 gate) |
| Closest approach to plate | **0.119 m** (from 0.262 m — so 0.143 m of real transport) |
| Peak contact force | 0.66 N (clears the 0.1 N threshold) |

The policy therefore **does** grasp, lift and carry: it moved the apple 14 cm toward the plate and
came within 12 cm of it. It misses because 0.119 m is still outside the plate — whose measured
footprint radius is 0.0755 m — not because it never attempts the transport. `object_moved_rate`
remains 0.0 throughout, which is the 0.5 m/s threshold defect, not the behaviour.

`v25` is the honest baseline: corrected gate (0.075 m), aligned funnel, and seed 1's
corpus-matched geometry.

### `v25` honest baseline, and the finding that reframes the whole diagnosis

`v25` — corrected gate (0.075 m), aligned funnel, seed 1's corpus-matched 0.204 m layout:

| Quantity | `v24` (seed 42) | `v25` (seed 1) |
| :--- | ---: | ---: |
| Success | 0/10 | **0/10** |
| Progress | 1×1.000 (false +), 1×0.667, 7×0.333, 1×0.0 | 1×0.667, 8×0.333, 1×0.0 |
| Stages observed | contact-only place fired | `objects_settled`, `object_lifted_above_resting_min` only |
| Start apple→plate | 0.2619 m | 0.2213 m |
| Closest approach | 0.1187 m | 0.1138 m |
| Transported | 0.1432 m | 0.1075 m |
| **Peak lift above rest** | **0.0277 m** | **0.0278 m** |
| Peak contact force | 0.66 N | 3.13 N |

The aligned funnel produced no spurious placement, confirming the fix.

**The transport endpoint is nearly invariant to where the plate is.** Between the two runs the
plate's starting distance differed by 40.6 mm while the transport endpoint differed by 4.9 mm — the
endpoint tracks the destination at **12%**. Peak lift is identical to 0.1 mm (0.0277 vs 0.0278 m)
across two different layouts.

So the policy is running a **stereotyped, destination-agnostic trajectory**: it grasps, lifts
~2.8 cm, carries the apple 11–14 cm, and stops ~11.4 cm from the plate centre wherever the plate
is — about 3.8 cm outside the plate's 0.0755 m rim, and roughly 45% short of the corpus's 0.21 m
transport.

**The corpus explains this completely.** Both objects are fixed for all 251 demonstrations: the
plate via a plain `Pose` (`galileo_g1_static_pick_and_place_environment.py:277`) and the apple via a
`PoseRange` whose half-range is `APPLE_SPAWN_XY_RANGE_M = 0.0`. The policy never saw the
destination move, so it had nothing from which to learn destination-conditioned placing. It
memorised one trajectory.

> [!IMPORTANT]
> **This reprioritises P4 and P5.** P2c established that vision is load-bearing (~2.9×), which
> presumably drives the reach and grasp — and the reach and grasp do work. But the *place* phase is
> open-loop with respect to the destination, and no photometric alignment fixes a phase that is not
> conditioned on the thing being aligned. **P5 is also weak here**: it augments the existing corpus,
> and that corpus contains zero destination variation to augment.
>
> The cheap decisive test is instead: place the apple and plate at the corpus's *robot-relative*
> offsets (corpus robot base `(0.25, 0.08)`, apple `(0.5785, 0.27)`, plate `(0.5785, 0.06)` — so
> apple `(+0.3285, +0.19)` and plate `(+0.3285, −0.02)` relative to the base). If the memorised
> trajectory then lands the apple on the plate, the diagnosis is confirmed and the failure is
> destination generalisation, not visual domain. If it still misses, the trajectory itself does not
> transfer and P6 (new demos, with destination variation) becomes the honest answer.

### Revised critical path

1. ~~Seed object placement on every eval~~ — **done**; `--placement_seed` is now mandatory for any
   comparison to mean anything, and the measurement tool accepts it too.
2. **Corpus-relative placement test** (above). Cheap, decisive, and it gates everything below.
3. **P3** metrology only if step 2 shows the trajectory transfers but lands short for visual
   reasons.
4. **P4** appearance alignment — **demoted**: it cannot fix a destination-agnostic place phase.
5. **P5** — **demoted**: the corpus has no destination variation to augment. Arm D was already
   dropped on the P2c evidence.
6. **P6** (new demos with destination variation) is now the most likely real answer, which should
   be recorded plainly: the zero-new-demonstration transfer premise looks unsupportable for the
   place phase.

---

## Retired / superseded numbering

| Old label | Now |
| :--- | :--- |
| remediation §7 Pathway A/B | rejected, unchanged |
| remediation §7 Pathway C | folded into **P0** (landed) |
| strategic `Phase 0` | **P0**/**P1** |
| strategic `Phase 0.5` (§1c) | **P2** |
| strategic `Phase 1` height sweep | **PX**, demoted |
| strategic `Phase 2` probes | merged into **P2(b)** |
| strategic `Phase 3` height-augmented finetune | void (height in tolerance) → **P5** |
| strategic `Phase 3′` (§5b) | **P4**/**P5**/**P6** |
| strategic `Phase 4` close-the-loop | continuous, not a phase |
| impl `§5b`–`§5e` | historical record |
| impl `§5f`/`§12` | **P0**/**P1** |
| impl `§13`/`§14`/`§16`/`§17` | **P2**/**P3**/**P4**/**P5** |
