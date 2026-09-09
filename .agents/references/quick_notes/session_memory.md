# Session Memory: Active Inference & Robot Vision-Language-Action (VLA) Calibration

## 1. DROID / Franka Geometric & Visual Standoff Constants
* **Robot Base Origin**: `[-0.55, 0.0, 0.0]` (Franka mounted on DROID stand).
* **Table-to-Arm Proximity**:
  * In real DROID physical setups, the Franka base is mounted immediately adjacent to the table edge ($10\text{ cm} - 15\text{ cm}$ gap).
  * Table origin is shifted to `[-0.25, 0.0, 0.0]` so the tabletop front edge sits directly against the Franka stand and tabletop center is within $0.30\text{ m} - 0.40\text{ m}$ of the robot base.
* **VLA Fine-Tuning Distribution & Near-Field Inductive Bias**:
  * **VLA Training Distribution**: VLA models (`GR00T-N1.6-DROID`, OpenVLA, Octo, $\pi_0$) are trained exclusively on human teleoperated demonstrations where objects are located strictly in the **near-field manipulation zone** ($20\text{ cm} - 45\text{ cm}$ directly in front of the robot arm).
  * **Visual Perception Limit**: Franka's downward-angled camera ($45^\circ$) only captures $X_{\text{world}} \in [-0.35, 0.05]\text{ m}$ ($20\text{ cm} - 50\text{ cm}$ in front of base). Anything further is outside the camera FOV, and the VLA cannot pick what it cannot see.
  * **Spatial Constraint Invariant**: All manipulands, target receptacles, and interactive objects must be placed within $d \in [0.25, 0.45]\text{ m}$ ($X \in [-0.30, -0.10]\text{ m}, Y \in [-0.20, 0.20]\text{ m}$) relative to the robot base.

## 2. Spatial Placement & Sector-Confined Pocket Randomization
* **Sector-Bounded Initial Sampling**:
  * `On(parent, surface_sector='front_right')` and `On(parent, surface_sector='front_left')` constrain candidate sampling in `ObjectPlacer` strictly to the designated sector bounds (e.g. $Y \in [-0.26, -0.10]\text{ m}$ for `front_right`, $Y \in [0.10, 0.26]\text{ m}$ for `front_left`), accounting for parent fixture translation.
* **Pocket Randomization on Reset**:
  * Objects with `surface_sector` automatically receive `RandomAroundSolution(x_half_m=0.03, y_half_m=0.03)`. On every episode reset, objects randomize within a $\pm 3\text{ cm}$ local pocket inside their section, rather than jumping across the entire tabletop.
* **Bilateral Workspace Separation**:
  * Source manipulands and destination receptacles are placed in opposite sectors (`front_right` vs. `front_left`), maintaining $\ge 28\text{ cm} - 36\text{ cm}$ lateral clearance.
  * This avoids visual feature overlap in wrist/exterior cameras and eliminates gripper-receptacle collisions during pre-grasp.

## 3. Environment & Container Setup
* **Host vs Container Storage Mount Conventions**:
  * **On the Host**:
    * Datasets: `$HOME/datasets/isaaclab_arena/<tutorial_name>` (e.g. `$HOME/datasets/isaaclab_arena/locomanipulation_tutorial`, `$HOME/datasets/isaaclab_arena/static_apple_tutorial`)
    * Models: `$HOME/models/isaaclab_arena/<tutorial_name>` (e.g. `$HOME/models/isaaclab_arena/locomanipulation_tutorial`, `$HOME/models/isaaclab_arena/static_apple_tutorial`)
  * **Inside the Container**:
    * Datasets: `/datasets/isaaclab_arena/<tutorial_name>`
    * Models: `/models/isaaclab_arena/<tutorial_name>`
    * Workspace / Repo: `/workspaces/IsaacLab-Arena` (or `/workspaces/isaaclab_arena` in sim container)
* **Devcontainer Persistent State**:
  * Development container: `isaaclab_arena-latest`
  * Submodules present: `IsaacLab`, `Isaac-GR00T`
  * System tools: `uv`, `rerun`, `huggingface_hub`

## 4. Unified Environment & Evaluation Semantic Versioning
* **Canonical Directory Hierarchy**:
  * Graph specs: `/workspaces/isaaclab_arena/generated_envs/<env_name>/v1, v2, v3, ...` with `latest` symlink pointer.
  * Evaluation runs: `/workspaces/isaaclab_arena/eval_output/<env_name>/v1, v2, v3, ...` with `latest` symlink pointer.
* **Dual-Ledger Lineage Tracking**:
  * Human/Agent JSON: `lineage.json` with parent version pointers, refinement triggers, and success rates.
  * W3C PROV-O RDF-star: `lineage.ttl` tracking agent activities, derivations, and evaluations.
* **Automated Telemetry Sync**:
  * `policy_runner.py` automatically synchronizes evaluation metrics (`success_rate`, `object_moved_rate`, `episode_count`) into `lineage.json` and `lineage.ttl` upon rollout completion.

## 5. Foundation Policy Server (Isaac-GR00T)
* **Architecture**: `nvidia/GR00T-N1.6-DROID` with `AlternateVLDiT` diffusion action chunking.
* **Embodiment Specification**: Must use `droid_abs_joint_pos` with DROID camera and joint space.
* **Protocol**: ZeroMQ RPC on port `5557` (default port `5556` may be in use by other services).
* **Language Conditioning**: Policy config YAML **must** declare `language_instruction: "<task description>"`. Without this, the multimodal language backbone receives empty string and fails to ground objects.
* **Evaluation Horizon**: Use at least $\ge 1500 - 2000\text{ steps}$ ($30 - 40\text{ s}$) for complete pick-and-place trajectories.

## 5. Active Inference Self-Healing Pipeline
* **Diagnostic Oracle**: `EvaluationDiagnosticOracle` ingests `eval_telemetry.ttl` and classifies defects (`camera_occlusion`, `unconditioned_vla`, `horizon_truncation`, `reach_singularity`).
* **Remediation Engine**: `EvaluationRemediationEngine` auto-patches policy YAML, pulls table/objects into the near-field VLA sweet spot ($X \in [-0.30, -0.10]\text{ m}$), assigns bilateral sectors, and re-relaxes the `SpatialFactorGraph`.
* **Single-Command Pipeline**:
  `python isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py --mode auto_heal --env_name <env_name>`

