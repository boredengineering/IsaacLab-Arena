# Plan 03 source-grounded review ledger

Status: the bounded three-round review below records the earlier plan revision. A subsequent user-directed scope correction makes bottom-up GraphQL/application refactoring the target and removes dashboard compatibility/integration obligations. That correction is recorded below; the earlier review does not certify the changed scope. Implementation and live release gates remain unexecuted.

Canonical plan: [event-mapping-refactoring_plan_03.md](event-mapping-refactoring_plan_03.md). Implementation status remains in the [existing handoff](dashboard_cli_workflow_parity/research-stack-implementation-handoff.md). This ledger records documentation review, not implementation approval or runtime acceptance.

## Baseline and scope

### User-directed scope correction after the bounded review

The user clarified: “we are refactoring the codebase and building it from the bottom up for the graphql so we should not be concerned about the dashboard at this point.” Dashboard compatibility was an assistant-added implementation strategy, not a user requirement. This direction supersedes the earlier dashboard/REST parity recommendations in this ledger.

- Plan 03 now defines domain/application, persistence, engine and command/query contracts for GraphQL from M0. The CLI exercises the same application; it does not define a separate CLI-first architecture.
- Phase 5, M4/M5, the extraction map and T10–T12 now target backend/GraphQL contracts, fresh-process recovery and API tests. No frontend files, browser tests, legacy route preservation, SQLite SSE adapter or new REST parity work is required.
- Retained identities, revisions, authorization, command receipts and request-independent execution ownership remain backend requirements. They are not justified by current dashboard behavior.
- Dashboard migration is deferred, not authorized for deletion. Under the further Neo4j-only correction below, SQLite dependency removal for reused backend capabilities is required now in the refactoring plan, not deferred with the dashboard.
- The historical findings and review dispositions below are preserved for attribution. N04/Q04's requirement to build a frontend reconciler is superseded; the underlying event-contract distinction remains relevant only to defining the backend API correctly.
- Verification for this scope correction is scoped documentation lint/citations/structural checks and parent scope-consistency inspection, not another independent review or runtime acceptance.

### Earlier review baseline

Further user correction: “I do not want SQlite I want to enforce the architecture we have designed using neo4j.” This is an architectural constraint, not a backend preference. Plan §2 now prohibits SQLite runtime authority, caches, dual writes and fallback in the refactored application. Persisted domain/workflow/command/event/profile records belong to Neo4j; immutable evidence bytes and private credentials retain their distinct non-database boundaries. §8 names the current Journal-backed ModelProfileStore and requires extraction/migration before reuse; the GraphQL bootstrap must not instantiate the unchanged SQLite application. M0 and T13 enforce dependency inventory plus isolated positive execution with SQLite unavailable and Neo4j-only readback. These are implementation acceptance obligations, not claims that SQLite has already been removed from source. Prior review allowances for retaining legacy SQLite authority do not govern the corrected target architecture.

- Recovered user request: an in-depth codebase/web-researched plan connecting the existing orchestrator to actual provider configuration, live Graph-RAG, native realization/capture, a supported launch configuration and manipulation policy evaluation, with foresight for later GraphQL.
- Source HEAD: `3440d6352dc90ba2b2451bb29f29f8f0bd165af9`, branch `dev/0.3.0-prerelease`.
- Resumption found a modified references index and untracked plan 03 attributed to Antigravity. Its original bytes were preserved locally at `outputs/workflow/plan03-research/initial-plan03.md`; the prior research/source ledger was reused, not reset.
- Scoped source inventory: 377 tracked files under the core generation package, example generation adapters, workbench frontend and `pyproject.toml`. Combined content fingerprint: `d6f0aa736700d090b9f4ad9021d3e663c8f0b1820be4ac5e75534388f9ac53ae`. Inventory is not reviewed coverage. Exact path/hash records and original plan digest: `outputs/workflow/plan03-research/review-baseline.json` (local ignored evidence).
- Reviewed units: existing foreground/core composition and CLI; model/profile/private authority; prior retrieval/retention; native builder/capture/sampler and policy bridge; event/read-model/frontend boundaries; official provider, Neo4j, Isaac Sim and GraphQL documentation.
- No package execution, live inference, simulation, policy requests, database access, service changes, installs, commits or credential-file reads are part of this review.

