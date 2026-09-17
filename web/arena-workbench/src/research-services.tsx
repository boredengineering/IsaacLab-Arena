import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ControlClient, ControlError, type ServiceStatus, type StartRequest } from './control-api';

const PENDING_KEY = 'arena.research-services.pending.v1';
const RETENTION_ERROR = 'Request retention unavailable or changed. No replacement Start is allowed; reconcile the original request with the operator.';
function retained(): { raw: string | null; request: StartRequest | null } {
  const raw = sessionStorage.getItem(PENDING_KEY);
  if (raw === null) return { raw, request: null };
  if (raw.length > 256) throw new Error();
  const v = JSON.parse(raw);
  if (!v || Object.keys(v).sort().join(',') !== 'profile_revision,request_id' || typeof v.request_id !== 'string' || !/^[0-9a-f]{32}$/.test(v.request_id) || typeof v.profile_revision !== 'string' || !/^[0-9a-f]{64}$/.test(v.profile_revision)) throw new Error();
  const request = { request_id: v.request_id, profile_revision: v.profile_revision };
  // This new version writes one canonical form; do not normalize damaged/duplicate records.
  if (raw !== JSON.stringify(request)) throw new Error();
  return { raw, request };
}

export function ResearchServices({ client: supplied }: { client?: ControlClient }) {
  const client = useMemo(() => supplied ?? new ControlClient(), [supplied]);
  const token = useRef<HTMLInputElement>(null);
  const owner = useMemo(() => ({ active: false, epoch: 0, busy: false, read: 0 }), [client]);
  const [status, setStatus] = useState<ServiceStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState<StartRequest | null>(null);
  const retention = useMemo(() => ({ raw: null as string | null, blocked: false }), [client]);
  useLayoutEffect(() => {
    owner.active = true; owner.epoch++; owner.busy = false; setEpoch(owner.epoch);
    const input = token.current;
    setStatus(null); setBusy(false); setError(''); setMessage('');
    try { const found = retained(); retention.raw = found.raw; setPending(found.request); }
    catch { retention.blocked = true; setError(RETENTION_ERROR); }
    return () => { owner.active = false; owner.epoch++; client.retire(); if (input) input.value = ''; };
  }, [client, owner, retention]);
  const generation = client.generation;
  const readEpoch = owner.read;
  const current = () => owner.active && owner.epoch === epoch && client.generation === generation;
  function checkRetention(allowMemoryRead = false): boolean {
    try {
      if (retained().raw !== retention.raw) throw new Error(RETENTION_ERROR);
      return true;
    } catch (e) {
      retention.blocked = true;
      // Only an already validated mount-local target may survive denied storage reads.
      // Malformed/replaced sibling records never grant this fallback or any POST.
      if (allowMemoryRead && e instanceof DOMException && e.name === 'SecurityError') return false;
      throw new Error(RETENTION_ERROR);
    }
  }
  function publish(next: ServiceStatus, target: StartRequest | null) {
    setStatus(next);
    if (!target) return;
    if (!checkRetention(true)) {
      setMessage(next.operation?.status === 'completed'
        ? 'Exact startup request completed; local retention is unavailable. Keep this request for GET-only recovery.'
        : 'Exact request observed; local retention is unavailable. Keep this request for GET-only recovery.');
      return;
    }
    if (next.operation?.status === 'completed' || next.operation?.status === 'failed') {
      try {
        sessionStorage.removeItem(PENDING_KEY);
        if (sessionStorage.getItem(PENDING_KEY) !== null) throw new Error(RETENTION_ERROR);
      } catch {
        retention.blocked = true;
        throw new Error(RETENTION_ERROR);
      }
      retention.raw = null; setPending(null);
      setMessage(next.operation.status === 'completed' ? 'Exact startup request completed. This is service startup only.' : 'Exact startup request failed. Service or API startup may be partial; inspect status before a new explicit request.');
    } else setMessage('Exact request remains in progress or unknown. Reconcile with GET only; no automatic or replacement Start.');
  }
  async function read(pair = false, recover = false) {
    if (!current() || owner.busy || owner.read !== readEpoch) return;
    owner.busy = true; owner.read++; setBusy(true); setError(''); setStatus(null);
    const lifetime = () => owner.active && owner.epoch === epoch;
    const input = token.current;
    const value = pair ? input?.value : undefined;
    if (input) input.value = '';
    let requestGeneration = generation;
    try {
      if (pair || recover) {
        const pairing = client.pair(recover ? undefined : value); requestGeneration = client.generation;
        await pairing;
      }
      if (!lifetime() || client.generation !== requestGeneration) return;
      checkRetention(!!pending);
      const next = await client.observe(pending ?? undefined);
      if (lifetime() && client.generation === requestGeneration) publish(next, pending);
    } catch (e) {
      if (lifetime() && (client.generation === requestGeneration || e instanceof ControlError && e.code === 'unauthorized')) setError(e instanceof ControlError ? e.message : RETENTION_ERROR);
    } finally { if (lifetime()) { owner.busy = false; setBusy(false); if (input) input.value = ''; } }
  }
  async function revoke() {
    if (!current() || owner.busy || !client.paired) return;
    owner.busy = true; owner.read++; setBusy(true); setError(''); setStatus(null);
    if (token.current) token.current.value = '';
    try {
      await client.revoke();
      if (owner.active && owner.epoch === epoch) setMessage('Control session ended. Existing service requests were not cancelled.');
    } catch (e) {
      if (owner.active && owner.epoch === epoch) setError(e instanceof ControlError ? e.message : 'Control revocation could not be verified.');
    } finally {
      if (owner.active && owner.epoch === epoch) { owner.busy = false; setBusy(false); }
    }
  }
  async function start() {
    const allowed = () => current() && !owner.busy && owner.read === readEpoch && !pending && !retention.blocked && status?.startup_allowed && client.paired;
    if (!allowed()) return;
    const target = { request_id: crypto.randomUUID().replaceAll('-', ''), profile_revision: status!.profile_revision };
    if (!window.confirm(`Start only the operator-approved arena, neo4j and gr00t services and Arena API?\nProfile: ${target.profile_revision}\nExpected policy: ${status!.expected_policy}\nThis can load cached model weights, allocate GPU/RAM, start the database and API, and create approved runtime state. No download, inference, simulation, graph query/publication or job replay is authorized. Existing Arena reconnection remains explicit.`) || !allowed()) return;
    owner.busy = true; owner.read++; setBusy(true); setError(''); setMessage('');
    try {
      checkRetention();
      if (retention.raw !== null) throw new Error(RETENTION_ERROR);
      retention.raw = JSON.stringify(target);
      sessionStorage.setItem(PENDING_KEY, retention.raw);
      checkRetention(); setPending(target);
      await client.start(target);
      if (!current()) return;
      const next = await client.observe(target);
      if (current()) publish(next, target);
    } catch (e) {
      if (current() || owner.active && owner.epoch === epoch && e instanceof ControlError && e.code === 'unauthorized') {
        if (!(e instanceof ControlError)) retention.blocked = true;
        setStatus(null);
        setError(e instanceof ControlError ? e.message : RETENTION_ERROR);
        setMessage('Start acceptance or readback is unresolved. Retain this request and use GET-only reconciliation; do not submit a replacement.');
      }
    } finally { if (owner.active && owner.epoch === epoch) { owner.busy = false; setBusy(false); } }
  }
  return <section className="research-services notice" aria-label="Research stack">
    <h2>Research stack</h2>
    <p>Independent host control. Pairing does not connect an Arena session or run a workflow.</p>
    <label>Control pairing token <input ref={token} type="password" autoComplete="off" maxLength={256} disabled={busy} /></label>
    <button type="button" disabled={busy} onClick={() => void read(true)}>Pair control</button>
    <button type="button" disabled={busy} onClick={() => void read(false, true)}>Recover control session</button>
    <button type="button" disabled={busy || !client.paired} onClick={() => void revoke()}>End control session</button>
    {!client.paired && <p>Control not paired. Helper installation and approved targets require operator configuration.</p>}
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {pending && <p>Retained request: <code>{pending.request_id}</code> · profile <code>{pending.profile_revision}</code>. GET-only reconciliation; no replay.</p>}
    <button type="button" disabled={busy || !client.paired} onClick={() => void read()}>{pending ? 'Reconcile exact startup request' : 'Refresh service status'}</button>
    {status && <div>
      <p>Expected policy: {status.expected_policy}</p>
      <p>Approved profile: <code>{status.profile_revision}</code></p>
      {status.services.map(s => <p key={s.id}>{s.id}: {s.status}</p>)}
      <p>API: {status.api}</p>
      {status.operation && <p>Observed helper operation: {status.operation.status} · {status.operation.code}. Request <code>{status.operation.request_id}</code>, profile <code>{status.operation.profile_revision}</code>. Observation is not new execution consent.</p>}
      {!status.startup_allowed && <p>Startup not admitted. Missing, mismatched or unavailable targets require operator review.</p>}
    </div>}
    <button type="button" disabled={busy || !client.paired || !status?.startup_allowed || !!pending || retention.blocked} onClick={() => void start()}>Start approved services</button>
    <p>Service startup is not inference, simulation, graph-read or task-success evidence. Reconnect Arena explicitly using the existing session control.</p>
  </section>;
}
