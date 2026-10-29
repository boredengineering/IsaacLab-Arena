# Policy Evaluation & Embodiments

Empirical rollout diagnostics, embodiment reachability studies, and controller assistance experiments across Unitree G1 and Franka Panda.

[← Back to Master Notes Index](../README.md)

---

## Documents in this Topic

| Document | Creation Date (YYYY-MM-DD) | Status | Subsystem | Summary |
|:---|:---:|:---|:---|:---|
| [Run Out of Open Router Tokens — Rollout Diagnostics](run_out_tokens-2026-09-06.md) | `2026-09-06` | Incident Log | Policy Evaluation | Empirical 20/20 episode rollout diagnostics analyzing apple grasp closing kinematics and gripper reopening behavior when OpenRouter API tokens expired. |
| [C1: Reference Controls Before Further Environment Search](c1_reference_control_and_transfer_strategy.md) | `2026-09-07` | Strategy Rec | Policy Transfer / DCRG | Strategy recommendation for baseline reference controls before further environment search; analyzes DCRG pilot on C1 task. |
| [C1 Calibrated Grasp — Reference Gate Execution Results](c1_calibrated_grasp_reference_gate_results.md) | `2026-09-08` | Empirical Report | Grasp Transfer Gate | Reference gate execution report for C1 calibrated grasp using frozen Spatial-Forcing G1 policy; failure autopsy at replay step 17. |
| [C1 Controller-Assistance Experiment Results](c1_controller_assistance_results.md) | `2026-09-08` | Empirical Report | Runtime Assistance | Evaluation of downward arm residuals and delayed finger commands to transfer frozen policy to unseen C1/v32 scene without changing physics. |
| [Unitree G1 Humanoid Tabletop Manipulation: Agentic VLM Failure Autopsy & Embodiment Diagnostics](g1_humanoid_vlm_agentic_debugging_and_remediation.md) | `2026-09-25` | Diagnostic Autopsy | Embodiment Diagnostics | Detailed autopsy of G1 humanoid tabletop manipulation failures: camera occlusion, WBC reachability limits, and depth spatial auditing. |

---

## Topic Context & Navigation

For cross-topic searches, chronological timelines, and complete document summaries, refer to the [Master Notes Library README](../README.md).
