# Bounded manual research — isolated journey passed

**Execution checkpoint:** parent ran `manual-research-v1` after API-security,
draft-code and v1/v2 checker closure (`deleg_7a5658ff`). Fresh run
`arena-f0-972cb716457b` passed the real browser/API journey and strict v3 checker.
It performed one editor save and two numbered research saves, exact Open, reload
and explicit v2 draft recovery; jobs and all six forbidden counters stayed zero.
Parent verified 43 artifact hashes, closed lifespan/socket, unchanged captured
source and authoritative cleanup, and inspected the recovered editor screenshot.
This is isolated authoring evidence, not deployment or full V7/native-fault acceptance.

The first run `arena-f0-6776c36862fd` remains failed: UI phases completed, but the
checker wrongly demanded query-free GET targets on preview/version-list reads.
Parent reproduced that in unit RED `arena-f0-unit-81ec4f30d3`, allowed queries only
on those documented GET/HEAD routes while keeping mutations query-free, and ran
144 Python + 10 Node units GREEN (`arena-f0-unit-56feb0dafd`) before the fresh run.
Its narrow closure review `deleg_91644d11` passed with no blocking findings;
the old failed proof is not relabelled. Queries are admitted only on the named
read routes, not as a new query-parameter validation protocol.

The acknowledgement flag records explicit parent approval of the reviewed API/UI
scope; supplying a flag alone never grants broader runtime or deployment approval.
The parent reports the earlier recovery/original-bundle protection, generic
jobs/workspace/SSE screening, research-identity search, Recent/pinning, manual
Retry capability fencing and original research-Open admission findings as
reviewed/tested closed checkpoints; they are not reopened blockers here.
The final production draft-controller review `deleg_181b8158` passed; parent
verified the current 1591-case production frontend selection and tsc/Vite build.
The separate native-storage case proof remains subject to its own checker review.

`readonly` and `authoring-v1` retain their original admission semantics and proof
contracts. Existing `arena-f0-933680638528` is still recorded `passed`; its
`browser-authoring.mjs` hash matches the unchanged current authoring driver.
No old proof or pixels were rewritten, upgraded or synthesized. The existing
proof file SHA-256 observed during this work is
`d9d2a3ab75231e52f0a7549db6fe865f74c8996b159c9fa8f2b96c6f998446ca`.
This was an inert historical read, not a rerun of that browser acceptance.

## Implemented journey (every step required)

1. Retain the original real-API baseline load/edit/restore, schema/catalogue and
   zero-job checks. Observe the production `/api/health` and `/api/editor`
   responses; require real durable-save/manual-save/exact-open metadata. No
   capability fulfillment, legacy Save substitute or direct POST is available.
2. Edit the actual CodeMirror root by adding a retained comment; require a new
   exact YAML/view validation request and that Request object's response.
   Click **Save durable revision**, require the keyed production POST and exact
   save-request GET receipt. Saving must not open/replace the editor source.
3. Click **Open research versions**, choose **Research save source → Verified
   durable editor revision**, store `manual-browser`, family `browser-family`.
   Require Save disabled until **Parent revision** is explicitly chosen.
4. Choose **None — start without a parent**, confirm **Save numbered research
   version**, and require POST 201 → exact reservation GET 200 for version 1.
   Select version 1 and verify its separate detail GET. Explicitly choose its
   research revision as parent, then repeat the confirmed POST+GET for version 2.
   Both versions preserve the same immutable editor source; neither selects or
   opens an editor document automatically. No publication target is submitted.
5. Select version 2 through its actual control/detail GET. Make a dirty edit,
   cancel **Open research version in editor**, and require unchanged visible
   bytes and zero document GETs across the cancellation boundary. Confirm a new
   explicit Open and compare exact root, source hash, canonical hash, descriptor,
   and all server `research_identity` fields.
