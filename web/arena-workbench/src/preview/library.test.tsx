import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LibraryPanel, EnvironmentPicker } from './library';

import { exampleFamilies } from './library-data';
import type { PreviewSelection } from './types';

const tabletop = exampleFamilies.find((family) => family.id === 'example-c1-g1-tabletop')!;
const inspectTabletop = () => fireEvent.click(screen.getByRole('button', { name: 'Inspect C1 · G1 tabletop' }));

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('toggles an exact inspected pin without treating example activity markers as pins', () => {
  const onOpen = vi.fn();
  render(<LibraryPanel onOpen={onOpen} />);
  const pins = screen.getByRole('region', { name: 'Local pins' });
  expect(within(pins).getByText('No local pins.')).toBeInTheDocument();
  inspectTabletop();
  fireEvent.change(screen.getByRole('combobox', { name: 'Inspect version' }), { target: { value: tabletop.versions[9].versionId } });
  fireEvent.click(screen.getByRole('button', { name: 'Pin inspected version' }));
  expect(within(pins).getByText(tabletop.versions[9].source)).toBeInTheDocument();
  expect(within(pins).getByText(tabletop.versions[9].versionId)).toBeInTheDocument();
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search example library' }), { target: { value: 'no-match' } });
  fireEvent.click(within(pins).getByRole('button', { name: 'Inspect pinned version' }));
  expect(screen.getByRole('combobox', { name: 'Inspect version' })).toHaveValue(tabletop.versions[9].versionId);
  fireEvent.click(screen.getByRole('button', { name: 'Unpin inspected version' }));
  expect(within(pins).getByText('No local pins.')).toBeInTheDocument();
  expect(onOpen).not.toHaveBeenCalled();
});

it('records only confirmed opened changes as deduplicated exact recents, never cancelled requests', () => {
  const onOpen = vi.fn();
  const view = render(<LibraryPanel onOpen={onOpen} opened={null} />);
  const recents = screen.getByRole('region', { name: 'Recent opens' });
  inspectTabletop();
  fireEvent.click(screen.getByRole('button', { name: 'Open environment' }));
  expect(onOpen).toHaveBeenCalledWith(tabletop.versions[0]);
  expect(within(recents).getByText('No confirmed opens yet.')).toBeInTheDocument();
  view.rerender(<LibraryPanel onOpen={onOpen} opened={tabletop.versions[0]} />);
  view.rerender(<LibraryPanel onOpen={onOpen} opened={tabletop.versions[1]} />);
  view.rerender(<LibraryPanel onOpen={onOpen} opened={{ ...tabletop.versions[0] }} />);
  expect(within(recents).getAllByRole('article')).toHaveLength(2);
  expect(within(recents).getAllByRole('article')[0]).toHaveTextContent(tabletop.versions[0].source);
  view.rerender(<LibraryPanel onOpen={onOpen} opened={{ ...tabletop.versions[0] }} />);
  fireEvent.click(within(recents).getAllByRole('button', { name: 'Open recent environment' })[1]);
  expect(onOpen).toHaveBeenLastCalledWith(tabletop.versions[1]);
  expect(within(recents).getAllByRole('article')[0]).toHaveTextContent(tabletop.versions[0].source);
  view.rerender(<LibraryPanel onOpen={onOpen} opened={null} />);
  expect(within(recents).getAllByRole('article')).toHaveLength(2);
});

