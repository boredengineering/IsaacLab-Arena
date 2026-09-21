# My notes on the event mapping refactoring

Trying to keep track and make sense of the overall progress and big picture of the project.

## Notes as 09/21/2026 - 14:56

The user's intuition is correct; frontend integration is deferred until after validation. A thorough code review will precede a live, end-to-end run of a test scenario. This run's goal is to confirm the integrity of the updated backend pipeline, verifying deterministic causal graph logging. Only then will the web application integration commence.

Your intuition is spot-on. Completing the code changes in event-mapping-refactoring_plan_03.md is necessary, but leaping directly into frontend changes without a live simulation trial would create a fragile integration.

The proper engineering path is:

1. Finish the remaining Plan 03 simulation milestones (M2 & M3).
2. Conduct a formal code & security review (pre-commit, license, credential checks).
3. Execute a live end-to-end trial run (real Isaac Sim PhysX, real Neo4j, real VLM & GR00T policy runner).
4. Execute the Webapp Integration (arena-workbench).

──────

### 1. The Big Picture: How the Pieces Fit Together

To understand why this sequence makes sense, here is the architecture of the project:

```bash
┌────────────────────────────────────────────────────────────────────────┐
│                        User & Frontend Layer                           │
│  • Webapp: web/arena-workbench (Next.js / React / Flow Canvas)        │
│  • Installed Network CLI: python -m ...workflow.cli                   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │  Strawberry GraphQL Contract (M5)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    Workflow API & Application Tier                     │
│  • workflow/api/ (schema.py, resolvers.py, server.py, security.py)     │
│  • workflow/service.py, commands.py, read_model.py, paging.py (M4)     │
│  • workflow/scope_binding.py, provider_configuration.py (M1)          │
└──────────────────┬─────────────────────────────────┬───────────────────┘
                    │                                 │
                    ▼                                 ▼
┌──────────────────────────────────────┐  ┌──────────────────────────────┐
│       Authoritative Store (M0)       │  │ Simulation & Policy Loop     │
│  • Neo4j Graph DB                    │  │  (M2 & M3)                   │
│  • Full causal history               │  │ • Isaac Sim & PhysX Settling │
│  • Candidates, decisions, attempts   │  │ • Franka / DROID Embodiments │
│  • Evidence artifacts & accounting   │  │ • Policy Evaluation (GR00T)  │
└──────────────────────────────────────┘  └──────────────────────────────┘
```

#### Why Refactoring Plan 03 Happened:

* Historical split-brain: Early prototypes stored events in a local SQLite file (journal.py) while simultaneously attempting to write to Neo4j. This caused desynchronization, lost causal traces, and race conditions.
* Architectural leak: Workflow domain logic had leaked into .
* Plan 03 Resolution: Extracted clean domain logic into , made Neo4j the sole system of record, retired SQLite completely, and built a formal Strawberry GraphQL contract layer.

──────

### 2. Immediate Next Steps: Completing Plan 03

Before touching the webapp, Hermes is currently completing the remaining foundational milestones:

Milestone                                                                                                                            | Scope                                                                                                                                | What It Achieves
--------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------
M0 (Done ✓)                                                                                                                          | Domain Models & Persistence                                                                                                          | Pure Neo4j event sourcing, accounting, profiles.
M1 (Done ✓)                                                                                                                          | Local Provider Wiring                                                                                                                | Private file storage, credential isolation, token registry.
M4 (Done ✓)                                                                                                                          | Durable Query & Recovery                                                                                                             | Keyset pagination, run cancellation, execution resumption.
M5 (Verified ✓)                                                                                                                      | GraphQL API & Network CLI                                                                                                            | Strawberry schema (1,175 lines), CLI launch/status/stop/run.
M2 (Next ⏳)                                                                                                                         | Native Scene Loop & PhysX                                                                                                            | ArenaEnvBuilder integration, blocking settle gate (‖𝐯‖ < 10⁻³ m/s), GPU lease management during VLM calls.
M3 (Next ⏳)                                                                                                                         | General Policy Evaluation                                                                                                            | Bridge policy_runner.py with TaskBase in policy_evaluation.py for Scenario A2 (Franka + DROID + banana + plate).

