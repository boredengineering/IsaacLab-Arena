# Event Mapping Refactoring Plan 02 — Application-Owned Generate and Verify

Status: **PROPOSAL — documentation only; implementation and live execution are not authorized by this plan.**

Baseline inspected: `45a0b26466`, branch `dev/0.3.0-prerelease`. Source anchors below describe this baseline; recheck before implementation.

Planning checkpoint: review-loop corrections are incorporated. Section 13 now decomposes P0 into owned work packages and explicit handoff gates; section 15 distinguishes decisions required for the first CLI from later-phase selections. These are planned deliverables, not completed contracts or permission to execute workloads. The review ledger preserves the exact revision reviewed before this action-plan elaboration.

## 1. Decision, scope and document ownership

Implement one application-owned, bounded **generate and verify environment** workflow over the existing Arena engines. Use Python, the existing Neo4j driver and existing bounded worker/process mechanisms. Do not add a general-purpose agent framework, message broker, distributed service stack or replacement policy runner.

The first deliverable is a complete CLI submission/status workflow: generate from a prompt using retained Graph-RAG context, validate, realize/capture, assess, and autonomously perform permitted repair and reassessment. The dashboard subsequently calls the **same application service**, not a browser-side sequence of Generate/Build/Repair buttons.

This proposal incorporates the user's two solutions and corrects the acceptance, schema, migration and recovery problems identified in [plan 01](event-mapping-refactoring_plan_01.md). Plan 01 remains historical design material, not an executable implementation specification. This document is the successor design proposal; the [existing handoff](dashboard_cli_workflow_parity/research-stack-implementation-handoff.md) remains the sole implementation-status owner. The [session study](../quick_notes/session_memory.md) retains the discussion and historical evidence. No new completion claims are implied.

### Scope boundaries

- Consolidate reusable application/runtime capabilities under `isaaclab_arena/agentic_environment_generation/`; retain existing engines and thin compatibility entry points.
- Move authority for **new managed verification workflows and their execution attempts** into Neo4j. Do not mirror those jobs into SQLite as a second source of lifecycle truth.
- Leave unrelated legacy workbench features on their existing authorities initially. Complete SQLite retirement is a separate, inventoried migration, not a prerequisite for the first vertical slice.
- Preserve existing authorization, cancellation, process ownership, resource leases, receipt validation and research-publication safeguards. Extraction must not remove them.
- Do not redesign the accepted dashboard, reorganize every diagnostic tool, replace DCRG's numerical method, or claim this fixes the unresolved browser-refresh/terminal-display reports.
- No service startup, credentials reuse, queue release, shared Neo4j schema/data writes, rendering, model calls or policy experiments are authorized by writing/reviewing this document.

### Baseline correction: trajectory tooling is already partly extracted

The older solution text describing import-time simulator startup and a failed-red-apple prompt is superseded by `45a0b26466`. Reuse:

- `isaaclab_arena/agentic_environment_generation/trajectory_capture.py:12`, `capture_trajectory`.
- `isaaclab_arena/agentic_environment_generation/trajectory_assessment.py:48`, `assess_trajectory`.
- `isaaclab_arena_examples/tools/render_policy_trajectory.py:16,43,129`, parser, `run`, and explicit `main` lifecycle.

These retain task-driven visual assessment and capture evidence; `task_success` remains unknown. Historical isolated tests and native capture/failure-exit evidence do not establish a live VLM-guided repair loop. Do not redo the prompt fix or relocate these helpers merely to match a diagram.

## 2. Observable outcome and non-negotiable invariants

One submission yields either an accepted candidate **under named criteria**, or a retained nonaccepted outcome with candidate/evidence where available and a precise reason. Operational failure, cancellation, blocked authorization and indeterminate execution remain distinct from scientific rejection.

| ID | Invariant |
| --- | --- |
| I1 | Candidate production, schema validity, realization, capture, assessment, scene acceptance, policy success and publication are different facts. |
| I2 | Acceptance requires every required criterion to be established by its declared evidence type and evaluator, bound to the selected candidate and execution profile. |
| I3 | Missing, stale, advisory, malformed or inconclusive evidence is never a pass. A VLM cannot replace required physical measurements. |
| I4 | Models propose and assess; application rules authorize effects, enforce deltas, reserve budgets and decide acceptance. |
| I5 | Every revised candidate has a new identity and fresh relevant evidence; no acceptance from its parent's visual/physical receipts. |
| I6 | Exactly one authoritative store owns each managed workflow/attempt. Database atomicity does not promise exactly-once remote inference or simulation effects. |
| I7 | Decision, budget reservation and next execution intent commit together before external work. Unknown effects require reconciliation, not blind retry. |
| I8 | The coordinator never holds the serial simulation/worker slot while awaiting a child; cancellation and cleanup remain executable during database outages. |
| I9 | Repair preserves the frozen research question. Physics, task gates and fixed poses cannot be relaxed to manufacture success. |
| I10 | Retention, scene acceptance, publication and successful-prior eligibility are separate dispositions. |
| I11 | CLI and HTTP enforce the same application authorization and use the same service. Read/query/refresh operations never dispatch work. |
| I12 | Core reusable code does not import examples or GUI implementations; domain imports do not start simulation or contact providers. |

## 3. Frozen request, identities and result contracts

Use existing Pydantic v2 support and standard-library types; choose one versioned wire schema rather than incompatible dataclass/Pydantic representations. Domain contracts must import without Torch, Isaac Sim, Omniverse, FastAPI, Streamlit or argparse. Validate finite numbers, bounded collections/text and complete field sets. Freeze nested values through immutable representations or canonical serialized snapshots; `frozen=True` around a mutable dictionary is insufficient.

Pure workflow-contract construction, serialization and invalid-input checks must also remain runtime-independent. Do not instantiate `ArenaEnvGraphSpec` or trigger registry validation in that boundary: `AssetSpec.registry_name` validation calls lazy asset registration, which can import simulator code. Keep opaque source bytes/identities and bounded contract fields in the pure request; validate actual candidates/catalogues through the existing schema in the execution adapter's admitted runtime. Test representative valid/invalid contract construction with runtime imports denied, not just module import. This does not introduce a parallel environment schema or remove candidate validation.

### 3.1 Workflow contract

| Field group | Required contents |
| --- | --- |
| Intent | Prompt; new-generation or explicit existing-candidate verification mode; embodiment/task requirements; research objective; source identity if supplied. New generation must not acquire the editor's current draft as a hidden base. |
| Required criteria | Stable criterion IDs, evaluator kind/version, required evidence modalities, exact subjects/frames, thresholds/tolerances, observation windows, and required/advisory designation. |
| Preserved constraints | Asset/embodiment identities, task and threshold semantics, fixed poses/support anchors, requested arrangement, physics settings, placement-validator policy and prohibited topology changes. |
| Permitted interventions | Explicit subject IDs and schema paths/operations, coordinate frame, units, numerical bounds, cumulative displacement origin, allowed support corrections and observation changes. Default: no unlisted mutation. |
| Execution configuration | Nonsecret model profiles and literal model IDs; generation/assessment roles; capture profiles/cameras/resolutions; simulator/runtime identity; seed policy; timestep/decimation; optional policy/config/checkpoint identity; artifact root policy. |
| Budgets | Total model invocations including generation/critique/repair and retries; realization attempts; simulation steps including settling; repair proposals; additional observations; optional policy episodes/steps; elapsed deadline and per-operation timeout. |
| Effect policy | Read-authorized prior source/database; operational writes; research publication permission (default not requested); optional DCRG permission; principal/authorization reference. Credentials are never contract payloads. |

A required criterion without a supported evidence producer is rejected at admission with `unsupported_criterion`, before paid/GPU work. An admitted producer failing at runtime yields missing/inconclusive evidence and bounded observation/recovery or a truthful stop.

Model profile updates do not mutate an accepted contract. Authorization renewal can replace an expired grant for the same frozen scope, not silently change the model, intervention, database or budget. Such changes require a new contract/run.

### 3.2 Identity and serialization rules

- Separate `operation_id`/idempotency key, `workflow_run_id`, contract digest, candidate ID/digest, decision ID, execution intent ID, attempt ID/generation, realization ID, evidence ID and assessment ID.
- An exact submission retry returns the same accepted request/run. Reusing its key with different canonical inputs is a conflict. The same contract may be deliberately run again using a new operation identity; a contract hash alone must not collapse independent experiments.
- Canonical contract hashing excludes run timestamps/ephemeral grants and includes a schema version. Store the complete validated canonical contract, not `__dict__` string representations of nested objects.
- Retain raw YAML byte digest and canonical parsed-spec digest separately. Version each digest algorithm. Existing workbench and DCRG encodings are not assumed interchangeable; adapters explicitly map them without rewriting historical identities.
- Candidate receipts bind parent candidate, source decision, input contract, canonical/raw spec, actual catalogue and prior snapshot, generator settings, validation/nonconvergence disposition and artifact manifest.
- Evidence binds candidate digest, attempt/generation, realization settings, runtime/asset identity available to the producer, seed/frame conventions, actual step counts, camera/timestamp labels, measurement schema and limitations.
- Assessment binds exact evidence manifest, criterion IDs, assessor/model/rubric versions, actual assessment tier, raw-response digest and structured findings. Missing runtime provenance stays unknown, not inferred from current files.

**Acceptance evidence cohort:** jointly state-dependent scene criteria must be established over one compatible realization, environment/reset identity and observation window. Matching candidate/profile/seed alone does not establish equal realized state: relation-controlled placement can randomize on reset. Record cohort/trial membership and actual state provenance; additional observations after a fresh realization/reset must re-establish affected conjunctive criteria. Do not select visibility from one realization and support from another merely because both passed individually. Multi-episode/seed research criteria may aggregate only under their frozen trial-coverage/aggregation rule, retaining failures and denominators; do not impose a single-realization rule on legitimate policy experiments. Cross-cohort static evidence reuse requires an explicit independence/equivalence rule. Tests must reject complementary scene passes across cohorts, accept a complete compatible cohort, and preserve valid declared multi-trial aggregation.

### 3.3 Separate lifecycle, phase and outcome

Proposed operational states: `pending`, `running`, `blocked_dependencies`, `blocked_authorization`, `reconciliation_required`, `cancel_requested`, `cancelled`, `accepted`, `stopped`, `failed`. These are new workflow states, not replacements for existing legacy job enums such as `succeeded`.

Retain phase independently: dependency readiness, prior retrieval, generation, validation, realization/capture, assessment, repair, optional policy experiment. Criterion verdicts are `established`, `violated`, `inconclusive`, `not_run`; advisory findings do not satisfy required criteria.

A read model exposes scene acceptance, policy outcome, workflow outcome, publication and cleanup separately. A completed worker can produce a rejected candidate; retained evidence from a cancelled attempt does not make the workflow successful.

## 4. Event map: commands, facts, ownership and recovery

Event modeling does **not** require full event sourcing. Use a transactional current-state record plus append-only domain events/receipts in Neo4j. Events describe facts; commands request work. The following names are proposed contracts, not existing APIs.

| Command / precondition | Durable fact and identity | Authoritative producer | Next action / failure behavior |
| --- | --- | --- | --- |
| `SubmitWorkflow`, valid contract and authorized scope | `WorkflowRequested`, accepted operation/run/contract | Application service admission transaction | Exact retry returns same run; unsupported criteria/conflicting key rejects without execution. |
| `CheckWorkflowDependencies`, exact requested scope and authorized bounded probes | `DependencyReadinessRecorded`, profile/instance identities, check time and per-dependency results | Existing host-control boundary plus runtime readiness adapters | Required unavailable/mismatched/unverified dependency blocks expensive execution; check is not inference or permission to start services. Pre-admission failure without Neo4j is reported locally, never represented as a durably accepted run. |
| `RetrievePriors`, source authorized | `PriorSnapshotRetained`, exact consumed context/hash/query/profile | Retrieval adapter plus validated receipt | Generate with this snapshot; required retrieval unavailable stops/blocks, optional fallback explicitly labelled. |
| `GenerateCandidate`, budget reserved | `CandidateProduced`, candidate/spec/prior/catalogue identities | Generation worker; store validates receipt | Validate final returned candidate even if engine reports convergence; no candidate means execution failure. |
| `ValidateCandidate`, exact candidate retained | `CandidateValidationRecorded`, schema/semantic/geometric verdicts | Validation adapter | Realize if admitted; supported invalidity may enter bounded repair, otherwise stop. |
| `RealizeAndCapture`, validated candidate, resource lease | `SceneRealized`, `EvidenceCaptured`, realization and manifest IDs | Owned simulation worker | Assess only complete relevant evidence; preserve partial artifacts and explicit termination/cleanup limits. |
| `AssessEvidence`, matching immutable artifacts | `CriterionAssessmentRecorded`, per-criterion findings | Physical evaluators and image-bound visual assessor | Aggregate against frozen criteria; inconclusive requests permitted observation or stops. |
| `DecideNext`, current workflow version and receipt set | `WorkflowDecisionRecorded`, rationale, reservation, next intent | Coordinator/store transaction | Accept, observe, repair, authorized policy experiment, stop, or reconcile. |
| `RepairCandidate`, explicit correction authority | `CorrectionProposed`, base/new candidate and structural delta | Existing refiner through repair adapter | Reject forbidden/no-effect/out-of-bounds changes; validate and freshly realize admissible candidate. |
| `EvaluatePolicy` / `RunDCRG`, scene prerequisites and experiment permission | `PolicyEvaluationRecorded` / `ExperimentDecisionRecorded` | Existing policy/DCRG engines through evidence adapters | Preserve counts, comparison decision and terminal task result separately; charge outer budget. |
| `CancelWorkflow`, exact active run | `CancellationRequested`, affected attempt generations | Service transaction; process owner performs stop | Fence further release/results; acknowledge terminal cancellation after owned cleanup. |
| `ResumeWorkflow`, retained identity and disposition | `WorkflowResumed` or explicit refusal | Service with current authorization/reconciliation | Continue known pending work; never infer retry permission from process disappearance. |
| `PromoteResearchPrior`, separate publication/eligibility permission | `ResearchPublicationRecorded`, exact source/projection/readback | Existing publication adapter with distinct receipt | Failure cannot rewrite scene acceptance; unknown publication reconciles exact target. |

