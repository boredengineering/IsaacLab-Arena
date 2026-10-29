import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { EditorView as CodeMirrorView } from '@codemirror/view';
import { beforeEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { App } from './app';
import { ApiClient } from './api';
import type { Validation } from './editor-contracts';

const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const yaml = 'env_name: fixture';
const validation = (label: string): Validation => ({
  valid: true, source_hash: 'source', canonical_hash: 'a'.repeat(64), errors: [], warnings: [], spec: {}, summary: label,
  graph: { nodes: [{ id: 'object', label, role: 'object', properties: {} }], edges: [] },
  assets: [], relations: [], reified_relations: [], tasks: [],
});
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve };
}
function setup(override: (url: string, init?: RequestInit) => Response | Promise<Response> | undefined = () => undefined) {
  let sessionNumber = 0;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const custom = override(url, init);
    if (custom !== undefined) return custom;
    if (url.endsWith('/sessions')) return response({ session_id: `session-${++sessionNumber}`, csrf_token: `csrf-${sessionNumber}`, expires_at: 9999999999 });
    if (url.endsWith('/health')) return response({ capabilities: {} });
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', jobs: [], event_cursor: 0 });
    if (url === '/api/editor') return response({ default_document_id: 'fixture', documents: [
      { id: 'fixture', name: 'Fixture', source: 'fixture.yaml' }, { id: 'other', name: 'Other', source: 'other.yaml' },
    ], capabilities: { generation: false, snapshots: true }, limitations: [] });
    if (url.includes('/editor/documents/')) return response({ document_id: 'frozen-fixture', source: 'fixture.yaml', yaml_text: yaml, source_hash: 'source', validation: validation('Original graph') });
    if (url.endsWith('/editor/validate')) return response(validation('Current graph'));
    if (url.includes('/editor/previews/')) return response({ status: 'miss', canonical_hash: 'a'.repeat(64), receipt: null });
    return response({ detail: 'not installed' }, 404);
  });
  const api = new ApiClient(fetcher as typeof fetch);
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const view = render(<App api={api} cache={cache} history={createMemoryHistory({ initialEntries: ['/'] })} makePort={() => null} />);
  return { api, fetcher, cache, ...view };
}
function edit(text: string) {
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: text } }));
}
async function reconnect(api: ApiClient) {
  act(() => api.expire());
  expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Reconnect session' }));
  await waitFor(() => expect(api.session?.session_id).toBe('session-2'));
}
beforeEach(() => sessionStorage.clear());

it.each(['success', 'error'])('drops old-document validation %s while loading a different frozen source with identical YAML', async (outcome) => {
  const old = deferred();
  const next = deferred();
  const { fetcher } = setup((url) => {
    if (url.endsWith('/editor/validate')) return old.promise;
    if (url.endsWith('/editor/documents/other')) return next.promise;
    return undefined;
  });
  await screen.findByRole('button', { name: 'Inspect Original graph' });
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Preserve prompt on document change' } });
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/editor/validate'))).toBe(true));
  fireEvent.change(screen.getByLabelText('Document'), { target: { value: 'other' } });
  expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
  await act(async () => old.resolve(outcome === 'success' ? response(validation('Obsolete graph')) : response({ detail: 'Obsolete error' }, 400)));
  expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
  expect(screen.queryByText('Obsolete error')).not.toBeInTheDocument();
  await act(async () => next.resolve(response({ document_id: 'frozen-other', source: 'other.yaml', yaml_text: yaml,
    source_hash: 'different-includes', validation: validation('Other source graph') })));
  await screen.findByRole('button', { name: 'Inspect Other source graph' });
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent(yaml);
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Preserve prompt on document change');
  expect(screen.getByLabelText('Document')).toHaveValue('other');
});

it('does not restore cached validation into a replacement session on route remount or substitute a missing frozen source', async () => {
  const pending = deferred();
  const { api, fetcher } = setup((url) => url.endsWith('/editor/validate') ? pending.promise : undefined);
  await screen.findByRole('button', { name: 'Inspect Original graph' });
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Cached prompt' } });
  fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
  await screen.findByRole('heading', { name: 'Neo4j query' });
  await reconnect(api);
  fireEvent.click(screen.getByRole('link', { name: 'Environment editor' }));
  await screen.findByRole('textbox', { name: 'YAML editor' });
  expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/editor/validate'))).toBe(true));
  await act(async () => pending.resolve(response({ detail: 'Frozen source unavailable' }, 409)));
  await screen.findByText('Frozen source unavailable');
  expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent(yaml);
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Cached prompt');
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(1);
});

