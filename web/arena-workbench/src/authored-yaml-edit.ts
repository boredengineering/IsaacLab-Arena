// Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { yamlLanguage } from '@codemirror/lang-yaml';

export interface RootPositionEditInput {
  draft: string;
  role: 'embodiment' | 'background' | 'object';
  nodeId: string;
  axis: 0 | 1 | 2;
  value: number;
}

export type RootPositionEditRefusal =
  | 'invalid-input' | 'axis-out-of-range' | 'nonfinite-value' | 'value-out-of-range'
  | 'input-too-large' | 'candidate-too-large' | 'structure-too-complex'
  | 'unsupported-syntax' | 'duplicate-key' | 'duplicate-id'
  | 'schema-unknown' | 'target-not-root' | 'no-change';

export type RootPositionEditResult =
  | { ok: true; candidate: string; range: { from: number; to: number }; before: number; after: number }
  | { ok: false; reason: RootPositionEditRefusal };

/** Inclusive UTF-8 limit for both the authored draft and proposed candidate. */
export const MAX_AUTHORED_YAML_BYTES = 256 * 1024;
const MAX_CST_NODES = 32768;
const MAX_CST_DEPTH = 64;

type Node = ReturnType<typeof yamlLanguage.parser.parse>['topNode'];

function children(node: Node): Node[] {
  const result: Node[] = [];
  for (let child = node.firstChild; child; child = child.nextSibling) {
    if (child.name !== 'Comment') result.push(child);
  }
  return result;
}

function text(node: Node, draft: string): string {
  return draft.slice(node.from, node.to);
}

// Deliberately no YAML escape decoding or implicit key/ID coercion.
function simpleString(node: Node, draft: string): string | undefined {
  const raw = text(node, draft);
  if (node.name === 'QuotedLiteral') {
    const inner = raw.slice(1, -1);
    if (!['"', "'"].includes(raw[0]) || raw.at(-1) !== raw[0] || /[\\\r\n]/.test(inner) || inner.includes(raw[0])) return undefined;
    return inner;
  }
  if (node.name === 'Literal' && /^[A-Za-z_][A-Za-z0-9_.-]*$/.test(raw) && !/^(?:true|false|null|yes|no|on|off|y|n)$/i.test(raw)) return raw;
  return undefined;
}

function keyText(pair: Node, draft: string): string | undefined {
  const key = pair.getChild('Key');
  const parts = key && children(key);
  return parts?.length === 1 ? simpleString(parts[0], draft) : undefined;
}

function validateTree(top: Node, draft: string): RootPositionEditRefusal | undefined {
  const allowed = new Set(['Stream', 'Document', 'BlockMapping', 'FlowMapping', 'BlockSequence', 'FlowSequence', 'Pair', 'Key', 'Item', 'Literal', 'QuotedLiteral', 'Comment', ':', ',', '-', '[', ']', '{', '}']);
  if (top.getChildren('Document').length > 1) return 'unsupported-syntax';
  const cursor = top.cursor();
  let count = 0;
  do {
    if (++count > MAX_CST_NODES) return 'structure-too-complex';
    let depth = 0;
    for (let ancestor = cursor.node.parent; ancestor; ancestor = ancestor.parent) {
      if (++depth > MAX_CST_DEPTH) return 'structure-too-complex';
    }
    if (cursor.type.isError || !allowed.has(cursor.name)) return 'unsupported-syntax';
    const node = cursor.node;
    if (node.name === 'QuotedLiteral' && simpleString(node, draft) === undefined) return 'unsupported-syntax';
    if (node.name === 'Literal' && /[\r\n]/.test(text(node, draft))) return 'unsupported-syntax';
    if (node.name === 'Pair') {
      const parts = children(node);
      if (parts.length !== 3 || parts[0].name !== 'Key' || parts[1].name !== ':') return 'unsupported-syntax';
    }
    if (node.name === 'BlockMapping' || node.name === 'FlowMapping') {
      const seen = new Set<string>();
      for (const pair of node.getChildren('Pair')) {
        const key = keyText(pair, draft);
        if (key === undefined || key === '<<') return 'unsupported-syntax';
        if (seen.has(key)) return 'duplicate-key';
        seen.add(key);
      }
    }
  } while (cursor.next());
  return undefined;
}

