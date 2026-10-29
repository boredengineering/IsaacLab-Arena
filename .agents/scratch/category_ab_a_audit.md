# Category A filesystem evidence audit

**Finding:** only **A1 apple → wooden bowl** has recovered executed Category A episode evidence. Seven historical run directories contain **97 episode records**. Three current-session attempts are separate: two empty/failed attempts and one completed **0/2** run. No banana, lemon, avocado or bell-pepper policy/preflight execution was recovered. This is bounded filesystem evidence, not proof no other runs ever occurred.

## Scenario status

| Catalog scenario | Evidence-backed status |
|---|---|
| **A1 Apple → wooden bowl** | Executed; all seven historical runs below, plus the separate current-session attempts. Legacy `droid_apple_bowl/droid_pick_apple_to_bowl.yaml` is an additional generated-only specification, not a proven alias of these runs. |
| **A2 Banana → large plate** | Proposed only: no `droid_banana_to_plate` spec or run found. The deck instead links an existing **banana → wooden bowl** spec, whose prose says “next to Rubik’s cube”; no execution found for that variant either. |
| **A3 Lemon → clay plate** | Proposed only: no generated spec or `droid_lemon_test/preflight` run found. A command block is not a completed preflight. |
| **A4 Avocado → serving bowl** | Exact catalog contract is proposed only. Existing `droid_avocado_to_bowl.yaml` targets **wooden_bowl_hot3d_robolab**, not `serving_bowl_vomp_robolab`; generated-only, no execution found. |
| **A5 Bell pepper → blue bin** | Proposed only: no generated spec or run found. |

