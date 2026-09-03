# Plan: G1 Policy Transfer Diagnosis & Height Invariance (Scenario C1 Follow-On)

> [!IMPORTANT]
> **Status**: ACTIVE — supersedes the "next steps" list drafted on 2026-09-03.
> **Decision context**: Pathways A (rebuild the benchmark on the shelf scene) and B (collect demos on `maple_table`) were rejected. The chosen direction is **fine-tune on the galileo scene and transfer to `maple_table`**, with the generation pipeline responsible for diagnosing and closing the transfer gap.
> **What changed during review**: the original step 1 recommended fine-tuning with height variation. Investigation found (a) the tolerance driving that recommendation was never measured, and (b) the galileo scene already contains the shelf tiers needed to measure it. The plan below therefore leads with measurement, not training.

---

## 1. The Correction That Reordered This Plan

The `arena:TrainingInvariant` for `surface_height_rel_pelvis` carries `tolerance = 0.15 m`. **That number was authored by hand, not measured.** Every quantitative claim derived from it inherits that:

| Claim | Depends on the tolerance? |
| :--- | :--- |
| The `maple_table` scene is out of distribution on height | **No** — holds for any tolerance in [0.05, 0.40] m |
| The departure is "5.6× tolerance" | **Yes** — ranges from 2× to 16× across that interval |
| `vertical_reach_ood` outranks `arm_laterality_mismatch` / `vision_domain_ood` | **Yes** — the ranking is a direct function of the assumed tolerances |

So the verdict is robust and the *prioritisation* is not. Since the prioritisation is what selects the remediation, and the remediation is what costs GPU-weeks, the tolerance must be measured before anything expensive is committed to.

The measurement is cheap, requires **no training**, and is described in Phase 1.

### Secondary correction: Mimic is not turnkey here

The original suggestion — "retarget the existing 200 demos across a height sweep with Mimic" — assumed infrastructure that does not exist in the shape required:

- `G1PickAndPlaceMimicEnvCfg` (`isaaclab_arena/tasks/pick_and_place_task.py:391`) hard-raises on anything but `ArmMode.DUAL_ARM` and sets `use_navigation_controller = True`, with a four-phase `navigate_to_table → navigate_turn_inplace → navigate_to_bin → final` body sequence. It is the **locomanipulation** config.
- The static tabletop task has **no** bespoke G1 mimic config; `test_g1_static_pick_and_place.py` passes no `mimic_env_cfg_factory` and falls through to the generic `PickPlaceMimicEnvCfg`.
- Every `SubTaskConfig` is anchored to a single `object_ref` with `selection_strategy="nearest_neighbor_object"`. Mimic retargets segments into new **object frames**; the recorded whole-body posture (torso pitch, knee bend of a reach-to-knee-height motion) is replayed, not re-solved.

Raising a target 80 cm is formally an object-pose change, so it is mechanically in-envelope. The open question is *yield*: whether transformed segments survive the success filter, and whether the survivors are dynamically sane or merely kinematically valid. With `generation_num_trials = 100` and `max_num_failures = 25`, a bad transform fails fast and loudly — which makes this cheap to falsify but not safe to assume.

**Consequence**: Mimic-based height augmentation is a Phase 3 option contingent on Phase 1 results, not a Phase 1 action.

---

## 2. Phase 0 — Already Validated (2026-09-03)

### The false-success detector fires on real artifacts

The `harness_false_success` check added to `EvaluationDiagnosticOracle` was written against the JSONL shape quoted in the C1 plan, not against the files. It has now been run over all 27 `episode_results_rank*.jsonl` under `eval_output/g1_tabletop_apple_to_plate/` (15 non-empty):

```
DETECTOR FIRES: 1/1 in v9_full/2026-09-02_23-13-55/  shortest = 15 steps
DETECTOR FIRES: 1/4 in 2026-09-02_21-41-15/          shortest = 31 steps
```

- The 15-step hit is exactly the record documented in the C1 autopsy (`success: true`, `episode_length: 15`, `progress.overall_score: 0.0`).
- The 31-step hit in `2026-09-02_21-41-15` is a **second occurrence that was not previously identified**, so the trap fired more than once across the v9-era runs.
- Record schema confirmed: `['env_id', 'episode_in_env', 'episode_length', 'job_name', 'language_instruction', 'progress', 'seed', 'success', 'timestamp']`. No field-name mismatch; the detector needs no changes.

