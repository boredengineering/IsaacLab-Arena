---
title: "Development State — 2026-10-16 Snapshot"
category: "Plan 04 Implementation & Hermes Agent"
date_created: "2026-10-16"
last_updated: "2026-10-16"
status: "Project Status Snapshot & Handoff"
subsystem: "Full Stack Repository Status"
tags: ["status-snapshot", "workstream-handoff", "g3-recovery", "unit-tests", "hardening"]
---

> **Topic / Category**: Plan 04 Implementation & Hermes Agent  
> **Date of Creation (YYYY-MM-DD)**: 2026-10-16 | **Last Updated (YYYY-MM-DD)**: 2026-10-16  
> **Status**: Project Status Snapshot & Handoff  
> **Subsystem**: Full Stack Repository Status  
> **Summary**: Comprehensive state-of-the-repository overview covering all workstreams (G3 proxy recovery, 173 unit tests passing, container and test suites, local inference milestones M1-M6, and next steps).

---

# Development State — 2026-10-16

A `workbench` background lookup failure in Stage 3's empirical campaign (G3) triggered a CPU-based proxy recovery procedure, passing 173 module tests.

Here is an overview of the project, where we left off across each workstream, and what is queued next.

---

## 1. What This Project Is

**Isaac Lab-Arena (`isaaclab-arena-private`)** is a robotics simulation environment-generation and policy-evaluation platform built on **Isaac Sim 6.0** and **Isaac Lab 3.0 Beta**, extended with an **Agentic Environment Generation & Local Physical AI Stack** designed for a Dual-Blackwell workstation (`GPU 0: RTX PRO 6000 96 GB` + `GPU 1: RTX 5090 32 GB`):

- **Core Arena Packages**:
  - [`isaaclab_arena/`](../../../../isaaclab_arena/) — Core simulation tasks, embodiments, scenes, assets, and evaluation runners ([`policy_runner.py`](../../../../isaaclab_arena/evaluation/policy_runner.py)).
  - First-party extensions: [`isaaclab_arena_environments/`](../../../../isaaclab_arena_environments/), [`isaaclab_arena_examples/`](../../../../isaaclab_arena_examples/), [`isaaclab_arena_g1/`](../../../../isaaclab_arena_g1/), [`isaaclab_arena_gr00t/`](../../../../isaaclab_arena_gr00t/), and [`isaaclab_arena_curobo/`](../../../../isaaclab_arena_curobo/).
- **Agentic Environment Generation ([`isaaclab_arena/agentic_environment_generation/`](../../../../isaaclab_arena/agentic_environment_generation/))**:
  - Synthesizes scene specifications (`ArenaEnvGraphSpec`) from natural language prompts using **RDF-star / W3C SHACL** validation ([`rdf_validation.py`](../../../../isaaclab_arena/agentic_environment_generation/rdf_validation.py)), **Loopy Belief Propagation (LBP)** spatial factor-graph relaxation ([`spatial_geometric_oracle.py`](../../../../isaaclab_arena/agentic_environment_generation/spatial_geometric_oracle.py)), **Neo4j 5.26 LPG** experience memory, **W3C PROV-O** lineage tracking, and a multi-tier **Visual & PhysX Preflight Critic** ([`visual_critic.py`](../../../../isaaclab_arena/agentic_environment_generation/visual_critic.py)).
- **Dual-Blackwell Air-Gapped Inference Stack ([`.agents/references/plans/local-inference/README.md`](../../plans/local-inference/README.md))**:
  - **GPU 0 (RTX PRO 6000 96 GB)**: `Qwen2.5-Coder-32B-Instruct-AWQ` via vLLM (Port `8000`) for schema-guided spec synthesis.
  - **GPU 1 (RTX 5090 32 GB)**: `Qwen2.5-VL-7B-Instruct` via vLLM (Port `8001`) for visual scene criticism + headless **Isaac Sim 6.0** + **`nvidia/GR00T-N1.6-DROID`** policy server (ZeroMQ Port `5556`).