## Requirement coverage

| ID | User requirement / retained invariant | Plan location | Verification obligation |
| --- | --- | --- | --- |
| R01 | Actual provider credentials and model configuration | Phase 1, §6, §11 | T01–T03 |
| R02 | Live Graph-RAG using existing provenance machinery | Phase 2, §7–8 | T05 |
| R03 | Native realization and capture, not synthetic relabelling | Phase 3, §8 | T06–T07 |
| R04 | Supported user-facing launch configuration | §5–6 | T02–T04, T09 |
| R05 | Manipulation-level policy acceptance | Phase 4, §4, §11 | T08 |
| R06 | Bottom-up application/event model and GraphQL contracts; dashboard deferred | Phase 5, M0/M4/M5, §7, §9 | T10–T12 |
| R07 | Reuse engines/application rather than new controller/services | §2, §5, §8 | T01–T02 |
| R08 | Separate isolated/native/live/deployed evidence and authorization | §1–2, §10–11 | All gates retain their scope |
| R09 | Honest scene/policy/publication/prior distinctions | §2, §7, §9 | T07–T08 |
| R10 | Original identities, replay, cancellation and retained refresh | §6–9 | T04, T09–T12 |
| R11 | Neo4j is the sole authoritative application database; no SQLite runtime dependency/fallback | §2, M0, §7–8, §11 | T01/T13 |

## Parent findings and initial corrections

These findings apply to the local draft at resumption; later reviewers may inspect a newer revision. Do not merge version-specific claims without checking the bytes.

| ID | Classification / severity | Counterexample and decisive source | Adjudication / smallest correction |
| --- | --- | --- | --- |
| P01 | Unsupported completion claim / high | Draft said fully verified and SQLite retired; plan 02 status is guarded isolated, `web_api/events.py:15,90` still reads Journal | Supported; §1 retains scoped milestone and legacy authority |
| P02 | Wrong existing interfaces / high | Core `workflow/cli.py:41` only supports inspect-contract; `foreground_workflow.py:44` rejects live credentials/startup; `graph_rag/retriever.py` does not exist | Supported; §6 distinguishes current versus proposed launch; Phase 2 reuses `graph_rag.py:387` |
| P03 | Unsafe/incomplete credential and accounting proposal / high | Draft raw `--api-key`, automatic dotenv and preflight ping omitted private authority/allowance; current CLI private pipe and role grants exist | Supported; Phase 1/§6 require explicit secret source, full readiness, released metered constructor effects; no blanket backend redesign |
| P04 | Retrieval/publication model contradiction / high | Invented AcceptedEnvironmentGraph query bypassed actual EnvironmentGraph/evaluation/publication validators; node count misses property changes | Supported; Phase 2 reuses exact snapshot and eligibility; T05 checks actual records/read-only authority; publication remains separate |
| P05 | Invented native evidence contract / high | Draft fixed 40 steps, camera/depth names and physics thresholds; `scene_observation.py:31,368–471` has different constants and strict contact mapping | Supported; Phase 3 requires calibrated versioned producer and native mapping; positive and failure gates T06–T07 |
| P06 | False policy-success proxy / high | Draft proximity/peak height/XY containment substituted grasp/lift/place; `evaluation_worker.py:24` uses existing policy runner and fixed profiles | Supported; Phase 4/§4 reuse measured task predicates and exact completed episodes; no automatic policy-failure repair or publication |
| P07 | Missing application/GraphQL semantics / high | Draft facade-only section omitted existing events, lost ACK replay, owner-derived projection changes and in-memory grants | Supported; §6–9 define shared commands, ownership, revisions/pagination, security and deferred subscriptions |
| P08 | Unsupported estimate / medium | 28-hour total had no native calibration, supported installation or policy compatibility basis | Supported; §5 replaces hours with dependency/exit gates |

