import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { EditorView as CodeMirrorView } from '@codemirror/view';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import { EvaluationOutcome, parseEvaluationProfiles, parseEvaluationResult } from './evaluate-policy';
import { RuntimeProvider } from './runtime';
import { ApiClient } from './api';
import { App } from './app';
import type { Job } from './contracts';
import type { Validation } from './editor-contracts';

const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const noPort = () => null;
const yaml = 'env_name: evaluation_fixture\n';
const inputHash = 'a'.repeat(64), canonicalHash = 'b'.repeat(64);
const fixed = { headless: true, enable_cameras: true, num_envs: 1, num_steps: 1000 };
const catalogue = { ...fixed, publication: 'not_requested', profiles: [
  { id: 'gr00t-droid', label: 'GR00T DROID', remote_host: '127.0.0.1', remote_port: 5555 },
  { id: 'openpi-droid', label: 'OpenPI DROID', remote_host: '127.0.0.1', remote_port: 8000 },
] };
const validation: Validation = { valid: true, source_hash: inputHash, canonical_hash: canonicalHash,
  errors: [], warnings: [], spec: {}, summary: 'Evaluation fixture', graph: { nodes: [], edges: [] },
  assets: [], relations: [], reified_relations: [], tasks: [] };
const session = { session_id: 's', csrf_token: 'csrf', expires_at: 9999999999 };
function evaluationJob(status: Job['status'] = 'succeeded'): Job {
  return { id: 'evaluate-job', workspace_id: 'default', kind: 'evaluate', status, stage: 'Policy worker finished',
    created_at: 0, updated_at: 0, created_by_session_id: 's', error: null,
    inputs: { yaml_text: yaml, document_id: 'frozen-document', input_hash: inputHash, canonical_hash: canonicalHash,
      profile: 'gr00t-droid', language_instruction: null, ...fixed },
    result: { schema_version: 1, input_hash: inputHash, canonical_hash: canonicalHash, ...fixed,
      profile: 'gr00t-droid', language_instruction: null, completed: true, publication: 'not_requested',
      metrics: { measured_reward: 0.25 }, episode_count: 0, success_count: null, artifacts: [], warnings: ['Server checkpoint was not verified.'] } };
}
function server(accepted = evaluationJob(), historical = false, gr00tPort = 5555) {
  let job: Job | undefined = historical ? accepted : undefined;
  let activity: (() => Promise<Response>) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit): Promise<Response> => {
    if (url.endsWith('/health')) return response({ capabilities: { diagnostic: false, build: true, policy_evaluation: true } });
    if (url.endsWith('/sessions')) return response(session);
    if (url.endsWith('/session/activity')) return activity ? activity() : response(session);
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', event_cursor: 0, jobs: job ? [job] : [] });
    if (url === '/api/editor') return response({ default_document_id: 'fixture', documents: [{ id: 'fixture', name: 'Fixture', source: 'fixture.yaml' }],
      capabilities: { build: true, snapshots: true, policy_evaluation: true }, limitations: [] });
    if (url.endsWith('/editor/documents/fixture')) return response({ document_id: 'frozen-document', source: 'fixture.yaml', yaml_text: yaml, source_hash: inputHash, validation });
    if (url.endsWith('/editor/validate')) return response(validation);
    if (url.includes('/editor/previews/')) return response({ status: 'miss', canonical_hash: canonicalHash, receipt: null });
    if (url.endsWith('/editor/evaluation-profiles')) return response({ ...catalogue,
      profiles: [{ ...catalogue.profiles[0], remote_port: gr00tPort }, catalogue.profiles[1]] });
    if (url.endsWith('/editor/evaluate')) { job = accepted; return response(job, 202); }
    if (url.endsWith('/jobs/evaluate-job/cancel')) { job = { ...job!, status: 'cancel_requested' }; return response(job); }
    if (url.endsWith('/jobs/evaluate-job')) return response(job ?? accepted);
    return response({ detail: 'Not installed in fixture' }, 404);
  });
  return { fetcher, delayActivity: (next: () => Promise<Response>) => { activity = next; } };
}
function mount(fetcher: ReturnType<typeof server>['fetcher'], path = '/?layout=v7') {
  const history = createMemoryHistory({ initialEntries: [path] });
  const api = new ApiClient(fetcher as typeof fetch);
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return { ...render(<App api={api} cache={cache} history={history} makePort={noPort} />), history, api, cache };
}
beforeEach(() => sessionStorage.clear());
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function retainedClick(button: HTMLElement) {
  const key = Object.keys(button).find(key => key.startsWith('__reactProps$'))!;
  return (button as unknown as Record<string, { onClick: () => void }>)[key].onClick;
}

