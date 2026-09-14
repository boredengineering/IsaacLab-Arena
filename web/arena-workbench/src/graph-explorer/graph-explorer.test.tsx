import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { useEffect } from 'react';
import type { GraphRendererProps } from './renderer-contracts';
const engine = vi.hoisted(() => ({ mounts: 0, calls: vi.fn(), props: null as GraphRendererProps | null, pendingSnapshot: null as GraphRendererProps['snapshot'] | null }));
vi.mock('./graph-2d', () => ({ default: function Mock(props: GraphRendererProps) {
  engine.props = props;
  useEffect(() => { engine.mounts++; if (props.scopeKey === 'init-error') props.onError('private error details'); props.onReady({ fit: engine.calls, zoom: engine.calls, pan: engine.calls, orbit: engine.calls, reset: engine.calls, setFrozen: engine.calls, setPinned: engine.calls, unpinAll: engine.calls, moveNode: engine.calls, nudgeNode: engine.calls, getSnapshot: () => engine.pendingSnapshot ?? engine.props!.snapshot }); return () => props.onReady(null); }, [props.onReady]);
  return <button onClick={() => props.onSelect({ kind: 'node', id: 'a' })}>Engine select A</button>;
} }));
vi.mock('./graph-3d', () => ({ default: function Broken() { throw new Error('WebGL unavailable'); } }));
import GraphExplorer from './graph-explorer';
const graph = { nodes: [{ id: 'a', label: 'Alpha', role: 'object', properties: '[truncated]' }, { id: 'b', label: 'Beta', role: 'background', properties: {} }], edges: [{ id: 'e', source: 'a', target: 'b', label: 'connects', properties: {} }] };
it('does not rerender an engine when it republishes identical numeric presentation state', async () => {
  render(<GraphExplorer graph={graph} scopeKey="idle-snapshot" revisionKey="1" label="Idle" sourceKind="authored" />);
  await screen.findByRole('button', { name: 'Engine select A' });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Zoom in' })).toBeEnabled());
  const before = engine.props!;
  act(() => before.onSnapshot({ ...before.snapshot, positions: new Map(before.snapshot.positions), pins: new Set(before.snapshot.pins) }));
  expect(engine.props).toBe(before);
});

it('provides a text-labelled role color legend independent of the canvas', async () => {
  render(<GraphExplorer graph={graph} scopeKey="legend" revisionKey="1" label="Legend" sourceKind="authored" />);
  await screen.findByRole('button', { name: 'Engine select A' });
  const legend = screen.getByRole('list', { name: 'Node color legend' });
  expect(legend.textContent).toContain('object');
  expect(legend.textContent).toContain('background');
  const colors = [...legend.querySelectorAll<HTMLElement>('[data-role-color]')];
  expect(colors).toHaveLength(2);
  expect(colors.every(color => color.style.backgroundColor !== '')).toBe(true);
});

