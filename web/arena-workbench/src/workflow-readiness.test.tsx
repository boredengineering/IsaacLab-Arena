import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { clientSessionScope } from './client-session-scope';
import { WorkflowReadiness, parseReadiness } from './workflow-readiness';

const runtime = vi.hoisted(() => ({ current: {} as {api: ApiClient; session: {session_id: string} | null} }));
vi.mock('./runtime', () => ({useRuntime: () => runtime.current}));
const metadata = () => ({schema_version: 1, checked_at: null, provider: {configured: false, source: 'none', verification: 'not_checked'},
  graph: {configured: false, status: 'not_configured'}, dependencies: {openai: true, neo4j: true, isaacsim: true},
  runtime: {build_adapter: true, evaluation_adapter: true, simulation: 'not_checked'},
  policy_servers: [{profile: 'gr00t-droid', host: '127.0.0.1', port: 5555, status: 'not_checked'}, {profile: 'openpi-droid', host: '127.0.0.1', port: 8000, status: 'not_checked'}],
  workflow: {research_versions: false, publication: false, managed_retrieval: false, scenario_harness: 'cli_only', evaluation_scope: 'droid_fixed_profiles'}});
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status});
function setup(handler?: (url: string, init: RequestInit) => Promise<Response> | undefined) {
  const fetcher = vi.fn(async (url: string, init: RequestInit) => handler?.(url, init) ?? response(url.endsWith('/activity') ? api.session : metadata()));
  const api = new ApiClient(fetcher as typeof fetch);
  api.session = {session_id: 'test-session', csrf_token: 'test-csrf', expires_at: 9999999999};
  runtime.current = {api, session: api.session};
  const cache = new QueryClient({defaultOptions: {queries: {retry: false, gcTime: 0}}});
  const tree = (active = true, providerRevision = 'none') => <QueryClientProvider client={cache}><WorkflowReadiness version={1} active={active} providerRevision={providerRevision} /></QueryClientProvider>;
  const view = render(tree());
  return {...view, api, cache, fetcher, redraw: (active = true, providerRevision = 'none') => view.rerender(tree(active, providerRevision))};
}

