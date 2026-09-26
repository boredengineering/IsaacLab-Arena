# P04-I03 — Source Review, Implementation Strategy and Actor–Critic Goals

- Reviewed: 2026-09-26
- Source baseline: `328045e90cb64d4e13a4fd9fa7b5ec584d401454`; the operator's revised I03 overview was an uncommitted change.
- Parent package: [03-full-scene-workflow.md](03-full-scene-workflow.md)
- Status: **PROPOSED — ALL GOALS UNISSUED. No application implementation or live trial was performed by this review.**
- Planning decision: the operator selected a separately budgeted fixed-candidate proof before the generated-scene trial. This selected a proposal, not execution authority.
- Main operation identity remains `p04-i03-full-scene-v1`.
- Proposed fixed-candidate operation: `p04-i03-fixed-scene-proof-v1`.

This document supplies the current implementation strategy and complete proposed goals. The overview's old contract example is not executable or a specification that code must be weakened to accept. Issuing one goal does not issue another goal. Do not paste this whole document as an execution request.

> [!IMPORTANT]
> **Devcontainer Named Volume & Path Invariant:**
> The repository operates inside a devcontainer mounted as a named volume. **Never hardcode absolute filesystem paths or `file:///` URIs in plans or documentation** (e.g. `file:///workspaces/...`). Always use repository-relative links (`../../../../...`) so paths resolve identically across host environments, devcontainers, editor extensions, and Git remotes.

## 1. Material findings remaining after the overview revision

The revision correctly separates implementation from proof, rejects uncertainty-driven arbitrary repair, and separates outcome claims. The following are still real implementation or specification gaps, not additional paperwork gates.

### R1 — Sharing a producer name does not preserve its semantics

