import { test, expect, type Page, type Locator } from '@playwright/test';
import { syntheticApi, openGraph, hostile, yaml, graphLaunchOptions } from './graph-fixtures';

// Real Chromium + actual force-graph engines; ONLY API data is synthetic.
// SwiftShader is software WebGL, not physical-GPU/simulator verification.
test.use({ launchOptions: graphLaunchOptions, serviceWorkers: 'block' });
test.setTimeout(35_000);
test.describe.configure({ mode: 'default' });
const states = new WeakMap<Page, Awaited<ReturnType<typeof syntheticApi>>>();
test.beforeEach(async ({ page }) => { states.set(page, await syntheticApi(page)); });
test.afterEach(async ({ page }, info) => {
  const state = states.get(page)!;
  const path = info.outputPath('synthetic-real-engine.png');
  await page.screenshot({ path, fullPage: true }).catch(() => {});
  await info.attach('synthetic-network-and-errors', { body: JSON.stringify(state, null, 2), contentType: 'application/json' });
  console.log(JSON.stringify({ test: info.title, screenshot: path, unexpected: state.unexpected, external: state.external, pageErrors: state.errors, lazy3dRequestCount: state.threeRequests.length }));
  expect.soft(state.unexpected, 'all API requests must be explicitly mocked').toEqual([]);
  expect.soft(state.external, 'hostile labels and engines must not request external resources').toEqual([]);
});
async function mode(root: Locator, name: string) {
  await root.getByRole('tablist', { name: 'Graph display mode' }).getByRole('tab', { name, exact: true }).click();
  if (name !== 'Table') await expect(root.locator(`[data-graph-renderer="${name.toLowerCase()}"] canvas`).first()).toBeVisible();
}
async function selectAlpha(root: Locator) {
  await mode(root, 'Table');
  await root.getByRole('button', { name: 'Inspect node fixture:a', exact: true }).click();
  await expect(root.getByRole('complementary', { name: 'Selection inspector' })).toContainText('Node: Synthetic Alpha');
}

test('synthetic entities: table, edge-only context, exclusions, Reveal, reifier/self-loop/hostile text', async ({ page }) => {
  const root = await openGraph(page);
  await selectAlpha(root);
  await expect(root.getByRole('table')).toContainText(hostile);
  await root.getByRole('tab', { name: 'Relationships', exact: true }).click();
  await expect(root.getByRole('table').locator('tbody tr')).toHaveCount(6);
  await root.getByRole('table').getByRole('button', { name: 'Inspect relationship fixture:loop', exact: true }).click();
  await expect(root.getByText('Self-loop constraint', { exact: true })).toBeVisible();
  await root.getByLabel('Search returned graph', { exact: true }).fill('EDGE_ONLY_NEEDLE');
  await root.getByLabel('Show matches only', { exact: true }).check();
  await expect(root.getByText(/Visible: 2 \/ returned 4 nodes/)).toContainText('4 / returned 6 relationships');
  await root.getByRole('button', { name: 'edge: EDGE_ONLY_NEEDLE · fixture:edge-only', exact: true }).click();
  await root.getByText('Node roles', { exact: true }).click();
  await root.getByRole('checkbox', { name: 'Role background', exact: true }).uncheck();
  await expect(root.getByText('Hidden by filters', { exact: true })).toBeVisible();
  await root.getByRole('button', { name: 'Reveal (clear filters)', exact: true }).click();
  await expect(root.getByLabel('Show matches only', { exact: true })).not.toBeChecked();
  await expect(root.getByLabel('Search returned graph', { exact: true })).toHaveValue('EDGE_ONLY_NEEDLE');
  await root.getByText('Relationship types', { exact: true }).click();
  await root.getByRole('checkbox', { name: 'Type EDGE_ONLY_NEEDLE', exact: true }).uncheck();
  await expect(root.getByText('Hidden by filters', { exact: true })).toBeVisible();
  await root.getByRole('button', { name: 'Reveal (clear filters)', exact: true }).click();
  await root.getByRole('button', { name: 'Clear filters', exact: true }).click();
  await root.getByRole('tab', { name: 'Nodes', exact: true }).click();
  await root.getByRole('button', { name: 'Inspect node fixture:r', exact: true }).click();
  await expect(root.getByRole('complementary')).toContainText('Reifier');
  await root.getByRole('button', { name: 'Inspect node fixture:hostile[]#', exact: true }).click();
  await expect(root.getByRole('complementary')).toContainText('[truncated]');
  expect(await page.evaluate(() => (window as any).__graphXSS)).toBeUndefined();
});

