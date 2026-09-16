import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { StrictMode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { EnvironmentLibrary, LIBRARY_PREFERENCES_KEY, normalizeLibrarySources, type SourceSummary } from './environment-library';
import { researchOpen } from './research-source';
import * as nativePreferences from './library-preferences-native';
import { decodeLibraryEnvelope } from './library-preferences';

// Serial deterministic adapter integration, not native browser IndexedDB evidence.
function transactionalPreferences() {
  let stored: unknown;
  let tail = Promise.resolve();
  let lost: () => void = () => {};
  vi.spyOn(nativePreferences, 'createNativeLibraryAdapter').mockImplementation(() => ({
    open: callback => {lost = callback; return Promise.resolve();}, close() {},
    transaction(mode, mutate) {
      const operation = tail.then(() => {const next = mutate(structuredClone(stored)); if (mode === 'readwrite') stored = structuredClone(next); return next;});
      tail = operation.then(() => {}, () => {}); return operation;
    },
  }));
  return {loseConnection: () => lost(), get preferences() {return decodeLibraryEnvelope(stored)?.preferences;}};
}
const settled = () => act(async () => {for (let n = 0; n < 16; n++) await Promise.resolve();});

it.each(['loading', 'unavailable'] as const)('records a parent-confirmed Open while the catalogue is %s without granting source actions', async sourcesStatus => {
  const storage = transactionalPreferences();
  const source = revision();
  const onOpen = vi.fn();
  render(<EnvironmentLibrary sources={[]} sourcesStatus={sourcesStatus} opened={{source, sequence: 1}} onOpen={onOpen} />);
  await settled();
  expect(storage.preferences?.recents).toEqual([storedRef(source)]);
  fireEvent.click(region('Recent opens').getByRole('button', {name: `Inspect reference ${source.id}`}));
  expect(region('Source inspection').getByRole('button', {name: 'Open source in editor'})).toBeDisabled();
  expect(region('Source inspection').getByRole('button', {name: 'Pin exact revision'})).toBeDisabled();
  expect(onOpen).not.toHaveBeenCalled();
  expect(localStorage.getItem(LIBRARY_PREFERENCES_KEY)).toBeNull();
});

it('withholds preference commands during IndexedDB initialization while keeping browsing available', () => {
  vi.spyOn(nativePreferences, 'createNativeLibraryAdapter').mockReturnValue({open: () => new Promise(() => {}), transaction: vi.fn(), close: vi.fn()});
  const source = revision();
  render(<EnvironmentLibrary sources={[source]} onOpen={vi.fn()} opened={{source, sequence: 1}} />);
  inspect();
  expect(screen.getByText('Loading Library preferences…')).toBeInTheDocument();
  expect(region('Source inspection').getByRole('button', {name: 'Pin exact revision'})).toBeDisabled();
  expect(region('Source inspection').getByRole('button', {name: 'Open source in editor'})).toBeEnabled();
  expect(localStorage.getItem(LIBRARY_PREFERENCES_KEY)).toBeNull();
});

it('rechecks current source bytes at queued transaction admission without borrowing mutated caller metadata', async () => {
  const storage = transactionalPreferences();
  const source = revision();
  render(<EnvironmentLibrary sources={[source]} opened={{source, sequence: 1}} onOpen={vi.fn()} />);
  await settled(); inspect(); pin();
  source.source_hash = 'c'.repeat(64);
  await settled();
  expect(storage.preferences?.pins).toEqual([]);
  expect(region('Source inspection').getByText('a'.repeat(64))).toBeInTheDocument();
  expect(screen.queryByText('Library preferences unavailable; using memory for this mount.')).not.toBeInTheDocument();
});
it('enables fresh pin admission when verified Open is a durable recent no-op', async () => {
  transactionalPreferences();
  const source = revision();
  localStorage.setItem(LIBRARY_PREFERENCES_KEY, JSON.stringify({version: 1, pins: [], recents: [storedRef(source)]}));
  const view = render(<EnvironmentLibrary sources={[source]} onOpen={vi.fn()} />);
  await settled(); inspect();
  expect(region('Source inspection').getByRole('button', {name: 'Pin exact revision'})).toBeDisabled();
  view.rerender(<EnvironmentLibrary sources={[source]} onOpen={vi.fn()} opened={{source, sequence: 1}} />);
  await settled();
  expect(region('Source inspection').getByRole('button', {name: 'Pin exact revision'})).toBeEnabled();
});
it('retires pre-fallback pin handlers but permits a newly rendered memory-only action', async () => {
  const storage = transactionalPreferences(); const source = revision();
  render(<EnvironmentLibrary sources={[source]} opened={{source, sequence: 1}} onOpen={vi.fn()} />);
  await settled(); inspect();
  const button = region('Source inspection').getByRole('button', {name: 'Pin exact revision'});
  expect(button).toBeEnabled();
  const key = Object.keys(button).find(key => key.startsWith('__reactProps$'))!;
  const retained = (button as unknown as Record<string, {onClick: () => void}>)[key].onClick;
  act(() => storage.loseConnection());
  act(() => retained());
  expect(region('Pinned revisions').queryAllByRole('listitem')).toHaveLength(0);
  pin(); expect(region('Pinned revisions').getAllByRole('listitem')).toHaveLength(1);
  expect(storage.preferences?.pins).toEqual([]);
});
const revision = (digit = 'a', name = 'Saved scene'): SourceSummary => ({
  id: `editor-revision:${digit.repeat(32)}`, name, source: 'editor revision', kind: 'editor_revision',
  revision_id: digit.repeat(32), source_hash: digit.repeat(64), canonical_hash: 'f'.repeat(64),
});
const file: SourceSummary = { id: 'discovered-scene', name: 'Kitchen_v9_robot.yaml', source: 'generated_envs/kitchen.yaml', kind: 'discovered_file' };
beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

it('retains typed research recents and pins with literal identity rather than mutable-file or inferred canonical labels', async () => {
  const storage = transactionalPreferences();
  const r = {store_id: 'local', reservation_id: 'a'.repeat(32), revision_id: 'b'.repeat(32), family: 'Example', version: 2, source: {job_id: 'c'.repeat(32), attempt_id: 'd'.repeat(32), generation: 1, receipt_sha256: 'e'.repeat(64), request_sha256: 'f'.repeat(64)}};
  const source = researchOpen(r, {digest: '1'.repeat(64), files: {'environment.yaml': {size: 20, sha256: '2'.repeat(64)}}});
  const onOpen = vi.fn();
  const fixture = render(<EnvironmentLibrary sources={[source]} opened={{source, sequence: 1}} onOpen={onOpen} />);
  await settled();
  expect(screen.getAllByText('Immutable research version')).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', {name: 'Inspect Example v2'}));
  expect(screen.getByRole('button', {name: 'Pin exact revision'})).toBeEnabled();
  expect(screen.getByText('Research family')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: 'Pin exact revision'}));
  await settled();
  const saved = storage.preferences;
  expect(localStorage.getItem(LIBRARY_PREFERENCES_KEY)).toBeNull();
  expect(saved?.pins[0]).toMatchObject({id: source.id, research_identity: source.research_identity, source_hash: source.source_hash});
  expect(saved?.pins[0].canonical_hash).toBeUndefined();
  fixture.unmount();
  render(<EnvironmentLibrary sources={[]} onOpen={onOpen} />);
  await settled();
  expect(screen.getAllByText('Missing exact reference')).toHaveLength(2);
  expect(screen.queryByText('Discovered file · mutable pointer')).not.toBeInTheDocument();
  expect(onOpen).not.toHaveBeenCalled();
});
it('searches actual rows and separates explicit Inspect from parent-owned Open requests', () => {
  const source = revision();
  const onOpen = vi.fn();
  const view = render(<EnvironmentLibrary sources={[file, source]} selectedId={file.id} onOpen={onOpen} />);
  expect(onOpen).not.toHaveBeenCalled();
  expect(screen.queryByRole('region', { name: 'Source inspection' })).not.toBeInTheDocument();
  expect(screen.getByText('Discovered file · mutable pointer')).toBeInTheDocument();
  expect(screen.getByText('Immutable editor revision')).toBeInTheDocument();
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search library' }), { target: { value: source.revision_id } });
  expect(screen.queryByText(file.name)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Saved scene' }));
  expect(onOpen).not.toHaveBeenCalled();
  const inspection = within(screen.getByRole('region', { name: 'Source inspection' }));
  expect(inspection.getByText(source.source_hash!)).toBeInTheDocument();
  expect(inspection.getByText(/parent confirms any unsaved replacement/i)).toBeInTheDocument();
  fireEvent.click(inspection.getByRole('button', { name: 'Open source in editor' }));
  expect(onOpen).toHaveBeenCalledExactlyOnceWith(source);
  expect(within(screen.getByRole('region', { name: 'Recent opens' })).getByText('No confirmed opens.')).toBeInTheDocument();
  view.rerender(<EnvironmentLibrary sources={[file, source]} selectedId={source.id} onOpen={onOpen} />);
  expect(onOpen).toHaveBeenCalledTimes(1);
});

it('normalizes legacy catalogue rows only as discovered files and projects additive metadata', () => {
  const legacy = { id: file.id, name: file.name, source: file.source, unexpected: 'not copied' };
  expect(normalizeLibrarySources([legacy]).sources).toEqual([file]);
  expect(normalizeLibrarySources([revision()]).sources).toEqual([revision()]);
});

it.each([
  null, [], 'bad', { ...file, id: '' }, { ...file, id: ' leading' },
  { ...file, id: 'bad\n' }, { ...file, name: {} }, { ...file, source: 'x'.repeat(2049) },
  { ...file, kind: 'research_version' }, { ...revision(), id: 'editor-revision:latest' },
  { ...revision(), id: revision().id.toUpperCase() }, { ...revision(), revision_id: 'b'.repeat(32) },
  { ...revision(), source_hash: 'a'.repeat(63) }, { ...revision(), canonical_hash: 'F'.repeat(64) },
  { ...revision(), kind: undefined }, { ...revision(), kind: 'discovered_file' },
  { ...file, revision_id: 'a'.repeat(32) },
].map(row => [row]))('quarantines malformed identity case %# without repairing or deriving metadata', row => {
  const result = normalizeLibrarySources([row]);
  expect(result.sources).toEqual([]);
  expect(result.issues.length).toBeGreaterThan(0);
});

it('quarantines every duplicate occurrence including a malformed duplicate instead of choosing a winner', () => {
  const valid = revision();
  const result = normalizeLibrarySources([valid, { ...valid, source_hash: 'bad' }, file]);
  expect(result.sources).toEqual([file]);
  const onOpen = vi.fn();
  render(<EnvironmentLibrary sources={[valid, valid, file]} onOpen={onOpen} />);
  expect(screen.getByText(/Duplicate source identity/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Inspect Saved scene' })).not.toBeInTheDocument();
  expect(onOpen).not.toHaveBeenCalled();
});

it.each(['loading', 'unavailable'] as const)('withholds source actions while the parent catalogue is %s', sourcesStatus => {
  const onOpen = vi.fn();
  render(<EnvironmentLibrary sources={[file]} sourcesStatus={sourcesStatus} onOpen={onOpen} />);
  expect(screen.getByText(sourcesStatus === 'loading' ? 'Loading sources…' : 'Sources unavailable. No replacement or latest-source fallback.')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: `Inspect ${file.name}` })).not.toBeInTheDocument();
  expect(onOpen).not.toHaveBeenCalled();
});

const region = (name: string) => within(screen.getByRole('region', { name }));
const inspect = (name = 'Saved scene') => fireEvent.click(region('Library sources').getByRole('button', { name: `Inspect ${name}` }));
const pin = () => fireEvent.click(region('Source inspection').getByRole('button', { name: 'Pin exact revision' }));

it('adds recents only on a verified parent confirmation and pins only that exact confirmed revision', () => {
  const a = revision();
  const onOpen = vi.fn();
  const view = render(<EnvironmentLibrary sources={[a]} onOpen={onOpen} />);
  inspect();
  expect(region('Source inspection').getByRole('button', { name: 'Pin exact revision' })).toBeDisabled();
  fireEvent.click(region('Source inspection').getByRole('button', { name: 'Open source in editor' }));
  expect(region('Recent opens').getByText('No confirmed opens.')).toBeInTheDocument();
  view.rerender(<EnvironmentLibrary sources={[a]} onOpen={onOpen} opened={{ source: a, sequence: 1 }} />);
  expect(region('Recent opens').getAllByRole('listitem')).toHaveLength(1);
  pin();
  expect(region('Pinned revisions').getByText(a.source_hash!)).toBeInTheDocument();
  expect(region('Source inspection').getByRole('button', { name: 'Unpin exact revision' })).toBeInTheDocument();
  view.rerender(<EnvironmentLibrary sources={[a]} onOpen={onOpen} opened={{ source: { ...a }, sequence: 2 }} />);
  expect(region('Recent opens').getAllByRole('listitem')).toHaveLength(1);
  expect(onOpen).toHaveBeenCalledTimes(1);
});

it('does not count cancelled or rejected parent Open requests as success', async () => {
  const onOpen = vi.fn().mockResolvedValueOnce(false).mockRejectedValueOnce(new Error('private transport detail'));
  render(<EnvironmentLibrary sources={[revision()]} onOpen={onOpen} />);
  inspect();
  fireEvent.click(region('Source inspection').getByRole('button', { name: 'Open source in editor' }));
  fireEvent.click(region('Source inspection').getByRole('button', { name: 'Open source in editor' }));
  expect(await screen.findByText('Open request failed. No recent was added.')).toBeInTheDocument();
  expect(screen.queryByText('private transport detail')).not.toBeInTheDocument();
  expect(region('Recent opens').getByText('No confirmed opens.')).toBeInTheDocument();
});

it('keeps discovered files explicitly mutable and refuses an immutable pin even after opening', () => {
  render(<EnvironmentLibrary sources={[file]} onOpen={vi.fn()} opened={{ source: file, sequence: 1 }} />);
  inspect(file.name);
  expect(region('Source inspection').getByText('Mutable file pointers cannot be pinned as immutable revisions.')).toBeInTheDocument();
  expect(region('Source inspection').queryByRole('button', { name: 'Pin exact revision' })).not.toBeInTheDocument();
  expect(region('Recent opens').getAllByRole('listitem')).toHaveLength(1);
});

it('bounds recents to 12, pins to 8, ignores replayed sequences and removes pins explicitly', () => {
  const rows = Array.from({ length: 14 }, (_, n) => revision(n.toString(16), `Scene ${n}`));
  const onOpen = vi.fn();
  const view = render(<EnvironmentLibrary sources={rows} onOpen={onOpen} />);
  for (const [index, row] of rows.entries()) {
    view.rerender(<EnvironmentLibrary sources={rows} onOpen={onOpen} opened={{ source: row, sequence: index + 1 }} />);
    inspect(row.name);
    if (index < 8) pin();
  }
  expect(region('Pinned revisions').getAllByRole('listitem')).toHaveLength(8);
  expect(region('Recent opens').getAllByRole('listitem')).toHaveLength(12);
  expect(region('Recent opens').queryByText(rows[0].id)).not.toBeInTheDocument();
  expect(region('Source inspection').getByRole('button', { name: 'Pin exact revision' })).toBeDisabled();
  expect(screen.getByText('Pin limit reached (8). Remove a pin first.')).toBeInTheDocument();
  view.rerender(<EnvironmentLibrary sources={rows} onOpen={onOpen} opened={{ source: rows[0], sequence: 1 }} />);
  expect(region('Recent opens').queryByText(rows[0].id)).not.toBeInTheDocument();
  fireEvent.click(region('Pinned revisions').getByRole('button', { name: `Remove pin ${rows[0].id}` }));
  pin();
  expect(region('Pinned revisions').getAllByRole('listitem')).toHaveLength(8);
});

it.each([
  { source: { ...revision(), source_hash: undefined }, sequence: 1 },
  { source: { ...revision(), id: 'editor-revision:latest' }, sequence: 1 },
  { source: revision(), sequence: NaN }, { source: revision(), sequence: -1 },
  { source: revision(), sequence: 1.5 },
])('refuses malformed success confirmation case %#', opened => {
  render(<EnvironmentLibrary sources={[revision()]} onOpen={vi.fn()} opened={opened} />);
  expect(region('Recent opens').getByText('No confirmed opens.')).toBeInTheDocument();
});

it.each(['missing', 'corrupt', 'duplicate', 'unavailable'] as const)('retains an exact frozen pin when its reference becomes %s, without latest fallback', condition => {
  const a = revision();
  const b = revision('b', 'Newer scene');
  const onOpen = vi.fn();
  const view = render(<EnvironmentLibrary sources={[a]} onOpen={onOpen} opened={{ source: a, sequence: 1 }} />);
  inspect(); pin();
  const sources = condition === 'missing' ? [b] : condition === 'corrupt' ? [{ ...a, source_hash: 'c'.repeat(64) }, b] : condition === 'duplicate' ? [a, a, b] : [a, b];
  view.rerender(<EnvironmentLibrary sources={sources} onOpen={onOpen} sourcesStatus={condition === 'unavailable' ? 'unavailable' : 'ready'} />);
  const pins = region('Pinned revisions');
  expect(pins.getByText(a.source_hash!)).toBeInTheDocument();
  expect(pins.queryByText('c'.repeat(64))).not.toBeInTheDocument();
  expect(pins.getByText(condition === 'missing' ? 'Missing exact reference' : condition === 'unavailable' ? 'Reference unavailable' : 'Corrupt or conflicting reference metadata')).toBeInTheDocument();
  fireEvent.click(pins.getByRole('button', { name: `Inspect reference ${a.id}` }));
  expect(region('Source inspection').getByText(a.source_hash!)).toBeInTheDocument();
  expect(region('Source inspection').getByRole('button', { name: 'Open source in editor' })).toBeDisabled();
  expect(onOpen).not.toHaveBeenCalled();
});

it('reopens a retained reference only through explicit Inspect then Open, never selection', () => {
  const a = revision();
  const onOpen = vi.fn();
  render(<EnvironmentLibrary sources={[a]} selectedId={a.id} onOpen={onOpen} opened={{ source: a, sequence: 1 }} />);
  fireEvent.click(region('Recent opens').getByRole('button', { name: `Inspect reference ${a.id}` }));
  expect(onOpen).not.toHaveBeenCalled();
  fireEvent.click(region('Source inspection').getByRole('button', { name: 'Open source in editor' }));
  expect(onOpen).toHaveBeenCalledExactlyOnceWith(a);
});

it('freezes exact metadata comparisons independently of source updates, inspection and in-place caller mutation', () => {
  const a = revision(); const b = revision('b', 'Other scene');
  const originalB = { ...b };
  const onOpen = vi.fn();
  const view = render(<EnvironmentLibrary sources={[a, b]} onOpen={onOpen} />);
  inspect();
  const choose = region('Source inspection').getByRole('combobox', { name: 'Compare with source' });
  fireEvent.change(choose, { target: { value: Array.from((choose as HTMLSelectElement).options).find(option => option.textContent === `Other scene — ${b.id}`)!.value } });
  fireEvent.click(region('Source inspection').getByRole('button', { name: 'Freeze metadata comparison' }));
  const table = screen.getByRole('table', { name: 'Frozen source metadata comparison' });
  const sourceRow = within(table).getByRole('row', { name: `Source hash ${a.source_hash} ${b.source_hash} Different` });
  expect(sourceRow).toBeInTheDocument();
  expect(within(table).getByRole('row', { name: `Canonical hash ${a.canonical_hash} ${b.canonical_hash} Same` })).toBeInTheDocument();
  expect(screen.getByText(/Metadata only.*not a raw YAML\/content diff/)).toBeInTheDocument();
  b.name = 'Retargeted'; b.source_hash = 'c'.repeat(64);
  view.rerender(<EnvironmentLibrary sources={[a, b]} onOpen={onOpen} selectedId={b.id} />);
  inspect('Retargeted');
  expect(within(table).getByText(originalB.name)).toBeInTheDocument();
  expect(within(table).getByText(originalB.source_hash!)).toBeInTheDocument();
  expect(within(table).queryByText('c'.repeat(64))).not.toBeInTheDocument();
  expect(region('Frozen comparison').getByText('B: Corrupt or conflicting reference metadata')).toBeInTheDocument();
  expect(onOpen).not.toHaveBeenCalled();
});

it('invalidates dependent comparison choices when inspection changes or a same-ID target changes hash', () => {
  const a = revision(); const b = revision('b', 'Other scene');
  const view = render(<EnvironmentLibrary sources={[a, b]} onOpen={vi.fn()} />);
  inspect();
  const choose = region('Source inspection').getByRole('combobox', { name: 'Compare with source' }) as HTMLSelectElement;
  fireEvent.change(choose, { target: { value: choose.options[1].value } });
  expect(region('Source inspection').getByRole('button', { name: 'Freeze metadata comparison' })).toBeEnabled();
  view.rerender(<EnvironmentLibrary sources={[a, { ...b, source_hash: 'c'.repeat(64) }]} onOpen={vi.fn()} />);
  expect(choose).toHaveValue('');
  expect(region('Source inspection').getByRole('button', { name: 'Freeze metadata comparison' })).toBeDisabled();
  inspect('Other scene');
  expect(region('Source inspection').getByRole('combobox', { name: 'Compare with source' })).toHaveValue('');
});

it('marks absent comparison hashes unknown instead of claiming missing values match', () => {
  render(<EnvironmentLibrary sources={[file, { ...file, id: 'second', name: 'Second file' }]} onOpen={vi.fn()} />);
  inspect(file.name);
  const choose = region('Source inspection').getByRole('combobox', { name: 'Compare with source' }) as HTMLSelectElement;
  fireEvent.change(choose, { target: { value: choose.options[1].value } });
  fireEvent.click(region('Source inspection').getByRole('button', { name: 'Freeze metadata comparison' }));
  expect(within(screen.getByRole('table', { name: 'Frozen source metadata comparison' })).getByRole('row', { name: 'Source hash Not provided Not provided Unknown' })).toBeInTheDocument();
});

const storedRef = (source = revision()) => ({ id: source.id, kind: source.kind, revision_id: source.revision_id, source_hash: source.source_hash, canonical_hash: source.canonical_hash });

it('persists only bounded versioned public references and restores without selecting or opening', async () => {
  const storage = transactionalPreferences();
  const a = revision('a', 'PRIVATE NAME NOT PERSISTED');
  const onOpen = vi.fn();
  const view = render(<EnvironmentLibrary sources={[a]} onOpen={onOpen} opened={{ source: a, sequence: 1 }} />);
  await settled();
  inspect(a.name); pin(); await settled();
  const raw = JSON.stringify(storage.preferences);
  expect(localStorage.getItem(LIBRARY_PREFERENCES_KEY)).toBeNull();
  expect(JSON.parse(raw)).toEqual({ version: 1, pins: [storedRef(a)], recents: [storedRef(a)] });
  expect(raw).not.toContain(a.name);
  expect(raw).not.toContain('editor revision');
  expect(raw.length).toBeLessThanOrEqual(16384);
  view.unmount();
  render(<EnvironmentLibrary sources={[]} selectedId={a.id} onOpen={onOpen} />);
  await settled();
  expect(region('Pinned revisions').getByText(a.id)).toBeInTheDocument();
  expect(region('Pinned revisions').getByText('Missing exact reference')).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Source inspection' })).not.toBeInTheDocument();
  expect(onOpen).not.toHaveBeenCalled();
});

it('does not treat restored local recents as fresh verification for pinning', async () => {
  transactionalPreferences();
  localStorage.setItem(LIBRARY_PREFERENCES_KEY, JSON.stringify({ version: 1, pins: [], recents: [storedRef()] }));
  render(<EnvironmentLibrary sources={[revision()]} onOpen={vi.fn()} />);
  await settled();
  expect(region('Recent opens').getAllByRole('listitem')).toHaveLength(1);
  inspect();
  expect(region('Source inspection').getByRole('button', { name: 'Pin exact revision' })).toBeDisabled();
  expect(screen.getByText(/Local references are not proof of a current successful open/)).toBeInTheDocument();
});

it.each([
  'not-json', '', 'x'.repeat(16385), JSON.stringify({ version: 2, pins: [], recents: [] }),
  JSON.stringify({ version: 1, pins: [{ ...storedRef(), id: 'editor-revision:latest' }], recents: [] }),
  JSON.stringify({ version: 1, pins: [storedRef(), storedRef()], recents: [] }),
  JSON.stringify({ version: 1, pins: [], recents: [{ ...storedRef(), source_hash: 'bad' }] }),
  JSON.stringify({ version: 1, pins: [{ ...storedRef(), source: 'private source' }], recents: [] }),
  JSON.stringify({ version: 1, pins: Array.from({ length: 9 }, (_, i) => storedRef(revision(i.toString(16)))), recents: [] }),
  JSON.stringify({ version: 1, pins: [], recents: Array.from({ length: 13 }, (_, i) => storedRef(revision(i.toString(16)))) }),
])('ignores corrupt, unsupported or oversized preference case %# without adopting latest or overwriting bytes on mount', async raw => {
  transactionalPreferences();
  localStorage.setItem(LIBRARY_PREFERENCES_KEY, raw);
  const onOpen = vi.fn();
  render(<EnvironmentLibrary sources={[revision()]} onOpen={onOpen} />);
  await settled();
  expect(screen.getByText('Stored Library references are malformed or unsupported; preserved. Using memory for this mount.')).toBeInTheDocument();
  expect(region('Pinned revisions').queryAllByRole('listitem')).toHaveLength(0);
  expect(region('Recent opens').queryAllByRole('listitem')).toHaveLength(0);
  expect(localStorage.getItem(LIBRARY_PREFERENCES_KEY)).toBe(raw);
  expect(onOpen).not.toHaveBeenCalled();
});

it.each(['quota', 'security', 'readback'] as const)('keeps a bounded memory fallback on injected adapter %s errors, without touching draft or retry records', async failure => {
  localStorage.setItem('draft-record', 'DRAFT'); localStorage.setItem('retry-record', 'RETRY');
  const set = vi.spyOn(Storage.prototype, 'setItem');
  const remove = vi.spyOn(Storage.prototype, 'removeItem');
  let transactions = 0; let failures = 0;
  let stored: unknown;
  vi.spyOn(nativePreferences, 'createNativeLibraryAdapter').mockReturnValue({
    open() {if (failure === 'security') {failures++; throw new DOMException('PRIVATE', 'SecurityError');} return Promise.resolve();},
    close() {},
    transaction(_mode, mutate) {
      transactions++;
      if (transactions > 1) {failures++; return Promise.reject(new DOMException('PRIVATE', failure === 'quota' ? 'QuotaExceededError' : 'UnknownError'));}
      stored = mutate(stored); return Promise.resolve(stored);
    },
  });
  const rows = Array.from({ length: 14 }, (_, i) => revision(i.toString(16), `Scene ${i}`));
  const onOpen = vi.fn();
  const view = render(<EnvironmentLibrary sources={rows} onOpen={onOpen} />);
  await settled();
  for (const [index, source] of rows.entries()) {
    view.rerender(<EnvironmentLibrary sources={rows} onOpen={onOpen} opened={{ source, sequence: index + 1 }} />);
    await settled();
    if (index === 0) { inspect(source.name); pin(); await settled(); }
  }
  expect(failures).toBe(1);
  expect(transactions).toBe(failure === 'security' ? 0 : 2);
  expect(screen.getByText('Library preferences unavailable; using memory for this mount.')).toBeInTheDocument();
  expect(region('Recent opens').getAllByRole('listitem')).toHaveLength(12);
  expect(region('Pinned revisions').getAllByRole('listitem')).toHaveLength(1);
  expect(localStorage.getItem('draft-record')).toBe('DRAFT');
  expect(localStorage.getItem('retry-record')).toBe('RETRY');
  expect(set).not.toHaveBeenCalled(); expect(remove).not.toHaveBeenCalled();
  expect(screen.queryByText(/PRIVATE/)).not.toBeInTheDocument();
});

it('provides labelled controlled panels with explicit focus and retains comparison across collapse', () => {
  const a = revision(); const b = revision('b', 'Other scene');
  const onOpen = vi.fn();
  render(<EnvironmentLibrary sources={[a, b]} onOpen={onOpen} />);
  inspect();
  expect(region('Source inspection').getByRole('heading', { name: a.name })).toHaveFocus();
  const choose = region('Source inspection').getByRole('combobox', { name: 'Compare with source' }) as HTMLSelectElement;
  fireEvent.change(choose, { target: { value: choose.options[1].value } });
  fireEvent.click(region('Source inspection').getByRole('button', { name: 'Freeze metadata comparison' }));
  const table = screen.getByRole('table', { name: 'Frozen source metadata comparison' });
  const scroll = screen.getByRole('region', { name: 'Comparison table scroll area' });
  expect(scroll).toHaveAttribute('tabindex', '0');
  const collapse = screen.getByRole('button', { name: 'Collapse inspection' });
  expect(collapse).toHaveAttribute('aria-expanded', 'true');
  expect(document.getElementById(collapse.getAttribute('aria-controls')!)).toBe(screen.getByRole('region', { name: 'Source inspection' }));
  fireEvent.click(collapse);
  expect(screen.queryByRole('region', { name: 'Source inspection' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Expand inspection' })).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(screen.getByRole('button', { name: 'Expand inspection' }));
  expect(region('Source inspection').getByRole('combobox', { name: 'Compare with source' })).toBe(choose);
  fireEvent.click(screen.getByRole('button', { name: 'Collapse comparison' }));
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Expand comparison' }));
  expect(screen.getByRole('table', { name: 'Frozen source metadata comparison' })).toBe(table);
  fireEvent.click(screen.getByRole('button', { name: 'Clear comparison' }));
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  for (const button of screen.getAllByRole('button')) expect(button).toHaveAttribute('type', 'button');
  expect(onOpen).not.toHaveBeenCalled();
});

it.each(['inspection', 'comparison', 'search'])('keeps source ID %s separate from accessibility targets', id => {
  const source = { ...file, id, name: 'Collision source' };
  const other = { ...file, id: 'other-source', name: 'Other source' };
  const onOpen = vi.fn();
  const view = render(<EnvironmentLibrary sources={[source, other]} onOpen={onOpen} />);
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Collision source' }));
  const choose = region('Source inspection').getByRole('combobox', { name: 'Compare with source' }) as HTMLSelectElement;
  fireEvent.change(choose, { target: { value: choose.options[1].value } });
  fireEvent.click(region('Source inspection').getByRole('button', { name: 'Freeze metadata comparison' }));
  const ids = Array.from(view.container.querySelectorAll('[id]'), element => element.id);
  expect(new Set(ids).size).toBe(ids.length);
  for (const article of region('Library sources').getAllByRole('article')) {
    const button = within(article).getByRole('button');
    const description = document.getElementById(button.getAttribute('aria-describedby')!);
    expect(description?.tagName).toBe('CODE');
    expect(article).toContainElement(description);
  }
  const collapse = screen.getByRole('button', { name: 'Collapse inspection' });
  expect(document.getElementById(collapse.getAttribute('aria-controls')!)).toBe(screen.getByRole('region', { name: 'Source inspection' }));
  expect(document.getElementById(screen.getByRole('button', { name: 'Collapse comparison' }).getAttribute('aria-controls')!)?.tagName).toBe('DIV');
  expect(screen.getByRole('searchbox', { name: 'Search library' })).toBeInTheDocument();
  expect(onOpen).not.toHaveBeenCalled();
});

it('paginates without selecting, displays exact IDs and labels empty search results', () => {
  const rows = Array.from({ length: 30 }, (_, i) => ({ ...file, id: `file-${i}`, name: `Scene ${i}` }));
  const onOpen = vi.fn();
  render(<EnvironmentLibrary sources={rows} onOpen={onOpen} />);
  expect(region('Library sources').getAllByRole('article')).toHaveLength(24);
  fireEvent.click(screen.getByRole('button', { name: 'Next library page' }));
  expect(region('Library sources').getAllByRole('article')).toHaveLength(6);
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search library' }), { target: { value: 'Scene 0' } });
  expect(region('Library sources').getByText('file-0')).toBeInTheDocument();
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search library' }), { target: { value: 'no match' } });
  expect(screen.getByText('No matching sources.')).toBeInTheDocument();
  expect(onOpen).not.toHaveBeenCalled();
});

it('scopes responsive theme styles and imports no runtime, providers, fixtures or API clients', () => {
  const css = readFileSync('src/environment-library.css', 'utf8');
  const source = readFileSync('src/environment-library.tsx', 'utf8');
  expect(source).toContain("import './environment-library.css'");
  expect(Array.from(source.matchAll(/from ['"]([^'"]+)['"]/g), match => match[1])).toEqual(['react', './environment-library-contract', './library-preferences', './environment-library-contract']);
  expect(source).not.toMatch(/fetch\(|useQuery\(|useRuntime\(|ApiClient|SessionProvider|\.\/preview\//);
  const style = document.createElement('style'); style.textContent = css; document.head.append(style);
  try {
    const rules = Array.from(style.sheet!.cssRules);
    const regular = rules.filter(rule => rule.type === CSSRule.STYLE_RULE) as CSSStyleRule[];
    const media = rules.filter(rule => rule.type === CSSRule.MEDIA_RULE) as CSSMediaRule[];
    expect(media.map(rule => rule.conditionText)).toEqual(expect.arrayContaining(['(max-width: 1100px)', '(max-width: 760px)']));
    for (const rule of [...regular, ...media.flatMap(rule => Array.from(rule.cssRules) as CSSStyleRule[])]) expect(rule.selectorText).toContain('.environment-library');
    expect(css).toContain('var(--surface)'); expect(css).toContain('var(--text)');
    expect(css).toContain('min-width: 0'); expect(css).toContain('overflow-x: auto');
    expect(css).toContain(':focus-visible'); expect(css).not.toMatch(/https?:|@import|word-break:\s*break-all/);
  } finally { style.remove(); }
});

it('handles a localStorage property SecurityError and synchronous parent failure without leaking either error', () => {
  vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => { throw new DOMException('PRIVATE STORAGE', 'SecurityError'); });
  render(<EnvironmentLibrary sources={[revision()]} onOpen={() => { throw new Error('PRIVATE OPEN'); }} />);
  inspect();
  fireEvent.click(region('Source inspection').getByRole('button', { name: 'Open source in editor' }));
  expect(screen.getByText('Library preferences unavailable; using memory for this mount.')).toBeInTheDocument();
  expect(screen.getByText('Open request failed. No recent was added.')).toBeInTheDocument();
  expect(region('Recent opens').getByText('No confirmed opens.')).toBeInTheDocument();
  expect(screen.queryByText(/PRIVATE/)).not.toBeInTheDocument();
});

it('ignores retired request failures and never treats a fulfilled Open promise as confirmation', async () => {
  let reject!: (error: Error) => void;
  const onOpen = vi.fn().mockImplementationOnce(() => new Promise<void>((_, fail) => { reject = fail; })).mockResolvedValueOnce({ verified: true });
  render(<EnvironmentLibrary sources={[revision(), file]} onOpen={onOpen} />);
  inspect(); fireEvent.click(region('Source inspection').getByRole('button', { name: 'Open source in editor' }));
  inspect(file.name);
  await act(async () => reject(new Error('retired error')));
  expect(screen.queryByText('Open request failed. No recent was added.')).not.toBeInTheDocument();
  await act(async () => fireEvent.click(region('Source inspection').getByRole('button', { name: 'Open source in editor' })));
  expect(region('Recent opens').getByText('No confirmed opens.')).toBeInTheDocument();
});

it('deduplicates StrictMode success effects and detaches Open payloads from frozen inspection', () => {
  const a = revision();
  const onOpen = vi.fn((source: SourceSummary) => { source.source_hash = 'b'.repeat(64); });
  render(<StrictMode><EnvironmentLibrary sources={[a]} opened={{ source: a, sequence: 1 }} onOpen={onOpen} /></StrictMode>);
  expect(region('Recent opens').getAllByRole('listitem')).toHaveLength(1);
  inspect(); fireEvent.click(region('Source inspection').getByRole('button', { name: 'Open source in editor' }));
  expect(region('Source inspection').getByText('a'.repeat(64))).toBeInTheDocument();
  expect(a.source_hash).toBe('a'.repeat(64));
});

it('deduplicates repeated pin actions before React commits instead of corrupting local preferences', async () => {
  const storage = transactionalPreferences();
  const a = revision();
  render(<EnvironmentLibrary sources={[a]} opened={{ source: a, sequence: 1 }} onOpen={vi.fn()} />);
  inspect();
  await settled();
  const button = region('Source inspection').getByRole('button', { name: 'Pin exact revision' });
  await act(async () => { button.click(); button.click(); });
  await settled();
  expect(region('Pinned revisions').getAllByRole('listitem')).toHaveLength(1);
  expect(storage.preferences?.pins).toEqual([storedRef(a)]);
  expect(localStorage.getItem(LIBRARY_PREFERENCES_KEY)).toBeNull();
  expect(screen.queryByText('Library preferences unavailable; using memory for this mount.')).not.toBeInTheDocument();
});

it('distinguishes same-name revision options and card descriptions with literal exact IDs', () => {
  const a = revision(); const b = revision('b'); const c = revision('c');
  render(<EnvironmentLibrary sources={[a, b, c]} onOpen={vi.fn()} />);
  const cards = region('Library sources').getAllByRole('article');
  for (const [index, row] of [a, b, c].entries()) {
    const button = within(cards[index]).getByRole('button', { name: 'Inspect Saved scene' });
    expect(button).toHaveAccessibleDescription(row.id);
  }
  fireEvent.click(within(cards[0]).getByRole('button', { name: 'Inspect Saved scene' }));
  expect(region('Source inspection').getByRole('option', { name: `Saved scene — ${b.id}` })).toBeInTheDocument();
  expect(region('Source inspection').getByRole('option', { name: `Saved scene — ${c.id}` })).toBeInTheDocument();
});
