import { createRendererDTOs, initialNodePosition, type GraphProjection, type LayoutPosition, type NormalizedGraph } from './graph-model';
import type { GraphPresentation } from './renderer-contracts';
import type { RendererNode, RendererLink } from './graph-model';
export type SimulationNode = Omit<RendererNode, 'fx'|'fy'|'fz'> & {fx?:number;fy?:number;fz?:number};
export type SimulationLink = Omit<RendererLink, 'source'|'target'> & {source:string|SimulationNode;target:string|SimulationNode};
export interface SimulationData {nodes:SimulationNode[];links:SimulationLink[]}

export function validPosition(p: LayoutPosition): boolean {
  return [p.x, p.y, p.z].every(n => Number.isFinite(n) && Math.abs(n) <= 1_000_000);
}

/** Mutable layout ownership; no force-engine references leave snapshot(). */
export class RendererState {
  data: SimulationData = { nodes: [], links: [] };
  private positions = new Map<string, LayoutPosition>();
  readonly pins = new Set<string>();
  frozen: boolean;
  constructor(readonly dimensions: 2 | 3, readonly scopeKey: string, snapshot: GraphPresentation) {
    this.frozen = snapshot.frozen;
    snapshot.positions.forEach((p, id) => { if (validPosition(p)) this.positions.set(id, { ...p, z: dimensions === 2 ? 0 : p.z }); });
    snapshot.pins.forEach(id => this.pins.add(id));
  }
  private remember() {
    this.data.nodes.forEach(n => { if (validPosition(n)) this.positions.set(n.id, { x: n.x, y: n.y, z: this.dimensions === 2 ? 0 : n.z }); });
  }
  private constrain() {
    this.data.nodes.forEach(n => {
      n.vx = n.vy = n.vz = 0;
      if (this.frozen || this.pins.has(n.id)) { n.fx = n.x; n.fy = n.y; n.fz = n.z; }
      else { delete n.fx; delete n.fy; delete n.fz; }
    });
  }
  private graph?: NormalizedGraph;
  private membership = '';
  reconcile(graph: NormalizedGraph, projection: GraphProjection) {
    // Selection and search metadata do not own the force engine's mutable DTOs.
    const membership = JSON.stringify([projection.nodes.map(n=>n.id).sort(), projection.edges.map(e=>e.id).sort()]);
    if (this.graph === graph && this.membership === membership) return this.data;
    this.graph = graph; this.membership = membership;
    this.remember();
    for (const id of this.positions.keys()) if (!graph.nodeById.has(id)) this.positions.delete(id);
    for (const id of this.pins) if (!graph.nodeById.has(id)) this.pins.delete(id);
    const dto = createRendererDTOs(graph, projection, this.dimensions, this.scopeKey);
    this.data = {
      nodes: dto.nodes.map(({fx,fy,fz,...node}) => ({...node,...(typeof fx==='number'?{fx}:{}),...(typeof fy==='number'?{fy}:{}),...(typeof fz==='number'?{fz}:{})})),
      links: dto.links.map(link => ({...link,source:typeof link.source==='string'?link.source:link.source.id,target:typeof link.target==='string'?link.target:link.target.id})),
    };
    this.data.nodes.forEach(n => Object.assign(n, this.positions.get(n.id) ?? {}));
    this.constrain();
    this.remember();
    return this.data;
  }
  setFrozen(value: boolean) { this.frozen = value; this.constrain(); }
  setPinned(id: string, value: boolean) {
    if (value) this.pins.add(id); else this.pins.delete(id);
    this.constrain();
  }
  unpinAll() { this.pins.clear(); this.constrain(); }
  move(id: string, position: LayoutPosition): boolean {
    const n = this.data.nodes.find(node => node.id === id);
    if (!n) return false;
    if (!validPosition(position)) {
      // The force engine mutates the DTO before invoking drag-end. Rejection
      // must repair that mutation, not just refuse to publish it.
      if (!validPosition(n)) Object.assign(n,this.positions.get(id) ?? initialNodePosition(id,this.dimensions,this.scopeKey));
      this.constrain();
      return false;
    }
    Object.assign(n, { x: position.x, y: position.y, z: this.dimensions === 2 ? 0 : position.z });
    this.positions.set(id,{x:n.x,y:n.y,z:n.z});
    this.pins.add(id);
    this.constrain();
    return true;
  }
  reset() {
    this.pins.clear();
    this.positions.clear();
    this.data.nodes.forEach(n => Object.assign(n, initialNodePosition(n.id, this.dimensions, this.scopeKey)));
    this.constrain();
  }
  snapshot(): GraphPresentation {
    this.remember();
    return { positions: new Map([...this.positions].map(([id, p]) => [id, { ...p }])), pins: new Set(this.pins), frozen: this.frozen };
  }
}