test('real 2D: keyboard/click coordinates, freeze, pin, nudge, reset and camera pixels', async ({ page }, info) => {
  const root = await openGraph(page); await selectAlpha(root); await mode(root, '2D');
  await expect(root.getByRole('button', { name: 'Freeze layout', exact: true })).toBeEnabled();
  await root.getByRole('button', { name: 'Freeze layout', exact: true }).press('Enter');
  await expect(root.getByRole('button', { name: 'Resume layout', exact: true })).toBeVisible();
  await root.getByLabel('Layout X', { exact: true }).fill('12'); await root.getByLabel('Layout Y', { exact: true }).fill('34');
  await root.getByRole('button', { name: 'Apply coordinates', exact: true }).press('Enter');
  await expect(root.getByRole('button', { name: 'Unpin selected', exact: true })).toBeVisible();
  await root.getByRole('button', { name: 'Nudge right (view-relative)', exact: true }).click();
  await expect(root.getByLabel('Layout X', { exact: true })).not.toHaveValue('12');
  const canvas = root.locator('[data-graph-renderer="2d"] canvas').first();
  const before = await canvas.screenshot();
  await root.getByRole('button', { name: 'Pan right', exact: true }).press('Enter');
  await root.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await expect.poll(async () => !(await canvas.screenshot()).equals(before)).toBe(true);
  await info.attach('measured-layout', { body: JSON.stringify({ x: await root.getByLabel('Layout X', { exact: true }).inputValue(), y: await root.getByLabel('Layout Y', { exact: true }).inputValue(), cameraPixelsChanged: true }), contentType: 'application/json' });
  await root.getByRole('button', { name: 'Unpin selected', exact: true }).click();
  await expect(root.getByRole('button', { name: 'Pin selected', exact: true })).toBeVisible();
  await root.getByRole('button', { name: 'Pin selected', exact: true }).click();
  await root.getByRole('button', { name: 'Unpin all', exact: true }).click();
  await expect(root.getByText('0 pinned · Frozen', { exact: true })).toBeVisible();
  await root.getByRole('button', { name: 'Reset layout', exact: true }).click();
  await expect(root.getByRole('complementary')).toContainText('Node: Synthetic Alpha');
  expect(states.get(page)!.errors).toEqual([]);
});

test('real 2D pointer drag moves and pins a node while frozen', async ({ page }, info) => {
  const root = await openGraph(page); await selectAlpha(root); await mode(root, '2D');
  await root.getByRole('button', { name: 'Freeze layout', exact: true }).click();
  await root.getByRole('combobox', { name: 'Label density', exact: true }).selectOption('all');
  const canvas = root.locator('[data-graph-renderer="2d"] canvas').first();
  await canvas.scrollIntoViewIfNeeded();
  await expect.poll(() => page.evaluate(() => !!(window as any).__graphDraws.alpha)).toBe(true);
  const point = await page.evaluate(() => (window as any).__graphDraws.alpha);
  const box = (await canvas.boundingBox())!;
  const dimensions = await canvas.evaluate((c: HTMLCanvasElement) => ({ width: c.width, height: c.height }));
  const x = box.x + point.x * box.width / dimensions.width, y = box.y + point.y * box.height / dimensions.height;
  const before = { x: await root.getByLabel('Layout X', { exact: true }).inputValue(), y: await root.getByLabel('Layout Y', { exact: true }).inputValue() };
  await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x + 42, y + 24, { steps: 12 }); await page.mouse.up();
  await expect(root.getByRole('button', { name: 'Unpin selected', exact: true })).toBeVisible();
  await expect(root.getByLabel('Layout X', { exact: true })).not.toHaveValue(before.x);
  await info.attach('actual-drag-measurement', { body: JSON.stringify({ point, before, after: { x: await root.getByLabel('Layout X', { exact: true }).inputValue(), y: await root.getByLabel('Layout Y', { exact: true }).inputValue() } }), contentType: 'application/json' });
});

