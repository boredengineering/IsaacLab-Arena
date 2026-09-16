import { createHash, webcrypto } from 'node:crypto';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { RuntimeProvider } from './runtime';
import { EditorRevisionSave, type EditorRevisionSaveProps } from './editor-revision-save';
import type { EditorSaveRequest } from './editor-revision-contracts';
const KEY = 'arena:editor-save:v1';
const hash = (text: string) => createHash('sha256').update(text).digest('hex');
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const session = { session_id: 'operator', csrf_token: 'never-retain-csrf', expires_at: 9999999999 };
function receipt(request: EditorSaveRequest, id = 'b'.repeat(32)) {
  return { schema_version: 1, idempotency_key: request.idempotency_key, state: 'committed',
    request_sha256: hash(JSON.stringify(['editor-save/v1', request.yaml_text, request.document_id ?? null, request.expected_source_hash ?? null])),
    revision: { revision_id: id, yaml_text: request.yaml_text, source_hash: hash(request.yaml_text), canonical_hash: 'c'.repeat(64),
      download_url: `/api/editor/revisions/${id}/download`, open_source: { kind: 'editor_revision', id: `editor-revision:${id}` } } };
}
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function server(handler: (url: string, init: RequestInit) => Promise<Response>, supported = true) {
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (url === '/api/sessions') return response(session);
    if (url === '/api/health') return response({ status: 'ok', capabilities: { durable_editor_save: supported } });
    if (url === '/api/workspaces/default') return response({ id: 'default', name: 'test', event_cursor: 0, jobs: [] });
    return handler(url, init);
  });
  return { api: new ApiClient(fetcher as typeof fetch), fetcher,
    saves: () => fetcher.mock.calls.filter(([url]) => url.startsWith('/api/editor/')) };
}
function mount(api: ApiClient, overrides: Partial<EditorRevisionSaveProps> = {}) {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const makePort = () => ({ onmessage: null, onmessageerror: null, postMessage() {}, start() {}, close() {} });
  let props = { enabled: true, draft: 'name: café\n', documentId: 'view:old', bindingKey: 'draft-A', ...overrides };
  const tree = () => <QueryClientProvider client={cache}><RuntimeProvider api={api} makePort={makePort}><EditorRevisionSave {...props} /></RuntimeProvider></QueryClientProvider>;
  const view = render(tree());
  return { ...view, cache, update: (next: Partial<EditorRevisionSaveProps>, nextApi = api) => { api = nextApi; props = { ...props, ...next }; view.rerender(tree()); } };
}
// Invoke the actual retained React handler, even after its DOM control retires.
function retainedClick(button: HTMLElement): () => void {
  const key = Object.keys(button).find(name => name.startsWith('__reactProps$'))!;
  return (button as unknown as Record<string, { onClick: () => void }>)[key].onClick;
}
async function ready() { await waitFor(() => expect(screen.getByRole('button', { name: 'Save durable revision' })).toBeEnabled()); }
beforeEach(() => { sessionStorage.clear(); Object.defineProperty(globalThis, 'crypto', { configurable: true, value: webcrypto }); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it.each([{ bindingKey: 'x'.repeat(2049) }, { expectedSourceHash: 'not-a-hash' }, { documentId: '' }])('never writes a fresh request that recovery would reject: %j', async props => {
  const s = server(async () => { throw new Error('must not POST'); }); mount(s.api, props); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/Conflict|Storage/i));
  expect(s.saves()).toHaveLength(0); expect(sessionStorage.getItem(KEY)).toBeNull();
});
it('admits explicit retained receipt GET and Open independently of current draft write eligibility', async () => {
  const request = { idempotency_key: 'read-only', yaml_text: 'name: café\n', document_id: 'view:old' };
  const raw = JSON.stringify({ schema_version: 1, binding: 'draft-A', request, request_sha256: receipt(request).request_sha256 });
  sessionStorage.setItem(KEY, raw);
  const s = server(async () => response(receipt(request)));
  const onSaved = vi.fn(), onOpen = vi.fn();
  mount(s.api, { enabled: false, readEnabled: true, onSaved, onOpen });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  expect(screen.getByRole('button', { name: 'Save durable revision' })).toBeDisabled();
  const retry = screen.getByRole('button', { name: 'Retry exact save' });
  expect(retry).toBeDisabled(); act(retainedClick(retry));
  expect(s.saves()).toHaveLength(0); expect(sessionStorage.getItem(KEY)).toBe(raw);
  fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledExactlyOnceWith(receipt(request).revision));
  expect(onOpen).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Open saved revision' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Open saved revision' }));
  expect(onOpen).toHaveBeenCalledExactlyOnceWith(receipt(request).revision.open_source);
  expect(s.saves().map(([url, init]) => [url, init.method])).toEqual([['/api/editor/save-requests/read-only', 'GET']]);
  expect(sessionStorage.getItem(KEY)).toBeNull();
});
it('withholds all save controls when read admission is retired even if write eligibility remains true', async () => {
  const s = server(async () => { throw new Error('must not dispatch'); });
  mount(s.api, { enabled: true, readEnabled: false });
  await waitFor(() => expect(s.api.session).not.toBeNull());
  const save = screen.getByRole('button', { name: 'Save durable revision' });
  expect(save).toBeDisabled(); act(retainedClick(save));
  await act(async () => { await new Promise(done => setTimeout(done, 20)); });
  expect(s.saves()).toHaveLength(0); expect(sessionStorage.getItem(KEY)).toBeNull();
});
it.each(['read ABA', 'write ABA', 'binding ABA', 'generation', 'client'] as const)('rejects retained GET handlers after %s without adopting replacement authority', async change => {
  const request = { idempotency_key: 'read-only', yaml_text: 'name: café\n', document_id: 'view:old' };
  const raw = JSON.stringify({ schema_version: 1, binding: 'draft-A', request, request_sha256: receipt(request).request_sha256 });
  sessionStorage.setItem(KEY, raw);
  const s = server(async () => response(receipt(request))), replacement = server(async () => response(receipt(request)));
  const onSaved = vi.fn(); const view = mount(s.api, { enabled: false, readEnabled: true, onSaved });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  const check = retainedClick(screen.getByRole('button', { name: 'Check save status' }));
  if (change === 'read ABA') { view.update({ readEnabled: false }); view.update({ readEnabled: true }); }
  if (change === 'write ABA') { view.update({ enabled: true }); view.update({ enabled: false }); }
  if (change === 'binding ABA') { view.update({ bindingKey: 'B' }); view.update({ bindingKey: 'draft-A' }); }
  if (change === 'generation') s.api.session = { ...session };
  if (change === 'client') view.update({}, replacement.api);
  act(check);
  await act(async () => { await new Promise(done => setTimeout(done, 20)); });
  expect(s.saves()).toHaveLength(0); expect(replacement.saves()).toHaveLength(0);
  expect(sessionStorage.getItem(KEY)).toBe(raw); expect(onSaved).not.toHaveBeenCalled();
});
it.each(['read', 'write'] as const)('releases a retired pending GET busy lock after %s eligibility ABA and requires fresh explicit readback', async admission => {
  const request = { idempotency_key: 'read-only', yaml_text: 'name: café\n', document_id: 'view:old' };
  const raw = JSON.stringify({ schema_version: 1, binding: 'draft-A', request, request_sha256: receipt(request).request_sha256 });
  sessionStorage.setItem(KEY, raw);
  const delayed = deferred<Response>(); let calls = 0;
  const s = server(async () => ++calls === 1 ? delayed.promise : response(receipt(request)));
  const onSaved = vi.fn(); const view = mount(s.api, { enabled: false, readEnabled: true, onSaved });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  await waitFor(() => expect(s.saves()).toHaveLength(1));
  if (admission === 'read') { view.update({ readEnabled: false }); view.update({ readEnabled: true }); }
  else { view.update({ enabled: true }); view.update({ enabled: false }); }
  expect(screen.getByRole('button', { name: 'Check save status' })).toBeDisabled();
  await act(async () => { delayed.resolve(response(receipt(request))); });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  expect(sessionStorage.getItem(KEY)).toBe(raw); expect(onSaved).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: 'Open saved revision' })).not.toBeInTheDocument();
  expect(s.saves()).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledExactlyOnceWith(receipt(request).revision));
  expect(s.saves().map(([, init]) => init.method)).toEqual(['GET', 'GET']);
});
it.each(['read', 'write'] as const)('retires a retained verified Open on %s admission ABA', async admission => {
  const request = { idempotency_key: 'read-only', yaml_text: 'name: café\n', document_id: 'view:old' };
  sessionStorage.setItem(KEY, JSON.stringify({ schema_version: 1, binding: 'draft-A', request, request_sha256: receipt(request).request_sha256 }));
  const s = server(async () => response(receipt(request))), onOpen = vi.fn();
  const view = mount(s.api, { enabled: false, readEnabled: true, onOpen });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  const open = retainedClick(await screen.findByRole('button', { name: 'Open saved revision' }));
  if (admission === 'read') { view.update({ readEnabled: false }); view.update({ readEnabled: true }); }
  else { view.update({ enabled: true }); view.update({ enabled: false }); }
  act(open); expect(onOpen).not.toHaveBeenCalled(); expect(s.saves()).toHaveLength(1);
});
it('does not dispatch when disabled while the frozen click is hashing', async () => {
  const s = server(async () => { throw new Error('must not POST'); }); const view = mount(s.api); await ready();
  act(() => { fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' })); view.update({ enabled: false }); });
  await act(async () => { await new Promise(done => setTimeout(done, 20)); });
  expect(s.saves()).toHaveLength(0); expect(sessionStorage.getItem(KEY)).toBeNull();
});
it('keeps exact ACK GET-only after successful storage write whose readback failed', async () => {
  let frozen!: EditorSaveRequest, failNext = false;
  const originalSet = Storage.prototype.setItem, originalGet = Storage.prototype.getItem;
  const s = server(async (_, init) => {
    if (init.method === 'POST') {
      frozen = JSON.parse(String(init.body));
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) { originalSet.call(this, key, value); if (key === KEY) failNext = true; });
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, key) { if (key === KEY && failNext) { failNext = false; throw new DOMException('blocked', 'SecurityError'); } return originalGet.call(this, key); });
      return response(receipt(frozen));
    }
    return response({ detail: 'unavailable' }, 503);
  });
  mount(s.api); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/Known accepted.*storage/i));
  expect(JSON.parse(sessionStorage.getItem(KEY)!).accepted).toEqual(receipt(frozen));
  expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Retry exact save' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  await waitFor(() => expect(s.saves()).toHaveLength(3));
});
it.each(['remove', 'verification read'] as const)('keeps recovered GET acceptance GET-only after cleanup %s SecurityError even when storage works again', async fault => {
  let frozen!: EditorSaveRequest;
  const firstServer = server(async (_, init) => { frozen = JSON.parse(String(init.body)); throw new Error('lost ACK'); });
  const first = mount(firstServer.api); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Unknown'));
  const retained = sessionStorage.getItem(KEY); first.unmount();
  const recovery = server(async () => response(receipt(frozen)));
  const onSaved = vi.fn(); mount(recovery.api, { onSaved });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  expect(recovery.saves()).toHaveLength(0);
  const retry = retainedClick(screen.getByRole('button', { name: 'Retry exact save' }));
  const originalRemove = Storage.prototype.removeItem;
  const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(function (this: Storage, key) {
    if (fault === 'remove') throw new DOMException('blocked', 'SecurityError');
    originalRemove.call(this, key);
    vi.spyOn(Storage.prototype, 'getItem').mockImplementationOnce(() => { throw new DOMException('blocked', 'SecurityError'); });
  });
  fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  expect(screen.getByRole('status')).toHaveTextContent(/Known accepted.*GET-only/i);
  expect(sessionStorage.getItem(KEY)).toBe(fault === 'remove' ? retained : null);
  remove.mockRestore();
  act(retry);
  fireEvent.click(screen.getByRole('button', { name: 'Retry exact save' }));
  expect(screen.getByRole('button', { name: 'Retry exact save' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  await waitFor(() => expect(recovery.saves()).toHaveLength(2));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  expect(recovery.saves().map(([url, init]) => [url, init.method])).toEqual([
    [`/api/editor/save-requests/${frozen.idempotency_key}`, 'GET'],
    [`/api/editor/save-requests/${frozen.idempotency_key}`, 'GET'],
  ]);
  expect(sessionStorage.getItem(KEY)).toBe(fault === 'remove' ? retained : null); expect(onSaved).not.toHaveBeenCalled();
});
it.each(['before removal', 'during removal', 'after cleanup failure'] as const)('preserves exact sibling replacement %s during GET-only recovery', async phase => {
  const request = { idempotency_key: 'F', yaml_text: 'name: café\n', document_id: 'view:old' };
  const peer = { ...request, idempotency_key: 'G', yaml_text: 'peer draft' };
  const record = (value: EditorSaveRequest) => JSON.stringify({ schema_version: 1, binding: 'draft-A', request: value, request_sha256: receipt(value).request_sha256 });
  const sibling = record(peer); sessionStorage.setItem(KEY, record(request));
  const originalGet = Storage.prototype.getItem, originalRemove = Storage.prototype.removeItem;
  const s = server(async () => {
    if (phase === 'before removal') vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, key) {
      if (key === KEY) sessionStorage.setItem(KEY, sibling);
      return originalGet.call(this, key);
    });
    return response(receipt(request));
  });
  const onSaved = vi.fn(); mount(s.api, { onSaved });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(function (this: Storage, key) {
    if (phase === 'after cleanup failure') throw new DOMException('blocked', 'SecurityError');
    originalRemove.call(this, key); sessionStorage.setItem(KEY, sibling);
  });
  fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  if (phase === 'after cleanup failure') {
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/Known accepted.*GET-only/i));
    remove.mockRestore(); sessionStorage.setItem(KEY, sibling);
    fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  }
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Conflict'));
  if (phase === 'before removal') expect(remove).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(KEY)).toBe(sibling); expect(onSaved).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Retry exact save' }));
  expect(s.saves().map(([, init]) => init.method)).toEqual(['GET']);
});
it('treats unreadable successful ACK as a conflict, never as fresh permission', async () => {
  const s = server(async () => new Response('not JSON', { status: 200 }));
  mount(s.api); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Conflict'));
  expect(s.saves()).toHaveLength(1); expect(sessionStorage.getItem(KEY)).not.toBeNull();
  expect(screen.getByRole('button', { name: 'Retry exact save' })).toBeDisabled();
});
it('accepts an inclusive 256KiB full ACK record and recovers it after failed readback without POST', async () => {
  const key = '11111111-1111-4111-8111-111111111111'; vi.spyOn(crypto, 'randomUUID').mockReturnValue(key);
  const base = { idempotency_key: key, yaml_text: '', document_id: 'view:old' };
  let binding = 'draft-A';
  const record = (request: EditorSaveRequest) => ({ schema_version: 1, binding, request, request_sha256: receipt(request).request_sha256, accepted: receipt(request) });
  const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;
  if ((262144 - bytes(record(base))) % 2) binding += 'x';
  const draft = 'x'.repeat((262144 - bytes(record(base))) / 2);
  let frozen!: EditorSaveRequest;
  const s = server(async (_, init) => {
    if (init.method === 'POST') { frozen = JSON.parse(String(init.body)); return response(receipt(frozen)); }
    return response({ detail: 'unavailable' }, 503);
  });
  const first = mount(s.api, { bindingKey: binding, draft }); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Known accepted — readback unavailable'));
  expect(new TextEncoder().encode(sessionStorage.getItem(KEY)!).length).toBe(262144); first.unmount();
  const b = server(async (_, init) => { expect(init.method).toBe('GET'); return response(receipt(frozen)); });
  mount(b.api, { bindingKey: binding, draft }); await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  expect(b.saves()).toHaveLength(0); expect(screen.getByRole('button', { name: 'Retry exact save' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved'));
});
it('releases the busy UI after retired settlement even when replacement rendered before it', async () => {
  const delayed = deferred<Response>(); let frozen!: EditorSaveRequest;
  const s = server(async (_, init) => { frozen = JSON.parse(String(init.body)); return delayed.promise; });
  const view = mount(s.api); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(s.saves()).toHaveLength(1));
  s.api.session = { ...session }; view.update({});
  await act(async () => { delayed.resolve(response(receipt(frozen))); });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
});
it.each(['null ACK', 'changed retained bytes'] as const)('rejects %s before replay after remount', async fault => {
  const request = { idempotency_key: 'retained', yaml_text: 'name: café\n', document_id: 'view:old' };
  const raw = JSON.stringify({ schema_version: 1, binding: 'draft-A', request,
    request_sha256: fault === 'changed retained bytes' ? '0'.repeat(64) : receipt(request).request_sha256,
    ...(fault === 'null ACK' ? { accepted: null } : {}) });
  sessionStorage.setItem(KEY, raw); const s = server(async () => { throw new Error('must not POST'); });
  mount(s.api); await waitFor(() => expect(s.api.session).not.toBeNull());
  const retry = screen.queryByRole('button', { name: 'Retry exact save' }); if (retry) fireEvent.click(retry);
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Conflict'));
  expect(s.saves()).toHaveLength(0); expect(sessionStorage.getItem(KEY)).toBe(raw);
});
it('allows a new explicit save only after the verified frozen draft changes', async () => {
  let frozen!: EditorSaveRequest;
  const s = server(async (_, init) => { if (init.method === 'POST') frozen = JSON.parse(String(init.body)); return response(receipt(frozen)); });
  const view = mount(s.api); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved'));
  const firstKey = frozen.idempotency_key;
  expect(screen.getByRole('button', { name: 'Save durable revision' })).toBeDisabled();
  view.update({ draft: 'new draft' }); await ready();
  expect(s.saves()).toHaveLength(2); fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(s.saves()).toHaveLength(4));
  expect(frozen.yaml_text).toBe('new draft'); expect(frozen.idempotency_key).not.toBe(firstKey);
});
it('legacy oversized eventual ACK is GET-only and never replaces the retained bytes', async () => {
  const request = { idempotency_key: 'legacy', yaml_text: 'x'.repeat(150000), document_id: 'view:old' };
  const raw = JSON.stringify({ schema_version: 1, binding: 'draft-A', request, request_sha256: receipt(request).request_sha256 });
  sessionStorage.setItem(KEY, raw);
  const s = server(async () => response({ detail: 'unknown' }, 404));
  mount(s.api, { draft: request.yaml_text });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Retry exact save' }));
  await act(async () => {});
  expect(s.saves()).toHaveLength(0); expect(sessionStorage.getItem(KEY)).toBe(raw);
  expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled();
});
it('preflights the full maximum checked ACK retention before any POST, including JSON escape expansion', async () => {
  const s = server(async () => { throw new Error('must not post'); });
  mount(s.api, { draft: '\\t'.repeat(50000) }); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/Storage/i));
  expect(s.saves()).toHaveLength(0); expect(sessionStorage.getItem(KEY)).toBeNull();
});
it.each(['POST', 'GET'] as const)('retires late %s settlement on same-ID generation replacement without touching pending evidence', async phase => {
  const delayed = deferred<Response>(); let frozen!: EditorSaveRequest;
  const s = server(async (_, init) => {
    if (init.method === 'POST') { frozen = JSON.parse(String(init.body)); return phase === 'POST' ? delayed.promise : response(receipt(frozen)); }
    return delayed.promise;
  });
  const onSaved = vi.fn(); const view = mount(s.api, { onSaved }); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(s.saves()).toHaveLength(phase === 'POST' ? 1 : 2));
  const baseline = sessionStorage.getItem(KEY); s.api.session = { ...session };
  await act(async () => { delayed.resolve(response(receipt(frozen))); });
  expect(sessionStorage.getItem(KEY)).toBe(baseline); expect(onSaved).not.toHaveBeenCalled();
  view.update({}); expect(screen.getByRole('status')).not.toHaveTextContent(/^Saved$/);
});
it.each(['replace', 'remove'] as const)('uses current onOpen after callback %s even through a retained handler', async change => {
  let frozen!: EditorSaveRequest;
  const s = server(async (_, init) => { if (init.method === 'POST') frozen = JSON.parse(String(init.body)); return response(receipt(frozen)); });
  const oldCallback = vi.fn(), latestCallback = vi.fn();
  const view = mount(s.api, { onOpen: oldCallback }); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved'));
  const open = retainedClick(screen.getByRole('button', { name: 'Open saved revision' }));
  view.update({ onOpen: change === 'replace' ? latestCallback : undefined });
  act(open);
  expect(oldCallback).not.toHaveBeenCalled();
  if (change === 'replace') expect(latestCallback).toHaveBeenCalledExactlyOnceWith(receipt(frozen).revision.open_source);
  else expect(latestCallback).not.toHaveBeenCalled();
  expect(s.saves()).toHaveLength(2);
});
it.each(['binding', 'client', 'generation', 'unmount'] as const)('rejects retained onOpen after %s retirement instead of delivering to either callback', async change => {
  let frozen!: EditorSaveRequest;
  const s = server(async (_, init) => { if (init.method === 'POST') frozen = JSON.parse(String(init.body)); return response(receipt(frozen)); });
  const replacement = server(async () => { throw new Error('must not dispatch'); });
  const oldCallback = vi.fn(), latestCallback = vi.fn();
  const view = mount(s.api, { onOpen: oldCallback }); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved'));
  const open = retainedClick(screen.getByRole('button', { name: 'Open saved revision' }));
  if (change === 'binding') view.update({ bindingKey: 'draft-B', onOpen: latestCallback });
  if (change === 'client') {
    view.update({ onOpen: latestCallback }, replacement.api);
    await waitFor(() => expect(replacement.api.session).not.toBeNull());
    expect(replacement.api.sessionGeneration).toBe(s.api.sessionGeneration);
  }
  if (change === 'generation') { view.update({ onOpen: latestCallback }); s.api.session = { ...session }; }
  if (change === 'unmount') view.unmount();
  act(open);
  expect(oldCallback).not.toHaveBeenCalled(); expect(latestCallback).not.toHaveBeenCalled();
  expect(s.saves()).toHaveLength(2); expect(replacement.saves()).toHaveLength(0);
});
it.each(['binding', 'client', 'unmount'] as const)('drops late GET callback after %s retirement without clearing evidence', async change => {
  let frozen!: EditorSaveRequest; const get = deferred<Response>();
  const s = server(async (_, init) => {
    if (init.method === 'POST') { frozen = JSON.parse(String(init.body)); return response(receipt(frozen)); }
    return get.promise;
  });
  const replacement = server(async () => { throw new Error('must not dispatch'); });
  const oldCallback = vi.fn(), latestCallback = vi.fn();
  const view = mount(s.api, { onSaved: oldCallback }); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(s.saves()).toHaveLength(2));
  const baseline = sessionStorage.getItem(KEY);
  if (change === 'binding') view.update({ bindingKey: 'draft-B', onSaved: latestCallback });
  if (change === 'client') {
    view.update({ onSaved: latestCallback }, replacement.api);
    await waitFor(() => expect(replacement.api.session).not.toBeNull());
    expect(replacement.api.sessionGeneration).toBe(s.api.sessionGeneration);
  }
  if (change === 'unmount') view.unmount();
  await act(async () => { get.resolve(response(receipt(frozen))); });
  if (change !== 'unmount') await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  expect(sessionStorage.getItem(KEY)).toBe(baseline);
  expect(oldCallback).not.toHaveBeenCalled(); expect(latestCallback).not.toHaveBeenCalled();
  expect(s.saves()).toHaveLength(2); expect(replacement.saves()).toHaveLength(0);
});
it('does not expose a saved revision from retired render ownership', async () => {
  let frozen!: EditorSaveRequest;
  const s = server(async (_, init) => { if (init.method === 'POST') frozen = JSON.parse(String(init.body)); return response(receipt(frozen)); });
  const onOpen = vi.fn(); const view = mount(s.api, { onOpen }); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved'));
  s.api.session = { ...session }; view.update({});
  expect(screen.queryByRole('button', { name: 'Open saved revision' })).toBeNull();
  expect(screen.getByRole('status')).not.toHaveTextContent(/^Saved$/); expect(onOpen).not.toHaveBeenCalled();
});
it.each(['retry', 'completion'] as const)('fences stale sibling F %s after another control completes F and begins G', async action => {
  let frozen!: EditorSaveRequest; const delayed = deferred<Response>();
  const a = server(async (_, init) => {
    if (init.method === 'POST') { frozen = JSON.parse(String(init.body)); throw new Error('lost'); }
    return delayed.promise;
  });
  const onSaved = vi.fn(); const first = mount(a.api, { onSaved }); await ready();
  fireEvent.click(first.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(first.getByRole('status')).toHaveTextContent('Unknown'));
  if (action === 'completion') fireEvent.click(first.getByRole('button', { name: 'Check save status' }));
  const b = server(async () => response(receipt(frozen))); const second = mount(b.api);
  await waitFor(() => expect(second.container.querySelector('button:nth-of-type(2)')).toBeEnabled());
  fireEvent.click(second.container.querySelector('button:nth-of-type(2)')!);
  await waitFor(() => expect(sessionStorage.getItem(KEY)).toBeNull()); second.unmount();
  const c = server(async () => { throw new Error('lost G'); }); const third = mount(c.api, { draft: 'G' });
  await waitFor(() => expect(third.container.querySelector('button')).toBeEnabled()); fireEvent.click(third.container.querySelector('button')!);
  await waitFor(() => expect(c.saves()).toHaveLength(1)); const retainedG = sessionStorage.getItem(KEY);
  if (action === 'completion') await act(async () => { delayed.resolve(response(receipt(frozen))); });
  else fireEvent.click(first.container.querySelector('button:nth-of-type(3)')!);
  await waitFor(() => expect(first.container.querySelector('[role=status]')).toHaveTextContent('Conflict'));
  expect(sessionStorage.getItem(KEY)).toBe(retainedG); expect(onSaved).not.toHaveBeenCalled();
  expect(a.saves()).toHaveLength(action === 'completion' ? 2 : 1);
});
it.each(['quota', 'lost', 'read-blocked'] as const)('keeps checked ACK in memory and GET-only when storage becomes %s', async fault => {
  let frozen!: EditorSaveRequest, reads = 0;
  const s = server(async (_, init) => {
    if (init.method === 'POST') {
      frozen = JSON.parse(String(init.body));
      if (fault === 'quota') vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('quota', 'QuotaExceededError'); });
      if (fault === 'lost') sessionStorage.removeItem(KEY);
      if (fault === 'read-blocked') vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new DOMException('blocked', 'SecurityError'); });
      return response(receipt(frozen));
    }
    reads++; return response({ detail: 'unavailable' }, 503);
  });
  const onSaved = vi.fn(); mount(s.api, { onSaved }); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/Known accepted.*storage/i));
  expect(screen.getByRole('button', { name: 'Retry exact save' })).toBeDisabled();
  vi.restoreAllMocks();
  fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  await waitFor(() => expect(reads).toBeGreaterThan(0));
  expect(s.saves().filter(([, init]) => init.method === 'POST')).toHaveLength(1); expect(onSaved).not.toHaveBeenCalled();
});
it.each(['bad POST', 'different GET', 'oversized ACK'] as const)('fails closed on %s, retains evidence and never claims Saved', async fault => {
  let frozen!: EditorSaveRequest;
  const s = server(async (_, init) => {
    if (init.method === 'POST') { frozen = JSON.parse(String(init.body)); const ack = receipt(frozen);
      if (fault === 'bad POST') ack.revision.source_hash = '0'.repeat(64);
      if (fault === 'oversized ACK') Object.assign(ack, { junk: 'x'.repeat(262145) });
      return response(ack); }
    return response(receipt(frozen, 'd'.repeat(32)));
  });
  const onSaved = vi.fn(); mount(s.api, { onSaved }); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Conflict'));
  expect(onSaved).not.toHaveBeenCalled(); expect(sessionStorage.getItem(KEY)).not.toBeNull();
  expect(screen.getByRole('button', { name: 'Retry exact save' })).toBeDisabled();
});
it.each(['unsupported', 'blocked storage', 'corrupt', 'oversized', 'changed generation'] as const)('blocks fresh POST for %s without replacing evidence', async fault => {
  const s = server(async () => { throw new Error('must not dispatch'); }, fault !== 'unsupported');
  if (fault === 'corrupt') sessionStorage.setItem(KEY, '{}');
  if (fault === 'oversized') sessionStorage.setItem(KEY, 'x'.repeat(262145));
  const before = sessionStorage.getItem(KEY);
  const view = mount(s.api); await waitFor(() => expect(s.api.session).not.toBeNull());
  if (fault === 'changed generation') { await ready(); s.api.session = { ...session }; }
  if (fault === 'blocked storage') { await ready(); vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('blocked', 'SecurityError'); }); }
  fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await act(async () => {});
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(fault === 'unsupported' ? /unsupported/i : /conflict|storage|retired/i));
  expect(s.saves()).toHaveLength(0);
  expect(sessionStorage.getItem(KEY)).toBe(before);
  view.unmount();
});
it('refuses replay of a changed payload but allows GET disposition of frozen old-view request after restart', async () => {
  let frozen!: EditorSaveRequest;
  const s = server(async (_, init) => {
    if (init.method === 'POST') { frozen = JSON.parse(String(init.body)); throw new Error('lost'); }
    return response(receipt(frozen));
  });
  const first = mount(s.api); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Unknown')); first.unmount();
  const replacement = server(async (_, init) => { expect(init.method).toBe('GET'); return response(receipt(frozen)); });
  const onSaved = vi.fn(); const next = mount(replacement.api, { draft: 'new draft', documentId: 'new-view', bindingKey: 'draft-B', onSaved });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  expect(screen.getByRole('button', { name: 'Retry exact save' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledExactlyOnceWith(receipt(frozen).revision));
  expect(replacement.saves().map(([url, init]) => [url, init.method])).toEqual([[`/api/editor/save-requests/${frozen.idempotency_key}`, 'GET']]); next.unmount();
});
it('retains unknown acceptance across remount; recovery GET never POSTs and explicit retry reuses exact key and payload', async () => {
  let frozen!: EditorSaveRequest, attempts = 0;
  const s = server(async (_, init) => {
    if (init.method === 'POST') { attempts++; const next = JSON.parse(String(init.body)); if (frozen) expect(next).toEqual(frozen); frozen = next;
      if (attempts === 1) throw new Error('lost ACK'); return response(receipt(frozen)); }
    return attempts === 1 ? response({ detail: 'unknown' }, 404) : response(receipt(frozen));
  });
  const first = mount(s.api); await ready(); fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Unknown'));
  const retained = sessionStorage.getItem(KEY)!; expect(retained).toContain(frozen.yaml_text.trim()); expect(retained).not.toContain(session.csrf_token);
  first.unmount(); const second = mount(s.api); await waitFor(() => expect(screen.getByRole('button', { name: 'Check save status' })).toBeEnabled());
  expect(s.saves()).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Check save status' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Unknown'));
  expect(s.saves().map(([, init]) => init.method)).toEqual(['POST', 'GET']);
  fireEvent.click(screen.getByRole('button', { name: 'Retry exact save' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved'));
  expect(attempts).toBe(2); second.unmount();
});
it.each(['replace', 'remove'] as const)('uses current onSaved after callback %s during GET without changing the frozen request', async change => {
  const get = deferred<Response>(); let frozen!: EditorSaveRequest;
  const s = server(async (_, init) => {
    if (init.method === 'POST') { frozen = JSON.parse(String(init.body)); return response(receipt(frozen)); }
    return get.promise;
  });
  const oldCallback = vi.fn(), latestCallback = vi.fn();
  const view = mount(s.api, { onSaved: oldCallback }); await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' }));
  await waitFor(() => expect(s.saves()).toHaveLength(2));
  view.update({ onSaved: change === 'replace' ? latestCallback : undefined, draft: 'new draft', documentId: 'view:new' });
  await act(async () => { get.resolve(response(receipt(frozen))); });
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Saved frozen revision'));
  expect(oldCallback).not.toHaveBeenCalled();
  if (change === 'replace') expect(latestCallback).toHaveBeenCalledExactlyOnceWith(receipt(frozen).revision);
  else expect(latestCallback).not.toHaveBeenCalled();
  expect(frozen.yaml_text).toBe('name: café\n'); expect(frozen.document_id).toBe('view:old');
  expect(s.saves().map(([, init]) => init.method)).toEqual(['POST', 'GET']);
  expect(sessionStorage.getItem(KEY)).toBeNull();
});
it('freezes click bytes, verifies POST then exact GET before Saved and opens only the checked revision', async () => {
  const get = deferred<Response>(); let frozen!: EditorSaveRequest;
  const s = server(async (url, init) => {
    if (init.method === 'POST') { frozen = JSON.parse(String(init.body)); return response(receipt(frozen)); }
    expect(url).toBe(`/api/editor/save-requests/${encodeURIComponent(frozen.idempotency_key)}`);
    return get.promise;
  });
  const onSaved = vi.fn(), onOpen = vi.fn(); const view = mount(s.api, { onSaved, onOpen }); await ready();
  act(() => { fireEvent.click(screen.getByRole('button', { name: 'Save durable revision' })); view.update({ draft: 'edited later' }); });
  await waitFor(() => expect(s.saves()).toHaveLength(2));
  expect(frozen.yaml_text).toBe('name: café\n'); expect(frozen.document_id).toBe('view:old');
  expect(screen.getByRole('status')).toHaveTextContent(/Known accepted.*readback/i);
  expect(onSaved).not.toHaveBeenCalled();
  await act(async () => { get.resolve(response(receipt(frozen))); });
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
  expect(screen.getByRole('status')).toHaveTextContent('Saved');
  expect(sessionStorage.getItem(KEY)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Open saved revision' }));
  expect(onOpen).toHaveBeenCalledWith(receipt(frozen).revision.open_source);
  expect(s.saves().map(([, init]) => init.method)).toEqual(['POST', 'GET']);
  expect(view.cache.getMutationCache().getAll()).toHaveLength(0);
});