it.each(['reactivation', 'same-ID session generation', 'client replacement'] as const)('immediately admits a fresh idle download after %s without reviving old controls', async boundary => {
  const bytes = new TextEncoder().encode('<html>verified attachment only</html>');
  const job = evaluationJob();
  job.result!.artifacts = [{ name: 'index.html', sha256: createHash('sha256').update(bytes).digest('hex'), size: bytes.length }];
  const fixture = server();
  let api = new ApiClient(fixture.fetcher as typeof fetch);
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const tree = (active = true) => <QueryClientProvider client={cache}><RuntimeProvider api={api} makePort={noPort}>
    <EvaluationOutcome job={job} active={active} />
  </RuntimeProvider></QueryClientProvider>;
  const view = render(tree());
  const button = screen.getByRole('button', { name: 'Download index.html' });
  await waitFor(() => expect(button).toBeEnabled());
  const oldClick = retainedClick(button);
  const create = vi.fn((_blob: Blob) => 'blob:verified-evaluation');
  vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL: create, revokeObjectURL: vi.fn() }));
  vi.stubGlobal('crypto', webcrypto);
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const fetcher = vi.fn(async () => new Response(bytes));
  vi.stubGlobal('fetch', fetcher);

  if (boundary === 'reactivation') {
    view.rerender(tree(false));
    expect(button).toBeDisabled();
    act(oldClick);
    expect(fetcher).not.toHaveBeenCalled();
  } else if (boundary === 'same-ID session generation') {
    api.session = { ...api.session! };
    act(oldClick); // Mutable ApiClient retirement must work even before React commits.
    expect(fetcher).not.toHaveBeenCalled();
  } else {
    api = new ApiClient(fixture.fetcher as typeof fetch);
    await api.connect();
  }
  view.rerender(tree());
  // Replacing a provider client explicitly reconnects before controls are admitted.
  if (boundary === 'client replacement') await waitFor(() => expect(button).toBeEnabled());
  act(oldClick);
  expect(fetcher).not.toHaveBeenCalled();
  expect(button).toBeEnabled();
  // No waitFor, timer, activity request or unrelated render may repair this click.
  fireEvent.click(button);
  expect(fetcher).toHaveBeenCalledOnce();
  await waitFor(() => expect(click).toHaveBeenCalledOnce());
  expect(create.mock.calls[0][0].type).toBe('application/octet-stream');
  expect(document.querySelector('iframe')).toBeNull();
});

