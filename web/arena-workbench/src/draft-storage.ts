const key = 'arena.editor.draft.v1';

export interface RecoverableDraft {
  version: 1;
  documentId: string;
  viewId: string;
  sourceHash: string;
  draft: string;
  prompt: string;
}

// Share the exact shape and size checks so every successful write can be recovered.
function parseDraft(raw: string | null): RecoverableDraft | null {
  if (!raw || raw.length > 600_000) return null;
  const value = JSON.parse(raw);
  if (value?.version !== 1 || !['documentId', 'viewId', 'sourceHash', 'draft', 'prompt'].every(
    field => typeof value[field] === 'string',
  )) return null;
  if (value.draft.length > 262_144 || value.prompt.length > 16_000) return null;
  return {
    version: 1, documentId: value.documentId, viewId: value.viewId,
    sourceHash: value.sourceHash, draft: value.draft, prompt: value.prompt,
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
