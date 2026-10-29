import type { GraphPresentation } from './renderer-contracts';
export function samePresentation(a: GraphPresentation, b: GraphPresentation): boolean {
  if (a === b) return true;
  if (a.frozen !== b.frozen || a.positions.size !== b.positions.size || a.pins.size !== b.pins.size) return false;
  for (const id of a.pins) if (!b.pins.has(id)) return false;
  for (const [id, point] of a.positions) {
    const other = b.positions.get(id);
    if (!other || point.x !== other.x || point.y !== other.y || point.z !== other.z) return false;
  }
  const left = a.camera, right = b.camera;
  return left?.zoom === right?.zoom
    && left?.center?.x === right?.center?.x && left?.center?.y === right?.center?.y
    && left?.position?.x === right?.position?.x && left?.position?.y === right?.position?.y && left?.position?.z === right?.position?.z
    && left?.target?.x === right?.target?.x && left?.target?.y === right?.target?.y && left?.target?.z === right?.target?.z;
}
