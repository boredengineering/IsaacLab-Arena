import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { EditorView as CodeMirrorView } from '@codemirror/view';
import { beforeEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { App } from './app';
import { ApiClient } from './api';
import { PROVIDERS } from './model-settings-contracts';
const response = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status });
beforeEach(() => sessionStorage.clear());
const validation = {
  valid: true,
  source_hash: 'hash',
  canonical_hash: 'a'.repeat(64),
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
    if (url.includes('/editor/previews/')) return response({ status: 'miss', canonical_hash: validation.canonical_hash, receipt: null });
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
    if (url.includes('/editor/previews/')) return response({ status: 'hit', canonical_hash: validation.canonical_hash, receipt: {
      canonical_hash: validation.canonical_hash, cache_key: 'saved-render', options: { view: 'isometric', resolution: 1024, asset_views: {} },
      input_hash: 'hash', warnings: [], assets: [{ id: 'table', artifact_id: 'table-image', url: '/api/editor/artifacts/table-image' }],
      scene: { artifact_id: 'scene-image', url: '/api/editor/artifacts/scene-image' },
    } });
    return base(url, init);
  });
  const view = mountEditor(fetcher);
  expect(await screen.findByRole('img', { name: 'table snapshot' })).toHaveAttribute('src', '/api/editor/artifacts/table-image');
  fireEvent.change(screen.getByLabelText('Preview mode'), { target: { value: 'scene' } });
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

