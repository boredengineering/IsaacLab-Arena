# Metric Range for the G1 Policy: Fix the Confounds, Then the Method

> [!IMPORTANT]
> **Status**: PLAN v2.1, 2026-09-06. v2.1 adds §2.4's third removal, §2.8 (external corroboration
> of the range/bearing asymmetry, and the cheapest perception remedy nobody costed), §2.9 (verified
> absences), and a fifth branch to the decision tree; §2.6 gains the two published loss recipes. No
> v2 finding is retracted. Originally: PLAN v2, 2026-09-05, replacing v1 of the same day. Supersedes §W5, §W7
> (gates G1/G2) and §2's teacher argument in
> [`spatial_forcing_da3_metric_alignment_plan.md`](spatial_forcing_da3_metric_alignment_plan.md);
> that plan's §3, §4 and §8 stand. Written after four investigations on 2026-09-05 -- a source-level
> diagnosis of the rerender, an audit of the 7 cm figure's provenance, a literature survey of
> geometry supervision for VLAs, and direct measurement of four candidate teachers. **v1 got two
> things wrong and they are corrected in place** (§2.1, §2.4). The headline change: the perception
> hypothesis is no longer the leading diagnosis, and two confounds outrank the method question.

## 1. The short version

v1 said: repair the ground truth, then train arms. That is still necessary and not sufficient. Four
findings reorder the work:

1. **The rerender's physics was always correct.** The state write reaches PhysX exactly; the *render*
   is frozen. v1's claim that `reset_to` "never applied" was wrong, and so was its proposed remedy.
2. **The 7 cm is the measured quantity and the 5 cm is the subtraction** -- the reverse of how both
   plans told it. What is unmeasured is the *attribution* of the 7 cm to monocular range.
3. **A competing diagnosis has more evidence behind it than the perception one**, and it would not be
   fixed by any depth teacher.
4. **The teacher has no metres to give**, for a stronger reason than v1's: two independent removals,
   not one. And the literature's only structural twin of our approach scores *below* baseline.

So the plan is: unfreeze the render, fix the corpus, *discriminate the diagnosis*, and only then pick
a method -- which, if perception is implicated, is probably not the one we built.

## 2. Verified findings

### 2.1 The rerender: physics is correct, the render is frozen

`sim.forward()` updates kinematics without stepping physics, and **every** path that pushes body
transforms to RTX is keyed on the physics step counter that only `step()` increments:

- `RenderContext.update_transforms` returns early when `_last_transforms_step == physics_step_count`
  (`renderers/render_context.py:112-120`) -- with a frozen counter, a permanent no-op.
- Its one scene-level call site is guarded by `if not self.cfg.lazy_sensor_update`
  (`scene/interactive_scene.py:634-635`), and `lazy_sensor_update` defaults to `True`
  (`scene/interactive_scene_cfg.py:80`) and is **never overridden anywhere in Arena**. The transform
  push that `render_frame`'s comment says it relies on is dead code.
- Under Newton, `sync_transforms_to_usd` early-returns on `_transforms_dirty`, which only stepping
  sets. Under PhysX, Isaac Lab's own comment describes the FabricManager "causing articulation meshes
  to freeze visually while physics continues to run", with a `_re_sync_fabric()` workaround wired
  only into the pause/resume path.

RTX therefore keeps drawing the transforms from the last real physics step -- `env.reset()` -- which
is the default pose with arms raised and the apple at its authored spawn rather than its resolved
placement. One mechanism, all four symptoms, and it explains why the image is crisply frozen rather
than noisy: the annotator gate keys on `render_generation`, which `sim.render()` *does* bump.

> [!CAUTION]
> **v1's correction.** A `--validate_states` run already exists --
> `eval_output/rerender/smoke/smoke_validated/rerender_summary.json` reports
> `state_playback_max_abs_error` of **exactly 0.0** for every entity including the apple, at
> 10.26 dB PSNR. The write round-trips through PhysX and re-fetches identically. So v1's remedy
> ("make `--validate_states` default-on") was aimed at the wrong layer: that hook validates physics,
> not rendering, and reporting 0.0 is what made this bug look like it lived somewhere else. The
> guard that would have caught it is the *other* one v1 proposed: **fail the run when consecutive
> depth frames are bit-identical while the recorded state is not.**

**This contaminates downstream work.** `calibrate_corpus_camera.py:198-216` uses the identical
protocol, and its docstring reasons from the misattribution -- "the disagreement has the near/far
parallax signature of a camera-mount difference rather than a scene-layout one." Camera pose reaches
RTX through direct USD prim writes (`IsaacRtxRenderer.update_camera` is a documented no-op) while
body transforms go through the frozen Fabric path, so that search would appear responsive to camera
offset and blind to scene state *whatever the true mount was*. Its fitted offset is likely an
artifact, and the camera-pitch investigation is downstream of the same bug.

