# TanStack Workbench graph explorer plan

## Status and decision boundary

- **Status:** implementation approved by the user; staged implementation is in progress. Final visual acceptance and removal of the legacy fallback remain separate gates.
- **Research date:** 2026-09-13.
- **Requested outcome:** replace the limiting authored spatial-graph diagram with a shared, inspectable **Table / 2D / 3D** explorer, with dragging and other navigation controls.
- **Repository baseline:** `dev/0.3.0-prerelease`, commit `af6774ec6`, clean at implementation start; the existing provider-key lifetime behavior is unrelated and must remain intact.
- **Scope of this planning task:** repository inspection, public documentation research, design, acceptance criteria, and independent review. No dependency installation, application-source migration, server restart, database write, paid inference, or Isaac Sim run is required to approve this plan.
- All proposed filenames, interfaces, budgets, and milestones below are **design proposals**, not claims that those implementations exist. Research establishes documented capabilities, not compatibility or performance in this checkout.

## 1. Executive recommendation

Build one reusable graph-explorer feature beneath `web/arena-workbench/src/`, with:

1. **2D as the default:** a force-directed relationship diagram with node dragging, selection, relationship inspection, neighborhood highlighting, pinning, zoom, pan, and fit.
2. **Table as a first-class alternative:** searchable, sortable Nodes and Relationships tables, sharing selection and an accessible property inspector with the visual views.
3. **3D as an optional, lazy-loaded view:** orbit, pan, zoom, node dragging, and click-to-focus; it must not become a prerequisite for inspecting the data.
4. **One shared controller:** filters, selection, data identity, and inspection are independent of whichever renderer is mounted.
5. **Explicit provenance:** authored YAML projections remain separate from persisted Neo4j query results. Layout coordinates have no authority over the physical scene.
6. **A staged replacement:** prove the dependency and interaction contract before integrating it into the live editor; retain a rollback path until both consumers pass acceptance.

The preferred candidate is the separate `react-force-graph-2d` and `react-force-graph-3d` packages, subject to the Phase 0 compatibility and usability gate. Their documented interfaces cover the requested 2D/3D interactions; the upstream project is MIT-licensed.[14][34] Do not import the combined VR/AR umbrella merely for convenience: its manifest includes VR and AR dependencies that are outside this feature.[35]

“Like Neo4j” means an exploration experience, not embedding Neo4j Browser or claiming exact product parity. Neo4j Browser documents tabular query results and node/relationship visualization; the requested 3D mode is our additional product requirement.[8]

## 2. What exists today: repository evidence

| Location | Observed behavior | Consequence for the migration |
| --- | --- | --- |
| `web/arena-workbench/src/graph-view.tsx:4` | One shared `GraphView({ graph, label })` component. | Avoid separate authored and persisted implementations. |
| `web/arena-workbench/src/graph-view.tsx:10` | Layout is a memoized fixed grid with at most four columns. | This is not force-directed placement; dense relationships remain hard to follow. |
| `web/arena-workbench/src/graph-view.tsx:27` | Zoom buttons and a transform reset labelled Fit graph. | Define real fit-to-visible-bounds behavior instead of merely resetting transforms. |
| `web/arena-workbench/src/graph-view.tsx:55` | Pointer dragging pans the background; node targets are excluded. | Individual nodes are not draggable. |
| `web/arena-workbench/src/graph-view.tsx:118` | Nodes have keyboard-activatable SVG controls; properties and connected edges appear below. | A Canvas migration must replace, not silently remove, keyboard access. |
| `web/arena-workbench/src/editor.tsx:498` | Authored graph is displayed only for valid current YAML. | Preserve the explicit invalid-draft withholding rule. |
| `web/arena-workbench/src/editor.tsx:511` | Unary constraints, all relations, explicit reifiers, and tasks have additional tabular views. | Do not discard these semantics because graph rendering improves. |
| `web/arena-workbench/src/neo4j.tsx:169` | Query output switches between raw table rows and the same graph renderer. | Preserve raw query rows; they are not interchangeable with graph entity tables. |
| `web/arena-workbench/src/editor-contracts.ts:1` | Nodes have string IDs, labels, roles, properties; edges have IDs, source, target, labels, properties. | The baseline contract already supports the explorer. |
| `isaaclab_arena/agentic_environment_generation/workbench/documents.py:35` | Projection includes assets, parent links, relations, and explicitly authored reifiers. | Render what the server returns; do not infer new relationships. |
| `isaaclab_arena_examples/agentic_environment_generation/web_api/graph_projection.py:15` | Neo4j entities are projected with caps and redaction. | Keep these boundaries and display truncation rather than requesting the entire database. |
| `web/arena-workbench/src/graph-view.test.tsx:5` | One grid-layout regression inspects SVG transforms. | Rewrite implementation-specific assertions and add real interaction coverage. |
| `web/arena-workbench/tests/e2e/editor.spec.ts:58` | Browser tests expect accessible per-node Inspect controls. | Keep equivalent accessible controls and separately test real canvas/WebGL pointer interactions. |
| `web/arena-workbench/src/runtime.tsx:25` | App-level session and observation ownership is independent of routes. | Do not add another event stream or remount the runtime for graph mode changes. |
| `web/arena-workbench/src/editor.css:461`, `src/theme.css:77` | Graph styling is coupled to SVG and light/dark overrides. | Move feature styles deliberately; Canvas/Three colors need theme values, not only CSS selectors. |

### 2.1 Read-only live baseline

The current default document, `isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml`, was read through the running editor API during planning. It validated and returned **6 nodes and 7 edges**. Its roles were `embodiment`, `background`, `object`, and `object_reference`; edge labels included `contains`, `is_anchor`, `on`, `position_limits`, and `at_position`.

This is a small functional fixture, **not** a dense-graph benchmark and **not** a fixture containing explicit reifiers. No new render or inference was requested by that read. Before implementation, capture the visible baseline at the same viewports used for acceptance, including a reifier fixture and a larger persisted query result.

### 2.2 Semantics that can be lost accidentally

- A unary relation currently projects as a self-loop because its target falls back to its subject (`documents.py:62`). Preserve that as a constraint representation, not a claim that two physical objects are connected.
- Explicit reifiers become real nodes with role `reifier` and `reifies_subject` / `reifies_object` edges (`documents.py:70`). Keep them distinguishable; do not manufacture intermediate statement nodes for ordinary edges.
- Authored relation IDs use `relation:{index}`. Reordering the relation list can reuse an ID for a different relation. **ID equality alone cannot preserve edge selection across changed YAML.**
- Neo4j node IDs are returned `element_id` values. Preserve them literally; never use display labels or parse IDs as CSS selectors.
- Neo4j projection includes a `labels` array in addition to `role`; the TypeScript `GraphNode` interface currently declares only `role`, which the backend chooses as the alphabetically first label. Preserve a validated optional `labels` array in the frontend normalization contract and test multi-label entities. Use an explicit documented role/label classification for reifiers rather than the existing substring heuristic; never infer reification from display text. This is an additive frontend contract correction, not a new backend field.
- The persisted projection limits graph output to **256 nodes / 512 edges**, bounds nested values, and marks truncation. Query execution separately limits rows to **200** (`graph_queries.py:186`). Those are different limits and different representations.
- `graph_projection.py:24` can replace exhausted/deep values, including an entity's `properties`, with the string `[truncated]`. The current TypeScript object-only properties declaration does not capture every actual response. Normalize properties as a bounded JSON value and preserve sentinel strings; inspector/table code must not assume `Object.entries(properties)` is always meaningful. Any shared TypeScript correction needs regression coverage for existing consumers.
- The authored schema's top-level validator checks asset uniqueness and ordinary references (`isaaclab_arena/environment_spec/arena_env_graph_spec.py:86`), but does not perform equivalent reifier ID/endpoint checks there. Frontend duplicate/dangling diagnostics are required even after schema-valid YAML. A broader backend validation correction is separate scope.
- A query returning scalar values can validly have rows and no graph entities. An empty graph must not hide or mislabel those rows.

