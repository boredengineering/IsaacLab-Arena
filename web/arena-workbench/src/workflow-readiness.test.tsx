import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { ApiClient } from './api';
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
  const tree = (active = true, providerRevision = 'none') => <QueryClientProvider client={cache}><WorkflowReadiness active={active} providerRevision={providerRevision} /></QueryClientProvider>;
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

it('rejects extra metadata and incompatible endpoint identities before caching', () => {
  expect(parseReadiness(metadata())).toEqual(metadata());
  expect(() => parseReadiness({...metadata(), secret: 'not-public'})).toThrow();
  const invalid = metadata(); invalid.policy_servers[0].host = 'other-host';
  expect(() => parseReadiness(invalid)).toThrow();
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
