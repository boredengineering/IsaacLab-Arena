# IsaacLab-Arena Reference Notes Library

Welcome to the **IsaacLab-Arena Reference Notes Library**. This repository houses deep technical investigations, empirical test reports, architectural analyses, postmortems, and developer runbooks authored during the design, development, and hardening of the IsaacLab-Arena robotics simulation platform.

All notes have been organized into **5 topical folders**, categorized with their **creation dates (in standard `YYYY-MM-DD` ISO 8601 format)**, stamped with standardized metadata banners, and indexed for rapid retrieval.

> [!NOTE]
> The directory `.agents/references/notes/` is linked to this directory (`quick_notes/`). All notes are strictly organized into the 5 topical subfolders below, with zero loose documents in the directory root.

---

## Topical Directory Structure

```text
.agents/references/notes/  (quick_notes/)
├── environment_generation/        # Procedural & agentic env gen, USD lowering, asset rendering
│   ├── asset_thumbnail_rendering_and_containers.md
│   ├── asset_thumbnails_vs_scene_rendering.md
│   ├── env_gen_summary_v01.md
│   └── README.md
├── policy_and_embodiments/        # Policy evaluation, robot embodiments, grasp transfer, diagnostics
│   ├── c1_calibrated_grasp_reference_gate_results.md
│   ├── c1_controller_assistance_results.md
│   ├── c1_reference_control_and_transfer_strategy.md
│   ├── g1_humanoid_vlm_agentic_debugging_and_remediation.md
│   ├── run_out_tokens-2026-09-06.md
│   └── README.md
├── plan04_and_hermes/             # Plan 04 implementation, Neo4j database, Hermes autonomous agent
│   ├── database-workflow-challenges_01.md
│   ├── development_state_10-16-2026.md
│   ├── g3_execution_blockers_and_root_cause_analysis.md
│   ├── hermes_architectural_mismatch.md
│   ├── hermes_plan_04_review.md
│   ├── recommendation_hermes_development.md
│   ├── retained_numeric_reassessment_architecture.md
│   ├── session_memory.md
│   └── README.md
├── event_mapping/                 # Domain-Driven Design (DDD), Event Modeling, GraphQL mappings
│   ├── event-mapping-refactoring_v03_notes.md
│   ├── event_mapping_code_references.md
│   └── README.md
└── infrastructure_and_tooling/    # Devcontainers, Git submodules, teleop datasets, LeRobot tooling
    ├── dataset_cheatsheet.md
    ├── study_devcontainer.md
    ├── submodule_shenanigans.md
    └── README.md
```

---

## Master Table of Contents

