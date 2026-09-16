# UI-first coverage and walkthrough gate

Status: V7 offline preview delivered and design direction accepted; the user subsequently authorized the functionalization plan's implementation and remaining features. Full operational coverage and live acceptance remain separate gates. This appendix implements the user's request to see the whole dashboard before adding backend complexity. It is subordinate to the [canonical parity plan](../dashboard_cli_workflow_parity.md), not a replacement architecture. Current implementation, verification limits and incident evidence remain in [implementation progress](implementation-progress.md).

## 1. Current decision and preserved preview boundary

The offline design phase has produced V7, which the user says looks good. Implementation of the [functionalization plan](v7-functionalization.md) is now authorized and underway; another offline redesign is not required. Preserve existing code and archives, and retain each U3 slice's explicit acceptance scope. The preview constraints below continue to govern offline artifacts. Design approval does not authorize live execution, public accounts or close a runtime parity requirement.

The preview is a research workbench whose primary destination and entry point is **Environment**, centered on one environment and its exact revision. Its design prioritizes operating on that environment; inspection and run monitoring are secondary. Reuse the existing typography, theme, editor/graph visual language and accessible controls. No marketing page, decorative metric tiles, new design-system dependency or gratuitous service layer.

## 2. Information architecture

The names below are proposed UI destinations, not existing routes or API contracts. Prefer tabs and contextual panels over one navigation item per capability.

| Destination | What the user can inspect/configure in the preview |
|---|---|
| Environment | Prompt-first New and explicit Refine; source/revision header; specification, authored graph, preview and evidence tabs; review candidate, apply, save, prepare publication as distinct actions. |
| Library | Typed environment/policy/experiment artifacts; family/version/lineage browser; source/include identity; asset/relation/task catalogues; schema reference; import/export forms. |
| Assets & scene | Historical asset/scene pixels, exact saved camera/capture, zoom/retry/provenance and local render planning; live RTX requirements exploration remains disconnected. |
| Build & evaluate | Separate Snapshot, Build/zero-action, Generate-and-build, Policy evaluation and Native Kit purposes; exact revision, approved profiles, budgets and recordings. |
| Improve | Separate evidence-bound repair, DCRG refinement/resume, and same-scene controller-assistance tabs; proposed-versus-accepted changes and retained failed evidence. |
| Experiments | Typed/legacy import, variations, effective child configurations, ordered runs/rebuilds, cumulative budget and stop/continue policy. |
| Runs & evidence | Research reports, metrics, videos, comparison and exact run attribution; no operational cancellation, authorization or integration-diagnostic controls. |
| Neo4j query | Explicit read-only query composer, examples and JSON parameters; separate frozen review and labelled Table/Graph result fixtures with stale/empty/error/truncated states. No publication actions. |
| Jobs & diagnostics | Operational journal and exact-job inspector; cancellation/authorization reviews; separate Developer diagnostics for bounded input, retained retry and explicit queue-resume review. No research metrics. |
| Research graph | Clearly separated persisted graph inspection and publication outcome/detail; no conflation with the authored draft graph or automatic graph query/publication. |
| Settings & readiness | Provider/model, graph, policy and storage profile concepts; owner/readiness/budget information; session boundaries and advanced approved profiles. No functioning credential entry in the preview. |

Editor draft/selection state must persist across destinations while each workspace displays its own relevant identity. Query, operational-job and report inspection do not inherit the editor's selected revision or expose its save controls. Moving to a run does not replace the editable draft; selecting a different version does not silently retarget an open execution form. A new user can find the primary prompt field without loading YAML or opening diagnostics.

### Next UX iteration: V7 inspect-and-correct workspace

The user requested that all seven recommendations below become part of the implementation plan. **V7 is now delivered as an offline inspect-and-correct preview**; exact verification and limitations are recorded in implementation progress. These recommendation rows also retain later production/streaming requirements, which the preview does not implement or authorize. Preserve the versioned previews, Cybernetic-Physics theme, sidebar-owned collapse control and original sun/moon switch. The goal is a coherent operating experience, not more navigation destinations or backend endpoints.

