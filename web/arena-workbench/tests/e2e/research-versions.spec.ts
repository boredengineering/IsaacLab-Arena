import { expect, test, type Page } from '@playwright/test';
import { writeFile } from 'node:fs/promises';

// Actual Chromium and mounted frontend; ALL API responses synthetic, never persistence proof.
const id = 'a'.repeat(32), attempt = 'b'.repeat(32), res = 'c'.repeat(32), rev = 'd'.repeat(32);
const nextRes = '1'.repeat(32), nextRev = '2'.repeat(32), digest = 'e'.repeat(64);
const key = 'arena:research-version:pending:v1', base = '/api/research/stores/local/versions';
const yaml = 'env_name: SYNTHETIC_Example';
const validation = { valid: true, source_hash: 'source-a', canonical_hash: digest, errors: [], warnings: [], spec: { env_name: 'SYNTHETIC_Example' }, summary: 'SYNTHETIC', graph: { nodes: [], edges: [] }, assets: [], relations: [], reified_relations: [], tasks: [] };
const reference = { job_id: id, attempt_id: attempt, generation: 2, receipt_sha256: digest, request_sha256: digest };
const profilesPath = '/api/research/publication-profiles';
const target = { profile_id: 'synthetic-profile', revision: '9'.repeat(64), scope_ownership: 'cooperative_immutable' };
const profile = { ...target, available: true };
const intent = 'synthetic-intent';
type Body = Record<string, unknown>;
function commit(body: Body, old = false) {
  const reservation = { reservation_id: old ? res : nextRes, revision_id: old ? rev : nextRev, version: old ? 3 : 4, store_id: 'local', family: body.family, workflow_id: body.idempotency_key, source: reference, parent_revision_id: body.parent_revision_id ?? null };
  const bound = { ...reservation, ...(body.publication_target ? { publication_request: { effect_id: intent, target_profile: body.publication_target } } : {}) };
  return { reservation: bound, manifest: { digest, binding: bound, note: '<script>hostile</script>', download_url: 'https://research-fixture.invalid/leak' }, relative_directory: `final/${body.family}/v${reservation.version}`, publication_intent_id: body.publication_target ? intent : null, download_url: 'javascript:alert(1)' };
}
const oldCommit = commit({ family: 'SYNTHETIC_Example', idempotency_key: 'old' }, true);
function row(c: ReturnType<typeof commit>) { return { ...c.reservation, state: 'COMMITTED', source_job_id: id, manifest_digest: c.manifest.digest }; }
type State = { requests: { method: string; path: string; query: string; raw: string | null; csrf?: string }[]; sessions: Body[]; posts: string[]; unexpected: string[]; external: string[]; errors: string[]; sockets: string[]; mode: 'ok' | 'lost' | 'mismatch' | 'intent-mismatch' | 'target-mismatch'; profiles: typeof profile[]; saved: ReturnType<typeof commit> | null; readbacks: number; dialogs: string[]; downloads: number };
const states = new WeakMap<Page, State>();
const pending = (page: Page) => page.evaluate(k => sessionStorage.getItem(k), key);
test.use({ serviceWorkers: 'block' });
test.setTimeout(35_000);
async function fixture(page: Page) {
  const s: State = { requests: [], sessions: [], posts: [], unexpected: [], external: [], errors: [], sockets: [], mode: 'ok', profiles: [{ ...profile }], saved: null, readbacks: 0, dialogs: [], downloads: 0 };
  states.set(page, s);
  page.on('pageerror', e => s.errors.push(e.stack ?? e.message));
  await page.addInitScript(() => Object.defineProperty(window, 'SharedWorker', { value: undefined }));
  const origin = new URL(process.env.WORKBENCH_BASE_URL ?? 'http://127.0.0.1:3001').origin;
  await page.routeWebSocket('**/*', socket => { const u = new URL(socket.url()); s.sockets.push(socket.url()); if (![new URL(origin).host, '127.0.0.1:5173'].includes(u.host)) s.external.push(socket.url()); socket.close(); });
  await page.context().route('**/*', async route => {
    const req = route.request(), u = new URL(req.url()), path = u.pathname, method = req.method();
    if (u.origin !== origin) { s.external.push(u.href); return route.abort('blockedbyclient'); }
    if (!path.startsWith('/api/')) {
      if (method === 'GET' && (/^\/(?:src\/|node_modules\/|@vite\/|@react-refresh$|@fs\/|assets\/)/.test(path) || ['/', '/workspaces/default', '/vite.svg', '/favicon.ico'].includes(path))) return route.continue();
      s.unexpected.push(`${method} ${path}`); return route.abort('blockedbyclient');
    }
    s.requests.push({ method, path, query: u.search, raw: req.postData(), csrf: req.headers()['x-csrf-token'] });
    const json = (value: unknown, status = 200) => route.fulfill({ json: value, status });
    if (s.requests.length > 150) { s.unexpected.push('API budget'); return route.abort('blockedbyclient'); }
    if (method === 'GET' && path === '/api/health') return json({ capabilities: { diagnostic: false } });
    if (method === 'POST' && path === '/api/sessions') { const session = { session_id: `synthetic-S${s.sessions.length + 1}`, csrf_token: `synthetic-csrf-S${s.sessions.length + 1}`, expires_at: 9999999999 }; s.sessions.push(session); return json(session); }
    if (method === 'POST' && path === '/api/session/activity') return json(s.sessions.at(-1));
    if (method === 'GET' && path === '/api/model-settings') return json({ configured: true, source: 'server', provider: 'openai', model: 'SYNTHETIC-no-contact', credential_ref: null, expires_at: null, session_keys_allowed: false, providers: [
      { id: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com/v1' }, { id: 'gemini', label: 'Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/' }, { id: 'openrouter', label: 'OpenRouter', base_url: 'https://openrouter.ai/api/v1' }, { id: 'nvidia', label: 'NVIDIA', base_url: 'https://integrate.api.nvidia.com/v1' },
    ] });
    if (method === 'GET' && path === '/api/workspaces/default') return json({ id: 'default', name: 'SYNTHETIC research acceptance', event_cursor: 0, jobs: [] });
    if (method === 'GET' && path === '/api/editor') return json({ default_document_id: 'a', documents: [{ id: 'a', name: 'Synthetic a', source: 'a.yaml' }], capabilities: { generation: true, generation_modes: true, research_versions: true, snapshots: false, neo4j: false }, limitations: ['ALL API SYNTHETIC'] });
    if (method === 'GET' && path === '/api/editor/documents/a') return json({ document_id: 'frozen-a', source: 'a.yaml', yaml_text: yaml, source_hash: 'source-a', validation });
    if (method === 'POST' && path === '/api/editor/validate') return json(validation);
    if (method === 'GET' && path === `/api/editor/previews/${digest}`) return json({ status: 'miss', canonical_hash: digest, receipt: null });
    const job = { id, kind: 'generate', workspace_id: 'default', status: 'succeeded', stage: 'complete', created_at: 1, updated_at: 1, created_by_session_id: 'synthetic-S1', error: null, execution: { released: true, candidate_accepted: true, outcome: 'candidate_accepted' }, inputs: { prompt: 'SYNTHETIC candidate selection', operation: 'new', retrieval_policy: 'allow_fallback', ...(method === 'POST' ? req.postDataJSON() : {}) }, result: { operation: 'new', yaml_text: yaml, validation, publication: 'not_published', traces: [], warnings: ['Synthetic candidate, no model call'], catalogue_sha256: digest, prior_snapshot: { status: 'empty', priors: [], exact_context: '', context_sha256: digest, warnings: [] } } };
    if (method === 'POST' && path === '/api/editor/generate') return json(job);
    if (method === 'GET' && path === `/api/jobs/${id}`) return json(job);
    if (method === 'GET' && path === '/api/research/stores') return json({ stores: [{ store_id: 'local', available: true, message: 'SYNTHETIC' }] });
    if (method === 'GET' && path === profilesPath) return json({ profiles: s.profiles });
    if (method === 'GET' && path === `/api/research/stores/local/candidates/${id}`) return json({ ...reference, ignored_field: 'NOT-RETAINED' });
    if (method === 'GET' && path === base) return json({ versions: [row(oldCommit), ...(s.saved && s.mode !== 'mismatch' ? [row(s.saved)] : [])], latest_version: s.saved && s.mode !== 'mismatch' ? 4 : 3, next_after_version: null });
    if (method === 'GET' && path === `${base}/${res}`) return json(oldCommit);
    if (method === 'POST' && path === base) {
      expect(req.headers()['x-csrf-token']).toBe(s.sessions.at(-1)?.csrf_token);
      s.posts.push(req.postData()!); s.saved = commit(req.postDataJSON());
      if (s.mode === 'lost') return route.abort('failed');
      return json(s.saved, 201);
    }
    if (method === 'GET' && path === `${base}/${nextRes}` && s.saved) {
      s.readbacks++;
      const readback = structuredClone(s.saved);
      if (s.mode === 'mismatch') readback.manifest.digest = 'f'.repeat(64);
      if (s.mode === 'intent-mismatch') {
        readback.publication_intent_id = 'different-intent';
        readback.reservation.publication_request!.effect_id = 'different-intent';
        readback.manifest.binding.publication_request!.effect_id = 'different-intent';
      }
      if (s.mode === 'target-mismatch') {
        const changed = { ...target, revision: '8'.repeat(64) };
        readback.reservation.publication_request!.target_profile = changed;
        readback.manifest.binding.publication_request!.target_profile = changed;
      }
      return json(readback);
    }
    if (method === 'GET' && path === `${base}/${res}/artifacts/environment.yaml`) { s.downloads++; return route.fulfill({ body: yaml, contentType: 'application/octet-stream', headers: { 'Content-Disposition': 'attachment; filename="environment.yaml"', 'X-Content-Type-Options': 'nosniff' } }); }
    s.unexpected.push(`${method} ${path}`); return json({ detail: 'Fail-closed synthetic API' }, 404);
  });
  await page.goto('/workspaces/default');
  await expect(page.locator('.cm-editor')).toBeVisible();
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  return s;
}
async function choose(page: Page) {
  await page.getByLabel('Describe the environment and task').fill('SYNTHETIC candidate selection');
  await page.getByRole('button', { name: 'Generate spec', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Apply generated YAML' })).toBeVisible();
  await page.getByRole('button', { name: 'Open research versions', exact: true }).click();
  await page.getByLabel('Research store').selectOption('local');
  await expect(page.getByRole('button', { name: 'Save research version', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Select version 3', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Download verified source' })).toBeVisible();
  await page.getByLabel('Parent revision').selectOption(rev);
}
async function confirmClick(page: Page, s: State, button: string, accept = true) {
  page.once('dialog', async dialog => { s.dialogs.push(dialog.message()); if (accept) await dialog.accept(); else await dialog.dismiss(); });
  await page.getByRole('button', { name: button, exact: true }).click();
}
async function reconnect(page: Page, s: State) {
  await page.getByRole('button', { name: 'Reconnect session', exact: true }).click();
  await expect.poll(() => s.sessions.length).toBe(2);
  await expect(page.getByRole('button', { name: 'Open research versions', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Open research versions', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Recover exact research save in this session', exact: true })).toBeVisible();
}
test.afterEach(async ({ page, browser }, info) => {
  const s = states.get(page); if (!s) return;
  await page.screenshot({ path: info.outputPath('chromium.png'), fullPage: true });
  const evidence = { proof: 'Actual Chromium, ALL API synthetic; no live persistence/provider/graph/simulator proof', title: info.title, status: info.status, browser: browser.version(), uid: process.getuid?.(), ...s, retained: await pending(page), counters: { api: s.requests.length, researchGets: s.requests.filter(r => r.method === 'GET' && r.path.startsWith('/api/research/')).length, savePosts: s.posts.length, readbacks: s.readbacks, downloads: s.downloads, unexpected: s.unexpected.length, external: s.external.length, blockedSockets: s.sockets.length } };
  await writeFile(info.outputPath('counters.json'), JSON.stringify(evidence, null, 2));
  if (info.status !== info.expectedStatus) await writeFile(info.outputPath('failure-dom.txt'), await page.locator('body').innerText());
  expect(s.unexpected).toEqual([]); expect(s.external).toEqual([]); expect(s.errors).toEqual([]);
  expect(s.requests.filter(r => /\/stream|\/graph|\/snapshots|\/render|\/evaluat|\/publish|\/simulate|\/grants?|\/providers?|\/models(?:\/|$)|\/publication(?:\/|$)/.test(r.path))).toEqual([]);
  expect(s.requests.filter(r => r.method !== 'GET' && !['/api/sessions', '/api/session/activity', '/api/editor/validate', '/api/editor/generate', base].includes(r.path))).toEqual([]);
  expect(process.getuid?.()).not.toBe(0);
});
test('closed panel makes no research GETs', async ({ page }) => {
  const s = await fixture(page);
  await page.getByRole('button', { name: 'Validate schema', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open research versions', exact: true })).toHaveAttribute('aria-expanded', 'false');
  expect(s.requests.filter(r => r.path.startsWith('/api/research/'))).toEqual([]);
  expect(s.posts).toEqual([]);
});
test('explicit candidate freezes family parent and verifies readback; safe download ignores hostile URLs', async ({ page }, info) => {
  const s = await fixture(page); await choose(page);
  const link = page.getByRole('link', { name: 'Download verified source' });
  expect(await link.getAttribute('href')).toBe(`${base}/${res}/artifacts/environment.yaml`);
  expect(await link.getAttribute('download')).toBe('environment.yaml');
  // Chromium's native download path cancels before synthetic routing (runs 1/2 preserved).
  // Verify the exact rendered URL and its browser-fetched synthetic attachment, not native download completion.
  const attachment = await link.evaluate(async anchor => {
    const response = await fetch((anchor as HTMLAnchorElement).href);
    return { url: response.url, status: response.status, disposition: response.headers.get('content-disposition'), type: response.headers.get('content-type'), body: await response.text() };
  });
  expect(attachment).toEqual({ url: `${new URL(page.url()).origin}${base}/${res}/artifacts/environment.yaml`, status: 200, disposition: 'attachment; filename="environment.yaml"', type: 'application/octet-stream', body: yaml });
  await writeFile(info.outputPath('synthetic-attachment.json'), JSON.stringify(attachment, null, 2));
  expect(s.downloads).toBe(1);
  await confirmClick(page, s, 'Save research version');
  await expect(page.getByText('Research version saved and verified. Graph publication was not performed.', { exact: true })).toBeVisible();
  await expect(page.getByText('Latest committed version: 4', { exact: true })).toBeVisible();
  expect(s.posts).toHaveLength(1); expect(JSON.parse(s.posts[0])).toEqual({ idempotency_key: expect.any(String), family: 'SYNTHETIC_Example', source_job_id: id, source_attempt_id: attempt, source_generation: 2, parent_revision_id: rev });
  expect(s.readbacks).toBe(1); expect(await pending(page)).toBeNull();
  await expect(page.locator('.cm-content')).toHaveText(yaml);
});
test('lost POST acknowledgement requires S2 recovery and separate retry confirmations with identical body and key', async ({ page }) => {
  const s = await fixture(page); await choose(page); s.mode = 'lost';
  await confirmClick(page, s, 'Save research version'); await expect(page.getByText(/Save unresolved\./)).toBeVisible();
  const raw = await pending(page), frozen = JSON.parse(raw!);
  expect(frozen.source).toEqual(reference); expect(s.posts).toHaveLength(1); expect(s.readbacks).toBe(0);
  await reconnect(page, s); expect(await pending(page)).toBe(raw); expect(s.posts).toHaveLength(1);
  await expect(page.getByRole('button', { name: 'Retry exact research save', exact: true })).toBeDisabled();
  await confirmClick(page, s, 'Recover exact research save in this session');
  expect(s.dialogs.at(-1)).toContain('single_operator_workspace');
  expect(JSON.parse((await pending(page))!)).toEqual({ ...frozen, session: 'synthetic-S2' }); expect(s.posts).toHaveLength(1);
  await expect(page.getByLabel('Research family')).toHaveValue('SYNTHETIC_Example'); await expect(page.getByLabel('Research family')).toBeDisabled(); await expect(page.getByLabel('Parent revision')).toHaveValue(rev);
  s.mode = 'ok'; await confirmClick(page, s, 'Retry exact research save');
  await expect(page.getByText('Research version saved and verified. Graph publication was not performed.', { exact: true })).toBeVisible();
  await expect(page.getByText('Latest committed version: 4', { exact: true })).toBeVisible();
  expect(s.posts).toEqual([JSON.stringify(frozen.body), JSON.stringify(frozen.body)]); expect(s.dialogs).toHaveLength(3); expect(s.readbacks).toBe(1); expect(await pending(page)).toBeNull();
});
test('mismatched readback never reports success or refreshes listing', async ({ page }) => {
  const s = await fixture(page); await choose(page); s.mode = 'mismatch';
  const lists = s.requests.filter(r => r.method === 'GET' && r.path === base).length;
  await confirmClick(page, s, 'Save research version'); await expect(page.getByText(/Save unresolved\./)).toBeVisible();
  expect(s.readbacks).toBe(1); expect(await pending(page)).not.toBeNull();
  await expect(page.getByText(/Research version saved and verified/)).toHaveCount(0);
  await expect(page.getByText('Latest committed version: 3', { exact: true })).toBeVisible();
  expect(s.requests.filter(r => r.method === 'GET' && r.path === base)).toHaveLength(lists);
});
const profileGets = (s: State) => s.requests.filter(r => r.path === profilesPath);
const preparedMessage = 'Research version saved and verified. Profile synthetic-profile: prepared, not published. Graph publication was not performed.';
async function optIn(page: Page, s: State) {
  await expect(page.getByLabel('Prepare publication on save')).not.toBeChecked();
  expect(profileGets(s)).toHaveLength(0);
  await page.getByLabel('Prepare publication on save').check();
  await expect(page.getByRole('button', { name: 'Save research version', exact: true })).toBeDisabled();
  await page.getByRole('combobox', { name: /^Publication profile/ }).selectOption(target.profile_id);
  await expect(page.getByRole('button', { name: 'Save research version', exact: true })).toBeEnabled();
  expect(profileGets(s)).toHaveLength(1);
  expect(Object.keys(s.profiles[0]).sort()).toEqual(['available', 'profile_id', 'revision', 'scope_ownership']);
}
function frozenDialog(message: string) {
  for (const text of ['local/SYNTHETIC_Example', rev, target.profile_id, target.revision, target.scope_ownership, 'not published']) expect(message).toContain(text);
}
test('preparation is default off even with panel candidate and parent selected', async ({ page }) => {
  const s = await fixture(page); await choose(page);
  await expect(page.getByLabel('Prepare publication on save')).not.toBeChecked();
  await expect(page.getByRole('combobox', { name: /^Publication profile/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'Validate schema', exact: true }).click();
  expect(profileGets(s)).toHaveLength(0); expect(s.posts).toHaveLength(0);
});
test('four-field opt-in catalogue freezes three-field target and explicit confirmation; POST plus GET is prepared not published', async ({ page }, info) => {
  const s = await fixture(page); await choose(page); await optIn(page, s);
  await confirmClick(page, s, 'Save research version', false);
  frozenDialog(s.dialogs.at(-1)!); expect(s.posts).toHaveLength(0); expect(await pending(page)).toBeNull();
  await confirmClick(page, s, 'Save research version');
  frozenDialog(s.dialogs.at(-1)!);
  await expect(page.getByText(preparedMessage, { exact: true })).toBeVisible();
  expect(s.posts).toHaveLength(1); expect(s.readbacks).toBe(1); expect(await pending(page)).toBeNull();
  const body = JSON.parse(s.posts[0]);
  expect(body).toEqual({ idempotency_key: expect.any(String), family: 'SYNTHETIC_Example', source_job_id: id, source_attempt_id: attempt, source_generation: 2, parent_revision_id: rev, publication_target: target });
  expect(Object.keys(body.publication_target).sort()).toEqual(['profile_id', 'revision', 'scope_ownership']);
  expect(s.saved?.publication_intent_id).toBe(intent);
  expect(s.saved?.reservation.publication_request).toEqual({ effect_id: intent, target_profile: target });
  expect(s.saved?.manifest.binding).toEqual(s.saved?.reservation);
  await page.getByRole('button', { name: 'Select version 4', exact: true }).click();
  await expect(page.getByText(/Prepared version, not published by this UI/)).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download verified source' })).toHaveAttribute('href', `${base}/${nextRes}/artifacts/environment.yaml`);
  await writeFile(info.outputPath('prepared-contract.json'), JSON.stringify({ catalogue: profile, body, commit: s.saved }, null, 2));
});
for (const change of ['changed', 'removed'] as const) test(`lost prepared save acknowledgement with profile ${change}: S2 explicit recovery replays byte-identical target body key without catalogue GET`, async ({ page }, info) => {
  const s = await fixture(page); await choose(page); await optIn(page, s); s.mode = 'lost';
  await confirmClick(page, s, 'Save research version');
  await expect(page.getByText(/Save unresolved\./)).toBeVisible();
  frozenDialog(s.dialogs.at(-1)!);
  const raw = (await pending(page))!, frozen = JSON.parse(raw), original = s.posts[0];
  expect(frozen.body.publication_target).toEqual(target); expect(original).toBe(JSON.stringify(frozen.body));
  await expect(page.getByLabel('Research family')).toBeDisabled();
  await expect(page.getByLabel('Parent revision')).toBeDisabled();
  await expect(page.getByRole('combobox', { name: /^Publication profile/ })).toBeDisabled();
  await page.screenshot({ path: info.outputPath('S1-unresolved.png'), fullPage: true });
  s.profiles = change === 'removed' ? [] : [{ ...profile, revision: '8'.repeat(64) }];
  const getsBefore = profileGets(s).length;
  await reconnect(page, s);
  expect(await pending(page)).toBe(raw); expect(s.posts).toHaveLength(1);
  await expect(page.getByRole('button', { name: 'Retry exact research save', exact: true })).toBeDisabled();
  await confirmClick(page, s, 'Recover exact research save in this session', false);
  frozenDialog(s.dialogs.at(-1)!); expect(await pending(page)).toBe(raw); expect(s.posts).toHaveLength(1);
  await confirmClick(page, s, 'Recover exact research save in this session');
  frozenDialog(s.dialogs.at(-1)!); expect(s.dialogs.at(-1)).toContain('single_operator_workspace');
  expect(JSON.parse((await pending(page))!)).toEqual({ ...frozen, session: 'synthetic-S2' });
  await expect(page.getByLabel('Research family')).toHaveValue(frozen.body.family);
  await expect(page.getByLabel('Parent revision')).toHaveValue(rev);
  await expect(page.getByText(/Retained publication target:/)).toContainText(target.revision);
  await page.screenshot({ path: info.outputPath('S2-recovered-not-retried.png'), fullPage: true });
  expect(s.posts).toHaveLength(1); expect(s.readbacks).toBe(0);
  await confirmClick(page, s, 'Retry exact research save', false); expect(s.posts).toHaveLength(1);
  s.mode = 'ok'; await confirmClick(page, s, 'Retry exact research save');
  for (const text of [target.profile_id, target.revision, target.scope_ownership, 'not published']) expect(s.dialogs.at(-1)).toContain(text);
  await expect(page.getByText(preparedMessage, { exact: true })).toBeVisible();
  expect(s.posts).toEqual([original, original]); expect(s.readbacks).toBe(1); expect(await pending(page)).toBeNull();
  expect(profileGets(s)).toHaveLength(getsBefore);
  expect(s.requests.filter(r => r.method === 'POST' && r.path === base).map(r => r.csrf)).toEqual(['synthetic-csrf-S1', 'synthetic-csrf-S2']);
  await writeFile(info.outputPath('exact-replay.json'), JSON.stringify({ change, replacementCatalogue: s.profiles, frozen, bodies: s.posts, profileGetsBefore: getsBefore, profileGetsAfter: profileGets(s).length }, null, 2));
});
for (const mismatch of ['intent-mismatch', 'target-mismatch'] as const) test(`prepared ${mismatch} readback retains unresolved exact request and never refreshes listing`, async ({ page }, info) => {
  const s = await fixture(page); await choose(page); await optIn(page, s); s.mode = mismatch;
  const lists = s.requests.filter(r => r.method === 'GET' && r.path === base).length;
  await confirmClick(page, s, 'Save research version');
  await expect(page.getByText(/Save unresolved\./)).toBeVisible();
  expect(s.posts).toHaveLength(1); expect(s.readbacks).toBe(1);
  const retained = (await pending(page))!;
  expect(JSON.stringify(JSON.parse(retained).body)).toBe(s.posts[0]);
  await expect(page.getByText(/Research version saved and verified/)).toHaveCount(0);
  await expect(page.getByText('Latest committed version: 3', { exact: true })).toBeVisible();
  expect(s.requests.filter(r => r.method === 'GET' && r.path === base)).toHaveLength(lists);
  await page.screenshot({ path: info.outputPath('mismatch-unresolved.png'), fullPage: true });
  await page.getByRole('button', { name: 'Close research versions', exact: true }).click();
  await page.getByRole('button', { name: 'Open research versions', exact: true }).click();
  expect(await pending(page)).toBe(retained); expect(s.posts).toHaveLength(1);
  await expect(page.getByRole('button', { name: 'Retry exact research save', exact: true })).toBeEnabled();
});
test('declined new-session recovery and declined retry send no POST', async ({ page }) => {
  const s = await fixture(page); await choose(page); s.mode = 'lost';
  await confirmClick(page, s, 'Save research version'); await expect(page.getByText(/Save unresolved\./)).toBeVisible();
  const raw = await pending(page); await reconnect(page, s);
  await confirmClick(page, s, 'Recover exact research save in this session', false);
  expect(await pending(page)).toBe(raw); expect(s.posts).toHaveLength(1);
  await expect(page.getByRole('button', { name: 'Retry exact research save', exact: true })).toBeDisabled();
  await confirmClick(page, s, 'Recover exact research save in this session');
  await confirmClick(page, s, 'Retry exact research save', false);
  expect(s.posts).toHaveLength(1); expect(s.readbacks).toBe(0);
  await expect(page.getByText(/Research version saved and verified/)).toHaveCount(0);
});
