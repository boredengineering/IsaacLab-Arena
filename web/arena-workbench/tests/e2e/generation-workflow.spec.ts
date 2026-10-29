import { expect, test, type Page, type Route } from '@playwright/test';
import { writeFile } from 'node:fs/promises';

// SYNTHETIC bounded API ONLY; actual published frontend and CodeMirror in Chromium.
// No provider, database, retrieval service, runtime generation or simulator proof.
const sourceYaml = 'env_name: SYNTHETIC_same_source';
const candidate = 'env_name: SYNTHETIC_generated_candidate';
const hostile = '<img src="https://generation-fixture.invalid/leak" onerror="window.__generationXSS=1">';
const validation = { valid: true, source_hash: 'source-a', canonical_hash: 'a'.repeat(64), errors: [], warnings: [], spec: {},
  summary: 'SYNTHETIC validation, not backend acceptance', graph: { nodes: [], edges: [] }, assets: [], relations: [], reified_relations: [], tasks: [] };
type Payload = Record<string, unknown>;
type State = {
  requests: { method: string; path: string; csrf?: string; payload?: Payload }[];
  responses: { method: string; path: string; status: number }[];
  sessions: Payload[]; delayedRoute: Route | null; delay: 'activity' | 'generation' | null;
  generations: Payload[]; validations: Payload[]; unexpected: string[]; external: string[]; errors: string[];
  ambiguous: boolean; lateDocument: Route | null; accepted: Payload | null;
};
const states = new WeakMap<Page, State>();
const blockedJob = { id: 'synthetic-workspace-blocked', kind: 'generate', workspace_id: 'default', status: 'blocked_authorization', stage: 'SYNTHETIC awaiting explicit authorization', inputs: { operation: 'new', prompt: 'SYNTHETIC workspace-only job', retrieval_policy: 'allow_fallback', idempotency_key: 'synthetic-workspace-request' } };
async function retainedRaw(page: Page) { return page.evaluate(() => sessionStorage.getItem('arena:editor:generate:v1')); }
async function reconnectS2(page: Page, state: State) {
  expect(state.sessions).toHaveLength(1);
  await page.getByRole('button', { name: 'Reconnect session', exact: true }).click();
  await expect.poll(() => state.sessions.length).toBe(2);
  await expect(page.getByRole('button', { name: 'Reconnect session', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'End session', exact: true })).toBeVisible();
}
async function verifyS2(page: Page, state: State) {
  const response = page.waitForResponse(r => r.url().endsWith('/api/editor/validate') && r.request().headers()['x-csrf-token'] === 'synthetic-csrf-S2');
  await page.getByRole('button', { name: 'Validate schema', exact: true }).click();
  await (await response).finished();
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  expect(state.sessions).toHaveLength(2);
  expect(state.requests.filter(r => r.path === '/api/editor/validate').at(-1)?.csrf).toBe('synthetic-csrf-S2');
}
test.use({ serviceWorkers: 'block' });
test.setTimeout(35_000);

