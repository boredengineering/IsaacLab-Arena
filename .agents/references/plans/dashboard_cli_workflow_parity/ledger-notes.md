# Static workflow parity ledger notes

Status: bounded P0 design inventory saved; **not application implementation or runtime parity acceptance**. This supplements [the main plan](../dashboard_cli_workflow_parity.md), [generation audit](cli-audit.md), and [evaluation audit](evaluation-audit.md). The main plan governs proposed UI/profile decisions.

## Verified coverage

[`workflow-parity-ledger.json`](workflow-parity-ledger.json) contains **394 uniquely identified entries**, partitioned into **26 disjoint source inventories**, covering **21 capability IDs (C01–C21)**. Every entry has source references, a literal/conditional/symbolic/unknown or not-applicable default, precedence, capability IDs, proposed profile/disposition, a unique proposed acceptance ID, a conservative implementation status and explicit limitations.

### Parser spelling counts

| Runner | Explicit declarations | Explicit source spellings | With inferred help/negative booleans | Ledger spellings |
|---|---:|---:|---:|---:|
| generation | 48 | 49 | 52 | 52 |
| policy | 47 | 48 | 52 | 52 |
| experiment | 39 | 41 | 44 | 44 |
| dcrg | 16 | 16 | 18 | 18 |

Generation's **49 explicit option spellings** are the audited 18 generation declarations + 13 shared Arena declarations + 17 AppLauncher declarations, with `--visualizer` / `--viz` as two spellings of one action. Its 52 ledger spellings additionally include `-h`, `--help`, and generated `--no-resolve_on_reset`. Policy additionally generates `--no-check_settling`; its total happens to equal generation's but is a different set. Experiment includes the `--eval_jobs_config` alias. DCRG has its own parser, not Arena/AppLauncher inheritance.

These parser counts **exclude dynamic policy fields**, accounted separately below. Shared flags are deliberately represented per runner: the same spelling can be active, ignored or illegal depending on the entry point. Aliases retain separate stable spelling IDs and their shared source declaration/destination. This is not a captured help transcript: policy registration is staged, and early help can precede dynamic registration.

### Other entry categories

| Category | Entries |
|---|---:|
| `assistance_json_field` | 25 |
| `capability_workflow` | 21 |
| `cli_option` | 166 |
| `controller_contract_field` | 9 |
| `dcrg_config_field` | 10 |
| `dynamic_policy_field` | 23 |
| `experiment_legacy_field` | 24 |
| `experiment_selector` | 2 |
| `experiment_typed_field` | 24 |
| `nonparser_operation` | 6 |
| `nonparser_parameter` | 32 |
| `override_mechanism` | 4 |
| `policy_yaml_field` | 17 |
| `variation_declaration_field` | 2 |
| `workflow_rule` | 29 |

The three supported effective policy-config field sets are GR00T remote **7**, GR00T Assisted **9**, and OpenPI **7** (23 total). These include inherited fields and the shared `num_envs` action where present; they are not 23 extra global parser flags. GR00T's nested YAML has 17 fields and assistance JSON has 25. Nested YAML fields are not invented standalone CLI options.

The six non-parser operations are the five documented scene/controller/evaluation registration, attachment and retrieval calls plus documented low-level assisted `run_rollout`; all 32 explicit caller parameters are recorded separately. Nine required controller contract keys are covered; extra JSON fields are preserved in the contract digest and are deliberately not represented as a finite exhausted schema.

The four override mechanisms are separate rows: graph document asset-swap flags, policy trailing Hydra variation overrides, experiment nested variation maps, and typed experiment declared-run field overrides. Concrete attached variation schemas remain profile-dependent.

## What verification actually established

- **28 static checks matched.** Fresh AST parsing independently rebuilt each runner's explicit/inferred spelling set, each named effective inherited config field set, and each selected operation parameter set; each matched ledger sets/counts.
- Generation's explicit spelling set also matched the 49-option audit table. All 21 ordered capability IDs matched the plan matrix.
- Every inventory source ID occurs once in that inventory and once in the ledger; the inventories are a complete, disjoint partition of the saved entry set. Entry IDs and proposed acceptance IDs are unique.
- All cited paths and line ranges resolved, and the 47 cited source snapshots remained unchanged during verification. Their SHA-256 digests and line counts are retained in the JSON. Existing source/audit assertions remain static evidence, not fresh runtime observations.
- JSON serialization/deserialization, required entry fields, allowed implementation-status values, capability references and rule references were checked before writing. The two files were written through `write_file`; no repository code, parser, config factory or default factory was imported/executed.

