import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { EditorView } from '@codemirror/view';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { useRuntime } from './runtime';
import { Neo4jView, type Neo4jViewProps } from './neo4j';
import type { QueryResult } from './editor-contracts';

vi.mock('./runtime', () => ({ useRuntime: vi.fn() }));
const renderer = vi.hoisted(() => {
  let resolve!: (value: { default: () => React.ReactNode }) => void;
  const promise = new Promise<{ default: () => React.ReactNode }>(done => { resolve = done; });
  return { promise, resolve, mounts: vi.fn() };
});
vi.mock('./graph-explorer/graph-2d', () => ({ default: () => <p>Test 2D renderer</p> }));
vi.mock('./graph-explorer/graph-3d', () => renderer.promise);
const response = (value: unknown) => new Response(JSON.stringify(value));
const session = { session_id: 'session-1', csrf_token: 'csrf-1', expires_at: 9999999999 };
const queryText = 'MATCH (n) RETURN n.name LIMIT $limit';
const result: QueryResult = {
  columns: ['name', 'count', 'metadata'], rows: [['retained scalar', 7, { checked: true }]],
  elapsed_ms: 2, truncated: false, read_only: true,
  graph: { nodes: [{ id: 'node', label: 'Retained node', role: 'object', properties: {} }], edges: [] },
};
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>(done => { resolve = done; });
  return { promise, resolve };
}
function setup(initial: Neo4jViewProps = {}, override: (url: string, init?: RequestInit) => Response | Promise<Response> | undefined = () => undefined) {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const custom = override(url, init);
    if (custom !== undefined) return custom;
    if (url === '/api/graph/status') return response({ available: true, message: 'Available' });
    if (url === '/api/graph/examples') return response({ queries: [{ id: 'names', name: 'Names', query: queryText, params: { limit: 5 } }] });
    if (url === '/api/session/activity') return response(api.session);
    if (url === '/api/graph/query') return response(result);
    throw new Error(`Unexpected transport: ${url}`);
  });
  const api = new ApiClient(fetcher as typeof fetch);
  api.session = session;
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  let runtimeApi = api;
  function tree(props: Neo4jViewProps) {
    vi.mocked(useRuntime).mockReturnValue({ api: runtimeApi, session: runtimeApi.session, status: 'live', error: '', connecting: false,
      connect: async () => {}, refresh: async () => {}, revoke: async () => {} });
    return <QueryClientProvider client={cache}><Neo4jView {...props} /></QueryClientProvider>;
  }
  const view = render(tree(initial));
  return { api, fetcher, cache, ...view, rerender: (props: Neo4jViewProps) => view.rerender(tree(props)),
    remount: () => {
      view.rerender(<QueryClientProvider client={cache}>{null}</QueryClientProvider>);
      view.rerender(tree(initial));
    },
    replaceClient: (next: ApiClient, props: Neo4jViewProps = {}) => {
      runtimeApi = next;
      view.rerender(tree(props));
    },
    posts: () => fetcher.mock.calls.filter(([url, init]) => url === '/api/graph/query' && init?.method === 'POST') };
}
function pendingMetadataClient(status: ReturnType<typeof deferred>, examples: ReturnType<typeof deferred>) {
  const fetcher = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url === '/api/graph/status') return status.promise;
    if (url === '/api/graph/examples') return examples.promise;
    throw new Error(`Unexpected replacement transport: ${url}`);
  });
  const api = new ApiClient(fetcher as typeof fetch);
  api.session = { ...session };
  return { api, fetcher };
}
const freshMetadata = {
  status: { available: true, message: 'Replacement connection verified' },
  examples: { queries: [{ id: 'fresh', name: 'Fresh example', query: 'MATCH (fresh) RETURN fresh', params: { fresh: true } }] },
};
function editQuery(text: string) {
  const editor = EditorView.findFromDOM(screen.getByRole('textbox', { name: 'Cypher query' }))!;
  act(() => editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: text } }));
}
async function ready() {
  await waitFor(() => expect(screen.getByRole('button', { name: 'Run read-only query' })).toBeEnabled());
}
afterEach(() => vi.clearAllMocks());

