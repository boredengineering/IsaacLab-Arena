import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, it, vi } from 'vitest';
import { EditorJobProgress, useEditorJob } from './editor-jobs';
import { GenerationReauthorization } from './generation-reauthorization';
import type { Job } from './contracts';
import { workspaceKey } from './cache';
import { ApiClient } from './api';
import { useModelSettings } from './model-settings';
import { PROVIDERS } from './model-settings-contracts';
import { clientSessionScope } from './client-session-scope';

const mocks = vi.hoisted(() => ({ runtime: {} as any }));
vi.mock('./runtime', () => ({ useRuntime: () => mocks.runtime }));
vi.mock('@tanstack/react-router', () => ({ Link: ({ children }: any) => <a>{children}</a> }));
const blocked: Job = { id: 'job/actual', workspace_id: 'default', kind: 'generate', status: 'blocked_authorization', stage: 'blocked', inputs: { operation: 'new' }, created_at: 0, updated_at: 0, result: null, error: null, created_by_session_id: 's' };
let cache: QueryClient;
function Harness() {
  const controller = useEditorJob('generate');
  return <><output>{controller.busy ? 'busy' : 'idle'}</output><EditorJobProgress controller={controller} /></>;
}
function mount(job = blocked) {
  sessionStorage.setItem('arena:editor:generate:v1', JSON.stringify({ payload: { idempotency_key: 'original' }, job }));
  cache.setQueryData(workspaceKey, { id: 'default', jobs: [job], name: 'Arena', event_cursor: 0 });
  return render(<QueryClientProvider client={cache}><Harness /></QueryClientProvider>);
}
function settings(ref = 'a'.repeat(64), source = 'session') {
  cache.setQueryData(clientSessionScope(mocks.runtime.api, mocks.runtime.session).queryKey, { configured: true, source, credential_ref: ref, expires_at: 9999999999 });
}
beforeEach(() => {
  sessionStorage.clear();
  cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const session = { session_id: 's', csrf_token: 'csrf', expires_at: 9999999999 };
  mocks.runtime = { session, api: { session, activity: vi.fn(async () => session), get: vi.fn(async () => blocked), mutate: vi.fn(async () => ({ ...blocked, status: 'queued' })) }, refresh: vi.fn(async () => {}) };
  settings();
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});
it('retains a lost response across remount and retries the same frozen reference and ID', async () => {
  mocks.runtime.api.mutate.mockRejectedValueOnce(new Error('SECRET unsafe detail'));
  const view = mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Reauthorize generation' }));
  await screen.findByRole('alert');
  expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument();
  const original = mocks.runtime.api.mutate.mock.calls[0][1];
  view.unmount();
  settings('b'.repeat(64));
  mount();
  expect(mocks.runtime.api.mutate).toHaveBeenCalledTimes(1);
  fireEvent.click(await screen.findByRole('button', { name: /Retry reauthorization/ }));
  await waitFor(() => expect(mocks.runtime.api.mutate).toHaveBeenCalledTimes(2));
  expect(mocks.runtime.api.mutate.mock.calls[1][1]).toEqual(original);
});
it('ignores a late renewal response after the session is replaced', async () => {
  let resolve!: (value: unknown) => void;
  mocks.runtime.api.mutate.mockImplementation(() => new Promise(r => { resolve = r; }));
  const view = mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Reauthorize generation' }));
  await waitFor(() => expect(mocks.runtime.api.mutate).toHaveBeenCalledTimes(1));
  const reads = mocks.runtime.api.get.mock.calls.length;
  mocks.runtime.session = { ...mocks.runtime.session, session_id: 'replacement' };
  mocks.runtime.api.session = mocks.runtime.session;
  view.rerender(<QueryClientProvider client={cache}><Harness /></QueryClientProvider>);
  await act(async () => { resolve({ ...blocked, status: 'queued' }); });
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
  expect(mocks.runtime.api.get.mock.calls.slice(reads).filter(([url]: string[]) => url === '/jobs/job%2Factual')).toHaveLength(1); // existing hook's new-session read only
  expect(sessionStorage.getItem('arena:reauthorization:v1:job%2Factual')).not.toBeNull();
});
it('keeps blocked modern generation unresolved for the competing generation guard', async () => {
  mount();
  expect(await screen.findByText('busy')).toBeInTheDocument();
});
it.each([
  [{ released: true, candidate_accepted: false, outcome: 'unknown' }, 'External execution outcome is unknown'],
  [{ released: true, candidate_accepted: true, outcome: 'candidate_accepted' }, 'An accepted candidate was preserved'],
  [{ released: false, candidate_accepted: false, outcome: 'not_released' }, 'Cancelled before external work was released'],
] as const)('discloses cancellation evidence independently from status: %j', async (execution, message) => {
  mount({ ...blocked, status: 'cancelled', execution });
  expect(await screen.findByText(new RegExp(message))).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /reauthoriz/i })).not.toBeInTheDocument();
});
it.each(['indeterminate', 'running', 'succeeded', 'cancelled'] as const)('does not offer renewal for %s jobs', async status => {
  mount({ ...blocked, status });
  await act(async () => {});
  expect(screen.queryByRole('button', { name: /reauthoriz/i })).not.toBeInTheDocument();
  expect(mocks.runtime.api.mutate).not.toHaveBeenCalled();
});
it('leaves legacy generation callers unchanged', async () => {
  mount({ ...blocked, inputs: {} });
  await act(async () => {});
  expect(screen.queryByRole('button', { name: /reauthoriz/i })).not.toBeInTheDocument();
  expect(screen.getByText('idle')).toBeInTheDocument();
});
it('fails closed for expired settings without posting a renewal', async () => {
  settings();
  cache.setQueryData(clientSessionScope(mocks.runtime.api, mocks.runtime.session).queryKey, (old: any) => ({ ...old, expires_at: 1 }));
  mount();
  expect(await screen.findByRole('button', { name: 'Reauthorize generation' })).toBeDisabled();
  expect(mocks.runtime.api.mutate).not.toHaveBeenCalled();
});
it('does not replace unreadable retained renewal information', async () => {
  sessionStorage.setItem('arena:reauthorization:v1:job%2Factual', '{broken');
  mount();
  expect(await screen.findByRole('button', { name: 'Reauthorize generation' })).toBeDisabled();
  expect(await screen.findByRole('alert')).toHaveTextContent('retained renewal');
  expect(mocks.runtime.api.mutate).not.toHaveBeenCalled();
});
it('explicitly cancels a blocked modern generation through the existing endpoint', async () => {
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel generation' }));
  await waitFor(() => expect(mocks.runtime.api.mutate).toHaveBeenCalledWith('/jobs/job%2Factual/cancel', {}));
  await waitFor(() => expect(mocks.runtime.refresh).toHaveBeenCalled());
  expect(mocks.runtime.api.get).toHaveBeenLastCalledWith('/jobs/job%2Factual');
});
it('omits credential_ref for server configuration', async () => {
  settings('unused', 'server');
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Reauthorize generation' }));
  await waitFor(() => expect(mocks.runtime.refresh).toHaveBeenCalled());
  expect(mocks.runtime.api.mutate.mock.calls[0][1]).toEqual({ idempotency_key: expect.any(String) });
});
it.each(['post', 'readback'])('retains renewal on an exact-ID mismatch in %s', async phase => {
  mount();
  await act(async () => {});
  if (phase === 'post') mocks.runtime.api.mutate.mockResolvedValue({ ...blocked, id: 'other' });
  else mocks.runtime.api.get.mockResolvedValue({ ...blocked, id: 'other' });
  fireEvent.click(await screen.findByRole('button', { name: 'Reauthorize generation' }));
  await screen.findByRole('alert');
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
  expect(sessionStorage.getItem('arena:reauthorization:v1:job%2Factual')).not.toBeNull();
});
it('freezes the click payload across settings rotation and disables duplicate submission', async () => {
  let resolve!: (value: unknown) => void;
  mocks.runtime.api.mutate.mockImplementation(() => new Promise(r => { resolve = r; }));
  mount();
  const button = await screen.findByRole('button', { name: 'Reauthorize generation' });
  fireEvent.click(button);
  expect(screen.getByRole('button', { name: 'Reauthorizing…' })).toBeDisabled();
  act(() => { settings('b'.repeat(64)); });
  expect(mocks.runtime.api.mutate.mock.calls[0][1].credential_ref).toBe('a'.repeat(64));
  await act(async () => { resolve({ ...blocked, status: 'queued' }); });
  expect(mocks.runtime.api.mutate).toHaveBeenCalledTimes(1);
});
it('drops callbacks after navigation away', async () => {
  let resolve!: (value: unknown) => void;
  mocks.runtime.api.mutate.mockImplementation(() => new Promise(r => { resolve = r; }));
  const view = mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Reauthorize generation' }));
  view.unmount();
  await act(async () => { resolve({ ...blocked, status: 'queued' }); });
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
  expect(sessionStorage.getItem('arena:reauthorization:v1:job%2Factual')).not.toBeNull();
});
it('allows an explicit retained replay without silently requiring replacement settings', async () => {
  mocks.runtime.api.mutate.mockRejectedValueOnce(new Error('lost'));
  const view = mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Reauthorize generation' }));
  await screen.findByRole('alert');
  const original = mocks.runtime.api.mutate.mock.calls[0][1];
  view.unmount();
  cache.removeQueries({ queryKey: ['model-settings'] });
  mount();
  const retry = await screen.findByRole('button', { name: 'Retry reauthorization' });
  expect(retry).toBeEnabled();
  fireEvent.click(retry);
  await waitFor(() => expect(mocks.runtime.api.mutate).toHaveBeenCalledTimes(2));
  expect(mocks.runtime.api.mutate.mock.calls[1][1]).toEqual(original);
});
it('does not send under a replaced API session before React has rerendered', async () => {
  mount();
  const button = await screen.findByRole('button', { name: 'Reauthorize generation' });
  mocks.runtime.api.session = { ...mocks.runtime.session, session_id: 'replacement' };
  fireEvent.click(button);
  expect(mocks.runtime.api.mutate).not.toHaveBeenCalled();
});
it('renders without network side effects or a separate observation stream', async () => {
  render(<QueryClientProvider client={cache}><GenerationReauthorization job={blocked} onVerified={mocks.runtime.refresh} /></QueryClientProvider>);
  await act(async () => {});
  expect(mocks.runtime.api.get).not.toHaveBeenCalled();
  expect(mocks.runtime.api.mutate).not.toHaveBeenCalled();
  expect(mocks.runtime.api.activity).not.toHaveBeenCalled();
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
});
it('rejects an invalid readback even when its ID matches', async () => {
  mount();
  await act(async () => {});
  mocks.runtime.api.get.mockResolvedValue({ id: blocked.id });
  fireEvent.click(await screen.findByRole('button', { name: 'Reauthorize generation' }));
  await screen.findByRole('alert');
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
});
it.each(['unknown', 'malformed', 'mismatch', 'generic'])('keeps ambiguous %s proof pinned across remount', async mode => {
  mocks.runtime.api.mutate.mockRejectedValue(Object.assign(new Error(mode === 'generic' ? 'Conflict' : JSON.stringify({ schema_version: 1, code: mode === 'unknown' ? 'renewal_unknown' : 'renewal_rejected', job_id: 'wrong', idempotency_key: 'wrong', fingerprint: mode === 'malformed' ? 'bad' : 'f'.repeat(64) })), { status: 409 }));
  const view = mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Reauthorize generation' }));
  await screen.findByRole('alert');
  const first = mocks.runtime.api.mutate.mock.calls[0][1];
  expect(screen.queryByRole('button', { name: 'Use current credentials' })).not.toBeInTheDocument();
  view.unmount();
  settings('b'.repeat(64));
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Retry reauthorization' }));
  await waitFor(() => expect(mocks.runtime.api.mutate).toHaveBeenCalledTimes(2));
  expect(mocks.runtime.api.mutate.mock.calls[1][1]).toEqual(first);
});
it('recovers sealed proof after remount with one explicit read and no automatic post', async () => {
  mocks.runtime.api.mutate.mockRejectedValueOnce(new Error('lost response'));
  const view = mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Reauthorize generation' }));
  await screen.findByRole('alert');
  const first = mocks.runtime.api.mutate.mock.calls[0][1];
  view.unmount();
  const { createHash } = await import('node:crypto');
  const fp = createHash('sha256').update(JSON.stringify({ credential_ref: first.credential_ref ?? null, idempotency_key: first.idempotency_key })).digest('hex');
  mocks.runtime.api.get.mockImplementation(async (url: string) => url.includes('reauthorization-disposition') ? { schema_version: 1, code: 'renewal_rejected', job_id: blocked.id, idempotency_key: first.idempotency_key, fingerprint: fp } : blocked);
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Check renewal disposition' }));
  expect(await screen.findByRole('button', { name: 'Use current credentials' })).toBeEnabled();
  expect(mocks.runtime.api.mutate).toHaveBeenCalledTimes(1);
  expect(mocks.runtime.api.get.mock.calls.filter(([url]: string[]) => url.includes('reauthorization-disposition'))).toHaveLength(1);
});
it('uses corrected credentials only after a sealed rejection and separate confirmation', async () => {
  mocks.runtime.api.mutate.mockImplementationOnce(async (_url: string, payload: any) => {
    const { createHash } = await import('node:crypto');
    const fingerprint = createHash('sha256').update(JSON.stringify({ credential_ref: payload.credential_ref ?? null, idempotency_key: payload.idempotency_key })).digest('hex');
    throw Object.assign(new Error(JSON.stringify({ schema_version: 1, code: 'renewal_rejected', job_id: blocked.id, idempotency_key: payload.idempotency_key, fingerprint })), { status: 409 });
  });
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Reauthorize generation' }));
  const correction = await screen.findByRole('button', { name: 'Use current credentials' });
  const first = mocks.runtime.api.mutate.mock.calls[0][1];
  act(() => settings('b'.repeat(64)));
  await waitFor(() => expect(correction).toBeEnabled());
  vi.mocked(window.confirm).mockReturnValueOnce(false);
  fireEvent.click(correction);
  expect(mocks.runtime.api.mutate).toHaveBeenCalledTimes(1);
  fireEvent.click(correction);
  expect(mocks.runtime.api.mutate).toHaveBeenCalledTimes(1);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry reauthorization' }));
  await waitFor(() => expect(mocks.runtime.api.mutate).toHaveBeenCalledTimes(2));
  const second = mocks.runtime.api.mutate.mock.calls[1][1];
  expect(second.credential_ref).toBe('b'.repeat(64));
  expect(second.idempotency_key).not.toBe(first.idempotency_key);
  expect(mocks.runtime.api.mutate.mock.calls[1][0]).toBe(mocks.runtime.api.mutate.mock.calls[0][0]);
});
it('requires explicit confirmation and verifies the exact renewed job before refreshing', async () => {
  mount();
  const button = await screen.findByRole('button', { name: 'Reauthorize generation' });
  expect(mocks.runtime.api.mutate).not.toHaveBeenCalled();
  vi.mocked(window.confirm).mockReturnValueOnce(false);
  fireEvent.click(button);
  expect(mocks.runtime.api.mutate).not.toHaveBeenCalled();
  mocks.runtime.api.get.mockResolvedValue({ ...blocked, status: 'queued' });
  fireEvent.click(button);
  await waitFor(() => expect(mocks.runtime.refresh).toHaveBeenCalled());
  expect(window.confirm).toHaveBeenCalledWith(expect.stringMatching(/same frozen prompt and profile.*uncertain/s));
  expect(mocks.runtime.api.mutate).toHaveBeenCalledWith('/editor/generations/job%2Factual/reauthorize', { idempotency_key: expect.any(String), credential_ref: 'a'.repeat(64) });
  expect(mocks.runtime.api.get).toHaveBeenLastCalledWith('/jobs/job%2Factual');
});

function authorityDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
const authorityResponse = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const authorityMetadata = (ref = 'a'.repeat(64)) => ({ providers: PROVIDERS, configured: true, source: 'session',
  provider: 'openai', model: 'dummy-model', credential_ref: ref, expires_at: 9999999999, session_keys_allowed: true });
function MetadataOwner() { useModelSettings(); return null; }
function mountAuthority(owners = ['editor'], handler?: (url: string, init: RequestInit) => Promise<Response>) {
  cache.clear();
  const session = { session_id: 's', csrf_token: 'dummy-authority-csrf', expires_at: 9999999999 };
  const transport = vi.fn(async (url: string, init: RequestInit) => {
    if (handler) return handler(url, init);
    if (url === '/api/model-settings') return authorityResponse(authorityMetadata());
    if (url === '/api/session/activity') return authorityResponse(session);
    if (url === '/api/jobs/job%2Factual' || url === '/api/editor/generations/job%2Factual/reauthorize') return authorityResponse(blocked);
    throw new Error('Unexpected authority fixture request');
  });
  const api = new ApiClient(transport as typeof fetch);
  api.session = session;
  const verified = vi.fn();
  mocks.runtime = { api, session: api.session, refresh: vi.fn() };
  const tree = (names: string[]) => <QueryClientProvider client={cache}><MetadataOwner />{names.map(name =>
    <section key={name} aria-label={name}><GenerationReauthorization job={blocked} onVerified={() => verified(name)} /></section>
  )}</QueryClientProvider>;
  const view = render(tree(owners));
  return { ...view, api, transport, verified, redraw: (names = owners) => view.rerender(tree(names)),
    posts: () => transport.mock.calls.filter(([url, init]) => url.endsWith('/reauthorize') && init.method === 'POST') };
}
function retainedAuthority() {
  const keys = Object.keys(sessionStorage).filter(key => key.startsWith('arena:reauthorization:'));
  expect(keys).toHaveLength(1);
  const raw = sessionStorage.getItem(keys[0])!;
  return { key: keys[0], raw, payload: JSON.parse(raw) };
}
function authorityOwner(name = 'editor') { return within(screen.getByRole('region', { name })); }
async function startAuthority(name = 'editor') {
  const button = await authorityOwner(name).findByRole('button', { name: 'Reauthorize generation' });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
}
function replaceAuthority(view: ReturnType<typeof mountAuthority>, mode: 'same-id' | 'client') {
  const api = mode === 'client' ? new ApiClient(view.transport as typeof fetch) : view.api;
  api.session = { session_id: 's', csrf_token: 'dummy-replaced-authority-csrf', expires_at: 9999999999 };
  mocks.runtime = { ...mocks.runtime, api, session: api.session };
  // Same-ID replacement must fence even before React gets an update.
  if (mode === 'client') view.redraw();
}
async function rejectionProof(payload: { credential_ref?: string; idempotency_key: string }) {
  const { createHash } = await import('node:crypto');
  const fingerprint = createHash('sha256').update(JSON.stringify({ credential_ref: payload.credential_ref ?? null, idempotency_key: payload.idempotency_key })).digest('hex');
  return { schema_version: 1, code: 'renewal_rejected', job_id: blocked.id, idempotency_key: payload.idempotency_key, fingerprint };
}

