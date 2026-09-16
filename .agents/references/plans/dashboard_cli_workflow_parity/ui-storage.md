# F3 UI storage ownership and transactional preferences

Status: bounded UI-storage implementation and verification complete. This extends F3; it does not complete the broader V7 plan or authorize deployment/live workloads. Draft-controller, guarded sessionStorage, transactional IndexedDB preferences and notification-only BroadcastChannel are implemented and independently reviewed. Parent verified 1591 production frontend tests across 64 files (11 offline-preview files excluded), typecheck/build, the real manual-research browser journey and scoped approval of nine native storage cases. Exact runs and limits are in implementation progress and `web/arena-workbench/tests/e2e/functional-v7/.runs/ui-storage-scoped-acceptance.json`. Native raw proofs retain PARTIAL/acceptance:false; parent approval is separately recorded, not a rewrite of machine results. Shared frontend remains stopped.

Preimplementation review `deleg_42f1666e` supported the architecture but required precise remount/lease/fallback/migration and transaction-outcome contracts. The amendments below resolve those requirements before implementation. Those planning clarifications were followed by implementation reviews and the bounded runtime evidence above; the design text itself is not proof of execution.

## Scope and observed baseline

- `src/draft-storage.ts` directly replaces/removes `arena.editor.draft.v1` in sessionStorage. `editor.tsx` persistence depends on rendering/loading transitions; a stale operation can overwrite a newer backup even when its document GET is retired.
- `src/environment-library.tsx` replaces the whole `arena.environment-library.v1` localStorage value from an effect. Readback detects some failures but is not transactional lost-update protection.
- Existing session, catalogue, source/hash, research-detail and snapshot epochs remain necessary. A storage adapter is not a substitute for those guards.
- Preserve pending save/research/publication/renewal records byte-for-byte and retain their existing controllers, keys and permission rules. No credentials, CSRF data, API clients or verified-source authority enter the new stores. User-authored YAML itself can be sensitive; this work does not claim browser-side DLP or encryption.
- No backend schema, Journal, ResearchStore, deployment, provider, GPU, Docker infrastructure, package dependency or offline V7 artifact changes.

## Selected mechanisms

1. One typed draft/persistence controller owned by the retained Editor, subscribed through React `useSyncExternalStore`. No module-global shared editor state or second QueryClient. Existing server metadata/validation continues in TanStack Query.
2. Guarded sessionStorage adapter for draft backups, retaining tab-local lifetime. A read/compare/write is synchronous within supported same-tab application writers; it is NOT a cross-context Web Storage transaction or a security boundary against malicious same-origin code. All production draft writers use the controller. A same-tab controller registry retires a replaced owner; duplicated tabs recover copied bytes under fresh runtime ownership.
3. Native IndexedDB read/write transactions for shared Library preferences, through one bounded typed adapter. No new npm dependency. IndexedDB remains a convenience cache, not the authoritative research store.
4. BroadcastChannel carries only bounded invalidation notifications after commit. It supplies no lock, source evidence or operation permission. Missing/broken notifications are recovered by rereading on focus/visibility; transactions alone protect shared updates.

Alternatives: localStorage readback cannot make cross-tab read-modify-write atomic. Web Locks plus localStorage would require a second correctness mechanism and unsupported-lock fallback. Migrating all YAML/retries to IndexedDB would unnecessarily change lifetime and recovery contracts. Redux/Zustand is unnecessary for one typed store; use the already installed React API.

## Draft controller and backup contract

Proposed modules: `draft-controller.ts` plus existing `draft-storage.ts` codec/adapter. Names are implementation targets, not claims that they exist yet.