it('inspects supplied local versions without mutation, name merging, storage or network and preserves known kinds', () => {
  const fetch = vi.fn(() => { throw new Error('No API'); });
  vi.stubGlobal('fetch', fetch);
  const get = vi.spyOn(Storage.prototype, 'getItem');
  const set = vi.spyOn(Storage.prototype, 'setItem');
  const local: PreviewSelection = Object.freeze({ ...tabletop.versions[0], familyId: 'example-local-saved', versionId: 'example-local-v1', source: 'example-local-memory', yaml: '# saved locally\n' });
  const policy = Object.freeze({ ...local, familyId: 'example-policy', versionId: 'example-local-policy', source: 'local-policy-example' });
  const supplied = Object.freeze([local, policy]);
  const before = JSON.stringify([exampleFamilies, supplied]);
  const onOpen = vi.fn();
  const view = render(<LibraryPanel onOpen={onOpen} localVersions={supplied} opened={local} />);
  fireEvent.click(within(screen.getByRole('region', { name: 'Recent opens' })).getByRole('button', { name: 'Inspect recent version' }));
  const inspector = screen.getByRole('region', { name: 'Version inspector' });
  expect(within(inspector).getByText(local.familyId)).toBeInTheDocument();
  expect(within(inspector).getByText(local.source)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Pin inspected version' }));
  fireEvent.click(within(screen.getByRole('region', { name: 'Local pins' })).getByRole('button', { name: 'Open pinned environment' }));
  expect(onOpen).toHaveBeenCalledWith(expect.objectContaining(local));
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Example policy profile' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Inspect version' }), { target: { value: policy.versionId } });
  expect(screen.queryByRole('button', { name: 'Open environment' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Pin inspected version' }));
  expect(within(screen.getByRole('region', { name: 'Local pins' })).getAllByRole('button', { name: 'Open pinned environment' })).toHaveLength(1);
  view.rerender(<LibraryPanel onOpen={onOpen} localVersions={[]} opened={local} />);
  fireEvent.click(within(screen.getByRole('region', { name: 'Local pins' })).getAllByRole('button', { name: 'Inspect pinned version' })[0]);
  expect(screen.getByRole('region', { name: 'Version inspector' })).toHaveTextContent(local.source);
  expect(JSON.stringify([exampleFamilies, supplied])).toBe(before);
  expect(fetch).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled(); expect(set).not.toHaveBeenCalled();
});

it('freezes explicitly selected same-family YAML and provenance until comparison is cleared', () => {
  render(<LibraryPanel onOpen={vi.fn()} />);
  inspectTabletop();
  fireEvent.change(screen.getByRole('combobox', { name: 'Inspect version' }), { target: { value: tabletop.versions[1].versionId } });
  const comparison = screen.getByRole('combobox', { name: 'Compare with version' });
  expect(comparison).toHaveValue('');
  expect(screen.getByRole('button', { name: 'Freeze version comparison' })).toBeDisabled();
  fireEvent.change(comparison, { target: { value: tabletop.versions[9].versionId } });
  fireEvent.click(screen.getByRole('button', { name: 'Freeze version comparison' }));
  const review = screen.getByRole('region', { name: 'Frozen version comparison' });
  const before = within(review).getByRole('region', { name: 'Before version' });
  const after = within(review).getByRole('region', { name: 'After version' });
  expect(before.querySelector('pre')?.textContent).toBe(tabletop.versions[1].yaml);
  expect(after.querySelector('pre')?.textContent).toBe(tabletop.versions[9].yaml);
  expect(before).toHaveTextContent(tabletop.versions[1].source);
  expect(after).toHaveTextContent(tabletop.versions[9].parent!);
  fireEvent.change(comparison, { target: { value: tabletop.versions[10].versionId } });
  expect(screen.getByText('Current choices differ from the frozen comparison. Clear it before reviewing another pair.')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Freeze version comparison' })).toBeDisabled();
  expect(after.querySelector('pre')?.textContent).toBe(tabletop.versions[9].yaml);
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search example library' }), { target: { value: 'no-match' } });
  expect(screen.getByRole('region', { name: 'Frozen version comparison' })).toBe(review);
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search example library' }), { target: { value: '' } });
  expect(screen.getByRole('combobox', { name: 'Compare with version' })).toHaveValue(tabletop.versions[10].versionId);
  fireEvent.click(screen.getByRole('button', { name: 'Clear frozen comparison' }));
  fireEvent.click(screen.getByRole('button', { name: 'Freeze version comparison' }));
  expect(within(screen.getByRole('region', { name: 'After version' })).getByText(tabletop.versions[10].source)).toBeInTheDocument();
});

it('reconciles primary/comparison collisions before freezing and never revives a hidden stale choice', () => {
  render(<LibraryPanel onOpen={vi.fn()} />);
  inspectTabletop();
  const primary = screen.getByRole('combobox', { name: 'Inspect version' });
  const comparison = screen.getByRole('combobox', { name: 'Compare with version' });
  fireEvent.change(comparison, { target: { value: tabletop.versions[1].versionId } });
  fireEvent.change(primary, { target: { value: tabletop.versions[1].versionId } });
  expect(comparison).toHaveValue('');
  expect(screen.getByRole('button', { name: 'Freeze version comparison' })).toBeDisabled();
  fireEvent.change(primary, { target: { value: tabletop.versions[0].versionId } });
  expect(comparison).toHaveValue('');
  fireEvent.change(comparison, { target: { value: tabletop.versions[1].versionId } });
  fireEvent.click(screen.getByRole('button', { name: 'Freeze version comparison' }));
  const prior = screen.getByRole('region', { name: 'After version' }).textContent;
  fireEvent.change(primary, { target: { value: tabletop.versions[1].versionId } });
  expect(comparison).toHaveValue('');
  expect(screen.getByRole('region', { name: 'After version' }).textContent).toBe(prior);
  fireEvent.click(screen.getByRole('button', { name: 'Inspect G1 · incompatible reach scenario' }));
  fireEvent.click(screen.getByRole('button', { name: 'Clear frozen comparison' }));
  expect(screen.getByRole('button', { name: 'Freeze version comparison' })).toBeDisabled();
  inspectTabletop();
  expect(screen.getByRole('combobox', { name: 'Compare with version' })).toHaveValue('');
});

it('keeps captured pins and frozen YAML unchanged when supplied records change under the same identity', () => {
  const local: PreviewSelection = { ...tabletop.versions[0], versionId: 'example-local-v20', version: 20, source: 'local-before.yaml', yaml: '# original local\n' };
  const onOpen = vi.fn();
  const view = render(<LibraryPanel onOpen={onOpen} localVersions={[local]} />);
  inspectTabletop();
  fireEvent.change(screen.getByRole('combobox', { name: 'Inspect version' }), { target: { value: local.versionId } });
  fireEvent.click(screen.getByRole('button', { name: 'Pin inspected version' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Compare with version' }), { target: { value: tabletop.versions[0].versionId } });
  fireEvent.click(screen.getByRole('button', { name: 'Freeze version comparison' }));
  expect(screen.getByText('Current choices match the frozen comparison.')).toBeInTheDocument();
  local.yaml = '# changed local\n'; local.source = 'local-after.yaml';
  view.rerender(<LibraryPanel onOpen={onOpen} localVersions={[local]} />);
  expect(screen.getByRole('region', { name: 'Before version' }).querySelector('pre')?.textContent).toBe('# original local\n');
  expect(screen.getByText('Current choices differ from the frozen comparison. Clear it before reviewing another pair.')).toBeInTheDocument();
  const pins = screen.getByRole('region', { name: 'Local pins' });
  expect(within(pins).getByText('local-before.yaml')).toBeInTheDocument();
  fireEvent.click(within(pins).getByRole('button', { name: 'Inspect pinned version' }));
  expect(screen.getByRole('region', { name: 'Version inspector' })).toHaveTextContent('local-before.yaml');
  fireEvent.click(screen.getByRole('button', { name: 'Open environment' }));
  expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ yaml: '# original local\n', source: 'local-before.yaml' }));
  fireEvent.click(screen.getByRole('button', { name: 'Inspect current supplied version' }));
  expect(screen.getByRole('region', { name: 'Version inspector' })).toHaveTextContent('local-after.yaml');
  expect(screen.getByRole('region', { name: 'Before version' }).querySelector('pre')?.textContent).toBe('# original local\n');
});

it('never reuses a comparison choice across families with colliding version IDs', () => {
  const localA = { ...tabletop.versions[0], familyId: 'example-local-a', familyName: 'Local A', versionId: 'shared-v1' };
  const localB = { ...localA, familyId: 'example-local-b', familyName: 'Local B' };
  const versions = [localA, { ...localA, versionId: 'shared-v2', version: 2 }, localB, { ...localB, versionId: 'shared-v2', version: 2 }];
  render(<LibraryPanel onOpen={vi.fn()} localVersions={versions} />);
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Local A' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Compare with version' }), { target: { value: 'shared-v2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Local B' }));
  expect(screen.getByRole('combobox', { name: 'Compare with version' })).toHaveValue('');
  expect(screen.getByRole('button', { name: 'Freeze version comparison' })).toBeDisabled();
});

