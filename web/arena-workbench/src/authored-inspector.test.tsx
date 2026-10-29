import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { Asset, Validation } from './editor-contracts';
import { AuthoredInspector } from './authored-inspector';

// Shape emitted by workbench/documents.py projection(), not a preview schema.
function fixture(): Validation {
  const entries = [
    { role: 'embodiment', entry: { id: 'robot', registry_name: 'franka', params: {} } },
    { role: 'background', entry: { id: 'room', registry_name: 'kitchen', params: {} } },
    { role: 'object', entry: { id: 'banana', registry_name: 'banana', params: {} } },
    { role: 'object_reference', entry: { id: 'shelf', parent_id: 'room', prim_path: '/World/Kitchen/Shelf', object_type: 'base', params: {} } },
  ];
  const assets: Asset[] = entries.map(({ role, entry }) => ({ ...entry, role, properties: entry }));
  return { valid: true, source_hash: 'a'.repeat(64), canonical_hash: 'b'.repeat(64), errors: [], warnings: [],
    spec: { embodiment: entries[0].entry, background: entries[1].entry, objects: [entries[2].entry], object_references: [entries[3].entry] },
    summary: 'Authored environment', assets,
    graph: { nodes: assets.map(asset => ({ id: asset.id, label: asset.id, role: asset.role, properties: asset.properties as never })), edges: [] },
    relations: [], reified_relations: [], tasks: [] };
}
function select(id: string) { fireEvent.change(screen.getByRole('combobox', { name: 'Authored asset' }), { target: { value: id } }); }
function field(label: string) { return screen.getByText(label, { selector: 'dt' }).nextElementSibling as HTMLElement; }
function freeze(value: unknown) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
}
afterEach(() => vi.unstubAllGlobals());

it.each([
  [{ initial_pose: { position_xyz: [1.25, -2, 0.5], rotation_xyzw: [0.1, 0.2, 0.3, 0.9] }, scale: [1, 2, 3] }, '1.25, -2, 0.5', '0.1, 0.2, 0.3, 0.9', '1, 2, 3'],
  [{ initial_pose: { position_xyz: [4, 5, 6] }, scale: 0.75 }, '4, 5, 6', 'Unavailable', '0.75'],
  [{}, 'Unavailable', 'Unavailable', 'Unavailable'],
  [{ initial_pose: null, scale: null }, 'Unavailable', 'Unavailable', 'Unavailable'],
  [{ initial_pose: { position_xyz: [Infinity, 0, 0], rotation_xyzw: [0, 0, NaN, 1] }, scale: Infinity }, 'Unavailable', 'Unavailable', 'Unavailable'],
  [{ initial_pose: { position_xyz: ['1', 2, 3], rotation_xyzw: [0, 0, 1] }, scale: {} }, 'Unavailable', 'Unavailable', 'Unavailable'],
])('shows authored pose and scale without inventing missing or invalid components (%j)', (params, position, quaternion, scale) => {
  const validation = fixture();
  validation.assets[2].properties.params = params;
  render(<AuthoredInspector validation={validation} bindingKey="a" onFocusSpecification={() => {}} />);
  select('banana');
  expect(field('Initial position · XYZ (m) · environment frame')).toHaveTextContent(position);
  expect(field('Initial rotation · quaternion XYZW')).toHaveTextContent(quaternion);
  expect(field('Authored scale')).toHaveTextContent(scale);
  expect(screen.getByText(/defaults.*unknown/i)).toBeInTheDocument();
  expect(screen.getByText(/not.*world.*pose/i)).toBeInTheDocument();
});

// ArenaEnvGraphSpec.validate/_assert_object_reference_parents accepts both roles.
it.each(['room', 'banana'])('accepts reference parent %s without resolving its parent-relative USD transform', parentId => {
  const validation = fixture();
  validation.assets[3].parent_id = parentId;
  validation.assets[3].properties.parent_id = parentId;
  render(<AuthoredInspector validation={validation} bindingKey="a" onFocusSpecification={() => {}} />);
  select('shelf');
  expect(field('Reference parent ID')).toHaveTextContent(parentId);
  expect(screen.getByText(/projected containment/i)).toBeInTheDocument();
  expect(screen.getByText(/parent-relative.*USD.*not resolved/i)).toBeInTheDocument();
  expect(screen.queryByText(/not a transform parent/i)).not.toBeInTheDocument();
  expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
});

