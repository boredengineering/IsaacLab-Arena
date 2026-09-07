# DA3 + Spatial Forcing pipeline for the G1 apple pick-and-place

**Status:** v1.1 (2026-09-06) -- **pipeline complete end to end; the method result is null.**
Dataset -> DA3 depth annotation -> SF finetune -> RGB-only serving -> measured comparison all run.
`align` is 0.86 cm *worse* than a matched control on vertical reach error, not significantly
(Welch *t* = 1.24, n = 20/arm), with identical success rates. See S4.

**And the base-model control shows the programme's premise was wrong.** The finetunes changed
nothing (+0.2 mm lateral, +1.7 mm vertical vs the base checkpoint), so the null is valid -- but the
base policy is over the apple in only 4/20 episodes, so "accurate bearing, wrong range" -- the
diagnosis that justified a *metric depth* teacher aimed at the *vertical* axis -- does not hold. The
hand reaches the right height and the right lateral position at different moments and never both,
which no depth supervision addresses. W2 (spawn variation) is the lever; the method was not. Supersedes the *method-selection* question in
`geometry_supervision_evidence_repair_plan.md`; that document is retained as the measured
evidence appendix (its §2.5/§2.5b teacher measurements and §2.2 reach tables are still the
only numbers we have).

## 1. Goal

One pipeline, four stages, no branching investigation:

1. Take the recorded G1 apple pick-and-place corpus.
2. Annotate it with depth from `depth-anything/DA3METRIC-LARGE`.
3. Finetune a custom GR00T-N1.7 on it with **Spatial Forcing** (arXiv:2510.12276).
4. Serve it as a self-contained inference pipeline: **RGB in from the robot camera, no depth
   sensor, actions out.**

Everything not on that path is out of scope for this plan.

## 2. The one design decision to state up front