## 3. Product scope and non-goals

### Included in the first complete release

- Table, 2D, and optional 3D views using the same returned graph.
- Node and edge selection; one property inspector.
- Search, role/type filters, visible-versus-returned counts, and one-hop neighborhood focus.
- Drag/pan/zoom, pin/unpin, fit, reset, and bounded automatic layout.
- Fullscreen/expanded viewing with keyboard-safe close behavior.
- Light/dark themes, reduced-motion behavior, and table fallback when visual rendering is unavailable.
- Shared use in authored and persisted graph contexts, preserving the existing Neo4j raw result table.
- Read-only presentation state with clear reset behavior.
- Component, model, real-browser, security, and performance acceptance evidence.

### Explicitly excluded

- Moving robots/objects in Isaac Sim or updating YAML poses by dragging graph nodes.
- Creating, deleting, reconnecting, or editing semantic nodes/edges through the canvas.
- Database writes, unconstrained Cypher, automatic database expansion, or increased backend query caps.
- New generation modes, Graph-RAG retrieval/publication, policy evaluation, and preview-renderer changes.
- VR/AR, collaboration, cross-user layout sharing, server-persisted layouts, and a new state-management framework.
- Graph analytics presented as research evidence, automatic success scoring, and undocumented inferred edges.
- Export/download features in the first release. JSON/CSV/image export is a later, separately reviewed addition with provenance, escaping, and redaction requirements.

A 3D relationship layout is **not** a 3D scene preview. The UI must say this near the mode controls, not bury it in documentation.

## 4. Renderer and table-library assessment

| Candidate | Evidence from documentation | Fit and decision |
| --- | --- | --- |
| Separate `react-force-graph-2d` + `react-force-graph-3d` | Canvas 2D, ThreeJS/WebGL 3D, node dragging, node/link callbacks, force controls, fit and camera APIs.[14] Project MIT license.[34] | **Preferred conditional choice.** Shared conceptual API reduces adapter divergence. Still requires custom accessibility, safe labels, edge geometry, and lifecycle verification. |
| Cytoscape.js for 2D plus a separate 3D engine | Documents automatic/manual layouts, stylesheets, selectors, graph algorithms, touch gestures, and an MIT core/first-party extension license.[1] | **2D fallback candidate** if force-graph fails edge legibility or interaction tests. Strong graph tooling, but two different engine models increase integration and testing cost. Do not assume a first-party 3D equivalent. |
| Sigma.js plus Graphology | Official site describes a network renderer paired with Graphology; it explicitly distinguishes the v3 site from an alpha-v4 documentation site.[4] | Consider for a later larger-graph requirement, not as an unmeasured performance win. Do not copy v4 drag APIs into a v3 installation. Does not establish the requested shared 2D/3D solution. |
| React Flow | Docs describe custom nodes/handles, selectable edges, and dragging connections to create edges.[18] | Better aligned with a future semantic node editor. This release is read-only relationship exploration, so introducing editing affordances and an additional 3D renderer is not preferred. |
| Neo4j Visualization Library (NVL) | Has React wrappers and built-in interactive callbacks.[16] The published license restricts use to specified Aura/commercial Neo4j offerings.[31] | **Do not adopt as the default.** The reused research database is Community and authored YAML works without Neo4j. Any NVL proposal needs explicit licensing review and a matching entitlement; visual similarity is not permission. |
| Extend the current custom SVG | Existing code is small and already has keyboard node controls. | Useful rollback/baseline; not preferred as a long-term route to independently implementing force layout, 3D, hit testing, and resource management. |

### 4.1 Version and dependency gate

The frontend currently pins React/React DOM `19.3.0`, TypeScript `5.9.3`, Vite `8.3.0`, TanStack Query `5.102.8`, Router `1.170.35`, and Playwright `1.58.2` in `web/arena-workbench/package.json`. No graph engine, Three.js, TanStack Table, or TanStack Virtual is directly declared there.

- Do not upgrade React, Router, Query, Vite, or TypeScript to make this feature convenient.
- Check the exact **standalone** package manifests, declaration files, license notices, transitive dependencies, and browser entry points at implementation time. An umbrella manifest with `react: "*"` is not a React 19 compatibility test.[35]
- Pin selected versions in `package.json` and the existing lockfile after the spike. Record the resolved versions, peer warnings, audit findings, and chunk sizes in acceptance evidence.
- Install/build/test only through the discovered non-root frontend container or matching disposable tooling container. No Node toolchain in the robotics runtime or host.
- Do not load libraries, fonts, sprites, or sample datasets from a CDN at runtime.
- If custom 3D geometries require a direct Three.js import, declare a compatible dependency deliberately and verify a single compatible resolved Three.js instance. Avoid accidental duplication through transitive imports.

### 4.2 Table decision

Use a semantic HTML table with controlled client-side filtering/sorting/pagination. Prefer `@tanstack/react-table` only after verifying the selected stable major in Phase 0; TanStack Query/Router already being installed does **not** install Table.

The researched v8 sorting guide documents `useReactTable` and controlled sorting; versioned v9 documentation exposes a different API. Freeze one major and use its matching documentation rather than mixing examples.[24][5] Table does not include virtualization by itself; that is a separate rendering layer.[32]

For the current bounded query output, start with pagination rather than adding virtualization automatically. Suggested page sizes: 25, 50, 100. Add TanStack Virtual only if measured authored-graph workloads justify the extra accessibility and focus-management complexity. Client-side sorting covers **returned data only**, not every graph entity in Neo4j.[24]

## 5. Detailed interaction design

### 5.1 Workspace structure

Proposed hierarchy:

```text
Authored spatial graph                         Authored YAML · Read-only layout
[Table] [2D] [3D]                               [Expand]
[Search returned graph] [Node roles] [Relationship types] [Clear filters]
Visible: N / returned N nodes · M / returned M relationships
[Zoom -] [Zoom +] [Fit visible] [Focus selection] [Navigation controls]
[Freeze layout] [Reset layout] [Help]
+------------------------------------------------+---------------------------+
| Table / 2D canvas / optional 3D canvas          | Selection inspector       |
|                                                | Identity, role/type       |
|                                                | Properties                |
|                                                | Connected entities        |
+------------------------------------------------+---------------------------+
Layout only — dragging does not change YAML or physical poses.
```

- On narrow screens, stack the inspector under the view; do not squeeze graph and inspector into unreadable columns.
- Expanded mode uses available viewport space without remounting the editor, discarding a draft, or spawning another graph instance.
- Prefer an accessible expanded dialog first; browser Fullscreen API can be progressive enhancement. Escape closes expansion, returns focus to its trigger, and preserves graph state.
- The graph canvas starts with a usable height (proposed 480 CSS pixels on desktop). Capture real screenshots before accepting exact sizing.
- Provide an empty state, no-filter-matches state, malformed-projection state, loading state, and renderer-unavailable state separately.

### 5.2 Table mode

- Nested switch: **Nodes / Relationships**.
- Node columns: label, full ID (copyable), role, incident relationship count. Properties are summarized; full nested values belong in the inspector.
- Relationship columns: type/label, source label + ID, target label + ID, full edge ID, properties summary. Direction is explicit; a self-loop is not displayed as a missing endpoint.
- Sorting is stable with ID tie-breaking. Distinguish null, missing, numeric, and string values; do not produce an accidental lexical numeric sort.
- Use actual buttons for Inspect/Focus actions so keyboard users need not click a row. Pointer row selection is an additional convenience.
- Selecting a row updates the shared inspector and remains selected after switching to 2D or 3D.
- Pagination never changes the graph's filter result. “Focus selection” should reveal the selected row's page when returning to Table.
- Counts state **returned**, **visible**, and **page rows** distinctly. No implied whole-database count.

