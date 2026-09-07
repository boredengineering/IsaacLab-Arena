# Spatial Forcing with DA3METRIC-LARGE: Giving the G1 Policy Metric Range

> [!NOTE]
> **Role, 2026-09-06.** The build is now directed by
> [`da3_spatial_forcing_pipeline_plan.md`](da3_spatial_forcing_pipeline_plan.md). This document
> remains the **method reference** -- §3's upstream-faithful description, §4's N1.7 porting
> analysis and §8's licence work are what the implementation was built from and still hold.
> Five updates from running it for the first time:
>
> 1. **`align_loss_coeff` is no longer unknown.** §3.5's WARNING is retracted:
>    `openvla-SF/vla-scripts/finetune_align.py` defines `align_loss_coeff: float = 0.5`, which is
>    exactly Arena's default, so it is upstream's own value rather than a guess. Still worth
>    sweeping -- upstream tuned it against OpenVLA's L1 action loss, not N1.7's flow-matching head
>    -- but not as an unknown. Do not conflate with VEGA's `lambda = 0.1` (arXiv:2605.10485).
> 2. **§3.4 is confirmed in its reasoning and only half-implemented.** The teacher does see the
>    student's *geometric* crop: the processor emits `geometry_images` from `stacked_images`, which
>    is post-augmentation, so positional alignment is meaningful as §3.4 requires. But the second
>    half -- replaying the crop while **dropping colour ops** -- was never built. The teacher
>    currently receives brightness and contrast jitter; the launcher only drops saturation and hue,
>    and does so for the whole arm rather than for the teacher alone. Open item, not a blocker.
> 3. **A consequence of (2) worth recording:** because the crop is stochastic per sample, a
>    precomputed teacher-feature cache is **unsound** under this recipe -- cached features would sit
>    under a different crop than the student's. This is why the pipeline plan keeps the online
>    teacher as the default and gates `--emit-latents` behind a determinism requirement.
> 4. **W5's metric-error budget must not use render-derived GT.** The ground truth it rests on comes
>    from the simulator render, which W1 of the evidence-repair plan shows is frozen. Superseded by
>    S1b of the pipeline plan: anchor the scale on **known scene geometry** -- the apple's 3.4 cm
>    relief at ~0.5 m, a ratio that survives the scale error -- which needs no ground truth at all.
> 5. **W6 could never have run, and now does.** Measuring the teacher's feature width is a forward
>    pass, and `AutoModel.from_pretrained` builds the policy on the **meta device**, so
>    `probe_feature_dim()` in `Gr00tN1d7.__init__` failed with "Cannot copy out of meta tensor"
>    every time, for both `align` and `mix`. Fixed by probing before construction and carrying the
>    width on the config as `geometry_feature_dim`. Two further defects surfaced immediately behind
>    it: `align_loss` was computed and never logged, and the frozen teacher's 342 tensors were being
>    written into every checkpoint. First working run: align 0.9916 -> 0.3969 -> 0.2564 with the
>    action loss falling alongside.

> [!CAUTION]
> **The premise is refuted, and the knowledge graph said so first (2026-09-07).**
> This plan exists to close a vertical range gap with a metric depth teacher. Three measurements
> now say the vertical axis is not the binding constraint, and Arena's own
> `policy_capability_graph.py` ranked the diagnostics that would have shown it at **cost 0.05,
> no rollout, no GPU** -- before any of the work in this plan was done.
>
> 1. **The reachability oracle fires categorically.** Robot base `(0.25, 0.08, 0.0)`, apple at
>    `(0.5785, 0.27, -0.0079)`. Horizontal distance 0.379 m is fine (band 0.25-0.95), but
>    pelvis-relative `rel_z = -0.758 m` against a band of `[-0.35, +0.45]`. The plate is worse at
>    -0.775 m. `KinematicManifold`'s docstring: such a mismatch is **categorical -- "no
>    policy-config patch closes it."**
> 2. **The corpus never crouches.** `teleop.base_height_command` spans **0.72-1.00 m** across all
>    208 episodes / 35 066 frames, and `navigate_command` and `torso_orientation_rpy_command` are
>    identically zero. Satisfying the band would need a pelvis at <= 0.342 m, a 0.66 m crouch that
>    never occurs. So the violation is not an artefact of an assumed standing pose.
> 3. **`ReachTracer` never measured one frame.** It picks the nearest matching body each step and
>    across the three arms tracked **six different links** -- `left_hand_middle_1_link` (~3.5 k
>    rows), `thumb_2`, `middle_0`, `index_1`, `palm`, `wrist_yaw`. Every historical reach figure
>    ("12.9 cm too high", "+0.1286 m at chunk 16", "~0.0795 m at chunk 8", "1.6 cm lateral /
>    4.95 cm vertical") is therefore irreproducible **by construction**, which is exactly what
>    happened when each was re-measured.
>
> **Two caveats, stated so this is not over-read.** The oracle's `[-0.35, +0.45]` band is a
> *heuristic* in a pure-math preflight, not a measured G1 envelope; and the 208 demos carry
> `next.reward = 1.0` each, so the task is presumably feasible -- which argues the band is too
> strict for a WBC that pitches the torso. Separately, the demo-side figure below uses
> `observation.eef_pose` (a wrist frame) while the traces use finger links; **those frames are not
> comparable** and an apples-to-apples measurement is still owed.
>
> What *is* firm: the demos' `eef_pose` never descends below **z = +0.0721** while the apple sits
> at **-0.0079**, and **0 of 208** episodes bring it within the apple's 3.4 cm radius in height.
>
> **Consequence for this plan.** §1's "accurate bearing, wrong range" framing is not supported;
> the base policy is over the apple in only 4/20 episodes. Spatial Forcing was aimed at an axis
> that is not the binding constraint, which is why S4 came out null and why the null was
> overdetermined. Do not resume geometry-teacher work from this document until the reachability
> question is settled against a *measured* G1 reach envelope and `ReachTracer` is pinned to a
> single, named frame.

> [!IMPORTANT]
> **Status**: PARTLY SUPERSEDED, 2026-09-05. §W5, §W7 (gates G1/G2) and §2's teacher argument
> are replaced by [`geometry_supervision_evidence_repair_plan.md`](geometry_supervision_evidence_repair_plan.md):
> the ground-truth depth those gates rest on was never valid, and the alignment loss is
> scale-invariant, so the metric-ness that selected this teacher cannot transfer through it.
> §3, §4 and §8 below stand. W1-W4 landed and pushed to
> `boredengineering/Isaac-GR00T` at `dev/arena_v0.3.0-compat` (`d78207d`; the branch's prior tip
> `1979f93` is preserved at `dev/arena_v0.3.0-compat-old`); 24 unit tests pass with 0 skips in the
> `.venv` interpreter that has the DA3 package, and `pre-commit` is clean. `DA3METRIC-LARGE` loads and emits 1024-wide features on the student's 8x11
> grid, verified end to end. C6 is unstarted, W5-W7 unstarted. Three claims in the
> original draft were wrong and are corrected in place: §4.1's truncation depth, W1's dependency
> risk, and W2/§8.4's load path. Originally: PLAN, 2026-09-05. Implements Spatial Forcing ([arXiv:2510.12276](https://arxiv.org/abs/2510.12276),
> ICLR 2026) against an Apache-2.0 geometry teacher, for the failure diagnosed in
> [`g1_monocular_depth_and_camera_pitch_debug.md`](g1_monocular_depth_and_camera_pitch_debug.md).
> Method details below are taken from the **reference implementation**, not the paper prose --
> the two disagree in one place (§3.1), and the code is what reproduces the results.