| Recommendation | Planned interaction and ownership | Acceptance before integration |
|---|---|---|
| R01 — central environment workspace | Keep specification, viewport, validation and selected-object inspector together; collapsible/resizable authoring and inspector panels. Assets & scene remains an expanded view with an explicit return to the same draft/source/selection. | Navigate/expand/collapse without losing prompt, edits, source or selected object; opening another version still requires the existing unsaved-input decision. Layout state alone submits nothing. |
| R02 — unmistakable source and status | Show distinct identity/status for current draft, saved version, historical pixels, live viewport and running simulation. Keep configured, authenticated, connected, rendered, validated and physically successful separate. | Every visible image/result/action names its actual source/revision/camera/job where known. Missing identity stays unknown. A historical image never becomes current by changing a badge, and incoming job/stream updates never retarget the draft. |
| R03 — useful scene inspector | Begin read-only: registry identity, node/prim identity, parent, pose, scale and supported properties. Distinguish authored values from solver-realized or simulated state. Select via asset list; viewport picking is available only with a verified prim/frame mapping. Later edits produce proposed changes, not immediate writes. | Selection is consistent across list/inspector/viewport only when identity is established. Static PNG clicks cannot invent prim identity. Source/frame changes retire stale selection. Applying a proposal checks its base revision and requires explicit review/validation. |
| R04 — actionable validation and recovery | Restore schema findings, schema/registry browsing, explicit flattened export and draft restore/download/discard. A finding selects the relevant field/YAML location when the validator provides a mapping; otherwise show the unmapped location honestly. | Late validation cannot overwrite current findings. Invalid proposals do not save/render. Reload/navigation preserve an unresolved recovery decision; restore and discard are explicit and cannot replace newer edits silently. |
| R05 — actions linked to jobs/evidence | Link each real accepted render/build/evaluation to its exact job, frozen inputs and artifact manifest. Add a compact activity indicator using existing observation state, with direct navigation to details; keep developer diagnostics secondary and visible failures/cleanup-pending states prominent. | Indicator and journal reconcile to the same IDs/cursor. Refreshing, filtering, route changes and reconnects do not submit work. Cancellation is not reported complete before cleanup evidence. No fake progress percentages or inferred artifact success. |
| R06 — useful Library history | Explicit pins/recents and comparison of two chosen immutable versions; typed environment/policy/experiment/unclassified entries; source/parent/evidence details where established. Use local nonsecret preferences first; do not add synchronized preference storage without a demonstrated requirement. | No automatic latest/best selection, guessed lineage or history deletion. Changed/unavailable source stays explicit. Primary/comparison collision clears invalid selection without rewriting a frozen comparison. Comparisons remain read-only and do not generate or publish. |
| R07 — governed live viewport | Design view-only, camera control, picking/inspection and edit-proposal modes separately. Show controller ownership, source/frame identity, connection/disconnect behavior and resource limits. Evaluate ovstage/ovrtx/ovstream in a separately approved bounded spike; keep Isaac Sim/Arena responsible for simulation. | Viewport cleanup and grant revocation are verified; stale input is rejected; no pointer action starts physics/generation/publication. TanStack manages route/server metadata, while the streaming component owns media/input lifecycle—not video frames in query cache. Runtime, hardware, media/client and licensing compatibility remain acceptance gates. |

#### V7 walkthrough and failure cases

Primary flow: **choose an exact version → inspect its scene/assets → select an object → inspect properties → inspect validation → review a proposed change**. Start with local/offline interactions and visibly attributable historical images; no live frame, pick hit or validated edit may be fabricated to complete the story.

- Keep an edited draft while expanding the viewport, opening job details and returning to the inspector.
- Select a historical capture or unavailable camera and verify its identity cannot be confused with a current/live scene.
- Change source while a validation/proposal/pick result is pending; retain historical evidence but reject stale application.
- Click an error with and without a source location; verify navigation or an explicit unmapped explanation.
- Compare A/B, then choose B as the primary; require a different comparison and preserve an already frozen A/B review.
- Lose observation or stream connection; preserve exact accepted handles, show stale/disconnected state and do not auto-submit/reconnect with mutation authority.
- Review a proposal without applying/saving/publishing it. Application, persistence, rendering and evaluation remain separate decisions.

