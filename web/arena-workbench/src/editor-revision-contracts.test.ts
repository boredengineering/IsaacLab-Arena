import { createHash, webcrypto } from 'node:crypto';
import { beforeAll, expect, it } from 'vitest';
import { decodeEditorSaveReceipt, editorSaveRequestHash, editorSourceHash } from './editor-revision-contracts';

beforeAll(() => { Object.defineProperty(globalThis, 'crypto', { configurable: true, value: webcrypto }); });
const hash = (text: string) => createHash('sha256').update(text).digest('hex');
const request = { idempotency_key: 'test-save-1', yaml_text: 'name: café\n', document_id: 'view:old', expected_source_hash: 'a'.repeat(64) };
function receipt() {
  const id = 'b'.repeat(32);
  return { schema_version: 1, idempotency_key: request.idempotency_key,
    request_sha256: hash(JSON.stringify(['editor-save/v1', request.yaml_text, request.document_id, request.expected_source_hash])), state: 'committed',
    revision: { revision_id: id, yaml_text: request.yaml_text, source_hash: hash(request.yaml_text), canonical_hash: 'c'.repeat(64),
      download_url: `/api/editor/revisions/${id}/download`, open_source: { kind: 'editor_revision', id: `editor-revision:${id}` } } };
}
it('normalizes wire key order and returns detached immutable checked fields', async () => {
  const value = receipt();
  const reordered = Object.fromEntries(Object.entries(value).reverse());
  const checked = await decodeEditorSaveReceipt(reordered, request);
  expect(JSON.stringify(checked)).toBe(JSON.stringify(await decodeEditorSaveReceipt(value, request)));
  expect(Object.isFrozen(checked.revision.open_source)).toBe(true);
  expect(Object.isFrozen(checked.revision)).toBe(true);
});
it.each([
  ['revision id', (r: ReturnType<typeof receipt>) => { r.revision.revision_id = 'BAD'; }],
  ['canonical hash', (r: ReturnType<typeof receipt>) => { r.revision.canonical_hash = 'bad'; }],
  ['open descriptor', (r: ReturnType<typeof receipt>) => { r.revision.open_source.id = 'editor-revision:other'; }],
  ['download URL', (r: ReturnType<typeof receipt>) => { r.revision.download_url = 'https://evil.test/'; }],
  ['extra field', (r: ReturnType<typeof receipt>) => { Object.assign(r, { unexpected: true }); }],
  ['oversized ACK', (r: ReturnType<typeof receipt>) => { Object.assign(r, { extra: 'x'.repeat(262145) }); }],
  ['wrong request', (r: ReturnType<typeof receipt>) => { r.request_sha256 = '0'.repeat(64); }],
  ['wrong raw source', (r: ReturnType<typeof receipt>) => { r.revision.source_hash = '0'.repeat(64); }],
  ['changed YAML', (r: ReturnType<typeof receipt>) => { r.revision.yaml_text += '\\n'; }],
])('rejects %s', async (_, alter) => {
  const value = receipt(); alter(value);
  await expect(decodeEditorSaveReceipt(value, request)).rejects.toThrow('Invalid editor save receipt');
});
it('hashes exact UTF8 source and compact versioned request tuple; decodes only bound committed receipts', async () => {
  expect(await editorSourceHash(request.yaml_text)).toBe(hash(request.yaml_text));
  expect(await editorSaveRequestHash(request)).toBe(receipt().request_sha256);
  expect(await editorSaveRequestHash({ yaml_text: '' })).toBe(hash('["editor-save/v1","",null,null]'));
  expect(await decodeEditorSaveReceipt(receipt(), request)).toEqual(receipt());
});
