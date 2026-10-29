import { researchIdentity, researchDescriptor, type ResearchIdentity } from './research-source';
/** Public catalogue metadata only. No document bytes, providers or API clients. */
export interface SourceSummary {
  id: string;
  name: string;
  source: string;
  kind: 'discovered_file' | 'editor_revision' | 'research_version';
  research_identity?: ResearchIdentity;
  revision_id?: string;
  source_hash?: string;
  canonical_hash?: string;
}
export type SourcesStatus = 'ready' | 'loading' | 'unavailable';
export type InspectedSource = LibraryReference & Partial<Pick<SourceSummary, 'name' | 'source'>>;
export type ReferenceState = 'available' | 'missing' | 'corrupt' | 'unavailable';
export const referenceStateLabel: Record<ReferenceState, string> = {
  available: 'Exact reference available', missing: 'Missing exact reference',
  corrupt: 'Corrupt or conflicting reference metadata', unavailable: 'Reference unavailable',
};
export const metadataFields = [
  ['id', 'Source ID'], ['name', 'Name'], ['source', 'Source'], ['kind', 'Kind'],
  ['revision_id', 'Revision ID'], ['source_hash', 'Source hash'], ['canonical_hash', 'Canonical hash'],
] as const;
export function resolveLibraryReference(ref: LibraryReference, catalogue: ReturnType<typeof normalizeLibrarySources>, status: SourcesStatus): { state: ReferenceState; source?: SourceSummary } {
  if (status !== 'ready') return { state: 'unavailable' };
  if (catalogue.invalidIds.has(ref.id)) return { state: 'corrupt' };
  const source = catalogue.sources.find(row => row.id === ref.id);
  if (!source) return { state: 'missing' };
  if (referenceKey(ref) !== referenceKey(source)) return { state: 'corrupt' };
  return { state: 'available', source };
}

export type LibraryReference = Pick<SourceSummary, 'id' | 'kind' | 'revision_id' | 'source_hash' | 'canonical_hash' | 'research_identity'>;
export const LIBRARY_PIN_LIMIT = 8;
export const LIBRARY_RECENT_LIMIT = 12;
export const LIBRARY_PREFERENCES_KEY = 'arena.environment-library.v1';
export const LIBRARY_PREFERENCES_LIMIT = 16384;
export interface LibraryPreferences { version: 1; pins: LibraryReference[]; recents: LibraryReference[] }
export const emptyLibraryPreferences = (): LibraryPreferences => ({ version: 1, pins: [], recents: [] });

/** Strict local hints, never a success receipt or authority to open a document. */
export function decodeLibraryPreferences(raw: string): LibraryPreferences | undefined {
  if (raw.length > LIBRARY_PREFERENCES_LIMIT) return;
  try {
    const value = record(JSON.parse(raw));
    if (!value || Object.keys(value).sort().join(',') !== 'pins,recents,version' || value.version !== 1) return;
    const parseRefs = (items: unknown, limit: number, pins: boolean) => {
      if (!Array.isArray(items) || items.length > limit) return;
      const refs: LibraryReference[] = [];
      const seen = new Set<string>();
      for (const item of items) {
        const row = record(item);
        if (!row || !['discovered_file', 'editor_revision', 'research_version'].includes(row.kind as string)
          || Object.keys(row).some(key => !referenceFields.some(field => field === key))) return;
        const source = normalizeLibrarySource({ ...row, name: 'Reference', source: 'Reference' });
        if (!source || ((pins || source.kind === 'editor_revision') && !isCompleteRevision(source))) return;
        const ref = libraryReference(source);
        const key = referenceKey(ref);
        if (seen.has(key)) return;
        seen.add(key); refs.push(ref);
      }
      return refs;
    };
    const pins = parseRefs(value.pins, LIBRARY_PIN_LIMIT, true);
    const recents = parseRefs(value.recents, LIBRARY_RECENT_LIMIT, false);
    if (!pins || !recents) return;
    return { version: 1, pins, recents };
  } catch { return; }
}

