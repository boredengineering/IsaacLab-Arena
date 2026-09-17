# Policy implementation handoff — review blockers fixed

## Current review-fix outcome

**76 passed, zero failures/errors/skips** in all three owned suites at `arena-f0-backend-3e7b018f503a` using the exact approved runner command below. Final source-manifest hashes match the six current owned Python files. `backend-proof.json` reports network/provider/graph/render/workload/subprocess counters all zero, egress denied before imports, no GPU devices. `run-proof.json` verifies owned cleanup; remaining_owned=[] from runner. Host isort (configured black profile), black (120/unstable), flake8 and git diff --check pass.

- N1.6 source inspected read-only at commit `ead52833afbbf4243f8cd5e7664f48a94de03b19`: processing_gr00t_n1d6.py:448-512 and Gr00tPolicy's `AutoProcessor.from_pretrained(model_dir)`. Admit/hash exact statistics.json and embodiment_id.json; test real **root-level** processor_config/statistics/embodiment layout with synthetic data, never model loading. Actual constructor remains embodiment_tag=OXE_DROID, model_path=local directory, device=..., strict=True. Embodiment mapping is written by save_pretrained; loader has a missing-file fallback, unlike mandatory statistics.
- N1.6 server/client lack close/context managers and call_endpoint timeout recovery. First-party OwnedPolicyServer inherits the existing native engine and owns lifecycle; VerifiedPolicyClient owns cleanup/recovery from verified socket/context/host/port/timeout attributes. Tests use N1.6-shaped inert peers and existing native server.run, not new SDK lifecycle APIs.
- Shared core exports `preflight_native_message(payload, *, max_bytes=67108864, max_array_bytes=67108864)` and `safe_decode_native_message(payload, decoder, **limits)` are ready for backend integration. Preflight returns raw plain MessagePack, NOT allocated arrays. It validates legacy NPY wrappers and current msgpack-numpy arrays/scalars before native decoding; numeric-only dtype, exact shape/product/data length, aggregate allocation and structure limits; no pickle/object/structured dtype/extensions/duplicate keys. Native server/client receive proxies both preflight before unchanged native from_bytes. Malicious tiny huge-count raw headers poison the allocation decoder on both receive paths; native-codec positive round trip passes.
- Config provenance deliberately narrowed: model-directory config_sha256 does **not** cover runtime Eagle processor/tokenizer/backbone files or SDK code. Exact dependency is installed `gr00t/model/modules/nvidia/Eagle-Block2A-2B-v2` (processing_gr00t_n1d6.py:49-53, modules/eagle_backbone.py). CLI help, source docstrings and shared Codec contract state independent runtime trust/pinning prerequisite. No complete-config verification claim.
- Full codec handshake once per owned connection (five RPCs), reused native modalities. Steady fresh Arena action = four RPCs (one inference + pre/post/final metadata), buffered action release = one metadata RPC. Full verification restored after socket replacement; original pin never upgraded. N1.6-shaped tests assert counts and fail-closed connect/fresh/buffered/reconnect drift. Native inference default 15000ms (configurable), metadata default 3000ms separately bounded; no auto inference retry.

### Review-fix RED→GREEN evidence

All run prefixes are `web/arena-workbench/tests/e2e/functional-v7/.runs/arena-f0-backend-` with `evidence/pytest.xml`:

| Slice | RED | GREEN |
| --- | --- | --- |
| N1.6 data-file allowlist | 3db5ba781af4 (1 fail) | c97c3c1830b0 (54 pass) |
| Raw MessagePack/NPY preflight | ffe7894e214a (9 fail) | 35aad79e64d3 (63 pass) |
| N1.6 lifecycle + receive poison | dfdd27b1713d (3 fail) | 76836de3f14f (66 pass) |
| Client RPC budget/deadlines | 57097e6e16f3 (1 fail) | 5f40c5208f6c (67 pass) |
| Arena RPC budget/drift | 74759dd4f2f1 (4 fail) | 8d4fcfc0d7dc (72 pass) |
| Explicit CLI provenance scope | 7df254ab2757 (1 fail) | 3e7b018f503a (76 pass; final formatted + extra malformed/roundtrip coverage) |

### Final six source hashes

