// Copyright (c) 2026, The Isaac Lab Arena Project Developers.
// SPDX-License-Identifier: Apache-2.0
// Test-only parent-prop fixture. No runtime/session/ApiClient or backend responses.
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { EnvironmentLibrary, type SourceSummary } from '../../../src/environment-library';
import '../../../src/environment-library.css';

const sources: SourceSummary[] = Array.from({ length: 9 }, (_, index) => {
  const digit = (index + 1).toString(16);
  const revision = digit.repeat(32);
  return { id: `editor-revision:${revision}`, revision_id: revision,
    name: `Synthetic reference ${index + 1}`, source: `test-only/reference-${index + 1}.yaml`,
    kind: 'editor_revision', source_hash: digit.repeat(64), canonical_hash: 'a'.repeat(64) };
});
function Fixture() {
  const [opened, setOpened] = useState<{ source: SourceSummary; sequence: number }>();
  const [requests, setRequests] = useState(0);
  return <main>
    <h1>Native IndexedDB test fixture</h1>
    <p>Synthetic reference metadata and simulated parent confirmation only. NOT real API verification,
      research-source verification, authored YAML, render evidence or permission to open production data.</p>
    <output aria-label="Fixture open requests">{requests}</output>
    <section aria-label="Test-only confirmation controls">
      {sources.map((source, index) => <button type="button" key={source.id}
        onClick={() => setOpened(previous => ({ source, sequence: (previous?.sequence ?? 0) + 1 }))}>
        Confirm fixture reference {index + 1}
      </button>)}
    </section>
    <EnvironmentLibrary sources={sources} opened={opened} onOpen={() => setRequests(value => value + 1)} />
  </main>;
}
// All native instrumentation and controls live in this test entry only.
// The ordinary UI smoke still mounts the production component without options.
import { createLibraryPreferencesController } from '../../../src/library-preferences';
import { createNativeLibraryAdapter, createLibraryNotifications, LIBRARY_DATABASE,
  LIBRARY_STORE, LIBRARY_RECORD_KEY, LIBRARY_CHANNEL } from '../../../src/library-preferences-native';
import { libraryReference, LIBRARY_PREFERENCES_KEY } from '../../../src/environment-library-contract';

declare global { interface Window {
  storageFixture: ReturnType<typeof installControls>; storageManual?: boolean;
  storageInitWitness?: { raw: string }; storageModuleEntry?: { phase: string; raw: string | null; initSeen: boolean };
} }
if (window.storageManual) window.storageModuleEntry = Object.freeze({ phase: 'fixture-module-entry',
  raw: localStorage.getItem(LIBRARY_PREFERENCES_KEY), initSeen: !!window.storageInitWitness });