## 6. Grasp Affordance, Contact Dynamics & Parallel Data Science Flywheel
* **Beyond Spatial Placement**: In addition to spatial reach and camera line-of-sight, organic/spherical objects (e.g. `apple_01_objaverse_robolab`) require tactile contact compliance and friction (`physics_material: friction >= 0.8`). The 2-finger parallel Franka gripper experiences rotational slip against spherical curvatures if approached without top-down alignment.
* **Parallel Simulation Scalability (`--num_envs N`)**: GPU tensorized execution allows simulating $N = 4, 16, 32, 64$ parallel environments concurrently ($32\times$ data collection speedup).
* **Data Science Diagnostic Flywheel**: When local compute is constrained for full foundation model fine-tuning, parallel trajectory generation provides the rich dataset required for offline data science (trajectory clustering, contact affordance heatmaps, sub-goal failure mode classification).
## 7. Statistical Diagnostic Methodology (Empirical Case Study N=65)
* **Markov Progression Funnel**:
  * Stage 0 (Settled): $65/65$ ($100\%$).
  * Stage 1 (Lifted off Table): $56/65$ ($86.2\%$) — proves perception, visual line-of-sight, and reach are solved.
  * Stage 2 (Placed in Receptacle): $8/65$ ($12.3\%$) — conversion from Lift $\to$ Place is only $14.3\%$ ($8/56$).
* **Chi-Square Test of Stage Independence**: $\chi^2 = 59.51,\; p = 1.22 \times 10^{-14}$. Proves failure is overwhelmingly localized to the in-flight transport and release phase, not the approach.
* **Grasp Decisiveness (Mann-Whitney U Test)**: Clean, prompt grasps ($< 300\text{ steps}$, median $293$) correlate with higher success vs delayed fumbling grasps (median $417\text{ steps}$).
* **In-Flight Survival Holding Time**: Failed lifted episodes held the apple in the air for an average of $448.9\text{ steps}$ ($9.0\text{ s}$) before rotational slip or time-out.

## 8. Realistic Policy/Controller Remediation & Graph Causal Memory
* **Sim-to-Real Invariant**: Never artificially inflate USD `physics_material` friction to force simulation success. In physical reality, fruit friction cannot be altered. Remediation must fix the controller, policy execution, and inference dynamics.
* **Valid Remediation Knobs**:
  1. *Receding Horizon Control*: Halve `action_chunk_length` to $16$ (or $8$) to enable $6 - 12\text{ Hz}$ closed-loop replanning and active slip correction.
  2. *Temporal Smoothing (EMA)*: Eliminates joint acceleration jerks ($\ddot{q}$) at chunk boundaries, reducing inertial flinging forces ($F = m \cdot a$).
  3. *Binary Gripper Squeeze Bias*: Snap continuous gripper predictions $> 0.5$ to $1.0$ (full rated motor clamping torque), maximizing normal force $F_N$.
  4. *Diffusion Steps*: Increase denoising steps (16–32) for low-variance trajectory synthesis.
* **Active Inference Auto-Heal Integration**:
  * `EvaluationDiagnosticOracle` parses `episode_results_rank*.jsonl`.
  * If $\text{Lift Rate} \ge 50\%$ and $\text{Conversion Rate} < 35\%$, it classifies `in_flight_slip_inertia` (Severity: 0.92) and patches `action_chunk_length = 16`.
* **Causal Knowledge Graph (Neo4j LPG + RDF-star)**:
  * Records `EvaluationRun` metrics (`lift_rate`, `conversion_rate`, $\chi^2$ p-value) and links versions via `(v2)-[:REMEDIATED_FROM {defect: 'in_flight_slip_inertia', patch: 'action_chunk_length=16'}]->(v1)`.
  * Forms a persistent empirical memory of which control parameters stabilize grasps for given object geometries.

## 9. False Positive Diagnostics & Codebase Containment Fix
* **Discrepancy Discovered**: Visual inspection in Omniverse Kit viewport (`--viz kit`) revealed that raw contact sensor telemetry (`object_on_destination`) logged false successes whenever an object grazed or bounced off the *exterior rim/base* of a receptacle.
* **Architectural Patch**: In `isaaclab_arena/tasks/pick_and_place_task.py`:
  1. Container auto-guarding sets default `max_separation = [0.12, 0.12, 0.15]` for all receptacle destinations (`bin`, `bowl`, `box`, `basket`).
  2. `objects_in_proximity` is formally added to `predicate_groups` in `get_progress_objectives`, guaranteeing that success requires both physical contact AND spatial centroid containment inside the cavity volume.

## 10. Scenario B1 (`droid_tomato_soup_to_blue_bin`) State
* **v1 Generated**: `tomato_soup_can_ycb_robolab` in `front_right`, `bin_b03_vomp_robolab` in `front_left`. 1 iteration, 0 errors.
* **Initial Visual Findings**:
  * Fast grasp acquisition ($122\text{ steps}$ vs $417\text{ steps}$ for apple) due to planar jaw surface alignment on vertical cylinder.
  * Rollouts timed out at 1000 steps ($20.0\text{ s}$) before completing place.
* **v2 Healed Configuration**:
  * Added `episode_length_s: 40.0` (2000 steps horizon) to allow full approach-lift-transfer-place execution.
  * Configured `max_separation: [0.15, 0.15, 0.15]`.
  * Policy instruction simplified to direct verb form: `"pick up the tomato soup can and place it into the blue bin"`.

## 12. Scenario B1 (`droid_tomato_soup_to_blue_bin`) Empirical Benchmark Results (N=50)
* **Statistical Funnel Breakdown**:
  * **Stage 0 (Settled)**: $50/50$ ($100.0\%$)
  * **Stage 1 (Lifted)**: $47/50$ ($94.0\%$) — confirms fast, reliable grasp acquisition on cylinder geometry (Median grasp step: $143$).
  * **Stage 2 (Placed / Success)**: $23/50$ ($46.0\%$) — strict centroid proximity inside receptacle cavity.
  * **Conversion Rate ($\text{Lift} \to \text{Place}$)**: $23/47$ ($48.9\%$).
  * **Temporal Dynamics**: Median place step: $370$ ($7.4\text{ s}$).
* **Comparison vs Organic/Spherical Asset (`apple_01`)**:
  * Tomato soup can Lift Rate ($94.0\%$) is significantly higher than Apple ($86.2\%$), with virtually no initial approach failures.
  * Conversion Rate ($48.9\%$) is $>3.4\times$ higher than baseline apple ($14.3\%$), confirming planar parallel gripper alignment against cylindrical faces drastically reduces rotational slip during high-acceleration transfer maneuvers.

