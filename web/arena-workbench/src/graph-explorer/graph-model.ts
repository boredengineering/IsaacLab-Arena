import type { GraphEdge, GraphNode, JSONValue } from '../editor-contracts';

export type { JSONValue } from '../editor-contracts';
export type GraphSelection = { kind: 'node' | 'edge'; id: string } | null;
export type DisplayNode = Readonly<GraphNode>;
export interface DisplayEdge extends Readonly<GraphEdge> {
  /** False means semantic identity cannot safely be retained across revisions. */
  readonly propertiesComplete: boolean;
}
export interface GraphDiagnostic {
  readonly code: string;
  readonly kind: 'graph' | 'node' | 'edge';
  readonly index?: number;
  readonly field?: string;
  readonly count?: number;
}
export interface NormalizedGraph {
  readonly nodes: readonly DisplayNode[];
  readonly edges: readonly DisplayEdge[];
  readonly nodeById: ReadonlyMap<string, DisplayNode>;
  readonly edgeById: ReadonlyMap<string, DisplayEdge>;
  readonly incidentEdges: ReadonlyMap<string, readonly DisplayEdge[]>;
  readonly diagnostics: readonly GraphDiagnostic[];
  readonly returned: Readonly<{ nodes: number; edges: number }>;
  readonly quarantined: Readonly<{ nodes: number; edges: number }>;
}

/** Defensive frontend budgets, not backend/query limits. Overflow is always diagnosed. */
export const GRAPH_LIMITS = Object.freeze({
  nodes: 10_000, edges: 20_000, fieldLength: 4096, labels: 128,
  propertyDepth: 24, propertyValues: 4096, propertyCharacters: 131_072,
  totalPropertyValues: 100_000, totalPropertyCharacters: 2_097_152,
  searchResults: 100,
});

function isRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

// Reading unknown JSON must not invoke accessors or inherit prototype fields.
function own(value: object, key: string): unknown {
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  return descriptor && 'value' in descriptor ? descriptor.value : undefined;
}

function validField(value: unknown, identity = false): value is string {
  return typeof value === 'string' && value.length <= GRAPH_LIMITS.fieldLength && (!identity || value.length > 0);
}

interface PropertyBudget { values: number; characters: number }

function copyProperties(input: unknown, budget: PropertyBudget) {
  let values = GRAPH_LIMITS.propertyValues;
  let characters = GRAPH_LIMITS.propertyCharacters;
  const issues = new Set<'invalid-properties' | 'properties-truncated'>();
  const ancestors = new Set<object>();
  const invalid = () => { issues.add('invalid-properties'); return '[invalid]' as const; };
  const truncated = () => { issues.add('properties-truncated'); return '[truncated]' as const; };
  const takeCharacters = (length: number) => {
    if (length > characters || length > budget.characters) return false;
    characters -= length;
    budget.characters -= length;
    return true;
  };
  const visit = (value: unknown, depth: number): JSONValue => {
    if (depth > GRAPH_LIMITS.propertyDepth || values-- <= 0 || budget.values-- <= 0) return truncated();
    if (value === null || typeof value === 'boolean') return value;
    if (typeof value === 'number') return Number.isFinite(value) ? value : invalid();
    if (typeof value === 'string') {
      if (!takeCharacters(value.length)) return truncated();
      // Server truncation is already lossy, including appended/nested markers.
      // Preserve display text, but never equate two lossy indexed-edge identities.
      if (value.includes('[truncated]')) issues.add('properties-truncated');
      return value;
    }
    if (!Array.isArray(value) && !isRecord(value)) return invalid();
    if (ancestors.has(value)) return invalid();
    if (Object.getOwnPropertySymbols(value).length) issues.add('invalid-properties');
    ancestors.add(value);
    let result: JSONValue;
    if (Array.isArray(value)) {
      const children: JSONValue[] = [];
      for (let i = 0; i < value.length; i++) {
        if (values <= 0 || budget.values <= 0) { children.push(truncated()); break; }
        children.push(visit(own(value, String(i)), depth + 1));
      }
      result = Object.freeze(children);
    } else {
      const children: Record<string, JSONValue> = Object.create(null);
      result = children;
      for (const key in value) {
        if (!Object.hasOwn(value, key)) continue;
        if (values <= 0 || budget.values <= 0 || !takeCharacters(key.length)) { result = truncated(); break; }
        if (key.includes('[truncated]')) issues.add('properties-truncated');
        children[key] = visit(own(value, key), depth + 1);
      }
      Object.freeze(children);
    }
    ancestors.delete(value);
    return result;
  };
  const properties = visit(input, 0);
  return { properties, complete: issues.size === 0, issues };
}