---

## 2. Where We Stopped

### A. Repository & DevContainer Migration (Completed Today — `2026-10-16`)
- **Plan**: [`isaaclab-arena-private-migration-plan.md`](../../plans/isaaclab-arena-private/isaaclab-arena-private-migration-plan.md)
- **Status**: **100% Complete**.
  - Migrated all 4 branches (`main` $\rightarrow$ `release/0.3.0` $\rightarrow$ `release/0.3.1` $\rightarrow$ `dev/0.3.0-prerelease`) cleanly into `boredengineering/isaaclab-arena-private` with Git LFS objects and initialized submodule gitlinks (`submodules/IsaacLab` and `submodules/Isaac-GR00T`).
  - Fixed [`.devcontainer/devcontainer.json`](../../../../.devcontainer/devcontainer.json) in commit `90ab530` to remove a duplicate mount and add `/workspaces/isaaclab-arena-private` to `PYTHONPATH` and `safe.directory`.
  - We are currently on branch `dev/0.3.0-prerelease` with a clean working tree.

### B. Track 1: Local Dual-GPU Inference & Codebase Hardening (`2026-10-06`)
- **Documents**:
  - [`experiment_01.md`](../../plans/local-inference/experiment_01.md)
  - [`experiment_01_findings.md`](../../plans/local-inference/experiment_01_findings.md)
  - [`hardening_plan.md`](../../plans/local-inference/hardening_plan.md)
- **Where we stopped**:
  1. **Phase 1.5 Zero-Action Simulation Gating Complete (`v5-1`)**: Evaluated Scenario A2 (*Franka DROID: Yellow Banana to Red Bowl*) across iterations `v1`–`v5-1`, achieving 100% stable equilibrium on `packing_table` (300/300 steps, $0.0009\text{ m/s}$ final linear velocity, zero drops).
  2. **Root-Cause Audit Completed**: Diagnosed why `v3` (banana rolled off `table_oak_robolab` chamfer at step 14) and `v3-1` (banana spawned inside the resting Franka gripper at `[-0.09, -0.10, 0.76]`, catapulting at step 0) passed static checks—identifying **9 pipeline weaknesses** (e.g., `--mode resolve` bypassing visual/physics critics, `VisualSceneCritic` called with `rendered_images=None`, substring collisions in `SpatialGeometricOracle`, missing 3D gripper exclusion zone, and VLM prompt conflation).
  3. **Hardening Plan Approved, Not Yet Coded**: Tasks **HR-01 through HR-08** are specified with ready-to-run `/goal` prompts in [`hardening_plan.md`](../../plans/local-inference/hardening_plan.md) and [`experiment_01_findings.md`](../../plans/local-inference/experiment_01_findings.md), but **zero code changes for HR-01–HR-08 have been applied to the Python files yet**.
  4. **Phase 1.6 GR00T Closed-Loop Rollout Pending**: After fixing the `--policy_config_yaml_path` CLI requirement and `MsgSerializer` wire compatibility in [`gr00t_remote_closedloop_policy.py`](../../../../isaaclab_arena_gr00t/policy/gr00t_remote_closedloop_policy.py), the 5-episode closed-loop `GR00T-N1.6-DROID` evaluation on `v5-1` remains marked `⏳ Pending Phase 1.6`.