function member(node: Node | undefined, key: string, draft: string): Node | undefined {
  if (!node || !['BlockMapping', 'FlowMapping'].includes(node.name)) return undefined;
  const pair = node.getChildren('Pair').find(pair => keyText(pair, draft) === key);
  return pair && children(pair)[2];
}

function decimalSpelling(value: number): string {
  if (Object.is(value, -0)) return '-0.0';
  const spelling = String(value);
  if (!spelling.includes('e')) return spelling;
  // Magnitude is capped at MAX_SAFE_INTEGER: only negative exponents reach here.
  const [mantissa, exponent] = String(Math.abs(value)).split('e');
  return (value < 0 ? '-' : '') + '0.' + '0'.repeat(-Number(exponent) - 1) + mantissa.replace('.', '');
}

/**
 * Propose one local source-preserving edit; this is NOT permission to apply it.
 *
 * Recognizes root embodiment/background mappings and objects sequence entries,
 * with an exact, unique explicit id and params.initial_pose.position_xyz path.
 * Only an existing three-element block/flow sequence of unquoted decimal numbers
 * is editable (optional sign, no leading zeroes, optional digits after a dot).
 * All three values must be finite, have magnitude <= Number.MAX_SAFE_INTEGER,
 * and not underflow to zero. This is a numeric safety bound, not a scene bound.
 *
 * CST contract characterized with @codemirror/lang-yaml 6.1.2 / @lezer/yaml 1.0.4:
 * Stream > Document > Block/FlowMapping > Pair(Key, ':', value), and sequences
 * contain Item(Literal), not Number. Comments may be siblings at any level.
 * Returned ranges are half-open UTF-16 offsets in input.draft (CodeMirror and
 * String.slice convention), NOT UTF-8 byte offsets or candidate-relative ranges.
 * Only that numeric token is replaced; all other source bytes remain unchanged.
 *
 * Deliberately refuses duplicate keys anywhere and duplicate root asset IDs
 * (including object_references, whose identities must be explicit simple strings
 * in a sequence of mappings; references are never editable),
 * parser recovery/errors, aliases/anchors/merges/tags, document markers and
 * directives, block/multiline scalars, escaped quoted scalars/keys/IDs, complex
 * or implicitly coerced plain keys/IDs, tabs/controls/BOM and non-LF/CRLF breaks.
 * Simple single/double quoting is supported without YAML escape decoding.
 * Exponent/hex/octal/sexagesimal/underscore/quoted numeric spellings are refused
 * rather than guessing a YAML resolver. Depth/node limits are 64 / 32768.
 *
 * Never opens external_yaml or creates overrides/defaults. Missing, included-only
 * or normalized-shape targets are refused. Text alone cannot distinguish an
 * authored leaf from an identical fully materialized normalized dump: the caller
 * MUST supply the actual current root draft, not normalized API YAML.
 *
 * The caller owns provenance, eligibility, current validation, authenticated
 * session/document/revision binding, registry and constraint checks, explicit
 * review/consent and server candidate validation BEFORE any apply. Success says
 * nothing about whether initial_pose affects the solver or final physical pose.
 */
