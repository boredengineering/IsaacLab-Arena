# Explicit stopped frontend dependency selection

**Dependency discovery, isolated typecheck and build are repaired and independently
reviewed. The historical Editor RED below was subsequently fixed; the genuine
authoring browser snapshot now passes. See [AUTHORING.md](AUTHORING.md) for current
evidence and remaining deployment/research/runtime boundaries.**
No production/API/UI files or authoring-v1 checker semantics were changed by this
repair. The shared frontend was not started, restarted, exec'd into, or queried for
logs/environment. No packages were installed and no infrastructure was restarted.

## Runnable commands

From `/workspaces/IsaacLab-Arena`, ordinary authorized verification:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run-functional-checks.py typecheck \
  --allow-frontend-verification \
  --frontend-dependency-container 964ddf2e645854708368230ff1770495df6f94c2ecca22b17c7d01ebc611f97d
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run-functional-checks.py build \
  --allow-frontend-verification \
  --frontend-dependency-container 964ddf2e645854708368230ff1770495df6f94c2ecca22b17c7d01ebc611f97d
```

The existing machine-local focused runner also accepts the same explicit selector:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 /tmp/arena-functional-frontend.py \
  --frontend-dependency-container 964ddf2e645854708368230ff1770495df6f94c2ecca22b17c7d01ebc611f97d \
  --preflight-only
PYTHONDONTWRITEBYTECODE=1 python3 /tmp/arena-functional-frontend.py \
  --frontend-dependency-container 964ddf2e645854708368230ff1770495df6f94c2ecca22b17c7d01ebc611f97d \
  src/editor-library.integration.test.tsx src/editor-revision-save.test.tsx \
  src/editor.test.tsx src/app.test.tsx
```

`/tmp/arena-functional-frontend.py` is a local focused Vitest helper, not a durable
checkout entry or a substitute for authoring acceptance. It still refuses arbitrary
npm/build/browser flags. The checkout's typecheck/build CLI is the durable entry.
The selector is also wired through `api --browser` and `run.py --browser`, but **do
not run full authoring until the pending UI fix is complete**. Then add this selector
to the existing paired runtime-image/provision-manifest command in `AUTHORING.md`;
keep that profile's normal checker and requirements unchanged.