## Independent review rounds

Round 1 (`deleg_c2ec2465`): three read-only reviewers returned six findings each against the original local draft. Their old plan line numbers refer to that preserved revision, not the corrected plan. Parent inspected decisive source independently and mapped duplicates instead of counting them as separate blockers.

| Reviewer finding IDs | Disposition | Correction / remaining obligation |
| --- | --- | --- |
| A1 (provider review), C6 (application review) | Supported, duplicates of P02/P03 | §6 explicitly distinguishes inspection CLI from proposed installed execution; private pipe, no raw-key argv |
| A2 | Supported, extends P03 | Phase 1 now specifies explicit endpoint/model/key binding, mixed-key regression, legacy `NV_API_KEY` and explicit alias handling |
| A3 | Narrowed | Global constructor-ping removal is unnecessary for integration; keep managed pings charged after release, separate metadata readiness and enforce total probe deadlines. New validate_connection/two-second guarantee removed |
| A4/A5 | Supported, duplicates of P04 | Existing snapshot/provenance machinery, exact readback, required/optional fallback and read-authorized DB tests |
| A6/B1 | Supported, extends P05 | Extract builder mechanics only; native owned worker/profile and explicit environment lifetime; no hidden legacy critic |
| B2 | Supported, new N01 | DROID absolute-position zero action is not hold; runner settle report is not blocking. Phase 3 adds action-term-correct hold and blocking bounded settle gate |
| B3 | Supported, new N02 | Real RGB camera names, policy observation keys, 16-frame/128-KiB scene bounds versus 64-image helper ceiling; short exact window or versioned extension |
| B4 | Supported, narrows P06 | Freeze droid_abs_joint_pos / N1.6 DROID / OXE_DROID plus actual served identity; generic OpenVLA claim removed; no model-availability claim |
| B5 | Supported, extends P06 | Preserve actual sequential task predicates/denominators; operational success is not independent grasp certification; scene-only accepted must not terminally preempt required policy stage |
| B6 | Supported, new N03 | Capture and policy runner reset independently; Phase 3 requires reset→hold/settle→observation→rollout, or fresh prerequisites for each new cohort |
| C1/C3/C4/C5 | Supported, duplicates/expansions of P01/P07 | Existing root extraction, live typed outcomes and projection revision, transport-specific auth/private grants, application-lifetime owner and explicit stop IPC |
| C2 | Supported, new N04 | Workflow invalidation DTO/reconciler distinct from JobEvent; global scope cursor, no fabricated old-cursor/new-state snapshot, reconnect/multi-run tests |

Parent source checks: `droid.py:347–468`; `trajectory_capture.py:12–75`; `evaluation/policy_runner.py:104–249,466–505`; `pick_and_place_task.py:133–197`; `inference_backend.py:224–314`; `scene_observation.py:23–31,77–82,186–235,368–497`; `scene_loop.py:64–98`; `web/reconcile.ts:12–47`; checked-in DROID policy config camera/modality fields. These are static evidence only. Additional policy-terminal gating was added as an implementation obligation, not an observed native test failure.

Round 2 (`deleg_6c9f0898`): two fresh challenge reviewers inspected corrected plan/source. P01/P04/P05/P06/P08 were rejected **as remaining objections**, not retracted as historical findings; P02/P03/P07 narrowed to concrete integration details. Native source hazards N01–N03 remain genuine implementation obligations, not evidence that the plan still prescribes the original incorrect approach. Some reviewers read before the parent's latest native-detail patch; their already-corrected recommendations were not applied twice.

