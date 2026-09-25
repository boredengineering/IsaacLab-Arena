# Architectural & Operational Plans Index

This directory contains planning, review, and protocol documents organized by engineering domain.

## Directory Structure

### 1. [`event_mapping/`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/event_mapping)
Execution owner, registered workflow lifecycle, and event mapping refactoring plans (Plan 01 through Plan 04), reviews, approvals, and designs.
- [`event-mapping-refactoring_plan_04.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/event_mapping/event-mapping-refactoring_plan_04.md) — Active plan for Milestones 1–4 (live generation, native validation, visual assessment, repair, and policy integration).
- [`event-mapping-plan04-operational-synthesis.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/event_mapping/event-mapping-plan04-operational-synthesis.md) — Executive operational synthesis, empirical checkpoints, operator invariants, and 5-stage roadmap.
- [`event-mapping-refactoring_plan_04-review.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/event_mapping/event-mapping-refactoring_plan_04-review.md) — Independent architecture and bounds review for Plan 04.
- [`event-mapping-plan04-s2-initialization-approval.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/event_mapping/event-mapping-plan04-s2-initialization-approval.md) — Boundary approval for S2 simulation initialization.
- [`event-mapping-registration-only-design.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/event_mapping/event-mapping-registration-only-design.md) — Registration-only protocol and lifecycle design.
- Earlier iterations: [`plan_01.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/event_mapping/event-mapping-refactoring_plan_01.md), [`plan_02.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/event_mapping/event-mapping-refactoring_plan_02.md), [`plan_03.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/event_mapping/event-mapping-refactoring_plan_03.md), and associated reviews.

### 2. [`dashboard_cli_workflow_parity/`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/dashboard_cli_workflow_parity)
Contracts, evidence, and audits establishing operational parity between CLI and Web API/Dashboard surfaces.
- [`dashboard_cli_workflow_parity.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/dashboard_cli_workflow_parity/dashboard_cli_workflow_parity.md) — Top-level parity specification.
- [`research-stack-implementation-handoff.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/dashboard_cli_workflow_parity/research-stack-implementation-handoff.md) — Canonical living handoff for research stack implementation.
- [`endpoint-contract-plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/dashboard_cli_workflow_parity/endpoint-contract-plan.md), [`research-stack-contracts.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/dashboard_cli_workflow_parity/research-stack-contracts.md), etc.

### 3. [`g1_manipulation_and_policy/`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/g1_manipulation_and_policy)
Unitree G1 humanoid manipulation, monocular camera calibration, tabletop task remediation, and policy transfer plans.
- [`g1_policy_transfer_implementation_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/g1_manipulation_and_policy/g1_policy_transfer_implementation_plan.md) — Policy transfer execution architecture.
- [`g1_policy_transfer_and_height_invariance_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/g1_manipulation_and_policy/g1_policy_transfer_and_height_invariance_plan.md) — Height invariance and transfer robustness.
- [`g1_tabletop_apple_remediation_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/g1_manipulation_and_policy/g1_tabletop_apple_remediation_plan.md) — Tabletop pick autopsy and remediation.
- [`g1_monocular_depth_and_camera_pitch_debug.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/g1_manipulation_and_policy/g1_monocular_depth_and_camera_pitch_debug.md) — Depth and camera pitch debugging.
- [`g1_pick_success_phases.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/g1_manipulation_and_policy/g1_pick_success_phases.md), [`g1_manipulation_trajectory_and_meta_learning_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/g1_manipulation_and_policy/g1_manipulation_trajectory_and_meta_learning_plan.md).

