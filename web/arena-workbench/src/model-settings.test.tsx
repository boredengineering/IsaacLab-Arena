import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { ModelSettings, useModelSettings } from './model-settings';
import type { ModelSettingsStatus } from './model-settings-contracts';
import { clientSessionScope } from './client-session-scope';

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
const documented: ModelSettingsStatus = { ...empty, profile_catalogue_version: 'harness-model-profiles/v1', effective_profile: null,
  profiles: [
    { id: 'openai-gpt-4.1', revision: 1, provider: 'openai', model: 'gpt-4.1', endpoint: providers[0].base_url,
      support: 'documented', documentation_urls: ['https://platform.openai.com/docs/models/gpt-4.1'],
      request_policy: { api: 'chat_completions', structured_output: 'json_schema', temperature_mode: 'configured', token_limit_parameter: 'max_tokens', store: null } },
    { id: 'openai-gpt-6-astra', revision: 1, provider: 'openai', model: 'gpt-6-astra', endpoint: providers[0].base_url,
      support: 'documented', documentation_urls: ['https://developers.openai.com/api/docs/models/gpt-6-astra'],
      request_policy: { api: 'chat_completions', structured_output: 'json_schema', temperature_mode: 'omitted', token_limit_parameter: 'max_completion_tokens', store: false } },
  ] };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function Harness({ active = true }: { active?: boolean }) {
  const settings = useModelSettings(active);
  return active ? <ModelSettings settings={settings} /> : null;
}
function delayed<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
function enterDummyKey(marker = 'dummy-scope-boundary-marker') {
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'scope-model' } });
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: marker } });
}
function replaceSettingsOwner(view: ReturnType<typeof setup>, mode: 'same-id' | 'client', redraw = true) {
  const api = mode === 'client' ? new ApiClient(view.fetcher as typeof fetch) : view.api;
  api.session = { session_id: 'one', csrf_token: 'dummy-replacement-csrf', expires_at: 9999999999 };
  runtime.current = { api, session: api.session };
  if (redraw) view.redraw();
}
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
  return { ...view, api, cache, fetcher, redraw: (active = true) => view.rerender(<QueryClientProvider client={cache}><Harness active={active} /></QueryClientProvider>) };
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

it('saves Never expires without a key timer and displays the session boundary on refresh', async () => {
  let status: ModelSettingsStatus = empty;
  const { fetcher, cache } = setup(async (_url, init) => {
    if (init.method === 'PUT') status = { ...configured, key_timer_disabled: true };
    return response(status);
  });
  await screen.findByText(/No provider configured/);
  const expiry = screen.getByRole('combobox', { name: 'Key expiration' });
  expect(screen.getByRole('option', { name: 'Never expires' })).toBeInTheDocument();
  fireEvent.change(expiry, { target: { value: 'never' } });
  expect(fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'user-model' } });
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'dummy-never-expiry-marker' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save temporary key' }));
  await screen.findByText(/Temporary key active.*No key timer/);
  const put = fetcher.mock.calls.find(([, init]) => init.method === 'PUT')!;
  expect(JSON.parse(String(put[1].body)).ttl_minutes).toBeNull();
  expect(screen.getByLabelText('API key')).toHaveValue('');
  expect(JSON.stringify(cache.getQueryCache().getAll().map(q => q.state))).not.toContain('dummy-never-expiry-marker');
  expect(screen.getByText(/cleared when the session ends or the API restarts/)).toBeInTheDocument();
  fireEvent.change(expiry, { target: { value: '30' } });
  fireEvent.click(screen.getByRole('button', { name: 'Refresh provider status' }));
  await screen.findByText(/Temporary key active.*No key timer/);
  expect(fetcher.mock.calls.filter(([, init]) => init.method === 'PUT')).toHaveLength(1);
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
  const key = clientSessionScope(runtime.current.api, runtime.current.session).queryKey;
  expect(cache.getQueryData(key)).toBeDefined();
  expect(cache.getQueryData(key)).not.toHaveProperty('api_key');
  fail = true;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh provider status' }));
  await screen.findByText(/Provider settings unavailable/);
  expect(cache.getQueryState(key)?.error).toBeInstanceOf(Error);
  expect(cache.getQueryState(key)?.error?.message).not.toContain('dummy-get-secret');
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

