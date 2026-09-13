import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { ModelSettings, useModelSettings } from './model-settings';
import type { ModelSettingsStatus } from './model-settings-contracts';

const runtime = vi.hoisted(() => ({ current: {} as { api: ApiClient; session: { session_id: string } | null } }));
vi.mock('./runtime', () => ({ useRuntime: () => runtime.current }));
const providers: ModelSettingsStatus['providers'] = [
  { id: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com/v1' },
  { id: 'gemini', label: 'Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/' },
  { id: 'openrouter', label: 'OpenRouter', base_url: 'https://openrouter.ai/api/v1' },
  { id: 'nvidia', label: 'NVIDIA', base_url: 'https://integrate.api.nvidia.com/v1' },
];
const empty: ModelSettingsStatus = { providers, configured: false, source: 'none', provider: null, model: null,
  expires_at: null, credential_ref: null, session_keys_allowed: true };
const configured: ModelSettingsStatus = { ...empty, configured: true, source: 'session', provider: 'openai', model: 'user-model',
  expires_at: 9999999999, credential_ref: 'public-ref-one' };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function Harness() { return <ModelSettings settings={useModelSettings()} />; }
function setup(handler?: (url: string, init: RequestInit) => Promise<Response>) {
  let status = empty;
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (handler) return handler(url, init);
    if (init.method === 'PUT') status = configured;
    return response(status);
  });
  const api = new ApiClient(fetcher as typeof fetch);
  api.session = { session_id: 'one', csrf_token: 'csrf', expires_at: 9999999999 };
  runtime.current = { api, session: api.session };
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const view = render(<QueryClientProvider client={cache}><Harness /></QueryClientProvider>);
  return { ...view, api, cache, fetcher, redraw: () => view.rerender(<QueryClientProvider client={cache}><Harness /></QueryClientProvider>) };
}
beforeEach(() => { sessionStorage.clear(); localStorage.clear(); });
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

it.each(['provider', 'model', 'expiration', 'consent', 'session', 'unmount', 'pagehide'])('clears an unsent password at the %s boundary', async (boundary) => {
  const view = setup();
  await screen.findByText(/No provider configured/);
  const password = screen.getByLabelText('API key');
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'user-model' } });
  fireEvent.click(screen.getByRole('checkbox'));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save temporary key' })).toBeEnabled());
  fireEvent.change(password, { target: { value: 'dummy-boundary-marker' } });
  if (boundary === 'provider') fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'gemini' } });
  if (boundary === 'model') fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'other-model' } });
  if (boundary === 'expiration') fireEvent.change(screen.getByLabelText('Key expiration'), { target: { value: '60' } });
  if (boundary === 'consent') fireEvent.click(screen.getByRole('checkbox'));
  if (boundary === 'session') { runtime.current = { ...runtime.current, session: { session_id: 'two' } }; view.redraw(); }
  if (boundary === 'unmount') view.unmount();
  if (boundary === 'pagehide') fireEvent(window, new Event('pagehide'));
  expect(password).toHaveValue('');
  if (boundary !== 'unmount') expect(screen.getByRole('checkbox')).not.toBeChecked();
  expect(view.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
});

it.each([15, 30, 60, 120])('sends the selected %s minute expiration only on explicit save', async (minutes) => {
  const { fetcher } = setup();
  await screen.findByText(/No provider configured/);
  const expiry = screen.getByRole('combobox', { name: 'Key expiration' });
  expect(expiry).toHaveValue('30');
  fireEvent.change(expiry, { target: { value: String(minutes) } });
  expect(fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'user-model' } });
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'dummy-expiration-marker' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save temporary key' }));
  await screen.findByText(/Temporary key active/);
  const put = fetcher.mock.calls.find(([, init]) => init.method === 'PUT')!;
  expect(JSON.parse(String(put[1].body)).ttl_minutes).toBe(minutes);
  expect(screen.getByLabelText('API key')).toHaveValue('');
});

it('clears any pre-consent password when consent is first granted', async () => {
  setup();
  await screen.findByText(/No provider configured/);
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'dummy-pre-consent' } });
  fireEvent.click(screen.getByRole('checkbox'));
  expect(screen.getByLabelText('API key')).toHaveValue('');
  expect(screen.getByRole('checkbox')).toBeChecked();
});