it('restores explicitly historical previews without calling them current or submitting automatic jobs', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.includes('/editor/previews/')) {
      const query = new URL(url, 'http://localhost').searchParams;
      return response({ status: 'historical', canonical_hash: validation.canonical_hash, receipt: {
        canonical_hash: validation.canonical_hash, cache_key: 'saved-history', freshness: 'unverified_assets',
        options: { view: query.get('view'), resolution: Number(query.get('resolution')), asset_views: JSON.parse(query.get('asset_views')!) },
        warnings: [], assets: [{ id: 'table', artifact_id: 'table-history', url: '/api/editor/artifacts/table-history' }],
        scene: { artifact_id: 'scene-history', url: '/api/editor/artifacts/scene-history' },
      } });
    }
    return base(url, init);
  });
  const view = mountEditor(fetcher);
  expect(await screen.findByRole('img', { name: 'table snapshot' })).toHaveAttribute('src', '/api/editor/artifacts/table-history');
  expect(screen.getByText('Historical preview · asset freshness unverified')).toBeInTheDocument();
  expect(screen.queryByText(/Saved previews match the validated scene/)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Preview mode'), { target: { value: 'scene' } });
  expect(screen.getByRole('img', { name: 'scene snapshot saved-history' })).toBeInTheDocument();
  expect(screen.queryByText('Matches current draft')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' }));
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'top' } });
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('view=top'))).toBe(true));
  await screen.findByRole('img', { name: 'scene snapshot saved-history' });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 1700)); });
  fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
  await screen.findByRole('heading', { name: 'Neo4j query' });
  fireEvent.click(screen.getByRole('link', { name: 'Environment editor' }));
  await screen.findByRole('img', { name: 'table snapshot' });
  view.unmount();
  sessionStorage.clear();
  mountEditor(fetcher);
  await screen.findByRole('img', { name: 'table snapshot' });
  expect(screen.getByText('Historical preview · asset freshness unverified')).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it.each(['hit', 'historical'])('uses the read-only %s catalogue without journal fallback after a miss', async (status) => {
  const base = editorServer();
  let hit = true;
  const hash = 'a'.repeat(64);
  const receipt = { input_hash: 'hash', canonical_hash: hash, cache_key: 'cache',
    freshness: status === 'historical' ? 'unverified_assets' : 'verified_assets',
    options: { view: 'isometric', resolution: 1024, asset_views: {} },
    assets: [{ id: 'table', artifact_id: 'catalogue-table', url: '/api/editor/artifacts/catalogue-table' }],
    scene: null, warnings: [] };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/editor/documents/')) return response({ ...(await (await base(url, init)).json()), validation: { ...validation, canonical_hash: hash } });
    if (url.includes('/editor/previews/')) return response({ status: hit ? status : 'miss', canonical_hash: hash, receipt: hit ? receipt : null });
    // A matching journal receipt must never override authoritative invalidation.
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', event_cursor: 1, jobs: [{
      id: 'old', kind: 'snapshots', status: 'succeeded', stage: 'complete', workspace_id: 'default',
      inputs: { document_id: 'frozen-fixture', canonical_hash: hash }, result: receipt,
    }] });
    return base(url, init);
  });
  const view = mountEditor(fetcher);
  expect(await screen.findByRole('img', { name: 'table snapshot' })).toHaveAttribute('src', '/api/editor/artifacts/catalogue-table');
  const lookup = fetcher.mock.calls.find(([url]) => url.includes('/editor/previews/'));
  expect(lookup?.[0]).toContain(`/editor/previews/${hash}?view=isometric&resolution=1024&asset_views=`);
  expect(lookup?.[1]?.method).toBe('GET');
  hit = false;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh saved previews' }));
  await screen.findByText('No saved previews for these camera options.');
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  view.unmount(); hit = false; mountEditor(fetcher);
  await screen.findByText('No saved previews for these camera options.');
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it('switches asset/scene previews and submits frozen camera options without editing YAML', async () => {
  const base = editorServer();
  const hash = 'b'.repeat(64);
  let release: (() => void) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.includes('/editor/documents/')) return response({ ...(await (await base(url, init)).json()), validation: { ...validation, canonical_hash: hash } });
    if (url.includes('/editor/previews/')) return response({ status: 'miss', canonical_hash: hash, receipt: null });
    if (url.endsWith('/session/activity')) await new Promise<void>((resolve) => { release = resolve; });
    if (url.endsWith('/editor/snapshots')) return response({ id: 'render', kind: 'snapshots', workspace_id: 'default', status: 'queued', stage: 'queued', inputs: {} });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  fireEvent.change(screen.getByLabelText('Preview mode'), { target: { value: 'scene' } });
  expect(screen.queryByText('No saved preview', { exact: true })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'top' } });
  fireEvent.change(screen.getByLabelText('Image resolution'), { target: { value: '512' } });
  fireEvent.change(screen.getByLabelText('Preview mode'), { target: { value: 'assets' } });
  fireEvent.change(screen.getByLabelText('Camera for table'), { target: { value: 'front' } });
  fireEvent.click(screen.getByRole('button', { name: 'Render snapshots' }));
  await waitFor(() => expect(release).toBeDefined());
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'side' } });
  act(() => release!());
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/editor/snapshots'))).toBe(true));
  const request = fetcher.mock.calls.find(([url]) => url.endsWith('/editor/snapshots'))!;
  expect(JSON.parse(String(request[1]?.body))).toMatchObject({ yaml_text: 'env_name: real_document', document_id: 'frozen-fixture',
    options: { view: 'top', resolution: 512, asset_views: { table: 'front' } } });
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('env_name: real_document');
});

