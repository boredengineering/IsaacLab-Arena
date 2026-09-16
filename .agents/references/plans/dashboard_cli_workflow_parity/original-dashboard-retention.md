# Original-dashboard retention review

Status: U2 findings and proposed next UI slice, not implemented parity. Source audit `deleg_ffe92b51` compared the original dashboard with the offline preview; parent checked the original query, journal/inspector and diagnostic controls against the preview graph/run panels. The layout-only v4 does not close these gaps.

The preview expanded planned workflows but omitted parts of the existing dashboard rather than merely relocating them. Named destinations and the historical CLI ledger do not establish retention of existing UI controls.

## V5 restoration status

The user approved the next offline slice. V5 source now provides explicit Neo4j query and Jobs & diagnostics workspaces, with local query/fixture binding, operational journal/inspector and diagnostic-review interactions. Publication remains in Research graph; research reports remain in Runs & evidence without operational controls. This addresses the named-workspace UI gap, not live query execution, real durable recovery, deployment or full original-dashboard parity. The other editor/metadata/provider/evidence gaps listed below remain open. See implementation progress for verification/export status.

## Original v4 priority findings

Paths below are relative to `web/arena-workbench/src/`.

| Existing feature | Source | Preview representation | Finding |
| --- | --- | --- | --- |
| Neo4j query composer: examples, Cypher, JSON-object parameters, explicit query and connection check | `neo4j.tsx:78–143` | `preview/workflow-panels.tsx:188–204`: local example-node label filter; explicitly no Cypher | Missing, not renamed |
| Query results: table/graph, row count/timing, stale and truncated result notices | `neo4j.tsx:145–221` | Fixed example node table and relationship prose | Only a partial illustration |
| Jobs journal: All/Active/Terminal filter, linked exact-job detail, timestamps and snapshot cursor | `app.tsx:398–517` | `preview/workflow-panels.tsx:155–185`: example queue and run selector | Partial; the operational journal is not reproduced |
| Exact job inspector: frozen inputs, result/error, cancellation requested versus cleanup, blocked-generation actions | `app.tsx:297–390` | Generic observe/cancel/recover review with unknown/cleanup examples | Partial; missing comparable detail and renewal surfaces |
| Integration diagnostic: opt-in capability, bounded steps/delay, retained-request retry and explicit queued-work resume | `app.tsx:145–292` | Diagnostics artifact selector and prerequisite prose | Missing; a diagnostics artifact is not a diagnostic execution workflow |
| Session controls and degraded observation: connection, end session/reconnect, stale snapshot | `app.tsx:94–134` | Offline banner and session-expired example states | Partial; login/signup mockups are not a replacement |

The original diagnostics form, journal and inspector are defined directly in `app.tsx`; there is no separate diagnostics component to infer from the filename tree. The original queue-resume control invokes a mutation; it must never be used merely to inspect the interface.

## Other retention gaps identified by the source audit

- Environment specification: schema diagnostics, hashes, flattened-YAML export and recovered-draft restore/download/discard (`editor.tsx:299–322,432–510`). Current textarea and local save examples are not equivalents.
- Render preview: Assets/Scene modes, camera/resolution choices, saved-preview refresh, retries and bounded automatic-preview consent (`editor.tsx:525–569`, `snapshots.tsx:134–135,194–211`). Current image-state examples show only part of the workflow.
- Authored graph: full structure/constraint inspection and renderer controls (`editor.tsx:570–596`, `graph-host.tsx:35–48`). The preview's fixed example graph is explicitly not synchronized from arbitrary YAML.
- Schema/registries: actual searchable metadata and paginated categories (`metadata-browser.tsx:25–59`), distinct from Coverage's historical ledger excerpts.
- Provider access: temporary-key lifetime, consent, refresh and forget controls (`model-settings.tsx:129–174`). Current nonsecret profile examples explain concepts but omit the lifecycle form. Any future preview must still reject real credential collection.
- Version/evidence details: research store/family/parent, manifest/lineage and exact consumed-prior inspection (`research-versions.tsx:189–210`, `generation-evidence.tsx:28–59`). Current Library/publication/evidence examples are partial.

## Recommended next UI-only slice

Restore discoverable, explicitly named **Neo4j query** and **Jobs & diagnostics** entry points before expanding more planned screens. Exact sidebar grouping remains a user-review decision; do not hide these capabilities behind an unlabeled generic selector.

1. Neo4j query: local composer, example selection, JSON validation, Table/Graph result-state previews and explicit stale/truncated/empty/error states. Keep read-only queries separate from publication actions.
2. Jobs & diagnostics: journal filters and exact-job inspector, with a separate secondary Developer diagnostics tab. Include blocked authorization, unresolved submission and cleanup-pending states; distinguish job operations from research reports/metrics in Runs & evidence.
3. Retain links between the views instead of inventing another job model or backend. Job IDs identify operations; run evidence identifies research results and their attribution.

All records/results must be labelled examples. No production runtime imports, API requests, query execution, job submission, queue resume, provider calls or credential capture. Review these surfaces with the user before connecting existing services.

## Evidence limits

The original dashboard shell was inspected at `http://localhost:3001/`; its navigation was visible while observation reported Connecting/unavailable. That is not proof the underlying features were removed or that live execution currently works. This audit establishes source/UI retention gaps, not deployment or database acceptance. Original production routes and code were not modified.
