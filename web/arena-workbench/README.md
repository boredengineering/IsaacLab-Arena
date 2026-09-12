# Arena environment workbench

React, TypeScript, Vite, TanStack Router and Query. The landing page is a two-column **ArenaEnvGraphSpec live editor**, with a pinned CodeMirror YAML editor, server validation, authored graph inspection, immutable revision export, reviewed prompt generation, and explicitly requested Isaac Sim snapshots. `/neo4j` is a separate read-only Cypher query surface with table and interactive graph results. `/developer/diagnostics` retains the opt-in transport diagnostics and `/jobs/:jobId` retains durable job deep links.

The UI does not invent document content, graph query results, progress percentages or images. Missing editor routes/adapters remain visible errors or disabled actions. Capabilities report adapter configuration, not successful generation/rendering. Unsaved drafts survive navigation and are retained in per-tab browser storage for reload recovery. After reload, Restore is explicit and requires matching source/frozen-view identities; changed includes block restoration but retain a YAML download option. Closing the tab or clearing storage can discard local recovery, so use immutable save/export for durable work. Accepted and unresolved editor job requests are retained separately and never automatically replayed.

## Appearance

Saved asset and scene previews are recovered from successful workspace jobs, including in fresh tabs. `snapshot-model.ts` selects the latest exact canonical scene match, deduplicates repeated renders, and bounds history to eight scenes. Older same-document previews are explicitly stale; matching asset names alone never establishes freshness. The workspace snapshot remains cached across route navigation. Recovery is currently limited to jobs present in the workspace snapshot or the explicitly retained job; a dedicated preview catalogue is planned.

Use **Render snapshots** beside Assets for an explicit GPU job. Missing robot thumbnails are labelled scene-only; failed image loads offer **Retry image**, which only fetches the existing artifact again. Zoom images are loaded on opening. Browser checks against an already rendered fixture use `WORKBENCH_E2E_CACHED_SNAPSHOTS=1` and `tests/e2e/asset-previews.spec.ts`; they never create a render automatically.

The Light/Dark switch at the far right of the top sidebar controls the whole workbench, including CodeMirror and authored/query graphs. Light is the default. The choice is saved under `arena.workbench.theme` in local storage; if browser storage is blocked, switching still works for the current page. Theme changes do not recreate the editor or submit jobs. `src/theme.tsx` owns preference state, `src/theme.css` owns the palette, and CodeMirror updates its appearance through a compartment.

For local launches, both `localhost` and `127.0.0.1` work on the configured port. Every mutation still requires an Origin matching that request's Host and the configured scheme, plus CSRF for established-session operations. Other hosts, ports and schemes are not implicitly trusted. These hostnames have separate browser cookies, storage and SharedWorkers; stay on one hostname while editing a draft.

## Run and verify without host Node installs

The deployment/proxy belongs to `docker/workbench/`; this directory owns application source only. Browser requests use relative `/api` URLs. Vite listens on internal `127.0.0.1:5173`; it intentionally has no direct API upstream. Use the same-origin Nginx proxy for real API work, not the Vite port.

Registry-validated build image: `node:22.22.0-bookworm-slim`, resolved digest `sha256:dd9d21971ec4395903fa6143c2b9267d048ae01ca6d3ea96f16cb30df6187d94`. Node 24 is also supported. Dependencies and transitive resolutions are pinned by `package-lock.json`.

Example on the Docker daemon host (set the **host-visible frontend directory**, not the editor-container path):

```sh
HOST_FRONTEND=/absolute/host/path/to/IsaacLab-Arena/web/arena-workbench
NODE_DEPS=arena-workbench-node-modules-v2  # choose a separate volume for another clone
# Set these from run_workbench.sh inspect, not from a root host shell's id command.
FRONTEND_UID=1000
FRONTEND_GID=1234

# Initialize only this disposable dependency volume; do not change source ownership.
docker volume create "$NODE_DEPS"
docker run --rm --user 0:0 \
  --mount type=volume,src="$NODE_DEPS",dst=/deps \
  node:22.22.0-bookworm-slim chown -R "$FRONTEND_UID:$FRONTEND_GID" /deps

docker run --rm --user "$FRONTEND_UID:$FRONTEND_GID" -e HOME=/tmp \
  --mount type=bind,src="$HOST_FRONTEND",dst=/app \
  --mount type=volume,src="$NODE_DEPS",dst=/app/node_modules \
  -w /app node:22.22.0-bookworm-slim \
  sh -c 'npm ci && npm test && npm run typecheck && npm run build'
```

