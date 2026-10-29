# Registration-only design under strict no-CUDA limits

Status: source-grounded design proposal, not implementation or execution authorization. The user chose “Keep strict no-CUDA limits; investigate a registration-only design” and subsequently requested consolidation into Plan 04 **with further debate before proceeding**. No package imports, tests, containers, native initialization or production-source changes were performed in this design investigation. [Plan 04](event-mapping-refactoring_plan_04.md) P1/G04-13/A04-17 and its [review ledger](event-mapping-refactoring_plan_04-review.md) govern this prerequisite; the [canonical implementation handoff](dashboard_cli_workflow_parity/research-stack-implementation-handoff.md) owns status. The contract below is frozen as a discussion baseline, not an approved implementation contract.

## Decision summary

**Current disposition — S1 contingency, not the selected approach:** Plan 04 selects S2, runtime-faithful isolated initialization through IF-A–IF-D. This document preserves S1's metadata/bootstrap contract only for an explicit evidence-backed contingency decision; do not implement it in parallel or require its manifest/context redesign before S2. S3 is another contingency and S4 complementary testing. Selecting S2 does not approve initialization effects or imply feasibility; the concrete admission packet remains pending.

If S1 is selected, use an explicitly selected immutable registration-metadata view, shared by catalogue construction and the existing graph-schema validators, with runtime class resolution kept separate. Built-in metadata should become a canonical declaration consumed by both that view and real runtime bindings—not an independently maintained catalogue, fake class registry or historical digest substitute.

This can support a bounded first-party proposal/validation path without importing simulator class modules. It is not a transparent replacement for arbitrary mutable Python registries. Keep legacy registry APIs/default behavior intact during migration. Do not globally change `get_all_keys()`, `is_registered()` or class getters merely to make E1 pass.

The design remains contingent on explicit ordering/extension policy and compatibility evidence. It does not complete E1, P1/P2 or the live trial.

## Why another import fix is insufficient

The actual pinned-image bytes show registry-driven imports reaching Isaac Lab's `utils.warp`, which calls `wp.init()`. First-time initialization constructs Warp Runtime, loads native libraries and invokes native `wp_init` before conditional CUDA capability/device queries. The no-CUDA route is not established. Quiet mode, absent devices, a later CPU default and an invented configuration flag are not substitutes for evidence.

Moving catalogue functions alone would retain their calls into global registry loading. Replacing initialization with a no-op or seeding fake runtime classes is not acceptable.

Evidence: `outputs/workflow/plan04-implementation/installed-execution/native-initialization-decision.md`, `registration-context-parent-verification.json`; independent source adjudication `deleg_1c02878c`. These establish an import-admission blocker, not that GPU work was executed.

## Source-bound semantics

| Source | Behavior to preserve or explicitly scope |
| --- | --- |
| `isaaclab_arena/assets/registries.py:30–88,345–385` | Insertion-ordered class registries; global lazy cascade for selected families; distinct EnvironmentRegistry; no successful-loaded flag on failed imports |
| `isaaclab_arena/assets/register.py:29–34,87–111` | Decorators warn and keep first duplicate; raw register rejects duplicates; asset/relation keys and task class-name keys differ |
| `isaaclab_arena/agentic_environment_generation/environment_generation_agent.py:803–955` | Asset category priority embodiment → background → object; effective ordered tags; asset/relation list order; sorted task keys; exact summaries and prompt formatting |
| `isaaclab_arena/agentic_environment_generation/spec_validation.py:18–29,52–63` | Effective constructor signature, ordered required parameters, variadic exclusion; agent-readiness/required-param issues are trace-only, not generic schema rejection |
| `isaaclab_arena/environment_spec/arena_env_graph_types.py:71–83,124–128,218–247` | Complete asset/task membership, relation arity, unchanged parameter normalization; USD resolution is separate runtime behavior |
| `isaaclab_arena/environment_spec/arena_env_graph_spec.py:63–168` | Existing coercions/defaults, identifier/reference constraints and override validation remain authoritative |
| `isaaclab_arena_examples/agentic_environment_generation/web_api/catalogues.py:22–64` | Existing compact sorted-key JSON digest over catalogue objects; list order is significant; 2 MiB ceiling |

Concrete counterexamples to a naïve static catalogue:

- `procedural_table` is defined in the object library but classified as background by tags.
- `light`, `directional_light`, `ground_plane`, and non-agent-ready tasks such as `NoTask` remain schema members even when omitted from prompt categories.
- `PickAndPlaceTaskRL` inherits readiness and has its own effective required constructor parameters; explicit decorators alone are insufficient.
- Summaries use the first nonblank line of `cls.__doc__`, not `inspect.getdoc()`. OpenDoorTask/CloseDoorTask lack class docstrings; inherited documentation would change their summaries.
- Alias registration and a custom class registered before built-ins affect keys and duplicate winners. Alphabetical sorting would change catalogue bytes/digests.
- Effective tags/readiness/signatures are currently live. Mutating class tags can change classification. Immutable selected metadata is an intentional capability boundary, not equivalent to arbitrary live mutation.

