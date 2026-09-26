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

`scene_observation.py:31,70-79,163-175` pins evaluator v1 to `0.01 m/s` and `0.05 rad/s`; `scene.settled` takes one subject. The proposed contract instead supplies two subjects and claims the stricter final-five `0.001 m/s` / `0.01 rad/s` rule. Reusing v1 would either reject the request or establish the wrong scientific criterion. Keep old evaluator bytes/meaning intact; implement a versioned strict evaluator over the actual retained settling samples, with explicit subject coverage and strict comparisons.

### R2 — The revised visual codec loses the I02 result semantics

`scene_observation.py:70-79,344-386` admits one subject for visual v1 and consumes Boolean per-frame answers. I02's `visibility-v2` validates `visible`, `not_visible`, and `uncertain` for every frame/subject (`:272-321`). `SplitScenePorts` still uses the legacy evaluation path. Selecting v1 cannot prove the proposed two-subject uncertainty-aware assessment. Join the complete structured response into the real full-scene worker, retention, evidence projection and router; do not reuse the retained-only execution mode as a hidden second operation. `not_visible` is not itself a causal diagnosis of occlusion.

### R3 — The new shared window changes the experiment

`NativeCaptureSettings.supported` requires `window.start_step == settle_steps`, exact criterion windows and camera coverage (`native_capture.py:85-121`). Capturing each of three cameras at steps 176–180 produces **15 images**, not the three terminal images promised in the outcome. Setting `settle_steps=176` to satisfy that guard also changes the settling protocol. The selected design below preserves 180 steps, the final-five measurement window and three images at step 180 using explicitly versioned coverage semantics. `visual_request` also calls `_window`, which compares the entire sample sequence with the visual criterion window (`scene_observation.py:129-139,229-242`; `split_scene_ports.py:157-170`). Fix request construction as well as admission/projection; do not simply remove the legacy common-window guard.

### R4 — The suggested benchmark assets are test vocabulary

The production asset library has `maple_table_robolab`, `red_block_basic_robolab` and `bin_b03_vomp_robolab` (`assets/background_library.py:206`, `assets/object_library.py:776,1682`). `synthetic_table` appears in `tests/test_environment_workflow_repairs.py:19`; the proposed synthetic names are not a verified live benchmark. Reuse the existing registered DROID/table/block/bin family. Proposed dimensions, friction and camera calibration remain unverified until their actual source or scoped measurement is identified. Do not invent replacement registry entries or claim visual reachability, support, calibration or policy success.

### R5 — Accounting-only is a joined path, not a contract enum edit

`foreground_authorization.py:269-282` selects accounting version 2 only for workflow schema 4. `ScenePorts.require_bounded_capability` and `SplitScenePorts.require_bounded_capability` still require token/cost-bounded allowances and compare their numeric caps. Other consumers include generation admission/reservation, send authorization, retained recovery and readback. Extend the selected policy coherently through these existing consumers, with no new ledger and no change to old modes. Role ceilings must be enforced durably: a total of four calls alone does not impose one initial generation, one repair and two assessments. Distinguish installed-config integer version `6`, proposed workflow string version `"6"`, evaluator versions and the existing database schema; they are not one version counter.

### R6 — A prompt instruction does not bind a repairable candidate

`BoundedSceneModels._proposal` already validates `ArenaEnvGraphSpec` (`scene_engines.py:140-164`); generation is not merely an arbitrary dictionary. What is missing is the selected benchmark/repair-shape constraint. A frozen `/relations/2/params/x` must actually address `red_block`'s unique scalar `at_position` relation in the generated original. Validate fixed ordering/identity before native release; do not mutate the admitted contract or silently reorder a retained candidate. `env_local` is not automatically table-local. `repairs.py:53-115` needs an explicit effective mapping, and `scene_observation.py:389-439` requires fresh realized displacement evidence. Structural XY permission is not proof that the solver moved the object.

### R7 — “Observe / stop” is still two different resource policies

