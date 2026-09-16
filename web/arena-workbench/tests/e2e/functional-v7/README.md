# F0 real API / browser acceptance

**Next manual-research profile: NOT-RUN, held for parent-approved API security
AND UI closure.** See [MANUAL_RESEARCH.md](MANUAL_RESEARCH.md) for the additive
`manual-research-v1` journey, strict firewall/checker, isolated unit evidence and
future gated command. No old profile/proof is replaced; the existing passed
`arena-f0-933680638528` authoring driver remains unchanged. Only isolated harness
units were exercised for this addition (126 Python + 10 builtins-only Node).

**Stopped frontend dependency repair:** see [STOPPED_FRONTEND.md](STOPPED_FRONTEND.md)
for the explicit exact-ID selector, passing isolated typecheck/build and runner
units, and the current genuine Editor integration RED. Full browser authoring
remains withheld pending the UI fix; CSS-only evidence is not acceptance.

**Latest V7 authoring acceptance is FAILED:** see [AUTHORING.md](AUTHORING.md)
for the genuine browser proof, screenshots, exact download bytes, HTTP counts,
strict additive authoring profile and production blockers. The older profiles
and evidence below are preserved, not upgraded or relabelled.

**Historical acceptance remains withdrawn.** `BASELINE.md` and all failed runs
are preserved; no old proof is upgraded. The renewed authorization covers fresh
isolated API load/validate, focused Documents/revision tests and ordinary gated
typecheck/build, never live workflows. The v3 run/ownership envelope now models
the immutable dependency donor separately from the API and discovered live
runtime; API/browser wire proofs remain v2. The original immutable image lacks
`neo4j`. A separately provisioned test-only image now passes actual API
load/validate and strict v3 consistency checks (commands and evidence below).
Security units pass: 99 Python and 6 Node tests, zero skips. No driver is mocked
or copied from a live container. This is not browser or focused backend acceptance.

## Durable focused commands

Run from `/workspaces/IsaacLab-Arena`:

```sh
python3 scripts/run-functional-checks.py security-units --node-units
python3 scripts/run-functional-checks.py api
python3 scripts/run-functional-checks.py backend
python3 scripts/run-functional-checks.py backend isaaclab_arena/tests/test_workbench_editor_revisions.py
python3 scripts/run-functional-checks.py typecheck --allow-frontend-verification
python3 scripts/run-functional-checks.py build --allow-frontend-verification
```

## Focused backend runtime selection and request-model RED

The shared CLI accepts paired `--runtime-image` / `--provision-manifest` in
`api` and `backend` modes only. Backend keyword arguments use those same names.
Selection reuses `run.select_runtime`: immutable ID, manifest validation, and
exact provisioned/base image projection readback precede staging or acquisition.
The proof retains live `runtime_image` / `runtime_id` separately from the
selected test image, saves and hashes the provision manifest, binds exported
Neo4j files to its exact hashes, and checks the inspected pytest container image
before starting it. Unpaired, malformed, mismatched and failed provenance inputs
fail closed. Early selection failures retain a failed proof and verified cleanup.

The exact core-only test selection still performs **no driver acquisition** and
mounts no `/pydeps`; an explicit override is validated rather than ignored.
No changes were made to the API, core implementation, provisioner or checker.
No browser was run, and optional browser/layout forwarding was not added.

Strict TDD runner evidence (all beneath `.runs/`):

- `arena-core-units-e2716159b998`: missing backend keyword support RED.
- `arena-core-units-b36386ec95db`: donor-binding/shared-CLI RED.
- `arena-core-units-8c1e253ad307`: mismatched pytest image readback RED.
- `arena-core-units-0e0d6068740d`: final **76 stdlib tests passed**, no skips,
  failures or errors; staged source unchanged and owned cleanup verified.

Reproduce the sandbox runner/CLI units:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 web/arena-workbench/tests/e2e/functional-v7/test_backend_checks.py --sandbox
```

Actual production request-model RED, not a dependency-availability abort:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run-functional-checks.py backend \
  isaaclab_arena_examples/tests/test_workbench_editor_revision_api.py \
  --runtime-image sha256:e20b3cc8258b793aaf1fe47c130f54e677fa9c0a6427991cfc1045b743162da5 \
  --provision-manifest web/arena-workbench/tests/e2e/functional-v7/.runs/arena-f0-provision-d94aed8076e8/provision-manifest.json
```

