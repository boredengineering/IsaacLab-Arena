import { beforeEach, expect, it } from 'vitest';
import { readDraft, storeDraft, type RecoverableDraft } from './draft-storage';

const key = 'arena.editor.draft.v1';
const backup: RecoverableDraft = {
  version: 1,
  documentId: 'fixture',
  viewId: 'frozen-fixture',
  sourceHash: 'hash',
  draft: 'env_name: previous_valid_backup',
  prompt: 'Keep this prompt',
};

beforeEach(() => sessionStorage.clear());

it.each([
  ['prompt', { ...backup, prompt: 'p'.repeat(16_001) }],
  ['YAML', { ...backup, draft: 'y'.repeat(262_145) }],
  ['serialized record', { ...backup, draft: '\0'.repeat(100_001) }],
] as const)('rejects oversized %s on write and read without replacing a valid backup', (_name, oversized) => {
  expect(storeDraft(backup)).toBe(true);
  const previous = sessionStorage.getItem(key);
  expect(storeDraft(oversized)).toBe(false);
  expect(sessionStorage.getItem(key)).toBe(previous);
  expect(readDraft()).toEqual(backup);

  // A pre-existing oversized record must be rejected by the same limits.
  sessionStorage.setItem(key, JSON.stringify(oversized));
  expect(readDraft()).toBeNull();
});

const rawBoundary = { ...backup, draft: '', prompt: '' };
const remaining = 600_000 - JSON.stringify(rawBoundary).length;
rawBoundary.draft = '\0'.repeat(Math.floor(remaining / 6)) + 'y'.repeat(remaining % 6);

it.each([
  ['prompt', { ...backup, prompt: 'p'.repeat(16_000) }],
  ['YAML', { ...backup, draft: 'y'.repeat(262_144) }],
  ['serialized record', rawBoundary],
] as const)('round-trips the inclusive %s limit', (_name, value) => {
  if (_name === 'serialized record') expect(JSON.stringify(value)).toHaveLength(600_000);
  expect(storeDraft(value)).toBe(true);
  expect(readDraft()).toEqual(value);
});
