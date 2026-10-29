// Copyright (c) 2026, The Isaac Lab Arena Project Developers.
// SPDX-License-Identifier: Apache-2.0
// Import-safe preparation. No auto-entry: parent must review host lifecycle first.
import assert from 'node:assert/strict';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import net from 'node:net';
import { createRequire } from 'node:module';

// Serializable Playwright evaluate callback. Never supplies an IDB adapter.
// An absent database is reported, not created by observation. Upgrade races abort.
export async function readNativeRecord() {
  const database = 'arena-workbench-ui', store = 'libraryPreferences';
  let listTimer;
  let known;
  try {
    known = await Promise.race([indexedDB.databases(), new Promise((_, reject) => {
      listTimer = setTimeout(() => reject(Error('native database listing timeout')), 1500);
    })]);
  } finally { clearTimeout(listTimer); }
  if (!known.some(item => item.name === database)) return { state: 'absent-database' };
  return new Promise((resolve, reject) => {
    let db, transaction, settled = false, value;
    const finish = (error, result) => {
      if (settled) return;
      settled = true; clearTimeout(timer);
      if (error && transaction) { try { transaction.abort(); } catch { /* already ended */ } }
      db?.close(); error ? reject(error) : resolve(result);
    };
    const timer = setTimeout(() => finish(Error('native observation timeout')), 3000);
    let request;
    try { request = indexedDB.open(database); }
    catch (error) { finish(error); return; }
    request.onupgradeneeded = () => {
      request.transaction.abort(); request.result.close();
      finish(Error('observation refused database creation/upgrade'));
    };
    request.onblocked = () => finish(Error('native observation blocked'));
    request.onerror = () => finish(request.error ?? Error('native observation open error'));
    request.onsuccess = () => {
      db = request.result;
      if (settled) { db.close(); return; }
      db.onversionchange = () => finish(Error('native observation versionchange'));
      try {
        if (!db.objectStoreNames.contains(store)) { finish(null, { state: 'absent-store' }); return; }
        globalThis.storageFixture?.observeConnection(db);
        transaction = db.transaction(store, 'readonly');
        const get = transaction.objectStore(store).get('default');
        get.onsuccess = () => { value = get.result; }; // Never an acknowledgement.
        get.onerror = () => finish(get.error ?? Error('native observation request error'));
        transaction.onabort = () => finish(transaction.error ?? Error('native observation aborted'));
        transaction.onerror = () => finish(transaction.error ?? Error('native observation transaction error'));
        transaction.oncomplete = () => {
          try {
            const raw = value === undefined ? null : JSON.stringify(value);
            if (raw !== null && raw.length > 32768) throw Error('native record observation budget');
            finish(null, { state: raw === null ? 'absent-record' : 'record', raw, settledBy: 'transaction.oncomplete',
              ...(globalThis.storageFixture ? { binding: globalThis.storageFixture.observationBinding(transaction) } : {}) });
          } catch (error) { finish(error); }
        };
      } catch (error) { finish(error); }
    };
  });
}

