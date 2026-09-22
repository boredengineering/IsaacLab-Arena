Offline setup and readiness inventory
====================================

This is the first Plan 04 operator inventory, **not** workflow launch, private
provider setup, live readiness, contract admission or an execution grant.
It leaves the installed query-only commands unchanged.

Usage (no service or credential access)
--------------------------------------

In an already installed, approved Arena runtime, as its mapped non-root operator,
use the existing module entry point. From the repository root in that runtime::

   /isaac-sim/python.sh -m isaaclab_arena.agentic_environment_generation.workflow.cli setup-readiness

This produces an unresolved scene-only inventory with consolidated blockers.
To inspect explicit public selections::

   /isaac-sim/python.sh -m isaaclab_arena.agentic_environment_generation.workflow.cli setup-readiness \
     --selection docs/pages/example_workflows/agentic_env_gen/setup_selection.example.json

The command reads only that bounded regular JSON data file, prints JSON to stdout
and exits 0 when the **offline report was produced**, even when every execution
gate is blocked. It does not create files, read private configuration, inspect
environment keys, connect to services, initialize native code, grant authority
or write any database/store. Normal Python module loading is not a scan of
operator data. It does not require optional GraphQL, DB or provider SDK imports.
No container start, installation or live probe is implied by these commands.
The CLI adapter and equivalent example JSON are exercised in admitted isolated
tests; this is not a deployed-runtime or fresh-process installation proof.

Malformed selections return exit 2, no stdout, and exactly
``setup-readiness: invalid selection file`` on stderr. Unknown/malformed CLI
arguments retain the existing static ``inspect-contract: invalid arguments``
diagnostic. Input paths and validation values are not echoed in errors.

Example
-------

Download :download:`setup_selection.example.json <setup_selection.example.json>`.
All labels are illustrative public selections, not tested model access or real
service discovery. The prior-read DNS/TLS URI is intentionally incompatible with
the current installed adapter: the report must retain it, not replace it with a
plaintext connection. The operational address is a documentation address, not a
working deployment. Repair, policy and inference request profiles remain undecided.

.. literalinclude:: setup_selection.example.json
   :language: json

Bounded selection schema v1
---------------------------

The root contains exactly ``schema_version`` (integer 1), ``outcome``
(``scene-only`` or ``required-policy``), and ``roles``. The file must be UTF-8 JSON,
at most 65,536 bytes, with nesting depth at most 12. Duplicate fields, nonfinite
numbers, unknown fields/roles, malformed values, final symlinks, nonregular files
and oversized inputs are rejected. No fields for import paths, secret values,
private file paths, environment variable names, readiness assertions or grants
are accepted. Public labels are not a secret-detection boundary; see below.

Each role can be absent or null (unresolved), or a partial object. Absent fields
become null; no provider/model/endpoint is inferred. Only these fields are allowed:

* ``generation``, ``assessment``, ``repair``: ``provider``, ``model``, ``endpoint``,
  ``credential``, ``inference_profile``. Providers are the existing pure catalogue's
  ``openai``, ``gemini``, ``openrouter`` or ``nvidia``. Literal public model labels
  are bounded to 256 ASCII characters. Endpoints are HTTP(S), at most 512 ASCII
  characters, with no userinfo, query, fragment, percent escapes or backslashes.
  A structurally valid noncatalogue endpoint remains literal and receives an
  implementation blocker; it is never silently normalized or contacted.
* ``local_policy``: ``provider`` (``gr00t``), ``model`` (public checkpoint label),
  ``endpoint`` (TCP with explicit port and no path, or HTTP(S)), ``credential``.
  Labels do not attest loaded checkpoint bytes or served-instance identity.
* ``prior_read``, ``operational_db``: ``provider`` (``neo4j``), ``endpoint``,
  ``database``, ``authentication`` (``basic``, ``bearer``, ``kerberos`` or ``none``),
  ``tls`` (``none``, ``system_ca``, ``custom_ca`` or ``self_signed``), ``credential``.
  These are desired transport/auth requirements, not claims of installed support.
  Bolt/Neo4j URI schemes, including TLS variants, are representable without DNS
  resolution. Certificate files are neither selected nor opened here.

``credential`` is null or an object containing ``alias``, ``source``,
``source_role``, and optionally ``public_id``. Alias and public ID are nonsecret
ASCII labels bounded to 128 characters. ``public_id`` may contain an explicitly
supplied provider-issued project/key identifier, **never a key or secret-derived
fingerprint**. This structural validator cannot recognize a secret pasted into
an otherwise valid public label: everything admitted is printed publicly.

``source`` is ``private_file``, ``private_pipe`` or ``named_environment``. These
are inventory choices, not implemented loaders. For local policy only, ``none``
explicitly represents no credential, with a public alias such as ``local-no-auth``.
The required source-role mapping is:

