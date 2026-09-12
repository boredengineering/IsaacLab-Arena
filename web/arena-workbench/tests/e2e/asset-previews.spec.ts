import { expect, test, type Page } from '@playwright/test';

test.skip(process.env.WORKBENCH_E2E_CACHED_SNAPSHOTS !== '1', 'Requires a real completed render for the default document; never renders implicitly');

async function loadedPreviews(page: Page) {
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  const index = await (await page.request.get('/api/editor')).json();
  const doc = await (await page.request.get(`/api/editor/documents/${index.default_document_id}`)).json();
  const workspace = await (await page.request.get('/api/workspaces/default')).json();
  const saved = workspace.jobs.find((job: { kind: string; status: string; inputs: Record<string, unknown> }) =>
    job.kind === 'snapshots' && job.status === 'succeeded' && job.inputs.canonical_hash === doc.validation.canonical_hash);
  expect(saved, 'Seed a real render explicitly before running cache recovery checks').toBeTruthy();
  await expect(page.locator('.asset-grid img')).toHaveCount(saved.result.assets.length);
  for (const image of await page.locator('.asset-grid img').all()) {
    await image.scrollIntoViewIfNeeded();
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true);
  }
  await expect(page.getByText('Matches current draft', { exact: true })).toBeVisible();
  const scene = page.locator('.scene-gallery .snapshot-image img').first();
  await scene.scrollIntoViewIfNeeded();
  await expect.poll(() => scene.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true);
  return doc;
}

test('real saved previews recover after navigation and reload, without GPU submissions', async ({ page }, testInfo) => {
  const submissions: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/api\/editor\/(generate|snapshots|save)$/.test(new URL(request.url()).pathname)) submissions.push(request.url());
  });
  await page.goto('/workspaces/default');
  const doc = await loadedPreviews(page);
  const render = await page.getByRole('button', { name: 'Render snapshots', exact: true }).boundingBox();
  const assets = await page.locator('.asset-grid').boundingBox();
  expect(render!.y).toBeLessThan(assets!.y);
  await expect(page.getByText('Robot preview is included in the scene snapshot.')).toBeVisible();
  await page.getByRole('link', { name: 'Neo4j query', exact: true }).click();
  await page.getByRole('link', { name: 'Environment editor', exact: true }).click();
  await loadedPreviews(page);
  await page.reload();
  await loadedPreviews(page);
  const editor = page.getByRole('textbox', { name: 'YAML editor' });
  await editor.click();
  await page.keyboard.press('ControlOrMeta+a');
  await page.keyboard.insertText(doc.yaml_text.replace(/^env_name:.*$/m, 'env_name: preview_recovery_modified'));
  await expect(page.getByText('Stale · draft changed since this render', { exact: true })).toBeVisible();
  await expect(page.getByText('Matches current draft', { exact: true })).toHaveCount(0);
  await page.getByRole('switch', { name: 'Dark mode' }).click();
  await page.screenshot({ path: testInfo.outputPath('asset-previews-dark.png'), fullPage: true });
  expect(submissions).toEqual([]);
});

test('a failed real artifact can be retried on mobile without rendering', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/workspaces/default');
  await loadedPreviews(page);
  const image = page.locator('.asset-grid img').first();
  const src = await image.getAttribute('src');
  const label = await image.getAttribute('alt');
  let failed = false;
  let renderPosts = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/api/editor/snapshots')) renderPosts++;
  });
  await page.route(`**${src}`, (route) => {
    if (!failed) { failed = true; return route.abort('connectionreset'); }
    return route.continue();
  });
  await page.reload();
  await page.locator('.asset-grid').scrollIntoViewIfNeeded();
  const retry = page.getByRole('button', { name: `Retry ${label}`, exact: true });
  await expect(retry).toBeVisible();
  await retry.click();
  const recovered = page.getByRole('img', { name: label!, exact: true });
  await expect.poll(() => recovered.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true);
  await page.getByRole('button', { name: `Zoom ${label}`, exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('asset-previews-mobile.png'), fullPage: true });
  expect(renderPosts).toBe(0);
});
