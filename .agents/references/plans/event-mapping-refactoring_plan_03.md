# Event Mapping Refactoring Plan 03: Bottom-Up Application Refactoring for GraphQL and Live Generation

**Document Identity**: `.agents/references/plans/event-mapping-refactoring_plan_03.md`
**Status**: Design proposal for live integration; not implementation or live-execution authorization.
**Provenance**: Initial local draft attributed to Antigravity; source-grounded continuation and review recorded in the companion review ledger.
**Date**: 2026-09-19
**Upstream Dependencies**:
- [Event Mapping Refactoring Plan 01](event-mapping-refactoring_plan_01.md) (Architectural Foundation & Neo4j Store)
- [Event Mapping Refactoring Plan 02](event-mapping-refactoring_plan_02.md) (Core Application-Owned State Machine & Process Fencing)
- **Source baseline**: `3440d6352dc90ba2b2451bb29f29f8f0bd165af9`, branch `dev/0.3.0-prerelease`.
- **Implementation-status owner**: [current handoff](dashboard_cli_workflow_parity/research-stack-implementation-handoff.md). This plan defines proposed work, not a second completion history.
- **Review**: [plan 03 review ledger](event-mapping-refactoring_plan_03-review.md). Source anchors refer to the baseline above.

---

## 1. Executive Summary & Problem Definition

### 1.1 Context and Why Plan 03 is Required
Plan 02 closed its **guarded isolated workflow milestone**, joining actual generation/model entrypoints, synthetic HTTP/capture, owned workers, Neo4j decisions and fresh CLI processes. Its five bounded review findings were closed within that scope; this document does not re-run or broaden that proof. Current managed workflow authority is Neo4j. Legacy workbench jobs, model catalogues and SSE still use SQLite Journal; SQLite was **not retired**. That is a current-code gap, not an allowed target architecture: the refactored application must use Neo4j exclusively for durable domain/application records. See plan 02's status and the handoff's final bounded correction gate.

However, **Plan 02 intentionally kept native simulation and live inference isolated behind synthetic test fixtures.**
Consequently:
1. **No Live Developer Entrypoint**: A new developer cannot simply run `arena-workflow run --prompt "..."` with their `OPENROUTER_API_KEY` or `OPENAI_API_KEY` and get a real environment.
2. **Missing Live Graph-RAG Retrieval**: The Neo4j store stores workflow events, but live prior retrieval from existing accepted environment graphs remains disconnected at the application boundary.
3. **No Native `SimulationApp` Stage Realization**: Realizing the generated YAML into a live USD stage with PhysX settling and multi-camera trajectory capture is still tied to legacy standalone runner scripts (`environment_generation_runner.py`).
4. **No Real Policy Rollout Assessment**: Autonomous verification against manipulation policies (e.g., Franka + DROID or G1) remains unintegrated in the live execution loop.

**Goal:** transfer coordination of the researched workflow from an external orchestrator such as Hermes into Arena: submit → retrieve exact priors → generate → validate → realize/capture → assess → permitted repair → fresh evidence → accept or explain the stop. Reuse the engines already exercised; do not create another orchestrator. The coherent model is research entities → identity/owner/lifecycle → retained facts and available actions → shared application commands/read models → GraphQL. A dashboard is a later consumer, outside the current refactoring scope.

**Scope correction from the user:** refactor the codebase bottom-up for GraphQL; do not make the current dashboard a design constraint or delivery dependency. Establish the domain/application model, persistence, engine adapters and command/query contracts that GraphQL will expose. The CLI is an executable consumer and verification surface of that same application, not a separate architecture or the reason to postpone GraphQL contract design. Dashboard routes, SQLite SSE compatibility, frontend integration and browser parity are outside this plan's current scope.

A2 remains the first proposed native/policy pilot, not proof that every embodiment works. Scene acceptance, policy success, publication and successful-prior eligibility remain distinct. Writing this plan authorizes no inference, GPU use, service startup, research-database access, dependency installation or protected deployment-file changes. Deferring dashboard work does not authorize deleting unrelated legacy code or data.

---

## 2. Architecture and invariant guardrails

### Mandatory persistence boundary: Neo4j, no SQLite

Neo4j is the sole authoritative database for the refactored application and its GraphQL/CLI interfaces: domain entities and revisions, accepted requests, workflow/attempt state, decisions, reservations, command receipts, events, persisted public profiles/catalogues and publication/evaluation metadata. No SQLite Journal, parallel job store, dual writes, SQLite cache or SQLite fallback is permitted in this application. Neo4j unavailability produces an explicit unavailable/unknown outcome, never a switch to local database state.

Immutable files remain the evidence/blob store, with identities/manifests and authoritative relationships recorded in Neo4j; they are not a second lifecycle database. Private credentials remain in the authorized private channel/in-memory grant boundary, not either database. Static configuration files may supply explicit configuration but cannot become a competing mutable application registry.

Any existing functionality selected for reuse that depends on Journal/SQLite must be extracted and reimplemented against the Neo4j persistence contracts before it enters the refactored application. This migration is required backend work, not deferred until dashboard integration. Preserve existing data for an explicit, verified import if required; do not delete or read private legacy databases during this planning task. No compatibility adapter may hide SQLite behind an otherwise Neo4j-facing GraphQL resolver.

```text
Domain/application contracts designed for GraphQL; CLI as an executable consumer
    → shared application facade (extracted ForegroundWorkflow + WorkflowService)
    → Neo4j admission / decisions / reservations / released intents
    → existing owned workers and private effect authority
        → GraphRAGRetriever → immutable prior receipt
        → EnvironmentGenerationAgent / BoundedSceneModels
        → ArenaEnvGraphSpec → ArenaEnvBuilder → native capture/measurements
        → existing policy_runner, when policy criteria are required
    → immutable artifacts + validated receipt adoption
    → explicit application decision: observe / repair / accept / stop / reconcile

Publication is a separate authorized command, never an acceptance side effect.
```

- Keep reusable application composition under `isaaclab_arena/agentic_environment_generation/`, with examples/HTTP/CLI as thin adapters. Domain imports must not import examples, FastAPI, SDK/native runtimes or resolve credentials.
- Preserve `WorkflowService`, `GenerationCoordinator`, `scene_loop`, Neo4j fences, immutable artifacts and physical ownership. A facade delegates; it does not introduce another job store or controller.
- Resolve secrets only at a trusted execution boundary. Configuration validation, profile listing and read/replay must not construct model backends or ping providers. Existing constructor pings remain charged effects after release; removing them globally is not required for this integration.
- Derive readiness from the **whole requested outcome**, including assessment, capture and policy where required, before the first model call. Missing required dependencies, unavailable required priors or unsupported criteria cause zero model calls, including initialization pings.
- Retain every candidate, failed assessment and decision diagnostically. Eligibility for retrieved successful priors requires existing publication/evaluation validation; do not invent replacement `AcceptedEnvironmentGraph` labels.
- Run native initialization/imports inside an owned runtime worker after authorization and resource acquisition. Official Isaac Sim documentation requires Kit initialization before dependent Omniverse imports.[14] Treat cleanup/ownership as verified receipts, not an assumption about process exit.
- A visual verdict cannot satisfy physical support, collision, causal diagnosis or policy-success requirements. Profile-specific measurements, frames, tolerances and windows must be frozen before release; missing measurement capability is unsupported, not a pass.
- Commit decision, cumulative reservation and next intent together. No refund or retry merely because remote effects are unknown. Current authenticated reads and exact replay remain possible without fresh execution grants.