For every retained event include schema version, run/aggregate identity, causation command, source attempt/decision where applicable, committed sequence and sanitized payload. Timestamps are descriptive, not replay cursors.

### Decision precedence

1. Verify contract/current version, cancellation/authorization state and exact receipt relationships.
2. Reconcile released operations whose outcomes are unknown; do not start substitute work.
3. Validate all required criterion results for the selected candidate.
4. If all requested criteria are established, accept; if only scene prerequisites are established and policy proof is requested, enter the explicitly authorized experiment phase.
5. When established actionable defects coexist with inconclusive criteria, repair first only if the defect, permitted correction and safety preconditions are already established and the repair would invalidate the additional observations. Do not collect evidence known to become obsolete. Uncertainty about the defect or correction itself requires bounded observation before repair.
6. For a supported defect, validate intervention scope and reserve the full next-operation allowance before repair. Otherwise, for insufficient evidence, collect only allowed additional observations within budget or stop `evidence_not_established`.
7. Stop with a named reason for exhausted budget, unsupported correction or no effective progress. Infrastructure errors remain failures/uncertain outcomes, not evidence that the scene is invalid.

## 5. Evidence and physical-semantic fidelity

### 5.1 Criterion-to-producer matrix

| Criterion | Evidence required | Producer / new work | Insufficient substitute |
| --- | --- | --- | --- |
| Correct assets/task | Validated spec/catalogue identity plus realized asset/task binding | Existing schema/catalogues and builder receipt adapter | Requested names or generated YAML alone |
| Realized arrangement | Actual object/support/robot transforms, declared frame and relation checks; selected views where required | Builder/relation-solver outputs plus new bounded telemetry adapter | Edited `initial_pose` or a low solver loss alone |
| Support/stability | Named support, actual measurement samples over a fixed window, support/contact predicate, bounded motion/tolerances, no invalid termination | New measured-support evaluator over existing simulator access | Static image, VLM opinion, or merely executing 40 steps |
| Required-view visibility | Identified cameras and nonempty current frames; specified visual rubric and any required deterministic visibility checks | Existing rendering/capture and VLM adapter; deterministic producer if required | Preview success, another camera, or advisory critic fallback |
| Reachability, when requested | Explicit geometric/kinematic check with frames, limits and supported assumptions | Existing oracle through a criterion-specific adapter | Visibility or successful scene construction |
| Policy task success, when requested | Exact policy identity/config/instruction, completed episode records, unchanged task predicates, seed/count coverage | Existing policy runner/evaluation adapters | VLM task-progress description or DCRG acceptance of lift improvement |

The first scene profile must implement the measured-support producer; it cannot remain a permanently unknown required check. Freeze its thresholds, units, sampling window and predicate definition before the live acceptance run. A result establishes that declared check, not universal physical correctness.

### 5.2 Capture and assessment integration

- Keep `static_preview`, `settled_scene` and `policy_trajectory` as distinct profiles. Existing snapshot worker allows zero simulation steps; do not silently change that contract.
- Capture required views and measurements during the same bounded realization when possible. Do not mandate a second Build merely to enable recording.
- Retain exact realized poses, relation/validator results and solver fallback/nonconvergence. A build that continues after strict placement validation fails does not pass placement acceptance.
- Trace `reified_relations`/authored semantics → ordinary runtime relations → solver inputs → realized poses. Preserve the mapping and explicitly unsupported fields. RDF reification alone is not proof of native RDF-star support, lossless round-tripping or causal truth.
- Reuse `trajectory_capture` and `assess_trajectory`; wrap their existing outputs rather than pretending they already provide physical measurements or per-criterion verdicts.
- Supply actual retained image bytes to `InferenceBackend.multimodal_chat`/supported critic entry points. Record actual tier; missing images, provider failure, malformed output and advisory fallback cannot become visual acceptance.
- The new `execution/scene_assessment.py` adapter must transmit the supported **visual** criterion IDs, subjects, required camera/frame identities and frozen rubric, then validate criterion-specific response coverage. `assess_trajectory` currently has a fixed diagnostic rubric and aggregate response; preserve that public helper contract and reuse its evidence/transport mechanics without relabelling generic `satisfactory` as arbitrary criterion proof. Missing, duplicate or mismatched criterion results cannot establish acceptance; test a positive criterion-aware response as well as those negatives. Physical predicates remain with measured producers.
- Managed image assessment must not invoke `VisualSceneCritic`'s implicit local-provider fallback. Its direct `urllib` path to a default endpoint/model bypasses the existing SDK transport guard. Any supported alternative assessor must be explicitly frozen, authorized and separately budgeted; otherwise cloud failure retains an inconclusive/failure disposition with no local request. Preserve legacy diagnostic fallback behavior outside managed workflows. Current generation calls the critic without images; this is a required boundary for the new image-assessment integration, not a claim that existing managed generation already takes that fallback.
- Preserve policy instruction separately from authored task. Preserve terminal-image unavailability: post-autoreset frames cannot be labelled terminal trajectory evidence.
- Retain capture/assessment before process-terminating simulator shutdown. Reuse nested policy/environment/provider cleanup and nonzero failure-exit behavior.
- Release the simulation/GPU resource before a remote assessment call when no simulator work remains. An extracted worker must not hold a warm renderer lease indefinitely and starve the next realization.

## 6. Permitted repair contract

The actual schema is `ArenaEnvGraphSpec`: `embodiment`, `background`, list-valued `objects`, `relations`, `reified_relations`, `placement_validators`, composite `task` and overrides. Do not implement guards against invented `robot`/object-map fields.

1. Freeze intent constraints at submission. After initial generation, retain the original candidate as the cumulative geometric baseline; it must itself satisfy protected identity/task requirements. If it does not, stop unless the contract explicitly defines a supported identity correction.
2. Build feedback from retained findings and the frozen contract. The model may suggest remedies; free-form text is never an authorization token.
3. Invoke `refine_spec` on the exact base candidate with `publish_to_graph=False` and retained feedback. Do not accidentally invoke New generation or silently retrieve unrelated replacement priors.
4. Compare full canonical specifications. Only allowlisted subject/path/operation deltas pass. Check task parameters, physics, validators, robot/support anchors, registry identities, relations/reifiers and object additions/removals—not only one pose field.
5. Enforce numerical limits in named frames against both the immediate parent and original baseline. Several individually small shifts cannot accumulate beyond the authorized total.
6. Distinguish physical settling during execution from authored support/Z modification. If support-height correction is permitted, name the exact effective runtime parameter and limits; otherwise reject it. DCRG's fixed-Z contract stays unchanged.
7. Validate the final returned candidate, including the refiner's last-iteration/fallback path. Nonconverged output is not automatically rejected as unusable, but it cannot bypass required checks.
8. Produce a correction receipt linking issue IDs, permitted operation, old/new values, structural validation and candidate lineage. Changed-candidate generation consumes repair/model budgets even when its delta is rejected.
9. Re-realize and compare the affected runtime quantities. If the solver overrides an authored pose, classify `no_effective_change`; do not repeatedly authorize an ineffective edit or accept it from text alone.
10. Require fresh relevant evidence for the repaired candidate. Static invariant evidence may be reused only through an explicit dependency rule proving unchanged inputs; the first slice conservatively reruns candidate validation and visual/physical checks.

The banana reference contract preserves DROID, maple table, banana-to-plate semantics, left/right arrangement and specified fixed poses. It authorizes only named placement/support corrections. No changes to gravity, friction, collisions, task thresholds or robot base are allowed to hide a failure.

## 7. Neo4j authority and execution protocol

### 7.1 Persistence boundary, not a replacement Journal sketch

Add a narrow `WorkflowStore` interface for workflow admission, exact lookup, snapshot/events, fenced transition/reservation, attempt claim/release, receipt commit, cancellation, reconciliation and owner cleanup. The concrete `Neo4jWorkflowStore` implements it. These are proposed responsibilities; method signatures are frozen in phase P0 before adapters are split among implementers.

Logical operational labels are proposed as `ArenaWorkflowRun`, `ArenaWorkflowCandidate`, `ArenaWorkflowDecision`, `ArenaExecutionIntent`, `ArenaExecutionAttempt`, `ArenaWorkflowEvidence`, `ArenaCriterionAssessment`, `ArenaWorkflowEvent` and `ArenaWorkflowOwner`. Scope uniqueness to the deployment/workspace where appropriate. Avoid generic labels accidentally consumed by existing research queries.

Retain relationships from run to candidate/intent/decision, candidate to realization/evidence, assessment to exact evidence, and correction to parent/child candidates. Full contracts and receipts use versioned canonical JSON properties or immutable artifact references. Do not store arbitrary nested dictionaries as native Neo4j properties.

Provision constraints/indexes through an explicit administrator-reviewed migration. Runtime constructors inspect readiness, not silently issue DDL against the shared research database. Pin the configured database explicitly in every session and authorization binding; never rely on a driver's default database.

### 7.2 Transaction and concurrency protocol

- Admission serializes on a deployment/workspace admission record, checks exact replay **before** queue capacity, and creates one run. Distinct concurrent keys cannot exceed the defined cap.
- Order submission handling as current boundary authentication/read-scope authorization and pure versioned request normalization, then exact scoped replay/conflict lookup and current public-output screening. Only a fresh submission resolves mutable source/profile/catalogue inputs, captures execution grants and enters capacity admission. Store submitted-request identity separately from any enriched accepted contract. An expired execution grant or unavailable source cannot prevent an otherwise authorized read of retained acceptance; expired authentication/wrong scope is not bypassed. Exact replay issues no grant and dispatches nothing; continuation still requires current execution authority. Serialize/recheck the acceptance key before committing fresh admission so concurrent submitters cannot create competing acceptances.
- The first implementation serializes operational mutations through one scoped control record, then locks the workflow record in a fixed order. Increment/update the shared record before reading protected state and keep the transaction short. Confirm the lock/query behavior with real Neo4j concurrency tests; no production-ready Cypher is claimed here.
- A decision transaction verifies expected run version, active phase, selected candidate membership, complete receipt bindings, valid authorization metadata, applicable fresh dependency readiness and available budget. It creates one stable decision, reservation and execution intent, advances state, and appends its event atomically. Bounded dependency probes run outside this transaction; retain and validate their identity-bound result before release rather than making network probes inside a retried transaction.
- Decision/intent identities derive from the expected transition identity, not a fresh random ID on each evaluation retry. Exact replay returns prior output; conflicting replay fails.
- External inference, simulator launch and publication never occur inside a retried database transaction callback. Bound transaction timeouts; retry only side-effect-free/idempotent persistence operations under the specified driver policy.
- Record reserved, consumed and provably unused/released allocation separately. Generation's internal validation/critic/refiner calls and transport retries share the outer budget. Configure or instrument existing engines so they cannot hide unmetered calls. Disable blind provider retries for released attempts whose completion is unknown.
- Adapt the existing preconstruction guard in `web_api/provider_security.py:bounded_client` into the execution boundary rather than adding an unrelated inference stack. Supply its allowance from the outer reservation and account for actual attempted calls before backend construction, including initialization ping, JSON/prim resolution, repair and multimodal requests across worker contexts. `run_json` telemetry omits constructor/image calls and cannot be the budget authority; the current per-context allowance must not reset the workflow budget. Keep transport retries distinct from semantic validation/repair iterations: setting the agent's shared `max_retries=0` currently removes its semantic loop as well. Exhausted or uncertain transport disposition must escape generic retry/fallback handling without another unreserved call. Regression-test ping/JSON/image/failed calls across multiple contexts, while preserving a positive semantic-validation path with transport retry disabled.
- Enforce wall-clock deadlines in the worker as well as persisted coordinator state. Count startup/recovery time consistently; never reset the overall deadline on resume. Local monotonic time enforces per-process timeout, while durable timestamps/deadline support restart.
- Claim an intent with an exclusive attempt ID/generation and owner epoch. Register exact host/boot/process-group/start identity before committing release authority. Recheck cancellation/authorization immediately before release.
- Receipt commit requires current attempt/generation, expected state, exact candidate/profile/artifact bindings and nonconflicting content. Same receipt replay is idempotent; different bytes under the same identity are rejected. Application create-only methods and restricted writer permissions protect immutable records; uniqueness alone is not immutability against an administrator.
- Store one canonical job/run view, or update state and any serialized projection in the same transaction. Never leave a queued JSON body behind running/completed node properties.