## 14. Scenario B1 (`droid_tomato_soup_to_blue_bin`) v3 Evaluation Results (N=52)
* **Statistical Funnel Breakdown**:
  * **Stage 0 (Settled)**: $52/52$ ($100.0\%$)
  * **Stage 1 (Lifted)**: $44/52$ ($84.6\%$) — Median grasp step: $142$ ($2.8\text{ s}$).
  * **Stage 2 (Placed / Success)**: $23/52$ ($44.2\%$ strict proximity, $48.1\%$ ledger score).
  * **Conversion Rate ($\text{Lift} \to \text{Place}$)**: $23/44$ ($52.3\%$) — improvement over v2 ($48.9\%$) and $>3.6\times$ over baseline apple ($14.3\%$).
  * **Temporal Dynamics Acceleration**: Median place step dropped from $370\text{ steps}$ ($7.4\text{ s}$) in v2 down to **$226\text{ steps}$ ($4.5\text{ s}$)** in v3 ($39\%$ faster trajectory execution).
## 15. Hybrid Deterministic & LLM-Assisted Auto-Healing Architecture & v4 Synthesis
* **Architecture Implementation**:
  * Added `--healing_mode {hybrid, deterministic, llm}` to `environment_generation_runner.py` (defaults to `hybrid`).
  * **Option A (Deterministic Statistical & Spatial Oracle)**:
    * Analyzes empirical Markov stage funnels (Lift vs Conversion).
    * Defect threshold tuned (`lift >= 50% and conversion < 75%`) to detect in-flight rotational slippage and open-loop inertial drift.
    * Automatically applies receding horizon chunk compression (`action_chunk_length: 16 -> 8`).
  * **Option B (Generative LLM Reasoning via OpenRouter/Gemini/OpenAI)**:
    * Automatically activated in `llm` mode or as a fallback in `hybrid` mode when failures cannot be resolved by standard deterministic rules.
## 16. Scenario B1 (`droid_tomato_soup_to_blue_bin`) v4 Empirical Benchmark (N=42) & Receding Horizon Trade-offs
* **Statistical Funnel Results**:
  * **Stage 0 (Settled)**: $42/42$ ($100.0\%$)
  * **Stage 1 (Lifted)**: $37/42$ ($88.1\%$)
  * **Stage 2 (Placed / Success)**: $6/42$ ($14.3\%$)
  * **Conversion Rate ($\text{Lift} \to \text{Place}$)**: $6/37$ ($16.2\%$)
  * **Median Execution Speed**: Grasp step: $240$, Place step: $614$ ($12.3\text{ s}$).
## 17. Scenario B4 (`droid_spam_can_to_grey_bin`) Empirical Benchmark Results (N=70)
* **Statistical Funnel Breakdown**:
  * **Stage 0 (Settled)**: $70/70$ ($100.0\%$)
  * **Stage 1 (Lifted)**: $68/70$ ($97.1\%$) — Median grasp step: $175$ ($3.5\text{ s}$).
  * **Stage 2 (Placed / Success)**: $18/70$ ($25.7\%$) — Median place step: $415$ ($8.3\text{ s}$).
  * **Conversion Rate ($\text{Lift} \to \text{Place}$)**: $18/68$ ($26.5\%$).
* **Auto-Heal Triggered (`v1` -> `v2`)**:
  * The automated oracle detected the high-lift ($97.1\%$) with lower conversion ($26.5\%$) and generated `v2` remediation snapshot in `generated_envs/droid_spam_can_to_grey_bin/v2/`.
  * Lineages updated across `lineage.json`, `lineage.ttl`, `README.md`, and Neo4j.


## 18. Unitree G1 Humanoid Tabletop Manipulation (`GN1x-Tuned-Arena-G1-Static-PickNPlace`) & VLM-in-the-Loop Failure Autopsy
* **Headless-First Diagnostic Principle**:
  * Run simulation evaluation completely headless across parallel GPU environments (`--num_envs 4`, `--num_steps 2000`) for maximum throughput (~15–20 steps/s).
  * Do not rely on persistent GUI viewports. If a milestone stalls or drops to 0%, trigger a multi-frame trajectory rollout (`render_policy_trajectory.py`) and submit keyframes to an LLM/VLM reasoning engine (Anthropic Claude 3.5 Sonnet / Claude 4.5 via OpenRouter).
* **Embodiment & Action Space Contract**:
  * The pre-trained checkpoint `nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace` produces **50-dimensional joint actions** (`action_dim: 50`).
  * Testing `g1_wbc_agile_pink` fails (`ValueError: Invalid action shape, expected: 23, received: 50` and `assert self.num_envs == 1`).
  * The correct embodiment is **`g1_wbc_agile_joint`** (paired with AGILE lower-body WBC balancing and upper-body joint commands).
  * Mandatory parameters: `initial_joint_pos: G1_STATIC_OPEN_ARM_JOINT_POS` (pre-clearing arms away from torso), high-friction finger physics (`static_friction=6.0`, `dynamic_friction=5.0`), and `action_chunk_length: 40`.
* **Empirical Proof on Reference Training Setup**:
  * Evaluating `galileo_g1_static_pick_and_place` on the exact same policy server (`127.0.0.1:5557`) achieved **100% success (`success_rate: 1.0, object_moved_rate: 1.0`)**, proving server health, joint mapping, and execution fidelity.
* **Root-Cause of High Tabletop Failure (`v6`)**:
  * **Vertical Out-Of-Distribution Gap**: In training, the apple was on a low warehouse shelf at $Z = -0.8015\text{ m}$ below the pelvis. On `maple_table`, the tabletop is at $Z = -0.0126\text{ m}$ below the pelvis ($\Delta Z = 80\text{ cm}$ mismatch).
  * **Kinematic Trajectory Tracking**: The policy reaches forward between steps 0–30, then attempts to plunge downward toward knee level ($Z \approx 0.69\text{ m}$), where it encounters the table plane and aborts/retreats.
  * **Visual Domain Shift**: Head camera views light-colored wood grain filling the viewport instead of dark metal warehouse racks.
* **Strategic Roadmap**:
  * Plan 1 (Production Tabletop): Collect 50–100 teleoperated demonstrations on `maple_table` at chest height and fine-tune GR00T N1.7.
  * Plan 2 (Zero-Shot Baseline): Lower the table/support surface so $\Delta Z \approx -0.80\text{ m}$ relative to the pelvis.
  * Plan 3 (Algorithmic Bridge): Implement vertical Cartesian delta compensation in the policy wrapper.