| Document | Topic Folder | Creation Date (YYYY-MM-DD) | Status | Subsystem | Purpose / Focus |
|:---|:---|:---:|:---|:---|:---|
| [asset_thumbnail_rendering_and_containers.md](environment_generation/asset_thumbnail_rendering_and_containers.md) | `environment_generation` | `2026-09-15` | Operational Ref | Omniverse RTX / Assets | Parallel GPU asset thumbnail rendering & container catalog |
| [asset_thumbnails_vs_scene_rendering.md](environment_generation/asset_thumbnails_vs_scene_rendering.md) | `environment_generation` | `2026-09-16` | Architectural Ref | Omniverse Nucleus | In-situ simulation rendering vs standalone Nucleus thumbnails |
| [env_gen_summary_v01.md](environment_generation/env_gen_summary_v01.md) | `environment_generation` | `2026-09-18` | Architecture Spec | Agentic Env Gen | v0.1 pipeline: prompt parsing, formal verification, PhysX settle |
| [run_out_tokens-2026-09-06.md](policy_and_embodiments/run_out_tokens-2026-09-06.md) | `policy_and_embodiments` | `2026-09-06` | Incident Log | Policy Evaluation | 20-episode rollout kinematics & gripper timing under token expiry |
| [c1_reference_control_and_transfer_strategy.md](policy_and_embodiments/c1_reference_control_and_transfer_strategy.md) | `policy_and_embodiments` | `2026-09-07` | Strategy Rec | Policy Transfer / DCRG | Baseline reference controls and transfer requirements for C1 |
| [c1_calibrated_grasp_reference_gate_results.md](policy_and_embodiments/c1_calibrated_grasp_reference_gate_results.md) | `policy_and_embodiments` | `2026-09-08` | Empirical Report | Grasp Transfer Gate | Reference gate execution failure autopsy at replay step 17 |
| [c1_controller_assistance_results.md](policy_and_embodiments/c1_controller_assistance_results.md) | `policy_and_embodiments` | `2026-09-08` | Empirical Report | Runtime Assistance | Downward residual & delayed finger commands for policy transfer |
| [g1_humanoid_vlm_agentic_debugging_and_remediation.md](policy_and_embodiments/g1_humanoid_vlm_agentic_debugging_and_remediation.md) | `policy_and_embodiments` | `2026-09-25` | Diagnostic Autopsy | Embodiment Diagnostics | Unitree G1 humanoid tabletop failure autopsy & depth auditing |
| [submodule_shenanigans.md](infrastructure_and_tooling/submodule_shenanigans.md) | `infrastructure_and_tooling` | `2026-09-10` | Developer Guide | Git Tooling | Mental model, fork tracking, and recovery for submodules |
| [dataset_cheatsheet.md](infrastructure_and_tooling/dataset_cheatsheet.md) | `infrastructure_and_tooling` | `2026-09-12` | Cheatsheet | Teleop / LeRobot | HDF5 to LeRobot conversion, storage paths, rerun visualization |
| [study_devcontainer.md](infrastructure_and_tooling/study_devcontainer.md) | `infrastructure_and_tooling` | `2026-09-14` | Engineering Study | Devcontainer Infra | Working directory fixes, host port conflicts (5555–5558) |
| [hermes_architectural_mismatch.md](plan04_and_hermes/hermes_architectural_mismatch.md) | `plan04_and_hermes` | `2026-09-21` | Problem Statement | Workflow / Database | Conflation of asset registration with simulation import graph |
| [event-mapping-refactoring_v03_notes.md](event_mapping/event-mapping-refactoring_v03_notes.md) | `event_mapping` | `2026-09-21` | Developer Notes | Event Modeling / DDD | DDD refactoring, command-vs-read models, GraphQL strategy |
| [event_mapping_code_references.md](event_mapping/event_mapping_code_references.md) | `event_mapping` | `2026-09-21` | Code Inventory | Baseline Inventory | Source references and proof boundaries against baseline 45a0b26466 |
| [database-workflow-challenges_01.md](plan04_and_hermes/database-workflow-challenges_01.md) | `plan04_and_hermes` | `2026-09-22` | Architectural Analysis | Plan 04 / Neo4j | Validating Neo4j persistence and live simulation contracts |
| [hermes_plan_04_review.md](plan04_and_hermes/hermes_plan_04_review.md) | `plan04_and_hermes` | `2026-09-22` | Architecture Review | Plan 04 Execution | Breakdown of Plan 04 phases (P0–P6) and multi-agent strategy |
| [session_memory.md](plan04_and_hermes/session_memory.md) | `plan04_and_hermes` | `2026-09-23` | Living Ledger | Cross-Agent Memory | Living checkpoint ledger, PhysX tokens, and freeze hashes |
| [recommendation_hermes_development.md](plan04_and_hermes/recommendation_hermes_development.md) | `plan04_and_hermes` | `2026-09-24` | Strategy Rec | Hermes Acceleration | Fast-track execution plan reducing delivery from 30 to 4-6 days |
| [retained_numeric_reassessment_architecture.md](plan04_and_hermes/retained_numeric_reassessment_architecture.md) | `plan04_and_hermes` | `2026-09-26` | Architecture Ref | GraphQL Schema 5 | Offline mathematical consistency & reassessWorkflowNumeric API |
| [g3_execution_blockers_and_root_cause_analysis.md](plan04_and_hermes/g3_execution_blockers_and_root_cause_analysis.md) | `plan04_and_hermes` | `2026-09-28` | Postmortem Report | Empirical Campaign | Postmortem of EXECUTION_STOPPED_NO_G3_ACCEPTANCE halt |
| [development_state_10-16-2026.md](plan04_and_hermes/development_state_10-16-2026.md) | `plan04_and_hermes` | `2026-10-16` | State Snapshot | Repository Overview | State-of-repo snapshot: G3 recovery, unit tests, local inference |

---

## Chronological Index (Timeline of Research & Engineering)

