# DA3 + Spatial Forcing pipeline for the G1 apple pick-and-place

**Status:** active, v1.0 (2026-09-06). Supersedes the *method-selection* question in
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
A full-length run is the remaining compute decision, not an open question.

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

Read the result against §4: on a zero-variation corpus a null result is informative, not a
refutation of the method.

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