6. Download the visible root using the production Blob control; read the actual
   downloaded bytes. Retain a real nonempty prompt so the production draft backup
   carries the exact selected research descriptor across reload (a completely
   clean empty-prompt editor does not persist selection). Reload and require a
   fresh view UUID with the same exact root/identity. Explicitly restore the
   retained prompt; this is not automatic draft restoration.
7. Make a new comment-only dirty draft, inspect only the actual
   `arena.editor.draft.v1` backup, reload again, require another fresh UUID and
   source-root display, then click **Restore draft**. Require exact restored
   bytes and a new validation against that fresh UUID. No storage injection,
   latest-version fallback, automatic save or job restart is permitted.
8. Read actual final jobs, capture real screenshots/trace, stop the owned API,
   independently read both commits and all five copied source artifacts through
   a newly opened ResearchStore on the **same app Journal**, then close the
   genuine lifespan and verify owned cleanup.

Search/Recent/pinning and adversarial live capability-rotation browser journeys
are **not claimed by this profile**. Their reviewed/tested fix checkpoints are
separate from browser acceptance. The import-safe negative units do not
impersonate production UI acceptance results.

## Boundary and checker

The API shim creates exactly one fresh ResearchStore after the real lifespan has
started, using `ResearchStore.create(app.state.journal, ...)` with the production
public-protection callback. It never creates a second Journal. Configured roots
are explicit and point only to `/private/manual-research` in the owned API tmpfs;
no existing research store is mounted. The browser cannot mount API state.

Only one keyed editor-save attempt and two manual-numbered-save attempts are
admitted. Attempts reserve budget before awaiting production dispatch, including
failed attempts. Manual bodies must have exactly `idempotency_key`, `family`,
`source`, and explicit null-or-revision `parent_revision_id`; source must contain
exactly `kind: editor_revision`, `editor_revision_id`, `source_hash`, and
`canonical_hash`. Flat/tagged candidate bodies, publication targets, grants,
unknown fields/stores/families, malformed identifiers/hashes, additional mutations
and query-suffixed mutation routes fail closed. The server's reservation includes
`publication_request: null`; that is distinct from the forbidden POST field.

The additive checker requires all journeys, exact numeric types, ordered request
boundaries, duplicate-key-free captured bodies, and response-to-Request-object
correlation. It compares all eight manual source fields across POST, readback,
selection, Open, reload, recovery and durable final readback; recomputes request,
reservation and manifest digests; and binds the server canonical hash to genuine
validation rather than inventing a canonicalizer. From actual copied artifact
bytes it independently recomputes raw-root, every-file, portable-bundle and
receipt hashes. The research receipt/manifest codecs use ASCII-escaped JSON;
editor bundle artifacts use sorted compact UTF-8 JSON without ASCII escaping.

The existing v3 run/ownership/source/dependency/artifact and v2 wire checks remain
mandatory. Manual source filenames and the two-entry mutation allowlist must
agree with the profile. Proxy mutation totals must equal the exact API records.
Missing actual downloads/screenshots/copied source artifacts fail acceptance.
All network/provider/graph/render/workload/subprocess forbidden counters and jobs
must remain zero. Existing nonroot, network-none, read-only source/dependencies,
preimport egress denial, capability/device restrictions, private UDS, bounded
lifespan and immutable-ID owned cleanup remain in force. No provider, Neo4j,
GPU, shared-service restart, install, secret or live-state access is authorized.
Self-authored hashes establish consistency, not independent authenticity.

## Draft-backup v1/v2 compatibility

The storage key remains `arena.editor.draft.v1`; neither the profile name nor
proof schema version changes. `backup_contract` checks the parsed object captured
by the **unchanged** browser driver at both prompt-context and dirty-recovery
checkpoints:

- v1 requires exactly `version`, `documentId`, `viewId`, `sourceHash`,
  `researchIdentity`, `draft`, `prompt`. v2 requires exactly those fields plus
  `draftId` and `revision`. Missing/extra fields and v2 metadata on v1 fail.
