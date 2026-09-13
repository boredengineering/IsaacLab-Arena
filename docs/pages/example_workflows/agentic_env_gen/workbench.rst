Agentic Workbench: Local Development
====================================

Implementation status
---------------------

The main route is now the ArenaEnvGraphSpec live editor: prompt input, YAML
authoring, schema diagnostics, immutable save/export, an interactive authored
graph, asset cards, task/constraint inspection and explicit snapshot rendering.
``/neo4j`` provides read-only Cypher queries with separate table and graph views.
Diagnostics are secondary at ``/developer/diagnostics``.

Generation is connected to the existing agent and accepts a temporary session key
through provider settings or a key in the server process environment. No successful
live model generation has been verified in this deployment. The workbench does not load credential files automatically or publish
generated drafts to Neo4j. Streamlit remains available through :doc:`gui_runner`;
this release is not full parity with every preview/evaluation workflow.

The initial diagnostic job is explicitly an integration test. It exercises
Python subprocess execution and progress reporting without calling an LLM,
starting Isaac Sim or evaluating a policy. A successful diagnostic is not
physical validation or task success.

See :doc:`../../concepts/agentic_workbench` for application ownership,
networking, session/job semantics and future deployment boundaries.

Prerequisites and scope
-----------------------

* Linux Docker Engine and Docker Compose.
* This clone's existing Arena runtime container, with its repository and
  evaluation directory mounts correctly discovered. Do not use an editor
  devcontainer in place of the simulation runtime.
* A non-root runtime identity that can read the installed Isaac Sim stack.
* A local evaluation filesystem supporting Unix sockets and SQLite locking.
* An unused loopback frontend port, default 3000. Different clones require
  distinct ports and state/socket paths.

Node, npm/npx, Vite and frontend test tools are installed in the frontend
container. They are not required on the host or in the Arena runtime.
The API uses the runtime's supported Python interpreter and explicit optional
web dependencies; installed transitive packages are not a dependency contract.

The frontend application source is under ``web/arena-workbench/``. Container
configuration is under ``docker/workbench/``. Keep ``node_modules``, generated
builds, logs and browser-test artifacts out of Git.

Safety and recovery checks
--------------------------

Before starting the API, resolve this clone's actual host mount source, runtime
identity and evaluation mount. Container-local repository paths can differ
from Docker host paths. The frontend receives only the dedicated API IPC
subdirectory read-only, not the evaluation tree or credentials.

Check frontend and API health independently. An available SPA may correctly
show the API as disconnected. The API can be healthy while the simulator or
policy server is unavailable. These states must not be collapsed into one
successful health indicator.

Browser refresh, session expiry and lost event connections do not cancel
submitted jobs. Recover the job ID and read its status; do not click a new
submission merely because a response was lost. Reuse the retained idempotency
key for an ambiguous submission.

An API/runtime restart is different from a browser reconnect. Recover queued
work explicitly after an unclean stop. Started work without verifiable
completion evidence remains indeterminate rather than being rerun blindly.
Do not delete another process's socket or kill operator-owned policy servers
when troubleshooting the workbench.

Verification record
-------------------

Before implementation, the non-simulation GUI baseline passed 35 tests and
the YAML loader passed seven tests in the discovered Arena container under
a non-root identity. The existing GUI subprocess preview test exceeded the
baseline command's time limit; its test-owned processes were stopped. That
preview is not recorded as a pass.

A separate live transport probe verified HTTP across a read-only IPC bind
mount, rejection of an unrelated non-root identity, and refusal of writes
through the frontend mount. This validates the selected local transport,
not the unfinished full application or simulation parity.

The assembled development launcher, Python health endpoint, browser diagnostic
submission, completed-job reload and live reconnection have been exercised.
The editor verification reran 102 backend/editor/query/snapshot tests with one
opt-in render test skipped, 44 frontend tests, and TypeScript checks. Thirteen
launcher tests passed. Live HTTP checks verified the default fixture,
invalid YAML diagnostics, stale-save rejection, downloaded immutable YAML,
unchanged source files, actual Neo4j entities and mutation rejection.

The snapshot service produced five real asset/reference PNGs and a full scene
overview for the default fixture, with one environment and zero action steps.
That verifies rendered output, not manipulation success. Five real Chromium
editor checks passed: draft reload recovery, document/schema/graph interaction,
save/export with unchanged source, Neo4j query/table/graph inspection, and real
image decoding, zoom and stale labels. The live generation test was skipped because credentials
and its run budget are not configured. The first browser run exposed an
over-broad test locator, which was corrected before the passing rerun. The full
workbench Chromium suite then passed 12 tests with only live model generation
skipped, including multi-tab SSE, accepted-but-lost submissions, revocation and
polling fallback. Independent backend, query and frontend recovery reviews
passed after fixes. The full repository test suite has not been run.

The legacy generator retains Flake8 findings reproduced against its HEAD
version (R508, F541 and SIM105), so the complete changed-file hook run is not
clean. Checks pass for the remaining changed files. The generated npm lockfile
is excluded from prose spell checking; its integrity hashes are unchanged.

Start and inspect the integration interface
-------------------------------------------

From the repository root, with the existing Arena runtime already running::

    sh docker/workbench/run_workbench.sh inspect --dev --diagnostics --port 3001
    sh docker/workbench/run_workbench.sh start --dev --diagnostics --port 3001
    sh docker/workbench/run_workbench.sh status --dev --diagnostics --port 3001

