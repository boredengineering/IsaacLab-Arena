# P04-I03-G3 / G3-R3 Full-Scene Native Execution — Comprehensive Debugging Notes & Recovery History

- **Document ID:** `P04-I03-G3-R3-DEBUG`
- **Created:** 2026-09-28
- **Status:** ACTIVE / IN RECOVERY (4 live attempts staged/run; diagnostic opacity resolved; preparing successor execution under ceiling 5/1/2)
- **Target Operations & Packages:**
  - [03-full-scene-workflow.md](03-full-scene-workflow.md)
  - [03-full-scene-workflow-strategy.md](03-full-scene-workflow-strategy.md)
- **Reference Campaign:** `p04-i03-programmatic-root-xy-pair-v1`
- **Historical Runs & Operations:**
  1. **Run 0 (Initial G3):** `p04-i03-g3-programmatic-root-xy-pair-v1` (`2a4a08ca2bfbb69a07e5cf39e2e3263d605d4f990a5d58e5f68dab688ee11451`) — `EXECUTION_STOPPED_NO_G3_ACCEPTANCE`
  2. **Run 1 (R3 Attempt 1):** `p04-i03-g3-successor-root-xy-pair-v1` (`a9ccd72995b997bbbca8b3b8092cafeb03113128c5f8e57ac610974630f94ad1`) — `R3_EXECUTION_STOPPED_NATIVE_CAPTURE_FAILURE_CLEANUP_VERIFIED`
  3. **Run 2 (Successor-R3 Attempt 2):** `p04-i03-g3-clock-recovery-root-xy-pair-v1` (`1ec3546b90f6d6e48f05c55c168b63e2579d09f61f33c8ad66e33f735694cee4`) — `SUCCESSOR_R3_EXECUTION_STOPPED_NATIVE_DIAGNOSTIC_FAILURE_CLEANUP_VERIFIED`
  4. **Run 3 (Successor-R3 Attempt 3 - Staged):** `p04-i03-g3-support-proxy-recovery-root-xy-pair-v1`

---

## 1. Executive Summary & Why We Are Repeatedly Stoppping at G3-R3

Goal **P04-I03-G3** (and specifically **G3-R3**, the live execution phase) is the first milestone in Plan 04 that requires **actual headless Omniverse Kit / Isaac Sim execution**, sensor telemetry generation, and physical intervention.

While it appears from the outside that the team has been "stuck" repeatedly on G3-R3, an architectural analysis reveals that we are systematically peeling back the layers of a sequential native simulation pipeline. Because Python and Omniverse Kit abort on the *first unhandled exception*, each live attempt has penetrated one layer deeper into the execution stack:

```
[Spawning & Env Setup]  ──► Run 0 crashed (stderr discarded, schema-5 failure dropped)
         │
[Kit / SimApp Boot]     ──► Passed
         │
[measured_reset]        ──► Run 1 crashed (PhysxManager.get_time does not exist)
         │
[Physics Stepping]      ──► Passed via subscribe_physics_on_step_events
         │
[Diagnostic Extraction] ──► Run 2 crashed (KeyError: 'workbench' in support proxy)
         │
[Camera & Observations] ──► STAGED (Support proxy fixed; awaiting Run 3 execution)
         │
[Evaluator Assessment]
         │
[Conditional C1 Repair]
```

### Protocol Constraints Causing Frequent Stops
Under **AC-I03** rules:
1. **Zero Native Releases for Debugging:** An agent cannot execute ad-hoc simulations or "quick probes" to test a hunch. Every native release must be accounted for and authorized by the operator.
2. **No Hot-Patching on Live Instances:** If a run crashes, it cannot be resumed or hot-patched. It must undergo full containment (drain API, release GPU lease, verify clean retirement), followed by non-sending TDD on CPU, a formal proposal with new operation keys, an independent critic review, and an explicit operator ceiling approval.
3. **Budget Ceilings Require Explicit Increases:** A full trial needs 2 native releases (1 for baseline C0, 1 for repair C1). When a run crashes at C0, it consumes 1 native release. To preserve the C1 opportunity on the next try, the ceiling must be incremented by the operator.

---

## 2. Deep Technical Breakdown of the 3 Crashes & Resolutions

