import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { EditorView as CodeMirrorView } from '@codemirror/view';
import { beforeEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { App } from './app';
import { ApiClient } from './api';
const response = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status });
beforeEach(() => sessionStorage.clear());
const validation = {
  valid: true,
  source_hash: 'hash',
  canonical_hash: 'canonical',
  errors: [],
  warnings: [],
  spec: { env_name: 'real_document' },
  summary: 'One authored object',
  graph: {
    nodes: [
      { id: 'table', label: 'Table', role: 'object', properties: { registry_name: 'table' } },
      { id: 'relation', label: 'Explicit relation', role: 'reifier', properties: {} },
    ],
    edges: [],
  },
  assets: [{ id: 'table', role: 'object', properties: {} }],
  relations: [{ kind: 'is_anchor', subject: 'table', reference: null }],
  reified_relations: [],
  tasks: [{ kind: 'Pick', description: 'Pick an object' }],
};
export function editorServer() {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/health')) return response({ capabilities: { diagnostic: false } });
    if (url.endsWith('/sessions') || url.endsWith('/session/activity'))
      return response({ session_id: 's', csrf_token: 'csrf', expires_at: 9999999999 });
    if (url.endsWith('/workspaces/default'))
      return response({ id: 'default', name: 'Arena', jobs: [], event_cursor: 0 });
    if (url === '/api/editor')
      return response({
        default_document_id: 'fixture',
        documents: [{ id: 'fixture', name: 'Fixture', source: 'tests/fixture.yaml' }],
        capabilities: { generation: false, snapshots: false, neo4j: true },
        limitations: [],
      });
    if (url.includes('/editor/documents/'))
      return response({
        document_id: 'frozen-fixture',
        source: 'tests/fixture.yaml',
        yaml_text: 'env_name: real_document',
        source_hash: 'hash',
        validation,
      });
    if (url.endsWith('/editor/validate'))
      return response(
        JSON.parse(String(init?.body)).yaml_text.includes('broken')
          ? {
              ...validation,
              valid: false,
              errors: ['Invalid environment'],
              graph: { nodes: [], edges: [] },
            }
          : validation,
      );
    return response({ detail: 'not installed' }, 404);
  });
}
export function mountEditor(fetcher = editorServer(), path = '/') {
  return render(
    <App
      api={new ApiClient(fetcher as typeof fetch)}
      cache={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
      history={createMemoryHistory({ initialEntries: [path] })}
      makePort={() => null}
    />,
  );
}
it('restores matching saved asset previews in a fresh tab without submitting a render', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/workspaces/default')) return response({
      id: 'default', name: 'Arena', event_cursor: 1,
      jobs: [{
        id: 'saved-render', workspace_id: 'default', kind: 'snapshots',
        status: 'succeeded', stage: 'completed', updated_at: 10,
        inputs: { document_id: 'frozen-fixture', canonical_hash: 'canonical', yaml_text: 'env_name: real_document' },
        result: {
          input_hash: 'hash', warnings: [],
          assets: [{ id: 'table', artifact_id: 'table-image', url: '/api/editor/artifacts/table-image' }],
          scene: { artifact_id: 'scene-image', url: '/api/editor/artifacts/scene-image' },
        },
      }],
    });
    return base(url, init);
  });
  const view = mountEditor(fetcher);
  expect(await screen.findByRole('img', { name: 'table snapshot' })).toHaveAttribute('src', '/api/editor/artifacts/table-image');
  expect(screen.getByText('Matches current draft')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
  await screen.findByRole('heading', { name: 'Neo4j query' });
  fireEvent.click(screen.getByRole('link', { name: 'Environment editor' }));
  await screen.findByRole('img', { name: 'table snapshot' });
  view.unmount();
  mountEditor(fetcher);
  await screen.findByRole('img', { name: 'table snapshot' });
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it('recovers unsaved YAML after reload without silently changing the source context', async () => {
  const fetcher = editorServer();
  const view = mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: recovered_draft' } }));
  view.unmount();
  mountEditor(fetcher);
  fireEvent.click(await screen.findByRole('button', { name: 'Restore draft' }));
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('recovered_draft'));
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it.each(['Restore draft', 'Discard recovered draft'])(
  'keeps pending recovery across Neo4j navigation until explicit %s',
  async (decision) => {
    const fetcher = editorServer();
    const view = mountEditor(fetcher);
    await screen.findByRole('button', { name: 'Inspect Table' });
    const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
    act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: pending_recovery' } }));
    fireEvent.change(screen.getByLabelText('Describe the environment and task'), {
      target: { value: 'Keep this prompt too' },
    });
    const backup = sessionStorage.getItem('arena.editor.draft.v1');
    expect(backup).toContain('pending_recovery');
    view.unmount();
    mountEditor(fetcher);
    await screen.findByRole('button', { name: 'Restore draft' });

    async function visitNeo4jAndReturn() {
      fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
      await screen.findByRole('heading', { name: 'Neo4j query' });
      fireEvent.click(screen.getByRole('link', { name: 'Environment editor' }));
      await screen.findByRole('textbox', { name: 'YAML editor' });
    }

    await visitNeo4jAndReturn();
    expect(screen.getByRole('button', { name: 'Restore draft' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('real_document');
    expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(backup);
    await visitNeo4jAndReturn();
    expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(backup);
    fireEvent.click(screen.getByRole('button', { name: decision }));
    await visitNeo4jAndReturn();
    expect(screen.queryByRole('button', { name: 'Restore draft' })).not.toBeInTheDocument();
    if (decision === 'Restore draft') {
      expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('pending_recovery');
      expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Keep this prompt too');
      expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(backup);
    } else {
      expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('real_document');
      expect(sessionStorage.getItem('arena.editor.draft.v1')).toBeNull();
    }
    expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
  },
);

it('blocks recovery into changed included-source context and preserves a download option', async () => {
  const fetcher = editorServer();
  const view = mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: my_draft' } }));
  view.unmount();
  const changed = vi.fn(async (url: string, init?: RequestInit) => {
    const responseValue = await fetcher(url, init);
    if (url.includes('/editor/documents/')) return response({ ...(await responseValue.json()), document_id: 'changed-view' });
    return responseValue;
  });
  mountEditor(changed);
  expect(await screen.findByRole('button', { name: 'Restore draft' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Download recovered YAML' })).toBeEnabled();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('real_document');
});

it.each(['prompt', 'YAML', 'serialized record'])(
  'offers a raw current-YAML download when %s exceeds browser storage limits',
  async (field) => {
    const fetcher = editorServer();
    mountEditor(fetcher);
    await screen.findByRole('button', { name: 'Inspect Table' });
    const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
    act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: previous_backup' } }));
    const backup = sessionStorage.getItem('arena.editor.draft.v1');
    const yaml = field === 'prompt' ? cm.state.doc.toString()
      : field === 'YAML' ? 'broken: [' + 'y'.repeat(262_145) : '\0'.repeat(100_001);
    if (field === 'prompt') {
      fireEvent.change(screen.getByLabelText('Describe the environment and task'), {
        target: { value: 'p'.repeat(16_001) },
      });
    } else {
      act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: yaml } }));
    }
    await screen.findByText(/Export your YAML before reloading/);
    expect(sessionStorage.getItem('arena.editor.draft.v1')).toBe(backup);
    const download = screen.queryByRole('button', { name: 'Download current YAML' });
    expect(download).not.toBeNull();
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:current-draft');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = createObjectURL;
      static revokeObjectURL = revokeObjectURL;
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    try {
      fireEvent.click(download!);
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      const blob = createObjectURL.mock.calls[0][0] as Blob;
      expect(blob.type).toBe('application/yaml');
      const contents = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsText(blob);
      });
      expect(contents).toBe(yaml);
      const anchor = click.mock.instances[0] as HTMLAnchorElement;
      expect(anchor.href).toBe('blob:current-draft');
      expect(anchor.download).toBe('arena-draft.yaml');
      await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith('blob:current-draft'));
      expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
    } finally {
      vi.unstubAllGlobals();
      click.mockRestore();
    }
  },
);

it('opens the real document editor with authored graph and no implicit GPU or generation work', async () => {
  const fetcher = editorServer();
  mountEditor(fetcher);
  expect(
    await screen.findByRole('heading', { name: 'ArenaEnvGraphSpec live editor' }),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent(
      'env_name: real_document',
    ),
  );
  expect(await screen.findByRole('button', { name: 'Inspect Table' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Inspect Explicit relation' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Table' }));
  expect(screen.getByRole('heading', { name: 'Node inspector' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /Unary constraints/ })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Run integration test' })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(
    0,
  );
});
it('keeps unsaved YAML when visiting Neo4j and returning to the editor', async () => {
  mountEditor();
  await waitFor(() =>
    expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('real_document'),
  );
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() =>
    cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: unsaved' } }),
  );
  fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
  await screen.findByRole('heading', { name: 'Neo4j query' });
  fireEvent.click(screen.getByRole('link', { name: 'Environment editor' }));
  await waitFor(() =>
    expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent(
      'env_name: unsaved',
    ),
  );
});
it('retains ambiguous generation across reload and retries the frozen request without a new prompt', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') { const data = await (await base(url, init)).json(); return response({ ...data, capabilities: { ...data.capabilities, generation: true } }); }
    if (url.endsWith('/editor/generate')) throw new TypeError('network lost');
    return base(url, init);
  });
  const view = mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Make a scene' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await screen.findByText('network lost');
  const body = fetcher.mock.calls.find(([url]) => url.endsWith('/editor/generate'))![1]?.body;
  view.unmount(); mountEditor(fetcher);
  const retry = await screen.findByRole('button', { name: 'Retry generation request' });
  await waitFor(() => expect(retry).toBeEnabled());
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))).toHaveLength(1);
  fireEvent.click(retry);
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))).toHaveLength(2));
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))[1][1]?.body).toBe(body);
});
it('saves an immutable export and only applies generation after explicit review', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') {
      const data = await (await base(url, init)).json();
      return response({ ...data, capabilities: { ...data.capabilities, generation: true } });
    }
    if (url.endsWith('/editor/save'))
      return response({
        revision_id: 'rev',
        yaml_text: 'env_name: real_document',
        source_hash: 'hash',
        canonical_hash: 'canonical',
        download_url: '/api/editor/revisions/rev/download',
      });
    if (url.endsWith('/editor/generate') || url === '/api/jobs/generation')
      return response({
        id: 'generation',
        workspace_id: 'default',
        kind: 'generate',
        status: 'succeeded',
        stage: 'complete',
        inputs: {},
        result: {
          yaml_text: 'env_name: generated',
          validation,
          warnings: [],
          publication: 'not_published',
          traces: [],
        },
      });
    return base(url, init);
  });
  mountEditor(fetcher);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save revision' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Save revision' }));
  expect(await screen.findByRole('link', { name: 'Export flattened YAML' })).toHaveAttribute(
    'href',
    '/api/editor/revisions/rev/download',
  );
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), {
    target: { value: 'Make a scene' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  expect(await screen.findByRole('button', { name: 'Apply generated YAML' })).toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('real_document');
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() =>
    cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: newer_draft' } }),
  );
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  fireEvent.click(screen.getByRole('button', { name: 'Apply generated YAML' }));
  expect(confirm).toHaveBeenCalled();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('newer_draft');
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', { name: 'Apply generated YAML' }));
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('generated');
  confirm.mockRestore();
  const save = fetcher.mock.calls.find(([url]) => url.endsWith('/editor/save'))!;
  expect(JSON.parse(String(save[1]?.body))).toMatchObject({
    document_id: 'frozen-fixture',
    expected_source_hash: 'hash',
  });
  expect((save[1]?.headers as Record<string, string>)['X-CSRF-Token']).toBe('csrf');
});
it('renders only on request, shows authenticated asset and scene images, and opens zoom', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') {
      const data = await (await base(url, init)).json();
      return response({ ...data, capabilities: { ...data.capabilities, snapshots: true } });
    }
    if (url.endsWith('/editor/snapshots') || url === '/api/jobs/render')
      return response({
        id: 'render',
        workspace_id: 'default',
        kind: 'snapshots',
        status: 'succeeded',
        stage: 'complete',
        inputs: { document_id: 'frozen-fixture', canonical_hash: 'canonical', yaml_text: 'env_name: real_document' },
        result: {
          input_hash: 'hash',
          assets: [{ id: 'table', artifact_id: 'asset', url: '/api/editor/artifacts/asset' }],
          scene: { artifact_id: 'scene', url: '/api/editor/artifacts/scene' },
          warnings: [],
        },
      });
    return base(url, init);
  });
  mountEditor(fetcher);
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeEnabled(),
  );
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Render snapshots' }).compareDocumentPosition(
    document.querySelector('.asset-grid')!,
  ) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Render snapshots' }));
  expect(await screen.findByRole('img', { name: 'table snapshot' })).toHaveAttribute(
    'src',
    '/api/editor/artifacts/asset',
  );
  fireEvent.click(await screen.findByRole('button', { name: /Zoom scene snapshot/ }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Close image' }));
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: cm.state.doc.length, insert: '\n# changed' } }));
  expect(screen.getByText('Stale · draft changed since this render')).toBeInTheDocument();
});
it('queries Neo4j separately with parameters and switches table results to an interactive graph', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/graph/status')) return response({ available: true, message: 'Connected' });
    if (url.endsWith('/graph/examples'))
      return response({
        queries: [
          {
            id: 'nodes',
            name: 'Nodes',
            query: 'MATCH (n) RETURN n LIMIT $limit',
            params: { limit: 2 },
          },
        ],
      });
    if (url.endsWith('/graph/query'))
      return response({
        columns: ['n'],
        rows: [[{ name: 'Persisted table' }]],
        graph: {
          nodes: [
            {
              id: 'persisted',
              label: 'Persisted table',
              role: 'Asset',
              properties: { name: 'Persisted table' },
            },
          ],
          edges: [],
        },
        elapsed_ms: 2,
        truncated: true,
        read_only: true,
      });
    return base(url, init);
  });
  mountEditor(fetcher, '/neo4j');
  expect(await screen.findByRole('heading', { name: 'Neo4j query' })).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Run read-only query' })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Run read-only query' }));
  expect(await screen.findByText(/Results truncated/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'Graph' }));
  fireEvent.click(screen.getByRole('button', { name: 'Inspect Persisted table' }));
  expect(screen.getByRole('heading', { name: 'Node inspector' })).toBeInTheDocument();
  expect(screen.queryByLabelText('Authored spatial graph')).not.toBeInTheDocument();
  expect(
    JSON.parse(String(fetcher.mock.calls.find(([url]) => url.endsWith('/graph/query'))![1]?.body)),
  ).toEqual({ query: 'MATCH (n) RETURN n LIMIT $limit', params: { limit: 2 } });
});