async function fixture(page: Page, options: { noDocument?: boolean; legacy?: boolean; lateDocument?: boolean; blocked?: boolean; otherRetained?: boolean } = {}) {
  const state: State = { requests: [], responses: [], sessions: [], delayedRoute: null, delay: null, generations: [], validations: [], unexpected: [], external: [], errors: [], ambiguous: false, lateDocument: null, accepted: null };
  states.set(page, state);
  page.on('response', response => { const url = new URL(response.url()); if (url.pathname.startsWith('/api/')) state.responses.push({ method: response.request().method(), path: url.pathname, status: response.status() }); });
  if (options.otherRetained) await page.addInitScript(() => sessionStorage.setItem('arena:editor:generate:v1', JSON.stringify({ payload: { prompt: 'SYNTHETIC other unresolved request', operation: 'new', retrieval_policy: 'require_service', idempotency_key: 'synthetic-other-request' } })));
  page.on('pageerror', error => state.errors.push(error.stack ?? error.message));
  await page.addInitScript(() => Object.defineProperty(window, 'SharedWorker', { value: undefined }));
  // Block WebSocket transport too, including Vite HMR; each test loads fresh source.
  await page.routeWebSocket('**/*', socket => {
    const url = new URL(socket.url());
    // Vite advertises its local dev port; it is still blocked, never connected.
    if (url.host !== '127.0.0.1:5173' && url.host !== new URL(process.env.WORKBENCH_BASE_URL ?? 'http://127.0.0.1:3001').host) state.external.push(`${url.origin}${url.pathname}`);
    socket.close();
  });
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), method = request.method(), path = url.pathname;
    const origin = new URL(process.env.WORKBENCH_BASE_URL ?? 'http://127.0.0.1:3001').origin;
    if (url.origin !== origin) { state.external.push(url.href); return route.abort('blockedbyclient'); }
    if (!path.startsWith('/api/')) {
      if (method === 'GET' && (/^\/(?:src\/|node_modules\/|@vite\/|@react-refresh$|@fs\/|assets\/)/.test(path) || ['/', '/workspaces/default', '/vite.svg', '/favicon.ico'].includes(path))) return route.continue();
      state.unexpected.push(`${method} ${path}`); return route.abort('blockedbyclient');
    }
    const payload = request.postData() ? request.postDataJSON() as Payload : undefined;
    state.requests.push({ method, path, csrf: request.headers()['x-csrf-token'], ...(payload ? { payload } : {}) });
    const json = (value: unknown, status = 200) => route.fulfill({ json: value, status });
    if (state.requests.length > 150) { state.unexpected.push('API request budget exceeded'); return route.abort('blockedbyclient'); }
    if (method === 'GET' && path === '/api/health') return json({ capabilities: { diagnostic: false } });
    if (method === 'POST' && path === '/api/sessions') {
      const session = { session_id: `synthetic-session-S${state.sessions.length + 1}`, csrf_token: `synthetic-csrf-S${state.sessions.length + 1}`, expires_at: 9999999999 };
      state.sessions.push(session); return json(session);
    }
    if (method === 'POST' && path === '/api/session/activity') {
      if (state.delay === 'activity') { state.delayedRoute = route; return; }
      return json(state.sessions.at(-1));
    }
    if (method === 'GET' && path === '/api/model-settings') return json({ configured: true, source: 'server', provider: 'openai', model: 'SYNTHETIC-no-provider-contact', credential_ref: null, expires_at: null, session_keys_allowed: false, providers: [
      { id: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com/v1' },
      { id: 'gemini', label: 'Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/' },
      { id: 'openrouter', label: 'OpenRouter', base_url: 'https://openrouter.ai/api/v1' },
      { id: 'nvidia', label: 'NVIDIA', base_url: 'https://integrate.api.nvidia.com/v1' },
    ] });
    if (method === 'GET' && path === '/api/workspaces/default') return json({ id: 'default', name: 'SYNTHETIC generation browser gate', event_cursor: 0, jobs: options.blocked ? [blockedJob] : [] });
    if (method === 'GET' && path === '/api/jobs/synthetic-workspace-blocked' && options.blocked) return json(blockedJob);
    if (method === 'GET' && path === '/api/editor') return json({ default_document_id: options.noDocument ? '' : 'a', documents: options.noDocument ? [] : ['a', 'b'].map(id => ({ id, name: `Synthetic ${id}`, source: `${id}.yaml` })), capabilities: { generation: true, snapshots: false, neo4j: false, ...(!options.legacy ? { generation_modes: true } : {}) }, limitations: ['SYNTHETIC API; no runtime/provider/database acceptance.'] });
    if (method === 'GET' && /^\/api\/editor\/documents\/[ab]$/.test(path)) {
      if (path.endsWith('/b') && options.lateDocument) { state.lateDocument = route; return; }
      const id = path.slice(-1);
      return json({ document_id: `frozen-${id}`, source: `${id}.yaml`, yaml_text: sourceYaml, source_hash: `source-${id}`, validation: { ...validation, source_hash: `source-${id}` } });
    }
    if (method === 'POST' && path === '/api/editor/validate') { state.validations.push(payload!); return json(validation); }
    if (method === 'GET' && path === `/api/editor/previews/${validation.canonical_hash}`) return json({ status: 'miss', canonical_hash: validation.canonical_hash, receipt: null });
    if (method === 'POST' && path === '/api/editor/generate') {
      state.generations.push(payload!);
      expect(request.headers()['x-csrf-token']).toBe(state.sessions.at(-1)?.csrf_token);
      if (state.ambiguous) return json({ detail: 'SYNTHETIC unresolved transport outcome' }, 503);
      state.accepted = { id: 'synthetic-generated', kind: 'generate', workspace_id: 'default', status: 'succeeded', stage: 'complete',
        inputs: { ...payload, ...(payload?.document_id ? { input_hash: 'source-a' } : {}) },
        result: { operation: payload?.operation ?? 'refine', yaml_text: candidate, validation, publication: 'not_published', traces: ['SYNTHETIC ONLY'], warnings: ['SYNTHETIC accepted result, not provider evidence'], catalogue_sha256: 'b'.repeat(64),
          prior_snapshot: { status: payload?.operation === 'refine' ? 'not_requested' : 'empty', priors: [], exact_context: 'SYNTHETIC context only', context_sha256: 'c'.repeat(64), warnings: [] } } };
      if (state.delay === 'generation') { state.delayedRoute = route; return; }
      return json(state.accepted);
    }
    if (method === 'GET' && path === '/api/jobs/synthetic-generated' && state.accepted) return json(state.accepted);
    if (method === 'GET' && path === '/api/editor/schema') return json({ schema_sha256: 'd'.repeat(64), schema: { title: hostile, type: 'object' } });
    if (method === 'GET' && path === '/api/editor/catalogues') return json({ catalogues: { assets: { embodiments: [{ name: hostile, tags: ['SYNTHETIC'], summary: 'Literal hostile fixture' }] }, relations: { relations: [] }, tasks: { tasks: [] } } });
    state.unexpected.push(`${method} ${path}`);
    return json({ detail: `Fail-closed synthetic fixture blocks ${method} ${path}` }, 404);
  });
  await page.goto('/workspaces/default');
  await expect(page.locator('.cm-editor')).toBeVisible();
  if (!options.noDocument) await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  return state;
}
async function generate(page: Page, prompt = 'SYNTHETIC prompt') {
  await page.getByLabel('Describe the environment and task').fill(prompt);
  await page.getByRole('button', { name: 'Generate spec', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Apply generated YAML' })).toBeVisible();
}
async function detached(page: Page, state: State) {
  await expect(page.getByLabel('Document', { exact: true })).toHaveValue('local:new-environment');
  await expect(page.locator('.cm-content')).toHaveText(candidate);
  const count = state.validations.length;
  await page.getByRole('button', { name: 'Validate schema', exact: true }).click();
  await expect.poll(() => state.validations.length).toBeGreaterThan(count);
  expect(state.validations.at(-1)).toEqual({ yaml_text: candidate });
}
test.afterEach(async ({ page }, info) => {
  const state = states.get(page);
  if (!state) return;
  await page.screenshot({ path: info.outputPath('synthetic-browser.png'), fullPage: true });
  const evidence = JSON.stringify({ proof: 'Real Chromium/frontend/CodeMirror; ALL API synthetic. No runtime/provider/database proof.', test: info.title, status: info.status, ...state, delayedRoute: !!state.delayedRoute, lateDocument: !!state.lateDocument, browser: { url: page.url(), retained: await retainedRaw(page), yaml: await page.locator('.cm-content').allTextContents() } }, null, 2);
  await writeFile(info.outputPath('synthetic-api-evidence.json'), evidence);
  await info.attach('synthetic-api-evidence', { body: evidence, contentType: 'application/json' });
  if (info.status !== info.expectedStatus) console.log(await page.locator('body').innerText());
  expect(state.unexpected, 'Unknown requests blocked').toEqual([]);
  expect(state.external, 'No external requests').toEqual([]);
  expect(state.errors, 'No uncaught browser errors').toEqual([]);
  expect(state.requests.filter(r => r.method !== 'GET' && !['/api/sessions', '/api/session/activity', '/api/editor/validate', '/api/editor/generate'].includes(r.path))).toEqual([]);
  expect(state.requests.filter(r => /\/graph\/|\/snapshots|\/render|\/evaluat|\/jobs$/.test(r.path))).toEqual([]);
});

for (const delay of ['activity', 'generation'] as const) test(`SYNTHETIC delayed ${delay} S1 response cannot dispatch or adopt after explicit S2 reconnect`, async ({ page }) => {
  const state = await fixture(page);
  state.delay = delay;
  await page.getByLabel('Describe the environment and task').fill('SYNTHETIC frozen S1 prompt');
  await page.getByRole('button', { name: 'Generate spec', exact: true }).click();
  await expect.poll(() => !!state.delayedRoute).toBe(true);
  const frozen = await retainedRaw(page);
  expect(JSON.parse(frozen!).payload).toEqual({ prompt: 'SYNTHETIC frozen S1 prompt', operation: 'new', retrieval_policy: 'allow_fallback', idempotency_key: expect.any(String) });
  expect(JSON.parse(frozen!)).not.toHaveProperty('job');
  expect(state.requests.filter(r => r.path === `/api/${delay === 'activity' ? 'session/activity' : 'editor/generate'}`).at(-1)?.csrf).toBe('synthetic-csrf-S1');
  await reconnectS2(page, state);
  await page.locator('.cm-content').fill('env_name: SYNTHETIC_S2_current_draft');
  const response = page.waitForResponse(r => r.url().endsWith(delay === 'activity' ? '/api/session/activity' : '/api/editor/generate'));
  state.delay = null;
  await state.delayedRoute!.fulfill({ json: delay === 'activity' ? state.sessions[0] : state.accepted });
  await (await response).finished();
  // Mutation settlement is an observable barrier after JSON parsing and ownership checks.
  await expect(page.getByRole('button', { name: 'Retry generation request', exact: true })).toBeEnabled();
  await verifyS2(page, state);
  expect(state.generations).toHaveLength(delay === 'activity' ? 0 : 1);
  expect(await retainedRaw(page)).toBe(frozen);
  await expect(page.getByRole('button', { name: 'Apply generated YAML' })).toHaveCount(0);
  await expect(page.locator('.cm-content')).toHaveText('env_name: SYNTHETIC_S2_current_draft');
  expect(state.requests.filter(r => r.path === '/api/jobs/synthetic-generated')).toEqual([]);
});

for (const otherRetained of [false, true]) test(`SYNTHETIC fresh tab workspace blocker explicit review never authorizes or adopts (other retained=${otherRetained})`, async ({ page }) => {
  const state = await fixture(page, { blocked: true, otherRetained });
  const before = await retainedRaw(page);
  expect(before === null).toBe(!otherRetained);
  const writes = state.requests.filter(r => r.method !== 'GET');
  await expect(page.getByRole('button', { name: 'Reauthorize generation', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Cancel generation', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Review blocked generation synthetic-workspace-blocked', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Reauthorize generation', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Cancel generation', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: otherRetained ? 'Retry generation request' : 'Generate spec', exact: true })).toBeDisabled();
  expect(await retainedRaw(page)).toBe(before);
  expect(state.requests.filter(r => r.method !== 'GET')).toEqual(writes);
  expect(state.generations).toEqual([]);
  expect(state.requests.filter(r => /reauthoriz|\/cancel$/.test(r.path))).toEqual([]);
  expect(await page.evaluate(() => Object.keys(sessionStorage).filter(key => key.startsWith('arena:reauthorization:')))).toEqual([]);
  await expect(page.locator('.cm-content')).toHaveText(sourceYaml);
});

test('SYNTHETIC New without document submits prompt-only bounded payload', async ({ page }) => {
  const state = await fixture(page, { noDocument: true });
  expect(state.generations).toHaveLength(0);
  await generate(page);
  expect(state.generations).toEqual([{ prompt: 'SYNTHETIC prompt', operation: 'new', retrieval_policy: 'allow_fallback', idempotency_key: expect.any(String) }]);
  await expect(page.getByText('No eligible priors', { exact: true })).toBeVisible();
  await expect(page.locator('.cm-content')).not.toHaveText(candidate);
});

test('SYNTHETIC New review leaves real CodeMirror intact then detaches source on apply', async ({ page }) => {
  const state = await fixture(page);
  await generate(page);
  await expect(page.locator('.cm-content')).toHaveText(sourceYaml);
  const editor = page.locator('.cm-content');
  await editor.fill('env_name: SYNTHETIC_user_edit');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: 'Apply generated YAML' }).click();
  await expect(editor).toHaveText('env_name: SYNTHETIC_user_edit');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Apply generated YAML' }).click();
  await detached(page, state);
  expect(state.generations).toHaveLength(1);
});

