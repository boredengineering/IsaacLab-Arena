import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { MetadataBrowser } from './metadata-browser';

const runtime = vi.hoisted(() => ({ current: {} as { api: ApiClient; session: { session_id: string } | null; status: string } }));
vi.mock('./runtime', () => ({ useRuntime: () => runtime.current }));
const schema = { schema: { type: 'object' }, schema_sha256: 'schema-digest' };
const catalogues = { catalogues: { assets: { embodiments: Array.from({ length: 53 }, (_, i) => ({ name: `robot-${i}`, tags: ['mobile'] })) } } };
function setup(handler = async (url: string) => new Response(JSON.stringify(url.endsWith('/schema') ? schema : catalogues))) {
  const fetcher = vi.fn(handler);
  const api = new ApiClient(fetcher as typeof fetch);
  api.session = { session_id: 'one', csrf_token: 'csrf', expires_at: 9999999999 };
  runtime.current = { api, session: api.session, status: 'live' };
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = () => <QueryClientProvider client={cache}><MetadataBrowser /></QueryClientProvider>;
  const view = render(tree());
  return { ...view, fetcher, api, cache, redraw: () => view.rerender(tree()) };
}
it('does not display an obsolete response after session replacement', async () => {
  let resolve!: (value: Response) => void;
  const view = setup(async url => url.endsWith('/schema') ? new Promise<Response>(done => { resolve = done; }) : new Response(JSON.stringify(catalogues)));
  fireEvent.click(screen.getByRole('button', { name: 'Open schema and registries' }));
  await screen.findByRole('table');
  view.api.session = { session_id: 'two', csrf_token: 'next', expires_at: 9999999999 };
  runtime.current = { ...runtime.current, session: view.api.session };
  view.redraw();
  resolve(new Response(JSON.stringify(schema)));
  await waitFor(() => expect(view.cache.getQueryState(['metadata-schema', 'one'])?.status).toBe('success'));
  expect(screen.queryByText('schema-digest')).not.toBeInTheDocument();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(view.fetcher).toHaveBeenCalledTimes(2);
});
it('hides cached data immediately when the API session expires before runtime catches up', async () => {
  const view = setup();
  fireEvent.click(screen.getByRole('button', { name: 'Open schema and registries' }));
  await screen.findByText('schema-digest');
  view.api.expire();
  view.redraw();
  expect(screen.queryByText('schema-digest')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Open schema and registries' })).toBeDisabled();
});
it.each(['absent', 'expired', 'replacement'])('withholds private data at the %s session boundary', async boundary => {
  const view = setup();
  fireEvent.click(screen.getByRole('button', { name: 'Open schema and registries' }));
  await screen.findByText('schema-digest');
  runtime.current = { ...runtime.current, session: boundary === 'absent' ? null : boundary === 'replacement' ? { session_id: 'two' } : runtime.current.session, status: boundary === 'expired' ? 'expired' : 'live' };
  view.api.session = boundary === 'replacement' ? { session_id: 'two', csrf_token: 'next', expires_at: 9999999999 } : boundary === 'absent' ? null : view.api.session;
  view.redraw();
  expect(screen.queryByText('schema-digest')).not.toBeInTheDocument();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(view.fetcher).toHaveBeenCalledTimes(2);
  const open = screen.getByRole('button', { name: 'Open schema and registries' });
  if (boundary === 'replacement') {
    fireEvent.click(open);
    await screen.findByText('schema-digest');
    expect(view.fetcher).toHaveBeenCalledTimes(4);
  } else expect(open).toBeDisabled();
});
it('shows loading and honest errors, retrying only explicitly', async () => {
  let resolve!: (value: Response) => void;
  let failed = true;
  const view = setup(async url => url.endsWith('/schema') && failed ? new Promise<Response>(done => { resolve = done; }) : new Response(JSON.stringify(url.endsWith('/schema') ? schema : catalogues)));
  fireEvent.click(screen.getByRole('button', { name: 'Open schema and registries' }));
  expect(screen.getByText('Loading schema…')).toBeInTheDocument();
  resolve(new Response('{}', { status: 500 }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Schema could not be loaded');
  expect(view.fetcher).toHaveBeenCalledTimes(2);
  failed = false;
  fireEvent.click(screen.getByRole('button', { name: 'Retry schema' }));
  expect(await screen.findByText('schema-digest')).toBeInTheDocument();
  expect(view.fetcher).toHaveBeenCalledTimes(3);
});
it('uses the bounded schema property tree', async () => {
  const view = setup(async url => new Response(JSON.stringify(url.endsWith('/schema') ? { schema_sha256: 'bounded', schema: Object.fromEntries(Array.from({ length: 250 }, (_, i) => [`field-${i}`, 'x'.repeat(5000)])) } : catalogues)));
  fireEvent.click(screen.getByRole('button', { name: 'Open schema and registries' }));
  await screen.findByText('bounded');
  expect(view.container.querySelectorAll('[data-property-row]')).toHaveLength(101);
  expect(screen.queryByText('field-100')).not.toBeInTheDocument();
  expect(view.container.querySelector('pre')?.textContent?.length).toBe(1024);
  fireEvent.click(screen.getByRole('button', { name: 'Next properties page for Properties' }));
  expect(screen.getByText('field-100')).toBeInTheDocument();
});
it('renders malformed and hostile registry fields as bounded text, including relation and task metadata', async () => {
  const hostile = '<img src=x onerror=alert(1)>';
  const view = setup(async url => new Response(JSON.stringify(url.endsWith('/schema') ? schema : { catalogues: {
    assets: { embodiments: [null, { name: hostile, tags: ['tag', null, {}] }, { name: {}, tags: 'bad' }], backgrounds: null, objects: {} },
    relations: { relations: [{ name: 'near', unary: false, summary: 'relation summary' }, { name: 'alone', unary: true }] },
    tasks: { tasks: [{ name: 'pick', required_params: ['target'], summary: 'task summary' }] },
  } })));
  fireEvent.click(screen.getByRole('button', { name: 'Open schema and registries' }));
  expect(await screen.findByText(hostile)).toBeInTheDocument();
  expect(view.container.querySelector('img')).toBeNull();
  expect(screen.getByText('tag')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Filter registries'), { target: { value: 'tag' } });
  expect(screen.getByText('1 matching / 3 collected entries')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Filter registries'), { target: { value: '' } });
  for (const category of ['backgrounds', 'objects']) {
    fireEvent.change(screen.getByLabelText('Registry category'), { target: { value: category } });
    expect(screen.getByText('0 matching / 0 collected entries')).toBeInTheDocument();
  }
  fireEvent.change(screen.getByLabelText('Registry category'), { target: { value: 'relations' } });
  expect(screen.getByText('Binary')).toBeInTheDocument();
  expect(screen.getByText('Unary')).toBeInTheDocument();
  expect(screen.getByText('relation summary')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Registry category'), { target: { value: 'tasks' } });
  expect(screen.getByText('target')).toBeInTheDocument();
  expect(screen.getByText('task summary')).toBeInTheDocument();
});
it('paginates collected registries with literal filtering and resets category/filter pages', async () => {
  setup();
  fireEvent.click(screen.getByRole('button', { name: 'Open schema and registries' }));
  const table = await screen.findByRole('table');
  expect(within(table).getAllByRole('row')).toHaveLength(26);
  expect(screen.getByText('53 matching / 53 collected entries')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Next registry page' }));
  expect(screen.getByText('robot-25')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Filter registries'), { target: { value: 'robot-0' } });
  expect(screen.getByText('robot-0')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Previous registry page' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Filter registries'), { target: { value: '.*' } });
  expect(screen.getByText('0 matching / 53 collected entries')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Filter registries'), { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: 'Next registry page' }));
  fireEvent.change(screen.getByLabelText('Registry category'), { target: { value: 'tasks' } });
  expect(screen.getByRole('button', { name: 'Previous registry page' })).toBeDisabled();
});
it('does no work closed and explicitly opens two GET reads', async () => {
  const { fetcher } = setup();
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Open schema and registries' }));
  expect(await screen.findByText('schema-digest')).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls.map(call => call[0]).sort()).toEqual(['/api/editor/catalogues', '/api/editor/schema']);
  expect(fetcher.mock.calls.every(call => (call as unknown as [string, RequestInit])[1].method === 'GET')).toBe(true);
});
