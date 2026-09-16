# Native UI storage — nine-case scoped approval

## Result and review boundary

**Current native candidate:** `.runs/arena-storage-0edd1ff0837a/`.
Chromium **145.0.7632.6** exercised all nine cases through the unchanged reviewed
native runner. All nine report `observed`; driver and host remain **PARTIAL / exit
2**. The independent `--check-partial` returns **2**, with nine v2 cases and
`acceptance: false`; `--check` retains **exit 1** for these unpromoted raw records.
Independent closure `deleg_21c08e34` approved the nine-case contract with no
findings. Parent separately recorded scoped approval in
`.runs/ui-storage-scoped-acceptance.json` after rehashing artifacts and checking
fresh Docker label/name absence. The native machine results are not rewritten.
This is neither whole-app acceptance nor deployment/power-loss durability.

Latest causal follow-up: review `deleg_023c9b78` confirmed the earlier repairs but
found missing production absence-read binding and incomplete versionchange
ordering. Parent reproduced five coherently resealed accepted counterexamples
in `arena-f0-unit-58906a16ea`, then required the initialized production connection,
an ordered get-success(raw=null) before missing-record abort, and native
versionchange before independent upgrade completion within the retired cut.
The legitimate close/fallback-before-fixture-listener order remains permitted.
`arena-f0-unit-6cd4cda619` passed 169 Python + 26 Node tests; the fresh native run
above passed the stricter partial checker with all nine cases observed, 21
verified artifacts and authoritative cleanup. Final narrow review
`deleg_21c08e34` passed; no earlier proof was promoted.

Predecessor `arena-storage-26240005661c` run-proof SHA-256 (retained unchanged):
`2c0f41fa99e3ae59c3f97da19e6355b4e83cfb894127efcd6558b16c2ff29b54`.
The checker verified **21 artifact hashes and 212 staged-source hashes**. All
source-manifest hashes were also recomputed. Source staging and the stopped
frontend dependency were unchanged across execution. Cleanup is authoritative
and empty; no page errors, rejected network requests, evidence errors or cleanup
errors were recorded.

The original candidate `.runs/arena-storage-2d401db8a27c/` and original smoke
`.runs/arena-storage-02494ebb5773/` are retained unchanged. They are historical
v1/partial evidence, not evidence of the repaired v2 contract. The smoke's
concurrent clicks are **not** relabelled as witnessed transaction overlap.

## Proof gaps repaired

The reviewed host prefix, main/inside-unit suffix, browser preflight/runner
suffix, physical loader, mounts, PROBE, budgets and `REVIEWED_BROWSER` flag were
byte-compared against the previous candidate and remain unchanged. Production
Library/controller/native-adapter bytes also compare unchanged. Changes are
confined to the case fixture, case driver/observer, checker, synthetic checker
fixtures/tests, and this document.

- **Bound readbacks:** every case record/absence observation has a `binding`
  containing its observer connection, transaction, and exact created/get/complete
  event sequence IDs. The read event contains the actual raw record (or null).
  The checker requires matching raw bytes, an ordered completed readonly chain,
  independent observer role, distinct ordered observations, and no orphan
  observer transaction. `settledBy` alone is insufficient.
- **Completed seeds and awaited writes:** native seed put success and completion
  are mandatory, bound to the seed transaction and exact typed record, before
  independent readback. Every awaited write has exactly one terminal; only the
  explicitly intentional command abort and missing-record refresh abort are
  allowed. Initialization get/put/complete and no-op put counts are checked.
  Native deletion includes a same-transaction success witness for the exact
  `libraryPreferences/default` store/key.
- **Closed-trace semantics:** outcome, write-count, put-count and notification
  rules run against final `closed` traces, not just pre-cleanup audits. Every
  transaction has a terminal there; orphan, duplicate and reordered terminals
  fail. The suffix permits only readonly lifecycle events and connection closes,
  followed by the unique final `fixture-closed`. Late writes, puts, rebroadcasts
  and events after closure fail.
