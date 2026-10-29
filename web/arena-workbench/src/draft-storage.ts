import { researchIdentity, researchDescriptor, type ResearchIdentity } from './research-source';
const key = 'arena.editor.draft.v1';

export type DraftStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export function draftStorage(): DraftStorage | null {
  try { return globalThis.sessionStorage; } catch { return null; }
}
export type DraftInspection = {status: 'absent' | 'valid' | 'invalid-record' | 'unavailable'; raw: string | null; value: RecoverableDraft | null};
export function inspectDraft(storage: DraftStorage | null): DraftInspection {
  let raw: string | null;
  try { if (!storage) throw new Error(); raw = storage.getItem(key); }
  catch { return {status: 'unavailable', raw: null, value: null}; }
  if (raw === null) return {status: 'absent', raw, value: null};
  try {
    const value = parseDraft(raw);
    return {status: value ? 'valid' : 'invalid-record', raw, value};
  } catch { return {status: 'invalid-record', raw, value: null}; }
}
export function compareDraft(storage: DraftStorage | null, expected: string | null, value: RecoverableDraft | null): {status: 'written' | 'conflict' | 'unavailable' | 'invalid-record'; raw?: string | null} {
  try {
    const raw = value === null ? null : JSON.stringify(value);
    if (raw !== null && !parseDraft(raw)) return {status: 'invalid-record'};
    if (!storage) return {status: 'unavailable'};
    if (storage.getItem(key) !== expected) return {status: 'conflict'};
    if (raw === expected) return {status: 'written', raw};
    if (raw === null) storage.removeItem(key); else storage.setItem(key, raw);
    // A successful set followed by failed readback is ambiguous. Never roll back.
    if (storage.getItem(key) !== raw) return {status: 'conflict'};
    return {status: 'written', raw};
  } catch { return {status: 'unavailable'}; }
}

interface DraftFields {
  documentId: string;
  viewId: string;
  sourceHash: string;
  draft: string;
  prompt: string;
  researchIdentity?: ResearchIdentity;
}
export type RecoverableDraft = DraftFields & ({version: 1} | {version: 2; draftId: string; revision: number});

// Share the exact shape and size checks so every successful write can be recovered.
export function parseDraft(raw: string | null): RecoverableDraft | null {
  if (!raw || raw.length > 601_024) return null;
  const value = JSON.parse(raw);
  if (value?.version !== 1 && value?.version !== 2) return null;
  if (value.version === 1 && raw.length > 600_000) return null;
  if (value.version === 2 && (typeof value.draftId !== 'string' || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value.draftId)
    || !Number.isSafeInteger(value.revision) || value.revision < 0)) return null;
  if (!['documentId', 'viewId', 'sourceHash', 'draft', 'prompt'].every(
    field => typeof value[field] === 'string',
  )) return null;
  if (value.draft.length > 262_144 || value.prompt.length > 16_000) return null;
  const identifier = (text: string) => text.length > 0 && text.length <= 256 && /^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(text);
  if (!identifier(value.documentId) || !identifier(value.viewId) || value.sourceHash.length > 64) return null;
  // Immutable selection IDs are descriptors, not frozen view IDs. Keep both
  // grammars exact; accepting a descriptor must not loosen view/hash evidence.
  if (value.documentId.startsWith('editor-revision:') && (!/^editor-revision:[a-f0-9]{32}$/.test(value.documentId)
    || !/^[a-f0-9]{32}$/.test(value.viewId) || !/^[a-f0-9]{64}$/.test(value.sourceHash))) return null;
  if (value.documentId.startsWith('research-version:')) {
    if (!researchIdentity(value.researchIdentity) || researchDescriptor(value.researchIdentity) !== value.documentId || !/^[a-f0-9]{32}$/.test(value.viewId) || !/^[a-f0-9]{64}$/.test(value.sourceHash)) return null;
    if ('kind' in value.researchIdentity.source && value.sourceHash !== value.researchIdentity.source.source_hash) return null;
  } else if (value.researchIdentity !== undefined) return null;
  return {
    ...(value.version === 1 ? {version: 1 as const} : {version: 2 as const, draftId: value.draftId, revision: value.revision}), documentId: value.documentId, viewId: value.viewId,
    sourceHash: value.sourceHash, draft: value.draft, prompt: value.prompt,
    ...(value.researchIdentity ? {researchIdentity: value.researchIdentity} : {}),
  };
}

/** Read browser-local inputs only; validation and source context must be checked again. */
export function readDraft(): RecoverableDraft | null {
  try {
    return parseDraft(sessionStorage.getItem(key));
  } catch {
    return null;
  }
}

export function storeDraft(value: RecoverableDraft | null): boolean {
  try {
    if (value) {
      const raw = JSON.stringify(value);
      if (!parseDraft(raw)) return false;
      sessionStorage.setItem(key, raw);
    } else sessionStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export function downloadRecoveredYaml(text: string, filename = 'arena-recovered-draft.yaml'): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/yaml' }));
  const link = globalThis.document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
