// Copyright (c) 2026, The Isaac Lab Arena Project Developers.
// SPDX-License-Identifier: Apache-2.0
// Builtin-only security checks. These never execute Chromium or IndexedDB.
import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, writeFile, mkdir, symlink, link, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
// No browser package is imported by these sandbox-only units.

const moduleURL = new URL('./ui-storage-fixture-loader.mjs', import.meta.url);
test('bounded fixture loader exists without importing browser packages', async () => {
  let module;
  try { module = await import(moduleURL); } catch (error) {
    assert.fail(`missing bounded fixture loader: ${error.code}`);
  }
  assert.equal(typeof module.loadFixture, 'function');
});

test('exact same-origin route only; no API, traversal, query or URL normalization', async () => {
  const { fixturePath, ORIGIN } = await import(moduleURL);
  assert.equal(fixturePath('GET', ORIGIN + '/'), 'fixture.html');
  assert.equal(fixturePath('GET', ORIGIN + '/fixture.js'), 'fixture.js');
  for (const url of [ORIGIN + '/api/editor', ORIGIN + '/fixture.js?x', ORIGIN + '/fixture.js#x',
    ORIGIN + '/x/../fixture.js', ORIGIN + '/%66ixture.js', ORIGIN + '//fixture.js',
    ORIGIN.replace('127.0.0.1', 'localhost') + '/', 'file:///fixture.js',
    'https://example.invalid/fixture.js', ORIGIN + ':80/']) {
    assert.equal(fixturePath('GET', url), null, url);
  }
  for (const method of ['POST', 'HEAD', 'OPTIONS', 'get']) assert.equal(fixturePath(method, ORIGIN + '/'), null);
});