Open ``http://localhost:3001`` or ``http://127.0.0.1:3001``. Port 3001 was explicitly selected for the verified
local launch because port 3000 was occupied. The default remains 3000; select an
available port explicitly rather than stopping another application. Do not run
``start`` again when ``status`` already reports an owned healthy API. To stop
only the workbench frontend and its verified API supervisor::

    sh docker/workbench/run_workbench.sh stop --dev --diagnostics --port 3001

The API health probe must preserve the configured browser Host authority even
over the Unix socket. Local launches accept both ``localhost:3001`` and
``127.0.0.1:3001``; omitting or changing the configured port is still rejected.
Each supplied Origin must match that request's Host and the configured scheme.
Mutations still require Origin, with CSRF checks for established sessions.
Other configured hostnames do not gain loopback aliases. The two loopback
names use separate browser cookies and draft storage, so keep the same hostname
while editing. Lifecycle-control, process-supervisor and
backend-instance locks have distinct names to avoid conflicting with each
other during startup.

Using the editor
----------------

The document picker loads existing repository YAML without modifying it. Editing
triggers debounced schema validation, not generation, graph publication or GPU
work. The graph shows authored assets, relations and explicit reifiers; invalid
YAML remains editable and does not display an old graph as if it were current.
Select a graph node to inspect its properties. Catalog selection IDs and loaded
view IDs differ: mutations use the loaded view ID, which binds frozen include
content, rather than silently reading another tab's newer source context.

``Save revision`` creates a new private snapshot and offers an explicitly
flattened YAML export. Original YAML and include files remain untouched.
Unsaved drafts survive in-app navigation and have per-tab reload recovery.
Restoration is explicit and requires unchanged source/frozen-include identity;
otherwise a raw YAML download remains available without silently substituting
new include content. Closing the tab or clearing browser storage can remove
that recovery copy. Use save/export for durable revisions; browser draft
recovery is distinct from durable submitted jobs.

An unresolved recovery stays available when navigating to Neo4j and back.
Oversized drafts or storage failures preserve the previous valid recovery copy
and offer ``Download current YAML`` for the current buffer, even if it cannot
pass schema validation. Browser quotas still apply; recovery is not a substitute
for a saved revision.

``Render snapshots`` explicitly queues a bounded Isaac Sim operation. It returns
the scene overview and object/reference thumbnails through authenticated artifact
URLs. The renderer is reused for later jobs, and matching canonical input can use
a checksum-verified receipt. Edits label existing images stale. The existing
renderer does not create a standalone robot thumbnail; the robot appears in the
scene overview. Rendering currently uses one environment and zero action steps,
not an adjustable policy rollout. Asset constructor parameters are restricted to
numeric/bool structures to prevent arbitrary asset URLs.

The cooperative renderer lease defaults to
``/eval/.arena-workbench-gpu.lock`` rather than private container ``/tmp``.
Cooperating clone containers must share that host-backed path. If they use
different evaluation mounts, configure the same absolute shared path through
``ARENA_WORKBENCH_GPU_LEASE``. This conservative lease serializes workbench
renderers; it does not control independent policy or simulator processes.

The Neo4j view accepts a restricted read-query subset, JSON parameters, and example
queries. Calls, updates, comments, namespaced/unknown functions and quoted function
invocations are rejected. Neo4j must classify the compiled query as read-only;
execution uses a five-second transaction timeout and always rolls back. Responses
are capped at 200 rows with bounded graph/value projection. Raw driver hydration
is not a hard memory bound; large aggregations still require operator care or
server-side resource limits. An unavailable database is shown explicitly and
does not disable YAML editing. Query results are never merged into the authored
scene graph.

Use the generation provider-settings panel to select a fixed provider endpoint,
enter a model ID and temporary API key, and explicitly consent to session use.
Choose a key expiration of 15 minutes, 30 minutes (default), 1 hour, or 2 hours.
The dedicated password control clears after submission; settings expire after
that duration or at session expiry, whichever comes first, and are removed from
API memory on access or periodic cleanup. Changing the selection only affects
the next save, not the current key's deadline. Keys are
not written to job history or YAML.
Saving settings makes no provider call. Forget the key or end the session when
finished. An already-authorized generation job may finish all its bounded model
calls; forgetting cannot revoke a key
at the provider or retract submitted data. Tabs sharing a browser session share
settings, and an API restart loses temporary credentials.

For unattended use, supported server environment variables remain
``OPENAI_API_KEY``, ``GEMINI_API_KEY``, ``OPENROUTER_API_KEY`` or ``NV_API_KEY``,
with the corresponding ``*_MODEL`` and ``*_BASE_URL`` when needed. Temporary
dashboard settings override that source for explicit session-bound generation;
forgetting them can restore the server fallback. Never enter keys in prompt,
YAML, or query fields. A generated result must be reviewed and explicitly applied;
it cannot silently replace a newer draft. See the architecture page's temporary
provider credentials section for lifecycle and residual security risks.

Development dependency ownership
--------------------------------

Run npm, formatter and browser-tool commands under the same non-root UID/GID as
the frontend. A root-created cache inside the dependency volume can make the next
``npm ci`` fail with EACCES. Repair only the discovered frontend dependency volume
or recreate that disposable volume; do not broaden repository or simulator
permissions and do not make the production server root to bypass the error.
