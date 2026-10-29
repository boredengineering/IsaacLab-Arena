import { useLayoutEffect } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { workspaceKey } from './cache';
import { defaultRenderOptions, SnapshotControls, SnapshotGallery, useSnapshots } from './snapshots';
import type { RenderOptions } from './editor-contracts';

// Real ApiClient/React Query/controllers; only HTTP transport is synthetic.
const mocks = vi.hoisted(() => ({ runtime: {} as any }));
vi.mock('./runtime', () => ({ useRuntime: () => mocks.runtime }));
const hash = 'a'.repeat(64);
const session = { session_id: 's1', csrf_token: 'csrf', expires_at: 9999999999 };
const response = (value: unknown) => new Response(JSON.stringify(value));
const receipt = { canonical_hash: hash, cache_key: 'cache-not-a-job', options: defaultRenderOptions,
  assets: [], scene: { artifact_id: 'pixels', url: '/api/editor/artifacts/pixels' }, warnings: [], freshness: 'unverified_assets' };
const hit = { status: 'historical', canonical_hash: hash, receipt };
let cache: QueryClient;
let snapshots: ReturnType<typeof useSnapshots>;
let commits: { canonical: string | null; fetching: boolean }[];
function Harness({ canonical = hash, documentId = 'doc', options = defaultRenderOptions, active = true, draft = 'draft' }: {
  canonical?: string | null; documentId?: string; options?: RenderOptions; active?: boolean; draft?: string;
}) {
  snapshots = useSnapshots(canonical, documentId, options, active);
  useLayoutEffect(() => { commits.push({ canonical, fetching: snapshots.lookup.isFetching }); });
  return <><SnapshotControls snapshots={snapshots} draft={draft} documentId={documentId} enabled={!!canonical} />
    <SnapshotGallery snapshots={snapshots} canonicalHash={canonical} /></>;
}
function setup(transport: (url: string, init?: RequestInit) => Promise<Response> = async () => response(hit)) {
  const fetcher = vi.fn(transport);
  const api = new ApiClient(fetcher as typeof fetch); api.session = session;
  mocks.runtime = { api, session: api.session, refresh: vi.fn(async () => {}) };
  const tree = (props: Parameters<typeof Harness>[0] = {}) => <QueryClientProvider client={cache}><Harness {...props} /></QueryClientProvider>;
  const view = render(tree());
  return { api, fetcher, view, rerender: (props: Parameters<typeof Harness>[0]) => view.rerender(tree(props)) };
}
beforeEach(() => { commits = []; sessionStorage.clear(); cache = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); });