test('lazy real 3D, retained selection and camera orbit, actual context-loss fallback', async ({ page }, info) => {
  const root = await openGraph(page); await selectAlpha(root);
  expect(states.get(page)!.threeRequests).toEqual([]);
  await mode(root, '3D');
  await expect.poll(() => states.get(page)!.threeRequests.length).toBeGreaterThan(0);
  await expect(root.getByRole('complementary')).toContainText('Node: Synthetic Alpha');
  await root.getByRole('button', { name: 'Freeze layout', exact: true }).click();
  const canvas = root.locator('[data-graph-renderer="3d"] canvas').first();
  const before = await canvas.screenshot();
  await root.getByRole('button', { name: 'Orbit right', exact: true }).click();
  await expect.poll(async () => !(await canvas.screenshot()).equals(before)).toBe(true);
  const context = await canvas.evaluate((c: HTMLCanvasElement) => { const gl = c.getContext('webgl2'); if (!gl) return { webgl2: false, lossExtension: false, renderer: null }; const ext = gl.getExtension('WEBGL_lose_context'); const debug = gl.getExtension('WEBGL_debug_renderer_info'); const result = { webgl2: true, lossExtension: !!ext, renderer: gl.getParameter(debug ? debug.UNMASKED_RENDERER_WEBGL : gl.RENDERER) }; ext?.loseContext(); return result; });
  await info.attach('actual-webgl-capability', { body: JSON.stringify(context), contentType: 'application/json' });
  expect(context.webgl2).toBe(true); expect(context.lossExtension).toBe(true);
  if (process.env.WORKBENCH_GRAPH_HARDWARE === '1') { expect(context.renderer).toContain('NVIDIA'); expect(context.renderer).not.toMatch(/SwiftShader|llvmpipe/i); }
  await expect(root.getByRole('alert')).toContainText('Graph renderer unavailable');
  await mode(root, 'Table'); await expect(root.getByRole('complementary')).toContainText('Node: Synthetic Alpha');
  await mode(root, '2D');
});

test('WebGL unavailable is local, with Table and 2D recovery', async ({ page }) => {
  // Deliberate browser capability failure; Canvas 2D and engine modules stay real.
  await page.addInitScript(() => { const original = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function(this: HTMLCanvasElement, kind: any, ...args: any[]) { if (String(kind).includes('webgl')) return null; return original.call(this, kind, ...args); } as any; });
  const root = await openGraph(page); await selectAlpha(root);
  await root.getByRole('tablist', { name: 'Graph display mode' }).getByRole('tab', { name: '3D', exact: true }).click();
  await expect(root.getByRole('alert')).toContainText('Graph renderer unavailable');
  await mode(root, 'Table'); await expect(root.getByRole('complementary')).toContainText('Node: Synthetic Alpha');
  await mode(root, '2D');
});

test('real 3D pointer dragging repositions the selected node while frozen', async ({ page }, info) => {
  const root = await openGraph(page); await selectAlpha(root);
  await root.getByLabel('Search returned graph', { exact: true }).fill('fixture:a');
  await root.getByLabel('Show matches only', { exact: true }).check();
  await expect(root.getByText(/Visible: 1 \/ returned 4 nodes/)).toBeVisible();
  await mode(root, '3D');
  await root.getByRole('button', { name: 'Freeze layout', exact: true }).click();
  for (const axis of ['X', 'Y', 'Z']) await root.getByLabel(`Layout ${axis}`, { exact: true }).fill('0');
  await root.getByRole('button', { name: 'Apply coordinates', exact: true }).click();
  await root.getByRole('button', { name: 'Fit visible', exact: true }).click();
  const canvas = root.locator('[data-graph-renderer="3d"] canvas').first();
  await canvas.scrollIntoViewIfNeeded();
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 40, box.y + box.height / 2 + 20, { steps: 12 });
  await page.mouse.up();
  await expect(root.getByLabel('Layout X', { exact: true })).not.toHaveValue('0');
  await expect(root.getByText('1 pinned · Frozen', { exact: true })).toBeVisible();
  await info.attach('actual-3D-drag-measurement', { body: JSON.stringify({ x: await root.getByLabel('Layout X', { exact: true }).inputValue(), y: await root.getByLabel('Layout Y', { exact: true }).inputValue(), z: await root.getByLabel('Layout Z', { exact: true }).inputValue() }), contentType: 'application/json' });
  expect(states.get(page)!.errors).toEqual([]);
});