### 5.3 2D mode

- Background drag pans; node drag repositions the node; wheel/pinch zooms only when the graph owns the interaction. Do not trap ordinary page scrolling outside the graph.
- Define a small pointer-movement threshold so the release after dragging is not interpreted as an unrelated click. Handle pointer cancellation and lost capture.
- Single click selects a node or relationship. Background click clears selection unless it ends a pan gesture.
- A selection shows the node's one-hop incident edges and neighbors distinctly while dimming unrelated elements. Edge selection highlights both endpoints and the exact edge.
- “Focus selection” frames the selected node and visible neighbors, or the selected edge and its endpoints. “Fit visible” uses only the current visible graph, with label/inspector padding.
- Dragged nodes become pinned by default. Inspector/toolbar actions unpin the selection or all nodes; an explicit pin indicator avoids invisible layout constraints.
- “Reset layout” resets visual coordinates/pins/camera for the current graph view; it does not reset filters, change the document, or alter data. “Clear filters” is separate.
- “Freeze layout” stops force motion while allowing selection, camera movement, and deliberate dragging. On release while frozen, a dragged node stays pinned without reheating the rest of the graph.
- “Resume layout” resumes bounded force motion of unpinned nodes; reduced-motion mode defaults to a settled/frozen view.
- Keep labels readable at useful scales: selected/hovered labels take priority; a label-density control may offer Selected / Auto / All. Never require labels to overlap to prove all data exists.
- Draw arrows, curved parallel edges, reciprocal edges, and self-loops. Assign deterministic lanes by endpoint pair and edge ID; do not merge distinct edges merely because labels match.
- Use stable role colors and a legend. Reifiers need shape/text distinction, not color alone. Preserve current role semantics rather than inventing a taxonomy from label substrings.

### 5.4 3D mode

- Load the 3D renderer only after an explicit mode choice. The library documents orbit/trackball/fly options; prefer **orbit** for the initial interaction model and test its real bindings.[14]
- Background drag rotates/orbits, pan uses the documented secondary gesture, wheel/pinch zooms, and node drag moves within the engine's interaction plane. Document that plane and do not imply physical-axis editing.
- Provide the same selection, neighborhood, pinning, freeze, fit, and reset semantics as 2D where meaningful.
- Maintain independent 2D and 3D camera/coordinate state. Selection and filters are shared; coordinate edits are not blindly projected back and forth between dimensions.
- Relationship arrows and selection must remain inspectable under depth occlusion. Label only selected/hovered entities by default, with a table/inspector alternative for every item.
- Disable auto-rotation, animated particles, endless layout movement, and decorative effects by default.
- If WebGL initialization fails or its context is lost, present a bounded error and **Switch to 2D / Table** actions. Do not replace the entire editor with a blank canvas. Browsers expose a `webglcontextlost` event for this condition.[33]
- Capability failure is local to the renderer, not “Neo4j disconnected” or “YAML invalid.”

### 5.5 Search, filters, and selection rules

Use literal, case-insensitive substring search over bounded **ID / label / role or edge type** fields initially. Do not run user regular expressions or deep-search arbitrary property blobs on every keypress.

- Node-role and relationship-type filters operate on returned entities only.
- The renderer receives edges only when both endpoints are visible. Keep disconnected visible nodes; do not silently delete them because an edge-type filter hides their edges.
- Search exposes a bounded match list for nodes and relationships; choosing a match selects it. A separate **Show matches only** toggle changes visibility, avoiding an ambiguous mix of searching and hiding.
- One-hop focus is a local projection of the loaded graph. Label it **Loaded neighbors**, not “Expand database.” Never issue a query merely because a node was clicked.
- If selection is hidden by filters, retain its identity/inspector with “Hidden by filters” and a Reveal action. Do not silently clear user intent.
- If the selected entity no longer exists in a new authoritative graph revision, clear it with an announcement. If an authored edge ID is reused with different endpoints/type/properties, treat it as a different selection.
- If filters produce no results, retain counts and provide Clear filters; do not report a database failure.

#### Exact visibility and Reveal policy

The pure model must implement the following ordered projection; neither renderer may invent a different filter interpretation:

1. **Base nodes:** retain normalized nodes allowed by the explicit role filter. An empty allowed-role selection means no roles, not all roles; the Clear filters action explicitly restores all roles.
2. **Base edges:** retain normalized edges allowed by the explicit type filter whose two endpoints are base nodes. Invalid/quarantined entities never enter either base set.
3. **Search matches:** compute matching base nodes and matching base edges separately. When Show matches only is off, or the search text is empty, the search-node set is all base nodes. Otherwise it is the union of matching nodes and **both endpoints of matching edges**. This makes an edge-only text match visible even when neither endpoint's own text matches. Endpoints introduced this way are labelled search context, not direct text matches.
4. **Loaded-neighborhood scope:** when disabled, its node set is all base nodes. When enabled, seed it from the selected node, or both endpoints of the selected edge, then add one-hop neighbors along base edges, ignoring edge direction for membership but preserving direction when drawing. If the selected node is not a base node, or the selected edge is not a base edge, use an empty neighborhood set, show the exclusion, and offer Reveal; do not override filters silently. A removed selection disables neighborhood scope with an announcement; enabling this scope without a selection is disabled.
5. **Visible nodes:** intersect the search-node set with the loaded-neighborhood node set. **Visible edges:** all base edges whose endpoints are both visible nodes. Thus edges between search-context nodes may also appear; style direct text matches distinctly and describe the result as an induced context graph, not exclusively matching relationships.
6. Explicit role/type exclusions are authoritative, followed by the neighborhood intersection. Search never resurrects excluded endpoints; the match list is labelled as searching the currently allowed roles/types. Counts identify direct matches separately from contextual visible entities.
7. **Reveal (clear filters)** is an explicit action: restore all roles and types, turn off Show matches only and neighborhood scope, retain the search text as a non-filtering highlight, and focus the still-existing selection. Its label/help makes the clearing behavior explicit. It cannot reveal malformed/quarantined or server-omitted entities, and issues no query.

Acceptance fixtures must include an edge-only match, an excluded endpoint role, an excluded edge type, a neighborhood/search conflict, and Reveal from each conflict. Table pagination operates after this projection and never affects membership.

### 5.6 Persisted Neo4j integration

Keep the query-result switch **Table / Graph**:

- **Table** remains the raw `columns` and `rows` returned by Cypher, preserving scalar values, nested structures, redaction, and the existing truncation notice.
- **Graph** hosts the shared **Table / 2D / 3D** explorer. Its inner Table is explicitly labelled **Graph entities**, with Nodes/Relationships subtabs.
- Although nested tabs need careful labelling, this avoids changing the meaning of the existing raw Table. Usability review may rename outer Table to **Query rows**, but must preserve its default and data.
- Explorer data is exactly `result.graph`. No inferred relationships, automatic follow-up queries, or merging with the editor's authored graph.
- Failed/newly pending queries do not silently relabel the last successful result. Preserve stale/error/truncated notices outside the renderer's own state.
- All neighbor counts and filters apply to returned results; a connected badge does not prove the graph is complete or that it contains measured research evidence.

### 5.7 Required non-drag alternatives

W3C's dragging guidance requires a single-pointer alternative without dragging and treats keyboard equivalence as a separate requirement.[36] Accessible inspection alone does not satisfy this manipulation requirement.

