# Event mapping — source references and proof boundaries

Source baseline: `45a0b26466`, branch `dev/0.3.0-prerelease`. This is the event-mapping study's source inventory, not implementation status or runtime verification. Line anchors are baseline-relative and must be rechecked after edits. The original unresolved `[cite: 1]` placeholders have been removed; the concrete repository paths below are the inspectable sources, not a recovered external bibliography.

Design and work ownership: [plan 02](../plans/event-mapping-refactoring_plan_02.md), especially §§5–11, P0 work packages and P6-V1–V6. Review provenance: [bounded review ledger](../plans/event-mapping-refactoring_plan_02-review.md). Historical discussion/evidence: [session memory](session_memory.md). No tests or research workloads ran for this inventory update.

Aliases: `C/` = `isaaclab_arena/agentic_environment_generation/`; `E/` = `isaaclab_arena_examples/agentic_environment_generation/`; `W/` = `E/web_api/`. Other paths are repository-relative. Each row separates an implemented capability from what it does **not** prove.

## Generation, scene verification and legacy repair

| Source | Actual responsibility / limitation | Plan 02 disposition |
| --- | --- | --- |
| `C/workbench/journal.py:61–147,406–858` | SQLite job/attempt/authorization/receipt/event/worker authority, including fencing and conservative restart. Early schema lines alone are not its whole interface. | §§7–8, P0-04; new managed workflow uses Neo4j, legacy operations migrate only through explicit boundaries. |
| `E/environment_generation_runner.py:255–349,747–819` | Existing `resolve`, `build`, `full`, `auto_heal` entry points combine several responsibilities. | §11; preserve compatibility while extracting reusable services. |
| `E/environment_generation_runner.py:660–736,798–807` | Build constructs an environment, calls a specification critic, performs zero-action steps and optionally records. | §§4–5; not automatically visual assessment, measured support or learned-policy success. |
| `C/environment_generation_agent.py:191–360` | New-generation Graph-RAG context, inference, grounding, RDF/SHACL/specification checks and bounded repair. | §§6,9, P0-03/06; exact consumed context and cumulative costs retained. |
| `C/visual_critic.py:322–354` `PhysXPreflightCritic` | Authored-coordinate heuristic; skipped/missing pose inputs can yield no issues. No PhysX settling or named-support measurement occurs here. | §§5,11, P0-02; advisory/preflight evidence, never measured stability proof. |
| `C/environment_generation_agent.py:358–388` | Fallback/nonconverged output can still emit `generation_completed`. | §6; validate the final candidate, not merely successful return. |
| `E/environment_generation_runner.py:301–349` | Saves a returned spec/version and attempts graph synchronization; no convergence requirement. | §§6,9,11; do not reuse the whole resolver as the new unpublished-candidate adapter. |
| `E/environment_generation_runner.py:439–598,794–796` | Legacy `auto_heal` diagnoses retained evaluation data and may change scene/policy; can discover latest directories. | §11; retained/deferred legacy path, not general managed scene repair. |
| `C/eval_self_healing.py:74–124,662–751` | Reads metrics/telemetry and applies diagnostic/remediation rules; missing rates can default to zero; general relaxation may be invoked. | §11; later reuse needs exact evidence and permission; no missing-evidence-as-measurement or automatic policy patching. |
| `C/environment_generation_agent.py:280–283`; `E/environment_generation_runner.py:688–689` | Current main critic callers omit rendered images. | §5.2; existing specification-feedback loop is not the proposed rendered-evidence loop. |
| `C/environment_generation_agent.py:430–503` | Refine consumes explicit feedback, repairs/grounds and performs bounded checks; not New prior retrieval. | §6 and P0-03; exact base/feedback, full delta checks and fresh relevant evidence. |
| `C/environment_generation_agent.py:311–335` | Specification-based visual feedback already feeds `repair_with_feedback`. | Reuse the engine; add evidence-bound application routing rather than claiming no repair mechanism exists. |
| `C/inference_backend.py:306–315,447–496` | Backend initialization invokes a ping; multimodal path encodes images and returns model text. | P0-06 and P6-V2; real transport accounting before construction, no physical-truth guarantee. |
| `C/visual_critic.py:75–186` `VisualSceneCritic` | Optional image cloud/local tiers and structured findings; local fallback uses its own HTTP path/default profile. | §5.2, P0-06; managed workflows prohibit implicit fallback and keep observations distinct from proof. |
| `C/spatial_geometric_oracle.py:455–568` `relax_spec_spatial_factor_graph` | General numeric grounding over support/clearance/reach factors; writes object and robot poses, not only target XY. | §§6,11, P0-03; preserve full contract, check runtime effect, distinguish from constrained DCRG proposer. |
| `W/generation.py:173–193` | Returns validated draft/warnings and explicitly says no simulation or policy evaluation ran. | §§1,4,11; draft production remains a distinct fact. |

## Trajectory tool — historical descriptions corrected