All dates follow the standard ISO 8601 format: **`YYYY-MM-DD`** (Year-Month-Day). Understanding when each note was authored provides crucial context on the historical state of the codebase:

1. **`2026-09-06`** — [run_out_tokens-2026-09-06.md](policy_and_embodiments/run_out_tokens-2026-09-06.md): Diagnostic rollout analysis when OpenRouter token limits halted an evaluation run.
2. **`2026-09-07`** — [c1_reference_control_and_transfer_strategy.md](policy_and_embodiments/c1_reference_control_and_transfer_strategy.md): Defining reference baseline controls before exploring further environment search spaces.
3. **`2026-09-08`** — [c1_calibrated_grasp_reference_gate_results.md](policy_and_embodiments/c1_calibrated_grasp_reference_gate_results.md): Execution of the C1 calibrated grasp reference gate and replay step 17 blocker autopsy.
4. **`2026-09-08`** — [c1_controller_assistance_results.md](policy_and_embodiments/c1_controller_assistance_results.md): Downward arm residual and delayed finger command assistance tests for zero-shot transfer.
5. **`2026-09-10`** — [submodule_shenanigans.md](infrastructure_and_tooling/submodule_shenanigans.md): Submodule mental model, personal forks, and detached HEAD recovery guide.
6. **`2026-09-12`** — [dataset_cheatsheet.md](infrastructure_and_tooling/dataset_cheatsheet.md): Teleoperation dataset management, HDF5-to-LeRobot conversion, and rerun visualizers.
7. **`2026-09-14`** — [study_devcontainer.md](infrastructure_and_tooling/study_devcontainer.md): Devcontainer optimization, ZeroMQ server port forwarding, and entrypoint path fixes.
8. **`2026-09-15`** — [asset_thumbnail_rendering_and_containers.md](environment_generation/asset_thumbnail_rendering_and_containers.md): GPU parallel asset thumbnail generator and container inventory.
9. **`2026-09-16`** — [asset_thumbnails_vs_scene_rendering.md](environment_generation/asset_thumbnails_vs_scene_rendering.md): Architectural analysis of Nucleus thumbnail caching vs live simulation camera pipelines.
10. **`2026-09-18`** — [env_gen_summary_v01.md](environment_generation/env_gen_summary_v01.md): First consolidated architecture specification for agentic environment generation and self-healing.
11. **`2026-09-21`** — [hermes_architectural_mismatch.md](plan04_and_hermes/hermes_architectural_mismatch.md): Problem analysis on conflating asset registration mechanisms with simulation import graphs.
12. **`2026-09-21`** — [event-mapping-refactoring_v03_notes.md](event_mapping/event-mapping-refactoring_v03_notes.md): Reflections on Domain-Driven Design, command-query separation, and EventStorming.
13. **`2026-09-21`** — [event_mapping_code_references.md](event_mapping/event_mapping_code_references.md): Baseline source inventory and test proof boundary tracing.
14. **`2026-09-22`** — [database-workflow-challenges_01.md](plan04_and_hermes/database-workflow-challenges_01.md): Deep-dive into database-workflow integration and live simulation contracts.
15. **`2026-09-22`** — [hermes_plan_04_review.md](plan04_and_hermes/hermes_plan_04_review.md): Detailed phase-by-phase architectural breakdown of Plan 04 (P0 through P6).
16. **`2026-09-23`** — [session_memory.md](plan04_and_hermes/session_memory.md): Living cross-agent checkpoint and resource allocation ledger.
17. **`2026-09-24`** — [recommendation_hermes_development.md](plan04_and_hermes/recommendation_hermes_development.md): Fast-track acceleration plan for autonomous Hermes development.
18. **`2026-09-25`** — [g1_humanoid_vlm_agentic_debugging_and_remediation.md](policy_and_embodiments/g1_humanoid_vlm_agentic_debugging_and_remediation.md): Failure autopsy of G1 humanoid tabletop pick-and-place manipulation.
19. **`2026-09-26`** — [retained_numeric_reassessment_architecture.md](plan04_and_hermes/retained_numeric_reassessment_architecture.md): Retained numeric reassessment architecture, GraphQL client documents, and math checks.
20. **`2026-09-28`** — [g3_execution_blockers_and_root_cause_analysis.md](plan04_and_hermes/g3_execution_blockers_and_root_cause_analysis.md): Postmortem of the G3 empirical campaign execution halt and schema mismatches.
21. **`2026-10-16`** — [development_state_10-16-2026.md](plan04_and_hermes/development_state_10-16-2026.md): Complete repository-wide status snapshot, test coverage, and local inference hardening.