`arena-f0-backend-191710c082fd/run-proof.json` records exit 1; its
`evidence/pytest.xml` contains **7 tests, 1 failure, 0 errors, 0 skips**.
`test_revision_save_accepts_an_explicit_retry_key_without_changing_legacy_fields`
fails because `SaveDraft` rejects `idempotency_key="save:test-1"` with Pydantic
`extra_forbidden`. Both inspected donor and pytest containers used the exact
provisioned image. Genuine Neo4j imported; preimport kernel denial passed as UID
1000, all six forbidden counters remained zero, source/artifact hashes and
provision/donor bytes matched, and authoritative cleanup listings were empty.
This is preserved missing-feature evidence, **not API/browser acceptance**.

## Test-only dependency provisioning and actual API proof

No project lockfile, protected Dockerfile, live environment or production tag is
changed. The fixed public wheels are `neo4j==6.2.0` (Python >=3.10) and its sole
mandatory dependency `pytz==2026.3.post1`. Official PyPI JSON and exact SHA-256
are independently checked before any wheel is unpacked. Extras are not installed:

| Wheel | Official PyPI SHA-256 |
| --- | --- |
| `neo4j-6.2.0-py3-none-any.whl` | `b87abdd13a5cc2e3bd51026926c2f20ac38fa3febe98c340520dce19e97388d0` |
| `pytz-2026.3.post1-py2.py3-none-any.whl` | `dd95840dd199baea12d9cc096a1d452caa6596a1c1e4b5f3dbd1541855d5e815` |

Reproduce acquisition/build with a **fresh** acquisition directory:

```sh
python3 -I scripts/provision-functional-runtime.py acquire web/arena-workbench/tests/e2e/functional-v7/.runs/my-fresh-wheel-acquisition
PYTHONDONTWRITEBYTECODE=1 python3 -I scripts/provision-functional-runtime.py build web/arena-workbench/tests/e2e/functional-v7/.runs/my-fresh-wheel-acquisition
```

Acquisition uses stdlib only, HTTPS to official PyPI/files.pythonhosted.org,
fixed pins, bounded reads, no redirects/proxies, and never imports repository or
acquired package code. It preserves official JSON and original wheels separately
from test evidence. Build verifies the exact project dependency declaration,
mandatory wheel requirements, entry bounds, paths, file types and wheel RECORD
hash/size/coverage. Links, special files, traversal, `.pth` hooks and unexpected
package roots fail before extraction. A fresh mount-free, UID-1000/read-only/
cap-drop/network-none probe discovers actual Python 3.12 sysconfig roots. The
generated test-only Dockerfile has one COPY layer, no RUN, no pip/setup execution,
and is built with `--network=none --pull=false` from the immutable base ID using
only an explicit inert tar context. Nothing under `docker/` is touched.

A second isolated probe rehashes all 737 installed wheel files through no-follow
descriptors under actual kernel denial before any package imports. The manifest
binds original base ID/layers, new image ID/layers, pinned wheels, all installed
hashes, declaration/acquisition hashes, recipe hash/image label, readback and
cleanup. `--runtime-image` accepts only an immutable ID plus this manifest; tags,
missing/linked manifests, inconsistent provenance and image projections fail
closed. Live discovery remains `runtime_image`/`runtime_id`; the test image is
separately named `selected_runtime_image`. Both donor and API must use it, remain
distinct from each other and the live runtime, and exported donor bytes must
equal the provisioned Neo4j file manifest. No provenance relabelling is allowed.

The actual provisioned image is:

```text
base: sha256:9af2ecbd69523de79b06a3edb992cba569679ab45ca997adf0d179dbd01883e8
test: sha256:e20b3cc8258b793aaf1fe47c130f54e677fa9c0a6427991cfc1045b743162da5
```

Ordinary API-only command using the retained local manifest:

