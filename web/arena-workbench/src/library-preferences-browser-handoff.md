# Library preferences: browser fixture handoff

## Public test seam (no production globals or extra component props)

Import `createLibraryPreferencesController` from `./library-preferences` in a trusted, same-origin test entry. Creation is inert; call `activate()` only at fixture mount and call its returned cleanup at retirement. Capture `captureOwner()` when rendering retained handlers and compose that predicate with current source admission; it never revives after activation replacement or terminal fallback. Subscribe with `subscribe(listener)`, inspect `getSnapshot()` (`mode`, `preferences`, `notice`), and dispose the subscription separately. `refresh(): Promise<void>` is read-only, coalesced, and disabled in initialization/memory mode.

Commands are `pin(reference, admissionGuard)`, `unpin(reference, admissionGuard)`, and `recordOpened(reference, admissionGuard)`. Each returns `Promise<LibraryOutcome>`: `committed`, `noop`, `limit`, `initializing`, `memory`, `retired`, `unavailable`, or `invalid`. A guard must return literal `true`; it is checked before dispatch and synchronously at the transaction read callback. The reference is validated and detached, including nested research provenance, at command creation. Fixture `() => true` is synthetic preference admission, **not** evidence of real source verification.

The default controller uses real browser IndexedDB, legacy localStorage reads, BroadcastChannel, focus, and visible-document notifications. Optional `LibraryPreferencesOptions` allows an `adapterFactory`, `readLegacy`, and `notifications` factory. Omitting `notifications` in an explicitly supplied options object disables notifications; production's no-argument default supplies them. `LibraryAdapter.open(onLost)` resolves the connection, `transaction(mode, mutate)` invokes a synchronous mutation callback inside a native record-read success callback (get, or count when proving absence) and resolves only on transaction completion, and `close()` retires that connection attempt. No API or unrelated awaited work belongs in `mutate`.

`./library-preferences-native` exports `createNativeLibraryAdapter(factory?: () => IDBFactory)`, `createLibraryNotifications`, and these fixed constants:

- `LIBRARY_DATABASE = 'arena-workbench-ui'`
- `LIBRARY_DATABASE_VERSION = 1`
- `LIBRARY_STORE = 'libraryPreferences'` (out-of-line keys)
- `LIBRARY_RECORD_KEY = 'default'`
- `LIBRARY_CHANNEL = 'arena-workbench-library-preferences'`
- `LIBRARY_NOTIFICATION = 'library-preferences-changed/v1'` (the entire allowed message)

Stored value: `LibraryEnvelope = {schemaVersion: 1, revision: nonnegativeSafeInteger, preferences: {version: 1, pins: LibraryReference[], recents: LibraryReference[]}}`. `decodeLibraryEnvelope`, `emptyLibraryEnvelope`, `applyLibraryCommand`, and their types are exported. Existing reference codecs, legacy key, serialized preference bound (16384 JavaScript code units), 8-pin and 12-recent limits remain in `environment-library-contract`. Production `EnvironmentLibrary` props and the parent `opened: {source, sequence}` handshake are unchanged. Restored references do not populate its fresh-source confirmation inventory.

## Native acceptance still required

The checked-in tests exercise pure reducers, a deterministic adapter boundary, production React integration with that boundary or memory fallback, and scripted IDB event wiring. They **do not** establish native transaction isolation, actual browser quota behavior, real cross-page BroadcastChannel, or browser acceptance.

Use separate same-origin pages in an isolated browser context with synthetic valid references and no API/provider/workload requests. Independently read the exact native record after writes. Exercise:

1. Concurrent distinct pins; unpin versus recent update; duplicate operations; competing eighth/ninth pins. Both valid operations survive serialization; only the excess distinct pin returns `limit`.
2. Real native put request success followed by transaction abort: no committed outcome and no durable mutation. A bounded test-only event hook may abort the transaction; do not replace IDB with a fake.
3. Native `get()` returns undefined both for absence and for a stored undefined value. Verify the adapter's same-transaction `count()` rejects stored undefined rather than reinitializing it. A transaction queued behind a native sibling readwrite transaction, then owner/source retirement before get-success. No mutation is admitted. Separately retire **after** admission: commit is allowed but retired UI publication is suppressed.
4. Legacy absent/valid/malformed/changed-before-import, concurrent first initializers, unchanged legacy bytes, no dual writes, and later old-tab edits not reimported.
5. Record disappearance, valid revision regression, and different preferences at the same revision. They latch memory mode rather than reinitialize; ordinary newer revisions are accepted.
6. Versionchange/deletion, late opening success after retirement, notification failure after commit, missing BroadcastChannel, foreign/oversized message values, repeated focus/visibility, and bounded read-only refreshes without rebroadcast.
7. Reload from durable IDB references, explicit actual production research Open → Recent → pin → reopen, and independent fresh source/permission verification. Adapter fixtures cannot substitute for this real-app source test.

## Native API constraints and limits

- Native IndexedDB transactions serialize writes; BroadcastChannel never locks or carries source permission. Commands during initialization are rejected, not queued. Memory changes never auto-flush; a new explicit activation/remount rereads durable state without merging them.
- The mutation callback is the admission linearization point, **not** request dispatch or transaction completion. Closing an IDB connection does not retroactively undo an already admitted transaction. Completion determines committed outcome; notification failure cannot relabel it aborted or cause replay.
- Schema version 1 is the minimum native database version. A normally existing version-1 database cannot serve as a lower-version connection blocking a version-1 upgrade. The scripted `onblocked` branch is tested, but a real blocked-upgrade fixture must disclose any test-only higher-version factory wrapper; it is not an ordinary fixed-v1 production-open scenario. Real higher-version opens/deletion can exercise production `versionchange` retirement.
- Native transaction liveness does not survive arbitrary `await`/timer gaps. A fixture holding a transaction must issue bounded requests within its event callbacks and release it explicitly; otherwise a supposed queued race may never occur.
- Legacy recheck is best-effort observed-value consistency, not an atomic transaction across localStorage and IndexedDB. A fresh mount after complete database deletion cannot distinguish first use from deletion and may import still-valid legacy bytes again. No surviving marker, permanent storage, account isolation, encryption, or power-loss guarantee is claimed.