### 2.2 The 7 cm is measured; its attribution is not

`g1_monocular_depth_and_camera_pitch_debug.md:459-465`: the vertical error **plateaus** at 7 cm
(chunk 8 → 7.95 cm, chunk 4 → 7.21 cm), and staleness is the residual `12.86 − 7.95 = 4.91`. Both
plans presented this backwards. The "Cause" column attributing the 7 cm to monocular range cites an
argument about the modality config, not an experiment.

Two further defects in that evidence base:

- **The 4.48 cm "closest approach" is home posture.** In `v29` the five smallest gaps are identical
  to five decimals -- `+0.04482` at global steps 980, 1960, 2940, 3920, 4900, exactly the episode
  boundaries, with `obj_z` pinned at spawn. It was used as one side of a "transfer degrades range
  2.6x" comparison whose other side is a mid-episode value. Real mid-episode approaches do better:
  `v28` reaches 4.34 cm, and `v30` reaches **3.37 cm** -- at the apple's 3.40 cm radius.
- **The per-episode tables cannot be re-derived.** `ReachTracer` never resets and writes no episode
  index, so the JSONL carries no episode boundary; chunk-16 reproduces (+0.1276 vs +0.1286) but
  chunk-8 and chunk-4 do not.
- The staleness experiment is **retracted at the task level** in its own record: 0 successes at every
  horizon, `P(0 lifts) = 0.9^6 ≈ 0.53`.

### 2.3 Scale vs offset is untested, and a competing diagnosis has more evidence

Every reach measurement was taken at one scene, one seed, one table height, one camera pitch, so the
error's functional form is **unidentifiable by construction**. The height sweep that would settle it
was designed in full, demoted off the critical path, and never run; its tooling
(`support_relation_sweep.py`, `summarize_support_sweep.py`) exists and has produced no output. The
one run at a different surface height predates hand tracing and was invalidated by an
object-ejection defect. The deck-height axis is additionally blocked by a hardcoded `Z_deck = 0.0`
for `maple_table` in `spatial_geometric_oracle.py:20-21`, where every other table reads 0.75.

