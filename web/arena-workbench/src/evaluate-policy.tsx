import { useLayoutEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { clientSessionScope } from './client-session-scope';
import { EditorJobProgress, useEditorJob } from './editor-jobs';
import { useRuntime } from './runtime';
import type { Job } from './contracts';

type ProfileId = 'gr00t-droid' | 'openpi-droid';
interface Profile { id: ProfileId; label: string; remote_host: '127.0.0.1'; remote_port: 5555 | 8000 }
const record = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const isProfile = (value: unknown): value is ProfileId => value === 'gr00t-droid' || value === 'openpi-droid';
const fixedProfile = (value: Record<string, unknown>) => value.headless === true && value.enable_cameras === true && value.num_envs === 1 && value.num_steps === 1000;
const instructionValid = (value: unknown): value is string | null => value === null || typeof value === 'string' && !!value.trim() && new TextEncoder().encode(value).length <= 4000;
export function parseEvaluationProfiles(value: unknown): Profile[] {
  const r = record(value);
  if (!fixedProfile(r) || r.publication !== 'not_requested' || !Array.isArray(r.profiles) || r.profiles.length !== 2) throw new Error('Evaluation profiles unavailable or invalid.');
  const profiles = r.profiles.map(value => {
    const p = record(value);
    if (!isProfile(p.id) || typeof p.label !== 'string' || !p.label.trim() || p.label.length > 200 || p.remote_host !== '127.0.0.1'
      || p.remote_port !== (p.id === 'gr00t-droid' ? 5555 : 8000)) throw new Error('Evaluation profiles unavailable or invalid.');
    return { id: p.id, label: p.label, remote_host: p.remote_host, remote_port: p.remote_port } as Profile;
  });
  if (new Set(profiles.map(p => p.id)).size !== profiles.length) throw new Error('Evaluation profiles unavailable or invalid.');
  return profiles;
}

export function EvaluationControls({ draft, documentId, enabled, available, canLaunch, canDispatch }: {
  draft: string; documentId?: string; enabled: boolean; available: boolean;
  canLaunch: () => boolean; canDispatch: () => boolean;
}) {
  const { api, session } = useRuntime();
  const scope = clientSessionScope(api, session);
  const cache = useQueryClient();
  const controller = useEditorJob('evaluate');
  const [profile, setProfile] = useState<ProfileId>('gr00t-droid');
  const [instruction, setInstruction] = useState('');
  const queryKey = ['evaluation-profiles', scope.id];
  const profiles = useQuery({ queryKey, enabled: available && scope.current(), retry: false, refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      if (signal.aborted || !scope.current() || !canDispatch()) throw new Error('Evaluation profiles are no longer current.');
      try {
        const result = await api.get<unknown>('/editor/evaluation-profiles');
        if (signal.aborted || !scope.current() || !canDispatch()) throw new Error();
        return parseEvaluationProfiles(result);
      } catch { throw new Error('Evaluation profiles unavailable or no longer current.'); }
    },
  });
  const profileEpoch = useRef(0);
  const renderedProfileEpoch = profileEpoch.current;
  useLayoutEffect(() => {
    const query = cache.getQueryCache().find({ queryKey });
    return cache.getQueryCache().subscribe(event => {
      if (event.query === query && event.type === 'updated' && (event.action.type === 'fetch' || event.action.type === 'invalidate')) profileEpoch.current++;
    });
  }, [cache, scope.id]);
  const retry = !!controller.retained && !controller.job;
  const chosen = retry ? controller.retained!.payload.profile : profile;
  function ownsProfiles() {
    const state = cache.getQueryState<Profile[]>(queryKey);
    return scope.current() && renderedProfileEpoch === profileEpoch.current && state?.status === 'success' && state.fetchStatus === 'idle' && !state.isInvalidated
      && state.data === profiles.data && !!state.data?.some(p => p.id === chosen);
  }
  const validInstruction = instructionValid(instruction === '' ? null : instruction);
  const allowed = available && ownsProfiles() && (retry || enabled && validInstruction);
  return <section aria-label="Evaluate policy">
    <h2>Evaluate policy</h2>
    <p>Fixed profile: headless, cameras on, 1 environment, 1000 policy steps; 900-second wall-clock cap. Settling steps are additional.</p>
    <p className="notice warning">Evaluate policy starts GPU simulation and remote inference. The remote policy server must already be running; no service is started here.</p>
    <p className="hint">DROID embodiment only (validated by the backend). A profile identifies a policy class, not a verified server checkpoint. No YAML generation or Neo4j publication.</p>
    <label>Policy profile<select aria-label="Policy profile" value={profile} onChange={e => { if (isProfile(e.target.value)) setProfile(e.target.value); }}>
      {(profiles.data ?? []).map(p => <option key={p.id} value={p.id}>{p.label} — {p.remote_host}:{p.remote_port}</option>)}
    </select></label>
    <label>Language instruction (optional)<textarea aria-label="Language instruction (optional)" value={instruction} onChange={e => setInstruction(e.target.value)} /></label>
    <p className="hint">Leave empty to use the real task description. An explicit instruction must not be blank and must be at most 4000 UTF-8 bytes.</p>
    {!validInstruction && <p role="alert">Instruction must not be blank and must be at most 4000 UTF-8 bytes.</p>}
    <button type="button" disabled={!allowed || controller.busy} onClick={() => {
      if (!allowed || controller.busy || !canDispatch() || !ownsProfiles() || (!retry && !canLaunch())) return;
      controller.submit.mutate({ yaml_text: draft, ...(documentId ? { document_id: documentId } : {}), profile,
        language_instruction: instruction === '' ? null : instruction }, () => canDispatch() && ownsProfiles());
    }}>{controller.submit.isPending ? 'Submitting evaluation…' : retry ? 'Retry evaluation request' : 'Evaluate policy'}</button>
    {!available && <p className="hint">Evaluation unavailable: an active session and advertised policy evaluation adapter are required.</p>}
    {available && !enabled && !retry && <p className="hint">Validate the current draft before evaluating.</p>}
    {profiles.error && <p role="alert">{profiles.error.message}</p>}
    <EditorJobProgress controller={controller} />
    <EvaluationOutcome job={controller.job} active={available} />
  </section>;
}