### 7.3 Replay, restart, cancellation and outages

Allocate a monotonic committed sequence from the same scoped control record used to serialize event-producing writes. Do not use `timestamp()` as a cursor. For the first slice, take the short control-record lock when reading snapshot plus cursor so they form one consistent view. Bound event pages, define a retained-prefix floor and report a replay gap requiring snapshot resynchronization. A new workflow stream is distinct from legacy global Journal SSE; merging them later requires a versioned contract, not fabricated comparable cursors.

Replay-page floor/committed-ceiling validation and page materialization must use that same short control-record consistency boundary as prefix pruning, or an explicitly tested equivalent protocol. Reject cursors beyond the committed ceiling as well as below the floor. A pruning race must return a complete eligible ordered page or a replay gap, never a surviving suffix that silently skips events. Test the reader/pruner interleaving; merely placing independent reads in a transaction is not a claimed isolation guarantee.

Only one local execution owner per scope is active initially. Preserve local process/resource locks where they still protect actual processes/artifacts; Neo4j authority does not make OS locks obsolete. Use owner epochs and verified cleanup to reject stale claims. A lease timeout alone is not proof an old simulator/model request stopped.

| Interruption point | Required disposition |
| --- | --- |
| Before execution release | A known unreleased intent may be claimed after owner recovery and authorization checks. |
| After release, before durable result | `reconciliation_required`; inspect exact retained worker receipt/artifacts or provider request handle if available. No automatic fresh call. |
| After receipt commit, before next decision | Reuse the exact verified receipt, confirm cleanup, and evaluate the next transition without repeating completed work. |
| Database commit acknowledgement lost | Read exact decision/intent/receipt identity; absence or inability to read is not automatic permission to repeat external work. |
| Neo4j unavailable during work | Do not release new work. Worker enforces local timeout, retains immutable result artifacts and cleans up; reconnect imports/verifies result under the original fence. Files are recovery evidence, not a second coordinator. |
| Cancellation races with completion | Fence further effects immediately; retain late evidence diagnostically, never overwrite cancellation with acceptance. Terminal cancellation requires cleanup acknowledgement. |
| Worker ownership uncertain | Pause new conflicting resource use and require ownership reconciliation; never kill an unrelated process based only on a recycled PID. |

A late cleanup acknowledgement must name the exact owner/attempt/registration. It cannot clear a replacement worker. Dirty startup preserves paused admission until owned work is reconciled. Resume of one workflow is not the existing whole-queue resume action.

P0 must define an authenticated owner-local stop path for CLI/API cancellation when Neo4j is unavailable. It uses the previously verified run/attempt/process registration, prevents further local release and performs owned cleanup without requiring a database transaction. It cannot accept arbitrary PIDs or trust unauthenticated callers. Retain stop evidence and reconcile it before any subsequent release; report durable cancellation as pending until Neo4j records it. This is a local execution interlock, not a second workflow-state authority. If the owner cannot be reached, report stop delivery as unconfirmed rather than claiming cancellation. Terminating a local provider client does not prove the remote request stopped; its effect and budget remain uncertain until reconciled.

### 7.4 Artifact durability

Use existing immutable storage patterns for spec, PNG/video, raw measurements and raw model responses. Write to owned staging paths, complete/flush artifacts and publish a content-bound manifest before graph receipt acceptance. Read back and verify actual bytes/schema when adopting evidence, not merely stored digest properties.

The filesystem and Neo4j are not one transaction. An artifact with no graph receipt is an orphan/reconciliation input; a graph receipt pointing at missing/corrupt bytes cannot satisfy criteria. Retain partial evidence and avoid overwriting previous attempts. No destructive garbage collection is part of the first slice. Reuse existing path/size/symlink protections and keep credentials out of logs, prompts and receipts.

## 8. Staged Journal migration and compatibility

### Stage A — new workflow ownership, legacy features unchanged

The new workflow and **all its child intents/attempts/results** live in Neo4j. Extract a framework-independent worker execution port from the current Supervisor/EditorExecution; it accepts a released typed intent and returns a typed receipt without directly manipulating SQLite Journal state. Existing legacy wrappers keep using Journal through their existing adapter. The new adapter uses WorkflowStore only.

Two authorities for **different operations** can coexist temporarily; two authorities for the **same operation** cannot. Do not submit a managed child into the legacy SQLite queue and then maintain its authoritative phase in Neo4j. Enforce separate operation namespaces and reject cross-store identity ambiguity.

Reuse the local shared GPU/process exclusion mechanism across old and new execution paths. Before initial native CLI acceptance require legacy conflicting dispatch paused, active conflicting attempts reconciled, and verified retirement/cleanup of any warm renderer. Pause alone does not close a reusable SimApp or release its lease. Use owner-mediated retirement or an already clean inactive legacy owner; the new CLI cannot close another owner's in-memory snapshot object or kill an arbitrary PID. Both paths must resolve the same physical lease file/mount with compatible runtime UID/ownership, and the new worker must actually acquire and retain it before execution. Failed cleanup or unavailable ownership blocks release without unpausing queued jobs. Automatic cross-owner handoff can remain a later dashboard integration; the initial CLI still needs this positive resource-readiness path. Test warm renderer → pause alone still unavailable → acknowledged retirement → CLI acquisition, with legacy jobs remaining queued.

Legacy sessions/model profiles may supply authenticated nonsecret inputs to the new service; a durable workflow authorization snapshot and each release decision belong to Neo4j. Ephemeral credentials stay in the existing private lifecycle. An expired browser credential cannot silently become a durable CLI/server credential.

P0 must produce the already-required positive foreground authorization composition: a local principal lifecycle, private credential resolver and workflow/attempt-binding port over Neo4j, with expiry/revocation and explicit renewal. Extract reusable grant/scope checks from `web_api/workflow_authorization.py`/`execution_grants.py`; do not reuse Journal/session-coupled `resolve()` unchanged or infer execution permission from configured credentials. The later HTTP adapter supplies its authenticated session principal to the same service checks; legacy authorization remains unchanged. A synthetic foreground CLI must release a permitted attempt without an HTTP app or SQLite job, then block its next release after authority expiry; status/replay must remain nondispatching. Exact port signatures remain a P0 selection, not a new authorization framework.

### Stage B — migrate selected existing workflow/job kinds

Before moving an existing kind, inventory these dependencies and their transactions:

| Existing source under `workbench/` | Responsibility to preserve or explicitly leave on legacy authority |
| --- | --- |
| `journal.py` | Admission/idempotency, attempt CAS/release, immutable legacy/modern candidate receipts, authorization renewals/rejections, cancellation, recovery, worker identity, queue state, snapshot/replay/pruning |
| `sessions.py` | Session identity, expiry and ownership; retain initially |
| `model_profile_store.py` | Create-only nonsecret model profiles; retain initially |
| `research_registry.py`, `research_store.py` | Store identity, reservations, artifact commits, lineage and candidate source access |
| `research_publication.py`, `research_retrieval.py` | Publication authorization/effect receipts, worker/reconciliation lifecycle and source selection |
| `research_backup.py` | SQLite snapshot consistency/backup verification; cannot be copied as a Neo4j backup mechanism |

These modules access `journal.db`/`_transaction` directly. Introduce typed persistence/source ports at actual transaction boundaries before replacing a backend. Preserve current successful-job status `succeeded`, event envelopes, exact request recovery, sealed renewals, and cancellation/cleanup behavior for old API callers. Do not claim a drop-in replacement with invented `step/get/list/complete` signatures.

Cutover for each migrated kind:

1. Stop new admissions and quiesce or explicitly classify its active attempts; do not cancel unrelated jobs.
2. Retain a validated legacy snapshot and artifact inventory with a migration manifest.
3. Import immutable IDs, receipts, source bindings and state into an isolated target scope. Missing historical evidence remains legacy/unknown, not newly accepted.
4. Compare counts, exact canonical content, lineage, cancellation/authorization dispositions and artifact availability; exercise read compatibility.
5. Fence the old writer for that kind, activate one routing/ownership manifest, then enable the new writer. Failure before activation leaves legacy authoritative.
6. After Neo4j accepts new writes, rollback means paused reconciliation and a verified reverse migration or continued Neo4j ownership—not simply re-enabling a stale SQLite writer.

Full SQLite retirement only follows migration of every remaining authority and replacement backup/recovery tests. It is deliberately outside the first CLI milestone.

## 9. Graph-RAG, provenance and research eligibility

- Reuse `GraphRAGRetriever.retrieve_prior_snapshot`/existing prior-receipt validation and the managed retrieval behavior in `web_api/generation.py:104–165`. Retain exact context, selected source identities, query/policy, source database, catalogue digest, availability/fallback and context digest **before generation consumes it**.
- New generation retrieves priors; Refine consumes exact candidate and retained feedback. Additional retrieval during repair is a separately declared, authorized and budgeted strategy, not an implied property of Neo4j connectivity.
- Explicitly call both generation and refinement with `publish_to_graph=False`. Their legacy default publication must not leak intermediate managed candidates into research retrieval.
- Existing research queries use `EnvironmentGraph`, reifiers and evaluation records. Define a tested projection/identity mapping into those structures rather than inventing an unconsumed `AcceptedEnvironmentGraph` label.
- Record operational failures/rejected candidates for diagnostic traversal without relabelling them successful priors. Keep structural/unevaluated fallback priors separately labelled from measured successful experience.
- Publication requires separate authority, exact immutable projection/readback and a publication receipt. Successful-prior eligibility additionally requires the declared measured evidence policy; a VLM approval or scene acceptance cannot supply it.
- Preserve relation endpoints, frames, numeric constraints, deciding evaluation ID and provenance in the consumed projection where supported. Explicitly report omissions; a richer stored graph does not prove the model saw those details.
- Stage A requires operational Neo4j persistence but does not require research publication. Introduce a typed workflow-candidate source adapter before routing these candidates through the existing SQL-coupled research save/publication services.

## 10. DCRG integration: optional experiment, not scene repair

Keep `dcrg/` and its measured comparator. Use `run_dcrg` and callable evaluation/proposal interfaces rather than launching a CLI and inferring success from printed text. A fixed owned worker may use subprocess isolation and an explicit receipt protocol; diagnostic stdout is not the domain contract.

Scene criteria are prerequisites, not terminal overall acceptance when policy success is requested. After scene acceptance, the workflow can evaluate a policy only under an explicit frozen policy contract. A policy failure in a valid scene does not by itself authorize changing the scene.

DCRG delegation additionally requires named experiment permission, supported embodiment/task/intervention, baseline evidence and sub-budget. The current bounded target-XY/fixed-Z constraints remain intact; no repair of wrong embodiment, support height or physics is routed into DCRG. DCRG candidate changes must pass the outer preserved constraints and fresh affected scene checks before policy scoring.

Ordinary policy evaluation and DCRG intervention have separate permissions: an authorized fixed-scene evaluation may establish the requested policy criterion without any DCRG permission. Admission rejects a required policy criterion when its producer or evaluation scope is unsupported; the scene-only CLI does not silently accept such a contract. If an admitted evaluation loses renewable authorization, retain `blocked_authorization`; explicit permanent refusal or expiry of the overall deadline stops with `required_evaluation_not_authorized` or `budget_exhausted`, respectively. If measured policy criteria fail and no further authorized evaluation or DCRG correction is available, stop `policy_criteria_not_established`, preserving scene acceptance and measured failure. Do not auto-request broader intervention authority or claim overall acceptance.