### C. Track 2: Plan 04 Installed Scene Workflow (`2026-09-28`)
- **What Track 2 Is**: **Track 2 (`Plan 04`) is the GraphQL + Neo4j backend engine built to power the dashboard and CLI from one unified state machine** ([`isaaclab_arena/agentic_environment_generation/workflow/`](../../../../isaaclab_arena/agentic_environment_generation/workflow/)).
  - **How It Evolved (Dashboard $\rightarrow$ Bottom-Up GraphQL + Neo4j Backend)**:
    1. **Started as the TanStack Workbench / Dashboard** ([`tanstack_agentic_workbench_plan.md`](../../plans/workbench_and_ui/tanstack_agentic_workbench_plan.md)): Initially started building a **React + TypeScript + TanStack** web dashboard (`web/` + FastAPI backend) to replace the legacy Streamlit review GUI and achieve full parity with the CLI ([`dashboard_cli_workflow_parity.md`](../../plans/dashboard_cli_workflow_parity/dashboard_cli_workflow_parity.md)).
    2. **Discovered Split-Brain State (SQLite vs. Neo4j & UI vs. CLI)**: While building the dashboard, it became clear that the web workbench was tracking jobs in a local **SQLite** database while the agentic pipeline used **Neo4j**, and the UI and CLI were running different validation/generation code paths.
    3. **Pivoted to "Bottom-Up GraphQL + Neo4j First, Dashboard Second"** ([`event-mapping-refactoring_plan_03.md`](../../plans/event_mapping/event-mapping-refactoring_plan_03.md) & [`event-mapping-refactoring_plan_04.md`](../../plans/event_mapping/event-mapping-refactoring_plan_04.md)): Paused frontend UI work and refactored the backend bottom-up into [`workflow/`](../../../../isaaclab_arena/agentic_environment_generation/workflow/) so that:
       - **Neo4j is the single source of truth** ([`workflow/neo4j_store.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/neo4j_store.py), retiring SQLite completely).
       - **GraphQL** ([`workflow/api/`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/), [`workflow/service.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/service.py)) is the unified API for everything: prompt generation, launching Isaac Sim workers, capturing camera PNGs, calling the VLM critic, repairing coordinates, and running policies.
       - Both the **CLI** ([`workflow/cli.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/cli.py)) and the **future TanStack Dashboard** act as clients of that exact same GraphQL API.
  - **Track 1 vs. Track 2 Summary**:
    - **Track 1 (`Local Inference` / [`hardening_plan.md`](../../plans/local-inference/hardening_plan.md))**: Dual-Blackwell local AI & physics work (making `vLLM` + `Isaac Sim` + `GR00T` + `VisualSceneCritic` + `SpatialGeometricOracle` generate and validate stable scenes locally without cloud APIs via [`environment_generation_runner.py`](../../../../isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py) and [`policy_runner.py`](../../../../isaaclab_arena/evaluation/policy_runner.py)).
    - **Track 2 (`Plan 04`)**: Stateful GraphQL + Neo4j orchestration backend ([`workflow/application.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/application.py)) proving that one single authenticated GraphQL request can autonomously own the entire pipeline with strict process and budget accounting.
- **Documents**:
  - [`how-far-to-finish-plan04.md`](../../plans/plan04_implementation/how-far-to-finish-plan04.md)
  - [`03-full-scene-workflow.md`](../../plans/plan04_implementation/03-full-scene-workflow.md)
  - [`event-mapping-refactoring_plan_03.md`](../../plans/event_mapping/event-mapping-refactoring_plan_03.md)
  - [`event-mapping-refactoring_plan_04.md`](../../plans/event_mapping/event-mapping-refactoring_plan_04.md)
  - [`tanstack_agentic_workbench_plan.md`](../../plans/workbench_and_ui/tanstack_agentic_workbench_plan.md)