it.each(['robot', 'shelf', 'missing'])('withholds reference parent %s even when projected and authored fields agree', parentId => {
  const validation = fixture();
  validation.assets[3].parent_id = parentId;
  validation.assets[3].properties.parent_id = parentId;
  render(<AuthoredInspector validation={validation} bindingKey="a" onFocusSpecification={() => {}} />);
  expect(screen.getByText(/authored data unavailable/i)).toBeInTheDocument();
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
});

it('retires selection across binding changes, null/invalid validation and same-ID replacement payloads', () => {
  const validation = fixture();
  const props = { validation, bindingKey: 'A', onFocusSpecification: () => {} };
  const view = render(<AuthoredInspector {...props} />);
  select('banana');
  view.rerender(<AuthoredInspector {...props} bindingKey="B" />);
  expect(screen.queryByRole('region', { name: 'Selected authored asset' })).not.toBeInTheDocument();
  view.rerender(<AuthoredInspector {...props} />);
  expect(screen.getByRole('combobox')).toHaveValue('');
  select('banana');
  view.rerender(<AuthoredInspector {...props} validation={null} />);
  expect(screen.queryByRole('region', { name: 'Selected authored asset' })).not.toBeInTheDocument();
  expect(screen.queryByText(/schema-valid/i)).not.toBeInTheDocument();
  view.rerender(<AuthoredInspector {...props} />);
  expect(screen.getByRole('combobox')).toHaveValue('');
  select('banana');
  view.rerender(<AuthoredInspector {...props} validation={{ ...validation, valid: false }} />);
  expect(screen.queryByRole('region', { name: 'Selected authored asset' })).not.toBeInTheDocument();
  view.rerender(<AuthoredInspector {...props} validation={fixture()} />);
  expect(screen.getByRole('combobox')).toHaveValue('');
  select('banana');
  view.rerender(<AuthoredInspector {...props} validation={fixture()} />);
  expect(screen.getByRole('combobox')).toHaveValue('');
});

it.each([
  (v: Validation) => { v.assets.push(v.assets[2]); },
  (v: Validation) => { v.assets[2].id = ''; },
  (v: Validation) => { v.assets[2].id = ' banana '; },
  (v: Validation) => { v.assets[2].id = 5 as never; },
  (v: Validation) => { v.assets[2].role = 'mystery'; },
  (v: Validation) => { v.assets[2].properties = null as never; },
  (v: Validation) => { v.assets[2].properties.id = 'other'; },
  (v: Validation) => { v.assets[2].registry_name = {} as never; },
  (v: Validation) => { v.assets[3].parent_id = 'missing'; },
  (v: Validation) => { v.assets[3].prim_path = {} as never; },
  (v: Validation) => { v.assets = {} as never; },
  (v: Validation) => { delete v.assets[1]; },
  (v: Validation) => { v.relations = null as never; },
  (v: Validation) => { v.reified_relations = null as never; },
  (v: Validation) => { v.tasks = null as never; },
  (v: Validation) => { v.valid = 'true' as never; },
])('withholds the entire projection for malformed or ambiguous wire identity %#', corrupt => {
  const validation = fixture(); corrupt(validation);
  render(<AuthoredInspector validation={validation} bindingKey="a" onFocusSpecification={() => {}} />);
  expect(screen.getByText(/authored data unavailable/i)).toBeInTheDocument();
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Selected authored asset' })).not.toBeInTheDocument();
  expect(screen.queryByText(/schema-valid/i)).not.toBeInTheDocument();
});

