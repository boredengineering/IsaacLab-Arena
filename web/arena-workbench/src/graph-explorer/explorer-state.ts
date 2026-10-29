import { createGraphFilters, edgeSemanticIdentity, type GraphFilters, type GraphSelection, type NormalizedGraph } from './graph-model';
import type { GraphPresentation, GraphRendererHandle } from './renderer-contracts';
export type ExplorerMode = 'table' | '2d' | '3d';
export interface ExplorerTableState { kind: 'node' | 'edge'; sorting: { id: string; desc: boolean }[]; pagination: { pageIndex: number; pageSize: number } }
export const createTableState = (): ExplorerTableState => ({ kind: 'node', sorting: [{ id: 'id', desc: false }], pagination: { pageIndex: 0, pageSize: 25 } });
export interface ExplorerState {
  scopeKey: string;
  revisionKey: string;
  initialized: boolean;
  mode: ExplorerMode;
  table: ExplorerTableState;
  selection: GraphSelection;
  edgeIdentity: string | null;
  filters: GraphFilters;
  /** Scope-lifetime category history; retain absent categories so exclusions survive reappearance. */
  knownRoles: ReadonlySet<string>;
  knownTypes: ReadonlySet<string>;
  snapshots: Record<'2d' | '3d', GraphPresentation>;
  announcement: string;
  reducedMotion: boolean;
}
/** Restore the orbit reference direction using camera-only methods, preserving layout/pins. */
export function resetViewCamera(handle: Pick<GraphRendererHandle, 'fit' | 'orbit' | 'getSnapshot'>, mode: ExplorerMode) {
  handle.fit();
  if (mode !== '3d') return;
  const camera = handle.getSnapshot().camera;
  if (!camera?.position || !camera.target) return;
  const x = camera.position.x - camera.target.x, y = camera.position.y - camera.target.y, z = camera.position.z - camera.target.z;
  const radius = Math.hypot(x, y, z);
  if (![x, y, z, radius].every(Number.isFinite) || radius < 1e-6) return;
  handle.orbit(-Math.atan2(x, z), Math.acos(Math.max(-1, Math.min(1, y / radius))) - Math.PI / 2);
}
const emptyGraph = { nodes: [], edges: [] } as unknown as NormalizedGraph;
/** Strip renderer-owned objects and extra fields; only current finite coordinates cross the boundary. */
export function copyPresentation(snapshot: GraphPresentation, graph: NormalizedGraph): GraphPresentation {
  const position = (p: { x: number; y: number; z: number } | undefined) => p && [p.x, p.y, p.z].every(Number.isFinite) ? { x: p.x, y: p.y, z: p.z } : undefined;
  const positions: GraphPresentation['positions'] = new Map();
  for (const [id, raw] of snapshot.positions) { const p = position(raw); if (p && graph.nodeById.has(id)) positions.set(id, p); }
  const camera: NonNullable<GraphPresentation['camera']> = {};
  if (snapshot.camera?.center && [snapshot.camera.center.x, snapshot.camera.center.y].every(Number.isFinite)) camera.center = { x: snapshot.camera.center.x, y: snapshot.camera.center.y };
  if (Number.isFinite(snapshot.camera?.zoom)) camera.zoom = snapshot.camera!.zoom;
  const cameraPosition = position(snapshot.camera?.position), target = position(snapshot.camera?.target);
  if (cameraPosition) camera.position = cameraPosition;
  if (target) camera.target = target;
  return { positions, pins: new Set([...snapshot.pins].filter(id => graph.nodeById.has(id))), frozen: snapshot.frozen === true, ...(Object.keys(camera).length ? { camera } : {}) };
}
export function createExplorerState(scopeKey: string, revisionKey: string, graph: NormalizedGraph | null, reducedMotion = false): ExplorerState {
  const snapshot = (): GraphPresentation => ({ positions: new Map(), pins: new Set(), frozen: reducedMotion });
  const filters = createGraphFilters(graph ?? emptyGraph);
  return { scopeKey, revisionKey, initialized: graph !== null, mode: '2d', table: createTableState(), selection: null, edgeIdentity: null,
    filters, knownRoles: filters.allowedRoles, knownTypes: filters.allowedTypes,
    snapshots: { '2d': snapshot(), '3d': snapshot() }, announcement: '', reducedMotion };
}
/** Explicit Clear/Reveal restores All intent, including absent and future categories. */
export function resetExplorerFilters(state: ExplorerState, graph: NormalizedGraph, preserveSearch = false): ExplorerState {
  const filters = { ...createGraphFilters(graph), search: preserveSearch ? state.filters.search : '' };
  return { ...state, filters, knownRoles: filters.allowedRoles, knownTypes: filters.allowedTypes };
}
export function selectEntity(state: ExplorerState, graph: NormalizedGraph, selection: GraphSelection): ExplorerState {
  const entity = selection && (selection.kind === 'node' ? graph.nodeById.get(selection.id) : graph.edgeById.get(selection.id));
  if (selection && !entity) return state;
  return { ...state, selection, edgeIdentity: selection?.kind === 'edge' ? edgeSemanticIdentity(graph.edgeById.get(selection.id)!) : null,
    filters: selection ? state.filters : { ...state.filters, neighborhood: false }, announcement: entity ? `Selected ${selection!.kind}: ${entity.label}` : 'Selection cleared.' };
}
export function reconcileExplorerState(state: ExplorerState, scopeKey: string, revisionKey: string, graph: NormalizedGraph | null): ExplorerState {
  if (scopeKey !== state.scopeKey) return createExplorerState(scopeKey, revisionKey, graph, state.reducedMotion);
  if (!graph || (state.initialized && revisionKey === state.revisionKey)) return state;
  let selection = state.selection;
  if (selection?.kind === 'node' && !graph.nodeById.has(selection.id)) selection = null;
  if (selection?.kind === 'edge') {
    const edge = graph.edgeById.get(selection.id);
    if (!edge || state.edgeIdentity === null || edgeSemanticIdentity(edge) !== state.edgeIdentity) selection = null;
  }
  const reconcile = (snapshot: GraphPresentation): GraphPresentation => ({ ...snapshot,
    positions: new Map([...snapshot.positions].filter(([id]) => graph.nodeById.has(id))),
    pins: new Set([...snapshot.pins].filter(id => graph.nodeById.has(id))) });
  const categories = createGraphFilters(graph);
  // New categories default to allowed; exclusions of known categories persist, even
  // through absence. Explicit empty allowsets mean None, never All. Filter updates
  // must replace sets (GraphFilters is readonly): only untouched default sets share
  // the history reference, distinguishing default All on an empty graph from None.
  const reconcileAllowed = (allowed: ReadonlySet<string>, known: ReadonlySet<string>, current: ReadonlySet<string>) => {
    const history = state.initialized ? new Set([...known, ...current]) : current;
    const next = !state.initialized || allowed === known ? history : allowed.size === 0 ? allowed
      : new Set([...allowed, ...[...current].filter(category => !known.has(category))]);
    return { allowed: next, known: history };
  };
  const roles = reconcileAllowed(state.filters.allowedRoles, state.knownRoles, categories.allowedRoles);
  const types = reconcileAllowed(state.filters.allowedTypes, state.knownTypes, categories.allowedTypes);
  return { ...state, revisionKey, initialized: true, selection, edgeIdentity: selection?.kind === 'edge' ? state.edgeIdentity : null,
    filters: !state.initialized ? categories : { ...state.filters,
      allowedRoles: roles.allowed,
      allowedTypes: types.allowed,
      neighborhood: selection ? state.filters.neighborhood : false },
    knownRoles: roles.known, knownTypes: types.known,
    snapshots: { '2d': reconcile(state.snapshots['2d']), '3d': reconcile(state.snapshots['3d']) },
    announcement: state.selection && !selection ? 'Selection cleared: entity removed or relationship identity changed.' : state.announcement };
}