Scope comes from [catalog A1–A5](../references/agentic_env_generation/env_gen_test.md#1-category-a-fresh-food--kitchen-tabletop-franka-droid--single-arm) and [presentation Category A](../references/presentations/category_a_b_manipulation_experiments.md#slide-4-category-a--fresh-food--kitchen-tabletop-scenarios), not their outcome claims. Actual sibling specs: [legacy apple](../../generated_envs/droid_apple_bowl/droid_pick_apple_to_bowl.yaml), [avocado](../../generated_envs/droid_avocado_bowl/droid_avocado_to_bowl.yaml), [banana](../../generated_envs/droid_rubiks_banana_bowl/droid_place_banana_next_to_rubiks_cube.yaml), and [Rubik’s cube → bowl with banana distractor](../../generated_envs/droid_rubiks_banana_bowl/droid_pick_rubiks_cube_to_wooden_bowl.yaml). The last is not a food-manipulation trial. Their README “latest/v1” and lineage paths are not present and do not prove evaluation.

## Historical A1 runs — 2026-09-01

Every denominator is completed JSONL episode records, not requested episodes. All records have **seed 42** (one distinct seed); environment IDs are parallel instances, not independent seeds. “Success” below is the **stored boolean**, not certified physical placement. “Lift” is a historical height-predicate event. “Complete” is `progress.all_complete`.

| Run / JSONL source | Version / chunk | Observed envs | Raw success | Lift event | Complete | Moved¹ | Median steps all / raw-success |
|---|---|---:|---:|---:|---:|---:|---:|
| [02-03-32](../../eval_output/droid_apple_to_wooden_bowl/2026-09-01_02-03-32/episode_results_rank0.jsonl) | v1? / 32? | 1 | 1/2 | 2/2 | 1/2 | 2/2 | 602 / 903 |
| [02-06-55](../../eval_output/droid_apple_to_wooden_bowl/2026-09-01_02-06-55/episode_results_rank0.jsonl) | v1 / 32 | 1 | 0/2 | 2/2 | 0/2 | 2/2 | 830 / — |
| [02-13-59](../../eval_output/droid_apple_to_wooden_bowl/2026-09-01_02-13-59/episode_results_rank0.jsonl) | v2? / 32? | 1 | 0/2 | 2/2 | 0/2 | 1/2 | 1000 / — |
| [02-21-10](../../eval_output/droid_apple_to_wooden_bowl/2026-09-01_02-21-10/episode_results_rank0.jsonl) | v2? / 32? | 4 | 0/8 | 7/8 | 0/8 | 7/8 | 1000 / — |
| [02-22-23](../../eval_output/droid_apple_to_wooden_bowl/2026-09-01_02-22-23/episode_results_rank0.jsonl) | v2 / 32 | 32 | 8/65 | 56/65 | 4/65 | 50/65 | 1000 / 694 |
| [04-04-44](../../eval_output/droid_apple_to_wooden_bowl/2026-09-01_04-04-44/episode_results_rank0.jsonl) | v3? / 16? | 16 | 1/16 | 16/16 | 1/16 | 16/16 | 1000 / 860 |
| [04-15-41](../../eval_output/droid_apple_to_wooden_bowl/2026-09-01_04-15-41/episode_results_rank0.jsonl) | v3 / 16 | 1 | 0/2 | 2/2 | 0/2 | 2/2 | 1000 / — |

¹ Moved counts reconstructed from each run’s `eval_telemetry.ttl` rate × its episode denominator, not recounted from missing velocity traces. The JSON inventory preserves TTL evaluation IDs, exact rates, HTML summaries, all raw rows with source line numbers, predicate events, progress distributions, episode-length distributions, and hashes. All nonempty runs’ JSONL counts/success rates agree with TTL and HTML.

**Version qualification:** [lineage.json](../../generated_envs/droid_apple_to_wooden_bowl/lineage.json) explicitly links only `02-06-55→v1`, `02-22-23→v2`, and `04-15-41→v3`. The other version/chunk assignments marked **?** are chronological candidates, **not proven runtime configuration**. Current policy files have horizon 32, chunks [v1=32](../../generated_envs/droid_apple_to_wooden_bowl/v1/policy_config.yaml), [v2=32](../../generated_envs/droid_apple_to_wooden_bowl/v2/policy_config.yaml), [v3=16](../../generated_envs/droid_apple_to_wooden_bowl/v3/policy_config.yaml). No historical run manifests/source hashes/checkpoint hashes were found. The spec’s internal name is `franka_droid_apple_to_bowl_maple_table`; telemetry uses family name `droid_apple_to_wooden_bowl`.

## Main discrepancies to fix in the presentation

1. **8/65 and 56/65 are reproducible, but “8 verified full pick-and-place successes” is not.** In the v2 run `02-22-23`, only **4/65** have `all_complete=true` and a destination event. Four success-flag rows have only settled progress, **no lift**, and **no placement event**: JSONL lines **6, 35, 45, 47** (env/episode **9/0, 20/1, 7/1, 10/1**). Preserve raw **8/65 = 12.3%** alongside the contradictory **4/65 = 6.2%** complete-predicate rate; neither is video-certified.

2. **14.3% is not a valid conditional lift→place conversion here.** Legacy code divides all success flags by lifted episodes (**8/56**), although four successes are outside the lifted set. The actual raw-success-and-lift intersection is **4/56 = 7.1%**. The 56 height events do not establish retained grasp or “perception/reachability solved.”

3. **Median 620 steps is not reproduced.** v2 median is **1000 steps across all 65**, **694 across the eight raw-success flags**, and **632.5 across the four all-complete rows**. Historical step duration is not pinned; deck conversions to 12.4 seconds and physical “in-flight holding time” cannot be treated as measured results. Elapsed steps after a height event are not time spent holding the apple.

4. **Lineage overwrites run history, it is not an exhaustive benchmark ledger.** It retains 0/2 for v1 and 0/2 for v3, omitting distinct raw **1/2** and **1/16** run outcomes. All seven runs remain in this inventory. Lineage `progress_score=0.0` is inconsistent with nonzero JSONL progress means. Its no-movement/500-step diagnoses conflict with linked v1 moved **2/2** and v2’s **42 records of length 1000**.

5. **Historical checkpoint identity is unverified.** TTL `modelWeightsPath` contains only `isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy`, not a model URI or digest. The deck’s N1.6-DROID label is context, not per-run proof. Current spec/config digests cannot retroactively freeze the historical runtime.

## Separate current-session evidence — 2026-09-09

| Attempt | Result |
|---|---|
| `03-35-53` | Empty JSONL + 96-byte HDF5; no completed episodes. Exact failure cause unassigned. |
| `04-32-36` | Empty JSONL + 96-byte HDF5; [launch log](droid_viz_20260909.log) lines 235/261/271 report video horizon **must be 1, got 2**. |
| [`04-37-42`](../../eval_output/droid_apple_to_wooden_bowl/viz_run/2026-09-09_04-37-42/episode_results_rank0.jsonl) | **2000 policy steps, exit 0; 0/2 success, 0/2 complete, moved 2/2, height event 2/2; seed42×2; lengths 1000/1000.** Mean progress 0.5. |

The [verified receipt](droid_n16_verified_result.json) identifies **nvidia/GR00T-N1.6-DROID**, revision `ae3ebe8d288971ac53aa30c756ea5cba0f52611b`, `OXE_DROID`; `latest→v3`. [Final log](droid_viz_20260909_final.log) records 2000/2000 and report creation. This run uses `object_lifted_above_resting_min(distance=0.05,min_airborne_steps=1)`: **one-step height excursion, not sustained grasp proof**. Historical events used `object_is_above_height(...use_settled_state=True)` and different score weights. Keep runs separate despite the shared v3 folder. No videos were recorded. Lineage write-back failed with permission denied; it was not silently updated.

## Metric semantics and audit limits

- **Moved ≠ lifted/grasped.** [ObjectMovedRateMetric](../../isaaclab_arena/metrics/object_moved.py) checks whether object linear speed exceeds its threshold at any step (current default **0.5 m/s**), then averages episodes. It is not displacement >3 cm or proof of hand contact. Historical threshold/source revision is not pinned.
- **Historical lift events have no dwell proof.** [Current spatial predicate](../../isaaclab_arena/tasks/predicates/spatial.py) explains settled-reference height checks (current old-function default 0.01 m); exact historical runtime threshold remains unverified. The current task’s gate implementation is [pick_and_place_task.py](../../isaaclab_arena/tasks/pick_and_place_task.py), not the nonexistent `pick_and_place.py` linked in the deck.
- **No duplicate A1 nonempty files, exact rows, or within-run episode keys found.** HTML/TTL/lineage are duplicate representations, not extra observations. The two identical empty-file hashes represent distinct attempted launches and are preserved.
- **Coverage:** 195 episode-result files enumerated across `eval_output` (**124**), `outputs` (**59**), and mounted `/eval` (**12**), plus generated specs/lineage and hidden/ignored `.agents/references`. Mounted episodes belong to G1/C1, not Category A Franka. Twelve anonymous empty `outputs` files without graph identity remain unattributed in JSON; they cannot establish another food scenario. No traversal errors.
- **No physical certification:** no historical A1 videos or retained-grasp traces were recovered. No HDF5 arrays, model weights, credentials or database were accessed; no evaluation was launched. Historical inventory totals (**97 episodes, 10 raw-success flags, 6 complete flags, 87 height events**) are **not a pooled performance estimate** across unpinned configurations.

**Machine-readable evidence:** [category_ab_a_audit.json](category_ab_a_audit.json). Only this report and that JSON inventory were created; the presentation and pre-existing files were not edited.