it('shows only matching authored relations, reifiers and task parameters, without solving placement', () => {
  const validation = fixture();
  validation.assets[2].properties.params = { initial_pose: { position_xyz: [7, 8, 9] } };
  validation.relations = [
    { kind: 'on', subject: 'banana', reference: 'shelf', params: { offset: 0.02 } },
    { kind: 'is_anchor', subject: 'robot', reference: null, params: {} },
  ];
  validation.reified_relations = [{ reifier_id: 'placement_contract', source_id: 'banana', target_id: 'shelf', relation_type: 'PLACED_ON', tolerance: { nominal: 0.01 } }];
  validation.tasks = [
    { kind: 'PickAndPlaceTask', params: { object: 'banana', target: 'shelf' } },
    { kind: 'OtherTask', params: { object: 'banana_suffix' } },
  ];
  freeze(validation);
  render(<AuthoredInspector validation={validation} bindingKey="a" onFocusSpecification={() => {}} />);
  select('banana');
  expect(field('Initial position · XYZ (m) · environment frame')).toHaveTextContent('7, 8, 9');
  expect(screen.getByText(/placement.*may.*ignore.*initial_pose/i)).toBeInTheDocument();
  const relations = within(screen.getByRole('region', { name: 'Relevant authored relations' }));
  fireEvent.click(relations.getByRole('button', { name: 'Expand 0' }));
  expect(relations.getByText('on', { selector: 'pre' })).toBeInTheDocument();
  expect(relations.queryByText('is_anchor', { selector: 'pre' })).not.toBeInTheDocument();
  const reifiers = within(screen.getByRole('region', { name: 'Relevant authored reifiers' }));
  fireEvent.click(reifiers.getByRole('button', { name: 'Expand 0' }));
  expect(reifiers.getByText('placement_contract', { selector: 'pre' })).toBeInTheDocument();
  const tasks = within(screen.getByRole('region', { name: 'Task parameters mentioning this ID' }));
  fireEvent.click(tasks.getByRole('button', { name: 'Expand 0' }));
  expect(tasks.getByText('PickAndPlaceTask', { selector: 'pre' })).toBeInTheDocument();
  expect(tasks.queryByText('OtherTask', { selector: 'pre' })).not.toBeInTheDocument();
  expect(tasks.getByText(/exact string match.*not inferred/i)).toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Raw authored properties' })).toBeInTheDocument();
});

it.each([
  (v: Validation) => { v.relations = [{ kind: 'on', subject: 'banana', reference: 'absent', params: {} }]; },
  (v: Validation) => { v.relations = [{ kind: {}, subject: 'banana', params: {} }]; },
  (v: Validation) => { v.reified_relations = [{ reifier_id: 'banana', source_id: 'banana', target_id: 'shelf', relation_type: 'ON' }]; },
  (v: Validation) => { const r = { reifier_id: 'r', source_id: 'banana', target_id: 'shelf', relation_type: 'ON' }; v.reified_relations = [r, r]; },
  (v: Validation) => { v.tasks = [{ kind: 'Task', params: [] }]; },
  (v: Validation) => { v.assets[2].role = Object.create(null); },
])('withholds malformed relationship/task identity and non-string roles %#', corrupt => {
  const validation = fixture(); corrupt(validation);
  render(<AuthoredInspector validation={validation} bindingKey="a" onFocusSpecification={() => {}} />);
  expect(screen.getByText(/authored data unavailable/i)).toBeInTheDocument();
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
});

it('sanitizes malformed nested values and cycles before PropertyTree or task matching can inspect them', () => {
  const validation = fixture();
  const cycle: Record<string, unknown> = {}; cycle.self = cycle;
  validation.assets[2].properties.params = {
    initial_pose: { position_xyz: [1, , 3], rotation_xyzw: { bad: true } },
    scale: NaN, notFinite: Infinity, bigint: 1n, fn: () => 'UNSAFE_FUNCTION',
    odd: new Date(), cycle,
  };
  validation.tasks = [{ kind: 'PickAndPlaceTask', params: { object: 'banana', cycle, bad: Infinity } }];
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  render(<AuthoredInspector validation={validation} bindingKey="a" onFocusSpecification={() => {}} />);
  select('banana');
  const raw = within(screen.getByRole('region', { name: 'Raw authored properties' }));
  fireEvent.click(raw.getByRole('button', { name: 'Expand params' }));
  fireEvent.click(raw.getByRole('button', { name: 'Expand cycle' }));
  expect(raw.getAllByText(/unavailable/i).length).toBeGreaterThan(0);
  expect(raw.queryByText(/Infinity|NaN|UNSAFE_FUNCTION/)).not.toBeInTheDocument();
  expect(field('Initial position · XYZ (m) · environment frame')).toHaveTextContent('Unavailable');
  expect(field('Authored scale')).toHaveTextContent('Unavailable');
  expect(fetcher).not.toHaveBeenCalled();
});

