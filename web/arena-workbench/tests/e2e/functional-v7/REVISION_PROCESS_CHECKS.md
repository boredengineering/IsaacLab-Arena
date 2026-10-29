# Real-process keyed revision checks

Test-only harness: `revision_process_checks.py` (stdlib host orchestration),
`revision_process_worker.py` (trusted static container worker), and
`test_revision_process_checks.py` (three import-safe proof rejection tests).
No production Documents, storage, API, frontend or other harness files were edited.

## Run

From `/workspaces/IsaacLab-Arena`:

```bash
python3 -B -m unittest discover -s web/arena-workbench/tests/e2e/functional-v7 -p test_revision_process_checks.py
python3 -B web/arena-workbench/tests/e2e/functional-v7/revision_process_checks.py
```

No options accept arbitrary commands, fixtures, worker code or failpoints. The host
uses the existing `OwnedRun`, projected Docker metadata, `stage`, `ConfinedRoot`,
core-only import boundary and genuine Git metadata adapter. Production source is
captured once into a read-only frozen stage before execution. Only the approved
minimal Arena test YAML is copied into fresh private state; saves use the real
Documents new-document path (`document_id=None`, `expected_source_hash=None`).

One exact-ID owned container uses the original immutable runtime image, UID/GID
1000, read-only root/source, private tmpfs, network-none, no GPU, dropped caps and
no-new-privileges. Initial core preflight verifies empty private state. Every fresh
worker independently verifies ownership/isolation and an actual kernel egress denial
before repository imports. No live-container exec, host Arena imports, dependency
installation/acquisition, graph/model/API/render execution or production policy
change is needed.

Host Docker CLI waiters start separate OS interpreters; no threaded pytest fork.
Only the fixed metadata capture can spawn before the workload audit is installed.
An enum-armed worker may signal only itself with SIGKILL. The host does not signal
live or host application processes. Cleanup acts only on verified immutable owned
container IDs and requires authoritative empty label/name listings.

The operation phase is bounded to 300 seconds, at most 20 execs, two parallel
writers, 45 seconds per worker and 55 seconds per exec. A fixed keeper expires
independently. Cleanup uses the existing bounded Docker calls after the operation
phase; its time is additional. Source capture is bounded to 128 MiB, private state
to 128 MiB, and each exported state snapshot to 8 MiB / 40 files. Failed run
directories and copied incomplete bundle bytes are retained, never repaired.

## Actual result

Run: `.runs/arena-revproc-ffc3f36fc4dc/` — **passed**, host exit 0,
79.279 seconds including evidence export and cleanup.

- 18 fresh exec process identities, plus the keeper; **3 exit 137**, **15 exit 0**.
- Five requested scenarios passed; **three distinct committed keys/revisions**.
- Three import-safe proof rejection tests passed separately. They are not runtime receipts.
- Every forbidden counter (`network`, `provider`, `graph`, `render`, `workload`,
  `subprocess`) was zero. All observed cgroup `oom`, `oom_kill`, `oom_group_kill`
  values were zero; Docker `OOMKilled` was false at each death verification.
- 346 frozen source files were unchanged. All 160 recorded artifact hashes were
  independently read back and matched. All private state was exported before removal.
- Cleanup verified: **zero remaining owned containers**. The failed earlier run
  below was also exported and cleaned; its evidence is retained.

| Scenario | Actual observation | Commits |
|---|---|---:|
| Partial payload | Real `os.write` wrote 7 of 1298 snapshot bytes, then self-SIGKILL. Fresh read and exact retry both returned `RevisionError: Incomplete or corrupt editor revision`; no catalogue row and no byte changes. | 0 |
| Before promotion | Payload and temporary manifest fsyncs completed, then SIGKILL immediately before real no-replace promotion. Fresh read/retry rejected incomplete evidence without changing it. | 0 |
| After promotion / before ACK | Real no-replace promotion completed, then SIGKILL before directory/area commit fsync and before any ACK/finalizer. Fresh read and retry returned the identical committed receipt and genuinely fsynced manifest, snapshot, export, bundle, area and state. Exact revision reopen validated real YAML/hash. | 1 |
| Independent writers, same key/payload | Writer A held the real transaction lock; B witnessed actual `flock` `BlockingIOError` before A proceeded. Both returned the identical receipt; fresh retry/reopen confirmed one manifest. | 1 |
| Independent writers, same key/different payload | Same genuine lock contention; the differing YAML comment changed the request hash. One committed; the other returned `RevisionError: Editor idempotency key conflict`. Fresh retry confirmed the winner and one manifest. | 1 |