- `version` must be a Python JSON integer 1 or 2 (not bool, float or string).
  v2 `draftId` must match lowercase hex `8-4-4-4-12`; `revision` must be an
  integer in `0..9007199254740991`, excluding bool/float/string. No RFC UUID
  version/variant constraints beyond the production grammar are invented.
- All existing fields remain exactly typed and equal to independently observed
  evidence: research descriptor, that phase's frozen view UUID, root SHA-256
  (`sourceHash` on the wire, not an invented `rootHash` field), full research
  identity, YAML and retained prompt. The complete source/receipt/manifest,
  validation-correlation, fresh-view and recovery assertions are unchanged.
- Metadata is validated per record only. Different or reused draft IDs, revision
  reset across remount, and mixed v1/v2 checkpoint pairs do not imply or require
  migration, stable IDs or globally monotonic revisions.
- Decoded YAML/prompt bounds remain 262144/16000 **JavaScript UTF-16 code units**,
  not UTF-8 bytes or Python code points. These do not relax the independent HTTP
  UTF-8 body budgets. Boundary units include ASCII, BMP and astral characters.

**Raw storage-size evidence is not captured.** Production `parseDraft` limits the
original serialized record to 600000 UTF-16 units for v1 and 601024 for v2.
The existing driver retains `JSON.parse(raw)`, including all v2 metadata, but not
`raw` itself. Reserializing that object loses whitespace/escape spelling and
cannot establish the original raw-record budget (or duplicate raw keys).
This checker therefore makes no raw-backup-size/codec acceptance claim. No
browser storage injection, repair or new capture fields were added.

## Current v2 checker safe-unit evidence

Only the existing approved sandbox entry was executed, from
`/workspaces/IsaacLab-Arena`:

```sh
python3 -B web/arena-workbench/tests/e2e/functional-v7/self_test.py \
  --node-units \
  --frontend-dependency-container 964ddf2e645854708368230ff1770495df6f94c2ecca22b17c7d01ebc611f97d
```

All paths below are relative to this directory's `.runs/`:

| Run | Observed result |
| --- | --- |
| `arena-f0-unit-316c1851ba` | RED: valid full-wire v2 fixture rejected at the old exact v1 backup comparison; 1 manual-suite failure, no errors. |
| `arena-f0-unit-b685b28857` | Initial GREEN: v1 and full-wire v2 accepted; 137 Python and 10 Node tests passed. |
| `arena-f0-unit-06195301ac` | Hardening RED: invalid v2 metadata and overlimit decoded fields accepted; 55 assertion failures, no errors. Existing identity/fieldset negatives still passed. |
| `arena-f0-unit-ee1d61ba5f` | Final GREEN: 143 Python tests (31 manual-suite tests with matrix subtests) and 10 builtins-only Node tests passed; zero failures/errors/skips. |

Final evidence was independently rehashed: all 15 artifacts and 22 staged
source files matched; ownership/run mirrors and suite totals agreed. Both
nonroot, read-only, network-none containers recorded kernel egress denial before
repository imports; no dependency volume was mounted. Cleanup records showed
verified immutable-ID removal and authoritative empty label/candidate listings;
evidence/cleanup errors and remaining-owned lists were empty. The browser driver,
API shim, runner, stage allowlist and common unit entry hashes matched the first
RED run. The concurrently owned native probe checker was not modified or run.

Current exercised source SHA-256:

| File | SHA-256 |
| --- | --- |
| `manual_research.py` | `5becaf6357dc0fbff64c5df845328dc193022f8318c02f8444dddcb6e2e76177` |
| `test_manual_research.py` | `4814f797b77fb5f18f2b7b151fd8604a15d32ca3dd92da6318ee92f9abea0b26` |
| unchanged `browser-manual-research.mjs` | `b48989d6be9174a695a1c000d451b3d66dc3f002355b1a41289e4e95adbeea20` |