it('shows configuration gaps without claiming verified dependencies or launching checks on mount', async () => {
  const fixture = setup();
  await screen.findByText('Model provider: not configured');
  expect(screen.getByText('Graph-RAG: not configured')).toBeVisible();
  expect(screen.getByText(/Full scenario harness remains CLI-only/)).toBeVisible();
  expect(screen.getByText(/No provider calls or GPU jobs/)).toBeVisible();
  expect(fixture.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
});

it('checks fixed dependencies only after an explicit click and reports limited evidence', async () => {
  const fixture = setup((url) => url.endsWith('/readiness/check') ? Promise.resolve(response({...metadata(), checked_at: 123, graph: {configured: true, status: 'available'}})) : undefined);
  await screen.findByText('Graph-RAG: not configured');
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await screen.findByText('Graph-RAG: database read verified');
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/readiness/check'))).toHaveLength(1);
  expect(fixture.fetcher.mock.calls.some(([url]) => /\/editor\/(generate|build|evaluate|snapshots)$/.test(url))).toBe(false);
});

it('does not display raw request errors', async () => {
  setup(url => url.endsWith('/readiness/check') ? Promise.resolve(response({detail: 'synthetic-private-marker'}, 500)) : undefined);
  await screen.findByText('Graph-RAG: not configured');
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await screen.findByText('Dependency check unavailable. No work was submitted.');
  expect(document.body.textContent).not.toContain('synthetic-private-marker');
});

it.each(['inactive', 'session'])('retires dependency-check permission during pending activity: %s', async mode => {
  let release!: (response: Response) => void;
  const fixture = setup(url => url.endsWith('/activity') ? new Promise(resolve => {release = resolve;}) : undefined);
  await screen.findByText('Graph-RAG: not configured');
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  const session = fixture.api.session;
  if (mode === 'session') fixture.api.session = {...session!};
  else fixture.redraw(false);
  await act(async () => release(response(session)));
  expect(fixture.fetcher.mock.calls.some(([url]) => url.endsWith('/readiness/check'))).toBe(false);
});

it.each([1, 5555, 5559, 65535])('decodes a bounded server-configured GR00T port %s', port => {
  const value = metadata(); value.policy_servers[0].port = port;
  expect(parseReadiness(value)).toEqual(value);
});

it.each([null, true, false, 0, -1, 65536, 5559.5, '5559', {}, [], NaN, Infinity])('rejects invalid readiness port %s', port => {
  const value = metadata();
  expect(() => parseReadiness({...value, policy_servers: [{...value.policy_servers[0], port}, value.policy_servers[1]]})).toThrow();
});

it('displays configured loopback readiness while keeping the check body endpoint-free', async () => {
  const value = metadata(); value.policy_servers[0].port = 5559;
  const fixture = setup(url => url.includes('/readiness') ? Promise.resolve(response(value)) : undefined);
  await screen.findByText('gr00t-droid: 127.0.0.1:5559 — not checked');
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/readiness/check'))).toHaveLength(1));
  expect(JSON.parse(fixture.fetcher.mock.calls.find(([url]) => url.endsWith('/readiness/check'))![1].body as string)).toEqual({});
});

it('rejects extra metadata and incompatible endpoint identities before caching', () => {
  expect(parseReadiness(metadata())).toEqual(metadata());
  expect(() => parseReadiness({...metadata(), secret: 'not-public'})).toThrow();
  const invalid = metadata(); invalid.policy_servers[0].host = 'other-host';
  expect(() => parseReadiness(invalid)).toThrow();
  const openpi = metadata(); openpi.policy_servers[1].port = 5559;
  expect(() => parseReadiness(openpi)).toThrow();
});

it.each(['session', 'provider', 'inactive'])('does not adopt a late dependency-check response after %s changes', async mode => {
  let release!: (response: Response) => void;
  const fixture = setup(url => url.endsWith('/readiness/check') ? new Promise(resolve => {release = resolve;}) : undefined);
  await screen.findByText('Graph-RAG: not configured');
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  if (mode === 'session') {fixture.api.session = {...fixture.api.session!}; fixture.redraw();}
  else if (mode === 'provider') fixture.redraw(true, 'replacement-reference');
  else fixture.redraw(false);
  await act(async () => release(response({...metadata(), checked_at: 123, graph: {configured: true, status: 'available'}})));
  if (mode === 'inactive') fixture.redraw();
  await screen.findByText('Graph-RAG: not configured');
  expect(screen.queryByText('Graph-RAG: database read verified')).not.toBeInTheDocument();
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/readiness/check'))).toHaveLength(1);
});

// Exact public shapes from readiness.metadata_v2/check_v2 and
// policy_readiness.probe_gr00t. These are HTTP transport fixtures, not live proof.
function v2Metadata(workflow = 'agentic_generation', provider = false) {
  const required = new Set(['api_contract', 'runtime', ...(workflow === 'graph_generation' ? ['generation_model', 'graph'] : workflow === 'agentic_generation' ? ['generation_model', 'graph', 'gpu'] : ['gpu']),
    ...(workflow === 'a2_gr00t' ? ['graph', 'policy_protocol', 'policy_model', 'policy_transport'] : []), ...(provider ? ['generation_model'] : [])]);
  return {schema_version: 2, workflow, checked_at: null as number | null,
    checks: ['api_contract', 'runtime', 'generation_model', 'graph', 'policy_protocol', 'policy_model', 'policy_transport', 'gpu'].map(id => ({
      id, required: required.has(id), status: id === 'api_contract' ? 'passed' : required.has(id) ? 'not_checked' : 'not_required',
      code: id === 'api_contract' ? 'api_contract_available' : !required.has(id) ? 'not_required'
        : ({runtime: 'runtime_not_checked', generation_model: 'generation_configuration_only', graph: 'graph_not_checked', gpu: 'resource_unknown'} as Record<string, string>)[id] ?? 'not_checked',
    })), policy: null as Record<string, unknown> | null, ready: false};
}
function v2Checked(workflow = 'agentic_generation', provider = false) {
  const value = v2Metadata(workflow, provider); value.checked_at = 123;
  const codes: Record<string, string> = {api_contract: 'api_contract_available', runtime: 'runtime_available', generation_model: 'generation_model_readable',
    graph: 'graph_retrieval_structural', policy_protocol: 'policy_protocol_available', policy_model: 'policy_model_verified',
    policy_transport: 'policy_transport_verified', gpu: 'resource_headroom_observed'};
  value.checks.forEach(row => {if (row.required && (row.id !== 'generation_model' || provider)) {row.status = 'passed'; row.code = codes[row.id];}});
  if (workflow === 'a2_gr00t') value.policy = {profile: 'gr00t-droid', expected_checkpoint: 'nvidia/GR00T-N1.6-DROID',
    instance_id: 'a'.repeat(32), checkpoint_sha256: 'b'.repeat(64), config_sha256: 'c'.repeat(64), serializer_sha256: 'd'.repeat(64),
    modalities_sha256: 'e'.repeat(64), inference: 'not_run'};
  value.ready = value.checks.filter(row => row.required).every(row => row.status === 'passed');
  return value;
}
function setupV2(handler?: (url: string, init: RequestInit) => Promise<Response> | undefined, strict = false) {
  const fetcher = vi.fn(async (url: string, init: RequestInit) => handler?.(url, init) ?? response(url.endsWith('/activity') ? api.session
    : url.endsWith('/check') ? v2Checked(JSON.parse(init.body as string).workflow, JSON.parse(init.body as string).check_provider)
    : v2Metadata(new URL(url, 'http://localhost').searchParams.get('workflow') ?? 'agentic_generation')));
  const api = new ApiClient(fetcher as typeof fetch);
  api.session = {session_id: 'test-session', csrf_token: 'test-csrf', expires_at: 9999999999};
  runtime.current = {api, session: api.session};
  const cache = new QueryClient({defaultOptions: {queries: {retry: false, gcTime: Infinity}}});
  let props = {active: true, providerRevision: 'session:reference', draft: 'scene: frozen\n', prompt: '  frozen task  ', documentId: 'f'.repeat(32), sourceIdentity: 'source-A'};
  const tree = () => {const child = <QueryClientProvider client={cache}><WorkflowReadiness {...props} /></QueryClientProvider>; return strict ? <StrictMode>{child}</StrictMode> : child;};
  const view = render(tree());
  return {...view, api, cache, fetcher, redraw: (change: Partial<typeof props> = {}) => {props = {...props, ...change}; view.rerender(tree());}};
}

it('offers one general generation-to-build readiness path with no scenario selector', async () => {
  const fixture = setupV2();
  await screen.findByText(/runtime_not_checked/);
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  expect(fixture.fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/editor/readiness?version=2&workflow=agentic_generation']);
  expect(screen.getByText(/Generation → inspect → build/)).toBeVisible();
  expect(screen.getByText(/Policy evaluation is separate and not required for generation or build/)).toBeVisible();
  expect(screen.getByRole('checkbox')).not.toBeChecked();
});

it('uses v2 metadata then explicitly checks the exact frozen editor input with provider reading off', async () => {
  const fixture = setupV2();
  await screen.findByText(/runtime_not_checked/);
  expect(fixture.fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/editor/readiness?version=2&workflow=agentic_generation']);
  expect(screen.getByRole('checkbox', {name: /authenticated provider-model metadata read/i})).not.toBeChecked();
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await screen.findByText('runtime_available');
  expect(screen.queryByText(/All requested dependency reads passed/)).not.toBeInTheDocument();
  const checks = fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check'));
  expect(checks).toHaveLength(1);
  expect(JSON.parse(checks[0][1].body as string)).toEqual({schema_version: 2, workflow: 'agentic_generation', check_provider: false,
    yaml_text: 'scene: frozen\n', prompt: '  frozen task  ', document_id: 'f'.repeat(32)});
  expect(checks[0][1].headers).toMatchObject({'X-CSRF-Token': 'test-csrf'});
  expect(screen.getByText(/Inference: not_run/)).toBeVisible();
  expect(screen.getByText(/Manual readiness does not authorize Evaluate/)).toBeVisible();
  expect(screen.queryByText('nvidia/GR00T-N1.6-DROID')).not.toBeInTheDocument();
  expect(screen.getByText('generation_configuration_only')).toBeVisible();
  expect(fixture.fetcher.mock.calls.some(([url]) => /\/(generate|build|evaluate|snapshots)$/.test(url))).toBe(false);
});

it('checks an arbitrary prompt without manufacturing a base source or a scenario', async () => {
  const fixture = setupV2(); await screen.findByText(/runtime_not_checked/);
  fixture.redraw({draft: undefined, documentId: undefined, prompt: '  G1 sorts unfamiliar objects by shape in a new workspace.  '});
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await screen.findByText('runtime_available');
  const checks = fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check'));
  expect(checks).toHaveLength(1);
  expect(JSON.parse(checks[0][1].body as string)).toEqual({schema_version: 2, workflow: 'agentic_generation', check_provider: false,
    prompt: '  G1 sorts unfamiliar objects by shape in a new workspace.  '});
  expect(fixture.fetcher.mock.calls.some(([url]) => /\/(generate|build|evaluate|snapshots|kill|reset)$/.test(url))).toBe(false);
});
it('rejects a retained provider-consented Check handler after consent off/on ABA', async () => {
  const fixture = setupV2(); await screen.findByText(/runtime_not_checked/);
  fireEvent.click(screen.getByRole('checkbox'));
  const button = screen.getByRole('button', {name: 'Check dependencies'});
  const key = Object.keys(button).find(key => key.startsWith('__reactProps$'))!;
  const click = (button as unknown as Record<string, {onClick: () => void}>)[key].onClick;
  fireEvent.click(screen.getByRole('checkbox')); fireEvent.click(screen.getByRole('checkbox'));
  await act(async () => click());
  expect(fixture.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
  fireEvent.click(button);
  await screen.findByText('generation_model_readable');
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check'))).toHaveLength(1);
});

it('never probes automatically on opt-in, focus, settings or refresh', async () => {
  const fixture = setupV2();
  await screen.findByText(/runtime_not_checked/);
  await screen.findByText('generation_configuration_only');
  const checkbox = screen.getByRole('checkbox', {name: /authenticated provider-model metadata read/i});
  fireEvent.click(checkbox);
  fireEvent.focus(window);
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check'))).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await screen.findByText('generation_model_readable');
  const checks = fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check'));
  expect(checks).toHaveLength(1);
  expect(JSON.parse(checks[0][1].body as string)).toMatchObject({workflow: 'agentic_generation', check_provider: true});
  const calls = fixture.fetcher.mock.calls.length;
  fixture.redraw({providerRevision: 'replacement'});
  expect(checkbox).not.toBeChecked();
  expect(screen.getByText(/Previous check is stale/)).toBeVisible();
  expect(fixture.fetcher.mock.calls).toHaveLength(calls);
  fireEvent.click(screen.getByRole('button', {name: 'Refresh readiness'}));
  await screen.findByText('generation_configuration_only');
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check'))).toHaveLength(1);
});

it.each(['draft', 'prompt', 'document', 'source', 'checkbox'])('retires pending provider consent before POST when %s changes', async mode => {
  let release!: (value: Response) => void;
  const fixture = setupV2(url => url.endsWith('/activity') ? new Promise(resolve => {release = resolve;}) : undefined);
  await screen.findByText(/runtime_not_checked/);
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  if (mode === 'checkbox') {fireEvent.click(screen.getByRole('checkbox')); fireEvent.click(screen.getByRole('checkbox'));}
  else fixture.redraw(mode === 'draft' ? {draft: 'scene: replacement'} : mode === 'prompt' ? {prompt: 'replacement'}
    : mode === 'document' ? {documentId: 'a'.repeat(32)} : {sourceIdentity: 'source-B'});
  await act(async () => release(response(fixture.api.session)));
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check'))).toHaveLength(0);
});

it.each(['draft', 'prompt', 'document', 'source', 'checkbox'])('withholds late checked evidence after %s changes', async mode => {
  let release!: (value: Response) => void;
  const fixture = setupV2(url => url.endsWith('/check') ? new Promise(resolve => {release = resolve;}) : undefined);
  await screen.findByText(/runtime_not_checked/);
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  if (mode === 'checkbox') {fireEvent.click(screen.getByRole('checkbox')); fireEvent.click(screen.getByRole('checkbox'));}
  else fixture.redraw(mode === 'draft' ? {draft: 'scene: replacement'} : mode === 'prompt' ? {prompt: 'replacement'}
    : mode === 'document' ? {documentId: 'a'.repeat(32)} : {sourceIdentity: 'source-B'});
  await act(async () => release(response(v2Checked())));
  expect(screen.queryByText('runtime_available')).not.toBeInTheDocument();
  expect(screen.queryByText(/All requested dependency reads passed/)).not.toBeInTheDocument();
  expect(screen.getByText(/Previous check is stale/)).toBeVisible();
});


it('retires an in-flight check on metadata invalidation even if identical metadata returns', async () => {
  let release!: (value: Response) => void;
  const fixture = setupV2(url => url.endsWith('/activity') ? new Promise(resolve => {release = resolve;}) : undefined);
  await screen.findByText(/runtime_not_checked/);
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  await act(async () => {await fixture.cache.invalidateQueries({queryKey: ['workflow-readiness-v2']});});
  await act(async () => release(response(fixture.api.session)));
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check'))).toHaveLength(0);
  expect(screen.getByText(/Previous check is stale/)).toBeVisible();
});
it.each([
  ['document', {documentId: 'bad-source'}], ['YAML bytes', {draft: 'é'.repeat(131073)}], ['prompt', {prompt: 'p'.repeat(16001)}],
] as const)('refuses inputs outside the backend readiness grammar: %s', async (_label, change) => {
  const fixture = setupV2(); await screen.findByText(/runtime_not_checked/);
  fixture.redraw(change);
  expect(screen.getByRole('button', {name: 'Check dependencies'})).toBeDisabled();
  expect(screen.getByText(/Readiness input is unavailable or exceeds server limits/)).toBeVisible();
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check'))).toHaveLength(0);
});

it.each(['session', 'provider', 'inactive', 'client'])('fences v2 activity and resets provider consent when %s ownership changes', async mode => {
  let release!: (value: Response) => void;
  const fixture = setupV2(url => url.endsWith('/activity') ? new Promise(resolve => {release = resolve;}) : undefined);
  await screen.findByText(/runtime_not_checked/);
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  const oldSession = fixture.api.session;
  if (mode === 'session') fixture.api.session = {...oldSession!}; // no React render before settlement
  if (mode === 'provider') fixture.redraw({providerRevision: 'replacement'});
  if (mode === 'inactive') {fixture.redraw({active: false}); fixture.redraw({active: true});}
  if (mode === 'client') {
    const api = new ApiClient(fixture.fetcher as typeof fetch); api.session = {...oldSession!};
    runtime.current = {api, session: api.session}; fixture.redraw();
  }
  await act(async () => release(response(oldSession)));
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check'))).toHaveLength(0);
  fixture.redraw();
  expect(screen.getByRole('checkbox')).not.toBeChecked();
});
it.each(['session', 'provider', 'inactive', 'client'])('drops late v2 checked evidence after %s retirement', async mode => {
  let release!: (value: Response) => void;
  const fixture = setupV2(url => url.endsWith('/check') ? new Promise(resolve => {release = resolve;}) : undefined);
  await screen.findByText(/runtime_not_checked/);
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  if (mode === 'session') fixture.api.session = {...fixture.api.session!};
  if (mode === 'provider') fixture.redraw({providerRevision: 'replacement'});
  if (mode === 'inactive') {fixture.redraw({active: false}); fixture.redraw({active: true});}
  if (mode === 'client') {
    const api = new ApiClient(fixture.fetcher as typeof fetch); api.session = {...fixture.api.session!};
    runtime.current = {api, session: api.session}; fixture.redraw();
  }
  await act(async () => release(response(v2Checked())));
  fixture.redraw();
  expect(screen.queryByText('runtime_available')).not.toBeInTheDocument();
  expect(screen.queryByText(/All requested dependency reads passed/)).not.toBeInTheDocument();
  expect(screen.getByText(/Previous check is stale/)).toBeVisible();
});
it.each(['v1', 'workflow', 'code', 'extra', 'consent'])('rejects mismatched v2 check responses without showing raw data: %s', async mode => {
  const result = v2Checked('agentic_generation', mode === 'consent');
  if (mode === 'workflow') result.workflow = 'build';
  if (mode === 'code') result.checks[0].code = 'synthetic-private-marker';
  const fixture = setupV2(url => url.endsWith('/check') ? Promise.resolve(response(mode === 'v1' ? metadata()
    : mode === 'extra' ? {...result, detail: 'synthetic-private-marker'} : result)) : undefined);
  await screen.findByText(/runtime_not_checked/);
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await screen.findByText('Dependency check unavailable. No work was submitted.');
  expect(screen.queryByText(/All requested dependency reads passed/)).not.toBeInTheDocument();
  expect(document.body.textContent).not.toContain('synthetic-private-marker');
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check'))).toHaveLength(1);
});
it('keeps replacement check evidence when a retired request fails late', async () => {
  const releases: ((value: Response) => void)[] = [];
  const fixture = setupV2(url => url.endsWith('/check') ? new Promise(resolve => {releases.push(resolve);}) : undefined);
  await screen.findByText(/runtime_not_checked/);
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(releases).toHaveLength(1));
  fixture.redraw({draft: 'scene: replacement'});
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(releases).toHaveLength(2));
  await act(async () => releases[1](response(v2Checked())));
  await screen.findByText('runtime_available');
  await act(async () => releases[0](response({detail: 'synthetic-private-marker'}, 500)));
  expect(screen.getByText('runtime_available')).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByRole('button', {name: 'Check dependencies'})).toBeEnabled();
});
it('observes current-session model settings retirement without issuing any settings or provider reads', async () => {
  let release!: (value: Response) => void;
  const fixture = setupV2(url => url.endsWith('/activity') ? new Promise(resolve => {release = resolve;}) : undefined);
  await screen.findByText(/runtime_not_checked/);
  const key = clientSessionScope(fixture.api, fixture.api.session).queryKey;
  fixture.cache.setQueryDefaults(key, {gcTime: Infinity});
  act(() => {fixture.cache.setQueryData(key, {source: 'server', provider: 'openai', model: 'gpt-4.1'});});
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(release).toBeTypeOf('function'));
  act(() => {void fixture.cache.invalidateQueries({queryKey: key, refetchType: 'none'});});
  await act(async () => release(response(fixture.api.session)));
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check') || url.endsWith('/model-settings'))).toHaveLength(0);
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  expect(screen.getByText(/Previous check is stale/)).toBeVisible();
});
it('keeps StrictMode metadata cancellation separate from one explicit provider-read request', async () => {
  const fixture = setupV2(undefined, true);
  await screen.findByText(/runtime_not_checked/);
  expect(fixture.fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await screen.findByText('generation_model_readable');
  expect(fixture.fetcher.mock.calls.filter(([url]) => url.endsWith('/check'))).toHaveLength(1);
});
it('keeps the constant general workflow usable after returning to cached metadata', async () => {
  const fixture = setupV2(); await screen.findByText(/runtime_not_checked/);
  fireEvent.click(screen.getByRole('checkbox'));
  fixture.redraw({active: false}); fixture.redraw({active: true});
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  expect(screen.getByRole('button', {name: 'Check dependencies'})).toBeEnabled();
  expect(fixture.fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/editor/readiness?version=2&workflow=agentic_generation']);
});
it.each(['v1', 'a2_gr00t', 'graph_generation', 'build'])('refuses old API metadata without scenario or v1 fallback: %s', async version => {
  const fixture = setupV2(url => url.includes('/readiness?') ? Promise.resolve(response(version === 'v1' ? metadata() : v2Metadata(version))) : undefined);
  await screen.findByText('Readiness metadata unavailable. Check the API connection.');
  expect(screen.getByRole('button', {name: 'Check dependencies'})).toBeDisabled();
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  expect(fixture.fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/editor/readiness?version=2&workflow=agentic_generation']);
});