```sh
python3 scripts/run-functional-checks.py api \
  --runtime-image sha256:e20b3cc8258b793aaf1fe47c130f54e677fa9c0a6427991cfc1045b743162da5 \
  --provision-manifest web/arena-workbench/tests/e2e/functional-v7/.runs/arena-f0-provision-d94aed8076e8/provision-manifest.json
python3 web/arena-workbench/tests/e2e/functional-v7/check_proof.py \
  web/arena-workbench/tests/e2e/functional-v7/.runs/arena-f0-85a1b7ff104b
```

Fresh API proof `arena-f0-85a1b7ff104b` passed: genuine document load, valid/invalid
validation, schema/catalogues, 401/403 guards, zero jobs and all forbidden counters
zero. UID 1000, caps zero, read-only mounts, actual preimport errno 101 denial,
lifespan closed, socket absent and authoritative owned-container cleanup passed.
Units: `.runs/arena-f0-unit-8c9eb8f895`. Provisioning:
`.runs/arena-f0-provision-d94aed8076e8`; public acquisition:
`.runs/neo4j-pypi-acquisition-6.2.0`. Failed TDD runs remain preserved, not upgraded.
The image is retained by immutable ID for repeat checks; no production tag is set.
Hashes prove artifact consistency, not independent authenticity. No browser,
GPU, DB, provider or live workflow execution was performed by this provisioning.

Backend accepts only the two exact revision test paths in `stage.BACKEND_TESTS`,
never arbitrary pytest flags. Source is the descriptor-confined `.py` import
closure plus the original API fixture and reviewed self-contained
`minimal_maple_table_env_graph.yaml`. No conftest discovery, plugin autoload,
checkout config or live state is used. Kernel denial and process/provider/graph
guards precede pytest/repository imports; Git metadata uses the same actual-image
capture adapter. Pytest writes only fresh `/private/pytest` state and evidence.
Success requires actual nonempty JUnit cases, zero failures/skips, zero forbidden
counters, immutable dependency availability, source hashes and verified cleanup.
Its proof scope is focused pytest, **not** F0 API acceptance.

Frontend entries issue exactly `npm run typecheck` or
`npm run build -- --outDir /evidence/dist --configLoader runner` in a fresh owned
nonroot/network-none/read-only sandbox after egress denial and dependency scan.
The installed frontend volume is explicitly trusted mutable input. No install,
dev server or Playwright workflow is run. If tool approval denies a command,
stop that verification; do not rephrase it or bypass the gate. Both ordinary
commands were permitted and exercised; the current frozen snapshot fails tsc
in `job-cancellation.test.tsx` and `position-edit-eligibility{,.test}.ts`.

Browser commands below remain separate reference commands, not blanket workflow
authorization. API-only execution is authorized under the fresh-state boundary:

```sh
python3 web/arena-workbench/tests/e2e/functional-v7/run.py
python3 web/arena-workbench/tests/e2e/functional-v7/run.py --browser
```

After parent integration, opt into the v7 chrome explicitly:

```sh
python3 web/arena-workbench/tests/e2e/functional-v7/run.py --browser --layout v7
```

The v7 check requires a visible `.workbench-chrome`; an ignored query parameter cannot count as v7 acceptance. Default `legacy` is the CPU/browser baseline. No workload-enabling flag is provided.

Each command prints its unique output directory under this folder's ignored `.runs/`. Independently check completed API/browser evidence:

```sh
python3 web/arena-workbench/tests/e2e/functional-v7/check_proof.py <printed-output-directory> --browser
```

Omit `--browser` for API-only runs; an asserted browser run is still checked in full
even if that flag is omitted. Evidence includes `run-proof.json`, fsynced
`ownership.json`, staged source/dependency SHA-256 manifests, exact sanitized Docker
configuration, process preimport denial proofs, real API response projections,
browser screenshot/trace, and final API/lifecycle cleanup proof. Session secrets
must not be included in JSON projections; private browser traces can contain
**fresh test-session** credentials, so `.runs/` is not for publication. Do not
inspect or publish private traces as part of this repair.

