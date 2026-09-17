import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRuntime } from './runtime';
import { clientSessionScope } from './client-session-scope';
import { parseReadinessV2, type ReadinessV2, type ReadinessCheck } from './readiness-contract';
export { parseReadinessV2 } from './readiness-contract';

type GraphStatus = 'not_configured' | 'not_checked' | 'available' | 'authentication_failed' | 'dependency_unavailable' | 'unavailable' | 'timeout' | 'configuration_changed' | 'invalid_configuration';
interface Readiness {
  schema_version: 1;
  checked_at: number | null;
  provider: {configured: boolean; source: 'none' | 'server' | 'session'; verification: 'not_checked'};
  graph: {configured: boolean; status: GraphStatus};
  dependencies: {openai: boolean; neo4j: boolean; isaacsim: boolean};
  runtime: {build_adapter: boolean; evaluation_adapter: boolean; simulation: 'not_checked'};
  policy_servers: {profile: 'gr00t-droid' | 'openpi-droid'; host: '127.0.0.1'; port: number; status: 'not_checked' | 'reachable' | 'unreachable'}[];
  workflow: {research_versions: boolean; publication: boolean; managed_retrieval: boolean; scenario_harness: 'cli_only'; evaluation_scope: 'droid_fixed_profiles'};
}
const graphLabels: Record<GraphStatus, string> = {
  not_configured: 'not configured', not_checked: 'configured; connection not checked', available: 'database read verified',
  authentication_failed: 'authentication rejected', dependency_unavailable: 'Neo4j driver unavailable', unavailable: 'database unavailable',
  timeout: 'check timed out', configuration_changed: 'configuration changed; check again',
  invalid_configuration: 'database configuration is incompatible with retrieval',
};
function exact(value: unknown, keys: string[]): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}
/** Only static statuses and bounded server-configured loopback endpoints enter the Query cache. */
export function parseReadiness(value: unknown): Readiness {
  const fail = () => { throw new Error('Invalid readiness response'); };
  if (!exact(value, ['schema_version', 'checked_at', 'provider', 'graph', 'dependencies', 'runtime', 'policy_servers', 'workflow'])) return fail();
  const r = value;
  if (r.schema_version !== 1 || !(r.checked_at === null || (typeof r.checked_at === 'number' && Number.isFinite(r.checked_at) && r.checked_at > 0))
    || !exact(r.provider, ['configured', 'source', 'verification']) || typeof r.provider.configured !== 'boolean'
    || typeof r.provider.source !== 'string' || !['none', 'session', 'server'].includes(r.provider.source) || r.provider.verification !== 'not_checked'
    || r.provider.configured !== (r.provider.source !== 'none')
    || !exact(r.graph, ['configured', 'status']) || typeof r.graph.configured !== 'boolean' || typeof r.graph.status !== 'string' || !Object.hasOwn(graphLabels, r.graph.status)
    || !exact(r.dependencies, ['openai', 'neo4j', 'isaacsim']) || !Object.values(r.dependencies).every(v => typeof v === 'boolean')
    || !exact(r.runtime, ['build_adapter', 'evaluation_adapter', 'simulation']) || typeof r.runtime.build_adapter !== 'boolean'
    || typeof r.runtime.evaluation_adapter !== 'boolean' || r.runtime.simulation !== 'not_checked'
    || !exact(r.workflow, ['research_versions', 'publication', 'managed_retrieval', 'scenario_harness', 'evaluation_scope'])
    || !['research_versions', 'publication', 'managed_retrieval'].every(key => typeof (r.workflow as Record<string, unknown>)[key] === 'boolean')
    || r.workflow.scenario_harness !== 'cli_only' || r.workflow.evaluation_scope !== 'droid_fixed_profiles'
    || !Array.isArray(r.policy_servers) || r.policy_servers.length !== 2) return fail();
  for (const [index, row] of r.policy_servers.entries()) {
    if (!exact(row, ['profile', 'host', 'port', 'status']) || row.profile !== ['gr00t-droid', 'openpi-droid'][index]
      || row.host !== '127.0.0.1' || typeof row.port !== 'number' || !Number.isInteger(row.port) || row.port < 1 || row.port > 65535
      || index === 1 && row.port !== 8000 || typeof row.status !== 'string' || !['not_checked', 'reachable', 'unreachable'].includes(row.status)) return fail();
  }
  return structuredClone(r) as unknown as Readiness;
}

interface WorkflowReadinessProps {
  active: boolean;
  providerRevision: string;
  version?: 1 | 2;
  draft?: string;
  documentId?: string;
  prompt?: string;
  sourceIdentity?: string;
  canCheck?: () => boolean;
}

