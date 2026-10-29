# Category B filesystem audit

**Verified:** 15 candidate runs: 10 with recorded episodes and 5 zero-episode reports. All 307 recorded rows have unique within-run identities; no malformed lines or duplicate rows. JSONL success counts and episode denominators agree with TTL and HTML for every candidate. These totals describe audit coverage, **not a pooled benchmark**.

Sources below are repository-relative unless absolute. The accompanying [JSON inventory](category_ab_b_audit.json) preserves exact absolute paths, source SHA-256s, every episode record with line citation, per-run statistics, current YAML/config snapshots, and lineage records. No presentation, pre-existing artifact, package code, or database was changed.

## Per-run results

**Success** means the archived boolean, not independently verified placement. **Lift** means a completed `object_is_above_height(...)` progress event, not a sustained grasp. **Moved** is the TTL aggregate velocity metric; its count is inferred from rate × N, not remeasured. Conversion uses the success/lift **intersection**. All nonempty runs record seed **42**; recorded environment IDs are not independent seeds.

| Family / version¹ | Run timestamp / source | Observed env IDs | Success | Lift event | Moved² | Success given lift | Progress complete |
|---|---|---:|---:|---:|---:|---:|---:|
| Tomato v1† | [2026-09-01_04-42-35](../../eval_output/droid_tomato_soup_to_blue_bin/2026-09-01_04-42-35/episode_results_rank0.jsonl) | 16 | 1/20 (5.0%) | 17/20 (85.0%) | 19/20 | 1/17 (5.9%) | 1/20 |
| Tomato v1 | [2026-09-01_04-52-54](../../eval_output/droid_tomato_soup_to_blue_bin/2026-09-01_04-52-54/episode_results_rank0.jsonl) | 1 | 0/2 (0.0%) | 2/2 (100.0%) | 2/2 | 0/2 (0.0%) | 0/2 |
| Tomato v2† | [2026-09-01_16-14-46](../../eval_output/droid_tomato_soup_to_blue_bin/2026-09-01_16-14-46/episode_results_rank0.jsonl) | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 1/1 | 1/1 (100.0%) | 0/1 |
| Tomato v2 | [2026-09-01_16-34-46](../../eval_output/droid_tomato_soup_to_blue_bin/2026-09-01_16-34-46/episode_results_rank0.jsonl) | 32 | 23/50 (46.0%) | 47/50 (94.0%) | 49/50 | 22/47 (46.8%) | 6/50 |
| Tomato v3† | [2026-09-01_17-27-51](../../eval_output/droid_tomato_soup_to_blue_bin/2026-09-01_17-27-51/episode_results_rank0.jsonl) | 32 | 25/52 (48.1%) | 44/52 (84.6%) | 51/52 | 23/44 (52.3%) | 11/52 |
| Tomato v3 | [2026-09-01_18-23-40](../../eval_output/droid_tomato_soup_to_blue_bin/2026-09-01_18-23-40/episode_results_rank0.jsonl) | 1 | 0/1 (0.0%) | 1/1 (100.0%) | 1/1 | 0/1 (0.0%) | 0/1 |
| Tomato v4 | [2026-09-01_18-40-38](../../eval_output/droid_tomato_soup_to_blue_bin/2026-09-01_18-40-38/episode_results_rank0.jsonl) | 32 | 6/42 (14.3%) | 37/42 (88.1%) | 41/42 | 6/37 (16.2%) | 2/42 |
| Spam v1† | [2026-09-01_19-09-49](../../eval_output/droid_spam_can_to_grey_bin/2026-09-01_19-09-49/episode_results_rank0.jsonl) | 32 | 18/70 (25.7%) | 68/70 (97.1%) | 66/70 | 18/68 (26.5%) | 2/70 |
| Spam v2 | [2026-09-01_19-29-40](../../eval_output/droid_spam_can_to_grey_bin/2026-09-01_19-29-40/episode_results_rank0.jsonl) | 32 | 13/67 (19.4%) | 49/67 (73.1%) | 40/67 | 13/49 (26.5%) | 3/67 |
| Spam v1 | [2026-09-01_19-53-15](../../eval_output/droid_spam_can_to_grey_bin/2026-09-01_19-53-15/episode_results_rank0.jsonl) | 1 | 0/2 (0.0%) | 1/2 (50.0%) | 1/2 | 0/1 (0.0%) | 0/2 |

¹ Explicit version assignments use the exact `eval_dir` in each family’s `generated_envs/.../lineage.json`. † Assignments use generation timing and, for the N52 tomato / N70 spam runs, next-version diagnostics and historical notes; they are **not hash-bound** run provenance. Do not pool pilots and parallel runs. ² Moved counts are reconstructed aggregate counts; the JSON retains the original rate string.

### Zero completed episodes—not zero-success benchmarks

