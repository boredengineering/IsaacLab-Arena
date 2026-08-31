# Session Memory: Active Inference & Robot Vision-Language-Action (VLA) Calibration

## 1. DROID / Franka Geometric & Visual Standoff Constants
* **Robot Base Origin**: `[-0.55, 0.0, 0.0]` (Franka mounted on DROID stand).
* **Table-to-Arm Proximity**:
  * In real DROID physical setups, the Franka base is mounted immediately adjacent to the table edge ($10\text{ cm} - 15\text{ cm}$ gap).
  * If the table origin is $(0.0, 0.0, 0.0)$, the front table edge begins at $X \approx -0.40\text{ m}$. Placing objects deep into the table ($X > 0.0\text{ m}$) violates physical reach and visual line-of-sight.
* **VLA Fine-Tuning Distribution & Near-Field Inductive Bias**:
  * **VLA Training Distribution**: VLA models (`GR00T-N1.6-DROID`, OpenVLA, Octo, $\pi_0$) are trained exclusively on human teleoperated demonstrations where objects are located strictly in the **near-field manipulation zone** ($20\text{ cm} - 45\text{ cm}$ directly in front of the robot arm).
  * **Visual Perception Limit**: Franka's downward-angled camera ($45^\circ$) only captures $X_{\text{world}} \in [-0.35, 0.05]\text{ m}$ ($20\text{ cm} - 50\text{ cm}$ in front of base). Anything further is outside the camera FOV, and the VLA cannot pick what it cannot see.
  * **Spatial Constraint Invariant**: All manipulands, target receptacles, and interactive objects must be placed within $d \in [0.25, 0.45]\text{ m}$ ($X \in [-0.30, -0.10]\text{ m}, Y \in [-0.20, 0.20]\text{ m}$) relative to the robot base.

## 2. Foundation Policy Server (Isaac-GR00T)
* **Architecture**: `nvidia/GR00T-N1.6-DROID` with `AlternateVLDiT` diffusion action chunking.
* **Protocol**: ZeroMQ RPC on port `5557` (default port `5556` may be in use by other services).
* **Language Conditioning**: Policy config YAML **must** declare `language_instruction: "<task description>"`. Without this, the multimodal language backbone receives empty string and fails to ground objects.
* **Evaluation Horizon**: Use at least $\ge 1500 - 2000\text{ steps}$ ($30 - 40\text{ s}$) for complete pick-and-place trajectories.

## 3. Active Inference Self-Healing Pipeline
* **Diagnostic Oracle**: `EvaluationDiagnosticOracle` ingests `eval_telemetry.ttl` and classifies defects (`camera_occlusion`, `unconditioned_vla`, `horizon_truncation`, `reach_singularity`).
* **Remediation Engine**: `EvaluationRemediationEngine` auto-patches policy YAML, pulls table/objects into the near-field VLA sweet spot ($X \in [-0.30, -0.10]\text{ m}$), and re-relaxes the `SpatialFactorGraph`.
* **Single-Command Pipeline**:
  `python isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py --mode auto_heal --base_spec <spec.yaml> --eval_dir <eval_output_dir>`
