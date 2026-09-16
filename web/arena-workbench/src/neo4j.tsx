import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useRuntime } from './runtime';
import { CodeEditor } from './code-editor';
import { GraphHost, type GraphRolloutProps } from './graph-host';
import type { QueryResult } from './editor-contracts';
import type { ApiClient } from './api';

// Primitive tokens remain distinct under Query's structural key hashing and stable
// across remounts, without retaining clients or credentials in cached variables.
const clientOwners = new WeakMap<ApiClient, string>();
function clientOwner(api: ApiClient) {
  let token = clientOwners.get(api);
  if (!token) {
    token = crypto.randomUUID();
    clientOwners.set(api, token);
  }
  return token;
}

interface Example {
  id: string;
  name: string;
  query: string;
  params: Record<string, unknown>;
}
export interface Neo4jViewProps extends GraphRolloutProps {
  active?: boolean;
}
interface QuerySubmission {
  query: string;
  params: Record<string, unknown>;
  paramsText: string;
  label: string;
  sessionId: string;
  sessionGeneration: number;
  owner: string;
  resultId: string;
  lifetime: number;
}
export function Neo4jView({ active = true, graphRenderer = 'legacy', onGraphRendererChange = () => {} }: Neo4jViewProps = {}) {
  const { api, session } = useRuntime();
  const sessionGeneration = api.sessionGeneration;
  // Keep the client (and its CSRF metadata) out of retained mutation variables.
  const owner = clientOwner(api);
  const sessionId = session?.session_id;
  const metadataScope = useMemo(() => ({ current: false }), [owner, sessionGeneration, sessionId]);
  useLayoutEffect(() => {
    metadataScope.current = true;
    return () => { metadataScope.current = false; };
  }, [metadataScope]);
  const metadataCurrent = () => metadataScope.current && !!sessionId &&
    api.sessionGeneration === sessionGeneration && api.session?.session_id === sessionId;
  async function readMetadata<T>(path: string, signal: AbortSignal): Promise<T> {
    const assertCurrent = () => {
      if (signal.aborted || !metadataCurrent())
        throw new Error('Neo4j metadata request retired; check the current session.');
    };
    assertCurrent();
    try {
      const data = await api.get<T>(path);
      assertCurrent();
      return data;
    } catch (error) {
      assertCurrent();
      throw error;
    }
  }
  const lifetime = useRef(0);
  const live = useRef(false);
  // Committed deactivation retires consent permanently, including an away/back round trip.
  useLayoutEffect(() => {
    live.current = active;
    return () => {
      live.current = false;
      lifetime.current++;
    };
  }, [active, api, sessionGeneration]);
  const status = useQuery({
    queryKey: ['neo4j-status', owner, sessionId, sessionGeneration],
    queryFn: ({ signal }) => readMetadata<{ available: boolean; message: string }>('/graph/status', signal),
    enabled: active && !!session,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const examples = useQuery({
    queryKey: ['neo4j-examples', owner, sessionId, sessionGeneration],
    queryFn: ({ signal }) => readMetadata<{ queries: Example[] }>('/graph/examples', signal),
    enabled: active && !!session,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const [query, setQuery] = useState('');
  const [params, setParams] = useState('{}');
  const [example, setExample] = useState('');
  const [tab, setTab] = useState<'table' | 'graph'>('table');
  const initialized = useRef(false);
  function choose(value: Example) {
    initialized.current = true;
    setExample(value.id);
    setQuery(value.query);
    setParams(JSON.stringify(value.params, null, 2));
  }
  useEffect(() => {
    if (active && metadataCurrent() && !initialized.current && examples.data?.queries[0] && !query)
      choose(examples.data.queries[0]);
  }, [active, metadataScope, examples.data]);
  let parsed: Record<string, unknown> = {};
  let paramsError = '';
  try {
    const value: unknown = JSON.parse(params);
    if (!value || typeof value !== 'object' || Array.isArray(value))
      throw new Error('Parameters must be a JSON object.');
    parsed = value as Record<string, unknown>;
  } catch (e) {
    paramsError = e instanceof Error ? e.message : String(e);
  }
  const run = useMutation({
    retry: false,
    mutationFn: async (submission: QuerySubmission) => {
      const submitted = { query: submission.query, params: submission.params };
      const assertCurrent = () => {
        if (!live.current || lifetime.current !== submission.lifetime || owner !== submission.owner ||
          api.sessionGeneration !== submission.sessionGeneration || api.session?.session_id !== submission.sessionId)
          throw new Error('Query request retired; run explicitly in the active workspace and current session.');
      };
      assertCurrent();
      try {
        await api.activity();
        assertCurrent();
        const result = await api.mutate<QueryResult>('/graph/query', submitted);
        assertCurrent();
        return { submitted: { ...submitted, paramsText: submission.paramsText, label: submission.label },
          sessionId: submission.sessionId, sessionGeneration: submission.sessionGeneration,
          owner: submission.owner, resultId: submission.resultId, result };
      } catch (error) {
        assertCurrent();
        throw error;
      }
    },
  });
  const result = run.data?.owner === owner && run.data?.sessionGeneration === sessionGeneration &&
    run.data?.sessionId === session?.session_id && run.data?.sessionId === api.session?.session_id
    ? run.data.result : undefined;
  const stale =
    !!result && !!run.data &&
    (run.data.submitted.query !== query ||
      run.data.submitted.paramsText !== params);
  return (
    <main id={active ? 'workspace' : undefined} className="workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">PERSISTED GRAPH EXPLORER</span>
          <h1>Neo4j query</h1>
          <p>
            Inspect persisted environments and relationships. This is not the editor’s authored
            graph.
          </p>
        </div>
        <span className="tag">Read-only</span>
      </div>
      <div className="query-grid">
        <section className="query-input">
          <h2>Cypher</h2>
          <p className="hint">
            Restricted MATCH / RETURN queries. Updates, CALL, comments and unsupported functions are
            rejected by the server.
          </p>
          <label htmlFor="query-example">Examples</label>
          <select
            id="query-example"
            value={example}
            onChange={(e) => {
              const next = examples.data?.queries.find((q) => q.id === e.target.value);
              if (next) choose(next);
            }}
          >
            <option value="">Choose an example</option>
            {examples.data?.queries.map((q) => (
              <option value={q.id} key={q.id}>
                {q.name}
              </option>
            ))}
          </select>
          {examples.error && (
            <p role="alert" className="error-text">
              Examples unavailable: {examples.error.message}
            </p>
          )}
          <label>Query</label>
          <CodeEditor label="Cypher query" language="text" value={query} onChange={value => { initialized.current = true; setQuery(value); }} />
          <label htmlFor="query-params">Parameters (JSON object)</label>
          <textarea
            id="query-params"
            rows={5}
            value={params}
            onChange={(e) => { initialized.current = true; setParams(e.target.value); }}
            spellCheck={false}
          />
          {paramsError && (
            <p className="error-text" role="alert">
              {paramsError}
            </p>
          )}
          <div className="editor-actions">
            <button
              className="primary"
              disabled={
                !active ||
                !session ||
                !query.trim() ||
                !!paramsError ||
                run.isPending ||
                !status.data?.available
              }
              onClick={() => {
                if (!active || !session || !metadataCurrent() || !status.data?.available) return;
                const selected = examples.data?.queries.find(value => value.id === example);
                const label = selected?.query === query && JSON.stringify(selected.params) === JSON.stringify(parsed)
                  ? selected.name : 'Custom query';
                run.mutate({ query, params: parsed, paramsText: params, label, sessionId: session.session_id,
                  sessionGeneration, owner, resultId: crypto.randomUUID(), lifetime: lifetime.current });
              }}
            >
              {run.isPending ? 'Running query…' : 'Run read-only query'}
            </button>
            <button disabled={!active || !session} onClick={() => active && session && void status.refetch()}>
              Check connection
            </button>
          </div>
          <p className="hint" role="status">
            {status.error
              ? status.error.message
              : (status.data?.message ?? 'Neo4j connection not yet verified.')}
          </p>
        </section>
        <section className="query-results">
          <div className="section-heading">
            <h2>Query results</h2>
            {result && (
              <span className="muted">
                {result.rows.length} rows · {result.elapsed_ms} ms
              </span>
            )}
          </div>
          {run.error && run.variables?.owner === owner && run.variables.sessionGeneration === sessionGeneration && (
            <p className="notice error" role="alert">
              {run.error.message}
            </p>
          )}
          {run.data && !result && (
            <p className="notice warning">
              Previous result withheld because its session changed. Run explicitly in the current session.
            </p>
          )}
          {stale && (
            <p className="notice warning">
              Previous query result · query or parameters have changed.
            </p>
          )}
          {result?.truncated && (
            <p className="notice warning">
              Results truncated by server limits. Narrow your MATCH or reduce the requested
              neighborhood.
            </p>
          )}
          {result ? (
            <>
              <details>
                <summary>Submitted query · {run.data?.submitted.label}</summary>
                <pre aria-label="Submitted Cypher query">{run.data?.submitted.query}</pre>
                <pre aria-label="Submitted parameters">{run.data?.submitted.paramsText}</pre>
              </details>
              <div className="result-tabs" role="tablist" aria-label="Query result format">
                <button role="tab" aria-selected={tab === 'table'} onClick={() => setTab('table')}>
                  Table
                </button>
                <button role="tab" aria-selected={tab === 'graph'} onClick={() => setTab('graph')}>
                  Graph
                </button>
              </div>
              <GraphHost graph={session ? result.graph : null} visible={active && tab === 'graph'}
                scopeKey={`persisted:${session?.session_id ?? 'expired'}:${run.data?.resultId ?? 'none'}`}
                revisionKey={run.data?.resultId ?? ''} label="Persisted Neo4j query graph" sourceKind="persisted"
                renderer={graphRenderer} onRendererChange={onGraphRendererChange} />
              {tab === 'table' && (
                <div className="table-scroll">
                  <table aria-label="Neo4j query results">
                    <thead>
                      <tr>
                        {result.columns.map((column, i) => (
                          <th key={i}>{column}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.map((row, i) => (
                        <tr key={i}>
                          {row.map((cell, j) => (
                            <td key={j}>
                              {typeof cell === 'object' ? (
                                <pre>{JSON.stringify(cell, null, 2)}</pre>
                              ) : (
                                String(cell ?? 'null')
                              )}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!result.rows.length && (
                    <div className="empty-state">Query returned no rows.</div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="empty-state">
              Choose an example or write a read-only query, then run it. Table and interactive graph
              results appear here.
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
