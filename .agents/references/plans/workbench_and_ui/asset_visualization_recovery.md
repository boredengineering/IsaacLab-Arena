# Asset visualization recovery and improvement plan

## Confirmed cause

A fresh localhost editor displays six 'Not rendered' cards and no images. The workspace journal contains five successful snapshot jobs matching the current validated canonical scene hash. All five asset artifact URLs and the scene URL return real PNG data with HTTP 200. The renderer/artifact transport is therefore working for this scene.

`useSnapshots()` rebuilds history only from the single job retained in browser sessionStorage. New tabs, cleared tab storage, and switching hostname lose that pointer despite durable server jobs. Assets blindly use history[0], which can also belong to a different scene. The only render action is below the graph/tasks rather than beside empty assets. The robot's intentionally unsupported isolated thumbnail looks identical to an unrendered object. Image failures cannot be retried and closed zoom dialogs eagerly fetch their full images.

## Implement now

1. Regress preview recovery from real workspace job data with empty browser storage, and mismatched/newer scene results.
2. Derive bounded render history from successful validated workspace receipts, plus the retained job for compatibility. Prefer exact canonical scene matches; retain same-document older renders only with explicit stale labels. Never infer a current scene from asset IDs alone.
3. Move the explicit Render snapshots action and job progress to Assets. Keep GPU work explicit; loading/reloading or typing must not submit jobs.
4. Distinguish unsupported embodiment thumbnails from missing previews; surface image failures with an explicit retry. Only load zoom images when opened.
5. Verify real images in a fresh localhost browser, reload/navigation recovery, image retry, current/stale matching, mobile/dark-mode layout, and zero automatic submissions. Run full frontend tests/type/build and scoped hooks. No new GPU render is necessary if existing exact-match artifacts verify.

## Follow-up scope (implemented; verification below)

### Phase 2: Dedicated preview catalogue

Add an authenticated read-only receipt lookup keyed by canonical hash so recovery is independent of the bounded job journal. Include renderer/version and asset/USD revision fingerprints in cache identity, bounded retention/cleanup, and missing-artifact invalidation. Test eviction and stale source dependencies before adding automatic cache retrieval. Do not turn a GET into a render.

### Phase 3: Better visual inspection

Add an asset/scene preview switcher, thumbnail loading indicators, scene-first camera framing, and per-asset camera controls. Extend the renderer to support isolated embodiment thumbnails. Investigate object-reference isolation/framing: the saved table-reference PNG loads but visually shows mostly the grid. Round displayed dimensions while retaining full precision in metadata. Return structured per-asset errors and partial-success results, not a single generic failed job. Keep authored graph relationships distinct from rendered evidence.

### Phase 4: Responsive rendering workflow

Separate cheap catalogue thumbnails from scene-dependent previews. Reuse asset thumbnails only with asset/version/constructor identity; use explicit bounded jobs for changed scenes. Add cancellable queued progress, renderer timing metrics, lazy image decoding and image-resolution variants. Gate automatic preview mode behind explicit user opt-in and resource budgets.

## Evaluation

### Implementation acceptance for phases 2–4

Implementation and final integration verification are complete within the documented freshness/pose limitations:

- [x] Authenticated read-only catalogue lookup survives journal-history removal and never launches a worker.
- [x] Cache identity includes canonical spec, normalized camera/resolution options, renderer revision and verifiable asset revisions; unknown remote freshness is explicit/fail-closed.
- [x] Bounded retention removes only owned, unreferenced preview storage; missing or modified PNGs invalidate receipts.
- [x] Actual table-reference image frames its intended prim, rather than an unresolved namespace or empty grid.
- [x] Actual isolated embodiment image renders the robot, with no fabricated/cropped stand-in.
- [x] Scene and per-asset camera presets and selected render resolution affect real outputs.
- [x] Reusable isolated thumbnails are independent of unrelated scene edits but invalidated by their asset/options identity.
- [x] Partial asset failures preserve usable outputs and return structured errors and measured timings.
- [x] Thumbnail/full variants remain authenticated and are selected appropriately by the UI.
- [x] Asset/scene switching, loading indicators, precise-versus-rounded dimensions and partial errors are usable in light/dark and mobile layouts.
- [x] Queued/running preview cancellation uses existing verified worker cleanup, not a local-only UI state change.
- [x] Automatic previews are off by default; explicit opt-in has debounce, rate/job budget, one in-flight job and no ambiguous submission replay.
- [x] Frontend cache misses/invalidation cannot be overridden by stale journal receipts or stale request completions.
- [x] Unit/security tests, actual GPU captures, cache-hit verification, browser checks, scoped hooks and architecture documentation agree.