### Phase 1: Total Diagnostic Opacity & Environment Scrubbing (Run 0)
- **Closeout Artifact:** [`G3-CLOSEOUT.md`](../../../../outputs/workflow/plan04-implementation/milestone1/p04-i03-g2-preview/G3-CLOSEOUT.md)
- **Symptom:** Worker PID 37159 exited immediately during C0. The orchestrator entered `reconciliation_required` without writing an error artifact or traceback (`OPEN_G3_RETENTION_GAP`).
- **Root Causes:**
  1. **Schema-5 Failure Dropped:** In [`service.py:825-829`](../../../../isaaclab_arena/agentic_environment_generation/workflow/service.py#L825-L829), `_record_scene_failure()` had `if contract.schema_version == "4":`. Full-scene workflows use schema 5, so all failure reporting was silently bypassed.
  2. **Stderr Diverted to `/dev/null`:** In [`foreground_generation.py:184`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_generation.py#L184), `subprocess.Popen` used `stderr=subprocess.DEVNULL`, destroying Python startup and Kit crash tracebacks.
  3. **Strict Environment Sanitization:** [`provider_security.py:38`](../../../../isaaclab_arena_examples/agentic_environment_generation/web_api/provider_security.py#L38) stripped `DISPLAY` and GPU runtime variables.
- **Resolution (Implemented in G3-R1):**
  - Updated `service.py`, `foreground_scene_ports.py`, and `neo4j_store.py` to route schema 5 failures properly.
  - Implemented bounded stderr piping and screening to preserve tracebacks in failure artifacts.
  - Verified with 492 CPU checks and froze proposal `93b77545...` in G3-R2.

---

### Phase 2: Physics Clock API Incompatibility (Run 1)
- **Closeout Artifact:** [`G3-R3-CLOSEOUT.md`](../../../../outputs/workflow/plan04-implementation/milestone1/p04-i03-g3-r3/G3-R3-CLOSEOUT.md)
- **Symptom:** Run 1 progressed past Kit initialization and into environment reset, but failed with:
  ```python
  AttributeError: type object 'PhysxManager' has no attribute 'get_time'
  ```
  at [`native_capture.py:494`](../../../../isaaclab_arena/agentic_environment_generation/workflow/native_capture.py#L494) (inside `measured_reset`) and line `515` (inside `clocks()`).
- **Root Cause:** The code assumed Omniverse PhysX exposed `base.sim.physics_manager.get_time()`, which does not exist in the Isaac Sim PhysX API.
- **Resolution (Implemented in `P04-I03-G3-CLOCK-RECOVERY`):**
  - Replaced `PhysxManager.get_time()` with an event-driven physics step listener:
    ```python
    omni.physx.get_physx_interface().subscribe_physics_on_step_events(
        self._record_physics_step, pre_step=False, order=0
    )
    ```
  - In `_record_physics_step(self, dt)`, accumulated actual physics step durations (`dt`) inside a thread-safe lock, asserting finite positive timesteps.
  - Separated nominal observation identity (`time_seconds`) from measured simulation time in [`observation_schedule.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/observation_schedule.py) and [`scene_observation.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/scene_observation.py).
  - Verified with 301 CPU checks in separate processes and froze proposal `4a375a45...`.

---

### Phase 3: Graph Node ID vs. Asset Registry Name Lookup (Run 2)
- **Closeout Artifact:** [`G3-SUCCESSOR-R3-CLOSEOUT.md`](../../../../outputs/workflow/plan04-implementation/milestone1/p04-i03-g3-successor-r3/G3-SUCCESSOR-R3-CLOSEOUT.md)
- **Symptom:** Run 2 passed Kit initialization, passed `measured_reset`, and successfully stepped physics. It then crashed in diagnostic sampling with:
  ```python
  KeyError: 'workbench'
  ```
  at [`native_capture.py:744`](../../../../isaaclab_arena/agentic_environment_generation/workflow/native_capture.py#L744) in `_camera_support_proxy`.
- **Root Cause:**
  - In the candidate graph spec, the background node has semantic ID `"workbench"` and registry name `"maple_table_robolab"`.
  - In `arena_env_graph_conversion_utils.py` and `Scene.add_asset()`, library backgrounds are registered in `Scene.assets` under their class attribute `self.name` (`"maple_table_robolab"`).
  - `native_capture.py:744` executed:
    ```python
    background = self.background_scene_name()   # Returned "workbench"
    name, _ = self.arena.scene.assets[background].get_object_cfg()  # KeyError: 'workbench'
    ```
- **Resolution (Implemented in `P04-I03-G3-SUPPORT-PROXY-RECOVERY`):**
  - Updated `_camera_support_proxy` to check `self.arena.scene.assets.get(background)` first, then fallback to `self.spec.background.registry_name` (`"maple_table_robolab"`), while preserving `"workbench"` as the output key in the returned diagnostic dictionary.
  - Added regression tests in `test_trajectory_assessment.py`, passed 173 CPU tests, passed host lint, received critic `CONTINUE`, and froze proposal `5fd68136...`.

---

## 3. Allocation & Cumulative Accounting Ledger

Every live simulation attempt is strictly tracked in native / repair / assessment format:

| Attempt | Operation ID | Result | Native Consumed | Repair Consumed | Assessment Consumed | Cumulative Native Used |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **Run 0 (G3 Initial)** | `p04-i03-g3-programmatic-root-xy-pair-v1` | Stopped (diagnostic gap) | 1 | 0 | 0 | 1 |
| **Run 1 (G3-R3-1)** | `p04-i03-g3-successor-root-xy-pair-v1` | Stopped (clock API) | 1 | 0 | 0 | 2 |
| **Run 2 (Successor-R3-2)** | `p04-i03-g3-clock-recovery-root-xy-pair-v1` | Stopped (`workbench` KeyError) | 1 | 0 | 0 | 3 |
| **Run 3 (Staged Next)** | `p04-i03-g3-support-proxy-recovery-root-xy-pair-v1` | Ready for launch | *2 max* | *1 max* | *2 max* | **5 max** |

### Why the Ceiling Increase (4 → 5) is Mandatory
- **Already Consumed:** 3 native releases.
- **Current Ceiling:** 4.
- **Remaining Under Current Ceiling:** Only 1 slot (`4 - 3 = 1`).
- If launched under ceiling 4, the run would be strictly **baseline-only** (C0). If C0 evaluates as negative (or unverified), the system would be prohibited from running the C1 conditional repair step because no native budget would remain.
- **Approving ceiling 5 (`5 / 1 / 2`)** provides 2 native releases for Run 3: 1 for baseline C0, and 1 for conditional repair C1 if eligible.

---

## 4. Anticipated Pipeline Stages Beyond the Support Proxy

To prevent being caught off-guard on Run 3, we have audited the remaining code paths that execute after `_camera_support_proxy`:

1. **3D World Bounding Box Computation:**
   - In `_camera_support_proxy:751-760`: uses `UsdGeom.BBoxCache` to compute world bounds for objects and background.
   - *Check:* Ensure prim paths in USD match the configured paths (`background_path = configured.format(...)`).
2. **Camera Sensor Acquisition & Frame Rendering:**
   - In `acquire_images()` & `camera_geometry()`: calls `env.unwrapped.scene.sensors[camera_name].data.output["rgb"]`.
   - *Check:* Verify that offscreen/headless camera rendering is properly configured and does not return empty or NaN tensors.
3. **RGB Image Encoding:**
   - Calls `encode_native_rgb(pixels, transform)` (converting raw NumPy arrays to PNG bytes).
4. **Observation Collection Validation:**
   - `validate_collection()` in `observation_schedule.py` asserts that measured physical step timestamps match nominal control steps within `1e-7` tolerance.
5. **Ternary Assessment:**
   - Passes RGB frames to `TernaryAssessment` (or model worker) to evaluate task success criteria.
6. **Conditional C1 Repair:**
   - If C0 is false and eligible, invokes `SceneRefiner` with programmatic root-XY displacement, creates a second native realization, and reassesses.

---

## 5. Playbook & Checklist for Launching Live Successors

Before issuing a live execution goal to Hermes, always verify this 5-point checklist:

- [ ] **Checklist 1: Clean Retirement Confirmed:** Check that previous API instances are `stopped/drained`, GPU leases are released, and durable owner is retired.
- [ ] **Checklist 2: Selection & Digest Frozen:** The successor proposal JSON (`successor-selection.json`) and SHA-256 must be verified from the previous closeout.
- [ ] **Checklist 3: Predecessor Handover Key Identified:** Identify the exact predecessor instance ID and effective configuration file for `--authorize-full-scene`.
- [ ] **Checklist 4: Allocation Arithmetic Aligned:** Ensure the prompt specifies `cumulative ceiling 5 / 1 / 2` with `2 native / 1 repair / 2 assessment` additional.
- [ ] **Checklist 5: Finite 60-Minute Expiry:** Ensure the private authority configuration derivative is prepared immediately prior to launch with an explicit 60-minute window (`approval_expires_at`).
