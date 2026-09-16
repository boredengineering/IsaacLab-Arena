import { afterEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { Observation } from './observation';
import { workspaceKey, jobKey } from './cache';
import { ApiClient } from './api';
const job = (status = 'running') => ({
  id: 'j1',
  workspace_id: 'default',
  kind: 'diagnostic',
  status,
  stage: status,
  inputs: { steps: 2, delay_seconds: 1 },
});
const snapshot = (cursor: number, status = 'running') => ({
  id: 'default',
  name: 'Arena workspace',
  jobs: [job(status)],
  event_cursor: cursor,
});
class Port {
  onmessage: ((e: MessageEvent) => void) | null = null;
  onmessageerror = null;
  postMessage = vi.fn();
  start() {}
  close() {}
  send(data: unknown) {
    this.onmessage?.(new MessageEvent('message', { data }));
  }
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
afterEach(() => vi.useRealTimers());

it.each(['snapshot', 'error'] as const)('does not share a retired observer pending %s with the replacement owner', async outcome => {
  const oldWire = deferred<unknown>();
  const oldGet = vi.fn(() => oldWire.promise);
  const nextGet = vi.fn().mockResolvedValue(snapshot(2, 'succeeded'));
  const cache = new QueryClient();
  const old = new Observation({ get: oldGet, expire: vi.fn() } as unknown as ApiClient, cache, () => null);
  const next = new Observation({ get: nextGet, expire: vi.fn() } as unknown as ApiClient, cache, () => null);
  try {
    const oldStarting = old.start();
    old.stop();
    const nextStarting = next.start();
    if (outcome === 'snapshot') oldWire.resolve(snapshot(99));
    else oldWire.reject(new Error('retired wire failure'));
    await Promise.all([oldStarting, nextStarting]);
    expect(nextGet).toHaveBeenCalledOnce();
    expect(cache.getQueryData(workspaceKey)).toMatchObject({ event_cursor: 2 });
    expect(cache.getQueryData(jobKey('j1'))).toMatchObject({ status: 'succeeded' });
    expect(next.error).toBe('');
    expect(next.status).toBe('degraded');
  } finally { old.stop(); next.stop(); cache.clear(); }
});

it.each(['snapshot', 'error'] as const)('stopped pending %s cannot notify subscribers or restart fallback polling', async outcome => {
  vi.useFakeTimers();
  const wire = deferred<unknown>();
  const get = vi.fn(() => wire.promise);
  const cache = new QueryClient();
  const observe = new Observation({ get, expire: vi.fn() } as unknown as ApiClient, cache, () => null);
  const listener = vi.fn();
  observe.subscribe(listener);
  try {
    const starting = observe.start();
    observe.stop();
    listener.mockClear();
    if (outcome === 'snapshot') wire.resolve(snapshot(99));
    else wire.reject(new Error('retired failure'));
    await starting;
    expect(listener).not.toHaveBeenCalled();
    expect(cache.getQueryData(workspaceKey)).toBeUndefined();
    await vi.advanceTimersByTimeAsync(600_000);
    expect(get).toHaveBeenCalledOnce();
  } finally { observe.stop(); cache.clear(); }
});

it('starts at most one port while its initial snapshot is pending and never restarts after stop', async () => {
  vi.useFakeTimers();
  const wire = deferred<unknown>();
  const get = vi.fn(() => wire.promise);
  const ports: Port[] = [];
  const cache = new QueryClient();
  const makePort = vi.fn(() => { const port = new Port(); ports.push(port); return port; });
  const observe = new Observation({ get, expire: vi.fn() } as unknown as ApiClient, cache, makePort);
  try {
    const first = observe.start();
    const second = observe.start();
    wire.resolve(snapshot(1, 'succeeded'));
    await Promise.all([first, second]);
    expect(makePort).toHaveBeenCalledOnce();
    observe.stop();
    await observe.start();
    expect(makePort).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(600_000);
    expect(get).toHaveBeenCalledOnce();
  } finally { observe.stop(); cache.clear(); }
});
it('ignores a queued port error after stop and releases port handlers exactly once', async () => {
  vi.useFakeTimers();
  const port = new Port();
  const close = vi.spyOn(port, 'close');
  const get = vi.fn().mockResolvedValue(snapshot(1));
  const cache = new QueryClient();
  const observe = new Observation({ get, expire: vi.fn() } as unknown as ApiClient, cache, () => port);
  const listener = vi.fn();
  observe.subscribe(listener);
  try {
    await observe.start();
    const queuedError = port.onmessageerror as unknown as (event: MessageEvent) => void;
    observe.stop();
    observe.stop();
    listener.mockClear();
    queuedError(new MessageEvent('messageerror'));
    await vi.advanceTimersByTimeAsync(600_000);
    expect(listener).not.toHaveBeenCalled();
    expect(get).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
    expect(port.onmessage).toBeNull();
    expect(port.onmessageerror).toBeNull();
  } finally { observe.stop(); cache.clear(); }
});

it('attaches before the snapshot request and reconciles buffered events into Query, including late terminal updates', async () => {
  let resolve!: (v: unknown) => void;
  const port = new Port();
  const get = vi.fn(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const cache = new QueryClient();
  const api = { get, expire: vi.fn() } as unknown as ApiClient;
  const observe = new Observation(api, cache, () => port);
  const starting = observe.start();
  expect(port.onmessage).toBeTypeOf('function');
  port.send({
    type: 'event',
    event: {
      schema_version: 1,
      id: 11,
      workspace_id: 'default',
      job_id: 'j1',
      kind: 'stage',
      job: job('succeeded'),
    },
  });
  resolve(snapshot(10));
  await starting;
  expect(cache.getQueryData(workspaceKey)).toMatchObject({ event_cursor: 11 });
  expect(cache.getQueryData(jobKey('j1'))).toMatchObject({ status: 'succeeded' });
  expect(port.postMessage).toHaveBeenCalledWith({ type: 'ready', cursor: 11 });
  observe.stop();
});
it('polls every five seconds only in degraded mode, stops for terminal jobs, and never posts jobs', async () => {
  vi.useFakeTimers();
  const get = vi
    .fn()
    .mockResolvedValueOnce(snapshot(1))
    .mockResolvedValueOnce(snapshot(2, 'succeeded'));
  const api = { get, expire: vi.fn() } as unknown as ApiClient;
  const observe = new Observation(api, new QueryClient(), () => null);
  await observe.start();
  expect(observe.status).toBe('degraded');
  await vi.advanceTimersByTimeAsync(4999);
  expect(get).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(get).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(60_000);
  expect(get).toHaveBeenCalledTimes(2);
  observe.stop();
});
it('bounds failed fallback requests and stops immediately on revoked sessions', async () => {
  vi.useFakeTimers();
  const get = vi.fn().mockRejectedValue(new Error('offline'));
  const api = { get, expire: vi.fn() } as unknown as ApiClient;
  const observe = new Observation(api, new QueryClient(), () => null);
  await observe.start();
  await vi.advanceTimersByTimeAsync(600_000);
  expect(get.mock.calls.length).toBeLessThanOrEqual(61);
  expect(observe.status).toBe('disconnected');
  observe.stop();
  const port = new Port();
  get.mockResolvedValue(snapshot(1));
  const second = new Observation(api, new QueryClient(), () => port);
  await second.start();
  port.send({ type: 'status', status: 'expired' });
  expect(api.expire).toHaveBeenCalledOnce();
  const count = get.mock.calls.length;
  await vi.advanceTimersByTimeAsync(60_000);
  expect(get).toHaveBeenCalledTimes(count);
  second.stop();
});