## 19. Spatial Forcing Scale-Invariance Literature Audit (2026-09) — Why Cosine Alignment Cannot Inject Metric Range
* **Verdict**: Leading hypothesis, not yet a finding. A scale-invariant cosine alignment loss very probably cannot close a systematic absolute range error, via two stacking removals of metric scale. Removal 1 is a code fact; Removal 2 is an architectural argument that our own measurement partly undercuts (the `focal/300` factorisation does not actually produce metric depth — plan §2.5b), so the settling experiment below is still owed.
* **Removal 1 — the loss discards magnitude**: Both SF reference implementations (`openvla-SF/prismatic/models/projectors.py`, `openpi-SF/src/openpi/models_pytorch/projectors.py`) compute `1 - cos` on `F.normalize`d vectors, and cosine is the **only** implemented loss (`else: raise NotImplementedError`). Rescaling the teacher leaves the loss bit-identical.
* **Removal 2 — the teacher has no metres**:
  * **VGGT** (arXiv:2503.11651, §3.4) normalises GT by "the average Euclidean distance of all 3D points in the point map $P$ to the origin", applied to camera translations, point map **and** depth map. Critically: "**unlike [DUSt3R], we do not apply such normalization to the predictions** ... instead, we force it to learn the normalization" — the scale-blindness is baked into the learned function, not invertible post-hoc.
  * **`DA3METRIC-LARGE` is affected too**: its metric-ness is a scalar *outside* the network — `external_dependencies/depth-anything-3/src/depth_anything_3/utils/alignment.py:118`, `depth * (focal_length / 300.0)`, applied to `metric_output.depth` **after** the DPT head. `da3metric-large.yaml` is a plain `DinoV2` + `DPT(output_dim: 1)` with **no camera head**. So layer-23 features are canonical-space, focal-normalised: metres live in a post-hoc multiply, never in the representation.
  * **Consequence**: "metric teacher" is a far weaker differentiator from `DA3MONO-LARGE` than originally assumed. The `DA3MONO-LARGE` contrast arm is the right detector.
* **Third strike (SF-specific)**: SF slices `agg_vggt_hidden[:, :, patch_start_idx:, :]`, keeping only patch tokens and **discarding VGGT's camera token** (which carries predicted intrinsics). Evo-0 by contrast keeps camera + register + 3D tokens.
* **Precision caveat on the argument**: cosine invariance alone proves only that the *norm* $\lVert f_i \rVert$ is discarded — one scalar per token. Absolute depth is also one scalar, so it *could* in principle live in the direction of a 1024-D vector. Useful decomposition (own derivation, not a citable result): $\lVert f_T - f_S \rVert^2 = (\lVert f_T \rVert - \lVert f_S \rVert)^2 + 2\lVert f_T \rVert \lVert f_S \rVert (1 - \cos\theta)$ — cosine penalises only the second term. **Cheap settling experiment**: run the `probe_depth_readout.py` ridge probe on **L2-normalised** vs. unnormalised layer-23 features. Survives $\Rightarrow$ direction carries scale; collapses $\Rightarrow$ magnitude does.
* **What SF actually reports (explicit negatives, full PDF read)**:
  * Ablations are only: target representation (SigLIP 94.0 / DINOv2 94.1 / VGGT-no-PE 94.7 / VGGT 96.9), aligned layer (1/8/16/24/32, best **24**), train iters, data fraction; plus $\alpha$ (0 / 0.02 / 0.1 / **0.5** / 2.5 / 12.5).
  * **No** relative-vs-metric teacher ablation. **No** loss-form (cosine vs MSE) ablation. **No** claim to fix absolute range — "metric"/"absolute" absent from its motivation.
  * **Zero cm/mm anywhere**: `\bcm\b` 0 hits, `\bmm\b` 0 hits, "positional error" 0 hits. Depth probing (Fig. 3) is **purely qualitative** rendered depth maps, probed with an affine-invariant DPT head. All metrics are success rate.
  * Its one height task ("place green block", height variation) is $67.5 \to 85.0\%$ SR — *relative* placement height, smallest relative gain, highest baseline.
* **Upstream loss-form gap**: REPA (arXiv:2410.06940) compares only NT-Xent vs negative cosine — **both scale-invariant**, never MSE. GLaD (arXiv:2512.09619) independently uses unnormalised squared $L_2$ against the same frozen VGGT and cites SF without ablating against it. **No paper runs cosine-vs-$L_2$ with a fixed teacher, and no paper critiques SF for discarding metric scale.**
* **Strongest empirical prior against SF here** — 3D-Mix (arXiv:2603.24393) nine-scheme pilot on Qwen3-VL-4B, SIMPLER avg, base $=57.81$: **3D-Tokens** (cosine align on a `<|vggt|>` token, VGGT-free at inference) $=56.25$ — **below base**; **Spatial Forcing** $=58.85$ (**+1.04**); Concat Fusion $=60.42$; **GatedFusion/3D-Mix** $=68.23$ (+10.42, VGGT-1B live at inference). Both zero-inference-cost schemes are the weakest non-catastrophic ones. AE Fusion (3.13) and Visual Fusion (4.69) *destroy* the policy — "add VGGT" is violently sensitive to *how*. Repo 404s.

## 20. Metric-Range Remedies for RGB-Only VLAs — Ranked, with Inference Cost
* **The architectural split is the key finding**: depth regression *through the shared VLM backbone* destabilises; depth regression in a **separate branch** works.
  * **Against a shared-backbone head**: GLaD — "explicit geometry supervision (predicting depth maps) ... **caused training divergence due to conflicting objectives**" (one line, no numbers). QDepth-VLA — pixel-wise regression instead of quantised tokens costs **$-3.9\%$**; removing the **depth expert** costs $-8.5\%$ (largest drop, so the *branch* matters more than the target format). BridgeVLA — swapping its heatmap head for direct MSE position regression craters RLBench **$88.2 \to 31.4\%$**.
  * **For a separate branch**: DepthVLA **+16.0** on Simpler over its own $\pi_0$ (58.8 $\to$ 74.8); QDepth-VLA's expert; MVUCF.