The checker verifies **internal consistency of self-authored artifacts**, not
authenticity or trustworthy execution. Reauthoring every consistent artifact and
hash is not an attestation. Independent isolation/execution review remains a gate.

## Isolation contract

- Discover this clone by host bind mapping, then use its installed runtime image by immutable ID, or the separately validated test-only provisioned image above. Reuse the installed frontend dependency volume read-only and a locally present matching Playwright image. API/browser runs use `--pull=never` and perform no installs.
- Persist intended names and run ownership labels **before** Docker creation. Read back isolation before start. No daemon socket inside a sandbox and no `docker exec` of live containers.
- Nonroot UID/GID 1000, supplemental runtime read group 1234, network-none, read-only root/source/dependencies, all capabilities dropped, no-new-privileges, bounded memory/PIDs, no GPU devices. Both API and browser actually attempt an external IP connection and require kernel denial **before repository imports**. A timeout is not proof of denial.
- Stage the API's conservative static Python import closure plus dynamic registry libraries; stage frontend entry-point import closure when requested. The **only YAML source** is `isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml`. No broad checkout, generated environments, live state, research stores, model/data caches or credential mounts.
- Production API import needs `neo4j` even with publication disabled. A mount-free owned immutable-image **dependency donor** probes the actual interpreter's `sysconfig` roots using stdlib under `-I -S`; it never guesses a Python-version path or imports the package. An available unique physical package directory is exported through the bounded source-only/no-follow archive validator. Provenance separately binds source role, donor create ID, source image, discovered live runtime ID and actual preimport probe. All three identities stay distinct. The v3 checker requires donor/API/optional-browser ownership and cleanup, including zero mounts on the donor. Missing bytes fail closed without install, live-container copy or fake modules.
- API state is a fresh, private tmpfs. The browser cannot mount it. A fresh mode-0700 bridge directory carries the API UDS; only the browser's network-none namespace has the loopback HTTP proxy. Nothing is published to the host network.
- Production `create_app`, lifespan/state lease, `Documents`, sessions, Origin/CSRF checks, load/validate/schema/catalogue endpoints and journal remain real. Snapshot construction is deliberately unavailable in trusted harness code. Provider/graph/render construction and network/subprocess attempts are instrumented/denied; default diagnostic, generation, research, publication and managed-retrieval capabilities are off.
- The shim allows only GET/HEAD, session establish/activity/revoke and schema-validation POSTs. Other workload mutations are denied before production dispatch. **No package-triggered OS subprocess is allowed**, including `git version`. Before repository imports, trusted harness code captures `/usr/bin/git version` once from the root-owned, read-only image executable, with fixed clean environment, cwd `/`, two-second timeout, successful status, empty stderr and validated ASCII version output. Genuine GitPython import uses a metadata-only adapter to replay those captured bytes, bounded to two reads; replay reads are not OS processes. Capture, replay count and empty `metadata_subprocesses` are separate proof fields. Warp's CPU-name metadata uses `os.uname()` instead of spawning `uname`.
- On completion, the API closes its genuine lifespan, reports an empty journal, and removes its socket. Cleanup checks exact labels, names and known immutable identities independently, removes only owned containers by ID, and requires successful authoritative listings proving absence. Unknown cleanup is failure. Private tmpfs state disappears with the container; only staged bytes and evidence remain. SIGINT/SIGTERM enter the same cleanup path.

## Acceptance and limits

The intended API test checks unauthenticated rejection and CSRF rejection,
independently derives the fixture's source/view IDs and source hash, compares
loaded and POST-validated results, rejects invalid YAML, obtains real
schema/catalogues, and verifies zero jobs. The repaired browser code now requires
a distinct post-boundary request sequence for each edit and restore, captures
exact outbound JSON/YAML and frozen view ID at the request event, and accepts only
that Playwright Request object's response. Canonical equality and initial embedded
validation are never correlation fallbacks. Final bytes must be copied from the
visible, focused CodeMirror control into a cleared clipboard and equal the staged
fixture exactly. This repaired path has **not** been exercised by an authorized
full browser run. No real API response is fulfilled/mocked.

