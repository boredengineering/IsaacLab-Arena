import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useLayoutEffect, type ReactNode } from 'react';
import { flushSync } from 'react-dom';
import { ApiClient } from './api';
import type { Job } from './contracts';
import { useJobCancellation } from './job-cancellation';

const mocks = vi.hoisted(() => ({ runtime: {} as any }));
vi.mock('./runtime', () => ({ useRuntime: () => mocks.runtime }));
const session = { session_id: 's1', csrf_token: 'csrf-fixture', expires_at: 9999999999 };
const job: Job = {
  id: 'exact-job', workspace_id: 'default', kind: 'generate', status: 'cancel_requested',
  stage: 'cleanup_requested', inputs: {}, created_at: 0, updated_at: 0,
  result: null, error: null, created_by_session_id: 's1',
};
let cache: QueryClient;
let transport: ReturnType<typeof vi.fn<typeof fetch>>;
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function mount(jobId: string | undefined = job.id) {
  return renderHook(({ id }: { id: string | undefined }) => useJobCancellation(id), {
    initialProps: { id: jobId } as { id: string | undefined },
    wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={cache}>{children}</QueryClientProvider>,
  });
}
beforeEach(() => {
  cache = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  transport = vi.fn<typeof fetch>(async path => {
    if (path === '/api/session/activity') return response(session);
    if (path === '/api/jobs/exact-job/cancel') return response(job);
    throw new Error(`Unexpected transport: ${path}`);
  });
  const api = new ApiClient(transport);
  api.session = { ...session };
  mocks.runtime = { api, session: api.session, refresh: vi.fn(async () => {}) };
});
afterEach(() => { cache.clear(); });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
type Retirement = 'job' | 'roundtrip' | 'unmount' | 'client' | 'session' | 'same-session-id';
function retire(view: ReturnType<typeof mount>, mode: Retirement) {
  if (mode === 'unmount') view.unmount();
  else if (mode === 'job' || mode === 'roundtrip') {
    // Commit the away scope even inside a batched click act.
    flushSync(() => view.rerender({ id: 'replacement-job' }));
    if (mode === 'roundtrip') view.rerender({ id: job.id });
  } else if (mode === 'client') {
    const api = new ApiClient(transport);
    api.session = { ...session };
    mocks.runtime = { ...mocks.runtime, api, session: api.session, refresh: vi.fn(async () => {}) };
    view.rerender({ id: job.id });
  } else {
    mocks.runtime.api.session = { ...session, session_id: mode === 'session' ? 's2' : session.session_id };
    // Deliberately no React update: actual ApiClient ownership must be checked.
  }
}

it.each<Retirement>(['job', 'roundtrip', 'unmount', 'client', 'session', 'same-session-id'])('retires activity preflight after %s', async mode => {
  const activity = deferred<Response>();
  transport.mockImplementation(async path => path === '/api/session/activity' ? activity.promise : response(job));
  const view = mount();
  const refresh = mocks.runtime.refresh;
  act(() => view.result.current.cancel.mutate());
  await waitFor(() => expect(transport).toHaveBeenCalledOnce());
  retire(view, mode);
  await act(async () => { activity.resolve(response(session)); });
  expect(transport).toHaveBeenCalledOnce();
  expect(refresh).not.toHaveBeenCalled();
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
  if (mode !== 'unmount') {
    await waitFor(() => expect(view.result.current.cancel.isPending).toBe(false));
    expect(view.result.current.cancel.error).toBeNull();
  }
});

it.each<Retirement>(['job', 'roundtrip', 'unmount', 'client', 'session', 'same-session-id'])('drops late cancellation acceptance after %s', async mode => {
  const cancel = deferred<Response>();
  transport.mockImplementation(async path => path === '/api/session/activity' ? response(session) : cancel.promise);
  const view = mount();
  const refresh = mocks.runtime.refresh;
  act(() => view.result.current.cancel.mutate());
  await waitFor(() => expect(transport).toHaveBeenCalledTimes(2));
  retire(view, mode);
  await act(async () => { cancel.resolve(response(job)); });
  expect(refresh).not.toHaveBeenCalled();
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
  if (mode !== 'unmount') {
    await waitFor(() => expect(view.result.current.cancel.isPending).toBe(false));
    expect(view.result.current.cancel.error).toBeNull();
  }
});

it('does not attribute old pending cancellation to a replacement job', async () => {
  const activity = deferred<Response>();
  transport.mockImplementation(() => activity.promise);
  const view = mount();
  act(() => view.result.current.cancel.mutate());
  await waitFor(() => expect(view.result.current.cancel.isPending).toBe(true));
  view.rerender({ id: 'replacement-job' });
  expect(view.result.current.cancel.isPending).toBe(false);
  await act(async () => { activity.resolve(response(session)); });
});

it('does not attribute settled cancellation errors to a replacement job', async () => {
  transport.mockImplementation(async () => response({ detail: 'activity unavailable' }, 503));
  const view = mount();
  act(() => view.result.current.cancel.mutate());
  await waitFor(() => expect(view.result.current.cancel.error?.message).toBe('activity unavailable'));
  view.rerender({ id: 'replacement-job' });
  expect(view.result.current.cancel.error).toBeNull();
  view.rerender({ id: job.id });
  expect(view.result.current.cancel.error).toBeNull();
});

