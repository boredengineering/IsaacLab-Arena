# Configured GR00T endpoint — finished, source-verified, NOT deployed

Contract preserved: `ARENA_WORKBENCH_GR00T_PORT` is canonical ASCII decimal `1..65535`, absent defaults to `5555`; explicit invalid values fail closed. Only host `127.0.0.1`; OpenPI remains `8000`.

## Completed
- Evaluation admission freezes `remote_host`/`remote_port` with the pinned server identity. Its private readiness envelope carries the captured GR00T port. Changed/invalid configuration during admission returns static `configuration_changed`, without submitting a job. Exact idempotent replay reuses frozen inputs without resolving the source, rechecking policy, or consulting current endpoint configuration.
- Evaluation workers validate complete endpoint tuples, reject malformed/partial values, and pass the same captured port to policy re-verification and harness argv. Historical inputs omitting both fields use explicit legacy GR00T `5555` / OpenPI `8000`, never the current environment.
- Metadata/server-info and native-codec peers share the captured port. Private readiness worker envelopes validate and forward it; nonpolicy workflows reject endpoint overrides. `agentic_generation` remains policy-RPC-free.
- Legacy readiness metadata/TCP probes capture configured profiles together and never mark a replacement endpoint reachable from old evidence. A2 readiness retires policy evidence on port changes.
- Evaluate and legacy readiness UI decoders accept bounded configured GR00T metadata, retain exact loopback/OpenPI constraints, and never send browser endpoint fields. Source/session/catalogue fences remain covered, including configured-port activity and identical-data refetch races.

## Evidence
All run names are under `web/arena-workbench/tests/e2e/functional-v7/.runs/`.
- Resumed frozen-endpoint RED: `arena-f0-backend-595bcab627ea`: **16 failed, 73 passed**. GREEN `8e7cd40f5b9a`: **89 passed**.
- Additional transport, readiness, UI and configuration-classification RED→GREEN runs retained in `policy-port-evidence.json`.
- Final backend `arena-f0-backend-4e82a53c0946`: **342 passed** across evaluate 117, readiness 183, policy readiness 36, wire 6. All six forbidden counters zero.
- Final frontend `arena-functional-frontend-8ed71854464b`: **250 passed** across four focused files (83/66/4/97).
- Ordinary isolated typecheck `arena-f0-typecheck-ab70a0544d24`: passed. Production bundle `arena-f0-build-4a8cdefbbd2e`: passed, with existing large-chunk/external-outDir warnings.
- Owned production/test source hashes match the final staged backend/frontend/typecheck runs; production UI hashes also match the successful bundle. Every run made by this resumed owner has authoritative `remaining_owned: []`. See `policy-port-evidence.json` for counts, hashes and pre-import isolation evidence.

## Scope
Modified API: `policy_endpoint.py`, `evaluate.py`, `evaluation_worker.py`, `policy_readiness.py`, `readiness.py`, `readiness_worker.py`; existing configured `evaluation_profiles.py` implementation retained and verified. Modified focused tests: `test_workbench_evaluate.py`, `test_workbench_readiness.py`, `test_workbench_policy_readiness.py`. Modified UI: `evaluate-policy.tsx`, `workflow-readiness.tsx` and their tests. `readiness_process.py` and wire tests were verified unchanged; its existing private pipe transport already preserves the captured endpoint and excludes mutable port environment.

No application/model-settings/generation/core-profile/stage/runner/control/docker edits by this owner. No commits, live jobs, model/provider/database/GPU requests, service stops/reloads/restarts or deployment. Tests use synthetic policy/OS/harness seams inside approved nonroot network-none containers, not live GR00T compatibility or GPU acceptance. Frontend dependencies remain trusted mutable installed input. Parent's runner discovery correction resolved the earlier blocker; older failure artifacts remain intact.