---

## 3. Detailed Work Breakdown & Phased Execution

### Phase 1: Supported launch configuration and live model composition
**Target Files**:
- `isaaclab_arena/agentic_environment_generation/inference_backend.py`
- `isaaclab_arena/agentic_environment_generation/workflow/inference_transport.py`
- `isaaclab_arena/agentic_environment_generation/inference_profiles.py`

#### Changes:
1. Extract the shared foreground composition and add an explicit installed profile, leaving `isolated-synthetic-v1` and its guards unchanged. Current `application_from_cli` is harness-only (`foreground_workflow.py:44`); it is not a production launcher.
2. Reuse `inference_profiles.py:29–175`, `BoundedSceneModels`, `ForegroundAuthority` and `ExecutionGrants`. Freeze role-specific literal endpoint/model/request policy and accounting metadata. The current built-in resolver only recognizes its enumerated OpenAI pairs; fixed endpoint support or a user-defined profile is not compatibility verification for every model.
3. Give a new operator a secret-free profile template, validation output, explicit credential source and exact run/status/cancel/resume walkthrough (§6). No secret-valued `--api-key` argv, automatic `.env` loading or hidden provider fallback. An opt-in launcher may read a **named environment variable** and pass its value privately; explain environment exposure and strip it from unrelated descendants. Prefer the existing private-pipe mechanism. This is a deliberate future ergonomic addition, not present behavior.
4. Metadata readiness and effect authorization stay separate. Initialize model clients only in released bounded workers with a shared allowance installed first. Constructor pings, SDK retries, image calls and failures consume the original cumulative call/token/cost/time ceilings. SDK defaults can retry; actual managed transport must be tested rather than relying on those defaults.[26]
5. Support one explicitly verified generation/assessment profile pair first. For OpenRouter, freeze routing, fallback and parameter requirements as part of the profile: provider fallback is enabled by default in its documentation, so identity/cost assumptions must not rely on an omitted field.[18] Add serialization and capability tests before advertising more pairs.
6. Reserve conservative attested bounds before every effect; explicit zero pricing is distinct from missing pricing. Provider model metadata can contain pricing overrides, so a single headline price is not a complete conservative bound.[8] Retain reservations separately from measured usage/billing.

Provider binding must be explicit, not inferred from model-name substrings or whichever key exists first. `inference_backend.py:224–245` can choose an OpenAI key for an OpenRouter model when both are present; pass the selected key/model/endpoint explicitly with dotenv disabled. Legacy NVIDIA uses `NV_API_KEY`; retain that as the documented named source, treating any proposed `NVIDIA_API_KEY` alias as opt-in with conflicting values rejected. Reuse/extract `web_api/provider_security.py` and `provider_readiness.py`; current metadata readiness is not universal provider support. Test mixed-key environments, literal model preservation, slow/error responses and total probe deadlines. Do not promise a new `validate_connection()` API or a two-second bound without implementing transport and overall deadline enforcement.

---

### Phase 2: Live Read-Only Graph-RAG Prior Retrieval from Neo4j
**Target Files**:
- `isaaclab_arena/agentic_environment_generation/workflow/prior_artifacts.py`
- `isaaclab_arena/agentic_environment_generation/graph_rag.py`
- `isaaclab_arena/agentic_environment_generation/workbench/research_retrieval.py`
- `isaaclab_arena/agentic_environment_generation/workflow/neo4j_store.py`

#### Changes:
1. Reuse `GraphRAGRetriever.retrieve_prior_snapshot` (`graph_rag.py:387`) with an explicitly authorized injected driver/database and, when selected, the existing managed publication/evaluation-readback callback. Do not introduce a second retrieval schema or bypass the current provenance validators with a keyword-only query.
2. Separate operational Neo4j write authority from research-prior read authority, even when endpoints share infrastructure. Use fixed reviewed queries, explicit database, least-privilege credentials, query/connection/overall deadlines, row/byte bounds and verified resource cleanup. READ routing alone is not a database security boundary. Do not call inference/publication inside a retried transaction callback; managed Neo4j transactions may re-run callbacks.[10]
3. Retain and verify the exact snapshot under prompt, contract digest and run before backend construction. Generation consumes `exact_context` once; refinement does not silently retrieve a newer corpus. Retain selection/version/evaluation counts and uncertainty, not merely graph names.
4. Distinguish `not_requested`, successful retrieval with no eligible priors, and unavailable/invalid retrieval. Required unavailable priors block with zero model calls. Optional fallback must be explicitly permitted and labelled; a bundled exemplar must never masquerade as a measured retrieved prior. Define whether an empty successful retrieval is acceptable in the selected retrieval profile before release.
5. Managed publication membership and evaluation evidence are not automatically one immutable database snapshot (`research_retrieval.py:14`). Retain validated consumed bytes and report that limitation; do not claim a stronger corpus snapshot guarantee.

---

### Phase 3: Native Isaac Sim Realization & Physics Settling
**Target Files**:
- `isaaclab_arena/agentic_environment_generation/workflow/native_realization.py` (proposed adapter, not a replacement engine)
- `isaaclab_arena/agentic_environment_generation/workflow/scene_engines.py`
- `isaaclab_arena_examples/agentic_environment_generation/web_api/generation_worker.py`

#### Changes:
1. Extract only reusable construction from `environment_generation_runner.py:660`: `ArenaEnvGraphSpec` → `to_arena_env()` → `ArenaEnvBuilder.make_registered()`. Use typed builder/runtime configuration rather than `argparse.Namespace`; leave CLI parsing, printing and the legacy best-effort critic outside the new adapter. Reuse existing builder and relation solver. Access Isaac Lab state through `env.unwrapped`.
2. Add a separately admitted native capture worker/profile beside the existing synthetic composition. Reuse owned prepare/register/release/cleanup and immutable receipts. Do not simply remove `synthetic_only` checks or run native callbacks in the coordinator. Acquire the common GPU lease; pausing a legacy queue is insufficient if a warm renderer still owns it.
3. Reuse `trajectory_capture.capture_trajectory` and `scene_observation.make_native_sampler`; verify actual tensors, coordinate/quaternion conventions, origin offsets, prim identity and filtered contact correspondence. The current sampler requires one environment, literal contact paths and force shape `(1, 1, 1, 3)` (`scene_observation.py:368–471`); ordinary templated paths and broader tables need a tested adapter/evaluator revision, not assertion removal.
4. Freeze bounded settle/capture windows, actual cameras/modalities and calibrated thresholds in an immutable profile. Current support constants are `0.01 m/s`, `0.05 rad/s` and `0.05 m` XY distance (`scene_observation.py:31`), not established universal acceptance limits. Its center-distance rule is not generic tabletop support. Do not substitute guessed 40-step settling, invented camera names, penetration measurements or unsupported depth channels.
5. Retain authored → solver-effective → realized pose mapping, placement-validator disposition and reset/realization identity. Relation-controlled non-anchor `initial_pose` edits may have no effect. Permit only supported effective XY repairs from the original baseline; fixed-Z repairs cannot fix support/Z or embodiment errors.
6. Record synchronized images and raw measurements through `SceneEvidenceArtifacts`/`ArtifactArea`, binding candidate/profile/seed/reset/window/step and camera calibration. Capture terminal state before autoreset or mark terminal images unavailable. A later rollout is not evidence of the failed episode.
7. Every repair receives fresh relevant native evidence from a compatible complete cohort. Retain partial capture before cleanup and preserve the failing process exit code; successful cleanup is not acceptance and retained images are not contact proof.

