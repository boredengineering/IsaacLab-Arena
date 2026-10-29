import { act, fireEvent, render, screen, waitFor, cleanup, within } from '@testing-library/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { createHash } from 'node:crypto';
import { StrictMode } from 'react';
import { ApiClient } from './api';
import backend from './publication-backend.fixture.json';
import { PublicationControls, type PublicationControlsProps } from './publication-controls';
const runtime = vi.hoisted(() => ({ current: {} as { api: ApiClient; session: { session_id: string } | null; status: string } }));
vi.mock('./runtime', () => ({ useRuntime: () => runtime.current }));
const hash = 'a'.repeat(64);
const props: PublicationControlsProps = { enabled: true, storeId: 'local', effectId: 'effect', registryId: 'registry', target: { profile_id: 'profile', revision: hash, scope_ownership: 'cooperative_immutable' }, versionRef: { reservation_id: 'reservation', revision_id: 'revision', version: 1, payload_sha256: hash, projection_digest: hash, scope_id: 'scope', database: backend.database, canonical_identity: backend.canonical_identity } };
const keyFor = (p = props) => 'arena:publication:request:v2:' + JSON.stringify([p.registryId, p.storeId, p.effectId, p.versionRef.reservation_id, p.versionRef.revision_id, p.versionRef.version]);
const KEY = keyFor();
const reply = (v: unknown) => new Response(JSON.stringify(v));
function setup(handler: (url: string, options?: RequestInit) => Promise<Response> = async () => reply({}), p = props) {
 const fetcher = vi.fn(handler), api = new ApiClient(fetcher as typeof fetch);
 api.session = { session_id: 'one', csrf_token: 'never-store', expires_at: 9999999999 };
 runtime.current = { api, session: api.session, status: 'live' };
 return { ...render(<PublicationControls {...p} />), api, fetcher };
}
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
beforeEach(() => { sessionStorage.clear(); vi.spyOn(window, 'confirm').mockReturnValue(true); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it.each(['unknown', 'blocked_authorization', 'unresolved'])('degraded binding permits only explicit disposition GET for %s and revalidation never auto-dispatches', async name => {
 let a = acceptance({ request_id: 'unused' });
 const v = setup(async (_u, o) => {
  if (o?.method === 'POST') { if (name === 'unresolved') throw Error('lost ACK'); a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: state(a, name) }); }
  if (name === 'unresolved') throw Error('unavailable');
  return reply({ accepted: a, state: state(a, name) });
 });
 click('Open publication controls'); click('Publish graph');
 await screen.findByText(name === 'unknown' ? /Unknown write outcome/ : name === 'blocked_authorization' ? /Blocked authorization; unsent/ : /Request unresolved/);
 const before = sessionStorage.getItem(KEY), calls = v.fetcher.mock.calls.length;
 v.rerender(<PublicationControls {...props} mutationEnabled={false} />);
 for (const label of ['Publish graph', 'Retry exact request', 'Renew blocked unsent request', 'Reconcile read-only', 'Cancel current attempt']) {
  expect(screen.getByRole('button', { name: label })).toBeDisabled(); click(label);
 }
 expect(v.fetcher).toHaveBeenCalledTimes(calls); expect(sessionStorage.getItem(KEY)).toBe(before);
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled();
 click('Check disposition'); await waitFor(() => expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled());
 expect(v.fetcher).toHaveBeenCalledTimes(calls + 1);
 v.rerender(<PublicationControls {...props} mutationEnabled />);
 expect(v.fetcher).toHaveBeenCalledTimes(calls + 1);
 expect(screen.getByRole('button', { name: name === 'unknown' ? 'Reconcile read-only' : name === 'blocked_authorization' ? 'Renew blocked unsent request' : 'Retry exact request' })).toBeEnabled();
});
it('degraded controls reopen without implicit GET and backend disable still blocks disposition', async () => {
 const v = setup(async () => { throw Error('lost'); });
 click('Open publication controls'); click('Publish graph'); await screen.findByText(/Request unresolved/);
 v.rerender(<PublicationControls {...props} mutationEnabled={false} />);
 click('Close publication controls'); click('Open publication controls');
 expect(v.fetcher).toHaveBeenCalledTimes(1);
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled();
 v.rerender(<PublicationControls {...props} enabled={false} mutationEnabled={false} />);
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeDisabled(); click('Check disposition');
 expect(v.fetcher).toHaveBeenCalledTimes(1);
 v.rerender(<PublicationControls {...props} mutationEnabled={false} />);
 v.api.session = { ...v.api.session!, session_id: 'two' };
 click('Check disposition'); expect(v.fetcher).toHaveBeenCalledTimes(1);
});
it.each(['session', 'generation'])('degraded mounted scope cannot authorize GET after %s replacement even after rerender', async boundary => {
 const v = setup(async () => { throw Error('lost'); }); click('Open publication controls'); click('Publish graph'); await screen.findByText(/Request unresolved/);
 v.rerender(<PublicationControls {...props} mutationEnabled={false} />);
 v.api.session = { ...v.api.session!, session_id: boundary === 'session' ? 'two' : 'one' }; runtime.current.session = v.api.session;
 v.rerender(<PublicationControls {...props} mutationEnabled={false} />);
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeDisabled();
 click('Check disposition'); expect(v.fetcher).toHaveBeenCalledTimes(1);
});
it('declined write does not POST; lost acknowledgement retains exact replay across unmount', async () => {
 const v = setup(async () => { throw new Error('private hostile failure'); }); click('Open publication controls');
 vi.mocked(window.confirm).mockReturnValue(false); click('Publish graph'); expect(v.fetcher).not.toHaveBeenCalled();
 vi.mocked(window.confirm).mockReturnValue(true); click('Publish graph'); await screen.findByText(/Request unresolved/);
 const raw = sessionStorage.getItem(KEY)!; expect(raw).not.toContain('never-store'); expect(raw.length).toBeLessThanOrEqual(4096);
 const first = v.fetcher.mock.calls[0]; v.unmount();
 render(<PublicationControls {...props} />); expect(v.fetcher).toHaveBeenCalledTimes(1); click('Open publication controls');
 await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(2));
 click('Retry exact request'); await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(3));
 expect(v.fetcher.mock.calls[2][0]).toEqual(first[0]); expect(v.fetcher.mock.calls[2][1]?.body).toEqual(first[1]?.body); expect(sessionStorage.getItem(KEY)).toBe(raw);
 expect(screen.queryByText(/private hostile/)).toBeNull();
});
function acceptance(body: Record<string, unknown>, operation = 'write', effect = 'effect') {
 const binding = { store_id: 'local', effect_id: effect, request_id: body.request_id, owner_session: 'one', principal: 'one', operation, previous_request_id: body.previous_request_id ?? null };
 const request_digest = createHash('sha256').update(JSON.stringify(binding, Object.keys(binding).sort())).digest('hex');
 return { schema_version: 1, registry_id: 'registry', ...binding, request_digest, attempt_id: 'attempt', generation: 1, capability: operation === 'reconcile' ? 'graph_read' : 'graph_write' };
}
function state(a: ReturnType<typeof acceptance>, name = 'claimed') { return { schema_version: 1, effect_id: 'effect', target_profile: props.target, payload_sha256: hash, state: name, cancelled: false, generation: a.generation, attempt_id: a.attempt_id, request_id: a.request_id, receipt: null as unknown, write_claim_count: 1, reconciliation: null as unknown, write_callback_open: false }; }
function receipt() { return { schema_version: 1, status: 'verified', effect_id: 'effect', target_profile: props.target, payload_sha256: hash, transport: { status: 'verified', effect_id: 'effect', database: props.versionRef.database, scope_id: 'scope', projection_digest: hash, canonical_identity: props.versionRef.canonical_identity, verification_boundary: { method: 'operator_attested_immutable_scope_v1', operator_attested: true, database_snapshot: false, declaration: backend.declaration } } }; }
it('verifies exact acceptance with advanced state, preserves reference and performs only explicit reads afterward', async () => {
 let accepted = acceptance({ request_id: 'unused' });
 const v = setup(async (_url, o) => { if (o?.method === 'POST') { accepted = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted, state: state(accepted) }); } const s = state(accepted, 'verified'); s.generation = 2; s.attempt_id = 'later'; s.request_id = 'later'; s.receipt = receipt(); return reply({ accepted, state: s }); });
 click('Open publication controls'); click('Publish graph'); await screen.findByText(/Verified publication/);
 expect(v.fetcher).toHaveBeenCalledTimes(2); expect(sessionStorage.getItem(KEY)).not.toBeNull();
 expect(screen.getByRole('button', { name: 'Retry exact request' })).toBeDisabled();
 click('Check disposition'); await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(3));
 expect(v.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(1);
});
it.each(['unknown', 'blocked_authorization', 'claimed', 'released', 'cancelled_no_send'])('gates followups and cancel for %s with separate declined confirmations', async name => {
 let a = acceptance({ request_id: 'unused' });
 const v = setup(async (_u, o) => { if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: state(a, name) }); } return reply({ accepted: a, state: state(a, name) }); });
 click('Open publication controls'); click('Publish graph'); await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(2));
 await waitFor(() => expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled());
 expect(screen.getByRole('button', { name: 'Renew blocked unsent request' }).hasAttribute('disabled')).toBe(name !== 'blocked_authorization');
 expect(screen.getByRole('button', { name: 'Reconcile read-only' }).hasAttribute('disabled')).toBe(name !== 'unknown');
 expect(screen.getByRole('button', { name: 'Cancel current attempt' }).hasAttribute('disabled')).toBe(name === 'cancelled_no_send');
 vi.mocked(window.confirm).mockReturnValue(false);
 click('Renew blocked unsent request'); click('Reconcile read-only'); click('Cancel current attempt');
 expect(v.fetcher).toHaveBeenCalledTimes(2);
});
it('unknown write can only explicitly start a predecessor-bound read, never another write', async () => {
 let a = acceptance({ request_id: 'unused' });
 const v = setup(async (u, o) => { if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body)), u.endsWith('reconcile') ? 'reconcile' : 'write'); return reply({ accepted_new: true, accepted: a, state: state(a, 'unknown') }); } return reply({ accepted: a, state: state(a, 'unknown') }); });
 click('Open publication controls'); click('Publish graph'); await screen.findByText(/Unknown write outcome/);
 const prior = a.request_id; click('Reconcile read-only'); await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(4));
 const posts = v.fetcher.mock.calls.filter(([,o]) => o?.method === 'POST'); expect(posts[1][0]).toMatch(/reconcile$/); expect(JSON.parse(String(posts[1][1]?.body))).toEqual({ request_id: expect.any(String), previous_request_id: prior });
 expect(screen.getByRole('button', { name: 'Publish graph' })).toBeDisabled();
});
it('retains POST acceptance across remount and rejects a changed GET acceptance', async () => {
 let a = acceptance({ request_id: 'unused' }), reads = 0;
 const v = setup(async (_u, o) => { if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: state(a) }); } reads++; const s = state(a, 'verified'); s.receipt = receipt(); return reply({ accepted: { ...a, attempt_id: 'wrong' }, state: s }); });
 click('Open publication controls'); click('Publish graph'); await screen.findByText(/Accepted; current state unavailable/);
 const stored = JSON.parse(sessionStorage.getItem(KEY)!); expect(stored.accepted).toEqual(a);
 v.unmount(); render(<PublicationControls {...props} />); click('Open publication controls'); await screen.findByText(/Accepted; current state unavailable/);
 expect(reads).toBe(2); expect(sessionStorage.getItem(KEY)).not.toBeNull();
});
it.each(['session', 'unmount', 'sibling', 'close'])('fences late acceptance after %s', async kind => {
 let finish!: (r: Response) => void;
 const v = setup(async () => new Promise<Response>(r => { finish = r; }));
 click('Open publication controls'); click('Publish graph'); const raw = sessionStorage.getItem(KEY)!;
 const f = JSON.parse(raw), a = acceptance(f.body);
 if (kind === 'session') { v.api.session = { session_id: 'two', csrf_token: 'other-secret', expires_at: 9999999999 }; runtime.current.session = v.api.session; v.rerender(<PublicationControls {...props} />); }
 if (kind === 'unmount') v.unmount();
 if (kind === 'sibling') sessionStorage.setItem(KEY, JSON.stringify({ ...f, body: { request_id: 'sibling' } }));
 if (kind === 'close') click('Close publication controls');
 const before = sessionStorage.getItem(KEY);
 await act(async () => { finish(reply({ accepted_new: true, accepted: a, state: state(a) })); });
 expect(v.fetcher).toHaveBeenCalledTimes(1); expect(sessionStorage.getItem(KEY)).toBe(before);
 if (kind === 'session') expect(screen.getByText(/Cross-session publication recovery is unsupported/)).toBeInTheDocument();
});
it.each(['null', 'mismatch', 'oversize', 'hostile'])('fails closed on %s state and retains exact request', async kind => {
 let a = acceptance({ request_id: 'unused' });
 const v = setup(async (_u, o) => {
  if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: null, disposition: 'accepted_state_unavailable' }); }
  const s = state(a, 'verified'); s.receipt = receipt();
  if (kind === 'mismatch') s.payload_sha256 = 'b'.repeat(64);
  if (kind === 'hostile') (s.receipt as Record<string, unknown>).secret = '<script>hostile</script>';
  if (kind === 'oversize') (s.receipt as Record<string, unknown>).secret = 'x'.repeat(131073);
  return reply({ accepted: a, state: kind === 'null' ? null : s });
 });
 click('Open publication controls'); click('Publish graph'); await screen.findByText(kind === 'null' ? /current state unavailable/ : /Accepted; current state unavailable/);
 expect(sessionStorage.getItem(KEY)).not.toBeNull(); expect(screen.queryByText(/^Verified publication/)).toBeNull();
 expect(screen.getByRole('button', { name: 'Reconcile read-only' })).toBeDisabled(); expect(v.container.querySelector('script,input,a')).toBeNull();
});
it.each(['https://bad', 'a/b', 'x;rm', 'x'.repeat(65)])('rejects hostile scope %s without API', bad => {
 const v = setup(undefined, { ...props, storeId: bad }); expect(screen.getByRole('button', { name: 'Open publication controls' })).toBeDisabled(); expect(v.fetcher).not.toHaveBeenCalled();
});
it('malformed retention never authorizes replacement or GET', () => {
 sessionStorage.setItem(KEY, '{bad'); const v = setup(); expect(screen.getByRole('button', { name: 'Open publication controls' })).toBeDisabled(); expect(v.fetcher).not.toHaveBeenCalled(); expect(sessionStorage.getItem(KEY)).toBe('{bad');
});
it('cancel posts the exact owned attempt and labels cancelled-but-verified without rollback', async () => {
 let a = acceptance({ request_id: 'unused' }), cancelled = false;
 const v = setup(async (u, o) => { if (u.endsWith('/cancel')) { cancelled = true; return reply({ cancelled: true }); } if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: state(a, 'released') }); } const s = state(a, cancelled ? 'verified' : 'released'); s.cancelled = cancelled; if (cancelled) s.receipt = receipt(); return reply({ accepted: a, state: s }); });
 click('Open publication controls'); click('Publish graph'); await screen.findByText(/Released; verification/); click('Cancel current attempt'); await screen.findByText(/Cancelled but verified/);
 expect(JSON.parse(String(v.fetcher.mock.calls[2][1]?.body))).toEqual({ request_id: a.request_id, attempt_id: a.attempt_id, generation: a.generation });
});
it('shows the frozen target and version for consent without fetching', () => {
 const v = setup(); click('Open publication controls'); expect(screen.getByText(/profile.*Version 1.*revision/)).toBeInTheDocument(); expect(v.fetcher).not.toHaveBeenCalled();
});
it('close and reopen fences old callbacks and allows a new explicit disposition check', async () => {
 let finish!: (r: Response) => void;
 const v = setup(async (_u, o) => o?.method === 'POST' ? new Promise<Response>(r => { finish = r; }) : reply({}));
 click('Open publication controls'); click('Publish graph'); const f = JSON.parse(sessionStorage.getItem(KEY)!);
 click('Close publication controls'); click('Open publication controls');
 await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(2));
 const before = sessionStorage.getItem(KEY);
 await act(async () => { const a = acceptance(f.body); finish(reply({ accepted_new: true, accepted: a, state: state(a) })); });
 expect(v.fetcher).toHaveBeenCalledTimes(2); expect(sessionStorage.getItem(KEY)).toBe(before);
});
it('accepted request cannot become another write replay after readback failure', async () => {
 const v = setup(async (_u, o) => { if (o?.method === 'POST') { const a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: state(a, 'unknown') }); } throw Error('404'); });
 click('Open publication controls'); click('Publish graph'); await screen.findByText(/Accepted; current state unavailable/);
 expect(screen.getByRole('button', { name: 'Retry exact request' })).toBeDisabled(); click('Retry exact request'); expect(v.fetcher).toHaveBeenCalledTimes(2);
});
it('freezes scope before confirmation and declines changed consent scope', () => {
 const changed = structuredClone(props); const v = setup(undefined, changed); click('Open publication controls');
 vi.mocked(window.confirm).mockImplementation(() => { changed.target.profile_id = 'different'; return true; });
 click('Publish graph'); expect(v.fetcher).not.toHaveBeenCalled(); expect(sessionStorage.getItem(KEY)).toBeNull();
});
it('permits explicit publication after StrictMode mount cleanup', async () => {
 const v = setup(async () => { throw Error('lost'); }); v.unmount();
 render(<StrictMode><PublicationControls {...props} /></StrictMode>);
 click('Open publication controls'); click('Publish graph');
 await screen.findByText(/Request unresolved/); expect(v.fetcher).toHaveBeenCalledTimes(1);
});
it.each(['POST', 'GET', 'cancel'])('retires %s dispatch ownership on disable and stale settlement cannot clear new work', async phase => {
 let a = acceptance({ request_id: 'unused' }); let finishOld!: (r: Response) => void, finishNew!: (r: Response) => void;
 let holding = true;
 const v = setup(async (u, o) => {
  if (u.endsWith('/cancel')) return new Promise<Response>(r => { finishOld = r; });
  if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); if (phase === 'POST') return new Promise<Response>(r => { finishOld = r; }); return reply({ accepted_new: true, accepted: a, state: state(a) }); }
  if (phase === 'GET' && holding) return new Promise<Response>(r => { finishOld = r; });
  if (!holding) return new Promise<Response>(r => { finishNew = r; });
  return reply({ accepted: a, state: state(a) });
 });
 click('Open publication controls'); click('Publish graph');
 if (phase === 'GET') await waitFor(() => expect(finishOld).toBeDefined());
 if (phase === 'cancel') { await screen.findByText(/Queued, not yet released/); click('Cancel current attempt'); }
 const count = v.fetcher.mock.calls.length;
 v.rerender(<PublicationControls {...props} enabled={false} />);
 v.rerender(<PublicationControls {...props} />); holding = false;
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled(); click('Check disposition');
 expect(v.fetcher).toHaveBeenCalledTimes(count + 1);
 await act(async () => finishOld(reply(phase === 'cancel' ? { cancelled: true } : phase === 'POST' ? { accepted_new: true, accepted: a, state: state(a) } : { accepted: a, state: state(a) })));
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeDisabled();
 await act(async () => finishNew(reply({ accepted: a, state: state(a) })));
 await waitFor(() => expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled());
 expect(v.fetcher).toHaveBeenCalledTimes(count + 1);
});
// pending has generation=0 and no acceptance; cancelled_no_send is a reachable terminal attempt.
it.each(['verified', 'unknown', 'cancelled_no_send'])('retains independent effect history after A is %s', async name => {
 const accepted = new Map<string, ReturnType<typeof acceptance>>();
 const v = setup(async (u, o) => {
  const effect = u.includes('/second/') ? 'second' : 'effect';
  if (o?.method === 'POST') accepted.set(effect, acceptance(JSON.parse(String(o.body)), 'write', effect));
  const a = accepted.get(effect)!; const s = state(a, name); s.effect_id = effect; if (name === 'cancelled_no_send') s.cancelled = true;
  if (name === 'verified') { const r = receipt(); r.effect_id = effect; r.transport.effect_id = effect; s.receipt = r; }
  return reply(o?.method === 'POST' ? { accepted_new: true, accepted: a, state: s } : { accepted: a, state: s });
 });
 click('Open publication controls'); click('Publish graph'); await waitFor(() => expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled());
 const first = v.fetcher.mock.calls[0][1]?.body;
 v.rerender(<PublicationControls {...props} effectId="second" />);
 expect(screen.getByRole('button', { name: 'Publish graph' })).toBeEnabled();
 click('Publish graph'); await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(4));
 await waitFor(() => expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled());
 v.rerender(<PublicationControls {...props} />); expect(screen.getByRole('button', { name: 'Publish graph' })).toBeDisabled();
 click('Check disposition'); await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(5));
 expect(v.fetcher.mock.calls[4][0]).toContain(JSON.parse(String(first)).request_id);
 expect(v.fetcher.mock.calls.filter(([,o]) => o?.method === 'POST')).toHaveLength(2);
});
it.each(['scope', 'session', 'generation'])('never displays prior verified evidence after %s replacement', async kind => {
 let a = acceptance({ request_id: 'unused' });
 const v = setup(async (_u, o) => {
  if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: state(a) }); }
  const s = state(a, 'verified'); s.receipt = receipt(); return reply({ accepted: a, state: s });
 });
 click('Open publication controls'); expect(screen.getByRole('status')).toHaveTextContent(/unchecked/i);
 click('Publish graph'); await screen.findByText(/^Verified publication/);
 if (kind !== 'scope') { v.api.session = { session_id: kind === 'session' ? 'two' : 'one', csrf_token: 'new', expires_at: 9999999999 }; runtime.current.session = v.api.session; }
 v.rerender(<PublicationControls {...props} effectId={kind === 'scope' ? 'second' : props.effectId} />);
 expect(screen.queryByText(/^Verified publication/)).toBeNull();
 expect(screen.getByRole('status')).toHaveTextContent(/unchecked/i);
 expect(v.fetcher).toHaveBeenCalledTimes(2);
});
it('rejects an incorrect immutable-scope boundary declaration', async () => {
 let a = acceptance({ request_id: 'unused' });
 const v = setup(async (_u, o) => {
  if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: state(a) }); }
  const s = state(a, 'verified'), r = receipt(); r.transport.verification_boundary.declaration = 'Cooperative immutable scope'; s.receipt = r;
  return reply({ accepted: a, state: s });
 });
 click('Open publication controls'); click('Publish graph'); await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(2));
 await screen.findByText(/Accepted; current state unavailable/); expect(screen.queryByText(/^Verified publication/)).toBeNull();
});
it('retains the real full unavailable acceptance before a failing GET', async () => {
 const v = setup(async (_u, o) => {
  if (o?.method === 'POST') return reply({ accepted_new: true, accepted: acceptance(JSON.parse(String(o.body))), state: null, disposition: 'accepted_state_unavailable', error: 'Publication state unavailable' });
  throw Error('read unavailable');
 });
 click('Open publication controls'); click('Publish graph'); await screen.findByText(/Accepted; current state unavailable/);
 expect(v.fetcher).toHaveBeenCalledTimes(2);
 expect(JSON.parse(sessionStorage.getItem(KEY)!).accepted).toBeDefined();
 expect(screen.getByRole('button', { name: 'Retry exact request' })).toBeDisabled();
});
it('accepts backend canonical names and dotted UTF-8 database identifiers', () => {
 const p = structuredClone(props);
 // research_projection.project_spec fallback; checked_graph_config permits 256 UTF-8 bytes.
 p.versionRef.canonical_identity = backend.canonical_identity;
 p.versionRef.database = '研究.'.repeat(36) + 'abcd';
 const v = setup(undefined, p);
 expect(new TextEncoder().encode(p.versionRef.database)).toHaveLength(256);
 expect(screen.getByRole('button', { name: 'Open publication controls' })).toBeEnabled();
 click('Open publication controls'); expect(screen.getByRole('button', { name: 'Publish graph' })).toBeEnabled();
 expect(v.fetcher).not.toHaveBeenCalled();
});
it.each(['POST', 'GET', 'cancel'])('re-enables checking after %s settles while disabled', async phase => {
 let a = acceptance({ request_id: 'unused' }); let finish!: (r: Response) => void;
 const v = setup(async (u, o) => {
  if (u.endsWith('/cancel')) return new Promise<Response>(r => { finish = r; });
  if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); if (phase === 'POST') return new Promise<Response>(r => { finish = r; }); return reply({ accepted_new: true, accepted: a, state: state(a) }); }
  if (phase === 'GET') return new Promise<Response>(r => { finish = r; });
  return reply({ accepted: a, state: state(a) });
 });
 click('Open publication controls'); click('Publish graph');
 if (phase === 'GET') await waitFor(() => expect(finish).toBeDefined());
 if (phase === 'cancel') { await screen.findByText(/Queued, not yet released/); click('Cancel current attempt'); }
 v.rerender(<PublicationControls {...props} enabled={false} />);
 const before = sessionStorage.getItem(KEY);
 await act(async () => finish(reply(phase === 'cancel' ? { cancelled: true } : phase === 'POST' ? { accepted_new: true, accepted: a, state: state(a) } : { accepted: a, state: state(a) })));
 expect(sessionStorage.getItem(KEY)).toBe(before);
 v.rerender(<PublicationControls {...props} />);
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled();
});
it('switching away from an outstanding POST preserves A and allows explicit B without stale unlock', async () => {
 const finishes: ((r: Response) => void)[] = [];
 const v = setup(async () => new Promise<Response>(r => finishes.push(r)));
 click('Open publication controls'); click('Publish graph'); const first = sessionStorage.getItem(KEY)!;
 const secondProps = { ...props, effectId: 'second' };
 v.rerender(<PublicationControls {...secondProps} />); click('Publish graph');
 expect(v.fetcher).toHaveBeenCalledTimes(2);
 const second = sessionStorage.getItem(keyFor(secondProps)); expect(second).not.toBeNull();
 await act(async () => { const a = acceptance(JSON.parse(first).body); finishes[0](reply({ accepted_new: true, accepted: a, state: state(a) })); });
 expect(sessionStorage.getItem(KEY)).toBe(first); expect(sessionStorage.getItem(keyFor(secondProps))).toBe(second);
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeDisabled();
 await act(async () => finishes[1](reply({})));
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled();
});
it('keeps two versions of one effect distinct and refuses to adopt sibling writes', async () => {
 const v = setup(async () => { throw Error('lost'); }); click('Open publication controls'); click('Publish graph'); await screen.findByText(/Request unresolved/);
 const first = sessionStorage.getItem(KEY)!;
 const next = { ...props, versionRef: { ...props.versionRef, version: 2, revision_id: 'revision2' } };
 v.rerender(<PublicationControls {...next} />); click('Publish graph'); await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(2));
 expect(sessionStorage.getItem(KEY)).toBe(first); expect(sessionStorage.getItem(keyFor(next))).not.toBeNull();
 v.rerender(<PublicationControls {...props} />);
 sessionStorage.setItem(KEY, JSON.stringify({ ...JSON.parse(first), body: { request_id: 'sibling' } }));
 click('Retry exact request'); expect(v.fetcher).toHaveBeenCalledTimes(2); expect(screen.getByText(/Request ownership changed/)).toBeInTheDocument();
});
it('mounted siblings cannot adopt or overwrite a request created after mount', async () => {
 const first = setup(async () => { throw Error('lost'); });
 const sibling = render(<PublicationControls {...props} />);
 const a = within(first.container), b = within(sibling.container);
 fireEvent.click(a.getByRole('button', { name: 'Open publication controls' }));
 fireEvent.click(b.getByRole('button', { name: 'Open publication controls' }));
 fireEvent.click(a.getByRole('button', { name: 'Publish graph' })); await a.findByText(/Request unresolved/);
 const before = sessionStorage.getItem(KEY);
 fireEvent.click(b.getByRole('button', { name: 'Publish graph' }));
 expect(first.fetcher).toHaveBeenCalledTimes(1); expect(sessionStorage.getItem(KEY)).toBe(before);
 expect(b.getByText(/Request ownership changed/)).toBeInTheDocument();
});
it('lost renewal acknowledgement retries exactly the predecessor-bound old body', async () => {
 let a = acceptance({ request_id: 'unused' }), renewing = false;
 const v = setup(async (u, o) => {
  if (u.endsWith('/renew')) { renewing = true; throw Error('lost'); }
  if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: state(a, 'blocked_authorization') }); }
  if (renewing) throw Error('unknown');
  return reply({ accepted: a, state: state(a, 'blocked_authorization') });
 });
 click('Open publication controls'); click('Publish graph'); await screen.findByText(/Blocked authorization; unsent/);
 click('Renew blocked unsent request'); await screen.findByText(/Request unresolved/);
 const previous = v.fetcher.mock.calls[2];
 expect(JSON.parse(String(previous[1]?.body)).previous_request_id).toBe(a.request_id);
 click('Retry exact request'); await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(4));
 expect(v.fetcher.mock.calls[3][0]).toBe(previous[0]); expect(v.fetcher.mock.calls[3][1]?.body).toBe(previous[1]?.body);
});
it('legacy global retention is blocked without migration or eviction', () => {
 sessionStorage.setItem('arena:publication:request:v1', '{}'); const v = setup();
 expect(screen.getByRole('button', { name: 'Open publication controls' })).toBeDisabled();
 expect(sessionStorage.getItem('arena:publication:request:v1')).toBe('{}'); expect(v.fetcher).not.toHaveBeenCalled();
});
it('full history refuses a new effect without evicting any unresolved record', () => {
 const { enabled: _enabled, ...scope } = props;
 for (let i = 0; i < 32; i++) { const p = { ...scope, effectId: 'retained' + i }; sessionStorage.setItem(keyFor(p), JSON.stringify({ session: 'one', scope: p, operation: 'write', body: { request_id: 'request' + i } })); }
 const before = { ...sessionStorage }; const v = setup(); click('Open publication controls'); click('Publish graph');
 expect(v.fetcher).not.toHaveBeenCalled(); expect({ ...sessionStorage }).toEqual(before);
 expect(screen.getByText(/Request ownership changed/)).toBeInTheDocument();
});
it.each(['', '   ', '\u00a0\u2003', '\u0085', 'x'.repeat(257), '研究.'.repeat(37), 'line\nfeed'])('rejects invalid backend database %s without dispatch', database => {
 const v = setup(undefined, { ...props, versionRef: { ...props.versionRef, database } });
 expect(screen.getByRole('button', { name: 'Open publication controls' })).toBeDisabled(); expect(v.fetcher).not.toHaveBeenCalled();
});
const bytes = (v: unknown) => new TextEncoder().encode(JSON.stringify(v)).length;
const requestId = '12345678-1234-1234-1234-123456789abc';
function nearLimit(operation: 'write' | 'renew' | 'reconcile', completeBytes: number) {
 const { enabled: _enabled, ...scope } = structuredClone(props);
 const f = { session: 'one', scope, operation, body: operation === 'write' ? { request_id: requestId } : { request_id: requestId, previous_request_id: 'prior' } };
 const accepted = { ...acceptance(f.body, operation), attempt_id: 'a'.repeat(64), generation: Number.MAX_SAFE_INTEGER };
 scope.versionRef.canonical_identity.name = '研究"\\\n';
 scope.versionRef.canonical_identity.name += 'n'.repeat(completeBytes - bytes({ ...f, accepted }));
 expect(bytes({ ...f, accepted })).toBe(completeBytes);
 return { f, accepted, p: { ...scope, enabled: true } };
}
it.each(['write', 'renew', 'reconcile'] as const)('old near-limit %s request stays read-only when complete ACK cannot fit', async operation => {
 const { f, p } = nearLimit(operation, 4097); expect(bytes(f)).toBeLessThanOrEqual(4096);
 const before = JSON.stringify(f); sessionStorage.setItem(KEY, before);
 const v = setup(async () => { throw Error('unavailable'); }, p);
 click('Open publication controls'); await screen.findByText(/Request unresolved/);
 click('Retry exact request');
 expect(v.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(0);
 expect(sessionStorage.getItem(KEY)).toBe(before);
 expect(screen.getByRole('status')).not.toHaveTextContent(/retry/i);
 expect(screen.getByRole('status')).toHaveTextContent(/Operator review/);
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled();
});
it('fresh near-limit request refuses POST before creating or changing history', () => {
 const { p } = nearLimit('write', 4097);
 const { f } = nearLimit('write', 4096); f.scope.effectId = 'other';
 sessionStorage.setItem(keyFor(f.scope), JSON.stringify(f)); const before = { ...sessionStorage };
 vi.spyOn(crypto, 'randomUUID').mockReturnValue(requestId);
 const v = setup(undefined, p); click('Open publication controls'); click('Publish graph');
 expect(v.fetcher).not.toHaveBeenCalled(); expect({ ...sessionStorage }).toEqual(before);
});
it.each(['renew', 'reconcile'] as const)('near-limit %s followup does not replace accepted predecessor', async operation => {
 const { f, p } = nearLimit(operation, 4097);
 const prior = { ...f, operation: 'write', body: { request_id: 'prior' }, accepted: acceptance({ request_id: 'prior' }) };
 expect(bytes(prior)).toBeLessThanOrEqual(4096);
 const before = JSON.stringify(prior); sessionStorage.setItem(KEY, before);
 vi.spyOn(crypto, 'randomUUID').mockReturnValue(requestId);
 const v = setup(async () => reply({ accepted: prior.accepted, state: state(prior.accepted, operation === 'renew' ? 'blocked_authorization' : 'unknown') }), p);
 click('Open publication controls'); await waitFor(() => expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled());
 click(operation === 'renew' ? 'Renew blocked unsent request' : 'Reconcile read-only');
 expect(v.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(0);
 expect(sessionStorage.getItem(KEY)).toBe(before);
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled();
});
it.each(['write', 'renew', 'reconcile'] as const)('maximum complete %s ACK fits 4KiB and survives failed GET/remount without POST retry', async operation => {
 const { f, accepted, p } = nearLimit(operation, 4096);
 vi.spyOn(crypto, 'randomUUID').mockReturnValue(requestId);
 if (operation !== 'write') sessionStorage.setItem(KEY, JSON.stringify(f));
 const v = setup(async (_u, o) => { if (o?.method === 'POST') return reply({ accepted_new: true, accepted, state: null, disposition: 'accepted_state_unavailable', error: 'Publication state unavailable' }); throw Error('read unavailable'); }, p);
 click('Open publication controls');
 if (operation !== 'write') await screen.findByText(/Request unresolved/);
 click(operation === 'write' ? 'Publish graph' : 'Retry exact request');
 await screen.findByText(/Accepted; current state unavailable/);
 const before = sessionStorage.getItem(KEY)!;
 expect(bytes(JSON.parse(before))).toBe(4096); expect(JSON.parse(before).accepted).toEqual(accepted);
 expect(screen.getByRole('status')).not.toHaveTextContent(/retry/i);
 expect(screen.getByRole('button', { name: 'Retry exact request' })).toBeDisabled();
 v.unmount(); render(<PublicationControls {...p} />); click('Open publication controls');
 await screen.findByText(/Accepted; current state unavailable/); click('Retry exact request');
 expect(sessionStorage.getItem(KEY)).toBe(before);
 expect(v.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(1);
});
it.each(['renew', 'reconcile'] as const)('maximum complete %s followup ACK replaces predecessor durably before failed readback', async operation => {
 const { f, accepted, p } = nearLimit(operation, 4096);
 const prior = { ...f, operation: 'write', body: { request_id: 'prior' }, accepted: acceptance({ request_id: 'prior' }) };
 sessionStorage.setItem(KEY, JSON.stringify(prior));
 vi.spyOn(crypto, 'randomUUID').mockReturnValue(requestId);
 let sent = false;
 const v = setup(async (_u, o) => {
  if (o?.method === 'POST') { sent = true; return reply({ accepted_new: true, accepted, state: null, disposition: 'accepted_state_unavailable' }); }
  if (sent) throw Error('read unavailable');
  return reply({ accepted: prior.accepted, state: state(prior.accepted, operation === 'renew' ? 'blocked_authorization' : 'unknown') });
 }, p);
 click('Open publication controls');
 const button = operation === 'renew' ? 'Renew blocked unsent request' : 'Reconcile read-only';
 await waitFor(() => expect(screen.getByRole('button', { name: button })).toBeEnabled()); click(button);
 await screen.findByText(/Accepted; current state unavailable/);
 const before = sessionStorage.getItem(KEY)!; expect(bytes(JSON.parse(before))).toBe(4096);
 expect(JSON.parse(before).accepted).toEqual(accepted);
 v.unmount(); render(<PublicationControls {...p} />); click('Open publication controls');
 await screen.findByText(/Accepted; current state unavailable/);
 expect(screen.getByRole('button', { name: 'Retry exact request' })).toBeDisabled();
 expect(sessionStorage.getItem(KEY)).toBe(before);
 expect(v.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(1);
});
it('preserves surrounding database whitespace in frozen destination and verified receipt', async () => {
 const p = { ...props, versionRef: { ...props.versionRef, database: ' research.db ' } };
 let a = acceptance({ request_id: 'unused' });
 const v = setup(async (_u, o) => {
  if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: null }); }
  const r = receipt(); r.transport.database = p.versionRef.database;
  const s = state(a, 'verified'); s.receipt = r; return reply({ accepted: a, state: s });
 }, p);
 click('Open publication controls'); click('Publish graph'); await screen.findByText(/^Verified publication/);
 expect(JSON.parse(sessionStorage.getItem(KEY)!).scope.versionRef.database).toBe(' research.db ');
 expect(v.fetcher).toHaveBeenCalledTimes(2);
});
it.each(['QuotaExceededError', 'SecurityError'])('keeps known ACK GET-only when real Storage.setItem throws %s after POST', async errorName => {
 let a = acceptance({ request_id: 'unused' }), frozen = '', failGet = true;
 const original = Storage.prototype.setItem;
 const writes = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {
  if (key === KEY && JSON.parse(value).accepted) throw new DOMException('private storage failure', errorName);
  return original.call(this, key, value);
 });
 const v = setup(async (_u, o) => {
  if (o?.method === 'POST') { frozen = sessionStorage.getItem(KEY)!; a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: null, disposition: 'accepted_state_unavailable', error: 'Publication state unavailable' }); }
  if (failGet) throw Error('GET unavailable');
  return reply({ accepted: a, state: state(a, 'blocked_authorization') });
 });
 click('Open publication controls'); click('Publish graph');
 await screen.findByText(/Acceptance storage\/readback failed/);
 expect(screen.getByRole('status')).toHaveTextContent(/Accepted; current state unavailable/);
 expect(screen.getByRole('status')).not.toHaveTextContent(/explicitly retry|private storage/);
 expect(sessionStorage.getItem(KEY)).toBe(frozen);
 expect(screen.getByRole('button', { name: 'Retry exact request' })).toBeDisabled();
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled();
 expect(v.fetcher).toHaveBeenCalledTimes(2);
 failGet = false; click('Check disposition'); await screen.findByText(/Blocked authorization; unsent/);
 expect(screen.getByRole('status')).toHaveTextContent(/Acceptance storage\/readback failed/);
 for (const name of ['Retry exact request', 'Publish graph', 'Renew blocked unsent request', 'Reconcile read-only', 'Cancel current attempt']) expect(screen.getByRole('button', { name })).toBeDisabled();
 writes.mockRestore(); click('Check disposition'); await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(4));
 await waitFor(() => expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled());
 expect(JSON.parse(sessionStorage.getItem(KEY)!)).toEqual({ ...JSON.parse(frozen), accepted: a });
 expect(screen.getByRole('button', { name: 'Renew blocked unsent request' })).toBeDisabled();
 expect(v.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(1);
 expect(v.fetcher.mock.calls.slice(1).every(([u, o]) => u.endsWith('/requests/' + a.request_id) && o?.method !== 'POST')).toBe(true);
});
it.each(['revoked', 'readback'])('keeps checked acceptance in memory when storage is %s after ACK', async kind => {
 let a = acceptance({ request_id: 'unused' }), unavailable = false, before = '';
 const set = Storage.prototype.setItem, get = Storage.prototype.getItem;
 vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, key) { if (unavailable) throw new DOMException('revoked', 'SecurityError'); return get.call(this, key); });
 vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {
  if (key === KEY && JSON.parse(value).accepted) { unavailable = true; if (kind === 'revoked') throw new DOMException('revoked', 'SecurityError'); }
  return set.call(this, key, value);
 });
 const v = setup(async (_u, o) => {
  if (o?.method === 'POST') { before = sessionStorage.getItem(KEY)!; a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: null }); }
  throw Error('GET unavailable');
 });
 click('Open publication controls'); click('Publish graph'); await screen.findByText(/Acceptance storage\/readback failed/);
 expect(screen.getByRole('status')).toHaveTextContent(/Accepted; current state unavailable/);
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled();
 expect(screen.getByRole('button', { name: 'Retry exact request' })).toBeDisabled();
 click('Check disposition'); await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(3));
 unavailable = false; vi.restoreAllMocks();
 expect(JSON.parse(sessionStorage.getItem(KEY)!)).toEqual(kind === 'revoked' ? JSON.parse(before) : { ...JSON.parse(before), accepted: a });
 v.unmount(); render(<PublicationControls {...props} />); click('Open publication controls');
 await screen.findByText(kind === 'revoked' ? /Request unresolved/ : /Accepted; current state unavailable/);
 expect(screen.getByRole('button', { name: 'Retry exact request' }).hasAttribute('disabled')).toBe(kind !== 'revoked');
 expect(v.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(1);
});
it.each(['scope', 'session', 'generation', 'unmount', 'close', 'disable', 'binding'])('fences pending GET after acceptance storage failure on %s', async kind => {
 let finish!: (r: Response) => void, a = acceptance({ request_id: 'unused' });
 const set = Storage.prototype.setItem;
 const writes = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {
  if (key === KEY && JSON.parse(value).accepted) throw new DOMException('quota', 'QuotaExceededError');
  return set.call(this, key, value);
 });
 const v = setup(async (_u, o) => {
  if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: null }); }
  return new Promise<Response>(r => { finish = r; });
 });
 click('Open publication controls'); click('Publish graph'); await waitFor(() => expect(finish).toBeDefined());
 expect(screen.getByRole('status')).toHaveTextContent(/Acceptance storage\/readback failed/);
 const before = sessionStorage.getItem(KEY);
 if (kind === 'scope') v.rerender(<PublicationControls {...props} effectId="second" />);
 if (kind === 'session' || kind === 'generation') { v.api.session = { session_id: kind === 'session' ? 'two' : 'one', csrf_token: 'new', expires_at: 9999999999 }; runtime.current.session = v.api.session; v.rerender(<PublicationControls {...props} />); }
 if (kind === 'unmount') v.unmount();
 if (kind === 'close') click('Close publication controls');
 if (kind === 'disable') v.rerender(<PublicationControls {...props} enabled={false} />);
 if (kind === 'binding') v.rerender(<PublicationControls {...props} mutationEnabled={false} />);
 writes.mockRestore(); const s = state(a, 'verified'); s.receipt = receipt();
 await act(async () => finish(reply({ accepted: a, state: s })));
 expect(sessionStorage.getItem(KEY)).toBe(before); expect(v.fetcher).toHaveBeenCalledTimes(2);
 expect(screen.queryByText(/^Verified publication/)).toBeNull();
 if (['scope', 'session', 'generation'].includes(kind)) expect(screen.getByRole('status')).toHaveTextContent(/unchecked/i);
 if (kind === 'disable') { v.rerender(<PublicationControls {...props} />); expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled(); expect(screen.getByRole('button', { name: 'Retry exact request' })).toBeDisabled(); }
 if (kind === 'binding') {
  expect(screen.getByRole('status')).toHaveTextContent(/Accepted; current state unavailable.*Acceptance storage\/readback failed/);
  expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Retry exact request' })).toBeDisabled();
 }
});
it.each(['F', 'G', 'other'])('preserves mounted sibling %s changes while known-ACK persistence fails', async kind => {
 let a = acceptance({ request_id: 'unused' }), finish!: (r: Response) => void, reads = 0, failWrites = true;
 const set = Storage.prototype.setItem;
 vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {
  if (failWrites && key === KEY && JSON.parse(value).accepted) throw new DOMException('quota', 'QuotaExceededError');
  return set.call(this, key, value);
 });
 const v = setup(async (u, o) => {
  if (o?.method === 'POST') {
   if (u.endsWith('/renew') || u.includes('/second/')) throw Error('lost sibling ACK');
   a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: null });
  }
  if (++reads === 1) return new Promise<Response>(r => { finish = r; });
  return reply({ accepted: a, state: state(a, 'blocked_authorization') });
 });
 click('Open publication controls'); click('Publish graph'); await screen.findByText(/Acceptance storage\/readback failed/);
 const original = sessionStorage.getItem(KEY)!;
 failWrites = false;
 const sibling = render(<PublicationControls {...props} effectId={kind === 'other' ? 'second' : props.effectId} />), b = within(sibling.container), first = within(v.container);
 fireEvent.click(b.getByRole('button', { name: 'Open publication controls' }));
 if (kind === 'other') { fireEvent.click(b.getByRole('button', { name: 'Publish graph' })); await b.findByText(/Request unresolved/); }
 else { await b.findByText(/Blocked authorization; unsent/); if (kind === 'G') { fireEvent.click(b.getByRole('button', { name: 'Renew blocked unsent request' })); await b.findByText(/Request unresolved/); } }
 const before = { ...sessionStorage }; failWrites = true;
 const s = state(a, 'verified'); s.receipt = receipt();
 await act(async () => finish(reply({ accepted: a, state: s })));
 expect({ ...sessionStorage }).toEqual(before);
 expect(first.getByRole('button', { name: 'Retry exact request' })).toBeDisabled();
 if (kind === 'G') { await first.findByText(/Request ownership changed/); expect(first.queryByText(/^Verified publication/)).toBeNull(); }
 else { await first.findByText(/^Verified publication/); expect(first.getByRole('status')).toHaveTextContent(/Acceptance storage\/readback failed/); expect(first.getByRole('button', { name: 'Check disposition' })).toBeEnabled(); }
 if (kind === 'other') expect(sessionStorage.getItem(KEY)).toBe(original);
 expect(v.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(kind === 'F' ? 1 : 2);
});
it.each(['available', 'quota'])('remount recovers acceptance only from backend GET with %s storage', async kind => {
 let a = acceptance({ request_id: 'unused' }), readWorks = false;
 const set = Storage.prototype.setItem;
 const writes = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {
  if (key === KEY && JSON.parse(value).accepted) throw new DOMException('quota', 'QuotaExceededError');
  return set.call(this, key, value);
 });
 const v = setup(async (_u, o) => {
  if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: null }); }
  if (!readWorks) throw Error('unavailable');
  return reply({ accepted: a, state: null });
 });
 click('Open publication controls'); click('Publish graph'); await screen.findByText(/Acceptance storage\/readback failed/);
 const before = sessionStorage.getItem(KEY)!; v.unmount();
 if (kind === 'available') writes.mockRestore(); readWorks = true;
 render(<PublicationControls {...props} />); click('Open publication controls');
 expect(screen.getByRole('status')).toHaveTextContent(/unchecked/i);
 await screen.findByText(/Accepted; current state unavailable/);
 expect(screen.getByRole('button', { name: 'Retry exact request' })).toBeDisabled();
 expect(sessionStorage.getItem(KEY)).toBe(kind === 'quota' ? before : JSON.stringify({ ...JSON.parse(before), accepted: a }));
 expect(v.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(1);
});
it('late POST ACK cannot replace sibling G and still reports acceptance retention failure', async () => {
 let a = acceptance({ request_id: 'unused' }), finish!: (r: Response) => void, failWrites = false;
 const set = Storage.prototype.setItem;
 vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {
  if (failWrites && key === KEY && JSON.parse(value).accepted) throw new DOMException('quota', 'QuotaExceededError');
  return set.call(this, key, value);
 });
 const v = setup(async (u, o) => {
  if (u.endsWith('/renew')) throw Error('lost G ACK');
  if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); return new Promise<Response>(r => { finish = r; }); }
  return reply({ accepted: a, state: state(a, 'blocked_authorization') });
 });
 click('Open publication controls'); click('Publish graph');
 const sibling = render(<PublicationControls {...props} />), b = within(sibling.container), first = within(v.container);
 fireEvent.click(b.getByRole('button', { name: 'Open publication controls' })); await b.findByText(/Blocked authorization; unsent/);
 fireEvent.click(b.getByRole('button', { name: 'Renew blocked unsent request' })); await b.findByText(/Request unresolved/);
 const before = sessionStorage.getItem(KEY); failWrites = true;
 await act(async () => finish(reply({ accepted_new: true, accepted: a, state: null })));
 await first.findByText(/Request ownership changed/);
 expect(first.getByRole('status')).toHaveTextContent(/Acceptance storage\/readback failed/);
 expect(first.getByRole('button', { name: 'Retry exact request' })).toBeDisabled();
 expect(sessionStorage.getItem(KEY)).toBe(before); expect(v.fetcher).toHaveBeenCalledTimes(3);
});
it.each(['mounted', 'remount'])('switches known acceptance to GET-only when storage is revoked during GET (%s)', async kind => {
 let a = acceptance({ request_id: 'unused' }), revoke = false;
 if (kind === 'remount') { const { enabled: _enabled, ...scope } = props; sessionStorage.setItem(KEY, JSON.stringify({ session: 'one', scope, operation: 'write', body: { request_id: a.request_id } })); }
 const get = Storage.prototype.getItem;
 vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, key) { if (revoke) throw new DOMException('revoked', 'SecurityError'); return get.call(this, key); });
 const v = setup(async (_u, o) => {
  if (o?.method === 'POST') { a = acceptance(JSON.parse(String(o.body))); return reply({ accepted_new: true, accepted: a, state: null }); }
  revoke = true; return reply({ accepted: a, state: state(a, 'blocked_authorization') });
 });
 click('Open publication controls'); if (kind === 'mounted') click('Publish graph'); await screen.findByText(/Acceptance storage\/readback failed/);
 expect(screen.getByRole('status')).toHaveTextContent(/Blocked authorization; unsent/);
 expect(screen.getByRole('button', { name: 'Check disposition' })).toBeEnabled();
 expect(screen.getByRole('button', { name: 'Retry exact request' })).toBeDisabled();
 expect(screen.getByRole('button', { name: 'Renew blocked unsent request' })).toBeDisabled();
 click('Check disposition'); await waitFor(() => expect(v.fetcher).toHaveBeenCalledTimes(kind === 'mounted' ? 3 : 2));
 revoke = false; expect(JSON.parse(sessionStorage.getItem(KEY)!).accepted).toEqual(kind === 'mounted' ? a : undefined);
});
it('closed and disabled controls never request APIs or render execution inputs', () => {
 const v = setup(); expect(v.fetcher).not.toHaveBeenCalled();
 v.rerender(<PublicationControls {...props} enabled={false} />);
 expect(screen.getByRole('button', { name: 'Open publication controls' })).toBeDisabled();
 expect(v.container.querySelector('input')).toBeNull(); expect(v.fetcher).not.toHaveBeenCalled();
});