An additional fresh-process replay deliberately injected an `OSError` at its first
resync: it returned **RevisionUncertain, not success**. A further fresh process
completed resync and recovered the same receipt without changing bundle bytes.
This is explicitly a test-only fsync fault, not an observed failing disk.

Each kill has a fsynced failpoint witness with exact run/invocation, PID namespace,
PID and start ticks, before-kill OOM counters, partial/complete bytes and hashes,
plus the independently observed direct-interpreter exit 137. No killed worker
emitted a finalizer or ACK. Resync paths record successful native `os.fsync` calls,
not mocked success. Full receipts and raw state copies are in `run-proof.json` and
`evidence/`; the table below lists the actual literal revision bindings.

Key prefix: `arena-revproc-ffc3f36fc4dc:`

| Key suffix | Revision ID | Canonical compact receipt SHA-256 |
|---|---|---|
| `after-promotion` | `15972efc715f9913fdb3c7c02fcc2752` | `769276c4c749e241e1d3e70936d97d380a9cc34e495d5186b018dd2d772752bf` |
| `race-same` | `7819915707333618edcc1c9d1d72082a` | `809c0aaa7c0a3d48ea94ebc0fbdc10260090044405c6ea267b5caf5d1af858d4` |
| `race-different` | `472a56caf4328f5d21024d8db6571af5` | `4950b7ed12a09413824ca1e83bbbe386da7c6336451e5f11330f52d0d79d3e57` |

All three winning request hashes:
`caa14af2f5807575789f20d3ff774af17e28e01b825961eab67faa1384ef0b84`.

Image: `sha256:9af2ecbd69523de79b06a3edb992cba569679ab45ca997adf0d179dbd01883e8`.
Removed container: `0bc21abc14679f1697084c1961bd035eb5328fe280c3b5347ddad8099fac3e1d`.

SHA-256 bindings:

- `run-proof.json`: `ac4cb0f270102c6fd5d5d5ea7d9ac431fda0582f44ea8ddf02571408d5cc08ec`
- `source-manifest.json`: `9bfeba4f7114fbd40200c5e72df243ac7cbf2bbf0a7fb59ad8332fd877909edd`
- Frozen `documents.py`: `3f6e2530afcbce28ea74ba49f641a6a81dc2fdddcdbb0e131afb93f734e03c2f`
- Frozen `editor_revision_storage.py`: `5b901a8f813ab600a20d271d476611614e96c53cebd4938db9429fd60d8908ad`
- Seven-byte partial snapshot: `a919d96336c0341929fed24a5de0a043716ae2d3bcd9e595f6e7ade01a950fc0`

These self-authored hashes establish consistency, not independent authenticity.
The two executed harness files match the successful frozen stage. The third unit
test was added after that run and executed separately; no production code changed.

## Preserved failed evidence and limitation

`.runs/arena-revproc-b81c9abce839/` failed the strict exit witness check: the real
worker reached the partial-write SIGKILL, but `/isaac-sim/python.sh` converted the
child signal exit to wrapper exit **1**. The checker correctly refused to accept
that as 137. Four exec records, stderr showing the exact killed PID, partial bytes,
fresh read/retry rejection, final export, unchanged source and verified empty
cleanup remain on disk. No failure was relabelled as success.

The successful run obtains the actual resolved read-only interpreter
`/isaac-sim/kit/python/bin/python3.12` and a fixed allowlist of runtime path variables
from its trusted owned keeper. Host Docker exec invokes that interpreter directly,
retaining real exit 137 without allowing worker-triggered subprocess execution.

**This is actual process-death/concurrency evidence on private tmpfs, not a
power-loss test.** It does not demonstrate survival of host shutdown, lost kernel
page cache, disk/controller failure, container-state destruction or physical media
persistence. Native fsync completion here proves the retry/resync control path,
not durable storage after loss of power. No API/model/GPU receipts are claimed.