it.each(['historical-missing', 'historical-verified', 'hit-unverified', 'unknown-freshness'])('rejects inconsistent freshness %s rather than displaying it as current', async (failure) => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/editor/previews/')) return response({
      status: failure.startsWith('historical') ? 'historical' : 'hit', canonical_hash: validation.canonical_hash,
      receipt: { canonical_hash: validation.canonical_hash, options: { view: 'isometric', resolution: 1024, asset_views: {} },
        freshness: failure === 'historical-missing' ? undefined : failure === 'historical-verified' ? 'verified_assets'
          : failure === 'hit-unverified' ? 'unverified_assets' : 'unknown',
        assets: [{ id: 'table', artifact_id: 'unsafe', url: '/api/editor/artifacts/unsafe' }], scene: null, warnings: [],
      },
    });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByText(/Preview catalogue unavailable/);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it.each(['hash', 'options', 'malformed', 'network'])('fails closed for a %s catalogue response even with matching journal data', async (failure) => {
  const base = editorServer();
  const hash = validation.canonical_hash;
  const receipt = { canonical_hash: hash, cache_key: 'unsafe', options: { view: 'isometric', resolution: 1024, asset_views: {} },
    assets: [{ id: 'table', artifact_id: 'unsafe', url: '/api/editor/artifacts/unsafe' }], scene: null, warnings: [] };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/editor/previews/')) {
      if (failure === 'network') throw new TypeError('catalogue offline');
      return response({ status: 'hit', canonical_hash: hash, receipt: { ...receipt,
        ...(failure === 'hash' ? { canonical_hash: 'd'.repeat(64) } : failure === 'options' ? { options: { ...receipt.options, view: 'top' } } : { assets: [null] }),
      } });
    }
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', event_cursor: 1, jobs: [{
      id: 'old', kind: 'snapshots', status: 'succeeded', stage: 'complete', workspace_id: 'default',
      inputs: { canonical_hash: hash, document_id: 'frozen-fixture' }, result: { ...receipt, input_hash: 'hash' },
    }] });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByText(/Preview catalogue unavailable/);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});

it('does not queue another snapshot while a workspace render is already active', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', event_cursor: 1, jobs: [{
      id: 'other-tab-render', kind: 'snapshots', status: 'running', stage: 'rendering', workspace_id: 'default', inputs: {},
    }] });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeDisabled();
  expect(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' })).toBeDisabled();
});

it('revokes automatic preview consent when the session ends', async () => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url === '/api/session' && init?.method === 'DELETE') return new Response(null, { status: 204 });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' }));
  expect(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' })).toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: 'End session' }));
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' })).not.toBeChecked());
});

it('requires opt-in for automatic previews and cancels the accepted job through its existing route', async () => {
  const base = editorServer();
  const hash = 'c'.repeat(64);
  let status = 'queued';
  const job = () => ({ id: 'auto-render', kind: 'snapshots', workspace_id: 'default', status, stage: status, inputs: {} });
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { snapshots: true } });
    if (url.includes('/editor/documents/')) return response({ ...(await (await base(url, init)).json()), validation: { ...validation, canonical_hash: hash } });
    if (url.includes('/editor/previews/')) return response({ status: 'miss', canonical_hash: hash, receipt: null });
    if (url.endsWith('/jobs/auto-render/cancel')) { status = 'cancel_requested'; return response(job()); }
    if (url.endsWith('/editor/snapshots') || url.endsWith('/jobs/auto-render')) return response(job());
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const toggle = screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' });
  expect(toggle).not.toBeChecked();
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'front' } });
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(0);
  fireEvent.click(toggle);
  fireEvent.change(screen.getByLabelText('Scene camera'), { target: { value: 'top' } });
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(1), { timeout: 4000 });
  expect(screen.getByText(/1 \/ 3 automatic jobs used/)).toBeInTheDocument();
  fireEvent.click(await screen.findByRole('button', { name: 'Cancel snapshot render' }));
  await screen.findByText('Cancellation requested; waiting for worker acknowledgment.');
  const cancel = fetcher.mock.calls.find(([url]) => url.endsWith('/jobs/auto-render/cancel'))!;
  expect((cancel[1]?.headers as Record<string, string>)['X-CSRF-Token']).toBe('csrf');
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/auto-render')).length).toBeGreaterThan(0);
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
it('requires explicit discard before replacing a rejected generation reference', async () => {
  const base = editorServer();
  const key = 'arena:editor:generate:v1';
  const previous = { payload: { prompt: 'old prompt', credential_ref: 'expired-reference', idempotency_key: 'old-request' } };
  sessionStorage.setItem(key, JSON.stringify(previous));
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/model-settings') return response({ providers: PROVIDERS, configured: true, source: 'session',
      provider: 'openai', model: 'new-model', expires_at: 9999999999, credential_ref: 'replacement-reference', session_keys_allowed: true });
    if (url.endsWith('/editor/generate')) return response({ detail: 'Temporary credential unavailable' }, 409);
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const discard = await screen.findByRole('button', { name: 'Discard unresolved request' });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  try {
    fireEvent.click(discard);
    expect(JSON.parse(sessionStorage.getItem(key)!)).toEqual(previous);
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('may already have been accepted'));
    confirm.mockReturnValue(true);
    fireEvent.click(discard);
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))).toHaveLength(0);
    fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'new prompt' } });
    fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
    await screen.findByText('Temporary credential unavailable');
    const sent = JSON.parse(String(fetcher.mock.calls.find(([url]) => url.endsWith('/editor/generate'))![1]?.body));
    expect(sent.credential_ref).toBe('replacement-reference');
    expect(sent.idempotency_key).not.toBe('old-request');
    expect(sent.prompt).toBe('new prompt');
    expect(await screen.findByRole('button', { name: 'Discard unresolved request' })).toBeEnabled();
  } finally {
    confirm.mockRestore();
  }
});