---

## Detailed Topic Guides

### 1. Environment Generation & Simulation Rendering (`environment_generation/`)

This directory contains specifications and architectural notes on how IsaacLab-Arena creates, validates, and visualizes simulation scenes:

- **[Asset Thumbnail Rendering & Container Catalog Reference](environment_generation/asset_thumbnail_rendering_and_containers.md)** (`2026-09-15`):
  Explains how to use `isaaclab_arena_examples/tools/render_asset_thumbnails.py` to batch-render registered environment assets into PNG thumbnails using parallel GPU headless rendering. Provides a catalog of standard bins, boxes, and trays (`steel_container`, `grey_storage_bin`, `baking_tray`, `cardboard_box`, etc.) with their canonical asset IDs.
  *Target Audience*: Developers adding new 3D assets or configuring UI object pickers.

- **[Asset Thumbnails vs. Scene Preview Rendering in IsaacLab-Arena & Omniverse](environment_generation/asset_thumbnails_vs_scene_rendering.md)** (`2026-09-16`):
  Distinguishes between *In-Situ Scene Rendering* (camera sensors attached to live simulation stages rendering via RTX Hydra delegates) and *Standalone Asset Thumbnail Generation* (Omniverse Nucleus thumbnail service caching 2D previews in `.thumbs/`). Explains how Nucleus generates asset thumbnails upon USD upload and how to avoid cache invalidation traps.
  *Target Audience*: Rendering engineers and developers debugging missing or black camera frames.

- **[IsaacLab-Arena: End-to-End Agentic Environment Generation & Self-Healing Workflow (v0.1)](environment_generation/env_gen_summary_v01.md)** (`2026-09-18`):
  High-level architectural overview of the v0.1 self-healing environment generation pipeline. Traces how user prompts are parsed by an LLM into an `ArenaEnvGraphSpec`, checked by the `SpatialGeometricOracle`, relaxed with factor graphs, settled in PhysX, audited by a multimodal VLM critic, and iteratively refined.
  *Target Audience*: Anyone seeking an architectural overview of agentic environment synthesis.

---

### 2. Policy Evaluation & Embodiments (`policy_and_embodiments/`)

This directory covers robot embodiment dynamics, policy evaluation rollouts, grasp transfer experiments, and failure diagnoses:

- **[C1: Reference Controls Before Further Environment Search](policy_and_embodiments/c1_reference_control_and_transfer_strategy.md)** (`2026-09-07`):
  Recommends validating baseline reference controls prior to running expensive combinatorial environment searches. Examines early DCRG (Dynamic Constraint Relaxation & Grounding) pilot rollouts and establishes criteria for evaluating policy transferability across varied fixtures.
  *Target Audience*: Reinforcement learning researchers and policy evaluation engineers.

- **[C1 Calibrated Grasp — Reference Gate Execution Results](policy_and_embodiments/c1_calibrated_grasp_reference_gate_results.md)** (`2026-09-08`):
  Empirical report documenting the reference gate execution on the C1 calibrated grasp benchmark with frozen Spatial-Forcing G1 policy. Analyzes why native-action replay failed predeclared fidelity limits at replay step 17 and records the blocking failure mode.
  *Target Audience*: Researchers benchmarking imitation learning and action chunk replay fidelity.

- **[C1 Controller-Assistance Experiment Results](policy_and_embodiments/c1_controller_assistance_results.md)** (`2026-09-08`):
  Empirical results testing whether simple runtime assistance heuristics—such as injecting a small downward arm force residual or delaying finger closure by a fixed delta—allow a frozen policy to succeed in unseen visual/geometric environments without retraining.
  *Target Audience*: Control engineers designing runtime safety and transfer wrappers.

- **[Run Out of Open Router Tokens — Rollout Diagnostics](policy_and_embodiments/run_out_tokens-2026-09-06.md)** (`2026-09-06`):
  A diagnostic incident report examining a 20-episode rollout run that terminated when LLM API tokens ran out. Provides frame-by-frame analysis of apple-grasp kinematics, gripper contact timing, and closure radius boundaries.
  *Target Audience*: Developers analyzing grasp affordances and episode evaluation failure modes.

