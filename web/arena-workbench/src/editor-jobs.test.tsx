import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { App } from './app';
import type { Job } from './contracts';

const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const noPort = () => null;
beforeEach(() => sessionStorage.clear());

it.each(['accepted', 'blocker'] as const)('preserves validated router search through the %s EditorJobProgress link', async mode => {
  const job: Job = {
    id: mode === 'accepted' ? 'accepted-generation' : 'blocked-generation', workspace_id: 'default', kind: 'generate',
    status: mode === 'accepted' ? 'succeeded' : 'blocked_authorization', stage: 'Review this generation',
    inputs: { operation: 'new' }, result: null, error: null, created_at: 0, updated_at: 0, created_by_session_id: 's',
  };
  if (mode === 'accepted') sessionStorage.setItem('arena:editor:generate:v1', JSON.stringify({
    payload: { idempotency_key: 'accepted-request', operation: 'new' }, job,
  }));
  const fetcher = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url.endsWith('/health')) return response({ capabilities: { diagnostic: false } });
    if (url.endsWith('/sessions') || url.endsWith('/session/activity'))
      return response({ session_id: 's', csrf_token: 'csrf', expires_at: 9999999999 });
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', jobs: [job], event_cursor: 0 });
    if (url.endsWith(`/jobs/${job.id}`)) return response(job);
    if (url === '/api/editor') return response({ default_document_id: '', documents: [], capabilities: {}, limitations: [] });
    return response({ detail: 'not installed in fixture' }, 404);
  });
  const history = createMemoryHistory({ initialEntries: ['/?filter=terminal&graphRenderer=explorer&layout=v7&unvalidated=discard'] });
  render(<App api={new ApiClient(fetcher as typeof fetch)} history={history} makePort={noPort}
    cache={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })} />);
  if (mode === 'blocker') fireEvent.click(await screen.findByRole('button', { name: `Review blocked generation ${job.id}` }));
  const link = await screen.findByRole('link', { name: 'Job details' });
  const target = new URL(link.getAttribute('href')!, 'http://localhost');
  expect(target.pathname).toBe(`/jobs/${job.id}`);
  expect(Object.fromEntries(target.searchParams)).toEqual({ filter: 'terminal', graphRenderer: 'explorer', layout: 'v7' });
  fireEvent.click(link);
  await waitFor(() => expect(history.location.pathname).toBe(`/jobs/${job.id}`));
  expect(Object.fromEntries(new URLSearchParams(history.location.search))).toEqual({ filter: 'terminal', graphRenderer: 'explorer', layout: 'v7' });
  expect(fetcher.mock.calls.filter(([url, init]) => init?.method === 'POST' && /\/editor\/|\/cancel$/.test(url))).toHaveLength(0);
});
