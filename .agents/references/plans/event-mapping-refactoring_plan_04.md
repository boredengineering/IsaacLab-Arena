# Event Mapping Refactoring Plan 04: Close the Live-Execution Gaps and Validate the Research Workflow

Status: proposed implementation and validation plan. Creating or approving this document is not permission to use live credentials, write production Neo4j, start/recreate containers, or run GPU/provider workloads. Each effectful gate requires the bounded authorization described below.

Baseline: `d8a75da704be268b32a11952cb84be638a80222d`, branch `dev/0.3.0-prerelease`; worktree clean at planning intake. Runtime services and real credentials were not inspected. Container names, ports, available memory and installed dependencies remain deployment-time observations, not facts inferred from old notes.

Inputs and ownership:
- [Plan 03](event-mapping-refactoring_plan_03.md), especially §§2–6, §7 modeling records, §9 G01–G10 and §10 T01–T21, remains the architectural/semantic contract.
- [v03 notes](../quick_notes/event-mapping-refactoring_v03_notes.md) preserve the brainstorm and historical progress claims; corrections below govern this plan without rewriting their attribution.
- [Canonical implementation handoff](dashboard_cli_workflow_parity/research-stack-implementation-handoff.md) remains the implementation-status owner. This plan does not create another completion history.
- [Native/policy adapter documentation](../../../docs/pages/example_workflows/agentic_env_gen/workflow_native_policy.rst) describes the implemented boundary. Resolve repository paths from the root; relative documentation links are verified during review.
- [Plan 04 review ledger](event-mapping-refactoring_plan_04-review.md) records findings, challenges and planning verification. Local source/evidence fingerprints live in `outputs/workflow/plan04-planning/`.

## 1. Goal and definition of success

Deliver a usable, application-owned, GraphQL-submitted research workflow using the actual approved Neo4j deployment, IsaacLab-Arena runtime and Isaac-GR00T policy service. Prove the application invokes the existing tools and owns the next transitions; an agent manually inspecting results and issuing the next stage is not end-to-end acceptance.

The delivery path is:

`authenticated submission → exact retained priors → generation → schema validation → owned native realization/settling/capture → retained numeric + visual assessment → permitted repair/fresh evidence if needed → scene disposition → required task-bound policy evaluation → retained result → fresh-client causal readback`

The first reference scenario is A2, not a scenario-specific application architecture. Preserve generic task/embodiment/policy/evaluator contracts and cross-task isolated tests. Preserve scene-only workflows. Publication and successful-prior eligibility are separate from workflow acceptance and remain disabled for the pilot unless independently authorized.

Four verdicts must remain separate:
1. **Software integration:** the installed interface drives the real declared adapters, persists exact identities and returns truthful results.
2. **Operational safety:** authorization, cumulative ceilings, cleanup and production-data boundaries behaved as declared.
3. **Scientific/task result:** scene validity and measured task success, failure or unknown for every predeclared trial.
4. **Release decision:** whether the evidence is sufficient to advance to frontend integration. Passing isolated tests or an explained failed manipulation is not successful A2 validation.

No dashboard implementation, general service manager, new job database, new simulator, policy training, automatic policy-diagnosis repair, production secret-management platform or broad cleanup is included. Reuse existing coordinators, owned workers, artifacts, runner and repository APIs. Production data warrants stronger operational discipline, not an unrelated infrastructure rewrite.

## 2. Reconcile progress before implementing

### 2.1 Evidence-supported baseline

Parent verification read `outputs/workflow/plan03-implementation/m2-m3-parent/final-verification.json` and compared its recorded repository-source hashes with the current checkout. They match at intake. The recorded sum is **1,550 test-case occurrences across 11 cohorts**, not 1,550 unique requirements or live experiments. The manifest explicitly excludes live M2/M3 and V1/V2 acceptance. This planning pass did not rerun those tests or recheck current service state.

Implemented foundations worth preserving include: Neo4j authority/recovery/read models; private bootstrap/provider boundaries; installed query-only GraphQL/CLI; native realization/hold/strict settle/capture; split capture/assessment and cleanup-gated GPU release; policy contracts/runner bridge/episode decoder; durable nonterminal policy handoff; typed retained policy projections. The native/numeric child transports were tested with synthetic native/process seams and real local pipes/artifacts, not launched Kit children.

### 2.2 Corrections to the v03 brainstorm

| Notes claim / shortcut | Plan 04 interpretation and correction |
| --- | --- |
| M2/M3 complete and V0/V1/V2 sealed after automated checks | Adapter/lifecycle implementation is isolated-tested. Plan 03 V0 also requires submission/recovery through GraphQL; V1/V2 require joined live execution. These gates remain open. |
| SQLite retired completely; pure Neo4j event sourcing | Neo4j is the required authority for the refactored application. Legacy SQLite code still exists outside it. Audit the selected transitive execution/retrieval path, not global absence of a filename. Retained commands/events do not alone imply full event sourcing or deterministic replay of stochastic physics/models. |
| `client run`, example YAML/configuration and fixed ports already work | Existing installed mode is query-only. Derive future executable commands from implemented parser/schema/help and test them from a fresh client. Historical ports/configurations are not an operator recipe. |
| RGB-D snapshot | Current DROID capture supports RGB; no depth capability is established. Keep policy and evaluator image transformations distinct. |
| Start the listed containers before reviewing dependencies | Discover exact existing services and their owners first. No implicit restart, rebuild, image pull, download or migration. |
| Live trial is a dry run | Native steps, paid model calls and production writes are real effects. Only a no-effect contract/preflight inspection is a dry run. |
| All fixtures passing implies causal logging is deterministic | Verify exact retained cause/identity/version relationships and monotonic reservations. Do not require identical stochastic outputs or infer physics fidelity from hashes. |
| Run all formatters and clean temporary outputs before a PR | Use scoped checks first; classify baseline failures and avoid unrelated churn. Preserve failed runs and hash-bound evidence; retention/deletion and commits/PRs need separate decisions. |
| Frontend work follows automatically | Frontend remains gated on the joined evidence and an explicit handoff decision; this plan does not authorize deleting REST/SSE/legacy data. |

