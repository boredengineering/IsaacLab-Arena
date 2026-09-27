# P04-I03-G3 Execution Blockers and Root Cause Analysis

## 1. Executive Summary

During the initial execution of **P04-I03-G3** (`p04-i03-g3-programmatic-root-xy-pair-v1`), the empirical campaign was halted by the parent orchestrator with disposition **`EXECUTION_STOPPED_NO_G3_ACCEPTANCE`** as recorded in [G3-CLOSEOUT.md](../../../../outputs/workflow/plan04-implementation/milestone1/p04-i03-g2-preview/G3-CLOSEOUT.md).

- **Actual Consumption:** 1 native release committed (Case C0 baseline), 0 repair sends, 0 assessment sends.
- **Skipped Cases:** C1 (conditional root XY repair) and N1/N2 (stationary numeric discrimination) were withheld because C0 failed to establish an empirical baseline.
- **Outcome:** Clean run cancellation (version 9), API drained, 0 orphaned processes, 0 GPU memory leaks, durable owner epoch 8 cleanly retired.
- **Critical Diagnostic Gap:** The initiating exception of the native child failure was lost (`OPEN_G3_RETENTION_GAP_NOT_A_STOPPED_CLOSEOUT_BLOCKER`).

---

## 2. Phase 1 Blockers: Pre-Boundary Source Mismatches (Resolved)

Prior to C0 launch, the read-only pre-boundary critic identified three deterministic source defects that would have caused immediate failure:

1. **F1: Field Name Mismatch in Native Worker Request**
   - **File:** `isaaclab_arena_examples/agentic_environment_generation/web_api/native_scene_worker.py:277-284`
   - **Defect:** Worker referenced `request.validated_semantic_digest`, but `SceneWorkerRequest` defined `validated_semantic_sha256`.
   - **Resolution:** Corrected worker parameter access to `validated_semantic_sha256`.

2. **F2: Hash Envelope Mismatch (Parent vs. Child)**
   - **File:** `isaaclab_arena_examples/agentic_environment_generation/foreground_native_scene.py:252-256`
   - **Defect:** Parent callback hashed the full envelope `{'valid': True, 'spec': <spec>}`, while the child worker hashed `spec.model_dump(mode='json')`.
   - **Resolution:** Introduced `_validated_semantic_sha256()` to hash the validated spec projection directly.

3. **F3: Raw vs. Semantic Candidate Serialization Mismatch**
   - **File:** `isaaclab_arena/agentic_environment_generation/workflow/native_capture.py`
   - **Defect:** Frozen baseline candidate contained empty lists for `object_references` and `cli_override_specs`. Pydantic deserialization normalized them to `None`, which failed exact-byte comparisons in non-`evidence_only` settings.
   - **Resolution:** Permitted semantic-equivalence revalidation across schema variations.

---

## 3. Phase 2 Blockers: Runtime Native Worker Failure and Diagnostic Loss

When C0 was launched, the child process died prematurely, leaving the orchestrator in `reconciliation_required` without retained causal records. Three compounding implementation bugs caused this diagnostic blindness:

### Blocker A: Schema 5 Failures Dropped Silently
- **Location:** [`isaaclab_arena/agentic_environment_generation/workflow/service.py:825-829`](../../../../isaaclab_arena/agentic_environment_generation/workflow/service.py#L825-L829)
- **Defect:**
  ```python
  @staticmethod
  def _record_scene_failure(ports, intent, contract, phase, error):
      if contract.schema_version == "4":
          ports.record_failure(intent, phase, error, contract=contract)
  ```
- **Impact:** G3 full-scene workflow contracts use `contract.schema_version == "5"`. Because line 827 restricted recording to `"4"`, all Schema 5 failure events bypassed `ports.record_failure()`, leaving no disk artifact or error message.

### Blocker B: Subprocess Stderr Sent to `/dev/null`
- **Location:** [`isaaclab_arena_examples/agentic_environment_generation/foreground_generation.py:184`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_generation.py#L184)
- **Defect:** Native worker spawned via `subprocess.Popen` with `stderr=subprocess.DEVNULL`.
- **Impact:** Any traceback occurring during Python startup, module loading, Kit/SimulationApp instantiation, or argument parsing was discarded.

### Blocker C: Environment Sanitization Stripped Graphical / Driver Context
- **Locations:**
  - [`isaaclab_arena_examples/agentic_environment_generation/web_api/provider_security.py:38`](../../../../isaaclab_arena_examples/agentic_environment_generation/web_api/provider_security.py#L38)
  - [`isaaclab_arena_examples/agentic_environment_generation/foreground_native_scene.py:81-87`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_native_scene.py#L81-L87)
- **Defect:** `worker_environment()` restricted child environment variables to a minimal set (`PATH`, `PYTHONPATH`, `LD_LIBRARY_PATH`, etc.) and omitted `DISPLAY` (e.g., `:1`) and `VK_ICD_FILENAMES`.
- **Impact:** Omniverse Kit / Isaac Sim failed to attach to the headless rendering context on initialization.

---

## 4. Remediation Checklist Before Re-issuing G3

1. **Patch `_record_scene_failure` in `service.py`:**
   Support both `"4"` and `"5"` for `contract.schema_version` and ensure proper error arguments are passed.
2. **Buffer Worker Stderr in `foreground_generation.py`:**
   Capture `stderr` to an artifact-backed stream or pipeline buffer instead of `subprocess.DEVNULL`.
3. **Preserve Headless/Graphics Context in `foreground_native_scene.py`:**
   Pass `DISPLAY` and relevant driver paths through the worker environment.
4. **Offline Container Dry-Run:**
   Execute a single-process headless probe of `native_scene_worker.py` without consuming campaign allocations.
5. **Re-issuance Prompt:**
   Configure a 60-minute finite authority window in private settings and dispatch the authorized `/goal` to Hermes.