- Controller commands: edit draft/prompt, capture/check Open ownership, accept source replacement, restore/discard recovery, persist eligible current content, retire owner. Separate transient status from persisted content.
- Snapshot identity stays stable until actual state changes. `subscribe` has symmetric cleanup; creation is inert, mount/retirement is StrictMode-safe. No storage writes, subscriptions or timer side effects from speculative render.
- Retain one authoritative content snapshot/controller for the existing QueryClient authoring lifetime, replacing the effect-mirrored content portion of `['editor-draft']`, not introducing a second writable copy. Retain the exact original backup baseline, revision, pending recovery and conflict/unavailable latches WITH the content. Warm remount compares against that baseline; it must never pair retained A with newly read sibling B as writable authority. Keep existing same-client validation reuse and replacement-generation revalidation; validation/source context may be retained alongside the controller but must not become another mutable draft store.
- Registry scope is the actual sessionStorage object/key within this application JS realm, with runtime instance identity and monotonic activation generation only (no YAML/client data). Every committed activation acquires a fresh generation; identity-checked cleanup permanently retires that generation. StrictMode setup after cleanup acquires another generation, never reactivates old tokens. A replaced instance cannot release its successor. Arbitrary external storage bytes changed and restored between observations cannot be detected; the supported guarantee is temporal fencing of cooperating controllers plus exact observed-byte comparison.
- Advance a safe monotonic draft revision synchronously on meaningful edits (including prompt changes and A→B→A), before React renders or debounce runs. Preserve same-value CodeMirror echo behavior. Freeze owner/revision/source and exact backup baseline before confirmation and GET; recheck after confirmation, every async completion/hash check, and immediately before replacement.
- Capture a handler eligibility token when controls render. Check it BEFORE acquiring a new operation token at click/dispatch; an old rendered callback cannot borrow a current revision after same-turn ABA. Route raw edits, prompt edits, initial/default/recovery/legacy document loads, explicit Library/research/receipt Open, legacy selection, generated Apply, reviewed-position Apply, Restore and Discard through commands. Source replacement/recovery disposition retires operations even when YAML is equal. Initial/default/recovery loads must not fabricate Recent/Open success evidence.
- A pending Open whose backup was replaced, removed or became uninspectable is retired. It cannot replace the draft or publish verified inventory/Recents. Releasing loading does not authorize persistence. A fresh explicit action in known memory-only mode may remain usable, but an in-flight action cannot silently downgrade to that mode.
- Persistence is content-command/revision driven, not a side effect of loading/validation/layout changes. First implementation may use bounded synchronous writes for eligible edits; no debounce is required. If debouncing is used, freeze expected revision and cancel stale work. No async work between sessionStorage baseline comparison and write/remove.
- Proposed v2 record preserves the existing bounded source fields/YAML/prompt and adds `draftId` and safe integer `revision`. Runtime lease/session ownership is not restored from these fields. Keep the existing key for discovery and decode v1 explicitly; migrate only a validated, still-owned baseline after explicit recovery or eligible authoring, never blindly overwrite unknown bytes.
- Distinguish absent, valid, invalid-record, conflict and unavailable. Malformed/oversized/unknown-version bytes are not absence. Compare-and-remove applies to both explicit Discard and clean-state deletion. Compare-and-write/readback failure latches a notice and retains current in-memory inputs; never adopt a sibling backup as permission to write.
- Preserve pending recovery across navigation. Explicit Restore validates exact current source identity (fresh research view UUID is allowed only by existing exact identity rules). Explicit Discard targets the captured record only. Download remains independent of API validation/storage availability.
- Freeze v1 serialized bound at 600000 JavaScript string code units; v2 at 601024, with unchanged per-field draft/prompt/source limits, UUID draftId and nonnegative safe-integer revision. Test exact inclusive boundaries independently. Pre-write rejection/atomic setItem failure leaves old stored bytes intact. If setItem succeeds but readback fails, persistence is ambiguous: retain captured v1 bytes in controller memory, withhold success and never blindly roll back a possibly replaced record. Same-key migration does not guarantee durable retention of v1 after successful replacement. Browser restart/session restore follows browser semantics; this is not permanent or power-loss-safe draft storage.

Draft storage transitions:

| State/event | Action and exit |
| --- | --- |
| Initially unreadable storage | Announced memory-only mode; no writes/removes; fresh explicit source actions remain usable under normal guards. |
| Readability lost during an Open | Retire the captured operation and latch memory-only state. Only a newly rendered explicit action may operate there. |
| Invalid/conflicting bytes | Preserve them, current content and captured recovery/download; block persistence and replacement. Offer explicit Review stored backup to inspect current bytes, not silently adopt them. |
| Failed compare/remove or ambiguous readback | Retain unresolved recovery/disposition and error state across remount; do not report successful Discard. |
| Explicit Review stored backup | Retire old operations; reread and expose an exact new recovery choice without replacing current content or enabling automatic writes. Still-unavailable storage stays memory-only. |
| Successful explicit Restore/Discard | Bind to the displayed recovery and current handler generation. Restore rechecks exact source. Discard conditionally replaces recovery with eligible current dirty content in one setItem, or removes it if clean; no later loading-effect flush. Clear obligation only after verified success. |
| Persistence later becomes readable | No automatic promotion/replay. Explicit reconciliation is required; ordinary edits remain in memory until then. |

