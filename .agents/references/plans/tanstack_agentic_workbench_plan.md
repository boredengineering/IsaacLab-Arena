# TanStack agentic environment workbench: implementation plan for review

Status: implementation approved and in progress. The user approved the revised plan and requested implementation, including the planned `docker/workbench/` additions. Existing simulator launchers, shared workflows, submodules and policy services remain outside that change scope. Source audit baseline: `dev/0.3.0-prerelease`, commit `f6c018c03`; implementation began from clean commit `396ad6835`. The earlier proposal was rejected, then revised and approved. Completion must be recorded per acceptance gate, not inferred from this approval. Paid generation and dedicated GPU evaluation require the bounded run budgets described below.

## 1. Decision and scope

Build a TanStack research workbench around the existing agentic environment workflow, not a visual reskin of Streamlit and not a replacement robotics backend.

Selected frontend for this revision: React + TypeScript + Vite, TanStack Router and Query, built and served from a dedicated frontend container. Add TanStack Table for evidence tables. Start with a read-only interactive graph renderer, not a drag-to-mutate scene editor. TanStack Start and SSR are not needed for this local application; do not create a second authoritative backend in JavaScript.

Initial deployment contract: one local operator, one Python API process, a supervised work queue, and at most one workbench-owned active simulation job on the configured GPU. Existing policy and Neo4j services remain operator-managed. Multiple tabs must work safely, but distributed scheduling, collaborative editing, cloud deployment, live WebRTC, and automatic policy-server provisioning are out of scope.

First usable release: generation, YAML authoring/save, inspection and zero-action preview, with responsive editing and recoverable jobs. Read-only inspection is an intermediate implementation gate, not the finished replacement. Policy evaluation and DCRG remain a separately authorized extension.

Two independently useful deliverables:

1. A read-only scenario/revision/graph/evidence workbench that works without starting Isaac Sim or making LLM calls.
2. Authoring, generation, preview, and bounded evaluation controls on top of explicit execution contracts.

Keep Streamlit available until the replacement passes runtime parity tests. Do not rewrite the policy runner, Graph-RAG retriever, spatial solvers, or DCRG controller in TypeScript.

## 2. What the current system actually does

Implementation checkpoint: the main TanStack route is now an environment editor, not the Slice 0 diagnostic console. Document/schema/graph/save/export, actual scene/object snapshot display, and a separate read-only Neo4j query/table/graph surface have been exercised through the real API and browser. B1/B4 authored reifier differences are preserved. Generation is wired but live verification is blocked on server credentials and an approved model-call budget. Independent backend, query and frontend recovery reviews passed after fixes. This does not mark all roadmap gates complete: numbered-version-manager integration, full evaluation/DCRG controls, distributed scheduling, and automatic graph publication are not delivered. The canonical runbook records exact verified scope and limitations.

Paths in this section are repository-relative. `A/` denotes `isaaclab_arena/agentic_environment_generation/`; `E/` denotes `isaaclab_arena_examples/agentic_environment_generation/`; `S/` denotes `isaaclab_arena/environment_spec/`.

### 2.1 The UI and CLI are different workflow adapters

- `E/review_gui/generation_panel.py:56-73,100-151`: caches an agent in Streamlit session state, calls `generate_spec`, loads YAML into the editor, and saves through the flat `spec_io` exporter. It does not call natural-language `refine_spec` or the version manager.
- `E/environment_generation_runner.py:239-333`: builds catalogues, chooses generation or base-spec refinement, creates a numbered version through `EnvironmentVersionManager`, and attempts another Neo4j sync.
- `E/review_gui/editor_panel.py:33-57,82-93`: editor validation and save are separate from the agent's repair/check pipeline. A schema-valid manual edit does not rerun all generation checks.
- `E/gui_runner.py:75-130`: supervises a persistent SimApp process and Streamlit. The app can continue when SimApp is unavailable.
- `E/review_gui/spec_visualization/visualization_widgets.py:102-129`: shows asset cards, a background prim tree, a Mermaid spatial graph, unary constraints, and task rows. This is not an experience-graph browser.

### 2.2 Generation and refinement

Actual generation flow (`A/environment_generation_agent.py:174-359`):

    registry-backed catalogues
      -> keyword-filtered Graph-RAG priors
      -> structured spec inference
      -> optional USD object-reference prim resolution
      -> reifier construction and geometric grounding
      -> bounded SHACL / geometry / critic checks and LLM repair
      -> deterministic fallback on some failures
      -> attempted Neo4j synchronization
      -> returned spec and telemetry

Important semantics:

- Generation can return a spec after fallback without proving the final candidate passed every check (`:225-359`). Treat candidate production, validation and publication as different outcomes.
- Prim-tree loading failure can return the unresolved spec with a warning (`A/prim_path_inference.py:55-65`); runtime conversion asserts that an object reference has a prim path (`S/arena_env_graph_conversion_utils.py:187-188`).
- Natural-language refinement is a separate method with its own checks (`A/environment_generation_agent.py:361-540`). It does not automatically retrieve DCRG history.
- Agent telemetry and inference counters are mutable per-agent state (`A/environment_generation_agent.py:115-130`; `A/inference_backend.py:97-130`). Use a fresh agent per generation job or explicit, tested per-job counter deltas; do not share one mutable agent across browser requests.
- Existing output is final telemetry and trace strings, not a durable structured stage-event stream. Progress stages require instrumentation at actual execution boundaries. Do not invent percentage-complete estimates.

### 2.3 Validation labels currently overstate what was checked

