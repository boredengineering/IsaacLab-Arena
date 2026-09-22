# Plan 04 S2 — IF-A initialization-feasibility and approval packet

Status: IF-A COMPLETE — REVIEWED PACKET READY FOR APPROVAL; EXECUTION CLOSED. No implementation or experiment executed. S2 is selected. This packet specifies a proposed implementation/effect envelope, not executable capabilities that already exist. Approval must explicitly cover the requested changes and effects; old import approval does not suffice. No automatic S1/S3 pivot. Safety/lifecycle review passed; the budget critic's single accounting finding is resolved in §7 and the retained budget ledger.

Governing plan: [Plan 04 P1/IF-A–IF-D and §8](event-mapping-refactoring_plan_04.md). Dispositions belong in the [review ledger](event-mapping-refactoring_plan_04-review.md); [canonical handoff](dashboard_cli_workflow_parity/research-stack-implementation-handoff.md) owns implementation state.

## 1. Source identity, evidence and readiness

IF-A intake: `2026-09-22T23:38:56Z`, HEAD `4dd679599dea3e9682d463380d31d8fe89bb3fb1`, branch `dev/0.3.0-prerelease`, clean checkout. Baseline: `outputs/workflow/plan04-planning/s2-if-a/baseline.json` (394 captured files, not a claim of complete reviewed coverage). Parent parsed 384 Python files as syntax only. Final documentation/source verification will bind this packet after review.

Retained evidence was rechecked without running packages:

- `s2-if-a/retained-evidence-check-corrected.json`: six retained cohorts' repository and generated source hashes match; historical 563 case occurrences, not new tests or E1 acceptance. The initial generated-file lookup mistake remains in `retained-evidence-check.json`; no failed runtime evidence was replaced.
- `s2-if-a/dependency-evidence.json`: 21 retained final-probe evidence leaf hashes match, including the started-process record carrying image-source observations. No native-library individual hashes were observed in that frontier.
- Prior source/input evidence under `outputs/workflow/plan04-implementation/installed-execution/`: `checkpoint-verification.json`, `registration-context-parent-verification.json`, `registration-final-checkpoint.json`, `native-initialization-decision.md`, and failed `joined-runs/` are preserved.
- `join-spec.md` is historical. Its old `result-status` and unwired metadata-probe statements are superseded by current harness lines 1052–1056 and 1516–1519. Its source-byte totals are not a new freeze. The 379-repository/383-total inventory is current at intake; implementation must recapture it, never inherit stale byte hashes.

Known: actual server/worker source paths and retained immutable-image Python evidence. Unknown: successful registration, native binary/linker identities, cache routing in practice, needed memory/time, current image/container availability and resource liveness. No current Docker inspection, credential read, DB access or application import was performed. Read-only discovery `deleg_0f7bd2fb` informs this draft; it is not its fresh critic review.

## 2. Exact reusable environment bindings

| Binding | Frozen value / provenance |
| --- | --- |
| Runtime image | `sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd` |
| Provision manifest | `outputs/workflow/plan03-implementation/graphql-provisioning/implementation/arena-f0-graphql-provision-fea7e278760f/provision-manifest.json` |
| Manifest SHA-256 | `03764536ed54c1f59cbf46305c5bc4ba618e2dc1deeeac7ffdfb21a0dffbf810` (parent readback matches) |
| Disposable DB image | `sha256:037cf5756f0135cbfd66b739b6df7c7c4bb100f9ce11602f6f9538e17e02c74d` |
| SDK parent image | `sha256:e20b3cc8258b793aaf1fe47c130f54e677fa9c0a6427991cfc1045b743162da5` (historical recipe parent, not an alternative image choice) |
| Runtime interpreter | `/isaac-sim/kit/python/bin/python3 -I -S -B` for owned children; existing outer image launch uses `/isaac-sim/python.sh -I -S` |
| Client identity | UID:GID `1000:1000`, supplementary group `1234`; no root runtime |
| DB identity | UID:GID `7474:7474`; database `workflowtest`, existing synthetic scope/binding and sentinel-only setup |
| Recipe pins | `/opt/arena-f0/provision-recipe.json`: `18ab4e13d3a0a4dc88390d852c632c437fcf980847e19b58d81b7ee74b111753`; `/opt/arena-f0/graphql-test-v1-recipe.json`: `4470dde2d4822e1cd4ecd451dbe534d772aab0037cd49b9c5aec508a51562aaf` |