Historical assistant interpretations in the notes are not new user requirements. Preserve the user's actual goal: a coherent research application, safely validated in live simulation before frontend integration.

## 3. Gap register and smallest intended corrections

All paths below are repository-relative. Source observations are bounded to the baseline; review them again before implementation. An open integration seam is not automatically a defective completed component.

| ID | Current boundary / evidence | Required correction or runtime proof | Gate |
| --- | --- | --- | --- |
| G04-01 | `workflow/api/schema.py` reports `query_only=True`; `api/installed_config.py` admits only query-only mode; `api/server.py` composes query resources | Add an explicit versioned execution composition and GraphQL/CLI command adapters over shared application methods. Preserve query-only mode; never remove guards to repurpose the isolated factory. | P1 |
| G04-02 | `workflow/application.py`, `service.py` and durable handlers exist, but query-server lifetime is not an execution-owner integration proof | Join one long-lived scope owner, private authority interlock and bounded driver; requests submit/query rather than own native children. Exercise active cancel, disconnect, lost ACK and known-unreleased resume through the same installed boundary. | P1 |
| G04-03 | `workflow/policy_evaluation.py:26–53` explicitly requires trusted runtime/cohort/evaluator ports and leaves creation, watchdog, cleanup and retention to its caller; `foreground_split_scene_ports.py` supplies capture/assess/repair, not policy | Supply the supported owned policy worker and concrete runtime/task/checkpoint/recorder adapters. Reuse `rollout_policy`; preserve exact released intent, deadlines and cleanup-before-adoption. | P2 |
| G04-04 | `native_capture.py`, `native_realization.py`, `scene_observation.py` are isolated-tested; receipts still say `native-unverified` | Calibrate actual posture, velocity, action ordering, prim/contact mapping, coordinates, camera activation/freshness and authored→solver→realized poses using actual PhysX. Integrity hashes do not certify the measurement. | P3 |
| G04-05 | Single-reset capture and post-reset policy hooks exist; a separately built policy environment is a new cohort | Re-establish all state-dependent prerequisites for every actual policy reset, with fresh IDs/evidence and charged steps. Decide how visual prerequisites are certified without holding the GPU across a slow VLM call; unsupported policies remain blocked, not assumed equivalent by seed. | P2/P3 |
| G04-06 | Native shared flock and verified cleanup ordering exist; they do not prove a separately running GR00T server releases resident VRAM | Select a tested co-residency topology with enough headroom or distinct devices. A same-device joint rollout needs simultaneous policy + simulator availability. Record service residency separately from the native slot; no unsafe lease release or kill to manufacture readiness. | P0/P3 |
| G04-07 | Source supports prior snapshots; Plan 03 identifies managed-prior metadata paths that used Journal/SQL; `_generate` calls its prior factory again on continuation | Freeze the retrieval selection in the accepted request and recover exact retained prior references before any new retrieval. Required unavailable priors block before model initialization. Prove nonempty eligible consumed priors; do not silently call legacy-only support a managed-prior migration. | P1/P4 |
| G04-08 | Model role/profile/allowance primitives exist; live compatible model pair and total transport behavior are not certified by configuration | Pin literal endpoint/model/routing, actual request/image capability, constructor pings, retries, pricing bounds and all paid attempts. Reuse actual generation/assessment/refiner entrypoints with private role injection and no ambient fallback. | P1/P4 |
| G04-09 | Query/store regressions used disposable Neo4j, not the target production database/schema/privileges | Separate research reads, operational pilot writes and admin DDL; approve backup/restore and a fresh pilot scope. Verify actual schema/index compatibility and bounded queries before any pilot write. | P0/P4 |
| G04-10 | Synthetic native transport tests do not prove Kit/process-group/parent-death behavior | Rehearse real owned-child startup, hard deadline, cancellation, nonzero shutdown and cleanup on dedicated test work, not fault injection against shared DB/GR00T. Unknown cleanup blocks further release. | P2/P3 |
| G04-11 | A2 contract fixtures and typed policy projections exist; successful live manipulation is absent | Pin real GR00T instance/weights/processor/serializer/modalities and operational PickAndPlace evaluator. Retain completed episodes, raw predicates, denominator and independently inspect video. | P3/P5 |
| G04-12 | Separate component/source proofs exist; `api/schema.py:1180–1188` still declares scene/generation detail and artifact bytes unsupported | Add bounded authenticated typed evidence/prior traversal and exact immutable-artifact access, then an exercised runbook and joined manifest. Correlate operation→run→intent→child→artifact→decision→trial; fresh clients reconstruct outcomes without provider keys or filesystem access. | P1/P4/P5/P6 |

