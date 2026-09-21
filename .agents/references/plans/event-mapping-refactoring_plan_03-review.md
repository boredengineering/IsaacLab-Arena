# Plan 03 source-grounded review ledger

Status: the bounded planning review passed, and the user subsequently authorized source implementation and admitted isolated tests. M0 modeling records have passed independent critique; implementation progress/evidence is owned by the linked handoff. Earlier verdicts below apply only to their recorded revisions. Native calibration and live acceptance remain unexecuted.

Canonical plan: [event-mapping-refactoring_plan_03.md](event-mapping-refactoring_plan_03.md). Implementation status remains in the [existing handoff](dashboard_cli_workflow_parity/research-stack-implementation-handoff.md). This ledger records documentation review, not implementation approval or runtime acceptance.

## Baseline and scope

### M0 modeling gate during authorized implementation

The user activated the plan-03 implementation goal with source/isolated-test authority and explicit live/protected-change exclusions. The [current handoff](dashboard_cli_workflow_parity/research-stack-implementation-handoff.md) records that authorization, all R/G/T delivery mappings and actual implementation evidence; this ledger remains the design/modeling review record.

`deleg_7f38ebf6` completed plan §7.4's M01–M15 records from the required original study and current source. Parent read back every record, verified all required modeling components/GWT cases and ran scoped documentation checks. Fresh critic `deleg_9acf4cb8` returned **PASS**: no concrete blocking contradiction in identity/authority/lifecycle/retention/actions, G01–G10 field-family coverage or the campaign map. In particular, cancel documents stop-before-DB/conflict-side delivery rather than promising impossible OS/DB rollback; resume separates recovery from continuation; historical cleanup, unsupported policy and readiness provenance remain explicit.

Reviewed model-bearing plan SHA-256: `00b9a0c902a9202401196070042589a7e6a1a5a96cababe9de2e731d289357c0`. Local structural check: `outputs/workflow/plan03-implementation/m0-model-record-checks.json`. This closes the per-interaction modeling prerequisite for the described effect-free slices, **not** T20's later executable-schema/application tests, all M0 repository work, or V0. Actual producer/profile/calibration selections remain gates for affected execution. The first event `source_id` readback increment is partial G10 work, not completion of typed causation/history/revision obligations.

### Latest review: complete development bootstrap and amended application contracts

- User asks whether anything remains missing after the general Physical AI, mandatory event-modeling and local credential/bootstrap clarifications, including operation from inside the editor devcontainer. Review scope is a usable single-operator research bootstrap and coherent V0 → joined V1 → V2 delivery, not production hardening or runtime implementation.
- Baseline: clean `dev/0.3.0-prerelease`, HEAD `8f40c55584c4998ac657128f433d4dd407a2905b`. Git comparison with `57a7d1f3fe67b1d2c3fa4a89a54f8ce5f8797b77` shows only the plan, ledger and reference-index changes. Starting plan SHA-256: `3e4c3a77c52bfac2a57760354f0e58bde2574e4af5d98ab649df0e6f95ca1ba3`. Public source/config fingerprint: `outputs/workflow/plan03-research/bootstrap-completeness-baseline.json`; inventory is not reviewed coverage.
- Round 1 `deleg_60b9fb53`: three read-only reviewers checked bootstrap/container identity and clients, original DDD-to-schema/general-task semantics, and native/policy reuse/delivery. Supported one medium bootstrap handoff gap and one low camera-activation clarification; no additional architectural contradiction. Parent independently traced historical cleanup projection and recorded provisional findings at `outputs/workflow/plan03-research/bootstrap-parent-findings.json`.
- Round 2 `deleg_4dde3eac`: two fresh challengers checked the proposed minimal bootstrap and attempted to disprove cleanup/camera/title concerns. Parent read decisive definitions/callers. No services, database queries, package execution, inference or real credential files were accessed.

