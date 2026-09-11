import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useRuntime } from './runtime';
import { CodeEditor } from './code-editor';
import { GraphView } from './graph-view';
import type { QueryResult } from './editor-contracts';
interface Example {
  id: string;
  name: string;
  query: string;
  params: Record<string, unknown>;
}
export function Neo4jView() {
  const { api, session } = useRuntime();
  const status = useQuery({
    queryKey: ['neo4j-status', session?.session_id],
    queryFn: () => api.get<{ available: boolean; message: string }>('/graph/status'),
    enabled: !!session,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const examples = useQuery({
    queryKey: ['neo4j-examples', session?.session_id],
    queryFn: () => api.get<{ queries: Example[] }>('/graph/examples'),
    enabled: !!session,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const [query, setQuery] = useState('');
  const [params, setParams] = useState('{}');
  const [example, setExample] = useState('');
  const [tab, setTab] = useState<'table' | 'graph'>('table');
  function choose(value: Example) {
    setExample(value.id);
    setQuery(value.query);
    setParams(JSON.stringify(value.params, null, 2));
  }
  useEffect(() => {
    if (examples.data?.queries[0] && !query) choose(examples.data.queries[0]);
  }, [examples.data]);
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
    mutationFn: async () => {
      const submitted = { query, params: parsed };
      await api.activity();
      return { submitted, result: await api.mutate<QueryResult>('/graph/query', submitted) };
    },
  });
  const result = run.data?.result;
  const stale =
    !!run.data &&
    (run.data.submitted.query !== query ||
      JSON.stringify(run.data.submitted.params) !== JSON.stringify(parsed));
  return (
    <main id="workspace" className="workspace">
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
          <CodeEditor label="Cypher query" language="text" value={query} onChange={setQuery} />
          <label htmlFor="query-params">Parameters (JSON object)</label>
          <textarea
            id="query-params"
            rows={5}
            value={params}
            onChange={(e) => setParams(e.target.value)}
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
                !session ||
                !query.trim() ||
                !!paramsError ||
                run.isPending ||
                !status.data?.available
              }
              onClick={() => run.mutate()}
            >
              {run.isPending ? 'Running query…' : 'Run read-only query'}
            </button>
            <button disabled={!session} onClick={() => void status.refetch()}>
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
          {run.error && (
            <p className="notice error" role="alert">
              {run.error.message}
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
              <div className="result-tabs" role="tablist" aria-label="Query result format">
                <button role="tab" aria-selected={tab === 'table'} onClick={() => setTab('table')}>
                  Table
                </button>
                <button role="tab" aria-selected={tab === 'graph'} onClick={() => setTab('graph')}>
                  Graph
                </button>
              </div>
              {tab === 'graph' ? (
                <GraphView graph={result.graph} label="Persisted Neo4j query graph" />
              ) : (
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