`scene_loop.py:368-384` routes inconclusive evidence to `observe`; `neo4j_store.py:3584-3585` turns that into capture for split ports. That can consume the second native launch on the unchanged candidate. For this bounded benchmark, a complete uncertain result must terminate sending/capture with an explicit nonaccepted outcome. A supported repair requires valid nonvisual prerequisites and a confirmed visual failure addressable by the authorized target/intervention—not any failed aggregate visibility record. Malformed output, retention failure and transport failure are integration failures, not scene rejection.

### R8 — The timing proposal is still not a reconciled budget

Six stages at 120 seconds reserve **720 seconds**, before additional cleanup-only/numeric intents; the appendix still sets `max_runtime_seconds=600`. A 90–120 second range is not an immutable executable selection or evidence that cold native startup fits. Derive concrete stage reservations from retained timings and the actual composed stages. `neo4j_store.py:3553-3623` charges prior reservations without refunds. Distinguish capture cohorts from PNGs, initial generation from repair, physical steps from wall time, and stage cleanup from final readback/drain. Do not shorten timeouts merely to make arithmetic pass.

### R9 — The installed lifecycle and source variants are missing from the join

The new mode also needs dispatch/setup/private-role/readiness/client/recovery handling, not just `installed_config.py` plus a factory. `api/server.py:160-168` and `cli.py:209-232` select existing modes explicitly. `PrivateRoles` and credential setup also select existing config versions. Reuse `InitialGenerationWorker` / `InitialGenerationReceiver` for initial generation; their retained-prior and output translation are not supplied by merely wiring the base `ForegroundGenerationWorker` (`foreground_initial_generation.py:6-12,30-77,80-135`). Retain the scope owner between stages, release only the GPU lease after exact native cleanup, and retire the owner at the end. A fixed-candidate empirical case requires an explicit existing-source selection; `_stage_deadline` currently assumes a generation attempt outside schema 3 (`foreground_split_scene_ports.py:99-116`). Trace cancellation, duplicate cleanup acknowledgement, post-crash recovery and handover for the new selection before live use.

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

## 3. Strategy and proposed allocations

| Goal | Deliverable that permits the next boundary | Permitted live effects if separately issued |
| --- | --- | --- |
| I03-G1 | Versioned contract/accounting/evidence/repair semantics implemented and exercised by real decoders/evaluators | No provider, Kit, API service or database effects |
| I03-G2 | Installed composition, scoped setup/readback, non-sending preview and lifecycle route ready; exact empirical selection frozen | Approved application/Neo4j setup only; no provider sends or native releases |
| I03-G3 | Fixed-candidate native/evidence proof; conditional real repair witness; all observed failures retained | At most 2 native launches and 3 provider sends: 0 initial generation, at most 1 repair and 2 assessments |
| I03-G4 | One generated-scene submission through the same composition; final causal readback and scoped closeout | At most 2 native launches and 4 provider sends: at most 1 initial generation, 1 repair and 2 assessments |

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

### I03-G1 — Implement truthful protocol and accounting semantics