- Generation calls `VisualSceneCritic.evaluate_scene_spec(spec)` without images (`A/environment_generation_agent.py:252-255`). The cloud/local VLM paths require `rendered_images` (`A/visual_critic.py:95-125`). This path therefore does not establish visual inspection by a VLM.
- `PhysXPreflightCritic` checks initial heights against nominal surfaces, rather than running PhysX (`A/visual_critic.py:322-354`). Its name must not become a "physics verified" badge.
- Visual advisory fallback returns `conforms=True` (`A/visual_critic.py:302-318`). A UI needs an explicit advisory/unavailable state, not just that boolean.
- Editor schema validation, agent-ready task checks, SHACL, heuristic geometry, runtime placement checks, zero-action preview and trained-policy success are different evidence levels.

Proposed check record: check name, candidate revision, method, status (`passed`, `failed`, `skipped`, `unavailable`, `advisory`), actual inputs/artifacts, diagnostics, and implementation/config identity where available. A later real simulation result does not retroactively prove an earlier heuristic correct.

### 2.4 Authored coordinates are not necessarily realized placements

`S/arena_env_graph_conversion_utils.py:171-184` applies an object's explicit initial pose only when it is anchored or has no non-anchor relations. Relation-controlled objects can be positioned again by the runtime placement solver. Relation arguments are filtered by constructor signature; some surface relations add randomization (`:210-246`).

The current preview (`E/review_gui/simapp/sim_preview.py:131-219`) builds the environment, solves relations, runs `ZeroActionPolicy`, and returns first/last viewport images. It is neither a trained-policy evaluation nor a continuous browser video stream.

The UI must distinguish:

- authored initial pose;
- anchor versus solver-controlled placement;
- declared relation parameters versus applied parameters;
- realized pose after build/reset (new capture adapter required);
- preview result versus policy task result.

Do not silently change solver semantics during UI migration. Report mismatches first and fix them as separately reviewed backend changes if necessary.

### 2.5 Source YAML versus resolved specification

The file loader resolves one level of relative `external_yaml` and rejects overlapping top-level keys (`S/arena_env_graph_yaml_loader.py:16-60`). The Streamlit editor parses text directly with `yaml.safe_load` and `from_dict` (`E/review_gui/editor_panel.py:33-53`). These are not equivalent entrypoints.

A document record must retain entry-file context, included source documents and their digests, raw YAML, and normalized/resolved model. Implement a shared text-plus-source-context loader rather than maintaining a browser-only merge algorithm. Preserve include sources on ordinary save; make flatten/export a separate explicit operation. Display normalization or unsupported-field loss instead of silently discarding source content.

### 2.6 Graph-RAG and graph inspection

`A/graph_rag.py:29-95,151-197` prefers evaluated priors using robot/fixture keyword filters, then falls back to structurally converged precedents. It keeps the selected run's rate and episode count together, but its returned projection lacks that evaluation ID and exact policy identity (`:123-137`). It is not exact-policy or task-contract-qualified retrieval.

Consequences:

- Show measured versus unevaluated precedent, sample size, selection filters, and retrieval unavailable versus no matches.
- Extend the retrieval result with selected evaluation ID, available policy/artifact identity, and a structured retrieval outcome. Do not call a second query later and imply it reproduces the priors originally consumed.
- Persist the exact retrieved payload/context with the generation job. If selection is exposed before generation, generation must consume that selected snapshot instead of silently retrieving again.
- Keep authoring graph, persisted experience graph, numerical factor graph, and experiment state-machine views separate.

The real local B1 source has explicit reifiers (`generated_envs/droid_tomato_soup_to_blue_bin/latest/droid_tomato_soup_to_blue_bin.yaml:84`); B4's inspected source contains ordinary relations and no reifier section (`generated_envs/droid_spam_can_to_grey_bin/latest/droid_spam_can_to_grey_bin.yaml:62-97`). Their internal names also differ from directory family names (`:6` in both files). These are useful integration fixtures, not immutable baseline selections: resolve and hash the chosen files before tests.

Display only persisted relationships in the database view. A synthetic visualization node must be explicitly labeled as derived. Inferred DCRG support reifiers carry `inferred_from_task`; do not present them as original authored assertions. Describe the stored explicit reification projection rather than promising native RDF-star storage.

### 2.7 Versioning, publication and evaluation identity

- Flat export and numbered versions coexist. `EnvironmentVersionManager` has hardcoded default roots, allocates latest-plus-one without a lock, and updates files/ledger/latest separately (`A/version_manager.py:54-86,123-169,224-246`).
- CLI family name and internal spec name can differ (`E/environment_generation_runner.py:300-324`). Valid CLI output goes through the version manager, not the advertised flat `--out_dir` path.
- Generation itself already writes to Neo4j (`A/environment_generation_agent.py:351-357`), before the GUI's explicit save. CLI may sync again.
- Legacy graph synchronization merges by spec name and defaults missing convergence telemetry to true (`A/lpg_neo4j_sync.py:74-108`). Same-name mutation is not an immutable revision.
- Ordinary evaluation can identify a scene from the YAML filename rather than its internal name (`isaaclab_arena/evaluation/policy_runner.py:572-597`).
- Legacy lineage stores one `evaluation` entry per version and replaces it on the next write (`A/version_manager.py:252-280`). It is not a complete run inventory.

Do not repair historical records speculatively. Index them with source and linkage confidence. New jobs must freeze both canonical model digest and raw source/config hashes, keep source family/internal name/graph identity separate, and assign independent run IDs.

### 2.8 DCRG and legacy healing are not the same operation

