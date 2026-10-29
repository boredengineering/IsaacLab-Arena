import { useEffect, useRef, useState } from 'react';
import { PublicationControls, type PublicationControlsProps } from './publication-controls';
import { useRuntime } from './runtime';

type Binding = Omit<PublicationControlsProps, 'enabled' | 'mutationEnabled'>;
const record = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {};
const token = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(v);
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const keys = (v: unknown, names: string) => Object.keys(record(v)).sort().join(',') === names.split(',').sort().join(',');
const canonical = (v: unknown): string => v === null || typeof v !== 'object' ? JSON.stringify(v) : Array.isArray(v) ? '[' + v.map(canonical).join(',') + ']' : '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonical(record(v)[k])).join(',') + '}';
function checkedBinding(value: unknown, storeId: string, commit: Record<string, unknown>): Binding {
 const b = record(value), t = record(b.target), ref = record(b.versionRef), canonical = record(ref.canonical_identity);
 const r = record(commit.reservation), request = record(r.publication_request), target = record(request.target_profile);
 if (!keys(b, 'storeId,effectId,registryId,target,versionRef') || !token(b.storeId) || b.storeId !== storeId || !token(b.effectId) || b.effectId !== commit.publication_intent_id || b.effectId !== request.effect_id || !token(b.registryId) || b.registryId !== r.registry_id) throw Error();
 if (!keys(t, 'profile_id,revision,scope_ownership') || !token(t.profile_id) || !hash(t.revision) || t.scope_ownership !== 'cooperative_immutable' || ['profile_id', 'revision', 'scope_ownership'].some(k => t[k] !== target[k])) throw Error();
 if (!keys(ref, 'reservation_id,revision_id,version,payload_sha256,projection_digest,scope_id,database,canonical_identity') || ['reservation_id', 'revision_id', 'version'].some(k => ref[k] !== r[k]) || !hash(ref.payload_sha256) || !hash(ref.projection_digest) || !token(ref.scope_id)) throw Error();
 // Canonical scene names are not route tokens. Keep the full backend identity.
 if (typeof ref.database !== 'string' || /^\p{White_Space}*$/u.test(ref.database) || /[\u0000-\u001f]/.test(ref.database) || new TextEncoder().encode(ref.database).length > 256 || !keys(canonical, 'name,sha256') || typeof canonical.name !== 'string' || canonical.name.length === 0 || !hash(canonical.sha256)) throw Error();
 return value as Binding;
}
interface PanelProps { storeId: string; commit: Record<string, unknown>; detailVerified?: boolean }
export function PublicationPanel(props: PanelProps) {
 const { api, session } = useRuntime();
 // Retention belongs to this immutable opening, never to a route or query cache.
 const identity = canonical([props.storeId, props.commit.reservation, record(props.commit.manifest).digest, props.commit.publication_intent_id, session?.session_id, api.sessionGeneration]);
 return <PublicationOpening key={identity} {...props} />;
}
function PublicationOpening({ storeId, commit: incomingCommit, detailVerified = true }: PanelProps) {
 const { api, session, status } = useRuntime();
 const [commit] = useState(() => structuredClone(incomingCommit));
 const [owner] = useState(session?.session_id), [epoch] = useState(api.sessionGeneration);
 const [open, setOpen] = useState(false);
 const current = () => !!owner && api.session?.session_id === owner && api.sessionGeneration === epoch && status !== 'expired';
 return <section aria-label="Publication execution">
  <button type="button" disabled={!current() || !open && !detailVerified} aria-expanded={open} onClick={() => { if (current() && (open || detailVerified)) setOpen(!open); }}>{open ? 'Close publication execution' : 'Open publication execution'}</button>
  {open && current() && <BindingView storeId={storeId} commit={commit} owner={owner!} epoch={epoch} detailVerified={detailVerified} />}
 </section>;
}
function BindingView({ storeId, commit, owner, epoch, detailVerified }: { storeId: string; commit: Record<string, unknown>; owner: string; epoch: number; detailVerified: boolean }) {
 const { api } = useRuntime();
 const [binding, setBinding] = useState<Binding | null>(null), [error, setError] = useState(false);
 const [attempt, setAttempt] = useState(0), [verifiedAttempt, setVerifiedAttempt] = useState(-1), [loading, setLoading] = useState(true);
 const invalidatedAttempt = useRef(-1);
 const verifiedBinding = useRef<Binding | null>(null);
 const reservation = commit.reservation as Record<string, unknown>;
 useEffect(() => {
  let active = true;
  const current = () => active && api.sessionGeneration === epoch && api.session?.session_id === owner;
  if (!current()) return;
  if (!detailVerified) { invalidatedAttempt.current = attempt; setVerifiedAttempt(-1); setLoading(false); return; }
  if (invalidatedAttempt.current >= attempt) return;
  setLoading(true); setError(false);
  void api.get<unknown>(`/research/stores/${storeId}/versions/${reservation.reservation_id}/publication-binding`).then(value => {
   if (!current()) return;
   try {
    const next = checkedBinding(value, storeId, commit);
    if (verifiedBinding.current && canonical(next) !== canonical(verifiedBinding.current)) throw Error();
    verifiedBinding.current = structuredClone(next); setBinding(verifiedBinding.current); setVerifiedAttempt(attempt);
   } catch { setBinding(null); setError(true); }
  }).catch(() => { if (current()) setError(true); }).finally(() => { if (current()) setLoading(false); });
  return () => { active = false; };
 }, [api, owner, epoch, storeId, reservation, commit, attempt, detailVerified]);
 return <>
  <p>Viewing a binding does not access the graph or publish. Publication status is unknown until checked; operator configuration is required for execution.</p>
  <button type="button" disabled={loading || !detailVerified} onClick={() => { if (detailVerified && api.sessionGeneration === epoch && api.session?.session_id === owner) { setLoading(true); setAttempt(n => n + 1); } }}>Revalidate publication binding</button>
  {binding && (!detailVerified || error || loading || verifiedAttempt !== attempt) && <p role="status">Previously verified scope retained for disposition checking only. Current binding unavailable; all POST actions, including graph-read reconciliation, are disabled.</p>}
  {binding ? <PublicationControls enabled mutationEnabled={detailVerified && !loading && !error && verifiedAttempt === attempt} {...binding} /> : <><button type="button" disabled>Open publication controls</button><p role={error ? 'alert' : 'status'}>{error ? 'Publication binding unavailable. Publication status unknown; operator configuration required. Revalidate explicitly to retry.' : 'Loading verified publication binding…'}</p></>}
 </>;
}