test('expanded keyboard focus, theme/mobile, and legacy rollback preserve unsaved YAML', async ({ page }) => {
  const root = await openGraph(page);
  const editor = page.getByRole('textbox', { name: 'YAML editor', exact: true });
  await editor.fill(`${yaml}\n# UNSAVED_SYNTHETIC_DRAFT`);
  const trigger = root.getByRole('button', { name: 'Expand graph', exact: true });
  await trigger.click(); await expect(root).toHaveAttribute('role', 'dialog');
  await expect(root.getByRole('button', { name: 'Close expanded graph', exact: true })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  expect(await root.evaluate(r => r.contains(document.activeElement))).toBe(true);
  await page.keyboard.press('Escape'); await expect(trigger).toBeFocused();
  await page.getByRole('switch', { name: 'Dark mode', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Use legacy graph', exact: true }).click();
  await expect(page.locator('.graph-explorer')).toHaveCount(0);
  await expect(editor).toContainText('UNSAVED_SYNTHETIC_DRAFT');
  await page.getByRole('button', { name: 'Try graph explorer', exact: true }).click();
  await expect(page.locator('.graph-explorer')).toBeVisible();
  await expect(editor).toContainText('UNSAVED_SYNTHETIC_DRAFT');
});

test('mocked raw query rows remain distinct from graph entities without follow-up queries', async ({ page }) => {
  await page.goto('/neo4j?graphRenderer=explorer');
  await page.getByRole('button', { name: 'Run read-only query', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Neo4j query results', exact: true })).toContainText('RAW_ROWS_ONLY');
  await page.getByRole('tablist', { name: 'Query result format' }).getByRole('tab', { name: 'Graph', exact: true }).click();
  const root = page.locator('.graph-explorer'); await selectAlpha(root);
  await expect(root.getByRole('table')).not.toContainText('RAW_ROWS_ONLY');
  await mode(root, '2D'); await mode(root, '3D');
  await page.getByRole('tablist', { name: 'Query result format' }).getByRole('tab', { name: 'Table', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Neo4j query results', exact: true })).toContainText('42');
  expect(states.get(page)!.queries).toHaveLength(1);
});

test('20 real-engine mode cycles dispose canvases and pending animation frames', async ({ page }, info) => {
  test.setTimeout(90_000);
  const root = await openGraph(page); await mode(root, 'Table');
  const cdp = await page.context().newCDPSession(page);
  await expect.poll(() => page.evaluate(() => (window as any).__graphPendingRAF.size)).toBe(0);
  const measurements: unknown[] = [];
  for (let cycle = 0; cycle < 20; cycle++) {
    await mode(root, cycle % 2 ? '3D' : '2D');
    await expect(root.getByRole('button', { name: 'Reset layout', exact: true })).toBeEnabled();
    await mode(root, 'Table');
    await expect(root.locator('[data-graph-renderer]')).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => (window as any).__graphPendingRAF.size), { timeout: 3000 }).toBe(0);
    await cdp.send('HeapProfiler.collectGarbage');
    const heap = await cdp.send('Runtime.getHeapUsage');
    measurements.push({ ...await page.evaluate(cycle => ({ cycle, canvases: document.querySelectorAll('.graph-explorer canvas').length, pendingRAF: (window as any).__graphPendingRAF.size }), cycle), usedHeapAfterGC: heap.usedSize });
  }
  await info.attach('20-cycle-measurements', { body: JSON.stringify(measurements, null, 2), contentType: 'application/json' });
  expect(states.get(page)!.errors).toEqual([]);
  await cdp.detach();
});
