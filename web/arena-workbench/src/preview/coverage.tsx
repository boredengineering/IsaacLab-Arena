import { useMemo, useState } from 'react';
import historical from './coverage-data.json';
import type { PreviewSection } from './types';

type Entry = typeof historical.entries[number];
type Mapping = { section: PreviewSection; label: string };
export const capabilityScreens: Record<string, Mapping> = {
  C01: { section: 'coverage', label: 'Schema reference' }, C02: { section: 'coverage', label: 'Catalogue reference' },
  C03: { section: 'environment', label: 'Environment / New' }, C04: { section: 'environment', label: 'Environment / Refine' },
  C05: { section: 'settings', label: 'Settings / provider & model' }, C06: { section: 'environment', label: 'Environment / consumed evidence' },
  C07: { section: 'library', label: 'Library / versions & lineage' }, C08: { section: 'graph', label: 'Research graph / publication' },
  C09: { section: 'library', label: 'Library / typed import & export' }, C10: { section: 'visualizer', label: 'Assets & scene / saved renders and planning' },
  C11: { section: 'build', label: 'Build / zero-action' }, C12: { section: 'build', label: 'Build / generate-and-build' },
  C13: { section: 'build', label: 'Build / policy evaluation' }, C14: { section: 'improve', label: 'Improve / repair' },
  C15: { section: 'improve', label: 'Improve / DCRG' }, C16: { section: 'runs', label: 'Runs / report & evidence' },
  C17: { section: 'jobs', label: 'Jobs & diagnostics / lifecycle; Settings / readiness' }, C18: { section: 'build', label: 'Build / Native Kit' },
  C19: { section: 'experiments', label: 'Experiments / variations & children' }, C20: { section: 'build', label: 'Build / advanced operator profiles' },
  C21: { section: 'improve', label: 'Improve / controller assistance' },
};

export function representation(entry: Entry): string {
  if (entry.implementation_status === 'needs_audit' || entry.disposition.includes('audit')) return 'unresolved audit';
  if (entry.disposition.startsWith('blocked') || entry.disposition.startsWith('replace_')) return 'rejected or ineffective option';
  if (entry.profile === 'private_credential_reference' || entry.disposition === 'private_transport_only' || entry.profile === 'caller_owned_driver') return 'operator prerequisite';
  if (entry.profile.includes('approved') || entry.profile === 'assisted_left_g1_privileged' || entry.disposition.includes('operator')) return 'approved-profile field';
  if (entry.profile === 'read_only' || ['capability_workflow', 'workflow_rule', 'nonparser_operation'].includes(entry.kind)) return 'read-only evidence';
  return 'planned field representation';
}
const categories = ['planned field representation', 'approved-profile field', 'read-only evidence', 'operator prerequisite', 'rejected or ineffective option', 'unresolved audit'];
const PAGE_SIZE = 20;
const json = (value: unknown) => JSON.stringify(value, null, 2);

