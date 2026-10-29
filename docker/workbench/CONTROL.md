# Installed control helper: operator prerequisites

This is a fixed-target host helper, not a Docker sandbox. Implementation tests do
not authorize or prove a live deployment, service start, policy load, inference,
API queue recovery, or database operation.

## Trusted launch and installation

Use Linux, a trusted `/usr/bin/env` with `-S` support, and a trusted
`/usr/bin/python3` (3.10+) and its standard library. The executable `control.py`
shebang invokes that absolute interpreter with **`-I -S` before Python starts**.
The equivalent explicit invocation is `/usr/bin/python3 -I -S /trusted/control.py`.
Do not use plain `python control.py`, `python -m`, or import it into a privileged
application. `-I` alone still permits system site hooks. The early built-in-only
`sys` guard refuses both missing flags, including for `install`, but cannot undo
`sitecustomize`/`.pth` execution that occurred before the script was entered.
See Python's [command-line](https://docs.python.org/3/using/cmdline.html) and
[site](https://docs.python.org/3/library/site.html) documentation.

Before the first invocation, stage independently reviewed helper bytes at an
operator-controlled path outside service-writable mounts and verify the review
hash there. Executing untrusted checkout bytes to perform their own hash check is
not a trust bootstrap. The same host operator, interpreter, OS dynamic loader,
Docker daemon and host mount namespace are trusted; neither flags nor the helper
protect against their compromise or concurrent privileged host remounts.

Installation needs an existing owner-private `0700` parent and a new installation
home. The profile must be owner-private `0600`, with independently pinned full
container/image IDs and actual configuration. Startup-capable modes additionally
require reviewed resource limits and startup evidence. After approval, the command shape is:

```text
/trusted/control.py install --home /operator-private/control --profile /operator-private/profile.json --source-sha256 REVIEWED_SHA256
/operator-private/control/control.py inspect --home /operator-private/control
```

The installation creates exact home/state `0700`, IPC `0750`, helper executable
`0700`, and private JSON `0600` permissions (including under umask `077`). Existing
API storage ownership/modes are checked, never recursively repaired. Bootstrap
can create only explicitly approved missing API directories. The operator needs
Docker permission and permission to establish the specified API UID/GID; those
are not granted by this helper.

`serve` binds the owned control UDS without starting services. `bootstrap` also
creates/starts the approved frontend and therefore needs separate explicit live
approval. Keep the home/profile/pairing/receipts outside **all** service mounts;
only its narrow IPC directory is intentionally shared with the frontend. Source
ancestor/symlink/inode aliases of the fixed local Docker socket are rejected.
Installation paths and marker hardlinks are rechecked on installed readback.
Host mount checks use metadata only. The separate startup-code review below
opens only explicitly listed bounded regular source files.

## Private startup contract (not HTTP-selectable)

The existing private profile remains schema version `1`, with one **required**
additional top-level field, `startup_review`. Its exact object keys are `mode`
and `files`, with the observation-only and explicit v2 metadata exceptions below; missing
fields, other extra fields and unknown modes fail closed. There
is no default, fallback, automatic migration or browser-selected mode. The HTTP
Start body remains exactly `{request_id, profile_revision}`; responses expose
neither the review, source paths, argv nor hashes individually.

- `observation-only-v1` is the explicit initial-configuration stage described
  below. It permits pairing and fixed service-state observation, **never Start**.
- `image-baked-v1` retains the strict existing rule: `ReadonlyRootfs` must be
  literal `true`, absolute entrypoint/simple argv and cwd outside mounted paths,
  no module/inline interpreter switches. Mounted data argv is still refused in
  this mode. Review the image's transitive code, environment, symlinks and hooks.
- `operator-reviewed-existing-v1` admits the **exact saved, operator-reviewed**
  existing entrypoint/command/cwd, including `python -m ...`, mounted cwd and
  mounted model-data arguments. `ReadonlyRootfs` must be an actual JSON boolean,
  either `false` or `true`, matching Docker's `HostConfig.ReadonlyRootfs`; integers,
  strings and null are refused. Writable root is not rewritten to read-only and
  is not proof of a safe startup. No container mutation or new image is implied.
- `operator-reviewed-existing-v2` retains that existing-stack startup/code review
  and adds the explicit fresh opaque-mount verification contract below. It does
  not upgrade observation pins or v1 profiles automatically.

For all startup-capable modes each service still has exactly `identity`, `startup_only`,
`offline`, `cached_weights`; the last three must be literal `true` based on
operator review, not discovery guesses. Identity keys remain exactly:
`Id`, `Image`, `User`, `Entrypoint`, `Cmd`, `WorkingDir`, `NetworkMode`, `Mounts`,
`Memory`, `MemorySwap`, `PidsLimit`, `Privileged`, `ReadonlyRootfs`, `EnvSha256`.
`Privileged` remains literal `false`; positive memory/PID limits and equal
Memory/MemorySwap remain required. Full IDs/images, actual user, all exact mount
fields and saved environment digest remain pinned and compared; there is no
same-name replacement or resource-check exemption. Docker-socket ancestor,
symlink/inode aliases and installed-authority/secret mounts remain prohibited.

### Observation-only initial configuration: exact private format

Keep schema version `1` and exactly these top-level keys:
`schema_version`, `origin`, `expected_policy`, `connections`, `services`, `api`,
`storage`, `resources`, `limits`, `frontend`, `startup_review`.
There are no new HTTP fields, frontend mode selectors or implicit fallbacks.
Use this exact private review object:

```json
"startup_review": {"mode": "observation-only-v1", "files": []}
```

`services` still contains exactly `arena`, `neo4j`, `gr00t`. Each service has
exactly the following shape (angle-bracket strings are placeholders, **not**
provisioning input). Replace every known identity field with its actual value;
the zero/null limits shown are permitted only when those are the actual limits:

```json
{
  "identity": {
    "Id": "<full-lowercase-64hex-container-ID>",
    "Image": "sha256:<full-lowercase-64hex-image-ID>",
    "User": "<actual-Config.User-string>",
    "Entrypoint": null,
    "Cmd": null,
    "WorkingDir": "<actual-Config.WorkingDir-string>",
    "NetworkMode": "<actual-HostConfig.NetworkMode-string>",
    "Mounts": [{"Type": "bind", "Source": "<actual-absolute-host-path>", "Destination": "<actual-absolute-container-path>", "RW": true}],
    "Memory": 0,
    "MemorySwap": 0,
    "PidsLimit": null,
    "Privileged": false,
    "ReadonlyRootfs": false,
    "EnvSha256": null
  },
  "startup_only": false,
  "offline": false,
  "cached_weights": false
}
```

- All three attestation flags must be literal `false`; true, integers, strings
  and null fail. `Entrypoint`, `Cmd`, `EnvSha256` must be explicit null, meaning
  **unobserved**, not empty argv/environment or reviewed-safe metadata.
- `Memory` and `MemorySwap` may be integer zero or the existing positive bounded
  integers and must still equal each other; `PidsLimit` may be null or positive.
  No negative/unlimited aliases or boolean-as-zero coercion are accepted.
  `ReadonlyRootfs` is the actual boolean; `Privileged` must remain literal false.
  User (including Docker's empty default-root string), normalized cwd (or empty),
  nonempty network mode, every mount and both full IDs remain pinned. Actual
  observations compare canonical identity bytes, not boolean/integer equality.
- `files` must be empty in this minimal mode: no mounted startup code is read,
  hashed, imported or executed. The Docker projection does not request
  `.Config.Env`, `.Config.Entrypoint`, `.Config.Cmd`, whole Config/container
  objects, or healthcheck/error output. It requests only known identity fields
  and `.State.Status`, then supplies the three explicit null metadata fields.
  Environment credentials are neither retrieved nor hashed.
- Other profile objects retain their exact existing schemas and validation:
  `connections` = `{neo4j_uri, neo4j_database, gr00t_host, gr00t_port}`;
  `api` = `{uid, gid, repo, state, socket, environment}`;
  `storage` = `{ipc_host, state_host, create}`;
  `resources` = `{min_ram_available_bytes, min_gpu_free_mib, reviewed_until}`;
  `limits` = `{docker_seconds, startup_seconds, receipts}`;
  `frontend` = `{image, uid, gid, memory_bytes, pids_limit, name}`.
  Resource settings are inactive, not capacity attestation; an expired positive
  `reviewed_until` is allowed. `api.environment` may be `{}`. No GPU, model,
  provider or database probe is performed. Expected policy remains exactly
  `nvidia/GR00T-N1.6-DROID`, a requested policy, not proof of a loaded model.

Install and `serve` can pair and observe actual stopped, unbounded Neo4j/GR00T
containers without changing them. Existing approved API IPC/state directories
must still satisfy the guard; missing or changed prerequisites report unknown,
not relaxed ownership or automatic repair. `bootstrap` remains the separately
authorized **fixed frontend only** create/start path and approved directory
preparation; even its inspect projection omits environment/argv in this mode.
It does not start a research container or execute the API supervisor.

Every observation reports `startup_allowed: false` and `api: "unknown"`, even
when Arena is running. The existing Arena API may be observed separately through
its own interface; unknown here is not evidence that it is stopped or unhealthy.
The helper never calls fixed API `status` or `ensure-paused` in this mode.
A schema-valid Start returns HTTP `403 {"error":"startup_disabled"}` before
Docker inspection, resource checks, task dispatch or receipt reservation, even
with a stale revision or retained request ID. Injected fields still return 400;
Host/Origin/session/CSRF validation is unchanged. Current profile drift cannot
enable the installed controller's pinned startup capability. Unknown receipts
remain queryable without reconciliation or reissue.

This is not startup approval, readiness certification or a generic manager.
To enable Start later, independently review real startup/environment/code and
bounded resources, then install a new explicit startup-capable profile/revision;
do not toggle browser fields, forge true flags, refresh pins automatically or
discard ambiguous receipts. Docker-socket and installation/private-secret mount
exclusions, isolated helper launch, singleton, pairing, IPC/state modes and
receipt protections are unchanged.

### Observation-only opaque mount metadata

A native host operator may lack traversal permission on a saved mount `Source`
(for example a named-volume parent). Do not chmod/chown that parent, read its
contents, silently ignore EACCES, or grant startup approval to install an observer.
Only `observation-only-v1` accepts the optional, static private `mount_metadata` list:

```text
"startup_review": {
  "mode": "observation-only-v1",
  "files": [],
  "mount_metadata": [
    {"Source": "<exact-saved-Mounts.Source>", "st_dev": <actual-st_dev>, "st_ino": <actual-st_ino>}
  ]
}
```

This is shape only, not provisioning data. The parent/operator must obtain the
actual leaf device/inode with an **explicitly authorized, stat-only, read-only
bind preflight** of each exact saved Source. Use a trusted fixed stat operation,
not a research container entrypoint, recursive traversal, directory listing,
content read, model/database probe, environment/argv read or permission change.
The operator must verify the exact host binding and its separation from the
Docker socket and installation/private ancestors. Do not assume a device number
from an unrelated/remote filesystem or container namespace identifies the host
inode; confirm that the read-only bind reports the host filesystem's same pair.
An inability to obtain trustworthy comparable metadata is a blocker, not an
invitation to invent pins. The helper performs no Docker metadata-preflight
command during install, HTTP handling or ordinary observation.

- Each entry has exactly `Source`, `st_dev`, `st_ino`. Source must be the exact
  normalized absolute string of a known service mount (bind or named volume),
  not a destination, parent, alias spelling or foreign path. One entry per
  distinct Source; no duplicates, extra keys or automatic discovery. The list
  is bounded to 128 entries. `st_dev` is a JSON integer in `[0, 2^64)` and
  `st_ino` in `(0, 2^64)`; booleans, floats, strings and null are refused.
- Entries may be omitted for accessible Sources. An opaque Source without its
  exact entry still fails closed with PermissionError. Both v1 startup-capable
  modes reject the field entirely, **even an empty list**. Empty `files`, false
  attestations, null unobserved identity fields and unconditional Start denial
  remain mandatory. Metadata pins are never startup-code evidence.
- Only a **PermissionError from that Source's stat** activates its pin. Missing
  Sources and other I/O errors with pins fail; target permission errors and
  later resolve/stat failures on otherwise accessible Sources do not activate
  fallback. Accessible pinned Sources must match their actual pair on validation,
  installed readback and every observation, including cached observations.
  Drift fails instead of refreshing the pin.
- Lexical containment checks remain in both directions for the installation.
  The pinned pair is compared against actual accessible protected target and
  lexical/resolved ancestor metadata, detecting socket/installation bind aliases.
  Visible symlink components of pinned Sources are refused. Accessible Sources
  retain realpath and inode checks, including the reverse installation exclusion;
  opaque Sources also check visible source ancestors for reverse aliases. Target
  stat failures other than absence fail closed. No mount contents are opened.
- The complete list is bound into `profile_revision` and the installed private
  profile digest. HTTP cannot supply or update it; Start remains 403 before
  inspection, dispatch, probes or receipt reservation. Metadata does not grant
  any new filesystem permissions or enable API supervisor execution.

**Residual trust:** a one-time metadata preflight is **not immutable or atomic**.
The helper cannot reconstruct hidden source ancestry, reject a hidden symlink
by inspection, or detect an opaque Source rebound/replaced after preflight.
Opaque reverse-ancestor separation therefore also relies on the operator's
binding review, not just a leaf pair. Docker/host administrators and the host
mount namespace were already trusted. Keep bindings stable; any binding or
hidden-ancestry change requires independent re-review and a new private profile,
never automatic pin refresh. This limited observation-only trust does not relax
normal startup authority, and the fallback **never grants Start**.

### Explicit startup-capable v2 opaque mount verification

This is a private operator-reviewed contract, not an additional global approval
gate or browser capability. Existing v1 and observation-only behavior above is
unchanged. Keep the profile's `schema_version: 1`, exact top-level keys and exact
service identities. The **exact four** v2 `startup_review` keys are:

```text
"startup_review": {
  "mode": "operator-reviewed-existing-v2",
  "files": [<the independently reviewed code entries specified below>],
  "mount_probe_image": "sha256:<full-lowercase-64hex-cached-image-ID>",
  "mount_metadata": [
    {"Source": "<exact-known-Mounts.Source>", "st_dev": <actual-host-device>, "st_ino": <actual-host-inode>}
  ]
}
```

Both metadata fields are required, even if the list is empty. Each entry has
exactly `Source`, `st_dev`, `st_ino`, using the same bounded integer ranges and
known-Source/duplicate restrictions as observation metadata. Commas in v2 pinned
Sources are refused to prevent Docker `--mount` syntax injection. No foreign
Source, destination, parent alias, tag, digest coercion or automatic discovery is
accepted. Entries are mandatory for opaque Sources; accessible Sources may omit
them, but any supplied accessible pin must still match. The probe image must
already be cached and independently trusted to provide `/usr/bin/stat`; its exact
image ID and absence of image-declared volumes are checked before every probe.
The reported deployment candidate is
`sha256:dfb492e9739a7aaac3a6579e53a02ab49f605907d516a3f74e06caf6002c7f5f`;
implementation tests did **not** inspect or run that image.

Installation verifies reviewed helper bytes before any probe. Installed readback
authenticates the helper and private profile digests before interpreting mount
authority or reading declared code. The server acquires its singleton before
probing. A fresh `verify_mount_sources` pass runs at install/readback, controller
admission and immediately before actual fixed service starts and both API execs.
Only a **Source stat PermissionError** permits a probe; absence, other I/O errors,
target errors and accessible drift fail closed. Reviewed code remains directly
readable with no-follow bounded code checks: metadata cannot admit inaccessible
code. Each pass compares fresh stat output against installed expected pairs;
it never learns/replaces pins or persists successful observations as authority.
One mapping per pass serves all protected ancestor comparisons, not one probe
per ancestor. Lexical containment, visible symlinks, protected target/ancestor
inode aliases and visible reverse source-ancestor aliases remain excluded.

The only new Docker effect is a temporary **stat-only** container for each exact
opaque Source. It uses one readonly bind at `/arena-mount-source`, overrides
entrypoint with `/usr/bin/stat`, and supplies only `--format=%d %i --` and that
fixed target. There is no shell, mount-content read, directory listing, image
pull, image volume, socket bind, published port, service exec or model/database
operation in this adapter. Fixed constraints are UID/GID `1000:1000`, workdir `/`,
`--pull=never`, network `none`, read-only root, all capabilities dropped,
no-new-privileges, restart `no`, disabled healthcheck, **64 MiB memory and equal
swap limit**, and **32 PIDs**. The operator must review the image's actual stat
binary, libraries and environment; pinning an arbitrary image does not make it
trusted.

Create and attached start are separate. An unpredictable name and ownership
label are retained with the full returned ID; ownership is read back before
start and cleanup. Lost create ACKs use only that exact name/label pair for
bounded discovery, never a service name. Cleanup gets a separate **two-second
total** budget even after the verification deadline, verifies ownership, removes
only the exact ID, and verifies absence. Unknown ownership, lookup ambiguity,
nonzero stat exit, malformed output, failed/expired cleanup and unproved absence
never authorize startup. Create-ACK loss is still a failed verification even if
cleanup succeeds. Unresolved cleanup retains ownership and disables subsequent
v2 verification in that adapter, including if Sources become host-accessible.
Concurrent probes serialize ownership within their deadlines. **Do not restart
the helper merely to clear an unresolved probe**: investigate the retained
name/label/ID and daemon state first. In-memory ownership is not a crash journal;
abrupt helper/host death can leave a bounded stopped/stat-only container requiring
operator cleanup. No cleanup of research containers is added.

All Sources share the verification's `limits.docker_seconds` budget (at most 15
seconds), nested inside the current observation/startup deadline. Observation's
second guard shares its original deadline, rather than resetting it: eight
seconds for v2 fresh probes/API status, unchanged two seconds for legacy modes.
Cached service labels never supply mount authority: their guard still verifies
fresh metadata, so v2 cached polls can incur probe cost. Cleanup may extend wall
time by its independent budget; filesystem/OS hangs are not subprocess bounds.

**Residual trust is explicit:** a leaf device/inode pair does not prove hidden
ancestry, hidden symlinks, hidden reverse aliases, or stable Docker binding after
the check. Host/daemon administrators, mount namespace, mount writers, cached
image and runtime remain trusted. This is not atomic check-and-start/exec or
writable-layer/transitive-code attestation. Maintain reviewed bindings; changes
require independent review and a new profile, never automatic repinning.

For the intended existing stack set private connections and API settings to:

```json
"connections": {"neo4j_uri":"bolt://127.0.0.1:7688", "neo4j_database":"neo4j", "gr00t_host":"127.0.0.1", "gr00t_port":5559},
"api": {"uid":1000, "gid":1000, "repo":"<existing-api-repo>", "state":"<existing-api-state>", "socket":"<existing-api-socket>", "environment":{"ARENA_WORKBENCH_GR00T_PORT":"5559"}}
```

These fragments are shape/examples, not replacement values for independently
reviewed graph settings, paths, code evidence or saved identities. The required
`connections.gr00t_port` accepts only JSON integers **1–65535**, never booleans or
strings; host stays exactly `127.0.0.1`. The optional API environment value must
be canonical positive decimal **1–65535** and match that connection when present.
Set `5559` explicitly for this existing stack, not `5555`; the helper does not
discover or mutate ports and never restarts a healthy API to change environment.

After independently reviewing/staging the new helper and profile, use the same
isolated `install --home NEW_OWNER_PRIVATE_HOME --profile REVIEWED_PROFILE
--source-sha256 REVIEWED_SHA256`, then installed `inspect --home ...` command
shapes above. A new home/profile revision does not authorize deleting old
receipts: preserve and investigate unresolved operations. Unlike observation
mode, v2 install/inspect/serve can now create the constrained temporary stat
probes, **not** start research services automatically. HTTP Start remains exactly
`{request_id, profile_revision}`; pairing, cookie/CSRF, exact receipts, recovery,
no queue release and no healthy-API restart remain unchanged. No install or live
command in this section was executed by the implementation agent.

### Exact reviewed source evidence (startup-capable modes)

`files` is a list of **3–32** explicitly reviewed **host-backed code files**, not
a directory, glob, model manifest or recursive scan. Every entry has exactly:

| Key | Private value |
| --- | --- |
| `service` | `arena`, `neo4j`, or `gr00t` |
| `container_path` | Absolute normalized mounted code path |
| `host_path` | Absolute normalized exact host file mapped by that service's bind mount |
| `sha256` | Independently reviewed lowercase 64-hex SHA-256 of that file's bytes |
| `device` | Actual host `st_dev`, nonnegative JSON integer, not boolean |
| `inode` | Actual host `st_ino`, positive JSON integer, not boolean |

The following is **shape only**, not executable provisioning input; placeholders
must be replaced by the parent/operator's reviewed evidence:

```text
"startup_review": {
  "mode": "operator-reviewed-existing-v1",
  "files": [
    {"service":"arena", "container_path":"<api.repo>/docker/workbench/runtime.py", "host_path":"<approved-repo-source>/docker/workbench/runtime.py", "sha256":"<reviewed-64hex>", "device":<st_dev>, "inode":<st_ino>},
    {"service":"arena", "container_path":"<api.repo>/docker/workbench/workbench.py", "host_path":"<approved-repo-source>/docker/workbench/workbench.py", "sha256":"<reviewed-64hex>", "device":<st_dev>, "inode":<st_ino>},
    {"service":"arena", "container_path":"<api.repo>/docker/resource_limits.py", "host_path":"<approved-repo-source>/docker/resource_limits.py", "sha256":"<reviewed-64hex>", "device":<st_dev>, "inode":<st_ino>}
  ]
}
```

Those three API-chain entries are mandatory **in all startup-capable modes**, because even the
strict image-baked service mode executes this mounted non-root API chain. They
must map through the approved Arena `api.repo` bind; overlapping/shadow mounts,
unmapped/volume-only paths, duplicate service/path entries and mismapped host
sources fail. Add every directly mounted startup-code file identified by the
operator review (for example a separate host-backed shell wrapper). Simple
absolute/relative `.py`/`.sh` argv, `--script=...` and mounted path entrypoints
require corresponding entries. This is not a shell/module resolver: the
operator must also enumerate mounted module sources and wrappers reached through
PATH, shell expressions, imports, hooks or indirection. The helper does not
execute or import reviewed host source to find dependencies.

The minimal reader supports `.py` and `.sh` source only, maximum **262144 bytes
per file** (at most **8388608 bytes** of accepted content per verification pass).
Hidden components and model/data/secret/cache/weight path components are refused;
model binaries, credentials and journals are never review inputs. The operator
must verify that the listed sources really are code, not relabeled sensitive
files; suffix checks cannot classify arbitrary content. No model-directory reads,
recursive traversal or automatic hashing/discovery command is provided. Host
paths cannot contain symlinks, including parent components. Reads use directory-
relative `O_NOFOLLOW`, require singly linked regular files, check device/inode
before content, bound the read, compare SHA-256 and detect observed read-time
changes/path replacement. A same-size edit with restored mtime still fails the
hash; replacement with identical bytes but a different inode still fails.

The entire review, mappings, hashes and inode expectations are part of canonical
`profile_revision`. Install validates sources before creating installation state;
installed readback verifies the pinned private profile before source reads.
Startup rechecks all listed files before service effects, and the Docker adapter
rechecks them immediately before **both** fixed `status` and `ensure-paused` API
execs. Observation never executes drifted API code or reconciles unknown receipts
from invalid evidence. Cached observations may retain earlier service labels,
but do not bypass source admission or authorize effects. Missing/changed source
blocks rather than updating hashes, copying files or restarting anything.

### Operator review and trust boundary

The parent/operator reviews the exact private profile format/evidence before
provisioning; this is not another global user-approval gate for implementation.
Record actual saved argv/cwd/data locations and prove startup-only/offline cached
loading by review. Do not set a flag merely because a container already exists.
After an intentional source edit or replacement, independently review the new
bytes/mapping/inode and install a newly reviewed profile/revision; never refresh
pins automatically or erase ambiguous receipts to retry. Investigate retained
unknown operations against their original revision. No deployment steps in this
runbook have been executed by the implementation tests.

**Remaining trusted assumptions:** Docker/container administrators, the runtime,
writable container layers, host OS/mount namespace and mount writers remain
trusted. Listed source hashes are **not** writable-layer attestation, image
content inspection, complete transitive-code attestation, interpreter/module
lookup verification or an atomic check-and-exec guarantee. An administrator or
mount writer can modify code after the last check; a running container may retain
an older bind after a host remount. Keep approved mappings stable. Operators must
review unlisted transitive runtime code, environment hooks and startup behavior;
a hash does not prove offline safety or no research effects.

Browser Start uses only `docker start <exact-saved-ID>` and the fixed non-root
API runtime `status`/`ensure-paused --start-paused` execs. It never invokes host
`run_docker.sh` or `run_gr00t_server.sh`, a user-selected shell or argv, nor
pulls/builds/recreates/downloads by default or substitutes model/database data.
It does not restart/reconfigure a healthy API or resume queued work. Separate
explicit host-only frontend bootstrap retains its previously approved cached-
image create/start path; it is not part of browser service Start.

In explicit v2 mode only, fresh mount admission also uses the constrained
temporary stat probes described above; this is not general new-service authority.

### Private API settings

The private `api.environment` allowlist accepts the two lowercase 64-hex policy
pins (`ARENA_GR00T_CHECKPOINT_SHA256`, `ARENA_GR00T_CONFIG_SHA256`), a positive
decimal GPU headroom budget (`ARENA_WORKBENCH_GPU_MIN_FREE_MIB`, up to ten
digits), and optional full `GPU-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` device UUID
(`ARENA_WORKBENCH_GPU_UUID`). These are explicit nonsecret operator settings,
not browser inputs, reservations or automatically chosen defaults. They are
forwarded on the fixed API execs; a healthy existing API is not restarted
or reconfigured. Visibility remains inherited from the approved container.
The readiness worker requires an already provisioned execution-lease file;
Check does not create it. Missing configuration leaves resource readiness
unknown rather than implying sufficient GPU capacity.

The allowlist also accepts `ARENA_WORKBENCH_GR00T_PORT` with the canonical port
and private-connection matching rules above.

## Observation and interrupted writes

Each HTTP observation shares a two-second total Docker subprocess budget across
all inspections and nested API status calls. The single-threaded HTTP server
reuses only service/API observations for a two-second cooldown after completion,
so queued polls do not each spend a full Docker budget ahead of Start or revoke.
Receipts/authentication are not cached; cached observations never reconcile an
unknown operation to completed. Starts still recheck the exact targets before
effects. These are application subprocess bounds, not guarantees against an OS
or filesystem hang. HTTP mutation handling remains serialized; no thread-per-
request authorization race was introduced.

Under the singleton/writer lease, a regular, owner-private, singly linked
`.pending` marker left by an interrupted replacement is discarded, never
promoted. Only the committed marker authorizes recovery. A retained `starting`
receipt becomes `unknown`; ambiguous starts/creates are not resent. Symlink,
hardlink, foreign-owner or wrong-mode pending files fail closed for operator
investigation. This shared writer covers receipts, pairing, frontend, profile and
installation markers. A partially completed initial installation without a
valid manifest still requires operator investigation, not automatic adoption.

## Evidence boundary and remaining deployment checks

Host verification commands (no live service calls):

```text
python3 -m unittest discover -s docker/workbench -p test_control.py
python3 -m unittest discover -s docker/workbench -p test_workbench.py
pre-commit run --files docker/workbench/control.py docker/workbench/test_control.py docker/workbench/CONTROL.md
```

The compatibility implementation was developed with observed RED→GREEN cycles:
missing mode support, missing API-chain mapping enforcement, same-metadata wrapper
byte drift, each API-chain file before status/paused exec (including drift during
identity inspection), stale install/readback, unlisted directly mounted scripts,
module argv in mounted cwd, drift at the final pre-start inspection, and changed
private-profile read ordering. Parent integration also checks the actual repository
API import-chain paths rather than assuming neighboring files. The prior startup-capable host runs passed **46 control tests**
and **24 launcher tests**, with scoped pre-commit passing. Negative regression
coverage includes HTTP mode/source injection, literal-boolean enforcement,
source mapping/digest/revision binding, missing/symlink/hardlink/special/oversize
files and identical-byte inode replacement. Existing security groups remain:

1. Docker socket ancestor/symlink/inode-alias exclusion.
2. Installed authority/private-secret mount and hardlink exclusion.
3. Private orphan `.pending` recovery without promotion or blind reissue.
4. Executable `-I -S` startup and the guard before non-builtin imports.
5. Exact private modes under umask `077`, no storage permission repair.
6. One overall observation budget/cooldown and bounded exact retained receipts.

Observation-only verification adds seven host tests covering safe projected
inspection (including frontend bootstrap), explicit null metadata without any
hash call in the adapter, install/pair/GET/revoke over an owned UDS, immutable
startup denial with current-profile drift and HTTP injection, type-exact known
identity comparison, mount/IPC exclusions, and retained receipt non-reissue.
The final observation-mode run passed **53 control tests** and **24 launcher
tests**; scoped pre-commit passed. Synthetic research state stayed unchanged,
with no API supervisor, resource/GPU/provider/model/database calls or research
starts; only the separate frontend-bootstrap fixture permits fake create/start.
No live inspection, deployment or service changes were performed.

Opaque-source regression coverage adds eight host tests: synthetic EACCES with
real temporary outside/protected inode pairs; install/readback without source
reads or Docker probes; exact schema/mapping/type rejection; accessible drift
even during cached observation; source-only PermissionError fallback; lexical
and visible symlink exclusions; refusal outside observation mode; and installed
UDS pairing/GET/Start/injection/profile-drift/revoke with an opaque Source. The
expanded run passed **61 control tests** and **24 launcher tests**. These tests
use injected permission errors rather than changing live host permissions and
do not perform the operator's actual metadata preflight or installation.

V2 verification passed **80 control tests** and **24 launcher tests**. Observed
RED→GREEN cases covered configured ports, the opaque install/readback/Start path,
stat-only Docker adapter, final exec/start mount admission, shared verification
and second-observation-guard deadlines, concurrent ownership serialization,
unknown-cleanup admission and singleton-before-probe ordering. Negative fixtures
cover foreign/duplicate/malformed Source/image contracts, inaccessible code,
protected aliases and visible symlinks, fresh and accessible inode drift, stat
output/exit failures, create ACK loss, ownership mismatch, ambiguous discovery,
cleanup timeouts and unproved absence. All Docker subprocess boundaries are synthetic;
no actual Docker command is invoked. An additional disposable Linux child really
runs as **UID/GID 1000**, receives EACCES on a root-owned `0700` temporary opaque
parent, and succeeds through mock-backed install/readback/fixed Start with port
`5559`. Only its disposable fixture ownership is changed. Existing observation
UDS/403/no-probe and receipt/API-healthy-restart protections remain covered.

Host stdlib tests use synthetic Docker records, owned temporary sockets/files
and an actually terminated disposable marker writer. Owned-UDS tests exercise
queued observation, Start acceptance and session revocation; they do not start
Docker services. Runtime argv/AST/mocked tests are **not evidence that the actual
API queue remains paused**. Before deployment acceptance, separately approve and
exercise cold frontend/API recovery and retained queued-work behavior through
the real API, preserve existing state/keys/services, verify graph credentials in
the actual worker, deploy/verify the intended policy wrapper and manifests, and
run separately approved protocol/transport/inference and GPU checks. No live
Docker inspection of saved environments or real startup is part of these tests.