`node_modules`, `dist`, browser screenshots, traces and reports are ignored locally. Do not install dependencies on the host or mount the whole repository into a frontend tooling container.

### Browser tests

Tests use Playwright 1.58.2 and its matching image `mcr.microsoft.com/playwright:v1.58.2-jammy`. That image's Node was checked as 24.13.0. `npm run test:e2e -- --list` discovers the tests without starting a workload.

A real static-build smoke test with explicitly injected API failures needs no backend or published port. Run all tooling as the same frontend UID/GID to avoid root-owned formatter/dependency caches:

```sh
docker run --rm --user "$FRONTEND_UID:$FRONTEND_GID" -e HOME=/tmp \
  --mount type=bind,src="$HOST_FRONTEND",dst=/app \
  --mount type=volume,src="$NODE_DEPS",dst=/app/node_modules \
  -w /app -e WORKBENCH_E2E_STATIC=1 \
  -e WORKBENCH_BASE_URL=http://127.0.0.1:4173 \
  mcr.microsoft.com/playwright:v1.58.2-jammy \
  npm run test:e2e -- disconnected.spec.ts
```

The production/development proxy must already be available for `workbench.spec.ts`. Set `WORKBENCH_BASE_URL` to its real browser origin. Diagnostic-submission tests additionally require **both** `WORKBENCH_E2E_DIAGNOSTICS=1` and API `--diagnostics`; otherwise the opt-in tests skip. They create only bounded diagnostic jobs, never simulations or generation. Run on an isolated integration journal with no unrelated active jobs. The long diagnostic crosses a 15-second heartbeat interval. The suite covers deep links, two tabs/one SharedWorker, actual progress, reload, accepted-but-lost response/idempotent retry, revocation and unsupported-SharedWorker polling. Restart/retention fault injection and actual proxy stream counting remain deployment/backend integration checks; the unit hub test proves the one-EventSource invariant.

No browser E2E server is started automatically unless `WORKBENCH_E2E_STATIC=1`. The isolated preview then uses internal port 4173 and is shut down by Playwright.

### Editor integration checks

`npm run test:e2e -- editor.spec.ts` uses actual authenticated `/api/editor` and `/api/graph` endpoints. The default cases load the real fixture, verify server diagnostics and authored graph nodes, save/export an immutable revision while verifying unchanged source, and query Neo4j. An absent editor API fails the test rather than silently substituting fixtures. A reported unavailable Neo4j connection is checked as an explicit unavailable state.

GPU and LLM tests are skipped unless separately authorized with `WORKBENCH_E2E_SNAPSHOTS=1` or `WORKBENCH_E2E_GENERATION=1`; each is bounded to five minutes. Do not enable these flags merely to run the suite. The snapshot case checks decoded real pixels, image zoom and stale labels after an edit. The generation case waits for a real completed job and explicitly applies the reviewed YAML.

For the existing frontend image, use `--entrypoint npm` (or `--entrypoint sh`) in disposable tooling containers: its default entrypoint is a persistent development supervisor and ignores a bare npm command as an executable override. Mount only this source directory writable for lockfile/build outputs and mount the clone's dependency volume. Match file ownership; do not change the running container lifecycle. Avoid formatting files while reading them through Vite's dev transform: a formatter's truncate/write can leave a cached empty module until a subsequent source edit invalidates it. Verify both the production build and a fresh browser load.

## State and safety rules

