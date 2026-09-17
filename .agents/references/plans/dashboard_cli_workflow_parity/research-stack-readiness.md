# Research stack readiness and approved-service startup

**PAUSED — 2026-09-17.** Preserve this design record; do not continue implementation or live operations from its earlier approvals. The latest user report is a disappearing dashboard after refresh. The [consolidated handoff](research-stack-implementation-handoff.md) is the current status; statements below are historical scope/decisions, not complete live acceptance.

Status: IMPLEMENTATION AND EXISTING-SERVICE LAUNCH AUTHORIZED. The user renewed implementation with priority on the existing Neo4j/GR00T launch path; implementation-added incompatibilities are corrections in that pipeline, not new prerequisites to defer. [Frozen implementation interfaces](research-stack-contracts.md) retain the existing helper/API authority split. Review and bounded launch of the existing cached services, configuration/resource corrections and matching dashboard integration are in scope. No container replacement, image/model download, generation, inference, simulation, queue release or graph publication is implied. No implementation checkpoint alone proves deployment or full-stack acceptance.

### Current delivery correction

Use the actual existing deployment rather than default-port assumptions: `neo4j-arena` publishes Bolt on host port **7688** (HTTP 7475), and the reviewed non-root/offline `gr00t-server` command serves DROID on **5559**. The installed observation profile's 7687/5555 values and API's hardcoded GR00T port are integration defects. Correct the private connection profile, use one validated server-side policy endpoint through readiness and frozen evaluation inputs, and preserve historical/default 5555 behavior explicitly. Do not redirect to unrelated running Neo4j services.

Before first start, apply and read back bounded RAM/swap/PID limits to these exact existing stopped IDs and check the owned stack's aggregate against daemon memory plus current headroom. Preserve original database volumes, cache and transport overlay. Complete the host-inaccessible mount-root check using fresh bounded metadata, not broader permissions or observation-only pins promoted to startup authority. Then start the saved services and check the actual worker connections. Service state, protocol/codec/model identity and executed research acceptance remain separate evidence.

Parallel implementation owns the requested create-only nonsecret model catalogue and its actual SDK policy propagation. It is not a dependency of existing-service startup. Credentials remain session-memory-only and no compatibility test runs automatically.

This is the C17/X01 service-prerequisite extension of [the canonical dashboard plan](../dashboard_cli_workflow_parity.md), not a replacement research architecture. Keep the accepted V7 layout, prompt-first creation, LPG/reification Graph-RAG, existing jobs/receipts, and separate build/evaluate/repair workflows.

## 1. Outcome and why this is necessary

Provide a **Research stack** panel that remains usable when the Arena API is down. The operator can select an approved workflow profile, inspect all dependencies and missing contracts, explicitly start its approved existing services, and then verify connections through the actual runtime paths. An unrelated listener, compatible-looking metadata or configured credential must never yield “ready with the correct policy.”

The default full research profile covers Arena/API, Neo4j and the selected GR00T policy, with generation LLM readiness shown separately. `gpt-6-astra` is the generation model; `nvidia/GR00T-N1.6-DROID` is the documented A2 policy checkpoint. These must never be conflated in labels or configuration.

| Current source | Limitation | Proposed change / reason |
| --- | --- | --- |
| `web_api/readiness.py:42–68,72–122` | Configuration/package metadata, authenticated Neo4j `RETURN 1`, policy TCP reachability only | Extend the existing readiness feature with explicit workflow, protocol, identity and worker-path checks. Do not replace it with another superficial health panel. |
| `web_api/evaluation_profiles.py:8–42` | Fixed ports and DROID scene compatibility; no served checkpoint identity | Add versioned expected policy contracts and compare actual server metadata to them. |
| `docker/workbench/workbench.py:109–183,239–289` | Discovery and lifecycle locking require running Arena | Add independent host-side profile/bootstrap/control ownership so stopped Arena can be started. |
| `docker/workbench/workbench.py:335–369` | Existing start path builds frontend and rejects an already-running frontend | Extract/reuse the API-only start boundary; do not call the whole launcher from a dashboard button. |
| `app.tsx:57–175`, `editor.tsx` | Shell survives disconnection, but editor readiness requires an API session/capability | Mount stack controls in Shell, outside editor/session admission. Preserve draft/controller lifetime. |
| `web_api/__main__.py:34–58`, `application.py:223,271` | `create_app` supports paused startup but CLI does not expose it | Thread explicit paused startup through the existing launcher so recovery cannot release queued research work. |