```
5cb0c81552e8e749f33d0e63b475852ac5c33818ce2a54376fcd5a219c540a7a  isaaclab_arena/agentic_environment_generation/policy_contract.py
b29a65029579d9241661edf88c3aae9b8d273548e009c0eed19c3bd5cd983a71  isaaclab_arena/tests/test_policy_contract.py
62e0bbd9406515c3c99e1d02f56a7c60cb05860c864256e4a28b18a34ef148b2  isaaclab_arena_gr00t/policy/serving_metadata.py
2599884d64b2f6b3b12ab645a57b56cf88240a7a7c5ed6cb4a84e210d67c87c4  isaaclab_arena_gr00t/tests/test_serving_metadata.py
d2c08b3f2fe643f1f00126020624f5d4ac58875ff0f1842b23bdec59cd658234  isaaclab_arena_gr00t/policy/gr00t_remote_closedloop_policy.py
4864fbd45277de785e17b5202aaa875af720710c754defaf7b0c2cb76cce5c9d  isaaclab_arena_gr00t/tests/test_gr00t_remote_closedloop_policy.py
```

Scope: six owned Python files + shared Codec section + this handoff only. No backend/frontend/runner/Docker/submodule edits, no commits, no live model weights/loads, inference, hardware, service, DB or hardware-attestation acceptance. Backend owner must connect the shared preflight before its dual-wire decoder; shared contract documents exact exports. Parent independent review/integration remains separate.

## Earlier implementation history (superseded by review-fix outcome)

Parent resolved the fixture blocker by capturing the exact inert YAML closure and giving the native tests the staged repository cwd required by their real nested configuration paths. All three suites now pass together (53 tests) at `arena-f0-backend-c1bc19ca1fd9`; current source hashes/zero forbidden counters/owned cleanup verified. Independent review is in progress. The earlier owner report below retains the original failure evidence; its fixture-blocked status is historical, not a current blocker. Live model/server/inference acceptance remains unperformed.

Subsequent independent review found N1.6 mandatory processor-file and lifecycle incompatibilities, allocation-before-validation in native NPY decoding, incomplete runtime-configuration provenance and redundant verification/timeout behavior. These are assigned for correction; the source is not ready for server deployment despite the genuine 53-test checkpoint. Backend legacy-codec compatibility is tracked with its separate owner. Keep this qualification ahead of the historical owner report below.

## Outcome

Source implementation complete (not stubs). Pure contract + metadata producer + actual-native-codec helper/client tests: **38 passed**. Native Arena integration tests remain **15 blocked by missing real YAML staging** (no implementation failures reached). No submodule, backend, runner, Docker, or frontend edits by policy owner. No commits. No live model/GPU/inference/server/graph effects. Synthetic tmp_path artifact fixtures only; no real .env or weights accessed.

## Parent action needed

Parent owns `web/arena-workbench/tests/e2e/functional-v7/stage.py`. Please capture the exact inert fixture closure when test_gr00t_remote_closedloop_policy.py is selected, using existing confined capture (no guard relaxation):

- isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml
- isaaclab_arena_gr00t/embodiments/droid/gr00t_8dof_joint_space.yaml
- isaaclab_arena_gr00t/embodiments/droid/8dof_joint_space.yaml
- isaaclab_arena_gr00t/embodiments/droid/13dof_joint_space.yaml
- isaaclab_arena_gr00t/tests/test_data/test_g1_locomanip_lerobot/test_g1_locomanip_gr00t_closedloop_config.yaml
- isaaclab_arena_gr00t/embodiments/g1/gr00t_43dof_joint_space.yaml
- isaaclab_arena_gr00t/embodiments/g1/43dof_joint_space.yaml

Dynamic real `isaaclab_arena_gr00t/embodiments/g1/g1_sim_wbc_data_config.py` now has a meaningful static import/assertion in the native test. New contract/serving modules likewise use real static test imports, not module stubs. Re-run all three admitted tests after staging; then obtain independent review (not available as a subagent tool here).

## Changed files