Reproduce sandboxed regression suites without frontend dependencies:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run-functional-checks.py security-units
PYTHONDONTWRITEBYTECODE=1 python3 web/arena-workbench/tests/e2e/functional-v7/test_backend_checks.py --sandbox
```

## Selection and trust contract

- The explicit token must be the literal lowercase 64-hex ID; names, prefixes,
  uppercase, whitespace and empty values fail before Docker metadata discovery.
- `docker inspect --format` queries only that exact ID. Its allowlist includes ID,
  image ID, `State.Status`, `State.Running`, and mounts at `/app` or
  `/app/node_modules`. No Config.Env, commands, arbitrary labels or full inspect
  records are requested. An unknown/replaced ID never falls back to a name or
  another running frontend.
- Readback must match the ID, report `exited` and `Running=false`, contain a
  SHA-256 image ID, exactly one `/app` bind from this discovered host clone's
  `web/arena-workbench`, and exactly one named volume at `/app/node_modules`.
  Missing/duplicate/ambiguous volumes and invalid volume names fail closed.
- The observed ID/status/image/mounts are recorded as `frontend_dependency_origin`.
  The image ID identifies the stopped container's image, **not the dependency
  bytes**. The installed volume is **trusted mutable input**, scanned before
  package imports and mounted read-only in the owned sandbox. Another authorized
  writer could mutate it; this is not immutable dependency provenance.
- Omitting the argument keeps the original running-only official discovery and
  legacy defaults. The local focused helper also retains its original stricter
  single-frontend rule. No stopped container is automatically adopted.
- `discover_frontend` does not need a runtime or Playwright image. Typecheck/build
  use it directly. `discover(root, browser=False)` and backend/core paths remain
  frontend-independent; an explicit frontend selector is rejected in those modes.
- Network-none, UID 1000, read-only source/root/dependencies, cap-drop,
  no-new-privileges, GPU denial, preimport egress checks and exact owned-ID cleanup
  remain in force. Only newly created owned containers are started or exec'd into.

Actual origin readback was the specified ID, status `exited`, image
`sha256:15e9e49b09da1c7895676b9b2dfbe44719157d4e6e9aac8345499a5ba109c03c`,
volume `arena-wb-6e74675cd31c_frontend_deps`. A metadata-only call to the official
browser discovery also resolved the approved installed Playwright image
`sha256:6446946a1d9fd62d9ae501312a2d76a43ee688542b21622056a372959b65d63d`;
it did not launch an API or browser.

## Genuine evidence

All paths below are under this folder's `.runs/`; failed snapshots remain intact.

| Evidence | Result |
| --- | --- |
| `arena-f0-unit-2f7d1a6ae5` | TDD RED: missing explicit discovery parameter |
| `arena-f0-unit-430e15baa1` | First positive selection GREEN |
| `arena-f0-unit-5c49c9f54f` | TDD RED: invalid origin/ID/scope accepted or validated too late |
| `arena-f0-unit-135ed9e7ab` | Strict origin negative cases GREEN |
| `arena-f0-unit-c322514f03` | TDD RED: missing frontend-only seam and npm forwarding |
| `arena-f0-unit-bc8e2876cc` | Frontend-only discovery/forwarding GREEN |
| `arena-core-units-179491ef82e3` | TDD RED: shared CLI and browser entry lacked selector |
| `arena-core-units-d1f8e126c53f` | **87** runner/CLI/lifecycle units passed, zero failures/errors |
| `arena-f0-unit-f172fdf1a5` | **112** security/contract units passed, zero failures/errors/skips; includes existing authoring checker units |
| `arena-functional-frontend-c51bfbcb2bcf/proof.json` | Actual final-helper preflight passed, no package/test/browser execution |
| `arena-f0-typecheck-47c66c19676f/run-proof.json` | Ordinary `npm run typecheck` passed, exit 0 |
| `arena-f0-build-869071816720/run-proof.json` | Ordinary production build passed, exit 0; output under `evidence/dist` |
| `arena-functional-frontend-087865b72d67/proof.json` | Actual focused Editor/App Vitest **RED: 189 passed, 3 failed, 192 total** |

The three failures are `editor-library.integration.test.tsx`'s retained-save cases
for **missing source**, **invalid source**, and **pending draft recovery**, at
line 291 in that frozen snapshot: the **Check saved receipt** button remains
disabled when expected enabled. This is an exercised component failure, not a
missing-dependency abort. No UI fix was attempted here. Other Editor (85),
revision-save (48), and App (14) tests passed; Library integration had 42 passes
and the three failures. These mocked-transport/jsdom tests are not real-browser
or real-API authoring acceptance.

Successful frontend preflight scanned 11,373 dependency entries before repository
imports with kernel egress denial. Typecheck/build additionally record
`ENETUNREACH`, UID 1000 and unchanged frozen staged source/artifact hashes. Build
emitted existing nonfatal outDir/chunk-size warnings. All listed final executions,
including the failed Editor test run, recorded authoritative cleanup with zero
remaining owned resources and no cleanup errors. Each run captured its own source
snapshot; no same-snapshot or live-tree full acceptance claim is made.

## Independent review of the CSS ad-hoc runner

Reviewed `/tmp/arena-mobile-css-check.py` and its retained records, without adopting
or rerunning it as the official harness. `arena-mobile-css-bbc522e0d551` retained a
failed run; `arena-mobile-css-284ad41effc9` records **30 passing tests across four
CSS/chrome/layout files**, a successful dependency/egress probe, and authoritative
empty cleanup. That is useful **scoped structural CSS/jsdom evidence**.

It is not trusted full acceptance: it substitutes a `docker ps -a` prefix filter
into `running_metadata`, does not validate an operator-provided exact full ID or
record/require stopped state, and hardcodes the expected dependency-volume name.
It lacks the official full source/artifact binding and authoring journey checker;
its main block also lacks the focused runner's explicit interrupt handling. No
browser layout/overflow measurement, durable Save journey, real API validation or
full authoring result follows from those 30 passes. Its observed actual ID/image
and cleanup records are retained, not discarded or relabelled. The official
repair reuses only the established isolation helpers, not this discovery bypass.