it.each(['committed-refetch', 'same-act-refetch', 'same-act-invalidate'] as const)(
  'retires retained pixels before invalid validation after %s', async mode => {
    let release!: (value: Response) => void;
    const view = setup();
    await screen.findByRole('img', { name: /scene snapshot/ });
    expect(snapshots.history[0].receiptId).toBe('cache-not-a-job');
    view.fetcher.mockImplementation(() => new Promise(resolve => { release = resolve; }));
    commits = [];
    const start = () => mode === 'same-act-invalidate'
      ? cache.invalidateQueries({ queryKey: ['preview-catalogue'], refetchType: 'none' })
      : snapshots.lookup.refetch();
    if (mode === 'committed-refetch') {
      act(() => { void start(); });
      await waitFor(() => expect(snapshots.lookup.isFetching).toBe(true));
      expect(screen.queryByRole('img')).not.toBeInTheDocument();
      view.rerender({ canonical: null, draft: 'invalid' });
    } else {
      act(() => { void start(); view.rerender({ canonical: null, draft: 'invalid' }); });
      expect(commits.some(commit => commit.canonical === hash && commit.fetching)).toBe(false);
    }
    expect(snapshots.history).toEqual([]);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    if (release) await act(async () => release(response(hit)));
    expect(snapshots.history).toEqual([]);
    expect(view.fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
  },
);

it.each(['cancel-success', 'cancel-error', 'error', 'invalidate-only'] as const)(
  'does not reacquire the previous query receipt after %s', async mode => {
    const view = setup();
    await screen.findByRole('img', { name: /scene snapshot/ });
    let release!: (value: Response) => void;
    view.fetcher.mockImplementation(() => new Promise(resolve => { release = resolve; }));
    if (mode === 'invalidate-only') {
      await act(async () => { await cache.invalidateQueries({ queryKey: ['preview-catalogue'], refetchType: 'none' }); });
    } else {
      act(() => { void snapshots.lookup.refetch(); });
      await waitFor(() => expect(snapshots.lookup.isFetching).toBe(true));
      if (mode.startsWith('cancel')) await act(async () => { await cache.cancelQueries({ queryKey: ['preview-catalogue'] }); });
      await act(async () => release(mode === 'cancel-success' ? response(hit) : new Response('unavailable', { status: 503 })));
    }
    // Keep the canonical hash first: cancellation reverts Query's old data.
    view.rerender({});
    expect(snapshots.history).toEqual([]);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    view.rerender({ canonical: null, draft: 'invalid' });
    expect(snapshots.history).toEqual([]);
    expect(view.fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
  },
);

const queryReplacements = ['accepted-job', 'status', 'canonical', 'options'] as const;
async function startReplacement(mode: typeof queryReplacements[number]) {
  const queued = { id: 'rollover-job', workspace_id: 'default', kind: 'snapshots', status: 'queued', stage: 'queued',
    inputs: { yaml_text: 'draft', document_id: 'doc', options: defaultRenderOptions }, result: null,
    created_at: 1, updated_at: 1, error: null, created_by_session_id: 's1' };
  if (mode === 'status') sessionStorage.setItem('arena:editor:snapshots:v1', JSON.stringify({
    payload: { ...queued.inputs, idempotency_key: 'retained-request' }, job: queued,
  }));
  const pending: { url: string; release: (value: Response) => void }[] = [];
  let defer = false;
  const view = setup(async url => {
    if (url.endsWith('/session/activity')) return response(session);
    if (url.endsWith('/editor/snapshots') || url.endsWith('/jobs/rollover-job')) return response(queued);
    if (defer) return new Promise(resolve => { pending.push({ url, release: resolve }); });
    return response(hit);
  });
  await screen.findByRole('img', { name: /scene snapshot/ });
  const original = cache.getQueryCache().find({ queryKey: ['preview-catalogue'], exact: false })!;
  expect(original).toBeDefined();
  defer = true;
  if (mode === 'accepted-job') fireEvent.click(screen.getByRole('button', { name: 'Render snapshots' }));
  else if (mode === 'status') act(() => { cache.setQueryData(workspaceKey, { jobs: [{ ...queued, status: 'running', stage: 'rendering' }] }); });
  else view.rerender(mode === 'canonical' ? { canonical: 'b'.repeat(64) } : { options: { ...defaultRenderOptions, view: 'top' } });
  await waitFor(() => expect(pending).toHaveLength(1));
  const replacement = cache.getQueryCache().findAll({ queryKey: ['preview-catalogue'] }).find(query => query.state.fetchStatus === 'fetching')!;
  expect(replacement).toBeDefined();
  expect(replacement).not.toBe(original);
  expect(replacement.queryKey.slice(0, 3)).toEqual(original.queryKey.slice(0, 3));
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  return { view, queued, pending, original, replacement };
}
function catalogueResponse(url: string, key: string, fresh = false) {
  const request = new URL(url, 'http://local.test');
  const canonical = request.pathname.split('/editor/previews/')[1];
  return response({ status: fresh ? 'hit' : 'historical', canonical_hash: canonical,
    receipt: { ...receipt, cache_key: key, canonical_hash: canonical, freshness: fresh ? 'verified_assets' : 'unverified_assets',
      options: { view: request.searchParams.get('view'), resolution: Number(request.searchParams.get('resolution')),
        asset_views: JSON.parse(request.searchParams.get('asset_views')!) } } });
}
it.each(queryReplacements)('retires completed authority when %s starts a replacement catalogue before invalid validation', async mode => {
  const { view, pending, replacement } = await startReplacement(mode);
  // Returning to original options while validation is invalid must not revive A.
  view.rerender({ canonical: null, draft: 'invalid' });
  expect(snapshots.history).toEqual([]);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  await act(async () => pending[0].release(catalogueResponse(pending[0].url, 'retired-replacement')));
  expect(replacement.state.dataUpdateCount).toBe(0);
  expect(snapshots.history).toEqual([]);
  expect(view.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(mode === 'accepted-job' ? 1 : 0);
});

it.each(queryReplacements.flatMap(mode => (['cancel-invalid', 'ABA-invalid'] as const)
  .filter(retirement => retirement !== 'ABA-invalid' || mode !== 'accepted-job')
  .flatMap(retirement => (['before', 'after'] as const).flatMap(order =>
    (['success', 'error'] as const).map(outcome => ({ mode, retirement, order, outcome }))))))(
  '$mode replacement $retirement rejects late $outcome $order fresh verification', async ({ mode, retirement, order, outcome }) => {
    const { view, queued, pending, original, replacement } = await startReplacement(mode);
    if (retirement === 'cancel-invalid') {
      await act(async () => { await cache.cancelQueries({ queryKey: ['preview-catalogue'] }); });
    } else {
      if (mode === 'status') act(() => { cache.setQueryData(workspaceKey, { jobs: [queued] }); });
      else view.rerender({});
      await waitFor(() => expect(pending).toHaveLength(2));
    }
    view.rerender({ canonical: null, draft: 'invalid' });
    expect(snapshots.history).toEqual([]);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    // Let gcTime: 0 dispose B so the next successful read owns a new object.
    await waitFor(() => expect(cache.getQueryCache().get(replacement.queryHash)).not.toBe(replacement));
    const abandoned = [...pending];
    const publications = vi.fn();
    const unsubscribe = cache.getQueryCache().subscribe(event => {
      if (event.query === replacement && event.type === 'updated' && event.action.type === 'success') publications();
    });
    const settleOld = async () => {
      await act(async () => { for (const request of abandoned) request.release(outcome === 'success'
        ? catalogueResponse(request.url, 'retired-replacement') : new Response('unavailable', { status: 503 })); });
    };
    try {
      if (order === 'before') { await settleOld(); expect(snapshots.history).toEqual([]); }
      view.rerender({});
      await waitFor(() => expect(pending).toHaveLength(abandoned.length + 1));
      expect(snapshots.history).toEqual([]);
      const fresh = pending[abandoned.length];
      await act(async () => fresh.release(catalogueResponse(fresh.url, 'fresh-verification', true)));
      await screen.findByRole('img', { name: 'scene snapshot fresh-verification' });
      if (order === 'after') await settleOld();
      expect(publications).not.toHaveBeenCalled();
      expect(replacement.state.dataUpdateCount).toBe(0);
      expect(snapshots.history.map(value => value.receiptId)).toEqual(['fresh-verification']);
      // Removed same-key objects must not revoke their fresh ABA replacements.
      act(() => { original.invalidate(); replacement.invalidate(); view.rerender({ canonical: null }); });
      expect(snapshots.history.map(value => value.receiptId)).toEqual(['fresh-verification']);
      expect(screen.queryByText(/Historical preview · asset freshness unverified/)).not.toBeInTheDocument();
      expect(screen.getByText(/Stale · draft changed since this render/)).toBeInTheDocument();
      expect(view.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(mode === 'accepted-job' ? 1 : 0);
    } finally { unsubscribe(); }
  },
);

it.each(['canonical', 'options'] as const)('retires history when adopting an already-fetching %s query', async mode => {
  const view = setup();
  await screen.findByRole('img', { name: /scene snapshot/ });
  const original = cache.getQueryCache().find({ queryKey: ['preview-catalogue'], exact: false })!;
  expect(original).toBeDefined();
  const nextHash = mode === 'canonical' ? 'b'.repeat(64) : hash;
  const nextOptions = mode === 'options' ? { ...defaultRenderOptions, view: 'top' as const } : defaultRenderOptions;
  const key = [...original.queryKey];
  key[3] = nextHash;
  key[4] = JSON.stringify(nextOptions);
  let release!: (value: Response) => void;
  view.fetcher.mockImplementation(() => new Promise(resolve => { release = resolve; }));
  const url = `/editor/previews/${nextHash}?view=${nextOptions.view}&resolution=1024&asset_views=%7B%7D`;
  let background!: Promise<unknown>;
  act(() => { background = cache.fetchQuery({ queryKey: key, queryFn: async ({ signal }) => {
    const value = await view.api.get(url);
    if (signal.aborted) throw new Error('Read cancelled.');
    return value;
  } }).catch(() => undefined); });
  await waitFor(() => expect(release).toBeTypeOf('function'));
  // A neighboring read alone does not revoke A's completed history.
  view.rerender({ canonical: null });
  expect(snapshots.history.map(value => value.receiptId)).toEqual(['cache-not-a-job']);
  view.rerender({ canonical: nextHash, options: nextOptions });
  expect(snapshots.lookup.isFetching).toBe(true);
  view.rerender({ canonical: null });
  expect(snapshots.history).toEqual([]);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  await act(async () => { release(catalogueResponse(url, 'background-result')); await background; });
  expect(snapshots.history).toEqual([]);
});

it('preserves truthful completed historical pixels through invalid validation without refetch', async () => {
  const view = setup();
  await screen.findByRole('img', { name: /scene snapshot/ });
  const completed = snapshots.history[0];
  view.rerender({ canonical: null, draft: 'invalid' });
  await act(async () => {});
  expect(snapshots.history).toEqual([completed]);
  expect(screen.getByText(/Historical preview · asset freshness unverified/)).toBeInTheDocument();
  expect(screen.getByText(/Stale · draft changed since this render/)).toBeInTheDocument();
  expect(view.fetcher).toHaveBeenCalledOnce();
});

it.each(['success', 'error'] as const)('retires catalogue on same-ID replacement before rerender and late %s', async outcome => {
  const view = setup();
  await screen.findByRole('img', { name: /scene snapshot/ });
  const query = cache.getQueryCache().find({ queryKey: ['preview-catalogue'], exact: false })!;
  const completedUpdates = query.state.dataUpdateCount;
  let release!: (value: Response) => void;
  view.fetcher.mockImplementation(() => new Promise(resolve => { release = resolve; }));
  act(() => { void snapshots.lookup.refetch(); });
  await waitFor(() => expect(release).toBeTypeOf('function'));
  view.api.session = { ...session };
  await act(async () => release(outcome === 'success' ? response(hit) : new Response('unavailable', { status: 503 })));
  expect(query.state.dataUpdateCount).toBe(completedUpdates);
  mocks.runtime = { ...mocks.runtime, session: view.api.session };
  view.rerender({ canonical: null });
  expect(snapshots.history).toEqual([]);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});

it('retires refetch and cancellation in one act without committing fetching pixels', async () => {
  const view = setup();
  await screen.findByRole('img', { name: /scene snapshot/ });
  let release!: (value: Response) => void;
  view.fetcher.mockImplementation(() => new Promise(resolve => { release = resolve; }));
  commits = [];
  await act(async () => {
    void snapshots.lookup.refetch();
    await cache.cancelQueries({ queryKey: ['preview-catalogue'] });
    view.rerender({ canonical: null });
  });
  expect(commits.some(commit => commit.canonical === hash && commit.fetching)).toBe(false);
  expect(snapshots.history).toEqual([]);
  await act(async () => release(response(hit)));
  expect(snapshots.history).toEqual([]);
});

it.each(['success', 'error'] as const)('rejects an in-flight read invalidated before its late %s', async outcome => {
  const view = setup();
  await screen.findByRole('img', { name: /scene snapshot/ });
  let release!: (value: Response) => void;
  view.fetcher.mockImplementation(() => new Promise(resolve => { release = resolve; }));
  act(() => { void snapshots.lookup.refetch(); });
  await waitFor(() => expect(release).toBeTypeOf('function'));
  await act(async () => { await cache.invalidateQueries({ queryKey: ['preview-catalogue'], refetchType: 'none' }); });
  await act(async () => release(outcome === 'success' ? response(hit) : new Response('unavailable', { status: 503 })));
  await waitFor(() => expect(snapshots.lookup.isFetching).toBe(false));
  expect(snapshots.history).toEqual([]);
  view.rerender({ canonical: null });
  expect(snapshots.history).toEqual([]);
});

it.each(['before', 'after'] as const)('ignores cancelled transport completion %s fresh reverification', async order => {
  const view = setup();
  await screen.findByRole('img', { name: /scene snapshot/ });
  const releases: ((value: Response) => void)[] = [];
  view.fetcher.mockImplementation(() => new Promise(resolve => { releases.push(resolve); }));
  act(() => { void snapshots.lookup.refetch(); });
  await waitFor(() => expect(releases).toHaveLength(1));
  await act(async () => { await cache.cancelQueries({ queryKey: ['preview-catalogue'] }); });
  expect(snapshots.history).toEqual([]);
  act(() => { void snapshots.lookup.refetch(); });
  await waitFor(() => expect(releases).toHaveLength(2));
  const fresh = { ...hit, receipt: { ...receipt, cache_key: 'new-verification', scene: { artifact_id: 'new-pixels', url: '/api/editor/artifacts/new-pixels' } } };
  if (order === 'before') {
    await act(async () => releases[0](response(hit)));
    expect(snapshots.history).toEqual([]);
  }
  await act(async () => releases[1](response(fresh)));
  await screen.findByRole('img', { name: 'scene snapshot new-verification' });
  if (order === 'after') await act(async () => releases[0](response(hit)));
  expect(snapshots.history.map(value => value.receiptId)).toEqual(['new-verification']);
  view.rerender({ canonical: null });
  expect(snapshots.history.map(value => value.receiptId)).toEqual(['new-verification']);
  expect(view.fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
});

const catalogueRetirements = ['generation', 'client'] as const;
it.each(catalogueRetirements.flatMap(mode => (['before', 'after'] as const).flatMap(order =>
  (['success', 'error'] as const).map(outcome => ({ mode, order, outcome })))))(
  'retires deferred catalogue $mode transport: late $outcome $order replacement settlement', async ({ mode, order, outcome }) => {
    const view = setup();
    await screen.findByRole('img', { name: /scene snapshot/ });
    const retiredCache = cache;
    const retiredQuery = cache.getQueryCache().find({ queryKey: ['preview-catalogue'], exact: false })!;
    expect(retiredQuery).toBeDefined();
    let oldRelease!: (value: Response) => void;
    view.fetcher.mockImplementation(() => new Promise(resolve => { oldRelease = resolve; }));
    act(() => { void snapshots.lookup.refetch(); });
    await waitFor(() => expect(oldRelease).toBeTypeOf('function'));
    let newRelease!: (value: Response) => void;
    const replacement = vi.fn(() => new Promise<Response>(resolve => { newRelease = resolve; }));
    if (mode === 'generation') { view.fetcher.mockImplementation(replacement); view.api.session = { ...session }; }
    else { const api = new ApiClient(replacement as typeof fetch); api.session = session; mocks.runtime = { ...mocks.runtime, api }; }
    mocks.runtime = { ...mocks.runtime, session: mocks.runtime.api.session };
    view.rerender({});
    await waitFor(() => expect(newRelease).toBeTypeOf('function'));
    expect(snapshots.history).toEqual([]);
    const publications = vi.fn();
    const unsubscribe = retiredCache.getQueryCache().subscribe(event => {
      if (event.query === retiredQuery && event.type === 'updated' && event.action.type === 'success') publications();
    });
    const settleOld = async () => { await act(async () => oldRelease(outcome === 'success' ? response(hit) : new Response('unavailable', { status: 503 }))); };
    try {
      if (order === 'before') { await settleOld(); expect(snapshots.history).toEqual([]); }
      await act(async () => newRelease(response({ ...hit, receipt: { ...receipt, cache_key: 'replacement-receipt' } })));
      await screen.findByRole('img', { name: 'scene snapshot replacement-receipt' });
      if (order === 'after') await settleOld();
      expect(publications).not.toHaveBeenCalled();
      expect(snapshots.history.map(value => value.receiptId)).toEqual(['replacement-receipt']);
      // Old cache events cannot retire fresh replacement pixels either.
      act(() => retiredQuery.invalidate());
      view.rerender({ canonical: null });
      expect(snapshots.history.map(value => value.receiptId)).toEqual(['replacement-receipt']);
      expect(view.fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
      expect(replacement).toHaveBeenCalledOnce();
    } finally { unsubscribe(); }
  },
);

it.each(['unmount', 'cache'] as const)('releases catalogue subscriptions on %s retirement', async mode => {
  const queryCache = cache.getQueryCache();
  const original = queryCache.subscribe.bind(queryCache);
  const active = new Set<object>();
  const spy = vi.spyOn(queryCache, 'subscribe').mockImplementation(listener => {
    const token = {};
    active.add(token);
    const unsubscribe = original(listener);
    return () => { active.delete(token); unsubscribe(); };
  });
  try {
    const view = setup();
    await screen.findByRole('img', { name: /scene snapshot/ });
    expect(active.size).toBeGreaterThan(0);
    if (mode === 'cache') {
      cache = new QueryClient();
      view.rerender({ canonical: null });
      expect(snapshots.history).toEqual([]);
      expect(active.size).toBe(0);
    }
    view.view.unmount();
    expect(active.size).toBe(0);
  } finally { spy.mockRestore(); }
});

it.each(['miss', 'error'] as const)('keeps late accepted old-job evidence without retargeting current pixels on catalogue %s', async state => {
  let accept!: (value: Response) => void;
  let oldInputs: Record<string, unknown> = {};
  const nextHash = 'b'.repeat(64);
  let accepted: Record<string, unknown>;
  const view = setup(async (url, init) => {
    if (url.endsWith('/session/activity')) return response(session);
    if (url.endsWith('/editor/snapshots')) {
      oldInputs = JSON.parse(String(init?.body));
      return new Promise(resolve => { accept = resolve; });
    }
    if (url.endsWith('/jobs/real-request-job')) return response(accepted);
    if (url.includes(nextHash)) return state === 'error' ? new Response('unavailable', { status: 503 })
      : response({ status: 'miss', canonical_hash: nextHash, receipt: null });
    return response(hit);
  });
  await screen.findByRole('img', { name: /scene snapshot/ });
  fireEvent.click(screen.getByRole('button', { name: 'Render snapshots' }));
  await waitFor(() => expect(accept).toBeTypeOf('function'));
  view.rerender({ documentId: 'new-source', canonical: nextHash, draft: 'new draft' });
  accepted = { id: 'real-request-job', workspace_id: 'default', kind: 'snapshots', status: 'succeeded', stage: 'complete',
    inputs: { ...oldInputs, canonical_hash: hash }, result: receipt, created_at: 1, updated_at: 1, error: null, created_by_session_id: 's1' };
  await act(async () => accept(response(accepted)));
  await waitFor(() => expect(snapshots.controller.job?.id).toBe('real-request-job'));
  expect(snapshots.controller.job?.inputs).toMatchObject({ yaml_text: 'draft', document_id: 'doc', options: defaultRenderOptions });
  expect(JSON.parse(sessionStorage.getItem('arena:editor:snapshots:v1')!)).toMatchObject({ payload: oldInputs, job: accepted });
  await waitFor(() => expect(snapshots.lookup.isFetching).toBe(false));
  expect(snapshots.history).toEqual([]);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(view.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(1);
});

it.each(['draft', 'camera-ABA', 'source-ABA'] as const)('fences real automatic preflight against %s without automatic replay', async mode => {
  let release!: (value: Response) => void;
  const view = setup(async url => {
    if (url.endsWith('/session/activity')) return new Promise(resolve => { release = resolve; });
    const canonical = url.includes('/editor/previews/') ? url.split('/editor/previews/')[1].split('?')[0] : hash;
    return response({ status: 'miss', canonical_hash: canonical, receipt: null });
  });
  await waitFor(() => expect(snapshots.lookup.data?.status).toBe('miss'));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' }));
  view.rerender({ draft: 'pending', canonical: 'b'.repeat(64) });
  await waitFor(() => expect(release).toBeTypeOf('function'), { timeout: 3000 });
  if (mode === 'draft') view.rerender({ draft: 'other', canonical: null });
  else {
    view.rerender(mode === 'camera-ABA' ? { draft: 'pending', canonical: 'b'.repeat(64), options: { ...defaultRenderOptions, view: 'top' } }
      : { draft: 'pending', canonical: 'b'.repeat(64), documentId: 'other' });
    view.rerender({ draft: 'pending', canonical: 'b'.repeat(64) });
  }
  await act(async () => release(response(session)));
  await waitFor(() => expect(snapshots.controller.submit.isPending).toBe(false));
  expect(view.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(0);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' }));
  expect(screen.getByRole('checkbox')).not.toBeChecked();
});

it('rejects retained automatic opt-in after source ABA', async () => {
  const view = setup();
  await screen.findByRole('img', { name: /scene snapshot/ });
  const checkbox = screen.getByRole('checkbox', { name: 'Automatic previews (GPU jobs)' });
  const props = Object.keys(checkbox).find(key => key.startsWith('__reactProps'))!;
  const change = (checkbox as any)[props].onChange;
  view.rerender({ documentId: 'other' });
  view.rerender({});
  await act(async () => change({ target: { checked: true } }));
  expect(checkbox).not.toBeChecked();
});

it('offers explicit exact retry of ambiguous old YAML/options even when the current draft is invalid', async () => {
  let posts = 0;
  const view = setup(async url => {
    if (url.endsWith('/session/activity')) return response(session);
    if (url.endsWith('/editor/snapshots')) { posts++; throw new Error('lost acknowledgement'); }
    return response(hit);
  });
  await screen.findByRole('img', { name: /scene snapshot/ });
  fireEvent.click(screen.getByRole('button', { name: 'Render snapshots' }));
  await waitFor(() => expect(snapshots.controller.submit.isPending).toBe(false));
  await waitFor(() => expect(posts).toBe(1));
  const frozen = sessionStorage.getItem('arena:editor:snapshots:v1');
  view.rerender({ draft: 'invalid new YAML', canonical: null, documentId: 'other', options: { ...defaultRenderOptions, view: 'side' } });
  expect(screen.getByText(/Retry uses the retained YAML, source, camera options and request ID, not the current draft/)).toBeInTheDocument();
  const retry = screen.getByRole('button', { name: 'Retry exact snapshot request' });
  expect(retry).toBeEnabled();
  fireEvent.click(retry);
  await waitFor(() => expect(posts).toBe(2));
  const requests = view.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'));
  expect(requests[0][1]?.body).toBe(requests[1][1]?.body);
  expect(JSON.parse(String(requests[1][1]?.body))).toMatchObject({ yaml_text: 'draft', document_id: 'doc', options: defaultRenderOptions });
  expect(sessionStorage.getItem('arena:editor:snapshots:v1')).toBe(frozen);
});

const retryRetirements = ['draft', 'camera', 'source', 'hidden', 'generation', 'client'] as const;
it.each(retryRetirements.flatMap(mode => (['before', 'during'] as const).map(phase => ({ mode, phase }))))(
  'retires retained exact-retry handlers $phase activity across $mode ABA/replacement', async ({ mode, phase }) => {
    let activity = 0;
    let release!: (value: Response) => void;
    const view = setup(async url => {
      if (url.endsWith('/session/activity')) {
        activity++;
        return activity === 2 && phase === 'during' ? new Promise(resolve => { release = resolve; }) : response(session);
      }
      if (url.endsWith('/editor/snapshots')) throw new Error('lost acknowledgement');
      return response(hit);
    });
    await screen.findByRole('img', { name: /scene snapshot/ });
    fireEvent.click(screen.getByRole('button', { name: 'Render snapshots' }));
    await waitFor(() => expect(snapshots.controller.error).toBeTruthy());
    const frozen = sessionStorage.getItem('arena:editor:snapshots:v1');
    const button = screen.getByRole('button', { name: 'Retry exact snapshot request' });
    expect(button).toBeEnabled();
    const propKey = Object.keys(button).find(key => key.startsWith('__reactProps'))!;
    const click = (button as any)[propKey].onClick;
    if (phase === 'during') {
      act(() => click());
      await waitFor(() => expect(release).toBeTypeOf('function'));
    }
    if (mode === 'generation') {
      // Real same-ID setter retires a control even before React sees replacement.
      view.api.session = { ...session };
      mocks.runtime = { ...mocks.runtime, session: view.api.session };
    } else if (mode === 'client') {
      const api = new ApiClient(view.fetcher as typeof fetch); api.session = session;
      mocks.runtime = { ...mocks.runtime, api, session: api.session };
      view.rerender({});
      mocks.runtime = { ...mocks.runtime, api: view.api, session: view.api.session };
      view.rerender({});
    } else {
      view.rerender(mode === 'draft' ? { draft: 'other' } : mode === 'camera' ? { options: { ...defaultRenderOptions, view: 'top' } }
        : mode === 'source' ? { documentId: 'other' } : { active: false });
      view.rerender({});
    }
    if (phase === 'before') await act(async () => click());
    else await act(async () => release(response(session)));
    await waitFor(() => expect(snapshots.controller.submit.isPending).toBe(false));
    expect(activity).toBe(phase === 'before' ? 1 : 2);
    expect(view.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(1);
    expect(sessionStorage.getItem('arena:editor:snapshots:v1')).toBe(frozen);
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    // Only a newly rendered explicit retry may send again, still byte-exact F.
    view.rerender({ canonical: null, draft: 'new invalid draft', documentId: 'new-source', options: { ...defaultRenderOptions, view: 'side' } });
    fireEvent.click(screen.getByRole('button', { name: 'Retry exact snapshot request' }));
    await waitFor(() => expect(view.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(2));
    await waitFor(() => expect(snapshots.controller.submit.isPending).toBe(false));
    const posts = view.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'));
    expect(posts[1][1]?.body).toBe(posts[0][1]?.body);
    expect(sessionStorage.getItem('arena:editor:snapshots:v1')).toBe(frozen);
  },
);

it.each(['draft', 'camera', 'source', 'canonical', 'hidden', 'draft-ABA', 'camera-ABA', 'source-ABA', 'hidden-ABA'] as const)(
  'does not POST a manual request after %s changes during activity preflight', async mode => {
    let release!: (value: Response) => void;
    const view = setup(async url => {
      if (url.endsWith('/session/activity')) return new Promise(resolve => { release = resolve; });
      if (url.endsWith('/editor/snapshots')) return response({});
      return response(hit);
    });
    await screen.findByRole('img', { name: /scene snapshot/ });
    fireEvent.click(screen.getByRole('button', { name: 'Render snapshots' }));
    await waitFor(() => expect(release).toBeTypeOf('function'));
    const change = mode.startsWith('draft') ? { draft: 'changed' } : mode.startsWith('camera') ? { options: { ...defaultRenderOptions, view: 'top' as const } }
      : mode.startsWith('source') ? { documentId: 'other' } : mode.startsWith('hidden') ? { active: false } : { canonical: null };
    view.rerender(change);
    if (mode.endsWith('ABA')) view.rerender({});
    await act(async () => release(response(session)));
    expect(view.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/snapshots'))).toHaveLength(0);
  },
);

it.each(['draft', 'camera', 'source', 'hidden'] as const)('rejects retained manual handlers after %s ABA before activity', async mode => {
  const view = setup();
  await screen.findByRole('img', { name: /scene snapshot/ });
  const button = screen.getByRole('button', { name: 'Render snapshots' });
  const propKey = Object.keys(button).find(key => key.startsWith('__reactProps'))!;
  const click = (button as any)[propKey].onClick;
  view.rerender(mode === 'draft' ? { draft: 'other' } : mode === 'camera' ? { options: { ...defaultRenderOptions, view: 'top' } }
    : mode === 'source' ? { documentId: 'other' } : { active: false });
  view.rerender({});
  await act(async () => click());
  expect(view.fetcher.mock.calls.filter(([url]) => url.endsWith('/session/activity') || url.endsWith('/editor/snapshots'))).toHaveLength(0);
});

it.each(['generation', 'client', 'source-ABA'] as const)('never retains catalogue pixels across %s ownership retirement', async mode => {
  const view = setup();
  await screen.findByRole('img', { name: /scene snapshot/ });
  if (mode === 'generation') {
    view.api.session = { ...session };
    mocks.runtime = { ...mocks.runtime, session: view.api.session };
  } else if (mode === 'client') {
    const api = new ApiClient(vi.fn(async () => response(hit)) as typeof fetch); api.session = session;
    mocks.runtime = { ...mocks.runtime, api, session: api.session };
  } else view.rerender({ canonical: null, documentId: 'other' });
  view.rerender({ canonical: null });
  expect(snapshots.history).toEqual([]);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});

it.each(['generation', 'client'] as const)('refetches catalogue for %s replacement without adopting cached reads', async mode => {
  const view = setup();
  await screen.findByRole('img', { name: /scene snapshot/ });
  let release!: (value: Response) => void;
  const replacement = vi.fn(async () => new Promise<Response>(resolve => { release = resolve; }));
  if (mode === 'generation') { view.fetcher.mockImplementation(replacement); view.api.session = { ...session }; }
  else { const api = new ApiClient(replacement as typeof fetch); api.session = session; mocks.runtime = { ...mocks.runtime, api }; }
  mocks.runtime = { ...mocks.runtime, session: mocks.runtime.api.session };
  view.rerender({});
  await waitFor(() => expect(replacement).toHaveBeenCalledOnce());
  expect(snapshots.history).toEqual([]);
  await act(async () => release(response({ status: 'miss', canonical_hash: hash, receipt: null })));
  expect(snapshots.history).toEqual([]);
});

it('keeps catalogue receipt identity separate from requesting job and unknown source/capture origin', async () => {
  const view = setup();
  await screen.findByRole('img', { name: /scene snapshot/ });
  expect(snapshots.history[0]).toMatchObject({ receiptId: 'cache-not-a-job' });
  expect(snapshots.history[0]).not.toHaveProperty('jobId');
  expect(snapshots.history[0]).not.toHaveProperty('requestJobId');
  expect(snapshots.history[0]).not.toHaveProperty('documentId');
  expect(screen.getByText(/Physical capture origin unknown/)).toBeInTheDocument();
  view.rerender({ documentId: 'equal-canonical-new-source' });
  await screen.findByRole('img', { name: /scene snapshot/ });
  expect(screen.getByText(/Matches current canonical scene and camera options/)).toBeInTheDocument();
  expect(screen.getByText(/not proof of capture for this source version/)).toBeInTheDocument();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});