it.each(['example-policy', 'example-experiment'])('blocks locally named non-environment picker selections for %s', (familyId) => {
  const onOpen = vi.fn();
  render(<EnvironmentPicker selection={{ ...tabletop.versions[0], familyId, versionId: 'example-local-disguised' }} onOpen={onOpen} onBrowse={vi.fn()} />);
  expect(screen.getByRole('button', { name: 'Open selected version' })).toBeDisabled();
  expect(onOpen).not.toHaveBeenCalled();
});

it('discloses unavailable local parent metadata without mistaking object field order for a source change', () => {
  const { parent: _parent, status: _status, ...base } = tabletop.versions[0];
  const local: PreviewSelection = { ...base, versionId: 'example-local-no-parent', version: 20 };
  const view = render(<LibraryPanel onOpen={vi.fn()} localVersions={[local]} />);
  inspectTabletop();
  fireEvent.change(screen.getByRole('combobox', { name: 'Inspect version' }), { target: { value: local.versionId } });
  expect(screen.getByRole('region', { name: 'Version inspector' })).toHaveTextContent('Unavailable · no parent metadata supplied');
  fireEvent.change(screen.getByRole('combobox', { name: 'Compare with version' }), { target: { value: tabletop.versions[0].versionId } });
  fireEvent.click(screen.getByRole('button', { name: 'Freeze version comparison' }));
  const { yaml, ...rest } = local;
  view.rerender(<LibraryPanel onOpen={vi.fn()} localVersions={[{ yaml, ...rest }]} />);
  expect(screen.getByText('Current choices match the frozen comparison.')).toBeInTheDocument();
});