## 1. Context

The measured failure on `g1_tabletop_apple_to_plate` is **accurate bearing, wrong range**: the hand
lands 1.6 cm from the apple horizontally -- inside its 3.4 cm radius, 5 of 5 episodes -- while
sitting **12.9 cm too high**. That decomposes into ~5 cm of action-chunk staleness, already bought
back by shortening the executed chunk, and **~7 cm of irreducible monocular range error** (§4.5,
§4.7 of the debug record). The policy sees one RGB frame and no depth, so metric range is not
observable and no configuration change can close 7 cm.

Spatial Forcing addresses exactly this: it does not add a depth input, it **supervises the VLM's
intermediate visual embeddings to carry the geometry a frozen 3D model already knows**. Nothing is
needed at inference, which matters because the real robot has no depth sensor.

**Why this teacher.** `DA3METRIC-LARGE` is Apache-2.0, 0.35B, trained exclusively on public academic
datasets, and is a **metric** depth specialist -- metric range being the precise quantity the policy
lacks. It sidesteps the licence wall that rules out VGGT-1B, VGGT-Omega and most Depth-Anything-3
sizes for anything beyond internal research.

## 2. Decisions and their evidence

| Decision | Value | Why |
| :--- | :--- | :--- |
| Method | Spatial Forcing (`align`) | Zero inference cost; no depth sensor at deployment |
| Teacher | `depth-anything/DA3METRIC-LARGE` | Apache-2.0, metric, DINOv2-init ViT-L |
| Teacher features | encoder layer **23**, dim **1024** | `out_layers: [4, 11, 17, 23]`, `cat_token: False`, head `dim_in: 1024` -- the last layer is what its own DPT head consumes, matching SF's "backbone latent before task heads" |
| Student layer | **post-`vl_self_attention`** (default), sweep `backbone_layer_{6,9,12}` | See §4.1 -- shallower than upstream, but by less than first thought |
| Contrast teachers | `DA3-BASE` (any-view), `Depth-Anything-V2-Small` | Isolates *metric* vs *multi-view* vs *cheap*; mirrors SF's own encoder ablation |

> [!CAUTION]
> **`DA3METRIC-LARGE` is monocular, not any-view.** Its config sets `alt_start: -1`,
> `qknorm_start: -1`, `rope_start: -1` -- alternating (cross-frame) attention is **disabled**. It is
> a plain ViT-L. SF's best result used VGGT, whose multi-view aggregation the paper explicitly
> credits for consistency. So this teacher trades away multi-view aggregation to gain metric scale.
> That is the right trade for a 7 cm *range* error, but it is a trade, and `DA3-BASE` (which does
> enable alternating attention) is in the plan specifically to measure what the trade costs.

**Licence hygiene.** Only `DA3-SMALL`, `DA3-BASE`, `DA3METRIC-LARGE` and `DA3MONO-LARGE` are
Apache-2.0. The Giant/Large/Nested series, including every `-1.1` refresh, is CC BY-NC 4.0, and
**several HF cards are mis-tagged `apache-2.0` while the repo table says otherwise**. The repo table
is authoritative. Consequence: no Apache checkpoint received the `-1.1` bug-fix retrain; its stated
benefit was street scenes, irrelevant to a tabletop. The config must carry an **allowlist** so a
non-commercial checkpoint cannot be selected by a typo.

## 3. The method, as implemented upstream

### 3.1 Loss and projector -- code, not prose

The paper describes "batch normalization Γ ... then a two-layer MLP". The reference implementation
(`openpi-SF/src/openpi/models_pytorch/projectors.py`) instead uses an **optional LayerNorm on the
student side** and no BatchNorm:

```python
self.fc1 = nn.Linear(llm_dim, 2 * vggt_dim, bias=True)
self.fc2 = nn.Linear(2 * vggt_dim, 2 * vggt_dim, bias=True)
self.act_fn1 = nn.GELU()
self.vlm_norm = nn.LayerNorm(llm_dim) if use_vlm_norm else None
# xavier_uniform on every Linear, bias zeroed
```

and the loss, per sample, masked to valid image tokens:

```python
_vision = F.normalize(_vision, dim=-1)
_vggt   = F.normalize(_vggt,   dim=-1)
align_loss += 1 - mean_flat((_vision * _vggt)[_mask].sum(dim=-1))
align_loss /= bsz
```

Total objective: `loss = action_loss + config.align_loss_coeff * align_loss`.

Note the projector's **output width equals the target width**, and the hidden width is the same. The
`2 * vggt_dim` in the code is because VGGT's aggregated tokens are twice its configured `vggt_dim`;
with `DA3METRIC-LARGE` (`cat_token: False`) the target is a flat **1024**, so the projector must be
`Linear(2048 -> 1024) -> GELU -> Linear(1024 -> 1024)`. **Measure the target width at load rather
than hardcoding it** -- the doubling is a VGGT quirk, not a rule.

### 3.2 The positional embedding is load-bearing

A positional embedding is added to the **target**, not the student tokens, "to ensure that the
supervised tokens preserve the critical position order within the auto-regressive process". SF's
own ablation:

| Target | LIBERO-Long | Avg |
| :--- | ---: | ---: |
| VGGT | **94.2** | **96.9** |
| VGGT **without** PE | 84.4 | 94.7 |

Ten points on Long for one term. It is not optional.

### 3.3 Teacher hygiene

The teacher runs under `torch.no_grad()` with bf16 autocast, with its prediction heads disabled
(`feature_only=True`). Patch tokens only -- `agg_vggt_hidden[:, :, patch_start_idx:, :]` drops the
camera and register tokens. Features are then resampled to the student's token grid by
`custom_pooling`, over a **rectangular** grid (`patch_h, patch_w = H // patch_size, W // patch_size`).

### 3.4 Teacher sees un-augmented images

