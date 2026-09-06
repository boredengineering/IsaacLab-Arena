# Metric Range for the G1 Policy: Fix the Confounds, Then the Method

> [!NOTE]
> **Role changed 2026-09-06.** This document is now the **measured evidence appendix**, not the
> active plan. The build is directed by
> [`da3_spatial_forcing_pipeline_plan.md`](da3_spatial_forcing_pipeline_plan.md): annotate the
> recorded corpus with `DA3METRIC-LARGE`, finetune N1.7 with Spatial Forcing, serve RGB-only.
>
> What stays load-bearing here: §2.2's reach tables, §2.5/§2.5b's teacher measurements (the
> `focal/300` pairing trap and the fitted-scale result), §2.8's range/bearing asymmetry, §2.9's
> verified absences, and §19-23 of `session_memory.md`. **§20's ranked method shortlist and the
> W-series work items are no longer the plan of record** -- the method is chosen. W2 (spawn
> variation) survives as the next lever and is restated as §4 of the pipeline plan.
>
> One §2.5b loose end is now closed: the empirically measured 1.64x `focal/300` factor is
> **explained**, not merely observed. The focal that belongs in DA3's conversion is the focal at
> the resolution the network is fed, and 458.1px x (518/480) / 300 = **1.637**, which the
> annotator now computes and prints. The formula was right; the raw output was already 1.568x
> large, which is why applying it made the error worse.

> [!IMPORTANT]
> **Status**: PLAN v2.2, 2026-09-06. v2.2 **retracts one v2.1 claim of its own**: §2.8's assertion
> that a second camera is the cheapest remedy was wrong -- it generalised the DROID *policy* config to
> the G1 *embodiment rig*, and `G1CameraCfg` has exactly one camera, so a spatial second view costs a
> rig change plus a 251-episode re-record. W3b now leads with temporal parallax instead. v2.1's
> §2.4 "third removal" is also demoted: it is real upstream but **void for our monocular teacher**.
> Surviving v2.1 additions: §2.6's two published loss recipes, §2.8's range/bearing corroboration,
> §2.9 (verified absences), W9 (residual). No v2 finding is retracted. Originally: PLAN v2, 2026-09-05, replacing v1 of the same day. Supersedes §W5, §W7
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
4. **The teacher lacks an absolute anchor, not usable geometry.** Its relative structure is good to
   **1.64 cm at 0.5 m** once one global scale is fitted -- inside the 7 cm target -- and v1's much
   worse figure was an artifact of applying DA3's own `focal/300` transform, which doubles the error
   here (§2.5b). What the cosine loss cannot transmit is that one scalar. And the literature's only
   structural twin of our approach scores *below* baseline.

So the plan is: unfreeze the render, fix the corpus, *discriminate the diagnosis*, and only then pick
a method -- which, if perception is implicated, is probably not the one we built.

## 2. Verified findings

### 2.1 The rerender: physics is correct, the render is frozen

`sim.forward()` updates kinematics without stepping physics, and **every** path that pushes body
transforms to RTX is keyed on the physics step counter that only `step()` increments:

- `RenderContext.update_transforms` returns early when `_last_transforms_step == physics_step_count`
  (`renderers/render_context.py:112-120`) -- with a frozen counter, a permanent no-op. **Corrected
  2026-09-06: this gate is moot.** `IsaacRtxRenderer.update_transforms` is itself `pass`, so the
  push does nothing on this renderer whether the gate opens or not. The conclusion below survives;
  this mechanism does not. See the execution log.
- Its one scene-level call site is guarded by `if not self.cfg.lazy_sensor_update`
  (`scene/interactive_scene.py:634-635`), and `lazy_sensor_update` defaults to `True`
  (`scene/interactive_scene_cfg.py:80`) and is **never overridden anywhere in Arena**. The transform
  push that `render_frame`'s comment says it relies on is dead code.