const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const count = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const artifactNames = ['index.html', 'episode_results_rank0.jsonl', 'eval_telemetry.ttl'] as const;
type ArtifactName = typeof artifactNames[number];
interface Artifact { name: ArtifactName; sha256: string; size: number }
function metricCopy(value: unknown): Record<string, unknown> | null {
  if (value === null) return null;
  let budget = 32000;
  function copy(v: unknown, depth: number): unknown {
    if (--budget < 0 || depth > 20) throw new Error();
    if (v === null || typeof v === 'boolean' || typeof v === 'number' && Number.isFinite(v)) return v;
    if (typeof v === 'string' && v.length <= 128 * 1024) return v;
    if (Array.isArray(v) && v.length <= 32000) return v.map(item => copy(item, depth + 1));
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      const entries = Object.entries(v);
      if (entries.length > 16000) throw new Error();
      return Object.fromEntries(entries.map(([key, item]) => { copy(key, depth + 1); return [key, copy(item, depth + 1)]; }));
    }
    throw new Error();
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error();
  const result = copy(value, 0) as Record<string, unknown>;
  if (new TextEncoder().encode(JSON.stringify(result)).length > 128 * 1024) throw new Error();
  return result;
}
/** Accept only measured results bound to this successful job's frozen evaluation. */
export function parseEvaluationResult(job: Job) {
  const r = record(job.result), i = record(job.inputs);
  if (job.kind !== 'evaluate' || job.status !== 'succeeded' || r.schema_version !== 1 || r.completed !== true
    || r.publication !== 'not_requested' || !fixedProfile(r) || !fixedProfile(i)
    || !hash(r.input_hash) || !hash(r.canonical_hash) || r.input_hash !== i.input_hash || r.canonical_hash !== i.canonical_hash
    || !isProfile(r.profile) || r.profile !== i.profile || !instructionValid(r.language_instruction) || r.language_instruction !== i.language_instruction
    || typeof i.yaml_text !== 'string' || !i.yaml_text.trim() || !(i.document_id === null || typeof i.document_id === 'string')
    || !count(r.episode_count) || !(r.success_count === null || count(r.success_count) && r.success_count <= r.episode_count)
    || !Array.isArray(r.artifacts) || r.artifacts.length > 3 || !Array.isArray(r.warnings) || r.warnings.length > 100
    || !r.warnings.every(w => typeof w === 'string' && w.length <= 2000)) return null;
  const artifacts: Artifact[] = [];
  for (const value of r.artifacts) {
    const a = record(value);
    if (!artifactNames.includes(a.name as ArtifactName) || !hash(a.sha256) || !count(a.size) || artifacts.some(item => item.name === a.name)) return null;
    artifacts.push({ name: a.name as ArtifactName, sha256: a.sha256, size: a.size });
  }
  try {
    return { input_hash: r.input_hash, canonical_hash: r.canonical_hash, profile: r.profile,
      language_instruction: r.language_instruction, metrics: metricCopy(r.metrics), episode_count: r.episode_count,
      success_count: r.success_count, artifacts, warnings: [...r.warnings] as string[] };
  } catch { return null; }
}

