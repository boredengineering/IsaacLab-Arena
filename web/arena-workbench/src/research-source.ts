/** Exact research wire codecs. Never tag or rewrite hashed legacy candidate JSON. */
export const record = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {};
export const token = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(v);
export const uuid = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{32}$/.test(v);
export const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
export interface CandidateSource { job_id: string; attempt_id: string; generation: number; receipt_sha256: string; request_sha256: string }
export interface ManualInput { kind: 'editor_revision'; editor_revision_id: string; source_hash: string; canonical_hash: string }
export interface ManualSource extends ManualInput { schema_version: 1; bundle_codec: 'arena-editor-bundle/v1'; bundle_sha256: string; receipt_sha256: string }
export type ResearchSource = CandidateSource | ManualSource;
const candidateFields = ['job_id', 'attempt_id', 'generation', 'receipt_sha256', 'request_sha256'];
const manualFields = ['kind', 'schema_version', 'editor_revision_id', 'source_hash', 'canonical_hash', 'bundle_codec', 'bundle_sha256', 'receipt_sha256'];
const inputFields = ['kind', 'editor_revision_id', 'source_hash', 'canonical_hash'];
const exact = (r: Record<string, unknown>, keys: string[]) => Object.keys(r).length === keys.length && keys.every(k => k in r);
export function isManualInput(v: unknown): v is ManualInput { const r = record(v); return exact(r, inputFields) && r.kind === 'editor_revision' && uuid(r.editor_revision_id) && hash(r.source_hash) && hash(r.canonical_hash); }
export function researchSource(v: unknown): v is ResearchSource {
  const r = record(v);
  if (exact(r, candidateFields)) return uuid(r.job_id) && uuid(r.attempt_id) && typeof r.generation === 'number' && Number.isSafeInteger(r.generation) && r.generation > 0 && hash(r.receipt_sha256) && hash(r.request_sha256);
  return exact(r, manualFields) && r.kind === 'editor_revision' && r.schema_version === 1 && r.bundle_codec === 'arena-editor-bundle/v1' && uuid(r.editor_revision_id) && ['source_hash', 'canonical_hash', 'bundle_sha256', 'receipt_sha256'].every(k => hash(r[k]));
}
export function manualInput(v: ManualInput): ManualInput { return {kind: 'editor_revision', editor_revision_id: v.editor_revision_id, source_hash: v.source_hash, canonical_hash: v.canonical_hash}; }
export function sameResearchSource(a: unknown, b: unknown) { return researchSource(a) && researchSource(b) && Object.keys(a).length === Object.keys(b).length && Object.entries(a).every(([k, v]) => record(b)[k] === v); }
export function sourceLabel(source: ResearchSource | ManualInput) { return 'kind' in source ? `Editor revision ${source.editor_revision_id}; source ${source.source_hash}; canonical ${source.canonical_hash}` : `Source job ${source.job_id}, attempt ${source.attempt_id}, generation ${source.generation}`; }
export interface ResearchIdentity { store_id: string; reservation_id: string; revision_id: string; family: string; version: number; manifest_digest: string; source: ResearchSource }
export function researchIdentity(v: unknown): v is ResearchIdentity {
  const r = record(v); return exact(r, ['store_id', 'reservation_id', 'revision_id', 'family', 'version', 'manifest_digest', 'source']) && token(r.store_id) && uuid(r.reservation_id) && uuid(r.revision_id) && token(r.family) && typeof r.version === 'number' && Number.isSafeInteger(r.version) && r.version > 0 && hash(r.manifest_digest) && researchSource(r.source);
}
export function sameResearchIdentity(a: unknown, b: unknown) { return researchIdentity(a) && researchIdentity(b) && ['store_id', 'reservation_id', 'revision_id', 'family', 'version', 'manifest_digest'].every(k => record(a)[k] === record(b)[k]) && sameResearchSource(a.source, b.source); }
export const researchDescriptor = (r: ResearchIdentity) => `research-version:${r.store_id}:${r.reservation_id}:${r.manifest_digest}`;
export const isResearchDescriptor = (v: unknown): v is string => typeof v === 'string' && /^research-version:[A-Za-z0-9][A-Za-z0-9_-]{0,63}:[a-f0-9]{32}:[a-f0-9]{64}$/.test(v);
export interface ResearchOpen { id: string; kind: 'research_version'; name: string; source: string; revision_id: string; source_hash: string; canonical_hash?: string; research_identity: ResearchIdentity }
export function researchOpen(reservation: Record<string, unknown>, manifest: Record<string, unknown>): ResearchOpen {
  const {store_id, reservation_id, revision_id, family, version, source} = reservation;
  const identity = {store_id, reservation_id, revision_id, family, version, source, manifest_digest: manifest.digest};
  const file = record(record(manifest.files)['environment.yaml']);
  if (!researchIdentity(identity) || !hash(file.sha256) || typeof file.size !== 'number' || !Number.isSafeInteger(file.size) || file.size < 0 || file.size > 262_144) throw new Error('Exact research opening evidence unavailable.');
  const manual = 'kind' in identity.source ? identity.source : undefined;
  if (manual && manual.source_hash !== file.sha256) throw new Error('Research root hash conflict.');
  const id = researchDescriptor(identity);
  return {id, kind: 'research_version', name: `${identity.family} v${identity.version}`, source: id, revision_id: identity.revision_id, source_hash: file.sha256, ...(manual ? {canonical_hash: manual.canonical_hash} : {}), research_identity: identity};
}