- Under Newton, `sync_transforms_to_usd` early-returns on `_transforms_dirty`, which only stepping
  sets. Under PhysX, Isaac Lab's own comment describes the FabricManager "causing articulation meshes
  to freeze visually while physics continues to run", with a `_re_sync_fabric()` workaround wired
  only into the pause/resume path.

> [!IMPORTANT]
> **Read the two callouts below together; the first was written before it was tested and its
> conclusion did not survive.** The source audit in it is sound -- the push is dead at the leaf -- but
> its proposed cause (Fabric/USD) was measured and refuted, along with two other candidates. See
> "W1 results" in §9. What §2.1's own bullets and observation say still stands; the mechanism is open.
>
> **Source audit, 2026-09-06 -- the push is dead at the leaf.** The three
> bullets above are all true but none of them is the operative cause, because the push is dead **at
> the leaf**, not merely gated and deduped:
>
> ```python
> # isaaclab_physx/renderers/isaac_rtx_renderer.py:381
> def update_transforms(self) -> None:
>     """No-op for Isaac RTX - uses USD scene directly."""
>     pass
> ```
>
> `IsaacRtxRenderer` inherits nothing better, so **every** route into
> `render_context.update_transforms` -- gated, un-gated, deduped or cadence-reset -- terminates in
> `pass`. Discriminators #1 and #2 are therefore not merely insufficient, they are **provably
> incapable**, and this was confirmed empirically: option (a) of the W1 callout (cadence reset plus a
> direct un-gated `update_transforms` call) left the render **bit-identical**, caught by the new
> §2.1 guard on frame 1 against a state delta of 5.09.
>
> The actual chain is one line further out. RTX "uses USD scene directly", and
> `SimulationCfg.use_fabric` (`simulation_cfg.py:262`, **default `True`**) is documented as: *"Enable/
> disable reading of physics buffers directly ... updates in the states in the scene is normally
> synchronized with USD. This leads to an overhead ... This flag allows **disabling the
> synchronization** and reading the data directly from the physics buffers."* So on defaults,
> `reset_to` writes physics, Fabric serves reads from the physics buffers, **USD is never
> synchronized**, and the renderer draws the last state USD actually saw. That is why
> `--validate_states` reports exactly 0.0: it reads back through the same Fabric path that is
> correct.
>
> **This predicted that `use_fabric = False` would fix it. It does not** -- measured, see §9. Nor does
> adding a real `sim.step()`. So the Fabric/USD story above is a plausible-but-false lead: keep the
> leaf-level `pass` finding, discard the causal conclusion.

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

### 2.4 The teacher has no absolute anchor to give -- two removals, not one

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

**A third pathway is closed upstream -- but it is void for us, so the count stays at two.** SF slices
`agg_vggt_hidden[:, :, patch_start_idx:, :]`, keeping only patch tokens and **discarding VGGT's
camera token** -- the one carrying its predicted intrinsics, and the only place a focal length could
enter its features. Evo-0, by contrast, keeps camera, register *and* 3D tokens. This is worth
recording for one reason only: it is why **SF's published results cannot be read as evidence either
way about metric transfer**, since upstream never gave its student a focal length to work with. It is
**not** a third removal in our setup -- `DA3METRIC-LARGE` is monocular and emits no camera token, so
`_forward_da3` has nothing of the kind to discard. Its one analogous choice is returning
`net.backbone` and dropping the DPT head, and per §2.5b that head's output is not metric either
without an anchor, so dropping it removes less than it appears to.

> [!CAUTION]
> **Do not over-argue this section; §2.5 and §2.5b cut the other way and they are measurements.**
> Every teacher resolves the apple's relief with the correct sign, `DA3METRIC-LARGE` reproduces the
> true +6.8%-of-range ratio to within **1.3x**, and one fitted global scale reaches **1.64 cm at
> 0.5 m** -- inside the 7 cm target. So the features demonstrably carry good *relative* geometry.
> What is missing is **one global scalar**, which §2.5b shows is fittable and W7b fits. Read "the
> teacher has no metres" as "**no absolute anchor**", never as "no usable geometry" -- that
> distinction is the difference between W6 being necessary and W7b being sufficient, and collapsing
> it is how v1 talked itself into selecting a teacher on the wrong axis.

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