export const expectedReferences = Object.freeze(Array.from({ length: 9 }, (_, index) => {
  const digit = (index + 1).toString(16);
  return Object.freeze({ id: `editor-revision:${digit.repeat(32)}`, kind: 'editor_revision',
    revision_id: digit.repeat(32), source_hash: digit.repeat(64), canonical_hash: 'a'.repeat(64) });
}));
// Frozen subset of the production LibraryEnvelope/LibraryPreferences contract.
// This fixture accepts only its exact synthetic editor revisions, not arbitrary hints.
export function validateDurablePins(observation, expected) {
  assert.equal(observation.state, 'record');
  assert.equal(observation.settledBy, 'transaction.oncomplete');
  assert.equal(typeof observation.raw, 'string'); assert(observation.raw.length <= 32768);
  const value = JSON.parse(observation.raw);
  assert.deepEqual(Object.keys(value).sort(), ['preferences', 'revision', 'schemaVersion']);
  assert.equal(value.schemaVersion, 1); assert(Number.isSafeInteger(value.revision) && value.revision >= 0);
  const preferences = value.preferences;
  assert.deepEqual(Object.keys(preferences).sort(), ['pins', 'recents', 'version']);
  assert.equal(preferences.version, 1); assert(JSON.stringify(preferences).length <= 16384);
  const canonical = row => {
    assert.deepEqual(Object.keys(row).sort(), ['canonical_hash', 'id', 'kind', 'revision_id', 'source_hash']);
    assert.equal(row.kind, 'editor_revision'); assert.match(row.revision_id, /^[a-f0-9]{32}$/);
    assert.equal(row.id, 'editor-revision:' + row.revision_id);
    assert.match(row.source_hash, /^[a-f0-9]{64}$/); assert.match(row.canonical_hash, /^[a-f0-9]{64}$/);
    return JSON.stringify([row.id, row.kind, row.revision_id, row.source_hash, row.canonical_hash]);
  };
  for (const [name, limit] of [['pins', 8], ['recents', 12]]) {
    assert(Array.isArray(preferences[name]) && preferences[name].length <= limit);
    const keys = preferences[name].map(canonical);
    assert.equal(new Set(keys).size, keys.length, 'duplicate exact reference');
  }
  assert.deepEqual(preferences.pins.map(canonical).sort(), expected.map(canonical).sort(), 'exact durable pins mismatch');
  return value;
}

export async function observeTwoPages(context, expect, origin, report = {}) {
  const pages = [];
  Object.assign(report, { scope: 'synthetic parent-prop fixture; actual native engine; no API/source verification',
    schedule: 'concurrent clicks; transaction overlap NOT witnessed', observations: [] });
  try {
    pages.push(await context.newPage()); pages.push(await context.newPage());
    await Promise.all(pages.map(page => page.goto(origin + '/')));
    const legacyBefore = report.legacyBefore = await pages[0].evaluate(() => localStorage.getItem('arena.environment-library.v1'));
    await Promise.all(pages.map(page => expect.poll(async () => (await page.evaluate(readNativeRecord)).state).toBe('record')));
    await Promise.all(pages.map(async (page, index) => {
      await page.getByRole('button', { name: `Confirm fixture reference ${index + 1}`, exact: true }).click();
      await page.getByRole('button', { name: `Inspect Synthetic reference ${index + 1}`, exact: true }).click();
      await expect(page.getByRole('button', { name: 'Pin exact revision', exact: true })).toBeEnabled();
    }));
    await Promise.all(pages.map(page => page.getByRole('button', { name: 'Pin exact revision', exact: true }).click()));
    for (const page of pages) {
      const pins = page.getByRole('region', { name: 'Pinned revisions', exact: true });
      for (const digit of ['1', '2']) await expect(pins.getByRole('button', {
        name: `Remove pin editor-revision:${digit.repeat(32)}`, exact: true })).toBeVisible();
      await expect(page.getByLabel('Fixture open requests', { exact: true })).toHaveText('0');
    }
    const observations = await Promise.all(pages.map(async (page, index) => {
      const value = await page.evaluate(readNativeRecord);
      report.observations[index] = value; // Retain actual oncomplete bytes before assertions.
      return value;
    }));
    observations.forEach(value => validateDurablePins(value, expectedReferences.slice(0, 2)));
    assert.equal(observations[0].raw, observations[1].raw, 'independent same-origin transaction readbacks differ');
    const legacyAfter = report.legacyAfter = await pages[1].evaluate(() => localStorage.getItem('arena.environment-library.v1'));
    assert.equal(legacyAfter, legacyBefore, 'probe must not dual-write legacy preferences');
    // This is an unseeded post-navigation sample, NOT legacy migration evidence.
    return report;
  } finally {
    const results = await Promise.allSettled(pages.map(page => page.close()));
    const failures = results.filter(result => result.status === 'rejected');
    if (failures.length) throw new AggregateError(failures.map(result => result.reason), 'page cleanup failed');
  }
}

