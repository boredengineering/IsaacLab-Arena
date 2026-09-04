# Plan: G1 Policy Transfer Diagnosis & Height Invariance (Scenario C1 Follow-On)

> [!IMPORTANT]
> **Status**: ACTIVE, **re-scoped 2026-09-04**. Supersedes the "next steps" list drafted on
> 2026-09-03.
>
> **Goal (explicit)**: get `nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace` to *actually pick the
> apple on the maple table*. Not to characterise why it cannot — to make it work.
>
> **This plan's title is now partly misleading and is kept for continuity.** Height invariance was
> measured on 2026-09-03 and found **in tolerance (6.5 cm)**. The height sweep is demoted from
> Phase 1 to an optional robustness check. §1b records what replaced it.
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

## 1b. What Replaced the Height Hypothesis (2026-09-04)

§1 argued that a hand-authored tolerance was driving the prioritisation, and that measurement had
to precede anything expensive. That argument was right, and following it dismantled the plan's own
leading hypothesis. Three rounds of measurement later:

| Invariant | 2026-09-03 belief | Measured | Where |
| :--- | :--- | :--- | :--- |
| `surface_height_rel_pelvis` | violated, 5.6× tolerance, **dominant** | **6.5 cm — in tolerance** | `measure_embodiment_frames.py` |
| `arm_laterality` | violated (C1 wants right, corpus is left) | **matches** (both left) | frame measurement |
| `prompt_alignment` | **satisfied** | **violated** — we fed a string absent from the corpus | `meta/tasks.jsonl` |
| `visual_domain` | violated | **violated, and now quantified**: 2.04× brightness, 71× red-dominant pixels | frame-0 comparison |
| — (unmodelled) | — | **harness fabricating episodes** | `v13` A/B |

Two of the plan's four ranked violations evaporated, one inverted sign, and the largest single
defect was in a component the ontology did not model at all. §10's falsification criteria called
both outcomes in advance, which is the one encouraging result here.

### The methodological finding, which matters more than any single correction

Every invariant that turned out wrong was **asserted in prose and never traced to an artefact**.
The height tolerance was hand-authored. The corpus prompt was recorded from memory into a plan
document and then read back as fact for ten iterations. Both were *confidently* wrong, and both
produced a coherent-looking ranking that sent effort in the wrong direction.

**Required change**: a `TrainingInvariant` must carry provenance — the artefact path and the
measurement that produced its reference value — and the planner must visibly distinguish
`measured` from `asserted`, refusing to rank on the latter. An unmeasured invariant is not a weak
invariant; it is an unfalsifiable one.

### The new dominant hypothesis, and its mechanism

The policy moves purposefully for 1000 steps and reaches a symmetric, target-independent posture.
That is the signature of **regression to the training-set mean trajectory**, and GR00T's
architecture explains why it is available: the VLM backbone is **frozen**, and only the DiT action
head and projectors train, so the imitation objective can be satisfied from **proprioceptive state
alone** — the *proprioception shift* / causal-confusion shortcut.

The appearance measurement supplies the reason vision cannot rescue it here: in the corpus,
"small reddish blob on a dark matte surface" is a near-perfect detector for the apple; the maple
table's wood grain occupies the **same colour region**, multiplying red-dominant pixels 71× and
destroying the cue.

These two findings are complementary, not competing: a policy that leaned on a fragile colour cue
*and* had a proprioceptive shortcut available will fall back to the shortcut precisely when the cue
breaks. That is the hypothesis Phase 0.5 tests directly.

---

## 1c. Phase 0.5 — Ground Truth Before Anything Else (**NEW, now the first action**)

The official GR00T workflow validates a checkpoint by **open-loop evaluation before closed-loop
rollout**. We skipped it for ten iterations and paid for it. Everything required is already local:

| Asset | Location | Status |
| :--- | :--- | :--- |
| Open-loop harness | `submodules/Isaac-GR00T/gr00t/eval/open_loop_eval.py` | present |
| Corpus dataset | `/datasets/.../Arena-G1-Static-PickNPlace-Task` (251 eps, 35,066 frames) | present |
| Checkpoint | HF cache | present |
| `nvidia/Cosmos-Reason2-2B` backbone | HF cache | present — **unblocks the activation probes** previously recorded as blocked on gated access |