it('keeps selection/filter controller through modes and withheld data with local-only interactions', async () => {
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Network forbidden in local graph test'));
  const props = { graph, scopeKey: 'scope', revisionKey: '1', label: 'Authored graph', sourceKind: 'authored' as const };
  const { rerender } = render(<GraphExplorer {...props} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Engine select A' }));
  expect(screen.getByText('Node: Alpha')).toBeTruthy();
  fireEvent.click(screen.getByRole('tab', { name: 'Table' }));
  fireEvent.click(screen.getByLabelText('Role object'));
  expect(screen.getByText('Hidden by filters')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Reveal (clear filters)' }));
  expect(screen.queryByText('Hidden by filters')).toBeNull();
  rerender(<GraphExplorer {...props} graph={null} />);
  expect(screen.queryByText('Node: Alpha')).toBeNull();
  rerender(<GraphExplorer {...props} />);
  expect(screen.getByText('Node: Alpha')).toBeTruthy();
  rerender(<GraphExplorer {...props} visible={false} />);
  expect(screen.queryByRole('tab')).toBeNull();
  rerender(<GraphExplorer {...props} />);
  expect(screen.getByText('Node: Alpha')).toBeTruthy();
  expect(fetchSpy).not.toHaveBeenCalled(); fetchSpy.mockRestore();
});
it('offers imperative navigation and layout controls without remounting the renderer on expansion', async () => {
  render(<GraphExplorer graph={graph} scopeKey="controls" revisionKey="1" label="Controls" sourceKind="authored" />);
  await screen.findByRole('button', { name: 'Engine select A' });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Zoom in' })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
  expect(engine.calls).toHaveBeenCalledWith(1.25);
  fireEvent.click(screen.getByRole('button', { name: 'Pan left' }));
  expect(engine.calls).toHaveBeenCalledWith(-10, 0);
  fireEvent.click(screen.getByRole('button', { name: 'Freeze layout' }));
  expect(engine.calls).toHaveBeenCalledWith(true);
  const mounts = engine.mounts;
  const outside = document.createElement('button'); outside.textContent = 'Outside'; document.body.append(outside);
  fireEvent.click(screen.getByRole('button', { name: 'Expand graph' }));
  expect(screen.getByRole('dialog')).toBeTruthy();
  expect(outside).toHaveAttribute('inert');
  expect(screen.getByRole('button', { name: 'Close expanded graph' })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Expand graph' })).toHaveFocus());
  expect(engine.mounts).toBe(mounts);
  expect(outside).not.toHaveAttribute('inert'); outside.remove();
});
it('uses manual mode activation and confines lazy renderer failure to its visual area', async () => {
  const log = vi.spyOn(console, 'error').mockImplementation(() => {});
  render(<GraphExplorer graph={graph} scopeKey="lazy" revisionKey="1" label="Lazy" sourceKind="persisted" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Engine select A' }));
  const tab = screen.getByRole('tab', { name: '2D' }); tab.focus();
  fireEvent.keyDown(tab, { key: 'ArrowRight' });
  expect(screen.getByRole('tab', { name: '3D' })).toHaveFocus();
  expect(tab).toHaveAttribute('aria-selected', 'true');
  fireEvent.click(screen.getByRole('tab', { name: '3D' }));
  await screen.findByRole('alert');
  expect(screen.getByText('Node: Alpha')).toBeTruthy();
  fireEvent.click(screen.getByRole('tab', { name: 'Table' }));
  expect(screen.getByRole('table')).toBeTruthy();
  log.mockRestore();
});
it('reconciles revision and scope while rejecting retired renderer callbacks', async () => {
  const props = { graph, scopeKey: 'scope', revisionKey: '1', label: 'Scope', sourceKind: 'authored' as const };
  const { rerender } = render(<GraphExplorer {...props} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Engine select A' }));
  const retired = engine.props!;
  act(() => retired.onSnapshot({ positions: new Map([['a', { x: 7, y: 2, z: 0 }]]), pins: new Set(['a']), frozen: true }));
  expect(screen.getByRole('button', { name: 'Resume layout' })).toBeTruthy();
  rerender(<GraphExplorer {...props} graph={null} />);
  rerender(<GraphExplorer {...props} revisionKey="2" />);
  await screen.findByRole('button', { name: 'Engine select A' });
  expect(screen.getByText('Node: Alpha')).toBeTruthy();
  expect(engine.props?.snapshot.pins.has('a')).toBe(true);
  rerender(<GraphExplorer {...props} scopeKey="replacement" />);
  act(() => { retired.onSelect({ kind: 'node', id: 'a' }); retired.onSnapshot({ positions: new Map(), pins: new Set(['a']), frozen: true }); });
  await screen.findByRole('button', { name: 'Engine select A' });
  expect(screen.queryByText('Node: Alpha')).toBeNull();
  expect(engine.props?.snapshot.pins.size).toBe(0);
});
it('projects edge-only matches with authoritative role/type filters and explicit Reveal', async () => {
  render(<GraphExplorer graph={graph} scopeKey="filters" revisionKey="1" label="Filters" sourceKind="persisted" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Engine select A' }));
  fireEvent.change(screen.getByLabelText('Search returned graph'), { target: { value: 'connects' } });
  fireEvent.click(screen.getByLabelText('Show matches only'));
  expect(engine.props!.projection.nodes).toHaveLength(2);
  expect(engine.props!.projection.matchingNodeIds.size).toBe(0);
  expect(engine.props!.projection.matchingEdgeIds.size).toBe(1);
  fireEvent.click(screen.getByLabelText('Type connects'));
  expect(engine.props!.projection.nodes).toHaveLength(0);
  expect(screen.getByText('Hidden by filters')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Reveal (clear filters)' }));
  expect(screen.getByLabelText('Search returned graph')).toHaveValue('connects');
  expect(screen.getByLabelText('Show matches only')).not.toBeChecked();
  expect(engine.props!.projection.nodes).toHaveLength(2);
  fireEvent.click(screen.getByLabelText('Role background'));
  expect(engine.props!.projection.edges).toHaveLength(0);
});
it('starts reduced-motion layouts frozen and preserves per-mode intent', async () => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })));
  render(<GraphExplorer graph={graph} scopeKey="motion" revisionKey="1" label="Motion" sourceKind="authored" />);
  await screen.findByRole('button', { name: 'Engine select A' });
  expect(screen.getByRole('button', { name: 'Resume layout' })).toBeTruthy();
  fireEvent.click(screen.getByRole('tab', { name: 'Table' }));
  expect(screen.getByRole('button', { name: 'Reset layout' })).toBeDisabled();
  fireEvent.click(screen.getByRole('tab', { name: '2D' }));
  await screen.findByRole('button', { name: 'Engine select A' });
  expect(engine.props!.snapshot.frozen).toBe(true);
  vi.unstubAllGlobals();
});
it('captures final numeric presentation before hiding a renderer', async () => {
  const props = { graph, scopeKey: 'capture', revisionKey: '1', label: 'Capture', sourceKind: 'authored' as const };
  const { rerender } = render(<GraphExplorer {...props} />);
  await screen.findByRole('button', { name: 'Engine select A' });
  engine.pendingSnapshot = { positions: new Map([['a', { x: 42, y: 3, z: 0 }]]), pins: new Set(['a']), frozen: true, camera: { zoom: 2 } };
  rerender(<GraphExplorer {...props} graph={null} />);
  engine.pendingSnapshot = null;
  rerender(<GraphExplorer {...props} />);
  await screen.findByRole('button', { name: 'Engine select A' });
  expect(engine.props!.snapshot.positions.get('a')?.x).toBe(42);
  expect(engine.props!.snapshot.camera?.zoom).toBe(2);
});
it('keeps initialization errors local and focuses selection after explicit Reveal', async () => {
  const { rerender } = render(<GraphExplorer graph={graph} scopeKey="init-error" revisionKey="1" label="Error" sourceKind="authored" />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Graph renderer unavailable');
  expect(screen.queryByText('private error details')).toBeNull();
  rerender(<GraphExplorer graph={graph} scopeKey="reveal" revisionKey="1" label="Reveal" sourceKind="authored" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Engine select A' }));
  fireEvent.click(screen.getByLabelText('Role object'));
  engine.calls.mockClear();
  fireEvent.click(screen.getByRole('button', { name: 'Reveal (clear filters)' }));
  await waitFor(() => expect(engine.calls).toHaveBeenCalledWith(['a', 'b']));
});
it('preserves table page across withheld data and raw-row hiding', () => {
  const many = { nodes: Array.from({ length: 60 }, (_, i) => ({ id: String(i), label: String(i), role: 'object', properties: {} })), edges: [] };
  const props = { graph: many, scopeKey: 'pages', revisionKey: '1', label: 'Pages', sourceKind: 'persisted' as const };
  const { rerender } = render(<GraphExplorer {...props} />);
  fireEvent.click(screen.getByRole('tab', { name: 'Table' }));
  fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
  expect(screen.getByText(/Page 2 of 3/)).toBeTruthy();
  rerender(<GraphExplorer {...props} graph={null} />);
  rerender(<GraphExplorer {...props} />);
  expect(screen.getByText(/Page 2 of 3/)).toBeTruthy();
  rerender(<GraphExplorer {...props} visible={false} />);
  rerender(<GraphExplorer {...props} />);
  expect(screen.getByText(/Page 2 of 3/)).toBeTruthy();
});
it.each([
  ['Clear filters', 'empty'],
  ['Clear filters', 'edgeless'],
  ['Clear filters', 'absent categories'],
  ['Reveal (clear filters)', 'edgeless'],
  ['Reveal (clear filters)', 'absent categories'],
])('%s restores All category intent after %s revisions', async (action, scenario) => {
  const props = { graph, scopeKey: 'reset-categories', revisionKey: '1', label: 'Reset categories', sourceKind: 'authored' as const };
  const { rerender } = render(<GraphExplorer {...props} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Engine select A' }));
  fireEvent.click(screen.getByRole('tab', { name: 'Table' }));
  fireEvent.click(screen.getByLabelText('Role background'));
  fireEvent.click(screen.getByLabelText('Type connects'));
  // Ordinary checkbox changes retain deliberate exclusions, including explicit None.
  rerender(<GraphExplorer {...props} revisionKey="2" />);
  expect(screen.getByLabelText('Role background')).not.toBeChecked();
  expect(screen.getByLabelText('Type connects')).not.toBeChecked();
  const reduced = {
    nodes: scenario === 'empty' ? [] : scenario === 'edgeless' ? graph.nodes : [graph.nodes[0]],
    edges: [],
  };
  rerender(<GraphExplorer {...props} graph={reduced} revisionKey="3" />);
  fireEvent.change(screen.getByLabelText('Search returned graph'), { target: { value: 'no match' } });
  fireEvent.click(screen.getByLabelText('Show matches only'));
  if (scenario !== 'empty') fireEvent.click(screen.getByLabelText('Loaded neighbors'));
  fireEvent.click(screen.getByRole('button', { name: action }));
  expect(screen.getByLabelText('Search returned graph')).toHaveValue(action === 'Clear filters' ? '' : 'no match');
  expect(screen.getByLabelText('Show matches only')).not.toBeChecked();
  expect(screen.getByLabelText('Loaded neighbors')).not.toBeChecked();
  if (scenario !== 'empty') expect(screen.getByText('Node: Alpha')).toBeTruthy();
  const expanded = {
    nodes: [...graph.nodes, { id: 'c', label: 'Gamma', role: 'light', properties: {} }],
    edges: [...graph.edges, { id: 'new', source: 'a', target: 'c', label: 'lit-by', properties: {} }],
  };
  rerender(<GraphExplorer {...props} graph={expanded} revisionKey="4" />);
  expect(screen.getByLabelText('Role background')).toBeChecked();
  expect(screen.getByLabelText('Role light')).toBeChecked();
  expect(screen.getByLabelText('Type connects')).toBeChecked();
  expect(screen.getByLabelText('Type lit-by')).toBeChecked();
  expect(screen.getByText(/Visible: 3 \/ returned 3 nodes · 2 \/ returned 2 relationships/)).toBeTruthy();
});

it('provides explicit stress and malformed graph states with usable Table access', async () => {
  const { rerender } = render(<GraphExplorer graph={{ nodes: Array.from({ length: 1000 }, (_, i) => ({ id: String(i), label: String(i), role: 'object', properties: {} })), edges: [] }} scopeKey="stress" revisionKey="1" label="Stress" sourceKind="authored" />);
  expect(screen.getByText(/Visualization limit/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Engine select A' })).toBeNull();
  fireEvent.click(screen.getByRole('tab', { name: 'Table' }));
  expect(screen.getByRole('table')).toBeTruthy();
  expect(screen.getByText(/1000 visible rows/)).toBeTruthy();
  rerender(<GraphExplorer graph={{ nodes: [null], edges: 'invalid' }} scopeKey="bad" revisionKey="1" label="Bad" sourceKind="persisted" />);
  expect(screen.getByText(/Projection diagnostics:/)).toBeTruthy();
  expect(screen.getByText(/No valid graph entities/)).toBeTruthy();
});