- **[Unitree G1 Humanoid Tabletop Manipulation: Agentic VLM Failure Autopsy & Embodiment Diagnostics](policy_and_embodiments/g1_humanoid_vlm_agentic_debugging_and_remediation.md)** (`2026-09-25`):
  Comprehensive failure autopsy of the Unitree G1 humanoid tabletop pick-and-place task (`nvidia/GN1x-Tuned-G1-PickPlace-PPO`). Dissects severe camera occlusion caused by the G1 torso pitch, whole-body controller (WBC) arm reachability bottlenecks, and outlines remediation using depth spatial auditing.
  *Target Audience*: Humanoid robotics engineers, VLM critic developers, and whole-body control specialists.

---

### 3. Plan 04 Implementation & Hermes Autonomous Agent (`plan04_and_hermes/`)

This directory documents Plan 04, the major effort to unify repository persistence, Neo4j graph storage, GraphQL APIs, and autonomous coding agent execution:

- **[Hermes Architectural Mismatch: Asset Registration vs Runtime Import Graph](plan04_and_hermes/hermes_architectural_mismatch.md)** (`2026-09-21`):
  Exposes the architectural confusion that halted Hermes agent development: conflating the static asset catalog metadata schema with Isaac Sim\'s dynamic runtime Python import graph. Clarifies API boundaries between workflow orchestration and database storage.
  *Target Audience*: Backend developers and autonomous agent developers building database wrappers.

- **[Database-Workflow Interaction Challenges & Architectural Validation](plan04_and_hermes/database-workflow-challenges_01.md)** (`2026-09-22`):
  Deep-dive into Plan 04 Goal A (Test `E1`), analyzing why validating Neo4j transaction lifecycles concurrently with headless GPU physics simulation is uniquely prone to deadlocks, memory leaks, and serialization mismatches.
  *Target Audience*: Database architects and workflow engine developers.

- **[Plan 04 Architecture & Hermes Multi-Agent Action Plan Review](plan04_and_hermes/hermes_plan_04_review.md)** (`2026-09-22`):
  Detailed phase-by-phase breakdown of Plan 04 across all 7 phases (P0: Prerequisites, P1: Schema, P2: DB Service, P3: API Client, P4: Workflow Engine, P5: Test Suites, P6: Verification). Reviews Hermes\'s autonomous multi-agent division of labor.
  *Target Audience*: Engineering leads, project managers, and autonomous agent orchestrators.

- **[Living Session Memory & Plan 04 Checkpoint Ledger](plan04_and_hermes/session_memory.md)** (`2026-09-23`):
  The central, living cross-agent state journal. Logs exact resource allocation limits (memory, threads, process quotas), PhysX admission tokens, immutable freeze hashes, and autonomous restart checkpoints across agents.
  *Target Audience*: AI coding agents and engineers resuming interrupted development sessions.

- **[Recommendation for Hermes Acceleration: Plan 04 Fast-Track Execution](plan04_and_hermes/recommendation_hermes_development.md)** (`2026-09-24`):
  Antigravity\'s architectural recommendation outlining how to accelerate Plan 04 delivery from a 15–30 day timeline to 4–6 working days by applying strict supervisor guardrails, eliminating unnecessary mock test churn, and focusing on native execution boundaries.
  *Target Audience*: Project leads and agents designing multi-agent software development workflows.

- **[Retained Numeric Reassessment Architecture & GraphQL Client Documents](plan04_and_hermes/retained_numeric_reassessment_architecture.md)** (`2026-09-26`):
  Architectural guide for Schema 5 numeric reassessment. Explains the purpose of `reassessWorkflowNumeric`, how GraphQL client queries are registered in `DOCUMENTS`, and why offline mathematical re-verification of simulation metrics is required.
  *Target Audience*: GraphQL API developers and verification engineers.

