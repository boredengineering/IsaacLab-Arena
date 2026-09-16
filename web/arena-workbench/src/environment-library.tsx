import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import './environment-library.css';
import {
  isCompleteRevision, libraryReference,
  LIBRARY_PIN_LIMIT, LIBRARY_RECENT_LIMIT,
  metadataFields, normalizeLibrarySource, normalizeLibrarySources, referenceKey,
  referenceStateLabel, resolveLibraryReference,
  type InspectedSource, type LibraryReference, type SourceSummary, type SourcesStatus,
} from './environment-library-contract';
import { createLibraryPreferencesController } from './library-preferences';
export { LIBRARY_PREFERENCES_KEY, normalizeLibrarySources, type SourceSummary } from './environment-library-contract';
export interface EnvironmentLibraryProps {
  sources: readonly SourceSummary[];
  /** Display marker only; selection and restoration never dispatch Open. */
  selectedId?: string;
  /** Parent data owner must withhold stale catalogue actions on loading/error. */
  sourcesStatus?: SourcesStatus;
  /** Detached exact-source request only. Parent owns unsaved confirmation, loading
   * and identity/hash verification. A return value or fulfilled promise is NOT success. */
  onOpen: (source: SourceSummary) => void;
  /** Publish only after verified success; sequence is a nonnegative safe integer
   * increasing for this mounted owner. Revisions require revision_id and both hashes.
   * Remount on data-owner retirement; preferences never authenticate a new owner. */
  opened?: { source: SourceSummary; sequence: number };
}
const kindLabel = (source: LibraryReference) => source.kind === 'research_version' ? 'Immutable research version' : source.kind === 'editor_revision' ? 'Immutable editor revision' : 'Discovered file · mutable pointer';

