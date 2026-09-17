import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { createMemoryHistory } from '@tanstack/react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { ResearchServices } from './research-services';
import { ControlClient } from './control-api';
afterEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
import { App } from './app';
import { ApiClient } from './api';

const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
const revision = 'a'.repeat(64);
const metadata = () => ({schema_version: 1, profile_revision: revision, expected_policy: 'nvidia/GR00T-N1.6-DROID',
  services: ['arena', 'neo4j', 'gr00t'].map(id => ({id, status: 'stopped'})), api: 'stopped', startup_allowed: true, operation: null});
function mountCold(handler?: (url: string, init: RequestInit) => Promise<Response | undefined> | undefined) {
  const arena = vi.fn(async () => response({detail: 'API unavailable'}, 503));
  const control = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    return (await handler?.(url, init!)) ?? response(url === '/control/session'
      ? {schema_version: 1, csrf_token: 'c'.repeat(64), expires_at: 9999999999} : metadata());
  });
  vi.stubGlobal('fetch', control);
  const cache = new QueryClient({defaultOptions: {queries: {retry: false, gcTime: 0}}});
  const view = render(<App api={new ApiClient(arena as typeof fetch)} cache={cache}
    history={createMemoryHistory({initialEntries: ['/workspaces/default']})} makePort={() => null} />);
  return {...view, arena, control, cache};
}
it('retains ambiguous acceptance across remount and reconciles only the exact request with GET', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  let request: {request_id: string; profile_revision: string} | undefined;
  let disposition = 'wrong';
  const handler = async (url: string, init: RequestInit) => {
    if (url.endsWith('/start')) { request = JSON.parse(String(init.body)); throw new Error('synthetic-private-error'); }
    if (url.includes('?request_id=')) {
      if (disposition === 'missing') return response({error: 'request_not_found'}, 404);
      return response({...metadata(), operation: {...request, request_id: disposition === 'wrong' ? 'e'.repeat(32) : request!.request_id, status: 'completed', code: 'services_started'}});
    }
  };
  const first = mountCold(handler);
  fireEvent.click(await screen.findByRole('button', {name: 'Recover control session'}));
  await screen.findByText('arena: stopped');
  fireEvent.click(screen.getByRole('button', {name: 'Start approved services'}));
  await screen.findByText(/Start acceptance or readback is unresolved/);
  const raw = sessionStorage.getItem('arena.research-services.pending.v1');
  expect(JSON.parse(raw!)).toEqual(request);
  expect(raw).not.toMatch(/synthetic|c{64}/);
  expect(document.body.textContent).not.toContain('synthetic-private-error');
  first.unmount();
  const next = mountCold(handler);
  fireEvent.click(await screen.findByRole('button', {name: 'Recover control session'}));
  await screen.findByText('Control response could not be verified.');
  expect(sessionStorage.getItem('arena.research-services.pending.v1')).toBe(raw);
  disposition = 'missing';
  fireEvent.click(screen.getByRole('button', {name: 'Reconcile exact startup request'}));
  await screen.findByText(/Exact request not found/);
  expect(screen.getByRole('button', {name: 'Start approved services'})).toBeDisabled();
  disposition = 'exact';
  fireEvent.focus(window);
  fireEvent(document, new Event('visibilitychange'));
  fireEvent.click(screen.getByRole('button', {name: 'Reconcile exact startup request'}));
  await screen.findByText('Exact startup request completed. This is service startup only.');
  expect(sessionStorage.getItem('arena.research-services.pending.v1')).toBeNull();
  expect(next.control.mock.calls.some(([url]) => String(url).endsWith('/start'))).toBe(false);
});