- **[P04-I03-G3 Execution Blockers and Root Cause Analysis](plan04_and_hermes/g3_execution_blockers_and_root_cause_analysis.md)** (`2026-09-28`):
  Postmortem analysis of the `EXECUTION_STOPPED_NO_G3_ACCEPTANCE` halt during empirical campaign execution. Identifies schema validation errors and asset lookup failures that blocked execution, providing remediation steps.
  *Target Audience*: CI/CD engineers and developers maintaining empirical test pipelines.

- **[Development State — 2026-10-16 Snapshot](plan04_and_hermes/development_state_10-16-2026.md)** (`2026-10-16`):
  A comprehensive state-of-the-repository overview covering all active workstreams: CPU proxy recovery, 173 unit tests passing, container and test suites, local inference milestones M1-M6, and upcoming engineering priorities.
  *Target Audience*: Anyone onboarding to or catching up on the current state of IsaacLab-Arena.

---

### 4. Event Mapping & Domain-Driven Design (`event_mapping/`)

This directory documents the domain modeling, event mapping, and DDD architectural refactoring of the platform:

- **[Notes on Event Mapping Refactoring & Domain-Driven Design](event_mapping/event-mapping-refactoring_v03_notes.md)** (`2026-09-21`):
  Informal engineering notes reflecting on the application of Domain-Driven Design (DDD) and Event Modeling to IsaacLab-Arena. Discusses command-query separation, entity identity ownership, and why frontend integration is deferred until backend event contracts are formally verified.
  *Target Audience*: Software architects and developers working on event-driven simulation orchestration.

- **[Event Mapping — Source References and Proof Boundaries](event_mapping/event_mapping_code_references.md)** (`2026-09-21`):
  A code reference inventory mapping relevant source files, tools, and callers to their respective test proof boundaries against repository baseline commit `45a0b26466`.
  *Target Audience*: Engineers reviewing code changes and verifying proof coverage against historical baselines.

---

### 5. Infrastructure, Tooling & Datasets (`infrastructure_and_tooling/`)

This directory covers devcontainers, Git submodules, and teleoperation dataset conversion tooling:

- **[Git Submodule Shenanigans & Fork Management Guide](infrastructure_and_tooling/submodule_shenanigans.md)** (`2026-09-10`):
  The definitive guide to Git submodule architecture in IsaacLab-Arena. Explains the relationship between parent repositories and vendored dependencies (`boredengineering/Isaac-GR00T` and `boredengineering/IsaacLab`), how to push changes to personal forks, and step-by-step commands to recover from detached `HEAD` states.
  *Target Audience*: All developers working with submodules or contributing changes to IsaacLab / Isaac-GR00T.

- **[Dataset Cheat Sheet: Conversion, LeRobot Format & Visualization](infrastructure_and_tooling/dataset_cheatsheet.md)** (`2026-09-12`):
  Operational cheat sheet for managing teleoperation datasets. Covers path mapping between host and Docker containers, running `convert_hdf5_to_lerobot.py` to produce LeRobot-compatible Parquet files, and inspecting episode trajectories with `rerun` and web visualizers.
  *Target Audience*: Teleoperation operators, data engineers, and imitation learning practitioners.

- **[Study on Devcontainer Optimization & Multi-Service Port Management](infrastructure_and_tooling/study_devcontainer.md)** (`2026-09-14`):
  Troubleshooting log resolving devcontainer stability issues. Documents fixing the working directory in `run_gr00t_server.sh` (`-w /workspace/gr00t`) and resolving host port contention across ports 5555–5558 for ZeroMQ communication.
  *Target Audience*: DevOps engineers and contributors setting up local devcontainer environments.

---

## Quick Lookup Matrix: Find What You Need

Use this cross-reference matrix to locate the note most relevant to your current challenge:

| If you are trying to... | Consult this Note | Folder |
|:---|:---|:---|
| Render asset thumbnails or find available container assets | [asset_thumbnail_rendering_and_containers.md](environment_generation/asset_thumbnail_rendering_and_containers.md) | `environment_generation` |
| Understand how Omniverse caches asset previews vs simulation cameras | [asset_thumbnails_vs_scene_rendering.md](environment_generation/asset_thumbnails_vs_scene_rendering.md) | `environment_generation` |
| Understand the end-to-end agentic environment generation flow | [env_gen_summary_v01.md](environment_generation/env_gen_summary_v01.md) | `environment_generation` |
| Debug Unitree G1 humanoid tabletop manipulation or VLM occlusion | [g1_humanoid_vlm_agentic_debugging_and_remediation.md](policy_and_embodiments/g1_humanoid_vlm_agentic_debugging_and_remediation.md) | `policy_and_embodiments` |
| Implement runtime controller assistance (downward residual, finger delay) | [c1_controller_assistance_results.md](policy_and_embodiments/c1_controller_assistance_results.md) | `policy_and_embodiments` |
| Review grasp transfer gates and replay fidelity limits | [c1_calibrated_grasp_reference_gate_results.md](policy_and_embodiments/c1_calibrated_grasp_reference_gate_results.md) | `policy_and_embodiments` |
| Understand Plan 04 database-workflow interaction and Neo4j contracts | [database-workflow-challenges_01.md](plan04_and_hermes/database-workflow-challenges_01.md) | `plan04_and_hermes` |
| Resolve Hermes agent asset registration vs import graph errors | [hermes_architectural_mismatch.md](plan04_and_hermes/hermes_architectural_mismatch.md) | `plan04_and_hermes` |
| Accelerate autonomous coding agent delivery (Plan 04 rules) | [recommendation_hermes_development.md](plan04_and_hermes/recommendation_hermes_development.md) | `plan04_and_hermes` |
| Retrieve active session checkpoints, PhysX tokens, or freeze hashes | [session_memory.md](plan04_and_hermes/session_memory.md) | `plan04_and_hermes` |
| Get a high-level snapshot of overall repository development state | [development_state_10-16-2026.md](plan04_and_hermes/development_state_10-16-2026.md) | `plan04_and_hermes` |
| Convert raw HDF5 teleop recordings to LeRobot datasets | [dataset_cheatsheet.md](infrastructure_and_tooling/dataset_cheatsheet.md) | `infrastructure_and_tooling` |
| Resolve Git submodule issues, detached HEAD, or commit to forks | [submodule_shenanigans.md](infrastructure_and_tooling/submodule_shenanigans.md) | `infrastructure_and_tooling` |
| Fix devcontainer port conflicts (ZeroMQ ports 5555–5558) | [study_devcontainer.md](infrastructure_and_tooling/study_devcontainer.md) | `infrastructure_and_tooling` |

---

## Maintenance Guidelines for New Notes

When authoring a new note in `.agents/references/notes/`:

1. **Place in the Appropriate Topical Folder**:
   - `environment_generation/`: Scene generation, USD, rendering, asset catalogs.
   - `policy_and_embodiments/`: Robot policies, humanoid/arm dynamics, grasp benchmarks, rollout logs.
   - `plan04_and_hermes/`: Database contracts, Neo4j, Plan 04 phases, session memories, postmortems.
   - `event_mapping/`: Domain modeling, EventStorming, GraphQL contracts, code inventories.
   - `infrastructure_and_tooling/`: Docker, devcontainers, submodules, datasets, scripts.

2. **Include Standard Metadata Header**:
   Always prepend YAML frontmatter and a Markdown metadata callout block:
   ```markdown
   ---
   title: "<Note Title>"
   category: "<Topical Category>"
   date_created: "YYYY-MM-DD"  # ISO 8601 standard format
   last_updated: "YYYY-MM-DD"  # ISO 8601 standard format
   status: "<Status: Reference | Empirical Report | Architecture | Postmortem>"
   subsystem: "<Primary Subsystem>"
   tags: ["tag1", "tag2"]
   ---

   > **Topic / Category**: <Topical Category>  
   > **Date of Creation (YYYY-MM-DD)**: YYYY-MM-DD | **Last Updated (YYYY-MM-DD)**: YYYY-MM-DD  
   > **Status**: <Status>  
   > **Subsystem**: <Primary Subsystem>  
   > **Summary**: <1-2 sentence executive summary>
   ```

3. **Repository-Relative Link Invariant**:
   Never hardcode absolute paths or `file:///` URIs. Use repository-relative links:
   - Root links from subfolders: `../../../../<path_from_repo_root>`
   - Links to sibling notes: `../<other_folder>/<note>.md`
   - Links within the same folder: `<sibling_note>.md`

4. **Update This Index**:
   Add the new note to the [Master Table of Contents](#master-table-of-contents), [Chronological Index](#chronological-index-timeline-of-research--engineering), and its subfolder `README.md`.
