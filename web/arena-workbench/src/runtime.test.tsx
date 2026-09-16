import { StrictMode } from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { jobKey, workspaceKey } from './cache';
import { RuntimeProvider, useRuntime } from './runtime';
import type { ObservationPort } from './observation';

const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const session = (id: string) => ({ session_id: id, csrf_token: `csrf-${id}`, expires_at: 9999999999 });
const snapshot = (name: string, cursor = 1) => ({
  id: 'default', name, event_cursor: cursor,
  jobs: [{ id: 'accepted', workspace_id: 'default', kind: 'diagnostic', status: 'running',
    stage: 'running', inputs: { steps: 2, delay_seconds: 1 } }],
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
class Port implements ObservationPort {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onmessageerror: ((event: MessageEvent) => void) | null = null;
  postMessage = vi.fn();
  start = vi.fn();
  close = vi.fn();
  send(data: unknown) { this.onmessage?.(new MessageEvent('message', { data })); }
}
const health = (owner: string, diagnostic: boolean) => ({
  status: owner, capabilities: { diagnostic, generation: false, preview: false },
});
function server(id: string, connect?: Promise<Response>, workspace?: Promise<Response>, metadata?: Promise<Response>) {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/health') return metadata ? (await metadata).clone() : response(health(id, false));
    // Each HTTP call receives a fresh body, including explicit reconnects.
    if (url === '/api/sessions') return connect ? (await connect).clone() : response(session(id));
    if (url === '/api/workspaces/default') return workspace ? (await workspace).clone() : response(snapshot(id));
    if (url === '/api/session/activity') return response({ ...session(id), expires_at: 9999999998 });
    throw new Error(`Unexpected request: ${init?.method} ${url}`);
  });
  return { api: new ApiClient(fetcher as typeof fetch), fetcher };
}
function mount(api: ApiClient, strict = false, fallback = false) {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const ports: Port[] = [];
  const makePort = () => {
    if (fallback) return null;
    const port = new Port();
    ports.push(port);
    return port;
  };
  let runtime!: ReturnType<typeof useRuntime>;
  function Probe() { runtime = useRuntime(); return null; }
  const tree = (client: ApiClient) => {
    const provider = <QueryClientProvider client={cache}>
      <RuntimeProvider api={client} makePort={makePort}><Probe /></RuntimeProvider>
    </QueryClientProvider>;
    return strict ? <StrictMode>{provider}</StrictMode> : provider;
  };
  const view = render(tree(api));
  return { cache, ports, get runtime() { return runtime; },
    replace: (client: ApiClient) => view.rerender(tree(client)),
    unmount: () => { view.unmount(); cache.clear(); } };
}
beforeEach(() => { sessionStorage.clear(); vi.useFakeTimers(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

it.each(['capability', 'error'] as const)('withholds client A cached health %s while same-session client B health is pending', async outcome => {
  const pending = deferred<Response>();
  const a = server('same', undefined, undefined, Promise.resolve(outcome === 'capability'
    ? response(health('A', true)) : response({ detail: 'A health unavailable' }, 503)));
  const b = server('same', undefined, undefined, pending.promise);
  const view = mount(a.api);
  try {
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(view.runtime.health).toEqual(outcome === 'capability' ? health('A', true) : undefined);
    expect(view.runtime.error).toBe(outcome === 'error' ? 'A health unavailable' : '');
    view.replace(b.api);
    // The replacement render itself must not expose the old capability.
    expect(view.runtime.health).toBeUndefined();
    expect(view.runtime.error).toBe('');
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(view.runtime.session?.session_id).toBe('same');
    expect(b.api.sessionGeneration).toBe(a.api.sessionGeneration);
    expect(b.fetcher.mock.calls.filter(([url]) => url === '/api/health')).toHaveLength(1);
    expect(view.runtime.health).toBeUndefined();
    await act(async () => {
      pending.resolve(response(health('B', false)));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(view.runtime.health).toEqual(health('B', false));
    expect(view.runtime.error).toBe('');
    expect(view.ports[0].close).toHaveBeenCalledOnce();
    expect(view.ports).toHaveLength(2);
  } finally { view.unmount(); }
});

it.each([
  ['success', 'before'], ['error', 'before'], ['success', 'after'], ['error', 'after'],
] as const)('discards retired health %s settling %s replacement health', async (outcome, order) => {
  const oldHealth = deferred<Response>();
  const newHealth = deferred<Response>();
  const a = server('same', undefined, undefined, oldHealth.promise);
  const b = server('same', undefined, undefined, newHealth.promise);
  const view = mount(a.api);
  try {
    await act(async () => {});
    const oldQuery = view.cache.getQueryCache().find({ queryKey: ['health'], exact: false })!;
    expect(oldQuery).toBeDefined();
    view.replace(b.api);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(view.runtime.health).toBeUndefined();
    expect(view.runtime.error).toBe('');
    expect(b.fetcher.mock.calls.filter(([url]) => url === '/api/health')).toHaveLength(1);
    const retiredSettlement = vi.fn();
    const unsubscribe = view.cache.getQueryCache().subscribe(event => {
      if (event.query === oldQuery && event.type === 'updated'
        && (event.action.type === 'success' || event.action.type === 'error')) retiredSettlement();
    });
    try {
      if (order === 'after') {
        await act(async () => {
          newHealth.resolve(response(health('B', false)));
          await vi.advanceTimersByTimeAsync(0);
        });
      }
      await act(async () => {
        oldHealth.resolve(outcome === 'success'
          ? response(health('A', true)) : response({ detail: 'retired A health error' }, 503));
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(view.runtime.health).toEqual(order === 'after' ? health('B', false) : undefined);
      expect(view.runtime.error).toBe('');
      expect(view.runtime.api).toBe(b.api);
      expect(view.runtime.session?.session_id).toBe('same');
      expect(view.runtime.status).not.toBe('disconnected');
      expect(retiredSettlement).not.toHaveBeenCalled();
      if (order === 'before') {
        await act(async () => {
          newHealth.resolve(response(health('B', false)));
          await vi.advanceTimersByTimeAsync(0);
        });
      }
      expect(view.runtime.health).toEqual(health('B', false));
      expect(view.ports).toHaveLength(2);
      expect(view.ports[0].close).toHaveBeenCalledOnce();
    } finally { unsubscribe(); }
  } finally { view.unmount(); }
});

it.each(['success', 'error'] as const)('ignores client A pending connect %s after client B commits', async outcome => {
  const pending = deferred<Response>();
  const a = server('A', pending.promise);
  const b = server('B');
  const view = mount(a.api);
  try {
    view.replace(b.api);
    await act(async () => {});
    expect(view.runtime.session?.session_id).toBe('B');
    await act(async () => { pending.resolve(outcome === 'success'
      ? response(session('A')) : response({ detail: 'retired A error' }, 503)); });
    expect(view.runtime.api).toBe(b.api);
    expect(view.runtime.session?.session_id).toBe('B');
    expect(view.runtime.error).toBe('');
    expect(view.runtime.status).not.toBe('disconnected');
    expect(view.cache.getQueryData(workspaceKey)).toMatchObject({ name: 'B' });
    expect(a.fetcher.mock.calls.filter(([url]) => url === '/api/workspaces/default')).toHaveLength(0);
    expect(view.ports).toHaveLength(1);
  } finally { view.unmount(); }
});

it('overlapped explicit reconnects create only one current observer for the coalesced session', async () => {
  const pending = deferred<Response>();
  const a = server('A', pending.promise);
  const view = mount(a.api);
  let reconnect!: Promise<void>;
  try {
    act(() => { reconnect = view.runtime.connect(); });
    await act(async () => { pending.resolve(response(session('A'))); await reconnect; });
    expect(a.fetcher.mock.calls.filter(([url]) => url === '/api/sessions')).toHaveLength(1);
    expect(view.ports).toHaveLength(1);
    expect(view.runtime.connecting).toBe(false);
    view.unmount();
    expect(view.ports.every(port => port.close.mock.calls.length === 1)).toBe(true);
  } finally { view.unmount(); }
});

it('StrictMode effect replay does not resurrect the pending first connection observer', async () => {
  const pending = deferred<Response>();
  const a = server('A', pending.promise);
  const view = mount(a.api, true);
  try {
    await act(async () => { pending.resolve(response(session('A'))); });
    expect(view.runtime.session?.session_id).toBe('A');
    expect(view.ports).toHaveLength(1);
    view.unmount();
    expect(view.ports.every(port => port.close.mock.calls.length === 1)).toBe(true);
  } finally { view.unmount(); }
});

it.each(['success', 'error'] as const)('retired observer start %s cannot complete the newer pending reconnect', async outcome => {
  const oldSnapshot = deferred<Response>();
  const nextSession = deferred<Response>();
  const a = server('A', undefined, oldSnapshot.promise);
  const view = mount(a.api);
  let reconnect!: Promise<void>;
  try {
    await act(async () => {});
    expect(view.ports).toHaveLength(1);
    a.fetcher.mockImplementation(async (url: string) => {
      if (url === '/api/sessions') return nextSession.promise;
      if (url === '/api/workspaces/default') return response(snapshot('new'));
      if (url === '/api/health') return response({ status: 'ok' });
      throw new Error(`Unexpected request: ${url}`);
    });
    act(() => { reconnect = view.runtime.connect(); });
    expect(view.ports[0].close).toHaveBeenCalledOnce();
    await act(async () => { oldSnapshot.resolve(outcome === 'success'
      ? response(snapshot('retired')) : response({ detail: 'retired snapshot error' }, 503)); });
    expect(view.runtime.connecting).toBe(true);
    expect(view.runtime.status).toBe('connecting');
    expect(view.runtime.error).toBe('');
    expect(view.cache.getQueryData(workspaceKey)).toBeUndefined();
    await act(async () => { nextSession.resolve(response(session('new'))); await reconnect; });
    expect(view.runtime.session?.session_id).toBe('new');
    expect(view.cache.getQueryData(workspaceKey)).toMatchObject({ name: 'new' });
  } finally { view.unmount(); }
});

it('replacement observer reads its own snapshot instead of adopting the retired in-flight wire request', async () => {
  const oldSnapshot = deferred<Response>();
  const a = server('A', undefined, oldSnapshot.promise);
  const b = server('B');
  const view = mount(a.api);
  try {
    await act(async () => {});
    view.replace(b.api);
    await act(async () => {});
    await act(async () => { oldSnapshot.resolve(response(snapshot('retired', 99))); });
    expect(b.fetcher.mock.calls.filter(([url]) => url === '/api/workspaces/default')).toHaveLength(1);
    expect(view.cache.getQueryData(workspaceKey)).toMatchObject({ name: 'B', event_cursor: 1 });
    expect(view.runtime.session?.session_id).toBe('B');
    expect(view.ports[0].close).toHaveBeenCalledOnce();
    act(() => { view.ports[0].send({ type: 'status', status: 'expired' }); });
    expect(view.runtime.session?.session_id).toBe('B');
    expect(b.api.session?.session_id).toBe('B');
  } finally { view.unmount(); }
});

it('retained commands cannot dispatch through a replaced or unmounted provider lifetime', async () => {
  const a = server('A');
  const b = server('B');
  const view = mount(a.api);
  try {
    await act(async () => {});
    const retired = view.runtime;
    view.replace(b.api);
    await act(async () => {});
    const aCalls = a.fetcher.mock.calls.length;
    const bCalls = b.fetcher.mock.calls.length;
    await act(async () => {
      await retired.connect();
      await retired.refresh();
      await retired.revoke();
    });
    expect(a.fetcher).toHaveBeenCalledTimes(aCalls);
    expect(b.fetcher).toHaveBeenCalledTimes(bCalls);
    const current = view.runtime;
    view.unmount();
    await current.connect();
    await current.refresh();
    await current.revoke();
    expect(b.fetcher).toHaveBeenCalledTimes(bCalls);
  } finally { view.unmount(); }
});

it('pagehide retires a pending connection before a restored page can receive its observer', async () => {
  const pending = deferred<Response>();
  const a = server('A', pending.promise);
  const view = mount(a.api);
  try {
    act(() => {
      window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }));
      window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
    });
    await act(async () => { pending.resolve(response(session('A'))); });
    expect(view.runtime.status).toBe('disconnected');
    expect(view.runtime.connecting).toBe(false);
    expect(view.runtime.session).toBeNull();
    expect(view.ports).toHaveLength(0);
    expect(a.fetcher.mock.calls.some(([url]) => url === '/api/workspaces/default')).toBe(false);
  } finally { view.unmount(); }
});

it('keeps accepted jobs observable across real activity without reconnecting or dispatching work', async () => {
  const a = server('A');
  const view = mount(a.api);
  try {
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const generation = a.api.sessionGeneration;
    const metadata = view.runtime.health;
    const healthCalls = a.fetcher.mock.calls.filter(([url]) => url === '/api/health').length;
    expect(metadata).toEqual(health('A', false));
    expect(healthCalls).toBeGreaterThan(0);
    await act(async () => { await a.api.activity(); });
    view.replace(a.api);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(view.runtime.health).toBe(metadata);
    expect(a.fetcher.mock.calls.filter(([url]) => url === '/api/health')).toHaveLength(healthCalls);
    expect(a.api.sessionGeneration).toBe(generation);
    act(() => { view.ports[0].send({ type: 'event', event: {
      schema_version: 1, id: 2, workspace_id: 'default', job_id: 'accepted', kind: 'stage',
      job: { ...snapshot('A').jobs[0], status: 'succeeded', stage: 'succeeded' },
    } }); });
    expect(view.cache.getQueryData(jobKey('accepted'))).toMatchObject({ status: 'succeeded' });
    expect(view.ports).toHaveLength(1);
    expect(a.fetcher.mock.calls.filter(([url]) => url === '/api/sessions')).toHaveLength(1);
    expect(a.fetcher.mock.calls.some(([url]) => url === '/api/jobs')).toBe(false);
  } finally { view.unmount(); }
});

it('retires all superseded fallback pollers and bounds the surviving owner', async () => {
  vi.useFakeTimers();
  const pending = deferred<Response>();
  const a = server('A', pending.promise);
  const view = mount(a.api, true, true);
  try {
    await act(async () => { pending.resolve(response(session('A'))); });
    await act(async () => { await vi.advanceTimersByTimeAsync(600_000); });
    expect(a.fetcher.mock.calls.filter(([url]) => url === '/api/workspaces/default').length).toBeLessThanOrEqual(61);
    expect(view.runtime.status).toBe('disconnected');
    await act(async () => { await view.runtime.connect(); });
    expect(view.runtime.status).toBe('degraded');
    view.unmount();
    const calls = a.fetcher.mock.calls.length;
    await vi.advanceTimersByTimeAsync(600_000);
    expect(a.fetcher).toHaveBeenCalledTimes(calls);
  } finally { view.unmount(); }
});