it('two mounted renewal owners share the frozen lost-ACK request instead of overwriting it', async () => {
  const view = mountAuthority(['editor', 'detail'], async url => url === '/api/model-settings'
    ? authorityResponse(authorityMetadata()) : Promise.reject(new Error('dummy-lost-ack')));
  await startAuthority('editor');
  await authorityOwner('editor').findByRole('alert');
  const first = retainedAuthority();
  const detail = authorityOwner('detail');
  await waitFor(() => expect(detail.getByRole('button', { name: /Retry reauthorization/ })).toBeEnabled());
  expect(view.posts()).toHaveLength(1); // Synchronization itself must never POST.
  fireEvent.click(detail.getByRole('button', { name: /Retry reauthorization/ }));
  await detail.findByRole('alert');
  expect(view.posts()).toHaveLength(2);
  expect(JSON.parse(String(view.posts()[1][1].body))).toEqual(first.payload);
  expect(retainedAuthority().raw).toBe(first.raw);
});

it('ignores legacy session-ID-only metadata for a real client', async () => {
  const fresh = authorityDeferred<Response>();
  const view = mountAuthority(['editor'], async () => fresh.promise);
  act(() => cache.setQueryData(['model-settings', 's'], authorityMetadata()));
  expect(screen.getByRole('button', { name: 'Reauthorize generation' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Reauthorize generation' }));
  expect(view.posts()).toHaveLength(0);
  await act(async () => { fresh.resolve(authorityResponse(authorityMetadata())); });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Reauthorize generation' })).toBeEnabled());
});

it('preserves exact retained bytes during an explicit replay', async () => {
  const payload = { credential_ref: 'a'.repeat(64), idempotency_key: 'retained-exact' };
  const key = `arena:reauthorization:v1:${encodeURIComponent(blocked.id)}`;
  const raw = JSON.stringify(payload, null, 2);
  sessionStorage.setItem(key, raw);
  const view = mountAuthority(['editor'], async url => url === '/api/model-settings'
    ? authorityResponse(authorityMetadata('b'.repeat(64))) : Promise.reject(new Error('dummy-lost-ack')));
  fireEvent.click(screen.getByRole('button', { name: 'Retry reauthorization' }));
  await screen.findByRole('alert');
  expect(view.posts()).toHaveLength(1);
  expect(JSON.parse(String(view.posts()[0][1].body))).toEqual(payload);
  expect(sessionStorage.getItem(key)).toBe(raw);
});

it('a peer replay retires earlier completion even when retained bytes are unchanged', async () => {
  const late = authorityDeferred<Response>();
  let posts = 0;
  const view = mountAuthority(['editor', 'detail'], async url => {
    if (url === '/api/model-settings') return authorityResponse(authorityMetadata());
    if (url.endsWith('/reauthorize')) {
      if (++posts === 1) return late.promise;
      throw new Error('dummy-peer-lost-ack');
    }
    return authorityResponse(blocked);
  });
  await startAuthority('editor');
  const first = retainedAuthority();
  fireEvent.click(await authorityOwner('detail').findByRole('button', { name: 'Retry reauthorization' }));
  await authorityOwner('detail').findByRole('alert');
  await act(async () => { late.resolve(authorityResponse(blocked)); });
  expect(view.posts()).toHaveLength(2);
  expect(view.transport.mock.calls.filter(([url]) => url === '/api/jobs/job%2Factual')).toHaveLength(0);
  expect(view.verified).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(first.key)).toBe(first.raw);
});

it('verified consumption synchronizes mounted owners without a new POST', async () => {
  const view = mountAuthority(['editor', 'detail']);
  await startAuthority('editor');
  await waitFor(() => expect(view.verified).toHaveBeenCalledWith('editor'));
  expect(authorityOwner('editor').getByRole('button', { name: 'Reauthorize generation' })).toBeEnabled();
  expect(authorityOwner('detail').getByRole('button', { name: 'Reauthorize generation' })).toBeEnabled();
  expect(Object.keys(sessionStorage).filter(key => key.startsWith('arena:reauthorization:'))).toHaveLength(0);
  expect(view.posts()).toHaveLength(1);
});

it.each(['malformed', 'replacement', 'removed'] as const)('fails closed when retained storage is %s before a retry click', async mode => {
  const view = mountAuthority(['editor'], async url => url === '/api/model-settings'
    ? authorityResponse(authorityMetadata()) : Promise.reject(new Error('dummy-lost-ack')));
  await startAuthority();
  await screen.findByRole('alert');
  const first = retainedAuthority();
  const replacement = mode === 'malformed' ? '{broken' : JSON.stringify({ idempotency_key: 'replacement-G', credential_ref: 'b'.repeat(64) });
  if (mode === 'removed') sessionStorage.removeItem(first.key);
  else sessionStorage.setItem(first.key, replacement);
  fireEvent.click(screen.getByRole('button', { name: 'Retry reauthorization' }));
  await act(async () => {});
  expect(view.posts()).toHaveLength(1);
  expect(sessionStorage.getItem(first.key)).toBe(mode === 'removed' ? null : replacement);
});

it('does not overwrite storage changed while retry confirmation is open', async () => {
  const view = mountAuthority(['editor'], async url => url === '/api/model-settings'
    ? authorityResponse(authorityMetadata()) : Promise.reject(new Error('dummy-lost-ack')));
  await startAuthority();
  await screen.findByRole('alert');
  const first = retainedAuthority();
  vi.mocked(window.confirm).mockImplementationOnce(() => {
    sessionStorage.setItem(first.key, '{broken');
    return true;
  });
  fireEvent.click(screen.getByRole('button', { name: 'Retry reauthorization' }));
  expect(view.posts()).toHaveLength(1);
  expect(sessionStorage.getItem(first.key)).toBe('{broken');
});

it.each(['post', 'readback'] as const)('retired %s completion cannot remove a replacement retained request with two mounted owners', async phase => {
  const late = authorityDeferred<Response>();
  const view = mountAuthority(['editor', 'detail'], async url => {
    if (url === '/api/model-settings') return authorityResponse(authorityMetadata());
    if (phase === 'post' ? url.endsWith('/reauthorize') : url === '/api/jobs/job%2Factual') return late.promise;
    return authorityResponse(blocked);
  });
  await startAuthority();
  await waitFor(() => expect(view.transport.mock.calls.some(([url]) => url === (phase === 'post'
    ? '/api/editor/generations/job%2Factual/reauthorize' : '/api/jobs/job%2Factual'))).toBe(true));
  const first = retainedAuthority();
  const replacement = JSON.stringify({ idempotency_key: 'replacement-G', credential_ref: 'b'.repeat(64) });
  sessionStorage.setItem(first.key, replacement);
  await act(async () => { late.resolve(authorityResponse(blocked)); });
  expect(sessionStorage.getItem(first.key)).toBe(replacement);
  expect(view.verified).not.toHaveBeenCalled();
});

it.each([
  ['same-id', 'post'], ['client', 'post'], ['same-id', 'readback'], ['client', 'readback'],
] as const)('fences %s replacement during renewal %s', async (mode, phase) => {
  const late = authorityDeferred<Response>();
  const view = mountAuthority(['editor'], async url => {
    if (url === '/api/model-settings') return authorityResponse(authorityMetadata());
    if (phase === 'post' ? url.endsWith('/reauthorize') : url === '/api/jobs/job%2Factual') return late.promise;
    return authorityResponse(blocked);
  });
  await startAuthority();
  await waitFor(() => expect(view.transport.mock.calls.some(([url]) => url === (phase === 'post'
    ? '/api/editor/generations/job%2Factual/reauthorize' : '/api/jobs/job%2Factual'))).toBe(true));
  const first = retainedAuthority();
  replaceAuthority(view, mode);
  const reads = view.transport.mock.calls.filter(([url]) => url === '/api/jobs/job%2Factual').length;
  await act(async () => { late.resolve(authorityResponse(blocked)); });
  expect(view.transport.mock.calls.filter(([url]) => url === '/api/jobs/job%2Factual')).toHaveLength(reads);
  expect(view.verified).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(first.key)).toBe(first.raw);
});

it('fences a same-ID replacement before React renders or the renewal POST starts', async () => {
  const view = mountAuthority();
  const button = await screen.findByRole('button', { name: 'Reauthorize generation' });
  await waitFor(() => expect(button).toBeEnabled());
  replaceAuthority(view, 'same-id');
  fireEvent.click(button);
  expect(view.posts()).toHaveLength(0);
  expect(Object.keys(sessionStorage).filter(key => key.startsWith('arena:reauthorization:'))).toHaveLength(0);
});

it.each(['same-id', 'client'] as const)('withholds %s replacement metadata until its own GET finishes without implicit renewal', async mode => {
  const fresh = authorityDeferred<Response>();
  let reads = 0;
  const view = mountAuthority(['editor'], async url => {
    if (url === '/api/model-settings') return ++reads === 1 ? authorityResponse(authorityMetadata()) : fresh.promise;
    throw new Error('No implicit authority request permitted');
  });
  const button = await screen.findByRole('button', { name: 'Reauthorize generation' });
  await waitFor(() => expect(button).toBeEnabled());
  replaceAuthority(view, mode);
  view.redraw();
  expect(screen.getByRole('button', { name: 'Reauthorize generation' })).toBeDisabled();
  await waitFor(() => expect(reads).toBe(2));
  await act(async () => { fresh.resolve(authorityResponse(authorityMetadata('b'.repeat(64)))); });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Reauthorize generation' })).toBeEnabled());
  expect(view.posts()).toHaveLength(0);
  expect(view.verified).not.toHaveBeenCalled();
});

it('ordinary activity preserves the mounted renewal scope and accepted readback', async () => {
  const late = authorityDeferred<Response>();
  const view = mountAuthority(['editor'], async url => {
    if (url === '/api/model-settings') return authorityResponse(authorityMetadata());
    if (url === '/api/session/activity') return authorityResponse({ session_id: 's', csrf_token: 'dummy-authority-csrf', expires_at: 9999999999 });
    if (url.endsWith('/reauthorize')) return late.promise;
    return authorityResponse(blocked);
  });
  await startAuthority();
  const epoch = view.api.sessionGeneration;
  await act(async () => { mocks.runtime = { ...mocks.runtime, session: await view.api.activity() }; });
  view.redraw();
  expect(view.api.sessionGeneration).toBe(epoch);
  await act(async () => { late.resolve(authorityResponse(blocked)); });
  expect(view.verified).toHaveBeenCalledWith('editor');
  expect(view.posts()).toHaveLength(1);
});

it('two mounted owners adopt the exact corrected A-to-G retention without an implicit POST', async () => {
  let ref = 'a'.repeat(64);
  let first: { idempotency_key: string; credential_ref?: string } | undefined;
  const view = mountAuthority(['editor', 'detail'], async (url, init) => {
    if (url === '/api/model-settings') return authorityResponse(authorityMetadata(ref));
    if (url.includes('/reauthorization-disposition?')) return authorityResponse(await rejectionProof(first!));
    if (url.endsWith('/reauthorize')) {
      first ??= JSON.parse(String(init.body));
      throw new Error('dummy-lost-ack');
    }
    throw new Error('Unexpected correction fixture request');
  });
  await startAuthority('editor');
  await authorityOwner('editor').findByRole('alert');
  const original = retainedAuthority();
  fireEvent.click(await authorityOwner('detail').findByRole('button', { name: 'Check renewal disposition' }));
  const correction = await authorityOwner('detail').findByRole('button', { name: 'Use current credentials' });
  ref = 'b'.repeat(64);
  fireEvent.focus(window);
  await waitFor(() => expect(cache.getQueryCache().getAll().some(q =>
    q.queryKey[0] === 'model-settings' && (q.state.data as { credential_ref?: string })?.credential_ref === ref)).toBe(true));
  fireEvent.click(correction);
  const corrected = retainedAuthority();
  expect(corrected.payload.idempotency_key).not.toBe(original.payload.idempotency_key);
  expect(corrected.payload.credential_ref).toBe(ref);
  expect(view.posts()).toHaveLength(1);
  fireEvent.click(await authorityOwner('editor').findByRole('button', { name: 'Retry reauthorization' }));
  await waitFor(() => expect(view.posts()).toHaveLength(2));
  expect(JSON.parse(String(view.posts()[1][1].body))).toEqual(corrected.payload);
  expect(sessionStorage.getItem(corrected.key)).toBe(corrected.raw);
});

it('blocks disposition reads after same-ID replacement before React renders', async () => {
  const view = mountAuthority(['editor'], async url => url === '/api/model-settings'
    ? authorityResponse(authorityMetadata()) : Promise.reject(new Error('dummy-lost-ack')));
  await startAuthority();
  await screen.findByRole('alert');
  replaceAuthority(view, 'same-id');
  fireEvent.click(screen.getByRole('button', { name: 'Check renewal disposition' }));
  await act(async () => {});
  expect(view.transport.mock.calls.filter(([url]) => url.includes('/reauthorization-disposition?'))).toHaveLength(0);
});

it.each(['same-id', 'client'] as const)('drops late disposition proof after %s replacement', async mode => {
  const late = authorityDeferred<Response>();
  const view = mountAuthority(['editor'], async url => {
    if (url === '/api/model-settings') return authorityResponse(authorityMetadata());
    if (url.includes('/reauthorization-disposition?')) return late.promise;
    throw new Error('dummy-lost-ack');
  });
  await startAuthority();
  await screen.findByRole('alert');
  const first = retainedAuthority();
  fireEvent.click(screen.getByRole('button', { name: 'Check renewal disposition' }));
  await waitFor(() => expect(view.transport.mock.calls.some(([url]) => url.includes('/reauthorization-disposition?'))).toBe(true));
  replaceAuthority(view, mode);
  await act(async () => { late.resolve(authorityResponse(await rejectionProof(first.payload))); });
  expect(screen.queryByRole('button', { name: 'Use current credentials' })).not.toBeInTheDocument();
  expect(sessionStorage.getItem(first.key)).toBe(first.raw);
  expect(view.posts()).toHaveLength(1);
});

it.each(['same-id', 'client', 'retention', 'confirmation'] as const)('does not correct with %s retired authority', async mode => {
  const view = mountAuthority(['editor'], async (url, init) => {
    if (url === '/api/model-settings') return authorityResponse(authorityMetadata());
    if (url.endsWith('/reauthorize')) return authorityResponse({ detail: await rejectionProof(JSON.parse(String(init.body))) }, 409);
    throw new Error('Unexpected correction fixture request');
  });
  await startAuthority();
  const correction = await screen.findByRole('button', { name: 'Use current credentials' });
  const first = retainedAuthority();
  const replaced = JSON.stringify({ idempotency_key: 'replacement-G', credential_ref: 'b'.repeat(64) });
  if (mode === 'same-id' || mode === 'client') replaceAuthority(view, mode);
  if (mode === 'retention') sessionStorage.setItem(first.key, replaced);
  if (mode === 'confirmation') vi.mocked(window.confirm).mockImplementationOnce(() => {
    replaceAuthority(view, 'same-id');
    return true;
  });
  fireEvent.click(correction);
  await act(async () => {});
  expect(sessionStorage.getItem(first.key)).toBe(mode === 'retention' ? replaced : first.raw);
  expect(view.posts()).toHaveLength(1);
});