// Serialized directly into Playwright's pre-script realm; no imported helpers,
// no fixture references and no module activation needed to construct the seed.
export function initializeNativeCase({ legacyRaw }) {
  // Playwright also initializes the empty initial document, which has no fixture.
  if (globalThis.location.href === 'about:blank') return;
  if (globalThis.storageFixture || document.scripts.length || document.readyState !== 'loading') {
    throw Error('native init must run before fixture modules');
  }
  globalThis.storageManual = true;
  if (legacyRaw !== null) {
    if (typeof legacyRaw !== 'string' || legacyRaw.length > 16384) throw Error('legacy init byte budget');
    localStorage.setItem('arena.environment-library.v1', legacyRaw);
    globalThis.storageInitWitness = Object.freeze({ phase: 'playwright-init-script', readyState: document.readyState,
      scripts: document.scripts.length, fixturePresent: !!globalThis.storageFixture, raw: legacyRaw,
      verifiedRaw: localStorage.getItem('arena.environment-library.v1') });
  }
}

// Versioned candidate evidence. The reviewed host still requires PARTIAL/exit 2.
export async function observeNativeCases(browser, configure, expect, origin, proof) {
  const cases = proof.result.cases = {};
  proof.result.case_schema = 'native-storage-candidate/v2';
  const audit = page => page.evaluate(() => window.storageFixture.audit());
  const has = (value, type) => value.events.some(event => event.type === type);
  const mode = (page, expected) => expect.poll(async () => (await audit(page)).snapshot?.mode).toBe(expected);
  const mount = async page => { await page.evaluate(() => window.storageFixture.mount()); await mode(page, 'persistent'); };
  for (const id of requiredCases) {
    const report = cases[id] = { id, schema: 2, status: 'started', isolation: 'fresh-browser-context',
      scope: 'native production controller; synthetic editor references/admission; no API/source authority',
      browser_version: browser.version(), bounds: { barrier_ms: 4000, barrier_requests: 100000, events_per_page: 512 },
      cleanup_verified: false, before: [], after: [], audits: [] };
    let context; const pages = [];
    try {
      context = await browser.newContext({ serviceWorkers: 'block' });
      await configure(context);
      const legacyRaw = id === 'legacy-exact-unchanged' ? '  ' + JSON.stringify({ version: 1, pins: expectedReferences.slice(0, 2), recents: expectedReferences.slice(2, 3) }) + '\n' : null;
      await context.addInitScript(initializeNativeCase, { legacyRaw });
      const page = await context.newPage(); pages.push(page); await page.goto(origin + '/');
      await page.waitForFunction(() => !!window.storageFixture);
      report.initial = await page.evaluate(readNativeRecord);
      assert.equal(report.initial.state, 'absent-database');
      if (id === 'legacy-exact-unchanged') {
        report.initWitness = await page.evaluate(() => window.storageInitWitness);
        report.moduleEntry = await page.evaluate(() => window.storageModuleEntry);
        report.legacyBefore = await page.evaluate(() => localStorage.getItem('arena.environment-library.v1'));
        assert.equal(report.initWitness.raw, legacyRaw); assert.equal(report.initWitness.verifiedRaw, legacyRaw);
        assert.equal(report.moduleEntry.raw, legacyRaw); assert.equal(report.moduleEntry.initSeen, true);
        report.preMount = await audit(page);
        await mount(page);
        report.after.push(await page.evaluate(readNativeRecord));
        const record = validateDurablePins(report.after[0], expectedReferences.slice(0, 2));
        assert.equal(record.revision, 0);
        assert.deepEqual(record.preferences, JSON.parse(report.legacyBefore));
        report.legacyAfter = await page.evaluate(() => localStorage.getItem('arena.environment-library.v1'));
        assert.equal(report.legacyBefore, report.legacyAfter);
      } else if (id === 'blocked-open-late-success') {
        report.fault = 'bounded factory version fault: production requested v1, native request v2 behind held v1; late upgrade abort, NOT late success';
        await page.evaluate(() => window.storageFixture.seed([]));
        report.before.push(await page.evaluate(readNativeRecord));
        await page.evaluate(() => window.storageFixture.holdConnection());
        await page.evaluate(() => window.storageFixture.mount(true));
        await mode(page, 'memory');
        report.blocked = await audit(page);
        assert(has(report.blocked, 'open-blocked'));
        report.outcomes = [await page.evaluate(() => window.storageFixture.pin(0))];
        await page.evaluate(() => window.storageFixture.release());
        await expect.poll(async () => has(await audit(page), 'late-upgrade-abort')).toBe(true);
        await expect.poll(async () => has(await audit(page), 'open-error')).toBe(true);
        await page.evaluate(() => window.storageFixture.refresh());
        report.after.push(await page.evaluate(readNativeRecord));
        assert.equal(report.after[0].raw, report.before[0].raw);
        assert.equal(report.outcomes[0], 'memory'); await mode(page, 'memory');
        report.databases = await page.evaluate(() => indexedDB.databases());
      } else {
        const capacity = id === 'competing-pins-at-capacity';
        if (capacity) await page.evaluate(() => window.storageFixture.seed([0, 1, 2, 3, 4, 5, 6]));
        await mount(page);
        report.before.push(await page.evaluate(readNativeRecord));
        if (id === 'two-pages-concurrent-pins' || capacity) {
          report.schedule = 'two native command transactions queued behind active readwrite barrier; writes serialize, not simultaneous execution';
          const sibling = await context.newPage(); pages.push(sibling); await sibling.goto(origin + '/');
          await mount(sibling);
          report.before.push(await sibling.evaluate(readNativeRecord));
          await page.evaluate(() => window.storageFixture.barrier());
          const pending = pages.map((p, index) => p.evaluate(i => window.storageFixture.pin(i), capacity ? index + 7 : index));
          // Fault paths may close a page before the aggregate await is reached.
          for (const command of pending) void command.catch(() => {});
          // Preserve both created transaction witnesses while the barrier is still live.
          for (const p of pages) await expect.poll(async () => (await audit(p)).events.filter(e => e.type === 'transaction-created' && e.label === 'command' && e.mode === 'readwrite').length).toBe(1);
          report.queued = await Promise.all(pages.map(audit));
          for (const a of report.queued) assert(!a.events.some(e => e.label === 'command' && ['get-success', 'transaction-complete', 'command-outcome'].includes(e.type)));
          assert(has(report.queued[0], 'barrier-active')); assert(!has(report.queued[0], 'barrier-release'));
          await page.evaluate(() => window.storageFixture.release());
          report.outcomes = await Promise.all(pending);
          assert.deepEqual([...report.outcomes].sort(), capacity ? ['committed', 'limit'] : ['committed', 'committed']);
          for (const p of pages) { await p.evaluate(() => window.storageFixture.refresh()); await mode(p, 'persistent'); report.after.push(await p.evaluate(readNativeRecord)); }
          const expected = capacity ? [...expectedReferences.slice(0, 7), expectedReferences[7 + report.outcomes.indexOf('committed')]] : expectedReferences.slice(0, 2);
          for (const observation of report.after) validateDurablePins(observation, expected);
          assert.equal(report.after[0].raw, report.after[1].raw);
        } else if (id === 'commit-notification-failure' || id === 'request-success-then-abort') {
          const abort = id === 'request-success-then-abort';
          report.fault = abort ? 'native put success listener calls same transaction.abort before complete' : 'BroadcastChannel.prototype.postMessage throws after native command transaction complete';
          await page.evaluate(abort => abort ? window.storageFixture.armAbort() : window.storageFixture.armPostFailure(), abort);
          report.outcomes = [await page.evaluate(() => window.storageFixture.pin(0))];
          report.after.push(await page.evaluate(readNativeRecord));
          assert.equal(report.outcomes[0], abort ? 'unavailable' : 'committed');
          if (abort) assert.equal(report.before[0].raw, report.after[0].raw);
          else validateDurablePins(report.after[0], expectedReferences.slice(0, 1));
          await mode(page, abort ? 'memory' : 'persistent');
        } else if (id === 'versionchange') {
          await page.evaluate(() => window.storageFixture.upgrade()); await mode(page, 'memory');
          report.retired = await audit(page);
          report.outcomes = [await page.evaluate(() => window.storageFixture.pin(0))];
          await page.evaluate(() => window.storageFixture.refresh());
          report.after.push(await page.evaluate(readNativeRecord));
          assert.equal(report.after[0].raw, report.before[0].raw);
          report.databases = await page.evaluate(() => indexedDB.databases());
        } else if (id === 'missing-record') {
          await page.evaluate(() => window.storageFixture.removeRecord());
          report.deleted = await page.evaluate(readNativeRecord);
          await page.evaluate(() => window.storageFixture.refresh()); await mode(page, 'memory');
          report.outcomes = [await page.evaluate(() => window.storageFixture.pin(0))];
          await page.evaluate(() => window.storageFixture.refresh());
          report.after.push(await page.evaluate(readNativeRecord));
          assert.equal(report.after[0].state, 'absent-record'); assert.equal(report.outcomes[0], 'memory');
        } else if (id === 'notification-no-authority') {
          report.payloads = [{ revision: 999, preferences: { pins: expectedReferences.slice(0, 1) } }, { type: 'library-preferences-changed/v1', revision: 999 }, 'foreign', null];
          report.beforeMessages = await audit(page);
          await page.evaluate(messages => window.storageFixture.messages(messages), report.payloads);
          report.invalidDelivered = await audit(page);
          const count = a => a.events.filter(e => e.type === 'transaction-created').length;
          assert.equal(count(report.beforeMessages), count(report.invalidDelivered), 'invalid payload must not refresh');
          await page.evaluate(() => window.storageFixture.barrier());
          report.beforeHints = await audit(page);
          await page.evaluate(() => window.storageFixture.messages(Array(16).fill('library-preferences-changed/v1')));
          report.heldHints = await audit(page);
          assert.equal(count(report.heldHints) - count(report.beforeHints), 1, 'one queued readonly refresh');
          await page.evaluate(() => window.storageFixture.release());
          await expect.poll(async () => (await audit(page)).events.filter(e => e.type === 'transaction-complete' && e.mode === 'readonly').length - report.beforeHints.events.filter(e => e.type === 'transaction-complete' && e.mode === 'readonly').length).toBe(2);
          report.afterHints = await audit(page);
          report.after.push(await page.evaluate(readNativeRecord));
          assert.equal(report.before[0].raw, report.after[0].raw);
          assert.deepEqual(report.afterHints.snapshot.preferences, report.beforeMessages.snapshot.preferences);
          // Independently mount the actual Library UI, without parent confirmation.
          const ui = await context.newPage(); pages.push(ui); await ui.goto(origin + '/');
          await ui.evaluate(() => window.storageFixture.mountUI());
          await ui.getByRole('button', { name: 'Inspect Synthetic reference 1', exact: true }).click();
          await expect.poll(async () => (await audit(ui)).events.filter(e => e.type === 'transaction-complete' && e.mode === 'readwrite').length).toBe(1);
          await expect(ui.getByText('Loading Library preferences…', { exact: true })).toHaveCount(0);
          report.uiReady = await audit(ui);
          await expect(ui.getByRole('button', { name: 'Pin exact revision', exact: true })).toBeDisabled();
          const uiState = async () => ({
            openRequests: await ui.getByLabel('Fixture open requests', { exact: true }).textContent(),
            pinDisabled: await ui.getByRole('button', { name: 'Pin exact revision', exact: true }).isDisabled(),
            pins: await ui.getByRole('region', { name: 'Pinned revisions', exact: true }).innerText(),
          });
          report.uiBefore = await uiState();
          assert.equal(report.uiBefore.pins, 'Pinned revisions\n\nNo pinned revisions.');
          await ui.evaluate(messages => window.storageFixture.messages(messages), [...report.payloads, 'library-preferences-changed/v1']);
          // Require the actual production connection's completed refresh; an
          // independent observer transaction cannot substitute for this witness.
          await expect.poll(async () => (await audit(ui)).events.filter(e => e.type === 'transaction-complete' && e.mode === 'readonly' && e.role === 'production' && e.seq > report.uiReady.events.length).length).toBe(1);
          report.uiRecord = await ui.evaluate(readNativeRecord);
          report.uiAfter = await uiState();
          assert.deepEqual(report.uiAfter, report.uiBefore);
          assert.equal(report.uiAfter.openRequests, '0'); assert.equal(report.uiAfter.pinDisabled, true);
          assert.equal(report.uiRecord.raw, report.after[0].raw);
        }
      }
      report.audits = await Promise.all(pages.map(audit));
      assert(report.audits.every(a => a.overflow === false));
      report.status = 'observed';
    } catch (error) {
      report.status = 'failed'; report.error = String(error).slice(0, 2048);
      report.audits = await Promise.all(pages.map(p => audit(p).catch(error => ({ error: String(error) }))));
    } finally {
      try {
        for (const page of pages) await page.evaluate(() => window.storageFixture?.close());
        report.closed = await Promise.all(pages.map(audit));
      } catch (error) { report.status = 'failed'; report.cleanup_error = String(error); }
      try { if (context) { await context.close(); report.cleanup_verified = true; } }
      catch (error) { report.status = 'failed'; report.cleanup_error = String(error); }
      await writeFile(`/evidence/native-case-${id}.json`, JSON.stringify(report, null, 2));
    }
    proof.required_cases[id] = report.status === 'observed' ? 'observed' : 'failed';
    // Keep exercising independent fresh contexts, preserving the exact failing trace.
  }
  assert(Object.values(cases).every(row => row.status === 'observed'), 'native case failures: ' + Object.values(cases).filter(row => row.status !== 'observed').map(row => row.id).join(', '));
}