### Two tests, run together

**(a) Open-loop fidelity.** Replay corpus trajectories, compare predicted vs. ground-truth actions,
record per-dimension MSE. Separates "checkpoint is broken / mis-normalised" from "checkpoint is
fine, deployment is wrong."

**(b) Modality ablation.** The decisive test, and the one this plan previously lacked. For fixed
state, re-run inference with the image intact, scrambled, and blanked; and for fixed image, with
state perturbed. Compare action chunks.

| Result | Interpretation | Consequence |
| :--- | :--- | :--- |
| Scrambling the image barely changes the chunk | policy is **state-driven**; the shortcut is real | Phase 3 augmentation is mandatory, not optional; appearance fixes alone cannot work |
| Chunk changes substantially with the image | vision **is** used | the fault is *what* vision encodes here → photometric/framing alignment (Pathway 1/2) should work |
| Perturbing state dominates everything | proprioception over-reliance confirmed quantitatively | state dropout is the specific fix |

> [!CAUTION]
> **Do not accept a good open-loop plot as clearance.** Causal confusion is *defined* by low
> open-loop loss with poor closed-loop performance, so (a) passing is consistent with the shortcut
> hypothesis, not evidence against it. (a) without (b) is exactly the mistake that would let this
> plan repeat its own history. Only (b) discriminates.

`measure_ablation_sensitivity` and `BlockConditioningDelta` in `policy_activation_probe.py` already
implement the machinery; Phase 0.5 is largely wiring them to the now-available backbone.

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

## 5b. Phase 3′ — The Two Interventions That Target the Measured Mechanism (**NEW**)

Phase 3 as originally written scoped a fine-tune around *height augmentation*. Height is in
tolerance, so that scope is void. It is replaced by the two interventions that address what was
actually measured, ordered cheapest-first.

### Intervention 1 — Photometric alignment (hours, no training)