// Scope regressions use the approved isolated focused runner.
it.each(['same-id', 'client'] as const)('clears unsent credentials and consent on %s owner replacement', async mode => {
  const view = setup();
  await screen.findByText(/No provider configured/);
  enterDummyKey();
  replaceSettingsOwner(view, mode);
  expect(screen.getByLabelText('API key')).toHaveValue('');
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  expect(view.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
});

it.each(['PUT', 'DELETE'] as const)('fences %s before React renders a same-ID replacement', async method => {
  const view = setup(async () => response(configured));
  await screen.findByText(/Temporary key active/);
  enterDummyKey();
  replaceSettingsOwner(view, 'same-id', false);
  if (method === 'PUT') fireEvent.submit(screen.getByRole('button', { name: 'Save temporary key' }).closest('form')!);
  else fireEvent.click(screen.getByRole('button', { name: 'Forget key' }));
  await act(async () => {});
  expect(view.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
  expect(screen.getByLabelText('API key')).toHaveValue('');
});

it.each(['same-id', 'client'] as const)('isolates late metadata from the %s replacement cache', async mode => {
  const old = delayed<Response>();
  const fresh = delayed<Response>();
  let reads = 0;
  const view = setup(async () => ++reads === 1 ? old.promise : fresh.promise);
  await waitFor(() => expect(reads).toBe(1));
  replaceSettingsOwner(view, mode);
  await act(async () => { old.resolve(response({ ...configured, model: 'retired-metadata' })); });
  expect(screen.queryByText(/Temporary key active.*retired-metadata/)).not.toBeInTheDocument();
  expect(screen.getByLabelText('API key')).toBeDisabled();
  await waitFor(() => expect(reads).toBe(2));
  await act(async () => { fresh.resolve(response({ ...configured, model: 'fresh-metadata' })); });
  await screen.findByText(/Temporary key active.*fresh-metadata/);
  const currentQueries = view.cache.getQueryCache().getAll().filter(q => q.getObserversCount() > 0);
  expect(currentQueries).toHaveLength(1);
  expect(currentQueries[0].queryKey).not.toEqual(['model-settings', 'one']);
  expect(JSON.stringify(currentQueries[0].queryKey)).not.toContain('dummy-replacement-csrf');
  expect(view.cache.getMutationCache().getAll()).toHaveLength(0);
});

it.each(['PUT', 'DELETE'] as const)('does not start %s readback after a same-ID replacement without render', async method => {
  const old = delayed<Response>();
  const view = setup(async (_url, init) => init.method === method ? old.promise : response(configured));
  await screen.findByText(/Temporary key active/);
  if (method === 'PUT') { enterDummyKey(); fireEvent.click(screen.getByRole('button', { name: 'Save temporary key' })); }
  else fireEvent.click(screen.getByRole('button', { name: 'Forget key' }));
  await waitFor(() => expect(view.fetcher.mock.calls.filter(([, init]) => init.method === method)).toHaveLength(1));
  const calls = view.fetcher.mock.calls.length;
  replaceSettingsOwner(view, 'same-id', false);
  await act(async () => { old.resolve(response(configured)); });
  expect(view.fetcher).toHaveBeenCalledTimes(calls);
});

it.each([
  ['same-id', 'write'], ['client', 'write'], ['same-id', 'readback'], ['client', 'readback'],
] as const)('drops retired %s callbacks during %s without clearing new consent', async (mode, phase) => {
  const old = delayed<Response>();
  let written = false;
  let heldReadback = false;
  const view = setup(async (_url, init) => {
    if (init.method === 'PUT') { written = true; return phase === 'write' ? old.promise : response(configured); }
    if (phase === 'readback' && written && !heldReadback) { heldReadback = true; return old.promise; }
    return response(empty);
  });
  await screen.findByText(/No provider configured/);
  enterDummyKey();
  fireEvent.click(screen.getByRole('button', { name: 'Save temporary key' }));
  await waitFor(() => expect(phase === 'readback' ? heldReadback : written).toBe(true));
  replaceSettingsOwner(view, mode);
  await waitFor(() => expect(screen.getByLabelText('Model')).toBeEnabled());
  await waitFor(() => expect(screen.getByLabelText('API key')).toBeEnabled());
  enterDummyKey('dummy-new-owner-marker');
  const calls = view.fetcher.mock.calls.length;
  await act(async () => { old.resolve(response({ detail: 'dummy-retired-error' }, 500)); });
  expect(view.fetcher).toHaveBeenCalledTimes(calls);
  expect(screen.getByLabelText('API key')).toHaveValue('dummy-new-owner-marker');
  expect(screen.getByRole('checkbox')).toBeChecked();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('preserves unsent credentials across ordinary activity and no-op redraws', async () => {
  const view = setup(async url => url === '/api/session/activity'
    ? response({ session_id: 'one', csrf_token: 'csrf', expires_at: 9999999999 }) : response(empty));
  await screen.findByText(/No provider configured/);
  enterDummyKey();
  const generation = view.api.sessionGeneration;
  await act(async () => { runtime.current = { api: view.api, session: await view.api.activity() }; });
  view.redraw();
  view.redraw();
  expect(view.api.sessionGeneration).toBe(generation);
  expect(screen.getByLabelText('API key')).toHaveValue('dummy-scope-boundary-marker');
  expect(screen.getByRole('checkbox')).toBeChecked();
  expect(view.fetcher.mock.calls.filter(([url]) => url === '/api/model-settings')).toHaveLength(1);
});

it.each(documented.profiles!)('selects $model only on explicit preset choice and saves credentials without claiming a live test', async profile => {
  let metadata = documented;
  const view = setup(async (_url, init) => {
    if (init.method === 'PUT') metadata = { ...documented, ...configured, model: profile.model,
      effective_profile: { id: profile.id, support: 'documented', verification: 'not_checked' } };
    return response(metadata);
  });
  await screen.findByText(/No provider configured/);
  const selector = screen.getByRole('combobox', { name: 'Model profile' });
  expect(screen.getByRole('option', { name: profile.model, exact: true })).toHaveValue(profile.id);
  expect(selector).toHaveValue('custom');
  expect(screen.getByLabelText('Model')).toHaveValue('');
  enterDummyKey();
  fireEvent.change(selector, { target: { value: profile.id } });
  expect(screen.getByLabelText('Provider')).toHaveValue(profile.provider);
  expect(screen.getByLabelText('Model')).toHaveValue(profile.model);
  expect(screen.getByLabelText('Provider endpoint')).toHaveValue(providers[0].base_url);
  expect(screen.getByLabelText('API key')).toHaveValue('');
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  expect(screen.getByText(/Documented adapter profile · not live verified/)).toBeInTheDocument();
  expect(screen.getByText(/Chat Completions.*json_schema/)).toBeInTheDocument();
  expect(screen.getByText(new RegExp('Temperature: ' + profile.request_policy.temperature_mode))).toBeInTheDocument();
  expect(screen.getByText(new RegExp(profile.request_policy.token_limit_parameter))).toBeInTheDocument();
  if (profile.request_policy.token_limit_parameter === 'max_completion_tokens') {
    expect(screen.getByText(/includes reasoning tokens/)).toBeInTheDocument();
  }
  expect(screen.getByRole('link', { name: 'Profile documentation 1' })).toHaveAttribute('href', profile.documentation_urls[0]);
  expect(view.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'dummy-profile-save-marker' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save temporary key' }));
  await screen.findByText(/Credential configured · not tested/);
  expect(screen.getByText(/Live structured-output test: not yet run · unavailable/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /test/i })).not.toBeInTheDocument();
  const writes = view.fetcher.mock.calls.filter(([, init]) => init.method === 'PUT');
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0][1].body))).toEqual({ provider: profile.provider, model: profile.model,
    api_key: 'dummy-profile-save-marker', ttl_minutes: 30 });
  expect(view.fetcher.mock.calls.every(([url]) => url === '/api/model-settings')).toBe(true);
  expect(screen.getByLabelText('API key')).toHaveValue('');
  expect(view.cache.getMutationCache().getAll()).toHaveLength(0);
  expect(JSON.stringify(view.cache.getQueryCache().getAll().map(q => q.state))).not.toContain('dummy-profile-save-marker');
});