P0 expands this bounded register if source review finds another relevant gap. Use finding IDs, a concrete counterexample and a smallest correction; do not turn every unknown into speculative infrastructure work.

## 4. Authorization, secrets and production boundaries

### 4.1 One bounded approval packet per campaign

After source/isolated gates, present a consolidated packet for approval; avoid repetitive approvals within an unchanged approved envelope. Reapproval is required when a listed boundary changes, a ceiling is exhausted or an outcome is unknown. No missing field inherits an unlimited default.

The packet must contain:
- source revision plus dirty-content digest; resolved entrypoints and dependency/image digests; scope, run/operation identities and the exact plan revision;
- exact discovered container IDs/mount mappings, runtime account/UID/GID/groups/HOME, simulator interpreter, policy-service ownership and endpoints; allowed actions for each existing service;
- explicit Neo4j endpoint/database/deployment/workspace; read-prior versus write-operational roles; allowed schema operations, backup/restore owner and pilot retention policy;
- literal generation/assessment/refinement provider models/endpoints/routing, task/policy/runtime/capture/evaluator revisions and seed schedule;
- total monetary ceiling and conservative rates, calls including pings/retries, input/output/image/token bounds, candidate/repair/observation/episode/native-step counts, startup/model/native/cleanup deadlines and whole-campaign wall time;
- GPU UUID/device allocation, co-residency decision, measured headroom and failure margin, host RAM/CPU/disk/artifact quotas, one active native job, approved asset/model-cache sources and whether any downloads are allowed;
- private credential source references/generation only, release authority/expiry, local API-auth instance, escalation contact and exact-owner emergency stop/reconciliation procedure.

Budget values are mandatory deployment selections, not invented estimates. Derive cold startup and per-stage allowances from approved calibration, then freeze final-run ceilings before submission. Calibration itself has its own small approved envelope. Preserve spent reservations across stages; a restart, failed process, unknown response or second seed does not reset the campaign cap. Distinguish measured provider usage from conservative reservations and actual billing. The allocation inventory includes the scene-only V1 run and the separate V2 generation-to-first-seed-policy run; neither is free because the other already passed.

**Selected cross-run enforcement:** existing reservations are per run (`neo4j_store.py:3302–3339`), not a campaign spending account. Before any effect, partition the approved envelope into fixed, nonoverlapping suballocations for paid readiness, calibration, lifecycle rehearsal, the generated-scene/first-policy run, any controlled repair witness and the second-seed reuse run. Validate that the sum of conservative allocations fits every cumulative ceiling and freeze an absolute campaign expiry. Bind each allocation to one allowed operation identity and payload digest, then the exact returned run/attempt identity; grants and the installed driver reject unlisted or mismatched operations. Reuse Neo4j command/admission/profile records for durable allocation linkage and exact replay, not a mutable counter in an evidence file or another billing database. Diagnostic effects outside ordinary workflow runs need an equally exact one-shot owned invocation/retained receipt before they may use their allocation. Per-run guards enforce each slice; the fixed finite allowlist prevents extra runs spending the envelope again. Never recycle unused/unknown allocations automatically after restart or failure. Additional runs or repartitioning need amended approval and must preserve all earlier allocations. A04-15 requires an isolated multi-run/restart exhaustion witness; this binding/allowlist is implementation work, not an existing campaign-budget capability.

### 4.2 Live credential handling

Use the existing owner-private, explicitly configured bootstrap source and trusted launcher. The operator supplies real keys through the supported private setup path; agents/reviewers never request key values in chat or inspect credential files. Saving keys is not authorizing calls. Do not discover `.env`, copy secrets into public configuration, argv, model prompts, Neo4j or evidence, or use whichever provider key happens to exist.

The launcher may read the selected secret source as part of separately approved execution; the plan does not prohibit that necessary runtime access. Give each child only its required private authority: native capture/numeric evaluation need no model keys; policy execution does not need cloud-provider keys unless the explicitly selected policy requires them. Never hand all DB/provider slots to every worker.

Review SDK errors, tracebacks, stdout/stderr, HTTP logging, GraphQL variables, process-environment capture and Docker diagnostics before live use. Redact at the emission boundary; scanning artifacts afterward cannot undo a leak. Use synthetic sentinels for positive and failure paths, do not scan real keys by printing them. Avoid unfiltered `docker inspect`/environment dumps. Record masked configured/authorized state, not secret hashes or values. Check provider data handling for the intended prompts/images and prohibit private unrelated research data in requests. A suspected leak stops the campaign and triggers operator-directed provider-side revocation; deleting a local file is not revocation.

The local single-user secret file remains plaintext accessible to its owner/root and backups. Loopback/token restrictions do not isolate a hostile same-user process or Docker-socket holder. This research trial does not certify multi-user production security.

### 4.3 Production Neo4j safety contract

Treat the user's production database as valuable shared data, even if it is on a local workstation.