Once M2 and M3 pass automated checks, Hermes seals Delivery Checkpoints V0, V1, and V2.

──────

### 3. Post-Plan 03 Roadmap

Once Plan 03 is sealed, here is our recommended roadmap:

```bash
┌─────────────────────────────────────────────────────┐   ┌──────────────────────┐
│                                                     │   │                      │
│          Plan 03 Completion (M2, M3, V0-V2)         ├─┐ │          B           ├───────────────────────────┐
│                                                     │ │ │                      │                           │
└──────────────────────────┬──────────────────────────┘ │ └──────────────────────┘                           │
                            │                            │                                                    │
                            ▼                            └─────────────▼                                      ▼
┌─────────────────────────────────────────────────────┐   ┌──────────────────────┐   ┌──────────────────────────────────────────────┐
│                                                     │   │                      │   │                                              │
│               B["Phase 1: Code Review               │   │   Quality Gates"]    │   │ Phase 2: Live Simulation Trial (Scenario A2) │
│                                                     │   │                      │   │                                              │
└─────────────────────────────────────────────────────┘   └──────────────────────┘   └───────────────────────┬──────────────────────┘
                                                                                                            │
                                                                                                            │
┌─────────────────────────────────────────────────────┐                                                      │
│                                                     │                                                      │
│ Phase 3: Webapp Modernization (web/arena-workbench) ├◄──────────────┬──────────────────────────────────────┘
│                                                     │               │
└──────────────────────────┬──────────────────────────┘               │
                            │                                          │
                            ▼                                          ▼
┌─────────────────────────────────────────────────────┐   ┌──────────────────────┐
│                                                     │   │                      │
│            E["Phase 4: Final Verification           │   │ Git PR Preparation"] │
│                                                     │   │                      │
└─────────────────────────────────────────────────────┘   └──────────────────────┘
```

#### Phase 1: Code Review & Quality Gates

* Security & Secret Audit: Ensure no credentials, API keys, or private roots leaked into tracked git files.
* Code Style & Pre-commit: Run host-level pre-commit run --all-files (black, flake8, isort, pyupgrade, copyright headers).
* SQLite Tombstone Verification: Confirm zero remaining references to journal.py or SQLite connections in production paths.

#### Phase 2: Live End-to-End Trial Run (Dry-Run in Isaac Sim)

Before frontend integration, we must prove the live simulation stack works in reality, not just mock test containers:

1. Start Services:
   * Local Neo4j container on Bolt port 7688.
   * Local or remote GR00T / OpenPI policy inference server (port 5559).

2. Launch Detached API Server:

```bash
python -m isaaclab_arena.agentic_environment_generation.workflow.cli api-launch \
    --config configs/workflow_local.yaml
```

3. Execute Scenario A2 via Network CLI:

```bash
python -m isaaclab_arena.agentic_environment_generation.workflow.cli client run \
    --config configs/workflow_local.yaml \
    --request "Place a ripe banana on the white ceramic plate using the Franka arm with DROID gripper"
```

4. Validation Checklist:

    [ ] LLM generates candidate scene YAML.

    [ ] Isaac Sim loads the assets and runs PhysX settling until velocity drops below threshold.

    [ ] Camera captures RGB-D snapshot for VLM verification.

    [ ] Franka arm executes policy trajectory.

    [ ] Neo4j logs the complete causal tree (Candidates → Decisions → Evidence Artifacts).


#### Phase 3: Webapp Integration (arena-workbench)

Now that the GraphQL contract and simulation loop are proven:

1. Rip Out Legacy SSE & REST:
   * Remove legacy endpoints /api/workflow and SQLite SSE stream listeners from the React state stores.