- Keep visible Zoom in/out buttons; add a compact **Navigation controls** disclosure containing focusable Pan left/right/up/down buttons. Each activation performs a finite camera-relative step; holding a pointer or dragging is never required.
- In 3D, add Orbit left/right/up/down and Reset camera buttons. Expose the current step size through an accessible selector; apply bounded orbit/zoom ranges and avoid singular camera positions.
- The selected-node inspector contains **Reposition layout node** controls: directional nudge buttons and finite numeric X/Y inputs (plus Z in 3D) with an explicit Apply action. Label the coordinates **graph-layout units, not scene meters**. Use fixed graph axes for numeric entry and clearly labelled view-relative directions for nudging.
- Keyboard users can Tab to these controls and activate them with Enter/Space; click/tap-only users can achieve the same actions without a drag, wheel, pinch, long press, or multi-touch gesture. Optional canvas shortcuts supplement these controls and must not intercept typing in inputs.
- Reposition/nudge has the same pin-on-move behavior as dragging. While frozen, only the deliberately moved node changes; while live, unpinned neighbors may respond within the bounded layout budget. All controls remain usable with reduced motion.
- Every camera manipulation offered by gestures has a corresponding button/form action. Phase 0 must prove the adapter supports those actions; failing the test blocks adopting that engine.
- Add separate keyboard-only and click/tap-only browser scenarios for zoom, pan, orbit, selected-node reposition, pin/unpin, freeze, and reset. Assert real camera/coordinate changes and unchanged YAML, not just focusable button presence.

## 6. Architecture and data ownership

### 6.1 Proposed module boundary

```text
web/arena-workbench/src/
  graph-explorer/
    graph-explorer.tsx       # modes, provenance, toolbar, expansion, error boundary
    graph-model.ts          # indexes, validation, filtering, edge lanes, identities
    explorer-state.ts       # selection, filters, mode, reconciliation
    graph-table.tsx         # node/edge table model and accessible actions
    graph-2d.tsx            # renderer adapter; imperative layout/camera ownership
    graph-3d.tsx            # lazy renderer adapter; WebGL/resource ownership
    graph-inspector.tsx     # shared property/relationship inspection
    graph-explorer.css      # feature-scoped layout and theme integration
    *.test.ts[x]            # colocated pure-model/component tests
  graph-view.tsx            # temporary compatibility wrapper during migration
```

These are proposed responsibilities, not a mandate to create a file per trivial helper. Keep backend contracts in `editor-contracts.ts`; avoid a second competing definition of the API's Graph.

### 6.2 Three distinct state layers

1. **Authoritative data:** immutable server-returned graph, validation/provenance, raw query rows. Owned by existing editor/query flows.
2. **Explorer state:** selected `{kind, id}`, literal search, role/type filters, mode, table sort/page, and expansion. Owned by the shared explorer controller.
3. **Renderer state:** positions, velocities, fixed coordinates, camera transforms, GPU objects, hit-test structures. Owned by adapters, isolated from the authoritative graph and React Query cache.

D3 documents that simulations mutate nodes and link forces may replace string endpoints with object references.[22][23] TanStack Query documents immutable cache updates.[30] Therefore:

- Copy nodes and links into minimal renderer DTOs; keep full properties in an immutable ID-indexed model for the inspector.
- Never pass `validation.graph` or `result.graph` directly into a mutating engine.
- Renderer fields such as `x/y/z`, `vx/vy/vz`, `fx/fy/fz`, index, Three objects, and object-valued endpoints must never enter YAML, exports, query caches, job inputs, or document hashes.
- Keep per-frame updates outside React state; publish only meaningful interactions. Re-rendering the editor on every force tick is a failure.
- Normalize at the graph boundary from unknown JSON rather than relying on the API client's TypeScript cast (`web/arena-workbench/src/api.ts:87`). Validate graph shape, optional labels, and property JSON/sentinels without turning malformed data into an application-wide crash. Do not assume the 256 KiB authored YAML bound is a node-count bound.
- Use `Map`/`Set` for graph IDs and entity-kind-aware selection; do not turn untrusted IDs into plain-object prototype keys.
- Validate duplicates and dangling endpoints explicitly. Quarantine invalid edges with a visible warning/count rather than silently drawing a false relationship; duplicate IDs must not arbitrarily overwrite one another.

### 6.3 Identity and update policy

Proposed explorer inputs: the existing `graph` plus `label`, `sourceKind`, `scopeKey`, `revisionKey`, and a small provenance summary. Concrete prop names remain implementation choices.

- Authored scope: authenticated session + workspace + the API-returned content-bound document identity. Revision: validated canonical hash (and source/view identity where needed).
- Persisted scope: authenticated session + query-result context; revision is tied to the **submitted** query/parameters and returned result snapshot, not mutable query-editor text. Do not place raw query text/properties in URL parameters or persistence keys.
- Mode switches preserve controller state and separate per-mode camera/layout snapshots.
- Each presentation snapshot contains only a version/scope/revision token, finite numeric coordinates keyed by entity ID, a user-pin set, camera numbers, and the mode's frozen/live flag. Retain at most one 2D and one 3D snapshot for the current scope, not a revision history. Never retain DTOs, properties, DOM nodes, force objects, Three.js objects, or closures into the previous renderer in these snapshots; drop removed-node coordinates during reconciliation.
- **Controller placement is above conditional renderer mounting.** In the authored editor, hold controller state in a stable per-surface hook/host above the `valid` conditional: the current exact-text validation gate (`editor.tsx:108`, `:186`) temporarily unmounts GraphView after an edit, before debounced validation finishes. Stop/unmount rendering and withhold inspector data during that interval while retaining only scoped presentation state for reconciliation when valid data returns. Do not keep a stale visual visible to preserve state.
- In the persisted view, hold the controller above the outer Query rows / Graph switch (`neo4j.tsx:179`). Returning from raw rows to the same result must restore filters/selection without preserving a hidden running renderer. A controller inside the conditionally rendered GraphView would not meet this requirement.
- Same-scope graph updates may reconcile retained node positions by ID. New nodes receive deterministic initial positions; removed nodes are removed. Edge selection additionally checks semantic identity because authored indexed IDs can be reused.
- A different document, result identity, or session resets entity selection and pins. Do not let two views with coincident IDs share layout state.
- Invalid authored YAML withholds the graph as today. An internal previous layout may be retained briefly for a matching valid revision, but must never be presented as the current invalid draft.
- Start with in-memory, instance-scoped state; reload resets layout. Cross-route/reload layout persistence is deferred. Do not reuse draft/sessionStorage mechanisms to store graph properties or credentials.
- Session expiry/replacement explicitly clears the explorer's selection, presentation snapshots, and retained property references and cancels stale renderer callbacks. Existing RuntimeProvider does not globally purge draft/query caches, so this is a local explorer policy, not a claim of application-wide cache cleanup. Reject late graph/controller updates captured under an older session or scope; preserve unrelated user draft-recovery behavior.
- Camera resize and theme changes must not reset pins or reheat the layout. Use measured container dimensions; do not rely on the engine's window-size default.

## 7. Lifecycle, performance, and browser resources

### 7.1 Do not confuse layout pause with renderer pause

The candidate's `pauseAnimation()` freezes rendering **and cancels user interaction**; its cooldown controls and engine-stop callback are separate.[14] This is a release-blocking spike question:

- Prove a **Freeze layout** implementation that retains click, zoom, pan, and intentional node dragging. Do not simply wire that button to `pauseAnimation()`.
- For hidden/unmounted views, stop or dispose the engine and animation work. Rendering pause is appropriate there because interaction is not expected.
- Resume only the visible renderer, and do not automatically restart force motion if the user froze the layout.
- Verify each adapter's actual public API at the pinned version. Do not assume a React wrapper forwards every underlying engine method identically.

#### Freeze-state ownership and transitions

The stable controller owns a separate frozen/live preference for 2D and 3D and stores it in the corresponding presentation snapshot. Keep **user pins** distinct from temporary constraints used internally to freeze all coordinates; unpinning a node must not accidentally release the entire frozen layout.

