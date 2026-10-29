import { test, expect } from '@playwright/test';
import { syntheticApi, yaml, graphLaunchOptions } from './graph-fixtures';

// Synthetic density measurements with actual engines. Report timing, not physical GPU claims.
test.use({ launchOptions: graphLaunchOptions, serviceWorkers: 'block' });
for (const size of [50, 256, 1000]) {
  test(`synthetic graph density ${size}: responsive table and bounded visual workload`, async ({ page }, info) => {
    test.setTimeout(90_000);
    const network = await syntheticApi(page);
    const graph = {
      nodes: Array.from({ length: size }, (_, i) => ({ id: `node:${i}`, label: `Synthetic density node ${i}`, role: i % 5 === 0 ? 'reifier' : 'object', properties: { synthetic: true } })),
      edges: Array.from({ length: size * 2 }, (_, i) => ({ id: `edge:${i}`, source: `node:${i % size}`, target: `node:${(i * 7 + 1) % size}`, label: `relation${i % 4}`, properties: {} })),
    };
    await page.route('**/api/editor/documents/graph-fixture', route => route.fulfill({ json: {
      document_id: `synthetic-density-${size}`, source: 'SYNTHETIC_DENSITY_ONLY.yaml', yaml_text: yaml, source_hash: 'source',
      validation: { valid: true, source_hash: 'source', canonical_hash: 'c'.repeat(64), errors: [], warnings: [], spec: {}, summary: 'Synthetic density fixture', graph, assets: [], relations: [], reified_relations: [], tasks: [] },
    } }));
    const started = Date.now();
    await page.goto('/workspaces/default?graphRenderer=explorer');
    const root = page.locator('.graph-explorer');
    const modes = root.getByRole('tablist', { name: 'Graph display mode' });
    await expect(modes).toBeVisible();
    await expect(root.getByText(`Visible: ${size} / returned ${size} nodes`, { exact: false })).toBeVisible();
    const timings: Record<string, unknown> = { synthetic: true, size, edges: graph.edges.length, pageReadyMs: Date.now() - started };
    if (size <= 256) {
      await expect(root.getByRole('button', { name: 'Freeze layout', exact: true })).toBeEnabled();
      await root.locator('[data-graph-renderer="2d"] canvas').first().scrollIntoViewIfNeeded();
      timings.initial2DReadyMs = Date.now() - started;
      timings.frameIntervals2D = await page.evaluate(() => new Promise(resolve => {
        const intervals: number[] = []; let previous = performance.now();
        function frame(now: number) { intervals.push(now - previous); previous = now; if (intervals.length < 90) requestAnimationFrame(frame); else { const sorted = intervals.slice(1).sort((a, b) => a - b); resolve({ samples: sorted.length, p95ms: sorted[Math.floor(sorted.length * .95)], maxMs: sorted.at(-1) }); } }
        requestAnimationFrame(frame);
      }));
      await root.getByRole('button', { name: 'Freeze layout', exact: true }).click();
    } else {
      await expect(root.getByText(/Visualization limit:/)).toBeVisible();
      await expect(root.locator('canvas')).toHaveCount(0);
    }
    await modes.getByRole('tab', { name: 'Table', exact: true }).click();
    await expect(root.getByRole('table').locator('tbody tr')).toHaveCount(25);
    const filterStarted = Date.now();
    await root.getByLabel('Search returned graph', { exact: true }).fill('node:0');
    await root.getByLabel('Show matches only', { exact: true }).check();
    await expect(root.getByText(`Visible: 1 / returned ${size} nodes`, { exact: false })).toBeVisible();
    timings.filterVisibleMs = Date.now() - filterStarted;
    await info.attach('synthetic-density-measurements', { body: JSON.stringify(timings, null, 2), contentType: 'application/json' });
    await page.screenshot({ path: info.outputPath(`synthetic-density-${size}.png`), fullPage: true });
    expect(network.errors).toEqual([]);
    expect(network.unexpected).toEqual([]);
    expect(network.external).toEqual([]);
  });
}