| Residual ID | Challenge and strongest counterargument | Parent adjudication / correction |
| --- | --- | --- |
| Q01 | Default task dwell is one step; wording “unchanged sustained lift” overstates the existing predicate even though task reuse is correct | Supported; reread `pick_and_place_task.py:69–75,133–197`. Phase 4/§4/T08 now say frozen operational lift/dwell/destination success, report actual parameters, and disclaim independent grasp certification; stronger dwell must be selected before release |
| Q02 | Scene/policy distinction exists, but current store still terminally accepts scene and foreground retires it | Narrowed; explicit nonterminal scene→reserved-policy handoff already added in Phase 4. T08 now includes crash/restart at that handoff; scene-only behavior preserved |
| Q03 | Submit lookup does not retrieve new cancel/resume command receipts | Supported medium gap; §9.1 now adds command_status/workflowCommand, scoped kind/key identity, canonical payloads, read-only lookup and proposed CLI command/flags; T11 cross-adapter/lost-ACK tests |
| Q04 | Metadata events cannot enter current full-JobEvent reducer; invalidation prose alone might be underspecified | Narrowed/already corrected; §9.2 explicitly selects separate workflow decoder/reconciler and scope-wide cursors, keeping legacy reducer unchanged; T11 adds the positive metadata-event regression |
| Q05 | Public/private binding examples and parser/factory extension were not explicit enough for onboarding | Supported low detail gap; §6.3 adds role/literal/source/private-slot mapping and coordinated installed parser/factory template acceptance. Phase 1 already documents NV_API_KEY and mixed-key rejection |

Rejected residual: the corrected plan equates scene acceptance and required policy success. Phase 4 and §7 already distinguish them; Q02 supplies the concrete current-store transition work rather than reopening the architecture finding. Rejected requirement: constructor pings must globally disappear; charged released pings satisfy the integration contract, while pure config/read paths stay effect-free.

Round 3 (`deleg_07555ad0`): a fresh read-only verifier read the full final plan/ledger and spot-checked decisive source. P01–P08 and N01–N04 passed as plan corrections; Q01/Q03/Q05 passed; Q02/Q04 narrowed and closed at planning level. No blocking contradiction was found. The verifier specifically checked scoped cross-adapter command keys, default one-step dwell limitations and the positive installed CLI→prior/model→native scene→required policy path, with GraphQL later. Review stops here; agreement does not establish runtime correctness or exhaustive coverage.

Remaining implementation/release gates under the corrected scope: shared domain/application and GraphQL contracts, installed parser/factory/templates, native hold/reset/capture calibration and provenance, transactional policy-stage integration, durable cancel/resume command receipts, backend GraphQL adapters and separately authorized provider/prior/native/policy acceptance. Dashboard integration is deferred, not a release gate. None is claimed implemented by this plan.

## Documentation verification

Initial citation verification: passed with evidence quotes for all 12 cited official sources; unused researched sources produce informational warnings. This checks citation identity/evidence presence, not independent correctness of every design claim. Repository facts use source anchors, and proposals are labelled as proposals.

Verification record:

- Scoped host pre-commit hooks passed on plan 03, this ledger and the references index after the initial trailing-whitespace hook normalized the draft. Applicable checks passed; Python-only hooks skipped. No whole-repository lint claim.
- Citation identity/evidence verification passed for all 12 cited official sources. Warnings identify unused research sources; no unknown citation or missing cited evidence. Repository facts and design proposals are separately source-anchored/labelled, so the low overall numeric-citation fraction is not claimed as factual-coverage proof.
- Static checks found balanced fenced blocks, existing relative link targets, unique R01–R10 and T01–T12 definitions and no undefined test references.
- The 377-file source fingerprint has no drift. Seven additionally inspected native/task/policy/camera files match the same HEAD bytes. Exact local checks: `outputs/workflow/plan03-research/documentation-checks.json`; inventory is not reviewed coverage.
- Historical independently reviewed plan SHA-256: `4a823f7a9e8a230738143e5ef1f59d45cd0b7aa089c0c3b4001f225124695e63`. The later user-directed scope correction changes those bytes; do not present this digest/review as verification of the corrected scope.
- Repository changes are limited to the pre-existing references-index edit, revised untracked plan 03 and new companion ledger. Local ignored research/verification artifacts are not committed deliverables. No code edits, staging or commits; no runtime tests or live workloads executed.