1. **Observe first, explicitly authorized:** targeted metadata/schema/index/privilege and bounded exact prior reads only. No broad corpus dump, profile/write query disguised as readiness, lazy schema installation or test-fixture initialization. Access mode is not a privilege boundary.
2. **Choose deployment shape:** prefer a dedicated operational pilot database on the approved production service if supported and provisioned by its administrator. Otherwise use a new deployment/workspace pilot scope with reviewed scoped writers in the existing database. Namespace scoping is application isolation, not database ACL isolation; explicitly accept that residual risk or block. No automatic fallback from one choice to the other.
3. **Backup/restore gate before writes:** administrator selects the procedure supported by the actual Neo4j version, edition and deployment. Retain a recent verified recoverable backup/snapshot identifier, retention location and restore rehearsal/evidence from a separate target. Do not presume online backup or multiple user databases are available. If a safe backup requires downtime, schedule it; never stop production opportunistically. Restoring a whole production database is not normal pilot rollback.
4. **Schema gate:** compare required constraints/indexes and label/property conventions to the current database; review collision and legacy compatibility. DDL is separate approved administration, with bounded ONLINE waits and readback. Normal startup/submission performs no DDL. A scoped pilot still shares global schema in a single database.
5. **Writer gate:** open only the explicit DB/scope/artifact binding; same binding replay is idempotent, mismatch rejects. Disable legacy runner graph sync, version-tree publication and automatic promotion. Pilot operational facts are authorized writes; research graph updates/publication are not included.
6. **Noninterference evidence:** retain exact touched IDs/relationships and scoped before/after observations; audit reviewed writer predicates and selected foreign sentinels. Sentinels/counts cannot prove global absence of changes in a concurrent database. Where stronger claims are needed, use administrator-provided transaction/audit evidence or a maintenance window, not full private-data exports.
7. **Rollback:** stop only owned execution, retain diagnostic records/artifacts, revoke further grants and mark the pilot disposition. Never issue wildcard deletion or destructive cleanup of shared records. Any later deletion uses a separately approved exact-owned-ID plan and referential checks; publication remains a separate action. On ambiguous commit, reconcile exact operation/intent IDs instead of resubmitting or restoring the database.

### 4.4 Heavy-container and GPU discipline

Resolve editor→host→simulator mount correspondence using the repository's [dev-container skill](../../skills/dev-container/SKILL.md); do not infer host identity from the editor's root HOME. Require exactly one selected runtime, not the first container matching a loose name. Run Arena package/native code with `/isaac-sim/python.sh` as the mapped non-root runtime user. Discover GR00T and Neo4j by their approved identity/configuration, not remembered names/ports.

Prefer already running, pinned services. Check accessible asset/model cache, writable run-specific output/TMPDIR/Kit paths, actual CUDA device identity and required Python dependencies before native startup. A query-test image or import success is not evidence the production simulator has the same optional API packages. Installations, image pulls, container recreation, mount changes and model downloads are distinct approvals. Never chmod broad runtime/cache trees to bypass permissions.

Keep one API owner inside the simulator namespace and its locally supervised children. The GR00T container is an independently owned inference service, not a child the workflow may kill by default. Preserve service state/settings and foreign jobs. For shared-GPU execution, show both simulator and served checkpoint fit together under the approved margin; serializing initialization alone cannot solve a rollout that needs both resident. Prefer distinct approved devices if co-residency cannot be established. Stop as unsupported-resource rather than silently offloading/changing model/dtype/physics.

A released native GPU flock is a physical-worker ownership fact, not proof all GPU allocations disappeared. Verify owned CUDA/process cleanup and account for declared persistent policy-server allocations. Slow VLM calls must not retain the native child/GPU lease; scope ownership may remain. Unknown process cleanup or contention blocks the next stage. No container-wide kill, shared-server shutdown, cache purge or `docker system prune` is a recovery mechanism.

## 5. Work packages and stop/go sequence

### P0 — Reconcile, review and freeze the campaign (no live effects)

Read Plan 03's original per-interaction models and the current implementation, not only the notes. For each changed operation answer: what happened, to which identity, who knows authoritatively, where it is retained, and what the user may see/do next. Extend the existing model/requirement map, not a competing architecture.

Perform a bounded source/security review of the selected call graph: installed API/CLI → shared handlers → grants/reservations → workers → actual tools → artifacts → Neo4j adoption → retained readback. Include all runtime imports and legacy defaults; check SQL/Journal dependencies and unauthorized provider/publication effects. Review native and policy lifetime separately. Preserve positive paths and known isolated proofs.

Deliver: updated gap dispositions; explicit production deployment/topology choices and approval-packet template; dependency/source fingerprint; narrow implementation file ownership; mapping to Plan 03 R/G/T obligations. Run scoped host formatting/license/secret-sentinel checks and the admitted isolated regressions after source changes. Record baseline lint separately. No all-files autoformat churn, no protected-file changes without asking, no secret inspection.

Exit: no unassigned critical path. A changed source snapshot requires review/rerun of affected evidence. No fixed completion date or unsupported assurance that all possible bugs have been found.

### P1 — Finish the joined installed application boundary (isolated first)

Add explicit execution mode/configuration and typed GraphQL submit/cancel/resume command adapters that delegate to existing shared handlers. CLI is an authenticated client, not a second owner or fallback executor. Preserve query-only startup and old retained shapes.

One long-lived execution owner handles committed intents independent of requests; offload blocking work without holding API request/global authority locks across simulation/model calls. Use current private grant interlocks at release. Bind operation payload/command receipt/run identity atomically and recover lost acknowledgements without creating duplicate work. Re-authenticate read/replay without demanding fresh provider secrets; new release after owner restart needs explicit reapproval.

