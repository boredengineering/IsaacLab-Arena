# P04-I01 — Native integration defects and bounded revalidation

> **Current status: VERIFIED and parent-closed on a5 (2026-09-25).**
> The original 3/3 and additional 2/2 native launches are consumed; zero remain.
> The proposal/review-script snapshot below is preserved as history, not a new
> allocation or a reversal of the [verified result](../../../../outputs/workflow/plan04-implementation/milestone1/installed-native-20260925T012042Z/p04-i01/LIVE_RESULT.txt)
> and [parent closeout](../../../../outputs/workflow/plan04-implementation/milestone1/installed-native-20260925T012042Z/p04-i01/parent-closeout.json).
> Successor [P04-I02](02-installed-visual-assessment.md) was issued and is blocked
> after installed worker release, with no recorded provider send or assessment result.
> Its execution window expired and durable retirement/API drain remain unresolved.
> The [issue-recovery proposal](02-installed-visual-assessment.md#issue-recovery-proposal--draft-for-review)
> is saved for further review, **NOT ISSUED**; no recovery or successor execution
> occurred during documentation work. This does not reopen I01's native allocation.
> The [canonical handoff](../dashboard_cli_workflow_parity/research-stack-implementation-handoff.md)
> owns current status. Unchecked proposal items and “not issued” text below are historical.

## Historical proposal and review-script snapshot

- Created: 2026-09-25
- Status: **Proposed — implementation and additional native execution not authorized by this document**
- Parent: [Plan 04](../event_mapping/event-mapping-refactoring_plan_04.md)
- Status owner: [canonical implementation handoff](../dashboard_cli_workflow_parity/research-stack-implementation-handoff.md)
- Previous allocation: **3/3 native launches consumed; none remain**
- Proposed new allocation: at most two additional native launches, only after the
  no-native gate and explicit issuance of the goal below.
- Development method: parent-led actor with one independent, read-only critic;
  evidence-driven correction loop, not a parallel application executor.

## 1. Outcome

Make the installed application complete retained-candidate native validation:
construction, the frozen settling gate, three same-cohort camera captures,
truthful persistence, fresh-client artifact-byte readback, replay and owned cleanup.

Repair integration boundaries before spending another native launch. Do not change
the scene or lower the acceptance criteria to obtain a pass. Do not replace the
installed workflow with a standalone helper invocation.

This work package does not close all of Milestone 1, visual validation, policy
acceptance, prior eligibility or Plan 04.

## 2. Established facts and remaining uncertainty

| Issue | Established evidence | What is not established |
| --- | --- | --- |
| Artifact layout | The native worker puts `native-capture-work` inside the artifact root; the reader allows only its marker, `staging` and `final`. Fresh candidate/artifact-inventory reads fail. | Successful authenticated artifact-byte recovery after repair |
| Native construction | Attempt a3 reached `schemas.activate_contact_sensors` and raised at the branch for no rigid bodies beneath the requested prim. No settling samples or camera frames were recorded. | The offending prim/asset and why its expected rigid body was absent |
| Candidate fidelity | The original file hash is unchanged; the raw-versus-normalized spec-admission defect was corrected before a3. | Native scientific acceptance |
| Lifecycle and retention | Failed-result/Neo4j readback and completed-operation replay without a new launch passed; owners retired and the final API drained. | Full success-path execution and artifact-byte acceptance |
| Code quality | A visual-dispatch test and CLI complexity lint remain failing. | Whether the test failure was present at baseline; merge readiness |

The earlier standalone realization of the same candidate built the scene, stepped
and captured images. It is the comparison case for constructor/wrapper inputs,
not proof that the installed path is equivalent or that settling passed.

### Evidence and code references

- [Installed bounded result](../../../../outputs/workflow/plan04-implementation/milestone1/installed-native-20260925T012042Z/LIVE_RESULT.txt)
- [Authenticated/Neo4j readback and replay](../../../../outputs/workflow/plan04-implementation/milestone1/installed-native-20260925T012042Z/parent-readback.json)
- [Failure chains and cleanup joins](../../../../outputs/workflow/plan04-implementation/milestone1/installed-native-20260925T012042Z/retained-evidence.json)
- [Earlier standalone result](../../../../outputs/workflow/plan04-implementation/milestone1/realize-20260924T232748Z/LIVE_RESULT.txt)
- [Native worker](../../../../isaaclab_arena_examples/agentic_environment_generation/web_api/native_scene_worker.py): scratch placement in `execute`; causal diagnostic retention before Kit shutdown.
- [Artifact store](../../../../isaaclab_arena/agentic_environment_generation/workbench/research_artifacts.py): `ArtifactArea._load` enforces the root layout.
- [Native realization adapter](../../../../isaaclab_arena/agentic_environment_generation/workflow/native_realization.py): `build_native_environment` calls the existing builder.
- [Read-only simulator reference](../../../../submodules/IsaacLab/source/isaaclab/isaaclab/sim/schemas/schemas.py): `activate_contact_sensors`, failure branch at line 720 in the inspected checkout. This is not permission to edit the submodule.

## 3. Immutable input and experimental policy

Original candidate:
`outputs/workflow/plan04-implementation/milestone1/realize-20260924T232748Z/candidate.json`

Original file SHA-256:
`8dcd08b813236ee0ccdcad1024594a70301d4a6fdcd0af41d013e05f5135a7e8`

Canonical admitted candidate digest:
`2dc9fa1eb2ec06c872366dc10bf709cb412b435b85e1417bc788854091051b53`

These hashes describe different representations. Verify each against its declared
bytes; do not compare canonicalized JSON with the original-file digest or silently
replace the original file with normalized output.

| Setting | Frozen requested value |
| --- | --- |
| Environments / concurrent native workers | One / one |
| Settling control steps | 180 |
| Final consecutive samples | Five |
| Linear velocity norm | Strictly below 0.001 m/s |
| Angular velocity norm | Strictly below 0.01 rad/s |
| Subjects | `red_block`, `blue_bin` |
| Simulation / placement seeds | 42 / 42 |
| Simulation timestep / decimation | 0.005 s / 4 |
| Control timestep | 0.020 s; 180 control steps imply a requested 3.600 s, not 0.900 s |
| Reset configuration | `resolve_on_reset=true`; initial reset only, no hidden terminal/autoreset substitution |
| Capture | Three fresh camera captures from the same cohort, no extra capture stepping after the final window |
| Per-launch bound | 600 seconds including cleanup |

These are an operator-approved revised settling policy, not established calibration.
The failed constructor never reached verification of the realized timestep/reset
behavior. A successful attempt must check those actual values.

## 4. Actor-critic development loop

### Roles and authority

- **Actor — parent agent:** the sole code writer and operator. It reads the actual
  interfaces, makes narrowly scoped fixes, runs existing checks, submits through
  the installed application, and verifies persistence, replay and cleanup. The
  application—not either development agent—owns its internal stage transitions.
- **Critic — independent subagent:** use the existing `delegate_task` tool with a
  fresh context at each meaningful checkpoint and at most one critic at a time.
  Supply the goal, limits, acceptance criteria and sanitized evidence explicitly;
  a child does not inherit this conversation. The critic reads the scoped diff,
  relevant source and retained evidence and challenges causality and acceptance.
  It must not edit files, run tests/services/simulation, load credentials, access
  private client files, write the database, submit operations or grant authority.
- The critic's read-only role is a task restriction, not a claim that delegation
  provides a separate filesystem sandbox. Do not pass secrets or private setup
  documents. Use the currently available tool schema, not invented delegation flags.
- Development-agent inference uses the existing Hermes configuration and can
  consume model tokens. The zero-provider constraint applies to Arena workflow
  generation, constructor probes, repair and VLM assessment; none is authorized.
  Do not load/export model credentials into the application or worker, or change
  Hermes provider configuration to run this loop. Do not claim zero LLM usage overall.

### Repeat on concrete evidence, not on a review schedule

1. **Observe:** reconcile current source, authority, retained result and ownership.
   Locate the earliest failed application boundary. Preserve the initiating error
   separately from shutdown/cleanup errors; a process exit code alone is not a verdict.
2. **Form and check one correction:** distinguish facts from hypotheses. Name the
   suspected cause, smallest in-scope change, predicted observation and exact existing
   check or installed command that can falsify it. Prefer the no-native path whenever
   it answers the question. Missing evidence calls for bounded diagnostics, not a guess.
3. **Act and capture:** implement only the supported correction and run its relevant
   existing check. When Gate A and live authority permit, freeze source and submit
   through the installed workflow. The application must retain native diagnostics
   before Kit shutdown, plus whatever measurements/images were actually produced.
   Never substitute fake samples, old camera images or manual stage chaining.
4. **Critique:** send one compact evidence packet at Gate A, after each native outcome,
   and after a materially changed correction to an unresolved blocker. Do not delegate
   every file/tool action, repeat generic reviews or start a reviewer campaign. While
   that snapshot is under review, do not change it or release another native worker.
5. **Correct or advance:** the actor verifies the critic's cited facts against exact
   source/artifacts, records the disposition, and applies the smallest supported fix.
   Re-run the affected existing checks. A retry must state what changed and which
   observed failure or missing diagnostic it addresses. Critic approval does not
   enlarge authority or release a worker; the actor rechecks all release conditions.
6. **Close:** continue routine in-scope corrections without asking after every patch.
   Stop only at verified acceptance or a stop condition below. Report the furthest
   real application boundary reached—not review counts, file counts or test totals.

### Evidence packet and critic response

Keep a short per-iteration record alongside the existing work-package evidence;
link existing artifacts rather than introducing a new reporting/accounting system.
Include only available, relevant evidence; label missing fields as unknown:

- Iteration/operation/attempt identities, captured source identity or scoped diff,
  unchanged candidate/policy identities, and allocation consumed/remaining.
- Exact installed command or existing check, exit/result status, furthest phase,
  sanitized initiating exception with the failing prim/asset reference when known,
  and separate cleanup observations.
- Actual measurement/camera availability and cohort identity, retained result and
  manifest references, fresh-client byte/hash comparisons, and replay release count.
- One causal hypothesis, its predicted observable change, proposed correction,
  actual before/after evidence, and unmet acceptance criteria.

Require a valid JSON critic response, using the tool's per-task `output_schema`
for its structure and the following fields:
`decision`, `evidence_refs`, `earliest_failed_boundary`, `hypothesis`, `prediction`,
`next_action`, `next_check`, `unmet_criteria`, `scope_or_budget_risks`.

- `CONTINUE`: a specific in-scope action is supported; this is not execution approval.
- `NEED_EVIDENCE`: name the smallest missing observation, preferring no-native reads.
  A diagnostic native run is still a counted launch and requires Gate A and authority.
- `BLOCKED`: no supported action fits the scope/allocation, or an ownership/safety
  issue prevents proceeding. Identify the exact operator decision needed.
- `ACCEPT`: every acceptance criterion has cited runtime evidence. It is a review
  recommendation; only the parent may mark the work package verified after readback.

An absent, unsupported or malformed verdict is not approval. Permit one format-only
correction request, with no new runtime effects; otherwise stop with that limitation.
If actor and critic disagree, obtain the smallest discriminating observation rather
than voting, spawning more reviewers or repeating the same argument.

### Loop bounds

- The proposed native allowance remains **two additional launches in total**, not
  two per iteration, process, new goal restart or new operation ID. Count diagnostic
  launches and failed starts according to the existing durable accounting. Never
  refund consumed releases because construction failed.
- After three unsuccessful non-native fix cycles for the same blocker, stop and
  request a concrete scope/architecture decision instead of trying a fourth variant.
- Verify owned cleanup before the next native release or changes to exercised source.
  Preserve evidence and perform required bounded cleanup even when the budget expires.
- Freeze source during each runtime attempt and its readback/replay acceptance.
  Runtime-affecting edits after a result invalidate the affected acceptance evidence;
  another native check, if needed, must fit the remaining allocation.
- No critic approval, successful unit check or lack of visible error replaces the
  real application criteria. Exhausted native authority ends execution; it does not
  trigger a new agent, a separate executor or an automatic budget extension.

## 5. Phase A — Repair without native execution

### A1. Separate scratch and retained artifacts

- [ ] Add an explicit, bounded, operator-owned native scratch location outside the
  sealed artifact root, delivered through the existing worker boundary.
- [ ] Keep per-attempt ownership/path validation and cleanup; do not expose arbitrary
  filesystem paths or relax artifact reader checks.
- [ ] Verify exact worker absence and ownership before recovering the existing layout.
  Preserve the misplaced scratch directory intact at a recorded safe location;
  preserve the marker, staged/final manifests, receipts, hashes and all failed evidence.
- [ ] Reopen the same artifact area. Do not create a fresh artifact/private root to
  evade failed state, ownership, configuration checks or consumed accounting.
- [ ] Use a fresh authenticated client to retrieve the retained candidate and available
  artifact bytes, compare their declared hashes, and prove reads/replay release no worker.
  Correct any remaining external-candidate read-path defect rather than equating
  a filesystem export with HTTP acceptance.

### A2. Make construction failures actionable

- [ ] Compare the installed wrapper's consumed construction inputs with the earlier
  working realization: prim mapping, asset references, contact-report requests,
  required asset/runtime environment delivery and relevant builder settings.
- [ ] Use retained logs and source first. Distinguish an incorrectly targeted subtree,
  missing/unloaded asset, and an inappropriate contact request as hypotheses—not facts.
- [ ] Retain the failed phase, offending prim, relevant asset reference and sanitized
  causal exception message before Kit shutdown, in addition to bounded static frames.
  Do not record locals, credentials or sensitive URL components.
- [ ] Keep inspection scoped to the failed construction boundary. No comprehensive
  simulator metadata inventory, physics redesign or submodule changes.
- [ ] Correct only an evidence-supported adapter/configuration mismatch. Do not
  globally disable contact checks or add rigid-body properties to force acceptance.
  If the remedy requires changing assets, physics or simulator code, stop for a decision.

If existing evidence cannot identify the prim, record that gap. The first newly
authorized native run must collect the required diagnosis; it is not an uncounted probe.

### A3. Resolve existing quality failures

- [ ] Diagnose `test_foreground_split_service_keeps_owner_and_cleans_before_model[False-False]`
  with the existing check; establish baseline status rather than assuming regression.
- [ ] Correct any in-scope dispatch defect without bypassing the authorization/send guard.
- [ ] Resolve C901 in `workflow/cli.py::_run_installed` with narrowly scoped command-handler
  cleanup, not a broad refactor.
- [ ] Run existing relevant checks. Do not add or modify tests, mocks or synthetic fixtures.
- [ ] Select simulation-free checks for Gate A. A check that initializes Kit/native
  simulation is a counted native launch, not a free test, and cannot run in this phase.
  Follow repository rules: lint on the host; Arena package checks inside the verified
  existing checkout container as the host user.

### Gate A

Before any new native launch, retain evidence that:

- [ ] The same artifact area reopens and authenticated candidate/artifact-byte reads pass.
- [ ] Original/canonical bytes match their respective hashes; failed records remain attributable.
- [ ] No model credentials are loaded into the Arena application or worker; no Arena
  workflow provider calls or native worker releases occurred during this phase.
- [ ] Useful bounded constructor diagnostics are wired, and the known/unknown cause is explicit.
- [ ] Relevant existing checks and scoped lint pass; unresolved failures are not hidden.
- [ ] The next candidate, settings, operation identity and source revision are frozen.
- [ ] The critic has reviewed this concrete evidence and the proposed next native
  action; the actor has resolved cited blocking findings and rechecked authority.

## 6. Phase B — Conditional installed native revalidation

This phase requires explicit issuance of the proposed goal or equivalent fresh
bounded authorization. The exhausted old allocation is never reset or reused.

- [ ] Record the new allocation and fresh operation identities using the existing
  authorization/accounting machinery; preserve old receipts, tombstones and reservations.
  Use checked configuration handover if the selected public configuration changes.
- [ ] Discover and verify this checkout's existing container, run as the host user,
  and keep one environment/owned native worker at a time.
- [ ] First additional launch: submit through the installed authenticated interface.
  Let the application own construction, settling, capture, persistence and cleanup.
- [ ] If it fails, retain the precise diagnosis and cleanup. A second additional launch
  is allowed only after a supported in-scope correction; never retry an unchanged failure.
- [ ] Feed the actual native outcome, retained artifacts and cleanup evidence into
  the actor-critic loop before selecting any next action. Missing settling samples
  or cameras are missing evidence, not a reason to recycle the older trial's artifacts.
- [ ] Freeze corrected source before acceptance. No warm-up/diagnostic launch outside
  the new allocation, no provider call and no manually launched next stage.

## 7. Acceptance and stop conditions

Mark this work package **Verified** only when all of these are evidenced:

- [ ] Real finite measurements pass the complete final five-sample settling window.
- [ ] Actual seeds, timestep and reset behavior agree with the frozen policy.
- [ ] Three fresh camera captures belong to that same candidate/cohort.
- [ ] The application retains the new attempt, candidate/policy identities, measurements,
  images and truthful outcome; fresh authenticated clients recover the bytes.
- [ ] Replaying the completed operation returns retained results without another launch.
- [ ] Physical owned-worker cleanup and durable owner retirement are verified.
- [ ] `native_settled=true` is supported by the actual passing attempt. `converged`,
  `verified` and prior eligibility are not promoted merely because native settling passes.
- [ ] Existing failed attempts remain unchanged; Plan 04 and the handoff state the
  verified native-only result and remaining visual/policy/general-validation gates.
- [ ] The final critic review cites these actual results, and the parent independently
  verifies the claims and marks completion; the critic cannot close tracked work.

Stop on the additional allocation being exhausted, unresolved ownership, an
out-of-scope remedy, no evidence-supported next correction, or the bounded non-native
loop failing to resolve the same blocker. Report software integration separately
from the scientific/native result. A truthful failure does not satisfy the positive
gate; passing checks does not close the whole Plan 04.

## Proposed goal prompt

**Not issued.** Saving this prompt grants no execution authority. Copy and issue it
only when both implementation and the conditional new allocation below are intended.

```text
/goal Complete P04-I01 in .agents/references/plans/plan04_implementation/01-native-integration-defects.md using a bounded actor-critic development loop. Repair the native integration defects and make the installed application run, capture, retain and recover the real native-validation result. Progress means executable application acceptance, not more plans, tests or review passes.

AUTHORITY AND ROLES

This issued goal authorizes narrowly scoped Arena adapter/orchestration changes, exact retained-scratch recovery, existing checks, authenticated readback and—only after Gate A passes—at most two additional native launches in total. Preserve the three consumed launches and all durable accounting. Do not start a new allocation on restart or because a different agent/operation is used.

You are the ACTOR and sole writer/operator. Use one independent CRITIC at a time through the existing delegate_task tool, in a fresh context at meaningful checkpoints. Pass the goal, constraints, acceptance criteria, scoped diff and sanitized evidence explicitly. Do not build a new agent framework, parallel executor, budget ledger or reporting platform.

The CRITIC is read-only: inspect the relevant source and evidence, challenge the root-cause hypothesis, find missing acceptance evidence, and propose the smallest next action. It must not edit files, run tests/services/simulation, submit operations, access credentials/private client files, write the database or grant authority. Development-agent inference may use the existing Hermes configuration and incur tokens; this is separate from Arena's zero-workflow-provider budget. Do not change provider configuration or read/export model credentials into the application, worker or review packet.

EXECUTION LOOP

1. Observe the earliest failed application boundary from real retained evidence. Separate initiating errors from cleanup errors and unknowns from facts. Identify one falsifiable causal hypothesis, the smallest in-scope correction, its predicted observation and the exact existing check or installed command that can verify it.
2. Apply that correction and run its affected existing checks. Prefer a no-native reproduction when it answers the question. If diagnosis is missing, improve bounded diagnostics rather than guessing. Do not add or modify tests, mocks, fixtures or a standalone acceptance harness. Honor repository tool boundaries: host lint, Arena package checks in the verified existing container as the host user. Gate A checks must be simulation-free; a test that initializes Kit/native simulation is a counted launch, not an exception to the gate.
3. Capture a compact record: iteration/operation/attempt and source identities; candidate/policy identities; allocation consumed/remaining; command and actual result; furthest phase; sanitized causal exception including prim/asset when known; real measurements/images and cohort if available; retained artifact references; authenticated readback/replay observations; and exact owned cleanup. Reuse existing evidence paths and record missing evidence explicitly.
4. Obtain the CRITIC's valid JSON response at Gate A, after each native outcome and after a materially changed correction to an unresolved blocker—not after every file/tool action. Use the tool's per-task output_schema to require decision (CONTINUE, NEED_EVIDENCE, BLOCKED or ACCEPT), evidence_refs, earliest_failed_boundary, hypothesis, prediction, next_action, next_check, unmet_criteria and scope_or_budget_risks. Each finding must cite evidence. Invalid or absent feedback is not approval; allow one format-only correction request, then stop if unusable.
5. Verify the critic's claims yourself. Resolve a disagreement with the smallest discriminating observation, not extra reviewers. Apply a supported in-scope fix, rerun affected checks, and continue without asking permission after every routine correction. Before every native release, independently recheck Gate A, current authority, remaining allocation, unchanged input/policy and previous-worker cleanup. Critic approval cannot waive any gate.
6. Stop only when all acceptance criteria are actually verified or a stated stop condition applies. After three unsuccessful non-native fix cycles for the same blocker, stop for a specific scope/architecture decision; do not try a fourth speculative variant. Never repeat an unchanged native failure. Every diagnostic native launch counts.

FIRST: GATE A, WITHOUT NATIVE EXECUTION

Separate native scratch from the sealed artifact root without weakening its reader. Verify ownership and worker absence before preserving/relocating misplaced scratch. Keep manifests, bytes, receipts, tombstones and failed evidence intact; reopen the same artifact area, not a replacement private root that evades history. Prove fresh authenticated candidate/artifact-byte reads and their declared hashes, and replay without a worker release.

Compare the installed constructor inputs with the earlier working realization. Retain bounded sanitized failure messages, failing phase and prim/asset references before Kit shutdown; do not capture locals, secrets or sensitive URL components. Treat prim mapping, asset loading and contact requests as hypotheses until evidenced. Do not globally disable contact checks or add physics properties to force construction. Resolve the outstanding existing visual-dispatch check and CLI lint failure without changing tests or weakening guards. Gate A passes only with real readback evidence, usable diagnostics, relevant existing checks/lint, frozen selections and the critic's evidence review; distinguish any still-unknown native cause explicitly.

THEN: BOUNDED INSTALLED EXECUTION

Reuse outputs/workflow/plan04-implementation/milestone1/realize-20260924T232748Z/candidate.json unchanged; original-file SHA-256 is 8dcd08b813236ee0ccdcad1024594a70301d4a6fdcd0af41d013e05f5135a7e8. Keep the plan's distinct canonical digest and frozen policy: seeds 42/42; simulation dt 0.005 s; decimation 4; control dt 0.020 s; resolve_on_reset=true with initial reset only; 180 control steps; final five consecutive samples; linear norm <0.001 m/s and angular norm <0.01 rad/s for red_block and blue_bin. Check actual realized values, forbid hidden terminal/autoreset substitution, and allow no extra capture stepping. This is an operator-approved revised policy, not established calibration.

Make zero Arena workflow provider requests: no generation, constructor probes, model repair or VLM assessment; no policy execution. Only the approved operational Neo4j binding may be used for this workflow, with trial writes limited to milestone1_live_20260924t232748z_r2 and required application-owned records. Preserve separate read/execution authority, private delivery and checked configuration handover.

Discover and verify this checkout's existing Isaac Lab container and run as the host user. Permit one environment and one owned native worker concurrently. Use the existing finite 600-second per-launch watchdog including cleanup. Submit fresh operation identities through the installed authenticated CLI/GraphQL interface. The coordinator, execution owner and owned worker must own the entire native run, capture, retention and cleanup; never manually launch each next stage.

Freeze exercised source during a run and its readback/replay verification. Capture the actual outcome before shutdown and verify physical cleanup and durable owner retirement before modifying that source or releasing another worker. If the first new launch fails, the second may run only after a cited, evidence-supported correction, including a targeted diagnostic correction if required. Failed starts and diagnostic runs consume the existing accounting allowance; no refunds or hidden probes. Changes affecting an earlier passing result require revalidation within the remaining allocation.

ACCEPTANCE, STOP AND CLOSEOUT

Accept only after finite measurements pass the actual final five-step window, three fresh camera captures belong to that same cohort, and the application retains the exact new attempt/candidate/policy identities, measurements, images and truthful outcome. A fresh authenticated client must recover retained bytes with matching hashes; replaying the completed operation must return its retained result without another native launch. Verify cleanup, unchanged prior failed records and zero Arena workflow provider calls. Set native_settled only from a genuinely passing attempt; do not automatically promote convergence, verification or prior eligibility.

The critic must cite the complete acceptance evidence; the parent independently verifies it and alone closes the work package. A review pass, successful process exit, unit-test count, filesystem export or accurately reported native failure is not positive native acceptance.

Stop for exhausted allocation, unresolved ownership, an out-of-scope remedy, no supported next correction, unusable independent critique or the repeated non-native failure limit. Preserve diagnostics and complete required bounded cleanup before reporting the exact blocker and operator decision needed. Do not change the candidate, seeds, thresholds, assets or physics; edit simulator/submodule code; recreate containers; reconfigure shared services; bypass synthetic/native guards; commit or push. Preserve unrelated working-tree changes; do not stash or reset them.

Update the work-package index, Plan 04 and canonical handoff with the final source/evidence references, allocation used, and separate integration, native-scientific, readback/replay and cleanup outcomes. Keep reporting concise. Do not claim full Milestone 1, VLM/visual validation, policy acceptance, prior eligibility or Plan 04 completion from this slice.
```

### New Review script

```bash
/goal Complete P04-I01 in .agents/references/plans/plan04_implementation/01-native-integration-defects.md using a bounded actor-critic development loop. Repair the native integration defects and make the installed application run, capture, retain and recover the real native-validation result. Progress means executable application acceptance, not more plans, tests or review passes.
  
  AUTHORITY AND ROLES
  
  This issued goal authorizes narrowly scoped Arena adapter/orchestration changes, exact retained-scratch recovery, existing checks, authenticated readback and—only after Gate A passes—at most two additional native launches in total. Preserve the three consumed launches and all durable accounting. Do not start a new allocation on restart or because a different agent/operation is used.
  
  You are the ACTOR and sole writer/operator. Use one independent CRITIC at a time through the available subagent delegation tool in a fresh context at meaningful checkpoints. Pass the goal, constraints, acceptance criteria, scoped diff and sanitized evidence explicitly. Do not build a new agent framework, parallel executor, budget ledger or reporting platform.
  
  The CRITIC is read-only: inspect the relevant source and evidence, challenge the root-cause hypothesis, find missing acceptance evidence, and propose the smallest next action. It must not edit files, run tests/services/simulation, submit operations, access credentials/private client files, write the database or grant authority. Development-agent inference may use the existing Hermes
configuration and incur tokens; this is separate from Arena's zero-workflow-provider budget. Do not change provider configuration or read/export model credentials into the application, worker or review packet.
  
  EXECUTION LOOP
  
  1. Observe the earliest failed application boundary from real retained evidence. Separate initiating errors from cleanup errors and unknowns from facts. Identify one falsifiable causal hypothesis, the smallest in-scope correction, its predicted observation and the exact existing check or installed command that can verify it.
  2. Apply that correction and run its affected existing checks. Prefer a no-native reproduction when it answers the question. If diagnosis is missing, improve bounded diagnostics rather than guessing. Do not add or modify tests, mocks, fixtures or a standalone acceptance harness. Honor repository tool boundaries: host lint, Arena package checks in the verified existing container
isaaclab_arena-latest as the non-root host user ubuntu (UID 1000, required by ForegroundOwnerLease). Gate A checks must be simulation-free; a test that initializes Kit/native simulation is a counted launch, not an exception to the gate.
  3. Capture a compact record: iteration/operation/attempt and source identities; candidate/policy identities; allocation consumed/remaining; command and actual result; furthest phase; sanitized causal exception including prim/asset when known; real measurements/images and cohort if available; retained artifact references; authenticated readback/replay observations; and exact owned
cleanup. Reuse existing evidence paths and record missing evidence explicitly.
  4. Obtain the CRITIC's valid JSON response at Gate A, after each native outcome and after a materially changed correction to an unresolved blocker—not after every file/tool action. Use the tool's per-task output_schema to require decision (CONTINUE, NEED_EVIDENCE, BLOCKED or ACCEPT), evidence_refs, earliest_failed_boundary, hypothesis, prediction, next_action, next_check, unmet_criteria
and scope_or_budget_risks. Each finding must cite evidence. Invalid or absent feedback is not approval; allow one format-only correction request, then stop if unusable.
  5. Verify the critic's claims yourself. Resolve a disagreement with the smallest discriminating observation, not extra reviewers. Apply a supported in-scope fix, rerun affected checks, and continue without asking permission after every routine correction. Before every native release, independently recheck Gate A, current authority, remaining allocation, unchanged input/policy and
previous-worker cleanup. Critic approval cannot waive any gate.
  6. Stop only when all acceptance criteria are actually verified or a stated stop condition applies. After three unsuccessful non-native fix cycles for the same blocker, stop for a specific scope/architecture decision; do not try a fourth speculative variant. Never repeat an unchanged native failure. Every diagnostic native launch counts.
  
  FIRST: GATE A, WITHOUT NATIVE EXECUTION
  
  Separate native scratch from the sealed artifact root without weakening its reader. Move stray native-capture-work out of /home/ubuntu/.local/state/arena/installed-native-20260925T012042Z/artifacts/ into a sibling scratch/ directory. Keep manifests, bytes, receipts, tombstones and failed evidence intact; reopen the same artifact area, not a replacement private root that evades history.
Prove fresh authenticated candidate/artifact-byte reads and their declared hashes, and replay without a worker release.

  Compare the installed constructor inputs with the earlier working realization. Retain bounded sanitized failure messages (str(cause)), failing phase and prim/asset references before Kit shutdown; do not capture locals, secrets or sensitive URL components. Treat prim mapping, asset loading and contact requests as hypotheses until evidenced. Do not globally disable contact checks or add
physics properties to force construction. Resolve the outstanding existing visual-dispatch check in split_scene_ports.py (line 158 receipt binding during assess) and CLI complexity lint (C901 in workflow/cli.py::_run_installed) without changing tests or weakening guards. Gate A passes only with real readback evidence, usable diagnostics, relevant existing checks/lint, frozen selections
and the critic's evidence review; distinguish any still-unknown native cause explicitly.

  THEN: BOUNDED INSTALLED EXECUTION

  Reuse outputs/workflow/plan04-implementation/milestone1/realize-20260924T232748Z/candidate.json unchanged; original-file SHA-256 is 8dcd08b813236ee0ccdcad1024594a70301d4a6fdcd0af41d013e05f5135a7e8. Keep the plan's distinct canonical digest and frozen policy: seeds 42/42; simulation dt 0.005 s; decimation 4; control dt 0.020 s; resolve_on_reset=true with initial reset only; 180 control
steps; final five consecutive samples; linear norm <0.001 m/s and angular norm <0.01 rad/s for red_block and blue_bin. Check actual realized values, forbid hidden terminal/autoreset substitution, and allow no extra capture stepping. This is an operator-approved revised policy, not established calibration.

  Make zero Arena workflow provider requests: no generation, constructor probes, model repair or VLM assessment; no policy execution. Only the approved operational Neo4j binding may be used for this workflow, with trial writes limited to milestone1_live_20260924t232748z_r2 and required application-owned records. Preserve separate read/execution authority, private delivery and checked
configuration handover.

  Discover and verify this checkout's existing Isaac Lab container (isaaclab_arena-latest) and run as non-root UID 1000 (ubuntu). Permit one environment and one owned native worker concurrently. Use the existing finite 600-second per-launch watchdog including cleanup. Submit fresh operation identities through the installed authenticated CLI/GraphQL interface. The coordinator, execution
owner and owned worker must own the entire native run, capture, retention and cleanup; never manually launch each next stage.

  Freeze exercised source during a run and its readback/replay verification. Capture the actual outcome before shutdown and verify physical cleanup and durable owner retirement before modifying that source or releasing another worker. If the first new launch fails, the second may run only after a cited, evidence-supported correction, including a targeted diagnostic correction if required.
Failed starts and diagnostic runs consume the existing accounting allowance; no refunds or hidden probes. Changes affecting an earlier passing result require revalidation within the remaining allocation.

  ACCEPTANCE, STOP AND CLOSEOUT

  Accept only after finite measurements pass the actual final five-step window, three fresh camera captures belong to that same cohort, and the application retains the exact new attempt/candidate/policy identities, measurements, images and truthful outcome. A fresh authenticated client must recover retained bytes with matching hashes; replaying the completed operation must return its
retained result without another native launch. Verify cleanup, unchanged prior failed records and zero Arena workflow provider calls. Set native_settled only from a genuinely passing attempt; do not automatically promote convergence, verification or prior eligibility.

  The critic must cite the complete acceptance evidence; the parent independently verifies it and alone closes the work package. A review pass, successful process exit, unit-test count, filesystem export or accurately reported native failure is not positive native acceptance.

  Stop for exhausted allocation, unresolved ownership, an out-of-scope remedy, no supported next correction, unusable independent critique or the repeated non-native failure limit. Preserve diagnostics and complete required bounded cleanup before reporting the exact blocker and operator decision needed. Do not change the candidate, seeds, thresholds, assets or physics; edit
simulator/submodule code; recreate containers; reconfigure shared services; bypass synthetic/native guards; commit or push. Preserve unrelated working-tree changes; do not stash or reset them.

  Update the work-package index, Plan 04 and canonical handoff with the final source/evidence references, allocation used, and separate integration, native-scientific, readback/replay and cleanup outcomes. Keep reporting concise. Do not claim full Milestone 1, VLM/visual validation, policy acceptance, prior eligibility or Plan 04 completion from this slice.
```

## Closeout — to be filled after authorized execution

- Goal/authorization reference: not issued.
- Actor-critic iterations and evidence/decision references: none; loop not started.
- Gate A evidence: pending.
- New operation/run identities and consumed allocation: none authorized under this plan.
- Native result and artifact-byte/replay evidence: pending.
- Cleanup evidence: pending for any future execution; previous cleanup remains in the handoff.
- Remaining blockers / next decision: approve a bounded goal or revise its scope.
- Canonical handoff update: pending execution, not implied by creation of this plan.