Meanwhile the **action-head diagnosis has measurements**: the place phase is destination-agnostic --
the plate's start distance differed 40.6 mm between layouts while the transport endpoint moved
4.9 mm, with peak lift identical to 0.1 mm. From a corpus with `APPLE_SPAWN_XY_RANGE_M = 0.0`, a
memorised absolute reach height produces exactly a constant vertical offset in a fixed scene, and
nothing measured excludes it. Independent support that this failure mode is real for our family of
model: under LIBERO-PRO's position perturbation, GR00T-N1.6 scores **28.1** having scored >0.9 on
stock LIBERO; VLATest finds VLAs pass **34.0%** of cases under mutated camera poses; and
[2510.02268](https://arxiv.org/html/2510.02268) shows policies infer camera pose from static
background cues in fixed scenes and that "this shortcut collapses" -- which is precisely a
zero-variation corpus evaluated at a shifted pose.

**A signed constant bias under a constant scene is weak evidence for monocular scale ambiguity**,
which is multiplicative and should co-vary with range.

### 2.4 The teacher has no metres to give -- two removals, not one

v1 argued the loss is scale-invariant. True, and verified in our code
(`(F.normalize(projected, dim=-1) * F.normalize(target, dim=-1)).sum(-1)`), but v1's "**by any
teacher**" overreached. Cosine discards only the *norm* -- one scalar per token -- and absolute depth
is also one scalar, so it could in principle live in the *direction* of a 1024-D vector:

```
‖f_T − f_S‖²  =  (‖f_T‖ − ‖f_S‖)²  +  2‖f_T‖‖f_S‖(1 − cos θ)
```

Cosine penalises only the second term. The airtight argument is the **second** removal: our teacher
has no metres in either magnitude or direction, because its metric-ness is a scalar applied *outside*
the network. `depth_anything_3/utils/alignment.py:118` is `depth * (focal_length / 300.0)`, applied
to the DPT head's output, and `DA3METRIC-LARGE`'s config declares **no camera head** (verified in our
own checkpoint). DA3 trains in canonical camera space at f=300 on scale-normalised targets, as VGGT
does explicitly -- "we do not apply such normalization to the predictions ... instead, we force it to
learn the normalization we choose." That is good architectural reason to doubt the layer-23 features
carry metres at all.

But it is an **argument, not a proof**, and §2.5b weakens it: if the metres really did live cleanly in
a post-hoc `focal/300` multiply, applying that multiply would produce metric depth, and it does not --
it roughly doubles the error, while the canonical-resize mechanism is refuted outright. So the honest
position is that the representation is *probably* scale-free, for reasons of training-target
normalisation rather than of a clean post-hoc factorisation. **W5 settles it empirically in an
afternoon**, and until it reports, treat this as the leading hypothesis rather than a finding.

**A third removal, code-verified.** SF slices `agg_vggt_hidden[:, :, patch_start_idx:, :]`, keeping
only patch tokens and **discarding the teacher's camera token** -- the one carrying its predicted
intrinsics, and the only place a focal length could enter. Evo-0, by contrast, keeps camera, register
*and* 3D tokens. Our `_forward_da3` inherits the same shape by a different route: it returns
`net.backbone`, **discarding the DPT head**, and this monocular checkpoint emits no camera token to
discard in the first place. So on both paths the one quantity that disambiguates metres is dropped
before the loss sees anything.

**And the loss-form question is unablated everywhere, not just in SF.** Upstream implements cosine and
nothing else -- the `else` branch is `raise NotImplementedError`, so there is no reference MSE variant
to copy. REPA, which SF builds on, compares only NT-Xent against negative cosine similarity -- **both
scale-invariant** -- and never tests MSE. Meanwhile **GLaD uses unnormalised squared L2 against the
same frozen VGGT** at the same LLM-hidden-state site and reports 94.1% LIBERO average, without ever
ablating against cosine. So the magnitude-preserving variant is not exotic; it is in use and
unmeasured against the variant we built. W5 is the cheap way to find out which side of that we are on.

**Consequence either way: "metric teacher" is a weak differentiator.** The old plan's §2 selected
`DA3METRIC-LARGE` for metric-ness that the loss cannot transmit and the representation probably does
not hold. The `DA3MONO-LARGE` contrast arm is well designed to detect exactly this and should be
kept.

### 2.5 What the teachers *do* have: the apple's relief

Measured on the dataset frames training actually feeds, with no ground truth required, by fitting the
table plane in 3D and asking whether the apple protrudes. The apple's true relief is 3.4 cm at
~0.5 m, i.e. **+6.8% of range** -- a ratio, so it survives the scale error.

| Teacher | table planarity RMS | apple relief | vs truth +6.8% |
| :--- | ---: | ---: | ---: |
| `DA3METRIC-LARGE` | 2.46% | +3.75 cm | **+8.99%** (1.3x) |
| `DA3-BASE` | **0.91%** | +9.44 cm | +12.14% (1.8x) |
| `DA3MONO-LARGE` | 3.13% | +25.99 cm | +38.5% (5.7x) |
| `Depth-Anything-V2-Small` | 2.38% | +10.23 cm | +42.4% (6.2x) |

**Every teacher sees the apple**, with the correct sign, and `DA3METRIC-LARGE` reproduces the ratio
to within 1.3x. The geometry we need is present in the features; only the absolute anchor is absent.
Caveat: affine-invariant teachers need a scale **and shift** fit, so the last two rows are indicative
rather than fair -- a plain `1/d` inversion is not the right transform for them.

### 2.5b The teacher's absolute error was mostly my formula -- and it is anchorable

**Two retractions from v1.** First, v1's headline "24.6 cm at the tabletop on the frames training
feeds, 1.48x" is not defensible: given §2.1 the GT depth is the default-pose render, so that row
compared different physical surfaces at the same pixel coordinates. Second, and larger: **the
`x focal/300` transform both plans prescribed makes the error roughly twice as bad.** On the properly
paired frame, table region only, GT median 0.501 m:

| Conversion of the net output | pred/gt | median abs err |
| :--- | ---: | ---: |
| raw, no rescale | 1.568x | 29.1 cm |
| `x f_native/300` (458.12/300), as the old §W5 prescribed | 2.394x | 70.8 cm |
| `x f_proc/300` (491.03/300), as v1 computed it | 2.566x | 79.5 cm |
| **one fitted global scale (0.655, numerically ~300/f)** | **1.027x** | **1.64 cm** |

So DA3METRIC-LARGE's relative geometry on this camera is good to **1.64 cm at 0.5 m -- well inside
the 7 cm target** -- once anchored, and the "teacher doesn't know the range" framing was an artifact
of applying DA3's own documented formula in a regime where it does not hold.

> [!CAUTION]
> **The tempting explanation is wrong, so do not ship the shortcut.** `300/f` is suspiciously close
> to the fitted scale, which suggests a canonical-focal units bug -- DA3 de-normalises from a
> canonical camera at `f_c = 300`. I tested it: feeding the image resized so its effective focal
> *is* 300 gives **2.358x**, worse, and the raw ratio moves the wrong way with `f_eff`
> (1.568x at 491 px, 2.358x at 301 px). The canonical-resize mechanism is **refuted**, so the
> matching arithmetic is a one-scene coincidence with no verified mechanism. Treat 0.655 as a
> **fitted anchor, not a formula** -- it is the same global scale the §2.5 fit already found by
> another route, and a coincidence without a mechanism is exactly what breaks on the next scene.

The literature says anchoring is the standard practice, not a workaround: DA3's own training pipeline
aligns teacher depth to sparse metric measurements by RANSAC global scale-shift, and MOMA (IROS 2025)
does a one-shot scale-shift-rotation fit against a static table plane per camera pose, taking raw
monocular error of 0.24-1.12 m down to 13-21 mm against a stated manipulation bar of **MAE < 30 mm**.
Our 1.64 cm is already inside that bar.

### 2.6 The literature's verdict on the method we built

- **Spatial Forcing does not ablate what we assumed it did.** Its three axes are target
  representation (SigLIP 94.0 / DINOv2 94.1 / VGGT-no-PE 94.7 / VGGT 96.9), aligned layer, and
  iterations/data fraction, plus loss weight (best α = 0.5). There is **no metric-vs-relative teacher
  ablation** -- all four of its teachers are scale-normalised or scale-free -- and **no loss-form
  ablation**. The strings `cm` and `mm` appear **zero** times in the paper; its depth probing is
  qualitative, through an affine-invariant DPT head. Its one height task gains the least of any.
- **The structural twin of our approach scores below baseline.** 3D-Mix's nine-scheme pilot, SIMPLER
  average, base 57.81: 3D-Tokens (cosine align on a geometry token) **56.25**; Spatial Forcing
  **58.85 (+1.04)**; Concat Fusion 60.42; GatedFusion **68.23 (+10.42)**. Both zero-inference-cost
  schemes are the weakest non-catastrophic ones, and every scheme that won meaningfully **kept the
  geometry model in the inference path**.
- **Metric specifically does help -- as a frozen input.** OASIS is the one matched-backbone ablation:
  removing metric depth costs LIBERO-Long 95.2 → 91.8, and substituting Depth-Anything-V2's relative
  depth recovers only to 92.0. "Metric scale, not depth in general, is what helps."
- **But a depth-regression head on the shared backbone destabilises.** GLaD reports explicit depth
  prediction "caused training divergence due to conflicting objectives"; QDepth-VLA finds pixel-wise
  regression costs −3.9% and removing the depth *expert* costs −8.5%; BridgeVLA's swap from a heatmap
  head to direct MSE position regression craters RLBench **88.2% → 31.4%**. The pattern across all
  of them: regression **through** the shared VLM hurts, regression in a **separate branch** works
  (DepthVLA, MVUCF, QDepth's expert).
- **The closest published match to our situation reports centimetres.** MVUCF puts a Softplus head
  regressing metres (0.05-5.0 m) at **GR00T-N1.6 layer 15**, freezes layers 0-7, deletes every head
  at deployment for zero inference cost, and reports depth-probe MAE **4.9 cm → 0.44 cm** and
  fraction within 2 cm **44% → 97%**. It also reports that **layer 12 "degraded token-level
  separation after training"** -- directly relevant to our `backbone_layer_{6,9,12}` sweep. No code
  released.
- **Two published recipes for W6's loss, and one cautionary tale.** DepthVLA is the closest
  working example: a depth expert in a mixture-of-transformers, no sensor at inference, trained with
  the **Eigen scale-invariant log loss at λ = 0.5** -- i.e. only *half* the scale term removed, so it
  is partially scale-aware -- against **metric** pseudo-labels from UniDepthV2 and Depth-Anything-V2.
  It gains **+16.0** on Simpler WidowX over its own π₀ re-implementation (58.8 → 74.8) with no action
  pretraining. QDepth-VLA is the counterexample that names our problem: it quantises **relative**
  depth into VQ-VAE tokens and concedes in its own ablation that "relative depth lacks absolute
  positional encoding necessary for stable control" (−5.5% avg, −15.8% on one task). And DreamVLA is
  the trap -- its auxiliary depth loss is a **deliberately scale-normalised MSE** that "removes the
  global scale ambiguity ... while ignoring any arbitrary global scale shift", which is exactly the
  mistake W6 exists to avoid. λ is therefore a **design decision, not a default**: at λ=1 the loss is
  fully scale-invariant and W6 degenerates into §2.4.
- **Our decisive advantage is that we have exact metric GT.** Every objection the literature raises
  to depth supervision is about pseudo-label noise. G³VLA measured a monocular teacher predicting a
  median 3.535 m against a simulator GT median of 0.027 m -- a **132.4x** ratio -- and concluded sim
  GT depth is what works. So: **do not distil a foundation model's metric scale; regress sim GT
  depth in metres.**

### 2.7 We were selecting the teacher on the wrong axis

**No paper in the literature uses a metric depth model as a Spatial Forcing teacher.** Every
follow-on -- GLaD, 3DThinkVLA, GWM-VLA, G³VLA, GeoAware-VLA, and
[2605.24642](https://arxiv.org/html/2605.24642v1), which pairs VGGT with **GR00T-N1.5** and is the
closest published work to this repo -- uses a VGGT/π³-class **multi-view pointmap** teacher. SF's own
encoder ablation credits multi-view geometric aggregation (base 92.7 → SigLIP 94.0 → DINOv2 94.1 →
VGGT 96.9), not metric accuracy. Combined with §2.4, the axis to select on is **multi-view geometric
richness and boundary sharpness**, not metric-ness -- which is what `DA3-BASE` has (`alt_start=4`)
and `DA3METRIC-LARGE` does not (`alt_start=-1`).

**And teacher choice may barely matter.** Any3D-VLA is the one paper that ablates the depth source
inside a tabletop manipulation policy, in a 40x50x20 cm workspace: Isaac-Sim GT **80.0**, UniDepthV2
**81.1**, DA3-metric **78.9**, MapAnything **80.0** -- all within noise, with estimated clouds
beating a RealSense D435 on transparent objects. Its conclusion, and SpatialVLA's, is that
hybrid-source *training data* matters far more than the estimator. **That is a direct argument for
spending on W2 rather than on teacher selection.**

Near-field is structurally out of distribution for this whole model class, and it is documented by
omission: **no primary source publishes an error band below 1 m** for any of these models. NYU-Depth
v2's ground truth comes from a Kinect v1 whose specified minimum is 0.4-0.8 m, so the canonical
indoor supervision set contains almost no real sub-0.5 m depth; DA3's metric head was fine-tuned on
13 named datasets of which 9 are driving, with nothing tabletop or sub-metre. Independent measurements
at our range agree with ours: MOMA reports raw Metric3Dv2 MAE 0.24-0.33 m and DAv2 0.71-1.12 m on a
fixed tabletop; a wildlife benchmark at 1-5 m finds Pearson **r 0.93-0.97 with badly wrong scale** --
the same structure-right/scale-wrong signature as §2.5b.

Licence-clean candidates, if a teacher swap is ever justified, verified on tag, card body and repo:

| Candidate | Licence | Why |
| :--- | :--- | :--- |
| `facebook/map-anything-apache` | **Apache-2.0** (all three sources agree) | The only licence-clean teacher with real multi-view alternating attention -- the property SF's ablation credits. 1.23B, so 3.5x our compute. Its single-view metric depth is poor, which §2.4 says should not matter under a cosine loss. |
| `Ruicheng/moge-3-vitl` | MIT (code; weights via HF tag only) | 370M, same size class as our current teacher, so the projector width and 8x11 resampling are unchanged. Boundary F1 **2.4x** DA3's, and DA3 ranks last on that axis -- boundary sharpness is what a 3.4 cm apple needs. |

> [!CAUTION]
> **Two licence traps.** `yyfz233/Pi3` is tagged `bsd-2-clause` on Hugging Face while its README says
> the weights are CC BY-NC 4.0, "Strictly Non-Commercial" -- and it is tempting because it wins
> ClearPose. **Add it to the old plan's §8.2 exclusion table.** `lpiccinelli/unidepth-v2-vitl14`
> carries **no licence field at all** while its repo is CC BY-NC 4.0; it has the best published indoor
> metric numbers, so it is usable for measurement only, never for shipping. Both corroborate the old
> plan's finding that HF cards mis-state licences, and that the repo is authoritative.

### 2.8 The range/bearing asymmetry is a documented class failure

Our signature (bearing inside the apple's radius, range wrong) is not idiosyncratic. The one paper
that decomposes imitation-policy error on exactly these two axes is
[2605.28736](https://arxiv.org/html/2605.28736) -- ACT, Diffusion Policy, SmolVLA and π₀, 28 trained
models -- and it separates "**lateral error** ... a failure in visual localization of the thread in
the image plane" from "**depth error** ... does not reach far enough (undershoot) or extends too far
past". Its findings, in order of relevance to us:

- "**depth errors are the dominant failure mode**, accounting for 20-35% of all test episodes, while
  lateral errors are markedly less frequent (0-25%)". Even its strongest model "fails almost
  exclusively due to depth errors (20%) rather than lateral mislocalization (5%)" -- the policies
  "have **largely solved the lateral localization problem** but continue to struggle" with range.
- **More demonstrations do not fix it**: depth errors stay at 20-35% "even at 160 episodes for every
  policy, suggesting that depth reasoning ... is **bottlenecked by the available perceptual signal
  rather than by demonstration count**." This is a direct warning about W2: spatial variation is
  necessary for a spatial objective to bind, but volume alone will not close a range gap.
- **The camera ablation is the actionable part.** "On-arm only (no side camera) causes depth errors to
  spike for every policy (**40-65%**), while side-cam only (no on-arm camera) shifts the failure mass
  into lateral errors of 30-45%." The two axes are carried by *different views*: bearing by the
  wrist/on-arm view, range by the side view.

**Mechanistic corroboration from our own model family.** GR00T N1's only spatial auxiliary is an
image-plane bearing loss and nothing else: it annotates target bounding boxes with OWL-v2, then
supervises "the **normalized center coordinates** ... by dividing its x and y coordinates by the image
width and height." There is **no range term anywhere in the objective**. A model trained to predict
normalised image-plane centres and nothing else is precisely a model with good bearing and unanchored
range. (Flagged: the causal link is ours; the paper draws no such conclusion, and N1.7 is a different
backbone -- but N1.7's relative-EEF action space and 20K hours of monocular human-video pretraining
supply no metric anchor either, so scale must come entirely from fine-tuning data.)

**The remedy this implies is cheaper than every method in §2.6 and is not on our work list**: check
whether the G1 head camera is the *only* view feeding the policy, and if so whether a second
viewpoint with baseline against the approach axis is available in the embodiment config. Range from
two views is triangulation, not inference. This should be priced before W6.

### 2.9 Verified absences -- what the literature will not tell us

Recorded so these are not re-searched. Each was looked for specifically and not found:

- **No paper decomposes VLA reach error into latency vs perception vs calibration.** RTC
  ([2506.07339](https://arxiv.org/html/2506.07339)) reports success rate, task-progress steps and
  throughput only; its sole decomposition tables are *compute* latency by component (SigLIP 18 ms,
  Gemma-2B prefill 44 ms, ...). It blames chunk **discontinuity** and distribution shift, not bias.
  So §2.2's plateau argument has no published template -- W3 is building the decomposition, not
  reproducing one.
- **No paper reports a signed per-axis (x/y/z) end-effector bias in metres for a VLA.**
  [2511.11298](https://arxiv.org/html/2511.11298) gets closest, naming "height (Z-axis) misalignment
  on bag (**closes above surface**)" and attributing pre-grasp error to "visual grounding drift and
  depth sensing noise" -- but unsigned and unquantified, and it explicitly warns that "ambiguities
  between perception precision, control timing, and state estimation make root-cause diagnosis
  non-trivial." G3's numbers will be the first of their kind we have seen; treat them as such.
- **No arXiv technical report exists for GR00T N1.5, N1.6 or N1.7**, and no NVIDIA document of any
  kind reports a vertical failure mode or per-axis error. N1 contains no failure analysis at all.
- **FLARE is absent from our vendored `submodules/Isaac-GR00T`** -- `grep -rn -i flare` returns only
  an unrelated CSS hit under `external_dependencies/depth-anything-3`. There is no upstream alignment
  infrastructure to reuse; `gr00t/model/modules/geometry_conditioning.py` is the whole geometry path.
- **No learned residual *calibration* correction for a learned policy exists.** The classical hand-eye
  literature fits height-dependent calibration offsets; the residual-RL literature corrects in
  *action* space. Nothing bridges them, so if W3 returns "calibration" the fix is ours to design.
- **W6 is unpublished territory.** No auxiliary-loss experiment anywhere regresses metric depth in
  metres and compares it against a scale-normalised target. OASIS varies a frozen *input*;
  QDepth-VLA and DreamVLA use relative or scale-normalised targets exclusively. That is the
  experiment our hypothesis calls for, and it means W6 has no baseline to inherit -- and, if it
  works, is publishable.

## 3. The re-ordered thesis

> The 7 cm is real and measured. Whether it is perceptual is not established, and the leading
> alternative -- a memorised reach height from a zero-variation corpus -- is both better evidenced
> and unfixable by any geometry teacher. Two confounds must be removed before any method can be
> evaluated: a frozen renderer that invalidates all ground truth, and a corpus with no spatial
> variation for a spatial objective to bind to.

Decision tree, in order:

1. **W1** unfreezes the render. Nothing downstream is measurable without it.
2. **W2** adds spatial variation. Without it no perception-side loss can help, and no gate is
   informative.
3. **W3** discriminates scale from offset, and perception from calibration. *This decides the method.*
4. **W3b** prices a second viewpoint before any method is funded. §2.8 shows range and bearing are
   carried by *different views*, and triangulation beats inference.
5. If perception is implicated → **W6**, a separate depth branch regressing sim GT metres.
   If calibration or memorisation is implicated → geometry supervision is the wrong tool: the remedy
   is data variation plus a calibration fit, or **W9**'s residual, which is the one published fix for
   our exact symptom.

## 4. Work items

### W1 -- Unfreeze the render
Four one-line discriminators, cheapest first, all in `render_frame`:
`env.sim._physics_step_count += 1` (isolates the dedupe, no physics effect);
`env.sim.render_context.reset_transform_cadence()` (sanctioned API);
`env.sim.physics_manager._sync_fabric_after_resume()` (PhysX-specific);
and in `main()`, `env_cfg.sim.use_fabric = False` -- **the decisive one**: if the render unfreezes,
the break is in the Fabric path. Add the bit-identical-depth guard from §2.1. Needs the Arena
container, currently `Exited (137)` (OOM).

### W2 -- Give the corpus spatial variation
`APPLE_SPAWN_XY_RANGE_M = 0.0` against a 20x22 cm evaluation range is the single largest confound.
This is cheaper than any method in §2.6 and is a prerequisite for measuring any of them. Re-record
or augment with genuine spawn variation in both position and support height.

### W3 -- Discriminate the diagnosis  *(this gates the method)*
Regress `hand_z_minus_obj` at closest horizontal approach against target range, over 3+ placement
seeds at differing base→apple distance. **Non-zero slope is scale; a flat line is offset.** Use the
seed/distance axis, not deck height, until `Z_deck` is derived from the fixture bounding box. Fix
`ReachTracer` to reset per episode and write an episode index first, or the result will be as
irreproducible as the tables in §2.2. Add the falsification arm the record never ran: apply
`cartesian_vertical_offset_adapter` and see whether a constant offset closes it -- if it does, the
diagnosis is calibration, not perception.

### W3b -- Make range observable: temporal parallax now, a second camera only with W2
Per §2.8, range and bearing are carried by different views. **The feasibility question is already
answered, and the answer is the expensive branch:** `G1CameraCfg` exposes exactly one camera,
`robot_head_cam`, and the corpus recorded exactly one view,
`observation.images.ego_view`. So a genuine *spatial* second view means changing the embodiment rig
**and** re-recording all 251 episodes -- it folds into W2's cost and does not compete with it. It is
not the cheapest remedy on the list.

What *is* cheap and already built is **temporal** parallax: `g1_sim_wbc_data_gr00t_n_1_7_parallax_config.py`
stacks the same camera at `delta_indices [-8, 0]`, and the `parallax` and `align_parallax` arms are
already wired in the launcher. That makes range observable through *motion* rather than through a
baseline, needs no new sensor and no re-record, and is the one item here that can run the moment W1
lands. It is weaker than triangulation -- the baseline is whatever the head moved in 8 frames, which
in a corpus this static may be almost nothing, and §2.3's `obj_z` spread of ~1 cm is a warning -- so
measure the effective baseline before drawing conclusions from a null result.

If W2 is funded, add a second camera with usable baseline against the approach axis **in the same
re-record**, since the marginal cost there is small and §2.8 says it targets exactly our failing
axis.

### W4 -- Re-derive the camera mount
`calibrate_corpus_camera.py`'s fitted offset is likely an artifact of §2.1. Re-run after W1 and
compare; if it collapses, the camera-pitch line of investigation needs revisiting too.

### W5 -- Does direction carry the scale?  *(one afternoon, settles §2.4)*
Fit `probe_depth_readout.py`'s ridge probe on **L2-normalised** layer-23 teacher features versus
unnormalised. If metric accuracy survives normalisation, direction carries scale and cosine alignment
can in principle transfer it; if it collapses, magnitude carries it and cannot. No paper asks this.

### W6 -- If perception is implicated: a separate depth branch, regressing sim GT metres
Per §2.6, **not** a head on the shared backbone. A small separate branch, scale-*aware* loss
(Eigen-style log loss at low λ, or a binned/heatmap readout over a metric range given BridgeVLA's
result against direct regression), target = **Isaac Lab GT depth in metres**, deleted at deployment.
Tap depth around layer 15 rather than 12, per MVUCF. Keep `align` only as a relative-structure
regulariser if W7's arms justify it.

### W7 -- Environment unblock
`/datasets` is not mounted in `gr00t-server`; `docker/run_gr00t_server.sh` has no reference to it and
`finetune_n17_geometry.sh:35` defaults there. Four-line diff in the old plan's §W6a. `docker/` is
**"ask first"** -- draft PR.

### W7b -- Anchor the teacher once, MOMA-style
Since §2.5b shows one global scale reaches 1.64 cm, fit the anchor properly rather than by a formula:
RANSAC scale-shift against the table plane, once per camera pose, with depth min-max normalisation
(MOMA reports that omitting the normalisation degrades MAE 13.4 → 41.3 mm). This matters only for
measurement and for any scale-*aware* objective (W6); the cosine path in W8 does not consume it.

### W8 -- Arms, minimal
Only after W1-W3. `baseline`, the primary teacher chosen by relief fidelity (§2.5), and
`DA3MONO-LARGE` as the contrast that tests §2.4's claim that metric-ness is not carried in the
representation. The five-arm matrix and the site/coefficient sweeps stay deferred.

### W9 -- If calibration or memorisation is implicated: an object-centric residual
[2606.18953](https://arxiv.org/html/2606.18953) is the one published remedy for our literal symptom,
on our base model family (GR00T-N1.5). Its Table 6 of shared sim/real failure modes reads, verbatim:
"**Hovers above cube, misses grasp** → Residual Fix: **Pushes end-effector down to the cube**", and
"Stops short of target → Moves end-effector closer." The residual is trained **only in simulation**
against the frozen base policy's own failures, and transfers zero-shot because it "observes object
pose, a representation invariant across domains" rather than pixels. That property is why it survives
the §2.1 render bug and the §2.3 memorisation diagnosis alike: it never looks at an image. Cheaper
than W6 and orthogonal to it -- it corrects the *action*, not the perception -- so it is the right
first move if W3 returns "offset". Compare against the existing
`cartesian_vertical_offset_adapter` falsification arm in W3: a constant offset is the zeroth-order
version of the same idea, and if that closes the gap, W9 is unnecessary.

## 5. Gates

**G1 -- diagnosis.** W3 returns a slope or a flat line, with enough range spread to distinguish them.
Failing this gate means we still do not know what we are fixing, and no method should be funded.

**G2 -- readout, honestly split.** On W2's varied corpus with a genuinely held-out split (assert the
targets differ at load time -- v1's baseline failed precisely here), the probe's depth error drops
materially against the baseline policy's embeddings.

**G3 -- task endpoint.** Hand-to-apple vertical error at closest horizontal approach, from a fixed
`ReachTracer`. Baseline to beat: **+0.1286 m at chunk 16, +0.0795 m at chunk 8**. Note §2.2: the
4.48 cm floor is not a real floor, and chunk 4 already reaches 3.37 cm.

## 6. What we are not doing, and why

- **Not swapping in another metric teacher for its metric-ness.** §2.4 -- the representation does not
  carry metres. `UniDepthV2` would be architecturally ideal but is CC BY-NC-4.0; VGGT's weights are
  CC-BY-NC-4.0, confirming the old plan's §8.2.
- **Not replacing cosine with unnormalised L2 against layer 23.** Those features are canonical-space,
  so L2 would transfer feature magnitude, not metres.
- **Not adding depth at inference yet.** §2.6 says the schemes that won all did, which makes this the
  strongest fallback -- but it contradicts the deployment constraint, so it is a decision for §8, not
  a default.

## 7. Risks

1. **W1 may not be a one-liner.** If the Fabric path cannot be refreshed without stepping physics,
   state playback may need a genuine `sim.step()` with zeroed dynamics, which changes what "replay"
   means.
2. **W3 may return "offset".** Then this whole line of work is the wrong tool, and the honest outcome
   is data variation plus calibration. Record it plainly.
3. **W2 may be expensive.** Re-recording demos with spatial variation is the costliest item here, and
   it is also the one with the clearest independent support (§2.3).
4. **Broken background materials.** Fallback vs dataset materials move the teacher's prediction by a
   **median 52.7 cm** on identical geometry, so every teacher measurement must use the RGB training
   actually feeds.
5. **The truncation risk** is unchanged (effective depth 0.62 against upstream's best 0.75), and
   MVUCF's layer-12 finding suggests the shallow end of our sweep may be actively harmful.
6. **W6 has no published baseline** (§2.9). Its λ, its tap site and its readout parameterisation are
   all unmeasured in combination, and the closest published points disagree: DepthVLA succeeds at
   λ=0.5 with a separate expert, DreamVLA neutralises scale on purpose, GLaD diverges outright with a
   backbone head. Budget for a λ sweep, not a single run.
7. **More data may not close a range gap** even with variation. §2.8's depth-error rate is flat from
   40 to 160 episodes per task. If W3 says "perceptual-absolute", W2 alone will not be sufficient and
   W3b or W6 becomes load-bearing.

## 8. Open decisions

1. **W7's mount** -- approve the `docker/run_gr00t_server.sh` diff, or stage the dataset under
   `~/models` as a one-off.
2. **Is depth at inference genuinely off the table?** The old plan assumed yes because the robot has
   no depth sensor. §2.6 says that is where the large wins are. Worth an explicit answer before W6.
3. **How much to spend on W2** before W3 reports -- the two are somewhat independent, and W3 on the
   *current* corpus is cheap and still discriminating.
4. **Whether to keep `align` at all** if W5 shows magnitude carries the scale and W3 says the error is
   perceptual-absolute. Then a separate metric branch is the whole intervention.
5. **Is a second view genuinely unavailable?** (§2.8, W3b.) This is the cheapest remedy on the list
   and the only one that makes range observable rather than inferred. It deserves an answer before
   W6 is funded, and it is a different question from decision 2 -- a second *RGB* view needs no depth
   sensor and so does not violate the deployment constraint.
