// Copyright (c) 2026, The Isaac Lab Arena Project Developers.
// SPDX-License-Identifier: Apache-2.0
// Real Chromium -> private loopback bridge -> UDS production API. No fulfilled API mocks.
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { readFile, writeFile, readdir, rename } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';

import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

// Import-safe seam for deterministic suppression/delay/reordering tests.
export function createValidationTracker() {
  let sequence = 0;
  const requests = new WeakMap(), records = [];
  return {
    get sequence() { return sequence; },
    records,
    request(request) {
      if (request.method() !== 'POST' || new URL(request.url()).pathname !== '/api/editor/validate') return;
      const request_body = request.postData();
      const payload = JSON.parse(request_body);
      const record = { sequence: ++sequence, request_body,
        request: Object.freeze({ yaml_text: payload.yaml_text, document_id: payload.document_id }) };
      requests.set(request, record); records.push(record);
    },
    async response(response) {
      const record = requests.get(response.request());
      if (!record) return; // Never adopt an unobserved response, even with identical bytes.
      record.status = response.status();
      try {
        const body = await response.json();
        record.response = body;
        record.response_request_sequence = record.sequence;
      } catch (error) { record.error = String(error); }
    },
    match(after, yaml, view) {
      return records.find(record => record.sequence > after && record.status === 200 &&
        record.response_request_sequence === record.sequence && record.response &&
        record.request.yaml_text === yaml && record.request.document_id === view);
    },
  };
}