async function preflight() {
  assert.equal(process.getuid(), 1000);
  const status = await readFile('/proc/self/status', 'utf8');
  assert.match(status, /CapEff:\s+0+\n/); assert.match(status, /NoNewPrivs:\s+1\n/);
  assert.deepEqual(await readdir('/sys/class/net'), ['lo']);
  assert.deepEqual(await readdir('/private'), []);
  assert(!(await readdir('/dev')).some(name => name.startsWith('nvidia') || name === 'dri'));
  const mounts = (await readFile('/proc/self/mountinfo', 'utf8')).split('\n').map(line => line.split(' '));
  for (const target of ['/', '/app', '/app/node_modules']) {
    assert(mounts.some(row => row[4] === target && row[5].split(',').includes('ro')), 'readonly mount required');
  }
  const code = await new Promise((resolve, reject) => {
    const socket = net.createConnection({ host: '198.18.0.1', port: 9 });
    socket.setTimeout(2000, () => { socket.destroy(); reject(Error('denial timeout')); });
    socket.once('connect', () => { socket.destroy(); reject(Error('egress possible')); });
    socket.once('error', error => { socket.destroy(); resolve(error.code); });
  });
  assert(['ENETUNREACH', 'EHOSTUNREACH', 'EPERM', 'EACCES'].includes(code));
  // Host must run the reused frontend_checks.PROBE dependency scan in this same
  // owned container before this driver. Do not import mutable packages without it.
  const dependencies = JSON.parse(await readFile('/evidence/preimport-frontend.json', 'utf8'));
  assert.equal(dependencies.status, 'passed'); assert.equal(dependencies.before_repository_imports, true);
  assert.equal(dependencies.egress_denied, true); assert.equal(dependencies.uid, 1000);
  const proof = { status: 'passed', uid: 1000, egress_denied: true, code, before_repository_imports: true };
  await writeFile('/evidence/preimport-storage-browser.json', JSON.stringify(proof));
}