> [!CAUTION]
> **v2.1 drew the wrong conclusion here and it is retracted.** It claimed a second camera was "cheaper
> than every method in §2.6", reasoning from `pov_cam_name_sim` accepting a list on the DROID path
> (`["external_camera_rgb", "wrist_camera_rgb"]`). That is the *policy* config; the binding constraint
> is the **rig**. `G1CameraCfg` exposes exactly one camera, `robot_head_cam`, and the corpus recorded
> exactly one view, so a genuine spatial baseline costs an embodiment change **plus** a 251-episode
> re-record. It is not cheap and it does not compete with W2 -- it folds into it.

What survives is the *direction*: range is carried by baseline, not by inference from one view, so
making range **observable** should be priced before any method that tries to infer it. **W3b** does
that, leading with the cheap version -- **temporal** parallax from the already-wired
`delta_indices [-8, 0]` arms -- and deferring a true second camera to W2's re-record, where its
marginal cost is small.

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
4. **W3b** makes range *observable* before any method tries to infer it -- temporal parallax now
   (already wired, no re-record), a spatial second camera only inside W2's re-record. §2.8 shows
   range and bearing are carried by different baselines; it does **not** make a second camera cheap.
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

> [!IMPORTANT]
> **W1 source audit, 2026-09-06 -- two of the four discriminators cannot work alone.** Both halves of
> the mechanism are now confirmed verbatim in `submodules/IsaacLab`, and they compose in series, so
> defeating either one by itself changes nothing:
>
> 1. **The call site is guarded off.** `interactive_scene.py:625-634` -- `scene.update()` calls
>    `self.sim.render_context.update_transforms(self.sim.get_physics_step_count())` **only**
>    `if not self.cfg.lazy_sensor_update`, and `interactive_scene_cfg.py:80` declares
>    `lazy_sensor_update: bool = True`. `render_frame` already calls `env.scene.update(...)`, so the
>    push it relies on is dead code today.
> 2. **The callee dedupes on a frozen counter.** `render_context.py:112-120` -- `update_transforms`
>    returns early when `self._last_transforms_step == physics_step_count`, and `sim.forward()` never
>    increments that counter. `reset_transform_cadence()` (`:139-141`) sets it back to `None`.
>
> **Consequence for the four listed discriminators**: #1 (`_physics_step_count += 1`) and #2
> (`reset_transform_cadence()`) each address only layer 2 and are **necessary but not sufficient** --
> with the layer-1 guard still on, `update_transforms` is never reached whatever the counter says. A
> null result from either, run alone, is uninformative rather than exculpatory. The two ways to
> address both layers at once:
>
> - **(a) surgical, preferred** -- in `render_frame`, defeat the dedupe and call the push *directly*,
>   bypassing the guard rather than changing it:
>   `env.sim.render_context.reset_transform_cadence()` then
>   `env.sim.render_context.update_transforms(env.sim.get_physics_step_count())`.
> - **(b) config-level** -- `env_cfg.scene.lazy_sensor_update = False` **plus** a cadence reset. Wider
>   blast radius: it also changes sensor-update semantics for every sensor in the scene, which is not
>   what we want to be testing here.
>
> Discriminator #4 (`use_fabric = False`) is unaffected by this and remains the decisive test of
> *where* the break is, but it is no longer the first thing to try. Order is now: (a), then #4, then
> #3.

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
5. **Does temporal parallax carry enough baseline to be worth anything?** (§2.8, W3b.) It is the only
   remedy that makes range *observable* without a re-record, and it is already wired -- but in a
   corpus this static the effective baseline over 8 frames may be near zero, so measure it before
   trusting a null result. A **spatial** second view is not the cheap option (W3b: rig change plus a
   251-episode re-record); the live question is whether to bundle it into W2 if W2 is funded. Note
   this is distinct from decision 2 -- a second *RGB* view needs no depth sensor, so it does not
   violate the deployment constraint.

## 9. Execution log