## Proposed ownership and interfaces

All new module/API names below are proposed, not existing symbols.

### 1. Canonical declarations and immutable selected view

Proposed pure owner: `isaaclab_arena/assets/registration_metadata.py`.

Descriptors contain:

- Asset: explicit registry key, trusted runtime module/qualname, effective ordered tags.
- Relation: explicit key, trusted runtime module/qualname, unary flag, exact owned summary/documentation.
- Task: explicit class-name key, trusted runtime module/qualname, effective agent-ready flag, ordered required parameter names, exact owned summary/documentation.
- Selection: schema/version, ordered registration set, declaration/source identity, explicit extension policy.

Include all schema members, not merely prompt-visible entries. Runtime module/qualname is trusted declaration data; never import a target supplied through a GraphQL contract or arbitrary file path.

A frozen `RegistrationView` exposes only metadata operations such as membership, ordered enumeration, arity and task constraints. It holds no classes and performs no dynamic module loading. Unknown or unrepresented entries reject explicitly. It must not silently fall back to runtime registration.

Move built-in authoritative metadata out of independently duplicated class literals: runtime classes/decorators consume the declarations. The executable constructor still owns argument binding; when actual classes are bound in a separately permitted runtime, verify target identity, ancestry, effective metadata and constructor contract. Do not forge `__signature__` or wrap constructors to create apparent parity.

This migration is more than adding a JSON cache. It requires reviewing the affected built-in assets, embodiments, relations and tasks. Class docstrings/tags/inheritance/mutable aliasing need explicit treatment; metadata ownership must not be split across two divergent definitions.

### 2. Preserve runtime registries and their compatibility surface

Keep existing class-returning APIs and legacy default enumeration behavior initially. Add a separate metadata view rather than changing what a declared-but-unloaded entry means to existing decorators.

Distinguish descriptor declaration from actual class binding. A declaration cannot make `register_asset` believe the real class is already registered. Preserve raw-register versus decorator duplicate behavior in legacy mode. In the selected immutable mode, reject collisions and unrepresented extensions; do not reinterpret first-wins histories.

No redesign of device/HDR/policy/retargeter/environment registries is needed for the first metadata boundary. Their actual runtime loading remains outside no-CUDA execution.

### 3. Pure catalogue projection

Proposed pure leaf: `isaaclab_arena/agentic_environment_generation/catalogues.py`.

Move dataclasses/formatters and metadata-backed builders here. Clean consumers import this leaf directly; legacy agent/web exports can retain object identity through reexports or explicit adapters where that does not pull runtime dependencies back into the clean path.

Preserve field names, strings, ordered tags, category precedence, asset/relation order and sorted task keys. Keep the existing digest algorithm and payload meaning. Compare canonical bytes before comparing hashes.

Legacy builders accepting injected class registries must remain supported on their legacy path; do not coerce those registries into a closed-world view silently.

### 4. Existing schema, explicitly supplied metadata

Do not create a second lightweight Pydantic schema. Modify only the registration-dependent lookups in the current validators and agent-validation helper; leave normalization/defaults/coercions/reference constraints and trace-versus-reject semantics intact.

Recommended propagation: explicit trusted validation context carrying the frozen view, threaded through `model_validate`, JSON parsing and convenience constructors, plus explicit catalogue/helper arguments. Absence of context preserves the legacy path; managed proposal mode must require the context, with no native fallback. Avoid process-global registry replacement or ambient thread-local selection.

This is an API design obligation: nested models, `from_dict`, SpecInference construction/parsing, worker receipt revalidation, parent adoption and concurrent offloaded calls all need a complete propagation map before implementation. A call that accidentally uses ordinary construction can reenter the native cascade; isolation tests must catch it.

Public request fields do not supply authority. Composition chooses the view, and the worker receives only its exact selected identity. It independently opens the same trusted declaration revision and compares identities before model initialization/paid effects. A mismatched or unavailable view fails closed.

## Two identities, not one overloaded hash

Preserve the existing execution-catalogue digest for the exact prompt vocabulary projection. It omits hidden assets and non-agent-ready tasks and therefore is not a complete schema identity.

Bind the complete descriptor/validation source revision separately in the managed execution selection and exact worker/adoption contract. The discussion baseline below selects a new opt-in versioned request/worker binding, not a mutation of immutable V1 receipts. Exact existing codec insertion points and limits still require a source-backed propagation map before implementation; do not claim current wire formats already carry this identity.