it.each(['activity', 'cancel', 'refresh'] as const)('suppresses a retired %s error without affecting replacement work', async phase => {
  const delayed = deferred<Response>();
  const oldRefresh = mocks.runtime.refresh;
  transport.mockImplementation(async path => {
    if (phase === 'activity' && path === '/api/session/activity') return delayed.promise;
    if (phase === 'cancel' && path !== '/api/session/activity') return delayed.promise;
    return response(path === '/api/session/activity' ? session : job);
  });
  if (phase === 'refresh') oldRefresh.mockImplementation(async () => {
    await delayed.promise;
    throw new Error('retired refresh');
  });
  const view = mount();
  act(() => view.result.current.cancel.mutate());
  await waitFor(() => expect(phase === 'refresh' ? oldRefresh : transport).toHaveBeenCalledTimes(phase === 'cancel' ? 2 : 1));
  retire(view, 'client');
  await act(async () => { delayed.resolve(response({ detail: 'retired failure' }, 503)); });
  await waitFor(() => expect(view.result.current.cancel.isPending).toBe(false));
  expect(view.result.current.cancel.error).toBeNull();
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
});

it.each<Retirement>(['job', 'roundtrip', 'unmount', 'client'])('retires the frozen click before mutationFn starts after %s', async mode => {
  const view = mount();
  act(() => {
    view.result.current.cancel.mutate();
    retire(view, mode);
  });
  await act(async () => {});
  expect(transport).not.toHaveBeenCalled();
});

it('does not let a retained callback target an old job after replacement', async () => {
  const view = mount();
  const oldCancel = view.result.current.cancel.mutate;
  retire(view, 'roundtrip');
  act(() => oldCancel());
  await act(async () => {});
  expect(transport).not.toHaveBeenCalled();
});

it('fences StrictMode lifecycle replay without disabling the current mount', async () => {
  const { result } = renderHook(() => {
    const cancellation = useJobCancellation(job.id);
    useLayoutEffect(() => { cancellation.cancel.mutate(); }, []);
    return cancellation;
  }, {
    reactStrictMode: true,
    wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={cache}>{children}</QueryClientProvider>,
  });
  await waitFor(() => expect(mocks.runtime.refresh).toHaveBeenCalledOnce());
  expect(transport).toHaveBeenCalledTimes(2);
  await waitFor(() => expect(result.current.cancel.isPending).toBe(false));
  expect(result.current.cancel.error).toBeNull();
});

it('preserves the exact encoded target and ignores runtime metadata-only rerenders', async () => {
  const exact = 'job/with ?special%chars';
  const activity = deferred<Response>();
  transport.mockImplementation(async path => path === '/api/session/activity' ? activity.promise : response({ ...job, id: exact }));
  const view = mount(exact);
  const refresh = mocks.runtime.refresh;
  act(() => view.result.current.cancel.mutate());
  await waitFor(() => expect(transport).toHaveBeenCalledOnce());
  mocks.runtime = { ...mocks.runtime, session: { ...session }, refresh: vi.fn(async () => {}) };
  view.rerender({ id: exact });
  await act(async () => { activity.resolve(response({ ...session, expires_at: session.expires_at + 1 })); });
  await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
  expect(transport.mock.calls[1][0]).toBe('/api/jobs/job%2Fwith%20%3Fspecial%25chars/cancel');
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
  expect(view.result.current.cancel.error).toBeNull();
});

it('freezes session generation before React Query starts the mutation', async () => {
  const { result } = mount();
  act(() => {
    result.current.cancel.mutate();
    // Same public session ID still represents a replacement session.
    mocks.runtime.api.session = { ...session };
  });
  await act(async () => {});
  expect(transport).not.toHaveBeenCalled();
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
  expect(result.current.cancel.error).toBeNull();
});

it.each([undefined, ''])('does not dispatch without an exact job ID: %s', async id => {
  const { result, rerender } = mount();
  // Explicit rerender distinguishes undefined from mount's default fixture ID.
  rerender({ id });
  act(() => result.current.cancel.mutate());
  await act(async () => {});
  expect(transport).not.toHaveBeenCalled();
  expect(result.current.cancel.isPending).toBe(false);
});

it.each([{}, { ...job, id: 'different-job' }, { ...job, status: 'invented' }])('rejects invalid or wrong-job cancellation acknowledgements: %j', async value => {
  transport.mockImplementation(async path => response(path === '/api/session/activity' ? session : value));
  const { result } = mount();
  act(() => result.current.cancel.mutate());
  await waitFor(() => expect(result.current.cancel.error?.message).toBe('Invalid cancellation status response'));
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
});

it('only requests exact-job cancellation, leaving terminal status to runtime observation', async () => {
  const { result } = mount();
  expect(transport).not.toHaveBeenCalled();
  act(() => result.current.cancel.mutate());
  await waitFor(() => expect(mocks.runtime.refresh).toHaveBeenCalledOnce());
  await waitFor(() => expect(result.current.cancel.isPending).toBe(false));
  expect(result.current.cancel.error).toBeNull();
  expect(transport.mock.calls.map(([path]) => path)).toEqual([
    '/api/session/activity', '/api/jobs/exact-job/cancel',
  ]);
  expect(transport.mock.calls[1][1]).toMatchObject({
    method: 'POST', credentials: 'same-origin', body: '{}',
    headers: { 'X-CSRF-Token': session.csrf_token },
  });
  expect(Object.keys(result.current)).toEqual(['cancel']);
  expect(Object.keys(result.current.cancel).sort()).toEqual(['error', 'isPending', 'mutate']);
  expect(cache.getQueryCache().getAll()).toHaveLength(0);
});
