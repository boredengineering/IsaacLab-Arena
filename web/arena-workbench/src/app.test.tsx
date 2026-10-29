import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { App } from './app';
import { ApiClient } from './api';
import { PROVIDERS } from './model-settings-contracts';
import { workspaceKey } from './cache';
import type { Workspace } from './contracts';
const session = { session_id: 'session1', csrf_token: 'csrf', expires_at: 9999999999 };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function server(diagnostic = false) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/health'))
      return response({
        status: 'ok',
        capabilities: { diagnostic, generation: false, preview: false },
      });
    if (url.endsWith('/sessions')) return response(session);
    if (url.endsWith('/workspaces/default'))
      return response({ id: 'default', name: 'Arena workspace', jobs: [], event_cursor: 0 });
    if (url.endsWith('/session/activity')) return response(session);
    if (url.endsWith('/jobs') && init?.method === 'POST') throw new TypeError('connection lost');
    return response({ detail: 'not found' }, 404);
  });
}
function mount(fetcher: ReturnType<typeof server>, path = '/developer/diagnostics') {
  return render(
    <App
      api={new ApiClient(fetcher as typeof fetch)}
      cache={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
      history={createMemoryHistory({ initialEntries: [path] })}
      makePort={() => null}
    />,
  );
}
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});
it('offers blocked-job renewal and cancellation on a fresh deep link without editor retention', async () => {
  const base = server();
  const job = { id: 'blocked', workspace_id: 'default', kind: 'generate', status: 'blocked_authorization', stage: 'blocked', inputs: { operation: 'new' }, created_at: 0, updated_at: 0, result: null, error: null, created_by_session_id: 'session1' };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', jobs: [job], event_cursor: 0 });
    if (url.endsWith('/model-settings')) return response({ providers: PROVIDERS, session_keys_allowed: true, credential_ref: null, configured: true, source: 'server', provider: 'openai', model: 'test', expires_at: null });
    if (url.endsWith('/jobs/blocked/cancel')) { job.status = 'cancelled'; return response(job); }
    if (url.endsWith('/jobs/blocked')) return response(job);
    return base(url, init);
  });
  mount(fetcher, '/jobs/blocked');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Reauthorize generation' })).toBeEnabled());
  expect(screen.getAllByRole('button', { name: /cancel generation|request cancellation/i })).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Cancel generation' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/jobs/blocked/cancel'))).toBe(true));
  expect(sessionStorage.getItem('arena:editor:generate:v1')).toBeNull();
});
it('retires a job cancellation before dispatch when navigation overtakes activity preflight', async () => {
  const base = server();
  const job = { id: 'pending-cancel', workspace_id: 'default', kind: 'diagnostic', status: 'queued', stage: 'queued', inputs: { steps: 3, delay_seconds: 1 }, created_at: 0, updated_at: 0, result: null, error: null, created_by_session_id: 'session1' };
  let release!: (value: Response) => void;
  const activity = new Promise<Response>(resolve => { release = resolve; });
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', jobs: [job], event_cursor: 0 });
    if (url.endsWith('/session/activity')) return activity;
    if (url.endsWith('/jobs/pending-cancel/cancel')) return response(job);
    return base(url, init);
  });
  mount(fetcher, '/jobs/pending-cancel');
  fireEvent.click(await screen.findByRole('button', { name: 'Request cancellation' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/session/activity'))).toBe(true));
  fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
  await screen.findByRole('heading', { name: 'Neo4j query' });
  await act(async () => { release(response(session)); });
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/jobs/pending-cancel/cancel'))).toBe(false);
});
it('toggles the sidebar theme and retains it across reload without submitting jobs', async () => {
  const fetcher = server();
  const view = mount(fetcher);
  const toggle = await screen.findByRole('switch', { name: 'Dark mode' });
  expect(toggle.closest('aside')).not.toBeNull();
  expect(toggle).toHaveAttribute('aria-checked', 'false');
  fireEvent.click(toggle);
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  expect(localStorage.getItem('arena.workbench.theme')).toBe('dark');
  view.unmount();
  mount(fetcher);
  expect(await screen.findByRole('switch', { name: 'Dark mode' })).toHaveAttribute('aria-checked', 'true');
  fireEvent.click(screen.getByRole('switch', { name: 'Dark mode' }));
  expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  expect(fetcher.mock.calls.filter(([url]) => url === '/api/jobs')).toHaveLength(0);
});
it('keeps theme switching usable when browser storage is unavailable', async () => {
  const read = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
  const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
  try {
    mount(server());
    fireEvent.click(await screen.findByRole('switch', { name: 'Dark mode' }));
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  } finally {
    read.mockRestore();
    write.mockRestore();
  }
});
it('loads a deep-linked job route without submitting a job and labels unimplemented capabilities', async () => {
  const fetcher = server();
  mount(fetcher, '/jobs/unknown');
  expect(await screen.findByRole('heading', { name: 'Job not found' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Run integration test' })).toBeDisabled();
  expect(screen.getByRole('link', { name: 'Environment editor' })).toBeInTheDocument();
  expect(screen.getByText(/not a robotics result/i)).toBeInTheDocument();
  expect(
    fetcher.mock.calls.filter(([url, init]) => url === '/api/jobs' && init?.method === 'POST'),
  ).toHaveLength(0);
});
it('requires server capability and explicit consent; ambiguous failures retain inputs across reload without replay', async () => {
  const fetcher = server(true);
  const view = mount(fetcher);
  const consent = await screen.findByRole('checkbox', { name: /enable diagnostic controls/i });
  const run = screen.getByRole('button', { name: 'Run integration test' });
  expect(run).toBeDisabled();
  fireEvent.click(consent);
  expect(run).toBeEnabled();
  fireEvent.click(run);
  expect(await screen.findByText(/connection lost/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Retry retained request' })).toBeEnabled();
  const sent = fetcher.mock.calls.filter(([url]) => url === '/api/jobs');
  expect(sent).toHaveLength(1);
  const body = sent[0][1]?.body;
  view.unmount();
  mount(fetcher);
  expect(await screen.findByRole('button', { name: 'Retry retained request' })).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => url === '/api/jobs')).toHaveLength(1);
  fireEvent.click(screen.getByRole('checkbox', { name: /enable diagnostic controls/i }));
  fireEvent.click(screen.getByRole('button', { name: 'Retry retained request' }));
  await waitFor(() =>
    expect(fetcher.mock.calls.filter(([url]) => url === '/api/jobs')).toHaveLength(2),
  );
  expect(fetcher.mock.calls.filter(([url]) => url === '/api/jobs')[1][1]?.body).toBe(body);
});
it.each([
  ['/?layout=v7', false],
  ['/developer/diagnostics?layout=v7', false],
  ['/jobs/queued-generate?layout=v7', false],
  ['/?layout=v7', true],
] as const)('exposes global Resume queue with diagnostics disabled on actual App %s (unavailable diagnostic retention: %s)', async (path, unavailableRetention) => {
  if (unavailableRetention) sessionStorage.setItem('arena:default:pending-diagnostic:v1', 'unresolved invalid diagnostic storage');
  const base = server(false);
  const jobs = ['generate', 'build'].map(kind => ({ id: `queued-${kind}`, workspace_id: 'default', kind, status: 'queued', stage: 'queued', inputs: {}, created_at: 0, updated_at: 0, result: null, error: null, created_by_session_id: 'session1' }));
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', jobs, event_cursor: 1 });
    if (url.endsWith('/jobs/resume-queue')) return response({ resumed: true });
    if (url.endsWith('/jobs/queued-generate')) return response(jobs[0]);
    return base(url, init);
  });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  const view = mount(fetcher, path);
  await waitFor(() => expect(document.querySelector('.app-shell')).toHaveClass('workbench-v7'));
  const resume = await screen.findByRole('button', { name: 'Resume queue' });
  expect(resume).toBeVisible();
  expect(resume).toBeEnabled();
  expect(screen.getAllByRole('button', { name: /^Resume queue$/ })).toHaveLength(1);
  expect(screen.getByText(/Observed queued jobs: 2/)).toHaveTextContent(/generate: 1/);
  expect(screen.getByText(/Observed queued jobs: 2/)).toHaveTextContent(/build: 1/);
  expect(screen.getByText(/Queued jobs do not prove/)).toBeInTheDocument();
  expect(screen.getByText(/entire shared workload queue.*including jobs not shown/i)).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/jobs/resume-queue'))).toBe(false);
  fireEvent.click(resume);
  expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/entire shared.*generation.*GPU.*not shown/s));
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/jobs/resume-queue'))).toBe(false);
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/session/activity'))).toBe(false);
  confirm.mockReturnValue(true);
  fireEvent.click(resume);
  expect(await screen.findByText(/Queue resume acknowledged/)).toBeInTheDocument();
  const posts = fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/resume-queue'));
  expect(posts).toHaveLength(1);
  expect(posts[0][1]).toMatchObject({ method: 'POST', credentials: 'same-origin', body: '{}', headers: { 'X-CSRF-Token': session.csrf_token } });
  fireEvent.click(screen.getByRole('button', { name: 'Reconnect session' }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/sessions'))).toHaveLength(2));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Resume queue' })).toBeEnabled());
  view.unmount();
  mount(fetcher, path);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Resume queue' })).toBeEnabled());
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/resume-queue'))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([url, init]) => init?.method === 'POST' && (url === '/api/jobs' || url.endsWith('/cancel')))).toHaveLength(0);
});
it.each(['before click', 'inside confirmation', 'during preflight'] as const)('rejects shared queue resume after same-ID replacement %s and permits freshly rendered controls', async boundary => {
  const base = server(false);
  let api: ApiClient;
  let release!: (value: Response) => void;
  let delayActivity = boundary === 'during preflight';
  const activity = new Promise<Response>(resolve => { release = resolve; });
  const queued = { id: 'queued-render', workspace_id: 'default', kind: 'snapshots', status: 'queued', stage: 'queued', inputs: {}, created_at: 0, updated_at: 0, result: null, error: null, created_by_session_id: 'session1' };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', jobs: [queued], event_cursor: 1 });
    if (url.endsWith('/session/activity')) return delayActivity ? activity : response({ ...session, expires_at: 99999999999 });
    if (url.endsWith('/jobs/resume-queue')) return response({ resumed: true });
    return base(url, init);
  });
  api = new ApiClient(fetcher as typeof fetch);
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<App api={api} cache={cache} history={createMemoryHistory({ initialEntries: ['/developer/diagnostics'] })} makePort={() => null} />);
  const resume = await screen.findByRole('button', { name: 'Resume queue' });
  const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => {
    if (boundary === 'inside confirmation') api.session = { ...session };
    return true;
  });
  const retentionKey = 'arena:editor:generate:v1';
  sessionStorage.setItem(retentionKey, 'replacement owner bytes');
  const write = vi.spyOn(Storage.prototype, 'setItem');
  const remove = vi.spyOn(Storage.prototype, 'removeItem');
  fetcher.mockClear();
  act(() => {
    if (boundary === 'before click') api.session = { ...session };
    fireEvent.click(resume);
  });
  if (boundary === 'during preflight') {
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/session/activity'))).toBe(true));
    api.session = { ...session };
    await act(async () => { release(response(session)); });
  } else await act(async () => {});
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/session/activity'))).toHaveLength(boundary === 'during preflight' ? 1 : 0);
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/jobs/resume-queue'))).toBe(false);
  if (boundary === 'before click') expect(confirm).not.toHaveBeenCalled();
  else expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/entire shared.*generation.*GPU.*not shown/s));
  expect(write).not.toHaveBeenCalled();
  expect(remove).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(retentionKey)).toBe('replacement owner bytes');

  // Explicit local rendering adopts the replacement; ordinary activity must not retire it.
  act(() => { cache.setQueryData<Workspace>(workspaceKey, previous => previous && ({ ...previous, event_cursor: 2 })); });
  await waitFor(() => expect(screen.getByText('2', { selector: '.panel-foot code' })).toBeInTheDocument());
  confirm.mockReturnValue(true);
  delayActivity = false;
  const generation = api.sessionGeneration;
  await act(async () => { await api.activity(); });
  expect(api.sessionGeneration).toBe(generation);
  fetcher.mockClear();
  fireEvent.click(screen.getByRole('button', { name: 'Resume queue' }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/resume-queue'))).toHaveLength(1));
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/session/activity'))).toHaveLength(1);
  expect(sessionStorage.getItem(retentionKey)).toBe('replacement owner bytes');
});
it.each(['navigation', 'unmount'])('retires confirmed queue resume during pending activity on %s', async boundary => {
  const base = server(false);
  const queued = { id: 'queued-render', workspace_id: 'default', kind: 'snapshots', status: 'queued', stage: 'queued', inputs: {}, created_at: 0, updated_at: 0, result: null, error: null, created_by_session_id: 'session1' };
  let release!: (value: Response) => void;
  const activity = new Promise<Response>(resolve => { release = resolve; });
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', jobs: [queued], event_cursor: 1 });
    if (url.endsWith('/session/activity')) return activity;
    if (url.endsWith('/jobs/resume-queue')) return response({ resumed: true });
    return base(url, init);
  });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  const view = mount(fetcher);
  fireEvent.click(await screen.findByRole('button', { name: 'Resume queue' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/session/activity'))).toBe(true));
  if (boundary === 'navigation') {
    fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
    await screen.findByRole('heading', { name: 'Neo4j query' });
  } else view.unmount();
  await act(async () => { release(response(session)); });
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/jobs/resume-queue'))).toBe(false);
});
it.each([
  ['navigation', 'success'], ['navigation', 'failure'],
  ['session', 'success'], ['session', 'failure'],
  ['unmount', 'success'], ['unmount', 'failure'],
] as const)('retires late queue POST %s / %s without refreshing or publishing to a replacement owner', async (boundary, outcome) => {
  const base = server(false);
  const queued = { id: 'queued-build', workspace_id: 'default', kind: 'build', status: 'queued', stage: 'queued', inputs: {}, created_at: 0, updated_at: 0, result: null, error: null, created_by_session_id: session.session_id };
  let release!: (value: Response) => void;
  const pending = new Promise<Response>(resolve => { release = resolve; });
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', jobs: [queued], event_cursor: 1 });
    if (url.endsWith('/jobs/resume-queue')) return pending;
    return base(url, init);
  });
  const api = new ApiClient(fetcher as typeof fetch);
  const view = render(<App api={api} cache={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })} history={createMemoryHistory({ initialEntries: ['/developer/diagnostics?layout=v7'] })} makePort={() => null} />);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  fireEvent.click(await screen.findByRole('button', { name: 'Resume queue' }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/resume-queue'))).toHaveLength(1));
  if (boundary === 'navigation') {
    fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
    await screen.findByRole('heading', { name: 'Neo4j query' });
    fireEvent.click(screen.getByRole('link', { name: 'Jobs & diagnostics' }));
    await screen.findByRole('heading', { name: 'Integration diagnostic' });
  } else if (boundary === 'unmount') view.unmount();
  else api.session = { ...session }; // Retire even before React observes the generation.
  fetcher.mockClear();
  await act(async () => { release(outcome === 'success' ? response({ resumed: true }) : response({ detail: 'synthetic-sensitive-response' }, 500)); });
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/workspaces/default'))).toHaveLength(0);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/resume-queue'))).toHaveLength(0);
  expect(screen.queryByText(/Queue resume acknowledged|Queue resume acknowledgement unavailable|synthetic-sensitive-response/)).not.toBeInTheDocument();
});
it('keeps a navigable disconnected shell when the API is down', async () => {
  const fetcher = vi.fn().mockRejectedValue(new TypeError('API offline'));
  mount(fetcher);
  expect(await screen.findByText('API offline')).toBeInTheDocument();
  expect(screen.getByText('Capability unknown')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Arena workspace' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Reconnect session' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Run integration test' })).toBeDisabled();
});
it('marks a back-forward cache restore disconnected instead of claiming a stopped observer is live', async () => {
  const fetcher = server();
  mount(fetcher);
  await screen.findByRole('button', { name: 'End session' });
  fireEvent(window, new Event('pagehide'));
  fireEvent(window, new PageTransitionEvent('pageshow', { persisted: true }));
  expect(await screen.findByText('Disconnected', { exact: true })).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => url === '/api/jobs')).toHaveLength(0);
});
