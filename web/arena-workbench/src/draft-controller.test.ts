import { beforeEach, expect, it, vi } from 'vitest';
import { advanceDraftRevision, DraftController, NEW_DOCUMENT } from './draft-controller';

beforeEach(() => sessionStorage.clear());
const key = 'arena.editor.draft.v1';
it('bounds monotonic revisions without rounding or resetting exhausted authority', () => {
  expect(advanceDraftRevision(0)).toBe(1);
  expect(advanceDraftRevision(Number.MAX_SAFE_INTEGER - 1)).toBe(Number.MAX_SAFE_INTEGER);
  for (const value of [-1, 0.5, NaN, Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER + 1]) expect(advanceDraftRevision(value)).toBeNull();
});
const backup = {version: 1 as const, documentId: NEW_DOCUMENT, viewId: NEW_DOCUMENT, sourceHash: '', draft: 'recovered', prompt: 'review'};
const openLocal = (controller: DraftController, text = 'draft A') => {
  const operation = controller.begin(controller.handler());
  expect(operation).not.toBeNull();
  expect(controller.accept(NEW_DOCUMENT, null, text, null, operation!)).toBe(true);
};

it.each(['draft', 'prompt'] as const)('never rearms implicit loading after explicit unbound %s ABA disposition', field => {
  const raw = JSON.stringify({...backup, documentId: 'unloaded-file', viewId: 'frozen-file', sourceHash: 'file-hash'});
  sessionStorage.setItem(key, raw);
  const controller = new DraftController(); controller.activate();
  const input = controller.handler();
  controller.edit({[field]: 'local intent'}, input);
  controller.edit({[field]: ''}, input);
  expect(controller.discard(controller.handler())).toBe(false);
  expect(sessionStorage.getItem(key)).toBe(raw);
  expect(controller.discard(controller.handler(), 'detach-current-inputs')).toBe(true);
  expect(controller.getSnapshot()).toMatchObject({documentId: NEW_DOCUMENT, loadedDocumentId: NEW_DOCUMENT, document: null, draft: '', prompt: '', recovery: null});
  expect(controller.beginLoad()).toBeNull();
  expect(sessionStorage.getItem(key)).toBeNull();
});

it.each(['draft', 'prompt'] as const)('requires explicit selection authority after %s ABA, including warm activation', field => {
  const controller = new DraftController(); const deactivate = controller.activate();
  controller.edit({[field]: 'local intent'}); controller.edit({[field]: ''});
  deactivate(); controller.activate();
  controller.select('metadata-default');
  expect(controller.getSnapshot().documentId).toBe('');
  expect(controller.beginLoad()).toBeNull();
  controller.select('explicit-choice', controller.begin(controller.handler())!);
  expect(controller.getSnapshot().documentId).toBe('explicit-choice');
  expect(controller.beginLoad()).not.toBeNull();
});

it('Discard keeps dirty loaded-source inputs rather than attributing them to a pending selection', () => {
  sessionStorage.setItem(key, JSON.stringify(backup));
  const controller = new DraftController(); controller.activate(); openLocal(controller, 'keep current');
  controller.select('pending-source', controller.begin(controller.handler())!);
  expect(controller.discard(controller.handler())).toBe(true);
  expect(controller.getSnapshot().documentId).toBe(NEW_DOCUMENT);
  expect(JSON.parse(sessionStorage.getItem(key)!)).toMatchObject({documentId: NEW_DOCUMENT, draft: 'keep current'});
});

it('does not Restore into a pending or failed legacy selection using the previous loaded identity', () => {
  const raw = JSON.stringify(backup); sessionStorage.setItem(key, raw);
  const controller = new DraftController(); controller.activate();
  controller.select('unresolved-source', controller.begin(controller.handler())!);
  expect(controller.restore(controller.handler())).toBe(false);
  expect(controller.getSnapshot().recovery).toEqual(backup);
  expect(controller.draft).toBe('');
  expect(sessionStorage.getItem(key)).toBe(raw);
});

it('retains raw input in memory and permanently withholds replacement at revision exhaustion', () => {
  const controller = new DraftController(); controller.activate(); openLocal(controller);
  const bytes = sessionStorage.getItem(key);
  // Fault-inject the unreachable-in-test elapsed command count, not backup authority.
  controller.getSnapshot().revision = Number.MAX_SAFE_INTEGER;
  const old = controller.begin(controller.handler())!;
  controller.edit({draft: 'last input'});
  expect(controller.getSnapshot().revision).toBe(Number.MAX_SAFE_INTEGER);
  expect(controller.draft).toBe('last input');
  expect(controller.begin(controller.handler())).toBeNull();
  expect(controller.check(old)).toBe(false);
  expect(sessionStorage.getItem(key)).toBe(bytes);
});

it('backs up a raw edit during pending legacy selection against its still-loaded source', () => {
  const controller = new DraftController(); controller.activate(); openLocal(controller);
  controller.select('pending-source', controller.begin(controller.handler())!);
  const pending = controller.beginLoad()!;
  controller.edit({draft: 'newer input'});
  expect(controller.getSnapshot().documentId).toBe(NEW_DOCUMENT);
  expect(JSON.parse(sessionStorage.getItem(key)!)).toMatchObject({documentId: NEW_DOCUMENT, draft: 'newer input'});
  expect(controller.check(pending)).toBe(false);
  expect(controller.beginLoad()).toBeNull();
});

