import { useEffect, useState } from 'react';
import { exampleFamilies } from './library-data';
import type { ExampleFamily, ExampleVersion } from './library-data';
import type { PreviewSelection } from './types';

interface EnvironmentPickerProps {
  selection: PreviewSelection | null;
  onOpen: (selection: PreviewSelection) => void;
  onBrowse: () => void;
}

export function EnvironmentPicker(props: EnvironmentPickerProps) {
  return <PickerDraft key={JSON.stringify([props.selection?.familyId, props.selection?.versionId])} {...props} />;
}

function PickerDraft({ selection, onOpen, onBrowse }: EnvironmentPickerProps) {
  const catalogue = exampleFamilies.filter((family) => family.kind === 'environment');
  const local = selection && selection.versionId.startsWith('example-local-') &&
    !exampleFamilies.some((family) => family.id === selection.familyId && family.kind !== 'environment') &&
    !catalogue.some((family) => family.id === selection.familyId && family.versions.some((version) => version.versionId === selection.versionId)) ? selection : null;
  // A local revision is one exact supplied choice, never merged by display name.
  const localChoiceId = local && catalogue.some((family) => family.id === local.familyId) ? `local:${local.versionId}` : local?.familyId;
  const [familyId, setFamilyId] = useState(localChoiceId ?? selection?.familyId ?? '');
  const [versionId, setVersionId] = useState(selection?.versionId ?? '');
  const families = local ? [...catalogue, { id: localChoiceId!, name: `${local.familyName} · local draft example`, baselineVersionId: null, versions: [local] }] : catalogue;
  const family = families.find((item) => item.id === familyId);
  const version = family?.versions.find((item) => item.versionId === versionId);
  return <section className="preview-environment-picker" aria-label="Environment picker">
    <p className="preview-muted">{selection ? `Open: ${selection.familyName} · v${selection.version}` : 'No environment open'}</p>
    <div className="preview-actions">
      <label className="preview-field">Family<select aria-label="Environment family" value={family?.id ?? ''} onChange={(event) => {
        const chosen = families.find((item) => item.id === event.target.value);
        setFamilyId(chosen?.id ?? ''); setVersionId(local && chosen?.id === localChoiceId ? local.versionId : chosen?.baselineVersionId ?? '');
      }}>
        <option value="">Choose example family…</option>
        {families.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      <label className="preview-field">Version<select aria-label="Environment version" value={version?.versionId ?? ''} disabled={!family} onChange={(event) => setVersionId(event.target.value)}>
        {!version && <option value="">Choose exact version…</option>}
        {family && [...family.versions].sort((a, b) => a.version - b.version).map((item) => <option key={item.versionId} value={item.versionId}>v{item.version}{item.versionId === family.baselineVersionId ? ' · explicit baseline' : ''}</option>)}
      </select></label>
      <button type="button" disabled={!version} onClick={() => { if (version) onOpen(version); }}>Open selected version</button>
      <button type="button" onClick={onBrowse}>Browse Library</button>
    </div>
  </section>;
}

function ImportReview() {
  const [sourceId, setSourceId] = useState('example-a2-droid');
  const [expectedKind, setExpectedKind] = useState('environment');
  const [review, setReview] = useState<string | null>(null);
  const source = exampleFamilies.find((family) => family.id === sourceId)!;
  return <details className="preview-panel preview-import-review">
    <summary>Approved import review · preview only</summary>
    <p className="preview-muted">Only bundled synthetic sources are selectable. No host paths, uploads, reads, imports or persistence.</p>
    <div className="preview-grid">
      <label className="preview-field">Approved example source<select aria-label="Approved example source" value={sourceId} onChange={(event) => { setSourceId(event.target.value); setReview(null); }}>
        {exampleFamilies.map((family) => <option key={family.id} value={family.id}>{family.name}</option>)}
      </select></label>
      <label className="preview-field">Expected root kind<select aria-label="Expected root kind" value={expectedKind} onChange={(event) => { setExpectedKind(event.target.value); setReview(null); }}>
        <option value="environment">Environment</option><option value="policy">Policy</option><option value="experiment">Experiment</option>
      </select></label>
    </div>
    <dl className="preview-grid">
      <div><dt>Declared example root</dt><dd>{source.kind}</dd></div>
      <div><dt>Source identity</dt><dd>{source.versions[0].source}</dd></div>
      <div><dt>Raw / canonical identity</dt><dd>Unavailable · no bytes parsed or hashes computed</dd></div>
      <div><dt>Frozen includes</dt><dd>Unverified · future approved-root resolution required</dd></div>
    </dl>
    <button type="button" onClick={() => setReview(expectedKind !== source.kind
      ? `Kind mismatch: expected ${expectedKind}, example declares ${source.kind}. Import blocked.`
      : `Review only: ${source.kind} root matches. Nothing imported; identity and include validation require the future adapter.`)}>Review example import</button>
    {review && <p role="status">{review}</p>}
  </details>;
}

const exactIdentity = (selection: PreviewSelection) => JSON.stringify([selection.familyId, selection.versionId]);

function snapshotVersion(selection: PreviewSelection): ExampleVersion {
  const metadata = selection as Partial<ExampleVersion>;
  return { familyId: selection.familyId, familyName: selection.familyName, versionId: selection.versionId, version: selection.version,
    source: selection.source, yaml: selection.yaml, robot: selection.robot, hand: selection.hand,
    parent: typeof metadata.parent === 'string' || metadata.parent === null ? metadata.parent : 'Unavailable · no parent metadata supplied',
    status: typeof metadata.status === 'string' ? metadata.status : 'Local saved example · not validated' };
}

function libraryFamilies(extras: readonly PreviewSelection[]): ExampleFamily[] {
  const families = exampleFamilies.map((family) => ({ ...family, versions: [...family.versions] }));
  for (const item of extras) {
    let family = families.find((candidate) => candidate.id === item.familyId);
    if (!family) {
      // Unknown families enter only through the parent's local saved/opened environment contract.
      family = { id: item.familyId, name: item.familyName, internalName: 'Unavailable · local example', kind: 'environment',
        scenario: 'Local saved example · no execution evidence', robot: item.robot, hand: item.hand, baselineVersionId: null, versions: [] };
      families.push(family);
    }
    if (!family.versions.some((version) => version.versionId === item.versionId)) family.versions.push(snapshotVersion(item));
  }
  return families;
}

interface LibraryPanelProps {
  onOpen: (selection: PreviewSelection) => void;
  opened?: PreviewSelection | null;
  localVersions?: readonly PreviewSelection[];
}

export function LibraryPanel({ onOpen, opened, localVersions = [] }: LibraryPanelProps) {
  const [pins, setPins] = useState<PreviewSelection[]>([]);
  const [recents, setRecents] = useState<PreviewSelection[]>([]);
  useEffect(() => {
    if (opened) setRecents((current) => [snapshotVersion(opened), ...current.filter((item) => exactIdentity(item) !== exactIdentity(opened))]);
  }, [opened]);
  const families = libraryFamilies([...localVersions, ...pins, ...recents]);
  const [familyId, setFamilyId] = useState<string | null>(null);
  const [versionId, setVersionId] = useState<string | null>(null);
  const [inspectedSnapshot, setInspectedSnapshot] = useState<ExampleVersion | null>(null);
  const [comparisonId, setComparisonId] = useState('');
  const [comparisonFamilyId, setComparisonFamilyId] = useState<string | null>(null);
  const [frozen, setFrozen] = useState<{ before: ExampleVersion; after: ExampleVersion } | null>(null);
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const visibleFamilies = families.filter((item) => (kind === 'all' || item.kind === kind) &&
    [item.id, item.name, item.internalName, item.scenario, item.robot, item.hand, ...item.versions.map((entry) => entry.source)].join(' ').toLowerCase().includes(query.trim().toLowerCase()));
  const family = visibleFamilies.find((item) => item.id === familyId);
  const version = family && (inspectedSnapshot ?? family.versions.find((item) => item.versionId === versionId));
  const selectedFamily = families.find((item) => item.id === familyId);
  const currentPrimary = selectedFamily?.versions.find((item) => item.versionId === versionId);
  const primary = inspectedSnapshot ?? currentPrimary;
  const comparison = familyId === comparisonFamilyId ? selectedFamily?.versions.find((item) => item.versionId === comparisonId && item.versionId !== versionId) : undefined;
  // Reconcile state as well as rendered options; filtering alone must not reset retained choices.
  useEffect(() => { if (comparisonId && !comparison) setComparisonId(''); }, [comparisonId, comparison]);
  const currentMatchesFrozen = frozen && primary && comparison &&
    JSON.stringify([snapshotVersion(primary), snapshotVersion(comparison)]) === JSON.stringify([frozen.before, frozen.after]);
  return <section className="preview-panel preview-library">
    <h2>Document Library</h2>
    <p className="preview-muted">Synthetic example documents only. Families are grouped by stable identity, not robot or filename.</p>
    <p className="preview-muted">Pins are explicit exact-version choices in local memory only. Example activity markers are not your pins or recent opens.</p>
    <section className="preview-library-pins" aria-label="Local pins">
      <h3>Local pins</h3>
      {pins.length === 0 && <p>No local pins.</p>}
      {pins.map((item) => <article className="preview-library-card" key={exactIdentity(item)}>
        <h4>{item.familyName} · v{item.version}</h4>
        <p>{item.familyId}</p><p>{item.versionId}</p><p>{item.source}</p>
        <button type="button" onClick={() => { setInspectedSnapshot(snapshotVersion(item)); setFamilyId(item.familyId); setVersionId(item.versionId); setKind('all'); setQuery(''); }}>Inspect pinned version</button>
        {families.find((family) => family.id === item.familyId)?.kind === 'environment' &&
          <button type="button" onClick={() => onOpen(item)}>Open pinned environment</button>}
      </article>)}
    </section>
    <section className="preview-library-recents" aria-label="Recent opens">
      <h3>Recent opens</h3>
      {recents.length === 0 && <p>No confirmed opens yet.</p>}
      {recents.map((item) => <article className="preview-library-card" key={exactIdentity(item)}>
        <h4>{item.familyName} · v{item.version}</h4>
        <p>{item.familyId}</p><p>{item.versionId}</p><p>{item.source}</p>
        <button type="button" onClick={() => { setInspectedSnapshot(snapshotVersion(item)); setFamilyId(item.familyId); setVersionId(item.versionId); setKind('all'); setQuery(''); }}>Inspect recent version</button>
        {families.find((family) => family.id === item.familyId)?.kind === 'environment' &&
          <button type="button" onClick={() => onOpen(item)}>Open recent environment</button>}
      </article>)}
    </section>
    <div className="preview-grid">
      <label className="preview-field">Search example library<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Family, source, scenario, robot…" /></label>
      <label className="preview-field">Document kind<select aria-label="Document kind" value={kind} onChange={(event) => setKind(event.target.value)}>
        <option value="all">All kinds</option><option value="environment">Environments</option><option value="policy">Policies</option><option value="experiment">Experiments</option><option value="unclassified">Unclassified</option>
      </select></label>
    </div>
    <table className="preview-table" aria-label="Example document families">
      <thead><tr><th>Family / document</th><th>Kind</th><th>Robot / hand</th><th>Versions</th><th>Example activity</th></tr></thead>
      <tbody>{visibleFamilies.map((family) => <tr key={family.id}>
        <td><button type="button" aria-label={`Inspect ${family.name}`} onClick={() => { setInspectedSnapshot(null); setFamilyId(family.id); setVersionId(family.baselineVersionId ?? family.versions[0].versionId); }}>{family.name}</button><div className="preview-muted">{family.id}</div></td>
        <td>{family.kind}</td><td>{family.robot} · {family.hand}</td><td>{family.versions.length} versions</td><td>{family.marker ?? '—'}</td>
      </tr>)}</tbody>
    </table>
    {visibleFamilies.length === 0 && <p className="preview-muted">No example documents match these filters.</p>}
    {family && version && <section className="preview-panel preview-version-inspector" aria-label="Version inspector">
      <h3>{family.name} · version inspector</h3>
      <p>{family.scenario}</p>
      {inspectedSnapshot && <div className="preview-library-captured-source">
        <p className="preview-muted">Inspecting a captured local card source, not a refreshed catalogue record.</p>
        <button type="button" disabled={!currentPrimary} onClick={() => setInspectedSnapshot(null)}>Inspect current supplied version</button>
      </div>}
      <label className="preview-field">Inspect version<select aria-label="Inspect version" value={version.versionId} onChange={(event) => { setInspectedSnapshot(null); setVersionId(event.target.value); }}>
        {[...family.versions].sort((a, b) => a.version - b.version).map((item) => <option key={item.versionId} value={item.versionId}>v{item.version}{item.versionId === family.baselineVersionId ? ' · explicit baseline' : ''}</option>)}
      </select></label>
      <dl className="preview-grid">
        <div><dt>Stable family identity</dt><dd>{family.id}</dd></div>
        <div><dt>Internal name</dt><dd>{family.internalName}</dd></div>
        <div><dt>Exact version identity</dt><dd>{version.versionId}</dd></div>
        <div><dt>Source</dt><dd>{version.source}</dd></div>
        <div><dt>Parent</dt><dd>{version.parent ?? 'None · example origin'}</dd></div>
        <div><dt>Robot</dt><dd>{version.robot}</dd></div>
        <div><dt>Hand</dt><dd>{version.hand}</dd></div>
        <div><dt>Status</dt><dd>{version.status}</dd></div>
      </dl>
      <p className="preview-muted">No rendered preview or execution evidence.</p>
      <details><summary>Example source preview</summary><pre>{version.yaml}</pre></details>
      <button type="button" onClick={() => setPins((current) => current.some((item) => exactIdentity(item) === exactIdentity(version))
        ? current.filter((item) => exactIdentity(item) !== exactIdentity(version)) : [...current, snapshotVersion(version)])}>
        {pins.some((item) => exactIdentity(item) === exactIdentity(version)) ? 'Unpin inspected version' : 'Pin inspected version'}
      </button>
      <p className="preview-muted">Inspecting is local. Open requests an exact version; the workspace reviews unsaved changes. Baseline is explicitly labelled, not inferred latest or best.</p>
      <section className="preview-library-comparison-controls" aria-label="Version comparison choices">
        <h4>Compare exact versions</h4>
        <p className="preview-muted">Before is the inspected version. Select a distinct same-family version as After. No latest/best selection or inferred metrics.</p>
        <label className="preview-field">Compare with version<select aria-label="Compare with version" value={comparison?.versionId ?? ''} onChange={(event) => { setComparisonFamilyId(family.id); setComparisonId(event.target.value); }}>
          <option value="">Choose exact comparison version…</option>
          {[...family.versions].filter((item) => item.versionId !== version.versionId).sort((a, b) => a.version - b.version).map((item) => <option key={item.versionId} value={item.versionId}>v{item.version} · {item.versionId}</option>)}
        </select></label>
        <button type="button" disabled={!comparison || !!frozen} onClick={() => {
          if (primary && comparison && primary.familyId === comparison.familyId && exactIdentity(primary) !== exactIdentity(comparison) && !frozen) {
            setFrozen({ before: snapshotVersion(primary), after: snapshotVersion(comparison) });
          }
        }}>Freeze version comparison</button>
      </section>
      {family.kind === 'environment' ? <div className="preview-actions"><button type="button" onClick={() => onOpen(version)}>Open environment</button></div> : <p className="preview-muted">Only environment documents can be opened in the workspace.</p>}
    </section>}
    {frozen && <section className="preview-library-comparison" aria-label="Frozen version comparison">
      <h3>Frozen version comparison</h3>
      <p className="preview-muted">Local source review only · no execution evidence or computed performance metrics. Clear this review before replacing it.</p>
      <p>{currentMatchesFrozen ? 'Current choices match the frozen comparison.' : 'Current choices differ from the frozen comparison. Clear it before reviewing another pair.'}</p>
      <div className="preview-library-comparison-grid">{(['before', 'after'] as const).map((side) => {
        const item = frozen[side];
        return <section key={side} className="preview-library-comparison-side" aria-label={side === 'before' ? 'Before version' : 'After version'}>
          <h4>{side === 'before' ? 'Before' : 'After'} · {item.familyName} · v{item.version}</h4>
          <dl><div><dt>Family</dt><dd>{item.familyId}</dd></div><div><dt>Exact version identity</dt><dd>{item.versionId}</dd></div>
            <div><dt>Source</dt><dd>{item.source}</dd></div><div><dt>Parent</dt><dd>{item.parent ?? 'None supplied · not inferred'}</dd></div></dl>
          <pre>{item.yaml}</pre>
        </section>;
      })}</div>
      <button type="button" onClick={() => setFrozen(null)}>Clear frozen comparison</button>
    </section>}
    <ImportReview />
  </section>;
}