/** Validate an API Graph from unknown JSON and retain immutable display data only. */
export function normalizeGraph(input: unknown): NormalizedGraph {
  const diagnostics: GraphDiagnostic[] = [];
  const graph = isRecord(input) ? input : {};
  if (!isRecord(input)) diagnostics.push({ code: 'invalid-graph', kind: 'graph' });
  const arrays = (key: 'nodes' | 'edges', kind: 'node' | 'edge') => {
    const value = own(graph, key);
    if (!Array.isArray(value)) {
      diagnostics.push({ code: 'invalid-array', kind: 'graph', field: key });
      return { items: [] as unknown[], count: 0 };
    }
    if (value.length > GRAPH_LIMITS[key]) {
      // Do not accept a prefix: a duplicate in the unexamined tail could alias an accepted ID.
      diagnostics.push({ code: 'entity-limit', kind, count: value.length });
      return { items: [] as unknown[], count: value.length };
    }
    return { items: Array.from({ length: value.length }, (_, index) => own(value, String(index))), count: value.length };
  };
  const rawNodes = arrays('nodes', 'node');
  const rawEdges = arrays('edges', 'edge');
  const budget = { values: GRAPH_LIMITS.totalPropertyValues, characters: GRAPH_LIMITS.totalPropertyCharacters };
  const validate = (items: unknown[], kind: 'node' | 'edge') => {
    const counts = new Map<string, number>();
    for (const item of items) {
      const id = isRecord(item) ? own(item, 'id') : undefined;
      if (validField(id, true)) counts.set(id, (counts.get(id) ?? 0) + 1);
    }
    const accepted: { value: Record<string, unknown>; index: number }[] = [];
    items.forEach((item, index) => {
      if (!isRecord(item)) { diagnostics.push({ code: 'invalid-entity', kind, index }); return; }
      let valid = true;
      const fields = kind === 'node' ? ['id', 'label', 'role'] : ['id', 'label', 'source', 'target'];
      for (const field of fields) {
        if (!validField(own(item, field), field === 'id' || field === 'source' || field === 'target')) {
          diagnostics.push({ code: 'invalid-field', kind, index, field }); valid = false;
        }
      }
      if ((counts.get(own(item, 'id') as string) ?? 0) > 1) {
        diagnostics.push({ code: 'duplicate-id', kind, index, field: 'id' }); valid = false;
      }
      if (kind === 'node' && Object.hasOwn(item, 'labels')) {
        const labels = own(item, 'labels');
        if (!Array.isArray(labels) || labels.length > GRAPH_LIMITS.labels
          || !Array.from({ length: labels.length }, (_, i) => own(labels, String(i))).every(label => validField(label, true))) {
          diagnostics.push({ code: 'invalid-field', kind, index, field: 'labels' }); valid = false;
        }
      }
      if (valid) accepted.push({ value: item, index });
    });
    return accepted;
  };
  const propertiesFor = (value: Record<string, unknown>, kind: 'node' | 'edge', index: number) => {
    const result = copyProperties(own(value, 'properties'), budget);
    for (const code of result.issues) diagnostics.push({ code, kind, index, field: 'properties' });
    return result;
  };
  const nodes: DisplayNode[] = validate(rawNodes.items, 'node').map(({ value, index }) => {
    const labels = own(value, 'labels') as string[] | undefined;
    return Object.freeze({
      id: own(value, 'id') as string, label: own(value, 'label') as string, role: own(value, 'role') as string,
      ...(labels ? { labels: Object.freeze([...labels]) } : {}),
      properties: propertiesFor(value, 'node', index).properties,
    });
  });
  const nodeById = new Map(nodes.map(node => [node.id, node]));
  const edges: DisplayEdge[] = [];
  for (const { value, index } of validate(rawEdges.items, 'edge')) {
    const source = own(value, 'source') as string;
    const target = own(value, 'target') as string;
    if (!nodeById.has(source) || !nodeById.has(target)) {
      diagnostics.push({ code: 'dangling-endpoint', kind: 'edge', index }); continue;
    }
    const { properties, complete } = propertiesFor(value, 'edge', index);
    edges.push(Object.freeze({ id: own(value, 'id') as string, label: own(value, 'label') as string,
      source, target, properties, propertiesComplete: complete }));
  }
  const edgeById = new Map(edges.map(edge => [edge.id, edge]));
  const incidentEdges = new Map<string, DisplayEdge[]>(nodes.map(node => [node.id, []]));
  for (const edge of edges) {
    incidentEdges.get(edge.source)!.push(edge);
    if (edge.source !== edge.target) incidentEdges.get(edge.target)!.push(edge);
  }
  incidentEdges.forEach(Object.freeze);
  return Object.freeze({
    nodes: Object.freeze(nodes), edges: Object.freeze(edges), nodeById, edgeById, incidentEdges,
    diagnostics: Object.freeze(diagnostics.map(diagnostic => Object.freeze(diagnostic))),
    returned: Object.freeze({ nodes: rawNodes.count, edges: rawEdges.count }),
    quarantined: Object.freeze({ nodes: rawNodes.count - nodes.length, edges: rawEdges.count - edges.length }),
  });
}