it.each(['inactive', 'away-and-back', 'unmounted'])('retires pending activity consent when %s, without a query POST', async (transition) => {
  const activity = deferred();
  const view = setup({}, url => url === '/api/session/activity' ? activity.promise : undefined);
  await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Run read-only query' }));
  await waitFor(() => expect(view.fetcher.mock.calls.some(([url]) => url === '/api/session/activity')).toBe(true));
  if (transition === 'unmounted') view.unmount();
  else {
    view.rerender({ active: false });
    if (transition === 'away-and-back') view.rerender({ active: true });
  }
  await act(async () => { activity.resolve(response(session)); });
  expect(view.posts()).toHaveLength(0);
  if (transition !== 'unmounted') {
    view.rerender({ active: true });
    await ready();
    expect(view.posts()).toHaveLength(0);
  }
});

it.each(['before-click', 'before-mutation', 'pending-activity', 'pending-result', 'settled-result'])('withholds reused-session-ID authorization at %s', async (stage) => {
  const pending = deferred();
  const view = setup({}, url =>
    (stage === 'pending-activity' && url === '/api/session/activity') ||
    (stage === 'pending-result' && url === '/api/graph/query') ? pending.promise : undefined);
  await ready();
  const replace = () => { view.api.session = { ...session }; };
  if (stage === 'before-click') replace(); // Runtime has not rendered the replacement yet.
  act(() => {
    fireEvent.click(screen.getByRole('button', { name: 'Run read-only query' }));
    if (stage === 'before-mutation') replace();
  });
  if (stage === 'pending-activity') {
    await waitFor(() => expect(view.fetcher.mock.calls.some(([url]) => url === '/api/session/activity')).toBe(true));
    replace();
    await act(async () => pending.resolve(response(session)));
  } else if (stage === 'pending-result') {
    await waitFor(() => expect(view.posts()).toHaveLength(1));
    replace();
    await act(async () => pending.resolve(response(result)));
  } else if (stage === 'settled-result') {
    await screen.findByText('retained scalar');
    replace();
  }
  await act(async () => {});
  view.rerender({ active: false });
  view.rerender({ active: true });
  await ready();
  expect(screen.queryByText('retained scalar')).not.toBeInTheDocument();
  if (stage === 'settled-result') expect(screen.getByText(/Previous result withheld/)).toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: 'Cypher query' })).toHaveTextContent(queryText);
  expect(view.posts()).toHaveLength(stage === 'pending-result' || stage === 'settled-result' ? 1 : 0);
  if (stage === 'before-click' || stage === 'before-mutation')
    expect(view.fetcher.mock.calls.filter(([url]) => url === '/api/session/activity')).toHaveLength(0);
});

it('pauses a late lazy renderer off-route without losing graph controller intent or scalar rows', async () => {
  const view = setup({ graphRenderer: 'explorer' });
  await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Run read-only query' }));
  await screen.findByText('retained scalar');
  fireEvent.click(screen.getByRole('tab', { name: 'Graph' }));
  const search = await screen.findByLabelText('Search returned graph');
  fireEvent.change(search, { target: { value: 'Retained' } });
  fireEvent.click(screen.getByRole('tab', { name: '3D' }));
  await screen.findByText(/Loading 3D renderer/);
  view.rerender({ active: false, graphRenderer: 'explorer' });
  await act(async () => {
    renderer.resolve({ default: () => { renderer.mounts(); return <p>Test 3D renderer</p>; } });
    await renderer.promise;
  });
  expect(renderer.mounts).not.toHaveBeenCalled();
  expect(screen.queryByLabelText('Search returned graph')).not.toBeInTheDocument();
  view.rerender({ active: true, graphRenderer: 'explorer' });
  await screen.findByText('Test 3D renderer');
  expect(screen.getByLabelText('Search returned graph')).toHaveValue('Retained');
  expect(screen.getByRole('tab', { name: '3D' })).toHaveAttribute('aria-selected', 'true');
  view.rerender({ active: false, graphRenderer: 'explorer' });
  expect(screen.queryByText('Test 3D renderer')).not.toBeInTheDocument();
  view.rerender({ active: true, graphRenderer: 'explorer' });
  const rawTabs = screen.getByRole('tablist', { name: 'Query result format' });
  fireEvent.click(rawTabs.querySelector('button')!);
  expect(screen.getByText('retained scalar')).toBeInTheDocument();
  expect(screen.getByText('7')).toBeInTheDocument();
  expect(view.posts()).toHaveLength(1);
});