Join exact supported provider/prior/capture/policy profile revisions and whole-outcome readiness. Requests needing an unsupported later phase fail before paid initialization. Complete the chosen Neo4j-only prior adapter; retain exact consumed bytes and label empty/optional/unavailable distinctly. Do not call the full managed-prior path complete if only a declared legacy Neo4j profile works.

**Selected candidate-binding sequence:** before generation, admit immutable policy/task/runtime capabilities, expected served-instance pins, criteria/aggregation and deterministic binding-derivation rules—not a guessed future candidate digest. After verified candidate adoption and before scene/policy release, derive and durably freeze the candidate-specific policy binding under the existing fenced transaction boundary. Preserve original task/policy pins, seed, budgets and deadline; recovery reopens that exact binding rather than deriving it from current defaults. The current scene-start check (`neo4j_store.py:3493–3495`) correctly rejects a mismatched preconstructed profile; later repair-candidate substitution is not a solution for the initial unknown digest. P1/P2 must join this derivation without weakening the check and prove a genuine generation output whose digest was unknown at initial admission. Candidate-specific unsupported geometry/evidence still stops before policy effects; capability readiness is not a prediction that generation will yield a valid scene.

P1 owns the typed provenance-preserving **reuse admission** needed for the second seed; P2 owns its native/policy consumption. Reuse immutable candidate bytes/digest with authoritative linkage to the original generated candidate, not another run's candidate ownership, generation fence or scene evidence. The new seed-bound run gets its own accepted command, candidate identity, fresh prerequisites and evaluation receipts. `ExistingSource` text alone does not implement this path, and current same-run adoption guards must remain. Test successful exact reuse plus cross-scope, tampered-byte and foreign-receipt rejection before P5; do not discover the missing command after paying for the first seed.

Version the accepted retrieval selection itself: source/database, eligibility/settings digest, required/optional policy and whether a successful empty result is permitted. Current `WorkflowContract` and installed operational-DB configuration are not proof those selections are frozen. Keep separate prior-read authority with no operational-credential fallback. `application.py:220–224` calls `prior_factory` on generation entry, and `prior_artifacts.py:44–55` retrieves before retaining. The live factory must first reopen the exact retained reference, with authoritative run linkage/disposition in Neo4j. Test interruption after bytes are retained but before generation release, changed corpus, revoked prior-read authority, and missing/tampered bytes: valid continuation uses the original context with no second retrieval; missing or ambiguous prior linkage blocks. Preserve current read authorization and no cross-store atomicity claim.

Expose the already modeled candidate→assessment→evidence and generation→prior detail through bounded typed queries, plus an authenticated exact artifact-byte retrieval contract. Reuse service/artifact validation, scope and historical ownership checks; no public filesystem paths or arbitrary Cypher. Enforce whole-response and per-artifact ceilings, including encoded expansion, and reject tampered/cross-scope access. Host-side artifact inspection is corroboration, not a substitute for fresh-client access. Keep command receipts, available actions and capability reporting honest about still-unsupported resume branches; either complete initial-no-reservation/validation-to-first-scene continuation or prove explicit truthful blockers before live use.

Exit: installed second-client submission→owned synthetic execution→durable result→fresh-client readback passes with egress denied and disposable Neo4j, plus active keyed cancellation/recovery and no-SQLite selected-path positives. Existing query-only regressions stay green. Parser-generated help and exercised commands become the only runbook syntax.

### P2 — Finish concrete native/policy composition (isolated, then dedicated native rehearsal)

Implement the owned policy child around `run_managed_policy`, actual runtime/task binding verification, existing GR00T policy adapter and retained episode decoder. Register before release; no initialization/inference/reset before its exact authorization. Preserve original deadlines and campaign step/episode accounting, including per-reset prerequisite work. Retain reports before process-terminating Kit shutdown and require genuine child success/verified cleanup for adoption.

Resolve G04-05 explicitly: capture and policy are separate registered workers, so policy construction cannot borrow earlier state-dependent evidence merely by candidate/seed. Freeze which prerequisites need fresh numeric or visual evidence on each reset. If a visual obligation needs slow VLM reapproval of the new cohort, design and test an explicit bounded pause/retained-state/revalidation protocol before claiming support; keeping a GPU lease across the call or restarting into an unmeasured scene is not an acceptable shortcut. Limit the first supported profile if necessary and report the narrower capability.

Provide a preparation seam for an **already-reset** cohort: `initialize_and_settle` currently calls `env.reset()` (`native_realization.py:217`), while the policy runner invokes its hook after reset/autoreset. Calling that helper unchanged would add a hidden reset. Preserve the legacy entrypoint while reusing hold/settle mechanics without resetting twice; test initial entry, autoreset, termination during preparation and the actual recorder's reset/index order.

Exercise receipt corruption, EOF/nonzero child, failed Kit close, cancel before/after release, monotonic deadline across blocking inference, parent death and recovery. Use existing isolated harnesses; any necessary native-capable test profile is an explicit reviewed addition, never a widened synthetic admission check. Native failure-injection jobs use a dedicated owned child and disposable/inert DB/provider dependencies. Do not crash shared Neo4j or kill the shared GR00T server.