Source observations are not deployment acceptance. Existing service names, IDs, ports and volumes must be rediscovered at provisioning; none are browser-selected Docker targets.

## 2. Architecture: retain one URL, separate startup from research execution

```text
Browser / existing V7 frontend, same loopback URL
  /control/* -> narrow Unix socket -> host service helper -> fixed Docker lifecycle operations
  /api/*     -> existing API socket -> Arena API / owned workers -> Neo4j and policy protocols
```

The helper runs as the approved host operator with Docker permission, independently of Arena. The browser, frontend and Arena API receive **no Docker socket**. The helper is not a second research scheduler: it owns only bounded startup receipts and observation of approved service instances. Existing research jobs, authorization, cancellation, publication and DCRG state remain with their current owners.

Use one separately owned control-socket directory, read-only mounted into the frontend. Keep the helper's executable, allowlist/profile, pairing material and operation state outside the repository and Arena-writable `/eval` mounts in deployment; install reviewed helper bytes from the repository to that owner-controlled location. Socket directory replacement and ownership must be validated before mounting. Reuse the existing loopback frontend port (currently 3010); no new public management port.

A one-time host bootstrap/provision step starts the frontend and helper independently of Arena and records approved identities. If those two are stopped, a browser cannot bootstrap itself: the documented host launcher is still required. No always-on cluster, generic Docker proxy or Kubernetes deployment is proposed.

Cold bootstrap must also satisfy the **existing API IPC mount**, not only create the new control directory. `compose.yaml` uses `create_host_path: false`; therefore provisioning must create or verify the approved host API IPC directory before frontend creation, even while Arena is stopped. Use the profile's already verified non-root API UID/GID, the runtime's exact parent/IPC `0750` and state `0700` requirements, and no-symlink path validation (`docker/workbench/runtime.py:124–152`). Create only explicitly approved missing directories; preserve existing state/journal bytes and reject ownership/mode conflicts rather than recursively chowning, broadening permissions or initializing a database. If the host operator cannot establish the required ownership, provisioning reports the exact prerequisite and stops. The normal runtime revalidates the same directories after Arena starts. The browser Start operation does not gain arbitrary mkdir/chown authority. Test Arena stopped with both present and missing IPC directories, including permission/symlink refusal.

### Operator-owned service profile

One reviewed profile per supported workflow binds:

- Existing full container IDs and expected image identities, clone/eval/database/model-cache mounts, network endpoints and actual service-user expectations.
- Existing Neo4j `/data` identity and explicit database, without putting credentials in public profile responses.
- Runtime interpreter, repository path, non-root API account/group, API origin/socket/state and a configuration revision.
- Policy model family, exact approved local checkpoint revision/weight manifest, embodiment, modalities, action convention, horizons and supported serializer protocol.
- Host RAM/PID limits and a separately assessed GPU-memory headroom requirement for policy loading plus simulation. Existing host RAM caps do not prove GPU headroom.
- A reviewed startup-only/offline-capable entrypoint contract. `docker start` executes the saved entrypoint; it does not inherently prevent downloads or queued work.

Missing/ambiguous containers, incompatible mounts, unapproved entrypoints or absent cached weights block startup with an operator action. Never substitute an empty Neo4j, a different policy or the whole simulation Compose stack. The current Compose policy endpoint is not automatically the dashboard's policy endpoint.

Implementation clarification: existing services do not require replacement read-only-root containers. The private profile explicitly selects `operator-reviewed-existing-v1` (or the separate strict `image-baked-v1` option); there is no HTTP-selected mode or implicit downgrade. Existing-service review retains actual boolean rootfs state, exact saved commands/mounts/resources and the same privileged/socket/installation-authority exclusions. A bounded source-evidence list pins mapped host-backed startup files by SHA-256, device and inode and is rechecked before starts and fixed API execs. The mandatory real API chain is `docker/workbench/runtime.py`, `docker/workbench/workbench.py`, and **`docker/resource_limits.py`**. Listed-byte checks do not attest writable container layers, all transitive imports or an atomic check-to-execution boundary; trusted container administrators and mount writers remain explicit assumptions. See `docker/workbench/CONTROL.md` for the exact operator-only schema and limits. This corrects the implementation-added blanket immutable-root restriction, not the original workflow or workload-authorization boundary.

## 3. What preflight validates