### 2026-09-06 -- W1 implemented

**Environment.** `isaaclab_arena-latest` was `Exited (137)` as §W1 recorded. Restarted cleanly with
63 GB of 91 GB available, so the earlier OOM was transient load, not a standing constraint.
`import isaaclab_arena` verifies inside the container.

**Source audit.** Both guards confirmed verbatim (see the W1 callout): the `lazy_sensor_update`
gate on the call site, and the frozen-counter dedupe in the callee. This retired discriminators #1
and #2 as standalone tests before spending a run on either. Corroborating evidence that the audit is
right: an earlier `smoke_sceneupdate` arm already tried adding `env.scene.update(...)` and scored
`rgb_fidelity.mean_abs_diff` **54.47**, no better than the `regression` arm's **53.40** -- exactly
what §2.1 predicts, because `scene.update` cannot push transforms while the gate is on.

**Change, option (a) -- surgical.** `rerender_demos.py::render_frame` now clears both layers before
rendering, without touching scene-wide sensor semantics:

```python
env.sim.forward()
env.sim.render_context.reset_transform_cadence()                              # defeat the dedupe
env.sim.render_context.update_transforms(env.sim.get_physics_step_count())    # bypass the gate
env.scene.update(dt=env.physics_dt)
```

**Guard added, per §2.1.** `assert_render_not_frozen` fails the run when a rendered frame is
bit-identical to its predecessor *while the recorded state moved*, with `state_max_abs_delta`
walking the nested state dict for the comparison. It prefers depth as the witness (geometry-bearing
and not smoothed by video encoding) and falls back to RGB under `--no_depth`. This is the guard that
`--validate_states` structurally could not provide: validation round-trips through physics, which is
precisely the layer that was already correct.

**Baselines to beat**, same dataset, episode 0, `renders_per_frame 2`, `depth_downsample 1`:
`regression` 53.40, `smoke_pitch0` 52.27, `smoke_sceneupdate` 54.47 (`rgb_fidelity.mean_abs_diff`,
lower is better; the recorded 10.26 dB PSNR is the same measurement). Smoke arm:
`eval_output/rerender/smoke/w1_transformpush`, 12 frames, `--validate_states`.

> [!NOTE]
> **Interpreting the result.** A large drop in `mean_abs_diff` confirms §2.1 end to end and unblocks
> W3/W5. A *null* result now means something specific and useful, because option (a) addresses both
> layers: it would point at discriminator #4 (`use_fabric = False`), i.e. the break is in the Fabric
> path rather than the transform-push cadence, and Risk 1 becomes live. The new guard should fire
> loudly in that case rather than producing another quietly wrong corpus.

### 2026-09-06 -- W1 results: three mechanisms ruled out by measurement

All three runs used episode 0, 12 frames, `renders_per_frame 2`. **Every one failed identically**,
with the new guard firing on frame 1 against a byte-identical state delta of **5.08701**:

| Arm | What it addressed | Result |
| :--- | :--- | :--- |
| `w1_transformpush` | cadence reset **+** direct un-gated `update_transforms` | frozen |
| `w1_nofabric` | `use_fabric = False` (re-enables `/physics/updateToUsd`) | frozen |
| `w1_step_nofabric` | `--no_fabric` **+** `sim.step(render=False)` per frame | frozen |

The third is the important one: it is the remedy Risk 1 anticipated -- a genuine physics step so the
physics-to-USD sync actually runs -- and it **did not help either**. So the freeze survives every
layer the §2.1 analysis identified, plus an actual step. `sim.step()` is not a plausible fix, and
Risk 1's proposed remedy is closed rather than pending.

**What the invariance of the failure tells us.** The state delta is byte-identical across all three
arms, which is expected (it is a property of the recording, not the render), but the *frames* being
bit-identical under three different flush mechanisms points away from a flush problem altogether. Two
candidates survive, and they are cheap to separate:

1. **The renderer is genuinely frozen** -- something upstream of all three mechanisms, e.g. the
   annotator/Replicator pipeline caching per stage rather than per render call.