* **Metric scale specifically is the load-bearing ingredient** — OASIS (arXiv:2605.25829), matched-backbone, LIBERO-Long: full **95.2%**, w/o Metric **91.8%**, w/ Rel. (Depth Anything V2) **92.0%**. Quote: "**Metric scale, not depth in general, is what helps**." Also names our teacher: "Unlike Depth Anything V2 and VGGT, which produce **normalized relative depth maps**, Depth Anything 3 estimates metric depth." *Caveat: metric depth is a frozen input feature there, not an auxiliary regression target.* Its richness ladder shows **2D image-plane supervision buys ~nothing** (89.5 no-traj $\to$ 90.7 2D $\to$ 92.3 3D $\to$ 93.2 world-frame $\to$ 95.2).
* **Ranked shortlist** (fit to "absolute metric range, RGB-only at inference"):
  1. **MVUCF-style training-only metric-depth head** (arXiv:2608.01826) — Softplus head regressing **metres** (valid 0.05–5.0 m) at **GR00T-N1.6 layer 15**, cross-view correspondence, **all heads deleted at deployment**. Cost: **zero** ("no extra inference FLOPs"; "camera calibration is used only to construct training targets"). **Only paper in ~25 surveyed reporting cm-level accuracy**: depth-probe MAE $4.9 \to 0.44\text{ cm}$; within 2 cm $44\% \to 97\%$. Freezes layers 0–7; **layer 12 "degraded token-level separation after training"** — directly relevant to the `backbone_layer_{6,9,12}` sweep. No code.
  2. **Metric depth as frozen input feature** (OASIS) — cost: depth-model forward. No code.
  3. **One-shot per-setup metric calibration** (MOMA, arXiv:2506.17110, IROS 2025) — scale-shift-**rotation** fit from sparse GT depth, once at calibration; sensor disabled after. ~ms/frame. Numbers mirror ours exactly: DAM RMSE $12.3 \to 1.6\text{ cm}$; Metric3Dv2 $32.8 \to 2.0\text{ cm}$; grasp SR 82% (SSRA) vs 72% (GSSA) vs 62% (LWLR).
  4. **3D-Mix gated fusion** — +10.42 but **VGGT-1B live**; teacher scale-normalised, so unlikely to fix range.
  5. **DepthVLA** (arXiv:2510.13375) — depth expert in a mixture-of-transformers, **no sensor**, "latency marginally". Loss is Eigen scale-invariant log at **$\lambda = 0.5$** (i.e. *partially* scale-aware) against **metric** pseudo-labels (UniDepthV2 + DAv2). No code found.
  6. **QDepth-VLA** (arXiv:2510.14836, AAMAS 2026) — VQ-VAE depth tokens + cross-entropy, **MIT**, +12.2% params, no sensor. **Relative depth only** (Video-Depth-Anything). Concedes: "**relative depth lacks absolute positional encoding necessary for stable control**."
  7. **Heatmap/voxel head over a metric grid** — BridgeVLA (Apache-2.0), PerAct (Apache-2.0, 1 cm voxels).
  8. **Object-centric residual RL** (arXiv:2606.18953) on GR00T-N1.5 — sidesteps perception; Table 6 lists verbatim "**Hovers above cube, misses grasp** $\to$ Residual Fix: **Pushes end-effector down to the cube**."
  9. Depth-at-inference family (**ruled out, no depth sensor**): SpatialBot (MIT, true mm), PointVLA (no code), GeoVLA (MIT), 3D-CAVLA (no licence), DP3/iDP3 (MIT), RVT/RVT-2 (**non-commercial**).
  10. SpatialVLA / RoboPoint / 3D-VLA — don't target absolute scale. SpatialVLA runs ZoeDepth **in-graph** but **requires intrinsics** (ships one hardcoded matrix, fx=fy=623.588) and explicitly disclaims scale: Ego3D PE "renders precise scale **unnecessary**". RoboPoint (Apache-2.0) needs depth *downstream* to lift 2D$\to$3D.
* **Recommendation**: do **not** distil a foundation-model teacher's metric scale. Regress **sim GT metric depth in metres** from a **separate small branch** (not a backbone head), with a scale-*aware* loss (Eigen log at low $\lambda$, or a binned/heatmap readout over a metric range given BridgeVLA/PerAct), deleted at deployment MVUCF-style. Keep `align` only as a *relative-structure* regulariser if the arms justify it. Replacing cosine with unnormalised $L_2$ against DA3METRIC layer-23 transfers feature magnitude, **not** metres.
* **Our decisive advantage — perfect metric GT**: every objection SF and QDepth-VLA raise against depth supervision ("sensor noise, hardware heterogeneity, incomplete depth coverage", "insufficient spatial–temporal consistency ... introducing substantial noise") is about **pseudo-labels**, and is void in Isaac Lab. G³VLA (arXiv:2606.24472) prices it: its monocular teacher predicted median depth **3.535 m against simulator GT median 0.027 m — a $132.4\times$ ratio** — concluding "**simulator ground-truth depth provides aligned point-map supervision and improves success rate**." **Corrected against our own measurement (2026-09-05)**: the earlier "24.6 cm / $1.48\times$" figure is **retracted** — it paired dataset RGB against a default-pose render, and applied DA3's `focal/300` transform, which *doubles* the error here. On a properly paired frame, table region: raw $1.568\times$ / 29.1 cm; with `focal/300` $2.566\times$ / 79.5 cm; **one fitted global scale $1.027\times$ / 1.64 cm** — i.e. inside the 7 cm gap once anchored. The canonical-focal units explanation is refuted (feeding at $f_\text{eff}\approx300$ gives $2.358\times$), so 0.655 is a fitted anchor, not a formula. See `geometry_supervision_evidence_repair_plan.md` §2.5b.
* **Note**: most "depth-aux" VLAs throw scale away anyway — DreamVLA uses a **scale-normalized MSE** that explicitly "removes the global scale ambiguity ... while ignoring any arbitrary global scale shift."