#### Native integration details that must not be hidden by adapter reuse

- **Hold actions:** `DroidAbsoluteJointPositionActionsCfg` (`isaaclab_arena/embodiments/droid/droid.py:347`) sets `use_default_offset=False`. Zero arm commands are not a posture hold. Reuse the runner seam but add an explicit embodiment-correct hold implementation using the selected action terms/joint ordering and measured/reset posture; preserve gripper semantics. `evaluation/policy_runner.py:104–114` currently returns zeros for non-WBC embodiments, so the existing helper is not sufficient for DROID. Native calibration must demonstrate posture retention before interpreting object motion.
- **Blocking settle gate:** `verify_and_settle_scene` currently permits at least 50 steps and returns an `all_objects_settled` report; `rollout_policy` discards that report (`policy_runner.py:160,247,469–477`). The managed path must enforce its frozen maximum, charge every settling step and reject unsettled/terminated/truncated cohorts before policy effects. Preserve legacy behavior unless a separately tested common fix is selected. Do not round a measured value before evaluating its threshold.
- **One reset sequence:** both `trajectory_capture.py:35` and `evaluation/policy_runner.py:466` reset unconditionally. Provide a tested capture/runner hook for an already initialized reset cohort or place hold/settling inside the owned reset lifecycle. Sequence is reset → embodiment-correct hold/settle → exact observation window → policy rollout when requested, with no hidden reset between these steps. Preserve existing helper defaults for legacy callers. If a policy worker rebuilds/resets, it must re-establish state-dependent scene prerequisites for that episode; a matching spec/seed is insufficient. Success/termination records remain separate from unavailable terminal images.
- **Actual cameras and bounds:** DROID sensors are `external_camera`, `external_camera_2`, `wrist_camera` with RGB-only configuration (`droid.py:425–468`). The checked-in policy consumes `external_camera_rgb` and `wrist_camera_rgb` (`isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml:21`); verify the corresponding observation keys before selecting extra evaluator views. Preserve the policy's view/preprocessing contract. Existing scene retention allows 16 PNG frames, at most 128 KiB each, and exact camera-by-step coverage (`scene_observation.py:186–235`), whereas the generic capture helper has a separate 64-image ceiling. A short post-settle window must satisfy both and the whole payload bound. Predeclare evaluator image resizing/encoding and record the transform; do not silently resize policy input or drop frames. Broader windows/depth require a versioned bounded evidence extension, not an incidental guard relaxation.
- **Native provenance:** current producer payloads recognize `synthetic` and `native-unverified`, while foreground admission/profile assurance remains synthetic-only. Add explicit native producer/profile/receipt support and calibrated provenance through the service/read model. Changing a string is not native verification, and hashes prove integrity rather than measurement authenticity.

---

### Phase 4: Policy Rollout & Task Acceptance Gate (Scenario A2)
**Target Files**:
- `isaaclab_arena/agentic_environment_generation/workflow/policy_evaluation.py` (New)
- `isaaclab_arena/agentic_environment_generation/trajectory_assessment.py`
- `isaaclab_arena/agentic_environment_generation/trajectory_capture.py`

#### Changes:
1. Reuse `evaluation/policy_runner.py` and the trusted completion bridge in `web_api/evaluation_worker.py:24`, not a new rollout algorithm. Existing profiles include `gr00t-droid` and `openpi-droid`; generic OpenVLA support is not established. Separate shared runner logic from fixed legacy endpoint/1000-step assumptions.
2. Extend the application contract, reservation codecs/store, worker packet, evidence producers, decision rules and read model together for required policy outcomes. `read_model.py:159` currently reports `policy_outcome="not_run"`; scene admission is not a supported policy executor. Merely filling `execution.policy` or changing a display label is insufficient.
3. Freeze served checkpoint/config/processor/modality and native transport identity, task instruction, exact scene, episode/reset/seed, step/settle deadlines and aggregation before release. Verify GR00T's expected instance at the receiving effect boundary, not only a successful ping. A DROID label or client YAML path is not proof of the loaded policy.
4. Use the selected task's frozen lift/dwell and destination predicates. End-effector proximity, a height peak, XY-in-bounds or VLM approval alone cannot substitute for the complete operational success sequence. Preserve completed episode records and denominators; no completed episodes means unknown/not established, never success. `PickAndPlaceTask` defaults to `min_airborne_steps=1` (`pick_and_place_task.py:72–75`), so default success does **not** establish sustained multi-step lift or independently verified grasp. Freeze/report actual dwell, lift height and optional destination bounds; stronger sustained-lift criteria must be explicitly selected before release, never inferred from the default or altered after failure.
5. First manipulation slice evaluates the fixed scene after scene acceptance; policy failure remains a retained nonaccepted outcome. Automatic policy-diagnosis-driven repair/DCRG is a later explicit capability. No invented reachability diagnosis or VLM prose is converted directly into pose deltas. Existing DCRG retains its own research invariants and must eventually compose under the outer workflow budgets without competing authority.
6. Disable legacy graph synchronization and version-tree side effects explicitly for local-only evaluation. Research publication is separate; do not automatically promote the pilot into successful priors.

The initial policy contract targets `droid_abs_joint_pos`, the served `nvidia/GR00T-N1.6-DROID` family and `OXE_DROID`, with actual checkpoint/config/serializer/modality pins verified independently. This is source feasibility, not a claim that the model is installed or A2 succeeds. Use `PickAndPlaceTask`'s frozen `require_lift_before_place` sequence, airborne dwell and destination-contact/velocity/proximity predicates (`isaaclab_arena/tasks/pick_and_place_task.py:133–197`); do not describe those operational predicates as independent grasp certification. A manipulation request must remain nonterminal after scene acceptance: atomically retain the scene disposition and reserve the policy intent, then terminally accept only after policy obligations pass. Preserve scene-only terminal acceptance for scene-only requests. Stop/failure in the required policy phase must never leave overall workflow state `accepted`.

---

### Phase 5: Shared application contracts and GraphQL boundary
**Target Files**:
- `isaaclab_arena/agentic_environment_generation/workflow/facade.py` (New Core Module)
- `isaaclab_arena_examples/agentic_environment_generation/web_api/` (existing FastAPI backend)
- Proposed GraphQL schema/resolver modules in the backend adapter layer; no frontend targets.

#### Changes:
1. Define the application/GraphQL contract alongside M0, not after a dashboard integration milestone. Extract the existing foreground application root into core. Proposed facade methods are `submit`, `status`, `cancel`, `resume`, `profiles`, `snapshot`, `events`; internal `drive_admitted` belongs to the execution owner. Names are design targets, not implemented APIs.
2. Build GraphQL queries/mutations over those shared commands/read models; use CLI and direct application tests to exercise the same behavior. Define continuation, authorization renewal and execution ownership from the managed domain model, not by mapping old dashboard buttons or queue endpoints. Maintaining legacy routes, reproducing SQLite SSE or implementing REST parity is not an acceptance requirement here.
3. Authenticate at the boundary and authorize through shared application rules. GraphQL's official guidance places authorization in business logic, avoiding inconsistent resolver-only checks.[16] Scope nested artifact/evidence/profile access as well as top-level operations.
4. Deliver backend entity identities, typed outcomes, available actions, durable query projections, command receipts and event/revision contracts that any future client can consume. Validate them without a dashboard. The schema sketch and backend recovery/security obligations are in §9; dashboard adaptation is a separate later task.

