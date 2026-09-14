import { expect, type Page } from '@playwright/test';

// Hardware mode requires the documented NVIDIA-enabled browser container, never a software fallback.
export const graphLaunchOptions = process.env.WORKBENCH_GRAPH_HARDWARE === '1'
  ? { channel: 'chromium', args: ['--no-sandbox', '--enable-gpu', '--ignore-gpu-blocklist', '--disable-software-rasterizer', '--use-gl=angle', '--use-angle=gl-egl'] }
  : { args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] };

// SYNTHETIC API FIXTURE ONLY. No simulator, database, or physical-scene evidence.
// The actual application and force-graph Canvas/Three renderers are NOT mocked.
export const hostile = '<img src="https://graph-fixture.invalid/leak" onerror="window.__graphXSS=1">';
export const graph = {
  nodes: [
    { id: 'fixture:a', label: 'Synthetic Alpha', role: 'object', properties: { marker: 'SYNTHETIC ONLY', nested: { safe: hostile } } },
    { id: 'fixture:b', label: 'Synthetic Beta', role: 'background', properties: {} },
    { id: 'fixture:r', label: 'Synthetic Reifier', role: 'reifier', labels: ['Reifier'], properties: {} },
    { id: 'fixture:hostile[]#', label: hostile, role: 'object', properties: '[truncated]' },
  ],
  edges: [
    { id: 'fixture:edge-only', source: 'fixture:a', target: 'fixture:b', label: 'EDGE_ONLY_NEEDLE', properties: { synthetic: true } },
    { id: 'fixture:parallel', source: 'fixture:a', target: 'fixture:b', label: 'parallel', properties: {} },
    { id: 'fixture:reverse', source: 'fixture:b', target: 'fixture:a', label: 'reverse', properties: {} },
    { id: 'fixture:loop', source: 'fixture:a', target: 'fixture:a', label: 'unary_constraint', properties: {} },
    { id: 'fixture:subject', source: 'fixture:r', target: 'fixture:a', label: 'reifies_subject', properties: {} },
    { id: 'fixture:object', source: 'fixture:r', target: 'fixture:b', label: 'reifies_object', properties: {} },
  ],
};
export const yaml = 'env_name: SYNTHETIC_GRAPH_ACCEPTANCE_ONLY';
const validation = { valid: true, source_hash: 'synthetic-source', canonical_hash: 'b'.repeat(64), errors: [], warnings: [], spec: {}, summary: 'SYNTHETIC GRAPH ACCEPTANCE ONLY', graph, assets: [], relations: [], reified_relations: [], tasks: [] };
export async function syntheticApi(page: Page) {
  const state = { unexpected: [] as string[], external: [] as string[], requests: [] as string[], queries: [] as unknown[], errors: [] as string[], threeRequests: [] as string[] };
  page.on('pageerror', e => state.errors.push(e.stack ?? e.message));
  page.on('request', r => { if (/graph-3d|react-force-graph-3d|three(?:\.|_)/i.test(r.url())) state.threeRequests.push(r.url()); });
  await page.addInitScript(() => {
    Object.defineProperty(window, 'SharedWorker', { value: undefined });
    // Passive observation of REAL Canvas draws, not a replacement renderer.
    const w = window as any;
    w.__graphDraws = {};
    w.__graphPendingRAF = new Set();
    const raf = window.requestAnimationFrame.bind(window), cancel = window.cancelAnimationFrame.bind(window);
    window.requestAnimationFrame = cb => { const id = raf(t => { w.__graphPendingRAF.delete(id); cb(t); }); w.__graphPendingRAF.add(id); return id; };
    window.cancelAnimationFrame = id => { w.__graphPendingRAF.delete(id); cancel(id); };
    const draw = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function(text, x, y, ...rest) {
      if (this.canvas.closest('[data-graph-renderer="2d"]') && text === 'Synthetic Alpha') {
        const m = this.getTransform();
        const nodeY = y - 10 - 12 / Math.max(Math.abs(m.a), 0.1);
        w.__graphDraws.alpha = { x: m.a*x + m.c*nodeY + m.e, y: m.b*x + m.d*nodeY + m.f, scale: m.a, at: performance.now() };
      }
      return draw.call(this, text, x, y, ...rest);
    };
  });
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url());
    if (!['http:', 'https:'].includes(url.protocol)) return route.continue();
    if (url.origin !== new URL(process.env.WORKBENCH_BASE_URL ?? 'http://127.0.0.1:3001').origin) {
      state.external.push(req.url()); return route.abort('blockedbyclient');
    }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname, entry = `${req.method()} ${path}`;
    state.requests.push(entry);
    const json = (value: unknown) => route.fulfill({ json: value });
    if (path === '/api/model-settings' && req.method() === 'GET') return json({ configured: false, source: 'none', provider: null, model: null, credential_ref: null, expires_at: null, session_keys_allowed: false, providers: [
      { id: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com/v1' },
      { id: 'gemini', label: 'Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/' },
      { id: 'openrouter', label: 'OpenRouter', base_url: 'https://openrouter.ai/api/v1' },
      { id: 'nvidia', label: 'NVIDIA', base_url: 'https://integrate.api.nvidia.com/v1' },
    ] });
    if (path === '/api/health') return json({ capabilities: { diagnostic: false } });
    if (path === '/api/sessions' || path === '/api/session/activity') return json({ session_id: 'synthetic-graph-session', csrf_token: 'synthetic-csrf', expires_at: 9999999999 });
    if (path === '/api/workspaces/default') return json({ id: 'default', name: 'SYNTHETIC GRAPH', event_cursor: 0, jobs: [] });
    if (path === '/api/editor') return json({ default_document_id: 'graph-fixture', documents: [{ id: 'graph-fixture', name: 'SYNTHETIC GRAPH', source: 'synthetic.yaml' }], capabilities: { snapshots: false, generation: false, neo4j: true }, limitations: ['Synthetic API data; actual browser renderer.'] });
    if (path === '/api/editor/documents/graph-fixture') return json({ document_id: 'synthetic-document', source: 'synthetic.yaml', yaml_text: yaml, source_hash: 'synthetic-source', validation });
    if (path === '/api/editor/validate') return json(validation);
    if (path.startsWith('/api/editor/previews/')) return json({ status: 'miss', canonical_hash: validation.canonical_hash, receipt: null });
    if (path === '/api/graph/status') return json({ available: true, message: 'SYNTHETIC database protocol fixture (no database contacted)' });
    if (path === '/api/graph/examples') return json({ queries: [{ id: 'synthetic', name: 'Synthetic read', query: 'MATCH (n) RETURN n LIMIT 4', params: {} }] });
    if (path === '/api/graph/query') { state.queries.push(req.postDataJSON()); return json({ columns: ['synthetic_scalar', 'nested'], rows: [[42, { marker: 'RAW_ROWS_ONLY', hostile }]], graph, elapsed_ms: 0, truncated: true }); }
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
    state.unexpected.push(entry);
    return route.fulfill({ status: 404, json: { detail: `Synthetic suite blocks ${entry}` } });
  });
  return state;
}
export async function openGraph(page: Page) {
  await page.goto('/workspaces/default?graphRenderer=explorer');
  const root = page.locator('.graph-explorer');
  await expect(root.getByRole('tablist', { name: 'Graph display mode' })).toBeVisible();
  return root;
}