export function CoveragePanel({ onNavigate }: { onNavigate: (section: PreviewSection) => void }) {
  const [view, setView] = useState('index');
  const [query, setQuery] = useState('');
  const [capability, setCapability] = useState('');
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Entry | null>(null);
  const rows = useMemo(() => historical.entries.filter(entry => (!capability || entry.capability_ids.includes(capability)) && (!category || representation(entry) === category) && `${json(entry)} ${entry.capability_ids.map(cap => capabilityScreens[cap].label).join(' ')} ${representation(entry)}`.toLowerCase().includes(query.toLowerCase())), [query, capability, category]);
  const changeView = (next: string) => { setView(next); setSelected(null); };
  return <section className="preview-panel" aria-label="Coverage index">
    <h2>Coverage & reference</h2>
    <p>394 historical ledger entries · 21 capability IDs · {historical.source_delta.length} managed CLI source additions requiring reconciliation.</p>
    <p className="preview-muted">Historical design evidence — not current runtime inventory. Static metadata only; no live catalogue, parser execution or API. An indexed field is not a working control and a screen mapping does not complete a capability.</p>
    <div className="preview-actions" aria-label="Coverage views">{[['index', 'Historical index'], ['schema', 'C01 Schema reference'], ['catalogue', 'C02 Catalogue reference'], ['delta', 'Current source delta'], ['gaps', 'Audit gaps G01–G05']].map(([id, label]) => <button key={id} aria-pressed={view === id} onClick={() => changeView(id)}>{label}</button>)}</div>
    <p>UI: represented as read-only index · Backend: unknown · Deployment: not deployed · Runtime: no runtime proof.</p>
    {view === 'index' && <>
      <div className="preview-grid">
        <label className="preview-field">Search coverage<input type="search" aria-label="Search coverage" value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} /></label>
        <label className="preview-field">Capability<select aria-label="Capability" value={capability} onChange={event => { setCapability(event.target.value); setPage(0); }}><option value="">All capabilities</option>{historical.capability_ids.map(cap => <option key={cap}>{cap}</option>)}</select></label>
        <label className="preview-field">Representation<select aria-label="Representation" value={category} onChange={event => { setCategory(event.target.value); setPage(0); }}><option value="">All representations</option>{categories.map(value => <option key={value}>{value}</option>)}</select></label>
      </div>
      <p role="status">{rows.length} matching historical entries · Page {page + 1} of {Math.max(1, Math.ceil(rows.length / PAGE_SIZE))}</p>
      <div className="preview-list">{rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map(entry => <article className="preview-panel" key={entry.id} data-testid="coverage-row"><button aria-label={`Inspect ${entry.id}`} onClick={() => setSelected(entry)}>{entry.id}</button><p>{entry.name} · {entry.capability_ids.join(', ')} · {representation(entry)}</p></article>)}</div>
      {!rows.length && <p>No matching entries. Clear the search or filters.</p>}
      <div className="preview-actions"><button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous page</button><button disabled={(page + 1) * PAGE_SIZE >= rows.length} onClick={() => setPage(page + 1)}>Next page</button></div>
      {selected && <section className="preview-panel" aria-label="Entry inspector">
        <h3>{selected.id} — {selected.name}</h3><button onClick={() => setSelected(null)}>Close inspector</button>
        <dl><dt>Planned disposition / representation</dt><dd>{representation(selected)}</dd><dt>Historical disposition (unaltered)</dt><dd>{selected.disposition}</dd><dt>Profile</dt><dd>{selected.profile}</dd><dt>Profile boundary</dt><dd>{historical.profile_semantics[selected.profile as keyof typeof historical.profile_semantics] ?? historical.profile_semantics.other_named_profiles}</dd><dt>Historical implementation status — not current backend status</dt><dd>{selected.implementation_status}</dd><dt>Historical default (expression, not evaluated)</dt><dd><pre>{json(selected.default)}</pre></dd><dt>Precedence</dt><dd>{selected.precedence}</dd><dt>Operator explanation / observed behavior</dt><dd>{'observed_behavior' in selected ? selected.observed_behavior : selected.proposed_acceptance}</dd><dt>Planned interaction check — not performed runtime acceptance</dt><dd>{selected.proposed_acceptance}</dd></dl>
        <p>No typed field control claimed by this index. Planned field representation remains separate from an actual typed control; unsupported, no-op, private and unresolved fields are read-only and cannot be dispatched.</p>
        <p>UI: represented (inspector only); interaction review/user approval pending. Backend: unknown. Deployment: not deployed. Runtime: no runtime proof.</p>
        <h4>Planned screen groups — inspect each control separately</h4><div className="preview-actions">{selected.capability_ids.map(cap => <button key={cap} onClick={() => cap === 'C01' ? changeView('schema') : cap === 'C02' ? changeView('catalogue') : onNavigate(capabilityScreens[cap].section)}>Open {capabilityScreens[cap].label} ({cap})</button>)}</div>
        <h4>Source provenance</h4><pre>{json(selected.source_refs)}</pre><h4>Limitations</h4><ul>{selected.coverage_limitations.map(text => <li key={text}>{text}</li>)}</ul>
        <details><summary>Full unmodified historical record</summary><pre>{json(selected)}</pre></details>
      </section>}
    </>}
    {view === 'gaps' && historical.remaining_audit_gaps.map(gap => <article className="preview-panel" key={gap.id}><h3>{gap.id} — {gap.scope}</h3><p>{gap.status}</p><p>{gap.detail}</p>{'entry_ids' in gap && <p>{gap.entry_ids?.join(', ')}</p>}</article>)}
    {view === 'delta' && <><h3>Current managed CLI source delta — not historical ledger IDs</h3><p>{historical.delta_method} Additions have no assigned capability IDs or approved profile; mappings to Settings, Library and Research graph are reconciliation review paths only.</p><p>Source revision SHA-256: {historical.delta_source_sha256}</p>{historical.source_delta.map(delta => <article className="preview-panel" key={delta.option}><h4>{delta.option}</h4><p>Source delta requiring reconciliation · canonical ledger ID: none · unresolved audit</p><p>{delta.explanation}</p><pre>{json(delta)}</pre></article>)}</>}
    {(view === 'schema' || view === 'catalogue') && <ReferenceView key={view} kind={view} />}
  </section>;
}

