# Making the accepted V7 design functional

## Prototype priority override

The latest user instruction is functionality-first: expose the existing README harness through TanStack to validate the prototype. F0–F8 below remain a capability/reference map, not a mandatory release-hardening sequence before missing features. Reuse the completed authoring/storage and existing New/Refine/Graph-RAG/publication paths; connect missing build/evaluation/research runner actions through narrow adapters. F8 production URL/proxy/authentication/deep-link work, expanded recovery coverage and optional displays do not block that implementation. Keep current security and execution controls, and require separate approval for actual model spend, graph writes, GPU work and protected infrastructure changes.

Status: reviewed plan; remaining feature implementation explicitly authorized. F0 verification repair and F2/F3 feature work are active; F1 source/scoped reviews are complete but integrated acceptance and deployment remain pending. The user accepted V7's design direction and authorized parallel implementation with independent review. Preserve `outputs/ui-previews/v1/` through `v7/` unchanged. This appendix extends the [canonical plan](../dashboard_cli_workflow_parity.md) and [endpoint contracts](endpoint-contract-plan.md); it is the recommended U3 delivery sequence, not a competing architecture or authorization for live effects.

## 1. What “functional” means

Separate three deliverables:

1. **Operational authoring core:** real approved documents and managed versions; Arena validation/schema/registry inspection; source-bound authored properties and supported reviewed edits; duplicate-safe durable saves, explicit recovery and downloads; actual source-bound asset/scene snapshots; real job observation. No synthetic schema, version allocation, job counts or image association may stand in for these operations.
2. **Complete agreed research workbench:** New/Refine, actual consumed priors, research persistence/publication, Neo4j query, jobs/diagnostics, build/full, policies/experiments/evidence, heal/DCRG/controller trials and supported advanced profiles. Every enabled C01–C21/option row needs its own acceptance evidence. Core completion is not full parity.
3. **Optional interactive display:** approved native Kit and/or ovstage + ovrtx + ovstream profiles with actual ownership/authentication/resource/input acceptance. Static snapshots can make the core visualizer functional without waiting for this. Rendering is not physics; simulation-state mirroring is an additional explicit contract.

V7 visual approval does not approve paid calls, GPU jobs, database writes, migrations, infrastructure edits or public/multiuser deployment. The user has now authorized implementation of the plan. Begin with F0/F1 and advance through dependency-ordered, independently reviewed code slices; the live-effects and protected-infrastructure gates above still apply.

## 2. Integration architecture and source ownership

The authorized [F3 UI-storage extension](ui-storage.md) specifies the controller/sessionStorage/IndexedDB implementation, migration and rollback boundaries, and storage-race acceptance matrix. It supersedes the temporary UI pause recorded in earlier progress, not the existing backend/retry/security contracts or live-effect gates.

**Port the design into the production app; do not connect the offline preview in place.** Keep the preview entry/build/CSP and no-network/no-storage tests intact. Never import PreviewApp or its synthetic inspector, fake version allocator, job fixtures or workflow reviews as operational controllers.

Existing production path:

    main.tsx → App → ThemeProvider / QueryClientProvider / RuntimeProvider
                  → production routes and shared authoring/observation controllers
                  → V7-derived presentation or retained legacy presentation
                  → existing ApiClient / domain services / owned workers

New component/hook names are to be chosen during implementation; the paths below identify current reuse/extraction owners, not files already created by this plan. Pure presentation may be shared with preview only if its dependency tree remains free of runtime/session/API effects.