- isaaclab_arena/agentic_environment_generation/policy_contract.py (new; all five exact pure exports)
- isaaclab_arena/tests/test_policy_contract.py
- isaaclab_arena_gr00t/policy/serving_metadata.py (new)
- isaaclab_arena_gr00t/tests/test_serving_metadata.py (new)
- isaaclab_arena_gr00t/policy/gr00t_remote_closedloop_policy.py (optional expected_server_info config; verified client selection, detached pin, buffered/fresh action-release checks, cleanup)
- isaaclab_arena_gr00t/tests/test_gr00t_remote_closedloop_policy.py
- research-stack-contracts.md: appended Codec contract section only
- this handoff

## Exact evidence

All below are under `web/arena-workbench/tests/e2e/functional-v7/.runs/`:

- Parent verified RED: `arena-f0-backend-82d5bd322e15/evidence/pytest.xml` — 7 missing policy_contract failures.
- Initial pure GREEN: `arena-f0-backend-a4e3b8ee80c5/evidence/pytest.xml` — 7 pass.
- Modalities/digest RED: `arena-f0-backend-bf3c6b4264ba/evidence/pytest.xml` — 9 missing helper failures; GREEN `arena-f0-backend-6e4811d0f09d/evidence/pytest.xml` — 16 pass.
- Producer RED: `arena-f0-backend-84ec9ce64e52/evidence/pytest.xml` — 11 missing serving module failures; GREEN `arena-f0-backend-c21e6309dd55/evidence/pytest.xml` — 27 pass combined.
- Native helper/config RED: `arena-f0-backend-87f5b522e4b7/evidence/pytest.xml` — 7 missing helper/client + 5 missing cfg-field failures, plus 10 existing native tests blocked by missing YAML.
- Native transport serialization lock RED: `arena-f0-backend-207ce6767076/evidence/pytest.xml` — 1 assertion failure; GREEN `arena-f0-backend-4ae9d348462c/evidence/pytest.xml` — 36 pass combined.
- No-weight/offline preflight RED: `arena-f0-backend-9025d6cd316d/evidence/pytest.xml` — 2 guard failures; GREEN `arena-f0-backend-1717e6c416bd/evidence/pytest.xml` — 38 pass.
- **Final formatted pure/producer/helper GREEN:** `arena-f0-backend-7de59d7b800d/evidence/pytest.xml` — passed, cleanup remaining_owned=[] (38 tests).
- **All-three integration attempt:** `arena-f0-backend-649abf5c0095/evidence/pytest.xml` — 53 total, 38 pass, 15 FileNotFoundError failures ONLY: 7 DROID config / 8 G1 fixture config. No assertion/model/protocol failures reached. Cleanup remaining_owned=[].

Cached host isort, black (120, unstable), flake8 all passed over the six owned Python files; git diff --check passed. Security-pattern scan found no eval/exec, pickle loads, shell=True or credential literals in producer. Final independent review remains parent-owned.

## Entrypoint and wire

`python -m isaaclab_arena_gr00t.policy.serving_metadata --model-path <materialized-local-model> --checkpoint-sha256 <operator-pin> --config-sha256 <operator-pin>`

Defaults localhost 127.0.0.1:5555, device cuda:0. `--fingerprint-only` tested through the actual CLI main prints hashes for synthetic artifacts without loading/binding; candidate hashes are not independent approval. Actual native Gr00tPolicy constructor signature checked in both vendored current source and n1.6-release source. Wrapper loads local approved safetensors/config directory offline, compares manifest before/after load, then creates same native PolicyServer and registers metadata + bounded codec echo. Refuses GROOT_SKIP_HF_MODEL_WEIGHTS no-weight mode and already-online HF state before model import. Compatible N1.6 runtime and immutable curated local assets remain operator prerequisites; actual approved model loading/inference was not authorized or exercised.

Shared helper exports and exact wire are appended to research-stack-contracts.md. Backend can use make_codec_probe, validate_codec_echo, native_serializer_sha256, verify_native_connection and VerifiedPolicyClient. Native client uses actual MsgSerializer with nonce + numeric/image arrays, 4096-byte echo/probe bound, complete identity/modality/codec checks, timeout-reconnect cleanup and shared RLock for scheduler traffic. Legacy cfg without pin remains unverified. Codec/metadata passes do not certify inference or task success, nor hardware attestation.