2. **Only *depth* is stale.** The guard prefers depth as its witness, and nothing so far establishes
   that RGB is frozen too. This matters because the three prior smoke arms scored `mean_abs_diff`
   52-54 against recorded RGB -- a *non-zero* comparison, so RGB is being produced -- but no arm ever
   checked whether RGB *changes between consecutive frames*. Note `depth_inf_fraction` is **0.0** in
   every arm, so this is not a dead annotator returning `inf`; the depth values are real, just
   possibly not refreshed.

The `w1_rgbwitness` arm settles it: `--no_depth` makes the guard fall back to RGB. If it **passes**,
the renderer is not frozen and the defect is confined to the depth annotator -- which would rewrite
§2.1 again and would be much better news, since RGB fidelity is what the corpus is scored on. If it
**fails**, candidate 1 holds and the search moves upstream of the transform/USD layer entirely.

> [!CAUTION]
> **§2.1's mechanism is now unsupported, and should stop being cited as established.** Its three
> bullets are accurate readings of the source, but the causal claim built on them -- that defeating
> the gate, the dedupe or the Fabric/USD sync would unfreeze the render -- is refuted by all three
> arms above. The *observation* (rendered frames do not follow the written state) stands and is now
> guarded automatically; the *explanation* does not. Treat the mechanism as open until
> `w1_rgbwitness` reports.

### 2026-09-06 -- [SUPERSEDED, WRONG] "W1 answered: the renderer is not frozen; the depth annotator is"

> [!WARNING]
> **This entry's conclusion is wrong. Superseded by the next two entries.** Kept because the mistake
> is instructive: it read a *nondeterministic* channel as evidence of state-following. Its measured
> nulls (`--no_fabric`, `--playback_step`, transform push) and its source finding
> (`IsaacRtxRenderer.update_transforms` is `pass`) do stand -- those are carried forward below.
> [!WARNING]
> **This entry's conclusion is superseded -- see "the RGB witness was unsound" below.** The RGB
> witness passed a *bit-identity* test, which RTX sampling noise defeats. Measured afterwards, this
> very run's frames move 0.42 grey levels against the recording's 2.72, so RGB was frozen too and
> all three consequences below are withdrawn. Kept in place because the three measured nulls it
> established are still valid and valuable.

`w1_rgbwitness` (`--no_depth`, so the guard falls back to RGB) **rendered all 12 frames and the guard
never fired**. Consecutive RGB frames differ. Combined with the three depth-witness arms, all of
which fired on frame 1:

| Witness | Consecutive frames | Verdict |
| :--- | :--- | :--- |
| **RGB** | **differ** | follows the written state |
| **depth** (`distance_to_image_plane`) | **bit-identical**, `depth_inf_fraction` 0.0 | stale, with real-valued contents |

**§2.1's diagnosis is wrong and is retracted.** The render is not frozen, the transforms do reach
RTX, and `reset_to` is visible in the image. The defect is **confined to the depth annotator**, which
returns real but unrefreshed values. That is why no flush mechanism moved it: the gate, the dedupe,
`use_fabric`, and a genuine `sim.step()` all operate on the transform/USD path, and the transform/USD
path was never the broken one.

**Three consequences, two of them good news.**

1. **The corpus RGB is usable.** Nothing about RGB playback needs repairing, which unblocks anything
   scored on images rather than on geometry.
2. **§2.1's contamination claim is refuted.** It held that
   `calibrate_corpus_camera.py`'s fitted offset "is likely an artifact" and that the camera-pitch
   investigation is "downstream of the same bug". That script fits on **RGB only** -- `_render_rgb`
   against `_recorded_rgb` (`:211-216`, `:281-282`, `:395`) -- and RGB was never frozen. Its search
   was responsive to scene state throughout, so its offset stands until shown otherwise and **W4
   loses its motivation**. Demote it.
