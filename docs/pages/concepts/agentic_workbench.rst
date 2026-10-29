Agentic Workbench Architecture
===============================

The workbench separates the browser interface from Arena's Python runtime.
The primary surface is an environment editor with prompt/YAML authoring,
validated graph inspection, immutable revision exports and real snapshots.
Persisted Neo4j query results have a separate view. Sessions, durable jobs and
live events support those workflows; diagnostics are not the main workspace.
Live model generation requires explicit temporary-session or server configuration.
Full policy evaluation remains outside this initial editor release. Streamlit remains
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

Graph explorer preview
-----------------------

``graphRenderer=explorer`` selects the new frontend graph explorer on the editor
and Neo4j routes. The default remains ``legacy`` during visual acceptance.
``GraphHost`` owns the rollout boundary and keeps **Use legacy graph** outside
optional module loading and error boundaries. Switching renderers is local
presentation state, not an API restart, graph write, or job submission.

The implementation is under ``web/arena-workbench/src/graph-explorer/``:

* ``graph-model.ts`` validates unknown projections, preserves literal IDs,
  quarantines malformed identities/endpoints with diagnostics, and provides
  immutable display values and indexed local filtering.
* ``explorer-state.ts`` owns source/revision-aware selection, filters, table
  state, and independent 2D/3D numeric presentation snapshots. Controllers stay
  above validation withholding and raw-query tab switches; visual adapters do
  not stay mounted when hidden.
* ``graph-table.tsx``, ``graph-inspector.tsx`` and ``property-tree.tsx`` provide
  semantic entity tables, endpoint navigation and bounded property inspection.
  Neo4j's raw query-row table remains separate from these graph-entity tables.
* ``graph-2d.tsx`` and lazily loaded ``graph-3d.tsx`` receive fresh property-free
  mutable layout objects. Force coordinates, object endpoints, pins, cameras,
  and graphics resources never become source YAML or cached API graph data.
* ``renderer-contracts.ts`` defines the presentation-only adapter controls.
  Freezing layout retains selection and navigation; stopping renderer animation
  is reserved for hidden/disposed views, not the visible Freeze control.

Authored validation belongs to a session, selected document and frozen source,
not just matching YAML text. Reconnecting with a retained draft withholds its
graph until current-session validation completes against that same frozen source;
it does not silently reload includes or discard draft/prompt edits. Delayed
responses from an obsolete owner cannot restore its graph. Applying a durable
generation result also requires fresh validation before graph display.

Graph coordinates are layout units, not scene meters. Browser WebGL in 3D uses
browser graphics resources but launches no Isaac Sim worker. Keyboard and
click-only pan/zoom/orbit and selected-node coordinate controls supplement drag
gestures. Table remains available when WebGL is unsupported or lost.

Search operates on returned IDs/labels/roles/types. Relationship-only matches
bring their allowed endpoints into the context graph; explicit role/type
exclusions still win. Neighborhoods are loaded neighbors only and never cause
database expansion. **Reveal (clear filters)** explicitly clears visibility
constraints rather than silently overriding them. Returned, valid, visible,
and paginated counts must not be described as database totals.

New role/type categories enter the default unfiltered view on a revision.
Deliberate exclusions survive category disappearance and reappearance, and an
explicit empty selection remains empty. Clear and Reveal reset that intent to
All, including on empty graphs; Reveal keeps the search text as highlighting
while removing visibility constraints. Truncation markers remain inspectable
text but cannot establish relationship identity across revisions.

The standalone force-graph wrappers are pinned to ``1.29.1``, Three.js and its
types to ``0.180.0``, and TanStack Table to ``8.21.3``. The isolated spike found
pointer-control failures with an unconstrained newer Three.js resolution;
retain the tested single-instance dependency closure unless it is revalidated.
Built-in HTML-capable graph labels are disabled; display labels and property
values use text-only application rendering. Server redaction/truncation and
frontend normalization diagnostics remain explicit.

The rollout retains the original SVG implementation until user acceptance.
Implementation evidence and remaining gates are recorded in the repository
plan ``.agents/references/plans/tanstack_graph_explorer.md``; a passing model or
component test does not establish 3D hardware performance or resource cleanup.