Retain separate outcomes: baseline evaluation, proposal admissibility, comparison accept/reject, lift/task counts, experiment terminal condition and outer workflow acceptance. A relative improvement is not full task success. Pin model/config/hand/frame/seed coverage and preserve remote-policy seeding uncertainty.

The current DCRG loop persists local state/manifests. For **managed** DCRG integration, extract a state/evaluation reservation port so Neo4j owns authoritative attempt/decision/budget state; local manifests remain evidence/export. Standalone legacy DCRG runs may retain their existing file authority in a separate namespace. Do not run the old file-owned loop unchanged as a second authoritative managed coordinator. This extraction is a later milestone, not a prerequisite for the scene-only CLI.

### 10.1 VLM-assisted DCRG — hypothesis and unchanged decision authority

**Hypothesis, not a result:** image-grounded assessment may identify invalid scenes before expensive trials, provide useful observations after failures, and help choose among permitted experiments. It may also add cost, incorrect diagnoses and unnecessary observations. Evaluate diagnostic usefulness, measured task outcomes and total cost separately; do not assume more VLM calls improve the method.

Use the same outer workflow and bounded workers. Logical path: requested outcome/criteria/allowed changes/budget → generate or load → validate → realize/observe → assess scene → permitted scene repair and reassessment, or established scene prerequisites → optional policy evaluation → measured performance → authorized DCRG proposal and reevaluation, or explicit terminal outcome. No new service, backend, free-form command agent or second orchestration framework is introduced.

Current source anchors:

- `dcrg/loop.py:67–69,110–134` exposes injected evaluation/proposal/sync boundaries; these are reusable seams, not existing VLM integration.
- `dcrg/loop.py:261–281,441–443` compares matched-count measured task/lift rates lexicographically and separately checks its terminal seed milestone. Preserve both semantics; neither is a robustness claim.
- `dcrg/loop.py:420–438` permits only the unique target's initial-pose XY within the original trust region/support rectangle, preserving Z and all other fields.
- `dcrg_runner.py:235–261` fetches exact per-seed graph feedback and supplies measured `dx/dy/dz` to `relax_spec_active_inference`. A VLM narrative is not a replacement feedback measurement.
- `dcrg/evaluation.py:18–99` requests camera-recorded rollouts; `:102–142` validates episode evidence. `EvaluationEvidence.artifacts` currently contains paths, not a complete frame/episode integrity manifest. Camera recording alone does not provide aligned VLM evidence.

The VLM may affect observation requests and authorized proposal choice, never overwrite measured success/lift fields, relax the experiment contract, or approve a candidate based on appearance. Keep the existing measured comparator unchanged in this workstream. Conflicting visual/measured evidence creates a retained discrepancy requiring deterministic evidence validation or human research review; do not silently rewrite either record or turn suspicion into a causal diagnosis.

### 10.2 The three roles and explicit rule-based routing

| Role | Inputs / permitted output | Application rule | Forbidden shortcut |
| --- | --- | --- | --- |
| Pre-experiment scene assessment | Exact candidate/cohort views, frozen visual rubric, separate geometry/contact measurements; visible defect or insufficient-view finding | Apply §§4–6 scene rules. Establish required physical checks independently. A visual warning can request a bounded observation or supported scene repair before trials. | VLM-only physical certification, quiet exclusion of difficult scenes, or DCRG invoked to fix missing assets/support Z. |
| Post-trial diagnosis | Exact completed evaluation/episode, ordered frames or bounded clips, policy instruction and separately labelled measured events | Record observation, hypothesis, uncertainty and evidence references. Request additional evidence only if authorized and decision-relevant; otherwise report unsupported/unknown. | Treating “occluded target,” “possible slip” or missing camera coverage as proven cause, measured contact, or replacement episode outcome. |
| Proposal guidance | Retained diagnosis plus measured feedback, frozen intervention catalogue, existing safe candidate proposals | Deterministic router validates evidence applicability, tool capability, scope and remaining budgets. It may select a declared proposal ID/strategy, then validate, realize and re-evaluate the resulting candidate. | Model-issued commands, arbitrary YAML edits, invented metric offsets, changes to friction/task gates/controller settings, or appearance-based acceptance. |

Initial routing actions are a closed set: `continue_measured_baseline`, `request_allowed_observation`, `request_supported_scene_repair`, `select_permitted_xy_proposal`, `stop_unsupported`, `stop_budget`. These are proposed typed application decisions, not model-executable tool names. The model's suggested action is untrusted input to the router.

- Insufficient camera evidence → permitted additional observation or explicit inconclusive stop. A new rollout/scene reset has a new evidence cohort and consumes its own reservation; never relabel it as the failed episode's missing terminal frame.
- Scene defect corroborated under declared checks → scene strategy before starting the experiment. Once a policy experiment is frozen, an incompatible scene defect stops that experiment; a newly authorized scene-repair workflow may derive a new scene and requires a new experiment/baseline. Do not carry prior policy scores across that change.
- Observed approach miss/occlusion with applicable measured spatial feedback → consider only existing supported target-XY proposals. If the requested correction requires moving the camera, robot, support, Z or clutter and the experiment forbids it, stop or retain baseline; do not widen DCRG permission.
- Possible transport slip → retain a diagnostic hypothesis. No automatic friction, gripper/controller or task-threshold patch belongs to this environment-only DCRG experiment. A VLM report alone does not demonstrate that target XY can repair the failure.
- Supported scene and no useful diagnosis → follow the predeclared no-advice behavior: retain the deterministic baseline proposer, request a bounded observation, or stop. Required visual criteria still cannot pass on advisory fallback. No implicit provider fallback or unlimited “try again” loop.

### 10.3 Evidence, diagnosis and proposal contracts

Add versioned contracts through the existing P0 domain owner, initially with `vlm_mode=disabled`. Proposed enabled modes are `observe_only`, `diagnose_and_route` and `proposal_guidance`. Freeze the mode, literal model/profile, rubric/prompt version, frame-selection rule, candidate catalogue/rules version, no-advice behavior and independent VLM/observation/proposal budgets in the experiment contract. Changing them starts a new experiment; current standalone resume checks must not reinterpret an old contract as the new mode.

An `EvaluationObservationManifest` must bind exact scene/spec and policy identities, evaluation ID, seed/environment/episode/reset IDs, selected camera, timestamp/step alignment, frame ordering, video/PNG/measurement digests and source-to-extracted-frame mapping. Include before/after context for alleged temporal events, omitted frames, occlusion, recording gaps and terminal/autoreset limitations. Hash actual media and verify it before assessment. Do not use `latest`, infer episode association from a filename alone, interpolate missing evidence as observations or equate nominal video FPS with measured simulator time. If the existing recorder does not retain sufficient alignment metadata, add a bounded recorder/evaluation hook before enabling diagnosis on that evidence; otherwise return `evidence_not_established`.

Use deterministic, bounded frame/clip selection from the retained rollout: sampled context plus declared event windows where timestamps are available. Freeze limits on selected frames, total bytes, clip duration and extraction work; evaluate resulting coverage before calling a model. Reuse the existing trajectory helper's image transport/receipt patterns but do **not** launch its standalone policy rollout merely to obtain an autopsy of a different retained evaluation.

A `VLMTrialAssessment` records status (`observations_available`, `inconclusive`, `failed`), manifest digest, actual model/provider profile, rubric version, raw response digest, and findings. Each finding includes subject, supported category, exact frame/window references, visible observation, separately labelled hypothesis, uncertainty, contradictory evidence and suggested intervention category if any. Self-reported model confidence is not calibrated probability. Strict response validation rejects extra command/code payloads, nonexistent evidence references, nonfinite values and mismatched identities. Zero usable images means no provider call and an inconclusive receipt.

A `GuidanceDecision` records the assessment/measurement identities, permitted strategy or candidate ID, rule version, applicability checks, reason and reserved next intent. A `ProposalBundle` records all offered candidate IDs/spec digests, solver inputs/seeds/settings, individual permission/geometry verdicts and retained ranking/selection rationale. Every selected candidate passes `validate_candidate` against the **original** DCRG spec and the outer scene/contract guards, then fresh relevant scene evidence and a measured rollout. A guidance receipt is not a proposal-acceptance receipt.

For the first prototype, do not translate VLM prose directly into numerical `dx/dy/dz`. Reuse `relax_spec_active_inference` with genuine measured feedback and a fixed, predeclared catalogue of already-supported solver configurations/proposals. If that yields only one distinct valid candidate, guidance cannot claim a ranking benefit: allow it to advise observation/abstention and report that limitation. A richer bounded XY candidate generator requires its own explicit capability/validation gate and must be available identically to the non-VLM comparator. No invented alternative solver behavior is assumed here.

### 10.4 Ownership, budgets and restart

The outer coordinator owns the requested outcome, scene prerequisites, child intents, cumulative budget, cancellation and continuation. The DCRG specialist owns the measured experimental comparison; the VLM adapter owns only its evidence-bound assessment receipt. Persist operational assessment/guidance and candidate lineage in Neo4j with exact causal references; keep large media/response artifacts immutable on disk. Diagnostic hypotheses are not successful research priors or causal facts. Extend research projection/readback only under the separate publication policy.

Managed VLM integration depends on the managed DCRG state port already required above. The current local loop can call `propose` again after an interruption with `pending_proposal=True`; simply adding a paid VLM call inside that callback could duplicate effects on resume. Retain a stable assessment intent/attempt and immutable receipt **before** proposal selection; interrupted released calls reconcile under §7, never silently rerun. Keep local `state.json` as legacy standalone authority only, not a second managed authority.

Reserve inference at the real transport boundary before backend construction, including pings, every selected-view request and any explicit retry. Charge all scene observations, media extraction, proposals, policy baselines, candidate evaluations and repeated trials to the global contract. DCRG's legacy candidate counter excludes baseline; the outer budget must include it. A duplicate candidate/evaluation receipt is reusable evidence only under the same complete experiment contract, not a new independent trial. Release simulator/GPU ownership before remote assessment when capture is complete; reacquire normally for any extra observation/reevaluation. Preserve exact owner-local cancellation and unknown remote-effect disposition.

### 10.5 Implementation units within P6

Paths below are relative to `isaaclab_arena/agentic_environment_generation/` unless stated otherwise. New paths are **proposed**; create only modules needed by the exercised slice. These units refine P6 and reuse P0–P4 contracts rather than creating parallel DTOs or another coordinator.

| Unit | Source / target | Work | Exit gate |
| --- | --- | --- | --- |
| P6-V1 — observation binding | Existing `dcrg/evaluation.py`, `dcrg/loop.py:EvaluationEvidence`, policy recorder hooks; proposed `execution/evaluation_observation.py` | Retain episode-aligned media inventory and bounded frame extraction; preserve original measured episode evidence separately. | Static/synthetic binding tests and real retained-artifact alignment check; missing alignment explicitly rejects temporal diagnosis. |
| P6-V2 — observe-only assessment | Existing `trajectory_assessment.py`, `InferenceBackend`, preconstruction guard; proposed `dcrg/vlm_assessment.py` using shared workflow contracts | Generic task/experiment rubric with ordered evidence, strict findings and no implicit endpoint fallback; append assessment without feeding advice into baseline decisions. | Valid/invalid/empty/mismatched evidence tests; `observe_only` cannot influence proposal selection, measured predicates or comparator decisions on the same supplied evidence. Retained-evidence replay preserves original policy counts/results; online shared-budget early stops remain possible and must be reported as resource effects. |
| P6-V3 — deterministic diagnosis router | Proposed `dcrg/guidance.py`; existing workflow decisions/repairs | Closed rules over structured findings, measured feedback, permissions and capability catalogue; observation/stop/proposal-selection intent. | Every action has a positive authorized path and explicit negative/unsupported path; ambiguous slip/contact never mutates physics or policy. |
| P6-V4 — constrained proposal selection | Existing `spatial_geometric_oracle.py:relax_spec_active_inference`, `dcrg/loop.py:validate_candidate`, extracted runner proposer | Expose measured-feedback proposer as callable core adapter; bounded candidate bundle and selection with identical candidate supply for comparator arms. | Forbidden/cumulative/no-effect candidate rejection and fresh scene validation; no ranking claim for a singleton/duplicate bundle. |
| P6-V5 — durable integration | Managed DCRG state/evaluation ports, shared Neo4j store and workflow coordinator | Bind model assessment/selection attempts, budgets and provenance before effects; add explicit CLI experiment profile through the same service. | Restart after VLM release/result/selection causes no duplicate completed call; no competing local state authority; baseline disabled-mode compatibility passes. |
| P6-V6 — controlled evaluation | Existing DCRG/evaluation tests, proposed `test_dcrg_vlm_assessment.py`, `test_dcrg_guidance.py`, `test_dcrg_vlm_recovery.py`; existing isolated/native harnesses | Run the comparison below only after contract, harness admission and explicit live authorization. | Evidence-backed report of diagnostic accuracy/coverage, task/lift outcomes, interventions and full cost; improvement, no benefit or harm all valid conclusions. |