| ID | Classification / adjudication and strongest counterargument | Accepted correction / implementation verification |
| --- | --- | --- |
| BC01 | Medium onboarding gap; supported, not a networking or new-worker-topology defect. Existing host-network configuration, private reader and same-container clients are compatible, but §6 did not select the path from root editor to host storage and simulator identity. Both container scripts lack the Arena credential mount | §6.2 now selects host-owned directory initialization, opt-in mapped-UID editor setup, read-only runtime directory mount and simulator-local client authentication via fixed-target wrapper. Runtime account/groups/HOME/config paths are explicit. Detached API launch is independent of editor/client lifetime; it is not the old per-command foreground CLI. T21 covers the full synthetic journey, update/restart, editor rebuild and stale auth |
| BC02 | Medium projection migration gap; narrowed, not missing cleanup evidence or unsafe takeover. `result_records` supplies the latest scope owner (`neo4j_store.py:1175,1872–1877`); `read_model.py:162–166` derives cleanup from its dirty flag. Exact worker cleanup/retired-owner records and historical recovery already exist (`foreground_recovery.py:143–176`) | §9.2 separates retained run/intent cleanup from current scope-owner activity/retirement. T10/T15 require cleaned run A to remain clean under a still-active owner or replacement B, while unresolved A never inherits unrelated cleanup. Reuse existing receipts/epochs rather than rebuilding ownership |
| BC03 | Low native extraction clarification; narrowed because camera/evidence acceptance already exists. Legacy extraction calls `to_arena_env()` with camera default false; conversion preserves an explicit false override (`arena_env_graph_spec.py:218–226`, `arena_env_graph_conversion_utils.py:144–146`). Graph parameters can already enable cameras, so failure is not universal | Phase 3 explicitly binds frozen camera activation through Kit and graph conversion. T06 covers omitted/default, explicit true, conflicting explicit false and missing observation keys; preserve camera-free profiles/legacy defaults and never silently rewrite a candidate |
| BC04 | Editorial clarification only; rejected as a substantive physics/simulator redesign defect. Existing text already reuses Arena and bounds repairs/calibration | Rename Phase 3 to connect existing Arena execution/capture and distinguish adapter wiring from tested hold/reset/window fixes. Explicitly forbid tuning physics or relaxing frozen criteria to manufacture acceptance. No new subsystem or test gate |

BC01 challenge details retained: the current `.devcontainer/devcontainer.json:89` helper fallback must not swallow a credential-initializer rejection; opt-in private initialization is a separate mandatory step. The runtime account's supplementary simulation group/HOME comes from `docker/setup/entrypoint.sh:23–28,59–60`, not merely a numeric UID. A mounted regular file, root-owned pipe or FD 0 does not satisfy `foreground_workflow_cli.py:171–188`; construct/populate/close the private pipe under the selected runtime identity. These are concrete bootstrap compatibility requirements, not a new security platform. Editor root/Docker-socket access is trusted; simulator-local auth avoids copying but does not isolate secrets from a hostile editor.

No additional correction is required for absent completed per-interaction modeling records: Phase 5/T20 already makes them an M0 prerequisite before each affected schema operation. Likewise, current policy-criterion rejection and synthetic-only factories are acknowledged implementation work, not proof the amended general architecture is contradictory. Existing engine reuse, Neo4j-only extraction, G01–G10 coverage and one joined V1 remain the selected direction. Calibration, installed dependency compatibility and positive native/provider/policy results remain release gates.

Round 3 `deleg_890bb825`: a fresh verifier read the complete corrected plan and checked decisive public source; **PASS at planning level**, with no remaining blocking contradiction found. BC01–BC03 corrections preserve positive paths and existing guards; BC04 remains editorial. DDD/GraphQL traceability, general-task T19/T20, Neo4j-only persistence and joined V1/V2 remain coherent. Review stops here; this is not exhaustive proof or runtime acceptance.

Verified plan SHA-256: `80668afec80649100d4dc79dc885eee1cc4782d4957ee95c72bc3e9731f6cb45`. Scoped pre-commit, `git diff --check`, relative links, balanced fences, unique R01–R16/T01–T21/G01–G10/BC01–BC04 definitions and proposed command shell syntax pass. Citation identity/evidence verification passes; unused research entries are informational warnings, not new factual coverage. Public source/config fingerprint remains unchanged. Exact local check record: `outputs/workflow/plan03-research/bootstrap-completeness-checks.json`.

All added tests are implementation obligations, not tests executed in this review. Only this ledger and plan 03 changed in the repository; no protected container configuration, application source or real credential storage was changed. No services, package tests, database/provider/native work, deployment, staging or commit occurred. The next implementation step remains M0/V0's completed domain/event records and Neo4j/application/GraphQL foundation, followed by the joined live slice—not another infrastructure platform.

### Subsequent clarification: launcher-managed local credential bootstrap

The user asks for explicit launcher creation/storage and emphasizes that this is bootstrap work before production readiness. Earlier plan text described private handoff but prohibited persistence, so it did not cover the agreed local-file approach. §6.2 now specifies hidden-prompt setup, owner-private files outside Git, versioned parsing, safe create/update/removal, host/container path handling, explicit loading, controlled restart/reapproval and a separate finite-lived runtime API-auth file. The default client walkthrough no longer requires manually assembled descriptors. The launcher stores operator-supplied third-party keys; it generates only the application's own auth token. No keys enter Neo4j/domain profiles/GraphQL/logs, and setup performs no inference/database/native probes.