Temporary provider credentials
------------------------------

Provider settings are a separate control plane, not environment YAML or durable
job inputs. ``GET /api/model-settings`` exposes public provider/model/source/expiry
metadata; authenticated, CSRF-protected ``PUT`` and ``DELETE`` set or forget a
temporary session credential. Saving settings never invokes the provider. Only
an explicit generation submission authorizes model work.

The browser password field is transient. Secret-bearing requests use the API
client directly rather than React Query mutations, whose retained variables
would otherwise keep a copy of the key. Only public status is query-cached.
There is no key persistence in localStorage, sessionStorage, draft recovery,
URLs, YAML, or browser job records. Provider changes and submission attempts
clear the input; UI errors must not echo request payloads.

The Python API owns a bounded, expiring in-memory credential store. Entries are
scoped to the authenticated browser session and expire after the selected
15/30/60/120 minutes (default 30), capped by the session deadline. They are
removed on access/periodic cleanup, session revocation, or API shutdown. Polling does not extend key
lifetime. Tabs sharing a session share its provider settings; tab closure does
not revoke the server entry. Durable sessions do not imply durable credentials.
The ``ttl_minutes`` setting is a strict allowed integer or explicit JSON ``null``,
enforced server-side. Omission retains the 30-minute default. ``null`` selects
**Never expires**, disabling only the key timer. Such credentials follow explicit
session activity up to the session's absolute deadline; polling does not renew
them. They still clear on session expiry/revocation, Forget, replacement, or API
shutdown and never persist across restart. Public ``key_timer_disabled`` metadata
distinguishes this mode; ``expires_at`` remains the current finite session deadline.
Changing the dropdown does not renew existing credentials; saving again replaces
the credential reference and its deadline. There is no cross-session retention.

Generation binds a non-secret credential reference to the submitting session.
The worker resolves that exact reference before execution; another session cannot
use it, and expiry/replacement cannot silently select another credential or the
server fallback. Recovery of an already-accepted matching submission does not
require its old key to remain valid and does not run it again. Explicitly
discarding an unresolved local retry clears only that tab's recovery record,
after warning that a job may already exist; it never silently rebinds credentials
or cancels accepted work. Raw keys never enter the journal or worker command line. The
resolved configuration crosses a private stdin pipe to the bounded subprocess.
Worker errors and receipts must not expose the key. An already-authorized generation
job may finish all its bounded model calls with the resolved credential: forgetting settings is not cancellation or
provider-side revocation, and requests already sent cannot be retracted.

Browser-entered keys use fixed HTTPS provider endpoints for OpenAI, Gemini,
OpenRouter, and NVIDIA's public API. Custom endpoint entry is intentionally absent:
an arbitrary URL would create credential-exfiltration and SSRF risks. Redirects
must not move authenticated requests to a different destination. Operator-managed
server environment configuration remains a separate trusted deployment choice.
Forgetting a temporary override can restore the server source for new requests;
the public status must make that fallback explicit.

This design limits accidental persistence, cross-session credential use, and
endpoint substitution; it is not a secrets vault or a multi-tenant security
boundary. The frontend proxy handles request bodies in transit. XSS, malicious
browser extensions, debug/network traces, same-user process access, core dumps,
swap, and privileged administrators remain part of the trusted-host threat model.
Python/JavaScript cannot guarantee that all RAM copies are securely erased.
Use restricted provider keys, budget limits, and revocation at the provider.
Consent covers prompts, scene YAML, catalogues, USD context, and retrieved graph
priors used by the selected workflow, not just transport of the API key.
Local loopback HTTP is supported; non-loopback credential entry requires a
configured HTTPS origin and still needs a separate authentication/TLS review.

Prompt-first generation and recovery
------------------------------------

The revised API advertises ``generation_modes`` independently from current model
readiness. New requests explicitly use ``operation=new`` and reject base/document
fields; refinement requires a frozen valid base. An older API without this
capability retains the legacy UI. Deployment and live-model acceptance are
separate from component tests; the P1 path returns drafts, not published research
versions or evaluated policies.

