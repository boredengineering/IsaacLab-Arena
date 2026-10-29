import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { RuntimeProvider } from './runtime';
import { QueueResume } from './queue-resume';
import { workspaceKey } from './cache';

const session = { session_id: 'queue-session', csrf_token: 'csrf', expires_at: 9999999999 };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const queued = { id: 'queued-build', workspace_id: 'default', kind: 'build', status: 'queued', stage: 'queued', inputs: {}, created_at: 0, updated_at: 0, result: null, error: null, created_by_session_id: session.session_id };
const noPort = () => null;
function setup(resumeResponse = async () => response({ resumed: true }), activityResponse = async () => response(session)) {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/health')) return response({ status: 'ok', capabilities: { diagnostic: false, generation: false, preview: false } });
    if (url.endsWith('/sessions')) return response(session);
    if (url.endsWith('/session/activity')) return activityResponse();
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', jobs: [queued], event_cursor: 1 });
    if (url.endsWith('/jobs/queued-build')) return response(queued);
    if (url.endsWith('/jobs/resume-queue') && init?.method === 'POST') return resumeResponse();
    return response({ detail: 'not found' }, 404);
  });
  const api = new ApiClient(fetcher as typeof fetch);
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: 3 } } });
  const view = render(<QueryClientProvider client={cache}><RuntimeProvider api={api} makePort={noPort}><QueueResume /></RuntimeProvider></QueryClientProvider>);
  return { api, cache, fetcher, view };
}
function retainedClick(button: HTMLElement): () => void {
  const key = Object.keys(button).find(name => name.startsWith('__reactProps$'))!;
  return (button as unknown as Record<string, { onClick(): void }>)[key].onClick;
}
beforeEach(() => { sessionStorage.clear(); });
it.each(['same turn', 'inside confirmation'])('locks synchronous duplicate clicks %s', async boundary => {
  let release!: (value: Response) => void;
  const pending = new Promise<Response>(resolve => { release = resolve; });
  const { fetcher } = setup(() => pending);
  const click = retainedClick(await screen.findByRole('button', { name: 'Resume queue' }));
  let reentered = false;
  const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => {
    if (boundary === 'inside confirmation' && !reentered) { reentered = true; click(); }
    return true;
  });
  act(() => { click(); if (boundary === 'same turn') click(); });
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/jobs/resume-queue'))).toBe(true));
  await act(async () => { release(response({ resumed: true })); });
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/session/activity'))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/resume-queue'))).toHaveLength(1);
});
it.each(['http error', 'lost response', 'false ACK', 'nonboolean ACK', 'missing ACK', 'invalid JSON'] as const)('keeps %s static and manual-only, even with cache retries enabled', async failure => {
  const marker = 'synthetic-sensitive-response';
  const { fetcher, cache, view } = setup(async () => {
    if (failure === 'http error') return response({ detail: marker }, 500);
    if (failure === 'lost response') throw new Error(marker);
    if (failure === 'false ACK') return response({ resumed: false });
    if (failure === 'nonboolean ACK') return response({ resumed: 'true' });
    if (failure === 'invalid JSON') return new Response('not JSON');
    return response({ message: marker });
  });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
  fireEvent.click(await screen.findByRole('button', { name: 'Resume queue' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Queue resume acknowledgement unavailable. Inspect jobs before a manual retry; the shared queue may already be running. No automatic retry was sent.');
  expect(screen.queryByText(/Queue resume acknowledged/)).not.toBeInTheDocument();
  expect(document.body.textContent).not.toContain(marker);
  const mutations = cache.getMutationCache().getAll();
  expect(mutations).toHaveLength(1);
  expect(mutations[0].options.retry).toBe(false);
  expect(mutations[0].state.error?.message).not.toContain(marker);
  fireEvent(document, new Event('visibilitychange'));
  await act(async () => {});
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/resume-queue'))).toHaveLength(1);
  confirm.mockReturnValue(false);
  fireEvent.click(screen.getByRole('button', { name: 'Resume queue' }));
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/resume-queue'))).toHaveLength(1);
  view.unmount();
});
it('requires an authenticated session even for a retained enabled handler', async () => {
  const { api, fetcher } = setup();
  const click = retainedClick(await screen.findByRole('button', { name: 'Resume queue' }));
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
  act(() => { api.expire(); click(); });
  expect(screen.getByRole('button', { name: 'Resume queue' })).toBeDisabled();
  expect(confirm).not.toHaveBeenCalled();
  expect(fetcher.mock.calls.filter(([url]) => /session\/activity|jobs\/resume-queue/.test(url))).toHaveLength(0);
});
it('withholds queue admission without observed queued jobs', async () => {
  const { cache, fetcher } = setup();
  await screen.findByRole('button', { name: 'Resume queue' });
  act(() => { cache.setQueryData(workspaceKey, { id: 'default', name: 'Arena', jobs: [], event_cursor: 2 }); });
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Resume queue' })).not.toBeInTheDocument());
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/resume-queue'))).toHaveLength(0);
});
it('sanitizes failed activity preflight without sending a queue POST', async () => {
  const { fetcher, cache } = setup(undefined, async () => response({ detail: 'synthetic-sensitive-response' }, 500));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  fireEvent.click(await screen.findByRole('button', { name: 'Resume queue' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Session activity could not be verified. Queue resume was not sent.');
  expect(document.body.textContent).not.toContain('synthetic-sensitive-response');
  expect(cache.getMutationCache().getAll()[0].state.error?.message).not.toContain('synthetic-sensitive-response');
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/session/activity'))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/resume-queue'))).toHaveLength(0);
});