3. **The GT-depth conclusion survives, with a different cause.** Rendered depth is still invalid, so
   §2.5b's retraction, and the W5/G1/G2 gates that rest on GT depth, remain correct as written -- but
   the repair is "fix the depth annotator refresh", not "re-plumb state playback". This is a far
   smaller and better-scoped job than Risk 1 feared, and Risk 1's `sim.step()` remedy is closed
   (measured, no effect).

**What is now unexplained.** RGB `mean_abs_diff` against the recording is 52-54 across every arm
including this one (54.49 here). The freeze was the standing explanation for that gap and it is gone.
**Risk 4 is now the leading candidate**: `galileo_locomanip` textures 404 on both buckets and 61 MDL
shader nodes fail to resolve per run, which would make the rerender differ from the recording
everywhere without any per-frame staleness. That is a materials/asset problem, not a playback
problem, and it should be the next thing tested -- it is also cheap, since §2.1 already priced the
same-geometry material swap at a median 52.7 cm of teacher-prediction movement.

**W1 restated.** Not "unfreeze the render" but: **find why `distance_to_image_plane` does not refresh
while `rgb` does.** Both come from the same camera and the same
`observation_manager.compute()["camera_obs"]` call, so the divergence is inside the annotator or its
caching, not in the scene or the transform pipeline. Start by comparing the two annotators' update
paths for that camera; the `render_frame` docstring's assumptions no longer apply.

**Code landed** (`isaaclab_arena/scripts/imitation_learning/rerender_demos.py`): the
`assert_render_not_frozen` / `state_max_abs_delta` guard, which is what produced every result above
and should stay -- it converts this class of bug from a silently wrong corpus into a hard failure.
`--no_fabric` and `--playback_step` are retained as measured-null diagnostics, both **off by
default**; the no-op transform-push edit was reverted, with the reason recorded in `render_frame`.

### 2026-09-06 -- the RGB witness was unsound; the render is frozen on both channels

**`assert_render_not_frozen` tests `np.array_equal`.** Bit-identity is a valid freeze test only for a
**deterministic** channel. `distance_to_image_plane` is deterministic, so a frozen scene makes it
bit-identical and the guard fires. RTX colour carries sampling noise, so a frozen scene still yields
distinct frames and the guard passes. The RGB pass measured renderer determinism, not state-following.

Measured directly, mean absolute difference between consecutive frames, greyscale:

| Sequence | consecutive mean | max | bit-identical pairs |
| :--- | ---: | ---: | ---: |
| `w1_rgbwitness` (the run that "passed") | **0.4238** | 1.0051 | **0** |
| `probe_set` rerender | 0.177 | 0.962 | 0 |
| **the recording itself** | **2.722** | 15.879 | -- |

The render moves at **16% of the recording's motion** in its own best case, over frames whose recorded
joint positions move up to 1.1034 rad. So **§2.1's conclusion stands: the render is frozen, on both
channels.** All three consequences of the superseded entry are withdrawn -- the corpus RGB is **not**
usable, `calibrate_corpus_camera.py`'s contamination concern **stands** (it fits rendered RGB against
recorded RGB, and the rendered side is frozen), and the repair is **not** confined to the depth
annotator. The `mean_abs_diff` of 52-54 that the entry called "unexplained" is not a separate mystery:
it is the freeze, which was the standing explanation before it was discarded.

**What that pass did establish, and it is worth keeping.** Three remedies are now measured nulls --
`--no_fabric`, a genuine `--playback_step`, and the transform push -- which closes Risk 1's own
proposed remedy by experiment. And one source fact corrects §2.1's *mechanism*:
`IsaacRtxRenderer.update_transforms` is literally `pass`, documented "No-op for Isaac RTX - uses USD
scene directly". So the `lazy_sensor_update` gate and the `RenderContext` dedupe that §2.1 named
**cannot be the cause** -- they gate a call that does nothing on this renderer. §2.1 was right that
the render is frozen and right that physics is fine, and **wrong about which gate does it**. The
transforms reach RTX through USD directly, and every mechanism tried so far operates elsewhere.