SF feeds the teacher `img_resize_wo_aug`. This plan **diverges deliberately**: feed the teacher the
same *geometric* crop as the student but skip *colour* jitter. Positional alignment is only
meaningful if both see the same crop, and Arena's pipeline does apply a random crop
(`crop_fraction: 0.95`). `A.ReplayCompose` records the geometric parameters
(`image_augmentations.py:26-95`), so the crop can be replayed onto the teacher's input while colour
ops are dropped. Note as a divergence from upstream and check it in the smoke test.

### 3.5 What SF reports

- **LIBERO avg 98.5** vs OpenVLA-OFT 97.1; best among methods needing no extra sensor.
- **3.8x faster training** to matched success (2K→72.7, 5K→87.5, 20K→93.7, 50K→96.5, 150K→96.9).
- **5.9x better data efficiency** (1%→42.3, 5%→75.8, 100%→96.9).
- Encoder ablation: base 92.7, SigLIP 94.0, DINOv2 94.1, VGGT-no-PE 94.7, **VGGT 96.9**. Every
  target beats base, so alignment helps even without a 3D teacher -- but the 3D teacher is worth
  ~2.8 points over DINOv2.
- Real robot: **+47.5 points** on stack-glass-cups from 40 demos.

> [!WARNING]
> **RETRACTED 2026-09-06.** This block said α "is never given a number" and that Arena's `0.5` was
> a guess. The paper body indeed omits it -- Appendix A is titled "Weight Factor" and the value is
> not recoverable from the HTML -- but the **reference implementation supplies it**:
> `openvla-SF/vla-scripts/finetune_align.py` sets `align_loss_coeff: float = 0.5`. Arena's default
> is therefore upstream's, not an invention. Sweep it because the transfer is uncertain (OpenVLA's
> L1 action loss vs N1.7's flow matching), not because the value is unknown.

## 4. Porting to GR00T N1.7

### 4.1 The layer-depth problem -- smaller than the first draft claimed

SF aligns **layer 24 of 32** in Prismatic (0.75 depth), and its layer ablation is non-monotonic:

| Layer (of 32) | Avg |
| ---: | ---: |
| 1 | 94.6 |
| 8 | 95.7 |
| 16 | 93.8 |
| **24** | **96.9** |
| 32 | 94.8 |

> [!IMPORTANT]
> **Corrected 2026-09-05, from the checkpoints rather than the dataclass defaults.** An earlier
> draft of this section read `select_layer: int = 12` out of `configs/model/gr00t_n1d7.py:47` and
> concluded the deepest reachable point was 12/28 = 0.43 depth. **No shipped checkpoint uses that
> default.** Verified in the `config.json` of `nvidia/GR00T-N1.7-3B`,
> `nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace`, and this comparison's own base model
> `gn1x_tuned_static_apple` -- all three carry:
>
> - `select_layer = 16` -> truncation at **16/28 = 0.57 depth**, not 0.43
> - `use_vlln = True` -> a real LayerNorm above the truncation
> - `vl_self_attention_cfg = {num_layers: 4, num_attention_heads: 32, attention_head_dim: 64, dropout: 0.2}`
>   -> a genuine **four-layer** self-attention transformer above it, not the `nn.Identity()` the
>   dataclass default would give
>
> Cosmos-Reason2-2B is confirmed at 28 text layers, hidden 2048.

That changes the risk materially. `vlln` + `vl_self_attention` live inside `Gr00tN1d7ActionHead`
(`gr00t_n1d7.py:84-92`, applied in `process_backbone_output`), so aligning above them puts the
supervision at an effective **20 layers** rather than 16 -- 0.62 of a notional 32, against upstream's
best at 0.75 and well clear of the 0.5 ratio that scored worst. Shallow, still, but not the
worst-case point the draft feared.

> [!CAUTION]
> **The site was already right, by accident.** `process_backbone_output` *replaces*
> `backbone_outputs["backbone_features"]` in place with its normalised, self-attended output, and
> the align block read that entry **after** `self.action_head(...)` had run. So the implementation
> was silently supervising post-`vl_self_attention` -- the correct site -- purely as an artifact of
> statement order. Moving the align block three lines earlier would have shifted the supervision
> four transformer layers shallower with nothing in the logs to show it. This is now an explicit
> `geometry_align_site` config (W4) with an assert on unrecognised names and a test pinning the
> parse, because "correct by accident" is one refactor away from "wrong and undetectable".

Sites, in order of preference:

1. **`post_vl_self_attention`** -- the default. Deepest reachable, no checkpoint change.
2. **`backbone_layer_{6, 9, 12}`** -- the shallow sweep. SF's layer 8/32 (0.25) scored second-best
   at 95.7, so shallow is not obviously fatal and the +/-1-point spread may be noise from their
   single-GPU ablation.
3. **`backbone_output`** -- the raw truncation point (layer 16), as the control that isolates what
   the four self-attention layers contribute.
4. **Raising `select_layer`** remains a last resort: it changes compute, the checkpoint's effective
   architecture, and invalidates comparison with the existing baseline.

### 4.2 Token grid -- already solved, and non-square

Vision config: 24 layers, `patch_size: 16`, `spatial_merge_size: 2`. Arena's 640x480 camera with
`shortest_image_edge`/`crop_fraction` yields an **8 x 11 = 88-token** grid, not square. This was
found the hard way and is already handled by `token_grid_from_image_grid_thw`, which reads the
processor's own `image_grid_thw`. The teacher's ViT-L/14 grid is resampled onto it bilinearly.

### 4.3 Masking

Upstream masks the alignment to valid image tokens, combining an empty-image mask with a
non-rectangular padding mask. Arena's G1 path is fixed-resolution and single-view, so no padding
arises today -- but the mask plumbing should exist, because `letter_box_transform` would introduce
padding and a silently-unmasked pad region would train the projector against nothing.

## 5. Corrections needed to the existing implementation

`gr00t/model/modules/geometry_conditioning.py` (branch `renan/feature/geometry-conditioning`) has
`mode="align"` working with 10 passing tests, but it was written from the paper summary. Against the
reference implementation it needs:

| # | Current | Correct to | Status |
| :-- | :--- | :--- | :--- |
| C1 | No positional embedding | **Add PE to the target** (§3.2) -- worth 10 points on Long upstream | **done** |
| C2 | `Linear -> BatchNorm1d -> GELU -> Linear`, output `geometry_dim` | `LayerNorm(student) -> Linear -> GELU -> Linear`, Xavier init, **output width = measured target width**; BatchNorm over a token axis is not what upstream does | **done** |
| C3 | `-cosine_similarity(...).mean()` | `1 - cos` with explicit `F.normalize`, per-sample then batch mean -- same gradient, non-negative and comparable to upstream logs | **done** |
| C4 | No mask argument | Accept an `align_mask` and apply it (§4.3) | **done** |
| C5 | `GEOMETRY_FEATURE_DIM_BY_ENCODER` hardcodes 384/768/1024 | Measure the width from one probe forward at load; the VGGT doubling shows the table is a trap | **done** -- table deleted, `probe_feature_dim()` added |
| C6 | Teacher fed post-augmentation images including colour jitter | Feed the geometric crop, drop colour ops (§3.4) | **not started**; `finetune_n17_geometry.sh:84-87` currently drops saturation and hue globally for geometry arms, which is a coarser stand-in, not replay |
| C7 | `align_weight` default `0.5` presented as settled | Rename to `align_loss_coeff`, document as **unknown upstream**, sweep it | **done** -- renamed through the config stack to `geometry_align_loss_coeff` |
| C8 | Encoder loaded via `AutoModelForDepthEstimation` | Add a DA3 branch -- **and do not go through `api.py`**, see W2 | **done** -- auto-detected family, Apache allowlist, strict load |
| C9 | Alignment site inherited from statement order | Explicit `geometry_align_site`, asserted and tested (§4.1) | **done** (W4) |

The align loss also moved from a flattened `(N, D)` signature to `(B, N, D)` plus an optional
`(B, N)` mask, because the target positional embedding and the per-sample mean are both defined over
the token axis and neither is expressible on a pre-flattened batch.

## 6. Work plan

### W1 -- Dependency probe -- ANSWERED: no rebuild needed

**Deliverable (2026-09-05): the image does NOT need rebuilding, and `docker/Dockerfile` does not
need touching.** The ask-first gate is avoided entirely. Resolved by reading DA3's manifests and
import graph rather than by installing, so nothing was mutated.

Three findings, each of which contradicts the draft's framing:

1. **`xformers` is optional, not a pin conflict.** Its single use is
   `model/dinov2/layers/swiglu_ffn.py:36`, inside a `try/except ImportError` that falls back to a
   pure-PyTorch `SwiGLUFFN`. The draft called an xformers/torch clash "the one thing that turns a
   small change into a rebuild fight"; it is a no-op. Skipping xformers costs a fused SwiGLU kernel
   in a frozen, `no_grad` teacher.
2. **`numpy<2` is already satisfied.** DA3 pins it; the GR00T training env has numpy **1.26.4**.
   Worth naming because it is the constraint that *would* have forced a rebuild.
3. **The real hazard is the import path, not the pins** -- see W2.

Environment as measured, correcting the draft's "venv312 has torch 2.9, the system env 2.7":

| Interpreter | torch | role |
| :--- | :--- | :--- |
| `/workspace/gr00t/.venv/bin/python` | 2.9.0+cu128 | the training env (uv-managed; `uv` at `/usr/local/bin/uv`, no `pip`) |
| `/opt/gr00t-venv312/bin/python` | 2.9.0+cu128 | image-level venv312, also no `pip` |
| `/usr/bin/python3` | 2.7.0a0+…nv25.04 | system env; **the only one with `pytest`** |

That last row is its own small trap: `pytest` and the full training dependencies live in *different*
interpreters, so the geometry unit tests run under `/usr/bin/python3` while a training smoke test
needs `.venv`. The tests are torch-only by design, which is what makes that split survivable.

### W2 -- Teacher wrapper -- DONE

Loads, runs, and produces the student's grid: 480x640 in -> 518x686 at the teacher -> 37x49 patches
-> resampled to 8x11 = **88 tokens of width 1024**, frozen, `no_grad`. The allowlist is enforced.

> [!CAUTION]
> **`from depth_anything_3.api import DepthAnything3` is the wrong entry point**, and both the
> draft's W2 and its §8.4 prescribed it. `api.py` imports `depth_anything_3.utils.export`, whose
> `__init__` eagerly pulls the COLMAP, GLB, Gaussian-splat and video exporters. Resolving the import
> graph gives **17 hard third-party packages**: `PIL addict cv2 einops evo huggingface_hub imageio
> matplotlib moviepy numpy omegaconf plyfile pycolmap torch torchvision tqdm trimesh` -- including
> `pycolmap`, `trimesh`, and `moviepy` pinned to 1.0.3 because `moviepy.editor` was removed in 2.x.
> None of it is on the model-forward path.
>
> Building the net from `{model.da3, model.dinov2.dinov2, model.dpt, cfg, registry, specs}` needs
> **five** -- `addict einops numpy omegaconf torch` -- with `xformers` soft. Only **`addict`** was
> missing. That is the entire dependency delta.

Four more details the draft got wrong, all found by running it:

1. **No forward hook is needed.** `DinoV2.forward` already returns
   `get_intermediate_layers(x, out_layers)`. The draft prescribed hooks because it assumed the only
   entry point was `api.py`, which returns just `depth/conf/extrinsics/intrinsics`.
2. **No token slicing is needed.** The return is a `(patch_tokens, cls_token)` pair per requested
   layer -- already separated -- and this monocular checkpoint's `aux` list is **empty**, so there
   are no camera or register tokens to drop. §3.3's `patch_start_idx` slice has no analogue here.
3. **`convert_metric_state_dict` must not be used.** It targets the original `torch.load` research
   checkpoints. The HF safetensors release was saved from the `api` wrapper whose `self.model` *is*
   this net, so the 406 keys arrive as `model.backbone.*` / `model.head.*` and need only that one
   prefix stripped -- then `load_state_dict(strict=True)` gives **missing=0, unexpected=0**. Running
   the conversion instead prepends `module.` and rewrites it to `model.`, yielding
   `model.model.backbone.*`: **406 missed, 406 unexpected, a silently untrained teacher.**
4. **The forward takes `(B, S, C, H, W)`**, where `S` is DA3's view axis -- 1 for a monocular
   teacher. A 4D tensor raises inside `_get_intermediate_layers_not_chunked`.

The teacher's input keeps the camera's aspect ratio at multiples of the ViT/14 patch size, so its
patch grid is rectangular in the same sense the student's token grid is and the resampling between
them is a rescale rather than a stretch. `Depth-Anything-V2`'s square 518 path is untouched.

Also confirmed first-hand: the bundled `depth_anything_3.configs.da3metric-large` yaml is
**byte-identical** to the checkpoint's own `config.json` `config` subtree, so either can build the
net; the checkpoint's is used, since it is the one the weights were saved against.

#### W2a -- where the source lives, and why not `pyproject.toml`

The first install put the clone in `/opt/depth-anything-3`, which is **container-local**, while
`uv` installed into `/workspace/gr00t/.venv` -- the *host-persistent*, gitignored 15 GB venv inside
`submodules/Isaac-GR00T`. That combination is a trap: the venv survives a container recreation and
the editable target does not, leaving
`_editable_impl_depth_anything_3.pth` pointing at a path that no longer exists. Fixed by moving the
clone to **`external_dependencies/depth-anything-3`** (pinned at `3d835ec`, 2026-07-27, 48 MB) and
reinstalling, which is the convention this repo already uses for LIBERO, robocasa, SimplerEnv and
GR00T-WholeBodyControl.