| Action | Frozen mode | Live mode |
| --- | --- | --- |
| Drag, nudge, or apply selected-node coordinates | Move only the selected node, update its user pin; keep all other coordinates stationary. | Move and pin the node; permit bounded relaxation of unpinned neighbors. |
| Unpin selected / Unpin all | Change user-pin intent only; nothing moves until explicit Resume layout. | Remove user pins and allow bounded relaxation. |
| Reset layout | Clear user pins and restore deterministic initial coordinates/camera for this mode; remain frozen without automatic settling animation. | Clear user pins and reinitialize this mode with bounded settling. |
| Change filters / search / neighborhood | Reproject visibility without moving retained nodes; newly visible/new nodes use retained or deterministic coordinates. | Reconcile positions and allow a bounded layout update without resetting camera or user pins. |
| Switch mode / raw-row tab, then return | Restore this mode's frozen flag, camera, positions, and user pins; no implicit reheat. | Restore this mode's own state; resume only within the configured layout budget. |
| Fit, focus, pan, orbit, zoom, resize, or theme | Camera/style-only change; does not alter force motion or pin intent. | Same separation; no automatic reheat merely from camera/theme changes. |
| New document or session | Discard old snapshots; initialize the new scope according to reduced-motion/default settings. | Same reset of scope-owned state. |

Reset layout in Table is disabled until a visual mode is selected, avoiding an ambiguous choice of which layout to reset. Ordinary same-document revisions reconcile as specified above; returning from invalid YAML does not override the saved frozen preference. Test frozen → mode switch → return, Reset while frozen, and Unpin while frozen with multiple nodes to verify that unrelated nodes stay still.

### 7.2 Lazy loading and cleanup

React `lazy` can defer a component's code until first rendering.[26] Use a dedicated loading/error boundary for the 3D module and keep the editor shell and Table usable while it loads.

- React caches the lazy loader's promise/resolved value and sends a rejection to an error boundary; remounting the same lazy component is not a promised network retry.[26] Declare it outside render, keep mode/fallback controls outside its boundary, and offer Table/2D after import failure. The initial recovery policy is **reload the page to retry a failed module load**, with a warning to preserve unsaved work first; do not add cache-busting imports or automatic retry loops.
- Treat pending imports as unabortable work whose result is inert until the current mode/scope authorizes a mount. Check current session/scope/revision in adapter setup and invalidate owned callbacks at cleanup. Leaving 3D while loading, then changing document/session, must not mount a late renderer for the previous graph; selecting 3D later uses only the current validated graph.
- Test delayed import resolution and rejection after switching to Table/2D, after a document replacement, and after session expiry. No hidden WebGL context may initialize; controls/inspector survive outside the failed boundary. A failed old load must not overwrite current editor errors or selection state.
- Mount at most one visual renderer per explorer; do not keep hidden 2D and 3D simulations running behind tab panels.
- On mode change, save presentation state, detach events/observers, cancel owned animation/timers, and release renderer-owned resources.
- Dispose custom Three.js geometries, materials, and textures explicitly; JavaScript garbage collection alone is not the resource policy documented for these objects.[28]
- Verify wrapper cleanup under React development lifecycle remounts and repeated navigation. Do not double-dispose shared resources without a defined owner.
- Use a bounded device-pixel ratio/quality setting for 3D after measurement; avoid taxing the browser GPU unnecessarily while robotics workloads may use the same workstation.
- Browser WebGL rendering is not Isaac Sim rendering, but it is not cost-free. Do not describe this feature as “no GPU use.” It launches **no simulator GPU job**.

### 7.3 Proposed measurement gates, not measured results

Record browser version, viewport, device-pixel ratio, hardware, production/dev build, graph shape, visible counts, and warm/cold module state for every measurement.

| Workload | Purpose | Proposed gate |
| --- | --- | --- |
| Real default graph (6 nodes / 7 edges) | Baseline legibility and overhead | All entities inspectable, useful initial framing, no label pile-up. |
| Synthetic 50-node / 100-edge graph with long/duplicate labels | Typical richer authored content | Selection/filter response p95 below 100 ms after load; stable input responsiveness. |
| Synthetic 256-node / 512-edge graph | Existing persisted-projection envelope | Warm initial usable view within 2 seconds; interaction frame intervals p95 below 33 ms on the declared reference machine. |
| Synthetic 1,000-node / 2,000-edge authored stress case | Beyond persisted cap; characterize degradation only | No browser crash/unbounded allocation; warning and Table fallback remain responsive. This is not a promised 3D support envelope. |
| Repeated 2D ↔ 3D ↔ Table transitions | Leaks and stale-state behavior | 20 cycles without accumulating active canvases, observers, workers, or animation loops; report heap/GPU-resource trends rather than claiming exact cross-browser memory. |
| Cold application load without selecting 3D | Bundle isolation | No 3D module/WebGL initialization before selection; report added initial and lazy compressed bytes. |

These are proposed acceptance targets requiring calibration in Phase 0. If unmet, reduce visual complexity or change the renderer; do not silently drop data or declare success because unit tests pass.

- Bound layout warmup/cooldown and debounce search where measurements justify it. Avoid long synchronous stabilization before first paint.
- Do not increase API graph caps for a frontend benchmark. Label stress data as synthetic and keep it out of the experience database.
- No Web Worker is assumed initially. If force computation blocks the UI at accepted sizes, document the evidence before adding a worker and its message/cancellation lifecycle.
- Existing large-bundle build warnings are a baseline, not permission to add an eager 3D dependency. Establish a byte budget from the spike's measured output and review it before merge.

## 8. Accessibility, security, and reliability

### 8.1 Accessibility contract

Canvas/WebGL visuals are not a replacement for semantic access to graph entities.

- Every node and relationship must be discoverable, selectable, and inspectable through Table/search/inspector controls using only the keyboard.
- Use semantic HTML tables with header associations and `aria-sort`; the WAI table pattern recommends these semantics for tabular information.[11]
- Do not add `role="grid"` without implementing its focus/navigation contract. The grid pattern requires managed focus; it is not decorative markup.[12]
- Implement mode tabs with associated tabpanels, arrow-key focus movement, Home/End, and Enter/Space activation. Manual activation avoids starting a lazy 3D load merely by arrowing through tabs.[29]
- Provide labeled controls for fit, focus, pin/unpin, freeze/resume, reset, and close; no hover-only essential actions.
- Provide the keyboard and single-pointer, non-drag camera/node controls defined above. Test both modalities independently; a table-only inspection alternative does not replace node repositioning or orbit controls.[36]
- Announce selection changes, filtered counts, unavailable renderers, and cleared stale selections politely. Do not announce simulation ticks.
- Honor reduced motion, sufficient contrast, visible focus, and non-color role distinctions. Fullscreen/expanded mode must return focus correctly.
- Re-test the current accessible per-node Inspect expectation with the new table/search equivalents; do not delete those tests simply because Canvas has no SVG buttons.

### 8.2 Untrusted graph content

The candidate's `nodeLabel` and `linkLabel` APIs support HTML content.[14] Graph labels/properties can originate in YAML, an LLM result, or Neo4j; none are trusted markup.

- Use application-owned React/text-only tooltips and inspector output, or a rigorously verified text-only adapter. Do not hand raw labels to an HTML-capable tooltip path.
- No `dangerouslySetInnerHTML`, HTML injection, executable links, embedded remote images, or automatic loading from property URLs.
- Bound both summaries and expanded property inspection. Use a lazily expanded tree: render at most 100 children per expansion page and no more than 500 property rows at once; show explicit Load next / Collapse controls. Long scalar text is revealed in bounded 4 KiB display segments, not one eager full-tree `JSON.stringify` or DOM text node. These are proposed frontend display budgets, not server truncation limits; calibrate them in Phase 0. Retain access to available returned values through incremental expansion while respecting server `[redacted]` and `[truncated]` markers; never attempt to recover omitted data. Treat non-object sentinels safely in inspection and edge semantic-identity comparison.
- Do not infer that all authored properties are sanitized because the Neo4j projection has a redactor. Keep existing provider-secret boundaries and never copy provider settings into the graph model.
- No graph payloads in analytics, console logs, crash traces, localStorage, or URLs. Any later export needs explicit user action and a separate review.
- Test HTML/script-shaped labels, quotes, Unicode, duplicate display names, IDs such as `__proto__`, and extremely long values. Assertions must include **no unexpected network requests**, not just absence of an alert dialog.

