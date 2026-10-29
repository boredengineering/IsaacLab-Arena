import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { App } from './app';
import { ApiClient } from './api';
import { PROVIDERS } from './model-settings-contracts';

vi.mock('./code-editor', () => ({ CodeEditor: ({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) => <textarea aria-label={label} value={value} onChange={event => onChange(event.target.value)} /> }));
const session = { session_id: 'f1-session', csrf_token: 'test-csrf', expires_at: 9999999999 };
const wire = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const validation = { valid: true, source_hash: 'source-hash', canonical_hash: 'a'.repeat(64), errors: [], warnings: [], spec: {}, summary: 'Unit fixture validation', graph: { nodes: [], edges: [] }, assets: [], relations: [], reified_relations: [], tasks: [] };
function setup(path = '/workspaces/default?filter=terminal&graphRenderer=legacy', jobs: unknown[] = []) {
 const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
  if (url.endsWith('/sessions') || url.endsWith('/session/activity')) return wire(session);
  if (url.endsWith('/health')) return wire({ status: 'ok', capabilities: { diagnostic: false, generation: false, preview: false } });
  if (url.endsWith('/workspaces/default')) return wire({ id: 'default', name: 'Workspace', jobs, event_cursor: 0 });
  if (url.endsWith('/model-settings')) return wire({ providers: PROVIDERS, configured: false, source: 'none', provider: null, model: null, expires_at: null, credential_ref: null, session_keys_allowed: false });
  if (url.endsWith('/editor')) return wire({ default_document_id: 'catalogue', documents: [{ id: 'catalogue', name: 'Fixture document', source: 'test.yaml' }], capabilities: { generation: false, generation_modes: true, snapshots: false, neo4j: false }, limitations: [] });
  if (url.includes('/editor/documents/')) return wire({ document_id: 'frozen-view', source: 'test.yaml', yaml_text: 'env_name: fixture\n', source_hash: 'source-hash', validation });
  if (url.endsWith('/editor/validate')) return wire({ ...validation, source_hash: 'source-hash' });
  if (url.includes('/editor/previews/')) return wire({ status: 'miss', canonical_hash: 'a'.repeat(64), receipt: null });
  if (url.endsWith('/graph/status')) return wire({ available: false, message: 'No graph in unit test' });
  if (url.endsWith('/graph/examples')) return wire({ queries: [] });
  return wire({ detail: 'not configured in unit fixture' }, 404);
 });
 const history = createMemoryHistory({ initialEntries: [path] });
 const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
 const api = new ApiClient(fetcher as typeof fetch);
 render(<App api={api} cache={cache} history={history} makePort={() => null} />);
 return { fetcher, history, cache, api };
}
beforeEach(() => { sessionStorage.clear(); localStorage.clear(); });

it('activates optional branded chrome without remounting the editor and rolls back explicitly', async () => {
 setup();
 await waitFor(() => expect(screen.getByLabelText('YAML editor')).toHaveValue('env_name: fixture\n'));
 const editor = screen.getByLabelText('YAML editor');
 fireEvent.click(screen.getByRole('button', { name: 'Try V7 layout' }));
 const brand = await screen.findByRole('img', { name: 'Cybernetic-Physics' });
 await waitFor(() => expect(brand.closest('.app-shell')).toHaveClass('workbench-v7'));
 expect(screen.getAllByRole('navigation', { name: 'Workspace navigation' })).toHaveLength(1);
 expect(screen.getByRole('switch', { name: 'Dark mode' }).closest('header')).not.toBeNull();
 expect(screen.getByLabelText('YAML editor')).toBe(editor);
 fireEvent.click(screen.getByRole('button', { name: 'Use legacy layout' }));
 await waitFor(() => expect(screen.queryByRole('img', { name: 'Cybernetic-Physics' })).not.toBeInTheDocument());
 expect(screen.getByLabelText('YAML editor')).toBe(editor);
 expect(screen.getByRole('switch', { name: 'Dark mode' }).closest('aside')).not.toBeNull();
});

