Installed workflow CLI and private setup
========================================

Scope and installation gate
---------------------------

The default query-only composition serves retained workflow queries without
execution credentials, an execution owner or mutations. The installed module
also exposes submit/cancel/resume for the guarded deterministic test composition;
that composition is harness-only, not an ordinary production operator launcher.
Neither mode starts containers. Configuration and credential installation grant
no execution authority.
The command called ``receipt`` reads an existing command receipt; it does not
execute that command. ``inspect-contract`` retains its original effect-free
behavior and does not import the optional HTTP server packages.

Use the already-running simulator discovered for the intended clone, as its
explicitly configured nonroot operator. The root editor's HOME is not the host
operator's HOME. No host-persistent mount mapping, editor rebuild, live credential
installation, or deployment has been established by this increment. The isolated
cohort exercises the actual module parser and composition in disposable UID-1000
state; it is not full T17, T21, or V0 acceptance.

The runtime must already provide the declared ``workflow-api`` and ``web`` optional
dependencies. This procedure installs nothing. It uses FastAPI/Strawberry plus
Uvicorn's asyncio/h11 single-worker server, with WebSockets, reload, proxy headers
and access logs disabled. Framework/driver logging is disabled in the server.

Explicit files
--------------

Supply an existing operator-owned mode-0600 ``server.json`` in a mode-0700
configuration directory outside the checkout. Its credential file must be the
explicit sibling ``credentials.json``. All files are plaintext: processes running
as that operator and root remain trusted. This is not encryption or a multiuser
secret store. No HOME/XDG discovery, dotenv loading, credential argv, or credential
environment variables are supported.

Configuration version 1 requires every field below (no extras):

* ``schema_version: 1``, ``mode: query-only``;
* ``operator`` with exact ``uid``, ``gid``, sorted distinct supplementary ``groups``,
  ``account``, ``home``, and ``cwd`` matching the running operator;
* ``private_root``, ``credentials_file``, ``artifact_root`` as explicit absolute
  canonical paths;
* ``endpoint`` as an explicit numeric IPv4 loopback HTTP URL ending in
  ``/graphql`` with a nonzero port;
* ``bolt_uri`` as an explicit numeric IPv4 Bolt URL and port, without userinfo,
  query, fragment, or path;
* a complete existing ``ScopeBinding`` in ``binding``;
* ``required_profiles`` containing complete exact ``ProfileRevision`` envelopes,
  not just IDs or implicit latest revisions;
* distinct ``bootstrap_principal`` and ``read_principal``.

Configuration is bounded at 256 KiB. Credentials are bounded at 128 KiB and contain
exactly ``schema_version: 1`` and
``databases.operational.{scheme,username,password}``, with ``scheme: basic``.
Username/password limits are 256/4096 UTF-8 bytes, with no control characters.
Duplicate keys, nonfinite numbers and extra fields are rejected.

Explicit private roles (configuration v3)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Version 3 retains those public fields, permits ``query-only`` or the existing
``isolated-synthetic-execution-v1`` mode, and requires ``role_bindings`` with
exactly ``generation``, ``assessment``, ``repair`` and ``prior_read``. The
synthetic mode still requires the original harness capability, even with valid
private setup. Version 2's fixed legacy synthetic fixture remains supported for
its existing acceptance cases.

Each model binding contains ``credential_alias`` and a complete public
``ProfileRegistration`` in ``profile``. Its exact revision must occur in
``required_profiles`` and contain the corresponding generation/assessment role.
No model, endpoint, request policy or accounting selection is inferred. The
current workflow contract uses the generation model for repair: the repair
binding must explicitly equal the generation binding, including its alias.
Independent repair profiles/credentials are rejected, not substituted.

The prior binding contains ``credential_alias``, ``endpoint``, ``database`` and
``authentication: basic``. It supports the same literal numeric IPv4 Bolt
transport, not DNS, routing or TLS. This is private role setup only; nonempty
prior retrieval is a separate slice.

