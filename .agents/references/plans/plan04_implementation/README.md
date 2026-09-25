# Plan 04 implementation plans

This folder holds bounded implementation plans and proposed goal prompts for
[Plan 04](../event_mapping/event-mapping-refactoring_plan_04.md).
It tracks what to do next without creating another runtime-status history.

Creating, editing or approving a planning document does not itself authorize code
execution, native launches, provider calls, credentials or database changes.
An execution goal must state those permissions explicitly.

## Start here

1. Read the [canonical implementation handoff](../dashboard_cli_workflow_parity/research-stack-implementation-handoff.md)
   for the latest measured result, remaining authority and evidence.
2. Open the current work package below for its scope, ordered actions and acceptance gates.
3. Issue its proposed goal separately if its execution authority is intended.
4. After execution, update the work package and this index, then record verified
   results in the canonical handoff and link the evidence. Do not mark a plan
   complete because its checklist was executed if its acceptance criteria failed.

## Current position

Snapshot: 2026-09-25. This is a navigation summary; the handoff remains authoritative.

- The installed zero-provider native path was exercised, but positive native
  validation is blocked. Its three-launch allocation is exhausted.
- The last attempt failed during contact-sensor activation in environment
  construction, before settling or camera capture.
- Native scratch inside the sealed artifact root blocks fresh candidate/artifact-byte reads.
- Failed-result readback, replay without another launch, and owned cleanup were verified.
- The next proposed work uses a parent-led actor and one independent read-only
  critic: observe, make a targeted fix, run/capture, critique the evidence, then
  correct or advance. It starts with repairs that require no native launch.
  Any additional native allocation remains unapproved until explicitly issued.

## Work-package register

| ID | Plan | Status | Next gate | Execution authority |
| --- | --- | --- | --- | --- |
| P04-I01 | [Native integration defects and bounded revalidation](01-native-integration-defects.md) | Proposed; actor-critic loop not started | Recover artifact-byte reads and improve constructor diagnostics without native execution | Not issued; goal proposes up to two additional launches in total, only after the no-native gate |

The current [goal prompt](01-native-integration-defects.md#proposed-goal-prompt)
is a proposal, not an active instruction.

The loop requires evidence-linked critic feedback and parent verification, not
review-count milestones. Native retries remain bounded and must test an identified
correction. Development-agent inference is separate from the zero Arena workflow
provider-request requirement; neither agent may deliver model credentials to the
native application. No execution or additional launch is authorized by editing
this index or its linked prompt.

## Document ownership

| Location | Owns |
| --- | --- |
| [Plan 04](../event_mapping/event-mapping-refactoring_plan_04.md) | Overall architecture, milestones and definition of success |
| This folder | Bounded work packages, approval boundaries, goal prompts and plan status |
| [Canonical handoff](../dashboard_cli_workflow_parity/research-stack-implementation-handoff.md) | Latest verified implementation outcome and current execution limits |
| [Runtime evidence](../../../../outputs/workflow/plan04-implementation/) | Actual run outputs, retained failures, hashes and readback evidence; may be local/ignored |

Existing plans and evidence remain in place. Links are used instead of moving or
copying the canonical handoff or rewriting historical approvals.

## Adding the next plan

- Copy [_template.md](_template.md) to the next `NN-short-topic.md` filename.
- Assign the matching `P04-Ixx` ID and add one row to the register.
- State the current blocker, evidence, permitted changes, prohibited effects,
  explicit allocation, ordered steps, acceptance conditions and stop conditions.
- Keep status separate from authority. Use `Proposed`, `Approved`, `In progress`,
  `Blocked`, `Verified` or `Superseded`; a status label never grants execution.
- Keep owners and deadlines unresolved unless explicitly assigned.
- Preserve failed attempts and prior allocations. A successor plan does not reset them.
- Put verified closeout details in the handoff and link them from the plan; avoid
  a second accumulating execution log here.