**Guard strengthened.** `assert_render_tracks_recording` adds the magnitude test bit-identity cannot
do: the render must reproduce at least a floor share (default 20%) of the recording's own
frame-to-frame motion. On the numbers above it fires at 0.156. Bit-identity is kept as the
deterministic-channel test, with the limitation documented in both docstrings.

**W1 restated, again.** Not "why does depth not refresh while RGB does" -- both are frozen. The
question is why body transforms do not reach the RTX USD scene when `sim.forward()` runs, given that
Fabric-off and a real physics step both fail to fix it. Next cheapest probes: whether the camera prim
itself moves (camera pose reaches RTX by direct USD writes, so it should), and whether a
`scene.reset()` before the write, as `ManagerBasedEnv.reset_to` does and `render_frame` omits, is what
actually unblocks it.

### 2026-09-06 -- determinism measurement, and what it adds to the entry above

The entry above was reached independently by another pass and its conclusion is the correct one; this
entry keeps only what is **additive** and drops the duplicate narrative.

**The sharpest number.** `--determinism_probe` renders one state twice with no write in between:

| Channel | same-state max abs diff | same-state **mean** abs diff | identical? |
| :--- | ---: | ---: | :--- |
| RGB | **42.0**, then **60.0** on a repeat | **0.877** | **No** |
| depth | **0.0** | 0.0 | **Yes** |

Put beside the entry above: same-state RGB noise is **0.877**, while `w1_rgbwitness`'s
consecutive-frame RGB difference was **0.4238**. **The noise exceeds the signal by ~2x**, so the RGB
"motion" in the run that "passed" is not merely small relative to the recording's 2.722 -- it is
*below RGB's own noise floor*. That closes the question rather than bounding it, and it is why
bit-identity can never fire on this channel: RGB is never bit-identical to anything, frozen or not.

**Confirmed with no simulator.** Every historical arm's saved `depth/*.npz` has all consecutive frames
bit-identical -- `regression`, `smoke_pitch0`, `smoke_sceneupdate`, `smoke_validated`. The freeze is
long-standing, not introduced by any recent change.

**A consequence for gate design, and a retraction of my own inference.** `rgb_fidelity.mean_abs_diff`
inherits that 0.877 noise floor. The five arms span 52.27-54.49 -- a spread of 2.2 on single episodes,
only ~2.5x the floor. So **arm-to-arm comparisons at 1-2 point granularity are unreliable**, and
earlier in this log I read `smoke_sceneupdate` 54.47 against `regression` 53.40 as "no better, exactly
as §2.1 predicts". A 1.07 difference against a 0.88 floor supports no such conclusion; withdrawn.
**G2/G3 should state a minimum detectable difference and use repeats plus multiple episodes**, not
single-run deltas.

**Code note.** `auto` now uses depth for bit-identity and prints a note when depth is off explaining
that the *motion* guard still covers the run -- an earlier version of that message wrongly said the
run was "unverified", which understated `assert_render_tracks_recording`.

### 2026-09-06 -- the motion guard was itself defeated by the noise floor

The determinism measurement above invalidates the first version of
`assert_render_tracks_recording` as committed in `7c47c2503`. It required the render to move at least
20% of the recording's motion: `0.2 x 2.722 = 0.544`, against a measured same-state noise floor of
**0.877**. **Noise alone cleared the threshold**, so a completely frozen render would have passed
in-process. It fired only on h264-decoded frames, where codec smoothing understates motion to
0.4238 -- an accident of the measurement path, not a working test.

Two further flaws in that formulation, both false-positive risks rather than false negatives:
matching the recording's *magnitude* is not required for correctness, because fallback materials
legitimately reduce apparent motion; and on a genuinely static episode segment the recording's own
motion is small while a fixed noise-derived threshold is not, so it would fail a correct render.

**Corrected invariant: the render must move more than its own noise, and the test is skipped when the
recording moved no more than the noise.** `measure_rgb_noise_floor` renders one unchanged state twice
at the start of each episode -- two extra renders -- and the guard requires
`rendered_motion >= noise_margin x noise_floor` (default 2x), returning early when
`recorded_motion <= noise_margin x noise_floor` because that frame pair cannot discriminate.
`min_motion_ratio` survives as an optional extra floor, defaulted to 0.

