# P04-I02 Installed Visual Assessment — Comprehensive Debugging Notes and Recovery Plan

- Document ID: `P04-I02-DEBUG`
- Created: 2026-09-25
- Status: Tracking & Analysis; Pre-issuance Review
- Target Package: [P04-I02 — Installed visual assessment of retained native evidence](02-installed-visual-assessment.md)
- Reference Operation: `p04-i02-visibility`
- Reference Run: `0664fc8038961d9ea079f89c6c35cc5d305f2c56a1255d2253c64ce089d33e19`
- Reference API Instance: `9a8eebfcbe9845498ec26fb81bb049ca`

---

## 1. Executive Summary & Problem Description

During Milestone 1 of Plan 04, the installed visual assessment operation `p04-i02-visibility` was admitted under schema 4 to assess step-180 camera frames captured by `p04-i01-native-a5` using model `gpt-6-astra`.

Although Gate A preflight checks passed, the live execution failed immediately upon worker release:
1. **Admitted but Unsent:** The model worker (`worker-db6e9a742765deb3bd6280d9216e469e`, PID 62210) was prepared and released, but **zero provider requests were dispatched** and zero bytes were returned.
2. **Missing Causal Evidence:** The worker exited cleanly and its physical cleanup was recorded (`physical-b57a0beacd8e42731c77b61c229a7a91`), but the intent entered `reconciliation_required` without any initiating error envelope or stack trace.
3. **Cancellation Stall:** A supported stop was issued (`p04-i02-stop-owned`), but the run stalled in `cancel_requested` (run version 8) instead of transitioning to terminal `cancelled`.
4. **Ownership & API Drain Lock:** Durable owner `foreground-62035-99d8e7410d0056e4bb1a012f4ae23dd9` (epoch 6) remained `dirty=True` without a retirement tombstone. Calling `api-stop` failed with `cleanup_unknown` (exit 1), leaving instance `9a8eebfcbe9845498ec26fb81bb049ca` in state `stopping`.
5. **Window Expiration:** The 600-second execution window expired at `16:22:51.511984 UTC` while debugging the cancellation deadlock.

Crucially, **fixing only the schema-4 cleanup guard in the store is insufficient**. Two fatal pre-send bugs existed on the parent side that crashed the dispatch before the worker ever received data on stdin.

---

## 2. Root Cause Analysis & Deep Technical Breakdown

Analysis of the approval expiration indicates a potential issue where the remaining lifetime at worker runtime is shorter than the execution window, leading to insufficient authorization.
Looking closely at the proposed prompt under `#### Prompt suggested to fix the issue in 02-installed-visual-assessment.md:521-595` alongside the actual codebase, there are 6 specific, concrete implementation details that are underspecified or left out.
Without these specifics, an executing agent could easily misdiagnose the call chain, break caller signatures, or get re-blocked.

---

### 1. How execute() Obtains the Principal (Attribute vs. Signature)

- **What the prompt currently says:**
  > "RetainedAssessmentPorts.execute passes None through the installed ForegroundScenePorts.require_bounded_capability override into authorization. Preserve the real bound assessment principal through that path..."