Dependency order: freeze P6-V1/V2 contracts with P0 owners; implement offline observation/assessment/routing tests while the managed state port is developed; integrate V1–V5 before any effectful guided loop; run V6 after integration and authorization. P6 does not require GraphQL or full legacy migration, and the first scene-only CLI does not wait for VLM-assisted DCRG. Standalone observe-only analysis of explicitly selected retained artifacts may be a separate approved research activity; it must not claim completion of the managed loop.

### 10.6 Experiment: does the VLM improve DCRG?

Pre-register scenario inclusion, intervention catalogue, exact checkpoint/config/hand/frame, model/prompt, candidate generation/rules, matched simulation/placement seeds, episode coverage, independent repetitions, budgets and endpoints before live work. Remote policy stochasticity may not be seeded by the simulator; report that limitation and use repeated trials rather than claiming identical action trajectories. Numerical sample sizes, cost ceilings, tolerances and meaningful-benefit/noninferiority thresholds remain an explicit research-contract selection, not inferred from this plan.

Separate two questions so scene filtering does not masquerade as a better optimizer:

1. **Preflight utility:** on a fixed included collection containing independently verified valid and defective scenes, compare measured/heuristic checks with those checks plus VLM observations. Measure detected defects, false alarms, abstentions, missed defects and avoided/added work. Report all admitted scenes, including stops; do not compare policy success only on the VLM-selected easier subset. Any oracle-invalid scene stops under the same shared safety rules in every arm.
2. **Policy-refinement utility:** start from the same scene-qualified initial specification in each arm, with the same policy, allowed XY region, measured feedback and episode/task predicates. Compare no-advice DCRG with bounded VLM diagnosis/routing and, only where a real candidate choice exists, proposal guidance. Test final candidates on predeclared held-out seeds/repetitions not used for selection. Do not feed held-out outcomes into further repair/ranking.

| Arm | VLM role | Comparison purpose |
| --- | --- | --- |
| B0 — no advice | No VLM calls; existing deterministic proposer under the shared managed/evidence protocol | Method baseline, distinct from legacy-versus-new infrastructure benchmarking. |
| B1 — observe only | Retain diagnosis on identical recorded evidence without feeding it into routing/proposal decisions | Measure diagnostic usefulness and added model cost without attributing policy changes to advice. Offline replay is labelled replay, not new policy evidence. |
| B2 — diagnosis/routing | VLM findings may trigger only declared observation/abstention or permitted existing strategy; non-VLM proposal order unchanged | Isolate value/cost of additional observations and supported routing. No pose is generated from free text. |
| B3 — proposal guidance | Same allowed candidate bundle/budget as comparator, with validated VLM-informed selection | Isolate selection value. If no meaningful multiple-candidate interface exists, this arm remains unsupported rather than fabricated. |

Use retained-evidence replay as B1's primary diagnostic control: annotation cannot alter the already-recorded policy counts/outcomes, and its extra cost is separately recorded. If observe-only assessment is also run online, its latency/cost may exhaust a shared deadline or allowance even without advice entering the controller; label such earlier stops as resource effects, not advice-induced decisions or silent exclusions. A fixed-policy-allowance comparison freezes the same permitted policy work and reports actual completed counts, auxiliary work and total cost. It does not guarantee identical outcomes from fresh stochastic trials. Under a fixed total cost/time ceiling, fewer policy evaluations due to model overhead are a legitimate measured disadvantage.

Hold candidate-generation capability and basic capture/physical checks constant when comparing advice modes. If a new candidate bundle generator is introduced, add its deterministic non-VLM selection control; do not attribute a larger search space to the VLM. Use both a fixed policy-evaluation allowance with full auxiliary costs reported and a fixed total cost/time budget comparison. Additional observations and model calls may leave less rollout budget; do not give the VLM arm free compute. Retain failed, rejected, indeterminate and stopped attempts in the trial accounting; missing cost data is unknown, not zero. Randomize/interleave execution order where practical to reduce service/cache/order confounding.

Primary task endpoints come from unchanged measured predicates: success and sustained-lift counts with denominators, terminal outcome, evaluations/time/cost to the declared milestone, and held-out outcome of the selected candidate. Diagnostic endpoints include blinded human/measurement-supported annotation agreement on **observable findings**, evidence-reference correctness, abstention/coverage, unsupported-intervention suggestion rate and added observation utility. Annotators may label an event ambiguous; neither another VLM nor model self-confidence is causal ground truth. Diagnose causal claims only through a separately designed intervention study, not ordinary agreement scoring.

Count episode and experiment units explicitly: aggregate/per-seed graph records represent the same episodes and cannot both enter the denominator; episodes within one run are not automatically independent repetitions. Report uncertainty at the preregistered experimental unit, disclose pairing and missingness, and preserve per-run raw results. The legacy “one success per requested seed” terminal milestone alone is insufficient evidence of improved transfer or robustness.

Keep the VLM feature opt-in/disabled by default until its declared utility gate passes. A successful integration without demonstrated benefit is a valid technical milestone, not proof that VLM-assisted DCRG should become the default. Archive negative/harmful results and stop at the approved research budget; no automatic prompt tuning on held-out trials.

### 10.7 VLM/DCRG regression and acceptance cases

- Missing/corrupt media, wrong evaluation/episode/seed, mismatched frame ordering or unknown reset alignment → no usable diagnosis; no invented contact/slip verdict.
- Generic satisfactory, contradictory observations, invalid evidence citations, duplicate findings, injection-like command text or proposed out-of-scope mutation → strict rejection/inconclusive/rule refusal; no arbitrary execution.
- “Looks improved” plus lower measured task/lift comparison → candidate remains rejected under the unchanged comparator. Useful diagnostic text never changes measured score.
- Allowed observation produces a new realization → require its own identity/cohort and full charged budget; old and new passing criteria cannot be combined opportunistically.
- Valid measured XY proposal and supported visual guidance → full structural/scene checks, matched-count fresh measured evaluation, then existing accept/reject semantics.
- Apparent slip suggests friction/controller/task-gate change → unsupported in this environment experiment; retain diagnosis without applying it.
- Duplicate proposal, exhausted reservation, cloud failure with implicit local fallback available, or interruption after model release → no unreserved/duplicate effect; exact receipts and uncertainty disposition retained.
- `vlm_mode=disabled` preserves baseline behavior; observe-only assessment content cannot affect routing or comparator decisions, while shared-budget resource stops remain explicit. Test retained-replay invariance separately from online budget-induced early stopping. Candidate-bundle controls and aggregate/per-seed deduplication remain explicit.

Add these cases to P0-07/P6 test admission and record separately which are synthetic, real retained-artifact checks, real provider integration or controlled native trials. No case is marked executed by this planning update.

## 11. Source-to-target extraction map

Aliases in this section: `C/` = `isaaclab_arena/agentic_environment_generation/`; `E/` = `isaaclab_arena_examples/agentic_environment_generation/`; `W/` = `E/web_api/`. Targets marked **new** are proposed, not implemented modules.

| Existing source / callable | Proposed owner and change | Compatibility / acceptance obligation |
| --- | --- | --- |
| `E/environment_generation_runner.py:255` `resolve_env_spec`; `:439` `run_auto_heal` | **new** `C/execution/generation.py` wraps generation/refinement; `C/workflow/service.py` owns new workflow decisions. Extract healing invocation later only where reused. | Preserve legacy `resolve/build/full/auto_heal` CLI behavior; do not silently replace their side effects. |
| `C/environment_generation_agent.py:139,390` `generate_spec/refine_spec`; `W/generation.py:104` `_generate` | Retain engine; extract reusable catalogue/prior/config/validation logic into new generation/prior adapters | Meter nested calls, preserve New/Refine semantics, disable managed publication, revalidate fallback output. |
| `C/visual_critic.py:322–354` `PhysXPreflightCritic` | Retain as specification-level preflight/advisory check; classify in `workflow/assessments.py` | Authored-coordinate heuristics cannot satisfy measured support/stability; zero reported issues may mean inputs were skipped. |
| `C/spatial_geometric_oracle.py:455–568` `relax_spec_spatial_factor_graph`; `:603` `relax_spec_active_inference` | Keep distinct general grounding and measured-feedback constrained-proposal adapters | General relaxation can alter robot/furniture/object poses; full contract guards must reject forbidden changes. It is not the fixed-Z target-XY DCRG proposer. |
| `C/eval_self_healing.py` diagnostic/remediation engines; runner `run_auto_heal` | Explicit retained legacy/deferred integration, not the managed scene-repair strategy | Never import latest-directory inference, missing-metric zero defaults or policy patches into the evidence-bound workflow; any later reuse requires exact provenance and separate intervention permission. |
| `W/provider_security.py:65` `bounded_client`; `C/inference_backend.py` constructor/JSON/multimodal paths; `C/visual_critic.py` | Extract/adapt preconstruction transport guard into `C/execution/` with the workflow reservation | Count actual attempts across contexts, separate transport/semantic retries, and forbid implicit managed provider fallback. |
| `C/graph_rag.py`, `C/prior_receipt.py`, `W/graph_access.py` and managed retrieval wiring | **new** `C/execution/priors.py` calls existing retriever/validators | Retain exact consumed snapshot and explicit database/authorization; no duplicate retriever. |
| `E/environment_generation_runner.py:660,712,733` builder/zero-action execution; `W/build_worker.py:19` `run_build` | **new** `C/execution/scene_capture.py` and owned worker entry point extract callable realization | Eliminate core imports of example runner and temporary `sys.argv` bridges; preserve legacy Build's current narrow proof. |
| `C/trajectory_capture.py:12`, `C/trajectory_assessment.py:48`; `isaaclab_arena_examples/tools/render_policy_trajectory.py` | Retain reusable helpers in place; **new** `C/execution/scene_assessment.py` adapts visual receipt; `C/workflow/assessments.py` evaluates criterion coverage | Preserve generic prompt, effective instruction, actual steps, pre-cleanup receipt and autoreset limits. |
| `W/snapshot_worker.py:24`, `snapshot_service.py`, `snapshot_process.py`; `E/review_gui/simapp/{render_identity,sim_preview,thumbnail_capture}.py` | Extract only required framework-independent rendering/process capabilities into `C/execution/`; keep GUI presentation and snapshot API wrappers | Zero-step preview stays separate; preserve renderer identity/cache semantics and GPU lease retirement. |
| `W/supervisor.py:42` `run`; `W/editor_execution.py:57,145` execution paths; ownership helpers | **new** `C/execution/supervisor.py`, `process_lifecycle.py`, worker ports | Coordinator not queued behind its own child; retain attempt release, process-group identity, cancellation and cleanup. |
| `C/workbench/journal.py` and direct SQL consumers in section 8 | **new** `C/workflow/store.py`, `neo4j_store.py`; legacy Journal adapter unchanged initially | New workflow bypasses SQL queue; migrated old kinds require explicit compatibility/cutover tests. |
| `isaaclab_arena/environment_spec/arena_env_graph_spec.py`, `arena_env_graph_conversion_utils.py`; relation solver and placer | **new** `C/workflow/repairs.py`, `C/execution/measurements.py` consume actual schema/runtime results | No parallel environment schema; full delta comparison, semantic/runtime fidelity, measured support evidence. |
| `isaaclab_arena/evaluation/policy_runner.py`; `W/evaluation_worker.py` | **new** `C/execution/policy_evaluation.py` reuses native runner through callable hooks | Preserve policy provenance, telemetry, task predicates, actual episode counts and local-only effect controls. |
| `C/dcrg/loop.py:110` `run_dcrg`; `E/dcrg_runner.py` | Later managed state-port/evaluation adapter; retain standalone CLI wrapper | No duplicated state authority; supported contract only; outer budget includes every nested experiment. |
| `E/managed_workflow_cli.py:771` `run_managed` | Keep legacy exact-request client; **new** `C/interfaces/cli/generate_and_verify.py` | New command explicitly distinguished from managed `resolve`; no accidental replay/publication or credentials migration. |
| `W/application.py`, existing routes/security/grants | **new** `C/interfaces/http/` adapter plus existing app composition | HTTP session/origin/CSRF stays at boundary; execution scope enforced in service for CLI too. |
| `W/workflow_authorization.py`, `execution_grants.py` | Extract reusable authorization/credential-binding port for core composition; retain legacy session/Journal adapter | P0 specifies foreground local principal and Neo4j attempt bindings; positive release and expiry/revocation tests precede CLI integration. |
| `docker/workbench/control.py`, existing workbench launcher; `W/readiness.py`, `readiness_process.py`, `policy_readiness.py`, `provider_readiness.py`, `resource_readiness.py` | P0-05 reuses host bootstrap/control and extracts callable runtime readiness checks into the shared application admission path | Host entrypoint remains outside a stopped Arena container; no general Docker access in core. Mandatory pre-model gate, including constructor ping prevention; preserve current startup authorization and paused queues. |
| `web/arena-workbench/src/{editor,editor-jobs,app}.tsx` | Extend existing editor/job views after CLI acceptance | One workflow submission; criterion/evidence/repair timeline; refresh observes retained identity, not resubmission. |

