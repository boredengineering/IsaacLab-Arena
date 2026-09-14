import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, it, vi } from 'vitest';
import { EditorJobProgress, useEditorJob } from './editor-jobs';
import { GenerationReauthorization } from './generation-reauthorization';
import type { Job } from './contracts';
import { workspaceKey } from './cache';

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
  cache.setQueryData(['model-settings', 's'], { configured: true, source, credential_ref: ref, expires_at: 9999999999 });
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
  cache.setQueryData(['model-settings', 's'], (old: any) => ({ ...old, expires_at: 1 }));
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