function ReferenceView({ kind }: { kind: string }) {
  const [query, setQuery] = useState('');
  const [catalogueKind, setCatalogueKind] = useState('asset');
  const [fieldId, setFieldId] = useState('');
  const [constraint, setConstraint] = useState('');
  const schemaIds = ['field.graph_override.arg', 'field.graph_override.target_node_id', 'parameter.register_environment_version.spec', 'parameter.register_environment_version.target_object_id'];
  const catalogueIds: Record<string, string[]> = {
    asset: ['mechanism.graph_asset_swap', 'field.graph_override.target_node_id', 'rule.variation_mechanisms'],
    relation: ['cli.generation.no_solve_relations', 'cli.generation.resolve_on_reset', 'rule.variation_mechanisms'],
    task: ['parameter.run_rollout.object_name', 'parameter.run_rollout.destination_name', 'parameter.run_rollout.hand_body', 'rule.dcrg_constraints'],
  };
  const ids = kind === 'schema' ? schemaIds : catalogueIds[catalogueKind];
  const entries = historical.entries.filter(entry => ids.includes(entry.id) && json(entry).toLowerCase().includes(query.toLowerCase()));
  const selected = entries.find(entry => entry.id === fieldId);
  const example = kind === 'schema' ? 'example-node-1' : `example-${catalogueKind}-constraint`;
  return <section className="preview-panel">
    <h3>{kind === 'schema' ? 'C01 Schema reference' : 'C02 Catalogue reference'}</h3>
    <p>Local reference example · revision example-reference-v1 · historical ledger schema revision {historical.revision}. Not a current schema/catalogue export; no registry enumerated or live data loaded.</p>
    <p>Historical ledger SHA-256: {historical.ledger_sha256}. Source revisions are retained verbatim, not refreshed to imply verification.</p>
    <p>{kind === 'schema' ? 'Illustrative field reference: graph override declarations and environment-version registration inputs. This is a bounded ledger excerpt, not the complete Arena schema.' : 'Illustrative asset, relation and task constraint reference. The historical ledger enumerates workflow restrictions, not the dynamic registry catalogue. Example identities below are local design labels, not supported registry names.'}</p>
    <label className="preview-field">Search reference fields<input type="search" aria-label="Search reference fields" value={query} onChange={event => setQuery(event.target.value)} /></label>
    {kind === 'catalogue' && <><label className="preview-field">Catalogue kind<select aria-label="Catalogue kind" value={catalogueKind} onChange={event => { setCatalogueKind(event.target.value); setFieldId(''); setConstraint(''); }}>{['asset', 'relation', 'task'].map(value => <option key={value}>{value}</option>)}</select></label><h4>{example}</h4><p>Selecting a constraint does not select a base environment. No source, version or active draft is changed.</p><button onClick={() => setConstraint(example)}>Select local example constraint</button><p role="status">{constraint ? `Local constraint selection: ${constraint}; not applied or submitted.` : 'No constraint selected.'}</p></>}
    <div className="preview-list">{entries.map(entry => <article key={entry.id} className="preview-panel"><button aria-label={`Inspect reference ${entry.name}`} onClick={() => setFieldId(entry.id)}>{entry.name}</button><p>{entry.id}</p><p>{entry.precedence}</p></article>)}</div>
    {entries.length === 0 && <p>No matching reference fields.</p>}
    {selected && <section aria-label="Reference field details" className="preview-panel"><h4>{selected.name}</h4><dl><dt>Local illustrative value — not an effective default</dt><dd>{example}</dd><dt>Declared type / parameter metadata</dt><dd><pre>{json('type_expression' in selected ? selected.type_expression : 'parser_kwargs' in selected ? selected.parser_kwargs : 'No type established in this ledger entry')}</pre></dd><dt>Historical default</dt><dd><pre>{json(selected.default)}</pre></dd><dt>Profile restriction</dt><dd>{selected.profile} · {selected.disposition}</dd><dt>Precedence and restrictions</dt><dd>{selected.precedence}</dd></dl><pre>{json(selected.source_refs)}</pre><ul>{selected.coverage_limitations.map(text => <li key={text}>{text}</li>)}</ul></section>}
    <p>Download contract: production would export the exact revision-bound schema or catalogue, without an agent or simulator. This preview can only export the labelled local ledger excerpt, never a claimed current runtime schema.</p>
    <a download={`example-${kind}-ledger-excerpt.json`} href={`data:application/json;charset=utf-8,${encodeURIComponent(json({ example_only: true, revision: 'example-reference-v1', historical_ledger_sha256: historical.ledger_sha256, entries }))}`}>Download local example excerpt</a>
  </section>;
}