## 21. Two Confounds That Outrank the Loss Question (G1 Tabletop 7 cm Gap)
* **Confound 1 — the training corpus has ZERO spatial variation**: `APPLE_SPAWN_XY_RANGE_M = 0.0`, while evaluation uses a $20 \times 22\text{ cm}$ placement range. **No perception-side auxiliary loss can help**: there is nothing for a spatial objective to bind to, and a constant scene at constant table height cannot teach range-from-vision. LIBERO-PRO (arXiv:2510.03827) prices this failure mode — under **Position Perturbation**: **GR00T-N1.6 = 28.1**, $\pi_0$ = 5.9, OpenVLA = **0.0**, all from $>0.9$ on stock LIBERO. **Adding spawn variation is cheaper than any remedy in §20 and is a prerequisite for measuring any of them.**
* **Confound 2 — "irreducible monocular range error" may be mis-attributed** *(inference; the debug record concludes otherwise)*: the 7 cm is a **signed, systematic** offset under an essentially constant scene. Monocular scale ambiguity is *multiplicative* and should co-vary with range; a constant bias at constant table height is equally consistent with a calibration/posture mismatch — and posture, pelvis height, stance and camera pitch are already known to be **coupled through the WBC**, with F1 failing in the *opposite* sign to the hypothesis.
  * Supporting: VLATest (arXiv:2409.12894) — VLAs pass only **34.0%** of cases under mutated camera poses. "Do You Know Where Your Camera Is?" (arXiv:2510.02268) — policies "**infer camera pose using visual cues from static backgrounds** in fixed scenes" and "this shortcut collapses" — precisely a fixed-scene corpus evaluated at a shifted pose.
  * **GR00T N1's only spatial auxiliary is a pure image-plane bearing loss** (normalised bbox centre $x, y$ — **no range term**), strikingly consistent with "bearing good, range bad".
  * **Cheap discriminator** (no paper does this decomposition): a latency-caused offset scales with horizon $\times$ descent speed; a perception/calibration-caused one does not. The $16 \to 8 \to 4$ plateau (4.9 cm then 0.7 cm) already says the residual is *not* staleness, but does **not** separate perception from calibration.
* **Closest published match to our symptom**: arXiv:2605.28736 (suture following, ACT/DP/SmolVLA/$\pi_0$) decomposes error into **lateral** vs **depth** and finds "**depth errors are the dominant failure mode**" (20–35% of episodes) vs lateral (0–25%) — and that this is "**bottlenecked by the available perceptual signal rather than by demonstration count**" (i.e. more demos will not fix it). Camera ablation separates the axes cleanly: on-arm-only spikes depth errors to 40–65%; side-cam-only shifts mass to lateral 30–45%.

## 22. Literature Absences Worth Knowing (verified negatives, 2026-09)
* **No paper decomposes VLA reach error into latency vs perception vs calibration.** RTC (arXiv:2506.07339) reports success/throughput only; its only decomposition tables are *compute* latency by component. It blames chunk **discontinuity**, not bias.
* **No paper reports a signed per-axis $(x/y/z)$ end-effector bias in cm for a VLA.** Closest: arXiv:2511.11298 names "small Z-offset ... closes above surface" but unsigned.
* **No arXiv technical report exists for GR00T N1.5 / N1.6 / N1.7**, and no NVIDIA document reports a vertical bias. GR00T N1 (arXiv:2503.14734) contains no failure analysis at all.
* **FLARE is entirely absent from our vendored `submodules/Isaac-GR00T`** (`grep -rn -i flare` returns only an unrelated CSS hit in `external_dependencies/depth-anything-3`). There is **no alignment infrastructure to repurpose**; the geometry path is our own `gr00t/model/modules/geometry_conditioning.py`.
* **No learned residual *calibration* correction for a learned policy** — residual RL corrects in action space, not calibration space.
* **No auxiliary-loss experiment that regresses metric depth in metres and compares against scale-normalised depth as the target.** OASIS varies a frozen input; QDepth-VLA and DreamVLA use relative/normalised targets only. **This is exactly our hypothesis, and it is unpublished.**
* **Licence corrections**:
  * **VGGT code** is a bespoke Meta "Research Materials" licence (GitHub API `NOASSERTION`); the word "commercial" appears **nowhere** in it, but its incorporated AUP bars "operation of ... **heavy machinery**" — worth a legal read for robotics regardless. The binding constraint is that **`facebook/VGGT-1B` weights are CC-BY-NC-4.0**. Existing §8.2 treatment is correct.
  * **`UniDepthV2`** is architecturally ideal as a metric teacher (metric, GT-intrinsics injectable, uncertainty output) but is **CC BY-NC-4.0 code with untagged weights** — belongs on the ruled-out list beside VGGT.
  * **Spatial Forcing's own repo is MIT** (`github.com/OpenHelix-Team/Spatial-Forcing`, ICLR 2026). **QDepth-VLA is MIT.** 3D-Mix, MVUCF, G³VLA, DepthVLA, OASIS, PointVLA: **no code published**.
* **Not verified — do not cite without checking**: OpenReview for SF (`euMVC1DO4k`) is bot-gated; **reviewer discussion of scale-invariance could not be read** and may be worth a signed-in look. Search-level only: Evo-0 (2507.00416), MetricAnything (2601.22054), AugVLA-3D (2602.10698), Pose-VLA (2602.19710), CamVLA (2607.05396), grounded-3D-point action-head injection (2606.27663, PDF would not decode), invariant-representation limits (2012.10713).

## 23. Cross-Cutting Conclusions & Plan Sync (2026-09-06)
* **Make range OBSERVABLE before trying to infer it — but a second camera is NOT cheap** *(corrected 2026-09-06; an earlier version of this bullet claimed it was)*. §21's camera ablation (arXiv:2605.28736) shows range and bearing are carried by *different baselines* — removing the side camera spikes depth errors to **40–65%**; removing the on-arm camera shifts failure mass into **lateral** error (30–45%) instead. The direction is right, the costing was wrong:
  * **The error to avoid**: `pov_cam_name_sim` accepts a *list* and the DROID path already runs two views (`["external_camera_rgb", "wrist_camera_rgb"]`), which looks like the plumbing is free. That is the **policy config**; the binding constraint is the **rig**. **`G1CameraCfg` exposes exactly one camera** (`robot_head_cam`) and the corpus recorded exactly one view (`observation.images.ego_view`), so a genuine spatial baseline costs an embodiment change **plus** a 251-episode re-record. It folds into the re-record cost rather than competing with it.
  * **What IS cheap and already built**: **temporal** parallax — `g1_sim_wbc_data_gr00t_n_1_7_parallax_config.py` stacks the same camera at `delta_indices [-8, 0]`, and the `parallax` / `align_parallax` arms are already wired in the launcher. No new sensor, no re-record. Weaker than triangulation (the baseline is only whatever the head moved in 8 frames, and in a corpus this static that may be ~nothing — the ~1 cm `obj_z` spread is a warning), so **measure the effective baseline before trusting a null result**.
  * If a re-record is funded anyway, add the second camera **in the same pass** — marginal cost is small there.
