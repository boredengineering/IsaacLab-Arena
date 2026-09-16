import type { EditorDocument, Validation } from './editor-contracts';
import { compareDraft, draftStorage, inspectDraft, type DraftStorage, type RecoverableDraft } from './draft-storage';
import { sameResearchIdentity } from './research-source';

export type OwnedValidation = {text: string; result: Validation; owner: string};
export const NEW_DOCUMENT = 'local:new-environment';
export function advanceDraftRevision(value: number): number | null {
  return Number.isSafeInteger(value) && value >= 0 && value < Number.MAX_SAFE_INTEGER ? value + 1 : null;
}
export interface DraftSnapshot {
  documentId: string;
  loadedDocumentId: string;
  document: EditorDocument | null;
  draft: string;
  prompt: string;
  validation: OwnedValidation | null;
  recovery: RecoverableDraft | null;
  revision: number;
  activation?: number;
  reconciliation?: boolean;
  loadRequest?: number;
  exhausted?: boolean;
  storageStatus: 'ready' | 'unavailable' | 'conflict' | 'invalid-record';
}

export interface DraftHandler {instance: symbol; revision: number; generation: number; status: DraftSnapshot['storageStatus']}
export interface DraftOperation extends DraftHandler {operation: number; baseline: string | null}

// One key, scoped to the actual Storage object. Bookkeeping only: no content or clients.
const leases = new WeakMap<DraftStorage, {instance: symbol | null; generation: number}>();

