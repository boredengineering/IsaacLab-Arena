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
afterEach(() => vi.useRealTimers());
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