test('captures only exact bounded physical files and hashes actual bytes', async () => {
  const { loadFixture } = await import(moduleURL);
  const root = await mkdtemp(join(tmpdir(), 'idb-loader-'));
  try {
    for (const name of ['fixture.html', 'fixture.js', 'fixture.css']) await writeFile(join(root, name), name);
    const fixture = await loadFixture(root);
    assert.equal(fixture.size, 3);
    assert.equal(fixture.get('fixture.js').sha256, createHash('sha256').update('fixture.js').digest('hex'));
    await writeFile(join(root, 'secret.env'), 'must not be offered');
    await assert.rejects(loadFixture(root), /exact fixture file allowlist/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('rejects symlink, hardlink, non-file, overbudget and symlink ancestors', async () => {
  const { loadFixture, MAX_ASSET_BYTES } = await import(moduleURL);
  const base = await mkdtemp(join(tmpdir(), 'idb-negative-'));
  try {
    const root = join(base, 'dist'); await mkdir(root);
    for (const name of ['fixture.html', 'fixture.css']) await writeFile(join(root, name), name);
    const external = join(base, 'external'); await writeFile(external, 'external bytes');
    const target = join(root, 'fixture.js');
    await symlink(external, target); await assert.rejects(loadFixture(root), /physical regular|ELOOP/); await rm(target);
    await link(external, target); await assert.rejects(loadFixture(root), /singly-linked/); await rm(target);
    await mkdir(target); await assert.rejects(loadFixture(root), /physical regular/); await rm(target, { recursive: true });
    await writeFile(target, Buffer.alloc(MAX_ASSET_BYTES + 1)); await assert.rejects(loadFixture(root), /asset byte budget/);
    await writeFile(target, 'ok'); await symlink(root, join(base, 'alias'));
    await assert.rejects(loadFixture(join(base, 'alias')), /physical directory/);
    await assert.rejects(loadFixture(root + '/../dist'), /lexical absolute/);
  } finally { await rm(base, { recursive: true, force: true }); }
});

test('route rejection aborts rather than fulfilling synthetic API responses', async () => {
  const { installFixtureRoutes, ORIGIN } = await import(moduleURL);
  const callbacks = {}, events = [];
  const context = { route: async (pattern, fn) => { callbacks.http = fn; },
    routeWebSocket: async (pattern, fn) => { callbacks.websocket = fn; } };
  await installFixtureRoutes(context, new Map([['fixture.html', { bytes: Buffer.from('test'), mime: 'text/html' }]]), events);
  let aborted = 0, fulfilled = 0, continued = 0;
  const route = (method, url) => ({ request: () => ({ method: () => method, url: () => url }),
    abort: async () => { aborted++; }, fulfill: async () => { fulfilled++; }, continue: () => { continued++; } });
  await callbacks.http(route('POST', ORIGIN + '/api/editor/save'));
  await callbacks.http(route('GET', ORIGIN + '/'));
  callbacks.websocket({ url: () => 'ws://127.0.0.1:31847/stream', close: () => { aborted++; } });
  assert.equal(aborted, 2); assert.equal(fulfilled, 1); assert.equal(continued, 0);
  assert.equal(events.length, 2);
});

test('HTTP denial settles even when rejection recording itself fails', async () => {
  const { installFixtureRoutes } = await import(moduleURL);
  let handler, aborted = false;
  await installFixtureRoutes({ route: async (_, fn) => { handler = fn; }, routeWebSocket: async () => {} },
    new Map(), Object.freeze([]));
  await assert.rejects(handler({ request: () => ({ method: () => 'POST', url: () => 'https://forbidden.invalid/' }),
    abort: async () => { aborted = true; } }), TypeError);
  assert.equal(aborted, true);
});

test('overflow still settles every denied HTTP and WebSocket request', async () => {
  const { installFixtureRoutes } = await import(moduleURL);
  const callbacks = {}, rejected = [], audit = { overflow: false };
  const context = { route: async (_, fn) => { callbacks.http = fn; },
    routeWebSocket: async (_, fn) => { callbacks.ws = fn; } };
  await installFixtureRoutes(context, new Map(), rejected, audit);
  let aborted = 0, closed = 0;
  for (let index = 0; index < 140; index++) {
    await callbacks.http({ request: () => ({ method: () => 'GET', url: () => 'https://forbidden.invalid/' }),
      abort: async () => { aborted++; }, continue: () => assert.fail('network continue') });
    await callbacks.ws({ url: () => 'wss://forbidden.invalid/', close: async () => { closed++; } });
  }
  assert.equal(aborted, 140); assert.equal(closed, 140);
  assert.equal(rejected.length, 128); assert.equal(audit.overflow, true);
});

test('driver finalizes failures from every phase and closes all acquired resources', async () => {
  const module = await import('./ui-storage-browser.mjs');
  assert.equal(typeof module.executeProbe, 'function', 'encompassing proof lifecycle missing');
  const names = ['preflight', 'imports', 'build', 'load', 'launch', 'context', 'routes', 'observe'];
  for (const fault of [...names, 'closeContext', 'closeBrowser', null]) {
    const calls = []; let saved;
    const phases = Object.fromEntries(names.map(name => [name, async () => {
      calls.push(name); if (name === fault) throw Error('injected ' + name);
      if (name === 'launch') return { version: () => 'synthetic', close: async () => {
        calls.push('closeBrowser'); if (fault === 'closeBrowser') throw Error(fault);
      } };
      if (name === 'context') return { close: async () => {
        calls.push('closeContext'); if (fault === 'closeContext') throw Error(fault);
      } };
      if (name === 'load') return new Map();
      return {};
    }]));
    phases.save = async proof => { saved = structuredClone(proof); };
    const proof = await module.executeProbe(phases);
    assert.deepEqual(saved, proof);
    assert.equal(proof.status, fault === null ? 'PARTIAL' : 'failed');
    assert.equal(module.probeExit(proof), fault === null ? 2 : 1);
    if (calls.includes('context')) assert(calls.includes('closeBrowser'));
    if (calls.includes('routes')) assert(calls.includes('closeContext'));
    assert.deepEqual(Object.values(proof.required_cases), Array(9).fill('NOT-RUN'));
  }
  assert.equal(module.probeExit({ status: 'passed', errors: [], cleanup_verified: false }), 1);
});

test('all observed native candidate flags still retain PARTIAL until parent release', async () => {
  const { executeProbe, probeExit, requiredCases } = await import('./ui-storage-browser.mjs');
  assert.deepEqual([...requiredCases], ['two-pages-concurrent-pins', 'competing-pins-at-capacity',
    'legacy-exact-unchanged', 'commit-notification-failure', 'request-success-then-abort',
    'blocked-open-late-success', 'versionchange', 'missing-record', 'notification-no-authority']);
  let closed = 0, saved;
  const inert = async () => ({});
  const proof = await executeProbe({ preflight: inert, imports: inert, build: inert,
    load: async () => new Map(), launch: async () => ({ version: () => 'synthetic-unit-only', close: async () => { closed++; } }),
    context: async () => ({ close: async () => { closed++; } }), routes: inert,
    observe: async (_context, _packages, proof) => {
      for (const name of requiredCases) proof.required_cases[name] = 'observed';
      return { case_schema: 'native-storage-candidate/v2', cases: {} }; // NOT real case evidence.
    }, save: async value => { saved = structuredClone(value); } });
  assert.deepEqual(saved, proof); assert.equal(closed, 2);
  assert.equal(proof.status, 'PARTIAL'); assert.equal(probeExit(proof), 2);
});

test('durable validator rejects matching empty, wrong identity and malformed records', async () => {
  const module = await import('./ui-storage-browser.mjs');
  assert.equal(typeof module.validateDurablePins, 'function', 'exact durable validator missing');
  const pins = ['1', '2'].map(digit => ({ id: `editor-revision:${digit.repeat(32)}`,
    kind: 'editor_revision', revision_id: digit.repeat(32), source_hash: digit.repeat(64), canonical_hash: 'a'.repeat(64) }));
  const record = { schemaVersion: 1, revision: 4, preferences: { version: 1, pins, recents: pins } };
  const observation = raw => ({ state: 'record', raw: JSON.stringify(raw), settledBy: 'transaction.oncomplete' });
  assert.deepEqual(module.validateDurablePins(observation(record), pins), record);
  for (const mutate of [r => {r.preferences.pins = [];}, r => {r.preferences.pins[1].source_hash = 'b'.repeat(64);},
    r => {r.preferences.pins.push(r.preferences.pins[0]);}, r => {r.revision = true;}, r => {r.unexpected = 1;},
    r => {r.preferences.pins[0].name = 'extra';}, r => {r.preferences.version = 2;}]) {
    const changed = structuredClone(record); mutate(changed);
    assert.throws(() => module.validateDurablePins(observation(changed), pins));
  }
  assert.throws(() => module.validateDurablePins({ ...observation(record), settledBy: 'request.onsuccess' }, pins));
});

test('two-page raw readbacks survive exact-pin failure and every page closes', async () => {
  const { observeTwoPages, readNativeRecord } = await import('./ui-storage-browser.mjs');
  const report = {}; let closed = 0;
  const raw = JSON.stringify({ schemaVersion: 1, revision: 0, preferences: { version: 1, pins: [], recents: [] } });
  const button = { click: async () => {}, getByRole: () => button };
  const context = { newPage: async () => ({ goto: async () => {}, getByRole: () => button, getByLabel: () => button,
    evaluate: async fn => fn === readNativeRecord ? { state: 'record', raw, settledBy: 'transaction.oncomplete' } : null,
    close: async () => { closed++; } }) };
  const expect = () => ({ toBeEnabled: async () => {}, toBeVisible: async () => {}, toHaveText: async () => {} });
  expect.poll = fn => ({ toBe: async value => assert.equal(await fn(), value) });
  await assert.rejects(observeTwoPages(context, expect, 'http://127.0.0.1:31847', report), /exact durable pins mismatch/);
  assert.equal(report.observations.length, 2, 'failed raw observations must be preserved');
  assert.equal(report.observations[0].raw, raw); assert.equal(report.observations[1].raw, raw);
  assert.equal(report.schedule, 'concurrent clicks; transaction overlap NOT witnessed');
  assert.equal(closed, 2);
});

test('directory identity uses device and inode; closes every descriptor after a close fault', async () => {
  const module = await import(moduleURL);
  assert.equal(typeof module.sameDirectory, 'function', 'physical directory identity seam missing');
  assert.equal(module.sameDirectory({ dev: 1n, ino: 4n }, { dev: 2n, ino: 4n }), false);
  assert.equal(module.sameDirectory({ dev: 1n, ino: 4n }, { dev: 1n, ino: 4n }), true);
  const closed = [];
  await assert.rejects(module.closeHandles([1, 2, 3].map(n => ({ close: async () => {
    closed.push(n); if (n === 2) throw Error('close fault');
  } }))), /close fault/);
  assert.deepEqual(closed, [3, 2, 1]);
});

test('observer closes on versionchange, absent store, transaction failure and open timeout', async () => {
  const { readNativeRecord } = await import('./ui-storage-browser.mjs');
  const original = { indexedDB: globalThis.indexedDB, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  try {
    for (const outcome of ['listing-timeout', 'open-timeout', 'versionchange', 'absent-store', 'transaction-failure', 'open-throw']) {
      const timers = new Map(); let next = 0, closed = 0, aborted = 0;
      globalThis.setTimeout = fn => { timers.set(++next, fn); return next; };
      globalThis.clearTimeout = id => timers.delete(id);
      const tx = { abort() { aborted++; }, objectStore: () => ({ get: () => ({}) }) };
      const db = { close() { closed++; }, objectStoreNames: { contains: () => outcome !== 'absent-store' },
        transaction() { if (outcome === 'transaction-failure') throw Error('transaction construction'); return tx; } };
      const request = { result: db };
      globalThis.indexedDB = { databases: () => outcome === 'listing-timeout' ? new Promise(() => {}) : Promise.resolve([{ name: 'arena-workbench-ui' }]),
        open() { if (outcome === 'open-throw') throw Error('open construction'); return request; } };
      const pending = readNativeRecord();
      const rejection = outcome === 'absent-store' ? null : assert.rejects(pending, /timeout|versionchange|construction/);
      await new Promise(resolve => setImmediate(resolve));
      if (outcome.endsWith('timeout')) [...timers.values()].at(-1)();
      else if (outcome !== 'open-throw') { request.onsuccess(); if (outcome === 'versionchange') db.onversionchange(); }
      if (rejection) await rejection;
      else assert.deepEqual(await pending, { state: 'absent-store' });
      if (outcome === 'open-timeout') request.onsuccess();
      assert.equal(closed, ['listing-timeout', 'open-throw'].includes(outcome) ? 0 : 1);
      assert.equal(aborted, outcome === 'versionchange' ? 1 : 0);
      assert.equal(timers.size, 0, outcome + ' timer must be cleared');
    }
  } finally { Object.assign(globalThis, original); }
});

test('legacy initialization seeds exact bytes before any fixture module', async () => {
  const { initializeNativeCase, expectedReferences } = await import('./ui-storage-browser.mjs');
  assert.equal(typeof initializeNativeCase, 'function');
  const prior = { document: globalThis.document, localStorage: globalThis.localStorage, location: globalThis.location,
    storageManual: globalThis.storageManual, storageInitWitness: globalThis.storageInitWitness };
  const values = new Map();
  try {
    globalThis.document = { readyState: 'complete', scripts: [] };
    globalThis.location = { href: 'about:blank' };
    assert.doesNotThrow(() => initializeNativeCase({ legacyRaw: null }));
    assert.equal(values.size, 0);
    globalThis.location = { href: 'http://127.0.0.1:31847/' };
    globalThis.document = { readyState: 'loading', scripts: [] };
    globalThis.localStorage = { setItem: (k, v) => values.set(k, v), getItem: k => values.get(k) ?? null };
    const raw = '  ' + JSON.stringify({ version: 1, pins: expectedReferences.slice(0, 2), recents: expectedReferences.slice(2, 3) }) + '\n';
    initializeNativeCase({ legacyRaw: raw });
    assert.equal(values.get('arena.environment-library.v1'), raw);
    assert.deepEqual(globalThis.storageInitWitness, { phase: 'playwright-init-script', readyState: 'loading', scripts: 0, fixturePresent: false, raw, verifiedRaw: raw });
    globalThis.document.scripts.push({});
    assert.throws(() => initializeNativeCase({ legacyRaw: raw }), /before fixture modules/);
  } finally { Object.assign(globalThis, prior); }
});

// Synthetic callback-order checks of the observer only, NOT native IDB evidence.
test('observer waits for oncomplete, rejects success-then-abort, and never writes', async () => {
  const { readNativeRecord } = await import('./ui-storage-browser.mjs');
  const original = globalThis.indexedDB;
  try {
    for (const outcome of ['complete', 'abort', 'missing']) {
      let closed = 0, settled = false, pendingGet;
      const tx = { abort() {}, objectStore(name) {
        assert.equal(name, 'libraryPreferences');
        return { get(key) { assert.equal(key, 'default'); return (pendingGet = {}); } };
      } };
      const db = { close() { closed++; }, objectStoreNames: { contains: () => true },
        transaction(name, mode) { assert.equal(mode, 'readonly'); return tx; } };
      const request = { result: db };
      globalThis.indexedDB = { databases: async () => [{ name: 'arena-workbench-ui' }],
        open(name) { assert.equal(name, 'arena-workbench-ui'); return request; } };
      const pending = readNativeRecord();
      pending.then(() => { settled = true; }, () => { settled = true; });
      await new Promise(resolve => setImmediate(resolve));
      request.onsuccess();
      pendingGet.result = outcome === 'missing' ? undefined : { revision: 3, preferences: { pins: [] } };
      pendingGet.onsuccess();
      await Promise.resolve(); assert.equal(settled, false, 'request success is not completion');
      if (outcome === 'abort') { tx.onabort(); await assert.rejects(pending, /aborted/); }
      else {
        tx.oncomplete(); const result = await pending;
        assert.equal(result.settledBy, 'transaction.oncomplete');
        assert.equal(result.state, outcome === 'missing' ? 'absent-record' : 'record');
      }
      assert.equal(closed, 1);
    }
  } finally { globalThis.indexedDB = original; }
});

test('observer refuses absent DB creation, blocks upgrades and closes late success', async () => {
  const { readNativeRecord } = await import('./ui-storage-browser.mjs');
  const original = globalThis.indexedDB;
  try {
    globalThis.indexedDB = { databases: async () => [], open() { assert.fail('must not create absent DB'); } };
    assert.deepEqual(await readNativeRecord(), { state: 'absent-database' });
    for (const outcome of ['blocked', 'upgrade']) {
      let closed = 0, aborted = 0;
      const request = { result: { close() { closed++; } }, transaction: { abort() { aborted++; } } };
      globalThis.indexedDB = { databases: async () => [{ name: 'arena-workbench-ui' }], open: () => request };
      const pending = readNativeRecord();
      const rejected = assert.rejects(pending, outcome === 'blocked' ? /blocked/ : /refused/);
      await new Promise(resolve => setImmediate(resolve));
      if (outcome === 'blocked') request.onblocked(); else request.onupgradeneeded();
      await rejected;
      request.onsuccess(); // A retired request cannot establish a connection.
      assert.equal(closed, outcome === 'blocked' ? 1 : 2);
      assert.equal(aborted, outcome === 'blocked' ? 0 : 1);
    }
  } finally { globalThis.indexedDB = original; }
});
