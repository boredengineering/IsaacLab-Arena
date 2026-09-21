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