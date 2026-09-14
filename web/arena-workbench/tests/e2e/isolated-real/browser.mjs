// Real Chromium -> loopback forwarding proxy -> production UDS API. No route/fulfill fixtures.
import http from 'node:http';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
const require = createRequire('/app/package.json');
const { chromium, expect } = require('@playwright/test');
const root = '/acceptance', port = 31847, origin = `http://127.0.0.1:${port}`;
const hash = value => createHash('sha256').update(value).digest('hex');
const proof = { kind: 'REAL browser/HTTP/API/journal/store; deterministic generation only', origin, http: [], external: [], errors: [], jobs: [], commits: [], attachments: [] };
const redact = data => {
  try { const v = JSON.parse(data); if (v.csrf_token) v.csrf_token = `[sha256:${hash(v.csrf_token)}]`; return v; }
  catch { return data.slice(0, 4096); }
};
const server = http.createServer(async (req, res) => {
  if (req.url.startsWith('/api/')) {
    const record = { method: req.method, path: req.url, csrf_sha256: req.headers['x-csrf-token'] ? hash(req.headers['x-csrf-token']) : null };
    proof.http.push(record);
    let body = '';
    req.on('data', c => body += c);
    req.on('end', () => record.request = redact(body));
    const upstream = http.request({ socketPath: `${root}/ipc/api.sock`, path: req.url, method: req.method, headers: { ...req.headers, host: `127.0.0.1:${port}`, 'accept-encoding': '', connection: 'close' } }, response => {
      record.status = response.statusCode;
      res.writeHead(response.statusCode, response.headers);
      let chunks = '';
      response.on('data', c => { if (chunks.length < 2 * 1024 * 1024) chunks += c; });
      response.on('end', () => record.response = redact(chunks));
      response.pipe(res);
    });
    upstream.on('error', e => { record.transport_error = e.message; res.writeHead(502); res.end('Isolated UDS unavailable'); });
    res.on('close', () => upstream.destroy());
    req.pipe(upstream);
    return;
  }
  try {
    const url = new URL(req.url, origin);
    const path = url.pathname.startsWith('/assets/') ? url.pathname : '/index.html';
    assert(!path.includes('..'));
    const data = await readFile(`${root}/dist${path}`);
    res.writeHead(200, { 'content-type': path.endsWith('.js') ? 'text/javascript' : path.endsWith('.css') ? 'text/css' : 'text/html' });
    res.end(data);
  } catch { res.writeHead(404); res.end(); }
});
let browser, context, page;
const get = async path => page.evaluate(async path => { const r = await fetch(path); return { status: r.status, body: await r.json() }; }, path);
async function generate(operation) {
  await page.getByRole('radio', { name: operation === 'new' ? 'New environment from prompt' : 'Refine current environment', exact: true }).check();
  await page.getByLabel('Describe the environment and task').fill(`Isolated deterministic ${operation} acceptance; no model execution`);
  const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/editor/generate' && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Generate spec', exact: true }).click();
  const accepted = await response;
  assert.equal(accepted.status(), 202);
  const ack = await accepted.json();
  const body = accepted.request().postDataJSON();
  assert.equal(body.operation, operation);
  if (operation === 'new') { assert(!('yaml_text' in body)); assert(!('base_yaml' in body)); assert(!('document_id' in body)); }
  else { assert.equal(typeof body.base_yaml, 'string'); assert(body.base_yaml.length > 10); }
  let job;
  await expect.poll(async () => { job = (await get(`/api/jobs/${ack.id}`)).body; return job.status; }, { timeout: 30000 }).toBe('succeeded');
  assert.equal(job.id, ack.id);
  assert.equal(job.result.operation, operation);
  assert.equal(job.result.prior_snapshot.status, operation === 'new' ? 'unavailable' : 'not_requested');
  assert.equal(job.result.validation.valid, true);
  assert.equal(job.result.publication, 'not_published');
  proof.jobs.push(job);
  await expect(page.getByRole('button', { name: 'Apply generated YAML', exact: true })).toBeVisible();
  await page.screenshot({ path: `${root}/${operation}-candidate.png`, fullPage: true });
  return job;
}
async function save(prepared, parent = null) {
  const open = page.getByRole('button', { name: 'Open research versions', exact: true });
  if (await open.count()) await open.click();
  await page.getByRole('combobox', { name: /^Research store/ }).selectOption('isolated');
  await page.getByLabel('Research family', { exact: true }).fill('IsolatedAcceptance');
  if (parent) {
    await page.getByRole('button', { name: `Select version ${parent.version}`, exact: true }).click();
    await page.getByRole('combobox', { name: /^Parent revision/ }).selectOption(parent.revision_id);
  }
  await page.getByLabel('Prepare publication on save', { exact: true }).setChecked(prepared);
  if (prepared) await page.getByRole('combobox', { name: /^Publication profile/ }).selectOption('isolated-unreachable');
  const response = page.waitForResponse(r => /\/stores\/isolated\/versions$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Save research version', exact: true }).click();
  const ack = await response;
  assert.equal(ack.status(), 201);
  const commit = await ack.json();
  const base = `/api/research/stores/isolated/versions/${commit.reservation.reservation_id}`;
  const readback = await get(base);
  assert.equal(readback.status, 200); assert.deepEqual(readback.body, commit);
  assert.equal(commit.reservation.parent_revision_id, parent?.revision_id ?? null);
  assert.equal(!!commit.publication_intent_id, prepared);
  proof.commits.push(commit);
  const expectedMessage = prepared ? 'Research version saved and verified. Profile isolated-unreachable: prepared, not published. Graph publication was not performed.' : 'Research version saved and verified. Graph publication was not performed.';
  await expect(page.getByText(expectedMessage, { exact: true })).toBeVisible();
  await expect(page.getByText(`Latest committed version: ${commit.reservation.version}`, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: `Select version ${commit.reservation.version}`, exact: true }).click();
  const attachment = await page.evaluate(async url => { const r = await fetch(url); return { status: r.status, text: await r.text(), disposition: r.headers.get('content-disposition') }; }, `${base}/artifacts/environment.yaml`);
  assert.equal(attachment.status, 200);
  const sha256 = hash(attachment.text);
  assert.equal(sha256, hash(proof.jobs.at(-1).result.yaml_text));
  assert.equal(sha256, commit.manifest.files['environment.yaml'].sha256);
  proof.attachments.push({ url: `${base}/artifacts/environment.yaml`, status: attachment.status, sha256, disposition: attachment.disposition });
  if (prepared) {
    const bindingPath = `${base}/publication-binding`;
    assert.equal(proof.http.filter(r => r.path === bindingPath).length, 0);
    const snapshot = async () => ({
      yaml: await page.evaluate(() => JSON.parse(sessionStorage.getItem('arena.editor.draft.v1')).draft),
      rendered: await page.locator('.cm-content').innerText(),
    });
    const before = await snapshot();
    assert.equal(before.yaml, proof.jobs[0].result.yaml_text);
    await writeFile(`${root}/controls-before.yaml`, before.yaml);
    const bindingResponse = page.waitForResponse(r => new URL(r.url()).pathname === bindingPath && r.request().method() === 'GET');
    await page.getByRole('button', { name: 'Open publication execution', exact: true }).click();
    const response = await bindingResponse;
    assert.equal(response.status(), 200);
    const binding = await response.json();
    assert.equal(binding.storeId, 'isolated');
    assert.equal(binding.effectId, commit.publication_intent_id);
    assert.equal(binding.registryId, commit.reservation.registry_id);
    assert.deepEqual(binding.target, commit.reservation.publication_request.target_profile);
    for (const field of ['reservation_id', 'revision_id', 'version']) assert.equal(binding.versionRef[field], commit.reservation[field]);
    assert.equal(binding.versionRef.database, 'neo4j');
    proof.preparation_binding = binding;
    await page.getByRole('button', { name: 'Open publication controls', exact: true }).click();
    const controls = page.getByRole('region', { name: 'Publication controls', exact: true });
    await expect(controls.getByRole('status')).toHaveText('Publication status unchecked.');
    await expect(controls.getByRole('button', { name: 'Publish graph', exact: true })).toBeEnabled();
    for (const name of ['Renew blocked unsent request', 'Reconcile read-only', 'Cancel current attempt']) await expect(controls.getByRole('button', { name, exact: true })).toBeDisabled();
    const scopeText = `Store ${binding.storeId}; effect ${binding.effectId}; profile ${binding.target.profile_id} (${binding.target.revision}, ${binding.target.scope_ownership}); Version ${binding.versionRef.version}, revision ${binding.versionRef.revision_id}, reservation ${binding.versionRef.reservation_id}.`;
    await expect(controls.getByText(scopeText, { exact: true })).toBeVisible();
    const after = await snapshot();
    assert.deepEqual(after, before);
    await writeFile(`${root}/controls-after.yaml`, after.yaml);
    proof.mounted_controls = { binding_request_from_ui: true, binding_path: bindingPath, scope_text: scopeText,
      status: await controls.getByRole('status').innerText(), fields: await controls.locator('button').evaluateAll(bs => bs.map(b => ({ name: b.textContent, disabled: b.disabled }))),
      yaml_before_sha256: hash(before.yaml), yaml_after_sha256: hash(after.yaml), rendered_yaml_unchanged: true };
    await page.screenshot({ path: `${root}/mounted-publication-controls.png`, fullPage: true });
    await page.getByRole('button', { name: 'Close publication controls', exact: true }).click();
    await page.getByRole('button', { name: 'Close publication execution', exact: true }).click();
    assert.equal(proof.http.filter(r => r.path === bindingPath).length, 1);
  }
  await page.screenshot({ path: `${root}/${prepared ? 'prepared' : 'saved'}.png`, fullPage: true });
  return commit.reservation;
}
try {
  assert.notEqual(process.getuid(), 0);
  await new Promise(resolve => server.listen(port, '127.0.0.1', resolve));
  await expect.poll(async () => { try { const r = await fetch(`${origin}/api/health`); return r.status === 200 && (await r.json()).status === 'ok'; } catch { return false; } }, { timeout: 60000 }).toBe(true);
  proof.health = await (await fetch(`${origin}/api/health`)).json();
  browser = await chromium.launch({ headless: true, args: ['--disable-background-networking', '--disable-component-update', '--disable-sync', '--no-first-run', '--disable-default-apps', '--disable-dev-shm-usage'] });
  proof.browser = browser.version();
  const browserCDP = await browser.newBrowserCDPSession();
  proof.browser_processes = await browserCDP.send('SystemInfo.getProcessInfo');
  await browserCDP.detach();
  context = await browser.newContext({ baseURL: origin, viewport: { width: 1440, height: 1100 } });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  context.on('request', r => { if (new URL(r.url()).origin !== origin) proof.external.push(r.url()); });
  page = await context.newPage();
  page.on('pageerror', e => proof.errors.push(e.stack ?? e.message));
  page.on('dialog', d => d.accept());
  page.on('websocket', s => { if (new URL(s.url()).host !== new URL(origin).host) proof.external.push(s.url()); });
  const unauth = await fetch(`${origin}/api/jobs`); assert.equal(unauth.status, 401);
  await page.goto('/workspaces/default');
  await expect(page.locator('.cm-editor')).toBeVisible({ timeout: 30000 });
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible({ timeout: 30000 });
  proof.capabilities = (await get('/api/editor')).body;
  assert.equal(proof.capabilities.capabilities.publication_execution, true);
  const csrfRejected = await page.evaluate(async () => { const r = await fetch('/api/editor/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ operation: 'new', prompt: 'rejected without CSRF', idempotency_key: 'must-not-exist' }) }); return r.status; });
  assert.equal(csrfRejected, 403);
  proof.csrf_rejection = csrfRejected;
  await generate('new');
  const first = await save(false);
  await page.getByRole('button', { name: 'Apply generated YAML', exact: true }).click();
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  await generate('refine');
  await save(true, first);
  const jobs = (await get('/api/jobs')).body.jobs;
  assert.deepEqual(jobs.map(j => j.id).sort(), proof.jobs.map(j => j.id).sort());
  assert(jobs.every(j => j.kind === 'generate'));
  const versions = (await get('/api/research/stores/isolated/versions?family=IsolatedAcceptance')).body;
  assert.equal(versions.versions.length, 2); assert.equal(versions.latest_version, 2);
  proof.versions = versions;
  await page.reload();
  await expect(page.locator('.cm-editor')).toBeVisible();
  for (const c of proof.commits) assert.deepEqual((await get(`/api/research/stores/isolated/versions/${c.reservation.reservation_id}`)).body, c);
  assert.deepEqual(proof.external, []); assert.deepEqual(proof.errors, []);
  proof.counters = {
    publication_posts: proof.http.filter(r => r.method === 'POST' && /publication|publish|reconcile|renew|cancel/.test(r.path)).length,
    binding_gets: proof.http.filter(r => r.method === 'GET' && r.path.endsWith('/publication-binding')).length,
    generation_posts: proof.http.filter(r => r.method === 'POST' && r.path === '/api/editor/generate' && r.status === 202).length,
    external_requests: proof.external.length,
  };
  assert.equal(proof.counters.publication_posts, 0);
  assert.equal(proof.counters.binding_gets, 1);
  assert.equal(proof.counters.generation_posts, 2);
  const allowedWrites = new Set(['/api/sessions', '/api/session/activity', '/api/editor/validate', '/api/editor/generate', '/api/research/stores/isolated/versions']);
  proof.counters.unexpected_mutations = proof.http.filter(r => !['GET', 'HEAD'].includes(r.method) && (r.method !== 'POST' || !allowedWrites.has(r.path))).length;
  assert.equal(proof.counters.unexpected_mutations, 0);
  assert(!proof.http.some(r => r.method === 'POST' && /\/(publish|reconcile|renew|cancel|snapshots|grants|evaluate|simulate)(\/|$)/.test(r.path)));
  proof.status = 'passed';
} catch (e) {
  proof.status = 'failed'; proof.failure = e.stack ?? String(e); process.exitCode = 1;
  if (page) { await writeFile(`${root}/failure-dom.txt`, await page.locator('body').innerText().catch(() => 'DOM unavailable')); await page.screenshot({ path: `${root}/failure.png`, fullPage: true }).catch(() => {}); }
} finally {
  if (context) await context.tracing.stop({ path: `${root}/trace.zip` });
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
  await writeFile(`${root}/browser-proof.json`, JSON.stringify(proof, null, 2));
  console.log(JSON.stringify({ status: proof.status, jobs: proof.jobs.map(j => j.id), commits: proof.commits.map(c => c.reservation), failure: proof.failure }));
}
