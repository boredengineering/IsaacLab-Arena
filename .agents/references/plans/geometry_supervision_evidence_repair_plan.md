# Geometry Supervision, Take 2: Repairing the Evidence Base and Re-choosing the Teacher

> [!IMPORTANT]
> **Status**: PLAN, 2026-09-05. Supersedes §W5, §W7 (gates G1/G2) and the teacher argument in §2 of
> [`spatial_forcing_da3_metric_alignment_plan.md`](spatial_forcing_da3_metric_alignment_plan.md).
> That plan's method (§3), student-side wiring (§4), licence and fetch tables (§8) stand and are not
> restated here. Its implementation W1-W4 is landed and pushed --
> `boredengineering/Isaac-GR00T` at `dev/arena_v0.3.0-compat` (`d78207d`), 24 tests pass with 0
> skips. This plan exists because three of the old plan's load-bearing numbers were measured on
> 2026-09-05 and **two of them were wrong**: the ground-truth depth it gates on was never valid, and
> the quantity G1 tests is one the alignment loss cannot see.

## 1. Why a new plan rather than an edit

The old plan is sound about *how* to align. It is wrong about *what evidence exists* and *why this
teacher*. Both errors point the same way: work was about to be spent training arms whose gates could
not have passed or failed meaningfully. Three findings, each independently verified:

1. **No usable ground-truth depth exists.** The rerender never applied the recorded simulator state,
   so every depth frame we have is one image of the environment's default pose.
2. **The depth-readout baseline was not a held-out measurement.** Train and test targets were
   identical, so `R² 0.997` measures memorisation of a single constant image.
3. **The alignment loss is scale-invariant**, so `DA3METRIC-LARGE`'s metric-ness -- the entire reason
   §2 selected it -- cannot transfer through the objective, and its metric error cannot contaminate
   the student either. G1 as written tests a quantity with no path into the loss.

## 2. What was measured

### 2.1 The rerender never applied the recorded state

`eval_output/rerender/probe_set`, the only ground-truth depth in the repo:

| Check | Result |
| :--- | :--- |
| Unique depth images across both episodes (120 frames) | **1** |
| `ep0` all 60 frames identical | `True` |
| `ep0[0]` vs `ep1[0]` identical | `True` |
| Recorded joint motion, `demo_0` first 60 frames | **1.1034 rad** max abs deviation from frame 0 |
| Recorded apple pose | present as `rigid_object/apple_01_objaverse_robolab`, world `(0.5785, 0.27, -0.0104)` |
| Apple visible in the rerendered frames | **no** |
| Arm pose vs the dataset frames at matching index | raised at centre, where the dataset has arms at the sides |
| `rgb_psnr_db` recorded by the run itself | **9.66 / 9.43 dB** |

The recording moves by over a radian and the render does not move at all, so this is not a static
corpus and not a stale depth annotator: **`env.scene.reset_to(...)` is not reaching the render.**
One cause explains every symptom -- the frames show the environment's own default pose, which is why
the arms are up, the apple is elsewhere, the depth is constant, and the fidelity check reports
9.66 dB. The earlier reading of "stale depth buffer" was wrong: RGB's 8.1 mean-abs frame-to-frame
difference is h264 noise at roughly 1 KB/frame, not motion.

> [!CAUTION]
> `rerender_demos.py` already ships `--validate_states`, whose help text is exactly
> *"separates 'the recording did not apply' from 'the scene renders the recorded state
> differently'"*. It is opt-in, and the probe-set run did not pass it -- the summary JSON carries no
> playback-error fields. A validation hook that exists and is not run is worth nothing. It must be
> **on by default** for any run whose output feeds a gate.

### 2.2 The depth-readout baseline was not a held-out measurement

`probe_depth_readout.py:278-279` reads RGB *and* depth from the rerender directory, then trains a
ridge probe on episode 0 and tests on episode 1. Given §2.1, both episodes' depth target is the same
constant image, so the reported **1.33 cm median / R² 0.997** describes a probe reproducing one fixed
depth map with train and test targets identical. It is not evidence the embedding reads depth. The
old plan cited it as the reason the *target-scene* split is the informative one; the corpus number is
weaker than that argument assumed, not merely near-duplicate.

### 2.3 The teacher's metric scale is wrong, and the loss cannot see it

Full `DA3METRIC-LARGE` net (backbone + DPT head) against the one valid GT image, using DA3's own
convention -- `apply_metric_scaling` in `utils/alignment.py` is `depth * focal / 300`, matching the
old plan's formula. Camera focal **458.12 px** (`focal_length=15`, Isaac Lab default
`horizontal_aperture=20.955`, width 640). GT spans 0.231-4.406 m.