function installControls() {
  type Event = { seq: number; type: string; tx?: number; mode?: string; label?: string; [key: string]: unknown };
  const events: Event[] = [];
  let label = 'fixture', serial = 0, overflow = false, abortPut = false, failPost = false, sending = false;
  const connectionIds = new WeakMap<IDBDatabase, number>();
  const roles = new WeakMap<IDBDatabase, string>();
  let connectionSerial = 0;
  const connectionId = (db: IDBDatabase) => {
    if (!connectionIds.has(db)) connectionIds.set(db, ++connectionSerial);
    return connectionIds.get(db)!;
  };
  const emit = (type: string, data: Omit<Event, 'seq' | 'type'> = {}) => {
    if (events.length >= 512) { overflow = true; return; }
    events.push({ seq: events.length + 1, type, ...data });
  };
  const ids = new WeakMap<IDBTransaction, { tx: number; label: string; mode: string }>();
  const watched = new WeakSet<IDBDatabase>();
  const nativeTransaction = IDBDatabase.prototype.transaction;
  IDBDatabase.prototype.transaction = function (...args: Parameters<IDBDatabase['transaction']>) {
    const tx = nativeTransaction.apply(this, args);
    if (this.name === LIBRARY_DATABASE) {
      if (!watched.has(this)) {
        watched.add(this);
        this.addEventListener('versionchange', event => emit('native-versionchange', { connection: connectionId(this), oldVersion: event.oldVersion, newVersion: event.newVersion }));
      }
      const data = { tx: ++serial, connection: connectionId(this), role: roles.get(this) ?? 'production', label, mode: tx.mode }; ids.set(tx, data);
      emit('transaction-created', data);
      tx.addEventListener('complete', () => emit('transaction-complete', data));
      tx.addEventListener('abort', () => emit('transaction-abort', data));
    }
    return tx;
  };
  const nativeGet = IDBObjectStore.prototype.get;
  IDBObjectStore.prototype.get = function (key) {
    const request = nativeGet.call(this, key), data = ids.get(this.transaction);
    if (data && !(data.label === 'barrier' && data.mode === 'readwrite')) request.addEventListener('success', () => emit('get-success', { ...data, ...(data.mode === 'readonly' ? { raw: request.result === undefined ? null : JSON.stringify(request.result) } : {}) }));
    return request;
  };
  const nativePut = IDBObjectStore.prototype.put;
  IDBObjectStore.prototype.put = function (...args: Parameters<IDBObjectStore['put']>) {
    const raw = JSON.stringify(args[0]);
    const request = nativePut.apply(this, args), data = ids.get(this.transaction);
    if (data) request.addEventListener('success', () => {
      emit('put-success', { ...data, raw });
      if (abortPut && data.label === 'command') {
        abortPut = false; emit('abort-after-put-success', data); this.transaction.abort();
      }
    });
    return request;
  };
  const nativeDelete = IDBObjectStore.prototype.delete;
  IDBObjectStore.prototype.delete = function (key) {
    const request = nativeDelete.call(this, key), data = ids.get(this.transaction);
    if (data) request.addEventListener('success', () => emit('delete-success', { ...data, key, store: this.name }));
    return request;
  };
  const nativeClose = IDBDatabase.prototype.close;
  IDBDatabase.prototype.close = function () { emit('connection-close', { connection: connectionId(this), version: this.version }); nativeClose.call(this); };
  const fixtureChannels = new WeakSet<BroadcastChannel>();
  const messageDescriptor = Object.getOwnPropertyDescriptor(BroadcastChannel.prototype, 'onmessage')!;
  Object.defineProperty(BroadcastChannel.prototype, 'onmessage', { ...messageDescriptor,
    set(listener) {
      const channel = this as BroadcastChannel;
      messageDescriptor.set!.call(channel, listener && function (event: MessageEvent) {
        if (channel.name === LIBRARY_CHANNEL && !fixtureChannels.has(channel)) emit('production-message', { data: event.data });
        return listener.call(channel, event);
      });
    },
  });
  const nativePost = BroadcastChannel.prototype.postMessage;
  BroadcastChannel.prototype.postMessage = function (message) {
    if (this.name === LIBRARY_CHANNEL) {
      emit('notification-post', { message, source: sending ? 'fixture-sender' : 'production' });
      if (failPost) { emit('notification-post-threw'); throw new DOMException('Fixture bounded post fault', 'InvalidStateError'); }
    }
    nativePost.call(this, message);
  };
  let controller: ReturnType<typeof createLibraryPreferencesController> | undefined;
  let retire: (() => void) | undefined, unsubscribe: (() => void) | undefined;
  const owned = new Set<IDBDatabase>();
  const channels = new Set<BroadcastChannel>();
  const timers = new Set<ReturnType<typeof setTimeout>>();
  const bounded = <T,>(work: Promise<T>, operation: string): Promise<T> => new Promise((resolve, reject) => {
    const timer = setTimeout(() => { timers.delete(timer); emit('operation-deadline', { operation }); reject(Error('fixture operation deadline: ' + operation)); }, 5000);
    timers.add(timer);
    work.then(value => { clearTimeout(timer); timers.delete(timer); resolve(value); }, error => { clearTimeout(timer); timers.delete(timer); reject(error); });
  });
  let release: (() => void) | undefined;
  const boundedOpen = (version = 1) => new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(LIBRARY_DATABASE, version);
    let ended = false;
    const timer = setTimeout(() => { ended = true; reject(Error('fixture open deadline')); }, 3000); timers.add(timer);
    request.onupgradeneeded = () => {
      if (ended) { request.transaction!.abort(); return; }
      if (!request.result.objectStoreNames.contains(LIBRARY_STORE)) request.result.createObjectStore(LIBRARY_STORE);
    };
    request.onerror = () => { clearTimeout(timer); timers.delete(timer); reject(request.error); };
    request.onsuccess = () => {
      clearTimeout(timer); timers.delete(timer);
      if (ended) { request.result.close(); return; }
      roles.set(request.result, 'fixture'); owned.add(request.result); resolve(request.result);
    };
  });
  let uiRoot: ReturnType<typeof createRoot> | undefined;
  return {
    mountUI() { uiRoot = createRoot(document.getElementById('root')!); uiRoot.render(<Fixture />); },
    references: sources.map(libraryReference),
    observeConnection(db: IDBDatabase) { roles.set(db, 'observer'); },
    observationBinding(transaction: IDBTransaction) {
      const data = ids.get(transaction);
      if (!data) throw Error('unobserved readback transaction');
      const event = (type: string) => {
        const matches = events.filter(e => e.tx === data.tx && e.type === type);
        if (matches.length !== 1) throw Error('missing readback event: ' + type);
        return matches[0].seq;
      };
      return { connection: connectionId(transaction.db), tx: data.tx, created: event('transaction-created'),
        get: event('get-success'), complete: event('transaction-complete') };
    },
    audit: () => ({ events: structuredClone(events), overflow, snapshot: controller?.getSnapshot() ?? null }),
    mount(versionFault = false) {
      if (controller) throw Error('one controller per case/page');
      label = 'initialize';
      controller = createLibraryPreferencesController({ readLegacy: () => localStorage.getItem(LIBRARY_PREFERENCES_KEY),
        notifications: () => createLibraryNotifications(),
        adapterFactory: () => createNativeLibraryAdapter(versionFault ? () => ({ open(name: string, version: number) {
          emit('factory-version-fault', { requested: version, actual: 2 });
          const request = indexedDB.open(name, 2);
          request.addEventListener('blocked', () => emit('open-blocked'));
          request.addEventListener('upgradeneeded', () => {
            emit('late-upgradeneeded');
            request.transaction!.addEventListener('abort', () => emit('late-upgrade-abort'));
          });
          request.addEventListener('error', () => emit('open-error', { name: request.error?.name }));
          request.addEventListener('success', () => emit('open-success'));
          return request;
        } } as unknown as IDBFactory) : undefined) });
      unsubscribe = controller.subscribe(() => emit('snapshot', { mode: controller!.getSnapshot().mode }));
      retire = controller.activate();
    },
    async pin(index: number) {
      label = 'command'; emit('command-start', { index });
      const outcome = await bounded(controller!.pin(libraryReference(sources[index]), controller!.captureOwner()), 'pin');
      emit('command-outcome', { index, outcome }); return outcome;
    },
    async refresh() { label = 'refresh'; await bounded(controller!.refresh(), 'refresh'); },
    armAbort() { abortPut = true; emit('arm-abort'); },
    armPostFailure() { failPost = true; emit('arm-post-failure'); },
    async seed(pins: number[]) {
      label = 'seed'; const db = await boundedOpen();
      await bounded(new Promise<void>((resolve, reject) => {
        const tx = db.transaction(LIBRARY_STORE, 'readwrite');
        tx.objectStore(LIBRARY_STORE).put({ schemaVersion: 1, revision: 0,
          preferences: { version: 1, pins: pins.map(index => libraryReference(sources[index])), recents: [] } }, LIBRARY_RECORD_KEY);
        tx.oncomplete = () => resolve(); tx.onabort = () => reject(Error('seed aborted'));
      }), 'seed');
      db.close(); owned.delete(db);
    },
    async holdConnection() { const db = await boundedOpen();
      db.addEventListener('versionchange', event => emit('holder-versionchange', { oldVersion: event.oldVersion, newVersion: event.newVersion }));
      release = () => { db.close(); owned.delete(db); emit('holder-released'); }; },
    async upgrade() {
      label = 'independent-upgrade'; const db = await boundedOpen(2);
      emit('independent-upgrade-complete', { version: db.version }); db.close(); owned.delete(db);
    },
    async removeRecord() {
      label = 'delete-record'; const db = await boundedOpen();
      await bounded(new Promise<void>((resolve, reject) => {
        const tx = db.transaction(LIBRARY_STORE, 'readwrite'); tx.objectStore(LIBRARY_STORE).delete(LIBRARY_RECORD_KEY);
        tx.oncomplete = () => resolve(); tx.onabort = () => reject(Error('delete aborted'));
      }), 'remove-record');
      db.close(); owned.delete(db);
    },
    async barrier() {
      label = 'barrier'; const db = await boundedOpen();
      const tx = db.transaction(LIBRARY_STORE, 'readwrite');
      const store = tx.objectStore(LIBRARY_STORE); let released = false, count = 0;
      const timer = setTimeout(() => { emit('barrier-deadline'); released = true; try { tx.abort(); } catch {} }, 4000);
      timers.add(timer);
      tx.addEventListener('complete', () => { clearTimeout(timer); timers.delete(timer); db.close(); owned.delete(db); emit('barrier-complete', { count }); });
      tx.addEventListener('abort', () => { clearTimeout(timer); timers.delete(timer); db.close(); owned.delete(db); emit('barrier-abort', { count }); });
      release = () => { released = true; emit('barrier-release', { count }); };
      await bounded(new Promise<void>(resolve => {
        const next = () => {
          const request = store.get(LIBRARY_RECORD_KEY);
          request.onsuccess = () => {
            count++;
            if (count === 1) { emit('barrier-active'); resolve(); }
            if (!released && count < 100000) next();
            else if (!released) { emit('barrier-budget'); tx.abort(); }
          };
        }; next();
      }), 'barrier-first-read');
    },
    release() { release?.(); release = undefined; },
    async messages(messages: unknown[]) {
      if (messages.length > 32) throw Error('message budget');
      const sender = new BroadcastChannel(LIBRARY_CHANNEL), witness = new BroadcastChannel(LIBRARY_CHANNEL);
      fixtureChannels.add(sender); fixtureChannels.add(witness);
      channels.add(sender); channels.add(witness);
      // Native delivery of a trailing sentinel proves earlier native messages crossed.
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => reject(Error('message deadline')), 2000); timers.add(timer);
        let delivered = 0;
        witness.onmessage = event => {
          delivered++; emit('message-delivered', { data: event.data });
          if (delivered === messages.length) { clearTimeout(timer); timers.delete(timer); resolve(); }
        };
        sending = true;
        try { for (const message of messages) sender.postMessage(message); } finally { sending = false; }
      });
      sender.close(); witness.close(); channels.delete(sender); channels.delete(witness);
    },
    close() {
      release?.(); retire?.(); unsubscribe?.(); uiRoot?.unmount();
      for (const timer of timers) clearTimeout(timer); timers.clear();
      for (const db of owned) db.close(); owned.clear();
      for (const channel of channels) channel.close(); channels.clear();
      emit('fixture-closed');
    },
  };
}
if (window.storageManual) {
  window.storageFixture = installControls();
  document.getElementById('root')!.textContent = 'Test-only native production-controller fixture; synthetic preference admission; NO API/source verification.';
} else createRoot(document.getElementById('root')!).render(<Fixture />);
