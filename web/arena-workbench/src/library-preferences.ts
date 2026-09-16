import { createNativeLibraryAdapter, createLibraryNotifications } from './library-preferences-native';
import {
  decodeLibraryPreferences, emptyLibraryPreferences, referenceKey, LIBRARY_PREFERENCES_KEY,
  LIBRARY_PIN_LIMIT, LIBRARY_RECENT_LIMIT,
  type LibraryPreferences, type LibraryReference,
} from './environment-library-contract';

/** Adapter callbacks run synchronously inside a native record-read success event.
 * The returned promise resolves only on transaction completion, never request success. */
export interface LibraryAdapter {
  open(onLost: () => void): Promise<void>;
  transaction(mode: 'readonly' | 'readwrite', mutate: (raw: unknown) => unknown): Promise<unknown>;
  close(): void;
}
export interface LibraryNotifications {
  subscribe(hint: () => void): () => void;
  post(): void;
  close(): void;
}
export interface LibraryPreferencesOptions {
  adapterFactory: () => LibraryAdapter;
  readLegacy: () => string | null;
  notifications?: () => LibraryNotifications;
}
export interface LibrarySnapshot {
  mode: 'initializing' | 'persistent' | 'memory';
  preferences: LibraryPreferences;
  notice: string;
}
export type LibraryOutcome = 'initializing' | 'committed' | 'memory' | 'noop' | 'limit' | 'retired' | 'unavailable' | 'invalid';
/** Mount-local hints, never source authority. Creation is inert; activate in an effect. */
export function createLibraryPreferencesController(options: LibraryPreferencesOptions = {
  adapterFactory: () => createNativeLibraryAdapter(),
  notifications: () => createLibraryNotifications(),
  readLegacy: () => globalThis.localStorage.getItem(LIBRARY_PREFERENCES_KEY),
}) {
  let snapshot: LibrarySnapshot = {mode: 'initializing', preferences: emptyLibraryPreferences(), notice: 'Loading Library preferences…'};
  let observed = emptyLibraryEnvelope();
  let adapter: LibraryAdapter;
  let epoch = 0;
  let active = false;
  let activation = 0;
  const retired = new Error('Retired Library command');
  const malformedLegacy = new Error('Malformed legacy preferences');
  let notifications: LibraryNotifications | undefined;
  let unsubscribe: (() => void) | undefined;
  let refreshing: Promise<void> | undefined;
  let refreshAgain = false;
  const listeners = new Set<() => void>();
  const publish = (next: LibrarySnapshot) => {snapshot = next; listeners.forEach(listener => {try {listener();} catch { /* Observers cannot change transaction outcome. */ }});};
  function closeNotifications() {
    try {unsubscribe?.();} catch { /* Best-effort cleanup. */ }
    try {notifications?.close();} catch { /* Best-effort cleanup. */ }
    unsubscribe = undefined; notifications = undefined;
  }
  function notifyFailure() {publish({...snapshot, notice: 'Library notification unavailable; refresh on focus remains available.'});}
  function observe(value: LibraryEnvelope) {
    // A read admitted before a newer local observation may complete afterward.
    if (value.revision < observed.revision) return;
    if (value.revision === observed.revision && JSON.stringify(value) === JSON.stringify(observed) && snapshot.mode === 'persistent') return;
    observed = value;
    publish({...snapshot, mode: 'persistent', preferences: value.preferences});
  }
  function refresh(): Promise<void> {
    if (!active || snapshot.mode !== 'persistent') return Promise.resolve();
    if (refreshing) {refreshAgain = true; return refreshing;}
    const owner = epoch;
    // One in-flight read and one coalesced trailing hint; no queue or timers.
    const work = Promise.resolve().then(() => {
      if (!active || owner !== epoch) throw retired;
      refreshAgain = false;
      return adapter.transaction('readonly', raw => {
        if (!active || owner !== epoch) throw retired;
        return checked(raw);
      });
    }).then(raw => {
      if (active && owner === epoch) observe(decodeLibraryEnvelope(raw)!);
    }).catch(() => fallback(owner)).finally(() => {
      if (refreshing !== work) return;
      refreshing = undefined;
      if (refreshAgain && active && owner === epoch) {refreshAgain = false; void refresh();}
    });
    refreshing = work;
    return work;
  }
  function fallback(owner: number, notice = 'Library preferences unavailable; using memory for this mount.') {
    if (owner !== epoch || !active) return;
    epoch++; adapter?.close(); closeNotifications();
    refreshing = undefined; refreshAgain = false;
    publish({...snapshot, mode: 'memory', notice});
  }
  function checked(raw: unknown) {
    const value = decodeLibraryEnvelope(raw);
    if (!value || value.revision < observed.revision || (value.revision === observed.revision && JSON.stringify(value) !== JSON.stringify(observed))) throw new Error('Library preference conflict');
    return value;
  }
  function activate() {
    adapter?.close(); closeNotifications();
    refreshing = undefined; refreshAgain = false;
    const owner = ++epoch;
    const lease = ++activation;
    active = true;
    observed = emptyLibraryEnvelope();
    publish({mode: 'initializing', preferences: emptyLibraryPreferences(), notice: 'Loading Library preferences…'});
    let legacy: string | null | undefined;
    try { legacy = options.readLegacy(); } catch { /* Existing IndexedDB needs no legacy access. */ }
    try {
      const connection = options.adapterFactory();
      adapter = connection;
      void connection.open(() => fallback(owner)).then(() => {
        if (!active || owner !== epoch) {connection.close(); throw retired;}
        return connection.transaction('readwrite', raw => {
          if (!active || owner !== epoch) throw retired;
          if (raw !== undefined) {
            const value = decodeLibraryEnvelope(raw);
            if (!value) throw new Error('Invalid Library preferences');
            return value;
          }
          // Observed-value consistency only: localStorage and IDB are not one transaction.
          if (legacy === undefined || options.readLegacy() !== legacy) throw new Error('Legacy preferences unavailable');
          const preferences = legacy === null ? emptyLibraryPreferences() : decodeLibraryPreferences(legacy);
          if (!preferences) throw malformedLegacy;
          return {schemaVersion: 1, revision: 0, preferences};
        });
      }).then(raw => {
        if (!active || owner !== epoch) return;
        const value = decodeLibraryEnvelope(raw);
        if (!value) throw new Error('Invalid Library preferences');
        observed = value;
        publish({mode: 'persistent', preferences: observed.preferences, notice: ''});
        if (!active || owner !== epoch) return;
        try {
          notifications = options.notifications?.();
          unsubscribe = notifications?.subscribe(() => {if (active && owner === epoch) void refresh();});
        } catch {notifyFailure();}
      }).catch(error => fallback(owner, error === malformedLegacy ? 'Stored Library references are malformed or unsupported; preserved. Using memory for this mount.' : undefined));
    } catch { fallback(owner); }
    return () => {if (lease === activation && active) {active = false; epoch++; adapter?.close(); closeNotifications(); refreshing = undefined; refreshAgain = false;}};
  }
  async function command(type: LibraryCommand['type'], reference: LibraryReference, guard: () => boolean): Promise<LibraryOutcome> {
    if (!active) return 'retired';
    if (snapshot.mode === 'initializing') return 'initializing';
    const owner = epoch;
    const admitted = () => {try {return guard() === true;} catch {return false;}};
    if (!admitted()) return 'retired';
    let detached: LibraryReference | undefined;
    try {detached = decodeCommandReference(type, reference);} catch { /* Invalid caller value. */ }
    if (!detached) return 'invalid';
    const operation = {type, reference: detached};
    const outcome: {status: LibraryChange['status']} = {status: 'noop'};
    try {
      if (snapshot.mode === 'memory') {
        const change = applyLibraryCommand({...observed, preferences: snapshot.preferences}, operation);
        if (change.status === 'changed') publish({...snapshot, preferences: change.envelope.preferences});
        return change.status === 'changed' ? 'memory' : change.status;
      }
      const raw = await adapter.transaction('readwrite', raw => {
        if (!active || owner !== epoch || !admitted()) throw retired;
        const change = applyLibraryCommand(checked(raw), operation);
        outcome.status = change.status;
        return change.envelope;
      });
      if (active && owner === epoch) {
        observe(decodeLibraryEnvelope(raw)!);
        if (outcome.status === 'changed') {try {notifications?.post();} catch {notifyFailure();}}
      }
      return outcome.status === 'changed' ? 'committed' : outcome.status;
    } catch (error) {
      if (error === retired || !active || owner !== epoch) return 'retired';
      fallback(owner);
      return 'unavailable';
    }
  }
  return {activate, refresh, getSnapshot: () => snapshot,
    captureOwner() {const owner = epoch; return () => active && owner === epoch;},
    subscribe(listener: () => void) {listeners.add(listener); return () => {listeners.delete(listener);};},
    pin: (reference: LibraryReference, guard: () => boolean) => command('pin', reference, guard),
    unpin: (reference: LibraryReference, guard: () => boolean) => command('unpin', reference, guard),
    recordOpened: (reference: LibraryReference, guard: () => boolean) => command('recordOpened', reference, guard),
  };
}