| Input RGB | Region | Raw median err | `pred/gt` | After one global scale | Pearson r |
| :--- | :--- | ---: | ---: | ---: | ---: |
| dataset (what training feeds) | tabletop 0.35-0.85 m | **24.6 cm** | 1.48x | **1.55 cm** | +0.57 |
| dataset | whole frame | 25.6 cm | 1.49x | 11.5 cm | +0.69 |
| rerendered | tabletop | 80.1 cm | 2.56x | 1.93 cm | +0.93 |
| rerendered | whole frame | 76.9 cm | 2.57x | 12.9 cm | +0.63 |

So the teacher puts a table 0.5 m away at roughly 0.74 m: **24.6 cm of absolute error, 3.5x the 7 cm
gap.** Its relative structure survives -- one global scale brings the tabletop residual to 1.55 cm.
DA3 concedes the point itself: `model/da3.py:408` least-squares-fits a scale whenever ground-truth
metric depth is available.

And the objective cannot see any of it. `geometry_conditioning.py` computes
`(F.normalize(projected, dim=-1) * F.normalize(target, dim=-1)).sum(-1)`, so rescaling the teacher's
features leaves the loss bit-identical. Two consequences, and they cut in both directions:

- The 1.48x error **cannot contaminate** the student. G1's stated failure condition is unreachable.
- Absolute metric scale **cannot be taught** through cosine alignment either, by any teacher. Spatial
  Forcing donates *relative geometric structure*; the absolute mapping must come from the action
  supervision.

## 3. The re-derived question

The old plan's thesis was "the policy lacks metric range, so supervise it with a metric teacher".
Half of that does not hold. The defensible thesis is narrower:

> Cosine alignment to a frozen geometry teacher can improve the **relative** geometric content of the
> backbone's image tokens. Whether that reduces a systematic **absolute** range error is an empirical
> question, and the mechanism is the action head exploiting better relative features -- not inherited
> metric scale.

That reorders the teacher axes. Metric-ness buys nothing through this loss. What plausibly matters is
relative depth fidelity and multi-view aggregation -- and on the properly paired frames the *any-view*
family looks stronger on exactly that (`r = +0.93` post-scale, against `+0.57`), though those two rows
are not comparable yet because they are different RGB inputs. **W3 is the experiment that settles it,
and it is cheap.** It is also possible the answer is that no teacher helps, in which case §6's fork
applies rather than a longer sweep.

## 4. Work items

### W1 -- Repair the state playback
Find why `env.scene.reset_to(frame_state, env_ids, is_relative=True)` does not change the render, in
`isaaclab_arena/scripts/imitation_learning/rerender_demos.py:345`. Candidates, cheapest first:
`frame_state_for_scene` returning frame-independent state; `is_relative=True` mismatching the
recording's frame; the write landing on a different env index than the one rendered; the refresh
protocol in `render_frame` (`sim.forward` -> `scene.update` -> `sim.render` xN ->
`observation_manager.compute`) not covering rigid-object transforms.

Make `--validate_states` **default-on**, with an explicit `--no_validate_states` escape, and write
per-frame playback error into the summary JSON unconditionally. Add a guard that **fails the run**
when consecutive depth frames are bit-identical while the recorded state is not -- that single check
would have caught this before any of it fed a gate.

Needs Isaac Sim, so it needs the Arena container, currently `Exited (137)` (SIGKILL/OOM).

### W2 -- Re-render an evidence set that can answer a gate
Once W1 passes validation: re-render the corpus scene **with the apple in view**, and the
**maple-table target scene**, which has never existed. Store GT depth plus the per-frame camera
extrinsics and intrinsics -- the current summary records `offset_pos`/`offset_rot` and resolution but
no intrinsics, which is why the focal had to be reconstructed from the embodiment config in §2.3.
Minimum: enough episodes that a held-out split is a real split, which given §2.2 means episodes whose
depth targets actually differ.

### W3 -- Re-measure the teachers on relative fidelity, and pick the primary  *(new G1)*
On paired GT from W2, for each of `DA3METRIC-LARGE`, `DA3-BASE`, `DA3MONO-LARGE` and
`Depth-Anything-V2-Small`, report **post-scale** median error, Pearson r and rank correlation, at the
**apple's projected pixels** and over the tabletop band, on the RGB that training actually feeds.
Absolute metric error is recorded for the log but is explicitly **not** a selection criterion, per
§2.3. Pick the primary teacher on relative fidelity. All four load and emit the 8x11 student grid
today -- widths 1024, 1536, 1024, 384 -- so this is measurement only, no new plumbing.

