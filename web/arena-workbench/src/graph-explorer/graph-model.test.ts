import { describe, expect, it } from 'vitest';
import * as model from './graph-model';
import type { Graph } from '../editor-contracts';

function freeze<T>(value: T): T {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

const node = (id: string, role = 'object', label = 'same label') => ({ id, role, label, properties: {} });
const edge = (id: string, source: string, target: string, label = 'on') => ({ id, source, target, label, properties: {} });

describe('normalizeGraph', () => {
  it('indexes literal identities without mutating a deeply frozen Graph', () => {
    const graph: Graph = freeze({
      nodes: [node('__proto__'), node('a'), node('disconnected')],
      edges: [edge('a', '__proto__', 'a'), edge('loop', 'a', 'a')],
    });
    const before = JSON.stringify(graph);
    const normalized = model.normalizeGraph(graph);
    expect(normalized.nodes.map(n => n.id)).toEqual(['__proto__', 'a', 'disconnected']);
    expect(normalized.nodeById.get('__proto__')?.label).toBe('same label');
    expect(normalized.edgeById.get('a')?.source).toBe('__proto__');
    expect(normalized.incidentEdges.get('a')?.map(e => e.id)).toEqual(['a', 'loop']);
    expect(normalized.incidentEdges.get('disconnected')).toEqual([]);
    expect(normalized.diagnostics).toEqual([]);
    expect(normalized.returned).toEqual({ nodes: 3, edges: 2 });
    expect(normalized.quarantined).toEqual({ nodes: 0, edges: 0 });
    expect(normalized.nodes[0]).not.toBe(graph.nodes[0]);
    expect(Object.isFrozen(normalized.nodes[0].properties)).toBe(true);
    expect(JSON.stringify(graph)).toBe(before);
    expect(model.normalizeGraph({ nodes: [], edges: [] }).nodes).toEqual([]);
  });

  it('quarantines every duplicate and dangling endpoint without conflating entity kinds', () => {
    const normalized = model.normalizeGraph({
      nodes: [node('a'), node('duplicate'), node('duplicate'), node('b'), { ...node('broken'), id: 12 }],
      edges: [edge('a', 'a', 'b'), edge('duplicate-edge', 'a', 'b'), edge('duplicate-edge', 'b', 'a'),
        edge('dangling', 'a', 'missing'), edge('ambiguous', 'a', 'duplicate'), { ...edge('bad', 'a', 'b'), target: {} }],
    });
    expect(normalized.nodes.map(n => n.id)).toEqual(['a', 'b']);
    expect(normalized.edges.map(e => e.id)).toEqual(['a']);
    expect(normalized.quarantined).toEqual({ nodes: 3, edges: 5 });
    expect(normalized.diagnostics.filter(d => d.code === 'duplicate-id')).toHaveLength(4);
    expect(normalized.diagnostics.filter(d => d.code === 'dangling-endpoint')).toHaveLength(2);
    expect(normalized.diagnostics.filter(d => d.code === 'invalid-field')).toHaveLength(2);
  });

  it('validates unknown shapes and fields rather than coercing or repairing identities', () => {
    for (const input of [null, false, 1, 'bad', [], { nodes: {}, edges: 'bad' }]) {
      const normalized = model.normalizeGraph(input);
      expect(normalized.nodes).toEqual([]);
      expect(normalized.edges).toEqual([]);
      expect(normalized.diagnostics.length).toBeGreaterThan(0);
    }
    const normalized = model.normalizeGraph({
      nodes: [node('  literal  '), node(''), { ...node('bad-label'), label: {} },
        { ...node('bad-role'), role: 8 }, { ...node('bad-labels'), labels: ['ReifiedRelation', 1] },
        { ...node('bad-labels-shape'), labels: 'ReifiedRelation' }, node('x'.repeat(4097))], edges: [],
    });
    expect(normalized.nodes.map(n => n.id)).toEqual(['  literal  ']);
    expect(normalized.quarantined.nodes).toBe(6);
    expect(normalized.diagnostics).toHaveLength(6);
  });

  it('copies and freezes nested JSON, preserves sentinels, and reports bounded or non-JSON values', () => {
    const properties = freeze(JSON.parse('{"__proto__":{"safe":[null,true,2,"[redacted]"]},"nested":{"x":1}}'));
    const cycle: Record<string, unknown> = {};
    cycle.self = cycle;
    let getterCalls = 0;
    const accessor = Object.defineProperty({}, 'secret', { enumerable: true, get() { getterCalls++; return 9; } });
    const graph = freeze({ nodes: [{ ...node('a'), properties }], edges: [{ ...edge('e', 'a', 'a'), properties: '[truncated]' }] });
    const normalized = model.normalizeGraph(graph);
    expect(normalized.nodes[0].properties).toEqual(properties);
    expect(normalized.nodes[0].properties).not.toBe(properties);
    expect(Object.isFrozen((normalized.nodes[0].properties as Record<string, unknown>).__proto__)).toBe(true);
    expect(normalized.edges[0].properties).toBe('[truncated]');
    expect(normalized.edges[0].propertiesComplete).toBe(false);
    expect(normalized.diagnostics).toEqual([{ code: 'properties-truncated', kind: 'edge', index: 0, field: 'properties' }]);
    const malformed = model.normalizeGraph({ nodes: [node('a')], edges: [
      { ...edge('cycle', 'a', 'a'), properties: cycle },
      { ...edge('non-json', 'a', 'a'), properties: { inf: Infinity, undef: undefined, date: new Date(), bigint: 1n } },
      { ...edge('accessor', 'a', 'a'), properties: accessor },
      { ...edge('long', 'a', 'a'), properties: { text: 'x'.repeat(200_000) } },
      { ...edge('wide', 'a', 'a'), properties: Array.from({ length: 20_000 }, (_, i) => i) },
    ] });
    expect(getterCalls).toBe(0);
    expect(malformed.edges).toHaveLength(5);
    expect(malformed.edges.every(e => !e.propertiesComplete)).toBe(true);
    expect(malformed.diagnostics.length).toBeGreaterThanOrEqual(5);
    expect(JSON.stringify(malformed.edges).length).toBeLessThan(200_000);
  });

  it('reports entity capacity limits instead of silently exposing a potentially ambiguous prefix', () => {
    const result = model.normalizeGraph({ nodes: Array.from({ length: 10_001 }, (_, i) => node(String(i))), edges: [] });
    expect(result.returned.nodes).toBe(10_001);
    expect(result.quarantined.nodes).toBe(10_001);
    expect(result.nodes).toEqual([]);
    expect(result.diagnostics).toContainEqual({ code: 'entity-limit', kind: 'node', count: 10_001 });
  });

  it('diagnoses sparse collections and non-JSON keys without invoking array accessors', () => {
    const sparse = model.normalizeGraph({ nodes: new Array(1), edges: [] });
    expect(sparse.quarantined.nodes).toBe(1);
    expect(sparse.diagnostics).toContainEqual({ code: 'invalid-entity', kind: 'node', index: 0 });
    const labels = new Array(1);
    let calls = 0;
    const entities = [node('a')];
    Object.defineProperty(entities, '0', { get() { calls++; return node('unsafe'); } });
    const bad = model.normalizeGraph({ nodes: entities, edges: [] });
    expect(calls).toBe(0);
    expect(bad.nodes).toEqual([]);
    const malformedLabels = model.normalizeGraph({ nodes: [{ ...node('labels'), labels }], edges: [] });
    expect(malformedLabels.quarantined.nodes).toBe(1);
    const symbol = model.normalizeGraph({ nodes: [node('a')], edges: [{ ...edge('e', 'a', 'a'), properties: { [Symbol('hidden')]: 9 } }] });
    expect(symbol.edges[0].propertiesComplete).toBe(false);
    expect(symbol.diagnostics[0].code).toBe('invalid-properties');
  });

  it('bounds deeply nested properties and total work across many entities', () => {
    let properties: unknown = { leaf: true };
    for (let i = 0; i < 1000; i++) properties = { child: properties };
    const graph = model.normalizeGraph({ nodes: [node('a')], edges: [
      { ...edge('deep', 'a', 'a'), properties },
      ...Array.from({ length: 50 }, (_, i) => ({ ...edge(`wide-${i}`, 'a', 'a'), properties: Array.from({ length: 4000 }, () => 1) })),
    ] });
    expect(graph.edges).toHaveLength(51);
    expect(graph.edges[0].propertiesComplete).toBe(false);
    expect(graph.edges.at(-1)?.propertiesComplete).toBe(false);
    expect(graph.diagnostics.filter(d => d.code === 'properties-truncated').length).toBeGreaterThan(1);
    expect(JSON.stringify(graph.edges).length).toBeLessThan(300_000);
  });
});

describe('ordered graph projection', () => {
  const input = freeze({
    nodes: [node('a', 'object', 'Alpha'), node('b', 'object', 'Beta'), node('c', 'background', 'Gamma'),
      node('d', 'object', 'Delta'), node('__proto__', 'object', 'Literal [a-z]+ <script>')],
    edges: [edge('a', 'a', 'b', 'NEEDLE'), edge('context', 'a', 'b', 'other'),
      edge('bc', 'b', 'c', 'NEEDLE'), edge('cd', 'c', 'd', 'other')],
  });

  it('highlights literal matches without hiding and never searches property blobs', () => {
    const graph = model.normalizeGraph(input);
    const filters = model.createGraphFilters(graph);
    const result = model.projectGraph(graph, { ...filters, search: '[A-Z]+' }, { kind: 'node', id: '__proto__' });
    expect(result.nodes).toHaveLength(5);
    expect([...result.matchingNodeIds]).toEqual(['__proto__']);
    expect([...result.matchingEdgeIds]).toEqual([]);
    expect(result.selectionStatus).toBe('visible');
    expect(model.projectGraph(graph, { ...filters, search: '.*', matchesOnly: true }).nodes).toEqual([]);
    const properties = model.normalizeGraph({ nodes: [{ ...node('p'), properties: { text: 'unsearchable' } }], edges: [] });
    expect(model.projectGraph(properties, { ...model.createGraphFilters(properties), search: 'unsearchable', matchesOnly: true }).nodes).toEqual([]);
    expect(model.projectGraph(graph, { ...filters, allowedRoles: new Set() }).nodes).toEqual([]);
    expect(model.projectGraph(graph, { ...filters, allowedTypes: new Set() }).nodes).toHaveLength(5);
    expect(model.projectGraph(graph, { ...filters, allowedTypes: new Set() }).edges).toEqual([]);
  });

  it('brings matching-edge endpoints into an induced context graph with authoritative exclusions', () => {
    const graph = model.normalizeGraph(input);
    const filters = { ...model.createGraphFilters(graph), search: 'needle', matchesOnly: true };
    const result = model.projectGraph(graph, filters, { kind: 'node', id: 'd' });
    expect(result.nodes.map(n => n.id)).toEqual(['a', 'b', 'c']);
    expect(result.edges.map(e => e.id)).toEqual(['a', 'context', 'bc']);
    expect([...result.matchingNodeIds]).toEqual([]);
    expect([...result.matchingEdgeIds]).toEqual(['a', 'bc']);
    expect([...result.searchContextNodeIds]).toEqual(['a', 'b', 'c']);
    expect(result.selectionStatus).toBe('hidden');
    expect(result.counts).toMatchObject({ returnedNodes: 5, returnedEdges: 4, visibleNodes: 3, visibleEdges: 3, matchingNodes: 0, matchingEdges: 2 });
    const roleExcluded = model.projectGraph(graph, { ...filters, allowedRoles: new Set(['object']) });
    expect(roleExcluded.nodes.map(n => n.id)).toEqual(['a', 'b']);
    expect([...roleExcluded.matchingEdgeIds]).toEqual(['a']);
    const typeExcluded = model.projectGraph(graph, { ...filters, allowedTypes: new Set(['other']) });
    expect(typeExcluded.nodes).toEqual([]);
    expect(typeExcluded.edges).toEqual([]);
  });

  it('intersects one-hop loaded scope after search, distinguishes kinds, and supports explicit Reveal', () => {
    const graph = model.normalizeGraph(input);
    const filters = { ...model.createGraphFilters(graph), search: 'Delta', matchesOnly: true, neighborhood: true };
    const conflict = model.projectGraph(graph, filters, { kind: 'node', id: 'a' });
    expect(conflict.nodes).toEqual([]);
    expect(conflict.neighborhoodStatus).toBe('active');
    const nodeScope = model.projectGraph(graph, { ...filters, search: '' }, { kind: 'node', id: 'a' });
    expect(nodeScope.nodes.map(n => n.id)).toEqual(['a', 'b']);
    const edgeScope = model.projectGraph(graph, { ...filters, search: '' }, { kind: 'edge', id: 'a' });
    expect(edgeScope.nodes.map(n => n.id)).toEqual(['a', 'b', 'c']);
    const excluded = { ...filters, search: 'needle', allowedRoles: new Set(['object']) };
    expect(model.projectGraph(graph, excluded, { kind: 'node', id: 'c' }).neighborhoodStatus).toBe('excluded');
    expect(model.projectGraph(graph, excluded, { kind: 'node', id: 'c' }).nodes).toEqual([]);
    const excludedEdge = { ...filters, allowedTypes: new Set(['other']) };
    expect(model.projectGraph(graph, excludedEdge, { kind: 'edge', id: 'a' }).neighborhoodStatus).toBe('excluded');
    for (const previous of [filters, excluded, excludedEdge]) {
      const revealed = model.revealGraphFilters(graph, previous);
      expect(revealed.search).toBe(previous.search);
      expect(revealed.matchesOnly).toBe(false);
      expect(revealed.neighborhood).toBe(false);
      const result = model.projectGraph(graph, revealed, { kind: 'node', id: 'c' });
      expect(result.nodes).toHaveLength(5);
      expect(result.edges).toHaveLength(4);
      expect(result.selectionStatus).toBe('visible');
    }
    const removed = model.projectGraph(graph, { ...filters, search: '' }, { kind: 'edge', id: 'missing' });
    expect(removed.selectionStatus).toBe('removed');
    expect(removed.neighborhoodStatus).toBe('removed');
    expect(removed.nodes).toHaveLength(5);
    expect(model.projectGraph(graph, { ...filters, search: '' }, null).neighborhoodStatus).toBe('no-selection');
  });

  it('bounds the match list without changing direct counts or visible membership', () => {
    const graph = model.normalizeGraph({ nodes: Array.from({ length: 150 }, (_, i) => node(String(i))), edges: [] });
    const result = model.projectGraph(graph, { ...model.createGraphFilters(graph), search: 'same label', matchesOnly: true });
    expect(result.matches).toHaveLength(100);
    expect(result.matchesTruncated).toBe(true);
    expect(result.counts.matchingNodes).toBe(150);
    expect(result.nodes).toHaveLength(150);
    expect(result.matches[0]).toEqual({ kind: 'node', id: '0' });
  });
});

describe('semantic classification and identity', () => {
  it('classifies only authored reifier role and the exact persisted ReifiedRelation label', () => {
    const graph = model.normalizeGraph({ nodes: [
      node('authored', 'reifier'), node('persisted-role', 'ReifiedRelation'),
      { ...node('multi', 'Asset'), labels: ['Asset', 'ReifiedRelation'] },
      node('display-name', 'object', 'reifier ReifiedRelation'), node('substring', 'NotReifiedRelation'),
      { ...node('near-label'), labels: ['reifiedrelation', 'SomeReifiedRelation'] },
    ], edges: [] });
    expect(graph.nodes.map(model.isReifier)).toEqual([true, true, true, false, false, false]);
    expect(graph.nodeById.get('multi')?.labels).toEqual(['Asset', 'ReifiedRelation']);
    expect(Object.isFrozen(graph.nodeById.get('multi')?.labels)).toBe(true);
  });

  it.each([
    '[truncated]', 'preserved prefix[truncated]', '[truncated] suffix',
    { nested: [null, { text: 'prefix[truncated]' }] },
    { 'key[truncated]': 'preserved value' },
  ])('marks server truncation anywhere in properties as indeterminate without altering display: %j', properties => {
    const graph = model.normalizeGraph({ nodes: [node('a')], edges: [{ ...edge('relation:0', 'a', 'a'), properties }] });
    expect(graph.edges[0].properties).toEqual(properties);
    expect(graph.edges[0].propertiesComplete).toBe(false);
    expect(model.edgeSemanticIdentity(graph.edges[0])).toBeNull();
    expect(graph.diagnostics).toContainEqual({ code: 'properties-truncated', kind: 'edge', index: 0, field: 'properties' });
  });

  it('detects indexed edge-ID reuse by ordered endpoints, type and canonical bounded JSON properties', () => {
    const normalizedEdge = (properties: unknown, changes = {}) => model.normalizeGraph({
      nodes: [node('a'), node('b')], edges: [{ ...edge('relation:0', 'a', 'b'), properties, ...changes }],
    }).edges[0];
    const original = normalizedEdge({ a: 1, b: [null, { z: true, y: '[redacted]' }] });
    const reordered = normalizedEdge({ b: [null, { y: '[redacted]', z: true }], a: 1 });
    expect(model.edgeSemanticIdentity(original)).toBe(model.edgeSemanticIdentity(reordered));
    for (const changed of [
      normalizedEdge(original.properties, { source: 'b', target: 'a' }),
      normalizedEdge(original.properties, { label: 'under' }), normalizedEdge({ a: '1', b: [null] }),
      normalizedEdge(null), normalizedEdge('[truncated]'),
    ]) expect(model.edgeSemanticIdentity(changed)).not.toBe(model.edgeSemanticIdentity(original));
    expect(model.edgeSemanticIdentity(normalizedEdge('[truncated]'))).toBeNull();
    expect(model.edgeSemanticIdentity(normalizedEdge({ bad: undefined }))).toBeNull();
    expect(model.edgeSemanticIdentity(normalizedEdge('x'.repeat(200_000)))).toBeNull();
  });
});

describe('renderer boundary and deterministic layout', () => {
  const input = freeze({
    nodes: [node('a'), node('b'), node('c', 'reifier')],
    edges: [edge('parallel-z', 'a', 'b'), edge('parallel-a', 'a', 'b', 'under'), edge('reverse', 'b', 'a'),
      edge('loop-z', 'a', 'a'), edge('loop-a', 'a', 'a'), edge('single', 'b', 'c')],
  });

  it('assigns distinct stable physical lanes for parallel, reciprocal and loop edges', () => {
    const graph = model.normalizeGraph(input);
    const lanes = model.assignEdgeLanes(graph);
    const reverseOrder = model.normalizeGraph({ nodes: [...input.nodes].reverse(), edges: [...input.edges].reverse() });
    for (const e of graph.edges) expect(model.assignEdgeLanes(reverseOrder).get(e.id)).toEqual(lanes.get(e.id));
    const physicalCurvatures = graph.edges.filter(e => ['parallel-z', 'parallel-a', 'reverse'].includes(e.id))
      .map(e => lanes.get(e.id)!.curvature * (e.source < e.target ? 1 : -1));
    expect(new Set(physicalCurvatures).size).toBe(3);
    expect(lanes.get('single')?.curvature).toBe(0);
    for (const id of ['loop-a', 'loop-z']) {
      expect(lanes.get(id)?.isLoop).toBe(true);
      expect(lanes.get(id)!.curvature).toBeGreaterThan(0);
    }
    expect(lanes.get('loop-a')?.rotation).not.toBe(lanes.get('loop-z')?.rotation);
    expect([...lanes.values()].every(lane => Number.isFinite(lane.curvature) && Math.abs(lane.curvature) <= 1 && Number.isFinite(lane.rotation))).toBe(true);
  });

  it('creates independently mutable renderer DTOs with full-model lanes and no source property references', () => {
    const graph = model.normalizeGraph(input);
    const before = JSON.stringify(input);
    const filters = { ...model.createGraphFilters(graph), allowedTypes: new Set(['under']) };
    const projected = model.projectGraph(graph, filters);
    const dto = model.createRendererDTOs(graph, projected);
    const fresh = model.createRendererDTOs(graph, projected);
    expect(dto.nodes).toHaveLength(3);
    expect(dto.links.map(link => link.id)).toEqual(['parallel-a']);
    expect(dto.links[0].curvature).toBe(model.assignEdgeLanes(graph).get('parallel-a')?.curvature);
    expect(dto.nodes[2].isReifier).toBe(true);
    expect(dto.nodes[0]).not.toHaveProperty('properties');
    expect(dto.links[0]).not.toHaveProperty('properties');
    dto.links[0].source = dto.nodes[0];
    dto.links[0].target = dto.nodes[1];
    dto.nodes[0].x = 123;
    dto.nodes[0].fx = 123;
    dto.nodes.sort((a, b) => b.id.localeCompare(a.id));
    expect(fresh.links[0].source).toBe('a');
    expect(fresh.nodes[0].x).not.toBe(123);
    expect(graph.edgeById.get('parallel-a')?.source).toBe('a');
    expect(graph.nodeById.get('a')).not.toHaveProperty('x');
    expect(JSON.stringify(input)).toBe(before);
  });

  it('seeds finite layout positions by literal ID and scope independently of graph order', () => {
    expect(model.layoutSeed('a', 'scope')).toBe(model.layoutSeed('a', 'scope'));
    expect(model.layoutSeed('a', 'scope')).not.toBe(model.layoutSeed('a', 'other'));
    expect(model.layoutSeed('a:b', 'c')).not.toBe(model.layoutSeed('b', 'c:a'));
    const first = model.initialNodePosition('__proto__', 3, 'scope');
    expect(first).toEqual(model.initialNodePosition('__proto__', 3, 'scope'));
    expect(first).not.toEqual(model.initialNodePosition('other', 3, 'scope'));
    expect(Object.values(first).every(value => Number.isFinite(value) && Math.abs(value) <= 100)).toBe(true);
    expect(model.initialNodePosition('__proto__', 2, 'scope').z).toBe(0);
    const graph = model.normalizeGraph(input);
    const a = model.createRendererDTOs(graph, undefined, 3, 'scope');
    const reversed = model.createRendererDTOs(model.normalizeGraph({ nodes: [...input.nodes].reverse(), edges: input.edges }), undefined, 3, 'scope');
    expect(a.nodes.find(n => n.id === 'a')).toEqual(reversed.nodes.find(n => n.id === 'a'));
  });
});
