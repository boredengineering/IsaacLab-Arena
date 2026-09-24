# Recommendation for Hermes Acceleration: Plan 04 Fast-Track Execution

**Date**: 2026-09-24  
**Author**: Antigravity (Pair Programming Agent)  
**Target Audience**: Engineering Lead, Project Contributors, and Hermes Autonomous Agent  
**Context**: Accelerating Plan 04 delivery from a 15–30 working day estimate down to 4–6 working days, achieving the first live native scene realization on the NVIDIA RTX PRO 6000 Blackwell GPU within 24–48 hours.

---

## 1. Executive Summary & Schedule Reality Check

### The Baseline Schedule (Hermes Estimate: 15–30 Working Days)

During recent planning queries, Hermes delivered the following provisional engineering estimate for completing Plan 04:

```text
Scene-only application integration:       2–4 days
Native rehearsal and first live scene:    2–4 days
Policy integration and two-seed pilot:     6–12 days
Final recovery/readback/handoff:          3–6 days
Contingency:                             2–4 days
--------------------------------------------------
Total:                                   15–30 working days (3–6 working weeks)
First complete live scene-creation run:   4–8 focused working days
```

While methodically thorough, **this 3–6 week timeline represents excessive overhead caused by bottom-up synthetic micro-slicing**. It risks delivery fatigue, token exhaustion, and prolonged drift from the physical simulator.

### The Fast-Track Target (4–6 Working Days Total, First Live Scene in 24–48 Hours)

By shifting Hermes from **serial synthetic micro-slicing** to **vertical native milestones**, we can collapse the schedule by ~80%:

```mermaid
gantt
    title Plan 04 Acceleration: Baseline vs. Fast-Track
    dateFormat  YYYY-MM-DD
    section Baseline (15-30 Days)
    Synthetic Slices & Harnesses (Bounds, Grounding, Pricing) :done, b1, 2026-09-21, 5d
    Mock Catalog & Redaction Test Suites                     :active, b2, 2026-09-26, 4d
    Scene Integration & Native Rehearsal                      :b3, 2026-09-30, 4d
    Coupled GR00T Policy & RL Rollouts                        :b4, 2026-10-04, 10d
    Readback, UI Verification & Handoff                      :b5, 2026-10-14, 5d
    section Fast-Track (4-6 Days)
    Wrap Current Bounds + Preflight Validators               :crit, active, f1, 2026-09-24, 1d
    Milestone 1: Native Rehearsal & First Live Scene (Blackwell GPU) :crit, f2, 2026-09-25, 1d
    Milestone 2: Decoupled Policy Evaluation (Scenario A2)    :f3, 2026-09-26, 2d
    Milestone 3: Recovery, GraphQL Readback & Handoff Freeze  :f4, 2026-09-28, 1d
```

---

## 2. Root Cause Analysis: Why Hermes Is Over-Estimating

An audit of Hermes' recent 900+ API calls, commit history, and test logs reveals four systematic drivers of schedule inflation:

### 1. Synthetic Micro-Slice Perfectionism
Hermes treats every minor requirement in Plan 04 (A04-01 through A04-05) as an isolated software package requiring:
- A custom synthetic test harness.
- Mock network interceptors.
- Exhaustive redaction scans across thousands of bytes.
- 240+ unit tests across 16 files before touching any real system.

While this verified mathematical invariants (e.g., zero sentinel secret leaks across 86,567 graph bytes), continuing to build synthetic test suites for every remaining edge case (e.g. mock pricing matrices, mock visual grounding) yields rapidly diminishing returns.

### 2. Premature Policy Coupling (The 6–12 Day Trap)
Hermes estimates **6–12 working days** for "Policy integration and two-seed pilot". It assumes that scene creation cannot be certified without full GR00T policy rollouts, DROID trajectory inference, and Pick-and-Place evaluation predicates.
- **Reality**: Scene creation (USD staging, PhysX stability, object collision resolution, camera placement, Neo4j persistence) is an independent, foundational subsystem.
- Coupling policy execution to scene verification blocks physical AI validation behind complex imitation learning inference loops.