### 8.3 No-side-effect invariants

Changing modes, searching, sorting, selecting, dragging, pinning, fitting, resetting layout, and expanding the view must not:

- modify YAML/source/canonical hashes;
- submit generation, preview, diagnostics, or evaluation jobs;
- save revisions or write to Neo4j;
- change API-key/provider state;
- resume a paused queue;
- create another SSE/SharedWorker observation stream.

Existing session/event polling may continue. Tests should distinguish those expected reads from forbidden writes. Any future session-activity integration for prolonged graph interaction is a separate deliberate policy decision, not an accidental side effect on every force tick.

## 9. Test and evidence plan

### 9.1 Pure model and reducer tests

- ID-indexing, empty graphs, one node, disconnected nodes, self-loops, parallel/reciprocal edges, explicit reifiers.
- Duplicate IDs, dangling edges, same-label different-ID entities, and node/edge ID collisions handled by entity-kind-aware selection.
- Deep-freeze the input Graph; layout preparation, interaction, sorting, and filtering must not mutate it or attach object endpoints.
- Literal search/filter semantics; deterministic lane assignment; count consistency; selection hidden versus removed.
- Edge-only search matches include both allowed endpoints; explicit role/type exclusions and neighborhood intersections win; Reveal clears those constraints exactly as documented.
- Same-document revision changes, indexed edge-ID reuse, different-document/session switches, and valid → invalid → valid transitions.
- Multi-label Neo4j reifiers, non-object `[truncated]` properties, optional-label shape validation, and late results from an older scope/session.
- Separate 2D/3D presentation snapshots and no cross-source state collisions.

### 9.2 Component tests

- Table/2D/3D tab semantics; initial 2D choice; lazy-loading/error fallback.
- Node and relationship property inspectors; endpoint navigation; keyboard actions and sorting.
- Filtered selection warning and Reveal; empty versus invalid/truncated/error states.
- Fullscreen/expanded focus restoration, theme changes, resize, reduced motion.
- Secret-shaped and hostile content remains text; provider credentials never enter explorer state.
- Mock adapters only for controller boundaries. Mocked canvas tests are **not** proof of dragging, WebGL rendering, or cleanup.

### 9.3 Real-browser rendering and interaction tests

Use the actual candidate engines with synthetic deterministic fixtures and the real default authored projection. Keep synthetic graphs visibly labelled and outside Neo4j.

- Verify useful pixels/screenshots in 2D and 3D, not merely a nonempty canvas element.
- Hit-test/select an actual node and actual edge; assert the inspector shows the expected source identity.
- Drag a real node and verify a changed layout position without a changed source graph; pan the background and verify a changed camera rather than a moved node.
- Freeze layout, then demonstrate that node/edge selection, pan/zoom, and deliberate dragging still work.
- Repeat camera movement and node repositioning using keyboard controls alone, then click/tap-only controls without dragging. Test frozen Reset/Unpin and frozen mode-return with unchanged unrelated-node coordinates.
- Pin/unpin/reset; fit filtered results; focus selected edge endpoints; verify loops/multi-edges remain separately inspectable.
- Switch Table → 2D → 3D → Table with consistent selection/filters; verify renderer-specific camera state is not confused.
- Exercise authored valid → validation-pending → invalid → valid transitions and outer Neo4j Query rows → Graph transitions. Assert presentation continuity for the same source without stale graph display or a hidden running engine.
- Exercise the actual expanded UI at desktop and narrow viewports in light/dark mode.
- Force 3D load failure and WebGL context loss; retain Table/2D/inspector access and the unsaved YAML draft.
- Delay the 3D import across mode/document/session changes and resolve/reject it afterward; verify no stale/hidden renderer is initialized and fallback controls still work.
- Repeated mode/route switches and document replacement leave no orphan canvases or force/render loops.
- Record requests and job IDs before/after local interactions; no generation/snapshot/save/query writes or credential changes are accepted.
- Live Neo4j test: run an explicitly authorized read-only query once, then navigate its returned graph without further query submissions. Verify raw scalar Query rows remain accessible and truncation remains visible.
- A software-rendered/headless WebGL test is an integration gate only. Also inspect on a real GPU-backed browser before claiming 3D usability or performance.

A narrow test-only observability hook may expose adapter camera/layout state for assertions, but it must not become a production data endpoint or replace actual pointer/pixel tests. Decide its shape in Phase 0.

### 9.4 Regression and operational verification

- Run targeted RED → GREEN tests for each vertical feature slice, then the full frontend suite and production TypeScript/Vite build inside the non-root frontend container.
- Retain existing YAML validation, immutable save, recovery, theme, snapshot catalogue, provider-key, and query tests.
- Run existing Python projection/query tests inside the discovered non-root Arena runtime if contracts or projection assumptions are touched. This plan does not authorize schema changes or simulator runs.
- Run scoped host pre-commit and documentation/link checks. Build documentation when the architecture/runbook pages are updated during implementation.
- Use the repository's current Playwright image/version and discovered mount/UID/GID. Direct reports to a writable temporary directory when source is read-only.
- Never stop the operator's active API for a test. If deployment eventually needs a restart, inspect jobs and announce credential-loss consequences first.
- Preserve baseline screenshots, exact fixture identities, package versions, test outputs, browser/hardware metadata, and known limitations in an acceptance record. Do not use historical scene images as graph-renderer evidence.

## 10. Phased execution and approval gates

### Phase 0 — Baseline and isolated compatibility spike

**Before beginning:** user approves this plan and the proposed dependencies in principle.

1. Capture current authored and persisted graph/table UX at matching viewports.
2. Record actual graph envelopes, including a reifier example, self-loops, and multi-edges.
3. In an isolated non-production fixture, test the standalone 2D/3D packages with the pinned project React/TypeScript/Vite toolchain.
4. Verify node/edge click, dragging, freeze-with-interaction, safe labels, 3D orbit, cleanup, and lazy bundle separation.
5. Evaluate Cytoscape as the 2D alternative only if the preferred engine misses a critical gate.
6. Resolve the table major/version and pagination decision; record licenses/transitive dependencies and initial performance.

**Exit:** a short decision record names pinned candidate versions, measured costs, API constraints, and pass/fail evidence. Failure means revise the choice, **not** install a half-working renderer in the main editor.

### Phase 1 — Shared model, accessible Table, and controller

1. Add pure data preparation/reconciliation tests before implementation.
2. Add entity tables, search/filter state, selection, and inspector using immutable inputs.
3. Preserve the existing SVG behind a temporary compatibility adapter while the new shared shell is tested.
4. Add provenance, visible counts, invalid/stale behavior, and expansion without touching runtime ownership.

**Exit:** Table/controller acceptance passes; no source mutation or new network side effects; current workflows still work.

### Phase 2 — Production-quality 2D

1. Add the 2D adapter and deterministic edge lanes/reifier treatment.
2. Implement and browser-test the complete drag/pin/freeze/focus/fit contract.
3. Test density, theme, accessibility alternatives, resize, and cleanup against Phase 0 measurements.
4. Integrate the authored view first through the existing GraphView boundary.

**Exit:** the 2D view is demonstrably more usable than the baseline for real and dense fixtures, with no editor regressions.