export const requiredCases = Object.freeze(['two-pages-concurrent-pins', 'competing-pins-at-capacity',
  'legacy-exact-unchanged', 'commit-notification-failure', 'request-success-then-abort',
  'blocked-open-late-success', 'versionchange', 'missing-record', 'notification-no-authority']);
export function probeExit(proof) {
  if (!proof.cleanup_verified || proof.errors.length || proof.status === 'failed') return 1;
  return proof.status === 'passed' && requiredCases.every(name => proof.required_cases?.[name] === 'observed') ? 0 : 2;
}
// A builtin-only orchestration seam: units inject inert callbacks, never packages.
export async function executeProbe(phases) {
  const proof = { schema_version: 1, status: 'failed', profile: 'native-ui-storage-probe-v1',
    real_api_evidence: false, rejected: [], errors: [], network: { overflow: false },
    required_cases: Object.fromEntries(requiredCases.map(name => [name, 'NOT-RUN'])), phases: [], cleanup_verified: false };
  let browser, context;
  const phase = async (name, ...args) => {
    proof.phases.push({ name, status: 'started' });
    const result = await phases[name](...args);
    proof.phases.at(-1).status = 'completed'; return result;
  };
  try {
    await phase('preflight');
    const packages = await phase('imports');
    await phase('build', packages);
    const fixture = await phase('load', packages);
    proof.fixture_sha256 = Object.fromEntries([...fixture].map(([name, data]) => [name, data.sha256]));
    browser = await phase('launch', packages);
    proof.browser_version = browser.version();
    context = await phase('context', browser, proof);
    await phase('routes', context, fixture, proof);
    proof.result = await phase('observe', context, packages, proof);
    assert.equal(proof.rejected.length, 0); assert.equal(proof.network.overflow, false); assert.equal(proof.errors.length, 0);
    proof.status = 'PARTIAL'; // Candidate cases await independent parent release.
  } catch (error) { proof.errors.push(String(error).slice(0, 2048)); }
  finally {
    let clean = true;
    for (const resource of [context, browser]) {
      try { if (resource) await resource.close(); }
      catch (error) { clean = false; proof.status = 'failed'; proof.errors.push(String(error).slice(0, 2048)); }
    }
    proof.cleanup_verified = clean;
    await phases.save(proof); // Write failure propagates to the executable's nonzero exit.
  }
  return proof;
}