**Artifact hygiene issue found in passing**: `eval_output/g1_tabletop_apple_to_plate/v9_eval/2026-09-02_23-10-27/episode_results_rank0.jsonl` is **0 bytes** while its sibling `eval_telemetry.ttl` and `index.html` were written. A run that emits telemetry but no episode records will read as "no data" rather than "failed", and the diagnostic oracle silently falls through to `object_moved_rate`. Worth a guard: refuse to write `eval_telemetry.ttl` when zero episodes were recorded.

### Pathway C is implemented and verified

Covered in `g1_tabletop_apple_remediation_plan.md` §7 and session `modelgraph`. Verified in the Isaac Sim container: the same gravity drop that fires success with the gate off never fires it with the gate on.

---

## 3. Phase 1 — Measure the Height Tolerance (No Training)

**This is the gating experiment. Nothing downstream should be committed to before it runs.**

### The galileo scene already has the tiers

`FIXTURE_SECTOR_BOUNDS["galileo_locomanip"]` in `spatial_geometric_oracle.py:36` already declares three decks, and `get_fixture_sector_bounds` resolves them by name. `surface_sector` is a first-class spec field (`arena_env_graph_types.py:339`) consumed by `object_placer.py:532`. **A height sweep is therefore a YAML change — no new assets, no geometry authoring.**

With the G1 base at world `z = 0` and the pelvis at `+0.75` (the convention in `spatial_geometric_oracle.py:423` and `policy_capability_graph._pelvis_height`):

| Sector | Deck world z | Height rel. pelvis | Role in the sweep |
| :--- | ---: | ---: | :--- |
| `galileo_locomanip` / `shelf_tier_1` | −0.03 | **−0.78 m** | Corpus height. Positive control — must succeed, or the stack is at fault |
| `galileo_locomanip` / `shelf_tier_2` | +0.50 | **−0.25 m** | Intermediate |
| `galileo_locomanip` / `shelf_tier_3` | +0.90 | **+0.15 m** | Above the maple table — the sweep *brackets* the target rather than extrapolating to it |
| `maple_table_robolab` (v9 pose) | ~0.755 | **+0.03 m** | The actual target |
| `wireshelving_a01_vomp_robolab` / `shelf_tier_1` | +0.76 | **+0.01 m** | Target height in a shelf-like visual domain |

`shelf_tier_1` at −0.78 m lands within 2 cm of the declared corpus invariant (−0.8015 m), which independently corroborates that invariant.

### The confound, and how these tiers break it

The C1 scene varies height **and** visual domain **and** laterality **and** prompt simultaneously. Five out-of-tolerance axes cannot be attributed from one failing run. The tiers permit a partial factorial that isolates height:

| Condition | Height rel. pelvis | Visual domain | Isolates |
| :--- | ---: | :--- | :--- |
| A — galileo `shelf_tier_1` | −0.78 | corpus | Positive control |
| B — galileo `shelf_tier_2` | −0.25 | corpus | Height only |
| C — galileo `shelf_tier_3` | +0.15 | corpus | Height only, past target |
| D — wireshelving `shelf_tier_1` | +0.01 | shelf-like, not corpus | Height at target + mild visual shift |
| E — `maple_table` (v9) | +0.03 | fully novel | Height + visual (the failing case) |

Hold laterality and prompt at the **corpus** values throughout (manipuland front-left, `"move the apple to the plate"`), so those two axes are constant and cannot contribute to the contrast. This is a diagnostic experiment, not a benchmark run — the C1 right-arm specification is deliberately not honoured here.

Read the result as follows:

- **A succeeds, B/C fail** → height is the blocking axis. The tolerance is bounded by where the curve breaks; proceed to Phase 3 height augmentation.
- **A/B/C all succeed, D/E fail** → height is **not** the blocker and `vertical_reach_ood` is mis-ranked. The blocker is visual, and the whole remediation ordering in `policy_capability_graph` needs revising. This outcome would invalidate the current dominant-mode conclusion, and it is a live possibility precisely because the tolerance was assumed.
- **A fails** → the stack, not the distribution, is at fault. Stop and re-verify against `galileo_g1_static_pick_and_place`, which is documented at `success_rate: 1.0`.

