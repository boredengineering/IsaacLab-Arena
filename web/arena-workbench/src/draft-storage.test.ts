import { beforeEach, expect, it, vi } from 'vitest';
import { readDraft, storeDraft, inspectDraft, compareDraft, type RecoverableDraft } from './draft-storage';

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

it('checks an already absent clean backup without a redundant removal', () => {
  const remove = vi.spyOn(Storage.prototype, 'removeItem');
  expect(compareDraft(sessionStorage, null, null)).toEqual({status: 'written', raw: null});
  expect(remove).not.toHaveBeenCalled();
});

it('conditionally writes and removes only the exact inspected backup', () => {
  storeDraft(backup);
  const baseline = inspectDraft(sessionStorage);
  expect(baseline.status).toBe('valid');
  const sibling = JSON.stringify({...backup, draft: 'sibling'});
  sessionStorage.setItem(key, sibling);
  expect(compareDraft(sessionStorage, baseline.raw!, null).status).toBe('conflict');
  expect(compareDraft(sessionStorage, baseline.raw!, backup).status).toBe('conflict');
  expect(sessionStorage.getItem(key)).toBe(sibling);
  expect(compareDraft(sessionStorage, sibling, backup).status).toBe('written');
  expect(compareDraft(sessionStorage, JSON.stringify(backup), null).status).toBe('written');
  expect(inspectDraft(sessionStorage).status).toBe('absent');
  sessionStorage.setItem(key, '');
  expect(inspectDraft(sessionStorage).status).toBe('invalid-record');
});

it('round-trips v2 metadata at its independent inclusive envelope bound', () => {
  const value = {...backup, version: 2 as const, draftId: '12345678-1234-4123-8123-123456789abc', revision: Number.MAX_SAFE_INTEGER, draft: '', prompt: ''};
  const remaining = 601_024 - JSON.stringify(value).length;
  value.draft = '\0'.repeat(Math.floor(remaining / 6)) + 'y'.repeat(remaining % 6);
  expect(JSON.stringify(value)).toHaveLength(601_024);
  expect(storeDraft(value)).toBe(true);
  expect(readDraft()).toEqual(value);
  expect(storeDraft({...value, draft: value.draft + 'x'})).toBe(false);
  expect(readDraft()).toEqual(value);
});

const revisionBackup = {...backup, documentId: `editor-revision:${'a'.repeat(32)}`, viewId: 'b'.repeat(32), sourceHash: 'c'.repeat(64)};
const researchIdentity = {store_id: 'local', reservation_id: 'd'.repeat(32), revision_id: 'e'.repeat(32), family: 'Example', version: 2, manifest_digest: 'f'.repeat(64), source: {job_id: 'a'.repeat(32), attempt_id: 'b'.repeat(32), generation: 1, receipt_sha256: 'c'.repeat(64), request_sha256: 'd'.repeat(64)}};
const researchBackup = {...revisionBackup, documentId: `research-version:local:${researchIdentity.reservation_id}:${researchIdentity.manifest_digest}`, researchIdentity};
it('round-trips exact research identity alongside descriptor, fresh view and raw hash', () => {
  expect(storeDraft(researchBackup)).toBe(true);
  expect(readDraft()).toEqual(researchBackup);
});
it.each([
  {documentId: 'research-version:local:latest'}, {documentId: researchBackup.documentId.replace('local', 'other')},
  {viewId: 'unfrozen'}, {sourceHash: 'broken'}, {researchIdentity: {...researchIdentity, version: 0}},
])('rejects malformed research recovery without erasing valid bytes: %j', invalid => {
  expect(storeDraft(researchBackup)).toBe(true);
  expect(storeDraft({...researchBackup, ...invalid})).toBe(false);
  expect(readDraft()).toEqual(researchBackup);
});
it('round-trips an immutable source ID separately from its frozen view ID', () => {
  expect(storeDraft(revisionBackup)).toBe(true);
  expect(readDraft()).toEqual(revisionBackup);
});
it.each([
  {documentId: 'editor-revision:latest'}, {documentId: `editor-revision:${'a'.repeat(33)}`},
  {documentId: `editor-revision:${'A'.repeat(32)}`}, {documentId: '../escape'},
  {viewId: 'b'.repeat(33)}, {viewId: 'unfrozen'}, {sourceHash: 'c'.repeat(63)},
])('rejects invalid source/view/hash grammar without erasing a recoverable revision: %j', malformed => {
  expect(storeDraft(revisionBackup)).toBe(true);
  expect(storeDraft({...revisionBackup, ...malformed})).toBe(false);
  expect(readDraft()).toEqual(revisionBackup);
  sessionStorage.setItem(key, JSON.stringify({...revisionBackup, ...malformed}));
  expect(readDraft()).toBeNull();
});

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