export async function runNativeStorageProbe() {
  let loader;
  return executeProbe({
    preflight,
    imports: async () => {
      loader = await import('./ui-storage-fixture-loader.mjs');
      const require = createRequire('/app/package.json');
      assert.equal(require('@playwright/test/package.json').version, '1.58.2');
      const { chromium, expect } = require('@playwright/test');
      const { build } = await import('/app/node_modules/vite/dist/node/index.js');
      return { chromium, expect, build };
    },
    build: async ({ build }) => {
      await build({ configFile: false, root: '/app', publicDir: false, esbuild: { jsx: 'automatic' },
        define: { 'process.env.NODE_ENV': '"production"' },
        build: { outDir: '/evidence/dist', emptyOutDir: false, minify: false, cssCodeSplit: false,
          lib: { entry: '/app/tests/e2e/functional-v7/ui-storage-fixture.tsx', name: 'NativeStorageFixture', formats: ['iife'], cssFileName: 'fixture' },
          rollupOptions: { output: { entryFileNames: 'fixture.js', assetFileNames: 'fixture.[ext]' } } } });
      await writeFile('/evidence/dist/fixture.html', '<!doctype html><html><head><meta charset="utf-8"><title>Test-only native storage</title><link rel="stylesheet" href="/fixture.css"></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>');
    },
    load: () => loader.loadFixture('/evidence/dist'),
    launch: ({ chromium }) => chromium.launch({ headless: true, args: ['--disable-gpu', '--disable-background-networking',
      '--disable-component-update', '--disable-sync', '--no-first-run', '--disable-default-apps'] }),
    context: async browser => browser.newContext({ serviceWorkers: 'block' }),
    routes: async (context, fixture, proof) => {
      context.setDefaultTimeout(5000); context.setDefaultNavigationTimeout(5000);
      context.on('page', page => page.on('pageerror', error => {
        if (proof.errors.length < 32) proof.errors.push(String(error).slice(0, 2048));
      }));
      await loader.installFixtureRoutes(context, fixture, proof.rejected, proof.network);
    },
    observe: async (context, { expect }, proof) => {
      await observeTwoPages(context, expect, loader.ORIGIN, (proof.result = {}));
      const fixture = await loader.loadFixture('/evidence/dist');
      await observeNativeCases(context.browser(), async next => {
        next.setDefaultTimeout(5000); next.setDefaultNavigationTimeout(5000);
        next.on('page', page => page.on('pageerror', error => {
          if (proof.errors.length < 32) proof.errors.push(String(error).slice(0, 2048));
        }));
        await loader.installFixtureRoutes(next, fixture, proof.rejected, proof.network);
      }, expect, loader.ORIGIN, proof);
      return proof.result;
    },
    save: proof => writeFile('/evidence/storage-browser.json', JSON.stringify(proof, null, 2)),
  });
}