- **What is left out & the code reality:**
  Look at the caller and callee signatures:
  - In [`service.py:749`](../../../../isaaclab_arena/agentic_environment_generation/workflow/service.py#L749):
    ```python
    output = ports.execute(released.intent, released.candidate, released.original, contract, **stage_args)
    ```
    `service.py` does **not** pass `principal` into `ports.execute()`.
  - In [`RetainedAssessmentPorts.execute`](../../../../isaaclab_arena/agentic_environment_generation/workflow/retained_assessment.py#L131):
    ```python
    def execute(self, intent, candidate, original, contract, *, retained_observation):
        self.require_bounded_capability(None, contract, intent.reservation)
    ```
  - In [`OwnedAssessmentPorts`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/installed_assessment.py#L233), `self.principal` was initialized by [`ForegroundScenePorts.__init__`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_scene_ports.py#L46).
- **The Risk:** If the prompt doesn't specify that the principal must be accessed via `getattr(self, "principal", None)`, an agent might modify `execute()`'s signature to require a `principal` parameter, breaking `service.py`, or fail to realize that `self.principal` is already attached to `ports`.
- **The Specification Needed:** The prompt must require retrieving the principal via `getattr(self, "principal", None)` inside `RetainedAssessmentPorts.execute`, strictly preserving `execute()`'s signature for `service.py`.

---

### 2. Exact Target Field for ExistingSource in ForegroundGenerationWorker.send

- **What the prompt currently says:**
  > "Inherited ForegroundGenerationWorker.send assumes owned.contract.source.prompt exists. Validate against the authoritative source variant, consistent with the packet builder's existing-source criterion rubric."
- **What is left out & the code reality:**
  The prompt does not name the exact match between the packet and the contract:
  - [`ForegroundScenePorts._call_child`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_scene_ports.py#L271) constructs:
    ```python
    prompt=contract.source.prompt if contract.source.kind == "new" else contract.criteria[0].rubric
    ```
  - In [`foreground_generation.py:238`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_generation.py#L238), the check is hardcoded:
    ```python
    packet["inputs"]["prompt"] != owned.contract.source.prompt
    ```
- **The Result & Masking:** For an `ExistingSource` (schema-4 retained evidence), there is **no `prompt` attribute** on `owned.contract.source`. Line 238 raises `AttributeError: 'ExistingSource' object has no attribute 'prompt'`. This exception is swallowed at line 269:
  ```python
  except Exception:
      raise RuntimeError("Private generation send incomplete") from None
  ```
  The child worker was spawned, received 0 bytes on stdin, and exited cleanly without sending any provider calls.
- **The Risk:** An agent might attempt to add a dummy `prompt` property to `ExistingSource` or bypass validation entirely.
- **The Specification Needed:** The prompt should state the exact conditional check:
  - If `owned.contract.source.kind == "new"`: check `owned.contract.source.prompt`.
  - If `owned.contract.source.kind == "existing"`: check `owned.contract.criteria[0].rubric`.

---

### 3. The Handover Deadlock in instance.py:331

- **What the prompt currently says:**
  > "For post-crash recovery, address the existing exited_unclean versus stopped/drained handover restriction through the smallest supported reconciliation/handover change."
- **What is left out & the code reality:**
  Look at [`instance.py:328-333`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/instance.py#L328-L333):
  ```python
  if (prior["identity"] is None or same_process(...) or prior["state"] not in {"stopped", "failed", "exited_unclean"}):
      raise ValueError("Prior instance unresolved")
  if transition is not None:
      if prior["state"] != "stopped" or prior["code"] != "drained":
          raise ValueError("Prior cleanup unresolved; recover using the previous configuration")
  ```
  - Line 328 already recognizes `exited_unclean` as an admissible prior state!
  - However, line 332 unconditionally rejects `exited_unclean` when `transition` is not `None`.
- **The Risk:** An agent might try to fabricate a `stopped/drained` record in the database, destroying crash evidence.
- **The Specification Needed:** The prompt should explicitly note that line 332 is the gate blocking handover after an unclean exit, and that the recovery path must allow transition from `exited_unclean` once physical cleanup and durable owner retirement are independently verified.

---

### 4. Sticky cleanup_unknown on a Still-Live API Process

- **What the prompt currently says:**
  > "Address assessment-mode recovery restrictions and sticky cleanup_unknown where required."
- **What is left out & the code reality:**
  If the host/container was not rebooted and PID 62035 is still running in state `stopping`:
  - In [`execution_owner.py:225`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/execution_owner.py#L225):
    ```python
    if self.cleanup_unknown:
        raise CleanupUnknown("Execution cleanup unresolved")
    ```
  - Once `ExecutionOwner.close()` experiences an initial timeout, `self.cleanup_unknown` is set to `True` permanently. Any subsequent call to `api-stop` or `close()` immediately raises `CleanupUnknown` without ever checking if the underlying background drain task (`self._closing`) has now finished!
- **The Risk:** Repeated `api-stop` commands will fail perpetually even after the background process finishes cleanly draining.
- **The Specification Needed:** If recovering a live API, `ExecutionOwner.close()` must check whether the pending `_closing` task has resolved before immediately raising on the sticky flag.

---

### 5. The Root Cause of Stuck Cancellation in neo4j_store.py:4089

- **What the prompt currently says:**
  > "Start with cancel_keyed → finish_cancelled → acknowledge_scene_cleanup and the schema-3-only duplicate-cleanup finalizer."
- **What is left out & the code reality:**
  - In [`neo4j_store.py:4071`](../../../../isaaclab_arena/agentic_environment_generation/workflow/neo4j_store.py#L4071):
    ```python
    if intent.worker_cleanup is not None:
        self._finish_known_native_cancel(tx, fence.run_id)
        return False
    ```
  - And `_finish_known_native_cancel` in [`neo4j_store.py:4089`](../../../../isaaclab_arena/agentic_environment_generation/workflow/neo4j_store.py#L4089) has:
    ```python
    if run is None or run.state != "cancel_requested" or parse_contract(run.contract_json).schema_version != "3":
        return False
    ```
  - Because schema 4 is excluded, the transaction returns `False` without setting `run.state = 'cancelled'`. As a result, `retire_cancelled()` fails, durable owner epoch 6 remains `dirty=True`, and the API cannot drain.
- **The Risk:** An agent might try to bypass the lease or force unlock in Cypher instead of fixing the schema guard.
- **The Specification Needed:** State explicitly that `_finish_known_native_cancel` (or an equivalent schema-4 cancel finalizer) must transition schema-4 runs from `cancel_requested` to `cancelled` upon duplicate cleanup acknowledgement.

---

### 6. Approval Expiry Drift (approval_expires_at)

- **What the prompt currently says:**
  > "Immediately before submission, verify the frozen approval, authentication and role-binding lifetimes still cover the intended execution window including cleanup..."
- **What is left out & the code reality:**
  In [`installed_assessment.py:285`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/installed_assessment.py#L285):
  ```python
  expires_at = min(auth.expires_at, selected.approval_expires_at)
  ```
  - When authoring the successor configuration (`p04-i02-visibility-r2`), `approval_expires_at` is set in the configuration JSON.
  - If pre-send critique, container checks, and preparation take 3–5 minutes, an initial 600-second expiry timestamp will have drifted significantly.
  - When the worker finally calls the provider, `deadline <= time.time()` in [`foreground_scene_ports.py:256`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_scene_ports.py#L256) will raise `"Scene role deadline expired"`.
- **The Risk:** The worker will be aborted due to role expiration before it completes the vision evaluation.
- **The Specification Needed:** The prompt should explicitly specify setting `approval_expires_at` with enough buffer (e.g., at least 600s + pre-send preparation headroom, aligned with token expiry) at configuration authoring time.

---

### 7. Parent-Side Error Retention Blindspot
- **Mechanism:** When `ForegroundGenerationWorker.send()` raises `RuntimeError("Private generation send incomplete") from None`, the initiating `AttributeError` is stripped.
- **Service Masking:** In [`service.py:758-767`](../../../../isaaclab_arena/agentic_environment_generation/workflow/service.py#L758-L767):
  ```python
  except Exception:
      self._store.mark_scene_unknown(run_id, snapshot.intent.intent_id)
      failed = True
  ```
  `mark_scene_unknown` flags the intent as `reconciliation_required` without recording the initiating exception type, phase, or safe reason.
- **Remedy:** Parent-side authorization and private-packet validation must capture a sanitized error record (phase: `parent_packet_send`, exception kind, safe reason) and store it before converting the intent status. Sanitization must strictly exclude raw locals, packet envelopes, credentials, or unscreened text.

---

### 8. Gate A Blindspot
- **False Confidence from Preview:** [`installed_assessment.py:114`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/installed_assessment.py#L114) `preview()` directly constructs `BoundedSceneModels` and invokes `assess()` with a deny hook. It completely bypasses `OwnedAssessmentPorts`, `ForegroundScenePorts`, and `ForegroundGenerationWorker.send`. Gate A passed 100% despite fatal pre-send bugs.
- **Remedy:** Gate A must explicitly review the actual installed call paths alongside the affected existing checks without creating synthetic test harnesses.

---

### Summary Checklist of Missing Items to Add to the Prompt

| Item | File Anchor | What Needs to be Explicit in Prompt |
|---|---|---|
| **Principal Retrieval** | [`retained_assessment.py:131`](../../../../isaaclab_arena/agentic_environment_generation/workflow/retained_assessment.py#L131) | Retrieve via `getattr(self, "principal", None)`; preserve `execute()` signature for `service.py`. |
| **ExistingSource Validation** | [`foreground_generation.py:238`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_generation.py#L238) | Validate against `criteria[0].rubric` for `kind == "existing"` (matching `_call_child`). |
| **Handover Deadlock** | [`instance.py:331`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/instance.py#L331) | Allow transition from `exited_unclean` when physical cleanup and owner retirement are verified. |
| **Sticky Cleanup Unknown** | [`execution_owner.py:225`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/execution_owner.py#L225) | Re-poll/check `_closing` task resolution instead of permanently failing on stale timeout. |
| **Schema-4 Cancel Finalizer** | [`neo4j_store.py:4089`](../../../../isaaclab_arena/agentic_environment_generation/workflow/neo4j_store.py#L4089) | Allow `_finish_known_native_cancel` to transition schema-4 runs to `cancelled` on duplicate cleanup. |
| **Approval Window Drift** | [`installed_assessment.py:285`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/installed_assessment.py#L285) | Author `approval_expires_at` with sufficient margin so pre-send review does not starve execution. |

---

## 3. Concrete Code Modifications Required

| Target File | Line(s) | Required Modification | Rationale |
|---|---|---|---|
| [`retained_assessment.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/retained_assessment.py#L131) | 131 | Pass `getattr(self, "principal", None)` instead of literal `None` to `require_bounded_capability`. | Propagates the authenticated assessment operator principal stored on `OwnedAssessmentPorts`. |
| [`foreground_scene_ports.py`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_scene_ports.py#L93) | 93–96 | Verify `principal == self.principal` and pass `self.principal` to `require_scene_execute`. | Enforces that only the authorized assessment operator can execute capability checks. |
| [`foreground_generation.py`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_generation.py#L238) | 238 | Branch source prompt check: `contract.source.prompt` if `kind == "new"`, else `contract.criteria[0].rubric`. | Prevents `AttributeError` on `ExistingSource` which lacks a `prompt` attribute. |
| [`foreground_generation.py`](../../../../isaaclab_arena_examples/agentic_environment_generation/foreground_generation.py#L269) | 269–270 | Retain sanitized causal failure descriptor before raising `RuntimeError`. | Preserves initiating exception identity before the generic wrapper masks it. |
| [`service.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/service.py#L758) | 758–767 | Record causal error on intent/run before calling `mark_scene_unknown`. | Prevents silent conversion to `reconciliation_required` without diagnostic cause. |
| [`neo4j_store.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/neo4j_store.py#L4089) | 4089 | Allow `_finish_known_native_cancel` to accept schema-4 contracts for duplicate cleanup. | Transitions `cancel_requested` to `cancelled`, enabling `retire_cancelled` to release owner. |
| [`execution_owner.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/execution_owner.py#L225) | 225–238 | Re-check status of background `_closing` task instead of immediately raising on sticky flag. | Allows still-running API process to finish draining cleanly on subsequent stop calls. |
| [`instance.py`](../../../../isaaclab_arena/agentic_environment_generation/workflow/api/instance.py#L331) | 331–333 | Permit handover from `exited_unclean` if physical cleanup and owner retirement are proven. | Unblocks successor launch after a machine reboot or unclean process termination. |

---

## 4. Comprehensive Successor Goal Prompt

Below is the fully amended, ready-to-issue prompt for `p04-i02-visibility-r2`. It incorporates all lifecycle recovery paths, concrete pre-send defect repairs, causal error retention, tightened Gate A verification, and cumulative attempt accounting.

```text
/goal Recover P04-I02’s blocked lifecycle, repair the retained-assessment failure boundary, then complete one installed authenticated visibility assessment.

Read .agents/references/plans/plan04_implementation/02-installed-visual-assessment.md: section 2 for exact inputs, sections 4–6 for restrictions and acceptance, and the final blocked-outcome record. Preserve historical evidence; do not resume obsolete budget or credential audits.

This issuance authorizes the ordered work below. Proceed through satisfied gates without requesting approval after each routine correction. Do not build the full scene workflow.

1. RECOVER THE EXISTING RUN — NO PROVIDER SENDS

Target run:
0664fc8038961d9ea079f89c6c35cc5d305f2c56a1255d2253c64ce089d33e19
Target API instance:
9a8eebfcbe9845498ec26fb81bb049ca

Re-read current state and match the retained owner/process identities. Recorded PID 62035 and owner epoch 6 are historical coordinates, not sufficient authority to signal a process.

Authorize the smallest necessary changes to existing cancellation, reconciliation, owner and installed lifecycle paths:
- In neo4j_store.py:4089 (_finish_known_native_cancel), permit schema-4 contracts so duplicate cleanup acknowledgement transitions run state from cancel_requested to cancelled, allowing retire_cancelled to release the dirty owner lease.
- In execution_owner.py:225, resolve sticky cleanup_unknown for still-live API processes: ExecutionOwner.close() must check whether the pending background drain task (self._closing) has resolved before immediately raising on the sticky flag.
- Distinguish a still-live old API from one that exited uncleanly during restart. An on-disk patch does not update a live process; a dead process cannot supply its lost in-memory cleanup capabilities. Recover through an ownership-verified, non-sending application path using the exact retained configuration, run, worker and owner identities.
- In instance.py:328-333, line 328 already recognizes exited_unclean as an admissible prior state, but line 332 unconditionally rejects exited_unclean when transition is not None. Allow configuration handover from prior state exited_unclean once physical cleanup and durable owner retirement are independently verified. Preserve original unclean-exit history; do not fabricate graceful drain status. No direct database state-forcing, metadata deletion, forced unlock, unanchored signals or clearing/relabeling cleanup flags merely to permit restart.

Gate further execution on fresh proof of completed cancellation, exact-worker cleanup, durable owner retirement/lease release, and either normal old-API stop/drain or verified post-crash recovery with supported handover. Process absence alone is insufficient. Preserve the failed run, its one-model-call/190-second reservation, all failures and producer records. Do not refund or reset anything.

2. REPAIR PRE-SEND BOUNDARIES AND RETAIN CAUSAL FAILURES

Treat the original released-worker failure as unresolved, separate from cancellation.

Trace the actual installed class hierarchy and parent authorization/private-packet preflight, then worker entry, send authorization, receive/validation and error retention. Recheck and narrowly correct the source-supported defects identified in this proposal:

- In retained_assessment.py:131, RetainedAssessmentPorts.execute must pass getattr(self, "principal", None) rather than literal None into require_bounded_capability, preserving the authenticated operator principal attached to OwnedAssessmentPorts (from ForegroundScenePorts.__init__) without altering execute()'s public signature (which is called by service.py:749 without a principal argument). Missing or mismatched authenticated principals must still be refused.
- In foreground_generation.py:238, ForegroundGenerationWorker.send must validate packet["inputs"]["prompt"] against owned.contract.criteria[0].rubric when owned.contract.source.kind == "existing" (matching ForegroundScenePorts._call_child), and against owned.contract.source.prompt only when kind == "new". Do not fabricate a prompt field, change the retained source or weaken exact-input checks.

For each correction, state the causal hypothesis, smallest change and predicted observation. Check affected callers of the same hooks to preserve native-only, synthetic and other budgeted guards without a general refactor or audit. The source match to the failed admission supports these defects but does not recover the historical initiating exception.

Retain the first sanitized causal failure in parent authorization/private-packet validation as well as child entry and receive, before wrappers replace it with a generic send error or reconciliation_required (in foreground_generation.py:269 and service.py:758). Use bounded phase, exception type/safe reason and existing run/intent/fence identities. Never retain private packets, credentials, locals or unscreened exception text. Keep cleanup errors separate; attempt bounded cleanup even if diagnostic retention itself fails, and report that failure explicitly.

If the historical exception is irrecoverable, record that honestly. Do not make reconstructing it an endless prerequisite or launch an unaccounted diagnostic worker. Ensure the next authorized installed attempt cannot silently lose the initiating error.

3. AUTHORIZE ONE SUCCESSOR ASSESSMENT

After lifecycle recovery, complete section 5's Gate A with explicit coverage of the actual installed capability/principal chain, existing-source private-packet validation and parent error-retention path. The current installed_assessment.preview directly constructs model tools: retain its request/zero-send evidence, but do not claim it exercises owned handoff. Cover the omitted paths through scoped source review and affected existing checks, not new tests, a harness or an extra worker. Only the authorized installed successor can establish live handoff and assessment acceptance.

Only after Gate A and the pre-send critique pass, authorize one successor operation, p04-i02-visibility-r2, explicitly linked to the failed consumer and unchanged p04-i01-native-a5 producer. Check the successor key first; if already admitted, recover it rather than invent another key. Never reopen or rewrite the expired original run.

Use section 2’s exact candidate, evidence and all three unchanged step-180 PNGs. Assess red_block and blue_bin in every frame using the retained rubric, model/profile and finite technical completion allowance. No recapture, cropping, candidate changes or manufactured uncertainty.

Authorize a fresh 600-second operation window beginning only at the successor's successful durable admission, after provider-free preparation and pre-send critique. Record its admitted_at and absolute deadline. In installed_assessment.py:285, expires_at = min(auth.expires_at, selected.approval_expires_at): author approval_expires_at in configuration JSON with sufficient buffer (e.g. at least 600s + pre-send preparation headroom, aligned with token expiry) at configuration authoring time so pre-send review does not starve execution and trigger "Scene role deadline expired" in foreground_scene_ports.py:256. Preview, critique and API startup do not start this operation clock. Retries, replay and restarts do not renew it. Preserve the 570-second assessment-stage limit and per-attempt limits of 180 seconds provider time plus 10 seconds cleanup. One worker at a time.

Allow at most THREE cumulative assessment-role gpt-6-astra provider attempts across the original and successor operations. Reconcile actual consumption first; the last verified ledger recorded zero sends across the producer (3/3 attempts remain). Preserve old reservations and record the successor’s normal application-owned reservations without resetting source-level accounting.

Keep accounting-only policy: no new monetary/token-budget vetoes, fabricated prices or replacement ledger. Preserve RequestEnvelope checks, technical limits and usage/cost reporting.

Apply section 5’s retry policy unchanged: recover retained responses and clean up first; retry only eligible formatting/coverage or transient transport failures within remaining authority. Count failed/uncertain sends. Disable SDK retries, pings and fallbacks. Stop at the first valid complete result, including negative or explicitly uncertain results.

Reuse supported private/configuration handover in the existing approved installation and namespace. Preserve credential secrecy, configuration identities and old lifecycle records.

4. VERIFY APPLICATION ACCEPTANCE

Submit through authenticated installed CLI/GraphQL; the application owns execution and retries. Retain every attempt’s request, response or failure, structured result, lineage and accounting.

Recover exact input and attempt/result bytes through a fresh authenticated client. Replay the completed successor and verify the same retained result with no additional provider request, worker release or allocation mutation. Verify final physical cleanup, durable retirement and API drain.

Use one read-only critic at pre-send and one at final outcome. Parent closes P04-I02 only when every applicable acceptance criterion is verified; otherwise report BLOCKED with the precise remaining boundary. A complete negative/uncertain assessment may satisfy integration, not scene acceptance.

EXECUTION DISCIPLINE

Keep corrections parent-led and narrow. No new or modified tests, mocks, fixtures, harnesses or synthetic campaigns. Run only affected existing simulation-free checks in the discovered checkout container as ubuntu via /isaac-sim/python.sh, plus scoped host lint; then advance to the installed path.

Stop after three unsuccessful provider-free corrections for the same blocker or an actual ownership, provenance, authority or scope blocker. Finish bounded cleanup and report the exact decision needed.

Zero additional native/Kit, capture, generation, scene repair, policy or prior-retrieval work. Preserve consumed allowances and all scientific flags. Keep repository protected paths untouched; no commits, pushes, stashes or resets.

Update the existing operation record, package, index, Plan 04 and canonical handoff. Report lifecycle recovery, assessment integration, visual verdict, readback/replay and final cleanup separately. No broader completion claim.
```