DCRG already has durable state, immutable snapshots, directory locking, exact resume contracts, evidence receipts and pending graph-sync events (`A/dcrg/loop.py:139-243,329-347`). A started evaluation without its receipt is indeterminate; automatic replay is prohibited.

The shipped CLI is bounded: one atomic pick/place task, known unrotated support geometry, target XY changes, pinned policy and hand frame. Its rollout adapter uses GR00T remote closed-loop policy, one environment and explicit seeds (`E/dcrg_runner.py:38-110`; `A/dcrg/evaluation.py:49-98`). Do not advertise it as a generic optimizer for every task or policy.

Legacy `auto_heal` diagnoses and creates patched files/another version without matched reevaluation (`E/environment_generation_runner.py:423-582`). It must be labeled "propose legacy repair", not "accepted improvement". Do not expose its global-most-recent-run inference as a safe UI default.

Controller trials change the controller/policy identity while keeping the scene fixed; they are not scene proposals (`docs/pages/concepts/dcrg.rst:105-128`). Initially expose these as read-only evidence.

## 3. Proposed architecture and ownership

    TanStack frontend
      read-only queries / explicit mutations / local drafts
                         |
                  Python HTTP adapter
                         |
       framework-neutral workbench application services
          |                    |                    |
      file/graph reads    generation process    job supervisor
                              |                    |
                       existing agent         existing SimApp RPC
                                              OR policy runner CLI
                                              OR DCRG CLI

Proposed new locations (none implemented by this plan):

- `web/arena-workbench/`: frontend manifest, routes, feature components, API client and tests. No existing JavaScript application manifest was found in the inspected first-party checkout.
- `docker/workbench/`: frontend Dockerfile, production/development proxy configurations, and frontend-only Compose definitions. These are deployment assets, not the frontend application source.
- `isaaclab_arena/agentic_environment_generation/workbench/`: framework-neutral document/revision, generation-result and evidence read contracts. No Streamlit, FastAPI, or frontend imports here.
- `isaaclab_arena_examples/agentic_environment_generation/web_api/`: HTTP routes, job supervision, artifact serving and adapters to existing example-side SimApp components. It may depend on core services, never the reverse.
- A new example launcher supervises the API/worker lifecycle. Retain `gui_runner.py` unchanged as a rollback path until cutover.

FastAPI/Uvicorn would be new explicit optional web dependencies, not assumed transitive dependencies. Keep them separate from Streamlit extras. The dedicated frontend container serves the SPA and proxies `/api/` to Python; Python does not serve the frontend build. Node is needed for frontend development/build, not the production static server. Keep `/api/` failures out of the SPA fallback. No Docker/workflow/pre-commit configuration edits without separate approval.

### Container placement, networking and proxy contract

**Selected topology: bridge-network frontend, existing host-network Arena, HTTP over a narrowly shared Unix socket.** This is a Linux-local deployment. It avoids changing robotics networking or exposing a backend TCP listener simply to connect the UI.

The inspected `docker/run_docker.sh:153` and `docker/docker-compose.sim.yml:76` put Arena on the host network. The latter also puts GR00T on the host network and binds its server to loopback (`:13,38-39`). A bridge container's `localhost` is not that host namespace. Docker service DNS or `host.docker.internal` does not make a host-loopback-only API reachable. Do not publish an API on `0.0.0.0` as a workaround, and do not migrate Arena/GR00T networking during this UI change.

    Browser: http://127.0.0.1:3000
        |
        | sole new published TCP port: 127.0.0.1:3000 -> frontend:3000
        v
    Dedicated frontend container (per-clone Docker bridge network)
        Nginx: serves SPA; /api/ proxy; no robotics dependencies
        |
        | HTTP + SSE over /run/arena-api/api.sock
        | narrowly shared directory, read-only in frontend
        v
    Existing clone's Arena container (host networking unchanged)
        Uvicorn API: Unix socket only, no TCP API listener
        job supervisor -> generation / SimApp / policy-runner workers
        |
        +-- existing operator-managed GR00T and Neo4j endpoints

Port and exposure contract:

| Service | Bind inside its container | Host exposure |
| --- | --- | --- |
| Frontend Nginx, dev and production | `0.0.0.0:3000` on a bridge network | `127.0.0.1:${WORKBENCH_HTTP_PORT:-3000}:3000`; loopback only. |
| Python API in Arena | Unix socket only, via Uvicorn `--uds` | No TCP port; no API `ports:` declaration. |
| Vite, development target only | `127.0.0.1:5173` inside frontend container | None; Nginx proxies development assets and HMR. |
| SimApp RPC | Existing private Unix socket within Arena | Not mounted into frontend; API/supervisor owns access. |
| Policy and Neo4j services | Existing discovered/configured endpoints | Unchanged; not made reachable through the frontend proxy. |

These are proposed defaults, not a claim the ports are available. Launch must fail clearly on a conflict and accept an explicit per-clone override. Use per-clone Compose project names, without a global `container_name`. The bridge is not declared `internal: true`, because frontend development/package installation may need outbound access; absence of published API ports is not a claim of complete network isolation. Remote use is through an explicit SSH tunnel to the loopback frontend; direct LAN binding and multi-user authentication are out of scope.

Unix socket and storage contract:

- Discover the clone's existing Arena container and the actual host source mounted at `/eval`; nested editor-container paths are not necessarily host paths. Do not infer the source from `$HOME` or use the first container matching an image. If `/eval` is absent or its filesystem cannot support sockets and SQLite locking, fail the preflight and request an approved local mount; do not silently create a second simulator.
- Use a short, configured per-clone directory such as `/eval/.wb/<clone_id>/ipc/` for `api.sock`, and a separate `/eval/.wb/<clone_id>/state/` for the journal. Validate the Unix socket path length before launch. `<clone_id>` is a stable identifier derived from the canonical host clone path, not an environment's mutable name.
- Mount only the IPC directory's corresponding host path into the frontend at `/run/arena-api:ro`. Do not mount `/eval` as a whole, the state database, simulator socket, model/data/cache directories, the full repository, or `/var/run/docker.sock`. Artifacts cross the authenticated API, never a broad frontend filesystem mount.
- Run both application sides non-root. Set IPC directory permissions to `0750`, socket permissions to `0660`, and grant the frontend process the socket's numeric group through supplementary group configuration. Do not grant world access. Keep the state directory owner-only. Test effective permissions with the actual API and Nginx users; a read-only directory mount permits connecting to an appropriately permissioned Unix socket but not replacing it.
- Bind-mount the directory rather than the socket inode so API restart can replace the socket. Create the IPC directory before starting Compose, even if the API is unavailable. Acquire the per-clone launcher lock and prove no live server owns a stale socket before unlinking it; never delete another clone's socket. The frontend can show a disconnected shell while the API starts or restarts.
- Check existing host-shared GPU lease storage separately from per-clone job storage. It must be common to cooperating workbenches on that GPU; placing the device lock only inside a clone directory would not serialize clones.

Proxy and build contract:

- Use Nginx in the frontend container in both modes, with a Unix-socket upstream to the API. Preserve the `/api/` prefix and query string; explicitly handle `/api` rather than returning SPA HTML. API failures stay API errors. Permit only configured upstreams, not browser-supplied URLs or shell commands.
- Production: a multi-stage image builds `web/arena-workbench/` with `npm ci` from its committed lockfile, then copies the build into an unprivileged Nginx runtime. Pin supported Node/Nginx versions or digests during implementation. The production image contains neither Node build tools nor Python/CUDA/submodules.
- Development: an explicit image target runs Nginx and Vite under a small signal-forwarding process supervisor. Mount only `web/arena-workbench/` for editing, with a container-owned dependency volume; do not mix host `node_modules` into it. Nginx proxies the browser's HMR WebSocket to internal Vite and `/api/` to the same Unix socket. Only port 3000 is published. The browser never needs port 5173 or Docker service names.
- Restrict SPA fallback to frontend routes and preserve API/artifact responses. Disable buffering and compression for SSE, forward reconnect headers, and use the heartbeat/timeouts specified below. Use body-size limits for YAML submissions and allowlisted artifact IDs with correct content types; implement range reads for recorded video when exposed.
- Strip untrusted forwarded headers and set the intended original Host/protocol at the proxy; configure the API's allowed browser origin explicitly. With a Unix upstream the peer address may be absent, so do not base session authorization on peer IP or trust arbitrary forwarded headers. Same-origin cookies and CSRF checks apply to commands regardless of transport.

Proposed deployment files (to create only at implementation approval):

    web/arena-workbench/                 application source, package.json, lockfile, tests
    docker/workbench/Dockerfile.frontend multi-stage production and development targets
    docker/workbench/Dockerfile.frontend.dockerignore
                                        allowlist frontend/config build inputs only
    docker/workbench/nginx.prod.conf     static serving and Unix API/SSE proxy
    docker/workbench/nginx.dev.conf      Vite/HMR and Unix API/SSE proxy
    docker/workbench/compose.yaml        frontend-only service; no duplicate Arena/GR00T/Neo4j
    docker/workbench/compose.dev.yaml    explicit development override
    docker/workbench/run_workbench.sh    host-side discovery, preflight and lifecycle commands

Use repository root as the build context with the Dockerfile-specific ignore file excluding everything except the frontend and required deployment assets; never send submodules, datasets, credentials or `.git` to the frontend build. Keep React routes/components out of `docker/`: changing a web component must not imply changing simulator infrastructure. Host-side launch tooling may use Docker to start the frontend and execute the Python launcher in the discovered Arena container; neither the web server nor Python HTTP handlers may use Docker's socket or accept arbitrary execution commands. API shutdown must stop only workbench-owned processes and preserve durable results.

The separate-container boundary is selected. A host-network frontend plus loopback API was considered but is not an automatically selected fallback: it would expose host-loopback services to the frontend and add another port conflict. If the Unix-socket preflight fails, stop with the specific mount/permission problem instead of weakening isolation silently.

### Process boundaries

- Run Python package operations inside the discovered simulator clone container, non-root, using its supported interpreter. Do not copy Arena into a generic Python API environment and assume imports work.
- Keep HTTP lifecycle independent of SimulationApp initialization. Catalogue/validation/generation operations may import registry/USD dependencies, so characterize them in their worker process rather than importing all Arena code at HTTP startup.
- Reuse the current long-lived SimApp server for thumbnails and zero-action previews. It services one connection sequentially (`E/review_gui/simapp/server.py:79-120`); disconnect after a completed operation. A per-client mutex alone does not provide global scheduling across browser tabs.
- Policy evaluation stays in an isolated policy-runner subprocess; do not run it inside the preview SimApp.
- Suspend/release the preview process before an evaluation when sharing a GPU. Acquire an explicit workbench resource lease. It does not magically govern external manual jobs; detect/report conflicting resource use rather than killing operator-owned processes.
- Start with one API/supervisor instance and a local SQLite job/event journal in a configured persistent host-mounted workbench state directory, not Redis/Celery/Kubernetes. Run long operations in worker processes, never blocking the HTTP event loop. Commit job transitions and their events in the same transaction. Keep large artifacts outside the database. Reuse DCRG's own state for its internals instead of creating a second candidate-acceptance state machine.
- Queue cancellation can be immediate. Active simulation cancellation needs process-group cleanup, interrupted manifests and worker recovery tests before a button is enabled. Losing an HTTP request is not a cancellation receipt.

