import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { EditorView as CodeMirrorView } from '@codemirror/view';
import { beforeEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { App } from './app';
import type { Job } from './contracts';
import type { Validation } from './editor-contracts';
import { parseBuildResult } from './build-environment';

const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const noPort = () => null;
const yaml = 'env_name: build_fixture\n';
const inputHash = 'a'.repeat(64);
const canonicalHash = 'b'.repeat(64);
const profile = { headless: true, num_envs: 1, num_steps: 20, policy: 'zero_action' };
const validation: Validation = { valid: true, source_hash: inputHash, canonical_hash: canonicalHash,
  errors: [], warnings: [], spec: {}, summary: 'Build fixture', graph: { nodes: [], edges: [] },
  assets: [], relations: [], reified_relations: [], tasks: [] };
const session = { session_id: 's', csrf_token: 'csrf', expires_at: 9999999999 };
function buildJob(status: Job['status'] = 'succeeded'): Job {
  return { id: 'build-job', workspace_id: 'default', kind: 'build', status, stage: 'Build worker finished',
    created_at: 0, updated_at: 0, created_by_session_id: 's', error: null,
    inputs: { yaml_text: yaml, document_id: 'frozen-document', input_hash: inputHash, canonical_hash: canonicalHash, ...profile },
    result: { schema_version: 1, input_hash: inputHash, canonical_hash: canonicalHash, ...profile, completed: true } };
}
function server(accepted = buildJob()) {
  let job: Job | undefined;
  let activity: (() => Promise<Response>) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit): Promise<Response> => {
    if (url.endsWith('/health')) return response({ capabilities: { diagnostic: false, build: true } });
    if (url.endsWith('/sessions')) return response(session);
    if (url.endsWith('/session/activity')) return activity ? activity() : response(session);
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', event_cursor: 0, jobs: job ? [job] : [] });
    if (url === '/api/editor') return response({ default_document_id: 'fixture', documents: [{ id: 'fixture', name: 'Fixture', source: 'fixture.yaml' }],
      capabilities: { build: true, snapshots: true }, limitations: [] });
    if (url.endsWith('/editor/documents/fixture')) return response({ document_id: 'frozen-document', source: 'fixture.yaml', yaml_text: yaml, source_hash: inputHash, validation });
    if (url.endsWith('/editor/validate')) return response(validation);
    if (url.includes('/editor/previews/')) return response({ status: 'miss', canonical_hash: canonicalHash, receipt: null });
    if (url.endsWith('/editor/build')) { job = accepted; return response(job, 202); }
    if (url.endsWith('/jobs/build-job/cancel')) { job = { ...job!, status: 'cancel_requested' }; return response(job); }
    if (url.endsWith('/jobs/build-job')) return response(job);
    return response({ detail: 'Not installed in fixture' }, 404);
  });
  return { fetcher, delayActivity: (next: () => Promise<Response>) => { activity = next; } };
}
function mount(fetcher: ReturnType<typeof server>['fetcher']) {
  const history = createMemoryHistory({ initialEntries: ['/?layout=v7'] });
  const api = new ApiClient(fetcher as typeof fetch);
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return { ...render(<App api={api} cache={cache} history={history} makePort={noPort} />), history, api, cache };
}
beforeEach(() => sessionStorage.clear());

it('mounts Build in the real editor and submits frozen validated YAML before presenting matched completion', async () => {
  const fixture = server();
  mount(fixture.fetcher);
  const button = await screen.findByRole('button', { name: 'Build environment' });
  await waitFor(() => expect(button).toBeEnabled());
  expect(screen.getByText(/20 zero-action simulation steps/)).toBeInTheDocument();
  expect(screen.getByText(/simulation effects/i)).toBeInTheDocument();
  let release!: (value: Response) => void;
  fixture.delayActivity(() => new Promise(resolve => { release = resolve; }));
  fireEvent.click(button);
  await waitFor(() => expect(release).toBeTypeOf('function'));
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: later_draft\n' } }));
  await act(async () => release(response(session)));
  expect(await screen.findByRole('heading', { name: 'Build completed' })).toBeInTheDocument();
  const posts = fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/build'));
  expect(posts).toHaveLength(1);
  expect(JSON.parse(String(posts[0][1]?.body))).toEqual({ yaml_text: yaml, document_id: 'frozen-document', idempotency_key: expect.any(String) });
  expect(screen.getByText(/not policy success or physics proof/i)).toBeInTheDocument();
  expect(fixture.fetcher.mock.calls.filter(([url, init]) => init?.method === 'POST' && /generate|snapshots|publish/.test(url))).toHaveLength(0);
});

it('labels Build status and cancellation independently from snapshots and generation', async () => {
  const fixture = server(buildJob('running'));
  mount(fixture.fetcher);
  const button = await screen.findByRole('button', { name: 'Build environment' });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  expect(await screen.findByText('Build environment · running')).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Build completed' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel build' }));
  expect(await screen.findByText('Cancellation requested; waiting for worker acknowledgment.')).toBeInTheDocument();
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/build-job/cancel'))).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'Refresh job status' })).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'Cancel generation' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Cancel snapshot render' })).not.toBeInTheDocument();
});