- **Legacy pre-module seeding:** Playwright `addInitScript` installs exact known
  synthetic reference bytes without consulting fixture globals. A bounded init
  witness records loading state, zero scripts, no fixture, seed and immediate
  readback. Fixture module entry independently records seeing that seed before
  controller activation. The old whitespace-bearing bytes remain unchanged.
  Playwright's initial `about:blank` is explicitly skipped; the actual fixture
  document still must meet the pre-script conditions.
- **Causal chains:** blocked → memory fallback → memory command/outcome → holder
  release; completed delete → completed absence observation → production refresh
  abort → memory fallback → command; and retirement cut → versionchange-case
  post-command. Actual listener ordering is respected: production close/fallback
  can be logged before the fixture's versionchange listener.
- **Production refresh, not observer substitution:** stable transaction roles
  distinguish production, fixture and independent observer connections. The
  test-only native BroadcastChannel handler wrapper records actual production
  delivery before invoking the original listener. Valid hints must precede
  completed production readonly refreshes with matching raw bytes. The actual
  Library UI must retain the exact **empty** shelf, disabled unconfirmed pin and
  zero Open requests. Equal but nonempty DOM snapshots cannot satisfy this case.

## Actual native cases

Each case uses a fresh BrowserContext, confirms an absent database before
activation, executes actual native operations, closes its fixture/context and
writes a separate report, including on failure. Cases run sequentially in one
browser. The production-component smoke remains separate.

| Case | Witness and observed result |
|---|---|
| `two-pages-concurrent-pins` | Two native command transactions are created while a real readwrite keepalive barrier is active; neither has read or settled at the captured cut. Release serializes writes. Both commit; independent completed readbacks contain both exact references at revision 2. This is **queued writer overlap**, not simultaneous mutation. |
| `competing-pins-at-capacity` | Completed native seed of seven pins, then two queued contenders. Exactly one commits and one returns limit. Revision 1 retains seven seeds plus the winner, with no eviction, loser write/notification or memory fallback. |
| `legacy-exact-unchanged` | Whitespace-bearing legacy seed is installed before any fixture script/module. Native initialize get/put/complete yields revision 0, two pins and one recent; legacy bytes remain identical. |
| `commit-notification-failure` | Test-only native postMessage fault throws after command transaction complete. Command remains committed at revision 1, with persistent snapshot and notification-unavailable notice. |
| `request-success-then-abort` | Actual native put-success listener aborts the same transaction before completion. Abort precedes unavailable; no commit/notification occurs and durable revision 0 remains unchanged. |
| `blocked-open-late-success` | Historical ID only: **NOT a late-success claim**. Explicit factory-version fault requests native v2 behind held v1 although production requested v1. Blocked causes memory fallback; memory command completes before holder release. Late upgrade aborts with AbortError, never success. DB remains unchanged at v1. |
| `versionchange` | Independent native v2 upgrade causes old production connection close and terminal memory fallback. Retirement precedes the later memory command; no durable replay/reactivation. |
| `missing-record` | Independent native delete success/complete, completed absent-record observation, then actual production readonly refresh abort and memory fallback. Subsequent memory pin/refresh leaves the record absent. |
| `notification-no-authority` | Four forged/foreign messages cause no transaction. Sixteen valid hints under a native barrier cause one queued and one trailing completed production refresh, no rebroadcast and unchanged bytes/snapshot. Separate actual Library UI receives messages and completes its own production refresh while remaining empty, unconfirmed and unopened. |

Predecessor `26240005661c` barrier keepalive completion counts were **463**, **89** and **71** for
concurrent pins, capacity and notification respectively. Limits remain 100000
requests / 4000 ms. Fixture operations retain 5000-ms rejection bounds, opens
3000 ms, native message delivery 2000 ms, and observer listing/open/transaction
deadlines. None of these change the reviewed host/capture budgets.