export function EnvironmentLibrary({ sources, selectedId, onOpen, opened, sourcesStatus = 'ready' }: EnvironmentLibraryProps) {
  const panelId = useId();
  const inspectionHeading = useRef<HTMLHeadingElement>(null);
  const [inspectionExpanded, setInspectionExpanded] = useState(true);
  const [comparisonExpanded, setComparisonExpanded] = useState(true);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [inspection, setInspection] = useState<InspectedSource>();
  const [preferenceController] = useState(() => createLibraryPreferencesController());
  const {preferences, notice: preferenceNotice, mode: preferenceMode} = useSyncExternalStore(preferenceController.subscribe, preferenceController.getSnapshot, preferenceController.getSnapshot);
  const {pins, recents} = preferences;
  const preferenceOwner = preferenceController.captureOwner();
  useEffect(() => preferenceController.activate(), [preferenceController]);
  const [confirmedThisMount, setConfirmedThisMount] = useState<LibraryReference[]>([]);
  const [comparisonChoice, setComparisonChoice] = useState('');
  const [comparison, setComparison] = useState<readonly [InspectedSource, SourceSummary]>();
  const [openError, setOpenError] = useState(false);
  const lastSequence = useRef(-1);
  const requestEpoch = useRef(0);
  const catalogue = normalizeLibrarySources(sources);
  const authorityKey = JSON.stringify([sourcesStatus, catalogue.sources, [...catalogue.invalidIds]]);
  const authority = useMemo(() => ({}), [authorityKey]);
  const currentAuthority = useRef(authority);
  useLayoutEffect(() => {currentAuthority.current = authority; return () => {currentAuthority.current = {};};}, [authority]);
  const sourceAdmitted = () => {
    if (!preferenceOwner() || currentAuthority.current !== authority || sourcesStatus !== 'ready') return false;
    // Props can contain caller-owned mutable objects even before React rerenders.
    const current = normalizeLibrarySources(sources);
    return authorityKey === JSON.stringify([sourcesStatus, current.sources, [...current.invalidIds]]);
  };
  // A verified parent receipt is independent of mutable catalogue availability.
  // Preserve its own identity/owner fence; it grants history, not source actions.
  const openedKey = JSON.stringify([opened?.sequence, opened && normalizeLibrarySource(opened.source)]);
  const openedAuthority = useMemo(() => ({}), [openedKey]);
  const currentOpenedAuthority = useRef(openedAuthority);
  useLayoutEffect(() => {
    currentOpenedAuthority.current = openedAuthority;
    return () => {currentOpenedAuthority.current = {};};
  }, [openedAuthority]);
  const openedAdmitted = () => preferenceOwner() && currentOpenedAuthority.current === openedAuthority
    && openedKey === JSON.stringify([opened?.sequence, opened && normalizeLibrarySource(opened.source)]);
  const available = sourcesStatus === 'ready' ? catalogue.sources : [];
  const query = search.toLowerCase();
  // Search only the bounded, normalized presentation fields, never nested provenance.
  const matches = available.filter(source => metadataFields.some(([key]) => {
    const value = source[key];
    return typeof value === 'string' && value.toLowerCase().includes(query);
  }));
  const currentPage = Math.min(page, Math.max(0, Math.ceil(matches.length / 24) - 1));
  const resolve = (ref: LibraryReference) => resolveLibraryReference(ref, catalogue, sourcesStatus);
  const inspectedKey = inspection ? referenceKey(inspection) : undefined;
  const inspectedSource = inspection ? resolve(inspection).source : undefined;
  const pinned = pins.some(item => referenceKey(item) === inspectedKey);
  const canPin = preferenceMode !== 'initializing' && inspection && inspectedSource && isCompleteRevision(inspection) && confirmedThisMount.some(item => referenceKey(item) === inspectedKey) && pins.length < LIBRARY_PIN_LIMIT;
  const comparisonOptions = available.filter(source => source.id !== inspection?.id);
  const comparisonTarget = comparisonOptions.find(source => referenceKey(source) === comparisonChoice);

  useEffect(() => () => { requestEpoch.current++; }, []);
  useEffect(() => { if (inspection && inspectionExpanded) inspectionHeading.current?.focus(); }, [inspection, inspectionExpanded]);
  useEffect(() => {
    if (!comparisonTarget && comparisonChoice) setComparisonChoice('');
  }, [comparisonTarget, comparisonChoice]);
  useEffect(() => {
    if (preferenceMode === 'initializing' || !openedAdmitted()) return;
    if (!opened || !Number.isSafeInteger(opened.sequence) || opened.sequence < 0 || opened.sequence <= lastSequence.current) return;
    lastSequence.current = opened.sequence;
    const source = normalizeLibrarySource(opened.source);
    if (!source || (source.kind === 'editor_revision' && !isCompleteRevision(source))) return;
    const ref = libraryReference(source);
    const prepend = (current: LibraryReference[]) => [ref, ...current.filter(item => referenceKey(item) !== referenceKey(ref))].slice(0, LIBRARY_RECENT_LIMIT);
    setConfirmedThisMount(prepend);
    void preferenceController.recordOpened(ref, openedAdmitted);
  }, [opened, openedAuthority, preferenceMode, preferenceController]);

  function inspect(source: InspectedSource) {
    requestEpoch.current++;
    setOpenError(false);
    setComparisonChoice('');
    setInspection({ ...source });
    setInspectionExpanded(true);
  }
  function inspectReference(ref: LibraryReference) {
    // Only exact identity resolution can supply presentation metadata; never latest.
    inspect(resolve(ref).source ?? libraryReference(ref));
  }
  function requestOpen() {
    if (!inspection || !inspectedSource) return;
    const epoch = ++requestEpoch.current;
    setOpenError(false);
    const failed = () => { if (epoch === requestEpoch.current) setOpenError(true); };
    // Freeze the displayed source, not a newer same-ID catalogue row.
    const payload = normalizeLibrarySource(inspection);
    if (!payload) return;
    try { void Promise.resolve(onOpen(payload)).catch(failed); }
    catch { failed(); }
  }
  function unpin(ref: LibraryReference) {
    void preferenceController.unpin(ref, () => preferenceOwner() && currentAuthority.current === authority);
  }
  function referenceList(refs: LibraryReference[], isPins: boolean) {
    return <ul>{refs.map(ref => <li key={referenceKey(ref)}>
      <code tabIndex={0}>{ref.id}</code><span>{kindLabel(ref)}</span>
      {ref.source_hash && <code tabIndex={0}>{ref.source_hash}</code>}
      <span>{referenceStateLabel[resolve(ref).state]}</span>
      <button type="button" aria-label={`Inspect reference ${ref.id}`} onClick={() => inspectReference(ref)}>Inspect</button>
      {isPins && <button type="button" aria-label={`Remove pin ${ref.id}`} onClick={() => unpin(ref)}>Remove pin</button>}
    </li>)}</ul>;
  }
  return <section className="environment-library" aria-label="Environment library">
    <h2>Library</h2>
    <p>Local references are not proof of a current successful open. Reopening is verified by the parent.</p>
    {preferenceNotice && <p role="status">{preferenceNotice}</p>}
    <p>Editor revisions are not research versions. No family, type or version is inferred from filenames.</p>
    {catalogue.issues.map(issue => <p role="alert" key={issue}>{issue}</p>)}
    {sourcesStatus !== 'ready' && <p role="status">{sourcesStatus === 'loading' ? 'Loading sources…' : 'Sources unavailable. No replacement or latest-source fallback.'}</p>}
    <label htmlFor={`${panelId}-search`}>Search library</label>
    <input id={`${panelId}-search`} type="search" maxLength={256} value={search} onChange={event => { setSearch(event.target.value.slice(0, 256)); setPage(0); }} />
    <div className="library-workspace">
    <section aria-label="Library sources">
      <p role="status">{sourcesStatus === 'ready' ? `${matches.length} matching sources` : 'Source actions withheld'}</p>
      {sourcesStatus === 'ready' && !matches.length && <p>{available.length ? 'No matching sources.' : 'No sources supplied.'}</p>}
      <div className="library-cards">
      {matches.slice(currentPage * 24, (currentPage + 1) * 24).map(source => <article key={source.id}>
        <h3>{source.name}</h3><p>{kindLabel(source)}</p><code tabIndex={0}>{source.source}</code>
        <code tabIndex={0} id={`${panelId}-source-${source.id}`}>{source.id}</code>
        {source.id === selectedId && <p>Selected in editor</p>}
        <button type="button" aria-describedby={`${panelId}-source-${source.id}`} onClick={() => inspect(source)}>Inspect {source.name}</button>
      </article>)}
      </div>
      <div className="library-actions">
        <button type="button" aria-label="Previous library page" disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>Previous</button>
        <span>Page {currentPage + 1} / {Math.max(1, Math.ceil(matches.length / 24))}</span>
        <button type="button" aria-label="Next library page" disabled={(currentPage + 1) * 24 >= matches.length} onClick={() => setPage(currentPage + 1)}>Next</button>
      </div>
    </section>
    {inspection && <div className="library-inspector">
      <button type="button" aria-expanded={inspectionExpanded} aria-controls={`${panelId}-inspection`} onClick={() => setInspectionExpanded(value => !value)}>{inspectionExpanded ? 'Collapse inspection' : 'Expand inspection'}</button>
      <section id={`${panelId}-inspection`} aria-label="Source inspection" hidden={!inspectionExpanded}>
      <h3 tabIndex={-1} ref={inspectionHeading}>{inspection.name ?? 'Retained reference'}</h3>
      <p>{referenceStateLabel[resolve(inspection).state]}</p>
      <div className="library-metadata-scroll" role="region" aria-label="Source metadata scroll area" tabIndex={0}>
        <dl>{metadataFields.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{inspection[key] ?? 'Not provided'}</dd></div>)}</dl>
        {inspection.research_identity && <dl><dt>Research store</dt><dd>{inspection.research_identity.store_id}</dd><dt>Research family</dt><dd>{inspection.research_identity.family}</dd><dt>Research version</dt><dd>{inspection.research_identity.version}</dd><dt>Reservation ID</dt><dd>{inspection.research_identity.reservation_id}</dd><dt>Manifest digest</dt><dd>{inspection.research_identity.manifest_digest}</dd></dl>}
      </div>
      <p>The parent confirms any unsaved replacement before loading. Inspect does not open a source.</p>
      <button type="button" disabled={!inspectedSource || !inspection.name || !inspection.source} onClick={requestOpen}>Open source in editor</button>
      {openError && <p role="alert">Open request failed. No recent was added.</p>}
      {inspection.kind !== 'discovered_file' ? <>
        <button type="button" disabled={!pinned && !canPin} onClick={() => {
          if (pinned) unpin(inspection);
          else if (canPin) void preferenceController.pin(libraryReference(inspection), () => sourceAdmitted() && !!canPin);
        }}>{pinned ? 'Unpin exact revision' : 'Pin exact revision'}</button>
        {!pinned && pins.length >= LIBRARY_PIN_LIMIT && <p>Pin limit reached (8). Remove a pin first.</p>}
        {!pinned && !canPin && <p>{inspection.kind === 'research_version' ? 'Pinning requires a confirmed successful open with exact research identity and root hash. Unknown canonical hashes are not inferred.' : 'Pinning requires a confirmed successful open with exact revision ID and both hashes.'}</p>}
      </> : <p>Mutable file pointers cannot be pinned as immutable revisions.</p>}
      <label>Compare with source <select aria-label="Compare with source" value={comparisonTarget ? comparisonChoice : ''} onChange={event => setComparisonChoice(event.target.value)}>
        <option value="">Choose a different source</option>
        {comparisonOptions.map(source => <option key={source.id} value={referenceKey(source)}>{source.name} — {source.id}</option>)}
      </select></label>
      <button type="button" disabled={!inspectedSource || !comparisonTarget} onClick={() => {
        if (inspectedSource && comparisonTarget) {
          setComparison([{ ...inspection }, { ...comparisonTarget }]);
          setComparisonExpanded(true);
        }
      }}>Freeze metadata comparison</button>
    </section></div>}
    </div>
    <div className="library-shelves">
    <section aria-label="Pinned revisions"><h3>Pinned revisions</h3>
      {!pins.length && <p>No pinned revisions.</p>}{referenceList(pins, true)}
    </section>
    <section aria-label="Recent opens"><h3>Recent opens</h3>
      {!recents.length && <p>No confirmed opens.</p>}{referenceList(recents, false)}
    </section>
    </div>
    {comparison && <section aria-label="Frozen comparison">
      <h3>Frozen comparison</h3>
      <div className="library-actions">
        <button type="button" aria-expanded={comparisonExpanded} aria-controls={`${panelId}-comparison`} onClick={() => setComparisonExpanded(value => !value)}>{comparisonExpanded ? 'Collapse comparison' : 'Expand comparison'}</button>
        <button type="button" onClick={() => setComparison(undefined)}>Clear comparison</button>
      </div>
      <div id={`${panelId}-comparison`} hidden={!comparisonExpanded}>
      <p>Metadata only — not a raw YAML/content diff. Matching canonical hashes do not prove identical source bytes.</p>
      <p>A: {referenceStateLabel[resolve(comparison[0]).state]}</p>
      <p>B: {referenceStateLabel[resolve(comparison[1]).state]}</p>
      <div className="library-table-scroll" role="region" aria-label="Comparison table scroll area" tabIndex={0}>
      <table><caption>Frozen source metadata comparison</caption>
        <thead><tr><th scope="col">Field</th><th scope="col">A (frozen)</th><th scope="col">B (frozen)</th><th scope="col">Exact equality</th></tr></thead>
        <tbody>{metadataFields.map(([key, label]) => {
          const a = comparison[0][key]; const b = comparison[1][key];
          return <tr key={key}><th scope="row">{label}</th><td>{a ?? 'Not provided'}</td><td>{b ?? 'Not provided'}</td><td>{a === undefined || b === undefined ? 'Unknown' : a === b ? 'Same' : 'Different'}</td></tr>;
        })}</tbody>
      </table>
      </div></div>
    </section>}
  </section>;
}