### Sizing

~20 episodes per condition at 2000 steps. Five conditions ≈ 100 episodes. With `--num_envs 4` at the documented 15–20 steps/s this is hours, not days, and consumes zero training compute.

### Deliverable

Replace the hand-authored tolerance with a measured one, and record its provenance:

```python
TrainingInvariant(
    axis="surface_height_rel_pelvis",
    numeric_value=-0.8015,
    tolerance=<measured>,   # from the Phase 1 sweep, not assumed
    ...
)
```

The invariant then becomes an empirical property with an evaluation behind it, which is the standard the rest of the registry should eventually be held to. `compress_action_chunk`'s efficacy of 0.35 is already measured this way (B1 v4: conversion 52% → 16%); the invariants should match.

---

## 4. Phase 2 — Point the Activation Probes at the Real Checkpoint

### The blocker: probes need in-process weights

`vision_ablation_sensitivity`, `vl_conditioning_delta_probe`, `action_chunk_dynamics_probe`, and `vl_embedding_ood_distance` all carry `requires_policy_weights=True`. They cannot run against the ZMQ server on `127.0.0.1:5557`, and `select_next_diagnostic` correctly refuses to offer them in that configuration. Two options:

1. **Standalone script (recommended)** — load the checkpoint locally, replay one recorded observation from a v9 rollout, run `probe_policy_inference`. Non-invasive, and sufficient to answer "is the policy conditioning on the image at all".
2. **Server-side probe endpoint** — the GR00T server already holds the weights; add an entry point returning a `ProbeReport` over the wire. More useful long-term, more invasive, and touches the policy-server contract.

Start with (1). Escalate to (2) only if probing becomes routine.

### Validation status

`test_policy_activation_probe.py` (15 tests) exercises hook navigation, role bucketing, seeding, and ablation semantics against a stand-in with GR00T's module topology (`backbone`, `action_head.model.transformer_blocks`, `action_head.vlln`, `action_head.action_decoder`). **It does not validate against the real `Gr00tN1d7`.** First contact with the real checkpoint should confirm:

- `_resolve_action_head` / `_resolve_backbone` find the modules through whatever wrapper the policy path uses.
- The backbone's `BatchFeature` output exposes `backbone_features` and `image_mask` with matching leading dimensions (the probe falls back to pooling over all tokens and emits a note if not).
- `_block_role` parity matches the loaded config's `attend_text_every_n_blocks`, which the probe reads from `action_head.config` rather than assuming.

### The corpus centroid

`vl_embedding_ood_distance` is registered but **inert** until a corpus image-token centroid exists. One pass over the 200 demo episodes with the probe's backbone hook, mean-pooling image-masked tokens, gives it. This measures OOD in the representation the action head actually consumes, which is strictly more relevant than pixel-space or depth-space comparison — and it is the cheapest way to answer the question Phase 3 depends on (see §5).

---

## 5. Phase 3 — Fine-Tune Scope, Decided by Phases 1 and 2

### The finding that constrains this phase

`submodules/Isaac-GR00T/gr00t/configs/finetune_config.py:49-58`:

```python
tune_llm = False          # frozen
tune_visual = False       # frozen
tune_projector = True     # tuned
tune_diffusion_model = True   # tuned
```

The **vision encoder is frozen by default**, and N1.5 onward freezes the VLM deliberately to preserve language grounding and generalization. This splits the two axes cleanly:

| Axis | Lives in | Tuned by default? | Mechanism |
| :--- | :--- | :--- | :--- |
| **Height / reach prior** | DiT action head | **Yes** | Direct — retraining the module that holds the prior |
| **Visual domain** | frozen vision encoder | **No** | Indirect — projector + DiT learn invariance to whatever the frozen encoder emits |

So height adaptation and the available lever line up well. Visual adaptation is weaker than the original plan implied: with `tune_visual=False` you are not adapting the encoder, and if its features for a bright maple deck are simply far from anything in the corpus, the projector has limited material to work with. `random_rotation_angle` and `color_jitter_params` are the built-in augmentation knobs; `state_dropout_prob` defaults to 0.2.