Return evidence per check with method, observed status, expected/observed identity where available, observation time, profile revision and static failure/remediation codes. Keep unknown, mismatched, unavailable and not requested distinct. Public output excludes credentials, raw container environments, arbitrary argv, driver errors and sensitive model paths.

| Dependency | Required checks | What is not proved |
| --- | --- | --- |
| Arena / API | Approved container/image/mount/user identity; bounded existing supervisor health; required API capabilities and supported contract versions; runtime package availability; execution worker can start under the actual sanitized environment and identity | Isaac Sim scene correctness or GPU success without an explicit smoke/build job |
| Neo4j | Explicit configured endpoint/database and read authorization; bounded authenticated transaction; the generation worker's actual graph configuration/grant and retriever path; eligible-prior outcome reported separately | Publication permission/commit, graph-informed correction integration or consumption by a future generation |
| GR00T protocol | Explicit `ping` and `get_modality_config`, strict bounded MessagePack decoding, correct DROID video/state/action/language contract and supported horizons | Correct checkpoint weights, ndarray transport or action inference from ping alone |
| GR00T identity | Trusted same-serving-instance metadata after model load; compare approved artifact/config/embodiment identity, not container name or a user-entered label | Hardware-backed attestation or behavior inferred only from metadata |
| Generation LLM | Exact provider/model/profile configured and accepted by the existing request policy; private credential availability at dispatch | Account access/structured inference until a separate bounded model test or real generation succeeds |
| Resources | Existing GPU lease ownership and known RAM/PID/GPU headroom; explicit unavailable/unknown if inspection is insufficient | Guaranteed OOM immunity or exclusion of unrelated external GPU processes |

The dependency matrix is workflow-specific: editing does not require Neo4j/GR00T; graph-backed generation requires worker retrieval and the generation model, not a policy rollout; zero-action Build requires Arena/GPU; GR00T evaluation requires matching policy plus Arena; the full graph-backed A2 workflow requires all applicable checks. Show the full stack even when only one action is blocked.

### GR00T identity is a real missing contract

The inspected upstream `PolicyServer` registers `ping`, `kill`, `get_action`, `reset`, and `get_modality_config` (`submodules/Isaac-GR00T/gr00t/policy/server_client.py:173–182`). It exposes no loaded-checkpoint identity endpoint. Omitting `endpoint` defaults to `get_action` (`:256`), so probes must always name an exact allowed endpoint.

First implement protocol checks without pretending they verify weights. To satisfy the **correct model** requirement, add a first-party serving wrapper/metadata adapter using the existing `PolicyServer.register_endpoint` hook; do not modify vendored model/processor code or replace the inference engine. Proposed endpoint: `get_server_info`. Publish a bounded nonsecret contract only after the intended local model successfully loads: serving-instance ID, policy implementation/version, resolved artifact/config fingerprints, embodiment and modality/action contract. Tie metadata to the same policy object serving actions. A hard-coded expected model label, launch argument, unrelated HTTP sidecar or cache-directory existence is insufficient.

An optional metadata-only serializer echo endpoint can verify the actual client/server ndarray codec using bounded synthetic arrays without calling the model. A bounded real inference smoke test remains a separately consented action before claiming inference compatibility. Never reset/kill a shared policy during readiness probes.

**Transport evidence is mandatory for verified evaluation admission; the echo implementation is optional.** Require either a bounded synthetic codec roundtrip or an explicitly approved inference smoke through the actual evaluation-worker/native `PolicyClient` environment. Bind the result to that loaded client's codec identity, the serving instance and server codec/model contract. Metadata/modality matches alone cannot pass this gate. If no supported roundtrip or approved smoke exists, show `transport unverified` and block verified evaluation. Client/server changes invalidate the result. A codec-only success still leaves model-action inference untested; report that separately and require the approved inference smoke before full-stack acceptance.

Existing unmodified servers report `protocol responsive / checkpoint unverified`; they do not receive a green “correct model” result or admit a checkpoint-verified evaluation. Do not silently accept a G1 policy on a DROID endpoint. For the documented N1.6 DROID profile, validate its one-frame/32-action contract rather than the checked-out N1.7 defaults. Discover the actual serving implementation during provisioning.

Deploying this wrapper is a distinct policy-server rollout. If the existing container cannot launch it without a changed command/mount, obtain approval for an exact replacement/rollout preserving weights, caches and rollback; the ordinary Start button never performs that upgrade. Correct-model acceptance stays blocked until this contract exists and is verified.