Exit to P3: actual policy worker composition is source/isolated-tested, all required ports are concrete, no arbitrary callback claims attest runtime pins, and dedicated native-lifecycle rehearsal has separately authorized evidence. The selected A2 per-reset prerequisite strategy must be named and pass an isolated positive witness before P3; P3 owns its separately approved native witness before P4/P5 production workload release. A strategy that requires fresh cloud visual assessment needs its own explicit model-role/call/cost suballocation during calibration; P3's exclusion of cloud generation/refinement is not assessment permission. If no strategy establishes the declared obligations while preserving cleanup-gated GPU release, required-policy live release remains blocked rather than silently weakening those obligations.

### P3 — Bounded fixed-candidate native and policy calibration

After the calibration approval packet, use the exact A2 asset/task profile but no cloud generation/refinement. This is diagnostic calibration, not V1/V2 delivery. Run cheap existing geometry/reach/camera checks before expensive rollouts; consult authorized exact historical priors/diagnostics before repeating known failures. Diagnostics inform selection, not fabricated physical success.

Native calibration must record:
- graph subject→effective instance/prim→solver pose→reset/settled measured pose, environment origin and quaternion convention; placement-validator verdict including fallback/nonconvergence;
- actual action term ordering/scales/offsets/gripper semantics and measured posture preservation; strict unrounded `||v|| < 10^-3 m/s` for every required subject through the frozen consecutive window, with declared angular bound and every settle step charged;
- actual camera enablement/observation keys, timestamps/step offsets, RGB freshness and view alignment; evaluator encoding/resizing/byte ceilings separately from unmodified policy images;
- physical filter/source/endpoints, real nonzero contact vectors and absent-contact negatives; supported numeric predicate thresholds, proximity limitations and independent video inspection;
- no hidden reset between settle and capture; every policy reset separately prepared, termination/truncation detected before post-autoreset state is mislabelled, terminal image absence explicitly retained;
- successful normal teardown, common-lease release and native process/device cleanup while leaving unrelated services untouched.

These are not all existing receipt fields. Add bounded versioned provenance where necessary: `relation_solver_interface.py:98–109` currently warns about best-loss layouts that failed strict validation, and native capture does not yet retain a selected-layout validator receipt. Preserve the selected reset layout and verdict before logs are suppressed; include a no-effect/relation-overridden edit as a negative repair witness. Current spawnable-object mapping and center-proximity support do not certify arbitrary tabletop/background subassets. Resolve the actual A2 table/plate/banana sensor paths; unsupported mapping needs a tested evaluator/mapping revision, not removed assertions. Retain actual observed camera pose/calibration/resolution and timestamp correspondence, not only requested camera names.

Use real GR00T readiness on the actual served instance: pinned checkpoint/processor/statistics/embodiment/config/module identities, native serializer/modalities and bounded synthetic-array echo. Metadata readiness is not inference. Only after separate policy-effect approval perform bounded real inference and check action shape/order/finiteness/horizon; recheck instance identity at receiving action/reset dispatch and before buffered action release. Do not replace an expected identity with whatever a reconnect returns. Record remote-policy randomness and reset/seeding limitations.

Managed policy admission must require independent expected-server pins even though the legacy remote-policy path permits them to be absent. The runtime attestor observes actual objects/settings; it must not echo the requested binding. Extend provenance beyond model-directory hashes to the loaded SDK/Eagle configuration/module dependencies, policy joint mapping and preprocessing, because `isaaclab_arena_gr00t/policy/serving_metadata.py` explicitly limits its model-directory attestation. Retain exact locally resolved artifacts without downloading replacements during readiness.

Freeze tolerances and acceptance predicates before each calibration experiment. If settings must change, retain the rejected result and produce a new versioned profile/contract; never reinterpret earlier evidence under new thresholds. No physics/gravity/friction/task/asset change to force a green result. Exit: supported native adapter and actual policy runtime are calibrated within the declared scope, or a precise blocker with zero subsequent paid generation.

### P4 — First complete live scene workflow (Plan 03 V1)

After production read/write/provider/native approval and P0–P3 gates, submit once through the installed GraphQL client. Use the exact catalogue prompt, frozen retrieval policy and generation/assessment profiles. The application, not the operator, drives all stage transitions. Capture/cleanup/GPU release precede model assessment; retained assessment must not rerender. Numeric-only branches must not create idle model workers.

Retain all generated candidates and failed attempts. For an allowed visibility failure with physical prerequisites established, actual refiner receives original/current candidate, exact failing evidence and allowed original-centered XY envelope. Validate the full returned candidate and solver-effective displacement; fresh capture/reassessment is mandatory. No Z/task/physics/topology edit or invented physical diagnosis. If the chosen candidate passes without repair, run one separately budgeted controlled visibility-repair witness under the same application composition; label it controlled, not spontaneous generation evidence. A naturally unrepairable result stops honestly.

Fresh client queries the complete causal chain and artifacts after the submitting client disconnects. Lost ACK replay uses the same operation identity and makes no duplicate provider/native calls. A supported normal workflow stop is an integration observation, not a positive scene gate; at least one valid generated scene and the supported repair witness are required for V1 closure.

### P5 — Required-policy A2 pilot through the same API (Plan 03 V2)