it('presents the typed Build result when its existing job-details link is selected', async () => {
  const fixture = server();
  const view = mount(fixture.fetcher);
  const button = await screen.findByRole('button', { name: 'Build environment' });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  fireEvent.click(await screen.findByRole('link', { name: 'Job details' }));
  await waitFor(() => expect(view.history.location.pathname).toBe('/jobs/build-job'));
  const inspector = await screen.findByRole('region', { name: 'Job details' });
  expect(within(inspector).getByRole('heading', { name: 'Build completed' })).toBeInTheDocument();
  expect(within(inspector).getByText(/not policy success or physics proof/)).toBeInTheDocument();
});

it.each(['missing capability', 'false capability', 'invalid draft', 'empty editor'] as const)('blocks fresh Build for %s without disabling independent snapshots', async boundary => {
  const fixture = server();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const reply = await fixture.fetcher(url, init);
    if (url === '/api/editor' && boundary !== 'invalid draft') {
      const index = await reply.json();
      if (boundary === 'empty editor') { index.default_document_id = ''; index.documents = []; }
      else if (boundary === 'false capability') index.capabilities.build = false;
      else delete index.capabilities.build;
      return response(index);
    }
    if (url.endsWith('/editor/documents/fixture') && boundary === 'invalid draft') {
      const doc = await reply.json(); doc.validation.valid = false;
      return response(doc);
    }
    return reply;
  });
  mount(fetcher);
  await screen.findByRole('button', { name: 'Build environment' });
  if (boundary.endsWith('capability')) await waitFor(() => expect(screen.getByRole('button', { name: 'Render snapshots' })).toBeEnabled());
  else await screen.findByText(boundary === 'invalid draft' ? 'Schema errors' : 'No document');
  const button = screen.getByRole('button', { name: 'Build environment' });
  expect(button).toBeDisabled(); fireEvent.click(button);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/build'))).toHaveLength(0);
});

it.each([
  ['schema_version', 2], ['completed', false], ['headless', false], ['num_envs', 2], ['num_steps', 0],
  ['policy', 'trained'], ['input_hash', 'c'.repeat(64)], ['canonical_hash', 'c'.repeat(64)],
  ['input_hash', 'not-a-hash'], ['canonical_hash', null],
] as const)('rejects a malformed or mismatched result field %s=%s', (field, value) => {
  const job = buildJob(); job.result = { ...job.result, [field]: value };
  expect(parseBuildResult(job)).toBeNull();
});
it.each(['queued', 'running', 'cancel_requested', 'cancelled', 'indeterminate', 'failed'] as const)('withholds typed completion for a %s job even with a completion-shaped result', status => {
  expect(parseBuildResult(buildJob(status))).toBeNull();
});
it('withholds typed completion for missing result or inconsistent frozen profile', () => {
  expect(parseBuildResult({ ...buildJob(), result: null })).toBeNull();
  const job = buildJob(); job.inputs.num_steps = 0;
  expect(parseBuildResult(job)).toBeNull();
});

it('shows unverified completion rather than Build completed for a mismatched result', async () => {
  const job = buildJob(); job.result!.canonical_hash = 'c'.repeat(64);
  const fixture = server(job); mount(fixture.fetcher);
  const button = await screen.findByRole('button', { name: 'Build environment' });
  await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button);
  expect(await screen.findByText(/Build completion is unverified/)).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Build completed' })).not.toBeInTheDocument();
});

it('retries the exact retained Build request even when the current draft is invalid', async () => {
  const fixture = server();
  let attempts = 0;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/editor/build') && ++attempts === 1) return response({ detail: 'Build adapter unavailable' }, 503);
    if (url.endsWith('/editor/validate')) return response({ ...validation, valid: false });
    return fixture.fetcher(url, init);
  });
  mount(fetcher);
  const button = await screen.findByRole('button', { name: 'Build environment' });
  await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button);
  expect(await screen.findByText('Build adapter unavailable')).toBeInTheDocument();
  const retry = await screen.findByRole('button', { name: 'Retry build request' });
  expect(screen.getByText('Submission unresolved. Retry sends the same frozen inputs and request ID.')).toBeInTheDocument();
  const first = fetcher.mock.calls.find(([url]) => url.endsWith('/editor/build'))![1]?.body;
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'invalid draft' } }));
  await screen.findByText('Schema errors');
  expect(retry).toBeEnabled(); fireEvent.click(retry);
  expect(await screen.findByRole('heading', { name: 'Build completed' })).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/build')).map(([, init]) => init?.body)).toEqual([first, first]);
});

it.each(['navigation', 'session replacement', 'capability withdrawal'] as const)('retires pending Build dispatch after %s during activity', async boundary => {
  const fixture = server();
  const view = mount(fixture.fetcher);
  const button = await screen.findByRole('button', { name: 'Build environment' });
  await waitFor(() => expect(button).toBeEnabled());
  let release!: (value: Response) => void;
  fixture.delayActivity(() => new Promise(resolve => { release = resolve; }));
  fireEvent.click(button);
  await waitFor(() => expect(release).toBeTypeOf('function'));
  if (boundary === 'navigation') {
    act(() => view.history.push('/neo4j?layout=v7'));
    await waitFor(() => expect(button).not.toBeVisible());
  } else if (boundary === 'session replacement') view.api.session = { ...view.api.session! };
  else act(() => { void view.cache.invalidateQueries({ queryKey: ['editor'], refetchType: 'none' }); });
  await act(async () => release(response(session)));
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/build'))).toHaveLength(0);
  expect(JSON.parse(sessionStorage.getItem('arena:editor:build:v1')!).payload).toEqual({ yaml_text: yaml, document_id: 'frozen-document', idempotency_key: expect.any(String) });
});