Behaviour on the measured numbers:

| Case | rendered | recorded | Result |
| :--- | ---: | ---: | :--- |
| frozen, noise only | 0.877 | 2.722 | **fires** |
| tracking, duller materials | 1.900 | 2.722 | passes |
| genuinely static segment | 0.880 | 1.100 | skipped, cannot discriminate |

**The lesson, for the gates as much as the guard**: on a stochastic channel, no freeze or
difference test means anything until its own noise floor is measured. That applies directly to
G2 and G3, which per the entry above need a stated minimum detectable difference and repeats rather
than single-run deltas.

### 2026-09-06 -- the repo already knew, and the graph's own prior is now falsified

`isaaclab_arena/agentic_environment_generation/policy_capability_graph.py` carries all three pieces
of this investigation, verified verbatim:

| Entry | Line | Content |
| :--- | ---: | :--- |
| `harness_stale_observation` (prior 0.08) | 451 | "with fabric enabled, poses written through the PhysX tensor API only reach the renderer during a physics step, and `reset()` never steps physics ... `num_rerenders_on_reset` is the documented remedy and **is reported not to fix it** ... **Diagnose in pixel space, not from success rates.**" |
| `stale_frame_assertion` (cost 0.05) | 606 | metric `reset_frame_prev_vs_self_distance_ratio` -- "Fresh frames give `d_prev >> d_self`; stale frames invert that." |
| `force_physics_step_before_sensor_read` (**efficacy 0.9**) | 851 | "Step physics once (or otherwise flush the fabric transform buffer) between reset and the first camera read." |

So "diagnose in pixel space" was written down before this session re-derived it over five simulator
runs, and `stale_frame_assertion` is the instrument the `--determinism_probe` rebuilt badly. Note
*why* the graph's version is better: a **ratio** of `d_prev` to `d_self` is scale-free, so it needs no
absolute threshold and is immune to the noise-floor trap that defeated two successive versions of our
own guard. The lesson we paid for twice was already encoded in the metric's shape.

**Two things keep this from being a pure indictment.** The graph's failure mode is about the *first*
observation after a reset; ours is a persistent freeze across every frame of a playback loop. Same
suspected root cause, different symptom, so the match is close but not exact.

**And the graph is wrong where it is most confident.** `--playback_step` *is*
`force_physics_step_before_sensor_read` -- a genuine `sim.step()` between the write and the read. It
was measured and it **failed**. A remediation carrying `expected_efficacy=0.9` measures **0.0** on
this case, and the stated mechanism ("only reach the renderer during a physics step") is therefore
incomplete: we stepped physics and the render stayed frozen. That, plus `--no_fabric` also failing,
means the fabric-ordering story does not explain this instance.

**The structural finding.** This session produced exactly the evidence the graph needs and there is no
path for it to arrive. `rerender_demos.py` writes `rerender_summary.json`; the self-healing path reads
`eval_telemetry.ttl`. Nothing routes a harness symptom into `policy_capability_graph.py`, and no
measurement can correct an efficacy prior, so `force_physics_step_before_sensor_read` will still read
0.9 tomorrow. The graph's knowledge also lives as prose inside `description=` strings, so a symptom
grep -- which is how anyone actually starts -- lands in Isaac Lab's source rather than in our own
recorded diagnosis.

**Proposed, not done** (these are design changes on core package code, so they need a decision):
tag the symptom surfaces with `mode_id`s so a grep lands in the graph; give the graph a
`modes_for_symptom()` / `rank_diagnostics(capabilities)` entry point and name it in `AGENTS.md` as the
first stop for a harness symptom; emit the TTL the oracle already reads from `rerender_summary.json`;
and record measured efficacy against `technique_id` so a 0.9 prior drops on contact with evidence.
The immediate one-line version is to correct `force_physics_step_before_sensor_read`'s prior and note
the measurement beside it.