Reference instruction: **“Grasp the yellow banana from the right side of the table and set it onto the white ceramic plate on the left.”** Bind `banana_ycb_robolab`, `plate_large_vomp_robolab`, `droid_abs_joint_pos`, the selected table/runtime and exact policy identity. Preserve the catalogue instruction rather than the paraphrase in the notes.

Pin the actual PickAndPlace task/evaluator and its lift-before-place, airborne dwell, destination contact/velocity/proximity sequence. Height peak, XY proximity, a VLM verdict or termination alone is not this task's success. Operational task acceptance is not independent grasp certification.

Use one fixed immutable generated candidate/profile/policy with **one completed episode on each of two predeclared distinct simulation seeds**, retaining all attempted/stopped/incomplete episodes. Freeze a seed schedule and exact way the current adapter represents it before launch. If bindings support only one seed per run, use two explicitly linked run IDs, one per seed; do not invent a single-run multi-seed capability or count repeated resets as independent seeds. Candidate reuse must be an explicit supported command/admission path with original generation provenance, not a manual DB insertion. At least one joined submission must include generation→scene→policy, not just evaluation of a hand-fed YAML.

Budget initial prerequisite work, every policy step, subsequent reset preparation, episodes, policy-server calls and all cleanup. Scene acceptance is nonterminal for these requests. Failed/unknown/incomplete policy results must preserve scene facts but never leave the run accepted. Empty episode files mean unknown denominator. Report raw successes/completed episodes, unknown/stopped counts and seed-specific outcomes; no cherry-picking, dropping failed seeds or automatic reroll. Two successful seeds establish a narrow pilot, not robustness or method efficacy.

Exit for positive A2 pilot: both predeclared seed obligations pass the frozen operational task predicates, episode bytes/video agree, exact served-instance/task/candidate pins remain valid, budgets/cleanup hold and fresh-client queries reconstruct the results. If either seed fails, close the attempt as failed/partial, diagnose from retained evidence, and obtain a separately versioned/approved next experiment rather than relaxing this one.

### P6 — Independent readback, reconciliation and handoff

Use existing exact retained queries and proof readers, not new graph labels or a parallel lifecycle ledger. Another authenticated client reconstructs the original command, frozen request, exact prior bytes, candidate lineage, capture/reset/window/measurement/frame identities, assessment, repair permission/decision, policy trial/episode accounting and cleanup disposition. Validate artifact bytes against their manifests from the allowed root; distinguish intended producer target from observed-state attribution.

Verify production writes only within the approved role/scope contract and retain administrator evidence appropriate to the concurrency limits. Verify owned processes/leases and exact trial-created resources, plus shared-service state preservation. Read access/replay must survive loss of execution grants; uncertain released work remains blocked and never silently redispatched. Controlled fault recovery belongs to rehearsal, not destructive tests on production.

Deliver a bounded report with separate implemented / isolated-tested / live-verified / deployed statuses, failed attempts, residual risks and exact evidence URLs/paths. Update the canonical handoff, not every historical paragraph. Recommend frontend work only after the required joined V1/V2 evidence is complete; any accepted exception needs an explicit user decision and must remain visible.

## 6. Acceptance matrix

Each row names new verification obligations, not tests already performed. Track executable test names, final source digest, evidence path and pass/fail/blocked/unrun in the review/handoff record. No row may be discharged by a different evidence level.

| ID | Obligation and positive/negative witness | Environment | Upstream coverage |
| --- | --- | --- | --- |
| A04-01 | Current-source traceability and all selected runtime imports; Neo4j-only positive route, forbidden SQLite/ambient effects rejected | Static + admitted isolation | T01/T13/T20, G01–G10 |
| A04-02 | Installed GraphQL submit/receipt/status from second client; query-only mode unchanged; wrong principal/scope/payload rejects | Disposable DB, denied external egress | T02/T09/T16/T21, G01/G02/G03 |
| A04-03 | Active keyed cancel, client disconnect, lost ACK replay, restart/reapproval and known-unreleased resume; uncertain release is not retried | Owned isolated processes + disposable DB | T04/T10/T11/T15, G01/G10 |
| A04-04 | Frozen retrieval source/eligibility/empty policy; full-outcome readiness blocks before constructor ping; nonempty bytes consumed; interrupted continuation reopens original bytes without retrieval despite changed corpus/credentials | Isolated, then approved bounded live read | T03/T05/T13/T17, G02/G04 |
| A04-05 | Private sentinel transport/error/log screening; no secrets in argv/public files/DB/artifacts; stale/revoked grants block new release | Isolated; runtime masked checks only | T03/T09/T21 |
| A04-06 | Exact production DB/schema/role/scope, recoverable backup and restore evidence, reviewed DDL/ONLINE indexes, scoped noninterference | Admin-approved metadata/read/write windows | T13/T15/T17 |
| A04-07 | Native source/object/pose/contact mapping, posture hold, strict settle equality/failure cases, camera/default/override and real arrays | Dedicated approved native calibration | T06/T14 |
| A04-08 | Same capture cohort and absolute windows; new policy reset remeasures prerequisites; terminal/autoreset pixels not confused | Isolated + dedicated native | T06/T08/T14 |
| A04-09 | Real child normal/failure/timeout/cancel/parent-death cleanup; common GPU release before slow VLM; persistent GR00T memory accounted | Dedicated owned-child rehearsal, then observed live | T09/T14/T15 |
| A04-10 | Pinned real policy/serializer/modalities; peer replacement fails before effect/release; actual action interface and episode decoder match | Isolated adversarial + approved GR00T calibration | T08/T19 |
| A04-11 | One installed submission drives generation→native→numeric/visual assessment; fresh client gets exact result; actual role transport/cost bound | Approved live V1 | T03/T05/T06/T18 |
| A04-12 | Actual permitted visibility repair→effective XY change→fresh capture→reassessment; forbidden changes reject | Isolated negatives + approved controlled live witness | T07/T14/T18 |
| A04-13 | Unknown-generated-digest→durably bound policy positive; nonterminal scene→owned policy; provenance-preserving second-seed reuse with new ownership/fresh evidence; complete task predicates on both seeds; failures remain nonaccepted | Isolated joining + approved live V2 | T08/T18/T19, G09 |
| A04-14 | Exact command→event cause→candidate/evidence→decision→trial GraphQL traversal, typed prior/detail and authenticated bounded artifact bytes after disconnect/restart; tamper/cross-scope rejection | Disposable tests + fresh live reader | T10/T12/T15/T16, G03–G10 |
| A04-15 | Fixed cross-run suballocations sum within campaign ceilings; exact-operation grants reject extra/mismatched/restarted duplicate spending; per-run monetary/call/token/step/episode/time bounds include preparation/retries/uncertainty; no refund | Isolated multi-run/restart exhaustion + observed live ledger | T03/T08/T14/T15 |
| A04-16 | Final owned cleanup and shared service preservation; original/failed evidence retained; publication remains absent without grant | All effectful phases, final exact readback | T09/T11/T15/T18 |

