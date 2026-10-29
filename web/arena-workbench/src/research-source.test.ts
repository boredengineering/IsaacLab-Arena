import { expect, it } from 'vitest';
import { researchSource, sameResearchSource, manualInput, researchOpen } from './research-source';
const hash = 'a'.repeat(64), id = 'b'.repeat(32);
const manual = { kind: 'editor_revision', schema_version: 1, editor_revision_id: id, source_hash: hash, canonical_hash: hash, bundle_codec: 'arena-editor-bundle/v1', bundle_sha256: hash, receipt_sha256: hash } as const;
const candidate = { job_id: id, attempt_id: id, generation: 1, receipt_sha256: hash, request_sha256: hash };
it('decodes the exact source union without tagging or changing legacy JSON', () => {
  expect(researchSource(candidate)).toBe(true);
  expect(researchSource(manual)).toBe(true);
  expect(sameResearchSource(candidate, {...candidate})).toBe(true);
  expect(sameResearchSource(manual, {...manual, bundle_sha256: 'c'.repeat(64)})).toBe(false);
  expect(manualInput(manual)).toEqual({kind: 'editor_revision', editor_revision_id: id, source_hash: hash, canonical_hash: hash});
  for (const source of [{...candidate, kind: 'accepted_candidate'}, {...manual, job_id: id}, {...manual, schema_version: true}, {...manual, bundle_codec: 'unknown'}, {...manual, source_hash: hash.toUpperCase()}]) expect(researchSource(source)).toBe(false);
});
it('binds an exact opening to source and manifest file hashes without invented canonical provenance', () => {
  const reservation = {store_id: 'local', family: 'Example', reservation_id: id, revision_id: id, version: 1, source: candidate};
  const manifest = {digest: hash, files: {'environment.yaml': {sha256: hash, size: 10}}};
  const opened = researchOpen(reservation, manifest);
  expect(opened).toMatchObject({id: `research-version:local:${id}:${hash}`, kind: 'research_version', source_hash: hash, research_identity: {...reservation, manifest_digest: hash}});
  expect(opened.canonical_hash).toBeUndefined();
  expect(researchOpen({...reservation, source: manual}, manifest).canonical_hash).toBe(hash);
  expect(() => researchOpen({...reservation, source: manual}, {...manifest, files: {'environment.yaml': {sha256: 'c'.repeat(64), size: 10}}})).toThrow();
});