Model and retrieval-read grants freeze separate private configurations and bind
to the durable request and exact attempt generation. They expire after at most
180 seconds, also capped by session/credential deadlines. The journal claims
attempts transactionally. The coordinator rechecks authorization after spawning
the owned worker and records release immediately before private pipe dispatch.
Queued work cannot silently adopt a replacement credential or endpoint.

Graph retrieval requires an explicit server profile. The owned driver is closed
on all paths, and measured, structural, empty, unavailable and not-requested
outcomes remain distinct. The shared ``prior_receipt.py`` validator checks bounded
fields, evidence consistency, canonical consumed context, digest, effective
settings and timing without re-querying. The catalogue digest is frozen at
submission and checked against the actual catalogue before external work.

Protected modern candidate receipts are immutable SQLite records capped at
2 MiB. Parent-side validation precedes acceptance. Restart adoption requires
verified receipt identity and recorded worker cleanup; released work without a
receipt remains indeterminate rather than being replayed. Cancellation preserves
accepted candidates and execution-outcome evidence independently from its local
lifecycle status. Stopping a worker does not establish that a provider did no work.

Blocked, unreleased work supports explicit reauthorization through
``POST /api/editor/generations/{job_id}/reauthorize``. Linked append-only grants
preserve original inputs; indeterminate work cannot use this route. Failed
renewal requests retain their request ID/reference until acceptance or durable
rejection is established. Rejection seals serialize against acceptance, are
capped at 128 per job, and never consume the accepted-generation slot. An
authenticated exact disposition read can recover the proof; missing records,
generic conflicts and commit failures are not rejection proof. Secret screening
precedes persistence or reflection of fresh request fields.

The browser offers explicitly selected controls for blocked jobs discovered in
other tabs, preserves ambiguous requests, and fences dispatch and late responses
by session/request ownership. Correcting a definitively rejected credential
requires separate confirmation and does not itself submit work. Applying a new
or foreign-source candidate detaches includes and revalidates in the current
session.

Managed research preview boundary
----------------------------------

Editor drafts, numbered managed research versions, graph publication and policy
evaluation are distinct states. Generation/Apply and editor Save revision remain
draft operations; explicit Save Research Version commits exact candidate identity,
immutable artifacts and optional immutable parent lineage. It requests neither
publication nor evaluation. Managed publication, retrieval-provider and worker
integration remain unfinished or under review, not a completed P2 deployment.

Operator-supplied ``research_roots`` (Python launcher ``--research-store``) are
opt-in; the empty default is unchanged. ``research_versions`` indicates configured
roots, not verified storage readiness. Discovery GETs never initialize or migrate.
Explicit offline ``research_admin init-store`` follows journal backup/review and
requires the supported current P1 schema. It does not construct a Journal or own
API lifecycle; incompatible schemas fail closed rather than silently migrating.
Managed roots are separate from legacy ``generated_envs`` / ``eval_output``.

The reviewed WAL-sidecar-safe admin preflight requires the documented offline,
trusted-owner Linux/POSIX-VFS scope, not an assumption that SQLite read-only queries
leave sidecars unchanged. Initialization/backup require ``--attest-quiescent`` and
closed connections throughout. A private main-plus-WAL copy preserves authoritative
WAL data. Conflicting locks fail busy without an implicit API stop, but idle rollback
connections may hold no lock. Physical preservation excludes access timestamps;
the runbook is not approval for a live cutover or proof of power-loss durability.

Save and generation recovery bind exact operation IDs across replacement sessions,
including S2, not ``latest`` or guessed family versions. The managed CLI consults
accepted-request identity before fresh server-model preflight; changed current
model settings cannot silently replace accepted work. Its current save has no
parent and publication is explicitly not requested. Legacy CLI behavior is not
changed or certified safe for concurrent managed-store writing.

Private checkpoints include Sessions-derived journal state. Their bounded local
filesystem copying uses a cooperative deadline, not a hard bound on blocked I/O
or proof of power-loss durability. Prepared restore produces only an inactive
database marked ``activation_required``: never activation, graph undo, or automatic
queue replay. Reconciliation and cutover need a separate authorized procedure.
See :doc:`../example_workflows/agentic_env_gen/workbench` for exact operator commands
and the remaining budget/runtime-proof acceptance boundary.

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