it.each([400, 401, 500])('clears failed %s attempts without displaying or caching raw errors or retrying', async (code) => {
  const { fetcher, cache } = setup(async (_url, init) => init.method === 'PUT'
    ? response({ detail: 'dummy-error-secret' }, code) : response(empty));
  await screen.findByText(/No provider configured/);
  const password = screen.getByLabelText('API key');
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'user-model' } });
  fireEvent.click(screen.getByRole('checkbox'));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save temporary key' })).toBeEnabled());
  fireEvent.change(password, { target: { value: 'dummy-error-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save temporary key' }));
  expect(password).toHaveValue('');
  // Even a password manager/script refilling during the request must be cleared at settlement.
  fireEvent.change(password, { target: { value: 'dummy-error-secret' } });
  await screen.findByText(/Could not update temporary provider settings/);
  expect(password).toHaveValue('');
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  expect(document.body.textContent).not.toContain('dummy-error-secret');
  expect(JSON.stringify(cache.getQueryCache().getAll().map(q => q.state))).not.toContain('dummy-error-secret');
  expect(cache.getMutationCache().getAll()).toHaveLength(0);
  expect(fetcher.mock.calls.filter(([, init]) => init.method === 'PUT')).toHaveLength(1);
});

it('forgets via DELETE, clears entry, and reads back the server fallback without calling a provider', async () => {
  let status = configured;
  const { fetcher } = setup(async (_url, init) => {
    if (init.method === 'DELETE') status = { ...configured, source: 'server', credential_ref: null, expires_at: null };
    return response(status);
  });
  await screen.findByText(/Temporary key active/);
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'dummy-forget-marker' } });
  fireEvent.click(screen.getByRole('button', { name: 'Forget key' }));
  expect(screen.getByLabelText('API key')).toHaveValue('');
  await screen.findByText(/Server environment fallback active/);
  expect(fetcher.mock.calls.filter(([, init]) => init.method === 'DELETE')).toHaveLength(1);
  expect(fetcher.mock.calls.at(-1)?.[1].method).toBe('GET');
  expect(screen.queryByRole('button', { name: 'Forget key' })).not.toBeInTheDocument();
});

it('refreshes only public metadata on focus and interval to observe other-tab rotation and expiry', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let status = configured;
  const { fetcher } = setup(async () => response(status));
  await screen.findByText(/Temporary key active/);
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'dummy-other-tab-marker' } });
  status = { ...configured, model: 'rotated-model', credential_ref: 'public-ref-two' };
  fireEvent.focus(window);
  await screen.findByText(/Temporary key active.*rotated-model/);
  expect(screen.getByLabelText('API key')).toHaveValue('');
  status = { ...empty };
  await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
  vi.useRealTimers();
  await screen.findByText(/No provider configured/);
  expect(fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
});

it('marks a locally expired credential unavailable even before polling can succeed', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const deadline = Date.now() + 2000;
  setup(async () => response({ ...configured, expires_at: deadline / 1000 }));
  await screen.findByText(/Temporary key active/);
  await act(async () => { vi.setSystemTime(deadline + 1); await vi.advanceTimersByTimeAsync(2500); });
  vi.useRealTimers();
  expect(screen.getByText(/Temporary key expired/)).toBeInTheDocument();
  expect(screen.queryByText(/Temporary key active/)).not.toBeInTheDocument();
});

it.each(['denied', 'unavailable'])('disables secret entry when settings are %s and explains why', async (mode) => {
  setup(async () => mode === 'denied' ? response({ ...empty, session_keys_allowed: false })
    : response({ detail: 'dummy-private-error' }, 503));
  await screen.findByText(mode === 'denied' ? /requires a configured HTTPS or loopback origin/ : /Provider settings unavailable/);
  expect(screen.getByLabelText('API key')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Save temporary key' })).toBeDisabled();
  expect(document.body.textContent).not.toContain('dummy-private-error');
});

it('sanitizes both successful metadata and GET failures before React Query retains them', async () => {
  let fail = false;
  const { cache } = setup(async () => fail ? response({ detail: 'dummy-get-secret' }, 500)
    : response({ ...empty, api_key: 'dummy-get-secret' }));
  await screen.findByText(/No provider configured/);
  expect(cache.getQueryData(['model-settings', 'one'])).not.toHaveProperty('api_key');
  fail = true;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh provider status' }));
  await screen.findByText(/Provider settings unavailable/);
  expect(cache.getQueryState(['model-settings', 'one'])?.error?.message).not.toContain('dummy-get-secret');
  expect(screen.getByLabelText('API key')).toBeDisabled();
});

it.each(['no-consent', 'blank-model', 'long-model', 'short-key', 'long-key', 'secret-in-model'])('clears invalid %s submission attempts without a request', async (mode) => {
  const { fetcher } = setup();
  await screen.findByText(/No provider configured/);
  expect(screen.getByLabelText('Model')).toHaveAttribute('maxlength', '256');
  expect(screen.getByLabelText('API key')).toHaveAttribute('maxlength', '4096');
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: mode === 'blank-model' ? ' ' : mode === 'long-model' ? 'm'.repeat(257) : mode === 'secret-in-model' ? 'dummy-validation-marker' : 'model' } });
  if (mode !== 'no-consent') fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: mode === 'long-key' ? 'k'.repeat(4097) : mode === 'short-key' ? 'short' : 'dummy-validation-marker' } });
  fireEvent.submit(screen.getByRole('button', { name: 'Save temporary key' }).closest('form')!);
  expect(screen.getByLabelText('API key')).toHaveValue('');
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  expect(fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
});