The plaintext-at-rest and same-user/root/backup risks are explicit. Production secret management/identity/rotation/auditing remain later work behind the same credential-source boundary, not prerequisites for the research prototype. T21 requires synthetic-only end-to-end bootstrap tests. No real credential file was read, created or changed, and no launcher was implemented by this documentation amendment. The earlier memory-only-token and no-secret-persistence statements are superseded only by these explicit private-file bootstrap provisions.

### Subsequent clarification: implementing agents need the original modeling questions

The user re-emphasized the original `entity → identity → owner → lifecycle → persistence → available actions` study as a prerequisite for Phase 5. The plan already linked the study in §7.1, but that was insufficient as an implementation handoff. Phase 5 now requires direct reads of the session study, source inventory and plan 02 §§3/4/11/12; embeds the original five questions plus DDD/recovery follow-ups; and requires completed per-interaction modeling records linked to G01–G10 and Given/When/Then tests before implementing the affected schema. T20 enforces traceability. Backend reconnect/restart/read semantics remain in scope without reviving dashboard implementation. Existing documents are extended instead of adding another design home.

The quoted “many local schemas” diagnosis originated in an earlier assistant explanation and was reiterated by the user to restore the broader goal; it is not evidence that the user authored that diagnosis or approved every later design proposal. Historical notes inform semantics, while current source/status and the latest Neo4j-only/GraphQL/general-Physical-AI decisions govern implementation. This amendment is documentation-only and does not inherit the earlier revision's independent-review digest.

### Subsequent user clarification: scenario examples are not the architecture

The user clarified that the project targets general Physical AI, not the A2 example. Phase 4 is now **General Policy Evaluation and Task-Specific Acceptance**. A2/DROID/GR00T/lift-and-place assumptions are confined to the reference acceptance profile. Common application, Neo4j and GraphQL contracts bind task/embodiment/policy/evaluator identities and declared criteria without scenario-name branches or universal manipulation metrics. M3/V2/G09/T08 were generalized; T19 adds positive isolated contract coverage for distinct task semantics and another embodiment/action-interface binding. Existing TaskBase and OpenDoorTask sources ground the separation; no broad live compatibility is claimed.

This clarification changes the previously reviewed plan bytes. The prior independent verdict and digest below remain evidence for that earlier revision, not independent verification of this amendment. Scoped documentation and structural checks verify the amendment; runtime/generalization tests are implementation obligations, not executed results.

### Earlier review: original DDD method → full GraphQL → live integration

- User asks whether plan 03 is the right next implementation step for live inference/native simulation and fully transitions the application to GraphQL according to the prior event-storming/DDD/event-mapping study. Neo4j-only persistence and no dashboard work remain explicit constraints.
- Recovered original user statements: session `20260916_171442_92ddc8`, message `48723` requested a hypothetical step-by-step workflow to understand event modeling and document DDD for GraphQL information/API design; `48727` required command then modeling, without execution. Session `20260918_161956_6f5661`, message `54866` rejected local schemas without a coherent application model connecting research entities, workflow state, actions and retained state. The repository study records the five authority/identity/retention questions at `quick_notes/session_memory.md:25–61`.
- An exact history search for “event storming” returned no match; the broader DDD search recovered the actual study. The method's semantics are retained without claiming a formally completed EventStorming workshop or that newly proposed aggregate boundaries were already agreed. Official EventStorming/Event Modeling/DDD references are now cited in plan §7.1.
- Current HEAD is `57a7d1f3fe67b1d2c3fa4a89a54f8ce5f8797b77`, initially clean. Git shows only the three planning/index documents changed since source revision `3440d6352dc90ba2b2451bb29f29f8f0bd165af9`.
- Starting plan SHA-256: `09ce7b40526e819d5e83d3431c1c7b49386736f9d49dc9afa0653e6732419a3e`. New scoped inventory contains 661 first-party source/config paths; content fingerprint `be8acf4feb8843a6a5f1629f663ebe39ee40d53bbf42311fed02c72de8a369a9`. Exact records: `outputs/workflow/plan03-research/ddd-live-review-baseline.json`. Fingerprinting is not reviewed coverage.
- Round 1 `deleg_bbf5e8a6`: independent DDD, native, GraphQL/Neo4j and delivery-order reviewers read the frozen plan/source. Parent read decisive methods/imports/SQL/window/routing code before corrections. Round 2 `deleg_8a49460c` challenged and narrowed the findings; round 3 `deleg_01ff7389` verified the full corrected plan and spot-checked decisive source.