```text
/goal Implement P04-I03's versioned full-scene protocol, accounting and evidence semantics without live effects.

Read .agents/references/plans/plan04_implementation/03-full-scene-workflow-strategy.md sections 1–4. AC-I03 applies in full. This issuance authorizes only the scoped source/document changes and simulation-free, database-free checks below. It does not authorize G2, G3 or G4.

You are the ACTOR and sole writer. Obtain one independent read-only pre-boundary critic on the concrete semantic design, then implement through the existing paths. Use a fresh focused critic for material corrections and a final scoped outcome critique, within AC-I03's stop limits.

1. Implement the selected new workflow version and accounting-only policy through contracts, generation/scene reservations, authorization, model allowances, send accounting and readers. Treat installed config version 6 and workflow string version "6" as distinct protocols. Preserve old schemas and their serialized meanings. Do not solve this by widening every schema guard, using dummy caps/prices or creating another ledger. Enforce initial-generation, repair, assessment and native counts separately and cumulatively.
2. Preserve 180 actual control steps, raw final samples 176–180 and exactly three terminal camera images at step 180. Implement explicit versioned cohort/window coverage and strict numeric evaluation for both subjects. Exercise visual_request/_window, retention and pure evidence-reader/replay validation with those numeric samples and terminal images together; keep legacy exact-window rejection. The actual fresh authenticated API readback remains a later installed/live proof. Join complete per-frame/per-subject visible/not_visible/uncertain results without Boolean coercion, and retain malformed/partial responses as integration failures. Do not change evaluator v1's existing semantics.
3. Validate the real selected asset/task vocabulary, canonical relation identity/order and exact authorized red_block XY leaves before effects. Keep the <=0.25m disk centered on the original candidate, freeze all other fields and require actual effective-placement evidence. Bind the decision predicate to a supported failure addressable by that intervention. Complete uncertainty stops this bounded case; it must not automatically route to another capture.
4. Support a strictly selected existing-source fixed-candidate proof and a new-source generated-scene trial through the same protocol. Explicitly retain not_requested prior policy with zero research-prior I/O. Preserve separate lifecycle, scene, integration and repair-coverage outcomes.
5. Exercise actual supported decoders/evaluators and affected existing checks. Minimal pure regressions may be added only within existing test modules for the changed semantics; no new mock loops, fixtures or harnesses. Run package checks in the discovered checkout container as the non-root operator; host lint only on changed files. Zero provider calls, zero Kit/native launches, zero API service starts, zero database I/O and zero credential installation.

Exit only after source-backed semantics and selected real decoders/checks agree and the parent verifies the critic's scoped ACCEPT. Record exactly what remains empirical. Passing this goal proves neither installed worker handoff nor native/VLM acceptance. Stop with the precise unsupported boundary after AC-I03's correction limits; do not substitute more tests or audits.
```

### I03-G2 — Join the installed owner, private roles and recovery path

```text
/goal Implement and exercise P04-I03's installed full-scene composition and non-sending readiness boundary.

Prerequisite: parent-accepted I03-G1 with its exact code/protocol evidence. Read .agents/references/plans/plan04_implementation/03-full-scene-workflow-strategy.md sections 1–4; AC-I03 applies in full. This issuance authorizes the scoped implementation and application setup below, not native or provider execution and not G3/G4.

Use one fresh read-only pre-boundary critic and one final scoped critic; parent remains sole writer/operator. Correct the first demonstrated failing boundary rather than building another executor.

1. Join the selected installed mode through config decoding, server/CLI dispatch, private role loading, readiness, ownership, previews, durable readers, cancellation and supported recovery/handover. Reuse InitialGenerationWorker/Receiver, split native/model stage adapters, existing owner/coordinator and artifact store. Keep scope ownership across stages; release the GPU only after exact acknowledged native cleanup. Do not infer a generation attempt for the fixed-candidate source.
2. The operator must name/confirm the exact existing approved operational installation and database/deployment/workspace before service or database effects. Resolve only that supported configuration. Within that scope, authorize normal profile/config/artifact administration, application records and owned API start/stop needed for this preparation. No database migration, production-target guess, old-record deletion or direct state-forcing. Database-mutating regression checks require a separately confirmed disposable scope; otherwise skip them explicitly rather than write elsewhere.
3. Authorize private binding of generation, assessment and explicitly shared repair roles from the existing OPENAI_API_KEY environment entry; if absent, read only that entry from the operator-named ~/.hermes/.env as local data. Use supported private delivery and the approved Neo4j binding. No secret disclosure or unrelated secret/profile reads. Setup grants no execution authority; missing private input blocks only its dependent step. Discover/start only already-existing verified checkout/Neo4j prerequisite containers when needed; never recreate them.
4. Exercise actual installed parsing, authenticated inspection, serializer/RequestEnvelope and non-sending preview boundaries. Deny provider sends and native releases, including constructor pings. A future candidate/image/request cannot be previewed as though it exists: report serializer/envelope coverage separately from actual child handoff and stage-specific bytes still to be produced. Reuse existing guarded checks; no new mock end-to-end loop or application bypass.
5. Freeze the fixed-candidate G3 selection described in section 3: a new immutable benchmark with provenance, supported real assets/repair mapping, exact operation identity, source/contract/profile hashes, concrete stage/cleanup reservations, role/count limits, no-retry policy and at most 1200 seconds overall. Prepare G4's selection template without claiming its future generated bytes or later authority. If adequate native/model/cleanup allowances cannot fit, return NEED_DECISION; do not invent 90–120s bounds. Read back all setup writes and stop/drain the owned preparation API through the supported path.

Exit with the exact public G3 selection path/digest, parent-verified setup/preview evidence and scoped critic verdict. Report unexercised native/provider boundaries honestly. Zero provider sends, zero Kit/native releases, zero policy and zero research-prior retrieval. G3 still requires separate issuance and fresh admission-time authority.
```

