// Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { yamlLanguage } from '@codemirror/lang-yaml';
import { proposeRootPositionEdit } from './authored-yaml-edit';

const draft = `# Authored scene; never a normalized API response.
external_yaml: "base_scene.yaml" # retain this declaration
embodiment:
  id: robot
  registry_name: droid_abs_joint_pos
  params:
    initial_pose:
      position_xyz: [0.0, -2.50, 3.0] # keep pose comment
      rotation_xyzw: [0, 0, 0, 1]
background:
  id: table
  registry_name: maple_table_robolab
  params:
    initial_pose:
      position_xyz: [-0.25, 0.0, 0.0]
objects:
- id: box
  registry_name: spam_can_ycb_robolab
  params:
    initial_pose:
      position_xyz: [0.125, 0.25, 0.75]
relations:
- kind: 'on'
  subject: box
  reference: table
  params: {}
`;

function edit(source = draft, overrides: Partial<Parameters<typeof proposeRootPositionEdit>[0]> = {}) {
  const input = Object.freeze({ draft: source, role: 'embodiment' as const, nodeId: 'robot', axis: 1 as const, value: 1.25, ...overrides });
  const snapshot = { ...input };
  const result = proposeRootPositionEdit(input);
  expect(input).toEqual(snapshot);
  return result;
}

describe('installed YAML CST characterization', () => {
  it('exposes Literal (not Number) ranges inside Pair/Item wrappers', () => {
    const source = 'embodiment:\n  id: robot\n  params:\n    initial_pose:\n      position_xyz: [1, -2.50, 3] # note\n';
    const tree = yamlLanguage.parser.parse(source);
    const mapping = tree.topNode.getChild('Document')!.getChild('BlockMapping')!;
    const asset = mapping.getChild('Pair')!.getChild('BlockMapping')!;
    const params = asset.getChildren('Pair')[1].getChild('BlockMapping')!;
    const pose = params.getChild('Pair')!.getChild('BlockMapping')!;
    const sequence = pose.getChild('Pair')!.getChild('FlowSequence')!;
    const leaf = sequence.getChildren('Item')[1].getChild('Literal')!;
    expect(source.slice(leaf.from, leaf.to)).toBe('-2.50');
    expect(tree.toString()).not.toContain('Number');
    expect(tree.toString()).toContain('Comment');
  });
});