it('deduplicates recents by family plus version, including same-version-ID families and non-environment cards', () => {
  const onOpen = vi.fn();
  const first = { ...tabletop.versions[0], familyId: 'example-local-a', versionId: 'shared-version' };
  const second = { ...first, familyId: 'example-local-b', source: 'second-family.yaml' };
  const view = render(<LibraryPanel onOpen={onOpen} opened={first} />);
  view.rerender(<LibraryPanel onOpen={onOpen} opened={second} />);
  view.rerender(<LibraryPanel onOpen={onOpen} opened={first} />);
  const recents = screen.getByRole('region', { name: 'Recent opens' });
  expect(within(recents).getAllByRole('article')).toHaveLength(2);
  for (const id of ['example-policy', 'example-experiment', 'example-unclassified']) {
    const entry = exampleFamilies.find((family) => family.id === id)!.versions[0];
    view.rerender(<LibraryPanel onOpen={onOpen} opened={entry} />);
    const card = within(recents).getAllByRole('article')[0];
    expect(within(card).queryByRole('button', { name: 'Open recent environment' })).not.toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', { name: 'Inspect recent version' }));
    expect(screen.queryByRole('button', { name: 'Open environment' })).not.toBeInTheDocument();
  }
  expect(onOpen).not.toHaveBeenCalled();
});