it('freezes exact submitted text, JSON text and example label while a newer draft stays retained', async () => {
  const activity = deferred();
  const view = setup({}, url => url === '/api/session/activity' ? activity.promise : undefined);
  await ready();
  const submittedParams = ' { "limit": 5 }\n';
  fireEvent.change(screen.getByLabelText('Parameters (JSON object)'), { target: { value: submittedParams } });
  act(() => {
    fireEvent.click(screen.getByRole('button', { name: 'Run read-only query' }));
    editQuery('MATCH (other) RETURN other');
    fireEvent.change(screen.getByLabelText('Parameters (JSON object)'), { target: { value: '{not-json' } });
  });
  await waitFor(() => expect(view.fetcher.mock.calls.some(([url]) => url === '/api/session/activity')).toBe(true));
  await act(async () => activity.resolve(response(session)));
  await screen.findByText('retained scalar');
  expect(JSON.parse(String(view.posts()[0][1]?.body))).toEqual({ query: queryText, params: { limit: 5 } });
  expect(view.posts()[0][1]?.headers).toMatchObject({ 'X-CSRF-Token': session.csrf_token });
  expect(screen.getByText(/Previous query result/)).toBeInTheDocument();
  expect(screen.getByText('Submitted query · Names')).toBeInTheDocument();
  expect(screen.getByLabelText('Submitted Cypher query').textContent).toBe(queryText);
  expect(screen.getByLabelText('Submitted parameters').textContent).toBe(submittedParams);
  view.rerender({ active: false });
  view.rerender({ active: true });
  expect(screen.getByRole('textbox', { name: 'Cypher query' })).toHaveTextContent('MATCH (other) RETURN other');
  expect(screen.getByLabelText('Parameters (JSON object)')).toHaveValue('{not-json');
  expect(screen.getByText('retained scalar')).toBeInTheDocument();
  expect(screen.getByText('Submitted query · Names')).toBeInTheDocument();
  expect(view.posts()).toHaveLength(1);
});

it('does not revive example initialization when a deliberately empty draft returns', async () => {
  const view = setup();
  await ready();
  editQuery('');
  fireEvent.change(screen.getByLabelText('Parameters (JSON object)'), { target: { value: ' { "retained": true } ' } });
  view.rerender({ active: false });
  view.rerender({ active: true });
  await act(async () => {});
  expect(screen.getByRole('textbox', { name: 'Cypher query' }).textContent).toBe('');
  expect(screen.getByLabelText('Parameters (JSON object)')).toHaveValue(' { "retained": true } ');
  expect(view.posts()).toHaveLength(0);
});

it('does not overwrite parameters edited before delayed examples arrive, including while inactive', async () => {
  const examples = deferred();
  const view = setup({}, url => url === '/api/graph/examples' ? examples.promise : undefined);
  fireEvent.change(screen.getByLabelText('Parameters (JSON object)'), { target: { value: '{"mine":true}' } });
  view.rerender({ active: false });
  await act(async () => examples.resolve(response({ queries: [{ id: 'late', name: 'Late', query: queryText, params: {} }] })));
  expect(screen.getByRole('textbox', { name: 'Cypher query' }).textContent).toBe('');
  view.rerender({ active: true });
  await act(async () => {});
  expect(screen.getByLabelText('Parameters (JSON object)')).toHaveValue('{"mine":true}');
  expect(screen.getByRole('textbox', { name: 'Cypher query' }).textContent).toBe('');
  expect(view.posts()).toHaveLength(0);
});

it('requires fresh connection metadata after same-ID session replacement', async () => {
  const status = deferred();
  let replaced = false;
  const view = setup({}, url => replaced && url === '/api/graph/status' ? status.promise : undefined);
  await ready();
  replaced = true;
  view.api.session = { ...session };
  view.rerender({ active: true });
  expect(screen.getByRole('button', { name: 'Run read-only query' })).toBeDisabled();
  await act(async () => status.resolve(response({ available: true, message: 'New session verified' })));
  await ready();
  expect(screen.getByText('New session verified')).toBeInTheDocument();
  expect(view.posts()).toHaveLength(0);
});