**DA3 must not go in `pyproject.toml`.** A `depth-anything-3 @ git+...` dependency resolves the
package's own metadata, which pulls all 24 declared dependencies and undoes the whole finding above;
`uv` has no per-package `--no-deps` in `pyproject.toml`. The repo agrees: none of the four existing
`external_dependencies/` packages appears in `[project] dependencies` either -- they are
ruff-excluded (`pyproject.toml:144`) and installed out of band. So the setup step stays a documented
command:

```bash
# inside the GR00T container, from /workspace/gr00t
uv pip install addict
uv pip install --no-deps -e external_dependencies/depth-anything-3
```

### W3 -- Corrections C1-C5, C7 -- DONE

Applied on `renan/feature/geometry-conditioning`. `geometry_conditioning.py` rewritten against the
reference implementation; the width table deleted from `gr00t_n1d7.py`; `geometry_align_weight`
renamed to `geometry_align_loss_coeff` through `configs/model/gr00t_n1d7.py`,
`configs/finetune_config.py`, `experiment/launch_finetune.py` and `gr00t_n1d7/setup.py`.

**20 unit tests pass** (`tests/gr00t/model/test_geometry_conditioning.py`), `pre-commit` clean. The
tests pin: `1 - cos` is 0 for identical and 2 for anti-aligned inputs; a masked loss equals the loss
over just the valid tokens, and poisoning masked positions does not move it; a fully-masked batch
raises; the projector's hidden and output widths both equal the measured target width and there is
no `BatchNorm1d`; `feature_dim` raises before a forward pass; the target embedding reaches the loss
and receives gradient; a pre-flattened batch raises.

> [!WARNING]
> **One test records a problem rather than a guarantee.** At the default
> `align_position_embedding_std = 0.02`, the target positional embedding shifts the loss by only
> **~2e-5** against unit-variance features -- it starts as a numerical no-op that the optimiser has
> to grow before C1 can be worth anything. SF credits the embedding with ten points on LIBERO-Long
> but publishes no initialisation scale, and its target is VGGT's aggregated tokens whose magnitude
> is unknown here. **W5 must report DA3METRIC-LARGE's feature scale, and this default must be set
> against it.** `test_positional_embedding_is_negligible_at_the_default_scale` documents the
> starting point so a later change is visible; it is not an endorsement.

### W4 -- Student-side alignment point -- DONE

`geometry_align_site` is now explicit and plumbed through the config stack, accepting
`post_vl_self_attention` (default), `backbone_output`, and `backbone_layer_<k>`. Parsing lives in
`geometry_conditioning.align_backbone_layer_from_site` -- beside the config it validates, and
importable with only torch, so it is testable without the training stack. `Qwen3Backbone` gained
`request_hidden_layers()`, which asserts `layer <= select_layer` and emits only the requested
hidden states, since the full tuple is one activation per layer. `Gr00tN1d7.forward` now captures
`backbone_features` **before** the action head overwrites it, so the site is a decision rather than
a consequence of statement order (§4.1).

### W5 -- Metric-error budget for the teacher

**Feature scale, already measured** (real `ego_view` frame from `episode_000180`, 518x686 in, 1813
patch tokens per layer). This is the number the target positional embedding has to be set against:

| DA3 `out_layers` entry | per-channel std | per-token L2 norm (mean) |
| ---: | ---: | ---: |
| 4 | 2.645 | 84.5 |
| 11 | 3.416 | 108.9 |
| 17 | 2.375 | 75.7 |
| **23** (the aligned one) | **0.718** | **23.0** |

Layer 23 is the *quietest* of the four by a factor of three or more. Absolute scale is irrelevant to
the loss, which L2-normalises both sides -- but the **PE's scale relative to the target** is not, and
at the default `std = 0.02` the embedding is **2.8% of layer 23's per-channel std**. So the earlier
note in W3 overstated it: the term is weak at initialisation, not literally inert, and because it is
learnable it can grow. Treat `align_position_embedding_std` as a third swept knob alongside
`geometry_align_loss_coeff` rather than as a settled default.

The depth-error measurement itself is still to do:
Compare `DA3METRIC-LARGE` against ground-truth sim depth using its own metric formula,
`metric_depth = focal * net_output / 300` with focal in pixels -- and we have GT intrinsics and GT
depth from `rerender_demos.py`. Report error **at the apple's projected pixels**, not whole-frame.
This is the number that says whether the teacher knows the 7 cm we are missing. With a relative
model this needed a scale-and-shift fit; with a metric model it is direct.

### W5a -- The arms could not select the teacher -- FIXED

`finetune_n17_geometry.sh` passed `--geometry-mode` and nothing else, while `geometry_encoder_id`
defaults to `depth-anything/Depth-Anything-V2-Small-hf` in `FinetuneConfig`. **Every `align` and
`mix` arm would therefore have trained against Depth-Anything-V2-Small while its logs said
`geometry_mode=align`** -- the `align-metric` and `align-cheap` arms of §W6 would have been the same
run, and the comparison would have looked healthy and measured nothing. `tyro` exposes the flag, so
this was purely a missing line in the launcher.

Fixed by making the teacher per-arm and printing it. Arms are now `baseline`, `parallax`, `align`
(DA3METRIC-LARGE), `align_anyview` (DA3-BASE), `align_cheap` (DA-V2-Small), `mix`, `align_parallax`,
with `--teacher` to override, `--align-site`, and `--align-loss-coeff` / `--pe-std` for the sweeps.
A geometry arm with no teacher now exits non-zero rather than falling back to the default, and a
path-shaped teacher that is not on disk fails with the `hf download` line needed to fix it.

Teachers resolve under `GEOMETRY_TEACHER_ROOT` (default `/models/isaaclab_arena`), **deliberately
not `$MODELS_DIR`**: that variable is commonly exported pointing at a task subdirectory -- observed
as `/models/isaaclab_arena/locomanipulation_tutorial` -- which would resolve the teacher to a path
that does not exist. Teachers are cross-task assets and live at the root of the models tree.

`geometry_align_position_embedding_std` is also plumbed end to end now, so W5's measured feature
scale can actually be acted on from the launcher.

### W6 -- Train the arms
#### W6a -- which container trains, and the one mount it needs

Neither container is currently able to run W6, for different reasons. Measured 2026-09-05:

| | `gr00t-server` | Arena container | this devcontainer |
| :--- | :--- | :--- | :--- |
| `/datasets` | **missing** | `~/datasets` | `~/datasets` |
| `/models` | `~/models` | `~/models` | `~/models` |
| `/eval` | missing | `~/eval` | missing |
| torch | 2.9.0+cu128 (`.venv`) | 2.10.0+cu128 | none |
| `transformers` | 4.57.3 | 4.57.6 | none |
| `gr00t` importable | yes | **yes** | no |
| `tyro` (needed by `launch_finetune.py`) | yes | **missing** | no |
| `pytest` | only in the torch-2.7 system env | yes | no |

So `finetune_n17_geometry.sh`'s defaults (`/datasets/...`, `/models/...`) match the **Arena**
container, where the data is but `tyro` is not; the complete training environment is in
**`gr00t-server`**, where `tyro` is but the data is not. The script's preflight loop does catch it
-- it exits with `Path does not exist: /datasets/...` -- so this fails fast rather than silently.

**Recommended fix: add the dataset mount to `gr00t-server`.** It is four lines in
`docker/run_gr00t_server.sh`, exactly mirroring the `/models` handling already there, including the
DevContainer host-path detection that inspects the devcontainer's own mounts by destination:
a
```diff
 HOST_MODELS_DIR="${MODELS_DIR:-$HOME/models}"
+HOST_DATASETS_DIR="${DATASET_DIR:-$HOME/datasets}"
 HOST_HF_CACHE_DIR="${HF_CACHE_DIR:-$HOME/.cache/huggingface}"
@@
         DETECTED_HOST_MODELS=$(docker inspect "${DEVCONTAINER_ID}" --format '{{range .Mounts}}{{if eq .Destination "/models"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true)
+        DETECTED_HOST_DATASETS=$(docker inspect "${DEVCONTAINER_ID}" --format '{{range .Mounts}}{{if eq .Destination "/datasets"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true)
@@
         [ -n "${DETECTED_HOST_MODELS}" ] && HOST_MODELS_DIR="${DETECTED_HOST_MODELS}"
+        [ -n "${DETECTED_HOST_DATASETS}" ] && HOST_DATASETS_DIR="${DETECTED_HOST_DATASETS}"
@@
     "-v" "${HOST_MODELS_DIR}:/models"
+    "-v" "${HOST_DATASETS_DIR}:/datasets"
```

`DATASET_DIR` is the right variable name because it is the one already used by convention on the
host and in the containers (§8.3), and it mirrors `MODELS_DIR`, which line 121 already consumes.
Consider `add_volume_if_it_exists`-style conditioning as `docker/run_docker.sh` does, so a host
without `~/datasets` still launches.

`docker/run_gr00t_server.sh` is **"ask first"** under `AGENTS.md`, so this is a draft PR, not a
direct edit. It is flagged and unchanged.

Two alternatives, both worse:

- **Install `tyro` into the Arena container** and train where the data already is. Rejected: its
  torch is 2.10 against gr00t-server's 2.9 and its `transformers` differs too, so the arms would not
  be reproducible against the environment the model was developed in -- and mutating Isaac Sim's
  interpreter risks the sim stack that Arena's own evaluation depends on, in a shared image every
  clone uses.
- **Point `DATASET_PATH` at something already mounted in `gr00t-server`**, i.e. under `~/models`.
  Zero shared-file change, but it puts datasets in the models tree and each future dataset needs the
  same manual placement. Acceptable only as a one-off unblock while the PR is open.

Via `isaaclab_arena_gr00t/scripts/finetune_n17_geometry.sh`, `--nproc-per-node 1..8`:

| Arm | teacher | `geometry_align_site` | `delta_indices` |
| :--- | :--- | :--- | :--- |
| baseline | none | -- | `[0]` |
| align-metric | `DA3METRIC-LARGE` | `post_vl_self_attention` | `[0]` |
| align-anyview | `DA3-BASE` | same | `[0]` |
| align-cheap | `DA-V2-Small` | same | `[0]` |
| align-metric-parallax | `DA3METRIC-LARGE` | same | `[-8, 0]` |

Plus, on the primary arm only, the site sweep `backbone_output` and `backbone_layer_{6, 9, 12}` --
the four self-attention layers above the truncation are the difference between 0.62 and 0.57
effective depth (§4.1), and `backbone_output` is the control that prices them.

`geometry_align_loss_coeff` swept over {0.1, 0.5, 1.0} on the primary arm only. Corpus frames as-is -- **no re-render, no
camera change** (the head-camera mount is digital-twin ground truth and is not to be refitted).

### W7 -- Gates

**G1 -- teacher competence (W5).** If `DA3METRIC-LARGE`'s own metric error at the apple is itself
~7 cm, it cannot teach what we lack and the teacher must change before any training spend.

**G2 -- depth readout, target scene.** `probe_depth_readout.py`, ridge probe on image-token
embeddings against GT depth, **trained on corpus, tested on the maple-table scene**. Baseline
already measured at **1.33 cm median / R² 0.997 on the corpus scene** -- which is why the
target-scene split is the only informative version: corpus-to-corpus in a zero-variation corpus is
near-duplicate evaluation. Pass = error drops materially on the **target** scene.

Note this probe is *stronger* than upstream's: SF's depth probing is qualitative, a DPT head and
figures, with no RMSE, δ₁ or AbsRel reported anywhere. Ours is quantitative.

**G3 -- task endpoint.** Hand-to-apple vertical error at closest horizontal approach, from the
`ReachTracer` hand tracing. Baseline to beat: **+0.1286 m at chunk 16, ~0.0795 m at chunk 8**, with
~7 cm as the stated floor. Success-rate comparison needs n ≥ 30 per arm and is out of this plan's
scope.

## 7. Risks

1. **The truncation risk (§4.1), downgraded but not gone.** Measured against the real checkpoints
   the deepest reachable site is an effective 20 layers, not 12 -- 0.62 depth against upstream's best
   at 0.75, and clear of the 0.5 ratio that scored worst. It is still shallower than upstream. If
   `post_vl_self_attention`, the `backbone_layer_{6,9,12}` sweep and the `backbone_output` control
   all fail, the honest conclusion is that SF does not port cleanly to a backbone truncated at 0.57
   depth -- not that geometry alignment does not work.
2. **The positional-embedding scale is unpinned and currently inert.** At the default std the target
   embedding moves the loss by ~2e-5 (W3). SF attributes ten points on LIBERO-Long to this term and
   publishes no scale, so the arm could reproduce the *ablated* configuration while believing it
   reproduced the full one. Gated on W5 measuring the teacher's feature scale.
3. **The corpus has zero spatial variation** (`APPLE_SPAWN_XY_RANGE_M = 0.0`, plate at a fixed
   `Pose`). All 251 episodes are one layout, so there is little for a spatial objective to bind to.
   SF's 5.9x data-efficiency claim is about *quantity*, not *diversity*, and does not rescue this.
   G2's target-scene split is what detects the failure.
