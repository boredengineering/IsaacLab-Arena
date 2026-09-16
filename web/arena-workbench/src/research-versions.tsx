import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { isJob, type Job } from './contracts';
import { useRuntime } from './runtime';
import { PropertyTree } from './graph-explorer/property-tree';
import { PublicationPanel } from './publication-panel';
import { clientSessionScope } from './client-session-scope';
import { researchSource, sameResearchSource, isManualInput, manualInput, sourceLabel, researchOpen, type ResearchSource, type ManualInput, type ResearchOpen } from './research-source';

const record = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {};
const token = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(v);
const uuid = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{32}$/.test(v);
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const positive = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v > 0;
interface Version { reservation_id: string; revision_id: string; version: number; parent_revision_id: string | null; state: 'COMMITTED' | 'committed' | 'RESERVED' | 'reserved'; source_job_id?: string; source?: ResearchSource; open_source?: {kind: 'research_version'; id: string} | null; manifest_digest: string | null }
function version(v: unknown): v is Version { const r = record(v); return uuid(r.reservation_id) && uuid(r.revision_id) && positive(r.version) && ((r.state === 'COMMITTED' || r.state === 'committed') && hash(r.manifest_digest) || (r.state === 'RESERVED' || r.state === 'reserved') && r.manifest_digest === null) && (r.source === undefined ? uuid(r.source_job_id) : researchSource(r.source) && ('kind' in r.source ? r.source_job_id === undefined : r.source_job_id === r.source.job_id)) && (r.parent_revision_id === null || uuid(r.parent_revision_id)); }
interface CandidateRef { job_id: string; attempt_id: string; generation: number; receipt_sha256: string; request_sha256: string }
interface PublicationTarget { profile_id: string; revision: string; scope_ownership: 'cooperative_immutable' }
function publicationTarget(v: unknown): v is PublicationTarget { const r = record(v); return Object.keys(r).length === 3 && token(r.profile_id) && hash(r.revision) && r.scope_ownership === 'cooperative_immutable'; }
function sameTarget(a: unknown, b: unknown) { return publicationTarget(a) && publicationTarget(b) && a.profile_id === b.profile_id && a.revision === b.revision && a.scope_ownership === b.scope_ownership; }
function candidateRef(v: unknown): v is CandidateRef { const r = record(v); return uuid(r.job_id) && uuid(r.attempt_id) && positive(r.generation) && hash(r.receipt_sha256) && hash(r.request_sha256); }
interface Payload { idempotency_key: string; family: string; source_job_id?: string; source_attempt_id?: string; source_generation?: number; source?: ManualInput; parent_revision_id?: string | null; publication_target?: PublicationTarget }
interface Frozen { session: string; store: string; body: Payload; source: CandidateRef | ManualInput }
function preparationLabel(f: Frozen) { const p = f.body.publication_target; return p ? `Profile ${p.profile_id} (${p.revision}, ${p.scope_ownership}): prepared, not published.` : 'No publication intent will be prepared.'; }
const STORAGE = 'arena:research-version:pending:v1';
class VersionConflict extends Error {}
function checkedCommit(value: unknown, store: string, family: string) {
 const c = record(value), r = record(c.reservation), m = record(c.manifest);
 if (!uuid(r.reservation_id) || !uuid(r.revision_id) || !positive(r.version) || r.store_id !== store || r.family !== family || !token(r.workflow_id) || !researchSource(r.source) || !(r.parent_revision_id === null || uuid(r.parent_revision_id)) || !hash(m.digest) || c.relative_directory !== `final/${family}/v${r.version}` || !(c.publication_intent_id === null || token(c.publication_intent_id))) throw new Error();
 const b = record(m.binding), source = record(r.source), boundSource = record(b.source);
 if (r.registry_id !== b.registry_id || r.registry_id !== undefined && !token(r.registry_id)) throw new Error();
 if (b.parent_revision_id !== r.parent_revision_id || b.version !== r.version || !sameResearchSource(source, boundSource)) throw new Error();
 if ('kind' in r.source && c.publication_intent_id !== null) throw new Error();
 if (b.reservation_id !== r.reservation_id || b.revision_id !== r.revision_id || b.store_id !== store || b.family !== family || b.workflow_id !== r.workflow_id) throw new Error();
 if (c.publication_intent_id === null) {
  if (r.publication_request != null || b.publication_request != null) throw new Error();
 } else {
  const request = record(r.publication_request), bound = record(b.publication_request);
  if (Object.keys(request).length !== 2 || Object.keys(bound).length !== 2 || request.effect_id !== c.publication_intent_id || bound.effect_id !== request.effect_id || !sameTarget(request.target_profile, bound.target_profile)) throw new Error();
 }
 return { commit: c, reservation: r, manifest: m };
}
const options = { retry: false, gcTime: 0, staleTime: 0, refetchOnWindowFocus: false, refetchOnReconnect: false } as const;
interface VersionsProps { candidate?: Job; publicationExecution?: boolean; manualSource?: ManualInput; manualWriteAllowed?: boolean; isManualWriteCurrent?: () => boolean; isResearchOpenCurrent?: () => boolean; onResearchOpen?: (source: ResearchOpen, isAuthorized: () => boolean) => void; isCurrent?: () => boolean; bindingKey?: string }
export function ResearchVersions(props: VersionsProps) {
 const { api, session, status } = useRuntime();
 if (!session || status === 'expired' || api.session?.session_id !== session.session_id) return <section aria-label="Research versions"><button type="button" disabled>Open research versions</button><p>Connect a session to browse research versions.</p></section>;
 return <SessionVersions key={clientSessionScope(api, session).id} {...props} />;
}
function SessionVersions(props: VersionsProps) {
 const [open, setOpen] = useState(false);
 return <section aria-label="Research versions"><button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Close research versions' : 'Open research versions'}</button>{open && <VersionBrowser {...props} />}</section>;
}
function VersionBrowser({ candidate, publicationExecution, manualSource, manualWriteAllowed = false, isManualWriteCurrent, isResearchOpenCurrent, onResearchOpen, isCurrent, bindingKey }: VersionsProps) {
 const { api, session } = useRuntime();
 const cache = useQueryClient();
 const scope = [session!.session_id, api.sessionGeneration];
 const clientKey = clientSessionScope(api, session).id;
 const initial = record(record(candidate?.result).validation).spec;
 const name = record(initial).env_name;
 const [familyChoice, setFamily] = useState(token(name) ? name : '');
 const [storeChoice, setStore] = useState('');
 const [pages, setPages] = useState([0]);
 const [selected, setSelected] = useState<Version | null>(null);
 const [parentChoice, setParent] = useState('');
 const [sourceChoice, setSourceChoice] = useState('candidate');
 const manual = sourceChoice === 'manual';
 const [prepare, setPrepare] = useState(false), [profileChoice, setProfile] = useState<PublicationTarget | null>(null);
 const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
 const active = useRef(true), dispatching = useRef(false);
 const epoch = api.sessionGeneration;
 useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
 const latestProps = useRef({ api, bindingKey, manualSource, onResearchOpen, isCurrent });
 latestProps.current = { api, bindingKey, manualSource, onResearchOpen, isCurrent };
 const controls = useRef({inputs: '', serial: 0});
 const inputs = JSON.stringify([bindingKey, manualSource, manualWriteAllowed, sourceChoice, storeChoice, familyChoice, parentChoice, selected, !!onResearchOpen]);
 if (controls.current.inputs !== inputs) controls.current = {inputs, serial: controls.current.serial + 1};
 const serial = controls.current.serial;
 const current = () => active.current && latestProps.current.api === api && api.sessionGeneration === epoch && api.session?.session_id === session!.session_id;
 const fresh = () => current() && controls.current.serial === serial && latestProps.current.bindingKey === bindingKey && (isCurrent?.() ?? true);
 // Permission is independent of the original source offer. Frozen retries need
 // current write admission, not a rediscovered revision or a replacement payload.
 const manualAuthorized = () => fresh() && manualWriteAllowed === true && (isManualWriteCurrent?.() ?? true);
 const detailEpoch = useRef(0);
 const renderedDetailEpoch = detailEpoch.current;
 const selection = JSON.stringify([storeChoice, familyChoice, selected, pages]);
 const selectedAuthority = useRef({selection});
 if (selectedAuthority.current.selection !== selection) selectedAuthority.current = {selection};
 const renderedSelection = selectedAuthority.current;
 // Capture the rendered permission epoch, not the latest callback's authority:
 // retained handlers must not borrow replacement admission after capability ABA.
 const researchAuthorized = () => current() && renderedSelection === selectedAuthority.current && renderedDetailEpoch === detailEpoch.current && !!latestProps.current.onResearchOpen && (isResearchOpenCurrent?.() ?? true);
 useLayoutEffect(() => cache.getQueryCache().subscribe(event => {
  if ((event.type === 'updated' || event.type === 'removed') && event.query.queryKey[0] === 'research-version' && event.query.queryKey[1] === session!.session_id && event.query.queryKey[2] === epoch) detailEpoch.current++;
 }), [cache, api, epoch, session!.session_id]);
 const readPending = (): { pending: Frozen | null; blocked: boolean } => {
  try {
   const raw = sessionStorage.getItem(STORAGE); if (raw === null) return { pending: null, blocked: false };
   if (raw.length > 4096) throw new Error();
   const f = JSON.parse(raw) as Frozen, b = record(f.body);
   if (Object.keys(record(f)).some(k => !['session', 'store', 'source', 'body'].includes(k))) throw new Error();
   if (b.source !== undefined) {
    if (typeof f.session !== 'string' || !token(f.store) || !isManualInput(f.source) || !isManualInput(b.source) || Object.entries(f.source).some(([k,v]) => record(b.source)[k] !== v) || !token(b.idempotency_key) || !token(b.family) || !(b.parent_revision_id === null || uuid(b.parent_revision_id)) || Object.keys(b).some(k => !['idempotency_key', 'family', 'source', 'parent_revision_id'].includes(k))) throw new Error();
    return {pending: f, blocked: false};
   }
   if (Object.keys(record(f.source)).some(k => !['job_id', 'attempt_id', 'generation', 'receipt_sha256', 'request_sha256'].includes(k))) throw new Error();
   if (typeof f.session !== 'string' || !token(f.store) || !candidateRef(f.source) || !token(b.idempotency_key) || !token(b.family) || !uuid(b.source_job_id) || !uuid(b.source_attempt_id) || !positive(b.source_generation) || !(b.parent_revision_id === undefined || uuid(b.parent_revision_id)) || ('publication_target' in b && !publicationTarget(b.publication_target)) || Object.keys(b).some(k => !['idempotency_key', 'family', 'source_job_id', 'source_attempt_id', 'source_generation', 'parent_revision_id', 'publication_target'].includes(k)) || f.source.job_id !== b.source_job_id || f.source.attempt_id !== b.source_attempt_id || f.source.generation !== b.source_generation) throw new Error();
   return { pending: f, blocked: false };
  } catch { return { pending: null, blocked: true }; }
 };
 const [retained, setRetained] = useState(readPending);
 // Same-tab JavaScript run-to-completion makes the check/action pairs synchronous:
 // no await between ownership comparison and POST/storage mutation. This is not
 // cross-context atomic CAS. Never poll or automatically adopt/retry another request.
 function owns(f: Frozen) {
  const stored = readPending();
  return !stored.blocked && stored.pending !== null && JSON.stringify(stored.pending) === JSON.stringify(f);
 }
 function ownershipLost() {
  setRetained({ pending: null, blocked: true });
  setMessage('Pending research save ownership changed. Close and reopen to review current storage; no newer request was dispatched or discarded.');
 }
 const family = retained.pending?.body.family ?? familyChoice;
 const store = retained.pending?.store ?? storeChoice;
 const parent = retained.pending?.body.parent_revision_id ?? (retained.pending ? '' : parentChoice);
 const locked = busy || !!retained.pending || retained.blocked;
 const eligible = isJob(candidate) && candidate.kind === 'generate' && uuid(candidate.id) && ['succeeded', 'cancelled'].includes(candidate.status) && candidate.execution?.outcome === 'candidate_accepted' && candidate.execution.released === true && candidate.execution.candidate_accepted === true && typeof candidate.result?.yaml_text === 'string' && candidate.result.yaml_text.length > 0 && record(candidate.result.validation).valid === true;
 const after = pages[pages.length - 1];
 const stores = useQuery({ ...options, queryKey: ['research-stores', ...scope, clientKey], queryFn: async () => {
  const r = record(await api.get<unknown>('/research/stores'));
  if (!Array.isArray(r.stores) || r.stores.length > 100 || !r.stores.every(v => token(record(v).store_id) && typeof record(v).available === 'boolean')) throw new Error();
  return r.stores.map(v => ({ store_id: record(v).store_id as string, available: record(v).available === true }));
 } });
 const available = stores.data?.some(s => s.store_id === store && s.available) === true;
 const profiles = useQuery({ ...options, queryKey: ['research-publication-profiles', ...scope, clientKey], enabled: !manual && prepare && !locked, queryFn: async () => {
  // Catalogue rows include available:true; frozen POST targets contain only the other three fields.
  const r = record(await api.get<unknown>('/research/publication-profiles'));
  if (!Array.isArray(r.profiles) || r.profiles.length > 16 || !r.profiles.every(v => { const { available, ...t } = record(v); return available === true && publicationTarget(t); }) || new Set(r.profiles.map(v => record(v).profile_id)).size !== r.profiles.length) throw new Error();
  return r.profiles.map(v => { const p = record(v); return { profile_id: p.profile_id, revision: p.revision, scope_ownership: p.scope_ownership } as PublicationTarget; });
 } });
 const chosenTarget = profiles.data?.find(p => sameTarget(p, profileChoice));
 const base = `/research/stores/${store}/versions`;
 const source = useQuery({ ...options, queryKey: ['research-candidate', ...scope, store, family, eligible ? candidate.id : null, clientKey], enabled: !manual && available && eligible && token(family) && !locked, queryFn: async () => {
  const r = await api.get<unknown>(`/research/stores/${store}/candidates/${candidate!.id}`);
  if (!candidateRef(r) || r.job_id !== candidate!.id) throw new Error();
  return { job_id: r.job_id, attempt_id: r.attempt_id, generation: r.generation, receipt_sha256: r.receipt_sha256, request_sha256: r.request_sha256 };
 } });
 const listing = useQuery({ ...options, queryKey: ['research-versions', ...scope, store, family, after, clientKey], enabled: available && token(family), queryFn: async () => {
  const r = record(await api.get<unknown>(`${base}?family=${encodeURIComponent(family)}&after_version=${after}&limit=25`));
  if (!Array.isArray(r.versions) || r.versions.length > 25 || !r.versions.every(v => version(v) && (v.source === undefined && v.open_source === undefined || (v.manifest_digest === null ? v.open_source === null : Object.keys(record(v.open_source)).length === 2 && record(v.open_source).kind === 'research_version' && record(v.open_source).id === `research-version:${store}:${v.reservation_id}:${v.manifest_digest}`)) && !(v.source && 'kind' in v.source && record(v).publication_intent_id != null)) || new Set(r.versions.map(v => record(v).reservation_id)).size !== r.versions.length || !(r.latest_version === null || positive(r.latest_version)) || !(r.next_after_version === null || positive(r.next_after_version) && r.next_after_version > after)) throw new Error();
  return { versions: r.versions as Version[], latest: r.latest_version as number | null, next: r.next_after_version as number | null };
 } });
 function checkedSelection(raw: unknown) {
  try {
   const c = checkedCommit(raw, store, family);
   if (c.reservation.reservation_id !== selected!.reservation_id || c.reservation.revision_id !== selected!.revision_id || c.manifest.digest !== selected!.manifest_digest || c.reservation.version !== selected!.version || (selected!.source ? !sameResearchSource(c.reservation.source, selected!.source) : record(c.reservation.source).job_id !== selected!.source_job_id) || c.reservation.parent_revision_id !== selected!.parent_revision_id) throw new Error();
   return c.commit;
  } catch { throw new VersionConflict(); }
 }
 const detail = useQuery({ ...options, queryKey: ['research-version', ...scope, store, family, selected?.reservation_id, clientKey], enabled: available && !!selected, queryFn: async () => {
  return checkedSelection(await api.get<unknown>(`${base}/${selected!.reservation_id}`));
 } });
 // Generic HTTP failures (including 409) do not prove an immutable identity mismatch.
 const detailConflict = detail.error instanceof VersionConflict;
 let detailMatchesSelection = false;
 if (selected && detail.data && !detailConflict) { try { checkedSelection(detail.data); detailMatchesSelection = true; } catch { /* A changed row cannot authenticate cached detail. */ } }
 function reset() { controls.current.serial++; selectedAuthority.current = {...selectedAuthority.current}; setPages([0]); setSelected(null); setParent(''); setMessage(''); }
 async function submit(f: Frozen) {
  const authorized = f.body.source ? manualAuthorized : current;
  if (!authorized() || dispatching.current || f.session !== session!.session_id) return;
  if (!owns(f)) { ownershipLost(); return; }
  dispatching.current = true; setBusy(true); setMessage('');
  try {
   const path = `/research/stores/${f.store}/versions`;
   const returned = await api.mutate<unknown>(path, f.body);
   if (!authorized()) return;
   function verify(v: unknown) {
    const c = checkedCommit(v, f.store, f.body.family), r = c.reservation, s = record(r.source);
    if (r.workflow_id !== f.body.idempotency_key || r.parent_revision_id !== (f.body.parent_revision_id ?? null)) throw new Error();
    if (f.body.source ? Object.entries(f.body.source).some(([k,v]) => s[k] !== v) : !sameResearchSource(r.source, f.source)) throw new Error();
    if (f.body.publication_target ? !sameTarget(f.body.publication_target, record(r.publication_request).target_profile) : c.commit.publication_intent_id !== null) throw new Error();
    return c;
   }
   const first = verify(returned);
   const readback = await api.get<unknown>(`${path}/${first.reservation.reservation_id}`);
   if (!authorized()) return;
   const exact = verify(readback);
   if (exact.reservation.reservation_id !== first.reservation.reservation_id || exact.reservation.revision_id !== first.reservation.revision_id || exact.reservation.version !== first.reservation.version || exact.manifest.digest !== first.manifest.digest || !sameResearchSource(exact.reservation.source, first.reservation.source) || exact.commit.publication_intent_id !== first.commit.publication_intent_id) throw new Error();
   if (!owns(f)) { ownershipLost(); return; }
   sessionStorage.removeItem(STORAGE);
   if (sessionStorage.getItem(STORAGE) !== null) throw new Error('Retry cleanup unverified');
   setStore(f.store); setFamily(f.body.family); setParent(''); setRetained({ pending: null, blocked: false });
   setMessage(f.body.publication_target ? `Research version saved and verified. Profile ${f.body.publication_target.profile_id}: prepared, not published. Graph publication was not performed.` : 'Research version saved and verified. Graph publication was not performed.');
   // Invalidate every page of this exact authenticated scope only after readback.
   void cache.invalidateQueries({ queryKey: ['research-versions', session!.session_id, epoch, f.store, f.body.family] });
  } catch { if (authorized()) setMessage('Save unresolved. Retained request must be retried exactly; no success has been verified.'); }
  finally { dispatching.current = false; if (current()) setBusy(false); }
 }
 function recover() {
  const f = retained.pending;
  if (!current() || !f || busy || f.session === session!.session_id) return;
  // The persistence route declares one workspace principal across session renewal.
  // Recovery changes only dispatch authentication, never the frozen request.
  if (!window.confirm(`Recover the exact retained research save under the newly authenticated SAME declared single_operator_workspace principal? Store/family: ${f.store}/${f.body.family}. ${sourceLabel(f.source)}. Parent: ${f.body.parent_revision_id ?? 'none'}. ${preparationLabel(f)} This does not POST; retry requires separate confirmation.`) || !current()) return;
  try {
   if (sessionStorage.getItem(STORAGE) !== JSON.stringify(f)) throw new Error();
   const recovered = { ...f, session: session!.session_id };
   sessionStorage.setItem(STORAGE, JSON.stringify(recovered));
   setRetained({ pending: recovered, blocked: false });
  } catch { setMessage('Recovery unavailable. The exact retained request has not been dispatched.'); }
 }
 function save() {
  if (manual) { saveManual(); return; }
  if (!current() || locked || !available || !eligible || !source.data || !token(family) || prepare && (!chosenTarget || profiles.isError || profiles.isFetching) || parent && (!selected || !detail.data || parent !== selected.revision_id)) return;
  const f: Frozen = { session: session!.session_id, store, source: { ...source.data }, body: { idempotency_key: crypto.randomUUID(), family, source_job_id: source.data.job_id, source_attempt_id: source.data.attempt_id, source_generation: source.data.generation, ...(parent ? { parent_revision_id: parent } : {}), ...(prepare && chosenTarget ? { publication_target: { ...chosenTarget } } : {}) } };
  if (!window.confirm(`Save accepted source as a research version in ${f.store}/${f.body.family}? Parent: ${f.body.parent_revision_id || 'none'}. ${preparationLabel(f)} This does not publish to the graph.`)) return;
  if (!current()) return;
  try { const stored = readPending(); if (stored.blocked || stored.pending) { ownershipLost(); return; } sessionStorage.setItem(STORAGE, JSON.stringify(f)); setRetained({ pending: f, blocked: false }); }
  catch { setRetained({ pending: null, blocked: true }); return; }
  void submit(f);
 }
 function saveManual() {
  if (!manualAuthorized() || locked || !available || !isManualInput(manualSource) || !token(family) || !parentChoice || parentChoice !== 'none' && (!selected || !detailMatchesSelection || detail.isFetching || detail.isError || parentChoice !== selected.revision_id)) return;
  const f: Frozen = {session: session!.session_id, store, source: manualInput(manualSource), body: {idempotency_key: crypto.randomUUID(), family, parent_revision_id: parentChoice === 'none' ? null : parentChoice, source: manualInput(manualSource)}};
  if (!window.confirm(`Save numbered research version in ${store}/${family}? ${sourceLabel(f.source)}. Parent: ${f.body.parent_revision_id ?? 'none'}. This saves the verified durable revision, NOT the current draft. Manual graph publication is unsupported.`) || !manualAuthorized()) return;
  try { const stored = readPending(); if (stored.blocked || stored.pending) { ownershipLost(); return; } sessionStorage.setItem(STORAGE, JSON.stringify(f)); setRetained({pending: f, blocked: false}); }
  catch { setRetained({pending: null, blocked: true}); return; }
  void submit(f);
 }
 let exactOpen: ResearchOpen | undefined;
 if (detailMatchesSelection && detail.data && !detail.isFetching && !detail.isError) { try { exactOpen = researchOpen(record(detail.data.reservation), record(detail.data.manifest)); } catch { /* Viewing legacy metadata does not invent opening evidence. */ } }
 return <>
  <p>Research versions preserve accepted generated source or a verified durable editor revision. Draft saving is separate. This does not publish to the research graph or replace editor YAML.</p>
  {manualSource && <label>Research save source<select disabled={locked} value={sourceChoice} onChange={e => {setSourceChoice(e.target.value); setParent(''); setPrepare(false); setProfile(null);}}><option value="candidate">Accepted generation candidate</option><option value="manual">Verified durable editor revision</option></select></label>}
  {manual && manualSource && <p>{sourceLabel(manualSource)}. Saves this immutable revision, not the current draft. Manual publication is unsupported.</p>}
  {stores.isPending && <p role="status">Loading research stores…</p>}
  {stores.isError && <p role="alert">Research stores unavailable. <button type="button" onClick={() => void stores.refetch()}>Retry stores</button></p>}
  {stores.data?.length === 0 && <p>No research stores configured.</p>}
  <label>Research store<select disabled={locked} value={store} onChange={e => { setStore(e.target.value); reset(); }}><option value="">Select a store</option>{retained.pending && !stores.data?.some(s => s.store_id === store) && <option value={store}>{store}</option>}{stores.data?.map(s => <option key={s.store_id} value={s.store_id} disabled={!s.available}>{s.store_id}{s.available ? '' : ' — unavailable'}</option>)}</select></label>
  <label>Research family<input disabled={locked} value={family} maxLength={64} onChange={e => { setFamily(e.target.value); reset(); }} /></label>
  {!token(family) && <p role="alert">Enter a valid family: 1–64 ASCII letters, digits, underscores or hyphens; begin with a letter or digit. Source names are not repaired.</p>}
  {listing.isFetching && <p role="status">Loading versions…</p>}
  {listing.isError && <p role="alert">Versions unavailable. <button type="button" onClick={() => void listing.refetch()}>Retry versions</button></p>}
  {listing.data && <><p>Latest committed version: {listing.data.latest ?? 'none'}</p><ul>{listing.data.versions.map(v => <li key={v.reservation_id}>{v.source && <p>{sourceLabel(v.source)}</p>}{v.state === 'reserved' || v.state === 'RESERVED' ? <span>Version {v.version} — reserved, not committed</span> : <button type="button" disabled={locked} onClick={() => { setSelected(v); setParent(''); }}>Select version {v.version}</button>}</li>)}</ul>
   <button type="button" aria-label="Previous versions page" disabled={locked || pages.length === 1} onClick={() => { setPages(pages.slice(0, -1)); setSelected(null); setParent(''); }}>Previous</button>
   <button type="button" aria-label="Next versions page" disabled={locked || listing.data.next === null} onClick={() => { setPages([...pages, listing.data!.next!]); setSelected(null); setParent(''); }}>Next</button></>}
  <label>Parent revision<select disabled={locked} value={parent} onChange={e => setParent(e.target.value)}><option value="">{manual ? 'Choose parent explicitly' : 'None'}</option>{manual && <option value="none">None — start without a parent</option>}{retained.pending && parent && <option value={parent}>{parent}</option>}{!retained.pending && selected && detail.data && <option value={selected.revision_id}>{selected.revision_id}</option>}</select></label>
  {!manual && !eligible && <p>No eligible accepted, validated generation candidate is selected.</p>}
  {!manual && !retained.pending?.body.source && <label><input type="checkbox" checked={retained.pending ? !!retained.pending.body.publication_target : prepare} disabled={locked} onChange={e => { setPrepare(e.target.checked); setProfile(null); }} />Prepare publication on save</label>}
  {prepare && <label>Publication profile<select value={chosenTarget?.profile_id ?? ''} disabled={locked} onChange={e => { const p = profiles.data?.find(p => p.profile_id === e.target.value); setProfile(p ? { ...p } : null); }}><option value="">Select a publication profile</option>{profiles.data?.map(p => <option key={p.profile_id} value={p.profile_id}>{p.profile_id} — {p.revision} — {p.scope_ownership}</option>)}</select></label>}
  {prepare && profiles.isError && <p role="alert">Publication profiles unavailable.</p>}
  {prepare && profiles.data?.length === 0 && <p>No publication profiles configured.</p>}
  {source.isError && <p role="alert">Exact candidate reference unavailable.</p>}
  <button type="button" disabled={locked || !available || !token(family) || (manual ? !manualAuthorized() || !isManualInput(manualSource) || !parentChoice : !eligible || !source.data || prepare && (!chosenTarget || profiles.isError || profiles.isFetching))} onClick={save}>{manual ? 'Save numbered research version' : 'Save research version'}</button>
  {retained.blocked && <p role="alert">Retained request storage is unavailable or invalid. Saving is blocked; resolve browser retry storage before continuing.</p>}
  {retained.pending?.body.publication_target && <p>Retained publication target: {retained.pending.body.publication_target.profile_id} — {retained.pending.body.publication_target.revision} — {retained.pending.body.publication_target.scope_ownership}. Preparation is unresolved; this does not publish.</p>}
  {retained.pending?.body.source && !manualAuthorized() && <p>Manual research writes unavailable. Frozen request retained; browsing does not retry or prove acceptance.</p>}
  {retained.pending && <><p role="status">Unresolved research save retained for {retained.pending.store}/{retained.pending.body.family}. {sourceLabel(retained.pending.source)}. No automatic retry.</p><button type="button" disabled={busy || retained.pending.session !== session!.session_id || !!retained.pending.body.source && !manualAuthorized()} onClick={() => { const f = retained.pending!; if (!(f.body.source ? manualAuthorized() : current())) return; if (window.confirm(`Retry the exact retained research save? ${preparationLabel(f)}`)) void submit(f); }}>Retry exact research save</button>{retained.pending.session !== session!.session_id && <><p>Request belongs to another session. Explicit recovery under the same declared workspace principal is required before retry.</p><button type="button" onClick={recover}>Recover exact research save in this session</button></>}</>}
  {message && <p role="status">{message}</p>}
  {exactOpen && onResearchOpen && <button type="button" disabled={!researchAuthorized()} onClick={() => { if (fresh() && researchAuthorized()) latestProps.current.onResearchOpen?.(exactOpen!, researchAuthorized); }}>Open research version in editor</button>}
  {detail.isError && <><p role="alert">Version details could not be verified.</p><button type="button" disabled={detail.isFetching} onClick={() => void detail.refetch()}>Retry version details</button></>}
  {selected && detail.data && detailMatchesSelection && <section aria-label="Selected committed version"><h4>Manifest</h4><PropertyTree key={`${store}:${selected.reservation_id}`} value={detail.data.manifest} /><h4>Lineage</h4><PropertyTree value={detail.data.reservation} /><p>{detail.data.publication_intent_id === null ? 'Unprepared existing version: no publication intent was saved.' : 'Prepared version: publication status unchecked; an intent is not proof of publication.'} No retroactive publication intent mutation is supported; preparation applies only to a new save.</p><a download="environment.yaml" href={`/api${base}/${selected.reservation_id}/artifacts/environment.yaml`}>Download verified source</a>{publicationExecution === true && available && !detailConflict && detail.data.publication_intent_id !== null && <PublicationPanel detailVerified={!detail.isFetching && !detail.isError} key={`${store}:${selected.reservation_id}:${detail.data.manifest && record(detail.data.manifest).digest}`} storeId={store} commit={detail.data} />}</section>}
 </>;
}
