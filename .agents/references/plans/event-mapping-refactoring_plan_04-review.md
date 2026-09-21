# Plan 04 planning review ledger

Canonical plan: [event-mapping-refactoring_plan_04.md](event-mapping-refactoring_plan_04.md).
Implementation progress remains in the [canonical handoff](dashboard_cli_workflow_parity/research-stack-implementation-handoff.md). This ledger records source/document review only, not execution authorization or runtime acceptance.

## Baseline and scope

- User requested a new gap-closing plan grounded in Plan 03 and the v03 notes, with a solid live trial using production Neo4j, heavy Arena/GR00T containers and live API keys.
- Planning baseline: clean `dev/0.3.0-prerelease`, HEAD `d8a75da704be268b32a11952cb84be638a80222d`.
- Direct-read inputs: Plan 03, its review ledger, `.agents/references/quick_notes/event-mapping-refactoring_v03_notes.md`, latest native/policy handoff and developer documentation, repository startup/container skills, current API/application/policy composition and project manifest.
- Local retained baseline: `outputs/workflow/plan04-planning/baseline.json`, including input/source hashes. Fingerprinted inventory is not reviewed coverage.
- Parent checked Plan 03's final verification manifest: 1,550 case occurrences across 11 recorded cohorts; recorded repository-source hashes match current files. This was evidence-file readback, not rerunning tests or inspecting live resources. Its explicit scope excludes live M2/M3 and V1/V2 acceptance.
- No package imports/tests, credential-file access, service/container actions, GPU/model effects, production DB access, provisioning, protected configuration edits, staging or commits are part of this planning review.

## Parent findings incorporated in draft

| ID | Classification / finding | Existing positive evidence / bounded conclusion | Correction |
| --- | --- | --- | --- |
| PR04-01 | High status contradiction: v03 notes seal V0/V1/V2 and broadly retire SQLite | 1,550 isolated case occurrences really are retained; they do not establish live delivery or global legacy removal | Plan §2 retains evidence and explicitly corrects claims without rewriting notes |
| PR04-02 | High integration gap: installed mode is query-only | Current `api/schema.py`, `installed_config.py`, `server.py` and docs deliberately enforce it; not a broken execution feature | G04-01/02, P1 preserve query-only and add separately admitted joined owner/commands |
| PR04-03 | High integration gap: policy bridge requires supplied runtime/cohort/evaluator ports | `policy_evaluation.py:26–53` documents caller ownership; split foreground supports capture/assess/repair | G04-03/05, P2 require concrete owned policy adapter and fresh-reset prerequisites |
| PR04-04 | High live-trial risk: production database, shared heavy services and keys must not inherit test-harness assumptions | Existing bounded lifecycle/private-source mechanisms are reusable, not live safety proof | §4 separates read/write/admin/publication, backup/restore, identity/topology/VRAM, role secrets and approval ceilings |
| PR04-05 | Medium scientific claim gap: safe completion is not successful manipulation | Plan 03 already requires two predeclared seeds and frozen PickAndPlace predicates | §§1/5 retain four verdicts, fixed candidate/seeds, all failures, no robustness claim |
| PR04-06 | Medium onboarding contradictions: speculative CLI/ports/RGB-D | Current docs state query-only and RGB, actual parser is authoritative | §2 correction table and §7 exercised runbook contract |

## Independent review

Round 1 `deleg_9f19dd7a` completed three independent source reviews: native/policy integration, application/production persistence, and operational/scientific trial design. All reported no edits/runtime effects. Their findings predominantly confirm unfinished Plan 03 integrations, not newly reproduced defects in completed components.

| ID | Adjudication / strongest existing counterargument | Correction and required evidence |
| --- | --- | --- |
| IR04-01 | Supported integration gap: policy worker is missing, but service cleanup/adoption guards already exist | G04-03/P2 reuse existing stage registration/service rather than rebuilding a controller |
| IR04-02 | Supported native reset hazard: parent directly confirmed `initialize_and_settle` unconditionally resets; existing runner hooks support initialized cohorts | P2 explicitly requires already-reset preparation and actual reset/recorder-order regressions |
| IR04-03 | Supported provenance gap: parent read solver fallback warning; builder/sampler checks exist but do not retain selected-layout validation disposition | P3 bounded selected-layout/validator/actual-pose receipt and effective/no-effect repair witnesses |
| IR04-04 | Supported calibration limitation, not an instruction to remove guards: current object/contact mapping and support predicate are narrow; RGB capture safeguards exist | P3 requires actual A2 endpoint/mapping/calibration or a versioned supported adapter, plus camera calibration/pose receipts |
| IR04-05 | Supported managed-policy attestation gap: existing server has guarded dispatch/codec verification; parent confirmed model-directory fingerprint excludes SDK/Eagle dependencies | P3 requires expected-server pins and observed runtime identity, not request echo or ping-as-inference |
| IR04-06 | Supported resource/coverage gate: native flock is not VRAM; seed-bound trial model and real decoder are reusable | §4.4 and P3/P5 require measured co-residency, separate seed-bound runs if necessary, exact completed records and task-stage diagnostics |
| IR04-07 | Supported retrieval-selection/recovery gap: existing immutable prior promotion rejects conflicting bytes but does not prevent a new query first; parent confirmed `_generate`→factory and capture→retriever ordering | P1/A04-04 freeze request retrieval policy, recover authoritative retained reference before retrieval, test interrupted retention with changed corpus/revoked retrieval access |
| IR04-08 | Supported query-detail gap: parent directly read `Capabilities.unsupported` listing detail/artifact gaps; summary queries genuinely work | P1/G04-12/A04-14 add bounded typed traversal and authenticated exact-byte access, not filesystem-only proof |
| IR04-09 | Supported operational release requirement, not a demonstrated production DB defect | §4.3 and §8 select admin-compatible recovery, separate role/DDL permissions, bounded noninterference claims, no production chaos tests, codec-compatible code rollback |
| IR04-10 | Supported unsupported-resume boundary; current keyed handlers already have exact receipt/selection/latch guards | P1 requires completing needed branches or truthful blocked capability and tests, not generic retry on unknown effects |

