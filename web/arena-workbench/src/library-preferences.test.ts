import { expect, it } from 'vitest';
import { applyLibraryCommand, decodeLibraryEnvelope, createLibraryPreferencesController, type LibraryAdapter } from './library-preferences';

// Deterministic adapter seam, not native IndexedDB acceptance.
function fakeAdapter() {
  let stored: unknown;
  const pending: {mode: string; mutate: (raw: unknown) => unknown; resolve: (raw: unknown) => void; reject: (error: Error) => void}[] = [];
  const adapter: LibraryAdapter = {
    open: () => Promise.resolve(), close: () => {},
    transaction: (mode, mutate) => new Promise((resolve, reject) => pending.push({mode, mutate, resolve, reject})),
  };
  return {adapter, pending, get stored() { return stored; }, set stored(value) { stored = value; },
    admit() { const job = pending.shift()!; try { const value = job.mutate(stored); return {complete() { if (job.mode === 'readwrite') stored = value; job.resolve(value); }, abort() {job.reject(new Error('abort'));}}; } catch (error) {job.reject(error as Error); return {complete() {}, abort() {}};} },
  };
}
const flush = async () => { for (let n = 0; n < 6; n++) await Promise.resolve(); };
it('withholds initializing commands and publishes only after transaction completion', async () => {
  const fake = fakeAdapter();
  const controller = createLibraryPreferencesController({adapterFactory: () => fake.adapter, readLegacy: () => null});
  const retire = controller.activate();
  expect(await controller.pin(ref(), () => true)).toBe('initializing');
  await flush(); fake.admit().complete(); await flush();
  expect(controller.getSnapshot().mode).toBe('persistent');
  const pin = controller.pin(ref(), () => true);
  const admitted = fake.admit();
  expect(controller.getSnapshot().preferences.pins).toEqual([]);
  admitted.complete(); expect(await pin).toBe('committed');
  expect(controller.getSnapshot().preferences.pins).toEqual([ref()]);
  retire();
});