### API coverage and dispatch gating

Maintain a small versioned required-capability matrix over the actual advertised backend contracts, not URL existence alone. Reuse the canonical C-row/endpoint mapping. Check required read contracts and use side-effect-free validators for write contracts; never probe readiness by submitting a generation/build/publication. Missing endpoint, old schema or incompatible response must appear as its own blocker.

Freeze workflow/profile/source identity with the preflight result. Recheck ephemeral service/configuration identity at execution release using the existing worker/grant boundaries; stale browser checks are not execution authority. A live policy-client identity check at connection/reconnection must reject a changed serving instance or contract rather than silently consume the replacement. Scope verified policy-client support explicitly; retain existing CLI compatibility separately. Helper/API restart or profile change invalidates applicable readiness. A control receipt cannot authorize a research job or grant graph access.

### Required API/request coverage ledger

S1 must produce a current, source-bound **method/path → workflow → actual UI/worker caller → request validator/admission → response decoder → exact-request readback → test/evidence/status** ledger. Enumerate each method/path separately in that implementation ledger; the grouped coverage requirements below are the planning baseline. Reconcile current router registration against the canonical C-row ledger rather than copying the historical route count. Each required row must be implemented/tested, unavailable with a concrete blocker, or explicitly unsupported; missing rows cannot be silently counted as ready.

| Required contract group | Real owner/caller and validation to cover | Safe live check versus behavioral/effect evidence |
| --- | --- | --- |
| Proposed control session/state/Start routes in section 4 | Shell control client → installed helper; pairing, Host/Origin/CSRF, exact profile/request revision, fixed-target admission and retained-request lookup | Read paired state safely; isolate start/replay/unknown-effect tests; real starts require approval |
| `GET /api/health`, `GET /api/editor`, `GET /api/editor/schema`, `GET /api/editor/catalogues` | `runtime.tsx`/editor → application/catalogues; decode actual protocol/capability/catalogue versions | Safe metadata reads; use existing catalogue/API tests for incompatible responses, not a green HTTP status alone |
| `POST /api/sessions`, `GET/DELETE /api/session`, `POST /api/session/activity` | Existing `ApiClient` → `security.py`; session/CSRF/expiry and actual reconnect semantics | Establish/read current session explicitly; expiry/revocation tests isolated, never revoke a user's session to test readiness |
| `GET/PUT/DELETE /api/model-settings` | Model settings controller → existing settings validation/private credential ownership | Read metadata; credential mutation/leakage tests use synthetic secrets, no automatic provider call |
| Existing readiness GET/check POST; proposed policy-smoke POST | Existing readiness controller → bounded runtime probe; strict workflow/source/profile/selection model, response status union and worker-context authorization | Checks only after consent; smoke requires separate inference budget; tests reject unsafe RPCs and stale identity |
| `GET /api/editor/documents/{document_id}`, `POST /api/editor/validate` | Editor → Documents and frozen include/source validation; decode exact source/canonical identities | Safe authorized document/schema checks; no substitution of a cached source for the selected draft |
| `POST /api/editor/generate`, `GET /api/editor/generate/operations/{idempotency_key}` | Existing generation controller → `GenerateDraft`, source/catalogue/grant admission and private worker; New/Refine distinction, actual consumed prior receipt, query `request_sha256` binding | Validate payload/admission and lost-ACK recovery in isolation; live model execution separately authorized |
| `POST /api/editor/save`, `GET /api/editor/save-requests/{idempotency_key}`, `GET /api/editor/revisions/{revision_id}/download` | Existing editor-save controller → `SaveDraft`, immutable source/receipt checks and exact download decoding | Reads of an authorized retained revision only; durable-write behavior isolated or separately approved |
| `POST /api/editor/build`, `POST /api/editor/snapshots`, `GET /api/editor/artifacts/{artifact_id}`, `GET /api/editor/previews/{canonical_hash}` | Existing Build/snapshot controllers → strict draft/profile models, source hashes, GPU admission, job and artifact decoders | No live submissions during Check; reuse focused Build/snapshot tests and separately approved real GPU acceptance |
| `GET /api/editor/evaluation-profiles`, `POST /api/editor/evaluate`, `GET /api/editor/evaluations/{job_id}/artifacts/{name}` | Evaluate controller → `evaluate.py` and actual evaluation worker/native policy client; spec/profile/identity/transport admission and matching artifact receipt | Read profiles safely; mismatch/refusal/zero-episode/decoding tests isolated; rollout requires separate approval |
| `GET /api/jobs`, `GET /api/jobs/{job_id}`, `GET /api/workspaces/default`, `GET /api/events` | Existing observation/SSE-or-polling owner; strict job/source/status decoding and reconnect | Safe reads; do not make diagnostic-job submission or queue resume a health check |
| `POST /api/jobs/{job_id}/cancel`, `POST /api/jobs/resume-queue`, generation reauthorization/disposition routes | Existing jobs/renewal controllers and retained exact-request contracts | Isolated behavioral tests only during readiness work; startup never invokes these mutations |
| `GET /api/graph/status`, `GET /api/graph/examples`, `POST /api/graph/query` and worker retrieval path | Graph UI/query validation and `graph_access.retrieve_snapshot`; explicit database/private grant, read-only bounds, exact context/fallback decoding | Consented bounded reads; successful explorer query cannot substitute for worker retrieval |
| Research version/publication routes registered in `research_routes.py` and `publication_routes.py` | Existing ResearchVersions/publication controls, strict reservation/source/target/grant/readback contracts | Enumerate their exact current methods in S1; configured-profile/read access does not attest write capability. Existing isolated publication tests and separately authorized exact-target readback remain required |