The source inventories distinguish closed AST sets from curated semantic/override/operation lists. The 29 cross-surface rules are **not** an exhaustive Cartesian enumeration of all flag combinations. No global custom-registry completeness is claimed.

## Decision-critical semantics retained

- Generation `--list_variations` and external-class selection are parsed no-ops; dynamic graph overrides are not wired there. Successful version output ignores `--out_dir`; family identity differs from spec identity; `--version` is only conditional auto-heal lookup. `policy_ref`/build `policy_config` do not select executed learned weights. New-generation feedback can contaminate lineage without changing synthesis.
- Standalone policy limit precedence differs from typed experiment precedence. Settling adds initial/reset simulation work outside policy limits, floors its maximum at 50 steps, can exit after index 40, rejects `terminated` but not the returned `truncated` signal, and warns/proceeds for residual speed. G1 posture hold differs from generation literal zeros. Reach-body selection, exact episode counts and vector overshoot are explicit.
- GR00T local/server modality precedence, effective horizon/chunking/history, OpenPI per-environment requests/reconnects and null keepalive CLI limitations are recorded. Assistance is privileged left-hand single-env G1 joint control with exact mapping, `chunk` scheduler, no bilateral mirror and strict numerical bounds—not generic DROID/controller search.
- Typed/legacy experiment selectors and fields, process-device and policy-batch overrides, rebuild budget splitting, absent configurable typed settling fields, output exclusions, rejected distributed mode and legacy chunk subprocess/output/failure behavior are recorded. Top-level shared experiment builder/source flags are not advertised as per-run overrides.
- DCRG freezes the scene/policy/seed/hand contract and resumes through its existing durable state/outbox; completed evidence is not replay authorization. Timeout alone is not verified descendant cleanup. Controller registration requires exact composite policy identity and source/hash evidence; graph read-back does not attest remote weights. Zero-success trials remain retrievable.
- Warm snapshot lease handoff, cancellation/indeterminate recovery, separately owned policy servers, unsafe report listeners, privileged Kit/display profiles and cumulative workbench budgets remain implementation gates.

## Remaining audits and explicit exclusions

- **G01 — supported_remote_yaml_consumers:** Fields are enumerated but not established as effective controls in the inspected remote path. Verify transitive consumers per approved GR00T profile; do not present served denoising/RNG controls or claim checkpoint selection.
- **G02 — legacy_graph_config_translation:** Characterize document-specific dynamic flag registration when graph adapter initially inspects process argv; Boolean false omission and dash/underscore destination collisions need explicit fail-closed handling.
- **G03 — unbounded_registry_and_variation_extensions:** All custom environment subcommands/typed factory fields, arbitrary policy classes, attached asset variation schemas, modality Python, joint maps and Kit extensions are not exhausted. Their exclusion from browser raw-input surface is explicit; newly supported profiles need separate static schema/consumer enumeration and approval.
- **G04 — runtime_resource_protocol_acceptance:** No actual parser, config instantiation, import availability, provider/policy protocol, camera/backend, GPU cleanup/lease, server attestation, graph transaction/readback or browser receipt verified. Live acceptance and numerical cumulative budgets remain approval-gated.
- **G05 — source_evidence_defaults:** Runtime path/default factories and environment-dependent defaults remain expressions, not evaluated values. Rank/rebuild summary normalization, settle truncation/threshold behavior, viewport-only camera startup and source-count changes need characterization before closing implementation acceptance.

Known finite input sets have been enumerated even where effectiveness needs further audit. New custom policy/environment/modality/variation profiles require a separately approved static schema/consumer extension; arbitrary browser imports, shell, unrestricted paths or admin access are not silently accepted exclusions counted as delivered parity.

Implementation statuses: **374 not_implemented**, **15 partial**, **5 needs_audit**. A source CLI existing is not dashboard support; partial denotes existing workbench foundations, never closed acceptance. Profile/disposition values are proposals, not approved live-run authority.

## Maintenance and scope

Stable IDs derive from runner plus exact option spelling, named effective config plus field, or named operation/rule. Preserve these IDs; update changed source references/defaults and rerun AST set comparison rather than importing parsers. For every approved dynamic profile, freeze its concrete class/schema, document/attached variation catalogue and source digest, then add a separately counted inventory. Reject unknown input fields instead of inferring coverage from registration availability.

Only `workflow-parity-ledger.json` and `ledger-notes.md` were created. Existing dirty work was not edited. No tests, runtime commands, network calls, services, jobs, model inference, simulator or database operations were executed. No secrets were read. The wider plan's runtime acceptance and numerical live budgets remain unapproved.