### Integration verification (phases 2–4)

Current integration evidence: real GPU probe `/eval/arena-preview-renderer-verification/run2` produced two camera/resolution variants. Visual inspection exposed missing Z-up/meter metadata in composed robot USDs; the shared composition helper now declares both, with a failing-then-passing regression and an upright real robot image. A cold render exceeded 210 seconds while loading materials; the bounded request budget is now 360 seconds.

The real API test also exposed inconsistent canonical-hash serialization. `Documents` and `SnapshotService` now share `canonical_digest`; execution rejects mismatches instead of silently relabelling them. Live job `d64e01a2a92249728d28445d83512512` published six assets plus a scene, each with 1024px full and 256px thumbnail variants. Catalogue recovery returned explicit historical/unverified-asset freshness. Queued cancellation `c1c7ad3257ef4398aff115da2df335f7` and running cancellation `dda1518b9c7a42239a089f760e3004c5` were read back as cancelled. Local acceptance downloads are under `/tmp/arena-preview-live-acceptance`.

Final checks: 205 Python tests passed, with one GPU-gated test skipped and one legacy subprocess test deselected; this count includes the legacy GUI CPU coverage. All 77 frontend unit tests passed. Nine Chromium checks passed: six against the live session/theme/artifact stack and three explicitly labelled protocol fixtures for automation/cancellation/error paths. Production image, TypeScript/Vite, Sphinx and scoped pre-commit checks passed. This is not a full repository test run.

Both independent-review findings are fixed and re-review passed without blockers. Resolved scale/reference-parent defaults are included before raw-cache lookup and frozen for capture. Directory-inode leases coordinate publication and retention; current/legacy orphan temporaries and orphan metadata consume age/byte/count budgets. The 23 targeted regressions include process-crash recovery. The earlier asynchronous Save input race is also fixed with explicit click-time variables.

Final deployed job `457097fc6dab464a8a0224daf721ba96` succeeded on the corrected renderer revision. All six asset PNGs and the scene were fetched as 1024px full and 256px thumbnail variants; the robot and table-reference pixels were visually inspected. Catalogue readback matched the canonical hash/cache key and returned historical/unverified-asset freshness. Queued cancellation `3c69152597374341ac39ce4b5319d957` was read back cancelled. The prior running-cancellation verification remains applicable to the unchanged lifecycle code.

Remaining limits: mutable remote USD dependency freshness cannot be established by the current registry; historical pixels are never treated as fresh render-cache hits. Verified reuse requires a configured complete local dependency revision provider; automatic registry-wide discovery is not implemented. Robot thumbnails use the authored USD joint pose, not simulated configured joints. Cold material loading is bounded at 360 seconds and upstream material warnings/large JavaScript chunk warnings remain. No policy-success inference, model calls or commits were made.

### Earlier recovery evaluation (phase 1)

Implemented recovery, canonical matching and bounded/deduplicated history, render controls beside Assets, image retry, lazy zoom, and scene-only robot labels. Regression testing also exposed workspace cache collection across route changes; the snapshot cache now outlives routes.

Verification: 55 frontend unit tests passed, type checking and production build passed, and six real browser tests passed. Browser checks loaded five existing asset PNGs plus the scene, recovered them after navigation/reload, marked a semantically changed draft stale, retried a deliberately interrupted artifact request on mobile, and exercised zoom/dark mode. They submitted no rendering, generation or save work. Scoped pre-commit checks passed. The build retains its existing large-chunk warning.

One existing save/generation unit test failed once with stale empty mutation input during the full run, then passed alone and in the full rerun; this was not reproduced in the real browser preview checks and was not changed as part of preview recovery.

No new GPU or model job was needed: existing-artifact checks verified five asset PNGs and one scene PNG. Image retrieval is not a simulation-policy success claim. Isolated robot thumbnails and the poorly framed reference thumbnail remain renderer improvements, not completed work.
