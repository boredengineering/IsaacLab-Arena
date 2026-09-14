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

Trying the graph explorer preview
----------------------------------

After launching the existing workbench, choose **Try graph explorer**, or open
``http://localhost:3001/workspaces/default?graphRenderer=explorer``. This is a
preview rollout; **Use legacy graph** returns to the existing SVG view without
changing the draft or restarting the API. Keep your usual hostname for cookies
and draft recovery.

* **Table** has Nodes and Relationships views with sorting, pagination and
  explicit Inspect buttons. Selection is shared with the visual modes.
* **2D** supports node dragging, pan/zoom, pins, Fit visible and Focus selection.
  Dragging pins a node. Freeze layout keeps inspection and camera controls
  working; Unpin while frozen takes effect when layout resumes.
* **3D** loads only when selected and supports orbit/pan/zoom. It is a
  relationship diagram, not the Isaac Sim scene. If WebGL fails, use Table or
  2D. A failed module download may require reloading; preserve unsaved work first.
* **Navigation controls** and inspector coordinate/nudge controls provide
  keyboard and click-only alternatives. Coordinates are graph-layout units,
  not physical poses. No YAML edits or simulator/model calls result.
* Search and role/type filters affect returned entities only. Reveal explicitly
  clears visibility filters. No follow-up database query is sent on selection.
* **Expand graph** gives the diagram more room; Escape closes it. Layout state
  is in-memory only and resets on reload or a new source/session.

In ``/neo4j?graphRenderer=explorer``, run an explicit read-only query and select
the outer **Graph** tab to explore its returned entities. The outer **Table**
still displays raw query rows, including scalar results. It is different from
the explorer's Nodes/Relationships table. Existing query limits are unchanged.

Visualizations above 512 valid nodes or 1,024 valid relationships use an explicit
Table fallback; frontend normalization has separate diagnostic safety limits.
Do not infer graph completeness or physical validity from any renderer.

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
Choose a key expiration of 15 minutes, 30 minutes (default), 1 hour, 2 hours,
or **Never expires**. The latter disables only the key timer, not session expiry:
the key stays in API memory until the session ends or the API restarts (or you
forget/replace it). Explicit session activity can extend its idle deadline within
the session's absolute lifetime; polling cannot. The active status shows the
current session deadline. Longer retention increases exposure.
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

Prompt-first A2 draft
----------------------

After deploying an API advertising ``generation_modes``, select **New environment
from prompt** without loading a template. With a provider and run budget approved,
enter: "Droid grasps the yellow banana from the right side of the maple table and
places it onto the large white ceramic plate on the left."

Choose whether unavailable retrieval should stop generation or allow an explicit
fallback. Inspect the returned context, catalogue digest, prior identities and
warnings; structural precedent is not measured policy success. Verify the DROID,
banana and large-plate assets and task destination before applying the result.
The application does not infer A2 success from schema validity. An empty database
can legitimately supply no priors, and query-page connectivity does not establish
the worker's separate server-configured retrieval profile.

Applying New detaches any previous document context and revalidates. **Refine
current environment** instead requires an explicit valid base. **Save revision** /
export of either result remains editor-draft persistence: this P1 action does not
create a numbered research version, publish Neo4j data, or evaluate a robot policy.
The opt-in **Save Research Version** preview below is a separate explicit action.

If authorization expires before release, select the blocked job and explicitly
reauthorize or cancel it. Correcting rejected credentials requires a verified
rejection and separate approval; ambiguous responses never silently switch keys.
Cancelled work can retain a candidate or an unknown provider outcome. Inspect the
evidence rather than treating every cancelled job as work never executed.

The current implementation evidence uses synthetic browser APIs and synthetic
subprocess workers. It does not establish successful live A2 inference. A running
older API must be rolled out separately after journal backup and recovery checks;
temporary credentials will be cleared by restart.

Managed research preview: operator onboarding
----------------------------------------------

.. warning::

   Initialization and backup are offline-only and require ``--attest-quiescent``.
   Close all journal connections and keep API/workers offline throughout; the CLI
   never stops them implicitly. Reviewed lock checks reject attached WAL connections
   and conflicting rollback transactions, not every idle connection. These preview
   interfaces are not an approved deployment cutover or power-loss durability proof.

This is an opt-in code preview, not a completed P2 deployment. Generation and
**Apply generated YAML** remain draft-only; **Save revision** / export saves an
editor snapshot. The separate **Save Research Version** action persists an exact
accepted candidate as a numbered version in a configured managed store, with
immutable artifacts and lineage. Neither save action requests publication or
policy evaluation. Publication transport, managed Graph-RAG retrieval integration
and worker integration remain unfinished or under review, not publicly enabled
end-to-end functionality. The legacy CLI remains a separate path, not a certified
safe concurrent writer to managed stores.