/** Retained authoring content. Transient loading and validation never flush backups. */
export class DraftController {
  private state: DraftSnapshot = {documentId: '', loadedDocumentId: '', document: null, draft: '', prompt: '', validation: null, recovery: null, revision: 0, storageStatus: 'ready'};
  private listeners = new Set<() => void>();
  private initialized = false;
  private storage: DraftStorage | null = null;
  private baseline: string | null = null;
  private draftId = '';
  private active = false;
  private generation = 0;
  private operation = 0;
  private instance = Symbol('draft owner');
  private selectionRevision = 0;
  private localIntent = false;
  private explicitMemoryLoad = false;
  private activation = Symbol('inert');
  constructor(private storageProvider: () => DraftStorage | null = draftStorage) {}
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => {this.listeners.add(listener); return () => {this.listeners.delete(listener);};};
  // Compatibility read-only projections; there is no mirrored mutable cache value.
  get draft() { return this.state.draft; }
  get document() { return this.state.document; }
  get validation() { return this.state.validation; }
  get storedBackup() { return this.baseline; }
  get pristineAuthoring() { return !this.localIntent; }
  get unboundAuthoring() { return !this.state.loadedDocumentId && this.localIntent; }
  private publish(update: Partial<DraftSnapshot>) {
    if (Object.entries(update).every(([key, value]) => this.state[key as keyof DraftSnapshot] === value)) return;
    this.state = {...this.state, ...update};
    this.listeners.forEach(listener => listener());
  }
  private nextRevision() {
    const revision = advanceDraftRevision(this.state.revision);
    if (revision === null) this.publish({exhausted: true, storageStatus: 'unavailable'});
    return revision;
  }
  activate() {
    this.active = true;
    const activation = this.activation = Symbol('activation');
    if (!this.initialized) {
      this.initialized = true;
      this.storage = this.storageProvider();
      const read = inspectDraft(this.storage);
      this.baseline = read.raw;
      this.draftId = crypto.randomUUID();
      this.publish({recovery: read.value, documentId: read.value?.documentId ?? '',
        loadedDocumentId: read.value?.documentId === NEW_DOCUMENT ? NEW_DOCUMENT : '',
        storageStatus: read.status === 'valid' || read.status === 'absent' ? 'ready' : read.status});
    }
    const generation = advanceDraftRevision(Math.max(this.generation, this.storage ? leases.get(this.storage)?.generation ?? 0 : 0));
    if (generation === null) {this.active = false; this.publish({exhausted: true, storageStatus: 'unavailable'}); return () => {};}
    this.generation = generation;
    if (this.storage) leases.set(this.storage, {instance: this.instance, generation});
    this.checkBaseline();
    this.publish({activation: generation});
    return () => {
      if (activation !== this.activation) return;
      if (this.storage && this.ownsLease()) leases.set(this.storage, {instance: null, generation: this.generation});
      this.active = false; this.operation++;
    };
  }
  private ownsLease() {
    const lease = this.storage ? leases.get(this.storage) : undefined;
    return this.active && (!this.storage || lease?.instance === this.instance && lease.generation === this.generation);
  }
  handler(): DraftHandler { return {instance: this.instance, revision: this.state.revision, generation: this.generation, status: this.state.storageStatus}; }
  live(handler: DraftHandler) { return this.ownsLease() && handler.instance === this.instance && handler.generation === this.generation; }
  eligible(handler: DraftHandler) {
    return !this.state.exhausted && this.live(handler) && handler.revision === this.state.revision && handler.status === this.state.storageStatus;
  }
  begin(handler: DraftHandler): DraftOperation | null {
    if (!this.eligible(handler) || !this.checkBaseline()) return null;
    return {...handler, operation: ++this.operation, baseline: this.baseline};
  }
  private checkBaseline(allowInvalid = false) {
    if (this.state.storageStatus === 'unavailable') return true;
    if (this.state.storageStatus !== 'ready' && !(allowInvalid && this.state.storageStatus === 'invalid-record')) return false;
    const read = inspectDraft(this.storage);
    if (read.status === 'unavailable') {this.publish({storageStatus: 'unavailable'}); return false;}
    if (read.raw !== this.baseline) {this.publish({storageStatus: 'conflict'}); return false;}
    return true;
  }
  check(token: DraftOperation) {
    return this.eligible(token) && token.operation === this.operation && token.baseline === this.baseline && this.checkBaseline();
  }
  setValidation(validation: OwnedValidation | null, handler = this.handler()) { if (this.live(handler)) this.publish({validation}); }
  select(documentId: string, operation?: DraftOperation) {
    if (!this.ownsLease() || (operation ? !this.check(operation) : !this.pristineAuthoring)) return;
    const revision = this.nextRevision();
    if (revision === null) return;
    this.selectionRevision = revision;
    this.explicitMemoryLoad = operation?.status === 'unavailable';
    this.publish({documentId, revision: this.selectionRevision, loadRequest: this.selectionRevision});
  }
  beginLoad() {
    // Metadata refresh is not fresh consent to replace a newer input or downgrade
    // a retired load into memory-only mode. Explicit legacy selection is separate.
    if (this.state.revision !== this.selectionRevision || this.state.storageStatus === 'unavailable' && !this.explicitMemoryLoad) return null;
    return this.begin(this.handler());
  }
  retireLoad() {
    if (!this.ownsLease()) return;
    // A fresh catalogue is not a fresh selection. Only explicit selection (or
    // pristine recovery disposition) may rearm this retired implicit request.
    this.selectionRevision = -1;
    this.operation++;
  }
  accept(documentId: string, document: EditorDocument | null, draft: string, validation: OwnedValidation | null, token: DraftOperation) {
    if (!this.check(token)) return false;
    const revision = this.nextRevision();
    if (revision === null) return false;
    const next = {...this.state, documentId, loadedDocumentId: documentId, document, draft, validation, revision};
    if (!next.recovery && !next.reconciliation && next.storageStatus === 'ready') {
      const result = compareDraft(this.storage, this.baseline, this.backup(next));
      if (result.status !== 'written') {this.publish({storageStatus: result.status}); return false;}
      this.baseline = result.raw!;
    }
    this.publish(next);
    return true;
  }
  edit(update: Partial<Pick<DraftSnapshot, 'draft' | 'prompt'>>, handler = this.handler()) {
    // Native input streams can contain multiple edits before a render. Fence the
    // mounted generation, not that stream's previous revision; replacement commands
    // instead require full revision eligibility before acquiring an operation.
    if (!this.live(handler) || Object.entries(update).every(([key, value]) => this.state[key as keyof DraftSnapshot] === value)) return;
    this.localIntent = true;
    const revision = this.nextRevision();
    this.publish({...update, revision: revision ?? this.state.revision,
      ...(this.state.loadedDocumentId && this.state.documentId !== this.state.loadedDocumentId ? {documentId: this.state.loadedDocumentId} : {})});
    this.persist();
  }
  private backup(s = this.state): RecoverableDraft | null {
    return s.draft === (s.document?.yaml_text ?? '') && !s.prompt ? null : {
      version: 2, draftId: this.draftId, revision: s.revision, documentId: s.documentId,
      viewId: s.document?.document_id ?? NEW_DOCUMENT, sourceHash: s.document?.source_hash ?? '', draft: s.draft, prompt: s.prompt,
      ...(s.document?.research_identity ? {researchIdentity: s.document.research_identity} : {}),
    };
  }
  private persist() {
    const s = this.state;
    if (!this.ownsLease() || s.recovery || s.reconciliation || s.storageStatus !== 'ready' || (!s.document && s.documentId !== NEW_DOCUMENT) || s.documentId !== s.loadedDocumentId) return;
    const result = compareDraft(this.storage, this.baseline, this.backup());
    if (result.status === 'written') this.baseline = result.raw!;
    else this.publish({storageStatus: result.status});
  }
  review(handler: DraftHandler) {
    if (!this.eligible(handler)) return;
    const revision = this.nextRevision();
    if (revision === null) return;
    this.operation++;
    if (!this.storage) {
      this.storage = this.storageProvider();
      if (this.storage) {
        const generation = advanceDraftRevision(Math.max(this.generation, leases.get(this.storage)?.generation ?? 0));
        if (generation === null) {this.active = false; this.publish({exhausted: true, storageStatus: 'unavailable'}); return;}
        this.generation = generation;
        leases.set(this.storage, {instance: this.instance, generation: this.generation});
        this.publish({activation: this.generation});
      }
    }
    const read = inspectDraft(this.storage);
    if (read.status === 'unavailable') {this.publish({storageStatus: 'unavailable'}); return;}
    this.baseline = read.raw;
    this.publish({recovery: read.value, reconciliation: true, revision,
      storageStatus: read.status === 'valid' || read.status === 'absent' ? 'ready' : read.status});
  }
  restore(handler: DraftHandler) {
    const {recovery, document, loadedDocumentId} = this.state;
    if (!recovery || !this.eligible(handler) || this.state.storageStatus !== 'ready' || !this.checkBaseline()) return false;
    if (this.state.documentId !== loadedDocumentId || recovery.documentId !== loadedDocumentId || recovery.sourceHash !== (document?.source_hash ?? '') ||
      (recovery.researchIdentity ? document?.source_origin?.id !== recovery.documentId || !sameResearchIdentity(recovery.researchIdentity, document.research_identity)
        : recovery.viewId !== (document?.document_id ?? NEW_DOCUMENT))) return false;
    const revision = this.nextRevision();
    if (revision === null) return false;
    const next = {...this.state, draft: recovery.draft, prompt: recovery.prompt, recovery: null, reconciliation: false,
      validation: recovery.draft === this.state.draft ? this.state.validation : null, revision};
    const result = compareDraft(this.storage, this.baseline, this.backup(next));
    if (result.status !== 'written') {this.publish({storageStatus: result.status}); return false;}
    this.baseline = result.raw!;
    this.operation++;
    this.publish(next);
    return true;
  }
  discard(handler: DraftHandler, disposition: 'keep-current-source' | 'detach-current-inputs' = 'keep-current-source') {
    if (!this.eligible(handler) || (this.state.storageStatus !== 'ready' && !(this.state.reconciliation && this.state.storageStatus === 'invalid-record')) || !this.checkBaseline(true)) return false;
    // An unloaded selection is not source provenance. Keeping authored inputs
    // requires explicit detachment consent, never a fabricated file/view binding.
    const unbound = this.unboundAuthoring;
    if (unbound && disposition !== 'detach-current-inputs') return false;
    const revision = this.nextRevision();
    if (revision === null) return false;
    const next = {...this.state, recovery: null, reconciliation: false, storageStatus: 'ready' as const, revision,
      ...(this.pristineAuthoring ? {loadRequest: revision} : {}),
      documentId: this.state.loadedDocumentId || this.state.documentId,
      ...(unbound ? {documentId: NEW_DOCUMENT, loadedDocumentId: NEW_DOCUMENT, document: null, validation: null} : {})};
    const result = compareDraft(this.storage, this.baseline, this.backup(next));
    if (result.status !== 'written') {this.publish({storageStatus: result.status}); return false;}
    this.baseline = result.raw!;
    this.operation++;
    if (this.pristineAuthoring) this.selectionRevision = next.revision;
    this.explicitMemoryLoad = false;
    this.publish(next);
    return true;
  }
}