Use existing `test_workbench_readiness.py`, `test_workbench_catalogues.py`, `test_workbench_editor.py`, `test_workbench_editor_revision_api.py`, `test_workbench_graph_access.py`, `test_workbench_evaluate.py` and neighboring generation/publication suites as owners of behavioral checks, plus the proposed helper and actual-App tests. Identify missing pure admission validators and response decoders explicitly rather than invoking effectful POSTs as probes. For Build/Evaluate/control operations without a dedicated disposition URL, test the actual retained key/request-to-job/receipt lookup and mark any missing recovery contract as a gap. A 404, incompatible response, wrong source, replay conflict or missing recovery handle has its own test. Do not claim all-backend closure from health and profile endpoints alone.

## 4. Proposed endpoints and owners

These routes and extensions are proposals, not existing registered APIs. Exact request/response schemas and negative tests must be frozen before parallel implementation.

| Method / path | Owner and effect |
| --- | --- |
| `POST /control/session` | Host helper: one-time operator pairing, or recovery of a still-valid helper session; no service start |
| `DELETE /control/session` | Host helper: revoke control session only |
| `GET /control/research-services` | Host helper: authenticated sanitized profile/service state and retained startup receipts; no protocol probing or starts |
| `POST /control/research-services/start` | Host helper: exact `{request_id, profile_revision}` for the single provisioned profile; bounded start of missing approved services; promptly return accepted operation identity |
| Existing `GET /api/editor/readiness` | Extend/version configuration and capability metadata; no external probes or model initialization |
| Existing `POST /api/editor/readiness/check` | Extend with a strict workflow/profile/source-scoped contract and explicit bounded check selection; actual runtime-side protocol/worker-path checks; no inference or research execution |
| Proposed `POST /api/editor/readiness/policy-smoke` | Separately consented bounded native-policy inference/transport test, only after identity checks; use existing job/lease ownership, no environment rollout or graph write |

Readiness v1 and v2 need explicit coordinated backend/frontend decoding; do not send new enum/shape fields to old strict consumers. Startup receipt lookup uses the retained exact request ID (query parameter on the service-state endpoint or equivalent fixed read contract), not global latest status. Duplicate same-ID/body returns the same operation; mismatched reuse conflicts. Preserve a bounded owner-private receipt history through helper restart, without evicting unresolved effects or inventing a completed start.

## 5. Startup sequence and failure handling

1. Pair once from the host-approved helper and select the provisioned research profile in the dashboard. Show expected services, policy checkpoint and effects before Start.
2. Take a host-owned lock independent of Arena; verify profile revision and all target identities/entrypoint requirements before the first mutation. Reserve the request identity and record intended starts.
3. Start the approved existing Arena and Neo4j containers only if stopped. Inspect resulting exact IDs/states. Start only the API within Arena through the existing non-root supervisor if absent, with explicit `--start-paused`; never restart a healthy API or discard a temporary key.
4. Check resources and start the approved GR00T service if stopped. Loading cached weights may use GPU memory and take time; disclose this as service startup, not free CPU-only checking. Do not switch checkpoints automatically.
5. Observe progress with bounded read-only polls. Proposed limits: one active startup, 15-second Docker calls and a 600-second total startup window; profile limits remain explicit and are calibrated before live approval. Per-probe time/byte limits are independent. A timeout preserves started services and unknown/not-ready outcomes.
6. Reconnect the normal Arena API session through existing UI behavior. After the reviewed Start-and-check action, run only the explicitly selected bounded runtime dependency checks. Show per-service results and unresolved blockers.
7. Require a separate generation/build/evaluation action. No queue resume, model call, snapshot, rollout or publication is implied by Start/check/reconnect. Existing running work is neither cancelled nor adopted. Queued work after API recovery stays paused until separately reviewed.

