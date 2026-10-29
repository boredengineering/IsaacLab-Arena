# Workflow design preview

A standalone React preview for reviewing the full research workflow before extending backend services. It does **not** replace or connect to the production workbench.

## Build and inspect

From the editor checkout (not the simulator), run:

```sh
python3 web/arena-workbench/scripts/run-preview.py
```

The launcher reuses installed Node/Playwright images and the discovered frontend dependency volume. It creates non-root, read-only, network-none containers with only frontend source/dependencies mounted. Egress denial is checked before repository imports. It runs preview-only unit tests, TypeScript, the preview build and an offline Chromium walkthrough, then removes its owned containers. No package downloads, API sessions, simulator imports, research volumes or credentials are required.

If the existing images, dependency volume or isolation are unavailable, stop and resolve that prerequisite explicitly. Do not run the tests in the live simulator as a substitute. The ordinary `npm run build` remains the production entry point; this preview uses separate configuration and does not change package scripts.

The command prints a new `/tmp/arena-ui-preview-*` directory containing:

- `artifact/arena-workflow-preview.html`: self-contained HTML; open directly in a browser, without a server.
- `browser/`: screenshots, Playwright trace and browser proof.
- `run-proof.json`: source hashes, artifact hash and owned-container cleanup results.
- Unit/typecheck/build/package logs. Failed attempts are retained separately.

The offline HTML embeds the compiled React/CSS assets and a hash-bound script policy. API connections, workers, forms targeting servers and external frames are prohibited by its content security policy. Opening it makes no live operations. All interactions and local example versions disappear on reload.

## Versioned desktop handoff

Container `/tmp` is evidence storage, not a desktop-browser path. Export each reviewed artifact into the host-mounted checkout under `outputs/ui-previews/vN/index.html`, preserving the host user's read access and verifying its SHA against the build proof. Never overwrite a prior version with different bytes. Keep a `version.json` checksum record per version and update only the top-level `outputs/ui-previews/index.html` comparison index.

The current archive contains v1 (initial workflow preview), v2 (global top account/theme bar and collapsible left navigation), v3 (Cybernetic-Physics branding with locally embedded website fonts), v4 (sidebar-owned collapse control and the original dashboard theme-switch presentation), v5 (explicit Neo4j query and Jobs & diagnostics workspaces), v6 (historical Assets & scene visualizer plus ovrtx/ovstream study), and v7 (cohesive authored inspection, pose reviews, memory recovery, exact-version Library and activity navigation). On the discovered host checkout, open `file:///home/tarfy/Documents/GitHub/BoredEngineer/IsaacLab-Arena/outputs/ui-previews/index.html`. Discover the host mount again if the checkout moves; do not substitute a container-only path.

In v2, Login and Sign up open inert account-layout dialogs with disabled, empty fields. There is no authentication or submission. The left sidebar can be collapsed using the top-left control; accessible route names remain available in the compact rail. Narrow screens initially collapse the navigation, and widening does not override a manual collapse. Neither layout nor theme changes replace the editable draft.

V4 moves the collapse control into the left sidebar and reproduces the original dashboard's sun/moon, Light/Dark label and slider presentation from `src/theme.tsx` / `src/theme.css`. It uses preview-local state rather than importing the production theme provider or sharing its storage key. Keyboard Space/Enter toggle appearance; Escape from navigation returns focus to the sidebar control. Wide and narrow sidebar choices are separate, so widening restores the desktop choice rather than overwriting it.

## Restored inspection and operations workspaces

V5 adds two directly named sidebar destinations, independent of editor selection and version-save controls:

- **Neo4j query:** local Cypher/JSON composer, finite-number validation, frozen review, explicit example-fixture loading, Table/Graph inspection and stale/empty/error/truncated states. Only exact bundled query/parameter values can load their labelled fixtures. Custom Cypher is never interpreted or executed; query syntax, permissions and server restrictions are not validated here. Connection states are illustrations, not connection checks.
- **Jobs & diagnostics:** All/Active/Terminal journal filters, exact-job inputs/outcome inspector, confirmation-gated cancellation/authorization reviews and a separate Developer diagnostics tab. Bounded inputs, retained same-ID retry, unavailable/invalid retention and whole-queue resume are local teaching scenarios, never submissions or acknowledgments.

Research graph retains publication preparation/outcome separately. Runs & evidence is for research reports, metrics, media and comparison; its former operational cancellation/recovery controls have moved out. No job controls or query result fixtures follow the editable environment's source selection. Navigation preserves each mounted workspace's local state. On narrow screens the graph/journal scroll horizontally instead of crushing labels.

Suggested new-workspace walkthrough: review a query, explicitly load its fixture, edit parameters and observe the stale binding; inspect a blocked job, freeze a renewal review, select another job and verify the original target remains visible; then review a diagnostic request and its same-ID retry. No completion or database result is produced by these actions.

## V6 Assets & scene

The direct **Assets & scene** destination and Environment → Preview link open the same retained visualizer. Assets/Scene views display three embedded historical PNGs: the maple-table scene, table reference and cube. Camera selection only selects matching saved captures; missing views do not reuse another image. Zoom is an enlarged saved image, not 3D navigation. Retry reloads embedded bytes, never a render job.

`render-samples/provenance.json` records the curated source/hash projection. The scene has a suspended mug; that known defect is preserved and disclosed. The standalone sideways robot image is excluded. Exact historical input bytes, source commit and asset freshness remain unverified, so these images never claim to match the current draft or to show ovrtx output.