it('allows GET-only recovery after verified completion cleanup fails without erasing retained identity', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  let request: {request_id: string; profile_revision: string} | undefined;
  mountCold(async (url, init) => {
    if (url.endsWith('/start')) { request = JSON.parse(String(init.body)); return response({...request, status: 'starting', code: 'starting'}, 202); }
    if (url.includes('?request_id=')) return response({...metadata(), operation: {...request, status: 'completed', code: 'services_started'}});
  });
  fireEvent.click(await screen.findByRole('button', {name: 'Recover control session'}));
  await screen.findByText('arena: stopped');
  const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new DOMException('synthetic-secret', 'SecurityError'); });
  fireEvent.click(screen.getByRole('button', {name: 'Start approved services'}));
  await screen.findByText(/Start acceptance or readback is unresolved/);
  remove.mockRestore();
  fireEvent.click(screen.getByRole('button', {name: 'Reconcile exact startup request'}));
  await screen.findByText('Exact startup request completed. This is service startup only.');
  expect(screen.getByRole('button', {name: 'Start approved services'})).toBeDisabled();
});

it('latches GET-only after lost-ACK remount cleanup fails even when later cleanup succeeds', async () => {
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  let request: {request_id: string; profile_revision: string} | undefined;
  const handler = async (url: string, init: RequestInit) => {
    if (url.endsWith('/start')) { request = JSON.parse(String(init.body)); throw new Error('lost ACK'); }
    if (url.includes('?request_id=')) return response({...metadata(), operation: {...request, status: 'completed', code: 'services_started'}});
  };
  const first = mountCold(handler);
  fireEvent.click(await screen.findByRole('button', {name: 'Recover control session'}));
  await screen.findByText('arena: stopped');
  fireEvent.click(screen.getByRole('button', {name: 'Start approved services'}));
  await screen.findByText(/Start acceptance or readback is unresolved/);
  const retained = sessionStorage.getItem('arena.research-services.pending.v1');
  expect(JSON.parse(retained!)).toEqual(request);
  first.unmount();
  const next = mountCold(handler);
  const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new DOMException('private cleanup failure', 'SecurityError'); });
  fireEvent.click(await screen.findByRole('button', {name: 'Recover control session'}));
  await screen.findByText(/Request retention unavailable or changed/);
  expect(sessionStorage.getItem('arena.research-services.pending.v1')).toBe(retained);
  remove.mockRestore();
  fireEvent.click(screen.getByRole('button', {name: 'Reconcile exact startup request'}));
  await screen.findByText('Exact startup request completed. This is service startup only.');
  expect(sessionStorage.getItem('arena.research-services.pending.v1')).toBeNull();
  expect(screen.getByRole('button', {name: 'Start approved services'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button', {name: 'Refresh service status'}));
  await screen.findByText('arena: stopped');
  expect(screen.getByRole('button', {name: 'Start approved services'})).toBeDisabled();
  expect(next.control.mock.calls.some(([url]) => String(url).endsWith('/start'))).toBe(false);
});

it('revokes control independently, clears the uncontrolled token and leaves Arena ownership unchanged', async () => {
  const fixture = mountCold(async (url, init) => {
    if (url === '/control/session' && init.method === 'DELETE') return response({schema_version: 1, revoked: true});
  });
  fireEvent.click(await screen.findByRole('button', {name: 'Recover control session'}));
  await screen.findByText('arena: stopped');
  const before = fixture.arena.mock.calls.length;
  const input = screen.getByLabelText('Control pairing token');
  fireEvent.change(input, {target: {value: 'synthetic-unsubmitted-secret'}});
  fireEvent.click(screen.getByRole('button', {name: 'End control session'}));
  await screen.findByText('Control session ended. Existing service requests were not cancelled.');
  expect(input).toHaveValue(''); expect(fixture.arena.mock.calls.length).toBe(before);
  expect(screen.getByRole('button', {name: 'Start approved services'})).toBeDisabled();
  const wire = fixture.control.mock.calls.find(([,init]) => init?.method === 'DELETE');
  expect(wire?.[1]).toMatchObject({body:'{}',headers:{'X-CSRF-Token':'c'.repeat(64)}});
});

it.each(['', '{"request_id":"'+'b'.repeat(32)+'","request_id":"'+'d'.repeat(32)+'","profile_revision":"'+revision+'"}'])('refuses malformed or duplicate retained identity without touching neighboring state: %s', async raw => {
  sessionStorage.setItem('arena.research-services.pending.v1', raw);
  sessionStorage.setItem('neighbor-draft', 'keep-exact');
  const fixture = mountCold();
  fireEvent.click(await screen.findByRole('button', {name: 'Recover control session'}));
  await screen.findByText(/Request retention unavailable or changed/);
  expect(screen.getByRole('button', {name: 'Start approved services'})).toBeDisabled();
  expect(fixture.control.mock.calls.filter(([url]) => String(url).includes('research-services'))).toHaveLength(0);
  expect(sessionStorage.getItem('arena.research-services.pending.v1')).toBe(raw);
  expect(sessionStorage.getItem('neighbor-draft')).toBe('keep-exact');
});

it('clears an unsubmitted pairing token immediately on refresh and on unmount', async () => {
  let hold = false; let finish!: (v:Response)=>void;
  const fixture = mountCold(async url => {
    if (url === '/control/research-services' && hold) return new Promise(resolve => { finish=resolve; });
  });
  fireEvent.click(await screen.findByRole('button', {name: 'Recover control session'}));
  await screen.findByText('arena: stopped');
  const input = screen.getByLabelText('Control pairing token');
  fireEvent.change(input, {target:{value:'synthetic-unsubmitted-secret'}});
  hold = true;
  fireEvent.click(screen.getByRole('button', {name:'Refresh service status'}));
  expect(input).toHaveValue('');
  await act(async () => { finish(response(metadata())); });
  fireEvent.change(input, {target:{value:'synthetic-unsubmitted-secret'}});
  fixture.unmount(); expect(input).toHaveValue('');
});

it('retains the exact request and reports expired pairing when Start returns unauthorized', async () => {
  vi.spyOn(window,'confirm').mockReturnValue(true);
  mountCold(async url => url.endsWith('/start') ? response({error:'unauthorized'},401) : undefined);
  fireEvent.click(await screen.findByRole('button', {name:'Recover control session'}));
  await screen.findByText('arena: stopped');
  fireEvent.click(screen.getByRole('button', {name:'Start approved services'}));
  await screen.findByText('Control pairing expired or was rejected. Pair or recover explicitly.');
  expect(sessionStorage.getItem('arena.research-services.pending.v1')).not.toBeNull();
  expect(screen.getByRole('button', {name:'Start approved services'})).toBeDisabled();
});

it('fences retained Start handlers across status refresh, owner replacement and confirmation', async () => {
  const wire = vi.fn(async (url: RequestInfo | URL) => response(String(url) === '/control/session' ? {schema_version:1,csrf_token:'c'.repeat(64),expires_at:9999999999} : metadata()));
  const client = new ControlClient(wire);
  const fixture = render(<ResearchServices client={client} />);
  fireEvent.click(screen.getByRole('button', {name:'Recover control session'}));
  await screen.findByText('arena: stopped');
  const node = screen.getByRole('button', {name:'Start approved services'});
  const key = Object.getOwnPropertyNames(node).find(k => k.startsWith('__reactProps$'))!;
  const oldClick = (node as unknown as Record<string,{onClick():void}>)[key].onClick;
  const confirm = vi.spyOn(window,'confirm').mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', {name:'Refresh service status'}));
  await screen.findByText('arena: stopped');
  act(() => oldClick()); expect(confirm).not.toHaveBeenCalled();
  confirm.mockImplementation(() => {client.retire(); return true;});
  fireEvent.click(screen.getByRole('button', {name:'Start approved services'}));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(wire.mock.calls.some(([url]) => String(url).endsWith('/start'))).toBe(false);
  const replacement = new ControlClient(wire);
  fixture.rerender(<ResearchServices client={replacement} />);
  act(() => oldClick());
  expect(wire.mock.calls.some(([url]) => String(url).endsWith('/start'))).toBe(false);
});

it('drops late old-owner pairing without clearing replacement-owner input or publishing status', async () => {
  let finish!: (v:Response)=>void;
  const oldWire = vi.fn(() => new Promise<Response>(resolve => {finish=resolve;}));
  const newWire = vi.fn(async () => response(metadata()));
  const fixture = render(<ResearchServices client={new ControlClient(oldWire)} />);
  fireEvent.click(screen.getByRole('button', {name:'Recover control session'}));
  fixture.rerender(<ResearchServices client={new ControlClient(newWire)} />);
  const input = screen.getByLabelText('Control pairing token');
  fireEvent.change(input,{target:{value:'synthetic-replacement-secret'}});
  await act(async () => {finish(response({schema_version:1,csrf_token:'d'.repeat(64),expires_at:9999999999}));});
  expect(input).toHaveValue('synthetic-replacement-secret');
  expect(screen.queryByText('arena: stopped')).not.toBeInTheDocument();
  expect(newWire).not.toHaveBeenCalled(); expect(oldWire).toHaveBeenCalledTimes(1);
});

it('keeps a validated in-memory request GET-only when tab storage becomes inaccessible', async () => {
  vi.spyOn(window,'confirm').mockReturnValue(true);
  let request: {request_id:string;profile_revision:string} | undefined;
  const fixture = mountCold(async (url,init) => {
    if (url.endsWith('/start')) {request=JSON.parse(String(init.body)); throw new Error('lost acknowledgement');}
    if (url.includes('?request_id=')) return response({...metadata(),operation:{...request,status:'completed',code:'services_started'}});
  });
  fireEvent.click(await screen.findByRole('button',{name:'Recover control session'}));
  await screen.findByText('arena: stopped');
  fireEvent.click(screen.getByRole('button',{name:'Start approved services'}));
  await screen.findByText(/Start acceptance or readback is unresolved/);
  const get = Storage.prototype.getItem;
  vi.spyOn(Storage.prototype,'getItem').mockImplementation(function(this:Storage,key:string) {
    if (key === 'arena.research-services.pending.v1') throw new DOMException('synthetic-private','SecurityError');
    return get.call(this,key);
  });
  fireEvent.click(screen.getByRole('button',{name:'Reconcile exact startup request'}));
  await screen.findByText('Exact startup request completed; local retention is unavailable. Keep this request for GET-only recovery.');
  expect(screen.getByRole('button',{name:'Start approved services'})).toBeDisabled();
  expect(fixture.control.mock.calls.filter(([url]) => String(url).endsWith('/start'))).toHaveLength(1);
  expect(fixture.control.mock.calls.filter(([url]) => String(url).includes('?request_id='))).toHaveLength(1);
});

it('shows an existing helper operation as observation, never adopting it as a new Start', async () => {
  const fixture = mountCold(async url => url === '/control/research-services' ? response({...metadata(),startup_allowed:false,operation:{request_id:'e'.repeat(32),profile_revision:revision,status:'unknown',code:'start_unknown'}}) : undefined);
  fireEvent.click(await screen.findByRole('button',{name:'Recover control session'}));
  await screen.findByText(/Observed helper operation: unknown · start_unknown/);
  expect(screen.getByRole('button',{name:'Start approved services'})).toBeDisabled();
  expect(sessionStorage.getItem('arena.research-services.pending.v1')).toBeNull();
  expect(fixture.control.mock.calls.some(([url]) => String(url).endsWith('/start'))).toBe(false);
});

it('prevents a retired reconciliation handler for F from removing a newer pending G', async () => {
  vi.spyOn(window,'confirm').mockReturnValue(true);
  const requests = new Map<string,{request_id:string;profile_revision:string}>();
  const fixture = mountCold(async (url,init) => {
    if (url.endsWith('/start')) {const target=JSON.parse(String(init.body)); requests.set(target.request_id,target); throw new Error('lost acknowledgement');}
    if (url.includes('?request_id=')) return response({...metadata(),operation:{...requests.get(url.split('=')[1]),status:'completed',code:'services_started'}});
  });
  fireEvent.click(await screen.findByRole('button',{name:'Recover control session'})); await screen.findByText('arena: stopped');
  fireEvent.click(screen.getByRole('button',{name:'Start approved services'})); await screen.findByText(/Start acceptance or readback is unresolved/);
  const node=screen.getByRole('button',{name:'Reconcile exact startup request'});
  const key=Object.getOwnPropertyNames(node).find(k=>k.startsWith('__reactProps$'))!;
  const oldClick=(node as unknown as Record<string,{onClick():void}>)[key].onClick;
  fireEvent.click(node); await screen.findByText('Exact startup request completed. This is service startup only.');
  fireEvent.click(screen.getByRole('button',{name:'Start approved services'})); await screen.findByText(/Start acceptance or readback is unresolved/);
  const raw=sessionStorage.getItem('arena.research-services.pending.v1');
  const reads=fixture.control.mock.calls.filter(([url])=>String(url).includes('?request_id=')).length;
  await act(async()=>oldClick());
  expect(fixture.control.mock.calls.filter(([url])=>String(url).includes('?request_id='))).toHaveLength(reads);
  expect(sessionStorage.getItem('arena.research-services.pending.v1')).toBe(raw);
});

it('requires explicit target confirmation and exact GET readback after Start in the mounted App', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  let request: {request_id: string; profile_revision: string} | undefined;
  const fixture = mountCold(async (url, init) => {
    if (url.endsWith('/start')) { request = JSON.parse(String(init.body)); return response({...request, status: 'starting', code: 'starting'}, 202); }
    if (url.includes('?request_id=')) return response({...metadata(), operation: {...request, status: 'completed', code: 'services_started'}});
  });
  const panel = await screen.findByRole('region', {name: 'Research stack'});
  fireEvent.change(within(panel).getByLabelText('Control pairing token'), {target: {value: 'synthetic-pairing-secret'}});
  fireEvent.click(within(panel).getByRole('button', {name: 'Pair control'}));
  await within(panel).findByText('arena: stopped');
  fireEvent.click(within(panel).getByRole('button', {name: 'Start approved services'}));
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining(revision));
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('nvidia/GR00T-N1.6-DROID'));
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('GPU'));
  expect(request).toBeUndefined();
  confirm.mockReturnValue(true);
  fireEvent.click(within(panel).getByRole('button', {name: 'Start approved services'}));
  await within(panel).findByText('Exact startup request completed. This is service startup only.');
  expect(request).toEqual({request_id: expect.stringMatching(/^[0-9a-f]{32}$/), profile_revision: revision});
  expect(fixture.control.mock.calls.filter(([url]) => String(url).endsWith('/start'))).toHaveLength(1);
  expect(fixture.control.mock.calls.some(([url]) => url === `/control/research-services?request_id=${request?.request_id}`)).toBe(true);
  expect(sessionStorage.getItem('arena.research-services.pending.v1')).toBeNull();
  confirm.mockRestore();
});