Store profiles and explicit initialization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Python API accepts ``research_roots`` or repeatable launcher arguments
``--research-store ID=ABSOLUTE_PATH``. The empty default is unchanged;
``research_versions`` is true only when roots are configured. A capability flag
is not proof a root is available. Profile validation and GET discovery/read
requests never initialize stores or migrate a journal. Missing, incompatible or
misbound stores fail closed.

Before changing an existing deployment, back up and review its P1 journal using
an operator-approved SQLite-consistent procedure (including WAL state), inspect
pending/indeterminate work, and coordinate maintenance with its owner. Do not
copy only a live main SQLite file. The managed ``backup`` command below requires
already registered stores; it is not the pre-initialization P1 backup procedure.
There is no silent P1 migration: ``init-store`` requires an existing journal with
the exact supported current P1 schema and private ownership/permissions. An older
schema is rejected, not repaired by opening the API or running this command.
Initialization attaches without constructing a new Journal or owning its lifecycle.

All paths below are **operator-replaced absolute placeholders**, not selected data
locations. Run only after review, inside the intended non-root Arena runtime with
its supported interpreter. Use a new managed root outside legacy
``generated_envs`` and ``eval_output`` trees; its parent must already exist. The
journal directory must be owner-private (0700), its database/sidecars 0600. Attest
only trusted-owner Linux-local storage with working SQLite locks and local rename
semantics, not a network/distributed filesystem::

    /isaac-sim/python.sh -m isaaclab_arena_examples.agentic_environment_generation.research_admin init-store \
      --journal /REPLACE/private-state/journal.sqlite3 \
      --store-id research --root /REPLACE/managed-research \
      --attest-local-filesystem --attest-quiescent

An optional, separately reviewed preparation step creates the local publication
request/worker ledger. It requires the same offline/quiescent conditions and an
already initialized registry. Missing initialized enforcement triggers are rejected,
not repaired; this review does not authorize a deployment cutover::

    /isaac-sim/python.sh -m isaaclab_arena_examples.agentic_environment_generation.research_admin init-publication-ledger \
      --journal /REPLACE/private-state/journal.sqlite3 --attest-quiescent

This changes only local SQLite publication schema. It does not install Neo4j
constraints, create publication intents, configure credentials, launch workers,
or enable publication. API startup never performs this initialization implicitly.

After initialization, configure the already reviewed API launch path, not a
second competing API. This is the Python launcher interface, not a promised
forwarding option on the stock Docker shell launcher::

    /isaac-sim/python.sh -m isaaclab_arena_examples.agentic_environment_generation.web_api \
      --state-dir /REPLACE/private-state --socket /REPLACE/private-ipc/api.sock \
      --origin http://localhost:3001 \
      --research-store research=/REPLACE/managed-research

Verify the exact advertised store and availability after the controlled rollout.
Do not initialize on behalf of a browser GET or bypass schema checks to make a
profile appear available. A source checkout does not upgrade a running API.

Save, lineage and exact recovery
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Review the candidate's exact job, attempt and generation before saving. Select
an explicit immutable parent revision for lineage, or intentionally no parent;
never infer it from a family name, highest version number, or ``latest``. Reserved
numbers are not proof of a committed version. Inspect the committed manifest and
exact version read/download, rather than guessing an output directory.

Retain the save operation ID and frozen store/family/source/parent request across
ambiguous responses. Recover that exact operation, including after session S1
expires and a replacement session S2 is established. Session replacement does not
create permission to select another candidate or issue a new operation. A conflict
or missing evidence is not proof that nothing committed. Use the UI's explicit
recovery controls; do not clear an unresolved save merely to allocate another
version. Generation job recovery and research-save recovery are distinct steps.

The optional managed CLI connects to an **already-running** owned Unix-socket API;
it does not start services. Fresh work requires the API's configured server model,
not a temporary dashboard key. This example generates from a prompt with no
``--base_spec`` and no API key in argv. Replace the socket/origin/profile and retain
the chosen operation ID before the first invocation; running this authorizes
bounded model work, so it is not a setup probe::

    /isaac-sim/python.sh isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
      --mode resolve \
      --prompt "Droid grasps the yellow banana from the maple table and places it onto the large white ceramic plate." \
      --managed_api_socket /REPLACE/private-ipc/api.sock \
      --managed_api_origin http://localhost:3001 \
      --managed_store_id research --managed_family banana_plate \
      --managed_operation_id REPLACE_WITH_RETAINED_OPERATION_ID