Render planning and **Live RTX exploration** freeze local draft/source/options and retain stale reviews after changes. Consent does not revive after changing values back. Live Connect remains disabled. The proposed live stack is ovstage → ovrtx → ovstream WebRTC; no native SDK, stream server or GPU job is started by this preview. See the [ovrtx study](../../.agents/references/plans/dashboard_cli_workflow_parity/ovrtx-visualization-study.md) for primary sources, compatibility/security/licensing gates and a proposed authorized spike.

## V7 inspect and correct

V7 delivers a cohesive specification / historical viewport / authored inspector workspace at `outputs/ui-previews/v7/index.html`. The final isolated run passed 175 UI tests and the desktop/intermediate/mobile walkthrough; independent re-review passed. This is an offline preview, not a live integration. V1–V6 are preserved.

Suggested V7 flow:

1. Choose **Synthetic inspection lab** in the Environment family picker and explicitly Open v1. With no source selected, **Load inspection example** offers the same unsaved-input guard.
2. Select **cube**, inspect its authored parent/pose/scale, then enter a Proposed value and **Review pose change**. The frozen diff requires consent before **Apply reviewed pose change**; changing source, draft or edit options invalidates consent even if values change back.
3. Expand the viewport and return without remounting it. Hide/show specification and inspector independently; the desktop Specification width control changes layout only.
4. **Keep recovery copy**, edit, and **Review recovery copy** before restoring. Recovery is memory-only, not sessionStorage or durable history. Source changes block the old copy; discard remains explicit. **Download raw draft** downloads the actual current bytes, including invalid text, without claiming flattening or Arena schema validity.
5. Enter a zero scale in the JSON example and click its finding to focus the corresponding specification key. Local checks cover only the declared `inspect-correct/v1` JSON subset; arbitrary YAML stays editable but has no fabricated inspector projection.
6. In Library, pin an exact inspected version, select a distinct same-family comparison and freeze it. Changing the primary cannot create a self-comparison or rewrite the old review. Recents follow confirmed opens, not cancelled requests, and remain in memory only.
7. Open **Activity examples** to inspect an exact static job fixture or browse explicitly independent research examples. Counts are derived from the same job fixture set. Navigation never turns unavailable observation into a working connection or attaches diagnostic examples to the draft.

The authored table/cube fixture uses preview-only registry labels, not real USD prim identities. Its properties are not solved/simulated transforms. Historical Maple-table pixels remain unrelated to the current draft and are never updated by a pose edit. Native physics, viewport picking, ovrtx rendering and ovstream remain disconnected. Generation/refinement and their illustrative graph/retrieval references are retained in the collapsible generation controls.

## Company branding

V3 uses the Cybernetic-Physics wordmark, Tomorrow headings, IBM Plex Sans body text, Kode Mono technical labels and the website's black/neutral/green palette. Light mode is an explicitly adapted workbench theme. Font files and licenses are embedded in the HTML, so no font CDN connection is needed. See [BRANDING.md](BRANDING.md) for observed sources, exact tokens, adaptations and licensing. The source-hash proof includes nested brand assets.

## Suggested walkthrough

1. Start in Environment without selecting a document. Enter a prompt or use the A2 example. Preview the frozen request, inspect an explicitly labelled candidate, and apply it only after reviewing the replacement.
2. Review a version save and create a session-only example. This demonstrates selection and downstream context; it is not a disk save or allocated research version.
3. Open Library, search C1, inspect its grouped history, select a specific version, and explicitly open it. Policies, experiments and unclassified artifacts have separate types. Version order is numeric; baseline is explicit, never inferred newest/best. Synthetic history is not an inventory of real C1 records.
4. Explore Build & evaluate, Improve, Experiments, Runs & evidence, Research graph and Settings & readiness. Edit inputs and review confirmations; outcome selectors are deliberate examples, not progressing jobs.
5. In Research graph, inspect publication-unknown and observe-only recovery. In Runs & evidence, inspect zero episodes and cleanup pending.
6. Use Coverage & reference to search the original capability/option inventory, its unresolved audit gaps, and later managed-CLI additions. Planned placement is not a claim that every advanced field already has an effective typed adapter.

## Boundaries

- No production ApiClient, runtime/session provider, provider SDK, graph connection or job worker is imported by the preview entry.
- The NVIDIA documentation reference in Live RTX exploration is an external link, opened only by explicit user action. The offline browser walkthrough does not follow it; zero-request evidence covers the exercised preview interactions, not that optional navigation outside the preview. It does not connect a renderer or pass draft data to NVIDIA.
- Candidate/schema/catalogue/graph examples are illustrative. The simplified example YAML is not certified runnable, the graph is not parsed from arbitrary edited YAML, and no scene image or execution metric is fabricated.
- The Library imports only bundled example metadata. Import review does not read/upload actual files. Experiment input currently demonstrates a labelled JSON/legacy subset, not a complete YAML adapter.
- The coverage index preserves 394 historical ledger records and separates 12 statically extracted managed CLI additions. Backend status is not inferred from that index. Historical gaps remain visible; user coverage review is still required.
- The real workbench, live research data and prior incident recovery are separate. This preview neither repairs nor establishes absence of effects from that incident.

## Source map

`src/preview/preview-app.tsx` owns navigation, the editable draft and local version selections. `environment.tsx` owns prompt/refinement and candidate review. `inspect-correct-workspace.tsx` owns local inspection/proposals/recovery and wraps the sole retained visualizer. `activity-preview.tsx` reuses job summaries for disconnected navigation. `library.tsx` handles grouped source/version selection, pins, recents and comparisons. `workflow-panels.tsx` holds downstream forms. `coverage.tsx` exposes the static inventory and local references. `preview.html` and `preview.vite.config.ts` are independent of production startup.

To refresh the static coverage projection after a reviewed source inventory change, use `scripts/build-preview-coverage.py` according to its argument/help contract. Do not overwrite historical source hashes to make current implementation appear verified.