| Area | Existing source to reuse or extract | Required change |
|---|---|---|
| App, navigation and appearance | `web/arena-workbench/src/main.tsx:5–16`, `app.tsx:48,529–598`, `theme.tsx`, `theme.css`; V7 shell/panel/branding presentation | One ApiClient, QueryClient, ThemeProvider and RuntimeProvider, not one per workspace or layout. Add a frontend-local legacy/V7 presentation selector outside optional imports. Preserve `/`, `/workspaces/default`, `/neo4j`, `/developer/diagnostics`, `/jobs/$jobId` and existing search contracts. Scope V7 styles instead of loading its global CSS into the legacy app. |
| Authoring state | `editor.tsx:65–135,159–255,299–321,359–425` | Extract one persistent authoring controller above temporary panels/layout changes. Retain catalogue ID, loaded view, raw draft, prompt, New/Refine, retrieval policy, validation owner, recovery, candidate/accepted-request state and presentation selections explicitly. Existing `editor-draft` cache does not retain every one of these fields. |
| YAML editor and inspection | `code-editor.tsx:25–35`, `metadata-browser.tsx:39–60`, `editor-contracts.ts:23–57`, `GraphHost`/GraphExplorer/PropertyTree | Use CodeMirror for real YAML and server validation for authored projection. Add a controlled graph/inspector selection seam and a source-location focus API. Replace V7 JSON parsing and regex finding navigation, not just its fixtures. |
| Observation/activity | `runtime.tsx:25–113`, `observation.ts:48–143`, reconciler/workspace cache, `app.tsx:294–413` | Derive activity, journal and exact-job inspector from the same reconciled snapshot/event cursor. Reuse StatusBadge/JobInspector and authorization controls; no second SSE connection or mutable fixture feed. |
| Generation and settings | `useEditorJob`/EditorJobProgress, GenerationEvidence, GenerationReauthorization, ModelSettings and editor New/Refine handlers | Preserve capability checks, exact request retention, private credential writes, candidate eligibility and source-detachment logic. Never forward unsupported preview fields or preserve raw credentials in hidden panels. |
| Library, versions and publication | V7 picker/comparison presentation; production ResearchVersions/VersionBrowser, PublicationPanel/checkedBinding/PublicationControls | Replace PreviewSelection/exampleFamilies with typed source/managed-version adapters. Preserve each save/recovery scope and exact commit/binding checks. Do not associate publication with whichever editor version happens to be selected later. |
| Images and rendering | `snapshots.tsx` useSnapshots/SnapshotImage/AssetGrid/SnapshotGallery/SnapshotControls and snapshot-model | Reuse authenticated cache/artifact handling and explicit job submission, not V7's embedded-image URL adapter. Separate cache identity, requesting job and physical origin job. Keep automatic preview off by default. |
| Query workspace | `neo4j.tsx:29–64,159–183` and independent GraphHost | Query/params/submitted result state is component-local today. Deliberately lift or retain it with session-scoped ownership so navigation matches V7 without mounting hidden query effects. Preserve scalar rows, stale/truncated states and explicit execution. |

### Visibility is not lifetime

V7 keeps hidden panels mounted. Applying that strategy wholesale in production can keep automatic rendering consent/scheduling active and bypass credential-field unmount cleanup (`automatic-preview.ts:28–55`, `snapshots.tsx:189–209`, `model-settings.tsx:69–78`). Specify separately:

- persistent nonsecret controller state;
- whether a view is visible/active;
- lifetime of observation, renderer/camera work and credential DOM nodes;
- source/session/selection/options epochs used to reject late callbacks and consent revival.

Global job observation may continue under the existing session. Leaving an execution surface must retire automatic-preview consent and any sensitive input; hidden renderers must pause/dispose according to their resource contract. Preserve drafts and frozen reviews without preserving passwords, automatic dispatch or input-control authority. A layout toggle must not reconnect the session or create a new cache.

## 3. Real authored-data and edit contract

The preview format is not a production wire model. Use runtime-checked projections from current, owned `Validation`, retaining raw YAML as the editable authority. `validation.spec` is normalized data with defaults/coercions; serializing it is not a source-preserving edit.

| V7 concept | Real Arena meaning / first supported behavior |
|---|---|
| Asset list | Distinguish embodiment, background and object AssetSpec `{id, registry_name, params}` from object_reference `{id, parent_id, prim_path, object_type, params}`. No universal parent/pose/scale record. Scope node and index-based relation identities to the exact validation result. |
| Position | Optional `params.initial_pose.position_xyz`: meters in the environment frame, not parent-local fixture units or measured runtime world position. Missing means not authored, not zero. |
| Rotation | Optional `params.initial_pose.rotation_xyzw`: quaternion **X,Y,Z,W**, not V7's Euler degrees. First supported rotation form must edit/review the quaternion atomically with finite/length/nonzero/normalization checks. Freeze a tolerance policy against the actual consumer; never silently normalize. Editable Euler remains unavailable until conventions and round-trip/singularity tests exist. |
| Effective placement | For objects, conversion applies initial_pose only when anchored or without non-anchor subject relations, and when the asset supports set_initial_pose. An `on`-constrained object's initial_pose edit can be ineffective. Such correction stays disabled with the controlling relation shown; do not promise it moves the rendered object. Embodiment/background support also needs an approved registry/constructor mapping. |
| Scale | Optional, registry-specific `params.scale`; dimensionless, not measured dimensions and not automatically unity. Display authored values/default provenance honestly. Keep generic scale editing unavailable until support and effective defaults are characterized. |
| Parent/prim | Object-reference parent_id is a reference into its parent asset, not a generic transform hierarchy. prim_path can be unresolved. No PNG picking or runtime-reference transform editing without verified mapping. |
| Registry metadata | Current catalogue names/tags are useful for inspection but are not typed constructor signatures, parameter-effectiveness guarantees or resolved USD dependency identities. Broader editing needs a versioned allowlist of supported descriptors, without constructing assets/loading USD to populate forms. |

Source: `isaaclab_arena/environment_spec/arena_env_graph_types.py:37–103`; `arena_env_graph_spec.py:38–60,86–145`; `arena_env_graph_conversion_utils.py:127–185,210–241`; `isaaclab_arena/utils/pose.py:20–30`; `isaaclab_arena/assets/object_base.py:149–189`. Pose itself checks tuple lengths, not all numerical/normalization semantics; ordinary schema validity is insufficient editing eligibility.