it('uses session settings to enable generation and freezes the reference at click and ambiguous retry', async () => {
  const base = editorServer();
  let ref = 'public-ref-original';
  let release: (() => void) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/model-settings') return response({ providers: PROVIDERS, configured: true, source: 'session',
      provider: 'openai', model: 'user-model', expires_at: 9999999999, credential_ref: ref, session_keys_allowed: true });
    if (url.endsWith('/session/activity')) await new Promise<void>(resolve => { release = resolve; });
    if (url.endsWith('/editor/generate')) throw new TypeError('network lost');
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByText(/Temporary key active/);
  await screen.findByRole('button', { name: 'Inspect Table' });
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Make a scene' } });
  expect(screen.getByRole('button', { name: 'Generate spec' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await waitFor(() => expect(release).toBeDefined());
  ref = 'public-ref-rotated';
  fireEvent.click(screen.getByRole('button', { name: 'Refresh provider status' }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url === '/api/model-settings')).toHaveLength(2));
  act(() => release!());
  await screen.findByText('network lost');
  const original = fetcher.mock.calls.find(([url]) => url.endsWith('/editor/generate'))![1]?.body;
  expect(JSON.parse(String(original))).toMatchObject({ credential_ref: 'public-ref-original', prompt: 'Make a scene', base_yaml: 'env_name: real_document' });
  fireEvent.click(screen.getByRole('button', { name: 'Retry generation request' }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/session/activity'))).toHaveLength(2));
  act(() => release!());
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))).toHaveLength(2));
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))[1][1]?.body).toBe(original);
});

it.each(['unconfigured', 'expired', 'unavailable'])('does not trust stale editor capability when provider status is %s', async (state) => {
  const base = editorServer();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') return response({ ...(await (await base(url, init)).json()), capabilities: { generation: true } });
    if (url === '/api/model-settings') return state === 'unavailable' ? response({ detail: 'offline' }, 503)
      : response({ providers: PROVIDERS, configured: state !== 'unconfigured', source: state === 'expired' ? 'session' : 'none',
        provider: state === 'expired' ? 'openai' : null, model: state === 'expired' ? 'model' : null,
        expires_at: state === 'expired' ? 1 : null, credential_ref: state === 'expired' ? 'expired-ref' : null, session_keys_allowed: true });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  await screen.findByText(state === 'unavailable' ? /Provider settings unavailable/ : state === 'expired' ? /Temporary key expired/ : /No provider configured/);
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Make a scene' } });
  expect(screen.getByRole('button', { name: 'Generate spec' })).toBeDisabled();
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate'))).toHaveLength(0);
});