Partial failure does not roll back by stopping Neo4j or unrelated services. Unknown Docker acceptance is reconciled from the exact recorded target, not blindly resent. Helper death leaves independently started services alone. No automatic stop/restart/recreate/remove/pull/build/volume/schema operation is available from these controls.

## 6. Security tradeoff and provisioning boundary

Docker permission is powerful host authority even for a non-root helper process. The narrow API reduces what the browser can request; it does not sandbox a compromised host helper. Keep the helper/profile installation host-owned and reviewed, with no imports from mutable repository code in its privileged request handler; any approved Arena exec is fixed to the existing non-root runtime command.

Use a short-lived one-time host-generated pairing token, entered into an uncontrolled password-style field and never included in URLs/logs/browser storage. After pairing, use a separate short-lived HttpOnly, SameSite=Strict, host-only cookie scoped to `/control` and a CSRF token retained only in memory. Use Secure cookies with HTTPS. Validate exact configured Host and Origin, JSON content type, CSRF and bounded pairing attempts; no wildcard CORS or proxy-injected bypass credential. Ordinary Arena sessions do not authorize Docker actions.

Only the control socket directory is mounted read-only into the frontend; profile, pairing token and state are not mounted. Proxy strips spoofable forwarding headers, disables caching and preserves Host/Origin. Profile revision and exact container IDs are rechecked before each effect. Require a separate review for any remote/multiuser deployment.

Scoped launcher/runtime/helper/proxy/Compose code changes under `docker/workbench/` are now implementation-authorized. Initial deployment still needs a frontend-only rebuild/recreation for its proxy configuration and new socket mount, preserving the public port. This is different from replacing research containers. The GR00T identity wrapper may require its own separately reviewed server rollout. No live policy image rebuild, service replacement or submodule change is implicitly approved.

Graph credentials remain operator-provisioned private configuration and existing worker grants, not helper profile JSON or browser startup payloads. Explicitly plan their propagation to the API/worker; starting a database cannot fix absent credentials. If reconfiguration requires an API restart, show the credential-clearing and queued-work implications and require a separate confirmation.

## 7. Files expected to change and why

| Existing / proposed source | Responsibility |
| --- | --- |
| Existing `docker/workbench/workbench.py`, `runtime.py` | Independent bootstrap, offline profile discovery and API-only paused startup while retaining current ownership/recovery logic |
| Proposed `docker/workbench/control.py` plus focused stdlib tests | Installed host helper, pairing, exact-profile lifecycle operations and small startup receipt store |
| Existing `docker/workbench/nginx.dev.conf`, `nginx.prod.conf`, `compose.yaml` | Same-origin control proxy and narrow read-only socket-directory mount; no Docker socket |
| Existing `web_api/__main__.py` | Expose existing `create_app(start_paused=...)` through an explicit launcher option |
| Existing `web_api/readiness.py`, `evaluation_profiles.py`; proposed `web_api/policy_readiness.py` | Versioned workflow contracts, protocol/identity comparison and bounded worker-context checks |
| Existing `web_api/editor_execution.py`, `generation_worker.py`, `evaluation_worker.py` and supported GR00T client | Enforce source/profile/serving identity at actual dispatch and policy connection, preserving existing grants and job ownership |
| Proposed first-party `isaaclab_arena_gr00t/policy/serving_metadata.py` | Adapt the existing GR00T server registration hook for loaded-policy identity and bounded codec metadata; no vendor model fork |
| Proposed frontend `research-services.tsx`, `control-api.ts` and tests; existing `app.tsx` | API-independent stack panel, pairing/start/recheck and explicit partial-failure UI |
| Existing `workflow-readiness.tsx`, `runtime.tsx`, Build/Evaluate controls | Reuse readiness and reconnect; render action-specific blockers without losing the editor or confusing model types |
| Existing README, workbench and GR00T runbooks; focused verification selection | One-time provisioning/boot, startup-versus-experiment permissions, identity limits, isolated test admission and real acceptance instructions |