All references and parent confirmations are explicitly **synthetic** exact
editor revisions. No API responses, research-source authority, authenticated
backend verification, authored YAML, renders, quota durability or browser
power-loss durability are established. Actual research Open/Recent/pin/reopen,
draft-controller closure and broader handoff scenarios remain separate work.

## Schema, tests and retained RED→GREEN evidence

The driver retains its old smoke plus
`result.case_schema = "native-storage-candidate/v2"`, an exact nine-case map,
and mandatory mirrored `evidence/native-case-<id>.json` artifacts. Case rows use
`schema: 2`. Raw observations are captured before assertions and settle only at
native transaction completion. Synthetic checker fixtures are data-only,
explicitly labelled and never substitute for new native observations.

The preceding v2 checker suite exercised **104 resealed candidate negatives**:
85 witness mutations, nine missing cases, nine missing case artifacts, and one
mismatched artifact mirror. Event edits update all prefix/audit/closed copies and
surviving readback event IDs before the full driver/artifact bundle is resealed.
The suite checks a valid control first. Negatives include coherent seed/readback
terminal deletions, connection/role/raw/ID substitutions, orphan/reordered
terminals and reads, causal reordering, late writes/rebroadcasts in every case,
late init witnesses, observer-only UI refresh and equally nonempty shelves.
Subtests are not extra unittest suite-test counts.
The current follow-up adds five coherent causal/connection counterexamples;
their failures were observed before the checker changes.

| Slice | Retained RED | GREEN |
|---|---|---|
| Seed completion | `arena-f0-unit-5c462f7889` (2 accepted counterexamples) | `arena-f0-unit-137506b521` |
| Closed trace | `arena-f0-unit-fa8d971239` (20 accepted counterexamples) | `arena-f0-unit-d89151850e` |
| Bound observer reads | `arena-f0-unit-991a58c7e6` (2 accepted counterexamples) | `arena-f0-unit-806725cd6f` |
| Pre-module seed | `arena-f0-unit-28fd0fa17d` | `arena-f0-unit-f099fcff23` |
| Causal/production refresh | `arena-f0-unit-643e8a095a` (6 accepted counterexamples) | `arena-f0-unit-be188f4345` |
| Initial about:blank guard | native `arena-storage-227c4f24ab55`, unit `arena-f0-unit-e950a5f7a2` | `arena-f0-unit-f48f9b8778` |
| Unexpected abort/raw/notify order | `arena-f0-unit-73058b212f` (4 accepted counterexamples) | `arena-f0-unit-4f5ca199bb` |
| Extra initialization put/native delete | `arena-f0-unit-b9dac768d7` (2 accepted counterexamples) | Storage's 25 tests pass in `arena-f0-unit-ae33b91db4` and `arena-f0-unit-3882b7efe2`; final full cohort `arena-f0-unit-a7aef3e157` |

Failed native `arena-storage-227c4f24ab55` observed all nine cases but retained
12 harness init errors on initial about:blank pages. It is not acceptance.
The corrected intermediate `arena-storage-da4bdb975983` is retained PARTIAL and
passed the then-current v2 partial checker. Only final
`arena-storage-26240005661c` includes the native delete-success enrichment.
A stale-ID expectation in an intermediate unit regression is also retained at
`arena-f0-unit-1bb80dc05d`; the test was corrected to rebind surviving IDs rather
than weakening the checker.

**Predecessor safe units:** `.runs/arena-f0-unit-a7aef3e157/` passed **168 Python +
26 Node**, including storage's **25/25 tests and all 104 candidate negatives**.
There were zero failures, errors, skips or cancellations; owned cleanup is empty.
That checkpoint's storage sources match its staged unit run. Unit proof SHA-256:
`41c346a469109b344c32eaac1573b9cccbf25917254d783b933b8359e9235fd2`.
The proof contains 16 artifacts and 28 staged-source hashes.