The private input document for v3 configuration has ``schema_version: 2``,
``databases`` and ``models``. Operational credentials retain their v1 shape.
Optional ``databases.prior_read`` contains ``alias``, ``scheme: basic``,
``username`` and ``password``. ``models`` maps selected roles to
``{alias, api_key}``; aliases must match the public bindings and equal aliases
must contain equal key bytes. Keys are bounded printable ASCII strings, at least
16 characters. Model and prior slots are separate; neither falls back to the
operational login or ambient environment. Missing slots can be stored for
query-only operation but cannot initialize guarded execution.

Setup/update assigns the stored document a random nonsecret ``generation``;
do not supply this field in the input. The returned generation is not a secret
hash or an execution grant. Runtime snapshots check the complete current
document, and the existing worker release guard excludes supported credential
updates while sending. A changed/missing source blocks new release until an
explicit restart and fresh authorization. Current-read access and immutable
receipt replay do not require model credentials. To withdraw only execution
credentials, update with empty ``models`` and omit ``prior_read``, retaining the
operational login. ``credentials-remove`` removes the entire credential file.

Credential input uses an explicitly supplied, UID/GID-owned mode-0600 anonymous
read pipe, FD 3 or greater. Its writer must close to provide EOF within five
seconds. Standard descriptors, ordinary files and writable pipe ends are rejected.
There is no implicit non-TTY password prompt or echoing fallback. A trusted input
tool must supply this private descriptor; the CLI does not read real credentials
until an explicitly selected local operation requires them.

Command forms
-------------

The following forms are implemented and exercised against synthetic disposable
state. ``ABS`` and ``ID`` denote operator-reviewed values, not runtime discovery.
Prefix every form with::

  /isaac-sim/python.sh -m isaaclab_arena.agentic_environment_generation.workflow.cli

Local setup and explicit administration::

  setup --config ABS --create --credentials-fd FD
  credentials-update --config ABS --credentials-fd FD
  credentials-remove --config ABS
  admin initialize-schema --config ABS
  admin initialize-scope --config ABS
  admin initialize-artifacts --config ABS --create
  admin register-profile --config ABS --registration ABS

Setup does not contact Neo4j. Schema administration executes the store's current
DDL and a bounded index wait. Scope/artifact/profile administration calls the
existing admin interfaces. Registration accepts a private bounded
``ProfileRegistration`` document. Normal API startup only opens and verifies
existing schema, scope, artifacts and exact profiles; it does not initialize them.
A failed cross-resource administration command is not an atomic rollback claim.

Exact instance lifetime::

  api-launch --config ABS --instance ID
  api-status --config ABS --instance ID
  api-stop --config ABS --instance ID
  api-reconcile --config ABS --instance ID
  api-handover --previous-config C1_ABS --previous-instance OLD_ID --config C2_ABS --instance NEW_ID

``ID`` is exactly 32 lowercase hexadecimal characters. Never reuse it for a new launch. Launch
persists intent before one detached server child, captures exact process identity,
and privately gates startup. The internal ``api-serve`` entry cannot be used
without the inherited lifetime lease and startup gate. Users do not create those
lifecycle descriptors manually.

A successful launch returns only the nonsecret receipt fields. The corresponding
private client descriptor is
``private_root/instances/ID/client.json``. Use that exact immutable instance path;
clients never follow a mutable current-auth pointer. Bearer lifetime is 3600
seconds, generation 1, with no hot renewal. Expiry is taken from the actual server
auth context. Stop revokes auth and drains the owned query executor and driver.
The UDS stop acknowledgement alone is not clean shutdown: public success also
requires a terminal receipt, exact process absence and released lifetime lease.

After a successful stop, launch with a new ID and select its new client descriptor.
Old descriptors are retained in consumed instance directories and their tokens
are rejected by the replacement. Those directories are tombstones, not reusable
slots. Any failed or interrupted launch can leave durable intent: reconcile its
exact ID rather than blindly spawning another process. Missing identity remains
unknown. There is no numeric-PID kill, takeover, repair, or general RPC facility.

