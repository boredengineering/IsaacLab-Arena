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
| **P1** | Distribution-violation corrections (config) | ✅ **DONE** 2026-09-04 | — | impl §12.2 |
| **P2** | Ground truth: open-loop eval + modality ablation | ⏳ **NEXT** | P3–P6 | impl §13 |
| **P2b** | **Fix `object_on_destination` false positive** | ⏳ **NEXT — blocks all scoring** | every rate | run log |
| **P3** | Observation-framing metrology | ⏸ pending P2b | P4 | impl §14 |
| **P4** | Photometric alignment (nuisance parameters) | ⏸ pending P3 | — | impl §16, strategic §5b.I1 |
| **P5** | Augmented re-finetune on existing corpus | ⏸ pending P2 | — | impl §17, strategic §5b.I2 |
| **P6** | Few-shot on target demos — **last resort** | ⏸ | — | strategic §5b.I3 |
| **PX** | Height sweep — **demoted, off critical path** | ⏸ optional | nothing | strategic §3 |

Legend: ✅ done · ⏳ in progress / next · ⏸ blocked or not started

---

## P0 — Harness integrity ✅

The settle loop's `torch.zeros()` hold action commanded a floor squat on the G1 WBC, collapsing the
robot and launching the apple before inference. Median episode length 7 → **1000 steps**,
terminations and false successes → **0**. Commit `83dc00658`.

**Exit criteria (met)**: full-horizon episodes, zero terminations, stable progress score.

## P1 — Distribution-violation corrections ✅

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
