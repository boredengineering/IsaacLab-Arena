import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { App } from './app';
import { ApiClient } from './api';

const response = (value: unknown) => new Response(JSON.stringify(value));
const yaml = 'env_name: same';
const validation = { valid: true, source_hash: 'source-a', canonical_hash: 'a'.repeat(64), errors: [], warnings: [],
  spec: {}, summary: 'Valid scene', graph: { nodes: [], edges: [] }, assets: [], relations: [], reified_relations: [], tasks: [] };
beforeEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); });
function setup({ operation = 'refine', retainedOperation = operation, inputHash = 'source-a', status = 'succeeded', result = true,
  late = false, validResult = true }: { operation?: string; retainedOperation?: string; inputHash?: string; status?: string; result?: boolean; late?: boolean; validResult?: boolean } = {}) {
  const job = { id: 'generated', kind: 'generate', workspace_id: 'default', status, stage: 'complete',
    inputs: { operation, base_yaml: yaml, document_id: 'frozen-a', input_hash: inputHash },
    result: result ? { yaml_text: 'env_name: candidate', validation: { ...validation, valid: validResult }, warnings: [] } : null,
    receipt: { yaml_text: 'env_name: receipt_only', validation } };
  sessionStorage.setItem('arena:editor:generate:v1', JSON.stringify({
    payload: { operation: retainedOperation, base_yaml: yaml, document_id: 'frozen-a', idempotency_key: 'retained' }, job,
  }));
  let resolveDocument: (value: Response) => void = () => {};
  const document = (id: string) => ({ document_id: `frozen-${id}`, source: `${id}.yaml`, yaml_text: yaml,
    source_hash: `source-${id}`, validation: { ...validation, source_hash: `source-${id}` } });
  const fetcher = vi.fn(async (url: string, init?: RequestInit): Promise<Response> => {
    if (url.endsWith('/health')) return response({ capabilities: { diagnostic: false } });
    if (url.endsWith('/sessions') || url.endsWith('/session/activity')) return response({ session_id: 's', csrf_token: 'csrf', expires_at: 9999999999 });
    if (url.endsWith('/workspaces/default')) return response({ id: 'default', name: 'Arena', jobs: [], event_cursor: 0 });
    if (url === '/api/editor') return response({ default_document_id: 'a', documents: ['a', 'b'].map(id => ({ id, name: id, source: `${id}.yaml` })),
      capabilities: { generation: true, generation_modes: true, snapshots: false }, limitations: [] });
    if (url.endsWith('/editor/documents/a')) return response(document('a'));
    if (url.endsWith('/editor/documents/b')) return late ? new Promise(resolve => { resolveDocument = resolve; }) : response(document('b'));
    if (url.endsWith('/jobs/generated')) return response(job);
    if (url.endsWith('/editor/validate')) return response(validation);
    return response({ detail: 'not installed' });
  });
  render(<App api={new ApiClient(fetcher as typeof fetch)} cache={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
    history={createMemoryHistory({ initialEntries: ['/'] })} makePort={() => null} />);
  return { fetcher, resolveDocument: () => resolveDocument(response(document('b'))) };
}
const apply = () => fireEvent.click(screen.getByRole('button', { name: 'Apply generated YAML' }));
it('allows explicit review and apply of a valid committed cancelled candidate without claiming success', async () => {
  setup({ status: 'cancelled' });
  await screen.findByText('Schema valid');
  expect(await screen.findByRole('button', { name: 'Apply generated YAML' })).toBeEnabled();
  expect(screen.getByText('Generation · cancelled')).toBeInTheDocument();
  expect(screen.getByText(/Committed candidate from a cancelled job/)).toHaveTextContent('not successful');
  apply();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('env_name: candidate');
  expect(screen.getByLabelText('Document')).toHaveValue('a');
});
it.each([{ result: false }, { validResult: false }])('does not infer a cancelled candidate from receipts or invalid results: %j', async (options) => {
  setup({ status: 'cancelled', ...options });
  await screen.findByText('Schema valid');
  expect(screen.queryByRole('button', { name: 'Apply generated YAML' })).not.toBeInTheDocument();
  expect(screen.queryByText('env_name: receipt_only')).not.toBeInTheDocument();
});
it.each(['new', 'refine'])('uses accepted %s operation rather than mismatched retained payload when applying', async (operation) => {
  const { fetcher } = setup({ operation, retainedOperation: operation === 'new' ? 'refine' : 'new' });
  await screen.findByText('Schema valid');
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
  apply();
  expect(screen.getByLabelText('Document')).toHaveValue(operation === 'new' ? 'local:new-environment' : 'a');
  expect(confirm).toHaveBeenCalledTimes(operation === 'new' ? 1 : 0);
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/editor/validate'))).toBe(true));
  const calls = fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate'));
  expect(JSON.parse(String(calls.at(-1)?.[1]?.body))).toEqual({ yaml_text: 'env_name: candidate',
    ...(operation === 'refine' ? { document_id: 'frozen-a' } : {}) });
});
it('displays the accepted active operation rather than retained mode', async () => {
  setup({ status: 'running', operation: 'refine', retainedOperation: 'new' });
  await screen.findByText('Schema valid');
  expect(screen.getByRole('radio', { name: 'Refine current environment' })).toBeChecked();
  expect(screen.queryByLabelText('Retrieval policy')).not.toBeInTheDocument();
});
it('treats a changed frozen input hash as a source change even with the same document and YAML', async () => {
  setup({ inputHash: 'other-includes' });
  await screen.findByText('Schema valid');
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  apply();
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('frozen inputs changed'));
  expect(screen.getByLabelText('Document')).toHaveValue('a');
  confirm.mockReturnValue(true);
  apply();
  expect(screen.getByLabelText('Document')).toHaveValue('local:new-environment');
});
it.each([false, true])('requires confirmation and detaches same-YAML foreign includes (late load: %s)', async (late) => {
  const { fetcher, resolveDocument } = setup({ late });
  await screen.findByText('Schema valid');
  fireEvent.change(screen.getByLabelText('Document'), { target: { value: 'b' } });
  if (!late) await screen.findByText('b.yaml');
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  apply();
  expect(confirm).toHaveBeenCalled();
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent(yaml);
  confirm.mockReturnValue(true);
  apply();
  expect(screen.getByLabelText('Document')).toHaveValue('local:new-environment');
  if (late) await act(async () => resolveDocument());
  expect(screen.getByRole('textbox', { name: 'YAML editor' })).toHaveTextContent('env_name: candidate');
  fireEvent.click(screen.getByRole('button', { name: 'Validate schema' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.endsWith('/editor/validate'))).toBe(true));
  const calls = fetcher.mock.calls.filter(([url]) => url.endsWith('/editor/validate'));
  expect(JSON.parse(String(calls.at(-1)?.[1]?.body))).toEqual({ yaml_text: 'env_name: candidate' });
});