**This is exactly what the Phase 2 centroid measurement resolves.** If the frozen encoder's `maple_table` embedding sits close to the corpus centroid, the projector has a tractable job and default flags suffice. If it sits far, `tune_visual=True` becomes necessary — at a real cost in generalization, and a decision worth making on evidence.

### Height augmentation options, cheapest first

1. **Sector-varied re-collection in the galileo scene.** Record or generate demos across `shelf_tier_1/2/3`. Keeps the visual domain constant (so it does not confound), uses existing assets, and directly targets the reach prior. Note this requires a **static** G1 mimic config or teleop — the existing `G1PickAndPlaceMimicEnvCfg` is locomanip-only (§1).
2. **Mimic retargeting across tiers.** Cheaper if it works; yield is the open question. Falsify with a single 100-trial generation run at `shelf_tier_2` and inspect both the success rate and a replay of the survivors for dynamically implausible whole-body motion.
3. **Small teleop supplement mixed with the 200 galileo demos.** If Mimic yield is poor, 20–30 genuine chest-height demos co-trained with the existing corpus may beat 200 synthetic ones of doubtful quality, because genuine whole-body coordination at the new height is the thing being learned.

### Post-fine-tune bookkeeping

Register a **new** `PolicyProfile` whose invariants reflect the widened training distribution — a measured `surface_height_rel_pelvis` tolerance, or the axis dropped entirely if height was randomised. Transfer readiness against `maple_table` then becomes a re-measurement rather than a re-argument, which is the property the whole graph exists to provide.

### The alternative that avoids retraining

`cartesian_vertical_offset_adapter` (efficacy 0.35, effort `config`) adds a vertical translation to the policy's end-effector predictions. It is the only scene-preserving, non-training remediation for `vertical_reach_ood` in the registry. Cheap enough for one experiment; its low efficacy reflects that it fights the closed-loop visual feedback the diffusion head expects. Worth falsifying, not worth planning around.

---

## 6. Phase 4 — Close the Loop

`build_policy_diagnostic_state` and `diagnose_transfer_readiness` are implemented and tested, but **nothing invokes them**. The graph currently describes; it does not yet decide.

1. **Pre-flight gate** — call `diagnose_transfer_readiness` in `isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py` before Isaac Sim launches, so a spec that violates a policy's invariants is caught for the price of arithmetic instead of a 2000-step rollout. The runner already exposes `--mode {full,resolve,build,schema,catalog,auto_heal}` (line 56); this belongs on the `build` and `full` paths.
2. **Planner-driven healing** — call `build_policy_diagnostic_state` on the `auto_heal` path so belief-ranked technique selection replaces the current fixed rule ordering, and emit `emit_policy_diagnostics_ttl` alongside the existing `lineage.ttl`.
3. **Neo4j mirror** — `sync_policy_diagnostics_to_neo4j` on the same path, so the `VIOLATES_INVARIANT` edges accumulate across environments and the question "which remediation actually moved the metric, historically" becomes a Cypher query rather than a memory exercise.

Ordering note: (1) is independently valuable and low-risk. (2) should wait until Phase 1 has corrected the tolerances, or the planner will confidently rank on assumed numbers.

---

## 7. Hygiene and Blockers

| Item | Detail | Owner decision needed |
| :--- | :--- | :--- |
| **`pre-commit` never ran** | Absent from both the devcontainer and `isaaclab_arena:latest`; it is host-only per `AGENTS.md`. black/isort/codespell have not seen any of the `modelgraph` work. Line length (≤120), trailing whitespace, EOF newlines, and import grouping were hand-checked. | **Blocker before commit** |
| **Branch strategy** | Currently on `dev/0.3.0-prerelease`. `AGENTS.md` requires `<username>/<type>/<short-description>` + PR against `main`; recent history commits straight to the dev branch. A branch is advisable since this touches core termination. | Yes |
| **Test-environment split** | `isaaclab_arena:latest` lacks `rdflib`; the devcontainer lacks `isaaclab`. `test_eval_self_healing.py`, `test_rdf_lowering.py`, `test_telemetry_to_prov.py` run in **neither** — that suite is silently unguarded. Fix is adding `rdflib`/`neo4j` to the sim image, which touches `docker/`. | Yes — `AGENTS.md` says ask first |
| **Duplicate auditor** | `isaaclab_arena_examples/tools/depth_spatial_auditor.py` is a byte-identical 466-line copy of the packaged module, imported by nothing. Copied rather than moved; will drift. | Delete the `examples/tools` copy |
| **Empty-run guard** | See §2 — a run that writes `eval_telemetry.ttl` with a 0-byte episode JSONL reads as "no data" rather than "failed". | Add the guard |