| ID | Supported gap / strongest existing counterargument | Correction and implementation verification |
| --- | --- | --- |
| DR01 | Entity table lacked domain invariant ownership; existing store already atomically commits decisions/reservations | §7.1 defines proposed logical contexts/run consistency root without replacing current atomicity; T15 concurrent-result/ownership gate |
| DR02 | Invalidation events plus latest view lose exact historical causes; current store already retains source_id internally | §7.2 named facts, typed source/causation/committed-version linkage and exact history queries; T10/T15 |
| DR03 | Scene→policy separation was stated but lacked a complete transition projection; current scene acceptance is terminal | §7.3 transition/outcome table preserves scene pass independently of failed/unknown/cancelled policy; T08/T15 |
| DR04 | Illustrative WorkflowResult/SDL could pass narrow tests without full research traversal | §9 G01–G10 coverage, typed candidate→decision→assessment→evidence traversal, WorkflowAdmitted naming and executable-schema gate; T16 |
| DR05 | One scene intent registers one model worker before parent capture; adding native child leaves ownership/deadline ambiguous | Phase 3 selects separately fenced capture/assessment stages with verified adoption/cleanup and original deadlines; T14 positive slow-capture and crash/recovery cases |
| DR06 | Post-settle windows conflict with zero-based admission/capture/displacement consumers | Phase 3 requires one absolute reset-relative offset across all consumers and charged settling; T14 nonzero-window proof |
| DR07 | Guard rejects forbidden repairs but actual refiner lacks original/permitted-delta envelope | Phase 3 bounded repair input; first supported repair is visual-only failure with physical pass, not general physical repair; T07 |
| DR08 | Profile hash alone does not configure module-global evaluator thresholds | Versioned exact settings bytes consumed at admission/production/evaluation/replay; T14 catalogue-change replay |
| DR09 | Neo4j-only intent missed eager web_api imports and SQL-backed managed-prior metadata | §8–9 extraction closure and Phase 2 migration of membership/reservation/readback repositories; T13 denies SQLite on positive retrieval/boot path |
| DR10 | HTTP principal/auth, process-private grants and direct CLI owner lifetime remained open choices | §6.4 selects local single-operator bearer auth with same-process long-lived owner/grants; §6 default network GraphQL CLI, no fallback; T09/T16 |
| DR11 | No explicit route from empty scope to immutable registered profiles/artifact identity | §6.5 admin initialization/register/open-verify contract; T17 fresh-process positive and missing-binding negatives |
| DR12 | Native CLI and isolated GraphQL could satisfy separate milestones without joined live delivery | §5 V0/V1/V2 and T18 require one GraphQL-submitted live scene run before policy extension, then same-boundary A2 |

Parent verdict at correction stage: right direction, but the prior revision was insufficiently explicit for unambiguous implementation. These are bounded missing connections/contracts, not a reason to rebuild the engines or add services. No model, GPU, database or package test executed during this review.

Round-2 challenge `deleg_8a49460c` narrowed the findings rather than treating every allegation as an absent subsystem:

- DR01/DR02/DR04: existing entities, evidence projections and internally retained source_id already supply foundations. Corrections add explicit ownership, typed causal traversal and enumerable schema coverage; they do not claim those foundations were missing or mandate event sourcing.
- DR05: rejected the broad claim that slow capture necessarily expires assessment. Existing `scene_ports.py:189–204` already checks capture plus model ceiling against the intent allowance. Remaining work is native ownership/topology and startup/retention/cleanup overhead. Separately fenced substages are a **selected design**, not the only theoretically valid design; a composite worker was considered but would need separately tracked native cleanup to satisfy GPU release before VLM. No second-registration API is assumed.
- DR06: retained evaluators already validate nonzero exact windows; only composition/reset/label/displacement consumers need the new propagation seam. Preserve existing evaluators/legacy defaults.
- DR07: original-baseline bounds and visual-only routing already enforce permission. The missing input is model guidance. Corrected “remaining allowance” to the original-centered admissible disk: no accidental cumulative-travel/shrinking-radius restriction; inward/tangential moves remain valid.
- DR08: existing runtime/capture profile identity/hashes remain. Bind actual native settings bytes/consumer parameters to them, not another registry.
- DR09: importing web_api eagerly imports legacy code but does not itself prove a DB was created; construction occurs in lifespan. Plain explicit-driver GraphRAG retrieval is not inherently SQLite-dependent. SQL migration is required for the managed callback path; do not silently discard that capability.
- DR10/DR11: added finite API authentication expiry/generation, private rotation/reapproval, grant-deadline caps and serialized private handoff. Default installed client is network GraphQL; emergency owner-local cancellation remains a distinct control path, not fallback execution. Explicit administration reuses existing schema/scope primitives rather than inventing another store.

