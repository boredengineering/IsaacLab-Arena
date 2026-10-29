import type { LibraryAdapter, LibraryNotifications } from './library-preferences';

export const LIBRARY_DATABASE = 'arena-workbench-ui';
export const LIBRARY_DATABASE_VERSION = 1;
export const LIBRARY_STORE = 'libraryPreferences';
export const LIBRARY_RECORD_KEY = 'default';
export const LIBRARY_NOTIFICATION = 'library-preferences-changed/v1';
export const LIBRARY_CHANNEL = 'arena-workbench-library-preferences';

/** Notifications contain no references, revisions or authority. */
export function createLibraryNotifications(): LibraryNotifications {
  let channel: BroadcastChannel | undefined;
  try {channel = new BroadcastChannel(LIBRARY_CHANNEL);} catch { /* Focus remains available. */ }
  let cleanup: (() => void) | undefined;
  return {
    subscribe(hint) {
      const focus = () => hint();
      const visible = () => {if (document.visibilityState === 'visible') hint();};
      if (channel) channel.onmessage = event => {if (event.data === LIBRARY_NOTIFICATION) hint();};
      window.addEventListener('focus', focus);
      document.addEventListener('visibilitychange', visible);
      cleanup = () => {
        window.removeEventListener('focus', focus);
        document.removeEventListener('visibilitychange', visible);
        if (channel) channel.onmessage = null;
      };
      return cleanup;
    },
    post() {if (!channel) throw new Error('Notification unavailable'); channel.postMessage(LIBRARY_NOTIFICATION);},
    close() {cleanup?.(); channel?.close(); channel = undefined;},
  };
}

/** One terminal connection attempt; no timers, reconnects or persistent fallback. */
export function createNativeLibraryAdapter(factory: () => IDBFactory = () => globalThis.indexedDB): LibraryAdapter {
  let database: IDBDatabase | undefined;
  let opening: IDBOpenDBRequest | undefined;
  let terminal = false;
  let rejectOpen: ((error: Error) => void) | undefined;
  const failure = () => new Error('Library preferences unavailable');
  function close() {
    terminal = true;
    rejectOpen?.(failure()); rejectOpen = undefined;
    try { opening?.transaction?.abort(); } catch { /* Already settled upgrade. */ }
    database?.close();
  }
  return {
    open(onLost) {
      if (terminal || opening) throw failure();
      // Resolve browser properties only at activation, never speculative render/import.
      const indexedDB = factory();
      if (!indexedDB) throw failure();
      return new Promise<void>((resolve, reject) => {
        rejectOpen = reject;
        const request = indexedDB.open(LIBRARY_DATABASE, LIBRARY_DATABASE_VERSION);
        opening = request;
        const lost = () => {if (!terminal) {close(); onLost();}};
        request.onblocked = lost;
        request.onerror = lost;
        request.onupgradeneeded = () => {
          if (terminal) {try {request.transaction?.abort();} catch { /* Closed. */ } return;}
          const db = request.result;
          if (!db.objectStoreNames.contains(LIBRARY_STORE)) db.createObjectStore(LIBRARY_STORE);
        };
        request.onsuccess = () => {
          const db = request.result;
          if (terminal) {db.close(); return;}
          database = db;
          db.onversionchange = lost;
          db.onclose = lost;
          rejectOpen = undefined;
          resolve();
        };
      });
    },
    transaction(mode, mutate) {
      return new Promise<unknown>((resolve, reject) => {
        if (terminal || !database) {reject(failure()); return;}
        let result: unknown;
        let error: unknown;
        const transaction = database.transaction(LIBRARY_STORE, mode);
        transaction.oncomplete = () => resolve(result);
        transaction.onabort = () => reject(error ?? failure());
        transaction.onerror = () => { /* Abort is the definitive failure event. */ };
        const store = transaction.objectStore(LIBRARY_STORE);
        const request = store.get(LIBRARY_RECORD_KEY);
        request.onerror = () => {error = failure();};
        const abort = (caught: unknown) => {
          error = caught;
          try {transaction.abort();} catch {reject(error);}
        };
        const apply = (raw: unknown) => {
          try {
            result = mutate(raw);
            if (mode === 'readwrite' && JSON.stringify(result) !== JSON.stringify(raw)) store.put(result, LIBRARY_RECORD_KEY);
          } catch (caught) {abort(caught);}
        };
        request.onsuccess = () => {
          if (request.result !== undefined) {apply(request.result); return;}
          // get() alone cannot distinguish absence from a stored undefined value.
          // Keep this existence read inside the same native transaction.
          try {
            const count = store.count(LIBRARY_RECORD_KEY);
            count.onerror = () => {error = failure();};
            count.onsuccess = () => {if (count.result === 0) apply(undefined); else abort(failure());};
          } catch (caught) {abort(caught);}
        };
      });
    },
    close,
  };
}