Spatial Forcing is a **training-time** method. It aligns the student's intermediate image tokens
to a frozen geometry teacher's features, and the teacher is then **deleted at deployment** — that
zero-inference-cost property is the paper's headline claim, and our `align` path already
implements it (`Gr00tN1d7.get_action`: *"`align` only shapes the weights and needs nothing at
inference"*).

So "the inference pipeline has DA3METRIC-LARGE as part of it" resolves two ways, and both are
already built as arms:

| | teacher at inference | what it is | cost |
|---|---|---|---|
| **`align`** (default) | **no** — distilled into the weights | true Spatial Forcing | zero |
| `mix` | **yes** — DA3 runs per frame | 3D-Mix gated fusion (arXiv:2603.24393) | one ViT-L forward/frame |

Both satisfy the hard requirement — **RGB only from the robot, no depth sensor** — because DA3 is
monocular either way. `align` is the default because it is the technique named in the goal and it
is free at inference; `mix` stays available as the arm where DA3 is genuinely resident, so the
choice is settled by measurement rather than by argument. If the intent is specifically "DA3 ships
inside the served artifact", that is `--arm mix`, and it is one flag.

## 3. Preconditions — measured 2026-09-06, not assumed

* **The recorded corpus RGB is healthy and usable.** Mean inter-frame |Δ| over the first 60
  frames: **2.7310** (ep 0), **2.5334** (ep 1), **2.6915** (ep 125), **2.9409** (ep 250); max up
  to 22.16; **0/59 bit-identical pairs** in every episode. This matters because it **decouples
  this plan from the frozen-render defect**: the freeze is in the *re-render* path
  (`IsaacRtxRenderer.update_transforms` is a no-op; the re-render moves 0.4238 against the
  recording's 2.722). We annotate the **recording**, so **W1 is not a blocker here.** Re-rendering
  is only needed if we ever want fresh views.
* **The teacher weights are already local:** `~/.cache/huggingface/hub/models--depth-anything--DA3METRIC-LARGE`
  (also `DA3-BASE`, `DA3MONO-LARGE`, `Depth-Anything-V2-Small-hf`).
* **Corpus shape: 208 episodes, not 251.** 35 066 frames, 50 fps, one camera
  `observation.images.ego_view` at 480x640 h264, `robot_type: unitree_g1`. No depth key exists yet.

  **`info.json`'s `total_episodes: 251` is stale.** Only 208 episodes exist — mp4 count, parquet
  count and `episodes.jsonl` all agree on 208 — with 43 gaps in the index range 0..250 (69-71,
  102-107, 134-156 partially, 186-202 partially). `total_frames` is *correct*: the 208 entries in
  `episodes.jsonl` sum to exactly 35 066. So the per-episode list is authoritative and only the
  count is wrong. The annotator reads `episodes.jsonl` and records both numbers in its manifest;
  iterating `range(total_episodes)` would both miss episode 250 and emit 43 spurious warnings.

  This corrects a figure that had propagated through the earlier plans, including the evidence
  appendix's costing of a re-record as "251 episodes". It is 208.
* **GPU:** one RTX PRO 6000 Blackwell, 97.9 GB — the teacher pass and the finetune both fit.

## 4. Known limiter, stated once and not re-argued

`APPLE_SPAWN_XY_RANGE_M = 0.0` (`galileo_g1_static_pick_and_place_environment.py:67`) against a
20x22 cm evaluation placement range. The training corpus has **zero spatial variation**. A
perception-side auxiliary loss has little to bind to when the scene is constant, so **do not expect
Spatial Forcing alone to close the 7 cm gap on this corpus.** This does not block the pipeline —
build it, measure it, and read the result as "what SF buys on a static corpus", which is a real
number we do not have. Adding spawn variation is the separate, cheaper lever and stays tracked in
the evidence-appendix plan as W2.

## 5. What already exists (do not rebuild)

Verified in `submodules/Isaac-GR00T` @ `d78207d` (branch `dev/arena_v0.3.0-compat`):

* `gr00t/model/modules/geometry_conditioning.py` (622 lines) — `FrozenGeometryEncoder` with the
  DA3 loader (strict on the backbone, tolerant of the discarded head), `probe_feature_dim()`,
  Apache-2.0 encoder allowlist, and the masked `1 - cos` alignment loss with a learnable
  **target-side** positional embedding.
* `align` / `mix` modes, alignment-site selection (`post_vl_self_attention`, `backbone_output`,
  `backbone_layer_<k>`), plumbed `FinetuneConfig` -> `launch_finetune` -> model config.
* `isaaclab_arena_gr00t/scripts/finetune_n17_geometry.sh` — 7 arms including `align` with
  `DA3METRIC-LARGE`.
* 23 tests in `tests/gr00t/model/test_geometry_conditioning.py`.
* Serving: `gr00t/eval/run_gr00t_server.py` + `docker/run_gr00t_server.sh`, and Arena's
  `isaaclab_arena_gr00t/policy/gr00t_remote_closedloop_policy.py`.

## 6. Gaps this plan closes

* **G1 — no depth annotation exists.** The teacher runs *online* inside the model. Nothing writes
  DA3 depth into the dataset, so the depth is neither inspectable nor reusable.
* **G2 — `align` loads DA3 at inference and never uses it.** `Gr00tN1d7.__init__` builds
  `FrozenGeometryEncoder` and calls `probe_feature_dim()` whenever `geometry_mode != "off"`, to
  size the projector. At inference in `align` mode that loads a ViT-L for nothing — directly
  against the "zero cost at inference" property that is the whole reason to prefer `align`.
  Fix: persist the probed width in the config and skip the encoder when it will not be used.
  **Done** -- `geometry_feature_dim` on the model config, probed once at training time and written
  back. `FrozenGeometryEncoder` already loads lazily and `get_action` never calls it in `align`
  mode, so the eager probe was the only thing keeping the teacher resident. Pinned by two tests.
* **G3 — `align_loss_coeff`'s docstring is wrong.** It says the value is *"Unknown upstream ...
  a guess kept only so a run starts"*. It is not: `openvla-SF/vla-scripts/finetune_align.py`
  defines `align_loss_coeff: float = 0.5`, which is exactly our default. Correct the provenance so
  it is not needlessly swept as an unknown. **Done** -- corrected in all three places it was
  duplicated (`geometry_conditioning.py`, `finetune_config.py`, `configs/model/gr00t_n1d7.py`),
  with the caveat that upstream tuned 0.5 against OpenVLA's L1 action loss rather than N1.7's
  flow-matching head, so it is still worth sweeping -- just not as an unknown. (`alpha` is the paper's name for it, Table 3 is its
  ablation. Do **not** conflate with VEGA's `lambda = 0.1`, a different paper.)
* **G5 — the `align` arm had never run, and could not have.** Measuring the teacher's width is a
  forward pass, and `AutoModel.from_pretrained` constructs the policy under transformers'
  **meta-device** init, where a forward cannot run. So `probe_feature_dim()` inside
  `Gr00tN1d7.__init__` failed with `NotImplementedError: Cannot copy out of meta tensor` before
  training could start — every time, for both `align` and `mix`. The infrastructure was complete
  and untested end to end. Fix: `Gr00tN1d7FinetunePipeline._resolve_geometry_feature_dim()` probes
  once on a real device *before* construction and passes the width in on the config; the
  `__init__` fallback now raises an instruction instead of a meta-tensor error.

  This is also why G2's fix was worth doing for its own sake rather than only as an optimisation:
  the recorded width is what lets construction avoid the probe at all.

* **G6 — `align_loss` was computed and then made invisible.** The model adds it into the reported
  `loss` and HF's trainer logs only the total, so a Spatial Forcing run contributing nothing looks
  identical to one that works. Given risk 2 — the target positional embedding starts at 2.8% of
  the teacher's feature scale — that is a live failure mode, not a hypothetical. Fixed:
  `Gr00tTrainer.compute_loss` now gathers and logs `align_loss` separately.

* **G7 — every `align` checkpoint carried the frozen teacher as dead payload.** The teacher is a
  registered submodule (for device/dtype handling), so training wrote all ~300 of its tensors into
  the policy checkpoint — 1.3 GB for `DA3METRIC-LARGE` — and loading then discarded them with a
  several-hundred-tensor "weights not used" warning that is indistinguishable at a glance from a
  real architecture mismatch. Fixed: `FrozenGeometryEncoder.state_dict` omits `_model.*`. Nothing
  is lost, because the teacher is frozen and rebuilt from `encoder_id` on first use. **Measured:**
  342 `geometry_encoder.*` tensors -> 0, checkpoint 13.82 GB -> 12.61 GB, with the 7 real
  `geometry_conditioning.*` tensors retained.

* **G4 — a feature cache is not sound under the current recipe, and that must be written down.**
  The processor emits `geometry_images` **post-augmentation**, and the *train* transform includes
  `FractionalRandomCrop` — a stochastic geometric crop per sample. A per-frame teacher cache would
  therefore be misaligned with the crop the student actually sees. So: **online teacher stays the
  default**, and the cache is opt-in behind an assertion that the crop is deterministic.

## 7. Stages

### S1 — Annotate the corpus with DA3METRIC-LARGE  *(closes G1)* — **DONE**

`isaaclab_arena_gr00t/scripts/annotate_dataset_depth.py`.

Reuses `FrozenGeometryEncoder` directly rather than re-deriving the preprocessing, so the
annotation and the online teacher cannot drift apart. Writes, per episode:

* **metric depth in metres** — `metric_depth = focal * net_output / 300.0`, the documented DA3METRIC
  conversion, with `focal` from the camera intrinsics. Stored as uint16 millimetres (lossless under
  PNG/zstd, ~1000x smaller than fp32) plus the scale factor in the manifest.
* **optional SF teacher latents** at the student's token grid, `--emit-latents`.
* a **manifest** recording `encoder_id`, `da3_out_layer`, `encoder_input_size`, the token grid,
  dtype, the focal used, and the `focal/300` factor — so a consumer that disagrees fails loudly.

**Measured on a smoke run (2026-09-06, episodes 0-1, 8 frames each):**

* Corpus 640x480 is fed to DA3 at **686x518**; focal **458.12px native -> 491.05px as fed**;
  `focal/300 = 1.6368`. This **explains** the 1.64x factor §2.5b measured empirically -- the
  formula is right and the focal simply has to be taken at the fed resolution.
* Canonical depth range 0.283-1.550 (mean 0.510); metric conversion 0.463-2.537 m (mean 0.835 m).
* **Geometry is sane:** frame 0 bottom-of-image median **0.565 m** is nearer than top-of-image
  median **0.696 m**, the correct sign for a head camera angled down at a table.
* **Latents are exactly the student grid:** `(8, 88, 1024)` -- 8x11 tokens, 1024-dim for the
  ViT-L teacher -- at per-channel std **0.6495**, consistent with the 0.718 measured previously
  for `DA3METRIC-LARGE` layer-23 patch tokens.
* Cost: ~375 KiB/frame compressed with depth at full resolution *and* latents. Depth alone
  measured at **7.4 GB**; `--depth-downsample 2` cuts it 4x.

**Full corpus annotated (2026-09-06):** 208 episodes, **35 066 frames in 1515 s (23.1 fps)**, 7.4 GB
at `/datasets/isaaclab_arena/static_apple_tutorial/depth_da3/`. Integrity verified per episode
rather than by total: all 208 `.npz` files present, **every** per-episode frame count matches
`episodes.jsonl` exactly, and the sum is 35 066 — i.e. every frame in the corpus is annotated,
none duplicated or dropped. Written without latents, since the online teacher is the default (G4);
`--emit-latents` adds them.

Remaining in S1: fit the single global scale factor (`--fit-scale-to-metres`), which §2.5b puts at
1.027x / 1.64 cm. The annotation is what that fit consumes, so it is unblocked.

**The `focal/300` trap stands:** the raw output is *not* metres, and §2.5b measured it at 1.568x
true on the table region, so applying the conversion makes it *worse* (2.566x / 79.5 cm) while one
fitted global scalar reached 1.027x / 1.64 cm. The annotator therefore writes the canonical output
*and* the converted metres *and* records every factor in `manifest.json`, asserting nothing about
which is metres. Fitting that scalar is the remaining piece of S1.

### S1a — Look at the annotation  *(done)*

`isaaclab_arena_gr00t/scripts/preview_depth_annotation.py` renders recorded RGB beside colourised
DA3 depth, colour scale fixed per episode so motion in the depth panel is real rather than
per-frame renormalisation. Episodes 0/1/125/250 render at 154/168/155/189 frames, matching
`episodes.jsonl`, depth spanning 0.33-1.06 m. Inspected: gripper and held apple nearest, the
plate's relief resolves, table graduates near-to-far, shelf column reads far. DA3 rounds the flat
plate into a dome -- normal monocular behaviour, harmless for alignment.

**Rerun**: `isaaclab_arena_examples/tools/visualize_lerobot_dataset.py` writes a `.rrd`, but
**`rerun` is installed in neither the devcontainer nor the GR00T image**. Generate inside the
container without touching the project environment, then view on the **host**:

```bash
# generate (in the container -- uv --with keeps rerun out of the project env)
docker exec gr00t-annotate bash -lc 'cd /workspace/gr00t && UV_LINK_MODE=copy \
  uv run --with rerun-sdk --with opencv-python-headless \
  python /workspaces/isaaclab_arena/isaaclab_arena_examples/tools/visualize_lerobot_dataset.py \
    --dataset-dir /datasets/isaaclab_arena/static_apple_tutorial/lerobot \
    --episode-index 0 --save-rrd /workspaces/isaaclab_arena/eval_output/viz/episode_000_rgb.rrd'

# view (on the host, where the Rerun viewer runs)
pip install rerun-sdk           # once
rerun eval_output/viz/episode_000_rgb.rrd
```

The container path is for *generating* the recording; the viewer is a host-side GUI. The
side-by-side mp4s from `preview_depth_annotation.py` need no viewer at all and are the faster
check.

### S1b — Fit the one global metric scale  *(the remainder of S1)*

**It does not gate S2.** Spatial Forcing's loss is `1 - cos`, which is scale-invariant, so the
fitted scalar cannot change the `align` run. It matters for two other things: knowing whether the
teacher carries usable *absolute* range, and as the prerequisite for the depth-regression branch
(evidence appendix W6). So S1b and S2 run in parallel.

**Anchor on known scene geometry, not on a render.** §2.5b's 1.64 cm figure was fitted against a
GT depth that came from the simulator render — the path W1 shows is frozen — so reproducing it that
way would inherit the defect this plan exists to avoid. §2.5's method needs **no ground truth**:
fit the table plane in 3D from the annotation, then anchor on the apple's known **3.4 cm relief at
~0.5 m (+6.8% of range)**, which is a ratio and survives the scale error. The apple's diameter is a
second, independent anchor.

Fit `s` in `metric = s * canonical_depth`, per camera pose, by RANSAC on the table region. Expect
`s ~ 0.655`: §2.5b measured raw at **1.568x** true, and 1/1.568 = 0.638. Write `s` and its residual
into `manifest.json` beside the factors already recorded.

**Do not use `metric_depth_mm` as metres.** The annotator writes it for completeness, but §2.5b
measured that exact conversion (`f_proc/300 = 491.03/300`, which matches the annotator's computed
491.05) as the **worst** of the four options at 2.566x / 79.5 cm. The raw canonical output is the
better starting point, and `s` multiplies *it*.

Acceptance: table-plane residual under ~2 cm at 0.5 m, and the fitted `s` within ~10% of 0.655
independently on at least three episodes at differing pose. A wildly pose-dependent `s` means one
global scalar is the wrong model and the fit should be per-pose.

#### Outcome (2026-09-06): **does not converge. The scale is not established.**

`isaaclab_arena_gr00t/scripts/fit_depth_metric_scale.py`. The scale-free check earned its place by
failing twice before any number was believed.

1. **The relief anchor is unusable.** With an apple-only window, relief measures **2.35% of range**
   where the apple's 0.068 m height at ~0.40 m demands **17%**. DA3 smooths the apple into the
   table: a relief anchor asks for a few-centimetre *depth difference* across ~70 px, which is
   exactly what monocular depth blurs. This is a firm finding and it **partly contradicts §2.5 of
   the evidence appendix**, which reports the ratio reproduced "to within 1.3x" -- not reproducible
   here on frame 0. Kept as a diagnostic only.
   *(A first attempt measured 7435 above-plane pixels: the window had been placed without looking
   and was on the destination plate, which is far larger in pixels than the apple and sits
   mid-table. Fixed by rendering frame 0 with a pixel grid and reading the apple's box off it --
   x 55-150, y 300-385.)*
2. **The apparent-size anchor is sound in principle and too noisy in practice.** Under a pinhole
   camera a known width `W` spanning `p` px sits at `Z = focal * W / p`, which needs no depth
   gradient. Measured across six episodes (0, 1, 40, 125, 180, 250): **s = 1.11, 1.23, 1.66,
   1.33, 1.23, 1.34 -> mean 1.314 +/- 0.170, a 41.5% spread**, and ~2x the appendix's 0.655.
   Three bias sources, none yet bounded: the colour segmentation
   drops the apple's unlit side, so the silhouette underestimates and `s` overestimates; the median
   depth over the mask includes edge pixels blurred onto the background, biasing the other way; and
   **the apple's lateral dimensions were never recorded** -- `_USD_ORIGIN_ABOVE_BOTTOM_M` gives only
   `min_z`/`max_z`, so its 0.068 m *height* stands in for its diameter.

**Correction to this plan's own §S1b claim.** It said the fit "needs no ground truth" and so avoids
W1. The *validation* does avoid the render, and that part holds. But a **trustworthy absolute
scale does not**: three anchors now disagree by factors of 1.7-7 and nothing available adjudicates
them. Settling the scale needs real GT depth, which needs the frozen render fixed. **S1b is
blocked on W1** after all -- for a definitive number, though not for the diagnostics above.

**Still does not block S2-S4**, for the reason already given: the alignment loss is scale-invariant,
so `align` is unaffected either way. What is blocked is any claim that this pipeline reports metres,
and the depth-regression branch that would consume them.

**Incidental finding, which refines §4.** Across episodes at frame 0 the apple's apparent diameter
spans 57.9-72.8 px and its canonical depth 0.325-0.399, even though `APPLE_SPAWN_XY_RANGE_M = 0.0`
fixes its world position. So the corpus has **no object variation but real viewpoint variation** --
the head pose differs per demo. §4's "constant scene" is therefore too strong: a spatial objective
has *something* to bind to, just not object placement. It also means a fixed pixel window does not
transfer across episodes, which is why episodes 1/40/125 yield zero above-plane pixels in episode
0's window.

### S2 — Finetune with Spatial Forcing

```bash
isaaclab_arena_gr00t/scripts/finetune_n17_geometry.sh --arm align    --nproc-per-node 1
isaaclab_arena_gr00t/scripts/finetune_n17_geometry.sh --arm baseline --nproc-per-node 1
```

Run **in sequence on one GPU**, never concurrently: measured 82 GB of 97 GB at batch 64, so two
would not fit, and the timings would not be comparable anyway.

**Two confounds in the arm definitions, found when launching and now fixable.** The claim that the
arms "differ only in the geometry flags" was wrong — `baseline` vs `align` differed in **three**
things:

| | `baseline` (as defined) | `align` |
|---|---|---|
| geometry loss | off | on |
| `--tune-visual` | **false** | **true** |
| colour jitter | **full** (+saturation, hue) | **reduced** |

Visual tuning and augmentation strength each move success rate on their own, so that comparison
cannot attribute a difference to Spatial Forcing. Both are now overridable, and the isolating
control is:

```bash
finetune_n17_geometry.sh --arm baseline --tune-visual --reduced-color-jitter   # control
finetune_n17_geometry.sh --arm align                                          # treatment
```

which differ in the geometry loss and nothing else. The arm defaults are unchanged, so `--arm
baseline` alone still reproduces the original definition; the run line now prints
`tune_visual=` and `reduced_color_jitter=` so a log records which was used.

**Budget: 5000 steps at batch 64, measured 1.40 s/it → ~1.9 h/arm, ~3.9 h for the pair.** Chosen
over the launcher's 20000 default for three reasons: 20000 is **36.5 epochs** over 35 066 frames
from a base already tuned on this task, which mostly memorises a corpus with zero spatial
variation (§4); `save_steps=1000` with `save_total_limit=5` means a 20000-step run **deletes every
checkpoint before step 16000**, while 5000 retains all five, so the best can be chosen; and SF's
own published curve (2K→72.7, 5K→87.5, 20K→93.7 on LIBERO) makes *faster convergence* the claim,
which is measured early. Override with `--max-steps 20000` for the full protocol. Both arms get the
same budget either way, which is what the comparison needs.

Both land in `geometry_arms/{baseline,align}`; within that root, `baseline` **is** the isolating
control, not the original arm definition.

Teacher `DA3METRIC-LARGE`, site `post_vl_self_attention`, `align_loss_coeff` 0.5 (now sourced),
`--tune-visual` on. Run `--arm baseline` as the control; they differ only in the geometry flags.

Acceptance: `align_loss` is logged, starts near 1.0 and **decreases**; the action loss does not
diverge relative to baseline. A flat `align_loss` means the target positional embedding is a no-op
at `pe_std = 0.02` — sweep it before concluding anything about the method.

**Met on a 30-step smoke (2026-09-06):** teacher width measured as 1024 before construction;
the 7 `geometry_conditioning.*` tensors initialise fresh as expected; and both losses fall
together —

| step | `align_loss` | action `loss` |
|---|---|---|
| 0  | 0.9916 | 0.3901 |
| 10 | 0.3969 | 0.1951 |
| 20 | 0.2564 | 0.1562 |

`align_loss` starting at 0.9916 is right for a `1 - cos` objective on a fresh random projector.
This is the **first** end-to-end `align` run: see G5 for why it could not have worked before.

#### The acceptance criterion above is wrong, and is corrected here

"Starts near 1.0 and decreases" is satisfied by a model that learned **nothing but the teacher's
mean direction**. `align_loss` is `1 - cos`, and cosine compares only directions, so if the
teacher's per-token features all point much the same way then a projector that ignores its input
and emits the mean already scores well.

Measured with `isaaclab_arena_gr00t/scripts/measure_align_target_floor.py` on
`DA3METRIC-LARGE` layer 23:

| grid | tokens | cos(token, mean) | **constant-predictor floor** | eff. rank | dims @ 90% var |
| :--- | ---: | ---: | ---: | ---: | ---: |
| student 8x11 | 264 | 0.8731 | **0.1269** | 8.6 | 21 |
| DA3 native 37x49 | 5439 | 0.8554 | **0.1446** | 11.3 | 37 |

So the teacher's features occupy roughly **9 effective dimensions out of 1024** and sit 0.87
aligned to their own mean. **Most of `align_loss`'s dynamic range — 0.99 down to ~0.13 — measures
nothing about geometry.** The informative range is the remaining ~0.13.

*A hypothesis of mine that the measurement killed:* the collapse looked like it must be the
resampling, since 37x49 DA3 patches averaged onto an 8x11 grid is ~28 patches per token. It is not
— native-grid features are barely higher rank (11.3 vs 8.6) and their floor is only 0.018 worse.
The low-rank structure is **intrinsic to the teacher at this layer**, not an artefact of how we
sample it.

**Corrected criterion: `align_loss` must fall clearly below the floor for the student's grid
(0.1269), not merely below 1.0.** Observed on the live run: 0.8797 (step 29) -> 0.7326 (40) ->
0.1009 (121) -> **0.0795 (212)**, i.e. 0.047 below the floor. So the alignment is learning
per-token structure and not only the mean — but the margin, not the headline drop, is the evidence.

This also reframes SF's own encoder ablation (base 92.7, SigLIP 94.0, DINOv2 94.1, VGGT 96.9): if
targets of this kind are largely low-rank, "every target beats base" is consistent with the
alignment acting mostly as a weak regulariser, with the teacher's identity worth comparatively
little. Not a refutation of the paper — a caution about reading its margins as geometry transfer.

### S3 — Serve RGB-only  *(closes G2)*

```bash
./docker/run_gr00t_server.sh -m <align-checkpoint> -e NEW_EMBODIMENT \
  -c isaaclab_arena_gr00t/embodiments/g1/g1_sim_wbc_data_gr00t_n_1_7_config.py
```

Acceptance: the server loads the checkpoint and returns actions from RGB alone; in `align` mode
**no DA3 resident** and startup carries no DA3 load. For `--arm mix`, DA3 *is* resident and that is
correct.

**Met (2026-09-06)**, loading the smoke checkpoint through `Gr00tPolicy`:

```
geometry_mode            = align
geometry_feature_dim     = 1024      <- read from the checkpoint, so no probe
geometry_encoder built   = True      <- constructed, for strict weight loading
DA3 weights materialised = False     <- never loaded
projector params         = 7,346,176
cuda allocated           = 6.32 GB
```

The teacher is genuinely absent from the served policy, which is the property that makes `align`
the right default for "RGB in, no depth sensor".

### S4 — Evaluate against the control

Closed-loop through `gr00t_remote_closedloop_policy.py` on
`galileo_g1_static_pick_and_place`, align vs baseline, same seeds. Report success rate **and**
`hand_z_minus_obj` at closest horizontal approach — the 7 cm gap is the quantity of interest, and
success rate alone hides it.

**Instrument repaired first (2026-09-06).** `ReachTracer` could not support this comparison, as the
evidence appendix noted: it never reset and wrote no episode index, so a multi-episode trace was one
undifferentiated stream. A second bug was found alongside it — the resting reference required
**every** environment to be still (`(speed < 1e-2).all()`), so one still-settling environment
withheld `lift` from all of them, and with a single environment a slow settle suppressed the column
entirely.

Both fixed in `isaaclab_arena/evaluation/policy_runner.py`: `begin_episode(env_ids)` is called at
each reset from `rollout_policy`, the resting reference is captured and re-captured **per
environment**, and every row now carries `episode` and `step_in_episode`. `lift` is `None` rather
than absent before the reference exists, since a missing key and a not-yet-known value are
different facts.

`isaaclab_arena/tests/test_reach_tracer.py`: **5 passed** in the Arena container once the GPU
freed after training (`/isaac-sim/python.sh -m pytest`). Covers the episode boundary, partial
resets, whole-scene resets, the pre-record no-op, and that written rows carry the index.

**Eval launcher:** `isaaclab_arena_gr00t/scripts/eval_s4_arm.sh --arm <arm> --episodes N`, which
encodes the invocation once so it stops being retyped. Three things verified against
`test_gr00t_remote_closedloop_policy_runner.py` — the only written-down working invocation — rather
than assumed:

* the flag is **`--policy_type`**, not `--policy`;
* **`--policy_config_yaml_path`** is required, and `g1_static_apple_gr00t_closedloop_config.yaml`
  already exists for this task;
* **`--headless --enable_cameras`** are needed — a vision policy with no cameras produces nothing,
  and the run must not try to open a GUI.

`--remote_host`/`--remote_port` are contributed by the policy rather than by `policy_runner_cli`,
which is why grepping the CLI for them finds nothing while the invocation still needs them. Two
recorded gotchas are baked in: every main-parser flag must precede the environment subcommand
(putting `--output_base_dir` after it exits 2 with no message), and omitting the remote flags
silently defaults to `localhost:5555`.

**The launcher checks its own output.** After the rollout it asserts the trace is non-empty, carries
the `hand_*` columns, and carries an `episode` index — the three ways the historical traces are
unusable, each of which looked like a successful run at the time. `ReachTracer` resolves hand bodies
by substring against the robot's body names and returns an empty mapping when none match, which
omits the columns with no error at all.

**Comparison script:** `isaaclab_arena_gr00t/scripts/compare_reach_traces.py` takes two or more
traces and reports `hand_z_minus_obj` at closest horizontal approach per arm. It refuses to present
a per-episode mean from a trace with no episode index, reporting a single global sample and saying
so instead.

#### The "baseline to beat" does not survive contact with the surviving traces

Run against the three historical traces that carry hand columns — the only ones that do, out of
thirteen, and **none of the thirteen has an episode index**:

| trace | `hand_z_minus_obj` at closest approach | horizontal distance there | max lift |
| :--- | ---: | ---: | ---: |
| `v28_handtrace` | **+0.0692 m** | 0.0072 m | +0.0141 m |
| `v29_chunk8` | **+0.0877 m** | 0.0016 m | +0.0077 m |
| `v30_chunk4` | **+0.0721 m** | 0.0092 m | +0.0170 m |

This plan and the evidence appendix both quote "**+0.1286 m at chunk 16, ~0.0795 m at chunk 8**" and
a "16 → 8 → 4 plateau (4.9 cm then 0.7 cm)". Neither reproduces:

* Chunk 8 measures **+0.0877 m**, not 0.0795.
* If `v28` is the chunk-16 run, it measures **+0.0692 m**, not 0.1286 — and is then the *best* of
  the three, which inverts the claimed monotone improvement.
* Chunk 4 (+0.0721) sits **above** chunk 8's 0.0877 only by going down, and the ordering across all
  three shows no monotone trend at all.

Most likely the historical figures used a different statistic (at grasp, or averaged over a
window) rather than the closest-approach minimum. But the statistic was never recorded, and the
appendix already states these tables "cannot be re-derived" — this confirms it with numbers.

**Consequence: there is no trustworthy prior for the vertical error.** Every one of these is a
single global minimum over a multi-episode stream with no spread, so none of them supports a
comparison. The S4 baseline must be measured fresh with the repaired tracer, from the
`baseline` arm now training, and no target from the older plans should be quoted as the number to
beat.

Max lift of 0.008–0.017 m across all three is consistent with the "closes on air" diagnosis: the
apple barely leaves the surface.

Read the result against §4: on a zero-variation corpus a null result is informative, not a
refutation of the method.

#### Result (2026-09-06): **null. Spatial Forcing did not help on this corpus.**

20 episodes per arm, same environment, same seeds, servers on port 5561.

| | baseline (control) | align (SF) |
| :--- | ---: | ---: |
| success rate | 0.05 (1/20) | **0.05 (1/20)** |
| object-moved rate | 0.95 | 0.90 |
| `hand_z_minus_obj` median | **+0.0879 m** | **+0.0904 m** |
| mean +/- sd | +0.0872 +/- 0.0204 | +0.0958 +/- 0.0234 |
| range across episodes | +0.028 to +0.121 | +0.066 to +0.153 |

align is **0.86 cm worse on the mean**, and the difference is **not significant**: Welch
*t* = 1.24 (df ~ 37), Cohen's *d* = 0.39, distributions overlapping. Success rates identical.

**This is not an underpowered null.** Minimum detectable difference at n=20 is ~1.94 cm, and the
7 cm gap this work set out to close is **3.6x** that. Had SF closed the gap, or a third of it, this
design would have seen it. What n=20 cannot resolve is a sub-2 cm effect.

**Three measurements taken earlier predicted this**, which is why it is informative rather than
disappointing:

1. **§4** -- the corpus has no object spatial variation, so a perception-side auxiliary loss has
   almost nothing to bind to.
2. **S2's floor measurement** -- the alignment target is intrinsically low-rank (~9 of 1024
   effective dimensions, constant-predictor floor 0.127), so most of the loss carries no geometry.
3. **S2's cost** -- align settled at 1.62x baseline's action loss to buy that weak signal.

A near-trivial target, on a corpus with nothing to generalise over, charged against action-loss
capacity. A null is what that predicts.

**What this does and does not establish.** It tests SF *on this corpus*, not SF in general. The
confounds dominate, so **fix the corpus before re-testing the method** -- which is the evidence
appendix's W2, and this is the strongest argument yet for doing it first: it is cheaper than any
method change and is a precondition for measuring one. Secondary levers, in expected-value order:
`--align-loss-coeff` below 0.5 (the 1.62x cost suggests it is too high), `--pe-std` above 0.02,
then `--arm mix`, which keeps DA3 live at inference and so does not depend on a scale-invariant
loss carrying scale.

**Both traces are episode-indexed and verified** (`trace OK: 20 episodes, hand columns present`) --
the first reach measurements here that are reproducible distributions rather than single global
minima. Per-episode values in `eval_output/s4_comparison.json`.

#### The base-model control (2026-09-07): the premise of this whole programme is wrong

`gn1x_tuned_static_apple` -- the checkpoint both arms were finetuned *from* -- run through the
identical 20-episode protocol.

| arm | n | lateral | vert @ closest | min abs(vert) | over apple (3.4 cm) | success | moved |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **base** (control) | 20 | **0.0506** | **+0.0862** | 0.0080 | **4/20** | 0.05 | 0.75 |
| baseline | 20 | 0.0508 | +0.0879 | 0.0041 | 6/20 | 0.05 | 0.95 |
| align | 20 | 0.0478 | +0.0904 | 0.0099 | 5/20 | 0.05 | 0.90 |

**1. The finetunes changed nothing.** baseline - base is **+0.2 mm lateral, +1.7 mm vertical**, far
inside noise. So the S4 null is a *valid* comparison, not a comparison of two degraded models, and
the earlier worry that 5000 steps damaged the policy is **refuted**. No shorter retrain is needed.

**2. The record's reach figures do not reproduce for the base model either.** The debug plan gives
1.6 cm lateral / 4.95 cm vertical at home; the base checkpoint measures **5.06 cm / 8.62 cm**. This
is the **third** set of reach numbers from the prior plans that fails to reproduce, alongside
"+0.1286 m at chunk 16" and "~0.0795 m at chunk 8".

**3. "Accurate bearing, wrong range" is false, and it was the premise for this entire programme.**
That diagnosis is what justified attacking the *vertical* axis with a *metric* depth teacher. But
the base policy is over the apple in only **4 of 20** episodes -- bearing was never accurate.

Note `min abs(vert)` of 0.4-1.0 cm across all three arms: the hand *does* reach the right height at
some moment, and the right lateral position at some *other* moment, but **never both at once**. It
sweeps past the apple. That is a trajectory/coordination failure. Neither a depth input nor a
geometry-aligned representation addresses it, which is why the S4 null was overdetermined --
Spatial Forcing was aimed at an axis that is not the binding constraint.

**Consequence for the transfer goal.** The stated aim is to transfer this policy from
`galileo_g1_static_pick_and_place` to a generated environment. Measured across 60 episodes and
three checkpoints, the policy does not perform the task at home (1/20, and that single success is
suspect given the record's history of false-positive place gates -- see `6433fc6a1`). On the
generated env v25 it never contacts the apple at all (object-moved 0.0 over 2 episodes, against
0.75-0.95 at home). The debug plan already said it: *"if the policy cannot place at home, no amount
of target-scene work can produce a placement."* That is now measured, not inferred.

**The lever is the corpus, not the method.** One apple position, one scene, 208 episodes: a policy
trained that way memorises a sweep. Spawn variation (W2) is the precondition for home performance
*and* for transfer, and no auxiliary loss substitutes for it.

**Two setup defects found while running it**, both now encoded in `eval_s4_arm.sh`:

* Ports **5555-5558 are all held** by host processes invisible from any container namespace
  (found by parsing `/proc/net/tcp` and mapping socket inodes; `ss`/`netstat` are unavailable).
  Use 5561 or above. This makes the debug plan's note that "the server in this setup is on 5557"
  stale.
* **`--policy_type` rejects the registered short name.** Its help says "either a registered policy
  name or a path to a policy class", but `get_policy_cls` asserts `"." in policy_type`. The dotted
  path is required. The help is wrong.

## 8. Risks

1. **Zero spatial variation (§4)** caps what SF can demonstrate here. Mitigation: report the
   reach metric, not just success; keep W2 (spawn variation) as the next lever.
2. **`pe_std = 0.02` may make the positional embedding a no-op.** Against unit-variance features
   it shifts the cosine by ~2e-5. SF credits this embedding with ten points on LIBERO-Long, so a
   near-zero init could silently discard the method's second-largest ingredient. Sweep it.
3. **Colour jitter perturbs the teacher's own input.** Already partly mitigated (saturation/hue
   dropped for geometry arms); brightness/contrast still reach DA3.
4. **`focal/300` mis-pairing** — see S1.
5. **The GR00T container does not mount `/datasets`.** `docker/run_gr00t_server.sh` mounts the
   workspace, `/models` and the HF cache only. S1 needs the corpus, so either a datasets mount is
   added there (a change under `docker/`, which AGENTS.md says to ask about first) or the
   annotation runs via its own launcher. Taking the second route for now.

---

## 9. Re-evaluation against the literature (2026-09-07)

Written after the three-arm measurement, with a web survey of how the field handles each of the
three problems the measurement exposed. **Two of my own earlier conclusions are retracted here.**

### 9.1 The metric scale is NOT blocked on W1 — the robot is the calibration target

**Retraction.** §S1b concluded "a definitive scale needs GT depth and therefore the frozen render
fixed, so S1b is blocked on W1". That is wrong, and the fix is a standard technique I did not
consider: **visual-kinematic scale recovery**. The survey's phrasing is exact — *"the robot arm
itself is a metrically known object already in the scene"* (KineDepth and the visual-kinematic
line).

We have everything needed and never used it:

* `observation.state` is 43-dim joint state on all **35 066** frames.
* Forward kinematics gives the gripper's **exact** 3D position in camera frame, per frame.
* The gripper is prominently visible in the ego view -- confirmed by eye in the frame-0 render
  (`eval_output/viz/frame0_grid.png`), where the hand occupies a large, well-lit region.

So: project the FK gripper position into the image, read `canonical_depth` at those pixels, and fit
`s`. That yields **exact per-frame anchors, 35 066 of them, with no renderer, no depth sensor, and
no dependency on W1.** It also fixes the two weaknesses that made the apparent-size anchor noisy
(§S1b): no reliance on colour segmentation, and no dependence on the apple's unrecorded lateral
dimensions.

[MOMA](https://arxiv.org/abs/2506.17110) -- already cited in the evidence appendix §20 -- is the
one-shot version of this, doing scale-shift-**rotation** alignment from sparse GT depth points at
calibration time. FK supplies those points for free, and its reported numbers are the target:
DAM RMSE 12.3 -> 1.6 cm.

**One caution the survey is explicit about:** a single global scale-shift *"assumes uniform scale
and shift biases, an assumption often violated in real scenes with diverse objects and depth
ranges"*, and *"metric recovery ultimately depends on anchor informativeness, degrading when
anchors lack spatial coverage or diversity."* The gripper sweeps the workspace over an episode, so
coverage is reasonable -- but if a single `s` still fails to fit, the 2026 refinements are
[image-adaptive scale fields](https://arxiv.org/html/2605.07418) (basis maps + least squares under
sparse anchors) and [factor-graph depth grounding](https://arxiv.org/pdf/2605.02667) (explicitly
avoiding GT-depth supervision).

### 9.2 Our success gate is the textbook false-positive class

The literature converges on a four-part gate, precisely to stop what bit us:

1. displacement threshold -- **lift >= 5 cm**;
2. a **dwell/hold of 3-5 s**, not a single timestep;
3. a **no-slip / pose-drift** check;
4. for placement, a **final-pose tolerance verified after release**;

plus **staged key-node checks so contact alone can never register as success**.

Ours is the failure mode they name: `object_on_destination` fires on a **0.1 N force threshold** --
a *"pure contact predicate that can fire without a force-closure grasp"*. That is exactly the
`6433fc6a1` false positive (plate rim grazing the apple, 0.28 s / 14-frame episode). The remedy in
[RoboWM-Bench](https://arxiv.org/html/2604.19092v1) is the staged gating above; *"momentary
success"* at a single timestep is called out as a weak notion because a trajectory is more likely
to pass through the goal by accident than to stabilise there.

**Also: report Wilson score intervals, not bare proportions.** At n=20 with 1 success, the point
estimate 0.05 carries an interval wide enough to be consistent with 0. Every success rate in this
plan should be re-reported that way, and `0.05` should not be spoken of as different from `0.0`.

**Action, no GPU needed:** re-score the three existing traces under a lift+dwell+pose gate. All
three carry `obj_z`, `lift`, `speed`, `dist_to_dest` and `contact_force` per step, so this is a
pure re-analysis. Expect 1/20 to become 0/20.

### 9.3 The corpus is the lever — and it does NOT require a re-record

The diagnosis is textbook. With one demonstrated pose *"a policy succeeds merely at the
demonstrated pose but fails to generalize"*, because *"the robot may learn to focus on spurious
correlations between the pixels and the demonstrated actions"*. More precisely for us: models
*"overfit to absolute information (e.g., coordinates) rather than the relational information
between objects ... as a result, the models perform poorly in novel object location setups"*
([Position-Invariant Regularization](https://openreview.net/forum?id=N00uQFLlvHC)).

On how much variation: no published constant, but the working rule is that **training positions
must span at least the deployment range**, with tabletop evaluations typically varying initial
object position by **+/- 20 cm in x and y**. IL interpolates far better than it extrapolates.

**The cost objection that deferred W2 is void.** The evidence appendix costed spatial variation as
a 208-episode re-record. The literature's answer is synthetic spatial data generation from an
*existing* demo set -- MimicGen, DemoGen, and
[R2RGen](https://arxiv.org/pdf/2510.08547), whose stated goal is *"to train a spatially generalized
visuomotor policy purely from a single collected demonstration set"*. **And `isaaclab_mimic` is
already vendored in `submodules/IsaacLab/source/`, with Arena-side coverage in
`isaaclab_arena/tests/test_sequential_task_mimic_data_generation.py`.** So spatial variation is a
data-generation run over the demos we have, not a re-record.

Two cheap complements from the same survey:

* **Random-crop augmentation** improves generalisation to spatial factors *and* to distractors and
  textures. We already apply `FractionalRandomCrop` -- worth checking whether `crop_fraction` is
  aggressive enough to be doing anything.
* [Decomposing the Generalization Gap](https://arxiv.org/html/2307.03659) ranks 11 factors by
  difficulty, consistently across sim and real: **new camera positions are the hardest**, new
  backgrounds the easiest. Relevant because our corpus already has viewpoint variation (§S1b's
  incidental finding: apparent apple diameter spans 57.9-72.8 px) but zero object variation -- i.e.
  it varies the hard factor and fixes the easy one, which is backwards.

### 9.4 The failure we measured is a named mode with known fixes

The field's decomposition matches ours exactly. [RoboFAC](https://arxiv.org/pdf/2505.12224)
formalises motion-planning failure as **"Position Deviation": a 3D offset `dp` in R^3** on the
end-effector, which *"is what lets you decompose the failure into lateral (XY) versus vertical (Z)
components"* -- the decomposition this session performed.

Our specific signature is documented in strong baselines:

* [Any3D-VLA](https://arxiv.org/pdf/2602.00807): pi-0.5, GraspVLA and SpatialVLA *"often exhibit
  horizontal grasp-position drift ... indicating spatial localization errors"* and *"reliance on
  non-robust spatial shortcut cues"*.
* [AnoleVLA](https://arxiv.org/pdf/2603.15046) separates *"position recognition error"* (arm moves
  to a location not corresponding to the object) from *"grasping point prediction error"*, and finds
  **position recognition error most frequent, with motions toward incorrect regions or empty
  space** -- our 4/20-over-the-apple result.
* [Benchmarking VLAs](https://arxiv.org/pdf/2511.11298) treats *"trajectory/state drift ...
  accumulated deviation over long horizons"* as its own category -- the closest analogue to
  "sweeps past", and consistent with our `min|vert|` of 0.4-1.0 cm coinciding with ~8.6 cm vertical
  error at closest lateral approach.

The fixes, in the order the survey ranks them: **dimension-specific additive bias correction**,
**re-staging/retry at the subtask level**, and **3D or multi-view geometric grounding**.

Note the first is already half-built here: `cartesian_vertical_offset_adapter` is the zeroth-order
version of dimension-specific bias correction -- **for the vertical axis only**. The measurement
says the lateral axis needs one at least as much.

### 9.5 Revised plan of record

Ordered by evidence-per-hour, not by novelty. Items 1-2 need no GPU.

| # | Item | Cost | Why first |
| :-- | :--- | :--- | :--- |
| **1** | **Re-score the three traces** under a lift+dwell+pose gate; report Wilson intervals | hours, CPU | The current 1/20 is probably 0/20. Every downstream comparison rests on the gate. |
| **2** | **Fit `s` from FK gripper anchors** (§9.1) | hours, CPU | Unblocks the metric scale without W1; retires an open question. |
| **3** | **Spatial variation via `isaaclab_mimic`** over the existing 208 demos | days, GPU | The lever. Precondition for home performance *and* transfer. No re-record. |
| **4** | **Retrain and re-measure base / baseline / align** on the varied corpus | ~5 h GPU | The only condition under which the S4 comparison means anything. |
| **5** | Lateral **and** vertical bias adapters, measured separately | days | Named fix for the measured mode; half already exists. |
| **6** | Revisit geometry supervision *only after 3-4* -- and prefer `mix` over `align` | days | `align`'s loss is scale-invariant, so it cannot carry metric scale by construction. |

**What is now closed:** the S4 comparison ran and is valid; the arms are not degraded; the vertical
axis is not the binding constraint; the "accurate bearing / wrong range" premise is refuted; and
Spatial Forcing on this corpus is measured, null, and explained.

**What W1 still blocks:** fresh rendered views, and any depth-regression target that needs GT depth
maps rather than sparse anchors. It no longer blocks the metric scale.