export interface LibraryEnvelope { schemaVersion: 1; revision: number; preferences: LibraryPreferences }
export type LibraryCommand = { type: 'pin' | 'unpin' | 'recordOpened'; reference: LibraryReference };
export type LibraryChange = { status: 'changed' | 'noop' | 'limit'; envelope: LibraryEnvelope };
export const emptyLibraryEnvelope = (): LibraryEnvelope => ({schemaVersion: 1, revision: 0, preferences: emptyLibraryPreferences()});
export function decodeLibraryEnvelope(value: unknown): LibraryEnvelope | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return;
  const row = value as Record<string, unknown>;
  if (Object.keys(row).sort().join(',') !== 'preferences,revision,schemaVersion' || row.schemaVersion !== 1
    || !Number.isSafeInteger(row.revision) || (row.revision as number) < 0) return;
  try {
    const preferences = decodeLibraryPreferences(JSON.stringify(row.preferences));
    if (preferences) return {schemaVersion: 1, revision: row.revision as number, preferences};
  } catch { /* Untrusted cache, never authority. */ }
}
function decodeCommandReference(type: LibraryCommand['type'], reference: LibraryReference): LibraryReference | undefined {
  const value = decodeLibraryPreferences(JSON.stringify({version: 1, pins: type === 'pin' ? [reference] : [], recents: type === 'pin' ? [] : [reference]}));
  return type === 'pin' ? value?.pins[0] : value?.recents[0];
}
export function applyLibraryCommand(current: LibraryEnvelope, command: LibraryCommand): LibraryChange {
  const reference = decodeCommandReference(command.type, command.reference);
  if (!reference || !decodeLibraryEnvelope(current)) throw new Error('Invalid Library preferences');
  const key = referenceKey(reference);
  const preferences = {...current.preferences};
  if (command.type === 'pin') {
    if (preferences.pins.some(item => referenceKey(item) === key)) return {status: 'noop', envelope: current};
    if (preferences.pins.length >= LIBRARY_PIN_LIMIT) return {status: 'limit', envelope: current};
    preferences.pins = [...preferences.pins, reference];
  } else if (command.type === 'unpin') preferences.pins = preferences.pins.filter(item => referenceKey(item) !== key);
  else preferences.recents = [reference, ...preferences.recents.filter(item => referenceKey(item) !== key)].slice(0, LIBRARY_RECENT_LIMIT);
  if (JSON.stringify(preferences) === JSON.stringify(current.preferences)) return {status: 'noop', envelope: current};
  const envelope = decodeLibraryEnvelope({schemaVersion: 1, revision: current.revision + 1, preferences});
  if (!envelope) throw new Error('Invalid Library preferences');
  return {status: 'changed', envelope};
}