Round 2 `deleg_69b27e6a` completed two fresh challenges against draft SHA-256 `3d0bb32392597e246018e9fdfda11c4969d0acd4c3e2ea54daea4204104b2ae1`. No architecture-level circularity was demonstrated. Two narrow planning corrections survived; broader objections were rejected or narrowed to already-declared implementation gates.

| ID | Adjudication / counterargument | Correction / verification obligation |
| --- | --- | --- |
| CR04-01 | Supported sequencing omission: current scene start requires the policy profile to match a candidate not known before generation. Later repair substitution exists but occurs too late to solve the initial check. Parent directly read `neo4j_store.py:3493–3495` | P1/P2 now select pre-generation capability/pin/derivation-rule admission, then candidate-specific durable binding after verified adoption. A04-13 requires unknown-generated-digest positive and exact recovery; no weaker mismatch check |
| CR04-02 | Narrowed campaign-budget omission: cumulative intent was explicit, but parent confirmed `neo4j_store.py:3302–3339` only totals one run | §4.1 selects fixed nonoverlapping suballocations and exact-operation/payload allowlist, summed conservative bounds, one-shot diagnostic receipts, original expiry and no unknown/refund recycling; A04-15 cross-run/restart exhaustion. Both V1 and separate V2 generation are allocated |
| CR04-03 | Narrowed, already-required implementation: scalar seeds and same-run generation guards make reuse absent, but P5 explicitly prohibited manual insertion and required a supported path | P1 owns typed reuse admission; P2 consumes exact bytes/digest with new ownership/fresh evidence and original generation linkage. A04-13 second-seed positive plus foreign/tampered negatives before live spending |
| CR04-04 | Narrowed feasibility gate, not demonstrated impossible cycle: a paused live environment does not satisfy cleanup-gated GPU release; draft already forbids that shortcut | P2 exit explicitly names the reset-prerequisite strategy and isolated witness; P3 owns native witness. Any cloud reassessment needs its own explicit calibration allocation. Unsupported obligations block rather than weaken |
| CR04-05 | Rejected planning gap: runtime attestation treated as measurement proof | Plan already requires observed bindings, concrete evidence producers, extended SDK/Eagle pins and real native/inference witnesses; current helpers remain unverified at live level |
| CR04-06 | Rejected planning gap: production DB recovery materially unspecified | Explicit DB/scope choice, admin-selected recoverable backup/restore, separate DDL, bounded noninterference and codec-compatible rollback already present; residual scoping/ACL limits disclosed |
| CR04-07 | Rejected planning gap: isolated passes substitute for live acceptance | Distinct P1 isolated, P2 rehearsal, P3 calibration and positive P4/P5 joined trials explicitly required; no completed live claim |
| CR04-08 | Rejected planning gap: independent causal/artifact API readback absent | G04-12/P1/A04-14 explicitly add currently missing typed detail/bytes, scope/tamper checks and fresh-reader reconstruction; local filesystem inspection alone cannot close the gate |

Round 3 `deleg_d102b466` returned **PASS at planning level**, with no blocking contradiction in its bounded review. It read the full plan/ledger and checked decisive source for candidate binding, per-run accounting, same-run adoption and unconditional native reset. It verified the corrected candidate-binding sequence, fixed cross-run allocations, provenance-preserving second-seed reuse, reset/lease feasibility gate and positive application-owned path. Implementation/calibration/deployment choices remain future gates, not actions performed during planning. The bounded review stops here; agreement is not exhaustive defect detection or live readiness.

## Verification

Reviewed plan SHA-256: `9f9e1757c58db6adb04f6412d9837837889f94832c72a360ddfee540d2568d9a`.

Parent checks passed: scoped host pre-commit hooks, local Markdown links, balanced fences, unique/sequential G04/A04/PR04/IR04/CR04 definitions, P0–P6 headings, whitespace/EOF, `git diff --check`, unchanged baseline HEAD and unchanged fingerprinted source/input files. Exact readback: `outputs/workflow/plan04-planning/document-verification.json`; repeatable stdlib-only checker: `verify_documents.py` beside it. No application test or live-readiness claim follows from these documentation checks.

Deliverables are this review ledger and the new Plan 04; historical notes, Plan 03 and canonical implementation handoff were preserved. All A04 rows remain future implementation/live obligations, not performed acceptance tests. No production DB access, credential inspection, container/service operation, native/model execution, staging or commit occurred.