Mandatory review cross-checks: maximum writer-admitted payload remains readable; retained history pins the exact producing intent/fence; scene disposition survives all policy failure/budget/cancel branches; per-run evidence never inherits another owner's cleanup; numeric settings are executable frozen bytes rather than labels; general task semantics remain outside core coordinator/GraphQL branches.

## 7. Evidence and operator deliverables

Reuse the existing artifact/receipt store. Proposed campaign root `outputs/workflow/plan04-live/<campaign-id>/` is an evidence bundle, not a new authority database; actual durable artifacts belong on the approved mounted evaluation volume and public reports may reference them. Do not put private roots, credentials, raw auth headers or unrelated DB contents into distributable bundles.

Required bundle contents:
- approval reference and secret-free frozen campaign specification, explicit seed schedule and all ceilings;
- source/dependency/image/profile/task/policy digests, deployment mapping and observed readiness times;
- exact operation/run/intent/registration/decision/trial IDs and canonical query responses, with database and scope binding;
- prior consumed-byte manifest, candidates/repair lineage, solver and measurement evidence, calibrated settings/version, frame transforms and reset-relative timestamps;
- raw bounded episode JSONL, task predicates/progress, policy pin/transport receipts, video/frame manifest and counts;
- reservation/usage/latency/resource observations; diagnostics for every failed/unknown/aborted attempt;
- cleanup/reconciliation and backup/restore references, schema/admin readback and selected noninterference evidence;
- final acceptance matrix and limitations, distinguishing actual observation from interpretation.

Create the eventual operator runbook from exercised installed commands: no-effect inspection → approved metadata readiness → explicit launch → submit with fixed operation ID → observe from another client → exact cancel/reconcile controls → retained readback → owned shutdown. Every command is labelled by where it executes, under which account, which effects it can cause and its expected exit/result semantics. No speculative executable `run` command is supplied in this plan while installed execution is absent.

## 8. Stop conditions and response

Stop new releases immediately for wrong source/profile/instance/database binding; missing backup/approval; unexpected asset/network/model fallback; possible credential disclosure; unavailable required prior; lease contention or unknown cleanup; nonfinite/mismapped native data; ineffective placement repair; unsupported reset prerequisite; budget/deadline breach; inconsistent episode/video/result; or ambiguous commit/remote effect.

Cancel only the exact owned child/job through existing control boundaries. Preserve diagnostics and unfinished/unknown outcomes. Do not retry until exact reconciliation proves the next effect is known-unreleased and fresh authority permits it. Do not kill shared services to clear a blocker. A task failure with intact orchestration is valuable evidence but is not a positive pilot. A safe stop is successful safety behavior, not permission to mark the entire plan complete.

Before restoring earlier application code, verify it can read the codecs/schema already written by the pilot. Code rollback is separately approved and cannot silently downgrade retained records or trigger a whole-production-DB restore. Production outage/corruption/permission-denial injection remains prohibited; rehearse it on disposable targets.

## 9. Completion and scope discipline

Plan 04 is complete only when the approved acceptance rows have source-bound evidence, V1 is joined through the installed API, V2 meets the fixed A2 pilot obligations, fresh-client causal readback and owned cleanup pass, and independent review identifies no unresolved blocking contradiction within the declared scope. Otherwise report the exact blocked rows and preserve the usable partial deliverables.

Do not declare M0–M5 or V0–V2 complete merely because this plan lists their names. Do not restart the architectural debate or repeat completed extractions without a new source-backed counterexample. Make the smallest missing connections, verify them under isolation, then spend live GPU/provider/database resources only on the evidence that isolation cannot supply.