it('bounds deep, wide and long content with explicit unavailable notices instead of serializing whole trees', () => {
  const validation = fixture();
  let deep: unknown = 'HIDDEN_DEPTH_MARKER';
  for (let i = 0; i < 100; i++) deep = { next: deep };
  validation.assets[2].properties.params = {
    deep, long: 'LONG_CONTENT_MARKER'.repeat(10000),
    wide: Object.fromEntries(Array.from({ length: 10000 }, (_, i) => [`k${i}`, i])),
  };
  render(<AuthoredInspector validation={validation} bindingKey="a" onFocusSpecification={() => {}} />);
  select('banana');
  const raw = within(screen.getByRole('region', { name: 'Raw authored properties' }));
  fireEvent.click(raw.getByRole('button', { name: 'Expand params' }));
  expect(raw.getAllByText(/unavailable/i).length).toBeGreaterThan(0);
  expect(screen.getByText(/display bounds.*2,000-value inspection budget per tree.*unavailable placeholders may exceed this count/i)).toBeInTheDocument();
  expect(screen.queryByText(/LONG_CONTENT_MARKER|HIDDEN_DEPTH_MARKER/)).not.toBeInTheDocument();
  expect(document.querySelectorAll('[data-property-row]').length).toBeLessThan(100);
});

it('withholds oversized collections and never invents an asset when the validated collection is empty', () => {
  const validation = fixture();
  validation.assets = [];
  const view = render(<AuthoredInspector validation={validation} bindingKey="a" onFocusSpecification={() => {}} />);
  expect(screen.getAllByRole('option')).toHaveLength(1);
  expect(screen.queryByRole('region', { name: 'Selected authored asset' })).not.toBeInTheDocument();
  view.rerender(<AuthoredInspector validation={{ ...fixture(), tasks: Array.from({ length: 501 }, () => ({ kind: 'Task', params: {} })) }} bindingKey="a" onFocusSpecification={() => {}} />);
  expect(screen.getByText(/authored data unavailable/i)).toBeInTheDocument();
});

it.each([
  (v: Validation) => { delete v.assets[3].prim_path; },
  (v: Validation) => { v.assets[2].properties.registry_name = 'conflicting_registry'; },
])('rejects conflicting optional projection fields without hiding their authored values behind defaults %#', corrupt => {
  const validation = fixture(); corrupt(validation);
  render(<AuthoredInspector validation={validation} bindingKey="a" onFocusSpecification={() => {}} />);
  expect(screen.getByText(/authored data unavailable/i)).toBeInTheDocument();
});

it('does not treat a zero quaternion as an authored orientation or execute nested property accessors', () => {
  const validation = fixture();
  const params = { initial_pose: { rotation_xyzw: [0, 0, 0, 0] } };
  const accessor = vi.fn(() => { throw new Error('must not execute'); });
  Object.defineProperty(params, 'unsafe', { enumerable: true, get: accessor });
  validation.assets[2].properties.params = params;
  render(<AuthoredInspector validation={validation} bindingKey="a" onFocusSpecification={() => {}} />);
  select('banana');
  expect(field('Initial rotation · quaternion XYZW')).toHaveTextContent('Unavailable');
  expect(accessor).not.toHaveBeenCalled();
});

it('selects actual projected IDs across all roles, stays read-only and only focuses the specification', () => {
  const validation = fixture();
  const before = JSON.stringify(validation);
  freeze(validation);
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  const focus = vi.fn();
  render(<AuthoredInspector validation={validation} bindingKey="session/source/text" onFocusSpecification={focus} />);
  expect(screen.getByText(/schema-valid.*not runtime-validated/i)).toBeInTheDocument();
  expect(screen.getByText(/read-only/i)).toBeInTheDocument();
  expect(screen.getByText(/editing.*unsupported/i)).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Selected authored asset' })).not.toBeInTheDocument();
  for (const asset of validation.assets) {
    select(asset.id);
    expect(field('Asset ID')).toHaveTextContent(asset.id);
    expect(field('Role')).toHaveTextContent(asset.role);
    expect(field('Registry')).toHaveTextContent(asset.registry_name ?? 'Not authored');
  }
  expect(field('Reference parent ID')).toHaveTextContent('room');
  expect(field('Prim path')).toHaveTextContent('/World/Kitchen/Shelf');
  expect(screen.getByText(/projected containment/i)).toBeInTheDocument();
  expect(screen.getByText(/parent-relative.*USD.*not resolved/i)).toBeInTheDocument();
  const button = screen.getByRole('button', { name: 'Focus raw specification' });
  expect(button).toHaveAttribute('type', 'button');
  fireEvent.click(button);
  expect(focus).toHaveBeenCalledTimes(1);
  expect(fetcher).not.toHaveBeenCalled();
  expect(JSON.stringify(validation)).toBe(before);
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
});