it.each([
  ['reactivation', 'success'], ['reactivation', 'error'],
  ['same-ID session generation', 'success'], ['same-ID session generation', 'error'],
  ['client replacement', 'success'], ['client replacement', 'error'],
] as const)('keeps a pending download retired after %s and late %s while the fresh download owns busy state', async (boundary, settlement) => {
  const bytes = new TextEncoder().encode('verified evaluation bytes');
  const job = evaluationJob();
  job.result!.artifacts = [{ name: 'index.html', sha256: createHash('sha256').update(bytes).digest('hex'), size: bytes.length }];
  const fixture = server();
  let api = new ApiClient(fixture.fetcher as typeof fetch);
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const tree = (active = true) => <QueryClientProvider client={cache}><RuntimeProvider api={api} makePort={noPort}>
    <EvaluationOutcome job={job} active={active} />
  </RuntimeProvider></QueryClientProvider>;
  const view = render(tree());
  const button = screen.getByRole('button', { name: 'Download index.html' });
  await waitFor(() => expect(button).toBeEnabled());
  const oldClick = retainedClick(button);
  const create = vi.fn(() => 'blob:verified-evaluation');
  vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL: create, revokeObjectURL: vi.fn() }));
  vi.stubGlobal('crypto', webcrypto);
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const pending: { resolve: (value: Response) => void; reject: (error: Error) => void; signal: AbortSignal }[] = [];
  // Deliberately ignore abort so the real completion fence must reject late transport settlement.
  const fetcher = vi.fn((_url: string, init: RequestInit) => new Promise<Response>((resolve, reject) => {
    pending.push({ resolve, reject, signal: init.signal as AbortSignal });
  }));
  vi.stubGlobal('fetch', fetcher);
  fireEvent.click(button);
  expect(fetcher).toHaveBeenCalledOnce();
  expect(button).toHaveTextContent('Verifying');

  if (boundary === 'reactivation') view.rerender(tree(false));
  else if (boundary === 'same-ID session generation') api.session = { ...api.session! };
  else api = new ApiClient(fixture.fetcher as typeof fetch);
  view.rerender(tree());
  if (boundary === 'client replacement') await waitFor(() => expect(button).toBeEnabled());
  expect(pending[0].signal.aborted).toBe(true);
  act(oldClick);
  expect(fetcher).toHaveBeenCalledOnce();
  expect(button).toBeEnabled();
  fireEvent.click(button);
  expect(fetcher).toHaveBeenCalledTimes(2);
  await act(async () => {
    if (settlement === 'success') pending[0].resolve(new Response(bytes));
    else pending[0].reject(new Error('retired transport failure'));
  });
  expect(create).not.toHaveBeenCalled();
  expect(click).not.toHaveBeenCalled();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(button).toBeDisabled();
  expect(button).toHaveTextContent('Verifying');
  expect(pending[1].signal.aborted).toBe(false);
  await act(async () => pending[1].resolve(new Response(bytes)));
  await waitFor(() => expect(click).toHaveBeenCalledOnce());
  expect(button).toBeEnabled();
  act(oldClick);
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it('downloads an idle retained editor outcome immediately after navigating away and back', async () => {
  const bytes = new TextEncoder().encode('retained editor attachment');
  const job = evaluationJob();
  job.result!.artifacts = [{ name: 'index.html', sha256: createHash('sha256').update(bytes).digest('hex'), size: bytes.length }];
  const fixture = server(job); const view = mount(fixture.fetcher);
  const evaluate = await screen.findByRole('button', { name: 'Evaluate policy' });
  await waitFor(() => expect(evaluate).toBeEnabled()); fireEvent.click(evaluate);
  const download = await screen.findByRole('button', { name: 'Download index.html' });
  const oldClick = retainedClick(download);
  const create = vi.fn(() => 'blob:verified-evaluation');
  vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL: create, revokeObjectURL: vi.fn() }));
  vi.stubGlobal('crypto', webcrypto);
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const fetcher = vi.fn(async () => new Response(bytes));
  vi.stubGlobal('fetch', fetcher);
  act(() => view.history.push('/neo4j?layout=v7'));
  await waitFor(() => expect(download).not.toBeVisible());
  act(oldClick);
  expect(fetcher).not.toHaveBeenCalled();
  act(() => view.history.push('/?layout=v7'));
  await waitFor(() => expect(download).toBeVisible());
  // The real editor revalidates catalogue admission on return before setting active.
  await waitFor(() => expect(download).toBeEnabled());
  expect(screen.getByRole('button', { name: 'Download index.html' })).toBe(download);
  act(oldClick);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(download);
  expect(fetcher).toHaveBeenCalledOnce();
  await waitFor(() => expect(click).toHaveBeenCalledOnce());
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/evaluate'))).toHaveLength(1);
});