Selected dependency evidence (presence is not import compatibility): Isaac Lab `6.1.14`, Torch `2.10.0+cu128`, USD core `25.11`, Warp `1.13.0`, purelib OpenAI `3.3.1`; a distinct prebundle OpenAI `2.32.0` exists and is **not** an automatic fallback. OpenAI 3.3.1's `httpx2`/`jiter` declarations are unresolved at this evidence level. Use the current exact PyYAML 6.0.3 binding at `/isaac-sim/exts/omni.pip.compute/pip_prebundle/yaml`, not its whole parent as an import root.

Retained source pins, rechecked against the recorded immutable-image observations, not freshly read inside an image:

- `/isaac-sim/kit/python/lib/python3.12/site-packages/warp/_src/context.py`: `40948811fbc2e99773883f762cc0eb939718b11d26676739e4332b13337d5ee2`.
- `/isaac-sim/kit/python/lib/python3.12/site-packages/warp/config.py`: `9a1ca6a287d599e64286e600dff2c929022fb1d0d836e4f68af31217f547325c`.
- `/isaac-sim/kit/python/lib/python3.12/site-packages/warp/__init__.py`: `4a272a0c07b087b8f43710ebb061f02b1bc002a1bf4f701c336528c64a6ba2f7`.
- Isaac Lab `utils/warp/__init__.py`: `c5bd9c6ab69725f706d7586a2c560fdf9d45c6145f5d387412dd2fbc878d6c7d`; initializer/setup and OpenAI pins are enumerated in `s2-if-a/dependency-evidence.json`.

Source-derived native candidates: `.../warp/bin/warp.so` and optional `.../warp/bin/warp-clang.so`. Their physical existence, sizes, hashes and linker dependencies are **not observed**. Do not fabricate them. The requested trust boundary is the exact existing image plus reviewed module/origin selection, not a fictional complete native manifest. Future in-attempt preflight must verify image/recipes and record selected actual binary identities before explicit Python extension/ctypes loading where interceptable. Native transitive loader dependencies remain an image-trust residual, recorded through bounded loaded-map observations; no exhaustive native reverse engineering is required or claimed.

## 3. Real entrypoints and minimal proposed changes

Current source, not new APIs:

1. `workflow/api/server.py:123–144`: `supervise` calls `installed_execution.compose` before constructing resources. `installed_execution.py:24–76` checks guarded synthetic mode/capability then imports real schema/foreground/catalogue code. These imports precede the later `execution_catalogue_sha256()` call at line 259. Environment/origin/effect controls must precede both, not just the named catalogue call.
2. `web_api/catalogues.py:36–48`: real catalogue builders; `assets/registries.py:365–385`: background → device → HDR → object → retargeter → embodiment → policy → relation → task imports. No registry substitution, skipping families or digest fixture is allowed.
3. `workflow_graphql_execution_join_harness.py:1531–1593`: fresh model bootstrap invokes `install_synthetic_sdk(scene=True)` before real `scene_worker.main`. `web/arena-workbench/tests/e2e/functional-v7/generation_worker_fixture.py:357–362` already performs actual `ArenaEnvGraphSpec.model_validate(minimal_spec_dict())`. Preparing caches/guards only inside `scene_worker.execute` is too late.
4. `web_api/scene_worker.py:183–204`: actual generate/refine catalogue construction, digest comparison and refinement schema parsing. Assessment has a separate cold import path. IF-B must cover server, generate, refine and assess startup separately, not infer all workers from a warmed parent.
5. Server readiness follows successful application lifespan boot (`workflow/api/application.py:123–140`). A listener, a fixture marker or parent cleanup is not application readiness/drain evidence.

Proposed implementation ownership, **not changed in IF-A**:

| Owner slice | Permitted future files | Acceptance |
| --- | --- | --- |
| S2 harness/runner | `scripts/run-workflow-neo4j-checks.py`, `scripts/workflow_graphql_execution_join_harness.py`, `scripts/workflow_graphql_execution_join_fixture.py`; one proposed new `isaaclab_arena/tests/test_environment_workflow_initialization_neo4j.py` | Explicit-only selector/cases, pre-import origin/cache/environment controls, bounded native diagnostics, aggregate deadline/quota/collection, no old-mode guard changes |
| Narrow production startup/validation seam | `workflow/api/installed_execution.py`, `workflow/api/server.py`, `web_api/scene_worker.py`; only if needed, one shared `workflow/registration_bootstrap.py` (proposed, nonexistent) | Extract/call the real registration/schema preparations without changing bodies/semantics, support a genuine before-readiness failure point, preserve existing one-use composition capability and legacy imports/defaults |
| Proof reader/regressions | Existing joined/lifecycle/import-boundary tests and the proposed test above | Real source-bound results, refusal, cold roles, exact cleanup, unchanged query-only/legacy positive behavior |

Prefixes above resolve within `isaaclab_arena/agentic_environment_generation/` for `workflow/`, and `isaaclab_arena_examples/agentic_environment_generation/` for `web_api/`. Do not edit Docker/CI/pre-commit files, submodules, provider implementations, registries/classes, or build/install dependencies. No new daemon, metadata service or orchestration framework. Any shared-helper change outside this list requires a scoped amendment; do not copy the full helper to evade ownership.

The production seam is not permission to manufacture a ready state or call a duplicate schema. It must be used by the actual installed path and cold workers. IF-B diagnostic preparation proves initialization semantics only; IF-C uses the real installed launcher/server, and IF-D proves the entire application route.

### Existing compatibility modifications requiring explicit treatment

`JoinGuards` currently installs `platform.processor = lambda: os.uname().machine` at line 1525. S2 must not use that substitution to claim unmodified native initialization. Keep old cohorts unchanged; S2 omits this assignment and retains the real stdlib implementation. Permit at most one fixed CPU-metadata subprocess per native-initializing role **only** with exact argv `uname -p`, no shell, fixed `PATH=/usr/bin:/bin`, read-only image executable origin/identity verification and bounded output (4 KiB)/deadline (2 s). Record actual occurrence; other argv/process discovery is denied. This is a proposed explicit allowance, not evidence that the pinned implementation needs or can perform it. If it needs a different operation, stop rather than patch the result.

The existing synthetic SDK transport and its SDK-platform fixture remain synthetic test infrastructure, labelled as such; no claim of unmodified provider/network behavior. Real Warp `init`, `Runtime`, `CDLL`, registry methods and Pydantic validators are never replaced or suppressed.

## 4. Effects, enforcement and admitted trust

All S2 controls install before any relevant package import in each cold role. Current Python guards alone are not a general native-code sandbox.

| Effect | Proposed policy and mechanism | Evidence / residual |
| --- | --- | --- |
| Native load/init | Permit real reviewed registration-triggered loading and initialization of trusted bytes in the fixed image, including `wp_init`, CPU/library setup and driver/toolkit/NVRTC capability queries | Selected Python extension/ctypes origins recorded and verified before load where interceptable; bounded `/proc` mappings after load. ELF constructors/internal calls are trusted image behavior, not individually proven inert |
| GPU probing vs workloads | Permit unsuccessful driver/device probing with **no GPU device exposure**. Prohibit GPU kernel work, simulator/Kit launch, physics/rendering, policy inference, USD asset-stage opening | Preserve no devices/device requests/privilege/capabilities and preflight `/dev/nvidia*`/`/dev/dri` absence; reject positive usable-device outcome. Source-call guards support named runtime denials but do not observe every native CPU call. No driver or GPU installation |
| External services | No real provider/policy/production DB, DNS or acquisition. Exact disposable DB and loopback/control endpoints only | Reuse internal IPv4 network/no gateway/no IPv6/no published ports and per-role Python socket/callsite guards. Native direct syscalls inside the isolated network are a disclosed trust residual; no secrets/shared targets are exposed there |
| Providers | IF-B/IF-C: zero model/backend/OpenAI constructors and zero SDK sends; HTTP-client setup used to install synthetic transport may occur. IF-D: only existing four model roles/eight synthetic sends | Server cannot construct a provider. Synthetic transport must be ready before allowed model constructors; real catalogue validation before installation is controlled by environment/guards, not hidden |
| Writes | Read-only root, dependencies, source and network manifests. Owned tmpfs caches and bounded tmpfs evidence only; no shared HOME, Docker socket or credential mounts | Kernel read-only/quota boundaries, before/after own cache manifest; no general arbitrary host writes. Any unredirectable required cache destination refuses instead of remounting broadly |
| Processes | Fixed role/argv tree, no shell or arbitrary exec; optional fixed `uname -p` allowance above. Kernel PID cap limits native threads/processes | Python audited spawn identities plus bounded process snapshots; native clone is not fully mediated by Python. Trusted libraries are not adversarial code; unexplained descendants/cleanup uncertainty are nonpass |
| Diagnostics | Preserve structured exception coordinates, bounded raw native stderr/exit/signal, mappings and resource observations | Do not keep server stderr at DEVNULL in S2. Screen sentinel/private values before public summaries; incomplete/overflow evidence cannot certify success. No live secrets supplied |