/** Existing v1 API/display remains available explicitly; current callers use v2. */
export function WorkflowReadiness(props: WorkflowReadinessProps) {
  return props.version === 1 ? <LegacyWorkflowReadiness {...props} /> : <WorkflowReadinessV2 {...props} />;
}
const checkLabels: Record<ReadinessCheck, string> = {api_contract: 'API contract', runtime: 'Runtime package availability', generation_model: 'Generation model',
  graph: 'Graph retrieval', policy_protocol: 'Policy protocol / modalities', policy_model: 'Policy model identity',
  policy_transport: 'Native policy transport', gpu: 'GPU headroom'};
function WorkflowReadinessV2({active, providerRevision, draft, documentId, prompt, sourceIdentity, canCheck}: WorkflowReadinessProps) {
  const {api, session} = useRuntime();
  const owner = clientSessionScope(api, session);
  const workflow = 'agentic_generation';
  const cache = useQueryClient();
  const reads = useRef(0);
  const [readEpoch, setReadEpoch] = useState(0);
  const source = useMemo(() => ({}), [owner.id, active, providerRevision, workflow, draft, documentId, prompt, sourceIdentity, readEpoch]);
  const inputValid = useMemo(() => (draft === undefined || typeof draft === 'string' && new TextEncoder().encode(draft).length <= 256 * 1024)
    && (documentId === undefined || typeof documentId === 'string' && /^[a-f0-9]{32}$/.test(documentId) && draft !== undefined)
    && (prompt === undefined || typeof prompt === 'string' && Array.from(prompt).length <= 16000), [draft, documentId, prompt]);
  const [consent, setConsent] = useState<{source: object; enabled: boolean} | null>(null);
  const checkProvider = consent?.source === source && consent.enabled;
  const lifetime = useMemo(() => ({active: true}), [source, consent]);
  useLayoutEffect(() => {lifetime.active = true; return () => {lifetime.active = false;};}, [lifetime]);
  const current = () => active && lifetime.active && owner.current() && readEpoch === reads.current && inputValid && (canCheck?.() ?? true);
  // Metadata belongs to the API/session/workflow, not to changing drafts or settings.
  const metadataLifetime = useMemo(() => ({active: true}), [owner.id, active, workflow]);
  useLayoutEffect(() => {metadataLifetime.active = true; return () => {metadataLifetime.active = false;};}, [metadataLifetime]);
  const metadataCurrent = () => active && metadataLifetime.active && owner.current();
  const queryKey = useMemo(() => ['workflow-readiness-v2', ...owner.queryKey.slice(1), workflow], [owner.id, workflow]);
  const query = useQuery({
    queryKey,
    queryFn: async ({signal}) => {
      try {
        if (!metadataCurrent() || signal.aborted) throw new Error();
        const data = parseReadinessV2(await api.get(`/editor/readiness?version=2&workflow=${workflow}`), workflow);
        if (!metadataCurrent() || signal.aborted || data.checked_at !== null) throw new Error();
        return data;
      } catch {throw new Error('Readiness metadata unavailable. Check the API connection.');}
    }, enabled: active && owner.current(), retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false, staleTime: Infinity,
  });
  useLayoutEffect(() => {
    const observed = cache.getQueryCache().find({queryKey});
    return cache.getQueryCache().subscribe(event => {
      const readinessRead = event.query === observed;
      const settingsRead = JSON.stringify(event.query.queryKey) === owner.id;
      if (event.type === 'updated' && (readinessRead && ['fetch', 'invalidate'].includes(event.action.type)
        || settingsRead && ['fetch', 'invalidate', 'success', 'error'].includes(event.action.type))) {
        // Observe the existing settings cache only: never add a settings/provider read.
        // Synchronous retirement also fences retained handlers and identical-data ABA.
        reads.current++; setReadEpoch(reads.current);
      }
    });
  }, [cache, queryKey]);
  const metadataAdmitted = () => {
    const state = cache.getQueryState(queryKey);
    return query.isSuccess && state?.status === 'success' && state.fetchStatus === 'idle' && !state.isInvalidated && state.data === query.data;
  };
  const [lastAttempt, setLastAttempt] = useState<object | null>(null);
  const [checking, setChecking] = useState<object | null>(null);
  const busy = useRef<object | null>(null);
  const [checked, setChecked] = useState<{lifetime: object; data: ReadinessV2} | null>(null);
  const [error, setError] = useState<object | null>(null);
  const data = current() && checked?.lifetime === lifetime ? checked.data : query.data;
  async function check() {
    if (!current() || !metadataAdmitted() || busy.current === lifetime) return;
    const body = {schema_version: 2, workflow, check_provider: checkProvider,
      ...(draft !== undefined ? {yaml_text: draft} : {}), ...(documentId !== undefined ? {document_id: documentId} : {}),
      ...(prompt?.trim() ? {prompt} : {})};
    busy.current = lifetime; setLastAttempt(lifetime); setChecking(lifetime); setChecked(null); setError(null);
    try {
      await api.activity();
      if (!current() || !metadataAdmitted()) return;
      const result = parseReadinessV2(await api.mutate('/editor/readiness/check', body), workflow, checkProvider);
      if (current() && metadataAdmitted()) setChecked({lifetime, data: result});
    } catch {if (current() && metadataAdmitted()) setError(lifetime);}
    finally {if (busy.current === lifetime) busy.current = null; if (current()) setChecking(null);}
  }
  return <section className="notice" aria-label="Workflow readiness">
    <h2>Workflow readiness</h2>
    <p>Configuration is not execution. Check performs bounded dependency reads, not inference, simulation, generation or publication.</p>
    <p>Generation → inspect → build: the general graph-backed workflow, for your prompt and current source, without a scenario or policy selection.</p>
    <p>API contracts cover model settings, generation, validation and Build, plus snapshots when the adapter is available. Generation model and graph reads do not constrain the draft to DROID. Build itself needs neither a model nor a policy server; this panel checks the combined workflow.</p>
    <label><input type="checkbox" checked={checkProvider} disabled={!current()} onChange={event => {
      if (!current()) return;
      lifetime.active = false; setConsent({source, enabled: event.target.checked});
    }} /> Allow one authenticated provider-model metadata read (not inference)</label>
    {!inputValid && <p role="status">Readiness input is unavailable or exceeds server limits. Review the frozen draft, document and prompt.</p>}
    {lastAttempt !== null && (lastAttempt !== lifetime || !current()) && <p role="status">Previous check is stale; source, session, settings or provider consent changed. Check again explicitly.</p>}
    <p>Provider reading is off by default, so generation-model verification stays not_checked until opt-in. Opt-in permits one authenticated model metadata GET for the exact configured model, currently gpt-4.1 or gpt-6-astra on the supported official endpoint. It does not prove inference permissions, quota or structured output.</p>
    <div className="editor-actions">
      <button type="button" disabled={!current() || !metadataAdmitted() || checking === lifetime} onClick={() => void check()}>Check dependencies</button>
      <button type="button" disabled={!current() || query.isFetching} onClick={() => {if (current()) {setChecked(null); void query.refetch();}}}>Refresh readiness</button>
    </div>
    {(query.isError || !data) && <p role="status">{query.isError ? 'Readiness metadata unavailable. Check the API connection.' : 'Loading readiness metadata…'}</p>}
    {error === lifetime && <p role="alert">Dependency check unavailable. No work was submitted.</p>}
    {data && !query.isError && <>
      <p>{data.ready ? 'All requested dependency reads passed at observation time.' : 'Requested dependency readiness is not established.'}</p>
      <ul>{data.checks.map(row => <li key={row.id}>{checkLabels[row.id]}: {row.status} — <code>{row.code}</code> ({row.required ? 'required' : 'not required'})</li>)}</ul>
      {data.policy && <details open><summary>Policy identity evidence</summary>
        <p>{data.policy.expected_checkpoint}</p>
        <dl>{Object.entries(data.policy).filter(([key]) => !['profile', 'expected_checkpoint', 'inference'].includes(key)).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value ?? 'not checked'}</dd></div>)}</dl>
      </details>}
      <p>Inference: not_run. GPU headroom is a point-in-time observation, not a reservation or simulation guarantee. Graph results describe retrieval reads, not consumed priors or generated research success.</p>
      {data.checked_at !== null && <p>Last explicit check: {new Date(data.checked_at * 1000).toLocaleString()}. Recheck after dependency or configuration changes.</p>}
    </>}
    <p>Policy evaluation is separate and not required for generation or build. No policy-server RPC is made by this check. Manual readiness does not authorize Evaluate. Evaluation retains its independent backend admission, pinned identity, transport and execution gates.</p>
  </section>;
}

