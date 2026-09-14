import { expect, test } from '@playwright/test';
import { graphLaunchOptions } from './graph-fixtures';

// Actual authenticated API, persisted read-only Neo4j queries, and real graph renderers.
// No credentials entered, no environment saves, no inference or simulator submissions.
test.use({ launchOptions: graphLaunchOptions, trace: 'off', video: 'off' });
test('live authored and persisted graphs use the explorer without changing jobs or source', async ({ page }, info) => {
  const writes: string[] = [], errors: string[] = [];
  page.on('request', request => { if (!['GET', 'HEAD'].includes(request.method())) writes.push(`${request.method()} ${new URL(request.url()).pathname}`); });
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/workspaces/default?graphRenderer=explorer');
  await expect(page.getByRole('button', { name: 'End session', exact: true })).toBeVisible();
  const beforeJobs = await (await page.request.get('/api/jobs')).json();
  const indexResponse = await page.request.get('/api/editor'); expect(indexResponse.ok()).toBe(true);
  const index = await indexResponse.json();
  const documentResponse = await page.request.get(`/api/editor/documents/${index.default_document_id}`); expect(documentResponse.ok()).toBe(true);
  const document = await documentResponse.json();
  const root = page.locator('.graph-explorer');
  await expect(root.getByText(`Visible: ${document.validation.graph.nodes.length} / returned ${document.validation.graph.nodes.length} nodes`, { exact: false })).toBeVisible();
  const modes = root.getByRole('tablist', { name: 'Graph display mode' });
  await modes.getByRole('tab', { name: 'Table', exact: true }).click();
  const first = document.validation.graph.nodes[0];
  await root.getByRole('button', { name: `Inspect node ${first.id}`, exact: true }).click();
  await expect(root.getByRole('complementary', { name: 'Selection inspector' })).toContainText(first.label);
  await modes.getByRole('tab', { name: '2D', exact: true }).click();
  await root.getByRole('button', { name: 'Freeze layout', exact: true }).click();
  await root.getByRole('button', { name: 'Expand graph', exact: true }).click();
  await root.getByRole('button', { name: 'Fit visible', exact: true }).click();
  await root.screenshot({ path: info.outputPath('live-authored-2d.png') });
  await modes.getByRole('tab', { name: '3D', exact: true }).click();
  await root.getByRole('button', { name: 'Freeze layout', exact: true }).click();
  const renderer = await root.locator('[data-graph-renderer="3d"] canvas').first().evaluate((canvas: HTMLCanvasElement) => {
    const gl = canvas.getContext('webgl2')!; const debug = gl.getExtension('WEBGL_debug_renderer_info');
    return gl.getParameter(debug ? debug.UNMASKED_RENDERER_WEBGL : gl.RENDERER);
  });
  if (process.env.WORKBENCH_GRAPH_HARDWARE === '1') expect(renderer).toContain('NVIDIA');
  await root.screenshot({ path: info.outputPath('live-authored-3d.png') });
  await root.getByRole('button', { name: 'Close expanded graph', exact: true }).click();
  await page.getByRole('button', { name: 'Use legacy graph', exact: true }).click();
  await expect(page.getByLabel('Authored spatial graph', { exact: true })).toBeVisible();
  const sourceAfter = await (await page.request.get(`/api/editor/documents/${index.default_document_id}`)).json();
  expect(sourceAfter.yaml_text).toBe(document.yaml_text);
  expect(sourceAfter.validation.canonical_hash).toBe(document.validation.canonical_hash);

  await page.goto('/neo4j?graphRenderer=explorer');
  await expect(page.getByRole('button', { name: 'Run read-only query', exact: true })).toBeEnabled();
  await page.getByRole('textbox', { name: 'Cypher query', exact: true }).fill('MATCH (e:EnvironmentGraph)-[r]->(n) RETURN e,r,n LIMIT 25');
  const queryResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/graph/query');
  await page.getByRole('button', { name: 'Run read-only query', exact: true }).click();
  const query = await queryResponse; expect(query.ok()).toBe(true);
  const result = await query.json(); expect(result.graph.nodes.length).toBeGreaterThan(0); expect(result.graph.edges.length).toBeGreaterThan(0);
  await expect(page.getByRole('table', { name: 'Neo4j query results', exact: true })).toBeVisible();
  await page.getByRole('tablist', { name: 'Query result format' }).getByRole('tab', { name: 'Graph', exact: true }).click();
  await expect(root.getByText(`Visible: ${result.graph.nodes.length} / returned ${result.graph.nodes.length} nodes`, { exact: false })).toBeVisible();
  await root.getByRole('button', { name: 'Expand graph', exact: true }).click();
  await root.getByRole('button', { name: 'Freeze layout', exact: true }).click();
  await root.getByRole('button', { name: 'Fit visible', exact: true }).click();
  await root.screenshot({ path: info.outputPath('live-neo4j-2d.png') });
  await root.getByRole('button', { name: 'Close expanded graph', exact: true }).click();
  await page.getByRole('tablist', { name: 'Query result format' }).getByRole('tab', { name: 'Table', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Neo4j query results', exact: true })).toBeVisible();
  const afterJobs = await (await page.request.get('/api/jobs')).json();
  expect(afterJobs.jobs.map((job: { id: string }) => job.id)).toEqual(beforeJobs.jobs.map((job: { id: string }) => job.id));
  expect(writes.filter(write => !['POST /api/sessions', 'POST /api/session/activity', 'POST /api/graph/query'].includes(write))).toEqual([]);
  expect(writes.filter(write => write === 'POST /api/graph/query')).toHaveLength(1);
  expect(errors).toEqual([]);
  await info.attach('live-graph-evidence', { body: JSON.stringify({ renderer, authored: { nodes: document.validation.graph.nodes.length, edges: document.validation.graph.edges.length }, persisted: { nodes: result.graph.nodes.length, edges: result.graph.edges.length, rows: result.rows.length, truncated: result.truncated }, writes, unchangedJobs: true, unchangedSource: true }, null, 2), contentType: 'application/json' });
});