test('SYNTHETIC require_service New selection survives Refine allow_fallback submission', async ({ page }) => {
  const state = await fixture(page);
  await page.getByLabel('Retrieval policy').selectOption('require_service');
  await page.getByRole('radio', { name: 'Refine current environment' }).check();
  await expect(page.getByLabel('Retrieval policy')).toHaveCount(0);
  await generate(page);
  expect(state.generations).toEqual([{ prompt: 'SYNTHETIC prompt', operation: 'refine', retrieval_policy: 'allow_fallback', base_yaml: sourceYaml, document_id: 'frozen-a', idempotency_key: expect.any(String) }]);
  await page.getByRole('radio', { name: 'New environment from prompt' }).check();
  await expect(page.getByLabel('Retrieval policy')).toHaveValue('require_service');
});

for (const late of [false, true]) test(`SYNTHETIC same-YAML foreign document requires confirm and detach (late=${late})`, async ({ page }) => {
  const state = await fixture(page, { lateDocument: late });
  await page.getByRole('radio', { name: 'Refine current environment' }).check();
  await generate(page);
  await page.getByLabel('Document', { exact: true }).selectOption('b');
  if (late) await expect.poll(() => !!state.lateDocument).toBe(true);
  else await expect(page.locator('.source-path')).toHaveText('b.yaml');
  let confirms = 0;
  page.once('dialog', async dialog => { confirms++; expect(dialog.message()).toContain('frozen inputs changed'); await dialog.dismiss(); });
  await page.getByRole('button', { name: 'Apply generated YAML' }).click();
  expect(confirms).toBe(1);
  await expect(page.locator('.cm-content')).toHaveText(sourceYaml);
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Apply generated YAML' }).click();
  if (late) await state.lateDocument!.fulfill({ json: { document_id: 'frozen-b', source: 'b.yaml', yaml_text: sourceYaml, source_hash: 'source-b', validation } });
  await detached(page, state);
  expect(state.generations).toHaveLength(1);
});