it('does not lend fallback-controller authority through equal activation numbers', () => {
  const first = new DraftController(() => null); const deactivate = first.activate();
  openLocal(first, 'first memory');
  const retained = first.handler();
  deactivate();
  const second = new DraftController(() => null); second.activate();
  openLocal(second, 'second memory');
  expect(second.handler().generation).toBe(retained.generation);
  second.edit({draft: 'borrowed memory'}, retained);
  second.review(retained);
  expect(second.begin(retained)).toBeNull();
  expect(second.discard(retained, 'detach-current-inputs')).toBe(false);
  expect(second.getSnapshot()).toMatchObject({draft: 'second memory', storageStatus: 'unavailable'});
  expect(second.getSnapshot().reconciliation).toBeUndefined();
  expect(first.begin(retained)).toBeNull();
  expect(sessionStorage.getItem(key)).toBeNull();
});

it('reacquires an initially inaccessible Storage object only through explicit Review', () => {
  let available = false;
  const controller = new DraftController(() => available ? sessionStorage : null);
  controller.activate(); openLocal(controller);
  available = true;
  controller.edit({prompt: 'memory'});
  expect(sessionStorage.getItem(key)).toBeNull();
  controller.review(controller.handler());
  expect(controller.getSnapshot().storageStatus).toBe('ready');
  expect(controller.discard(controller.handler())).toBe(true);
  expect(JSON.parse(sessionStorage.getItem(key)!)).toMatchObject({draft: 'draft A', prompt: 'memory'});
});

it('does not borrow a matching numeric generation from an unrelated controller', () => {
  const storage = () => ({getItem: () => null, setItem: () => {}, removeItem: () => {}});
  const first = new DraftController(storage); first.activate();
  const second = new DraftController(storage); second.activate();
  expect(first.handler().generation).toBe(second.handler().generation);
  expect(second.begin(first.handler())).toBeNull();
});

it('Review of absent storage does not automatically promote or replay memory edits', () => {
  const controller = new DraftController(); controller.activate(); openLocal(controller);
  sessionStorage.removeItem(key);
  expect(controller.begin(controller.handler())).toBeNull();
  controller.review(controller.handler());
  controller.edit({draft: 'unreplayed'});
  expect(sessionStorage.getItem(key)).toBeNull();
  expect(controller.discard(controller.handler())).toBe(true);
  expect(JSON.parse(sessionStorage.getItem(key)!).draft).toBe('unreplayed');
});

it('requires explicit Review then Discard before replacing a sibling with retained dirty inputs', () => {
  const controller = new DraftController(); controller.activate(); openLocal(controller);
  const old = controller.handler();
  const sibling = JSON.stringify(backup);
  sessionStorage.setItem(key, sibling);
  expect(controller.begin(old)).toBeNull();
  controller.review(controller.handler());
  expect(controller.getSnapshot().recovery).toEqual(backup);
  expect(controller.draft).toBe('draft A');
  controller.edit({prompt: 'keep my current prompt'});
  expect(sessionStorage.getItem(key)).toBe(sibling);
  expect(controller.discard(old)).toBe(false);
  expect(controller.discard(controller.handler())).toBe(true);
  expect(JSON.parse(sessionStorage.getItem(key)!)).toMatchObject({version: 2, draft: 'draft A', prompt: 'keep my current prompt'});
  expect(controller.getSnapshot().recovery).toBeNull();
});

it('keeps failed Discard obligation and original bytes across reactivation', () => {
  const raw = JSON.stringify(backup);
  sessionStorage.setItem(key, raw);
  const controller = new DraftController();
  const dispose = controller.activate();
  const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {throw new DOMException('denied', 'SecurityError');});
  expect(controller.discard(controller.handler())).toBe(false);
  expect(controller.getSnapshot().recovery).toEqual(backup);
  expect(controller.getSnapshot().storageStatus).toBe('unavailable');
  remove.mockRestore(); dispose(); controller.activate();
  expect(controller.getSnapshot().recovery).toEqual(backup);
  controller.edit({prompt: 'in memory'});
  expect(sessionStorage.getItem(key)).toBe(raw);
});

it('permanently retires replaced same-storage owners and identity-checks StrictMode cleanup', () => {
  const first = new DraftController();
  const disposeFirst = first.activate();
  openLocal(first);
  const old = first.handler();
  const second = new DraftController();
  const disposeSecond = second.activate();
  const current = second.handler();
  expect(first.begin(old)).toBeNull();
  const bytes = sessionStorage.getItem(key);
  first.edit({draft: 'retired content'});
  expect(first.draft).toBe('draft A');
  expect(sessionStorage.getItem(key)).toBe(bytes);
  disposeFirst();
  expect(second.begin(current)).not.toBeNull();
  disposeSecond();
  second.activate();
  expect(second.begin(current)).toBeNull();
  expect(second.begin(second.handler())).not.toBeNull();
  disposeSecond();
  expect(second.begin(second.handler())).not.toBeNull();
});
