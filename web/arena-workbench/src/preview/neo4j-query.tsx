import React, { useState } from 'react';

type Draft = { query: string; params: string };
const initial: Draft = { query: 'MATCH (e:Environment {name: $name})-[:USES]->(r:Robot)\nRETURN e, r LIMIT 10', params: '{"name":"Example tabletop"}' };
const examples = [
  { id: 'relationships', label: 'Relationships example', ...initial },
  { id: 'empty', label: 'Empty example', query: initial.query, params: '{"name":"Example missing environment"}' },
  { id: 'error', label: 'Error example', query: initial.query, params: '{"name":"Example unavailable database"}' },
  { id: 'truncated', label: 'Truncated example', query: initial.query.replace('LIMIT 10', 'LIMIT 1'), params: initial.params },
];
type Example = typeof examples[number];
const nodes = [
  { id: 'example-environment', label: 'Environment', name: 'Example tabletop' },
  { id: 'example-robot', label: 'Robot', name: 'Example G1' },
];
function finite(value: unknown): boolean {
  if (typeof value === 'number') return Number.isFinite(value);
  return !value || typeof value !== 'object' || Object.values(value).every(finite);
}
function validParams(text: string): boolean {
  try {
    const value: unknown = JSON.parse(text);
    return !!value && typeof value === 'object' && !Array.isArray(value) && finite(value);
  } catch { return false; }
}