export function EvaluationOutcome({ job, active = true }: { job?: Job; active?: boolean }) {
  if (!job || job.kind !== 'evaluate') return null;
  const result = parseEvaluationResult(job);
  if (!result) return job.status === 'succeeded'
    ? <p className="notice warning">Evaluation completion is unverified: the result is missing, malformed or does not match the frozen inputs.</p> : null;
  return <section aria-label="Policy evaluation result">
    <h3>Policy evaluation completed</h3>
    <p>Completion is not manipulation proof. The profile identifies a policy class, not a verified server checkpoint.</p>
    <dl><dt>Profile</dt><dd>{result.profile}</dd>
      <dt>Language instruction</dt><dd>{result.language_instruction ?? 'Real task description (no override)'}</dd>
      <dt>Recorded completed episodes</dt><dd>{result.episode_count}</dd>
      {result.success_count !== null && <><dt>Recorded successes</dt><dd>{result.success_count}</dd></>}
      <dt>Input hash</dt><dd><code>{result.input_hash}</code></dd>
      <dt>Canonical hash</dt><dd><code>{result.canonical_hash}</code></dd></dl>
    {result.episode_count === 0 && <p className="notice warning">No completed-episode evidence</p>}
    {result.success_count === null && <p>Success count not recorded.</p>}
    {result.metrics === null ? <p>No measured metrics recorded.</p> : <details open><summary>Measured metrics (server recorded)</summary><pre>{JSON.stringify(result.metrics, null, 2)}</pre></details>}
    {result.warnings.length > 0 && <ul aria-label="Evaluation warnings">{result.warnings.map((warning, n) => <li key={n}>{warning}</li>)}</ul>}
    {result.artifacts.length > 0 && <ul aria-label="Evaluation artifacts">{result.artifacts.map(artifact => <li key={`${job.id}:${artifact.name}:${artifact.sha256}:${artifact.size}`}>
      <EvaluationDownload jobId={job.id} artifact={artifact} active={active} />
    </li>)}</ul>}
    <p className="hint">Frozen result: headless, cameras on, 1 environment, 1000 policy steps. Not the current draft. No generation or Neo4j publication was requested. HDF5 and video downloads are not served in this prototype.</p>
  </section>;
}

function EvaluationDownload({ jobId, artifact, active }: { jobId: string; artifact: Artifact; active: boolean }) {
  const { api, session } = useRuntime();
  const scope = clientSessionScope(api, session);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const lifetime = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const [renderedLifetime, setRenderedLifetime] = useState(lifetime.current);
  useLayoutEffect(() => {
    // Publish the committed lifetime even when idle busy/error resets bail out.
    // Cleanup must retire old handlers without also stranding the fresh control.
    setRenderedLifetime(lifetime.current);
    setBusy(false); setError(false);
    return () => { lifetime.current++; abort.current?.abort(); };
  }, [scope.id, active]);
  async function download() {
    const current = () => active && scope.current() && lifetime.current === renderedLifetime;
    if (busy || !current() || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(jobId)) return;
    setBusy(true); setError(false);
    const controller = new AbortController(); abort.current = controller;
    const timer = setTimeout(() => controller.abort(), 12_000);
    try {
      // ApiClient is JSON-only. Fetch the authenticated fixed attachment route,
      // never a result-supplied URL or HTML preview. Keep bytes outside query caches.
      if (artifact.size > 64 * 1024 * 1024) throw new Error();
      const response = await fetch(`/api/editor/evaluations/${encodeURIComponent(jobId)}/artifacts/${artifact.name}`, {
        credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal,
      });
      if (!current() || !response.ok || !response.body) throw new Error();
      const reader = response.body.getReader();
      const bytes = new Uint8Array(artifact.size);
      let offset = 0;
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (!current() || controller.signal.aborted) throw new Error();
          if (done) break;
          if (offset + value.byteLength > bytes.length) throw new Error();
          bytes.set(value, offset); offset += value.byteLength;
        }
      } finally { await reader.cancel(); reader.releaseLock(); }
      if (offset !== bytes.length) throw new Error();
      const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
      if (digest !== artifact.sha256 || !current() || controller.signal.aborted) throw new Error();
      const url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }));
      const anchor = document.createElement('a');
      try {
        anchor.href = url; anchor.download = artifact.name; document.body.append(anchor); anchor.click();
      } finally { anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 0); }
    } catch { if (current()) setError(true); }
    finally { clearTimeout(timer); if (current()) setBusy(false); }
  }
  return <>
    <button type="button" disabled={!active || !scope.current() || busy} onClick={() => void download()}>{busy ? `Verifying ${artifact.name}…` : `Download ${artifact.name}`}</button>
    <span> {artifact.size} bytes · SHA-256 <code>{artifact.sha256}</code></span>
    {error && <p role="alert">Download unavailable or byte verification failed. No file was offered. Downloads are limited to 64 MiB.</p>}
  </>;
}