---

## 8. Hardware Feasibility

Measured on this host:

```
NVIDIA RTX PRO 6000 Blackwell Workstation Edition
97,887 MiB VRAM   |   compute capability 12.0 (SM120)   |   driver 595.84
```

- **Default fine-tune (projector + DiT, VLM frozen)**: comfortable. The N1.7 DiT is 32 layers at hidden 1536 — order a few hundred million trainable parameters out of ~3B. Optimiser states plus activations sit well inside 96 GB; batch size is more likely to be tuned upward than to fight OOM.
- **Full-model (`tune_llm=True`)**: plausible at this capacity, but not indicated by anything in the diagnosis.
- **VRAM is not the constraint.** Nor, as it turns out, are the kernels:
  - **SM120 kernel compatibility — VERIFIED 2026-09-03.** `isaaclab_arena_examples/tools/verify_gr00t_training_kernels.py` confirms in `gr00t-dev:latest` that `sm_120` is natively compiled in, flash-attn 2.7.3 forward+backward works, SDPA backward works at the DiT's real shapes (32 heads x head_dim 48, asymmetric kv_dim 2048), and the **real 550 M-parameter `AlternateVLDiT` completes forward+backward with all 232 gradient tensors finite**. Both the default and escalated fine-tune configs are kernel-ready.
    Note the trained path is **SDPA, not flash-attn**: flash-attn serves only the Qwen3 backbone, which the default config freezes. And the `dit.py` math-SDPA workaround guards sm**121** (Spark) only, so it is inactive here — `GR00T_DIT_SDPA_MODE=math` is the escape hatch if needed. See the implementation plan §9.5 for the full table and a discrepancy against the `sm120dock` pins.
  - **Data generation wall-clock** is the real constraint. Isaac Sim rollouts and Mimic generation are largely serial and dominate the schedule; 96 GB does not help. `--num_envs` does.

---

## 9. Recommended Order

1. **Phase 1 height sweep** — no training, corrects the tolerance, and can invalidate the current dominant-mode ranking. Gates everything expensive.
2. **Phase 2 corpus centroid + one local probe run** — cheap, and determines whether `tune_visual` must be unfrozen in Phase 3.
3. **Phase 4 item (1)** the pre-flight gate — independent, low-risk, immediately useful.
4. **Phase 3** fine-tune, scoped by what (1) and (2) actually showed.
5. **Phase 4 items (2)–(3)** once the tolerances are measured rather than assumed.

Hygiene (§7) runs in parallel and blocks only the commit.

---

## 10. What Would Falsify This Plan

Stated up front so the Phase 1 result is read honestly rather than fitted:

- **A/B/C all succeed** (§3) → height is not the blocker, `vertical_reach_ood` is mis-ranked, and the remediation ordering in `policy_capability_graph` is wrong. Phase 3 would then target the visual axis, and `tune_visual` becomes the central question rather than a contingency.
- **Condition A fails** → the fault is in the stack or the harness, not the distribution, and the entire OOD framing is premature.
- **Mimic yield at `shelf_tier_2` is near zero** → height augmentation needs teleop or a motion planner, and the "cheap" characterisation of Phase 3 was wrong.
- **The corpus centroid shows `maple_table` embeddings are close to the corpus** → the visual domain shift is smaller than the depth audit's pixel-space and geometry-space evidence suggested, and `vision_domain_ood` should be down-weighted.

---

## 11. References

- `.agents/references/plans/g1_tabletop_apple_remediation_plan.md` — the C1 autopsy and Pathway C
- `.agents/references/plans/depth_alignment_integration_plan.md` — complete as of 2026-09-03
- `.agents/memory/sessions/20260903_180000_modelgraph.md` — ontology, probes, planner
- `.agents/memory/sessions/20260903_043800_c1blockers.md` — the blockers this plan responds to
- `.agents/memory/sessions/20260827_015608_sm120dock.md` — SM120 toolchain pins