| Graph | Run / source | Policy | Evidence |
|---|---|---|---|
| `mustard_above_raisin` | [outputs/2026-08-28_00-50-14](../../outputs/2026-08-28_00-50-14/eval_telemetry.ttl) | Zero action | JSONL empty; HTML/TTL N=0; moved=NaN |
| `mustard_above_raisin` | [outputs/2026-08-28_00-52-18](../../outputs/2026-08-28_00-52-18/eval_telemetry.ttl) | Zero action | JSONL empty; HTML/TTL N=0; moved=NaN |
| `mustard_above_raisin` | [eval_output/mustard_test/2026-08-29_07-44-46](../../eval_output/mustard_test/2026-08-29_07-44-46/eval_telemetry.ttl) | Zero action | JSONL empty; HTML/TTL N=0; moved=NaN |
| `droid_pick_mustard_to_bin` | [eval_output/droid_mustard_test/2026-08-29_21-47-18](../../eval_output/droid_mustard_test/2026-08-29_21-47-18/eval_telemetry.ttl) | Zero action | JSONL empty; HTML/TTL N=0; moved=NaN |
| `droid_pick_mustard_to_bin` | [eval_output/debug_run/2026-08-30_16-29-38](../../eval_output/debug_run/2026-08-30_16-29-38/eval_telemetry.ttl) | Zero action | JSONL empty; HTML/TTL N=0; moved=NaN |

**Mustard correction:** `droid_mustard_test/2026-08-29_21-47-18` (`eval_run_1788040065`) has **zero completed episodes**, not N=1 or 100% lift. Its separate `debug_run` also has N=0. The three `mustard_above_raisin` runs are a distinct DROID task (mustard onto a raisin box), not grey-bin sorting. None of these reports proves a crash, a successful stability pass, or a completed grasp. A 300-step command in guidance is a requested budget, not measured episode duration.

## Duration audit

All numbers below are **environment steps**. Medians use the conventional average of the central pair. `Contact among success` is the first completed `object_on_destination` event restricted to episodes with `success=true`; it is neither full episode duration nor a strict-containment certificate.

| Family / run | All-episode length median | Successful-episode length median | Lift event median | Contact among success median | Historical upper-middle contact |
|---|---|---:|---:|---:|---:|
| Tomato 2026-09-01_04-42-35 | 1000 | 392 | 120 | 392 | 392 |
| Tomato 2026-09-01_04-52-54 | 1000 | — | 254 | — | — |
| Tomato 2026-09-01_16-14-46 | 455 | 455 | 365 | 455 | 455 |
| Tomato 2026-09-01_16-34-46 | 639 | 401 | 143 | 369 | 370 |
| Tomato 2026-09-01_17-27-51 | 630 | 264 | 142 | 226 | 226 |
| Tomato 2026-09-01_18-23-40 | 877 | — | 157 | — | — |
| Tomato 2026-09-01_18-40-38 | 1003.5 | 576 | 240 | 576 | 614 |
| Spam 2026-09-01_19-09-49 | 1000 | 413 | 173 | 413 | 415 |
| Spam 2026-09-01_19-29-40 | 1000 | 434 | 284 | 421 | 421 |
| Spam 2026-09-01_19-53-15 | 1000 | — | 159 | — | — |

- **Tomato N50:** 370 is the upper-middle contact step among successes; conventional median is **369**, successful-episode median **401**, all-episode median **639**.
- **Tomato N52:** 226 is the contact-event median among successes; successful-episode median is **264**, all-episode median **630**. It is not a generic median execution duration.
- **Tomato N42:** 614 is the upper-middle contact step; conventional contact/successful-episode median is **576**, all-episode median **1003.5**.
- **Spam N70:** 175 is the upper-middle **lift** step (conventional median **173**), not placement time. Successful-episode/contact median is **413**; upper-middle contact **415**.
- **Spam N67:** 284 is the **lift** median; contact among successes is **421**, successful-episode median **434**, all-episode median **1000**.
- Tomato N2 episode lengths are **exactly 1000**, not “>1000”. Other false labels cannot all be called timeouts; termination reasons are absent from these records.
- Current default `sim.dt=1/200`, `decimation=4` implies **0.02 s per environment step** ([config](../../isaaclab_arena/environments/isaaclab_arena_manager_based_env_cfg.py), lines 77–91). Thus conditional successful-episode medians are tomato N50 **8.02 s**, N52 **5.28 s**, N42 **11.52 s**; spam N70 **8.26 s**, N67 **8.68 s**. This is a **current-default-derived conversion, not archived run timing**. Wall-clock completion spans and directory-to-TTL intervals are separately recorded in JSON.
- At that conditional step size, chunk32/16/8 means **1.5625/3.125/6.25 Hz**, not the presentation’s doubled frequencies. No run-local timing snapshot proves the executed rate.

## Corrections and provenance limits