Residual trust acceptance is not permission to perform a prohibited effect. If a required prohibition lacks the claimed control/assurance basis at final review, do not launch. The approval explicitly accepts trusted pinned native initialization and limited observations; it does not certify resistance to malicious native code.

### Owned cache configuration

For each invocation create a fresh `/tmp/s2-init/<case>/<role>/` with mode 0700, owned by 1000:1000, checked without following links. In each child launch environment set `HOME=<role>/home`, `XDG_CACHE_HOME=<role>/cache`, `TMPDIR=<role>/tmp`, `WARP_CACHE_PATH=<role>/cache/warp`; create only these owned directories before imports. Keep `PATH=/usr/bin:/bin`, `NVIDIA_VISIBLE_DEVICES=void`, `CUDA_VISIBLE_DEVICES=` and BLAS/OMP/MKL thread caps 1. Retain explicit `-I -S -B`; `-I` does not disable arbitrary application environment variables.

Retained Warp `config.py:110–121` documents `WARP_CACHE_PATH`; this is supported configuration, not a guessed CUDA-disable flag. Real resolved `warp.config.kernel_cache_dir` must stay beneath the role root, including the version subdirectory. Actual `build.init_kernel_cache` bytes/ancillary writes remain a preflight check, not a verified fact. If environment sanitizers drop these variables or initialization occurs first, fail. Do not import Warp early just to set configuration or patch its cache initializer.

## 5. Numerical bounds — proposed changes are explicit

| Limit | IF-B/IF-C proposed | Existing E1 / reason |
| --- | --- | --- |
| Client memory/swap/PIDs/CPU | **4 GiB / 4 GiB / 256 / 1 CPU** | E1 is 768 MiB/128 PIDs/1 CPU. Explicit requested increase, not inherited authority. Reuses the existing scene-cohort ceiling; not an observed S2 requirement or host-capacity claim |
| DB, where required by IF-C | 1 GiB memory/swap,128 PIDs,1 CPU; existing bounded DB tmpfs | Unchanged; IF-B pure registration roles need no DB reads/writes; don't start one just to simulate admission |
| Client filesystem | Root/source read-only; `/tmp`128 MiB; evidence **32 MiB tmpfs**; shm16 MiB; caps dropped/no-new-privileges/private IPC | `/evidence` is currently an unquotaed host bind. S2 must implement bounded tmpfs collection, not claim collection-time checks are a write quota |
| Cold role | 40 s hard external deadline each; 4 sequential roles maximum IF-B; one native-initializing installed server IF-C | Existing model alarm30/server145 differ; new diagnostic budget does not silently change legacy alarms |
| Attempt clock | 300 s total from before discovery/container creation to completion of evidence collection; all operations consume remaining time | Existing150s starts after container startup; S2 must close that gap |
| Cleanup reserve | 120 s aggregate per attempt, separate from the300s work deadline; exact group reap ≤5s; each Docker command ≤min(45s,remaining) | Existing per-command45s is not an aggregate cleanup bound. At reserve expiry record unknown, stop all launches and request exact-owner reconciliation |
| Failure timeout | After real initialization, injected pre-readiness stall is externally stopped after5s, then ≤5s exact group reap | Tests supervisor containment, **not** a native-hang simulation or guaranteed native graceful shutdown |
| Data | stdout8MiB/stderr64KiB per child; leaf4MiB; evidence32MiB aggregate; at most55 leaves; CPU-metadata stdout4KiB | Exceeding any bound is nonpass; reserve structured failure/cleanup records within the quota |
| Source | Existing8MiB total and64KiB manifest retained; exact source count recaptured after implementation | 383 is intake inventory, not permission to silently add files. If new exact inventory exceeds old count, update only new selector's reviewed literal; byte caps unchanged |
| Native preflight evidence | at most64 explicit selected binary identities; stream hashes with64KiB buffer; at most2GiB per file/8GiB cumulative reads; maps256 rows/64KiB; shares attempt deadline | Proposed bounded witness limits, not observed library sizes; no recursive whole-image enumeration, downloads or `ldd` execution |