it.each(['legacy', 'unknown-provider', 'malformed'] as const)('keeps %s credential configuration separate from compatibility and allows explicit custom entry', async mode => {
  const metadata = mode === 'legacy' ? configured : mode === 'unknown-provider'
    ? { ...configured, ...documented, configured: true, source: 'server', provider: 'unknown-provider', model: 'gpt-6-astra',
      effective_profile: { id: null, support: 'unverified', verification: 'not_checked' } }
    : { ...configured, ...documented, configured: true, source: 'session', provider: 'openai', model: 'user-model',
      credential_ref: 'public-ref-one', expires_at: 9999999999, profiles: [{ private: 'dummy-metadata-secret' }] };
  const view = setup(async () => response(metadata));
  await screen.findByText(/Credential configured · not tested/);
  expect(screen.getByText(/Effective profile: compatibility unverified/)).toBeInTheDocument();
  expect(screen.queryByText(/Provider settings unavailable/)).not.toBeInTheDocument();
  if (mode !== 'unknown-provider') expect(screen.getByText(/Profile presets unavailable/)).toBeInTheDocument();
  expect(screen.getByLabelText('Model')).toHaveValue('');
  fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'nvidia' } });
  enterDummyKey();
  expect(screen.getByText(/Custom profile · unverified/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save temporary key' })).toBeEnabled();
  expect(JSON.stringify(view.cache.getQueryCache().getAll().map(q => q.state))).not.toContain('dummy-metadata-secret');
  expect(view.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
});

function reactHandler<T>(node: Element, name: string): T {
  const key = Object.getOwnPropertyNames(node).find(k => k.startsWith('__reactProps$'))!;
  return (node as unknown as Record<string, Record<string, T>>)[key][name];
}

it.each(['focus', 'invalidate', 'source', 'profile', 'session'] as const)('retires preset consent and key at the %s metadata boundary, including retained submit handlers', async boundary => {
  const pendingRead = delayed<Response>();
  const view = setup(async () => response(documented));
  await screen.findByText(/No provider configured/);
  fireEvent.change(screen.getByRole('combobox', { name: 'Model profile' }), { target: { value: 'openai-gpt-6-astra' } });
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'dummy-retired-profile-marker' } });
  const form = screen.getByRole('button', { name: 'Save temporary key' }).closest('form')!;
  const submit = reactHandler<(e: { preventDefault: () => void }) => Promise<void>>(form, 'onSubmit');
  const key = clientSessionScope(view.api, view.api.session).queryKey;
  const query = view.cache.getQueryCache().find({ queryKey: key })!;
  expect(query).toBeDefined();
  view.fetcher.mockImplementation(async () => pendingRead.promise);
  await act(async () => {
    if (boundary === 'focus') window.dispatchEvent(new Event('focus'));
    if (boundary === 'invalidate') query.invalidate();
    if (boundary === 'source') view.cache.setQueryData(key, { ...documented, source: 'server', configured: true,
      provider: 'openai', model: 'gpt-4.1', effective_profile: { id: 'openai-gpt-4.1', support: 'documented', verification: 'not_checked' } });
    if (boundary === 'profile') view.cache.setQueryData(key, { ...documented, profiles: [] });
    if (boundary === 'session') replaceSettingsOwner(view, 'same-id', false);
    void submit({ preventDefault: () => {} });
  });
  expect(view.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
  expect(screen.getByLabelText('API key')).toHaveValue('');
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  if (boundary === 'session') view.redraw();
  expect(screen.getByRole('combobox', { name: 'Model profile' })).toHaveValue('custom');
  if (boundary === 'focus' || boundary === 'invalidate') {
    expect(screen.queryByText(/Documented adapter profile · not live verified/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save temporary key' })).toBeDisabled();
  }
  await act(async () => { pendingRead.resolve(response(documented)); });
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  expect(view.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
});

it('does not resurrect documented support from retained data after a failed refresh', async () => {
  let fail = false;
  setup(async () => fail ? response({ detail: 'dummy-profile-read-error' }, 503) : response(documented));
  await screen.findByText(/No provider configured/);
  fireEvent.change(screen.getByRole('combobox', { name: 'Model profile' }), { target: { value: 'openai-gpt-6-astra' } });
  expect(screen.getByText(/Documented adapter profile · not live verified/)).toBeInTheDocument();
  fail = true;
  fireEvent.focus(window);
  await screen.findByText(/Provider settings unavailable/);
  expect(screen.queryByText(/Documented adapter profile · not live verified/)).not.toBeInTheDocument();
  expect(screen.getByText(/Profile presets unavailable/)).toBeInTheDocument();
  expect(screen.getByLabelText('API key')).toHaveValue('');
  expect(screen.getByRole('combobox', { name: 'Model profile' })).toHaveValue('custom');
});

it('rejects retained preset selection before a same-ID session replacement renders', async () => {
  const view = setup(async () => response(documented));
  await screen.findByText(/No provider configured/);
  const select = screen.getByRole('combobox', { name: 'Model profile' });
  const change = reactHandler<(e: { target: { value: string } }) => void>(select, 'onChange');
  replaceSettingsOwner(view, 'same-id', false);
  act(() => change({ target: { value: 'openai-gpt-6-astra' } }));
  expect(screen.getByLabelText('Model')).toHaveValue('');
  expect(view.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
});

it('withholds stale credential-active claims during a refresh failure', async () => {
  let fail = false;
  setup(async () => fail ? response({}, 503) : response(configured));
  await screen.findByText(/Temporary key active/);
  fail = true;
  fireEvent.focus(window);
  await screen.findByText(/Provider settings unavailable/);
  expect(screen.queryByText(/Temporary key active/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Credential configured · not tested/)).not.toBeInTheDocument();
});

it('drops late profile metadata when the settings source is deactivated and requires a fresh read on return', async () => {
  const old = delayed<Response>();
  const fresh = delayed<Response>();
  let reads = 0;
  const view = setup(async () => ++reads === 1 ? old.promise : fresh.promise);
  await waitFor(() => expect(reads).toBe(1));
  const key = clientSessionScope(view.api, view.api.session).queryKey;
  view.redraw(false);
  await act(async () => { old.resolve(response(documented)); });
  expect(view.cache.getQueryData(key)).toBeUndefined();
  view.redraw(true);
  await waitFor(() => expect(reads).toBe(2));
  expect(screen.getByRole('combobox', { name: 'Model profile' })).toBeDisabled();
  await act(async () => { fresh.resolve(response(documented)); });
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Model profile' })).toBeEnabled());
  expect(screen.getByRole('combobox', { name: 'Model profile' })).toHaveValue('custom');
  expect(screen.getByLabelText('Model')).toHaveValue('');
  expect(view.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
});

it.each(['submit', 'preset'] as const)('retired %s handlers cannot erase a newly consented password after profile or session replacement', async action => {
  const view = setup(async () => response(documented));
  await screen.findByText(/No provider configured/);
  enterDummyKey();
  const form = screen.getByRole('button', { name: 'Save temporary key' }).closest('form')!;
  const submit = reactHandler<(e: { preventDefault: () => void }) => Promise<void>>(form, 'onSubmit');
  const change = reactHandler<(e: { target: { value: string } }) => void>(screen.getByRole('combobox', { name: 'Model profile' }), 'onChange');
  replaceSettingsOwner(view, 'same-id');
  await waitFor(() => expect(screen.getByLabelText('API key')).toBeEnabled());
  enterDummyKey('dummy-fresh-profile-owner');
  await act(async () => {
    if (action === 'submit') await submit({ preventDefault: () => {} });
    else change({ target: { value: 'openai-gpt-6-astra' } });
  });
  expect(screen.getByLabelText('API key')).toHaveValue('dummy-fresh-profile-owner');
  expect(screen.getByRole('checkbox')).toBeChecked();
  expect(view.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
});