it.each(['inactive', 'replacement', 'settled-replacement'])('withholds retired query error details after %s', async (transition) => {
  const pending = deferred();
  const view = setup({}, url => url === '/api/graph/query' ? pending.promise : undefined);
  await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Run read-only query' }));
  await waitFor(() => expect(view.posts()).toHaveLength(1));
  if (transition === 'inactive') view.rerender({ active: false });
  if (transition === 'replacement') view.api.session = { ...session };
  await act(async () => pending.resolve(new Response(JSON.stringify({ detail: 'Retired private query detail' }), { status: 400 })));
  if (transition === 'settled-replacement') {
    await screen.findByText('Retired private query detail');
    view.api.session = { ...session };
  }
  view.rerender({ active: true });
  await ready();
  expect(screen.queryByText('Retired private query detail')).not.toBeInTheDocument();
  expect(view.posts()).toHaveLength(1);
});

it('does no initial work while inactive and never POSTs from active navigation alone', async () => {
  const view = setup({ active: false });
  await act(async () => {});
  expect(view.fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole('main')).not.toHaveAttribute('id', 'workspace');
  expect(screen.getByRole('button', { name: 'Run read-only query' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Check connection' })).toBeDisabled();
  expect(screen.getByRole('textbox', { name: 'Cypher query' })).toHaveTextContent('');
  view.rerender({ active: true });
  await ready();
  expect(screen.getByRole('main')).toHaveAttribute('id', 'workspace');
  view.rerender({ active: false });
  const calls = view.fetcher.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: 'Check connection' }));
  await act(async () => { await view.cache.invalidateQueries(); });
  expect(view.fetcher).toHaveBeenCalledTimes(calls);
  view.rerender({ active: true });
  await ready();
  expect(view.posts()).toHaveLength(0);
});

it('withholds cached status and examples for a different client with the same ID and generation', async () => {
  const view = setup();
  await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Run read-only query' }));
  await screen.findByText('retained scalar');
  const status = deferred();
  const examples = deferred();
  const replacement = pendingMetadataClient(status, examples);
  expect(replacement.api.sessionGeneration).toBe(view.api.sessionGeneration);
  expect(replacement.api.session?.session_id).toBe(view.api.session?.session_id);
  view.replaceClient(replacement.api);
  // Capture the synchronous render, before any replacement metadata can arrive.
  const disabledBeforeFresh = (screen.getByRole('button', { name: 'Run read-only query' }) as HTMLButtonElement).disabled;
  const oldStatusBeforeFresh = screen.queryByText('Available');
  const oldExampleBeforeFresh = screen.queryByRole('option', { name: 'Names' });
  const oldResultBeforeFresh = screen.queryByText('retained scalar');
  await act(async () => {
    status.resolve(response(freshMetadata.status));
    examples.resolve(response(freshMetadata.examples));
  });
  expect(disabledBeforeFresh).toBe(true);
  expect(oldStatusBeforeFresh).toBeNull();
  expect(oldExampleBeforeFresh).toBeNull();
  expect(oldResultBeforeFresh).toBeNull();
  await screen.findByText(freshMetadata.status.message);
  await ready();
  expect(screen.getByRole('textbox', { name: 'Cypher query' })).toHaveTextContent(queryText);
  expect(screen.getByLabelText('Parameters (JSON object)')).toHaveValue(JSON.stringify({ limit: 5 }, null, 2));
  expect(view.posts()).toHaveLength(1);
  expect(replacement.fetcher.mock.calls.some(([url]) => url === '/api/graph/query' || url === '/api/session/activity')).toBe(false);
});