Checked changed-configuration handover
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Keep C1 unchanged. Stop/reconcile its exact instance using C1, not C2. Launches
retain public ``configuration.json`` inside each private instance tombstone.
For a configuration change, use ``api-handover`` after C1 reaches exactly
``stopped/drained`` with its process gone. An unresolved or unclean owner must be
recovered with C1 first; reconciliation alone is not a drain proof.

Handover checks C1's full digest and retained configuration under the existing
metadata/lifetime locks before consuming a distinct C2 instance. Durable scope,
Bolt binding, artifact root, private/credential roots, operator and principals
must remain unchanged. Supported endpoint/profile/mode selections can change;
unsupported execution still fails closed. Tombstones and durable allocations
are never deleted or reset. Retrying the identical handover with the same target
ID observes that consumed transition instead of launching another child; it is
not permission to reuse the ID for different work. Old instance tokens are not
accepted by C2. Credential-only replacement under unchanged C1 is a separate
``credentials-update`` plus ordinary exact restart/reapproval operation, not a
configuration handover.

Fixed network queries::

  profiles --client ABS
  profile PROFILE_ID --revision DECIMAL --client ABS
  status RUN_ID --client ABS
  submission OPERATION_ID --client ABS
  receipt --kind SUBMIT OPERATION_ID --client ABS
  runs --first 10 --client ABS
  events --first 10 --client ABS

Receipt kinds also include ``CANCEL`` and ``RESUME``. Runs/events support an
explicit ``--after`` cursor. All requests use fixed typed operation documents
with variables through actual HTTPX HTTP, never direct-store fallback, arbitrary
query input, principal override, redirects, proxy environment, or cookies.

Exit 0 means the local command or transport response completed; inspect the typed
GraphQL result for ``NotFound``/``QueryFailure``. Exit 2 is a static rejection or
incomplete operation, not proof of no effects. Exit 3 is an unresolved instance
observation. Public diagnostics do not include raw exceptions or argument values.

Explicit retained priors (guarded synthetic composition only)
-------------------------------------------------------------

Workflow contract schema ``"2"`` adds a required ``retrieval`` selection to a
new-generation request with ``effects.allow_database_reads: true``. This is
separate from public installed configuration v3 and private bootstrap v2.
Schema ``"1"`` retains its original wire representation and explicitly
unavailable/unconfigured prior path; it does not silently enable reads.

Every schema-2 retrieval field is explicit:

* ``schema_version: "1"``, ``source: "neo4j-legacy-graph-rag"`` and
  ``eligibility: "measured-or-structural-v1"`` select the existing legacy-only
  GraphRAG snapshot implementation. Managed/SQLite sources are not supported
  by this composition and are not imported or opened on this path.
* ``credential_alias``, ``endpoint`` and ``database`` must match the installed
  ``role_bindings.prior_read`` literally. Only numeric IPv4
  ``bolt://address:port`` with the separately installed Basic prior-read login
  is supported. No operational-login, endpoint or ambient-secret fallback occurs.
* ``settings`` supplies ``limit`` (1–5), ``min_success_rate`` (0–1),
  ``min_episodes`` (1–1,000,000), ``query_timeout_seconds: 5.0`` and
  ``max_transaction_retry_time_seconds: 0.0``. Both
  ``connection_timeout_seconds`` and ``connection_acquisition_timeout_seconds``
  must be positive and no greater than 5 seconds; the installed case explicitly
  selects 3.0 and 5.0 respectively. No timeout is inferred from a missing field.
* ``settings_sha256`` is SHA-256 over compact, sorted-key JSON of exactly
  ``{"eligibility": ELIGIBILITY, "settings": SETTINGS}``. This hashes public
  selection data, not credentials.
* ``required`` and ``allow_empty`` are booleans. ``required: true`` blocks an
  unavailable retrieval outcome. An empty successful retrieval is allowed only
  when ``allow_empty: true``. Optional retrieval does not waive source selection,
  current authorization, credential binding or integrity checks. Structural-only
  examples remain explicitly unevaluated; they are not policy-performance evidence.