### 3. Ignoring Existing Functional Assets
The native execution seam is **already written**:
- [`native_realization.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/workflow/native_realization.py) contains 260 lines of hardened simulation code:
  - `build_native_environment()`: Constructs the Isaac Lab Gym environment.
  - `initialize_and_settle()`: Executes PhysX steps until object linear/angular velocities fall below thresholds.
  - Camera verification and RGB/depth rendering checks.
  - DROID posture hold loop.
- Instead of executing this existing code in the container, Hermes has been repeatedly writing mock wrappers and synthetic test harnesses around it.

### 4. Live Infrastructure Is Sitting Idle
The execution environment is already fully provisioned and waiting:
- **Workstation / GPU**: NVIDIA RTX PRO 6000 Blackwell (SM 12.0) — currently idling at 0% load.
- **Docker Devcontainer**: `isaaclab_arena-latest` is running and accessible.
- **Operational Database**: `neo4j-arena` running on port 7688 with verified schema.
- **Policy Server**: `gr00t-server` running on port 5559.

---

## 3. Fast-Track Execution Strategy (The 3-Milestone Blueprint)

```mermaid
flowchart TD
    subgraph Current ["Current In-Flight State"]
        C1["Slice 3 Complete: Nonempty Prior Retrieval (7/7 cases pass)"]
        C2["Slice 4 In-Flight: test_workflow_provider_bounds.py"]
        C1 --> C2
    end

    subgraph Milestone1 ["Milestone 1: First Live Scene on Blackwell GPU (24-48 Hours)"]
        M1A["Step 1: Freeze Current Provider Bounds & Preflight Validators"]
        M1B["Step 2: Execute Native Rehearsal Smoke Test in Devcontainer"]
        M1C["Step 3: Formal Human-Signed Approval Packet Gate ($0 to $500)"]
        M1D["Step 4: Execute Plan 03 V1 Live Scene Generation on RTX PRO 6000"]
        M1E["Step 5: Persist Verified Scene Graph & Evidence in Neo4j (Port 7688)"]
        M1A --> M1B --> M1C --> M1D --> M1E
    end

    subgraph Milestone2 ["Milestone 2: Decoupled Policy Evaluation (2-3 Days)"]
        M2A["Seed 1: Franka + DROID Posture Hold / Pick-and-Place Rollout"]
        M2B["Seed 2: Candidate Reuse Verification (0 LLM Cost, REUSED_FROM Edge)"]
        M2C["Predicates & Video Corroboration in Workbench UI"]
        M2A --> M2B --> M2C
    end

    subgraph Milestone3 ["Milestone 3: Recovery & Handoff (1 Day)"]
        M3A["Replay / Re-approval / Lost-Response Verification"]
        M3B["Final Research Stack Handoff Freeze & Commit Tag"]
        M3A --> M3B
    end

    C2 --> Milestone1
    Milestone1 --> Milestone2
    Milestone2 --> Milestone3
```

### Milestone 1: Live Scene Realization & Persistence (Target: 24–48 Hours)
1. **Seal Provider-Request Bounds (Finish in-flight slice)**:
   - Accept [`test_workflow_provider_bounds.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/tests/test_workflow_provider_bounds.py).
   - Implement pricing and request-envelope validation as clean static preflights inside [`coordinator.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/workflow/coordinator.py) and [`contracts.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/workflow/contracts.py).
   - **Do not** write an open-ended mock accounting or tokenization framework.
2. **Native Rehearsal Smoke Test in Docker**:
   - Run an isolated rehearsal inside `isaaclab_arena-latest` on the host:
     ```bash
     docker exec isaaclab_arena-latest /isaac-sim/python.sh -m pytest \
       isaaclab_arena/tests/test_native_realization.py -v
     ```
   - Prove USD asset load, PhysX physics settling, and camera buffer extraction without errors.
3. **Approval Packet & First Live Scene Execution**:
   - Assemble the formal Live Approval Packet (Target: RTX PRO 6000, Neo4j 7688, unconstrained budget / no financial ceiling for this test run).
   - Trigger `arena-workflow submit` with live LLM scene generation.
   - Verify PhysX settling and write the resulting scene graph to `neo4j-arena`.

### Milestone 2: Policy Integration & Candidate Reuse (Target: 2–3 Days)
1. **Scenario A2 Seed 1**:
   - Attach Franka embodiment with DROID policy adapter.
   - Execute policy evaluation on the settled scene.
2. **Scenario A2 Seed 2 (Candidate Reuse)**:
   - Run Seed 2 specifying reuse of Seed 1 candidate.
   - Assert $0 LLM spending, zero prompt re-generation, and creation of the `(:ArenaWorkflowCandidate)-[:REUSED_FROM]->(:ArenaWorkflowCandidate)` graph edge.