This is **schema/catalogue/editor acceptance**, not simulation, model execution, physical stability, graph publication or GPU-render acceptance. Source is frozen in a read-only staging tree. The proof reports live files changed since capture separately; it intentionally does not certify full live-tree stability while sibling frontend work is in progress.

## Required v3 envelope / v2 wire contract — consistency, not acceptance

`check_proof.py` is the executable schema; missing fields fail rather than falling
back to legacy proof. All additions below must come from actual observations,
not invented success records. `test_check_proof.py` constructs **synthetic**
contracts solely for verifier regression; never promote them to run evidence.

**API producer/checker boundary:**

- Emit integer `schema_version: 2` and explicit `status: "passed"` in
  `api-proof.json`, `api-final.json`, and `preimport-api.json` only at their real
  successful boundaries. The embedded `api.preimport` must equal the standalone
  preimport file. Keep exact nonempty integer-zero counters with precisely
  `network/provider/graph/render/workload/subprocess` in both API records.
- Preserve `source` (approved relative path), exact `yaml_text`, `document` (actual
  loaded response including source/document_id/YAML/source_hash/validation), and
  `validation_request` (exact `{yaml_text, document_id}` posted). Preserve
  source/view IDs, source and canonical hashes, actual schema/catalogues, invalid
  validation errors, HTTP authentication/CSRF evidence, disabled capabilities,
  empty jobs, and required `metadata_subprocesses: []`. Preserve the
  production schema/catalogue response `schema_version: 1` (distinct from proof
  v2); the checker recomputes their compact sorted-JSON content hashes.
- Require the exact emitted `metadata_capture` fields: `argv: ["/usr/bin/git",
  "version"]`, `cwd: "/"`, integer `timeout_seconds: 2`,
  `before_repository_imports: true`, integer `returncode: 0`, and `stdout`
  matching the producer's ASCII Git-version grammar including its final newline.
  `metadata_replays` must be an integer one or two, matching the genuine fresh
  GitPython import contract and adapter budget, not a subprocess allowance.
  Missing fields, boolean numeric substitutes and contradictory extra capture
  fields are rejected. These records do not independently attest executable bytes
  or authenticity; the actual immutable-executable checks remain producer work.
- Preimport fields are required: UID 1000, kernel-denial errno, zero `caps`,
  `before_repository_imports`, `egress_denied`, `no_new_privileges`,
  `readonly_source_root_deps` all true, and `gpu_devices: []`. Final lifecycle and
  socket-absence observations must be true. Failure paths must never publish a
  passed final record.

**Run/staging producer/checker boundary:**

- Emit integer `schema_version: 3` and status in final `run-proof.json` and
  `ownership.json`; their run/candidates/containers/cleanup/remaining-owned/
  cleanup-errors/cleanup-verification fields must agree without boolean/integer
  coercion. Required `created_ids` and `verified_isolation` maps must mirror
  ownership exactly, cover precisely dependency donor, API and selected-browser role names,
  bind each immutable create ACK to its inspected/cleaned container ID, and mark
  every isolation observation literal `true`. Unknown IDs, missing/extra roles,
  donor/live-runtime/API identity aliases and mismatched images fail acceptance.
- Persist `host_output`, exact sanitized container `labels`, immutable images,
  user, host configuration and mount records. No unexpected mounts, devices,
  published ports, broad binds, privileged/root operation or unbounded memory/PIDs
  are accepted. Source/dependency mounts and the browser bridge must be read-only.
- Require projected `PidMode` and `UsernsMode` to be empty/null, `IpcMode` to be
  `private`, and `VolumesFrom` to be empty/null. Missing fields, host/shared
  namespaces and inherited volumes are rejected for each intended role.
- Each successful cleanup row requires `ownership_verified: true`, `removed:
  true`, and the exact known name/ID. Add `cleanup_verification` with
  `{status: "passed", authoritative: true, label_ids: [], candidate_ids:
  {"<each registered name>": []}}` only after successful authoritative listings.
- Require `cleanup_verified: true` and empty `evidence_errors`,
  `staged_source_hash_errors`, `live_source_hash_errors` and `cleanup_errors`,
  mirrored in ownership. Ordinary recorded live-source changes remain permitted
  under frozen staged-source scope; failed/unsafe live-source hash reads do not.