it('preserves unsaved YAML, prompt and graph when saving settings and never persists the password', async () => {
  const base = editorServer();
  let configured = false;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/model-settings') {
      if (init?.method === 'PUT') configured = true;
      return response({ providers: PROVIDERS, configured, source: configured ? 'session' : 'none', provider: configured ? 'gemini' : null,
        model: configured ? 'user-model' : null, credential_ref: configured ? 'public-ref' : null, expires_at: configured ? 9999999999 : null,
        session_keys_allowed: true });
    }
    return base(url, init);
  });
  const storage = vi.spyOn(Storage.prototype, 'setItem');
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  await screen.findByText(/No provider configured/);
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: unsaved_provider_test' } }));
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Keep my prompt' } });
  fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'gemini' } });
  fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'user-model' } });
  fireEvent.click(screen.getByRole('checkbox', { name: /I consent/ }));
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'dummy-editor-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save temporary key' }));
  await screen.findByText(/Temporary key active/);
  expect(screen.getByLabelText('API key')).toHaveValue('');
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Keep my prompt');
  expect(cm.state.doc.toString()).toBe('env_name: unsaved_provider_test');
  await screen.findByRole('button', { name: 'Inspect Table' });
  expect(JSON.stringify(storage.mock.calls)).not.toContain('dummy-editor-secret');
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
  storage.mockRestore();
});

it('freezes revision YAML and source identity at the click before asynchronous activity', async () => {
  const base = editorServer();
  let release: (() => void) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/session/activity')) await new Promise<void>((resolve) => { release = resolve; });
    if (url.endsWith('/editor/save')) return response({ revision_id: 'frozen', download_url: '/api/editor/revisions/frozen/download' });
    return base(url, init);
  });
  mountEditor(fetcher);
  await screen.findByRole('button', { name: 'Inspect Table' });
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => {
    fireEvent.click(screen.getByRole('button', { name: 'Save revision' }));
    cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: edited_after_click' } });
  });
  await waitFor(() => expect(release).toBeDefined());
  act(() => release!());
  await screen.findByRole('link', { name: 'Export flattened YAML' });
  const saved = JSON.parse(String(fetcher.mock.calls.find(([url]) => url.endsWith('/editor/save'))![1]?.body));
  expect(saved).toEqual({ yaml_text: 'env_name: real_document', document_id: 'frozen-fixture', expected_source_hash: 'hash' });
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
        canonical_hash: 'a'.repeat(64),
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
  let rendered = false;
  const receipt = { canonical_hash: validation.canonical_hash, cache_key: 'render', options: { view: 'isometric', resolution: 1024, asset_views: {} }, input_hash: 'hash',
    assets: [{ id: 'table', artifact_id: 'asset', url: '/api/editor/artifacts/asset' }],
    scene: { artifact_id: 'scene', url: '/api/editor/artifacts/scene' }, warnings: [] };
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/editor') {
      const data = await (await base(url, init)).json();
      return response({ ...data, capabilities: { ...data.capabilities, snapshots: true } });
    }
    if (url.includes('/editor/previews/')) return response({ status: rendered ? 'hit' : 'miss', canonical_hash: validation.canonical_hash, receipt: rendered ? receipt : null });
    if (url.endsWith('/editor/snapshots')) rendered = true;
    if (url.endsWith('/editor/snapshots') || url === '/api/jobs/render')
      return response({
        id: 'render',
        workspace_id: 'default',
        kind: 'snapshots',
        status: 'succeeded',
        stage: 'complete',
        inputs: { document_id: 'frozen-fixture', canonical_hash: 'a'.repeat(64), yaml_text: 'env_name: real_document' },
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
  fireEvent.change(screen.getByLabelText('Preview mode'), { target: { value: 'scene' } });
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