Only ``resolve`` supports this adapter. It rejects CLI credentials, endpoint and
sampling overrides. Optional ``--model`` asserts the configured/accepted model;
it does not reconfigure the server. Rerun unchanged with the same operation ID to
recover an ambiguous result: exact accepted-request lookup precedes fresh model
preflight, so already accepted work can be recovered even if current server model
settings changed, including in S2. Recovery never silently reauthorizes or reruns
indeterminate work. A polling timeout does not cancel the accepted job.

On success the adapter verifies the exact commit readback and YAML digest and
reports ``version_ref`` plus an authenticated artifact URL; it does not write a
legacy output or request publication (``publication=not_requested``). The current
CLI save explicitly has no parent; it does not infer lineage from ``--base_spec``.
Use explicit parent selection in the research UI when that lineage is required.
Without managed flags the old versioned CLI resolve behavior remains unchanged,
including its separate publication attempt; see the existing CLI onboarding.

Private checkpoints, not automatic restore
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After stores exist, repeat ``--store`` for **all registered profiles**. Destinations
must be new, private operator-chosen locations. Estimate and verification read an
existing sealed checkpoint, not a live journal. Both initialization and backup
require ``--attest-quiescent``: close all journal connections and keep the API and
workers offline throughout the command. Nothing is stopped implicitly; conflicting
SQLite locks cause an immediate busy response. Idle rollback connections may hold
no lock, so the operator's offline attestation remains necessary. Preflight validates a private
main-database-plus-WAL copy, not an ``immutable=1`` view of an active journal::

    /isaac-sim/python.sh -m isaaclab_arena_examples.agentic_environment_generation.research_admin backup \
      --journal /REPLACE/private-state/journal.sqlite3 \
      --store research=/REPLACE/managed-research \
      --destination /REPLACE/private-checkpoints/checkpoint-001 --attest-quiescent
    /isaac-sim/python.sh -m isaaclab_arena_examples.agentic_environment_generation.research_admin verify-checkpoint \
      --source /REPLACE/private-checkpoints/checkpoint-001
    /isaac-sim/python.sh -m isaaclab_arena_examples.agentic_environment_generation.research_admin estimate-checkpoint \
      --source /REPLACE/private-checkpoints/checkpoint-001
    /isaac-sim/python.sh -m isaaclab_arena_examples.agentic_environment_generation.research_admin prepare-restore \
      --source /REPLACE/private-checkpoints/checkpoint-001 \
      --destination /REPLACE/private-restore/prepared-001

Checkpoints contain private journal data, including Sessions-derived state; treat
them as private backups, not shareable research exports. Temporary model keys are
not made durable by checkpointing. The checkpoint service has a 30-second
cooperative deadline; administrative preflight separately budgets five seconds
for copying. Blocked OS I/O/fsync cannot be forcibly interrupted. Checksums, bounded
copying and fault tests are not proof of power-loss durability. A
``durability_uncertain`` result is not success or permission to overwrite/retry
blindly; inspect the exact checkpoint. ``busy`` requires resolving ownership or
contention, not deleting locks.

``prepare-restore`` **never activates** a database. It produces an inactive
``journal.inactive.sqlite3`` with ``activation_required=true``. It does not perform
a full API restore, undo Neo4j effects, or automatically replay the queue. Do not
point the API at this prepared copy as a shortcut. Activation and reconciliation
of immutable effect IDs and research references require a separate authorized
procedure; this preview supplies no automatic cutover or rollback command.

Remaining acceptance
~~~~~~~~~~~~~~~~~~~~

* Approve provider spend/token/time budgets and retrieval/result limits before
  live model work; set independent render/evaluation budgets before GPU work.
* Obtain runtime evidence on the reviewed deployment: exact accepted operation
  recovery across restart/S2, committed artifact readback, and separately authorized
  publication/retrieval/worker behavior. Synthetic browser APIs, unit tests and
  docs builds do not prove live inference, graph effects or physical policy success.

Development dependency ownership
--------------------------------

Run npm, formatter and browser-tool commands under the same non-root UID/GID as
the frontend. A root-created cache inside the dependency volume can make the next
``npm ci`` fail with EACCES. Repair only the discovered frontend dependency volume
or recreate that disposable volume; do not broaden repository or simulator
permissions and do not make the production server root to bypass the error.