it.each(['client', 'same-ID generation'])('rejects pending metadata from the retired %s before it enters the cache', async transition => {
  const oldStatus = deferred();
  const oldExamples = deferred();
  const status = deferred();
  const examples = deferred();
  let replaced = false;
  const view = setup({}, url => {
    if (url === '/api/graph/status') return replaced ? status.promise : oldStatus.promise;
    if (url === '/api/graph/examples') return replaced ? examples.promise : oldExamples.promise;
    return undefined;
  });
  await waitFor(() => expect(view.fetcher).toHaveBeenCalledTimes(2));
  const retiredQueries = view.cache.getQueryCache().getAll();
  const replacement = pendingMetadataClient(status, examples);
  if (transition === 'client') view.replaceClient(replacement.api);
  else {
    replaced = true;
    view.api.session = { ...session };
    view.rerender({});
  }
  await act(async () => {
    oldStatus.resolve(response({ available: true, message: 'Retired connection metadata' }));
    oldExamples.resolve(response({ queries: [{ id: 'retired', name: 'Retired example', query: queryText, params: { old: true } }] }));
  });
  await waitFor(() => expect(retiredQueries.every(query => query.state.fetchStatus === 'idle')).toBe(true));
  const retiredData = retiredQueries.map(query => query.state.data);
  const disabledBeforeFresh = (screen.getByRole('button', { name: 'Run read-only query' }) as HTMLButtonElement).disabled;
  const textBeforeFresh = screen.getByRole('textbox', { name: 'Cypher query' }).textContent;
  const retiredOptionBeforeFresh = screen.queryByRole('option', { name: 'Retired example' });
  const retiredStatusBeforeFresh = screen.queryByText('Retired connection metadata');
  await act(async () => {
    status.resolve(response(freshMetadata.status));
    examples.resolve(response(freshMetadata.examples));
  });
  expect(retiredData).toEqual([undefined, undefined]);
  expect(disabledBeforeFresh).toBe(true);
  expect(textBeforeFresh).toBe('');
  expect(retiredOptionBeforeFresh).toBeNull();
  expect(retiredStatusBeforeFresh).toBeNull();
  await screen.findByText(freshMetadata.status.message);
  await ready();
  expect(screen.getByRole('textbox', { name: 'Cypher query' })).toHaveTextContent(freshMetadata.examples.queries[0].query);
  expect(view.posts()).toHaveLength(0);
  expect(replacement.fetcher.mock.calls.some(([url]) => url === '/api/graph/query' || url === '/api/session/activity')).toBe(false);
});

it.each(['client', 'same-ID generation'])('preserves a deliberately empty user draft across %s metadata replacement', async transition => {
  const oldExamples = deferred();
  const status = deferred();
  const examples = deferred();
  let replaced = false;
  const view = setup({}, url => {
    if (url === '/api/graph/examples') return replaced ? examples.promise : oldExamples.promise;
    if (replaced && url === '/api/graph/status') return status.promise;
    return undefined;
  });
  await screen.findByText('Available');
  editQuery('MATCH (mine) RETURN mine');
  editQuery('');
  const draftParams = ' { "mine": true }\n';
  fireEvent.change(screen.getByLabelText('Parameters (JSON object)'), { target: { value: draftParams } });
  const replacement = pendingMetadataClient(status, examples);
  if (transition === 'client') view.replaceClient(replacement.api);
  else {
    replaced = true;
    view.api.session = { ...session };
    view.rerender({});
  }
  await act(async () => oldExamples.resolve(response({ queries: [{ id: 'old', name: 'Old example', query: queryText, params: {} }] })));
  const textAfterOld = screen.getByRole('textbox', { name: 'Cypher query' }).textContent;
  const paramsAfterOld = (screen.getByLabelText('Parameters (JSON object)') as HTMLTextAreaElement).value;
  await act(async () => {
    status.resolve(response(freshMetadata.status));
    examples.resolve(response(freshMetadata.examples));
  });
  await screen.findByRole('option', { name: 'Fresh example' });
  view.rerender({ active: false });
  view.rerender({ active: true });
  expect(textAfterOld).toBe('');
  expect(paramsAfterOld).toBe(draftParams);
  expect(screen.getByRole('textbox', { name: 'Cypher query' }).textContent).toBe('');
  expect(screen.getByLabelText('Parameters (JSON object)')).toHaveValue(draftParams);
  expect(screen.queryByRole('option', { name: 'Old example' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Run read-only query' })).toBeDisabled();
  expect(view.posts()).toHaveLength(0);
  expect(replacement.fetcher.mock.calls.some(([url]) => url === '/api/graph/query' || url === '/api/session/activity')).toBe(false);
});

it('accepts pending metadata after ordinary activity updates the session deadline', async () => {
  const status = deferred();
  const examples = deferred();
  const view = setup({}, url => {
    if (url === '/api/graph/status') return status.promise;
    if (url === '/api/graph/examples') return examples.promise;
    return undefined;
  });
  await waitFor(() => expect(view.fetcher).toHaveBeenCalledTimes(2));
  const generation = view.api.sessionGeneration;
  const queries = view.cache.getQueryCache().getAll();
  await act(async () => { await view.api.activity(); });
  view.rerender({});
  await act(async () => {
    status.resolve(response(freshMetadata.status));
    examples.resolve(response(freshMetadata.examples));
  });
  await ready();
  expect(view.api.sessionGeneration).toBe(generation);
  expect(view.cache.getQueryCache().getAll()).toEqual(queries);
  expect(view.fetcher.mock.calls.filter(([url]) => url === '/api/graph/status' || url === '/api/graph/examples')).toHaveLength(2);
  expect(screen.getByText(freshMetadata.status.message)).toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: 'Cypher query' })).toHaveTextContent(freshMetadata.examples.queries[0].query);
  expect(view.posts()).toHaveLength(0);
});