Earlier full-green `arena-f0-unit-4f5ca199bb` passed 161 Python + 26 Node.
Subsequent `arena-f0-unit-ae33b91db4` and `arena-f0-unit-3882b7efe2` retained
failures from the separate owner's active manual-research v2-backup work (storage
itself passed). Once that owner's implementation changed, the approved unchanged
runner was rerun and the final 168-test Python cohort passed. No out-of-scope file
was changed to force those tests green. The Python count increase is from that
owner's additional manual-research tests, not inflated storage subtest counts.

## Commands and preserved execution limits

From `/workspaces/IsaacLab-Arena`:

```sh
python3 -B web/arena-workbench/tests/e2e/functional-v7/ui_storage_probe.py --browser --allow-storage-browser --frontend-dependency-container 964ddf2e645854708368230ff1770495df6f94c2ecca22b17c7d01ebc611f97d
python3 -B web/arena-workbench/tests/e2e/functional-v7/ui_storage_probe.py --safeunits --frontend-dependency-container 964ddf2e645854708368230ff1770495df6f94c2ecca22b17c7d01ebc611f97d
python3 -B web/arena-workbench/tests/e2e/functional-v7/ui_storage_probe.py --check-partial web/arena-workbench/tests/e2e/functional-v7/.runs/arena-storage-0edd1ff0837a
python3 -B web/arena-workbench/tests/e2e/functional-v7/ui_storage_probe.py --check web/arena-workbench/tests/e2e/functional-v7/.runs/arena-storage-0edd1ff0837a
```

Native/partial-check exits remain 2, safe units exit 0, and the full
acceptance-check retains exit 1 for unpromoted machine records. The separate
scoped approval receipt records the completed parent/independent review.

- OwnedRun reserves identity before create, retains the exact ACK, performs
  actual dependency preflight before imports and verifies absence after cleanup.
- Pinned local image remains
  `sha256:6446946a1d9fd62d9ae501312a2d76a43ee688542b21622056a372959b65d63d`.
  Network-none/nonroot/read-only/cap-drop/no-new-privileges and resource limits
  are unchanged; no API-state, daemon-socket or GPU mount exists.
- The stopped frontend dependency volume is trusted mutable installed bytes,
  not immutable provenance. No installs, pulls, shared restarts or commits ran.
- Only three fixed same-origin fixture assets are fulfilled. Other HTTP requests
  abort, WebSockets close and service workers are blocked. No fake API responses.
- Existing exclusive host-capture storage is unmounted. The combined 1-MiB exec
  capture and physical 4-MiB asset / 8-MiB aggregate budgets are unchanged; these
  do not impose quotas on child-created artifacts, Docker logs or metadata calls.

Self-authored hashes establish consistency, not independent authenticity. Parent
review and fresh artifact/cleanup checks are recorded separately from raw status.
All old, failed and intermediate proofs remain retained.

## Files and executable fingerprints

Changed only: `ui-storage-fixture.tsx`, `ui-storage-browser.mjs`,
`ui-storage-probe.test.mjs`, CHECKER portion of `ui_storage_probe.py`, synthetic
fixtures/tests in `test_ui_storage_probe.py`, and `UI_STORAGE_PROBE.md`.

```text
f19cfd6197b5edbf401113a25de2c22eb407127f4f522517e369af31d52f559e  ui_storage_probe.py
2dbcecc9f2cb61cf7e815357efc3c30334f91d3b8109e39acc2be13010574238  test_ui_storage_probe.py
dc3fd55d2251f58f24cac7aac179ecf0e0e55e48544bcc2e21cd198666f8fd56  ui-storage-fixture.tsx
2f07d545bc52314a4e98ae09f5472a0e415edea374479dd8395c9b8269aacbd6  ui-storage-browser.mjs
663f59052a875c4599ad68e5a3780acfa06ae2a855d893a3b28e806fce6a5779  ui-storage-probe.test.mjs
```

Unchanged loader:
`d2c61faf7056b86f1b7b798980eb785c1f8dcef31df80444c37017a5b51ea66f`.