export async function main() {
const out = '/evidence', origin = 'http://127.0.0.1:31847';
const profile = process.env.F0_PROFILE ?? 'readonly';
assert(['readonly', 'authoring-v1', 'manual-research-v1'].includes(profile));
const proof = { schema_version: 2, profile, status: 'failed', external: [], errors: [], forbidden: [], http: [] };
const sha256 = value => createHash('sha256').update(value).digest('hex');
let browser, context, server;
async function preflight() {
  assert.equal(process.getuid(), 1000);
  const status = await readFile('/proc/self/status', 'utf8');
  assert.match(status, /CapEff:\s+0+\n/);
  assert.match(status, /NoNewPrivs:\s+1\n/);
  assert.deepEqual(Object.keys(os.networkInterfaces()), ['lo']);
  assert(!(await readdir('/dev')).some(name => name.startsWith('nvidia') || name === 'dri'));
  const mounts = await readFile('/proc/self/mountinfo', 'utf8');
  for (const target of ['/', '/source', '/app', '/app/node_modules']) {
    const mount = mounts.split('\n').map(line => line.split(' ')).find(fields => fields[4] === target);
    assert(mount && mount[5].split(',').includes('ro'), `Read-only required: ${target}`);
  }
  const code = await new Promise((resolve, reject) => {
    const probe = net.createConnection({ host: '1.1.1.1', port: 443 });
    probe.setTimeout(2000, () => { probe.destroy(); reject(Error('Egress probe timed out; denial unproven')); });
    probe.once('connect', () => { probe.destroy(); reject(Error('Egress unexpectedly possible')); });
    probe.once('error', error => { probe.destroy(); resolve(error.code); });
  });
  assert(['ENETUNREACH', 'EHOSTUNREACH', 'EPERM', 'EACCES'].includes(code));
  proof.preimport = { schema_version: 2, status: 'passed', uid: process.getuid(), egress_denied: true,
    code, before_repository_imports: true, caps: '0000000000000000', no_new_privileges: true,
    readonly_source_root_deps: true, gpu_devices: [] };
  await writeFile(`${out}/preimport-browser.json`, JSON.stringify(proof.preimport, null, 2));
}
try {
  await preflight();
  // Dependency and repository imports happen only after the actual denial probe.
  const require = createRequire('/app/package.json');
  const { chromium, expect } = require('@playwright/test');
  assert.equal(require('@playwright/test/package.json').version, '1.58.2');
  proof.frontend_dependencies = { playwright_version: '1.58.2',
    files: Object.fromEntries(await Promise.all(['.package-lock.json', '@playwright/test/package.json', 'vite/package.json']
      .map(async name => [name, sha256(await readFile(`/app/node_modules/${name}`))]))) };
  const build = spawnSync('node', ['/app/node_modules/vite/bin/vite.js', 'build', '--configLoader', 'runner',
    '--outDir', `${out}/dist`], { cwd: '/app', encoding: 'utf8', timeout: 120000 });
  await writeFile(`${out}/build.log`, `${build.stdout}\n${build.stderr}`);
  assert.equal(build.status, 0, build.error?.message ?? build.stderr);
  server = http.createServer(async (request, response) => {
    const url = new URL(request.url, origin);
    if (url.pathname.startsWith('/api/')) {
      const record = { method: request.method, path: url.pathname };
      proof.http.push(record);
      const allowed = request.method === 'GET' || request.method === 'HEAD' ||
        (request.method === 'POST' && ['/api/sessions', '/api/session/activity', '/api/editor/validate'].includes(url.pathname)) ||
        (request.method === 'DELETE' && url.pathname === '/api/session') ||
        (['authoring-v1', 'manual-research-v1'].includes(profile) && request.method === 'POST' && url.pathname === '/api/editor/save') ||
        (profile === 'manual-research-v1' && request.method === 'POST' && url.pathname === '/api/research/stores/manual-browser/versions');
      if (!allowed) {
        proof.forbidden.push(record);
        response.writeHead(403); response.end('F0 workload denied'); return;
      }
      const upstream = http.request({ socketPath: '/bridge/api.sock', path: request.url, method: request.method,
        headers: { ...request.headers, host: '127.0.0.1:31847', connection: 'close' } }, received => {
        record.status = received.statusCode;
        response.writeHead(received.statusCode, received.headers);
        received.pipe(response);
      });
      upstream.on('error', error => { record.error = error.message; response.writeHead(502); response.end('Private UDS unavailable'); });
      response.on('close', () => upstream.destroy());
      request.pipe(upstream);
      return;
    }
    try {
      const target = url.pathname.startsWith('/assets/') ? path.resolve(`${out}/dist`, '.' + decodeURIComponent(url.pathname)) : `${out}/dist/index.html`;
      assert(target.startsWith(`${out}/dist/`));
      const bytes = await readFile(target);
      const mime = { '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.woff2': 'font/woff2' }[path.extname(target)] ?? 'text/html';
      response.writeHead(200, { 'content-type': mime }); response.end(bytes);
    } catch { response.writeHead(404); response.end(); }
  });
  await new Promise(resolve => server.listen(31847, '127.0.0.1', resolve));
  browser = await chromium.launch({ headless: true, args: ['--disable-gpu', '--disable-background-networking',
    '--disable-component-update', '--disable-sync', '--no-first-run', '--disable-default-apps'] });
  proof.browser_version = browser.version();
  context = await browser.newContext({ baseURL: origin, viewport: { width: 1440, height: 1100 } });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin !== origin) {
      proof.external.push(route.request().url()); return route.abort();
    }
    return route.continue();
  });
  await context.routeWebSocket('**/*', websocket => { proof.external.push(websocket.url()); websocket.close(); });
  const page = await context.newPage();
  let manualTracker, manualDriver;
  if (profile === 'manual-research-v1') {
    const manual = await import('./browser-manual-research.mjs');
    manualTracker = manual.createExchangeTracker(); manualDriver = manual.manualResearch;
    page.on('request', request => { try { manualTracker.request(request); } catch (error) { proof.errors.push(String(error)); } });
    page.on('response', response => { void manualTracker.response(response); });
  }
  page.on('pageerror', error => proof.errors.push(error.message));
  const validations = createValidationTracker();
  proof.validation_exchanges = validations.records;
  page.on('request', request => {
    try { validations.request(request); } catch (error) { proof.errors.push(String(error)); }
  });
  page.on('response', response => { void validations.response(response); });
  const layout = process.env.LAYOUT === 'v7' ? '?layout=v7' : '';
  await page.goto(`/workspaces/default${layout}`);
  if (process.env.LAYOUT === 'v7') await expect(page.locator('.workbench-chrome')).toBeVisible({ timeout: 15000 });
  else await expect(page.locator('.workbench-chrome')).toHaveCount(0);
  proof.layout_verified = true;
  await expect(page.locator('.cm-editor')).toBeVisible({ timeout: 45000 });
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible({ timeout: 45000 });
  proof.schema_valid_visible = true;
  const api = JSON.parse(await readFile(`${out}/api-proof.json`, 'utf8'));
  assert.equal(api.schema_version, 2);
  assert.equal(api.status, 'passed');
  const fixtureText = await readFile('/source/isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml', 'utf8');
  // Each phase requires a NEW request with exact bytes, then THAT object's response.
  // Canonical equality cannot distinguish the added newline, and is never a wait predicate.
  const content = page.locator('.cm-content');
  proof.validation_phases = [];
  for (const [phase, yaml] of [['edit', fixtureText + '\n'], ['restore', fixtureText]]) {
    const after_sequence = validations.sequence;
    await content.fill(yaml);
    await expect.poll(() => !!validations.match(after_sequence, yaml, api.view_id), { timeout: 15000 }).toBe(true);
    const exchange = validations.match(after_sequence, yaml, api.view_id);
    assert.equal(exchange.response.valid, true);
    assert.equal(exchange.response.source_hash, sha256(yaml));
    assert.equal(exchange.response.canonical_hash, api.validation.canonical_hash);
    proof.validation_phases.push({ phase, after_sequence, request_sequence: exchange.sequence });
    if (phase === 'restore') {
      proof.validation_request = exchange.request;
      proof.validation = exchange.response;
    }
  }
  await expect(content).toBeVisible();
  proof.final_editor_visible = true;
  // Read the populated editor through its actual select-all/copy command, not fixture/state fallback.
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.evaluate(() => navigator.clipboard.writeText('F0: no editor bytes copied yet'));
  await content.click();
  await expect(content).toBeFocused();
  await page.keyboard.press('Control+a');
  await page.keyboard.press('Control+c');
  proof.final_editor_yaml = await page.evaluate(() => navigator.clipboard.readText());
  assert.equal(proof.final_editor_yaml, fixtureText);
  proof.final_editor_readback = 'visible-codemirror-select-all-clipboard';
  proof.final_editor_sha256 = sha256(proof.final_editor_yaml);
  await page.keyboard.press('ArrowRight');
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  proof.source = api.source;
  proof.source_hash = sha256(fixtureText);
  proof.source_id = api.source_id; proof.view_id = proof.validation_request.document_id;
  const readbacks = await page.evaluate(async () => {
    const result = {};
    for (const name of ['schema', 'catalogues']) {
      const response = await fetch(`/api/editor/${name}`);
      result[name] = { status: response.status, body: await response.json() };
    }
    const response = await fetch('/api/jobs');
    result.jobs = { status: response.status, body: await response.json() };
    return result;
  });
  assert.equal(readbacks.schema.status, 200); assert.equal(readbacks.catalogues.status, 200);
  assert.equal(readbacks.jobs.status, 200);
  assert.equal(readbacks.schema.body.schema_sha256, api.schema.schema_sha256);
  assert.equal(readbacks.catalogues.body.catalogue_sha256, api.catalogues.catalogue_sha256);
  assert.deepEqual(readbacks.jobs.body.jobs, []);
  proof.readbacks = readbacks;
  proof.layout = process.env.LAYOUT ?? 'legacy';
  await page.screenshot({ path: `${out}/browser.png`, fullPage: true });
  if (profile === 'authoring-v1') {
    const { authoring } = await import('./browser-authoring.mjs');
    await authoring({ page, context, proof, api, validations, expect, out, sha256 });
  }
  if (profile === 'manual-research-v1') {
    await manualDriver({page, proof, api, expect, out, sha256, tracker: manualTracker});
  }
  assert.deepEqual(proof.external, []); assert.deepEqual(proof.forbidden, []); assert.deepEqual(proof.errors, []);
  assert(proof.http.some(row => row.path === `/api/editor/documents/${api.source_id}` && row.status === 200));
  proof.status = 'passed';
} catch (error) {
  proof.error = error.stack ?? String(error);
  if (context?.pages()[0]) {
    await context.pages()[0].screenshot({path: `${out}/browser-failure.png`, fullPage: true}).catch(() => {});
    await writeFile(`${out}/browser-failure.txt`, await context.pages()[0].locator('body').innerText().catch(() => 'Page unavailable'));
  }
  console.error(proof.error);
} finally {
  if (context) await context.tracing.stop({ path: `${out}/browser-trace.zip` });
  if (browser) await browser.close();
  if (server) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
  await writeFile(`${out}/browser-proof.pending`, JSON.stringify(proof, null, 2));
  await rename(`${out}/browser-proof.pending`, `${out}/browser-proof.json`);
}
return proof.status === 'passed' ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main();
}