it('keeps metadata ownership and frozen results across ordinary activity and no-op renders', async () => {
  const view = setup();
  await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Run read-only query' }));
  await screen.findByText('retained scalar');
  const queries = view.cache.getQueryCache().getAll();
  const generation = view.api.sessionGeneration;
  const currentSession = view.api.session;
  const metadataCalls = () => view.fetcher.mock.calls.filter(([url]) => url === '/api/graph/status' || url === '/api/graph/examples');
  const callCount = metadataCalls().length;
  editQuery('MATCH (draft) RETURN draft');
  await act(async () => { await view.api.activity(); });
  expect(view.api.session).not.toBe(currentSession);
  expect(view.api.sessionGeneration).toBe(generation);
  view.rerender({});
  view.rerender({});
  await act(async () => {});
  expect(view.cache.getQueryCache().getAll()).toEqual(queries);
  expect(metadataCalls()).toHaveLength(callCount);
  expect(screen.getByText('Available')).toBeInTheDocument();
  expect(screen.getByRole('option', { name: 'Names' })).toBeInTheDocument();
  expect(screen.getByText('retained scalar')).toBeInTheDocument();
  expect(screen.getByLabelText('Submitted Cypher query').textContent).toBe(queryText);
  expect(screen.getByText('Submitted query · Names')).toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: 'Cypher query' })).toHaveTextContent('MATCH (draft) RETURN draft');
  expect(view.posts()).toHaveLength(1);
});

it('keeps opaque metadata keys stable across same-client remounts', async () => {
  const view = setup();
  await ready();
  const keys = view.cache.getQueryCache().getAll().map(query => query.queryKey);
  expect(keys).toHaveLength(2);
  for (const key of keys) {
    expect(key.every(part => typeof part === 'string' || typeof part === 'number')).toBe(true);
    expect(JSON.stringify(key)).not.toContain(session.csrf_token);
  }
  view.remount();
  await ready();
  expect(view.cache.getQueryCache().getAll().map(query => query.queryKey)).toEqual(keys);
  expect(view.posts()).toHaveLength(0);
});

it.each([200, 503])('rejects retired metadata before React observes session replacement (HTTP %s)', async httpStatus => {
  const oldStatus = deferred();
  const oldExamples = deferred();
  const status = deferred();
  const examples = deferred();
  let replaced = false;
  const view = setup({}, url => {
    if (url === '/api/graph/status') return replaced ? status.promise : oldStatus.promise;
    if (url === '/api/graph/examples') return replaced ? examples.promise : oldExamples.promise;
    return undefined;
  });
  await waitFor(() => expect(view.fetcher).toHaveBeenCalledTimes(2));
  const retiredQueries = view.cache.getQueryCache().getAll();
  replaced = true;
  view.api.session = { ...session };
  // Do not rerender: cancellation on observer replacement cannot cover this gap.
  await act(async () => {
    oldStatus.resolve(new Response(JSON.stringify(httpStatus === 200
      ? { available: true, message: 'Retired private metadata' }
      : { detail: 'Retired private metadata' }), { status: httpStatus }));
    oldExamples.resolve(new Response(JSON.stringify(httpStatus === 200
      ? { queries: [{ id: 'retired', name: 'Retired private metadata', query: queryText, params: {} }] }
      : { detail: 'Retired private metadata' }), { status: httpStatus }));
  });
  await waitFor(() => expect(retiredQueries.every(query => query.state.fetchStatus === 'idle')).toBe(true));
  expect(retiredQueries.map(query => query.state.data)).toEqual([undefined, undefined]);
  expect(retiredQueries.map(query => query.state.error?.message).join(' ')).not.toContain('Retired private metadata');
  view.rerender({});
  expect(screen.getByRole('button', { name: 'Run read-only query' })).toBeDisabled();
  expect(screen.getByRole('textbox', { name: 'Cypher query' }).textContent).toBe('');
  await act(async () => {
    status.resolve(response(freshMetadata.status));
    examples.resolve(response(freshMetadata.examples));
  });
  await ready();
  expect(screen.getByText(freshMetadata.status.message)).toBeInTheDocument();
  expect(view.posts()).toHaveLength(0);
});