4. **The teacher is monocular** (§2), unlike VGGT upstream. `align-anyview` measures the cost.
5. **α is unpublished** and the sweep is on three values only.
6. **Broken background materials.** `galileo_locomanip` references textures that 404 on both the
   staging and production buckets; 61 MDL shader nodes fail to resolve every run, so the scene
   renders with fallback materials. This affects the teacher's input as much as the student's. It
   does not invalidate an alignment objective -- both see the same pixels -- but it does mean the
   corpus frames we train on are not the frames the dataset was recorded from.
7. **Falsification.** If G1 passes, G2 shows no target-scene readout gain, and G3 does not move,
   then embedding alignment has been tested properly and failed here, and the live option becomes
   new demonstrations with genuine spatial variation. Record that plainly rather than absorbing it.

## 8. Model options and how to fetch them

Licences and gating below were **verified against the Hugging Face API on 2026-09-05**, not taken
from papers or blog posts. `gated` and the `license:` tag come from `api/models/<id>`.

### 8.1 Teacher candidates

| Repo id | Licence (verified) | Size | Geometry | Any-view? | Role here |
| :--- | :--- | ---: | :--- | :--- | :--- |
| **`depth-anything/DA3METRIC-LARGE`** | **apache-2.0**, not gated | 0.35B | **metric** depth | no (`alt_start: -1`) | **primary teacher** -- metric is the failing quantity |
| `depth-anything/DA3-BASE` | apache-2.0, not gated | 0.12B | rel. depth + pose | **yes** | contrast: does multi-view aggregation matter? |
| `depth-anything/DA3-SMALL` | apache-2.0, not gated | 0.08B | rel. depth + pose | yes | cheapest any-view; inference-affordable for a `mix` variant |
| `depth-anything/DA3MONO-LARGE` | apache-2.0, not gated | 0.35B | rel. depth (mono) | no | relative counterpart to METRIC-LARGE; isolates *metric* from *capacity* |
| `facebook/map-anything-apache` | apache-2.0, not gated | 1B | metric point maps + pose | **yes** | VGGT-class Apache alternative; beats VGGT on pointmap rel. error (0.16 vs 0.20) |
| `Ruicheng/moge-2-vitl` | **mit** | ViT-L | metric point map + normals + FOV | no | MIT, single-view specialist |
| `Ruicheng/moge-2-vitl-normal` | mit | ViT-L | + normal maps | no | as above, with normals |
| `depth-anything/Depth-Anything-V2-Small-hf` | apache-2.0, not gated | 24.8M | relative depth | no | already wired and tested; the cheap floor |

All eight rows re-verified against the HF API on 2026-09-05: present, `gated=False`, licences as
listed. Each is fetched to `${MODELS_DIR}<repo-basename>` per §8.3 and referenced by that local path,
not by repo id.

### 8.2 Ruled out -- do not select

| Repo id | Licence (verified) | Why excluded |
| :--- | :--- | :--- |
| `facebook/VGGT-Omega` | `license:other`, **`gated=manual`** | Non-commercial research licence + manual approval |
| `facebook/map-anything` | **cc-by-nc-4.0** | Non-commercial; the `-apache` sibling is the one to use |
| `depth-anything/Depth-Anything-V2-Base-hf` | **cc-by-nc-4.0** | Only DA-V2-**Small** is Apache in that family |
| `depth-anything/DA3-LARGE-1.1` and the GIANT / NESTED series | repo table says **cc-by-nc-4.0** | See the warning below |

> [!CAUTION]
> **Hugging Face reports the wrong licence for `DA3-LARGE-1.1`.** Re-verified 2026-09-05: the HF
> API returns `license:apache-2.0`, **and the HF model card's own table also says "Apache 2.0"** --
> while the upstream GitHub README table
> (`ByteDance-Seed/depth-anything-3/README.md`, licence column) lists `DA3-LARGE-1.1` as
> **CC BY-NC 4.0**, alongside `DA3-LARGE`, both GIANT checkpoints and both NESTED checkpoints. A
> maintainer confirmed the CC BY-NC status in a HF discussion. **The GitHub table is authoritative;
> neither the HF tag nor the HF card is.** The disagreement is worse than "a mis-tag" -- the card a
> reader would actually consult is the one that is wrong -- which is exactly why §2 requires an
> explicit allowlist in config rather than trusting a licence string at download time.
>
> Separately, the `Depth-Anything-V2-Metric-*` variants carry **no licence tag at all**
> (`license:UNSET`). Do not assume they inherit Small's Apache terms -- verify before use.

### 8.3 Download commands

Both containers ship the modern `hf` CLI at `/usr/local/bin/hf` (`huggingface-cli` remains as a
legacy alias). Teachers are materialised **outside** the HF cache, into the mounted models volume,
via `--local-dir` -- so a container recreation cannot lose them and both containers resolve the same
path.

Path convention -- base directories, host and container:

```bash
# --- on the host
export DATASET_DIR=$HOME/datasets/isaaclab_arena/
export MODELS_DIR=$HOME/models/isaaclab_arena/

# --- inside either container (the same two trees, bind-mounted)
export DATASET_DIR=/datasets/isaaclab_arena/
export MODELS_DIR=/models/isaaclab_arena/
```

> [!IMPORTANT]
> Two footguns in that convention:
> 1. **Keep the trailing slash.** The commands below concatenate directly
>    (`${MODELS_DIR}DA3METRIC-LARGE`) rather than inserting a separator, so a value without the
>    trailing `/` silently writes a sibling named `isaaclab_arenaDA3METRIC-LARGE`.
> 2. **The Arena container's shell may already export these pointing at a *task* subdirectory**
>    (observed: `MODELS_DIR=/models/isaaclab_arena/locomanipulation_tutorial`, no trailing slash).
>    Re-export the base values above before downloading, or the teacher lands under an unrelated
>    task. Teachers are cross-task assets and belong at the base level.

Primary teacher:

```bash
hf download depth-anything/DA3METRIC-LARGE --local-dir ${MODELS_DIR}DA3METRIC-LARGE
```

Contrast teachers (§8.1), same pattern:

```bash
hf download depth-anything/DA3-BASE                   --local-dir ${MODELS_DIR}DA3-BASE
hf download depth-anything/DA3MONO-LARGE              --local-dir ${MODELS_DIR}DA3MONO-LARGE
hf download depth-anything/Depth-Anything-V2-Small-hf --local-dir ${MODELS_DIR}Depth-Anything-V2-Small-hf
hf download facebook/map-anything-apache              --local-dir ${MODELS_DIR}map-anything-apache
hf download Ruicheng/moge-2-vitl                      --local-dir ${MODELS_DIR}moge-2-vitl
```