The server consumes a one-shot prior-selection gate under the existing scope
lock, uses a transient ``retrieval_read`` grant, and closes the read driver and
revokes that grant before any worker release. Current grant/principal validity
is rechecked before driver/session/query/cursor I/O and after cleanup; a read
starts only while enough authorization time remains for its selected connection,
acquisition and query bounds. Expiry or revocation vetoes the result even when
retrieval would otherwise permit an unavailable outcome. These are operation
boundary checks, not a claim to retract an already dispatched database read.
The exact snapshot is retained in
the existing immutable artifact area. A bounded, digested run linkage binds the
accepted contract/selection, disposition, context hash and exact manifest before
generation reservation/release. No prior login is delivered to model workers.

The existing known-unreleased generation continuation reopens those exact bytes;
it never retrieves again. Corpus changes and withdrawal of the prior login do
not change the retained context. Missing, tampered, oversized, foreign or
incomplete linkage/bytes reject rather than rebuilding the snapshot. A crash
during selection/retention remains a fail-closed incomplete selection, not an
automatic retry. This does not add recovery for every pre-reservation crash point.
Current authorized ``prior``/``artifact`` reads use the same authoritative
linkage and do not require retrieval authority or an execution factory.

Evidence and limitations
------------------------

The Plan 04 ``workflow-graphql-execution-joined`` cases ``operator`` and
``rotation`` exercise these new paths using real installed CLI/HTTP, owned
workers, sentinel keys and disposable Neo4j. ``operator`` checks credential
withdrawal, C1-to-C2 handover/replay, stale-token rejection, unchanged durable
work and fresh query-only artifact access. ``rotation`` replaces sentinel keys
under unchanged C1, restarts/reapproves a known-unreleased attempt, verifies the
new keys at the actual deterministic worker constructors, and preserves original
reservations and lost-response receipts. They do not certify live provider access,
password enforcement, native simulation or production execution. Current results
and commands are recorded in the canonical research-stack implementation handoff.

The ``prior`` case seeds a structural-only fixture in its own disposable graph,
retrieves a nonempty snapshot through the installed boundary, interrupts before
worker release, changes the corpus and withdraws the prior login. It then
restarts/reapproves the existing generation attempt and observes the original
complete context in the actual SDK mock-transport payload, with zero new reads.
It verifies immutable authenticated readback, lost-response replay, original
reservations, query-only authorization/integrity negatives and exact cleanup.
The fixture and deterministic responses do not certify simulation, model quality,
live provider access or real-password enforcement.

The following older query-network evidence retains its original narrower scope.

The additive ``workflow-graphql-network`` cohort uses one disposable auth-disabled
Neo4j DB and one test container, no published ports, and the accepted immutable
GraphQL test image. Installed composition supplies loaded basic credentials even
though that DB does not enforce passwords; this proves private loading/handoff,
not wrong-password rejection or production database authentication.

The cohort repeats kernel denial, immutable image/import witnesses, source guards
and role permissions in each fresh interpreter. It covers explicit fresh setup
and admin, retained writer data, authenticated loopback queries, disconnected
launcher/clients, exact stop, new-instance restart, old-token rejection and
missing-artifact startup failure without initialization. It also checks private
file refusals, restrictive umask, input descriptor restrictions, interrupted
credential replacement and failed directory sync. The old ASGI/Bolt-only cohort
remains child-free.

The remaining adversarial lifecycle acceptance matrix is not complete: simultaneous
launch/lost acknowledgement, wrong live UDS peer, real or controlled DB-outage
stop, delayed-query drain under stop, and physical expiry observations need further
isolated cases and independent review. No hour-long expiry test was performed.
Local stale-writer and missing-identity tests do not establish a physical old-exit
race. Node readback excludes only control ``revision``/``lock_anchor``; complete
schema/relationship readback is not yet part of this new cohort.

Retained source/JUnit/import/process/cleanup artifacts and the explicit acceptance
status are under
``outputs/workflow/plan03-implementation/graphql-query-launch/implementation/``.
Do not treat a passing current subset as completion of the entire selected
contract or approval to deploy shared services.