it.each(['valid', 'wrong hash', 'wrong size', 'session replaced'] as const)('downloads fixed attachments only after checking actual bytes: %s', async boundary => {
  const bytes = new TextEncoder().encode('<html><script>never inline</script></html>');
  const job = evaluationJob();
  job.result!.artifacts = [{ name: 'index.html', sha256: createHash('sha256').update(bytes).digest('hex'), size: bytes.length }];
  const fixture = server(job); const view = mount(fixture.fetcher);
  const button = await screen.findByRole('button', { name: 'Evaluate policy' });
  await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button);
  const download = await screen.findByRole('button', { name: 'Download index.html' });
  const create = vi.fn((_blob: Blob) => 'blob:verified-evaluation');
  const revoke = vi.fn();
  vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL: create, revokeObjectURL: revoke }));
  vi.stubGlobal('crypto', webcrypto);
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const fetcher = vi.fn(async () => {
    if (boundary === 'session replaced') view.api.session = { ...view.api.session! };
    const received = boundary === 'wrong hash' ? new Uint8Array(bytes.length).fill(65) : boundary === 'wrong size' ? bytes.slice(1) : bytes;
    return new Response(received);
  });
  vi.stubGlobal('fetch', fetcher);
  fireEvent.click(download);
  if (boundary === 'valid') {
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect(create).toHaveBeenCalledOnce();
    const blob = create.mock.calls[0][0] as Blob;
    const actual = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsText(blob); });
    expect(actual).toBe(new TextDecoder().decode(bytes));
    expect(blob.type).toBe('application/octet-stream');
    expect((click.mock.instances[0] as HTMLAnchorElement).download).toBe('index.html');
  } else {
    await waitFor(() => expect(download).not.toHaveTextContent('Verifying'));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(create).not.toHaveBeenCalled(); expect(click).not.toHaveBeenCalled();
  }
  expect(fetcher).toHaveBeenCalledWith('/api/editor/evaluations/evaluate-job/artifacts/index.html', expect.objectContaining({ credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: expect.any(AbortSignal) }));
  expect(document.querySelector('iframe')).toBeNull();
});

it.each([1, 5555, 5559, 65535])('accepts bounded configured GR00T port %s without changing fixed OpenPI', port => {
  const configured = structuredClone(catalogue); configured.profiles[0].remote_port = port;
  expect(parseEvaluationProfiles(configured)).toEqual(configured.profiles);
});

it.each([null, true, false, 0, -1, 65536, 5559.5, '5559', {}, [], NaN, Infinity])('rejects noncanonical server port %s', port => {
  expect(() => parseEvaluationProfiles({ ...catalogue, profiles: [{ ...catalogue.profiles[0], remote_port: port }, catalogue.profiles[1]] })).toThrow();
});

it.each(['localhost', '127.0.0.2', '::1', 'example.test', '127.0.0.1:5559'])('rejects changed server host %s', host => {
  expect(() => parseEvaluationProfiles({ ...catalogue, profiles: [{ ...catalogue.profiles[0], remote_host: host }, catalogue.profiles[1]] })).toThrow();
});

it('keeps OpenPI fixed at 8000 even when GR00T is configured', () => {
  expect(() => parseEvaluationProfiles({ ...catalogue,
    profiles: [catalogue.profiles[0], { ...catalogue.profiles[1], remote_port: 5559 }] })).toThrow();
});

it('displays configured GR00T metadata but never sends a browser endpoint field', async () => {
  const fixture = server(evaluationJob('queued'));
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => url.endsWith('/editor/evaluation-profiles')
    ? response({ ...catalogue, profiles: [{ ...catalogue.profiles[0], remote_port: 5559 }, catalogue.profiles[1]] }) : fixture.fetcher(url, init));
  mount(fetcher);
  const button = await screen.findByRole('button', { name: 'Evaluate policy' });
  await waitFor(() => expect(button).toBeEnabled());
  expect(screen.getByRole('option', { name: 'GR00T DROID — 127.0.0.1:5559' })).toBeInTheDocument();
  fireEvent.click(button);
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/evaluate'))).toHaveLength(1));
  const body = JSON.parse(fetcher.mock.calls.find(([url]) => url.endsWith('/editor/evaluate'))![1]!.body as string);
  expect(body.profile).toBe('gr00t-droid');
  expect(body).not.toHaveProperty('remote_host'); expect(body).not.toHaveProperty('remote_port');
});