## 4. Data contracts before endpoint proliferation

Define and test these records first. Proposed names below are API concepts, not existing Python symbols.

1. `SourceDocument`: allowlisted workspace document ID, original text, include source IDs, content hashes and source context.
2. `Revision`: original family, internal spec name, parent revision, canonical resolved-spec digest, source hashes, normalized spec, check reports. An unsaved draft is not a published graph.
3. `GenerationAttempt`: job ID, provider/model profile, prompt/base revision, exact prior snapshot, candidate/repair snapshots, telemetry, validation outcomes, persistence outcomes.
4. `PreviewRun`: exact revision/runtime settings, worker status, returned artifact IDs, and realized-placement data when captured.
5. `EvaluationRunView`: original record namespace/ID, linked revision or explicit unknown link, actual policy identity or unknown, config hash, seed/episode identities, raw metrics/predicates, integrity issues and artifact references.
6. `ExperimentView`: DCRG run directory identity, frozen contract, accepted spec hash, proposals, separate decisions, evidence receipts and graph-sync states.

Keep raw YAML byte hashes and canonical model hashes as distinct fields. Do not substitute one for the other. Treat legacy numbered versions as aliases to inspected artifacts, not canonical identities. DCRG graph registration requires a support target; do not use it as a universal revision API for arbitrary tasks.

Minimal HTTP groups, added only when their slice ships:

- capability/health and catalogue/schema reads;
- document/revision inspection, validation and explicit snapshot creation;
- generation/refinement submissions and job/artifact reads;
- graph/experience/evaluation reads;
- preview, evaluation and supported DCRG submissions.

Mutations accept explicit frozen inputs and an idempotency key. A repeated request returns the existing job, not another paid generation or GPU run. GETs and router preloaders must never launch generation, simulation, publication or graph repair.

### Persistence ownership change

Before exposing generation mutations, add an explicit backward-compatible control separating candidate generation from legacy automatic graph publication. Preserve CLI behavior until its adapter deliberately changes. The new workbench owns snapshot then publication, with separate statuses and exact graph read-back. Do not hide a graph write behind draft generation.

Use the existing version manager through a locked/atomic snapshot boundary; configure roots explicitly and harden path containment. Preserve existing layouts for downstream tools. Introduce an append-only run index without rewriting historical evaluation receipts. Publication failure must be retryable without calling the LLM or rerunning simulation.

### TanStack-specific state rules

- Router owns selected scenario/revision/run, tab and filters in validated URL parameters.
- Query owns immutable snapshots and server job/evidence state. Query keys include revision/run/namespace/filter identities.
- Local editor state owns unsaved YAML and selection; a refetch must not overwrite it. Saves use expected revision/content hash and return conflicts.
- Graph layout is presentation state. Dragging a node changes layout only until typed scene mutation semantics are separately designed and validated.
- Tune Query stale times/refetch behavior. All costly actions are explicit mutations, with idempotency and intentional retry rules. SSE is the primary live transport; status polling is a bounded degraded-mode fallback only. Refreshing a tab must not repeat a run.
- Generate TypeScript request/response types from the API contract, but retain server-side registry, include, task and semantic validation. Generic JSON Schema forms cannot replace dynamic relation/task parameter semantics.

### Live transport: HTTP commands and SSE events

Use HTTP for commands and snapshots, and Server-Sent Events for Python-to-browser progress. Do not add an application WebSocket protocol in the first release: there is no current interactive control or live-video requirement. Vite's development HMR WebSocket is a separate tooling connection, not a simulation channel. A future teleoperation/video feature needs its own protocol and safety review.

Proposed API contract (not existing endpoints):

| Operation | Endpoint | Semantics |
| --- | --- | --- |
| Establish/recover browser session | `POST /api/sessions`, `GET /api/session` | Issue/validate an opaque cookie; allocate no agent or simulator. |
| Inspect workspace | `GET /api/workspaces/{workspace_id}` | Return permitted roots as document IDs, revisions and job summaries, never credentials. |
| Submit work | `POST /api/jobs` | Explicit job kind, workspace/revision or draft snapshot, frozen options, idempotency key; return `202` and job ID after durable acceptance. |
| Read job | `GET /api/jobs/{job_id}` | Authoritative status, stage, result/artifact references and event cursor. |
| Observe operator jobs | `GET /api/events?after={cursor}` | Multiplex permitted workspace/job events over one stream, not one stream per job. |
| Cancel work | `POST /api/jobs/{job_id}/cancel` | Record a cancellation request; report cancellation only after worker acknowledgment/cleanup. |
| Read artifact | `GET /api/artifacts/{artifact_id}` | Authorized, allowlisted file lookup; no arbitrary filesystem paths. |
| End browser session | `DELETE /api/session` | Revoke session and streams; does not cancel jobs or delete evidence. |

Events carry `schema_version`, monotonically increasing journal event ID, `workspace_id`, `job_id`, revision/draft hash, timestamp, kind and a bounded payload. Emit actual `queued`, `started`, `stage_changed`, diagnostic and terminal-result events; do not invent stage percentages. Persist each durable event before broadcasting it. Diagnostics exclude keys, connection credentials and unbounded model output. Raw logs are paginated artifacts rather than an unlimited SSE buffer.