it('retires a removed comparison candidate without changing the frozen review or reviving it on return', () => {
  const local = Object.freeze({ ...tabletop.versions[0], versionId: 'example-local-removed', version: 20, yaml: '# retained review\n' });
  const supplied = Object.freeze([local]);
  const before = JSON.stringify(supplied);
  const view = render(<LibraryPanel onOpen={vi.fn()} localVersions={supplied} />);
  inspectTabletop();
  fireEvent.change(screen.getByRole('combobox', { name: 'Compare with version' }), { target: { value: local.versionId } });
  fireEvent.click(screen.getByRole('button', { name: 'Freeze version comparison' }));
  view.rerender(<LibraryPanel onOpen={vi.fn()} localVersions={[]} />);
  expect(screen.getByRole('combobox', { name: 'Compare with version' })).toHaveValue('');
  expect(screen.getByRole('region', { name: 'After version' }).querySelector('pre')?.textContent).toBe(local.yaml);
  expect(screen.getByText('Current choices differ from the frozen comparison. Clear it before reviewing another pair.')).toBeInTheDocument();
  view.rerender(<LibraryPanel onOpen={vi.fn()} localVersions={supplied} />);
  expect(screen.getByRole('combobox', { name: 'Compare with version' })).toHaveValue('');
  expect(JSON.stringify(supplied)).toBe(before);
});

