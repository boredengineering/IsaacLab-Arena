import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryHistory, createRootRoute, createRouter, RouterContextProvider } from '@tanstack/react-router';
import { EditorView as CodeMirrorView } from '@codemirror/view';
import { beforeEach, expect, it, vi } from 'vitest';
import { EditorView } from './editor';
import { ApiClient } from './api';
import { RuntimeProvider } from './runtime';
import { ThemeProvider } from './theme';
import type { DraftController } from './draft-controller';

beforeEach(() => sessionStorage.clear());
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
const yaml = 'env_name: readiness_editor\n';
const frozenId = 'a'.repeat(32);
const validation = {valid: true, source_hash: 'b'.repeat(64), canonical_hash: 'c'.repeat(64), errors: [], warnings: [],
  spec: {env_name: 'readiness_editor'}, summary: 'Fixture', graph: {nodes: [], edges: []}, assets: [], relations: [], reified_relations: [], tasks: []};
// Public metadata_v2 shape: no dependency reads are simulated as successful.
const metadata = {schema_version: 2, workflow: 'agentic_generation', checked_at: null, policy: null, ready: false,
  checks: [
    {id: 'api_contract', status: 'passed', code: 'api_contract_available', required: true},
    {id: 'runtime', status: 'not_checked', code: 'runtime_not_checked', required: true},
    {id: 'generation_model', status: 'not_checked', code: 'generation_not_configured', required: true},
    {id: 'graph', status: 'not_checked', code: 'graph_not_configured', required: true},
    {id: 'policy_protocol', status: 'not_required', code: 'not_required', required: false},
    {id: 'policy_model', status: 'not_required', code: 'not_required', required: false},
    {id: 'policy_transport', status: 'not_required', code: 'not_required', required: false},
    {id: 'gpu', status: 'not_checked', code: 'resource_unknown', required: true},
  ]};
function mount(holdActivity = false) {
  let release!: (value: Response) => void;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/health')) return response({capabilities: {diagnostic: false}});
    if (url.endsWith('/sessions')) return response({session_id: 's', csrf_token: 'csrf', expires_at: 9999999999});
    if (url.endsWith('/session/activity')) return holdActivity ? new Promise<Response>(resolve => {release = resolve;}) : response(api.session);
    if (url.endsWith('/workspaces/default')) return response({id: 'default', name: 'Arena', jobs: [], event_cursor: 0});
    if (url === '/api/editor') return response({default_document_id: 'fixture', documents: [{id: 'fixture', name: 'Fixture', source: 'tests/fixture.yaml'}],
      capabilities: {generation: false, snapshots: false, workflow_readiness: true}, limitations: []});
    if (url.includes('/editor/documents/')) return response({document_id: frozenId, source: 'tests/fixture.yaml', yaml_text: yaml, source_hash: 'b'.repeat(64), validation});
    if (url.endsWith('/editor/validate')) return response(validation);
    if (url.includes('/editor/readiness?')) return response(metadata);
    if (url.endsWith('/editor/readiness/check')) return response({...metadata, checked_at: 123});
    return response({detail: 'not installed in transport fixture'}, 404);
  });
  const api = new ApiClient(fetcher as typeof fetch);
  const cache = new QueryClient({defaultOptions: {queries: {retry: false, gcTime: 0}}});
  const router = createRouter({routeTree: createRootRoute(), history: createMemoryHistory()});
  const noPort = () => null;
  const view = render(<RouterContextProvider router={router}><QueryClientProvider client={cache}><ThemeProvider><RuntimeProvider api={api} makePort={noPort}><EditorView /></RuntimeProvider></ThemeProvider></QueryClientProvider></RouterContextProvider>);
  return {...view, api, cache, fetcher, release: () => release(response(api.session)), hasActivity: () => !!release};
}
async function loaded() {
  const node = await screen.findByRole('textbox', {name: 'YAML editor'});
  const editor = CodeMirrorView.findFromDOM(node)!;
  await waitFor(() => expect(editor.state.doc.toString()).toBe(yaml));
  await waitFor(() => expect(screen.getByRole('button', {name: 'Check dependencies'})).toBeEnabled());
  return editor;
}
it('wires readiness to the real editor frozen document, current YAML and literal prompt', async () => {
  const view = mount();
  const editor = await loaded();
  act(() => editor.dispatch({changes: {from: 0, to: editor.state.doc.length, insert: yaml + '# authored\n'}}));
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), {target: {value: '  literal prompt  '}});
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(view.fetcher.mock.calls.filter(([url]) => url.endsWith('/readiness/check'))).toHaveLength(1));
  const call = view.fetcher.mock.calls.find(([url]) => url.endsWith('/readiness/check'))!;
  expect(JSON.parse(String(call[1]?.body))).toEqual({schema_version: 2, workflow: 'agentic_generation', check_provider: false,
    yaml_text: yaml + '# authored\n', document_id: frozenId, prompt: '  literal prompt  '});
});
it('retires the real editor source during readiness activity even through prompt ABA', async () => {
  const view = mount(true); await loaded();
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(view.hasActivity()).toBe(true));
  const controller = view.cache.getQueryData<DraftController>(['editor-draft'])!;
  act(() => {controller.edit({prompt: 'intervening'}); controller.edit({prompt: ''});});
  await act(async () => view.release());
  expect(view.fetcher.mock.calls.filter(([url]) => url.endsWith('/readiness/check'))).toHaveLength(0);
  expect(screen.getByText(/Previous check is stale/)).toBeVisible();
});
it('retires the real editor readiness request on a same-ID session replacement before React renders', async () => {
  const view = mount(true); await loaded();
  fireEvent.click(screen.getByRole('button', {name: 'Check dependencies'}));
  await waitFor(() => expect(view.hasActivity()).toBe(true));
  view.api.session = {...view.api.session!};
  await act(async () => view.release());
  expect(view.fetcher.mock.calls.filter(([url]) => url.endsWith('/readiness/check'))).toHaveLength(0);
});
it('refuses a retained real-editor Check handler after synchronous authoring ABA', async () => {
  const view = mount(); await loaded();
  const button = screen.getByRole('button', {name: 'Check dependencies'});
  const propsKey = Object.keys(button).find(key => key.startsWith('__reactProps$'))!;
  const click = (button as unknown as Record<string, {onClick: () => void}>)[propsKey].onClick;
  const controller = view.cache.getQueryData<DraftController>(['editor-draft'])!;
  act(() => {controller.edit({prompt: 'intervening'}); controller.edit({prompt: ''}); click();});
  await act(async () => {});
  expect(view.fetcher.mock.calls.filter(([url]) => url.endsWith('/readiness/check') || url.endsWith('/activity'))).toHaveLength(0);
});