The earlier study described a hardcoded failed-red-apple prompt and import-time startup in `render_policy_trajectory.py`. Those descriptions are superseded by `45a0b26466`; they are not remaining implementation tasks. Old capture references to lines 107–120 and VLM references to 131–151 no longer identify those operations.

| Current source | Actual responsibility / limitation | Plan 02 disposition |
| --- | --- | --- |
| `isaaclab_arena_examples/tools/render_policy_trajectory.py:43–126,129–153` | Explicit `run`/`main`, core capture at 79, capture manifest at 88–101, generic assessment at 111 and cleanup/failure-exit handling. Returns retained assessment and prints a summary. | Reuse thin diagnostic wrapper; no automatic repair or measured task success is claimed. |
| `C/trajectory_capture.py:12` `capture_trajectory` | Reusable selected-camera capture with actual steps/stop reason and terminal-autoreset limitations. | Scene and policy evidence adapters preserve profile distinctions; new episode alignment must be verified. |
| `C/trajectory_assessment.py:48–150` `assess_trajectory` | Task/spec/image-bound generic diagnostic rubric and retained digests/assessment; `task_success` remains unknown. | New criterion/trial adapters add supported structured coverage; generic satisfactory is not physical or policy proof. |

## DCRG — measured experiment, with VLM assistance proposed

| Source | Actual responsibility / limitation | Plan 02 disposition |
| --- | --- | --- |
| `E/dcrg_runner.py:130–265` | Evaluates per-seed baselines/candidates, records graph evidence and retrieves exact recurrent feedback for bounded proposals. | §10/P6; extract callable wiring, not a stdout-driven external-agent loop. |
| `C/dcrg/loop.py:253–316` | Matched-count measured task/lift comparison, proposal accept/reject, separate terminal success/exhaustion. | Comparator remains authoritative; VLM appearance/diagnosis cannot replace its scores. |
| `C/dcrg/loop.py:151–244,283–295` | Immutable specs, file-owned state, exact evaluation reuse and indeterminate evaluation; a pending proposal callback may run again. | Managed state port plus stable VLM intent/receipt needed before paid calls enter the proposal path. |
| `C/dcrg/loop.py:25–68,420–443` | Explicit episode evidence/config and original-baseline target-XY-only guard; task/lift scoring. | Freeze experiment scope and retain task/physics/Z/other fields; improvement is not robust task success. |
| `C/dcrg/evaluation.py:18–99,102–142` | Requests camera video and validates seed/episode count plus sustained-lift/placement evidence. | P6-V1 must add exact media/episode/frame alignment and integrity; recorded video paths alone do not establish it. |
| `C/spatial_geometric_oracle.py` `relax_spec_active_inference` | Copy-on-write bounded target-XY proposal from measured feedback; requires supported support geometry and fixed-Z compatibility. | P6-V4 reuses measured feedback; never substitute invented VLM `dx/dy/dz` or general scene relaxation. |

## Execution and test inventory

| Source | What it covers | What it does not establish / planned use |
| --- | --- | --- |
| `W/supervisor.py:42–63`; `W/editor_execution.py:57–102,145` | Serial dispatch and bounded managed/legacy worker execution. | Extract shared process/authorization ports; coordinator cannot occupy its child's serial slot. |
| `W/snapshot_worker.py:24–37` | GUI-owned rendering imports; snapshot contract explicitly permits zero steps. | Extract reusable rendering; static preview is not post-settle stability. |
| `isaaclab_arena/tests/test_visual_and_graph_rag.py:62–111` | Authored-coordinate heuristic occlusion with no images/backend. | Not live VLM judgment; extend heuristic/advisory boundary regression under P0-07/P2. |
| `isaaclab_arena/tests/test_environment_generation_agent.py:120–178` | Synthetic invalid/repaired responses and SHACL repair flow. | Not rendered-scene repair; preserve final-candidate/fallback coverage and isolate all side effects. |
| `isaaclab_arena/tests/test_inference_backend.py:186–227` | Synthetic SDK requests, initialization/image paths, model/token/profile/transport fields. | Not physical assessment; reuse for provider budget and request-boundary tests. |
| `isaaclab_arena/tests/test_dcrg_loop.py:73–84,125–149` | Synthetic episodes and measured comparison/rejection/recovery logic. | Not empirical VLM utility; extend opt-in guidance compatibility/restart tests in P6. |
| `isaaclab_arena_examples/tests/test_workbench_snapshots.py:315–352` | Explicit GPU opt-in artifact inventory, PNG dimensions/variation and freshness limitations. | Not support or automatic repair proof; keep real render execution separately authorized. |

The detailed VLM/DCRG proposal is in plan 02 §10.1–10.7: scene assessment, post-trial observations/hypotheses and supported proposal guidance under deterministic application rules, followed by controlled utility/cost comparisons. These are proposed integrations, not newly discovered existing capabilities. Exact test admission/profile classification remains P0-07 work; this inventory is not an executable test command list.