The [endpoint contract plan](endpoint-contract-plan.md) maps these recommendations and C01–C21 to existing routes, necessary extensions, proposed future families and entry/exit gates. An offline V7 interaction does not authorize those contracts' implementation or live execution.

### Existing-dashboard retention gate

U2 review found missing original-dashboard controls despite the broader planned destination map. Track these separately from the historical CLI ledger in [Original-dashboard retention review](original-dashboard-retention.md). Neo4j query is not equivalent to an example graph label filter; Jobs & diagnostics is not equivalent to a research-evidence selector. Restore or explicitly disposition these original workflows with the user before treating the redesigned dashboard as a complete replacement. V5 restored local query and operational job/diagnostic workspaces; V6 added historical Assets & scene viewing. Remaining original editor/metadata/provider/evidence gaps feed R01–R07 and the endpoint contract plan. None of these previews authorizes queries, queue resume or backend expansion.

### Document selection refinement

Use a compact environment-family selector followed by an exact version selector, with a searchable Library for inspection. Collapse version history at the family level, keep policies/experiments/unclassified artifacts separate, show exact source and lineage where established, and require explicit Open plus unsaved-input confirmation. Recent/pinned examples and explicitly chosen baselines are not inferred latest/best versions. Group legacy records by established metadata or clearly labelled source folders, never by robot/name similarity alone. No records are deleted or migrated to reduce visual clutter. The preview demonstrates this with synthetic C1 history; production catalogue integration remains a later reviewed slice.

## 3. Capability-to-screen coverage

Every row needs a concrete form/detail surface and a clickable review path, not just a navigation label or disabled button. Fields can use progressive disclosure; advanced options must remain discoverable through a searchable coverage index. This is planned coverage, not a claim that these screens exist.

| Capability | Destination / surface | Minimum visible controls and evidence |
|---|---|---|
| C01 | Library / schema | Schema revision, search, field details, download explanation; read-only operation. |
| C02 | Library / catalogues | Asset/relation/task search, parameters, restrictions and catalogue revision; selecting a constraint versus selecting a base is explicit. |
| C03 | Environment / New | Scenario/family, prompt, optional registry constraints, retrieval choice, model/budget summary; no required template or implicit base. |
| C04 | Environment / Refine | Exact base version/include identity, feedback, proposed diff and explicit apply; source changes require a decision. |
| C05 | Settings and execution summary | Provider/model/temperature and named endpoint profile, key lifecycle explanation, configuration versus authentication versus inference status. |
| C06 | Environment / consumed evidence | Exact prior identity and receipt; measured, structural, empty and unavailable states; fallback permission and unknown provenance. |
| C07 | Library / versions and lineage | Family/internal name/version/revision, parent, origin, save confirmation and persistence-unknown recovery. |
| C08 | Version / publication detail | Prepare versus publish, frozen target, explicit consent, pending/verified/unknown/blocked states, observe versus reconcile versus renew; unsupported cross-session recovery visible. |
| C09 | Library / typed artifacts | Type/root/version disambiguation, approved import, frozen includes, raw/canonical identity and export; no arbitrary host path control. |
| C10 | Assets & scene; Environment / Preview link | Scene versus asset snapshot, source freshness, explicit request/budget and stale/missing image; not a simulation-success label. |
| C11 | Build & evaluate / Build | Exact revision, reset/step limit, solver options, start/stop artifacts and diagnostics; zero-action versus posture-hold distinguished. |
| C12 | Build & evaluate / Generate-and-build | Review both stages and budgets, exact candidate-to-build handoff, completed generation retained after build failure. |
| C13 | Build & evaluate / Policy evaluation | Approved GR00T/OpenPI profile, checkpoint/server identity, fixed scene, effective limit/seeds, cameras/recording and unsupported combinations. |
| C14 | Improve / Repair | Exact failed run and scene/policy config, repair mode, diagnostics, proposed diff, explicit accept and separately authorized reevaluation. |
| C15 | Improve / DCRG | Supported scenario/hand/policy constraints, objective, cumulative budget, lineage, current iteration and exact resume point; not ordinary healing. |
| C16 | Runs & evidence / report | Run/scene/policy identities, completed episode denominator, unknown metrics, partial/failed artifacts, media/report views and comparisons. |
| C17 | Jobs & diagnostics; Settings | Readiness and owner, queued/active/terminal states, cancellation versus cleanup pending, selected recovery scope, session expiry and unknown outcomes. |
| C18 | Build & evaluate / Native Kit | Supported managed native session/display profile and launch/close ownership; screenshot, browser 3D, recording and interactive Kit explicitly different. |
| C19 | Experiments | Import/type, variations/effective config, seeds, ordered children/rebuilds, cumulative budget, continue-on-error and unattempted children. |
| C20 | Build & evaluate / advanced profiles | Device/rendering/solver/recording/animation/distribution/display settings with effective values, profile restrictions, no-ops/rejected options and operator prerequisites. |
| C21 | Improve / Controller assistance | Observe/offset/gate/combined modes, privileged-state consent, supported left-hand G1 contract, scene/controller/checkpoint identity, traces, trial registration/attachment and zero-success retrieval. |