### Proposed minimal package additions

```text
isaaclab_arena/agentic_environment_generation/
  ...existing generation, graph, geometry and trajectory engines retained...
  workflow/                 # NEW
    contracts.py            # versioned domain/wire contracts
    service.py              # submit, inspect, cancel, resume boundaries
    coordinator.py          # short-step routing
    decisions.py            # pure criterion/budget decision rules
    assessments.py          # criterion/evidence binding and aggregation
    repairs.py              # structural permissions and delta validation
    store.py                # persistence port
    neo4j_store.py           # transactional implementation
  execution/                # NEW; add only exercised adapters
    supervisor.py
    process_lifecycle.py
    priors.py
    generation.py
    scene_capture.py
    measurements.py
    scene_assessment.py
    policy_evaluation.py    # later optional policy phase
    workers/
  interfaces/               # NEW
    cli/generate_and_verify.py
    http/
  dcrg/                     # retained; managed integration later
  workbench/                # retained legacy/editor/research services
```

Dependency tests cover the extracted closure, not just the new folder names. Core services/workers must not import examples indirectly through a moved wrapper. Keep policy-runner simulator imports deferred. HTTP/framework imports belong to interfaces; domain decisions depend on contracts/ports, not Neo4j or simulator classes. Register the concrete store/adapters at the composition root. Tests remain in existing test directories.

## 12. CLI, read model and later dashboard/GraphQL contract

### Proposed CLI surface — not runnable at this baseline

The new module's planned verbs are `run`, `status`, `cancel`, `resume`. `run` accepts an explicit versioned contract file and operation ID, durably submits once, then drives/observes the application-owned loop. The contract can contain a prompt for New generation; a base YAML is not required.

Illustrative syntax only:

```text
/isaac-sim/python.sh -m isaaclab_arena.agentic_environment_generation.interfaces.cli.generate_and_verify run --contract <contract.json> --operation-id <stable-id>
/isaac-sim/python.sh -m isaaclab_arena.agentic_environment_generation.interfaces.cli.generate_and_verify status --run-id <retained-run-id>
/isaac-sim/python.sh -m isaaclab_arena.agentic_environment_generation.interfaces.cli.generate_and_verify cancel --run-id <retained-run-id>
/isaac-sim/python.sh -m isaaclab_arena.agentic_environment_generation.interfaces.cli.generate_and_verify resume --run-id <retained-run-id>
```

Run from the discovered clone's simulation container as its nonroot user; do not hardcode container names/ports. Neo4j/model configuration uses existing trusted profile plumbing, not secrets on argv or embedded in contract files. Document worker-visible endpoints and runtime prerequisites before the first runnable release.

For the initial foreground CLI, loss of its execution owner stops/cleans owned workers and leaves recoverable state; uninterrupted background completion after terminal loss is not promised. The later API host supplies the long-lived owner using the same service. `status` never launches work; `resume` reconciles exact state before continuation and cannot change the accepted contract.

Return a machine-readable run handle immediately after durable acceptance, before expensive work. Retain it through disconnected observation. Final output includes candidate/artifact identities, criterion verdicts and evidence, decision/stop reason, consumed/remaining budgets, experiment/publication dispositions and cleanup/recovery status. Submission acceptance is not workflow acceptance. Define/document exit codes distinguishing accepted, nonaccepted terminal, blocked/unknown, cancelled and execution error in P0.

The current UI/API is FastAPI HTTP plus existing job observation, not GraphQL. First add typed service adapters preserving current routes. After the CLI gate, define GraphQL commands/read models for start, inspect, cancel and explicitly resume blocked work; select/admit a dependency separately because none is currently declared. Resolvers cannot implement a second coordinator.

The dashboard retains the accepted run ID, displays original/repaired candidates and per-criterion evidence, and recovers via exact read. TanStack Query is an ephemeral cache. Refresh/navigation/polling cannot reauthorize or dispatch. Cancel/resume are workflow-specific and distinct from global queue controls. Preserve the existing editor draft/save/library contracts; applying an accepted candidate to a draft is explicit, not automatic.

### 12.1 Bootstrap/readiness admission — before any model call

**Owner: P0-05**, with P0-06 supplying the guarded provider-construction boundary and P0-07 owning regressions. Keep this small: a host-side entrypoint over existing startup controls, a shared readiness result, and an admission check before expensive work. Do not introduce another service or orchestrator.

1. The host-side entrypoint discovers the approved existing Arena/Neo4j/selected-policy instances from the deployment profile. It runs outside Arena so it can report or recover a stopped runtime. Default behavior is check-and-report; only an explicitly authorized start request may use the existing helper to start missing approved services. Do not recreate containers, switch models, download weights, alter schemas or resume queues as an implicit convenience.
2. Derive the dependency set from the **whole requested outcome**, before generation. A full GR00T/DCRG request must check the selected policy server up front, not spend generation tokens and discover it missing later. A scene-only contract does not require a policy server. Hosted generation/VLM endpoints need not be local containers.
3. Once the runtime is reachable, perform bounded, non-inference readiness checks through its actual nonroot worker configuration/network/credential path. Reuse existing probes; container-running status alone is insufficient. Do not construct `InferenceBackend` for checking: its initializer calls `_ping`, which is an inference request.
4. Before the first generation/assessment backend is constructed, require all checks declared mandatory by the workflow profile to pass. Retain a small result with check time, profile revision, expected/observed service identities, per-check status, static blocker code and suggested operator action; exclude credentials/raw errors. Unknown or unsupported required checks are not passes. Provider metadata reads do not prove inference quality or guaranteed availability.
5. Recheck relevant ephemeral identities/availability at each expensive operation's release, especially after waiting, restart or configuration change. Readiness is not a resource reservation: acquire the actual execution/GPU lease under §8. A service may fail after a check; preserve the existing bounded failure/reconciliation behavior rather than promising zero failure or zero sunk cost.

| Dependency | Required for | Pre-execution evidence / limit |
| --- | --- | --- |
| Arena runtime | Scene realization and all policy workflows | Intended clone/image/runtime user, required packages/worker capabilities, artifact access and applicable resource checks. A stopped runtime is handled by the host entrypoint, not an in-container self-start. |
| Neo4j | Every new managed workflow | Intended endpoint/database, authenticated bounded access, required operational schema and authorized store capability; research-prior availability remains a separate result. Do not create a replacement empty database or run DDL during readiness. |
| Generation model and required assessment VLM | Each requested model-backed stage | Exact frozen model/provider configuration and current private authorization; supported non-inference endpoint/metadata checks according to the readiness profile. No completion, multimodal call or initialization ping is a health check. Unsupported required verification reports a blocker rather than a false ready result. |
| Selected GR00T/other policy server | Requested policy evaluation or DCRG, not scene-only work | Protocol responsiveness, expected serving/checkpoint identity, compatible modalities and required transport evidence through the runtime client. TCP listening alone is insufficient. Policy inference smoke is separately authorized, not hidden inside this gate. |
| GPU/process resources | Simulation and applicable local policy execution | Relevant resource/ownership checks and acknowledged warm-renderer retirement, followed by actual lease acquisition before execution; observed headroom is not an OOM guarantee. |

Reuse [the existing research-stack readiness design](dashboard_cli_workflow_parity/research-stack-readiness.md) and [host-control contract](../../../docker/workbench/CONTROL.md) for the lifecycle boundary, while treating their historical approvals/deployment observations as history—not new permission. Service startup, dependency probing and research execution remain separate authorized effects. The startup helper must preserve startup-only entrypoints and paused workload recovery; it is not a second workflow-state authority.

On fresh submission, missing required dependencies return a structured `dependencies_not_ready` result and no model execution. If Neo4j is unavailable before any admission attempt, return `accepted=false` with local diagnostics and retain the caller's operation ID for exact retry; do not manufacture a workflow receipt. If admission may have committed but its acknowledgement is lost, report admission as unknown instead of asserting `accepted=false`, then perform exact readback under §7.2. If a run is already accepted and the store is reachable, record `blocked_dependencies` with its blockers; if the store is unavailable, report durable disposition as unknown and reconcile before continuation. Known unreleased work may continue after explicit resume and successful recheck under the same contract/budget; already released uncertain work still requires reconciliation. Deadline expiry preserves a truthful stop/unknown outcome and cannot reset the budget.

Exact accepted-request replay and `status` remain read-only under §7.2: do not demand renewed execution readiness, start services or issue a grant merely to retrieve prior acceptance. Fresh execution/resume passes the gate; observation does not. A failed readiness check never releases unrelated queued jobs.

**Required regression: unavailable required dependency → zero model calls, including initialization pings.** Add proposed `isaaclab_arena/tests/test_environment_workflow_readiness.py` through P0-07's existing exact-file admission, reusing current readiness/paused-start/provider tests and synthetic service probes. Verify:

- Each required dependency independently stopped, unreachable, mismatched or unverified prevents generation/assessment backend construction and records **zero** SDK completions, multimodal calls, `_ping` requests and direct-HTTP fallback calls. Test the composed `run` admission path, not just a readiness helper in isolation.
- Stopped Arena is caught at the host entrypoint without invoking the runtime/model; Neo4j outage produces no false durable acceptance. Startup probes are mocked—no real containers or accounts are touched by these regressions.
- Scene-only readiness succeeds without GR00T; the same absent GR00T blocks a full policy/DCRG contract before its first LLM call. An all-ready positive control reaches exactly the expected synthetic model boundary under a reserved budget, proving the gate does not reject every workflow.
- A dependency lost or replaced between stages blocks the **next** model/evaluation release without repeating completed calls; preserve already-spent budget and evidence.
- Exact replay/status does not probe/start dependencies or dispatch; authorized startup leaves legacy jobs paused; explicit resume rechecks readiness but never blindly retries an uncertain released operation.

These are implementation requirements, not tests executed by this documentation update. Any changes to the existing `docker/` host entrypoint still require the repository's separate approval before code changes or live starts.

## 13. Phased action plan and gates

All implementation phases below are **not started**. The design review and this documentation update do not complete P0. Each phase closes only with its stated evidence, not with a file-count or test-count claim. No commits/pushes are implied.

| Phase | Work / files | Entry dependencies | Exit evidence |
| --- | --- | --- | --- |
| P0 — freeze contracts and compatibility | Complete P0-01 through P0-07 below: freeze shared contracts, evidence/repair profile, store/worker/authorization boundaries, provider budgets, harness admission and CLI result mapping. | Approved implementation scope; fresh source audit | P0 handoff checklist satisfied, including admitted pure contract tests and concrete measured-support producer design/thresholds; no inferred criterion coverage. |
| P1 — authority and execution lifecycle | Implement Neo4j store, short coordinator transitions, authorization/fencing, resource/process port, event cursor and artifacts/reconciliation behavior. Preserve legacy wrappers. | P0; approved isolated Neo4j test scope/schema | Real transaction race/crash tests with deterministic stub workers; exact retry/conflict, budget/cancellation/replay/outage cases; no model/GPU calls. |
| P2 — adapters and physical evidence | Extract needed builder/render/process helpers; add prior/generation, capture/measurement, assessment and repair adapters; wire decision routing. | P0/P1 shared interfaces | Synthetic full loop and failure tests; actual-schema delta and runtime-fidelity regressions; generator consumes the retained prior snapshot without re-retrieval; published-but-unmeasured fixtures cannot enter measured-success retrieval; imports/legacy wrapper compatibility; all nested costs metered. |
| P3 — complete CLI vertical slice | Implement host bootstrap/readiness gate and runtime run/status/cancel/resume using shared service; document configuration/identity/output. | P1/P2; P0-05 dependency contract | Required-dependency failure yields zero model calls including initialization pings; all-ready synthetic control reaches autonomous repair/reassessment; truthful inspect/cancel/resume/stop/restart with no external feedback. |
| P4 — bounded native acceptance | Exercise real generation/render/physical measurement/VLM/repair/rerender path under a predeclared live contract. | P3; explicit live budgets, credentials scope, database namespace, GPU ownership and artifact location approved | Real before/after evidence, criterion records, autonomous decision chain, unsupported stop and no duplicate completed work on resume. Failure is retained, not replaced with synthetic evidence. |
| P5 — existing dashboard and HTTP/GraphQL | Add service adapters and one integrated workflow UI; share read model; retain draft/library semantics; implement selected GraphQL adapter without duplicate orchestration. | P4 accepted for declared scene profile | Real mounted submission/status/evidence journey and refresh recovery; cancel/scope checks; exact same workflow identities as CLI. No claim to fix unrelated refresh bugs without reproduction. |
| P6 — optional policy/DCRG integration | Policy evidence adapter, DCRG managed state port, outer reservations and the opt-in P6-V1–V6 VLM work packages in §10; separate research-source/publication mapping. | Scene workflow gates; approved experiment/eligibility contract; P0/P1 execution boundaries | Supported measured experiment with unchanged comparator/task/physics; scene revalidation; no second authority; VLM diagnosis/routing/proposal guidance evaluated against no-advice controls for utility and full cost, not presumed improvement. |
| P7 — selected legacy migrations | Migrate explicitly chosen job kinds/direct SQL consumers using section 8; complete retirement only after full inventory | Per-kind dependency/transaction inventory and approved cutover | Import/readback equivalence, old-writer fencing, compatibility/replay/backup and rollback rehearsal. |