### Narrow source-preserving edits first

Implement local proposals over **existing explicit numeric leaves in root-authored, supported initial_pose mappings**. The first release must explicitly identify its supported registry/role/constraint cases. No ID rename, registry swap, general parenting, implicit pose construction or arbitrary constructor editing is included by accident.

1. Bind the review to session/selection epoch, returned loaded-view ID, original source/include identity, exact draft bytes/hash, validation identity, node/path, old value and edit-options epoch.
2. Prove a unique explicit root YAML node and leaf using a bounded concrete syntax/source-range representation. Characterize the installed CodeMirror/Lezer YAML parser before relying on it; its availability does not prove round-trip safety. If it cannot prove the mapping, refuse the edit and use the raw editor/read-only inspector until a reviewed mapping solution exists. Do not add a parser dependency silently.
3. Replace only the proven source range(s). Untouched comments, quoting, order, whitespace, unrelated parameters and include declaration remain byte-identical. Do not use JSON.stringify, whole-document safe_dump, regex key search or normalized spec serialization as a hidden rewrite.
4. Validate the candidate through E014 with the **same returned view ID** and compatible authoring checks. Candidate validation belongs to the candidate, not the current draft. Validate shape/numbers/effectiveness for the supported editable surface; general open-ended params must not inherit a false physical-validity badge.
5. Show the exact edit/full diff and separate candidate diagnostics. Structured Apply requires successful validation of the exact candidate **and** successful supported-editability checks, plus explicit consent and matching source/session/selection/options epochs. Pending, failed, invalid or stale candidate validation disables Apply. Recheck every identity/epoch at the click; A→B→A cannot revive consent. Apply once to the local draft, invalidate current validation and obtain fresh validation. It does not save, publish, render or execute physics.
6. Keep unsupported/ambiguous fields read-only with a reason. Do not advertise the inspector as fully functional until the documented supported edit cases actually pass this flow.

No new proposal/apply endpoint is needed for this narrow local path. N24 remains runtime-prim→authored translation and is not a prerequisite or substitute. Structured server diagnostics/source origins and approved editing descriptors may extend E014/E003; those are additive contract work, not a new editing service/authority by default.

### Include and source-location boundaries

The current editor resolves one frozen relative `external_yaml` within approved roots, forbids nested includes and rejects duplicate top-level keys across root/include. This is composition, **not override semantics** (`workbench/documents.py:125–190`, `workbench/document_yaml.py:15–71`, `environment_spec/arena_env_graph_yaml_loader.py:16–61`).

- Included assets are inspectable but read-only for the first structured-edit slice. Do not add root `objects:` to override an included objects list.
- Missing/defaulted/normalized fields and shorthand have no proven root edit range. Do not fabricate one from canonical paths.
- Included-file editing requires a separate approved bundle contract or explicitly detached flatten-and-edit operation. Preserve the original source and lineage; never silently write includes or flatten under a source-preserving label.
- Require expected_source_hash for source-bound saves, together with the loaded view and frozen include context. Detached New uses its separate semantics, never a stale source ID.
- Frozen view IDs are memory-backed. After API restart, re-establish verified source/bundle identity; a remembered view ID alone cannot restore authority or prove unchanged includes.
- E014 errors/warnings are currently strings. Add structured findings/origins only where reliable, retaining legacy fields for compatibility. Extend CodeEditor with an owned source-location focus command. Declare offset units and handle UTF-8 bytes versus JavaScript/CodeMirror UTF-16, CRLF and Unicode. If no precise mapping exists, focus the specification with an explicit unmapped finding; never select a guessed field.

## 4. Ordered implementation slices

These F IDs organize **U3 integrations** and map to existing P dependency phases. They are not new services or a replacement phase ledger. Complete each slice with real isolated UI→API→readback evidence before enabling its mutations. Implementation, deployment and separately authorized live evidence remain distinct.