export const referenceFields = ['id', 'kind', 'revision_id', 'source_hash', 'canonical_hash', 'research_identity'] as const;
export function libraryReference(source: LibraryReference): LibraryReference {
  return {
    id: source.id, kind: source.kind,
    ...(source.revision_id !== undefined ? { revision_id: source.revision_id } : {}),
    ...(source.source_hash !== undefined ? { source_hash: source.source_hash } : {}),
    ...(source.canonical_hash !== undefined ? { canonical_hash: source.canonical_hash } : {}),
    ...(source.research_identity !== undefined ? { research_identity: { ...source.research_identity, source: { ...source.research_identity.source } } } : {}),
  };
}
export const referenceKey = (source: LibraryReference) => JSON.stringify(referenceFields.map(field => source[field] ?? null));
export const isCompleteRevision = (source: LibraryReference) => !!source.revision_id && !!source.source_hash && (source.kind === 'editor_revision' && !!source.canonical_hash || source.kind === 'research_version' && researchIdentity(source.research_identity) && source.id === researchDescriptor(source.research_identity));

const record = (value: unknown): Record<string, unknown> | undefined => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
const text = (value: unknown, limit: number): value is string => typeof value === 'string' && value.length > 0 && value.length <= limit && !/[\x00-\x1f\x7f]/.test(value);
const hash = (value: unknown): value is string => text(value, 64) && /^[a-f0-9]{64}$/.test(value);

export function normalizeLibrarySource(value: unknown): SourceSummary | undefined {
  const row = record(value);
  if (!row || !text(row.id, 256) || !/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(row.id)
    || !text(row.name, 512) || !text(row.source, 2048)) return;
  const kind = row.kind === undefined ? 'discovered_file' : row.kind;
  if (kind !== 'discovered_file' && kind !== 'editor_revision' && kind !== 'research_version') return;
  if (kind === 'research_version') {
    if (!researchIdentity(row.research_identity) || row.id !== researchDescriptor(row.research_identity) || row.revision_id !== row.research_identity.revision_id || !hash(row.source_hash)) return;
    if ('kind' in row.research_identity.source && (row.source_hash !== row.research_identity.source.source_hash || row.canonical_hash !== row.research_identity.source.canonical_hash)) return;
  } else if (row.id.startsWith('research-version:') || row.research_identity !== undefined) return;
  else if (kind === 'editor_revision') {
    if (!text(row.revision_id, 32) || !/^[a-f0-9]{32}$/.test(row.revision_id)
      || row.id !== `editor-revision:${row.revision_id}`) return;
  } else if (row.id.startsWith('editor-revision:') || row.revision_id !== undefined) return;
  if (row.source_hash !== undefined && !hash(row.source_hash)) return;
  if (row.canonical_hash !== undefined && !hash(row.canonical_hash)) return;
  return {
    id: row.id, name: row.name, source: row.source, kind,
    ...(kind === 'editor_revision' || kind === 'research_version' ? { revision_id: row.revision_id as string } : {}),
    ...(kind === 'research_version' ? { research_identity: { ...(row.research_identity as ResearchIdentity), source: { ...(row.research_identity as ResearchIdentity).source } } } : {}),
    ...(row.source_hash !== undefined ? { source_hash: row.source_hash as string } : {}),
    ...(row.canonical_hash !== undefined ? { canonical_hash: row.canonical_hash as string } : {}),
  };
}

/** Quarantine all ambiguous occurrences, even when one duplicate is malformed. */
export function normalizeLibrarySources(value: unknown): { sources: SourceSummary[]; issues: string[]; invalidIds: Set<string> } {
  const invalidIds = new Set<string>();
  if (!Array.isArray(value)) return { sources: [], issues: ['Malformed source catalogue.'], invalidIds };
  const counts = new Map<string, number>();
  for (const item of value) {
    const id = record(item)?.id;
    if (text(id, 256)) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  const sources: SourceSummary[] = [];
  let malformed = false;
  let duplicate = false;
  for (const item of value) {
    const row = normalizeLibrarySource(item);
    const id = record(item)?.id;
    if (typeof id === 'string' && (counts.get(id) ?? 0) > 1) {
      duplicate = true;
      invalidIds.add(id);
    } else if (row) sources.push(row);
    else {
      malformed = true;
      if (text(id, 256)) invalidIds.add(id);
    }
  }
  return { sources, invalidIds, issues: [
    ...(duplicate ? ['Duplicate source identity: all ambiguous rows withheld.'] : []),
    ...(malformed ? ['Malformed source metadata: unsafe rows withheld.'] : []),
  ] };
}