1. **Success denominators verified, completeness not certified.** Tomato 0/2, 23/50, 25/52, 6/42 and spam 18/70, 13/67 are accurately transcribed success labels. Omitted runs include tomato **1/20**, **1/1**, **0/1**, and spam **0/2**. The single successful tomato episode is a pilot, not a robustness result.
2. **Conditional conversion:** tomato N50 is **22/47 = 46.8%**, not 23/47 = 48.9%. N52 is **23/44 = 52.3%**, not 25/44 = 56.8%. One and two success-labeled episodes respectively have no completed lift event. Their exact identities and source lines are retained in JSON.
3. **Progress mismatch:** N52 has **11/52 progress-complete episodes**, only **10** also success-labeled. Therefore “23 strict-proximity placements” is not supported by the 23-success-and-lift intersection. Other runs also have success/incomplete and failure/complete combinations. Report the original labels and progress separately; do not silently relabel or promote a height event to retained transport.
4. **Moved is not lift:** e.g. tomato N52 moved **51/52** vs lift **44/52**; spam N67 moved **40/67** vs lift **49/67**. The primary benchmark lift counts do match completed height events, but TTL alone cannot supply them. [Current moved implementation](../../isaaclab_arena/metrics/object_moved.py), lines 42–75, tests whether velocity ever exceeds a threshold. [Height predicate](../../isaaclab_arena/tasks/predicates/spatial.py), lines 21–48, differs from the sustained-lift predicate. Neither current source is a pinned historical runtime snapshot.
5. **Chunk provenance conflicts:** current tomato v1/v2/v3 `policy_config.yaml` files all specify **chunk16**, v4 **chunk8**; all horizons are 32. Claimed historical chunk32 for v1/v2 is not verified. Spam current v1/v2 specify 16/8. Lineage records an intended 16→8 remediation, but **none of the candidate directories archives a launch manifest or run-local policy config**. A causal chunk “sweet spot” is not established by this record set.
6. **Mutable lineage:** tomato v3’s `evaluation` now points at the later **0/1** run, not N52; spam v1 points at the later **0/2**, not N70. `current_version` is 3 and 1 respectively while v4/v2 still exist. Use timestamped run IDs, not the latest/current pointer. Repeated lineage statements that the rollout was limited to 500 steps conflict with recorded episode lengths reaching 1000/2000; treat them as diagnostics, not budgets.
7. **Identity gaps:** TTL `modelWeightsPath` is a policy **class name**, not a checkpoint. There is no run-local checkpoint digest, exact simulator/policy source version, actual chunk receipt, remote diffusion seed, or rollout command. Historical notes mention GR00T-N1.6-DROID, but these artifacts do not pin the served model. Spec family names also differ from internal YAML `env_name`; aliases are preserved.
8. **Mechanism claims remain unverified.** Metadata does not prove sidewall collisions, slip, diffusion-noise causation, or geometric/friction explanations. No HDF5 payloads or video were inspected in this audit; physical containment and sustained grasp are not independently certified.

## Generated/configured only and catalog-only scenarios

- `generated_envs/droid_mustard_bin/` contains **four distinct YAMLs**: evaluated-name `droid_pick_mustard_to_bin` plus `droid_pick_mustard_into_bin`, `droid_mustard_bottle_into_grey_bin`, and `unnamed_env` with **no matching run found**. The first uses `mustard_bottle_hope_robolab`, the second `mustard_ycb_robolab`, others generic `mustard_bottle`; do not collapse them into a HOT3D bottle or purple-crate benchmark. File presence alone does not validate legacy schemas.
- **Cracker→brown box, tuna→small plate, mustard→purple crate:** catalog prompts exist in [scenario catalog](../references/agentic_env_generation/env_gen_test.md), but no matching generated YAML or evaluation evidence was found. These are **catalog-only**, not proven generated or evaluated.
- **Sugar→bowl:** configured DROID GR00T/OpenPI reference jobs exist in `isaaclab_arena_environments/eval_jobs_configs/droid_pnp_srl_gr00t_jobs_config.json` and `experiment_configs/droid_pnp_srl_openpi_experiment.yaml`; no matching run found. These are not the tomato/spam scene or a completed Category B experiment.
- **Raisin→grey bin** and related mustard/butter/tuna RoBoLab task YAMLs exist; no matching evaluation found except the three zero-episode `mustard_above_raisin` reports. Existing task templates are not generated-run evidence. JSON lists the exact related source paths.

## Coverage and verification

Filesystem walk covered `eval_output` (639 files), `outputs` (158), `generated_envs` (142), and mounted `/eval` (205), including directory-name discovery, text content search, and a follow-up scan for graph names discovered in scenario YAMLs. Logs and `.agents/references` were checked for context; no extra Category B run was identified in `/eval`. HDF5/binary payloads were excluded. Generic empty artifacts with no scenario-identifying metadata cannot be attributed to Category B and are not invented as such.

The JSON records every discovered candidate, including N=0 reports, and retains source hashes for reproducibility. Checks: exact per-run identity uniqueness; success/lift intersection; TTL and HTML N/success reconciliation; current source files exist; no rates for N=0. Repository-era code defaults and historical notes are explicitly distinguished from runtime provenance.