| Slice | Concrete work / dependency | Exit evidence |
|---|---|---|
| F0 — freeze migration and safety contract | Capture current production editor/query/job behavior and V7 archive hashes. Freeze layout switch/fallback, persistent controller ownership, active-effect retirement, typed projection/editability and supported field/options matrix. Establish no-egress-before-import API/browser tests with synthetic stores, no live credentials/research volumes. Record target/configuration owners without changing protected infrastructure. P0/C17. | Reviewed state/effect/identity map and actual isolated test preflight; no parser/app construction outside isolation. No blanket baseline pytest against the live environment. |
| F1 — real shell, document and read inspection | Port V7 presentation into production App/Shell under existing providers; extract shared authoring state without mounting two active editors. Reuse CodeEditor, MetadataBrowser, owned E001/E004/E012/E003/E014 data and controlled GraphHost selection. Real session/deadline/disconnect UI; actual activity/queries via existing observation and explicit query actions. Keep unsupported mutations unavailable. P1/C01/C02/C09/C17. | Real approved YAML loads into V7 layout, invalid/current/stale states are correct, schema/registry and authored roles/relations/tasks are real. Legacy↔V7 switching, query/jobs navigation and reload preserve permitted state without duplicate streams, hidden scheduling or secret retention. No model/GPU/graph writes. |
| F2 — real supported inspect-and-correct | Implement section 3's runtime-checked projection, constraint-aware edit eligibility and source-preserving candidate editing. Add structured diagnostics/focus or explicit unmapped fallback; preserve explicit apply/revalidation. Quaternions and registry support require characterization, not preview conventions. P1/P2, C04/C09. | Exact root numeric edit→candidate validation→diff/consent→apply→revalidation; unchanged unrelated bytes, read-only included/unknown fields, stale/ambiguous/ineffective edits blocked. Raw YAML remains editable/downloadable even when invalid. |
| F3 — durable save, Library and recovery | Complete X03/N15 duplicate-safe editor save and crash/readback semantics. Add typed source/family discovery (E001 extension/N12; N13 only if needed). Reuse real managed version reads and comparison; store nonsecret references for pins/recents, not preview YAML copies. Preserve production tab recovery and separate retry stores. Complete X05 editor_revision source variant before numbered research save of manual edits. P2/C07/C09. | Lost save ACK/restart cannot allocate duplicates. Source/include CAS and actual revision bytes verified. Candidate save remains candidate bytes after manual edits; manual numbered save uses verified editor-revision provenance. Pin/open/compare uses exact identifiers and successful opens; quota/malformed preferences do not erase recovery. |
| F4 — real current-draft snapshot workflow | Reuse E013/E009/E002 and production snapshot controllers. Complete X02/X09 identity/origin projection; enforce actual 512/1024 options and eligibility, lease/cleanup safety and separate asset/scene semantics. Link only actual job IDs and verified artifacts into the shared activity/inspector. P2/P3/C10/C17. | Explicit approved render request→exact requesting job→matching canonical/options/dependency receipt→decoded actual pixels. Cover partial/error/missing/historical states and version switch during render. Cache reads/image retry do not submit work; unknown origins produce no invented job link. GPU acceptance requires its own target/budget. |
| F5 — generation, settings, query and publication completion | Reuse existing New/Refine, private ModelSettings, useEditorJob, GenerationEvidence/Reauthorization and ResearchVersions/PublicationPanel/Controls. Finish supported strict settings/options, exact consumed-prior and retained-request integration. Complete X07 feature-off recovery and store/graph compatibility. Existing save-time preparation remains separate from write; later preparation N16 is a decision-gated extension. P1/P2/C03–C08/C17. | New without template/base fields; refine with exact base; reviewed candidate/apply independent of save/render. Actual authorized provider/retrieval and publication receipts when approved, no fake query-derived prior evidence, no repeat inference on publication recovery. Query browsing remains read-only and separate from publication. |
| F6 — remaining research workspaces | Implement existing P3–P5 obligations through typed run/profile/validation/disposition adapters, secure artifact manifests/media and existing authoritative domain services. Build/full → policy/evidence/experiments → heal/DCRG/controller trials; complete queue snapshot/consent and GPU handoff before dispatch. Proposed N01–N11/N25/N26 are selected by actual workflow need, not all required for F1. | C11–C16/C19–C21 and relevant C20 options have exact input/effective-limit/child/evidence/cleanup receipts. Preserve generation on build failure, unattempted experiment children, DCRG authority/outbox and specific controller contracts. No “generic jobs can execute anything” shortcut. |
| F7 — optional interactive displays | Separately approved compatibility spike, then N17–N24 native/ovrtx profiles. Stage/dependency identity, authenticated client/signaling/media/input, controller grants, bounded GPU/NVENC resources and owned release. Keep current snapshots as fallback. P6/C18/C20. | Native display and browser streaming independently tested; no-op/unimplemented modes not advertised. Camera/picking never grants physics, source edits or publication. Simulation mirroring and editable Euler/runtime transforms require their own contracts. |
| F8 — controlled rollout and handoff | Per enabled slice, build the production entry, verify real same-origin proxy/auth/routes/deep links and perform the accepted V7 journey. Retain compatible legacy fallback and accepted-operation observation; update runbook and capability status. Finish P7 only when all agreed executable rows have receipts. | User-accessible working HTTP URL and exact enabled-feature report, not a container path/file preview. Retained requests/drafts survive supported rollout/rollback; old/incompatible binaries cannot mutate newer records. No silent store migration or data deletion. |

**Dependency order:** F0 → F1 → F2 → F3 → F4 forms the recommended operational authoring core. Read-only activity/query/metadata work can proceed independently within F1; existing generation control extraction may happen there but does not enable live spend. F5 completes the model/publication branch under separate permissions. F6 follows its actual storage/identity/resource prerequisites; F7 is not a prerequisite for core authoring and cannot substitute for physics acceptance. F8 gates each deployment increment as well as eventual full release.