Bounded evidence collection is a required implementation gate: keep the owned client collector alive within its300s deadline while the host obtains a bounded Docker archive of `/evidence`; no extra container exec/shell. Readiness-marker archive checks capped at30 and2s spacing within the same deadline; one final archive stream capped at36MiB including tar overhead. Reject unsafe paths/links/types and extract only the allowed evidence leaves with no-follow writes. On timeout/overflow, retain available failure metadata outside the archive and perform exact-owned teardown. No new process service; extend existing runner/collector/OwnedRun pattern. A stopped container's lost tmpfs must not be reported as successful evidence preservation.

These are ceilings, not a claim all cases fit. Resource exhaustion is inconclusive under this packet, not an automatic increase. No more memory, GPU access, image acquisition or extra runs without amended approval.

## 6. Finite IF-B/IF-C matrix and exact proposed routing

**Unavailable today:** the runner currently has only fixed existing modes and two image/manifest options. It has no IF-B/IF-C mode, `--case`, or arbitrary pytest selector. The following route is a specification to implement and review, **not a command to run now**:

```
python3 scripts/run-workflow-neo4j-checks.py workflow-graphql-initialization \
  --initialization-case positive \
  --runtime-image sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd \
  --provision-manifest outputs/workflow/plan03-implementation/graphql-provisioning/implementation/arena-f0-graphql-provision-fea7e278760f/provision-manifest.json
```

Exactly three proposed `--initialization-case` values: `positive`, `failure`, `timeout`; accepted only with the proposed explicit mode. Existing selectors/behavior remain unchanged. Fix the selected test to the corresponding single case in the proposed test file; no arbitrary `-k`, pytest passthrough or caller-supplied import/command.

| Attempt | Fixed roles and cases | Required proof |
| --- | --- | --- |
| B1 / positive | Four sequential cold roles: `init-server`, `init-generate`, `init-refine`, `init-assess`; no workflow submission, DB access or SDK send | Real preparation/catalogue/schema in each applicable path, per-role origins/cache/mappings, supported fixture normalization, unknown asset/relation/dangling-reference rejection, real unknown-YAML-field rejection, catalogue agreement/disagreement handling before constructors |
| C1 / failure | Existing installed setup2/admin5/launcher1/server1/stop≤1/status≤1; no submit/result/model workflow roles. Trigger a single fixed failure after the real registration phase and before execution readiness | Installed readiness absent/refused, no owner admission, retained original failure and exact owned-process/container/network cleanup; no invented ready state |
| C2 / timeout | Same bounded installed roles as C1; real initialization then fixed pre-readiness stall for5s, terminated externally | No readiness/admission/SDK sends, exact expected timeout/signal identity and cleanup; label as supervisor-stall evidence, not actual Warp-hang reproduction |

The B1 diagnostic child argv is proposed exactly as `[EXE, '-I', '-S', '-B', '/source/scripts/workflow_graphql_execution_join_harness.py', '--initialization', 'positive', ROLE]` with ROLE one of the four literal names above. No grandchildren except the bounded fixed CPU-metadata command. Each model preparation must reach the same early fixture validation as its installed counterpart without executing model work; extract shared real preparation only if necessary, no duplicate fake schema. Every negative case runs in its existing admitted role, not hidden extra processes.

