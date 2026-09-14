# UI-first coverage and walkthrough gate

Status: revised delivery specification; preview not yet implemented. This appendix implements the user's request to see the whole dashboard before adding backend complexity. It is subordinate to the [canonical parity plan](../dashboard_cli_workflow_parity.md), not a replacement architecture. Current implementation and incident evidence remain in [implementation progress](implementation-progress.md).

## 1. Immediate decision

Pause feature expansion in APIs, persistence, scheduling, authorization and recovery. Preserve existing work. Do not finish every backend phase before showing the complete interface. First build a navigable, frontend-only preview of the entire C01–C21 workflow, walk it with the user, and record omissions and simplifications. UI approval does not authorize live execution or close a runtime parity requirement.

The preview is a research workbench whose primary destination and entry point is **Environment**, centered on one environment and its exact revision. Its design prioritizes operating on that environment; inspection and run monitoring are secondary. Reuse the existing typography, theme, editor/graph visual language and accessible controls. No marketing page, decorative metric tiles, new design-system dependency or gratuitous service layer.

## 2. Information architecture

The names below are proposed UI destinations, not existing routes or API contracts. Prefer tabs and contextual panels over one navigation item per capability.

| Destination | What the user can inspect/configure in the preview |
|---|---|
| Environment | Prompt-first New and explicit Refine; source/revision header; specification, authored graph, preview and evidence tabs; review candidate, apply, save, prepare publication as distinct actions. |
| Library | Typed environment/policy/experiment artifacts; family/version/lineage browser; source/include identity; asset/relation/task catalogues; schema reference; import/export forms. |
| Build & evaluate | Separate Snapshot, Build/zero-action, Generate-and-build, Policy evaluation and Native Kit purposes; exact revision, approved profiles, budgets and recordings. |
| Improve | Separate evidence-bound repair, DCRG refinement/resume, and same-scene controller-assistance tabs; proposed-versus-accepted changes and retained failed evidence. |
| Experiments | Typed/legacy import, variations, effective child configurations, ordered runs/rebuilds, cumulative budget and stop/continue policy. |
| Runs & evidence | User-facing queue and history, selected run details, stages, cancellation/recovery eligibility, reports, metrics, videos and exact attribution; diagnostics remains secondary. |
| Research graph | Clearly separated persisted graph inspection and publication outcome/detail; no conflation with the authored draft graph or automatic graph query/publication. |
| Settings & readiness | Provider/model, graph, policy and storage profile concepts; owner/readiness/budget information; session boundaries and advanced approved profiles. No functioning credential entry in the preview. |

The environment/revision/run breadcrumb must persist across destinations. Moving to a run does not replace the editable draft; selecting a different version does not silently retarget an open execution form. A new user can find the primary prompt field without loading YAML or opening diagnostics.

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
| C10 | Environment / preview | Scene versus asset snapshot, source freshness, explicit request/budget and stale/missing image; not a simulation-success label. |
| C11 | Build & evaluate / Build | Exact revision, reset/step limit, solver options, start/stop artifacts and diagnostics; zero-action versus posture-hold distinguished. |
| C12 | Build & evaluate / Generate-and-build | Review both stages and budgets, exact candidate-to-build handoff, completed generation retained after build failure. |
| C13 | Build & evaluate / Policy evaluation | Approved GR00T/OpenPI profile, checkpoint/server identity, fixed scene, effective limit/seeds, cameras/recording and unsupported combinations. |
| C14 | Improve / Repair | Exact failed run and scene/policy config, repair mode, diagnostics, proposed diff, explicit accept and separately authorized reevaluation. |
| C15 | Improve / DCRG | Supported scenario/hand/policy constraints, objective, cumulative budget, lineage, current iteration and exact resume point; not ordinary healing. |
| C16 | Runs & evidence / report | Run/scene/policy identities, completed episode denominator, unknown metrics, partial/failed artifacts, media/report views and comparisons. |
| C17 | Runs & evidence; Settings | Readiness and owner, queued/active/terminal states, cancellation versus cleanup pending, selected recovery scope, session expiry and unknown outcomes. |
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
| U2: coverage review | User walkthrough, independent UX/safety critique, resolved gaps and proposed simplifications | Explicit user approval of workflow coverage and prioritization before adding backend capability. Outstanding exclusions are named and approved, never counted as working. |
| U3: one vertical workflow at a time | Connect an approved UI action to the smallest existing service boundary, preserving shared CLI semantics | Exact UI→request→result verification under isolation, then separately authorized live acceptance when required. Update UI coverage, backend implementation, deployment and runtime evidence independently. |

Do not discard completed backend work. Reuse it after U2; add an endpoint only when a reviewed UI action lacks a safe existing contract. Every proposal for backend expansion identifies that action, why existing contracts cannot serve it, its side effects and bounded acceptance case. No endpoint-per-widget rule and no speculative recovery framework.

P0–P7 remain dependency/acceptance categories for the eventual working system, not the immediate work queue. U1/U2 do not wait for P2 live publication, P3–P7 implementations or credentials. Full parity still requires genuine receipts for executable capabilities. Publishing the preview is not a production rollout.

## 7. Status reporting

Maintain separate dimensions rather than one completion badge:

- **UI coverage:** missing / represented / interaction-reviewed / user-approved.
- **Backend:** absent / partial / implemented / isolated-tested.
- **Deployment:** not deployed / deployed with capability off / enabled.
- **Runtime evidence:** not run / blocked / verified for a stated target and scope.

Show blockers and their reason next to the relevant workflow. The top-level handoff reports the preview URL, screens and interactions actually reviewed, unresolved coverage entries, the next approved integration, and the fact that real execution is unavailable in preview. Do not replace the user's review with accumulated test counts.