### I03-G3 — Prove the fixed-candidate native/evidence boundary

```text
/goal Execute the separately budgeted P04-I03 fixed-candidate empirical proof through the installed full-scene composition.

Prerequisites: parent-accepted G1/G2; operator-confirmed exact G3 selection path/digest; no unresolved ownership or mandatory producer/mapping blocker. Read .agents/references/plans/plan04_implementation/03-full-scene-workflow-strategy.md sections 2–4; AC-I03 applies in full. If the selection or concrete reservation envelope is absent, do not launch.

This issuance authorizes only p04-i03-fixed-scene-proof-v1 and its frozen existing candidate: at most TWO cumulative native releases, ZERO initial-generation sends, ONE repair send and TWO assessment sends (THREE provider sends total), 360 control steps, two initial resets, two capture cohorts and six terminal PNGs. Counts include failures and uncertainty; no refund, retry or automatic new-key successor. At most 1200 seconds from durable admission through API drain. One worker at a time. No preset monetary/aggregate-token cap; retain usage and cost estimates or unknowns, with frozen finite technical request/completion limits.

1. Parent rechecks source, exact scope, old cleanup/handover, role bindings, accounting and the effective auth/approval/grant lifetime for the entire selected window. Obtain one fresh read-only pre-send critic. Immediately before the single authenticated submission, repeat the freshness/authority check; retain actual admitted_at and absolute deadline. Critic approval is not authority.
2. Let the application own capture, numeric verification and complete tri-state assessment of both subjects in all three step-180 cameras. Verify actual reset-relative samples, tensor/subject/coordinate identities, image preprocessing and any declared sensing/measurement validity references. Historical hashes and one model opinion do not establish calibration. No uncounted native smoke, additional capture or operator-launched next stage.
3. Only if the frozen supported-visual-failure predicate is satisfied and all required nonvisual prerequisites hold may the application call the refiner once. Validate exact original-centered XY permissions, preserve all other fields, then require a fresh realization, effective displacement witness, settling evidence and reassessment. Never fabricate a negative critique or change the benchmark mid-run to force branch coverage. A complete uncertain or already-passing result ends this case without further sends/captures and leaves repair unexercised.
4. Recover exact candidate/input/request/response/measurement/PNG/result bytes through a fresh authenticated client. Verify no-effect replay and unchanged dispatch, native-release and reservation records. Verify physical cleanup, GPU release, durable owner retirement, lease release and API drain within the original window, then obtain the final read-only critic. Preserve every failed attempt and any cleanup uncertainty.

Report the six claim dimensions separately, plus timing and the exact empirical prerequisites now supported for G4. A truthful negative/inconclusive assessment can establish integration, not scene acceptance, sensing calibration or a completed repair witness. If native/sensing/mapping validity is unresolved, block G4 and state the smallest next experiment requiring separate authority. Do not consume G4's allocation. A material application fault ends this frozen trial after bounded recovery; correct source under a non-sending goal, not by hot-patching or restarting this allocation.
```

### I03-G4 — Prove the generated-scene workflow and close verified scope

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