it('ignores an old write response after the browser session changes', async () => {
  let finish: (r: Response) => void = () => {};
  const view = setup(async (_url, init) => init.method === 'PUT'
    ? new Promise<Response>(resolve => { finish = resolve; }) : response(empty));
  await screen.findByText(/No provider configured/);
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'old-model' } });
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'dummy-old-session-marker' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save temporary key' }));
  await waitFor(() => expect(view.fetcher.mock.calls.some(([, init]) => init.method === 'PUT')).toBe(true));

  view.api.session = { session_id: 'two', csrf_token: 'csrf-two', expires_at: 9999999999 };
  runtime.current = { api: view.api, session: view.api.session };
  view.redraw();
  await waitFor(() => expect(screen.getByLabelText('Model')).toBeEnabled());
  await waitFor(() => expect(screen.getByLabelText('API key')).toBeEnabled());
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'new-model' } });
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'dummy-new-session-marker' } });
  await act(async () => { finish(response({ detail: 'old request failed' }, 500)); });
  expect(screen.getByLabelText('API key')).toHaveValue('dummy-new-session-marker');
  expect(screen.getByRole('checkbox')).toBeChecked();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('saves only after consent using direct CSRF mutation, clears immediately, caches only public status and never calls inference', async () => {
  const { cache, fetcher } = setup();
  await screen.findByText(/No provider configured/);
  const password = screen.getByLabelText('API key');
  expect(password).toHaveAttribute('type', 'password');
  expect(password).toHaveAttribute('autocomplete', 'new-password');
  expect(screen.getByLabelText('Model')).toHaveValue('');
  expect(screen.getByLabelText('Provider endpoint')).toHaveValue(providers[0].base_url);
  expect(screen.getByLabelText('Provider endpoint')).toHaveAttribute('readonly');
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'user-model' } });
  expect(screen.getByRole('button', { name: 'Save temporary key' })).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.change(password, { target: { value: 'dummy-secret-marker' } });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save temporary key' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Save temporary key' }));
  expect(password).toHaveValue('');
  await screen.findByText(/Temporary key active/);
  const put = fetcher.mock.calls.find(([, init]) => init.method === 'PUT')!;
  expect(put[0]).toBe('/api/model-settings');
  expect(JSON.parse(String(put[1].body))).toEqual({ provider: 'openai', model: 'user-model', api_key: 'dummy-secret-marker', ttl_minutes: 30 });
  expect(put[1].headers).toMatchObject({ 'X-CSRF-Token': 'csrf' });
  expect(fetcher.mock.calls.filter(([, init]) => init.method === 'GET').length).toBeGreaterThanOrEqual(2);
  expect(cache.getMutationCache().getAll()).toHaveLength(0);
  expect(JSON.stringify(cache.getQueryCache().getAll().map(q => q.state))).not.toContain('dummy-secret-marker');
  expect(JSON.stringify(sessionStorage)).not.toContain('dummy-secret-marker');
  expect(JSON.stringify(localStorage)).not.toContain('dummy-secret-marker');
  expect(fetcher.mock.calls.every(([url]) => url === '/api/model-settings')).toBe(true);
  expect(screen.getByText(/shared by tabs/)).toBeInTheDocument();
  expect(screen.getByText(/already running.*may finish/i)).toBeInTheDocument();
});