Do not wait for every future endpoint or SDK before producing a useful core. Conversely, if F3 manual numbered persistence or F4 real snapshots are incomplete, call the result a narrower slice—not fully functional V7.

## 5. Persistence and observation details that cannot be skipped

### Editor revision versus research version

Legacy unkeyed E011 allocates a fresh revision; immutability alone does not imply duplicate-safe retry. The keyed source implementation now pairs E011 with E047 (`GET /api/editor/save-requests/{idempotency_key}`), superseding N15's earlier alternate URL. Initial authenticated restart/replay/reopen coverage passes; full X03 fault/security/UI acceptance is still required. Preserve one request→one revision, same-key/different-payload conflict, exact verified disposition and explicit frozen retries; no automatic replay.

E038 persists an exact accepted generated candidate job/attempt/generation. **Saving the edited draft is a different source contract.** Extend that route/domain with a strict union of accepted_candidate and editor_revision over the same ResearchStore/Journal. The editor revision must be immutable, read back, validated and explicitly parented. Update reservation/manifest validation, list/detail source fields, frontend decoders, CLI adapters and publication projection/preparation assumptions together. Never make up a generation job or receipt, overwrite candidate bytes, or create a second version manager.

Keep raw draft download, flattened editor export, editor revision, numbered research version, preparation and publication separately named. Later preparation of unprepared versions remains unavailable unless N16 and immutable binding semantics are implemented. Research-save recovery for the declared same single-operator principal and original-session-bound publication recovery are different policies; preserve that difference.

### Opening saved sources is also contract work

E004 now loads discovered documents and keyed `editor-revision:<32hex>` descriptors into fresh frozen views. E010 exports flattened editor YAML; E039/E040 inspect/download managed research versions. Exact configured-store research-version opening is now implemented at the API/domain boundary; production UI integration is pending. These IDs and responses are not interchangeable: a research reservation cannot be passed to the loader as though it were an issued editor view.

The typed **openable source descriptor** and resolver are implemented for keyed editor revisions; extend the same authority to exact managed research versions rather than adding another source store. The research resolver now accepts exact `research-version:<store_id>:<reservation_id>:<manifest_digest>` descriptors and returns a fresh view plus `research_identity`; its UI consumers and final acceptance remain incomplete. Support discovered_file, editor_revision and research_version as distinct origins; preserve their original identifiers rather than synthesizing paths. Return exact origin/manifest and raw/canonical/bundle identities with the new frozen view. Reject unknown kinds, malformed IDs, digest mismatch, uncommitted versions and paths outside approved roots before exposing an editable source.

For immutable revisions, load and verify the stored root/include bundle, not current mutable include files. Adapt load/validate/save source checks to the explicit immutable-bundle origin; do not silently skip validation or apply mutable-file CAS to an unrelated export path. If only a flattened artifact is available, require an explicitly labelled detached materialized copy and preserve its known origin; do not claim source-preserving bundle recovery. UI Open, pin resolution, comparison and post-restart recovery must use the supported descriptor/view contract. This extends existing source authority, not a second library store or arbitrary-file API.

F3 cannot be called complete merely because a save returned an ID or download worked: an exact committed saved source must be reopenable through the supported editor contract, or its limitation must remain an explicit uncompleted core requirement. API restart must create/revalidate a fresh view from verified durable identity, not revive an old memory-only view ID.

### X05 source-bridge implementation requirements from the code audit

The authenticated API adapter now preserves flat candidate requests, accepts tagged candidate references and manual `source: {kind: "editor_revision", editor_revision_id, source_hash, canonical_hash}` with an explicit nullable `parent_revision_id`, and derives the full source proofs server-side. Commit envelopes remain unchanged; list rows add exact source metadata and nullable `open_source`, with `source_job_id` only for candidates. Authenticated editor capabilities advertise `manual_research_save` and `research_version_open` only with configured research roots. Manual publication remains unsupported. Forty-six scoped HTTP/core tests pass; UI integration, source-aware consumers and final API review remain outstanding.

Domain implementation now exists, with scoped tests recorded in implementation progress; authenticated API/opening integration and downstream consumers remain active work, not accepted functionality. The implementation contract is:

- `Documents.load_revision_bundle(revision_id, *, protect_snapshot=None)` and `Documents.verify_revision_bundle(revision_id, bundle, *, protect_snapshot=None)` expose detached, reject-only-protected portable evidence. Fields are exactly `schema_version=1`, `codec="arena-editor-bundle/v1"`, `receipt`, `snapshot`, `export_yaml`, `bundle_sha256`. The bundle digest hashes UTF-8 JSON `["arena-editor-bundle/v1", receipt, snapshot, export_yaml]`, using sorted keys, compact separators, finite values and `ensure_ascii=False`.
- Manual persisted source fields are exactly `kind="editor_revision"`, `schema_version=1`, `editor_revision_id`, `source_hash`, `canonical_hash`, `bundle_codec`, `bundle_sha256`, `receipt_sha256`. The receipt digest retains the existing research ASCII-escaped canonical JSON codec; raw and canonical scene hashes are not changed.
- `ResearchStore.persist_editor_revision(family, workflow_id, *, source, bundle_loader, approval, parent_revision_id, publication_request=None)` uses explicit `persist_editor_revision` approval. Committed replay can pass `bundle_loader=None` and verifies copied evidence; noncommitted work requires the same verified source. Every non-None manual publication request is currently rejected before reservation/source loading.
- Self-contained artifacts are `environment.yaml`, `editor-snapshot.json`, `editor-receipt.json`, `export.yaml`, and reservation `source.json`. Snapshot/receipt artifacts use the editor codec; existing research manifest/commit envelopes and legacy candidate wrappers remain unchanged. `research_source.py` provides strict dispatch and shared source/artifact verification for the subsequent consumers.

The remaining integration requirements are:

- Reuse the existing ResearchRegistry/ResearchStore and Journal. Add strict `accepted_candidate` / `editor_revision` source dispatch; preserve the exact historical five-field untagged candidate source and existing flat API request through explicit legacy adapters. Never insert fields into old hashed reservations/manifests or rewrite old same-key responses.
- Require an explicit family and explicit parent decision for manual saves. Bind only a verified committed keyed editor revision, not a mutable view or client-supplied include bundle. Introduce a public reject-only-protected bundle loader; do not reach into `Documents.frozen`, private revision internals or flattened downloads from ResearchStore.
- Copy exact authored root, frozen includes, flattened export and checked revision evidence into the existing immutable research artifact envelope. Specify editor and research JSON codecs separately. A committed research version must remain readable/openable after the original editor storage is removed; incomplete retries must re-establish their exact bound source rather than substitute a newer revision.
- Share source-aware frozen-source verification across persistence readback, exact opening, projection/preparation and managed retrieval. Keep source hash, canonical scene hash, bundle hash and research manifest digest distinct. Candidate job events remain candidate-only; manual persistence must not fabricate jobs, attempts or accepted-generation receipts.
- E038 needs strict tagged input with mixed/unknown branches rejected; list/detail/UI/CLI decoders need source-aware compatibility. Manual save/open/preparation capabilities must describe actual implemented support. If a consumer is deferred, reject unsupported preparation before reservation instead of producing an unusable intent.
- Opening must bind the configured store, committed reservation and exact manifest to a fresh immutable view with retained includes. Reject malformed descriptors, wrong store/digest, uncommitted records and missing source context; never infer latest/best or reconstruct lineage from filenames.
- Acceptance includes exact retry, changed-payload/family/parent conflict, callback mutation and current-secret rejection, unused/escaped include content, corrupt/partial artifacts, restart, independent research-bundle recovery, legacy candidate/CLI/publication compatibility and backup/restore. This audit is implementation guidance, not executed X05 acceptance.

### Preferences versus recovery versus pending operations

Use bounded, versioned local-installation/workspace-scoped references for sidebar/panel preferences and pins/recents. Reuse ThemeProvider; update recents after successful verified opening. Resolve pinned references again; changed/unavailable data is not silently replaced by latest. Do not persist raw keys, consent, authority, full YAML, query results or job payloads as preferences.

Production draft recovery already uses sessionStorage with source/view matching; retain its unresolved state across navigation and preserve invalid raw download. Memory-only V7 recovery is not its replacement. API restart/replacement view handling requires explicit re-verification. Preference storage failure degrades to memory without corrupting draft or request retention. Each pending generation/save/publication operation retains its own exact tuple and cleanup rules; restoring a draft never retries an operation.

### Snapshot identity and eligibility

The bounded frontend slice now separates receipt/cache IDs from actual requesting jobs, preserves unknown physical origin and adds owned preflight/exact-retry handling; independent review and later browser revalidation are pending. Backend provenance, verified-byte artifact transport and shared render eligibility remain implementation work. Existing HTTP payloads were not changed by this frontend slice.

Keep these fields distinct: raw submitted draft hash; canonical scene hash; normalized options; renderer/dependency revisions; cache/receipt identity; current requesting job; nullable verified physical origin job; artifact IDs/digests.
Job input input_hash is raw-draft identity; catalogue snapshot input_hash denotes canonical identity, while editor_execution currently overwrites the journal result's input_hash with the raw draft hash. Preserve legacy meanings and add unambiguous fields instead of silently redefining this inconsistent legacy field.

Replace the misleading client cache-key-in-jobId shape. Publish an allowlisted verified origin/dependency projection where available; worker asset_manifest is currently dropped by the service. Canonically equal versions may share pixels without proving a render was performed for the newly selected version. Unknown historical origin gets no journal deep link.