it('mounts independent control pairing in the actual cold API-down App without background Start or reconnect', async () => {
  const fixture = mountCold();
  const panel = await screen.findByRole('region', {name: 'Research stack'});
  const input = within(panel).getByLabelText('Control pairing token');
  expect(input).toHaveAttribute('type', 'password');
  fireEvent.change(input, {target: {value: 'synthetic-pairing-secret'}});
  fireEvent.click(within(panel).getByRole('button', {name: 'Pair control'}));
  await within(panel).findByText('arena: stopped');
  expect(input).toHaveValue('');
  expect(within(panel).getByRole('button', {name: 'Start approved services'})).toBeEnabled();
  const arenaBefore = fixture.arena.mock.calls.length;
  fireEvent.focus(window);
  fireEvent(document, new Event('visibilitychange'));
  fireEvent.click(within(panel).getByRole('button', {name: 'Refresh service status'}));
  await waitFor(() => expect(fixture.control.mock.calls.filter(([url]) => url === '/control/research-services').length).toBeGreaterThan(1));
  expect(fixture.arena.mock.calls.length).toBe(arenaBefore);
  expect(fixture.control.mock.calls.some(([url]) => String(url).includes('/start'))).toBe(false);
  expect(JSON.stringify(fixture.cache.getQueryCache().getAll().map(q => [q.queryKey, q.state.data]))).not.toMatch(/synthetic-pairing-secret|c{64}/);
  expect(fixture.cache.getMutationCache().getAll().some(m => JSON.stringify(m.state.variables)?.includes('synthetic-pairing-secret'))).toBe(false);
  expect(document.body.textContent).not.toContain('synthetic-pairing-secret');
});
