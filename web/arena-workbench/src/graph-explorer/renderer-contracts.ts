import type { GraphProjection, GraphSelection, LayoutPosition, NormalizedGraph } from './graph-model';

/** Presentation-only state, scoped to one graph surface and dimension. Never persist it. */
export interface GraphPresentation {
  positions: Map<string, LayoutPosition>;
  pins: Set<string>;
  frozen: boolean;
  camera?: {
    center?: { x: number; y: number };
    zoom?: number;
    position?: LayoutPosition;
    target?: LayoutPosition;
  };
}
export interface GraphRendererHandle {
  fit(ids?: readonly string[]): void;
  zoom(factor: number): void;
  pan(dx: number, dy: number): void;
  orbit(yaw: number, pitch: number): void;
  reset(): void;
  setFrozen(value: boolean): void;
  setPinned(id: string, value: boolean): void;
  unpinAll(): void;
  moveNode(id: string, position: LayoutPosition): void;
  nudgeNode(id: string, dx: number, dy: number, dz?: number): void;
  getSnapshot(): GraphPresentation;
}
export interface GraphRendererProps {
  graph: NormalizedGraph;
  projection: GraphProjection;
  scopeKey: string;
  snapshot: GraphPresentation;
  selection: GraphSelection;
  labels: 'selected' | 'auto' | 'all';
  onSelect(selection: GraphSelection): void;
  onReady(handle: GraphRendererHandle | null): void;
  onSnapshot(snapshot: GraphPresentation): void;
  onError(message: string): void;
}
