# Backend owner handoff

## Verified implementation

- Readiness v1 preserved; v2 strict metadata/check models, workflow-specific check IDs, required-route/body-validator/capability matrix, static `READINESS_CODES` exported from readiness.py.
- Fixed localhost GR00T explicit ping/modality/identity reads; operator checkpoint/config pins; same-instance comparison before/after codec verification; bounded plain MessagePack decoder rejects duplicate keys, extensions, unsafe arrays and ambiguous modality-wrapper JSON.
- New readiness_worker.py/readiness_process.py: private stdin configuration, sanitized generation-worker environment, actual graph_access.retrieve_snapshot invocation, bounded output/deadline, owned process-group cleanup and retained slot on ambiguous cleanup. No job/journal/queue writes from checks.
- Evaluate checks fresh policy/transport metadata before acceptance, freezes expected_server_info in durable inputs, rechecks it inside evaluation_worker before scene writes/harness start, then passes a detached exact pin into native typed configuration via a worker-local policy factory wrapper. Legacy OpenPI remains separate/unverified; evaluation-profiles adds `policy_contracts` without changing existing profile rows.
- `NativeCodecPeer` invokes the actual shared verify_native_connection + native MsgSerializer in worker code, with five allowed read RPCs, bounded deadlines and cleanup; no inference/reset/kill RPC in readiness.

## Final owned-source verification

Run: `web/arena-workbench/tests/e2e/functional-v7/.runs/arena-f0-backend-f6dec4b98855`.

145/145 passed: readiness 29, policy_readiness 16, evaluate 78, existing evaluation_harness 22. All six forbidden counters zero (network/provider/graph/render/workload/subprocess), cleanup_verified=true, remaining_owned=[], staged_source_unchanged=true. Real pipe/artifact bytes with synthetic transport/graph/harness/process-identity seams; NOT live policy/GPU/subprocess acceptance. Black/isort with repository options, flake8 and git diff --check passed using offline cached host lint tools.

`backend-owner-evidence.json` contains all test names, all ten owned Python source SHA-256 values verified against that run's staged manifest, proof hashes and exact static public-code/route matrices. JUnit SHA-256: `958ded212fdaad45a90170a5c61b02e205e4d75c6a56e09d05a080e29347aee0`.

Selected preserved RED → GREEN runs (all prefix arena-f0-backend-):
- Missing model expectation: 8d2a98a823ed → 41ccfb1ecc8f.
- V2 metadata: c4cd35504b59 → 41ccfb1ecc8f.
- Worker graph path: 5c0f866f9eb5 → 58f2e6c94711.
- Protocol/model distinctions: f6d3cd296295 → 57431c329ce9 (intermediate missing shared module preserved).
- Evaluation model/codec/instance refusal: dcc92aeb3317 → 57431c329ce9.
- Worker recheck/native cfg handoff: a25eb8a73b10 → d013df1e63b9.
- Duplicate private worker receipt: d410e7d3cdb3 → 134f90e75062.
- Default native helper integration: 56414f40c168 → 122a61553c24.
- Literal v2 fields: ad2535e39856 → 3689df56bcf1.

## Critical pending policy-review integration — NOT full A2 readiness

Parent review established actual N1.6 `__ndarray_class__/as_npy` wire format, while current API `decode_codec_reply` intentionally accepts only a tightly preflighted msgpack-numpy envelope. Thus N1.6 legacy NPY replies currently fail closed as transport unverified; the green synthetic msgpack-numpy tests do NOT prove N1.6 compatibility. Policy fix owner sa-0-df283e03 is implementing a shared raw codec preflight. Parent/follow-up must replace API-local `decode_codec_reply` validation with that shared preallocation-safe helper, add actual N1.6 raw-wire fixtures, and rerun the four backend suites. Do not send NPY bytes directly to native from_bytes/np.load: validate raw header version/length/shape/dtype/count/body length before allocation. No duplicate legacy parser was added during concurrent policy ownership.

## Other explicit unfinished behavior

- `gpu/resource_unknown` has no implemented PASS-evidence admission: Build/A2 overall `ready` remains false even if policy checks pass. A reviewed resource-budget/lease evidence contract is still needed, not merely deployment configuration.
- `generation_configuration_only` is not live provider verification. Graph generation overall `ready` remains false; no bounded authorized provider-test/result-receipt admission is implemented. No provider call is made by Check.
- No policy-smoke endpoint/job implemented. Existing evaluate is a fixed 1000-step simulator rollout, not a one-inference smoke. Adding a smoke needs separately reviewed reuse of existing job/lease/effect budgets/receipts, outside this bounded dependency-read API; no synchronous inference endpoint or fake pass was substituted.
- Worker graph check exercises the actual legacy retriever using explicit private operator config, not managed-selection grants or proof of a future generation's consumed prior. Empty/structural/measured are service-retrieval outcomes, not research success or publication permission.
- Frontend/Docker/shared-policy files and runner allowlists were not modified by this owner. No commits; no live .env/SQL/services/provider calls or queue changes.