### Phase 3 — Optional 3D

1. Add the lazy 3D module and bounded resource lifecycle.
2. Wire shared selection/filter/inspector state with separate camera/positions.
3. Add WebGL failure/context-loss handling and inspect real browser pixels/interactions.
4. Measure repeated mount/unmount and mixed workloads; keep the 2D/Table escape paths reliable.

**Exit:** all promised 3D interactions work; unsupported browsers degrade explicitly rather than hiding data. Do not label a disabled tab as completed 3D support.

### Phase 4 — Persisted-query integration and full regression

1. Reuse the explorer for `result.graph` without changing raw Query rows.
2. Preserve submitted-query identity, stale notices, scalar-only results, redaction, and truncation.
3. Complete browser regression for both source kinds, provider-key controls, draft recovery, and zero expensive submissions.
4. Compare baseline/final screenshots, performance, and chunk sizes; independently review security and architecture.

**Exit:** authored and persisted views meet the same explorer contract while retaining different provenance and persistence semantics.

### Phase 5 — Documentation, rollout, and cleanup

1. Update the canonical workbench architecture/runbook and README with controls, source boundaries, browser requirements, and limitations.
2. Document proposed module ownership and state lifecycle; keep this plan as a decision/acceptance record, not a competing runbook.
3. Obtain user acceptance of actual screenshots and interactions before making the new renderer the sole default.
4. Remove the temporary old-SVG compatibility implementation only after acceptance and rollback verification.

**Exit:** supported launch path verified, no unrelated working-tree changes lost, independent review passed, and all limitations are stated. No commit/push is implied by implementation approval.

### Concrete rollback mechanism during Phases 1–5

Use a temporary **frontend-only renderer selector at the existing shared GraphView boundary**, with `legacy` and `explorer` choices. This is a proposed implementation requirement, not an existing launcher flag.

- A validated, nonsecret URL search value `graphRenderer=legacy|explorer` selects the mode on both authored and persisted graph routes. Preserve unrelated search parameters. Invalid values use the current rollout default. Do not persist graph data or credentials in this parameter.
- Until acceptance, the default remains `legacy`; test and user-preview URLs explicitly request `explorer`. A **Use legacy graph** action lives in the outer shared host, outside lazy imports and renderer error boundaries, and updates only this local route setting. Its availability must not depend on the new engine loading successfully.
- Both routes keep their validity/session/provenance gates and raw data tables; the switch changes only graph presentation. Falling back disposes the new engine and clears its presentation snapshots while preserving YAML draft, prompt, document, query text/result, provider controls, and job state. No API restart is needed.
- Require lazy loading of the new explorer implementation from that boundary so a failed optional module does not make the legacy route unusable. Do not static-import new engine modules from the legacy path.
- Roll back immediately for missing entities, incorrect identity/selection, XSS or unexpected network activity, draft/provider-state corruption, failed non-drag controls, or unacceptable resource use. Read-only Table/legacy access stays available while the issue is investigated; rollback is not a waiver of acceptance criteria.
- Dependency/lockfile additions remain installed but unused during a renderer-switch rollback. If they themselves break the frontend build, stop integration and apply a **reviewed graph-feature-only reverse patch**, including exactly its manifest/lockfile hunks, after checking for concurrent dependency edits. Re-run the non-root clean install/build and both legacy consumer tests. Do not blindly restore the entire manifest/lockfile over later changes.
- Never use a whole-tree reset, blanket stash, or unrelated-file checkout for this rollback. Record a baseline diff before graph implementation and compare it afterward so existing provider-key changes remain intact. Commits or history changes require separate user authorization.
- Before switching the default, exercise rollback from both consumers, including simulated explorer-import failure, with an unsaved YAML draft and retained raw query rows. Verify unchanged content/job IDs, legacy node inspection, and resource cleanup.
- Keep the selector and legacy implementation through user acceptance. Remove them only in an isolated cleanup change after a verified legacy-capable frontend build artifact and feature-only reverse patch are retained with reproduction instructions. Test restoration of that artifact/patch before removing the live fallback; do not claim rollback is verified merely because the old file exists.

## 11. Risks and mitigations

| Risk | Mitigation / release gate |
| --- | --- |
| HTML-capable tooltips expose untrusted content | Text-only adapters, hostile-label tests, no external-resource loads. |
| Force engine mutates Query/editor data | Separate minimal renderer copies and deep-freeze regressions. |
| “Pause” disables click/drag | Prove freeze-versus-render-pause behavior before choosing the engine. |
| Browser GPU/resources leak | Explicit ownership/cleanup, one mounted renderer, repeated-cycle tests. |
| 3D is impressive but less legible | 2D default, selected labels, focus/neighborhood controls, Table always available. |
| Dense edges or self-loops become indistinguishable | Stable curved lanes, arrows, hit testing, exact-edge table/inspector selection. |
| YAML reorder reuses a relation ID | Semantic identity check or selection reset on changed graph revision. |
| Layout masquerades as physical positions/evidence | Persistent layout-only/provenance labels; no semantic write callbacks. |
| Raw query values lost during “Table” migration | Preserve outer Query rows; inner table explicitly Graph entities. |
| Keyboard support regresses with Canvas | Equivalent semantic tables/search/inspector actions and manual browser review. |
| Dependency/version mismatch | Pinned-version spike; no unrelated toolchain upgrade; do not mix v8/v9 or Sigma v3/v4 docs. |
| Performance targets only hold on small fixtures | Measured envelope, declared hardware, synthetic stress fixtures, explicit degradation. |
| New controls crowd the research editor | Expand action, responsive inspector, compact toolbar, baseline/final UX review. |
| Source/session changes show a stale selection | Scope/revision-aware reconciliation; invalid graph withholding; no cross-session storage. |

## 12. Approval checklist and unresolved decisions

Before implementation, confirm:

- [ ] Approve Table / 2D / optional 3D, with 2D default and read-only layout semantics.
- [ ] Approve a shared authored/persisted explorer while retaining Neo4j raw Query rows.
- [ ] Approve the standalone force-graph candidate spike and the Cytoscape fallback gate.
- [ ] Approve in-memory layout state only; reload reset is acceptable for the first release.
- [ ] Approve pin-on-drag and explicit Freeze/Resume, subject to demonstrated engine behavior.
- [ ] Agree the initial support envelope and calibrate performance targets on the actual workstation/browser.
- [ ] Select exact dependency/table major versions from the spike; no versions are approved solely by this document.
- [ ] Review expanded/narrow layouts and distinguish a relationship graph from a physical 3D scene.

Questions intentionally left to evidence rather than guesses:

1. Can the candidate preserve interaction while freezing layout cleanly in both adapters?
2. Are parallel edges and unary self-loops legible and independently clickable at the accepted density?
3. Does the standalone dependency set work without peer/type/workaround upgrades in this exact React 19 build?
4. Are 3D cold-load and memory costs acceptable on the operator's browser, including software/no-WebGL paths?
5. Is paginated semantic Table sufficient, or do measured authored fixtures justify virtualization?
6. Does the actual UX justify any later cross-route layout retention, without expanding privacy/storage scope?

## 13. Planning verification and review record