C1/C2 reuse current exact CLI constants Q/C/I/D from `workflow_graphql_execution_join_harness.py:38–67` and `join-spec.md:11,26–42`: two setup calls, five administrative calls, `api-launch --config C --instance I`, production launcher request `[EXE,-m,isaaclab_arena.agentic_environment_generation.workflow.cli,api-serve,--config,C,--instance,I,--lease-fd,L,--gate-fd,G]` wrapped by the existing isolated CLI entry. Case selection is a fixed trusted harness capability before spawn, never an arbitrary production config hook. Stop/status are limited cleanup/readback roles, not authorization to launch a replacement server.

Per-attempt direct child ceilings: B1 four; C1/C2 ten each. Ordinary descendant ceilings: B1 four; C1/C2 eleven each including the server. Optional CPU-metadata child ceilings: B1 four; C1/C2 one each. Whole matrix:24 direct role launches,26 ordinary descendants and at most6 extra CPU-metadata descendants. PID/thread ceilings are separate. Zero provider/model sends in all three attempts. No retry or additional failed-probe allocation is hidden in these numbers; partial failures consume the attempt even if later roles were not launched.

Identity/cache refusal assertions (wrong source/image/origin, preloaded/shadow module, cache symlink/owner/out-of-root) are prelaunch/static guard tests inside the approved implementation checks; if their checks execute a native import or extra child, they must be counted in this finite matrix or separately reapproved. An invalid task-parameter case must preserve existing trace-only semantics, not invent a stronger Pydantic rejection. No S2 pass if ordinary real schema negatives are bypassed.

## 7. Budgets, outcomes and IF-D transition

**Instantiated allowance:** `outputs/workflow/plan04-planning/s2-if-a/budget-ledger.json` records start `2026-09-22T23:38:56Z` and observed closeout `23:49:11Z` (615 seconds elapsed). Conservatively charge **15 minutes** to IF-A, including all elapsed waiting and a285-second closeout reserve through `23:53:56Z`; do not refund unused reserve. One hypothesis/discovery-plus-fresh-challenge round is consumed; arithmetic closeout remains part of that round. **Zero diagnostic attempts** consumed. Remaining within the proposed total60-minute/two-round/three-attempt ceiling: **45 active minutes, one hypothesis/challenge round and three diagnostic attempts**, all still awaiting effect approval. No additional allocation is requested or implied.

Approval would permit only that remainder, not a fresh60-minute budget. Charge future implementation, source preparation, critique and experiments while this feasibility blocker is unresolved; explicit operator approval-wait is paused. The full three-attempt300s work+120s cleanup envelope reserves **1,260 seconds (21 minutes)**, leaving **24 minutes** of the remainder for implementation/review/other charged activity. These are hard ceilings, not an estimate or guarantee the implementation can fit. If implementation or a failed attempt exhausts the allowance before all gates pass, stop with partial/inconclusive evidence and one amendment request. First exhausted time/round/attempt limit stops new work; the matrix uses all three attempt slots, with no automatic correction retry.

Before each invocation, record exact source/packet/image/case identity, prior observations, changed discriminating hypothesis if repeating, expected outcomes and remaining time/attempts. Three unsuccessful corrections per defect remains an independent upper limit; in this investigation a correction also consumes remaining attempt/time allowance. At budget exhaustion perform only already-approved bounded cleanup/evidence retention. Unknown cleanup blocks all new work; never recycle identities or kill unrelated resources.

- **Feasible:** all applicable positive, refusal, identity and cleanup predicates pass under frozen limits. Advance only to an independently admitted IF-D; do not claim simulation/live acceptance.
- **Bounded implementation defect:** preserve evidence; correct only within approved file/effect scope and remaining budgets, then re-review affected final bytes.
- **Required extra effect/resource:** stop and request an explicit S2 amendment with evidence. No automatic S1/S3 fallback, wider package root, memory increase, device pass-through or install.
- **Inconclusive:** missing/overflow evidence, unobserved identity, crash/OOM/deadline before requisite witness, unresolved startup dependency or exhausted allowance. Preserve it; neither success nor proof S2 is impossible.
- **Prohibited effect:** stop/contain and record violation. Later approval cannot turn that run into a pass.

