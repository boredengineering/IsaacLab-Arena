import { useEffect, useRef, useState } from 'react';
import { useRuntime } from './runtime';
// Exact versioned boundary from research_graph_transport; not arbitrary attestation prose.
import backend from './publication-backend.fixture.json';
/** Trusted, already-frozen committed intent bindings; never user-entered transport configuration.
 * enabled is session/backend read admission (default false). mutationEnabled defaults
 * true for existing callers, but must be false while current binding is unavailable.
 * A retained verified scope permits disposition checking, never cached authorization.
 * versionRef digests/transport identity must come from verified immutable intent data.
 */
export interface PublicationControlsProps {
 enabled?: boolean; mutationEnabled?: boolean; storeId: string; effectId: string; registryId: string;
 target: { profile_id: string; revision: string; scope_ownership: 'cooperative_immutable' };
 versionRef: { reservation_id: string; revision_id: string; version: number; payload_sha256: string; projection_digest: string; scope_id: string; database: string; canonical_identity: { name: string; sha256: string } };
}
type Operation = 'write' | 'renew' | 'reconcile';
type Frozen = { accepted?: Record<string, unknown>; session: string; scope: Omit<PublicationControlsProps, 'enabled' | 'mutationEnabled'>; operation: Operation; body: { request_id: string; previous_request_id?: string } };
const LEGACY_KEY = 'arena:publication:request:v1';
const PREFIX = 'arena:publication:request:v2:';
const storageKey = (s: Frozen['scope']) => PREFIX + JSON.stringify([s.registryId, s.storeId, s.effectId, s.versionRef.reservation_id, s.versionRef.revision_id, s.versionRef.version]);
const obj = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {};
const token = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(v);
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const positive = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v > 0;
const keys = (v: unknown, names: string) => Object.keys(obj(v)).sort().join(',') === names.split(',').sort().join(',');
const same = (a: unknown, b: unknown): boolean => canonical(a) === canonical(b);
function canonical(v: unknown): string { if (v === null || typeof v !== 'object') return JSON.stringify(v); if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']'; return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonical(obj(v)[k])).join(',') + '}'; }
function validScope(v: unknown): v is Frozen['scope'] {
 const s = obj(v), t = obj(s.target), r = obj(s.versionRef), c = obj(r.canonical_identity);
 // Python transport str.strip() treats NEL as whitespace; JS trim() does not.
 // Unicode White_Space plus the C0 rejection below matches without normalizing names.
 return keys(s, 'storeId,effectId,registryId,target,versionRef') && token(s.storeId) && token(s.effectId) && token(s.registryId) && keys(t, 'profile_id,revision,scope_ownership') && token(t.profile_id) && hash(t.revision) && t.scope_ownership === 'cooperative_immutable' && keys(r, 'reservation_id,revision_id,version,payload_sha256,projection_digest,scope_id,database,canonical_identity') && token(r.reservation_id) && token(r.revision_id) && positive(r.version) && hash(r.payload_sha256) && hash(r.projection_digest) && token(r.scope_id) && typeof r.database === 'string' && !/^\p{White_Space}*$/u.test(r.database) && new TextEncoder().encode(r.database).length >= 1 && new TextEncoder().encode(r.database).length <= 256 && !/[\u0000-\u001f]/.test(r.database) && keys(c, 'name,sha256') && typeof c.name === 'string' && c.name.length > 0 && hash(c.sha256);
}
function parseFrozen(raw: string): Frozen {
 if (new TextEncoder().encode(raw).length > 4096) throw Error();
 const f = JSON.parse(raw), b = obj(f.body);
 if (!(keys(f, 'session,scope,operation,body') || keys(f, 'session,scope,operation,body,accepted') && validAccepted(f.accepted)) || !token(f.session) || !validScope(f.scope) || !['write', 'renew', 'reconcile'].includes(f.operation) || !token(b.request_id) || !(f.operation === 'write' ? keys(b, 'request_id') : keys(b, 'request_id,previous_request_id') && token(b.previous_request_id) && b.previous_request_id !== b.request_id)) throw Error();
 return f;
}
function readAll(): Record<string, Frozen> {
 // Legacy global records have no bounded history ownership: never migrate or overwrite silently.
 if (sessionStorage.getItem(LEGACY_KEY) !== null) throw Error();
 const result: Record<string, Frozen> = {};
 for (let i = 0; i < sessionStorage.length; i++) {
  const key = sessionStorage.key(i)!;
  if (!key.startsWith(PREFIX)) continue;
  if (Object.keys(result).length >= 32) throw Error();
  const f = parseFrozen(sessionStorage.getItem(key)!);
  if (key !== storageKey(f.scope)) throw Error();
  result[key] = f;
 }
 return result;
}
function store(f: Frozen) {
 const all = readAll(), key = storageKey(f.scope), raw = JSON.stringify(f);
 if (!all[key] && Object.keys(all).length >= 32) throw Error();
 parseFrozen(raw); // Same per-record bound on writes and reads; never evict unresolved entries.
 sessionStorage.setItem(key, raw);
}
function acceptanceFits(f: Frozen): boolean {
 // Exact checked() wire contract: binding fields are frozen; only attempt_id
 // (64 token bytes) and generation (positive safe integer) have unknown sizes.
 // Serialize the full record including UTF-8/JSON escaping, not a guessed margin.
 const accepted = { schema_version: 1, registry_id: f.scope.registryId, effect_id: f.scope.effectId, request_id: f.body.request_id, owner_session: f.session, principal: f.session, store_id: f.scope.storeId, operation: f.operation, request_digest: 'a'.repeat(64), previous_request_id: f.body.previous_request_id ?? null, attempt_id: 'a'.repeat(64), generation: Number.MAX_SAFE_INTEGER, capability: f.operation === 'reconcile' ? 'graph_read' : 'graph_write' };
 try { parseFrozen(JSON.stringify({ ...f, accepted })); return true; } catch { return false; }
}
function validAccepted(v: unknown) { const a = obj(v); return keys(a, 'schema_version,registry_id,effect_id,request_id,owner_session,principal,store_id,operation,request_digest,previous_request_id,attempt_id,generation,capability') && a.schema_version === 1 && ['registry_id','effect_id','request_id','owner_session','principal','store_id','attempt_id'].every(k => token(a[k])) && hash(a.request_digest) && positive(a.generation) && (a.previous_request_id === null || token(a.previous_request_id)) && ['write','renew','reconcile'].includes(String(a.operation)) && ['graph_read','graph_write'].includes(String(a.capability)); }
type Observed = { accepted: Record<string, unknown>; state: Record<string, unknown> | null };
function bounded(v: unknown) {
 let count = 0;
 function walk(x: unknown, depth: number) { if (++count > 8192 || depth > 16) throw Error(); if (x !== null && typeof x === 'object') Object.values(x).forEach(y => walk(y, depth + 1)); else if (!['string', 'number', 'boolean'].includes(typeof x) && x !== null || typeof x === 'number' && !Number.isFinite(x)) throw Error(); }
 walk(v, 0); if (new TextEncoder().encode(JSON.stringify(v)).length > 131072) throw Error();
}
async function checked(v: unknown, f: Frozen, post = false): Promise<Observed> {
 bounded(v); const r = obj(v), a = obj(r.accepted), s = r.state === null ? null : obj(r.state), p = f.scope;
 if (!(post ? (keys(r, 'accepted_new,accepted,state') || (keys(r, 'accepted_new,accepted,state,disposition') || keys(r, 'accepted_new,accepted,state,disposition,error') && r.error === 'Publication state unavailable') && r.disposition === 'accepted_state_unavailable' && s === null) && typeof r.accepted_new === 'boolean' : keys(r, 'accepted,state'))) throw Error();
 const binding = { store_id: p.storeId, effect_id: p.effectId, request_id: f.body.request_id, owner_session: f.session, principal: f.session, operation: f.operation, previous_request_id: f.body.previous_request_id ?? null };
 const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical(binding))))).map(n => n.toString(16).padStart(2, '0')).join('');
 if (!keys(a, 'schema_version,registry_id,effect_id,request_id,owner_session,principal,store_id,operation,request_digest,previous_request_id,attempt_id,generation,capability') || a.schema_version !== 1 || a.registry_id !== p.registryId || Object.entries(binding).some(([k, val]) => a[k] !== val) || a.request_digest !== digest || !token(a.attempt_id) || !positive(a.generation) || a.capability !== (f.operation === 'reconcile' ? 'graph_read' : 'graph_write')) throw Error();
 if (s !== null) {
  if (!keys(s, 'schema_version,effect_id,target_profile,payload_sha256,state,cancelled,generation,attempt_id,request_id,receipt,write_claim_count,reconciliation,write_callback_open') || s.schema_version !== 1 || s.effect_id !== p.effectId || !same(s.target_profile, p.target) || s.payload_sha256 !== p.versionRef.payload_sha256 || !['pending','claimed','released','unknown','blocked_authorization','cancelled_no_send','verified'].includes(String(s.state)) || typeof s.cancelled !== 'boolean' || typeof s.write_callback_open !== 'boolean' || !positive(s.generation) || !token(s.attempt_id) || !token(s.request_id) || !Number.isSafeInteger(s.write_claim_count) || Number(s.write_claim_count) < 0 || Number(s.write_claim_count) > 64 || s.reconciliation !== null && (!keys(s.reconciliation, 'state') || !['claimed','released','unknown','verified'].includes(String(obj(s.reconciliation).state)))) throw Error();
  if (s.state === 'verified') {
   const rc = obj(s.receipt), t = obj(rc.transport), b = obj(t.verification_boundary), ref = p.versionRef;
   if (!keys(rc, 'schema_version,status,effect_id,target_profile,payload_sha256,transport') || rc.schema_version !== 1 || rc.status !== 'verified' || rc.effect_id !== p.effectId || !same(rc.target_profile, p.target) || rc.payload_sha256 !== ref.payload_sha256 || !keys(t, 'status,effect_id,database,scope_id,projection_digest,canonical_identity,verification_boundary') || t.status !== 'verified' || t.effect_id !== p.effectId || t.database !== ref.database || t.scope_id !== ref.scope_id || t.projection_digest !== ref.projection_digest || !same(t.canonical_identity, ref.canonical_identity) || !keys(b, 'method,operator_attested,declaration,database_snapshot') || b.method !== 'operator_attested_immutable_scope_v1' || b.operator_attested !== true || b.database_snapshot !== false || b.declaration !== backend.declaration || new TextEncoder().encode(JSON.stringify(rc)).length > 8192) throw Error();
  } else if (s.receipt !== null) throw Error();
 }
 return { accepted: a, state: s };
}
function disposition(o: Observed): string {
 const s = o.state;
 if (!s) return 'Accepted; current state unavailable. Publication is not verified. Read-only checking remains available.';
 if (s.state === 'verified') return s.cancelled ? 'Cancelled but verified publication. Cancellation did not roll back the graph.' : 'Verified publication — operator-attested immutable scope, not a database snapshot.';
 return ({ pending: 'Prepared, not published.', claimed: 'Queued, not yet released.', released: 'Released; verification pending.', unknown: 'Unknown write outcome. Read-only reconciliation is required; another write is prohibited.', blocked_authorization: 'Blocked authorization; unsent. Renewal requires separate approval.', cancelled_no_send: 'Cancelled-no-send. No graph write was released.' } as Record<string, string>)[String(s.state)];
}
export function PublicationControls(props: PublicationControlsProps) {
 const { api, session, status } = useRuntime();
 const { enabled, mutationEnabled = true, ...scope } = props;
 const epoch = api.sessionGeneration, owner = session?.session_id;
 const [mountedSession] = useState({ owner, epoch });
 const sameSession = mountedSession.owner === owner && mountedSession.epoch === epoch;
 const identity = canonical([scope, owner, epoch]);
 const [open, setOpen] = useState(false), [busyOperation, setBusyOperation] = useState<symbol | null>(null);
 const [notice, setNotice] = useState({ identity, text: 'Publication status unchecked.' });
 const message = notice.identity === identity ? notice.text : 'Publication status unchecked.';
 const setMessage = (text: string) => setNotice({ identity, text });
 const [history, setHistory] = useState<Record<string, Frozen>>(() => { try { return readAll(); } catch { return {}; } });
 // Component-lifetime evidence, never a claim of persistence across remount.
 const known = useRef(new Map<string, { value: Frozen; baseline: Frozen; failed: boolean }>());
 const retained = history[storageKey(scope)] ?? null;
 const getOnly = !!known.current.get(storageKey(scope))?.failed;
 const setRetained = (f: Frozen) => setHistory(h => ({ ...h, [storageKey(f.scope)]: f }));
 const [blocked, setBlocked] = useState(() => { try { readAll(); return false; } catch { return true; } });
 const [observation, setObservation] = useState<{ identity: string; value: Observed | null } | null>(null);
 const observed = observation?.identity === identity ? observation.value : null;
 const setObserved = (value: Observed | null) => setObservation({ identity, value });

 const active = useRef(true), dispatching = useRef<symbol | null>(null), gate = useRef({ enabled, mutationEnabled, scope, open });
 gate.current = { enabled, mutationEnabled, scope, open };
 const lifetime = useRef(0), context = canonical([identity, enabled, mutationEnabled, status]), previousContext = useRef(context);
 if (previousContext.current !== context) { previousContext.current = context; lifetime.current++; dispatching.current = null; }
 const renderCycle = lifetime.current, busy = dispatching.current !== null && busyOperation === dispatching.current;
 function release(id: symbol) { if (dispatching.current === id) { dispatching.current = null; if (active.current) setBusyOperation(null); } }
 useEffect(() => { active.current = true; return () => { active.current = false; lifetime.current++; dispatching.current = null; }; }, []);
 const current = () => sameSession && renderCycle === lifetime.current && active.current && gate.current.enabled === true && gate.current.open && api.sessionGeneration === epoch && api.session?.session_id === owner && status !== 'expired' && validScope(gate.current.scope) && same(gate.current.scope, scope);
 const unsupported = !!retained && retained.session !== owner;
 const usable = sameSession && enabled === true && validScope(scope) && !!owner && api.session?.session_id === owner && status !== 'expired' && !unsupported && !blocked && (!retained || same(retained.scope, scope));
 const mutable = usable && mutationEnabled && !getOnly;
 const mutationCurrent = () => current() && gate.current.mutationEnabled && !known.current.get(storageKey(scope))?.failed;
 function owns(f: Frozen, readOnly = false) {
  const memory = known.current.get(storageKey(f.scope));
  try { const stored = readAll()[storageKey(f.scope)] ?? null; return same(stored, f) || !!memory && same(memory.value, f) && same(stored, memory.baseline); }
  catch (error) {
   // Unavailable storage is not evidence that a sibling replaced the request.
   // Only already-validated, exact in-memory acceptance permits a GET fallback.
   if (readOnly && error instanceof DOMException && error.name === 'SecurityError' && memory && f.accepted && same(memory.value, f)) { memory.failed = true; return true; }
   return false;
  }
 }
 function lost() { const f = known.current.get(storageKey(scope))?.value; const text = 'Request ownership changed. Operator review required; no request was replaced or discarded.'; setBlocked(true); setObserved(null); setMessage(f ? acceptanceMessage(f, text) : text); }
 function capacityUnavailable() { setMessage('Insufficient bounded acceptance storage. Operator review required; no request was replaced or sent. Read-only checking remains available.'); }
 function remember(f: Frozen, accepted: Record<string, unknown>): Frozen {
  const key = storageKey(f.scope), previous = known.current.get(key);
  const next = { ...f, accepted };
  const memory = { value: next, baseline: previous && same(previous.value, f) ? previous.baseline : f, failed: previous?.failed ?? false };
  known.current.set(key, memory); setRetained(next);
  // Record validated acceptance before any fallible browser storage operation.
  try { if (!owns(next)) throw Error(); store(next); if (!same(readAll()[key], next)) throw Error(); memory.baseline = next; }
  catch { memory.failed = true; }
  return next;
 }
 function acceptanceMessage(f: Frozen, text: string) { return text + (known.current.get(storageKey(f.scope))?.failed ? ' Acceptance storage/readback failed. This mounted request is GET-only; acceptance is held in memory and is not guaranteed after remount. Operator review required.' : ''); }
 async function dispatch(f: Frozen, post: boolean) {
  if (!current() || dispatching.current || f.session !== owner || post && (!mutationCurrent() || !!f.accepted)) return;
  if (!owns(f, !post)) { lost(); return; }
  if (post && !acceptanceFits(f)) { capacityUnavailable(); return; }
  const operationId = Symbol(); dispatching.current = operationId; setBusyOperation(operationId);
  try {
   const base = `/research/stores/${f.scope.storeId}/publications/${f.scope.effectId}`;
   if (post) {
    const raw = await api.mutate<unknown>(`${base}/${f.operation}`, f.body);
    if (!current()) return;
    const first = await checked(raw, f, true);
    if (!current()) return;
    if (f.accepted && !same(f.accepted, first.accepted)) throw Error();
    f = remember(f, first.accepted);
    setObserved(null); setMessage(acceptanceMessage(f, disposition({ accepted: first.accepted, state: null })));
   }
   if (!current() || !owns(f, true)) { if (current()) lost(); return; }
   const raw = await api.get<unknown>(`${base}/requests/${f.body.request_id}`);
   if (!current()) return;
   const next = await checked(raw, f);
   if (!current()) return;
   if (f.accepted && !same(f.accepted, next.accepted)) throw Error();
   f = remember(f, next.accepted); if (!owns(f, true)) { lost(); return; } setObserved(next); setMessage(acceptanceMessage(f, disposition(next)));
  } catch { if (current()) { setObserved(null); setMessage(f.accepted ? acceptanceMessage(f, disposition({ accepted: f.accepted, state: null })) : !acceptanceFits(f) ? 'Request unresolved. Insufficient bounded acceptance storage; Operator review required. Exact request retained. Read-only checking remains available.' : 'Request unresolved. Exact request retained; no publication verified. Check disposition or explicitly retry the identical request.'); } }
  finally { release(operationId); }
 }
 const state = observed?.state;
 const exactCurrent = !!state && !!observed && ['request_id', 'attempt_id', 'generation'].every(k => state[k] === observed.accepted[k]);
 const canRenew = exactCurrent && state?.state === 'blocked_authorization' && state.cancelled === false && state.write_callback_open === false;
 const canRead = exactCurrent && state?.state === 'unknown' && state.write_callback_open === false && !['claimed', 'released'].includes(String(obj(state.reconciliation).state));
 const canCancel = exactCurrent && ['claimed', 'released', 'unknown', 'blocked_authorization'].includes(String(state?.state));
 function follow(operation: 'renew' | 'reconcile') {
  if (!mutable || !mutationCurrent() || busy || dispatching.current || !retained || !(operation === 'renew' ? canRenew : canRead)) return;
  if (!window.confirm(operation === 'renew' ? 'Renew this blocked, unsent attempt with a new predecessor-bound graph write authorization?' : 'Reconcile this unknown outcome using graph READ ONLY? This cannot authorize another graph write.')) return;
  if (!mutationCurrent()) return;
  if (!owns(retained)) { lost(); return; }
  try {
   const f: Frozen = { session: retained.session, scope: retained.scope, operation, body: { request_id: crypto.randomUUID(), previous_request_id: retained.body.request_id } };
   if (!acceptanceFits(f)) { capacityUnavailable(); return; }
   store(f); setRetained(f); setObserved(null); void dispatch(f, true);
  } catch { lost(); }
 }
 async function cancel() {
  if (!mutable || !mutationCurrent() || busy || dispatching.current || !retained || !canCancel || !observed) return;
  const f = retained, a = observed.accepted;
  const body = { request_id: f.body.request_id, attempt_id: a.attempt_id, generation: a.generation };
  if (!window.confirm('Cancel only this accepted current attempt? Released writes may still verify. Cancellation is not rollback.')) return;
  if (!mutationCurrent()) return;
  if (!owns(f)) { lost(); return; }
  const operationId = Symbol(); dispatching.current = operationId; setBusyOperation(operationId);
  try {
   const response = await api.mutate<unknown>(`/research/stores/${f.scope.storeId}/publications/${f.scope.effectId}/cancel`, body);
   if (!current()) return;
   if (!owns(f)) { lost(); return; }
   if (!keys(response, 'cancelled') || typeof obj(response).cancelled !== 'boolean') throw Error();
   release(operationId); await dispatch(f, false);
  } catch { if (current()) { setObserved(null); setMessage('Cancellation unresolved. Request retained; check disposition. No rollback is implied.'); } }
  finally { release(operationId); }
 }
 function begin() {
  if (!mutable || busy || retained || !mutationCurrent()) return;
  const frozenScope = JSON.parse(JSON.stringify(scope)) as Frozen['scope'];
  if (!window.confirm('Publish this frozen version to the graph? This authorizes one graph write, not policy or simulation execution.')) return;
  if (!mutationCurrent() || !same(frozenScope, gate.current.scope)) return;
  try {
   if (readAll()[storageKey(frozenScope)]) { lost(); return; }
   const f: Frozen = { session: owner!, scope: frozenScope, operation: 'write', body: { request_id: crypto.randomUUID() } };
   if (!acceptanceFits(f)) { capacityUnavailable(); return; }
   store(f); setRetained(f); void dispatch(f, true);
  } catch { lost(); }
 }
 return <section aria-label="Publication controls">
  <button type="button" disabled={!usable && !open} aria-expanded={open} onClick={() => { if (open) { lifetime.current++; dispatching.current = null; setBusyOperation(null); gate.current.open = false; setOpen(false); } else { gate.current.open = true; setOpen(true); if (retained && usable && mutationEnabled) void dispatch(retained, false); } }}>{open ? 'Close publication controls' : 'Open publication controls'}</button>
  {(!validScope(scope) || blocked) && <p role="alert">Publication controls unavailable: invalid scope or retained request. Operator review required.</p>}
  {unsupported && <p role="alert">Cross-session publication recovery is unsupported. Operator recovery required; old requests cannot be adopted by this session.</p>}
  {open && <>{validScope(scope) && <p>Store {scope.storeId}; effect {scope.effectId}; profile {scope.target.profile_id} ({scope.target.revision}, {scope.target.scope_ownership}); Version {scope.versionRef.version}, revision {scope.versionRef.revision_id}, reservation {scope.versionRef.reservation_id}.</p>}<p>No policy or simulation success is implied. Cancellation is not rollback.</p><p role="status">{message}</p>
   <button type="button" disabled={!mutable || busy || !canRenew} onClick={() => follow('renew')}>Renew blocked unsent request</button>
   <button type="button" disabled={!mutable || busy || !canRead} onClick={() => follow('reconcile')}>Reconcile read-only</button>
   <button type="button" disabled={!mutable || busy || !canCancel} onClick={() => void cancel()}>Cancel current attempt</button>
   <button type="button" disabled={!mutable || busy || !!retained} onClick={begin}>Publish graph</button>
   {retained && <><button type="button" disabled={!usable || busy} onClick={() => void dispatch(retained, false)}>Check disposition</button><button type="button" disabled={!mutable || busy || !!observed || !!retained.accepted || !acceptanceFits(retained)} onClick={() => { if (window.confirm('Retry only the exact retained publication request? No new write key will be created.')) void dispatch(retained, true); }}>Retry exact request</button></>}
  </>}
 </section>;
}
