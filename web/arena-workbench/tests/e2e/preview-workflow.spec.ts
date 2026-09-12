import { expect, test, type Page } from '@playwright/test';

// Deliberate protocol fixtures, not simulator evidence. Every API request is intercepted.
const hash = 'a'.repeat(64);
const yaml = 'env_name: browser_protocol_fixture';
const validation = { valid: true, source_hash: 'source', canonical_hash: hash, errors: [], warnings: [], spec: {},
  summary: 'Protocol fixture', graph: { nodes: [], edges: [] },
  assets: [{ id: 'cube', role: 'object', properties: {} }], relations: [], reified_relations: [], tasks: [] };
const artifact = (id: string) => ({ artifact_id: id, url: `/api/editor/artifacts/${id}` });
const image = { ...artifact('full-fixture'), dimensions_m: [1.123456789, 2, 3], variants: {
  thumbnail: { ...artifact('thumb-fixture'), width: 256, height: 256 }, full: { ...artifact('full-fixture'), width: 1024, height: 1024 },
} };
const receipt = { canonical_hash: hash, cache_key: 'fixture-cache', input_hash: 'source', renderer_version: 'fixture-only',
  // Property order must not affect identity.
  options: { asset_views: {}, resolution: 1024, view: 'isometric' }, assets: [{ id: 'cube', ...image }], scene: image,
  warnings: [], partial: true, errors: [{ id: 'other', stage: 'framing', code: 'empty_bounds', message: 'Fixture failure' }], timings: { render_seconds: 1.234567 } };

test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status !== testInfo.expectedStatus) console.log(await page.locator('body').innerText());
});

async function mockApi(page: Page) {
  // SharedWorker fetches bypass page.route; use the existing polling fallback so
  // protocol fixtures cannot accidentally contact the live authenticated stream.
  await page.addInitScript(() => Object.defineProperty(window, 'SharedWorker', { value: undefined }));
  const state = { hit: true, ambiguous: false, cancelled: false, posts: [] as Record<string, unknown>[], images: [] as string[], lookups: [] as string[] };
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (value: unknown, status = 200) => route.fulfill({ status, json: value });
    if (path === '/api/health') return json({ capabilities: { diagnostic: false } });
    if (path === '/api/sessions' || path === '/api/session/activity') return json({ session_id: 'fixture-session', csrf_token: 'fixture-csrf', expires_at: 9999999999 });
    if (path === '/api/workspaces/default') return json({ id: 'default', name: 'Protocol fixture', event_cursor: 0, jobs: [{
      id: 'journal-fixture', kind: 'snapshots', workspace_id: 'default', status: 'succeeded', stage: 'complete', inputs: { canonical_hash: hash, document_id: 'frozen-fixture' }, result: receipt,
    }] });
    if (path === '/api/editor') return json({ default_document_id: 'fixture', documents: [{ id: 'fixture', name: 'Fixture', source: 'fixture.yaml' }], capabilities: { snapshots: true, generation: false, neo4j: false }, limitations: [] });
    if (path === '/api/editor/documents/fixture') return json({ document_id: 'frozen-fixture', source: 'fixture.yaml', yaml_text: yaml, source_hash: 'source', validation });
    if (path === '/api/editor/validate') return json(validation);
    if (path.startsWith('/api/editor/previews/')) {
      state.lookups.push(request.url());
      const hit = state.hit && url.searchParams.get('view') === 'isometric';
      return json({ status: hit ? 'hit' : 'miss', canonical_hash: hash, receipt: hit ? receipt : null });
    }
    if (path.startsWith('/api/editor/artifacts/')) {
      state.images.push(path);
      return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#888"/><text x="30" y="128" fill="white">TEST FIXTURE</text></svg>' });
    }
    const job = { id: 'mock-job', kind: 'snapshots', workspace_id: 'default', status: state.cancelled ? 'cancel_requested' : 'queued', stage: 'protocol fixture', inputs: state.posts[0] ?? {} };
    if (path === '/api/editor/snapshots') {
      state.posts.push(request.postDataJSON());
      expect(request.headers()['x-csrf-token']).toBe('fixture-csrf');
      return state.ambiguous ? route.abort('connectionreset') : json(job);
    }
    if (path === '/api/jobs/mock-job/cancel') { state.cancelled = true; return json({ ...job, status: 'cancel_requested' }); }
    if (path === '/api/jobs/mock-job') return json(job);
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
    return json({ detail: `Protocol fixture does not implement ${path}` }, 404);
  });
  return state;
}

