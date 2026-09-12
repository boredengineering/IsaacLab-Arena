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

## Subsequent improvements

### Phase 2: Dedicated preview catalogue

Add an authenticated read-only receipt lookup keyed by canonical hash so recovery is independent of the bounded job journal. Include renderer/version and asset/USD revision fingerprints in cache identity, bounded retention/cleanup, and missing-artifact invalidation. Test eviction and stale source dependencies before adding automatic cache retrieval. Do not turn a GET into a render.

### Phase 3: Better visual inspection

Add an asset/scene preview switcher, thumbnail loading indicators, scene-first camera framing, and per-asset camera controls. Extend the renderer to support isolated embodiment thumbnails. Investigate object-reference isolation/framing: the saved table-reference PNG loads but visually shows mostly the grid. Round displayed dimensions while retaining full precision in metadata. Return structured per-asset errors and partial-success results, not a single generic failed job. Keep authored graph relationships distinct from rendered evidence.

### Phase 4: Responsive rendering workflow

Separate cheap catalogue thumbnails from scene-dependent previews. Reuse asset thumbnails only with asset/version/constructor identity; use explicit bounded jobs for changed scenes. Add cancellable queued progress, renderer timing metrics, lazy image decoding and image-resolution variants. Gate automatic preview mode behind explicit user opt-in and resource budgets.

## Evaluation

Implemented recovery, canonical matching and bounded/deduplicated history, render controls beside Assets, image retry, lazy zoom, and scene-only robot labels. Regression testing also exposed workspace cache collection across route changes; the snapshot cache now outlives routes.

Verification: 55 frontend unit tests passed, type checking and production build passed, and six real browser tests passed. Browser checks loaded five existing asset PNGs plus the scene, recovered them after navigation/reload, marked a semantically changed draft stale, retried a deliberately interrupted artifact request on mobile, and exercised zoom/dark mode. They submitted no rendering, generation or save work. Scoped pre-commit checks passed. The build retains its existing large-chunk warning.

One existing save/generation unit test failed once with stale empty mutation input during the full run, then passed alone and in the full rerun; this was not reproduced in the real browser preview checks and was not changed as part of preview recovery.

No new GPU or model job was needed: existing-artifact checks verified five asset PNGs and one scene PNG. Image retrieval is not a simulation-policy success claim. Isolated robot thumbnails and the poorly framed reference thumbnail remain renderer improvements, not completed work.