- Router owns `/`, `/workspaces/default`, `/neo4j`, `/developer/diagnostics`, `/jobs/:jobId` and validated `filter=all|active|terminal`. Navigation, preload and reload never submit jobs.
- Query owns reconciled workspace and exact job caches. The raw consistent snapshot has a separate query key, so late HTTP results cannot overwrite live job state directly. Job-mutation responses trigger a snapshot refresh rather than an unversioned cache overwrite.
- A named module SharedWorker owns one EventSource per origin and fans out through MessagePorts. A joining tab attaches its listener **before** requesting its snapshot. The reconciler applies only contiguous journal IDs newer than the snapshot cursor and ignores duplicate/stale replay. No timestamp-based ordering is used for state reconciliation.
- Pre-snapshot buffers cap at 256 events. Worker subscribers cap at 128 unacknowledged messages, including pulses; lagging subscribers receive a resync request and stop receiving events until their fresh snapshot is ready. `resync_required`, invalid events and gaps refetch an authoritative snapshot. No synthetic progress is generated.
- Stream failures close the old source, probe `GET /api/session`, and reconnect with 1/2/4…30-second capped backoff. Repeated failures report degradation. A worker heartbeat watchdog also detects unavailable worker support. Status-only snapshot polling is every 5 seconds, stops when watched jobs are terminal, and caps at 60 automatic attempts per observation session. Reconnect is explicit after exhaustion. Refocusing can read a snapshot but cannot renew a session or submit work.
- Sessions use same-origin HttpOnly cookies. Browser fetch provides `Origin`; JavaScript does not forge the forbidden header. Mutations supply `X-CSRF-Token` from memory. Origin-scoped Web Locks serialize initial session creation where supported. Session tokens are never written to browser storage or worker URLs. `401`/revocation stops observation and disables controls; a new session requires explicit reconnect, except normal initial page establishment.
- Explicit job/save/query actions call `/session/activity`; background validation, polling and stream probes do not extend idle expiry. Ending a session never cancels its jobs. A back-forward-cache restore shows disconnected rather than falsely claiming a stopped observer is live.
- Before a job POST, the exact request/key is saved in per-tab `sessionStorage`. Ambiguous network/timeout/invalid-response failures retain it across reload. Retrying is an explicit button action using the same key and frozen inputs, including after session replacement. No automatic mutation retry is configured. Storage failure blocks submissions. The request is removed only after a valid authoritative job response. Closing/clearing a tab may remove browser-local retention; inspect the durable journal before manually starting another test.
- Queued resume is explicit. Active cancellation remains `cancel_requested` until backend cleanup acknowledgment. `indeterminate` is not replayed or relabeled as success.

## API assumptions

`src/contracts.ts` preserves the durable session/journal contract for diagnostic, generation and snapshot jobs. `src/editor-contracts.ts` mirrors the shared editor API: `/editor`, `/editor/documents/:id`, `/editor/validate`, `/editor/save`, `/editor/generate`, `/editor/snapshots`, authenticated artifacts/revision downloads, and `/graph/status`, `/graph/examples`, `/graph/query`. The authored graph comes exclusively from current server validation; explicit reifiers are shown as diamonds and unary constraints and tasks retain their complete raw definitions. Neo4j results are never merged into that authored graph. The transport adapter must return:

- Public `GET /api/health`: `{status, capabilities: {diagnostic, generation: false, preview: false}}`.
- `POST /api/sessions`, `GET /api/session`, `POST /api/session/activity`: `{session_id, csrf_token, expires_at}`. `DELETE /api/session` revokes; no job ownership is removed.
- `GET /api/workspaces/default`: `{id: 'default', name, jobs, event_cursor}` from one consistent transaction.
- `POST /api/jobs`: bounded `{workspace_id: 'default', kind: 'diagnostic', idempotency_key, inputs: {steps, delay_seconds}}`, returning a full Job with HTTP 202. The same operator/workspace/key must remain idempotent across sessions.
- Explicit `POST /api/jobs/:id/cancel` and `POST /api/jobs/resume-queue` commands.
- `GET /api/events?after=N`: named `job` events with schema version 1, monotonic journal ID, job/workspace identity and a full Job; `resync_required` signals replay gaps. SSE event `id`/`Last-Event-ID` semantics belong to the backend. `session_expired`/`session_revoked` notifications are supported, but periodic session GET probes also detect 401 without relying on those optional event names.
- Single-operator/default-workspace journal IDs are contiguous. A gap or unsupported schema fails safely to snapshot resync. Timestamps are epoch seconds or ISO strings. Error bodies use `{detail: string}`; 401 means expired/revoked, 409 conflicting frozen inputs, 422 unsupported.

Unit/React tests use explicit fixtures; browser disconnected tests deliberately block API calls. Neither constitutes verification of a live backend, proxy permissions, a simulation, or research results.

Parent integration verified the actual editor on loopback port 3001: loading/validation, source-preserving save/export, real Neo4j table/graph results and actual decoded snapshots/zoom/stale labels passed Chromium tests. The live generation case remains skipped without configured model credentials. See the canonical workbench runbook for the current acceptance record and limits.