[`scene_observation.py:31, 70–79, 163–175`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_observation.py#L31) pins evaluator v1 to `0.01 m/s` and `0.05 rad/s`; `scene.settled` takes one subject. The proposed contract instead supplies two subjects and claims the stricter final-five `0.001 m/s` / `0.01 rad/s` rule. Reusing v1 would either reject the request or establish the wrong scientific criterion. Keep old evaluator bytes/meaning intact; implement a versioned strict evaluator over the actual retained settling samples, with explicit subject coverage and strict comparisons.

### R2 — The revised visual codec loses the I02 result semantics

[`scene_observation.py:70–79, 344–386`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_observation.py#L70) admits one subject for visual v1 and consumes Boolean per-frame answers. I02's `visibility-v2` validates `visible`, `not_visible`, and `uncertain` for every frame/subject ([`:272–321`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_observation.py#L272-L321)). [`SplitScenePorts`](../../../../isaaclab_arena/agentic_environment_generation/workflow/split_scene_ports.py#L38) still uses the legacy evaluation path. Selecting v1 cannot prove the proposed two-subject uncertainty-aware assessment. Join the complete structured response into the real full-scene worker, retention, evidence projection and router; do not reuse the retained-only execution mode as a hidden second operation. `not_visible` is not itself a causal diagnosis of occlusion.

### R3 — The new shared window changes the experiment

[`NativeCaptureSettings.supported`](../../../../isaaclab_arena/agentic_environment_generation/workflow/native_capture.py#L85-L121) requires `window.start_step == settle_steps`, exact criterion windows and camera coverage ([`native_capture.py:85–121`](../../../../isaaclab_arena/agentic_environment_generation/workflow/native_capture.py#L85-L121)). Capturing each of three cameras at steps 176–180 produces **15 images**, not the three terminal images promised in the outcome. Setting `settle_steps=176` to satisfy that guard also changes the settling protocol. The selected design below preserves 180 steps, the final-five measurement window and three images at step 180 using explicitly versioned coverage semantics. `visual_request` also calls `_window`, which compares the entire sample sequence with the visual criterion window ([`scene_observation.py:129–139, 229–242`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_observation.py#L129); [`split_scene_ports.py:157–170`](../../../../isaaclab_arena/agentic_environment_generation/workflow/split_scene_ports.py#L157)). Fix request construction as well as admission/projection; do not simply remove the legacy common-window guard.

### R4 — The suggested benchmark assets are test vocabulary

The production asset library has `maple_table_robolab`, `red_block_basic_robolab` and `bin_b03_vomp_robolab` ([`assets/background_library.py:206`](../../../../isaaclab_arena/assets/background_library.py#L206), [`assets/object_library.py:776, 1682`](../../../../isaaclab_arena/assets/object_library.py#L776)). `synthetic_table` appears in [`tests/test_environment_workflow_repairs.py:19`](../../../../isaaclab_arena/tests/test_environment_workflow_repairs.py#L19); the proposed synthetic names are not a verified live benchmark. Reuse the existing registered DROID/table/block/bin family. Proposed dimensions, friction and camera calibration remain unverified until their actual source or scoped measurement is identified. Do not invent replacement registry entries or claim visual reachability, support, calibration or policy success.

### R5 — Accounting-only is a joined path, not a contract enum edit

[`foreground_authorization.py:269–282`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_authorization.py#L269) selects accounting version 2 only for workflow schema 4. [`ScenePorts.require_bounded_capability`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_ports.py#L184) and [`SplitScenePorts.require_bounded_capability`](../../../../isaaclab_arena/agentic_environment_generation/workflow/split_scene_ports.py#L78) still require token/cost-bounded allowances and compare their numeric caps. Other consumers include generation admission/reservation, send authorization, retained recovery and readback. Extend the selected policy coherently through these existing consumers, with no new ledger and no change to old modes. Role ceilings must be enforced durably: a total of four calls alone does not impose one initial generation, one repair and two assessments. Distinguish installed-config integer version `6`, proposed workflow string version `"6"`, evaluator versions and the existing database schema; they are not one version counter.

### R6 — A prompt instruction does not bind a repairable candidate

`BoundedSceneModels._proposal` already validates `ArenaEnvGraphSpec` ([`scene_engines.py:140–164`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_engines.py#L140)); generation is not merely an arbitrary dictionary. What is missing is the selected benchmark/repair-shape constraint. A frozen `/relations/2/params/x` must actually address `red_block`'s unique scalar `at_position` relation in the generated original. Validate fixed ordering/identity before native release; do not mutate the admitted contract or silently reorder a retained candidate. `env_local` is not automatically table-local. [`repairs.py:53–115`](../../../../isaaclab_arena/agentic_environment_generation/workflow/repairs.py#L53) needs an explicit effective mapping, and [`scene_observation.py:389–439`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_observation.py#L389) requires fresh realized displacement evidence. Structural XY permission is not proof that the solver moved the object.

### R7 — “Observe / stop” is still two different resource policies

[`scene_loop.py:368–384`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_loop.py#L368) routes inconclusive evidence to `observe`; [`neo4j_store.py:3584–3585`](../../../../isaaclab_arena/agentic_environment_generation/workflow/neo4j_store.py#L3584) turns that into capture for split ports. That can consume the second native launch on the unchanged candidate. For this bounded benchmark, a complete uncertain result must terminate sending/capture with an explicit nonaccepted outcome. A supported repair requires valid nonvisual prerequisites and a confirmed visual failure addressable by the authorized target/intervention—not any failed aggregate visibility record. Malformed output, retention failure and transport failure are integration failures, not scene rejection.

### R8 — The timing proposal is still not a reconciled budget

Six stages at 120 seconds reserve **720 seconds**, before additional cleanup-only/numeric intents; the appendix still sets `max_runtime_seconds=600`. A 90–120 second range is not an immutable executable selection or evidence that cold native startup fits. Derive concrete stage reservations from retained timings and the actual composed stages. [`neo4j_store.py:3553–3623`](../../../../isaaclab_arena/agentic_environment_generation/workflow/neo4j_store.py#L3553) charges prior reservations without refunds. Distinguish capture cohorts from PNGs, initial generation from repair, physical steps from wall time, and stage cleanup from final readback/drain. Do not shorten timeouts merely to make arithmetic pass.

### R9 — The installed lifecycle and source variants are missing from the join

The new mode also needs dispatch/setup/private-role/readiness/client/recovery handling, not just [`installed_config.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/installed_config.py) plus a factory. [`api/server.py:160–168`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/server.py#L160) and [`cli.py:209–232`](../../../../isaaclab_arena/agentic_environment_generation/workflow/cli.py#L209) select existing modes explicitly. `PrivateRoles` and credential setup also select existing config versions. Reuse `InitialGenerationWorker` / `InitialGenerationReceiver` for initial generation; their retained-prior and output translation are not supplied by merely wiring the base `ForegroundGenerationWorker` ([`foreground_initial_generation.py:6–12, 30–77, 80–135`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_initial_generation.py#L6)). Retain the scope owner between stages, release only the GPU lease after exact native cleanup, and retire the owner at the end. A fixed-candidate empirical case requires an explicit existing-source selection; `_stage_deadline` currently assumes a generation attempt outside schema 3 ([`foreground_split_scene_ports.py:99–116`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_split_scene_ports.py#L99)). Trace cancellation, duplicate cleanup acknowledgement, post-crash recovery and handover for the new selection before live use.

### R10 — The proof/authority contract remains incomplete

The proposed mock end-to-end phase conflicts with [Plan 04's investigation limits](../event_mapping/event-mapping-refactoring_plan_04.md#8-anti-dopamine-invariants--investigation-budgets). Existing guarded checks are regression evidence, not native acceptance. A zero-database-write goal cannot run database-mutating checks. The prior policy, credential source, operational scope and effect permissions need explicit selection. A preflight in one goal cannot establish effective authority at admission in a later goal. Finally, reporting an unexercised repair is truthful but does not close [Plan 03 V1's live repair obligation](../event_mapping/event-mapping-refactoring_plan_03.md#concrete-delivery-checkpoints).

Code references in R1–R9 are under `isaaclab_arena/agentic_environment_generation/workflow/`, except the explicitly named `assets/`, `tests/`, and `isaaclab_arena_examples/agentic_environment_generation/foreground_*.py` modules. These are source findings, not assertions that the proposed path has run.

## 2. Selected design for implementation

1. **Preserve the experiment:** one initial reset per realization; seeds and hold posture frozen; 180 control steps; both subjects' raw final samples 176–180; strict linear `<0.001 m/s` and angular `<0.01 rad/s`; exactly the three named RGB cameras captured at step 180. No extra settling/capture steps, policy, autoreset substitution or relabelled earlier frames.
2. **Version evidence semantics:** bind numeric and visual coverage to the same candidate, contract/profile, realization, reset and absolute step origin while declaring their actual different windows. Update producer, sampler/retention, evaluator, projection and fresh reader together. Preserve legacy equal-window and evaluator behavior. Do not require 15 images merely to satisfy an old DTO.
3. **Keep tri-state visibility:** every terminal camera has both subject answers and an exact frame digest. A valid negative/uncertain result is complete assessment integration, not scene acceptance. Preserve all six answers and their reasons. Correct freshness limitations for this new producer without rewriting I02's historical limitations.
4. **Constrain generation and repair:** selected real asset IDs, robot/task vocabulary, subject IDs, relation ordering and allowed scalar leaves are validated before effects. Freeze everything except the authorized original-centered XY disk for `red_block`; radius at most `0.25 m`. Preserve Z, task, topology, physics, cameras and all other fields. Retain original/current/proposed candidates, critique, permission envelope and actual effective-displacement witness.
5. **Make the prior policy explicit:** first I03 cases use `not_requested`, with a bound retained receipt and no research-prior queries or credentials. This is a declared no-retrieval policy, not proof of live prior integration. Operational Neo4j reads/writes remain separately authorized. A later nonempty-prior proof is a different selection.
6. **Use the same installed composition twice:** an explicit fixed existing candidate exercises the downstream native/assessment/repair boundary; a new-source operation then exercises real initial generation followed by that same boundary. No second executor or manually submitted next stage. Config version 6, workflow version `"6"` and `full-scene-execution-v1` remain proposed names until implemented and validated independently.
7. **Use existing accounting-only machinery:** no preset USD or aggregate-token ceiling; finite technical request/completion limits remain mandatory. Generation and repair use the explicitly shared generation-role model binding, assessment its own binding. Record actual usage and sourced cost estimates or explicit unknowns, never synthetic/free pricing.
8. **Stop rather than re-observe uncertainty:** one initial capture/assessment, at most one supported repair and one fresh capture/assessment. No automatic same-candidate recapture, provider retry, constructor ping, fallback, hidden generation correction or new retrieval. All failed/uncertain dispatches and native releases consume their selected effect allowance.

### Outcome and continuation rules

- Keep lifecycle state, evidence verdict, scene disposition, repair coverage and scientific flags separate. Use existing lifecycle states or an explicit reviewed versioned extension, not a forced `rejected`/`inconclusive` database state.
- Report each claim as verified, failed, inconclusive, blocked or not exercised as applicable. A proposed repair or changed JSON is not a completed repair witness; require effective native change plus fresh reassessment and cleanup.
- Goal 3 may establish valid native/sensing behavior without exercising repair. Goal 4 then remains possible only if every required producer/mapping prerequisite is established and no material blocker remains. Repair coverage remains open until actually witnessed in Goal 3 or Goal 4.
- A complete uncertain response does not establish sensor adequacy or calibration. If it exposes unresolved sensing, coordinate, settling or mapping validity, hold the dependent live trial and state the smallest discriminating experiment; do not spend the other case's allocation as an improvised diagnostic.
- Even if the joined workflow returns an explained nonaccepted result, positive scene acceptance remains false. Do not close Plan 04's positive-scene obligation, calibration, policy, prior eligibility or full-plan completion. Record any unmet parent-plan obligation explicitly.

## 2.1 Architectural Blueprint & Feasibility Evaluation

This section evaluates the feasibility of resolving the structural bottlenecks identified during review, transitioning from rigid pilot-specialized clamps to a generalist, physically grounded robotics environment generation engine. Configurable does not mean untraceable: the platform must retain which exact settings produced each observation and verdict.

### 2.1.1 Dynamic Settling Semantics in API Contracts
- **Codebase Reality**: [`contracts.py:111–145`](../../../../isaaclab_arena/agentic_environment_generation/workflow/contracts.py#L111) already contains `Criterion.limit`, `subjects`, and `observation_window`. However, downstream implementations in [`scene_observation.py:163–172`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_observation.py#L163) hardcode `SUPPORT_THRESHOLDS`, while [`native_capture.py:64–79`](../../../../isaaclab_arena/agentic_environment_generation/workflow/native_capture.py#L64) pins threshold fields to fixed values (`ge=0.01, le=0.01`) and enforces a single subject (`count = 1`). This is an implementation restriction, not a property of the API contract.
- **Typed Parameterized Evaluator (`settled-v2`)**:
  - Linear and angular velocity thresholds, units, and comparison operators (`operator="le"`).
  - Subject selection (`subjects: tuple[Identifier, ...]`) and reference frame (`coordinate_frames=("world",)`).
  - Required consecutive duration or sample count (e.g. final 5 control steps).
  - Temporal and subject aggregation rules (e.g., every selected subject must satisfy every sample in the window).
  - Missing-data and measurement-validity rules.
- **Typed Physical Predicates**: "Stationary" is only one physical predicate. An object may be stationary relative to a moving platform, while a bipedal robot should not satisfy a zero-velocity criterion. The general harness must support typed predicates: stationarity, pose convergence, contact stability, and task-specific conditions. Adapters declare supported predicates and measurements.
- **Measurement Retention & Post-Hoc Evaluation Efficiency**: Raw measurements (velocities, poses, contact forces) are retained separately from derived verdicts. Different thresholds can be evaluated against the same retained samples without relaunching native simulation, provided the retained samples cover the new criterion. These are new, labelled assessments—not retroactive edits to historical results. Exploratory threshold tuning is strictly distinguished from validation under a previously fixed criterion to prevent "relaxing requirements until it passes."

### 2.1.2 Ternary Logic as a First-Class Semantic Model
- **Codebase Reality**: Binary boolean logic in [`scene_observation.py:370`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_observation.py#L370) (`type(item["visible"]) is bool`) forces an epistemic dilemma, while [`scene_loop.py:384`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_loop.py#L384) converts any inconclusive assessment into `action="observe"`, triggering an unbudgeted native re-capture loop.
- **Three-Valued Truth Definition**:
  - `TRUE`: Supported by valid evidence.
  - `FALSE`: Contradicted by valid evidence.
  - `UNKNOWN`: The evidence does not establish either (e.g., camera resolution too low, sensor glare, or occlusion by the robot's own arm).
- **Formal Kleene 3-Valued Logic Algebra** [17]:
  $$\text{TRUE} \land \text{UNKNOWN} = \text{UNKNOWN}, \quad \text{FALSE} \land \text{UNKNOWN} = \text{FALSE}$$
  $$\text{TRUE} \lor \text{UNKNOWN} = \text{TRUE}, \quad \neg\text{UNKNOWN} = \text{UNKNOWN}$$
  Explicit enums are used rather than SQL NULL semantics.
- **Ontic vs. Epistemic Separation**: `not_visible` indicates an **ontic physical defect** (object occluded by scene geometry; candidate-repairable). `uncertain` indicates an **epistemic sensing defect**. Moving the object in response to epistemic uncertainty wastes compute and degrades scene quality.
- **Aggregation Rules**: Aggregation distinguishes `ANY` ("visible in at least one camera") from `ALL` ("visible in every camera"). Complete response coverage is preserved: an `ANY` predicate does not excuse dropping requested frame answers. Truth is kept distinct from execution status, model confidence, evidence age, and sensor conflict (contradictory reports require explicit conflict reasons).
- **End-to-End Codec Path**: The ternary verdict schema and validation rules reach all four layers:
  1. *Installed Worker* ([`split_scene_ports.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/split_scene_ports.py)): Requests, parses, and validates structured ternary JSON answers.
  2. *Retention Layer* ([`scene_evidence_artifacts.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_evidence_artifacts.py)): Preserves raw responses and typed evidence with UNKNOWN and its full provenance.
  3. *Evidence Projection* ([`scene_observation.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_observation.py)): Maps `visible` $\to$ `established`, `not_visible` $\to$ `violated`, `uncertain` $\to$ `inconclusive` without boolean reduction.
  4. *Router* ([`scene_loop.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_loop.py)): Distinguishes acceptance, supported physical correction, further observation, and technical failure.

### 2.1.3 Decoupled Sampling and Rendering Schedules
- **Codebase Reality**: [`native_capture.py:114`](../../../../isaaclab_arena/agentic_environment_generation/workflow/native_capture.py#L114) asserts that every criterion's `observation_window` must equal `self.window`, forcing camera rendering across all settling steps (3 cameras $\times$ 5 steps = 15 images, $>2\text{ MB}$ payload, $\approx 15,000$ VLM tokens).
- **Three-Way Schedule Separation**:
  1. *State Sampling*: Measurements, subjects, cadence, and clock (e.g. continuous 50–100Hz settling steps 176–180).
  2. *Image Acquisition*: Cameras, modalities, resolution, explicit step lists (e.g. terminal step 180 or keyframes $[0, 180]$), or event triggers.
  3. *Criterion Coverage*: Which observations each predicate requires.
- **Simulation Time Semantics**: Physics steps, control steps, and simulation time are distinguished explicitly.
- **Adaptive Observation Policies**: Support registered adaptive policies (e.g., capture after settling is established; request an alternate camera view when visibility remains unknown; acquire denser measurements around detected contact events).
- **Retention**: Retain the requested policy, the concrete schedule selected during execution, and the observations actually obtained, bound to candidate, reset, time, and sensor. Eliminates 80% rendering overhead and cuts token costs from $\approx 15,000$ to $\approx 3,000$ tokens per evaluation.

### 2.1.4 Lifecycle, Authorization and Accounting Architecture
Strengthen the existing execution owner and coordinator rather than introducing external orchestration frameworks:
- **A. Long-Running Operation Pattern (Google AIP-151 [1])**:
  Submission returns a durable operation identity. Status, progress, result retrieval, and cancellation operate on that identity. Extends [`execution_owner.py:54–110`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/execution_owner.py#L54) while preserving GraphQL interfaces.
- **B. Idempotent Admission & Atomic Mutex (AWS Idempotent APIs [2])**:
  Caller-provided operation identity plus immutable intent atomically records admission. Replay returns the prior receipt without creating duplicate model calls or native processes. Uncertain dispatches are reconciled with honest accounting.
- **C. Separation of Intent, Capability, and Authority**:
  - *Contract*: Describes the experiment.
  - *Installed Adapter*: Declares supported capabilities.
  - *Authentication & Grants*: Determine what may execute.
  - *Credentials*: Enable access but do not grant permission.
  Centralize checks in the admission path; preserve role-specific private delivery and fence checks at dispatch and durable writes.
- **D. Concurrency-Safe Dynamic Amendments (Google AIP-154 [16])**:
  Operational budget amendments carry expected resource-version/ETag, actor, and reason. Reject stale updates. Operational budget adjustments are strictly distinct from scientific criteria amendments; neither resets consumption or rewrites historical evidence.
- **E. Separating "Stop Requested" from "Cleanup Verified" (Kubernetes Finalizers [6])**:
  Cancellation stops new dispatches, addresses the exact owned worker, retains partial results and failures, verifies physical cleanup, and then releases GPU leases. A GPU is never released merely because a heartbeat disappeared.
- **F. Progress & Checkpointing (Temporal Heartbeats [4] & OpenTelemetry Context [14])**:
  Retain stage, attempt, owner epoch, last progress, usage, and first failure. A live process must prove progress; heartbeats support long-running native execution and cancellation.

### 2.1.5 Programmatic Causal Justification in Physical AI
Rather than assuming an ungrounded LLM explanation, physical simulation (USD + PhysX + RTX) is a deterministic glass-box diagnostic oracle. Causal justification is structured into three levels:
1. *Hypothesis Support*: Observations support a mechanism worth testing.
2. *Intervention Verification*: The requested physical change actually occurred in simulation.
3. *Causal-Effect Evidence*: A controlled comparison supports the predicted consequence.

**Concrete 6-Step Visibility-Repair Protocol**:
1. *Define Outcome Metric*: Target, camera, visibility rubric (projected extent, visible pixels, defined occlusion ratio).
2. *Collect Mechanism Diagnostics*: Replicator annotators [18] (depth, instance segmentation) and Isaac Lab contact sensors [20] distinguish:
   - Outside camera frustum $\to$ coverage limitation.
   - Projected footprint below pixel threshold $\to$ resolution limitation.
   - Adequate projected extent + depth/instance evidence of intervening mesh $\to$ supported occlusion.
3. *Register Structured Hypothesis*: Formulate a falsifiable hypothesis (e.g., *"Bin geometry blocks target line-of-sight; permitted XY displacement should reduce that obstruction"*), binding supporting measurements and predicted result.
4. *Matched Counterfactual Comparison*: Compare a no-intervention baseline with the intervention from matched initial conditions, holding other variables fixed (DoWhy / EconML causal inference [12]; respecting Isaac Lab reproducibility guidelines [21]).
5. *Verify Intervention & Consequence*: Did the object move to the intended location? Did visibility improve? Were settling and support conditions maintained? Changed JSON alone satisfies none of these.
6. *Check Alternatives & Repeatability*: Verify improvement was not caused by uncontrolled settling or lighting drift.

Simulator ground truth serves as an explicitly labelled diagnostic oracle; it is never leaked into RGB-only agent policy evaluation.

### 2.1.6 Dynamic Budgeting & Operational Profiles (Eliminating Test-Bench Clamps)
[`WorkflowBudget`](../../../../isaaclab_arena/agentic_environment_generation/workflow/contracts.py#L87) already contains runtime, calls, tokens, cost, steps, and timeout fields. The barrier is that downstream validators in [`contracts.py:275–317`](../../../../isaaclab_arena/agentic_environment_generation/workflow/contracts.py#L275) and [`neo4j_store.py:3553–3623`](../../../../isaaclab_arena/agentic_environment_generation/workflow/neo4j_store.py#L3553) impose artificial 600/1,200s caps and non-refunded reservations.

- **Three Selectable Budget Policies**:
  - `Enforced`: Configured limits prevent additional work.
  - `Advisory`: Targets produce warnings or planning signals, not rejection.
  - `Accounting-only`: Usage is retained without experiment-budget vetoes.
- **Testing Profile**:
  - Aggregate runtime and overall deadline are explicitly unset/unenforced.
  - Long native stages use heartbeat supervision and progress/cancellation handling.
  - Token/USD accounting remains enabled without a spending veto.
  - Call, launch, and observation ceilings are explicit policy choices.
- **Four Distinct Architectural Concepts**:
  1. *Scientific stopping rule*: When the experiment has sufficient evidence or reaches its declared horizon.
  2. *Resource budget*: Optional policy on expenditure.
  3. *Liveness supervision*: Detecting stalls/failures and processing cancellation.
  4. *Authority/backend limits*: Permitted effects, ownership, payload limits, service constraints.
- **Renewable Scoped Leases/Grants**: Removing global deadlines requires renewable scoped leases/grants, rather than demanding an authority grant that covers an infinite duration at admission. A budget amendment does not silently renew authorization.

## 3. Strategy and proposed allocations

| Goal | Deliverable that permits the next boundary | Permitted live effects if separately issued |
| --- | --- | --- |
| I03-G1 | Parameterized general contracts, evidence semantics (Kleene ternary logic), decoupled schedules, and selectable budget policies | No provider, Kit, API service or database effects |
| I03-G2 | Coherent installed execution, authority, lifecycle (AIP-151/154, finalizers, heartbeats), dynamic policy handling, and non-sending preview | Approved application/Neo4j setup only; no provider sends or native releases |
| I03-G3 | Real configurable measurement and programmatic causal-intervention proof on frozen candidate; diagnostic oracles verified | At most 2 native launches and 3 provider sends: 0 initial generation, at most 1 repair and 2 assessments |
| I03-G4 | Generated-scene integration through that same composition; causal readback and scoped closeout | At most 2 native launches and 4 provider sends: at most 1 initial generation, 1 repair and 2 assessments |

The tabletop red block and blue bin settings represent **one benchmark profile** within a general-purpose, configurable physical AI environment harness—not the hardcoded definition of the harness.

The operator chose this **proposed** two-case strategy during review. If both live goals are later issued, their combined ceilings are **4 new native launches and 7 provider sends**, not 2/4 for the whole package. The G4 ceiling remains the original 2/4 proposal. Do not transfer unused capacity between cases or renew it by reissuing a goal, changing operation IDs, restarting or delegating. Existing I01/I02 consumption and reservations remain historical and unchanged.

Each live case proposes at most 360 actual control steps, two initial resets, two capture cohorts and six terminal PNGs across its two possible candidates. These are maxima, not mandatory effects. Its absolute window is at most **1,200 seconds from durable admission through final API drain**. G2 must freeze actual numeric stage/cleanup reservations, request limits and final readback/drain headroom that fit both the case runtime reservation ceiling and this wall-clock bound. If a sufficient finite envelope cannot fit, return NEED_DECISION before issuing the live goal; do not silently raise 1,200 seconds or reduce the required experiment.

Use the existing store/intent/reservation records for enforcement and readback. A public case selection and a summary of those records are not another accounting system. Case identity, approved operation IDs, and cumulative consumption must survive process and session restarts; a previously admitted/failed same-key operation is never a fresh trial.

### Exact selection required before a live goal is issuable

The producing goal records the actual artifact path and digest; no path or hash below is claimed to exist now. The selection must contain:

- case, operation and predecessor identities; source manifest and current code version; exact contract/config/profile identities;
- fixed-candidate bytes/digest for G3, or exact prompt, constrained catalogues and generation settings for G4;
- runtime/capture/evaluator versions, assets, subject/prim mapping, hold/reset/seeds, numeric and image windows, image transforms/byte bounds and measurement validity obligations;
- original-centered repair permission and the predicate that permits it, with a fail-closed target mapping;
- explicit `not_requested` prior policy; exact operational database/deployment/workspace, existing artifact store and approved private installation identity;
- role configuration references and named credential source, never secret values; supported old-instance handover and cleanup prerequisites;
- case-level counts, exact per-stage reservations including cleanup, runtime sum, absolute duration, technical output bounds, and no-retry policy;
- effective authentication, approval and role-grant requirements rechecked immediately before admission; then the actual admitted time and absolute deadline;
- existing command entrypoints and scope-safe check commands, their expected observations, and which boundaries still require native/provider execution.

At admission, freeze known inputs and policies. Future generated candidates, images and candidate-specific requests are frozen and verified by the application at their actual stage boundaries. Do not pretend those bytes existed in a pre-generation preview or require an operator to resubmit a contract between stages.

## 4. Shared actor–critic protocol (AC-I03)

Every goal below incorporates this section. It is part of the proposed issuance, not execution authority on its own.

### Roles and loop

1. The parent is the ACTOR, sole writer/operator and final acceptance owner. Use one fresh, independent READ-ONLY CRITIC at a time through `delegate_task(tasks=[{goal, context, output_schema}])`. No additional agent framework, parallel implementers or critic-driven application operations.
2. Before the selected boundary, the actor states one causal hypothesis or implementation obligation, the smallest change/check, predicted observable result and applicable effect allowance. Provide the critic the goal, precise acceptance criteria, scoped source/diff, sanitized retained observations and consumed/remaining limits. Critics may read public source/evidence, but must not edit, run tests/services/constructors, open private configuration/credentials, send application requests or write the database.
3. Require a structured verdict: `CONTINUE`, `ACCEPT`, `BLOCKED` or `NEED_EVIDENCE`; cited criterion/evidence; concrete material blocker; and the smallest discriminating next action with its effects. `CONTINUE` means the reviewed next boundary is supported, not authorized or already proven. `ACCEPT` is scoped to the named goal. An unusable critique blocks; request one bounded clarification, not another general audit.
4. The actor verifies the findings, performs supported in-scope corrections and the allowed check, then requests a fresh focused delta critique if the reviewed boundary materially changed. Do not ask the operator after every routine correction. Never treat a critic's approval as permission to widen effects, waive a prerequisite or claim an unobserved outcome.
5. Normal checkpoints are one pre-boundary critique and one final-outcome critique per goal, not one per edit, worker or test. The application's live pipeline runs autonomously between these checkpoints. Complete bounded cleanup within its deadline before waiting on a final critic.
6. Stop after three unsuccessful corrections to the same blocker. Preserve the count across reissued goals/contexts. For a new architectural blocker, honor Plan 04's maximum two hypothesis/challenge rounds, three diagnostic invocations and 60 minutes of active investigation. These are ceilings, not a required investigation phase. Stop sooner on authority, ownership, scope or technical-limit failure.
7. The parent closes only verified criteria. Report the furthest actual application boundary, exact blocker and smallest decision needed. Passing checks, a source review, a preview and saved artifacts never become a live proof by aggregation.

### Common scope and verification rules

- Read current git state and definitions/callers before edits. Reuse the owner, coordinator, model tools, profile registry, grants, RequestEnvelope, artifact readers and durable ledger. Apply the smallest coherent correction to producer and consumers; no general rewrite, new orchestrator or secret-management system.
- Keep code work to the selected workflow/application/foreground/model-worker paths and indispensable callers. Do not change simulator/submodule code, assets, `docker/`, `.github/workflows/`, `.pre-commit-config.yaml`, fixture files or shared services/data. Do not commit, push, stash or reset. Preserve unrelated changes and all historical evidence.
- Prefer affected existing simulation-free checks. Minimal pure protocol regressions in existing test modules may accompany genuinely new semantics; observe their failure before correction. Do not create a mock simulator/provider end-to-end loop, new test files, fixtures, harnesses, source-extraction proof runners or scenario matrices. Existing synthetic results remain labelled synthetic and cannot satisfy live acceptance. Do not run a full suite that can start Kit implicitly.
- Discover the checkout container through `.agents/skills/dev-container/SKILL.md`; Arena package checks use `/isaac-sim/python.sh` as the mapped non-root operator. Lint stays on the host. No container recreation/rebuild, GR00T startup, global cache fixes or native smoke outside an explicitly issued native allowance. Starting an existing verified prerequisite is permitted only by the goal's effect scope.
- A no-database-effects goal must select checks that perform no database I/O. Database-mutating existing checks require a separately approved disposable scope, never an inferred production target. Missing that scope is a narrow blocker, not permission to create a fixture database.
- Preserve authenticated principals, grant/configuration binding, SDK retry/ping suppression and sanitized first-causal-failure retention at both parent and child boundaries. Cleanup is attempted even when diagnostic retention fails. Recover and validate retained provider bytes before considering any further action; unrecovered retention/ownership/authentication failures never justify another send.
- The live goals permit no provider retries, no same-candidate recapture and no hidden schema-repair calls. A valid negative/uncertain response ends assessment of those bytes. The separately authorized scene repair changes a candidate and requires new evidence; it is not a retry of the verdict.
- Count failed or uncertain provider dispatches and native releases conservatively in the existing ledger. Proven pre-dispatch refusals are distinct from sends, but reservations are never refunded. Development-agent/critic inference is separate from Arena application sends.
- Freeze source/config/inputs from live admission through recovery/replay/cleanup. Do not hot-patch an admitted run. A material application defect triggers bounded retention/recovery and stop; source correction returns to the non-sending implementation goal. Reissuing a spent/expired live goal or using a new operation key does not grant another allocation. A collector-only correction may recover retained bytes without effects, but must not erase its original failure.
- Clean up only exact owned processes, revalidating retained/live identities rather than historical PIDs. Read back cancellation, worker cleanup, GPU release, scope-owner retirement and API drain separately. Do not force database states, unlock leases, remove metadata, clear uncertainty flags or fabricate graceful shutdown after a crash.
- Refresh effective authentication/approval/role grants for the full selected live window at actual admission; configuration or credential installation is not authority. Use supported private delivery and exact configuration handover. Never print credentials, place them in argv/public artifacts, or search unrelated profiles/secrets.
- Update the existing package/index and canonical handoff with scoped verified results, preserved failures and remaining claims. Preserve I01 as native-only and I02 as integration-only with an uncertain visual result. Do not promote scientific flags or prior eligibility from workflow success.

## 5. Proposed goal prompts

All four prompts are **DRAFT — NOT ISSUED**. Each is independently issuable only after its stated prerequisite and selection are satisfied. Read the common protocol as well as the individual prompt.

### I03-G1 — Parameterized general contracts, evidence semantics, and budget policies

```text
/goal Implement P04-I03's parameterized general contracts, Kleene ternary evidence semantics, decoupled schedules, and selectable budget policies without live effects.

Read .agents/references/plans/plan04_implementation/03-full-scene-workflow-strategy.md sections 1–4. AC-I03 applies in full. This issuance authorizes only the scoped source/document changes and simulation-free, database-free checks below. It does not authorize G2, G3 or G4.

You are the ACTOR and sole writer. Obtain one independent read-only pre-boundary critic on the concrete semantic design, then implement through the existing paths. Use a fresh focused critic for material corrections and a final scoped outcome critique, within AC-I03's stop limits.

1. Implement Schema 6 and parameterize contracts in isaaclab_arena/agentic_environment_generation/workflow/contracts.py:
   - Define Schema 6 ("schema_version": "6") supporting both new generation (NewSource) and existing candidates (ExistingSource).
   - Parameterize Criterion and CriterionLimit for "settled-v2": support typed velocity thresholds (linear_velocity_threshold_m_per_s, angular_velocity_threshold_rad_per_s), comparison operators (operator="le"), multi-subject evaluation (tuple of subjects), and required duration (min_consecutive_settled_steps).
   - Decouple schedules: support camera rendering schedules (e.g. step: 180) independently from high-frequency physics state observation windows (e.g. start_step: 176, end_step: 180), removing the legacy 15-image forced common-window restriction.
   - Extend WorkflowBudget: add selectable budget policies ("enforced", "advisory", "accounting_only") and operational profiles (profile="development_debug" vs "ci" vs "benchmark").
   - Relax artificial validator clamps: remove hardcoded runtime/deadline clamps (< 570s, < 600s in lines 304–306); enforce only logical sanity (per_operation_timeout_seconds <= total_deadline_seconds). Remove lines 311–317 clamp that restricts null token/cost caps exclusively to schema 4, allowing Schema 6 to support accounting-only budgets with null token/cost ceilings.
   - Introduce TernaryVerdict enum/types (TRUE / visible, FALSE / not_visible, UNKNOWN / uncertain) with Kleene algebraic operations.
2. Implement raw measurement retention and Kleene evaluation in isaaclab_arena/agentic_environment_generation/workflow/scene_observation.py:
   - Separate raw physical measurements (linear/angular velocities, contact forces, poses) from derived verdicts in observation records, enabling post-hoc threshold re-evaluation without sim relaunch.
   - Implement settled-v2 evaluator evaluating all declared subjects across the observation window against the dynamic threshold limits.
   - Implement Kleene ternary logic evaluator for visual criteria: return TRUE (established), FALSE (violated), or UNKNOWN (inconclusive). Differentiate ontic physical defects (repairable) from epistemic sensing limitations (non-repairable; UNKNOWN stops rather than repairs). Support ANY vs ALL camera aggregation without boolean coercion.
3. Relax validator clamps in isaaclab_arena/agentic_environment_generation/workflow/native_capture.py:
   - Remove hardcoded clamps on settle_linear_m_per_s, evaluator_linear_m_per_s, evaluator_angular_rad_per_s, and evaluator_xy_m (relaxing ge=0.01, le=0.01 etc. to admit dynamic contract values).
4. Retain not_requested prior policy:
   - Ensure Schema 6 explicitly retains the not_requested research-prior policy receipt with zero prior I/O.
5. Exercise supported decoders/evaluators and add minimal pure regressions:
   - Add unit regressions in existing test modules (isaaclab_arena/tests/test_environment_workflow_contracts.py and test_environment_workflow_scene_observation.py) proving Schema 6, settled-v2, Kleene algebra, and relaxed budget rules without Kit or network imports.
   - Run package checks in the discovered checkout container as the non-root operator; host lint only on changed files. Zero provider calls, zero Kit/native launches, zero API service starts, zero database I/O, and zero credential installation.

Exit only after source-backed semantics and selected real decoders/checks agree and the parent verifies the critic's scoped ACCEPT. Record exactly what remains empirical. Passing this goal proves neither installed worker handoff nor native/VLM acceptance. Stop with the precise unsupported boundary after AC-I03's correction limits; do not substitute more tests or audits.
```

### I03-G2 — Coherent installed execution, authority, lifecycle, and dynamic policy handling

```text
/goal Implement and exercise P04-I03's installed full-scene composition, execution owner lifecycle, and non-sending readiness boundary.

Prerequisite: parent-accepted I03-G1 with its exact code/protocol evidence. Read .agents/references/plans/plan04_implementation/03-full-scene-workflow-strategy.md sections 1–4; AC-I03 applies in full. This issuance authorizes the scoped implementation and application setup below, not native or provider execution and not G3/G4.

Use one fresh read-only pre-boundary critic and one final scoped critic; parent remains sole writer/operator. Correct the first demonstrated failing boundary rather than building another executor.

1. Inspect admission path edge cases and join installed full-scene composition:
   - Define InstalledFullSceneConfig in isaaclab_arena/agentic_environment_generation/workflow/api/installed_config.py.
   - Implement FullScenePorts joining InitialGenerationWorker, SplitScenePorts (native PhysX settling/capture), visual assessment (retained or active model), and SceneRefiner (conditional repair) under the owned coordinator.
   - Inspect submitWorkflow in isaaclab_arena/agentic_environment_generation/workflow/service.py: verify Schema 6 admission when allow_operational_writes=true and dependency report is ready.
2. Implement long-running execution owner lifecycle (Google AIP-151) and idempotent admission (AWS idempotent APIs):
   - Submission returns a durable operation ID; status, progress, and cancellation operate on that identity.
   - Idempotent admission: submitting an identical request with the same operation_id returns the prior admission receipt immediately without duplicate dispatch. Submitting a modified payload with the same operation_id raises an atomic conflict.
3. Enforce clean separation of Intent, Capability, and Authority:
   - Centralize support validation in _validate_support in service.py before mutable checks or durable store admission.
   - Implement concurrency-safe dynamic budget amendments with resource-version/ETag checking (Google AIP-154), keeping budget updates strictly distinct from scientific criteria.
4. Implement verified cleanup before resource release (Kubernetes finalizer pattern):
   - Cancellation stops new dispatches, signals the active owned worker, retains partial failures, verifies physical process exit, and only then releases GPU leases.
   - Implement Temporal-style heartbeat liveness supervision across long native/model execution stages.
5. Authorize private binding of generation, assessment, and repair roles:
   - Read OPENAI_API_KEY from environment/local config for private role binding; never hardcode credentials or log secret values.
   - Split native and model adapters cleanly under the execution owner. Exercise actual installed parsing, authenticated inspection, serializer/RequestEnvelope, and non-sending preview boundaries. Deny provider sends and native releases.
6. Freeze the fixed-candidate G3 selection artifact:
   - Freeze candidate bytes, provenance, supported real assets/repair mapping, exact operation identity, source/contract/profile hashes, concrete reservations with TCC dynamic headroom refunding, and role limits under the development_debug operational profile.

Exit with the exact public G3 selection path/digest, parent-verified setup/preview evidence, and scoped critic verdict. Report unexercised native/provider boundaries honestly. Zero provider sends, zero Kit/native releases, zero policy and zero research-prior retrieval. G3 still requires separate issuance and fresh admission-time authority.
```

### I03-G3 — Configurable measurement and programmatic causal-intervention proof

```text
/goal Execute the separately budgeted P04-I03 fixed-candidate empirical proof through the installed full-scene composition with programmatic causal justification.

Prerequisites: parent-accepted G1/G2; operator-confirmed exact G3 selection path/digest; no unresolved ownership or mandatory producer/mapping blocker. Read .agents/references/plans/plan04_implementation/03-full-scene-workflow-strategy.md sections 2–4; AC-I03 applies in full. If the selection or concrete reservation envelope is absent, do not launch.

This issuance authorizes only p04-i03-fixed-scene-proof-v1 and its frozen existing candidate: at most TWO cumulative native releases, ZERO initial-generation sends, ONE repair send and TWO assessment sends (THREE provider sends total), 360 control steps, two initial resets, two capture cohorts and six terminal PNGs. Counts include failures and uncertainty; no refund, retry or automatic new-key successor. At most 1200 seconds from durable admission through API drain. One worker at a time. No preset monetary/aggregate-token cap; retain usage and cost estimates or unknowns, with frozen finite technical request/completion limits.

1. Parent rechecks source, exact scope, old cleanup/handover, role bindings, accounting and the effective auth/approval/grant lifetime for the entire selected window. Obtain one fresh read-only pre-send critic. Immediately before the single authenticated submission, repeat the freshness/authority check; retain actual admitted_at and absolute deadline. Critic approval is not authority.
2. Execute the 6-step causal justification protocol for physical evaluation:
   a. Define outcome metric: Target, camera, and visibility rubric.
   b. Collect mechanism diagnostics: Use Replicator depth/instance annotators and Isaac Lab contact sensors to distinguish coverage limits, resolution limits, and intervening occluders.
   c. Register structured hypothesis: Bind supporting measurements and predicted displacement consequence before intervention.
   d. Run matched counterfactual comparison: Compare no-intervention baseline with intervention from matched initial conditions.
   e. Verify intervention and consequence: Confirm physical displacement in sim, visibility improvement, and maintained support/settling.
   f. Check repeatability and alternatives.
3. Let the application own capture, numeric verification, and complete Kleene ternary assessment of both subjects in all three step-180 cameras. Simulator ground truth serves as a labelled diagnostic oracle, never leaked into RGB policy inputs.
4. Only if the frozen supported-visual-failure predicate is satisfied and all required nonvisual prerequisites hold may the application call the refiner once. Validate exact original-centered XY permissions, preserve all other fields, then require a fresh realization, effective displacement witness, settling evidence and reassessment. Complete uncertainty stops this bounded case; it does not trigger illegal repair or runaway capture.
5. Recover exact candidate/input/request/response/measurement/PNG/result bytes through a fresh authenticated client. Verify no-effect replay, physical cleanup, GPU release, durable owner retirement, lease release and API drain within the window, then obtain the final read-only critic.

Report the six claim dimensions separately, plus timing and empirical prerequisites for G4. A material application fault ends this frozen trial after bounded recovery; correct source under a non-sending goal, not by hot-patching.
```

### I03-G4 — Generated-scene integration through the configurable composition

```text
/goal Execute one P04-I03 generated-scene workflow through the installed application and close only its verified scope.

Prerequisites: parent-accepted G1/G2; G3's required empirical producer/mapping checks established with no unresolved material blocker; operator-confirmed exact final G4 selection path/digest. Reconcile any source changes since G3 against its evidence rather than assuming transfer. Read .agents/references/plans/plan04_implementation/03-full-scene-workflow-strategy.md sections 2–4; AC-I03 applies in full. This issuance does not rerun or renew G3.

Authorize p04-i03-full-scene-v1 with the frozen NewSource prompt and selected catalogues: at most TWO cumulative native releases, ONE initial-generation send, ONE repair send and TWO assessment sends (FOUR provider sends total), 360 control steps, two initial resets, two capture cohorts and six terminal PNGs. Counts include failed/uncertain effects. No provider retries, constructor pings, fallback, same-candidate recapture or new retrieval. One worker at a time; at most 1200 seconds from durable admission through API drain. No preset USD/aggregate-token cap; freeze adequate finite technical completion/request limits and retain actual usage/cost or explicit unknowns.

1. Obtain one fresh read-only pre-send critique of the exact final source/selection, cumulative limits and G3 evidence applicability. Immediately recheck effective authentication, approval and role grants against the entire window. Verify previous exact cleanup/handover. Retain admitted_at/deadline from the single authenticated submitWorkflow admission.
2. The installed application alone owns initial generation, candidate validation, native settling/capture, numeric and tri-state visual assessment, conditional permitted repair, fresh evidence and disposition. Freeze and verify candidate-specific requests at their actual boundaries; do not manually submit follow-on stages, edit generated bytes, change the admitted contract or silently fill an unsupported generated representation. Preserve the declared not_requested prior receipt.
3. Preserve 180-step/final-five/three-terminal-camera semantics per realization. Repair only a supported failure addressable by the frozen red_block intervention, with all nonvisual prerequisites established. Keep uncertainty, ineffective edits, unsupported corrections, budget stops and infrastructure failures distinct. Do not retry valid negative/uncertain answers or coerce an accepted scene.
4. Before the deadline, perform fresh authenticated exact-byte causal readback and completed-operation no-effect replay; verify unchanged effect/reservation records and historical I01/I02 records. Verify exact worker cleanup, GPU and scope lease release, durable owner retirement and supported API drain. After cleanup obtain the final read-only critic; the parent independently applies acceptance.

Report installed integration, physical measurements, visual assessment, actual repair coverage, scene disposition and readback/replay/cleanup separately. Full Plan 03 V1 repair coverage needs a genuine supported repair witness from G3 or this trial; two unexercised cases do not establish it. Positive scene acceptance and outstanding measurement/calibration obligations remain separate gates, including Plan 04's positive-scene requirement. Update the existing operation record, package/index, Plan 04 status and canonical handoff truthfully. No policy execution, prior promotion, full Milestone1 or Plan04 completion claim. If any required boundary is unproven, close only the supported slice and report the precise remaining decision without starting another trial.
```

## 6. Issuance and closeout checklist

- [ ] Parent/operator accepts the proposed semantic choices and issues G1 explicitly.
- [ ] G1 has actual decoder/evaluator/check evidence, not just this plan.
- [ ] G2's service/database scope is explicitly confirmed; private setup is not dispatch authority.
- [ ] Exact G3 selection and sufficient numeric timing envelope exist; the operator issues G3 separately.
- [ ] Required empirical producer/mapping checks are established or the precise blocker is retained.
- [ ] Exact final G4 selection incorporates applicable empirical evidence; the operator issues G4 separately.
- [ ] Original I01/I02 history, scientific caveats and consumed allowances remain intact.
- [ ] Both live cases retain their individual counters/deadlines; combined consumption is read from the existing ledger, not a new bookkeeping service.
- [ ] Any unexercised repair, nonaccepted scene, calibration or other parent-plan obligation remains explicitly open.

All checkboxes are intentionally open. This planning review is not implementation progress or runtime acceptance.

## 7. Architectural References

- [1] **Google AIP-151**: Long-running Operations (https://google.aip.dev/151)
- [2] **AWS Architecture Center**: Making retries safe with idempotent APIs (https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs)
- [4] **Temporal Documentation**: Long-running Activity Execution and Heartbeating (https://docs.temporal.io/design-patterns/long-running-activity)
- [6] **Kubernetes Concepts**: Working with Finalizers for Verified Resource Teardown (https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers)
- [12] **DoWhy / EconML**: Causal Inference and Counterfactual Intervention Analysis (https://pywhy.org/dowhy/v0.11/example_notebooks/tutorial-causalinference-machinelearning-using-dowhy-econml.html)
- [14] **OpenTelemetry Specification**: Context Propagation and Distributed Tracing (https://opentelemetry.io/docs/concepts/context-propagation)
- [16] **Google AIP-154**: Resource-version and ETag Concurrency Controls (https://google.aip.dev/154)
- [17] **PostgreSQL Documentation**: Three-Valued Logic Algebra (https://www.postgresql.org/docs/current/functions-logical.html)
- [18] **NVIDIA Omniverse Replicator**: Core Annotators and Synthetic Data Generation (https://docs.omniverse.nvidia.com/py/replicator/1.11.16/source/extensions/omni.replicator.core/docs/annotators_details.html)
- [20] **NVIDIA Isaac Lab Documentation**: Contact Sensors and Simulation Physics (https://isaac-sim.github.io/IsaacLab/main/source/overview/core-concepts/sensors/contact_sensor.html)
- [21] **NVIDIA Isaac Lab Documentation**: Simulation Reproducibility and Determinism (https://isaac-sim.github.io/IsaacLab/main/source/features/reproducibility.html)
