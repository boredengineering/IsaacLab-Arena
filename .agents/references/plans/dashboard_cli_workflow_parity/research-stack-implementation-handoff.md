# Research workflow implementation checkpoint

Updated: 2026-09-18. This is the single current handoff. The user has now authorized implementing [event-mapping plan 02](../event-mapping-refactoring_plan_02.md) through the bounded implementer/critic/verifier loop. Earlier study and narrow-fix evidence remain in the [session memory](../../quick_notes/session_memory.md#current-study-and-progress--2026-09-18).

## 1. Current authorization and implementation gate

Current implementation gate: request/admission/readiness, relation-effective repair guards, frozen-criterion evidence matching and initial Neo4j generation reservation/claim/registration/release/cancellation. Artifact-backed generation-result adoption and exact cleanup acknowledgement are in progress. No complete CLI, native measurement producer, orchestration loop or deployed runtime delivery is claimed.

- User explicitly approved scoped `docker/workbench/` bootstrap/readiness wiring changes while preserving existing security and paused queues. This is not approval to start/replace research services.
- User explicitly approved a disposable test-only Neo4j container from a cached image, isolated storage and no access to research data/credentials. No image downloads, model/GPU work or shared-service changes are included.
- Initial parent baseline: sandbox runner `arena-core-units-7447c10bd0e7` passed; focused trajectory baseline `arena-f0-backend-d1aeb15aff3e` passed 59 tests, zero forbidden-effect counters, unchanged staged source and verified owned cleanup. Evidence under `web/arena-workbench/tests/e2e/functional-v7/.runs/` is ignored and not retained by ordinary commits.
- No commits/pushes or shared queue release. Live native/model acceptance remains a separately bounded gate. Existing dashboard reliability and physical placement issues below remain unresolved.
- User declined the proposed bounded native smoke test and selected **continue implementation and isolated tests only**. Do not run the proposed simulator/GPU smoke or treat earlier isolated-Neo4j approval as native execution approval. Continue offline/container-isolated development; native acceptance remains blocked on a future explicit authorization.

### Current verified increments (not end-to-end acceptance)

- Exact offline workflow-test admission: eight explicitly named test files, nonempty unique pure-workflow subsets use the existing core sandbox; legacy defaults/mixed profiles remain unchanged. Implementer RED `arena-core-units-8a326c0cd304` retained four expected failures; GREEN `arena-core-units-a9d27b1d10ec` and parent rerun `arena-core-units-fc4f85104141` passed all 101 sandbox checks. Independent read-only critic found no blocker. No isolation/proof guards were weakened.
- Pure dependency gate: RED `arena-f0-backend-c3f95fa00074` failed because the new module did not exist; GREEN `arena-f0-backend-cc664cd8337b` passed. Verified negative and positive deferred-factory behavior with synthetic probes only. This is **not** the composed application/host readiness acceptance; current probe transports remain caller-owned and the gate cannot forcibly interrupt arbitrary Python callbacks.
- Scene scout traced the actual banana fixture: `on` without `at_position` ignores an authored non-anchor `initial_pose`. Raw fixture is not an existing demonstrated XY-repair success. The proposed guard must reject missing effective relation parameters; any initial enrichment and physical threshold calibration remain explicit later work, not invented measurements.
- Neo4j admission/event-store and initial attempt fencing now have real disposable-database verification (latest evidence below). Complete recovery, composed CLI, native measurement production and scene acceptance remain open.

Current follow-up evidence and open gates:

- Harness final scoped bytes: `arena-core-units-a64f7ccaf262` passed 101 checks; parent verified final source hashes. Incidental formatter churn was removed. Pre-existing lint findings remain unchanged, not silently fixed.
- Contract semantics were expanded after parent review: preservation/intervention paths and bounds, criterion modalities/frames/windows, distinct model roles, seed/capture configuration and cumulative operation/deadline budgets. Canonical-output expansion bug reproduced and fixed; the surrogate allegation was rejected because Pydantic already prevents invalid strings. Parent contract run `arena-f0-backend-3bd7ecbfaf7d` passed. DCRG requests remain explicitly unsupported in this initial schema.
- Admission service currently composes injected scoped authority, producer-support validation, full-outcome dependency derivation and store admission only. Replay skips fresh support/probes/execution authority. Fresh operational-write denial regression is RED `arena-f0-backend-8368af4e5378`, GREEN `arena-f0-backend-0ab1e0cea9af`. No worker is released and no CLI composition is delivered by this utility.
- Repair critic found missing non-anchor/support-profile guards. Regression RED `arena-f0-backend-21869b444666` had seven expected failures; final implementation GREEN `arena-f0-backend-8690c67abe7e` and parent `arena-f0-backend-4b4fc4863561` passed. Guard now rejects target anchors/missing or ambiguous support identity; scalar-XY structural permission is not physical feasibility or original-baseline authentication.
- Contract-bound repair adapter additionally derives exact allowed x/y paths, subject, env-local frame and minimum cumulative displacement ceiling from the frozen contract, with contract/original/candidate digests. Parent `arena-f0-backend-30391d2e0056` passed; independent critic approved the structural scope. Actual schema validation, baseline provenance, immediate-parent lineage and realized effect remain separate obligations.
- Scene evidence metadata utility requires explicit selected cohort; historical failures remain diagnostics instead of permanent vetoes. Frozen criterion projection binds full criterion digest, producer, frames and exact window; unsupported modalities/windows/counts reject. Independent binding review closed after a 128/129 boundary regression; parent `arena-f0-backend-3e93783158d0` passed. Native measurements and image artifact verification remain missing.
- Disposable runner safety gaps were corrected with synthetic regressions and parent source review: confined output creation, ambiguous-create cleanup unknowns, staged import origin checks and runner-specific proof/JUnit validation. Parent real workflow tests resumed. This new runner is not validated by the legacy F0 proof checker.
- Real admission races initially deadlocked with dependent-only control updates. Constant-SET locking passed repeated same/different-key races, conflicting replay, mixed snapshot/admission and injected post-write rollback. Administrative scope initialization remains a quiescent prerequisite, not a concurrent migration guarantee.
- Initial generation-attempt persistence supports reservation, owner/epoch claim, exact registration, one-winner release and cancellation fencing. Release/readiness DTO mismatch found by independent critic was corrected: reservation and release now derive the same contract-required dependency set, bind optional trusted instance pins and conservatively map probe-start monotonic time into wall time. Missing pins remain profile-only verification, not service identity proof.
- Latest parent verification: `arena-neo4j-3fd8735bf9864034b6c1243cc2a4db0f` passed **33 real database tests** including concurrent releases/reservations, cancellation race and committed-release ACK loss with retry returning false. `arena-f0-backend-26da3df40f3e` passed **344 isolated tests** across seven current workflow suites. Both had zero failures/errors/skips and verified owned cleanup. These overlapping counts are not an end-to-end acceptance total.
- Still missing: concrete host/bootstrap and runtime probe wiring, private credential/owner lease composition, actual bounded worker adapter, invocation metering, receipt/cleanup/recovery completion, image/measurement capture, application coordinator/CLI loop, native calibration/acceptance, policy/DCRG extension and dashboard parity. No paid inference, GPU trial, shared queue release or research-database write has been performed.
- Subsequent generation-result slice reuses actual `ArtifactArea` bytes and service verification before immutable Neo4j adoption. Exact receipt plus synthetic owner-cleanup evidence advances `running/generation` to `running/validation`, not scene acceptance. Parent real `arena-neo4j-a6f2004e6b62425b86d3aecd2a5f86ab` passed and independent adoption critic approved this scope. Kernel cleanup, YAML/JSON semantic equivalence and truthful catalogue/prior provenance are not established by hashes.
- Lifecycle phase is now separate from operational state. Released uncertainty can be marked for reconciliation without retry/refund; exact retained results/cleanup reconcile the original attempt and cancellation wins. Parent added a real RED for receipt-present/cleanup-uncertain and verified the fix in `arena-neo4j-5d12a9c9a5544850922602c8e72e1eb6`.
- `GenerationCoordinator` dispatch/local-stop utility exists with injected authority/lease/worker ports, but no actual adapters or completion receiver. Parent isolated `arena-f0-backend-e84f3d76f7fc` passed and scoped critic found no safety blocker. Real-store integration then exposed three reds in `arena-neo4j-fd6978ad773d45d5b88192014054fa9f`: missing pre-claim/claim-ACK recovery IDs and nonterminal pending/no-worker cancellation. Targeted fixes are in progress; retain these as unresolved until rerun. No full application/CLI delivery is implied.
- Some isolated test logs contain an ignored teardown `AttributeError` at existing harness `api.py:171` (module name becomes null during interpreter shutdown). Recorded pytest/proof status is passing, but logs are not warning-free. No unrelated harness change has been made for this.

### Historical interruption and limits

Latest interruption: **“have you messed up the cli again ? I cannot see the terminal anymore.”** Code work stopped; the user then requested saving progress and the event-modeling study. Hermes was observed running with a responsive tool channel, but the host terminal display could not be inspected. Cause and whether the panel disappeared versus text became blank are unknown. No terminal/Hermes configuration change or service restart was performed. Preserve current edits; do not resume from older approvals.

The earlier **“I refreshed the page and everything disappeared”** dashboard report remains independently unresolved. The study established a missing application-owned visual-assessment/repair coordination path, not a proven cause of either display symptom.

The user subsequently authorized finishing the narrow `render_policy_trajectory.py` correction before continuing the event-mapping study. The tool delegates to core task-driven capture/assessment helpers, preserves completed capture evidence across cleanup failures, retains the resolved policy instruction, forwards device selection, and preserves failure exit status through native shutdown. The parent reran **59 isolated tests** successfully. A final-source native smoke check retained nine real RGB frames over two zero-action steps and verified exit 1 for an injected pre-provider failure. No live GR00T/VLM inference, graph operation or full repair-loop acceptance occurred. See the session-memory follow-up for exact evidence and material/texture warnings. This narrow authorization does not resume dashboard implementation or shared services.

**The prior implementation pause is superseded only by the current scoped plan-02 authorization above. Dashboard reliability remains unresolved; full V7/CLI parity is not accepted.** Earlier “live delivery” and “fixed” reports describe bounded observations, not reliable user delivery. It is not established whether the disappearance affects rendering, session state, unsaved drafts or persisted data. No data-loss diagnosis or recovery is claimed; shared workload release remains outside this checkpoint.

## 2. Checkout and commit boundary

- Checkout: `/workspaces/IsaacLab-Arena`, branch `dev/0.3.0-prerelease`.
- Implementation baseline: clean `8058fcf42d89bc4bba7d88576843e684c5fedca3`, the user's committed planning/reference changes. Production source still starts from the trajectory-fix baseline `45a0b26466`; older checkout observations are historical.
- Implementation now creates scoped changes from that baseline. No staging or commit is authorized; the user owns the commit decision.
- A commit preserves selected source/docs, **not** the installed host helper, private profiles, SQLite journals, browser state, cached images/dependency volumes or ignored verification artifacts.
- Application-owned bounded orchestration, Neo4j workflow authority and core consolidation are now authorized for implementation according to plan 02. They are not delivered merely because implementation is authorized; record verified increments here.

## 3. Intended workflow retained

The baseline remains the existing [agentic generation README](../../../../isaaclab_arena_examples/agentic_environment_generation/README.md): prompt-first generation using Graph-RAG, inspect, build, and separately evaluate. Reuse the existing agent, retriever, relation solver and policy runner; this handoff does not propose a replacement architecture.

LPG/Neo4j, RDF/reification, provenance, measured outcomes and bounded DCRG corrections remain the research context. Do not equate declared relations with physically realized placement, or RDF reification with proven native RDF-star/lossless round-tripping. The A2 banana/plate placement failure remains unresolved: valid YAML and a short Build did not prove objects spawned on the table.

## 4. Earlier dashboard implementation and observations (2026-09-17)

| Area | Source / bounded observation | Remaining limit |
| --- | --- | --- |
| V7 editor | Existing authoring, validation, save/recovery, Library and inspection work; earlier isolated and live checks | Latest refresh disappearance unresolved; no claim of reliable complete interface |
| Model profiles | Create-only nonsecret Journal catalogue; capability settings frozen through settings, grants, jobs, workers and SDK requests; Add/readback/select UI | User-defined profiles remain unverified; no live compatibility matrix or automatic provider test |
| Live profile example | `openai-gpt-4.1-mini-user` saved through UI, API and independent SQLite readback; no key activated | Observation predates latest refresh failure; current user-visible state not rechecked |
| General readiness | Scenario selector removed; runtime/graph/model/GPU checks follow general generation/inspection/build | Last check passed API/runtime/GPU, but graph was not configured; not successful Graph-RAG generation |
| Existing services | Neo4j and GR00T started using their existing containers/cache; resource caps read back; GR00T ping and DROID modalities checked from Arena | Service state is not model identity, codec/inference acceptance or task success |
| Host control | Private v2 helper installed; paired browser Start with all services already running completed by exact GET readback | No live browser cold-start test; time-limited pairing is separate from API session and queue resume |
| Policy endpoint | Trusted configured GR00T port flows through readiness and frozen evaluation inputs; live catalogue showed 5559 | First-party metadata wrapper exists in source, but running server lacked `get_server_info`; verified-policy acceptance remains open |
| Queue resume | Global `Resume queue` added outside diagnostics, with whole-queue warning, confirmation and session/route fencing | Agent only tested Cancel live. User subsequently reported disappearance after refresh |

## 5. Last-known queue and runtime state — not a fresh live probe

Immediately before the user's latest report, both jobs were still queued:

| Job | ID | Last observed state |
| --- | --- | --- |
| Generation | `2da78c386c234556b012c65c5d31a830` | queued |
| Build | `1e537acb672246edb9520f060c9fe7e2` | queued |

The agent did not resume or cancel these jobs. Queue resume affects the entire shared queue, not just generation. Re-observe it before any future release; do not duplicate submissions or assume an old execution grant remains valid.

- Dashboard URL used: `http://127.0.0.1:3010/?layout=v7`.
- Existing target graph: `neo4j-arena`, Bolt **7688**, HTTP **7475**. Other Neo4j instances are not substitutes.
- Existing target policy: `gr00t-server`, loopback **5559**, cached `nvidia/GR00T-N1.6-DROID`. OpenPI's separate port remains 8000.
- Last API reload used `--start-paused`. The Supervisor dispatch pause is distinct from journal `queue_paused`; a false journal flag alone does not establish active dispatch.
- Neo4j 2 GiB/256 tasks; GR00T 16 GiB/1024 tasks; equal memory/swap caps. Recorded owned caps including Arena/editor/frontend/helper were below daemon RAM; this did not bound unrelated applications.
- Host helper: `arena-workbench-control-v2-final-6e74675cd31c.service`, private installation `/home/tarfy/.local/state/arena-workbench-control-6e74675cd31c/installed-v2-final`. No credentials or pairing values belong in Git. Pairing lasts 30 minutes and is browser-session-specific; it does not resume jobs.
- Host-installed bytes/profile are separate from checkout edits. Reviewed file drift can invalidate startup admission. Private state and ignored `outputs/control-setup/` scripts are not a reproducible committed deployment recipe.
- API graph credentials were not configured at the last check. Permission to reuse the existing database account was asked but unanswered. Current user-session generation-key availability is unknown; do not infer it from another session's metadata.

## 6. Evidence map — historical scopes, not one acceptance total

| Checkpoint | Recorded result | Where to look |
| --- | --- | --- |
| Combined model/endpoint backend | 682 isolated cases; SDK transport separate/synthetic | [Integration evidence](model-endpoint-integration-backend.json) |
| Production frontend before Resume extraction | 1,989 cases / 72 files; preview excluded; sequential bounded batches | [Aggregate](frontend-integration-evidence.json), [file inventory](frontend-integration-files.json) |
| Model-profile owner / policy-port owner | Focused tests, typecheck/build, source hashes and limitations | [Model evidence](model-profile-owner-evidence.json), [port evidence](policy-port-evidence.json) |
| Host helper | Parent 82 control + 24 launcher tests; real stat-only probes; scoped hooks | [Live startup record](startup-live-evidence.json), [runbook](../../../../docker/workbench/CONTROL.md) |
| Profile live save/readback | UI, authenticated API and independent SQLite readback, no model call | [Live profile record](model-profile-live-evidence.json) |
| Resume extraction, later than full frontend run | 165 focused cases across 8 files, typecheck/build; live Cancel-only check | Runs below and [historical log](implementation-progress.md) |

Resume artifacts under `web/arena-workbench/tests/e2e/functional-v7/.runs/`:
`arena-functional-frontend-bb0f7cdb65f1`, `arena-f0-typecheck-1b6671c4b75d`, `arena-f0-build-254174d33037`.
These ignored local artifacts may not exist in a fresh clone. Counts overlap and must not be added. The later Resume patch was not followed by another whole-frontend run. The user report supersedes any claim of repeatable refresh acceptance.

Older 382/1,925-case records, synthetic Chromium traces, API inventories and owner status files remain historical evidence. A route ledger is not full mutation coverage; a successful component test or mocked transport is not an executed research workflow.

## 7. Where the changes live

- `isaaclab_arena/agentic_environment_generation/`: inference profiles/backend, strict scene adaptation, policy contract and Journal-backed model-profile store.
- `isaaclab_arena_examples/agentic_environment_generation/web_api/`: settings, authorization/grants, worker propagation, readiness, evaluation endpoints and paused API startup.
- `isaaclab_arena_gr00t/`: policy metadata/codec wrapper and optional verified native-client integration.
- `web/arena-workbench/src/`: model settings, readiness, host-control panel, queue-resume panel and existing editor changes.
- `docker/workbench/`, `docker/resource_limits.py`: helper, launcher/API lifecycle, proxy/socket integration and resource budgets.
- Tests beside those components and the existing `functional-v7` verification runner.

Review tracked **and untracked** source files when preparing the commit. Do not bulk-add model caches, private profiles, keys, runtime state or datasets. This checkpoint is not commit approval or a claim that all pending changes are correct.

## 8. Reading order and resumption boundary

1. This checkpoint: current implementation gate, authorization and limits.
2. [Session memory](../../quick_notes/session_memory.md): short decision record and conversation recovery anchor.
3. [Historical progress log](implementation-progress.md): provenance only; contradictory “current” paragraphs are superseded.
4. [Dashboard design](../dashboard_cli_workflow_parity.md), [endpoint contracts](endpoint-contract-plan.md), [research-stack design](research-stack-readiness.md), [model-profile contract](model-profile-contract.md): retained design records, not a new execution mandate.

Continue the currently authorized plan-02 implementation through its dependency and verification gates. Older approvals do not authorize additional shared-service changes, paid/GPU experiments or queue release. Preserve historical evidence rather than upgrading it to current acceptance.