it('mounts the real bounded-edit inspector over current validation in V7 without replacing the editor', async () => {
 const { fetcher } = setup();
 await waitFor(() => expect(screen.getByLabelText('YAML editor')).toHaveValue('env_name: fixture\n'));
 const editor = screen.getByLabelText('YAML editor');
 fireEvent.click(screen.getByRole('button', { name: 'Try V7 layout' }));
 expect(await screen.findByRole('region', { name: 'Authored inspector' })).toHaveAttribute('data-read-only', 'false');
 expect(screen.getByLabelText('Authored asset')).toBeVisible();
 expect(screen.getByText('Schema-valid · not runtime-validated')).toBeInTheDocument();
 expect(screen.getByLabelText('YAML editor')).toBe(editor);
 expect(fetcher.mock.calls.some(([url, init]) => init?.method === 'POST' && /generate|snapshots|save|publications/.test(url))).toBe(false);
});

it('does not put authorization-blocked work in the terminal filter', async () => {
 setup('/developer/diagnostics?filter=terminal', [{ id: 'blocked', workspace_id: 'default', kind: 'generate', status: 'blocked_authorization', stage: 'blocked', inputs: {}, created_at: 0, updated_at: 0, result: null, error: null, created_by_session_id: session.session_id }]);
 await screen.findByText('No jobs match this filter');
 expect(screen.queryByRole('link', { name: /generate blocked/ })).not.toBeInTheDocument();
 fireEvent.change(screen.getByLabelText('Filter jobs'), { target: { value: 'active' } });
 expect(await screen.findByRole('link', { name: /generate blocked/ })).toBeInTheDocument();
 expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
});

it('keeps legacy default and preserves URL filters/session through the explicit V7 layout choice', async () => {
 const { fetcher, history } = setup();
 await waitFor(() => expect(screen.getByLabelText('YAML editor')).toHaveValue('env_name: fixture\n'));
 fireEvent.change(screen.getByLabelText('YAML editor'), { target: { value: 'env_name: retained\n' } });
 const sessions = fetcher.mock.calls.filter(([url]) => url.endsWith('/sessions')).length;
 fireEvent.click(screen.getByRole('button', { name: 'Try V7 layout' }));
 await waitFor(() => expect(history.location.search).toContain('layout=v7'));
 expect(history.location.search).toContain('filter=terminal');
 expect(history.location.search).toContain('graphRenderer=legacy');
 fireEvent.click(screen.getByRole('button', { name: 'Use legacy layout' }));
 await waitFor(() => expect(history.location.search).not.toContain('layout=v7'));
 expect(screen.getByLabelText('YAML editor')).toHaveValue('env_name: retained\n');
 expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/sessions'))).toHaveLength(sessions);
 expect(fetcher.mock.calls.some(([url, init]) => init?.method === 'POST' && /generate|snapshots|save|publications/.test(url))).toBe(false);
});

it('keeps one editor controller and its refine inputs across query navigation', async () => {
 const { fetcher } = setup();
 await waitFor(() => expect(screen.getByLabelText('YAML editor')).toHaveValue('env_name: fixture\n'));
 const editor = screen.getByLabelText('YAML editor');
 fireEvent.change(editor, { target: { value: 'env_name: retained-navigation\n' } });
 fireEvent.click(screen.getByRole('link', { name: 'Neo4j query' }));
 await screen.findByRole('heading', { name: 'Neo4j query' });
 fireEvent.click(screen.getByRole('link', { name: 'Environment editor' }));
 await waitFor(() => expect(screen.getByLabelText('YAML editor')).toBeVisible());
 expect(screen.getByLabelText('YAML editor')).toBe(editor);
 expect(editor).toHaveValue('env_name: retained-navigation\n');
 expect(fetcher.mock.calls.some(([url, init]) => url.endsWith('/graph/query') && init?.method === 'POST')).toBe(false);
});

it('preserves layout and renderer choice through diagnostics navigation and filter changes', async () => {
 const { history } = setup('/workspaces/default?filter=terminal&graphRenderer=legacy&layout=v7');
 await screen.findByRole('button', { name: 'Use legacy layout' });
 fireEvent.click(screen.getByRole('link', { name: 'Jobs & diagnostics' }));
 await screen.findByLabelText('Filter jobs');
 expect(history.location.search).toContain('layout=v7');
 expect(history.location.search).toContain('graphRenderer=legacy');
 fireEvent.change(screen.getByLabelText('Filter jobs'), { target: { value: 'active' } });
 await waitFor(() => expect(history.location.search).toContain('filter=active'));
 expect(history.location.search).toContain('layout=v7');
 expect(history.location.search).toContain('graphRenderer=legacy');
});
