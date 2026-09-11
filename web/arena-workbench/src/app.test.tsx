import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { App } from './app';
import { ApiClient } from './api';
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