### Full option ledger, not just 21 headings

Use the existing `workflow-parity-ledger.json` as the finite source inventory. Its 394 entry IDs and G01–G05 audit gaps are historical design evidence, not current implementation status. Do not rewrite historical source hashes to make a new UI look verified.

At preview completion, supply a companion coverage index keyed by every existing entry ID. Each entry must record: capability IDs, screen/control or profile-detail location, visible label, disposition (typed control / approved-profile field / read-only evidence / operator prerequisite / rejected or ineffective option / unresolved audit), planned interaction check, and separately the actual backend/runtime status. An unsupported option must have a discoverable explanation. Do not auto-mark an entry covered merely because its C-row has a screen. Unknown/dynamic fields stay unresolved rather than becoming invented effective controls. Any source options introduced after the inventory must be listed as additions requiring reconciliation; do not present the historical inventory as a current parser census.

## 4. Preview behavior and isolation

- Use the existing React/TypeScript frontend stack and reusable presentation components. Add a dedicated preview entry point/build, not another application framework, generic workflow engine, or new backend service. Existing production routes and working components remain intact.
- The preview must not mount the live runtime/session provider, construct ApiClient, register production observation workers, fetch health/catalogues, invoke production action handlers, or load operator profiles/credentials. A flag that merely disables buttons is insufficient isolation. Audit transitive imports for mount-time effects.
- Run on a separate local preview origin with disposable browser storage, no live cookies, no live API proxy and no credentials. Retain production profile/storage bindings untouched. Do not reload/restart the existing dashboard or backend to serve the preview.
- Browser policy/network interception permits only the preview's own static assets; API requests and outbound connections are denied and treated as test failures. Node/build/test execution also needs OS/container-level egress denial with a verified denial probe before repository/test imports. No broad Arena regression suite or simulator import is needed for this UI milestone.
- Prefer an existing isolated frontend environment and standard browser/network controls. If verified isolation is unavailable, stop and request approval for the smallest necessary setup change; do not weaken isolation or introduce new container infrastructure or a custom interception framework as an implicit part of this preview task.
- A persistent banner states **Design preview — example data; no jobs or database operations**. Example records use distinct `example-*` identities; example statuses/artifacts are labelled in panels and any exports. Do not use real research names as fabricated successful results or create synthetic success statistics.
- Primary execution controls say **Preview request**, **Review confirmation**, or **Show example outcome**, never pretend to submit a real job. The intended production action name appears in the confirmation for design review. Transitions are driven by explicit state selection, not fake autonomous progress or timers.
- A small state selector exposes empty/loading/candidate/persisted/publication-unknown/blocked/failed/cancelled examples where relevant. Keep candidate validity, artifact persistence, publication, build and evaluation outcomes separate. Unknown metrics are unavailable, not zero; examples never constitute verified receipts.
- Forms must support real local editing, validation messages, navigation, source selection, diffs, confirmation review, cancel/back, and inspecting planned artifacts. A grid of placeholders is not a complete preview. Use local fixture state only; no secret fields accept or retain input.
- In preview, show planned sections even when the production adapter is absent, with an explicit explanation. In production, actual server capabilities and authorization still gate all operations; do not force-enable production flags to make the UI complete.