### 4. [`spatial_reasoning_and_vision/`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/spatial_reasoning_and_vision)
Spatial forcing, depth alignment, VLA spatial reasoning, closed-loop USD traversal, and VLM visual verification.
- [`Evaluating VLA Spatial Reasoning Methods.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/spatial_reasoning_and_vision/Evaluating%20VLA%20Spatial%20Reasoning%20Methods.md) — Evaluation of spatial reasoning in vision-language-action models.
- [`da3_spatial_forcing_pipeline_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/spatial_reasoning_and_vision/da3_spatial_forcing_pipeline_plan.md) — DA3 spatial forcing pipeline.
- [`spatial_forcing_da3_metric_alignment_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/spatial_reasoning_and_vision/spatial_forcing_da3_metric_alignment_plan.md) — Metric alignment specification.
- [`closed_loop_usd_traversal_and_vlm_vision_verification_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/spatial_reasoning_and_vision/closed_loop_usd_traversal_and_vlm_vision_verification_plan.md) — Visual inspection and USD scene traversal.
- [`geometry_supervision_evidence_repair_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/spatial_reasoning_and_vision/geometry_supervision_evidence_repair_plan.md), [`depth_alignment_integration_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/spatial_reasoning_and_vision/depth_alignment_integration_plan.md), [`autonomous_scene_reasoning_and_vlm_feedback_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/spatial_reasoning_and_vision/autonomous_scene_reasoning_and_vlm_feedback_plan.md).

### 5. [`dcrg_and_grasp_transfer/`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/dcrg_and_grasp_transfer)
Dynamic Causal Reasoning Graph (DCRG) telemetry, RL fidelity, and calibrated grasp transfer protocols.
- [`c1_calibrated_grasp_and_graph_guided_transfer_experiment.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/dcrg_and_grasp_transfer/c1_calibrated_grasp_and_graph_guided_transfer_experiment.md) — C1 calibrated grasp transfer.
- [`c1_calibrated_grasp_test_protocol.json`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/dcrg_and_grasp_transfer/c1_calibrated_grasp_test_protocol.json) — Protocol machine specification.
- [`dcrg_rl_fidelity_and_epistemic_telemetry_repair_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/dcrg_and_grasp_transfer/dcrg_rl_fidelity_and_epistemic_telemetry_repair_plan.md) — Telemetry repair plan.
- [`dcrg_c1_implementation_review.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/dcrg_and_grasp_transfer/dcrg_c1_implementation_review.md).

### 6. [`workbench_and_ui/`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/workbench_and_ui)
Frontend architecture, TanStack Query/Router agentic workbench, graph explorer, and localhost session lifecycle.
- [`tanstack_agentic_workbench_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/workbench_and_ui/tanstack_agentic_workbench_plan.md) — Workbench UI architecture.
- [`tanstack_graph_explorer.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/workbench_and_ui/tanstack_graph_explorer.md) — Graph visualizer implementation.
- [`workbench_localhost_session_fix.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/workbench_and_ui/workbench_localhost_session_fix.md), [`asset_visualization_recovery.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/workbench_and_ui/asset_visualization_recovery.md).

### 7. [`infrastructure_and_automation/`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/infrastructure_and_automation)
Autonomous evaluation flywheels and devcontainer tooling.
- [`autonomous_evaluation_self_healing_flywheel_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/infrastructure_and_automation/autonomous_evaluation_self_healing_flywheel_plan.md) — Self-healing evaluation loop.
- [`codex_devcontainer_integration_plan.md`](file:///workspaces/IsaacLab-Arena/.agents/references/plans/infrastructure_and_automation/codex_devcontainer_integration_plan.md) — Container integration protocol.

### 8. [`plan04_implementation/`](plan04_implementation/README.md)
Bounded implementation work packages, approval boundaries, acceptance gates and proposed goal prompts for Plan 04. The existing research-stack handoff remains the owner of verified runtime status.
- [Work-package index and current position](plan04_implementation/README.md) — What is blocked, what is proposed next, and how to add another plan.
- [P04-I01: Native integration defects and bounded revalidation](plan04_implementation/01-native-integration-defects.md) — Repair scratch/artifact separation and constructor diagnostics before any newly authorized native launch. Proposed, not approved for execution.
- [P04-GUIDE-01: How far to finish Plan 04 (Orchestrator parity guide)](plan04_implementation/how-far-to-finish-plan04.md) — Executive guide and Mermaid architecture comparing external vs application orchestrator, root cause breakdown, and punch list.
- [New work-package template](plan04_implementation/_template.md) — Scope, authority, evidence, gates, goal prompt and closeout.
