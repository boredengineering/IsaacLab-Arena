import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import type { Job } from './contracts';
import { ResearchVersions } from './research-versions';
import { PublicationPanel } from './publication-panel';
import { StrictMode } from 'react';
import backendIdentity from './publication-backend.fixture.json';
const runtime = vi.hoisted(() => ({ current: {} as { api: ApiClient; session: { session_id: string } | null; status: string } }));
vi.mock('./runtime', () => ({ useRuntime: () => runtime.current }));
const id = 'a'.repeat(32), attempt = 'b'.repeat(32), res = 'c'.repeat(32), rev = 'd'.repeat(32), digest = 'e'.repeat(64);
const candidate: Job = { id, kind: 'generate', workspace_id: 'default', status: 'succeeded', stage: 'done', created_at: 1, updated_at: 1, created_by_session_id: 'one', inputs: {}, error: null, execution: { released: true, candidate_accepted: true, outcome: 'candidate_accepted' }, result: { yaml_text: 'env_name: Example', validation: { valid: true, spec: { env_name: 'Example' } } } };
const reference = { job_id: id, attempt_id: attempt, generation: 2, receipt_sha256: digest, request_sha256: digest };
const row = { reservation_id: res, revision_id: rev, version: 3, parent_revision_id: null, state: 'COMMITTED', source_job_id: id, manifest_digest: digest, publication_intent_id: null };
const commit = saved({ family: 'Example', idempotency_key: 'old' });
type Handler = (url: string, options?: RequestInit) => Promise<Response>;
const reply = (value: unknown) => new Response(JSON.stringify(value));
function setup(handler: Handler = async () => reply({ stores: [] }), job: Job | undefined = candidate, publicationExecution?: boolean) {
 const fetcher = vi.fn(handler), api = new ApiClient(fetcher as typeof fetch);
 api.session = { session_id: 'one', csrf_token: 'secret', expires_at: 9999999999 };
 runtime.current = { api, session: api.session, status: 'live' };
 const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
 const tree = () => <QueryClientProvider client={cache}><ResearchVersions candidate={job} publicationExecution={publicationExecution} /></QueryClientProvider>;
 const view = render(tree()); return { ...view, api, fetcher, cache, redraw: () => view.rerender(tree()), setCapability: (value: boolean) => { publicationExecution = value; view.rerender(tree()); } };
}
const open = () => fireEvent.click(screen.getByRole('button', { name: 'Open research versions' }));
const executionTarget = { profile_id: 'research', revision: 'f'.repeat(64), scope_ownership: 'cooperative_immutable' as const };
function executionCommit() {
 const reservation = { ...commit.reservation, registry_id: 'registry', publication_request: { effect_id: 'effect', target_profile: executionTarget } };
 return { ...commit, reservation, manifest: { ...commit.manifest, binding: reservation }, publication_intent_id: 'effect' };
}
const executionBinding = { storeId: 'local', effectId: 'effect', registryId: 'registry', target: executionTarget, versionRef: { reservation_id: res, revision_id: rev, version: 3, payload_sha256: digest, projection_digest: digest, scope_id: 'scope', database: backendIdentity.database, canonical_identity: backendIdentity.canonical_identity } };
async function executionBrowsing(url: string) {
 if (url.endsWith('/publication-binding')) return reply(executionBinding);
 if (url.endsWith(`/${res}`)) return reply(executionCommit());
 if (url.includes('/versions?')) { const data = await (await browsing(url)).json(); return reply({ ...data, versions: data.versions.map((v: typeof row) => v.reservation_id === res ? { ...v, publication_intent_id: 'effect' } : v) }); }
 return browsing(url);
}
async function selectPrepared() {
 await selectStore(); fireEvent.click(await screen.findByRole('button', { name: 'Select version 3' })); await screen.findByRole('link', { name: 'Download verified source' });
}
it.each(['available', 'quota', 'revoked'])('mounted acceptance survives binding failure with %s storage and only explicit disposition GET', async storage => {
 const { createHash } = await import('node:crypto');
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 let bindingFails = false, readFails = true, revoked = false, accepted: Record<string, unknown> = {};
 const set = Storage.prototype.setItem, get = Storage.prototype.getItem;
 const writes = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key, value) {
  if (key.startsWith('arena:publication:request:v2:') && JSON.parse(value).accepted && storage !== 'available') {
   revoked = storage === 'revoked'; throw new DOMException('storage unavailable', storage === 'quota' ? 'QuotaExceededError' : 'SecurityError');
  }
  return set.call(this, key, value);
 });
 const reads = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, key) { if (revoked) throw new DOMException('revoked', 'SecurityError'); return get.call(this, key); });
 const view = setup(async (url, o) => {
  if (url.endsWith('/publication-binding') && bindingFails) return new Response('{}', { status: 404 });
  if (o?.method === 'POST') {
   const b = { store_id: 'local', effect_id: 'effect', request_id: JSON.parse(String(o.body)).request_id, owner_session: 'one', principal: 'one', operation: 'write', previous_request_id: null };
   accepted = { schema_version: 1, registry_id: 'registry', ...b, request_digest: createHash('sha256').update(JSON.stringify(b, Object.keys(b).sort())).digest('hex'), attempt_id: 'attempt', generation: 1, capability: 'graph_write' };
   return reply({ accepted_new: true, accepted, state: null });
  }
  if (url.includes('/requests/')) {
   if (readFails) throw Error('unavailable');
   return reply({ accepted, state: { schema_version: 1, effect_id: 'effect', target_profile: executionTarget, payload_sha256: digest, state: 'blocked_authorization', cancelled: false, generation: 1, attempt_id: 'attempt', request_id: accepted.request_id, receipt: null, write_claim_count: 0, reconciliation: null, write_callback_open: false } });
  }
  return executionBrowsing(url);
 }, candidate, true);
 await selectPrepared(); fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByRole('region', { name: 'Publication controls' });
 fireEvent.click(screen.getByRole('button', { name: 'Open publication controls' }));
 fireEvent.click(screen.getByRole('button', { name: 'Publish graph' })); await screen.findByText(/Accepted; current state unavailable/);
 const controls = screen.getByRole('region', { name: 'Publication controls' }), before = { ...sessionStorage };
 const count = () => view.fetcher.mock.calls.filter(([u]) => u.includes('/publications/')).length;
 const initial = count(); bindingFails = true;
 fireEvent.click(screen.getByRole('button', { name: 'Revalidate publication binding' }));
 await screen.findByText(/Previously verified scope retained for disposition checking only/);
 expect(screen.getByRole('region', { name: 'Publication controls' })).toBe(controls);
 expect(screen.getByText(/Accepted; current state unavailable/)).toBeInTheDocument();
 expect(count()).toBe(initial); expect({ ...sessionStorage }).toEqual(before);
 for (const name of ['Publish graph', 'Retry exact request', 'Renew blocked unsent request', 'Reconcile read-only', 'Cancel current attempt']) expect(screen.getByRole('button', { name })).toBeDisabled();
 readFails = false; fireEvent.click(screen.getByRole('button', { name: 'Check disposition' }));
 await screen.findByText(/Blocked authorization; unsent/); expect(count()).toBe(initial + 1);
 bindingFails = false; fireEvent.click(screen.getByRole('button', { name: 'Revalidate publication binding' }));
 await waitFor(() => expect(screen.getByRole('button', { name: 'Revalidate publication binding' })).toBeEnabled());
 expect(screen.queryByText(/Previously verified scope retained/)).not.toBeInTheDocument();
 expect(screen.getByRole('button', { name: 'Renew blocked unsent request' }).hasAttribute('disabled')).toBe(storage !== 'available');
 expect(count()).toBe(initial + 1); expect(view.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(1);
 writes.mockRestore(); reads.mockRestore();
 // Closing retires memory. A fresh unavailable opening cannot adopt even these bytes.
 bindingFails = true; const persisted = { ...sessionStorage };
 fireEvent.click(screen.getByRole('button', { name: 'Close publication execution' }));
 fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByText(/Publication binding unavailable. Publication status unknown/);
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 expect(screen.queryByText(/Accepted; current state unavailable|Blocked authorization; unsent/)).not.toBeInTheDocument();
 expect({ ...sessionStorage }).toEqual(persisted); expect(count()).toBe(initial + 1);
});
it.each(['payload', 'target', 'malformed'])('binding revalidation conflict %s discards old scope instead of degrading', async kind => {
 let changed = false;
 const view = setup(async url => {
  if (changed && url.endsWith('/publication-binding')) {
   if (kind === 'malformed') return reply({ invalid: true });
   return reply({ ...executionBinding, ...(kind === 'target' ? { target: { ...executionTarget, revision: '1'.repeat(64) } } : { versionRef: { ...executionBinding.versionRef, payload_sha256: '1'.repeat(64) } }) });
  }
  return executionBrowsing(url);
 }, candidate, true);
 await selectPrepared(); fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByRole('region', { name: 'Publication controls' }); fireEvent.click(screen.getByRole('button', { name: 'Open publication controls' }));
 const before = { ...sessionStorage }; changed = true;
 fireEvent.click(screen.getByRole('button', { name: 'Revalidate publication binding' }));
 await waitFor(() => expect(screen.getByRole('button', { name: 'Revalidate publication binding' })).toBeEnabled());
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 expect(screen.queryByText(/Previously verified scope retained/)).not.toBeInTheDocument();
 expect({ ...sessionStorage }).toEqual(before);
 expect(view.fetcher.mock.calls.some(([u, o]) => u.includes('/publications/') || o?.method === 'POST')).toBe(false);
});
it('binding initial opening survives StrictMode effect cleanup', async () => {
 const view = setup(executionBrowsing, candidate, true); view.unmount();
 render(<StrictMode><PublicationPanel storeId="local" commit={executionCommit()} /></StrictMode>);
 fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByRole('region', { name: 'Publication controls' });
 expect(view.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
});
it.each(['manifest', 'reservation', 'revision', 'target', 'session', 'generation'])('panel retires the opening synchronously on immutable %s replacement', async boundary => {
 let fail = false;
 const setupView = setup(async url => fail && url.endsWith('/publication-binding') ? new Response('{}', { status: 404 }) : executionBrowsing(url)); setupView.unmount();
 const initial = executionCommit();
 const view = render(<PublicationPanel storeId="local" commit={initial} />);
 fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByRole('region', { name: 'Publication controls' }); fireEvent.click(screen.getByRole('button', { name: 'Open publication controls' }));
 const next = structuredClone(initial);
 if (boundary === 'manifest') next.manifest.digest = '1'.repeat(64);
 if (boundary === 'reservation') next.reservation.reservation_id = '1'.repeat(32);
 if (boundary === 'revision') next.reservation.revision_id = '1'.repeat(32);
 if (boundary === 'target') next.reservation.publication_request.target_profile.revision = '1'.repeat(64);
 if (boundary === 'session' || boundary === 'generation') { setupView.api.session = { ...setupView.api.session!, session_id: boundary === 'session' ? 'two' : 'one' }; runtime.current.session = setupView.api.session; }
 fail = true; const before = { ...sessionStorage };
 view.rerender(<PublicationPanel storeId="local" commit={next} />);
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 expect(screen.queryByText(/Previously verified scope retained/)).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByText(/Publication binding unavailable/);
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 expect({ ...sessionStorage }).toEqual(before);
 expect(setupView.fetcher.mock.calls.some(([u, o]) => u.includes('/publications/') || o?.method === 'POST')).toBe(false);
});
it.each(['selected-manifest', 'returned-manifest', 'returned-source'])('conflicting %s withholds old committed and publication state', async boundary => {
 let changed = false;
 const view = setup(async url => {
  if (changed && url.endsWith(`/${res}`)) {
   const next = executionCommit();
   if (boundary === 'returned-manifest') next.manifest.digest = '1'.repeat(64);
   if (boundary === 'returned-source') next.reservation.source = { ...reference, job_id: attempt };
   return reply(next);
  }
  return executionBrowsing(url);
 }, candidate, true);
 await selectPrepared(); fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByRole('region', { name: 'Publication controls' }); fireEvent.click(screen.getByRole('button', { name: 'Open publication controls' }));
 const before = { ...sessionStorage };
 if (boundary === 'selected-manifest') {
  act(() => view.cache.setQueriesData({ queryKey: ['research-versions'] }, { versions: [{ ...row, manifest_digest: '1'.repeat(64) }], latest: 3, next: null }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Next versions page' })).toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: 'Select version 3' }));
 } else {
  changed = true; await act(async () => { await view.cache.invalidateQueries({ queryKey: ['research-version'] }); });
  await screen.findByText('Version details could not be verified.');
 }
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 expect(screen.queryByRole('region', { name: 'Selected committed version' })).not.toBeInTheDocument();
 expect({ ...sessionStorage }).toEqual(before);
});
it('explicit execution open loads binding only, then mounts reviewed controls without graph access', async () => {
 let done!: (r: Response) => void;
 const view = setup(async url => url.endsWith('/publication-binding') ? new Promise<Response>(resolve => { done = resolve; }) : executionBrowsing(url), candidate, true);
 expect(view.fetcher).not.toHaveBeenCalled(); await selectPrepared();
 expect(view.fetcher.mock.calls.some(([u]) => u.endsWith('/publication-binding'))).toBe(false);
 fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByText('Loading verified publication binding…');
 expect(screen.getByRole('button', { name: 'Open publication controls' })).toBeDisabled();
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 await act(async () => done(reply(executionBinding)));
 fireEvent.click(await screen.findByRole('button', { name: 'Open publication controls' }));
 expect(screen.getByRole('button', { name: 'Publish graph' })).toBeEnabled();
 expect(screen.getByText(/Publication status unchecked/)).toBeInTheDocument();
 expect(view.fetcher.mock.calls.filter(([u]) => u.endsWith('/publication-binding'))).toHaveLength(1);
 expect(view.fetcher.mock.calls.some(([u, o]) => o?.method === 'POST' || /\/publications\/|\/graph/.test(u))).toBe(false);
 expect(sessionStorage.length).toBe(0);
});
it.each(['store', 'effect', 'registry', 'target', 'target-revision', 'ownership', 'reservation', 'revision', 'version', 'payload', 'projection', 'scope', 'database', 'canonical', 'extra'])('execution binding rejects %s mismatch before mounting any controls', async mismatch => {
 const binding = structuredClone(executionBinding);
 if (mismatch === 'store') binding.storeId = 'elsewhere';
 if (mismatch === 'effect') binding.effectId = 'other';
 if (mismatch === 'registry') binding.registryId = 'other';
 if (mismatch === 'target') binding.target.profile_id = 'other';
 if (mismatch === 'target-revision') binding.target.revision = '1'.repeat(64);
 if (mismatch === 'ownership') Object.assign(binding.target, { scope_ownership: 'mutable' });
 if (mismatch === 'reservation') binding.versionRef.reservation_id = id;
 if (mismatch === 'revision') binding.versionRef.revision_id = id;
 if (mismatch === 'version') binding.versionRef.version = 4;
 if (mismatch === 'payload') binding.versionRef.payload_sha256 = 'bad';
 if (mismatch === 'projection') binding.versionRef.projection_digest = 'bad';
 if (mismatch === 'scope') binding.versionRef.scope_id = '../bad';
 if (mismatch === 'database') binding.versionRef.database = '\u0085';
 if (mismatch === 'canonical') binding.versionRef.canonical_identity.sha256 = 'bad';
 if (mismatch === 'extra') Object.assign(binding, { state: 'verified' });
 const view = setup(async url => url.endsWith('/publication-binding') ? reply(binding) : executionBrowsing(url), candidate, true);
 await selectPrepared(); fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByText(/Publication binding unavailable. Publication status unknown; operator configuration required/);
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 expect(screen.getByRole('button', { name: 'Open publication controls' })).toBeDisabled();
 expect(view.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
});
it.each(['registry', 'source', 'version'])('execution never opens for a selected commit with mismatched %s evidence', async mismatch => {
 const c = structuredClone(executionCommit()); c.manifest.binding = structuredClone(c.manifest.binding);
 if (mismatch === 'registry') c.manifest.binding.registry_id = 'other';
 if (mismatch === 'source') { c.reservation.source.job_id = attempt; c.manifest.binding.source.job_id = attempt; }
 if (mismatch === 'version') { c.reservation.version = 4; c.manifest.binding.version = 4; c.relative_directory = 'final/Example/v4'; }
 const view = setup(async url => url.endsWith(`/${res}`) ? reply(c) : executionBrowsing(url), candidate, true);
 await selectStore(); fireEvent.click(await screen.findByRole('button', { name: 'Select version 3' }));
 await screen.findByText('Version details could not be verified.');
 expect(screen.queryByRole('button', { name: 'Open publication execution' })).not.toBeInTheDocument();
 expect(view.fetcher.mock.calls.some(([u]) => u.endsWith('/publication-binding'))).toBe(false);
});
it('execution binding is not refetched by activity in the same authenticated generation', async () => {
 const view = setup(executionBrowsing, candidate, true); await selectPrepared();
 fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByRole('region', { name: 'Publication controls' });
 runtime.current.session = { ...runtime.current.session! }; view.redraw(); await act(async () => {});
 expect(view.fetcher.mock.calls.filter(([u]) => u.endsWith('/publication-binding'))).toHaveLength(1);
});
it('execution open cannot fetch under a retired session before React has rerendered', async () => {
 const view = setup(executionBrowsing, candidate, true); await selectPrepared();
 view.api.session = { session_id: 'two', csrf_token: 'new', expires_at: 9999999999 };
 fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' })); await act(async () => {});
 expect(view.fetcher.mock.calls.some(([u]) => u.endsWith('/publication-binding'))).toBe(false);
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
});
it('execution preserves mounted controls during detail reverification but retires them on manifest conflict', async () => {
 let fail = false, done!: (r: Response) => void;
 const view = setup(async url => fail && url.endsWith(`/${res}`) ? new Promise<Response>(resolve => { done = resolve; }) : executionBrowsing(url), candidate, true);
 await selectPrepared(); fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 const controls = await screen.findByRole('region', { name: 'Publication controls' });
 fireEvent.click(screen.getByRole('button', { name: 'Open publication controls' }));
 fail = true; void view.cache.invalidateQueries({ queryKey: ['research-version'] });
 await waitFor(() => expect(done).toBeTypeOf('function'));
 expect(screen.getByRole('region', { name: 'Publication controls' })).toBe(controls);
 expect(screen.getByRole('button', { name: 'Publish graph' })).toBeDisabled();
 const conflicting = executionCommit(); conflicting.manifest.digest = 'f'.repeat(64);
 await act(async () => done(reply(conflicting)));
 await screen.findByText('Version details could not be verified.');
 expect(screen.queryByRole('button', { name: 'Open publication execution' })).not.toBeInTheDocument();
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
});
it.each([409, 500, 503])('unavailable details (%s) preserve mounted scope without restoring mutation authority until explicit revalidation', async status => {
 let fail = false;
 const view = setup(async url => fail && url.endsWith(`/${res}`) ? new Response(JSON.stringify({ detail: 'Research version unavailable' }), { status }) : executionBrowsing(url), candidate, true);
 await selectPrepared(); fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 const controls = await screen.findByRole('region', { name: 'Publication controls' }); fireEvent.click(screen.getByRole('button', { name: 'Open publication controls' }));
 fail = true; await act(async () => { await view.cache.invalidateQueries({ queryKey: ['research-version'] }); });
 await screen.findByText('Version details could not be verified.');
 expect(screen.getByRole('region', { name: 'Publication controls' })).toBe(controls);
 expect(screen.getByRole('button', { name: 'Publish graph' })).toBeDisabled();
 expect(screen.getByRole('button', { name: 'Revalidate publication binding' })).toBeDisabled();
 fail = false; fireEvent.click(screen.getByRole('button', { name: 'Retry version details' }));
 await waitFor(() => expect(screen.queryByText('Version details could not be verified.')).not.toBeInTheDocument());
 expect(screen.getByRole('region', { name: 'Publication controls' })).toBe(controls);
 expect(screen.getByRole('button', { name: 'Publish graph' })).toBeDisabled();
 expect(view.fetcher.mock.calls.filter(([u]) => u.endsWith('/publication-binding'))).toHaveLength(1);
 fireEvent.click(screen.getByRole('button', { name: 'Revalidate publication binding' }));
 await waitFor(() => expect(screen.getByRole('button', { name: 'Publish graph' })).toBeEnabled());
 expect(view.fetcher.mock.calls.some(([u, o]) => u.includes('/publications/') || o?.method === 'POST')).toBe(false);
});
it('capability disable and re-enable cannot adopt a retired opening response', async () => {
 const completions: ((r: Response) => void)[] = [];
 const view = setup(async url => url.endsWith('/publication-binding') ? new Promise<Response>(resolve => completions.push(resolve)) : executionBrowsing(url), candidate, true);
 await selectPrepared(); fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByText('Loading verified publication binding…');
 view.setCapability(false);
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 await act(async () => completions[0](reply(executionBinding)));
 view.setCapability(true);
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 expect(completions).toHaveLength(1);
 fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await waitFor(() => expect(completions).toHaveLength(2));
 await act(async () => completions[1](reply(executionBinding)));
 await screen.findByRole('region', { name: 'Publication controls' });
 expect(view.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
});

it.each([undefined, false, true])('execution capability %s never discovers bindings for an unprepared version', async capability => {
 const view = setup(browsing, candidate, capability); await selectPrepared();
 expect(screen.queryByRole('button', { name: 'Open publication execution' })).not.toBeInTheDocument();
 expect(view.fetcher.mock.calls.some(([u]) => /publication-binding|publication-profiles|\/publications\//.test(u))).toBe(false);
});
it.each([undefined, false])('execution capability %s keeps prepared versions view-only', async capability => {
 const view = setup(executionBrowsing, candidate, capability); await selectPrepared();
 expect(screen.queryByRole('button', { name: 'Open publication execution' })).not.toBeInTheDocument();
 expect(view.fetcher.mock.calls.some(([u]) => /publication-binding|publication-profiles|\/publications\//.test(u))).toBe(false);
});
it.each([403, 404, 409, 500, 'network', 'invalid'])('execution binding unavailable (%s) never falls back to storage or a publication claim', async error => {
 const retained = { session: 'one', scope: executionBinding, operation: 'write', body: { request_id: 'old' } };
 const key = 'arena:publication:request:v2:' + JSON.stringify(['registry', 'local', 'effect', res, rev, 3]);
 sessionStorage.setItem(key, JSON.stringify(retained)); const before = sessionStorage.getItem(key);
 const view = setup(async url => {
  if (url.endsWith('/publication-binding')) {
   if (error === 'network') throw Error('private-error');
   return error === 'invalid' ? reply({ ...executionBinding, state: 'verified' }) : new Response(JSON.stringify({ detail: 'private-error' }), { status: Number(error) });
  }
  return executionBrowsing(url);
 }, candidate, true);
 await selectPrepared(); fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByText(/Publication binding unavailable. Publication status unknown; operator configuration required/);
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 expect(screen.queryByText(/private-error/)).not.toBeInTheDocument();
 expect(view.fetcher.mock.calls.some(([u, o]) => /\/publications\//.test(u) || o?.method === 'POST')).toBe(false);
 expect(sessionStorage.getItem(key)).toBe(before);
});
it.each(['close', 'browser-close', 'family', 'store', 'page', 'session', 'generation', 'expired'])('execution ignores a late binding after %s', async boundary => {
 let done!: (r: Response) => void;
 const view = setup(async url => url.endsWith('/publication-binding') ? new Promise<Response>(resolve => { done = resolve; }) : executionBrowsing(url), candidate, true);
 await selectPrepared(); fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByText('Loading verified publication binding…');
 if (boundary === 'close') fireEvent.click(screen.getByRole('button', { name: 'Close publication execution' }));
 if (boundary === 'browser-close') fireEvent.click(screen.getByRole('button', { name: 'Close research versions' }));
 if (boundary === 'family') fireEvent.change(screen.getByLabelText('Research family'), { target: { value: 'Other' } });
 if (boundary === 'store') fireEvent.change(screen.getByLabelText('Research store'), { target: { value: '' } });
 if (boundary === 'page') fireEvent.click(screen.getByRole('button', { name: 'Next versions page' }));
 if (boundary === 'session' || boundary === 'generation') { view.api.session = { ...view.api.session!, session_id: boundary === 'session' ? 'two' : 'one' }; runtime.current.session = view.api.session; view.redraw(); }
 if (boundary === 'expired') { runtime.current.status = 'expired'; view.redraw(); }
 await act(async () => done(reply(executionBinding)));
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 expect(view.fetcher.mock.calls.filter(([u]) => u.endsWith('/publication-binding'))).toHaveLength(1);
 expect(view.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
});
it('execution close and reopen cannot adopt the prior opening response', async () => {
 const completions: ((r: Response) => void)[] = [];
 const view = setup(async url => url.endsWith('/publication-binding') ? new Promise<Response>(resolve => { completions.push(resolve); }) : executionBrowsing(url), candidate, true);
 await selectPrepared(); fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByText('Loading verified publication binding…');
 fireEvent.click(screen.getByRole('button', { name: 'Close publication execution' }));
 fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 expect(completions).toHaveLength(2);
 await act(async () => completions[0](reply(executionBinding)));
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 await act(async () => completions[1](reply(executionBinding)));
 await screen.findByRole('region', { name: 'Publication controls' });
 expect(view.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
});
it('execution close preserves an exact retained request without checking it or adopting it in another session', async () => {
 const retained = { session: 'one', scope: executionBinding, operation: 'write', body: { request_id: 'old' } };
 const key = 'arena:publication:request:v2:' + JSON.stringify(['registry', 'local', 'effect', res, rev, 3]);
 sessionStorage.setItem(key, JSON.stringify(retained)); const before = sessionStorage.getItem(key);
 const view = setup(executionBrowsing, candidate, true); await selectPrepared();
 fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' })); await screen.findByRole('region', { name: 'Publication controls' });
 fireEvent.click(screen.getByRole('button', { name: 'Close publication execution' }));
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 expect(sessionStorage.getItem(key)).toBe(before);
 view.api.session = { session_id: 'two', csrf_token: 'new', expires_at: 9999999999 }; runtime.current.session = view.api.session; view.redraw();
 await selectPrepared(); fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByText(/Cross-session publication recovery is unsupported/);
 expect(screen.getByRole('button', { name: 'Open publication controls' })).toBeDisabled();
 expect(sessionStorage.getItem(key)).toBe(before);
 expect(view.fetcher.mock.calls.some(([u, o]) => /\/publications\//.test(u) || o?.method === 'POST')).toBe(false);
});
it('execution binds the selected older version, not latest, and retires its pending response on selection change', async () => {
 let done!: (r: Response) => void;
 const next = structuredClone(executionCommit());
 next.reservation.reservation_id = '1'.repeat(32); next.reservation.revision_id = '2'.repeat(32); next.reservation.version = 4;
 next.relative_directory = 'final/Example/v4';
 const view = setup(async url => {
  if (url.endsWith(`/${res}/publication-binding`)) return new Promise<Response>(resolve => { done = resolve; });
  if (url.includes('?')) return reply({ versions: [row, { ...row, reservation_id: next.reservation.reservation_id, revision_id: next.reservation.revision_id, version: 4 }], latest_version: 4, next_after_version: null });
  if (url.endsWith(`/${next.reservation.reservation_id}`)) return reply(next);
  return executionBrowsing(url);
 }, candidate, true);
 await selectPrepared(); expect(screen.getByText('Latest committed version: 4')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' })); await screen.findByText('Loading verified publication binding…');
 expect(view.fetcher.mock.calls.filter(([u]) => u.endsWith('/publication-binding')).map(([u]) => u)).toEqual([`/api/research/stores/local/versions/${res}/publication-binding`]);
 fireEvent.click(screen.getByRole('button', { name: 'Select version 4' })); await screen.findByRole('link', { name: 'Download verified source' });
 await act(async () => done(reply(executionBinding)));
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 expect(screen.getByRole('button', { name: 'Open publication execution' })).toHaveAttribute('aria-expanded', 'false');
 expect(view.fetcher.mock.calls.filter(([u]) => u.endsWith('/publication-binding'))).toHaveLength(1);
});
it('execution binding HTTP 401 retires authenticated controls and preserves retained bytes', async () => {
 const view = setup(async url => url.endsWith('/publication-binding') ? new Response('{}', { status: 401 }) : executionBrowsing(url), candidate, true);
 view.api.onExpired = () => { runtime.current.session = null; runtime.current.status = 'expired'; view.redraw(); };
 sessionStorage.setItem('arena:publication:request:v2:unresolved', 'unchanged');
 await selectPrepared(); fireEvent.click(screen.getByRole('button', { name: 'Open publication execution' }));
 await screen.findByText('Connect a session to browse research versions.');
 expect(screen.queryByRole('region', { name: 'Publication controls' })).not.toBeInTheDocument();
 expect(sessionStorage.getItem('arena:publication:request:v2:unresolved')).toBe('unchanged');
 expect(view.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
});
async function browsing(url: string) {
 if (url.endsWith('/stores')) return reply({ stores: [{ store_id: 'local', available: true, message: 'ready' }, { store_id: 'offline', available: false, message: '<img src=x>' }] });
 if (url.includes('/candidates/')) return reply(reference);
 if (url.includes('?')) return reply({ versions: [row], next_after_version: url.includes('after_version=0') ? 3 : null, latest_version: 3 });
 return reply(commit);
}
async function selectStore() { open(); await screen.findByRole('option', { name: 'local' }); fireEvent.change(screen.getByLabelText('Research store'), { target: { value: 'local' } }); }
it('browses bounded committed pages with explicit detail selection and safe attachment URLs', async () => {
 const view = setup(browsing); await selectStore();
 expect(await screen.findByText('Latest committed version: 3')).toBeInTheDocument();
 expect(screen.getByRole('option', { name: 'offline — unavailable' })).toBeDisabled();
 expect(screen.queryByRole('link')).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', { name: 'Select version 3' }));
 expect(await screen.findByRole('link', { name: 'Download verified source' })).toHaveAttribute('href', `/api/research/stores/local/versions/${res}/artifacts/environment.yaml`);
 expect(screen.getByText('<script>hostile</script>')).toBeInTheDocument(); expect(view.container.querySelector('script,img')).toBeNull();
 fireEvent.click(screen.getByRole('button', { name: 'Next versions page' }));
 await waitFor(() => expect(view.fetcher.mock.calls.some(([url]) => url.includes('after_version=3&limit=25'))).toBe(true));
 expect(screen.queryByRole('link')).not.toBeInTheDocument();
});
function saved(body: Record<string, unknown>) { const reservation = { reservation_id: res, revision_id: rev, version: 3, store_id: 'local', family: body.family, workflow_id: body.idempotency_key, source: reference, parent_revision_id: body.parent_revision_id ?? null }; return { reservation, manifest: { digest, binding: reservation, note: '<script>hostile</script>' }, relative_directory: 'final/Example/v3', publication_intent_id: null }; }
it('confirmation freezes exact candidate tuple and explicit parent then verifies exact readback', async () => {
 let body: Record<string, unknown> = {}; vi.spyOn(window, 'confirm').mockReturnValue(true);
 const view = setup(async (url, opts) => { if (opts?.method === 'POST') { body = JSON.parse(String(opts.body)); return reply(saved(body)); } if (url.endsWith(`/${res}`)) return reply(saved(Object.keys(body).length ? body : { family: 'Example', idempotency_key: 'old' })); return browsing(url); });
 await selectStore(); await screen.findByRole('button', { name: 'Select version 3' });
 await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled());
 expect(screen.getByLabelText('Parent revision')).toHaveValue('');
 fireEvent.click(screen.getByRole('button', { name: 'Select version 3' })); await screen.findByRole('link');
 fireEvent.change(screen.getByLabelText('Parent revision'), { target: { value: rev } });
 fireEvent.click(screen.getByRole('button', { name: 'Save research version' }));
 await screen.findByText('Research version saved and verified. Graph publication was not performed.');
 expect(body).toEqual({ idempotency_key: expect.any(String), family: 'Example', source_job_id: id, source_attempt_id: attempt, source_generation: 2, parent_revision_id: rev });
 expect(view.fetcher.mock.calls.filter(([, opts]) => opts?.method === 'POST')).toHaveLength(1);
 expect(sessionStorage.length).toBe(0);
});
it('does not retain unexpected candidate fields or upload source YAML', async () => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 const view = setup(async (url, opts) => opts?.method === 'POST' ? Promise.reject(new Error('lost')) : url.includes('/candidates/') ? reply({ ...reference, csrf_token: 'do-not-retain', yaml_text: 'do-not-retain' }) : browsing(url));
 await selectStore(); await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled()); fireEvent.click(screen.getByRole('button', { name: 'Save research version' }));
 await screen.findByText(/Save unresolved/);
 expect(sessionStorage.getItem(sessionStorage.key(0)!)).not.toContain('do-not-retain');
 expect(view.fetcher.mock.calls.find(([, o]) => o?.method === 'POST')?.[1]?.body).not.toContain('yaml');
});
it('replays the identical frozen payload after unmount and candidate replacement, without autodispatch', async () => {
 vi.spyOn(window, 'confirm').mockReturnValue(true); let body: Record<string, unknown> = {};
 const first = setup(async (url, opts) => { if (opts?.method === 'POST') { body = JSON.parse(String(opts.body)); throw new Error('lost'); } return browsing(url); });
 await selectStore(); await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled()); fireEvent.click(screen.getByRole('button', { name: 'Save research version' })); await screen.findByText(/Save unresolved/);
 expect(body).not.toHaveProperty('parent_revision_id'); first.unmount();
 const second = setup(async (url, opts) => opts?.method === 'POST' || url.endsWith(`/${res}`) ? reply(saved(body)) : browsing(url), { ...candidate, id: 'f'.repeat(32), result: { ...candidate.result, validation: { valid: true, spec: { env_name: 'Changed' } } } });
 expect(second.fetcher).not.toHaveBeenCalled(); open(); await screen.findByRole('button', { name: 'Retry exact research save' });
 expect(screen.getByLabelText('Research family')).toHaveValue('Example'); expect(screen.getByLabelText('Research store')).toHaveValue('local'); expect(screen.getByLabelText('Research family')).toBeDisabled();
 expect(second.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
 fireEvent.click(screen.getByRole('button', { name: 'Retry exact research save' })); await screen.findByText(/Research version saved and verified/);
 expect(second.fetcher.mock.calls.find(([, o]) => o?.method === 'POST')?.[1]?.body).toBe(JSON.stringify(body));
});
it.each(['returned', 'readback'])('retains unresolved payload on %s identity mismatch', async mismatch => {
 vi.spyOn(window, 'confirm').mockReturnValue(true); let body: Record<string, unknown> = {};
 setup(async (url, opts) => { if (opts?.method === 'POST') { body = JSON.parse(String(opts.body)); const c = saved(body); if (mismatch === 'returned') c.reservation.source = { ...reference, attempt_id: res }; return reply(c); } if (url.endsWith(`/${res}`)) { const c = saved(body); c.reservation.revision_id = id; return reply(c); } return browsing(url); });
 await selectStore(); await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled()); fireEvent.click(screen.getByRole('button', { name: 'Save research version' })); await screen.findByText(/Save unresolved/);
 expect(sessionStorage.length).toBe(1); expect(screen.queryByText(/Research version saved and verified/)).not.toBeInTheDocument();
});
it.each(['unmount', 'session'])('ignores late mutation completion after %s and retains the frozen request', async boundary => {
 vi.spyOn(window, 'confirm').mockReturnValue(true); let done!: (r: Response) => void, body: Record<string, unknown> = {};
 const view = setup(async (url, opts) => { if (opts?.method === 'POST') { body = JSON.parse(String(opts.body)); return new Promise<Response>(r => { done = r; }); } return browsing(url); });
 await selectStore(); await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled()); fireEvent.click(screen.getByRole('button', { name: 'Save research version' }));
 if (boundary === 'unmount') view.unmount(); else { view.api.session = { session_id: 'two', csrf_token: 'next', expires_at: 9999999999 }; runtime.current.session = view.api.session; view.redraw(); }
 const count = view.fetcher.mock.calls.length; await act(async () => done(reply(saved(body))));
 expect(view.fetcher).toHaveBeenCalledTimes(count); expect(sessionStorage.length).toBe(1); expect(screen.queryByText(/Research version saved and verified/)).not.toBeInTheDocument();
 if (boundary === 'session') { open(); expect(screen.getByRole('button', { name: 'Retry exact research save' })).toBeDisabled(); }
});
it('shows reserved entries without treating reserved numbers as latest committed or selectable parents', async () => {
 setup(async url => url.includes('?') ? reply({ versions: [{ ...row, state: 'committed' }, { ...row, reservation_id: id, revision_id: attempt, state: 'reserved', version: 4, manifest_digest: null }], latest_version: 3, next_after_version: null }) : browsing(url));
 await selectStore(); await screen.findByText('Latest committed version: 3');
 expect(screen.getByText('Version 4 — reserved, not committed')).toBeInTheDocument();
 expect(screen.queryByRole('button', { name: 'Select version 4' })).not.toBeInTheDocument();
});
it.each(['legacy', 'failed', 'running', 'invalid', 'malformed'])('withholds candidate requests for %s jobs', async kind => {
 const job = { ...candidate, ...(kind === 'legacy' ? { execution: undefined } : kind === 'invalid' ? { result: { yaml_text: 'x', validation: { valid: false, spec: { env_name: 'Example' } } } } : kind === 'malformed' ? { execution: { ...candidate.execution!, released: false } } : { status: kind as Job['status'] }) };
 const view = setup(browsing, job); await selectStore(); await screen.findByText('Latest committed version: 3');
 expect(screen.getByRole('button', { name: 'Save research version' })).toBeDisabled(); expect(view.fetcher.mock.calls.some(([url]) => url.includes('/candidates/'))).toBe(false);
});
it('accepts preserved cancelled candidates but cancellation of confirmation writes nothing', async () => {
 vi.spyOn(window, 'confirm').mockReturnValue(false); const view = setup(browsing, { ...candidate, status: 'cancelled' }); await selectStore();
 await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled()); fireEvent.click(screen.getByRole('button', { name: 'Save research version' }));
 expect(sessionStorage.length).toBe(0); expect(view.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
});
it('does not repair invalid source family names and permits explicit valid entry', async () => {
 const view = setup(browsing, { ...candidate, result: { ...candidate.result, validation: { valid: true, spec: { env_name: ' bad/name ' } } } }); await selectStore();
 expect(screen.getByLabelText('Research family')).toHaveValue(''); expect(view.fetcher.mock.calls.some(([url]) => url.includes('/candidates/'))).toBe(false);
 fireEvent.change(screen.getByLabelText('Research family'), { target: { value: 'Explicit' } }); await screen.findByText('Latest committed version: 3');
 expect(view.fetcher.mock.calls.some(([url]) => url.includes('family=Explicit'))).toBe(true);
});
it('does not display a late private query after session replacement or reopen automatically', async () => {
 let done!: (r: Response) => void; const view = setup(async () => new Promise<Response>(r => { done = r; })); open();
 view.api.session = { session_id: 'two', csrf_token: 'next', expires_at: 9999999999 }; runtime.current.session = view.api.session; view.redraw();
 await act(async () => done(reply({ stores: [{ store_id: 'private', available: true }] })));
 expect(screen.queryByRole('option', { name: 'private' })).not.toBeInTheDocument(); expect(view.fetcher).toHaveBeenCalledTimes(1);
 expect(screen.getByRole('button', { name: 'Open research versions' })).toBeInTheDocument();
});
it('rejects hostile identifiers and oversize pages with static errors', async () => {
 const view = setup(async url => url.endsWith('/stores') ? reply({ stores: [{ store_id: '../<img src=x>', available: true }] }) : browsing(url)); open();
 await screen.findByText('Research stores unavailable.'); expect(view.container.querySelector('img')).toBeNull(); expect(view.fetcher).toHaveBeenCalledTimes(1);
});
it('bounds manifest properties and refuses a mismatched manifest source binding', async () => {
 setup(async url => url.endsWith(`/${res}`) ? reply({ ...commit, manifest: { ...commit.manifest, binding: { ...commit.reservation, source: { ...reference, attempt_id: res } } } }) : browsing(url));
 await selectStore(); fireEvent.click(await screen.findByRole('button', { name: 'Select version 3' })); await screen.findByText('Version details could not be verified.'); expect(screen.queryByRole('link')).not.toBeInTheDocument();
});
it('bounds long manifest text and large property counts without whole-tree serialization', async () => {
 const view = setup(async url => url.endsWith(`/${res}`) ? reply({ ...commit, manifest: { ...commit.manifest, ...Object.fromEntries(Array.from({ length: 250 }, (_, i) => [`property-${i}`, 'x'.repeat(5000)])) } }) : browsing(url));
 await selectStore(); fireEvent.click(await screen.findByRole('button', { name: 'Select version 3' })); await screen.findByRole('link');
 expect(view.container.querySelectorAll('[data-property-row]').length).toBeLessThanOrEqual(120);
 expect(screen.queryByText('property-100')).not.toBeInTheDocument(); expect(Array.from(view.container.querySelectorAll('pre')).every(p => p.textContent!.length <= 1024)).toBe(true);
});
it.each([null, { versions: Array.from({ length: 26 }, () => row), latest_version: 3, next_after_version: null }, { versions: [null], latest_version: 3, next_after_version: null }])('rejects malformed or over-limit pages', async page => {
 setup(async url => url.includes('?') ? reply(page) : browsing(url)); await selectStore(); await screen.findByText('Versions unavailable.'); expect(screen.queryByRole('button', { name: 'Select version 3' })).not.toBeInTheDocument();
});
it('never turns untrusted artifact paths into a download URL', async () => {
 setup(async url => url.endsWith(`/${res}`) ? reply({ ...commit, relative_directory: 'javascript:alert(1)', download_url: 'https://evil.test' }) : browsing(url));
 await selectStore(); fireEvent.click(await screen.findByRole('button', { name: 'Select version 3' })); await screen.findByText('Version details could not be verified.'); expect(screen.queryByRole('link')).not.toBeInTheDocument();
});
it('withholds late family details and resets explicitly chosen parent when family changes', async () => {
 let done!: (r: Response) => void;
 setup(async url => url.endsWith(`/${res}`) ? new Promise<Response>(r => { done = r; }) : browsing(url));
 await selectStore(); fireEvent.click(await screen.findByRole('button', { name: 'Select version 3' }));
 fireEvent.change(screen.getByLabelText('Research family'), { target: { value: 'Other' } }); await act(async () => done(reply(commit)));
 expect(screen.queryByRole('link')).not.toBeInTheDocument(); expect(screen.getByLabelText('Parent revision')).toHaveValue('');
});
it('blocks persistence when tab storage is unavailable', async () => {
 vi.spyOn(window, 'confirm').mockReturnValue(true); vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('secret failure'); });
 const view = setup(browsing); await selectStore(); await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled()); fireEvent.click(screen.getByRole('button', { name: 'Save research version' }));
 await screen.findByText(/Retained request storage is unavailable/); expect(view.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false); expect(screen.queryByText('secret failure')).not.toBeInTheDocument();
});
it('recovers a lost save only after confirmation in S2, preserving parent and exact frozen source', async () => {
 const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
 const newId = vi.spyOn(crypto, 'randomUUID');
 let body: Record<string, unknown> = {}, posts = 0;
 const newCommit = () => { const c = saved(body); c.reservation.version = 4; c.reservation.reservation_id = '1'.repeat(32); c.reservation.revision_id = '2'.repeat(32); c.relative_directory = 'final/Example/v4'; return c; };
 const view = setup(async (url, opts) => {
  if (opts?.method === 'POST') { posts++; body = JSON.parse(String(opts.body)); if (posts === 1) throw new Error('lost'); return reply(newCommit()); }
  if (url.endsWith(`/${'1'.repeat(32)}`)) return reply(newCommit());
  if (url.includes('?') && posts === 2) return reply({ versions: [{ ...row, ...newCommit().reservation }], latest_version: 4, next_after_version: null });
  if (url.endsWith(`/${res}`)) return reply(saved(Object.keys(body).length ? body : { family: 'Example', idempotency_key: 'old' }));
  return browsing(url);
 });
 await selectStore(); fireEvent.click(await screen.findByRole('button', { name: 'Select version 3' })); await screen.findByRole('link');
 fireEvent.change(screen.getByLabelText('Parent revision'), { target: { value: rev } });
 await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled());
 fireEvent.click(screen.getByRole('button', { name: 'Save research version' })); await screen.findByText(/Save unresolved/);
 const key = sessionStorage.key(0)!, original = sessionStorage.getItem(key)!, frozen = JSON.parse(original);
 view.api.session = { session_id: 'two', csrf_token: 'next', expires_at: 9999999999 }; runtime.current.session = view.api.session; view.redraw(); open();
 const recover = await screen.findByRole('button', { name: 'Recover exact research save in this session' });
 expect(posts).toBe(1); expect(sessionStorage.getItem(key)).toBe(original);
 confirm.mockReturnValue(false); fireEvent.click(recover);
 expect(posts).toBe(1); expect(sessionStorage.getItem(key)).toBe(original); expect(screen.getByRole('button', { name: 'Retry exact research save' })).toBeDisabled();
 expect(confirm.mock.lastCall?.[0]).toContain('single_operator_workspace');
 for (const exact of [id, attempt, 'generation 2', 'local/Example']) expect(confirm.mock.lastCall?.[0]).toContain(exact);
 confirm.mockReturnValue(true); fireEvent.click(recover);
 expect(JSON.parse(sessionStorage.getItem(key)!)).toEqual({ ...frozen, session: 'two' }); expect(posts).toBe(1);
 await waitFor(() => expect(screen.getByLabelText('Research store')).toHaveValue('local'));
 expect(screen.getByLabelText('Research family')).toHaveValue('Example'); expect(screen.getByLabelText('Parent revision')).toHaveValue(rev);
 confirm.mockReturnValue(false); fireEvent.click(screen.getByRole('button', { name: 'Retry exact research save' })); expect(posts).toBe(1);
 confirm.mockReturnValue(true); fireEvent.click(screen.getByRole('button', { name: 'Retry exact research save' })); await screen.findByText(/Research version saved and verified/);
 expect(posts).toBe(2); expect(body).toEqual(frozen.body); expect(frozen.source).toEqual(reference); expect(body.parent_revision_id).toBe(rev);
 expect(newId).toHaveBeenCalledTimes(1);
 expect(view.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST').map(([, o]) => o!.body)).toEqual([JSON.stringify(body), JSON.stringify(body)]);
 await screen.findByText('Latest committed version: 4'); expect(screen.getByRole('button', { name: 'Select version 4' })).toBeInTheDocument();
});
it.each(['matching', 'mismatch'])('refreshes only the saved listing after verified GET: %s', async outcome => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 let body: Record<string, unknown> = {}, done!: (r: Response) => void, verified = false;
 const view = setup(async (url, opts) => {
  if (opts?.method === 'POST') { body = JSON.parse(String(opts.body)); return reply(saved(body)); }
  if (url.endsWith(`/${res}`)) return new Promise<Response>(r => { done = r; });
  if (url.includes('?')) return reply({ versions: verified ? [row] : [], latest_version: verified ? 3 : null, next_after_version: null });
  return browsing(url);
 });
 const invalidate = vi.spyOn(view.cache, 'invalidateQueries');
 const epoch = view.api.sessionGeneration;
 const capturedPages = [25, 50].map(page => ['research-versions', 'one', epoch, 'local', 'Example', page]);
 const neighbors = [
  ['research-versions', 'two', epoch, 'local', 'Example', 0],
  ['research-versions', 'one', epoch + 1, 'local', 'Example', 0],
  ['research-versions', 'one', epoch, 'other-store', 'Example', 0],
  ['research-versions', 'one', epoch, 'local', 'OtherFamily', 0],
  ['research-version', 'one', epoch, 'local', 'Example', res],
 ];
 for (const key of [...capturedPages, ...neighbors]) view.cache.setQueryData(key, { versions: [row], latest: 3, next: null });
 await selectStore(); await screen.findByText('Latest committed version: none');
 await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled());
 fireEvent.click(screen.getByRole('button', { name: 'Save research version' })); await waitFor(() => expect(done).toBeTypeOf('function'));
 expect(invalidate).not.toHaveBeenCalled(); expect(view.fetcher.mock.calls.filter(([u]) => u.includes('?'))).toHaveLength(1);
 verified = true; const result = saved(body); if (outcome === 'mismatch') result.manifest.digest = 'f'.repeat(64);
 await act(async () => done(reply(result)));
 if (outcome === 'matching') {
  await screen.findByText('Latest committed version: 3'); expect(screen.getByRole('button', { name: 'Select version 3' })).toBeInTheDocument();
  expect(invalidate).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ['research-versions', 'one', view.api.sessionGeneration, 'local', 'Example'] }));
  expect(view.fetcher.mock.calls.filter(([u]) => u.includes('?'))).toHaveLength(2);
 } else {
  await screen.findByText(/Save unresolved/); expect(invalidate).not.toHaveBeenCalled(); expect(view.fetcher.mock.calls.filter(([u]) => u.includes('?'))).toHaveLength(1);
 }
 for (const key of capturedPages) expect(view.cache.getQueryState(key)?.isInvalidated).toBe(outcome === 'matching');
 for (const key of neighbors) {
  expect(view.cache.getQueryState(key)?.isInvalidated).toBe(false);
  expect(view.cache.getQueryData(key)).toEqual({ versions: [row], latest: 3, next: null });
 }
});
it.each(['POST', 'GET'])('fences old S1 late %s after S2 confirmed recovery without clearing or refreshing new state', async phase => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 let body: Record<string, unknown> = {}, done!: (r: Response) => void;
 const view = setup(async (url, opts) => {
  if (opts?.method === 'POST') {
   body = JSON.parse(String(opts.body));
   if (runtime.current.api.session?.session_id === 'two') throw new Error('S2 unresolved');
   if (phase === 'POST') return new Promise<Response>(r => { done = r; });
   return reply(saved(body));
  }
  if (url.endsWith(`/${res}`)) return new Promise<Response>(r => { done = r; });
  return browsing(url);
 });
 const invalidate = vi.spyOn(view.cache, 'invalidateQueries');
 await selectStore(); await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled());
 fireEvent.click(screen.getByRole('button', { name: 'Save research version' })); await waitFor(() => expect(done).toBeTypeOf('function'));
 view.api.session = { session_id: 'two', csrf_token: 'next', expires_at: 9999999999 }; runtime.current.session = view.api.session; view.redraw(); open();
 fireEvent.click(await screen.findByRole('button', { name: 'Recover exact research save in this session' }));
 fireEvent.click(screen.getByRole('button', { name: 'Retry exact research save' })); await screen.findByText(/Save unresolved/); await screen.findByText('Latest committed version: 3');
 const retained = sessionStorage.getItem(sessionStorage.key(0)!)!, count = view.fetcher.mock.calls.length;
 await act(async () => done(reply(saved(body))));
 expect(sessionStorage.getItem(sessionStorage.key(0)!)).toBe(retained); expect(JSON.parse(retained).session).toBe('two');
 expect(invalidate).not.toHaveBeenCalled(); expect(view.fetcher).toHaveBeenCalledTimes(count); expect(screen.getByRole('button', { name: 'Retry exact research save' })).toBeEnabled();
 expect(screen.queryByText(/Research version saved and verified/)).not.toBeInTheDocument();
});
it.each(['unmount', 'generation'])('does not invalidate listings when verified readback outlives %s', async boundary => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 let body: Record<string, unknown> = {}, done!: (r: Response) => void;
 const view = setup(async (url, opts) => {
  if (opts?.method === 'POST') { body = JSON.parse(String(opts.body)); return reply(saved(body)); }
  if (url.endsWith(`/${res}`)) return new Promise<Response>(r => { done = r; });
  return browsing(url);
 });
 const invalidate = vi.spyOn(view.cache, 'invalidateQueries');
 await selectStore(); await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled());
 fireEvent.click(screen.getByRole('button', { name: 'Save research version' })); await waitFor(() => expect(done).toBeTypeOf('function'));
 if (boundary === 'unmount') view.unmount(); else view.api.session = { ...view.api.session! };
 const count = view.fetcher.mock.calls.length; await act(async () => done(reply(saved(body))));
 expect(invalidate).not.toHaveBeenCalled(); expect(view.fetcher).toHaveBeenCalledTimes(count); expect(sessionStorage.length).toBe(1);
});
const pendingKey = 'arena:research-version:pending:v1';
const frozenRequest = () => ({ session: 'one', store: 'local', source: reference, body: { idempotency_key: 'frozen-F', family: 'Example', source_job_id: id, source_attempt_id: attempt, source_generation: 2 } });
async function siblings(handler: Handler, sessionId = 'one') {
 const view = setup(handler);
 if (sessionId !== 'one') { view.api.session = { session_id: sessionId, csrf_token: 'next', expires_at: 9999999999 }; runtime.current.session = view.api.session; view.redraw(); }
 const sibling = render(<QueryClientProvider client={view.cache}><ResearchVersions candidate={candidate} /></QueryClientProvider>);
 const a = within(view.container), b = within(sibling.container);
 fireEvent.click(a.getByRole('button', { name: 'Open research versions' }));
 fireEvent.click(b.getByRole('button', { name: 'Open research versions' }));
 await a.findByRole('button', { name: 'Retry exact research save' });
 await b.findByRole('button', { name: 'Retry exact research save' });
 return { ...view, a, b };
}
it('a stale mounted sibling cannot retry F or clear the newer unresolved G', async () => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 const f = frozenRequest(); sessionStorage.setItem(pendingKey, JSON.stringify(f));
 const view = await siblings(async (url, opts) => {
  if (opts?.method === 'POST') { const body = JSON.parse(String(opts.body)); if (body.idempotency_key !== f.body.idempotency_key) throw new Error('G unresolved'); return reply(saved(body)); }
  if (url.endsWith(`/${res}`)) return reply(saved(f.body));
  return browsing(url);
 });
 fireEvent.click(view.a.getByRole('button', { name: 'Retry exact research save' }));
 await view.a.findByText(/Research version saved and verified/);
 await waitFor(() => expect(view.a.getByRole('button', { name: 'Save research version' })).toBeEnabled());
 fireEvent.click(view.a.getByRole('button', { name: 'Save research version' })); await view.a.findByText(/Save unresolved/);
 const g = sessionStorage.getItem(pendingKey); expect(g).not.toBe(JSON.stringify(f));
 const posts = () => view.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST').length;
 expect(posts()).toBe(2);
 fireEvent.click(view.b.getByRole('button', { name: 'Retry exact research save' }));
 await act(async () => {});
 expect(posts()).toBe(2); expect(sessionStorage.getItem(pendingKey)).toBe(g);
});
it.each(['POST', 'GET'])('in-flight sibling F finishing after new G preserves G: %s', async phase => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 const f = frozenRequest(); sessionStorage.setItem(pendingKey, JSON.stringify(f));
 let done!: (r: Response) => void, fPosts = 0, fGets = 0;
 const view = await siblings(async (url, opts) => {
  if (opts?.method === 'POST') {
   const body = JSON.parse(String(opts.body)); if (body.idempotency_key !== f.body.idempotency_key) throw new Error('G unresolved');
   if (++fPosts === 1 && phase === 'POST') return new Promise<Response>(r => { done = r; });
   return reply(saved(body));
  }
  if (url.endsWith(`/${res}`)) { if (++fGets === 1 && phase === 'GET') return new Promise<Response>(r => { done = r; }); return reply(saved(f.body)); }
  return browsing(url);
 });
 fireEvent.click(view.b.getByRole('button', { name: 'Retry exact research save' }));
 await waitFor(() => expect(done).toBeTypeOf('function'));
 fireEvent.click(view.a.getByRole('button', { name: 'Retry exact research save' }));
 await view.a.findByText(/Research version saved and verified/);
 await waitFor(() => expect(view.a.getByRole('button', { name: 'Save research version' })).toBeEnabled());
 fireEvent.click(view.a.getByRole('button', { name: 'Save research version' })); await view.a.findByText(/Save unresolved/);
 const g = sessionStorage.getItem(pendingKey);
 await act(async () => done(reply(saved(f.body))));
 expect(sessionStorage.getItem(pendingKey)).toBe(g);
 expect(view.b.queryByText(/Research version saved and verified/)).not.toBeInTheDocument();
});
it.each(['', '{broken', 'null', 'extra-source', 'extra-record', 'wrong-source'])('malformed pending storage fails closed before retry without discard: %s', async malformed => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 const f = frozenRequest();
 if (malformed === 'extra-source') Object.assign(f.source = { ...reference }, { unexpected: 'not-allowed' });
 if (malformed === 'extra-record') Object.assign(f, { unexpected: 'not-allowed' });
 const raw = malformed.startsWith('extra-') ? JSON.stringify(f) : JSON.stringify(frozenRequest());
 sessionStorage.setItem(pendingKey, raw);
 const view = setup(browsing); open();
 if (!malformed.startsWith('extra-')) sessionStorage.setItem(pendingKey, malformed === 'wrong-source' ? JSON.stringify({ ...f, source: { ...reference, receipt_sha256: 'f'.repeat(64) } }) : malformed);
 const before = sessionStorage.getItem(pendingKey);
 const retry = screen.queryByRole('button', { name: 'Retry exact research save' }); if (retry) fireEvent.click(retry);
 await act(async () => {});
 expect(view.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(0);
 expect(sessionStorage.getItem(pendingKey)).toBe(before);
 expect(screen.getByRole('button', { name: 'Save research version' })).toBeDisabled();
});
it('fresh begin cannot overwrite malformed storage inserted after mount', async () => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 const view = setup(browsing); await selectStore();
 await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled());
 sessionStorage.setItem(pendingKey, '');
 fireEvent.click(screen.getByRole('button', { name: 'Save research version' }));
 await act(async () => {});
 expect(sessionStorage.getItem(pendingKey)).toBe('');
 expect(view.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(0);
});
it('S2 same-principal recovery from a stale mounted sibling cannot overwrite G', async () => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 const f = frozenRequest(); sessionStorage.setItem(pendingKey, JSON.stringify(f));
 const view = await siblings(async (url, opts) => {
  if (opts?.method === 'POST') { const body = JSON.parse(String(opts.body)); if (body.idempotency_key !== f.body.idempotency_key) throw new Error('G unresolved'); return reply(saved(body)); }
  if (url.endsWith(`/${res}`)) return reply(saved(f.body));
  return browsing(url);
 }, 'two');
 fireEvent.click(view.a.getByRole('button', { name: 'Recover exact research save in this session' }));
 expect(view.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(0);
 fireEvent.click(view.a.getByRole('button', { name: 'Retry exact research save' }));
 await view.a.findByText(/Research version saved and verified/);
 await waitFor(() => expect(view.a.getByRole('button', { name: 'Save research version' })).toBeEnabled());
 fireEvent.click(view.a.getByRole('button', { name: 'Save research version' })); await view.a.findByText(/Save unresolved/);
 const g = sessionStorage.getItem(pendingKey);
 fireEvent.click(view.b.getByRole('button', { name: 'Recover exact research save in this session' }));
 await act(async () => {});
 expect(view.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(2);
 expect(sessionStorage.getItem(pendingKey)).toBe(g);
 expect(view.b.getByRole('button', { name: 'Retry exact research save' })).toBeDisabled();
});
it('two fresh mounted instances cannot replace a sibling pending request', async () => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 const view = setup(async (url, opts) => opts?.method === 'POST' ? Promise.reject(new Error('lost')) : browsing(url));
 const sibling = render(<QueryClientProvider client={view.cache}><ResearchVersions candidate={candidate} /></QueryClientProvider>);
 const a = within(view.container), b = within(sibling.container);
 for (const scope of [a, b]) {
  fireEvent.click(scope.getByRole('button', { name: 'Open research versions' }));
  await scope.findByRole('option', { name: 'local' });
  fireEvent.change(scope.getByLabelText('Research store'), { target: { value: 'local' } });
  await waitFor(() => expect(scope.getByRole('button', { name: 'Save research version' })).toBeEnabled());
 }
 fireEvent.click(a.getByRole('button', { name: 'Save research version' }));
 const f = sessionStorage.getItem(pendingKey);
 fireEvent.click(b.getByRole('button', { name: 'Save research version' }));
 await act(async () => {});
 expect(view.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(1);
 expect(sessionStorage.getItem(pendingKey)).toBe(f);
 expect(b.getByRole('button', { name: 'Save research version' })).toBeDisabled();
});
const target = { profile_id: 'archive', revision: digest, scope_ownership: 'cooperative_immutable' };
async function enablePreparation() {
 fireEvent.click(screen.getByRole('checkbox', { name: 'Prepare publication on save' }));
 await screen.findByRole('option', { name: /archive/ });
 fireEvent.change(screen.getByLabelText('Publication profile'), { target: { value: 'archive' } });
}
it('publication preparation is default off and profile discovery requires explicit opt-in', async () => {
 const view = setup(async url => url.endsWith('/publication-profiles') ? reply({ profiles: [{ ...target, available: true }] }) : browsing(url));
 await selectStore(); await screen.findByText('Latest committed version: 3');
 expect(screen.getByRole('checkbox', { name: 'Prepare publication on save' })).not.toBeChecked();
 expect(view.fetcher.mock.calls.some(([u]) => u.includes('publication'))).toBe(false);
 await enablePreparation();
 expect(view.fetcher.mock.calls.filter(([u]) => u.endsWith('/publication-profiles'))).toHaveLength(1);
 expect(view.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
 expect(view.container.querySelector('input[type=password], input[type=url]')).toBeNull();
 expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled();
});
it.each([
 null, [], Array.from({ length: 17 }, (_, i) => ({ ...target, profile_id: `profile-${i}`, available: true })),
 [{ ...target, available: false }], [{ ...target, available: true, password: 'never-cache' }],
 [{ ...target }], // A three-field POST target is not a complete catalogue row.
 [{ ...target, available: true, revision: 'bad' }], [{ ...target, available: true, profile_id: '../bad' }],
 [{ ...target, available: true, scope_ownership: 'mutable' }], [{ ...target, available: true }, { ...target, available: true }],
].map(profiles => ({ profiles })))('publication profiles reject invalid or oversized metadata: %j', async ({ profiles }) => {
 const view = setup(async url => url.endsWith('/publication-profiles') ? reply({ profiles }) : browsing(url));
 await selectStore(); fireEvent.click(screen.getByRole('checkbox', { name: 'Prepare publication on save' }));
 await screen.findByText(profiles?.length === 0 ? 'No publication profiles configured.' : 'Publication profiles unavailable.');
 expect(screen.getByRole('button', { name: 'Save research version' })).toBeDisabled();
 expect(JSON.stringify(view.cache.getQueryData(['research-publication-profiles', 'one', view.api.sessionGeneration])) ?? '').not.toContain('never-cache');
 expect(view.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
});
function prepared(body: Record<string, unknown>, selectedTarget: unknown = body.publication_target) {
 const c = saved(body), request = { effect_id: 'intent-123', target_profile: selectedTarget };
 return { ...c, publication_intent_id: 'intent-123', reservation: { ...c.reservation, publication_request: request }, manifest: { ...c.manifest, binding: { ...c.reservation, publication_request: request } } };
}
it('publication target freezes before confirmation edits and persists exactly for lost-save retry', async () => {
 let body: Record<string, unknown> = {};
 const confirm = vi.spyOn(window, 'confirm').mockImplementation(() => {
  expect(sessionStorage.getItem(pendingKey)).toBeNull();
  fireEvent.change(screen.getByLabelText('Research family'), { target: { value: 'Edited' } });
  fireEvent.change(screen.getByLabelText('Publication profile'), { target: { value: 'other' } });
  return true;
 });
 const view = setup(async (url, opts) => {
  if (opts?.method === 'POST') { body = JSON.parse(String(opts.body)); throw new Error('lost'); }
  if (url.endsWith('/publication-profiles')) return reply({ profiles: [{ ...target, available: true }, { ...target, profile_id: 'other', available: true }] });
  return browsing(url);
 });
 await selectStore(); await enablePreparation();
 fireEvent.click(screen.getByRole('button', { name: 'Save research version' })); await screen.findByText(/Save unresolved/);
 expect(body.publication_target).toEqual(target); expect(body.family).toBe('Example');
 expect(confirm.mock.lastCall?.[0]).toContain('archive'); expect(confirm.mock.lastCall?.[0]).toContain('prepared, not published');
 expect(JSON.parse(sessionStorage.getItem(pendingKey)!).body).toEqual(body);
 const old = sessionStorage.getItem(pendingKey)!; view.unmount(); confirm.mockReturnValue(true);
 const retry = setup(async (url, opts) => opts?.method === 'POST' || url.endsWith(`/${res}`) ? reply(prepared(body)) : browsing(url));
 retry.api.session = { session_id: 'two', csrf_token: 'next', expires_at: 9999999999 }; runtime.current.session = retry.api.session; retry.redraw(); open();
 expect(sessionStorage.getItem(pendingKey)).toBe(old);
 fireEvent.click(await screen.findByRole('button', { name: 'Recover exact research save in this session' }));
 expect(retry.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
 fireEvent.click(screen.getByRole('button', { name: 'Retry exact research save' }));
 await screen.findByText(/Research version saved and verified/);
 expect(screen.getByText(/prepared, not published/)).toBeInTheDocument();
 expect(retry.fetcher.mock.calls.find(([, o]) => o?.method === 'POST')?.[1]?.body).toBe(JSON.stringify(body));
 expect(retry.fetcher.mock.calls.some(([u]) => /publication|grant|graph/.test(u))).toBe(false);
 expect(sessionStorage.getItem(pendingKey)).toBeNull();
});
it.each(['POST', 'GET'].flatMap(phase => ['absent', 'effect', 'target', 'binding', 'changed-intent', 'unexpected'].map(fault => ({ phase, fault }))))('publication verification rejects $phase $fault without clearing or invalidating', async ({ phase, fault }) => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 const f = frozenRequest(), body = { ...f.body, publication_target: target };
 sessionStorage.setItem(pendingKey, JSON.stringify({ ...f, body }));
 const broken = () => {
  if (fault === 'absent') return saved(body);
  const c = prepared(body);
  if (fault === 'effect') c.publication_intent_id = 'wrong';
  if (fault === 'target') c.reservation.publication_request.target_profile = { ...target, revision: 'f'.repeat(64) };
  if (fault === 'binding') c.manifest.binding = { ...c.manifest.binding, publication_request: { ...c.reservation.publication_request, effect_id: 'wrong' } };
  if (fault === 'changed-intent') { c.publication_intent_id = 'intent-456'; c.reservation.publication_request.effect_id = 'intent-456'; }
  if (fault === 'unexpected') Object.assign(c.reservation.publication_request, { unexpected: true });
  return c;
 };
 // A different but internally valid intent on POST has no prior effect to compare.
 const view = setup(async (url, opts) => {
  if (opts?.method === 'POST') return reply(phase === 'POST' && fault !== 'changed-intent' ? broken() : prepared(body));
  if (url.endsWith(`/${res}`)) return reply(phase === 'GET' || fault === 'changed-intent' ? broken() : prepared(body));
  return browsing(url);
 });
 const invalidate = vi.spyOn(view.cache, 'invalidateQueries'); open();
 const old = sessionStorage.getItem(pendingKey);
 fireEvent.click(await screen.findByRole('button', { name: 'Retry exact research save' }));
 await screen.findByText(/Save unresolved/);
 expect(sessionStorage.getItem(pendingKey)).toBe(old); expect(invalidate).not.toHaveBeenCalled();
 expect(screen.queryByText(/Research version saved and verified/)).not.toBeInTheDocument();
 expect(view.fetcher.mock.calls.filter(([, o]) => o?.method === 'POST').every(([u]) => u === '/api/research/stores/local/versions')).toBe(true);
});
it('publication selection pins metadata rather than silently adopting a replaced profile revision', async () => {
 const view = setup(async url => url.endsWith('/publication-profiles') ? reply({ profiles: [{ ...target, available: true }] }) : browsing(url));
 await selectStore(); await enablePreparation();
 expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled();
 act(() => view.cache.setQueryData(['research-publication-profiles', 'one', view.api.sessionGeneration], [{ ...target, revision: 'f'.repeat(64) }]));
 await waitFor(() => expect(screen.getByRole('button', { name: 'Save research version' })).toBeDisabled());
 fireEvent.change(screen.getByLabelText('Publication profile'), { target: { value: 'archive' } });
 expect(screen.getByRole('button', { name: 'Save research version' })).toBeEnabled();
});
it.each([false, true])('publication detail explicitly labels preparation without retroactive mutation: %s', async isPrepared => {
 const view = setup(async url => url.endsWith(`/${res}`) ? reply(isPrepared ? prepared({ family: 'Example', idempotency_key: 'old' }, target) : commit) : browsing(url));
 await selectStore(); fireEvent.click(await screen.findByRole('button', { name: 'Select version 3' }));
 await screen.findByText(isPrepared ? /Prepared version: publication status unchecked/ : /Unprepared existing version/);
 expect(screen.getByText(/No retroactive publication intent/)).toBeInTheDocument();
 expect(view.fetcher.mock.calls.some(([u, o]) => o?.method === 'POST' || /publication|grant|graph/.test(u))).toBe(false);
});
it('publication retained target is shown in S2 recovery and retry confirmations without discovery', async () => {
 const f = frozenRequest(); sessionStorage.setItem(pendingKey, JSON.stringify({ ...f, session: 'old', body: { ...f.body, publication_target: target } }));
 const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
 const view = setup(async (u, o) => o?.method === 'POST' ? Promise.reject(new Error('lost')) : browsing(u)); open();
 expect(screen.getByText(/Retained publication target: archive/)).toHaveTextContent(digest);
 expect(screen.getByRole('checkbox', { name: 'Prepare publication on save' })).toBeChecked();
 fireEvent.click(screen.getByRole('button', { name: 'Recover exact research save in this session' }));
 expect(confirm.mock.lastCall?.[0]).toContain('archive');
 fireEvent.click(screen.getByRole('button', { name: 'Retry exact research save' }));
 expect(confirm.mock.lastCall?.[0]).toContain('archive'); expect(confirm.mock.lastCall?.[0]).toContain('prepared, not published');
 await screen.findByText(/Save unresolved/);
 expect(view.fetcher.mock.calls.some(([u]) => /publication|grant|graph/.test(u))).toBe(false);
});
it.each([null, [], {}, { ...target, available: true }, { ...target, revision: 3 }, { ...target, password: 'blocked-secret' }, { ...target, profile_id: ' bad ' }].map(publication_target => ({ publication_target })))('publication malformed nested retention is preserved untouched: %j', async ({ publication_target }) => {
 const f = frozenRequest(), raw = JSON.stringify({ ...f, body: { ...f.body, publication_target } }); sessionStorage.setItem(pendingKey, raw);
 const view = setup(browsing); open(); await screen.findByText(/Retained request storage is unavailable/);
 expect(sessionStorage.getItem(pendingKey)).toBe(raw); expect(screen.queryByRole('button', { name: 'Retry exact research save' })).not.toBeInTheDocument();
 expect(screen.getByRole('checkbox', { name: 'Prepare publication on save' })).toBeDisabled();
 expect(view.fetcher.mock.calls.some(([u, o]) => o?.method === 'POST' || /publication|grant|graph/.test(u))).toBe(false);
});
it('publication nested target changes lose sibling ownership rather than dispatching a replacement', async () => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 const f = frozenRequest(), original = { ...f, body: { ...f.body, publication_target: target } };
 sessionStorage.setItem(pendingKey, JSON.stringify(original)); const view = setup(browsing); open();
 const newer = JSON.stringify({ ...original, body: { ...original.body, publication_target: { ...target, revision: 'f'.repeat(64) } } });
 sessionStorage.setItem(pendingKey, newer); fireEvent.click(screen.getByRole('button', { name: 'Retry exact research save' }));
 await screen.findByText(/Pending research save ownership changed/);
 expect(sessionStorage.getItem(pendingKey)).toBe(newer); expect(view.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
});
it.each(['unmount', 'session'])('publication delayed profile response cannot revive selection after %s', async boundary => {
 let done!: (r: Response) => void;
 const view = setup(async u => u.endsWith('/publication-profiles') ? new Promise<Response>(r => { done = r; }) : browsing(u));
 await selectStore(); fireEvent.click(screen.getByRole('checkbox', { name: 'Prepare publication on save' }));
 await waitFor(() => expect(done).toBeTypeOf('function'));
 if (boundary === 'unmount') view.unmount(); else { view.api.session = { session_id: 'two', csrf_token: 'new', expires_at: 9999999999 }; runtime.current.session = view.api.session; view.redraw(); open(); }
 await act(async () => done(reply({ profiles: [{ ...target, available: true }] })));
 expect(screen.queryByRole('option', { name: /archive/ })).not.toBeInTheDocument();
 expect(view.fetcher.mock.calls.filter(([u]) => u.endsWith('/publication-profiles'))).toHaveLength(1);
 expect(view.fetcher.mock.calls.some(([, o]) => o?.method === 'POST')).toBe(false);
});
it('publication opt-out saves legacy body unchanged and never adds a target to an old retained request', async () => {
 vi.spyOn(window, 'confirm').mockReturnValue(true);
 let body: Record<string, unknown> = {};
 const view = setup(async (u, o) => {
  if (o?.method === 'POST') { body = JSON.parse(String(o.body)); throw new Error('lost'); }
  return u.endsWith('/publication-profiles') ? reply({ profiles: [{ ...target, available: true }] }) : browsing(u);
 });
 await selectStore(); await enablePreparation(); fireEvent.click(screen.getByRole('checkbox', { name: 'Prepare publication on save' }));
 fireEvent.click(screen.getByRole('button', { name: 'Save research version' })); await screen.findByText(/Save unresolved/);
 expect(body).not.toHaveProperty('publication_target'); const raw = sessionStorage.getItem(pendingKey); view.unmount();
 const old = setup(async (u, o) => o?.method === 'POST' || u.endsWith(`/${res}`) ? reply(saved(body)) : browsing(u)); open();
 expect(sessionStorage.getItem(pendingKey)).toBe(raw); expect(screen.getByRole('checkbox', { name: 'Prepare publication on save' })).toBeDisabled();
 fireEvent.click(screen.getByRole('button', { name: 'Retry exact research save' })); await screen.findByText(/Research version saved and verified/);
 expect(old.fetcher.mock.calls.find(([, o]) => o?.method === 'POST')?.[1]?.body).toBe(JSON.stringify(body));
 expect(old.fetcher.mock.calls.some(([u]) => /publication|grant|graph/.test(u))).toBe(false);
});
beforeEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); });
it('makes no requests while closed and honestly reports unconfigured stores on explicit open', async () => {
 const view = setup(); expect(view.fetcher).not.toHaveBeenCalled(); open();
 expect(await screen.findByText('No research stores configured.')).toBeInTheDocument();
 expect(view.fetcher).toHaveBeenCalledTimes(1);
});