- Repository integration points and current graph contracts were inspected read-only.
- The default document's graph counts were read from the live API; no graph renderer implementation or benchmark was performed.
- Public primary documentation was retrieved for renderer APIs, licenses, force mutation, table behavior, accessibility, lazy loading, and WebGL cleanup.
- Citation verification, existing repository-reference checks, scoped pre-commit, and whitespace checks passed. The final Sources block includes the W3C dragging guidance [36]; the reviewer's missing-entry observation preceded regeneration of that block.
- Independent source-architecture audit: **completed**. Its actionable findings were checked against source and incorporated: stable controller ownership above conditional mounts; exact source/revision identity; indexed edge-ID reuse; reifier validation gaps; optional Neo4j labels; property truncation sentinels; local session cleanup; and preservation of raw query rows and backend limits. The audit ran no tests or renderers.
- Initial independent full-plan review: **revise**. Three blockers were identified and addressed in this document: (1) keyboard and click/tap-only alternatives for manipulation, (2) exact edge-match/endpoint visibility and Reveal rules, and (3) an explicit shared-boundary rollback selector plus scoped dependency reversal. Additional comments produced bounded property-tree rendering, presentation-only snapshots, a per-mode freeze transition matrix, and delayed-import/session-race acceptance. These are design corrections, not executed feature tests.
- Focused independent re-review of the corrected plan: **PASS**, with no blocking contradictions. The reviewer confirmed the non-drag controls, ordered visibility/Reveal policy, concrete rollback, presentation-only snapshots, freeze transitions, bounded inspection, and delayed-import handling. This verdict concerns the plan, not demonstrated renderer behavior. Implementation remains unapproved.
- Implementation/test checklist items above remain unchecked; planning is not feature completion.

## 14. Implementation execution record

The user approved implementation after the reviewed plan. Earlier planning-review statements that implementation was unapproved describe that historical gate, not the current authorization.

- [x] Rechecked checkout and discovered the existing non-root frontend/runtime deployment.
- [x] Baseline frontend suite: 131 tests passed before graph changes.
- [x] Phase 0 core renderer compatibility and interaction spike; later hardware gates verified in the integrated implementation.
- [x] Shared immutable model and accessible Table/controller engineering acceptance.
- [x] 2D adapter engineering acceptance.
- [x] Lazy 3D adapter and bounded failure/lifecycle engineering acceptance.
- [x] Authored/persisted integration and legacy-switch rollback acceptance.
- [x] Browser, bounded performance, security and independent implementation review.
- [x] Architecture/runbook update and preview handoff.
- [ ] User visual acceptance and separately approved fallback removal.

Only completed, tool-backed gates are checked here. Review findings remain blockers until their regressions and re-review pass; the legacy renderer remains the default.

### Evidence collected during implementation

- Isolated spike: standalone wrappers `1.29.1`, TanStack Table `8.21.3`, and Three/types `0.180.0` passed the core interaction gate. An unconstrained Three `0.186.0` closure produced real pointer errors and was rejected. Evidence: `/eval/.graph-explorer-spike/README.md` and its lockfile/browser reports. The production dependency graph has one deduplicated Three instance.
- The implementation initially reproduced a rapid-3D-switch `layout.tick` error. Removing reheat before deferred graph initialization fixed the recorded 20-cycle failure; both software and NVIDIA hardware checks subsequently passed with zero leftover graph canvases/pending RAF callbacks.
- Hardware renderer: ANGLE EGL reports `NVIDIA RTX PRO 6000 Blackwell Workstation Edition`, not SwiftShader. Hardware acceptance reports are under `/eval/graph-explorer-acceptance/`, including `hardware-report.json`, `hardware-extra-report.json`, and `live-report.json`.
- The real authenticated API/default document and a bounded, explicit Neo4j query were exercised through Table/2D/3D and legacy rollback. Source YAML/canonical hash and job IDs were unchanged. These checks did not invoke generation, save, or simulation.
- Synthetic 50/100 and 256/512 node/edge fixtures became 2D-ready in under one second in the recorded hardware run. Browser RAF interval p95 was about 16.8 ms; these are browser responsiveness samples, not a general renderer throughput guarantee. The 1,000/2,000 fixture used the explicit Table fallback.
- Post-GC heap readings across 20 mixed-mode cycles rose from 32,122,668 bytes after the first 3D load to 34,557,048 bytes at the end. This records a trend, not proof of zero memory/GPU-resource leakage; no unbounded-retention claim is made.
- First full implementation review found authored-session validation ownership and newly introduced role/type filtering bugs. Session/source ownership now passes focused regressions and independent re-review. A further Clear/Reveal-on-empty-graph intent bug was corrected by resetting filter intent and category history together. The model/state/controller regression run passed 51 tests, and the final focused filter re-review passed without blockers. Review also prompted bounded full-key/type inspection, conservative truncated-edge identity, and stronger rollback assertions.
- Independent renderer review found a 3D engine-stop/update feedback loop, refresh-triggered resource disposal churn, offscreen animation, selection-only layout reconstruction, coincident-edge hit geometry, and inconsistent layout/camera bounds. Scoped fixes passed seven actual-engine NVIDIA regressions and final independent re-review with no concrete blockers. Idle commits/publications stabilized; selection retained DTOs; custom node/sprite resources had zero style-change disposals and exactly one teardown disposal; offscreen RAF paused; coincident edge picking and million-unit fit/focus passed. Details: `/eval/graph-explorer-acceptance/renderer-review-closure.md`.

### Final verification and handoff

- Parent rerun: **229 frontend tests in 32 files passed**; TypeScript and production Vite build passed. **37 API graph/projection/editor validation tests passed**, with unrelated tests deselected.
- Parent final NVIDIA browser run: **20 tests passed, zero failed/skipped/flaky**, covering synthetic API fixtures with real engines, dedicated engine regressions, density limits, and real authenticated authored/Neo4j data. Machine-readable evidence: `/eval/graph-explorer-acceptance/final-report.json` and `final-summary.json`; screenshots: `final-results/`. Host counterparts are under `/home/tarfy/eval/graph-explorer-acceptance/`.
- Pre-commit passed across all 54 changed files; whitespace checks and the strict Sphinx build passed. No commits or pushes were made.
- Production build retains the large-chunk warning. Initial application JS is 339.62 kB gzip; the separate lazy 3D chunk is 307.96 kB gzip. These are final build sizes, not deltas or network timing guarantees.
- Preview: `http://localhost:3001/workspaces/default?graphRenderer=explorer` (HTTP 200 and live browser workflow verified). Use **Use legacy graph** for local rollback; legacy remains the default.
- Remaining acceptance limits: user review of dense labels, depth occlusion, contrast and narrow/expanded ergonomics; long-duration GPU/heap behavior is not proven by bounded lifecycle tests. Actual-engine StrictMode and topology-replacement disposal coverage is a non-blocking follow-up identified by final review. No universal leak-free or performance guarantee is claimed.
- No generation, simulation, save, provider-setting, or graph-publication jobs were submitted by these checks. The live graph query was an explicit bounded read, and source/job-list invariance was verified.

## Sources

[1] https://js.cytoscape.org
[4] https://sigmajs.org
[5] https://tanstack.com/table/v9/docs/framework/react/guide/virtualization
[8] https://neo4j.com/docs/browser
[11] https://www.w3.org/WAI/ARIA/apg/patterns/table
[12] https://www.w3.org/WAI/ARIA/apg/patterns/grid
[14] https://github.com/vasturiano/react-force-graph
[16] https://neo4j.com/docs/nvl/current/react-wrappers
[18] https://reactflow.dev/learn/concepts/terms-and-definitions
[22] https://d3js.org/d3-force/simulation
[23] https://d3js.org/d3-force/link
[24] https://tanstack.com/table/v8/docs/guide/sorting
[26] https://react.dev/reference/react/lazy
[28] https://threejs.org/manual/en/cleanup.html
[29] https://www.w3.org/WAI/ARIA/apg/patterns/tabs
[30] https://tanstack.com/query/latest/docs/framework/react/guides/updates-from-mutation-responses
[31] https://neo4j.com/docs/reference/license/nvl
[32] https://tanstack.com/table/v8/docs/guide/virtualization
[33] https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/webglcontextlost_event
[34] https://raw.githubusercontent.com/vasturiano/react-force-graph/master/LICENSE
[35] https://raw.githubusercontent.com/vasturiano/react-force-graph/master/package.json
[36] https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html