export function Neo4jQueryPreview() {
  const [draft, setDraft] = useState(initial);
  const [review, setReview] = useState<Draft | null>(null);
  const [connection, setConnection] = useState('unverified');
  const [loaded, setLoaded] = useState<{ example: Example; draft: Draft } | null>(null);
  const [format, setFormat] = useState('Table');
  const [selected, setSelected] = useState<string | null>(null);
  const paramsValid = validParams(draft.params);
  const matching = paramsValid ? examples.find(example => example.query === draft.query && example.params === JSON.stringify(JSON.parse(draft.params))) : undefined;
  const changed = (snapshot: Draft) => snapshot.query !== draft.query || snapshot.params !== draft.params;
  return <section className="preview-query-layout" aria-label="Neo4j query preview">
    <section className="preview-panel"><h2>Neo4j query</h2><p>No database connection. Offline composer only; no query is executed or published.</p>
      <label className="preview-field">Connection-state example<select aria-label="Connection-state example" value={connection} onChange={event => setConnection(event.target.value)}>{['unverified', 'available', 'unavailable', 'session-expired'].map(value => <option key={value} value={value}>{value} example</option>)}</select></label>
      <p role="status" aria-label="Connection example status">{connection} example only — no connection checked; local review and fixture browsing remain available.</p>
      <label className="preview-field">Query example<select aria-label="Query example" value={matching?.id ?? ''} onChange={event => { const example = examples.find(item => item.id === event.target.value); if (example) setDraft({ query: example.query, params: example.params }); }}><option value="" disabled>Custom query — no fixture</option>{examples.map(example => <option key={example.id} value={example.id}>{example.label}</option>)}</select></label>
      <p className="preview-muted">Selecting an example replaces the composer only. Frozen reviews and previously loaded fixtures are retained, never retargeted.</p>
      <label className="preview-field">Cypher query<textarea className="preview-query-code" aria-label="Cypher query" rows={6} spellCheck={false} value={draft.query} onChange={event => setDraft({ ...draft, query: event.target.value })} /></label>
      <label className="preview-field">Parameters (JSON object)<textarea className="preview-query-code" aria-label="Parameters (JSON object)" rows={4} spellCheck={false} value={draft.params} onChange={event => setDraft({ ...draft, params: event.target.value })} /></label>
      {!paramsValid && <p role="alert">Parameters must be a JSON object with finite numbers at every nesting level.</p>}
      {!draft.query.trim() && <p role="alert">Enter a Cypher query to review.</p>}
      <button type="button" disabled={!!review || !paramsValid || !draft.query.trim()} onClick={() => setReview({ ...draft })}>Review query locally</button>
      {review && <section className="preview-candidate" aria-label="Frozen query review"><h3>Frozen query review</h3><p>Not executed. Query syntax, permissions and server restrictions are not validated here.</p>{changed(review) && <p role="status">Review is stale — query or parameters changed. Frozen content is unchanged.</p>}<pre data-testid="frozen-query-review">{JSON.stringify({ exampleOnly: true, executed: false, query: review.query, params: JSON.parse(review.params) }, null, 2)}</pre><button type="button" onClick={() => setReview(null)}>Clear query review</button></section>}
    </section>
    <section className="preview-panel" aria-label="Example query results"><h2>Example results</h2>
      <p>Loading a bundled fixture is separate from query review. Exact example Cypher and parameter values are required; JSON whitespace is ignored. No Cypher interpreter or server validation is available.</p>
      {!matching && <p role="status">Custom-query results unavailable — this draft does not match a bundled fixture. You can review valid inputs locally, but cannot execute them.</p>}
      <button type="button" disabled={!matching} onClick={() => { if (matching) { setLoaded({ example: matching, draft: { ...draft } }); setSelected(null); } }}>Load example fixture</button>
      {loaded ? <>
        <h3>{loaded.example.label}</h3><p className="preview-tag">Fixture only — not executed query results</p>
        {changed(loaded.draft) && <p role="status">Fixture is stale — query or parameters changed. The retained fixture below belongs only to its original example, not the current draft.</p>}
        <details><summary>Fixture query binding</summary><pre>{JSON.stringify({ query: loaded.draft.query, params: JSON.parse(loaded.draft.params) }, null, 2)}</pre></details>
        {loaded.example.id === 'error' ? <p role="alert">Error fixture — illustrative database unavailable; no request was made.</p>
          : loaded.example.id === 'empty' ? <p className="preview-empty">Empty fixture — 0 example rows.</p>
          : <>{loaded.example.id === 'truncated' && <p role="status">Truncated fixture — 1 example row shown; additional rows intentionally omitted.</p>}
            <div className="preview-tabs" role="group" aria-label="Example result format">{['Table', 'Graph'].map(value => <button type="button" key={value} aria-pressed={format === value} onClick={() => setFormat(value)}>{value}</button>)}</div>
            {format === 'Table' ? <table className="preview-table" aria-label="Example Neo4j rows"><thead><tr><th>e: Environment</th><th>r: Robot</th><th>Relationship</th></tr></thead><tbody><tr><td>{nodes[0].name}</td><td>{nodes[1].name}</td><td>USES (example)</td></tr></tbody></table>
              : <><p className="preview-muted">Example relationship layout, not physical poses or a live persisted graph. Select a node by click, Enter or Space.</p>
                <p className="preview-muted">Scroll the diagram horizontally on narrow screens, or use Table.</p>
                <div className="preview-query-graph-scroll" role="region" aria-label="Scrollable example graph" tabIndex={0}><svg role="group" aria-label="Example Neo4j graph" viewBox="0 0 600 200" width="100%">
                  <path d="M 220 100 H 380 l -10 -6 m 10 6 l -10 6" fill="none" stroke="var(--muted)" strokeWidth="2" />
                  <text x="300" y="85" textAnchor="middle" fill="var(--text)" fontSize="14">USES</text>
                  {nodes.map((node, index) => <g key={node.id} role="button" tabIndex={0} aria-label={`Inspect ${node.name}`} aria-pressed={selected === node.id} onClick={() => setSelected(node.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(node.id); } }}>
                    <rect x={index ? 380 : 20} y="60" width="200" height="80" rx="4" fill="var(--inset)" stroke={selected === node.id ? 'var(--accent)' : 'var(--control-border)'} strokeWidth={selected === node.id ? 3 : 1} />
                    <text x={index ? 480 : 120} y="92" textAnchor="middle" fill="var(--muted)" fontSize="13">{node.label}</text>
                    <text x={index ? 480 : 120} y="116" textAnchor="middle" fill="var(--text)" fontSize="16">{node.name}</text>
                  </g>)}
                </svg></div>
                <section aria-label="Example node inspector"><h3>Example node inspector</h3>{selected ? <pre>{JSON.stringify({ exampleOnly: true, ...nodes.find(node => node.id === selected) }, null, 2)}</pre> : <p>Select an example node to inspect its fixture properties.</p>}</section>
              </>}
          </>}
      </> : <p className="preview-empty">No fixture loaded. Review does not load results; choose an example and explicitly load its fixture.</p>}
    </section>
  </section>;
}