---

## 4. Verification Protocol & Acceptance Criteria

Verification progresses from pure/static boundaries to admitted isolated integration, then separately authorized native/live pilots. Preserve the plan-02 positive and zero-effect negative paths. §10 defines acceptance IDs and evidence; passing synthetic tests does not remove native limitations.

For A2, retain the original catalogue instruction: “Grasp the yellow banana from the right side of the table and set it onto the white ceramic plate on the left.” Pin `banana_ycb_robolab`, `plate_large_vomp_robolab`, `droid_abs_joint_pos` and the selected table/runtime identities from the [scenario catalogue](../agentic_env_generation/env_gen_test.md#-category-a-fresh-food--kitchen-tabletop-franka-droid--single-arm). Its historical geometry and ports are not current deployment facts.

Proposed pilot: one completed manipulation episode on each of two predeclared distinct simulation seeds, with the unchanged frozen operational PickAndPlace success sequence established for both before claiming pilot manipulation acceptance. This is not independent grasp certification. Record all stopped/failed/incomplete attempts and remote-policy randomness limitations. Freeze numerical horizons, thresholds and total budgets before launch; do not invent them in this plan or relax them after failure. Two successful seeds would not establish robustness, DCRG efficacy, causal diagnosis or prior eligibility.

---

## 5. Implementation Sequence & Milestones

| Milestone | Concrete deliverable / exit gate | Dependencies |
| :--- | :--- | :--- |
| M0: Domain/application foundation | Coherent identities, ownership, commands/queries and GraphQL contract sketch; Neo4j-only repository contracts and dependency inventory; no SQLite-backed runtime path | Approved implementation scope; existing researched workflow and engines |
| M1: Installed launch + model/prior wiring | Secret-free profiles, private credentials, full readiness, actual generation and exact retained live-prior adapter; isolated positive/zero-call proofs | M0; chosen supported role profiles |
| M2: Native scene loop | Owned native builder/capture/sampler; calibrated effective-placement and support evidence; application-owned repair/reassessment; usable CLI runbook | M1; separate native/live approval and declared resource scope |
| M3: Manipulation acceptance | Policy evidence/reservation/decision integration and A2 fixed-scene pilot, with honest failures and exact recovery | M2; pinned supported policy and separate policy-effect approval |
| M4: Durable backend query/command model | Execution owner independent of requests, typed result projections, bounded events/revisions, command lookup and recovery | M0; extend and verify per engine slice as M1–M3 are implemented, without frontend work |
| M5: GraphQL application adapter | Schema/resolvers over the same application; query/mutation, authorization and CLI/direct-call contract tests | M0/M4 contracts and selected API dependency; isolated adapter work need not wait for live native approval |

Milestone numbers group work, not a requirement to finish native pilots before designing GraphQL. Define contracts in M0 and implement/test the backend/GraphQL boundary incrementally against the same engine-backed application. Dashboard compatibility does not gate this work; removing SQLite dependencies from each reused backend capability is a mandatory gate for that capability, not optional legacy follow-up. No fixed-hour total is supported by the current native calibration, installation and policy unknowns. Assign file ownership per vertical slice; use red→green isolated tests, bounded independent review, then explicitly authorized live acceptance.

## 6. Operator journey and launch contract

### 6.1 Current versus proposed entry points

Current core `workflow.cli` implements **only `inspect-contract`** (`workflow/cli.py:41`). Execution is in `isaaclab_arena_examples.agentic_environment_generation.foreground_workflow_cli`, whose default factory is admitted only by the isolated harness. There is no established `arena-workflow` console command. Do not document speculative `--prompt`, `--provider` or `--eval-policy` flags as working now.

M0/M1 should retain the existing execution module as a compatibility entry point while delegating to core. The following is the **target installed-profile walkthrough**, not an executable live recipe today. `/private` paths are operator-selected examples; the implementation must deliver the templates and profile schema first.

```text
python -m isaaclab_arena_examples.agentic_environment_generation.foreground_workflow_cli run \
  --config /private/installed-profile.json --principal operator \
  --operation-id a2-pilot-001 --credentials-fd 3 /private/a2-contract.json
```

Command → application mapping: authenticate trusted local operator → normalize/freeze request → exact operation replay lookup → full required-role/profile/readiness/authority checks → durable admission and flushed run handle → bounded prior retention and generation → native scene loop → optional required policy phase → retained result. The launcher supplies descriptor 3 as the existing bounded owner-private pipe, not a secret file or shell argument. Preserve the exact admitted run ID.

```text
python -m isaaclab_arena_examples.agentic_environment_generation.foreground_workflow_cli status \
  --config /private/installed-profile.json --principal operator EXACT_RUN_ID
python -m isaaclab_arena_examples.agentic_environment_generation.foreground_workflow_cli cancel \
  --config /private/installed-profile.json --principal operator EXACT_RUN_ID
python -m isaaclab_arena_examples.agentic_environment_generation.foreground_workflow_cli resume \
  --config /private/installed-profile.json --principal operator EXACT_RUN_ID
```

Status → authenticated retained read only. Cancel → owner-local stop plus durable cancellation, separately reporting delivery/cleanup/unknown remote effects. Resume → exact reconciliation or known-unreleased continuation; fresh private authority is supplied only if required, without changing the frozen request. Same key + same contract returns the same admission even after a profile disappears; same key + changed contract conflicts. A different seed/model/intervention/budget requires a new contract/run, not authorization renewal.

### 6.2 Required onboarding deliverables

1. A secret-free installed-profile template binding deployment/workspace, operational DB, separate prior-read profile, artifact/lease roots, runtime/capture and generation/assessment/policy roles. Public profiles contain immutable revisions/digests and capabilities, never secrets or executable import paths.
2. A profile/contract compilation and validation command, designed in M1, that shows planned dependencies, exact selected request policies, budgets and unsupported criteria without probing/starting anything. Prompt/scenario convenience must compile to the same strict contract; it is not an alternative admission path.
3. A trusted local credential launcher with explicit private-pipe and optional named-environment-source modes, documented selection (an explicit pipe disables environment discovery; explicitly selecting both rejects), no automatic dotenv scan, no secret persistence, bounded static diagnostics and redaction tests. Current config parser rejects installed composition and the default factory rejects supplied credentials; adding a pipe flag alone does not make it supported.
4. A separately invoked bounded readiness check distinguishing configured, supported, observed-ready and execution-authorized. It must not infer simulation capability from a model ping or policy capability from metadata alone.
5. An installation/admin checklist: discover the clone's runtime/container, run native work non-root with `/isaac-sim/python.sh`, verify mounts/UID/GPU visibility/common lease, explicitly initialize new operational schema/artifact scope, configure read-only prior access and check pinned service identities. Runtime constructors never lazily migrate schema or initialize an unrelated store.
6. A fresh-operator walkthrough that produces an inspectable candidate, manifest, criterion/decision history and terminal result; a second process reads status and requests cancellation. Preserve JSONL admission-before-effects and current exit semantics (accepted 0, invalid 2, blocked/unknown 3, denied 4, failed 5, stopped 6, cancelled 7). Replace synthetic limitation labels only when supported by the new producer's actual receipts.

### 6.3 Paired public/private configuration example

This is a **proposed mapping example**, not a loadable current configuration or a claim of live model compatibility. M1 must deliver the matching versioned JSON templates and validators, extending both `foreground_workflow_cli._config` and the installed factory's validation together; the isolated factory stays unchanged.

| Role | Public profile / literal binding example | Explicit private source and worker mapping |
| --- | --- | --- |
| generation | Operator profile `generation-openai-example`, revision 1; provider `openai`, model `gpt-4.1`, endpoint `https://api.openai.com/v1`; checked frozen request policy and settings digest | Selected launcher source `env:OPENAI_API_KEY` or private-pipe slot `models.generation`; never ambient priority scanning. Resolve nonempty key only for authorized fresh execution, then explicitly set `api_key`, `model`, `base_url`, `inference_profile`, `workflow_accounting`, `load_dotenv=False` |
| assessment | Distinct profile `assessment-openai-example`, revision 1; same literal pair only if its required image/response capability is admitted | Private slot `models.assessment`, explicit source may be shared by operator choice; separate role scope/deadline/accounting despite equal key/model |
| operational DB | Named database/profile, deployment/workspace, public endpoint and immutable settings revision | Separate private slot `databases.operational`; grants operational lifecycle access, not research-prior/publication authority |
| prior read | Explicit database and reviewed retrieval/eligibility profile | Separate private slot `databases.prior_read`, read-authorized source only; no fallback to operational DB credentials |

The proposed pipe envelope has a schema version and enumerated role slots, not arbitrary imports/configuration overrides. Exact byte/type limits and redaction follow the existing private channel; secrets never contribute to public settings hashes. Public config freezes literal binding and profile digest, not the key. Pipe-source selection disables environment discovery. If environment mode is explicitly selected, other provider keys must not affect the mapping; `NV_API_KEY` remains the legacy NVIDIA source, not an implicit synonym for `NVIDIA_API_KEY`. On exact replay, perform current read authentication and lookup before resolving these execution-only slots. End-to-end template tests must traverse both parser and installed factory, not just validate a dictionary in isolation.

### 6.4 Startup and deployment boundaries

Default is observe-only readiness. `--allow-startup` cannot mean arbitrary Docker/shell access: use the existing scoped bootstrap/paired host-control protocol only after an installed helper and exact service allowlist are explicitly configured. Provisioning, model downloads and DB migration are separate administrative tasks. Changes under `docker/`, CI, pre-commit configuration or submodules require separate approval.

Start with one explicit execution owner per scope on the intended local deployment, not Kubernetes or a broker. For API-driven work, use a bounded background driver around the existing application; Neo4j intents are authoritative and wakeups are hints. Request completion/browser disconnect must not own worker lifetime. Do not enqueue managed workflows into the legacy SQLite Supervisor. FastAPI response-background work alone is not the durable ownership/recovery design.

Private grants currently live in process memory (`web_api/execution_grants.py`); a grant ID cannot transfer credentials to another process/container. Define owner-local credential resolution or explicit reapproval over a private authenticated channel. Verify common lease/socket/artifact mounts and effective UID/host/boot/process identity in the actual deployment. Existing same-UID Unix-socket stop is not arbitrary cross-host recovery. An unreachable owner or expired lease does not permit signaling foreign PIDs or redispatching uncertain effects.

## 7. Coherent event/domain model

These are logical responsibilities in one application, not new services or a demand for full event sourcing. Neo4j transactionally owns all durable domain/application records in the refactored backend; immutable files hold large evidence bytes. Existing SQLite data is legacy migration input only, never a runtime authority or fallback for this application. The proposed event names below are conceptual mappings; do not claim every name is an existing event enum.

| Entity / identity | Authority and retained facts | What survives refresh / user action |
| --- | --- | --- |
| Input source / revision | Explicit source bytes or immutable revision accepted by the application | Run binds frozen source identity, never an implicit mutable editor state; editor draft lifecycle is outside this scope |
| Request / operation ID / contract digest | Neo4j admission and canonical immutable contract | Same request can be looked up after lost acknowledgement; intentional new experiment gets a new operation ID |
| Workflow run / version | Neo4j current state, phase, decisions, budget and events | Status and allowed actions; version does not itself describe all owner-derived result changes |
| Execution intent / attempt / owner epoch | Neo4j reservation/release fence plus physical owner's independent locality/cleanup witness | Known pending work may continue; released unknown work must reconcile |
| Prior snapshot / context hash | Validated immutable artifact, bound to prompt/run/contract and authorized retrieval profile | Show exact consumed context/provenance and unavailable/empty distinction; no re-retrieval on refresh |
| Candidate / digest / parent / original baseline | Immutable source bytes + Neo4j selection/lineage | Inspect every candidate and repair delta, not only latest; raw and canonical digests remain distinct |
| Realization / reset / cohort / window | Owned runtime receipt and immutable native evidence | Distinguish authored scene from realized state; no stitching complementary passes across resets |
| Assessment / decision | Exact evidence selection, criterion/producer/model/rubric version, structured result and next action | Explain accept/repair/stop; unknown and advisory evidence never become required passes |
| Policy trial / episode | Frozen policy/task/scene/seeds, episode records and aggregation receipt | Display numerator and denominator, incomplete episodes, failures and actual provenance |
| Publication / prior eligibility | Existing explicit publication/readback and evaluation-eligibility contracts | Independent status; scene acceptance never silently publishes or qualifies a successful prior |

| Command | Retained fact / owner | Next action and failure boundary |
| --- | --- | --- |
| Submit | Request admitted, service/store | Announce stable run before execution; conflict/not-ready is not acceptance |
| Retrieve priors | Exact snapshot retained, authorized retrieval adapter | Required unavailable → block without model construction |
| Generate / validate | Candidate produced and validation disposition, existing engine + receiver | Application chooses native realization; no implicit agent auto-heal/publication fallback |
| Realize / observe / assess | Compatible cohort and criterion assessments, native producer + assessment adapters | Required pass → scene accepted; supported failure → permitted repair; unknown → bounded observation or stop |
| Repair | Child candidate and enforced cumulative delta, refiner + application guard | Fresh validation and evidence; no physical/task gate changes |
| Evaluate policy | Episode/aggregation receipt, existing policy runner + application | Overall acceptance only when all requested scene AND policy obligations pass |
| Cancel | Stop delivery, cancellation and cleanup are separate facts | Owner-local interruption must remain possible when DB access fails |
| Resume | Continuation/reconciliation disposition | Never renew authority or repeat remote effects on read-only replay |
| Publish | Exact target/readback/eligibility result | Separate authority and receipt; ambiguous write does not retry blindly |

Budget accounting spans all stages and restarts: model attempts including pings/retries, tokens/cost upper bounds, generation/repair candidates, realized scenes, settle/capture/policy steps, observations, episodes and wall deadlines. Retain the original deadline; resume never resets it. Unknown consumption is not zero. Producer failure and scientific rejection are separate from operational failure.

## 8. File-level reuse and extraction map

Prefixes: `core/` = `isaaclab_arena/agentic_environment_generation/`; `examples/` = `isaaclab_arena_examples/agentic_environment_generation/`. Proposed files are explicitly marked; the map is an implementation contract, not a claim they exist. Existing modules under `workbench/` or `web_api/` may contain reusable backend capabilities; their names do not imply frontend work or a requirement to preserve dashboard interfaces.

| Existing source / entry point | Proposed ownership / change | Compatibility and acceptance gate |
| --- | --- | --- |
| `examples/foreground_workflow.py:320` (`ForegroundWorkflow`), `:44` (harness factory) | Extract orchestration wiring to proposed `core/workflow/application.py` / `facade.py`; keep separate trusted isolated/installed composition factories | Same service/controller, not rewritten state machine; old import/CLI wrappers preserved; T01/T02 |
| `examples/foreground_authorization.py`, `foreground_owner.py`, `foreground_control.py`, `foreground_cancellation.py`, `foreground_recovery.py` | Move transport-neutral authority/owner interfaces and reusable local runtime adapters to core incrementally | Keep browser authentication/FastAPI dependencies in examples; preserve lock ordering, cancellation-before-DB and exact historical receipts; T04/T09 |
| `examples/foreground_initial_generation.py`, `foreground_scene.py`, `foreground_scene_ports.py`; `web_api/generation_worker.py` | Reuse actual worker protocol, SDK allowance and model callbacks; separate adapter imports from web-only bootstrap | Native capture is a new explicitly admitted worker action, not a synthetic-profile bypass; T03/T06 |
| `core/workflow/service.py`, `coordinator.py`, `scene_loop.py`, `neo4j_store.py` | Remain authoritative application decisions/transactional state; add policy-stage intents and command receipts only where missing | Current replay and reserved-before-effect behavior preserved; no second SQLite lifecycle; T02/T04/T08 |
| `core/inference_profiles.py`, `workflow/scene_engines.py`, `inference_transport.py`; `examples/foreground_authorization.py` | Narrow operator-configured profile registry + role-specific private resolution; reuse existing model engines | Registry description never grants authority or starts effects; T03 |
| `core/workbench/model_profile_store.py:15–50`, `workbench/journal.py` and direct SQL consumers selected for reuse | Inventory each retained capability; replace its SQL persistence with Neo4j repositories, immutable IDs, transactions and conflict/replay semantics | Current ModelProfileStore creates SQL tables/triggers via Journal; do not wire it into the new backend. Migrate required profile records or explicitly initialize a new Neo4j catalogue; T13 |
| `core/graph_rag.py:387`, `workbench/research_retrieval.py`, `workflow/prior_artifacts.py` | Installed read-authorized retriever callback, exact retained receipt, no new graph schema | Existing eligibility/readback validators and optional/required semantics; T05 |
| `examples/environment_generation_runner.py:660` → `ArenaEnvGraphSpec.to_arena_env` / `ArenaEnvBuilder.make_registered` | Proposed `core/workflow/native_realization.py` typed adapter; existing runner delegates | Do not copy legacy broad critic exception fallback into managed acceptance; T06/T07 |
| `core/trajectory_capture.py:12`, `trajectory_assessment.py:48`, `workflow/scene_observation.py:368`, `scene_evidence_artifacts.py` | Retain existing helpers; add native sampler/camera/profile calibration and receipt assembly | Preserve task-driven prompts, terminal/autoreset behavior and nested cleanup; no redo of earlier trajectory fix; T06/T07 |
| `isaaclab_arena/evaluation/policy_runner.py`, `examples/web_api/evaluation_worker.py:24`, `evaluation_artifacts.py`, `evaluation_profiles.py` | Proposed `core/workflow/policy_evaluation.py` adapter and shared pure evaluation contract | Keep runner, metrics and task predicates; remove fixed legacy policy budget as a hidden managed default; T08 |
| `core/workflow/read_model.py:20`, `neo4j_store.py:2047,2061` | Extend shared outcome/action projection, bounded list/evidence queries and full projection revision | Existing events are reused, not re-created; T10 |
| `examples/web_api/application.py`, `security.py`, `workflow_authorization.py` | Extract reusable HTTP/security functions into a backend composition that constructs only the refactored application and Neo4j repositories | Do not mount GraphQL into the unchanged legacy bootstrap if that creates Journal/SQLite. No route/SSE compatibility requirement; T11/T12/T13 |

Extraction order: characterize existing callers → move one reusable seam → leave compatibility exports → run isolated parity → migrate its managed caller. Do not relocate every legacy diagnostic script or copy their implicit environment/graph defaults into core.

For SQLite-backed capabilities, the sequence is inventory domain records/invariants and direct SQL callers → define the Neo4j repository/transaction contract → implement and test against disposable Neo4j → explicitly import required historical records with identity/relationship/readback checks → remove the SQLite dependency from the new composition. An import, if needed, is an explicit one-way administrative operation with retained mapping/reconciliation evidence, not online dual writes or a runtime fallback. Avoid copying an entire legacy bootstrap merely to reuse a helper. Compatibility exports may delegate to the Neo4j implementation; they must not retain SQL execution inside the refactored backend.

## 9. GraphQL contracts over the refactored application

### 9.1 API shape and dependency choice

Use the same facade for GraphQL, direct application calls and CLI. New REST endpoints are not a prerequisite or required parallel interface. The schema models research/workflow commands and results, not autogenerated Neo4j CRUD or arbitrary Cypher. Authentication creates a secret-free `AuthContext` (principal, deployment/workspace, capabilities, deadline, correlation); never trust a mutation's claimed principal or serialize cookies/provider keys/private grants into context/logs.

Recommend evaluating Strawberry's optional FastAPI router first because this is a Python/Pydantic application; Ariadne is the SDL-first alternative. Neither is currently declared in `pyproject.toml:36–42`. Selection requires pinned Python/FastAPI compatibility, security tests and dependency/license inventory; it is not approval to install now. Strawberry documents that synchronous resolver functions run on its event loop, so blocking Neo4j/filesystem work must be explicitly offloaded and long workflow execution delegated to the owner.[4]

Illustrative contract sketch, **not complete executable SDL**; names/types are proposed and must be generated/tested against the shared wire contract:

```graphql
scalar Cursor
scalar Revision
scalar Digest

type Query {
  workflow(id: ID!): Workflow
  workflowSubmission(operationId: ID!): SubmissionLookup!
  workflowCommand(kind: WorkflowCommandKind!, operationId: ID!): CommandLookup!
  workflowProfiles: [WorkflowProfile!]!
  workflows(first: Int!, after: Cursor): WorkflowConnection!
  workflowEvents(after: Cursor!, first: Int!): WorkflowEventPageResult!
}

type Mutation {
  submitWorkflow(input: SubmitWorkflowInput!): SubmitWorkflowResult!
  cancelWorkflow(input: CancelWorkflowInput!): CancelWorkflowResult!
  resumeWorkflow(input: ResumeWorkflowInput!): ResumeWorkflowResult!
}

input SubmitWorkflowInput { operationId: ID!, request: WorkflowRequestInput! }
enum WorkflowCommandKind { SUBMIT CANCEL RESUME }
input CancelWorkflowInput { operationId: ID!, runId: ID! }
input ResumeWorkflowInput {
  operationId: ID!
  runId: ID!
  expectedVersion: Revision!
  renewAuthorization: Boolean!
}

union SubmitWorkflowResult = WorkflowAccepted | RequestConflict | AdmissionRefused | OutcomeUnknown
union CancelWorkflowResult = CancellationObservation | RequestConflict | CommandRefused | OutcomeUnknown
union ResumeWorkflowResult = ContinuationAccepted | RequestConflict | CommandRefused | OutcomeUnknown
union WorkflowEventPageResult = WorkflowEventPage | ReplayGap

type Workflow {
  id: ID!
  operationId: ID!
  version: Revision!
  projectionRevision: Revision!
  eventCursor: Cursor!
  state: WorkflowState!
  phase: WorkflowPhase!
  result: WorkflowResult!
  availableActions: [WorkflowAction!]!
}
```

`WorkflowRequestInput` maps the existing source, criteria, preservation/intervention, profile, budget and effect fields; add versioned policy coverage fields rather than accepting arbitrary JSON. `WorkflowResult` distinguishes candidate production, scene acceptance, policy outcome, workflow outcome, publication, cleanup and uncertainty. Artifact access resolves authorized immutable IDs/manifests, never arbitrary local paths. Cursor/revision scalars must preserve exact large values; GraphQL `Int` is only signed 32-bit.[29]

Submit already has exact replay semantics. Durable operation-key receipts for cancel/resume are **new work**, not supplied by adding SDL arguments. Specify scope/key/canonical payload digest, retained disposition and conflict behavior. A stale expected version must not block emergency owner-local stop; report cancellation delivery independently. Unknown mutation responses trigger lookup of the same operation, never a new key and fresh effects. `renewAuthorization` requests renewal under shared rules; it does not itself authorize anything. Ordinary GraphQL partial data/errors cannot be interpreted as a completed mutation.[23] Serial root mutation execution within one request does not serialize separate clients or provide transaction/effect idempotency.[29]

#### Command recovery across adapters

Add shared `command_status(auth, kind, operation_id)` and expose it through the proposed GraphQL `workflowCommand` and CLI `command-status --kind … --operation-id …`. Namespace is `(operational database/store authority, deployment, workspace, command kind, operation ID)`, never adapter name or a caller-selected principal. For `SUBMIT`, this wraps the existing scoped submission identity unchanged; no rekeying of old runs. Kind is explicit for new cancel/resume receipts, so the same literal ID in a different kind cannot alias the wrong receipt. Current read authorization always applies.

Freeze canonical command payloads: submit → accepted canonical request; cancel → exact run ID; resume → exact run ID, expected run version and renewal-request flag. Retain payload digest, target, disposition and uncertainty with the command version; same scoped kind/key + changed payload conflicts. Queries return `not_found`, a retained receipt, or explicit store-unavailable/unknown, without dispatch or fresh credential resolution. The lookup result is the retained command disposition, while a separate status query observes newer run state.

Propose `--operation-id` for installed-profile cancel/resume, `--expected-version` for installed-profile resume, and the read-only `command-status` command. These flags/command do **not** exist in the current parser; retain legacy invocation behavior separately. Direct application calls, CLI and GraphQL must share payload normalization and receipt lookup. Verify lost acknowledgements and cross-adapter replay with zero new released effects/grant renewal. Emergency owner-local stop remains deliverable before DB/receipt access; if persistence fails, report local delivery and durable outcome unknown separately. Command idempotency cannot promise exactly-once remote effects.

### 9.2 Existing events, revisions and pagination gaps

- `Neo4jWorkflowStore._event` (`neo4j_store.py:362`) already appends scoped events atomically with transitions. `snapshot` and `events_after` (`:2047`, `:2061`) already use a shared control-lock boundary; event pages enforce 1–1000 entries and reject cursors outside floor/ceiling. Do not propose rebuilding a missing event store.
- Current public events expose sequence, run ID, operation ID, kind and schema version, not a rich payload/aggregate revision/source linkage. Define a backend workflow-event DTO with **invalidation semantics followed by authorized projection queries**; extend sanitized envelopes only for explicit domain needs. Keep scope-wide event cursors when querying an individual run; a later status read is not the historical state of an older event. Test duplicate/multi-run events, query/event races and replay gaps at the application/API boundary. No frontend reconciler or legacy JobEvent conversion is part of this work.
- Snapshot currently returns all scoped runs; bounded result loading is not pagination. Add bounded keyset run/evidence/candidate connections with scoped opaque cursors. Choose explicit live-list consistency initially; invalidate/refetch on changes rather than claiming unimplemented historical snapshot reconstruction. GraphQL guidance supports opaque cursor connections, but that alone does not create storage snapshot semantics.[22]
- Run version and projection revision differ. `retire_owner` (`:1987`) changes owner-derived cleanup without a run event; `read_model.py:162` displays that cleanup. Add owner-dependent result invalidation/revision before promising stable ETags. `_lock` increments an internal control revision even on these reads; do not expose it blindly as domain revision.
- Define the event authority/stream namespace from the Neo4j-backed application; SQLite SSE is not the target contract and requires no compatibility adapter here. Floor checking is not proof of a retention/pruning implementation. Design pruning and cursor validation/page materialization together before enabling retention.
- Begin with bounded authenticated polling/event pages. Subscriptions are deferred: GraphQL does not prescribe their transport, and periodic polling is a documented alternative for less frequent updates.[1] A later transport must retain replay gaps, authentication renewal and bounded queues; it must not own execution lifetime.

### 9.3 Durable query semantics and API security

Every backend entity/query result binds `(authority namespace, deployment, workspace, entity ID)` and the complete result revision. A fresh authenticated client/process can reconstruct selected run/candidate/evidence and command dispositions from retained state. Query/profile/event reads never resolve execution grants, start services or dispatch work. `availableActions` is computed from retained state and current permission, not a promise that a later command cannot lose a race. Client caching, browser refresh/navigation, editor drafts and the historical disappearance report are deferred dashboard concerns, not acceptance criteria here.

Define API authentication independently of the dashboard; reuse suitable existing security code without importing UI lifecycle assumptions. For cookie-authenticated HTTP, enforce exact Origin and CSRF mutation checks. Deny GET mutations, scope nested resolvers and artifact fetches, cap body/depth/complexity/aliases/batching/list sizes, sanitize errors and rate-limit expensive reads. Consider trusted operation documents; GraphQL security guidance describes such allowlists.[25] No GraphQL Docker/shell/host-PID operations. Test authorized positive paths as well as denial cases through backend clients, without requiring a browser.

## 10. Acceptance matrix and evidence ladder

Tests below are obligations for implementation, **not results of this planning session**. Use the repository's admitted isolated harness for package execution and disposable Neo4j, without weakening ordinary F0 guards. Native/live/shared services require separate explicit authorization. Record exact source/profile/contract digests, proof artifacts, cleanup and limits for each gate; do not sum overlapping test cohorts into end-to-end coverage.

| ID | Positive path | Required counterexamples / retained evidence | Gate |
| --- | --- | --- | --- |
| T01 | Pure contracts, profile catalogue and facade import without runtime effects; wrappers delegate to the refactored application | Deny native/SDK/web imports and credential discovery at pure boundary; no dynamic request-selected factories; no Journal/SQLite dependency in refactored application paths | M0 isolated |
| T02 | Fresh submission → handle → real generation entrypoint → scene decisions; exact replay before mutable config/grants | Same key changed contract conflicts; removed profile/expired execution grant does not break authenticated replay; no duplicate admission/dispatch | M0/M1 isolated |
| T03 | Actual SDK serialization for selected generation and assessment roles, shared allowance before construction | Every required unavailable dependency gives zero calls incl. ping; role mismatch, revoke/expiry, retry/image failure, unknown pricing and direct-HTTP fallback; static secret-free diagnostics | M1 isolated, then bounded provider approval |
| T04 | Reserve/register/release/adopt/cleanup and exact restart recovery | Lost commit/release ACK, cancel during callback, DB unavailable cancel-client, dead owner, missing/tampered receipt; unknown released work never redispatches; original budget/deadline unchanged | M1/M2 isolated and intended-process topology |
| T05 | Existing retriever returns eligible provenance and exact context consumed once | Empty versus unavailable; required prior blocks; wrong database, malformed/mutable evaluation, duplicate identity, timeout/cleanup; read-only credential denial of writes and exact property/relationship readback (node count alone is insufficient) | M1 isolated DB; separately approved prior read |
| T06 | Native builder yields wrapper, literal runtime subject mapping and aligned state/RGB evidence under one owned lease | Templated prim path, wrong tensor/force filter/frame, missing camera/modality, falling/sliding object, nonfinite sample, terminal/autoreset, startup/close failure, warm legacy renderer contention | M2 isolated adapter tests then native calibration |
| T07 | Application autonomously repairs an explicitly permitted effective XY failure and obtains a fresh complete passing cohort | No-effect initial_pose edit; original cumulative radius exceeded; Z/task/physics/topology mutation; mixed-reset complementary passes; unsupported producer; exhausted budget retains nonaccepted outcome | M2 isolated and approved native scene loop |
| T08 | Policy runner completes declared A2 episodes with frozen operational lift/dwell/destination predicates, exact identity and denominators | Server replacement/wrong modalities, no completed episodes, partial horizon, settle failure, incomplete predicate sequence, policy budget exhaustion; crash/restart at atomic scene→policy handoff; no graph/lineage side effect; policy failure cannot leave overall accepted; one-step dwell never relabelled sustained grasp | M3 isolated then approved policy pilot |
| T09 | Separate process reaches exact owner's stop channel and verified cleanup; API response/disconnect does not own work | Wrong UID/scope/namespace, unreachable owner, DB outage, expired in-memory grants, restarted owner; no arbitrary PID kill/takeover | M2/M4 deployment topology |
| T10 | Bounded status/list/events reconstruct selection and cleanup with complete projection revision | Wrong-scope/floor/ceiling cursors, owner retirement without run transition, overflow, concurrent mutation/pruning; every read leaves domain execution unchanged | M4 isolated DB |
| T11 | Direct application/CLI/GraphQL share normalized contracts, command dispositions and stable IDs across fresh clients/processes | Duplicate/lost submit/cancel/resume response recovered by scoped kind/key lookup; cross-adapter replay and changed-payload conflict; event/query revision races; observer never dispatches or renews | M4/M5 backend integration tests |
| T12 | GraphQL queries/mutations implement the shared application contract without dashboard dependencies | Applicable CSRF/origin/GET mutation checks, nested cross-scope artifact, alias/batch bypass, body/complexity limits, large revision, blocking resolver, partial error/unknown mutation, secret sentinels | M5 isolated API tests |
| T13 | Neo4j-only backend boots and exercises profiles, submit/status/cancel/resume, events and GraphQL queries/mutations with no legacy DB present | Static import/caller inventory plus runtime Journal/SQLite connection denial; all application writes/reads verified in disposable Neo4j; DB outage fails explicitly with no local fallback/dual writes; selected data import preserves identities, conflicts, relationships and replay | M0 and every reused capability; M4/M5 full backend gate |

Live proof ladder: (a) installed observation-only config/status; (b) authorized bounded provider/prior checks; (c) embodiment-correct hold/native calibration without policy inference; (d) actual application-owned scene loop; (e) fixed-scene policy pilot; (f) GraphQL submission/query/cancellation through a backend client over the same application. Isolated GraphQL contract tests run earlier without live effects. Each is a separate receipt/claim. A valid rejection completes execution honestly but does not satisfy the positive scene/manipulation acceptance gate. Always report implemented, isolated-tested, live-verified and deployed separately.

## 11. Decisions to freeze before release and deferred scope

| Decision | Default proposal / owner | Release condition |
| --- | --- | --- |
| Provider/model pair and accounting | Operator selects one literal generation/assessment pair; trusted adapter verifies supported policy | Capabilities, route/fallback policy, positive token and conservative cost bounds frozen; no guessed current prices |
| Credential UX | Private pipe first; named environment source optional and explicit | Security tradeoff documented; no dotenv/argv secret fallback; cross-process owner handling tested |
| Prior source and empty behavior | Explicit read-only profile; optionality selected in contract | Authorized database, eligibility callback and empty/unavailable semantics fixed before first inference |
| Native producer | One-environment calibrated scene profile | Resolved prim/contact/camera/coordinate mapping, effective XY placement and thresholds demonstrated |
| Policy pilot | A2, verified N1.6 DROID-compatible service, two distinct declared simulator seeds | Served artifacts/modalities, instruction, unchanged predicates, step/settle/deadline caps and aggregation frozen; remote RNG uncertainty declared |
| Installed owner topology | Existing local host/container boundaries, one owner per scope | Same lease/socket/artifact resources and cancellation verified; no inferred cross-host support |
| GraphQL dependency | Evaluate Strawberry first; Ariadne alternative | Dependency/license/compatibility review and application-contract/security tests; no dashboard or REST migration prerequisite |
| Durable profiles | Explicit immutable public profile definitions with Neo4j-backed application catalogue/revisions | No Journal-backed ModelProfileStore or read-through SQLite adapter; retained settings and identity/conflict checks verified in Neo4j |

Deferred: dashboard/frontend work, browser parity and legacy dashboard-route/SSE migration; generic service orchestration/distributed scheduling, automatic research publication, generalized OpenVLA/G1/GR1 profiles, policy-diagnosis-driven DCRG/VLM intervention, GraphQL subscriptions and robustness claims. SQLite removal from the refactored application's dependencies is **not deferred**; historical data transfer requires explicit administration, not compatibility at runtime. Preserve existing DCRG engines/research history; deferral is not a claim those experiments never existed. Native calibration failures may require a versioned producer or constrained initial scope, not silent weakening of the research question.

## Sources

[1] https://graphql.org/learn/subscriptions
[4] https://strawberry.rocks/docs/integrations/fastapi
[8] https://openrouter.ai/docs/guides/overview/models
[10] https://neo4j.com/docs/python-manual/current/transactions
[14] https://docs.isaacsim.omniverse.nvidia.com/6.0.0/py/source/extensions/isaacsim.simulation_app/docs/index.html
[16] https://graphql.org/learn/authorization
[18] https://openrouter.ai/docs/guides/routing/provider-selection
[22] https://graphql.org/learn/pagination
[23] https://graphql.org/learn/response
[25] https://graphql.org/learn/security
[26] https://github.com/openai/openai-python
[29] https://spec.graphql.org/September2025