it.each([5555, 5559])('retires a frozen dispatch when the profile catalogue at %s refetches identical data during activity', async port => {
  const fixture = server(evaluationJob(), false, port); const view = mount(fixture.fetcher);
  const button = await screen.findByRole('button', { name: 'Evaluate policy' });
  await waitFor(() => expect(button).toBeEnabled());
  let release!: (value: Response) => void;
  fixture.delayActivity(() => new Promise(resolve => { release = resolve; }));
  fireEvent.click(button); await waitFor(() => expect(release).toBeTypeOf('function'));
  await act(async () => { await view.cache.invalidateQueries({ queryKey: ['evaluation-profiles'] }); });
  await act(async () => release(response(session)));
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/evaluate'))).toHaveLength(0);
  expect(sessionStorage.getItem('arena:editor:evaluate:v1')).not.toBeNull();
});

it.each(['missing capability', 'false capability', 'invalid draft', 'malformed profile', 'whitespace instruction', 'over-byte-limit instruction'] as const)('blocks fresh evaluation for %s while keeping Build independent', async boundary => {
  const fixture = server();
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const reply = await fixture.fetcher(url, init);
    if (url === '/api/editor' && boundary.endsWith('capability')) {
      const index = await reply.json();
      if (boundary === 'false capability') index.capabilities.policy_evaluation = false; else delete index.capabilities.policy_evaluation;
      return response(index);
    }
    if (url.endsWith('/editor/documents/fixture') && boundary === 'invalid draft') { const doc = await reply.json(); doc.validation.valid = false; return response(doc); }
    if (url.endsWith('/editor/evaluation-profiles') && boundary === 'malformed profile') return response({ ...catalogue, profiles: [{ ...catalogue.profiles[0], remote_host: 'evil.example' }, catalogue.profiles[1]] });
    return reply;
  });
  mount(fetcher);
  const button = await screen.findByRole('button', { name: 'Evaluate policy' });
  if (boundary.includes('instruction')) {
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.change(screen.getByRole('textbox', { name: 'Language instruction (optional)' }), { target: { value: boundary === 'whitespace instruction' ? '  \n ' : 'é'.repeat(2001) } });
  } else if (boundary === 'invalid draft') await screen.findByText('Schema errors');
  else await waitFor(() => expect(screen.getByRole('button', { name: 'Build environment' })).toBeEnabled());
  expect(button).toBeDisabled(); fireEvent.click(button);
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/evaluate'))).toHaveLength(0);
  if (boundary.endsWith('capability')) expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/evaluation-profiles'))).toHaveLength(0);
});

it.each(['navigation', 'session replacement', 'capability withdrawal'] as const)('retires configured-port evaluation during activity after %s', async boundary => {
  const fixture = server(evaluationJob(), false, 5559); const view = mount(fixture.fetcher);
  const button = await screen.findByRole('button', { name: 'Evaluate policy' });
  await waitFor(() => expect(button).toBeEnabled());
  let release!: (value: Response) => void;
  fixture.delayActivity(() => new Promise(resolve => { release = resolve; }));
  fireEvent.click(button); await waitFor(() => expect(release).toBeTypeOf('function'));
  if (boundary === 'navigation') { act(() => view.history.push('/neo4j?layout=v7')); await waitFor(() => expect(button).not.toBeVisible()); }
  else if (boundary === 'session replacement') view.api.session = { ...view.api.session! };
  else act(() => { void view.cache.invalidateQueries({ queryKey: ['editor'], refetchType: 'none' }); });
  await act(async () => release(response(session)));
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/evaluate'))).toHaveLength(0);
});

it('retries an unresolved evaluation with the byte-exact retained profile, instruction, YAML and key', async () => {
  const fixture = server(); let attempts = 0;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/editor/evaluate') && ++attempts === 1) return response({ detail: 'Evaluation unavailable' }, 503);
    if (url.endsWith('/editor/validate')) return response({ ...validation, valid: false });
    return fixture.fetcher(url, init);
  });
  mount(fetcher); const button = await screen.findByRole('button', { name: 'Evaluate policy' });
  await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button);
  const retry = await screen.findByRole('button', { name: 'Retry evaluation request' });
  const first = fetcher.mock.calls.find(([url]) => url.endsWith('/editor/evaluate'))![1]?.body;
  fireEvent.change(screen.getByRole('combobox', { name: 'Policy profile' }), { target: { value: 'openpi-droid' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Language instruction (optional)' }), { target: { value: 'Different instruction' } });
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'invalid draft' } }));
  await screen.findByText('Schema errors'); expect(retry).toBeEnabled(); fireEvent.click(retry);
  await screen.findByRole('region', { name: 'Policy evaluation result' });
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/evaluate')).map(([, init]) => init?.body)).toEqual([first, first]);
});