test('SYNTHETIC absent generation_modes preserves legacy controls and payload', async ({ page }) => {
  const state = await fixture(page, { legacy: true });
  await expect(page.getByRole('radio', { name: 'New environment from prompt' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Open schema and registries' })).toHaveCount(0);
  await generate(page);
  expect(state.generations).toEqual([{ prompt: 'SYNTHETIC prompt', base_yaml: sourceYaml, document_id: 'frozen-a', idempotency_key: expect.any(String) }]);
});

test('SYNTHETIC metadata explicit open is GET-only and hostile text stays literal', async ({ page }) => {
  const state = await fixture(page);
  const metadata = () => state.requests.filter(r => /\/editor\/(schema|catalogues)$/.test(r.path));
  expect(metadata()).toEqual([]);
  const writes = state.requests.filter(r => r.method !== 'GET').length;
  await page.getByRole('button', { name: 'Open schema and registries' }).click();
  await expect(page.getByRole('cell', { name: hostile, exact: true })).toBeVisible();
  expect(metadata().map(r => `${r.method} ${r.path}`).sort()).toEqual(['GET /api/editor/catalogues', 'GET /api/editor/schema']);
  expect(state.requests.filter(r => r.method !== 'GET')).toHaveLength(writes);
  expect(state.generations).toHaveLength(0);
  await expect(page.locator('img[src*="generation-fixture.invalid"]')).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as Record<string, unknown>).__generationXSS)).toBeUndefined();
});