SSE contract:

- Use named events, SSE `id`, `Content-Type: text/event-stream`, `Cache-Control: no-cache`, and `X-Accel-Buffering: no`. Configure the proxy with response buffering/cache disabled for streams, HTTP/1.1 upstream, a 75-second read timeout, and a 15-second server heartbeat. These are configured defaults, not measured performance claims.
- Return workspace/job snapshots with a journal event cursor from one consistent database read, then subscribe after that cursor. Honor `Last-Event-ID` on automatic reconnection; use `after` for a newly created stream. Replay is at-least-once: deduplicate by event ID and never let an older event overwrite newer job state. When another tab joins an existing stream, attach its event buffer before fetching its snapshot, then apply buffered events newer than the snapshot cursor.
- Keep durable stage/state events for at least seven days and never prune those needed by active jobs. If a cursor predates retention, send `resync_required`; the client closes the stream, fetches a fresh snapshot/cursor, and reconnects. Do not silently omit the gap. Terminal results/evidence follow separate retention and are not deleted with the event window.
- Use one shared connection per browser profile/origin across tabs through a SharedWorker and its MessagePorts. On browsers without SharedWorker support, use the bounded polling fallback rather than adding a second leader-election system. The stream multiplexes this local operator's authorized workspace/job events. Never create unbounded per-tab/per-job streams: HTTP/1.1 browser connection limits also affect API responsiveness.
- Slow subscribers have bounded buffers. Disconnect a lagging subscriber and let it replay; never block generation or simulation on a browser consuming events. A disconnect cancels only the streaming subscription.
- After repeated stream failures, show an explicit disconnected/degraded indicator and read active job status every five seconds while retrying SSE with backoff. Stop fallback polling when SSE recovers or all watched jobs are terminal; ordinary navigation/refocus may still fetch a snapshot. No mutation is retried just because observation failed.
- SSE handlers update/invalidate exact TanStack Query job/revision keys. Keep YAML drafts separate from server cache. Fetch images/video via artifact URLs; SSE carries references, not binary frames.

### Sessions, workspaces, jobs and simulation ownership

These are separate identities. A session is not a container, Python interpreter, generation agent, or GPU lease.

| Identity | Owner and persistence | Lifecycle |
| --- | --- | --- |
| Operator | Local single-operator deployment | Trust boundary; this release is not multi-user isolation. |
| Browser session | Backend opaque cookie record in SQLite | Shared by tabs on the same origin; survives refresh/API restart until expiry or revocation. |
| Workspace | Backend durable record | Scenario/revision context and configured storage roots; outlives browser sessions. |
| Draft | Browser IndexedDB, keyed by workspace/base revision and tab draft ID | Saved locally while typing; not a canonical revision. Surface recovery/conflict options instead of silently merging tabs. |
| Job | Backend durable journal and immutable input snapshot | One requested operation; outlives HTTP/SSE connections and session expiry. |
| Simulation worker | Backend-supervised process | Started on demand; reused for previews, not created for each session. |
| GPU lease | Supervisor lock plus journal owner/job record | Belongs to the executing job, never a browser tab or session. |

Session lifecycle and access:

1. On first visit, obtain a session through the same-origin API. Use an HttpOnly, SameSite=Strict, path-scoped cookie with a clone/port-specific name; localhost cookies are not isolated by port. Use Secure when HTTPS is enabled. Validate exact allowed Host/Origin and a per-session CSRF token for mutations; no wildcard CORS, URL tokens, or provider keys in browser storage. Session creation must itself reject cross-origin requests.
2. Default expiry is 24 hours without explicit user activity, with a seven-day absolute lifetime. Background heartbeats, SSE and status polling do not extend it. Revalidate streams on expiry/revocation and close them; the client establishes a new session when the operator returns.
3. Reopening creates/reuses a session and reads existing workspace jobs. In this single-operator scope, a replacement session can access that operator's prior jobs; `created_by_session_id` is audit metadata, not the sole ownership check. These rules are not sufficient authentication for a shared machine or network deployment. LAN exposure requires authentication/TLS review first.
4. Submitted jobs retain a frozen YAML/include snapshot or saved revision and options, independently of later edits. The idempotency lookup is scoped to operator/workspace/key, not the expiring session; the same key with different inputs returns a conflict. Keep the key/result binding for the job's retained lifetime.
5. Closing a tab, logging out or losing the network does not cancel queued/running work. Cancellation is a separate explicit action. Expired sessions may be pruned without deleting jobs, snapshots, artifacts or graph evidence. Browser-local drafts can be lost when browser storage is cleared; do not claim backend durability for them.

Job and worker lifecycle:

- States: `queued`, `running`, `cancel_requested`, `succeeded`, `failed`, `cancelled`, `indeterminate`. A worker records start/receipt identities around external execution. A success transition requires the adapter's verified completion receipt, not process launch or an HTTP `200`.
- Keep job outcome separate from research outcome: a completed evaluation may have zero task successes; graph publication may be pending even when files exist. DCRG retains its own acceptance/rejection and resume contract.
- One supervisor per clone/state directory holds an exclusive OS lock. Before any GPU work, it acquires the configured device lease and serializes all workbench previews/evaluations across sessions. Use a host-shared lease directory keyed by GPU UUID so cooperating clones share the lock. Detect/report unrelated operator workloads; never claim the lease controls external processes or kill them.
- Start SimApp lazily for thumbnails/preview, keeping the HTTP API usable without it. Reuse it sequentially, reset/close the prior environment between jobs, and label results with the exact input hash. Release an idle preview worker after five minutes; release it before an exclusive evaluation. Retained warm GPU memory remains leased, not available for another job.
- Cancelling a queued job removes it atomically before dispatch. Active cancellation is enabled only for adapters with verified process-group shutdown and receipt handling. Until then, return an explicit unsupported result rather than a cosmetic cancelled badge. Do not release a GPU lease until the worker has actually stopped.
- API/container restart is not a browser reconnect. Recover the journal and inspect worker identity/receipts before dispatch; queued jobs remain paused until operator resume after an unclean restart. Work that started without a verifiable outcome becomes `indeterminate`, not automatically replayed. A stale database lease is not proof a process exited: verify identity, including process start identity rather than PID alone. DCRG evidence recovery remains authoritative.

## 5. Implementation slices with acceptance gates

Implement in order: 0 -> A -> B -> C -> D. Slice E requires a separate runtime budget/authorization. Each slice must have a runnable demonstration and its regression tests; static scaffolding is not completion. Reuse the source audit in section 2 rather than rebuilding the research subsystem.

### Slice 0: container-to-Python vertical slice

After approval for the new `docker/workbench/` files, create the frontend scaffold/image/proxy, minimal Python API and SQLite session/job/event infrastructure. Add an explicitly test-only bounded diagnostic worker to exercise progress without invoking an LLM, simulator or database. Never present its events as real robotics results. Establish networking, same-origin access, reconnection and ownership before building feature panels.

Acceptance:

- Build the frontend image from its declared lockfile, run it non-root, and load a deep-linked route in a real browser. Verify static files, `/api/health`, API errors and SSE through the actual proxy. The shell remains available with the API down and shows a disconnected state.
- Verify the selected listener bindings and absence of unintended published ports; check both development and production modes. Confirm no Docker socket, model directory, repository-wide mount or provider credentials enter the frontend container/image.
- Confirm Arena/GR00T network modes remain unchanged, only the loopback frontend port is published, and no API TCP socket exists. Verify IPC connection as the real frontend UID/GID, refusal for an unrelated non-root UID, inability to modify the read-only IPC directory, socket replacement after API restart, and two clones with distinct ports/socket paths. Verify the new UI is not reachable through the host's LAN address; do not infer this from a healthcheck alone.
- Observe real diagnostic-worker stage events before the worker finishes, including across a heartbeat interval. Test proxy restart, forced SSE disconnect, duplicate replay, expired event cursor, slow consumer and fallback polling. Each returns to authoritative job state without repeating the operation.
- Open multiple tabs, submit two jobs and refresh/reopen. Verify stable job identities, one shared stream where supported, no browser-connection starvation, no lost submitted inputs and no simulator startup.
- Test session expiry/revocation, cross-origin mutation rejection, clone-specific cookies, idempotency conflicts, old-session retries from a replacement session and artifact-path traversal rejection.
- Restart the API while the diagnostic worker runs; verify recovery/indeterminate semantics and that interrupted jobs are not blindly replayed. Fault-inject between job-state and event writes to verify transactional consistency.

### Slice A: read-only scenario and evidence workspace

Deliver a runnable TanStack shell plus Python read adapters. Open existing files from configured roots; distinguish family/internal name/version, show YAML, assets, ordinary relations, reifiers, tasks, historical runs and artifacts. Use the existing graph read helpers where adequate; add scoped read projections where provenance fields are missing. Do not query the whole graph into the browser.

Acceptance:

- B1 and B4 source fixtures render their different reifier structures without invented statements.
- Raw source and internal name remain visible; `latest` is resolved to a specific inspected file/revision.
- Missing graph links and missing episode metrics display as unknown, not zero or inferred success.
- File views work with Neo4j or Isaac Sim unavailable; no LLM initialization on page load.
- Repeated representations of one raw evaluation are not counted as additional episodes.

### Slice B: deterministic authoring and revision storage

Extract schema validation and save orchestration from Streamlit. Support raw YAML plus include context, catalogue-backed inspection, explicit validation, draft/saved diff and snapshot creation. Add atomic/locked version allocation and explicit roots; do not silently change generated policy templates into verified configurations.

Acceptance:

- Invalid YAML and unresolved references remain editable and retain diagnostics.
- An include-based RoboLab task loads consistently with the existing file loader; no implicit flattening on save.
- Two tabs saving the same base detect a conflict rather than overwriting each other.
- Restart preserves saved snapshots; original history remains unchanged.
- Manual schema validity is not displayed as SHACL/runtime/policy verification.
- Browser refresh recovers a local draft without overwriting it from a server refetch; two tabs keep distinct drafts and detect conflicting saves.

### Slice C: observable generation and natural-language refinement

Wrap the existing agent in a dedicated job. Add optional structured events at real stage boundaries and capture final traces regardless of success. Persist selected priors and candidate diffs. Isolate per-job telemetry. Separate generation from publication using the compatibility control above.

Acceptance:

- Generated candidate, fallback candidate, invalid candidate and graph-sync failure are distinguishable.
- Graph memory outage differs from an empty retrieval.
- Priors displayed are exactly those consumed by that job; measured rates retain their deciding run and denominator where known.
- Publication retry does not regenerate the spec.
- One real bounded generation is exercised after mock/contract tests; no claim of physical success follows from it.
- Progress comes from real agent stage boundaries over SSE. Typing and browsing remain responsive during generation; instrument LLM call counts to verify panel navigation, reconnect and refocus never repeat inference.