## Transactional Library preferences

Proposed modules: `library-preferences.ts` (codec, adapter and observable controller) and production integration in `environment-library.tsx`. Reuse `environment-library-contract.ts` exact reference codecs and existing 8-pin/12-recent bounds.

- Database `arena-workbench-ui`, schema version 1; object store `libraryPreferences`, key `default` for the current single-workspace same-origin UI. This is not cross-account synchronization; a future multi-workspace/account product needs an explicit scope migration. Persist references only, never verified catalogue rows, raw YAML, credentials or Open capability.
- Envelope: schema version, monotonic safe integer revision, validated existing preferences. Validate reads AND the serialized post-operation record. Refuse corruption/overflow, never silently reset.
- Commands are `pin(reference)`, `unpin(reference)`, `recordOpened(reference)` and refresh. Every command opens a read/write transaction, reads the latest record, applies just that operation, validates bounds and writes. Only transaction completion establishes persistence success; request success followed by abort is failure. Do not do API fetches or unrelated awaits inside transactions.
- Pin and recordOpened admission remains with current UI/source authority. Capture a runtime owner guard; check before dispatch and again at the transaction mutation boundary. Retired queued operations are not admitted. Finalizers may release owned busy state but cannot publish into a replacement controller.
- Detach and validate the entire reference, including nested research identity, at command creation. At the transaction read callback, recheck the original runtime owner and applicable source admission before mutation. That is the admission point: an already admitted transaction may commit after subsequent retirement; suppress stale controller/UI publication, but do not promise retroactive cancellation. A committed transaction is not permission to Open a document.
- `transaction.oncomplete` fixes committed outcome. Later notification or refresh failure cannot relabel it aborted or trigger a retry. A newer sibling value on readback is valid, not byte-mismatch failure. Monotonic revision plus connection/request epochs keep delayed initialization/refresh from replacing newer local observations. At the pin limit, reject only the excess distinct pin as `limit` (no eviction, no storage-unavailable state); exact duplicates are no-ops.
- Never persist an entire stale component snapshot. Ordinary concurrent valid preference commands merge serially and do not revoke a separately verified document Open merely because another tab pinned something. Corrupt/replaced storage or controller retirement withholds preference writes. Recents are recorded only AFTER the editor actually accepted an exact verified Open; a cancelled/stale Open emits no command. This removes the lost-update race without claiming an atomic transaction spanning IndexedDB, HTTP and React state.
- Import valid legacy localStorage preferences only when the IndexedDB record is genuinely absent, within the same write transaction as initial insertion. Recheck the captured legacy value before migration. Preserve legacy bytes; do not dual-write or automatically reimport later old-tab changes. If legacy bytes are malformed or IndexedDB upgrade is blocked, preserve them and show an explicit unavailable/recovery notice rather than pretending empty success.
- Legacy recheck is best-effort observed-value consistency, NOT an atomic transaction across localStorage and IndexedDB. Concurrent initializers serialize the absent→present IndexedDB insertion. After initialization, disappearance, revision regression or different contents at the same revision is a conflict; never reinitialize that connection. Ordinary newer revisions are valid. A fresh mount after complete database deletion has no surviving marker distinguishing history from first use and may import the still-valid legacy value; permanent no-reimport detection is outside scope.
- Handle blocked upgrades, versionchange, database deletion, transaction abort, quota/read errors, notification failure and unmount. Close connections/channels/listeners. No retry timers or silent persistent fallback. Existing visible preferences may remain memory-only with a clear notice; no success message may imply persistence.
- Memory fallback is an explicit state, not a second durable store. If IndexedDB is unavailable initially, ordinary browsing remains usable; safe in-memory pin operations must still meet source admission and cannot destroy legacy data. Restoration grants no fresh verification.
- While initializing, withhold preference mutations explicitly (no unbounded command queue). Blocked/error/versionchange/deletion transitions are terminal for that connection attempt: invalidate its epoch, abort pending upgrade work where possible, and close late successful connections. Late callbacks cannot initialize/flush after fallback or unmount. Memory-only commands are never replayed automatically into persistence. A new explicit connection attempt or remount rereads durable state and does not silently merge memory changes. Coalesce notification-triggered read-only refreshes; ignore message revisions/payloads as authority and never rebroadcast refresh results.

## Cross-module boundary / implementation ownership