Final `run-proof.json` SHA-256:
`c4c344f246969e933a936cb90add31b14c6628ebe413745a3d7534f3ea5bc2f0`.
These are synthetic checker/unit results, not production API/browser evidence.
At this historical unit checkpoint, the manual browser was NOT-RUN pending
approval. The later real journey and reviewed checker fix are recorded at the
top of this document; this unit record itself is not upgraded to browser evidence.

## Historical unit checkpoints (before v2 checker changes)

Parent verification rerun: `.runs/arena-f0-unit-dee2c2e034/` passed the same
126 Python and 10 Node unit tests. Parent checked per-suite totals, zero skips,
all 15 artifact hashes and authoritative empty cleanup. No browser/API acceptance
was launched by that unit command. Profile review was pending at that checkpoint.

Run from `/workspaces/IsaacLab-Arena`:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 web/arena-workbench/tests/e2e/functional-v7/self_test.py \
  --node-units \
  --frontend-dependency-container 964ddf2e645854708368230ff1770495df6f94c2ecca22b17c7d01ebc611f97d
```

Final unit evidence: `.runs/arena-f0-unit-7d83113ad8/` — **126 Python tests and
10 builtins-only Node tests passed**, zero failures/errors/skips. The new Python
suite contains 14 tests with additional subtest negatives. Source hashes stayed
unchanged, evidence errors were empty, and authoritative cleanup listings showed
no owned containers remaining. The stopped frontend selector is used only for
local image discovery; no dependency volume is mounted for these units.

Tests cover exact manual firewall/body boundaries and budgets, the one-Journal
bootstrap seam, closure/browser admission, complete synthetic checker contracts,
missing/contradictory metadata and lineage, correlation/reordering, duplicate
wire keys, wrong typed identities, changed roots/UUIDs/recovery backups, extra
jobs, missing durable records, download digests, and independently resealed bundle
and receipt contradictions. Fixtures are explicitly synthetic, inert unit inputs,
never API acceptance records or generated pixels. Per-suite logs now survive
owned cleanup for diagnosing expected RED runs.

Preserved TDD evidence includes firewall RED `3366c9d3b2`, missing checker RED
`4704cebb74`, missing bootstrap RED `6a69f3b3a4`, Node tracker RED `3251340680`,
artifact checker RED `118a2a4c6f`, and subsequent metadata/budget/lineage/duplicate
key REDs. All are unit-only `.runs/arena-f0-unit-<suffix>/` directories. The initial
suite-allowlist mismatch and legacy producer fixture default-profile mismatch
were corrected without relaxing old profile admission.

## Reproduction command — same bounded approved scope

This invokes a real frontend build and real
browser/API mutations in fresh owned state; it is not a unit-test command.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 web/arena-workbench/tests/e2e/functional-v7/run.py \
  --browser --layout v7 --profile manual-research-v1 \
  --manual-research-closure-approved \
  --frontend-dependency-container 964ddf2e645854708368230ff1770495df6f94c2ecca22b17c7d01ebc611f97d \
  --runtime-image sha256:e20b3cc8258b793aaf1fe47c130f54e677fa9c0a6427991cfc1045b743162da5 \
  --provision-manifest web/arena-workbench/tests/e2e/functional-v7/.runs/arena-f0-provision-d94aed8076e8/provision-manifest.json

python3 web/arena-workbench/tests/e2e/functional-v7/check_proof.py \
  <actual-new-output-directory> --browser
```

The launcher prints a fresh directory and retains failed evidence. Missing
metadata, changed production labels/contracts, failed security closure, failed
build, unavailable isolated dependencies, or an uncompleted UI journey is a
blocker—not permission to fabricate API data, repair storage, fulfill routes,
synthesize screenshots or relabel old evidence. The shared functional CLI was
not changed; use the explicit profile launcher above.
