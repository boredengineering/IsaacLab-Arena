import { expect, it, vi } from 'vitest';
import { normalizeGraph, projectGraph } from './graph-model';
import { createExplorerState, reconcileExplorerState, resetExplorerFilters, selectEntity, copyPresentation, resetViewCamera } from './explorer-state';
const data = (property: unknown = {}) => normalizeGraph({ nodes: [{ id: '__proto__', label: 'A', role: 'object', properties: {} }], edges: [{ id: 'relation:0', source: '__proto__', target: '__proto__', label: 'on', properties: property }] });
it('retains scoped presentation through withheld data and reconciles semantic edge identity', () => {
  const graph = data();
  let state = createExplorerState('scope', '1', graph, true);
  expect(state.mode).toBe('2d');
  expect(state.snapshots['2d'].frozen).toBe(true);
  state = selectEntity(state, graph, { kind: 'edge', id: 'relation:0' });
  expect(reconcileExplorerState(state, 'scope', 'pending', null)).toBe(state);
  expect(reconcileExplorerState(state, 'scope', '2', data()).selection).toEqual(state.selection);
  expect(reconcileExplorerState(state, 'scope', '3', data({ changed: true })).selection).toBeNull();
  expect(reconcileExplorerState(state, 'other', '1', graph).selection).toBeNull();
});
it.each(['[truncated]', { nested: ['prefix[truncated]'] }])('clears selection across equally server-truncated edge revisions: %j', properties => {
  const graph = data(properties);
  const selected = selectEntity(createExplorerState('s', '1', graph), graph, { kind: 'edge', id: 'relation:0' });
  expect(selected.edgeIdentity).toBeNull();
  expect(reconcileExplorerState(selected, 's', '2', data(properties)).selection).toBeNull();
  expect(graph.edges[0].properties).toEqual(properties);
});
it('copies finite numeric snapshots only and clears indeterminate edge identities', () => {
  const graph = data(NaN);
  const selected = selectEntity(createExplorerState('s', '1', graph), graph, { kind: 'edge', id: 'relation:0' });
  expect(selected.edgeIdentity).toBeNull();
  expect(reconcileExplorerState(selected, 's', '2', data(NaN)).selection).toBeNull();
  const position = { x: 1, y: 2, z: 3, properties: 'must not retain' };
  const copied = copyPresentation({ positions: new Map([['__proto__', position], ['removed', position]]), pins: new Set(['__proto__', 'removed']), frozen: true, camera: { zoom: Infinity, center: { x: 2, y: 3 } } }, graph);
  expect(copied.positions.get('__proto__')).toEqual({ x: 1, y: 2, z: 3 });
  expect(copied.positions.has('removed')).toBe(false);
  expect(copied.camera?.zoom).toBeUndefined();
  position.x = 99;
  expect(copied.positions.get('__proto__')?.x).toBe(1);
});
it('initializes an empty revision token after withheld data and prunes removed nodes', () => {
  const withheld = createExplorerState('s', '', null);
  const available = reconcileExplorerState(withheld, 's', '', data());
  expect(available.filters.allowedRoles.has('object')).toBe(true);
  const selected = selectEntity(available, data(), { kind: 'node', id: '__proto__' });
  selected.snapshots['2d'].positions.set('__proto__', { x: 1, y: 2, z: 0 });
  selected.snapshots['2d'].pins.add('__proto__');
  const removed = reconcileExplorerState({ ...selected, filters: { ...selected.filters, neighborhood: true } }, 's', 'removed', normalizeGraph({ nodes: [], edges: [] }));
  expect(removed.selection).toBeNull();
  expect(removed.filters.neighborhood).toBe(false);
  expect(removed.snapshots['2d'].positions.size).toBe(0);
  expect(removed.snapshots['2d'].pins.size).toBe(0);
  expect(removed.announcement).toContain('Selection cleared');
});
const revisedCategories = () => normalizeGraph({
  nodes: [...data().nodes, { id: 'r', label: 'Relation', role: 'reifier', properties: {} }],
  edges: [...data().edges, { id: 'new', source: '__proto__', target: 'r', label: 'participant', properties: {} }],
});
it('includes newly introduced roles and relationship types in default filters across revisions', () => {
  const graph = revisedCategories();
  const initial = createExplorerState('s', '1', data());
  const next = reconcileExplorerState(initial, 's', '2', graph);
  const projection = projectGraph(graph, next.filters);
  expect(projection.nodeIds.has('r')).toBe(true);
  expect(projection.edgeIds.has('new')).toBe(true);
  expect(initial.filters.allowedRoles).toEqual(new Set(['object']));
  expect(initial.filters.allowedTypes).toEqual(new Set(['on']));
});
it('keeps partial exclusions through disappearance and reappearance while allowing unseen categories', () => {
  let state = createExplorerState('s', '1', revisedCategories());
  state = { ...state, filters: { ...state.filters, allowedRoles: new Set(['object']), allowedTypes: new Set(['on']), search: 'keep' } };
  state = reconcileExplorerState(state, 's', '2', data());
  const graph = normalizeGraph({
    nodes: [...revisedCategories().nodes, { id: 'light', label: 'Light', role: 'light', properties: {} }],
    edges: [...revisedCategories().edges, { id: 'lit', source: '__proto__', target: 'light', label: 'lit-by', properties: {} }],
  });
  const next = reconcileExplorerState(state, 's', '3', graph);
  expect(next.filters.allowedRoles).toEqual(new Set(['object', 'light']));
  expect(next.filters.allowedTypes).toEqual(new Set(['on', 'lit-by']));
  expect(next.filters.search).toBe('keep');
  expect([...projectGraph(graph, next.filters).nodeIds]).toEqual(['__proto__', 'light']);
  expect([...projectGraph(graph, next.filters).edgeIds]).toEqual(['relation:0', 'lit']);
});
it.each(['allowedRoles', 'allowedTypes'] as const)('preserves an explicitly empty %s across revisions', field => {
  const initial = createExplorerState('s', '1', data());
  const next = reconcileExplorerState({ ...initial, filters: { ...initial.filters, [field]: new Set<string>() } }, 's', '2', revisedCategories());
  expect(next.filters[field].size).toBe(0);
  expect(projectGraph(revisedCategories(), next.filters).edges).toEqual([]);
});
it('allows categories after an initially empty default graph but not explicitly empty filters', () => {
  const initial = createExplorerState('s', '1', normalizeGraph({ nodes: [], edges: [] }));
  const emptyRevision = reconcileExplorerState(initial, 's', '2', normalizeGraph({ nodes: [], edges: [] }));
  const graph = revisedCategories();
  const next = reconcileExplorerState(emptyRevision, 's', '3', graph);
  expect(projectGraph(graph, next.filters).nodes).toHaveLength(graph.nodes.length);
  expect(projectGraph(graph, next.filters).edges).toHaveLength(graph.edges.length);
  const explicit = reconcileExplorerState({ ...initial, filters: { ...initial.filters, allowedRoles: new Set(), allowedTypes: new Set() } }, 's', '2', graph);
  expect(explicit.filters.allowedRoles.size).toBe(0);
  expect(explicit.filters.allowedTypes.size).toBe(0);
});
it.each([false, true])('explicit filter reset preserves selection/presentation and restores empty All (preserveSearch=%s)', preserveSearch => {
  const graph = data();
  const selected = selectEntity(createExplorerState('s', '1', graph, true), graph, { kind: 'edge', id: 'relation:0' });
  selected.snapshots['2d'].positions.set('__proto__', { x: 7, y: 3, z: 0 });
  selected.snapshots['2d'].pins.add('__proto__');
  const state = { ...selected, filters: { ...selected.filters, search: 'keep', matchesOnly: true, neighborhood: true, allowedRoles: new Set<string>(), allowedTypes: new Set<string>() } };
  const reset = resetExplorerFilters(state, normalizeGraph({ nodes: [], edges: [] }), preserveSearch);
  expect(reset.filters.allowedRoles).toBe(reset.knownRoles);
  expect(reset.filters.allowedTypes).toBe(reset.knownTypes);
  expect(reset.filters.search).toBe(preserveSearch ? 'keep' : '');
  expect(reset.filters.matchesOnly).toBe(false);
  expect(reset.filters.neighborhood).toBe(false);
  expect(reset.selection).toBe(state.selection);
  expect(reset.edgeIdentity).toBe(state.edgeIdentity);
  expect(reset.snapshots).toBe(state.snapshots);
  expect(reset.table).toBe(state.table);
  expect(reset.mode).toBe(state.mode);
  expect(reset.announcement).toBe(state.announcement);
  expect(state.filters.matchesOnly).toBe(true);
  expect(state.filters.allowedRoles).not.toBe(state.knownRoles);
  const returned = reconcileExplorerState(reset, 's', '2', revisedCategories());
  const projection = projectGraph(revisedCategories(), returned.filters, returned.selection);
  expect(projection.nodes).toHaveLength(2);
  expect(projection.edges).toHaveLength(2);
});
it('resets 3D camera orientation without resetting layout or pins', () => {
  const fit = vi.fn(), orbit = vi.fn();
  resetViewCamera({ fit, orbit, getSnapshot: () => ({ positions: new Map(), pins: new Set(['a']), frozen: true, camera: { position: { x: 10, y: 0, z: 0 }, target: { x: 0, y: 0, z: 0 } } }) }, '3d');
  expect(fit).toHaveBeenCalledOnce();
  expect(orbit).toHaveBeenCalledWith(-Math.PI / 2, 0);
});