describe('preview document library', () => {
  it('clears a staged family safely when returning to the picker placeholder', () => {
    const onOpen = vi.fn();
    render(<EnvironmentPicker selection={null} onOpen={onOpen} onBrowse={vi.fn()} />);
    const family = screen.getByRole('combobox', { name: 'Environment family' });
    fireEvent.change(family, { target: { value: 'example-c1-g1-tabletop' } });
    fireEvent.change(family, { target: { value: '' } });
    expect(family).toHaveValue('');
    expect(screen.getByRole('combobox', { name: 'Environment version' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Open selected version' })).toBeDisabled();
    expect(onOpen).not.toHaveBeenCalled();
  });
  it('shows an explicitly supplied local example as its own exact draft, never merging by family label', () => {
    const local = { familyId: 'example-local-candidate', familyName: 'C1 · G1 tabletop', versionId: 'example-local-candidate-v7', version: 7, source: 'example-local-memory', yaml: '# example local draft\n', robot: 'G1', hand: 'Left' };
    const onOpen = vi.fn();
    const onBrowse = vi.fn();
    const view = render(<EnvironmentPicker selection={local} onOpen={onOpen} onBrowse={onBrowse} />);
    const families = screen.getByRole('combobox', { name: 'Environment family' });
    expect(families).toHaveValue(local.familyId);
    expect(within(families).getAllByRole('option')).toHaveLength(exampleFamilies.filter((family) => family.kind === 'environment').length + 2);
    expect(screen.getByRole('option', { name: 'C1 · G1 tabletop · local draft example' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Environment version' })).toHaveValue(local.versionId);
    expect(within(screen.getByRole('combobox', { name: 'Environment version' })).getAllByRole('option')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Open selected version' }));
    expect(onOpen).toHaveBeenLastCalledWith(local);
    fireEvent.change(families, { target: { value: 'example-g1-reach' } });
    expect(screen.getByRole('combobox', { name: 'Environment version' })).toHaveValue('example-g1-reach-v1');
    view.rerender(<EnvironmentPicker selection={{ ...local, versionId: 'example-local-candidate-v8', version: 8 }} onOpen={onOpen} onBrowse={onBrowse} />);
    expect(screen.getByRole('combobox', { name: 'Environment version' })).toHaveValue('example-local-candidate-v8');
    fireEvent.click(screen.getByRole('button', { name: 'Browse Library' }));
    expect(onBrowse).toHaveBeenCalledOnce();
  });
  it('reviews only approved example import metadata without reading or uploading files', () => {
    const onOpen = vi.fn();
    const { container } = render(<LibraryPanel onOpen={onOpen} />);
    fireEvent.click(screen.getByText('Approved import review · preview only'));
    fireEvent.change(screen.getByRole('combobox', { name: 'Approved example source' }), { target: { value: 'example-policy' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Expected root kind' }), { target: { value: 'environment' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review example import' }));
    expect(screen.getByRole('status')).toHaveTextContent('Kind mismatch: expected environment, example declares policy. Import blocked.');
    fireEvent.change(screen.getByRole('combobox', { name: 'Expected root kind' }), { target: { value: 'policy' } });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Review example import' }));
    expect(screen.getByRole('status')).toHaveTextContent('Review only: policy root matches. Nothing imported; identity and include validation require the future adapter.');
    expect(screen.getByText('Raw / canonical identity')).toBeInTheDocument();
    expect(screen.getByText('Frozen includes')).toBeInTheDocument();
    expect(container.querySelector('input[type="file"]')).toBeNull();
    expect(onOpen).not.toHaveBeenCalled();
  });
  it('does not leave a hidden environment open action behind a policy-only filter', () => {
    const onOpen = vi.fn();
    render(<LibraryPanel onOpen={onOpen} />);
    fireEvent.click(screen.getByRole('button', { name: 'Inspect C1 · G1 tabletop' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Document kind' }), { target: { value: 'policy' } });
    expect(screen.queryByRole('region', { name: 'Version inspector' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Open environment' })).not.toBeInTheDocument();
    expect(onOpen).not.toHaveBeenCalled();
  });
  it('preserves colliding internal names as distinct families and exact version source identities', () => {
    const onOpen = vi.fn();
    render(<LibraryPanel onOpen={onOpen} />);
    for (const name of ['C1 · G1 tabletop', 'G1 · incompatible reach scenario']) {
      fireEvent.click(screen.getByRole('button', { name: `Inspect ${name}` }));
      fireEvent.click(screen.getByRole('button', { name: 'Open environment' }));
    }
    const [tabletop, reach] = onOpen.mock.calls.map(([selection]) => selection);
    expect(tabletop.familyId).not.toBe(reach.familyId);
    expect(tabletop.source).not.toBe(reach.source);
    expect(tabletop.hand).not.toBe(reach.hand);
    expect(tabletop.yaml).not.toBe(reach.yaml);
    fireEvent.change(screen.getByRole('combobox', { name: 'Inspect version' }), { target: { value: 'example-g1-reach-v2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Open environment' }));
    const secondRevision = onOpen.mock.calls[2][0];
    expect(secondRevision.familyId).toBe(reach.familyId);
    expect(secondRevision.versionId).not.toBe(reach.versionId);
    expect(secondRevision.source).not.toBe(reach.source);
    expect(secondRevision.yaml).not.toBe(reach.yaml);
  });
  it('keeps the picker compact and local until explicit Open, with parent-controlled active selection', () => {
    const onOpen = vi.fn();
    const onBrowse = vi.fn();
    const view = render(<EnvironmentPicker selection={null} onOpen={onOpen} onBrowse={onBrowse} />);
    const families = screen.getByRole('combobox', { name: 'Environment family' });
    expect(within(families).getAllByRole('option')).toHaveLength(exampleFamilies.filter((family) => family.kind === 'environment').length + 1);
    expect(screen.getByRole('button', { name: 'Open selected version' })).toBeDisabled();
    fireEvent.change(families, { target: { value: 'example-c1-g1-tabletop' } });
    const versions = screen.getByRole('combobox', { name: 'Environment version' });
    expect(versions).toHaveValue('example-c1-g1-tabletop-v1');
    fireEvent.change(versions, { target: { value: 'example-c1-g1-tabletop-v10' } });
    expect(onOpen).not.toHaveBeenCalled();
    expect(screen.getByText('No environment open')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open selected version' }));
    const requested = onOpen.mock.calls[0][0];
    expect(requested.versionId).toBe('example-c1-g1-tabletop-v10');
    expect(screen.getByText('No environment open')).toBeInTheDocument();
    view.rerender(<EnvironmentPicker selection={requested} onOpen={onOpen} onBrowse={onBrowse} />);
    expect(screen.getByText('Open: C1 · G1 tabletop · v10')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Browse Library' }));
    expect(onBrowse).toHaveBeenCalledOnce();
    expect(onOpen).toHaveBeenCalledOnce();
  });
  it('searches across source, name and scenario while combining the kind filter', () => {
    render(<LibraryPanel onOpen={vi.fn()} />);
    const search = screen.getByRole('searchbox', { name: 'Search example library' });
    const kind = screen.getByRole('combobox', { name: 'Document kind' });
    fireEvent.change(search, { target: { value: '  BANANA  ' } });
    expect(screen.getAllByRole('button', { name: /^Inspect / })).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Inspect A2 · DROID banana to plate' })).toBeInTheDocument();
    fireEvent.change(search, { target: { value: 'example-tabletop' } });
    expect(screen.getAllByRole('button', { name: /^Inspect / })).toHaveLength(3);
    fireEvent.change(kind, { target: { value: 'policy' } });
    expect(screen.getAllByRole('button', { name: /^Inspect / })).toHaveLength(1);
    fireEvent.change(search, { target: { value: 'no-match' } });
    expect(screen.getByText('No example documents match these filters.')).toBeInTheDocument();
    fireEvent.change(kind, { target: { value: 'all' } });
    fireEvent.change(search, { target: { value: 'example-c1-g1-tabletop/v10.yaml' } });
    expect(screen.getAllByRole('button', { name: /^Inspect / })).toHaveLength(1);
  });
  it('keeps policies, experiments and unclassified records inspectable but not openable', () => {
    const onOpen = vi.fn();
    render(<LibraryPanel onOpen={onOpen} />);
    for (const name of ['Example policy profile', 'Example seed comparison', 'Example unclassified document']) {
      fireEvent.click(screen.getByRole('button', { name: `Inspect ${name}` }));
      expect(screen.getByRole('region', { name: 'Version inspector' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Open environment' })).not.toBeInTheDocument();
      expect(screen.getByText('Only environment documents can be opened in the workspace.')).toBeInTheDocument();
    }
    expect(onOpen).not.toHaveBeenCalled();
  });
  it('inspects numerically ordered versions locally, opening only an explicit exact revision', () => {
    const onOpen = vi.fn();
    render(<LibraryPanel onOpen={onOpen} />);
    fireEvent.click(screen.getByRole('button', { name: 'Inspect C1 · G1 tabletop' }));
    const versions = screen.getByRole('combobox', { name: 'Inspect version' });
    expect(within(versions).getAllByRole('option').map((option) => option.textContent)).toEqual(
      Array.from({ length: 12 }, (_, index) => `v${index + 1}${index === 0 ? ' · explicit baseline' : ''}`),
    );
    fireEvent.change(versions, { target: { value: 'example-c1-g1-tabletop-v10' } });
    expect(onOpen).not.toHaveBeenCalled();
    expect(screen.getByText('example-c1-g1-tabletop-v9')).toBeInTheDocument();
    expect(screen.getByText('example-library/example-c1-g1-tabletop/v10.yaml')).toBeInTheDocument();
    expect(screen.getByText('Example only · not validated')).toBeInTheDocument();
    expect(screen.getByText('No rendered preview or execution evidence.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open environment' }));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ familyId: 'example-c1-g1-tabletop', versionId: 'example-c1-g1-tabletop-v10', version: 10, hand: 'Left', robot: 'G1' }));
  });
  it('shows families, not flattened versions, with separate artifact kinds', () => {
    render(<LibraryPanel onOpen={vi.fn()} />);
    const rows = within(screen.getByRole('table', { name: 'Example document families' })).getAllByRole('row');
    expect(rows).toHaveLength(exampleFamilies.length + 1);
    expect(screen.getByRole('button', { name: 'Inspect C1 · G1 tabletop' })).toBeInTheDocument();
    expect(screen.getByText('12 versions')).toBeInTheDocument();
    expect(screen.getByText('Pinned example')).toBeInTheDocument();
    expect(screen.getByText('Recent example')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Inspect G1 · incompatible reach scenario' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Inspect A2 · DROID banana to plate' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Open environment' })).not.toBeInTheDocument();
  });
});