The source audit found a second raw-thumbnail cache: a newly published receipt can contain pixels from an earlier capture. Separate journal-authoritative publishing job, actual requesting job and nullable per-artifact physical origin; never fill unknown raw-cache origins with the current job. Renderer implementation hashes are not full Kit/driver identities, and worker asset metadata cannot upgrade the default missing whole-scene dependency revision to verified freshness. Allowlist bounded public capture metadata rather than exposing raw USD paths/dictionaries.

Return actual artifact/variant digests and dimensions, and serve the exact verified bytes rather than checking a pathname before FileResponse reopens it. Shared non-rendering eligibility checks must run before admission as well as in the worker. Fence manual and automatic dispatch before/after activity awaits against monotonic source/options/selection/visibility/session ownership; an accepted old job remains observable without being reattributed to the current draft. Missing robot/scene images need truthful partial-failure labels. Real UI→job→worker→download→decoded/visually inspected GPU acceptance remains a separately authorized gate.

Asset thumbnails show isolated USD/authored defaults, not solved scene poses. Scene overview has separate construction/solving semantics. Schema validity is broader than rendering eligibility; show string-parameter/prim/nesting restrictions before submission. The preview's 2048 planning choice is not currently supported by the 512/1024 production contract. Never silently downgrade it. Automatic rendering remains off initially; later opt-in must retain bounded attempts, retired visibility/source/session consent and ambiguous-acceptance refusal.

## 6. Whole-dashboard activation map

Every destination stays discoverable, but each enabled action must be real. Unsupported actions show an explicit reason rather than fixture success. Do not keep synthetic records intermingled with operational data.

| V7 destination/control | Activation slice and disposition |
|---|---|
| Environment / specification / inspector | F1/F2 real documents, schema, authored projection and bounded supported edits. New remains prompt-first, never requires the synthetic inspection family. |
| Library / versions / pins / compare | F3 real typed/catalogue/managed identities and successful opens. Optional uploads/source-bundle imports require N14; not implicit arbitrary-path access. |
| Assets & scene | F4 actual snapshots/cache/error/identity behavior; F7 optional streaming/picking. Historical fallback visibly distinct from a current request. |
| Activity / Jobs & diagnostics | F1 shared observation and exact deep links; mutation actions retain actual backend admission and X08 exact queue approval. Diagnostic-only jobs are not research evidence. |
| Neo4j query | F1 presentation/state reuse; actual query/probe only on approved target and explicit actions. Results are not publication readback or historical consumed-prior receipts. |
| Settings & readiness / top bar | F1 existing local-operator connection/session controls; F5 supported model/private credential options. Recommend replacing inert Login/Sign up with connection/deadline/revoke for the local release. Real accounts require separate identity/provider/multiuser scope, not session-ID relabelling. |
| Research graph / publication | F3 verified stored identity; F5 existing preparation/write/observe/reconcile/renew/cancel protocol with X07 closure. No auto-publication on pose apply or save. |
| Build & evaluate | F6 actual build/full/policy adapters and approved effective limits; F7 native display profiles. No callback to generic diagnostic submission. |
| Improve | F6 exact-evidence repair/DCRG/controller adapters, proposed vs accepted changes, original authority/receipts and explicit downstream effects. |
| Experiments | F6 typed/legacy validation, complete planned children, variation/rebuild/cumulative budget semantics; not environment validation applied to arbitrary config roots. |
| Runs & evidence | F6 manifest-linked reports/metrics/media with raw denominators and partial outcomes. F1 may show existing generation/diagnostic artifacts only with their actual meaning. |
| Coverage & reference | Record UI, source implementation, isolated acceptance, deployment and target runtime evidence independently. Keep supported-option and unresolved C/G rows; no completion from screen presence. |

## 7. Acceptance and failure walkthroughs

These are required tests/tabletop traces, **not tests executed by this planning task**. Use real supported YAML/source bundles and deterministic isolated service fixtures for integration; no V7 synthetic parser or historical image can satisfy real model/GPU acceptance.