it('rechecks original source and activation at admission, not after an admitted commit', async () => {
  const fake = fakeAdapter();
  const controller = createLibraryPreferencesController({adapterFactory: () => fake.adapter, readLegacy: () => null});
  const retire = controller.activate(); await flush(); fake.admit().complete(); await flush();
  let allowed = true;
  const first = controller.pin(ref(), () => allowed);
  allowed = false; fake.admit().complete();
  expect(await first).toBe('retired');
  expect(controller.getSnapshot().preferences.pins).toEqual([]);
  allowed = true;
  const second = controller.pin(ref(), () => allowed);
  const admitted = fake.admit();
  retire(); admitted.complete();
  expect(await second).toBe('committed');
  expect(decodeLibraryEnvelope(fake.stored)?.preferences.pins).toEqual([ref()]);
  expect(controller.getSnapshot().preferences.pins).toEqual([]);
  expect(await controller.pin(ref('b'), () => true)).toBe('retired');
});
it('aborted transactions latch memory-only without replaying the failed command', async () => {
  const fake = fakeAdapter();
  const controller = createLibraryPreferencesController({adapterFactory: () => fake.adapter, readLegacy: () => null});
  const retire = controller.activate(); await flush(); fake.admit().complete(); await flush();
  const first = controller.pin(ref(), () => true); fake.admit().abort();
  expect(await first).toBe('unavailable');
  expect(controller.getSnapshot().mode).toBe('memory');
  expect(controller.getSnapshot().preferences.pins).toEqual([]);
  expect(await controller.pin(ref('b'), () => true)).toBe('memory');
  expect(fake.pending).toHaveLength(0);
  expect(controller.getSnapshot().preferences.pins).toEqual([ref('b')]); retire();
});
it('imports legacy only at absent-record initialization and rechecks observed bytes', async () => {
  const legacy = JSON.stringify({version: 1, pins: [ref()], recents: []});
  const fake = fakeAdapter();
  let bytes = legacy;
  const controller = createLibraryPreferencesController({adapterFactory: () => fake.adapter, readLegacy: () => bytes});
  let retire = controller.activate(); await flush(); fake.admit().complete(); await flush();
  expect(controller.getSnapshot().preferences.pins).toEqual([ref()]);
  retire(); bytes = JSON.stringify({version: 1, pins: [ref('b')], recents: []});
  retire = controller.activate(); await flush(); fake.admit().complete(); await flush();
  expect(controller.getSnapshot().preferences.pins).toEqual([ref()]); retire();
  const other = fakeAdapter();
  const changing = createLibraryPreferencesController({adapterFactory: () => other.adapter, readLegacy: () => bytes});
  const stop = changing.activate(); await flush(); bytes = legacy;
  other.admit().complete(); await flush();
  expect(changing.getSnapshot().mode).toBe('memory'); expect(other.stored).toBeUndefined(); stop();
});
it('makes fallback terminal for late initialization and old StrictMode cleanup', async () => {
  const first = fakeAdapter(); const second = fakeAdapter();
  let lost!: () => void; let resolve!: () => void;
  first.adapter.open = callback => {lost = callback; return new Promise(done => {resolve = done;});};
  let count = 0;
  const controller = createLibraryPreferencesController({adapterFactory: () => count++ ? second.adapter : first.adapter, readLegacy: () => null});
  const oldStop = controller.activate(); lost();
  expect(controller.getSnapshot().mode).toBe('memory');
  await controller.pin(ref(), () => true); resolve(); await flush();
  expect(first.pending).toHaveLength(0);
  const newStop = controller.activate(); oldStop(); await flush(); second.admit().complete(); await flush();
  expect(controller.getSnapshot().mode).toBe('persistent');
  expect(controller.getSnapshot().preferences.pins).toEqual([]); newStop();
});
it.each([undefined, {schemaVersion: 1, revision: 0, preferences: {version: 1, pins: [], recents: []}}, {schemaVersion: 1, revision: 1, preferences: {version: 1, pins: [], recents: []}}])('rejects missing, regressed or same-revision conflicting storage after initialization %#', async replacement => {
  const fake = fakeAdapter();
  fake.stored = applyLibraryCommand(empty(), {type: 'pin', reference: ref()}).envelope;
  const controller = createLibraryPreferencesController({adapterFactory: () => fake.adapter, readLegacy: () => null});
  const stop = controller.activate(); await flush(); fake.admit().complete(); await flush();
  fake.stored = replacement;
  const result = controller.pin(ref('b'), () => true); fake.admit().complete();
  expect(await result).toBe('unavailable');
  expect(fake.stored).toEqual(replacement);
  expect(controller.getSnapshot().preferences.pins).toEqual([ref()]); stop();
});
it('coalesces hint refreshes, accepts newer siblings, and never rebroadcasts reads', async () => {
  const fake = fakeAdapter(); let hint!: () => void; let posts = 0; let closed = 0;
  const controller = createLibraryPreferencesController({adapterFactory: () => fake.adapter, readLegacy: () => null,
    notifications: () => ({subscribe(callback) {hint = callback; return () => {closed++;};}, post() {posts++;}, close() {closed++;}})});
  const stop = controller.activate(); await flush(); fake.admit().complete(); await flush();
  fake.stored = applyLibraryCommand(empty(), {type: 'pin', reference: ref()}).envelope;
  hint(); hint(); hint(); await flush();
  expect(fake.pending).toHaveLength(1); expect(fake.pending[0].mode).toBe('readonly');
  const older = fake.admit();
  const pin = controller.pin(ref('b'), () => true); fake.admit().complete(); await pin;
  older.complete(); await flush();
  expect(controller.getSnapshot().preferences.pins).toEqual([ref(), ref('b')]);
  if (fake.pending.length) {fake.admit().complete(); await flush();}
  expect(posts).toBe(1); expect(fake.pending).toHaveLength(0);
  stop(); expect(closed).toBe(2); hint(); await flush(); expect(fake.pending).toHaveLength(0);
});
it('notification failure cannot relabel a completed transaction aborted or retry it', async () => {
  const fake = fakeAdapter(); let posts = 0;
  const controller = createLibraryPreferencesController({adapterFactory: () => fake.adapter, readLegacy: () => null,
    notifications: () => ({subscribe() {return () => {};}, close() {}, post() {posts++; throw new Error('PRIVATE');}})});
  const stop = controller.activate(); await flush(); fake.admit().complete(); await flush();
  const pin = controller.pin(ref(), () => true); fake.admit().complete();
  expect(await pin).toBe('committed');
  expect(controller.getSnapshot().mode).toBe('persistent');
  expect(controller.getSnapshot().preferences.pins).toEqual([ref()]);
  expect(controller.getSnapshot().notice).toMatch(/notification/i);
  expect(posts).toBe(1); expect(fake.pending).toHaveLength(0); stop();
});
it('validates the entire detached command before transaction dispatch', async () => {
  const fake = fakeAdapter();
  const controller = createLibraryPreferencesController({adapterFactory: () => fake.adapter, readLegacy: () => null});
  const stop = controller.activate(); await flush(); fake.admit().complete(); await flush();
  const result = controller.pin({...ref(), unexpected: 'not a preference'} as ReturnType<typeof ref>, () => true);
  expect(fake.pending).toHaveLength(0);
  expect(await result).toBe('invalid');
  expect(controller.getSnapshot().mode).toBe('persistent'); stop();
});
it('preserves malformed legacy bytes with a specific read-only recovery notice', async () => {
  const fake = fakeAdapter();
  const controller = createLibraryPreferencesController({adapterFactory: () => fake.adapter, readLegacy: () => 'not-json'});
  const stop = controller.activate(); await flush(); fake.admit().complete(); await flush();
  expect(fake.stored).toBeUndefined();
  expect(controller.getSnapshot().notice).toMatch(/malformed.*preserved/i);
  expect(await controller.pin(ref(), () => true)).toBe('memory');
  expect(fake.pending).toHaveLength(0); stop();
});
it('keeps the observable memory snapshot stable for no-op commands and cleans subscriptions', async () => {
  const controller = createLibraryPreferencesController({adapterFactory: () => {throw new Error('denied');}, readLegacy: () => null});
  let publications = 0; const unsubscribe = controller.subscribe(() => {publications++;});
  const stop = controller.activate();
  await controller.pin(ref(), () => true);
  const before = controller.getSnapshot(); const count = publications;
  expect(await controller.pin(ref(), () => true)).toBe('noop');
  expect(controller.getSnapshot()).toBe(before); expect(publications).toBe(count);
  unsubscribe(); await controller.unpin(ref(), () => true); expect(publications).toBe(count); stop();
});
it('denies a throwing admission guard without exposing errors or opening a transaction', async () => {
  const fake = fakeAdapter();
  const controller = createLibraryPreferencesController({adapterFactory: () => fake.adapter, readLegacy: () => null});
  const stop = controller.activate(); await flush(); fake.admit().complete(); await flush();
  await expect(controller.pin(ref(), () => {throw new Error('PRIVATE');})).resolves.toBe('retired');
  expect(fake.pending).toHaveLength(0); expect(controller.getSnapshot().mode).toBe('persistent'); stop();
});
it('serializes sibling pin/unpin/recent operations against the latest adapter record', async () => {
  const fake = fakeAdapter();
  const options = {adapterFactory: () => fake.adapter, readLegacy: () => null};
  const a = createLibraryPreferencesController(options); const b = createLibraryPreferencesController(options);
  const stopA = a.activate(); const stopB = b.activate(); await flush();
  fake.admit().complete(); fake.admit().complete(); await flush();
  const pinA = a.pin(ref(), () => true); const pinB = b.pin(ref('b'), () => true);
  fake.admit().complete(); await pinA; fake.admit().complete(); await pinB;
  const unpin = a.unpin(ref(), () => true); const recent = b.recordOpened(ref('c'), () => true);
  fake.admit().complete(); await unpin; fake.admit().complete(); await recent;
  expect(decodeLibraryEnvelope(fake.stored)?.preferences).toEqual({version: 1, pins: [ref('b')], recents: [ref('c')]});
  stopA(); stopB();
});
it('rejects only the excess sibling pin at capacity, keeping both connections persistent', async () => {
  const fake = fakeAdapter();
  let baseline = empty() as ReturnType<typeof applyLibraryCommand>['envelope'];
  for (let n = 0; n < 7; n++) baseline = applyLibraryCommand(baseline, {type: 'pin', reference: ref(n.toString(16))}).envelope;
  fake.stored = baseline;
  const options = {adapterFactory: () => fake.adapter, readLegacy: () => null};
  const a = createLibraryPreferencesController(options); const b = createLibraryPreferencesController(options);
  const stopA = a.activate(); const stopB = b.activate(); await flush(); fake.admit().complete(); fake.admit().complete(); await flush();
  const pinA = a.pin(ref('7'), () => true); const pinB = b.pin(ref('8'), () => true);
  fake.admit().complete(); expect(await pinA).toBe('committed');
  fake.admit().complete(); expect(await pinB).toBe('limit');
  expect(decodeLibraryEnvelope(fake.stored)?.preferences.pins).toHaveLength(8);
  expect(a.getSnapshot().mode).toBe('persistent'); expect(b.getSnapshot().mode).toBe('persistent'); stopA(); stopB();
});
it.each([null, [], {}, {schemaVersion: 2, revision: 0, preferences: {version: 1, pins: [], recents: []}}, {schemaVersion: 1, revision: -1, preferences: {version: 1, pins: [], recents: []}}, {schemaVersion: 1, revision: Number.MAX_SAFE_INTEGER + 1, preferences: {version: 1, pins: [], recents: []}}, {schemaVersion: 1, revision: 0, preferences: {version: 1, pins: [], recents: [], extra: 'private'}}, {schemaVersion: 1, revision: 0, preferences: {version: 1, pins: [], recents: []}, extra: 'private'}])('strictly rejects malformed envelope %#', value => {
  expect(decodeLibraryEnvelope(value)).toBeUndefined();
});
it('never revives a rendered owner guard after activation replacement or terminal fallback', async () => {
  const first = fakeAdapter(); const second = fakeAdapter(); let lost!: () => void;
  first.adapter.open = callback => {lost = callback; return Promise.resolve();};
  let calls = 0;
  const controller = createLibraryPreferencesController({adapterFactory: () => calls++ ? second.adapter : first.adapter, readLegacy: () => null});
  const stop = controller.activate(); await flush(); first.admit().complete(); await flush();
  const oldGuard = controller.captureOwner(); expect(oldGuard()).toBe(true);
  lost(); expect(oldGuard()).toBe(false);
  const memoryGuard = controller.captureOwner(); expect(memoryGuard()).toBe(true);
  const replacementStop = controller.activate(); stop(); await flush(); second.admit().complete(); await flush();
  expect(oldGuard()).toBe(false); expect(memoryGuard()).toBe(false);
  expect(controller.captureOwner()()).toBe(true); replacementStop();
});
it('does not install notification resources when publication synchronously retires the owner', async () => {
  const fake = fakeAdapter(); let notificationFactories = 0;
  const controller = createLibraryPreferencesController({adapterFactory: () => fake.adapter, readLegacy: () => null,
    notifications() {notificationFactories++; return {subscribe() {return () => {};}, post() {}, close() {}};}});
  const stop = controller.activate();
  const unsubscribe = controller.subscribe(() => {if (controller.getSnapshot().mode === 'persistent') stop();});
  await flush(); fake.admit().complete(); await flush();
  expect(notificationFactories).toBe(0); unsubscribe();
});
const ref = (digit = 'a') => ({id: `editor-revision:${digit.repeat(32)}`, kind: 'editor_revision' as const, revision_id: digit.repeat(32), source_hash: digit.repeat(64), canonical_hash: 'f'.repeat(64)});
const empty = () => ({schemaVersion: 1 as const, revision: 0, preferences: {version: 1 as const, pins: [], recents: []}});
it('applies an operation to the latest typed envelope without replacing sibling preferences', () => {
  const a = applyLibraryCommand(empty(), {type: 'pin', reference: ref()});
  expect(a.status).toBe('changed');
  const b = applyLibraryCommand(a.envelope, {type: 'recordOpened', reference: ref('b')});
  expect(b.envelope).toEqual({schemaVersion: 1, revision: 2, preferences: {version: 1, pins: [ref()], recents: [ref('b')]}});
  expect(decodeLibraryEnvelope(b.envelope)).toEqual(b.envelope);
});
it('bounds distinct pins without eviction or degradation and makes duplicate operations no-ops', () => {
  let state = empty() as ReturnType<typeof applyLibraryCommand>['envelope'];
  for (let n = 0; n < 8; n++) state = applyLibraryCommand(state, {type: 'pin', reference: ref(n.toString(16))}).envelope;
  expect(applyLibraryCommand(state, {type: 'pin', reference: ref('8')})).toEqual({status: 'limit', envelope: state});
  expect(applyLibraryCommand(state, {type: 'pin', reference: ref('0')})).toEqual({status: 'noop', envelope: state});
  expect(applyLibraryCommand(state, {type: 'unpin', reference: ref('9')})).toEqual({status: 'noop', envelope: state});
  for (let n = 0; n < 14; n++) state = applyLibraryCommand(state, {type: 'recordOpened', reference: ref(n.toString(16))}).envelope;
  expect(state.preferences.recents).toHaveLength(12);
  expect(state.preferences.pins).toHaveLength(8);
  expect(() => applyLibraryCommand({...state, revision: Number.MAX_SAFE_INTEGER}, {type: 'unpin', reference: ref('0')})).toThrow();
  expect(() => applyLibraryCommand(state, {type: 'pin', reference: {id: 'file', kind: 'discovered_file'}})).toThrow();
});
import { libraryReference, normalizeLibrarySource } from './environment-library-contract';
import { researchOpen } from './research-source';

it('detaches nested research identity at the reference boundary', () => {
  const source = researchOpen({store_id: 'local', reservation_id: 'a'.repeat(32), revision_id: 'b'.repeat(32), family: 'Example', version: 2, source: {job_id: 'c'.repeat(32), attempt_id: 'd'.repeat(32), generation: 1, receipt_sha256: 'e'.repeat(64), request_sha256: 'f'.repeat(64)}}, {digest: '1'.repeat(64), files: {'environment.yaml': {size: 20, sha256: '2'.repeat(64)}}});
  const ref = libraryReference(source);
  const normalized = normalizeLibrarySource(source)!;
  if (!('generation' in source.research_identity.source)) throw new Error('Candidate fixture');
  source.research_identity.source.generation = 9;
  expect(ref.research_identity!.source).toMatchObject({generation: 1});
  expect(normalized.research_identity!.source).toMatchObject({generation: 1});
});
