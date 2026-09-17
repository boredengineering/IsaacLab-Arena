# Dashboard implementation checkpoint — paused

Updated: 2026-09-17. This is the single current dashboard handoff, not a new strategy or an instruction to resume implementation.

## 1. User decision and latest failure

The user reports: **“I refreshed the page and everything disappeared.”** They are concerned that successive plans and fixes have made the repository convoluted. They requested saved session progress and consolidated references, then intend to commit themselves and reconsider the strategy.

**Implementation is paused. Dashboard reliability is unresolved; full V7/CLI parity is not accepted.** Earlier “live delivery” and “fixed” reports describe bounded observations before this report, not reliable user delivery. It is not established whether the disappearance affects rendering, session state, unsaved drafts or persisted data. No data-loss diagnosis or recovery is claimed. No further application edits, service changes or workload release are part of this documentation checkpoint.

## 2. Checkout and commit boundary

- Checkout: `/workspaces/IsaacLab-Arena`, branch `dev/0.3.0-prerelease`.
- HEAD at checkpoint: `f9519bd3ef` (`reviewing dashboard`, 2026-09-16).
- There are modified tracked files and untracked implementation/evidence files. No staging or commit was performed for this handoff; the user owns the commit decision.
- A commit preserves selected source/docs, **not** the installed host helper, private profiles, SQLite journals, browser state, cached images/dependency volumes or ignored verification artifacts.
- No new strategy has been selected. Old plan authorizations below do not override the pause.

## 3. Intended workflow retained

The baseline remains the existing [agentic generation README](../../../../isaaclab_arena_examples/agentic_environment_generation/README.md): prompt-first generation using Graph-RAG, inspect, build, and separately evaluate. Reuse the existing agent, retriever, relation solver and policy runner; this handoff does not propose a replacement architecture.

LPG/Neo4j, RDF/reification, provenance, measured outcomes and bounded DCRG corrections remain the research context. Do not equate declared relations with physically realized placement, or RDF reification with proven native RDF-star/lossless round-tripping. The A2 banana/plate placement failure remains unresolved: valid YAML and a short Build did not prove objects spawned on the table.

## 4. What exists, and what was actually observed

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

1. This checkpoint: current stop state and limits.
2. [Session memory](../../quick_notes/session_memory.md): short decision record and conversation recovery anchor.
3. [Historical progress log](implementation-progress.md): provenance only; contradictory “current” paragraphs are superseded.
4. [Dashboard design](../dashboard_cli_workflow_parity.md), [endpoint contracts](endpoint-contract-plan.md), [research-stack design](research-stack-readiness.md), [model-profile contract](model-profile-contract.md): retained design records, not a new execution mandate.

Wait for the user's new strategy. Do not resume fixes, releases, experiments or another planning expansion merely because an older document says “implementation authorized.”