Language fixture corrected with direct source proof: `git -C submodules/Isaac-GR00T show n1.6-release:gr00t/configs/data/embodiment_configs.py`, oxe_droid language modality_keys=[annotation.language.language_instruction]. Bare language_instruction was wrong; no protocol weakening.

## Re-run command

`python3 scripts/run-functional-checks.py --runtime-image sha256:e20b3cc8258b793aaf1fe47c130f54e677fa9c0a6427991cfc1045b743162da5 --provision-manifest web/arena-workbench/tests/e2e/functional-v7/.runs/arena-f0-backend-1353292277b9/provision-manifest.json backend isaaclab_arena/tests/test_policy_contract.py isaaclab_arena_gr00t/tests/test_serving_metadata.py isaaclab_arena_gr00t/tests/test_gr00t_remote_closedloop_policy.py`

## Guarded-call race fix — supersedes prior effect-safety claim

**136 passed, zero failures/errors/skips** in the exact three-suite command above, final formatted source run `arena-f0-backend-a518eb46d6d0`. Exact changed-source hashes match its `source-manifest.json` and `run-proof.json`; all forbidden counters are zero, egress denied before imports, uid 1000, GPU devices empty, staged source unchanged, owned cleanup verified and remaining_owned=[]. Host configured isort/black/flake8 and git diff --check pass.

- Closed the metadata-check → effect race with additive `verified_call(expected_server_info, endpoint, data)` on the same native server. Strict exact pin equality against bound metadata and exact effect-body validation occur before calling the same policy's get_action/reset handler. No other endpoint is permitted. No native/submodule dispatch changes.
- Verified client transparently wraps action/reset requests with a detached private pin and original data. Original effect-specific deadlines, shared RLock, no automatic retry, no fallback, initial five/fresh four/buffered one RPC budgets and existing pre/post/final verification remain. Legacy registrations are unchanged. This new unreleased first-party v1 contract includes the guard with no new server-info fields; older unsupported peers fail closed. Full wire contract appended to research-stack-contracts.md.
- Actual PolicyClient.call_endpoint and PolicyServer.run were exercised over inert sockets using the native serializer. A peer swapped AFTER the successful metadata response but BEFORE the effect request receives **zero fake action/reset calls**. Valid pin dispatches exactly once; malformed bodies/pins, disallowed endpoints and changed bound policy/model/processor/metadata all reject before fake effects. Actual outbound wrapper shape, caller-pin mutation, array/options preservation, reset/inference deadlines, timeout no-retry and unsupported-peer no-fallback are covered. Existing RPC spies now expect verified_call and additionally assert the private pin and original inner endpoint/data rather than dropping verification.

### Guarded-call RED→GREEN evidence

All prefixes below are `web/arena-workbench/tests/e2e/functional-v7/.runs/arena-f0-backend-`; results read from `evidence/pytest.xml`:

| Slice | RED | GREEN |
| --- | --- | --- |
| Receiving-instance race + actual client wire | `9bf440d7c45f`: 4 failures; both replacements executed one fake effect before the fix, valid calls still used legacy wire | `f0f49c0e797c`: 80 passed |
| Strict effect-body validation | `7c4f3b252623`: 5 failures; missing options/wrong option type/wrong observation type reached fake effects | `b3f208816376`: 136 passed |
| Final formatted source + contract docstrings | — | `a518eb46d6d0`: 136 passed |

Final changed Python hashes:

```
e88d3c04fcc95e4273c24dfa40cb834ba391c1d0acdda492b8351d7520741405  isaaclab_arena_gr00t/policy/serving_metadata.py
4ff7c46a1c1d4696f8bd0cdc2ed17e915b41f11ad3cae95f5ded80d8631e9975  isaaclab_arena_gr00t/tests/test_serving_metadata.py
50a2e347a396a6b8ae078dfca85572c7d6031a3e6f321e97534cae7319328a9a  isaaclab_arena_gr00t/tests/test_gr00t_remote_closedloop_policy.py
```

Scope: these three Python files plus appended shared contract/status sections only. No core policy_contract, API/readiness, native policy implementation, runner, Docker, frontend or submodule changes by this fix. No live service/model/weights/GPU/DB/inference effects, no real .env access, no commits. Prior original hashes/counts above are historical; this final run verifies the race fix on the parent's integrated contract source.
