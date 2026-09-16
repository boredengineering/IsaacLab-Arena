import { expect, it, vi } from 'vitest';
import { createLibraryNotifications, LIBRARY_NOTIFICATION, createNativeLibraryAdapter, LIBRARY_DATABASE, LIBRARY_DATABASE_VERSION, LIBRARY_STORE, LIBRARY_RECORD_KEY } from './library-preferences-native';

it('accepts only a fixed bounded hint and falls back to focus with symmetric cleanup', () => {
  let channel!: {onmessage: ((event: {data: unknown}) => void) | null; postMessage: ReturnType<typeof vi.fn>; close: ReturnType<typeof vi.fn>};
  vi.stubGlobal('BroadcastChannel', class {
    onmessage = null; postMessage = vi.fn(); close = vi.fn();
    constructor() {channel = this;}
  });
  try {
    const notifications = createLibraryNotifications(); const hint = vi.fn(); const stop = notifications.subscribe(hint);
    channel.onmessage!({data: {revision: Number.MAX_SAFE_INTEGER, pins: ['forged']}});
    channel.onmessage!({data: 'x'.repeat(100000)}); expect(hint).not.toHaveBeenCalled();
    channel.onmessage!({data: LIBRARY_NOTIFICATION}); expect(hint).toHaveBeenCalledTimes(1);
    notifications.post(); expect(channel.postMessage).toHaveBeenCalledWith(LIBRARY_NOTIFICATION);
    window.dispatchEvent(new Event('focus')); expect(hint).toHaveBeenCalledTimes(2);
    stop(); notifications.close(); window.dispatchEvent(new Event('focus')); expect(hint).toHaveBeenCalledTimes(2);
    expect(channel.close).toHaveBeenCalledTimes(1);
    vi.stubGlobal('BroadcastChannel', undefined);
    const fallback = createLibraryNotifications(); const fallbackHint = vi.fn(); const stopFallback = fallback.subscribe(fallbackHint);
    window.dispatchEvent(new Event('focus')); expect(fallbackHint).toHaveBeenCalledTimes(1);
    expect(() => fallback.post()).toThrow(); stopFallback(); fallback.close();
  } finally {vi.unstubAllGlobals();}
});
// Scripted IDB event boundary: proves adapter lifecycle wiring, NOT native transactions.
function events() {
  const request = {result: null as unknown, onsuccess: null as null | (() => void), onerror: null as null | (() => void)};
  const countRequest = {result: 0, onsuccess: null as null | (() => void), onerror: null as null | (() => void)};
  const store = {get: vi.fn(() => request), count: vi.fn(() => countRequest), put: vi.fn()};
  const tx = {objectStore: vi.fn(() => store), abort: vi.fn(() => tx.onabort?.()), oncomplete: null as null | (() => void), onabort: null as null | (() => void), onerror: null as null | (() => void)};
  const db = {objectStoreNames: {contains: () => false}, createObjectStore: vi.fn(), transaction: vi.fn(() => tx), close: vi.fn(), onversionchange: null as null | (() => void), onclose: null as null | (() => void)};
  const opening = {result: db, transaction: tx, onblocked: null as null | (() => void), onupgradeneeded: null as null | (() => void), onsuccess: null as null | (() => void), onerror: null as null | (() => void)};
  const factory = {open: vi.fn(() => opening)};
  return {request, countRequest, store, tx, db, opening, factory, adapter: createNativeLibraryAdapter(() => factory as unknown as IDBFactory)};
}
it('opens the fixed schema and resolves writes only on transaction completion', async () => {
  const fake = events(); const lost = vi.fn(); const opened = fake.adapter.open(lost);
  expect(fake.factory.open).toHaveBeenCalledWith(LIBRARY_DATABASE, LIBRARY_DATABASE_VERSION);
  fake.opening.onupgradeneeded!(); expect(fake.db.createObjectStore).toHaveBeenCalledWith(LIBRARY_STORE);
  fake.opening.onsuccess!(); await opened;
  let settled = false;
  const write = fake.adapter.transaction('readwrite', () => ({value: 'checked'})).then(value => {settled = true; return value;});
  expect(fake.store.get).toHaveBeenCalledWith(LIBRARY_RECORD_KEY);
  fake.request.onsuccess!(); await Promise.resolve();
  expect(fake.store.put).toHaveBeenCalledWith({value: 'checked'}, LIBRARY_RECORD_KEY);
  expect(settled).toBe(false);
  fake.tx.oncomplete!(); expect(await write).toEqual({value: 'checked'});
  fake.adapter.close(); expect(fake.db.close).toHaveBeenCalled();
});
it('rejects request success followed by transaction abort', async () => {
  const fake = events(); const opened = fake.adapter.open(vi.fn()); fake.opening.onsuccess!(); await opened;
  const write = fake.adapter.transaction('readwrite', () => ({value: 1}));
  fake.request.onsuccess!(); fake.tx.onabort!();
  await expect(write).rejects.toThrow(); fake.adapter.close();
});
it.each(['onversionchange', 'onclose'] as const)('retires connections on %s and refuses later transactions', async event => {
  const fake = events(); const lost = vi.fn(); const opened = fake.adapter.open(lost); fake.opening.onsuccess!(); await opened;
  fake.db[event]!(); expect(fake.db.close).toHaveBeenCalled(); expect(lost).toHaveBeenCalledTimes(1);
  await expect(fake.adapter.transaction('readwrite', () => ({}))).rejects.toThrow();
  expect(fake.db.transaction).not.toHaveBeenCalled();
});
it('uses readonly transactions for refreshes and never writes an unchanged record', async () => {
  const fake = events(); const opened = fake.adapter.open(vi.fn()); fake.opening.onsuccess!(); await opened;
  fake.request.result = {revision: 1};
  for (const mode of ['readonly', 'readwrite'] as const) {
    const read = fake.adapter.transaction(mode, raw => raw); fake.request.onsuccess!(); fake.tx.oncomplete!();
    expect(await read).toEqual({revision: 1});
    expect(fake.db.transaction).toHaveBeenLastCalledWith(LIBRARY_STORE, mode);
  }
  expect(fake.store.put).not.toHaveBeenCalled(); fake.adapter.close();
});
it('aborts synchronous quota or admission errors and preserves the original failure for the controller', async () => {
  const fake = events(); const opened = fake.adapter.open(vi.fn()); fake.opening.onsuccess!(); await opened;
  const error = new Error('retired');
  const retired = fake.adapter.transaction('readwrite', () => {throw error;}); fake.request.onsuccess!();
  await expect(retired).rejects.toBe(error);
  fake.store.put.mockImplementation(() => {throw new DOMException('quota', 'QuotaExceededError');});
  const quota = fake.adapter.transaction('readwrite', () => ({revision: 1})); fake.request.onsuccess!();
  await expect(quota).rejects.toMatchObject({name: 'QuotaExceededError'});
  expect(fake.tx.abort).toHaveBeenCalledTimes(2); fake.adapter.close();
});
it('closing a pending open rejects it and suppresses late upgrade and success', async () => {
  const fake = events(); const opened = fake.adapter.open(vi.fn()); fake.adapter.close(); await expect(opened).rejects.toThrow();
  fake.opening.onupgradeneeded!(); fake.opening.onsuccess!();
  expect(fake.db.createObjectStore).not.toHaveBeenCalled(); expect(fake.db.close).toHaveBeenCalled();
});
it('distinguishes genuinely absent keys from corrupt stored undefined before initialization', async () => {
  const fake = events(); const opened = fake.adapter.open(vi.fn()); fake.opening.onsuccess!(); await opened;
  fake.request.result = undefined;
  const mutate = vi.fn(() => ({revision: 0}));
  const corrupt = fake.adapter.transaction('readwrite', mutate); fake.request.onsuccess!();
  expect(fake.store.count).toHaveBeenCalledWith(LIBRARY_RECORD_KEY);
  fake.countRequest.result = 1; fake.countRequest.onsuccess!();
  await expect(corrupt).rejects.toThrow(); expect(mutate).not.toHaveBeenCalled(); expect(fake.store.put).not.toHaveBeenCalled();
  const absent = fake.adapter.transaction('readwrite', mutate); fake.request.onsuccess!();
  fake.countRequest.result = 0; fake.countRequest.onsuccess!(); fake.tx.oncomplete!();
  expect(await absent).toEqual({revision: 0}); expect(mutate).toHaveBeenCalledExactlyOnceWith(undefined); fake.adapter.close();
});
it('blocked open is terminal and closes a late success without upgrading', async () => {
  const fake = events(); const lost = vi.fn(); const opened = fake.adapter.open(lost);
  fake.opening.onblocked!(); await expect(opened).rejects.toThrow();
  fake.opening.onupgradeneeded!(); fake.opening.onsuccess!();
  expect(fake.db.createObjectStore).not.toHaveBeenCalled(); expect(fake.tx.abort).toHaveBeenCalled();
  expect(fake.db.close).toHaveBeenCalled(); expect(lost).toHaveBeenCalledTimes(1);
});