Parallelism: once P0 freezes interfaces, Neo4j/lifecycle and pure evidence/repair work can proceed independently; integration waits for both. Do not assign concurrent edits to the same source extraction. Reuse the existing harness and give every implementation owner its exact admitted test paths. Do not make a general persistence rewrite block the smallest working scene slice.

### 13.1 P0 work packages — what to freeze before implementation fan-out

Owners below are responsibility roles to assign when implementation is authorized, not additional services or already assigned people. New production/test files remain **proposed**. Use the aliases `C/`, `W/` and `E/` from section 11. One contracts owner integrates edits to shared `workflow/contracts.py`/`store.py`; other owners propose changes through that owner rather than editing those files concurrently.

| Package | Accountable role | Existing source / proposed destination | Concrete P0 deliverable | Completion evidence / dependency |
| --- | --- | --- | --- | --- |
| P0-01 | Domain-contract owner | Existing spec/receipt conventions; proposed `C/workflow/contracts.py`, `service.py`, `decisions.py` and core contract tests | Versioned submitted-request and enriched accepted-contract schemas; identity/hash rules; lifecycle/phase/criterion enums; bounded service inputs/outputs for submit, inspect, cancel and resume; CLI result/exit-code mapping. Freeze each command's expected state, allowed effect and response before adapters implement it. | Valid/invalid pure construction and serialization fixtures; exact retry/conflict fixtures; new generation accepts a prompt without a base; importing/constructing requests does not load the runtime. Harness owner admits tests before execution. |
| P0-02 | Evidence/profile owner | `ArenaEnvGraphSpec`, graph conversion, relation solver/placer, task/measurement access, trajectory helpers; proposed `C/execution/measurements.py`, `scene_assessment.py`, `C/workflow/assessments.py` | One supported scene-verification profile: exact registered embodiment/background/object/task IDs, required views, per-criterion producers, compatible realization/reset/window cohort, measured-support predicate and threshold units, visual rubric/response coverage, unsupported-criterion behavior. Pin which runtime fields provide each measurement and which must be newly instrumented. | Producer matrix has no required criterion without a producer design. Complete-cohort positive and complementary-cohort negative examples; visual response cannot certify contact. Numerical thresholds and observation windows are explicit proposed contract values with rationale, not claims of calibration or measurements. Depends on P0-01 identities. |
| P0-03 | Repair/fidelity owner | `refine_spec`, actual spec schema/conversion, relations and DCRG candidate guard; proposed `C/workflow/repairs.py`, `C/execution/generation.py` | Full-spec allowlist/delta contract for the P0-02 profile: permitted subject/path/operation, coordinate frame, cumulative bound against original candidate, protected fields and effective relation/pose consumers. Define issue → authorized correction → candidate → fresh evidence routing, including ineffective/final-fallback output. | Schema-level positive/negative delta fixtures; semantic-to-runtime field map; realized-effect check design. A supported correction must have an effective consumer, not just a changed YAML coordinate. Depends on P0-01/02; no relaxation of physics/task gates. |
| P0-04 | Persistence/lifecycle owner | Journal admission/attempt/replay/recovery, artifact storage and release/cleanup callers; proposed `C/workflow/store.py`, `neo4j_store.py`, `coordinator.py` | Exact store port and transaction table: request replay before mutable resolution; expected-version decision/reservation/intent commit; current-attempt release/receipt commit; cancellation/reconciliation; event-page/prune consistency. Define immutable artifact adoption and current-state/receipt authority for every transition. | Transition table includes positive path, forbidden transitions and interruption before/after each release/commit. Prepare isolated Neo4j schema/transaction-test specification for P1; no shared DDL or database call is part of P0 documentation. Depends on P0-01; coordinates identity/cleanup contract with P0-05. |
| P0-05 | Execution/authorization owner | Existing host control/launcher and `W/readiness.py`/policy/provider/resource probes; `W/workflow_authorization.py`, `execution_grants.py`, `supervisor.py`, `editor_execution.py`, process ownership/GPU helpers; proposed shared execution/admission ports | Bootstrap/readiness stage in §12.1: outcome-specific full dependency set, host entrypoint outside Arena, non-inference worker-path checks before backend construction, structured blocked result and per-release recheck. Retain local-principal/resolver, Neo4j attempt/grant binding, shared CLI/HTTP scope checks, worker envelopes, exact cleanup, owner-local stop and renderer retirement. | Required unavailable dependency → zero model calls including initialization pings; all-ready positive and scene-only-without-policy controls. Positive release without HTTP/SQLite job; expiry blocks next release; replay stays read-only; no queue resume/start authority inferred. Depends on P0-01/P0-04 and P0-06/07 guards/tests; no arbitrary PID/endpoint/credential acceptance. |
| P0-06 | Provider-budget owner | `W/provider_security.py:bounded_client`, `InferenceBackend`, agent semantic loops, critic fallback; proposed generation/assessment execution adapters | Shared invocation-reservation/attempt-accounting interface installed before backend construction; count ping, JSON, prim-resolution, image, repair and failed/unknown calls across contexts. Separate transport retry policy from semantic repair allowance. Explicitly disable implicit managed local-VLM fallback. | Synthetic invocation-sequence fixtures prove reservation cannot reset on worker/context recreation; exhausted or uncertain work cannot invoke another provider; semantic validation still runs with transport retry disabled. Depends on P0-01 and P0-04/05 reservation/release identities. |
| P0-07 | Verification/integration owner | Existing `scripts/run-functional-checks.py`, `functional-v7/stage.py`/`backend_checks.py`, compatibility suites; proposed core/CLI tests | Exact test admission and core/API/runtime profile matrix for all P0/P1/P2 owners; fixture/artifact boundaries; command register labelled runnable only after verified admission. Map scenarios A–O and review findings to suites and later live gates. Specify the first CLI vertical journey and retained output bundle. | Selection/staging regressions preserve denial; each implementation owner receives a verified exact offline command before work starts. Real Neo4j and native/GPU/provider tests remain separately scoped. Starts with P0-01 fixture inventory; final handoff depends on P0-02 through P0-06. |

### 13.2 Execution order and P0 handoff

1. Assign the contracts and harness owners first. Agree on pure request/receipt skeletons and exact test staging; do not start parallel implementations against independently invented schemas.
2. Explore/freeze P0-02/03 together and P0-04/05 together. The evidence pair settles what a valid observation/correction means; the lifecycle pair settles when an effect may run and how its result is adopted. P0-06 joins the lifecycle pair before any real provider adapter is released.
3. Integrate one synthetic transition walkthrough: host/runtime dependency checks → durably accepted prompt with pre-model readiness gate → retained prior snapshot → candidate → validated realization/cohort → criterion assessment → permitted correction → new candidate/cohort → declared acceptance. Also walk unavailable dependencies with zero model calls, missing physical proof, forbidden change, lost admission response, interrupted release, cancellation/outage and budget exhaustion.
4. Freeze the versioned interfaces through the contracts owner. Record disagreements as explicit unresolved selections; do not bury them in provider defaults or implementation assumptions.
5. Close P0 only against the handoff checklist below. Then P1 may implement the durable store/lifecycle while P2 builds pure adapter/criterion logic against the frozen ports; integrated worker execution waits for P1's release/receipt gates. P3 consumes those shared components, not a separate coordinator.

P0 handoff checklist — every item remains **open** until implementation supplies its evidence:

- [ ] P0-01 request/result/identity contracts and CLI outcomes are versioned; positive and negative pure construction tests pass in the admitted harness.
- [ ] P0-02 identifies the concrete first scene profile, measurements, frames, cohort rules, numerical criteria and actual/new producer boundaries. No placeholder producer can satisfy admission.
- [ ] P0-03 maps permitted semantic changes to runtime-effective parameters, original-baseline bounds, full invariant checks and reassessment dependencies.
- [ ] P0-04/05 agree on transaction/attempt/owner fences, exact replay, cleanup, local cancellation and authorization composition; every transition has a specified positive and failure outcome.
- [ ] P0-05 defines the §12.1 bootstrap/readiness gate and dependency matrix; P0-06/07 cover unavailable dependency → zero model calls including initialization pings, all-ready admission, scene-only policy optionality and per-release rechecks.
- [ ] P0-06 accounts for every supported inference path before construction and separates semantic iterations from transport retries and implicit fallback.
- [ ] P0-07 supplies verified exact offline commands/profile selections, owned fixture scope and test-to-scenario coverage; isolated Neo4j/native gates are explicitly separate.
- [ ] A focused contract-integration review resolves cross-owner inconsistencies. This is review of the new P0 artifacts, not another open-ended architecture exploration loop.

Do not interpret a completed checklist in documentation as proof that the resulting Neo4j transactions, simulator measurements or VLM repair work. Those are P1–P4 execution gates. Conversely, do not block P0 on selecting GraphQL or migrating unrelated SQLite consumers.

### 13.3 Review findings → implementation obligations

The [review ledger](event-mapping-refactoring_plan_02-review.md) retains evidence, rejected counterarguments and final dispositions. This compact register assigns follow-through without upgrading narrowed claims into new architecture defects.

| Review ID | P0 owner/package | Required downstream regression / gate |
| --- | --- | --- |
| EX-01 | P0-06 | P2 managed image assessment cannot fall through to an undeclared local provider; authorized alternative profile remains a separate reserved invocation. |
| EX-02 | P0-06 with P0-04 | P2 ping/JSON/prim/image/failed-call accounting spans contexts; P1 reservations remain bounded; transport retry changes do not disable semantic validation. |
| EX-03 | P0-01 with P0-07 | Pure request construction rejects runtime imports; actual candidate/catalogue validation still runs in the admitted execution adapter. |
| DM-01 | P0-02 | A/D/E reject complementary passes from different realizations/resets; complete cohort and explicitly declared multi-trial aggregation still pass. |
| DM-02 | P0-02 | Criterion-specific visual request/response validates declared rubric/views; generic satisfactory output remains insufficient for arbitrary criterion coverage. |
| PE-01 | P0-04 | P1 reader/pruner race returns an intact eligible page or explicit gap; no silently omitted prefix. |
| PE-02 | P0-04 with P0-05 | Exact admitted-request recovery survives expired execution authority/unavailable source without issuing a grant, bypassing read authorization or dispatching work. |
| IF-01 | P0-05 | P4 starts from verified owner cleanup/common-lease acquisition, not pause alone; queued legacy work stays unreleased. |
| IF-02 | P0-05 | Positive foreground release under scoped local authority without HTTP/SQLite job; expiry blocks subsequent release. This remains the clarified P0 composition selection. |
| IF-03 | P0-07 | Existing/new suite admission and core/API profile selection are checked before owner handoff. The original missing-prerequisite claim remains rejected; this is checklist precision. |

### Tests and documentation to extend

Existing tests to reuse/extend, subject to current runner admission:

- `isaaclab_arena/tests/test_trajectory_assessment.py` and current core generation/graph tests.
- Explicit study references: `isaaclab_arena/tests/test_visual_and_graph_rag.py` (heuristic/advisory boundaries), `test_environment_generation_agent.py` (semantic repair/fallback), `test_inference_backend.py` (synthetic transport and preconstruction guards), `test_dcrg_loop.py` (synthetic measured comparison/recovery), and `isaaclab_arena_examples/tests/test_workbench_snapshots.py` (snapshot lifecycle and separately opted-in GPU rendering). Preserve their proof limits; none alone establishes the autonomous VLM repair/guidance loop. P0-07 owns exact admission; DCRG-specific extensions belong to P6.
- `isaaclab_arena_examples/tests/test_workbench_journal.py`, `test_workbench_generation_modes.py`, `test_workbench_generation_receipts.py`, `test_workbench_managed_cli.py`, `test_workbench_build_environment.py`, `test_workbench_evaluation_harness.py`, `test_workbench_workflow_authorization.py`, `test_workbench_reauthorization.py`.
- Existing frontend editor-job, generation, build/evaluation, ownership and research-version tests in `web/arena-workbench/src/`.

