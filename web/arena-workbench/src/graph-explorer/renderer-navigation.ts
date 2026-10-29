import { layoutSeed, type GraphSelection, type LayoutPosition, type NormalizedGraph } from './graph-model';
import { validPosition } from './renderer-state';
// Camera coordinates are not node layout coordinates: fitting the supported
// ±1e6 cube necessarily places the camera outside that cube.
export const validCameraPosition=(p:LayoutPosition)=>[p.x,p.y,p.z].every(Number.isFinite);
export interface Camera3D { position: LayoutPosition; target: LayoutPosition }
const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(max, n));
// Supports fitting the full ±1e6 layout range even in the minimum-size surface.
export const MIN_LAYOUT_ZOOM = 1e-6;
export const boundedZoom = (n: number) => clamp(n, MIN_LAYOUT_ZOOM, 20);
const subtract = (a: LayoutPosition, b: LayoutPosition): LayoutPosition => ({ x: a.x-b.x, y:a.y-b.y, z:a.z-b.z });
const cross = (a: LayoutPosition, b: LayoutPosition): LayoutPosition => ({x:a.y*b.z-a.z*b.y,y:a.z*b.x-a.x*b.z,z:a.x*b.y-a.y*b.x});
const unit = (v: LayoutPosition): LayoutPosition => { const d = Math.hypot(v.x,v.y,v.z) || 1; return {x:v.x/d,y:v.y/d,z:v.z/d}; };
export function fitCamera(points: readonly LayoutPosition[], camera: Camera3D, width: number, height: number, fov: number): Camera3D | null {
  const finite = points.filter(validPosition);
  if (!finite.length || ![width,height,fov].every(Number.isFinite) || width<=0 || height<=0 || fov<=0 || fov>=180) return null;
  const bounds = (axis: 'x'|'y'|'z') => [Math.min(...finite.map(p=>p[axis])),Math.max(...finite.map(p=>p[axis]))];
  const x=bounds('x'),y=bounds('y'),z=bounds('z');
  const target={x:(x[0]+x[1])/2,y:(y[0]+y[1])/2,z:(z[0]+z[1])/2};
  const radius=Math.max(40,...finite.map(p=>Math.hypot(p.x-target.x,p.y-target.y,p.z-target.z)+35));
  const vertical=fov*Math.PI/360;
  const halfFov=Math.min(vertical,Math.atan(Math.tan(vertical)*width/height))*0.8;
  const distance=Math.max(10,radius/Math.sin(halfFov));
  let direction=unit(subtract(camera.position,camera.target));
  if(Math.hypot(direction.x,direction.y,direction.z)<0.01)direction={x:0,y:0,z:1};
  return {target,position:{x:target.x+direction.x*distance,y:target.y+direction.y*distance,z:target.z+direction.z*distance}};
}
export function cameraBasis(camera: Camera3D) {
  const forward = unit(subtract(camera.target, camera.position));
  const raw = cross(forward, {x:0,y:1,z:0});
  const right = Math.hypot(raw.x,raw.y,raw.z) < 1e-6 ? {x:1,y:0,z:0} : unit(raw);
  return {right, up: unit(cross(right,forward)), forward};
}
export function translateView(camera: Camera3D, dx: number, dy: number, dz = 0): LayoutPosition {
  const {right,up,forward} = cameraBasis(camera);
  return {x:right.x*dx+up.x*dy+forward.x*dz,y:right.y*dx+up.y*dy+forward.y*dz,z:right.z*dx+up.z*dy+forward.z*dz};
}
export function zoomCamera(camera: Camera3D, factor: number): Camera3D | null {
  if (!Number.isFinite(factor) || factor <= 0 || !validCameraPosition(camera.position) || !validCameraPosition(camera.target)) return null;
  const offset = subtract(camera.position,camera.target);
  const length = Math.hypot(offset.x,offset.y,offset.z);
  if (length < 1e-6) return null;
  const distance=Math.max(10,length/factor);
  if(!Number.isFinite(distance))return null;
  const scale = distance/length;
  return { target: {...camera.target}, position: {x:camera.target.x+offset.x*scale,y:camera.target.y+offset.y*scale,z:camera.target.z+offset.z*scale} };
}
export function orbitCamera(camera: Camera3D, yaw: number, pitch: number): Camera3D | null {
  if (![yaw,pitch].every(Number.isFinite) || !validCameraPosition(camera.position) || !validCameraPosition(camera.target)) return null;
  const d = subtract(camera.position,camera.target);
  const r = Math.max(10,Math.hypot(d.x,d.y,d.z));
  const theta = Math.atan2(d.x,d.z) + clamp(yaw,-Math.PI,Math.PI);
  const phi = clamp(Math.acos(clamp(d.y/r,-1,1)) - clamp(pitch,-Math.PI,Math.PI),0.01,Math.PI-0.01);
  return {target:{...camera.target},position:{x:camera.target.x+r*Math.sin(phi)*Math.sin(theta),y:camera.target.y+r*Math.cos(phi),z:camera.target.z+r*Math.sin(phi)*Math.cos(theta)}};
}
export function selectionHighlight(graph: NormalizedGraph, selection: GraphSelection) {
  const nodes = new Set<string>(); const edges = new Set<string>();
  if (selection?.kind === 'node') {
    nodes.add(selection.id);
    for (const e of graph.incidentEdges.get(selection.id) ?? []) { edges.add(e.id); nodes.add(e.source); nodes.add(e.target); }
  } else if (selection) {
    const e = graph.edgeById.get(selection.id);
    if (e) {edges.add(e.id);nodes.add(e.source);nodes.add(e.target);}
  }
  return {nodes,edges};
}
export function showLabel(mode: 'selected'|'auto'|'all', priority: boolean, scale: number, count: number) {
  return priority || mode === 'all' || (mode === 'auto' && scale >= (count > 80 ? 1.8 : count > 25 ? 0.9 : 0.4));
}
export function roleColor(role: string) {
  return ['#3b82f6','#f59e0b','#10b981','#a78bfa','#f472b6','#06b6d4'][layoutSeed(role)%6];
}