2. Implement Strawberry GraphQL Client:
   * Set up an Apollo / Urql client pointed at http://127.0.0.1:18761/graphql.
   * Wire GraphQL operations:
     * submitWorkflowMutation: Submit text prompt or scene configuration.
     * useRunInspectionQuery: Retrieve real-time run status and causal tree.
     * useCandidateConnection & useDecisionConnection: Keyset pagination for browsing candidate variations.
     * cancelWorkflowMutation & resumeWorkflowMutation: User intervention controls.

3. Integrate Graph Visualizer:
   * Map Neo4j node/edge outputs directly into the interactive graph canvas in the workbench.

4. End-to-End User Journey Walkthrough:
   * User types a prompt in the browser → views generated scene render → inspects causal decision nodes → downloads evaluation metrics.


#### Phase 4: Final PR & Documentation

* Clean up any temporary artifacts in outputs/workflow/.
* Update AGENTS.md and top-level documentation with the new workflow usage.
* Create a signed-off branch and PR following repository guidelines.

──────

### 4. Summary of Authorizations You Will Need to Provide

As we progress through these stages, here are the few points where your authorization or input will be needed:

1. GPU Allocation for M2/M3: When running Isaac Sim PhysX tests (requires access to the GPU device).
2. Live VLM API Key: When running the Phase 2 live trial (OpenAI or NVIDIA NIM key stored securely in credentials.json).
3. Git Commit / PR Approval: When all tests and live runs pass and we prepare the final git commits.

Hermes is currently proceeding through the final steps of M5/M2. Let's let Hermes finish the current execution cycle, after which we will begin the Phase 1 Review together!

──────

## Progress Verification & Status Update (09/21/2026 - 21:25 UTC)

