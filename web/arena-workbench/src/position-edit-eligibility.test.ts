import { expect, it } from 'vitest';
import { positionEditEligibility } from './position-edit-eligibility';
import type { Validation } from './editor-contracts';

// ArenaEnvGraphSpec shape: root assets, params.initial_pose, task composition.
const draft = '# preserve this comment\r\nenv_name: review_table\r\nembodiment: {id: robot, registry_name: franka}\r\nbackground:\r\n  id: desk\r\n  registry_name: table\r\n  params:\r\n    initial_pose:\r\n      position_xyz: [0.5, 0, 0] # meters\r\n      rotation_xyzw: [0, 0, 0, 1]\r\nobjects: []\r\nrelations: []\r\ntask: {composition: atomic, subtasks: [{kind: NoTask, params: {}}]}\r\n';
function validation(): Validation {
  const properties = { id: 'desk', registry_name: 'table', params: { initial_pose: { position_xyz: [0.5, 0, 0], rotation_xyzw: [0, 0, 0, 1] } } };
  return { valid: true, source_hash: 'a'.repeat(64), canonical_hash: 'b'.repeat(64), errors: [], warnings: [], spec: {}, summary: 'Schema valid',
    assets: [{ id: 'desk', registry_name: 'table', role: 'background', properties }], relations: [], reified_relations: [], tasks: [{kind: 'NoTask', params: {}}], graph: {nodes: [], edges: []} };
}
it.each([
  ['invalid', (v: Validation): void => { v.valid = false; }],
  ['pending', (_v: Validation): null => null],
  ['unknown registry', (v: Validation) => { v.assets[0].registry_name = 'kitchen'; }],
  ['wrong role', (v: Validation) => { v.assets[0].role = 'object'; }],
  ['reference', (v: Validation) => { v.assets[0].role = 'object_reference'; }],
  ['duplicate ID', (v: Validation) => { v.assets.push(v.assets[0]); }],
  ['constrained subject', (v: Validation) => { v.relations = [{kind: 'on', subject: 'desk', reference: 'robot', params: {}}]; }],
  ['constrained reference', (v: Validation) => { v.relations = [{kind: 'on', subject: 'robot', reference: 'desk', params: {}}]; }],
  ['reifier', (v: Validation) => { v.reified_relations = [{source_id: 'desk', target_id: 'robot'}]; }],
  ['scale', (v: Validation) => { v.assets[0].properties.params = {scale: 1}; }],
  ['projection mismatch', (v: Validation) => { v.assets[0].properties.id = 'different'; }],
] as const)('refuses %s', (_name, change) => {
  const v = validation(); const changed = change(v);
  expect(positionEditEligibility(draft, changed === null ? null : v, 'desk').ok).toBe(false);
});
it.each([
  ['included only', 'external_yaml: scene.yaml\ntask: {composition: atomic, subtasks: [{kind: NoTask}]}\n'],
  ['normalized shape', 'assets: [{id: desk, registry_name: table}]'],
  ['registry mismatch', draft.replace('registry_name: table', 'registry_name: kitchen')],
  ['defaulted position', draft.replace('position_xyz: [0.5, 0, 0]', 'other: [0.5, 0, 0]')],
  ['defaulted rotation', draft.replace('rotation_xyzw: [0, 0, 0, 1]', 'other: [0, 0, 0, 1]')],
  ['nonfinite', draft.replace('[0.5, 0, 0]', '[.inf, 0, 0]')],
  ['duplicate root', draft + 'background: {}\r\n'],
  ['zero quaternion', draft.replace('[0, 0, 0, 1]', '[0, 0, 0, 0]')],
  ['nonunit quaternion', draft.replace('[0, 0, 0, 1]', '[0, 0, 0, 2]')],
  ['unknown constructor argument', draft.replace('    initial_pose:', '    reset_pose: false\r\n    initial_pose:')],
])('refuses raw %s', (_name, text) => expect(positionEditEligibility(text, validation(), 'desk').ok).toBe(false));
it.each([
  ['missing canonical hash', (v: Validation) => {v.canonical_hash = null;}],
  ['null asset', (v: Validation) => {v.assets.push(null as never);} ],
  ['null relation', (v: Validation) => {v.relations.push(null as never);} ],
  ['reference child', (v: Validation) => {v.assets.push({id: 'child', role: 'object_reference', parent_id: 'desk', properties: {}});} ],
  ['nonfinite projection', (v: Validation) => {v.assets[0].properties.params = {initial_pose: {position_xyz: [Infinity, 0, 0], rotation_xyzw: [0, 0, 0, 1]}};} ],
  ['defaulted projection', (v: Validation) => {v.assets[0].properties.params = {};} ],
])('rejects malformed/unsupported %s without throwing', (_name, modify) => {
  const v = validation(); modify(v);
  expect(positionEditEligibility(draft, v, 'desk').ok).toBe(false);
});
it('preserves scalar composition declarations but refuses non-scalar external_yaml', () => {
  const includedTask = 'external_yaml: task.yaml\r\n' + draft.replace('task: {composition: atomic, subtasks: [{kind: NoTask, params: {}}]}\r\n', '');
  expect(positionEditEligibility(includedTask, validation(), 'desk').ok).toBe(true);
  expect(positionEditEligibility(includedTask.replace('external_yaml: task.yaml', 'external_yaml: [task.yaml]'), validation(), 'desk').ok).toBe(false);
});
it('admits only the explicit root table background pose and preserves the actual source', () => {
  const result = positionEditEligibility(draft, validation(), 'desk');
  expect(result).toEqual({ ok: true, role: 'background', position: [0.5, 0, 0] });
});
