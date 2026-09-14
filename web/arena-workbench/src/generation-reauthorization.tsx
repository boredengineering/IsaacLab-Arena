import { useLayoutEffect, useRef, useState } from 'react';
import { skipToken, useQuery } from '@tanstack/react-query';
import { isJob, type Job } from './contracts';
import { useRuntime } from './runtime';
import type { ModelSettingsStatus } from './model-settings-contracts';

type Renewal = { idempotency_key: string; credential_ref?: string };
async function fingerprint(payload: Renewal) {
  const bytes = new TextEncoder().encode(JSON.stringify({ credential_ref: payload.credential_ref ?? null, idempotency_key: payload.idempotency_key }));
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
}
async function sealed(value: unknown, jobId: string, payload: Renewal) {
  if (!value || typeof value !== 'object') return false;
  const proof = value as Record<string, unknown>;
  return Object.keys(proof).length === 5 && proof.schema_version === 1 && proof.code === 'renewal_rejected'
    && proof.job_id === jobId && proof.idempotency_key === payload.idempotency_key
    && typeof proof.fingerprint === 'string' && /^[a-f0-9]{64}$/.test(proof.fingerprint)
    && proof.fingerprint === await fingerprint(payload);
}

export function isBlockedGeneration(job: Job) {
  return job.kind === 'generate' && job.status === 'blocked_authorization'
    && ['new', 'refine'].includes(String(job.inputs.operation));
}
export function GenerationReauthorization({ job, onVerified }: { job: Job; onVerified(): void }) {
  const runtime = useRuntime();
  // Subscribe to the editor's existing settings observation, without another request or timer.
  const { data: settings, isError: settingsError } = useQuery<ModelSettingsStatus>({ queryKey: ['model-settings', runtime.session?.session_id], queryFn: skipToken });
  const available = !!runtime.session && !!settings?.configured && !settingsError
    && (settings.source === 'server' || (settings.source === 'session' && !!settings.credential_ref
      && (settings.expires_at ?? 0) * 1000 > Date.now()));
  const storageKey = `arena:reauthorization:v1:${encodeURIComponent(job.id)}`;
  const [retained, setRetained] = useState<{ idempotency_key: string; credential_ref?: string } | null | 'invalid'>(() => {
    try {
      const raw = sessionStorage.getItem(storageKey);
      if (!raw) return null;
      const value = JSON.parse(raw);
      if (!value || typeof value.idempotency_key !== 'string' || !/^[A-Za-z0-9_.:-]{1,128}$/.test(value.idempotency_key)
        || (value.credential_ref !== undefined && (typeof value.credential_ref !== 'string' || !/^[a-f0-9]{64}$/.test(value.credential_ref)))
        || Object.keys(value).some(key => !['idempotency_key', 'credential_ref'].includes(key))) throw new Error();
      return value;
    } catch { return 'invalid'; }
  });
  const [pending, setPending] = useState(false);
  const canSubmit = !!runtime.session && retained !== 'invalid' && (!!retained || available);
  const [failed, setFailed] = useState(false);
  const [rejected, setRejected] = useState(false);
  const scope = useRef(0);
  const sending = useRef(false);
  useLayoutEffect(() => {
    scope.current++;
    sending.current = false;
    setPending(false);
    setFailed(false);
    setRejected(false);
    return () => { scope.current++; };
  }, [job.id, runtime.session?.session_id]);
  if (!isBlockedGeneration(job)) return null;
  async function renew() {
    if (sending.current || retained === 'invalid' || !canSubmit || !runtime.session) return;
    if (!window.confirm('Reauthorize this generation with the same frozen prompt and profile? This resumes only unreleased work; it does not regenerate uncertain work.')) return;
    const id = job.id;
    const sessionId = runtime.session.session_id;
    const token = scope.current;
    const api = runtime.api;
    const current = () => scope.current === token && api.session?.session_id === sessionId;
    if (!current()) return;
    const payload = Object.freeze(retained ?? { idempotency_key: crypto.randomUUID(), ...(settings?.source === 'session' && settings.credential_ref ? { credential_ref: settings.credential_ref } : {}) });
    sending.current = true;
    setPending(true); setFailed(false);
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(payload));
      setRetained(payload);
      const accepted = await api.mutate<unknown>(`/editor/generations/${encodeURIComponent(id)}/reauthorize`, payload);
      if (!current()) return;
      if (!isJob(accepted) || accepted.id !== id || accepted.kind !== 'generate') throw new Error();
      const verified = await api.get<unknown>(`/jobs/${encodeURIComponent(id)}`);
      if (!current()) return;
      if (!isJob(verified) || verified.id !== id || verified.kind !== 'generate') throw new Error();
      sessionStorage.removeItem(storageKey);
      setRetained(null);
      onVerified();
    } catch (error) {
      let verified = false;
      try {
        if (error instanceof Error && 'status' in error && error.status === 409) verified = await sealed(JSON.parse(error.message), id, payload);
      } catch { /* Unstructured or malformed conflicts remain ambiguous. */ }
      if (current()) { setRejected(verified); setFailed(true); }
    }
    finally { if (current()) { sending.current = false; setPending(false); } }
  }
  async function checkDisposition() {
    if (sending.current || !retained || retained === 'invalid' || !runtime.session) return;
    const token = scope.current;
    const api = runtime.api;
    const sessionId = runtime.session.session_id;
    const current = () => scope.current === token && api.session?.session_id === sessionId;
    if (!current()) return;
    sending.current = true; setPending(true);
    try {
      const fp = await fingerprint(retained);
      if (!current()) return;
      const query = new URLSearchParams({ idempotency_key: retained.idempotency_key, fingerprint: fp });
      const proof = await api.get<unknown>(`/editor/generations/${encodeURIComponent(job.id)}/reauthorization-disposition?${query}`);
      const verified = await sealed(proof, job.id, retained);
      if (current()) { setRejected(verified); setFailed(!verified); }
    } catch { if (current()) setFailed(true); }
    finally { if (current()) { sending.current = false; setPending(false); } }
  }
  function correct() {
    if (!rejected || pending || sending.current || !available || !runtime.session
      || runtime.api.session?.session_id !== runtime.session.session_id) return;
    if (!window.confirm('Use current credentials with a new renewal request ID for this same job? This does not submit approval; confirm reauthorization separately.')) return;
    try {
      const payload = { idempotency_key: crypto.randomUUID(), ...(settings?.source === 'session' && settings.credential_ref ? { credential_ref: settings.credential_ref } : {}) };
      sessionStorage.setItem(storageKey, JSON.stringify(payload));
      setRetained(payload); setRejected(false); setFailed(false);
    } catch { setFailed(true); }
  }
  return <div className="notice warning">
    <p>Authorization is blocked. Explicit approval keeps the same frozen prompt and profile; uncertain work is never regenerated.</p>
    {retained === 'invalid' ? <p role="alert">Cannot read retained renewal information. Check the job journal before resolving this browser storage.</p> : retained && <p>Retry sends the same request ID and frozen credential reference, never a replacement key.</p>}
    <button type="button" disabled={pending || !canSubmit} onClick={() => void renew()}>{pending ? 'Reauthorizing…' : retained && retained !== 'invalid' ? 'Retry reauthorization' : 'Reauthorize generation'}</button>
    {rejected && <><p>The journal sealed this request as rejected. It can never be accepted.</p><button type="button" disabled={pending || !available} onClick={correct}>Use current credentials</button></>}
    {retained && retained !== 'invalid' && !rejected && <button type="button" disabled={pending || !runtime.session} onClick={() => void checkDisposition()}>Check renewal disposition</button>}
    {failed && !rejected && <p role="alert">Reauthorization could not be verified. Retry the same request explicitly.</p>}
  </div>;
}