Every DA3 repo is exactly **4 files** (`config.json`, `model.safetensors`, `README.md`,
`.gitattributes`), so there are no demo assets to filter and `--include` is unnecessary. `hf auth
login` is **not** needed -- none of the §8.1 teachers is gated (verified 2026-09-05).

Loading then points at the local directory rather than a repo id, which keeps a run
offline-reproducible and independent of `HF_HOME`:

```python
import os
from depth_anything_3.api import DepthAnything3

model = DepthAnything3.from_pretrained(f"{os.environ['MODELS_DIR']}DA3METRIC-LARGE")
```

**Status: all four teachers are fetched**, host-persistent under `~/models/isaaclab_arena`, and
visible as `/models/isaaclab_arena/...` in the Arena container, this devcontainer, and
`gr00t-server` alike (all three bind the same host `~/models`). Commits recorded 2026-09-05 from
each local dir's `.cache/huggingface/download/model.safetensors.metadata`:

| Teacher | size | pinned commit |
| :--- | ---: | :--- |
| `DA3METRIC-LARGE` | 1.3 GB | `4010e39f3634a45bc60553321fb49fb760bd594e` |
| `DA3MONO-LARGE` | 1.3 GB | `f465978e618db8cc79c83b8bbf24964857db1875` |
| `DA3-BASE` | 517 MB | `f4a6c9b3c95e41c82048423d3493a81ec3fa810e` |
| `Depth-Anything-V2-Small-hf` | 95 MB | `5426e4f0f36572d16453bbda7a8389317b1bef99` |

`DA3METRIC-LARGE`'s commit equals the repo's current `main` sha, and its `model.safetensors` is
sha256 `bbea5b0b3ee389849cffa7ddae89de064a90abd2b055fc5aa99aac68db324776`. **Record these in the run
manifest and re-fetch with `--revision <commit>`**, since `hf download` without one tracks a moving
`main` and the arms would not be comparable across a silent upstream refresh.

> [!NOTE]
> **Correcting an earlier note in this plan:** it claimed a second ~1.3 GB copy of
> `DA3METRIC-LARGE` sat in the default HF cache and should be deleted. Measured: that path holds
> only a `refs/main` stub totalling **12 KB**, and the whole xet cache is 55 MB. There is no
> duplicate to reclaim.

> [!NOTE]
> `--local-dir` also sidesteps the cache-location trap that an earlier draft of this section had to
> work around: the GR00T container's default `HF_HOME` (`/root/.cache/huggingface`) is host-mounted
> and holds the gated `nvidia/Cosmos-Reason2-2B` backbone, so **overriding `HF_HOME` there hides the
> backbone and produces a 401 that reads like a permissions failure**. With `--local-dir` nothing
> needs overriding in either container, and the pre-existing `/models/.hf_cache` (which already
> holds `Depth-Anything-V2-Small-hf`) stays valid for anything cached the old way.
>
> Consequently the `docker/run_docker.sh` change that would mount `~/.cache/huggingface` into the
> Arena container the way `run_gr00t_server.sh` does is now **optional rather than the fix**. It is
> an "ask first" file under `AGENTS.md`, so it stays flagged and unchanged either way.


### 8.4 Package installs per family

```bash
# DA3 -- not on PyPI. Install the SOURCE ONLY: `pip install -e .` would pull 24 declared
# dependencies (pycolmap, open3d, moviepy==1.0.3, evo, e3nn, trimesh, gradio ...) that exist for the
# CLI, benchmark and export paths, none of which a frozen feature extractor touches. See W2.
# Clone into external_dependencies/, NOT a container-local path like /opt: the .venv that holds the
# editable pointer lives on the host and outlives the container, so a /opt target dangles. See W2a.
git clone https://github.com/ByteDance-Seed/depth-anything-3 \
  submodules/Isaac-GR00T/external_dependencies/depth-anything-3
uv pip install addict                                  # the only missing runtime dep
uv pip install --no-deps -e external_dependencies/depth-anything-3
# xformers is OPTIONAL: its one use is guarded by try/except with a pure-PyTorch SwiGLU fallback.
# python: from depth_anything_3.cfg import create_object, load_config
#         net = create_object(load_config(f"{os.environ['MODELS_DIR']}DA3METRIC-LARGE/config.json"))
#         # then utils.model_loading.load_pretrained_weights(net, ..., is_metric=True)
#         # NOT depth_anything_3.api -- that import pulls the 17-package export chain.

# MapAnything -- not on PyPI either
git clone https://github.com/facebookresearch/map-anything && cd map-anything && pip install -e .

# MoGe-2
pip install git+https://github.com/microsoft/MoGe.git

# Depth-Anything-V2 -- already available, no install needed
# python: from transformers import AutoModelForDepthEstimation
```

W1 resolved the first block: `xformers` is optional, `numpy<2` is already satisfied at 1.26.4, and
`docker/Dockerfile` does not need touching. The remaining install is `addict` plus a `--no-deps`
source install, both inside the container's existing training env.

## 9. Sources

- Spatial Forcing: [arXiv:2510.12276](https://arxiv.org/abs/2510.12276) · [code](https://github.com/OpenHelix-Team/Spatial-Forcing) (MIT) -- method details in §3 taken from `openpi-SF/src/openpi/models_pytorch/{pi0_align_pytorch.py,projectors.py}` and `openpi-SF/scripts/train_align_pytorch.py`
- Depth Anything 3: [arXiv:2511.10647](https://arxiv.org/abs/2511.10647) · [code](https://github.com/bytedance-seed/depth-anything-3) · [DA3METRIC-LARGE config](https://github.com/bytedance-seed/depth-anything-3/blob/main/src/depth_anything_3/configs/da3metric-large.yaml) · [DA3-LARGE licence clarification](https://huggingface.co/depth-anything/DA3-LARGE/discussions/2)
- Alternatives considered: [MapAnything](https://arxiv.org/pdf/2509.13414) (`facebook/map-anything-apache`, Apache-2.0, any-view, 1B) · [MoGe-2](https://github.com/microsoft/MoGe) (MIT) · [VGGT-Omega](https://huggingface.co/facebook/VGGT-Omega) (non-commercial; VGGT-1B benchmark contamination noted 2026-08-18)
- Contrast method: [3D-Mix for VLA](https://arxiv.org/html/2603.24393v1) -- gated fusion, needs the teacher at inference; its pilot scores SF at only +1.04 over base, which the shared-encoder design lets us adjudicate ourselves
- In-repo: [`g1_monocular_depth_and_camera_pitch_debug.md`](g1_monocular_depth_and_camera_pitch_debug.md) · [`g1_pick_success_phases.md`](g1_pick_success_phases.md)