it.each(['success', 'error'])('drops a delayed old-session manual validation %s before the reconnect debounce', async (outcome) => {
  const old = deferred();
  const fresh = deferred();
  let requests = 0;
  const { api, fetcher, cache } = setup((url) => url.endsWith('/editor/validate') ? (++requests === 1 ? old.promise : fresh.promise) : undefined);
  await screen.findByRole('button', { name: 'Inspect Original graph' });
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
  await waitFor(() => expect(requests).toBe(1));
  await reconnect(api);
  await act(async () => old.resolve(outcome === 'success' ? response(validation('Obsolete graph')) : response({ detail: 'Obsolete error' }, 400)));
  expect(screen.queryByText('Obsolete error')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
  expect(cache.getQueryData<{ validation: { result: Validation } }>(['editor-draft'])?.validation.result.summary).toBe('Original graph');
  await waitFor(() => expect(requests).toBe(2));
  await act(async () => fresh.resolve(response(validation('Fresh graph'))));
  await screen.findByRole('button', { name: 'Inspect Fresh graph' });
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it('revalidates an explicitly applied durable result even when its YAML is unchanged', async () => {
  const job = { id: 'durable-generation', kind: 'generate', workspace_id: 'default', status: 'succeeded', stage: 'complete', inputs: {},
    result: { yaml_text: yaml, validation: validation('Old generated graph'), warnings: [], publication: 'not_published', traces: [] } };
  const retained = JSON.stringify({ payload: { idempotency_key: 'durable-key', base_yaml: yaml, prompt: 'Original prompt' }, job });
  sessionStorage.setItem('arena:editor:generate:v1', retained);
  const pending = deferred();
  let validations = 0;
  const { api, fetcher } = setup((url) => {
    if (url.endsWith('/jobs/durable-generation')) return response(job);
    if (url.endsWith('/editor/validate')) return ++validations === 1 ? response(validation('Current graph')) : pending.promise;
    return undefined;
  });
  await screen.findByRole('button', { name: 'Inspect Original graph' });
  await reconnect(api);
  await screen.findByRole('button', { name: 'Inspect Current graph' });
  fireEvent.click(screen.getByRole('button', { name: 'Apply generated YAML' }));
  expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled();
  await waitFor(() => expect(validations).toBe(2));
  await act(async () => pending.resolve(response(validation('Revalidated generated graph'))));
  await screen.findByRole('button', { name: 'Inspect Revalidated generated graph' });
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent(yaml);
  expect(sessionStorage.getItem('arena:editor:generate:v1')).toBe(retained);
  expect(fetcher.mock.calls.filter(([url]) => /generate$|snapshots|\/save$/.test(url))).toHaveLength(0);
});

it('rejects an HTTP document response that settles in the same turn as session expiry', async () => {
  const old = deferred();
  const { api, cache, fetcher } = setup((url) => url.includes('/editor/documents/') ? old.promise : undefined);
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('/editor/documents/'))).toBe(true));
  edit('env_name: retained_draft');
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Retained prompt' } });
  await act(async () => {
    api.expire();
    old.resolve(response({ document_id: 'obsolete-view', source: 'obsolete.yaml', yaml_text: yaml, source_hash: 'obsolete-source', validation: validation('Obsolete load') }));
  });
  expect(cache.getQueryData<{ document: unknown }>(['editor-draft'])?.document).toBeNull();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('env_name: retained_draft');
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Retained prompt');
  expect(screen.queryByRole('button', { name: /^Inspect / })).not.toBeInTheDocument();
});

it.each(['loaded source', 'validated draft'])('withholds unchanged %s after expiry until current-session validation, preserving its frozen source and prompt', async (kind) => {
  const pending = deferred();
  const text = kind === 'loaded source' ? yaml : 'env_name: unsaved_draft';
  let expired = false;
  const { api, fetcher } = setup((url) => url.endsWith('/editor/validate')
    ? expired ? pending.promise : response(validation('Original graph')) : undefined);
  await screen.findByRole('button', { name: 'Inspect Original graph' });
  if (kind === 'validated draft') {
    edit(text);
    fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
    await screen.findByRole('button', { name: 'Inspect Original graph' });
  }
  const previousRequests = fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate')).length;
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Keep this prompt' } });
  expired = true;
  await reconnect(api);
  expect(screen.queryByRole('button', { name: 'Inspect Original graph' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save revision' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeDisabled();
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate'))).toHaveLength(previousRequests + 1));
  const request = fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate')).at(-1)!;
  expect(JSON.parse(String(request[1]?.body))).toEqual({ yaml_text: text, document_id: 'frozen-fixture' });
  expect(request[1]?.headers).toMatchObject({ 'X-CSRF-Token': 'csrf-2' });
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(1);
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent(text);
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Keep this prompt');
  await act(async () => pending.resolve(response(validation('Reauthenticated graph'))));
  await screen.findByRole('button', { name: 'Inspect Reauthenticated graph' });
  expect(screen.getByRole('button', { name: 'Save revision' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeEnabled();
  expect(fetcher.mock.calls.filter(([url]) => /generate|snapshots|\/save$/.test(url))).toHaveLength(0);
});