### Slice D: truthful simulation preview

Adapt existing SimApp RPC to supervised jobs and artifact IDs. Preserve prim tree, thumbnails/AABBs, unary constraints, task rows and first/last frames. Add effective-placement instrumentation so explicit versus solver-controlled poses are inspectable. Do not promise live streaming.

Acceptance:

- Run a real preview on a pinned small fixture; verify frames exist and correspond to the submitted revision.
- A relation-controlled object is labeled correctly; observed realized pose is distinguished from authored pose.
- Concurrent tabs queue rather than compete for the socket; an old preview never replaces a newer revision's result.
- SimApp failure leaves editing available and can recover without restarting the whole web UI.
- Preview is labeled zero-action, never a trained-policy success score.
- Verify one simulator owner across two sessions and cooperating clones on the same GPU. Test idle worker release, supported cancellation and worker crash recovery without terminating operator-owned policy services.

### Slice E: evaluation, then bounded DCRG controls

First launch ordinary evaluation from a frozen revision and approved policy/runtime profile. Fix the new-run graph identity join explicitly; do not infer it from filenames. Capture actual server identity verification where available, otherwise block certification and show the limitation.

Then expose supported DCRG contracts using the existing CLI/controller. Read its state and receipts directly. Keep legacy repair and controller-trial evidence separate. Do not add generic automatic history routing or controller search as part of this slice.

Acceptance:

- Real bounded rollout completes with exact episode accounting, source hashes and artifact links; task failure is a valid test outcome.
- File outcome, graph sync, evidence validity, candidate decision and task success have separate statuses.
- Browser reconnect never launches a duplicate run.
- Indeterminate DCRG execution requires evidence recovery; changed resume contract is rejected.
- Out-of-contract candidate edits are rejected before GPU execution.
- Per-seed, aggregate and legacy representations are not pooled as independent trials.

Streamlit retirement requires completion of Slices B-D parity gates, not completion of every future research feature. Slice E is separately gated because it authorizes expensive side effects.

## 6. Verification and remaining decisions

Existing relevant tests include:

- `isaaclab_arena_examples/tests/test_review_gui.py`
- `isaaclab_arena/tests/test_environment_generation_agent.py`
- `isaaclab_arena/tests/test_spec_inference.py`
- `isaaclab_arena/tests/test_arena_env_graph_yaml_loader.py`
- `isaaclab_arena/tests/test_arena_env_graph_conversion.py`
- `isaaclab_arena/tests/test_visual_and_graph_rag.py`
- `isaaclab_arena/tests/test_dcrg_loop.py`
- `isaaclab_arena/tests/test_dcrg_graph.py`

Add frontend unit tests, API contract tests and browser end-to-end tests. Existing mocked tests are not proof of live simulation parity. Run Arena/package tests in the discovered simulator container; lint on the host. Validate real generation, preview and evaluation only under explicit bounded runtime budgets during implementation.

Decisions resolved in this revision: a dedicated frontend container, React/Vite with Router/Query, frontend-owned same-origin proxy, SSE rather than application WebSockets, durable jobs independent of expiring sessions, and a first release through authoring/generation/preview parity.

Implementation entry checks, not open architecture choices:

1. Obtain approval before creating/changing Docker assets, shared workflows or pre-commit configuration. This revision edits documentation only.
2. Discover the actual clone/runtime mount, non-root UID/GID, configured document/output/state roots, available listener ports and operator-managed model/runtime profiles. Refuse conflicts rather than choosing another clone or silently changing endpoints.
3. Before Slice C publication, document and test the identity mapping for non-DCRG arbitrary tasks. Preserve existing graph records and avoid silently generalizing support-specific DCRG registration. Generation may run with publication explicitly unavailable until this gate passes; do not claim parity with graph publication yet.
4. Before real Slice C/D/E runs, agree a bounded generation/preview/evaluation budget. Require live receipts and browser evidence for their acceptance tests, not mocks alone.

Documentation deliverables during implementation: one architecture page at `docs/pages/concepts/agentic_workbench.rst` and one launch/recovery runbook at `docs/pages/example_workflows/agentic_env_gen/workbench.rst`, linked into existing navigation. Document both container startup orders, configuration variables, API/session/event contracts, recovery, and the Streamlit rollback path. This plan remains the implementation checklist, not a second conflicting runbook.

No calendar estimate is justified until a runtime baseline and API/import boundary are exercised. The riskiest work is publication identity, loader/registry compatibility, and simulator ownership—not React components.

## 7. Framework references consulted

- TanStack Start overview: https://tanstack.com/start/latest/docs/framework/react/overview
- Start SPA mode and static shell behavior: https://tanstack.com/start/latest/docs/framework/react/guide/spa-mode
- Router integration with external data loading: https://tanstack.com/router/latest/docs/framework/react/guide/external-data-loading
- Query stale/refetch/retry defaults: https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults
- Docker host-network behavior and ignored port publishing: https://docs.docker.com/engine/network/drivers/host/
- SSE framing, reconnects and browser connection limits: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
- Nginx proxy buffering and streaming directives: https://nginx.org/en/docs/http/ngx_http_proxy_module.html
- Uvicorn Unix-socket binding and reverse-proxy deployment: https://uvicorn.dev/settings/ and https://uvicorn.dev/deployment/

These establish framework behavior only. Repository source and real runtime tests determine Arena capabilities. Older research notes contain architectural aspirations and stale CLI recipes; they are not substitutes for the call paths cited above.
