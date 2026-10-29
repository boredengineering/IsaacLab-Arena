# Isolated real browser/API acceptance

Run from the **editor container**, in this checkout:

```sh
python3 web/arena-workbench/tests/e2e/isolated-real/run.py
```

The runner discovers the matching simulator/frontend mounts and uses locally installed images and dependencies. It does not install packages, restart the live dashboard, commit changes, contact providers, or start Neo4j.

## Actual boundaries exercised

- Chromium runs the currently bundled production workbench, without `page.route`, response fixtures, or disabled SharedWorker. Its real HTTP traffic—including shared-worker traffic—passes through a recording loopback proxy at `http://127.0.0.1:31847` inside a dedicated network namespace.
- The proxy forwards `/api/*` to the production API Unix socket; session cookies, CSRF checks, authorization, schema validation, scheduler, attempt fencing, worker cleanup, SQLite journal, research store and manifests are real.
- Only trusted **test code** replaces generation configuration, the snapshot adapter, the worker executable, and `generation.generate`. The worker calls unchanged `generation_worker.main()` for private-envelope validation, parent-death handling and JSON framing. Its YAML is a labelled deterministic fixture, **not model evidence**. New reports retrieval unavailable; Refine reports not requested.
- UI actions perform New → review → save research version 1 → apply YAML → Refine → save version 2 with explicit parent and publication preparation. Exact HTTP job IDs, reservation/readback IDs, source lineage, attachment hashes, profile revision and preparation binding are checked. Explicit test setup initializes ONLY the fresh private Journal, ResearchStore and publication worker ledger under the launcher's lease before API lifespan. Publication admission is enabled with the real PublicationScheduler; no publication command is submitted or worker substituted.
- After selecting prepared version 2, accessible buttons open PublicationPanel ("Open publication execution") then actual PublicationControls ("Open publication controls"). The binding GET is observed from that UI action, never manually fetched. Exact displayed scope, enabled Publish graph, disabled renew/reconcile/cancel, and initial "Publication status unchecked." are asserted without clicking any execution action. Full YAML from the editor's existing draft backup plus rendered CodeMirror text are compared before/after; independent disk checks bind the response to the prepared intent and projection.
- Proxy counters forbid publication POSTs of any kind and allow only the explicit session, validation, deterministic generation and version-save mutations. Pass-through API observers count scheduler accept/enqueue and grant issuance, all zero; scheduler workers/tasks/slots and pending worker ownership are zero. No graph connections, provider calls, simulation or GPU work occur.
- Missing CSRF is rejected with 403; unauthenticated jobs read is rejected with 401. Reload rereads exact saved versions.
- After clean API shutdown, a separate nonroot verifier mounts private state **read-only**. It checks SQLite integrity, clean-shutdown metadata, completed jobs/attempts, cleaned workers, exact durable candidate hashes, and every committed artifact against the HTTP manifest. Publication states/bindings/receipts/requests/workers tables must be empty while exactly one immutable pending prepared intent exists; metadata schema rows are expected, not execution.

## Isolation and cleanup

Every new container uses `--network none`; the API additionally rejects IP socket connections with a Python audit hook. The browser and build containers cannot mount private state. Existing repository/dependency mounts are read-only. Fresh volumes are initialized as root; all API/build/browser/verification work runs as UID:GID `1000:1234`. No GPU device requests or Docker socket mounts are passed.

Readiness uses real UDS and loopback HTTP health checks with bounded deadlines, never a blind sleep. The API receives SIGTERM through a pidfd after boot/start-identity verification (signalling `python.sh` alone does not guarantee Uvicorn lifespan cleanup). Owned container IDs and volumes are removed in bounded cleanup; these container cgroups contain all browser/API subprocesses. Socket removal and empty worker ownership are verified.

The current deployment's live directory `/eval/.wb/6e74675cd31c/state` is read only for before/after file SHA-256, size, mtime and inode comparison. Runtime, frontend and `neo4j-arena` container identities must remain unchanged. The runner never sends live API requests. Access times are not an invariant.

## Proof output

Each attempt preserves a new private `/tmp/arena-real-acceptance-*` directory, including failed attempts:

- `run-proof.json`: isolation, ownership, cleanup, live-state comparison, source and artifact hashes.
- `browser-proof.json`: actual HTTP requests/responses, IDs/readbacks, successful jobs, manifests, attachment digests and browser failures. CSRF values are hashed in this JSON; the private Playwright trace contains isolated session traffic.
- `disk-proof.json`: independent post-shutdown SQLite/artifact verification.
- `worker-proof.jsonl`, `worker-frames.jsonl`, `spawn-proof.jsonl`: deterministic execution, actual received frames and production worker process identities.
- `trace.zip`, `new-candidate.png`, `refine-candidate.png`, `saved.png`, `prepared.png`: actual Chromium evidence.
- `mounted-publication-controls.png`, `controls-before.yaml`, `controls-after.yaml`: actual opened controls and unchanged editor draft; `bootstrap.json` and `api-before-cleanup.json` prove explicit setup and zero publication activity with admission enabled.
- `private/`: stopped isolated journal and committed artifact files; never the operator's journal.
- Build/API/browser logs and a snapshot of these test scripts.

The live container may reference an already-pruned image; the runner falls back to its locally installed service image tag. The simulator image lacks the locally installed Neo4j Python driver, so the actual package is copied read-only from the existing simulator into temporary dependency storage. Importing it does not connect to Neo4j. Vite uses `--configLoader runner` because its default loader attempts to write `.vite-temp` into the shared dependency volume. The runner bundles the current source, but is **not a substitute for TypeScript/unit-test gates**: concurrent source edits can make those gates temporarily fail. Source changes during acceptance are reported explicitly.

## Execution remains out of scope

This harness proves mounted controls opening, not publication execution, recovery, or graph readback. Keep the isolated origin, private store and real transport. Any future execution scenario requires its own authorization and trusted test-only worker injection; never add a public HTTP fixture switch. Real Neo4j/schema changes and real model/GPU execution remain outside this harness and require separate approval. Every run gets a distinct artifact directory; failed attempts and source-change flags are retained.