The incident remains a separate blocker for legacy execution verification and live rollout. Preview isolation does not establish that the prior research data was unaffected, resolve recovery policy, or authorize cleanup of that database.

## 5. Walkthroughs before more backend work

Each walkthrough starts at navigation, edits the relevant form, reviews exact inputs/side effects, inspects an example result, and follows its next action. Record screenshots and omissions, not fictional execution receipts.

1. **A2 from scratch:** prompt for DROID banana to large plate, no base document; inspect constraints, prior/fallback examples and execution summary; review candidate, save, publication and optional downstream actions separately. No claim of A2 physical success.
2. **Existing research:** browse typed library, inspect exact source/includes/version, refine, compare/apply and retain parent lineage; switching selection never retargets a pending form.
3. **Inspect / build / evaluate:** show why snapshot, zero-action build, generated-then-built scene, policy rollout and Native Kit differ; review effective limits, profiles, recordings and exact revision handoff.
4. **Failed/uncertain operation:** lost acknowledgement, storage unavailable, model expiry, publication unknown, cleanup pending and replacement session. Verify the proposed UI does not offer unsafe retry or imply cross-session recovery is implemented.
5. **Repair and controlled refinement:** select failed evidence, propose a repair without accepting it, then separately inspect DCRG and controller-assistance constraints and budget/resume states.
6. **Experiments and evidence:** import variations, inspect children and aggregate budget, show cancellation/partial/zero-episode output, compare runs and inspect labelled media examples.
7. **Operator readiness:** distinguish missing service configuration, unverified identity and unavailable adapter; find prerequisites without a browser shell or credential leakage. Diagnostics is not the normal research entry point.

User review answers: Can I find every planned workflow? Are inputs and effects clear? What is missing? What can be removed or merged? Which one real workflow should be connected next? Capture decisions against capability/ledger IDs.

## 6. Delivery order and exit evidence

| Milestone | Deliverable | Exit gate |
|---|---|---|
| U0: structure | This screen map, capability coverage and explicit preview/isolation contract | Independent plan review; no silent loss of C01–C21 or G01–G05. |
| U1: complete preview | Navigable frontend preview, substantive forms/details, local state examples, full per-entry coverage index and screenshots | Verified browser navigation/forms/keyboard use at desktop and narrow viewport; zero API/model/graph/job calls; source remains separate from production runtime. Preview evidence is not runtime evidence. |
| U2: coverage review | V7 design direction accepted; retain the walkthrough/critique record and explicit workflow gaps | Remaining approval is selected-slice scope/prioritization and operational exclusions, not another mandatory preview cycle. Exclusions are never counted as working. |
| U3: one vertical workflow at a time | Connect an approved UI action to the smallest existing service boundary, preserving shared CLI semantics | Exact UI→request→result verification under isolation, then separately authorized live acceptance when required. Update UI coverage, backend implementation, deployment and runtime evidence independently. |

Do not discard completed backend work. With V7's design direction accepted, reuse it in approved U3 slices; add an endpoint only when a reviewed UI action lacks a safe existing contract. Every proposal for backend expansion identifies that action, why existing contracts cannot serve it, its side effects and bounded acceptance case. No endpoint-per-widget rule and no speculative recovery framework.

P0–P7 remain dependency/acceptance categories for the eventual working system, not the immediate work queue. U1/U2 do not wait for P2 live publication, P3–P7 implementations or credentials. Full parity still requires genuine receipts for executable capabilities. Publishing the preview is not a production rollout.

## 7. Status reporting

Maintain separate dimensions rather than one completion badge:

- **UI coverage:** missing / represented / interaction-reviewed / user-approved.
- **Backend:** absent / partial / implemented / isolated-tested.
- **Deployment:** not deployed / deployed with capability off / enabled.
- **Runtime evidence:** not run / blocked / verified for a stated target and scope.

Show blockers and their reason next to the relevant workflow. The top-level handoff reports the preview URL, screens and interactions actually reviewed, unresolved coverage entries, the next approved integration, and the fact that real execution is unavailable in preview. Do not replace the user's review with accumulated test counts.