Hermes has completed the implementation and isolated verification for both **Milestone 2 (M2)** and **Milestone 3 (M3)**. The comprehensive test suite was executed across **1,550 total test cases with 0 failures and 0 errors**, sealed in [`outputs/workflow/plan03-implementation/m2-m3-parent/final-verification.json`](file:///workspaces/IsaacLab-Arena/outputs/workflow/plan03-implementation/m2-m3-parent/final-verification.json).

### Master Progress Summary

| Milestone / Phase | Key Modules & Artifacts | Status | Core Architecture & Goals | Pass / Acceptance Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **M0: Domain Foundation & Repositories** | `accounting.py`, `profiles.py`, `queries.py`, `neo4j_store.py` | **Completed & Verified** ✓ | Pure Neo4j event sourcing; domain records extracted from `examples`; total retirement of SQLite `journal.py`. | • `T01`, `T13`, `T15` passed.<br>• Zero SQLite dual-writes or fallbacks.<br>• Domain models serialize purely via Neo4j. |
| **M1: Local Bootstrap & Provider Isolation** | `scope_binding.py`, `admin.py`, `provider_configuration.py`, `credentials.json` | **Completed & Verified** ✓ | Private credential isolation outside git (`credentials.json` mode `0600`); scoped token registry; eliminate `.env` / argv leakage. | • Adversarial critic `deleg_a79fbc` PASS (`T03`, `T21`, `T05`, `SB01`).<br>• Zero secret disclosure in process trees or logs. |
| **M4: Durable Query & Command Recovery** | `paging.py`, `commands.py`, `read_model.py`, `service.py` | **Completed & Verified** ✓ | Opaque keyset cursor pagination (`hasMore`, `endCursor`); durable run cancellation (`KC01-03`); admission/execution resumption (`RA01-02`, `RE01-02`). | • **570/570 ordinary Neo4j cases passed** after 4 GiB container authorization. |
| **M5: GraphQL API & Network CLI** | `schema.py`, `resolvers.py`, `cli.py`, `server.py` | **Completed & Verified** ✓ | Contract-first Strawberry GraphQL schema (1,175 lines); detached Uvicorn server with private UDS control socket (`control.sock`); installed network CLI. | • In-process ASGI suite passed 42/42 cases.<br>• Detached installed network CLI suite passed 42/42 cases (`parent-network-verification.json`). |
| **M2: Native Scene Loop & PhysX Settling** | `native_realization.py`, `native_capture.py`, `native_resources.py`, `split_scene_ports.py` | **Completed & Verified** ✓ | Split native lifecycle (`capture` → `assess` → `repair`); blocking settle gate (\|\|v\|\| < 10^-3 m/s); mandatory GPU release before VLM wait; DROID posture hold. | • Isolated native capture suite: **144/144 passed**.<br>• Core lifecycle suite: **368/368 passed**.<br>• Verified GPU lease released before assessment.<br>• Handed off in `m2-split-core/HANDOFF.md`. |
| **M3: General Policy Evaluation** | `policy_evaluation.py`, `policy_contracts.py`, `policy_runner.py`, `policy_episode_records.py` | **Completed & Verified** ✓ | Bridge `policy_runner` to `TaskBase`; `initialized_observation` and `post_reset` hooks; immutable `PolicyTrialReceipt`; nonterminal scene-to-policy handoffs. | • Policy & transport suite: **204/204 passed**.<br>• Scene producers: **106/106 passed**.<br>• Handed off in `m3-policy-core/HANDOFF.md`. |
| **Checkpoints V0, V1, V2** | Full multi-suite regression & Neo4j integration | **Sealed & Verified** ✓ | Prove all modules operate harmoniously under disposable container constraints with zero regressions. | • **1,550 total test cases passed (0 failures)** across 11 suites.<br>• Unified Neo4j suite passed **611/611 cases**.<br>• Sealed in `outputs/workflow/plan03-implementation/m2-m3-parent/final-verification.json`. |

### Detailed Test Suite Breakdown (1,550 Passed / 0 Failures)

- **`neo4j`** (Unified Neo4j Database Store & Event Sourcing): **611 passed**
- **`core`** (Domain Models, Accounting, Commands, Paging): **368 passed**
- **`policy_and_transport`** (Policy Evaluation, Task Binding, Trial Receipts): **204 passed**
- **`native_capture`** (Native Realization, Posture Hold, Settle Gate): **144 passed**
- **`scene_producers`** (Scene Observation, Camera Coverage, Evidence): **106 passed**
- **`graphql`** (Strawberry GraphQL Resolvers & Schema): **43 passed**
- **`network`** (Detached Uvicorn Server & Network CLI Client): **42 passed**
- **`model_engines`** (Model Interfaces & Allowance Bounds): **19 passed**
- **`legacy_scene`** (Scene Engine Compatibility Regressions): **11 passed**
- **`legacy_process`** (Process Isolation Regressions): **1 passed**
- **`legacy_cli`** (Legacy CLI Harness Regression): **1 passed**

### Remaining Open Gates & Next Steps

1. **Installed Submission Integration**:
   - The CLI query suite is fully verified; wire the concrete generation worker execution seam into the CLI launcher so the installed client can submit generation jobs directly.
2. **Live Simulation Trial (Scenario A2 Smoke Run)**:
   - Run a real, non-mocked execution of Scenario A2 (Franka + DROID + banana + plate) in Isaac Sim:
     - Real PhysX physics settling with the blocking settle gate.
     - Real VLM prompt refinement via credentials in `credentials.json`.
     - Real policy rollout on the Franka/DROID embodiment.
     - Verify the full causal graph and evidence artifacts in Neo4j.
3. **Webapp Modernization (`web/arena-workbench`)**:
   - Retire legacy `/api/workflow` and SQLite SSE event-stream code.
   - Wire the Strawberry GraphQL client (`http://127.0.0.1:18761/graphql`) using typed queries/mutations and keyset pagination.
   - Connect the interactive canvas to Neo4j graph nodes.
4. **Final PR & Documentation**:
   - Run `pre-commit run --all-files`.
   - Submit signed-off pull request against `main`.