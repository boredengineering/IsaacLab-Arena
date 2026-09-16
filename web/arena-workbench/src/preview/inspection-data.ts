import type { PreviewSelection } from './types';

/** Synthetic authored fixtures, not Arena schema or renderer/prim identities. */
export const inspectionVersions: readonly PreviewSelection[] = [1, 2].map(version => ({
 familyId: 'example-inspection', familyName: 'Synthetic inspection lab',
 versionId: `example-inspection-v${version}`, version,
 source: `synthetic/inspection/v${version}/scene.yaml`, robot: 'None — synthetic fixture', hand: 'Not applicable',
 yaml: JSON.stringify({
  previewSchema: 'inspect-correct/v1', synthetic: true,
  assets: [
   { id: 'table', registry: 'preview:table', parent: null, pose: { position: [0, 0, 0], rotationDegrees: [0, 0, 0] }, scale: [1, 1, 1] },
   { id: 'cube', registry: 'preview:cube', parent: 'table', pose: { position: [version === 1 ? 0.25 : 0.4, 0, 0.8], rotationDegrees: [0, 0, 0] }, scale: [1, 1, 1] },
  ],
 }, null, 2) + '\n',
}));