| ID | Required outcome |
|---|---|
| A01 | Load a real approved root with each asset/reference/relation/task role; all identities map to the exact validation result. Missing/defaulted pose remains not authored. |
| A02 | Edit one supported root position: prove unchanged unrelated source bytes, candidate validation, explicit consent/apply and fresh current validation. Original root/include files remain untouched by both apply and save; the distinct persistence action creates an immutable revision rather than overwriting them. |
| A03 | Quaternion XYZW shape/finite/nonzero/normalization policy and unsupported Euler/scale/registry cases fail clearly; relation-controlled ineffective pose correction is refused. No schema-success→placement-success inference. |
| A04 | Included fields inspect read-only; duplicate-root override, nested includes, aliases/merge ambiguity, duplicate keys, unsafe paths and shorthand/defaulted locations never receive guessed edits. |
| A05 | Source/include/session changes, reordered objects, late validation, selection and edit options A→B→A retire stale proposals without overwriting current draft or reviving consent. Pending/failed/invalid exact-candidate validation or failed editability checks disable structured Apply even with consent; raw-editor correction/download remain available. |
| A06 | CodeMirror diagnostic focus handles precise source ownership, CRLF/Unicode/offset units and unknown mappings; candidate findings cannot relabel the current draft valid. |
| A07 | Lost editor-save ACK and crashes before/during/after file commit recover one exact revision; same key/different request conflicts and unknown states do not mint another UUID. |
| A08 | Candidate save after manual edits still saves candidate bytes. Edited research save uses the new immutable editor_revision variant and explicit verified parent, with all readers/CLI/publication projections compatible. |
| A09 | Reload→unresolved recovery→leave→return retains the decision. Changed includes/API restart block unsupported restore; raw invalid text remains downloadable. Preferences/quota failure cannot erase pending operation state. |
| A10 | Actual render accepts the chosen validated source/options, reports its exact requesting job, and decodes verified returned artifacts. Version/camera changes do not retarget completion; partial/missing/historical/origin-unknown remain honest. |
| A11 | Activity/journal/deep link use one reconciled snapshot/SSE cursor across routes/tabs; unavailable is not zero. Pagination cannot starve supervisor selection or authorize a whole queue from one page. |
| A12 | Layout fallback and inactive tabs preserve permitted draft/query state but stop sensitive inputs and automatic preview/input authority. Missing optional V7 chunks cannot destroy the legacy editor or accepted requests. |
| A13 | Prompt-only New omits base/document fields; Refine binds exact source. Lost acceptance, changed credential reference, session replacement and cancelled preserved candidates follow existing receipts without repeat inference. |
| A14 | Publication uses exact verified version/intent/target; read/recovery survives the approved feature-off mode and cross-session restrictions remain explicit. No save/restore/apply/query issues a graph write. |
| A15 | Build/full/evaluation/experiments/repair/DCRG/controller/display each passes its existing C-row identity, budget, evidence and cleanup tests; isolated mocks do not close live acceptance. |
| A16 | Production HTTP entry, same-origin proxy, deep links, static assets/fonts, host/origin/CSRF, session expiry and rollback are exercised from the user's browser path. Delivered URL and enabled features match observed deployment, not source-only claims. |
| A17 | Save/reopen exact editor and research versions with cleared browser state and an API restart. Verify origin/root/include/manifest digests, fresh view identity and supported editability; reject stale/malformed/missing bundles without reading current mutable includes or silently detaching. |

## 8. Deployment, rollback and remaining decisions

Production `main.tsx` constructs the actual API/client providers. Serve its build through the existing same-origin workbench proxy; opening archived `file://.../v7/index.html` must remain offline. Vite's internal port is not the configured API proxy (`web/arena-workbench/README.md:21–23`). Re-discover clone/container/mount/user/origin at deployment time. Do not assume a current service is healthy because an older README records acceptance.

Keep production and preview bundles/tests separate, scope CSS and font assets, preserve existing URLs and capability checks, and make the legacy/V7 selector available before loading optional components. Do not mount both controllers to implement a visual toggle. A compatible rollback must retain accepted-job/publication observation and exact retry state; X07 still blocks a blanket feature-off recovery guarantee. No destructive schema rollback or automatic legacy-writer cutover.

Run all package/API/simulator-touching verification with enforced OS/container egress denial **before imports**, nonroot ownership, explicit synthetic state and no live credential/data mounts. Preview tests do not authorize the historical backend suite; the Neo4j incident remains unresolved. Separate isolated contract tests, real proxy/browser acceptance, controlled deployment, provider/DB acceptance and GPU/streaming acceptance. Changes under docker/, workflows, pre-commit configuration or submodules require separate approval.

Before enabling affected operations, resolve:

- first implementation slice and approved source/test-state roots; recommended F0/F1, not another offline design rewrite;
- supported registry/role/constraint pose cases, YAML parser/source-range proof and quaternion policy;
- X03 durable save protocol and X05 manual research-source compatibility;
- actual provider/graph/GPU targets and numerical budgets for each live acceptance;
- local-operator session controls versus separately scoped real accounts, shared preferences and cross-session publication adoption;
- optional later include editing, unprepared-version preparation, live viewport/physics mirroring and advanced-profile exclusions.

## 9. Review status

Source audits `deleg_f204b273` independently examined production controller/visibility/rollout seams and actual YAML/pose/include/save/render semantics. Parent additionally read production App/Runtime/Editor/MetadataBrowser/contracts/deployment documentation and verified conversion/include/Pose source. No application imports or runtime probes were used. The route inventory still reconstructs to 46 source-registered routes; no new proposal endpoint is required for the recommended narrow authored edit. Final independent consistency review `deleg_b6a8527f` passed with no blockers. Its editorial approval-scope clarification and explicit candidate-validity Apply gate are incorporated. Static slice/case/reference/link/source-hash/archive checks and scoped pre-commit passed. This verifies plan consistency, not operational implementation or live acceptance.
