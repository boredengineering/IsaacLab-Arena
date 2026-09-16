export interface EditorSaveRequest {
  idempotency_key: string;
  yaml_text: string;
  document_id?: string;
  expected_source_hash?: string;
}
export interface EditorRevision {
  revision_id: string;
  yaml_text: string;
  source_hash: string;
  canonical_hash: string;
  download_url: string;
  open_source: { kind: 'editor_revision'; id: string };
}
export interface EditorSaveReceipt {
  schema_version: 1;
  idempotency_key: string;
  request_sha256: string;
  state: 'committed';
  revision: EditorRevision;
}
export async function editorSourceHash(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}
export function editorSaveRequestHash(request: Pick<EditorSaveRequest, 'yaml_text' | 'document_id' | 'expected_source_hash'>) {
  return editorSourceHash(JSON.stringify(['editor-save/v1', request.yaml_text, request.document_id ?? null, request.expected_source_hash ?? null]));
}
export async function decodeEditorSaveReceipt(value: unknown, request: EditorSaveRequest): Promise<EditorSaveReceipt> {
  const invalid = () => new Error('Invalid editor save receipt');
  const exact = (v: unknown, keys: string[]) => !!v && typeof v === 'object' && !Array.isArray(v)
    && Object.keys(v).sort().join(',') === keys.sort().join(',');
  let serialized: string;
  try { serialized = JSON.stringify(value); } catch { throw invalid(); }
  if (typeof serialized !== 'string' || new TextEncoder().encode(serialized).length > 256 * 1024) throw invalid();
  // Detach the wire value before asynchronous digest checks.
  const receipt = JSON.parse(serialized) as EditorSaveReceipt;
  const revision = receipt?.revision;
  if (!exact(receipt, ['schema_version', 'state', 'idempotency_key', 'request_sha256', 'revision'])
    || !exact(revision, ['revision_id', 'yaml_text', 'source_hash', 'canonical_hash', 'download_url', 'open_source'])
    || !exact(revision?.open_source, ['kind', 'id'])
    || typeof revision?.revision_id !== 'string' || !/^[a-f0-9]{32}$/.test(revision.revision_id)
    || typeof revision.canonical_hash !== 'string' || !/^[a-f0-9]{64}$/.test(revision.canonical_hash)
    || revision.download_url !== `/api/editor/revisions/${revision.revision_id}/download`
    || revision.open_source.kind !== 'editor_revision' || revision.open_source.id !== `editor-revision:${revision.revision_id}`) throw invalid();
  if (receipt?.schema_version !== 1 || receipt.state !== 'committed'
    || receipt.idempotency_key !== request.idempotency_key
    || receipt.request_sha256 !== await editorSaveRequestHash(request)
    || receipt.revision?.yaml_text !== request.yaml_text
    || receipt.revision.source_hash !== await editorSourceHash(request.yaml_text)) throw new Error('Invalid editor save receipt');
  return Object.freeze({ schema_version: 1, idempotency_key: receipt.idempotency_key,
    request_sha256: receipt.request_sha256, state: 'committed',
    revision: Object.freeze({ revision_id: revision.revision_id, yaml_text: revision.yaml_text,
      source_hash: revision.source_hash, canonical_hash: revision.canonical_hash,
      download_url: revision.download_url,
      open_source: Object.freeze({ kind: 'editor_revision', id: revision.open_source.id }),
    }),
  });
}
