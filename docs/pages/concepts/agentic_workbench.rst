Agentic Workbench Architecture
===============================

The workbench separates the browser interface from Arena's Python runtime.
The primary surface is an environment editor with prompt/YAML authoring,
validated graph inspection, immutable revision exports and real snapshots.
Persisted Neo4j query results have a separate view. Sessions, durable jobs and
live events support those workflows; diagnostics are not the main workspace.
Live model generation requires explicit server configuration, and full policy
evaluation remains outside this initial editor release. Streamlit remains
available while the broader parity gates are completed.

Source ownership
----------------

* ``web/arena-workbench/`` owns React components, TanStack Router/Query,
  browser state, frontend dependencies and tests.
* ``docker/workbench/`` owns frontend image targets, Nginx configuration,
  Compose definitions and host-side lifecycle tooling. It does not contain
  application pages or a second implementation of Arena.
* ``isaaclab_arena/agentic_environment_generation/workbench/`` owns
  framework-neutral persistent application state, bounded include-aware YAML
  loading, frozen document views and source/semantic hashes.
* ``isaaclab_arena_examples/agentic_environment_generation/web_api/`` owns
  HTTP routes, the Unix-socket launcher, worker supervision, the restricted
  read-only query adapter and authenticated artifact serving.

Node, npm/npx and frontend development dependencies belong in the frontend
container. Installed dependencies, build output and caches are not committed.
The production frontend contains static assets and Nginx rather than Node,
Python, CUDA or Isaac Lab submodules.

Deployment boundary
-------------------

The Linux-local deployment uses this boundary::

    browser
      -> loopback frontend port
      -> Nginx in a bridge-network frontend container
      -> HTTP/SSE over a narrowly shared Unix socket
      -> Python API in the existing Arena runtime container
      -> application workers

Arena's existing host networking is retained. Docker service discovery does
not make a host-loopback listener reachable from a bridge-network container.
The API therefore uses a Unix socket rather than broadening its TCP listener.
Only the frontend port is published, on host loopback. The frontend never
receives the Docker socket, simulator RPC socket, model directories or the
whole evaluation directory.

Mount the API socket's containing directory read-only into the frontend.
Matching numeric group permissions permit connections, while the read-only
mount prevents replacement. Mounting the directory rather than an individual
socket inode allows API restarts to replace the socket. State storage remains
in a different, private directory in the runtime's persistent evaluation mount.

Frontend development and production share the API proxy. Development additionally
proxies Vite and its hot-reload WebSocket inside the frontend container. HMR
is not a simulation-control channel. The application protocol uses ordinary
HTTP commands and server-sent events, not application WebSockets.

State and execution
-------------------

A browser session is neither a container nor an agent instance. Sessions use
opaque cookies and explicit CSRF-protected mutations. The local deployment
represents one operator; it does not provide multi-user authentication or
isolation. Do not expose it to a network without an authentication/TLS review.

Workspace records, submitted job inputs and results outlive browser sessions.
An idempotency key belongs to the operator/workspace, not the current session,
so a replacement session can safely recover an ambiguous submission. Reusing
the key with different inputs is a conflict, not another run.

The local SQLite journal commits job state and its corresponding event in one
transaction. Job workers execute outside the HTTP event loop. A completed HTTP
request or a launched subprocess is not proof of successful work. Closing a tab
or losing an event stream does not cancel or restart a job.

Jobs distinguish queued, running, cancellation requested, succeeded, failed,
cancelled and indeterminate outcomes. Cancellation requires actual worker
acknowledgment and cleanup. After an unclean restart, work without verifiable
completion evidence cannot be automatically replayed. Queued work requires
explicit recovery/resume as defined by the launcher and API.

Live event contract
-------------------

SSE carries bounded event records and artifact references rather than binary
images or unbounded logs. Events have a monotonic journal ID. A consistent
snapshot/cursor followed by replay avoids the gap between initial loading and
subscription. Clients deduplicate repeated events and do not apply an older
state over a newer state.

Nginx must not buffer or compress event streams. Server heartbeats keep the
connection active, and reconnects resume from the last observed event ID.
An expired cursor requires a fresh snapshot rather than silent data loss.
Slow consumers cannot block workers. Stream access is rechecked when a
session expires or is revoked.

The browser shares its event connection across tabs where SharedWorker is
supported. Unsupported or disconnected clients use bounded status polling;
observation never repeats a mutation. TanStack Query stores server state,
while unsaved editor drafts remain independent browser state.

Preview catalogue and rendering
--------------------------------

The preview catalogue is separate from the job journal. Authenticated
``GET /api/editor/previews/{canonical_hash}`` reads an existing receipt without
creating a job, starting Isaac Sim, or extending session activity. Camera view,
resolution and per-asset camera overrides are part of the lookup identity.

Receipts bind the canonical scene, normalized options, renderer implementation
revision and asset dependency revision. A configured ``LocalAssetRevisions``
provider can fingerprint trusted complete local dependency bundles. The default
registry does not establish freshness for mutable remote dependencies: these
receipts return ``historical`` with ``unverified_assets`` freshness, not a cache
hit. They can be displayed with a warning, but are never reused to skip a fresh
render. Changed known dependencies, renderer revisions, missing artifacts and
expired receipts invalidate lookup. Historical receipts cannot bypass these
checks, and the browser does not fall back to journal images on a catalogue miss.

The private artifact store publishes authenticated full PNGs and thumbnails of
at most 256 pixels. Default retention is 256 receipts, 512 MiB of published PNGs
and 30 days; raw thumbnail accelerators have a separate budget. Cleanup is a
writer/startup operation, not a GET side effect, and avoids symlinks. Isolated
thumbnail reuse requires a complete local dependency closure plus constructor,
camera and renderer identity; mutable remote paths alone never establish reuse.

Snapshot jobs freeze isometric/front/side/top views, 512/1024 render resolution
and optional per-asset view overrides. Reference prims are rebased from runtime
namespaces into the original USD hierarchy before isolation and camera framing.
Robot thumbnails show the authored USD joint pose, not a simulated configured
joint state. Composed robot-on-stand stages declare their Z-up, meter coordinate
system for standalone viewers. Partial render errors preserve available images
and report node-specific diagnostics and measured stage timings.

Rendering remains explicit by default. Optional automatic previews require
per-view consent, a validated changed scene, a confirmed catalogue miss, a
1.5-second debounce and a 10-second minimum interval. Each enable permits at
most three attempts with one in flight. Ambiguous submissions stop automation;
navigation, document/session changes and reload revoke consent. Historical
receipts do not automatically trigger a render. Cancellation uses the durable
job route and waits for actual worker cleanup.

Simulation and future deployment
--------------------------------

Simulation adapters must keep a separate process and explicit GPU ownership.
A browser session cannot own the GPU. Preview workers are sequential and
must release resources before an exclusive evaluation. External policy
services remain operator-managed. A diagnostic worker never starts Isaac Sim.

This local deployment is not a Kubernetes implementation. Container images,
API contracts and job identities can carry forward; a distributed deployment
would replace the local socket transport, SQLite/single-supervisor ownership
and filesystem leases with network services, shared persistence and scheduler
ownership. Keep those details at deployment/worker boundaries rather than in
React components or scientific algorithms.

See :doc:`../example_workflows/agentic_env_gen/workbench` for the implementation
status, local setup and verification instructions.
