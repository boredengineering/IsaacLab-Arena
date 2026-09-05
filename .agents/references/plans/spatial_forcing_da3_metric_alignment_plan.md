# Spatial Forcing with DA3METRIC-LARGE: Giving the G1 Policy Metric Range

> [!IMPORTANT]
> **Status**: PLAN, 2026-09-05. Implements Spatial Forcing ([arXiv:2510.12276](https://arxiv.org/abs/2510.12276),
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
| Student layer | sweep **{6, 9, 12}** + post-`vl_self_attention` | See §4.1 -- the truncation forces this |
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
> **`align_loss_coeff` (α) is never given a number** in the paper body -- Appendix A is titled
> "Weight Factor" but the value is not recoverable from the HTML, and it is not in the files fetched.
> Treat α as unknown and sweep it. The `0.5` currently defaulted in Arena is a guess and should not
> be reported as if it came from the paper.

## 4. Porting to GR00T N1.7

### 4.1 The layer-depth problem -- the main technical risk

SF aligns **layer 24 of 32** in Prismatic (0.75 depth), and its layer ablation is non-monotonic:

| Layer (of 32) | Avg |
| ---: | ---: |
| 1 | 94.6 |
| 8 | 95.7 |
| 16 | 93.8 |
| **24** | **96.9** |
| 32 | 94.8 |

**Cosmos-Reason2-2B has 28 text layers (hidden 2048), and N1.7 truncates the LLM at
`select_layer=12`** (`qwen3_backbone.py:194-195`, `configs/model/gr00t_n1d7.py:40-51`). Layers above
12 **do not exist** in the model, so the deepest available alignment point is **12/28 = 0.43
depth** -- near the 16/32 = 0.5 ratio that scored *worst* in SF's sweep.

Three responses, in order of preference:

1. **Align after `vlln` + `vl_self_attention`** (`gr00t_n1d7.py:176-179`). These sit above the
   truncated backbone and add effective depth without changing the checkpoint, so this is the
   closest reachable analogue to "deep but not deepest". **Try this first.**
2. **Sweep {6, 9, 12}** inside the backbone. SF's own numbers put layer 8/32 (0.25) second-best at
   95.7, ahead of 16/32, so shallow is not obviously fatal and the ±1-point spread may be noise
   from their single-GPU ablation.
3. **Raise `select_layer`** only as a last resort: it changes compute, the checkpoint's effective
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

| # | Current | Correct to |
| :-- | :--- | :--- |
| C1 | No positional embedding | **Add PE to the target** (§3.2) -- worth 10 points on Long upstream |
| C2 | `Linear -> BatchNorm1d -> GELU -> Linear`, output `geometry_dim` | `LayerNorm(student) -> Linear -> GELU -> Linear`, Xavier init, **output width = measured target width**; BatchNorm over a token axis is not what upstream does |
| C3 | `-cosine_similarity(...).mean()` | `1 - cos` with explicit `F.normalize`, per-sample then batch mean -- same gradient, non-negative and comparable to upstream logs |
| C4 | No mask argument | Accept an `align_mask` and apply it (§4.3) |
| C5 | `GEOMETRY_FEATURE_DIM_BY_ENCODER` hardcodes 384/768/1024 | Measure the width from one probe forward at load; the VGGT doubling shows the table is a trap |
| C6 | Teacher fed post-augmentation images including colour jitter | Feed the geometric crop, drop colour ops (§3.4) |
| C7 | `align_weight` default `0.5` presented as settled | Rename to `align_loss_coeff`, document as **unknown upstream**, sweep it |
| C8 | Encoder loaded via `AutoModelForDepthEstimation` | Add a DA3 branch; DA3 is not in `transformers` |

## 6. Work plan

### W1 -- Dependency probe (no gated edit)
Verify `depth-anything-3` installs against the GR00T image's pinned torch **before** touching
`docker/Dockerfile`. Install is `pip install xformers "torch>=2" torchvision` then `pip install -e .`;
skip the `gsplat` extra (Gaussian head only). The image's `venv312` has torch 2.9, the system env
2.7 -- an `xformers` conflict is the one thing that turns a small change into a rebuild fight.
**Deliverable**: a yes/no on whether the image needs rebuilding.

### W2 -- Teacher wrapper
Extend `FrozenGeometryEncoder` with a DA3 branch: `from depth_anything_3.api import DepthAnything3`,
`from_pretrained("depth-anything/DA3METRIC-LARGE")`, frozen, eval, bf16, `no_grad`. The Python API
returns only `depth/conf/extrinsics/intrinsics` -- **no intermediate features** -- so features come
from a forward hook on the ViT blocks at `out_layers`, the same technique
`probe_depth_readout.py` already uses on the GR00T backbone. Measure the width (expect 1024) rather
than trusting the config. Add the Apache-only allowlist.

### W3 -- Corrections C1-C7
Apply the table in §5. Extend the unit tests: PE presence changes the loss; masked tokens are
excluded; projector output width equals the measured target width; `1 - cos` is 0 for identical
inputs and 2 for anti-aligned.

### W4 -- Student-side alignment point
Make the alignment site configurable over `{backbone layer 6, 9, 12, post-vl_self_attention}` and
plumb it through `Gr00tN1d7.forward`. Requires `output_hidden_states` from the truncated backbone,
which `qwen3_backbone.py:361` already requests.

### W5 -- Metric-error budget for the teacher
Compare `DA3METRIC-LARGE` against ground-truth sim depth using its own metric formula,
`metric_depth = focal * net_output / 300` with focal in pixels -- and we have GT intrinsics and GT
depth from `rerender_demos.py`. Report error **at the apple's projected pixels**, not whole-frame.
This is the number that says whether the teacher knows the 7 cm we are missing. With a relative
model this needed a scale-and-shift fit; with a metric model it is direct.

### W6 -- Train the arms
Via `isaaclab_arena_gr00t/scripts/finetune_n17_geometry.sh`, `--nproc-per-node 1..8`:

| Arm | teacher | student layer | `delta_indices` |
| :--- | :--- | :--- | :--- |
| baseline | none | -- | `[0]` |
| align-metric | `DA3METRIC-LARGE` | best of W4 | `[0]` |
| align-anyview | `DA3-BASE` | same | `[0]` |
| align-cheap | `DA-V2-Small` | same | `[0]` |
| align-metric-parallax | `DA3METRIC-LARGE` | same | `[-8, 0]` |

α swept over {0.1, 0.5, 1.0} on the primary arm only. Corpus frames as-is -- **no re-render, no
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

1. **The truncation risk (§4.1) is the big one.** N1.7's only available alignment depths sit where
   SF measured its weakest results. If the post-`vl_self_attention` variant and the {6, 9, 12} sweep
   all fail, the honest conclusion is that SF does not port cleanly to a backbone truncated at 0.43
   depth -- not that geometry alignment does not work.
2. **The corpus has zero spatial variation** (`APPLE_SPAWN_XY_RANGE_M = 0.0`, plate at a fixed
   `Pose`). All 251 episodes are one layout, so there is little for a spatial objective to bind to.
   SF's 5.9x data-efficiency claim is about *quantity*, not *diversity*, and does not rescue this.
   G2's target-scene split is what detects the failure.
3. **The teacher is monocular** (§2), unlike VGGT upstream. `align-anyview` measures the cost.
4. **α is unpublished** and the sweep is on three values only.
5. **Broken background materials.** `galileo_locomanip` references textures that 404 on both the
   staging and production buckets; 61 MDL shader nodes fail to resolve every run, so the scene
   renders with fallback materials. This affects the teacher's input as much as the student's. It
   does not invalidate an alignment objective -- both see the same pixels -- but it does mean the
   corpus frames we train on are not the frames the dataset was recorded from.
6. **Falsification.** If G1 passes, G2 shows no target-scene readout gain, and G3 does not move,
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

### 8.2 Ruled out -- do not select

| Repo id | Licence (verified) | Why excluded |
| :--- | :--- | :--- |
| `facebook/VGGT-Omega` | `license:other`, **`gated=manual`** | Non-commercial research licence + manual approval |
| `facebook/map-anything` | **cc-by-nc-4.0** | Non-commercial; the `-apache` sibling is the one to use |
| `depth-anything/Depth-Anything-V2-Base-hf` | **cc-by-nc-4.0** | Only DA-V2-**Small** is Apache in that family |
| `depth-anything/DA3-LARGE-1.1` and the GIANT / NESTED series | repo table says **cc-by-nc-4.0** | See the warning below |

> [!CAUTION]
> **The HF metadata lies for `DA3-LARGE-1.1`.** Its API response reports
> `license:apache-2.0`, while the repo's own model table lists it as CC BY-NC 4.0, and a maintainer
> confirmed the CC BY-NC status in a HF discussion. **The repo table is authoritative, not the HF
> tag.** Verified first-hand on 2026-09-05. This is why §2 requires an explicit allowlist in config
> rather than trusting a licence string at download time.
>
> Separately, the `Depth-Anything-V2-Metric-*` variants carry **no licence tag at all**
> (`license:UNSET`). Do not assume they inherit Small's Apache terms -- verify before use.

### 8.3 Download commands

Both containers have the modern `hf` CLI (`huggingface_hub` 0.36.2); `huggingface-cli` still exists
as a legacy alias. Cache locations differ, and this matters -- overriding `HF_HOME` in the GR00T
container **hides the host-mounted cache holding the gated `nvidia/Cosmos-Reason2-2B` backbone**,
which fails with a 401 that looks like a permissions problem.

```bash
# --- GR00T container: use the default cache. It is host-mounted
# (/home/<user>/.cache/huggingface -> /root/.cache/huggingface) and already holds the VLM backbone.
# Do NOT set HF_HOME here.
docker exec gr00t-server bash -lc 'hf download depth-anything/DA3METRIC-LARGE'
docker exec gr00t-server bash -lc 'hf download depth-anything/DA3-BASE'

# --- Arena container: /root/.cache is NOT host-mounted, so downloads are lost on container
# recreation. Point HF_HOME at the mounted models volume instead (never at the repo).
ARENA_CONTAINER=$(docker ps --format '{{.Names}}	{{.Image}}'   | awk -F'	' '$2 ~ /^isaaclab_arena:/ {print $1; exit}')
docker exec "$ARENA_CONTAINER" su $(id -un) -c \
  'HF_HOME=/models/.hf_cache hf download depth-anything/DA3METRIC-LARGE'

# --- optional contrast teachers
hf download depth-anything/DA3MONO-LARGE
hf download facebook/map-anything-apache
hf download Ruicheng/moge-2-vitl
hf download depth-anything/Depth-Anything-V2-Small-hf   # already cached at /models/.hf_cache
```

Useful flags: `--include "*.safetensors" "*.json"` to skip demo assets, `--local-dir <path>` to
materialise outside the cache, and `hf auth login` only for gated repos (none of the Apache teachers
above are gated).

> [!NOTE]
> The proper fix for the Arena container is one line in `docker/run_docker.sh` mounting
> `~/.cache/huggingface` the way `run_gr00t_server.sh` already does, so both containers share one
> cache. That file is "ask first" under `AGENTS.md`, so it is flagged rather than changed.

### 8.4 Package installs per family

```bash
# DA3 -- not on PyPI. Skip the gsplat extra (Gaussian head only).
git clone https://github.com/ByteDance-Seed/depth-anything-3 && cd depth-anything-3
pip install xformers "torch>=2" torchvision && pip install -e .
# python: from depth_anything_3.api import DepthAnything3
#         model = DepthAnything3.from_pretrained("depth-anything/DA3METRIC-LARGE")

# MapAnything -- not on PyPI either
git clone https://github.com/facebookresearch/map-anything && cd map-anything && pip install -e .

# MoGe-2
pip install git+https://github.com/microsoft/MoGe.git

# Depth-Anything-V2 -- already available, no install needed
# python: from transformers import AutoModelForDepthEstimation
```

W1's dependency probe covers exactly the first block: whether `xformers` resolves against the GR00T
image's pinned torch (2.9 in `venv312`, 2.7 in the system env) before `docker/Dockerfile` is touched.

## 9. Sources

- Spatial Forcing: [arXiv:2510.12276](https://arxiv.org/abs/2510.12276) · [code](https://github.com/OpenHelix-Team/Spatial-Forcing) (MIT) -- method details in §3 taken from `openpi-SF/src/openpi/models_pytorch/{pi0_align_pytorch.py,projectors.py}` and `openpi-SF/scripts/train_align_pytorch.py`
- Depth Anything 3: [arXiv:2511.10647](https://arxiv.org/abs/2511.10647) · [code](https://github.com/bytedance-seed/depth-anything-3) · [DA3METRIC-LARGE config](https://github.com/bytedance-seed/depth-anything-3/blob/main/src/depth_anything_3/configs/da3metric-large.yaml) · [DA3-LARGE licence clarification](https://huggingface.co/depth-anything/DA3-LARGE/discussions/2)
- Alternatives considered: [MapAnything](https://arxiv.org/pdf/2509.13414) (`facebook/map-anything-apache`, Apache-2.0, any-view, 1B) · [MoGe-2](https://github.com/microsoft/MoGe) (MIT) · [VGGT-Omega](https://huggingface.co/facebook/VGGT-Omega) (non-commercial; VGGT-1B benchmark contamination noted 2026-08-18)
- Contrast method: [3D-Mix for VLA](https://arxiv.org/html/2603.24393v1) -- gated fusion, needs the teacher at inference; its pilot scores SF at only +1.04 over base, which the shared-encoder design lets us adjudicate ourselves
- In-repo: [`g1_monocular_depth_and_camera_pitch_debug.md`](g1_monocular_depth_and_camera_pitch_debug.md) · [`g1_pick_success_phases.md`](g1_pick_success_phases.md)
