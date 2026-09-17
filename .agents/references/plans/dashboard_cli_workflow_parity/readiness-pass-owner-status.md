# Readiness PASS follow-up handoff

## Delivered

- Build/A2 can now pass GPU dependency reading from two bounded same-device `nvidia-smi` observations plus a read-only existing-lease contention check. Explicit server `ARENA_WORKBENCH_GPU_MIN_FREE_MIB` is mandatory; optional exact `ARENA_WORKBENCH_GPU_UUID`, preserved CUDA/NVIDIA visibility, existing non-root-owned lease and non-MIG unambiguous device metadata are prerequisites. No lease-file creation/mutation, runtime CUDA selection changes, reservation or simulation guarantee.
- Strict v2 `check_provider:boolean=false`; GET/v1/ordinary v2 remain provider-call-free. Explicit opt-in resolves the actual private ModelSettings reference/server config without issuing workflow grants, sends one authenticated official documented model-metadata GET via the private worker, and fences current credential/configuration at completion. Only exact existing OpenAI documented profile pairs can pass `generation_model_readable`; no Agent, chat, inference, proxy, redirects or retries. HTTP status, malformed/duplicate/oversized data and timeout remain static codes.
- Full A2 now actually invokes the Neo4j worker retriever with its explicit private database config. Generation is separate for existing-draft A2 unless requested; graph generation still requires explicit provider reading for overall dependency `ready:true`. PASS means requested dependency/read checks only, never inference/physical/full-stack acceptance.
- Modified only readiness.py, readiness_worker.py, readiness_process.py, existing test_workbench_readiness.py; added resource_readiness.py/provider_readiness.py; appended clarification to research-stack-contracts.md. No helper, policy, frontend, Docker or runner changes; no commits.

## Verification

Final exact four-suite run: `arena-f0-backend-653bcee8b284` under the existing isolated functional runner. **210/210 passed** (readiness 94, policy-readiness 16, evaluate 78, evaluation harness 22). Network/provider/graph/render/workload/subprocess forbidden counters all zero; cleanup verified, no remaining owned containers, staged source unchanged. Real temporary lease/pipe bytes with synthetic GPU/HTTP/process/graph/policy seams; not live service validation.

Six owned source hashes match the staged source manifest. Exact command, hashes, test counts and preserved RED→GREEN run IDs are in `readiness-pass-owner-evidence.json`; JUnit SHA256 `924a59126151857065dd98f6bcb5c2cb696f7aa00e7dd6ed30445374171dbcf9`. Offline cached black/isort/flake8 and git diff --check passed.

## Parent work still explicit

1. Wire the two new nonsecret GPU environment keys into approved helper provisioning (or provision server environment directly). Preserve execution visibility and the already configured shared lease; Check will not initialize a missing lease. Root/API/service deployment blockers remain outside this owner.
2. Synchronize frontend static code allowlist and add explicit provider-read consent. No frontend tests were executed; frontend approval remains denied/pending.
3. Parent owns `policy_readiness.decode_codec_reply` and new `test_workbench_policy_wire.py` raw N1.6 consumer integration. This owner did not edit either or claim the new wire suite was included; rerun integration after that change.
4. The separately bounded policy-smoke job/effect/receipt contract remains unfinished, awaiting frontend approval. No policy inference, physical success, generation quota/structured-output capability or live GPU/Neo4j readiness was proven.