Round 3 `deleg_01ff7389`: **passed at planning level**, with no blocking contradiction. The verifier confirmed DDD ownership/causation→Neo4j→typed GraphQL traversal; coherent native-stage ownership/window/settings/repair choices; Neo4j-only import/retrieval extraction; same-process authentication/grant/owner lifetime; explicit admin bootstrap; and one joined V1 GraphQL/live checkpoint before V2 policy. Earlier overbroad claims about slow-capture timeout, absent permission enforcement and absent nonzero-window evaluators remain rejected/narrowed, not silently promoted to defects. Review stops here.

Current parent conclusion: **the corrected plan is the right next implementation step**, beginning with V0 and a narrow V1 vertical slice rather than a dashboard migration or a new orchestration platform. Full GraphQL completion is G01–G10 plus their executable-schema/query tests, not the illustrative SDL alone. Numerical native calibration, installed package compatibility, exact provider/policy/profile settings and separately authorized positive live acceptance remain release gates, not performed tests.

Current verification record:

- Final reviewed plan SHA-256: `93eb2ad2cd6187bd797a5cbfbf8103b75814491abeb8d69731f3aeb24e1c9681`.
- Scoped host pre-commit, citation identity/evidence verification and `git diff --check` passed. All 15 cited official sources have evidence quotes; unused research sources yield informational warnings only.
- Static checks reconcile 12 requirement IDs, 12 DR finding IDs, 18 acceptance-test IDs and 10 GraphQL-coverage IDs; links/fences and proposed CLI shell syntax pass. Proposed commands were not executed.
- The 661-file source/config snapshot has no drift; only plan 03, this ledger and the references index were edited. Exact local evidence: `outputs/workflow/plan03-research/ddd-live-review-checks.json` and its baseline manifest. Inventory size is not reviewed coverage.
- No runtime tests, package imports, service/database operations, live inference, native simulation, installation, staging or commit. Source/tabletop/plan verification does not establish deployment or scientific acceptance.

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
| R03 | Native realization and capture, not synthetic relabelling | Phase 3, §8 | T06–T07/T14 |
| R04 | Supported user-facing launch configuration | §5–6 | T02–T04, T09 |
| R05 | Task-bound policy acceptance, with manipulation as a reference example | Phase 4, §4, §11 | T08/T19 |
| R06 | Bottom-up DDD ownership/event-causation model and complete GraphQL contracts; dashboard deferred | Phase 5, M0/M4/M5, §7, §9 G01–G10 | T10–T12/T15–T16 |
| R07 | Reuse engines/application rather than new controller/services | §2, §5, §8 | T01–T02 |
| R08 | Separate isolated/native/live/deployed evidence and authorization | §1–2, §10–11 | All gates retain their scope |
| R09 | Honest scene/policy/publication/prior distinctions | §2, §7, §9 | T07–T08 |
| R10 | Original identities, replay, cancellation and retained refresh | §6–9 | T04, T09–T12 |
| R11 | Neo4j is the sole authoritative application database; no SQLite runtime dependency/fallback | §2, M0, §7–8, §11 | T01/T13 |
| R12 | Joined live inference/native workflow through GraphQL, with explicit initialization and request-independent owner | §5 V0/V1/V2, §6.4–6.5 | T09/T14/T17–T18 |
| R13 | General Physical AI architecture; A2 is an example, not hardcoded task/embodiment/policy semantics | Phase 4, M3/V2, G09 | T08/T19 |
| R14 | Original domain/event-modeling questions are mandatory implementation inputs, with explicit answers driving the schema | Phase 5 mandatory study, §7, §9 | T20 |
| R15 | Launcher creates/stores/loads local credentials for a usable research bootstrap, not a production secret manager | §6.2–6.4, M1 | T21 |
| R16 | Bootstrap works from the root editor devcontainer with explicit host persistence, mapped runtime identity and usable simulator-local clients | §6.1–6.4 selected topology | T21 and T09; protected mount changes remain separately approved |

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