Draft owner: `draft-controller*`, `draft-storage*`, `editor.tsx`, `editor-library.integration.test.tsx`, and necessary editor tests. Preserve Library's current public props; no direct edits to preference implementation.

Preferences owner: `library-preferences*`, `environment-library.tsx/.test.tsx` and narrow preference contracts/tests. No editor/research/snapshot changes. Existing `opened` confirmation remains the only recent-registration input, so no shared-file integration seam is needed initially.

Parent: plan/progress, harness/browser acceptance and assembled verification. Freeze public interfaces before changing cross-owner files. Request independent scoped reviews after GREEN; do not count an owner-reported pass as parent verification.

## Scenario table and exit evidence

These are design walkthroughs until executed; every required case needs a named regression.

| Case | Required result |
| --- | --- |
| Edit during deferred Open; draft A→B→A | Old Open cannot replace content or emit Open/Recent evidence. |
| Backup replacement during confirmation/GET/hash | Preserve exact replacement bytes and current inputs; retire old operation. |
| Index retirement after backup replacement | Loading cleanup cannot write/remove the newer backup. |
| Pending Restore/Discard versus sibling replacement | Do not restore/delete sibling bytes; show conflict and keep Download. |
| Layout/navigation, remount and StrictMode | Retain content/recovery; no duplicate writer or unmount flush. |
| Session/client replacement with same public ID | Old controls and delayed writes remain retired; no permission from stored IDs. |
| Invalid/oversized/unavailable storage and quota | Preserve old record; honest memory-only status; no automatic retry/POST. |
| Two tabs concurrently pin distinct references | Both operations survive, subject to the existing bounded pin policy. |
| Concurrent unpin/recent update and same-reference operations | Latest transaction state is used; no stale whole-record overwrite. |
| Transaction request success then abort | No durable-success acknowledgement; reread actual database state. |
| Legacy migration, blocked upgrade and stale old tab | No data deletion, dual-write or surprise reimport. |
| Channel missing/out-of-order/foreign messages | At most a bounded reread; no source authority or network mutation. |
| Real research Open→Recent→pin→reopen/reload | Exact identity verified; preferences remain hints and backend recovery remains intact. |
| Warm remount A after external backup B | Retained baseline remains A; B cannot become permission to persist A. |
| StrictMode activation/cleanup/activation and retained handler | Fresh generation is usable; old generation never revives. |
| Queued transaction versus retired source/nested-reference mutation | Original detached command is revalidated before admission; no borrowed permission. |
| Competing pins at capacity | One serial result; excess returns limit without eviction or degraded storage. |
| Commit followed by channel/refresh error | Committed outcome remains committed; no automatic replay. |
| Late initialization/refresh versus newer commit | Older snapshot cannot replace newer observation. |
| Blocked open later succeeds; versionchange; record disappears | Close/abort retired attempt; no fallback flush, surprise initialization or reimport. |
| Forged notification and repeated focus events | Bounded/coalesced reads only, no writes, source authority or notification loop. |

Entry: independent plan review, current source inventory and approved isolated dependency preflight. Implement each behavior through RED→GREEN. Then run focused cohorts, ordinary typecheck/build and current full frontend enumeration (report exclusions/any unresolved baseline separately). Exercise real IndexedDB with separate same-origin browser pages; inert adapter tests do not prove transactions. Run the existing genuine manual-research-v1 profile only after storage implementation review and security closure; extend browser coverage for Library preferences separately rather than claiming the old driver covers it. No model/graph/render calls are authorized.

Keep immutable run artifacts, failed proofs and exact source hashes. Read back records in tests, verify cleanup and count unique cases programmatically. Do not claim deployment, full V7 or durable backend changes from this slice.

## Rollback

Do not delete or rewrite accepted V7 previews, existing draft backups, legacy preferences or pending receipts. A source rollback must not reinterpret v2 records as v1; unsupported versions remain recoverable/downloadable through the new code and untouched by failed migration. Do not advertise automatic backwards compatibility with older writers. Reverting transactional preferences must disable persistent writes rather than restore unsafe dual writers; retain IndexedDB records for forward recovery.

## References

- React subscription/snapshot requirements: https://react.dev/reference/react/useSyncExternalStore
- IndexedDB transaction lifecycle/upgrade coordination: https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API/Using_IndexedDB
- Tab-local storage and copied opener state: https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage
- BroadcastChannel notifications: https://developer.mozilla.org/en-US/docs/Web/API/Broadcast_Channel_API