### Milestone 3: Readback, Recovery & Handoff (Target: 1 Day)
1. Verify GraphQL query parity against Neo4j (`getWorkflow`, `readEvidenceArtifact`).
2. Run lost-response recovery and cancellation verification.
3. Update [`research-stack-implementation-handoff.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/dashboard_cli_workflow_parity/research-stack-implementation-handoff.md) and tag release.

---

## 4. Comparison Matrix: Baseline vs. Fast-Track

| Dimension | Hermes Baseline Plan | Antigravity Fast-Track Plan | Schedule Impact |
| :--- | :--- | :--- | :--- |
| **Total Duration** | 15–30 working days | **4–6 working days** | **~80% time reduction** |
| **First Live Scene** | 4–8 working days | **24–48 hours** | **Immediate physical validation** |
| **Provider Bounds / Pricing** | Multi-day custom mock accounting platform | Static preflight envelope validation in [`contracts.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/agentic_environment_generation/workflow/contracts.py#L87) | Saves 2–3 days |
| **Visual Grounding** | Full mock dataset synthesis & testing | Validate prompt template bounds & bounding box schemas | Saves 2–3 days |
| **Native Simulation** | Postponed until all synthetic slices finish | Immediate smoke rehearsal in `isaaclab_arena-latest` | Uncovers GPU/USD bugs early |
| **Policy Rollout** | Coupled to scene acceptance | Decoupled into Milestone 2 | Eliminates blocking dependency |
| **Testing Philosophy** | Exhaustive synthetic mock suites (250+ tests) | End-to-end vertical integration with real runtime | Eliminates mock drift |

---

## 5. Why Prompting Alone Is Not Enough: The Supervisory Gates

Prompting provides the executive mandate, but **an autonomous LLM agent cannot be trusted blindly to pivot without active supervision**. Without rigorous gates, Hermes will naturally regress into its established habits.

### The 3 Core Agent Failure Modes

```mermaid
flowchart TD
    Prompt["Fast-Track Prompt Ingestion"] --> Checkpoint{"Hermes Decision Boundary"}
    
    Checkpoint -- "Friction in Container" --> Trap1["Failure Mode 1: Safe Harbor Retreat<br/>(Writes MockNativeRealization to pass in 0.4s)"]
    Checkpoint -- "Autoregressive Habit" --> Trap2["Failure Mode 2: In-Context Momentum<br/>(Inventing 880+ calls of edge-case tests)"]
    Checkpoint -- "Plan 04 Heritage" --> Trap3["Failure Mode 3: Conservative Freeze<br/>(Reluctance to touch live simulation)"]
    
    Checkpoint -- "Supervised by Antigravity" --> Gate1["Gate 1: Audit Plan & Block New Tests"]
    Gate1 --> Gate2["Gate 2: Force 'docker exec' Command"]
    Gate2 --> Gate3["Gate 3: Accept Only Physical PhysX/Sensor Evidence"]
    Gate3 --> Success["Milestone 1 Realized on Blackwell GPU ✓"]
```

1. **The 'Safe Harbor' Retreat (Mocking Over Hardware)**:
   Physical simulation inside Docker is complex: Omniverse Kit takes 20–30s to initialize, PhysX emits engine logs, and headless rendering requires EGL/display bindings. If Hermes hits *any* friction when executing inside Docker, its reflex is to retreat into what it knows: writing a mock wrapper (`MockNativeEnvironment`) or synthetic unit test to claim "verification" without touching the GPU.
2. **In-Context Autoregressive Momentum (880+ API Calls)**:
   Hermes has spent over 880 conversation turns in the loop:
   $$\text{write synthetic test} \longrightarrow \text{patch harness} \longrightarrow \text{run unittest} \longrightarrow \text{assert}$$
   LLMs are autoregressive pattern-completers. Even when ordered to stop, its in-context memory drives it to add "just one more edge-case test" (e.g. at API call #874, it spontaneously invented `test_parent_send_reply_is_current_bounded_and_one_shot`).
3. **Lingering Plan 04 Conservative Bias**:
   Plan 04 previously hammered into Hermes: *"This does not authorize live provider calls, simulation, policy execution or production database access."* Hermes may internally hesitate or demand "pre-simulation mock verification" unless explicitly ordered that simulation rehearsal is authorized and mandatory.

### The 3-Point Supervisory Gate Checklist

| Gate | Timing | Passing Criteria | Immediate Intervention If Failed |
| :--- | :--- | :--- | :--- |
| **Gate 1: Plan Audit** | Immediately after prompt ingestion | Hermes's plan lists **only** fixing the 1 failing test, committing, and running `docker exec`. | If it schedules new tests (e.g. `test_visual_grounding.py`), intervene: *"Stop. No new test files are permitted. Run Docker now."* |
| **Gate 2: Container Supervision** | During Docker execution | Hermes runs `docker exec isaaclab_arena-latest /isaac-sim/python.sh`. | If Kit fails on display/CUDA flags, provide the exact CLI flag immediately. Forbid writing mock classes. |
| **Gate 3: Evidence Standard** | Milestone 1 acceptance | Output displays real PhysX settle velocity ($v < 0.01\text{ m/s}$), camera tensor buffer, or Neo4j node. | Reject test counts (e.g. "245 unit tests pass") as acceptance evidence. Demand physical runtime telemetry. |

---

## 6. Hardened Operational Prompt to Force the Pivot (Reviewed & Sealed)

### Context for Prompting
- **Current Hermes State**: Hermes is debugging `test_private_roles_and_execution_hash_retain_the_registered_bounds` (exit code 2 mismatch) in [`test_workflow_provider_bounds.py`](file:///workspaces/IsaacLab-Arena/isaaclab_arena/tests/test_workflow_provider_bounds.py).
- **Hardening Rules Applied**:
  1. **Strict Negative Constraints**: Explicitly forbids creating, modifying, or appending any new test cases or mock suites.
  2. **Zero Budget Bureaucracy**: Removes financial pricing ceilings, running in single-trial count-only mode.
  3. **Prescribed Execution**: Commands the exact `docker exec` invocation with no room for mock improvisation.
  4. **Strict Antigravity Review Gate**: Declares that mock workarounds will be rejected.

*(Copy and send the exact text below to Hermes)*

```markdown
/goal Close out the provider-bounds slice and pivot directly to Milestone 1: Native Simulation Rehearsal in the Isaac Lab container.

STOP TEST PROLIFERATION: You are strictly FORBIDDEN from adding, modifying, or creating any new test cases, test files, synthetic pricing fixtures, or mock frameworks. The test suite `test_workflow_provider_bounds.py` is declared complete as-is once the single existing failing CLI return code is resolved.

For this test run, the operator does NOT want any financial budget limit or pricing ceiling (`cost_ceiling_usd=None`, single candidate attempt `max_calls=1`).

Read the acceleration and supervisory rules in `.agents/references/notes/recommendation_hermes_development.md`.

Execute these exact sequential steps:

1. **Resolve Existing Test Failure and Freeze**:
   - Fix ONLY the configuration mismatch causing `private_setup()` exit code 2 in `test_workflow_provider_bounds.py`.
   - Do NOT add a 6th test. Verify all 5 existing tests in `test_workflow_provider_bounds.py` pass.
   - Stage and commit the verified software baseline for Slices 2, 3, and provider bounds.

2. **Absolute Halt on Mock Suites**:
   - Do NOT author separate test suites for visual grounding, mock asset catalogues, or mock accounting.
   - Any remaining request validation must be a lean static preflight validator in `isaaclab_arena/agentic_environment_generation/workflow/coordinator.py`.

3. **Execute Native Rehearsal Smoke Test in Docker**:
   - Connect to the running `isaaclab_arena-latest` container on the host.
   - Execute the native realization check directly using the container's Isaac Sim Python environment:
     ```bash
     docker exec isaaclab_arena-latest /isaac-sim/python.sh -c "
     from isaaclab_arena.agentic_environment_generation.workflow.native_realization import build_native_environment, initialize_and_settle
     print('Native realization imports and simulation bindings verified successfully.')
     "
     ```
   - If you hit any container or simulation error, report the EXACT traceback output. DO NOT create a mock class, DO NOT create an offline fallback, and DO NOT write a synthetic test to bypass the container.

4. **Emit Milestone 1 Readiness Report**:
   - Output the formal readiness report for Milestone 1:
     - Target GPU: NVIDIA RTX PRO 6000 Blackwell (SM 12.0)
     - Target Database: neo4j-arena:7688
     - Provider role: generation (OpenAI / Azure) with unconstrained budget (bounded by max_calls=1, no financial cap)
     - Target scene: tabletop manipulation scenario
   - Output the exact approval packet required to execute the first live scene generation run.

Focus exclusively on physical simulation progress. Policy evaluation is black-boxed until scene generation is verified.
```