Replay must return retained identities without rebuilding a newer default view. Changed metadata/order must not rewrite old receipts or candidate bytes. New incompatible selections require new explicit identity/versioning.

## Scope of the no-CUDA path

Parent source adjudication narrows a generic native-generation concern:

- Current `BoundedSceneModels.generate` calls the real agent with `proposal_only=True` (`workflow/scene_engines.py:177–186`). `generate_spec` returns at `environment_generation_agent.py:225–228`, before prim-path inference at `247–252` and spatial/native validation.
- Refinement likewise passes `proposal_only=True` (`scene_engines.py:214–223`) and returns before native grounding (`environment_generation_agent.py:457–460`). Its earlier `_discover_candidate_affordances` is string classification (`621–632`), not USD inspection.
- `PrimPathInference.infer` defers USD loading until call time (`prim_path_inference.py:55–60`). Constructing that helper is not the same as calling it.

Therefore native grounding is not proven to be an unavoidable second runtime blocker for E1's existing proposal-only route. This is source reasoning, not a successful cold-import/execution proof. The agent's current top-level registry/RelationBase imports still must be separated.

Keep the real proposal-only contract and its existing warning: schema validity is not grounding, physical validity or policy success. Full generation, `resolve_usd_path`, runtime conversion, relation placement validation, simulator/native capture and policy execution remain outside this design. Do not skip an operation that the selected mode actually requires and then claim equivalent behavior.

## First implementation contract to approve

The following is the **fixed S1 candidate discussion baseline**, not authority to implement or a requirement on other routes. First choose the strategy under Plan 04 P1. If S1 is chosen, these policies make its contract concrete without inventing an enumerated manifest, final bytes or proven compatibility. Changing a row requires an explicit design revision and review; unanswered details block S1 implementation rather than trigger more implicit probing.

| Decision | Proposed first-mode contract | Still to debate/verify before implementation |
| --- | --- | --- |
| Ordering/version | First-party immutable selection with a versioned descriptor schema and content-addressed declaration revision. Asset/relation enumeration uses explicit ordered declaration lists; task projection retains sorted keys, tag/required-parameter sequences retain their semantic order, prompt formatting keeps its existing independent sorting. No discovery-based or guessed alphabetical replacement for registry insertion order. Every membership/order/semantic change changes full metadata identity; incompatible schema/validation semantics require a new version. | Agree the selected built-in membership and explicit ordered lists. They have not been enumerated/frozen as an executable manifest. Where historical order cannot be established within authority, require an explicitly named new selection; never claim historical digest equality. |
| Extensions/mutation | First mode is closed to undeclared plugins, aliases, duplicate keys and post-freeze metadata mutation. Known first-party aliases must be explicit declarations. Unsupported extensions reject before model initialization, never disappear silently. Legacy class registries preserve first-wins decorator behavior and raw-register uniqueness. A later extension requires a pure, reviewed contribution and a new selection identity, not runtime discovery. | Confirm that this opt-in capability boundary is acceptable for the first installed mode; review concrete legacy extension/alias callers. No arbitrary extension equivalence is promised. |
| Metadata identity/wire | Keep the existing ordered vocabulary projection/digest untouched in meaning. Add a separate versioned full-metadata binding to **new-mode accepted request identity, immutable generation/refinement worker packet, result receipt and parent adoption checks**. Bind descriptor schema/selection/revision, canonical complete descriptors including order and hidden members, and validation-source/codec revision. Composition chooses the trusted view; server/worker must agree before model initialization. Absence is allowed only on the unchanged legacy path. No V1 receipt rewrite or reinterpretation. | Identify exact existing versioned codecs/fields and size limits in one source-backed map. Define canonical byte encoding and digest coverage before code; the conceptual binding is not an existing symbol or observed wire format. Decide eventual runtime worker verification without bypassing runtime ancestry/constructor validation. |
| Validation context | Keep the real schema. Pass the verified immutable view explicitly through root/nested model validation, `from_dict`/JSON helpers, SpecInference parsing and repair, generate/refine initial/returned specs, worker receipts and parent adoption. Managed mode requires context at every seam; missing context fails before legacy fallback. Ordinary legacy calls retain their behavior. No process-global registry replacement or thread-local implicit selection. Preserve trace-only checks, coercion/default/normalization and cross-reference semantics. | Freeze the complete call-site map, including `scene_engines.py:130,212` revalidations and `spec_inference.py:87,151` task tracing. Decide safe adapters for convenience constructors that cannot forward context and prove concurrent views remain separate. |