The C1 specification pins the table asset, the objects, the layout and the task. It does **not**
pin dome-light intensity or material albedo. Those are renderer nuisance parameters, and the
literature says they are the *dominant* transfer axis: a visual-DR ablation reports no-randomisation
41%, camera-only 48%, **lighting-only 87%**, full 90%
([Robust Visual Sim-to-Real Transfer](https://arxiv.org/pdf/2307.15320)).

Target the measured statistics, not an aesthetic:

| Statistic | Corpus | Target now | Goal |
| :--- | :--- | :--- | :--- |
| Mean frame brightness | 50.8 | 103.5 | within ~15% of 50.8 |
| Red-dominant pixel count | 1,169 | 82,966 | within ~2× of 1,169 |
| Apple bbox | 46×48 px | swamped | separable blob |

Two knobs: dome-light intensity, and the table material's albedo/roughness. Reducing exposure alone
darkens the wood but leaves its **hue** inside the apple's colour region, so the 71× figure will
only partly fall — the albedo change is likely the load-bearing one. Both require a schema addition
(the graph spec currently has no appearance block at all); tracked in the implementation plan.

**This is a genuine test, not a fix by fiat.** If aligning photometry produces a lift, §1b's
mechanism is confirmed. If it does not, the colour-cue account is wrong and the shortcut account
(Intervention 2) carries the whole explanation.

> [!NOTE]
> Report the metric on the *unaligned* scene too, permanently. A benchmark that only reports its
> best-lit configuration is measuring the lighting, not the pipeline.

### Intervention 2 — Re-finetune on the existing corpus, with shortcut-breaking augmentation

**No new demonstrations. Target scene untouched.** All 251 corpus episodes are local, so this is
squarely the §7b decision — adapt the model, not the scene — and it attacks the frozen-VLM
shortcut identified in §1b rather than a symptom.

| Knob | Why | Source |
| :--- | :--- | :--- |
| **State dropout** (mask proprioception with high probability) | removes the shortcut's availability, forcing the action head onto vision | NVIDIA recipe; ChauffeurNet-style dropout, ~80% masking reported |
| **Colour / photometric jitter** on recorded frames | makes "reddish blob on dark matte" insufficient, so the policy must encode shape and context | NVIDIA recipe; classic visual DR |
| **`--tune-visual`** | with the encoder frozen, no augmentation can change what features exist | GR00T finetuning guide |
| Background compositing (optional) | corpus backgrounds are dense and near-constant; target is an empty void | SIMPLER varies background/lighting/distractors/texture |

Expected honest ceiling: dropout is well-attested but **partial** — in the proprioception-shift
study, dropout and PrimeNet land *between* full-state BC and vision-only BC. Plan for a
recoverable fraction of the gap, not a solved task.

**Required ablation, cheap and diagnostic**: train a vision-only (no-proprioception) arm. If it
beats the full-state policy, the shortcut is confirmed and that arm is also the performance floor
any mitigation must clear.

### Intervention 3 — Few-shot adaptation (**last resort**)

10–20 `maple_table` demonstrations with LoRA / object-centric adaptation
([ControlVLA](https://alphaxiv.org/overview/2506.16211v1): 10–20 demos → 76.7% vs 20.8%;
[PriorVLA](https://arxiv.org/html/2605.10925): 10 demos → 48% in-distribution, 32% OOD).

This is a **softened Pathway B** and inherits its objection: it requires new demonstrations on the
target scene. Keep it last, and if it is reached, say plainly that the zero-new-demo transfer
premise did not hold rather than relabelling it a success.

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

## 9. Recommended Order (**revised 2026-09-04**)

The previous ordering led with the height sweep. Height is in tolerance, so that ordering is void.

| # | Action | Cost | Gates what |
| :--- | :--- | :--- | :--- |
| **1** | **Phase 0.5 (§1c)** — open-loop eval **+ modality ablation** | hours, no training | *everything*. Determines whether the fault is normalisation, vision-grounding, or the state shortcut |
| **2** | Re-derive the two mis-stated invariants from artefacts, add provenance | hours | the planner's ranking, which is currently built on one false and one retracted value |
| **3** | **Intervention 1 (§5b)** — photometric alignment | hours | tests the colour-cue mechanism; may produce a lift on its own |
| **4** | Pre-flight gate (Phase 4 item 1) | low | independent, immediately useful |
| **5** | **Intervention 2 (§5b)** — augmented re-finetune on the existing corpus | 1 training run | the primary remediation if step 1 shows the state shortcut |
| **6** | Height sweep (old Phase 1) — **demoted** to robustness characterisation | moderate | nothing on the critical path |
| **7** | Intervention 3 — few-shot on target demos | teleop + training | last resort only |

Steps 1–2 are pure measurement and must complete before any GPU-week is committed. That is the same
discipline §1 argued for; the difference is that it now has a track record of overturning the
plan's own hypotheses three times.

---

## 10. What Would Falsify This Plan (**revised 2026-09-04**)

The 2026-09-03 criteria are retained below for the record, because two of them **fired**. New
criteria for the current hypothesis:

- **Modality ablation shows the chunk changes substantially with the image** → the state-shortcut
  account is wrong; vision is used, and the fault is what it encodes. Intervention 2's augmentation
  is then mis-targeted and Interventions 1–2 should be reordered toward framing/appearance.
- **Photometric alignment produces no lift and open-loop MSE is low** → the colour-cue mechanism
  (§1b) is wrong despite the 71× measurement, and appearance is a correlate rather than a cause.
- **Open-loop MSE is high on corpus data** → the entire OOD framing is premature *again*; the fault
  is normalisation metadata or modality wiring, and no scene-side or training-side work should
  start until it is fixed.
- **Augmented re-finetune recovers nothing** → the zero-new-demonstration premise fails, and
  Pathway B's objection was correct all along. Say so explicitly rather than sliding to
  Intervention 3 and calling the result a transfer success.
- **The vision-only ablation arm underperforms the full-state policy** → there is no proprioceptive
  shortcut to break, and state dropout is wasted effort.

### 2026-09-03 criteria — outcome

| Criterion | Outcome |
| :--- | :--- |
| A/B/C all succeed → height mis-ranked, remediation ordering wrong | **FIRED.** Height measured in tolerance; ordering was wrong |
| Condition A fails → fault is in the stack or harness, OOD framing premature | **FIRED.** The settle-loop hold action was fabricating episodes |
| Mimic yield near zero → "cheap" characterisation wrong | not yet tested (Phase 3 descoped) |
| Corpus centroid close → down-weight `vision_domain_ood` | not yet tested; probes now unblocked (§1c) |

Two of four predicted the failure correctly *and in advance*. The criteria were worth writing; the
lesson is that they should have gated the ten iterations that ran before them.

---

## 11. References

- `.agents/references/plans/g1_tabletop_apple_remediation_plan.md` — the C1 autopsy and Pathway C
- `.agents/references/plans/depth_alignment_integration_plan.md` — complete as of 2026-09-03
- `.agents/memory/sessions/20260903_180000_modelgraph.md` — ontology, probes, planner
- `.agents/memory/sessions/20260903_043800_c1blockers.md` — the blockers this plan responds to
- `.agents/memory/sessions/20260827_015608_sm120dock.md` — SM120 toolchain pins

### External research (2026-09-04)

Checkpoint and framework:
- [GN1x-Tuned-Arena-G1-Static-PickNPlace model card](https://huggingface.co/nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace) — 251 eps / 35,066 frames @ 50 Hz, XR teleop, from `GR00T-N1.7-3B`
- [New-embodiment finetuning guide](https://github.com/NVIDIA/Isaac-GR00T/blob/main/getting_started/3_0_new_embodiment_finetuning.md) — state dropout, colour jitter, `--tune-visual` / `--tune-llm`
- [Isaac-GR00T evaluation & benchmarking](https://deepwiki.com/NVIDIA/Isaac-GR00T/7-evaluation-and-benchmarking) — open-loop-before-closed-loop workflow

Same symptom reported against this codebase:
- [#200](https://github.com/NVIDIA/Isaac-GR00T/issues/200) — "moves toward the target but lands ~5 cm away", 7/10
- [#210](https://github.com/NVIDIA/Isaac-GR00T/issues/210) — arm reaches *above* the object and stops
- [#241](https://github.com/NVIDIA/Isaac-GR00T/issues/241) — testing whether the policy conditions on vision at all
- [#408](https://github.com/NVIDIA/Isaac-GR00T/issues/408), [#213](https://github.com/NVIDIA/Isaac-GR00T/issues/213) — `NEW_EMBODIMENT` metadata / stats failures
- [#314](https://github.com/NVIDIA/Isaac-GR00T/issues/314) — instability when `action_dim > 32` (ours is 43/50)

Shortcut learning and causal confusion:
- [Causal Confusion in Imitation Learning](https://proceedings.neurips.cc/paper_files/paper/9343-causal-confusion-in-imitation-learning.pdf) — **low open-loop loss, poor closed-loop performance**
- [Adapt Your Body: Mitigating Proprioception Shifts](https://www.researchgate.net/publication/393184798_Adapt_Your_Body_Mitigating_Proprioception_Shifts_in_Imitation_Learning) — proprioception shift; dropout is partial
- [Fighting Copycat Agents](https://arxiv.org/pdf/2010.14876), [GABRIL](https://arxiv.org/pdf/2507.19647), [Initial State Interventions](https://arxiv.org/pdf/2307.15980)

Viewpoint and appearance sensitivity:
- [AnyCamVLA](https://arxiv.org/html/2603.05868v1) — $\pi_0$ 65.3% → **6.3% under a 15° camera rotation**; test-time canonicalisation
- [OC-VLA](https://arxiv.org/html/2508.13103) — actions re-parameterised into camera frame
- [Robust Visual Sim-to-Real Transfer](https://arxiv.org/pdf/2307.15320) — DR ablation: 41% / 48% / **87% lighting-only** / 90%
- [SIMPLER](https://arxiv.org/pdf/2405.05941) — sim-to-sim variation over background, lighting, distractors, table texture
- [IDAPT](https://arxiv.org/pdf/2107.00339) — grounding source env in target beats DR at high randomisation

Few-shot adaptation:
- [ControlVLA](https://alphaxiv.org/overview/2506.16211v1) — 10–20 demos → 76.7% vs 20.8%
- [PriorVLA](https://arxiv.org/html/2605.10925) — 10 demos → 48% in-dist / 32% OOD, 25% of params
- [Domain Arithmetic](https://arxiv.org/pdf/2607.00666) — one demo per scene, LoRA in the vision encoder