### W4 -- An honest depth-readout baseline  *(new G2)*
Re-run `probe_depth_readout.py` on W2's set with a split whose test targets differ from its train
targets, and assert that at load time rather than trusting the directory. Report against the target
scene, and report the constant-predictor control alongside, as the current script already does.

### W5 -- Training environment: the `/datasets` mount
`gr00t-server` mounts `/models`, the HF cache, `/workspace/gr00t`, `/workspace/pretrained_ckpts` and
`/workspaces/isaaclab_arena` -- no `/datasets`, and `docker/run_gr00t_server.sh` contains no
reference to it. `finetune_n17_geometry.sh:35` defaults there and the preflight at `:115` exits.
The four-line diff is in the old plan's §W6a. `docker/` is **"ask first"**, so this is a draft PR.

### W6 -- C6, augmentation replay
Unstarted. Feed the teacher the student's geometric crop via `A.ReplayCompose` and drop colour ops,
replacing the current stand-in that drops saturation and hue globally for geometry arms. Worth doing
before the sweeps rather than after, since it confounds arm comparison.

### W7 -- Arms, reduced
Run the primary arm chosen by W3, `baseline`, and `align_cheap` as the cheap-teacher control. The
old plan's five-arm matrix plus site and coefficient sweeps is deferred until one arm has moved a
gate: §2.3 removes the metric-vs-relative contrast that justified half of it.

## 5. Gates

**G1 (replaces teacher-competence).** A teacher's post-scale relative error at the apple's pixels is
materially below 7 cm on the frames training feeds. Fails only if *no* teacher clears it, which would
mean no available teacher knows the geometry we lack.

**G2 (replaces depth readout).** On W2's target scene, with a genuinely held-out split, the probe's
error drops materially against the baseline policy's embeddings. The split assertion is part of the
gate.

**G3 (unchanged).** Hand-to-apple vertical error at closest horizontal approach, from `ReachTracer`.
Baseline to beat: **+0.1286 m at chunk 16, ~0.0795 m at chunk 8**, ~7 cm the stated floor.

## 6. Risks and the falsification fork

1. **W1 may not be a small bug.** If the state write cannot be made to reach the render, there is no
   ground-truth depth for this corpus at all, and G1/G2 must be replaced by something that needs no
   GT -- or the plan stops.
2. **Absolute-scale error may be the whole 7 cm.** If it is, §2.3 says cosine alignment cannot fix it
   regardless of teacher, and the live options become a depth input at train *and* inference, demos
   with genuine spatial variation, or an explicit range calibration. This is the fork to take
   seriously, not a footnote.
3. **The corpus has zero spatial variation** (`APPLE_SPAWN_XY_RANGE_M = 0.0`), so there is little for
   a spatial objective to bind to. Unchanged from the old plan's Risk 3, and W2's target scene is
   what detects it.
4. **Broken background materials.** `galileo_locomanip` textures 404 on both buckets; 61 MDL shader
   nodes fail to resolve per run. §2.3 now prices this: the same geometry under fallback versus
   dataset materials moves the teacher's prediction by a **median 52.7 cm**, so the teacher is highly
   sensitive to it, and any measurement must be made on the RGB training actually feeds.
5. **The truncation risk** (old plan §4.1) is unchanged: effective depth 0.62 against upstream's best
   at 0.75.

## 7. What carries over unchanged

The old plan's §3 (method, projector, positional embedding, teacher hygiene), §4 (student-side
alignment site, `align_backbone_layer_from_site`, `request_hidden_layers`), §8 (licences verified
against the HF API, fetch commands, checkpoint SHAs), and the landed implementation: allowlist,
probed feature width, masked `1 - cos` loss, per-arm teacher selection in the launcher, and the DA3
backbone-strict/head-tolerant load that unblocked `align_anyview` (`d78207d`).

Also carried over, and still true: `geometry_align_loss_coeff` and
`geometry_align_position_embedding_std` are unpublished upstream and remain knobs to sweep, not
defaults to cite. Layer 23 of `DA3METRIC-LARGE` has per-channel std 0.718, against which the default
PE std of 0.02 is 2.8%.

## 8. Open decisions

1. **W5's mount** -- approve the `docker/run_gr00t_server.sh` diff, or accept the one-off of staging
   the dataset under `~/models` while the PR is open.
2. **Whether to keep a metric teacher as primary** once W3 reports, given that metric-ness has no
   path through the loss.
3. **How much of §6.2 to pre-commit to** -- if alignment cannot reach an absolute error, is a depth
   input at inference acceptable for this robot, or is that off the table as §1 of the old plan
   assumed?