it.each([
  ['schema_version', 2], ['completed', false], ['headless', false], ['enable_cameras', false], ['num_envs', 2], ['num_steps', 20],
  ['publication', 'published'], ['profile', 'openpi-droid'], ['language_instruction', 'Different'], ['input_hash', 'c'.repeat(64)], ['canonical_hash', null],
  ['episode_count', -1], ['episode_count', 1.5], ['success_count', 1], ['metrics', []], ['metrics', { x: Infinity }],
  ['warnings', ['x'.repeat(2001)]], ['artifacts', [{ name: '../index.html', sha256: inputHash, size: 0 }]],
  ['artifacts', [{ name: 'video.mp4', sha256: inputHash, size: 0 }]],
] as const)('withholds malformed or mismatched measured field %s', (field, value) => {
  const job = evaluationJob(); job.result = { ...job.result, [field]: value };
  expect(parseEvaluationResult(job)).toBeNull();
});
it.each(['queued', 'running', 'cancel_requested', 'cancelled', 'indeterminate', 'failed', 'blocked_authorization'] as const)('never presents completion-shaped results for %s', status => {
  expect(parseEvaluationResult(evaluationJob(status))).toBeNull();
});
it('binds all frozen fixed inputs and displays only detached bounded measured data', () => {
  for (const field of ['headless', 'enable_cameras', 'num_envs', 'num_steps', 'profile', 'language_instruction', 'input_hash', 'canonical_hash', 'yaml_text', 'document_id']) {
    const job = evaluationJob(); delete job.inputs[field]; expect(parseEvaluationResult(job)).toBeNull();
  }
  const job = evaluationJob(); expect(parseEvaluationResult({ ...job, kind: 'build' })).toBeNull();
  const result = parseEvaluationResult(job)!;
  (job.result!.metrics as Record<string, unknown>).measured_reward = 999;
  expect(result.metrics).toEqual({ measured_reward: 0.25 });
  expect(parseEvaluationProfiles(catalogue)).toHaveLength(2);
  expect(() => parseEvaluationProfiles({ ...catalogue, profiles: [catalogue.profiles[0], catalogue.profiles[0]] })).toThrow();
});

it('reads historical measured results on a direct job route without starting evaluation', async () => {
  const fixture = server(evaluationJob(), true); mount(fixture.fetcher, '/jobs/evaluate-job?layout=v7');
  const inspector = await screen.findByRole('region', { name: 'Job details' });
  expect(await within(inspector).findByRole('region', { name: 'Policy evaluation result' })).toBeInTheDocument();
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/evaluate'))).toHaveLength(0);
});

it('withholds raw untrusted evaluation metrics in JobInspector when frozen result identity mismatches', async () => {
  const job = evaluationJob(); job.result!.canonical_hash = 'c'.repeat(64); job.result!.metrics = { untrusted_claim: 'DO_NOT_PRESENT_AS_MEASUREMENT' };
  const fixture = server(job, true); mount(fixture.fetcher, '/jobs/evaluate-job?layout=v7');
  const inspector = await screen.findByRole('region', { name: 'Job details' });
  expect(await within(inspector).findByText(/Evaluation completion is unverified/)).toBeInTheDocument();
  expect(within(inspector).queryByText(/DO_NOT_PRESENT_AS_MEASUREMENT/)).not.toBeInTheDocument();
});

it('keeps an evaluation request unresolved if admission returns another job kind', async () => {
  const job = evaluationJob(); job.kind = 'build'; const fixture = server(job); mount(fixture.fetcher);
  const button = await screen.findByRole('button', { name: 'Evaluate policy' });
  await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button);
  expect(await screen.findByRole('button', { name: 'Retry evaluation request' })).toBeEnabled();
  expect(JSON.parse(sessionStorage.getItem('arena:editor:evaluate:v1')!).job).toBeUndefined();
});

