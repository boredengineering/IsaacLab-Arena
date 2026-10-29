import { expect, test, type Page } from '@playwright/test';
// These tests use the real API. They never fabricate documents, query results or pixels.
async function openEditor(page: Page) {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'ArenaEnvGraphSpec live editor' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'End session' })).toBeVisible();
  const indexResponse = await page.request.get('/api/editor');
  expect(
    indexResponse.ok(),
    'Editor API must be installed; do not silently pass an unavailable stack',
  ).toBe(true);
  const index = await indexResponse.json();
  await expect(page.getByRole('combobox', { name: 'Document', exact: true })).toHaveValue(
    index.default_document_id,
  );
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  return index;
}
async function replaceYaml(page: Page, text: string) {
  const editor = page.getByRole('textbox', { name: 'YAML editor' });
  await editor.click();
  await page.keyboard.press('ControlOrMeta+a');
  await page.keyboard.insertText(text);
}
test('unsaved YAML recovers after reload without restarting a job', async ({ page }) => {
  const index = await openEditor(page);
  const doc = await (await page.request.get(`/api/editor/documents/${index.default_document_id}`)).json();
  let submissions = 0;
  page.on('request', request => {
    if (/\/api\/editor\/(generate|snapshots|save)$/.test(new URL(request.url()).pathname) && request.method() === 'POST') submissions++;
  });
  await replaceYaml(page, doc.yaml_text + '\n# browser recovery check\n');
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Restore draft', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Restore draft', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'YAML editor' })).toContainText('browser recovery check');
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  expect(submissions).toBe(0);
});

test('real document, live schema diagnostics, explicit reifiers and read-only load', async ({
  page,
}, testInfo) => {
  const jobs: string[] = [];
  page.on('request', (r) => {
    if (
      /\/api\/editor\/(generate|snapshots)$/.test(new URL(r.url()).pathname) &&
      r.method() === 'POST'
    )
      jobs.push(r.url());
  });
  const index = await openEditor(page);
  const doc = await (
    await page.request.get(`/api/editor/documents/${encodeURIComponent(index.default_document_id)}`)
  ).json();
  await expect(page.getByRole('textbox', { name: 'YAML editor' })).toContainText('env_name');
  await expect(page.getByLabel('Authored spatial graph', { exact: true })).toBeVisible();
  for (const node of doc.validation.graph.nodes)
    await expect(
      page.getByRole('button', { name: `Inspect ${node.label}`, exact: true }),
    ).toHaveCount(1);
  if (doc.validation.graph.nodes.length) {
    await page
      .getByRole('button', { name: `Inspect ${doc.validation.graph.nodes[0].label}`, exact: true })
      .click();
    await expect(page.getByRole('heading', { name: 'Node inspector' })).toBeVisible();
  }
  await replaceYaml(page, 'env_name: [invalid');
  await expect(page.getByText('Schema errors', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save revision' })).toBeDisabled();
  await expect(page.getByLabel('Authored spatial graph', { exact: true })).toHaveCount(0);
  await replaceYaml(page, doc.yaml_text);
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
  expect(jobs).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('editor-real-document.png'), fullPage: true });
});
test('immutable save exports server YAML without changing the source document', async ({
  page,
}) => {
  const index = await openEditor(page);
  const path = `/api/editor/documents/${encodeURIComponent(index.default_document_id)}`;
  const before = await (await page.request.get(path)).json();
  const saved = page.waitForResponse(
    (r) => new URL(r.url()).pathname === '/api/editor/save' && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Save revision' }).click();
  const saveResponse = await saved;
  expect(saveResponse.ok()).toBe(true);
  const revision = await saveResponse.json();
  await expect(page.getByRole('link', { name: 'Export flattened YAML' })).toHaveAttribute(
    'href',
    revision.download_url,
  );
  const exported = await page.request.get(revision.download_url);
  expect(exported.ok()).toBe(true);
  expect(await exported.text()).toContain('env_name');
  const after = await (await page.request.get(path)).json();
  expect(after.source_hash).toBe(before.source_hash);
  expect(after.yaml_text).toBe(before.yaml_text);
});
test('real Neo4j examples produce table and separately inspectable graph results', async ({
  page,
}, testInfo) => {
  await openEditor(page);
  await page.getByRole('link', { name: 'Neo4j query', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Neo4j query', exact: true })).toBeVisible();
  const status = await (await page.request.get('/api/graph/status')).json();
  if (!status.available) {
    await expect(page.getByRole('button', { name: 'Run read-only query' })).toBeDisabled();
    await expect(page.getByText(status.message, { exact: true })).toBeVisible();
    return;
  }
  const response = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/graph/query');
  await page.getByRole('button', { name: 'Run read-only query' }).click();
  const resultResponse = await response;
  expect(resultResponse.ok()).toBe(true);
  const result = await resultResponse.json();
  expect(result.read_only).toBe(true);
  await expect(page.getByRole('table', { name: 'Neo4j query results' })).toBeVisible();
  await page.getByRole('tab', { name: 'Graph', exact: true }).click();
  if (result.graph.nodes.length) {
    await expect(page.getByLabel('Persisted Neo4j query graph', { exact: true })).toBeVisible();
    await page
      .getByRole('button', { name: `Inspect ${result.graph.nodes[0].label}`, exact: true })
      .first()
      .click();
    await expect(page.getByRole('heading', { name: 'Node inspector' })).toBeVisible();
  }
  await expect(page.getByLabel('Authored spatial graph', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('editor-neo4j.png'), fullPage: true });
});
test('explicit GPU render yields real decoded images, zoom and stale labels', async ({ page }) => {
  test.skip(
    process.env.WORKBENCH_E2E_SNAPSHOTS !== '1',
    'Requires explicit bounded GPU authorization.',
  );
  test.setTimeout(300_000);
  const index = await openEditor(page);
  expect(index.capabilities.snapshots).toBe(true);
  await page.getByRole('button', { name: 'Render snapshots' }).click();
  await page.getByLabel('Preview mode', { exact: true }).selectOption('scene');
  const image = page.getByRole('img', { name: /^scene snapshot / }).first();
  await expect(image).toBeVisible({ timeout: 260_000 });
  expect(
    await image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0),
  ).toBe(true);
  await page
    .getByRole('button', { name: /^Zoom scene snapshot/ })
    .first()
    .click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: 'Close image' }).last().click();
  const editor = page.getByRole('textbox', { name: 'YAML editor' });
  await editor.click();
  await page.keyboard.press('ControlOrMeta+End');
  await page.keyboard.insertText('\n# edited after render\n');
  await expect(page.getByText('Stale · draft changed since this render').first()).toBeVisible();
});
test('generation requires explicit authorization and review before applying', async ({ page }) => {
  test.skip(
    process.env.WORKBENCH_E2E_GENERATION !== '1',
    'Requires explicit LLM budget authorization.',
  );
  test.setTimeout(300_000);
  const index = await openEditor(page);
  expect(index.capabilities.generation).toBe(true);
  await page
    .getByLabel('Describe the environment and task')
    .fill(
      'Keep the current objects and robot. Preserve the pick-and-place task and produce a valid ArenaEnvGraphSpec.',
    );
  await page.getByRole('button', { name: 'Generate spec' }).click();
  await expect(page.getByRole('button', { name: 'Apply generated YAML' })).toBeVisible({
    timeout: 260_000,
  });
  await page.getByRole('button', { name: 'Apply generated YAML' }).click();
  await expect(page.getByText('Schema valid', { exact: true })).toBeVisible();
});