test('SYNTHETIC unresolved retry preserves exact payload despite prompt and CodeMirror edits', async ({ page }) => {
  const state = await fixture(page);
  state.ambiguous = true;
  await page.getByLabel('Retrieval policy').selectOption('require_service');
  await page.getByLabel('Describe the environment and task').fill('Frozen synthetic prompt');
  await page.getByRole('button', { name: 'Generate spec', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Retry generation request' })).toBeVisible();
  expect(state.generations).toHaveLength(1);
  await expect(page.getByRole('radio', { name: 'New environment from prompt' })).toBeDisabled();
  await page.getByLabel('Describe the environment and task').fill('Later synthetic prompt');
  await page.locator('.cm-content').fill('env_name: SYNTHETIC_later_edit');
  state.ambiguous = false;
  await page.getByRole('button', { name: 'Retry generation request' }).click();
  await expect(page.getByRole('button', { name: 'Apply generated YAML' })).toBeVisible();
  expect(state.generations).toHaveLength(2);
  expect(state.generations[1]).toEqual(state.generations[0]);
  expect(state.generations[0]).toEqual({ prompt: 'Frozen synthetic prompt', operation: 'new', retrieval_policy: 'require_service', idempotency_key: expect.any(String) });
  await expect(page.locator('.cm-content')).toHaveText('env_name: SYNTHETIC_later_edit');
});
