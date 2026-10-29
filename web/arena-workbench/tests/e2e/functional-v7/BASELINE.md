# Historical F0 evidence — acceptance withdrawn

**Full acceptance is withdrawn.** The old browser predicate could reuse an initial
validation for both edit and restore because canonical YAML identity was unchanged.
The old checker also accepted incomplete artifact/counter/status/identity evidence.
The following is the preserved historical report, **not a current pass**. Do not
delete, rewrite, or relabel the original artifacts as v2 evidence.

The historical production API plus Chromium run used the **legacy layout**:

- Command: `python3 web/arena-workbench/tests/e2e/functional-v7/run.py --browser`
- Evidence directory: `.runs/arena-f0-42e2e8aa98f1/` relative to this directory.
- The then-current, insufficient verifier reported success; that result is invalidated.
- `run-proof.json` SHA-256: `9639c9620fed0c54eb92053992436aa9aa66b11b1cd70dca19a913991ebba03a`.
- Chromium: `145.0.7632.6`, installed Playwright `1.58.2`; no browser installation.
- API and browser preimport probes: actual `ENETUNREACH`, UID 1000, read-only root/source/dependencies, no GPU devices. API effective capabilities: `0000000000000000`.
- Genuine validation: **6 assets, 6 nodes, 7 edges**. Invalid YAML rejected; unauthenticated and missing-CSRF checks rejected.
- Historical authenticated schema/catalogue requests were reported. The old harness's assertion that separate edit and restore requests completed is **not established by its predicates**; exact browser correlation must be rerun after authorization.
- Final counters: network/provider/graph/render/workload/arbitrary-subprocess **all zero**. Two explicitly allowed `git version` metadata probes are separately recorded, not hidden in those counts.
- Journal jobs: `[]`; genuine API lifespan closed; socket absent; authoritative owned-container listings: `[]`; cleanup errors: `[]`.
- Frozen staged source unchanged. Live source changes during this capture: `[]`; this does **not** replace the parent's eventual complete-source handoff acceptance.

## Real document identity

Approved source: `isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml`.

| Field | Actual value |
|---|---|
| Source ID | `31b1a1df12dd09930e774a6d301aba3b` |
| Frozen view ID | `36b17325a63c9cdc21165f25a3a1a9f0` |
| Raw source SHA-256 | `efbd78fc67152b13d2f95eaa5a192b0277af127ea9c2243d71ef869588e2b879` |
| Canonical spec hash | `4dc190b67905761ef90bfac0d95d75fdc19541ef28582edf57e16ac0d7cd8ce9` |
| Schema hash | `55996fc5d2754ef209aec9ebc902dd2da752c4b0355094ebbbd5eb1183fa7e6c` |
| Catalogue hash | `3e673d7f6aa54762d8eca190ec1e479fb9a8c450086d347788a4964343015b44` |

## Fault and lifecycle evidence

- Seven mocked-daemon tests passed inside the nonroot network-none runtime sandbox: `.runs/arena-f0-unit-e87898e7cc/`. This includes a witnessed RED→GREEN same-label replacement-ID cleanup regression.
- Actual after-create fault: `.runs/arena-f0-a4b7460f8d9b/`; expected exit 1, authoritative remaining-owned `[]`.
- Actual preimport denial fault: `.runs/arena-f0-e306c1b3c2ee/`; expected exit 1 before Arena imports, authoritative remaining-owned `[]`.
- Earlier failed attempts remain in `.runs/` rather than being overwritten. They diagnosed the missing installed Neo4j dependency, harmless registry-import metadata subprocesses, a read-only nested mountpoint, the sanitized Playwright browser path, and the distinction between embedded load validation and post-edit validation.

## Remaining gates

1. Integrate v2 run/API proof fields, strict staging/dependency discovery, and owned-isolation/cleanup readbacks; see README's producer contract.
2. Complete bounded regression review, including suppressed/delayed/reordered validation correlation and tampered/missing/contradictory proof rejection. Synthetic unit tests are not API/browser evidence.
3. Obtain explicit permission before **any full harness/build run**. The browser harness invokes Vite; standard build/typecheck commands remain denied. Do not execute the existing orchestration or temporary unit runner before its safe handoff.
4. After approval and stable-source handoff, capture new legacy and v7 evidence, exercise exact edit/restore requests plus actual final editor bytes, and pass the v2 consistency checker and independent acceptance review.

Neither layout has renewed acceptance. Self-authored artifact hashes establish internal consistency, **not authenticity**, trustworthy execution, or live-tree stability. No provider, graph publication/retrieval, research mutation, simulation, physical task success or GPU rendering is authorized by this CPU-only work.