it('accepts bounded metrics up to the actual server receipt limits', () => {
  const job = evaluationJob(); job.result!.metrics = { notes: 'x'.repeat(65000) };
  expect(parseEvaluationResult(job)?.metrics?.notes === (job.result!.metrics as Record<string, unknown>).notes).toBe(true);
});

it('shows measured N=0 evidence without claiming success and mounts the same outcome in JobInspector', async () => {
  const fixture = server(); const view = mount(fixture.fetcher);
  const button = await screen.findByRole('button', { name: 'Evaluate policy' });
  await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button);
  const outcome = await screen.findByRole('region', { name: 'Policy evaluation result' });
  expect(within(outcome).getByText('No completed-episode evidence')).toBeInTheDocument();
  expect(within(outcome).getByText(/"measured_reward": 0.25/)).toBeInTheDocument();
  expect(within(outcome).getByText(/Completion is not manipulation proof/)).toBeInTheDocument();
  expect(within(outcome).getByText('Server checkpoint was not verified.')).toBeInTheDocument();
  expect(outcome.textContent).not.toMatch(/(?:0|100)%/);
  expect(JSON.parse(String(fixture.fetcher.mock.calls.find(([url]) => url.endsWith('/editor/evaluate'))![1]?.body)).language_instruction).toBeNull();
  fireEvent.click(screen.getByRole('link', { name: 'Job details' }));
  await waitFor(() => expect(view.history.location.pathname).toBe('/jobs/evaluate-job'));
  const inspector = await screen.findByRole('region', { name: 'Job details' });
  expect(within(inspector).getByRole('region', { name: 'Policy evaluation result' })).toBeInTheDocument();
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/evaluate'))).toHaveLength(1);
});

it('labels policy evaluation progress and cancellation independently of Build and generation', async () => {
  const fixture = server(evaluationJob('running')); mount(fixture.fetcher);
  const button = await screen.findByRole('button', { name: 'Evaluate policy' });
  await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button);
  expect(await screen.findByText('Policy evaluation · running')).toBeInTheDocument();
  expect(screen.getByRole('progressbar', { name: 'evaluate progress' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel evaluation' }));
  expect(await screen.findByText('Cancellation requested; waiting for worker acknowledgment.')).toBeInTheDocument();
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/jobs/evaluate-job/cancel'))).toHaveLength(1);
  expect(screen.queryByRole('region', { name: 'Policy evaluation result' })).not.toBeInTheDocument();
});

it('mounts explicit policy consent in the real editor and freezes only API inputs before activity', async () => {
  const fixture = server(); mount(fixture.fetcher);
  const button = await screen.findByRole('button', { name: 'Evaluate policy' });
  await waitFor(() => expect(button).toBeEnabled());
  expect(screen.getByRole('button', { name: 'Build environment' })).toBeEnabled();
  expect(screen.getByText(/900-second wall-clock cap/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox', { name: 'Policy profile' }), { target: { value: 'openpi-droid' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Language instruction (optional)' }), { target: { value: 'Pick up the cup' } });
  let release!: (value: Response) => void;
  fixture.delayActivity(() => new Promise(resolve => { release = resolve; }));
  fireEvent.click(button);
  await waitFor(() => expect(release).toBeTypeOf('function'));
  fireEvent.change(screen.getByRole('textbox', { name: 'Language instruction (optional)' }), { target: { value: 'Later instruction' } });
  const cm = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: 'env_name: later_draft\n' } }));
  await act(async () => release(response(session)));
  await waitFor(() => expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/evaluate'))).toHaveLength(1));
  const post = fixture.fetcher.mock.calls.find(([url]) => url.endsWith('/editor/evaluate'))!;
  expect(JSON.parse(String(post[1]?.body))).toEqual({ yaml_text: yaml, document_id: 'frozen-document', profile: 'openpi-droid',
    language_instruction: 'Pick up the cup', idempotency_key: expect.any(String) });
  expect(fixture.fetcher.mock.calls.filter(([url, init]) => init?.method === 'POST' && /generate|snapshots|publish|\/build/.test(url))).toHaveLength(0);
});