IF-D is **not included in the requested three diagnostic executions**. After IF-B/IF-C acceptance and final source refreeze, request/record a separate joined admission amendment. Existing command (valid selector, still not permitted for S2 without amendment):

```
python3 scripts/run-workflow-neo4j-checks.py workflow-graphql-execution-joined \
  --runtime-image sha256:b94e17024f1e123ac5a42759ab56651a18823fda7c701e765cba31f200154cdd \
  --provision-manifest outputs/workflow/plan03-implementation/graphql-provisioning/implementation/arena-f0-graphql-provision-fea7e278760f/provision-manifest.json
```

Preserve actual E1's12 direct/17 descendant roles and4 model children/8 synthetic SDK sends unless a separately reviewed explicit delta accounts for unmodified CPU-metadata calls. Reconcile constructor/transport timing, source inventory and additional resource/diagnostic controls with that exact run; no implicit inheritance from IF-B. Required-policy refusal and query-only regressions remain prerequisites. Readiness, authenticated submit, client detachment, worker result, durable DB/artifact agreement, fresh result readback and exact cleanup all remain required. A new registration dependency at IF-D returns to this same blocker's remaining budget, not an unlimited integration retry loop.

## 8. Exact approval requested and unresolved execution gates

Request one explicit decision covering:

1. **Implementation scope:** the files/selector/bootstrap/diagnostic/quota/deadline changes in §3–6, with unchanged legacy cohorts and independent final-source critique. No protected files, dependency installation or registry redesign.
2. **Trusted initialization effects:** reviewed class-library registration, native library initialization and capability/driver probing in the exact image without devices; owned cache writes; optional fixed CPU-metadata subprocess. Accept the stated image/native-observation residuals, not arbitrary native behavior.
3. **Resource delta and finite execution:**4GiB/256PID client cap,32MiB evidence tmpfs/collector,300s work+120s cleanup per attempt, three counted B1/C1/C2 invocations under the remaining shared investigation allocation. Existing DB caps, no-device/network/workload limits stay.
4. **Conditional release:** approval does not bypass implementation checks, actual image/recipe/native-origin/cache preflight, source refreeze or final-source critic. If any predicate cannot be established, do not run; return one consolidated blocker. IF-D and live/native simulation remain outside this request.

Outstanding before release: implement the unavailable route/seams/controls; record actual native file bindings under immutable-image trust; resolve exact supported package origin/dependency selection (including Isaac Lab path rewrites and OpenAI/httpx2/jiter); verify supported cache routing without an initializer stub; verify inherited `platform.processor` replacement is absent in S2; prove bounded native diagnostics/quota/aggregate deadline and authoritative cleanup. These are specified implementation/preflight gates, not claims already satisfied. If source review shows a materially different native/init requirement, amend S2 rather than silently expanding. IF-A can be complete as a reviewed approval packet while these execution gates remain closed.

## 9. Review and final verification

Fresh independent critics `deleg_2394928d` reviewed the complete draft. Safety/lifecycle returned PASS limited IF-A. Budget/acceptance returned one closeout finding: consumption/remaining allowance was not instantiated. Parent accepted it and supplied the conservative timestamped arithmetic above; counts remain24 direct,26 ordinary descendants and≤6 CPU-metadata descendants, with no added runs or effects. That mechanical closeout is parent-verified, not claimed as a second independent review.

Final checks and content hashes: `outputs/workflow/plan04-planning/s2-if-a/document-verification.json`; baseline, corrected retained-source readback, dependency-source checks, matrix arithmetic and budget ledger are beside it. Canonical handoff, Plan04, review ledger and shared session memory record IF-A completion and the approval gate. No staged-source import, application tests, container/image commands, native code or live services occurred. No test resources were launched; prior resource-cleanup evidence is historical, not a fresh liveness inspection. IF-B/IF-C and IF-D remain unrun; no runtime feasibility or deployed acceptance is claimed.