Proposed filenames are implementation targets, not claims that these modules already exist. Follow actual installed server/client APIs when freezing the wrapper interface.

## 8. Delivery slices and acceptance

Implement after plan and scoped infrastructure approval, with narrow RED→GREEN tests and independent review. Do not stop at the first row and call the full request delivered.

| Slice | Deliverable | Required exit evidence |
| --- | --- | --- |
| S1 Contracts and stronger read-only checks | Versioned workflow matrix, Neo4j worker-path probe, strict GR00T protocol/modality results, explicit unknown checkpoint | Real production API tests under network denial using synthetic protocol peers; missing route/version, malformed/error/oversized replies and no forbidden RPCs |
| S2 API-independent stack control | Paired shell panel, installed host helper, approved-ID starts, paused API bootstrap and retained startup outcomes | Isolated fake-Docker command-boundary tests plus real disposable lifecycle tests under separate approval; cold API-down browser journey and duplicate/partial/timeout/restart cases |
| S3 Correct policy identity | First-party metadata wrapper, approved loaded-artifact identity, native client comparison at connection/reconnection | Mismatched checkpoint/replay policy, changed instance, stale metadata, N1.6/N1.7 modality mismatch; metadata success cannot satisfy inference test |
| S4 Integrated workflow admission | Action-specific blockers, source/profile binding, explicit inference smoke and readiness display after Start | Actual-App/browser tests; no effect on refresh/pairing/metadata/checks, no queued work released by startup, no stale readiness authorizing a replacement policy |
| S5 Approved local acceptance | Existing Arena + existing Neo4j + intended GR00T model through one user-facing URL | Approved exact targets/entrypoints/resources; genuine protocol/database/identity evidence, separately approved inference and Build smoke, exact receipts and preserved data/services |

**First usable vertical checkpoint (S1 + S2):** open the cold API-down stack panel, pair, Start the approved existing services, observe paused API startup, reconnect and execute the real consented dependency checks through the same URL. Unverified policy evaluation stays disabled. This checkpoint is useful preparation functionality, not completion of correct-model/transport/evaluation requirements; S3–S5 remain required.

Acceptance walkthrough: open dashboard with Arena stopped; panel remains available; pair and review Start; only approved stopped services start; wrong GR00T model remains blocked; correct server connects under the expected instance/model contract; Neo4j is checked from the actual worker context; missing graph credentials remain actionable; API starts paused; subsequent explicit A2 generation records the exact consumed priors. Build still has to diagnose the floating-object problem; stack readiness does not close geometric acceptance or the missing repair-loop integrations.

Negative cases also include unrelated listener, missing container, same-name replacement, changed model mount, unreviewed auto-download entrypoint, low GPU memory, missing runtime dependency, incompatible API schema, revoked control session, hostile Origin, helper/profile tampering, service death after check and partial startup. Keep old jobs/specs/database volumes unchanged.

## 9. Review and external sources

Read-only discovery reviews covered native GR00T protocol/identity and stopped-Arena control/security. They found the missing identity RPC, session-gated readiness UI, dependency on running Arena during launcher discovery, and absent CLI paused-start flag. A separate independent plan review required explicit cold-bootstrap API-directory ownership, transport-as-admission evidence, and a method/path/request/decoder/readback coverage ledger, and recommended a first usable vertical checkpoint. The parent added all four clarifications above and checked the relevant source boundaries. These are reviewed design findings and parent amendments, not an independently rerun closure verdict, implementation approval or live startup tests.

Primary references:
- [Docker Engine security](https://docs.docker.com/engine/security/): Docker daemon access is a sensitive control boundary.
- [docker container start](https://docs.docker.com/reference/cli/docker/container/start/): starts existing stopped containers; it is not provisioning or entrypoint side-effect isolation.
- [PyZMQ API](https://pyzmq.readthedocs.io/en/stable/api/zmq.html): own bounded socket/context lifetimes; unclosed sockets can block termination, and destroying sockets from other threads is unsafe.
- [Existing GR00T evaluation guide](../../../../docs/pages/example_workflows/agentic_env_gen/eval_with_gr00t.rst): intended DROID checkpoint, modality/version and array-transport distinctions.
