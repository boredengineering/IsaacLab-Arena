import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { EditorView as CodeMirrorView } from '@codemirror/view';
import { beforeEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { App } from './app';
import { ApiClient } from './api';

vi.mock('./graph-explorer/graph-explorer', () => ({ default: ({ graph, visible }: { graph: unknown; visible: boolean }) =>
  graph && visible ? <p>Explorer fixture</p> : null }));
const session = { session_id: 'graph-session', csrf_token: 'csrf', expires_at: 9999999999 };
const validation = { valid: true, source_hash: 'source', canonical_hash: 'canonical', errors: [], warnings: [], spec: {}, summary: 'fixture',
  graph: { nodes: [{ id: 'object', label: 'Object', role: 'object', properties: {} }], edges: [] }, assets: [], relations: [], reified_relations: [], tasks: [] };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function setup(path: string) {
  const fetcher = vi.fn(async (url: string) => {
    if (url.endsWith('/sessions')) return response(session);
    if (url.endsWith('/health')) return response({ status: 'ok', capabilities: {} });
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', jobs: [], event_cursor: 0 });
    if (url === '/api/editor') return response({ default_document_id: 'fixture', documents: [{ id: 'fixture', name: 'Fixture', source: 'fixture.yaml' }], capabilities: {}, limitations: [] });
    if (url.includes('/editor/documents/')) return response({ document_id: 'frozen', source: 'fixture.yaml', yaml_text: 'env_name: fixture', source_hash: 'source', validation });
    if (url === '/api/editor/validate') return response(validation);
    return response({ detail: 'not installed' }, 404);
  });
  const history = createMemoryHistory({ initialEntries: [path] });
  render(<App api={new ApiClient(fetcher as typeof fetch)} cache={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })} history={history} makePort={() => null} />);
  return { history, fetcher };
}
beforeEach(() => sessionStorage.clear());
it('switches the shared renderer through URL state without changing draft or unrelated filters', async () => {
  const { history, fetcher } = setup('/workspaces/default?filter=active&bookmark=graph%2Fnotes');
  await screen.findByRole('button', { name: 'Inspect Object' });
  const editor = screen.getByRole('textbox', { name: 'YAML editor' });
  const cm = CodeMirrorView.findFromDOM(editor)!;
  act(() => cm.dispatch({ changes: { from: cm.state.doc.length, insert: '\n# unsaved graph review' } }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Describe the environment and task' }), { target: { value: 'Unsubmitted prompt' } });
  await screen.findByRole('button', { name: 'Inspect Object' });
  const before = editor.textContent;
  const requests = fetcher.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: 'Try graph explorer' }));
  await screen.findByText('Explorer fixture');
  expect(history.location.search).toContain('graphRenderer=explorer');
  expect(history.location.search).toContain('filter=active');
  expect(new URLSearchParams(history.location.search).get('bookmark')).toBe('graph/notes');
  expect(editor.textContent).toBe(before);
  fireEvent.click(screen.getByRole('button', { name: 'Use legacy graph' }));
  await screen.findByRole('button', { name: 'Inspect Object' });
  expect(history.location.search).toContain('graphRenderer=legacy');
  expect(editor.textContent).toContain('unsaved graph review');
  expect(screen.getByRole('textbox', { name: 'Describe the environment and task' })).toHaveValue('Unsubmitted prompt');
  expect(fetcher.mock.calls.slice(requests)).toEqual([]);
});
it('accepts explicit explorer preview URLs and fails invalid choices back to legacy', async () => {
  const { history } = setup('/workspaces/default?graphRenderer=explorer');
  await screen.findByText('Explorer fixture');
  history.replace('/workspaces/default?graphRenderer=invalid');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Inspect Object' })).toBeInTheDocument());
});
