import type { PreviewSelection } from './types';
import { inspectionVersions } from './inspection-data';

export type ExampleKind = 'environment' | 'policy' | 'experiment' | 'unclassified';
export interface ExampleVersion extends PreviewSelection {
  parent: string | null;
  status: string;
}
export interface ExampleFamily {
  id: string;
  name: string;
  internalName: string;
  kind: ExampleKind;
  scenario: string;
  robot: string;
  hand: string;
  marker?: string;
  baselineVersionId: string | null;
  versions: ExampleVersion[];
}

export const exampleFamilies: ExampleFamily[] = [
  { id: 'example-c1-g1-tabletop', name: 'C1 · G1 tabletop', internalName: 'example-tabletop', kind: 'environment', scenario: 'C1-labelled tabletop; illustrative, not a validated C1 contract', robot: 'G1', hand: 'Left', marker: 'Pinned example', baselineVersionId: 'example-c1-g1-tabletop-v1', versions: [] },
  { id: 'example-g1-reach', name: 'G1 · incompatible reach scenario', internalName: 'example-tabletop', kind: 'environment', scenario: 'Overhead reach; incompatible with tabletop controller assumptions', robot: 'G1', hand: 'Right', baselineVersionId: 'example-g1-reach-v1', versions: [] },
  { id: 'example-a2-droid', name: 'A2 · DROID banana to plate', internalName: 'example-a2', kind: 'environment', scenario: 'A2-labelled banana to large plate; no physical result', robot: 'DROID', hand: 'Parallel gripper', marker: 'Recent example', baselineVersionId: 'example-a2-droid-v1', versions: [] },
  { id: 'example-policy', name: 'Example policy profile', internalName: 'example-tabletop', kind: 'policy', scenario: 'Illustrative controller configuration', robot: 'G1', hand: 'Left', baselineVersionId: null, versions: [] },
  { id: 'example-experiment', name: 'Example seed comparison', internalName: 'example-seeds', kind: 'experiment', scenario: 'Illustrative ordered variations', robot: 'G1', hand: 'Left', baselineVersionId: null, versions: [] },
  { id: 'example-unclassified', name: 'Example unclassified document', internalName: 'example-unknown', kind: 'unclassified', scenario: 'Root type unresolved; requires review', robot: 'Unknown', hand: 'Unknown', baselineVersionId: null, versions: [] },
].map((family) => ({ ...family, versions: Array.from({ length: family.id === 'example-c1-g1-tabletop' ? 12 : family.id === 'example-g1-reach' ? 2 : 1 }, (_, i) => ({
  familyId: family.id, familyName: family.name, versionId: `${family.id}-v${i + 1}`, version: i + 1,
  source: `example-library/${family.id}/v${i + 1}.yaml`, yaml: `# Synthetic design example; not a runnable or validated environment\nexample_family_id: ${family.id}\nname: ${family.internalName}\nexample_revision: ${i + 1}\nrobot: ${family.robot}\nhand: ${family.hand}\nscenario: ${family.scenario}\n`,
  robot: family.robot, hand: family.hand, parent: i === 0 ? null : `${family.id}-v${i}`,
  status: 'Example only · not validated',
})) })) as ExampleFamily[];

exampleFamilies.push({ id: 'example-inspection', name: 'Synthetic inspection lab', internalName: 'inspect-correct/v1', kind: 'environment', scenario: 'Explicit preview-only authored objects; not Arena schema or a rendered scene', robot: 'None — synthetic fixture', hand: 'Not applicable', baselineVersionId: 'example-inspection-v1', versions: inspectionVersions.map((version, index) => ({ ...version, parent: index === 0 ? null : 'example-inspection-v1', status: 'Synthetic authored example · not runtime validated' })) });
