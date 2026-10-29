# Planning execution and resolving conflicting examples

Status: proposed execution/verification procedure, not authorization to perform it. This extends the main parity plan without claiming implementation, migration, inference, database writes or simulation have already happened. Planning these operations now is required; performing them depends on their phase and explicit approval.

## 1. The difference between planning and performing

“No application implementation, migration, inference, database writes or simulator jobs were performed during planning” is an audit statement, not a proposal to leave these activities undesigned. Before execution we specify the inputs, owner, side effects, limits, evidence and recovery path. The researched protocol defines the technical guarantees; this document defines the operational sequence and how it is reviewed.

| Activity | What is planned in advance | Approval / boundary | Required evidence and stop condition |
|---|---|---|---|
| Application implementation | P0/P1 changes split into shared Python request/attempt/grant contracts, worker adapter and prompt-first UI; tests fail before behavior changes; preserve the existing graph/editor behavior and CLI contract | Explicit code-edit phase approval; separate permission for `docker/`, shared workflows or submodules | Container-backed unit/integration/type/build checks, no-network provider tests, independent review. Stop on regression or unresolved identity/security contract; no implicit live calls from tests. |
| Migration / writer cutover | Inventory stores and writers; propose managed local root, compatibility versions and additive graph schema; produce a dry-run mapping and backup/restore procedure; rehearse crash recovery on synthetic disposable data | P2 approval after A2 prompt-first review; exact roots/database/schema scope and maintenance window approved separately | Source/target manifests, backup restore verification, compatibility/refusal tests, no-clobber version tests. Stop on active unknown writers, existing identity conflict, missing backup or failed restoration. Historical stores remain unchanged until explicit migration authority exists. |
| Live inference | Freeze A2 prompt/constraints, model/endpoint profile, catalogue/retrieval mode, private credential grant, call/token/wall limits and output destination | Explicit bounded provider-run approval; no key in chat, YAML, argv or durable logs | Actual attempt/candidate receipt, exact prior context or disclosed fallback, request/result identity and warnings. Unknown provider outcome remains indeterminate; no automatic replay or unapproved budget increase. |
| Neo4j writes | Separate publication from model work; freeze payload/effect ID and target profile; prepare schema fixtures/readback, outage/late-commit/revocation cases and publication-only retry | Explicit graph-write/schema approval; synthetic isolated target first where available; production/research namespace chosen explicitly | Transaction/effect receipt and canonical content readback; no publication-success inference from generation exit. Conflicting identity blocks. Unknown/negative read while prior transaction is in flight cannot authorize resend. |
| Simulator build | Freeze approved scene revision, runtime/device/profile, one-owner GPU lease, steps/env count/settling/recording limits and output manifest | P3 plus explicit GPU/run budget; no competing warm snapshot worker | Verified lease acquisition, actual build/reset/step results, exact new-job images/video where requested and descendant cleanup. Stop on incompatible assets/actions, handoff failure or resource budget. Zero-action work is not task success. |
| Policy evaluation / experiments | Freeze checkpoint identity verification method, config/modality/hand/frame, seeds, exactly one effective step/episode limit, settling and cumulative child budgets | P4/P5 plus specific policy/experiment approval; do not stop or reconfigure shared servers implicitly | Raw episode records, count-consistent summaries, policy identity and exact scene links. Identity change or missing evidence stops continuation; retain partial/failed evidence. |

### First A2 progression

1. Characterize source contracts and implement P1 with synthetic/no-network tests. Demonstrate that New from prompt sends neither base YAML nor a document ID and that Refine does not change meaning.
2. Agree a bounded live draft-only A2 attempt. Use an approved existing interactive budget or a separately approved CLI-compatible profile; do not silently raise limits. This test may read eligible Graph-RAG priors but does not authorize publication or simulation.
3. Review actual A2 YAML, the large-plate destination, consumed priors/fallback, validation methods and candidate receipt. If it is a bowl task or contains an unrelated template, the scenario check fails even if the schema passes.
4. Discuss and approve P2 managed storage/graph changes. Rehearse version/publication recovery with disposable fixtures before the live research destination. Then validate A2 versioning and publication as separate effects, reusing a verified candidate where appropriate rather than needlessly regenerating it.
5. Approve a separate bounded build/snapshot test against that exact revision. Approve policy evaluation only after runtime/config identity and compatibility are established. Do not convert a generation approval into an open-ended research run.