Proposed new core suites: `test_environment_workflow_contracts.py`, `test_environment_workflow_decisions.py`, `test_environment_workflow_store.py`, `test_environment_workflow_repairs.py`, `test_environment_workflow_evidence.py`, `test_environment_workflow_import_boundaries.py`. Add CLI compatibility tests under `isaaclab_arena_examples/tests/`; real Neo4j/native acceptance tests remain separately opt-in.

Add the proposed composed readiness regression in §12.1 and reuse `isaaclab_arena_examples/tests/test_workbench_readiness.py`, `test_workbench_paused_start.py` and `test_workbench_policy_readiness.py` alongside the provider-transport tests. Keep host startup effects mocked in offline tests; none of these readiness checks is a hidden inference smoke or live Docker operation.

Use `scripts/run-functional-checks.py` and `web/arena-workbench/tests/e2e/functional-v7/{stage.py,backend_checks.py}`. New exact files need reviewed admission; do not assume the default backend suite includes them. Keep offline model/graph/simulator seams synthetic and OS-level network denial intact. Real Neo4j concurrency tests use a separate disposable authorized scope; live GPU/model tests cannot be disguised as offline units. Arena package/runtime tests execute in the repository-approved container/nonroot environment, host lint remains on the host.

Assign a P0 harness owner to verify admission for the named existing compatibility suites **as well as** new suites and to classify their core/API/runtime execution profiles. The current `core_only` selector recognizes exact singleton selections, so adding a file to an allowlist alone does not establish simulator-free/core import isolation. Before parallel implementation, supply exact verified commands/profile selections and extend selection/staging regressions without weakening denial. This makes the existing admission obligation actionable; it is not a request for another test framework.

Update the example README, existing workbench/concept documentation and DCRG docs only for changed contracts. Add one linked workflow architecture page and one runbook when the executable interface exists. Preserve plan/history/status roles. Changes to `docker/`, workflows, pre-commit configuration or submodules require separate approval.

## 14. Acceptance scenarios and evidence requirements

| Case | Deliberate input/condition | Required result |
| --- | --- | --- |
| A — baseline scene | Supported profile with all criterion producers | Accept only when each required criterion has matching established evidence; no repair consumed. |
| B — autonomous correction | Fixture whose defect survives relation solving and settling and has an effective permitted correction | Real defect measured/observed; retained assessment drives repair without external feedback; new candidate re-realized/reassessed; accept only after checks pass. |
| C — unsupported correction | Fixture proven unsatisfiable under its specific allowed deltas | Stop `unsupported_intervention`; preserve constraints, failed criteria and explanation. Overlap alone is not proof moving the robot is required. |
| D — insufficient evidence | VLM satisfactory but required physical evidence missing; missing required view; advisory fallback | No acceptance; bounded authorized observation or `evidence_not_established`. |
| E — stale/malformed evidence | Wrong candidate/digest/attempt, altered artifact, malformed model JSON, unavailable terminal image | Reject binding or retain inconclusive limitation; never upgrade to pass. |
| F — ineffective repair | Coordinate changes ignored by runtime relations; strict solver fallback | Detect no effective correction/failed placement; stop or choose another permitted bounded strategy. |
| G — forbidden/cumulative change | Physics/task/validator edit, unlisted topology change, cumulative shift beyond original bound | Reject before realizing the unauthorized candidate; retain proposed delta and budget cost. |
| H — budget concurrency | Two decisions claim last allowance; nested inference retry/repair attempts | Only one authorized reservation; no negative counters or unmetered work; exhaustion terminal reason. |
| I — restart boundaries | Stop owner before release, after release, after receipt commit | Known unreleased work may continue; unknown work reconciles; verified completed work reused without duplicate provider/simulator call. |
| J — cancellation/cleanup | Cancel during launch or commit, including Neo4j outage; late stale worker receipt/cleanup | Owner-local authenticated stop works without a DB transaction; distinguish delivered local stop from pending durable cancellation/unknown remote effects; no subsequent release before reconciliation; identity-bound cleanup and diagnostic evidence retained. |
| K — replay/idempotency | Same/conflicting submission; concurrent capacity; events with same wall-clock timestamp; pruned cursor | Exact original result or conflict; bounded admission; no lost events; explicit replay-gap snapshot. |
| L — graph eligibility | Accepted but unevaluated scene; rejected repair; publication not authorized | Operational retention only; no accidental successful-prior retrieval or engine default publication. |
| M — optional experiment | Scene established but policy criterion outstanding; DCRG permission absent/present | No premature overall acceptance; denied experiment does not run; permitted supported experiment retains distinct measured outcome. |
| N — legacy coexistence | Old snapshot worker holds GPU; new workflow submits; old jobs queued | Resource exclusion/handoff works; no implicit global queue resume or duplicate authority. |
| O — UI recovery, later | Refresh/reconnect at assessment/repair/terminal phases | Same run and evidence recovered with no fresh expensive submission; unsaved draft remains a separate contract. |

Extend these existing cases with the review counterexamples rather than creating another acceptance framework: A/D/E cover incompatible realization cohorts and missing criterion-aware rubric/view coverage; H covers constructor/prim/image calls across contexts and forbidden local fallback; K covers replay/prune races and exact recovery after execution-grant expiry without bypassing read authorization; N covers acknowledged renderer retirement before the first CLI as well as later coexistence. P0/P1 include positive local-principal release/expiry and representative pure-contract construction tests.

A floating object that simply falls onto the table is not a guaranteed repair fixture. In P2/P4 verify the injected defect at **realized** state and select a correction path the runtime actually consumes. Do not require a predetermined candidate number from stochastic generation; acceptance concerns observed autonomous correction within budget. Retain failed attempts and all used budget.

### First live acceptance bundle

Before running, record the exact prompt/contract, supported assets/task, generation and VLM identities, database scope, permitted corrections, numeric budgets/tolerances, seeds, runtime/container identity and output path. The bundle must retain original/repaired specs, exact prior snapshot, candidate/attempt/decision IDs, actual image/measurement manifests, per-criterion assessments, structural deltas, realized pose comparison, consumed budgets, terminal/cleanup disposition and exact Neo4j readback.

Synthetic tests establish routing/protocol behavior; real frames/measurements and model responses establish this integration only. Neither a positive code review nor a successful scene experiment proves policy transfer or statistical robustness. Native evidence must never be substituted with plausible mocked results.

## 15. Review checklist and unresolved implementation selections

This document selects the architecture and migration scope, not the still-unimplemented concrete contracts. Resolve selections at the gate that needs them; do not let a later interface/deployment choice become an accidental prerequisite for the first scene CLI.

| Selection still open | Accountable package / phase | Required before | What closes it |
| --- | --- | --- | --- |
| Concrete banana asset/task IDs and effective relation fields | P0-02/03 | P0 handoff | Source-backed supported profile and correction-consumer map, not a fabricated fixture path. |
| Support predicate, tolerances/window, coordinate/quaternion conventions, camera/rubric/cohort rules | P0-02 | P0 handoff | Explicit versioned criterion configuration and measurement implementation design with positive/negative fixtures. Thresholds are proposed values until calibrated/validated; live evidence arrives in P4. |
| Exact contract/store/worker/service signatures and CLI exit-code mapping | P0-01/04/05 | P0 handoff | One shared interface contract and admitted pure tests; no competing per-adapter schemas. |
| Foreground principal/private resolver, grant renewal and owner-local stop composition | P0-05 | P0 handoff | Concrete scoped lifecycle plus synthetic release/expiry/stop contract; no credentials retained in plan or public receipts. |
| Exact old/new test admission, profiles and commands | P0-07 | Implementation-owner handoff | Reviewed selection/staging changes and actual isolated command output; not a command guessed from a filename. |
| Neo4j database/version compatibility, schema privileges and disposable transaction-test target | P0-04 prepares; P1 verifies | P1 real database tests | Approved target and schema scope, runtime driver compatibility and isolated concurrency/recovery evidence. Shared research DB is not an automatic test target. |
| Numerical live budgets, runtime/resource ownership, private credential provisioning and artifact destination | P4 operator with P0-02/05/06 contracts | Any native rendering/model acceptance run | Explicit bounded run contract and authorization; no effects authorized by this plan update. |
| GraphQL library/schema/transport details | P5 interface owner | P5 implementation | Selected dependency and typed adapter design over the already verified application service; not required by P0–P4. |
| Policy/DCRG profile and managed state port; per-kind legacy cutovers | P6/P7 owners | Their separately scoped work | Supported experiment/cutover contracts and evidence under §§8/10; not part of the first scene-only deliverable. |
| VLM/DCRG mode, evidence alignment, supported guidance catalogue, no-advice behavior and controlled-comparison protocol | P6-V1–V6 owners | Any enabled managed VLM/DCRG run | Freeze model/rubric/routing, truthful frame/episode provenance, candidate-control parity, evaluation units/budgets and utility thresholds; improvement remains a hypothesis until controlled results support it. |

Review the plan independently for persistence/execution and evidence/research semantics. Walk A/B/D/I/J/M against I1–I12 before implementation; label that exercise **design validation**, not runtime proof. A plan is ready to implement only when its first phase has a concrete positive path, not merely many rejection checks.

### Required changes from plan 01, traced

| Plan 01 issue | Resolution here |
| --- | --- |
| Aggregate satisfactory status treated as acceptance | Sections 3–5 define per-criterion evidence and non-substitutable measurement types. |
| Wrong schema and prose-based mutation permission | Section 6 uses actual Arena schema, complete structural deltas and realized fidelity. |
| Frozen budget mistaken for remaining budget | Section 7 reserves persisted cumulative allowances before release. |
| Incomplete/drop-in Journal replacement | Section 8 isolates new operations and inventories direct SQL consumers before per-kind migration. |
| Timestamp cursors/stale serialized jobs/unfenced cleanup | Section 7 specifies committed sequence, canonical view updates and exact owner cleanup. |
| Automatic candidate-to-successful-prior promotion | Section 9 separates retention, publication and evidence-based eligibility. |
| Policy acceptance before required experiment | Section 10 separates scene prerequisites, optional experiment and whole-run outcome. |
| Historical trajectory fix proposed again | Section 1 preserves completed helpers and their limits. |
| Coarse phases and ambiguous repair scenarios | Sections 11–14 give source owners, dependencies and evidence-based acceptance cases. |

## 16. Draft verification boundary

Writing this plan changes documentation only. Runtime code, database schema/state, workers, services, credentials and queued jobs remain untouched. Documentation checks validate links/format and review consistency; implementation, native acceptance and deployment remain future work under their own approval and evidence gates.

Independent read-only reviews covered persistence/execution and evidence/research semantics. They found no fundamental architecture contradiction; the cancellation-during-outage gap and clarifications on mixed criteria, experiment permission and prior-consumption/eligibility tests were incorporated above. A tabletop walkthrough covered baseline acceptance, autonomous correction, missing physical proof, restart boundaries, cancellation, concurrent final-budget claims and optional policy experiments. This is design-consistency review, not a formal proof or an executed acceptance experiment. P0 selections and every implementation/live gate remain open.

The subsequent bounded exploration/cross-examination loop is recorded in the [review ledger](event-mapping-refactoring_plan_02-review.md), including the frozen baseline, requirement coverage, narrowed/rejected claims, accepted corrections and remaining runtime obligations. Use its closure status rather than treating the earlier focused review as exhaustive coverage.

Post-review planning update: §13.1–13.3 operationalize the already-selected design as P0 work packages/handoff obligations, and §15 assigns outstanding selections to the correct gate. This elaboration does not mark P0 implemented, select unverified numerical thresholds, reopen the completed broad review loop or extend its hash-bound verdict to new code. Verify resulting P0 contract artifacts through the focused handoff review before P1/P2 integration.

The later user-requested VLM/DCRG extension is §10.1–10.7: opt-in scene assessment, evidence-bound diagnosis and permitted proposal guidance, explicit implementation units and a controlled utility study. It preserves the measured comparator and the single workflow authority. The companion [code-reference inventory](../quick_notes/event_mapping_code_references.md) distinguishes current source, historical trajectory changes and test proof limits. This new research plan is not covered automatically by the earlier review digest and authorizes no experiments.

The subsequent bootstrap/readiness addition is §12.1 and belongs to P0-05. It explicitly gates model construction on required service readiness, including the initialization-ping regression, while reusing existing host control and bounded probes. This remains a plan requirement; startup code, tests and services were not executed by adding it.