.. list-table:: Logical bindings only, not private values
   :header-rows: 1

   * - Role
     - Source role
   * - generation
     - models.generation
   * - assessment
     - models.assessment
   * - repair
     - models.repair
   * - local_policy
     - policy.local
   * - prior_read
     - databases.prior_read
   * - operational_db
     - databases.operational

Equal aliases display ``shared_alias_with`` for every affected role, while role
bindings remain separate. A shared alias must agree on source and public ID.
This does not verify equal private key bytes or authorize cross-role fallback.

``inference_profile`` is null or the existing complete public inference-profile
shape validated by ``checked_inference_profile`` and its pure request-policy
validator. Builtin profiles must match the catalogue exactly; user-defined
profiles must remain ``unverified``/``not_checked``. Provider/model/endpoint must
match literally; trailing-slash differences are not repaired. Supplying a
profile with asserted live verification is invalid. A null profile remains a
separate request-profile blocker even when the public binding is configured.

Interpreting the report
-----------------------

* ``public_selection: configured`` means required public fields are present, not
  that a private source exists, a credential works or the installed adapter can
  execute that choice. Partial/absent fields report ``unresolved``.
* ``access`` and ``capability`` always remain ``not_checked``; ``execution`` is
  always ``not_authorized``. Check times are null, credential generation is
  ``not_observed`` and execution authorization is false. User assertions cannot
  upgrade these fields.
* ``blockers`` are consolidated by code, with owner ``operator_setup``,
  ``implementation_missing`` or ``runtime_verification``, affected roles/outcomes
  and concrete next actions. Shared runtime prerequisites use an empty role list.
* Scene-only omits policy blockers but still displays its unresolved policy row.
  Required-policy adds policy composition, checkpoint/task/evaluator setup,
  inference, GPU co-residency and per-reset verification gates. Neither report
  claims scene execution currently works through the installed CLI. This bounded
  first inventory assumes generation, visual assessment, repair and prior reads;
  it is not a generic dependency compiler or a policy-free execution admission.

The installed DB compatibility row describes exact numeric IPv4
``bolt://address:port`` and Basic operational credentials only. DNS, routing,
TLS/certificate requirements and other authentication modes remain incompatible,
not automatically downgraded. Installed runtime reads its configured private
file; pipe input during setup is not runtime pipe support. Query runtime and
explicit administration select the **same** ``databases.operational`` credential
slot. Distinct application principal strings do not select different DB logins.
The installed prior-read slot and complete provider-role bootstrap are missing.
Keep administration operator-owned or implement a narrowly reviewed adapter;
never solve compatibility by granting runtime DDL privileges.

``selection_sha256`` hashes canonical JSON (sorted keys, compact separators,
ASCII escapes) of the normalized versioned public selection, including outcome.
Missing roles and role-selection fields become explicit nulls; the optional
credential ``public_id`` retains its supplied shape. No literal value is altered. Changing
a public binding changes the digest. The digest is not a key fingerprint and
cannot detect key rotation, revocation or service drift. This report stores no
checks and is **not a durable lifecycle registry**. Later measured checks need
exact configuration/credential-generation binding and time, fresh revalidation
when bindings change, and separately approved release authority and budgets.

Remaining gates
---------------

Private provider/prior-role setup, installed execution composition, exact prior
recovery, measured model request/image capability, billing/price ceilings,
DB privileges/schema and paired recovery, native calibration/cleanup, and
(required-policy only) policy runtime/reset proofs remain separate work.
Collecting keys is not a prerequisite to continue approved source/isolated work.
No probe or speculative setup/run command is provided by this inventory.

Developer request-envelope seam
-------------------------------

``workflow.request_envelope.RequestEnvelope`` and the optional
``BoundedSceneModels(request_envelopes=...)`` map constrain actual SDK requests
for each approved model role. Refinement continues to use the generation role.
The current callable version supports direct official OpenAI chat completions,
not gateways or automatic provider routing. It does not select a model or price.

Validation covers detached arguments, serialized JSON and final HTTPX request
bytes/headers/route before transport. Text, schema, output and inline PNG limits
are explicit. PNG checks cover structure, CRCs and dimensions, not pixel decoding.
Constructor pings consume their own allowance; rejecting a later assessment does
not undo its earlier ping. Enveloped SDK clients reject public ``copy`` and
``with_options`` cloning, including replacement transports. The absent-envelope
legacy path is unchanged. This is an instance-local supported-callable guard,
not an arbitrary-Python or credential sandbox.

These bounds remain conditional on a trusted conservative all-envelope pricing
attestation. Actual provider rates, account billing, installed profile/grant
binding and live compatibility are not verified. Synthetic HTTP tests exercise
actual generation/refinement/assessment serialization and an HTTPX auth resend;
they do not establish SDK token-refresh behavior or live provider acceptance.