- Write `source-manifest.json`, mirror it in `source_sha256`, and add
  `staging: {policy_version: 2, approved_fixture: "<approved relative YAML path>",
  manifest_sha256: "<hash of source-manifest.json bytes>"}`. Hash every staged
  source byte; no symlinks or extra unmanifested files. Include the harness
  api/run/stage/checker sources and, for browser mode, browser.mjs and frontend
  main/vite/package/index entrypoints. Preserve staged-source and live-change
  observations; these are not live-tree stability acceptance.
- Write `dependency-manifest.json` exactly equal to run `dependency`, without
  boolean/integer coercion. It contains the separate donor ID/image/role, discovered
  runtime ID, actual successful preimport probe, observed `/site-packages/neo4j`
  path and nonempty file hashes. `dependency-probe.json` is also preserved on
  availability failure. The checker rehashes inert `pydeps` and checks identities,
  images, source path, isolation, read-only mounts and cleanup.
- Copy the actual browser's `frontend_dependencies` into the run record. Browser
  captures installed Playwright `1.58.2` plus SHA-256 of node_modules'
  `.package-lock.json`, `@playwright/test/package.json`, and `vite/package.json`.
  These observations are bound to the discovered mounted dependency volume;
  they do not attest every installed dependency byte.
- Hash `ownership.json`, `source-manifest.json`, `dependency-manifest.json`, all
  API/preimport/final JSON files, and **every evidence file recursively** (including
  built dist assets). Browser mode additionally requires its proof/preimport,
  screenshot, trace, build log and `dist/index.html`. The artifact map cannot be
  empty or omit any required artifact. Hashing private trace bytes does not
  authorize opening their contents.

**Browser contract:** `schema_version: 2`, explicit success and both matching
preimport records; exact source/document identities; monotonic
`validation_exchanges` with raw `request_body`, frozen `request`, response body,
status and `response_request_sequence`; `validation_phases` ordered edit/restore
with `after_sequence < request_sequence` and a newer restore boundary; exact
final editor YAML/hash/visible readback; schema/catalogue/jobs response bodies and
statuses; explicit layout and DOM verification. The checker cross-compares all
of these rather than trusting a canonical-hash-only assertion. A browser run
cannot be downgraded by omitting `--browser` from the checker command.

## Bounded failure tests

The import-safe `request-correlation.test.mjs` uses only Node builtins and the
browser's pure tracker; importing `browser.mjs` does not build or launch anything.
`test_check_proof.py` uses stdlib plus only the checker and private temporary
synthetic fixtures. These tests cover suppressed/delayed/reordered traffic,
request-object identity, immutable byte capture, missing schema/artifact fields,
empty/malformed counters, tampering, resealed contradictions, path/symlink
rejection, source coverage and browser-check downgrade attempts. They are not
substitutes for an authorized isolated integration run.

The approved bounded regression command is:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 web/arena-workbench/tests/e2e/functional-v7/self_test.py --node-units
```

It stages an exact inert allowlist into independently owned nonroot, network-none,
read-only sandboxes, with actual kernel-denial probes before repository imports,
no dependency mounts, and no daemon socket inside. Python suites cover mocked
daemon lifecycle, confined staging, boundary adapters, resealed proof tampering,
producer contracts and real immutable-image GitPython metadata compatibility.
Node uses builtins-only correlation tests, not Vite or Playwright execution.
Archive negatives isolate each path/type/suffix guard: only actual link entries
carry a link target, and otherwise-valid package roots prevent unrelated guards
from masking the intended rejection. Both API-only and browser synthetic proof
fixtures remain verifier tests only, not genuine response/pixel evidence.

These real integration fault commands intentionally exit **1**, preserve failed proof, and must report `remaining_owned: []`:

```sh
python3 web/arena-workbench/tests/e2e/functional-v7/run.py --fault after-create
python3 web/arena-workbench/tests/e2e/functional-v7/run.py --fault preimport-denial
```

If image/dependency discovery or isolation is unavailable, the harness stops rather than weakening the boundary. It never executes the historical `isolated-real/run.py`.
