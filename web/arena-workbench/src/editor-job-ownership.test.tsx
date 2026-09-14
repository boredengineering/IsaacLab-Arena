import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, it, vi } from 'vitest';
import { EditorJobProgress, useEditorJob } from './editor-jobs';
import { ApiClient } from './api';
import type { Job } from './contracts';
import { workspaceKey } from './cache';
const mocks = vi.hoisted(() => ({ runtime: {} as any }));
vi.mock('./runtime', () => ({ useRuntime: () => mocks.runtime }));
vi.mock('@tanstack/react-router', () => ({ Link: ({ children }: any) => <a>{children}</a> }));
const key = 'arena:editor:generate:v1';
const blocked: Job = { id: 'blocked1', workspace_id: 'default', kind: 'generate', status: 'blocked_authorization', stage: 'blocked', inputs: { operation: 'new' }, created_at: 0, updated_at: 0, result: null, error: null, created_by_session_id: 's1' };
let cache: QueryClient;
let controller: ReturnType<typeof useEditorJob>;
function Harness() { controller = useEditorJob('generate'); return <><output>{controller.busy ? 'busy' : 'idle'}</output><button onClick={() => controller.submit.mutate({ prompt: 'frozen' })}>Submit</button><button onClick={() => controller.cancel.mutate('blocked1')}>Cancel test</button><EditorJobProgress controller={controller} /></>; }
function mount() { return render(<QueryClientProvider client={cache}><Harness /></QueryClientProvider>); }
beforeEach(() => {
  sessionStorage.clear(); cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const api = new ApiClient(); api.session = { session_id: 's1', csrf_token: 'c', expires_at: 9999999999 };
  vi.spyOn(api, 'activity').mockResolvedValue(api.session);
  vi.spyOn(api, 'mutate').mockResolvedValue({ ...blocked, status: 'queued' });
  vi.spyOn(api, 'get').mockResolvedValue(blocked);
  mocks.runtime = { api, session: api.session, refresh: vi.fn(async () => {}) };
  cache.setQueryData(['model-settings', 's1'], { configured: true, source: 'server' });
});
it.each(['Submit', 'Cancel test'])('does not dispatch %s across delayed activity/session replacement', async name => {
  let finish!: () => void;
  mocks.runtime.api.activity.mockImplementation(() => new Promise<void>(resolve => { finish = resolve; }));
  mount(); fireEvent.click(screen.getByText(name));
  await waitFor(() => expect(mocks.runtime.api.activity).toHaveBeenCalled());
  mocks.runtime.api.session = { ...mocks.runtime.session, session_id: 's2' };
  await act(async () => { finish(); });
  expect(mocks.runtime.api.mutate).not.toHaveBeenCalled();
});
it.each(['unmount', 'replacement'])('late acceptance after %s cannot overwrite storage or refresh', async mode => {
  let finish!: (value: unknown) => void;
  mocks.runtime.api.mutate.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = mount(); fireEvent.click(screen.getByText('Submit'));
  await waitFor(() => expect(mocks.runtime.api.mutate).toHaveBeenCalled());
  const frozen = sessionStorage.getItem(key);
  if (mode === 'unmount') view.unmount(); else mocks.runtime.api.session = { ...mocks.runtime.session, session_id: 's2' };
  await act(async () => { finish({ ...blocked, status: 'queued' }); });
  expect(sessionStorage.getItem(key)).toBe(frozen);
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
});
it.each([false, true, 'accepted'])('offers explicit selection for multiple unretained blockers (retained=%s)', async retained => {
  if (retained) sessionStorage.setItem(key, JSON.stringify({ payload: { idempotency_key: 'unresolved', prompt: 'keep' } }));
  if (retained === 'accepted') sessionStorage.setItem(key, JSON.stringify({ payload: { idempotency_key: 'old' }, job: { ...blocked, id: 'old', status: 'succeeded' } }));
  const original = sessionStorage.getItem(key);
  cache.setQueryData(workspaceKey, { jobs: [blocked, { ...blocked, id: 'blocked2' }] });
  mocks.runtime.api.get.mockImplementation(async (url: string) => ({ ...blocked, id: url.endsWith('/old') ? 'old' : 'blocked1', status: 'cancelled' }));
  mocks.runtime.refresh.mockImplementation(async () => { cache.setQueryData(workspaceKey, { jobs: [] }); });
  mount(); expect(screen.getByText('busy')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Reauthorize generation' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Review blocked generation blocked2' }));
  expect(screen.getByRole('button', { name: 'Reauthorize generation' })).toBeInTheDocument();
  expect(sessionStorage.getItem(key)).toBe(original);
  fireEvent.click(screen.getByRole('button', { name: 'Review blocked generation blocked1' }));
  fireEvent.click(screen.getByRole('button', { name: 'Cancel generation' }));
  await screen.findByText('idle');
  expect(mocks.runtime.api.mutate).toHaveBeenCalledWith('/jobs/blocked1/cancel', {});
  expect(sessionStorage.getItem(key)).toBe(original);
});
it('freezes inputs at click before the mutation starts and retains ambiguous retry unchanged', async () => {
  mocks.runtime.api.mutate.mockRejectedValueOnce(new Error('lost'));
  mount();
  const inputs = { prompt: 'original', nested: { mode: 'new' } };
  act(() => { controller.submit.mutate(inputs); inputs.prompt = 'edited'; inputs.nested.mode = 'refine'; });
  await screen.findByText('lost');
  const first = mocks.runtime.api.mutate.mock.calls[0][1];
  expect(first).toMatchObject({ prompt: 'original', nested: { mode: 'new' } });
  fireEvent.click(screen.getByText('Submit'));
  await waitFor(() => expect(mocks.runtime.refresh).toHaveBeenCalledOnce());
  expect(mocks.runtime.api.mutate.mock.calls[1][1]).toEqual(first);
  expect(JSON.parse(sessionStorage.getItem(key)!)).toMatchObject({ payload: first, job: { id: 'blocked1' } });
});
it('drops a late cancellation error after session replacement', async () => {
  let fail!: (error: Error) => void;
  mocks.runtime.api.get.mockImplementation(() => new Promise((_resolve, reject) => { fail = reject; }));
  mount(); fireEvent.click(screen.getByText('Cancel test'));
  await waitFor(() => expect(mocks.runtime.api.get).toHaveBeenCalled());
  mocks.runtime.api.session = { ...mocks.runtime.session, session_id: 's2' };
  await act(async () => { fail(new Error('retired')); });
  await waitFor(() => expect(controller.cancel.isPending).toBe(false));
  expect(controller.cancel.error).toBeNull();
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
});
it.each(['submit', 'cancel'] as const)('captures %s session ownership at click, not when mutationFn starts', async operation => {
  mount();
  act(() => {
    if (operation === 'submit') controller.submit.mutate({ prompt: 'original' });
    else controller.cancel.mutate('blocked1');
    mocks.runtime.api.session = { ...mocks.runtime.session, session_id: 's2' };
  });
  await act(async () => {});
  expect(mocks.runtime.api.activity).not.toHaveBeenCalled();
  expect(mocks.runtime.api.mutate).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(key)).toBeNull();
});
it('does not publish late cancellation readback after unmount', async () => {
  let finish!: (value: unknown) => void;
  mocks.runtime.api.get.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = mount(); fireEvent.click(screen.getByText('Cancel test'));
  await waitFor(() => expect(mocks.runtime.api.get).toHaveBeenCalled());
  view.unmount(); sessionStorage.setItem(key, 'new runtime storage');
  await act(async () => { finish({ ...blocked, status: 'cancelled' }); });
  expect(mocks.runtime.refresh).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(key)).toBe('new runtime storage');
});