/** Exact authored role / persisted schema label; never classify from display text. */
export function isReifier(node: DisplayNode): boolean {
  return node.role === 'reifier' || node.role === 'ReifiedRelation' || (node.labels?.includes('ReifiedRelation') ?? false);
}

function canonicalJSON(value: JSONValue): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJSON).join(',')}]`;
  const record = value as { readonly [key: string]: JSONValue };
  return `{${Object.keys(record).sort().map(key => `${JSON.stringify(key)}:${canonicalJSON(record[key])}`).join(',')}}`;
}

/**
 * Compare this only for the same edge ID in two normalized revisions. Null means
 * server truncation or normalization lost information: clear selection, never
 * treat two nulls as equal. Literal truncation markers are conservative false positives.
 * Canonicalize bounded per-entity JSON, not a graph/deep-stringify on each search.
 * This token contains properties and must stay in memory, never logs/URLs/storage.
 */
export function edgeSemanticIdentity(edge: DisplayEdge): string | null {
  return edge.propertiesComplete ? canonicalJSON([edge.source, edge.target, edge.label, edge.properties]) : null;
}

export interface EdgeLane {
  readonly laneIndex: number;
  readonly count: number;
  /** Engine-relative signed curvature; reverse endpoints reverse the physical side. */
  readonly curvature: number;
  /** Loop-plane rotation in radians (also usable by a 3D adapter). */
  readonly rotation: number;
  readonly isLoop: boolean;
}

/** Compute from the entire normalized graph, never the filtered edge list. */
export function assignEdgeLanes(graph: Pick<NormalizedGraph, 'edges'>): ReadonlyMap<string, EdgeLane> {
  const groups = new Map<string, DisplayEdge[]>();
  for (const edge of graph.edges) {
    const endpoints = edge.source <= edge.target ? [edge.source, edge.target] : [edge.target, edge.source];
    const key = JSON.stringify(endpoints);
    const group = groups.get(key) ?? [];
    group.push(edge);
    groups.set(key, group);
  }
  const lanes = new Map<string, EdgeLane>();
  for (const group of groups.values()) {
    group.sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
    group.forEach((edge, index) => {
      const count = group.length;
      const isLoop = edge.source === edge.target;
      const canonicalCurvature = count === 1 ? 0 : (index - (count - 1) / 2) * Math.min(0.28, 1.6 / (count - 1));
      const curvature = isLoop ? 0.6 + 0.35 * index / count : canonicalCurvature * (edge.source < edge.target ? 1 : -1);
      lanes.set(edge.id, Object.freeze({ laneIndex: index, count, isLoop, curvature: curvature || 0, rotation: isLoop ? 2 * Math.PI * index / count : 0 }));
    });
  }
  return lanes;
}

export interface LayoutPosition { x: number; y: number; z: number }

/** Non-cryptographic deterministic seed for display only, never semantic identity. */
export function layoutSeed(id: string, scopeKey = ''): number {
  let hash = 2166136261;
  const text = JSON.stringify([scopeKey, id]);
  for (let i = 0; i < text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 16777619);
  return hash >>> 0;
}

export function initialNodePosition(id: string, dimensions: 2 | 3 = 2, scopeKey = ''): LayoutPosition {
  let seed = layoutSeed(id, scopeKey);
  const coordinate = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return (seed / 4294967296 - 0.5) * 200;
  };
  return { x: coordinate(), y: coordinate(), z: dimensions === 3 ? coordinate() : 0 };
}

export interface RendererNode extends LayoutPosition {
  id: string; label: string; role: string; isReifier: boolean;
  index?: number; vx?: number; vy?: number; vz?: number;
  fx?: number | null; fy?: number | null; fz?: number | null;
}
export interface RendererLink extends EdgeLane {
  id: string; label: string;
  source: string | RendererNode;
  target: string | RendererNode;
  index?: number;
}
export interface RendererDTOs { nodes: RendererNode[]; links: RendererLink[] }

/** Fresh mutable engine objects; properties and original endpoint references never cross this boundary. */
export function createRendererDTOs(
  graph: NormalizedGraph,
  projection: Pick<GraphProjection, 'nodes' | 'edges'> = graph,
  dimensions: 2 | 3 = 2,
  scopeKey = '',
): RendererDTOs {
  const lanes = assignEdgeLanes(graph);
  return {
    nodes: projection.nodes.map(node => ({ id: node.id, label: node.label, role: node.role,
      isReifier: isReifier(node), ...initialNodePosition(node.id, dimensions, scopeKey) })),
    links: projection.edges.map(edge => ({ id: edge.id, label: edge.label, source: edge.source, target: edge.target, ...lanes.get(edge.id)! })),
  };
}

export interface GraphFilters {
  readonly allowedRoles: ReadonlySet<string>;
  readonly allowedTypes: ReadonlySet<string>;
  readonly search: string;
  readonly matchesOnly: boolean;
  readonly neighborhood: boolean;
}
export interface GraphProjection {
  readonly nodes: readonly DisplayNode[];
  readonly edges: readonly DisplayEdge[];
  readonly nodeIds: ReadonlySet<string>;
  readonly edgeIds: ReadonlySet<string>;
  /** Direct text matches within the role/type-allowed base graph, before neighborhood intersection. */
  readonly matchingNodeIds: ReadonlySet<string>;
  readonly matchingEdgeIds: ReadonlySet<string>;
  readonly searchContextNodeIds: ReadonlySet<string>;
  readonly matches: readonly Exclude<GraphSelection, null>[];
  readonly matchesTruncated: boolean;
  readonly selectionStatus: 'none' | 'visible' | 'hidden' | 'removed';
  readonly neighborhoodStatus: 'off' | 'active' | 'excluded' | 'no-selection' | 'removed';
  readonly counts: Readonly<{
    returnedNodes: number; returnedEdges: number; validNodes: number; validEdges: number;
    baseNodes: number; baseEdges: number; visibleNodes: number; visibleEdges: number;
    matchingNodes: number; matchingEdges: number;
  }>;
}

/** Empty allowed sets deliberately mean no entities; use this helper for All/Clear filters. */
export function createGraphFilters(graph: NormalizedGraph): GraphFilters {
  return {
    allowedRoles: new Set(graph.nodes.map(node => node.role)),
    allowedTypes: new Set(graph.edges.map(edge => edge.label)),
    search: '', matchesOnly: false, neighborhood: false,
  };
}

export function revealGraphFilters(graph: NormalizedGraph, filters: GraphFilters): GraphFilters {
  return { ...createGraphFilters(graph), search: filters.search };
}

/** Plan §5.5: allowed base → search endpoint union → one-hop intersection → induced edges. */
export function projectGraph(graph: NormalizedGraph, filters: GraphFilters, selection: GraphSelection = null): GraphProjection {
  const baseNodes = graph.nodes.filter(node => filters.allowedRoles.has(node.role));
  const baseNodeIds = new Set(baseNodes.map(node => node.id));
  const baseEdges = graph.edges.filter(edge => filters.allowedTypes.has(edge.label) && baseNodeIds.has(edge.source) && baseNodeIds.has(edge.target));
  const baseEdgeIds = new Set(baseEdges.map(edge => edge.id));
  // Do not truncate an oversized query into a different literal search.
  const query = filters.search.length <= GRAPH_LIMITS.fieldLength ? filters.search.toLowerCase() : null;
  const matchesText = (...fields: string[]) => !!query && fields.some(field => field.toLowerCase().includes(query));
  const matchingNodeIds = new Set(baseNodes.filter(node => matchesText(node.id, node.label, node.role)).map(node => node.id));
  const matchingEdgeIds = new Set(baseEdges.filter(edge => matchesText(edge.id, edge.label)).map(edge => edge.id));
  const searchNodeIds = !filters.matchesOnly || filters.search === '' ? new Set(baseNodeIds) : new Set(matchingNodeIds);
  const contextCandidates = new Set<string>();
  for (const edge of baseEdges) {
    if (matchingEdgeIds.has(edge.id)) {
      searchNodeIds.add(edge.source); searchNodeIds.add(edge.target);
      if (!matchingNodeIds.has(edge.source)) contextCandidates.add(edge.source);
      if (!matchingNodeIds.has(edge.target)) contextCandidates.add(edge.target);
    }
  }
  const selectedExists = selection !== null && (selection.kind === 'node' ? graph.nodeById.has(selection.id) : graph.edgeById.has(selection.id));
  let neighborhoodStatus: GraphProjection['neighborhoodStatus'] = 'off';
  let neighborhoodIds = baseNodeIds;
  if (filters.neighborhood) {
    if (!selection) neighborhoodStatus = 'no-selection';
    else if (!selectedExists) neighborhoodStatus = 'removed';
    else {
      neighborhoodIds = new Set<string>();
      const allowed = selection.kind === 'node' ? baseNodeIds.has(selection.id) : baseEdgeIds.has(selection.id);
      neighborhoodStatus = allowed ? 'active' : 'excluded';
      if (allowed) {
        const selectedEdge = selection.kind === 'edge' ? graph.edgeById.get(selection.id)! : null;
        const seeds = new Set(selectedEdge ? [selectedEdge.source, selectedEdge.target] : [selection.id]);
        seeds.forEach(id => neighborhoodIds.add(id));
        for (const edge of baseEdges) {
          if (seeds.has(edge.source) || seeds.has(edge.target)) {
            neighborhoodIds.add(edge.source); neighborhoodIds.add(edge.target);
          }
        }
      }
    }
  }
  const nodes = baseNodes.filter(node => searchNodeIds.has(node.id) && neighborhoodIds.has(node.id));
  const nodeIds = new Set(nodes.map(node => node.id));
  const edges = baseEdges.filter(edge => nodeIds.has(edge.source) && nodeIds.has(edge.target));
  const edgeIds = new Set(edges.map(edge => edge.id));
  const selectionStatus = !selection ? 'none' : !selectedExists ? 'removed'
    : (selection.kind === 'node' ? nodeIds.has(selection.id) : edgeIds.has(selection.id)) ? 'visible' : 'hidden';
  const matches: Exclude<GraphSelection, null>[] = [];
  for (const id of matchingNodeIds) {
    if (matches.length >= GRAPH_LIMITS.searchResults) break;
    matches.push(Object.freeze({ kind: 'node', id }));
  }
  for (const id of matchingEdgeIds) {
    if (matches.length >= GRAPH_LIMITS.searchResults) break;
    matches.push(Object.freeze({ kind: 'edge', id }));
  }
  return Object.freeze({
    nodes: Object.freeze(nodes), edges: Object.freeze(edges), nodeIds, edgeIds, matchingNodeIds, matchingEdgeIds,
    searchContextNodeIds: new Set(nodes.filter(node => contextCandidates.has(node.id)).map(node => node.id)),
    matches: Object.freeze(matches), matchesTruncated: matchingNodeIds.size + matchingEdgeIds.size > matches.length,
    selectionStatus, neighborhoodStatus,
    counts: Object.freeze({
      returnedNodes: graph.returned.nodes, returnedEdges: graph.returned.edges,
      validNodes: graph.nodes.length, validEdges: graph.edges.length, baseNodes: baseNodes.length, baseEdges: baseEdges.length,
      visibleNodes: nodes.length, visibleEdges: edges.length, matchingNodes: matchingNodeIds.size, matchingEdges: matchingEdgeIds.size,
    }),
  });
}