Required artifact before implementation approval: one bounded contract listing the chosen order/membership, codec/context call-site map, owned files, exact permitted tests/resource envelope and unresolved runtime-parity gate. Source-only mapping must stay inside Plan 04's architectural investigation budget; mapping a design does not authorize native class imports. The user may revise any proposed row during the current debate.

## File-owned implementation slices, after approval

| Slice | Main source surface | Acceptance |
| --- | --- | --- |
| Metadata foundation | New metadata leaf; relevant built-in declaration migration; narrow `assets/register.py`/`registries.py` integration | One metadata authority; complete membership; no runtime import on descriptor construction; declaration vs class binding distinct |
| Pure projection | New catalogue leaf; agent and web catalogue callers | Exact projection/format/digest semantics for the explicitly supported selection; legacy adapters remain explicit |
| Real validation | Existing graph type/spec models and `spec_validation.py`; SpecInference and validation callers | Explicit context propagation; unchanged normalized output and trace/reject boundaries; no native fallback |
| Worker/application binding | Existing `scene_worker.py`, generation protocol/adoption, `scene_engines.py`, installed composition and foreground adapters | Exact metadata/candidate/receipt binding before effects; same shared application/coordinator and real synthetic SDK transport |
| Compatibility/acceptance | Existing admitted tests plus separately reviewed pure/isolated cohort | Cold validation, deterministic negatives, joined client→owner→worker→fresh reader, unchanged native denials and exact cleanup |

Built-in migration potentially touches the background/object libraries, embodiment metadata (including inherited bases), relation definitions and registered task modules. This is a bounded cross-cutting refactor, not a one-file fix. No protected IsaacLab submodule/deployment change is part of the proposal.

## Required tests and honest limits

For S1, before claiming isolated completion:

- Cold import AND actual real-schema construction under unchanged native/Warp/CUDA/USD/provider denials; no fake runtime module/registry injection.
- Complete membership positives for `NoTask` and hidden assets; unknown keys; unary/binary reference rules; existing normalization and cross-references.
- Inherited readiness/tags/signatures, positional-only/keyword-only/variadic/default cases, direct empty docstrings, tag ordering/category priority.
- Explicit order/alias/duplicate/mutation/extension dispositions; ensure unsupported cases are reported, not omitted.
- Canonical catalogue bytes and prompt strings, then digest equality wherever parity is actually claimed; separate full metadata identity and semantic changes hidden from the vocabulary digest.
- Concurrent independent validation contexts and every parent/worker revalidation seam; mixed/missing metadata identity rejects before model initialization.
- Exact retained replay under changed defaults without record rewriting; server-worker mismatch refusal and required-policy refusal before effects.
- Actual joined synthetic E1 with real shared ownership/SDK serialization, second-client readback and cleanup; component counts alone are insufficient.

Separately gated: real class identity/constructor/ancestry/metadata parity, native runtime conversion and custom extension behavior. Strict no-CUDA tests cannot establish those by importing the prohibited runtime classes. Historical digests or fixtures are corroboration, not substitutes for that missing comparison. Registration-only capability may be implemented/tested before runtime parity, but must not be certified as a transparent legacy replacement or live-ready.

## Review disposition and remaining decisions

Independent analyses: `deleg_42c38c89` task 1 (candidate ownership/design) and task 2 (compatibility challenge). Both were read-only. Parent accepted the separation and counterexamples, but narrowed the proposal to opt-in metadata instead of global registry-enumeration changes, and distinguished E1 proposal-only generation from generic native grounding.

Open before implementation: user agreement on the discussion baseline; concrete built-in ordered manifest; exact canonical identity encoding and backward-compatible codec/context map; strategy and authority for eventual runtime parity. Policies are now explicit above, but these artifacts and acceptance evidence do not yet exist. Consolidation into Plan 04 is not observed acceptance or permission to resume.

Final fresh source challenge `deleg_b369d6f0`: **PASS limited to the design proposal**, with no concrete blocking contradiction found. It verified the selected proposal-only early returns, string-only affordance discovery, remaining import/validation-context obligations, registry compatibility counterexamples and separate metadata identity. This is neither implementation approval nor no-CUDA runtime proof. Scoped documentation hooks and `git diff --check` passed; no application tests were run in this design phase. Input/source hashes and final document identity are retained in `outputs/workflow/plan04-implementation/installed-execution/registration-only-design-verification.json`.

Canonical status remains: E1/P1 incomplete, strict no-CUDA stop in force for native registration, existing software and failed evidence preserved. No application source changes or runtime execution were performed for this design. The earlier review/hash is a historical design snapshot; the five-document consolidation has separate documentation-only verification at `outputs/workflow/plan04-planning/registration-consolidation/`. Plan 04 §8 supplies the prospective chain-wide investigation limit; this document does not create a separate goal or budget.
