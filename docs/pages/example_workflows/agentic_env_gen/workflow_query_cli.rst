Query-only installed module
===========================

Scope and installation gate
---------------------------

This module serves retained workflow queries. It does not submit, cancel, resume,
execute a workflow, start containers, or own the Neo4j workflow execution lease.
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

``ID`` is exactly 32 lowercase hexadecimal characters. Never reuse it. Launch
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

Evidence and limitations
------------------------

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