export function proposeRootPositionEdit(input: RootPositionEditInput): RootPositionEditResult {
  if (!input || typeof input.draft !== 'string' || typeof input.value !== 'number' ||
      typeof input.nodeId !== 'string' || !input.nodeId ||
      !['embodiment', 'background', 'object'].includes(input.role)) return { ok: false, reason: 'invalid-input' };
  const { draft, role, nodeId, axis, value } = input;
  if (axis !== 0 && axis !== 1 && axis !== 2) return { ok: false, reason: 'axis-out-of-range' };
  if (!Number.isFinite(value)) return { ok: false, reason: 'nonfinite-value' };
  if (Math.abs(value) > Number.MAX_SAFE_INTEGER) return { ok: false, reason: 'value-out-of-range' };
  if (draft.length > MAX_AUTHORED_YAML_BYTES) return { ok: false, reason: 'input-too-large' };
  const bytes = new TextEncoder().encode(draft).byteLength;
  if (bytes > MAX_AUTHORED_YAML_BYTES) return { ok: false, reason: 'input-too-large' };
  // Reject non-UTF-8 strings, tabs, YAML line-break variants and controls rather
  // than allow the highlighting parser to silently skip or normalize them.
  if (/[\uD800-\uDFFF\u0000-\u0009\u000B\u000C\u000E-\u001F\u007F-\u009F\u2028\u2029\uFEFF\uFFFE\uFFFF]/u.test(draft) || /\r(?!\n)/.test(draft)) {
    return { ok: false, reason: 'unsupported-syntax' };
  }
  const top = yamlLanguage.parser.parse(draft).topNode;
  const refusal = validateTree(top, draft);
  if (refusal) return { ok: false, reason: refusal };
  const document = top.getChild('Document');
  const root = document ? children(document)[0] : undefined;
  if (!root || !['BlockMapping', 'FlowMapping'].includes(root.name)) return { ok: false, reason: 'schema-unknown' };
  const assets: { role: RootPositionEditInput['role']; node: Node; id: string }[] = [];
  const identities = new Set<string>();
  for (const assetRole of ['embodiment', 'background', 'object', 'object_reference'] as const) {
    const isSequence = assetRole === 'object' || assetRole === 'object_reference';
    const collection = member(root, isSequence ? `${assetRole}s` : assetRole, draft);
    if (!collection) continue;
    if (isSequence && !['BlockSequence', 'FlowSequence'].includes(collection.name)) {
      return { ok: false, reason: 'schema-unknown' };
    }
    const nodes = isSequence ? collection.getChildren('Item').map(item => item.firstChild) : [collection];
    for (const node of nodes) {
      if (!node || !['BlockMapping', 'FlowMapping'].includes(node.name)) return { ok: false, reason: 'schema-unknown' };
      const id = member(node, 'id', draft);
      const identity = id && simpleString(id, draft);
      if (!identity) return { ok: false, reason: 'schema-unknown' };
      if (identities.has(identity)) return { ok: false, reason: 'duplicate-id' };
      identities.add(identity);
      if (assetRole !== 'object_reference') assets.push({ role: assetRole, node, id: identity });
    }
  }
  const asset = assets.find(asset => asset.role === role && asset.id === nodeId)?.node;
  if (!asset) return { ok: false, reason: 'target-not-root' };
  const params = member(asset, 'params', draft);
  const pose = member(params, 'initial_pose', draft);
  const sequence = member(pose, 'position_xyz', draft);
  if (!sequence || !['BlockSequence', 'FlowSequence'].includes(sequence.name)) return { ok: false, reason: 'schema-unknown' };
  const items = sequence.getChildren('Item');
  if (items.length !== 3) return { ok: false, reason: 'schema-unknown' };
  const leaves: { node: Node; value: number }[] = [];
  for (const item of items) {
    const parts = children(item);
    const node = parts[0];
    if (parts.length !== 1 || node.name !== 'Literal' || !/^[+-]?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(text(node, draft))) {
      return { ok: false, reason: 'schema-unknown' };
    }
    const number = Number(text(node, draft));
    if (!Number.isFinite(number) || Math.abs(number) > Number.MAX_SAFE_INTEGER || (number === 0 && /[1-9]/.test(text(node, draft)))) {
      return { ok: false, reason: 'value-out-of-range' };
    }
    leaves.push({ node, value: number });
  }
  const { node: leaf, value: before } = leaves[axis];
  if (before === value) return { ok: false, reason: 'no-change' };
  const replacement = decimalSpelling(value);
  // Both the old numeric leaf and the replacement are ASCII.
  if (bytes - (leaf.to - leaf.from) + replacement.length > MAX_AUTHORED_YAML_BYTES) return { ok: false, reason: 'candidate-too-large' };
  return { ok: true, candidate: draft.slice(0, leaf.from) + replacement + draft.slice(leaf.to), range: { from: leaf.from, to: leaf.to }, before, after: value };
}
