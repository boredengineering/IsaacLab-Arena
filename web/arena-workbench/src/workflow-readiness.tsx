import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRuntime } from './runtime';
import { clientSessionScope } from './client-session-scope';

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
/** Only static statuses and fixed endpoint identities enter the Query cache. */
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
      || row.host !== '127.0.0.1' || row.port !== [5555, 8000][index] || typeof row.status !== 'string' || !['not_checked', 'reachable', 'unreachable'].includes(row.status)) return fail();
  }
  return structuredClone(r) as unknown as Readiness;
}

export function WorkflowReadiness({active, providerRevision}: {active: boolean; providerRevision: string}) {
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