test('mock catalogue variants, invalidation, inspection and mobile dark layout never submit jobs', async ({ page }, testInfo) => {
  const state = await mockApi(page);
  await page.goto('/workspaces/default');
  const image = page.getByRole('img', { name: 'cube snapshot', exact: true });
  await expect(image).toHaveAttribute('src', '/api/editor/artifacts/thumb-fixture');
  await image.scrollIntoViewIfNeeded();
  await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
  expect(state.images).not.toContain('/api/editor/artifacts/full-fixture');
  await expect(page.getByText('Partial preview · some artifacts failed')).toBeVisible();
  await page.getByText('Renderer timings', { exact: true }).click();
  await expect(page.getByText('render_seconds: 1.235', { exact: true })).toBeVisible();
  await expect(page.getByText('Dimensions (m): 1.123 × 2 × 3')).toHaveAttribute('title', '1.123456789 × 2 × 3');
  await page.getByRole('button', { name: 'Zoom cube snapshot', exact: true }).click();
  await expect(page.getByRole('img', { name: 'Zoomed cube snapshot' })).toHaveAttribute('src', '/api/editor/artifacts/full-fixture');
  await page.getByRole('button', { name: 'Close image' }).click();
  await page.getByLabel('Preview mode', { exact: true }).selectOption('scene');
  await expect(page.getByText('Matches current draft', { exact: true })).toBeVisible();
  await page.getByLabel('Preview mode', { exact: true }).selectOption('assets');
  await page.getByLabel('Scene camera', { exact: true }).selectOption('top');
  await expect(page.locator('.asset-grid img')).toHaveCount(0);
  await page.getByLabel('Scene camera', { exact: true }).selectOption('isometric');
  await expect(image).toBeVisible();
  state.hit = false;
  await page.getByRole('button', { name: 'Refresh saved previews' }).click();
  await expect(page.getByText('No saved previews for these camera options.')).toBeVisible();
  await expect(page.locator('.asset-grid img')).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' })).not.toBeChecked();
  await expect(page.locator('.asset-grid img')).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('switch', { name: 'Dark mode' }).click();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('mock-preview-mobile-dark.png'), fullPage: true });
  expect(state.posts).toEqual([]);
});

test('mock automatic mode requires consent, freezes options and exposes cancel/readback', async ({ page }) => {
  const state = await mockApi(page); state.hit = false;
  await page.goto('/workspaces/default');
  const toggle = page.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' });
  await expect(toggle).not.toBeChecked();
  await page.getByLabel('Scene camera', { exact: true }).selectOption('front');
  await page.waitForTimeout(1800);
  expect(state.posts).toHaveLength(0);
  await toggle.check();
  await page.getByLabel('Scene camera', { exact: true }).selectOption('top');
  await page.getByLabel('Image resolution', { exact: true }).selectOption('512');
  await page.getByLabel('Camera for cube', { exact: true }).selectOption('side');
  await expect.poll(() => state.posts.length).toBe(1);
  expect(state.posts[0]).toMatchObject({ yaml_text: yaml, document_id: 'frozen-fixture', options: { view: 'top', resolution: 512, asset_views: { cube: 'side' } } });
  await page.getByLabel('Scene camera', { exact: true }).selectOption('front');
  await page.waitForTimeout(1800);
  expect(state.posts).toHaveLength(1);
  await page.getByRole('button', { name: 'Cancel snapshot render', exact: true }).click();
  await expect(page.getByText('Cancellation requested; waiting for worker acknowledgment.')).toBeVisible();
  expect(state.cancelled).toBe(true);
});

test('mock ambiguous automatic submission is never replayed by editing or reload', async ({ page }) => {
  const state = await mockApi(page); state.hit = false; state.ambiguous = true;
  await page.goto('/workspaces/default');
  await page.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' }).check();
  await page.getByLabel('Scene camera', { exact: true }).selectOption('top');
  await expect.poll(() => state.posts.length).toBe(1);
  await expect(page.getByText('Automatic previews paused.', { exact: false })).toBeVisible();
  await page.getByLabel('Scene camera', { exact: true }).selectOption('front');
  await page.waitForTimeout(1800);
  expect(state.posts).toHaveLength(1);
  await page.reload();
  await expect(page.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' })).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' })).toBeDisabled();
  expect(state.posts).toHaveLength(1);
  await page.getByRole('button', { name: 'Retry snapshot request', exact: true }).click();
  await expect.poll(() => state.posts.length).toBe(2);
  expect(state.posts[1]).toEqual(state.posts[0]);
});