* **More data alone will not close a range gap.** Depth-error rate in arXiv:2605.28736 is **flat from 40 to 160 episodes per task** — "bottlenecked by the available perceptual signal rather than by demonstration count." Spatial variation (§21 confound 1) is *necessary* for a spatial objective to bind, but not *sufficient* if the error is perceptual-absolute.
* **The magnitude-preserving alignment variant is in use and unmeasured against ours.** GLaD applies **unnormalised squared $L_2$** at the same LLM-hidden-state site against the same frozen VGGT and reports **94.1%** LIBERO avg — without ever ablating against cosine. Upstream SF implements cosine *only* (`else: raise NotImplementedError`), and REPA compared only NT-Xent vs cosine (**both** scale-invariant). So cosine-vs-$L_2$ is unablated everywhere, not just in SF.
* **$\lambda$ is a design decision, not a default** (for any scale-aware depth objective): DepthVLA succeeds at Eigen log **$\lambda = 0.5$** with a *separate expert* (+16.0 Simpler over its own $\pi_0$); DreamVLA neutralises scale **on purpose** ("removes the global scale ambiguity ... ignoring any arbitrary global scale shift"); GLaD **diverges outright** with a backbone head. At $\lambda = 1$ the loss is fully scale-invariant and degenerates back into the §19 problem.
* **A published remedy exists for our literal symptom, on our base family.** arXiv:2606.18953 (GR00T-N1.5): object-centric residual trained **only in sim** against the frozen base's own failures, transferring zero-shot because it "observes object pose, a representation invariant across domains" — i.e. **it never looks at an image**, so it is immune to both the frozen-render bug and the memorisation diagnosis. Cheaper than a depth branch and orthogonal to it. The existing `cartesian_vertical_offset_adapter` is the zeroth-order version; if a constant offset closes the gap, the residual is unnecessary.
* **"No metres" means "no absolute ANCHOR", not "no usable geometry".** Collapsing that distinction is how the old plan talked itself into selecting a teacher on the wrong axis. The measurements cut against over-arguing scale-blindness: every teacher resolves the apple's relief with the correct **sign**, `DA3METRIC-LARGE` reproduces the true $+6.8\%$-of-range ratio to within **1.3x**, and **one fitted global scale reaches 1.64 cm at 0.5 m** — inside the 7 cm target. What is missing is a single global scalar, and it is fittable (RANSAC scale-shift against the table plane, once per camera pose).
* **A claim of mine that did NOT survive contact with the code**: the SF "camera-token discard" is real upstream (`agg_vggt_hidden[:, :, patch_start_idx:, :]` drops VGGT's intrinsics-bearing camera token) but is **void for our teacher** — `DA3METRIC-LARGE` is monocular and emits no camera token, so there is nothing to discard. It is *not* a third removal of metric scale in our setup; it only explains why **SF's own published results are uninformative either way about metric transfer**. Removal count stays at **two**.
* **Plan sync**: landed in `plans/geometry_supervision_evidence_repair_plan.md` **v2.2** (2026-09-06) — §2.6 loss recipes, **§2.8** (range/bearing corroboration, with the second-camera claim retracted in place), **§2.9** (verified absences), **W9** (residual), risks 6–7, open decision 5. W3b was rewritten (by another pass) to lead with temporal parallax; §2.4's "third removal" and §2.8's "cheapest remedy" were **both retracted**. No v2 finding was retracted.

## 24. G1 Reinforcement Learning: Operational Space Control (7-D Diff-IK), WBC Balance & Multi-Keypoint Guidance (2026-09-08)
* **Curse of Dimensionality Solved**: Raw 50-D joint action exploration ($O(\epsilon^{50})$) suffered catastrophic exploration collapse (knuckle twitching/swatting). Reduced policy action space to $\mathbb{R}^7$: $\mathbf{a}_t = [\Delta x, \Delta y, \Delta z, \Delta \text{roll}, \Delta \text{pitch}, \Delta \text{yaw}, g_{\text{finger}}]$.
* **Decoupled WBC Diff-IK Action Architecture (`G1DecoupledWBCDiffIKAction`)**:
  * Diff-IK operates in parallel on GPU using PhysX link Jacobians and Damped Least Squares (DLS: $\mathbf{J}^\dagger = \mathbf{J}^T (\mathbf{J}\mathbf{J}^T + \lambda^2 \mathbf{I})^{-1}$).
  * **Floating-Base Jacobian Slicing Rule**: In Isaac Lab, floating-base articulations reserve columns $0..5$ for base 6-DoF. Joint columns start at `num_base_dofs = 6`. Correct slice: `[idx + num_base_dofs for idx in arm_joint_ids]`.
  * **Standing Balance**: Unitree AGILE Whole-Body Controller (WBC) dynamically manages 12 leg joints to maintain 0.75m pelvis height and bipedal balance, completely decoupled from arm task-space control.
  * **Finger Synergy**: 1D scalar $g \in [-1, 1]$ smoothly actuates all 7 left hand finger joints (`left_hand_thumb_*`, `left_hand_index_*`, `left_hand_middle_*`).
* **Finger Grasp Polarity Correction**: G1 hand URDF requires negative joint positions to curl index/middle fingers (`-pos / 1.0`), while thumb curls positive (`pos / 0.7`). Previous reward penalised closing the hand; corrected in `finger_grasp_enclosure`.
* **Multi-Keypoint Geometric Guidance (`multi_keypoint_grasp_guidance`)**: Exponential guidance reward tracking distances between 4 hand link keypoints (`left_wrist_yaw_link`, `left_hand_thumb_2_link`, `left_hand_index_1_link`, `left_hand_middle_1_link`) and the target object, simultaneously solving position, approach orientation, and grasp aperture.
* **Empirical Validation (150 Iterations / 230k Steps on RTX PRO 6000 Blackwell)**:
  * Mean total reward surged **0.67 $\to$ 3.87 (+477%)**.
  * Mean episode length extended **24.0 $\to$ 73.3 steps**.
  * `finger_grasp_enclosure` reached **0.4287**, `approach_alignment` reached **0.1729**.
  * Checkpoint: `logs/rsl_rl/g1_diff_ik_7d_validation/2026-09-08_21-20-25/model_149.pt`.
  * Rollout evaluation (`policy_runner.py`): 100% standing stability (0 falls), 100% object moved rate, active finger enclosure.

## 25. Multi-Tier Arm Velocity Mitigation, EMA Smoothing, and Visual Rollout Validation (2026-09-08 / 2026-09-09)
* **Excessive Speed Mitigation & Kinematic Smoothing**:
  * Clamped maximum single-step Cartesian displacement: `scale_pos = 0.025m` ($2.5\,\text{cm}$) and `scale_rot = 0.08rad`, strictly capping maximum end-effector linear velocity to $\le 1.25\,\text{m/s}$ at $50\,\text{Hz}$.
  * Added EMA command low-pass filtering ($\alpha = 0.8$) in `G1DecoupledWBCDiffIKAction` to eliminate high-frequency action chatter.
  * Added `arm_joint_vel_l2` penalty (weight `-0.0005`) in `PickAndPlaceRewardCfg`.
  * Increased action rate penalty by 5x (`action_rate_l2 = -0.005`).
  * Fixed camera/replicator auto-initialization in `policy_runner.py` for `--record_viewport_video`.
* **Visual Evaluation Rollout**:
  * Recorded 300-step (6.0s) rollout (`outputs/2026-09-08_22-46-43/rl-video-step-0.mp4`).
  * 100% bipedal standing balance maintained by Unitree AGILE WBC throughout rollout.
  * Controlled Cartesian descent with palm downward over apple; zero ballistic swatting, zero knuckle collisions.
  * Hand hovers in pre-grasp enclosure directly over the target apple.
  * Committed in `5a39b3104f` on `dev/0.3.0-prerelease`.

## 26. Reverse Curriculum Architecture (Milestone M4) & Pre-Grasp / Lift Kinematics (2026-09-09)
* **Empirical Pre-Grasp Kinematics Extraction**:
  * Extracted from step 10 of rollout evaluation checkpoint `model_149.pt` where palm reached hover $1.7\,\text{cm}$ above apple:
    * `left_shoulder_pitch_joint`: -0.1038, `left_shoulder_roll_joint`: -0.0865, `left_shoulder_yaw_joint`: 0.2141
    * `left_elbow_joint`: 0.4491
    * `left_wrist_roll_joint`: 0.1850, `left_wrist_pitch_joint`: -0.0044, `left_wrist_yaw_joint`: 0.1924
* **Reverse Curriculum Event Terms (`pick_and_place_task_rl.py`)**:
  * `reset_robot_arm_reverse_curriculum`: Selects fraction `curriculum_ratio` (default $0.35$ in training) of resetting envs and writes arm joint angles to pre-grasp posture with zero velocity.
  * **Isaac Lab Joint Order Contract**: `robot.find_joints(joint_names)` defaults to sorting indices internally; must explicitly pass `preserve_order=True` when mapping dictionary values to index order.
  * `reset_object_reverse_curriculum`: Selects fraction `lift_curriculum_ratio` (default $0.15$ in training) and elevates the manipuland by `lift_height_offset = 0.025m`, training the policy directly on in-flight transport and release without having to explore the full reach-and-grasp sequence from scratch every episode.
* **Honest Evaluation Decoupling**:
  * In `g1_apple_to_plate_rl_environment.py`, curriculum ratios are dynamically zeroed when `rl_training_mode=False`.
  * Standalone evaluation runs (`policy_runner.py`) always test the policy from the canonical home posture without artificial reset assistance.

## 27. Reverse Curriculum Calibration, Stance Loading Dynamics, and Extended Training Convergence (Milestone M4) (2026-09-09)
* **Stance Transition vs Forward-Reaching Arm Coupling (Root Cause Diagnosis)**:
  * In initial curriculum testing, the G1 humanoid spawned in a 14 cm deep crouch ($Z = 0.0007\,\text{m}$), causing its forward outstretched arm during pre-grasp reset to dip down to $Z = -0.028\,\text{m}$ (10 cm into table surface) during the stance loading transient.
  * PhysX penetration forces pushed the hand down, causing table collisions and object scattering.
  * Extracted settled standing posture from physics rollout: Pelvis $Z = 0.1414\,\text{m}$, root pos `[-0.4896, 0.0, 0.1414]`, and lower-body leg angles `G1_SETTLED_LOWER_BODY_JOINT_POS`.
  * In [`g1_apple_to_plate_rl_environment.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena_environments/g1_apple_to_plate_rl_environment.py), bound `G1_SETTLED_LOWER_BODY_JOINT_POS` and initialized robot at settled standing root pose.
* **Mid-Air Spawning Depenetration Explosion (Root Cause Diagnosis)**:
  * Attempting to spawn rigid manipuland in mid-air (`lift_curriculum_ratio = 0.15`) without physical attachment or active grasping caused severe PhysX depenetration impulses against the robot fingers, catapulting the apple 7.25m into the air and triggering `object_dropped` at 98%.
  * Setting `lift_curriculum_ratio = 0.0` while retaining arm pre-grasp curriculum (`curriculum_ratio = 0.50`) eliminated object explosions completely, providing smooth, stable descent and grasp exploration.
* **Extended RL Training (250 Iterations / 384,000 Steps on RTX PRO 6000 Blackwell)**:
  * Run directory: `logs/rsl_rl/g1_diff_ik_curriculum_m4_standing/2026-09-09_01-31-26/`
  * Checkpoint: `model_249.pt`
  * Wall time: 391.63s (~6.5 minutes at ~960 steps/sec across 64 parallel PhysX environments).
  * **Mean Total Reward**: Surged to **16.63** (M1 $\to 0.82$, M3 $\to 3.87$, M4 $\to \mathbf{16.63}$ - a **+330%** jump over M3 and **+2380%** over M1).
  * **Mean Episode Length**: Reached **230.87 steps** (76% of episodes run to full 300-step horizon timeout; drop rate dropped from 98% to 24%).
  * **Finger Grasp Enclosure**: Reached **0.8096** (near complete finger flexion around apple).
  * **Approach Alignment**: Reached **0.3238**, Multi-Keypoint Guidance reached **0.5686**.
  * **Active Lifting Discovered**: `Episode_Reward/lifting_object: 0.0750`.
  * **Active Transport Discovered**: `Episode_Reward/transporting_object: 0.0212`.
* **Evaluation Rollout (`policy_runner.py`)**:
  * Zero falls, zero NaN actions, 100% standing balance across all 3 episodes (300 steps each).
  * Viewport video recorded (`outputs/2026-09-09_01-38-31/rl-video-step-0.mp4`): G1 stands stably at the table, reaches arm directly toward target apple, closes fingers with vertical posture, avoiding drop terminations.
  * Telemetry recorded (`eval_telemetry.ttl`, `episode_results_rank0.jsonl`).
  * Milestone M4 marked **COMPLETED**.