- **Where we stopped**:
  - **Stage 1 (`P04-I01` — Native Simulation Slice — *Completed Sept 25*)**: Verified & Closed. Tested that the GraphQL server can launch an owned Isaac Sim worker ([`native_capture.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/native_capture.py)), step PhysX for 180 steps (`red_block` and `blue_bin`), verify settling ($< 0.001\text{ m/s}$ linear, $< 0.01\text{ rad/s}$ angular), capture 3 camera PNGs, seal artifacts with SHA-256 hashes, and cleanly shut down worker processes.
  - **Stage 2 (`P04-I02` — Installed Visual Assessment — *Completed Sept 25*)**: Verified & Closed. Tested that the GraphQL server can send the 3 retained PNGs from Stage 1 to the VLM (`gpt-6-astra`) via [`retained_assessment.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/retained_assessment.py), store the structured visibility verdict in Neo4j, replay the result without re-charging tokens, and drain the API server cleanly.
  - **Stage 3 (`P04-I03` — Full Configurable Scene Loop — *Paused Sept 28*)**: Combines Stages 1 & 2 + automated XY coordinate repair ([`scene_loop.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_loop.py), [`repairs.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/repairs.py)) into one unbroken GraphQL submission.
    - `G1` (contracts, `schema_version == "5"` in [`contracts.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/contracts.py)) and `G2` (non-sending installed GraphQL composition, 976 CPU unit tests passed) completed (`ACCEPT_NON_SENDING_G2`).
    - During `G3` (`SUCCESSOR-R3`), live native execution hit a `workbench` background asset lookup bug; `SUPPORT-PROXY-RECOVERY` fixed the lookup on CPU (173 tests passing) and prepared the `p04-i03-g3-support-proxy-recovery-root-xy-pair-v1` successor proposal (awaiting operator issuance and native ceiling bump $4 \rightarrow 5$).

---

## 3. What Is Next

Depending on which track you want to advance right now, our immediate next steps are:

1. **Execute the Codebase Hardening Plan ([`hardening_plan.md`](../../plans/local-inference/hardening_plan.md) — Recommended First Step for Local Inference)**
   - **Phase 1 (Defenses & Parity)**:
     - **HR-01**: Add pre-flight endpoint probing (`127.0.0.1:8000`, `8001`, `7688`) and `--strict-critics` to [`environment_generation_runner.py`](../../../../isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py) and [`visual_critic.py`](../../../../isaaclab_arena/agentic_environment_generation/visual_critic.py).
     - **HR-02**: Unify `generate_spec()` and `refine_spec()` validation via `_evaluate_spec_holistic()` in [`environment_generation_agent.py`](../../../../isaaclab_arena/agentic_environment_generation/environment_generation_agent.py).
     - **HR-03 & HR-07**: Fix `FIXTURE_SECTOR_BOUNDS` substring collision, add `table_oak_robolab` chamfer margins, and add the 3D resting gripper exclusion volume in [`spatial_geometric_oracle.py`](../../../../isaaclab_arena/agentic_environment_generation/spatial_geometric_oracle.py).
     - **HR-04 & HR-08**: Remove silent `try/except pass` in factor-graph relaxation and update the local VLM preflight prompt in [`visual_critic.py`](../../../../isaaclab_arena/agentic_environment_generation/visual_critic.py) to check for step-0 kinematic collisions and model IDs dynamically.
   - **Phase 2 & 3 (Grounded Sim & Self-Healing)**:
     - **HR-06**: Transparent tier-aware telemetry card in [`telemetry.py`](../../../../isaaclab_arena/agentic_environment_generation/telemetry.py).
     - **HR-05**: Implement `--mode grounded-resolve` (30-step headless settle + camera frame capture + Port 8001 VLM inspection loop).
     - **HR-07 (Bridge)**: Emit `failure_manifest.json` on drops in [`policy_runner.py`](../../../../isaaclab_arena/evaluation/policy_runner.py) and ingest it in `--mode auto_heal`.
2. **Run Experiment 01 Phase 1.6 (Closed-Loop GR00T-N1.6-DROID Rollout)**
   - Execute the 5-episode closed-loop manipulation benchmark on the settled `v5-1` banana-to-red-bowl environment (`GPU 1`) and record task success rate in [`experiment_01.md`](../../plans/local-inference/experiment_01.md).
3. **Resume Plan 04 Stage 3 (`P04-I03-G3` Support-Proxy Recovery)**
   - Review and issue the `p04-i03-g3-support-proxy-recovery-root-xy-pair-v1` live fixed-candidate native/repair proof in [`03-full-scene-workflow.md`](../../plans/plan04_implementation/03-full-scene-workflow.md).
