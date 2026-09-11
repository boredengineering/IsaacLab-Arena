# Workbench localhost session and header fix

## Confirmed root cause

The frontend is served at both localhost:3001 and 127.0.0.1:3001, but the Python API was launched with origin http://127.0.0.1:3001. Its middleware compares Host to that single authority. A request through localhost receives 403 Host not allowed, while the numeric loopback health request succeeds. The session route also requires the single configured Origin. Consequently session establishment fails before SharedWorker/SSE observation starts. Reconnect repeats the rejected request; it cannot fix server configuration. The proxy correctly preserves the browser Host and must continue doing so.

## Implementation plan

1. Regress localhost session creation against a numeric-loopback-configured API, and regress right-aligned theme placement at desktop/mobile sizes.
2. For a configured localhost or 127.0.0.1 origin only, allow exactly those two authorities with the same configured scheme and port. Require any supplied Origin to match the request Host and configured scheme. Keep mutation Origin mandatory, CSRF mandatory, host-only HttpOnly cookies, and foreign host/port/scheme rejection. Do not use wildcards, trust forwarding headers, or change Docker networking.
3. Move the existing theme switch after navigation at the far right of the top sidebar; retain an upper-right mobile position with navigation below.
4. Run backend security regressions, frontend unit/type/build checks, restart only the workbench API/frontend through its owned launcher, and exercise the user's exact localhost URL in a real browser.
5. Verify initial session, live stream, explicit reconnect after a controlled session-request failure, reload, navigation, theme persistence, and no generation/render/save/job submissions. Repeat on numeric loopback and verify hostile origins/hosts remain blocked.

## Scope

No credential reads, model calls, GPU work, graph publication, Docker infrastructure edits, commits, or unrelated undo changes. Hostnames remain separate browser origins: cookies, local storage, and SharedWorkers are not shared across localhost and 127.0.0.1. Users should stay on one hostname for a draft.

## Evaluation

- RED: API regression returned 403 for localhost; desktop browser placement regression found the switch left of navigation. The live localhost reconnect test failed against the old running API.
- GREEN: 104 workbench backend tests passed, one opt-in test skipped; 46 frontend unit tests passed. Type checking and production build passed (existing large-chunk warning remains).
- Four real browser tests passed: reconnect/live observation on each loopback hostname, desktop theme/draft/reload behavior, and upper-right mobile placement. No job/generation/render/save submissions were made by these browser checks.
- Direct browser inspection at http://localhost:3001/workspaces/default?filter=all showed Live · shared stream, no alerts, and the theme switch to the right of navigation.
- Full regression found one isolated graph-router test fixture missing the new Host-to-Origin mapping; updated its fixture and reran the full suite successfully.
- Restart initially hit the launcher's transient port-availability check after shutdown; there was no remaining frontend listener. A later start passed unchanged. No Docker infrastructure edits were needed.