A full CLI `resolve` command currently attempts publication; it must not be used as a supposedly draft-only P1 smoke test. The future P1 adapter's explicit draft-only operation is the appropriate boundary for that milestone. P2 is required for full README resolve-path parity.

## 2. Reasoning about contradictory documentation

Use evidence by question, not a single rule that “code always wins”:

- **What is the intended task?** Use the user's scenario contract and corrected research catalogue. Parser spelling cannot change banana-to-plate into banana-to-bowl.
- **What invocation does this checkout accept?** Use the current parser and its dispatch/call path. A slide or a remembered CLI alias does not establish executable syntax.
- **What side effects occur?** Trace the actual workflow plus documented constraints: generation, retrieval, version output and publication are separate effects.
- **What happened previously?** Require exact archived artifacts/run receipts, not the existence of a command or a similarly named folder. Missing recovered evidence means “not established,” not “impossible” or “certainly never happened.”
- **What should change?** Preserve intent, make the smallest explicit interface/documentation correction, then validate at the right level. If changing semantics or adding a CLI alias is desired, that is a separately tested compatibility change—not a silent repair of historical evidence.

### Worked A2 example

**Observed inputs**

- `.agents/references/presentations/category_a_b_manipulation_experiments.md:568-586` describes proposed A2: DROID banana-to-large-plate, family `droid_banana_to_plate`; it contains `--mode generate`.
- The current runner's mode declaration (`environment_generation_runner.py:49-60`) accepts `full`, `resolve`, `build`, `schema`, `catalog`, `auto_heal`; dispatch at `:731-766` routes `resolve` to generation without SimulationApp.
- The example README at `:372-391` specifies `resolve` without `--base_spec` for scratch Graph-RAG generation, with version/lineage output and attempted publication.
- The A2 presentation's build example at `:589-600` points to `droid_place_banana_next_to_rubiks_cube.yaml`, a different task. It is not A2 build or evaluation evidence.

**Diagnosis**

The intended A2 task is coherent. Its historical command has interface drift, and its visualization example has a scenario/artifact mismatch. These are separate defects. Neither proves the generation algorithm cannot produce A2. Neither permits relabelling a sibling run as A2 success.

**Explicit repair proposal**

For the current CLI, replace the invalid mode with `--mode resolve`, retain the A2 task/registry/family constraints, omit `--base_spec`, and disclose model calls, filesystem writes and attempted Neo4j publication. Select the provider/model profile explicitly; do not inherit an unverified historic model availability claim. The supported dashboard should express this as New from prompt, not template refinement.

After an authorized successful generation, use the exact returned, inspected A2 artifact as the input to a separately authorized `build` invocation. Do not guess an output path from `--out_dir`, a stale `latest` alias or the sibling command. Actual valid version output currently uses the version manager; read its receipt and verify `env_name`, embodiment, banana and large-plate assets, task endpoints and scene hash.

**Validation ladder**

1. Static interface check: inspect parser choices, dispatch and branch conditions. This establishes `resolve` as the appropriate current operation; it does not establish successful inference.
2. Isolated contract tests after implementation approval: reject invalid `generate`; route new to `generate_spec` with no implicit base; route refine separately; prove no accidental full-mode simulator startup. Avoid importing simulator-heavy runner main into the API merely to test spelling.
3. Approved live generation: inspect the actual candidate receipt and A2 contract; capture retrieval/no-prior/unavailable separately. A schema pass alone is insufficient.
4. Authorized publication: verify the exact stored revision and side effects, or retain partial/unknown status honestly.
5. Authorized build: inspect the actual A2 scene and realized placement; rendering/build is not policy success.
6. Authorized evaluation: bind the same scene to the actual policy and inspect raw episode evidence before claiming task success.

**Documentation repair**

Preserve the historical example as superseded, with its original token and an explanatory correction note; publish the verified current command in the canonical README/runbook. Replace the wrong sibling build example only with an actual A2 receipt-bound example after one exists. Add static example-mode and scenario-artifact checks to prevent recurrence. Do not “fix” the old command and then imply that the corrected command ran historically. This planning task records the proposed correction; it does not execute it or rewrite the historical presentation.

## 3. General decision rule

When a command and intended task disagree, first preserve the task contract, then reconcile the command against this checkout, then verify the actual result. The outcome can be a corrected invocation, a newly implemented compatibility feature, or a clearly documented blocker. “Do not silently translate” means corrections must be explicit and evidenced—not that we must stop at finding a typo or refuse to help.
