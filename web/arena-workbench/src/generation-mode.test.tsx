import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { EditorView as CodeMirrorView } from '@codemirror/view';
import { App } from './app';
import { ApiClient } from './api';

const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const validation = { valid: true, source_hash: 'hash', canonical_hash: 'a'.repeat(64), errors: [], warnings: [],
  spec: {}, summary: 'Valid scene', graph: { nodes: [], edges: [] }, assets: [], relations: [], reified_relations: [], tasks: [] };
beforeEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); });
function setup(documents: 'loaded' | 'none' | 'loading' = 'loaded', modes = true, succeed = false, research = false) {
  const job = { id: 'generated', kind: 'generate', workspace_id: 'default', status: 'succeeded', stage: 'complete',
    inputs: { operation: 'new' }, result: { yaml_text: 'env_name: new', validation, warnings: [], prior_snapshot: { status: 'empty', priors: [], exact_context: '', warnings: [] } } };
  const fetcher = vi.fn(async (url: string, init?: RequestInit): Promise<Response> => {
    if (url.endsWith('/health')) return response({ capabilities: { diagnostic: false } });
    if (url.endsWith('/sessions') || url.endsWith('/session/activity')) return response({ session_id: 's', csrf_token: 'csrf', expires_at: 9999999999 });
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', jobs: [], event_cursor: 0 });
    if (url === '/api/editor') return response({ default_document_id: documents === 'none' ? '' : 'fixture',
      documents: documents === 'none' ? [] : [{ id: 'fixture', name: 'Fixture', source: 'fixture.yaml' }],
      capabilities: { generation: true, snapshots: false, neo4j: false, ...(modes ? { generation_modes: true } : {}), ...(research ? { research_versions: true } : {}) }, limitations: [] });
    if (url.includes('/editor/documents/')) {
      if (documents === 'loading') return new Promise(() => {});
      return response({ document_id: 'frozen-fixture', source: 'fixture.yaml', yaml_text: 'env_name: old', source_hash: 'hash', validation });
    }
    if (url.endsWith('/editor/validate')) return response({ ...validation, valid: !JSON.parse(String(init?.body)).yaml_text.includes('broken') });
    if (url.includes('/editor/previews/')) return response({ status: 'miss', canonical_hash: validation.canonical_hash, receipt: null });
    if (url.endsWith('/editor/generate')) return succeed ? response(job) : response({ detail: 'ambiguous request' }, 503);
    if (url.endsWith('/jobs/generated')) return response(job);
    return response({ detail: 'not installed' }, 404);
  });
  render(<App api={new ApiClient(fetcher as typeof fetch)} cache={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
    history={createMemoryHistory({ initialEntries: ['/'] })} makePort={() => null} />);
  return fetcher;
}
const payloads = (fetcher: ReturnType<typeof setup>) => fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/generate')).map(([, init]) => JSON.parse(String(init?.body)));
it.each([false, true])('gates managed versions behind capability without fetching before opening (%s)', async research => {
  const fetcher = setup('none', true, false, research);
  await screen.findByRole('radio', { name: 'New environment from prompt' });
  if (research) await screen.findByRole('button', { name: 'Open research versions' });
  else expect(screen.queryByRole('button', { name: 'Open research versions' })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.includes('/research/'))).toBe(false);
});
it('offers metadata inspection without fetching it before an explicit open', async () => {
  const fetcher = setup('none');
  await screen.findByRole('button', { name: 'Open schema and registries' });
  expect(fetcher.mock.calls.some(([url]) => /\/editor\/(schema|catalogues)$/.test(url))).toBe(false);
});
it('displays the returned retrieval receipt without issuing a graph query', async () => {
  const fetcher = setup('none', true, true);
  await screen.findByRole('radio', { name: 'New environment from prompt' });
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'A2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await screen.findByText('No eligible priors');
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', { name: 'Apply generated YAML' }));
  expect(screen.getByText('No eligible priors')).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.includes('/graph/'))).toBe(false);
});
it('backs up the detached new draft and recovers it explicitly without catalogue context', async () => {
  setup('loaded', true, true);
  await screen.findByText('Schema valid');
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'A new scene' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await screen.findByRole('button', { name: 'Apply generated YAML' });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', { name: 'Apply generated YAML' }));
  editYaml('env_name: new_unsaved');
  expect(JSON.parse(sessionStorage.getItem('arena.editor.draft.v1')!).draft).toBe('env_name: new_unsaved');
  confirm.mockReturnValue(false);
  fireEvent.change(screen.getByLabelText('Document'), { target: { value: 'fixture' } });
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('new_unsaved');
  cleanup();
  const fetcher = setup();
  await screen.findByRole('button', { name: 'Restore draft' });
  fireEvent.click(screen.getByRole('button', { name: 'Restore draft' }));
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('new_unsaved');
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
  await screen.findByText('Schema valid');
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/'))).toHaveLength(0);
  expect(payloads(fetcher)).toHaveLength(0);
  const request = fetcher.mock.calls.find(([url]) => url.endsWith('/editor/validate'))!;
  expect(JSON.parse(String(request[1]?.body))).toEqual({ yaml_text: 'env_name: new_unsaved' });
});
it('offers a read-only retrieval policy without claiming a GraphRAG receipt before evidence', async () => {
  const fetcher = setup();
  await screen.findByText('Schema valid');
  expect(screen.getByText('GraphRAG retrieval evidence pending · no retrieval claimed.')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Retrieval policy'), { target: { value: 'require_service' } });
  expect(payloads(fetcher)).toHaveLength(0);
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Use service' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await waitFor(() => expect(payloads(fetcher)).toHaveLength(1));
  expect(payloads(fetcher)[0]).toEqual({ prompt: 'Use service', operation: 'new', retrieval_policy: 'require_service', idempotency_key: expect.any(String) });
  expect(screen.getByLabelText('Retrieval policy')).toBeDisabled();
});
it('scopes required retrieval to New and preserves its choice across Refine submission', async () => {
  const fetcher = setup('loaded', true, true);
  await screen.findByText('Schema valid');
  fireEvent.change(screen.getByLabelText('Retrieval policy'), { target: { value: 'require_service' } });
  fireEvent.click(screen.getByRole('radio', { name: 'Refine current environment' }));
  expect(screen.queryByLabelText('Retrieval policy')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Refine' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await screen.findByRole('button', { name: 'Apply generated YAML' });
  expect(payloads(fetcher)[0]).toMatchObject({ operation: 'refine', retrieval_policy: 'allow_fallback' });
  fireEvent.click(screen.getByRole('radio', { name: 'New environment from prompt' }));
  expect(screen.getByLabelText('Retrieval policy')).toHaveValue('require_service');
});
it('leaves legacy payloads and controls unchanged without the capability', async () => {
  const fetcher = setup('loaded', false);
  await screen.findByText('Schema valid');
  expect(screen.queryByRole('radio', { name: 'New environment from prompt' })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Legacy' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await waitFor(() => expect(payloads(fetcher)).toHaveLength(1));
  expect(payloads(fetcher)[0]).toEqual({ prompt: 'Legacy', base_yaml: 'env_name: old', document_id: 'frozen-fixture', idempotency_key: expect.any(String) });
});
it.each(['loaded', 'loading'] as const)('applies a late new result with %s source only explicitly and validates without frozen includes or document identity', async (documents) => {
  const fetcher = setup(documents, true, true);
  await screen.findByRole('radio', { name: 'New environment from prompt' });
  if (documents === 'loaded') await screen.findByText('Schema valid');
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'A new scene' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await screen.findByRole('button', { name: 'Apply generated YAML' });
  fireEvent.click(screen.getByRole('radio', { name: 'Refine current environment' }));
  editYaml('env_name: untouched_until_apply');
  expect(screen.getByLabelText('Document')).toHaveValue('fixture');
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  fireEvent.click(screen.getByRole('button', { name: 'Apply generated YAML' }));
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('untouched_until_apply');
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', { name: 'Apply generated YAML' }));
  expect(screen.getByRole('option', { name: 'New environment', selected: true })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate')).length).toBeGreaterThan(0));
  const validations = fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate')).map(([, init]) => JSON.parse(String(init?.body)));
  expect(validations.at(-1)).toEqual({ yaml_text: 'env_name: new' });
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/editor/documents/')).map(([url]) => url)).toEqual(['/api/editor/documents/fixture']);
  await screen.findByText('Schema valid');
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Refine the new scene' } });
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await waitFor(() => expect(payloads(fetcher)).toHaveLength(2));
  expect(payloads(fetcher)[1]).toEqual({ operation: 'refine', prompt: 'Refine the new scene', base_yaml: 'env_name: new',
    retrieval_policy: 'allow_fallback', idempotency_key: expect.any(String) });
});
it('requires a valid refine base, preserves drafts on toggles and freezes unresolved retries', async () => {
  const fetcher = setup();
  await screen.findByText('Schema valid');
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Refine this' } });
  fireEvent.click(screen.getByRole('radio', { name: 'Refine current environment' }));
  editYaml('broken draft');
  expect(screen.getByRole('button', { name: 'Generate spec' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
  await screen.findByText('Schema errors');
  expect(screen.getByRole('button', { name: 'Generate spec' })).toBeDisabled();
  fireEvent.click(screen.getByRole('radio', { name: 'New environment from prompt' }));
  expect(screen.getByRole('button', { name: 'Generate spec' })).toBeEnabled();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('broken draft');
  expect(screen.getByLabelText('Describe the environment and task')).toHaveValue('Refine this');
  expect(payloads(fetcher)).toHaveLength(0);
  editYaml('env_name: revised');
  fireEvent.click(screen.getByRole('radio', { name: 'Refine current environment' }));
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
  await screen.findByText('Schema valid');
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await waitFor(() => expect(screen.getByRole('radio', { name: 'New environment from prompt' })).toBeDisabled());
  await screen.findByRole('button', { name: 'Retry generation request' });
  expect(payloads(fetcher)[0]).toEqual({ prompt: 'Refine this', operation: 'refine', retrieval_policy: 'allow_fallback',
    base_yaml: 'env_name: revised', document_id: 'frozen-fixture', idempotency_key: expect.any(String) });
  editYaml('broken later');
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'Later prompt' } });
  fireEvent.click(screen.getByRole('button', { name: 'Retry generation request' }));
  await waitFor(() => expect(payloads(fetcher)).toHaveLength(2));
  expect(payloads(fetcher)[1]).toEqual(payloads(fetcher)[0]);
});
function editYaml(text: string) {
  const view = CodeMirrorView.findFromDOM(screen.getByRole('textbox', { name: 'YAML editor' }))!;
  act(() => view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } }));
}
it.each(['loaded', 'none', 'loading'] as const)('defaults to prompt-only generation with %s documents', async (documents) => {
  const fetcher = setup(documents);
  expect(await screen.findByRole('radio', { name: 'New environment from prompt' })).toBeChecked();
  if (documents === 'loaded') await screen.findByText('Schema valid');
  fireEvent.change(screen.getByLabelText('Describe the environment and task'), { target: { value: 'A new scene' } });
  expect(payloads(fetcher)).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: 'Generate spec' }));
  await waitFor(() => expect(payloads(fetcher)).toHaveLength(1));
  expect(payloads(fetcher)[0]).toEqual({ prompt: 'A new scene', operation: 'new', retrieval_policy: 'allow_fallback', idempotency_key: expect.any(String) });
});