function LegacyWorkflowReadiness({active, providerRevision}: {active: boolean; providerRevision: string}) {
  const {api, session} = useRuntime();
  const owner = clientSessionScope(api, session);
  const lifetime = useMemo(() => ({active: false}), [owner.id, active, providerRevision]);
  useLayoutEffect(() => { lifetime.active = true; return () => {lifetime.active = false;}; }, [lifetime]);
  const current = () => active && lifetime.active && owner.current();
  const query = useQuery({
    queryKey: ['workflow-readiness', ...owner.queryKey.slice(1), providerRevision],
    queryFn: async ({signal}) => {
      try {
        if (!current() || signal.aborted) throw new Error();
        const data = parseReadiness(await api.get('/editor/readiness'));
        if (!current() || signal.aborted) throw new Error();
        return data;
      } catch { throw new Error('Readiness metadata unavailable. Check the API connection.'); }
    },
    enabled: active && owner.current(), retry: false, refetchOnWindowFocus: false,
  });
  const busy = useRef<object | null>(null);
  const [checking, setChecking] = useState<object | null>(null);
  const [checked, setChecked] = useState<{lifetime: object; data: Readiness} | null>(null);
  const [error, setError] = useState<object | null>(null);
  const data = !query.isError && !query.isFetching && checked?.lifetime === lifetime ? checked.data : query.data;
  async function check() {
    if (!current() || busy.current === lifetime) return;
    busy.current = lifetime; setChecking(lifetime); setError(null); setChecked(null);
    try {
      await api.activity();
      if (!current()) return;
      const result = parseReadiness(await api.mutate('/editor/readiness/check', {}));
      if (current()) setChecked({lifetime, data: result});
    } catch { if (current()) setError(lifetime); }
    finally {
      if (busy.current === lifetime) busy.current = null;
      if (current()) setChecking(null);
    }
  }
  return <section className="notice" aria-label="Workflow readiness">
    <h2>Workflow readiness</h2>
    <p>Configuration is not successful execution. No provider calls or GPU jobs are made by this panel.</p>
    <div className="editor-actions">
      <button type="button" disabled={!current() || checking === lifetime} onClick={() => void check()}>Check dependencies</button>
      <button type="button" disabled={!current() || query.isFetching} onClick={() => {if (current()) {setChecked(null); void query.refetch();}}}>Refresh readiness</button>
    </div>
    {(query.isError || !data) && <p role="status">{query.isError ? 'Readiness metadata unavailable. Check the API connection.' : 'Loading readiness metadata…'}</p>}
    {error === lifetime && <p role="alert">Dependency check unavailable. No work was submitted.</p>}
    {data && !query.isError && <>
      <p>{data.provider.configured ? `Model provider: configured (${data.provider.source}); endpoint and model not tested` : 'Model provider: not configured'}</p>
      {!data.provider.configured && <p>Configure Temporary provider settings below, or explicit server credentials. Saving a key does not test it.</p>}
      <p>Graph-RAG: {graphLabels[data.graph.status]}</p>
      {!data.graph.configured && <p>Operator setup required: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD and NEO4J_DATABASE in the API process. The web API does not read .env or use the CLI’s default graph password.</p>}
      <p>For Graph-RAG experiments, select “Require read-only retrieval service”. Fallback may generate without graph priors. A connection check is not evidence that generation consumed priors; inspect its retrieval receipt.</p>
      <ul>{data.policy_servers.map(row => <li key={row.profile}>{row.profile}: {row.host}:{row.port} — {row.status.replaceAll('_', ' ')}</li>)}</ul>
      <p>Policy checks establish TCP reachability only—not server protocol, checkpoint identity or embodiment compatibility. Simulation readiness requires an explicit Build.</p>
      <details><summary>Harness dependencies and scope</summary>
        <ul>{Object.entries(data.dependencies).map(([name, found]) => <li key={name}>{name}: {found ? 'package found; runtime not exercised' : 'package missing'}</li>)}</ul>
        <p>Build adapter: {data.runtime.build_adapter ? 'available' : 'unavailable'}. Evaluation adapter: {data.runtime.evaluation_adapter ? 'available' : 'unavailable'} (fixed DROID profiles only).</p>
        <p>Research versions: {data.workflow.research_versions ? 'configured' : 'not configured'}. Publication: {data.workflow.publication ? 'enabled' : 'disabled'}. Managed retrieval: {data.workflow.managed_retrieval ? 'enabled' : 'disabled'}.</p>
      </details>
      <p>Full scenario harness remains CLI-only: env_gen_test.md’s G1/GR1 profiles and auto-healing loop are not wired to these fixed web evaluation controls.</p>
      {data.checked_at !== null && <p>Last explicit check: {new Date(data.checked_at * 1000).toLocaleString()}. Recheck after dependency or configuration changes.</p>}
    </>}
  </section>;
}