describe('proposeRootPositionEdit', () => {
  it.each([
    draft.replace('objects:\n', 'objects:\n-\n'),
    draft.replace('objects:\n', 'objects:\n- # empty object\n'),
    draft.replace('relations:', '-\nrelations:'),
    draft.replace('[0.0, -2.50, 3.0]', '\n      - 0.0\n      - -2.50\n      -\n      - 3.0'),
    draft.replace('[0.0, -2.50, 3.0]', '[0.0, -2.50, 3.0,,]'),
    draft.replace('[0.0, -2.50, 3.0]', '[0.0, -2.50, ,3.0]'),
  ])('refuses sparse collections instead of counting only present CST Item nodes', source => {
    expect(edit(source).ok).toBe(false);
  });

  it.each(['\n', '\r\n'])('preserves Unicode, comments, include declaration and %j EOL outside a block-sequence numeric leaf', eol => {
    const source = ('# 🦾 界 e\u0301 — position_xyz: [fake]\n' + draft)
      .replace('      position_xyz: [0.0, -2.50, 3.0]', '      position_xyz: # axes\n      - 0.0 # first\n      # interleaved\n      - -2.50 # second 🦾\n      - 3.0')
      .replaceAll('\n', eol);
    const result = edit(source);
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.candidate).toBe(source.replace('-2.50', '1.25'));
    expect(source.slice(result.range.from, result.range.to)).toBe('-2.50');
    const suffixAt = result.range.from + '1.25'.length;
    const encode = (value: string) => [...new TextEncoder().encode(value)];
    expect(encode(result.candidate.slice(0, result.range.from))).toEqual(encode(source.slice(0, result.range.from)));
    expect(encode(result.candidate.slice(suffixAt))).toEqual(encode(source.slice(result.range.to)));
    expect(result.candidate).toContain('external_yaml: "base_scene.yaml" # retain this declaration');
  });

  it('supports commented multiline flow sequences, trailing comma and flow mappings', () => {
    const source = 'objects: [{id: box, params: {initial_pose: {position_xyz: [0.125, # x\n  0.25, # y\n  0.75, # z\n]}}}]\n';
    const result = edit(source, { role: 'object', nodeId: 'box' });
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.candidate).toBe(source.replace('0.25', '1.25'));
  });

  it.each(['../scenes/two_bin.yaml', '"base_scene.yaml"', "'base_scene.yaml'"])('preserves scalar external_yaml %s while editing an explicit local leaf', include => {
    const source = draft.replace('"base_scene.yaml"', include);
    const result = edit(source);
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.candidate).toBe(source.replace('-2.50', '1.25'));
  });

  it.each(['../scenes/two_bin.yaml', '"included.yaml"', "'included.yaml'"])('refuses scalar included-only document %s without adding an override', include => {
    const source = `external_yaml: ${include} # contents not opened or inferred\n`;
    expect(edit(source, { role: 'object', nodeId: 'box' })).toEqual({ ok: false, reason: 'target-not-root' });
  });

  it.each(['robot', 'table', 'box', '"robot"', "'box'"])('refuses root reference ID %s colliding with any asset role', id => {
    const source = draft + `object_references:\n- id: ${id}\n  parent_id: table\n  prim_path: /World/Table/Top\n`;
    expect(edit(source)).toEqual({ ok: false, reason: 'duplicate-id' });
  });

  it('refuses duplicate reference IDs unrelated to the selected local asset', () => {
    const source = draft + 'object_references: [{id: shelf, parent_id: table}, {id: "shelf", parent_id: box}]\n';
    expect(edit(source)).toEqual({ ok: false, reason: 'duplicate-id' });
  });

  it.each([
    '[]',
    '[{id: shelf, parent_id: table, prim_path: /World/Table/Top}]',
    '\n- id: shelf\n  parent_id: box\n  prim_path: /World/Box/Top',
  ])('preserves unique root reference collection %s while editing a local asset', references => {
    const source = draft + `object_references: ${references}\n`;
    const result = edit(source);
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.candidate).toBe(source.replace('-2.50', '1.25'));
  });

  it.each([
    'null', 'shelf', '{shelf: {id: shelf}}', '[shelf]', '[[shelf]]',
    '[{parent_id: table}]', '[{id: ""}]', '[{id: 12}]', '[{id: true}]',
    '[{id: [shelf]}]', '[{id: {name: shelf}}]',
  ])('refuses unsupported reference identity shape %s even for an unrelated local edit', references => {
    expect(edit(draft + `object_references: ${references}\n`)).toEqual({ ok: false, reason: 'schema-unknown' });
  });

  it('keeps root references ineligible for numeric editing even with an explicit pose', () => {
    const source = draft + 'object_references: [{id: shelf, parent_id: table, params: {initial_pose: {position_xyz: [0, 1, 2]}}}]\n';
    expect(edit(source, { role: 'object', nodeId: 'shelf' })).toEqual({ ok: false, reason: 'target-not-root' });
    expect(edit(source, { role: 'object_reference' as never, nodeId: 'shelf' })).toEqual({ ok: false, reason: 'invalid-input' });
  });

  it.each(['', '# empty\n', '[]\n', 'scalar\n', 'null\n'])('refuses an unknown root schema %j', source => {
    expect(edit(source)).toEqual({ ok: false, reason: 'schema-unknown' });
  });

  it.each([
    draft.replace('id: table', 'id: "robot"'),
    draft.replace('id: table', "id: 'box'"),
    draft.replace('relations:', 'objects: []\nrelations:'),
    draft.replace('relations:', '- id: box\n  params: {}\nrelations:'),
  ])('rejects ambiguous root collections even when the selected asset precedes them', source => {
    expect(edit(source).ok).toBe(false);
  });

  it('bounds UTF-8 input inclusively, not UTF-16 code units', () => {
    const max = 256 * 1024;
    const bytes = new TextEncoder().encode(draft).length;
    const exact = draft + '#' + 'x'.repeat(max - bytes - 1);
    expect(new TextEncoder().encode(exact).length).toBe(max);
    expect(edit(exact).ok).toBe(true);
    expect(edit(exact + 'x')).toEqual({ ok: false, reason: 'input-too-large' });
    const unicode = draft + '#' + '界'.repeat(Math.floor(max / 2));
    expect(unicode.length).toBeLessThan(max);
    expect(edit(unicode)).toEqual({ ok: false, reason: 'input-too-large' });
    expect(edit(exact, { value: 1234567890 })).toEqual({ ok: false, reason: 'candidate-too-large' });
  });

  it.each(['\ud800', '\udfff', '\u0000', '\t', '\u0085', '\u2028', '\ufeff', '\ufffe', '\uffff', '\r'])('refuses unsupported source character %j', character => {
    expect(edit(draft + '# comment' + character)).toEqual({ ok: false, reason: 'unsupported-syntax' });
  });

  it.each([
    { role: 'objects' }, { role: '' }, { nodeId: '' }, { nodeId: 12 },
    { draft: null }, { draft: 12 }, { value: '1.25' },
  ])('refuses malformed runtime arguments %j', overrides => {
    expect(edit(draft, overrides as unknown as Parameters<typeof edit>[1])).toEqual({ ok: false, reason: 'invalid-input' });
  });

  it('returns refusal for missing runtime input', () => {
    expect(proposeRootPositionEdit(null as unknown as Parameters<typeof proposeRootPositionEdit>[0])).toEqual({ ok: false, reason: 'invalid-input' });
  });

  it('bounds structural depth and node count before selecting a target', () => {
    expect(edit(draft + 'metadata: ' + '['.repeat(100) + '0' + ']'.repeat(100) + '\n')).toEqual({ ok: false, reason: 'structure-too-complex' });
    expect(edit(draft + 'metadata: [' + '0,'.repeat(20000) + ']\n')).toEqual({ ok: false, reason: 'structure-too-complex' });
  });

  it.each([NaN, Infinity, -Infinity])('refuses nonfinite proposed value %s', value => {
    expect(edit(draft, { value })).toEqual({ ok: false, reason: 'nonfinite-value' });
  });

  it.each([-1, 3, 1.5, NaN, Infinity, '1', null, undefined])('refuses invalid axis %s', axis => {
    expect(edit(draft, { axis: axis as 1 })).toEqual({ ok: false, reason: 'axis-out-of-range' });
  });

  it.each([Number.MAX_VALUE, -Number.MAX_VALUE, Number.MAX_SAFE_INTEGER + 1])('refuses unsafe-magnitude proposed value %s', value => {
    expect(edit(draft, { value })).toEqual({ ok: false, reason: 'value-out-of-range' });
  });

  it.each([-2.5, -0, 0])('refuses numeric no-change including zero sign (%s)', value => {
    const source = value === -2.5 ? draft : draft.replace('-2.50', '-0.0');
    expect(edit(source, { value })).toEqual({ ok: false, reason: 'no-change' });
  });

  it.each([
    '[0.0, "-2.50", 3.0]', '[0.0, -2.50, "3.0"]', '[true, -2.50, 3]',
    '[0, -2.50, null]', '[0, -2.50, .inf]', '[0, -2.50, .nan]',
    '[0, -2.50, 0x10]', '[0, -2.50, 01]', '[0, -2.50, 1_000]',
    '[0, -2.50, 1e3]', '[0, -2.50, 1.0e+3]', '[0, -2.50, .5]',
    '[0, -2.50, 1.]', '[0, -2.50, 1:20]', '[0, -2.50, {x: 3}]',
    '[0, -2.50, [3]]', '[0, -2.50]', '[0, -2.50, 3, 4]', 'null',
  ])('requires exactly three explicit unquoted decimal leaves: %s', position => {
    expect(edit(draft.replace('[0.0, -2.50, 3.0]', position))).toEqual({ ok: false, reason: 'schema-unknown' });
  });

  it.each(['9007199254740992', '9'.repeat(320), '0.' + '0'.repeat(330) + '1'])('refuses current leaf outside numeric range', scalar => {
    expect(edit(draft.replace('3.0]', scalar + ']'))).toEqual({ ok: false, reason: 'value-out-of-range' });
  });

  it.each([1e-7, -1e-7, Number.MIN_VALUE, Number.MAX_SAFE_INTEGER, -0])('emits a decimal scalar (not resolver-dependent exponent) for %s', value => {
    const result = edit(draft, { value });
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    const spelling = result.candidate.slice(result.range.from, result.candidate.length - (draft.length - result.range.to));
    expect(spelling).toMatch(/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/);
    expect(Object.is(Number(spelling), value)).toBe(true);
    expect(result.after).toBe(value);
  });

  it('supports uncomplicated quoted keys and IDs without rewriting their spelling', () => {
    const source = draft.replace('embodiment:', '"embodiment":').replace('  id: robot', "  'id': 'robot'").replace('    initial_pose:', '    "initial_pose":').replace('      position_xyz:', "      'position_xyz':");
    const result = edit(source);
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.candidate).toBe(source.replace('-2.50', '1.25'));
  });

  it.each([
    ['root', draft + 'embodiment: {}\n'],
    ['quoted equivalent root', draft + '"embodiment": {}\n'],
    ['ID', draft.replace('  id: robot', '  id: other\n  id: robot')],
    ['params', draft.replace('  params:', '  params: {}\n  params:')],
    ['pose', draft.replace('    initial_pose:', '    initial_pose: {}\n    initial_pose:')],
    ['position', draft.replace('      position_xyz:', '      "position_xyz": [9, 8, 7]\n      position_xyz:')],
    ['unrelated flow mapping', draft + 'metadata: {a: 1, "a": 2}\n'],
  ])('refuses duplicate %s keys globally', (_label, source) => {
    expect(edit(source)).toEqual({ ok: false, reason: 'duplicate-key' });
  });

  it.each([
    ['escaped root key', draft.replace('embodiment:', '"embod\\u0069ment":')],
    ['escaped duplicate', draft + '"embod\\u0069ment": {}\n'],
    ['escaped key in unrelated map', draft + 'metadata: {"a\\nb": 1}\n'],
    ['single quote escape key', draft + "metadata: {'it''s': 1}\n"],
    ['escaped identity', draft.replace('id: robot', 'id: "rob\\u006ft"')],
    ['anchor', draft.replace('  params:', '  params: &pose')],
    ['unrelated anchor', draft + 'metadata: &a {x: 1}\n'],
    ['alias', draft.replace('[0.0, -2.50, 3.0]', '*pose')],
    ['merge', draft + 'metadata: {<<: {x: 1}}\n'],
    ['quoted merge', draft + "metadata: {'<<': {x: 1}}\n"],
    ['tag', draft.replace('[0.0, -2.50, 3.0]', '!!seq [0.0, -2.50, 3.0]')],
    ['unrelated tag', draft + 'metadata: !custom hello\n'],
    ['multiple documents', draft + '---\nother: 1\n'],
    ['directive', '%YAML 1.2\n---\n' + draft],
    ['document markers', '---\n' + draft + '...\n'],
    ['block scalar', draft + 'metadata: |\n  hello\n'],
    ['complex key', draft + '? [a, b]\n: value\n'],
    ['implicitly coerced key', draft + 'metadata: {true: 1, yes: 2}\n'],
    ['malformed YAML', draft + 'metadata: [1, 2\n'],
  ])('refuses unsupported %s rather than guessing', (_label, source) => {
    expect(edit(source)).toEqual({ ok: false, reason: 'unsupported-syntax' });
  });

  it.each([
    ['embodiment', 'robot', 0, '0.0'],
    ['background', 'table', 0, '-0.25'],
    ['object', 'box', 2, '0.75'],
  ] as const)('selects only root %s/%s axis %s', (role, nodeId, axis, before) => {
    const result = edit(draft, { role, nodeId, axis });
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(draft.slice(result.range.from, result.range.to)).toBe(before);
    expect(result.candidate).toBe(draft.slice(0, result.range.from) + '1.25' + draft.slice(result.range.to));
  });

  it.each([
    ['wrong role', draft, { role: 'object' as const, nodeId: 'robot' }],
    ['wrong id', draft, { nodeId: 'Robot' }],
    ['included-only id', draft, { role: 'object' as const, nodeId: 'included_box' }],
    ['nested role', 'scene:\n' + draft.split('\n').map(line => '  ' + line).join('\n'), {}],
    ['duplicate root IDs', draft.replace('id: box', 'id: robot'), {}],
    ['duplicate unrelated IDs', draft.replace('id: box', 'id: table'), {}],
    ['missing explicit ID', draft.replace('  id: robot\n', ''), {}],
    ['normalized objects mapping', draft.replace('objects:\n- id: box', 'objects:\n  box:\n    id: box'), {}],
    ['defaulted pose', draft.replace('position_xyz: [0.0, -2.50, 3.0]', 'rotation: [0, 0, 0]'), {}],
    ['wrong path', draft.replace('    initial_pose:', '    pose:'), {}],
  ])('refuses %s without synthesizing a root override', (_label, source, overrides) => {
    expect(edit(source as string, overrides as Parameters<typeof edit>[1])).toMatchObject({ ok: false, reason: expect.any(String) });
  });

  it('replaces only the explicit authored numeric leaf at its CST range', () => {
    const result = edit();
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    const from = draft.indexOf('-2.50');
    expect(result).toEqual({ ok: true, candidate: draft.slice(0, from) + '1.25' + draft.slice(from + 5), range: { from, to: from + 5 }, before: -2.5, after: 1.25 });
  });
});
